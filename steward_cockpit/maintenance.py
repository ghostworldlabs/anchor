"""codex-discipline-2026-09-15 Wave 1.6 — the service-wide maintenance barrier.

One durable state that lets Anchor activate new code without a forced kill:

* John's messages keep being accepted into each steward's persisted queue;
* no new steward wake, page-open wake, or delegated job launch starts;
* every running steward turn and delegated job is allowed to reach its own
  boundary; the barrier polls until nothing is in flight;
* then, and only then, the supervised process restarts onto the code on disk
  (the same drain-and-exit /api/restart performs), and the flag is cleared
  by the fresh boot.

Every activation this week waited hours because the only tools were "refuse
while busy" and "kill after ten seconds". This is the third option.
Stdlib only; the callers inject how to list engines, running jobs, and how
to restart, so it is testable without a server.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).parent
STATE_FILE = HERE / "maintenance-state.json"
POLL_SECONDS = 5.0
MAX_WAIT_SECONDS = 4 * 3600  # a barrier that never drains is reported, not silent

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"active": False}
_THREAD: threading.Thread | None = None
_GENERATION = 0  # a superseded watcher (cancelled/cleared then re-armed) never writes again


def _write(state: dict[str, Any]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _load() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"active": False}
    except (OSError, ValueError):
        return {"active": False}


def boot_clear(reason: str = "fresh boot") -> None:
    """A fresh process is, by definition, past the barrier."""
    with _LOCK:
        state = _load()
        if state.get("active"):
            state.update({"active": False, "cleared_at": time.time(), "cleared_reason": reason})
            _write(state)
        _STATE.clear()
        _STATE.update(state)


def is_active() -> bool:
    with _LOCK:
        return bool(_STATE.get("active"))


def status() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)


def cancel(reason: str = "cancelled") -> dict[str, Any]:
    with _LOCK:
        _STATE.update({"active": False, "cleared_at": time.time(), "cleared_reason": reason})
        _write(_STATE)
        return dict(_STATE)


def begin(reason: str, *, busy_engines: Callable[[], list[str]],
          running_jobs: Callable[[], list[str]], restart: Callable[[str], Any],
          poll_seconds: float = POLL_SECONDS, max_wait: float = MAX_WAIT_SECONDS,
          clock: Callable[[], float] = time.time) -> dict[str, Any]:
    """Arm the barrier and start the drain watcher. Idempotent while active."""
    global _THREAD, _GENERATION
    with _LOCK:
        if _STATE.get("active") and _THREAD is not None and _THREAD.is_alive():
            return dict(_STATE)
        # active with a dead watcher (Grok R1): re-arm under a new generation
        # so the flag can never outlive its drain thread
        _GENERATION += 1
        generation = _GENERATION
        _STATE.clear()
        _STATE.update({"active": True, "generation": generation, "reason": str(reason)[:200],
                       "requested_at": clock(), "waiting_on": [], "checks": 0,
                       "restart_called": False})
        _write(_STATE)

    def _mine() -> bool:
        return bool(_STATE.get("active")) and _STATE.get("generation") == generation

    def _watch() -> None:
        while True:
            with _LOCK:
                if not _mine():
                    return
                started = _STATE.get("requested_at") or clock()
            try:
                waiting = [f"steward:{k}" for k in busy_engines()] + [f"job:{j}" for j in running_jobs()]
            except Exception as exc:  # a broken probe must not fake a drained system
                waiting = [f"probe-error:{type(exc).__name__}"]
            with _LOCK:
                if not _mine():
                    return
                _STATE["waiting_on"] = waiting[:50]
                _STATE["checks"] = int(_STATE.get("checks", 0)) + 1
                _STATE["last_check_at"] = clock()
                drained = not waiting
                timed_out = clock() - started > max_wait
                if drained:
                    _STATE["restart_called"] = True
                    _STATE["drained_at"] = clock()
                elif timed_out:
                    _STATE["active"] = False
                    _STATE["cleared_reason"] = "max wait exceeded; still busy"
                    _STATE["cleared_at"] = clock()
                _write(_STATE)
            if drained:
                try:
                    restart(str(reason))
                except Exception as exc:
                    with _LOCK:
                        _STATE["active"] = False
                        _STATE["cleared_reason"] = f"restart failed: {type(exc).__name__}"
                        _STATE["cleared_at"] = clock()
                        _write(_STATE)
                return
            if timed_out:
                return
            time.sleep(poll_seconds)

    _THREAD = threading.Thread(target=_watch, name="anchor-maintenance-barrier", daemon=True)
    _THREAD.start()
    return status()
