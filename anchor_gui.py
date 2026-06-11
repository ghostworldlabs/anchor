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

def parse_tasks_from_md(filepath):
    tasks = []
    if not filepath or not filepath.exists():
        return tasks
    text = filepath.read_text(encoding="utf-8")
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
    text = filepath.read_text(encoding="utf-8")
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
    text = filepath.read_text(encoding="utf-8")
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
    text = filepath.read_text(encoding="utf-8")
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

    if DASHBOARD_MD.exists():
        _add(parse_tasks_from_md(DASHBOARD_MD))
    if DOMAINS_DIR.exists():
        for f in sorted(DOMAINS_DIR.glob("*.md")):
            _add(parse_tasks_from_md(f), default_domain=f.stem)

    projects = []
    seen_p = set()
    if PROJECTS_MD.exists():
        for p in parse_projects_from_md(PROJECTS_MD):
            key = p["name"].lower().strip()[:60]
            if key not in seen_p:
                seen_p.add(key)
                projects.append(p)

    inbox = []
    if INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(INBOX_MD))

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
import deliverables as _deliv
import lanes as _lanes
import job_runner as _jr
import gate_adapter as _gate
import brownfield_scan as _bscan
import anchor_marker as _marker


def _unsafe_path_seg(seg: str) -> bool:
    """True if a URL segment is unsafe to use as a filesystem path component.

    Rejects path separators (``/`` ``\\``) and parent-dir traversal (``..``)
    before the value is used to build a filesystem path. Mirrors the
    path-traversal hardening on the vendored-KaTeX static route.
    """
    if seg is None:
        return False
    return "/" in seg or "\\" in seg or ".." in seg


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
    return {"ok": True, "scanned": dict(scan.counts), "adopt": adopt,
            "sibling_adopt": sibling, "marker": marker}


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


