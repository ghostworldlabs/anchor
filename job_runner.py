#!/usr/bin/env python3
"""Anchor job runner — the keystone of the R&D control surface (Wave 4).

A *job* is a server-owned subprocess that streams stdout line-by-line. In
production a job is a ``claude -p --input-format stream-json --output-format
stream-json`` invocation running the relevant skill (researchPrime / crucible /
foreman) in the project cwd (Master Plan D1). For tests and to keep the Foreman
gate billing-free, the launched command is resolved from the **``ANCHOR_RUNNER_CMD``**
env var, which the test suite points at ``tests/fake_claude.py``.

Responsibilities (frozen design — MASTER-PLAN.md "Job runner (the keystone)" +
Wave 4 acceptance):
- ``launch(lane, ...)`` — spawn the runner subprocess (cwd = project), stream
  stdout to a DURABLE log file *and* an in-memory ring buffer, and record a job
  with ``{job_id, lane, pid, status, log_path}`` (+ extras).
- ``tail(job_id, since)`` — return the captured lines *after* index ``since``
  (long-poll friendly; the HTTP long-poll wrapper lives in :func:`long_poll`).
- ``long_poll(job_id, since, ceiling)`` — block up to ``ceiling`` seconds (the
  production default is 25s, injectable for fast tests) for new lines.
- liveness / startup reconciliation — mark dead-but-"running" jobs ``interrupted``.
- ``cancel(job_id)`` — tree-kill via ``taskkill /T /F /PID <pid>`` (reaps
  grandchildren, spike-proven) → status ``cancelled``; tolerates an
  already-gone process without crashing.

All job-state / JSON mutations run under ``paths.WRITE_LOCK``. Job records are
persisted under ``ANCHOR_DATA_DIR`` (resolved via ``paths`` — never a hard-coded
location). Per-project namespacing happens in Wave 6; here a single jobs store
keyed by ``job_id`` is sufficient.

Stdlib only. No third-party imports.
"""

import json
import os
import shlex
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

import paths as _paths

# ── Constants ──────────────────────────────────────────────────────────────

#: Env var holding the runner command (indirection point). When unset, the
#: production default below is used. Tests set this to the fake runner so live
#: ``claude`` is never invoked.
RUNNER_CMD_ENV = "ANCHOR_RUNNER_CMD"

#: Production default runner (D1). NOT used in the gate — tests override via
#: ANCHOR_RUNNER_CMD. The per-lane skill/prompt seed is layered on in Wave 6.
DEFAULT_RUNNER_CMD = (
    "claude -p --input-format stream-json --output-format stream-json"
)

#: Long-poll ceiling (seconds). Production default per the frozen design; the
#: HTTP layer passes this. Injectable so tests run fast (never actually 25s).
DEFAULT_LONGPOLL_CEILING = 25.0

#: Sub-directory under the data dir that holds job records + durable logs.
JOBS_DIRNAME = "rnd_jobs"

#: In-memory ring buffer cap per job (durable log keeps the full history).
RING_CAPACITY = 5000

# Job statuses.
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"
STATUS_INTERRUPTED = "interrupted"
STATUS_FAILED = "failed"

# ── In-memory live job table ────────────────────────────────────────────────
# Maps job_id -> a _LiveJob holding the Popen, reader thread, and ring buffer.
# Only live (this-process) jobs appear here; persisted records on disk are the
# durable source of truth and survive restarts.
_LIVE = {}
_LIVE_LOCK = threading.RLock()

# Maps job_id -> the jobs directory resolved AT LAUNCH TIME. A job's storage
# location is pinned for its lifetime so a background reader/finalizer thread
# writes to the same place even if ANCHOR_DATA_DIR changes underneath it (which
# also matters in tests, where each test's tmp data dir is torn down while a
# daemon reader may still be finalizing). For jobs that predate this process
# (startup reconciliation), the helpers fall back to the live data dir.
_JOB_DIRS = {}
_JOB_DIRS_LOCK = threading.RLock()


class _LiveJob:
    """Runtime handle for a job owned by *this* server process."""

    __slots__ = ("job_id", "proc", "ring", "reader", "log_path", "lock", "done")

    def __init__(self, job_id, proc, log_path):
        self.job_id = job_id
        self.proc = proc
        self.ring = deque(maxlen=RING_CAPACITY)
        self.reader = None
        self.log_path = log_path
        self.lock = threading.Lock()
        self.done = threading.Event()


