#!/usr/bin/env python3
"""
Anchor GUI — Local web-based dashboard with full read/write access.

Starts a local HTTP server that serves the interactive dashboard and provides
API endpoints so that every click (done, add, capture) writes directly to
the markdown files, logs changes, and refreshes the state.

Usage:
    python3 anchor_gui.py          # Opens dashboard in your default browser
    python3 anchor_gui.py --port 8777   # Use a custom port

Launch from Cowork by typing "Dashboard" — Claude will run this for you.
"""

import json, logging, os, re, socket, sys, threading, time, traceback, webbrowser
from datetime import datetime, date
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote as url_quote, urlparse
import html as html_lib

# ── Paths ──────────────────────────────────────────────────────────────
# Single-folder layout (was previously dual-folder PSU + Axmra; consolidated 2026-05-02).
# Wave 2: data paths resolve via the shared `paths` helper, honoring the
# ANCHOR_DATA_DIR env var (unset -> the code dir, so behavior is unchanged).
import paths as _paths

# Process-wide write lock: held around every markdown/JSON mutation so two
# concurrent mutating requests (ThreadingHTTPServer) cannot lose an update.
WRITE_LOCK = _paths.WRITE_LOCK

# ANCHOR_DIR is the *code* dir (used for static assets like anchor.ico).
ANCHOR_DIR = _paths.CODE_DIR

DASHBOARD_MD = _paths.dashboard_md()
PROJECTS_MD = _paths.projects_md()
INBOX_MD = _paths.inbox_md()
DOMAINS_DIR = _paths.domains_dir()
LOGS_DIR = _paths.logs_dir()
CANCELLED_MD = _paths.cancelled_md()
SAVED_FOR_LATER_MD = _paths.saved_for_later_md()

# Ensure data dirs exist (logs/, domains/, health_reports/). This is the GUI's
# explicit call — directory creation is no longer an import-time side effect of
# the shared helper.
_paths.ensure_data_dirs()

# ── Error Logging ─────────────────────────────────────────────────────
ERROR_LOG = LOGS_DIR / "errors.log"
ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(ERROR_LOG),
    level=logging.ERROR,
    format="%(asctime)s — %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Also log INFO to the error log for server lifecycle events
_logger = logging.getLogger("anchor")
_logger.setLevel(logging.INFO)
# Guard against double-handler attach: if anchor_gui is imported more than once
# in the same interpreter (e.g. by anchor_healthcheck), only one FileHandler
# should remain on the logger. Also disable propagation so records don't also
# get written by the root logger's FileHandler (installed by basicConfig above)
# — that was producing duplicated lines in errors.log.
if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(ERROR_LOG)
           for h in _logger.handlers):
    _fh = logging.FileHandler(str(ERROR_LOG))
    _fh.setFormatter(logging.Formatter("%(asctime)s — %(levelname)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(_fh)
_logger.propagate = False


# ── Build identity (cache-bust) ────────────────────────────────────────
# Computed ONCE at process startup. Used by the self-healing client JS to
# detect a redeploy and force a cache-busting reload (and to kill any leftover
# service worker / Cache Storage left behind by an old Anchor build).
def _compute_build_id():
    import subprocess
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ANCHOR_DIR),
            capture_output=True, text=True, timeout=5,
        )
        rev = (out.stdout or "").strip()
        if out.returncode == 0 and rev:
            return rev
    except Exception:
        pass
    # Fallback: mtime of this source file (changes on every redeploy).
    try:
        return str(int(os.path.getmtime(__file__)))
    except Exception:
        return "0"


BUILD_ID = _compute_build_id()


# Self-healing cache-bust client JS. Kept as a plain (non-f) string so it can
# be embedded verbatim in BOTH the f-string dashboard page (generate_html) and
# the concatenated project-window page without brace-doubling concerns. The
# build id is substituted via a simple placeholder, not f-string formatting.
_CACHE_BUST_JS_TEMPLATE = """
(function () {
  try {
    window.__ANCHOR_BUILD__ = "__ANCHOR_BUILD_ID__";
    // Kill any leftover service worker registered by an OLD Anchor build.
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      navigator.serviceWorker.getRegistrations().then(function (rs) {
        rs.forEach(function (r) { try { r.unregister(); } catch (e) {} });
      }).catch(function () {});
    }
    // Best-effort: clear any stale Cache Storage entries.
    if (window.caches && caches.keys) {
      caches.keys().then(function (ks) {
        ks.forEach(function (k) { try { caches.delete(k); } catch (e) {} });
      }).catch(function () {});
    }
    function checkVersion() {
      fetch('/api/version', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var v = d && d.version;
          if (!v || v === window.__ANCHOR_BUILD__) return;
          // Loop guard: never reload more than once per server version.
          var key = 'anchor_reloaded_for';
          try {
            if (sessionStorage.getItem(key) === String(v)) return;
            sessionStorage.setItem(key, String(v));
          } catch (e) {}
          location.replace(location.pathname + '?v=' + encodeURIComponent(v));
        })
        .catch(function () {});
    }
    checkVersion();
    setInterval(checkVersion, 30000);
  } catch (e) {}
})();
"""


def cache_bust_script():
    """Return the inline cache-bust JS for the current BUILD_ID.

    No f-string formatting is used (the JS contains literal braces), so this is
    safe to drop into an f-string page as ``{cache_bust_script()}`` only after
    the result is a plain string — callers embed the returned string verbatim.
    """
    return _CACHE_BUST_JS_TEMPLATE.replace("__ANCHOR_BUILD_ID__", BUILD_ID)


# ── Parsing ────────────────────────────────────────────────────────────

#: Warnings from the most recent gather_all() — markdown files that could not
#: be read/parsed and were skipped so one bad file can't 500 the whole
#: dashboard. Best-effort, for diagnostics/tests and future UI surfacing. (The
#: daily healthcheck independently flags malformed files via its own strict
#: parse check.)
LAST_GATHER_WARNINGS = []


def _read_md_text(filepath):
    """Read a markdown file as text, resilient to non-UTF-8 bytes.

    Anchor always writes markdown as UTF-8, but a file edited by an external
    tool can arrive in another encoding (e.g. a Windows-1252 em-dash, byte
    0x97). A single such byte must never take down the dashboard: try strict
    UTF-8 first, and on a UnicodeDecodeError fall back to a lenient decode so
    the stray byte degrades to a replacement char instead of raising. The next
    write re-saves the file as clean UTF-8. The daily healthcheck still reads
    strictly, so a malformed file is still surfaced there for cleanup.
    """
    try:
        return filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return filepath.read_text(encoding="utf-8", errors="replace")


def parse_tasks_from_md(filepath):
    tasks = []
    if not filepath or not filepath.exists():
        return tasks
    text = _read_md_text(filepath)
    for line in text.splitlines():
        m = re.match(r'\s*-\s*\[([ xX])\]\s*\*?\*?(.*?)(?:\*?\*?\s*—\s*(.*))?$', line)
        if m:
            done = m.group(1).lower() == 'x'
            raw_text = m.group(2).strip().rstrip('*')
            meta = m.group(3) or ""
            pm = re.search(r'Priority:\s*(\d)', meta) or re.search(r'Priority:\s*(\d)', raw_text)
            priority = int(pm.group(1)) if pm else 2
            em = re.search(r'energy:\s*(\w+)', meta, re.I) or re.search(r'energy:\s*(\w+)', raw_text, re.I)
            energy = em.group(1).lower() if em else "med"
            dm = re.search(r'\[(\w+)\]', meta) or re.search(r'\[(\w+)\]', raw_text)
            domain = dm.group(1).lower() if dm else "personal"
            due_m = re.search(r'Due:\s*([\d/\-\w]+)', meta, re.I)
            due = due_m.group(1) if due_m else ""
            # Extract the optional Project: <id> field (Wave 3 task↔project link;
            # a no-op until Wave 9 — it must simply round-trip unchanged).
            proj_m = re.search(r'Project:\s*([^\s—]+)', meta, re.I)
            project = proj_m.group(1).strip() if proj_m else ""
            # Extract notes
            notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|Project|\[)|$)', meta, re.I)
            if not notes_m:
                notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
            notes = notes_m.group(1).strip().rstrip(' —') if notes_m else ""
            clean = re.sub(r'\s*—\s*Priority:.*', '', raw_text)
            clean = re.sub(r'\s*—\s*\[.*', '', clean)
            clean = re.sub(r'\s*—\s*energy:.*', '', clean, flags=re.I)
            clean = re.sub(r'\s*—\s*Notes:.*', '', clean, flags=re.I)
            clean = re.sub(r'\s*—\s*Project:.*', '', clean, flags=re.I)
            clean = clean.strip(' *')
            tasks.append({"text": clean, "done": done, "priority": priority,
                          "energy": energy, "domain": domain, "due": due,
                          "notes": notes, "project": project})
    return tasks


def serialize_task_line(task):
    """Serialize a parsed task dict back to its markdown line.

    Round-trips the Wave 3 ``project`` field (``Project: <id>``) unchanged so a
    task with a project link survives parse→serialize (a no-op until Wave 9).
    Field order mirrors :func:`add_task` so existing tasks serialize identically.
    """
    check = "x" if task.get("done") else " "
    text = task.get("text", "")
    priority = task.get("priority", 2)
    energy = task.get("energy", "med")
    domain = task.get("domain", "personal")
    due = task.get("due", "")
    notes = task.get("notes", "")
    project = task.get("project", "")
    due_str = f" — Due: {due}" if due else ""
    notes_str = f" — Notes: {notes}" if notes else ""
    project_str = f" — Project: {project}" if project else ""
    return (f"- [{check}] {text} — Priority: {priority} — energy: {energy} "
            f"— [{domain}]{due_str}{project_str}{notes_str}")


def parse_projects_from_md(filepath):
    projects = []
    if not filepath or not filepath.exists():
        return projects
    text = _read_md_text(filepath)
    current = None
    for line in text.splitlines():
        h2 = re.match(r'^##\s+(.+)', line)
        if h2:
            if current:
                projects.append(current)
            current = {"name": h2.group(1).strip(), "domain": "academic", "priority": 2,
                       "status": "active", "effort": "high", "due": "", "next": "",
                       "collabs": "", "notes": ""}
            continue
        if current:
            kv = re.match(r'\s*-\s*\*\*(\w[\w\s]*?):\*\*\s*(.*)', line)
            if kv:
                key = kv.group(1).strip().lower()
                val = kv.group(2).strip()
                if key == "domain":
                    current["domain"] = val.lower().split("+")[0].strip().split("/")[0].strip()
                elif key == "priority":
                    try: current["priority"] = int(val)
                    except: pass
                elif key == "status":
                    current["status"] = val.lower().split("—")[0].strip()
                elif key.startswith("next"):
                    current["next"] = val
                elif key == "collaborators":
                    current["collabs"] = val
                elif key == "notes":
                    current["notes"] = val
                elif key in ("effort", "effort level"):
                    current["effort"] = val.lower()
                elif key in ("deadline", "due"):
                    current["due"] = val
    if current:
        projects.append(current)
    return projects


def parse_inbox_from_md(filepath):
    items = []
    if not filepath or not filepath.exists():
        return items
    text = _read_md_text(filepath)
    for line in text.splitlines():
        m = re.match(r'\s*-\s*(\d{4}-\d{2}-\d{2}):\s*(.*?)(?:\s*\[(\w+)\])?\s*$', line)
        if m:
            items.append({"date": m.group(1), "text": m.group(2).strip(),
                          "domain": m.group(3) or ""})
    return items


def parse_archived_tasks(filepath):
    """Parse cancelled or saved-for-later tasks from their archive file."""
    items = []
    if not filepath or not filepath.exists():
        return items
    text = _read_md_text(filepath)
    for line in text.splitlines():
        m = re.match(r'\s*-\s*(\d{4}-\d{2}-\d{2}):\s*(.*?)(?:\s*—\s*\[(\w+)\])?(?:\s*—\s*P(\d))?(?:\s*—\s*Notes:\s*(.*))?$', line)
        if m:
            items.append({
                "date": m.group(1),
                "text": m.group(2).strip(),
                "domain": m.group(3) or "",
                "priority": int(m.group(4)) if m.group(4) else 2,
                "notes": m.group(5).strip() if m.group(5) else "",
            })
    return items


# ── Gather all data ────────────────────────────────────────────────────

def gather_all():
    """Read everything from both directories, return (projects, tasks, inbox)."""
    all_tasks = []
    seen = set()

    def _add(task_list, default_domain=None):
        for t in task_list:
            key = t["text"].lower().strip()[:60]
            if key not in seen:
                seen.add(key)
                if default_domain and t["domain"] == "personal":
                    t["domain"] = default_domain
                all_tasks.append(t)

    # Collect per-render warnings locally; a single unreadable/unparseable file
    # must be skipped (recorded here) rather than 500-ing the whole dashboard.
    # We accumulate into a local list and publish it atomically at the end, so
    # concurrent gather_all() calls (ThreadingHTTPServer) never observe a torn
    # mid-clear state of the module global.
    _warn = []

    def _safe(parse_fn, src, *, into, **kw):
        try:
            into(parse_fn(src), **kw)
        except Exception as e:  # one bad file can't take down every view
            _warn.append(f"{getattr(src, 'name', src)}: {e}")

    if DASHBOARD_MD.exists():
        _safe(parse_tasks_from_md, DASHBOARD_MD, into=_add)
    if DOMAINS_DIR.exists():
        for f in sorted(DOMAINS_DIR.glob("*.md")):
            _safe(parse_tasks_from_md, f, into=_add, default_domain=f.stem)

    projects = []
    seen_p = set()
    if PROJECTS_MD.exists():
        try:
            parsed_projects = parse_projects_from_md(PROJECTS_MD)
        except Exception as e:
            parsed_projects = []
            _warn.append(f"{PROJECTS_MD.name}: {e}")
        for p in parsed_projects:
            key = p["name"].lower().strip()[:60]
            if key not in seen_p:
                seen_p.add(key)
                projects.append(p)

    inbox = []
    if INBOX_MD.exists():
        try:
            inbox.extend(parse_inbox_from_md(INBOX_MD))
        except Exception as e:
            _warn.append(f"{INBOX_MD.name}: {e}")

    # Publish warnings atomically (slice-assign in place, no clear/append window).
    LAST_GATHER_WARNINGS[:] = _warn

    # Filter out synthetic health-check probes so they never appear in any view
    all_tasks = [t for t in all_tasks if "__healthcheck__" not in t["text"].lower()]
    inbox = [i for i in inbox if "__healthcheck__" not in i["text"].lower()]

    return projects, all_tasks, inbox


# ── Health report banner ──────────────────────────────────────────────

HEALTH_REPORTS_DIR = ANCHOR_DIR / "health_reports"


def latest_health_report():
    """Return (date_str, status, path) for the most recent health report, or None.

    status is "OK" or "ISSUES FOUND" (taken from the second non-blank line of the report).
    """
    if not HEALTH_REPORTS_DIR or not HEALTH_REPORTS_DIR.exists():
        return None
    reports = sorted(HEALTH_REPORTS_DIR.glob("*.md"), reverse=True)
    for r in reports:
        if r.name.lower() == "readme.md":
            continue
        try:
            text = r.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r'^Status:\s*(.+)$', text, re.MULTILINE)
        if m:
            status = m.group(1).strip()
            return (r.stem, status, r)
    return None


def _all_md_files():
    files = []
    if DASHBOARD_MD.exists():
        files.append(DASHBOARD_MD)
    if DOMAINS_DIR.exists():
        files.extend(sorted(DOMAINS_DIR.glob("*.md")))
    return files


# ── R&D control surface (Wave 3) ───────────────────────────────────────
# Thin id-keyed project registry + New Project flow + per-project store +
# folder-grouped projects view + single-instance project windows.

import rnd_registry as _rnd
import dir_browser as _dirb
import effort_history as _eh
import sessions as _sessions
import report_viewer as _rv
import summarizer as _summarizer
import deliverables as _deliv
import lanes as _lanes
import job_runner as _jr
import gate_adapter as _gate
import brownfield_scan as _bscan
import anchor_marker as _marker
import rnd_terminal as _term
import terminal_session as _termsess
import paths as _paths  # re-import alias (already imported above; harmless)


# ── Hand-rolled stdlib WebSocket frame codec (RFC 6455) — PURE functions ─────
# v3 "Mission Control" (MASTER-PLAN §D / Wave 3). The ConPTY terminal transport
# is a minimal hand-rolled WebSocket carrying PTY bytes both ways over the raw
# socket. The frame codec is factored into PURE, socket-free functions so it is
# unit-testable without a connection.
import base64 as _b64
import hashlib as _hashlib
import struct as _struct

#: The RFC 6455 GUID concatenated with the client key to derive the accept hash.
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# WebSocket opcodes.
WS_OP_CONT = 0x0
WS_OP_TEXT = 0x1
WS_OP_BINARY = 0x2
WS_OP_CLOSE = 0x8
WS_OP_PING = 0x9
WS_OP_PONG = 0xA


def ws_accept_key(client_key: str) -> str:
    """Compute the ``Sec-WebSocket-Accept`` value for a client key (RFC 6455).

    ``base64(sha1(client_key + WS_GUID))``. Pure + deterministic so it is
    unit-tested against the spec example
    (``dGhlIHNhbXBsZSBub25jZQ==`` -> ``s3pPLMBiTxaQ9kYGzzhZRbK+xOo=``).
    """
    digest = _hashlib.sha1(
        (client_key.strip() + WS_GUID).encode("ascii")).digest()
    return _b64.b64encode(digest).decode("ascii")


def encode_text_frame(text) -> bytes:
    """Encode a server->client TEXT frame (FIN=1, unmasked — server frames are
    never masked per RFC 6455)."""
    if isinstance(text, str):
        payload = text.encode("utf-8")
    else:
        payload = bytes(text)
    return _encode_frame(WS_OP_TEXT, payload)


def encode_close_frame(code=1000, reason=b"") -> bytes:
    """Encode a server->client CLOSE frame with an optional status code."""
    if isinstance(reason, str):
        reason = reason.encode("utf-8")
    payload = _struct.pack(">H", code) + reason if code is not None else b""
    return _encode_frame(WS_OP_CLOSE, payload)


def encode_pong_frame(payload=b"") -> bytes:
    """Encode a server->client PONG frame echoing the ping payload."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return _encode_frame(WS_OP_PONG, payload)


def _encode_frame(opcode, payload: bytes) -> bytes:
    """Build a single unmasked WebSocket frame (FIN=1) for ``opcode``+payload."""
    b0 = 0x80 | (opcode & 0x0F)            # FIN=1, opcode
    n = len(payload)
    if n < 126:
        header = _struct.pack(">BB", b0, n)
    elif n < (1 << 16):
        header = _struct.pack(">BBH", b0, 126, n)
    else:
        header = _struct.pack(">BBQ", b0, 127, n)
    return header + payload


#: Max bytes a single client frame's declared payload may be before the codec
#: signals a clean close instead of accumulating an unbounded inbuf. Also caps
#: the fragmentation-reassembly buffer (FIN=0 TEXT + CONTINUATION run).
MAX_WS_FRAME = 1 << 20  # 1 MiB

#: A pseudo-opcode the codec emits to tell the pump to close the connection on a
#: protocol error (oversized frame, unmasked client data frame, bad fragment).
#: It is NOT a real RFC 6455 opcode (0x10 is out of the 4-bit opcode range), so
#: it can never collide with a genuine decoded frame.
WS_SIGNAL_CLOSE = 0x10


def decode_frames(buf: bytes, state=None, require_mask=False):
    """Decode as many complete WebSocket frames as ``buf`` holds.

    Returns ``(messages, rest)`` where ``messages`` is a list of
    ``(opcode, payload_bytes)`` and ``rest`` is the trailing bytes of an
    incomplete frame to carry forward.

    ``decode_frames`` is dual-use: the pump decodes CLIENT frames (always masked)
    and tests decode SERVER frames (never masked). Pass ``require_mask=True``
    (the pump does) to enforce RFC 6455 §5.1 — an unmasked CLIENT frame is then a
    protocol error and yields a single ``(WS_SIGNAL_CLOSE, ...)`` message so the
    pump closes the connection. With ``require_mask=False`` (default) an unmasked
    frame's payload is taken verbatim (so server→client frames decode cleanly).

    Bounded (FIX 3): a frame whose DECLARED payload length exceeds
    :data:`MAX_WS_FRAME` yields ``(WS_SIGNAL_CLOSE, ...)`` instead of buffering
    toward an allocation — even before the payload bytes arrive.

    Fragmentation reassembly (FIX 6, RFC 6455 §5.4): a TEXT/BINARY frame with
    FIN=0 starts a message that is continued by CONTINUATION (opcode 0x0) frames
    and delivered as ONE message when a CONTINUATION arrives with FIN=1. Control
    frames (close/ping/pong) are delivered immediately and may interleave a
    fragmented data message. Reassembly state is carried in the optional
    ``state`` dict (the pump passes a persistent one); when ``state`` is None a
    transient one is used (single-buffer/backward-compatible call form). The
    reassembly buffer is itself bounded by :data:`MAX_WS_FRAME`.
    """
    if state is None:
        state = {}
    messages = []
    i = 0
    n = len(buf)
    while True:
        if n - i < 2:
            break
        b0 = buf[i]
        b1 = buf[i + 1]
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        j = i + 2
        if length == 126:
            if n - j < 2:
                break
            length = _struct.unpack(">H", buf[j:j + 2])[0]
            j += 2
        elif length == 127:
            if n - j < 8:
                break
            length = _struct.unpack(">Q", buf[j:j + 8])[0]
            j += 8
        # Reject an oversized DECLARED payload BEFORE waiting for/allocating it.
        if length > MAX_WS_FRAME:
            messages.append((WS_SIGNAL_CLOSE, b"frame too large"))
            return messages, b""
        is_control = bool(opcode & 0x8)
        # RFC 6455 §5.1: a client frame MUST be masked. When decoding client
        # frames (require_mask), an unmasked frame is a protocol error.
        if require_mask and not masked:
            messages.append((WS_SIGNAL_CLOSE, b"unmasked client frame"))
            return messages, b""
        mask = b""
        if masked:
            if n - j < 4:
                break
            mask = buf[j:j + 4]
            j += 4
        if n - j < length:
            break  # incomplete payload — wait for more bytes
        payload = bytearray(buf[j:j + length])
        if masked and mask:
            for k in range(length):
                payload[k] ^= mask[k & 3]
        payload = bytes(payload)
        i = j + length

        if is_control:
            # Control frames are never fragmented; deliver immediately, even mid
            # data-message reassembly.
            messages.append((opcode, payload))
            continue

        if opcode == WS_OP_CONT:
            if "frag_op" not in state:
                # CONTINUATION with no message in progress — protocol error.
                messages.append((WS_SIGNAL_CLOSE, b"unexpected continuation"))
                return messages, b""
            state["frag_buf"] = state.get("frag_buf", b"") + payload
            if len(state["frag_buf"]) > MAX_WS_FRAME:
                messages.append((WS_SIGNAL_CLOSE, b"fragmented message too large"))
                return messages, b""
            if fin:
                messages.append((state.pop("frag_op"), state.pop("frag_buf")))
            continue

        # A new TEXT/BINARY data frame.
        if not fin:
            # Start of a fragmented message.
            state["frag_op"] = opcode
            state["frag_buf"] = payload
            if len(state["frag_buf"]) > MAX_WS_FRAME:
                messages.append((WS_SIGNAL_CLOSE, b"fragmented message too large"))
                return messages, b""
            continue
        messages.append((opcode, payload))
    return messages, buf[i:]


def _unsafe_path_seg(seg: str) -> bool:
    """True if a URL segment is unsafe to use as a filesystem path component.

    Rejects path separators (``/`` ``\\``) and parent-dir traversal (``..``)
    before the value is used to build a filesystem path. Mirrors the
    path-traversal hardening on the vendored-KaTeX static route.
    """
    if seg is None:
        return False
    return "/" in seg or "\\" in seg or ".." in seg


# ── Vendored terminal-console static asset (Wave 7) ──────────────────────────
# The lightweight, dependency-free terminal console (anchor-term) is vendored
# exactly like KaTeX: a read-only static dir served traversal-safe under a URL
# prefix. It backs the interactive terminal that replaces the raw-log console.
ANCHOR_TERM_DIR = ANCHOR_DIR / "vendor" / "anchor-term"
ANCHOR_TERM_URL_PREFIX = "/vendor/anchor-term"
_ANCHOR_TERM_CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def anchor_term_asset(rel_path: str):
    """Resolve a ``/vendor/anchor-term/<rel>`` request to (bytes, content_type).

    Path-traversal safe (mirrors ``report_viewer.katex_asset``): the resolved
    file MUST stay within :data:`ANCHOR_TERM_DIR`. Returns ``None`` for a missing
    file or an escape attempt.
    """
    rel = rel_path.lstrip("/")
    target = (ANCHOR_TERM_DIR / rel).resolve()
    try:
        target.relative_to(ANCHOR_TERM_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = _ANCHOR_TERM_CONTENT_TYPES.get(target.suffix.lower(),
                                           "application/octet-stream")
    return target.read_bytes(), ctype


# ── Vendored xterm.js static asset (real terminal emulator) ──────────────────
# The interactive terminal canvas is a genuine xterm.js Terminal. xterm.js is
# pure browser JS (no native/compiled component), vendored offline as a plain
# static asset exactly like KaTeX. The anchor-term chrome (input line, gates,
# adopt panel) is layered on top via the anchor-term asset above.
XTERM_DIR = ANCHOR_DIR / "vendor" / "xterm"
XTERM_URL_PREFIX = "/vendor/xterm"


def xterm_asset(rel_path: str):
    """Resolve a ``/vendor/xterm/<rel>`` request to (bytes, content_type).

    Path-traversal safe (same containment pattern as :func:`anchor_term_asset`
    and ``report_viewer.katex_asset``): the resolved file MUST stay within
    :data:`XTERM_DIR`. Returns ``None`` for a missing file or an escape attempt.
    """
    rel = rel_path.lstrip("/")
    target = (XTERM_DIR / rel).resolve()
    try:
        target.relative_to(XTERM_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = _ANCHOR_TERM_CONTENT_TYPES.get(target.suffix.lower(),
                                           "application/octet-stream")
    return target.read_bytes(), ctype


# Single-instance project windows (Master Plan C2): opening a project that is
# already open returns the EXISTING instance id rather than spawning a duplicate.
# Server-side, process-local map {project_id: instance_id}. Guarded by the same
# process-wide write lock so concurrent opens resolve to one instance.
_project_instances = {}


def open_project_instance(project_id: str) -> dict:
    """Return the (single) window instance for a project, creating if needed.

    Re-opening an already-open project returns the same ``instance_id`` — no
    duplicate window (C2). Returns ``{project_id, instance_id, reused}``.
    """
    with WRITE_LOCK:
        existing = _project_instances.get(project_id)
        if existing is not None:
            return {"project_id": project_id, "instance_id": existing,
                    "reused": True}
        import uuid as _uuid
        inst = _uuid.uuid4().hex
        _project_instances[project_id] = inst
        return {"project_id": project_id, "instance_id": inst, "reused": False}


def close_project_instance(project_id: str) -> bool:
    """Forget a project's open instance (so a later open is fresh)."""
    with WRITE_LOCK:
        return _project_instances.pop(project_id, None) is not None


def _maybe_git_init(folder: Path) -> bool:
    """Optionally run ``git init`` in ``folder``. Best-effort, never raises.

    Returns True if git init was attempted and succeeded. Skipped silently if
    git is unavailable or the folder is already a repo.
    """
    try:
        import subprocess
        if (folder / ".git").exists():
            return False
        subprocess.run(["git", "init"], cwd=str(folder), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30)
        return True
    except Exception:
        return False


def create_new_folder_project(name: str, parent_path, priority: int = 2,
                              git_init: bool = False) -> dict:
    """+ New Project / create-new-folder mode.

    Creates ``<parent>/<name>`` (optional ``git init``), registers a project
    with a FRESH id, and scaffolds ``.anchor/projects/<id>/{lanes}/``. Returns
    the registry entry plus ``folder_created`` / ``git_initialized`` flags.
    """
    with WRITE_LOCK:
        parent = Path(parent_path).expanduser()
        folder = parent / name
        folder.mkdir(parents=True, exist_ok=True)
        git_done = _maybe_git_init(folder) if git_init else False
        entry = _rnd.add_project(name, str(folder), priority=priority,
                                 scaffold=True)
        log_change(f"R&D: created project '{name}' at {folder} (id {entry['id']})")
        try:
            discover_and_adopt(entry["id"])
        except Exception:
            pass
        return {"entry": entry, "folder_created": True,
                "git_initialized": git_done}


def select_existing_project(name: str, folder_path, priority: int = 2) -> dict:
    """+ New Project / select-existing mode.

    Registers the chosen folder as a project (fresh id, isolated store). Adding
    another project for a folder that already hosts projects is allowed
    (1 folder : N projects). A missing path still registers but surfaces a
    ``path-missing`` state on read (no crash).
    """
    with WRITE_LOCK:
        folder = Path(folder_path).expanduser()
        exists = folder.exists()
        entry = _rnd.add_project(name, str(folder), priority=priority,
                                 scaffold=exists)
        if not exists:
            # Don't fabricate a store under a missing path; mark it so the view
            # shows path-missing rather than crashing.
            entry = dict(entry)
            entry["state"] = _rnd.STATE_PATH_MISSING
        existing = _rnd.group_by_folder().get(str(folder), [])
        log_change(f"R&D: registered project '{name}' at {folder} (id {entry['id']})")
        # Brownfield: instantly discover + adopt any pre-existing trio artifacts
        # so the tile/Kanban/home panel populate from disk on register.
        if exists:
            try:
                discover_and_adopt(entry["id"])
            except Exception:
                pass
        return {"entry": entry, "path_exists": exists,
                "siblings_in_folder": [e for e in existing
                                       if e["id"] != entry["id"]]}


def discover_and_adopt(project_id: str) -> dict:
    """One brownfield pipeline: scan -> adopt -> reconcile -> write marker.

    Called from register (``add_project`` wiring), open (``GET /project/<id>``),
    and the manual Rescan (``POST /api/rnd/rescan``). Idempotent, bounded, and
    robust to a missing/huge/UNC/mistyped folder (returns a no-op report, never
    hangs/raises). Discovered records are reconciled (pruned when their artifact
    is gone); real efforts are never touched. The marker (``Anchor.md`` +
    sidecar) is rewritten ONLY when its structure changed (no-churn).

    Returns ``{"ok": bool, "scanned": <counts>, "adopt": <report>,
    "marker": <report>}``.
    """
    proj = _rnd.get_project(project_id)
    if proj is None:
        return {"ok": False, "reason": "unknown-project"}
    folder = (proj or {}).get("folder_path", "")
    try:
        if not folder or not Path(folder).is_dir():
            return {"ok": False, "reason": "path-missing"}
    except OSError:
        return {"ok": False, "reason": "path-missing"}

    scan = _bscan.scan(folder)
    adopt = _eh.adopt_discovered(folder, project_id, scan)
    # Reconcile is implicit in adopt (prunes stale discovered), but run an
    # explicit pass too so a deleted artifact whose lane vanished is pruned.
    _eh.reconcile_discovered(folder, project_id)
    # Folder-history unification (Wave 2, scope #1): also adopt trio sessions
    # found in OTHER project-ids' stores for the SAME folder, so a run recorded
    # under a sibling id is not invisible to this project. Non-destructive — the
    # sibling stores/ids are left intact (the explicit, reviewable
    # ``reconcile_folder`` is what folds + hard-deletes them).
    sibling = _eh.adopt_sibling_sessions(folder, project_id)
    marker = _marker.write_anchor_md(folder)
    # Wave 5 (v3): proactively (re)generate the accurate cached PROJECT summary
    # off the render path. We force a regenerate here so a rescan picks up new
    # plan docs / deliverables; the dashboard render only READS the cache.
    _trigger_project_summary(folder, project_id, force=True)
    # Wave 6 (v3): proactively generate per-session summaries that lack a cache,
    # so an expanded session accordion serves a ready cache rather than a
    # "generating…" fallback. Background + gated like the project summary.
    _trigger_project_session_summaries(folder, project_id)
    return {"ok": True, "scanned": dict(scan.counts), "adopt": adopt,
            "sibling_adopt": sibling, "marker": marker}


#: Proactive project-summary generation is OFF by default so importing the module
#: and calling endpoints in unit tests never spawns a background model job. The
#: live server turns it ON in ``main()``; a test can opt in via the env flag
#: ``ANCHOR_PROACTIVE_SUMMARY=1``. When OFF, summaries are still generated
#: lazily/on demand (and the render path always just reads the cache).
_PROACTIVE_SUMMARY_ENABLED = (
    os.environ.get("ANCHOR_PROACTIVE_SUMMARY", "").strip().lower()
    in ("1", "true", "yes", "on"))


def _trigger_project_summary(folder_path, project_id, force: bool = False):
    """Kick off proactive project-summary generation WITHOUT blocking the caller.

    Wave 5 (v3): the accurate cached project summary is generated proactively on
    rescan through the runner seam (``ANCHOR_RUNNER_CMD`` → never live claude),
    in a background daemon thread so the rescan/render path is never blocked by a
    model run. All errors are swallowed — a failed generation just leaves the row
    on its blurb fallback (and never poisons the cache, per summarizer FIX 2).

    No-op unless proactive generation is enabled (the live server enables it; see
    ``_PROACTIVE_SUMMARY_ENABLED``) so unit tests that merely register/open a
    project never spawn a background model job.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return
    # Snapshot the runner-seam env at TRIGGER time so a late daemon thread uses
    # the runner/counter configured now — not whatever the process env is when it
    # finally runs. (Forwarded to the spawned job via job_runner.launch(env=...).
    # In production this is just ANCHOR_RUNNER_CMD; in tests it also carries the
    # STUB_* vars so a leaked thread can't bump a later test's call counter.)
    runner_env = {k: v for k, v in os.environ.items()
                  if k == "ANCHOR_RUNNER_CMD" or k.startswith("STUB_")
                  or k.startswith("FAKE_")}

    def _run():
        try:
            _summarizer.summarize_project(folder_path, project_id, force=force,
                                          runner_env=(runner_env or None))
        except Exception:
            pass
    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


def _trigger_session_summary(folder_path, project_id, lane, session,
                             force: bool = False):
    """Kick off proactive SESSION-summary generation WITHOUT blocking (Wave 6).

    Mirror of ``_trigger_project_summary``: generates one session's cached,
    validated summary through the runner seam in a background daemon thread, so
    neither the render path nor the read-only ``/api/rnd/session_summary``
    endpoint ever blocks on a model run. No-op unless proactive generation is
    enabled (``_PROACTIVE_SUMMARY_ENABLED``) so unit tests that merely
    register/open a project never spawn a background model job. Errors are
    swallowed (a failed run never poisons the cache, per summarizer FIX 2).

    The runner-seam env is snapshotted at trigger time (same isolation rationale
    as the project-summary trigger) and forwarded to ``job_runner.launch``.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return
    runner_env = {k: v for k, v in os.environ.items()
                  if k == "ANCHOR_RUNNER_CMD" or k.startswith("STUB_")
                  or k.startswith("FAKE_")}
    if runner_env:
        os.environ.setdefault("_ANCHOR_SESS_SUMMARY_ENV", "1")

    def _run():
        try:
            # Forward the snapshotted runner env onto the spawned job for test
            # isolation. summarize_session resolves the runner from the process
            # env; in production this is just ANCHOR_RUNNER_CMD (already set).
            prev = {}
            for k, v in runner_env.items():
                prev[k] = os.environ.get(k)
                os.environ[k] = v
            try:
                _summarizer.summarize_session(folder_path, project_id, lane,
                                              session, force=force)
            finally:
                for k, old in prev.items():
                    if old is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = old
        except Exception:
            pass
    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


