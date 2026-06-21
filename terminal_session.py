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
import re
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
    import boneyard as _boneyard  # v10 Wave 6 Boneyard capture (stdlib-only; no
    #                              cycle: boneyard imports only paths +
    #                              rnd_registry, lazily summarizer/effort_history)
except Exception:  # pragma: no cover - boneyard is always importable, defensive
    _boneyard = None

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

#: The marker substring the greet line ends with (see :func:`_default_seed_text`:
#: ``✓ <Skill> loaded — what would you like to do?``). The v10 pending-paste flush
#: waits until this appears in the PTY output buffer before pasting the task
#: prompt — that is the "the skill loaded and greeted" signal. Matched
#: case-insensitively on the stable, skill-independent tail of the greet line.
GREET_MARKER = "what would you like to do?"


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


def _resolve_grass_origin_from_chain(parent_id, parent_rec):
    """Return the grass_origin a child should inherit from the chain it joins.

    v10 Wave 4 FIX 1 (D8): the stamp must reach the CHAIN ROOT, not just the
    direct parent. Prefer the direct parent's own stamp (cheapest, common case);
    otherwise walk the chain members ONCE (a single bounded ``chain_members``
    read — no parent-pointer recursion, so it is inherently cycle-safe) and adopt
    any non-empty ``grass_origin`` found among them. Returns ``""`` when no member
    carries one. Best-effort: any registry error degrades to ``""``.
    """
    direct = (parent_rec.get("grass_origin", "") or "") if parent_rec else ""
    if direct:
        return direct
    if not parent_id:
        return ""
    try:
        chain_id = _reg.chain_for(parent_id)
        if not chain_id:
            return ""
        for m in _reg.chain_members(chain_id):
            go = (m.get("grass_origin", "") or "") if isinstance(m, dict) else ""
            if go:
                return go
    except Exception:
        return ""
    return ""


#: Sentinel: ``backend`` not explicitly passed → default to the project's
#: last-used engine (v4 Wave 2).
_UNSET = object()


