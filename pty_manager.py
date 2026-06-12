#!/usr/bin/env python3
"""Anchor PTY session manager — real ConPTY (pywinpty) with a stub backend seam.

v3 "Mission Control" (MASTER-PLAN §D / Implementation-Plan Wave 1). This is the
ONE place in Anchor that may use a native dependency (``pywinpty`` / ConPTY),
consciously waiving the otherwise stdlib-only rule **for the terminal subsystem
only**. The native dependency is isolated here and imported LAZILY:

- ``import winpty`` happens INSIDE the pywinpty backend's ``start`` path, never at
  module import. So ``import pty_manager`` always works even on a host without
  pywinpty; only actually *starting* a real PTY (default backend) needs it.
- If ``winpty`` is absent, the pywinpty backend raises :class:`PtyUnavailable`;
  the rest of the module — and the whole rest of Anchor — is unaffected.

Backend selection is by the env var ``ANCHOR_PTY_BACKEND``:

- ``ANCHOR_PTY_BACKEND=stub`` selects the deterministic in-memory **stub**
  backend used by every test (no real subprocess, no native dep).
- unset / anything else selects the real **pywinpty** backend (runtime).

Manager core API (cursor-stable like ``job_runner.tail``):

    start(cmd, cwd=None, env=None) -> session_id
    write(session_id, data)
    read_since(session_id, cursor) -> {"text", "next", "status"}
    resize(session_id, cols, rows)
    kill(session_id)

Unknown-session calls raise :class:`UnknownSession` (a ``KeyError`` subclass).
Thread-safe: a module-local re-entrant lock guards the live-session table, since
the live HTTP server is threaded.
"""

import os
import subprocess
import sys
import threading
import uuid

# ── Errors ──────────────────────────────────────────────────────────────────


class PtyUnavailable(RuntimeError):
    """The real PTY backend (pywinpty / ConPTY) is unavailable on this host.

    Raised by the pywinpty backend when ``import winpty`` fails. The terminal
    subsystem reports "real terminal unavailable"; the rest of Anchor is fine.
    """


class UnknownSession(KeyError):
    """A manager call referenced a session id that is not in the live table."""


# ── Backend selection ─────────────────────────────────────────────────────────

#: Env var that selects the PTY backend. ``stub`` → in-memory fake child;
#: unset / anything else → the real pywinpty (ConPTY) backend.
BACKEND_ENV = "ANCHOR_PTY_BACKEND"
STUB_BACKEND = "stub"

#: Max characters of cumulative output retained per session. A long-lived
#: terminal can't grow memory without bound; we keep only this tail window.
#: ``read_since`` preserves absolute-cursor semantics across the drop boundary
#: (see :meth:`_StubChild.read_since`).
MAX_BUFFER_CHARS = 200_000


def select_backend():
    """Return a backend instance per ``ANCHOR_PTY_BACKEND`` (read at call time).

    ``stub`` → :class:`StubBackend`; anything else (incl. unset) →
    :class:`PywinptyBackend`. Kept tiny/pure so the selection is unit-testable.
    """
    raw = os.environ.get(BACKEND_ENV)
    if raw and raw.strip().lower() == STUB_BACKEND:
        return StubBackend()
    return PywinptyBackend()


# ── Stub backend — deterministic in-memory pty-able fake child ────────────────