def _trigger_project_session_summaries(folder_path, project_id):
    """Proactively generate summaries for all of a project's sessions lacking a
    cache (Wave 6) — bounded, background, gated like the project-summary trigger.

    Walks each trio lane's sessions (skipping the defensive ``loose::`` wrappers),
    and for any session WITHOUT a cached summary kicks off a background
    generation. No-op unless ``_PROACTIVE_SUMMARY_ENABLED``. Best-effort: any
    error per lane/session is swallowed so a rescan is never blocked or broken.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return
    try:
        lanes = [c[0] for c in _KANBAN_COLUMNS if c[0] != "grass"]
    except Exception:
        lanes = ["research", "plan", "build", "deliverables"]
    for trio_lane in lanes:
        try:
            sess_list = _sessions.list_sessions(folder_path, project_id, trio_lane)
        except Exception:
            continue
        for s in sess_list:
            sid = (s.get("session_id") or "")
            if not sid or sid.startswith("loose::"):
                continue
            store_lane = _eh._resolve_subdir(trio_lane)
            try:
                if _summarizer.load_cached(folder_path, project_id, store_lane,
                                           sid) is not None:
                    continue
            except Exception:
                pass
            _trigger_session_summary(folder_path, project_id, trio_lane, s)


def render_status_line_html(project_id: str) -> str:
    """Render the per-lane SESSION summary line (Research/Planning/Build/Deliv).

    Wave 3 contract: ``rnd_registry.status_line`` returns per-lane counts +
    provenance, so the line reads e.g.
    ``Research: 1 · Planning: 2 (1 imported) · Build: 1 · Deliverables: 1`` —
    a lane with sessions NEVER renders as ``import`` or ``none-yet``. A lane with
    zero sessions shows a dimmed ``0``; an imported count adds a small
    ``(N imported)`` provenance chip; a live job adds ``• N running``.
    """
    line = _rnd.status_line(project_id)
    chips = []
    for lane in _rnd.STATUS_LANES:
        counts = line.get(lane) or {}
        n = int(counts.get("count", 0) or 0)
        n_imp = int(counts.get("imported", 0) or 0)
        n_run = int(counts.get("running", 0) or 0)
        label = lane.capitalize()
        prov = (f' <span class="rnd-imported">({n_imp} imported)</span>'
                if n_imp else '')
        run = (f' <span class="rnd-running">&bull; {n_run} running</span>'
               if n_run else '')
        dim = ' rnd-lane-empty' if n == 0 else ''
        chips.append(
            f'<span class="rnd-lane{dim}">'
            f'{html_lib.escape(label)}: {n}{prov}{run}</span>'
        )
    return '<div class="rnd-status-line">' + "".join(chips) + "</div>"


def _project_summary_text(entry: dict) -> tuple:
    """Return ``(summary_text, source)`` for a project's thin-row summary.

    Wave 5 (v3): the row's summary is the accurate CACHED project summary when
    present (``summarizer.load_cached_project`` — read-only, NEVER runs the model
    on the render path), else the existing blurb (seeded once from CLAUDE.md/
    README/Anchor.md), else "". ``source`` is ``"summary"`` | ``"blurb"`` | ``""``.
    """
    pid_raw = entry.get("id", "")
    folder = entry.get("folder_path", "")
    # 1. Cached project summary (read-only — no model run on the render path).
    if folder:
        try:
            cached = _summarizer.load_cached_project(folder, pid_raw)
            if cached:
                txt = (cached.get("summary_text") or "").strip()
                if txt:
                    return txt, "summary"
        except Exception:
            pass
    # 2. Fall back to the blurb (seed once if empty).
    blurb = entry.get("blurb", "") or ""
    if not blurb.strip():
        try:
            seeded = _rnd.seed_blurb(pid_raw)
            if seeded:
                blurb = seeded.get("blurb", "") or ""
        except Exception:
            pass
    if blurb.strip():
        return blurb.strip(), "blurb"
    return "", ""


def _project_status_dot(entry: dict, status_line: dict) -> str:
    """Pick the row's status-dot class (kept simple + documented, Wave 5).

    Mapping: green if ANY lane has a running session; for inactive projects
    (archived/future/retired) a dimmed grey; otherwise a neutral idle grey. The
    dot is purely advisory (the per-lane mini-counts carry the detail)."""
    state = entry.get("state", "active")
    if state in ("archived", "future", "retired"):
        return "rnd-dot-idle"
    try:
        if any(int((status_line.get(l) or {}).get("running", 0) or 0) > 0
               for l in status_line):
            return "rnd-dot-running"
    except Exception:
        pass
    return "rnd-dot-idle"


def render_project_tile_html(entry: dict) -> str:
    """Render a THIN, full-width project ROW (v3 Wave 5, IMPLEMENTATION-PLAN
    lines 124-141): ``name · accurate cached project summary · per-lane
    mini-counts · status dot``. Clicking the row opens the project window;
    lifecycle controls (P1/P2, rescan, blurb, notes, archive/retire/reactivate)
    moved OFF the row into a kebab/hover menu so the row stays one line. This
    REPLACES the old square ``.rnd-tile``."""
    pid_raw = entry.get("id", "")
    pid = html_lib.escape(pid_raw)
    name = html_lib.escape(entry.get("name", ""))
    pr = entry.get("priority", 2)
    state = html_lib.escape(entry.get("state", "active"))
    notes = entry.get("notes", "") or ""
    notes_attr = html_lib.escape(notes, quote=True)
    folder = entry.get("folder_path", "")

    # Row summary text: cached project summary, else blurb (read-only path).
    summary_text, _src = _project_summary_text(entry)
    summary_attr = html_lib.escape(summary_text, quote=True)
    summary_block = (f'<span class="rnd-row-summary" title="{summary_attr}">'
                     f'{html_lib.escape(summary_text)}</span>'
                     if summary_text else
                     '<span class="rnd-row-summary rnd-dim">No summary yet</span>')
    # data-blurb keeps the kebab "Blurb" prompt seeded with the editable blurb.
    blurb = entry.get("blurb", "") or ""
    blurb_attr = html_lib.escape(blurb, quote=True)

    # Per-lane mini-counts (compact form of the status line) + status dot.
    status = render_status_line_html(pid_raw)
    try:
        sline = _rnd.status_line(pid_raw)
    except Exception:
        sline = {}
    dot_cls = _project_status_dot(entry, sline)

    is_active = state in ("active", "path-missing")
    p1on = " rnd-pr-on" if pr == 1 else ""
    p2on = " rnd-pr-on" if pr == 2 else ""
    rescan_btn = (f'<button class="rnd-mini" onclick="rndRescan(\'{pid}\')" '
                  f'title="Re-scan the folder for trio artifacts">Rescan</button>')
    if is_active:
        lifecycle = (
            f'<button class="rnd-mini{p1on}" onclick="rndSetPriority(\'{pid}\',1)" title="Priority 1">P1</button>'
            f'<button class="rnd-mini{p2on}" onclick="rndSetPriority(\'{pid}\',2)" title="Priority 2">P2</button>'
            f'{rescan_btn}'
            f'<button class="rnd-mini" onclick="rndBlurb(\'{pid}\')" title="Edit blurb (what this project is)">Blurb</button>'
            f'<button class="rnd-mini" onclick="rndNotes(\'{pid}\')" title="Edit notes">Notes</button>'
            f'<button class="rnd-mini" onclick="rndArchive(\'{pid}\')" title="Archive (shelve, reviewable)">Archive</button>'
            f'<button class="rnd-mini rnd-danger" onclick="rndRetire(\'{pid}\')" title="Retire / cancel">Retire</button>'
        )
    else:
        lifecycle = (
            f'<button class="rnd-mini rnd-accent" onclick="rndReactivate(\'{pid}\')" title="Make active again">Reactivate</button>'
            f'{rescan_btn}'
            f'<button class="rnd-mini" onclick="rndBlurb(\'{pid}\')" title="Edit blurb (what this project is)">Blurb</button>'
            f'<button class="rnd-mini" onclick="rndNotes(\'{pid}\')" title="Edit notes">Notes</button>'
        )
    # Kebab menu holds all lifecycle controls so the row stays thin. The row
    # itself (click anywhere not on the kebab) opens the project window.
    kebab = (
        f'<div class="rnd-kebab" onclick="event.stopPropagation()">'
        f'<button class="rnd-kebab-btn" onclick="rndToggleKebab(event,\'{pid}\')" '
        f'title="Project actions" aria-label="Project actions">&#8942;</button>'
        f'<div class="rnd-kebab-menu" id="rnd-kebab-{pid}">'
        f'{lifecycle}'
        f'</div>'
        f'</div>'
    )
    return (
        f'<div class="rnd-row" data-project-id="{pid}" data-notes="{notes_attr}" '
        f'data-blurb="{blurb_attr}" tabindex="0" role="button" '
        f'onclick="openProjectWindow(\'{pid}\')" '
        f'title="Open {name}">'
        f'<span class="rnd-dot {dot_cls}" aria-hidden="true"></span>'
        f'<span class="rnd-name">{name}</span>'
        f'<span class="rnd-badge rnd-p{pr}">P{pr}</span>'
        f'<span class="rnd-badge rnd-state-{state}">{state}</span>'
        f'{summary_block}'
        f'<span class="rnd-row-counts">{status}</span>'
        f'{kebab}'
        f'</div>'
    )


def _render_folder_groups(groups: dict) -> str:
    """Render folder-grouped tiles (shared by the active + archive views)."""
    blocks = []
    for folder in sorted(groups):
        tiles = "".join(render_project_tile_html(e) for e in groups[folder])
        blocks.append(
            f'<details class="rnd-folder" open>'
            f'<summary class="rnd-folder-head">{html_lib.escape(folder)}'
            f' <span class="rnd-folder-count">'
            f'({len(groups[folder])})</span></summary>'
            f'<div class="rnd-folder-tiles rnd-folder-rows">{tiles}</div>'
            f'</details>'
        )
    return '<div class="rnd-projects">' + "".join(blocks) + '</div>'


def render_projects_view_html(include_archived: bool = False,
                              include_future: bool = False,
                              include_retired: bool = False) -> str:
    """Render the ACTIVE folder-grouped projects view (collapsible folder → tiles).

    Defaults to active-only; inactive projects (archived/future/retired) live on
    the separate Archive view (:func:`render_archive_view_html`).
    """
    groups = _rnd.group_by_folder(include_archived=include_archived,
                                  include_future=include_future,
                                  include_retired=include_retired)
    if not groups:
        return ('<div class="rnd-projects"><p class="rnd-empty">'
                'No active R&D projects. Use "+ New Project" to add one.</p></div>')
    return _render_folder_groups(groups)


def render_archive_view_html() -> str:
    """Render the Archive/Inactive view: archived + future + retired projects,
    each reactivatable (the tile shows a Reactivate button for inactive states)."""
    inactive = _rnd.list_inactive_projects()
    if not inactive:
        return ('<div class="rnd-projects"><p class="rnd-empty">'
                'No archived, future, or retired projects.</p></div>')
    groups = {}
    for e in inactive:
        groups.setdefault(e.get("folder_path", ""), []).append(e)
    return _render_folder_groups(groups)


# Kanban column wiring: which trio/store lanes map to each board column, the
# column's display label + glyph, and the "+ New run" affordance.
_KANBAN_COLUMNS = (
    ("research", "research", "Research", "\U0001F52C", "+ New research run"),
    ("plan", "planning", "Planning", "\U0001F4D0", "+ New plan run"),
    ("build", "build", "Build", "\U0001F528", "+ New build run"),
    ("deliverables", "deliverables", "Deliverables", "\U0001F4E6", "+ Add deliverable"),
    ("grass", "grass", "Grass Catchers", "\U0001F33F", "+ Add idea"),
)


def _fmt_age(created_at) -> str:
    """Compact relative age ("now", "5m", "2h", "3d", "1w") from an epoch ts."""
    try:
        ts = float(created_at or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    delta = max(0.0, time.time() - ts)
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    if delta < 604800:
        return f"{int(delta // 86400)}d"
    return f"{int(delta // 604800)}w"


# Map a job record's status/state to the board state-pill class + label.
def _effort_pill(status, gate_state):
    """Return ``(pill_class, pill_label, is_live, needs_input)`` for an effort."""
    if gate_state == "awaiting-input":
        return ("input", "needs input", True, True)
    if status == _jr.STATUS_RUNNING:
        return ("run", "running", True, False)
    if status == _jr.STATUS_DONE:
        return ("done", "done", False, False)
    if status in (_jr.STATUS_FAILED, _jr.STATUS_INTERRUPTED, _jr.STATUS_CANCELLED):
        label = "failed" if status == _jr.STATUS_FAILED else status
        return ("fail", label, False, False)
    return ("", status or "queued", False, False)


def _gather_project_efforts(folder_path, project_id):
    """Join each lane's effort pointer-records with their live job records.

    Returns ``{column_lane: [effort_view, ...]}`` newest-first, where an
    ``effort_view`` carries everything the board needs (already HTML-escaped
    where it lands in attributes/text) plus the live status/gate.
    """
    # Index job records by job_id for the live-status join (newest job wins on
    # duplicate ids, which never happens, but be defensive).
    jobs_by_id = {}
    for jr in _jr.list_records():
        jid = jr.get("job_id")
        if jid:
            jobs_by_id[jid] = jr
    out = {}
    for trio_lane, _subdir, _label, _glyph, _addlabel in _KANBAN_COLUMNS:
        try:
            efforts = _eh.list_efforts(folder_path, project_id, trio_lane)
        except Exception:
            efforts = []
        views = []
        # Version numbering (vN) is computed over NON-DISCOVERED (real) efforts
        # ONLY (honesty contract): a discovered card gets NO vN. So the newest
        # REAL effort is v<real_count>, descending; discovered cards are skipped
        # in the version counter and instead carry an "imported" marker.
        real_total = sum(1 for e in efforts if not _eh.is_discovered(e))
        real_seen = 0
        for idx, eff in enumerate(efforts):
            jid = eff.get("job_id", "")
            job = jobs_by_id.get(jid, {})
            discovered = _eh.is_discovered(eff)
            status = job.get("status") or eff.get("status") or ""
            gate_state = job.get("state")
            pill_cls, pill_lbl, is_live, needs_input = _effort_pill(
                status, gate_state)
            if discovered:
                # No vN; an "imported" marker instead. Discovered records are
                # never live and never link to a report viewer route.
                ver = ""
                is_live = needs_input = False
                pill_cls, pill_lbl = "", ""
            else:
                # Newest real effort = v<real_total>, descending by recency.
                real_seen += 1
                ver = f"v{real_total - real_seen + 1}" if real_total else "v1"
            skill = eff.get("skill") or job.get("skill") or ""
            seed = eff.get("prompt_seed") or ""
            hint = seed.strip().splitlines()[0] if seed.strip() else ""
            sub = " · ".join(p for p in (skill, hint) if p)
            # A manual/promoted Grass Catchers idea (Wave 5) carries its text as
            # the title; surface it so the card body shows the idea, not a blank.
            if not discovered and eff.get("kind") == "idea":
                idea_text = (eff.get("title") or "").strip()
                if idea_text:
                    sub = idea_text
            cost = (eff.get("cost") or {})
            cost_usd = float(cost.get("total_cost_usd", 0.0) or 0.0)
            views.append({
                "job_id": jid,
                "trio_lane": trio_lane,
                "ver": ver,
                "status": status,
                "pill_cls": pill_cls,
                "pill_lbl": pill_lbl,
                "is_live": is_live,
                "needs_input": needs_input,
                "is_done": (not discovered) and status == _jr.STATUS_DONE,
                "age": _fmt_age(eff.get("created_at")),
                "skill": skill,
                "sub": sub,
                "cost_usd": 0.0 if discovered else cost_usd,
                "discovered": discovered,
                "artifact_path": eff.get("artifact_path", "") if discovered else "",
                "title": eff.get("title", "") if discovered else "",
                "kind": eff.get("kind", "") if discovered else "",
            })
        out[trio_lane] = views
    return out


def _render_effort_card(ev, store_lane, project_id):
    """Render ONE effort card. Done efforts link to the report viewer; live ones
    carry the data hooks the console uses to attach. Every dynamic field is
    HTML-escaped (XSS-safe)."""
    jid = ev["job_id"]
    jid_esc = html_lib.escape(jid, quote=True)
    ver = html_lib.escape(ev["ver"])
    age = html_lib.escape(ev["age"])
    sub = html_lib.escape(ev["sub"]) if ev["sub"] else ""

    # ── Discovered (brownfield-imported) card: subtle, honest, no vN ──────────
    # It carries data-discovered="1" + a small dot + an "imported" marker, and
    # links to the REAL on-disk file via /artifact/<pid>?path=<rel>. It is NEVER
    # masqueraded as an Anchor-run session (no vN, no cost, no live hooks).
    if ev.get("discovered"):
        rel = ev.get("artifact_path", "")
        title = ev.get("title", "") or rel
        kind = ev.get("kind", "")
        title_esc = html_lib.escape(title)
        kind_esc = html_lib.escape(kind)
        data = (
            f" data-job-id=\"{jid_esc}\""
            f" data-lane=\"{html_lib.escape(store_lane, quote=True)}\""
            f" data-trio-lane=\"{html_lib.escape(ev['trio_lane'], quote=True)}\""
            f" data-discovered=\"1\" data-live=\"0\""
            f" data-artifact-path=\"{html_lib.escape(rel, quote=True)}\""
        )
        marker = ("<span class='imported'><span class='dotdisc'></span>"
                  "imported</span>")
        inner = (
            f"<div class='er'>{marker}"
            f"<span class='age'>{age}</span></div>"
            f"<div class='sub'>{title_esc}"
            + (f" <span class='dkind'>{kind_esc}</span>" if kind_esc else "")
            + "</div>"
        )
        if rel:
            href = (f"/artifact/{html_lib.escape(project_id, quote=True)}"
                    f"?path={url_quote(rel, safe='')}")
            return (f"<div class='effort discovered'{data} "
                    f"onclick=\"openReport('{html_lib.escape(href, quote=True)}')\">"
                    f"{inner}</div>")
        return f"<div class='effort discovered'{data}>{inner}</div>"

    pill = ""
    if ev["pill_cls"]:
        dot = ""
        if ev["pill_cls"] == "run":
            dot = "<span class='dotpulse'></span>"
        elif ev["pill_cls"] == "input":
            dot = "<span class='dotwarn'></span>"
        pill = (f"<span class='statepill {ev['pill_cls']}'>{dot}"
                f"{html_lib.escape(ev['pill_lbl'])}</span>")
    cost_bit = ""
    if ev["cost_usd"] > 0:
        cost_bit = (f"<span class='ecost'>${ev['cost_usd']:.4f}</span>")
    # Classes + data hooks. A live/needs-input card is clickable to attach the
    # console; a done card links to its report.
    cls = "effort"
    data = (f" data-job-id=\"{jid_esc}\" data-lane=\"{html_lib.escape(store_lane, quote=True)}\""
            f" data-trio-lane=\"{html_lib.escape(ev['trio_lane'], quote=True)}\""
            f" data-ver=\"{ver}\" data-live=\"{'1' if ev['is_live'] else '0'}\"")
    inner = (
        f"<div class='er'><span class='ver'>{ver}</span>{pill}"
        f"<span class='age'>{age}</span></div>"
        + (f"<div class='sub'>{sub}{cost_bit}</div>" if (sub or cost_bit) else "")
    )
    if ev["is_done"] and jid:
        # Link a done effort to the report viewer route.
        href = (f"/report/{html_lib.escape(project_id, quote=True)}/"
                f"{html_lib.escape(ev['trio_lane'], quote=True)}/{jid_esc}")
        return (f"<div class='{cls}'{data} onclick=\"openReport('{href}')\">"
                f"{inner}</div>")
    if ev["is_live"] and jid:
        return (f"<div class='{cls}' id='effort_{jid_esc}'{data} "
                f"onclick=\"attachSession('{jid_esc}')\">{inner}</div>")
    return f"<div class='{cls}'{data}>{inner}</div>"


def _gather_project_sessions(folder_path, project_id, efforts_by_lane=None):
    """Group each lane's effort views into SESSIONS (v2 Wave 4, MASTER-PLAN §A).

    Wraps :func:`sessions.list_sessions` (Wave 1) — one trio run = one session —
    and joins each session to the per-effort views produced by
    :func:`_gather_project_efforts`. Returns ``{trio_lane: [session_view, ...]}``
    newest-first, where a ``session_view`` is::

        {"session_id", "members": [effort_view, ...]}

    ``members`` are the session's effort views, newest-first (the representative
    card = ``members[0]``). Member views not found (defensive) are skipped.
    """
    if efforts_by_lane is None:
        efforts_by_lane = _gather_project_efforts(folder_path, project_id)
    out = {}
    for trio_lane, _subdir, _label, _glyph, _addlabel in _KANBAN_COLUMNS:
        views = efforts_by_lane.get(trio_lane, [])
        # Index this lane's effort views by job_id for the session→view join.
        by_jid = {}
        for v in views:
            jid = v.get("job_id") or ""
            by_jid.setdefault(jid, v)
        try:
            sess_list = _sessions.list_sessions(folder_path, project_id, trio_lane)
        except Exception:
            sess_list = []
        session_views = []
        claimed = set()
        for s in sess_list:
            members = []
            for m in s.get("member_files", []):
                jid = (m.get("job_id") or "").strip()
                v = by_jid.get(jid)
                if v is not None:
                    members.append(v)
                    claimed.add(jid)
            if not members:
                continue
            # Keep members newest-first (the effort views already arrive
            # newest-first from list_efforts; preserve that ordering).
            session_views.append({
                "session_id": s.get("session_id", ""),
                "members": members,
            })
        # Defensive: surface any effort view not claimed by a session as its own
        # single-member session so nothing silently disappears from the board.
        for v in views:
            jid = v.get("job_id") or ""
            if jid not in claimed:
                claimed.add(jid)
                session_views.append({
                    "session_id": f"loose::{jid}",
                    "members": [v],
                })
        out[trio_lane] = session_views
    return out


def _render_kanban_html(folder_path, project_id):
    """Render the 5-column Kanban board (Research|Planning|Build|Deliverables|
    Grass Catchers).

    Each lane renders SESSIONS, not per-file cards (v2 Wave 4): the MOST-RECENT
    session is the visible card; the remaining sessions sit behind a "previous
    sessions (N)" ``<details>`` expander. One trio run = one card.
    """
    efforts_by_lane = _gather_project_efforts(folder_path, project_id)
    sessions_by_lane = _gather_project_sessions(
        folder_path, project_id, efforts_by_lane)
    cols = []
    for trio_lane, store_lane, label, glyph, add_label in _KANBAN_COLUMNS:
        views = efforts_by_lane.get(trio_lane, [])
        session_views = sessions_by_lane.get(trio_lane, [])
        any_live = any(v["is_live"] and not v["needs_input"] for v in views)
        any_input = any(v["needs_input"] for v in views)
        badge = ""
        if any_input:
            badge = "<span class='attn'>⚠ input</span>"
        elif any_live:
            badge = "<span class='live'><span class='dotpulse'></span>live</span>"
        cards = _render_lane_sessions(session_views, store_lane, project_id)
        # The "+ New run" affordance launches that lane. Research offers an
        # engine choice (Claude default + Gemini); plan/build are Claude-only;
        # deliverables are config-driven (no launch); grass catchers get a
        # placeholder add affordance (content feeds wired in Wave 5).
        if trio_lane == "deliverables":
            add = (f"<span class='addnew rnd-dim' title='Deliverables are run "
                   f"from the project config'>{html_lib.escape(add_label)}</span>")
        elif trio_lane == "grass":
            # Grass Catchers content feeds (Wave 5): manual add + promote from
            # INBOX. Both POST behind the auth gate via the project-window JS.
            add = (
                f"<span class='addnew' onclick=\"addIdea()\">"
                f"{html_lib.escape(add_label)}</span> "
                f"<span class='addnew' onclick=\"promoteInbox()\">"
                f"+ From inbox</span>"
            )
        elif trio_lane == "research":
            add = (
                "<span class='addnew' onclick=\"openTerminal('research','claude')\">"
                "+ New research run (Claude)</span> "
                "<span class='addnew' onclick=\"openTerminal('research','gemini')\">"
                "Gemini</span>"
            )
        else:
            add = (f"<span class='addnew' onclick=\"openTerminal('{trio_lane}')\">"
                   f"{html_lib.escape(add_label)}</span>")
        cols.append(
            f"<div class='col' data-col-lane='{html_lib.escape(trio_lane, quote=True)}'>"
            f"<h4><span>{glyph}</span> {html_lib.escape(label)} "
            f"<span class='badge' id='badge_{html_lib.escape(trio_lane, quote=True)}'>{badge}</span></h4>"
            f"<div class='col-cards' id='cards_{html_lib.escape(trio_lane, quote=True)}'>{cards}</div>"
            f"{add}</div>"
        )
    return "<div class='kan'>" + "".join(cols) + "</div>"


def _safe_dom_id(seg: str) -> str:
    """A DOM-id-safe slug of a session id (which contains ``::`` etc.)."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(seg or "")) or "x"


def _render_lane_sessions(session_views, store_lane, project_id):
    """Render a lane's sessions: most-recent visible + a "previous sessions"
    expander holding the rest (v2 Wave 4).

    Each session renders as ONE card (its representative = ``members[0]``); the
    remaining members of a multi-file session sit behind a small per-card
    "files (N)" expander so a 7-file Crucible run is one card, not seven. The
    representative keeps the existing click target (report viewer / attach /
    artifact); DONE / imported sessions ALSO get a "summary" affordance opening
    the cached validated summary page (Wave 6). Live / running cards keep
    attaching to the console (no Wave 4/7 regression).
    """
    if not session_views:
        return ""
    def _render_session_card(sv):
        members = sv.get("members", [])
        if not members:
            return ""
        rep = members[0]
        head = _render_effort_card(rep, store_lane, project_id)
        # Wave 6 summary affordance: only for DONE or imported (non-live)
        # sessions, and not for the defensive "loose::" single-effort wrappers
        # (those have no grouped session record to summarize). Live/running
        # representatives keep their console-attach click untouched.
        sid = sv.get("session_id", "") or ""
        rep_summarizable = (
            (rep.get("is_done") or rep.get("discovered"))
            and not rep.get("is_live")
            and sid and not sid.startswith("loose::")
        )
        summary_link = ""
        if rep_summarizable:
            trio_lane = rep.get("trio_lane", store_lane)
            # v3 Wave 6: clicking "summary" EXPANDS an inline accordion (no
            # navigation to /summary). The toggle carries the pid/lane/sid in
            # data-* attributes; the JS fetches /api/rnd/session_summary and
            # renders the panel in place. The ONLY new tab is a doc link inside
            # the rendered panel (report/artifact routes).
            esc_pid = html_lib.escape(project_id, quote=True)
            esc_lane = html_lib.escape(trio_lane, quote=True)
            esc_sid = html_lib.escape(sid, quote=True)
            panel_id = "summ_" + html_lib.escape(
                _safe_dom_id(trio_lane + "_" + sid), quote=True)
            summary_link = (
                f"<div class='session-summary-link'>"
                f"<a href=\"#\" class='summary-toggle' "
                f"data-pid=\"{esc_pid}\" data-lane=\"{esc_lane}\" "
                f"data-session=\"{esc_sid}\" data-panel=\"{panel_id}\" "
                f"onclick=\"toggleSessionSummary(this);return false;\">"
                f"summary</a>"
                f"<div class='session-summary-panel' id=\"{panel_id}\" "
                f"style='display:none'></div>"
                f"</div>"
            )
        rest = members[1:]
        if not rest:
            if summary_link:
                return f"<div class='session'>{head}{summary_link}</div>"
            return head
        inner = "".join(
            _render_effort_card(m, store_lane, project_id) for m in rest)
        return (
            f"<div class='session'>{head}{summary_link}"
            f"<details class='session-files'>"
            f"<summary>files ({len(rest) + 1})</summary>"
            f"<div class='session-files-body'>{inner}</div>"
            f"</details></div>"
        )
    recent = _render_session_card(session_views[0])
    older = session_views[1:]
    if not older:
        return recent
    older_cards = "".join(_render_session_card(sv) for sv in older)
    return (
        f"{recent}"
        f"<details class='prev-sessions'>"
        f"<summary>previous sessions ({len(older)})</summary>"
        f"<div class='prev-sessions-body'>{older_cards}</div>"
        f"</details>"
    )


