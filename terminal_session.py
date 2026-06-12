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

import json
import os
import uuid
from pathlib import Path

import paths as _paths
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

#: Default engine when a project has never picked one (v4 Wave 2).
DEFAULT_ENGINE = _reg.BACKEND_CLAUDE

#: Per-project last-used-engine pointer file, stored alongside the per-project
#: cache under ``<folder>/.anchor/projects/<id>/`` (the convention summarizer
#: uses for its project-summary.json). Persisted atomically under WRITE_LOCK.
ENGINE_POINTER_NAME = "engine.json"


# ── Per-project last-used engine persistence (v4 Wave 2) ─────────────────────
#
# The chosen engine (claude|gemini) is selected ONCE per session, but a project
# "remembers" its last-used engine so a fresh session defaults to it. Persisted
# as ``{"last_engine": "<engine>"}`` in ``engine.json`` under the per-project
# store dir — the SAME ``<folder>/.anchor/projects/<id>/`` directory summarizer
# caches into. Atomic write (tmp + os.replace) under ``paths.WRITE_LOCK`` so a
# concurrent ThreadingHTTPServer writer / crash mid-write can't corrupt it.


def _engine_pointer_path(project_id) -> Path:
    """``<folder>/.anchor/projects/<id>/engine.json`` (not created).

    Returns ``None`` if the project (and thus its folder) cannot be resolved.
    """
    proj = _rnd.get_project(project_id)
    if proj is None:
        return None
    folder = proj.get("folder_path", "")
    if not folder:
        return None
    return _rnd.project_store_dir(folder, project_id) / ENGINE_POINTER_NAME


def last_engine_for_project(project_id) -> str:
    """Return the project's last-used engine, defaulting to ``claude`` when unset.

    Best-effort: a missing/corrupt/unreadable pointer (or an unknown project)
    returns :data:`DEFAULT_ENGINE`. An out-of-range persisted value (not a known
    backend) also falls back to the default rather than propagating garbage.
    """
    p = _engine_pointer_path(project_id)
    if p is None or not p.exists():
        return DEFAULT_ENGINE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return DEFAULT_ENGINE
    eng = data.get("last_engine") if isinstance(data, dict) else None
    if eng in VALID_BACKENDS:
        return eng
    return DEFAULT_ENGINE


def set_last_engine_for_project(project_id, engine) -> bool:
    """Persist the project's last-used engine (atomic, under WRITE_LOCK).

    No-op (returns ``False``) for an unknown backend or an unresolvable project;
    otherwise writes ``{"last_engine": engine}`` and returns ``True``. A write
    failure is swallowed (returns ``False``) — remembering the engine is a
    convenience, never worth crashing a live session over.
    """
    if engine not in VALID_BACKENDS:
        return False
    p = _engine_pointer_path(project_id)
    if p is None:
        return False
    try:
        with _paths.WRITE_LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(
                json.dumps({"last_engine": engine}, ensure_ascii=False),
                encoding="utf-8")
            os.replace(str(tmp), str(p))
        return True
    except OSError:
        return False


# ── Per-lane skill-seed map (v4 Wave 1) ──────────────────────────────────────
#
# Kill the repeating-prompt bug at the root: a brand-new cockpit terminal session
# auto-loads its lane's trio skill exactly ONCE, greets ONCE, then behaves like a
# normal interactive terminal. The seed is a SINGLE opening stdin turn written
# right after the PTY launches; ``seeded`` is recorded on the session record so it
# is NEVER re-sent on a later attach/input/read.
#
# Lane → skill (both the trio-lane key ``plan`` and the on-disk dir name
# ``planning`` map to Crucible so either naming convention is tolerated):
#   research          → researchPrime
#   plan / planning   → Crucible
#   build             → Foreman
LANE_SKILL = {
    "research": "researchPrime",
    "plan": "Crucible",
    "planning": "Crucible",
    "build": "Foreman",
}

#: A single global override env var (when set, used verbatim for EVERY lane —
#: tests assert deterministically against it). Per-lane overrides take the form
#: ``ANCHOR_SEED_PROMPT_<LANE-UPPER>`` and win over the global one for that lane.
SEED_ENV_GLOBAL = "ANCHOR_TERMINAL_SEED"
SEED_ENV_LANE_PREFIX = "ANCHOR_SEED_PROMPT_"