# ── Persistence ─────────────────────────────────────────────────────────────

def jobs_dir() -> Path:
    """Directory holding job records + durable logs, under ANCHOR_DATA_DIR."""
    return _paths.data_dir() / JOBS_DIRNAME


def _jobs_dir_for(job_id: str) -> Path:
    """Resolve a specific job's jobs dir, honoring the launch-time pin.

    Pinned at launch so background threads stay consistent; falls back to the
    current data dir for jobs not launched by this process (reconciliation).
    """
    with _JOB_DIRS_LOCK:
        pinned = _JOB_DIRS.get(job_id)
    return pinned if pinned is not None else jobs_dir()


def _record_path(job_id: str) -> Path:
    return _jobs_dir_for(job_id) / f"{job_id}.json"


def log_path_for(job_id: str) -> Path:
    return _jobs_dir_for(job_id) / f"{job_id}.log"


def _ensure_jobs_dir() -> None:
    jobs_dir().mkdir(parents=True, exist_ok=True)


def _write_record(rec: dict) -> None:
    """Persist a job record (atomic-ish) under the write lock."""
    with _paths.WRITE_LOCK:
        p = _record_path(rec["job_id"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)


def load_record(job_id: str):
    """Return the persisted job record dict, or ``None``."""
    p = _record_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_records() -> list:
    """All persisted job records (best-effort; skips unreadable ones)."""
    d = jobs_dir()
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


def _update_record(job_id: str, **fields) -> dict:
    """Read-modify-write a record under the lock. Returns the new record."""
    with _paths.WRITE_LOCK:
        rec = load_record(job_id) or {"job_id": job_id}
        rec.update(fields)
        _write_record(rec)
        return rec


# ── Runner command resolution ────────────────────────────────────────────────

def resolve_runner_cmd(extra_args=None) -> list:
    """Resolve the runner command as an argv list.

    Reads ``ANCHOR_RUNNER_CMD`` (falls back to the production ``claude`` default
    when unset). ``extra_args`` (a list) is appended — used by later waves to
    pass the per-lane skill/prompt seed. Parsed with :func:`shlex.split` using
    POSIX rules so a path like ``python C:/.../fake_claude.py`` survives intact
    on Windows (backslashes are avoided by passing forward-slash paths).
    """
    raw = os.environ.get(RUNNER_CMD_ENV)
    if not (raw and raw.strip()):
        raw = DEFAULT_RUNNER_CMD
    argv = shlex.split(raw, posix=True)
    if extra_args:
        argv = argv + list(extra_args)
    return argv


# ── Launch ───────────────────────────────────────────────────────────────────

def launch(lane: str, cwd=None, extra_args=None, env=None,
           job_id: str = None) -> dict:
    """Launch a server-owned job. Returns the job record.

    The record holds at least ``{job_id, lane, pid, status, log_path}``. stdout
    is streamed by a daemon reader thread into a durable log file *and* an
    in-memory ring buffer. ``cwd`` is the project working directory; ``env`` is
    merged onto the current environment.
    """
    job_id = job_id or uuid.uuid4().hex
    # Pin this job's storage dir for its lifetime (resolved now, once).
    pinned = jobs_dir()
    pinned.mkdir(parents=True, exist_ok=True)
    with _JOB_DIRS_LOCK:
        _JOB_DIRS[job_id] = pinned
    lp = log_path_for(job_id)
    # Truncate/create the durable log up front so tail() always has a target.
    lp.write_text("", encoding="utf-8")

    argv = resolve_runner_cmd(extra_args)

    full_env = dict(os.environ)
    if env:
        full_env.update(env)

    # On Windows, create a new process group so the whole tree is reapable and
    # signals/kills target the group. taskkill /T handles tree reap regardless,
    # but the flag keeps the child detached from our console.
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=full_env,
        bufsize=1,
        text=True,
        creationflags=creationflags,
    )

    live = _LiveJob(job_id, proc, lp)
    with _LIVE_LOCK:
        _LIVE[job_id] = live

    rec = {
        "job_id": job_id,
        "lane": lane,
        "pid": proc.pid,
        "status": STATUS_RUNNING,
        "log_path": str(lp),
        "cwd": str(cwd) if cwd else None,
        "started_at": time.time(),
        "exit_code": None,
        "session_id": None,
    }
    _write_record(rec)

    live.reader = threading.Thread(
        target=_reader_loop, args=(live,), name=f"job-reader-{job_id}",
        daemon=True,
    )
    live.reader.start()
    return rec