def render_project_window_html(project_id: str) -> str:
    """Render the rich per-project window ("Dashboard A") for ``/project/<id>``.

    A 4-column Kanban (Research|Planning|Build|Deliverables) of versioned effort
    cards, a multi-session console drawer that attaches to whichever live job you
    click (its log tail + an Ask box for gates + a Stop button — acting on the
    ATTACHED job only), the lifecycle header (priority/notes/archive/retire or
    reactivate), the cost rollup + linked-tasks strip. Returns a standalone HTML
    page. All engine/user content is HTML-escaped (XSS-safe).
    """
    entry = _rnd.get_project(project_id)
    if entry is None:
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Project not found</title></head><body>"
                "<h1>Project not found</h1>"
                f"<p>No R&amp;D project with id "
                f"{html_lib.escape(project_id)}.</p>"
                "<p><a href='/'>&larr; Back to dashboard</a></p>"
                "</body></html>")
    # Surface path-missing on read.
    eff = _rnd.list_projects()
    for e in eff:
        if e["id"] == project_id:
            entry = e
            break
    inst = open_project_instance(project_id)
    folder_raw = entry.get("folder_path", "")
    name = html_lib.escape(entry.get("name", ""))
    folder = html_lib.escape(folder_raw)
    state_raw = entry.get("state", "active")
    state = html_lib.escape(state_raw)
    pr = entry.get("priority", 2)
    pid_attr = html_lib.escape(project_id, quote=True)
    notes_raw = entry.get("notes", "") or ""
    notes_attr = html_lib.escape(notes_raw, quote=True)
    notes_esc = html_lib.escape(notes_raw)
    blurb_raw = entry.get("blurb", "") or ""
    if not blurb_raw.strip():
        try:
            seeded = _rnd.seed_blurb(project_id)
            if seeded:
                blurb_raw = seeded.get("blurb", "") or ""
        except Exception:
            pass
    blurb_attr = html_lib.escape(blurb_raw, quote=True)
    blurb_esc = html_lib.escape(blurb_raw)
    is_active = state_raw in ("active", "path-missing")
    p1on = " rnd-pr-on" if pr == 1 else ""
    p2on = " rnd-pr-on" if pr == 2 else ""
    # Lifecycle header actions (all send the auth token via _postJson in the JS).
    rescan_btn = (f"<button class='rnd-mini' onclick=\"rndRescan('{pid_attr}')\" "
                  f"title='Re-scan the folder for trio artifacts'>Rescan</button>")
    if is_active:
        lifecycle = (
            f"<button class='rnd-mini{p1on}' onclick=\"rndSetPriority('{pid_attr}',1)\" title='Priority 1'>P1</button>"
            f"<button class='rnd-mini{p2on}' onclick=\"rndSetPriority('{pid_attr}',2)\" title='Priority 2'>P2</button>"
            f"{rescan_btn}"
            f"<button class='rnd-mini' onclick=\"rndBlurb('{pid_attr}')\">Blurb</button>"
            f"<button class='rnd-mini' onclick=\"rndNotes('{pid_attr}')\">Notes</button>"
            f"<button class='rnd-mini' onclick=\"rndArchive('{pid_attr}')\">Archive</button>"
            f"<button class='rnd-mini rnd-danger' onclick=\"rndRetire('{pid_attr}')\">Retire</button>"
        )
    else:
        lifecycle = (
            f"<button class='rnd-mini rnd-accent' onclick=\"rndReactivate('{pid_attr}')\">Reactivate</button>"
            f"{rescan_btn}"
            f"<button class='rnd-mini' onclick=\"rndBlurb('{pid_attr}')\">Blurb</button>"
            f"<button class='rnd-mini' onclick=\"rndNotes('{pid_attr}')\">Notes</button>"
        )
    kanban = _render_kanban_html(folder_raw, project_id)
    status = render_status_line_html(project_id)
    rollup = render_cost_rollup_html(project_id, folder_raw)
    tasks_html = render_project_tasks_html(project_id)
    deliverables_html = render_deliverables_html(project_id, folder_raw)
    pid_js = json.dumps(project_id)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{name} — Anchor R&amp;D</title>"
        # Vendored REAL xterm.js terminal (canvas) + anchor-term chrome, both
        # served like KaTeX. xterm.css styles the terminal grid; anchor-term.css
        # styles the REPL chrome (input line, gates, adopt panel) around it.
        f"<link rel='stylesheet' href='{XTERM_URL_PREFIX}/xterm.css'>"
        f"<link rel='stylesheet' href='{ANCHOR_TERM_URL_PREFIX}/anchor-term.css'>"
        "<style>"
        ":root{--bg:#0f1117;--surface:#1a1d27;--surface2:#232733;"
        "--border:#2e3340;--text:#e2e4e9;--text-dim:#8b8f9a;--accent:#6c9cfc;"
        "--danger:#f87171;--warning:#fbbf24;--success:#4ade80;color-scheme:dark}"
        "*{box-sizing:border-box}"
        "body{font-family:system-ui,Segoe UI,sans-serif;background:var(--bg);"
        "color:var(--text);margin:0;padding:24px;line-height:1.5}"
        "a{color:var(--accent)}"
        ".dash{background:var(--surface);border:1px solid var(--border);"
        "border-radius:12px;overflow:hidden;margin-top:12px}"
        ".dhead{display:flex;align-items:center;gap:12px;padding:14px 18px;"
        "border-bottom:1px solid var(--border);background:var(--surface2);"
        "flex-wrap:wrap}"
        ".dhead .name{font-size:18px;font-weight:700}"
        ".dhead .path{font-size:12px;color:var(--text-dim);"
        "font-family:ui-monospace,Consolas,monospace}"
        ".dhead .right{margin-left:auto;display:flex;gap:6px;align-items:center;"
        "flex-wrap:wrap}"
        ".pri{font-size:10px;font-weight:700;padding:1px 7px;border-radius:4px}"
        ".pri.p1{background:rgba(248,113,113,.18);color:var(--danger)}"
        ".pri.p2{background:rgba(251,191,36,.15);color:var(--warning)}"
        ".chip{font-size:10px;padding:1px 8px;border-radius:20px;"
        "border:1px solid var(--border);color:var(--text-dim)}"
        ".chip.active{color:var(--success);border-color:rgba(74,222,128,.3)}"
        ".rnd-mini{font-size:11px;padding:3px 9px;border-radius:6px;"
        "border:1px solid var(--border);background:var(--surface2);"
        "color:var(--text);cursor:pointer}"
        ".rnd-mini:hover{border-color:var(--accent)}"
        ".rnd-mini.rnd-pr-on{border-color:var(--accent);color:var(--accent)}"
        ".rnd-mini.rnd-danger:hover{border-color:var(--danger);color:var(--danger)}"
        ".rnd-mini.rnd-accent{border-color:var(--accent);color:var(--accent)}"
        ".kan{display:grid;grid-template-columns:repeat(5,1fr);gap:0}"
        ".kan .col{border-right:1px solid var(--border);min-height:180px;"
        "padding:12px}"
        ".kan .col:last-child{border-right:none}"
        ".kan .col h4{font-size:11px;text-transform:uppercase;letter-spacing:1px;"
        "color:var(--text-dim);display:flex;align-items:center;gap:7px;"
        "margin:0 0 10px}"
        ".kan .col h4 .badge{margin-left:auto}"
        ".attn{font-size:10px;font-weight:700;color:var(--warning);"
        "background:rgba(251,191,36,.15);border:1px solid rgba(251,191,36,.4);"
        "border-radius:20px;padding:1px 7px;display:inline-flex;align-items:center;"
        "gap:4px}"
        ".live{font-size:10px;font-weight:700;color:var(--accent);"
        "background:rgba(108,156,252,.13);border:1px solid rgba(108,156,252,.4);"
        "border-radius:20px;padding:1px 7px;display:inline-flex;align-items:center;"
        "gap:4px}"
        ".effort{background:var(--surface2);border:1px solid var(--border);"
        "border-radius:8px;padding:8px 10px;margin-bottom:7px;font-size:12px;"
        "cursor:pointer;transition:.12s}"
        ".effort:hover{border-color:var(--accent)}"
        ".effort.attached{border-color:var(--accent);"
        "box-shadow:0 0 0 1px var(--accent) inset}"
        ".effort .er{display:flex;align-items:center;gap:7px}"
        ".effort .ver{font-weight:600}"
        ".effort .age{margin-left:auto;color:var(--text-dim);font-size:11px}"
        ".effort .sub{font-size:11px;color:var(--text-dim);margin-top:3px}"
        ".effort .ecost{margin-left:6px;color:var(--success)}"
        ".effort.discovered{border-style:dashed;opacity:.92}"
        ".session-files{margin:-3px 0 7px}"
        ".session-files>summary{font-size:10.5px;color:var(--text-dim);"
        "cursor:pointer;list-style:none;padding-left:2px}"
        ".session-files>summary:hover{color:var(--accent)}"
        ".session-files-body{padding-left:8px;border-left:1px solid var(--border)}"
        ".prev-sessions{margin-top:2px}"
        ".prev-sessions>summary{font-size:11px;color:var(--text-dim);"
        "cursor:pointer;list-style:none;padding:3px 2px}"
        ".prev-sessions>summary:hover{color:var(--accent)}"
        ".prev-sessions-body{margin-top:6px}"
        # v3 Wave 6 — in-place expandable session summary accordion.
        ".session-summary-link{margin:-2px 0 7px}"
        ".summary-toggle{font-size:10.5px;color:var(--text-dim);"
        "cursor:pointer;text-decoration:none}"
        ".summary-toggle:hover{color:var(--accent)}"
        ".session-summary-panel{margin-top:6px;padding:8px 10px;font-size:11px;"
        "border:1px solid var(--border);border-radius:8px;"
        "background:rgba(255,255,255,.02)}"
        ".summ-loading{color:var(--text-dim);font-size:10.5px;font-style:italic}"
        ".summ-title{font-weight:600;margin-bottom:5px;color:var(--text)}"
        ".summ-field{margin:3px 0;color:var(--text);line-height:1.4}"
        ".summ-field b{color:var(--text-dim);font-weight:600}"
        ".summ-effort{color:var(--text-dim)}"
        ".summ-note{font-style:italic;color:var(--text-dim)}"
        ".summ-claims{margin:6px 0;padding-left:18px}"
        ".summ-claims li{margin:2px 0}"
        ".summ-docs{margin-top:6px}"
        ".summ-docs b{color:var(--text-dim);font-size:10.5px}"
        ".summ-docs ul{margin:4px 0;padding-left:18px}"
        ".summ-docs a{color:var(--accent);text-decoration:none}"
        ".summ-docs a:hover{text-decoration:underline}"
        ".summ-launch{margin-top:8px}"
        ".summ-launch-btn{font-size:10.5px;cursor:pointer;color:var(--accent);"
        "background:rgba(108,156,252,.1);border:1px solid rgba(108,156,252,.4);"
        "border-radius:6px;padding:3px 9px}"
        ".summ-launch-btn:hover{background:rgba(108,156,252,.2)}"
        ".imported{font-size:10px;color:var(--text-dim);"
        "display:inline-flex;align-items:center;gap:5px;letter-spacing:.5px}"
        ".dotdisc{width:6px;height:6px;border-radius:50%;"
        "background:var(--text-dim);display:inline-block}"
        ".effort .dkind{color:var(--text-dim);font-size:10px;"
        "border:1px solid var(--border);border-radius:10px;padding:0 6px}"
        ".statepill{font-size:10px;padding:1px 7px;border-radius:20px;"
        "border:1px solid var(--border)}"
        ".statepill.done{color:var(--success);border-color:rgba(74,222,128,.35);"
        "background:rgba(74,222,128,.1)}"
        ".statepill.run{color:var(--accent);border-color:rgba(108,156,252,.4);"
        "background:rgba(108,156,252,.12)}"
        ".statepill.input{color:var(--warning);border-color:rgba(251,191,36,.4);"
        "background:rgba(251,191,36,.12)}"
        ".statepill.fail{color:var(--danger);border-color:rgba(248,113,113,.4);"
        "background:rgba(248,113,113,.12)}"
        ".addnew{font-size:12px;color:var(--accent);cursor:pointer;"
        "display:inline-block;margin-top:4px}"
        ".addnew.rnd-dim{color:var(--text-dim);cursor:default}"
        ".dotpulse{width:7px;height:7px;border-radius:50%;background:var(--accent);"
        "animation:pulse 1.5s infinite;display:inline-block}"
        ".dotwarn{width:7px;height:7px;border-radius:50%;background:var(--warning);"
        "animation:pulse 1.5s infinite;display:inline-block}"
        "@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(108,156,252,.5)}"
        "70%{box-shadow:0 0 0 6px rgba(108,156,252,0)}"
        "100%{box-shadow:0 0 0 0 rgba(108,156,252,0)} }"
        ".console{border-top:1px solid var(--border);background:#0c0e14}"
        ".console .ctabs{display:flex;align-items:center;gap:6px;padding:8px 14px;"
        "border-bottom:1px solid var(--border);flex-wrap:wrap}"
        ".console .ctabs .lbl{font-size:10px;text-transform:uppercase;"
        "letter-spacing:1px;color:var(--text-dim);margin-right:4px}"
        ".ctab{font-size:11.5px;padding:4px 11px;border-radius:7px;"
        "border:1px solid var(--border);background:var(--surface);"
        "color:var(--text-dim);cursor:pointer;display:inline-flex;"
        "align-items:center;gap:6px}"
        ".ctab.sel{color:var(--text);border-color:var(--accent);"
        "background:rgba(108,156,252,.1)}"
        ".ctab.warn.sel{border-color:var(--warning);"
        "background:rgba(251,191,36,.1);color:var(--warning)}"
        ".console .cbody{padding:12px 16px}"
        ".console .src{font-size:11px;color:var(--text-dim);margin-bottom:8px}"
        ".console .log{font-family:ui-monospace,Consolas,monospace;font-size:12px;"
        "color:#cdd2dc;white-space:pre-wrap;max-height:200px;overflow:auto}"
        ".console .ask{margin-top:10px;background:var(--surface2);"
        "border:1px solid rgba(251,191,36,.4);border-radius:8px;padding:10px}"
        ".console .ask .qtext{font-size:12.5px;margin-bottom:8px}"
        ".console .ask .opts{display:flex;gap:8px;flex-wrap:wrap}"
        ".inputrow{display:flex;gap:8px;margin-top:9px}"
        ".inputrow input{flex:1;background:var(--bg);border:1px solid var(--border);"
        "border-radius:7px;padding:8px 11px;color:var(--text);font-size:13px}"
        ".btn{font-size:12px;padding:5px 12px;border-radius:7px;"
        "border:1px solid var(--border);background:var(--surface2);"
        "color:var(--text);cursor:pointer}"
        ".btn:hover{border-color:var(--accent)}"
        ".btn.accent{background:var(--accent);color:#0b1020;"
        "border-color:var(--accent);font-weight:600}"
        ".taskstrip{border-top:1px solid var(--border);padding:11px 16px}"
        ".rnd-status-line{margin:0;display:flex;gap:8px;flex-wrap:wrap}"
        ".rnd-lane{padding:4px 10px;border-radius:6px;background:#1b2030;"
        "font-size:13px}"
        ".rnd-lane-empty{color:var(--text-dim)}"
        ".rnd-imported{color:var(--text-dim);font-style:italic;font-size:11px}"
        ".rnd-running{color:var(--success);font-size:11px}"
        ".rnd-dim{color:var(--text-dim)}"
        "h2{font-size:14px;margin:18px 0 6px}"
        # ── Wave 4: stacking window-manager UI (session bar + windows) ──
        # NOTE: this is a PLAIN (non-f) string literal — single braces are FINE.
        ".sessbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;"
        "padding:10px 16px;border-top:1px solid var(--border);"
        "background:var(--surface2)}"
        ".sessbar .lbl{font-size:10px;text-transform:uppercase;letter-spacing:1px;"
        "color:var(--text-dim);margin-right:2px}"
        ".sessbar .hint{font-size:11px;color:var(--text-dim);margin-left:auto}"
        ".sessbtn{font-size:11.5px;padding:4px 11px;border-radius:7px;"
        "border:1px solid var(--border);background:var(--surface);"
        "color:var(--text);cursor:pointer;display:inline-flex;align-items:center;"
        "gap:6px}"
        ".sessbtn:hover{border-color:var(--accent)}"
        ".sessbtn.open{border-color:var(--accent);background:rgba(108,156,252,.1)}"
        ".sess-dot{width:8px;height:8px;border-radius:50%;display:inline-block;"
        "background:var(--text-dim)}"
        ".sess-dot--green{background:#4ade80}"
        ".sess-dot--amber{background:#fbbf24}"
        ".sess-dot--red{background:#f87171}"
        ".sess-dot--grey{background:#8b8f9a}"
        ".newsess{font-size:11px;padding:3px 10px;border-radius:7px;"
        "border:1px dashed var(--border);background:transparent;"
        "color:var(--accent);cursor:pointer}"
        ".newsess:hover{border-color:var(--accent)}"
        # The window LAYER is a positioned canvas the brick-stacked windows live in.
        ".winlayer{position:relative;min-height:40px;padding:0 16px 16px}"
        ".termwin{position:absolute;width:520px;height:340px;background:#0c0e14;"
        "border:1px solid var(--border);border-radius:10px;overflow:hidden;"
        "box-shadow:0 8px 24px rgba(0,0,0,.45);display:flex;flex-direction:column;"
        "min-width:260px;min-height:120px}"
        ".termwin.minimized{height:34px!important;min-height:0;resize:none}"
        ".termwin.minimized .termbody,.termwin.minimized .winresize{display:none}"
        ".termwin .wintitle{display:flex;align-items:center;gap:8px;"
        "padding:6px 10px;background:var(--surface2);"
        "border-bottom:1px solid var(--border);cursor:move;user-select:none;"
        "font-size:12px}"
        ".termwin .wintitle .wt-label{font-weight:600;white-space:nowrap;"
        "overflow:hidden;text-overflow:ellipsis}"
        ".termwin .wintitle .wt-meta{color:var(--text-dim);font-size:11px}"
        ".termwin .wintitle .wt-sp{margin-left:auto}"
        ".winbtn{width:20px;height:20px;line-height:18px;text-align:center;"
        "border-radius:5px;border:1px solid var(--border);background:var(--surface);"
        "color:var(--text-dim);cursor:pointer;font-size:12px;padding:0}"
        ".winbtn:hover{color:var(--text);border-color:var(--accent)}"
        ".winbtn.kill:hover{color:var(--danger);border-color:var(--danger)}"
        ".termwin .termbody{flex:1;overflow:hidden;padding:4px}"
        ".termwin .winresize{position:absolute;right:0;bottom:0;width:16px;"
        "height:16px;cursor:nwse-resize}"
        ".termwin .winresize::after{content:'';position:absolute;right:3px;"
        "bottom:3px;width:7px;height:7px;border-right:2px solid var(--text-dim);"
        "border-bottom:2px solid var(--text-dim)}"
        "</style></head><body>"
        f"<p><a href='/'>&larr; Back to dashboard</a></p>"
        f"<div class='dash' data-notes='{notes_attr}' data-blurb='{blurb_attr}'>"
        # ── Lifecycle header ──
        "<div class='dhead'>"
        f"<span class='name'>{name}</span>"
        f"<span class='path'>{folder}</span>"
        "<div class='right'>"
        f"<span class='pri p{pr}'>P{pr}</span>"
        f"<span class='chip{' active' if is_active else ''}'>{state}</span>"
        f"{lifecycle}"
        "</div></div>"
        # ── Project blurb ("what this project is"; click 'Blurb' above to edit) ──
        + (f"<div class='rnd-blurb' data-blurb='{blurb_attr}' "
           f"style='padding:8px 18px;border-bottom:1px solid var(--border);"
           f"font-size:13px'>{blurb_esc}</div>" if blurb_raw.strip() else "")
        # ── Project notes (like a task's Notes; click 'Notes' above to edit) ──
        + (f"<div style='padding:8px 18px;border-bottom:1px solid var(--border);"
           f"font-size:12.5px;color:var(--text-dim);white-space:pre-wrap'>"
           f"&#128221; {notes_esc}</div>" if notes_raw.strip() else "")
        +
        # ── 4-state status line (consistent with the dashboard tiles) ──
        f"<div style='padding:8px 18px;border-bottom:1px solid var(--border)'>{status}</div>"
        # ── Kanban board ──
        f"{kanban}"
        # ── Wave 4: session button bar + stacking window manager (ConPTY) ──
        # The bar is repopulated on load from /api/rnd/term_sessions; each button
        # is status-colored and opens/attaches that session's terminal window.
        "<div class='sessbar' id='sessionBar'>"
        "<span class='lbl'>Live terminals</span>"
        "<span id='sessionBtns'></span>"
        "<button class='newsess' onclick=\"newTermSession('research')\">+ research</button>"
        "<button class='newsess' onclick=\"newTermSession('plan')\">+ plan</button>"
        "<button class='newsess' onclick=\"newTermSession('build')\">+ build</button>"
        "<span class='hint' id='sessionBarHint'>no live terminal sessions</span>"
        "</div>"
        "<div class='winlayer' id='windowLayer'></div>"
        # ── Console drawer (session tabs + attached log + ask + stop) ──
        "<div class='console' id='console'>"
        "<div class='ctabs'><span class='lbl'>Sessions</span>"
        "<span id='ctabs'></span>"
        "<span id='ctabsHint' style='margin-left:auto;font-size:11px;"
        "color:var(--text-dim)'>launch or click a live effort to attach ↑</span>"
        "</div>"
        "<div class='cbody'>"
        "<div class='src' id='consoleSrc'>No session attached.</div>"
        # Interactive terminal host (Wave 7): openTerminal() mounts the vendored
        # anchor-term console here over the SSE stream. This replaces the raw-log
        # launch console as the primary surface for NEW research/plan/build runs.
        "<div id='termHost'></div>"
        # Legacy raw-log mirror (kept as a fallback for reattaching to a
        # background job via the /api/rnd/tail poll — does not break Wave 4/6).
        "<div class='log' id='laneLog'></div>"
        "<div id='laneGate' class='ask' style='display:none'></div>"
        "<div class='inputrow' id='inputRow' style='display:none'>"
        "<input id='replyText' placeholder='…or type a reply to this session'>"
        "<button class='btn accent' onclick='sendReply()'>Send</button>"
        "<button class='btn' onclick='stopAttached()'>Stop job</button>"
        "</div></div></div>"
        # ── Linked tasks strip ──
        f"<div class='taskstrip'>{tasks_html}</div>"
        "</div>"
        f"{rollup}"
        f"{deliverables_html}"
        f"<p style='color:#8a90a2;font-size:12px'>instance "
        f"{html_lib.escape(inst['instance_id'])}</p>"
        # Vendored REAL xterm.js (defines window.Terminal) — MUST load before the
        # anchor-term adapter, which instantiates an xterm.js Terminal and layers
        # the REPL chrome on top while preserving window.AnchorTerm.mount.
        f"<script src='{XTERM_URL_PREFIX}/xterm.js'></script>"
        # anchor-term adapter (Wave 7+): drives the xterm.js Terminal and provides
        # window.AnchorTerm.mount (SSE stream + input line + inline gate + adopt).
        f"<script src='{ANCHOR_TERM_URL_PREFIX}/anchor-term.js'></script>"
        "<script>\n"
        f"var PROJECT_ID = {pid_js};\n"
        f"window.ANCHOR_AUTH_REQUIRED = {'true' if _paths.expected_token() else 'false'};\n"
        + _PROJECT_WINDOW_JS +
        "</script>"
        "<script>" + cache_bust_script() + "</script>"
        "</body></html>"
    )