def start_session(project_id, lane, backend=_UNSET, label="", seed_context=None,
                  parent_session_id=None, paste_prompt=None, grass_origin=None,
                  effort_id=None, effort_managed=False):
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

    v10 Wave 1: ``paste_prompt`` (optional) is the task prompt for a handoff that
    must be DELIVERED BUT NOT SUBMITTED. When provided, phase-1 (the lane
    load+greet seed, ending ``\\n``) is still written so the skill auto-loads and
    greets, but the ``paste_prompt`` is NOT written to the PTY at start — it is
    recorded on the session record as ``pending_paste`` (with
    ``paste_flushed=False``) and later written to the PTY input WITHOUT a trailing
    newline exactly once, after the greet is observed, by
    :func:`_flush_pending_paste` (wired into the first ``read_since``/``attach``).
    With no ``paste_prompt`` the behavior is exactly as v9 (the regression-guarded
    back-compat path) — ``seed_context`` continues to fold onto the seed and is
    auto-submitted as today.

    v10 Wave 4: ``grass_origin`` (optional) is the originating grass idea id for a
    grass→project lineage chain (D8). When passed it is stamped on the new
    session's registry record; when omitted it is INHERITED from the parent's
    record (so once a chain is grass-stamped — e.g. by ``export_grass_to_project``
    on the dev session — every downstream session in that chain carries the
    origin and can trace back to the idea). Empty for any non-grass chain (the
    default). It is just an idea id — SAFE to carry into the board / chain
    projections (never worktree_path/branch).

    v12 Wave 1: ``effort_id`` (optional) is the stable id of the EFFORT this
    session belongs to. When given the new record inherits it (a context-relief
    continuation joins the SAME effort); when omitted the record's
    ``effort_id`` defaults to its own session_id (a fresh effort). ``effort_managed``
    (default False) is the v12 discriminator — passed True ONLY by the v12
    entrypoints; every existing caller leaves it False, so there is NO behavior
    change for them (both default to today's behavior).

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
    parent_rec = None
    if parent_id:
        parent_rec = _reg.get_session(parent_id)
        chain_id = _reg.chain_for(parent_id)
        if not chain_id:
            parent_id = ""  # unknown parent → start a fresh chain
            parent_rec = None

    # v10 Wave 4 (D8): grass→project lineage. The new session's ``grass_origin``
    # is the explicit value if passed, ELSE INHERITED from anywhere in the chain
    # it is joining (so once an exported/promoted grass chain is stamped, EVERY
    # downstream session in it traces back to the idea — even when the direct
    # parent's own record happens to carry an empty stamp but a chain ancestor
    # carries it). Empty for any non-grass chain. Cheap + cycle-safe: a single
    # bounded read of the chain members (no parent-pointer recursion).
    origin = (grass_origin or "")
    if not origin and parent_rec is not None:
        origin = _resolve_grass_origin_from_chain(parent_id, parent_rec)

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
            grass_origin=origin,
            # v12 Wave 1: inherit the effort id if given (a context-relief
            # continuation joins the SAME effort), else default to own sid;
            # ``effort_managed`` stored exactly as passed (the v12 discriminator).
            effort_id=(effort_id or sid),
            effort_managed=bool(effort_managed),
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

    # v10 Wave 1: record the task prompt as a PENDING PASTE — held UNSENT in the
    # PTY input until the user presses Enter. It is NOT written here; it is
    # delivered exactly once, after the greet, by :func:`_flush_pending_paste`
    # (wired into the first read_since/attach). Recorded with paste_flushed=False
    # so the flush guard knows it is still pending. With no paste_prompt this is
    # skipped entirely (the v9 back-compat path is untouched).
    pending = (paste_prompt or "")
    if pending:
        try:
            record = _reg.update_session(
                sid, pending_paste=pending, paste_flushed=False)
        except Exception:
            pass

    # v4 Wave 2: remember the engine this session chose so the NEXT session for
    # this project defaults to it. Best-effort (never fails a live session).
    set_last_engine_for_project(project_id, backend)
    return record


def _flush_pending_paste(session_id):
    """Write a session's PENDING task prompt to the PTY input, UNSENT, once (v10 W1).

    The v10 "paste-NOT-submit" handoff: a session started with ``paste_prompt``
    holds that prompt on its record as ``pending_paste`` (``paste_flushed=False``)
    without writing it. THIS function delivers it — exactly once, after the greet
    is observed — by writing it to the PTY **without a trailing newline** so it
    sits in the input line UNSENT until the user presses Enter.

    Trigger ("greet observed") — the SOUND test (fixes the premature-flush bug):
    the greet line ``✓ <Skill> loaded — what would you like to do?`` is quoted
    VERBATIM inside the seed text Anchor writes at start (see
    :func:`_default_seed_text`), and the PTY echoes stdin — so :data:`GREET_MARKER`
    is already in the buffer from the moment the seed is ECHOED, BEFORE the model
    loads the skill or actually greets. A plain substring/`in` test therefore
    flushes prematurely (Master-Plan R1). Instead we count marker OCCURRENCES and
    require MORE than the seed text itself contains:

      base    = number of marker occurrences in the recorded ``seed_text`` (the
                exact bytes written at start; the echo contributes exactly ``base``)
      greeted = the buffer's marker count is STRICTLY GREATER than ``base``
                (the MODEL's real greet adds at least one more occurrence)

    There is intentionally NO ``len(text) > len(seed_text)`` fallback — that fired
    on almost any output and was the second half of the premature-flush defect.
    If the seed was env-overridden (``ANCHOR_TERMINAL_SEED``) to a text with ZERO
    marker occurrences, then ``base == 0`` and any appearance of the marker (from a
    model greet) triggers — acceptable. If such an overridden seed ALSO omits the
    marker AND the model greet won't contain it, the paste simply STAYS pending
    (honest: we never fabricate a greet we didn't observe).

    Real-ConPTY caveat: stdin echo may carry interleaved ANSI control codes, so
    counting the stable, skill-independent marker SUBSTRING tolerates that far
    better than positional/line matching.

    IDEMPOTENT + cheap to call on every read/attach:
      - no record / no ``pending_paste`` / already ``paste_flushed`` → no-op;
      - the greet has NOT been observed yet → no-op (left pending for a later read);
      - on a successful CLAIM it sets ``paste_flushed=True`` and clears
        ``pending_paste`` (so a second call never re-emits).

    Concurrency (Defect 2 — TOCTOU): under ``ThreadingHTTPServer`` two concurrent
    ``read_since``/``attach`` calls could both pass the guard and both write a
    double paste. The check-and-claim is therefore done as a compare-and-set under
    the process-wide :data:`paths.WRITE_LOCK` (a reentrant ``RLock`` — the SAME
    lock ``session_registry.update_session`` takes, so re-acquiring it for the
    persist can't self-deadlock). The winning thread CLAIMS the paste (sets
    ``paste_flushed=True`` + clears ``pending_paste`` + persists) BEFORE releasing
    the lock and BEFORE writing the bytes to the PTY; a losing/late thread sees
    ``paste_flushed`` already True and no-ops. (Rare tradeoff: if the PTY write
    fails AFTER the claim, the paste is lost rather than re-emitted — once-only
    dominates; we log a best-effort warning.)

    Never raises — a missing/dead PTY or a persist failure simply leaves the paste
    pending (it can be retried on the next read) without disturbing the caller.
    Returns ``True`` iff the paste was claimed+written on THIS call, else ``False``.
    """
    try:
        rec = _reg.get_session(session_id)
    except Exception:
        return False
    if rec is None:
        return False
    if not (rec.get("pending_paste") or "") or rec.get("paste_flushed"):
        return False

    # Has the greet been observed? Read the live PTY output buffer (cursor 0).
    try:
        out = _pty.read_since(session_id, 0)
    except _pty.UnknownSession:
        return False  # no live PTY (e.g. after a restart) — leave it pending
    except Exception:
        return False
    text = (out.get("text") or "") if isinstance(out, dict) else ""

    # Distinguish the ECHOED seed from a REAL model greet by counting marker
    # occurrences beyond what the seed text itself contributes (see docstring).
    marker = GREET_MARKER.lower()
    seed_text = rec.get("seed_text") or ""
    base = seed_text.lower().count(marker)
    if text.lower().count(marker) <= base:
        return False  # still waiting on the model's actual greet — stay pending

    # Compare-and-set the claim under WRITE_LOCK (reentrant; same lock
    # update_session takes). Re-load + re-check inside the lock so exactly ONE
    # concurrent thread wins; claim (persist paste_flushed=True + clear pending)
    # BEFORE releasing the lock and BEFORE the PTY write, so only the winner
    # proceeds to write.
    with _paths.WRITE_LOCK:
        try:
            rec = _reg.get_session(session_id)
        except Exception:
            return False
        if rec is None:
            return False
        pending = rec.get("pending_paste") or ""
        if not pending or rec.get("paste_flushed"):
            return False  # a concurrent thread already claimed it
        try:
            _reg.update_session(
                session_id, paste_flushed=True, pending_paste="")
        except Exception:
            return False  # couldn't claim → leave it for a later read

    # Strip a trailing newline so a prompt that itself ends in "\n"/"\r\n" (e.g. a
    # Wave-2 NEXT-PROMPT.md body) can NEVER auto-submit — the paste must land in
    # the input line UNSENT.
    pending = pending.rstrip("\r\n")

    # Deliver the prompt to the PTY input WITHOUT a trailing newline (UNSENT).
    # We have already claimed the paste, so a write failure here loses this paste
    # (accepted tradeoff: once-only dominates double-paste). Log best-effort.
    try:
        _pty.write(session_id, pending)
    except Exception as exc:
        try:
            import sys as _sys
            print("warning: pending-paste claimed but PTY write failed for "
                  "%s: %s" % (session_id, exc), file=_sys.stderr)
        except Exception:
            pass
        return False
    return True


def queue_paste(session_id, text):
    """Queue a PENDING task prompt onto an ALREADY-LIVE session (v10 W5).

    The v10 "paste-NOT-submit" handoff normally records ``pending_paste`` at
    :func:`start_session`. But when a *bare* develop session already exists (e.g.
    the user clicked "Plan"/Develop on a grass idea FIRST, minting a plan dev
    session with NO handoff), a later research→plan *advance* must still deliver
    the generated handoff prompt onto that existing session — WITHOUT re-starting
    it. This sets ``pending_paste=<text>`` + ``paste_flushed=False`` on the record
    (reusing the Wave-1 plumbing) so the SAME :func:`_flush_pending_paste` path
    delivers it UNSENT on the next read/attach. The session has already greeted, so
    the greet-marker-count guard is already satisfied → it flushes immediately,
    unsent.

    SAFETY (no double-paste): the CALLER must only invoke this on a session that
    has NEITHER a pending paste NOR an already-flushed one (``not pending_paste and
    not paste_flushed``) — a session that already carries a handoff (pending,
    pre-flush) or already received one (flushed) must NOT get a second. This helper
    re-checks that guard under the registry semantics and refuses otherwise.

    Returns ``True`` iff the paste was queued on THIS call, else ``False`` (unknown
    session, empty text, or the guard refused). Never raises.
    """
    text = (text or "")
    if not text.strip():
        return False
    try:
        rec = _reg.get_session(session_id)
    except Exception:
        return False
    if rec is None:
        return False
    # Guard against double-paste / re-advance: refuse if a handoff is already
    # pending (pre-flush) or already delivered (flushed).
    if (rec.get("pending_paste") or "") or rec.get("paste_flushed"):
        return False
    try:
        _reg.update_session(
            session_id, pending_paste=text, paste_flushed=False)
    except Exception:
        return False
    return True


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
    # v10 Wave 1: if a task prompt is pending for this session and the greet has
    # been observed, paste it (unsent) before replaying the buffer so the
    # reattaching client sees the prompt sitting in the input line. Idempotent +
    # cheap; a no-op when nothing is pending or the greet hasn't appeared yet.
    _flush_pending_paste(session_id)
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
    # v10 Wave 1: the first read that observes the greet flushes a pending task
    # prompt to the PTY input (unsent). Idempotent + cheap; a no-op when nothing
    # is pending. Done BEFORE the read so the freshly-pasted bytes (which the
    # stub echoes) surface in THIS read's output.
    _flush_pending_paste(session_id)
    try:
        return _pty.read_since(session_id, cursor)
    except _pty.UnknownSession:
        return {"ok": False, "reason": "unknown-session"}


def kill(session_id, project_id=None, _record_boneyard=True):
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

    ``_record_boneyard`` (PRIVATE, default ``True``): when ``False`` the v10 W6
    ``killed`` Boneyard capture is SUPPRESSED. :func:`delete_session` passes
    ``False`` when it kills a still-live session as part of a delete — the
    ``deleted`` entry is the canonical record for a delete, so a kill-driven
    ``killed`` entry would be a spurious DUPLICATE. Doc PERSISTENCE
    (``capture_session_docs``) still runs regardless — only the Boneyard record is
    suppressed, so the subsequent ``deleted`` entry's ``doc_rels`` are populated.

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

    # v10 Wave 6 — Boneyard capture (D3 source "killed"). A hard-kill is the
    # deliberate "I'm done / discarding" action; if this session PRODUCED material
    # (persisted docs), index it in the project's Boneyard. This is purely ADDITIVE
    # — the session's normal finished tile/record is unaffected — and BEST-EFFORT:
    # a Boneyard failure must NEVER break the kill path. SUPPRESSED when this kill
    # is part of a delete_session (the canonical "deleted" entry is recorded there;
    # a "killed" entry too would be a spurious duplicate for ONE delete).
    if _record_boneyard:
        _capture_killed_to_boneyard(session_id, project_id, record, docs_out)

    return {
        "ok": True,
        "session_id": session_id,
        "pty_killed": pty_killed,
        "docs": docs_out,
        "worktree": wt_out,
    }


def _capture_killed_to_boneyard(session_id, project_id, record, docs_out):
    """Index a killed session in the Boneyard iff it produced material (W6).

    BEST-EFFORT — swallows every error so a Boneyard failure can never break the
    kill path. References the docs the v8 keystone just persisted (no copy).
    """
    if _boneyard is None:
        return
    try:
        rec = record if record is not None else _reg.get_session(session_id)
        if rec is None:
            return
        if project_id is None:
            project_id = rec.get("project_id") or None
        if not project_id:
            return
        proj = _rnd.get_project(project_id)
        folder = (proj or {}).get("folder_path", "") if proj else ""
        if not folder:
            return
        lane = rec.get("lane", "") or ""
        # Prefer the docs THIS kill just persisted; fall back to the v8 join.
        doc_rels = list((docs_out or {}).get("persisted", []) or [])
        entry = _boneyard.build_session_entry(
            folder, project_id, lane, session_id,
            source=_boneyard.SOURCE_KILLED, record=rec,
            doc_rels=(doc_rels or None))
        # Only record a killed entry when the session actually produced material.
        if entry.get("doc_rels"):
            _boneyard.record_entry(folder, project_id, entry)
    except Exception:
        return


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


# ── True session delete (v9 Wave 1) ──────────────────────────────────────────
#
# DELETE is DISTINCT from KILL (v8). KILL ends a *running* session: it reaps the
# PTY, persists the produced docs into the main folder, removes the worktree, and
# marks the registry record DONE — the record (and its board tile) PERSIST so the
# work is resumable. DELETE *removes the session from Anchor entirely*: the
# registry record is hard-deleted (so it never re-surfaces on a reload), and the
# session's effort pointer-records / index entries / cached summary are removed.
#
# Option A (LOCKED): the produced DOCUMENTS are KEPT on disk — only Anchor's
# pointer-records + cache (which merely reference them) are dropped. So the
# committed plan/research/build files stay in the project folder/git.

def delete_session(session_id, project_id=None):
    """Permanently delete a managed session from Anchor (v9 Wave 1).

    Distinct from :func:`kill`: this REMOVES the registry record (so the tile is
    gone and STAYS gone across a reload — ``term_sessions``/the board read the
    registry, which no longer holds it) AND removes the session's lane effort
    pointer-records / index entries / cached summary
    (``effort_history.delete_session_efforts``). The produced DOCUMENTS are KEPT
    on disk (Option A) — only the Anchor pointer-records + cache are dropped.

    If the session is still LIVE it is :func:`kill`-ed first (reap PTY + persist
    docs + remove worktree), so a running session can be deleted safely.

    Best-effort, IDEMPOTENT (a second delete is a clean no-op), and never raises.
    Returns ``{"ok": True, "deleted": bool, "session_id", "killed": bool,
    "efforts": {...}}`` where ``deleted`` is whether a registry record was
    removed (False if the id was already unknown).
    """
    rec = _reg.get_session(session_id)
    if project_id is None and rec:
        project_id = rec.get("project_id") or None
    lane = (rec.get("lane") if rec else "") or ""

    killed = False
    # If the session is still live (a running PTY / RUNNING status), kill it first
    # so the PTY + worktree are reaped and its docs are persisted before we drop
    # the record. Tolerate any failure — delete must still proceed. We SUPPRESS the
    # kill's "killed" Boneyard capture (``_record_boneyard=False``): a delete of a
    # live session must yield exactly ONE Boneyard entry — the canonical "deleted"
    # entry recorded below — not a "killed" + "deleted" pair. Doc PERSISTENCE still
    # runs in kill, so the "deleted" entry's doc_rels are populated.
    try:
        if rec is not None and (
                session_id in set(_pty.live_sessions())
                or rec.get("status") == _reg.STATUS_RUNNING):
            kill(session_id, project_id=project_id, _record_boneyard=False)
            killed = True
    except Exception:
        killed = False

    # Hard-delete the registry record (the durability of "stays gone": the board
    # + term_sessions read the registry, so a removed record never re-surfaces).
    try:
        deleted = bool(_reg.remove_session(session_id))
    except Exception:
        deleted = False

    # Remove the lane effort pointer-records / index entries / cached summary —
    # but KEEP the produced documents on disk (Option A). Resolve the folder.
    efforts_out = {"ok": False, "reason": "unresolved"}
    try:
        if project_id and lane:
            proj = _rnd.get_project(project_id)
            folder = (proj or {}).get("folder_path", "") if proj else ""
            if folder:
                # v10 Wave 6 (D10) — CAPTURE the Boneyard entry BEFORE
                # delete_session_efforts drops the pointer-records: the entry is
                # built from efforts_for_session_id (the docs the session
                # produced) + the cached summary, which only exist WHILE the
                # pointer-records are still present. After this call the efforts
                # are gone — the Boneyard is the deleted session's ONLY remaining
                # home (the docs stay on disk, Option A). BEST-EFFORT.
                _capture_deleted_to_boneyard(folder, project_id, lane,
                                             session_id, rec)
                efforts_out = _eh.delete_session_efforts(
                    folder, project_id, lane, session_id)
    except Exception:
        efforts_out = {"ok": False, "reason": "error"}

    return {
        "ok": True,
        "deleted": deleted,
        "session_id": session_id,
        "killed": killed,
        "efforts": efforts_out,
    }


def _capture_deleted_to_boneyard(folder, project_id, lane, session_id, record):
    """Index a v9-DELETED session in the Boneyard (D3 source "deleted") — W6.

    MUST be called BEFORE ``effort_history.delete_session_efforts`` drops the
    pointer-records (D10): the entry's ``doc_rels`` are resolved from
    ``efforts_for_session_id`` (which only returns docs WHILE the pointer-records
    exist). Unlike a kill, the deleted session's tile + efforts are about to be
    gone, so the Boneyard is its ONLY remaining home — we record it even if the
    docs list is empty (the entry still preserves the session's identity/summary).
    BEST-EFFORT — swallows every error so it can never break the delete path.
    """
    if _boneyard is None:
        return
    try:
        entry = _boneyard.build_session_entry(
            folder, project_id, lane, session_id,
            source=_boneyard.SOURCE_DELETED, record=record)
        _boneyard.record_entry(folder, project_id, entry)
    except Exception:
        return


def cleanup_ghost_sessions(project_id):
    """Delete a project's empty GHOST sessions (v9 Wave 1).

    A *ghost* is a registry session record in a terminal/non-running state
    (DONE/FAILED/IDLE — never a live RUNNING one) that has NO effort pointer-
    records tied to it in its lane (it produced nothing Anchor recorded). These
    accumulate as phantom tiles. This sweeps them: for each candidate it confirms
    ``efforts_for_session_id`` is empty in its lane, then :func:`delete_session`-s
    it (record + any cache). RUNNING sessions and sessions WITH efforts are left
    untouched.

    Best-effort, never raises. Returns ``{"ok": True, "removed": [session_id...]}``.
    """
    removed = []
    try:
        proj = _rnd.get_project(project_id)
        folder = (proj or {}).get("folder_path", "") if proj else ""
        for rec in _reg.list_sessions(project_id=project_id):
            try:
                if rec.get("status") == _reg.STATUS_RUNNING:
                    continue  # never sweep a live session
                sid = rec.get("session_id")
                lane = (rec.get("lane") or "")
                has_efforts = False
                if folder and lane:
                    try:
                        has_efforts = bool(_eh.efforts_for_session_id(
                            folder, project_id, lane, sid))
                    except Exception:
                        has_efforts = False
                if has_efforts:
                    continue  # not a ghost — it produced recorded work
                delete_session(sid, project_id=project_id)
                removed.append(sid)
            except Exception:
                continue
    except Exception:
        pass
    return {"ok": True, "removed": removed}


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
         parent_session_id=planning_session_id, paste_prompt=<plan prompt>)``) — it
         inherits the planning session's ``chain_id``; the build prompt is delivered
         as a v10 PENDING PASTE (held unsent until the user looks), never
         auto-submitted, on this unattended path too;
      3. primes the build worktree with BOTH artifacts via
         :func:`handoff.prime_worktree` (HANDOFF.md → the plan docs) AND
         :func:`handoff.write_next_prompt` (NEXT-PROMPT.md → the reviewable prompt);
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

        # v11 Wave 3 — route the plan→build prompt + persist + handoff materials
        # through the SHARED keystone (:func:`prepare_stage_handoff`) so this path
        # is consistent with research→plan and equally verified, AND so the plan-set
        # DISCOVERY below sees the planning session's just-persisted docs. The
        # keystone is called BEFORE discovery because the persist is what makes the
        # plan set discoverable on the paths where the docs are NOT already on main
        # (notably the reconcile-dead transition, which marks the session DONE
        # WITHOUT running kill()'s persist; the hard-kill path already persisted in
        # kill() so this is an idempotent, content-addressed no-op re-capture). The
        # keystone:
        #   - PERSISTS the planning session's produced docs (best-effort, idempotent;
        #     no-ops safely if the worktree is already reaped — then the docs are
        #     already on main from kill());
        #   - BUILDS the build prompt via handoff.build_next_stage_prompt('build'),
        #     which discovers the plan set and reuses ``_build_seed_for_plan`` (the
        #     real plan-doc paths) AND applies ``clean_paste_opener`` — so the
        #     redundant "Load the Foreman skill." opener is already stripped;
        #   - RESOLVES doc_rels + skill (Foreman) + the planning session's cached
        #     summary for a shared HANDOFF.md.
        hk = prepare_stage_handoff(project_id, planning_session_id, "build")

        # Discover the plan set the build executes on. Prefer a pre-captured one
        # (the caller captured it BEFORE reaping the planning worktree); else
        # discover now — AFTER the keystone persisted the planning docs into main,
        # so they are discoverable on every path. ``prime_worktree`` below uses the
        # plan set for the richer plan-set-specific HANDOFF.md.
        if not plan_set:
            try:
                plan_set = _handoff.discover_recent_plan_set(
                    folder, project_id, source_session_id=planning_session_id)
            except Exception:
                plan_set = None
        if not plan_set:
            return None  # no plan ⇒ no advance
        # The task prompt is delivered as a PENDING PASTE (held in the build PTY
        # input UNSENT until the user presses Enter) — NOT folded into the
        # auto-submitted seed. The phase-1 load+greet seed still fires (Foreman
        # auto-loads + greets); the build prompt sits pending. This holds for the
        # UNATTENDED reconcile-dead path too: the build greets and waits — nothing
        # auto-submits — until the first attach flushes the paste unsent. Honest
        # fallback to the plan-set seed if the keystone prompt is empty (no docs).
        next_prompt = (hk.get("prompt") or "").strip()
        if not next_prompt:
            next_prompt = _handoff.clean_paste_opener(
                _build_seed_for_plan(plan_set))

        # Start the linked build session: skill auto-loads/greets (phase-1), the
        # build prompt is recorded as pending_paste (delivered unsent after greet).
        try:
            build_rec = start_session(
                project_id, "build",
                paste_prompt=next_prompt,
                parent_session_id=planning_session_id,
                label="auto · from plan")
        except TerminalSessionError:
            return None

        build_sid = build_rec.get("session_id", "")
        build_wt = build_rec.get("worktree_path", "")

        # Prime the (fresh, never-reaped) build worktree with BOTH artifacts BEFORE
        # anyone reaps anything: the structural HANDOFF.md (plan doc paths) and the
        # reviewable NEXT-PROMPT.md (the exact pending-paste prompt). Captured from
        # the discovered plan set. The plan→build HANDOFF.md is written by
        # ``prime_worktree`` (the RICHER plan-set-specific form: titled Master plan /
        # Implementation plan / supporting docs) — kept verbatim (no v10 regression);
        # the shared ``write_handoff_md`` generalizes ONLY the no-plan-set case
        # (research→plan), so it is NOT layered here where prime_worktree already
        # wrote the canonical plan-set HANDOFF.md (it would otherwise clobber it).
        # The shared keystone's persist (above) is what makes prime_worktree's
        # referenced plan docs genuinely exist in this checkout.
        if build_wt:
            try:
                _handoff.prime_worktree(build_wt, plan_set, project_id=project_id)
            except Exception:
                pass
            try:
                _handoff.write_next_prompt(build_wt, next_prompt)
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


