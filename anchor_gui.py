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
import session_registry as _sessreg
import handoff as _handoff
import preview_server as _preview
import project_bootstrap as _bootstrap
import project_remote as _remote  # v8 Wave 3 — GitHub link + auto-push (seam)
import boneyard as _boneyard  # v10 Wave 6/7 — per-project searchable discard index
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


# ── Vendored Ghost World Labs brand mark static asset (Wave 9) ───────────────
# The GWL brand mark (gwl-m-icon.svg) is vendored on-disk under vendor/brand/
# and served traversal-safe exactly like the KaTeX/xterm/anchor-term assets. It
# backs the home-page lockup and the dashboard favicon. Pure-data static SVG —
# no native dependency, no secret.
BRAND_DIR = ANCHOR_DIR / "vendor" / "brand"
BRAND_URL_PREFIX = "/vendor/brand"
_BRAND_CONTENT_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def brand_asset(rel_path: str):
    """Resolve a ``/vendor/brand/<rel>`` request to (bytes, content_type).

    Path-traversal safe (same containment pattern as :func:`anchor_term_asset`
    / :func:`xterm_asset` / ``report_viewer.katex_asset``): the resolved file
    MUST stay within :data:`BRAND_DIR`. Returns ``None`` for a missing file or
    an escape attempt (so a ``../`` traversal can never read outside the brand
    dir).
    """
    rel = rel_path.lstrip("/")
    target = (BRAND_DIR / rel).resolve()
    try:
        target.relative_to(BRAND_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = _BRAND_CONTENT_TYPES.get(target.suffix.lower(),
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


def _bootstrap_project_best_effort(folder, project_name) -> None:
    """Best-effort v8 bootstrap: starter CLAUDE.md + git-init the folder.

    Wired into the register / open / rescan paths so a non-git project doesn't
    dead-end a session start with ``not-a-git-repo`` and the keystone (Wave 2
    doc persistence) has a repo to commit to. NEVER breaks registration/rescan
    if bootstrap fails (try/except → log + skip). Idempotent (an existing repo /
    CLAUDE.md is a no-op).
    """
    try:
        if not folder:
            return
        f = Path(folder)
        if not f.is_dir():
            return
        res = _bootstrap.bootstrap_project(folder, project_name)
        git = res.get("git", {})
        cm = res.get("claude_md", {})
        if git.get("initialized"):
            log_change(f"R&D: bootstrap git-init {folder}")
        elif not git.get("ok") and git.get("reason") == "git-unavailable":
            log_change(f"R&D: bootstrap skipped git-init (git unavailable) {folder}")
        if cm.get("created"):
            log_change(f"R&D: bootstrap wrote starter CLAUDE.md {folder}")
    except Exception:
        pass  # bootstrap is best-effort; never block registration/open/rescan


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
        # v8 Wave 1: always bootstrap (starter CLAUDE.md + git-init if absent) so
        # a session start never dead-ends on not-a-git-repo. Idempotent + best-
        # effort; honors the explicit git_init above (a no-op if already a repo).
        _bootstrap_project_best_effort(folder, name)
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
        # v8 Wave 1: bootstrap an existing folder on register — starter CLAUDE.md
        # + git-init if it isn't a repo — so a research/build session start on it
        # no longer returns not-a-git-repo. Best-effort + idempotent; skipped for
        # a missing path (nothing to bootstrap).
        if exists:
            _bootstrap_project_best_effort(folder, name)
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

    # v8 Wave 1: bootstrap on open/rescan (this is the rescan path AND the open
    # path via GET /project/<id>) — starter CLAUDE.md + git-init if the folder
    # isn't a repo. Best-effort + idempotent; heals a non-git project so a later
    # session start succeeds.
    _bootstrap_project_best_effort(folder, (proj or {}).get("name", ""))

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


def _resolve_finished_session(folder, project_id, lane, session_id):
    """Resolve the durable SESSION dict for a finished managed session (v8 Wave 5).

    A managed terminal session (the killed one) keys off a bare registry id, but
    the documents it PRODUCED were persisted (Wave 2 ``persist_session_docs``) as
    DISCOVERED efforts that group — in ``sessions.list_sessions`` — under their
    common parent directory, NOT under the bare managed id. So a kill's durable
    summary/detail must TIE the managed session to its produced docs explicitly:

      1. Prefer an exact ``sessions.list_sessions`` match on the managed id (a RUN
         session adopted under the same id, e.g. a discover→adopt flow).
      2. Else SYNTHESIZE a session dict from the lane efforts tagged with this
         managed ``session_id`` (``effort_history.efforts_for_session_id``) — the
         persisted produced docs. This is the no-loss tie: the killed session now
         resolves to a lane SESSION carrying {its id, its produced docs}, so the
         summarizer seeds skill/prompts/actions off the REAL docs (not empty).

    Returns a session dict (with ``member_files``) when the managed session has
    resolvable produced docs, else ``None`` (honest — nothing was produced).
    Never raises.
    """
    try:
        for s in _sessions.list_sessions(folder, project_id, lane):
            if s.get("session_id") == session_id:
                return s
    except Exception:
        pass
    try:
        members = _eh.efforts_for_session_id(folder, project_id, lane,
                                             session_id)
    except Exception:
        members = []
    if not members:
        return None
    # Synthesize a session dict keyed to the MANAGED id so its cached summary
    # (and the detail view, which fetches by that id) carries these exact docs.
    discovered = all(_eh.is_discovered(m) for m in members)
    try:
        ts = max(float(m.get("created_at", 0.0) or 0.0) for m in members)
    except (TypeError, ValueError):
        ts = 0.0
    skill = ""
    title = ""
    for m in members:
        if not skill and m.get("skill"):
            skill = m["skill"]
        if not title and (m.get("title") or "").strip():
            title = (m.get("title") or "").strip()
    return {
        "session_id": session_id,
        "lane": _eh._resolve_subdir(lane),
        "skill": skill,
        "timestamp": ts,
        "title": title,
        "member_files": members,
        "provenance": "imported" if discovered else "run",
        "summary_ref": None,
    }


def _trigger_session_summary_on_finish(project_id, lane, session_id):
    """Best-effort: schedule a BACKGROUND session-summary for a session that just
    reached a terminal state (v7 Wave 2 — kill / finish→build / reconcile-dead).

    Resolves the project folder + the effort-history ``session`` dict (the shape
    ``_trigger_session_summary`` needs) from ``session_id`` and kicks off the
    existing background generator. NON-BLOCKING and IDEMPOTENT:

      - returns immediately (the generation runs on a daemon thread);
      - skips when the session already has a CACHED summary (so a second finish /
        a repeated reconcile poll never re-runs the model);
      - a failed generation never poisons the cache (the summarizer surfaces
        ``error`` WITHOUT writing, per FIX 2).

    No-op unless ``_PROACTIVE_SUMMARY_ENABLED`` (the live server enables it; tests
    opt in). Never raises — any resolution failure is swallowed so it can never
    delay or break the finish (kill / finish→build / reconcile) response.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return
    try:
        if not project_id or not lane or not session_id:
            return
        proj = _rnd.get_project(project_id)
        if proj is None:
            return
        folder = proj.get("folder_path", "")
        if not folder:
            return
        store_lane = _eh._resolve_subdir(lane)
        # Idempotent: a session that already has a cache is left alone (the
        # summarizer would no-op it too, but skip the thread spin-up entirely).
        try:
            if _summarizer.load_cached(folder, project_id, store_lane,
                                       session_id) is not None:
                return
        except Exception:
            pass
        # v8 Wave 5 — TIE the finished managed session to the docs it PRODUCED.
        # The Wave-2 keystone persists those docs tagged with this session_id, so
        # the durable summary keyed to the managed id seeds skill/prompts/actions
        # off the REAL produced docs (no-loss), not an empty record.
        session = _resolve_finished_session(folder, project_id, lane, session_id)
        if session is None:
            # The session produced no resolvable docs (e.g. nothing was written)
            # — seed a minimal record off the registry so the summarizer still has
            # a session_id/title to key the (honest, empty) cache to.
            session = {"session_id": session_id}
        _trigger_session_summary(folder, project_id, lane, session)
    except Exception:
        pass


def _auto_push_on_finish(project_id):
    """Best-effort: auto-push the project's repo when a session reaches a terminal
    state (v8 Wave 3 — wired into the kill/finish path AFTER the produced docs are
    persisted/committed by Wave 2's capture-before-reap).

    Delegates to :func:`project_remote.auto_push_if_opted`, which pushes ONLY when
    the project is BOTH linked to a remote AND opted-in to auto-push. A non-linked
    or non-opted project never pushes. NON-BLOCKING + never raises — any failure is
    swallowed so it can never delay or break the finish response. In tests the
    configured ``origin`` is a LOCAL BARE repo (``file://``) so there is NO network.
    """
    try:
        if not project_id:
            return
        _remote.auto_push_if_opted(project_id)
    except Exception:
        pass


#: Max chars of prior-session context folded into a continue-live seed (bounded).
_MAX_CONTINUE_SEED_CHARS = 4000


def _build_continue_seed(folder_path, project_id, lane, source_session_id):
    """Build the seed_context text for "Continue in a live session" (v5 Wave 2).

    READ-ONLY: resolves the prior (done/historical) session and assembles a
    compact context string from its CACHED summary, preferring (in order):

      1. the cached summary's rendered markdown (``markdown``), else
      2. a deterministic digest of the cached summary's structured fields
         (skill · what-was-asked · north-star · prompts · files produced), else
      3. the live session record's intent (``what_was_asked`` / ``title``).

    NEVER mutates the original session/summary (Risk R2) — every access is a read.
    Returns a bounded string (or ``""`` when nothing resolves, in which case the
    new session is started bare-seeded with just the lane skill). Stdlib only;
    never raises.
    """
    store_lane = _eh._resolve_subdir(lane)
    cached = None
    try:
        cached = _summarizer.load_cached(folder_path, project_id, store_lane,
                                         source_session_id)
    except Exception:
        cached = None

    parts = ["This is a continuation of an earlier session in the "
             + str(lane) + " lane. Here is its summary so you can pick up the "
             "work:"]
    if isinstance(cached, dict):
        md = (cached.get("markdown") or "").strip()
        if md:
            parts.append(md)
        else:
            skill = (cached.get("skill") or "").strip()
            if skill:
                parts.append("Skill: " + skill)
            asked = (cached.get("what_was_asked") or "").strip()
            if asked:
                parts.append("Originally asked: " + asked)
            ns = (cached.get("north_star") or "").strip()
            if ns:
                parts.append("North Star: " + ns)
            prompts = cached.get("prompts") or []
            if prompts:
                parts.append("Prompts asked: "
                             + " | ".join(str(p) for p in prompts))
            actions = cached.get("actions") or []
            labels = []
            for a in actions:
                if isinstance(a, dict):
                    lbl = (a.get("label") or a.get("rel")
                           or a.get("job_id") or "").strip()
                else:
                    lbl = str(a).strip()
                if lbl:
                    labels.append(lbl)
            if labels:
                parts.append("Files produced: " + ", ".join(labels))
    else:
        # No cached summary — fall back to the live session record's intent.
        session = None
        try:
            for s in _sessions.list_sessions(folder_path, project_id, lane):
                if s.get("session_id") == source_session_id:
                    session = s
                    break
        except Exception:
            session = None
        if session:
            asked = (session.get("title") or "").strip()
            if asked:
                parts.append("Originally: " + asked)

    text = "\n\n".join(p for p in parts if p and p.strip()).strip()
    # If we never resolved any real prior context (only the lead-in line), return
    # empty so the new session is started bare-seeded (just the lane skill).
    if len(parts) <= 1:
        return ""
    return text[:_MAX_CONTINUE_SEED_CHARS]


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
                    # v7 Wave 1: normalize the cached summary to a clean, capped
                    # plain-text short line for the row (strip markdown/glyphs).
                    return _summarizer.short_summary_text(txt), "summary"
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


def _project_status_dot(entry: dict, status_line: dict, registry_running: int = 0) -> str:
    """Pick the row's status-dot class (kept simple + documented, Wave 5).

    Mapping: green if ANY lane has a running session; for inactive projects
    (archived/future/retired) a dimmed grey; otherwise a neutral idle grey. The
    dot is purely advisory (the per-lane mini-counts carry the detail).

    v10.1 FIX 3 — ``status_line.running`` counts ONLY effort-history/job_runner
    sessions; a live MANAGED terminal/ConPTY session registers in
    ``session_registry`` as RUNNING with NO job_runner record, so it left the dot
    grey. ``registry_running`` (the count from the SAME registry read the
    activity line already does, ZERO new rnd_jobs/ scans) greens the dot when any
    managed session is running. (A running general/grass managed session greens
    the dot too — a defensible "is anything running" signal.)"""
    state = entry.get("state", "active")
    if state in ("archived", "future", "retired"):
        return "rnd-dot-idle"
    try:
        if int(registry_running or 0) > 0:
            return "rnd-dot-running"
        if any(int((status_line.get(l) or {}).get("running", 0) or 0) > 0
               for l in status_line):
            return "rnd-dot-running"
    except Exception:
        pass
    return "rnd-dot-idle"


# Map a registry session status → the locked status-light color word, mirroring
# `_session_light_class` / the JS `_statusColor` (single source of truth for the
# four colors). Used by the home-row "what's happening" line (Wave 7).
_SESSION_STATUS_COLOR = {
    _sessreg.STATUS_RUNNING: "green",
    _sessreg.STATUS_NEEDS_ATTENTION: "amber",
    _sessreg.STATUS_DONE: "amber",
    _sessreg.STATUS_FAILED: "red",
    _sessreg.STATUS_IDLE: "grey",
}


def _project_activity_reflection(pid_raw: str) -> dict:
    """Return a CACHE/REGISTRY-only activity reflection for a home-dashboard row
    (v6 Wave 7). Reads ONLY ``session_registry`` (no model call, no PTY) so it is
    safe on the render path.

    Returns ``{running: int, latest: {lane, label, status, color, age} | None}``:
    - ``running`` — how many of the project's managed sessions are RUNNING;
    - ``latest`` — the newest session (by ``created_at``) with a human label, its
      lane, status, status-color word, and a compact age — for the "latest:
      planning · Crucible pipeline plan (running)" line. ``None`` when the
      project has no managed sessions at all (honest — never fabricated).
    Never raises (a registry hiccup degrades to ``{running:0, latest:None}``).
    """
    out = {"running": 0, "latest": None}
    try:
        sessions = _sessreg.list_sessions(project_id=pid_raw)
    except Exception:
        return out
    if not sessions:
        return out
    out["running"] = sum(1 for s in sessions
                         if s.get("status") == _sessreg.STATUS_RUNNING)
    # list_sessions is already newest-first by created_at, so [0] is the newest.
    newest = sessions[0]
    lane = (newest.get("lane") or "").strip()
    status = (newest.get("status") or _sessreg.STATUS_IDLE).strip()
    # A friendly title: the session's own label if it set one, else the lane name.
    label = (newest.get("label") or "").strip() or (lane.capitalize() or "session")
    out["latest"] = {
        "lane": lane,
        "label": label,
        "status": status,
        "color": _SESSION_STATUS_COLOR.get(status, "grey"),
        "age": _fmt_age(newest.get("created_at")),
    }
    return out


def _render_activity_reflection_html(refl: dict) -> str:
    """Render the per-row activity-reflection block (v6 Wave 7): a running
    indicator/count + a "what's happening" latest-session line. Honest empty
    state ("idle — no sessions") when the project has none. Pure formatting of
    the cache/registry-sourced ``refl`` dict; never runs the model."""
    running = int(refl.get("running", 0) or 0)
    latest = refl.get("latest")
    parts = []
    if running > 0:
        # A live indicator (the pulsing dot CSS) + the count.
        parts.append(
            f'<span class="rnd-act-running" title="live sessions">'
            f'<span class="rnd-act-pulse" aria-hidden="true"></span>'
            f'running: {running}</span>'
        )
    if latest:
        lane = latest.get("lane") or ""
        lane_lbl = html_lib.escape(lane.capitalize() or "session")
        title = html_lib.escape(latest.get("label") or "")
        status = html_lib.escape(latest.get("status") or "")
        color = html_lib.escape(latest.get("color") or "grey")
        age = html_lib.escape(latest.get("age") or "")
        age_txt = f' · {age}' if age else ""
        parts.append(
            f'<span class="rnd-act-latest">latest: '
            f'<span class="rnd-act-lane">{lane_lbl}</span> · '
            f'<span class="rnd-act-title">{title}</span> '
            f'<span class="rnd-act-status rnd-act-{color}">'
            f'({status})</span>{age_txt}</span>'
        )
    if not parts:
        # Honest placeholder — never fabricate activity.
        parts.append('<span class="rnd-act-latest rnd-dim">'
                     'idle — no sessions yet</span>')
    return '<div class="rnd-row-activity">' + "".join(parts) + "</div>"


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

    # v6 Wave 7 — timely activity reflection (running count + newest-session
    # "what's happening" line), sourced from the session registry ONLY (no model
    # call on the render path). Honest "idle — no sessions yet" placeholder when
    # the project has none.
    # v10.1 FIX 3 — capture the reflection ONCE (it carries the registry running
    # count) so the status dot can reuse it (the SAME single registry read; ZERO
    # new rnd_jobs/ scans, GET / perf invariant holds).
    refl = _project_activity_reflection(pid_raw)
    activity_block = _render_activity_reflection_html(refl)

    # Per-lane mini-counts (compact form of the status line) + status dot.
    status = render_status_line_html(pid_raw)
    try:
        sline = _rnd.status_line(pid_raw)
    except Exception:
        sline = {}
    # v10.1 FIX 3 — pass the registry running count so a live MANAGED terminal
    # session (no job_runner record → status_line.running == 0) still greens the
    # home-row dot.
    dot_cls = _project_status_dot(
        entry, sline, registry_running=int(refl.get("running", 0) or 0))

    # Per-row cost/tokens/time rollup (v4 Wave 8, MASTER-PLAN cockpit dashboard
    # rows). Reuses the Wave-3 `effort_history.project_effort_rollup` (RUN-session
    # totals only — imported/discovered contribute 0, never fabricated) and the
    # shared `_fmt_rollup_line` formatter. Rendered at LIFETIME by default; the
    # R&D view's single global lifetime/30-day toggle (rndRowsRollupWindow) swaps
    # every row's text in place via the read-only `/api/rnd/project_rollup`
    # endpoint, so a no-JS view still shows lifetime totals. Never raises.
    try:
        roll = _eh.project_effort_rollup(pid_raw, window=_eh.WINDOW_LIFETIME)
        roll_txt = html_lib.escape(_fmt_rollup_line(roll))
    except Exception:
        roll_txt = ""
    rollup_block = (
        f'<span class="rnd-row-roll" data-pid="{pid}" data-window="lifetime" '
        f'title="Cost / tokens / time across run sessions">{roll_txt}</span>'
    )

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
    # v9 Wave 3 — drag-to-group: the row is draggable and carries its current
    # group so the drag handlers can call /api/rnd/set_group (dashboard-only; NO
    # disk move). The ⋮⋮ grip is the drag affordance. The on-disk folder path is
    # deliberately NOT stamped on the row (it lives on the project-window header;
    # the v8 no-path-on-dashboard invariant holds — the Wave-4 move dialog reads
    # the path server-side, not from the row).
    group = entry.get("group", "") or ""
    group_attr = html_lib.escape(group, quote=True)
    return (
        f'<div class="rnd-row" data-project-id="{pid}" data-notes="{notes_attr}" '
        f'data-blurb="{blurb_attr}" data-group="{group_attr}" '
        f'draggable="true" tabindex="0" role="button" '
        f'onclick="openProjectWindow(\'{pid}\')" '
        f'title="Open {name}">'
        f'<span class="rnd-grip" aria-hidden="true" '
        f'title="Drag into a folder">&#8942;&#8942;</span>'
        f'<span class="rnd-dot {dot_cls}" aria-hidden="true"></span>'
        f'<span class="rnd-name">{name}</span>'
        f'<span class="rnd-badge rnd-p{pr}">P{pr}</span>'
        f'<span class="rnd-badge rnd-state-{state}">{state}</span>'
        f'{summary_block}'
        f'{activity_block}'
        f'<span class="rnd-row-counts">{status}</span>'
        f'{rollup_block}'
        f'{kebab}'
        f'</div>'
    )


def _render_folder_groups(groups: dict) -> str:
    """Render a FLAT one-line ROW list for the dashboard (v4 Wave 8 — archive view).

    The per-folder directory header is GONE on the FLAT path; projects render as
    a single flat list of thin rows. Still used by the Archive view, which has no
    group concept. The ACTIVE home dashboard now uses
    :func:`_render_group_folders` (v9 Wave 3 collapsible folders) instead.
    """
    rows = []
    for folder in sorted(groups):
        rows.extend(render_project_tile_html(e) for e in groups[folder])
    return ('<div class="rnd-projects">'
            '<div class="rnd-folder-rows">' + "".join(rows) + '</div>'
            '</div>')


def _group_folder_path(entries: list) -> str:
    """If every project in a group shares one on-disk parent/path, return it.

    The mockup shows a folder's real on-disk path in the header only when it is
    uniform across the group's projects. Returns "" when the group is empty or
    its projects live in different folders (heterogeneous → no path shown).
    """
    paths = {(e.get("folder_path") or "") for e in entries if e.get("folder_path")}
    if len(paths) == 1:
        return next(iter(paths))
    return ""


def _render_group_folders(groups: dict) -> str:
    """Render the home dashboard's COLLAPSIBLE FOLDERS (v9 Wave 3).

    ``groups`` is keyed by GROUP NAME (from ``rnd_registry.group_by_group``) →
    list of project entries; the empty-group bucket is keyed ``Ungrouped`` and
    always renders last (it is the drop target for "remove from a folder").

    Each folder is a header (▸/▾ twisty · name · count · uniform on-disk path)
    over a body of the group's thin project rows. Folders are a drop target for
    drag-to-group; collapse state is persisted client-side (localStorage) by the
    home dashboard JS (``rndFolderInit``). Organization ONLY — no disk move.
    """
    ungrouped_label = getattr(_rnd, "UNGROUPED_LABEL", "Ungrouped")
    # Order: named groups as given (group_by_group already sorts them), with
    # Ungrouped last regardless of dict order.
    names = [g for g in groups if g != ungrouped_label]
    if ungrouped_label in groups:
        names.append(ungrouped_label)

    folders = []
    for gname in names:
        entries = groups.get(gname, [])
        rows = "".join(render_project_tile_html(e) for e in entries)
        name_esc = html_lib.escape(gname)
        name_attr = html_lib.escape(gname, quote=True)
        is_ungrouped = (gname == ungrouped_label)
        # The Ungrouped bucket is a catch-all, not a real on-disk folder → never
        # stamp a path on it (even if its members happen to share a dir).
        fpath = "" if is_ungrouped else _group_folder_path(entries)
        path_block = (f'<span class="rnd-fpath">{html_lib.escape(fpath)}</span>'
                      if fpath else '')
        drop_hint = ('<span class="rnd-fdrop-hint">drop here to remove '
                     'from a folder</span>' if is_ungrouped else '')
        folders.append(
            f'<div class="rnd-folder" data-group="{name_attr}" '
            f'data-ungrouped="{"1" if is_ungrouped else "0"}">'
            f'<div class="rnd-folder-head" '
            f'onclick="rndToggleFolder(this)" role="button" tabindex="0" '
            f'title="Collapse / expand folder">'
            f'<span class="rnd-tw" aria-hidden="true">▾</span>'
            f'<span class="rnd-fname">{name_esc}</span>'
            f'<span class="rnd-fcount">({len(entries)})</span>'
            f'{path_block}'
            f'<span class="rnd-fsp"></span>'
            f'{drop_hint}'
            f'</div>'
            f'<div class="rnd-folder-body">{rows}</div>'
            f'</div>'
        )
    return ('<div class="rnd-projects">'
            '<div class="rnd-folder-list" id="rndFolderList">'
            + "".join(folders) +
            '</div></div>')


def render_projects_view_html(include_archived: bool = False,
                              include_future: bool = False,
                              include_retired: bool = False) -> str:
    """Render the ACTIVE folder-grouped projects view (collapsible folder → tiles).

    Defaults to active-only; inactive projects (archived/future/retired) live on
    the separate Archive view (:func:`render_archive_view_html`).
    """
    groups = _rnd.group_by_group(include_archived=include_archived,
                                 include_future=include_future,
                                 include_retired=include_retired)
    # group_by_group always returns the Ungrouped bucket; "empty" = only an
    # empty Ungrouped bucket and no named (extra) groups.
    ungrouped_label = getattr(_rnd, "UNGROUPED_LABEL", "Ungrouped")
    has_any = any(groups.get(g) for g in groups)
    extra_groups = sorted(g for g in groups if g != ungrouped_label)
    if not has_any and not extra_groups:
        return ('<div class="rnd-projects"><p class="rnd-empty">'
                'No active R&D projects. Use "+ New Project" to add one.</p></div>')
    return (_render_folder_toolbar()
            + _render_rows_rollup_toggle()
            + _render_group_folders(groups))


def _render_folder_toolbar() -> str:
    """The "+ New folder" control row above the collapsible folders (v9 W3).

    "+ New folder" prompts for a name and creates an empty group; you then drag
    a project row into it (NO disk move). Purely additive — a no-JS view still
    renders the existing folders below."""
    return (
        '<div class="rnd-folder-toolbar">'
        '<button class="rnd-newfolder-btn" type="button" '
        'onclick="rndNewFolder()" title="Create a new project folder (group)">'
        '+ New folder</button>'
        '<span class="rnd-folder-hint">drag any project row (⋮⋮) '
        'into a folder header to group it</span>'
        '</div>'
    )


def _render_rows_rollup_toggle() -> str:
    """A single GLOBAL lifetime/30-day toggle for the R&D rows' cost rollups
    (v4 Wave 8). Clicking re-fetches every row's read-only
    ``/api/rnd/project_rollup?window=...`` and swaps the text in place
    (``rndRowsRollupWindow`` in the JS). Lifetime is the default; the toggle is
    purely additive (a no-JS view still shows lifetime totals on each row)."""
    return (
        '<div class="rnd-rows-rolltog" role="group" '
        'aria-label="project rollup window">'
        '<span class="rnd-rows-rolltog-label">Σ&nbsp;effort:</span>'
        '<b class="on" data-window="lifetime" '
        'onclick="rndRowsRollupWindow(\'lifetime\',this)">lifetime</b>'
        '<b data-window="30d" '
        'onclick="rndRowsRollupWindow(\'30d\',this)">30d</b>'
        '</div>'
    )


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


# v4 Wave 4 — Paradigm-2 lane-tile status light.
#
# Map a session's representative effort view → the LOCKED status-light bucket
# (session_registry status constants → colors, MASTER-PLAN §E):
#   running                       → green  (live PTY / job producing output)
#   needs-attention / done        → amber  (come look — waiting on you or finished)
#   failed / cancelled / interrupted → red
#   idle / unknown / discovered   → grey
# This mirrors the JS ``_statusColor`` (which maps the registry status strings):
# a single source of truth for the four colors, applied here at the lane-tile
# render and there at the live session-bar / panel render.
def _session_light_class(ev):
    """Return the lane-tile status-light color class ('green'|'amber'|'red'|
    'grey') for a session's representative effort view ``ev``."""
    if not ev:
        return "grey"
    if ev.get("needs_input"):
        return "amber"          # needs-attention (awaiting input)
    if ev.get("is_live"):
        return "green"          # running
    status = (ev.get("status") or "").strip()
    if ev.get("is_done") or status == _jr.STATUS_DONE:
        return "amber"          # done → amber (finished; awaiting your review)
    if status in (_jr.STATUS_FAILED, _jr.STATUS_INTERRUPTED, _jr.STATUS_CANCELLED):
        return "red"
    return "grey"               # idle / discovered / unknown


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
    # Gather each lane's efforts ONCE, then load ONLY the job records those
    # efforts actually reference (targeted load_record per job_id) — instead of
    # scanning the entire global rnd_jobs/ dir via list_records() for every
    # project-lane. That full scan made the dashboard O(projects x lanes x
    # all-jobs); once rnd_jobs/ grew to ~1k records it pushed GET / past the
    # health check's 5s timeout (the red banner). The lookup only ever needs the
    # records for THIS project's efforts, so load exactly those.
    efforts_by_lane = {}
    needed_jids = set()
    for trio_lane, _subdir, _label, _glyph, _addlabel in _KANBAN_COLUMNS:
        try:
            lane_efforts = _eh.list_efforts(folder_path, project_id, trio_lane)
        except Exception:
            lane_efforts = []
        efforts_by_lane[trio_lane] = lane_efforts
        for _e in lane_efforts:
            _jid = _e.get("job_id")
            if _jid:
                needed_jids.add(_jid)
    jobs_by_id = {}
    for _jid in needed_jids:
        try:
            _rec = _jr.load_record(_jid)
        except Exception:
            _rec = None
        if _rec:
            jobs_by_id[_jid] = _rec
    out = {}
    for trio_lane, _subdir, _label, _glyph, _addlabel in _KANBAN_COLUMNS:
        efforts = efforts_by_lane.get(trio_lane, [])
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


# v7 Wave 3 — bridge LIVE managed sessions (session_registry) into the board.
#
# The board's trio columns are keyed by the trio-lane values in _KANBAN_COLUMNS
# (research / plan / build / deliverables / grass). A registry record's ``lane``
# may use the store form (``planning``) or the trio form (``plan``); both map to
# the ``plan`` board column. ``general`` (Wave 4) + ``grass`` are NOT trio board
# columns and are EXCLUDED here.
_REGISTRY_LANE_TO_COLUMN = {
    "research": "research",
    "plan": "plan",
    "planning": "plan",
    "build": "build",
    "deliverables": "deliverables",
}

#: session_registry status → the locked light-color bucket (mirrors
#: :func:`_session_light_class`; running=green, needs-attention=amber,
#: done=amber, failed=red, idle/unknown=grey).
_REG_STATUS_LIGHT = {
    _sessreg.STATUS_RUNNING: "green",
    _sessreg.STATUS_NEEDS_ATTENTION: "amber",
    _sessreg.STATUS_DONE: "amber",
    _sessreg.STATUS_FAILED: "red",
    _sessreg.STATUS_IDLE: "grey",
}


def _registry_session_view(rec):
    """Build a single board ``effort_view``-shaped dict from a LIVE managed
    session record (``session_registry``), so a started session can render as a
    lane tile BEFORE it has any effort-history rows (v7 Wave 3).

    SAFE: reads only the projection-safe fields (session_id, lane, status,
    label, created_at) — NEVER ``worktree_path`` / ``branch`` (those must not
    leak into the page). The shape carries the same keys ``_render_lane_tile`` /
    ``_session_state_text`` / ``_session_light_class`` read off a representative
    effort view, plus the registry ``status`` and a ``from_registry`` marker so
    the merge can keep the live status when deduping against an effort view.
    """
    status = (rec.get("status") or "").strip()
    is_live = status == _sessreg.STATUS_RUNNING
    needs_input = status == _sessreg.STATUS_NEEDS_ATTENTION
    is_done = status in _sessreg.TERMINAL_STATUSES
    if status == _sessreg.STATUS_RUNNING:
        pill_cls, pill_lbl = "run", "running"
    elif status == _sessreg.STATUS_NEEDS_ATTENTION:
        pill_cls, pill_lbl = "input", "needs input"
    elif status == _sessreg.STATUS_DONE:
        pill_cls, pill_lbl = "done", "done"
    elif status == _sessreg.STATUS_FAILED:
        pill_cls, pill_lbl = "fail", "failed"
    else:
        pill_cls, pill_lbl = "", (status or "idle")
    label = (rec.get("label") or "").strip()
    return {
        "job_id": "",
        "trio_lane": _REGISTRY_LANE_TO_COLUMN.get(
            (rec.get("lane") or "").strip(), ""),
        "ver": "",
        "status": status,
        "pill_cls": pill_cls,
        "pill_lbl": pill_lbl,
        "is_live": is_live,
        "needs_input": needs_input,
        "is_done": is_done,
        "age": _fmt_age(rec.get("created_at")),
        "skill": "",
        "sub": label,
        "cost_usd": 0.0,
        "discovered": False,
        "artifact_path": "",
        "title": label,
        "kind": "",
        # v10 Wave 4: grass→project lineage stamp. Just an idea id — SAFE (never
        # worktree_path/branch). Lets a board tile show the "from grass: <idea>"
        # back-link chip when this session's chain traces back to a grass idea.
        "grass_origin": (rec.get("grass_origin") or ""),
        # v7 Wave 3 merge markers (consumed only by _gather_project_sessions):
        "from_registry": True,
        "_reg_session_id": rec.get("session_id") or "",
        "_reg_created_at": rec.get("created_at") or 0.0,
        "_reg_status": status,
        "_reg_light": _REG_STATUS_LIGHT.get(status, "grey"),
    }


def _strip_session_prefix(sid: str) -> str:
    """Strip the effort session_id namespacing prefix (``run::`` / ``loose::`` /
    ``discovered::`` …) to recover the bare id, for cross-form dedupe with a
    managed registry session id (v7 Wave 3)."""
    s = str(sid or "")
    idx = s.find("::")
    return s[idx + 2:] if idx >= 0 else s


def _merge_registry_sessions(session_views, trio_lane, reg_by_column):
    """Merge the LIVE managed sessions for ``trio_lane`` into the effort-derived
    ``session_views`` (v7 Wave 3), deduped by session_id and ordered newest-first.

    - A registry session whose id ALREADY appears as an effort session keeps the
      richer effort view but adopts the LIVE registry status (so a just-started
      run shows running even before its effort rows land).
    - A registry session with no effort counterpart becomes a synthetic
      single-member session_view.
    - Ordered newest-first by created_at (registry ``created_at`` for synthetic
      rows; the effort rep's already-newest order is preserved by sort-stability).

    Returns the merged, newest-first list. ``general`` / ``grass`` never reach
    here (not in ``_REGISTRY_LANE_TO_COLUMN`` values for the trio columns).
    """
    reg_rows = reg_by_column.get(trio_lane, [])
    if not reg_rows:
        return session_views
    # Index existing effort session_views by id for dedupe + live-status adoption.
    # An effort session derived from a run job is keyed ``run::<job_id>`` (and a
    # defensive loose view ``loose::<job_id>``), while a managed registry session
    # is keyed by the BARE session id — which equals that job_id when the session
    # was adopted (terminal_session reuses the pty/session id as the job id). So
    # we index BOTH the full key AND the prefix-stripped tail to dedupe across
    # those two forms.
    by_sid = {}
    for sv in session_views:
        sid = sv.get("session_id") or ""
        by_sid.setdefault(sid, sv)
        tail = _strip_session_prefix(sid)
        if tail and tail != sid:
            by_sid.setdefault(tail, sv)
    merged = list(session_views)
    # Stamp created_at onto each existing view for the newest-first sort (the
    # rep member carries the effort age, not an epoch; fall back to 0 → sorts
    # after timestamped registry rows of equal recency, which is fine).
    order = {id(sv): i for i, sv in enumerate(merged)}
    sort_ts = {id(sv): _sv_created_at(sv) for sv in merged}
    for rv in reg_rows:
        sid = rv.get("_reg_session_id") or ""
        existing = by_sid.get(sid)
        if existing is not None:
            # DEDUPE: keep the richer effort view, adopt the live registry status
            # onto its representative member so the tile light/state is current.
            rep = (existing.get("members") or [None])[0]
            if isinstance(rep, dict):
                rep["is_live"] = rv["is_live"]
                rep["needs_input"] = rv["needs_input"]
                rep["is_done"] = rep.get("is_done") or rv["is_done"]
                if rv["status"]:
                    rep["status"] = rv["status"]
                rep["pill_cls"] = rv["pill_cls"]
                rep["pill_lbl"] = rv["pill_lbl"]
            sort_ts[id(existing)] = max(
                sort_ts.get(id(existing), 0.0), rv.get("_reg_created_at") or 0.0)
            continue
        sv = {"session_id": sid, "members": [rv]}
        merged.append(sv)
        by_sid[sid] = sv
        order[id(sv)] = len(order)
        sort_ts[id(sv)] = rv.get("_reg_created_at") or 0.0
    # Newest-first by created_at; stable on ties (preserves original ordering).
    merged.sort(key=lambda sv: (-(sort_ts.get(id(sv), 0.0)), order.get(id(sv), 0)))
    return merged


def _sv_created_at(sv):
    """Best-effort epoch created_at for a session_view (for the merge sort).

    A registry-sourced view carries ``_reg_created_at``; an effort view does not
    carry an epoch on the rep (it carries a compact age), so it returns 0.0 and
    relies on the stable secondary key to preserve effort order."""
    rep = (sv.get("members") or [None])[0]
    if isinstance(rep, dict) and rep.get("_reg_created_at"):
        return float(rep.get("_reg_created_at") or 0.0)
    return 0.0


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
    # v7 Wave 3 — pull the project's LIVE managed sessions ONCE and bucket them
    # by board column (research/plan/build/deliverables). ``general``/``grass``
    # are excluded (not in _REGISTRY_LANE_TO_COLUMN). Registry-only (no model
    # call); never leaks worktree_path/branch (see _registry_session_view).
    reg_by_column = {}
    try:
        for rec in _sessreg.list_sessions(project_id=project_id):
            # v8 Wave 6: a CONTAINED grass-workbench develop session keeps its
            # research/plan lane (so its trio skill seeds) but must NOT render as
            # a board tile — it lives only in the workbench pane. Its label marker
            # excludes it here (and the JS never adds it to MANAGED/the top strip).
            if _eh.is_grass_dev_label(rec.get("label")):
                continue
            col = _REGISTRY_LANE_TO_COLUMN.get((rec.get("lane") or "").strip())
            if not col:
                continue
            reg_by_column.setdefault(col, []).append(_registry_session_view(rec))
    except Exception:
        reg_by_column = {}
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
        # v7 Wave 3 — bridge in the LIVE managed sessions for this column,
        # deduped by session_id + ordered newest-first (the most-recent becomes
        # the prominent tile, older ones the expander).
        session_views = _merge_registry_sessions(
            session_views, trio_lane, reg_by_column)
        out[trio_lane] = session_views
    # Build→Planning tie: a BUILD session whose source directory equals a PLANNING
    # session's source directory (the Foreman EXECUTION-LOG lives under
    # planning/<version>/ next to the plan docs) is the SAME trio run's build
    # stage — tie them so the build tile can link back to the plan it executed.
    # Honest: only an unambiguous (single-planning-session-per-dir) match links;
    # no match → no link (nothing fabricated). Discovered/effort sessions only —
    # live managed sessions carry their own v6 parent/chain lineage.
    _attach_build_planning_tie(out)
    return out


def _sv_source_dir(sv) -> str:
    """The folder-relative POSIX source directory of a discovered session view,
    from its representative member's ``artifact_path`` (``""`` if none/loose)."""
    for m in sv.get("members", []) or []:
        ap = (m.get("artifact_path") or "").strip().replace("\\", "/")
        if ap and "/" in ap:
            return ap.rsplit("/", 1)[0]
    return ""


def _attach_build_planning_tie(out) -> None:
    """Attach ``linked_planning`` = ``{"session_id", "label"}`` to each BUILD
    session that shares a source directory with exactly one PLANNING session.

    Mutates ``out`` in place. The planning ``session_id`` is the real
    (un-qualified) ``dir::…`` id whose tile lives in the Planning column, so a
    chip/breadcrumb click resolves to that tile via ``openPanel``. ``label`` is
    the version dir basename (e.g. ``rnd-v4``).
    """
    planning_by_dir = {}        # source_dir -> session_id (None marks ambiguous)
    # NB: the planning column's key in ``out`` is the trio-lane "plan" (its
    # store-lane is "planning"); see _KANBAN_COLUMNS.
    for sv in out.get("plan", []) or []:
        d = _sv_source_dir(sv)
        if not d:
            continue
        sid = sv.get("session_id") or ""
        if not sid:
            continue
        planning_by_dir[d] = None if d in planning_by_dir else sid
    for sv in out.get("build", []) or []:
        d = _sv_source_dir(sv)
        if not d:
            continue
        sid = planning_by_dir.get(d)
        if not sid:
            continue   # no match, or ambiguous (>1 planning session in that dir)
        label = d.rsplit("/", 1)[-1] or d
        sv["linked_planning"] = {"session_id": sid, "label": label}


def _idea_source_label(eff) -> str:
    """Human source chip for a grass idea: 'from inbox' | 'discovered' | 'manual'.

    Reads the effort record (NOT the trimmed view) so it can see the honest
    provenance markers ``promoted_from`` / discovered / manual-add.
    """
    if _eh.is_discovered(eff):
        return "discovered"
    if (eff.get("promoted_from") or "") == "inbox":
        return "from inbox"
    return "manual"


#: Human label for a grass idea's lifecycle status (used by the workbench chips).
_GRASS_STATUS_LABEL = {
    _eh.GRASS_RAW: "raw",
    _eh.GRASS_REFINED: "refined",
    _eh.GRASS_PROMOTED: "promoted",
}


# v10 Wave 7 — Boneyard: human label for each locked source (D3).
_BONEYARD_SOURCE_LABEL = {
    _boneyard.SOURCE_KILLED: "killed",
    _boneyard.SOURCE_DELETED: "deleted",
    _boneyard.SOURCE_GRASS_DELETED: "grass-deleted",
}


def _boneyard_entry_view(project_id, entry) -> dict:
    """SAFE projection of a Boneyard entry + server-built traversal-safe doc links.

    The entry comes from ``boneyard.list_entries`` / ``boneyard.search``, already a
    SAFE projection (only the public ``_SAFE_KEYS`` — never an absolute path /
    worktree / branch). We add ``doc_links`` (``[{name, href}]``) by routing EVERY
    ``doc_rel`` through the existing traversal-safe ``/artifact?path=<rel>`` route
    (W7 routing decision: the produced docs survive on disk by their main-folder
    rel path under Option A regardless of source — killed/deleted/grass-deleted —
    so /artifact is ALWAYS resolvable and consistent; no fragile /report job_id
    resolution from a content-addressed effort id). The href is path+query escaped;
    the route itself rejects ``..``/absolute/symlink-escape. No absolute path /
    worktree / branch is ever emitted.
    """
    e = entry or {}
    pid_q = url_quote(str(project_id), safe="")
    links = []
    for rel in (e.get("doc_rels", []) or []):
        rel = str(rel or "").strip()
        if not rel:
            continue
        name = rel.replace("\\", "/").rsplit("/", 1)[-1] or rel
        href = f"/artifact/{pid_q}?path={url_quote(rel, safe='')}"
        links.append({"name": name, "href": href})
    # ``when_display`` is the formatted, LOCAL-tz timestamp string computed ONCE on
    # the server (v10 Wave 7 fix). BOTH the server initial render
    # (_render_boneyard_entry_html) AND the client live-search render
    # (_boneyardEntryHtml) use it verbatim, so the displayed time is byte-identical
    # across the initial paint and a post-search re-render (the client used to
    # re-format ``when`` in UTC, causing a ~tz-offset jump on the first search).
    # ``when`` (raw epoch) is kept too for any ordering/raw use. SAFE: a formatted
    # string only — no path / worktree / branch.
    when_raw = e.get("when", 0)
    when_display = ""
    try:
        if when_raw:
            when_display = datetime.fromtimestamp(
                float(when_raw)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        when_display = ""
    return {
        "entry_id": e.get("entry_id", ""),
        "source": e.get("source", ""),
        "source_label": _BONEYARD_SOURCE_LABEL.get(e.get("source", ""),
                                                   e.get("source", "")),
        "session_id": e.get("session_id", ""),
        "lane": e.get("lane", ""),
        "title": e.get("title", ""),
        "summary_excerpt": e.get("summary_excerpt", ""),
        "idea_text": e.get("idea_text", ""),
        "when": when_raw,
        "when_display": when_display,
        "doc_links": links,
    }


def _render_boneyard_entry_html(view) -> str:
    """Render ONE Boneyard entry as a ``.byentry`` (collapsed; expands to summary +
    doc links). All engine/user content HTML-escaped. ``view`` is the
    ``_boneyard_entry_view`` shape (SAFE projection + ``doc_links``)."""
    src = view.get("source", "")
    src_lbl = html_lib.escape(view.get("source_label", src) or src)
    src_cls = html_lib.escape(src, quote=True)
    # RAW title escaped EXACTLY ONCE (quote-safe). ``title`` here is the escaped
    # string reused below; we must NOT re-escape it (the v10-W7 double-escape bug
    # turned ``A & B`` into ``A &amp;amp; B`` because the already-escaped value was
    # passed back through html.escape on the data-title attribute).
    title_raw = view.get("title", "") or "(untitled)"
    title = html_lib.escape(title_raw, quote=True)
    lane = (view.get("lane", "") or "").strip()
    lane_chip = (f"<span class='bylanechip'>{html_lib.escape(lane)}</span>"
                 if lane else "")
    # The displayed timestamp is the server-computed, LOCAL-tz ``when_display`` from
    # the SAFE projection — the SAME string the client live-search render uses, so
    # the initial paint and a post-search re-render are byte-identical (no tz jump).
    when_txt = view.get("when_display", "") or ""
    when_chip = (f"<span class='bywhen'>{html_lib.escape(when_txt)}</span>"
                 if when_txt else "")
    # The expand body: full summary/idea text + doc links.
    summary = (view.get("summary_excerpt", "") or "").strip()
    idea = (view.get("idea_text", "") or "").strip()
    body_text = summary or idea
    if body_text:
        sum_html = (f"<div class='bysum'>{html_lib.escape(body_text)}</div>")
    else:
        sum_html = ("<div class='bysum dim'>No summary captured.</div>")
    # A short collapsed excerpt (the first line of whatever body we have).
    excerpt = body_text.splitlines()[0] if body_text else ""
    exc_html = (f"<div class='byexc'>{html_lib.escape(excerpt)}</div>"
                if excerpt else "")
    links = view.get("doc_links", []) or []
    if links:
        rows = "".join(
            f"<a class='bydoc' href='{html_lib.escape(l['href'], quote=True)}' "
            f"target='_blank' rel='noopener'>{html_lib.escape(l['name'])}</a>"
            for l in links)
        docs_html = (f"<div class='bydocs'><div class='h'>Documents</div>"
                     f"{rows}</div>")
    else:
        docs_html = ("<div class='bydocs'><div class='h'>Documents</div>"
                     "<span class='none'>No documents.</span></div>")
    eid = html_lib.escape(view.get("entry_id", ""), quote=True)
    return (
        f"<div class='byentry' data-byentry=\"{eid}\" data-source='{src_cls}' "
        f"data-title=\"{title}\" "
        f"onclick='toggleBoneyardEntry(this)'>"
        f"<div class='byhd'>"
        f"<span class='bybadge {src_cls}'>{src_lbl}</span>"
        f"<div class='bymeta'><div class='bytitle'>{title}</div>{exc_html}</div>"
        f"{lane_chip}{when_chip}<span class='bycar'>&#9656;</span>"
        f"</div>"
        f"<div class='bybody' onclick='event.stopPropagation()'>"
        f"{sum_html}{docs_html}"
        f"</div>"
        f"</div>"
    )


def _render_boneyard_panel(project_id) -> str:
    """Render the Boneyard panel template (hidden; cloned into ``#panelStack`` by
    ``openBoneyard()``): a search box over a newest-first entry list. The initial
    entries are server-rendered (so the DOM positive/negative assertions are real);
    live search re-fetches ``/api/rnd/boneyard?q=`` and re-renders the list. An
    honest empty state when the project has no discarded material."""
    entry = _rnd.get_project(project_id)
    folder = (entry or {}).get("folder_path", "")
    try:
        raw = _boneyard.list_entries(folder, project_id)
    except Exception:
        raw = []
    views = [_boneyard_entry_view(project_id, e) for e in raw]
    if views:
        rows = "".join(_render_boneyard_entry_html(v) for v in views)
        list_html = rows
    else:
        # Honest empty state — NO fabricated entries (Wave-7 negative).
        list_html = ("<div class='byempty' data-byempty='1'>"
                     "Nothing discarded yet. Killed sessions with material, "
                     "deleted sessions, and deleted grass ideas land here.</div>")
    return (
        "<div class='boneyard' id='boneyardView'>"
        "<div class='bytop'>"
        "<span class='ic'>&#9760;</span>"
        "<span class='lbl'>Discarded material</span>"
        "<span class='sp'></span>"
        "<input class='bysearch' id='boneyardSearch' type='search' "
        "placeholder='search discarded&hellip;' oninput='searchBoneyard()'>"
        "</div>"
        f"<div class='bylist' id='boneyardList'>{list_html}</div>"
        "</div>"
    )


def _render_grass_column_tile(folder_path, project_id) -> str:
    """Render the Grass LANE column content: a single tile that OPENS the
    full-width two-pane idea workbench panel (v5 Wave 5).

    The 5-column cockpit board's Grass column is too narrow for the B+C hybrid
    two-pane workbench, so the column shows one clickable tile (idea count +
    status mix) whose click (``openGrassWorkbench()``) expands the workbench panel
    in ``#panelStack`` — exactly like a lane tile opens a session panel. The old
    single-column ``idea-board`` / ``idea-card`` markup is GONE.
    """
    try:
        ideas = _eh.grass_workbench_data(folder_path, project_id)
    except Exception:
        ideas = []
    n = len(ideas)
    n_raw = sum(1 for i in ideas if i["status"] == _eh.GRASS_RAW)
    n_ref = sum(1 for i in ideas if i["status"] == _eh.GRASS_REFINED)
    n_pro = sum(1 for i in ideas if i["status"] == _eh.GRASS_PROMOTED)
    light = "green" if n_ref else ("amber" if n_raw else "grey")
    sub = (f"{n_raw} raw · {n_ref} refined · {n_pro} promoted"
           if n else "no ideas yet")
    return (
        f"<div class='tile lane-tile grass-tile' data-grass-tile='1' "
        f"data-light='{light}' onclick='openGrassWorkbench()'>"
        f"<div class='tr1'><span class='lane'>ideas</span>"
        f"<span class='ver'></span>"
        f"<span class='lt {light}' aria-hidden='true'></span></div>"
        f"<div class='ttl'>Idea workbench</div>"
        f"<div class='st'><span class='state done'>{html_lib.escape(sub)}</span>"
        f"<span class='age'>· {n} idea{'s' if n != 1 else ''}</span></div>"
        f"</div>"
    )


def _render_grass_idea_li(idea) -> str:
    """Render one idea as a ``.gli`` row for the workbench LEFT list (mockup C)."""
    status = idea["status"]
    cls_extra = (" r" if status == _eh.GRASS_REFINED
                 else (" p" if status == _eh.GRASS_PROMOTED else ""))
    title = html_lib.escape(idea["title"] or "(untitled idea)")
    short = html_lib.escape(idea["short_id"])
    idea_attr = html_lib.escape(idea["idea_id"], quote=True)
    st_lbl = html_lib.escape(_GRASS_STATUS_LABEL.get(status, status))
    src = html_lib.escape(idea["source"])
    return (
        f"<div class='gli{cls_extra}' data-idea=\"{idea_attr}\" "
        f"data-status='{html_lib.escape(status)}' "
        f"data-title=\"{html_lib.escape(idea['title'], quote=True)}\">"
        f"<div class='t'>{title}</div>"
        f"<div class='m'><span class='dot'></span>"
        f"<span class='idchip'>{short}</span>"
        f"<span class='stchip {html_lib.escape(status)}'>{st_lbl}</span>"
        f"<span class='srcchip'>{src}</span>"
        # v9 Wave 2 — a red ✕ DELETE control on the idea row. event.stopPropagation
        # so clicking ✕ does NOT also select the idea; deleteGrassIdea is
        # confirm()-gated then POSTs grass_delete {confirm:true}.
        f"<span class='gli-del' title='Delete this idea' "
        f"onclick=\"event.stopPropagation();deleteGrassIdea('{idea_attr}')\">"
        f"&#10005;</span>"
        f"</div></div>"
    )


def _render_grass_workbench(folder_path, project_id) -> str:
    """Render the FULL B+C hybrid Grass workbench (the approved mockup), as a
    hidden template the panel manager clones into ``#panelStack`` (v5 Wave 5).

    Structure (matching ``_mockups/grass_catcher_refined.html``):
      - ``.gtabs`` filter-tab row: 🌿 · All/raw/refined/promoted (with counts) ·
        a ``.gsearch`` search box · ``+ Add idea`` / ``+ From inbox`` buttons.
      - ``.gwrap`` two-pane grid: ``.glist`` (filtered idea list, ``.gli`` rows
        with ``.idchip``/``.stchip``/``.srcchip``) · ``.gwork`` (the selected
        idea's workbench: title + id + status, ``.desc``, ``.devbar`` with
        Develop 🔬 Research / 📐 Plan + engine toggle + → Promote to a lane, a
        ``.gterms`` block of TWO independent, collapsible ``.gterm`` workbench
        terminals (v10 Wave 3 — one per lane: research, plan), and ``.ghist``
        refinement history with per-version pull buttons).

    The JS (``openGrassWorkbench`` / ``selectGrassIdea`` / ``filterGrass`` /
    ``toggleGrassTerminal`` / ``developGrass`` / ``pullGrass``) wires interactivity;
    this server render
    provides the data-bearing DOM (so the rendered-DOM assertions are real).
    """
    try:
        ideas = _eh.grass_workbench_data(folder_path, project_id)
    except Exception:
        ideas = []
    n = len(ideas)
    n_raw = sum(1 for i in ideas if i["status"] == _eh.GRASS_RAW)
    n_ref = sum(1 for i in ideas if i["status"] == _eh.GRASS_REFINED)
    n_pro = sum(1 for i in ideas if i["status"] == _eh.GRASS_PROMOTED)
    tabs = (
        "<div class='gtabs'>"
        "<span class='ic'>&#127807;</span>"
        f"<span class='gtab on' data-filter='all'>All <span class='n'>{n}</span></span>"
        f"<span class='gtab' data-filter='raw'>raw <span class='n'>{n_raw}</span></span>"
        f"<span class='gtab' data-filter='refined'>refined "
        f"<span class='n'>{n_ref}</span></span>"
        f"<span class='gtab' data-filter='promoted'>promoted "
        f"<span class='n'>{n_pro}</span></span>"
        "<span class='sp'></span>"
        "<input class='gsearch' type='search' placeholder='search ideas&hellip;' "
        "oninput='filterGrass()'>"
        "<button class='mini' onclick='addIdea()'>+ Add idea</button>"
        "<button class='mini' onclick='promoteInbox()'>+ From inbox</button>"
        "</div>"
    )
    if ideas:
        lis = "".join(_render_grass_idea_li(i) for i in ideas)
        list_html = (
            f"<div class='glist'>{lis}"
            "<div class='gadd'><button class='mini' style='width:100%' "
            "onclick='addIdea()'>+ Add idea</button></div></div>"
        )
    else:
        list_html = (
            "<div class='glist'><div class='gli-empty'>No ideas yet — "
            "capture one with &ldquo;+ Add idea&rdquo;.</div>"
            "<div class='gadd'><button class='mini' style='width:100%' "
            "onclick='addIdea()'>+ Add idea</button></div></div>"
        )
    # The right workbench pane starts EMPTY (a "select an idea" hint); selecting
    # a .gli populates it client-side from the row's data + a fetch of /api/rnd/grass.
    work_html = (
        "<div class='gwork' data-empty='1'>"
        "<div class='gwork-empty'>Select an idea on the left to develop it.</div>"
        "</div>"
    )
    return (
        "<div class='grass-workbench' data-grass-workbench='1'>"
        f"{tabs}"
        f"<div class='gwrap'>{list_html}{work_html}</div>"
        "</div>"
    )


def _render_kanban_html(folder_path, project_id):
    """Render the Paradigm-2 lane board: 5 ``.p2col`` columns (Research|Planning|
    Build|Deliverables|Grass) inside a ``.p2lanes`` grid (v4.1 cockpit-render).

    Each content lane (research/plan/build) renders GENUINE Paradigm-2 ``.tile``
    cards — the MOST-RECENT session is the visible tile (status light + click-to-
    -openPanel hook); the remaining sessions sit behind a "previous sessions (N)"
    ``<details>`` expander, ALSO rendered as tiles (NOT effort cards, NO report
    links / summary accordions / file expanders — that detail lives in the opened
    panel). The Deliverables lane renders launch-by-type tiles; the Grass lane is
    the idea board. Each column has an ``<h4>`` header (glyph + label + a live/attn
    lane badge) and a "+ new <lane>" launcher.
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
        # The lane header badge is a small status light (mockup: <span class="lt">
        # in the <h4>): amber when a session needs you, a pulsing green when one is
        # live, otherwise nothing.
        badge = ""
        if any_input:
            badge = "<span class='lt amber' title='needs you'></span>"
        elif any_live:
            badge = "<span class='lt green' title='running'></span>"
        if trio_lane == "grass":
            # v5 Wave 5: the grass lane column shows ONE tile that opens the
            # full-width two-pane B+C hybrid workbench panel (the column is too
            # narrow for the two-pane workbench). The old single-column idea-board
            # markup is gone; the workbench template is appended after the board.
            cards = _render_grass_column_tile(folder_path, project_id)
        elif trio_lane == "deliverables":
            # The deliverables lane is launch-by-type TILES (mockup Paradigm-2),
            # NOT session/effort cards: a tile per pinned deliverable whose click
            # launches it per its type contract.
            cards = _render_deliverable_lane_tiles(folder_path, project_id)
        else:
            cards = _render_lane_sessions(
                session_views, store_lane, project_id, trio_lane, folder_path)
        # The "+ new <lane>" launcher. Research offers an engine choice (Claude
        # default + Gemini); plan/build are Claude-only via the seeded ConPTY path
        # (newTermSession → term_start → terminal_session.start_session);
        # deliverables are config-driven (no launch); grass gets manual add +
        # promote-from-INBOX.
        if trio_lane == "deliverables":
            add = ""
        elif trio_lane == "grass":
            add = (
                f"<span class='addnew' onclick=\"addIdea()\">"
                f"{html_lib.escape(add_label)}</span> "
                f"<span class='addnew' onclick=\"promoteInbox()\">"
                f"+ From inbox</span>"
            )
        elif trio_lane == "research":
            add = (
                "<span class='addnew' onclick=\"newTermSession('research','claude')\">"
                "+ New research run (Claude)</span> "
                "<span class='addnew' onclick=\"newTermSession('research','gemini')\">"
                "Gemini</span>"
            )
        else:
            add = (f"<span class='addnew' onclick=\"newTermSession('{trio_lane}')\">"
                   f"{html_lib.escape(add_label)}</span>")
        lane_attr = html_lib.escape(trio_lane, quote=True)
        cols.append(
            f"<div class='p2col' data-col-lane='{lane_attr}'>"
            f"<h4><span>{glyph}</span> {html_lib.escape(label)} "
            f"<span class='sp'></span>"
            f"<span class='badge' id='badge_{lane_attr}'>{badge}</span></h4>"
            f"<div class='col-tiles' id='cards_{lane_attr}'>{cards}</div>"
            f"{add}</div>"
        )
    board = "<div class='p2lanes'>" + "".join(cols) + "</div>"
    # v5 Wave 5: the full two-pane Grass workbench, rendered ONCE as a hidden
    # template the panel manager (openGrassWorkbench) clones into #panelStack.
    workbench = (
        "<div id='grassWorkbenchTpl' style='display:none'>"
        + _render_grass_workbench(folder_path, project_id)
        + "</div>"
    )
    return board + workbench


def _safe_dom_id(seg: str) -> str:
    """A DOM-id-safe slug of a session id (which contains ``::`` etc.)."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(seg or "")) or "x"


def _session_tile_title(rep) -> str:
    """The visible title for a Paradigm-2 lane tile, derived from a session's
    representative effort view. Discovered → its ``title``; a run → its prompt
    hint / skill ``sub``; falls back to a lane-agnostic placeholder."""
    if not rep:
        return "session"
    if rep.get("discovered"):
        return (rep.get("title") or rep.get("artifact_path") or "imported").strip()
    sub = (rep.get("sub") or "").strip()
    if sub:
        return sub
    return (rep.get("skill") or "session").strip() or "session"


def _session_state_text(rep):
    """Return ``(state_class, state_label)`` for a tile's ``.st`` state span,
    mapped from the representative effort view (mirrors the mockup states:
    running / needs you / fail / done / imported / idle)."""
    if not rep:
        return ("done", "idle")
    if rep.get("discovered"):
        return ("done", "imported")
    if rep.get("needs_input"):
        return ("attn", "needs you")
    if rep.get("is_live"):
        return ("running", "running")
    if rep.get("is_done"):
        return ("done", "done")
    pill = (rep.get("pill_cls") or "").strip()
    if pill == "fail":
        return ("fail", rep.get("pill_lbl") or "failed")
    return ("done", rep.get("pill_lbl") or rep.get("status") or "idle")


def _session_tile_blurb(sv, folder_path, project_id, store_lane):
    """The short, clean blurb line for a lane tile (v7 Wave 3).

    Cache/registry-only — NEVER a synchronous model call on the render path:

    - A FINISHED session prefers its CACHED session summary blurb
      (:func:`summarizer.session_blurb`, a cache read; ``""`` when uncached).
    - A RUNNING session (or a finished one with no cache yet) falls back to its
      own short intent — the rep's ``sub`` (skill · prompt hint) or its
      ``title``/``label`` — run through :func:`summarizer.tile_blurb` so it is
      clean + capped (the Wave-1 normalizer).
    - Honest empty (``""``) when there is neither; the caller renders nothing.

    Stdlib only; never raises (degrades to ``""``).
    """
    rep = (sv.get("members") or [None])[0]
    if not isinstance(rep, dict):
        return ""
    sid = (sv.get("session_id") or "").strip()
    blurb = ""
    # Prefer a cached SESSION summary blurb (cache read; no model call). Skip the
    # synthetic "loose::<jid>" ids (no real cached summary keyed on them).
    if sid and not sid.startswith("loose::"):
        try:
            blurb = _summarizer.session_blurb(
                folder_path, project_id, store_lane, sid) or ""
        except Exception:
            blurb = ""
    if blurb:
        return blurb
    # Fall back to the session's own short intent (running or uncached).
    intent = (rep.get("sub") or rep.get("title") or "").strip()
    if not intent:
        return ""
    try:
        return _summarizer.tile_blurb(intent) or ""
    except Exception:
        return ""


def _render_lane_tile(sv, trio_lane, project_id, folder_path=None,
                      store_lane=""):
    """Render ONE session as a GENUINE Paradigm-2 ``.tile`` (v4.1 cockpit-render).

    Schema (per the mockup): ``.tr1`` (lane + version + status light ``.lt``),
    ``.ttl`` (title), ``.st`` (state + age). The tile carries a status light
    (locked color bucket via :func:`_session_light_class`) and a click hook
    (``laneTileClick`` → ``openPanel``) that opens the full-width inline panel —
    where the summary + transcript/terminal live. The tile itself contains NO
    report-viewer links, NO summary accordion, NO files expander; that detail
    moved INTO the opened panel. The legacy ``lane-tile`` class + ``data-light``
    are preserved alongside ``.tile`` so the panel-open hooks/tests still bind.
    """
    members = sv.get("members", [])
    rep = members[0] if members else None
    if rep is None:
        return ""
    light = _session_light_class(rep)
    sid = sv.get("session_id", "") or ""
    sid_attr = html_lib.escape(sid, quote=True)
    lane_attr = html_lib.escape(trio_lane, quote=True)
    ver = html_lib.escape(rep.get("ver") or "")
    age = html_lib.escape(rep.get("age") or "")
    title = html_lib.escape(_session_tile_title(rep))
    state_cls, state_lbl = _session_state_text(rep)
    state_lbl = html_lib.escape(state_lbl)
    # Extra tile class for the attn/fail accent borders (mockup .tile.attn/.fail).
    extra = ""
    if light == "amber" and rep.get("needs_input"):
        extra = " attn"
    elif light == "red":
        extra = " fail"
    st_bits = [f"<span class='state {html_lib.escape(state_cls)}'>{state_lbl}</span>"]
    if age:
        st_bits.append(f"<span class='age'>· {age}</span>")
    n_members = len(members)
    counts = ""
    if n_members > 1:
        counts = (f"<div class='counts'>{n_members} files</div>")
    # v7 Wave 3 — a short, clean blurb line (cache/registry-only; no model call).
    # Cached session-summary blurb for a finished session, else the session's own
    # short intent for a running/uncached one; honest-empty renders nothing.
    blurb_html = ""
    if folder_path is not None:
        blurb = _session_tile_blurb(sv, folder_path, project_id, store_lane)
        if blurb:
            blurb_html = f"<div class='blurb'>{html_lib.escape(blurb)}</div>"
    # Live-job data hooks: a live/needs-input representative carries its job_id +
    # live flag as data-* attributes (used by tests + any future re-adoption of a
    # background job). The cockpit opens such a tile through laneTileClick →
    # openPanel like any other. (Discovered/done tiles carry no live hooks.)
    live_data = ""
    if rep.get("is_live"):
        jid = rep.get("job_id", "") or ""
        live_data = (
            f" data-job-id=\"{html_lib.escape(jid, quote=True)}\""
            f" data-trio-lane=\"{lane_attr}\""
            f" data-ver=\"{ver}\" data-live=\"1\"")
    # Build→Planning tie (Option A): a clickable chip on the build tile linking to
    # the planning session this build executed on (set by _attach_build_planning_tie
    # only when there is a clear single-planning match). The matched planning
    # session_id rides as data-* so the opened panel's chain breadcrumb can render
    # the same tie (see _loadChainBreadcrumb's static fallback). Clicking the chip
    # opens that planning session's panel without also opening this tile's panel.
    tie = sv.get("linked_planning") or {}
    tie_data = ""
    tie_chip = ""
    if tie.get("session_id"):
        lp_sid = html_lib.escape(tie["session_id"], quote=True)
        lp_lbl = html_lib.escape(tie.get("label") or "planning")
        lp_lbl_attr = html_lib.escape(tie.get("label") or "planning", quote=True)
        tie_data = (f" data-linked-planning=\"{lp_sid}\""
                    f" data-linked-planning-label=\"{lp_lbl_attr}\"")
        tie_chip = (
            f"<span class='tiechip' title='Open the planning session this build "
            f"executed on' onclick=\"openLinkedPlanning(event,'{lp_sid}')\">"
            f"&#9741; Planning: {lp_lbl} &#9656;</span>")
    # v10 Wave 4 FIX 2 (D8): the board-tile "from grass" lineage chip. When this
    # session's record carries a ``grass_origin`` (set on the dev session at
    # export, or INHERITED down the chain by start_session FIX 1), render a chip
    # on the plan/build board tile that links back to the originating grass idea
    # — satisfying D8 VISIBLY on the board (not only in the opened panel). The
    # chip reads ONLY the SAFE projection field ``grass_origin`` (an idea id —
    # never worktree_path/branch). Its label + dead-state ("idea removed") are
    # resolved client-side by ``_resolveGrassOriginChips`` against the loaded
    # grass data, so the server render stays cheap and the panel + tile chips
    # share one dead-chip code path. Only plan/build columns carry it (the lanes
    # the mockup depicts); research is the chain root, never "from" itself.
    grass_chip = ""
    origin = (rep.get("grass_origin") or "").strip()
    if origin and trio_lane in ("plan", "planning", "build"):
        origin_attr = html_lib.escape(origin, quote=True)
        grass_chip = (
            f"<span class='grassorigin' data-grass-origin=\"{origin_attr}\" "
            f"data-grass-pending=\"1\" "
            f"title='This work traces back to a grass idea — click to open it'>"
            f"&#127793; from grass</span>")
    return (
        f"<div class='tile lane-tile{extra}' data-session=\"{sid_attr}\" "
        f"data-lane=\"{lane_attr}\" data-light=\"{light}\"{live_data}{tie_data} "
        f"onclick=\"laneTileClick(event,'{sid_attr}')\">"
        f"<div class='tr1'><span class='lane'>{ver or lane_attr}</span>"
        f"<span class='ver'></span>"
        f"<span class='lt {light}' aria-hidden='true'></span></div>"
        f"<div class='ttl'>{title}</div>"
        f"{blurb_html}"
        f"<div class='st'>{''.join(st_bits)}</div>"
        f"{counts}"
        f"{tie_chip}"
        f"{grass_chip}"
        f"</div>"
    )


def _render_lane_sessions(session_views, store_lane, project_id, trio_lane="",
                          folder_path=None):
    """Render a lane's sessions as Paradigm-2 tiles: most-recent visible +
    a "previous sessions (N)" expander holding the rest, ALSO as tiles
    (v4.1 cockpit-render — replaces the old effort-card lane content).

    The MOST-RECENT session is the visible lane TILE — a status light
    (``.lt green/amber/red/grey`` from :func:`_session_light_class`) + a
    click-to-expand hook (``laneTileClick`` → ``openPanel``) opening the
    full-width inline panel (NOT a floating window, NOT page nav). The remaining
    sessions are tiles inside a ``<details class='prev-sessions'>`` expander. No
    tile carries report links / a summary accordion / a files expander — that
    detail lives in the opened panel.
    """
    if not session_views:
        return ""
    recent = _render_lane_tile(
        session_views[0], trio_lane, project_id, folder_path, store_lane)
    older = session_views[1:]
    if not older:
        return recent
    older_tiles = "".join(
        _render_lane_tile(sv, trio_lane, project_id, folder_path, store_lane)
        for sv in older)
    return (
        f"{recent}"
        f"<details class='prev-sessions'>"
        f"<summary>previous sessions ({len(older)})</summary>"
        f"<div class='prev-sessions-body'>{older_tiles}</div>"
        f"</details>"
    )


# v4.1 cockpit-render — Deliverables lane = launch-by-type TILES.
def _render_deliverable_lane_tiles(folder_path, project_id) -> str:
    """Render the Deliverables lane as launch-by-type ``.tile`` cards (mockup
    Paradigm-2): one tile per pinned deliverable, showing its name + type, whose
    click launches it via the existing ``launchDeliverable`` JS (which POSTs the
    type-appropriate run endpoint). Falls back to a placeholder when none are
    pinned. Best-effort; never raises."""
    try:
        pinned = _deliv.list_pinned_deliverables(folder_path, project_id)
    except Exception:
        pinned = []
    if not pinned:
        return ("<div class='idea-empty'>No deliverables pinned yet — a Foreman "
                "build pins one on GREEN.</div>")
    tiles = []
    for r in pinned:
        name = html_lib.escape(r.get("title") or r.get("artifact_path") or "")
        rel = r.get("artifact_path", "") or ""
        raw_type = (r.get("deliverable_type", "") or "").strip().lower()
        if raw_type not in _deliv.VALID_TYPES:
            raw_type = _deliv.infer_type(rel)
        dtype = html_lib.escape(raw_type)
        did = r.get("job_id", "") or ""
        rel_attr = html_lib.escape(rel, quote=True)
        did_attr = html_lib.escape(did, quote=True)
        tiles.append(
            f"<div class='tile deliv-tile deliv-pinned' data-deliv=\"{rel_attr}\" "
            f"data-deliv-id=\"{did_attr}\" data-deliv-type=\"{dtype}\" "
            f"onclick=\"launchDeliverable(this)\">"
            f"<div class='tr1'><span class='lane'>{dtype}</span>"
            f"<span class='lt grey' aria-hidden='true'></span></div>"
            f"<div class='ttl'>{name}</div>"
            f"<div class='st'><span class='state done'>▸ launch</span>"
            f"<span class='deliv-msg' style='color:var(--text-dim);"
            f"margin-left:6px'></span></div>"
            f"<button class='deliv-stop' onclick=\"event.stopPropagation();"
            f"stopDeliverable(this)\" style='display:none'>Stop</button>"
            f"</div>"
        )
    return "".join(tiles)


def _fmt_rollup_line(roll: dict) -> str:
    """Render a ``project_effort_rollup`` dict as ``Σ <tok> tok · $<c> · <t> · N sessions``.

    Used by the project-window header (v4 Wave 5). Run-session-only totals (the
    rollup already excludes imported/discovered). Stdlib only; never raises.
    """
    toks = int(roll.get("tokens", 0) or 0)
    cost = float(roll.get("cost_usd", 0.0) or 0.0)
    ms = int(roll.get("wall_clock_ms", 0) or 0)
    n = int(roll.get("sessions", 0) or 0)
    secs = ms / 1000.0
    if secs >= 3600:
        tstr = f"{secs / 3600.0:.1f}h"
    elif secs >= 60:
        tstr = f"{secs / 60.0:.0f}m"
    else:
        tstr = f"{secs:.0f}s"
    if toks >= 1000:
        tokstr = f"{toks / 1000.0:.0f}k tok"
    else:
        tokstr = f"{toks} tok"
    return (f"Σ {tokstr} · ${cost:.2f} · {tstr} "
            f"· {n} session{'' if n == 1 else 's'}")


def render_header_rollup_html(project_id: str) -> str:
    """The per-project cost/tokens/time rollup for the project-window header.

    Server-side render of ``effort_history.project_effort_rollup(pid,'lifetime')``
    beside the project path (v4 Wave 5, MASTER-PLAN cockpit header). A small
    lifetime/30-day toggle re-fetches the read-only ``/api/rnd/project_rollup``
    endpoint and swaps the text in place (the actual swap is the JS
    ``rndRollupWindow``). Both windows' text are rendered so a no-JS view still
    shows lifetime totals. Stdlib only; never raises (omits on failure).
    """
    try:
        life = _eh.project_effort_rollup(project_id, window=_eh.WINDOW_LIFETIME)
    except Exception:
        return ""
    pid_attr = html_lib.escape(project_id, quote=True)
    life_txt = html_lib.escape(_fmt_rollup_line(life))
    return (
        f"<span class='roll' id='hdrRollup' data-window='lifetime' "
        f"data-pid=\"{pid_attr}\">{life_txt}</span>"
        f"<span class='rolltog' role='group' aria-label='rollup window'>"
        f"<b class='on' data-window='lifetime' "
        f"onclick=\"rndRollupWindow('lifetime',this)\">lifetime</b>"
        f"<b data-window='30d' "
        f"onclick=\"rndRollupWindow('30d',this)\">30d</b>"
        f"</span>"
    )


def render_project_window_html(project_id: str) -> str:
    """Render the per-project "Project Cockpit" (Paradigm 2) for ``/project/<id>``.

    A 5-column Paradigm-2 lane grid (``.p2lanes`` → Research|Planning|Build|
    Deliverables|Grass) of clean status-light TILES (most-recent session per lane
    + a "previous sessions" expander; Deliverables = launch-by-type tiles; Grass =
    idea board). Clicking ANY tile (live OR historical) opens an inline expanding
    panel in ``#panelStack`` with a split summary on top (materials + doc-role
    links) and, below, a live xterm terminal for running sessions or a read-only
    note for done/historical ones. Plus the lifecycle header with the cost/tokens/
    time rollup. Returns a standalone HTML page; all engine/user content is
    HTML-escaped (XSS-safe).
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
    # v5 Wave 3: the project's cached OBJECTIVE summary (read-only — NEVER runs
    # the model on the render path). Shown in the header as the "objective" line;
    # falls back to the blurb when no summary is cached yet.
    objective_raw = ""
    try:
        cached = _summarizer.load_cached_project(folder_raw, project_id)
        if cached:
            # v7 Wave 1: clean, capped plain-text objective line (strip
            # markdown/decorative glyphs) for the project-window header.
            objective_raw = _summarizer.short_summary_text(
                (cached.get("summary_text") or "").strip())
    except Exception:
        objective_raw = ""
    objective_esc = html_lib.escape(objective_raw)
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
    # Wave 8: if this project's folder IS an Anchor checkout (has anchor_gui.py),
    # pin it as the runnable deliverable so the Deliverables LANE shows it as a
    # launch-by-type tile. Idempotent (content-addressed); best-effort. (The loose
    # bottom "Deliverables / Pinned" section is gone — deliverables are the lane.)
    # MUST run BEFORE _render_kanban_html so the freshly-pinned deliverable shows
    # in the Deliverables lane on THIS render (not only the next one).
    try:
        if (Path(folder_raw) / _preview.DEFAULT_TARGET).is_file():
            ensure_anchor_deliverable(folder_raw, project_id)
    except Exception:
        pass
    # v5 Wave 4: backfill — scan this project's BUILD sessions and auto-pin any
    # unambiguously-resolved deliverable so it appears in the Deliverables lane.
    # Idempotent (content-addressed pins); ambiguous/none left unpinned (never
    # fabricated). Best-effort: a failure never breaks the window render. Runs
    # BEFORE the kanban render so the auto-pinned deliverable surfaces this render.
    try:
        _deliv.backfill_build_deliverables(folder_raw, project_id)
    except Exception:
        pass
    kanban = _render_kanban_html(folder_raw, project_id)
    status = render_status_line_html(project_id)
    header_rollup = render_header_rollup_html(project_id)
    tasks_html = render_project_tasks_html(project_id)
    # v10 Wave 7: the Boneyard panel, rendered ONCE as a hidden template the panel
    # manager (openBoneyard) clones into #panelStack — same idiom as the grass
    # workbench template.
    boneyard_tpl = (
        "<div id='boneyardTpl' style='display:none'>"
        + _render_boneyard_panel(project_id)
        + "</div>"
    )
    pid_js = json.dumps(project_id)
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{name} — Anchor R&amp;D</title>"
        # Vendored REAL xterm.js terminal (canvas), served like KaTeX. xterm.css
        # styles the terminal grid mounted inside each live inline panel. (The v2
        # anchor-term REPL chrome is no longer used by the cockpit.)
        f"<link rel='stylesheet' href='{XTERM_URL_PREFIX}/xterm.css'>"
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
        # v4 Wave 5: header rollup (Σ tokens · $ · time · N sessions) + window toggle.
        ".dhead .roll{font-size:11px;color:var(--text-dim);"
        "font-family:ui-monospace,Consolas,monospace;border-left:1px solid "
        "var(--border);padding-left:10px;margin-left:2px}"
        ".dhead .rolltog{display:inline-flex;border:1px solid var(--border);"
        "border-radius:6px;overflow:hidden;margin-left:2px}"
        ".dhead .rolltog b{font-size:10px;padding:2px 8px;background:var(--surface);"
        "color:var(--text-dim);cursor:pointer;font-weight:500}"
        ".dhead .rolltog b.on{background:rgba(108,156,252,.15);color:var(--accent);"
        "font-weight:700}"
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
        # v8 Wave 3 — GitHub link / auto-push header controls (#ghRemote span).
        ".gh-remote{display:inline-flex;align-items:center;gap:7px}"
        ".gh-linked{font-size:11px;color:var(--accent);"
        "max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".gh-autopush{font-size:11px;color:var(--text);display:inline-flex;"
        "align-items:center;gap:3px;cursor:pointer;user-select:none}"
        # v4.1 cockpit-render — Paradigm-2 lane board (.p2lanes / .p2col), the
        # mockup's "Inline expanding panels" column layout (replaces .kan/.col).
        ".p2lanes{display:grid;grid-template-columns:repeat(5,1fr);gap:9px;"
        "padding:14px 16px}"
        ".p2col{min-width:0}"
        ".p2col h4{font-size:10.5px;text-transform:uppercase;letter-spacing:1px;"
        "color:var(--text-dim);display:flex;align-items:center;gap:7px;"
        "margin:0 0 9px}"
        ".p2col h4 .sp{flex:1}"
        ".p2col .tile{margin-bottom:8px}"
        ".col-tiles{min-height:24px}"
        # The lane-header live/attn light is a small .lt dot in the <h4> (set by
        # _render_kanban_html). The "previous sessions (N)" expander holds the
        # older sessions AS TILES below the most-recent visible tile.
        ".prev-sessions{margin-top:2px}"
        ".prev-sessions>summary{font-size:11px;color:var(--text-dim);"
        "cursor:pointer;list-style:none;padding:3px 2px}"
        ".prev-sessions>summary:hover{color:var(--accent)}"
        ".prev-sessions-body{margin-top:6px}"
        ".summ-loading{color:var(--text-dim);font-size:10.5px;font-style:italic}"
        ".addnew{font-size:12px;color:var(--accent);cursor:pointer;"
        "display:inline-block;margin-top:4px}"
        ".addnew.rnd-dim{color:var(--text-dim);cursor:default}"
        # ── v4 Wave 6: Grass Catcher IDEA BOARD (not a flat text page) ──
        # The grass lane opens as a board of idea cards; each carries its text, a
        # source chip (inbox / discovered / manual), and two promote actions
        # (→ Research / → Plan) that start a NEW seeded session in that lane.
        ".idea-board{display:flex;flex-direction:column;gap:7px}"
        ".idea-card{background:var(--surface2);border:1px solid var(--border);"
        "border-radius:7px;padding:9px 11px}"
        ".idea-card .itxt{font-size:12px;color:var(--text);font-weight:500}"
        ".idea-card .irow{display:flex;align-items:center;gap:8px;margin-top:6px}"
        ".idea-src{font-size:10px;text-transform:uppercase;letter-spacing:.5px;"
        "color:var(--text-dim);padding:1px 6px;border:1px solid var(--border);"
        "border-radius:9px}"
        ".idea-card .isp{flex:1}"
        ".idea-promote{font-size:11px;color:var(--accent);cursor:pointer;"
        "border:1px solid var(--border);border-radius:7px;padding:2px 8px}"
        ".idea-promote:hover{border-color:var(--accent)}"
        ".idea-empty{font-size:11px;color:var(--text-dim);padding:4px 2px}"
        # ── v5 Wave 5: Grass B+C hybrid workbench (mockup grass_catcher_refined) ──
        ".grass-tile{cursor:pointer}"
        ".grass-workbench{background:var(--surface);border:1px solid var(--border);"
        "border-radius:10px;overflow:hidden}"
        ".gtabs{display:flex;align-items:center;gap:5px;padding:9px 12px;"
        "border-bottom:1px solid var(--border);background:var(--surface2);"
        "flex-wrap:wrap}"
        ".gtabs .ic{font-size:15px;margin-right:4px}"
        ".gtab{font-size:12px;padding:5px 12px;border-radius:20px;"
        "border:1px solid var(--border);color:var(--text-dim);cursor:pointer}"
        ".gtab.on{color:var(--text);background:rgba(108,156,252,.12);"
        "border-color:var(--accent)}"
        ".gtab .n{opacity:.7}"
        ".gtabs .sp{flex:1}"
        ".gsearch{font-size:12px;padding:4px 9px;border-radius:7px;"
        "border:1px solid var(--border);background:var(--surface);color:var(--text);"
        "min-width:140px}"
        ".gwrap{display:grid;grid-template-columns:320px 1fr;min-height:430px}"
        ".glist{border-right:1px solid var(--border);background:#13161f;"
        "overflow:auto;max-height:560px}"
        ".gli{padding:10px 13px;border-bottom:1px solid var(--border);cursor:pointer}"
        ".gli:hover{background:var(--surface2)}"
        ".gli.sel{background:rgba(108,156,252,.1);border-left:3px solid var(--accent)}"
        ".gli .t{font-size:12.5px;line-height:1.35}"
        ".gli .m{font-size:10.5px;color:var(--text-dim);margin-top:4px;display:flex;"
        "gap:7px;align-items:center;flex-wrap:wrap}"
        ".gli .dot{width:6px;height:6px;border-radius:50%;background:var(--text-dim)}"
        ".gli.r .dot{background:var(--success)}.gli.p .dot{background:var(--accent)}"
        ".gli-empty{padding:14px 13px;color:var(--text-dim);font-size:12px}"
        # v9 Wave 2 — the red ✕ DELETE control on an idea row (pushed to the right).
        ".gli-del{margin-left:auto;color:#ef4444;font-size:12px;line-height:1;"
        "cursor:pointer;padding:1px 5px;border-radius:5px;opacity:.55;"
        "border:1px solid transparent}"
        ".gli-del:hover{opacity:1;background:rgba(239,68,68,.12);"
        "border-color:rgba(239,68,68,.4)}"
        ".idchip{font-family:ui-monospace,Consolas,monospace;font-size:10px;"
        "color:var(--text-dim);background:var(--surface);border:1px solid var(--border);"
        "border-radius:5px;padding:1px 6px}"
        ".srcchip{font-size:10px;color:var(--text-dim);border:1px solid var(--border);"
        "border-radius:20px;padding:1px 8px}"
        ".stchip{font-size:10px;border-radius:20px;padding:1px 8px}"
        ".stchip.raw{color:var(--text-dim);border:1px solid var(--border)}"
        ".stchip.refined{color:var(--success);border:1px solid rgba(34,197,94,.4);"
        "background:rgba(34,197,94,.08)}"
        ".stchip.promoted{color:var(--accent);border:1px solid rgba(108,156,252,.4);"
        "background:rgba(108,156,252,.08)}"
        ".gwork{padding:15px 18px;min-width:0;display:flex;flex-direction:column}"
        ".gwork-empty{color:var(--text-dim);font-size:13px;padding:20px 4px}"
        ".gwork h3{font-size:16px;margin-bottom:5px;display:flex;align-items:center;"
        "gap:9px;flex-wrap:wrap}"
        ".gwork .desc{font-size:13px;color:var(--text);margin-bottom:4px}"
        ".gwork .sub{font-size:12px;color:var(--text-dim);margin-bottom:12px}"
        ".devbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;"
        "margin-bottom:4px}"
        ".devbar .lbl{font-size:11px;color:var(--text-dim)}.devbar .sp{flex:1}"
        ".mini.go{border-color:rgba(34,197,94,.5)}"
        # v10 Wave 3 — TWO independent, labeled, collapsible terminal hosts
        # (research + plan). Each is a .gterm with its own bar + toggle caret; a
        # collapsed one HIDES its term-host (the session stays LIVE underneath).
        ".devbar .mini.go.on{background:rgba(34,197,94,.13);"
        "border-color:var(--success);color:#d8ffe6}"
        ".devbar .mini.go .car{display:inline-block;width:11px;font-size:10px;"
        "color:var(--text-dim);margin-left:4px}"
        ".devbar .mini.go.on .car{color:var(--success)}"
        ".grass-workbench .gterms{margin-top:11px;display:flex;"
        "flex-direction:column;gap:11px}"
        ".grass-workbench .gterm{background:#05070c;border:1px solid var(--border);"
        "border-radius:8px;overflow:hidden;display:flex;flex-direction:column;"
        "resize:vertical;min-height:150px}"
        ".grass-workbench .gterm[data-lane='research']{border-left:3px solid var(--success)}"
        ".grass-workbench .gterm[data-lane='plan']{border-left:3px solid var(--accent)}"
        ".grass-workbench .gterm .tbar{display:flex;align-items:center;gap:8px;"
        "padding:5px 9px;background:#11141c;border-bottom:1px solid var(--border);"
        "cursor:pointer}"
        ".grass-workbench .gterm .tbar .lab{font-size:11px;color:var(--text-dim)}"
        ".grass-workbench .gterm .tbar .lab b{color:var(--text)}"
        ".grass-workbench .gterm .tbar .sp{flex:1}"
        ".grass-workbench .gterm .tbar .car{font-size:11px;color:var(--text-dim);"
        "width:14px;text-align:center}"
        ".grass-workbench .gterm .tbar .gsave{font-size:10.5px;padding:2px 7px;cursor:pointer}"
        ".grass-workbench .gterm .tbar .gsave:disabled{opacity:.4;cursor:default}"
        # v10 Wave 4 — per-lane Archive control (distinct from Save).
        ".grass-workbench .gterm .tbar .garchive{font-size:10.5px;padding:2px 7px;"
        "cursor:pointer}"
        ".grass-workbench .gterm .tbar .garchive:disabled{opacity:.4;cursor:default}"
        ".grass-workbench .gterm .term-host{flex:1;overflow:auto;min-height:120px}"
        ".grass-workbench .gterm.collapsed{resize:none;min-height:0}"
        ".grass-workbench .gterm.collapsed .term-host{display:none}"
        ".grass-workbench .gterm.collapsed{border-style:dashed;opacity:.92}"
        ".grass-workbench .gterm .stale{color:var(--text-dim);font-size:10px}"
        ".ghist{margin-top:13px;border-top:1px solid var(--border);padding-top:10px}"
        ".ghist .h{font-size:10px;text-transform:uppercase;letter-spacing:1px;"
        "color:var(--text-dim);margin-bottom:7px}"
        ".ghist .hr{font-size:12px;color:var(--text);padding:6px 0;"
        "border-bottom:1px solid var(--border);display:flex;gap:9px;"
        "align-items:center;flex-wrap:wrap}"
        ".ghist .hr a{color:var(--accent);text-decoration:none}"
        ".ghist .hr .sp{flex:1}"
        ".ghist-empty{font-size:11.5px;color:var(--text-dim)}"
        # v10 Wave 4 — Archived material list (per-idea bundles: docs + summary).
        ".garch{margin-top:13px;border-top:1px solid var(--border);padding-top:10px}"
        ".garch .h{font-size:10px;text-transform:uppercase;letter-spacing:1px;"
        "color:var(--text-dim);margin-bottom:7px}"
        ".garch .ar{font-size:12px;color:var(--text);padding:6px 0;"
        "border-bottom:1px solid var(--border);display:flex;gap:9px;"
        "align-items:center;flex-wrap:wrap}"
        ".garch .ar .lnchip{font-size:10px;text-transform:uppercase;"
        "letter-spacing:.5px;background:#1b2030;padding:1px 6px;border-radius:5px;"
        "color:var(--text-dim)}"
        ".garch .ar .alink{color:var(--accent);text-decoration:none}"
        ".garch .ar .sp{flex:1}"
        ".garch .ar .garch-nodoc,.garch .ar .garch-nosum{color:var(--text-dim);"
        "font-style:italic;font-size:11px}"
        ".garch-empty{font-size:11.5px;color:var(--text-dim)}"
        # v10 Wave 4 — panel-header "from grass: <idea>" lineage back-link chip.
        ".grassorigin{font-size:10.5px;background:#15301c;color:#7be0a0;"
        "border:1px solid #2a5a3a;padding:1px 8px;border-radius:9px;cursor:pointer;"
        "margin-left:6px;white-space:nowrap}"
        ".grassorigin:hover{background:#1c3d26}"
        ".grassorigin.removed{background:#1b1e26;color:#6b7280;"
        "border-color:#33384a;cursor:default;opacity:.7}"
        ".grassorigin.removed:hover{background:#1b1e26}"
        "@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(108,156,252,.5)}"
        "70%{box-shadow:0 0 0 6px rgba(108,156,252,0)}"
        "100%{box-shadow:0 0 0 0 rgba(108,156,252,0)} }"
        # ── v10 Wave 7 — Boneyard panel (per-project discarded material) ──────
        # A search box over a newest-first list of discard entries; each entry has
        # a source badge (killed/deleted/grass-deleted), title, when, lane, a short
        # excerpt/idea text, and (expanded) the full text + doc links (open via the
        # safe /artifact route in a new tab). Honest empty state when nothing was
        # discarded. Matches the cockpit dark-slate styling.
        ".boneyard{display:flex;flex-direction:column;min-width:0}"
        ".bytop{display:flex;align-items:center;gap:9px;padding:10px 14px;"
        "border-bottom:1px solid var(--border);background:var(--surface2);"
        "flex-wrap:wrap}"
        ".bytop .ic{font-size:15px;margin-right:2px}"
        ".bytop .lbl{font-size:11px;color:var(--text-dim)}"
        ".bytop .sp{flex:1}"
        ".bysearch{font-size:12px;padding:5px 10px;border-radius:7px;"
        "border:1px solid var(--border);background:var(--surface);color:var(--text);"
        "min-width:200px}"
        ".bylist{padding:8px 12px;overflow:auto;max-height:560px;"
        "display:flex;flex-direction:column;gap:8px}"
        ".byentry{background:var(--surface2);border:1px solid var(--border);"
        "border-radius:8px;overflow:hidden}"
        ".byentry .byhd{display:flex;align-items:center;gap:9px;padding:9px 12px;"
        "cursor:pointer;flex-wrap:wrap}"
        ".byentry .byhd:hover{background:#20242f}"
        ".byentry .bytitle{font-size:12.5px;color:var(--text);font-weight:500;"
        "min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
        "max-width:100%}"
        ".byentry .byexc{font-size:11px;color:var(--text-dim);margin-top:2px;"
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".byentry .bymeta{min-width:0;flex:1}"
        ".bybadge{font-size:9.5px;text-transform:uppercase;letter-spacing:.5px;"
        "padding:2px 8px;border-radius:20px;border:1px solid var(--border);"
        "color:var(--text-dim);white-space:nowrap}"
        ".bybadge.killed{color:var(--warning);border-color:rgba(251,191,36,.4);"
        "background:rgba(251,191,36,.08)}"
        ".bybadge.deleted{color:var(--danger);border-color:rgba(248,113,113,.4);"
        "background:rgba(248,113,113,.08)}"
        ".bybadge.grass-deleted{color:var(--success);"
        "border-color:rgba(34,197,94,.4);background:rgba(34,197,94,.08)}"
        ".bylanechip{font-size:10px;color:var(--text-dim);"
        "border:1px solid var(--border);border-radius:5px;padding:1px 6px}"
        ".bywhen{font-size:10px;color:var(--text-dim);white-space:nowrap}"
        ".bycar{font-size:11px;color:var(--text-dim);width:14px;text-align:center}"
        ".byentry .bybody{display:none;padding:0 13px 12px;"
        "border-top:1px solid var(--border)}"
        ".byentry.open .bybody{display:block}"
        ".byentry .bysum{font-size:12px;color:var(--text);margin:11px 0 8px;"
        "white-space:pre-wrap;line-height:1.45}"
        ".byentry .bysum.dim{color:var(--text-dim);font-style:italic}"
        ".bydocs{display:flex;flex-direction:column;gap:5px}"
        ".bydocs .h{font-size:10px;text-transform:uppercase;letter-spacing:1px;"
        "color:var(--text-dim);margin-bottom:2px}"
        ".bydoc{font-size:12px;color:var(--accent);text-decoration:none;"
        "font-family:ui-monospace,Consolas,monospace}"
        ".bydoc:hover{text-decoration:underline}"
        ".bydocs .none{font-size:11px;color:var(--text-dim);font-style:italic}"
        ".byempty{padding:26px 14px;color:var(--text-dim);font-size:13px;"
        "text-align:center}"
        ".taskstrip{border-top:1px solid var(--border);padding:11px 16px}"
        ".rnd-status-line{margin:0;display:flex;gap:8px;flex-wrap:wrap}"
        ".rnd-lane{padding:4px 10px;border-radius:6px;background:#1b2030;"
        "font-size:13px}"
        ".rnd-lane-empty{color:var(--text-dim)}"
        ".rnd-imported{color:var(--text-dim);font-style:italic;font-size:11px}"
        ".rnd-running{color:var(--success);font-size:11px}"
        ".rnd-dim{color:var(--text-dim)}"
        "h2{font-size:14px;margin:18px 0 6px}"
        # ── v4.1 cockpit-render: Paradigm-2 lane TILE (.tile schema) + status
        # light (.lt). The most-recent session in each lane is a clean .tile with
        # a top row (.tr1 = lane/version + a status light .lt), a title (.ttl), and
        # a state line (.st = state + age). The light color comes from the LOCKED
        # bucket (_session_light_class ↔ the JS _statusColor): running=green,
        # needs-you/done=amber, failed=red, idle/discovered=grey. The legacy
        # .lane-tile class is kept as an alias on the same element so the panel-open
        # hooks still bind. (Single-brace plain literals — NOT an f-string.)
        ".tile{background:var(--surface2);border:1px solid var(--border);"
        "border-radius:10px;padding:11px 12px;cursor:pointer;transition:.12s;"
        "position:relative}"
        ".tile:hover{border-color:var(--accent);transform:translateY(-1px)}"
        ".tile.attn{border-color:rgba(251,191,36,.45)}"
        ".tile.fail{border-color:rgba(248,113,113,.45)}"
        ".tile .tr1{display:flex;align-items:center;gap:8px}"
        ".tile .lane{font-size:11px;text-transform:uppercase;letter-spacing:.8px;"
        "color:var(--text-dim);font-weight:700}"
        ".tile .ver{margin-left:auto;font-size:11px;color:var(--text-dim)}"
        ".tile .ttl{font-size:13px;font-weight:600;margin-top:6px;line-height:1.35;"
        "word-break:break-word}"
        # v7 Wave 3 — the short session blurb line under the tile title.
        ".tile .blurb{font-size:11px;color:var(--text-dim);margin-top:3px;"
        "line-height:1.35;word-break:break-word}"
        ".tile .st{font-size:11px;color:var(--text-dim);margin-top:5px;"
        "display:flex;align-items:center;gap:6px;flex-wrap:wrap}"
        ".tile .st .state{font-weight:600}"
        ".tile .st .state.running{color:var(--success)}"
        ".tile .st .state.attn{color:var(--warning)}"
        ".tile .st .state.fail{color:var(--danger)}"
        ".tile .st .state.done{color:var(--text-dim)}"
        ".tile .st .age{color:var(--text-dim)}"
        ".tile .counts{font-size:10.5px;color:var(--text-dim);margin-top:6px}"
        # Build→Planning tie chip (Option A): a small clickable pill on a build
        # tile linking back to the planning session it executed on.
        ".tile .tiechip{display:inline-flex;align-items:center;gap:4px;"
        "font-size:10.5px;margin-top:7px;padding:1px 7px;border-radius:9px;"
        "font-weight:600;cursor:pointer;color:var(--accent);"
        "background:rgba(108,156,252,.13);border:1px solid rgba(108,156,252,.35)}"
        ".tile .tiechip:hover{background:rgba(108,156,252,.25)}"
        ".tile .deliv-stop{font-size:11px;margin-top:6px;padding:2px 8px;"
        "border-radius:6px;border:1px solid var(--border);"
        "background:var(--surface);color:var(--text);cursor:pointer}"
        # The status light is a small inline dot in the tile's .tr1 (and in the
        # lane-header .badge / panel .pbar). Used inline-flex elsewhere too.
        ".lt{width:9px;height:9px;border-radius:50%;display:inline-block;"
        "flex-shrink:0;background:var(--text-dim)}"
        ".tile .tr1 .lt{margin-left:auto}"
        ".lt.green{background:#22c55e}"
        ".lt.amber{background:#fbbf24}"
        ".lt.red{background:#f87171}"
        ".lt.grey{background:#8b8f9a;opacity:.6}"
        # ── v4 Wave 4: inline expanding PANEL STACK (replaces the floating windows) ──
        # Clicking a lane tile expands a full-width panel appended BELOW the board.
        # Panels stack down the page; minimize collapses back to the tile (the
        # session keeps running); the X kills behind a confirm. Wave 5 fills the
        # panel body (split summary + xterm terminal); this wave ships the shell.
        ".panel-stack{display:flex;flex-direction:column}"
        # v6 Wave 6: transient note when killing a planning session auto-opens a
        # linked build session. Advisory chrome — fades out after a few seconds.
        ".autobuild-note{margin:6px 0;padding:6px 10px;border-radius:6px;"
        "background:#0f291b;border:1px solid #22c55e;color:#86efac;"
        "font-size:12px;font-weight:600}"
        # v10 Wave 2: a subtle hint shown when a handoff opens the next stage with
        # the prompt PASTED-but-UNSENT in the input — "review & press Enter to run".
        ".pendpaste-hint{margin:6px 0;padding:6px 10px;border-radius:6px;"
        "background:#1a1530;border:1px solid #7c6cf0;color:#cbc4ff;"
        "font-size:12px;font-weight:600}"
        ".panel{border-top:1px solid var(--border);background:var(--surface);"
        "position:relative}"
        ".panel.minimized .pin{display:none}"
        # ── v6 Wave 3: maximize (▢) toggle — fills the cockpit viewport. A
        # .panel.maxd is lifted out of the stacked column to a fixed full-screen
        # overlay (high z-index) and restored on a second click. Its body stretches
        # to use the height so the terminal re-fits to the larger area.
        ".panel.maxd{position:fixed;top:0;left:0;right:0;bottom:0;z-index:9000;"
        "margin:0;border:0;overflow:auto;display:flex;flex-direction:column}"
        ".panel.maxd .pin{flex:1;resize:none;width:auto;max-width:none;"
        "min-height:0}"
        ".panel.maxd .tpane{flex:1}"
        ".panel .pbar{display:flex;align-items:center;gap:9px;padding:9px 16px;"
        "background:var(--surface2);border-bottom:1px solid var(--border)}"
        ".panel .pbar .ic{font-size:14px}"
        ".panel .pbar .ti{font-size:13px;font-weight:700;white-space:nowrap;"
        "overflow:hidden;text-overflow:ellipsis}"
        ".panel .pbar .mt{color:var(--text-dim);font-size:11px}"
        # v8 Wave 4 — the loaded-skill chip ("planning · Crucible", etc.).
        ".panel .pbar .skl{font-size:10px;color:var(--accent);"
        "background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.35);"
        "border-radius:10px;padding:1px 8px;white-space:nowrap;"
        "text-transform:uppercase;letter-spacing:.4px}"
        ".panel .pbar .sp{flex:1}"
        # Panel body STACKS: split summary on top, full-width terminal below.
        # v6 Wave 3: the body is the FREE-resize box (resize:both) so dragging the
        # panel's bottom-right corner resizes the whole panel — width AND height,
        # not just the terminal sub-pane. Size persists per session (_panelRects).
        ".panel .pin{padding:15px 18px;display:flex;flex-direction:column;gap:13px;"
        "resize:both;overflow:auto;min-height:160px;min-width:360px;max-width:100%}"
        ".panel .panel-body{min-height:60px}"
        ".panelbtn{width:22px;height:20px;line-height:18px;text-align:center;"
        "border-radius:5px;border:1px solid var(--border);background:var(--surface);"
        "color:var(--text-dim);cursor:pointer;font-size:12px;padding:0}"
        ".panelbtn:hover{color:var(--text);border-color:var(--accent)}"
        # v6 Wave 3: the maximize (▢) toggle. When the panel is maxd the button
        # shows its 'active' accent so it reads as a toggle.
        ".panelbtn.max:hover{color:var(--text);border-color:var(--accent)}"
        ".panel.maxd .panelbtn.max{color:var(--accent);border-color:var(--accent)}"
        # v5 Wave 1: the panel header carries THREE distinct controls —
        #   .min   '–'  minimize (keeps the session running)
        #   .close '×'  CLOSE-to-tile (tears down the panel DOM only; the session
        #               record + lane tile persist; reopenable). NON-destructive.
        #   .hardkill '🗑' KILL (confirm-gated → term_kill → reap PTY + worktree +
        #               drop the tile). Visually distinct (danger glyph/color).
        ".panelbtn.close:hover{color:var(--text);border-color:var(--accent)}"
        ".panelbtn.hardkill{color:var(--danger);border-color:var(--border)}"
        ".panelbtn.hardkill:hover{color:#fff;background:var(--danger);"
        "border-color:var(--danger)}"
        # v9 Wave 1: the TRUE-DELETE control (red '✕'). Visually + behaviorally
        # DISTINCT from .hardkill (🗑): delete removes the session record entirely
        # (kill only ends a running session). Always-on danger border + bold red
        # glyph, separated from the other controls, filling solid red on hover.
        ".panelbtn.delete{color:#fff;background:var(--danger);"
        "border-color:var(--danger);font-weight:700;margin-left:6px}"
        ".panelbtn.delete:hover{color:var(--danger);background:transparent;"
        "border-color:var(--danger)}"
        # Legacy alias retained so any old reference to .kill still styles as danger.
        ".panelbtn.kill:hover{color:var(--danger);border-color:var(--danger)}"
        # v5 Wave 1: the live-session bar (reopenable chips for LIVE managed
        # sessions that aren't server-rendered board tiles). Empty → no height.
        ".live-session-bar{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}"
        ".live-session-bar:empty{margin:0}"
        ".live-chip{display:inline-flex;align-items:center;gap:6px;"
        "padding:4px 10px;border-radius:14px;cursor:pointer;font-size:12px;"
        "background:var(--surface2);border:1px solid var(--border)}"
        ".live-chip:hover{border-color:var(--accent)}"
        ".live-chip .ttl{font-weight:600}"
        # v6 Wave 4: a FINISHED (done/failed) tile renders greyed (.done) with a
        # ✓ check; it's still clickable (reopens its read-only summary panel).
        ".live-chip.done{opacity:.72}"
        ".live-chip .ck{color:#22c55e;font-size:11px;margin-left:2px}"
        # "previously done (N)" expander: older finished sessions in a lane tuck
        # under this small collapsible cluster so the row stays tidy.
        ".live-session-bar .prevdone{display:inline-flex;align-items:center}"
        ".live-session-bar .prevdone>summary{cursor:pointer;font-size:11px;"
        "color:var(--text-dim);list-style:none;padding:4px 8px;border-radius:14px;"
        "border:1px dashed var(--border);user-select:none}"
        ".live-session-bar .prevdone>summary:hover{color:var(--text);"
        "border-color:var(--accent)}"
        ".live-session-bar .prevdone[open]>summary{color:var(--text)}"
        ".live-session-bar .prevdone-tiles{display:inline-flex;flex-wrap:wrap;"
        "gap:8px;margin-left:8px}"
        # Per-session engine toggle in the panel bar (◆ Claude / ✦ Gemini). Chosen
        # once; flipping POSTs term_set_engine to relaunch this session on the other
        # engine in the SAME worktree (mockup Paradigm-2 panel header).
        ".panel .pbar .englbl{font-size:10px;color:var(--text-dim);"
        "margin-left:4px}"
        ".engtog{display:inline-flex;border:1px solid var(--border);"
        "border-radius:7px;overflow:hidden}"
        ".engtog b{font-size:10.5px;padding:3px 9px;background:var(--surface);"
        "color:var(--text-dim);cursor:pointer;font-weight:500}"
        ".engtog b.on{background:rgba(34,197,94,.15);color:var(--success);"
        "font-weight:700}"
        # ── v4 Wave 5: split summary — materials LEFT, role links RIGHT, both
        # columns filling EQUAL vertical height (mockup Paradigm-2 internals).
        # The left effort line sinks to the bottom (.smat .effbar{margin-top:auto});
        # the right's second link group pins to the bottom (.slinks .slh.two).
        # v6 Wave 9 (polish 2): the summary block keeps its NATURAL height at the
        # top of the .pin flex column (flex:0 0 auto) so the terminal pane below it
        # (flex:1 1 auto) absorbs all the extra height when the panel is dragged
        # taller — growing terminal ROWS, not the summary.
        ".panel .summary{font-size:12px;flex:0 0 auto}"
        ".panel .summary.split{display:grid;grid-template-columns:1.5fr 1fr;"
        "gap:20px;align-items:stretch}"
        ".panel .summary .smat{min-width:0;display:flex;flex-direction:column}"
        ".panel .summary .smat .sgoal{font-size:13px;color:var(--text);"
        "margin-bottom:10px}"
        ".panel .summary .smat .row{display:flex;gap:10px;font-size:12px;"
        "margin-bottom:7px}"
        ".panel .summary .smat .row .k{color:var(--text-dim);min-width:92px;"
        "flex-shrink:0}"
        ".panel .summary .smat .effbar{font-size:11px;color:var(--text-dim);"
        "margin-top:auto}"
        # v5 Wave 4 — a BUILD panel's resolved deliverable (a link) or honest
        # "none yet" placeholder.
        ".panel .summary .smat .bdeliv{display:flex;gap:10px;align-items:center;"
        "font-size:12px;margin-bottom:9px}"
        ".panel .summary .smat .bdeliv .k{color:var(--text-dim);min-width:92px;"
        "flex-shrink:0}"
        ".panel .summary .smat .bdeliv .doc{display:inline-flex;gap:6px;"
        "align-items:center;font-size:11.5px;padding:3px 10px;border-radius:7px;"
        "border:1px solid var(--border);background:var(--surface);"
        "color:var(--text);text-decoration:none}"
        ".panel .summary .smat .bdeliv .doc:hover{border-color:var(--accent)}"
        ".panel .summary .smat .bdeliv .doc .role{font-size:9.5px;"
        "color:var(--text-dim)}"
        ".panel .summary .smat .bdeliv.none{color:var(--warning);"
        "font-style:italic}"
        ".panel .summary .slinks{border-left:1px solid var(--border);"
        "padding-left:18px;display:flex;flex-direction:column}"
        ".panel .summary .slinks .slh{font-size:10px;text-transform:uppercase;"
        "letter-spacing:1px;color:var(--text-dim);margin:0 0 8px}"
        ".panel .summary .slinks .slh.two{margin-top:auto}"
        ".panel .summary .slinks .doc{display:flex;width:100%;margin-bottom:6px;"
        "align-items:center;gap:6px;font-size:11.5px;padding:4px 10px;"
        "border-radius:7px;border:1px solid var(--border);background:var(--surface);"
        "color:var(--text);text-decoration:none}"
        ".panel .summary .slinks .doc:hover{border-color:var(--accent)}"
        ".panel .summary .slinks .doc .role{margin-left:auto;font-size:9.5px;"
        "color:var(--text-dim)}"
        ".panel .summary .summ-loading{color:var(--text-dim);font-style:italic}"
        # ── v4 Wave 5: full-width terminal pane BELOW the summary, VERTICALLY
        # RESIZABLE (drag the bottom edge; the JS fits + term_resize on resize).
        # v6 Wave 9 (polish 2): the terminal pane FLEXES to fill the panel body's
        # remaining vertical space (flex:1 1 auto) instead of a fixed height, so
        # dragging the .pin panel taller grows the TERMINAL (more rows) — not the
        # summary scroll area. A min-height keeps it usable at the panel's natural
        # (un-resized) height; it still has its own bottom-edge handle
        # (resize:vertical) for a terminal-only nudge. The .pin flex column (below)
        # is what distributes the height.
        ".panel .tpane{background:#05070c;border:1px solid var(--border);"
        "border-radius:8px;overflow:hidden;resize:vertical;"
        "flex:1 1 auto;min-height:200px;display:flex;flex-direction:column}"
        ".panel .tpane .tbar{display:flex;align-items:center;gap:8px;"
        "padding:5px 9px;background:#11141c;border-bottom:1px solid var(--border)}"
        ".panel .tpane .tbar .lab{font-size:11px;color:var(--text-dim)}"
        ".panel .tpane .tbar .rzhint{font-size:10px;color:var(--text-dim);"
        "margin-left:auto}"
        ".panel .tpane .term-host{background:#05070c;flex:1;overflow:auto;"
        "min-height:90px}"
        ".panel .tpane .ro-note{color:var(--text-dim);font-size:12px;"
        "font-family:ui-monospace,Consolas,monospace;padding:11px 13px}"
        # v5 Wave 2 — past-session read-only view (skill/prompts/files + Continue).
        ".panel .tpane .ro-past{padding:11px 13px;font-size:12px;"
        "color:var(--text);overflow:auto}"
        ".panel .tpane .ro-actions{margin-bottom:9px}"
        ".panel .tpane .ro-continue{background:#1f6feb;color:#fff;border:0;"
        "border-radius:6px;padding:6px 12px;font-size:12px;cursor:pointer;"
        "font-weight:600}"
        ".panel .tpane .ro-continue:hover{background:#388bfd}"
        ".panel .tpane .ro-sec{display:flex;gap:10px;margin-top:8px;"
        "font-size:12px}"
        ".panel .tpane .ro-sec .ro-k{color:var(--text-dim);min-width:92px;"
        "font-weight:600}"
        ".panel .tpane .ro-list{margin:3px 0 4px 0;padding-left:20px;"
        "color:var(--text-dim);font-size:11.5px}"
        ".panel .tpane .ro-list li{margin:2px 0}"
        # v6 Wave 5 — "Advance to Planning →" bar (research panels) + the chain
        # breadcrumb (panel header). The advance bar is the mockup Step-3 green
        # control; the breadcrumb is a row of clickable chain nodes.
        # The advance / finish bars keep their natural height in the .pin flex
        # column (flex:0 0 auto) so they never steal vertical space from the
        # flexing terminal pane (v6 Wave 9 polish 2).
        ".panel .pin .advbar{display:flex;align-items:center;gap:10px;"
        "flex:0 0 auto;flex-wrap:wrap;padding:9px 11px;border-radius:8px;"
        "border:1px solid rgba(34,197,94,.4);background:rgba(34,197,94,.07)}"
        ".panel .pin .advbar .advt{font-size:11.5px;color:var(--text-dim)}"
        ".panel .pin .advbar .advt b{color:#bff3cf}"
        ".panel .pin .advbar .advbtn{margin-left:auto;font-size:12px;"
        "padding:6px 13px;border-radius:7px;border:1px solid rgba(34,197,94,.55);"
        "background:rgba(34,197,94,.14);color:#cdf5d8;cursor:pointer;"
        "font-weight:600}"
        ".panel .pin .advbar .advbtn:hover{background:rgba(34,197,94,.26)}"
        # v6 Wave 9 (polish 1): the planning "Finish → Build" bar. Same Step-3 green
        # control family as the research advance bar (distinct class so it does not
        # collide with the research-only advance-bar gate/assertions).
        ".panel .pin .fbbar{display:flex;align-items:center;gap:10px;"
        "flex:0 0 auto;flex-wrap:wrap;padding:9px 11px;border-radius:8px;"
        "border:1px solid rgba(34,197,94,.4);background:rgba(34,197,94,.07)}"
        ".panel .pin .fbbar .fbt{font-size:11.5px;color:var(--text-dim)}"
        ".panel .pin .fbbar .fbt b{color:#bff3cf}"
        ".panel .pin .fbbar .fbbtn{margin-left:auto;font-size:12px;"
        "padding:6px 13px;border-radius:7px;border:1px solid rgba(34,197,94,.55);"
        "background:rgba(34,197,94,.14);color:#cdf5d8;cursor:pointer;"
        "font-weight:600}"
        ".panel .pin .fbbar .fbbtn:hover{background:rgba(34,197,94,.26)}"
        ".panel .pin .fbbar .fbnote{margin-left:auto;font-size:11px;"
        "color:var(--text-dim);font-style:italic}"
        ".panel .pbar .chaincrumb{display:inline-flex;align-items:center;gap:4px;"
        "flex-wrap:wrap;font-size:11px}"
        ".panel .pbar .chaincrumb .cc-sep{color:var(--accent);font-weight:700}"
        ".panel .pbar .chaincrumb .cc-node{color:var(--accent);cursor:pointer;"
        "display:inline-flex;align-items:center;gap:4px;"
        "padding:1px 6px;border-radius:5px;border:1px solid transparent}"
        ".panel .pbar .chaincrumb .cc-node:hover{border-color:var(--accent)}"
        # v8 Wave 7: a per-node status light (locked color map) — live=green,
        # done=amber, failed=red, idle/historical=grey — so each chain node's
        # state is visible at a glance, not only on hover.
        ".panel .pbar .chaincrumb .cc-node .cc-light{width:7px;height:7px;"
        "border-radius:50%;display:inline-block;flex-shrink:0;"
        "background:var(--text-dim)}"
        ".panel .pbar .chaincrumb .cc-node .cc-light.green{background:#22c55e}"
        ".panel .pbar .chaincrumb .cc-node .cc-light.amber{background:#fbbf24}"
        ".panel .pbar .chaincrumb .cc-node .cc-light.red{background:#f87171}"
        ".panel .pbar .chaincrumb .cc-node .cc-light.grey{background:#8b8f9a;"
        "opacity:.6}"
        ".panel .pbar .chaincrumb .cc-node.cur{color:var(--text);"
        "border-color:var(--border);background:var(--surface)}"
        "</style></head><body>"
        f"<p><a href='/'>&larr; Back to dashboard</a></p>"
        f"<div class='dash' data-notes='{notes_attr}' data-blurb='{blurb_attr}'>"
        # ── Lifecycle header ──
        "<div class='dhead'>"
        f"<span class='name'>{name}</span>"
        f"<span class='path'>{folder}</span>"
        # v4 Wave 5: the per-project cost/tokens/time rollup beside the path,
        # with a lifetime/30-day toggle (run-session-only totals).
        f"{header_rollup}"
        "<div class='right'>"
        f"<span class='pri p{pr}'>P{pr}</span>"
        f"<span class='chip{' active' if is_active else ''}'>{state}</span>"
        # v7 Wave 4 (#4): "Open terminal" — start a BARE general session (no trio
        # skill seed) via the existing newTermSession path. It opens an inline
        # panel + a top-strip chip like any live session and carries the per-panel
        # Claude/Gemini engine toggle. It is NOT a board lane column (John's choice
        # B) and never auto-advances. Defaults to Claude; the panel toggle switches.
        "<button class='rnd-mini rnd-accent' id='openTermBtn' "
        "onclick=\"newTermSession('general','claude')\">"
        "&#9000; Open terminal</button>"
        # v10 Wave 7 (#3): "Boneyard" — open the per-project searchable list of
        # DISCARDED material (hard-killed-w/-material + v9-deleted + deleted-grass
        # ideas). Opens an inline panel in #panelStack (like the grass workbench);
        # read-only (GET /api/rnd/boneyard); docs open via the safe /artifact route.
        "<button class='rnd-mini' id='openBoneyardBtn' "
        "onclick=\"openBoneyard()\" title='Discarded material (searchable)'>"
        "&#9760; Boneyard</button>"
        # v8 Wave 3: GitHub link + Option-A auto-push controls. Rendered EMPTY and
        # populated on load by renderRemoteControls() from GET /api/rnd/remote_status
        # (a token-gated read). Unlinked → a "Link GitHub" button (linkGithub());
        # linked → the remote shown + an auto-push opt-in toggle (set_auto_push) +
        # a "Push now" button (push_now). Default new repos are PRIVATE.
        "<span class='gh-remote' id='ghRemote'></span>"
        f"{lifecycle}"
        "</div></div>"
        # ── Project OBJECTIVE (v5 Wave 3 — cached, validated; read-only) ──
        + (f"<div class='proj-objective' data-objective='1' "
           f"style='padding:8px 18px;border-bottom:1px solid var(--border);"
           f"font-size:13px;color:var(--text)'>"
           f"<b style='color:var(--accent)'>Objective:</b> {objective_esc}</div>"
           if objective_raw else "")
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
        # ── Paradigm-2 lane board (.p2lanes → 5 .p2col tile columns) ──
        # v7 Wave 6: wrap in a stable #kanbanBoard container so refreshBoard()
        # can swap the server-rendered board fragment in place (instant-in-column
        # tile after a session-lifecycle mutation) without a full page reload.
        f"<div id='kanbanBoard'>{kanban}</div>"
        # ── Paradigm-2 inline PANEL STACK ──
        # Clicking ANY lane tile (live OR historical) expands a full-width inline
        # panel here, stacking down the page (NOT a floating window, NOT page nav).
        # Each panel = a split summary on top (materials + role-links) + a
        # full-width terminal pane below (live xterm for a running session; a
        # read-only "session complete" note for a done/historical one). The panel
        # bar carries the engine ◆Claude/✦Gemini toggle (term_set_engine), a
        # minimize, and a kill (× confirm). No old console drawer / live-terminals
        # bar / loose cost-rollup / loose deliverables-pinned section remains.
        # v5 Wave 1: a thin LIVE-session bar above the panel stack. A live managed
        # terminal session (started via "+ new <lane>") is NOT a server-rendered
        # board tile, so close-to-tile would otherwise leave no reopen vector. The
        # session bar renders one clickable chip per LIVE managed session — closing
        # its panel keeps the chip (reopenable); hard-kill removes it. (No-op /
        # empty when there are no live sessions; populated by renderSessionBar.)
        "<div class='live-session-bar' id='sessionBar'></div>"
        "<div class='panel-stack' id='panelStack'></div>"
        # v10 Wave 7: the Boneyard panel template (hidden; cloned into #panelStack
        # by openBoneyard()).
        + boneyard_tpl +
        # ── Linked tasks strip (kept compact) ──
        f"<div class='taskstrip'>{tasks_html}</div>"
        "</div>"
        # Visible build/version stamp so new-vs-cached is unmistakable at a glance.
        f"<p style='color:#8a90a2;font-size:12px'>"
        f"<b style='color:#22c55e'>Project Cockpit</b> (v4.1 · Paradigm 2) "
        f"&bull; build {html_lib.escape(BUILD_ID)} &bull; instance "
        f"{html_lib.escape(inst['instance_id'])}</p>"
        # Vendored REAL xterm.js (defines window.Terminal) — the cockpit panel JS
        # instantiates an xterm.js Terminal directly over the v3 WS/SSE transport.
        f"<script src='{XTERM_URL_PREFIX}/xterm.js'></script>"
        "<script>\n"
        f"var PROJECT_ID = {pid_js};\n"
        # v10 Wave 5 (DEFECT-2 fix): the [grass-dev] label marker, injected from
        # the single Python constant so the JS top-strip filter can't drift from
        # ``effort_history.is_grass_dev_label``.
        f"var GRASS_DEV_LABEL_PREFIX = {json.dumps(_eh.GRASS_DEV_LABEL_PREFIX)};\n"
        f"window.ANCHOR_AUTH_REQUIRED = {'true' if _paths.expected_token() else 'false'};\n"
        + _PROJECT_WINDOW_JS +
        "</script>"
        "<script>" + cache_bust_script() + "</script>"
        "</body></html>"
    )


# JS for the v4.1 "Project Cockpit" (Paradigm-2). Drives ONLY: the inline
# expanding panel stack (openPanel/minimize/kill + the xterm transport for live
# sessions, a read-only note for historical ones), the per-panel engine toggle
# (term_set_engine), the lane-tile click (laneTileClick → openPanel), the lane
# launchers (newTermSession → term_start), the grass idea board (add/promote),
# type-aware deliverable launch, the lifecycle header, and the header rollup
# toggle. NO console drawer / live-terminals bar / loose rollup or deliverables
# section remain. Plain RAW string (NOT an f-string), so braces are single. No
# template interpolation here beyond the PROJECT_ID var injected above.
_PROJECT_WINDOW_JS = r"""
// ════════════════════════════════════════════════════════════════════════════
// v4.1 "Project Cockpit" — Paradigm-2 (inline expanding panels). The ONLY
// terminal surface is the inline panel inside #panelStack (openPanel). There is
// NO console drawer, NO live-terminals bar, NO loose cost-rollup / deliverables
// section — those v3 leftovers were removed. Plain RAW string (single braces).
// ════════════════════════════════════════════════════════════════════════════

function _esc(s) {
  // FULL HTML escaping (defense-in-depth). Escapes &, <, > AND BOTH quote chars
  // (" -> &quot;, ' -> &#39;) so output is safe inside double- OR single-quoted
  // attributes — not just text nodes. (Pre-v10-W7-fix this escaped only & < >,
  // which let a title/value containing a double-quote break out of a
  // data-title="..." attribute → stored DOM XSS in the Boneyard live search.)
  // Verified safe for every _esc(...) caller in _PROJECT_WINDOW_JS: each puts the
  // result into HTML text content or a quoted attribute, never a JS-string/URL
  // context where &quot;/&#39; would render literally wrong.
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

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
// On first load: ask for a token once if required, then sync MANAGED from the
// session registry so a tile for an already-running terminal can re-open its
// inline panel.
window.addEventListener('DOMContentLoaded', function () {
  if (window.ANCHOR_AUTH_REQUIRED && !_anchorToken()) { setAnchorToken(); }
  repopulate();
  // v8 Wave 3: render the GitHub link / auto-push header controls from the
  // current remote_status (read-only GET; never a model call / network).
  try { renderRemoteControls(); } catch (e) {}
  // v10 Wave 4 FIX 2/3: resolve the board-tile "from grass" chips (label +
  // dead-state) once the grass data is loaded (read-only GET). Best-effort.
  try {
    _loadGrassData().then(function () {
      try { _resolveGrassOriginChips(document); } catch (e) {}
    });
  } catch (e) {}
});
function _postJson(url, payload) {
  var headers = {'Content-Type': 'application/json'};
  var tok = _anchorToken();
  if (tok) headers['X-Anchor-Token'] = tok;
  return fetch(url, { method: 'POST', headers: headers, body: JSON.stringify(payload) });
}
function _isUnauthorized(r, data) { return r.status === 401 || (data && data.error === 'unauthorized'); }

// ── v8 Wave 3 — GitHub link + Option-A auto-push (header controls) ───────────
// renderRemoteControls(): fetch the project's current remote_status (read-only,
// token-gated GET) and paint the #ghRemote header span. Unlinked → a single
// "Link GitHub" button. Linked → the remote host/name + an auto-push opt-in
// checkbox (set_auto_push) + a "Push now" button (push_now). NO network here —
// this is a pure registry read. Never throws into the page (best-effort).
async function renderRemoteControls() {
  var host = document.getElementById('ghRemote');
  if (!host) return;
  var st = null;
  try {
    var url = '/api/rnd/remote_status?project_id=' +
      encodeURIComponent(PROJECT_ID) + _tokenQ();
    var r = await fetch(url, _jsonHdrs());
    st = await r.json();
  } catch (e) { st = null; }
  if (!st || !st.ok) {
    // Unknown state → still offer the link control (best-effort).
    host.innerHTML = "<button class='rnd-mini' id='ghLinkBtn' " +
      "onclick='linkGithub()'>&#128279; Link GitHub</button>";
    return;
  }
  if (!st.linked) {
    host.innerHTML = "<button class='rnd-mini' id='ghLinkBtn' " +
      "onclick='linkGithub()'>&#128279; Link GitHub</button>";
    return;
  }
  // Linked: show a short remote label + the auto-push toggle + Push now.
  var label = _ghShortRemote(st.remote_url);
  var checked = st.auto_push ? ' checked' : '';
  host.innerHTML =
    "<span class='gh-linked' id='ghLinkedLabel' title='" + _esc(st.remote_url) +
      "'>&#128279; " + _esc(label) + "</span>" +
    "<label class='gh-autopush' title='Auto-push this project when a session " +
      "finishes'><input type='checkbox' id='ghAutoPush'" + checked +
      " onchange='toggleAutoPush(this.checked)'> auto-push</label>" +
    "<button class='rnd-mini' id='ghPushNowBtn' onclick='pushNow()'>" +
      "&#8593; Push now</button>";
}

// Trim a remote URL to a compact "owner/name" (or host/name) for the header.
function _ghShortRemote(u) {
  u = String(u || '');
  if (!u) return 'linked';
  var s = u.replace(/^https?:\/\//, '').replace(/^git@/, '')
           .replace(/\.git$/, '').replace(/:/g, '/');
  var parts = s.split('/').filter(function (p) { return p; });
  if (parts.length >= 2) return parts.slice(-2).join('/');
  return s;
}

// linkGithub(): inline prompt to link a GitHub remote. If gh is available we
// offer "Create new private repo" (mode=create) vs "Paste an existing URL"
// (mode=existing); when gh is unavailable we offer paste-only (the server also
// degrades create → {reason:'gh-unavailable', suggest:'paste-url'}).
async function linkGithub() {
  // Probe current state so we can decide whether to offer "create".
  var ghAvailable = true;
  try {
    var sr = await fetch('/api/rnd/remote_status?project_id=' +
      encodeURIComponent(PROJECT_ID) + _tokenQ(), _jsonHdrs());
    var sd = await sr.json();
    if (sd && typeof sd.gh_available === 'boolean') ghAvailable = sd.gh_available;
  } catch (e) {}
  var mode, value;
  if (ghAvailable) {
    var pick = window.prompt(
      'Link GitHub — type:\n  C = Create a new PRIVATE repo\n' +
      '  (or paste an existing repo URL)\n  (Cancel = not now)', 'C');
    if (pick === null) return;            // not now
    pick = (pick || '').trim();
    if (pick.toUpperCase() === 'C' || pick === '') {
      mode = 'create';
      var nm = window.prompt('New private repo name (blank = folder name):', '');
      if (nm === null) return;
      value = (nm || '').trim();
    } else {
      mode = 'existing';
      value = pick;
    }
  } else {
    // gh unavailable → paste-only.
    var url = window.prompt(
      'gh is unavailable — paste an existing GitHub repo URL to link:', '');
    if (url === null) return;
    url = (url || '').trim();
    if (!url) return;
    mode = 'existing';
    value = url;
  }
  var payload = {project_id: PROJECT_ID, mode: mode, value: value};
  var r, data;
  try {
    r = await _postJson('/api/rnd/link_github', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/link_github', payload);
      data = await r.json();
    }
  } catch (e) { alert('[link GitHub error] ' + e.message); return; }
  if (!data.ok) {
    if (data.reason === 'gh-unavailable') {
      // Fall back to paste-only on the spot.
      var url2 = window.prompt(
        'gh is unavailable — paste an existing GitHub repo URL to link:', '');
      if (url2 === null) return;
      url2 = (url2 || '').trim();
      if (!url2) return;
      var p2 = {project_id: PROJECT_ID, mode: 'existing', value: url2};
      var r2 = await _postJson('/api/rnd/link_github', p2);
      var d2 = await r2.json();
      if (!d2.ok) { alert('[link GitHub refused] ' + (d2.error || d2.reason || 'unknown')); return; }
    } else {
      alert('[link GitHub refused] ' + (data.error || data.reason || 'unknown'));
      return;
    }
  }
  renderRemoteControls();
}

// toggleAutoPush(on): persist the per-project auto-push opt-in (set_auto_push).
async function toggleAutoPush(on) {
  var payload = {project_id: PROJECT_ID, enabled: !!on};
  var r, data;
  try {
    r = await _postJson('/api/rnd/set_auto_push', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/set_auto_push', payload);
      data = await r.json();
    }
  } catch (e) { alert('[auto-push error] ' + e.message); return; }
  if (!data.ok) {
    alert('[auto-push refused] ' + (data.error || 'unknown'));
    renderRemoteControls();             // re-sync the checkbox to truth
  }
}

// pushNow(): manual "Push now" — git push -u origin <branch>. In tests origin is
// a LOCAL BARE repo (file://) so there is NO network. Reports the outcome.
async function pushNow() {
  var btn = document.getElementById('ghPushNowBtn');
  if (btn) { btn.disabled = true; btn.textContent = 'Pushing…'; }
  var payload = {project_id: PROJECT_ID};
  var r, data;
  try {
    r = await _postJson('/api/rnd/push_now', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/push_now', payload);
      data = await r.json();
    }
  } catch (e) {
    alert('[push error] ' + e.message);
    if (btn) { btn.disabled = false; btn.innerHTML = '&#8593; Push now'; }
    return;
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '&#8593; Push now'; }
  if (!data.ok || !data.pushed) {
    alert('[push refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
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

// Promote a Grass Catcher idea into a NEW seeded session in a lane (Wave 6).
// POST /api/rnd/promote_grass {project_id, idea_id, lane} → the backend starts a
// session SEEDED with the idea text (reusing the Wave-1 seed path); we then
// register it in MANAGED and open its inline panel (reusing openPanel/repopulate).
// The idea REMAINS in grass (copy, never destroy).
async function promoteGrass(ideaId, lane) {
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, lane: lane};
  var r, data;
  try {
    r = await _postJson('/api/rnd/promote_grass', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/promote_grass', payload);
      data = await r.json();
    }
  } catch (e) { alert('[promote grass error] ' + e.message); return; }
  if (!data.ok || !data.session) {
    alert('[promote refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || lane, backend: rec.backend || 'claude',
    status: rec.status || 'running', label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] = (_laneCounters[rec.lane || lane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  // v7 Wave 6: re-fetch the server-rendered board so the just-started session's
  // lane-column tile appears INSTANTLY (no page reload). The board is the single
  // source of truth — re-fetch, don't JS-inject — so dedupe stays correct.
  refreshBoard();
  // Re-sync indices/labels from the registry shortly after.
  setTimeout(repopulate, 600);
}

// ── v10 Wave 7 — Boneyard (per-project searchable discard list) ─────────────
// The header "Boneyard" button opens a FULL-WIDTH panel in #panelStack (cloned
// from #boneyardTpl, the server-rendered search box + entry list). Live search
// re-fetches GET /api/rnd/boneyard?q=<term> (so it exercises boneyard.search) and
// re-renders the list; each entry expands to its summary + doc links (opened via
// the safe /artifact route). Read-only — no mutation, no model call.
function _boneyardTokenQ() {
  var t = _anchorToken();
  return t ? ('&token=' + encodeURIComponent(t)) : '';
}

function openBoneyard() {
  var stack = document.getElementById('panelStack');
  var tpl = document.getElementById('boneyardTpl');
  if (!stack || !tpl) return;
  var existing = document.getElementById('boneyardPanel');
  if (existing) {
    if (existing.classList.contains('minimized')) existing.classList.remove('minimized');
    existing.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    return;
  }
  var panel = document.createElement('div');
  panel.className = 'panel';
  panel.id = 'boneyardPanel';
  var bar = document.createElement('div');
  bar.className = 'pbar';
  var title = document.createElement('span');
  title.className = 'ti';
  title.textContent = '☠ Boneyard — discarded material';
  var sp = document.createElement('span');
  sp.className = 'sp';
  var minBtn = document.createElement('button');
  minBtn.className = 'panelbtn min';
  minBtn.title = 'Minimize';
  minBtn.textContent = '–';
  minBtn.onclick = function (e) { e.stopPropagation(); panel.classList.add('minimized'); };
  var closeBtn = document.createElement('button');
  closeBtn.className = 'panelbtn close';
  closeBtn.title = 'Close';
  closeBtn.textContent = '×';
  closeBtn.onclick = function (e) { e.stopPropagation(); panel.remove(); };
  bar.appendChild(title); bar.appendChild(sp);
  bar.appendChild(minBtn); bar.appendChild(closeBtn);
  var pin = document.createElement('div');
  pin.className = 'pin';
  pin.innerHTML = tpl.innerHTML;        // clone the rendered boneyard markup
  panel.appendChild(bar); panel.appendChild(pin);
  stack.appendChild(panel);
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

// Build ONE entry's DOM from a server entry view (the SAFE projection + doc_links).
function _boneyardEntryHtml(e) {
  var src = e.source || '';
  var srcLbl = e.source_label || src || '';
  var title = e.title || '(untitled)';
  var body = ((e.summary_excerpt || '').trim()) || ((e.idea_text || '').trim());
  var excerpt = body ? body.split('\n')[0] : '';
  // Use the server-computed, LOCAL-tz when_display verbatim (the SAME string the
  // server initial render emits) so the displayed time is byte-identical across
  // the initial paint and this live-search re-render. (Pre-fix this re-formatted
  // e.when in UTC via toISOString → a ~tz-offset jump the instant a user searched.)
  var whenTxt = e.when_display || '';

  var laneChip = e.lane ? ('<span class="bylanechip">' + _esc(e.lane) + '</span>') : '';
  var whenChip = whenTxt ? ('<span class="bywhen">' + _esc(whenTxt) + '</span>') : '';
  var excHtml = excerpt ? ('<div class="byexc">' + _esc(excerpt) + '</div>') : '';
  var sumHtml = body
    ? ('<div class="bysum">' + _esc(body) + '</div>')
    : ('<div class="bysum dim">No summary captured.</div>');
  var docsInner = '';
  var links = e.doc_links || [];
  if (links.length) {
    for (var i = 0; i < links.length; i++) {
      docsInner += '<a class="bydoc" href="' + _esc(links[i].href)
        + '" target="_blank" rel="noopener">' + _esc(links[i].name) + '</a>';
    }
  } else {
    docsInner = '<span class="none">No documents.</span>';
  }
  var docsHtml = '<div class="bydocs"><div class="h">Documents</div>' + docsInner + '</div>';
  return '<div class="byentry" data-byentry="' + _esc(e.entry_id || '')
    + '" data-source="' + _esc(src) + '" data-title="' + _esc(title)
    + '" onclick="toggleBoneyardEntry(this)">'
    + '<div class="byhd"><span class="bybadge ' + _esc(src) + '">' + _esc(srcLbl)
    + '</span><div class="bymeta"><div class="bytitle">' + _esc(title) + '</div>'
    + excHtml + '</div>' + laneChip + whenChip + '<span class="bycar">&#9656;</span></div>'
    + '<div class="bybody" onclick="event.stopPropagation()">' + sumHtml + docsHtml + '</div>'
    + '</div>';
}

// Toggle one entry's expanded (summary + doc links) state.
function toggleBoneyardEntry(el) {
  if (!el) return;
  el.classList.toggle('open');
}

// Live search: re-fetch GET /api/rnd/boneyard?q=<term> (exercises boneyard.search)
// and re-render the list newest-first. Debounced lightly. An empty result shows
// the honest empty state (no fabricated rows).
var _boneyardSearchTimer = null;
function searchBoneyard() {
  if (_boneyardSearchTimer) clearTimeout(_boneyardSearchTimer);
  _boneyardSearchTimer = setTimeout(_doBoneyardSearch, 120);
}
async function _doBoneyardSearch() {
  var panel = document.getElementById('boneyardPanel');
  if (!panel) return;
  var box = panel.querySelector('#boneyardSearch');
  var list = panel.querySelector('#boneyardList');
  if (!list) return;
  var q = box ? (box.value || '').trim() : '';
  try {
    var r = await fetch('/api/rnd/boneyard?project_id=' + encodeURIComponent(PROJECT_ID)
                        + '&q=' + encodeURIComponent(q) + _boneyardTokenQ());
    var data = await r.json();
    if (!data || !data.ok) return;
    var entries = data.entries || [];
    if (!entries.length) {
      list.innerHTML = '<div class="byempty" data-byempty="1">'
        + (q ? 'No discarded material matches &ldquo;' + _esc(q) + '&rdquo;.'
             : 'Nothing discarded yet.') + '</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < entries.length; i++) html += _boneyardEntryHtml(entries[i]);
    list.innerHTML = html;
  } catch (e) { /* read-only; leave the current list on a transient error */ }
}

// ── Grass B+C hybrid idea workbench (v5 Wave 5) ─────────────────────────────
// The grass lane column tile (.grass-tile) opens a FULL-WIDTH two-pane workbench
// panel in #panelStack (the column is too narrow for the two-pane workbench). The
// workbench markup is rendered server-side into #grassWorkbenchTpl and cloned in.
// Tabs + search scope the left list; selecting a .gli loads the right workbench;
// Develop starts a SEEDED live session in the workbench terminal; a saved
// refinement appears in the history (grass-<id>/dev-N) and is pullable.
var _grassEngine = 'claude';   // workbench engine toggle (research can use gemini)
var _grassData = {};            // idea_id -> idea record (from /api/rnd/grass)
var _grassDevSession = null;    // the active Develop session id (for Save refinement)
// v10 Wave 3 — per-(idea,lane) develop session id, so each of the TWO terminal
// hosts (research, plan) remembers its own LIVE session across collapse/expand.
// Key: ideaId + '::' + lane → session_id. A collapse never clears this (the
// session stays live); only switching ideas resets via selectGrassIdea.
var _grassLaneSession = {};

function openGrassWorkbench() {
  var stack = document.getElementById('panelStack');
  var tpl = document.getElementById('grassWorkbenchTpl');
  if (!stack || !tpl) return;
  var existing = document.getElementById('grassPanel');
  if (existing) {
    if (existing.classList.contains('minimized')) existing.classList.remove('minimized');
    existing.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    return;
  }
  var panel = document.createElement('div');
  panel.className = 'panel';
  panel.id = 'grassPanel';
  var bar = document.createElement('div');
  bar.className = 'pbar';
  var title = document.createElement('span');
  title.className = 'ti';
  title.textContent = '🌿 Grass Catcher — idea workbench';
  var sp = document.createElement('span');
  sp.className = 'sp';
  var minBtn = document.createElement('button');
  minBtn.className = 'panelbtn min';
  minBtn.title = 'Minimize';
  minBtn.textContent = '–';
  minBtn.onclick = function (e) { e.stopPropagation(); panel.classList.add('minimized'); };
  var closeBtn = document.createElement('button');
  closeBtn.className = 'panelbtn close';
  closeBtn.title = 'Close';
  closeBtn.textContent = '×';
  closeBtn.onclick = function (e) { e.stopPropagation(); panel.remove(); };
  bar.appendChild(title); bar.appendChild(sp);
  bar.appendChild(minBtn); bar.appendChild(closeBtn);
  var pin = document.createElement('div');
  pin.className = 'pin';
  pin.innerHTML = tpl.innerHTML;     // clone the rendered workbench markup
  panel.appendChild(bar); panel.appendChild(pin);
  stack.appendChild(panel);
  _wireGrassWorkbench(panel);
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  // Hydrate the idea data (status + refinements) for the right workbench.
  _loadGrassData();
}

function _wireGrassWorkbench(panel) {
  // Tabs: click sets the active filter and re-filters the list.
  var tabs = panel.querySelectorAll('.gtab');
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].onclick = (function (tab) {
      return function () {
        var all = panel.querySelectorAll('.gtab');
        for (var j = 0; j < all.length; j++) all[j].classList.remove('on');
        tab.classList.add('on');
        filterGrass();
      };
    })(tabs[i]);
  }
  // Rows: click selects the idea.
  var rows = panel.querySelectorAll('.gli');
  for (var k = 0; k < rows.length; k++) {
    rows[k].onclick = (function (row) {
      return function () { selectGrassIdea(row.getAttribute('data-idea')); };
    })(rows[k]);
  }
}

async function _loadGrassData() {
  try {
    var r = await fetch('/api/rnd/grass?project_id=' + encodeURIComponent(PROJECT_ID)
                        + _grassTokenQ());
    var data = await r.json();
    if (data && data.ok && data.ideas) {
      _grassData = {};
      for (var i = 0; i < data.ideas.length; i++) _grassData[data.ideas[i].idea_id] = data.ideas[i];
    }
  } catch (e) { /* read-only; workbench still works from row data */ }
  // v10 Wave 4 FIX 2/3: now that grass data is current, resolve any pending
  // board-tile "from grass" chips (label/dead-state). Idempotent.
  try { _resolveGrassOriginChips(document); } catch (e) {}
}
function _grassTokenQ() {
  var t = _anchorToken();
  return t ? ('&token=' + encodeURIComponent(t)) : '';
}

// filterGrass(): scope the left .gli list by the active status tab + the search box.
function filterGrass() {
  var panel = document.getElementById('grassPanel');
  if (!panel) return;
  var active = panel.querySelector('.gtab.on');
  var filter = active ? (active.getAttribute('data-filter') || 'all') : 'all';
  var sbox = panel.querySelector('.gsearch');
  var q = sbox ? (sbox.value || '').trim().toLowerCase() : '';
  var rows = panel.querySelectorAll('.gli');
  for (var i = 0; i < rows.length; i++) {
    var row = rows[i];
    var st = row.getAttribute('data-status') || 'raw';
    var ttl = (row.getAttribute('data-title') || '').toLowerCase();
    var okStatus = (filter === 'all') || (st === filter);
    var okSearch = !q || ttl.indexOf(q) !== -1;
    row.style.display = (okStatus && okSearch) ? '' : 'none';
  }
}

// selectGrassIdea(ideaId): load the chosen idea's RIGHT workbench (text +
// devbar + a terminal pane + refinement history). Marks the row selected.
function selectGrassIdea(ideaId) {
  var panel = document.getElementById('grassPanel');
  if (!panel) return;
  var rows = panel.querySelectorAll('.gli');
  var row = null;
  for (var i = 0; i < rows.length; i++) {
    rows[i].classList.remove('sel');
    if (rows[i].getAttribute('data-idea') === ideaId) { row = rows[i]; rows[i].classList.add('sel'); }
  }
  if (!row) return;
  var rec = _grassData[ideaId] || {};
  var title = (rec.title != null) ? rec.title : (row.getAttribute('data-title') || '');
  var status = rec.status || row.getAttribute('data-status') || 'raw';
  var short = rec.short_id || '';
  var notes = rec.notes || '';
  var work = panel.querySelector('.gwork');
  if (!work) return;
  work.removeAttribute('data-empty');
  work.setAttribute('data-idea', ideaId);
  var html = ''
    + '<h3>' + _esc(title || '(untitled idea)')
    + ' <span class="idchip">' + _esc(short) + '</span>'
    + ' <span class="stchip ' + _esc(status) + '">' + _esc(status) + '</span></h3>'
    + (notes ? '<div class="desc">' + _esc(notes) + '</div>' : '')
    + '<div class="sub">Develop with a tool — the session is seeded with this '
    + 'idea’s text + any refinements. Output is saved here with a new id and '
    + 'is pullable into a Research or Plan run.</div>'
    + '<div class="devbar"><span class="lbl">Develop:</span>'
    + '<button class="mini go" data-dev="research">🔬 Research<span class="car">▸</span></button>'
    + '<button class="mini go" data-dev="plan">📐 Plan<span class="car">▸</span></button>'
    + '<span class="sp"></span>'
    + '<span class="lbl">Engine</span>'
    + '<button class="mini gengtog">◆ Claude</button>'
    + '<button class="mini gexport" title="Copy this idea’s research/plan work up '
    + 'into real lane tiles; the idea stays here marked promoted">⇪ Export to project</button></div>'
    // v10 Wave 3 — TWO independent, labeled, collapsible terminal hosts
    // (research, plan). Each renders COLLAPSED until its Develop button starts/
    // focuses its (idea, lane) session; collapsing hides the host, never kills.
    // Each terminal owns its OWN Save-refinement control (.gsave) so a save
    // targets the bound session for THAT lane — never the last-focused global one.
    + '<div class="gterms">'
    + '<div class="gterm collapsed" data-lane="research">'
    + '<div class="tbar"><span class="ic">🔬</span>'
    + '<span class="lab"><b>Research terminal</b> · not started</span>'
    + '<span class="sp"></span>'
    // v10 Wave 4 — Archive (D7): persist THIS session produced docs + summary
    // into a per-idea bundle that survives kill. DISTINCT from Save (a text
    // snapshot). Disabled until this lane Develop session is live.
    + '<button class="mini garchive" data-archive-lane="research" disabled '
    + 'title="Archive THIS research session\'s produced docs + summary into a '
    + 'per-idea bundle (survives kill; available at promotion)">🗄 Archive</button>'
    // v10 Wave 5 — Advance to Plan: push THIS research dev session → a linked
    // grass PLAN dev session using the SAME paste-NOT-submit seeded handoff as
    // the project-level advance. Only the research lane carries this control.
    // Disabled until this research Develop session is live.
    + '<button class="mini gadvance" data-advance="research" disabled '
    + 'title="Advance this research to a linked Plan session in the workbench — '
    + 'the Crucible prompt is pasted UNSENT for you to review and press Enter">'
    + '➜ Advance to Plan</button>'
    + '<button class="mini gsave" data-save-lane="research" disabled '
    + 'title="Save THIS research session\'s output as a new '
    + 'grass-&lt;id&gt;/dev-N refinement">💾 Save</button>'
    + '<span class="car">▸</span></div>'
    + '<div class="term-host" data-grass-term="research"></div></div>'
    + '<div class="gterm collapsed" data-lane="plan">'
    + '<div class="tbar"><span class="ic">📐</span>'
    + '<span class="lab"><b>Plan terminal</b> · not started</span>'
    + '<span class="sp"></span>'
    + '<button class="mini garchive" data-archive-lane="plan" disabled '
    + 'title="Archive THIS plan session\'s produced docs + summary into a '
    + 'per-idea bundle (survives kill; available at promotion)">🗄 Archive</button>'
    + '<button class="mini gsave" data-save-lane="plan" disabled '
    + 'title="Save THIS plan session\'s output as a new '
    + 'grass-&lt;id&gt;/dev-N refinement">💾 Save</button>'
    + '<span class="car">▸</span></div>'
    + '<div class="term-host" data-grass-term="plan"></div></div>'
    + '</div>'
    // v10 Wave 4 — Archived material: the per-idea archive bundles (persisted
    // docs + summary), newest-first. Empty until the idea is archived.
    + '<div class="garch"><div class="h">Archived material · saved docs + '
    + 'summary tied to this idea</div><div class="garch-rows"></div></div>'
    + '<div class="ghist"><div class="h">Refinement history · pull any version '
    + 'into another effort</div><div class="ghist-rows"></div></div>';
  work.innerHTML = html;
  // Wire the devbar — each Develop button TOGGLES its lane's terminal.
  var dbtns = work.querySelectorAll('button[data-dev]');
  for (var d = 0; d < dbtns.length; d++) {
    dbtns[d].onclick = (function (lane) {
      return function () { toggleGrassTerminal(ideaId, lane); };
    })(dbtns[d].getAttribute('data-dev'));
  }
  // Clicking a terminal's bar toggles that same terminal (collapse/expand) —
  // independent of the other; never kills the session.
  var bars = work.querySelectorAll('.gterm .tbar');
  for (var bi = 0; bi < bars.length; bi++) {
    bars[bi].onclick = (function (lane) {
      return function () { toggleGrassTerminal(ideaId, lane); };
    })(bars[bi].parentNode.getAttribute('data-lane'));
  }
  var eng = work.querySelector('.gengtog');
  if (eng) eng.onclick = function () {
    _grassEngine = (_grassEngine === 'claude') ? 'gemini' : 'claude';
    eng.textContent = (_grassEngine === 'claude') ? '◆ Claude' : '✦ Gemini';
  };
  var exp = work.querySelector('.gexport');
  if (exp) exp.onclick = function () { exportGrass(ideaId); };
  // PER-LANE Save-refinement: each .gterm bar carries its OWN Save button that
  // saves THAT lane's bound (idea, lane) session — never the last-focused global.
  // The button lives inside the bar, so stop propagation so a Save click does not
  // also collapse/expand the terminal. Each starts disabled until its lane's
  // Develop session is live (enabled in developGrass), and switching ideas resets.
  var svbtns = work.querySelectorAll('button[data-save-lane]');
  for (var si = 0; si < svbtns.length; si++) {
    svbtns[si].disabled = true;
    svbtns[si].onclick = (function (lane) {
      return function (ev) {
        if (ev) ev.stopPropagation();
        saveGrassRefinement(ideaId, lane);
      };
    })(svbtns[si].getAttribute('data-save-lane'));
  }
  // v10 Wave 4 — PER-LANE Archive: each .gterm bar carries its OWN Archive button
  // that archives THAT lane's bound (idea, lane) session's docs + summary into the
  // idea bundle. Lives inside the bar → stopPropagation so it does not also
  // collapse/expand. Disabled until its lane's Develop session is live.
  var arbtns = work.querySelectorAll('button[data-archive-lane]');
  for (var ai = 0; ai < arbtns.length; ai++) {
    arbtns[ai].disabled = true;
    arbtns[ai].onclick = (function (lane) {
      return function (ev) {
        if (ev) ev.stopPropagation();
        archiveGrassSession(ideaId, lane);
      };
    })(arbtns[ai].getAttribute('data-archive-lane'));
  }
  // v10 Wave 5 — Advance to Plan: the research lane's own control pushes its dev
  // session → a linked grass PLAN dev session. Lives inside the research bar →
  // stopPropagation so it does not also collapse/expand. Disabled until the
  // research Develop session is live (enabled in developGrass).
  var advbtns = work.querySelectorAll('button[data-advance]');
  for (var avi = 0; avi < advbtns.length; avi++) {
    advbtns[avi].disabled = true;
    advbtns[avi].onclick = (function () {
      return function (ev) {
        if (ev) ev.stopPropagation();
        advanceGrassToPlan(ideaId);
      };
    })();
  }
  // Both terminal hosts render COLLAPSED + unbound for a freshly selected idea.
  _grassDevSession = null;
  _grassLaneSession[ideaId + '::research'] = null;
  _grassLaneSession[ideaId + '::plan'] = null;
  _renderGrassArchives(work, rec.archives || []);
  _renderGrassHistory(work, rec.refinements || []);
}

// _renderGrassArchives(work, archives): render the per-idea Archived-material list
// (persisted docs + a summary link), newest-first. Each archive's docs link via
// /artifact/<pid>?path=<rel>; its summary via /summary/<pid>/<lane>/<sid>. Honest
// empty state when none. (v10 Wave 4.)
function _renderGrassArchives(work, archives) {
  var box = work.querySelector('.garch-rows');
  if (!box) return;
  if (!archives || !archives.length) {
    box.innerHTML = '<div class="garch-empty">No archived material yet — Archive '
      + 'a Research or Plan session to save its docs + summary here.</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < archives.length; i++) {
    var a = archives[i];
    var lane = a.lane || '';
    var sid = a.session_id || '';
    var docs = a.docs || [];
    var doclinks = '';
    for (var d = 0; d < docs.length; d++) {
      var rel = docs[d];
      var href = '/artifact/' + encodeURIComponent(PROJECT_ID)
        + '?path=' + encodeURIComponent(rel);
      var nm = rel.split('/').pop();
      doclinks += '<a class="alink" target="_blank" href="' + _esc(href) + '">'
        + _esc(nm) + '</a>';
    }
    if (!doclinks) doclinks = '<span class="garch-nodoc">(no docs)</span>';
    var sumhref = '/summary/' + encodeURIComponent(PROJECT_ID) + '/'
      + encodeURIComponent(lane) + '/' + encodeURIComponent(sid);
    var sumlink = (a.has_summary)
      ? '<a class="alink" target="_blank" href="' + _esc(sumhref) + '">summary</a>'
      : '<span class="garch-nosum">summary pending</span>';
    html += '<div class="ar"><span class="lnchip">' + _esc(lane) + '</span> '
      + doclinks + '<span class="sp"></span>' + sumlink + '</div>';
  }
  box.innerHTML = html;
}

function _renderGrassHistory(work, refs) {
  var box = work.querySelector('.ghist-rows');
  if (!box) return;
  if (!refs || !refs.length) {
    box.innerHTML = '<div class="ghist-empty">No refinements yet — Develop the idea '
      + 'with Research or Plan to save one.</div>';
    return;
  }
  var html = '';
  for (var i = 0; i < refs.length; i++) {
    var r = refs[i];
    var rid = r.refinement_id || '';
    var lbl = r.label || (r.text ? r.text.slice(0, 60) : 'refinement');
    html += '<div class="hr"><span class="idchip">' + _esc(rid) + '</span> '
      + _esc(lbl) + '<span class="sp"></span>'
      + '<button class="mini" data-pull="' + _esc(rid) + '" data-lane="research">pull into Research…</button>'
      + '<button class="mini" data-pull="' + _esc(rid) + '" data-lane="plan">pull into Plan…</button></div>';
  }
  box.innerHTML = html;
  var pbtns = box.querySelectorAll('button[data-pull]');
  var ideaId = work.getAttribute('data-idea');
  for (var k = 0; k < pbtns.length; k++) {
    pbtns[k].onclick = (function (rid, lane) {
      return function () { pullGrass(ideaId, rid, lane); };
    })(pbtns[k].getAttribute('data-pull'), pbtns[k].getAttribute('data-lane'));
  }
}

// _grassWork(ideaId): the .gwork pane for THIS idea (fallback to the visible one).
function _grassWork(ideaId) {
  var panel = document.getElementById('grassPanel');
  if (!panel) return null;
  return panel.querySelector('.gwork[data-idea="' + _cssEsc(ideaId) + '"]')
      || panel.querySelector('.gwork');
}

// _grassTermBox(work, lane): the .gterm container for one lane (research|plan).
function _grassTermBox(work, lane) {
  return work ? work.querySelector('.gterm[data-lane="' + _cssEsc(lane) + '"]') : null;
}

// toggleGrassTerminal(ideaId, lane): v10 Wave 3. Research and Plan each own a
// SEPARATE, independently-collapsible terminal. Clicking a Develop button (or the
// terminal's own bar):
//   • if that lane's terminal is COLLAPSED → EXPAND it. If no session is bound
//     yet, start/focus the (idea, lane) develop session (developGrass) and mount
//     its xterm in THIS lane's host; if already mounted, just reveal it.
//   • if that lane's terminal is EXPANDED → COLLAPSE (minimize) it. The session
//     stays LIVE (the PTY + transport are untouched) — only the host is hidden.
// The two lanes are fully independent: toggling one never touches the other.
function toggleGrassTerminal(ideaId, lane) {
  var work = _grassWork(ideaId);
  if (!work) return;
  var box = _grassTermBox(work, lane);
  if (!box) return;
  if (box.classList.contains('collapsed')) {
    box.classList.remove('collapsed');
    _setGrassToggle(work, lane, true);
    // Bind a session the first time this lane is opened (or re-focus its terminal).
    if (!_grassLaneSession[ideaId + '::' + lane]) {
      developGrass(ideaId, lane);
    } else {
      var host = box.querySelector('[data-grass-term]');
      if (host) host.scrollIntoView({behavior: 'smooth', block: 'nearest'});
      _grassDevSession = _grassLaneSession[ideaId + '::' + lane];
    }
  } else {
    // COLLAPSE only — session stays live (do NOT unmount/kill the PTY).
    box.classList.add('collapsed');
    _setGrassToggle(work, lane, false);
  }
}

// _setGrassToggle(work, lane, open): reflect the open/collapsed state on the
// Develop button (active cue + ▾/▸ caret) and the terminal bar's caret.
function _setGrassToggle(work, lane, open) {
  if (!work) return;
  var btn = work.querySelector('button[data-dev="' + _cssEsc(lane) + '"]');
  if (btn) {
    btn.classList.toggle('on', !!open);
    var bc = btn.querySelector('.car');
    if (bc) bc.textContent = open ? '▾' : '▸';
  }
  var box = _grassTermBox(work, lane);
  if (box) {
    var tc = box.querySelector('.tbar .car');
    if (tc) tc.textContent = open ? '▾' : '▸';
  }
}

// developGrass(ideaId, lane): start a SEEDED workbench session (the idea + its
// refinements) and mount its terminal in THIS lane's own .gterm host. Token-aware.
// Called by toggleGrassTerminal when a lane is first opened. The backend dedupes
// on the live (idea, lane) session — research and plan are two DIFFERENT lanes, so
// both can be live at once (two concurrent dev sessions per idea).
async function developGrass(ideaId, lane) {
  var work = _grassWork(ideaId);
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, lane: lane, backend: _grassEngine};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_develop', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_develop', payload);
      data = await r.json();
    }
  } catch (e) { alert('[develop error] ' + e.message); return; }
  if (!data.ok || !data.session) { alert('[develop refused] ' + (data.error || 'unknown')); return; }
  var sid = data.session.session_id;
  // v8 Wave 6: a develop session is CONTAINED. It is DELIBERATELY NOT added to
  // MANAGED / renderSessionBar (no top-strip chip) and NOT pushed to the board
  // (refreshBoard) — it lives ONLY in the workbench pane below, keyed by
  // (idea, lane). Re-clicking Develop focuses this same session (the backend
  // dedupes on the live (idea, lane) session and returns it). The board bridge
  // also excludes it server-side via the [grass-dev] label marker.
  var box = _grassTermBox(work, lane);
  var host = box ? box.querySelector('[data-grass-term]') : null;
  var lab = box ? box.querySelector('.tbar .lab') : null;
  var icon = (lane === 'plan') ? '📐' : '🔬';
  var name = (lane === 'plan') ? 'Plan terminal' : 'Research terminal';
  if (lab) lab.innerHTML = '<b>' + _esc(name) + '</b> · ' + _esc(_grassEngine)
    + ' · grass-dev · ' + _esc(sid);
  if (host) {
    // Re-focus: if THIS session's terminal is already mounted, just bring it up.
    if (host.getAttribute('data-session') === sid && PANELS[sid]) {
      host.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } else {
      host.setAttribute('data-session', sid);
      PANELS[sid] = {el: document.getElementById('grassPanel'), body: host, term: null, transport: null};
      _mountTerminal(sid, host);
    }
  }
  // Bind this session to THIS (idea, lane) so a later expand re-focuses it AND so
  // Save-refinement targets the right host. Mark this lane's toggle OPEN.
  _grassLaneSession[ideaId + '::' + lane] = sid;
  _grassDevSession = sid;
  _setGrassToggle(work, lane, true);
  // Enable THIS lane's own Save-refinement button (the other lane's stays as-is).
  var sv = box ? box.querySelector('button[data-save-lane="' + _cssEsc(lane) + '"]') : null;
  if (sv) sv.disabled = false;
  // v10 Wave 4 — enable THIS lane's own Archive button too (the other stays as-is).
  var ar = box ? box.querySelector('button[data-archive-lane="' + _cssEsc(lane) + '"]') : null;
  if (ar) ar.disabled = false;
  // v10 Wave 5 — enable the research lane's own Advance-to-Plan control once its
  // dev session is live (only the research bar carries it).
  if (lane === 'research') {
    var adv = box ? box.querySelector('button[data-advance="research"]') : null;
    if (adv) adv.disabled = false;
  }
}

// archiveGrassSession(ideaId, lane): v10 Wave 4 (D7). Archive THIS LANE's live
// Develop session's PRODUCED docs + summary into a per-idea bundle that survives a
// kill — DISTINCT from Save (a text snapshot). POST /api/rnd/grass_archive →
// effort_history.archive_grass_session. The idea STAYS in grass. Re-renders the
// Archived-material list with the new bundle. Honest: if nothing was produced the
// server returns ok:false with a reason (surfaced, not faked). Token-aware.
async function archiveGrassSession(ideaId, lane) {
  var work = _grassWork(ideaId);
  if (!work) return;
  var sid = _grassLaneSession[ideaId + '::' + lane] || null;
  if (!sid) { alert('[archive] open this lane’s Develop session first'); return; }
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, lane: lane};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_archive', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_archive', payload);
      data = await r.json();
    }
  } catch (e) { alert('[archive error] ' + e.message); return; }
  if (!data.ok) {
    alert('[nothing to archive] ' + (data.reason || data.error || 'no docs produced yet'));
    return;
  }
  // Re-fetch the grass data so the idea record's archives ride the next render,
  // then re-render THIS idea's Archived-material list with the new bundle.
  await _loadGrassData();
  var rec = _grassData[ideaId] || {};
  _renderGrassArchives(work, rec.archives || []);
}

// advanceGrassToPlan(ideaId): v10 Wave 5 (Pillar 2 #2). From THIS idea's RESEARCH
// dev session, push research → plan using the SAME paste-NOT-submit seeded handoff
// as the project-level advance — staying INSIDE the grass workbench, linked. POST
// /api/rnd/grass_advance → effort_history.advance_grass_research_to_plan builds the
// Crucible prompt from the research dev session's persisted docs, starts (or
// focuses) the CONTAINED (idea, 'plan') dev session with the prompt delivered
// PASTED-but-UNSENT, links it to the research session (parent_session_id +
// grass_origin), and records the stage edge. On success we ENSURE the grass PLAN
// terminal is OPEN and mounts the returned plan dev session (reusing the Wave-3
// toggle/mount path), so the pasted-unsent prompt becomes visible in the plan
// terminal input for the user to review and press Enter. The research dev session
// must be live first (the control is disabled until then). v11.1 Wave 2: the
// advance NEVER refuses on "no written doc" — the keystone snapshots the research
// conversation transcript so the plan session ALWAYS opens with a transcript-backed
// (or honest-minimal "create the plan") prompt. The only ok:false left is
// no-research-session (no research dev session to advance from), surfaced honestly.
// Token-aware. No auto-submit (the prompt is the v10 pending paste).
async function advanceGrassToPlan(ideaId) {
  var work = _grassWork(ideaId);
  if (!work) return;
  var rsid = _grassLaneSession[ideaId + '::research'] || null;
  if (!rsid) { alert('[advance] open this idea’s Research session first'); return; }
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, backend: _grassEngine};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_advance', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_advance', payload);
      data = await r.json();
    }
  } catch (e) { alert('[advance error] ' + e.message); return; }
  if (!data || !data.ok || !data.session) {
    // v11.1 Wave 2: the advance NO LONGER refuses on "no written doc" — the
    // keystone snapshots the research conversation transcript and the plan session
    // ALWAYS opens (with a transcript-backed or honest-minimal "create the plan"
    // prompt). The only legitimate refusal left is no-research-session (there is no
    // research dev session at all to advance FROM); honest-surface it.
    alert('[nothing to advance] ' + ((data && (data.reason || data.error))
      || 'open this idea’s Research session first'));
    return;
  }
  var rec = data.session;
  var psid = rec.session_id;
  // Mount the returned grass PLAN dev session into the plan lane's OWN host, then
  // ensure the plan terminal toggles OPEN (reuse the Wave-3 mount/toggle path). We
  // bind the (idea, 'plan') session id BEFORE toggling so toggleGrassTerminal
  // re-focuses THIS session instead of starting a second develop session.
  var box = _grassTermBox(work, 'plan');
  var host = box ? box.querySelector('[data-grass-term]') : null;
  var lab = box ? box.querySelector('.tbar .lab') : null;
  if (lab) lab.innerHTML = '<b>Plan terminal</b> · ' + _esc(_grassEngine)
    + ' · grass-dev · ' + _esc(psid);
  if (host && host.getAttribute('data-session') !== psid) {
    host.setAttribute('data-session', psid);
    PANELS[psid] = {el: document.getElementById('grassPanel'), body: host, term: null, transport: null};
    _mountTerminal(psid, host);
  }
  _grassLaneSession[ideaId + '::plan'] = psid;
  _grassDevSession = psid;
  // Reveal the plan terminal (it may be collapsed) + reflect the open state.
  if (box) box.classList.remove('collapsed');
  _setGrassToggle(work, 'plan', true);
  // Enable the plan lane's own Save + Archive controls (its dev session is live).
  var sv = box ? box.querySelector('button[data-save-lane="plan"]') : null;
  if (sv) sv.disabled = false;
  var ar = box ? box.querySelector('button[data-archive-lane="plan"]') : null;
  if (ar) ar.disabled = false;
  // The Crucible prompt is delivered PASTED-but-UNSENT (pending paste, flushed by
  // the terminal transport after the skill greets). Hint the user it is sitting in
  // the input line for review — nothing was submitted.
  // v10 Wave 5 (DEFECT-1 fix): only flash the "prompt ready" hint when the server
  // actually delivered/queued a fresh paste on THIS advance (data.paste_delivered).
  // A focus of an ALREADY-handed-off plan session (re-advance, or one the user is
  // mid-typing in) delivers nothing → we must NOT flash a misleading hint over an
  // input we didn't write to. (On a fresh mint AND on the develop-plan-first focus
  // that just queued the handoff, paste_delivered is true.)
  if (data.paste_delivered) {
    _flashPendingPasteHint(psid);
  }
}

// saveGrassRefinement(ideaId, lane): persist THIS LANE's live Develop session's
// output as a NEW versioned refinement (grass-<id>/dev-N) and re-render the history
// so it appears with a pull control. Closes the develop→save→appears loop end to
// end. v10 Wave 3 — research and plan are INDEPENDENT lanes, each with its OWN Save
// control, so the save targets THAT lane's bound (idea, lane) session (NOT the
// last-focused global one). The session's visible terminal text is captured
// best-effort as the refinement text; the session_id links the refinement to the
// run. Saving requires that lane's terminal be open (its Develop session live).
// Token-aware.
async function saveGrassRefinement(ideaId, lane) {
  var work = _grassWork(ideaId);
  if (!work) return;
  // THIS lane's bound develop session (set in developGrass). No session ⇒ nothing
  // to save (the per-lane Save button is disabled until its lane is live anyway).
  var sid = _grassLaneSession[ideaId + '::' + lane] || null;
  if (!sid) { alert('[save] open this lane’s Develop session first'); return; }
  // Capture THIS lane's own terminal host text (its [data-grass-term="<lane>"]).
  var box = _grassTermBox(work, lane);
  var host = box ? box.querySelector('[data-grass-term][data-session="'
                                     + _cssEsc(sid) + '"]') : null;
  if (!host && box) host = box.querySelector('[data-grass-term]');
  var text = host ? ((host.innerText || '').trim().slice(-4000)) : '';
  var payload = {project_id: PROJECT_ID, idea_id: ideaId,
                 session_id: sid,
                 label: 'Refinement from ' + lane + ' workbench session', text: text};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_save_refinement', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_save_refinement', payload);
      data = await r.json();
    }
  } catch (e) { alert('[save error] ' + e.message); return; }
  if (!data.ok) { alert('[save refused] ' + (data.error || 'unknown')); return; }
  // Re-fetch the grass data and re-render THIS idea's history so the new
  // grass-<id>/dev-N row appears with its pull controls.
  await _loadGrassData();
  var rec = _grassData[ideaId] || {};
  _renderGrassHistory(work, rec.refinements || []);
  // The idea is now REFINED — reflect it on the workbench chip + the list row.
  var chip = work.querySelector('h3 .stchip');
  if (chip) { chip.className = 'stchip refined'; chip.textContent = 'refined'; }
  // The .gli list rows live under #grassPanel (the left list) — look the row up
  // there (the prior code read an undeclared `panel`, throwing a ReferenceError).
  var panel = document.getElementById('grassPanel');
  var lrow = panel ? panel.querySelector('.gli[data-idea="' + _cssEsc(ideaId) + '"]') : null;
  if (lrow) lrow.setAttribute('data-status', 'refined');
}

// exportGrass(ideaId): EXPORT the idea's research/plan develop work UP into REAL
// lane tiles (Option B). POST /api/rnd/grass_export → the backend copies the
// develop docs up as board-visible lane sessions AND marks the idea "promoted"
// (linked) — the idea STAYS in grass. We then refresh the board so the new lane
// tiles appear, and flip the workbench + list chip to "promoted". Token-aware.
async function exportGrass(ideaId) {
  var payload = {project_id: PROJECT_ID, idea_id: ideaId};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_export', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_export', payload);
      data = await r.json();
    }
  } catch (e) { alert('[export error] ' + e.message); return; }
  if (!data.ok) {
    alert('[export refused] ' + (data.error || data.reason || 'unknown'));
    return;
  }
  // The idea is now PROMOTED — reflect it on the workbench chip + the list row.
  var panel = document.getElementById('grassPanel');
  var work = panel ? panel.querySelector('.gwork[data-idea="' + _cssEsc(ideaId) + '"]') : null;
  if (!work) work = panel ? panel.querySelector('.gwork') : null;
  if (work) {
    var chip = work.querySelector('h3 .stchip');
    if (chip) { chip.className = 'stchip promoted'; chip.textContent = 'promoted'; }
  }
  var lrow = panel ? panel.querySelector('.gli[data-idea="' + _cssEsc(ideaId) + '"]') : null;
  if (lrow) { lrow.setAttribute('data-status', 'promoted'); lrow.classList.add('p'); }
  // Re-fetch the server-rendered board so the exported research/plan lane tiles
  // appear INSTANTLY (the board is the single source of truth — re-fetch, never
  // JS-inject — so dedupe stays correct).
  refreshBoard();
}

// pullGrass(ideaId, refinementId, lane): pull a refinement version into a NEW
// seeded session (research/plan) and open its inline panel. Token-aware.
async function pullGrass(ideaId, refinementId, lane) {
  var payload = {project_id: PROJECT_ID, idea_id: ideaId,
                 refinement_id: refinementId, lane: lane, backend: _grassEngine};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_pull', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_pull', payload);
      data = await r.json();
    }
  } catch (e) { alert('[pull error] ' + e.message); return; }
  if (!data.ok || !data.session) { alert('[pull refused] ' + (data.error || 'unknown')); return; }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || lane, backend: rec.backend || _grassEngine,
    status: rec.status || 'running', label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] = (_laneCounters[rec.lane || lane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  setTimeout(repopulate, 600);
}

// _refreshGrassCounts(root): recompute the .gtabs filter-count chips from the
// REMAINING .gli rows under `root` (a live #grassPanel OR the hidden source
// #grassWorkbenchTpl) and write them into the matching .gtab[data-filter] .n
// spans (all = total rows, raw/refined/promoted = rows by data-status). Deriving
// from the actual rows (not an arithmetic decrement) means the counts can never
// drift after a delete. Guarded for missing elements (no throw).
function _refreshGrassCounts(root) {
  if (!root) return;
  var rows = root.querySelectorAll('.gli[data-status]');
  var counts = {all: 0, raw: 0, refined: 0, promoted: 0};
  for (var i = 0; i < rows.length; i++) {
    counts.all++;
    var st = rows[i].getAttribute('data-status');
    if (counts.hasOwnProperty(st)) counts[st]++;
  }
  var keys = ['all', 'raw', 'refined', 'promoted'];
  for (var k = 0; k < keys.length; k++) {
    var tab = root.querySelector('.gtab[data-filter="' + keys[k] + '"] .n');
    if (tab) tab.textContent = String(counts[keys[k]]);
  }
}

// deleteGrassIdea(ideaId): permanently DELETE a grass idea (v9 Wave 2). confirm()-
// gated (an irreversible removal), then POST /api/rnd/grass_delete {confirm:true}.
// On success the idea row is removed from the workbench list AND — if it was the
// selected idea — the right workbench pane is cleared. The idea does not return
// (grass_workbench_data no longer lists it). Token-aware (retries once on 401).
async function deleteGrassIdea(ideaId) {
  if (!confirm('Delete this idea? This permanently removes it and its refinements.')) return;
  var payload = {project_id: PROJECT_ID, idea_id: ideaId, confirm: true};
  var r, data;
  try {
    r = await _postJson('/api/rnd/grass_delete', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/grass_delete', payload);
      data = await r.json();
    }
  } catch (e) { alert('[delete error] ' + e.message); return; }
  if (!data.ok) { alert('[delete refused] ' + (data.error || data.reason || 'unknown')); return; }
  var panel = document.getElementById('grassPanel');
  if (panel) {
    var lrow = panel.querySelector('.gli[data-idea="' + _cssEsc(ideaId) + '"]');
    if (lrow) lrow.remove();
    // If the deleted idea was the selected one, clear the right workbench pane.
    var work = panel.querySelector('.gwork[data-idea="' + _cssEsc(ideaId) + '"]')
            || panel.querySelector('.gwork');
    if (work && work.getAttribute('data-idea') === ideaId) {
      work.removeAttribute('data-idea');
      work.setAttribute('data-empty', '1');
      work.innerHTML = '<div class="gwork-empty">Select an idea to develop it.</div>';
    }
  }
  // Drop it from the cached grass data too, so a later select can't resurrect it.
  if (_grassData && _grassData[ideaId]) { try { delete _grassData[ideaId]; } catch (e) {} }
  // v10.1 FIX 2 — the workbench is server-rendered ONCE into a hidden template
  // (#grassWorkbenchTpl); openGrassWorkbench clones it on EVERY fresh open and
  // closeBtn does panel.remove(). Removing only the LIVE row leaves the stale
  // idea in the template, so close→reopen re-clones it back. Prune the matching
  // row from the source template too, so later clones are clean. (DOM-only on a
  // display:none template; no re-wiring, no server change.)
  var stpl = document.getElementById('grassWorkbenchTpl');
  var trow = stpl && stpl.querySelector('.gli[data-idea="' + _cssEsc(ideaId) + '"]');
  if (trow) trow.remove();
  // v10.1 FIX 2 follow-up — the .gtabs filter-count chips were server-rendered
  // ONCE into the template and never updated, so after a delete they read stale
  // (e.g. "All 1" over an empty list, both live AND on a later re-clone). Recompute
  // the counts from the REMAINING rows on BOTH the live panel (immediate update)
  // and the source template (so a close→reopen re-clone shows correct counts).
  _refreshGrassCounts(panel);
  _refreshGrassCounts(stpl);
}

// ── Type-aware deliverable launch (v4 Wave 7) ───────────────────────────────
// Clicking launch ADAPTS to the deliverable type:
//   skill/tool → verify status (available/loaded/missing); NO process.
//   service    → start a preview (free port ≠8777, isolated data dir) or pull
//                up the running one; open the URL in a new tab + show Stop.
//   program    → run-to-result; report success/failure.
//   doc        → open the rendered view (the /artifact route) in a new tab.
// Token-aware via _postJson (retries once on 401).
async function launchDeliverable(btn) {
  var li = btn.closest('.deliv-pinned');
  var msg = li ? li.querySelector('.deliv-msg') : null;
  var did = li ? li.getAttribute('data-deliv-id') : '';
  var dtype = li ? li.getAttribute('data-deliv-type') : '';
  if (!did) { if (msg) msg.textContent = 'no deliverable id'; return; }
  if (msg) msg.textContent = 'launching…';
  btn.disabled = true;
  var payload = {project_id: PROJECT_ID, deliverable_id: did};
  try {
    var r = await _postJson('/api/rnd/launch_deliverable', payload);
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/launch_deliverable', payload);
      data = await r.json();
    }
    if (!data || !data.ok) {
      if (msg) msg.textContent = 'failed: ' + ((data && data.error) || 'unknown');
      btn.disabled = false;
      return;
    }
    if (dtype === 'service') {
      if (li) li.setAttribute('data-preview-id', data.preview_id || '');
      if (msg) msg.textContent = (data.pulled_up ? 'pulled up' : 'running')
        + ' on port ' + (data.port || '?');
      var stopBtn = li ? li.querySelector('.deliv-stop') : null;
      if (stopBtn) stopBtn.style.display = '';
      btn.style.display = 'none';
      if (data.url) window.open(data.url, '_blank');
    } else if (dtype === 'doc') {
      if (msg) msg.textContent = 'opened';
      btn.disabled = false;
      if (data.href) window.open(data.href, '_blank');
    } else if (dtype === 'skill' || dtype === 'tool') {
      if (msg) msg.textContent = dtype + ': ' + (data.status || '?');
      btn.disabled = false;
    } else {  // program / script
      if (msg) msg.textContent = 'result: ' + (data.status || (data.ok ? 'ok' : 'failed'));
      btn.disabled = false;
    }
  } catch (e) {
    if (msg) msg.textContent = 'error: ' + e.message;
    btn.disabled = false;
  }
}

async function stopDeliverable(btn) {
  var li = btn.closest('.deliv-pinned');
  var pid = li ? li.getAttribute('data-preview-id') : '';
  var msg = li ? li.querySelector('.deliv-msg') : null;
  if (!pid) { if (msg) msg.textContent = 'no running preview'; return; }
  btn.disabled = true;
  try {
    var r = await _postJson('/api/rnd/preview_stop', {preview_id: pid});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/preview_stop', {preview_id: pid});
      data = await r.json();
    }
    if (msg) msg.textContent = 'stopped';
    btn.style.display = 'none';
    if (li) li.removeAttribute('data-preview-id');
    var runBtn = li ? li.querySelector('.deliv-run') : null;
    if (runBtn) { runBtn.style.display = ''; runBtn.disabled = false; }
  } catch (e) {
    if (msg) msg.textContent = 'stop error: ' + e.message;
    btn.disabled = false;
  }
}

function openReport(href) { window.open(href, '_blank'); }

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

// ── Header cost/tokens/time rollup: lifetime / 30-day toggle (v4 Wave 5) ─────
// The header renders the lifetime rollup server-side; this toggle re-fetches the
// read-only /api/rnd/project_rollup for the chosen window and swaps the text in
// place (no page reload). Lifetime is the default; the toggle is purely additive.
function rndRollupWindow(window_, btn) {
  var el = document.getElementById('hdrRollup');
  if (!el) return;
  var pid = el.getAttribute('data-pid') || PROJECT_ID;
  // Flip the on-state on the two toggle buttons.
  if (btn && btn.parentNode) {
    var bs = btn.parentNode.querySelectorAll('b');
    for (var i = 0; i < bs.length; i++) bs[i].classList.remove('on');
    btn.classList.add('on');
  }
  var url = '/api/rnd/project_rollup?pid=' + encodeURIComponent(pid)
    + '&window=' + encodeURIComponent(window_) + _tokenQ();
  fetch(url, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d && d.ok && d.text) {
        el.textContent = d.text;
        el.setAttribute('data-window', window_);
      }
    })
    .catch(function () {});
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
// Paradigm-2 INLINE ACCORDION PANEL MANAGER — the ONLY terminal surface.
//
// Each lane's most-recent session is a TILE carrying a status light. Clicking a
// tile (laneTileClick → openPanel) EXPANDS a full-width inline panel appended to
// the #panelStack BELOW the board — panels stack down the page, they never float
// or overlap. A second click / the panel's "– min" button collapses it back to
// the tile (minimizePanel) WITHOUT killing the session. The panel's "×" button is
// CLOSE-to-tile (closePanel) — it tears down the panel DOM only and leaves the
// session record + lane tile intact (reopenable). A SEPARATE "🗑 Kill" button is
// the deliberate hard-kill, gated behind a confirm() (killPanel → POST
// /api/rnd/term_kill) that also removes the session's tile. repopulate() reads
// /api/rnd/term_sessions to keep the MANAGED map in sync (so a tile for an
// already-running terminal can re-open its panel).
//
// The terminal transport is UNCHANGED (WS term_ws first; SSE-out term_stream2 +
// POST-in term_input2 fallback; term_resize), mounted into the panel body host.
// A LIVE session mounts xterm; a DONE/historical session shows a read-only note.
// ════════════════════════════════════════════════════════════════════════════

// MANAGED: session_id -> {session_id, lane, backend, status, label, idx} for
// LIVE (non-terminal) managed sessions — these mount a live xterm terminal.
var MANAGED = {};
// FINISHED (v6 Wave 4): session_id -> {session_id, lane, backend, status, label,
// created_at, chain_id, parent_session_id, idx} for TERMINAL-status (done/failed)
// managed sessions. v5 dropped these from the row; v6 KEEPS them as greyed,
// reopenable tiles (per lane: newest prominent, older ones under "previously
// done"). Clicking a finished tile opens a HISTORICAL (read-only) panel showing
// the Wave-1 session summary — _synthSessionRecord reads the tile's data-* attrs,
// so a finished tile is NOT in MANAGED and openPanel treats it as non-live.
var FINISHED = {};
// PANELS: session_id -> {el, body, term, transport} for an OPEN inline panel.
var PANELS = {};
var _laneCounters = {};   // lane -> running index, for "plan 1", "plan 2" labels
// _KILLED (v6 Wave 4): session ids the user DELIBERATELY hard-killed this page
// load. term_kill marks the registry record 'done' (terminal) — indistinguishable
// by status from a naturally-finished session — so without this set a killed tile
// would re-enter the row as a greyed FINISHED tile on the next repopulate(). A
// hard-kill means GONE; we suppress these ids from both MANAGED and FINISHED.
var _KILLED = {};

// _DELETED (v9 Wave 1): session ids the user TRUE-DELETED this page load. Delete
// (term_delete) HARD-REMOVES the registry record + the session's effort pointer-
// records + cached summary — so unlike a kill (which leaves a 'done' record that
// would otherwise re-enter as a greyed tile), a deleted session never comes back
// from the registry. We still record the id here so any in-flight repopulate()
// that raced the delete cannot momentarily re-add the tile. (The produced
// documents are KEPT on disk — Option A — only the Anchor record/cache is gone.)
var _DELETED = {};

// Map a session status to the LOCKED color bucket (MASTER-PLAN §D / §E; this is
// the SAME mapping the server's _session_light_class applies to the lane tiles):
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

// v8 Wave 4 — skill clarity. Mirror terminal_session.LANE_SKILL so the panel
// header can show WHICH trio skill a session loaded (the user's "loads Crucible"
// confusion): research→researchPrime, plan/planning→Crucible, build→Foreman.
// A lane with no mapped skill (grass/general/deliverables) returns '' (no chip).
function _skillForLane(lane) {
  switch (lane) {
    case 'research': return 'researchPrime';
    case 'plan':
    case 'planning': return 'Crucible';
    case 'build': return 'Foreman';
    default: return '';
  }
}

// _isTerminalStatus: mirror session_registry.TERMINAL_STATUSES ({done, failed}).
// The live-session bar is the reopen vector for LIVE (non-terminal) sessions
// ONLY; a terminal session (a hard-killed one is marked 'done', a crashed one
// 'failed') must never sit in it.
function _isTerminalStatus(status) {
  return status === 'done' || status === 'failed';
}

// v10 Wave 5 (DEFECT-2 fix): a CONTAINED grass-workbench develop session keeps
// its research/plan lane (so its trio skill seeds) but its registry label is
// stamped with the [grass-dev] prefix — it must NEVER appear on the top strip
// (#sessionBar) or in MANAGED/FINISHED. It lives ONLY in the workbench pane,
// where it is mounted by session id directly (developGrass → _mountTerminal),
// not via repopulate(). Mirrors effort_history.is_grass_dev_label; the prefix is
// injected from the Python constant (GRASS_DEV_LABEL_PREFIX) so they can't drift.
function _isGrassDevLabel(label) {
  var p = (typeof GRASS_DEV_LABEL_PREFIX !== 'undefined') ? GRASS_DEV_LABEL_PREFIX : '[grass-dev] ';
  return typeof label === 'string' && label.indexOf(p) === 0;
}

// repopulate(): fetch the project's live managed sessions from the registry and
// re-sync the MANAGED map (so a tile / re-open keys on a real, stable record).
// Kept under the historical name loadSessions too (callers use it).
async function repopulate() {
  var url = '/api/rnd/term_sessions?project_id=' + encodeURIComponent(PROJECT_ID);
  var data;
  try {
    var r = await fetch(url);
    data = await r.json();
  } catch (e) { return; }
  if (!data || !data.ok) return;
  var sessions = data.sessions || [];
  // Rebuild the MANAGED (live) + FINISHED (terminal) maps, preserving a stable
  // per-lane index per session.
  var seenLive = {};
  var seenDone = {};
  _laneCounters = {};
  sessions.sort(function (a, b) {
    return (a.created_at || 0) - (b.created_at || 0);
  });
  for (var i = 0; i < sessions.length; i++) {
    var s = sessions[i];
    if (!s.session_id) continue;
    // v10 Wave 5 (DEFECT-2 fix): a CONTAINED grass-workbench develop session
    // (research OR plan) is excluded from the top strip + MANAGED/FINISHED. It is
    // mounted by session id directly in the workbench pane (developGrass), never
    // via this path. Skip BEFORE it enters either map or renderSessionBar.
    if (_isGrassDevLabel(s.label)) continue;
    // v6 Wave 4: a DELIBERATELY hard-killed session is GONE — never re-add it
    // (its registry record persists as 'done', which would otherwise re-enter it
    // as a greyed FINISHED tile). This preserves the v5 "killed tile stays gone".
    if (_KILLED[s.session_id]) continue;
    // v9 Wave 1: a TRUE-DELETED session is GONE (registry record removed); never
    // re-add it even if an in-flight fetch raced the delete and still saw it.
    if (_DELETED[s.session_id]) continue;
    var lane = s.lane || 'session';
    if (_isTerminalStatus(s.status)) {
      // v6 Wave 4: a TERMINAL session (a deliberate hard-kill marks the registry
      // record 'done'; a crash 'failed') is KEPT — but in FINISHED (a greyed,
      // reopenable tile), NOT in MANAGED (so openPanel won't try to mount a live
      // PTY for it; it synthesizes a read-only historical panel instead). If it
      // was previously live, drop it from MANAGED + close its now-stale live panel
      // (its PTY is gone) so the tile re-renders as finished.
      if (MANAGED[s.session_id]) { _closePanel(s.session_id); delete MANAGED[s.session_id]; }
      var pdone = FINISHED[s.session_id] || {};
      FINISHED[s.session_id] = {
        session_id: s.session_id, lane: lane, backend: s.backend || '',
        status: s.status || 'done', label: s.label || '',
        created_at: s.created_at || pdone.created_at || 0,
        chain_id: s.chain_id || '', parent_session_id: s.parent_session_id || '',
        idx: pdone.idx || 0
      };
      seenDone[s.session_id] = true;
      continue;
    }
    // A LIVE (running/idle/needs-attention) session → colored tile in the row.
    // If it was previously finished (e.g. reconcile re-statused it back live —
    // rare), drop the stale FINISHED entry.
    if (FINISHED[s.session_id]) delete FINISHED[s.session_id];
    _laneCounters[lane] = (_laneCounters[lane] || 0) + 1;
    var prev = MANAGED[s.session_id] || {};
    MANAGED[s.session_id] = {
      session_id: s.session_id, lane: lane, backend: s.backend || '',
      status: s.status || 'idle', label: s.label || '',
      chain_id: s.chain_id || '', parent_session_id: s.parent_session_id || '',
      created_at: s.created_at || prev.created_at || 0,
      idx: prev.idx || _laneCounters[lane]
    };
    seenLive[s.session_id] = true;
  }
  // Drop LIVE sessions the registry no longer reports at all (gone, not merely
  // terminal — a terminal one moved to FINISHED above) and close any stale panel.
  for (var sid in MANAGED) {
    if (!seenLive[sid]) { _closePanel(sid); delete MANAGED[sid]; }
  }
  // Drop FINISHED sessions the registry no longer reports (e.g. hard-kill removed
  // the record). A killed tile must not reappear.
  for (var dsid in FINISHED) {
    if (!seenDone[dsid]) delete FINISHED[dsid];
  }
  renderSessionBar();
  // v7 Wave 6: after re-syncing the live/finished maps from the registry, also
  // re-fetch the server-rendered board so the lane-column tiles reflect the
  // current set (a session that finished / advanced / reconciled-dead between
  // polls). The board is the single source of truth for the columns — re-fetch,
  // don't JS-inject — so a session shows EXACTLY ONE tile in its lane.
  refreshBoard();
}
// Back-compat alias: the historical name used by callers.
var loadSessions = repopulate;

// renderSessionBar(): v5 Wave 1 — render one clickable TILE per LIVE managed
// session into #sessionBar. A live terminal session (started via "+ new <lane>")
// is NOT a server-rendered board tile, so this bar IS its reopenable tile: after
// close-to-tile its chip persists (click it → openPanel re-attaches the live
// terminal); a deliberate hard-kill removes the chip (via _removeSessionTile, the
// SAME selector — these chips carry .tile + data-session). Empty bar when there
// are no live managed sessions. Idempotent (rebuilds from MANAGED each call).
function renderSessionBar() {
  var bar = document.getElementById('sessionBar');
  if (!bar) return;
  // Don't clobber a chip the panel manager is mid-removing: rebuild from the maps.
  bar.innerHTML = '';
  // (1) LIVE managed sessions → colored, reopenable tiles (running/idle/attn).
  var live = Object.keys(MANAGED);
  for (var i = 0; i < live.length; i++) {
    var s = MANAGED[live[i]];
    if (!s) continue;
    bar.appendChild(_buildBarTile(s, false));
  }
  // (2) v6 Wave 4: FINISHED (done/failed) sessions → greyed, reopenable tiles.
  //     Per lane the MOST-RECENT finished session is shown PROMINENTLY in the
  //     row; older finished ones in that lane collapse under a small
  //     "previously done (N)" expander so the row stays tidy but nothing is lost.
  var doneIds = Object.keys(FINISHED);
  if (doneIds.length) {
    // Group by lane, newest-first within each lane (by created_at, then idx).
    var byLane = {};
    for (var j = 0; j < doneIds.length; j++) {
      var d = FINISHED[doneIds[j]];
      if (!d) continue;
      var lane = d.lane || 'session';
      (byLane[lane] = byLane[lane] || []).push(d);
    }
    var lanes = Object.keys(byLane).sort();
    for (var k = 0; k < lanes.length; k++) {
      var group = byLane[lanes[k]];
      group.sort(function (a, b) {
        return (b.created_at || 0) - (a.created_at || 0) || (b.idx || 0) - (a.idx || 0);
      });
      // The newest finished session in this lane is the prominent tile.
      bar.appendChild(_buildBarTile(group[0], true));
      // Older finished ones collapse under "previously done (N)".
      if (group.length > 1) {
        var det = document.createElement('details');
        det.className = 'prevdone';
        det.setAttribute('data-lane', lanes[k]);
        var sum = document.createElement('summary');
        sum.textContent = 'previously done (' + (group.length - 1) + ')';
        det.appendChild(sum);
        var wrap = document.createElement('span');
        wrap.className = 'prevdone-tiles';
        for (var m = 1; m < group.length; m++) {
          wrap.appendChild(_buildBarTile(group[m], true));
        }
        det.appendChild(wrap);
        bar.appendChild(det);
      }
    }
  }
}

// _buildBarTile(s, finished): build one tiles-row tile element for a session
// record. .tile + data-session so _synthSessionRecord / _removeSessionTile bind,
// and the click hook is the SAME laneTileClick → openPanel path. A FINISHED tile
// is greyed (.done) and carries data-light='grey' so openPanel synthesizes a
// read-only historical panel (it is NOT in MANAGED). A LIVE tile carries
// data-live='1' + its status color.
function _buildBarTile(s, finished) {
  var sid = s.session_id;
  var chip = document.createElement('span');
  var light = finished ? 'grey' : _statusColor(s.status);
  chip.className = 'tile lane-tile live-chip' + (finished ? ' done' : '');
  chip.setAttribute('data-session', sid);
  chip.setAttribute('data-lane', s.lane || '');
  chip.setAttribute('data-light', light);
  if (finished) { chip.setAttribute('data-finished', '1'); }
  else { chip.setAttribute('data-live', '1'); }
  chip.onclick = (function (theId) {
    return function (ev) { laneTileClick(ev, theId); };
  })(sid);
  var dot = document.createElement('span');
  dot.className = 'lt ' + light;
  var lbl = document.createElement('span');
  lbl.className = 'ttl';
  lbl.textContent = (s.label ? s.label : (s.lane + ' ' + (s.idx || '')));
  chip.appendChild(dot);
  chip.appendChild(lbl);
  if (finished) {
    var ck = document.createElement('span');
    ck.className = 'ck';
    ck.textContent = '✓';
    chip.appendChild(ck);
  }
  return chip;
}

// laneTileClick: a Paradigm-2 lane tile was clicked → open its inline panel.
// The tile no longer contains report links / a summary accordion, so the click
// reliably reaches openPanel. We still ignore clicks that land on an explicit
// control (a <details>/<summary> disclosure, an engine toggle, or an explicit
// link/button) before reaching the tile, so those keep their own behavior.
function laneTileClick(ev, sessionId) {
  var t = ev && ev.target;
  while (t && t.classList && !t.classList.contains('tile')) {
    if (t.tagName === 'SUMMARY' || t.tagName === 'A' ||
        t.tagName === 'BUTTON' || t.classList.contains('engtog')) {
      return;   // explicit control handles its own click
    }
    t = t.parentNode;
  }
  openPanel(sessionId);
}

// openLinkedPlanning(ev, planningSid): from a BUILD tile's "⛓ Planning: …" chip,
// open the matched planning session's panel WITHOUT also opening this build tile's
// panel (stopPropagation keeps the click off the tile's laneTileClick). The
// planning session's tile lives in the Planning column with data-session ==
// planningSid, so openPanel resolves it via _synthSessionRecord.
function openLinkedPlanning(ev, planningSid) {
  if (ev) ev.stopPropagation();
  if (planningSid) openPanel(planningSid);
}

// Start a brand-new managed terminal session for a lane (Wave-3 term_start),
// then refresh the bar and open its inline panel. backend defaults to claude.
async function newTermSession(lane, backend, opts) {
  backend = backend || 'claude';
  var payload = {project_id: PROJECT_ID, lane: lane, backend: backend};
  // Wave 6 seam: a seed hint (the source session id) rides into term_start so
  // Wave 7 can build the stage-handoff on top of it. term_start tolerates the
  // extra field today (start_session ignores it); Wave 7 wires it through.
  if (opts && opts.seed_session) payload.seed_session = opts.seed_session;
  // Wave 7 offer→confirm: for a BUILD lane, OFFER the most-recent plan set and
  // only prime on confirm. We fetch the read-only proposal, and if a plan set
  // exists, ask "Execute on this plan set?". YES → proceed (term_start primes).
  // NO → drop the seed and launch a bare build session (non-blocking).
  if (lane === 'build') {
    try {
      var qp = 'project_id=' + encodeURIComponent(PROJECT_ID) + '&lane=build';
      if (opts && opts.seed_session)
        qp += '&seed_session=' + encodeURIComponent(opts.seed_session);
      var pr = await fetch('/api/rnd/handoff_proposal?' + qp);
      var pd = await pr.json();
      if (pd && pd.ok && pd.has_plan_set) {
        var ps = pd.plan_set || {};
        var msg = 'Execute on this plan set? ' +
          (ps.title || ps.plan_dir || 'plan set') +
          ' — ' + (ps.impl_plan_rel || ps.master_plan_rel || '');
        if (!confirm(msg)) {
          // User declined the offer: launch without seeding a plan set.
          delete payload.seed_session;
        }
      }
    } catch (e) { /* proposal is advisory; never block the launch */ }
  }
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
  openPanel(sid);
  // v7 Wave 6: re-fetch the server-rendered board so the just-started session's
  // lane-column tile appears INSTANTLY (no page reload). The board is the single
  // source of truth — re-fetch, don't JS-inject — so dedupe stays correct.
  refreshBoard();
  // Re-sync indices/labels from the registry shortly after.
  setTimeout(repopulate, 600);
}

// openPanel(sessionId): expand (or scroll to) the session's INLINE panel in the
// #panelStack below the board. A second openPanel on an OPEN, non-minimized panel
// toggles it back to minimized (collapse-to-tile); an already-minimized panel
// re-expands. The session keeps running throughout — this only shows/hides the
// panel body. The panel header carries "– min" (minimizePanel), "× close"
// (closePanel — close-to-tile, NON-destructive) + "🗑 Kill" (killPanel,
// confirm-gated reap that also removes the tile).
function openPanel(sessionId) {
  // A LIVE managed terminal session → attach its PTY (as today). ANY other tile
  // (historical / discovered / imported) → SYNTHESIZE a panel record from its
  // DOM tile so the panel still opens with the split summary + a read-only body.
  var s = MANAGED[sessionId];
  var isLive = !!s;
  if (!s) {
    s = _synthSessionRecord(sessionId);
    if (!s) return;
  }
  var existing = PANELS[sessionId];
  if (existing && existing.el) {
    // Second click toggles minimize/expand (no kill, no re-mount).
    if (existing.el.classList.contains('minimized')) {
      existing.el.classList.remove('minimized');
      existing.el.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    } else {
      minimizePanel(sessionId);
    }
    renderSessionBar();
    return;
  }
  var stack = document.getElementById('panelStack');
  if (!stack) return;

  var panel = document.createElement('div');
  panel.className = 'panel';
  panel.setAttribute('data-session', sessionId);

  var bar = document.createElement('div');
  bar.className = 'pbar';
  var dot = document.createElement('span');
  dot.className = 'lt ' + _statusColor(s.status);
  var title = document.createElement('span');
  title.className = 'ti';
  title.textContent = (s.label ? s.label : (s.lane + ' ' + s.idx));
  // v8 Wave 4 — surface the LOADED trio skill (e.g. "build · Foreman" /
  // "planning · Crucible" / "research · researchPrime") so it is unambiguous
  // which skill this session is running. Omitted for skill-less lanes.
  var skillEl = document.createElement('span');
  skillEl.className = 'skl';
  var _skl = _skillForLane(s.lane || '');
  skillEl.textContent = _skl ? (s.lane + ' · ' + _skl) : (s.lane || '');
  skillEl.setAttribute('data-skill', _skl);
  var meta = document.createElement('span');
  meta.className = 'mt';
  meta.textContent = s.backend ? ('· ' + s.backend) : '';
  // v6 Wave 5: chain breadcrumb (R-1 → P-2 → …) — the lineage this session
  // belongs to. Filled async from /api/rnd/chain; each node is clickable →
  // openPanel(thatSession). Empty (hidden) for a session with no chain yet.
  var crumb = document.createElement('span');
  crumb.className = 'chaincrumb';
  crumb.setAttribute('data-session', sessionId);
  var sp = document.createElement('span');
  sp.className = 'sp';
  // Per-session engine toggle (◆ Claude / ✦ Gemini). Chosen once; flipping POSTs
  // term_set_engine to relaunch this LIVE session on the other engine in the same
  // worktree. Research can switch freely; plan/build stay Claude-only (the server
  // also enforces this). Historical/non-live sessions have no process to switch,
  // so the toggle is omitted there.
  var engEl = null;
  if (isLive) engEl = _buildEngineToggle(sessionId, s);
  // v5 Wave 1 — THREE visually + behaviorally distinct panel-header controls:
  //   (a) '–'  minimize  — collapse to a header strip; session keeps running.
  //   (b) '×'  CLOSE     — close-to-tile: tear down the panel DOM + transport
  //        ONLY. Does NOT kill the PTY / remove the worktree / drop the registry
  //        record / remove the lane tile. The session stays reopenable (click its
  //        tile to re-attach a live terminal or re-show the summary). Live AND
  //        historical panels use this same non-destructive close.
  //   (c) '🗑' KILL      — deliberate hard-kill, confirm-gated. Reaps the PTY +
  //        worktree (POST /api/rnd/term_kill), removes the MANAGED record AND the
  //        session's lane tile (gone). For a historical/non-live session with no
  //        live PTY, Kill still removes the tile/record cleanly (no orphan).
  var minBtn = document.createElement('button');
  minBtn.className = 'panelbtn min';
  minBtn.title = 'Minimize (keeps the session running)';
  minBtn.textContent = '–';
  minBtn.onclick = function (e) { e.stopPropagation(); minimizePanel(sessionId); };
  // v6 Wave 3: maximize (▢) — toggle the panel to fill the cockpit viewport
  // (.panel.maxd) and back to its prior size. Either way the xterm terminal is
  // re-fit so cols/rows track the new area (no freeze / clip).
  var maxBtn = document.createElement('button');
  maxBtn.className = 'panelbtn max';
  maxBtn.title = 'Maximize / restore (re-fits the terminal)';
  maxBtn.textContent = '▢';
  maxBtn.onclick = function (e) { e.stopPropagation(); maximizePanel(sessionId); };
  var closeBtn = document.createElement('button');
  closeBtn.className = 'panelbtn close';
  closeBtn.title = 'Close panel (keeps the session — reopen from its tile)';
  closeBtn.textContent = '×';
  closeBtn.onclick = function (e) { e.stopPropagation(); closePanel(sessionId); };
  var killBtn = document.createElement('button');
  killBtn.className = 'panelbtn hardkill';
  killBtn.title = 'Kill this session (terminate + remove its tile)';
  killBtn.textContent = '🗑';
  killBtn.onclick = function (e) { e.stopPropagation(); killPanel(sessionId); };
  //   (d) '✕'  DELETE     — v9 Wave 1: TRUE delete, the red top-right control.
  //        VISUALLY + behaviorally DISTINCT from KILL (🗑): kill ENDS a *running*
  //        session (keeps the record so it's resumable); delete REMOVES the
  //        record entirely (POST /api/rnd/term_delete) — the registry record +
  //        effort pointer-records + cached summary are dropped, so the tile is
  //        gone and STAYS gone across a reload. The produced DOCUMENTS are KEPT
  //        on disk (Option A). Confirm-gated.
  var delBtn = document.createElement('button');
  delBtn.className = 'panelbtn delete';
  delBtn.title = 'Delete this session from Anchor (removes the record; keeps its documents)';
  delBtn.textContent = '✕';
  delBtn.onclick = function (e) { e.stopPropagation(); deletePanel(sessionId); };
  bar.appendChild(dot); bar.appendChild(title);
  bar.appendChild(skillEl); bar.appendChild(meta);
  bar.appendChild(crumb);
  bar.appendChild(sp);
  if (engEl) {
    var englbl = document.createElement('span');
    englbl.className = 'englbl';
    englbl.textContent = 'engine';
    bar.appendChild(englbl);
    bar.appendChild(engEl);
  }
  bar.appendChild(minBtn); bar.appendChild(maxBtn);
  bar.appendChild(closeBtn); bar.appendChild(killBtn);
  bar.appendChild(delBtn);

  // Panel inner body STACKS (mockup Paradigm-2): a split summary block on TOP
  // (materials left + role-tagged doc links right, EQUAL height), then a
  // full-width, vertically-resizable terminal pane BELOW.
  var pin = document.createElement('div');
  pin.className = 'pin';
  // v6 Wave 3: the .pin body is the FREE-resize box (CSS resize:both). Restore
  // this session's persisted panel rect (width + height) if the user resized it
  // earlier this page load (_panelRects, keyed by session_id).
  var _rect = _panelRects[sessionId];
  if (_rect) {
    if (_rect.w) pin.style.width = _rect.w;
    if (_rect.h) pin.style.height = _rect.h;
  }

  // (1) Split summary block — filled async from /api/rnd/session_summary +
  //     /api/rnd/session_doc_roles. Absent → just a thin loading note.
  var summ = document.createElement('div');
  summ.className = 'summary split';
  summ.setAttribute('data-session', sessionId);
  summ.innerHTML = '<div class="summ-loading">loading session summary…</div>';
  pin.appendChild(summ);

  // (2) The terminal pane (resizable wrapper) with a bar + the xterm host.
  var tpane = document.createElement('div');
  tpane.className = 'tpane';
  // Persisted per-session height (in-memory): restore if the user resized it.
  if (_panelHeights[sessionId]) tpane.style.height = _panelHeights[sessionId];
  var tbar = document.createElement('div');
  tbar.className = 'tbar';
  var lab = document.createElement('span');
  lab.className = 'lab';
  lab.textContent = (isLive ? (s.backend || 'terminal') : 'log') + ' · ' + s.session_id;
  var rz = document.createElement('span');
  rz.className = 'rzhint';
  rz.textContent = '⤡ drag the panel corner to resize';
  tbar.appendChild(lab);
  tbar.appendChild(rz);
  var host = document.createElement('div');
  host.className = 'panel-body term-host';
  host.setAttribute('data-session', sessionId);
  tpane.appendChild(tbar);
  tpane.appendChild(host);
  pin.appendChild(tpane);

  // v6 Wave 5: a research session's panel gets an "Advance to Planning →" bar
  // (mockup Step 3). One click starts a NEW linked planning tile seeded from this
  // research (advanceSession → POST /api/rnd/advance_session). Shown ONLY for the
  // research lane this wave (the plan→build auto path is Wave 6).
  if ((s.lane || '') === 'research') {
    var adv = document.createElement('div');
    adv.className = 'advbar';
    var advt = document.createElement('span');
    advt.className = 'advt';
    advt.innerHTML = 'When this research is done, advance it to a new linked '
      + '<b>planning</b> session, seeded from this work:';
    var advb = document.createElement('button');
    advb.className = 'advbtn';
    advb.type = 'button';
    advb.textContent = 'Advance to Planning →';
    advb.onclick = function (e) {
      e.stopPropagation();
      advanceSession(sessionId, 'planning');
    };
    adv.appendChild(advt);
    adv.appendChild(advb);
    pin.appendChild(adv);
  }

  // v6 Wave 9 (polish 1): a PLANNING session's panel gets an explicit, friendly
  // "Finish → Build" bar (mirrors the research advance bar style). One click POSTs
  // /api/rnd/finish_to_build → captures the plan set, marks THIS planning session
  // done (non-destructive — its worktree is kept, the tile stays reopenable), and
  // auto-opens ONE linked build session. Honest when there is no plan set yet
  // (shows a small note, opens no build). Shown ONLY for the plan/planning lane.
  if ((s.lane || '') === 'plan' || (s.lane || '') === 'planning') {
    var fbb = document.createElement('div');
    fbb.className = 'fbbar';
    var fbt = document.createElement('span');
    fbt.className = 'fbt';
    fbt.innerHTML = 'When this plan is ready, finish it and advance to a new '
      + 'linked <b>build</b> session that executes on it:';
    var fbbtn = document.createElement('button');
    fbbtn.className = 'fbbtn';
    fbbtn.type = 'button';
    fbbtn.textContent = 'Finish → Build →';
    fbbtn.onclick = function (e) {
      e.stopPropagation();
      finishToBuild(sessionId);
    };
    fbb.appendChild(fbt);
    fbb.appendChild(fbbtn);
    pin.appendChild(fbb);
  }

  panel.appendChild(bar);
  panel.appendChild(pin);
  stack.appendChild(panel);

  PANELS[sessionId] = {el: panel, body: host, term: null, transport: null,
                       tpane: tpane, pin: pin, fit: null, ro: null, pinRo: null,
                       maxd: false};
  if (isLive) {
    // LIVE managed terminal: mount xterm over the v3 transport (UNCHANGED).
    _mountTerminal(sessionId, host);
  } else {
    // HISTORICAL/discovered session: NO live PTY. Show a read-only note (the
    // summary above carries the materials + doc links). We try to load a
    // transcript/log if one exists; otherwise a "session complete" note.
    _mountReadOnlyBody(sessionId, host, s);
  }
  _loadPanelSummary(sessionId, summ);
  _loadChainBreadcrumb(sessionId, crumb);
  _loadGrassOriginChip(sessionId, crumb);
  _wirePanelResize(sessionId, tpane);
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  renderSessionBar();
}

// _CHAIN_ABBR: lane → the breadcrumb node prefix (research→R, planning/plan→P,
// build→B). Mirrors the mockup's R-/P-/B- labels.
var _CHAIN_ABBR = {research: 'R', planning: 'P', plan: 'P', build: 'B'};

// _loadChainBreadcrumb(sessionId, host): fetch this session's lineage chain and
// render a clickable breadcrumb (R-1 → P-2 → …) into the panel header. Read-only
// (GET /api/rnd/chain, ?token=); each node opens that session's panel. A chain of
// one (no lineage) renders nothing. Best-effort — any error leaves the crumb empty.
//
// v8 Wave 7 — full chain navigation on the now-DURABLE artifacts (W2/W5):
//   - Renders for EVERY panel — live AND done/historical (openPanel calls this
//     unconditionally; a done/historical tile resolves via _synthSessionRecord),
//     so you can navigate the chain from a finished build the same as from a live
//     research session.
//   - Each node shows a status LIGHT (green/amber/red/grey) + the lane + a short
//     label, so a node's state is visible at a glance (not only on hover).
//   - Click a sibling node → openPanel(thatId): if it is LIVE it focuses/attaches
//     its terminal; if DONE/historical it opens that session's DETAIL view (the W5
//     read-only body — summary + produced docs + "Continue the dialog"). So you can
//     move research→plan→build AND back build→plan→research, landing on real content.
//   - HONEST partial chains: members.length < 2 → render nothing (a lone session
//     with no siblings shows no misleading breadcrumb; no fabricated nodes — the
//     server only emits the records that actually exist for this chain).
function _loadChainBreadcrumb(sessionId, host) {
  if (!host) return;
  var url = '/api/rnd/chain?project_id=' + encodeURIComponent(PROJECT_ID)
    + '&session=' + encodeURIComponent(sessionId) + _tokenQ();
  fetch(url, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var members = (d && d.ok && d.members) ? d.members : [];
      host.innerHTML = '';
      if (members.length < 2) {
        // No managed/registry chain (e.g. a DISCOVERED build session). Fall back
        // to the static Build→Planning tie carried on the tile (Option A): render
        // a 2-node breadcrumb (P <label> → B <label>) so the imported build still
        // shows — and can navigate to — the plan it executed on.
        _renderStaticTieCrumb(sessionId, host);
        return;
      }
      members.forEach(function (m, i) {
        if (i > 0) {
          var sep = document.createElement('span');
          sep.className = 'cc-sep';
          sep.textContent = '→';
          host.appendChild(sep);
        }
        var node = document.createElement('span');
        var lane = m.lane || '';
        var abbr = _CHAIN_ABBR[lane] || (lane ? lane.charAt(0).toUpperCase() : '?');
        node.className = 'cc-node' + (m.session_id === sessionId ? ' cur' : '');
        node.setAttribute('data-session', m.session_id);
        node.setAttribute('data-lane', lane);
        // A small status light (locked color map) makes each node's state visible
        // at a glance — a done sibling reads amber, a live one green, etc.
        var lt = document.createElement('span');
        lt.className = 'cc-light ' + _statusColor(m.status || '');
        node.appendChild(lt);
        var txt = document.createElement('span');
        txt.className = 'cc-txt';
        txt.textContent = m.label ? m.label : (abbr + ' ' + lane);
        node.appendChild(txt);
        node.title = lane + ' · ' + (m.status || '');
        node.onclick = (function (theId) {
          return function (ev) { ev.stopPropagation(); openPanel(theId); };
        })(m.session_id);
        host.appendChild(node);
      });
    })
    .catch(function () {});
}

// _loadGrassOriginChip(sessionId, host): v10 Wave 4 (D8). If this session's chain
// carries a grass_origin (it was exported/promoted from a grass idea, OR is a
// downstream plan/build that inherited the stamp), render a "from grass: <idea>"
// back-link chip into the panel header. Clicking it opens the Grass workbench
// focused on that idea (openGrassWorkbench → selectGrassIdea). HONEST: no
// grass_origin in the chain → no chip (no fabricated back-link). Read-only
// (GET /api/rnd/chain, ?token=); best-effort (any error leaves no chip).
function _loadGrassOriginChip(sessionId, host) {
  if (!host) return;
  var url = '/api/rnd/chain?project_id=' + encodeURIComponent(PROJECT_ID)
    + '&session=' + encodeURIComponent(sessionId) + _tokenQ();
  fetch(url, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var members = (d && d.ok && d.members) ? d.members : [];
      // Find a grass_origin anywhere in the chain (this session or a sibling).
      var origin = '';
      for (var i = 0; i < members.length; i++) {
        var go = (members[i] && members[i].grass_origin) || '';
        if (go) { origin = go; break; }
      }
      // HONEST: empty origin → no chip (no fabricated back-link).
      if (!origin) return;
      // Ensure the grass data is loaded so we can resolve the idea title AND
      // detect a DELETED origin (FIX 3 dead-chip). _loadGrassData is idempotent.
      var done = function () {
        var rec = (_grassData && _grassData[origin]) ? _grassData[origin] : null;
        var chip = document.createElement('span');
        chip.className = 'grassorigin';
        chip.setAttribute('data-grass-origin', origin);
        if (!rec) {
          // DEAD CHIP: the originating idea no longer exists — render greyed/
          // disabled, no live link (FIX 3). Keep the stamp; be honest in the UI.
          chip.classList.add('removed');
          chip.setAttribute('data-grass-removed', '1');
          chip.title = 'The originating grass idea was removed';
          chip.textContent = '🌱 from grass (idea removed)';
          host.appendChild(chip);
          return;
        }
        var label = (rec.title || rec.short_id || origin);
        chip.title = 'This work traces back to a grass idea — click to open it';
        chip.textContent = '🌱 from grass: ' + (label.length > 40
          ? label.slice(0, 40) + '…' : label);
        chip.onclick = function (ev) {
          ev.stopPropagation();
          if (typeof openGrassWorkbench === 'function') openGrassWorkbench();
          // Focus the originating idea once the workbench list has rendered.
          setTimeout(function () {
            try { selectGrassIdea(origin); } catch (e) {}
          }, 250);
        };
        host.appendChild(chip);
      };
      if (_grassData && Object.keys(_grassData).length) { done(); return; }
      try { _loadGrassData().then(done).catch(done); } catch (e) { done(); }
    })
    .catch(function () {});
}

// _resolveGrassOriginChips(root): resolve every server-rendered board-tile
// "from grass" chip placeholder (v10 Wave 4 FIX 2/3). The server emits a chip
// stub carrying ONLY data-grass-origin (the SAFE idea id) + data-grass-pending;
// here we resolve its label, dead-state, and click handler against the loaded
// _grassData — exactly like the panel chip (shared dead-chip path). Idempotent:
// a chip is processed once (its pending marker is cleared). Best-effort.
function _resolveGrassOriginChips(root) {
  root = root || document;
  var pend = root.querySelectorAll('.grassorigin[data-grass-pending]');
  for (var i = 0; i < pend.length; i++) {
    var el = pend[i];
    var origin = el.getAttribute('data-grass-origin') || '';
    el.removeAttribute('data-grass-pending');
    if (!origin) { el.style.display = 'none'; continue; }
    var rec = (_grassData && _grassData[origin]) ? _grassData[origin] : null;
    if (!rec) {
      // DEAD CHIP on the tile: greyed/disabled, no live link (FIX 3).
      el.classList.add('removed');
      el.setAttribute('data-grass-removed', '1');
      el.title = 'The originating grass idea was removed';
      el.textContent = '🌱 from grass (idea removed)';
      el.onclick = null;
      continue;
    }
    var label = (rec.title || rec.short_id || origin);
    el.title = 'This work traces back to a grass idea — click to open it';
    el.textContent = '🌱 from grass: ' + (label.length > 40
      ? label.slice(0, 40) + '…' : label);
    (function (oid) {
      el.onclick = function (ev) {
        ev.stopPropagation();
        if (typeof openGrassWorkbench === 'function') openGrassWorkbench();
        setTimeout(function () {
          try { selectGrassIdea(oid); } catch (e) {}
        }, 250);
      };
    })(origin);
  }
}

// _renderStaticTieCrumb(sessionId, host): the DISCOVERED build→planning fallback
// breadcrumb (Option A). When a session has no managed/registry chain, read the
// session's tile for data-linked-planning (+ label) and, if present, render a
// 2-node breadcrumb "P <label> → B <label>" into the panel header. The P node
// opens the matched planning session's panel; the B node is the current one.
// No tie on the tile → nothing rendered (honest; no fabricated chain).
function _renderStaticTieCrumb(sessionId, host) {
  if (!host) return;
  var tile = document.querySelector('.tile[data-session="' + _cssEsc(sessionId) + '"]');
  if (!tile) return;
  var planSid = tile.getAttribute('data-linked-planning');
  if (!planSid) return;
  var label = tile.getAttribute('data-linked-planning-label') || '';
  function _node(abbr, lab, isCur, openSid) {
    var node = document.createElement('span');
    node.className = 'cc-node' + (isCur ? ' cur' : '');
    var lt = document.createElement('span');
    lt.className = 'cc-light grey';
    node.appendChild(lt);
    var txt = document.createElement('span');
    txt.className = 'cc-txt';
    txt.textContent = lab ? (abbr + ' ' + lab) : abbr;
    node.appendChild(txt);
    if (openSid) {
      node.onclick = function (ev) { ev.stopPropagation(); openPanel(openSid); };
    }
    return node;
  }
  host.appendChild(_node('P', label, false, planSid));
  var sep = document.createElement('span');
  sep.className = 'cc-sep';
  sep.textContent = '→';
  host.appendChild(sep);
  host.appendChild(_node('B', label, true, null));
}

// _synthSessionRecord(sessionId): build a MANAGED-shaped record for a NON-live
// tile from its DOM, so openPanel can render a panel for a historical /
// discovered / imported session. Reads the tile's data-lane + data-light (the
// locked status color the server stamped) off the page. Returns null only if no
// such tile exists.
function _synthSessionRecord(sessionId) {
  var tile = document.querySelector('.tile[data-session="' + _cssEsc(sessionId) + '"]');
  if (!tile) return null;
  var lane = tile.getAttribute('data-lane') || '';
  var light = tile.getAttribute('data-light') || 'grey';
  // Map the light color back to a coarse status (only for the header dot/title).
  var status = (light === 'green') ? 'running'
             : (light === 'amber') ? 'done'
             : (light === 'red') ? 'failed' : 'idle';
  var ttlEl = tile.querySelector('.ttl');
  var label = ttlEl ? (ttlEl.textContent || '').trim() : '';
  return {session_id: sessionId, lane: lane, backend: '', status: status,
          label: label, idx: '', historical: true};
}

// CSS.escape shim for the attribute selector (older engines lack CSS.escape).
function _cssEsc(s) {
  if (window.CSS && CSS.escape) return CSS.escape(s);
  return String(s).replace(/["\\\]]/g, '\\$&');
}

// _buildEngineToggle(sessionId, s): the ◆ Claude / ✦ Gemini toggle for the panel
// bar. The currently-selected engine (s.backend, default claude) is highlighted;
// clicking the OTHER engine POSTs term_set_engine (relaunch in the same worktree)
// and updates the record + toggle on success. Returns the .engtog element.
function _buildEngineToggle(sessionId, s) {
  var cur = (s && s.backend) || 'claude';
  var tog = document.createElement('span');
  tog.className = 'engtog';
  tog.title = 'Chosen once; flip to switch this session to the other engine.';
  [['claude', '◆ Claude'], ['gemini', '✦ Gemini']].forEach(function (pair) {
    var eng = pair[0];
    var b = document.createElement('b');
    b.textContent = pair[1];
    b.setAttribute('data-engine', eng);
    if (eng === cur) b.className = 'on';
    b.onclick = function (e) {
      e.stopPropagation();
      if (eng === ((MANAGED[sessionId] || {}).backend || cur)) return;  // already on it
      setSessionEngine(sessionId, eng, tog);
    };
    tog.appendChild(b);
  });
  return tog;
}

// setSessionEngine(sessionId, engine, tog): flip a LIVE session to the other
// engine via /api/rnd/term_set_engine (relaunch in the same worktree). On success
// update the MANAGED record + the toggle's on-state; on refusal (e.g. plan/build
// is Claude-only) alert and leave the toggle unchanged.
async function setSessionEngine(sessionId, engine, tog) {
  var r, data;
  try {
    r = await _postJson('/api/rnd/term_set_engine', {session: sessionId, engine: engine});
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_set_engine', {session: sessionId, engine: engine});
      data = await r.json();
    }
  } catch (e) { alert('[engine switch error] ' + e.message); return; }
  if (!data || !data.ok) {
    alert('[engine switch refused] ' + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  if (MANAGED[sessionId]) MANAGED[sessionId].backend = engine;
  if (tog) {
    var bs = tog.querySelectorAll('b');
    for (var i = 0; i < bs.length; i++) {
      bs[i].className = (bs[i].getAttribute('data-engine') === engine) ? 'on' : '';
    }
  }
  // Re-sync the registry shortly (the relaunch mints a fresh PTY in the worktree).
  setTimeout(repopulate, 600);
}

// _mountReadOnlyBody (v5 Wave 2): a NON-live (done/historical) session has no
// PTY. Instead of a dead-end "session complete" note, render a REAL past-session
// view in the terminal host: the SKILL invoked, the PROMPTS asked, and the
// ACTIONS/files produced (from the cached session summary), plus a "Continue in a
// live session" button that starts a NEW live session in the SAME lane seeded
// with this session's context. Honest placeholders when a field is absent.
function _mountReadOnlyBody(sessionId, host, s) {
  var runningNote = (s.status === 'running')
    ? '<div class="ro-note">Session is running in the background — no live '
      + 'terminal attached.</div>'
    : '';
  // Skeleton with a Continue button (always available for a historical session)
  // and a region we fill async from the cached session summary.
  host.innerHTML = runningNote
    + '<div class="ro-past" data-session="' + _esc(sessionId) + '">'
    + '<div class="ro-actions">'
    + '<button class="ro-continue" type="button">▶ Continue in a live session</button>'
    + '</div>'
    + '<div class="ro-detail"><div class="summ-loading">loading past-session '
    + 'summary…</div></div>'
    + '</div>';
  var btn = host.querySelector('.ro-continue');
  if (btn) btn.onclick = function (e) {
    e.stopPropagation();
    continueSession(sessionId, s.lane);
  };
  var detail = host.querySelector('.ro-detail');
  _fillPastSessionDetail(sessionId, (s && s.lane) || '', detail);
}

// _fillPastSessionDetail: fetch the cached session summary and render the
// skill/prompts/produced-files (v5 Wave 2). Read-only; honest placeholders for
// absent fields. The summary GET returns the full cached structured dict, so the
// new skill/prompts/actions fields ride along.
function _fillPastSessionDetail(sessionId, lane, detail, _tries) {
  if (!detail) return;
  // v8 Wave 5 — a just-killed session's durable summary is generated in the
  // BACKGROUND (kill schedules it). The GET returns status:'generating' until it
  // lands, so we poll a bounded number of times before painting the honest
  // "being generated" placeholder — the detail then shows the REAL produced
  // docs/summary as soon as it caches (no-loss close-out), not a dead-end.
  _tries = _tries || 0;
  var sUrl = '/api/rnd/session_summary?pid=' + encodeURIComponent(PROJECT_ID)
    + '&lane=' + encodeURIComponent(lane)
    + '&session=' + encodeURIComponent(sessionId);
  fetch(sUrl, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      var summ = (d && d.status === 'ready' && d.summary) ? d.summary : null;
      if (!summ && d && d.status === 'generating' && _tries < 20) {
        setTimeout(function () {
          _fillPastSessionDetail(sessionId, lane, detail, _tries + 1);
        }, 500);
        return;
      }
      detail.innerHTML = _renderPastSession(summ);
    })
    .catch(function () {
      detail.innerHTML = '<div class="ro-note">Summary unavailable.</div>';
    });
}

// _renderPastSession(summary): the skill/prompts/produced-files block for a
// historical session's read-only body. Every section is honest — absent data
// renders an explicit placeholder, never fabricated content.
function _renderPastSession(summary) {
  if (!summary) {
    return '<div class="ro-note">No cached summary yet for this session — '
      + 'it is being generated. Reopen shortly, or continue it live above.</div>';
  }
  var out = [];
  var skill = (summary.skill || '').trim ? (summary.skill || '').trim() : summary.skill;
  out.push('<div class="ro-sec"><span class="ro-k">Skill invoked</span><span>'
    + (skill ? _esc(skill) : '<i>not recorded</i>') + '</span></div>');
  var prompts = summary.prompts || [];
  out.push('<div class="ro-sec"><span class="ro-k">Prompts asked</span></div>');
  if (prompts.length) {
    var pl = ['<ul class="ro-list">'];
    for (var i = 0; i < prompts.length; i++)
      pl.push('<li>' + _esc(prompts[i]) + '</li>');
    pl.push('</ul>');
    out.push(pl.join(''));
  } else {
    out.push('<div class="ro-note"><i>No prompts recorded for this session.</i></div>');
  }
  var actions = summary.actions || [];
  out.push('<div class="ro-sec"><span class="ro-k">Files produced</span></div>');
  if (actions.length) {
    var al = ['<ul class="ro-list">'];
    for (var j = 0; j < actions.length; j++) {
      var a = actions[j];
      var lbl = (a && (a.label || a.rel || a.job_id)) || '';
      al.push('<li>' + _esc(lbl) + '</li>');
    }
    al.push('</ul>');
    out.push(al.join(''));
  } else {
    out.push('<div class="ro-note"><i>No files recorded for this session.</i></div>');
  }
  return out.join('');
}

// continueSession(sessionId, lane): v5 Wave 2 — POST /api/rnd/continue_session
// (token-authed) to start a NEW live session in the SAME lane, seeded with the
// prior session's summary/context. The ORIGINAL session is never mutated. On
// success the new session is added to MANAGED and its panel opened/attached
// (reusing the live-session panel path).
async function continueSession(sessionId, lane) {
  var payload = {project_id: PROJECT_ID, lane: lane, source_session: sessionId};
  var r, data;
  try {
    r = await _postJson('/api/rnd/continue_session', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/continue_session', payload);
      data = await r.json();
    }
  } catch (e) { alert('[continue error] ' + e.message); return; }
  if (!data || !data.ok || !data.session) {
    alert('[continue refused] ' + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || lane, backend: rec.backend || 'claude',
    status: rec.status || 'running', label: rec.label || '',
    idx: (_laneCounters[rec.lane || lane] = (_laneCounters[rec.lane || lane] || 0) + 1)
  };
  renderSessionBar();
  // v10.1 FIX 1 — Restart-in-place: the cockpit's only terminal surface is an
  // inline panel in #panelStack. continueSession mints a BRAND-NEW session id,
  // so openPanel(sid) would stack a SECOND panel below the still-open source.
  // Instead: carry the source panel's geometry onto the new id, open the new
  // panel, then _closePanel the SOURCE (tears down its DOM/transport ONLY —
  // never the MANAGED record or the lane/board tile, so the source session
  // stays reopenable). The new session keeps its own board tile (the v6
  // new-tile-per-session invariant is preserved). NEVER killPanel/term_kill
  // (those reap the worktree/record).
  if (_panelRects[sessionId] && !_panelRects[sid]) _panelRects[sid] = _panelRects[sessionId];
  if (_panelHeights[sessionId] && !_panelHeights[sid]) _panelHeights[sid] = _panelHeights[sessionId];
  openPanel(sid);
  if (sid !== sessionId) _closePanel(sessionId);
  setTimeout(repopulate, 600);
}

// advanceSession(sourceId, toLane): v6 Wave 5 — MANUAL advance research →
// planning. POST /api/rnd/advance_session (token-authed) to start a NEW LINKED
// session in toLane (defaults 'planning'), seeded with the SOURCE session's
// grounded summary/report; the SOURCE record is never mutated (server reuses the
// read-only continue-seed builder). On success the new session is added to
// MANAGED and its panel opened (reusing the continueSession success path); the
// new tile lands in the SAME chain as the source.
async function advanceSession(sourceId, toLane) {
  toLane = toLane || 'planning';
  var payload = {project_id: PROJECT_ID, source_session: sourceId, to_lane: toLane};
  var r, data;
  try {
    r = await _postJson('/api/rnd/advance_session', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/advance_session', payload);
      data = await r.json();
    }
  } catch (e) { alert('[advance error] ' + e.message); return; }
  if (!data || !data.ok || !data.session) {
    alert('[advance refused] ' + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  var rec = data.session;
  var sid = rec.session_id;
  MANAGED[sid] = {
    session_id: sid, lane: rec.lane || toLane, backend: rec.backend || 'claude',
    status: rec.status || 'running', label: rec.label || '',
    chain_id: rec.chain_id || '', parent_session_id: rec.parent_session_id || sourceId,
    idx: (_laneCounters[rec.lane || toLane] = (_laneCounters[rec.lane || toLane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  // v10 Wave 2: the next-stage prompt is delivered PASTED-but-UNSENT (pending
  // paste, flushed by the terminal transport after the skill greets). Hint the
  // user that it is sitting in the input line for review — nothing was submitted.
  _flashPendingPasteHint(sid);
  // v7 Wave 6: instant-in-column tile for the advanced (build) session.
  refreshBoard();
  setTimeout(repopulate, 600);
}

// finishToBuild(planningId): v6 Wave 9 (polish 1) — the explicit, NON-destructive
// plan→build advance. POSTs /api/rnd/finish_to_build (token-gated): the server
// captures the plan set, marks THIS planning session done WITHOUT reaping its
// worktree (it stays a reopenable finished tile — close-to-tile philosophy), then
// auto-advances to ONE linked build (idempotent server-side). On success we mint
// the build tile (_addAutoBuildTile + note, the SAME path the hard-kill auto-build
// uses) and move the planning session to a greyed FINISHED tile (reusing the
// Wave-4 finished-tile path). With NO plan set the server honestly returns
// auto_build:null + a reason → we show a small note and create no build.
async function finishToBuild(planningId) {
  var payload = {project_id: PROJECT_ID, session: planningId};
  var r, data;
  try {
    r = await _postJson('/api/rnd/finish_to_build', payload);
    data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/finish_to_build', payload);
      data = await r.json();
    }
  } catch (e) { alert('[finish→build error] ' + e.message); return; }
  if (!data || !data.ok) {
    alert('[finish→build refused] '
      + ((data && (data.error || data.reason)) || 'unknown'));
    return;
  }
  if (data.auto_build && data.auto_build.session_id) {
    // Move the planning session to a finished (greyed, reopenable) tile — it is
    // DONE but its worktree/record persist (non-destructive). Then mint the build.
    _finishPlanningTile(planningId);
    _addAutoBuildTile(data.auto_build);
  } else {
    // Honest: no plan set yet → nothing to build. Surface a small inline note on
    // the planning panel's finish bar (no tile is created, the session stays live).
    _flashNoPlanNote(planningId, (data.reason || 'no plan set yet'));
  }
  // v7 Wave 6: refresh the board so the planning→finished + new build tiles
  // (the lane-column tiles) update instantly without a page reload.
  refreshBoard();
  setTimeout(repopulate, 600);
}

// _finishPlanningTile(sessionId): move a now-DONE planning session from the LIVE
// (MANAGED) map to the FINISHED map (greyed, reopenable tile — Wave-4 path) and
// close its open panel. The registry record + worktree are KEPT server-side (the
// finish was non-destructive); repopulate() will re-confirm it as a terminal tile.
function _finishPlanningTile(sessionId) {
  var s = MANAGED[sessionId];
  if (s) {
    FINISHED[sessionId] = {
      session_id: sessionId, lane: s.lane || 'planning',
      backend: s.backend || '', status: 'done', label: s.label || '',
      created_at: s.created_at || 0, chain_id: s.chain_id || '',
      parent_session_id: s.parent_session_id || '', idx: s.idx || 0
    };
    delete MANAGED[sessionId];
  }
  _closePanel(sessionId);
  renderSessionBar();
}

// _flashNoPlanNote(sessionId, reason): when finish→build finds no plan set, show
// a brief honest note in the planning panel's finish bar (no build fabricated).
function _flashNoPlanNote(sessionId, reason) {
  try {
    var p = PANELS[sessionId];
    var bar = p && p.el ? p.el.querySelector('.fbbar') : null;
    if (!bar) return;
    var old = bar.querySelector('.fbnote');
    if (old && old.parentNode) old.parentNode.removeChild(old);
    var note = document.createElement('span');
    note.className = 'fbnote';
    note.textContent = 'No plan set yet — nothing to build (' + reason + ')';
    bar.appendChild(note);
    setTimeout(function () {
      if (note && note.parentNode) note.parentNode.removeChild(note);
    }, 6000);
  } catch (e) { /* advisory only */ }
}

// Per-session terminal-pane height (in-memory persistence across minimize /
// re-open within this page load). Keyed by session_id → CSS height string.
var _panelHeights = {};
// v6 Wave 3: per-session PANEL rect (the freely-resized .pin body's CSS width +
// height). Keyed by session_id → {w, h}. Restored on re-open; NOT applied while
// the panel is maximized (maxd) so restore returns to the pre-maximize size.
var _panelRects = {};

// _loadPanelSummary(sessionId, host): fill the split summary — materials LEFT
// (.smat: goal / North-Star / what-was-asked / effort) from the cached session
// summary, role-tagged doc links RIGHT (.slinks) from session_doc_roles. Both
// fetches are read-only; absent fields / roles are simply not rendered. The
// terminal mounts regardless (the summary is advisory chrome).
function _loadPanelSummary(sessionId, host) {
  if (!host) return;
  // The lane comes from the MANAGED record for a live session, else from the
  // page tile (historical/discovered) so the summary/doc-roles fetch keys on the
  // right (pid, lane, session).
  var s = MANAGED[sessionId] || _synthSessionRecord(sessionId);
  var lane = (s && s.lane) || '';
  // session_id here is the MANAGED (live-terminal) id; its lane is the trio lane
  // (research/plan/build). The summary/doc-roles endpoints key on (pid, lane,
  // session). A live terminal session may have no cached trio-session summary
  // yet — that's fine; we render whatever resolves and omit the rest.
  var sUrl = '/api/rnd/session_summary?pid=' + encodeURIComponent(PROJECT_ID)
    + '&lane=' + encodeURIComponent(lane)
    + '&session=' + encodeURIComponent(sessionId);
  var rUrl = '/api/rnd/session_doc_roles?pid=' + encodeURIComponent(PROJECT_ID)
    + '&lane=' + encodeURIComponent(lane)
    + '&session=' + encodeURIComponent(sessionId)
    + _tokenQ();
  var summary = null, roles = {}, buildDeliv = null;
  function _paint() {
    host.innerHTML = _renderSplitSummary(summary, roles, lane, buildDeliv);
  }
  fetch(sUrl, _jsonHdrs())
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d && d.status === 'ready' && d.summary) summary = d.summary;
    })
    .catch(function () {})
    .then(function () { return fetch(rUrl, _jsonHdrs()); })
    .then(function (r) { return r.json(); })
    .then(function (d) { if (d && d.ok && d.roles) roles = d.roles; })
    .catch(function () {})
    .then(function () {
      // v5 Wave 4 — a BUILD session's panel surfaces ITS resolved deliverable
      // (or an honest "none yet" placeholder). Read-only; never fabricated.
      if (lane !== 'build') return null;
      var dUrl = '/api/rnd/build_deliverable?pid=' + encodeURIComponent(PROJECT_ID)
        + '&lane=build&session=' + encodeURIComponent(sessionId) + _tokenQ();
      return fetch(dUrl, _jsonHdrs())
        .then(function (r) { return r.json(); })
        .then(function (d) { if (d && d.ok) buildDeliv = d; })
        .catch(function () {});
    })
    .catch(function () {})
    .then(_paint);
}

// _renderSplitSummary(summary, roles, lane): the EQUAL-HEIGHT two-column split.
// LEFT (.smat) = materials; the effort line uses margin-top:auto so it sinks to
// the bottom. RIGHT (.slinks) = role-tagged doc links; a second link group (when
// present) uses .slh.two (margin-top:auto) so it pins to the bottom — making both
// columns fill the same height per the mockup.
function _renderSplitSummary(summary, roles, lane, buildDeliv) {
  var L = [];   // left materials
  // v5 Wave 4 — a BUILD panel shows ITS deliverable (resolved → a link; absent →
  // an honest placeholder). Rendered FIRST so it is prominent in the materials.
  if (lane === 'build' && buildDeliv) {
    if (buildDeliv.resolved && buildDeliv.deliverable) {
      var bd = buildDeliv.deliverable;
      L.push('<div class="bdeliv resolved"><span class="k">Deliverable</span>'
        + '<a class="doc" href="' + _esc(bd.href || '#') + '" target="_blank" '
        + 'rel="noopener">' + _esc(bd.name || bd.path || 'deliverable')
        + '<span class="role">' + _esc(bd.type || '') + '</span></a></div>');
    } else {
      L.push('<div class="bdeliv none">' + _esc(buildDeliv.reason
        || 'no deliverable pinned yet') + ' — pin one</div>');
    }
  }
  if (summary) {
    if (summary.title) L.push('<div class="sgoal">' + _esc(summary.title) + '</div>');
    if (summary.north_star) L.push('<div class="row"><span class="k">North Star</span><span>' + _esc(summary.north_star) + '</span></div>');
    if (summary.what_was_asked) L.push('<div class="row"><span class="k">Asked</span><span>' + _esc(summary.what_was_asked) + '</span></div>');
    if (summary.when_run) L.push('<div class="row"><span class="k">When run</span><span>' + _esc(summary.when_run) + '</span></div>');
    var eff = '';
    if (summary.hasOwnProperty('effort')) {
      if (summary.effort === null) eff = 'imported — no run metrics';
      else if (summary.effort) {
        var secs = ((summary.effort.wall_clock_ms || 0) / 1000).toFixed(1);
        eff = _esc(summary.effort.tokens || 0) + ' tokens · ' + secs + 's wall-clock · '
          + _esc(summary.effort.runs || 0) + ' run(s)';
      }
    }
    if (eff) L.push('<div class="effbar">' + eff + '</div>');
  }
  if (!L.length) L.push('<div class="summ-loading">No cached summary for this session yet.</div>');

  // RIGHT: role-tagged links. Roles split into a primary group + a secondary
  // (.two) group so both columns fill equal height (locked CSS).
  var primary = [], secondary = [];
  var groups = _DOC_ROLE_GROUPS[lane] || {};
  for (var role in roles) {
    if (!roles.hasOwnProperty(role)) continue;
    var lk = roles[role];
    var html = '<a class="doc" href="' + _esc(lk.href) + '" target="_blank" '
      + 'rel="noopener">' + _esc(lk.label || role)
      + '<span class="role">' + _esc(role) + '</span></a>';
    if ((groups.two || []).indexOf(role) >= 0) secondary.push(html);
    else primary.push(html);
  }
  var R = [];
  if (primary.length) {
    R.push('<div class="slh">' + _esc(groups.primary_label || 'Documents') + '</div>');
    R = R.concat(primary);
  }
  if (secondary.length) {
    R.push('<div class="slh two">' + _esc(groups.two_label || 'More') + '</div>');
    R = R.concat(secondary);
  }
  var right = R.length ? ('<div class="slinks">' + R.join('') + '</div>') : '';
  return '<div class="smat">' + L.join('') + '</div>' + right;
}

// Per-lane role grouping for the split's two link groups (primary + .two). The
// secondary group pins to the bottom (.slh.two) so both columns share height.
var _DOC_ROLE_GROUPS = {
  research: {primary_label: 'Research outputs', two_label: 'Provenance',
            two: ['provenance']},
  planning: {primary_label: 'Plan documents', two_label: 'Objective',
            two: ['northstar']},
  plan: {primary_label: 'Plan documents', two_label: 'Objective',
        two: ['northstar']},
  build: {primary_label: 'Build outputs', two_label: 'Plan it executes',
         two: ['northstar', 'plan']}
};

// _wirePanelResize(sessionId, tpane): v6 Wave 3 — the WHOLE panel is freely
// resizable: the .pin body carries CSS `resize:both`, so the browser draws a
// corner drag handle and the user can resize the panel to any width+height
// (the inner .tpane also still has its own bottom-edge handle). We watch BOTH
// boxes with ResizeObservers: on a .pin change persist the panel rect (w+h) in
// _panelRects (skipping while maximized) and re-fit the terminal; on a .tpane
// change persist the terminal height and re-fit. Falls back to no-op if
// ResizeObserver is unavailable (the CSS resize still works visually).
function _wirePanelResize(sessionId, tpane) {
  var p = PANELS[sessionId];
  if (!p || !tpane || typeof ResizeObserver === 'undefined') return;
  var ro = new ResizeObserver(function () {
    _panelHeights[sessionId] = tpane.style.height || (tpane.offsetHeight + 'px');
    _fitPanelTerminal(sessionId);
  });
  ro.observe(tpane);
  p.ro = ro;
  // The .pin free-resize box → persist the panel rect + re-fit on every change.
  if (p.pin) {
    var pro = new ResizeObserver(function () {
      if (!p.maxd) {
        _panelRects[sessionId] = {
          w: p.pin.style.width || (p.pin.offsetWidth + 'px'),
          h: p.pin.style.height || (p.pin.offsetHeight + 'px')
        };
      }
      _fitPanelTerminal(sessionId);
    });
    pro.observe(p.pin);
    p.pinRo = pro;
  }
}

// maximizePanel(sessionId): v6 Wave 3 — toggle the panel to fill the cockpit
// viewport (.panel.maxd: a fixed full-screen overlay) and back to its prior
// freely-resized rect. On BOTH the maximize and the restore we re-fit the xterm
// terminal (twice — immediately + after the layout settles) so cols/rows track
// the new area and the terminal never freezes or clips. The session keeps
// running throughout — this only changes the panel's geometry.
function maximizePanel(sessionId) {
  var p = PANELS[sessionId];
  if (!p || !p.el) return;
  // A maximize on a minimized panel first re-expands it (so there's something
  // to fill the screen with).
  if (p.el.classList.contains('minimized')) p.el.classList.remove('minimized');
  if (!p.maxd) {
    // Remember the freely-resized rect so restore returns to it exactly, then
    // clear the inline size so .panel.maxd's fixed fill takes over.
    if (p.pin) {
      p._restoreRect = {w: p.pin.style.width, h: p.pin.style.height};
      p.pin.style.width = '';
      p.pin.style.height = '';
    }
    p.el.classList.add('maxd');
    p.maxd = true;
  } else {
    p.el.classList.remove('maxd');
    p.maxd = false;
    // Restore the pre-maximize rect (if any).
    if (p.pin && p._restoreRect) {
      if (p._restoreRect.w) p.pin.style.width = p._restoreRect.w;
      if (p._restoreRect.h) p.pin.style.height = p._restoreRect.h;
    }
  }
  // Re-fit now and again after the geometry change paints (xterm needs the new
  // host size to recompute cols/rows; the ResizeObserver also fires, but we call
  // explicitly so the fit happens even on browsers that batch RO callbacks).
  _fitPanelTerminal(sessionId);
  setTimeout(function () { _fitPanelTerminal(sessionId); }, 60);
}

// _fitPanelTerminal(sessionId): re-fit the xterm to its host then push the new
// cols/rows to the PTY via term_resize (the existing transport endpoint). Uses
// the xterm fit addon when present; otherwise relies on the onResize hook the
// mounted terminal already wires to term_resize.
function _fitPanelTerminal(sessionId) {
  var p = PANELS[sessionId];
  if (!p || !p.term) return;
  try {
    if (p.fit && p.fit.fit) {
      p.fit.fit();              // triggers term.onResize → term_resize
    } else if (p.term.resize) {
      // No fit addon: compute BOTH cols and rows from the host so the terminal
      // fills the FULL panel width (xterm defaults to 80 cols → only the left
      // ~third of a wide panel) and reflows on vertical resize. ~7.2px/char,
      // ~17px/row at 12px monospace.
      var host = p.body;
      // v10.1 FIX 4 — collapse/zero-size guard: a collapsed/hidden host (e.g.
      // `.gterm.collapsed .term-host{display:none}`) has no offsetParent / zero
      // box; bail so we don't compute a degenerate cols/rows + spam term_resize.
      if (!host || host.offsetParent === null
          || host.clientHeight === 0 || host.clientWidth === 0) return;
      var hw = (host && host.clientWidth) || 600;
      var hh = (host && host.clientHeight) || 90;
      var cols = Math.max(20, Math.floor((hw - 8) / 7.2));
      var rows = Math.max(4, Math.floor((hh - 4) / 17));
      p.term.resize(cols, rows);   // triggers onResize → term_resize
    }
  } catch (e) {}
}

// _tokenQ(): the ?token= suffix for read-only GET endpoints that gate via the
// query param (same semantics as the WS/SSE transport token).
function _tokenQ() {
  var tok = _anchorToken();
  return tok ? ('&token=' + encodeURIComponent(tok)) : '';
}

// Shared Accept-JSON headers object (one definition avoids a literal double
// close-brace in nested fetch-option object literals — the served-HTML
// brace-hygiene contract for this RAW single-brace string).
var _ACCEPT_JSON = {Accept: 'application/json'};
function _jsonHdrs() { return {headers: _ACCEPT_JSON}; }

// ── refreshBoard (v7 Wave 6) ────────────────────────────────────────────────
// Instant-in-column board refresh. After a session-lifecycle mutation (start /
// finish / advance / promote / develop) the SERVER-rendered 5-lane board is the
// single source of truth for the lane-column tiles, so we just re-fetch the
// board fragment (GET /api/rnd/board_html, ?token=) and swap #kanbanBoard's
// innerHTML in place — no full page reload. Because the tile comes from the
// server render (NOT JS-injected), dedupe stays correct: a started session
// shows EXACTLY ONE tile in its lane column. Guarded so it never throws into
// the UI (a failed refresh just leaves the prior board until the next refresh /
// reload). The top live strip (renderSessionBar) is unaffected — it stays the
// instant chip view for live managed sessions; this only refreshes the columns.
async function refreshBoard() {
  try {
    var url = '/api/rnd/board_html?project_id=' + encodeURIComponent(PROJECT_ID) + _tokenQ();
    var r = await fetch(url, Object.assign({cache: 'no-store'}, _jsonHdrs()));
    if (!r || !r.ok) return;
    var data = await r.json();
    if (!data || !data.ok || typeof data.html !== 'string') return;
    var board = document.getElementById('kanbanBoard');
    if (!board) return;                    // guard: container absent
    board.innerHTML = data.html;
    // v10 Wave 4 FIX 2/3: the swapped-in board re-emits "from grass" chip stubs;
    // resolve them (label/dead-state) against the loaded grass data. If grass
    // data isn't loaded yet, fetch it (which itself re-resolves on completion).
    try {
      if (_grassData && Object.keys(_grassData).length) {
        _resolveGrassOriginChips(board);
      } else {
        _loadGrassData();
      }
    } catch (e) {}
  } catch (e) { /* never throw into the UI */ }
}

// minimizePanel: collapse the panel back to a header-only strip. The session and
// its terminal transport keep RUNNING — this only hides the panel body.
function minimizePanel(sessionId) {
  var p = PANELS[sessionId];
  if (!p || !p.el) return;
  p.el.classList.add('minimized');
  renderSessionBar();
}

// _closePanel: tear down the panel DOM + transport WITHOUT killing the session
// (used by close-to-tile, and when the registry no longer reports a session, e.g.
// after a kill). It NEVER touches the MANAGED record or the lane tile — the
// session stays reopenable from its tile.
function _closePanel(sessionId) {
  var p = PANELS[sessionId];
  if (!p) return;
  try { if (p.ro && p.ro.disconnect) p.ro.disconnect(); } catch (e) {}
  try { if (p.pinRo && p.pinRo.disconnect) p.pinRo.disconnect(); } catch (e) {}
  try { if (p.fitRo && p.fitRo.disconnect) p.fitRo.disconnect(); } catch (e) {}  // v10.1 FIX 4
  try { if (p.transport && p.transport.close) p.transport.close(); } catch (e) {}
  try { if (p.term && p.term.dispose) p.term.dispose(); } catch (e) {}
  if (p.el && p.el.parentNode) p.el.parentNode.removeChild(p.el);
  delete PANELS[sessionId];
}

// closePanel: the panel "×" = CLOSE-to-tile. Tears down the panel DOM + transport
// ONLY (via _closePanel). It does NOT kill the PTY, NOT remove the worktree, NOT
// remove the registry record, NOT remove the lane tile — the session stays
// reopenable (click its tile → laneTileClick → openPanel re-attaches a live
// terminal for a running session, or re-shows the summary for a historical one).
// Live AND historical panels use this same non-destructive close.
function closePanel(sessionId) {
  _closePanel(sessionId);
  renderSessionBar();
}

// _removeSessionTile: drop the lane-board tile for a session from the DOM (used by
// the deliberate hard-kill only — close-to-tile NEVER removes a tile). Removes the
// most-recent visible tile AND any tile inside a "previous sessions" expander.
function _removeSessionTile(sessionId) {
  var sel = '.tile[data-session="' + _cssEsc(sessionId) + '"]';
  var tiles = document.querySelectorAll(sel);
  for (var i = 0; i < tiles.length; i++) {
    var el = tiles[i];
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }
}

// killPanel: the panel "🗑 Kill" = deliberate HARD-KILL, gated behind a confirm().
// Only on YES do we POST /api/rnd/term_kill (reap PTY + remove worktree + mark the
// registry record terminal), then tear down the panel, drop the MANAGED record AND
// remove the session's lane tile so it's gone. For a historical/non-live session
// the server returns 404 (unknown-session) — that's fine; we STILL remove the
// tile + record cleanly (no orphan). (Minimize/close, by contrast, never kill.)
async function killPanel(sessionId) {
  var s = MANAGED[sessionId];
  var name = s ? (s.label || (s.lane + ' ' + s.idx)) : sessionId;
  if (!confirm('Are you sure? Kill the "' + name + '" session? This terminates its process and removes its tile.')) return;
  var autoBuild = null;
  try {
    var r = await _postJson('/api/rnd/term_kill', {session: sessionId});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_kill', {session: sessionId});
      data = await r.json();
    }
    // A 404 unknown-session (historical tile with no live PTY) is NOT an error
    // for kill — there is simply no process to reap; we still drop the tile.
    // v6 Wave 6: killing a PLANNING session that produced a real plan set
    // auto-opens a linked BUILD session (server-side). Surface its new tile.
    if (data && data.auto_build) autoBuild = data.auto_build;
  } catch (e) { alert('[kill error] ' + e.message); }
  _KILLED[sessionId] = 1;       // v6 Wave 4: suppress this id from future repopulate
  _closePanel(sessionId);
  delete MANAGED[sessionId];
  delete FINISHED[sessionId];   // v6 Wave 4: also evict a finished tile if killed
  _removeSessionTile(sessionId);
  renderSessionBar();
  // v6 Wave 6: mint the auto-opened build tile (new MANAGED entry + bar) and
  // open its panel, with a tiny "auto-opened from this plan" note.
  if (autoBuild && autoBuild.session_id) {
    _addAutoBuildTile(autoBuild);
  }
  // v7 Wave 6: re-fetch the server-rendered board so the killed session's tile
  // is dropped (and any auto-opened build tile appears) instantly, no reload.
  refreshBoard();
  setTimeout(repopulate, 400);
}

// deletePanel: the panel red "✕" = TRUE DELETE (v9 Wave 1), DISTINCT from kill.
// Confirm-gated. On YES we POST /api/rnd/term_delete {confirm:true} — the server
// hard-deletes the registry record + the session's effort pointer-records +
// cached summary (the produced DOCUMENTS are KEPT on disk — Option A). Then we
// tear down the panel, drop the MANAGED/FINISHED record, mark the id _DELETED
// (so an in-flight repopulate can't re-add it) and remove the lane tile. Because
// the registry record is GONE, term_sessions/the board no longer surface it — so
// it STAYS gone across a reload (the v6 key bug for kills is moot for delete).
async function deletePanel(sessionId) {
  var s = MANAGED[sessionId] || FINISHED[sessionId];
  var name = s ? (s.label || (s.lane + ' ' + s.idx)) : sessionId;
  if (!confirm('Are you sure? This permanently removes the "' + name +
               '" session from Anchor (its registry record, effort records and ' +
               'cached summary). The produced documents are KEPT on disk. This ' +
               'cannot be undone.')) return;
  try {
    var r = await _postJson('/api/rnd/term_delete', {session: sessionId, confirm: true});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/term_delete', {session: sessionId, confirm: true});
      data = await r.json();
    }
  } catch (e) { alert('[delete error] ' + e.message); }
  _DELETED[sessionId] = 1;       // suppress this id from any future repopulate
  delete _KILLED[sessionId];
  _closePanel(sessionId);
  delete MANAGED[sessionId];
  delete FINISHED[sessionId];
  _removeSessionTile(sessionId);
  renderSessionBar();
  // Re-fetch the server-rendered board so the deleted session's tile is dropped
  // instantly (the registry record is gone → the board no longer renders it).
  refreshBoard();
  setTimeout(repopulate, 400);
}

// cleanupGhostSessions: v9 Wave 1 small "clear empty sessions" action — sweep the
// project's empty ghost (terminal/idle, no-effort) registry records. Confirm +
// token gated; refreshes the board on success.
async function cleanupGhostSessions() {
  if (!confirm('Clear empty sessions? This removes session records that produced ' +
               'nothing (no documents are affected).')) return;
  try {
    var r = await _postJson('/api/rnd/cleanup_ghost_sessions',
                            {project_id: PROJECT_ID, confirm: true});
    var data = await r.json();
    if (_isUnauthorized(r, data) && setAnchorToken()) {
      r = await _postJson('/api/rnd/cleanup_ghost_sessions',
                          {project_id: PROJECT_ID, confirm: true});
      data = await r.json();
    }
    if (data && data.removed) {
      for (var i = 0; i < data.removed.length; i++) {
        _DELETED[data.removed[i]] = 1;
        _closePanel(data.removed[i]);
        delete MANAGED[data.removed[i]];
        delete FINISHED[data.removed[i]];
        _removeSessionTile(data.removed[i]);
      }
    }
  } catch (e) { alert('[cleanup error] ' + e.message); }
  renderSessionBar();
  refreshBoard();
  setTimeout(repopulate, 400);
}

// _addAutoBuildTile(rec): v6 Wave 6 — register the server-started auto-advance
// build session as a LIVE managed tile (same shape advanceSession uses), render
// the bar, open its panel, and flash a tiny "→ auto-opened Build from this plan"
// note so the user sees the planning→build hand-off happen.
function _addAutoBuildTile(rec) {
  var sid = rec.session_id;
  var lane = rec.lane || 'build';
  MANAGED[sid] = {
    session_id: sid, lane: lane, backend: rec.backend || 'claude',
    status: rec.status || 'running', label: rec.label || 'auto · from plan',
    chain_id: rec.chain_id || '', parent_session_id: rec.parent_session_id || '',
    auto_from_plan: true,
    idx: (_laneCounters[lane] = (_laneCounters[lane] || 0) + 1)
  };
  renderSessionBar();
  openPanel(sid);
  _flashAutoBuildNote(rec);
  // v10 Wave 2: the build prompt is a PENDING PASTE (unsent) — hint the user.
  _flashPendingPasteHint(sid);
}

// _flashAutoBuildNote(rec): a small, transient banner above the panel stack.
function _flashAutoBuildNote(rec) {
  try {
    var host = document.getElementById('panelStack') || document.body;
    var note = document.createElement('div');
    note.className = 'autobuild-note';
    note.setAttribute('data-session', rec.session_id);
    var which = 'Build ' + (rec.session_id || '').slice(0, 6);
    note.textContent = '→ auto-opened ' + which + ' from this plan';
    if (host.firstChild) host.insertBefore(note, host.firstChild);
    else host.appendChild(note);
    setTimeout(function () {
      if (note && note.parentNode) note.parentNode.removeChild(note);
    }, 6000);
  } catch (e) { /* the tile already landed; the note is advisory */ }
}

// _flashPendingPasteHint(sessionId): v10 Wave 2 — a subtle, transient hint above
// the panel stack telling the user the next-stage prompt is PASTED but UNSENT in
// the terminal input ("review & press Enter to run"). Nothing auto-submits; the
// prompt is the v10 pending paste, flushed UNSENT by the terminal transport read.
function _flashPendingPasteHint(sessionId) {
  try {
    var host = document.getElementById('panelStack') || document.body;
    var note = document.createElement('div');
    note.className = 'pendpaste-hint';
    note.setAttribute('data-session', sessionId || '');
    note.textContent = 'prompt ready — review & press Enter to run (nothing was submitted)';
    if (host.firstChild) host.insertBefore(note, host.firstChild);
    else host.appendChild(note);
    setTimeout(function () {
      if (note && note.parentNode) note.parentNode.removeChild(note);
    }, 8000);
  } catch (e) { /* advisory only */ }
}

// Mount xterm.js in the panel body host over the Wave-3 transport (UNCHANGED).
// Prefer the hand-rolled WebSocket (term_ws); fall back to SSE-out (term_stream2)
// + POST-in (term_input2). Bytes from read_since are decoded str sent as UTF-8.
function _mountTerminal(sessionId, body) {
  var w = PANELS[sessionId];
  if (!w) return;
  if (!window.Terminal) {
    body.textContent = 'terminal component failed to load';
    return;
  }
  var _termTheme = {background: '#0c0e14'};
  var term = new window.Terminal({convertEol: true, fontSize: 12,
                                  theme: _termTheme, scrollback: 5000});
  term.open(body);
  w.term = term;
  w.body = body;
  var tok = _anchorToken();
  var tq = tok ? ('&token=' + encodeURIComponent(tok)) : '';

  // Fit to the host NOW + shortly after layout settles (xterm starts at 80 cols).
  _fitPanelTerminal(sessionId);
  setTimeout(function () { _fitPanelTerminal(sessionId); }, 60);

  // v10.1 FIX 4 — make _mountTerminal self-sufficient about reflow. The board
  // path wires a ResizeObserver in _wirePanelResize, but the grass mounts never
  // call it, so an ENLARGED grass terminal (.gterm host is CSS resize:vertical)
  // grew but xterm never reflowed (nothing observed it → _fitPanelTerminal never
  // ran). Attach our OWN observer on the INNER host (`body` = the .term-host the
  // fit measures), stored on a DISTINCT key (w.fitRo, NOT p.ro — never clobber
  // the board's _wirePanelResize observer). Disconnect any prior fitRo first
  // (grass never calls _closePanel, so a re-develop would otherwise leak
  // observers). Idempotent for the board (same cols/rows → xterm no-ops).
  if (typeof ResizeObserver !== 'undefined') {
    try { if (w.fitRo && w.fitRo.disconnect) w.fitRo.disconnect(); } catch (e) {}
    var fro = new ResizeObserver(function () { _fitPanelTerminal(sessionId); });
    fro.observe(body);
    w.fitRo = fro;
  }

  // Outbound user keystrokes → term_input2 (works for BOTH transports; the WS
  // also accepts frames, but routing input through the POST keeps one path).
  term.onData(function (d) {
    _postJson('/api/rnd/term_input2', {session: sessionId, data: d});
  });
  // Keyboard paste: xterm emits Ctrl+V as the control byte \x16, so paste never
  // happened (only right-click, which uses the browser's native paste event).
  // Intercept Ctrl/Cmd+V → read the clipboard → term.paste (honors bracketed
  // paste so multi-line prompts don't run line-by-line). Ctrl+Shift+C copies a
  // selection. Everything else passes through unchanged.
  term.attachCustomKeyEventHandler(function (e) {
    if (e.type !== 'keydown') return true;
    var mod = e.ctrlKey || e.metaKey;
    if (mod && !e.altKey && (e.key === 'v' || e.key === 'V')) {
      if (navigator.clipboard && navigator.clipboard.readText) {
        navigator.clipboard.readText().then(function (t) {
          if (t) { try { term.paste(t); } catch (err) {
            _postJson('/api/rnd/term_input2', {session: sessionId, data: t}); } }
        }).catch(function () {});
      }
      return false;  // suppress the \x16 control byte
    }
    if (mod && e.shiftKey && (e.key === 'c' || e.key === 'C')) {
      var sel = term.getSelection && term.getSelection();
      if (sel && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(sel).catch(function () {});
        return false;
      }
    }
    return true;
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
// (v3 floating-window drag/resize helpers removed in v4 Wave 4: inline panels
// stack in the document flow — Wave 5 adds the terminal-pane vertical resize.)
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


def ensure_anchor_deliverable(folder_path: str, project_id: str):
    """Pin ``anchor_gui.py`` as the project's runnable Anchor deliverable (Wave 8).

    Idempotent: ``deliverables.pin_deliverable`` is content-addressed by path, so
    pinning the same file twice produces no duplicate. ``anchor_gui.py`` is a
    long-running SERVER (not a run-to-completion program), so its run is the
    ephemeral preview (``preview_server``), not the program contract — it is
    pinned with type ``program`` only so it surfaces in the Deliverables lane.
    Best-effort: a pin failure never breaks the window render.

    Pin-if-absent: this runs on EVERY ``GET /project/<id>`` render, and
    ``pin_deliverable`` → ``record_effort`` unconditionally rewrites the pointer
    JSON under ``WRITE_LOCK``. To avoid needless disk-write/lock churn on this
    hot path, skip the pin entirely when ``anchor_gui.py`` is already pinned for
    this project; the first render still pins. The pinned content/id is
    unchanged (content-addressed by path).
    """
    try:
        target = _preview.DEFAULT_TARGET
        for rec in _deliv.list_pinned_deliverables(folder_path, project_id):
            if (rec.get("artifact_path") or "") == target:
                return rec  # already pinned — no write, no lock contention
        return _deliv.pin_deliverable(
            folder_path, project_id, target,
            name=target, dtype=_deliv.TYPE_PROGRAM,
            description="Anchor dashboard web app (run as an ephemeral preview)")
    except Exception:
        return None


def render_deliverables_html(project_id: str, folder_path: str) -> str:
    """Render the project's deliverables: pinned deliverables (with Run/Stop) +
    deliverable run-status records (Wave 9 AC1 + v3 Wave 8 ephemeral preview).

    The pinned ``anchor_gui.py`` deliverable gets a **Run** action that starts an
    ephemeral preview on a free port (≠8777) and opens it in a new tab, plus a
    **Stop** that reaps it — token-aware via the project-window JS.
    """
    pinned = []
    try:
        pinned = _deliv.list_pinned_deliverables(folder_path, project_id)
    except Exception:
        pinned = []
    try:
        records = _deliv.list_status(folder_path, project_id)
    except Exception:
        records = []

    out = ["<h2>Deliverables</h2>"]

    # Pinned deliverables with Run/Stop (the runnable Anchor deliverable).
    if pinned:
        # v4 Wave 7: the launch action ADAPTS to the deliverable type — the
        # per-type affordance label mirrors the "📦 Deliverable" mockup card.
        _launch_label = {
            _deliv.TYPE_SERVICE: "▶ launch in window / pull up",
            _deliv.TYPE_PROGRAM: "▶ run in a window",
            _deliv.TYPE_SCRIPT: "▶ run in a window",
            _deliv.TYPE_SKILL: "✓ verify status",
            _deliv.TYPE_TOOL: "✓ verify status",
            _deliv.TYPE_DOC: "📖 open rendered",
        }
        items = []
        for r in pinned:
            name = html_lib.escape(
                r.get("title") or r.get("artifact_path") or "")
            rel = r.get("artifact_path", "") or ""
            raw_type = (r.get("deliverable_type", "") or "").strip().lower()
            if raw_type not in _deliv.VALID_TYPES:
                raw_type = _deliv.infer_type(rel)
            dtype = html_lib.escape(raw_type)
            did = r.get("job_id", "") or ""
            rel_attr = html_lib.escape(rel, quote=True)
            did_attr = html_lib.escape(did, quote=True)
            label = html_lib.escape(_launch_label.get(raw_type, "▶ launch"))
            items.append(
                f"<li class='deliv-pinned' data-deliv=\"{rel_attr}\" "
                f"data-deliv-id=\"{did_attr}\" data-deliv-type=\"{dtype}\">"
                f"<span class='deliv-name'>{name}</span> "
                f"<span style='color:#8a90a2;font-size:12px'>[{dtype}]</span> "
                f"<button class='deliv-run' "
                f"onclick=\"launchDeliverable(this)\">{label}</button> "
                f"<button class='deliv-stop' "
                f"onclick=\"stopDeliverable(this)\" style='display:none'>"
                f"Stop</button> "
                f"<span class='deliv-msg' style='color:#8a90a2;"
                f"font-size:12px'></span></li>"
            )
        out.append("<h3 style='margin:8px 0 4px;font-size:14px;color:#aeb4c2'>"
                   "Pinned</h3>")
        out.append("<ul style='list-style:none;padding:0'>"
                   + "".join(items) + "</ul>")

    # Run-status records (read-only history).
    if records:
        colors = {_deliv.STATUS_SUCCESS: "#4caf78",
                  _deliv.STATUS_FAILED: "#e06c75",
                  _deliv.STATUS_TIMED_OUT: "#d6a35c"}
        rows = []
        for r in records:
            status = r.get("status", "")
            color = colors.get(status, "#8a90a2")
            name = html_lib.escape(
                r.get("name", "") or r.get("deliverable_id", ""))
            dtype = html_lib.escape(r.get("type", ""))
            rows.append(
                f"<li>{name} <span style='color:#8a90a2;font-size:12px'>"
                f"[{dtype}]</span> — <span style='color:{color}'>"
                f"{html_lib.escape(status)}</span></li>"
            )
        out.append("<h3 style='margin:8px 0 4px;font-size:14px;color:#aeb4c2'>"
                   "Run history</h3>")
        out.append("<ul style='list-style:none;padding:0'>"
                   + "".join(rows) + "</ul>")

    if not pinned and not records:
        out.append("<p style='color:#8a90a2'>No deliverables yet.</p>")
    return "".join(out)


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
<link rel="icon" href="/vendor/brand/gwl-m-icon.svg?v={BUILD_ID}" type="image/svg+xml">
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

/* Ghost World Labs brand lockup (Wave 9) — elegant, unobtrusive, theme-fit */
.gwl-lockup {{
    display: flex; align-items: center; gap: 9px;
    padding: 14px 20px 4px;
}}
.gwl-lockup img {{
    width: 26px; height: 26px; border-radius: 6px; flex-shrink: 0;
    box-shadow: 0 0 8px rgba(34, 197, 94, 0.35);
}}
.gwl-lockup .gwl-wordmark {{
    font-size: 12px; font-weight: 700; letter-spacing: 0.3px;
    color: #f8fafc; line-height: 1.1;
}}
.gwl-lockup .gwl-wordmark .gwl-accent {{ color: #22c55e; }}
.gwl-badge {{
    display: inline-flex; align-items: center; gap: 5px;
    margin: 4px 20px 14px; padding: 3px 9px;
    font-size: 10px; font-weight: 600; letter-spacing: 0.2px;
    color: #f8fafc; background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(34, 197, 94, 0.35); border-radius: 999px;
}}
.gwl-badge .gwl-rad {{ color: #22c55e; }}
.gwl-footer {{
    margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px;
    font-size: 11px; color: var(--text-dim);
}}
.gwl-footer img {{ width: 16px; height: 16px; border-radius: 4px; }}
.gwl-footer .gwl-accent {{ color: #22c55e; }}

/* v4 Wave 8 — Option B masthead lockup (branding_proposals.html Proposal B):
   Anchor title · vertical divider · GWL mark + wordmark off to the side ·
   "Powered by NextGen Nuclear ☢" pill pushed to the far right. Reuses the SINGLE
   vendored brand mark (/vendor/brand/gwl-m-icon.svg); no second asset. */
.masthead {{
    display: flex; align-items: center; gap: 18px;
    padding: 14px 0 18px; margin-bottom: 8px;
    border-bottom: 1px solid var(--border);
}}
.masthead .mh-title {{
    font-size: 28px; font-weight: 700; letter-spacing: -0.5px;
    display: flex; align-items: center; gap: 9px;
}}
.masthead .mh-title .mh-anchor {{ color: var(--accent); }}
.masthead .mh-vdiv {{ width: 1px; height: 38px; background: var(--border); flex-shrink: 0; }}
.masthead .mh-lock {{ display: flex; align-items: center; gap: 10px; }}
.masthead .mh-lock img {{
    width: 30px; height: 30px; border-radius: 7px; flex-shrink: 0;
    box-shadow: 0 0 9px rgba(34, 197, 94, 0.4);
}}
.masthead .mh-words {{ line-height: 1.2; }}
.masthead .mh-words .mh-w1 {{ font-size: 13px; font-weight: 700; color: #f8fafc; }}
.masthead .mh-words .mh-w1 .gwl-accent {{ color: #22c55e; }}
.masthead .mh-words .mh-w2 {{ font-size: 10.5px; color: var(--text-dim); margin-top: 2px; }}
.masthead .mh-spacer {{ flex: 1; }}
.masthead .mh-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 11px; border-radius: 999px;
    font-size: 10.5px; font-weight: 600; color: #f8fafc;
    background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(34, 197, 94, 0.4);
}}
.masthead .mh-pill .gwl-rad {{ color: #22c55e; }}
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
/* v4 Wave 8: the per-folder directory header (.rnd-folder/.rnd-folder-head/
   .rnd-folder-tiles) was removed — projects render as a FLAT row list. */
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
/* v9 Wave 3 — collapsible project FOLDERS (group field; drag-to-group). */
.rnd-folder-toolbar {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
.rnd-newfolder-btn {{ font-size: 12px; padding: 6px 12px; border-radius: 7px; border: 1px solid rgba(108,156,252,.5); background: var(--surface2, #232733); color: var(--accent); cursor: pointer; }}
.rnd-newfolder-btn:hover {{ border-color: var(--accent); }}
.rnd-folder-hint {{ font-size: 11.5px; color: var(--text-dim); }}
.rnd-folder-list {{ display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
.rnd-folder {{ border-bottom: 1px solid var(--border); }}
.rnd-folder:last-child {{ border-bottom: none; }}
.rnd-folder-head {{ display: flex; align-items: center; gap: 8px; padding: 11px 14px; cursor: pointer; background: var(--surface2, #232733); }}
.rnd-folder-head:hover {{ background: var(--surface3, #2a2f3d); }}
.rnd-tw {{ font-size: 11px; color: var(--text-dim); width: 12px; flex: 0 0 auto; }}
.rnd-fname {{ font-size: 13.5px; font-weight: 600; }}
.rnd-fcount {{ font-size: 11px; color: var(--text-dim); }}
.rnd-fpath {{ font-size: 10.5px; color: var(--text-dim); font-family: ui-monospace, Consolas, monospace; margin-left: 6px; }}
.rnd-fsp {{ flex: 1; }}
.rnd-fdrop-hint {{ font-size: 11px; color: var(--accent); }}
.rnd-folder-body {{ display: flex; flex-direction: column; gap: 6px; padding: 6px 8px 8px; }}
.rnd-folder.rnd-collapsed .rnd-folder-body {{ display: none; }}
.rnd-folder.rnd-droptarget .rnd-folder-head {{ outline: 2px dashed var(--accent); outline-offset: -2px; }}
.rnd-grip {{ flex: 0 0 auto; color: var(--text-dim); font-size: 13px; cursor: grab; letter-spacing: -2px; }}
.rnd-row[draggable="true"] {{ cursor: grab; }}
.rnd-row.rnd-dragging {{ opacity: .5; }}
/* v9 Wave 4 — the Option-C "move on disk + group" confirm dialog. */
.rnd-move-overlay {{ position: fixed; inset: 0; z-index: 9000; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; }}
.rnd-move-dlg {{ max-width: 560px; width: calc(100% - 40px); border: 1px solid rgba(239,68,68,.4); border-radius: 12px; background: #160f12; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,.6); }}
.rnd-move-h {{ padding: 10px 14px; background: rgba(239,68,68,.1); font-size: 14px; font-weight: 600; border-bottom: 1px solid rgba(239,68,68,.3); color: var(--text); }}
.rnd-move-b {{ padding: 13px 14px; font-size: 13px; color: var(--text); }}
.rnd-move-mono {{ font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; color: #cdd2dc; background: #05070c; border: 1px solid var(--border); border-radius: 7px; padding: 8px 10px; margin: 9px 0; word-break: break-all; }}
.rnd-move-mono .rnd-move-arr {{ color: var(--accent); }}
.rnd-move-guard {{ font-size: 12px; color: var(--text-dim); margin-top: 8px; }}
.rnd-move-guard b {{ color: #e9dca8; }}
.rnd-move-acts {{ display: flex; flex-wrap: wrap; gap: 9px; padding: 11px 14px; border-top: 1px solid var(--border); }}
.rnd-move-btn {{ font-size: 12.5px; padding: 7px 12px; border-radius: 7px; border: 1px solid var(--border); background: var(--surface2, #232733); color: var(--text); cursor: pointer; }}
.rnd-move-btn:hover {{ border-color: var(--accent); }}
.rnd-move-btn.rnd-move-go {{ border-color: rgba(239,68,68,.55); background: rgba(239,68,68,.14); color: #ffd2d2; }}
/* v3 Wave 5 — thin full-width project ROWS (replace the square .rnd-tile). */
.rnd-folder-rows {{ display: flex; flex-direction: column; gap: 6px; }}
.rnd-row {{ display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface2, #232733); cursor: pointer; position: relative; }}
.rnd-row:hover {{ border-color: var(--accent); }}
.rnd-row:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
.rnd-dot {{ flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%; background: var(--text-dim); }}
.rnd-dot.rnd-dot-running {{ background: var(--success); box-shadow: 0 0 5px var(--success); }}
.rnd-dot.rnd-dot-idle {{ background: var(--text-dim); }}
.rnd-row .rnd-name {{ flex: 0 0 auto; white-space: nowrap; }}
.rnd-row-summary {{ flex: 2 1 0; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--text); opacity: .85; }}
.rnd-row-summary.rnd-dim {{ color: var(--text-dim); opacity: .6; font-style: italic; }}
/* v6 Wave 7 — timely activity reflection: running indicator + "what's happening". */
.rnd-row-activity {{ flex: 3 1 0; min-width: 0; display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-dim); overflow: hidden; }}
.rnd-act-running {{ flex: 0 0 auto; display: inline-flex; align-items: center; gap: 4px; color: var(--success); font-weight: 600; }}
.rnd-act-pulse {{ width: 7px; height: 7px; border-radius: 50%; background: var(--success); box-shadow: 0 0 5px var(--success); animation: rndActPulse 1.4s ease-in-out infinite; }}
@keyframes rndActPulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .35; }} }}
.rnd-act-latest {{ flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.rnd-act-lane {{ text-transform: capitalize; color: var(--text); opacity: .85; }}
.rnd-act-title {{ color: var(--text); opacity: .9; }}
.rnd-act-status.rnd-act-green {{ color: var(--success); }}
.rnd-act-status.rnd-act-amber {{ color: #e0a02a; }}
.rnd-act-status.rnd-act-red {{ color: var(--danger, #e06c6c); }}
.rnd-act-status.rnd-act-grey {{ color: var(--text-dim); }}
.rnd-row-counts {{ flex: 0 0 auto; }}
.rnd-row-counts .rnd-status-line {{ gap: 5px; }}
.rnd-row-counts .rnd-lane {{ padding: 2px 7px; font-size: 11px; }}
/* v4 Wave 8 — per-row cost/tokens/time rollup + the R&D view's global window toggle. */
.rnd-row-roll {{ flex: 0 0 auto; font-size: 11px; color: var(--text-dim); white-space: nowrap; font-variant-numeric: tabular-nums; }}
.rnd-rows-rolltog {{ display: inline-flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; color: var(--text-dim); }}
.rnd-rows-rolltog-label {{ margin-right: 2px; }}
.rnd-rows-rolltog b {{ font-size: 10px; padding: 2px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text-dim); font-weight: 600; cursor: pointer; }}
.rnd-rows-rolltog b.on {{ background: rgba(108,156,252,.15); color: var(--accent); border-color: var(--accent); }}
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
    <div class="gwl-lockup">
      <img src="/vendor/brand/gwl-m-icon.svg?v={BUILD_ID}" alt="Ghost World Labs">
      <div class="gwl-wordmark">Ghost World <span class="gwl-accent">Labs</span></div>
    </div>
    <div class="gwl-badge">Powered by NextGen Nuclear <svg class="gwl-rad" width="12" height="12" viewBox="0 0 24 24" style="vertical-align:middle" role="img" aria-label="radiation"><circle cx="12" cy="12" r="2.6" fill="#22c55e"/><path fill="#22c55e" d="M13.6 14.77L17.5 21.53A11 11 0 0 1 6.5 21.53L10.4 14.77A3.2 3.2 0 0 0 13.6 14.77ZM8.8 12L1 12A11 11 0 0 1 6.5 2.47L10.4 9.23A3.2 3.2 0 0 0 8.8 12ZM13.6 9.23L17.5 2.47A11 11 0 0 1 23 12L15.2 12A3.2 3.2 0 0 0 13.6 9.23Z"/></svg></div>
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
    <!-- v4 Wave 8 — Option B masthead lockup (Anchor · divider · GWL mark +
         wordmark · NextGen Nuclear pill). Single vendored brand mark. -->
    <div class="masthead">
      <div class="mh-title"><span class="mh-anchor">&#9875;</span>Anchor</div>
      <div class="mh-vdiv"></div>
      <div class="mh-lock">
        <img src="/vendor/brand/gwl-m-icon.svg?v={BUILD_ID}" alt="Ghost World Labs">
        <div class="mh-words">
          <div class="mh-w1">Ghost World <span class="gwl-accent">Labs</span></div>
          <div class="mh-w2">R&amp;D Mission Control</div>
        </div>
      </div>
      <div class="mh-spacer"></div>
      <div class="mh-pill">Powered by NextGen Nuclear <svg class="gwl-rad" width="12" height="12" viewBox="0 0 24 24" style="vertical-align:middle" role="img" aria-label="radiation"><circle cx="12" cy="12" r="2.6" fill="#22c55e"/><path fill="#22c55e" d="M13.6 14.77L17.5 21.53A11 11 0 0 1 6.5 21.53L10.4 14.77A3.2 3.2 0 0 0 13.6 14.77ZM8.8 12L1 12A11 11 0 0 1 6.5 2.47L10.4 9.23A3.2 3.2 0 0 0 8.8 12ZM13.6 9.23L17.5 2.47A11 11 0 0 1 23 12L15.2 12A3.2 3.2 0 0 0 13.6 9.23Z"/></svg></div>
    </div>
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
      <div id="rndProjectsRows">{rnd_projects_html}</div>
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

    <!-- Ghost World Labs footer credit (Wave 9) -->
    <div class="gwl-footer">
      <img src="/vendor/brand/gwl-m-icon.svg?v={BUILD_ID}" alt="Ghost World Labs">
      <span>A <b class="gwl-accent">Ghost World Labs</b> tool &bull; Powered by NextGen Nuclear <svg class="gwl-rad" width="11" height="11" viewBox="0 0 24 24" style="vertical-align:middle" role="img" aria-label="radiation"><circle cx="12" cy="12" r="2.6" fill="#22c55e"/><path fill="#22c55e" d="M13.6 14.77L17.5 21.53A11 11 0 0 1 6.5 21.53L10.4 14.77A3.2 3.2 0 0 0 13.6 14.77ZM8.8 12L1 12A11 11 0 0 1 6.5 2.47L10.4 9.23A3.2 3.2 0 0 0 8.8 12ZM13.6 9.23L17.5 2.47A11 11 0 0 1 23 12L15.2 12A3.2 3.2 0 0 0 13.6 9.23Z"/></svg></span>
    </div>
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

<!-- v9 Wave 4 — the Option-C "move on disk + group" confirm dialog. Hidden by
     default; shown when a project row is dropped into a folder header. -->
<div class="rnd-move-overlay" id="rndMoveOverlay" style="display:none"
     onclick="if(event.target===this)rndMoveCancel()">
  <div class="rnd-move-dlg" role="dialog" aria-modal="true"
       aria-labelledby="rndMoveTitle">
    <div class="rnd-move-h" id="rndMoveTitle">Move project into folder?</div>
    <div class="rnd-move-b">
      <span id="rndMoveLede">You dragged a project into a folder. Also move its
      directory on disk to match?</span>
      <div class="rnd-move-mono" id="rndMovePaths"></div>
      <div class="rnd-move-guard">Safety: the move is <b>refused for the Anchor
      app itself</b> and for any project with a <b>live session</b> (stop them
      first). The move is atomic — folder moved, registry + git worktrees +
      discovery re-pointed — and rolls back if anything fails.</div>
    </div>
    <div class="rnd-move-acts">
      <button class="rnd-move-btn rnd-move-go" type="button"
              id="rndMoveGo">Move on disk + group</button>
      <button class="rnd-move-btn" type="button" id="rndMoveJust">Just group
      (leave files where they are)</button>
      <button class="rnd-move-btn" type="button"
              onclick="rndMoveCancel()">Cancel</button>
    </div>
  </div>
</div>

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
    // v5 Wave 3: when the R&D view opens, pull the latest rows so a change made
    // in a project window (or another tab) shows up without a manual reload.
    if (view === 'rnd') rndRowsRefresh();
}}

// ── v5 Wave 3: live-ish R&D rows refresh (no full page reload) ──
// Poll the read-only rows fragment ONLY while the R&D view is active AND the
// tab is visible; swap the container's innerHTML only when the fragment CHANGED
// (diff-before-swap → no DOM churn / scroll jumps). Failure-tolerant: a failed
// fetch is a silent no-op, never throws.
function _rndViewActive() {{
    const v = document.getElementById('view-rnd');
    return !!(v && v.style.display !== 'none'
              && document.visibilityState === 'visible');
}}
function rndRowsRefresh() {{
    try {{
        if (!_rndViewActive()) return;
        // Don't clobber an OPEN kebab menu (the swap would re-render it closed) —
        // skip this tick; the user is mid-interaction. The next tick refreshes.
        if (document.querySelector('.rnd-kebab-menu.rnd-kebab-open')) return;
        const box = document.getElementById('rndProjectsRows');
        if (!box) return;
        fetch('/api/rnd/projects_html', {{cache: 'no-store'}})
          .then(function (r) {{ return r.ok ? r.json() : null; }})
          .then(function (d) {{
              if (!d || !d.ok || typeof d.html !== 'string') return;
              if (!_rndViewActive()) return;              // re-check after await
              if (document.querySelector('.rnd-kebab-menu.rnd-kebab-open')) return;
              if (d.html === box.innerHTML) return;       // diff-before-swap
              // Preserve the user's lifetime/30d rollup-window toggle across the
              // swap: the server fragment always renders 'lifetime' as active, so
              // capture the active window BEFORE the swap and re-apply it after
              // (otherwise the 15s poll would silently revert a 30d selection).
              var onBtn = box.querySelector('.rnd-rows-rolltog b.on[data-window]');
              var savedWin = onBtn ? onBtn.getAttribute('data-window') : 'lifetime';
              box.innerHTML = d.html;
              if (savedWin && savedWin !== 'lifetime') {{
                  var reBtn = box.querySelector(
                      '.rnd-rows-rolltog b[data-window="' + savedWin + '"]');
                  if (reBtn) rndRowsRollupWindow(savedWin, reBtn);
              }}
              // v9 Wave 3 — re-wire folder drag/drop + restore collapse state on
              // the freshly-swapped rows.
              if (typeof rndFolderInit === 'function') rndFolderInit();
          }})
          .catch(function () {{}});                       // silent no-op
    }} catch (e) {{}}
}}
setInterval(rndRowsRefresh, 15000);
document.addEventListener('visibilitychange', function () {{
    if (document.visibilityState === 'visible') rndRowsRefresh();
}});

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
// time, but one window each). The URL is version-stamped with the build id so a
// project window left open across a DEPLOY no longer matches the new URL and the
// browser re-navigates (reloads) it — otherwise a same-name/same-URL window is
// merely focused (no re-fetch) and would show stale pre-deploy HTML.
function openProjectWindow(pid) {{
    var w = window.open('/project/' + encodeURIComponent(pid) + '?v={BUILD_ID}', 'anchorproj_' + pid);
    if (w) {{ try {{ w.focus(); }} catch (e) {{}} }}
}}
function rndSetPriority(pid, pr) {{ apiCall('/api/rnd/set_priority', {{id: pid, priority: pr}}); }}
function rndArchive(pid) {{ if (confirm('Archive this project? It moves to the Archive view (kept, reviewable).')) apiCall('/api/rnd/archive_project', {{id: pid}}); }}
function rndRetire(pid) {{ if (confirm('Retire/cancel this project? It moves to the Archive view as retired.')) apiCall('/api/rnd/retire_project', {{id: pid}}); }}
function rndReactivate(pid) {{ apiCall('/api/rnd/reactivate_project', {{id: pid}}); }}
function rndRescan(pid) {{ apiCall('/api/rnd/rescan', {{id: pid}}); }}
// v4 Wave 8 — one GLOBAL lifetime/30-day toggle for the dashboard rows' cost
// rollups. Re-fetches each row's read-only /api/rnd/project_rollup?window=... and
// swaps the .rnd-row-roll text in place (no page reload). The header renders
// lifetime server-side, so a no-JS view still shows lifetime totals.
function rndRowsRollupWindow(window_, btn) {{
    if (btn && btn.parentNode) {{
        var bs = btn.parentNode.querySelectorAll('b');
        for (var i = 0; i < bs.length; i++) bs[i].classList.remove('on');
        btn.classList.add('on');
    }}
    var tok = _anchorToken();
    var tq = tok ? ('&token=' + encodeURIComponent(tok)) : '';
    var rolls = document.querySelectorAll('.rnd-row-roll[data-pid]');
    for (var j = 0; j < rolls.length; j++) {{
        (function (el) {{
            var pid = el.getAttribute('data-pid') || '';
            if (!pid) return;
            var url = '/api/rnd/project_rollup?pid=' + encodeURIComponent(pid)
                + '&window=' + encodeURIComponent(window_) + tq;
            var hdrs = {{'Content-Type': 'application/json'}};
            fetch(url, {{headers: hdrs}})
                .then(function (r) {{ return r.json(); }})
                .then(function (d) {{
                    if (d && d.ok && typeof d.text === 'string') {{
                        el.textContent = d.text;
                        el.setAttribute('data-window', window_);
                    }}
                }})
                .catch(function () {{}});
        }})(rolls[j]);
    }}
}}
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

// ── v9 Wave 3 — project FOLDERS (group field; collapsible; drag-to-group) ──
// Organization only — NOTHING moves on disk this wave (that's Wave 4). Dragging
// a row into a folder header just sets the project's `group` via set_group.
var RND_FOLDER_LS = 'anchor_rnd_folder_collapsed';
function _rndCollapsedSet() {{
    try {{ return JSON.parse(localStorage.getItem(RND_FOLDER_LS) || '[]') || []; }}
    catch (e) {{ return []; }}
}}
function _rndSaveCollapsed(arr) {{
    try {{ localStorage.setItem(RND_FOLDER_LS, JSON.stringify(arr || [])); }} catch (e) {{}}
}}
// Collapse / expand one folder, persisting the state by group name.
function rndToggleFolder(headEl) {{
    var folder = headEl && headEl.closest ? headEl.closest('.rnd-folder') : null;
    if (!folder) return;
    var collapsed = folder.classList.toggle('rnd-collapsed');
    var tw = folder.querySelector('.rnd-tw');
    if (tw) tw.textContent = collapsed ? '\\u25B8' : '\\u25BE';  // ▸ / ▾
    var g = folder.getAttribute('data-group') || '';
    var set = _rndCollapsedSet();
    var i = set.indexOf(g);
    if (collapsed && i < 0) set.push(g);
    else if (!collapsed && i >= 0) set.splice(i, 1);
    _rndSaveCollapsed(set);
}}
// "+ New folder" — name a group and assign the FIRST ungrouped project to it,
// OR (if there is none) create an empty folder by re-rendering a placeholder.
// Simplest persistence model: a folder "exists" once >=1 project carries that
// group. We create it by re-grouping the first ungrouped project; if none are
// ungrouped, we still surface an empty folder via localStorage so the user can
// drag into it (it persists once a project lands there).
var RND_PENDING_FOLDERS = 'anchor_rnd_pending_folders';
function _rndPendingFolders() {{
    try {{ return JSON.parse(localStorage.getItem(RND_PENDING_FOLDERS) || '[]') || []; }}
    catch (e) {{ return []; }}
}}
function _rndSavePending(arr) {{
    try {{ localStorage.setItem(RND_PENDING_FOLDERS, JSON.stringify(arr || [])); }} catch (e) {{}}
}}
function rndNewFolder() {{
    var name = window.prompt('New folder name:', '');
    if (name === null) return;
    name = (name || '').trim();
    if (!name) return;
    // Render an empty folder immediately so the user can drag into it. It only
    // truly persists once a project is dropped in (set_group), but we keep the
    // pending name in localStorage so a reload still shows the empty folder.
    var pend = _rndPendingFolders();
    if (pend.indexOf(name) < 0) {{ pend.push(name); _rndSavePending(pend); }}
    // The home page renders the folder list in two places — create in each.
    var lists = document.querySelectorAll('.rnd-folder-list');
    for (var i = 0; i < lists.length; i++) _rndEnsureFolderIn(lists[i], name);
}}
// Ensure a folder header with the given group name exists in ONE list (create
// an empty one before that list's Ungrouped folder if absent). Returns the el.
function _rndEnsureFolderIn(list, name) {{
    if (!list) return null;
    var sel = (window.CSS && CSS.escape) ? CSS.escape(name) : name;
    var existing = list.querySelector('.rnd-folder[data-group="' + sel + '"]');
    if (existing) return existing;
    var folder = document.createElement('div');
    folder.className = 'rnd-folder';
    folder.setAttribute('data-group', name);
    folder.setAttribute('data-ungrouped', '0');
    folder.innerHTML =
        '<div class="rnd-folder-head" role="button" tabindex="0" '
        + 'title="Collapse / expand folder">'
        + '<span class="rnd-tw" aria-hidden="true">\\u25BE</span>'
        + '<span class="rnd-fname"></span>'
        + '<span class="rnd-fcount">(0)</span>'
        + '<span class="rnd-fsp"></span>'
        + '</div><div class="rnd-folder-body"></div>';
    folder.querySelector('.rnd-fname').textContent = name;
    var head = folder.querySelector('.rnd-folder-head');
    head.addEventListener('click', function () {{ rndToggleFolder(head); }});
    // Insert before this list's Ungrouped folder so Ungrouped stays last.
    var ung = list.querySelector('.rnd-folder[data-ungrouped="1"]');
    if (ung) list.insertBefore(folder, ung); else list.appendChild(folder);
    _rndWireFolderDrop(folder);
    return folder;
}}
// Wire one folder header as a drop target. Dropping a dragged project row here
// calls set_group with this folder's group ("" for the Ungrouped folder).
function _rndWireFolderDrop(folder) {{
    var head = folder.querySelector('.rnd-folder-head');
    if (!head) return;
    head.addEventListener('dragover', function (ev) {{
        ev.preventDefault();
        if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';
        folder.classList.add('rnd-droptarget');
    }});
    head.addEventListener('dragleave', function () {{
        folder.classList.remove('rnd-droptarget');
    }});
    head.addEventListener('drop', function (ev) {{
        ev.preventDefault();
        folder.classList.remove('rnd-droptarget');
        var pid = ev.dataTransfer ? ev.dataTransfer.getData('text/plain') : '';
        if (!pid) return;
        var isUng = folder.getAttribute('data-ungrouped') === '1';
        var grp = isUng ? '' : (folder.getAttribute('data-group') || '');
        // v9 Wave 4 — the Option-C choice. Dropping into the Ungrouped folder
        // (remove from a folder) is dashboard-only — just set_group, no dialog.
        // Dropping into a NAMED folder asks: "Move on disk + group" (the guarded
        // move_project) vs "Just group" (set_group only) vs Cancel.
        if (isUng) {{
            apiCall('/api/rnd/set_group', {{project_id: pid, group: grp}});
        }} else {{
            rndMoveDialog(pid, grp, folder);
        }}
    }});
}}
// ── v9 Wave 4 — the Option-C "move on disk + group" dialog ─────────────────
// On a drop into a NAMED folder, offer: (1) "Move on disk + group" → the guarded
// POST /api/rnd/move_project {{confirm:true}} (refuses the Anchor app + any
// live-session project; atomic + rolls back); (2) "Just group" → the Wave-3
// set_group (dashboard-only, NO disk move); (3) Cancel.
function rndMoveDialog(pid, group, folder) {{
    var ov = document.getElementById('rndMoveOverlay');
    if (!ov) {{  // dialog markup absent → fall back to the plain group path.
        apiCall('/api/rnd/set_group', {{project_id: pid, group: group}});
        return;
    }}
    var pname = '';
    var row = document.querySelector('.rnd-row[data-project-id="'
        + (window.CSS && CSS.escape ? CSS.escape(pid) : pid) + '"]');
    if (row) {{
        var n = row.querySelector('.rnd-name');
        if (n) pname = n.textContent || '';
    }}
    var title = document.getElementById('rndMoveTitle');
    if (title) title.textContent =
        'Move "' + (pname || 'project') + '" into folder "' + group + '"?';
    // The exact source→dest paths are resolved server-side (the row deliberately
    // carries no on-disk path); show the destination group so the user knows
    // what "move on disk" does.
    var mono = document.getElementById('rndMovePaths');
    if (mono) mono.textContent = 'Destination group: ' + group
        + '  →  <projects-root>/' + group + '/<project-dir>';
    var go = document.getElementById('rndMoveGo');
    var just = document.getElementById('rndMoveJust');
    if (go) go.onclick = function () {{ rndMoveConfirm(pid, group, true); }};
    if (just) just.onclick = function () {{ rndMoveConfirm(pid, group, false); }};
    ov.style.display = 'flex';
}}
function rndMoveCancel() {{
    var ov = document.getElementById('rndMoveOverlay');
    if (ov) ov.style.display = 'none';
}}
// onDisk=true → the guarded move_project; false → set_group (Wave-3 path). On a
// refusal (Anchor repo / live session) we surface a clear toast (no reload).
function rndMoveConfirm(pid, group, onDisk) {{
    rndMoveCancel();
    if (!onDisk) {{
        apiCall('/api/rnd/set_group', {{project_id: pid, group: group}});
        return;
    }}
    var headers = {{'Content-Type': 'application/json'}};
    var tok = (typeof _anchorToken === 'function') ? _anchorToken() : '';
    if (tok) headers['X-Anchor-Token'] = tok;
    fetch('/api/rnd/move_project', {{
        method: 'POST', headers: headers,
        body: JSON.stringify({{project_id: pid, group: group, confirm: true}})
    }}).then(function (r) {{ return r.json(); }}).then(function (data) {{
        if (data && data.ok) {{
            showToast('Moved on disk + grouped under "' + group + '"');
            setTimeout(function () {{ window.location.reload(); }}, 700);
        }} else {{
            var reason = (data && data.reason) || (data && data.error) || 'unknown';
            var msg;
            if (reason === 'refused-anchor-repo')
                msg = "Can't move the running Anchor app (it'd kill the server). Grouped only.";
            else if (reason === 'refused-live-sessions')
                msg = 'Refused: this project has a live session — stop it first. Grouped only.';
            else
                msg = 'Move refused (' + reason + '). Grouped only.';
            showToast(msg);
            // The dashboard grouping still applies even when the disk move is
            // refused, so the row at least lands under the folder.
            apiCall('/api/rnd/set_group', {{project_id: pid, group: group}});
        }}
    }}).catch(function (e) {{
        showToast('Move error: ' + e.message);
    }});
}}
// Make project rows draggable and wire every folder as a drop target. Also
// restore the persisted collapse state. The home page renders the folder list
// in TWO places (the dashboard section + the #rndProjectsRows view), so we wire
// EVERY .rnd-folder-list. Runs on DOMContentLoaded + after an in-place refresh.
function rndFolderInit() {{
    var lists = document.querySelectorAll('.rnd-folder-list');
    for (var L = 0; L < lists.length; L++) {{
        var list = lists[L];
        if (list.getAttribute('data-rnd-wired') === '1') continue;
        list.setAttribute('data-rnd-wired', '1');
        // Draggable rows.
        var rows = list.querySelectorAll('.rnd-row[draggable="true"]');
        for (var i = 0; i < rows.length; i++) {{
            (function (row) {{
                row.addEventListener('dragstart', function (ev) {{
                    var pid = row.getAttribute('data-project-id') || '';
                    if (ev.dataTransfer) {{
                        ev.dataTransfer.setData('text/plain', pid);
                        ev.dataTransfer.effectAllowed = 'move';
                    }}
                    row.classList.add('rnd-dragging');
                }});
                row.addEventListener('dragend', function () {{
                    row.classList.remove('rnd-dragging');
                }});
            }})(rows[i]);
        }}
        // Drop targets + restore collapse state.
        var folders = list.querySelectorAll('.rnd-folder');
        var collapsed = _rndCollapsedSet();
        for (var j = 0; j < folders.length; j++) {{
            _rndWireFolderDrop(folders[j]);
            var g = folders[j].getAttribute('data-group') || '';
            if (collapsed.indexOf(g) >= 0) {{
                folders[j].classList.add('rnd-collapsed');
                var tw = folders[j].querySelector('.rnd-tw');
                if (tw) tw.textContent = '\\u25B8';  // ▸
            }}
        }}
        // Re-surface any pending (empty, not-yet-populated) folders from a prior
        // "+ New folder" that has no project yet.
        var pend = _rndPendingFolders();
        for (var k = 0; k < pend.length; k++) {{
            if (!list.querySelector('.rnd-folder[data-group="'
                + (window.CSS && CSS.escape ? CSS.escape(pend[k]) : pend[k]) + '"]')) {{
                _rndEnsureFolderIn(list, pend[k]);
            }}
        }}
    }}
}}
window.addEventListener('DOMContentLoaded', rndFolderInit);
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

# WinError codes for the benign "the client went away" socket conditions.
# 10053 = WSAECONNABORTED (an established connection aborted by the host/software),
# 10054 = WSAECONNRESET (connection reset by peer). These ride in on a generic
# OSError on Windows (BufferedWriter.write → sock.sendall) rather than as the
# typed ConnectionAbortedError / ConnectionResetError, so we sniff .winerror too.
_BENIGN_DISCONNECT_WINERRORS = (10053, 10054)


def _is_benign_disconnect(exc):
    """True for a socket-teardown error that means the CLIENT closed the
    connection mid-response — not a server bug. A browser closing a terminal
    tab (or Playwright tearing down a page) makes the in-flight SSE/WS/HTTP
    write raise one of these; treating them as a normal client-gone condition
    is correct production behavior, never an error to surface or log loudly.

    Catches the typed connection-teardown exceptions AND a Windows OSError whose
    ``winerror`` is 10053/10054 (which is how the abort actually arrives on the
    BufferedWriter.write → sock.sendall path). Deliberately TIGHT — it never
    swallows a generic OSError/Exception that could hide a real defect.
    """
    if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                        ConnectionAbortedError)):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) \
            in _BENIGN_DISCONNECT_WINERRORS:
        return True
    return False


class AnchorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def log_error(self, format, *args):
        # Quiet the benign client-disconnect noise the base class would log to
        # stderr (it routes BrokenPipe/ConnectionReset/timeout messages here).
        # Real protocol errors still surface via the normal response paths.
        return

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            # Client closed mid-response (browser tab close / Playwright
            # teardown). Nothing left to send — swallow ONLY the benign
            # disconnect; re-raise anything else.
            if _is_benign_disconnect(exc):
                return
            raise

    def _send_html(self, html_text):
        body = html_text.encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if _is_benign_disconnect(exc):
                return
            raise

    def _send_bytes(self, data, content_type, cache="no-cache"):
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            if _is_benign_disconnect(exc):
                return
            raise

    # ── SSE for the interactive terminal (Wave 7) ────────────────────────────
    def _sse_event(self, event, data_obj):
        """Write ONE well-formed SSE event frame and flush it.

        Frame shape (per the SSE spec): an ``event:`` line, one ``data:`` line
        carrying a JSON payload, then a BLANK line terminating the event. Flushed
        immediately so a streaming client observes events as they arrive.

        Teardown hardening: writing/flushing onto a ``wfile`` whose underlying
        socket was already closed (client gone, or the request thread torn down
        out from under a leaked pump) raises ``ValueError("I/O operation on
        closed file")`` — which is a benign client-gone condition, not a server
        bug, but it is NOT in the OSError family the stream loops guard on. We
        normalize it to a ``BrokenPipeError`` so the existing
        ``except (BrokenPipeError, ConnectionResetError, OSError)`` guards end
        the stream CLEANLY (the daemon thread never raises a stray ValueError on
        teardown). The benign socket-teardown OSErrors propagate unchanged for
        those same guards; any non-benign error is re-raised untouched.
        """
        payload = json.dumps(data_obj, ensure_ascii=False)
        frame = f"event: {event}\ndata: {payload}\n\n"
        try:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
        except ValueError as exc:
            # I/O on a closed file (wfile closed under us) == client/connection
            # gone. Re-raise as BrokenPipeError so the OSError-family guards
            # catch it; never swallow a different ValueError.
            if "closed file" in str(exc):
                raise BrokenPipeError(str(exc)) from exc
            raise

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
            # High backstop (the loop ends on a terminal session or client
            # disconnect); the old 240/5000 ceiling froze the SSE fallback after
            # ~60s. Tests pass an explicit small max_ticks.
            max_ticks = int(q.get("max_ticks", ["4000000"])[0] or 4000000)
        except (TypeError, ValueError):
            max_ticks = 4000000
        # Clamp client-supplied knobs (self-DoS guard): poll in [0.01, 1.0]s,
        # max_ticks in [1, 4_000_000] (high backstop — loop ends on close/done).
        poll_interval = min(1.0, max(0.01, poll_interval))
        max_ticks = min(4000000, max(1, max_ticks))
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
            # Default is effectively "for the life of the connection": the loop
            # already breaks on client close (recv b"") or a dead session, so this
            # is only a runaway backstop. The old 1200/5000 ceiling (~60-250s) was
            # the FREEZE bug — a multi-minute session lost its stream and went
            # silent. Tests pass an explicit small max_ticks via the query knob.
            max_ticks = int(q.get("max_ticks", ["4000000"])[0] or 4000000)
        except (TypeError, ValueError):
            max_ticks = 4000000
        # Clamp client-supplied knobs (self-DoS guard): poll in [0.01, 1.0]s,
        # max_ticks in [1, 4_000_000] (a high backstop — the loop ends on close).
        poll_interval = min(1.0, max(0.01, poll_interval))
        max_ticks = min(4000000, max(1, max_ticks))

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
            elif self.path.startswith(BRAND_URL_PREFIX):
                # Read-only vendored Ghost World Labs brand mark static asset
                # (Wave 9), served like KaTeX/xterm (traversal-safe). Backs the
                # home-page lockup and the dashboard favicon.
                rel = urlparse(self.path).path[len(BRAND_URL_PREFIX):]
                asset = brand_asset(rel)
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
            elif self.path.startswith("/api/rnd/handoff_proposal"):
                # Read-only stage-handoff PROPOSAL (v3 Wave 7): the UI shows
                # "execute on this plan set?" BEFORE launching a build session.
                # Pure metadata (structure-only, no contents) — read endpoint,
                # consistent with the other read GETs (no token required).
                # /api/rnd/handoff_proposal?project_id=<id>&lane=build[&seed_session=<sid>]
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0]
                       or q.get("id", [""])[0] or "").strip()
                lane = (q.get("lane", ["build"])[0] or "build").strip()
                seed = (q.get("seed_session", [""])[0] or "").strip() or None
                if not pid:
                    self._send_json({"ok": False,
                                     "error": "project_id required"}, 400)
                elif _unsafe_path_seg(pid):
                    self._send_json({"ok": False, "error": "bad pid"}, 400)
                elif _unsafe_path_seg(lane):
                    self._send_json({"ok": False, "error": "bad lane"}, 400)
                elif seed and _unsafe_path_seg(seed):
                    self._send_json({"ok": False, "error": "bad seed"}, 400)
                else:
                    proj = _rnd.get_project(pid)
                    if proj is None:
                        self._send_json({"ok": False,
                                         "error": "Unknown project"}, 404)
                    else:
                        folder = proj.get("folder_path", "")
                        try:
                            prop = _handoff.propose_handoff(
                                folder, pid, lane, source_session_id=seed)
                        except Exception:
                            prop = {"has_plan_set": False}
                        self._send_json({"ok": True, **prop})
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
                        # session so generation can seed from its members. v8 Wave
                        # 5 — a killed managed session's produced docs are persisted
                        # tagged with its id (they GROUP elsewhere in list_sessions),
                        # so resolve via _resolve_finished_session which TIES the
                        # managed id to those exact docs. Unresolvable → TERMINAL
                        # "unknown" (the panel stops polling); else kick off
                        # background generation run-once and tell the panel to poll.
                        session = None
                        try:
                            session = _resolve_finished_session(
                                folder, pid, lane, session_id)
                        except Exception:
                            session = None
                        if session is None:
                            self._send_json({"ok": True, "status": "unknown"})
                        else:
                            _trigger_session_summary(
                                folder, pid, lane, session)
                            self._send_json({"ok": True, "status": "generating"})
            elif self.path.startswith("/api/rnd/session_doc_roles"):
                # Read-only (v4 Wave 5): the per-lane ROLE→doc map for one
                # session (summarizer.session_doc_roles, Wave 3). The cockpit's
                # split-summary RIGHT column (.slinks) renders these role-tagged
                # links. Each href reuses the EXISTING /report and /artifact
                # routes; absent roles are simply omitted (never fabricated).
                # AUTH: ``?token=`` (read-only GET; back-compat when no token set).
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
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
                    try:
                        roles = _summarizer.session_doc_roles(
                            pid, lane, session_id)
                    except Exception:
                        roles = {}
                    self._send_json({"ok": True, "roles": roles})
            elif self.path.startswith("/api/rnd/build_deliverable"):
                # Read-only (v5 Wave 4): resolve the DELIVERABLE one BUILD session
                # produced — explicit signals only, never fabricated. The build
                # panel fetches this to show the deliverable (name/type/link) or an
                # honest "no deliverable pinned yet" placeholder when unresolved.
                # NO mutation, NO model call. AUTH: ``?token=`` (read-only GET).
                # /api/rnd/build_deliverable?pid=<id>&lane=build&session=<sid>
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("pid", [""])[0]
                       or q.get("project_id", [""])[0] or "").strip()
                lane = (q.get("lane", ["build"])[0] or "build").strip()
                session_id = (q.get("session", [""])[0] or "").strip()
                if not pid or not session_id:
                    self._send_json({"ok": False,
                                     "error": "pid, session required"}, 400)
                elif _unsafe_path_seg(pid):
                    self._send_json({"ok": False, "error": "bad pid"}, 400)
                elif _unsafe_path_seg(lane):
                    self._send_json({"ok": False, "error": "bad lane"}, 400)
                else:
                    proj = _rnd.get_project(pid)
                    folder = (proj or {}).get("folder_path", "")
                    result = {"resolved": False, "deliverable": None,
                              "reason": "no deliverable pinned yet"}
                    try:
                        session = None
                        for s in _sessions.list_sessions(folder, pid, lane):
                            if s.get("session_id") == session_id:
                                session = s
                                break
                        if session is not None:
                            result = _deliv.resolve_build_deliverable(
                                folder, pid, session)
                    except Exception:
                        result = {"resolved": False, "deliverable": None,
                                  "reason": "no deliverable pinned yet"}
                    self._send_json({"ok": True,
                                     "resolved": bool(result.get("resolved")),
                                     "deliverable": result.get("deliverable"),
                                     "reason": result.get("reason", "")})
            elif self.path.startswith("/api/rnd/grass"):
                # Read-only (v5 Wave 5): the project's Grass ideas + their status
                # + versioned refinements, for the two-pane idea workbench. NO
                # mutation, NO model call. AUTH: ``?token=`` (read-only GET;
                # back-compat when no token set). Project-scoped (no cross-project
                # grass view). /api/rnd/grass?project_id=<id>
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0]
                       or q.get("pid", [""])[0]
                       or q.get("id", [""])[0] or "").strip()
                if not pid:
                    self._send_json({"ok": False,
                                     "error": "project_id required"}, 400)
                elif _unsafe_path_seg(pid):
                    self._send_json({"ok": False, "error": "bad pid"}, 400)
                else:
                    proj = _rnd.get_project(pid)
                    if proj is None:
                        self._send_json({"ok": False,
                                         "error": "Unknown project"}, 404)
                    else:
                        folder = proj.get("folder_path", "")
                        try:
                            ideas = _eh.grass_workbench_data(folder, pid)
                        except Exception:
                            ideas = []
                        self._send_json({"ok": True, "ideas": ideas})
            elif self.path.startswith("/api/rnd/boneyard"):
                # Read-only (v10 Wave 7): the project's per-project Boneyard — a
                # searchable list of DISCARDED material (hard-killed sessions w/
                # material, v9-deleted sessions, deleted grass ideas). NO mutation,
                # NO model call. AUTH: ``?token=`` (read-only GET; back-compat when
                # no token set), mirroring /api/rnd/grass. Project-scoped (D4 —
                # never a cross-project view).
                #   /api/rnd/boneyard?project_id=<id>&q=<query>
                # Empty ``q`` → ALL entries (newest-first); else boneyard.search.
                # Each entry is the SAFE projection (boneyard._SAFE_KEYS — never an
                # absolute path / worktree / branch) PLUS server-built, traversal-
                # safe ``doc_links`` (href via the existing /artifact route — the
                # file survives on disk by rel path regardless of source, Option A,
                # so /artifact is ALWAYS resolvable and consistent across sources).
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0]
                       or q.get("pid", [""])[0]
                       or q.get("id", [""])[0] or "").strip()
                query = (q.get("q", [""])[0] or "").strip()
                if not pid:
                    self._send_json({"ok": False,
                                     "error": "project_id required"}, 400)
                elif _unsafe_path_seg(pid):
                    self._send_json({"ok": False, "error": "bad pid"}, 400)
                else:
                    proj = _rnd.get_project(pid)
                    if proj is None:
                        self._send_json({"ok": False,
                                         "error": "Unknown project"}, 404)
                    else:
                        folder = proj.get("folder_path", "")
                        try:
                            if query:
                                entries = _boneyard.search(folder, pid, query)
                            else:
                                entries = _boneyard.list_entries(folder, pid)
                        except Exception:
                            entries = []
                        out = [_boneyard_entry_view(pid, e) for e in entries]
                        self._send_json({"ok": True, "entries": out, "q": query})
            elif self.path.startswith("/api/rnd/remote_status"):
                # Read-only (v8 Wave 3): the project's GitHub link state for the
                # header control — {linked, remote_url, auto_push}. NO mutation,
                # NO network. AUTH: ``?token=`` (read-only GET; back-compat when
                # no token set). /api/rnd/remote_status?project_id=<id>
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0]
                       or q.get("pid", [""])[0]
                       or q.get("id", [""])[0] or "").strip()
                if not pid:
                    self._send_json({"ok": False,
                                     "error": "project_id required"}, 400)
                elif _unsafe_path_seg(pid):
                    self._send_json({"ok": False, "error": "bad pid"}, 400)
                elif _rnd.get_project(pid) is None:
                    self._send_json({"ok": False,
                                     "error": "Unknown project"}, 404)
                else:
                    st = _remote.remote_status(pid)
                    self._send_json({"ok": True, "linked": st["linked"],
                                     "remote_url": st["remote_url"],
                                     "auto_push": st["auto_push"]})
            elif self.path.startswith("/api/rnd/project_rollup"):
                # Read-only (v4 Wave 5): the per-project cost/tokens/time rollup
                # (effort_history.project_effort_rollup, Wave 3) for the header's
                # lifetime/30-day toggle. RUN-session totals only (imported /
                # discovered contribute 0 — never fabricated). Returns both the
                # raw fields and a pre-formatted ``text`` for the header swap.
                # AUTH: ``?token=`` (read-only GET; back-compat when no token set).
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("pid", [""])[0]
                       or q.get("project_id", [""])[0] or "").strip()
                window = (q.get("window", ["lifetime"])[0] or "lifetime").strip()
                if window not in (_eh.WINDOW_LIFETIME, _eh.WINDOW_30D):
                    window = _eh.WINDOW_LIFETIME
                if not pid:
                    self._send_json({"ok": False, "error": "pid required"}, 400)
                elif _unsafe_path_seg(pid):
                    self._send_json({"ok": False, "error": "bad pid"}, 400)
                else:
                    try:
                        roll = _eh.project_effort_rollup(pid, window=window)
                    except Exception:
                        roll = {"tokens": 0, "cost_usd": 0.0,
                                "wall_clock_ms": 0, "sessions": 0}
                    self._send_json({"ok": True, "window": window,
                                     "rollup": roll,
                                     "text": _fmt_rollup_line(roll)})
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
                # Read-only: managed terminal sessions for a project — the
                # repopulate-from-registry hook the cockpit tiles row paints from
                # on load. Returns a SAFE projection of each registry record (NO
                # absolute worktree_path / branch — the UI has no need for them,
                # and they MUST NOT leak). Consistent with /api/rnd/projects
                # (GET, no mutation, no auth gate).
                #
                # v6 Wave 4: this projection now INCLUDES terminal-status
                # (done/failed) sessions too — finished tiles stay in the row as
                # greyed, reopenable tiles (newest-prominent + "previously done").
                # It also carries the Wave-2 lineage fields
                # (parent_session_id / chain_id) so the front end can group a
                # chain. Still SAFE: worktree_path / branch are NEVER included.
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0] or "").strip()
                # v6 Wave 9 (polish 3): wire the reconcile→auto-advance into the
                # project-window refresh/poll path. Before listing, reconcile the
                # registry against the LIVE PTY set: a managed planning session
                # whose process is gone is re-statused DONE and (idempotently)
                # auto-advanced to ONE linked build — so a planning session that
                # DIED (not just an explicit hard-kill) advances on the next
                # refresh. Idempotent on parent_session_id → repeated polls are
                # no-ops. Best-effort + fully guarded: an error here NEVER breaks
                # the (read-only) session list response. live_session_ids MUST be
                # passed (the function default treats NO session as live, which
                # would wrongly mark live ones stale).
                try:
                    live = list(_termsess._pty.live_sessions())
                    _rec_out = _termsess.reconcile_and_advance(
                        live_session_ids=live)
                    # v7 Wave 2: any session newly re-statused DONE by the
                    # reconcile-dead path gets a background session-summary
                    # scheduled (best-effort, non-blocking, idempotent — a cached
                    # one is skipped, so repeated polls don't re-run the model).
                    # Never breaks the read-only session-list response.
                    try:
                        marked = ((_rec_out or {}).get("reconcile", {})
                                  or {}).get("marked", []) or []
                        for _sid in marked:
                            _r = _termsess.get_session(_sid)
                            if _r is None:
                                continue
                            _trigger_session_summary_on_finish(
                                _r.get("project_id"), _r.get("lane"), _sid)
                    except Exception:
                        pass
                except Exception:
                    pass
                try:
                    recs = _termsess.list_sessions(project_id=pid or None)
                except Exception:
                    recs = []
                safe = []
                for r in recs:
                    if not isinstance(r, dict):
                        continue
                    # v10 Wave 5 (DEFECT-2 fix): a CONTAINED grass-workbench
                    # develop session (research/plan, [grass-dev] label) must NOT
                    # surface on the top strip. It is mounted by session id
                    # directly in the workbench pane (developGrass), not via this
                    # projection, so dropping it here keeps the contained promise
                    # at the source (the JS top-strip guard is the belt-and-braces
                    # second line). Nothing else consumes this projection for
                    # grass-dev sessions (the chain breadcrumb uses chain_members).
                    if _eh.is_grass_dev_label(r.get("label")):
                        continue
                    safe.append({
                        "session_id": r.get("session_id"),
                        "project_id": r.get("project_id", ""),
                        "lane": r.get("lane", ""),
                        "backend": r.get("backend", ""),
                        "status": r.get("status", ""),
                        "label": r.get("label", ""),
                        "created_at": r.get("created_at"),
                        "parent_session_id": r.get("parent_session_id", ""),
                        "chain_id": r.get("chain_id", ""),
                        # v10 Wave 4: grass→project lineage (SAFE — idea id only,
                        # never worktree_path/branch).
                        "grass_origin": r.get("grass_origin", ""),
                    })
                self._send_json({"ok": True, "sessions": safe})
            elif self.path.startswith("/api/rnd/chain"):
                # Read-only (v6 Wave 5): the ordered lineage chain a session
                # belongs to, for the panel-header breadcrumb (R-1 → P-2 → …).
                # Resolves chain_for(session) → chain_members(chain_id) and emits
                # a SAFE projection of each member (session_id / lane / label /
                # status / parent_session_id / chain_id — NEVER worktree_path or
                # branch). AUTH: ``?token=`` (read-only GET; back-compat when no
                # token configured). /api/rnd/chain?project_id=<id>&session=<sid>
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                q = parse_qs(urlparse(self.path).query)
                sid = (q.get("session", [""])[0]
                       or q.get("session_id", [""])[0] or "").strip()
                if not sid:
                    self._send_json({"ok": False,
                                     "error": "session required"}, 400)
                else:
                    try:
                        chain_id = _sessreg.chain_for(sid)
                        members = (_sessreg.chain_members(chain_id)
                                   if chain_id else [])
                    except Exception:
                        chain_id = None
                        members = []
                    safe = []
                    for r in members:
                        if not isinstance(r, dict):
                            continue
                        safe.append({
                            "session_id": r.get("session_id"),
                            "lane": r.get("lane", ""),
                            "label": r.get("label", ""),
                            "status": r.get("status", ""),
                            "parent_session_id": r.get("parent_session_id", ""),
                            "chain_id": r.get("chain_id", ""),
                            # v10 Wave 4: grass→project lineage (SAFE — idea id only).
                            "grass_origin": r.get("grass_origin", ""),
                        })
                    self._send_json({"ok": True, "chain_id": chain_id or "",
                                     "members": safe})
            elif self.path.startswith("/api/rnd/board_html"):
                # Read-only (v7 Wave 6): the project's rendered 5-lane board
                # FRAGMENT, so an already-open project window can refresh the
                # board IN PLACE after a session-lifecycle mutation (start /
                # finish / advance / promote / develop) and the lane-column
                # tile appears WITHOUT a full page reload. REUSES
                # _render_kanban_html (the SAME server render the page used) —
                # the board is the single source of truth, so the JS just
                # re-fetches it (no duplicate JS-injected tile; dedupe stays
                # correct = exactly one tile per session in its lane). SAFE: the
                # kanban render already emits SAFE tiles (no absolute
                # worktree_path / branch). AUTH: ``?token=`` (read-only GET;
                # back-compat when no token configured), consistent with the
                # other ?token= GET seams. /api/rnd/board_html?project_id=<id>
                if not self._term_token_ok():
                    self._send_json({"ok": False, "error": "unauthorized"}, 401)
                    return
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0] or "").strip()
                entry = _rnd.get_project(pid) if pid else None
                if not pid or entry is None:
                    self._send_json({"ok": False,
                                     "error": "unknown project"}, 404)
                    return
                folder_raw = entry.get("folder_path", "")
                try:
                    frag = _render_kanban_html(folder_raw, pid)
                except Exception:
                    frag = ("<div class='p2lanes'><p class='rnd-empty'>"
                            "Board unavailable.</p></div>")
                self._send_json({"ok": True, "html": frag})
            elif self.path.startswith("/api/rnd/projects_html"):
                # Read-only (v5 Wave 3): the rendered R&D rows FRAGMENT, so an
                # already-open main dashboard can poll for changes (new session,
                # added idea, priority/notes/blurb edit, archive, new project,
                # refreshed summary, rollups) and swap them in WITHOUT a full
                # page reload. REUSES render_projects_view_html (which reads
                # ONLY the cached summaries — no synchronous model run here). No
                # mutation, no auth gate (consistent with /api/rnd/projects).
                try:
                    frag = render_projects_view_html()
                except Exception:
                    frag = ('<div class="rnd-projects"><p class="rnd-empty">'
                            'No active R&amp;D projects.</p></div>')
                self._send_json({"ok": True, "html": frag})
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
            elif self.path.startswith("/api/rnd/previews"):
                # Read-only: list ephemeral deliverable previews for a project
                # (reconciles dead previews → stopped so the UI repopulates
                # truthfully on reconnect). Wave 8. Returns a SAFE projection of
                # each registry record — NO absolute filesystem paths
                # (data_dir / folder_path); the UI only needs the id/url/port/
                # status. Consistent with the term_sessions projection (which
                # strips worktree_path). The persisted record (.anchor/
                # previews.json) keeps the full fields for reaping.
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0] or "").strip() or None
                safe = []
                for r in _preview.list_previews(pid):
                    if not isinstance(r, dict):
                        continue
                    safe.append({
                        "preview_id": r.get("preview_id"),
                        "project_id": r.get("project_id"),
                        "target": r.get("target", ""),
                        "port": r.get("port"),
                        "url": r.get("url", ""),
                        "status": r.get("status", ""),
                        "started_at": r.get("started_at"),
                        "stopped_at": r.get("stopped_at"),
                    })
                self._send_json({"ok": True, "previews": safe})
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            if _is_benign_disconnect(e):
                # Client closed the connection mid-GET (browser tab close /
                # Playwright teardown). Not a server error — stop silently;
                # the socket is gone so there's nothing to write back.
                return
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

        elif self.path == "/api/rnd/set_group":
            # v9 Wave 3 — reassign a project's dashboard FOLDER (group) only.
            # Organization-only: this NEVER moves anything on disk (that is the
            # v9 Wave 4 guarded on-disk move). Token-gated by the do_POST middleware.
            pid = body.get("project_id", "") or body.get("id", "")
            group = body.get("group", "")
            try:
                entry = _rnd.set_group(pid, group)
                self._send_json({
                    "ok": True,
                    "entry": entry,
                    "message": (f"Grouped under '{entry.get('group')}'"
                                if entry.get("group")
                                else "Moved to Ungrouped"),
                })
            except KeyError:
                self._send_json({"ok": False, "error": "Not found"}, 404)

        elif self.path == "/api/rnd/move_project":
            # v9 Wave 4 — GUARDED on-disk move: relocate a project's directory
            # into a group subfolder and re-point registry+worktrees+discovery.
            # Token-gated by the do_POST middleware above AND requires an
            # explicit confirm:true (a real, irreversible filesystem move).
            # REFUSES (no fs change) the running Anchor repo + any live-session
            # project, surfacing the refusal reason. NEVER raises into here.
            import project_move as _pmove
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            group = body.get("group", "")
            confirm = bool(body.get("confirm"))
            if not pid:
                self._send_json(
                    {"ok": False, "error": "project_id required"}, 400)
            elif not confirm:
                self._send_json({"ok": False,
                                 "error": "move requires confirm:true",
                                 "reason": "confirm-required"}, 400)
            else:
                try:
                    out = _pmove.move_to_group(pid, group)
                except Exception as exc:  # defensive — move_to_group never raises
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                else:
                    status = 200 if out.get("ok") else (
                        404 if out.get("reason") == "unknown-project" else 400)
                    self._send_json(out, status)

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

        elif self.path == "/api/rnd/launch_deliverable":
            # v4 Wave 7: TYPE-AWARE launch of a pinned deliverable. Dispatches on
            # the deliverable's type — skill/tool VERIFY status (no spawn);
            # service launches/pulls-up a persistent preview (free port != 8777,
            # isolated temp data dir); program runs to result; doc returns the
            # rendered view href. Auth is enforced by the middleware above.
            pid = (body.get("project_id", "") or body.get("pid", "")).strip()
            deliverable_id = (body.get("deliverable_id", "") or "").strip()
            proj = _rnd.get_project(pid)
            if proj is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            elif not deliverable_id:
                self._send_json({"ok": False,
                                 "error": "deliverable_id required"}, 400)
            else:
                folder = proj.get("folder_path", "")
                try:
                    res = _deliv.launch_deliverable(folder, pid, deliverable_id)
                except Exception as exc:  # never a 500 to the UI
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                else:
                    if not res.get("ok") and \
                            res.get("reason") == "unknown deliverable":
                        # Unknown deliverable id → clean 404 (not a crash).
                        self._send_json({"ok": False,
                                         "error": "unknown deliverable",
                                         "reason": "unknown-deliverable"}, 404)
                    elif not res.get("ok"):
                        # Type-specific clean failure (e.g. service never came
                        # up / program failed its contract) → 400, not a 500.
                        self._send_json({"ok": False,
                                         "error": res.get("reason")
                                         or "launch failed",
                                         "type": res.get("type"),
                                         "port": res.get("port")}, 400)
                    else:
                        self._send_json({"ok": True, **res})

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

        # ── Runnable Anchor deliverable — ephemeral preview (Wave 8) ──
        elif self.path == "/api/rnd/preview_start":
            # Spin up an EPHEMERAL preview of the project's deliverable web app
            # (e.g. anchor_gui.py) on an OS-assigned free port (NEVER 8777) in an
            # isolated TEMP ANCHOR_DATA_DIR — so it can never bind or disturb the
            # live :8777 service. Auth is enforced by the middleware above.
            pid = (body.get("project_id", "") or "").strip()
            proj = _rnd.get_project(pid)
            if proj is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                folder = proj.get("folder_path", "")
                target = (body.get("deliverable") or body.get("target")
                          or _preview.DEFAULT_TARGET)
                res = _preview.start_preview(folder, pid, target=target)
                if res.get("ok"):
                    self._send_json({"ok": True, "url": res.get("url"),
                                     "preview_id": res.get("preview_id"),
                                     "port": res.get("port"),
                                     "pid": res.get("pid")})
                else:
                    # Clean 400 (e.g. target missing / never came up), not a 500.
                    self._send_json({"ok": False,
                                     "error": res.get("reason", "preview failed"),
                                     "port": res.get("port")}, 400)

        elif self.path == "/api/rnd/preview_stop":
            # Tree-kill + reap a running preview. Idempotent; 404 for unknown id.
            preview_id = (body.get("preview_id", "") or "").strip()
            res = _preview.stop_preview(preview_id)
            if res.get("ok"):
                self._send_json({"ok": True,
                                 "preview_id": res.get("preview_id"),
                                 "status": res.get("status")})
            else:
                self._send_json({"ok": False,
                                 "error": res.get("reason", "unknown preview"),
                                 "reason": "unknown-preview"}, 404)

        # ── ConPTY terminal session lifecycle (Wave 3) ────────────────
        # These are the NEW ConPTY surface — distinct from the v2 REPL
        # endpoints (start_terminal/term_input/term_stream). Auth is enforced
        # by the middleware above (mutating POSTs).
        elif self.path == "/api/rnd/term_start":
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            lane = (body.get("lane", "") or "").strip()
            backend = (body.get("backend", "") or "claude").strip() or "claude"
            label = body.get("label", "") or ""
            # Wave 6 seam → Wave 7: a launch-from-panel carries the source
            # session id as a seed hint. On a BUILD launch we now consume it:
            # after start_session creates the session+worktree, we discover the
            # most-recent plan set (preferring this seed_session's plan docs),
            # prime the worktree with a HANDOFF reference file, and record the
            # handoff in the per-project Anchor reference. The bare-PTY launch
            # still works when there is no plan set (no crash; priming skipped).
            _seed_session = (body.get("seed_session", "") or "").strip() or None
            if not pid or not lane:
                self._send_json({"ok": False,
                                 "error": "project_id and lane required"}, 400)
            else:
                proj = _rnd.get_project(pid)
                if proj is None:
                    self._send_json({"ok": False,
                                     "error": "Unknown project"}, 404)
                else:
                    try:
                        rec = _termsess.start_session(pid, lane, backend=backend,
                                                      label=label)
                    except _termsess.TerminalSessionError as exc:
                        self._send_json({"ok": False, "error": str(exc)}, 400)
                    else:
                        handoff_info = None
                        if lane in _handoff.BUILD_LANES:
                            folder = proj.get("folder_path", "")
                            try:
                                plan_set = _handoff.discover_recent_plan_set(
                                    folder, pid, source_session_id=_seed_session)
                            except Exception:
                                plan_set = None
                            if plan_set:
                                primed = _handoff.prime_worktree(
                                    rec.get("worktree_path", ""), plan_set,
                                    project_id=pid)
                                recorded = _handoff.record_handoff(
                                    folder, pid, rec.get("session_id", ""),
                                    plan_set)
                                handoff_info = {
                                    "plan_set": plan_set,
                                    "primed": primed,
                                    "recorded": bool(recorded.get("ok")),
                                }
                        resp = {"ok": True, "session": rec}
                        if handoff_info is not None:
                            resp["handoff"] = handoff_info
                        self._send_json(resp)

        elif self.path == "/api/rnd/term_kill":
            session = (body.get("session", "") or "").strip()
            if not session:
                self._send_json({"ok": False, "error": "session required"}, 400)
            elif _termsess.get_session(session) is None:
                self._send_json({"ok": False,
                                 "error": f"unknown session: {session}",
                                 "reason": "unknown-session"}, 404)
            else:
                # v6 Wave 6: a DELIBERATE hard-kill of a PLANNING session is a
                # DONE transition that may auto-advance to build.
                #
                # v8 Wave 4 (ordering fix): kill() PERSISTS the session's
                # freshly-produced docs into the MAIN folder (Wave 2,
                # capture-before-reap) BEFORE the worktree is reaped. The plan-set
                # capture (discover_recent_plan_set) reads the MAIN folder, so it
                # must run AFTER kill() — otherwise it sees the project as it was
                # before this session and the auto-opened build gets a stale (or no)
                # plan. So: kill (persists docs + sets STATUS_DONE + reaps), THEN
                # capture the now-persisted plan set, THEN auto-advance (idempotent
                # on parent_session_id; no plan ⇒ no advance). Best-effort.
                rec = _termsess.get_session(session)
                pid_for_advance = rec.get("project_id") if rec else None
                planning_kill = (
                    rec is not None
                    and rec.get("lane") in _termsess._PLANNING_LANES
                    and pid_for_advance)
                out = _termsess.kill(session)
                # v7 Wave 2: a killed session is DONE — schedule a background
                # session-summary so the finished tile opens to a real summary
                # (and so it's restartable). Best-effort + non-blocking +
                # idempotent (skips a cached one); never delays the kill response.
                try:
                    _trigger_session_summary_on_finish(
                        pid_for_advance or (rec.get("project_id") if rec else None),
                        rec.get("lane") if rec else None, session)
                except Exception:
                    pass
                # v8 Wave 3: auto-push the project AFTER kill() persisted the
                # produced docs (Wave 2, capture-before-reap) — but ONLY when the
                # project is linked to a remote AND has opted in. A non-linked or
                # non-opted project never pushes. Best-effort + never blocks the
                # kill response; in tests origin is a LOCAL BARE repo (no network).
                try:
                    _auto_push_on_finish(
                        pid_for_advance or (rec.get("project_id") if rec else None))
                except Exception:
                    pass
                auto_build = None
                if planning_kill:
                    # Capture the plan set AFTER kill() persisted this session's
                    # produced docs into the main folder (the ordering fix above).
                    try:
                        post_plan_set = _termsess.capture_plan_set(
                            pid_for_advance, session)
                    except Exception:
                        post_plan_set = None
                    try:
                        auto_build = _termsess.auto_advance_planning_to_build(
                            pid_for_advance, session,
                            plan_set=post_plan_set)
                    except Exception:
                        auto_build = None
                self._send_json({"ok": True, "result": out,
                                 "auto_build": auto_build})

        elif self.path == "/api/rnd/term_delete":
            # v9 Wave 1 — TRUE session delete (DISTINCT from term_kill). Removes
            # the session from Anchor entirely: hard-deletes the registry record
            # (so the tile stays gone across a reload), drops its lane effort
            # pointer-records / index entries / cached summary, and (if still
            # live) kills it first. The produced DOCUMENTS are KEPT (Option A).
            # Token-gated by the do_POST middleware above AND requires an explicit
            # confirm:true in the body (a deliberate, irreversible removal).
            session = (body.get("session", "") or "").strip()
            confirm = bool(body.get("confirm"))
            if not session:
                self._send_json({"ok": False, "error": "session required"}, 400)
            elif not confirm:
                self._send_json({"ok": False,
                                 "error": "delete requires confirm:true",
                                 "reason": "confirm-required"}, 400)
            else:
                try:
                    out = _termsess.delete_session(session)
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                else:
                    self._send_json({"ok": True,
                                     "deleted": bool(out.get("deleted")),
                                     "result": out})

        elif self.path == "/api/rnd/cleanup_ghost_sessions":
            # v9 Wave 1 — sweep a project's empty GHOST sessions (terminal/idle
            # registry records with NO tied efforts). Token-gated + confirm-gated
            # (it deletes records). Project-scoped.
            pid = (body.get("project_id", "") or "").strip()
            confirm = bool(body.get("confirm"))
            if not pid:
                self._send_json({"ok": False, "error": "project_id required"}, 400)
            elif not confirm:
                self._send_json({"ok": False,
                                 "error": "cleanup requires confirm:true",
                                 "reason": "confirm-required"}, 400)
            else:
                try:
                    out = _termsess.cleanup_ghost_sessions(pid)
                except Exception as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 500)
                else:
                    self._send_json({"ok": True,
                                     "removed": out.get("removed", [])})

        elif self.path == "/api/rnd/term_set_engine":
            # v4 Wave 2: toggle a live session to the other engine (claude|gemini).
            # Token-gated by the do_POST middleware above. Reaps + relaunches in
            # the SAME worktree, re-seeds once, updates the registry backend.
            session = (body.get("session", "") or "").strip()
            engine = (body.get("engine", "") or "").strip()
            if not session or not engine:
                self._send_json({"ok": False,
                                 "error": "session and engine required"}, 400)
            elif engine not in _termsess.VALID_BACKENDS:
                self._send_json({"ok": False,
                                 "error": "invalid engine (expected claude|gemini)",
                                 "reason": "invalid-engine"}, 400)
            elif _termsess.get_session(session) is None:
                self._send_json({"ok": False,
                                 "error": f"unknown session: {session}",
                                 "reason": "unknown-session"}, 404)
            else:
                try:
                    rec = _termsess.switch_engine(session, engine)
                except _termsess.TerminalSessionError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)
                else:
                    self._send_json({"ok": True, "session": rec})

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

        elif self.path == "/api/rnd/promote_grass":
            # v4 Wave 6: promote a Grass Catcher idea into a NEW seeded session in
            # the target lane (research|plan). Reuses the Wave-1 seed path via
            # effort_history.promote_grass_to_lane → terminal_session.start_session
            # so the opening turn loads the lane skill AND carries the idea text.
            # The idea REMAINS in grass (copy, never destroy). Auth enforced above.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            lane = (body.get("lane", "") or "").strip()
            if not pid or not idea_id or not lane:
                self._send_json(
                    {"ok": False,
                     "error": "project_id, idea_id and lane required"}, 400)
            elif lane not in _eh.PROMOTE_LANES:
                self._send_json(
                    {"ok": False,
                     "error": "lane must be one of %s"
                     % (", ".join(_eh.PROMOTE_LANES),)}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                try:
                    rec = _eh.promote_grass_to_lane(pid, idea_id, lane)
                    self._send_json({"ok": True, "session": rec})
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)
                except _termsess.TerminalSessionError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)

        elif self.path == "/api/rnd/grass_develop":
            # v5 Wave 5: DEVELOP a grass idea in a seeded WORKBENCH session in the
            # target lane (research|plan). Reuses the Wave-1 seed path via
            # effort_history.develop_grass_idea → terminal_session.start_session,
            # seeding the idea text + its latest refinements. The idea STAYS in
            # grass (copy, never destroy). Auth enforced by the middleware above.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            lane = (body.get("lane", "") or "").strip()
            backend = (body.get("backend", "") or "").strip() or None
            if not pid or not idea_id or not lane:
                self._send_json(
                    {"ok": False,
                     "error": "project_id, idea_id and lane required"}, 400)
            elif lane not in _eh.PROMOTE_LANES:
                self._send_json(
                    {"ok": False, "error": "lane must be one of %s"
                     % (", ".join(_eh.PROMOTE_LANES),)}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                try:
                    rec = _eh.develop_grass_idea(pid, idea_id, lane,
                                                 backend=backend)
                    self._send_json({"ok": True, "session": rec})
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)
                except _termsess.TerminalSessionError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)

        elif self.path == "/api/rnd/grass_save_refinement":
            # v5 Wave 5: save a NEW versioned refinement (grass-<id>/dev-N) for an
            # idea (append-only; auto-incrementing N). Marks the idea REFINED.
            # Auth enforced above. 404 unknown project, 400 unknown idea/empty.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            if not pid or not idea_id:
                self._send_json(
                    {"ok": False,
                     "error": "project_id and idea_id required"}, 400)
            else:
                proj = _rnd.get_project(pid)
                if proj is None:
                    self._send_json({"ok": False,
                                     "error": "Unknown project"}, 404)
                else:
                    folder = proj.get("folder_path", "")
                    try:
                        rec = _eh.save_grass_refinement(
                            folder, pid, idea_id,
                            text=body.get("text", ""),
                            label=body.get("label", ""),
                            artifacts=body.get("artifacts") or [],
                            session_id=body.get("session_id") or None)
                        self._send_json({"ok": True, "refinement": rec})
                    except ValueError as ve:
                        self._send_json({"ok": False, "error": str(ve)}, 400)

        elif self.path == "/api/rnd/grass_set_status":
            # v5 Wave 5: set a grass idea's lifecycle status (raw/refined/
            # promoted), validating the transition. Auth enforced above.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            status = (body.get("status", "") or "").strip()
            if not pid or not idea_id or not status:
                self._send_json(
                    {"ok": False,
                     "error": "project_id, idea_id and status required"}, 400)
            else:
                proj = _rnd.get_project(pid)
                if proj is None:
                    self._send_json({"ok": False,
                                     "error": "Unknown project"}, 404)
                else:
                    folder = proj.get("folder_path", "")
                    try:
                        rec = _eh.set_grass_status(
                            folder, pid, idea_id, status,
                            promoted_to_session=body.get("promoted_to_session"),
                            promoted_to_lane=body.get("promoted_to_lane"))
                        self._send_json({"ok": True, "idea": rec})
                    except ValueError as ve:
                        self._send_json({"ok": False, "error": str(ve)}, 400)

        elif self.path == "/api/rnd/grass_pull":
            # v5 Wave 5: PULL a chosen refinement version into a NEW seeded session
            # (research|plan). Reuses the Wave-1 seed path. Idea + refinement are
            # left untouched. Auth enforced above.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            refinement_id = (body.get("refinement_id", "") or "").strip()
            lane = (body.get("lane", "") or "").strip()
            backend = (body.get("backend", "") or "").strip() or None
            if not pid or not idea_id or not refinement_id or not lane:
                self._send_json(
                    {"ok": False,
                     "error": "project_id, idea_id, refinement_id and lane "
                              "required"}, 400)
            elif lane not in _eh.PROMOTE_LANES:
                self._send_json(
                    {"ok": False, "error": "lane must be one of %s"
                     % (", ".join(_eh.PROMOTE_LANES),)}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                try:
                    rec = _eh.pull_grass_refinement(
                        pid, idea_id, refinement_id, lane, backend=backend)
                    self._send_json({"ok": True, "session": rec})
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)
                except _termsess.TerminalSessionError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)

        elif self.path == "/api/rnd/grass_export":
            # v8 Wave 6: EXPORT an idea's research/plan develop WORK up into REAL
            # lane tiles (Option B): copy the develop docs up as board-visible
            # lane sessions AND mark the idea "promoted" with a link. The idea
            # STAYS in grass (copy, never destroy). Auth enforced above.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            if not pid or not idea_id:
                self._send_json(
                    {"ok": False, "error": "project_id and idea_id required"}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                try:
                    res = _eh.export_grass_to_project(pid, idea_id)
                    code = 200 if res.get("ok") else 400
                    self._send_json(res, code)
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)

        elif self.path == "/api/rnd/grass_archive":
            # v10 Wave 4 (D7): ARCHIVE a grass dev session's produced docs +
            # summary into a per-idea bundle (survives kill; available at
            # promotion). Distinct from grass_save_refinement (a text snapshot).
            # Token-gated by the do_POST middleware above. The idea STAYS in grass.
            # HONEST: ok:false + reason when there is no dev session / no docs.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            lane = (body.get("lane", "") or "").strip()
            if not pid or not idea_id or not lane:
                self._send_json(
                    {"ok": False,
                     "error": "project_id, idea_id and lane required"}, 400)
            elif lane not in _eh.PROMOTE_LANES:
                self._send_json(
                    {"ok": False, "error": "lane must be one of %s"
                     % (", ".join(_eh.PROMOTE_LANES),)}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                try:
                    res = _eh.archive_grass_session(pid, idea_id, lane)
                    # ok:false is an honest "nothing to archive" (200, not an
                    # error) — the bundle is None + a reason; never fabricated.
                    self._send_json(res, 200)
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)

        elif self.path == "/api/rnd/grass_advance":
            # v10 Wave 5 (Pillar 2 #2): ADVANCE a grass idea's RESEARCH dev session
            # → a linked grass PLAN dev session, staying INSIDE the workbench, using
            # the SAME paste-NOT-submit seeded handoff as the project-level advance
            # (Wave 1/2). effort_history.advance_grass_research_to_plan builds the
            # research→plan prompt from the research dev session's persisted docs,
            # starts (or focuses) the CONTAINED (idea, 'plan') dev session with
            # paste_prompt (held UNSENT) + parent_session_id (links the chain) +
            # grass_origin, and records the stage edge. Token-gated by the do_POST
            # middleware above. v11.1 Wave 2: the keystone snapshots a research
            # CONVERSATION's transcript when no file was written, so the plan session
            # ALWAYS opens (transcript-backed or honest-minimal prompt); the only
            # ok:false left is no-research-session (no research dev session at all to
            # advance FROM). The idea STAYS in grass.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            backend = (body.get("backend", "") or "").strip() or None
            if not pid or not idea_id:
                self._send_json(
                    {"ok": False, "error": "project_id and idea_id required"}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                try:
                    res = _eh.advance_grass_research_to_plan(
                        pid, idea_id, backend=backend)
                    # ok:false is an honest "nothing to advance" (200, not an
                    # error) — session is None + a reason; never fabricated.
                    self._send_json(res, 200)
                except ValueError as ve:
                    self._send_json({"ok": False, "error": str(ve)}, 400)
                except _termsess.TerminalSessionError as exc:
                    self._send_json({"ok": False, "error": str(exc)}, 400)

        elif self.path == "/api/rnd/grass_delete":
            # v9 Wave 2 — permanently DELETE a grass idea + all its grass-side
            # stores (pointer-record + index entry + refinements dir + the
            # contained dev_sessions). Token-gated by the do_POST middleware above
            # AND requires an explicit confirm:true (a deliberate, irreversible
            # removal). Project-scoped — never touches another project's grass.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            idea_id = (body.get("idea_id", "") or "").strip()
            confirm = bool(body.get("confirm"))
            if not pid or not idea_id:
                self._send_json(
                    {"ok": False, "error": "project_id and idea_id required"}, 400)
            elif not confirm:
                self._send_json({"ok": False,
                                 "error": "delete requires confirm:true",
                                 "reason": "confirm-required"}, 400)
            else:
                proj = _rnd.get_project(pid)
                if proj is None:
                    self._send_json({"ok": False,
                                     "error": "Unknown project"}, 404)
                else:
                    folder = proj.get("folder_path", "")
                    try:
                        out = _eh.delete_grass_idea(folder, pid, idea_id)
                    except Exception as exc:
                        self._send_json({"ok": False, "error": str(exc)}, 500)
                    else:
                        self._send_json({"ok": True,
                                         "deleted": bool(out.get("deleted")),
                                         "result": out})

        elif self.path == "/api/rnd/link_github":
            # v8 Wave 3: link the project's repo to a GitHub remote. mode=create
            # → gh repo create <name> --private (through the ANCHOR_GH_CMD seam —
            # NEVER real github.com in tests); mode=existing → git remote add
            # origin <url> (local). Persists the remote on the project record.
            # Default repos are PRIVATE. Auth enforced by the middleware above.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            mode = (body.get("mode", "") or "").strip().lower()
            value = (body.get("value", "") or "").strip()
            if not pid or not mode:
                self._send_json(
                    {"ok": False, "error": "project_id and mode required"}, 400)
            elif mode not in ("create", "existing"):
                self._send_json(
                    {"ok": False,
                     "error": "mode must be 'create' or 'existing'"}, 400)
            else:
                proj = _rnd.get_project(pid)
                if proj is None:
                    self._send_json({"ok": False,
                                     "error": "Unknown project"}, 404)
                else:
                    folder = proj.get("folder_path", "")
                    res = _remote.link_github(folder, mode, value,
                                              project_id=pid)
                    code = 200 if res.get("ok") else 400
                    self._send_json(res, code)

        elif self.path == "/api/rnd/set_auto_push":
            # v8 Wave 3: persist the per-project auto-push-on-finish opt-in flag.
            # Auth enforced above. A non-opted project never pushes.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            if not pid:
                self._send_json({"ok": False,
                                 "error": "project_id required"}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                enabled = bool(body.get("enabled"))
                _remote.set_auto_push(pid, enabled)
                self._send_json({"ok": True, "auto_push": enabled})

        elif self.path == "/api/rnd/push_now":
            # v8 Wave 3: manual "Push now" — git push -u origin <branch>. In tests
            # origin is a LOCAL BARE repo (file://) so there is NO network. Auth
            # enforced above. 400 when not linked (no origin). Never raises.
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            if not pid:
                self._send_json({"ok": False,
                                 "error": "project_id required"}, 400)
            elif _rnd.get_project(pid) is None:
                self._send_json({"ok": False, "error": "Unknown project"}, 404)
            else:
                proj = _rnd.get_project(pid)
                folder = proj.get("folder_path", "")
                res = _remote.push_project(folder, pid)
                code = 200 if res.get("ok") else 400
                self._send_json(res, code)

        elif self.path == "/api/rnd/continue_session":
            # v5 Wave 2: open a NEW live session in the SAME lane as a DONE/
            # historical session, SEEDED with that prior session's context (its
            # cached summary, else a deterministic digest of its members). The
            # ORIGINAL session/registry record is NEVER mutated (Risk R2) — we
            # only READ it. Reuses terminal_session.start_session(seed_context=…)
            # (the Wave-1 seed path), so the new session's single opening turn
            # loads the lane skill AND carries the prior context. Auth enforced by
            # the do_POST middleware above (mutating/terminal).
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            lane = (body.get("lane", "") or "").strip()
            source = (body.get("source_session", "")
                      or body.get("session", "") or "").strip()
            backend = (body.get("backend", "") or "").strip() or None
            if not pid or not lane or not source:
                self._send_json(
                    {"ok": False,
                     "error": "project_id, lane and source_session required"},
                    400)
            else:
                proj = _rnd.get_project(pid)
                if proj is None:
                    self._send_json({"ok": False,
                                     "error": "Unknown project"}, 404)
                else:
                    folder = proj.get("folder_path", "")
                    seed_context = _build_continue_seed(
                        folder, pid, lane, source)
                    try:
                        if backend:
                            rec = _termsess.start_session(
                                pid, lane, backend=backend,
                                seed_context=seed_context)
                        else:
                            rec = _termsess.start_session(
                                pid, lane, seed_context=seed_context)
                    except _termsess.TerminalSessionError as exc:
                        self._send_json({"ok": False, "error": str(exc)}, 400)
                    else:
                        self._send_json({"ok": True, "session": rec,
                                         "seeded_from": source})

        elif self.path == "/api/rnd/advance_session":
            # v6 Wave 5: MANUAL advance research → planning. Starts a NEW live
            # session in ``to_lane`` (defaults 'planning' for a research source),
            # LINKED to the source via ``parent_session_id`` (so it inherits the
            # source's ``chain_id`` — see session_registry.start_session / Wave 2),
            # and SEEDED with the source session's grounded summary/report context.
            # The seed is built by the SAME read-only _build_continue_seed helper
            # (its cached summary, else a member digest), so the SOURCE session /
            # registry record is NEVER mutated — we only READ it. Returns the new
            # session record in the same JSON shape as continue_session. Auth is
            # enforced by the do_POST token middleware above (mutating/terminal).
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            source = (body.get("source_session", "")
                      or body.get("session", "") or "").strip()
            to_lane = (body.get("to_lane", "") or "").strip() or "planning"
            backend = (body.get("backend", "") or "").strip() or None
            if not pid or not source:
                self._send_json(
                    {"ok": False,
                     "error": "project_id and source_session required"},
                    400)
            else:
                proj = _rnd.get_project(pid)
                if proj is None:
                    self._send_json({"ok": False,
                                     "error": "Unknown project"}, 404)
                else:
                    folder = proj.get("folder_path", "")
                    # Resolve the SOURCE session's lane for the seed lookup. The
                    # seed reads the source's CACHED summary in ITS lane; default
                    # to 'research' (the only source this wave advances).
                    src_lane = "research"
                    try:
                        for r in _termsess.list_sessions(project_id=pid):
                            if r.get("session_id") == source:
                                src_lane = r.get("lane") or src_lane
                                break
                    except Exception:
                        pass
                    # v11 Wave 2 — THE user-facing fix: route research→plan through
                    # the SHARED handoff KEYSTONE (terminal_session.prepare_stage_
                    # handoff), mirroring finish_to_build's capture-before-advance.
                    # The keystone (a) PERSISTS the live source session's produced
                    # docs into the MAIN project (copy + commit to main HEAD,
                    # session-tagged efforts — best-effort, idempotent, never raises)
                    # so they ride into the planning worktree (checked out off main
                    # HEAD); (b) BUILDS the REAL doc-referencing prompt (names the
                    # actual persisted paths + "read these first, then plan" + load
                    # Crucible — honest minimal only when there are genuinely no
                    # docs, never fabricated); (c) resolves doc_rels + skill + the
                    # source's cached summary for HANDOFF.md. This is the fix for the
                    # reported failure: the pre-v11 path NEVER persisted the live
                    # research docs, so the prompt was a bare "load Crucible" with no
                    # paths and no HANDOFF.md.
                    hk = _termsess.prepare_stage_handoff(pid, source, to_lane)
                    # v11 honesty guard: if the keystone could NOT resolve the
                    # source session (ok=False → no record / unknown id → empty
                    # prompt + empty doc_rels), do NOT mint an orphan planning
                    # session with an empty paste. Return an honest error instead
                    # (matching the honest-degradation discipline). The
                    # no-DOCS-but-valid-source path keeps ok=True and proceeds with
                    # the honest minimal prompt — only the source-unresolvable case
                    # is guarded here.
                    if not hk.get("ok"):
                        self._send_json(
                            {"ok": False,
                             "error": "could not resolve source session"}, 400)
                        return
                    # The reviewable TASK PROMPT is delivered as a PENDING PASTE
                    # (held in the new PTY input UNSENT until the user presses
                    # Enter — paste-NOT-submit, unchanged). The grounded summary
                    # context still seeds phase-1 (load+greet) so the model greets
                    # with prior context. Best-effort: an empty prompt → falls back
                    # to today's seed-context-only path (honest, no fabrication).
                    seed_context = _build_continue_seed(
                        folder, pid, src_lane, source)
                    paste = (hk.get("prompt", "") or "").strip() or None
                    try:
                        if backend:
                            rec = _termsess.start_session(
                                pid, to_lane, backend=backend,
                                seed_context=seed_context,
                                paste_prompt=paste,
                                parent_session_id=source)
                        else:
                            rec = _termsess.start_session(
                                pid, to_lane, seed_context=seed_context,
                                paste_prompt=paste,
                                parent_session_id=source)
                    except _termsess.TerminalSessionError as exc:
                        self._send_json({"ok": False, "error": str(exc)}, 400)
                    else:
                        # The planning worktree now EXISTS (off main HEAD, which the
                        # keystone just committed the research docs to). Write BOTH
                        # durable artifacts into it: the real HANDOFF.md (lists the
                        # persisted upstream doc paths + the Crucible skill + the
                        # source's cached summary) AND NEXT-PROMPT.md (the reviewable
                        # pasted prompt). Then record the research->plan stage edge.
                        # All best-effort — a write hiccup never strands the advance.
                        new_wt = rec.get("worktree_path", "")
                        new_sid = rec.get("session_id", "")
                        if new_wt:
                            try:
                                _handoff.write_handoff_md(
                                    new_wt, hk.get("doc_rels", []),
                                    hk.get("skill", "") or "Crucible",
                                    hk.get("summary_text", ""))
                            except Exception:
                                pass
                            if paste:
                                try:
                                    _handoff.write_next_prompt(new_wt, paste)
                                except Exception:
                                    pass
                        try:
                            _handoff.record_stage_link(
                                folder, pid, source, new_sid,
                                kind="research->plan")
                        except Exception:
                            pass
                        self._send_json({"ok": True, "session": rec,
                                         "advanced_from": source,
                                         "to_lane": to_lane,
                                         "persisted": hk.get("persisted", [])})

        elif self.path == "/api/rnd/finish_to_build":
            # v6 Wave 9 (polish 1): EXPLICIT, NON-DESTRUCTIVE plan→build advance.
            # Mirrors the term_kill auto-advance trigger, but WITHOUT reaping the
            # planning session's worktree: it stays a reopenable, finished tile
            # (close-to-tile philosophy). Steps:
            #   1. capture the plan set NOW (before any reap) via capture_plan_set;
            #   2. mark THIS planning session DONE via session_registry
            #      .update_session(status=STATUS_DONE) — NOT kill() (worktree kept);
            #   3. auto_advance_planning_to_build(..., plan_set=…) — idempotent on
            #      parent_session_id, so a second call never duplicates the build.
            # No plan set ⇒ {ok:true, auto_build:null, reason:"no plan set yet"} so
            # the UI can be honest (never a fabricated build). Auth is enforced by
            # the do_POST token middleware above (mutating).
            pid = (body.get("project_id", "") or body.get("id", "")).strip()
            session = (body.get("session", "")
                       or body.get("source_session", "") or "").strip()
            if not pid or not session:
                self._send_json(
                    {"ok": False,
                     "error": "project_id and session required"}, 400)
            else:
                rec = _termsess.get_session(session)
                if rec is None:
                    self._send_json({"ok": False,
                                     "error": f"unknown session: {session}",
                                     "reason": "unknown-session"}, 404)
                elif rec.get("lane") not in _termsess._PLANNING_LANES:
                    self._send_json(
                        {"ok": False,
                         "error": "finish→build applies only to a planning "
                                  "session",
                         "reason": "not-planning"}, 400)
                else:
                    # 0) v11 Wave 3 — route the persist through the SHARED keystone
                    #    (:func:`prepare_stage_handoff`), unifying this path with
                    #    research→plan + auto-advance. The keystone PERSISTS the
                    #    planning session's produced docs into the MAIN project (copy
                    #    + commit to main HEAD, session-tagged efforts — best-effort,
                    #    idempotent, never raises) WITHOUT reaping the worktree, so the
                    #    planning session stays a reopenable finished tile (v6
                    #    non-destructive finish semantics preserved). This is the
                    #    North-Star hole fix (the finish→build path marks the session
                    #    DONE via update_session WITHOUT kill(), so persist is NOT
                    #    otherwise run — the plan docs authored in the planning
                    #    worktree would never reach main, and the build worktree
                    #    created off main HEAD by auto_advance would lack the
                    #    HANDOFF.md/NEXT-PROMPT.md referenced paths). It is ALSO what
                    #    makes the just-authored plan set DISCOVERABLE to the
                    #    capture_plan_set() below: discovery reads the session-tagged
                    #    effort pointer-records the persist creates, so the persist
                    #    MUST run here, before capture, on the worktree-only finish
                    #    flow (the docs are not yet on main / not yet recorded as
                    #    efforts otherwise). The build prompt itself is (re)built by
                    #    auto_advance_planning_to_build through the SAME keystone
                    #    (idempotent re-persist), so there is ONE persist+prompt
                    #    mechanism across every advance path.
                    try:
                        _termsess.prepare_stage_handoff(pid, session, "build")
                    except Exception:
                        pass
                    # 1) Capture the plan set AFTER persisting (so the just-authored
                    #    plan docs are now on main HEAD and discoverable). No reap
                    #    here, so the worktree survives either way.
                    plan_set = _termsess.capture_plan_set(pid, session)
                    if not plan_set:
                        # Honest: no plan set yet ⇒ no build (worktree untouched;
                        # the session stays exactly as it was — we do NOT mark it
                        # done if there is nothing to advance to).
                        self._send_json({"ok": True, "auto_build": None,
                                         "reason": "no plan set yet"})
                    else:
                        # 2) Mark the planning session DONE WITHOUT reaping its
                        #    worktree (non-destructive — reopenable finished tile).
                        try:
                            _sessreg.update_session(
                                session, status=_sessreg.STATUS_DONE)
                        except KeyError:
                            pass
                        # v7 Wave 2: the finished planning session is DONE —
                        # schedule a background session-summary (best-effort,
                        # non-blocking, idempotent). Never delays this response.
                        try:
                            _trigger_session_summary_on_finish(
                                pid, rec.get("lane"), session)
                        except Exception:
                            pass
                        # 3) Auto-advance to ONE linked build (idempotent).
                        try:
                            auto_build = _termsess.auto_advance_planning_to_build(
                                pid, session, plan_set=plan_set)
                        except Exception:
                            auto_build = None
                        if auto_build is None:
                            self._send_json(
                                {"ok": True, "auto_build": None,
                                 "reason": "no build (already advanced or "
                                           "discovery failed)"})
                        else:
                            self._send_json({"ok": True,
                                             "auto_build": auto_build})

        # 2026-05-12: /api/shutdown removed. The NSSM "anchor" service on
        # gwl-server owns process lifecycle. To restart: run `nssm restart
        # anchor` on gwl-server. The dashboard cannot kill the server.

        else:
            self._send_json({"ok": False, "error": "Unknown endpoint"}, 404)
      except Exception as e:
            if _is_benign_disconnect(e):
                # Client closed the connection mid-POST. Not a server error.
                return
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


class _QuietDisconnectMixin:
    """Server mixin that quiets BENIGN client-disconnect errors.

    socketserver calls ``handle_error(request, client_address)`` when a request
    handler raises an unhandled exception, and by default it prints a full
    traceback to stderr. A browser closing a terminal tab (or Playwright tearing
    a page down) makes an in-flight SSE/WS/HTTP write raise
    ``ConnectionAbortedError``/``ConnectionResetError``/``BrokenPipeError`` (on
    Windows often a bare ``OSError`` with ``winerror`` 10053/10054). That is the
    client going away, not a server bug — so we swallow it silently here as a
    last line of defense (the handlers already break out of their stream loops
    on these). Any OTHER exception still gets the normal noisy traceback so real
    defects are never hidden.
    """

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if _is_benign_disconnect(exc):
            return
        super().handle_error(request, client_address)


class _ExclusiveThreadingHTTPServer(_QuietDisconnectMixin, ThreadingHTTPServer):
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


class _QuietThreadingHTTPServer(_QuietDisconnectMixin, ThreadingHTTPServer):
    """Plain ThreadingHTTPServer for the ephemeral ``port=0`` path (tests /
    health check) that also quiets benign client-disconnect errors — so a
    Playwright teardown racing an in-flight stream can't print a traceback or
    flake the gate."""
    daemon_threads = True


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
        server_cls = _QuietThreadingHTTPServer
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
    # v11.1 Wave 1 FIX-3: the keystone's background transcript-refine summary
    # (terminal_session._trigger_background_source_summary) gates on the
    # ANCHOR_PROACTIVE_SUMMARY env flag — it reads the env directly to avoid an
    # import cycle (terminal_session must not import anchor_gui). Set it here in
    # the SERVER main() path (never imported, never run in tests/healthcheck) so
    # the refine actually fires in production. Tests/the 5 AM healthcheck never
    # call main(), so they keep the flag unset/OFF and never spawn live claude.
    os.environ["ANCHOR_PROACTIVE_SUMMARY"] = "1"
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