class _StubChild:
    """A faithful, in-memory fake pty child.

    No real subprocess. It is "alive" from ``start`` until ``kill``. A ``write``
    ECHOES the written text into the child's readable output buffer, so a
    start→write→read round-trip works. ``read_since`` returns output after a
    cursor (a character offset into the cumulative output buffer). ``resize``
    records the requested cols/rows. This stub is reused by later waves (the
    Wave-3 terminal tests), so it is deliberately faithful and importable.
    """

    def __init__(self, cmd, cwd=None, env=None):
        self.cmd = cmd
        self.cwd = cwd
        self.env = env
        # Bounded tail window of cumulative output. ``_total`` = total chars ever
        # produced; ``_dropped`` = chars discarded from the front. The retained
        # text is always the last ``_total - _dropped`` chars.
        self._buf = ""           # retained tail window (str)
        self._total = 0
        self._dropped = 0
        self._lock = threading.RLock()
        self.cols = 80
        self.rows = 24
        self._alive = True
        self.reaped = False

    def _append(self, text):
        """Append output to the bounded tail window (caller holds ``_lock``)."""
        if not text:
            return
        self._buf += text
        self._total += len(text)
        excess = len(self._buf) - MAX_BUFFER_CHARS
        if excess > 0:
            self._buf = self._buf[excess:]
            self._dropped += excess

    def _read_since(self, cursor):
        """Serve output after ``cursor`` from the tail window (holds ``_lock``).

        A cursor below ``_dropped`` (caller missed scrollback) is clamped to the
        oldest retained char — no crash, no duplication. ``next`` is the absolute
        total, so a re-read from ``next`` returns ``""``.
        """
        start = max(int(cursor), self._dropped)
        if start >= self._total:
            return "", self._total
        text = self._buf[start - self._dropped:]
        return text, self._total

    # --- lifecycle ---
    def is_alive(self):
        with self._lock:
            return self._alive

    def kill(self):
        with self._lock:
            self._alive = False
            self.reaped = True

    # --- io ---
    def write(self, data):
        if data is None:
            return
        text = data if isinstance(data, str) else data.decode("utf-8", "replace")
        with self._lock:
            if not self._alive:
                return
            # Echo the written bytes into the readable output buffer so a
            # round-trip test observes them.
            self._append(text)

    def read_since(self, cursor):
        """Return (text_after_cursor, next_cursor).

        ``cursor`` is an ABSOLUTE character offset into the cumulative output.
        The next cursor is the absolute total, so a second read returns nothing
        new. Output past the bounded tail window is dropped (see ``_append``).
        """
        with self._lock:
            return self._read_since(cursor)

    def resize(self, cols, rows):
        with self._lock:
            self.cols = int(cols)
            self.rows = int(rows)


class StubBackend:
    """Backend that creates :class:`_StubChild` instances (no native dep)."""

    name = STUB_BACKEND

    def start(self, cmd, cwd=None, env=None):
        return _StubChild(cmd, cwd=cwd, env=env)


# ── pywinpty backend — real ConPTY child (lazy native import) ─────────────────


class _PywinptyChild:
    """A real ConPTY child driven by ``pywinpty``'s high-level ``PtyProcess``.

    pywinpty's ``read()`` can block, so a daemon reader thread continuously
    drains output into an in-memory cumulative buffer; ``read_since`` then serves
    that buffer cursor-stably (same contract as the stub). ``write`` feeds the
    PTY; ``resize`` calls ``setwinsize(rows, cols)``; ``kill`` terminates the
    child (force) and stops the reader.
    """

    def __init__(self, proc):
        self._proc = proc                 # winpty.PtyProcess
        self.pid = getattr(proc, "pid", None)
        # Bounded tail window of cumulative output (see _StubChild for the
        # absolute-cursor contract). ``_total``/``_dropped`` track the absolute
        # offset of the retained window.
        self._buf = ""
        self._total = 0
        self._dropped = 0
        self._lock = threading.RLock()
        self._closed = False
        self.cols = None
        self.rows = None
        # Drain output in the background because PtyProcess.read() blocks.
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()

    def _drain(self):
        while True:
            if self._closed:
                break
            try:
                data = self._proc.read(1024)
            except EOFError:
                break
            except Exception:
                break
            if data:
                with self._lock:
                    self._append(data)

    def _append(self, text):
        """Append output to the bounded tail window (caller holds ``_lock``)."""
        if not text:
            return
        self._buf += text
        self._total += len(text)
        excess = len(self._buf) - MAX_BUFFER_CHARS
        if excess > 0:
            self._buf = self._buf[excess:]
            self._dropped += excess

    def is_alive(self):
        try:
            return bool(self._proc.isalive())
        except Exception:
            return False

    def kill(self):
        # Signal the daemon reader thread to stop; _drain breaks on the
        # terminated proc's EOFError/exception, so no busy-spin and no need to
        # block on a join (it's a daemon).
        with self._lock:
            self._closed = True
        pid = self.pid
        try:
            self._proc.terminate(force=True)
        except Exception:
            pass
        # terminate(force=True) reaps only the DIRECT child; real `claude`
        # spawns `node` grandchildren. Mirror job_runner's tree-kill precedent
        # (`taskkill /T /F /PID`) so the whole tree is reaped — failure tolerated.
        if sys.platform == "win32" and pid:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=15,
                )
            except (OSError, subprocess.SubprocessError):
                pass

    def write(self, data):
        if data is None:
            return
        text = data if isinstance(data, str) else data.decode("utf-8", "replace")
        try:
            self._proc.write(text)
            try:
                self._proc.flush()
            except Exception:
                pass
        except Exception:
            pass

    def read_since(self, cursor):
        # Absolute-cursor contract; a cursor below the retained window is clamped
        # to the oldest retained char (missed scrollback) — no crash/duplication.
        with self._lock:
            start = max(int(cursor), self._dropped)
            if start >= self._total:
                return "", self._total
            return self._buf[start - self._dropped:], self._total

    def resize(self, cols, rows):
        self.cols = int(cols)
        self.rows = int(rows)
        try:
            # pywinpty signature is setwinsize(rows, cols).
            self._proc.setwinsize(int(rows), int(cols))
        except Exception:
            pass


