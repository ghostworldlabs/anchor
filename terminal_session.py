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
import effort_history as _eh  # v8 Wave 2 keystone: persist_session_docs (no
#                              cycle: effort_history imports neither this module
#                              nor session_registry — only paths + rnd_registry)
import handoff as _handoff  # v6 Wave 6 auto-advance (no cycle: handoff imports
#                            neither terminal_session nor session_registry)

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


def seed_for_lane(lane, seed_context=None):
    """Return the one-time seed text for ``lane`` (env-overridable), or ``None``.

    Resolution order (so tests can pin a deterministic value):
      1. ``ANCHOR_SEED_PROMPT_<LANE-UPPER>`` — per-lane override;
      2. ``ANCHOR_TERMINAL_SEED`` — single global override (all lanes);
      3. the built-in :func:`_default_seed_text` for the lane's mapped skill.

    A lane with no mapped skill and no override returns ``None`` (no seed sent) —
    e.g. the ``grass`` future-ideas lane is a bare shell.

    ``seed_context`` (v4 Wave 6) is an optional extra payload appended to the
    chosen lane seed as the THING TO WORK ON — e.g. a Grass Catcher idea promoted
    into a Research/Plan session. It is folded onto whatever seed was resolved
    above (including an env override, so the promote path stays deterministic in
    tests) so the SINGLE opening turn loads the lane skill AND carries the idea.
    """
    base = None
    per_lane = os.environ.get(SEED_ENV_LANE_PREFIX + str(lane).upper())
    if per_lane is not None:
        base = per_lane
    else:
        glob = os.environ.get(SEED_ENV_GLOBAL)
        if glob is not None:
            base = glob
        else:
            skill = LANE_SKILL.get(lane)
            base = _default_seed_text(skill) if skill else None

    ctx = (seed_context or "").strip()
    if not ctx:
        return base
    # Fold the idea onto the lane seed as one combined opening turn. If the lane
    # had no skill seed (None), the context alone becomes the opening turn.
    suffix = (
        "Here is the idea to work on (promoted from Grass Catchers): "
        "{ctx}\n"
    ).format(ctx=ctx)
    if base is None:
        return suffix
    # Drop a trailing newline on the base so the two parts arrive as ONE turn.
    return base.rstrip("\n") + " " + suffix


def _valid_lanes():
    """Canonical set of lane names a terminal session may run.

    The terminal lane is threaded through ``lanes.check_engine_allowed``, so the
    authoritative names are the trio-lane keys (``research``/``plan``/``build``)
    plus the future-ideas ``grass`` lane and the v7 bare ``general`` lane. We also
    accept the ``rnd_registry`` on-disk lane DIR names (``planning``/
    ``deliverables``) so either naming convention is tolerated — but a typo like
    ``"planx"`` is rejected BEFORE any worktree/PTY is created.

    ``general`` (v7 Wave 4) is a deliberately BARE lane: it is NOT in
    :data:`LANE_SKILL` (so :func:`seed_for_lane` returns ``None`` → no seed → a
    bare PTY, like ``grass``), it is NOT a trio board column (excluded from
    ``anchor_gui._REGISTRY_LANE_TO_COLUMN``), and it is NOT a planning lane (so
    :func:`auto_advance_planning_to_build` never advances it).
    """
    lanes = set()
    try:
        lanes.update(_rnd.STATUS_LANES)
    except Exception:  # pragma: no cover - rnd_registry always defines it
        pass
    lanes.add("grass")
    lanes.add("general")
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


