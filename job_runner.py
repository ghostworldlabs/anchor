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

#: Production default runner (D1) — the *base* claude command shape. NOT used in
#: the gate (tests override via ANCHOR_RUNNER_CMD). This base is what
#: ``resolve_runner_cmd`` returns when no per-launch prompt is supplied (e.g. the
#: engine-selector tests that only inspect the command shape). For a real launch
#: the per-lane argv is built by ``build_backend_argv`` below, which appends the
#: prompt + output-dir + permission flags appropriate to the lane (research is
#: non-gated and takes the prompt on argv; plan/build are gated and take the
#: prompt as a stream-json user message on stdin).
DEFAULT_RUNNER_CMD = "claude -p --output-format stream-json"

#: Engine backends. Claude is the default and runs on all lanes; Gemini is a
#: portable read-only engine offered ONLY for the research lane (policy enforced
#: in ``lanes.launch_lane``). The runner command for each is resolved by
#: :func:`resolve_runner_cmd`. ``ANCHOR_RUNNER_CMD`` (the test indirection point)
#: ALWAYS wins, regardless of backend, so the mock runner drives every test.
BACKEND_CLAUDE = "claude"
BACKEND_GEMINI = "gemini"
DEFAULT_BACKEND = BACKEND_CLAUDE

#: Env var overriding the Gemini runner command. When unset,
#: :data:`DEFAULT_GEMINI_CMD` is used. Spike finding (2026-06-09): ``gemini -p``
#: runs headless and authenticates as the service user, BUT it refuses agentic
#: work in a project folder unless ``--skip-trust`` is passed — it treats
#: untrusted dirs as read-only and overrides the approval mode. Since jobs run
#: INSIDE the project folder, ``--skip-trust`` is required. ``--output-format
#: stream-json`` is supported. ``--approval-mode plan`` is read-only (research is
#: non-mutating). The prompt/seed is appended by the lane wiring via
#: ``extra_args`` exactly as for claude; the gemini CLI tolerates/parses the
#: trailing seed. Override the whole command via this env var if needed.
#: Spike finding (2026-06-09, verified live): the previous default passed
#: ``--approval-mode plan``, which is READ-ONLY — a research lane MUST write its
#: report into the output dir, so ``plan`` blocks it. The minimal write-capable
#: mode is ``auto_edit`` (auto-approves file edits; gemini is research-only here
#: and never needs to run shell commands, so ``yolo`` would be over-broad). Also
#: note the real gemini flag is ``-p/--prompt`` whose VALUE is the prompt (NOT a
#: bare ``-p`` consuming the prompt from stdin) and ``--include-directories``
#: (NOT ``--output-dir``) grants access to the output dir — both are appended by
#: ``build_backend_argv`` for a real launch. This base constant is the command
#: SHAPE returned when no per-launch prompt is supplied.
GEMINI_CMD_ENV = "ANCHOR_GEMINI_CMD"
DEFAULT_GEMINI_CMD = (
    "gemini --skip-trust -p --output-format stream-json --approval-mode auto_edit"
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

#: The set of runner statuses that mean the job's process lifecycle is over.
#: A terminal job cannot accept a continuation turn (its session is gone).
TERMINAL_STATUSES = frozenset(
    (STATUS_DONE, STATUS_CANCELLED, STATUS_INTERRUPTED, STATUS_FAILED)
)

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

# ── Concurrency policy registries (Wave 6) ──────────────────────────────────
# All concurrency/lock state lives under ``paths.WRITE_LOCK`` (acquired by the
# helpers below), per the frozen design. These are *in-process* tables — a
# server owns its subprocess jobs, so a single ThreadingHTTPServer's policy is
# enforced here; durable records on disk remain the cross-restart source of
# truth.
#
# _ACTIVE_LANE maps (project_id, lane) -> job_id for the currently-running job
# in that project lane. It enforces WITHIN-a-project same-lane serialization
# (cross-lane stays concurrent because the key includes the lane).
_ACTIVE_LANE = {}
# _FOLDER_BUILD maps folder_path -> job_id for the build currently holding that
# folder's build lock. It enforces ACROSS-projects-sharing-a-folder build
# serialization: at most one build per folder at a time. research/plan are NOT
# folder-locked, so they never appear here and never block.
_FOLDER_BUILD = {}

#: The lane that mutates the shared working tree and is therefore serialized at
#: the FOLDER level (the trio forbids parallel coders in one tree).
BUILD_LANE = "build"

#: Refusal reasons surfaced when a launch is blocked by the concurrency policy.
REFUSED_SAME_LANE = "same-lane-busy"
REFUSED_FOLDER_BUILD = "folder-build-lock"


class LaneBusyError(RuntimeError):
    """Raised when a launch is refused by the concurrency policy.

    Carries a machine-readable ``reason`` (one of :data:`REFUSED_SAME_LANE` /
    :data:`REFUSED_FOLDER_BUILD`) and ``holder`` (the job_id already holding the
    contended slot) so the caller / UI can render the right indicator (e.g. the
    folder-build-lock badge).
    """

    def __init__(self, reason, holder=None, message=None):
        self.reason = reason
        self.holder = holder
        super().__init__(message or f"{reason} (held by {holder})")


class _LiveJob:
    """Runtime handle for a job owned by *this* server process."""

    __slots__ = ("job_id", "proc", "ring", "reader", "log_path", "lock", "done",
                 "gated")

    def __init__(self, job_id, proc, log_path, gated=False):
        self.job_id = job_id
        self.proc = proc
        self.ring = deque(maxlen=RING_CAPACITY)
        self.reader = None
        self.log_path = log_path
        self.lock = threading.Lock()
        self.done = threading.Event()
        # Truthy ("plan"/"build") for a gated lane: the reader loop feeds each
        # stdout line to the gate adapter so an AskUserQuestion frame surfaces as
        # awaiting-input state in production (NOT just in hand-injected tests).
        self.gated = gated


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

def _shlex_split(raw: str) -> list:
    """Split a command string into argv, surviving Windows backslash paths.

    Carried-bug fix: ``shlex.split(posix=True)`` eats backslashes, corrupting an
    explicitly-set ``ANCHOR_RUNNER_CMD`` like ``python C:\\dev\\...\\fake.py`` on
    Windows. Use ``posix=False`` on Windows so backslashes survive; POSIX rules
    elsewhere. (The prod defaults use forward-slash-free bare binaries, so this
    only matters for an explicit override.)
    """
    return shlex.split(raw, posix=(os.name != "nt"))


def _build_claude_argv(prompt, output_dir, gated) -> list:
    """Build a VALID ``claude`` argv for a real (override-unset) launch.

    Verified-real claude flags only (claude --help): ``-p`` (print/headless),
    ``--output-format stream-json``, ``--add-dir <dir>`` (grant tool access to
    the output dir so the skill can WRITE its report there), and
    ``--permission-mode <mode>``.

    - RESEARCH (non-gated): the natural-language seed IS the prompt and is passed
      as a trailing argv value. ``acceptEdits`` is the MINIMAL mode that lets the
      skill write files into the output dir (``plan`` is read-only and would
      block the report; ``bypassPermissions`` is broader than research needs).
    - PLAN/BUILD (gated): ``--input-format stream-json`` is added, which makes
      claude consume the prompt as a stream-json user message from STDIN (NOT
      argv) — so the prompt is delivered by :func:`launch` on the stdin pipe, not
      here. build mutates the tree and may run Bash → ``bypassPermissions``; plan
      is non-mutating but writes docs → ``acceptEdits``.

    There is intentionally NO ``--skill`` / ``--output-dir`` / ``--prompt-seed``
    (none are real flags — that was the bug). Skills are auto-discovered and
    invoked via the natural-language seed.
    """
    # Live-smoke finding (2026-06-10): real ``claude -p --output-format
    # stream-json`` REQUIRES ``--verbose`` ("--output-format=stream-json requires
    # --verbose") — without it claude refuses to start. (Not in the mock path.)
    argv = ["claude", "-p", "--verbose", "--output-format", "stream-json"]
    if output_dir:
        argv += ["--add-dir", str(output_dir)]
    if gated:
        # Gated lanes consume the initial prompt from stdin as a stream-json user
        # message (delivered by launch()); build may mutate the tree + run Bash.
        argv += ["--input-format", "stream-json"]
        argv += ["--permission-mode", "bypassPermissions" if gated == "build"
                 else "acceptEdits"]
        # Prompt is NOT placed on argv for gated lanes — it arrives on stdin.
    else:
        # Research: minimal write-capable mode; the seed is the prompt on argv.
        argv += ["--permission-mode", "acceptEdits"]
        if prompt:
            argv.append(prompt)
    return argv


def _build_gemini_argv(prompt, output_dir, gated) -> list:
    """Build a VALID ``gemini`` argv for a real (override-unset) launch.

    Verified-real gemini flags only (gemini --help): ``--skip-trust`` (REQUIRED —
    untrusted folders are forced read-only otherwise, and jobs run inside the
    project folder), ``-p/--prompt <value>`` (the prompt is the VALUE),
    ``--output-format stream-json``, ``--approval-mode {…}`` (``auto_edit`` lets
    the skill write its report; ``plan`` is read-only and would block it), and
    ``--include-directories <dir>`` (NOT ``--output-dir``) to grant access to the
    output dir.

    Gemini is research-only (non-gated) per policy, so there is no gated branch.
    """
    argv = ["gemini", "--skip-trust", "-p"]
    if prompt:
        argv.append(prompt)
    argv += ["--output-format", "stream-json", "--approval-mode", "auto_edit"]
    if output_dir:
        argv += ["--include-directories", str(output_dir)]
    return argv


def build_backend_argv(backend, prompt, output_dir, gated) -> list:
    """Build the VALID production argv for a backend + lane shape.

    Used only on the override-UNSET (real-CLI) path. Dispatches to the
    per-backend builder. ``gated`` is falsy for research, ``"plan"``/``"build"``
    (truthy) for the gated lanes (claude only — gemini is research-only).
    """
    if backend == BACKEND_GEMINI:
        return _build_gemini_argv(prompt, output_dir, gated)
    return _build_claude_argv(prompt, output_dir, gated)


def resolve_runner_cmd(extra_args=None, backend=DEFAULT_BACKEND,
                       prompt=None, output_dir=None, gated=False) -> list:
    """Resolve the runner command as an argv list, honoring the engine backend.

    Resolution order (CRITICAL — the test indirection must always win):
    1. ``ANCHOR_RUNNER_CMD`` set → use it **for any backend** (this is how the
       whole test suite drives the mock ``tests/fake_claude.py`` regardless of
       which engine a launch selected). The base mock command is used as-is; if a
       ``prompt`` is supplied it is appended as a trailing arg the mock tolerates
       via ``parse_known_args`` (so tests still drive the mock and the prompt
       never leaks into a real CLI). ``extra_args`` (test flags like ``--lines``)
       are appended last. Never broken by the per-backend builders.
    2. else (override unset → a REAL launch): build a VALID per-backend, per-lane
       argv via :func:`build_backend_argv` — but only when a ``prompt`` is
       supplied (a real lane launch always supplies one). When no ``prompt`` is
       supplied (e.g. an engine-selector test inspecting only the command SHAPE),
       fall back to the per-backend default command constant so its shape is
       observable. ``extra_args`` are appended in both sub-cases.

    Rationale for the shape: the dead flags ``--skill``/``--output-dir``/
    ``--prompt-seed`` are GONE (they are not real CLI flags — that was the bug).
    A research lane delivers its natural-language seed as the prompt; a gated
    lane delivers it on stdin (see :func:`build_backend_argv`).
    """
    override = os.environ.get(RUNNER_CMD_ENV)
    if override and override.strip():
        # Test indirection: the mock runner drives every test. Use the override
        # base verbatim; append the prompt (mock ignores it) so the gated/stdin
        # path is exercised without a real CLI, then the test's extra_args.
        argv = _shlex_split(override)
        if prompt is not None:
            argv = argv + [prompt]
    elif prompt is not None:
        # Real launch: construct a valid per-backend argv from scratch.
        argv = build_backend_argv(backend, prompt, output_dir, gated)
    else:
        # Shape-only resolution (no prompt): return the per-backend default base.
        if backend == BACKEND_GEMINI:
            gem = os.environ.get(GEMINI_CMD_ENV)
            raw = gem if (gem and gem.strip()) else DEFAULT_GEMINI_CMD
        else:
            raw = DEFAULT_RUNNER_CMD
        argv = _shlex_split(raw)
    if extra_args:
        argv = argv + list(extra_args)
    return argv


# ── Launch ───────────────────────────────────────────────────────────────────

def _stream_json_user_turn(text: str) -> str:
    """Render an initial prompt as a stream-json user message (for stdin).

    A gated lane (claude ``--input-format stream-json``) consumes its INITIAL
    prompt as a stream-json user message on stdin (the prompt is NOT on argv).
    This is the same envelope shape ``gate_adapter._format_turn`` writes for a
    continuation answer, so the session reads them uniformly.
    """
    envelope = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }
    return json.dumps(envelope, ensure_ascii=False) + "\n"