def render_project_tile_html(entry: dict) -> str:
    """Render a 'Rich' project tile: name, priority, state, effort rollup, notes,
    and lifecycle actions (open-in-its-own-window, change priority, edit notes,
    archive / retire — or reactivate for an inactive project)."""
    pid_raw = entry.get("id", "")
    pid = html_lib.escape(pid_raw)
    name = html_lib.escape(entry.get("name", ""))
    pr = entry.get("priority", 2)
    state = html_lib.escape(entry.get("state", "active"))
    notes = entry.get("notes", "") or ""
    notes_attr = html_lib.escape(notes, quote=True)
    folder = entry.get("folder_path", "")
    # Project blurb ("what this project is"): seed once from CLAUDE.md/README/
    # Anchor.md when empty, then render. Best-effort — never block the tile.
    blurb = entry.get("blurb", "") or ""
    if not blurb.strip():
        try:
            seeded = _rnd.seed_blurb(pid_raw)
            if seeded:
                blurb = seeded.get("blurb", "") or ""
        except Exception:
            pass
    blurb_attr = html_lib.escape(blurb, quote=True)
    blurb_block = (f'<div class="rnd-blurb" data-blurb="{blurb_attr}">'
                   f'{html_lib.escape(blurb)}</div>') if blurb.strip() else ''
    status = render_status_line_html(pid_raw)
    # Effort rollup ("amount of effort") — count + cost/time/tokens.
    try:
        total = _eh.project_rollup(pid_raw, folder).get("total", {})
        n_eff = int(total.get("effort_count", 0) or 0)
        n_imp = int(total.get("discovered_count", 0) or 0)
    except Exception:
        total, n_eff, n_imp = {}, 0, 0
    imported_bit = (f' · <span class="rnd-imported">{n_imp} imported</span>'
                    if n_imp else "")
    if n_eff:
        effort_line = (f'<div class="rnd-effort">{n_eff} effort'
                       f'{"s" if n_eff != 1 else ""}{imported_bit} · '
                       f'{html_lib.escape(_fmt_cost(total))}</div>')
    elif n_imp:
        # Brownfield project with only imported artifacts (no Anchor runs yet).
        effort_line = (f'<div class="rnd-effort">0 efforts{imported_bit}</div>')
    else:
        effort_line = '<div class="rnd-effort rnd-dim">no efforts yet</div>'
    notes_block = (f'<div class="rnd-notes" title="{notes_attr}">&#128221; '
                   f'{html_lib.escape(notes)}</div>') if notes.strip() else ''
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
    return (
        f'<div class="rnd-tile" data-project-id="{pid}" data-notes="{notes_attr}">'
        f'<div class="rnd-tile-head">'
        f'<span class="rnd-name">{name}</span>'
        f'<span class="rnd-badge rnd-p{pr}">P{pr}</span>'
        f'<span class="rnd-badge rnd-state-{state}">{state}</span>'
        f'</div>'
        f'{blurb_block}'
        f'{status}'
        f'{effort_line}'
        f'{notes_block}'
        f'<div class="rnd-actions">'
        f'<button class="rnd-mini rnd-open-btn" onclick="openProjectWindow(\'{pid}\')" '
        f'title="Open in its own window (multiple projects at once)">Open &#8599;</button>'
        f'{lifecycle}'
        f'</div>'
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
            f'<div class="rnd-folder-tiles">{tiles}</div>'
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
            add = (f"<span class='addnew rnd-dim' title='Grass Catchers content "
                   f"feeds arrive in a later build'>{html_lib.escape(add_label)}"
                   f"</span>")
        elif trio_lane == "research":
            add = (
                "<span class='addnew' onclick=\"launchLane('research','claude')\">"
                "+ New research run (Claude)</span> "
                "<span class='addnew' onclick=\"launchLane('research','gemini')\">"
                "Gemini</span>"
            )
        else:
            add = (f"<span class='addnew' onclick=\"launchLane('{trio_lane}')\">"
                   f"{html_lib.escape(add_label)}</span>")
        cols.append(
            f"<div class='col' data-col-lane='{html_lib.escape(trio_lane, quote=True)}'>"
            f"<h4><span>{glyph}</span> {html_lib.escape(label)} "
            f"<span class='badge' id='badge_{html_lib.escape(trio_lane, quote=True)}'>{badge}</span></h4>"
            f"<div class='col-cards' id='cards_{html_lib.escape(trio_lane, quote=True)}'>{cards}</div>"
            f"{add}</div>"
        )
    return "<div class='kan'>" + "".join(cols) + "</div>"


def _render_lane_sessions(session_views, store_lane, project_id):
    """Render a lane's sessions: most-recent visible + a "previous sessions"
    expander holding the rest (v2 Wave 4).

    Each session renders as ONE card (its representative = ``members[0]``); the
    remaining members of a multi-file session sit behind a small per-card
    "files (N)" expander so a 7-file Crucible run is one card, not seven. The
    representative keeps the existing click target (report viewer / attach /
    artifact) — summaries arrive in a later wave.
    """
    if not session_views:
        return ""
    def _render_session_card(sv):
        members = sv.get("members", [])
        if not members:
            return ""
        head = _render_effort_card(members[0], store_lane, project_id)
        rest = members[1:]
        if not rest:
            return head
        inner = "".join(
            _render_effort_card(m, store_lane, project_id) for m in rest)
        return (
            f"<div class='session'>{head}"
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
        # ── Console drawer (session tabs + attached log + ask + stop) ──
        "<div class='console' id='console'>"
        "<div class='ctabs'><span class='lbl'>Sessions</span>"
        "<span id='ctabs'></span>"
        "<span id='ctabsHint' style='margin-left:auto;font-size:11px;"
        "color:var(--text-dim)'>launch or click a live effort to attach ↑</span>"
        "</div>"
        "<div class='cbody'>"
        "<div class='src' id='consoleSrc'>No session attached.</div>"
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
        text = md_file.read_text(encoding="utf-8")
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
        text = md_file.read_text(encoding="utf-8")
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
        content = filepath.read_text(encoding="utf-8")
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
    content = INBOX_MD.read_text(encoding="utf-8")
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
        text = md_file.read_text(encoding="utf-8")
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

        text = md_file.read_text(encoding="utf-8")
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
        text = proj_file.read_text(encoding="utf-8")
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
        text = md_file.read_text(encoding="utf-8")
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
    content = filepath.read_text(encoding="utf-8")
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
    text = archive_file.read_text(encoding="utf-8")
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
.rnd-tile {{ border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; background: var(--surface2, #232733); display: flex; flex-direction: column; gap: 7px; }}
.rnd-tile:hover {{ border-color: var(--accent); }}
.rnd-tile-head {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
.rnd-name {{ font-weight: 600; font-size: 14px; }}
.rnd-badge {{ font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-dim); }}
.rnd-badge.rnd-p1 {{ background: rgba(248,113,113,.18); color: var(--danger); border-color: rgba(248,113,113,.3); }}
.rnd-badge.rnd-p2 {{ background: rgba(251,191,36,.15); color: var(--warning); border-color: rgba(251,191,36,.3); }}
.rnd-badge[class*="rnd-state-archived"], .rnd-badge[class*="rnd-state-future"], .rnd-badge[class*="rnd-state-retired"] {{ background: rgba(255,255,255,.04); }}
.rnd-effort {{ font-size: 11px; color: var(--accent); }}
.rnd-imported {{ color: var(--text-dim); font-style: italic; font-size: 11px; }}
.rnd-running {{ color: var(--success); font-size: 11px; }}
.rnd-effort.rnd-dim {{ color: var(--text-dim); }}
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
function rndNotes(pid) {{
    var el = document.querySelector('.rnd-tile[data-project-id="' + pid + '"]');
    var cur = el ? (el.getAttribute('data-notes') || '') : '';
    var n = window.prompt('Project notes:', cur);
    if (n === null) return;
    apiCall('/api/rnd/set_notes', {{id: pid, notes: n}});
}}
function rndBlurb(pid) {{
    var el = document.querySelector('.rnd-tile[data-project-id="' + pid + '"]');
    var bEl = el ? el.querySelector('.rnd-blurb') : null;
    var cur = bEl ? (bEl.getAttribute('data-blurb') || '') : '';
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

    def do_GET(self):
        try:
            _path_only = urlparse(self.path).path
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
    global _server_instance
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