# ── v11 Wave 1: the shared stage-handoff keystone ────────────────────────────
#
# THE BUG v11 fixes: ``advance_session`` (research→plan) never persisted the
# LIVE source research session's produced docs. Persistence
# (``effort_history.persist_session_docs`` via :func:`capture_session_docs`) ran
# ONLY in :func:`kill` and in ``finish_to_build`` (plan→build). So advancing a
# still-LIVE research session left its reports in the worktree, unpersisted →
# :func:`research_set_for_session` (reads only session-tagged persisted efforts)
# returned None → ``handoff.build_next_stage_prompt`` fell to the bare fallback
# with no doc paths, and no HANDOFF.md was written.
#
# ``prepare_stage_handoff`` is the ONE shared helper that fixes this at the root:
# it PERSISTS the source stage's produced docs FIRST (best-effort, idempotent,
# does NOT reap the worktree — works whether the source is live or done), THEN
# builds the real handoff prompt (which now finds the just-persisted,
# session-tagged docs), resolves the handoff materials (doc_rels + skill +
# upstream summary), and kicks off a non-blocking background source-stage summary.
# Wave 2/3 wire the advance/finish paths through it; this wave is backend-only.

def _summary_text_from_cached(cached):
    """A short plain-text digest from a cached structured summary, or ``""``.

    Prefers the cached ``markdown`` (rendered summary body); falls back to the
    joined grounded ``claims``; honest ``""`` when nothing is cached/usable.
    Never raises.
    """
    if not isinstance(cached, dict):
        return ""
    try:
        md = (cached.get("markdown") or "").strip()
        if md:
            return md
        claims = cached.get("claims") or []
        joined = "\n".join(
            str(c.get("text") if isinstance(c, dict) else c).strip()
            for c in claims
            if (c.get("text") if isinstance(c, dict) else c))
        return joined.strip()
    except Exception:
        return ""