def launch(lane: str, cwd=None, extra_args=None, env=None,
           job_id: str = None, backend=DEFAULT_BACKEND,
           prompt=None, output_dir=None, gated=False) -> dict:
    """Launch a server-owned job. Returns the job record.

    The record holds at least ``{job_id, lane, pid, status, log_path, backend}``.
    stdout is streamed by a daemon reader thread into a durable log file *and* an
    in-memory ring buffer. ``cwd`` is the project working directory; ``env`` is
    merged onto the current environment. ``backend`` ∈ {"claude","gemini"}
    selects the engine command (resolved by :func:`resolve_runner_cmd`); it is
    recorded on the job so the UI/history can show which engine ran the effort.
    ``ANCHOR_RUNNER_CMD``, when set, still overrides the command for any backend.

    ``prompt`` (the natural-language lane seed), ``output_dir`` (project-scoped),
    and ``gated`` (falsy for research; ``"plan"``/``"build"`` for the gated lanes)
    are threaded into :func:`resolve_runner_cmd` so a real launch builds a VALID
    per-backend argv.

    Stdin handling (D / SETUP §5):
    - NON-GATED (research) **or** no prompt: ``stdin=DEVNULL`` (unchanged Wave-4
      contract — the prompt, if any, is on argv).
    - GATED (plan/build, claude only): ``stdin=PIPE`` kept OPEN for the job's
      lifetime, and the INITIAL prompt is written as a stream-json user message
      (claude's ``--input-format stream-json`` consumes the prompt from stdin,
      not argv). The live process stdin is registered with the gate adapter so an
      answer can be written into the SAME pipe. NOTE: in the test path
      (``ANCHOR_RUNNER_CMD`` set → the mock), the mock reads no stdin, so we still
      open the pipe but the mock simply ignores it; gate tests register their own
      fake sink. This plain-text-after-auto-dismiss gate path is inherently
      FRAGILE (SETUP §4 residual risk): AskUserQuestion can't be answered via a
      tool_result, so the model re-asks in plain text and we answer with a
      stream-json user TEXT turn — best-effort continuation, not guaranteed.
    """
    backend = backend or DEFAULT_BACKEND
    job_id = job_id or uuid.uuid4().hex
    # Pin this job's storage dir for its lifetime (resolved now, once).
    pinned = jobs_dir()
    pinned.mkdir(parents=True, exist_ok=True)
    with _JOB_DIRS_LOCK:
        _JOB_DIRS[job_id] = pinned
    lp = log_path_for(job_id)
    # Truncate/create the durable log up front so tail() always has a target.
    lp.write_text("", encoding="utf-8")

    argv = resolve_runner_cmd(extra_args, backend=backend, prompt=prompt,
                              output_dir=output_dir, gated=gated)

    full_env = dict(os.environ)
    if env:
        full_env.update(env)

    # On Windows, create a new process group so the whole tree is reapable and
    # signals/kills target the group. taskkill /T handles tree reap regardless,
    # but the flag keeps the child detached from our console.
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    # Gated lanes need a kept-open stdin PIPE so the initial prompt + the gate
    # answer can be written into the live session. Non-gated lanes keep the
    # original DEVNULL contract.
    use_stdin_pipe = bool(gated)
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=(subprocess.PIPE if use_stdin_pipe else subprocess.DEVNULL),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=full_env,
        bufsize=1,
        text=True,
        # The runner emits UTF-8 (claude -p stream-json, em-dashes / smart quotes /
        # ☢ etc.). Without an explicit encoding, text mode uses the Windows locale
        # (cp1252) and mojibakes every non-ASCII char at capture time. Decode UTF-8
        # (replace any stray byte rather than crash the reader thread).
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )

    live = _LiveJob(job_id, proc, lp, gated=gated)
    with _LIVE_LOCK:
        _LIVE[job_id] = live

    # For a gated lane, deliver the initial prompt as a stream-json user turn on
    # stdin and register the (kept-open) pipe with the gate adapter so a later
    # answer writes into the SAME session. Deferred import avoids a cycle.
    if use_stdin_pipe and proc.stdin is not None:
        try:
            if prompt:
                proc.stdin.write(_stream_json_user_turn(prompt))
                proc.stdin.flush()
            import gate_adapter as _ga
            _ga.register_stdin_sink(job_id, proc.stdin)
        except (OSError, ValueError, ImportError):
            # A dead/closed pipe (e.g. the mock exited instantly) is non-fatal —
            # the reader thread + finalize still record the terminal status.
            pass

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
        "backend": backend,
    }
    _write_record(rec)

    live.reader = threading.Thread(
        target=_reader_loop, args=(live,), name=f"job-reader-{job_id}",
        daemon=True,
    )
    live.reader.start()
    return rec