# JS for the rich project window. Drives the multi-session console: a SESSIONS
# map keyed by job_id (each with its own log tail, cursor, status, gate), an
# ATTACHED job_id the console mirrors, session tabs, and per-session attach /
# answer-gate / stop. answerGate + stopAttached ALWAYS act on the ATTACHED job
# only (no cross-wire). Plain string (NOT an f-string), so braces are single. No
# template interpolation here beyond the PROJECT_ID var injected above.
_PROJECT_WINDOW_JS = r"""
// SESSIONS: job_id -> {jobId, lane, since, lines:[], status, pending, tabName}
var SESSIONS = {};
var _attached = null;          // job_id the console is currently mirroring
var _pollTimer = null;

function _esc(s) { var d = document.createElement('div'); d.textContent = (s == null ? '' : s); return d.innerHTML; }

// ── Access token (D4) ──────────────────────────────────────────────────────
// The shared-secret token is kept ONLY in this browser's localStorage and sent
// as X-Anchor-Token on mutating POSTs. It is NEVER embedded in the served HTML
// (GET is unauthenticated, so embedding would leak it to anyone who can reach
// the page). When ANCHOR_TOKEN is unset on the server, auth is disabled and the
// header is simply ignored, so local use needs no token.
function _anchorToken() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
function setAnchorToken() {
  var cur = _anchorToken();
  var t = window.prompt('Paste your Anchor access token:', cur);
  if (t === null) return false;            // user cancelled
  try { if (t) { localStorage.setItem('anchor_token', t.trim()); } else { localStorage.removeItem('anchor_token'); } } catch (e) {}
  return true;
}
// On first load, if the server requires auth and no token is stored yet, ask once.
window.addEventListener('DOMContentLoaded', function () {
  if (window.ANCHOR_AUTH_REQUIRED && !_anchorToken()) { setAnchorToken(); }
  adoptLiveEfforts();
  _startPolling();
  // Wave 4: repopulate the ConPTY session button bar from the registry so
  // reopening the dashboard reflects live managed sessions.
  loadSessions();
});
function _postJson(url, payload) {
  var headers = {'Content-Type': 'application/json'};
  var tok = _anchorToken();
  if (tok) headers['X-Anchor-Token'] = tok;
  return fetch(url, { method: 'POST', headers: headers, body: JSON.stringify(payload) });
}
function _isUnauthorized(r, data) { return r.status === 401 || (data && data.error === 'unauthorized'); }

// On load, adopt any live/needs-input effort cards rendered server-side as
// sessions (so a background job that was already running shows up + can be
// attached without a fresh launch).
function adoptLiveEfforts() {
  var cards = document.querySelectorAll('.effort[data-live="1"]');
  for (var i = 0; i < cards.length; i++) {
    var c = cards[i];
    var jid = c.getAttribute('data-job-id');
    if (jid && !SESSIONS[jid]) {
      _ensureSession(jid, c.getAttribute('data-trio-lane') || '',
                     c.getAttribute('data-ver') || '');
    }
  }
  if (!_attached) {
    var first = Object.keys(SESSIONS)[0];
    if (first) attachSession(first);
  }
  renderTabs();
}

function _ensureSession(jobId, lane, ver) {
  if (!SESSIONS[jobId]) {
    SESSIONS[jobId] = {jobId: jobId, lane: lane || '', ver: ver || '',
                       since: 0, lines: [], status: 'running', pending: null,
                       tabName: ((lane || 'job') + (ver ? (' ' + ver) : ''))};
  }
  return SESSIONS[jobId];
}

function renderTabs() {
  var host = document.getElementById('ctabs');
  if (!host) return;
  host.innerHTML = '';
  var ids = Object.keys(SESSIONS);
  for (var i = 0; i < ids.length; i++) {
    var s = SESSIONS[ids[i]];
    var span = document.createElement('span');
    var warn = (s.pending ? ' warn' : '');
    var sel = (s.jobId === _attached ? ' sel' : '');
    span.className = 'ctab' + warn + sel;
    var dot = s.pending ? "<span class='dotwarn'></span>"
                        : (_isLiveStatus(s.status) ? "<span class='dotpulse'></span>" : '');
    span.innerHTML = dot + _esc(s.tabName) + (s.pending ? ' · needs input' : '');
    (function (jid) { span.onclick = function () { attachSession(jid); }; })(s.jobId);
    host.appendChild(span);
  }
  var hint = document.getElementById('ctabsHint');
  if (hint) hint.style.display = ids.length ? 'none' : '';
}

function _isLiveStatus(st) {
  return st === 'running' || st === 'awaiting-input' || !st;
}

function attachSession(jobId) {
  if (!SESSIONS[jobId]) _ensureSession(jobId, '', '');
  _attached = jobId;
  // Highlight the attached effort card.
  var cards = document.querySelectorAll('.effort');
  for (var i = 0; i < cards.length; i++) cards[i].classList.remove('attached');
  var card = document.getElementById('effort_' + jobId);
  if (card) card.classList.add('attached');
  _renderAttached();
  renderTabs();
}

function _renderAttached() {
  var log = document.getElementById('laneLog');
  var src = document.getElementById('consoleSrc');
  var gate = document.getElementById('laneGate');
  var inputRow = document.getElementById('inputRow');
  if (!_attached || !SESSIONS[_attached]) {
    if (src) src.textContent = 'No session attached.';
    if (log) log.textContent = '';
    if (gate) gate.style.display = 'none';
    if (inputRow) inputRow.style.display = 'none';
    return;
  }
  var s = SESSIONS[_attached];
  if (src) {
    src.innerHTML = 'Attached to: <b style="color:var(--text)">' +
      _esc(s.tabName) + '</b> · ' + _esc(s.status || '') + ' · job ' + _esc(s.jobId);
  }
  if (log) { log.textContent = s.lines.join('\n'); log.scrollTop = log.scrollHeight; }
  if (inputRow) inputRow.style.display = 'flex';
  if (s.pending) { _renderGate(s.pending); }
  else if (gate) { gate.style.display = 'none'; gate.innerHTML = ''; }
}

// ── Interactive terminal (Wave 7) ───────────────────────────────────────────
// openTerminal starts a PERSISTENT stream-json REPL session for the lane and
// mounts the vendored anchor-term console (SSE stream + input line + inline gate
// + exit→discover→confirm-adopt). This is the affordance the "+ New
// research/plan/build run" links call, replacing the raw-log launch console.
var _activeTerm = null;
async function openTerminal(lane, backend) {
  backend = backend || 'claude';
  var payload = {project_id: PROJECT_ID, lane: lane, backend: backend};
  var r, data;
  try {
    r = await _postJson('/api/rnd/start_terminal', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/start_terminal', payload);
      data = await r.json();
    }
  } catch (e) { alert('[terminal error] ' + e.message); return; }
  if (!data.ok) {
    alert('[terminal refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
  var host = document.getElementById('termHost');
  var src = document.getElementById('consoleSrc');
  if (src) src.textContent = 'Interactive ' + lane + ' terminal · ' + backend +
    ' · session ' + data.session;
  // Hide the legacy raw-log mirror while the terminal is the active surface.
  var legacy = document.getElementById('laneLog');
  if (legacy) legacy.style.display = 'none';
  if (_activeTerm && _activeTerm.dispose) _activeTerm.dispose();
  if (!window.AnchorTerm) { alert('terminal component failed to load'); return; }
  _activeTerm = window.AnchorTerm.mount({
    host: host,
    session: data.session,
    lane: lane,
    title: lane + ' · ' + backend,
    // Token-aware POST helper the component uses for input/discover/adopt.
    postJson: function (url, p) {
      return _postJson(url, p).then(function (resp) {
        return resp.json().then(function (d) {
          if (_isUnauthorized(resp, d) && setAnchorToken()) {
            return _postJson(url, p).then(function (r2) { return r2.json(); });
          }
          return d;
        });
      });
    },
    onAdopted: function () {
      // The produced docs are now a session in the lane — refresh to show it.
      setTimeout(function () { location.reload(); }, 800);
    }
  });
}

async function launchLane(lane, backend) {
  // backend defaults to 'claude'. Only the research lane offers 'gemini';
  // plan/build are Claude-only (enforced server-side too).
  backend = backend || 'claude';
  var r, data;
  var payload = {project_id: PROJECT_ID, lane: lane, backend: backend};
  try {
    r = await _postJson('/api/rnd/launch_lane', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/launch_lane', payload);
      data = await r.json();
    }
  } catch (e) { alert('[launch error] ' + e.message); return; }
  if (!data.ok) {
    alert('[launch refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
  var s = _ensureSession(data.job_id, lane, '');
  s.status = data.status || 'running';
  s.tabName = lane + (data.backend ? (' · ' + data.backend) : '');
  attachSession(data.job_id);
  _startPolling();
}

// ── Grass Catchers content feeds (Wave 5) ───────────────────────────────────
// Manual add: prompt for idea text, POST /api/rnd/add_idea, then refresh so the
// new grass card renders. Token-aware via _postJson (retries once on 401).
async function addIdea() {
  var text = window.prompt('New idea for Grass Catchers:', '');
  if (text === null) return;            // cancelled
  text = (text || '').trim();
  if (!text) return;
  var payload = {project_id: PROJECT_ID, text: text};
  var r, data;
  try {
    r = await _postJson('/api/rnd/add_idea', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/add_idea', payload);
      data = await r.json();
    }
  } catch (e) { alert('[add idea error] ' + e.message); return; }
  if (!data.ok) { alert('[add idea refused] ' + (data.error || 'unknown')); return; }
  location.reload();
}

// Promote from INBOX: prompt for the inbox item text, POST /api/rnd/promote_inbox
// (copy-by-default — the inbox item is not removed), then refresh.
async function promoteInbox() {
  var text = window.prompt('Promote which INBOX item into Grass Catchers? (type the item text)', '');
  if (text === null) return;
  text = (text || '').trim();
  if (!text) return;
  var payload = {project_id: PROJECT_ID, text: text};
  var r, data;
  try {
    r = await _postJson('/api/rnd/promote_inbox', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/promote_inbox', payload);
      data = await r.json();
    }
  } catch (e) { alert('[promote inbox error] ' + e.message); return; }
  if (!data.ok) { alert('[promote inbox refused] ' + (data.error || 'unknown')); return; }
  location.reload();
}

function _startPolling() {
  if (_pollTimer) clearTimeout(_pollTimer);
  _pollOnce();
}

// Poll EVERY known session each tick so background sessions keep their gate +
// status fresh (a lane badge can flip to ⚠ input even when not attached). Only
// the ATTACHED session re-renders the console body.
async function _pollOnce() {
  var ids = Object.keys(SESSIONS);
  var anyLive = false;
  for (var i = 0; i < ids.length; i++) {
    var s = SESSIONS[ids[i]];
    var terminal = ['done', 'cancelled', 'interrupted', 'failed'];
    if (s.status && terminal.indexOf(s.status) >= 0 && !s.pending) continue;
    anyLive = true;
    try {
      var r = await fetch('/api/rnd/tail?job_id=' + encodeURIComponent(s.jobId) + '&since=' + s.since);
      var data = await r.json();
      if (data.lines && data.lines.length) {
        for (var k = 0; k < data.lines.length; k++) {
          var ln = data.lines[k];
          s.lines.push(typeof ln === 'string' ? ln : JSON.stringify(ln));
        }
        s.since = data.next;
      }
      if (data.status) s.status = data.status;
      s.pending = data.pending_prompt || null;
    } catch (e) { /* keep polling */ }
  }
  // Refresh lane badges from the freshest session state, then the tabs + body.
  _refreshBadges();
  renderTabs();
  if (_attached) _renderAttached();
  _pollTimer = setTimeout(_pollOnce, 1500);
}

// Flip each lane header badge to ⚠ input / live based on its sessions.
function _refreshBadges() {
  var byLane = {};
  var ids = Object.keys(SESSIONS);
  for (var i = 0; i < ids.length; i++) {
    var s = SESSIONS[ids[i]];
    if (!s.lane) continue;
    var b = byLane[s.lane] || (byLane[s.lane] = {live: false, input: false});
    if (s.pending) b.input = true;
    else if (_isLiveStatus(s.status) && (s.status === 'running' || s.status === 'awaiting-input')) b.live = true;
  }
  for (var lane in byLane) {
    var el = document.getElementById('badge_' + lane);
    if (!el) continue;
    if (byLane[lane].input) el.innerHTML = "<span class='attn'>⚠ input</span>";
    else if (byLane[lane].live) el.innerHTML = "<span class='live'><span class='dotpulse'></span>live</span>";
  }
}

function _renderGate(prompt) {
  var box = document.getElementById('laneGate');
  if (!box) return;
  // Build the gate DOM without inline onclick handlers. The option label is
  // carried only as the button's text node + a data-gate-opt attribute; a single
  // delegated listener (wired once below) reads getAttribute('data-gate-opt') and
  // calls answerGate(label). This avoids the HTML-attribute breakout that an
  // an inline onclick built from JSON.stringify(label) caused (the double quotes
  // from JSON.stringify terminated the double-quoted onclick attribute), which made
  // every gate option button non-functional.
  box.innerHTML = '';
  var q = document.createElement('div');
  q.className = 'qtext';
  var strong = document.createElement('strong');
  strong.textContent = (prompt.question != null ? prompt.question : 'Input requested');
  q.appendChild(strong);
  box.appendChild(q);
  var optsWrap = document.createElement('div');
  optsWrap.className = 'opts';
  var opts = prompt.options || [];
  opts.forEach(function (o) {
    var label = (o && o.label != null) ? o.label : String(o);
    var btn = document.createElement('button');
    btn.className = 'btn accent';
    btn.setAttribute('data-gate-opt', label);  // attribute value is set via the DOM API, never string-concatenated into HTML
    btn.textContent = label;
    optsWrap.appendChild(btn);
  });
  box.appendChild(optsWrap);
  // Wire the delegated click handler exactly once for this box.
  if (!box._gateDelegated) {
    box._gateDelegated = true;
    box.addEventListener('click', function (e) {
      var t = e.target;
      while (t && t !== box && !(t.getAttribute && t.hasAttribute && t.hasAttribute('data-gate-opt'))) {
        t = t.parentNode;
      }
      if (t && t.getAttribute && t.hasAttribute('data-gate-opt')) {
        answerGate(t.getAttribute('data-gate-opt'));
      }
    });
  }
  box.style.display = 'block';
}

// answerGate ALWAYS targets the ATTACHED session (no cross-wire). The reply box
// + the gate option buttons both route here.
async function answerGate(choice) {
  if (!_attached) return;
  var jid = _attached;
  try {
    var payload = {job_id: jid, choice: choice};
    var r = await _postJson('/api/rnd/answer_gate', payload);
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/answer_gate', payload);
      data = await r.json();
    }
    if (SESSIONS[jid]) {
      SESSIONS[jid].lines.push('[gate answered: ' + choice +
        (data.written ? '' : ' (no-op: ' + data.reason + ')') + ']');
      SESSIONS[jid].pending = null;
    }
  } catch (e) { if (SESSIONS[jid]) SESSIONS[jid].lines.push('[gate error] ' + e.message); }
  var box = document.getElementById('laneGate');
  if (box) { box.style.display = 'none'; box.innerHTML = ''; }
  if (_attached === jid) _renderAttached();
  renderTabs();
  _startPolling();
}

function sendReply() {
  var inp = document.getElementById('replyText');
  if (!inp || !inp.value.trim()) return;
  var v = inp.value;
  inp.value = '';
  answerGate(v);
}

// stopAttached ALWAYS cancels the ATTACHED job only (no cross-wire).
async function stopAttached() {
  if (!_attached) return;
  var jid = _attached;
  try {
    var r = await _postJson('/api/rnd/cancel_job', {job_id: jid});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/cancel_job', {job_id: jid});
      data = await r.json();
    }
    if (SESSIONS[jid]) {
      SESSIONS[jid].status = (data && data.status) || 'cancelled';
      SESSIONS[jid].pending = null;
      SESSIONS[jid].lines.push('[stopped: ' + ((data && data.status) || 'cancelled') + ']');
    }
  } catch (e) { if (SESSIONS[jid]) SESSIONS[jid].lines.push('[stop error] ' + e.message); }
  if (_attached === jid) _renderAttached();
  renderTabs();
}

function openReport(href) { window.open(href, '_blank'); }

// Open a session's cached, validated summary page (Wave 6 back-compat: direct
// /summary links still work; the session card no longer navigates here).
function openSummary(href) { window.open(href, '_blank'); }

// ── In-place expandable session summaries (v3 Wave 6) ───────────────────────
// Clicking "summary" EXPANDS an inline accordion in the Kanban (NO navigation
// to /summary). The panel fetches the cached structured summary as JSON and
// renders when-run · what-was-asked · North-Star · doc links (the ONLY new tab)
// · effort (tokens + wall-clock; imported → "no run metrics"), plus a "Launch
// new session" button that calls the Wave-3/4 launch path seeded from THIS
// session. Collapsing hides it; reopening serves the cache.
function toggleSessionSummary(el) {
  var panelId = el.getAttribute('data-panel');
  var panel = document.getElementById(panelId);
  if (!panel) return;
  if (panel.style.display !== 'none' && panel.getAttribute('data-loaded') === '1') {
    // Collapse.
    panel.style.display = 'none';
    return;
  }
  panel.style.display = 'block';
  if (panel.getAttribute('data-loaded') === '1') return;  // reopen → cache
  var pid = el.getAttribute('data-pid');
  var lane = el.getAttribute('data-lane');
  var sid = el.getAttribute('data-session');
  panel.innerHTML = '<div class="summ-loading">loading…</div>';
  _loadSessionSummary(panel, pid, lane, sid, 0);
}

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function _sessionSummaryUrl(pid, lane, sid) {
  return '/api/rnd/session_summary?pid=' + encodeURIComponent(pid)
    + '&lane=' + encodeURIComponent(lane)
    + '&session=' + encodeURIComponent(sid);
}

function _loadSessionSummary(panel, pid, lane, sid, attempt) {
  var _hdrs = {Accept: 'application/json'};
  fetch(_sessionSummaryUrl(pid, lane, sid), {headers: _hdrs} )
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data && data.status === 'ready' && data.summary) {
        panel.innerHTML = _renderSessionSummary(data.summary, pid, lane, sid);
        _wireLaunchFromPanel(panel, lane, sid);
        panel.setAttribute('data-loaded', '1');
        return;
      }
      // TERMINAL status (unknown project / missing session): STOP polling and
      // show an honest "summary unavailable" note instead of spinning forever.
      if (data && (data.status === 'unknown' || data.status === 'not-found'
                   || data.ok === false)) {
        panel.innerHTML = '<div class="summ-loading">Summary unavailable for '
          + 'this session.</div>' + _launchButtonHtml();
        _wireLaunchFromPanel(panel, lane, sid);
        panel.setAttribute('data-loaded', '1');
        return;
      }
      // "generating…" fallback: poll a bounded number of times, then stop.
      if (attempt < 20) {
        panel.innerHTML = '<div class="summ-loading">generating summary… '
          + '(this runs once and is then cached)</div>';
        setTimeout(function () {
          _loadSessionSummary(panel, pid, lane, sid, attempt + 1);
        }, 1500);
      } else {
        panel.innerHTML = '<div class="summ-loading">Summary is still '
          + 'generating. Close and reopen shortly to view it.</div>'
          + _launchButtonHtml();
        _wireLaunchFromPanel(panel, lane, sid);
        panel.setAttribute('data-loaded', '1');
      }
    })
    .catch(function (e) {
      panel.innerHTML = '<div class="summ-loading">Could not load summary: '
        + _esc(e.message) + '</div>';
    });
}

function _renderSessionSummary(s, pid, lane, sid) {
  var h = [];
  if (s.title) h.push('<div class="summ-title">' + _esc(s.title) + '</div>');
  if (s.when_run) h.push('<div class="summ-field"><b>When run:</b> '
    + _esc(s.when_run) + '</div>');
  if (s.what_was_asked) h.push('<div class="summ-field"><b>What was asked:</b> '
    + _esc(s.what_was_asked) + '</div>');
  if (s.north_star) h.push('<div class="summ-field"><b>North Star:</b> '
    + _esc(s.north_star) + '</div>');
  // Effort: imported sessions honestly show "no run metrics" (effort === null).
  if (s.hasOwnProperty('effort')) {
    if (s.effort === null) {
      h.push('<div class="summ-field summ-effort"><b>Effort:</b> '
        + 'imported — no run metrics</div>');
    } else if (s.effort) {
      var secs = ((s.effort.wall_clock_ms || 0) / 1000).toFixed(1);
      h.push('<div class="summ-field summ-effort"><b>Effort:</b> '
        + _esc(s.effort.tokens || 0) + ' tokens · ' + _esc(secs) + 's wall-clock · '
        + _esc(s.effort.runs || 0) + ' run(s)</div>');
    }
  }
  var claims = s.claims || [];
  if (claims.length) {
    var items = claims.map(function (c) { return '<li>' + _esc(c) + '</li>'; });
    h.push('<ul class="summ-claims">' + items.join('') + '</ul>');
  } else if (s.no_grounded_claims) {
    h.push('<div class="summ-field summ-note">No grounded claims could be '
      + 'extracted for this session.</div>');
  }
  // Document links — each opens the rendered markdown in a NEW TAB (the ONLY
  // new tab) via the existing /report and /artifact routes.
  var links = s.member_links || [];
  if (links.length) {
    var ls = links.map(function (lk) {
      return '<li><a href="' + _esc(lk.href) + '" target="_blank" '
        + 'rel="noopener">' + _esc(lk.label) + '</a></li>';
    });
    h.push('<div class="summ-docs"><b>Documents</b><ul>' + ls.join('')
      + '</ul></div>');
  }
  h.push(_launchButtonHtml());
  return '<div class="summ-body">' + h.join('') + '</div>';
}

function _launchButtonHtml() {
  return '<div class="summ-launch"><button class="summ-launch-btn" '
    + 'type="button">Launch new session</button></div>';
}

// Wire the panel's "Launch new session" button to the Wave-3/4 launch path,
// seeded from THIS session. The lane + a seed hint (the source session id) ride
// into newTermSession so Wave 7 can build the handoff on top of this seam.
function _wireLaunchFromPanel(panel, lane, sid) {
  var btn = panel.querySelector('.summ-launch-btn');
  if (!btn) return;
  btn.onclick = function () {
    newTermSession(lane, null, {seed_session: sid});
  };
}

// ── Lifecycle header actions (token-aware via _postJson) ────────────────────
function _lifecycle(url, payload, reload) {
  return _postJson(url, payload).then(function (r) {
    return r.json().then(function (data) {
      if (_isUnauthorized(r, data) && setAnchorToken()) {
        return _postJson(url, payload).then(function (r2) { return r2.json(); });
      }
      return data;
    });
  }).then(function (data) {
    if (reload !== false) location.reload();
    return data;
  }).catch(function (e) { alert('Action failed: ' + e.message); });
}
function rndSetPriority(pid, pr) { _lifecycle('/api/rnd/set_priority', {id: pid, priority: pr}); }
function rndArchive(pid) { if (confirm('Archive this project?')) _lifecycle('/api/rnd/archive_project', {id: pid}); }
function rndRetire(pid) { if (confirm('Retire/cancel this project?')) _lifecycle('/api/rnd/retire_project', {id: pid}); }
function rndReactivate(pid) { _lifecycle('/api/rnd/reactivate_project', {id: pid}); }
function rndRescan(pid) { _lifecycle('/api/rnd/rescan', {id: pid}); }
function rndNotes(pid) {
  var d = document.querySelector('.dash');
  var cur = d ? (d.getAttribute('data-notes') || '') : '';
  var n = window.prompt('Notes for this project:', cur);
  if (n === null) return;
  _lifecycle('/api/rnd/set_notes', {id: pid, notes: n});
}
function rndBlurb(pid) {
  var d = document.querySelector('.dash');
  var cur = d ? (d.getAttribute('data-blurb') || '') : '';
  var n = window.prompt('What this project is (blurb):', cur);
  if (n === null) return;
  _lifecycle('/api/rnd/set_blurb', {id: pid, blurb: n});
}

// ── Task linking (surfaces the existing link_task endpoint) ─────────────────
function rndLinkTask(el) {
  // Project id rides via the element's data-project attribute (the browser
  // entity-decodes it for us), avoiding the inline-string-literal trap.
  var pid = el.dataset.project || '';
  var t = window.prompt('Link a task to this project (type the task text):', '');
  if (t === null) return;
  t = t.trim();
  if (!t) return;
  _lifecycle('/api/rnd/link_task', {text: t, project_id: pid});
}
function rndUnlinkTask(el) {
  // Read the raw task text from the DOM dataset (entity-decoded by the
  // browser) so it matches the markdown task text verbatim — works even when
  // the text contains apostrophes, quotes, &, <, or >.
  var text = el.dataset.task || '';
  if (!confirm('Unlink this task from the project?')) return;
  // An empty project_id unlinks the matching task (backend contract).
  _lifecycle('/api/rnd/link_task', {text: text, project_id: ''});
}

// ════════════════════════════════════════════════════════════════════════════
// Wave 4 — stacking window-manager UI for ConPTY terminal sessions.
//
// A top bar of terse, STATUS-COLORED buttons (one per live managed session,
// labeled "<lane> <index>"); clicking opens/attaches that session's terminal in
// a draggable / resizable / minimizable WINDOW that stacks like a brick. Minimize
// keeps the session/process RUNNING (it only hides the window). The X control is
// KILL — gated behind a confirm() — which POSTs /api/rnd/term_kill, removes the
// window, and refreshes the bar. xterm.js is mounted in each window over the
// Wave-3 transport (WS first, SSE-out + POST-in fallback). All POSTs are
// token-aware via _postJson; the WS/SSE URLs carry ?token= from localStorage.
//
// This is a NEW surface; it does NOT touch the v2 console drawer (openTerminal /
// launchLane) above.
// ════════════════════════════════════════════════════════════════════════════

// MANAGED: session_id -> {session_id, lane, backend, status, label, idx}
var MANAGED = {};
// WINDOWS: session_id -> {el, term, transport, body} for an OPEN window.
var WINDOWS = {};
var _laneCounters = {};   // lane -> running index, for "plan 1", "plan 2" labels
var _winZ = 30;           // z-index cursor so a focused window comes forward

// Map a session status to the LOCKED color bucket (MASTER-PLAN §D / §E):
//   running              -> green  (working; ignore)
//   needs-attention/done -> amber  (come look)
//   failed               -> red
//   idle / unknown       -> grey
function _statusColor(status) {
  if (status === 'running') return 'green';
  if (status === 'needs-attention' || status === 'done') return 'amber';
  if (status === 'failed') return 'red';
  return 'grey';
}

// Fetch the project's live managed sessions from the registry and paint the bar.
async function loadSessions() {
  var url = '/api/rnd/term_sessions?project_id=' + encodeURIComponent(PROJECT_ID);
  var data;
  try {
    var r = await fetch(url);
    data = await r.json();
  } catch (e) { return; }
  if (!data || !data.ok) return;
  var sessions = data.sessions || [];
  // Rebuild the MANAGED map, preserving a stable per-lane index per session.
  var seen = {};
  _laneCounters = {};
  sessions.sort(function (a, b) {
    return (a.created_at || 0) - (b.created_at || 0);
  });
  for (var i = 0; i < sessions.length; i++) {
    var s = sessions[i];
    if (!s.session_id) continue;
    var lane = s.lane || 'session';
    _laneCounters[lane] = (_laneCounters[lane] || 0) + 1;
    var prev = MANAGED[s.session_id] || {};
    MANAGED[s.session_id] = {
      session_id: s.session_id, lane: lane, backend: s.backend || '',
      status: s.status || 'idle', label: s.label || '',
      idx: prev.idx || _laneCounters[lane]
    };
    seen[s.session_id] = true;
  }
  // Drop sessions the registry no longer reports (and close any stale window).
  for (var sid in MANAGED) {
    if (!seen[sid]) { _closeWindow(sid); delete MANAGED[sid]; }
  }
  renderSessionBar();
}

function renderSessionBar() {
  var host = document.getElementById('sessionBtns');
  if (!host) return;
  host.innerHTML = '';
  var ids = Object.keys(MANAGED);
  for (var i = 0; i < ids.length; i++) {
    var s = MANAGED[ids[i]];
    var btn = document.createElement('button');
    btn.className = 'sessbtn' + (WINDOWS[s.session_id] ? ' open' : '');
    btn.setAttribute('data-session', s.session_id);
    btn.setAttribute('data-status', s.status);
    var dot = document.createElement('span');
    dot.className = 'sess-dot sess-dot--' + _statusColor(s.status);
    btn.appendChild(dot);
    var txt = document.createElement('span');
    txt.textContent = (s.label ? s.label : (s.lane + ' ' + s.idx));
    btn.appendChild(txt);
    (function (sid) {
      btn.onclick = function () { openSessionWindow(sid); };
    })(s.session_id);
    host.appendChild(btn);
  }
  var hint = document.getElementById('sessionBarHint');
  if (hint) hint.style.display = ids.length ? 'none' : '';
}

// Start a brand-new managed terminal session for a lane (Wave-3 term_start),
// then refresh the bar and open its window. backend defaults to claude.
async function newTermSession(lane, backend, opts) {
  backend = backend || 'claude';
  var payload = {project_id: PROJECT_ID, lane: lane, backend: backend};
  // Wave 6 seam: a seed hint (the source session id) rides into term_start so
  // Wave 7 can build the stage-handoff on top of it. term_start tolerates the
  // extra field today (start_session ignores it); Wave 7 wires it through.
  if (opts && opts.seed_session) payload.seed_session = opts.seed_session;
  var r, data;
  try {
    r = await _postJson('/api/rnd/term_start', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_start', payload);
      data = await r.json();
    }
  } catch (e) { alert('[terminal start error] ' + e.message); return; }
  if (!data.ok || !data.session) {
    alert('[terminal refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || lane, backend: rec.backend || backend,
    status: rec.status || 'running', label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] = (_laneCounters[rec.lane || lane] || 0) + 1)
  };
  renderSessionBar();
  openSessionWindow(sid);
  // Re-sync indices/labels from the registry shortly after.
  setTimeout(loadSessions, 600);
}

// Open (or focus) a stacking terminal window for a managed session.
function openSessionWindow(sessionId) {
  var s = MANAGED[sessionId];
  if (!s) return;
  if (WINDOWS[sessionId]) { _focusWindow(sessionId); return; }
  var layer = document.getElementById('windowLayer');
  if (!layer) return;

  var win = document.createElement('div');
  win.className = 'termwin';
  win.setAttribute('data-session', sessionId);
  // Brick-stack: offset each new window so they stack like bricks (2–3 visible).
  var n = Object.keys(WINDOWS).length;
  win.style.left = (16 + (n % 3) * 36) + 'px';
  win.style.top = (16 + n * 30) + 'px';
  win.style.zIndex = (++_winZ);

  var bar = document.createElement('div');
  bar.className = 'wintitle';
  var label = document.createElement('span');
  label.className = 'wt-label';
  label.textContent = (s.label ? s.label : (s.lane + ' ' + s.idx));
  var meta = document.createElement('span');
  meta.className = 'wt-meta';
  meta.textContent = s.backend ? ('· ' + s.backend) : '';
  var sp = document.createElement('span');
  sp.className = 'wt-sp';
  var minBtn = document.createElement('button');
  minBtn.className = 'winbtn min';
  minBtn.title = 'Minimize (keeps the session running)';
  minBtn.textContent = '–';
  minBtn.onclick = function (e) { e.stopPropagation(); _toggleMinimize(sessionId); };
  var killBtn = document.createElement('button');
  killBtn.className = 'winbtn kill';
  killBtn.title = 'Kill this session';
  killBtn.textContent = '×';
  killBtn.onclick = function (e) { e.stopPropagation(); killSession(sessionId); };
  bar.appendChild(label); bar.appendChild(meta);
  bar.appendChild(sp); bar.appendChild(minBtn); bar.appendChild(killBtn);

  var body = document.createElement('div');
  body.className = 'termbody';

  var grip = document.createElement('div');
  grip.className = 'winresize';

  win.appendChild(bar); win.appendChild(body); win.appendChild(grip);
  layer.appendChild(win);

  WINDOWS[sessionId] = {el: win, body: body, term: null, transport: null};
  win.addEventListener('mousedown', function () { _focusWindow(sessionId); });
  _wireDrag(win, bar);
  _wireResize(win, grip);
  _mountTerminal(sessionId, body);
  renderSessionBar();
}

function _focusWindow(sessionId) {
  var w = WINDOWS[sessionId];
  if (w && w.el) w.el.style.zIndex = (++_winZ);
}

function _toggleMinimize(sessionId) {
  var w = WINDOWS[sessionId];
  if (!w || !w.el) return;
  // Minimize ONLY hides/collapses the window — it NEVER kills the session.
  w.el.classList.toggle('minimized');
}

function _closeWindow(sessionId) {
  var w = WINDOWS[sessionId];
  if (!w) return;
  try { if (w.transport && w.transport.close) w.transport.close(); } catch (e) {}
  try { if (w.term && w.term.dispose) w.term.dispose(); } catch (e) {}
  if (w.el && w.el.parentNode) w.el.parentNode.removeChild(w.el);
  delete WINDOWS[sessionId];
}

// X = KILL with a confirm gate. Only on YES do we POST term_kill, then close the
// window + refresh the bar. (Minimize, by contrast, never kills.)
async function killSession(sessionId) {
  var s = MANAGED[sessionId];
  var name = s ? (s.label || (s.lane + ' ' + s.idx)) : sessionId;
  if (!confirm('Kill the "' + name + '" terminal session? This stops its process.')) return;
  try {
    var r = await _postJson('/api/rnd/term_kill', {session: sessionId});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_kill', {session: sessionId});
      data = await r.json();
    }
  } catch (e) { alert('[kill error] ' + e.message); }
  _closeWindow(sessionId);
  delete MANAGED[sessionId];
  renderSessionBar();
  setTimeout(loadSessions, 400);
}

// Mount xterm.js in the window body over the Wave-3 transport. Prefer the
// hand-rolled WebSocket (term_ws); fall back to SSE-out (term_stream2) + POST-in
// (term_input2). Bytes from read_since are decoded str sent as UTF-8 text.
function _mountTerminal(sessionId, body) {
  var w = WINDOWS[sessionId];
  if (!w) return;
  if (!window.Terminal) {
    body.textContent = 'terminal component failed to load';
    return;
  }
  var _termTheme = {background: '#0c0e14'};
  var term = new window.Terminal({convertEol: true, fontSize: 12, theme: _termTheme});
  term.open(body);
  w.term = term;
  var tok = _anchorToken();
  var tq = tok ? ('&token=' + encodeURIComponent(tok)) : '';

  // Outbound user keystrokes → term_input2 (works for BOTH transports; the WS
  // also accepts frames, but routing input through the POST keeps one path).
  term.onData(function (d) {
    _postJson('/api/rnd/term_input2', {session: sessionId, data: d});
  });
  // Resize → term_resize (best-effort, token-aware).
  term.onResize(function (sz) {
    _postJson('/api/rnd/term_resize',
              {session: sessionId, cols: sz.cols, rows: sz.rows});
  });

  // Transport: try WebSocket first; on error fall back to the SSE stream.
  var wsProto = (location.protocol === 'https:') ? 'wss:' : 'ws:';
  var wsUrl = wsProto + '//' + location.host +
              '/api/rnd/term_ws?session=' + encodeURIComponent(sessionId) + tq;
  var sseStarted = false;
  function startSSE() {
    if (sseStarted) return;
    sseStarted = true;
    var sseUrl = '/api/rnd/term_stream2?session=' + encodeURIComponent(sessionId) + tq;
    var es = new EventSource(sseUrl);
    w.transport = es;
    es.addEventListener('output', function (ev) {
      try { var p = JSON.parse(ev.data); if (p.text) term.write(p.text); } catch (e) {}
    });
    es.addEventListener('done', function () { try { es.close(); } catch (e) {} });
    es.onerror = function () { /* bounded server stream; let it close */ };
  }
  try {
    var ws = new WebSocket(wsUrl);
    w.transport = ws;
    ws.onmessage = function (ev) { term.write(ev.data); };
    ws.onclose = function () {
      // If the WS never carried data (e.g. upgrade unsupported), use SSE.
      if (!sseStarted) startSSE();
    };
    ws.onerror = function () { try { ws.close(); } catch (e) {} startSSE(); };
  } catch (e) { startSSE(); }
}

// Titlebar drag — move the window within the layer (brick repositioning).
function _wireDrag(win, handle) {
  handle.addEventListener('mousedown', function (e) {
    if (e.target.classList && e.target.classList.contains('winbtn')) return;
    e.preventDefault();
    var sx = e.clientX, sy = e.clientY;
    var ox = win.offsetLeft, oy = win.offsetTop;
    function mv(ev) {
      win.style.left = Math.max(0, ox + (ev.clientX - sx)) + 'px';
      win.style.top = Math.max(0, oy + (ev.clientY - sy)) + 'px';
    }
    function up() {
      document.removeEventListener('mousemove', mv);
      document.removeEventListener('mouseup', up);
    }
    document.addEventListener('mousemove', mv);
    document.addEventListener('mouseup', up);
  });
}

// Resize handle — grow/shrink the window from its bottom-right corner.
function _wireResize(win, grip) {
  grip.addEventListener('mousedown', function (e) {
    e.preventDefault();
    e.stopPropagation();
    var sx = e.clientX, sy = e.clientY;
    var ow = win.offsetWidth, oh = win.offsetHeight;
    function mv(ev) {
      win.style.width = Math.max(260, ow + (ev.clientX - sx)) + 'px';
      win.style.height = Math.max(120, oh + (ev.clientY - sy)) + 'px';
    }
    function up() {
      document.removeEventListener('mousemove', mv);
      document.removeEventListener('mouseup', up);
    }
    document.addEventListener('mousemove', mv);
    document.addEventListener('mouseup', up);
  });
}
"""


def _fmt_cost(rollup: dict) -> str:
    """Render a one-line cost/time/tokens summary from a rollup dict."""
    cost = rollup.get("total_cost_usd", 0.0) or 0.0
    dur_ms = rollup.get("duration_ms", 0) or 0
    toks = rollup.get("total_tokens", 0) or 0
    secs = dur_ms / 1000.0
    return (f"${cost:.4f} · {secs:.1f}s · {toks:,} tok "
            f"({rollup.get('effort_count', 0)} effort"
            f"{'s' if rollup.get('effort_count', 0) != 1 else ''})")


def render_cost_rollup_html(project_id: str, folder_path: str) -> str:
    """Render the per-project cost/time/tokens rollup (tile + dashboard, Wave 7).

    Shows the project total plus a per-lane breakdown. Best-effort: a project
    with no efforts shows zeros and never crashes.
    """
    try:
        roll = _eh.project_rollup(project_id, folder_path)
    except Exception:
        return ""
    total = roll.get("total", {})
    lanes = roll.get("lanes", {})
    rows = []
    for lane in _eh.ROLLUP_LANES:
        lr = lanes.get(lane, {})
        if not lr.get("effort_count"):
            continue
        rows.append(
            f"<div class='rnd-lane'>{html_lib.escape(lane)}: "
            f"{html_lib.escape(_fmt_cost(lr))}</div>"
        )
    breakdown = ("<div class='rnd-status-line'>" + "".join(rows) + "</div>"
                 if rows else "")
    n_imp = int(total.get("discovered_count", 0) or 0)
    imported_bit = (f" · <span class='rnd-imported'>{n_imp} imported</span>"
                    if n_imp else "")
    return (
        "<h2>Cost rollup</h2>"
        f"<p style='font-size:15px'><strong>Total:</strong> "
        f"{html_lib.escape(_fmt_cost(total))}{imported_bit}</p>"
        f"{breakdown}"
    )


# ── Task ↔ project link (Wave 9 — activates the parsed Project: field) ──────

def project_tasks(project_id: str) -> list:
    """Return every active task whose ``Project: <id>`` field matches.

    ``gather_all()`` already parses each task's ``project`` field (Wave 3) and
    deduplicates; Wave 9 simply FILTERS on it. This is the data behind the
    project-tasks view (AC2). Returns the matching task dicts (order preserved).
    """
    pid = (project_id or "").strip()
    if not pid:
        return []
    _projects, tasks, _inbox = gather_all()
    return [t for t in tasks if (t.get("project") or "").strip() == pid]


def render_project_tasks_html(project_id: str) -> str:
    """Render the linked-tasks strip inside the project window (v2 Wave 4 / §G).

    Surfaces the existing ``link_task`` capability: lists every active task whose
    ``Project: <id>`` matches, each with an Unlink affordance, plus a "Link task"
    button that calls the existing ``/api/rnd/link_task`` endpoint. Replaces the
    old dead-end "no tasks linked yet" message with a working strip.
    """
    pid_attr = html_lib.escape(project_id, quote=True)
    link_btn = (f"<button class='rnd-mini' data-project=\"{pid_attr}\" "
                f"onclick=\"rndLinkTask(this)\" "
                f"title='Link an existing task to this project'>+ Link task"
                f"</button>")
    header = (f"<h2 style='display:flex;align-items:center;gap:10px'>Tasks "
              f"{link_btn}</h2>")
    tasks = project_tasks(project_id)
    if not tasks:
        return (header + "<p class='rnd-empty-tasks' style='color:#8a90a2'>"
                "No tasks linked to this project yet. Use "
                "<strong>+ Link task</strong> above (or "
                "<code>anchor.py link \"task\" --project &lt;id&gt;</code>).</p>")
    rows = []
    for t in tasks:
        mark = "✓" if t.get("done") else "○"
        txt_raw = t.get("text", "")
        txt = html_lib.escape(txt_raw)
        txt_attr = html_lib.escape(txt_raw, quote=True)
        dom = html_lib.escape(t.get("domain", ""))
        pr = t.get("priority", 2)
        # Task identity rides via data- attributes (entity-decoded by the
        # browser), NOT as an inline JS string arg — so text with apostrophes,
        # quotes, &, <, > round-trips verbatim to /api/rnd/link_task.
        unlink = (f"<button class='rnd-mini rnd-unlink' "
                  f"data-task=\"{txt_attr}\" data-project=\"{pid_attr}\" "
                  f"onclick=\"rndUnlinkTask(this)\" "
                  f"title='Unlink this task'>Unlink</button>")
        rows.append(
            f"<li class='linked-task' style='display:flex;align-items:center;"
            f"gap:8px;margin-bottom:5px'>"
            f"<span style='color:#6c9cfc'>{mark}</span> {txt} "
            f"<span style='color:#8a90a2;font-size:12px'>"
            f"(P{pr} · {dom})</span>"
            f"<span style='margin-left:auto'>{unlink}</span></li>"
        )
    return (header + "<ul style='list-style:none;padding:0'>"
            + "".join(rows) + "</ul>")


def render_deliverables_html(project_id: str, folder_path: str) -> str:
    """Render the project's deliverable status records (Wave 9 AC1).

    Read-only: shows each deliverable's type + last run status (the dashboard
    surfacing of the status records ``deliverables.run_deliverable`` persists).
    """
    try:
        records = _deliv.list_status(folder_path, project_id)
    except Exception:
        records = []
    if not records:
        return ("<h2>Deliverables</h2><p style='color:#8a90a2'>"
                "No deliverable runs recorded yet.</p>")
    colors = {_deliv.STATUS_SUCCESS: "#4caf78",
              _deliv.STATUS_FAILED: "#e06c75",
              _deliv.STATUS_TIMED_OUT: "#d6a35c"}
    rows = []
    for r in records:
        status = r.get("status", "")
        color = colors.get(status, "#8a90a2")
        name = html_lib.escape(r.get("name", "") or r.get("deliverable_id", ""))
        dtype = html_lib.escape(r.get("type", ""))
        rows.append(
            f"<li>{name} <span style='color:#8a90a2;font-size:12px'>"
            f"[{dtype}]</span> — <span style='color:{color}'>"
            f"{html_lib.escape(status)}</span></li>"
        )
    return ("<h2>Deliverables</h2><ul style='list-style:none;padding:0'>"
            + "".join(rows) + "</ul>")


# ── Change operations ──────────────────────────────────────────────────
#
# Every function that MUTATES a markdown or JSON file is wrapped with
# @_with_write_lock. The lock is a process-wide RLock (re-entrant), so nested
# mutators (e.g. mark_done -> log_change) acquire it safely. Under
# ThreadingHTTPServer this serializes concurrent writers so no update is lost.

import functools as _functools


def _with_write_lock(fn):
    @_functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        with WRITE_LOCK:
            return fn(*args, **kwargs)
    return _wrapped


@_with_write_lock
def log_change(message):
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    LOGS_DIR.mkdir(exist_ok=True)
    log_file = LOGS_DIR / f"{today}.md"
    if not log_file.exists():
        day_name = datetime.now().strftime("%A")
        log_file.write_text(f"# {today} — {day_name}\n\n## Changes\n", encoding="utf-8")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"- {now} — {message}\n")
    print(f"  Logged: {now} — {message}")


@_with_write_lock
def mark_done(task_text):
    search = task_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[ \]', line) and search in line.lower():
                new_lines.append(line.replace("[ ]", "[x]", 1))
                found = True
                changed = True
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    if found:
        log_change(f"Completed: {task_text}")
    return found


@_with_write_lock
def mark_undone(task_text):
    search = task_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[[xX]\]', line) and search in line.lower():
                new_lines.append(re.sub(r'\[[xX]\]', '[ ]', line, count=1))
                found = True
                changed = True
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    if found:
        log_change(f"Reopened: {task_text}")
    return found


@_with_write_lock
def add_task(text, domain="academic", priority=2, energy="med", due="", notes=""):
    due_str = f" — Due: {due}" if due else ""
    notes_str = f" — Notes: {notes}" if notes else ""
    line = f"- [ ] {text} — Priority: {priority} — energy: {energy} — [{domain}]{due_str}{notes_str}"

    def _insert(filepath, section_names):
        if not filepath or not filepath.exists():
            return False
        content = _read_md_text(filepath)
        for section in section_names:
            idx = content.find(section)
            if idx >= 0:
                ns = content.find("\n##", idx + len(section))
                if ns < 0:
                    ns = len(content)
                content = content[:ns].rstrip() + "\n" + line + "\n\n" + content[ns:]
                filepath.write_text(content, encoding="utf-8")
                return True
        return False

    _insert(DASHBOARD_MD, ["## Today's Priorities", "## Active Priorities"])
    if DOMAINS_DIR.exists():
        _insert(DOMAINS_DIR / f"{domain}.md", ["## Active Tasks"])

    log_change(f"Added task: {text} [{domain}] P{priority}")


@_with_write_lock
def capture_inbox(text, domain=""):
    today = date.today().isoformat()
    domain_tag = f" [{domain}]" if domain else ""
    line = f"- {today}: {text}{domain_tag}"
    if not INBOX_MD.exists():
        # Fresh/empty data dir: create a minimal inbox so the capture is never
        # silently dropped.
        INBOX_MD.write_text("# Inbox\n\n", encoding="utf-8")
    content = _read_md_text(INBOX_MD)
    content = content.rstrip() + "\n" + line + "\n"
    INBOX_MD.write_text(content, encoding="utf-8")
    log_change(f"Captured: {text}")


@_with_write_lock
def link_task(task_text, project_id):
    """Link a task to an R&D project — set/maintain its ``Project: <id>`` field.

    Wave 9 activation: edits ONLY the ``Project:`` field on the first matching
    active task line, preserving every other character verbatim (byte-stable for
    untouched tasks; clean round-trip for linked ones). An empty ``project_id``
    unlinks. Mirrors ``anchor.link_task``. Returns True if a task was updated.
    """
    search = task_text.lower().strip()
    new_id = (project_id or "").strip()
    found = False
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if (not found and re.match(r'\s*-\s*\[([ xX])\]', line)
                    and search in line.lower()):
                existing = re.search(r'(\s*—\s*Project:\s*)([^\s—]+)', line, re.I)
                if existing:
                    if new_id:
                        new_line = (line[:existing.start(2)] + new_id
                                    + line[existing.end(2):])
                    else:
                        new_line = line[:existing.start(1)] + line[existing.end(2):]
                else:
                    new_line = line.rstrip() + f" — Project: {new_id}" if new_id else line
                if new_line != line:
                    changed = True
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    if found:
        log_change(f"Linked task '{task_text}' to project {new_id}" if new_id
                   else f"Unlinked task '{task_text}'")
    return found


@_with_write_lock
def edit_task(old_text, new_text=None, new_priority=None, new_domain=None, new_energy=None, new_due=None, new_notes=None):
    """Edit a task's properties across all markdown files. Only changes specified fields."""
    search = old_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue

        # Infer domain from filename: domains/family.md → "family"
        file_domain = None
        if md_file.parent == DOMAINS_DIR:
            file_domain = md_file.stem  # e.g. "family", "academic", "writing", "commercial"

        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[([ xX])\]', line) and search in line.lower():
                check_m = re.match(r'(\s*-\s*\[)([ xX])(\]\s*)', line)
                if check_m:
                    prefix = check_m.group(1)
                    check_state = check_m.group(2)
                    rest = line[check_m.end():]

                    # Parse existing text (everything before the first " — ")
                    raw_rest = line[check_m.end():]
                    text_end = raw_rest.find(" — ")
                    existing_text = raw_rest[:text_end].strip(' *') if text_end >= 0 else raw_rest.strip(' *')
                    existing_priority = 2
                    existing_energy = "med"
                    existing_due = ""

                    # Domain: prefer file-inferred domain, then tag in line, then "personal"
                    existing_domain = file_domain or "personal"
                    dm = re.search(r'\[(\w+)\]', rest)
                    if dm and not file_domain:
                        existing_domain = dm.group(1).lower()

                    pm = re.search(r'Priority:\s*(\d)', rest)
                    if pm: existing_priority = int(pm.group(1))
                    em = re.search(r'energy:\s*(\w+)', rest, re.I)
                    if em: existing_energy = em.group(1).lower()
                    due_m = re.search(r'Due:\s*([\d/\-\w]+)', rest, re.I)
                    if due_m: existing_due = due_m.group(1)
                    existing_notes = ""
                    notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|Project|\[)|$)', rest, re.I)
                    if not notes_m:
                        notes_m = re.search(r'Notes:\s*(.+?)$', rest, re.I)
                    if notes_m: existing_notes = notes_m.group(1).strip().rstrip(' —')
                    # Preserve the optional Project: <id> link unchanged (Wave 3).
                    existing_project = ""
                    proj_m = re.search(r'Project:\s*([^\s—]+)', rest, re.I)
                    if proj_m: existing_project = proj_m.group(1).strip()

                    # Apply only specified changes
                    t_text = new_text if new_text is not None else existing_text
                    t_priority = new_priority if new_priority is not None else existing_priority
                    t_energy = new_energy if new_energy is not None else existing_energy
                    t_domain = new_domain if new_domain is not None else existing_domain
                    t_due = new_due if new_due is not None else existing_due
                    t_notes = new_notes if new_notes is not None else existing_notes
                    due_str = f" — Due: {t_due}" if t_due else ""
                    notes_str = f" — Notes: {t_notes}" if t_notes else ""
                    project_str = f" — Project: {existing_project}" if existing_project else ""

                    new_line = f"{prefix}{check_state}] {t_text} — Priority: {t_priority} — energy: {t_energy} — [{t_domain}]{due_str}{project_str}{notes_str}"
                    new_lines.append(new_line)
                    found = True
                    changed = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    if found:
        changes = []
        if new_text and new_text != old_text:
            changes.append(f"renamed to '{new_text}'")
        if new_priority is not None:
            changes.append(f"P{new_priority}")
        if new_domain:
            changes.append(f"[{new_domain}]")
        if new_due is not None:
            changes.append(f"due {new_due}" if new_due else "due removed")
        log_change(f"Edited task '{old_text}': {', '.join(changes)}")
    return found


