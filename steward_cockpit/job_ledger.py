"""The job ledger's nudge (round 5, John 2026-10-13: the steward is in charge of tracking efficiency and the Foundry
tools to build or use). The ledger itself is the Foundry tool `ft.py ledger`, derived from the job records; this
module only decides when the Campaign steward - Anchor's home - is handed it: after 10 more finished jobs, or 7 days
with at least one. It never changes a tier or a setting, and a nudge that cannot be delivered is simply tried again
at the next finish."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

EVERY_JOBS = 10
EVERY_S = 7 * 86400
RULE = ("\n\nYou keep the books (John 2026-10-13). Read the numbers above as prompts to look, not proof. Bring John at "
        "most ONE recommendation, in plain words: a tier or size change, a new Foundry tool, or a landing cause that "
        "keeps recurring - or nothing, if nothing stands out. Never change tiers.json or any setting yourself.")
_LOCK = threading.Lock()


def _base():
    from steward_cockpit import code_jobs
    return code_jobs.jobs_base()


def finished_count():
    """Jobs started so far (the jobs index Anchor appends at every start): the ledger is due as work accumulates,
    whether or not a job reached its timing line."""
    try:
        with open(_base() / "jobs-index.jsonl", "rb") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def _state_path():
    return _base() / "ledger-state.json"


def _read_state():
    try:
        st = json.loads(_state_path().read_text(encoding="utf-8"))
        return st if isinstance(st, dict) else None
    except (OSError, ValueError):
        return None


def _write_state(rows, at):
    p = _state_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"rows": rows, "at": at}), encoding="utf-8")
    tmp.replace(p)


def due(rows, state, now):
    """Is a ledger note due? First sight only starts the count."""
    if state is None:
        return False
    new = rows - int(state.get("rows") or 0)
    return new >= EVERY_JOBS or (new >= 1 and now - float(state.get("at") or 0) >= EVERY_S)


def ledger_text():
    from steward_cockpit import foundry_tools
    ft = foundry_tools.index_path().parent / "ft.py"
    r = subprocess.run([sys.executable, str(ft), "ledger"], capture_output=True, text=True, timeout=30,
                       encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = (r.stdout or "").strip()
    if r.returncode != 0 or not text:
        raise RuntimeError("the ledger tool failed: %s" % ((r.stderr or "")[-200:] or r.returncode))
    return text


def campaign_engine():
    from steward_cockpit import campaign_say, steward_routes
    return steward_routes.get_engine(str(campaign_say.campaign_dir()), create=False)


def _is_campaign(eng):
    try:
        from steward_cockpit import campaign_say
        return Path(str(eng.dir)).resolve() == campaign_say.campaign_dir().resolve()
    except Exception:
        return False


def nudge(now=None, engine=None):
    """Hand the Campaign steward the ledger when it is due. Returns True when a note was accepted. Never raises.
    Called after every job's report and from the Campaign steward's own hourly tick, so a note missed while it slept
    is delivered when it is up again; the count advances only once the note is accepted."""
    try:
        if engine is not None and not _is_campaign(engine):
            return False
        with _LOCK:
            now = time.time() if now is None else now
            rows, state = finished_count(), _read_state()
            if state is None:
                _write_state(rows, now)
                return False
            if not due(rows, state, now):
                return False
            eng = engine if engine is not None else campaign_engine()
            if eng is None or not eng.alive():
                return False                      # asleep: the count stands, the next finish tries again
            text = ledger_text()
            ident = "attention:ledger:%s-%d" % (time.strftime("%Y%m%d", time.localtime(now)), rows)
            res = eng.enqueue_job_result(ident, "THE JOB LEDGER (every %d jobs or 7 days)\n" % EVERY_JOBS + text + RULE)
            if not (isinstance(res, dict) and res.get("ok")):
                return False
            _write_state(rows, now)
            return True
    except Exception:
        return False


def nudge_later(engine=None):
    threading.Thread(target=nudge, kwargs={"engine": engine}, name="job-ledger-nudge", daemon=True).start()
