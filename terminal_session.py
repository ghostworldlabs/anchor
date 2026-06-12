#!/usr/bin/env python3
"""Anchor live terminal session service — Wave 3 of v3 "Mission Control".

Ties together the three Wave-1/Wave-2 substrates into one live session service:

- ``pty_manager`` (Wave 1) — the real ConPTY / stub PTY child;
- ``session_registry`` (Wave 2) — the durable, restart-surviving registry;
- ``worktrees`` (Wave 2) — per-session git-worktree isolation.

The keystone flow (per the Wave-2 seam recorded in ``EXECUTION-LOG.md``):

    mint sid -> worktrees.create_worktree(pid, sid)
             -> pty_manager.start([backend], cwd=worktree_path)  (BARE shell —
                NO auto-seeded skill/prompt; that is a later wave's concern)
             -> session_registry.register_session(..., status=RUNNING,
                                                  session_id=sid)

The **same id** is used as both the pty_manager session id and the registry
``session_id`` — minted once, threaded through — so there is exactly ONE id per
session.

``attach`` REATTACHES by replaying the live screen buffer (``read_since`` from
cursor 0); detach is implicit (a client simply stops reading — NOTHING is killed
on detach, the process keeps running). ``kill`` reaps the PTY, marks the registry
record terminal, and removes the worktree.

Every entry point tolerates an unknown / already-dead session cleanly (clear
error dict, never a crash). Stdlib only; the native PTY dep is isolated in
``pty_manager`` and selected by ``ANCHOR_PTY_BACKEND`` (``stub`` in all tests).
"""

import uuid

import pty_manager as _pty
import session_registry as _reg
import worktrees as _wt
import rnd_registry as _rnd

try:
    import lanes as _lanes
except Exception:  # pragma: no cover - lanes is always importable, defensive
    _lanes = None


#: Backends this service accepts (mirrors session_registry.VALID_BACKENDS).
VALID_BACKENDS = {_reg.BACKEND_CLAUDE, _reg.BACKEND_GEMINI}


def _valid_lanes():
    """Canonical set of lane names a terminal session may run.

    The terminal lane is threaded through ``lanes.check_engine_allowed``, so the
    authoritative names are the trio-lane keys (``research``/``plan``/``build``)
    plus the future-ideas ``grass`` lane. We also accept the ``rnd_registry``
    on-disk lane DIR names (``planning``/``deliverables``) so either naming
    convention is tolerated — but a typo like ``"planx"`` is rejected BEFORE any
    worktree/PTY is created.
    """
    lanes = set()
    try:
        lanes.update(_rnd.STATUS_LANES)
    except Exception:  # pragma: no cover - rnd_registry always defines it
        pass
    lanes.add("grass")
    if _lanes is not None:
        try:
            lanes.update(_lanes.LANES.keys())
        except Exception:  # pragma: no cover - defensive
            pass
    return lanes


class TerminalSessionError(RuntimeError):
    """A terminal-session operation failed for a clear, reportable reason."""


def _new_id() -> str:
    """Mint one fresh id used as BOTH the pty + registry session id."""
    return uuid.uuid4().hex


def _check_engine_allowed(lane, backend):
    """Enforce the lane/engine policy (Gemini = research-only) if available.

    Reuses ``lanes.check_engine_allowed`` when the lane name maps onto a known
    lane; otherwise it only validates the backend is a recognized engine. Raises
    :class:`TerminalSessionError` for a disallowed engine / unknown backend.
    """
    if backend not in VALID_BACKENDS:
        raise TerminalSessionError(
            "unknown backend %r (expected claude|gemini)" % (backend,))
    if _lanes is not None:
        try:
            _lanes.check_engine_allowed(lane, backend)
        except getattr(_lanes, "EngineNotAllowedError", ()) as exc:
            raise TerminalSessionError(str(exc)) from exc


def start_session(project_id, lane, backend=_reg.BACKEND_CLAUDE, label=""):
    """Start a live, worktree-isolated, registered terminal session.

    Resolves ``project_id`` in ``rnd_registry``, mints ONE session id, creates a
    git worktree for it, launches a **bare interactive** ``backend`` PTY in that
    worktree (NO auto-seeded skill/prompt — a clean shell), and registers the
    session as ``RUNNING``. The pty id IS the registry ``session_id``.

    Returns the registry record (incl. ``session_id``). Raises
    :class:`TerminalSessionError` for an unknown project or a disallowed engine.
    On a worktree-creation failure it raises with the git reason (nothing is left
    registered / no PTY is leaked).
    """
    proj = _rnd.get_project(project_id)
    if proj is None:
        raise TerminalSessionError("unknown project: %s" % (project_id,))

    # Validate the lane BEFORE creating any worktree/PTY — a typo must not mint a
    # real session. (Reuses the canonical lane set; engine policy is checked next.)
    if lane not in _valid_lanes():
        raise TerminalSessionError(
            "unknown lane %r (expected one of: %s)"
            % (lane, ", ".join(sorted(_valid_lanes()))))

    _check_engine_allowed(lane, backend)

    sid = _new_id()

    # 1) Isolated worktree first — if this fails we never start a PTY.
    wt = _wt.create_worktree(project_id, sid)
    if not wt.get("ok"):
        raise TerminalSessionError(
            "worktree creation failed (%s): %s"
            % (wt.get("reason", "unknown"), wt.get("detail", "")))
    worktree_path = wt["path"]
    branch = wt["branch"]

    # 2) Launch a BARE interactive PTY in the worktree (no skill/prompt seeding).
    try:
        pty_sid = _pty.start([backend], cwd=worktree_path)
    except Exception as exc:
        # Roll back the worktree so a failed launch leaves nothing behind.
        try:
            _wt.remove_worktree(sid, project_id=project_id)
        except Exception:
            pass
        raise TerminalSessionError(
            "failed to start PTY (%s): %s" % (backend, exc)) from exc

    # 3) Reuse the pty id AS the registry session_id (ONE id per session).
    #    pty_manager mints its own opaque id; rebind it to our chosen sid so the
    #    registry, worktree and PTY all key off a single id.
    with _pty._TABLE_LOCK:
        child = _pty._LIVE.pop(pty_sid, None)
        if child is not None:
            _pty._LIVE[sid] = child

    # 4) Register the session. If THIS fails (after the PTY is started+rebound),
    #    roll back BOTH the PTY and the worktree so nothing is left as an orphan
    #    invisible to reconcile — the docstring's "nothing left registered / no
    #    PTY leaked" promise must hold for the registry-failure path too.
    try:
        record = _reg.register_session(
            project_id=project_id,
            lane=lane,
            backend=backend,
            worktree_path=worktree_path,
            branch=branch,
            status=_reg.STATUS_RUNNING,
            label=label,
            session_id=sid,
        )
    except Exception as exc:
        try:
            _pty.kill(sid)
        except Exception:
            pass
        try:
            _wt.remove_worktree(sid, project_id=project_id)
        except Exception:
            pass
        raise TerminalSessionError(
            "failed to register session (%s); rolled back PTY + worktree"
            % (exc,)) from exc
    return record