@_with_write_lock
def edit_project(old_name, new_name=None, new_priority=None, new_domain=None,
                 new_status=None, new_effort=None, new_due=None, new_next=None):
    """Edit a project's properties in PROJECTS.md files."""
    search = old_name.lower().strip()
    found = False

    for proj_file in [PROJECTS_MD]:
        if not proj_file or not proj_file.exists():
            continue
        text = _read_md_text(proj_file)
        lines = text.splitlines()
        new_lines = []
        in_project = False
        i = 0
        while i < len(lines):
            line = lines[i]
            h2 = re.match(r'^##\s+(.+)', line)
            if h2 and search in h2.group(1).lower():
                in_project = True
                found = True
                # Replace name if needed
                if new_name:
                    new_lines.append(f"## {new_name}")
                else:
                    new_lines.append(line)
                i += 1
                # Process key-value lines within this project section
                while i < len(lines):
                    line = lines[i]
                    # Stop at next project heading
                    if re.match(r'^##\s+', line):
                        in_project = False
                        break
                    kv = re.match(r'(\s*-\s*\*\*)(\w[\w\s]*?)(:\*\*\s*)(.*)', line)
                    if kv:
                        key = kv.group(2).strip().lower()
                        indent = kv.group(1)
                        colon = kv.group(3)
                        if key == "priority" and new_priority is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_priority}")
                        elif key == "domain" and new_domain:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_domain}")
                        elif key == "status" and new_status:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_status}")
                        elif key in ("effort", "effort level") and new_effort:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_effort}")
                        elif key in ("deadline", "due") and new_due is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_due}")
                        elif key.startswith("next") and new_next is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_next}")
                        else:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)
                    i += 1
                continue
            else:
                if h2:
                    in_project = False
                new_lines.append(line)
            i += 1
        proj_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    if found:
        changes = []
        if new_name and new_name != old_name:
            changes.append(f"renamed to '{new_name}'")
        if new_priority is not None:
            changes.append(f"P{new_priority}")
        if new_domain:
            changes.append(f"[{new_domain}]")
        if new_status:
            changes.append(f"status: {new_status}")
        if new_next is not None:
            changes.append(f"next: {new_next}")
        log_change(f"Edited project '{old_name}': {', '.join(changes)}")
    return found


def _remove_task_from_files(task_text):
    """Remove a task line from all markdown files. Returns the task dict if found."""
    search = task_text.lower().strip()
    found_task = None
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[([ xX])\]', line) and search in line.lower():
                # Parse the task before removing
                if not found_task:
                    tm = re.match(r'\s*-\s*\[([ xX])\]\s*\*?\*?(.*?)(?:\*?\*?\s*—\s*(.*))?$', line)
                    if tm:
                        meta = tm.group(3) or ""
                        dm = re.search(r'\[(\w+)\]', meta)
                        pm = re.search(r'Priority:\s*(\d)', meta)
                        notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|\[)|$)', meta, re.I)
                        if not notes_m:
                            notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
                        found_task = {
                            "text": task_text,
                            "domain": dm.group(1).lower() if dm else "",
                            "priority": int(pm.group(1)) if pm else 2,
                            "notes": notes_m.group(1).strip().rstrip(' —') if notes_m else "",
                        }
                changed = True
                continue  # skip this line (remove it)
            new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return found_task


def _append_to_archive(filepath, task_dict):
    """Append a task entry to an archive file (CANCELLED.md or SAVED_FOR_LATER.md)."""
    if not filepath:
        return
    today = date.today().isoformat()
    domain_str = f" — [{task_dict.get('domain', '')}]" if task_dict.get('domain') else ""
    priority_str = f" — P{task_dict.get('priority', 2)}"
    notes_str = f" — Notes: {task_dict['notes']}" if task_dict.get('notes') else ""
    line = f"- {today}: {task_dict['text']}{domain_str}{priority_str}{notes_str}"

    if not filepath.exists():
        filepath.write_text(f"# {filepath.stem.replace('_', ' ').title()}\n\n", encoding="utf-8")
    content = _read_md_text(filepath)
    content = content.rstrip() + "\n" + line + "\n"
    filepath.write_text(content, encoding="utf-8")


@_with_write_lock
def cancel_task(task_text):
    """Cancel a task: remove from active lists, add to CANCELLED.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(CANCELLED_MD, task)
        log_change(f"Cancelled: {task_text}")
        return True
    return False


@_with_write_lock
def save_for_later(task_text):
    """Save a task for later: remove from active lists, add to SAVED_FOR_LATER.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(SAVED_FOR_LATER_MD, task)
        log_change(f"Saved for later: {task_text}")
        return True
    return False


@_with_write_lock
def restore_task(task_text, from_archive="saved"):
    """Restore a task from an archive back to the active dashboard."""
    archive_file = SAVED_FOR_LATER_MD if from_archive == "saved" else CANCELLED_MD
    if not archive_file or not archive_file.exists():
        return False
    text = _read_md_text(archive_file)
    search = task_text.lower().strip()
    found = None
    new_lines = []
    for line in text.splitlines():
        if search in line.lower() and not found:
            # Parse the archived task
            m = re.match(r'\s*-\s*\d{4}-\d{2}-\d{2}:\s*(.*?)(?:\s*—\s*\[(\w+)\])?(?:\s*—\s*P(\d))?(?:\s*—\s*Notes:\s*(.*))?$', line)
            if m:
                found = {
                    "text": m.group(1).strip(),
                    "domain": m.group(2) or "personal",
                    "priority": int(m.group(3)) if m.group(3) else 2,
                    "notes": m.group(4).strip() if m.group(4) else "",
                }
            continue  # remove from archive
        new_lines.append(line)
    if found:
        archive_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        add_task(found["text"], found["domain"], found["priority"], "med", "", found["notes"])
        log_change(f"Restored from {from_archive}: {task_text}")
        return True
    return False


# ── HTML Dashboard Generation ─────────────────────────────────────────