class PywinptyBackend:
    """Real ConPTY backend. Imports ``winpty`` LAZILY inside :meth:`start`."""

    name = "pywinpty"

    def start(self, cmd, cwd=None, env=None):
        # Lazy native import — this is the ONLY ``import winpty`` in Anchor and
        # it must NOT run at module import time. A missing native dep surfaces a
        # clear, isolated error.
        try:
            import winpty  # noqa: F401  (imported lazily on purpose)
        except Exception as exc:  # ImportError or a native-load failure
            raise PtyUnavailable(
                "pywinpty (ConPTY) is unavailable: real terminal cannot start "
                "(%s). Set ANCHOR_PTY_BACKEND=stub for the test backend." % exc
            ) from exc

        argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        argv = [str(a) for a in argv]
        # pywinpty wants dimensions as (rows, cols); default to 24x80.
        proc = winpty.PtyProcess.spawn(
            argv, cwd=cwd, env=env, dimensions=(24, 80))
        return _PywinptyChild(proc)


# ── Manager core ──────────────────────────────────────────────────────────────

#: Module-local lock guarding the live-session table. The HTTP server is
#: threaded, so every table mutation/read goes through this.
_TABLE_LOCK = threading.RLock()

#: session_id -> child object (a _StubChild or _PywinptyChild).
_LIVE = {}


def _get(session_id):
    with _TABLE_LOCK:
        child = _LIVE.get(session_id)
    if child is None:
        raise UnknownSession(session_id)
    return child


def start(cmd, cwd=None, env=None):
    """Start a PTY child for ``cmd`` and return its ``session_id``.

    The backend is selected per ``ANCHOR_PTY_BACKEND`` at call time. ``cmd`` may
    be a string or an argv list. Returns a fresh opaque session id.
    """
    backend = select_backend()
    child = backend.start(cmd, cwd=cwd, env=env)
    sid = uuid.uuid4().hex
    with _TABLE_LOCK:
        _LIVE[sid] = child
    return sid


def write(session_id, data):
    """Write ``data`` (str or bytes) onto the session's PTY input.

    Raises :class:`UnknownSession` for an unknown id.
    """
    child = _get(session_id)
    child.write(data)


def read_since(session_id, cursor=0):
    """Return output produced AFTER ``cursor`` for a session.

    Returns ``{"text", "next", "status"}`` where ``next`` is the cursor to pass
    on the next read (cursor-stable: a second read from ``next`` returns ``""``)
    and ``status`` is ``"running"`` or ``"dead"``. Raises :class:`UnknownSession`
    for an unknown id.
    """
    child = _get(session_id)
    text, nxt = child.read_since(cursor)
    # Absolute count of chars dropped from the FRONT of the bounded tail window.
    # A reattaching client compares this against its cursor to know whether older
    # scrollback was discarded (see terminal_session.attach's ``truncated``).
    try:
        with child._lock:
            dropped = int(child._dropped)
    except Exception:
        dropped = 0
    return {
        "text": text,
        "next": nxt,
        "dropped": dropped,
        "status": "running" if child.is_alive() else "dead",
    }


def resize(session_id, cols, rows):
    """Resize the session's PTY to ``cols`` x ``rows``.

    Raises :class:`UnknownSession` for an unknown id.
    """
    child = _get(session_id)
    child.resize(cols, rows)


def kill(session_id):
    """Kill the session's child, reap it, and remove it from the live table.

    Raises :class:`UnknownSession` for an unknown id. After ``kill`` the id is no
    longer in the live table (a subsequent manager call raises UnknownSession).
    """
    with _TABLE_LOCK:
        child = _LIVE.get(session_id)
        if child is None:
            raise UnknownSession(session_id)
        del _LIVE[session_id]
    child.kill()


def live_sessions():
    """Return the list of currently-live session ids (snapshot)."""
    with _TABLE_LOCK:
        return list(_LIVE.keys())


def _reset_live_table_for_tests():
    """Test hook: kill + drop every live session (mirrors job_runner's helper)."""
    with _TABLE_LOCK:
        children = list(_LIVE.values())
        _LIVE.clear()
    for c in children:
        try:
            c.kill()
        except Exception:
            pass
