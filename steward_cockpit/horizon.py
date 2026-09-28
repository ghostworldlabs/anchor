"""The after rule — the line under a project re-derived from the plan after every event that changes it (W3 of the
steward revision, 2026-09-28; the synthesis R3; his answer Q1: the line may be rewritten unattended, that line only).

``refresh(record_dir, reason)`` asks the engine to derive and write the horizon (``ecgberht update --horizon
--horizon-reason <reason>``): the focus, then what follows it, stamped with the roadmap's last seq and the focus it was
read from; unchanged since the stamp → the engine writes nothing. The cockpit calls it on the four events — accepted,
produced (a run's handback), answered (a decision), refined (the feedback turn: "after this draft: X, then Y") — and
on a close. ``sweep(dirs)`` is the server tick's half: with no seat awake, every record whose roadmap moved past its
stamp is refreshed once (``reason="tick"``). Best-effort, background, stdlib only; never a step, never a status."""
import json
import subprocess
import threading
from pathlib import Path

import paths as _paths


def _run(record_dir, reason, timeout=25.0):
    try:
        from . import refinement_client as _rc
        deps = _rc._resolve_dependencies(None, None)
        if not isinstance(deps, tuple):
            return deps
        node, cli = deps
        args = [node, cli, "update", "--project", str(record_dir), "--horizon"]
        if reason:
            args += ["--horizon-reason", str(reason)]
        completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout, creationflags=getattr(_paths, "NO_WINDOW", 0))
        out = (completed.stdout or "").strip()
        return json.loads(out.splitlines()[-1]) if out else {"ok": False, "error": "no_output", "message": (completed.stderr or "")[:300]}
    except Exception as exc:
        return {"ok": False, "error": "horizon_failed", "message": str(exc)[:300]}


def refresh(record_dir, reason="", background=True):
    """Re-derive the line for ``record_dir`` after ``reason`` (accepted · produced · answered · refined · closed ·
    stalled · tick). Background by default so no route waits on the engine; returns the engine's JSON when run
    in the foreground. Never raises."""
    if not record_dir or not (Path(str(record_dir)) / "roadmap.json").is_file():
        return {"ok": False, "error": "no_record"}
    if not background:
        return _run(record_dir, reason)
    threading.Thread(target=_run, args=(record_dir, reason), name="horizon-refresh", daemon=True).start()
    return {"ok": True, "queued": True}


def _last_seq(record_dir):
    try:
        rm = json.loads((Path(record_dir) / "roadmap.json").read_text(encoding="utf-8"))
        ev = rm.get("roadmap_events") or []
        return int((ev[-1] or {}).get("seq") or 0) if ev else 0
    except Exception:
        return None


def _stamped_seq(record_dir):
    try:
        st = json.loads((Path(record_dir) / "strip.json").read_text(encoding="utf-8"))
        v = st.get("horizon_source_seq")
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    except Exception:
        return None


def stale(record_dir):
    """True when the roadmap has moved past the line's stamp (or the line was never derived) and a strip exists."""
    last = _last_seq(record_dir)
    if last is None or not (Path(str(record_dir)) / "strip.json").is_file():
        return False
    stamped = _stamped_seq(record_dir)
    return stamped is None or last > stamped


def sweep(dirs, runner=None, limit=8):
    """The tick's half (his Q1): refresh every stale record among ``dirs`` — at most ``limit`` per tick, oldest
    first in the given order — in ONE background thread. Returns the dirs it will refresh. ``runner`` is injected
    by the tests."""
    todo = [str(d) for d in dirs or () if stale(d)][: max(0, int(limit or 0))]
    if not todo:
        return []
    run = runner or (lambda d: _run(d, "tick"))

    def work():
        for d in todo:
            try:
                run(d)
            except Exception:
                pass
    threading.Thread(target=work, name="horizon-sweep", daemon=True).start()
    return todo


def record_dirs(roots):
    """Every steward record under the given project roots: the root when it has a Face, plus one level of efforts
    (the cockpit's own discovery). Never raises."""
    out = []
    try:
        from .steward_campaign import discover_efforts
    except Exception:
        return out
    for root in roots or ():
        try:
            for e in discover_efforts(str(root)) or []:
                rel = str((e or {}).get("rel") or "")
                out.append(str(Path(root) / rel) if rel else str(root))
        except Exception:
            continue
    return out