def generate_html(projects, tasks, inbox):
    """Generate a full standalone HTML dashboard matching the original Anchor style."""
    today_str = datetime.now().strftime("%A, %B %d, %Y")
    active = [t for t in tasks if not t["done"]]
    done_tasks = [t for t in tasks if t["done"]]
    # Whether the server requires a token (remote/exposed). Embedded as a bool so
    # the page can prompt for the token ONCE on first load — never the token value
    # itself (GET is unauthenticated; embedding the secret would leak it).
    auth_required_js = "true" if _paths.expected_token() else "false"

    # ── Health banner ──
    # If the most recent health report flagged issues, show a banner at the top.
    health_banner_html = ""
    hr = latest_health_report()
    if hr is not None:
        report_date, status, _ = hr
        if "ISSUE" in status.upper() or "FAIL" in status.upper() or "ERROR" in status.upper():
            health_banner_html = (
                f'<div style="background:#3b1f1f;border:1px solid #9b3a3a;color:#ffb3b3;'
                f'padding:10px 14px;border-radius:6px;margin:0 0 10px 0;font-size:13px;">'
                f'<strong style="color:#ff7a7a">&#9888; Health check found issues</strong>'
                f' on {html_lib.escape(report_date)}. '
                f'See <code style="background:#2a1414;padding:1px 5px;border-radius:3px">'
                f'health_reports/{html_lib.escape(report_date)}.md</code> for details.'
                f'</div>'
            )

    # Domain sort order: commercial first, then academic, family, writing, personal
    domain_sort_order = {"commercial": 0, "academic": 1, "family": 2, "writing": 3, "personal": 4}
    # Energy sort order: high-energy tasks first, then med, then low
    energy_sort_order = {"high": 0, "med": 1, "medium": 1, "low": 2}
    today_iso = date.today().isoformat()

    # Top Tasks = P1 tasks + anything due today (any priority)
    # Other Tasks = everything P2+ (that isn't due today)
    # Within Top Tasks: due today first, then by domain order (commercial → academic → family → writing → personal)
    p1 = [t for t in active if t["priority"] == 1]
    due_today_non_p1 = [t for t in active if t["priority"] != 1 and t.get("due") and t["due"] <= today_iso]
    p1_sorted = sorted(p1, key=lambda t: (
        0 if t.get("due") and t["due"] <= today_iso else 1,  # due today first
        domain_sort_order.get(t["domain"], 9),
        t["text"]
    ))

    seen_top = set()
    top_tasks = []
    for t in due_today_non_p1 + p1_sorted:
        key = t["text"].lower()[:60]
        if key not in seen_top:
            seen_top.add(key)
            top_tasks.append(t)
    top_done = len([t for t in top_tasks if t["done"]])
    top_task_texts = set(t["text"].lower()[:60] for t in top_tasks)

    # P1 and P2+ projects
    p1_projects = sorted([p for p in projects if p["priority"] == 1 and p["status"] == "active"],
                         key=lambda p: (0 if p.get("due") else 1, p.get("due", ""), p["name"]))
    p2_projects = sorted([p for p in projects if p["priority"] >= 2 and p["status"] == "active"],
                         key=lambda p: (p["priority"], p["name"]))

    # P2+ tasks not already in Top Tasks (other tasks).
    # Sort: by domain (commercial → academic → family → writing → personal),
    # then by energy (high → med → low), then by priority number, then text.
    other_tasks = sorted(
        [t for t in active if t["priority"] >= 2 and t["text"].lower()[:60] not in top_task_texts],
        key=lambda t: (
            domain_sort_order.get(t["domain"], 9),
            energy_sort_order.get(t.get("energy", "med").lower(), 1),
            t["priority"],
            t["text"],
        ),
    )

    # Group by domain for sidebar
    domain_counts = {}
    for t in active:
        domain_counts[t["domain"]] = domain_counts.get(t["domain"], 0) + 1

    def esc(s):
        return html_lib.escape(str(s)).replace("'", "&#39;").replace('"', "&quot;")

    def linkify_notes(s):
        """Escape HTML, then convert URLs into clickable <a> tags."""
        escaped = html_lib.escape(str(s))
        return re.sub(
            r'(https?://[^\s<>&\'"]+)',
            r'<a href="\1" target="_blank" rel="noopener" onclick="event.stopPropagation()">\1</a>',
            escaped
        )

    def notes_popover(notes_text):
        """Build a hoverable popover element for task notes."""
        if not notes_text:
            return ""
        linked = linkify_notes(notes_text)
        return f'''<span class="notes-wrapper">
            <span class="notes-indicator">&#128203;</span>
            <div class="notes-popover">{linked}</div>
        </span>'''

    def js_safe(s):
        """Escape a string for safe use inside JS onclick='func(\"...\")' attributes."""
        import base64
        return base64.b64encode(s.encode('utf-8')).decode('ascii')

    def task_data_b64(t):
        """Base64-encode a task's full data dict for safe embedding in HTML attributes."""
        import base64
        d = {"text": t["text"], "priority": t["priority"], "domain": t["domain"],
             "energy": t.get("energy","med"), "due": t.get("due",""), "notes": t.get("notes","")}
        return base64.b64encode(json.dumps(d).encode('utf-8')).decode('ascii')

    def project_data_b64(p):
        """Base64-encode a project's full data dict for safe embedding in HTML attributes."""
        import base64
        d = {"name": p["name"], "priority": p["priority"], "domain": p["domain"],
             "status": p.get("status","active"), "effort": p.get("effort","high"),
             "due": p.get("due",""), "next": p.get("next","")}
        return base64.b64encode(json.dumps(d).encode('utf-8')).decode('ascii')

    # Domain labels and colors
    domain_labels = {
        "academic": "Academic Research", "writing": "Writing Projects",
        "family": "Family & Personal", "commercial": "Commercial",
        "personal": "Systems & Meta"
    }
    domain_css_colors = {
        "academic": "var(--academic)", "writing": "var(--writing)",
        "family": "var(--family)", "commercial": "var(--commercial)",
        "personal": "var(--personal)"
    }

    # Build top task rows
    def top_task_row(t):
        done_class = "done" if t["done"] else ""
        btn_class = "checked" if t["done"] else ""
        action = "markUndone" if t["done"] else "markDone"
        btn_label = "&#10003; Done" if t["done"] else "Done"
        effort = t.get("energy", "med")
        b64 = js_safe(t["text"])
        tb64 = task_data_b64(t)
        if t["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteTask(\'{b64}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteTask(\'{b64}\')">&#8593; P1</button>'
        notes_html = notes_popover(t.get("notes", ""))
        return f'''<div class="top-task-row {done_class}">
            <button class="top-task-done-btn {btn_class}" onclick="{action}('{b64}')">{btn_label}</button>
            <span class="top-task-text">{esc(t["text"])}{notes_html}</span>
            {f'<span class="top-task-due">{esc(t["due"])}</span>' if t.get("due") else ""}
            <span class="top-task-effort {effort}">{effort}</span>
            <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            {tier_btn}
            <button class="edit-btn" onclick="openEditTask(decTask('{tb64}'))">&#9998;</button>
            <button class="cancel-btn" onclick="cancelTask('{b64}')" title="Cancel task">&#10007;</button>
            <button class="save-later-btn" onclick="saveForLater('{b64}')" title="Save for later">&#128337;</button>
        </div>'''

    # Build project cards
    def project_card(p):
        effort = p.get("effort", "high")
        pb64 = project_data_b64(p)
        b64p = js_safe(p["name"])
        if p["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteProject(\'{b64p}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteProject(\'{b64p}\')">&#8593; P1</button>'
        return f'''<div class="card priority-{p["priority"]}{' has-deadline' if p.get('due') else ''}">
            <div class="card-main">
                <div class="card-top">
                    <h3>{esc(p["name"])}</h3>
                    {f'<span class="due-badge">{esc(p["due"])}</span>' if p.get("due") else ""}
                    <span class="effort-badge {effort}">{effort}</span>
                    <span class="domain-tag {p["domain"]}">{esc(p["domain"])}</span>
                    {tier_btn}
                    <button class="edit-btn" onclick="openEditProject(decProj('{pb64}'))">&#9998;</button>
                </div>
                {f'<div class="next-text">Next: {esc(p["next"])}</div>' if p.get("next") else ""}
            </div>
        </div>'''

    # Build task items (for Other Tasks and domain views).
    # Presentation mirrors top_task_row() so P2 tasks look the same as P1 tasks —
    # flat row with a Done button instead of a boxy checkbox card.
    def task_item(t):
        done_class = "done" if t["done"] else ""
        btn_class = "checked" if t["done"] else ""
        action = "markUndone" if t["done"] else "markDone"
        btn_label = "&#10003; Done" if t["done"] else "Done"
        effort = t.get("energy", "med")
        b64 = js_safe(t["text"])
        tb64 = task_data_b64(t)
        if t["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteTask(\'{b64}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteTask(\'{b64}\')">&#8593; P1</button>'
        notes_html = notes_popover(t.get("notes", ""))
        return f'''<div class="top-task-row p2-task-row {done_class}">
            <button class="top-task-done-btn {btn_class}" onclick="{action}('{b64}')">{btn_label}</button>
            <span class="top-task-text">{esc(t["text"])}{notes_html}</span>
            {f'<span class="top-task-due">{esc(t["due"])}</span>' if t.get("due") else ""}
            <span class="top-task-effort {effort}">{effort}</span>
            <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            {tier_btn}
            <button class="edit-btn" onclick="openEditTask(decTask('{tb64}'))">&#9998;</button>
            <button class="cancel-btn" onclick="cancelTask('{b64}')" title="Cancel task">&#10007;</button>
            <button class="save-later-btn" onclick="saveForLater('{b64}')" title="Save for later">&#128337;</button>
        </div>'''

    # Build sidebar nav items
    domain_order = ["academic", "writing", "family", "commercial", "personal"]
    nav_items = ""
    for d in domain_order:
        if d in domain_counts or any(p["domain"] == d for p in projects):
            count = domain_counts.get(d, 0)
            nav_items += f'''<div class="nav-item" data-view="{d}" onclick="showView('{d}')">
                <span class="dot" style="background:{domain_css_colors.get(d,'var(--text-dim)')}"></span>
                {domain_labels.get(d, d.title())}
                <span class="count">{count}</span>
            </div>'''

    # Build domain views — same structure as the main dashboard
    domain_views = ""
    for d in domain_order:
        d_projects = [p for p in projects if p["domain"] == d]
        d_tasks = [t for t in tasks if t["domain"] == d]
        d_active = [t for t in d_tasks if not t["done"]]
        d_done = [t for t in d_tasks if t["done"]]
        if not d_projects and not d_tasks:
            continue

        # Same logic as main dashboard: Top Tasks = P1 + due soon
        d_p1 = [t for t in d_active if t["priority"] == 1]
        d_due_soon_non_p1 = [t for t in d_active if t["priority"] != 1 and t.get("due") and t["due"] <= today_iso]
        d_p1_sorted = sorted(d_p1, key=lambda t: (
            0 if t.get("due") and t["due"] <= today_iso else 1,
            t["text"]
        ))
        d_seen_top = set()
        d_top_tasks = []
        for t in d_due_soon_non_p1 + d_p1_sorted:
            key = t["text"].lower()[:60]
            if key not in d_seen_top:
                d_seen_top.add(key)
                d_top_tasks.append(t)
        d_top_done = len([t for t in d_top_tasks if t["done"]])
        d_top_texts = set(t["text"].lower()[:60] for t in d_top_tasks)

        # P1 and P2+ projects for this domain
        d_p1_projects = sorted([p for p in d_projects if p["priority"] == 1 and p["status"] == "active"],
                               key=lambda p: (0 if p.get("due") else 1, p.get("due", ""), p["name"]))
        d_p2_projects = sorted([p for p in d_projects if p["priority"] >= 2 and p["status"] == "active"],
                               key=lambda p: (p["priority"], p["name"]))

        # P2+ tasks not already in top tasks.
        # Sort: by energy (high → med → low), then by priority number, then text.
        # (Domain is constant here since we're inside a single-domain view.)
        d_other_tasks = sorted(
            [t for t in d_active if t["priority"] >= 2 and t["text"].lower()[:60] not in d_top_texts],
            key=lambda t: (
                energy_sort_order.get(t.get("energy", "med").lower(), 1),
                t["priority"],
                t["text"],
            ),
        )

        # Stats for this domain
        d_active_projects = len([p for p in d_projects if p.get("status") == "active"])

        # Build the top tasks rows
        d_top_rows = "".join(top_task_row(t) for t in d_top_tasks)
        if not d_top_tasks:
            d_top_rows = '<div class="empty-msg">No priority or time-sensitive tasks in this domain.</div>'

        # Build completed items for this domain
        d_completed_items = ""
        for t in reversed(d_done):
            b64c = js_safe(t["text"])
            notes_html_c = notes_popover(t.get("notes", ""))
            d_completed_items += f'''<div class="task-item completed">
                <div class="task-check checked" onclick="markUndone('{b64c}')"></div>
                <div class="task-text">{esc(t["text"])}{notes_html_c}</div>
                <div class="task-meta">
                    {f'<span class="task-energy">{t["energy"]}</span>' if t.get("energy") else ""}
                    <span class="task-priority p{t["priority"]}">P{t["priority"]}</span>
                </div>
            </div>'''

        domain_views += f'''
        <div class="view" id="view-{d}" style="display:none">
            <div class="page-header">
                <div style="display:flex;align-items:center;gap:8px">
                    <h2>{domain_labels.get(d, d.title())}</h2>
                    <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Dashboard</button>
                </div>
                <div class="date">{today_str}</div>
            </div>

            <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
                <button class="btn btn-sm" onclick="toggleAddTask_{d}()">+ Add Task</button>
            </div>
            <div class="add-task-bar" id="addTaskBar_{d}" style="display:none;flex-wrap:wrap">
                <input type="text" id="newTask_{d}" placeholder="What needs to be done?" onkeypress="if(event.key==='Enter')addTaskDomain('{d}')" style="min-width:200px" />
                <select id="newPriority_{d}">
                    <option value="1">P1</option>
                    <option value="2" selected>P2</option>
                    <option value="3">P3</option>
                </select>
                <div class="date-picker-wrap">
                  <input type="date" id="newDue_{d}" title="Due date (optional)" />
                  <button type="button" class="cal-toggle" onclick="toggleCalendar('newDue_{d}', this)" title="Open calendar">&#128197;</button>
                  <div class="cal-popup" id="cal_newDue_{d}"></div>
                </div>
                <button class="btn btn-sm" onclick="addTaskDomain('{d}')">Add</button>
                <input type="text" id="newNotes_{d}" placeholder="Notes — email, link, reference (optional)" style="min-width:200px;flex:1;margin-top:4px" />
            </div>

            <div class="top-tasks-box">
                <div class="top-header">
                    <h3>Top Tasks</h3>
                    <span class="top-progress">{d_top_done} / {len(d_top_tasks)} done</span>
                </div>
                {d_top_rows}
            </div>

            {f'<div class="section-header"><h3>Priority 1 Projects</h3></div><div class="card-grid">{"".join(project_card(p) for p in d_p1_projects)}</div>' if d_p1_projects else ""}

            <div class="stats-row">
                <div class="stat-card"><div class="num">{d_active_projects}</div><div class="label">Active Projects</div></div>
                <div class="stat-card"><div class="num">{len(d_active)}</div><div class="label">Open Tasks</div></div>
                <div class="stat-card"><div class="num">{len(d_done)}</div><div class="label">Completed</div></div>
            </div>

            {f'<div class="section-header"><h3>Other Tasks</h3></div><div class="task-list">{"".join(task_item(t) for t in d_other_tasks)}</div>' if d_other_tasks else ""}

            {f'<div class="section-header"><h3>Priority 2+ Projects</h3></div><div class="card-grid">{"".join(project_card(p) for p in d_p2_projects)}</div>' if d_p2_projects else ""}

            {f'<div class="section-header" style="margin-top:24px"><h3>Completed ({len(d_done)})</h3></div><div class="task-list">{d_completed_items}</div>' if d_done else ""}
        </div>'''

    # Build completed view
    completed_items = ""
    for t in reversed(done_tasks):  # most recent first
        b64c = js_safe(t["text"])
        notes_html = notes_popover(t.get("notes", ""))
        completed_items += f'''<div class="task-item completed">
            <div class="task-check checked" onclick="markUndone('{b64c}')"></div>
            <div class="task-text">{esc(t["text"])}{notes_html}</div>
            <div class="task-meta">
                {f'<span class="task-energy">{t["energy"]}</span>' if t.get("energy") else ""}
                <span class="task-priority p{t["priority"]}">P{t["priority"]}</span>
                <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            </div>
        </div>'''
    if not done_tasks:
        completed_items = '<div class="empty-msg">No completed tasks yet. Check off items from the dashboard to see them here.</div>'

    # Build cancelled view
    cancelled_tasks = parse_archived_tasks(CANCELLED_MD)
    cancelled_items = ""
    for ct in reversed(cancelled_tasks):
        b64r = js_safe(ct["text"])
        notes_line = f'<div class="archived-notes">Notes: {esc(ct["notes"])}</div>' if ct.get("notes") else ""
        cancelled_items += f'''<div class="task-item archived-task">
            <div style="flex:1">
                <div class="task-text">{esc(ct["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Cancelled {esc(ct["date"])}{(' &bull; ' + esc(ct["domain"])) if ct.get("domain") else ""} &bull; P{ct.get("priority",2)}</div>
                {notes_line}
            </div>
            <button class="btn btn-sm btn-outline" onclick="restoreTask('{b64r}','cancelled')" style="font-size:11px">&#8634; Restore</button>
        </div>'''
    if not cancelled_tasks:
        cancelled_items = '<div class="empty-msg">No cancelled tasks.</div>'

    # Build saved-for-later view
    saved_tasks = parse_archived_tasks(SAVED_FOR_LATER_MD)
    saved_items = ""
    for st in reversed(saved_tasks):
        b64r = js_safe(st["text"])
        notes_line = f'<div class="archived-notes">Notes: {esc(st["notes"])}</div>' if st.get("notes") else ""
        saved_items += f'''<div class="task-item archived-task">
            <div style="flex:1">
                <div class="task-text">{esc(st["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Saved {esc(st["date"])}{(' &bull; ' + esc(st["domain"])) if st.get("domain") else ""} &bull; P{st.get("priority",2)}</div>
                {notes_line}
            </div>
            <button class="btn btn-sm btn-outline" onclick="restoreTask('{b64r}','saved')" style="font-size:11px">&#8634; Restore</button>
        </div>'''
    if not saved_tasks:
        saved_items = '<div class="empty-msg">No saved-for-later tasks.</div>'

    # Inbox items
    inbox_items = ""
    for item in inbox:
        inbox_items += f'''<div class="task-item">
            <div style="flex:1">
                <div class="task-text">{esc(item["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">{esc(item["date"])}{(' &bull; ' + esc(item["domain"])) if item.get("domain") else ""}</div>
            </div>
        </div>'''
    if not inbox:
        inbox_items = '<div class="empty-msg">Inbox empty. Nice work.</div>'

    # R&D control surface: surface the (previously orphaned) folder-grouped
    # projects view inside the dashboard. Best-effort so a registry hiccup never
    # blanks the whole dashboard.
    try:
        rnd_projects_html = render_projects_view_html()
    except Exception:
        rnd_projects_html = ('<div class="rnd-projects"><p class="rnd-empty">'
                             'R&amp;D projects unavailable.</p></div>')
    try:
        rnd_archive_html = render_archive_view_html()
    except Exception:
        rnd_archive_html = ('<div class="rnd-projects"><p class="rnd-empty">'
                            'Archive unavailable.</p></div>')

    # Pre-build balance widget rows (avoid nested f-string issues)
    max_count = max(domain_counts.values()) if domain_counts else 1
    balance_rows = ""
    for d in domain_order:
        if d in domain_counts:
            pct = min(100, domain_counts[d] * 100 // max(max_count, 1))
            color = domain_css_colors.get(d, 'var(--text-dim)')
            balance_rows += f'''<div class="balance-row">
                <span class="label">{d.title()[:8]}</span>
                <div class="balance-bar"><div class="fill" style="width:{pct}%;background:{color}"></div></div>
                <span>{domain_counts[d]}</span>
            </div>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anchor Dashboard — J.C. Liechty</title>
<link rel="icon" href="/anchor.ico?v=2026-05-11" type="image/x-icon">
<link rel="icon" href="/anchor.png?v=2026-05-11" type="image/png" sizes="256x256">
<link rel="apple-touch-icon" href="/anchor-touch.png?v=2026-05-11">
<style>
:root {{
    --bg: #0f1117; --surface: #1a1d27; --surface2: #232733; --border: #2e3340;
    --text: #e2e4e9; --text-dim: #8b8f9a; --accent: #6c9cfc;
    --academic: #6c9cfc; --writing: #c084fc; --family: #4ade80;
    --commercial: #fb923c; --personal: #67e8f9;
    --danger: #f87171; --warning: #fbbf24; --success: #4ade80;
    color-scheme: dark;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; min-height: 100vh; }}
.app {{ display: flex; min-height: 100vh; }}

/* Sidebar */
.sidebar {{
    width: 260px; background: var(--surface); border-right: 1px solid var(--border);
    padding: 20px 0; flex-shrink: 0; display: flex; flex-direction: column;
    position: fixed; top: 0; left: 0; bottom: 0; overflow-y: auto;
}}
.sidebar h1 {{ font-size: 20px; padding: 0 20px 4px; font-weight: 700; }}
.sidebar h1 span {{ color: var(--accent); }}
.sidebar .subtitle {{ font-size: 11px; color: var(--text-dim); padding: 0 20px 20px; }}
.nav-section {{ margin-top: 16px; }}
.nav-section h3 {{ font-size: 10px; text-transform: uppercase; letter-spacing: 1.2px; color: var(--text-dim); padding: 0 20px 6px; }}
.nav-item {{
    padding: 8px 20px; cursor: pointer; font-size: 13px; display: flex; align-items: center;
    gap: 10px; transition: background 0.15s; border-left: 3px solid transparent;
}}
.nav-item:hover {{ background: var(--surface2); }}
.nav-item.active {{ background: var(--surface2); border-left-color: var(--accent); }}
.nav-item .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
.nav-item .count {{ margin-left: auto; background: var(--surface2); padding: 1px 7px; border-radius: 10px; font-size: 11px; color: var(--text-dim); }}

/* Balance widget */
.balance-widget {{
    margin: auto 16px 16px; padding: 14px; background: var(--surface2);
    border-radius: 10px; border: 1px solid var(--border);
}}
.balance-widget h4 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); margin-bottom: 10px; }}
.balance-bars {{ display: flex; flex-direction: column; gap: 6px; }}
.balance-row {{ display: flex; align-items: center; gap: 8px; font-size: 11px; }}
.balance-row .label {{ width: 60px; color: var(--text-dim); }}
.balance-bar {{ flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }}
.balance-bar .fill {{ height: 100%; border-radius: 3px; transition: width 0.5s ease; }}

/* Main content */
.main {{ margin-left: 260px; flex: 1; padding: 28px 32px; max-width: 1100px; }}
.page-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }}
.page-header h2 {{ font-size: 22px; font-weight: 600; }}
.page-header .date {{ color: var(--text-dim); font-size: 13px; }}

/* Cards */
.card-grid {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 24px; }}
.card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; transition: border-color 0.2s; display: flex; align-items: center; gap: 12px;
}}
.card:hover {{ border-color: #3e4455; }}
.card.priority-1 {{ border-left: 3px solid var(--danger); }}
.card.priority-2 {{ border-left: 3px solid var(--warning); }}
.card.priority-3 {{ border-left: 3px solid var(--accent); }}
.card.has-deadline {{ background: linear-gradient(90deg, rgba(248,113,113,0.06), transparent 40%); }}
.card-main {{ flex: 1; min-width: 0; }}
.card-top {{ display: flex; align-items: center; gap: 8px; }}
.card h3 {{ font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.due-badge {{ font-size: 10px; background: rgba(248,113,113,0.2); color: var(--danger); padding: 1px 7px; border-radius: 3px; font-weight: 600; white-space: nowrap; }}
.effort-badge {{ font-size: 9px; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }}
.effort-badge.low {{ background: rgba(74,222,128,0.15); color: var(--success); }}
.effort-badge.med {{ background: rgba(251,191,36,0.12); color: var(--warning); }}
.effort-badge.high {{ background: rgba(192,132,252,0.12); color: var(--writing); }}
.next-text {{ font-size: 11.5px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }}
.domain-tag {{ font-size: 9px; text-transform: uppercase; letter-spacing: 0.8px; padding: 2px 7px; border-radius: 4px; white-space: nowrap; }}
.domain-tag.academic {{ background: rgba(108,156,252,0.15); color: var(--academic); }}
.domain-tag.writing {{ background: rgba(192,132,252,0.15); color: var(--writing); }}
.domain-tag.family {{ background: rgba(74,222,128,0.15); color: var(--family); }}
.domain-tag.commercial {{ background: rgba(251,146,60,0.15); color: var(--commercial); }}
.domain-tag.personal {{ background: rgba(103,232,249,0.15); color: var(--personal); }}

.card-grid.expanded .card {{ flex-direction: column; align-items: stretch; padding: 14px; }}
.card-grid.expanded .card-main {{ width: 100%; }}
.card-grid.expanded .card h3 {{ white-space: normal; }}
.card-grid.expanded .next-text {{ white-space: normal; }}

/* Tasks */
.task-list {{ margin-bottom: 24px; }}
.section-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }}
.section-header h3 {{ font-size: 15px; font-weight: 600; }}
.task-item {{
    display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px; transition: all 0.15s;
}}
.task-item:hover {{ border-color: #3e4455; }}
.task-item.completed {{ opacity: 0.5; }}
.task-item.completed .task-text {{ text-decoration: line-through; }}
.task-check {{
    width: 18px; height: 18px; border: 2px solid var(--border); border-radius: 5px;
    cursor: pointer; flex-shrink: 0; margin-top: 1px; display: flex; align-items: center;
    justify-content: center; transition: all 0.15s;
}}
.task-check:hover {{ border-color: var(--accent); }}
.task-check.checked {{ background: var(--accent); border-color: var(--accent); }}
.task-check.checked::after {{ content: '\\2713'; color: white; font-size: 11px; font-weight: 700; }}
.task-text {{ font-size: 13px; flex: 1; }}
.task-meta {{ display: flex; gap: 8px; align-items: center; flex-shrink: 0; }}
.task-priority {{ font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }}
.task-priority.p1 {{ background: rgba(248,113,113,0.15); color: var(--danger); }}
.task-priority.p2 {{ background: rgba(251,191,36,0.15); color: var(--warning); }}
.task-priority.p3 {{ background: rgba(108,156,252,0.15); color: var(--accent); }}
.task-energy {{ font-size: 10px; color: var(--text-dim); }}

/* Top Tasks */
.top-tasks-box {{
    background: var(--surface); border: 1px solid rgba(108,156,252,0.3);
    border-radius: 12px; padding: 16px 18px; margin-bottom: 20px;
}}
.top-tasks-box .top-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }}
.top-tasks-box h3 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--accent); }}
.top-tasks-box .top-progress {{ font-size: 11px; color: var(--text-dim); }}
.top-task-row {{ display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border); transition: opacity 0.3s; }}
.top-task-row:last-child {{ border-bottom: none; }}
.top-task-row.done {{ opacity: 0.4; }}
.top-task-row.done .top-task-text {{ text-decoration: line-through; }}
.top-task-done-btn {{
    padding: 4px 12px; font-size: 11px; font-weight: 600; border-radius: 5px;
    cursor: pointer; flex-shrink: 0; transition: all 0.15s;
    border: 1px solid var(--border); background: var(--surface2); color: var(--text-dim);
}}
.top-task-done-btn:hover {{ background: var(--success); color: #000; border-color: var(--success); }}
.top-task-done-btn.checked {{ background: var(--success); color: #000; border-color: var(--success); }}
.top-task-text {{ font-size: 13px; flex: 1; font-weight: 500; position: relative; }}
.top-task-due {{ font-size: 10px; background: rgba(248,113,113,0.2); color: var(--danger); padding: 2px 8px; border-radius: 4px; font-weight: 600; white-space: nowrap; }}
.top-task-effort {{ font-size: 9px; padding: 2px 6px; border-radius: 3px; white-space: nowrap; }}
.top-task-effort.low {{ background: rgba(74,222,128,0.15); color: var(--success); }}
.top-task-effort.med {{ background: rgba(251,191,36,0.12); color: var(--warning); }}
.top-task-effort.high {{ background: rgba(192,132,252,0.12); color: var(--writing); }}

/* Stats row */
.stats-row {{ display: flex; gap: 10px; margin-bottom: 20px; }}
.stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; flex: 1; text-align: center; }}
.stat-card .num {{ font-size: 20px; font-weight: 700; }}
.stat-card .label {{ font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}

/* Inbox */
.inbox-input-row {{ display: flex; gap: 8px; margin-bottom: 16px; }}
.inbox-input-row input {{
    flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; color: var(--text); font-size: 13px; outline: none;
}}
.inbox-input-row input:focus {{ border-color: var(--accent); }}
.inbox-input-row input::placeholder {{ color: var(--text-dim); }}
.inbox-input-row select {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 12px; color: var(--text); font-size: 13px; cursor: pointer;
}}

/* Buttons */
.btn {{
    background: var(--accent); color: #fff; border: none; padding: 10px 18px;
    border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap;
}}
.btn:hover {{ opacity: 0.85; }}
.btn-sm {{ padding: 6px 12px; font-size: 12px; }}
.btn-outline {{ background: transparent; border: 1px solid var(--border); color: var(--text); }}
.btn-outline:hover {{ background: var(--surface2); opacity: 1; }}

/* Add task bar */
.add-task-bar {{
    display: flex; gap: 8px; margin-bottom: 12px;
}}
.add-task-bar input {{
    flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; color: var(--text); font-size: 13px; outline: none;
}}
.add-task-bar input:focus {{ border-color: var(--accent); }}
.add-task-bar input::placeholder {{ color: var(--text-dim); }}
.add-task-bar select {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; color: var(--text); font-size: 12px; cursor: pointer;
}}

.empty-msg {{ color: var(--text-dim); font-size: 13px; padding: 12px; text-align: center; }}

/* Date picker wrapper */
.date-picker-wrap {{
    position: relative; display: inline-flex; align-items: center; gap: 0;
}}
.date-picker-wrap input[type="date"] {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px 0 0 8px;
    padding: 8px 10px; color: var(--text); font-size: 12px; width: 140px; outline: none;
}}
.date-picker-wrap input[type="date"]:focus {{ border-color: var(--accent); }}
.date-picker-wrap input[type="date"]::-webkit-calendar-picker-indicator {{ filter: invert(0.7); cursor: pointer; }}
.cal-toggle {{
    background: var(--surface2); border: 1px solid var(--border); border-left: none;
    border-radius: 0 8px 8px 0; padding: 8px 10px; cursor: pointer; color: var(--text-dim);
    font-size: 14px; display: flex; align-items: center; transition: all 0.15s;
}}
.cal-toggle:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

/* Calendar popup */
.cal-popup {{
    display: none; position: absolute; top: 100%; left: 0; z-index: 1000;
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); min-width: 280px; margin-top: 4px;
}}
.cal-popup.open {{ display: block; }}
.cal-header {{
    display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;
}}
.cal-header button {{
    background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); cursor: pointer; padding: 4px 10px; font-size: 13px; transition: all 0.15s;
}}
.cal-header button:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.cal-header .cal-title {{ font-size: 13px; font-weight: 600; color: var(--text); }}
.cal-grid {{
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; text-align: center;
}}
.cal-grid .cal-dow {{
    font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px;
    padding: 4px 0; font-weight: 600;
}}
.cal-grid .cal-day {{
    font-size: 12px; padding: 6px 2px; border-radius: 6px; cursor: pointer;
    color: var(--text); transition: all 0.12s; border: 1px solid transparent;
}}
.cal-grid .cal-day:hover {{ background: var(--surface2); border-color: var(--accent); }}
.cal-grid .cal-day.today {{ border-color: var(--accent); font-weight: 700; }}
.cal-grid .cal-day.selected {{ background: var(--accent); color: #fff; font-weight: 700; }}
.cal-grid .cal-day.other-month {{ color: var(--text-dim); opacity: 0.4; }}
.cal-grid .cal-day.empty {{ cursor: default; }}
.cal-grid .cal-day.empty:hover {{ background: transparent; border-color: transparent; }}
.cal-actions {{
    display: flex; gap: 6px; margin-top: 10px; justify-content: flex-end;
}}
.cal-actions button {{
    background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text-dim); cursor: pointer; padding: 4px 12px; font-size: 11px; transition: all 0.15s;
}}
.cal-actions button:hover {{ color: var(--text); background: var(--border); }}
.cal-actions .cal-today-btn:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

/* Modal date picker adjustments */
.modal .date-picker-wrap {{ width: 100%; }}
.modal .date-picker-wrap input[type="date"] {{ width: 100%; border-radius: 8px 0 0 8px; }}

/* Edit buttons */
.edit-btn {{
    background: none; border: none; color: var(--text-dim); cursor: pointer;
    font-size: 12px; padding: 2px 6px; border-radius: 4px; opacity: 0; transition: all 0.15s;
}}
.task-item:hover .edit-btn, .top-task-row:hover .edit-btn, .card:hover .edit-btn {{ opacity: 1; }}
.edit-btn:hover {{ background: var(--surface2); color: var(--accent); }}

/* Promote/Demote buttons */
.promote-btn, .demote-btn {{
    background: none; border: 1px solid var(--border); color: var(--text-dim); cursor: pointer;
    font-size: 10px; padding: 2px 8px; border-radius: 4px; opacity: 0; transition: all 0.15s; white-space: nowrap;
}}
.card:hover .promote-btn, .card:hover .demote-btn,
.task-item:hover .promote-btn, .task-item:hover .demote-btn,
.top-task-row:hover .promote-btn, .top-task-row:hover .demote-btn {{ opacity: 1; }}
.promote-btn:hover {{ background: rgba(248,113,113,0.15); color: var(--danger); border-color: var(--danger); }}
.demote-btn:hover {{ background: rgba(251,191,36,0.15); color: var(--warning); border-color: var(--warning); }}

/* Modal */
.modal-overlay {{
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    z-index: 200; align-items: center; justify-content: center;
}}
.modal-overlay.open {{ display: flex; }}
.modal {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 24px; width: 500px; max-width: 90vw; max-height: 85vh; overflow-y: auto;
}}
.modal h3 {{ font-size: 16px; margin-bottom: 16px; }}
.modal label {{ font-size: 12px; color: var(--text-dim); display: block; margin-bottom: 4px; margin-top: 12px; }}
.modal input, .modal select, .modal textarea {{
    width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 12px; color: var(--text); font-size: 13px; outline: none; font-family: inherit;
}}
.modal textarea {{ resize: vertical; min-height: 60px; }}
.modal input:focus, .modal select:focus {{ border-color: var(--accent); }}
.modal-actions {{ display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }}

/* R&D existing-folder picker */
.rnd-picker-loc {{
    font-size: 12px; color: var(--text-dim); margin-bottom: 6px;
    word-break: break-all; line-height: 1.4;
}}
.rnd-picker-loc b {{ color: var(--text); }}
.rnd-picker-selected {{
    font-size: 12px; margin: 6px 0 0; padding: 6px 10px; border-radius: 6px;
    background: rgba(108,156,252,0.12); border: 1px solid var(--accent);
    color: var(--text); word-break: break-all; line-height: 1.4;
}}
.rnd-picker-selected.empty {{
    background: var(--surface2); border-color: var(--border); color: var(--text-dim);
}}
.rnd-picker-err {{
    font-size: 12px; margin: 6px 0; padding: 6px 10px; border-radius: 6px;
    background: rgba(248,113,113,0.12); border: 1px solid var(--danger); color: var(--text);
    word-break: break-all; line-height: 1.4;
}}
/* Explorer-style expandable TREE folder picker */
.rnd-tree {{
    background: var(--surface2); max-height: 300px; overflow: auto;
    border: 1px solid var(--border); border-radius: 6px; padding: 6px;
    margin-top: 6px; font-size: 13px;
}}
.rnd-tree-children {{ margin-left: 16px; border-left: 1px solid var(--border); padding-left: 2px; }}
.rnd-tree-row {{
    display: flex; align-items: center; gap: 8px; padding: 5px 6px;
    border-radius: 5px; cursor: pointer; user-select: none; transition: background 0.12s;
}}
.rnd-tree-row:hover {{ background: rgba(108,156,252,0.14); }}
.rnd-tree-row.selected {{ background: rgba(108,156,252,0.28); }}
.rnd-tree-row .rt-caret {{
    flex: 0 0 auto; width: 14px; text-align: center; color: var(--text-dim);
    font-size: 11px;
}}
.rnd-tree-row .rt-icon {{ flex: 0 0 auto; font-size: 15px; }}
.rnd-tree-row .rt-name {{
    flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.rnd-tree-err {{ color: var(--danger); font-size: 11px; padding: 2px 6px 2px 22px; }}
.rnd-use-btn {{ background: var(--accent); }}

/* Toast */
.toast {{
    position: fixed; bottom: 24px; right: 24px; background: var(--success);
    color: #000; padding: 12px 20px; border-radius: 8px; font-weight: 600;
    display: none; z-index: 200; animation: fadeIn 0.2s;
}}
@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}

/* Cancel / Save for Later buttons */
.cancel-btn, .save-later-btn {{
    background: none; border: 1px solid var(--border); cursor: pointer;
    font-size: 10px; padding: 2px 8px; border-radius: 4px; opacity: 0; transition: all 0.15s; white-space: nowrap;
}}
.cancel-btn {{ color: var(--danger); }}
.save-later-btn {{ color: var(--warning); }}
.task-item:hover .cancel-btn, .task-item:hover .save-later-btn,
.top-task-row:hover .cancel-btn, .top-task-row:hover .save-later-btn {{ opacity: 1; }}
.cancel-btn:hover {{ background: rgba(248,113,113,0.15); border-color: var(--danger); }}
.save-later-btn:hover {{ background: rgba(251,191,36,0.15); border-color: var(--warning); }}

/* Notes popover */
.notes-wrapper {{
    position: relative; display: inline-block; margin-left: 6px;
}}
.notes-indicator {{
    font-size: 11px; cursor: help; opacity: 0.6;
}}
.notes-wrapper:hover .notes-indicator {{ opacity: 1; }}
.notes-popover {{
    display: none; position: absolute; bottom: calc(100% + 8px); left: 50%;
    transform: translateX(-50%); z-index: 150;
    background: var(--surface2); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; min-width: 220px; max-width: 400px;
    font-size: 12px; line-height: 1.6; color: var(--text);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    word-break: break-word; white-space: normal;
}}
.notes-popover::after {{
    content: ''; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
    border: 6px solid transparent; border-top-color: var(--border);
}}
.notes-popover a {{
    color: var(--accent); text-decoration: underline; word-break: break-all;
}}
.notes-popover a:hover {{ color: #93b8fd; }}
.notes-wrapper:hover .notes-popover {{ display: block; }}

/* Archived task notes */
.archived-notes {{
    font-size: 12px; color: var(--text-dim); margin-top: 4px;
    padding: 4px 8px; background: var(--surface2); border-radius: 4px;
    word-break: break-word;
}}
.archived-notes a {{ color: var(--accent); }}

/* Archived task items */
.archived-task {{
    align-items: center;
}}

@media (max-width: 768px) {{
    .sidebar {{ display: none; }}
    .main {{ margin-left: 0; padding: 16px; }}
    .stats-row {{ flex-wrap: wrap; }}
    .stat-card {{ min-width: calc(50% - 6px); }}
}}

/* ── R&D project tiles (rich) ── */
.rnd-projects {{ display: flex; flex-direction: column; gap: 14px; }}
.rnd-folder {{ border: 1px solid var(--border); border-radius: 10px; overflow: hidden; background: var(--surface); }}
.rnd-folder-head {{ cursor: pointer; padding: 10px 14px; font-family: ui-monospace, Consolas, monospace; font-size: 12px; color: var(--text-dim); background: rgba(255,255,255,.02); }}
.rnd-folder-count {{ color: var(--text-dim); }}
.rnd-folder-tiles {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; padding: 12px; }}
.rnd-name {{ font-weight: 600; font-size: 14px; }}
.rnd-badge {{ font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-dim); }}
.rnd-badge.rnd-p1 {{ background: rgba(248,113,113,.18); color: var(--danger); border-color: rgba(248,113,113,.3); }}
.rnd-badge.rnd-p2 {{ background: rgba(251,191,36,.15); color: var(--warning); border-color: rgba(251,191,36,.3); }}
.rnd-badge[class*="rnd-state-archived"], .rnd-badge[class*="rnd-state-future"], .rnd-badge[class*="rnd-state-retired"] {{ background: rgba(255,255,255,.04); }}
.rnd-imported {{ color: var(--text-dim); font-style: italic; font-size: 11px; }}
.rnd-running {{ color: var(--success); font-size: 11px; }}
.rnd-status-line {{ margin: 0; display: flex; flex-wrap: wrap; gap: 8px; }}
.rnd-lane {{ padding: 4px 10px; border-radius: 6px; background: #1b2030; font-size: 13px; }}
.rnd-lane.rnd-lane-empty {{ color: var(--text-dim); }}
.rnd-blurb {{ font-size: 12px; color: var(--text); opacity: .85; }}
.rnd-notes {{ font-size: 11.5px; color: var(--text-dim); background: rgba(255,255,255,.03); border-radius: 6px; padding: 5px 8px; white-space: pre-wrap; }}
.rnd-actions {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 2px; }}
.rnd-mini {{ font-size: 11px; padding: 3px 9px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }}
.rnd-mini:hover {{ border-color: var(--accent); }}
.rnd-mini.rnd-pr-on {{ border-color: var(--accent); color: var(--accent); font-weight: 600; }}
.rnd-mini.rnd-open-btn {{ background: var(--accent); color: #0b1020; border-color: var(--accent); font-weight: 600; }}
.rnd-mini.rnd-accent {{ border-color: var(--accent); color: var(--accent); }}
/* v3 Wave 5 — thin full-width project ROWS (replace the square .rnd-tile). */
.rnd-folder-rows {{ display: flex; flex-direction: column; gap: 6px; }}
.rnd-row {{ display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface2, #232733); cursor: pointer; position: relative; }}
.rnd-row:hover {{ border-color: var(--accent); }}
.rnd-row:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
.rnd-dot {{ flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%; background: var(--text-dim); }}
.rnd-dot.rnd-dot-running {{ background: var(--success); box-shadow: 0 0 5px var(--success); }}
.rnd-dot.rnd-dot-idle {{ background: var(--text-dim); }}
.rnd-row .rnd-name {{ flex: 0 0 auto; white-space: nowrap; }}
.rnd-row-summary {{ flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--text); opacity: .85; }}
.rnd-row-summary.rnd-dim {{ color: var(--text-dim); opacity: .6; font-style: italic; }}
.rnd-row-counts {{ flex: 0 0 auto; }}
.rnd-row-counts .rnd-status-line {{ gap: 5px; }}
.rnd-row-counts .rnd-lane {{ padding: 2px 7px; font-size: 11px; }}
.rnd-kebab {{ flex: 0 0 auto; position: relative; }}
.rnd-kebab-btn {{ background: transparent; border: 1px solid transparent; color: var(--text-dim); font-size: 16px; line-height: 1; padding: 2px 7px; border-radius: 6px; cursor: pointer; }}
.rnd-kebab-btn:hover {{ border-color: var(--border); color: var(--text); }}
.rnd-kebab-menu {{ display: none; position: absolute; right: 0; top: 100%; margin-top: 4px; z-index: 30; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 6px; flex-direction: column; gap: 4px; min-width: 120px; box-shadow: 0 6px 18px rgba(0,0,0,.4); }}
.rnd-kebab-menu.rnd-kebab-open {{ display: flex; }}
.rnd-kebab-menu .rnd-mini {{ width: 100%; text-align: left; }}
.rnd-mini.rnd-danger:hover {{ border-color: var(--danger); color: var(--danger); }}
.rnd-empty {{ color: var(--text-dim); font-size: 13px; }}
</style>
</head>
<body>
<div class="app">
  <nav class="sidebar">
    <h1><span>&#9875;</span> Anchor</h1>
    <div class="subtitle">J.C. Liechty — Life Dashboard</div>
    <div class="nav-section">
      <h3>Views</h3>
      <div class="nav-item active" data-view="dashboard" onclick="showView('dashboard')">
        <span class="dot" style="background:var(--accent)"></span> Dashboard
      </div>
      <div class="nav-item" data-view="inbox" onclick="showView('inbox')">
        <span class="dot" style="background:var(--warning)"></span> Inbox <span class="count">{len(inbox)}</span>
      </div>
      <div class="nav-item" data-view="rnd" onclick="showView('rnd')">
        <span class="dot" style="background:#6c9cfc"></span> R&amp;D
      </div>
      <div class="nav-item" data-view="rnd-archive" onclick="showView('rnd-archive')">
        <span class="dot" style="background:var(--text-dim)"></span> R&amp;D Archive
      </div>
    </div>
    <div class="nav-section">
      <h3>Domains</h3>
      {nav_items}
    </div>
    <div class="balance-widget">
      <h4>Domain Balance</h4>
      <div class="balance-bars">
        {balance_rows}
      </div>
    </div>
  </nav>

  <div class="main">
    <!-- Dashboard view -->
    <div class="view" id="view-dashboard">
      {health_banner_html}
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Dashboard</h2>
          <button class="btn btn-sm" onclick="refresh()" style="font-size:11px;padding:4px 10px;background:var(--accent)">&#8635; Update</button>
          <button class="btn btn-sm btn-outline" id="completedBtn" onclick="showView('completed')" style="font-size:11px;padding:4px 10px">&#10003; Completed ({len(done_tasks)})</button>
          <button class="btn btn-sm btn-outline" onclick="showView('cancelled')" style="font-size:11px;padding:4px 10px;border-color:var(--danger);color:var(--danger)">&#10007; Cancelled ({len(cancelled_tasks)})</button>
          <button class="btn btn-sm btn-outline" onclick="showView('saved')" style="font-size:11px;padding:4px 10px;border-color:var(--warning);color:var(--warning)">&#128337; Saved ({len(saved_tasks)})</button>
          <!-- 2026-05-12: Stop button removed. Server lifecycle is owned by
               the NSSM "anchor" service on gwl-server. To restart, run
               `nssm restart anchor` on gwl-server. -->
        </div>
        <div class="date">{today_str}</div>
      </div>

      <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
        <button class="btn btn-sm" onclick="toggleAddTask()">+ Add Task</button>
      </div>
      <div class="add-task-bar" id="addTaskBar" style="display:none;flex-wrap:wrap">
        <input type="text" id="newTask" placeholder="What needs to be done?" onkeypress="if(event.key==='Enter')addTask()" style="min-width:200px" />
        <select id="newDomain">
          <option value="academic">Academic</option>
          <option value="commercial">Commercial</option>
          <option value="writing">Writing</option>
          <option value="family">Family</option>
          <option value="personal">Personal</option>
        </select>
        <select id="newPriority">
          <option value="1">P1</option>
          <option value="2" selected>P2</option>
          <option value="3">P3</option>
        </select>
        <div class="date-picker-wrap">
          <input type="date" id="newDue" title="Due date (optional)" />
          <button type="button" class="cal-toggle" onclick="toggleCalendar('newDue', this)" title="Open calendar">&#128197;</button>
          <div class="cal-popup" id="cal_newDue"></div>
        </div>
        <button class="btn btn-sm" onclick="addTask()">Add</button>
        <input type="text" id="newNotes" placeholder="Notes — email, link, reference (optional)" style="min-width:200px;flex:1;margin-top:4px" />
      </div>

      <div class="top-tasks-box">
        <div class="top-header">
          <h3>Top Tasks</h3>
          <span class="top-progress">{top_done} / {len(top_tasks)} done</span>
        </div>
        {"".join(top_task_row(t) for t in top_tasks)}
      </div>

      <!-- R&D Projects (home dashboard section) -->
      <div class="section-header" style="display:flex;align-items:center;gap:8px">
        <h3>R&amp;D Projects</h3>
        <button class="btn btn-sm" onclick="openNewProject()" style="font-size:11px;padding:4px 10px;background:var(--accent)">+ New Project</button>
      </div>
      {rnd_projects_html}

      <div class="section-header"><h3>Priority 1 Projects</h3></div>
      <div class="card-grid">{"".join(project_card(p) for p in p1_projects)}</div>

      <div class="stats-row">
        <div class="stat-card"><div class="num">{len([p for p in projects if p["status"]=="active"])}</div><div class="label">Active Projects</div></div>
        <div class="stat-card"><div class="num">{len(active)}</div><div class="label">Open Tasks</div></div>
        <div class="stat-card"><div class="num">{len(done_tasks)}</div><div class="label">Completed</div></div>
        <div class="stat-card"><div class="num">{len(inbox)}</div><div class="label">In Inbox</div></div>
      </div>

      <div class="section-header"><h3>Other Tasks</h3></div>
      <div class="task-list">
        {"".join(task_item(t) for t in other_tasks)}
      </div>

      <div class="section-header"><h3>Priority 2+ Projects</h3></div>
      <div class="card-grid">{"".join(project_card(p) for p in p2_projects)}</div>
    </div>

    <!-- Completed view -->
    <div class="view" id="view-completed" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Completed</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <div class="task-list">{completed_items}</div>
    </div>

    <!-- Cancelled view -->
    <div class="view" id="view-cancelled" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Cancelled Tasks</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Tasks you decided not to do. Click Restore to move one back to active.</p>
      <div class="task-list">{cancelled_items}</div>
    </div>

    <!-- Saved for Later view -->
    <div class="view" id="view-saved" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Saved for Later</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Tasks on hold. Click Restore to move one back to active.</p>
      <div class="task-list">{saved_items}</div>
    </div>

    <!-- Inbox view -->
    <div class="view" id="view-inbox" style="display:none">
      <div class="page-header"><h2>Inbox</h2></div>
      <div class="inbox-input-row">
        <input type="text" id="captureText" placeholder="Quick capture — type anything and hit Enter..." onkeydown="if(event.key==='Enter')captureItem()">
        <select id="captureDomain">
          <option value="">No tag</option>
          <option value="academic">Academic</option>
          <option value="writing">Writing</option>
          <option value="family">Family</option>
          <option value="commercial">Commercial</option>
          <option value="personal">Personal</option>
        </select>
        <button class="btn" onclick="captureItem()">Add</button>
      </div>
      <div class="task-list">{inbox_items}</div>
    </div>

    <!-- R&D control surface view -->
    <div class="view" id="view-rnd" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>R&amp;D Projects</h2>
          <button class="btn btn-sm" onclick="openNewProject()" style="font-size:11px;padding:4px 10px;background:var(--accent)">+ New Project</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Per-project R&amp;D control surface. <b>Open</b> a project to launch research / plan / build jobs in its own window (run several at once). Use the tile buttons to change priority, add notes, or archive / retire a project. <a href="#" onclick="showView('rnd-archive');return false" style="color:var(--accent)">View Archive &#8594;</a></p>
      {rnd_projects_html}
    </div>

    <div class="view" id="view-rnd-archive" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>R&amp;D Archive</h2>
          <button class="btn btn-sm" onclick="showView('rnd')" style="font-size:11px;padding:4px 10px">&#8592; Active projects</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Archived, future, and retired projects (kept, reviewable). Use <b>Reactivate</b> to bring one back to the active list.</p>
      {rnd_archive_html}
    </div>

    <!-- Domain views -->
    {domain_views}
  </div>
</div>

<!-- Edit Task Modal -->
<div class="modal-overlay" id="editTaskModal">
  <div class="modal">
    <h3>Edit Task</h3>
    <input type="hidden" id="editTaskOld" />
    <label>Task</label>
    <input type="text" id="editTaskText" />
    <label>Domain</label>
    <select id="editTaskDomain">
      <option value="academic">Academic</option>
      <option value="commercial">Commercial</option>
      <option value="writing">Writing</option>
      <option value="family">Family</option>
      <option value="personal">Personal</option>
    </select>
    <label>Priority</label>
    <select id="editTaskPriority">
      <option value="1">P1 — Urgent</option>
      <option value="2">P2 — Important</option>
      <option value="3">P3 — Normal</option>
    </select>
    <label>Energy</label>
    <select id="editTaskEnergy">
      <option value="low">Low</option>
      <option value="med">Med</option>
      <option value="high">High</option>
    </select>
    <label>Due Date</label>
    <div class="date-picker-wrap">
      <input type="date" id="editTaskDue" />
      <button type="button" class="cal-toggle" onclick="toggleCalendar('editTaskDue', this)" title="Open calendar">&#128197;</button>
      <div class="cal-popup" id="cal_editTaskDue"></div>
    </div>
    <label>Notes</label>
    <textarea id="editTaskNotes" placeholder="Email, link, reference, context..."></textarea>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('editTaskModal')">Cancel</button>
      <button class="btn" onclick="saveEditTask()">Save</button>
    </div>
  </div>
</div>

<!-- Edit Project Modal -->
<div class="modal-overlay" id="editProjectModal">
  <div class="modal">
    <h3>Edit Project</h3>
    <input type="hidden" id="editProjOld" />
    <label>Name</label>
    <input type="text" id="editProjName" />
    <label>Domain</label>
    <select id="editProjDomain">
      <option value="academic">Academic</option>
      <option value="commercial">Commercial</option>
      <option value="writing">Writing</option>
      <option value="family">Family</option>
      <option value="personal">Personal</option>
    </select>
    <label>Priority</label>
    <select id="editProjPriority">
      <option value="1">P1 — Top Tier</option>
      <option value="2">P2 — Important</option>
      <option value="3">P3 — Normal</option>
    </select>
    <label>Status</label>
    <select id="editProjStatus">
      <option value="active">Active</option>
      <option value="paused">Paused</option>
      <option value="completed">Completed</option>
      <option value="blocked">Blocked</option>
    </select>
    <label>Effort</label>
    <select id="editProjEffort">
      <option value="low">Low</option>
      <option value="med">Med</option>
      <option value="high">High</option>
    </select>
    <label>Due Date</label>
    <div class="date-picker-wrap">
      <input type="date" id="editProjDue" />
      <button type="button" class="cal-toggle" onclick="toggleCalendar('editProjDue', this)" title="Open calendar">&#128197;</button>
      <div class="cal-popup" id="cal_editProjDue"></div>
    </div>
    <label>Next Step</label>
    <input type="text" id="editProjNext" />
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('editProjectModal')">Cancel</button>
      <button class="btn" onclick="saveEditProject()">Save</button>
    </div>
  </div>
</div>

<!-- New R&D Project Modal -->
<div class="modal-overlay" id="newProjectModal">
  <div class="modal">
    <h3>New R&amp;D Project</h3>
    <div style="display:flex;gap:8px;margin-bottom:8px">
      <button type="button" class="btn btn-sm" id="npModeNewBtn" onclick="npSetMode('new_folder')">Create new folder</button>
      <button type="button" class="btn btn-sm btn-outline" id="npModeExistingBtn" onclick="npSetMode('existing')">Select existing</button>
    </div>
    <label>Project name</label>
    <input type="text" id="npName" placeholder="Project name" oninput="npNameEdited()" />
    <label>Priority</label>
    <select id="npPriority">
      <option value="1">P1 — Top Tier</option>
      <option value="2" selected>P2 — Important</option>
      <option value="3">P3 — Normal</option>
    </select>
    <!-- Create-new-folder mode -->
    <div id="npNewFolderFields">
      <label>Parent path</label>
      <input type="text" id="npParentPath" placeholder="e.g. C:\\dev" />
      <label style="display:flex;align-items:center;gap:6px;margin-top:6px">
        <input type="checkbox" id="npGitInit" /> Initialize git repo
      </label>
    </div>
    <!-- Select-existing mode (Explorer-style expandable TREE) -->
    <div id="npExistingFields" style="display:none">
      <input type="hidden" id="npFolderPath" />
      <label>Browse to a folder on gwl-server</label>
      <div class="rnd-picker-err" id="npBrowseErr" style="display:none"></div>
      <div class="rnd-tree" id="npTree" role="tree"></div>
      <button type="button" class="btn btn-sm rnd-use-btn" id="npSelectHereBtn" style="margin-top:8px" onclick="npSelectCurrent()">&#10003; Use this folder</button>
      <div class="rnd-picker-selected empty" id="npSelected">No folder selected yet</div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('newProjectModal')">Cancel</button>
      <button class="btn" onclick="createNewProject()">Create</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// Heartbeat disabled — the server runs until explicitly stopped so the
// dashboard is instantly available when you return to the tab later.

// ── Access token (D4) ──
// Kept ONLY in this browser's localStorage; sent as X-Anchor-Token on mutating
// POSTs; NEVER embedded in the served HTML (GET is unauthenticated). When the
// server has no ANCHOR_TOKEN set, auth is off and the header is ignored.
window.ANCHOR_AUTH_REQUIRED = {auth_required_js};
function _anchorToken() {{ try {{ return localStorage.getItem('anchor_token') || ''; }} catch (e) {{ return ''; }} }}
function setAnchorToken() {{
    const cur = _anchorToken();
    const t = window.prompt('Paste your Anchor access token:', cur);
    if (t === null) return false;
    try {{ if (t) {{ localStorage.setItem('anchor_token', t.trim()); }} else {{ localStorage.removeItem('anchor_token'); }} }} catch (e) {{}}
    return true;
}}
// On first load, if the server requires auth and we have no token yet, ask once.
// Once stored, this never fires again (token persists in localStorage).
window.addEventListener('DOMContentLoaded', function () {{
    if (window.ANCHOR_AUTH_REQUIRED && !_anchorToken()) {{ setAnchorToken(); }}
}});

async function apiCall(endpoint, body) {{
    // Retry once on network failure — the server may have briefly paused
    // (e.g. GC, slow I/O) and the browser throttled our heartbeat.
    async function _doFetch() {{
        const headers = {{'Content-Type': 'application/json'}};
        const tok = _anchorToken();
        if (tok) headers['X-Anchor-Token'] = tok;
        const r = await fetch(endpoint, {{
            method: 'POST',
            headers: headers,
            body: JSON.stringify(body)
        }});
        return await r.json();
    }}
    try {{
        let data;
        try {{ data = await _doFetch(); }}
        catch(e1) {{
            await new Promise(res => setTimeout(res, 400));
            data = await _doFetch();
        }}
        // Auth required but missing/stale → let the user supply it, then retry once.
        if (data && data.error === 'unauthorized' && setAnchorToken()) {{
            data = await _doFetch();
        }}
        if (data.ok) {{
            showToast(data.message || 'Done!');
            setTimeout(() => window.location.reload(), 600);
        }} else {{
            showToast('Error: ' + (data.error || 'unknown'));
        }}
    }} catch(e) {{
        showToast('Connection error: ' + e.message + ' — the server may have stopped. Relaunch the dashboard.');
    }}
}}

function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 2500);
}}

// ── Calendar Picker ──
let _calOpen = null;   // currently open calendar popup element
let _calInput = null;   // the date input it controls
let _calMonth = null;   // displayed month (0-11)
let _calYear = null;    // displayed year

function toggleCalendar(inputId, btn) {{
    const popup = document.getElementById('cal_' + inputId);
    const input = document.getElementById(inputId);
    if (_calOpen && _calOpen === popup) {{ closeAllCalendars(); return; }}
    closeAllCalendars();
    _calOpen = popup;
    _calInput = input;
    // Start on the input's current value or today
    const cur = input.value ? new Date(input.value + 'T00:00:00') : new Date();
    _calMonth = cur.getMonth();
    _calYear = cur.getFullYear();
    renderCalendar();
    popup.classList.add('open');
}}

function closeAllCalendars() {{
    document.querySelectorAll('.cal-popup.open').forEach(el => el.classList.remove('open'));
    _calOpen = null;
    _calInput = null;
}}

function renderCalendar() {{
    if (!_calOpen) return;
    const today = new Date();
    const todayStr = today.getFullYear() + '-' + String(today.getMonth()+1).padStart(2,'0') + '-' + String(today.getDate()).padStart(2,'0');
    const selectedStr = _calInput.value || '';
    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const dows = ['Su','Mo','Tu','We','Th','Fr','Sa'];

    const firstDay = new Date(_calYear, _calMonth, 1).getDay();
    const daysInMonth = new Date(_calYear, _calMonth + 1, 0).getDate();
    const daysInPrev = new Date(_calYear, _calMonth, 0).getDate();

    let html = `<div class="cal-header">
        <button onclick="calNav(-1)">&#9664;</button>
        <span class="cal-title">${{monthNames[_calMonth]}} ${{_calYear}}</span>
        <button onclick="calNav(1)">&#9654;</button>
    </div><div class="cal-grid">`;
    dows.forEach(d => html += `<span class="cal-dow">${{d}}</span>`);

    // Previous month trailing days
    for (let i = firstDay - 1; i >= 0; i--) {{
        const day = daysInPrev - i;
        const m = _calMonth === 0 ? 12 : _calMonth;
        const y = _calMonth === 0 ? _calYear - 1 : _calYear;
        const ds = y + '-' + String(m).padStart(2,'0') + '-' + String(day).padStart(2,'0');
        html += `<span class="cal-day other-month" onclick="calPick('${{ds}}')">${{day}}</span>`;
    }}
    // Current month days
    for (let d = 1; d <= daysInMonth; d++) {{
        const ds = _calYear + '-' + String(_calMonth+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
        let cls = 'cal-day';
        if (ds === todayStr) cls += ' today';
        if (ds === selectedStr) cls += ' selected';
        html += `<span class="${{cls}}" onclick="calPick('${{ds}}')">${{d}}</span>`;
    }}
    // Next month leading days
    const totalCells = firstDay + daysInMonth;
    const remaining = (7 - (totalCells % 7)) % 7;
    for (let d = 1; d <= remaining; d++) {{
        const m = _calMonth === 11 ? 1 : _calMonth + 2;
        const y = _calMonth === 11 ? _calYear + 1 : _calYear;
        const ds = y + '-' + String(m).padStart(2,'0') + '-' + String(d).padStart(2,'0');
        html += `<span class="cal-day other-month" onclick="calPick('${{ds}}')">${{d}}</span>`;
    }}
    html += `</div>`;
    html += `<div class="cal-actions">
        <button onclick="calClear()">Clear</button>
        <button class="cal-today-btn" onclick="calPickToday()">Today</button>
    </div>`;
    _calOpen.innerHTML = html;
}}

function calNav(delta) {{
    _calMonth += delta;
    if (_calMonth > 11) {{ _calMonth = 0; _calYear++; }}
    if (_calMonth < 0) {{ _calMonth = 11; _calYear--; }}
    renderCalendar();
}}

function calPick(dateStr) {{
    if (_calInput) {{
        _calInput.value = dateStr;
        _calInput.dispatchEvent(new Event('change'));
    }}
    closeAllCalendars();
}}

function calPickToday() {{
    const t = new Date();
    calPick(t.getFullYear() + '-' + String(t.getMonth()+1).padStart(2,'0') + '-' + String(t.getDate()).padStart(2,'0'));
}}

function calClear() {{
    if (_calInput) {{ _calInput.value = ''; _calInput.dispatchEvent(new Event('change')); }}
    closeAllCalendars();
}}

// Close calendar when clicking outside
document.addEventListener('click', function(e) {{
    if (_calOpen && !e.target.closest('.date-picker-wrap')) closeAllCalendars();
}});

function dec(b64) {{ return decodeURIComponent(Array.from(atob(b64), c => '%' + c.charCodeAt(0).toString(16).padStart(2,'0')).join('')); }}
function decTask(b64) {{ return JSON.parse(dec(b64)); }}
function decProj(b64) {{ return JSON.parse(dec(b64)); }}
function markDone(b64) {{ apiCall('/api/done', {{text: dec(b64)}}); }}
function markUndone(b64) {{ apiCall('/api/undone', {{text: dec(b64)}}); }}

function addTask() {{
    const text = document.getElementById('newTask').value.trim();
    if (!text) return;
    const domain = document.getElementById('newDomain').value;
    const priority = parseInt(document.getElementById('newPriority').value);
    const due = document.getElementById('newDue').value || '';
    const notes = document.getElementById('newNotes').value.trim();
    apiCall('/api/add', {{text, domain, priority, energy: 'med', due, notes}});
}}

function cancelTask(b64) {{
    if (confirm('Cancel this task? It will be moved to the Cancelled list.')) {{
        apiCall('/api/cancel', {{text: dec(b64)}});
    }}
}}

function saveForLater(b64) {{
    if (confirm('Save this task for later? It will be moved off the dashboard.')) {{
        apiCall('/api/save_for_later', {{text: dec(b64)}});
    }}
}}

function restoreTask(b64, from_archive) {{
    apiCall('/api/restore', {{text: dec(b64), from: from_archive}});
}}

function captureItem() {{
    const text = document.getElementById('captureText').value.trim();
    if (!text) return;
    const domain = document.getElementById('captureDomain').value;
    apiCall('/api/capture', {{text, domain}});
}}

function refresh() {{ window.location.reload(); }}

function toggleAddTask() {{
    const bar = document.getElementById('addTaskBar');
    bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
    if (bar.style.display === 'flex') document.getElementById('newTask').focus();
}}

function showView(view) {{
    document.querySelectorAll('.view').forEach(el => el.style.display = 'none');
    const el = document.getElementById('view-' + view);
    if (el) el.style.display = 'block';
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navEl = document.querySelector('.nav-item[data-view="' + view + '"]');
    if (navEl) navEl.classList.add('active');
}}

// ── Modal helpers ──
function closeModal(id) {{
    document.getElementById(id).classList.remove('open');
}}

function openEditTask(t) {{
    document.getElementById('editTaskOld').value = t.text;
    document.getElementById('editTaskText').value = t.text;
    document.getElementById('editTaskDomain').value = t.domain || 'academic';
    document.getElementById('editTaskPriority').value = t.priority || 2;
    document.getElementById('editTaskEnergy').value = t.energy || 'med';
    document.getElementById('editTaskDue').value = t.due || '';
    document.getElementById('editTaskNotes').value = t.notes || '';
    document.getElementById('editTaskModal').classList.add('open');
}}

function saveEditTask() {{
    const old_text = document.getElementById('editTaskOld').value;
    const body = {{
        old_text: old_text,
        new_text: document.getElementById('editTaskText').value.trim(),
        new_priority: parseInt(document.getElementById('editTaskPriority').value),
        new_domain: document.getElementById('editTaskDomain').value,
        new_energy: document.getElementById('editTaskEnergy').value,
        new_due: document.getElementById('editTaskDue').value || '',
        new_notes: document.getElementById('editTaskNotes').value.trim(),
    }};
    closeModal('editTaskModal');
    apiCall('/api/edit_task', body);
}}

function openEditProject(p) {{
    document.getElementById('editProjOld').value = p.name;
    document.getElementById('editProjName').value = p.name;
    document.getElementById('editProjDomain').value = p.domain || 'academic';
    document.getElementById('editProjPriority').value = p.priority || 2;
    document.getElementById('editProjStatus').value = p.status || 'active';
    document.getElementById('editProjEffort').value = p.effort || 'high';
    document.getElementById('editProjDue').value = p.due || '';
    document.getElementById('editProjNext').value = p.next || '';
    document.getElementById('editProjectModal').classList.add('open');
}}

function saveEditProject() {{
    const old_name = document.getElementById('editProjOld').value;
    const body = {{
        old_name: old_name,
        new_name: document.getElementById('editProjName').value.trim(),
        new_priority: parseInt(document.getElementById('editProjPriority').value),
        new_domain: document.getElementById('editProjDomain').value,
        new_status: document.getElementById('editProjStatus').value,
        new_effort: document.getElementById('editProjEffort').value,
        new_due: document.getElementById('editProjDue').value || '',
        new_next: document.getElementById('editProjNext').value,
    }};
    closeModal('editProjectModal');
    apiCall('/api/edit_project', body);
}}

// ── R&D: New Project modal ──
let _npMode = 'new_folder';
// Tracks whether npName currently holds an auto-suggested basename (vs a value
// the user typed). When true, selecting a folder may overwrite it; the moment
// the user edits the field (npNameEdited), we stop auto-overwriting.
let _npAutoName = false;

function openNewProject() {{
    _npMode = 'new_folder';
    npSetMode('new_folder');
    document.getElementById('npName').value = '';
    document.getElementById('npParentPath').value = '';
    document.getElementById('npFolderPath').value = '';
    document.getElementById('npGitInit').checked = false;
    _npCurrentPath = null;
    _npAutoName = false;
    npUpdateSelectedUI();
    document.getElementById('newProjectModal').classList.add('open');
}}

// Called on every keystroke in the name field: a manual edit clears the
// auto-suggest flag so later folder selections never clobber the user's text.
function npNameEdited() {{ _npAutoName = false; }}

// Auto-suggest the project name from a selected folder's basename, but ONLY if
// the field is empty or still holds a prior auto-suggestion (never overwrite a
// value the user typed). Keeps the field fully editable.
function npSuggestName(path) {{
    if (!path) return;
    const nameEl = document.getElementById('npName');
    const cur = (nameEl.value || '').trim();
    if (cur !== '' && !_npAutoName) return;   // user typed their own — leave it
    const base = npBasename(path);
    if (!base) return;
    nameEl.value = base;
    _npAutoName = true;
}}

// Last path segment (drive-letter and trailing-separator aware), e.g.
// 'C:\\dev\\Anchor' -> 'Anchor', 'C:\\' -> 'C:'.
function npBasename(path) {{
    // NOTE: this is inside a Python f-string, so a literal backslash in the
    // emitted JS regex needs FOUR here ('\\\\' -> '\\' in JS -> one '\\' match).
    // Two backslashes would collapse to one in the f-string and the JS regex
    // would only match forward slashes, breaking Windows path basenames.
    let p = String(path).replace(/[\\\\/]+$/, '');     // strip trailing slashes
    const parts = p.split(/[\\\\/]+/);
    let base = parts[parts.length - 1] || '';
    if (/^[A-Za-z]:$/.test(base)) base = base.charAt(0);  // 'C:' -> 'C'
    return base;
}}

function npSetMode(mode) {{
    _npMode = mode;
    const isNew = mode === 'new_folder';
    document.getElementById('npNewFolderFields').style.display = isNew ? 'block' : 'none';
    document.getElementById('npExistingFields').style.display = isNew ? 'none' : 'block';
    document.getElementById('npModeNewBtn').className = 'btn btn-sm' + (isNew ? '' : ' btn-outline');
    document.getElementById('npModeExistingBtn').className = 'btn btn-sm' + (isNew ? ' btn-outline' : '');
    if (!isNew) npTreeInit();
}}

// ── Explorer-style expandable TREE picker ────────────────────────────────────
// Each tree node is a <div class="rnd-tree-node"> containing one clickable row
// (caret + folder icon + label) and a hidden children container. Clicking a row
// BOTH selects the node (highlight + Selected line + name auto-suggest) AND
// toggles lazy expansion (fetch child dirs from /api/rnd/dir_browse). Clicking
// an open node again collapses it. Drill arbitrarily deep.

let _npCurrentPath = null;   // the currently highlighted/selected folder path

// Populate the top level with the drive roots.
async function npTreeInit() {{
    const tree = document.getElementById('npTree');
    if (!tree) return;
    tree.innerHTML = '';
    _npCurrentPath = null;
    let data;
    try {{ data = await npDirBrowse(null); }}
    catch(e) {{ npTreeErr(tree, 'Browse failed: ' + e.message); return; }}
    const res = (data && data.result) || {{}};
    (res.roots || []).forEach(r => tree.appendChild(npMakeNode(r, r)));
}}

// Fetch helper — returns the parsed JSON for a dir_browse call.
async function npDirBrowse(path) {{
    const url = '/api/rnd/dir_browse' + (path ? ('?path=' + encodeURIComponent(path)) : '');
    const r = await fetch(url);
    return await r.json();
}}

// Build one tree node (row + empty children container). `path` is the absolute
// folder path; `label` is what to display (drive root or folder basename).
function npMakeNode(path, label) {{
    const node = document.createElement('div');
    node.className = 'rnd-tree-node';
    node.dataset.path = path;

    const row = document.createElement('div');
    row.className = 'rnd-tree-row';
    row.dataset.path = path;

    const caret = document.createElement('span');
    caret.className = 'rt-caret';
    caret.textContent = '\\u25B8';                // ▸ collapsed

    const icon = document.createElement('span');
    icon.className = 'rt-icon';
    icon.textContent = '\\uD83D\\uDCC1';          // 📁

    const name = document.createElement('span');
    name.className = 'rt-name';
    name.textContent = label;

    row.appendChild(caret);
    row.appendChild(icon);
    row.appendChild(name);

    const kids = document.createElement('div');
    kids.className = 'rnd-tree-children';
    kids.style.display = 'none';

    node.appendChild(row);
    node.appendChild(kids);

    node._loaded = false;
    node._open = false;

    // One click = select + toggle expand/collapse.
    row.addEventListener('click', function(ev) {{
        ev.stopPropagation();
        npTreeSelect(row, path);
        npTreeToggle(node);
    }});

    return node;
}}

// Highlight a row as the current selection, update the Selected line, and
// auto-suggest the project name.
function npTreeSelect(row, path) {{
    document.querySelectorAll('#npTree .rnd-tree-row.selected')
        .forEach(r => r.classList.remove('selected'));
    row.classList.add('selected');
    _npCurrentPath = path;
    document.getElementById('npFolderPath').value = path;
    npSuggestName(path);
    npUpdateSelectedUI();
}}

// Expand (lazy-load children on first open) or collapse a node.
async function npTreeToggle(node) {{
    const caret = node.querySelector(':scope > .rnd-tree-row > .rt-caret');
    const kids = node.querySelector(':scope > .rnd-tree-children');
    if (node._open) {{
        node._open = false;
        caret.textContent = '\\u25B8';            // ▸
        kids.style.display = 'none';
        return;
    }}
    node._open = true;
    caret.textContent = '\\u25BE';                // ▾
    kids.style.display = 'block';
    if (node._loaded) return;
    node._loaded = true;
    let data;
    try {{ data = await npDirBrowse(node.dataset.path); }}
    catch(e) {{ npTreeErr(kids, 'Browse failed: ' + e.message); return; }}
    const res = (data && data.result) || {{}};
    if (res.error) {{
        // Inline message; parent stays usable. Allow a later retry.
        node._loaded = false;
        npTreeErr(kids, "Can't open this folder — " + res.error);
        return;
    }}
    kids.innerHTML = '';
    const dirs = res.dirs || [];
    if (!dirs.length) {{
        const empty = document.createElement('div');
        empty.className = 'rnd-tree-err';
        empty.style.color = 'var(--text-dim)';
        empty.textContent = '(no subfolders)';
        kids.appendChild(empty);
        return;
    }}
    dirs.forEach(d => kids.appendChild(npMakeNode(d.path, d.name)));
}}

// Render a small inline error/notice inside a container.
function npTreeErr(container, msg) {{
    const e = document.createElement('div');
    e.className = 'rnd-tree-err';
    e.textContent = msg;
    container.innerHTML = '';
    container.appendChild(e);
    container.style.display = 'block';
}}

// "Use this folder" — confirm the currently highlighted folder (selection
// already set it; this is the explicit confirm affordance).
function npSelectCurrent() {{
    if (!_npCurrentPath) {{ showToast('Click a folder in the tree first'); return; }}
    document.getElementById('npFolderPath').value = _npCurrentPath;
    npSuggestName(_npCurrentPath);
    npUpdateSelectedUI();
    showToast('Using: ' + _npCurrentPath);
}}

function npUpdateSelectedUI() {{
    const sel = (document.getElementById('npFolderPath').value || '').trim();
    const el = document.getElementById('npSelected');
    if (!el) return;
    if (sel) {{
        el.classList.remove('empty');
        el.innerHTML = 'Selected: <b>' + escHtml(sel) + '</b>';
    }} else {{
        el.classList.add('empty');
        el.textContent = 'No folder selected yet';
    }}
}}

function escHtml(s) {{ const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }}
function jsStr(s) {{ return JSON.stringify(s == null ? '' : s); }}

async function createNewProject() {{
    const name = document.getElementById('npName').value.trim();
    if (!name) {{ showToast('Project name required'); return; }}
    const priority = parseInt(document.getElementById('npPriority').value);
    let body;
    if (_npMode === 'new_folder') {{
        const parent = document.getElementById('npParentPath').value.trim();
        if (!parent) {{ showToast('Parent path required'); return; }}
        body = {{mode: 'new_folder', name, priority, parent_path: parent,
                 git_init: document.getElementById('npGitInit').checked}};
    }} else {{
        const folder = document.getElementById('npFolderPath').value.trim();
        if (!folder) {{ showToast('No folder selected — browse to a folder and click “Select this folder”'); return; }}
        body = {{mode: 'existing', name, priority, folder_path: folder}};
    }}
    closeModal('newProjectModal');
    apiCall('/api/rnd/new_project', body);
}}

// 2026-05-12: stopServer() removed. The dashboard no longer kills its own
// server; that responsibility now belongs to the NSSM "anchor" service
// supervisor on gwl-server. To restart, run `nssm restart anchor`.
// /api/shutdown is also gone from the Python side, so external POSTs can
// no longer kill the server either.

function promoteProject(b64) {{ apiCall('/api/promote_project', {{name: dec(b64)}}); }}
function demoteProject(b64) {{ apiCall('/api/demote_project', {{name: dec(b64)}}); }}

// ── R&D project lifecycle (rich tiles) ──
// Open a project in ITS OWN window, named per-project: if that window is already
// open, this focuses it instead of opening a duplicate (multiple projects at a
// time, but one window each).
function openProjectWindow(pid) {{
    var w = window.open('/project/' + encodeURIComponent(pid), 'anchorproj_' + pid);
    if (w) {{ try {{ w.focus(); }} catch (e) {{}} }}
}}
function rndSetPriority(pid, pr) {{ apiCall('/api/rnd/set_priority', {{id: pid, priority: pr}}); }}
function rndArchive(pid) {{ if (confirm('Archive this project? It moves to the Archive view (kept, reviewable).')) apiCall('/api/rnd/archive_project', {{id: pid}}); }}
function rndRetire(pid) {{ if (confirm('Retire/cancel this project? It moves to the Archive view as retired.')) apiCall('/api/rnd/retire_project', {{id: pid}}); }}
function rndReactivate(pid) {{ apiCall('/api/rnd/reactivate_project', {{id: pid}}); }}
function rndRescan(pid) {{ apiCall('/api/rnd/rescan', {{id: pid}}); }}
// v3 Wave 5 — toggle a project ROW's kebab menu (lifecycle controls live here so
// the thin row stays one line). Closes any other open menu first.
function rndToggleKebab(ev, pid) {{
    ev.stopPropagation();
    var menu = document.getElementById('rnd-kebab-' + pid);
    var wasOpen = menu && menu.classList.contains('rnd-kebab-open');
    document.querySelectorAll('.rnd-kebab-menu.rnd-kebab-open').forEach(function(m) {{
        m.classList.remove('rnd-kebab-open');
    }});
    if (menu && !wasOpen) menu.classList.add('rnd-kebab-open');
}}
document.addEventListener('click', function() {{
    document.querySelectorAll('.rnd-kebab-menu.rnd-kebab-open').forEach(function(m) {{
        m.classList.remove('rnd-kebab-open');
    }});
}});
function rndNotes(pid) {{
    var el = document.querySelector('.rnd-row[data-project-id="' + pid + '"]');
    var cur = el ? (el.getAttribute('data-notes') || '') : '';
    var n = window.prompt('Project notes:', cur);
    if (n === null) return;
    apiCall('/api/rnd/set_notes', {{id: pid, notes: n}});
}}
function rndBlurb(pid) {{
    var el = document.querySelector('.rnd-row[data-project-id="' + pid + '"]');
    var cur = el ? (el.getAttribute('data-blurb') || '') : '';
    var n = window.prompt('What this project is (blurb):', cur);
    if (n === null) return;
    apiCall('/api/rnd/set_blurb', {{id: pid, blurb: n}});
}}
function promoteTask(b64) {{ apiCall('/api/promote_task', {{text: dec(b64)}}); }}
function demoteTask(b64) {{ apiCall('/api/demote_task', {{text: dec(b64)}}); }}

// Domain-specific add task
function toggleAddTask_(domain) {{
    const bar = document.getElementById('addTaskBar_' + domain);
    bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
    if (bar.style.display === 'flex') document.getElementById('newTask_' + domain).focus();
}}
// Alias so onclick="toggleAddTask_family()" works via dynamic name
{" ".join(f"function toggleAddTask_{d}() {{ toggleAddTask_('{d}'); }}" for d in domain_order)}

function addTaskDomain(domain) {{
    const text = document.getElementById('newTask_' + domain).value.trim();
    if (!text) return;
    const priority = parseInt(document.getElementById('newPriority_' + domain).value);
    const due = document.getElementById('newDue_' + domain).value || '';
    const notes = document.getElementById('newNotes_' + domain).value.trim();
    apiCall('/api/add', {{text, domain, priority, energy: 'med', due, notes}});
}}
</script>
<script>{cache_bust_script()}</script>
</body>
</html>'''


# ── HTTP Server ────────────────────────────────────────────────────────

class AnchorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_text):
        body = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data, content_type, cache="no-cache"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    # ── SSE for the interactive terminal (Wave 7) ────────────────────────────
    def _sse_event(self, event, data_obj):
        """Write ONE well-formed SSE event frame and flush it.

        Frame shape (per the SSE spec): an ``event:`` line, one ``data:`` line
        carrying a JSON payload, then a BLANK line terminating the event. Flushed
        immediately so a streaming client observes events as they arrive.
        """
        payload = json.dumps(data_obj, ensure_ascii=False)
        frame = f"event: {event}\ndata: {payload}\n\n"
        self.wfile.write(frame.encode("utf-8"))
        self.wfile.flush()

    def _serve_term_sse(self):
        """Stream a terminal session's output as Server-Sent Events.

        Stdlib-only streaming: a chunked ``text/event-stream`` response that
        loops, polling :func:`rnd_terminal.read_since` for new output, flushing an
        ``output`` event for new lines, a ``status`` event on change, and a
        ``gate`` event when an in-session prompt surfaces. It emits a
        ``heartbeat`` every few idle ticks and ENDS with a ``done`` event when the
        session is terminal OR a bounded tick budget elapses — so a test can read
        N events and the stream closes (no indefinite hang). The bound + poll
        interval are query-overridable for fast hermetic tests.
        """
        q = parse_qs(urlparse(self.path).query)
        session = (q.get("session", [""])[0] or "").strip()
        try:
            since = int(q.get("since", ["0"])[0] or 0)
        except (TypeError, ValueError):
            since = 0
        if not session:
            self._send_json({"ok": False, "error": "missing session"}, 400)
            return
        # Bounded loop knobs (defaults are production-sane; tests shrink them so
        # the stream ends quickly). poll_interval in seconds; max_ticks bounds the
        # total loop iterations; heartbeat_every emits a keep-alive on idle ticks.
        try:
            poll_interval = float(q.get("poll", ["0.25"])[0] or 0.25)
        except (TypeError, ValueError):
            poll_interval = 0.25
        try:
            max_ticks = int(q.get("max_ticks", ["240"])[0] or 240)
        except (TypeError, ValueError):
            max_ticks = 240
        try:
            heartbeat_every = int(q.get("hb", ["8"])[0] or 8)
        except (TypeError, ValueError):
            heartbeat_every = 8

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        # No Content-Length → chunked/streamed body via the connection close.
        self.end_headers()

        cursor = since
        last_status = None
        idle = 0
        try:
            for _tick in range(max(1, max_ticks)):
                # Guard the per-tick read + event emission so ANY exception from
                # read_since (not just pipe/OS errors) ends the stream CLEANLY
                # with a terminal done/error event instead of letting the handler
                # thread crash mid-stream and leaving the client hung (never
                # getting a 'done'). Pipe/connection errors mean the client is
                # already gone, so for those we just stop without trying to write.
                try:
                    out = _term.read_since(session, cursor)
                    lines = out.get("lines") or []
                    if lines:
                        self._sse_event("output", {"lines": lines,
                                                   "next": out.get("next", cursor)})
                        cursor = out.get("next", cursor)
                        idle = 0
                    else:
                        idle += 1
                    status = out.get("status")
                    if status and status != last_status:
                        self._sse_event("status", {"status": status})
                        last_status = status
                    pending = out.get("pending_prompt")
                    if pending:
                        self._sse_event("gate", {"prompt": pending})
                    if status in _term.TERMINAL_STATUSES:
                        # Drain any final lines, then end the stream cleanly.
                        final = _term.read_since(session, cursor)
                        fl = final.get("lines") or []
                        if fl:
                            self._sse_event("output", {"lines": fl,
                                                       "next": final.get("next", cursor)})
                            cursor = final.get("next", cursor)
                        self._sse_event("done", {"status": status, "next": cursor})
                        return
                    if heartbeat_every and idle and idle % heartbeat_every == 0:
                        self._sse_event("heartbeat", {"next": cursor})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # Client closed the connection — stop cleanly (re-raise to the
                    # outer guard, which simply returns).
                    raise
                except Exception:
                    # ANY other failure (a generic read_since error, a bad record,
                    # etc.): emit a final error-flavored done so the client always
                    # gets a terminal frame, then end the stream. Best-effort — if
                    # even this write fails the outer guard swallows it.
                    try:
                        self._sse_event("done", {"status": "error",
                                                 "next": cursor, "error": True})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return
                time.sleep(max(0.0, poll_interval))
            # Tick budget exhausted while still live — end with a heartbeat-flavored
            # done so the client can re-open (bounded, never an infinite hold).
            self._sse_event("done", {"status": last_status or "running",
                                     "next": cursor, "bounded": True})
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Client closed the connection — stop cleanly.
            return

    # ── ConPTY terminal transport (Wave 3) ──────────────────────────────────
    def _term_token_ok(self):
        """Auth a terminal GET endpoint via the ``?token=`` query param.

        Browsers can't set request headers on an EventSource / WebSocket
        handshake, so the terminal GET surface (an RCE surface) authenticates via
        a query-param token with the SAME semantics as ``paths.auth_ok``: if no
        token is configured (``ANCHOR_TOKEN`` unset) it is allowed (local
        back-compat); otherwise the provided token must match. Also accepts a
        token carried in the ``Sec-WebSocket-Protocol`` header (for WS clients).
        """
        q = parse_qs(urlparse(self.path).query)
        provided = (q.get("token", [None])[0])
        if provided is None:
            # WS clients may smuggle the token via the subprotocol header.
            provided = self.headers.get("Sec-WebSocket-Protocol")
        return _paths.auth_ok(provided)

    def _serve_term_stream2(self):
        """SSE-out fallback for a ConPTY session (Wave 3).

        The plan's named fallback half: an ``text/event-stream`` of a ConPTY
        session's output via ``pty_manager.read_since`` (through
        ``terminal_session.read_since``). Modeled on :meth:`_serve_term_sse` —
        bounded by ``max_ticks``, heartbeated, ends with a ``done`` event on a
        terminal (``dead``) status or when the tick budget elapses. Query knobs
        ``poll``/``max_ticks``/``hb``/``since`` mirror the v2 SSE handler.

        AUTH: ``?token=`` (401 when a token is configured and missing/wrong).
        """
        if not self._term_token_ok():
            self._send_json({"ok": False, "error": "unauthorized"}, 401)
            return
        q = parse_qs(urlparse(self.path).query)
        session = (q.get("session", [""])[0] or "").strip()
        try:
            since = int(q.get("since", ["0"])[0] or 0)
        except (TypeError, ValueError):
            since = 0
        if not session:
            self._send_json({"ok": False, "error": "missing session"}, 400)
            return
        try:
            poll_interval = float(q.get("poll", ["0.25"])[0] or 0.25)
        except (TypeError, ValueError):
            poll_interval = 0.25
        try:
            max_ticks = int(q.get("max_ticks", ["240"])[0] or 240)
        except (TypeError, ValueError):
            max_ticks = 240
        # Clamp client-supplied knobs (self-DoS guard): poll in [0.01, 1.0]s,
        # max_ticks in [1, 5000] — keeps tiny test values valid.
        poll_interval = min(1.0, max(0.01, poll_interval))
        max_ticks = min(5000, max(1, max_ticks))
        try:
            heartbeat_every = int(q.get("hb", ["8"])[0] or 8)
        except (TypeError, ValueError):
            heartbeat_every = 8

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        cursor = since
        last_status = None
        idle = 0
        try:
            for _tick in range(max(1, max_ticks)):
                try:
                    out = _termsess.read_since(session, cursor)
                    if not out.get("ok", True):  # unknown session
                        self._sse_event("done", {"status": "error",
                                                 "next": cursor, "error": True})
                        return
                    text = out.get("text", "")
                    if text:
                        self._sse_event("output", {"text": text,
                                                   "next": out.get("next", cursor)})
                        cursor = out.get("next", cursor)
                        idle = 0
                    else:
                        idle += 1
                    status = out.get("status")
                    if status and status != last_status:
                        self._sse_event("status", {"status": status})
                        last_status = status
                    if status == "dead":
                        final = _termsess.read_since(session, cursor)
                        ft = final.get("text", "") if isinstance(final, dict) else ""
                        if ft:
                            self._sse_event("output", {"text": ft,
                                                       "next": final.get("next", cursor)})
                            cursor = final.get("next", cursor)
                        self._sse_event("done", {"status": status, "next": cursor})
                        return
                    if heartbeat_every and idle and idle % heartbeat_every == 0:
                        self._sse_event("heartbeat", {"next": cursor})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    raise
                except Exception:
                    try:
                        self._sse_event("done", {"status": "error",
                                                 "next": cursor, "error": True})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return
                time.sleep(max(0.0, poll_interval))
            self._sse_event("done", {"status": last_status or "running",
                                     "next": cursor, "bounded": True})
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _serve_term_ws(self):
        """Hand-rolled stdlib WebSocket terminal endpoint (Wave 3, RFC 6455).

        Detects the ``Upgrade: websocket`` handshake, authenticates via
        ``?token=`` (or the ``Sec-WebSocket-Protocol`` header), computes the
        ``Sec-WebSocket-Accept`` value, replies ``101 Switching Protocols``, then
        takes over the raw socket and pumps PTY bytes BOTH ways:

        - decode client frames (text/binary -> ``terminal_session.input``;
          close -> end; ping -> pong);
        - poll ``terminal_session.read_since`` for new output -> encode + send
          server text frames.

        The pump loop is BOUNDED/interruptible (``poll``/``max_ticks`` query
        knobs, same as the SSE handler) so it ends cleanly on client close or a
        terminal (``dead``) session and is testable without hanging.
        """
        # AUTH FIRST: never upgrade an unauthorized handshake.
        if not self._term_token_ok():
            self._send_json({"ok": False, "error": "unauthorized"}, 401)
            return

        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self._send_json({"ok": False, "error": "missing Sec-WebSocket-Key"},
                            400)
            return

        q = parse_qs(urlparse(self.path).query)
        session = (q.get("session", [""])[0] or "").strip()
        if not session:
            self._send_json({"ok": False, "error": "missing session"}, 400)
            return
        try:
            poll_interval = float(q.get("poll", ["0.05"])[0] or 0.05)
        except (TypeError, ValueError):
            poll_interval = 0.05
        try:
            max_ticks = int(q.get("max_ticks", ["1200"])[0] or 1200)
        except (TypeError, ValueError):
            max_ticks = 1200
        # Clamp client-supplied knobs (self-DoS guard): poll in [0.01, 1.0]s,
        # max_ticks in [1, 5000] — keeps tiny test values valid.
        poll_interval = min(1.0, max(0.01, poll_interval))
        max_ticks = min(5000, max(1, max_ticks))

        # ── 101 handshake ────────────────────────────────────────────────
        accept = ws_accept_key(key)
        handshake = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: " + accept + "\r\n"
            "\r\n"
        )
        try:
            self.connection.sendall(handshake.encode("ascii"))
        except OSError:
            return

        # ── raw-socket pump (both ways), bounded + interruptible ─────────
        sock = self.connection
        sock.settimeout(max(0.01, poll_interval))
        inbuf = b""
        cursor = 0
        ws_state = {}  # persistent fragmentation-reassembly state for decode_frames
        try:
            for _tick in range(max(1, max_ticks)):
                # 1) Drain client -> PTY (non-blocking-ish via the socket timeout).
                try:
                    chunk = sock.recv(65536)
                    if chunk == b"":
                        break  # client closed the TCP connection
                    inbuf += chunk
                    # Guard the carried inbuf so an endless stream of incomplete
                    # frame headers can't grow it without bound either.
                    if len(inbuf) > MAX_WS_FRAME:
                        break
                    msgs, inbuf = decode_frames(inbuf, ws_state,
                                                require_mask=True)
                    closed = False
                    for opcode, payload in msgs:
                        if opcode in (WS_SIGNAL_CLOSE, WS_OP_CLOSE):
                            # Protocol error or a client close -> clean close.
                            closed = True
                            break
                        if opcode == WS_OP_PING:
                            try:
                                sock.sendall(encode_pong_frame(payload))
                            except OSError:
                                closed = True
                                break
                            continue
                        if opcode == WS_OP_PONG:
                            continue  # unsolicited pong — ignore
                        if opcode in (WS_OP_TEXT, WS_OP_BINARY):
                            # Reassembled, complete data message (CONT frames are
                            # folded in by the codec — never delivered alone).
                            data = payload.decode("utf-8", "replace")
                            res = _termsess.input(session, data)
                            if not res.get("ok"):
                                closed = True
                                break
                    if closed:
                        break
                except socket.timeout:
                    pass
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break

                # 2) Pump PTY -> client.
                try:
                    out = _termsess.read_since(session, cursor)
                except Exception:
                    break
                if not out.get("ok", True):
                    break  # unknown session
                text = out.get("text", "")
                if text:
                    try:
                        sock.sendall(encode_text_frame(text))
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break
                    cursor = out.get("next", cursor)
                if out.get("status") == "dead":
                    # Drain any final output, then close cleanly.
                    final = _termsess.read_since(session, cursor)
                    ft = final.get("text", "") if isinstance(final, dict) else ""
                    if ft:
                        try:
                            sock.sendall(encode_text_frame(ft))
                        except OSError:
                            pass
                    break
        finally:
            try:
                sock.sendall(encode_close_frame())
            except OSError:
                pass

    def do_GET(self):
        try:
            _path_only = urlparse(self.path).path
            if (self.headers.get("Upgrade", "").lower() == "websocket"
                    and _path_only == "/api/rnd/term_ws"):
                # Hand-rolled stdlib WebSocket terminal transport (Wave 3). Must
                # be checked BEFORE the normal GET dispatch because it takes over
                # the raw socket. Auth-gated inside (?token=).
                self._serve_term_ws()
                return
            if _path_only == "/api/rnd/term_stream2":
                # SSE-out fallback for a ConPTY session (Wave 3). Auth-gated
                # inside (?token=). Distinct from the v2 /api/rnd/term_stream.
                self._serve_term_stream2()
                return
            if _path_only == "/" or _path_only == "/dashboard":
                # Serve the dashboard for "/" REGARDLESS of query string so the
                # cache-busting reload ("/?v=<build_id>") lands on the dashboard
                # instead of 404ing.
                projects, tasks, inbox = gather_all()
                html = generate_html(projects, tasks, inbox)
                self._send_html(html)
            elif _path_only == "/api/version":
                # Must always be fetched fresh (no-store) so the self-healing
                # client can detect a redeploy.
                body = json.dumps({"version": BUILD_ID}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/favicon.ico" or self.path.startswith("/anchor.ico"):
                ico_path = ANCHOR_DIR / "anchor.ico"
                if ico_path.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/x-icon")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(ico_path.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path.startswith("/anchor.png"):
                png_path = ANCHOR_DIR / "anchor.png"
                if png_path.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(png_path.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path.startswith("/anchor-touch.png"):
                png_path = ANCHOR_DIR / "anchor-touch.png"
                if png_path.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(png_path.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path == "/api/status":
                projects, tasks, inbox = gather_all()
                active = [t for t in tasks if not t["done"]]
                self._send_json({
                    "projects": len(projects),
                    "active": len(active),
                    "done": len([t for t in tasks if t["done"]]),
                    "inbox": len(inbox),
                })
            elif self.path.startswith(_rv.KATEX_URL_PREFIX):
                # Read-only vendored KaTeX static assets for the Reader (Wave 7).
                rel = urlparse(self.path).path[len(_rv.KATEX_URL_PREFIX):]
                asset = _rv.katex_asset(rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype, cache="public, max-age=86400")
            elif self.path.startswith(XTERM_URL_PREFIX):
                # Read-only vendored REAL xterm.js static asset (terminal canvas),
                # served like KaTeX (traversal-safe). Loaded before anchor-term.js.
                rel = urlparse(self.path).path[len(XTERM_URL_PREFIX):]
                asset = xterm_asset(rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype, cache="public, max-age=86400")
            elif self.path.startswith(ANCHOR_TERM_URL_PREFIX):
                # Read-only vendored terminal-console static asset (Wave 7),
                # served like KaTeX (traversal-safe). Backs the interactive
                # terminal that replaced the raw-log launch console.
                rel = urlparse(self.path).path[len(ANCHOR_TERM_URL_PREFIX):]
                asset = anchor_term_asset(rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype, cache="public, max-age=3600")
            elif self.path.startswith("/api/rnd/term_stream"):
                # SSE (Server-Sent Events) stream of a terminal session's output
                # (Wave 7). Implemented on stdlib http.server as a chunked
                # text/event-stream response loop: it flushes "output"/"status"/
                # "gate" events as new lines arrive, emits periodic "heartbeat"
                # events, and TERMINATES cleanly with a "done" event when the
                # session reaches a terminal status OR a bounded number of ticks
                # elapses. The bound (max_ticks) makes it TESTABLE without
                # hanging: a client reads a finite set of events and the stream
                # ends. The ThreadingHTTPServer handles concurrent streams.
                self._serve_term_sse()
            elif self.path.startswith("/report/"):
                # Read-only report viewer (Wave 7): PDF-by-default else Reader.
                # /report/<project_id>/<lane>[/<job_id>]
                parts = [p for p in urlparse(self.path).path[len("/report/"):]
                         .split("/") if p]
                if len(parts) < 2:
                    self.send_response(404)
                    self.end_headers()
                else:
                    pid, lane = parts[0], parts[1]
                    job_id = parts[2] if len(parts) > 2 else None
                    # Reject path-separator / traversal in the path-bound
                    # segments before they hit the filesystem (consistent with
                    # the hardened KaTeX static route).
                    if any(_unsafe_path_seg(seg)
                           for seg in (lane, job_id) if seg is not None):
                        self.send_response(400)
                        self.end_headers()
                        return
                    proj = _rnd.get_project(pid)
                    folder = (proj or {}).get("folder_path", "")
                    out = _rv.render_effort(folder, pid, lane, job_id)
                    body = out["body"]
                    if isinstance(body, str):
                        body = body.encode("utf-8")
                    self._send_bytes(body, out["content_type"])
            elif self.path.startswith("/summary/"):
                # Read-only cached session SUMMARY page (Wave 6): the validated,
                # cached markdown summary (goal · key decisions · files-with-
                # links) rendered via report_viewer (vendored KaTeX). Generated
                # once on first view (run-once), then served from cache.
                # /summary/<project_id>/<lane>/<session_id>
                parts = [p for p in urlparse(self.path).path[len("/summary/"):]
                         .split("/") if p]
                if len(parts) < 3:
                    self.send_response(404)
                    self.end_headers()
                else:
                    pid, lane = parts[0], parts[1]
                    # The session_id may itself contain '/'-free '::' segments;
                    # rejoin any remaining components defensively.
                    session_id = "/".join(parts[2:])
                    if _unsafe_path_seg(lane):
                        self.send_response(400)
                        self.end_headers()
                        return
                    proj = _rnd.get_project(pid)
                    folder = (proj or {}).get("folder_path", "")
                    # Look up the live session record so an uncached summary can
                    # be generated on first view (run-once).
                    session = None
                    try:
                        for s in _sessions.list_sessions(folder, pid, lane):
                            if s.get("session_id") == session_id:
                                session = s
                                break
                    except Exception:
                        session = None
                    out = _summarizer.render_summary_page(
                        folder, pid, lane, session_id, session=session)
                    body = out["body"]
                    if isinstance(body, str):
                        body = body.encode("utf-8")
                    self._send_bytes(body, out["content_type"])
            elif self.path.startswith("/api/rnd/session_summary"):
                # Read-only structured SESSION summary as JSON (v3 Wave 6): the
                # in-place accordion fetches this instead of navigating to the
                # /summary page. If cached → return it. If NOT cached → kick off
                # background generation (run-once, runner seam) and return a
                # {status:"generating"} fallback so the panel can re-fetch. This
                # NEVER runs the model synchronously on the request thread.
                # /api/rnd/session_summary?pid=<id>&lane=<lane>&session=<sid>
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("pid", [""])[0] or "").strip()
                lane = (q.get("lane", [""])[0] or "").strip()
                session_id = (q.get("session", [""])[0] or "").strip()
                if not pid or not lane or not session_id:
                    self._send_json({"ok": False,
                                     "error": "pid, lane, session required"}, 400)
                elif _unsafe_path_seg(pid):
                    self._send_json({"ok": False, "error": "bad pid"}, 400)
                elif _unsafe_path_seg(lane):
                    self._send_json({"ok": False, "error": "bad lane"}, 400)
                else:
                    proj = _rnd.get_project(pid)
                    folder = (proj or {}).get("folder_path", "")
                    store_lane = _eh._resolve_subdir(lane)
                    cached = None
                    try:
                        cached = _summarizer.load_cached(
                            folder, pid, store_lane, session_id)
                    except Exception:
                        cached = None
                    if isinstance(cached, dict) and not cached.get("error"):
                        self._send_json({"ok": True, "status": "ready",
                                         "summary": cached})
                    elif proj is None:
                        # Unknown / unregistered project → TERMINAL status so a
                        # polling panel STOPS (never an endless "generating").
                        self._send_json({"ok": True, "status": "unknown"})
                    else:
                        # Not cached (or a prior failed/uncached run): resolve the
                        # live session record so generation can seed from its
                        # members. If the session id is not among the project's
                        # sessions for this lane → TERMINAL "unknown" (the panel
                        # stops polling). Otherwise kick off background
                        # generation run-once and tell the panel to poll.
                        session = None
                        try:
                            for s in _sessions.list_sessions(folder, pid, lane):
                                if s.get("session_id") == session_id:
                                    session = s
                                    break
                        except Exception:
                            session = None
                        if session is None:
                            self._send_json({"ok": True, "status": "unknown"})
                        else:
                            _trigger_session_summary(
                                folder, pid, lane, session)
                            self._send_json({"ok": True, "status": "generating"})
            elif self.path.startswith("/artifact/"):
                # Read-only serving of a DISCOVERED (brownfield) artifact from a
                # project's folder (Wave 4). Traversal-safe via the proven
                # report_viewer.katex_asset containment pattern:
                #   target=(folder/rel).resolve(); target.relative_to(folder)
                # Rejects absolute rel, ../.. escape, .git/.anchor, symlink
                # escape -> 400/404, ZERO bytes read.
                pid = urlparse(self.path).path[len("/artifact/"):].strip("/")
                q = parse_qs(urlparse(self.path).query)
                rel = q.get("path", [None])[0]
                if not pid or not rel:
                    self.send_response(400)
                    self.end_headers()
                    return
                proj = _rnd.get_project(pid)
                folder = (proj or {}).get("folder_path", "")
                if not folder:
                    self.send_response(404)
                    self.end_headers()
                    return
                asset = _rv.resolve_project_artifact(folder, rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype)
            elif self.path.startswith("/project/"):
                # Per-project window (Wave 3 basic view + 4-state status line).
                # Opening a brownfield project DISCOVERS + ADOPTS its on-disk
                # trio artifacts so the Kanban/tile/home panel populate (Wave 6).
                pid = urlparse(self.path).path[len("/project/"):].strip("/")
                try:
                    discover_and_adopt(pid)
                except Exception:
                    pass  # discovery is best-effort; never block the view
                self._send_html(render_project_window_html(pid))
            elif self.path.startswith("/api/rnd/term_sessions"):
                # Read-only (Wave 4): live managed terminal sessions for a
                # project — the repopulate-from-registry hook the window-manager
                # button bar paints from on load. Returns a SAFE projection of
                # each registry record (NO absolute worktree_path — the UI has
                # no need for it). Consistent with /api/rnd/projects (GET, no
                # mutation, no auth gate).
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0] or "").strip()
                try:
                    recs = _termsess.list_sessions(project_id=pid or None)
                except Exception:
                    recs = []
                safe = []
                for r in recs:
                    if not isinstance(r, dict):
                        continue
                    safe.append({
                        "session_id": r.get("session_id"),
                        "lane": r.get("lane", ""),
                        "backend": r.get("backend", ""),
                        "status": r.get("status", ""),
                        "label": r.get("label", ""),
                        "created_at": r.get("created_at"),
                    })
                self._send_json({"ok": True, "sessions": safe})
            elif self.path.startswith("/api/rnd/projects"):
                # Read-only: folder-grouped registry listing.
                self._send_json({"ok": True,
                                 "groups": _rnd.group_by_folder()})
            elif self.path.startswith("/api/rnd/dir_browse"):
                # Read-only directory browser for the "select existing" UI.
                q = parse_qs(urlparse(self.path).query)
                path_arg = q.get("path", [None])[0]
                self._send_json({"ok": True,
                                 "result": _dirb.browse(path_arg)})
            elif self.path.startswith("/api/rnd/tail"):
                # Read-only incremental log tail for the project-window console
                # drawer. Returns {lines,next,status,pending_prompt}. This is a
                # plain non-blocking ?since= fetch (the JS polls ~1.5s); it never
                # holds the request, so it can't stall the dashboard.
                q = parse_qs(urlparse(self.path).query)
                job_id = (q.get("job_id", [""])[0] or "").strip()
                try:
                    since = int(q.get("since", ["0"])[0] or 0)
                except (TypeError, ValueError):
                    since = 0
                if not job_id:
                    self._send_json({"ok": False, "error": "missing job_id"}, 400)
                else:
                    out = _jr.tail(job_id, since)
                    try:
                        pending = _gate.load_pending_prompt(job_id)
                    except Exception:
                        pending = None
                    self._send_json({
                        "ok": True,
                        "lines": out.get("lines", []),
                        "next": out.get("next", since),
                        "total": out.get("total", 0),
                        "status": out.get("status"),
                        "pending_prompt": pending,
                    })
            elif self.path.startswith("/api/rnd/jobs"):
                # Read-only: recent job records for a project (lane status).
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0] or "").strip()
                jobs = [r for r in _jr.list_records()
                        if not pid or r.get("project_id") == pid]
                jobs.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
                self._send_json({"ok": True, "jobs": jobs})
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            _logger.error(f"GET {self.path} failed: {e}\n{traceback.format_exc()}")
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_POST(self):
      try:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        # Token-auth middleware (Wave 2 / D4). Every mutating /api/* POST
        # requires a valid shared-secret token when ANCHOR_TOKEN is configured.
        # If ANCHOR_TOKEN is unset, auth is disabled (local-only back-compat).
        # The token may be supplied via the X-Anchor-Token header (preferred)
        # or a "token" field in the JSON body. Read endpoints are not gated.
        provided = self.headers.get("X-Anchor-Token")
        if provided is None and isinstance(body, dict):
            provided = body.get("token")
        if not _paths.auth_ok(provided):
            self._send_json({"ok": False, "error": "unauthorized"}, 401)
            return

        if self.path == "/api/done":
            text = body.get("text", "")
            ok = mark_done(text)
            self._send_json({"ok": ok, "message": f"Marked done: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/undone":
            text = body.get("text", "")
            ok = mark_undone(text)
            self._send_json({"ok": ok, "message": f"Reopened: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/add":
            text = body.get("text", "")
            domain = body.get("domain", "academic")
            priority = body.get("priority", 2)
            energy = body.get("energy", "med")
            due = body.get("due", "")
            notes = body.get("notes", "")
            add_task(text, domain, priority, energy, due, notes)
            self._send_json({"ok": True, "message": f"Added: {text} [{domain}] P{priority}"})

        elif self.path == "/api/capture":
            text = body.get("text", "")
            domain = body.get("domain", "")
            capture_inbox(text, domain)
            self._send_json({"ok": True, "message": f"Captured: {text}"})

        elif self.path == "/api/edit_task":
            old_text = body.get("old_text", "")
            ok = edit_task(
                old_text,
                new_text=body.get("new_text"),
                new_priority=body.get("new_priority"),
                new_domain=body.get("new_domain"),
                new_energy=body.get("new_energy"),
                new_due=body.get("new_due"),
                new_notes=body.get("new_notes"),
            )
            self._send_json({"ok": ok, "message": f"Updated task" if ok else f"Task not found: {old_text}"})

        elif self.path == "/api/edit_project":
            old_name = body.get("old_name", "")
            ok = edit_project(
                old_name,
                new_name=body.get("new_name"),
                new_priority=body.get("new_priority"),
                new_domain=body.get("new_domain"),
                new_status=body.get("new_status"),
                new_effort=body.get("new_effort"),
                new_due=body.get("new_due"),
                new_next=body.get("new_next"),
            )
            self._send_json({"ok": ok, "message": f"Updated project" if ok else f"Project not found: {old_name}"})

        elif self.path == "/api/promote_project":
            name = body.get("name", "")
            ok = edit_project(name, new_priority=1)
            self._send_json({"ok": ok, "message": f"Promoted to P1: {name}" if ok else f"Not found: {name}"})

        elif self.path == "/api/demote_project":
            name = body.get("name", "")
            ok = edit_project(name, new_priority=2)
            self._send_json({"ok": ok, "message": f"Demoted to P2: {name}" if ok else f"Not found: {name}"})

        elif self.path == "/api/promote_task":
            text = body.get("text", "")
            ok = edit_task(text, new_priority=1)
            self._send_json({"ok": ok, "message": f"Promoted to P1: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/demote_task":
            text = body.get("text", "")
            ok = edit_task(text, new_priority=2)
            self._send_json({"ok": ok, "message": f"Demoted to P2: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/cancel":
            text = body.get("text", "")
            ok = cancel_task(text)
            self._send_json({"ok": ok, "message": f"Cancelled: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/save_for_later":
            text = body.get("text", "")
            ok = save_for_later(text)
            self._send_json({"ok": ok, "message": f"Saved for later: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/restore":
            text = body.get("text", "")
            from_archive = body.get("from", "saved")
            ok = restore_task(text, from_archive)
            self._send_json({"ok": ok, "message": f"Restored: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/heartbeat":
            global _last_heartbeat
            _last_heartbeat = datetime.now()
            self._send_json({"ok": True})

        # ── R&D control surface (Wave 3) ──────────────────────────────
        elif self.path == "/api/rnd/new_project":
            mode = body.get("mode", "existing")
            name = body.get("name", "")
            priority = body.get("priority", 2)
            if mode == "new_folder":
                res = create_new_folder_project(
                    name, body.get("parent_path", ""),
                    priority=priority,
                    git_init=bool(body.get("git_init", False)),
                )
            else:
                res = select_existing_project(
                    name, body.get("folder_path", ""), priority=priority,
                )
            self._send_json({"ok": True, **res})

        elif self.path == "/api/rnd/open_project":
            pid = body.get("id", "")
            self._send_json({"ok": True, **open_project_instance(pid)})

        elif self.path == "/api/rnd/rescan":
            # Re-discover + re-adopt a brownfield project's on-disk artifacts:
            # scan -> adopt -> reconcile (prune deletions) -> rewrite marker.
            # Idempotent (no dupes). Clean JSON; never a 500 for a bad folder.
            pid = body.get("id", "") or body.get("project_id", "")
            res = discover_and_adopt(pid)
            code = 200 if res.get("ok") else 404
            self._send_json(res, code)

        elif self.path == "/api/rnd/set_priority":
            pid = body.get("id", "")
            try:
                entry = _rnd.set_priority(pid, int(body.get("priority", 2)))
                self._send_json({"ok": True, "entry": entry})
            except KeyError:
                self._send_json({"ok": False, "error": "Not found"}, 404)

        elif self.path == "/api/rnd/archive_project":
            pid = body.get("id", "")
            try:
                self._send_json({"ok": True,
                                 "entry": _rnd.archive_project(pid)})
            except KeyError:
                self._send_json({"ok": False, "error": "Not found"}, 404)

        elif self.path == "/api/rnd/future_project":
            pid = body.get("id", "")
            try:
                self._send_json({"ok": True,
                                 "entry": _rnd.mark_future(pid)})
            except KeyError:
                self._send_json({"ok": False, "error": "Not found"}, 404)

        elif self.path == "/api/rnd/retire_project":
            pid = body.get("id", "")
            try:
                self._send_json({"ok": True,
                                 "entry": _rnd.retire_project(pid)})
            except KeyError:
                self._send_json({"ok": False, "error": "Not found"}, 404)

        elif self.path == "/api/rnd/reactivate_project":
            pid = body.get("id", "")
            try:
                self._send_json({"ok": True,
                                 "entry": _rnd.reactivate_project(pid)})
            except KeyError:
                self._send_json({"ok": False, "error": "Not found"}, 404)

        elif self.path == "/api/rnd/set_notes":
            pid = body.get("id", "")
            try:
                self._send_json({"ok": True,
                                 "entry": _rnd.set_notes(pid, body.get("notes", ""))})
            except KeyError:
                self._send_json({"ok": False, "error": "Not found"}, 404)

        elif self.path == "/api/rnd/set_blurb":
            pid = body.get("id", "")
            try:
                self._send_json({"ok": True,
                                 "entry": _rnd.set_blurb(pid, body.get("blurb", ""))})
            except KeyError:
                self._send_json({"ok": False, "error": "Not found"}, 404)

        # ── R&D control surface (Wave 9) ──────────────────────────────
        elif self.path == "/api/rnd/link_task":
            # Link/unlink a task ↔ R&D project (activates the Project: field).
            text = body.get("text", "")
            pid = body.get("project_id", "")
            ok = link_task(text, pid)
            self._send_json({
                "ok": ok,
                "message": (f"Linked '{text}' → {pid}" if pid else
                            f"Unlinked '{text}'") if ok
                           else f"Task not found: {text}",
            })

        elif self.path == "/api/rnd/run_deliverable":
            # Run a deliverable per its type contract; persist + report status.
            pid = body.get("project_id", "")
            proj = _rnd.get_project(pid)
            if proj is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                folder = proj.get("folder_path", "")
                try:
                    rec = _deliv.run_deliverable(
                        body.get("type", ""),
                        target=body.get("target"),
                        argv=body.get("argv"),
                        cwd=body.get("cwd") or folder or None,
                        timeout=float(body.get("timeout",
                                               _deliv.DEFAULT_TIMEOUT)),
                        folder_path=folder,
                        project_id=pid,
                        name=body.get("name"),
                    )
                    self._send_json({"ok": True, "status": rec})
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)

        elif self.path == "/api/rnd/pin_deliverable":
            # Pin a path (e.g. anchor_gui.py) as a deliverable so it surfaces as
            # a deliverables-lane effort even though it is not under a
            # deliverables/ directory. With "declare":true, instead pin every
            # deliverable declared in the folder's Anchor.md marker block.
            pid = body.get("project_id", "")
            proj = _rnd.get_project(pid)
            if proj is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                folder = proj.get("folder_path", "")
                if body.get("declare"):
                    res = _deliv.declare_deliverables_from_marker(folder, pid)
                    self._send_json({"ok": True, **res})
                else:
                    path = body.get("path", "") or body.get("target", "")
                    if not path:
                        self._send_json({"ok": False,
                                         "error": "path required"}, 400)
                    else:
                        try:
                            rec = _deliv.pin_deliverable(
                                folder, pid, path,
                                name=body.get("name"),
                                dtype=body.get("type"),
                                description=body.get("description", ""),
                            )
                        except ValueError as e:
                            # A path that escapes the project folder is rejected
                            # cleanly (400), never a 500-crash.
                            self._send_json({"ok": False, "error": str(e)}, 400)
                        else:
                            self._send_json({"ok": True, "effort": rec})

        # ── R&D control surface — lane launch + gate answer (UI wiring) ──
        elif self.path == "/api/rnd/launch_lane":
            # Launch a trio lane (research|plan|build) for a project. Returns a
            # clean JSON error (not a 500) for an unknown project / invalid lane
            # / a concurrency refusal (same-lane-busy or folder-build-lock).
            pid = body.get("project_id", "")
            lane = body.get("lane", "")
            backend = body.get("backend") or _lanes.DEFAULT_BACKEND
            if lane not in _lanes.LANES:
                self._send_json({"ok": False, "error": f"invalid lane: {lane}",
                                 "reason": "invalid-lane"}, 400)
            elif backend not in (_lanes.BACKEND_CLAUDE, _lanes.BACKEND_GEMINI):
                self._send_json({"ok": False,
                                 "error": f"invalid engine: {backend}",
                                 "reason": "invalid-engine"}, 400)
            else:
                try:
                    rec = _lanes.launch_lane(pid, lane, backend=backend)
                    self._send_json({
                        "ok": True,
                        "job_id": rec.get("job_id"),
                        "lane": lane,
                        "backend": rec.get("backend"),
                        "status": rec.get("status"),
                        "skill": rec.get("skill"),
                        "gates": rec.get("gates"),
                    })
                except _lanes.EngineNotAllowedError as eng:
                    # Engine policy refused (e.g. gemini on plan/build) — clean
                    # JSON error, NOT a 500.
                    self._send_json({
                        "ok": False,
                        "error": str(eng),
                        "reason": "engine-not-allowed",
                        "lane": eng.lane,
                        "backend": eng.backend,
                    }, 400)
                except KeyError:
                    self._send_json({"ok": False,
                                     "error": f"unknown project: {pid}",
                                     "reason": "unknown-project"}, 404)
                except _jr.LaneBusyError as busy:
                    # Concurrency policy refused the launch — surface a clean
                    # indicator (same-lane-busy / folder-build-lock), not a 500.
                    self._send_json({
                        "ok": False,
                        "error": str(busy),
                        "reason": busy.reason,
                        "holder": busy.holder,
                    }, 409)

        elif self.path == "/api/rnd/answer_gate":
            # Answer a pending in-session gate by writing a single stdin turn.
            job_id = body.get("job_id", "")
            choice = body.get("choice", "")
            res = _gate.answer(job_id, choice)
            self._send_json({
                "ok": bool(res.written),
                "written": bool(res.written),
                "reason": res.reason,
                "job_id": res.job_id,
            })

        # ── R&D interactive terminal (Wave 7) ─────────────────────────
        elif self.path == "/api/rnd/start_terminal":
            # Start a persistent interactive terminal session for a lane. The
            # returned job_id is the terminal session id the SSE stream + input
            # endpoints key off of. Clean JSON errors (not 500s) for unknown
            # project / invalid lane / engine or concurrency refusals.
            pid = body.get("project_id", "")
            lane = body.get("lane", "")
            backend = body.get("backend") or _lanes.DEFAULT_BACKEND
            if lane not in _lanes.LANES:
                self._send_json({"ok": False, "error": f"invalid lane: {lane}",
                                 "reason": "invalid-lane"}, 400)
            elif backend not in (_lanes.BACKEND_CLAUDE, _lanes.BACKEND_GEMINI):
                self._send_json({"ok": False,
                                 "error": f"invalid engine: {backend}",
                                 "reason": "invalid-engine"}, 400)
            else:
                try:
                    rec = _term.start_terminal(pid, lane, backend=backend)
                    self._send_json({
                        "ok": True,
                        "session": rec.get("job_id"),
                        "job_id": rec.get("job_id"),
                        "lane": lane,
                        "backend": rec.get("backend"),
                        "status": rec.get("status"),
                        "skill": rec.get("skill"),
                        "gates": rec.get("gates"),
                    })
                except _lanes.EngineNotAllowedError as eng:
                    self._send_json({"ok": False, "error": str(eng),
                                     "reason": "engine-not-allowed",
                                     "lane": eng.lane, "backend": eng.backend},
                                    400)
                except KeyError:
                    self._send_json({"ok": False,
                                     "error": f"unknown project: {pid}",
                                     "reason": "unknown-project"}, 404)
                except _jr.LaneBusyError as busy:
                    self._send_json({"ok": False, "error": str(busy),
                                     "reason": busy.reason,
                                     "holder": busy.holder}, 409)

        elif self.path == "/api/rnd/term_input":
            # Write ONE user turn onto a live terminal session's stdin (reuses the
            # gate-adapter stdin sink — never forks it). Auth is enforced by the
            # middleware above. Clean JSON for an unknown/terminal session.
            session = (body.get("session", "") or body.get("job_id", "")).strip()
            text = body.get("text", "")
            if not session:
                self._send_json({"ok": False, "error": "missing session"}, 400)
            elif text is None or not str(text).strip():
                # Reject an empty/whitespace-only turn cleanly (nothing written).
                self._send_json({"ok": False, "written": False,
                                 "session": session, "error": "empty turn",
                                 "reason": "empty"}, 400)
            elif len(str(text)) > _term.MAX_TURN_CHARS:
                # Reject an oversized turn cleanly (nothing written).
                self._send_json({"ok": False, "written": False,
                                 "session": session, "error": "turn too large",
                                 "reason": "too-large"}, 413)
            else:
                ok = _term.send_turn(session, text)
                self._send_json({"ok": bool(ok), "written": bool(ok),
                                 "session": session,
                                 "reason": None if ok else "not-writable"})

        elif self.path == "/api/rnd/term_discover":
            # On session exit, return the adoption PROPOSAL (files this session
            # produced under its output dir) for the UI to confirm. Read-style but
            # POSTed so the token-aware client path is uniform.
            session = (body.get("session", "") or body.get("job_id", "")).strip()
            proposal = _term.discover_produced(session) if session else None
            if proposal is None:
                self._send_json({"ok": False,
                                 "error": f"unknown session: {session}",
                                 "reason": "unknown-session"}, 404)
            else:
                self._send_json({"ok": True, "proposal": proposal})

        elif self.path == "/api/rnd/term_adopt":
            # Confirm-adopt a terminal session's produced files as ONE session in
            # the lane (Wave 1 grouping + Wave 2 adopt paths). Auth enforced above.
            session = (body.get("session", "") or body.get("job_id", "")).strip()
            if not session:
                self._send_json({"ok": False, "error": "missing session"}, 400)
            else:
                sess = _term.adopt_produced(session)
                if sess is None:
                    self._send_json({"ok": False,
                                     "error": "nothing to adopt",
                                     "reason": "nothing-adoptable"}, 404)
                else:
                    self._send_json({"ok": True, "session": sess})

        elif self.path == "/api/rnd/cancel_job":
            # Stop a running job (tree-kill via job_runner.cancel). Acts on the
            # job_id supplied by the ATTACHED console session only — the caller
            # passes the exact job_id, so two concurrent sessions never cross-
            # wire. A clean 404 for an unknown id; auth is already enforced by the
            # middleware above (this is a mutating POST).
            job_id = (body.get("job_id", "") or "").strip()
            rec = _jr.load_record(job_id) if job_id else None
            if rec is None:
                self._send_json({"ok": False, "error": f"unknown job: {job_id}",
                                 "reason": "unknown-job"}, 404)
            else:
                out = _jr.cancel(job_id)
                self._send_json({
                    "ok": True,
                    "job_id": job_id,
                    "status": (out or {}).get("status"),
                })

        # ── ConPTY terminal session lifecycle (Wave 3) ────────────────
        # These are the NEW ConPTY surface — distinct from the v2 REPL
        # endpoints (start_terminal/term_input/term_stream). Auth is enforced
        # by the middleware above (mutating POSTs).
        elif self.path == "/api/rnd/term_start":
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            lane = (body.get("lane", "") or "").strip()
            backend = (body.get("backend", "") or "claude").strip() or "claude"
            label = body.get("label", "") or ""
            # Wave 6 seam: a launch-from-panel carries the source session id as a
            # seed hint. start_session does NOT consume it yet (a bare
            # interactive PTY); Wave 7 wires the stage-handoff on top of this.
            _seed_session = (body.get("seed_session", "") or "").strip()
            if not pid or not lane:
                self._send_json({"ok": False,
                                 "error": "project_id and lane required"}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                try:
                    rec = _termsess.start_session(pid, lane, backend=backend,
                                                  label=label)
                    self._send_json({"ok": True, "session": rec})
                except _termsess.TerminalSessionError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)

        elif self.path == "/api/rnd/term_kill":
            session = (body.get("session", "") or "").strip()
            if not session:
                self._send_json({"ok": False, "error": "session required"}, 400)
            elif _termsess.get_session(session) is None:
                self._send_json({"ok": False,
                                 "error": f"unknown session: {session}",
                                 "reason": "unknown-session"}, 404)
            else:
                out = _termsess.kill(session)
                self._send_json({"ok": True, "result": out})

        elif self.path == "/api/rnd/term_resize":
            session = (body.get("session", "") or "").strip()
            cols = body.get("cols")
            rows = body.get("rows")
            if not session or cols is None or rows is None:
                self._send_json({"ok": False,
                                 "error": "session, cols, rows required"}, 400)
            else:
                out = _termsess.resize(session, cols, rows)
                if out.get("ok"):
                    self._send_json({"ok": True})
                elif out.get("reason") == "unknown-session":
                    self._send_json({"ok": False,
                                     "error": f"unknown session: {session}",
                                     "reason": "unknown-session"}, 404)
                else:
                    self._send_json({"ok": False,
                                     "error": out.get("detail", "bad request"),
                                     "reason": out.get("reason")}, 400)

        elif self.path == "/api/rnd/term_input2":
            # POST-in half of the SSE-out + POST-in fallback transport. Authed by
            # the middleware above.
            session = (body.get("session", "") or "").strip()
            data = body.get("data", "")
            if not session:
                self._send_json({"ok": False, "error": "session required"}, 400)
            else:
                out = _termsess.input(session, data)
                if out.get("ok"):
                    self._send_json({"ok": True})
                else:
                    self._send_json({"ok": False,
                                     "error": f"unknown session: {session}",
                                     "reason": "unknown-session"}, 404)

        # ── R&D validated, cached session summary (Wave 6) ────────────
        elif self.path == "/api/rnd/regenerate_summary":
            # Force re-run + re-cache a session's validated summary. Auth is
            # already enforced by the middleware above (mutating POST). The
            # session's members are summarized again through the runner seam and
            # summary.json + summary.md are overwritten. Clean 404 for an unknown
            # project or session.
            pid = body.get("project_id", "") or body.get("id", "")
            lane = body.get("lane", "")
            session_id = body.get("session_id", "")
            proj = _rnd.get_project(pid)
            if proj is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            elif not lane or not session_id:
                self._send_json({"ok": False,
                                 "error": "lane and session_id required"}, 400)
            else:
                folder = proj.get("folder_path", "")
                session = None
                try:
                    for s in _sessions.list_sessions(folder, pid, lane):
                        if s.get("session_id") == session_id:
                            session = s
                            break
                except Exception:
                    session = None
                if session is None:
                    self._send_json({"ok": False,
                                     "error": f"Unknown session: {session_id}"},
                                    404)
                else:
                    summary = _summarizer.summarize_session(
                        folder, pid, lane, session, force=True)
                    self._send_json({"ok": True, "summary": summary})

        # ── R&D Grass Catchers content feeds (Wave 5) ─────────────────
        elif self.path == "/api/rnd/add_idea":
            # Manually add an idea to a project's Grass Catchers lane (a real
            # Anchor-created idea card, NOT a discovered artifact). Auth is
            # already enforced by the middleware above. Clean 404 for an unknown
            # project; 400 for empty text.
            pid = body.get("project_id", "") or body.get("id", "")
            proj = _rnd.get_project(pid)
            if proj is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                folder = proj.get("folder_path", "")
                try:
                    rec = _eh.add_idea(folder, pid,
                                       body.get("text", ""),
                                       notes=body.get("notes", ""))
                    self._send_json({"ok": True, "effort": rec})
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)

        elif self.path == "/api/rnd/promote_inbox":
            # Promote an EXISTING INBOX.md item into a project's Grass Catchers
            # (copy-by-default: the inbox item is NOT removed). Reuses the
            # existing inbox parser — no new format. Auth enforced above.
            pid = body.get("project_id", "") or body.get("id", "")
            proj = _rnd.get_project(pid)
            if proj is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                folder = proj.get("folder_path", "")
                inbox_items = parse_inbox_from_md(INBOX_MD)
                try:
                    rec = _eh.promote_inbox(folder, pid,
                                            body.get("text", ""),
                                            inbox_items=inbox_items)
                    self._send_json({"ok": True, "effort": rec})
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)

        # 2026-05-12: /api/shutdown removed. The NSSM "anchor" service on
        # gwl-server owns process lifecycle. To restart: run `nssm restart
        # anchor` on gwl-server. The dashboard cannot kill the server.

        else:
            self._send_json({"ok": False, "error": "Unknown endpoint"}, 404)
      except Exception as e:
            _logger.error(f"POST {self.path} failed: {e}\n{traceback.format_exc()}")
            self._send_json({"ok": False, "error": str(e)}, 500)


_server_instance = None
_last_heartbeat = None
_heartbeat_active = False  # Only start monitoring after the first heartbeat arrives


def _heartbeat_watchdog():
    """Background thread: heartbeat monitoring disabled.

    The server now runs until explicitly stopped — via the Stop button in the
    dashboard, Ctrl+C in the terminal, or by killing the Python process. This
    keeps the dashboard instantly available when the user comes back to the
    tab after any amount of time.
    """
    return


class _ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that claims EXCLUSIVE ownership of its port.

    On Windows, ``socket.SO_EXCLUSIVEADDRUSE`` guarantees only ONE process can
    own the listening port — so a duplicate/orphan Anchor process can never
    silently squat 8777 and serve stale code. We deliberately turn OFF
    ``allow_reuse_address`` (HTTPServer enables SO_REUSEADDR by default, which
    is what permits port sharing) and set SO_EXCLUSIVEADDRUSE before binding.

    Used ONLY for the real fixed-port path (see ``make_server``). The ephemeral
    ``port=0`` path used by the tests/health check keeps the default behavior.
    """

    # HTTPServer sets this to 1 (SO_REUSEADDR). Force it off for exclusivity.
    allow_reuse_address = False

    def server_bind(self):
        try:
            self.socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
            )
        except (AttributeError, OSError):
            # SO_EXCLUSIVEADDRUSE is Windows-only; on any platform/socket that
            # rejects it, fall back to the default bind (use_exclusive_bind
            # already gates us to Windows, so this is just belt-and-suspenders).
            pass
        super().server_bind()


def make_server(host="127.0.0.1", port=8777):
    """Construct + bind the threading HTTP server.

    Two distinct bind-failure modes are reconciled here (D4/Wave 2 + Wave 3
    single-instance guard):

    - **Transient** failures (e.g. EADDRNOTAVAIL — a slow-to-come-up Tailscale
      interface not yet assignable) are retried by ``paths.bind_with_retry``.
    - **Address already owned by another Anchor** (EADDRINUSE) is NOT retried —
      ``bind_with_retry`` re-raises it immediately so the caller can exit
      cleanly instead of spinning into a bad state.

    For the real fixed port (non-zero, on Windows) we bind with
    SO_EXCLUSIVEADDRUSE so the OS guarantees a single owner. The ``port=0``
    ephemeral path (tests / health check) keeps the default ThreadingHTTPServer
    behavior so OS-assigned ports are unaffected.
    """
    if _paths.use_exclusive_bind(host, port):
        server_cls = _ExclusiveThreadingHTTPServer
    else:
        server_cls = ThreadingHTTPServer
    return _paths.bind_with_retry(
        lambda: server_cls((host, port), AnchorHandler)
    )


_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def resolve_bind_host():
    """Resolve the server bind host from ``ANCHOR_BIND`` (default loopback).

    Set ``ANCHOR_BIND`` to the Tailscale IP (e.g. ``100.69.215.4``) to expose the
    dashboard over the tailnet. SAFETY (D4): refuse a non-loopback bind unless
    ``ANCHOR_TOKEN`` is configured — otherwise every mutating ``/api/*`` endpoint
    (including the ``bypassPermissions`` build lane) would be reachable
    unauthenticated. Returns the host string; raises ``RuntimeError`` for the
    unsafe combination so ``main`` can refuse to start.
    """
    host = (os.environ.get("ANCHOR_BIND") or "127.0.0.1").strip() or "127.0.0.1"
    if host not in _LOOPBACK_HOSTS and _paths.expected_token() is None:
        raise RuntimeError(
            f"Refusing to bind {host} without ANCHOR_TOKEN set — that would "
            f"expose mutating endpoints (incl. the build lane) unauthenticated. "
            f"Set ANCHOR_TOKEN, or use ANCHOR_BIND=127.0.0.1 for local-only."
        )
    return host


def main():
    global _server_instance, _PROACTIVE_SUMMARY_ENABLED
    # The live server proactively (re)generates the cached project summary on
    # rescan/discovery (Wave 5). Unit tests leave this off (default) so importing
    # the module never spawns a background model job.
    _PROACTIVE_SUMMARY_ENABLED = True
    port = 8777
    no_browser = "--no-browser" in sys.argv
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    try:
        bind_host = resolve_bind_host()
    except RuntimeError as exc:
        print(str(exc))
        try:
            _logger.error(str(exc))
        except Exception:
            pass
        sys.exit(1)

    try:
        server = make_server(bind_host, port)
    except OSError as exc:
        # Single-instance guard: another healthy Anchor already owns this port.
        # Do NOT retry-forever or fight for the port — exit cleanly so the
        # existing server keeps serving and we never become a stale duplicate.
        if _paths.classify_bind_error(exc) == "exit":
            msg = (
                f"Anchor already running on {port} — this instance is exiting "
                f"to avoid a duplicate."
            )
            print(msg)
            try:
                _logger.warning(msg)
            except Exception:
                pass
            sys.exit(0)
        raise
    _server_instance = server
    # Browser/log URL: localhost for a loopback bind, else the bound interface.
    url = (f"http://localhost:{port}" if bind_host in _LOOPBACK_HOSTS
           else f"http://{bind_host}:{port}")

    # Start heartbeat watchdog thread
    watchdog = threading.Thread(target=_heartbeat_watchdog, daemon=True)
    watchdog.start()

    print(f"\n{'='*50}")
    print(f"  Anchor Dashboard running at {url}")
    print(f"  Server runs until you stop it (Stop button / Ctrl+C).")
    print(f"  Press Ctrl+C to stop manually.")
    print(f"  Error log: {ERROR_LOG}")
    print(f"{'='*50}\n")

    _logger.info(f"Server started on {url}")

    if not no_browser:
        # Open browser after a short delay
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _logger.info("Server stopped")
        print("\nAnchor stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