def _default_seed_text(skill):
    """The one-time opening instruction: load the skill, confirm, greet once.

    A single instruction string that tells the model to load the lane's skill,
    confirm it is ready, greet EXACTLY once with ``✓ <Skill> loaded — what would
    you like to do?`` and then wait for the user — nothing more. Ends with a
    newline so it is delivered as one submitted turn.
    """
    return (
        "Load the {skill} skill now. Once it is loaded and ready, greet me "
        "EXACTLY once with this single line and nothing else: "
        "\"✓ {skill} loaded — what would you like to do?\" "
        "Then stop and wait for my next message. Do not repeat this greeting."
        "\n"
    ).format(skill=skill)


def seed_for_lane(lane):
    """Return the one-time seed text for ``lane`` (env-overridable), or ``None``.

    Resolution order (so tests can pin a deterministic value):
      1. ``ANCHOR_SEED_PROMPT_<LANE-UPPER>`` — per-lane override;
      2. ``ANCHOR_TERMINAL_SEED`` — single global override (all lanes);
      3. the built-in :func:`_default_seed_text` for the lane's mapped skill.

    A lane with no mapped skill and no override returns ``None`` (no seed sent) —
    e.g. the ``grass`` future-ideas lane is a bare shell.
    """
    per_lane = os.environ.get(SEED_ENV_LANE_PREFIX + str(lane).upper())
    if per_lane is not None:
        return per_lane
    glob = os.environ.get(SEED_ENV_GLOBAL)
    if glob is not None:
        return glob
    skill = LANE_SKILL.get(lane)
    if not skill:
        return None
    return _default_seed_text(skill)


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


#: Sentinel: ``backend`` not explicitly passed → default to the project's
#: last-used engine (v4 Wave 2).
_UNSET = object()


def start_session(project_id, lane, backend=_UNSET, label=""):
    """Start a live, worktree-isolated, registered terminal session.

    Resolves ``project_id`` in ``rnd_registry``, mints ONE session id, creates a
    git worktree for it, launches an interactive ``backend`` PTY in that worktree,
    registers the session as ``RUNNING``, and — for a lane with a mapped trio
    skill — writes **exactly one** opening stdin turn that loads the lane's skill
    and greets once (the v4 Wave-1 seed; recorded as ``seeded=True`` so it is
    never re-sent). The pty id IS the registry ``session_id``.

    v4 Wave 2: when ``backend`` is NOT explicitly passed it defaults to the
    project's **last-used engine** (:func:`last_engine_for_project`, ``claude``
    when unset); on a successful start the chosen engine is recorded as the
    project's last_engine so the next session inherits it.

    Returns the registry record (incl. ``session_id``). Raises
    :class:`TerminalSessionError` for an unknown project or a disallowed engine.
    On a worktree-creation failure it raises with the git reason (nothing is left
    registered / no PTY is leaked).
    """
    proj = _rnd.get_project(project_id)
    if proj is None:
        raise TerminalSessionError("unknown project: %s" % (project_id,))

    # v4 Wave 2: no explicit engine → inherit the project's last-used one.
    if backend is _UNSET:
        backend = last_engine_for_project(project_id)

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

    # 5) Seed the lane's skill EXACTLY ONCE. This is the only place the seed is
    #    ever written — it happens right after a successful launch+register and
    #    is recorded as ``seeded=True`` on the record, so no later attach/input/
    #    read can re-send it. A lane with no mapped skill (e.g. ``grass``) gets a
    #    bare shell (seed_text == None → nothing written). A write/persist failure
    #    is non-fatal: the session is already live and usable; we simply leave it
    #    un-seeded rather than tearing down a working terminal.
    seed_text = seed_for_lane(lane)
    if seed_text:
        try:
            _pty.write(sid, seed_text)
        except Exception:
            seed_text = None  # seed not delivered → don't claim it was
        if seed_text:
            try:
                record = _reg.update_session(
                    sid, seeded=True, seed_text=seed_text)
            except Exception:
                pass

    # v4 Wave 2: remember the engine this session chose so the NEXT session for
    # this project defaults to it. Best-effort (never fails a live session).
    set_last_engine_for_project(project_id, backend)
    return record