def _reader_loop(live: _LiveJob) -> None:
    """Drain the subprocess stdout into the ring buffer + durable log.

    While draining, sniff each line for a stream-json ``result`` envelope and
    capture its cost/usage/duration onto the job record (Wave 7) so the effort
    history can roll cost up per-lane / per-project. The last ``result`` line
    wins (a session emits one terminal result envelope).

    BLOCKER FIX (gated lanes): for a GATED lane (``live.gated`` truthy) we also
    feed each line to ``gate_adapter.parse_event``; the FIRST ``AskUserQuestion``
    frame is persisted via ``gate_adapter.mark_awaiting_input`` so the job's gate
    ``state`` flips to ``awaiting-input`` and ``pending_prompt`` is stored. This
    is the ONLY production path that surfaces a gate from the live stream — before
    this, the reader merely logged the frame as a plain line and the prompt box
    (which renders solely on a non-null ``load_pending_prompt``) never appeared,
    so gated lanes were end-to-end dead. We gate this on ``live.gated`` so a
    research lane (non-gated) never acquires spurious gate state. The deferred
    import avoids a module import cycle (gate_adapter imports job_runner). We only
    mark the FIRST gate (``gate_marked``) — re-asks land in the log; the existing
    answer/continuation path advances ``state`` off awaiting-input.
    """
    proc = live.proc
    result_envelope = None
    gate_marked = False
    _ga = None
    if live.gated:
        try:
            import gate_adapter as _ga
        except ImportError:
            _ga = None
    try:
        with open(live.log_path, "a", encoding="utf-8") as logf:
            for line in proc.stdout:
                line = line.rstrip("\n")
                with live.lock:
                    live.ring.append(line)
                logf.write(line + "\n")
                logf.flush()
                env = _parse_result_envelope(line)
                if env is not None:
                    result_envelope = env
                # Gated lanes: surface the first AskUserQuestion gate from the
                # live stream into awaiting-input state (production wiring).
                if _ga is not None and not gate_marked:
                    try:
                        prompts = _ga.parse_event(line)
                    except Exception:
                        prompts = []
                    if prompts:
                        try:
                            _ga.mark_awaiting_input(live.job_id, prompts[0])
                            gate_marked = True
                        except Exception:
                            pass
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
        _finalize(live.job_id, code, result_envelope)
        live.done.set()


