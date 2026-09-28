"""Presence — where John is, and the leave receipt when he switches (W0 of the steward revision, 2026-09-28).

One small durable fact under ``.anchor/``: ``presence.json`` = ``{"project_id": ..., "at": <epoch>}`` — the project he
opened last (a cockpit page or a card on the High Seat). ``note_open(pid)`` records the new one and returns the
PREVIOUS project id when it differs — the explicit switch. The caller (anchor_gui) then asks the engine to append a
``leave`` receipt to the previous project's record (``ecgberht update --leave --leave-at <iso>``) in the background,
best-effort: the receipt is his own act recorded, never a step, never a status. The cockpit engine's quiet transition
is the fallback, not the trigger (ChatGPT's critique, 2026-09-27: engine inactivity is not his leaving).

Stdlib only; the engine call is injected (``leave_fn``) so this module is testable without Node.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paths as _paths

PRESENCE_NAME = "presence.json"


def _presence_path() -> Path:
    return _paths.data_dir() / ".anchor" / PRESENCE_NAME


def read_presence() -> dict:
    """The last-opened project ``{"project_id": str, "at": float}`` or ``{}``; never raises."""
    try:
        d = json.loads(_presence_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def note_open(project_id, now=None, folder=""):
    """Record that he opened ``project_id`` now (``folder`` = its record folder, for the sleep fallback). Returns
    ``(previous_project_id, previous_at)`` when this is a switch from a DIFFERENT project, else ``(None, None)``.
    Atomic write under the shared lock; never raises."""
    pid = str(project_id or "").strip()
    if not pid:
        return (None, None)
    now = float(now if now is not None else time.time())
    try:
        with _paths.WRITE_LOCK:
            prev = read_presence()
            p = _presence_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps({"project_id": pid, "at": now, "folder": str(folder or "")}), encoding="utf-8")
            os.replace(str(tmp), str(p))
    except Exception:
        return (None, None)
    prev_pid = str(prev.get("project_id") or "").strip()
    if prev_pid and prev_pid != pid:
        try:
            prev_at = float(prev.get("at"))
        except (TypeError, ValueError):
            prev_at = now
        return (prev_pid, prev_at)
    return (None, None)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def on_open(project_id, leave_fn, now=None, background=True, folder=""):
    """The one call the routes make: note the open; on a switch, run ``leave_fn(previous_pid, left_at_iso)`` —
    in a daemon thread by default so a page never waits on the engine. Returns the previous pid or None."""
    prev, prev_at = note_open(project_id, now=now, folder=folder)
    if not prev or leave_fn is None:
        return prev
    left_at = iso(now if now is not None else time.time())

    def run():
        try:
            leave_fn(prev, left_at)
        except Exception:
            pass
    if background:
        threading.Thread(target=run, name="presence-leave", daemon=True).start()
    else:
        run()
    return prev


def _same_folder(a, b) -> bool:
    try:
        return os.path.normcase(os.path.normpath(str(a or ""))) == os.path.normcase(os.path.normpath(str(b or "")))
    except Exception:
        return False


def leave_if_still_here(folder, leave_fn, now=None):
    """The FALLBACK (the cockpit engine going quiet): when presence still says he is on this project's folder —
    he never switched — record the leave now. Returns True when a leave was recorded. Never raises."""
    cur = read_presence()
    if not cur or not _same_folder(cur.get("folder"), folder):
        return False
    try:
        leave_fn(str(cur.get("project_id") or ""), iso(now if now is not None else time.time()))
        return True
    except Exception:
        return False


def run_leave(record_dir, left_at_iso, timeout=20.0):
    """Append the leave receipt to the record at ``record_dir`` through the engine CLI
    (``ecgberht update --project <dir> --leave --leave-at <iso>``). Returns the engine's JSON or a failure dict;
    never raises. The CLI and node are resolved the way the refinement client resolves them."""
    import subprocess
    try:
        from . import refinement_client as _rc
        deps = _rc._resolve_dependencies(None, None)
        if not isinstance(deps, tuple):
            return deps
        node, cli = deps
        completed = subprocess.run(
            [node, cli, "update", "--project", str(record_dir), "--leave", "--leave-at", str(left_at_iso)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=getattr(_paths, "NO_WINDOW", 0))
        out = (completed.stdout or "").strip()
        return json.loads(out.splitlines()[-1]) if out else {"ok": False, "error": "no_output", "message": (completed.stderr or "")[:300]}
    except Exception as exc:
        return {"ok": False, "error": "leave_failed", "message": str(exc)[:300]}