def _trigger_background_source_summary(folder, project_id, lane, session_id):
    """Best-effort, NON-BLOCKING: spin a daemon thread to summarize the source
    session so the upstream digest is available, without blocking the advance.

    Mirrors the ``anchor_gui`` summarize-on-finish mechanism (daemon thread +
    idempotent cache skip) but lives here so the keystone never imports
    ``anchor_gui`` (which would be a module cycle: ``anchor_gui`` imports
    ``terminal_session``). Skips when a cache already exists; a failed generation
    never poisons the cache (the summarizer surfaces ``error`` without writing).
    Any failure — including a missing summarizer/runner — is swallowed; the
    digest is a nice-to-have, never a blocker.

    GATED on the SAME proactive-summary signal as ``anchor_gui`` (the
    ``ANCHOR_PROACTIVE_SUMMARY`` env flag) — read directly here so we never import
    ``anchor_gui`` (the cycle). When proactive summary is DISABLED (the default in
    every unit-test / healthcheck context), this is a hard NO-OP: no daemon thread
    is spawned, so a stubbed context NEVER spawns a live ``claude`` for the digest.
    The digest's absence does NOT change ``prepare_stage_handoff`` correctness —
    that function still persists docs + builds the real prompt regardless.
    """
    if not (folder and project_id and lane and session_id):
        return
    # No-op unless proactive generation is enabled (same gate anchor_gui uses;
    # read the env flag directly to avoid the anchor_gui import cycle). Tests and
    # the 5 AM healthcheck leave this OFF, so the background summary never runs and
    # no live claude is ever spawned from a stubbed context.
    if (os.environ.get("ANCHOR_PROACTIVE_SUMMARY", "").strip().lower()
            not in ("1", "true", "yes", "on")):
        return

    # Dedup at the root (v11.1 FIX): when the SOURCE session is already TERMINAL
    # (DONE / FAILED — i.e. it's being/was finished, e.g. a hard-killed planning
    # session that auto-advances to build), its summary is owned by the canonical
    # summarize-on-finish hook (``anchor_gui._trigger_session_summary_on_finish``).
    # The keystone background summary must NOT double up on it (two model calls
    # for the same session + racy idempotency). The keystone summary's value is for
    # a LIVE source being advanced from (the normal research→plan advance + the
    # v11.1 conversation-transcript case, where the research source stays RUNNING) —
    # there it remains the only trigger and fires as before. Best-effort: a status
    # read failure falls through to the prior behavior (fire the summary).
    try:
        _src_rec = _reg.get_session(session_id)
        if isinstance(_src_rec, dict):
            _src_status = (_src_rec.get("status") or "").strip().lower()
            if _src_status in (_reg.STATUS_DONE, _reg.STATUS_FAILED):
                return
    except Exception:
        pass

    def _run():
        try:
            import summarizer as _sm  # lazy: no cycle, optional at import time
            import effort_history as _eh_local
            # No os.environ mutation: the gate above means this only runs in
            # PRODUCTION (proactive enabled), where ANCHOR_RUNNER_CMD is already
            # the real configured value in the ambient process env. The summarizer
            # resolves the runner from that env, so the daemon thread relies on it
            # as-is — never writing process-global env from a daemon thread.
            store_lane = _eh_local._resolve_subdir(lane)
            # Idempotent: a session that already has a cache is left alone.
            try:
                if _sm.load_cached(folder, project_id, store_lane,
                                   session_id) is not None:
                    return
            except Exception:
                pass
            # Tie the summary to the docs the session PRODUCED (the keystone just
            # persisted them tagged with this session_id).
            try:
                efforts = _eh_local.efforts_for_session_id(
                    folder, project_id, store_lane, session_id)
            except Exception:
                efforts = []
            session = {"session_id": session_id, "lane": lane,
                       "efforts": efforts}
            _sm.summarize_session(folder, project_id, store_lane, session)
        except Exception:
            pass

    try:
        import threading
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