def switch_engine(session_id, engine):
    """Toggle a live session to the other engine, keeping its identity.

    Reaps the current session's PTY child (keeping the SAME ``session_id``,
    worktree, branch, lane, and label), launches a NEW PTY on ``engine`` in the
    SAME worktree, re-applies the lane's skill seed ONCE on the new engine, and
    updates the registry record's ``backend`` (+ ``seeded``/``seed_text``). The
    project's last_engine is updated to ``engine`` on success.

    Identity is preserved: the new PTY (which the manager mints under its own
    opaque id) is rebound under the EXISTING ``session_id`` (the same trick
    :func:`start_session` uses), so the registry, worktree and PTY keep keying
    off one id — no orphan PTY and no orphan worktree.

    On a relaunch FAILURE the record is rolled back to its prior, consistent
    state (original backend/seed restored, no half-killed live PTY left behind,
    the worktree untouched) and :class:`TerminalSessionError` is raised.

    Raises :class:`TerminalSessionError` for an unknown session / unknown
    backend / a disallowed lane+engine combination (engine policy is enforced
    BEFORE the old PTY is reaped, so a refused switch never disturbs the session).
    """
    if engine not in VALID_BACKENDS:
        raise TerminalSessionError(
            "unknown backend %r (expected claude|gemini)" % (engine,))

    record = _reg.get_session(session_id)
    if record is None:
        raise TerminalSessionError("unknown session: %s" % (session_id,))

    lane = record.get("lane", "")
    worktree_path = record.get("worktree_path", "")
    project_id = record.get("project_id") or None
    prior_backend = record.get("backend", DEFAULT_ENGINE)
    prior_seeded = bool(record.get("seeded", False))
    prior_seed_text = record.get("seed_text", "") or ""

    if not worktree_path:
        raise TerminalSessionError(
            "session %s has no worktree to relaunch in" % (session_id,))

    # Enforce the lane/engine policy BEFORE touching the live PTY — a refused
    # switch (e.g. gemini on a plan/build lane) leaves the session exactly as-is.
    _check_engine_allowed(lane, engine)

    # 1) Reap the current PTY child (tolerate an already-dead/unknown one).
    try:
        _pty.kill(session_id)
    except _pty.UnknownSession:
        pass

    # 2) Launch a NEW PTY on the other engine in the SAME worktree.
    try:
        pty_sid = _pty.start([engine], cwd=worktree_path)
    except Exception as exc:
        # Relaunch failed: leave the record CONSISTENT. The old PTY is already
        # reaped, so mark the session IDLE (no live process) but keep its prior
        # backend/seed bookkeeping intact — no orphan PTY, worktree untouched.
        try:
            _reg.update_session(
                session_id, status=_reg.STATUS_IDLE, backend=prior_backend,
                seeded=prior_seeded, seed_text=prior_seed_text)
        except Exception:
            pass
        raise TerminalSessionError(
            "failed to relaunch on %s (%s); session left idle, worktree intact"
            % (engine, exc)) from exc

    # 3) Rebind the new PTY under the EXISTING session_id (one id per session).
    with _pty._TABLE_LOCK:
        child = _pty._LIVE.pop(pty_sid, None)
        if child is not None:
            _pty._LIVE[session_id] = child

    # 4) Update the registry record: new backend, RUNNING, seed reset (a fresh
    #    engine needs the skill re-loaded once).
    record = _reg.update_session(
        session_id, backend=engine, status=_reg.STATUS_RUNNING,
        seeded=False, seed_text="")

    # 5) Re-apply the lane seed ONCE on the new engine (same discipline as start).
    seed_text = seed_for_lane(lane)
    if seed_text:
        try:
            _pty.write(session_id, seed_text)
        except Exception:
            seed_text = None
        if seed_text:
            try:
                record = _reg.update_session(
                    session_id, seeded=True, seed_text=seed_text)
            except Exception:
                pass

    # 6) Remember the now-current engine for the project.
    if project_id is not None:
        set_last_engine_for_project(project_id, engine)
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
