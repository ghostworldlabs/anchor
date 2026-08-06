"""Conversation -> commission: the steward actually RUNS a skill (2026-08-06).

WHY THIS MODULE EXISTS. Every seam already existed and none of them were
joined: the chamber could talk (converse), the engine could propose and
hash-confirm a commission (commission-run-bridge), a managed session could be
launched with the skill loaded (commission_executor.launch_commission_in_session),
the run loop could drive it to a decision point (commission_runner), and the
engine could read a finished run back to John and raise the High Seat
(steward-run-ingest via the same bridge). This module is the join, and ONLY
the join:

    propose -> John confirms -> session starts -> run loop drives -> stopped
    -> the run record is written -> the bridge ingests it (report + raise
    + handback) -> John opens THAT session, answers, hands it back
    -> watch re-arms -> produced -> ingested -> reported.

THE LONG-LIVED-PROCESS LAW (learned the hard way): a throwaway process kills
the PTY it starts. Launch + drive must live in ONE long-lived process — this
module runs inside the Anchor service, and the watcher is a daemon thread of
that service.

WHAT IT NEVER DOES: answer a question the skill asked (commission_runner's
law), or derive project state (the engine's ledger owns that; run records
here are the steward's own bookkeeping about runs, nothing more).

Stdlib only. The Node bridge is an external CLI through an injectable seam
(``ANCHOR_ECGBERHT_BRIDGE_CMD``), fully stubbed in tests — same pattern as
``ANCHOR_RUNNER_CMD``.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import paths as _paths
import commission_executor as _ce
import commission_runner as _cr

ANCHOR_DIR = Path(__file__).resolve().parent

#: Durable per-project stores (under the project folder, like .anchor/ elsewhere).
COMMISSION_STORE_REL = os.path.join(".anchor", "commissions")
RUN_RECORDS_REL = os.path.join(".anchor", "commission-runs")

#: The bridge does a real seat call on ingest-run (report read) — be generous.
BRIDGE_TIMEOUT_S = 60
INGEST_TIMEOUT_S = 300

#: How much transcript tail a run record keeps. The session window replays the
#: full PTY; the record only needs enough for a post-mortem read.
TRANSCRIPT_TAIL_CHARS = 4000

RUN_RECORD_SCHEMA = "anchor-commission-run-v0"

#: Production watch bounds. MEASURED (E2E 2026-08-06): Crucible at xhigh
#: effort sat >4 minutes with ZERO TUI repaint mid-think — the runner's 90s
#: default would have classified a hard-working skill as QUIET. A real plan
#: run is tens of minutes, not seconds.
DEFAULT_RUNNER_KWARGS = {
    "poll_seconds": 10,
    "max_seconds": 2700,
    "quiet_seconds": 420,
}

#: The second turn — the one that turns "skill loaded" into "skill working".
#: The brief itself rides the session seed (launch_commission_in_session folds
#: it onto the lane seed), so this stays short and constant.
WORK_TURN = (
    "Begin the commissioned work now — the brief is in your opening context. "
    "Work autonomously and do not wait for further instruction. "
    "FIRST, check whether any decision on this step is genuinely John's alone "
    "(a goal lock, a direction choice, a spend approval): if so, ask that "
    "question plainly and STOP — before doing any deep work that the answer "
    "could invalidate. Otherwise work on; whenever you genuinely need John's "
    "decision, ask it plainly and stop."
)


# ── Bridge (the one door to the Ecgberht engine) ─────────────────────────────

def _ecgberht_root() -> Path:
    """ECGBERHT_ROOT env override, else the sibling checkout beside Anchor."""
    env = os.environ.get("ECGBERHT_ROOT", "").strip()
    if env:
        return Path(env)
    return ANCHOR_DIR.parent / "Ecgberht"


def run_bridge(mode: str, payload: dict, timeout: int = BRIDGE_TIMEOUT_S) -> dict:
    """Spawn the commission-run bridge with ``payload`` on STDIN (never argv —
    transcripts cross the 32,767-char argv cap instantly) and parse its
    one-line JSON reply.

    ``ANCHOR_ECGBERHT_BRIDGE_CMD`` overrides the command for tests (a python
    stub), exactly like ``ANCHOR_RUNNER_CMD`` stubs the model runner.
    """
    override = os.environ.get("ANCHOR_ECGBERHT_BRIDGE_CMD", "").strip()
    if override:
        # posix=False so Windows backslash paths survive (job_runner's carried
        # fix) — but then quoted tokens KEEP their quotes, and subprocess would
        # double-quote them. Strip one layer of surrounding quotes per token.
        cmd = [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t
               for t in shlex.split(override, posix=(os.name != "nt"))] + [mode]
        cwd = str(ANCHOR_DIR)
    else:
        bridge = _ecgberht_root() / "scripts" / "commission-run-bridge.mjs"
        if not bridge.exists():
            return {"ok": False, "error": "ecgberht_engine_missing",
                    "message": "commission-run bridge not found (set ECGBERHT_ROOT "
                               "or keep the Ecgberht checkout beside Anchor)"}
        cmd = ["node", str(bridge), mode]
        cwd = str(_ecgberht_root())
    try:
        res = subprocess.run(
            cmd,
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            cwd=cwd, creationflags=getattr(_paths, "NO_WINDOW", 0))
    except Exception as exc:
        return {"ok": False, "error": "bridge_spawn_failed", "message": str(exc)}
    out = (res.stdout or "").strip()
    if not out:
        return {"ok": False, "error": "bridge_no_output",
                "message": (res.stderr or "").strip()[:500]}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {"ok": False, "error": "bridge_bad_json", "message": out[:500]}


# ── Run records (the steward's own bookkeeping — never project state) ───────

def _run_record_path(folder: str, session_id: str) -> Path:
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_.")
    return Path(folder) / RUN_RECORDS_REL / f"{safe}.json"


def _atomic_write_json(target: Path, obj: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def load_run_record(folder: str, session_id: str) -> Optional[dict]:
    p = _run_record_path(folder, session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_runs(folder: str) -> list:
    """SAFE projections of the project's commission runs, newest-first.
    Never a worktree path, never the transcript body."""
    root = Path(folder) / RUN_RECORDS_REL
    if not root.exists():
        return []
    rows = []
    for p in sorted(root.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append({
            "session_id": rec.get("session_id"),
            "commission_id": rec.get("commission_id"),
            "skill": rec.get("skill"),
            "step_id": rec.get("step_id"),
            "lane": rec.get("lane"),
            "outcome": rec.get("outcome"),
            "ran": rec.get("ran"),
            "elapsed_s": rec.get("elapsed_s"),
            "at": rec.get("at"),
            "watch_count": rec.get("watch_count", 1),
            "report": rec.get("report"),
            "raised": rec.get("raised"),
        })
    rows.sort(key=lambda r: r.get("at") or "", reverse=True)
    return rows


# ── Watcher registry (one watcher per session, ever) ────────────────────────

_WATCHERS: dict = {}
_WATCHERS_LOCK = threading.Lock()


def watcher_active(session_id: str) -> bool:
    with _WATCHERS_LOCK:
        t = _WATCHERS.get(session_id)
        return bool(t and t.is_alive())


def _claim_watcher(session_id: str, thread: threading.Thread) -> bool:
    with _WATCHERS_LOCK:
        existing = _WATCHERS.get(session_id)
        if existing and existing.is_alive():
            return False
        _WATCHERS[session_id] = thread
        return True


# ── Propose ─────────────────────────────────────────────────────────────────

def propose(folder: str, step_id: Optional[str] = None,
            skill: Optional[str] = None, depth: Optional[str] = None,
            who: str = "ecgberht-steward") -> dict:
    """Ask the engine to propose a commission for the step in hand.
    READ-ONLY — the reply carries requires_confirm and the hash John binds."""
    payload = {"project": str(folder), "who": who}
    if step_id:
        payload["step_id"] = step_id
    if skill:
        payload["skill"] = skill
    if depth:
        payload["depth"] = depth
    return run_bridge("propose-active", payload)


# ── Confirm + launch + watch (the join) ─────────────────────────────────────

def confirm_and_launch(
    folder: str,
    proposal: dict,
    *,
    project_id: str,
    who: str = "john",
    backend: str = "claude",
    watch: bool = True,
    start_session_fn: Optional[Callable] = None,
    read_fn: Optional[Callable] = None,
    write_fn: Optional[Callable] = None,
    runner_kwargs: Optional[dict] = None,
    auth_ctx: Optional[dict] = None,
    expected_token: Optional[str] = None,
    enforce_auth: bool = False,
    thread_factory: Optional[Callable] = None,
) -> dict:
    """John said go: hash-confirm through the engine, launch the managed
    session with the skill loaded and the brief seeded, and start the watcher
    that will fetch him when the skill needs him.

    Injectable seams (``start_session_fn`` / ``read_fn`` / ``write_fn`` /
    ``thread_factory``) make this fully testable without a live PTY.
    """
    if not proposal or not isinstance(proposal, dict):
        return {"ok": False, "error": "proposal_required"}

    confirmed = run_bridge("confirm", {
        "project": str(folder),
        "proposal": proposal,
        "who": who,
    })
    if not confirmed.get("ok"):
        return {"ok": False, "error": confirmed.get("error", "confirm_failed"),
                "message": confirmed.get("message"), "confirm": confirmed}

    job = confirmed.get("job") or {}
    skill = job.get("skill") or proposal.get("skill")
    step_id = job.get("step_id") or proposal.get("step_id")
    commission_id = (job.get("commission_id") or job.get("job_id")
                     or proposal.get("proposal_id"))
    lane = _ce.lane_for_commissioned_skill(skill)
    if not lane:
        return {"ok": False, "error": "skill_has_no_session_lane",
                "message": f"'{skill}' has no managed-session lane — it cannot "
                           "run as a commissioned session yet.",
                "skill": skill, "confirm": confirmed}

    brief = build_brief(proposal, skill=skill)

    def _launch(**kwargs):
        return _ce.launch_commission_in_session(
            start_session_fn=start_session_fn, **kwargs)

    store_root = Path(folder) / COMMISSION_STORE_REL
    commission = {
        "confirmed": True,
        "commission_id": commission_id,
        "skill": skill,
        "depth": proposal.get("depth_cell"),
        "step_id": step_id,
        "who": who,
    }
    launched = _ce.execute_confirmed_commission(
        commission,
        store_root=store_root,
        launch_fn=_launch,
        lane=lane,
        backend=backend,
        project_id=project_id,
        folder_path=folder,
        prompt=brief,
        auth_ctx=auth_ctx,
        expected_token=expected_token,
        enforce_auth=enforce_auth,
    )
    if not launched.get("ok", True) and launched.get("error"):
        return {"ok": False, "error": launched.get("error"),
                "message": launched.get("message") or launched.get("user_text"),
                "launch": launched}

    session_id = launched.get("session_id") or launched.get("job_id")
    if not session_id:
        return {"ok": False, "error": "no_session_id", "launch": launched}

    record = {
        "schema": RUN_RECORD_SCHEMA,
        "session_id": session_id,
        "commission_id": commission_id,
        "skill": skill,
        "step_id": step_id,
        "lane": lane,
        "project_id": project_id,
        "outcome": "running",
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "watch_count": 0,
        "worktree_path": launched.get("worktree_path"),
    }
    _atomic_write_json(_run_record_path(folder, session_id), record)

    watching = False
    if watch:
        watching = _start_watcher(
            folder, project_id, record, watch_only=False,
            read_fn=read_fn, write_fn=write_fn,
            runner_kwargs=runner_kwargs, thread_factory=thread_factory)

    return {
        "ok": True,
        "session_id": session_id,
        "commission_id": commission_id,
        "skill": skill,
        "step_id": step_id,
        "lane": lane,
        "watching": watching,
        "say": (f"Commissioned — {skill} is running in a session I manage. "
                "I'll come get you the moment it needs you."),
    }


def build_brief(proposal: dict, skill: Optional[str] = None) -> str:
    """The opening brief, folded onto the lane seed. Everything the engine
    proposal already knows about the step — nothing invented here."""
    step = proposal.get("step") or {}
    lines = [
        f"COMMISSION BRIEF — {skill or proposal.get('skill') or 'skill'} "
        f"for roadmap step '{step.get('name') or proposal.get('step_id') or ''}'.",
    ]
    if step.get("done_when"):
        lines.append(f"The step is done when: {step['done_when']}")
    commission = proposal.get("commission") or {}
    if commission.get("active_effort"):
        lines.append(f"Active effort: {commission['active_effort']}")
    lines.append(
        "Work from the project in this folder. When you genuinely need John's "
        "decision, ask it plainly and stop — do not guess on his behalf.")
    return "\n".join(lines)


# ── The watcher (runs inside the service — the long-lived process) ──────────

def _start_watcher(folder, project_id, record, *, watch_only,
                   read_fn=None, write_fn=None, runner_kwargs=None,
                   thread_factory=None) -> bool:
    session_id = record["session_id"]

    def _run():
        _watch_session(folder, project_id, record,
                       watch_only=watch_only,
                       read_fn=read_fn, write_fn=write_fn,
                       runner_kwargs=runner_kwargs)

    factory = thread_factory or (lambda fn: threading.Thread(
        target=fn, name=f"commission-watch-{session_id}", daemon=True))
    thread = factory(_run)
    if not _claim_watcher(session_id, thread):
        return False
    thread.start()
    return True


def _watch_session(folder, project_id, record, *, watch_only,
                   read_fn=None, write_fn=None, runner_kwargs=None) -> dict:
    """One watch: drive (or resume watching) the session, then bring the run
    home through the bridge. Runs on the watcher thread."""
    session_id = record["session_id"]
    if read_fn is None or write_fn is None:
        import terminal_session as _ts
        read_fn = read_fn or _ts.read_since
        write_fn = write_fn or _ts.input

    kwargs = dict(DEFAULT_RUNNER_KWARGS) if runner_kwargs is None else dict(runner_kwargs)
    result = _cr.run_commissioned_session(
        session_id,
        WORK_TURN,
        read_fn=read_fn,
        write_fn=write_fn,
        watch_only=watch_only,
        **kwargs,
    )
    return finish_run(folder, project_id, record, result)


def finish_run(folder, project_id, record, result) -> dict:
    """The run stopped: persist the record, then hand it to the engine —
    report, conversation log, raise, handback — via the ingest bridge."""
    session_id = record["session_id"]
    transcript = result.get("transcript", "") or ""
    updated = {
        **record,
        "outcome": result.get("outcome"),
        "ran": result.get("ran"),
        "elapsed_s": result.get("elapsed_s"),
        "transcript_chars": result.get("transcript_chars"),
        "transcript_tail": transcript[-TRANSCRIPT_TAIL_CHARS:],
        "watch_count": int(record.get("watch_count", 0)) + 1,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    ingest = run_bridge("ingest-run", {
        "project": str(folder),
        "project_id": project_id,
        "run": {
            "outcome": result.get("outcome"),
            "transcript": transcript,
            "ran": result.get("ran"),
            "elapsed_s": result.get("elapsed_s"),
            "skill": record.get("skill"),
            "step_id": record.get("step_id"),
            "session_id": session_id,
            "commission_id": record.get("commission_id"),
            "worktree": record.get("worktree_path"),
        },
    }, timeout=INGEST_TIMEOUT_S)

    if ingest.get("ok"):
        updated["report"] = ingest.get("report")
        updated["raised"] = ingest.get("raised")
        updated["handback"] = (ingest.get("handback") or {}).get("ingested") \
            if isinstance(ingest.get("handback"), dict) else None
    else:
        # The ingest failing is a fact John gets, not a silent swallow.
        updated["report"] = {
            "say": "The run stopped but I could not read it back "
                   f"({ingest.get('error', 'bridge_failed')}). Open the session to see it.",
        }
        updated["ingest_error"] = ingest.get("error")

    _atomic_write_json(_run_record_path(folder, session_id), updated)
    return {"ok": True, "record": updated, "ingest": ingest}


# ── Hand it back (after John answered in the session) ───────────────────────

def rearm_watch(folder, project_id, session_id, *,
                read_fn=None, write_fn=None, runner_kwargs=None,
                thread_factory=None) -> dict:
    """John answered in the session and handed it back — resume the watch
    WITHOUT sending anything (the cursor snaps past the old question first)."""
    record = load_run_record(folder, session_id)
    if record is None:
        return {"ok": False, "error": "unknown_run",
                "message": "No commission run record for that session."}
    if watcher_active(session_id):
        return {"ok": True, "already_watching": True, "session_id": session_id}
    started = _start_watcher(
        folder, project_id, record, watch_only=True,
        read_fn=read_fn, write_fn=write_fn,
        runner_kwargs=runner_kwargs, thread_factory=thread_factory)
    return {"ok": started, "session_id": session_id, "watching": started,
            "say": "Watching again — carry on; I'll take it from here."}

# NOTE deliberately ABSENT: a panel-close re-arm hook. The panel × is a
# GRACEFUL CLOSE that STOPS the PTY (terminal_session.close_session) — there
# is nothing left to watch after it. Handing a session back to the steward is
# an explicit act on a LIVE session ("Hand it back" → /commission_watch),
# which is also exactly how John described the flow.
