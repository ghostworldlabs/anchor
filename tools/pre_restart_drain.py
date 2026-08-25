"""Graceful pre-restart drain: park every live PTY WARM (rearch W3).

Pre-designed in W3 as the fallback the ConPTY spike verdict may route W17 to:
if PTYs stay dashboard-owned, then a dashboard restart (``nssm restart
anchor``, a deploy) must cost each live terminal a WARM reconnect — never
dead context. For EVERY live PTY session this drain:

1. **parks** it via :func:`terminal_session.close_session` — the graceful
   close (crucible-improve W6): stops the PTY, KEEPS the registry record
   (re-statused ``STATUS_IDLE``), preserves the worktree, and PERSISTS the
   produced docs into the main project (``capture_session_docs``) so they
   survive the boot orphan-reaper;
2. **seeds the warm resume** — ensures the session's validated summary is
   CACHED (the thing :func:`anchor_gui._build_continue_seed` reads first), by
   generating it synchronously through the runner seam when absent, BOUNDED
   by a daemon-thread timeout (:data:`DRAIN_SUMMARY_TIMEOUT`, module-global →
   test-tunable) so a wedged model call can never block the restart.

The post-restart reopen (click the parked tile → ``continue_session``) then
opens WARM: docs persisted + summary cached. Proven against a stub PTY
session by the W3 gate (``tests/test_rearch_2026_07.py``); wired into the
deploy script by W17 iff the spike verdict is NO.

Best-effort throughout: a failure on one session never blocks draining the
rest, and the drain never raises out of :func:`drain`. Stdlib only.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Per-session cap on the synchronous warm-seed summary generation. Module
#: global (not captured at import) so tests/operators can tune it.
DRAIN_SUMMARY_TIMEOUT = 20.0


def _bootstrap_path():  # pragma: no cover - script-mode import shim
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _live_pty_records(project_id=None):
    """The registry records the drain targets: live-PTY-attached OR RUNNING.

    The union is deliberate: a RUNNING record whose PTY already died still
    deserves the park (close_session is tolerant), and an attached PTY whose
    record drifted still gets stopped.
    """
    import pty_manager
    import session_registry as reg

    attached = set(pty_manager.live_sessions())
    out = []
    for rec in reg.list_sessions(project_id=project_id):
        sid = rec.get("session_id")
        if sid in attached or rec.get("status") == reg.STATUS_RUNNING:
            out.append(rec)
    return out


def _resolve_session_dict(folder, project_id, lane, session_id):
    """The effort-history session dict the summarizer keys on (docs-tied).

    Reuses :func:`anchor_gui._resolve_finished_session` (the v8 no-loss
    resolution that ties the managed session to the docs it PRODUCED) when
    available; falls back to a minimal ``{"session_id": ...}`` record so the
    summarizer can still cache an honest summary.
    """
    try:
        import anchor_gui
        session = anchor_gui._resolve_finished_session(
            folder, project_id, lane, session_id)
        if session is not None:
            return session
    except Exception:
        pass
    return {"session_id": session_id}


def ensure_warm_seed(project_id, lane, session_id, timeout=None) -> str:
    """Ensure the session's summary is CACHED (the warm-resume seed).

    Returns one of:

    * ``"cached"``     — a summary was already cached (idempotent no-op);
    * ``"generated"``  — generated + cached now, through the runner seam;
    * ``"timeout"``    — the bounded generation did not finish in time (the
      restart proceeds; resume falls back to the persisted docs / intent);
    * ``"unavailable"``— the project/folder could not be resolved or the
      generation failed honestly (no cache written — never poisoned).
    """
    import effort_history as eh
    import rnd_registry as rnd
    import summarizer

    if timeout is None:
        timeout = DRAIN_SUMMARY_TIMEOUT
    try:
        proj = rnd.get_project(project_id) if project_id else None
        folder = (proj or {}).get("folder_path", "")
        if not folder:
            return "unavailable"
        store_lane = eh._resolve_subdir(lane)
        if summarizer.load_cached(folder, project_id, store_lane,
                                  session_id) is not None:
            return "cached"
        session = _resolve_session_dict(folder, project_id, lane, session_id)

        # Bounded synchronous generation: a wedged runner can NEVER block the
        # restart (same daemon-thread discipline as switch_engine's digest).
        def _gen():
            try:
                summarizer.summarize_session(folder, project_id, store_lane,
                                             session)
            except Exception:
                pass

        t = threading.Thread(target=_gen, daemon=True)
        t.start()
        t.join(timeout)
        if t.is_alive():
            return "timeout"
        if summarizer.load_cached(folder, project_id, store_lane,
                                  session_id) is not None:
            return "generated"
        return "unavailable"
    except Exception:
        return "unavailable"


def drain(project_id=None, dry_run=False, summary_timeout=None) -> dict:
    """Park every live PTY session warm; returns the drain report.

    ``dry_run=True`` only enumerates what WOULD be drained (no mutation).
    Never raises: per-session failures are recorded in the report and the
    drain proceeds to the next session.
    """
    import terminal_session as ts

    records = _live_pty_records(project_id=project_id)
    drained = []
    for rec in records:
        sid = rec.get("session_id")
        pid = rec.get("project_id")
        lane = rec.get("lane", "")
        entry = {"session_id": sid, "project_id": pid, "lane": lane,
                 "label": rec.get("label", "")}
        if dry_run:
            entry["would_drain"] = True
            drained.append(entry)
            continue
        try:
            closed = ts.close_session(sid, project_id=pid)
            entry["parked"] = bool(closed.get("ok"))
            entry["status"] = closed.get("status")
            docs = closed.get("docs") or {}
            entry["docs_persisted"] = list(docs.get("persisted") or [])
            entry["seed"] = ensure_warm_seed(pid, lane, sid,
                                             timeout=summary_timeout)
        except Exception as e:                      # never blocks the rest
            entry["parked"] = False
            entry["error"] = f"{type(e).__name__}: {e}"
        drained.append(entry)

    # ── Cockpit steward engines (2026-08-25; REWIRED same day after review) ──
    # The cockpit engines are long-lived `claude` processes owned by the RUNNING
    # SERVICE — this drain is a separate process, so an in-process registry read
    # is a structural no-op (first version's defect: it always saw an empty
    # ENGINES and reported [] — indistinguishable from "none live"). The drain
    # now asks THE SERVICE to park its own engines via POST /api/steward/drain-all
    # and reports each failure class BY NAME — never a vacuous empty.
    cockpit = {"mode": "http", "parked": [], "idle": [], "errors": [], "note": None}
    if dry_run:
        cockpit["note"] = "dry-run: service drain-all not called"
    else:
        import json as _json
        import os as _os
        import urllib.request as _rq
        import urllib.error as _er
        url = _os.environ.get("ANCHOR_URL", "http://127.0.0.1:8777") + "/api/steward/drain-all"
        req = _rq.Request(url, data=b"{}", method="POST",
                          headers={"Content-Type": "application/json"})
        tok = _os.environ.get("ANCHOR_TOKEN", "")
        if tok:
            req.add_header("X-Anchor-Token", tok)
        try:
            with _rq.urlopen(req, timeout=30) as resp:
                body = _json.loads(resp.read().decode("utf-8"))
                cockpit.update({k: body.get(k, cockpit[k]) for k in ("parked", "idle", "errors")})
        except _er.HTTPError as e:
            if e.code == 401:
                cockpit["note"] = ("cockpit engines NOT parked: the service requires "
                                   "X-Anchor-Token and ANCHOR_TOKEN is not in this shell's "
                                   "env — export it (or park from the dashboard) before "
                                   "restarting, or steward turns die mid-flight and lean on --resume")
            else:
                cockpit["note"] = f"cockpit drain HTTP {e.code}: engines NOT parked"
        except Exception as e:
            cockpit["note"] = (f"service unreachable ({type(e).__name__}) — nothing to park "
                               f"(service already down) OR wrong ANCHOR_URL")

    return {"ok": True, "dry_run": bool(dry_run), "count": len(drained),
            "drained": drained, "cockpit": cockpit}


def main(argv=None):  # pragma: no cover - thin CLI shim
    import argparse
    import json

    _bootstrap_path()
    ap = argparse.ArgumentParser(
        description="Graceful pre-restart drain: park every live PTY warm "
                    "(close_session park + docs capture + warm-resume seed).")
    ap.add_argument("--project", default=None,
                    help="drain only this project id (default: all)")
    ap.add_argument("--dry-run", action="store_true",
                    help="enumerate what would be drained; mutate nothing")
    ap.add_argument("--timeout", type=float, default=None,
                    help="per-session warm-seed generation cap in seconds "
                         f"(default {DRAIN_SUMMARY_TIMEOUT})")
    args = ap.parse_args(argv)
    report = drain(project_id=args.project, dry_run=args.dry_run,
                   summary_timeout=args.timeout)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