# v11.1 Wave 1 (D3/D4): snapshot a CONVERSATION-only research session.
#
# THE GAP v11.1 fixes: a research (or plan) session whose work lived only as a
# terminal CONVERSATION (the model answered in the PTY, wrote NO file) produces no
# document-classified doc → the handoff's ``doc_rels`` is empty → grass hard-
# refuses and the non-grass advance opens with a misleading prompt. The
# conversation is lost — only files survived.
#
# When the initial ``capture_session_docs`` persist yields ZERO docs (D4 — only
# the gap case), the keystone SYNCHRONOUSLY snapshots the source session's PTY
# transcript into ``<lane>/<short-sid>-transcript.md`` (an ``_is_document_rel``-
# valid ``.md`` under the lane dir), cleaned of the seed/greet boilerplate + ANSI
# control sequences and capped to a sane tail. Re-running ``capture_session_docs``
# then persists + session-tags it, so ``research_set_for_session`` finds it and
# the REAL doc-referencing prompt engages, and the transcript rides into the next
# worktree (off main HEAD). Best-effort + idempotent (deterministic filename,
# content-addressed persist); a snapshot failure NEVER breaks the advance.

#: Strip ANSI / control escape sequences (CSI / OSC / single-char escapes).
#:
#: A REAL ``claude`` ConPTY stream is a TUI: SGR colors, CSI cursor moves +
#: erase-line/screen, OSC title sequences, plus DEC private-mode toggles
#: (``\x1b[?25l`` etc.). The pre-v11.1 regex only covered the common CSI/OSC
#: forms; this one broadens to ALL CSI (any params/intermediates/final), both OSC
#: terminators (BEL ``\x07`` and ST ``\x1b\\``), the standalone ``\x1b(`` charset
#: selects, and stray control bytes (KEEP ``\t`` ``\n`` ``\r`` — ``\r`` is needed
#: for the in-place redraw collapse below, the others are real layout).
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"        # CSI  \x1b[ ... final byte (incl. ?, =, >)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC  \x1b] ... BEL / ST
    r"|\x1b[PX^_].*?(?:\x07|\x1b\\)"  # DCS/PM/APC/SOS strings ... ST/BEL
    r"|\x1b[()][0-9A-Za-z]"           # charset designation \x1b( B  etc.
    r"|\x1b[@-Z\\-_]"                 # other two-char escapes (RIS, IND, NEL…)
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"  # stray control chars (keep \t \n \r)
)