def attach(session_id):
    """Reattach to a session: replay the full live screen buffer + status.

    Returns ``{"ok": True, "session_id", "buffer", "cursor", "status",
    "record"}`` where ``buffer`` is the full retained PTY output (``read_since``
    from cursor 0) so a reconnecting client sees prior output, ``cursor`` is the
    next read cursor, and ``status`` is the PTY liveness (``running``/``dead``).
    Detach is implicit (the client simply stops reading) — NOTHING is killed.

    For an unknown session returns ``{"ok": False, "reason": "unknown-session"}``
    (never raises).
    """
    record = _reg.get_session(session_id)
    try:
        out = _pty.read_since(session_id, 0)
    except _pty.UnknownSession:
        # No live PTY (e.g. after a restart) — replay nothing but report the
        # registry record so the UI can still show the (idle) session.
        return {
            "ok": True,
            "session_id": session_id,
            "buffer": "",
            "cursor": 0,
            "dropped": 0,
            "truncated": False,
            "status": "dead",
            "record": record,
        }
    dropped = int(out.get("dropped", 0) or 0)
    return {
        "ok": True,
        "session_id": session_id,
        "buffer": out.get("text", ""),
        "cursor": out.get("next", 0),
        # Honest replay: how many older chars were discarded from the bounded
        # buffer, and a convenience bool a reattaching client can branch on.
        "dropped": dropped,
        "truncated": dropped > 0,
        "status": out.get("status"),
        "record": record,
    }


def input(session_id, data):
    """Write ``data`` (str/bytes) onto the session's PTY stdin.

    Returns ``{"ok": True}`` on success, or
    ``{"ok": False, "reason": "unknown-session"}`` for an unknown id (no raise).
    """
    try:
        _pty.write(session_id, data)
    except _pty.UnknownSession:
        return {"ok": False, "reason": "unknown-session"}
    return {"ok": True}


def resize(session_id, cols, rows):
    """Resize the session's PTY. Returns a status dict (no raise on unknown)."""
    try:
        _pty.resize(session_id, cols, rows)
    except _pty.UnknownSession:
        return {"ok": False, "reason": "unknown-session"}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": "bad-dimensions", "detail": str(exc)}
    return {"ok": True}


def read_since(session_id, cursor=0):
    """Thin wrapper over ``pty_manager.read_since`` (cursor-stable output read).

    Returns the manager's ``{"text", "next", "status"}`` on success, or
    ``{"ok": False, "reason": "unknown-session"}`` for an unknown id.
    """
    try:
        return _pty.read_since(session_id, cursor)
    except _pty.UnknownSession:
        return {"ok": False, "reason": "unknown-session"}


def kill(session_id, project_id=None):
    """Kill a session: reap the PTY, mark the registry terminal, remove worktree.

    Tolerant: an unknown/already-dead PTY still proceeds to re-status the registry
    record (``STATUS_DONE``) and remove the worktree. ``project_id`` is resolved
    from the registry record when not supplied so the worktree's owning repo can
    be located for a clean ``git worktree remove``. Other sessions are untouched.

    Returns ``{"ok": True, "session_id", "pty_killed", "worktree": {...}}``.
    """
    record = _reg.get_session(session_id)
    if project_id is None and record:
        project_id = record.get("project_id") or None

    pty_killed = False
    try:
        _pty.kill(session_id)
        pty_killed = True
    except _pty.UnknownSession:
        pty_killed = False  # already dead / never had a live PTY — tolerate

    # Mark the registry record terminal (DONE) — tolerate an unknown id.
    try:
        _reg.update_session(session_id, status=_reg.STATUS_DONE)
    except KeyError:
        pass

    # Remove the per-session worktree (safety-checked, tolerant of already-gone).
    wt_out = _wt.remove_worktree(session_id, project_id=project_id)

    return {
        "ok": True,
        "session_id": session_id,
        "pty_killed": pty_killed,
        "worktree": wt_out,
    }


def list_sessions(project_id=None, status=None):
    """Thin pass-through to ``session_registry.list_sessions`` (for UI/CLI)."""
    return _reg.list_sessions(project_id=project_id, status=status)


def get_session(session_id):
    """Return the registry record for ``session_id`` (or ``None``)."""
    return _reg.get_session(session_id)