def _parse_result_envelope(line: str):
    """Return the cost fields from a stream-json ``result`` line, or ``None``.

    A real ``claude -p`` stream-json session ends with a ``{"type":"result", ...}``
    envelope carrying ``total_cost_usd``, ``usage``, ``duration_ms``, and
    ``session_id`` (spike-proven). The mock runner emits the same shape. Only
    well-formed JSON objects of ``type == "result"`` are recognized; everything
    else (plain content lines) is ignored cheaply.
    """
    s = line.strip()
    if not s.startswith("{") or '"result"' not in s:
        return None
    try:
        obj = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict) or obj.get("type") != "result":
        return None
    return obj


def _cost_from_envelope(env: dict) -> dict:
    """Normalize a result envelope into the cost fields stored on a record.

    Returns ``{total_cost_usd, duration_ms, input_tokens, output_tokens,
    total_tokens, session_id}`` with safe defaults. Token counts come from the
    envelope's ``usage`` block.
    """
    usage = env.get("usage") or {}
    inp = usage.get("input_tokens") or 0
    out = usage.get("output_tokens") or 0
    try:
        inp = int(inp)
    except (TypeError, ValueError):
        inp = 0
    try:
        out = int(out)
    except (TypeError, ValueError):
        out = 0
    try:
        cost = float(env.get("total_cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    try:
        dur = int(env.get("duration_ms") or 0)
    except (TypeError, ValueError):
        dur = 0
    return {
        "total_cost_usd": cost,
        "duration_ms": dur,
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "session_id": env.get("session_id"),
    }


def _finalize(job_id: str, exit_code, result_envelope=None) -> None:
    """Record the terminal status once the process exits.

    Cancellation may have already set the status to ``cancelled``; do not
    clobber a terminal status that was set deliberately. If a ``result``
    envelope was captured from the stream (Wave 7), stamp its cost/usage/
    duration onto the record regardless of the terminal status (a cancelled
    job may still have emitted a partial result envelope before the kill).
    """
    with _paths.WRITE_LOCK:
        rec = load_record(job_id)
        if rec is None:
            return
        if result_envelope is not None:
            cost = _cost_from_envelope(result_envelope)
            rec["cost"] = cost
            if cost.get("session_id") and not rec.get("session_id"):
                rec["session_id"] = cost["session_id"]
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


def extract_assistant_text(lines) -> list:
    """Extract the model's ACTUAL text from a job's captured stdout lines.

    Production runs ``claude -p --output-format stream-json``, whose stdout is
    NDJSON envelopes — the model's text is NOT emitted as bare lines. It lives in
    ``{"type":"assistant","message":{"content":[{"type":"text","text":...}]}}``
    frames, and the complete final answer is in the terminal
    ``{"type":"result","result":"<final text>"}`` envelope (the ``-p`` print
    result). A naive "skip every ``{...}`` line with a ``type``" parser therefore
    discards 100% of the model output in production (the summarizer bug).

    This returns the model's text as a list of non-empty, newline-split lines,
    preferring the canonical ``result`` envelope text, then concatenated
    ``assistant`` text blocks. **Back-compat:** a line that is NOT a stream-json
    envelope (e.g. a bare claim line from a test stub / non-stream output) is
    taken verbatim as text, so existing stub-driven callers keep working.

    Stdlib only; never raises (an unparseable line is treated as bare text).
    """
    result_text = None
    assistant_parts = []
    bare_parts = []
    for raw in (lines or []):
        s = (raw or "").strip()
        if not s:
            continue
        obj = None
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
            except (json.JSONDecodeError, ValueError):
                obj = None
        if isinstance(obj, dict) and obj.get("type"):
            t = obj.get("type")
            if t == "result":
                r = obj.get("result")
                if isinstance(r, str) and r.strip():
                    result_text = r  # last terminal result wins
            elif t == "assistant":
                msg = obj.get("message") or {}
                for block in (msg.get("content") or []):
                    if (isinstance(block, dict)
                            and block.get("type") == "text"
                            and isinstance(block.get("text"), str)
                            and block["text"].strip()):
                        assistant_parts.append(block["text"])
            # Other envelope types (system/user/tool_use/...) carry no answer text.
            continue
        # Not a recognized envelope → a bare text line (test stub / plain output).
        bare_parts.append(s)

    if result_text is not None:
        text = result_text
    elif assistant_parts:
        text = "\n".join(assistant_parts)
    else:
        text = "\n".join(bare_parts)

    return [ln.strip() for ln in text.splitlines() if ln.strip()]


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
        if out["status"] in TERMINAL_STATUSES:
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


# ── Concurrency policy: same-lane serialize + folder-build lock (Wave 6) ─────

def _holder_is_active(job_id: str) -> bool:
    """True if ``job_id`` is still a live (non-terminal) job.

    Used to garbage-collect stale slots: a holder whose record is terminal (or
    gone) no longer occupies its lane/folder slot, so a fresh launch may proceed.
    Consults the durable record (the cross-restart source of truth); reconciles
    a dead 'running' record to interrupted via :func:`liveness_check`.
    """
    if not job_id:
        return False
    rec = load_record(job_id)
    if rec is None:
        return False
    if rec.get("status") in TERMINAL_STATUSES:
        return False
    # Record still says running — verify the process is genuinely alive,
    # reconciling a dead-but-"running" record to interrupted as a side effect.
    rec = liveness_check(job_id) or rec
    return rec.get("status") not in TERMINAL_STATUSES


def _gc_lane_slot(project_id: str, lane: str) -> None:
    """Drop the (project_id, lane) active slot if its holder is no longer live."""
    key = (project_id, lane)
    holder = _ACTIVE_LANE.get(key)
    if holder is not None and not _holder_is_active(holder):
        _ACTIVE_LANE.pop(key, None)


def _gc_folder_build(folder_path: str) -> None:
    """Drop the folder build lock if its holder is no longer live."""
    holder = _FOLDER_BUILD.get(folder_path)
    if holder is not None and not _holder_is_active(holder):
        _FOLDER_BUILD.pop(folder_path, None)


def lane_holder(project_id: str, lane: str):
    """Return the job_id currently holding (project_id, lane), or ``None``.

    Self-healing: a stale slot whose holder has gone terminal is cleared first.
    """
    with _paths.WRITE_LOCK:
        _gc_lane_slot(project_id, lane)
        return _ACTIVE_LANE.get((project_id, lane))


def folder_build_holder(folder_path: str):
    """Return the job_id holding ``folder_path``'s build lock, or ``None``.

    This is what the UI's folder-build-lock badge keys off of. Self-healing:
    a finished build's lock is released here.
    """
    folder_path = str(folder_path)
    with _paths.WRITE_LOCK:
        _gc_folder_build(folder_path)
        return _FOLDER_BUILD.get(folder_path)


def launch_guarded(lane: str, project_id: str, folder_path, cwd=None,
                   extra_args=None, env=None, job_id: str = None,
                   backend=DEFAULT_BACKEND, prompt=None, output_dir=None,
                   gated=False) -> dict:
    """Launch a job under the Wave-6 concurrency policy.

    Policy (frozen design — MASTER-PLAN "Lanes & concurrency"):
    - WITHIN a project: same-lane jobs are **serialized** (a second same-lane
      launch while one is live is refused); cross-lane jobs run **concurrently**
      (the key includes the lane, so different lanes never contend).
    - ACROSS projects sharing a folder: **build** jobs are serialized at the
      FOLDER level (at most one build per ``folder_path``); a second build in
      that folder — even for a different project — is refused with the
      ``folder-build-lock`` indicator. research/plan are NOT folder-locked.

    The reservation (check-and-set of both the lane slot and, for builds, the
    folder lock) plus the actual :func:`launch` all happen INSIDE
    ``paths.WRITE_LOCK``, so the policy is correct under concurrency — two
    builds for one folder can never both win the lock.

    ``prompt`` / ``output_dir`` / ``gated`` are threaded straight through to
    :func:`launch` so the real per-backend argv (and the gated stdin pipe) are
    built there. They are inert under the concurrency policy itself.

    Raises :class:`LaneBusyError` (with ``reason`` + ``holder``) when refused.
    On success returns the job record (as :func:`launch`).
    """
    folder_path = str(folder_path)
    with _paths.WRITE_LOCK:
        # 1) Same-lane within-project serialization.
        _gc_lane_slot(project_id, lane)
        same = _ACTIVE_LANE.get((project_id, lane))
        if same is not None:
            raise LaneBusyError(REFUSED_SAME_LANE, holder=same)

        # 2) Folder-level build lock (build lane only).
        if lane == BUILD_LANE:
            _gc_folder_build(folder_path)
            held = _FOLDER_BUILD.get(folder_path)
            if held is not None:
                raise LaneBusyError(REFUSED_FOLDER_BUILD, holder=held)

        # Both gates clear → launch under the lock, then record the reservation
        # against the real job_id so subsequent contenders see it.
        rec = launch(lane, cwd=cwd, extra_args=extra_args, env=env,
                     job_id=job_id, backend=backend, prompt=prompt,
                     output_dir=output_dir, gated=gated)
        jid = rec["job_id"]
        _ACTIVE_LANE[(project_id, lane)] = jid
        if lane == BUILD_LANE:
            _FOLDER_BUILD[folder_path] = jid
        # Stamp the policy context onto the durable record for introspection
        # (and so the folder-build-lock badge can be reconstructed from disk).
        _update_record(jid, project_id=project_id, folder_path=folder_path)
        return rec


def release_slots(job_id: str) -> None:
    """Release any lane/folder slots a (now-finished) job was holding.

    Called when a job reaches a terminal status to promptly free its lane and,
    if it was a build, its folder lock. Safe to call repeatedly; the lazy GC in
    the holder accessors also reclaims slots, so this is an optimization for
    responsiveness, not a correctness requirement.
    """
    with _paths.WRITE_LOCK:
        for key, holder in list(_ACTIVE_LANE.items()):
            if holder == job_id:
                _ACTIVE_LANE.pop(key, None)
        for folder, holder in list(_FOLDER_BUILD.items()):
            if holder == job_id:
                _FOLDER_BUILD.pop(folder, None)


# ── Test/maintenance helpers ─────────────────────────────────────────────────

def wait(job_id: str, timeout: float = 30.0) -> dict:
    """Block until the job's reader thread finishes (or timeout). Test helper."""
    with _LIVE_LOCK:
        live = _LIVE.get(job_id)
    if live is not None:
        live.done.wait(timeout=timeout)
    return load_record(job_id)


def _reset_live_table_for_tests() -> None:
    """Drop the in-memory live + policy tables (used between tests).

    Does not kill procs. Clears the live job table and the Wave-6 concurrency
    registries (lane slots + folder build locks) so each test starts clean.
    """
    with _LIVE_LOCK:
        _LIVE.clear()
    with _paths.WRITE_LOCK:
        _ACTIVE_LANE.clear()
        _FOLDER_BUILD.clear()