#: The box-drawing input chrome ``claude`` draws around the prompt line
#: (``╭───╮`` ``│ > … │`` ``╰───╯``) plus the bottom status bar. A line that is
#: DOMINATED by box-drawing glyphs is interface chrome, not dialogue.
_BOX_DRAW_CHARS = "─━│┃┄┅┆┇┈┉┊┋┌┍┎┏┐┑┒┓└┕┖┗┘┙┚┛├┝┞┟┠┡┢┣┤┥┦┧┨┩┪┫┬┭┮┯┰┱┲┳┴┵┶┷┸┹┺┻┼┽┾┿╀╁╂╃╄╅╆╇╈╉╊╋╌╍╎╏═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬╭╮╯╰"
_BOX_DRAW_SET = set(_BOX_DRAW_CHARS)

#: Spinner / status glyphs ``claude`` redraws on the working line (braille dots
#: + a few common spinner frames). A line that is only spinner chrome (a spinner
#: glyph + "esc to interrupt"-style text + tokens/elapsed) is transient status.
_SPINNER_CHARS = "⠀⠁⠂⠃⠄⠅⠆⠇⠈⠉⠊⠋⠌⠍⠎⠏⠐⠑⠒⠓⠔⠕⠖⠗⠘⠙⠚⠛⠜⠝⠞⠟⠠⠡⠢⠣⠤⠥⠦⠧⠨⠩⠪⠫⠬⠭⠮⠯⠰⠱⠲⠳⠴⠵⠶⠷⠸⠹⠺⠻⠼⠽⠾⠿⣀⣄⣆⣇⣦⣧⣷⣿◐◓◑◒◴◵◶◷⣾⣽⣻⢿⡿⣟⣯⣷✶✻✽✢·∗"
_SPINNER_SET = set(_SPINNER_CHARS)
#: Status-line phrases ``claude`` shows on the spinner / working line.
_STATUS_PHRASE_RE = re.compile(
    r"esc to interrupt|ctrl\+|tokens?\b|press up|\bthinking\b|\besc\b",
    re.IGNORECASE,
)

#: Cap the snapshot — keep a HEAD (the research framing/question) AND a TAIL (the
#: latest findings); the middle is what gets dropped when oversized.
_TRANSCRIPT_MAX_CHARS = 32768   # ~32 KB total budget
_TRANSCRIPT_HEAD_CHARS = 12288  # ~12 KB of the opening (the framing survives)
_TRANSCRIPT_TAIL_CHARS = 20480  # ~20 KB of the latest discussion


def _collapse_cr_redraws(text):
    """Collapse carriage-return in-place redraws to each line's FINAL frame.

    A real terminal stream redraws the status/spinner line hundreds of times by
    emitting ``...\\r...\\r...`` with NO newline — each ``\\r`` returns the cursor
    to column 0 so subsequent chars OVERWRITE the line in place. Naively
    ``text.replace("\\r", "\\n")`` would explode every redraw frame into its own
    line (the pre-fix bug). Instead, process line-by-line: within a logical line
    (split on ``\\n``), apply ``\\r`` as an in-place cursor reset and emit only the
    LAST rendered state. ``\\r\\n`` is normalized first so a real CRLF stays one
    line break. Stdlib only.
    """
    text = text.replace("\r\n", "\n")
    out_lines = []
    for logical in text.split("\n"):
        if "\r" not in logical:
            out_lines.append(logical)
            continue
        # Render the segments separated by \r as overwrites onto one line buffer.
        rendered = ""
        for seg in logical.split("\r"):
            if len(seg) >= len(rendered):
                rendered = seg
            else:
                # Shorter segment overwrites the prefix; the tail of the prior
                # frame remains (true terminal column semantics, no clear-line).
                rendered = seg + rendered[len(seg):]
        out_lines.append(rendered)
    return "\n".join(out_lines)


def _is_chrome_line(line):
    """True when ``line`` is terminal interface chrome (box / spinner / status).

    Conservative — only flags a line that is DOMINATED by box-drawing glyphs, or
    is a spinner/status frame (a spinner glyph and/or a known status phrase with
    little else). Real prose (even prose that mentions "esc") is kept because it
    has substantial non-chrome content.
    """
    s = line.strip()
    if not s:
        return False
    # Box-drawing chrome: the line is mostly box glyphs (the prompt frame).
    boxy = sum(1 for ch in s if ch in _BOX_DRAW_SET)
    nonspace = sum(1 for ch in s if not ch.isspace())
    if nonspace and boxy >= max(2, int(nonspace * 0.5)):
        return True
    # Spinner/status frame: starts with (or is mostly) a spinner glyph, and the
    # residual text is short status chrome.
    has_spinner = any(ch in _SPINNER_SET for ch in s)
    residual = "".join(ch for ch in s if ch not in _SPINNER_SET).strip()
    if has_spinner and (not residual or len(residual) <= 60
                        or _STATUS_PHRASE_RE.search(residual)):
        return True
    # A pure status line with no real content (e.g. a redrawn token counter).
    if _STATUS_PHRASE_RE.search(s) and len(s) <= 40:
        return True
    # The model's own greet line ("✓ <Skill> loaded — what would you like to
    # do?") — boilerplate, not dialogue. Dropped whether or not the seed echo was
    # already stripped (it survives as a separate real-output line).
    low = s.lower()
    if GREET_MARKER.lower() in low and "loaded" in low and len(s) <= 80:
        return True
    return False