def _reader_loop(live: _LiveJob) -> None:
    """Drain the subprocess stdout into the ring buffer + durable log."""
    proc = live.proc
    try:
        with open(live.log_path, "a", encoding="utf-8") as logf:
            for line in proc.stdout:
                line = line.rstrip("\n")
                with live.lock:
                    live.ring.append(line)
                logf.write(line + "\n")
                logf.flush()
    except (ValueError, OSError):
        # Pipe closed underneath us (e.g. process tree-killed mid-read). Not
        # fatal — finalization below records the terminal status.
        pass
    finally:
        try:
            proc.stdout.close()
        except Exception:
            pass
        code = proc.wait()
        # Finalize the persisted record BEFORE signaling done, so a waiter that
        # unblocks on `done` always observes the terminal status.
        _finalize(live.job_id, code)
        live.done.set()


def _finalize(job_id: str, exit_code) -> None:
    """Record the terminal status once the process exits.

    Cancellation may have already set the status to ``cancelled``; do not
    clobber a terminal status that was set deliberately.
    """
    with _paths.WRITE_LOCK:
        rec = load_record(job_id)
        if rec is None:
            return
        if rec.get("status") in (STATUS_CANCELLED, STATUS_INTERRUPTED):
            # Terminal status already chosen (cancel / reconciliation). Keep it,
            # just stamp the exit code + finish time.
            rec["exit_code"] = exit_code
            rec.setdefault("finished_at", time.time())
            _write_record(rec)
            return
        rec["exit_code"] = exit_code
        rec["finished_at"] = time.time()
        rec["status"] = STATUS_DONE if exit_code == 0 else STATUS_FAILED
        _write_record(rec)


# ── Tail / long-poll ─────────────────────────────────────────────────────────

def _lines_from_log(job_id: str) -> list:
    """Read the full durable log as a list of lines (no trailing newline)."""
    lp = log_path_for(job_id)
    if not lp.exists():
        return []
    try:
        text = lp.read_text(encoding="utf-8")
    except OSError:
        return []
    if text == "":
        return []
    lines = text.split("\n")
    # A trailing newline yields a final empty element — drop it.
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def all_lines(job_id: str) -> list:
    """Return every captured line for a job (live ring if present, else log)."""
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None:
        with live.lock:
            # The ring is capped; if it has been truncated, fall back to the
            # durable log which holds full history.
            if len(live.ring) >= live.ring.maxlen:
                return _lines_from_log(job_id)
            return list(live.ring)
    return _lines_from_log(job_id)


def tail(job_id: str, since: int = 0) -> dict:
    """Return captured lines *after* index ``since``.

    Returns ``{lines, next, total, status}`` where ``next`` is the index a
    client should pass as ``since`` on its next poll, ``total`` is the current
    line count, and ``status`` is the job's current status.
    """
    lines = all_lines(job_id)
    total = len(lines)
    start = max(0, int(since))
    new = lines[start:] if start < total else []
    rec = load_record(job_id) or {}
    return {
        "lines": new,
        "next": total,
        "total": total,
        "status": rec.get("status"),
    }


def long_poll(job_id: str, since: int = 0,
              ceiling: float = DEFAULT_LONGPOLL_CEILING,
              poll_interval: float = 0.05) -> dict:
    """Block up to ``ceiling`` seconds for lines after ``since``.

    Returns immediately if new lines already exist; otherwise polls every
    ``poll_interval`` seconds until new lines appear, the job ends, or the
    ceiling elapses. ``ceiling`` is injectable so tests need not wait 25s; the
    production default (:data:`DEFAULT_LONGPOLL_CEILING`) is unchanged.
    """
    deadline = time.monotonic() + max(0.0, float(ceiling))
    while True:
        out = tail(job_id, since)
        if out["lines"]:
            return out
        # If the job is finished and there is nothing new, return (empty) so the
        # client learns the terminal status rather than spinning.
        if out["status"] in (STATUS_DONE, STATUS_CANCELLED,
                              STATUS_INTERRUPTED, STATUS_FAILED):
            return out
        if time.monotonic() >= deadline:
            return out
        time.sleep(poll_interval)