def start_session(project_id, lane, backend=_UNSET, label="", seed_context=None,
                  parent_session_id=None):
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

    v4 Wave 6: ``seed_context`` (optional) is folded onto the lane seed (via
    :func:`seed_for_lane`) so the single opening turn loads the lane skill AND
    carries an extra payload — e.g. a Grass Catcher idea promoted into this
    Research/Plan session — as the thing to work on. It is recorded in
    ``seed_text`` and, like the base seed, is written exactly once.

    v6 Wave 2: ``parent_session_id`` (optional) links this session into an
    existing lineage. When given, the new session JOINS the parent's chain
    (``chain_id`` = the parent's chain_id, resolved via
    :func:`session_registry.chain_for`) and records ``parent_session_id``. When
    omitted, the new session starts its OWN chain (chain_id == its own id). The
    parent record is never mutated.

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

    # v6 Wave 2: resolve the chain this session joins. A parent links the new
    # session into the parent's chain; with no parent the session starts its own
    # singleton chain (chain_id defaults to its own sid in register_session). An
    # unknown parent id is ignored (the session simply starts its own chain).
    parent_id = parent_session_id or ""
    chain_id = None
    if parent_id:
        chain_id = _reg.chain_for(parent_id)
        if not chain_id:
            parent_id = ""  # unknown parent → start a fresh chain

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
            parent_session_id=parent_id,
            chain_id=chain_id,
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
    seed_text = seed_for_lane(lane, seed_context=seed_context)
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
    """Kill a session: reap the PTY, mark terminal, PERSIST DOCS, remove worktree.

    Tolerant: an unknown/already-dead PTY still proceeds to re-status the registry
    record (``STATUS_DONE``) and remove the worktree. ``project_id`` is resolved
    from the registry record when not supplied so the worktree's owning repo can
    be located for a clean ``git worktree remove``. Other sessions are untouched.

    v8 Wave 2 (THE KEYSTONE): BEFORE the worktree is reaped, the session's
    produced documents are persisted into the MAIN project (copied + committed
    via :func:`capture_session_docs` → ``effort_history.persist_session_docs``)
    so they survive the kill, are discoverable from the main folder, and ride
    into later worktrees (which are checked out off main HEAD). This is
    best-effort — a persistence failure never blocks the kill.

    Returns ``{"ok": True, "session_id", "pty_killed", "docs": {...},
    "worktree": {...}}``.
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

    # v8 KEYSTONE: capture + persist the session's produced docs into the MAIN
    # project BEFORE the worktree is reaped (after which they'd be gone forever).
    docs_out = capture_session_docs(session_id, project_id=project_id,
                                    record=record)

    # Remove the per-session worktree (safety-checked, tolerant of already-gone).
    wt_out = _wt.remove_worktree(session_id, project_id=project_id)

    return {
        "ok": True,
        "session_id": session_id,
        "pty_killed": pty_killed,
        "docs": docs_out,
        "worktree": wt_out,
    }


def capture_session_docs(session_id, project_id=None, record=None):
    """Persist a session's produced docs into the MAIN project (before any reap).

    Generalizes the v6 ``capture_plan_set`` capture-before-reap discipline to ALL
    trio docs: resolves the session's registry record (its lane + worktree_path),
    then delegates to :func:`effort_history.persist_session_docs`, which copies
    the produced documents into the main folder, records per-doc efforts so they
    are discoverable, and commits them scoped to the project repo.

    Best-effort and never raises — returns the ``persist_session_docs`` result, or
    a ``{"ok": False, "reason": ...}`` dict when the session/worktree/project
    cannot be resolved (so a missing record can't break the kill path).
    """
    try:
        rec = record if record is not None else _reg.get_session(session_id)
        if rec is None:
            return {"ok": False, "reason": "unknown-session", "persisted": []}
        if project_id is None:
            project_id = rec.get("project_id") or None
        if not project_id:
            return {"ok": False, "reason": "no-project", "persisted": []}
        worktree_path = rec.get("worktree_path", "")
        if not worktree_path:
            return {"ok": False, "reason": "no-worktree", "persisted": []}
        proj = _rnd.get_project(project_id)
        if proj is None:
            return {"ok": False, "reason": "unknown-project", "persisted": []}
        folder = proj.get("folder_path", "")
        if not folder:
            return {"ok": False, "reason": "no-folder", "persisted": []}
        lane = rec.get("lane", "") or ""
        return _eh.persist_session_docs(
            folder, project_id, lane, session_id, worktree_path)
    except Exception:
        return {"ok": False, "reason": "error", "persisted": []}


# ── Auto advance planning → build (v6 Wave 6) ────────────────────────────────
#
# When a PLANNING session reaches a terminal/DONE state via a DELIBERATE
# hard-kill or a RECONCILE-DEAD transition (NOT a keep-alive close, NOT process
# self-exit), and a real MASTER+IMPL plan set is discoverable, the cockpit
# AUTOMATICALLY opens exactly ONE linked build session that executes on that plan.
#
# Trigger semantics are LOCKED (MASTER-PLAN Risks R1/R2):
#   - fires ONLY for a planning-lane session that is TERMINAL/DONE;
#   - exactly ONE build per planning session — IDEMPOTENT on
#     ``parent_session_id`` (a second reconcile/restart never duplicates);
#   - no plan set ⇒ no advance;
#   - the build worktree is PRIMED (HANDOFF.md → the plan docs) and the stage
#     edge is recorded, captured from the discovered plan set BEFORE the planning
#     worktree is reaped (callers pre-capture and pass ``plan_set`` to be safe).
#
# This lives here (not in ``session_registry``) so the registry stays free of a
# terminal_session/handoff import — no import cycle. ``handoff`` imports neither
# module, so importing it here is safe.

#: Planning lane aliases that qualify for the plan→build auto-advance (the trio
#: key ``plan`` and the on-disk dir name ``planning`` both map to a plan stage).
_PLANNING_LANES = frozenset(("plan", "planning"))


def _doc_paths_for_seed(doc_set):
    """Ordered, de-duplicated list of the REAL persisted doc paths in a set.

    Pulls the main-folder-relative POSIX paths a plan/research set carries —
    master + impl first (when present), then the rest of ``doc_rels`` — so the
    generated seed can name the ACTUAL documents the upstream session produced
    (which, after v8 Wave 2 persistence, physically exist in this checkout).
    """
    if not doc_set:
        return []
    primary = []
    for key in ("master_plan_rel", "impl_plan_rel", "report_rel"):
        v = (doc_set.get(key) or "").strip()
        if v and v not in primary:
            primary.append(v)
    ordered = list(primary)
    for r in (doc_set.get("doc_rels") or []):
        r = (r or "").strip()
        if r and r not in ordered:
            ordered.append(r)
    return ordered


def _build_seed_for_plan(plan_set):
    """A build seed listing the REAL plan-doc paths the build executes on.

    Generated from the persisted plan set (v8 Wave 2 — the docs now genuinely
    exist in the build checkout): names :data:`LANE_SKILL['build']` (Foreman),
    lists the actual ``planning/.../IMPLEMENTATION-PLAN.md`` + ``MASTER-PLAN.md``
    (and supporting doc) paths, and a short read-first instruction. ``prime_worktree``
    writes the same paths into HANDOFF.md, which is also referenced here.
    """
    skill = LANE_SKILL.get("build", "Foreman")
    title = (plan_set.get("title") or plan_set.get("plan_dir")
             or "the planning session's plan set")
    docs = _doc_paths_for_seed(plan_set)
    if docs:
        doc_lines = "\n".join("- " + d for d in docs)
        read_first = (
            "Read these documents first, then proceed to execute on them:\n"
            "%s" % doc_lines)
    else:
        read_first = ("The plan docs are referenced in HANDOFF.md in this "
                      "worktree.")
    return (
        "Load the %s skill. You are executing on the plan produced by the "
        "upstream planning session: %s.\n%s\nHANDOFF.md in this worktree also "
        "lists these plan documents." % (skill, title, read_first))


def _build_seed_for_research(research_set):
    """A planning seed listing the REAL research-doc paths the plan builds on.

    The research→plan analog of :func:`_build_seed_for_plan`: names
    :data:`LANE_SKILL['plan']` (Crucible), lists the actual persisted research
    report path(s), and a short read-first instruction. ``research_set`` is a
    plan-set-shaped dict (``doc_rels`` / ``report_rel`` / ``master_plan_rel``)
    or ``None``; with no docs it degrades to a bare Crucible seed reference.
    """
    skill = LANE_SKILL.get("plan", "Crucible")
    docs = _doc_paths_for_seed(research_set)
    if docs:
        doc_lines = "\n".join("- " + d for d in docs)
        read_first = (
            "Read these research documents first, then plan from them:\n%s"
            % doc_lines)
    else:
        read_first = ("The upstream research report is in this worktree "
                      "checkout.")
    return (
        "Load the %s skill. Plan from the upstream research session's findings."
        "\n%s" % (skill, read_first))


def auto_advance_planning_to_build(project_id, planning_session_id,
                                   planning_worktree_path=None, plan_set=None):
    """Auto-open one linked, primed build session from a DONE planning session.

    Fires only when ``planning_session_id`` is a planning-lane session in a
    terminal/DONE status (the deliberate hard-kill or reconcile-dead transition).
    Returns ``None`` (a clean no-op) in every gated-out case:

      - the session is unknown, not a planning lane, or not terminal/DONE;
      - a build session with ``parent_session_id == planning_session_id`` already
        exists (**idempotent** — survives reconcile/restart, never duplicates);
      - no MASTER+IMPL plan set is discoverable (``no plan ⇒ no advance``).

    Otherwise it:
      1. discovers the plan set (or uses the pre-captured ``plan_set`` passed by a
         caller that captured it BEFORE the planning worktree was reaped);
      2. starts a NEW linked build session (``start_session(lane='build',
         parent_session_id=planning_session_id, seed_context=<plan seed>)``) — it
         inherits the planning session's ``chain_id``;
      3. primes the build worktree via :func:`handoff.prime_worktree`
         (HANDOFF.md → the plan docs, which already exist in the checkout);
      4. records the generic stage edge ``plan->build`` via
         :func:`handoff.record_stage_link`.

    Returns the new build registry record on success. Never raises — any failure
    (no project, discovery error, start failure) returns ``None`` so it can be
    called best-effort from the kill / reconcile transition without breaking it.
    """
    try:
        record = _reg.get_session(planning_session_id)
        if record is None:
            return None
        lane = record.get("lane", "")
        if lane not in _PLANNING_LANES:
            return None
        # Only a TERMINAL/DONE planning session advances (the hard-kill /
        # reconcile-dead transition the cockpit owns — never a keep-alive close,
        # never a live/idle session).
        if record.get("status") != _reg.STATUS_DONE:
            return None

        proj = _rnd.get_project(project_id)
        if proj is None:
            return None
        folder = proj.get("folder_path", "")
        if not folder:
            return None

        # IDEMPOTENCY: one build per planning session. If a build already links to
        # this planning session as its parent, do nothing (a second reconcile /
        # restart re-running this must NOT create a duplicate).
        for s in _reg.list_sessions(project_id=project_id):
            if (s.get("lane") == "build"
                    and s.get("parent_session_id") == planning_session_id):
                return None

        # Discover the plan set the build executes on. Prefer a pre-captured one
        # (the caller captured it BEFORE reaping the planning worktree); else
        # discover now (discovery reads the project folder, not the worktree).
        if not plan_set:
            try:
                plan_set = _handoff.discover_recent_plan_set(
                    folder, project_id, source_session_id=planning_session_id)
            except Exception:
                plan_set = None
        if not plan_set:
            return None  # no plan ⇒ no advance

        # Start the linked, seeded build session.
        try:
            build_rec = start_session(
                project_id, "build",
                seed_context=_build_seed_for_plan(plan_set),
                parent_session_id=planning_session_id,
                label="auto · from plan")
        except TerminalSessionError:
            return None

        build_sid = build_rec.get("session_id", "")
        build_wt = build_rec.get("worktree_path", "")

        # Prime the (fresh, never-reaped) build worktree with the plan reference
        # BEFORE anyone reaps anything — captured from the discovered plan set.
        if build_wt:
            try:
                _handoff.prime_worktree(build_wt, plan_set, project_id=project_id)
            except Exception:
                pass
        # Record the generic plan→build stage edge (Wave 2; rescan-durable).
        try:
            _handoff.record_stage_link(
                folder, project_id, planning_session_id, build_sid,
                kind="plan->build")
        except Exception:
            pass
        # Also append the v3 handoff record (parallel list) for the inspection
        # surfaces — best-effort, never blocks the advance.
        try:
            _handoff.record_handoff(folder, project_id, build_sid, plan_set)
        except Exception:
            pass
        return build_rec
    except Exception:
        return None


def reconcile_and_advance(live_session_ids=None, worktree_exists=None,
                          mark_stale_status=_reg.STATUS_DONE):
    """Reconcile the registry, then auto-advance any newly-DONE planning session.

    The cockpit's reconcile-dead path (a managed session whose process is gone):
    re-status the stale sessions, then for each one that was a **planning** session
    just marked terminal/DONE, attempt :func:`auto_advance_planning_to_build`
    (idempotent on ``parent_session_id``, so re-running reconcile never
    duplicates; ``no plan ⇒ no advance``). Best-effort — an advance failure for
    one session never breaks the reconcile or the others.

    Reconcile here defaults ``mark_stale_status`` to ``STATUS_DONE`` (not the
    registry default ``STATUS_IDLE``) because a reconcile-dead transition for the
    cockpit IS the "this session finished" signal that gates the advance. Returns
    ``{"reconcile": <report>, "auto_builds": [<build_record>, ...]}``.
    """
    report = _reg.reconcile(
        live_session_ids=live_session_ids, worktree_exists=worktree_exists,
        mark_stale_status=mark_stale_status, apply=True)
    auto_builds = []
    if mark_stale_status == _reg.STATUS_DONE:
        for sid in report.get("marked", []):
            rec = _reg.get_session(sid)
            if rec is None or rec.get("lane") not in _PLANNING_LANES:
                continue
            pid = rec.get("project_id") or None
            if not pid:
                continue
            try:
                build = auto_advance_planning_to_build(pid, sid)
            except Exception:
                build = None
            if build is not None:
                auto_builds.append(build)
    return {"reconcile": report, "auto_builds": auto_builds}


def capture_plan_set(project_id, planning_session_id):
    """Discover the planning session's plan set NOW (before any reap). or ``None``.

    Helper for the kill path: capture the plan set from the still-intact project
    state BEFORE :func:`kill` reaps the planning worktree, so the subsequent
    :func:`auto_advance_planning_to_build` primes from a known-good plan set even
    if discovery were ever to depend on the worktree. Never raises.
    """
    try:
        proj = _rnd.get_project(project_id)
        if proj is None:
            return None
        folder = proj.get("folder_path", "")
        if not folder:
            return None
        return _handoff.discover_recent_plan_set(
            folder, project_id, source_session_id=planning_session_id)
    except Exception:
        return None


def research_set_for_session(project_id, research_session_id):
    """Build a research-doc set (plan-set-shaped) for a research session, or None.

    The research→plan analog of :func:`capture_plan_set`: resolves the research
    session's persisted member docs (via ``sessions.list_sessions`` over the
    research lane) into a ``{report_rel, doc_rels, plan_dir, title}`` dict so
    :func:`_build_seed_for_research` can name the REAL report path(s). Prefers a
    member whose basename looks like a report; otherwise carries every member
    doc. Returns ``None`` when the session has no resolvable docs. Never raises.
    """
    try:
        proj = _rnd.get_project(project_id)
        if proj is None:
            return None
        folder = proj.get("folder_path", "")
        if not folder:
            return None
        from pathlib import PurePosixPath
        # Prefer the docs this exact session persisted (the effort pointer-records
        # carry the originating ``session_id`` in their ``extra``); fall back to
        # ALL research docs when no session-tagged ones resolve (e.g. brownfield).
        efforts = _eh.list_efforts(folder, project_id, "research")
        tagged = [e for e in efforts
                  if e.get("session_id") == research_session_id
                  and (e.get("artifact_path") or "").strip()]
        pool = tagged or [e for e in efforts
                          if (e.get("artifact_path") or "").strip()]
        doc_rels = []
        report_rel = ""
        for e in pool:
            rel = (e.get("artifact_path") or "").strip().replace("\\", "/")
            if not rel or rel in doc_rels:
                continue
            doc_rels.append(rel)
            name = PurePosixPath(rel).name.lower()
            if not report_rel and ("report" in name or rel.startswith("research/")):
                report_rel = rel
        if not doc_rels:
            return None
        if not report_rel:
            report_rel = doc_rels[0]
        plan_dir = PurePosixPath(report_rel).parent.as_posix()
        if plan_dir in (".", "/"):
            plan_dir = ""
        return {
            "research_session_id": research_session_id,
            "report_rel": report_rel,
            "doc_rels": doc_rels,
            "plan_dir": plan_dir,
            "title": "research findings",
        }
    except Exception:
        return None


def build_research_to_plan_seed(project_id, research_session_id):
    """The generated research→plan seed (Crucible + real report paths), or None.

    Wraps :func:`research_set_for_session` + :func:`_build_seed_for_research`.
    Returns ``None`` when no research docs resolve, so a caller can fall back to
    a summary-only seed. Never raises.
    """
    rset = research_set_for_session(project_id, research_session_id)
    if not rset:
        return None
    return _build_seed_for_research(rset)


def list_sessions(project_id=None, status=None):
    """Thin pass-through to ``session_registry.list_sessions`` (for UI/CLI)."""
    return _reg.list_sessions(project_id=project_id, status=status)


def get_session(session_id):
    """Return the registry record for ``session_id`` (or ``None``)."""
    return _reg.get_session(session_id)