def _strip_seed_greet(text, seed_text=""):
    """Remove the load+greet preamble from CLEANED text, robust to rendering.

    The seed Anchor writes ("Load the <Skill> skill now … greet me EXACTLY once …
    ✓ <Skill> loaded — what would you like to do?") is ECHOED by the PTY. On the
    STUB / a narrow terminal it echoes the seed VERBATIM (byte-exact); on a real
    ConPTY it comes back RENDERED (line-wrapped at terminal width, glyphs), so a
    byte-exact ``startswith`` won't match.

    Resolution order (byte-exact FIRST so we never under-strip a known seed — e.g.
    a grass develop seed that carries the idea text AS PART OF the seed must be
    removed WHOLE, not cut at the greet marker mid-seed):

      1. **byte-exact** full-seed strip (``startswith`` / ``find``) — removes the
         entire recorded seed including any idea-text suffix;
      2. **whitespace-normalized** full-seed match — handles a rendered seed whose
         only difference is collapsed/wrapped whitespace; cut the same span;
      3. **marker-based** cut — when the seed isn't recoverable as a whole (heavily
         re-flowed render), cut everything up to and INCLUDING the greet marker
         (``what would you like to do?``), the boilerplate↔dialogue boundary, but
         ONLY when the "Load the … skill" boilerplate genuinely precedes it.

    If none matches (env-overridden / absent seed), leave the text untouched
    (never over-strip real dialogue). Operates on the CLEANED text (post ANSI
    strip) so control codes don't defeat the match.
    """
    if not text:
        return text
    seed = (seed_text or "").strip()
    # 1) byte-exact whole-seed strip (stub echo + the grass idea-suffix seed).
    if seed_text and text.startswith(seed_text):
        return text[len(seed_text):]
    if seed:
        idx = text.find(seed)
        if idx != -1:
            return text[:idx] + text[idx + len(seed):]
    # 2) whitespace-normalized whole-seed match (rendered/re-flowed seed). Map the
    # normalized match span back to a raw cut by walking raw chars while skipping
    # the collapsed whitespace, so the WHOLE seed (incl. idea suffix) is removed.
    if seed and len(seed) > 20:
        norm_seed = re.sub(r"\s+", " ", seed).strip()
        # Build a normalized view of text + an index map back to raw offsets.
        norm_chars = []
        norm_to_raw = []
        prev_ws = False
        for i, ch in enumerate(text):
            if ch.isspace():
                if prev_ws:
                    continue
                norm_chars.append(" ")
                norm_to_raw.append(i)
                prev_ws = True
            else:
                norm_chars.append(ch)
                norm_to_raw.append(i)
                prev_ws = False
        norm_text = "".join(norm_chars)
        nidx = norm_text.find(norm_seed)
        if nidx != -1:
            raw_start = norm_to_raw[nidx]
            end_n = nidx + len(norm_seed) - 1
            raw_end = norm_to_raw[end_n] if end_n < len(norm_to_raw) else len(text) - 1
            return text[:raw_start] + text[raw_end + 1:]
    # 3) marker-based cut (heavily re-flowed render; no whole-seed recovery).
    low = text.lower()
    greet = GREET_MARKER.lower()  # "what would you like to do?"
    gpos = low.rfind(greet)
    if gpos != -1 and re.search(r"load the .{0,40}? skill", low):
        load_pos = low.find("load the")
        if 0 <= load_pos < gpos:
            cut = gpos + len(greet)
            nl = text.find("\n", cut)
            return text[nl + 1:] if nl != -1 else text[cut:]
    return text


def _clean_transcript_text(raw, seed_text=""):
    """Clean a raw PTY buffer into honest transcript markdown text, or ``""``.

    Real-ConPTY-robust. The pipeline (stdlib ``re`` only):

      1. **Collapse ``\\r`` in-place redraws** to each line's FINAL frame
         (:func:`_collapse_cr_redraws`) — a real status/spinner line is rewritten
         hundreds of times via carriage-return with no newline; we keep only the
         last render instead of exploding every frame into a line (the pre-fix
         bug that buried the Q&A under stale redraw frames).
      2. **Strip ANSI/CSI/OSC/DCS** escape sequences + stray control bytes
         (:data:`_ANSI_ESCAPE_RE`).
      3. **Strip the load+greet preamble** robustly (:func:`_strip_seed_greet`) —
         marker-based so a line-wrapped rendered seed is still removed.
      4. **Drop interface chrome** lines (box-drawing input frame + spinner/status
         frames) — :func:`_is_chrome_line`, conservative.
      5. **Collapse consecutive DUPLICATE content lines** to one (a spinner that
         survived as repeated identical lines folds to a single line) and collapse
         runs of blank lines.
      6. **Cap** keeping a HEAD + TAIL slice (the research framing AND the latest
         findings survive; the middle is marked truncated on a line boundary).

    Returns ``""`` when nothing meaningful remains. Never raises.
    """
    try:
        text = raw or ""
        # 1. Carriage-return in-place redraw collapse (BEFORE ANSI strip so the
        # \r boundaries are intact; the ANSI regex keeps \r).
        text = _collapse_cr_redraws(text)
        # 2. Strip ANSI / control sequences (now keeps \t \n only; \r consumed).
        text = _ANSI_ESCAPE_RE.sub("", text)
        text = text.replace("\r", "\n")  # any residual lone CR → newline
        # 3. Strip the load+greet preamble (rendered-robust, on cleaned text).
        text = _strip_seed_greet(text, seed_text=seed_text)
        # 4 + 5. Drop chrome lines; collapse consecutive duplicate content lines.
        kept = []
        prev = None
        blank_run = 0
        for line in text.split("\n"):
            if _is_chrome_line(line):
                continue
            stripped = line.rstrip()
            if not stripped.strip():
                blank_run += 1
                if blank_run <= 1:
                    kept.append("")
                continue
            blank_run = 0
            if stripped == prev:
                continue  # collapse a repeated identical content line
            prev = stripped
            kept.append(stripped)
        text = "\n".join(kept)
        text = re.sub(r"\n[ \t]*\n([ \t]*\n)+", "\n\n", text)
        text = text.strip()
        if not text:
            return ""
        # 6. Cap keeping HEAD + TAIL (the framing + the latest discussion).
        if len(text) > _TRANSCRIPT_MAX_CHARS:
            head = text[:_TRANSCRIPT_HEAD_CHARS]
            # End the head on a line boundary.
            hnl = head.rfind("\n")
            if hnl > 0:
                head = head[:hnl]
            tail = text[-_TRANSCRIPT_TAIL_CHARS:]
            tnl = tail.find("\n")
            if 0 <= tnl < 200:
                tail = tail[tnl + 1:]
            text = (head.rstrip() + "\n\n[… middle truncated …]\n\n"
                    + tail.strip())
        return text
    except Exception:
        return ""