# ── Liveness / reconciliation ────────────────────────────────────────────────

def _pid_alive(pid) -> bool:
    """Best-effort: is a PID currently a live process? Stdlib only."""
    if not pid:
        return False
    if os.name == "nt":
        # tasklist filtered by PID; if the PID appears, it's alive.
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
        return str(int(pid)) in (out.stdout or "")
    # POSIX
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def liveness_check(job_id: str) -> dict:
    """Reconcile one job's status against reality.

    If a record says ``running`` but its process is gone (and it isn't a live
    job still being drained in *this* process), mark it ``interrupted``.
    Returns the (possibly updated) record.
    """
    rec = load_record(job_id)
    if rec is None:
        return None
    if rec.get("status") != STATUS_RUNNING:
        return rec
    # A job still draining in this very process is genuinely live even if the
    # PID check races; trust the live table + its done flag.
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None and not live.done.is_set():
        if _pid_alive(rec.get("pid")):
            return rec
        # Process died but reader hasn't finalized yet — let _finalize handle it
        # unless the pid is truly gone; mark interrupted to be safe.
    if _pid_alive(rec.get("pid")):
        return rec
    return _update_record(job_id, status=STATUS_INTERRUPTED,
                          finished_at=time.time())


def reconcile_on_startup() -> list:
    """Mark every dead-but-"running" persisted job ``interrupted``.

    Called at server startup: any job recorded ``running`` whose process is no
    longer alive (e.g. the server was restarted out from under it) is honestly
    reported as ``interrupted`` (C9 — restart-from-checkpoint, not transparent
    resume). Returns the list of reconciled job_ids.
    """
    changed = []
    for rec in list_records():
        if rec.get("status") != STATUS_RUNNING:
            continue
        jid = rec.get("job_id")
        with _LIVE_LOCK:
            live = _LIVE.get(jid)
        if live is not None and not live.done.is_set():
            # Owned by this live process and still draining — leave it.
            continue
        if not _pid_alive(rec.get("pid")):
            _update_record(jid, status=STATUS_INTERRUPTED,
                           finished_at=time.time())
            changed.append(jid)
    return changed


# ── Cancel (tree-kill) ───────────────────────────────────────────────────────

def cancel(job_id: str) -> dict:
    """Tree-kill a job and mark it ``cancelled``.

    Uses ``taskkill /T /F /PID <pid>`` on Windows to reap the full process tree
    (children + grandchildren — spike-proven). On POSIX, falls back to killing
    the process group. An already-gone process is tolerated (no crash). The
    status is set to ``cancelled`` regardless, so an external cancel is honestly
    recorded even if the process raced to exit first.

    Returns the updated record (or ``None`` if the job is unknown).
    """
    rec = load_record(job_id)
    if rec is None:
        return None

    pid = rec.get("pid")
    # Set the terminal status FIRST so the reader's _finalize() does not clobber
    # it with done/failed when the pipe closes after the kill.
    _update_record(job_id, status=STATUS_CANCELLED)

    if pid:
        _tree_kill(pid)

    # Give the reader thread a moment to drain + finalize the exit code.
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None:
        live.done.wait(timeout=10)

    return load_record(job_id)


def _tree_kill(pid) -> None:
    """Kill a process tree by PID, tolerating an already-dead process."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            # Process already gone / taskkill unavailable — not fatal.
            pass
        return
    # POSIX best-effort: kill the process group, then the pid.
    try:
        os.killpg(os.getpgid(pid), 9)
    except (OSError, ProcessLookupError):
        try:
            os.kill(pid, 9)
        except (OSError, ProcessLookupError):
            pass


# ── Test/maintenance helpers ─────────────────────────────────────────────────

def wait(job_id: str, timeout: float = 30.0) -> dict:
    """Block until the job's reader thread finishes (or timeout). Test helper."""
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None:
        live.done.wait(timeout=timeout)
    return load_record(job_id)


def _reset_live_table_for_tests() -> None:
    """Drop the in-memory live table (used between tests). Does not kill procs."""
    with _LIVE_LOCK:
        _LIVE.clear()