def _snapshot_transcript_doc(record, source_session_id):
    """Snapshot the source session's PTY transcript into a lane doc (D3/D4).

    Reads the source session's full cumulative PTY output (``read_since(sid, 0)``),
    cleans it (:func:`_clean_transcript_text`), and writes it to
    ``<source_worktree>/<source_lane>/<short-sid>-transcript.md`` — a deterministic
    filename (so a re-advance overwrites the same path, idempotent) that
    ``_is_document_rel`` classifies as a produced doc. Creates the lane dir if
    missing. Returns the repo-relative POSIX path written, or ``None`` when there
    is no live PTY / no meaningful transcript / any failure. Never raises.
    """
    try:
        if not isinstance(record, dict):
            return None
        worktree_path = (record.get("worktree_path") or "").strip()
        lane = (record.get("lane") or "").strip()
        if not worktree_path or not lane:
            return None
        wt = Path(worktree_path)
        if not wt.is_dir():
            return None
        # Read the full cumulative output buffer (cursor 0).
        try:
            out = _pty.read_since(source_session_id, 0)
        except _pty.UnknownSession:
            return None  # no live PTY (e.g. reaped) → nothing to snapshot
        raw = (out.get("text") or "") if isinstance(out, dict) else ""
        body = _clean_transcript_text(raw, seed_text=record.get("seed_text") or "")
        if not body:
            return None
        store_lane = _eh._resolve_subdir(lane)
        short_sid = (source_session_id or "")[:12] or "session"
        rel = "%s/%s-transcript.md" % (store_lane, short_sid)
        dest = wt / store_lane / ("%s-transcript.md" % short_sid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        header = "# %s session transcript (%s)\n\n" % (lane.title(), short_sid)
        dest.write_text(header + body + "\n", encoding="utf-8")
        return rel
    except Exception:
        return None


def prepare_stage_handoff(project_id, source_session_id, to_lane):
    """Persist the source stage's docs + build the real next-stage handoff (v11 W1).

    The ONE shared keystone for an advance/handoff. Given a SOURCE session (live
    or done) and the TARGET lane to advance into, it:

      (a) resolves the source session record (its lane + worktree) and maps
          ``to_lane`` → the next-stage skill (plan/planning→Crucible, build→Foreman);
      (b) **PERSISTS** the source session's produced docs via
          :func:`capture_session_docs` — copies + commits them into the main
          project AND records session-tagged DISCOVERED efforts. Best-effort and
          IDEMPOTENT (content-addressed, byte-identical skip); works whether the
          source is LIVE or done; does NOT reap the worktree. A persistence
          failure is swallowed (degrades to the honest minimal prompt) — it can
          NEVER raise out of this function;
      (c) **BUILDS** the next-stage prompt via
          ``handoff.build_next_stage_prompt`` — now that the docs are persisted +
          session-tagged, :func:`research_set_for_session` finds them → the REAL
          prompt naming the actual doc paths + a "read these first" instruction.
          For plan→build it discovers the plan set as today. Honest minimal,
          skill-correct prompt only when there are genuinely no docs;
      (d) **RESOLVES** the handoff materials: the real persisted ``doc_rels``
          (from :func:`effort_history.efforts_for_session_id` over the source
          lane; for plan→build also the discovered plan-set doc rels), the skill,
          and the source session's cached summary text (``""`` if absent);
      (e) **TRIGGERS** a NON-BLOCKING background source-stage summary (daemon
          thread; idempotent; failure swallowed) so the digest becomes available
          without blocking the advance.

    Returns ``{ok, prompt, doc_rels, skill, summary_text, persisted}``. ``ok`` is
    True when the source session resolved (even with no docs — an honest empty
    handoff is still a successful prepare). Never raises.
    """
    out = {"ok": False, "prompt": "", "doc_rels": [], "skill": "",
           "summary_text": "", "persisted": []}

    lane_key = (to_lane or "").strip().lower()
    skill = LANE_SKILL.get(lane_key, "")
    out["skill"] = skill

    # (a) Resolve the source session record + the project folder.
    rec = _reg.get_session(source_session_id)
    if rec is None:
        return out
    if not project_id:
        project_id = rec.get("project_id") or None
    if not project_id:
        return out
    source_lane = (rec.get("lane") or "").strip()
    proj = _rnd.get_project(project_id)
    if proj is None:
        return out
    folder = proj.get("folder_path", "")
    if not folder:
        return out
    # From here on the source resolved → an honest empty handoff is still ok.
    out["ok"] = True

    # (b) PERSIST the source session's produced docs — best-effort, idempotent,
    # NEVER raises out of prepare_stage_handoff (degrade to the honest prompt).
    try:
        persist_res = capture_session_docs(
            source_session_id, project_id=project_id, record=rec)
        if isinstance(persist_res, dict):
            out["persisted"] = list(persist_res.get("persisted") or [])
    except Exception:
        out["persisted"] = []

    # (b.2) v11.1 D3/D4: CONVERSATION-only capture. When the initial persist
    # produced ZERO document-classified docs (D4 — only the gap case), snapshot
    # the source session's PTY transcript into a lane doc and re-persist it so the
    # conversation is not lost and the REAL doc-referencing prompt engages. Wrapped
    # best-effort — on ANY failure leave ``persisted`` empty and fall through to
    # the honest-minimal prompt; NEVER raise out of prepare_stage_handoff.
    if not out["persisted"]:
        try:
            snap_rel = _snapshot_transcript_doc(rec, source_session_id)
            if snap_rel:
                persist_res2 = capture_session_docs(
                    source_session_id, project_id=project_id, record=rec)
                if isinstance(persist_res2, dict):
                    out["persisted"] = list(persist_res2.get("persisted") or [])
        except Exception:
            pass  # leave persisted as-is (empty) → honest-minimal prompt

    # (c) BUILD the next-stage prompt from the now-persisted, session-tagged docs.
    try:
        out["prompt"] = _handoff.build_next_stage_prompt(
            folder, project_id, source_session_id, lane_key) or ""
    except Exception:
        out["prompt"] = ""

    # (d) RESOLVE the handoff materials: the real persisted doc rels.
    doc_rels = []
    try:
        if source_lane:
            store_lane = _eh._resolve_subdir(source_lane)
            for e in _eh.efforts_for_session_id(
                    folder, project_id, store_lane, source_session_id):
                rel = (e.get("artifact_path") or "").strip().replace("\\", "/")
                if rel and rel not in doc_rels:
                    doc_rels.append(rel)
        # For plan→build also fold in the discovered plan-set doc rels (the
        # build's HANDOFF.md lists the plan documents, not the planning session's
        # own member docs only).
        if lane_key == "build":
            try:
                plan_set = _handoff.discover_recent_plan_set(
                    folder, project_id, source_session_id=source_session_id)
            except Exception:
                plan_set = None
            if plan_set:
                for r in _doc_paths_for_seed(plan_set):
                    if r and r not in doc_rels:
                        doc_rels.append(r)
    except Exception:
        pass
    out["doc_rels"] = doc_rels

    # (d cont.) the source session's cached summary text (honest "" if absent).
    try:
        import summarizer as _sm
        if source_lane:
            cached = _sm.load_cached(
                folder, project_id, _eh._resolve_subdir(source_lane),
                source_session_id)
            out["summary_text"] = _summary_text_from_cached(cached)
    except Exception:
        out["summary_text"] = ""

    # (e) TRIGGER a non-blocking background source-stage summary.
    try:
        _trigger_background_source_summary(
            folder, project_id, source_lane, source_session_id)
    except Exception:
        pass

    return out


def list_sessions(project_id=None, status=None):
    """Thin pass-through to ``session_registry.list_sessions`` (for UI/CLI)."""
    return _reg.list_sessions(project_id=project_id, status=status)


def get_session(session_id):
    """Return the registry record for ``session_id`` (or ``None``)."""
    return _reg.get_session(session_id)
