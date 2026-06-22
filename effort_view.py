#!/usr/bin/env python3
"""Anchor effort view-layer — group registry sessions into EFFORTS (stdlib only).

v12 "Efforts" Wave 9 (MASTER-PLAN §4.5, IMPLEMENTATION-PLAN §Wave 9). Legacy
research→plan→build *chains* (three separate session records linked by
``chain_id``) and the new v12 *single-session efforts* (one record already
carrying a ``stage_history``) must render UNIFORMLY as **efforts** — one tile per
effort, one stage track.

This module is the **derived, drift-safe, deduped view** that makes that uniform:

  - :func:`build_effort_view` groups the project's ``session_registry`` records by
    ``chain_id`` and emits ONE effort dict per chain. A new single-session effort
    (its ``chain_id == session_id`` and it already carries ``stage_history``)
    passes through as its own one-member chain — i.e. as one effort.
  - It is **REBUILT FROM THE REGISTRY ON EVERY CALL** — a *derived cache*, never a
    stored source of truth. A member deleted from the registry simply DROPS from
    the view (no ghost stage). Building twice yields equal results (idempotent).
  - It is **deduped** against the migration overlap (Shark SK-6): if a chain
    member is ALSO present as a live record carrying its own ``stage_history``,
    the effort renders EXACTLY ONCE (grouping is by ``chain_id``, so a member can
    only land in one effort), and the live status wins for the effort's status.
  - It is **guarded** like ``project_move`` (v9): it never treats/modifies the
    Anchor repo specially (compared against ``paths.CODE_DIR``) and is **READ
    ONLY** — it never reaps/kills/mutates a live member or the registry.
  - SAFE projections only — a member projection NEVER carries ``worktree_path`` /
    ``branch`` (no leak into the render layer).

Stdlib only. Best-effort: a per-member failure (e.g. a summary read) degrades to
honest empty data and never breaks the view.
"""

import session_registry as _reg


# Display order for the trio stages (research → plan → build → others).
_STAGE_ORDER = {"research": 0, "plan": 1, "build": 2}
_STAGE_ORDER_DEFAULT = 9

# Map a member's trio stage to the on-disk STORE-lane its docs/summary live under
# (research → research, plan → planning, build → build). Mirrors
# ``effort_history._STORE_LANE_FOR_STAGE`` / ``session_registry._STAGE_STORE_LANE``
# WITHOUT importing them at module scope (stdlib-only / cheap import discipline).
_STORE_LANE_FOR_STAGE = {
    "research": "research",
    "plan": "planning",
    "build": "build",
}

# The registry statuses that mean a session has a LIVE process.
_LIVE_STATUSES = frozenset((_reg.STATUS_RUNNING,))


def _member_stage(rec: dict) -> str:
    """The trio stage a member contributes (its ``current_stage``).

    Falls back to deriving from ``lane`` for a record that somehow lacks a
    ``current_stage`` (``_normalize`` already derives it, so this is defensive).
    """
    st = (rec.get("current_stage") or "").strip()
    if st:
        return st
    lane = (rec.get("lane") or "").strip()
    if lane == "research":
        return "research"
    if lane in ("plan", "planning"):
        return "plan"
    if lane == "build":
        return "build"
    return ""


def _stage_rank(stage: str) -> int:
    return _STAGE_ORDER.get(stage, _STAGE_ORDER_DEFAULT)


def _created_at(rec: dict) -> float:
    c = rec.get("created_at")
    try:
        return float(c) if c is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _docs_for_member_stage(folder_path, project_id, rec: dict, stage: str):
    """SAFE doc projections a member produced for its ``stage`` (best-effort).

    Prefers the v12 stage-scoped join (``efforts_for_session_stage``); falls back
    to the v8 session-id join (``efforts_for_session_id`` on the stage's
    store-lane) for legacy chain members that were persisted before stage tagging.
    Returns ``[{label, rel}]`` — NEVER an absolute path / worktree / branch.
    """
    if not stage:
        return []
    sid = rec.get("session_id") or ""
    if not sid:
        return []
    store_lane = _STORE_LANE_FOR_STAGE.get(stage, stage)
    try:
        import effort_history as _eh
    except Exception:
        return []
    efforts = []
    try:
        efforts = _eh.efforts_for_session_stage(folder_path, project_id, sid, stage)
    except Exception:
        efforts = []
    if not efforts:
        # Legacy fallback: the v8 persist tagged docs with the session id only
        # (no stage) — join on the store-lane.
        try:
            efforts = _eh.efforts_for_session_id(folder_path, project_id,
                                                 store_lane, sid)
        except Exception:
            efforts = []
    out = []
    for e in efforts:
        rel = (e.get("artifact_path") or e.get("rel") or "").strip()
        rel = rel.replace("\\", "/")
        label = (e.get("title") or rel or e.get("job_id") or "").strip()
        if not rel and not label:
            continue
        out.append({"label": label or rel, "rel": rel})
    return out


def _summary_ref_for_member_stage(folder_path, project_id, rec: dict, stage: str):
    """A short cached-summary blurb for a member's stage, or ``""`` (best-effort).

    READ-ONLY: never runs the model. Resolves via the stage's recorded
    ``store_lane`` (the v12 Wave-4 closed-stage read path), falling back to the
    derived store-lane. ``""`` when uncached (honest — the render shows a
    placeholder).
    """
    if not stage:
        return ""
    sid = rec.get("session_id") or ""
    if not sid:
        return ""
    # Prefer the store_lane recorded on the stage entry (survives a lane flip).
    store_lane = _STORE_LANE_FOR_STAGE.get(stage, stage)
    try:
        ent = _reg.stage_entry(rec, stage)
        if isinstance(ent, dict) and ent.get("store_lane"):
            store_lane = ent.get("store_lane")
    except Exception:
        pass
    try:
        import summarizer as _sm
        return _sm.session_blurb(folder_path, project_id, store_lane, sid,
                                 stage=stage) or ""
    except Exception:
        return ""


def _member_projection(folder_path, project_id, rec: dict) -> dict:
    """A SAFE per-member projection — NEVER ``worktree_path`` / ``branch``.

    Carries the member's stage + its produced docs + a cached summary blurb so
    the synthesized ``stage_history`` references each member's real artifacts.
    """
    stage = _member_stage(rec)
    sid = rec.get("session_id") or ""
    return {
        "session_id": sid,
        "stage": stage,
        "lane": rec.get("lane") or "",
        "kind": rec.get("kind") or "",
        "status": rec.get("status") or "",
        "label": rec.get("label") or "",
        "created_at": _created_at(rec),
        "live": rec.get("status") in _LIVE_STATUSES,
        "docs": _docs_for_member_stage(folder_path, project_id, rec, stage),
        "summary_ref": _summary_ref_for_member_stage(
            folder_path, project_id, rec, stage),
    }


def _synth_stage_history(folder_path, project_id, members: list) -> list:
    """Synthesize a chain's ``stage_history`` from its members.

    Ordered research → plan → build (then by ``created_at``); each member
    contributes ONE stage entry referencing its persisted docs + cached summary.
    A new single-session effort already carrying its own ``stage_history`` is
    handled by :func:`_effort_from_single_session` instead — this is the
    multi-member (legacy chain) synthesis path.
    """
    out = []
    for m in members:
        stage = _member_stage(m)
        if not stage:
            continue
        sid = m.get("session_id") or ""
        docs = _docs_for_member_stage(folder_path, project_id, m, stage)
        out.append({
            "stage": stage,
            "session_id": sid,
            "store_lane": _STORE_LANE_FOR_STAGE.get(stage, stage),
            "status": m.get("status") or "",
            "state": "active" if m.get("status") in _LIVE_STATUSES else "done",
            "live": m.get("status") in _LIVE_STATUSES,
            "doc_count": len(docs),
            "docs": docs,
            "summary_ref": _summary_ref_for_member_stage(
                folder_path, project_id, m, stage),
        })
    out.sort(key=lambda e: (_stage_rank(e.get("stage", "")),))
    return out


def _effort_from_single_session(folder_path, project_id, rec: dict) -> dict:
    """Pass a v12 single-session effort through as ONE effort.

    A new effort already carries its own ``stage_history`` (each entry written by
    ``set_current_stage`` as the one session advanced research→plan→build). We
    enrich each entry with the member's persisted docs + a cached summary blurb so
    the render layer reads the SAME shape as a synthesized chain effort.
    """
    sid = rec.get("session_id") or ""
    raw_history = rec.get("stage_history") or []
    history = []
    for ent in raw_history:
        if not isinstance(ent, dict):
            continue
        stage = (ent.get("stage") or "").strip()
        store_lane = (ent.get("store_lane")
                      or _STORE_LANE_FOR_STAGE.get(stage, stage))
        docs = _docs_for_member_stage(folder_path, project_id, rec, stage)
        history.append({
            "stage": stage,
            "session_id": sid,
            "store_lane": store_lane,
            "status": ent.get("state") or "",
            "state": ent.get("state") or "",
            "live": rec.get("status") in _LIVE_STATUSES
                    and ent.get("ended_at") is None,
            "doc_count": len(docs) or int(ent.get("doc_count") or 0),
            "docs": docs,
            "summary_ref": _summary_ref_for_member_stage(
                folder_path, project_id, rec, stage),
        })
    history.sort(key=lambda e: (_stage_rank(e.get("stage", "")),))
    current_stage = (rec.get("current_stage") or "").strip()
    if not current_stage and history:
        current_stage = history[-1].get("stage", "")
    return {
        "effort_id": rec.get("effort_id") or sid,
        "chain_id": rec.get("chain_id") or sid,
        "kind": rec.get("kind") or "",
        "current_stage": current_stage,
        "status": rec.get("status") or "",
        "live": rec.get("status") in _LIVE_STATUSES,
        "created_at": _created_at(rec),
        "stage_history": history,
        "members": [_member_projection(folder_path, project_id, rec)],
        "effort_managed": bool(rec.get("effort_managed")),
    }


def _effort_from_chain(folder_path, project_id, chain_id: str,
                       members: list) -> dict:
    """Build ONE effort dict from a chain's (ordered) members.

    ``current_stage`` = the MOST-ADVANCED member's stage; ``status`` = the NEWEST
    member's status (live status wins — see :func:`build_effort_view` dedup);
    ``live`` = any member RUNNING; ``stage_history`` synthesized from the members.
    The effort_id is the chain ROOT session_id (the earliest / lowest-rank member).
    """
    # Root = the lowest stage-rank member, tie-broken by earliest created_at.
    root = min(members, key=lambda r: (_stage_rank(_member_stage(r)),
                                       _created_at(r)))
    # Most-advanced member → current_stage.
    most_adv = max(members, key=lambda r: (_stage_rank(_member_stage(r)),
                                           _created_at(r)))
    current_stage = _member_stage(most_adv)
    # Newest member → status (a LIVE member's status wins over a stale newest).
    live_members = [r for r in members if r.get("status") in _LIVE_STATUSES]
    if live_members:
        status_rec = max(live_members, key=_created_at)
    else:
        status_rec = max(members, key=_created_at)
    history = _synth_stage_history(folder_path, project_id, members)
    return {
        "effort_id": root.get("effort_id") or root.get("session_id") or chain_id,
        "chain_id": chain_id,
        "kind": root.get("kind") or "trio",
        "current_stage": current_stage,
        "status": status_rec.get("status") or "",
        "live": bool(live_members),
        "created_at": _created_at(root),
        "stage_history": history,
        "members": [_member_projection(folder_path, project_id, m)
                    for m in members],
        "effort_managed": any(bool(m.get("effort_managed")) for m in members),
    }


def _is_single_session_effort(members: list) -> bool:
    """A v12 single-session effort = one member that carries its own
    ``stage_history`` (the session advanced in place). A bare single member with
    no stage_history is a one-member legacy chain → still synthesize from it (the
    paths converge, but this keeps the pass-through semantics explicit)."""
    if len(members) != 1:
        return False
    return bool(members[0].get("stage_history"))


def build_effort_view(folder_path, project_id) -> list:
    """Group a project's registry records into a list of efforts, ONE per chain.

    REBUILT FROM THE REGISTRY ON EVERY CALL (a derived cache, never a stored
    source). Grouping is by ``chain_id``, so each member lands in exactly one
    effort — the migration overlap (a chain member that is ALSO a live record with
    ``stage_history``) renders exactly ONCE, with the live status winning. A member
    deleted from the registry simply drops (no ghost stage). READ-ONLY — never
    reaps/mutates a live member. Guarded like ``project_move``: the Anchor repo is
    never treated specially / never mutated (this function performs NO writes at
    all). Newest-first by the chain root's ``created_at``.

    Returns ``[effort_dict, ...]``; SAFE projections only (no worktree/branch).
    Best-effort — never raises (a per-effort failure is skipped).
    """
    try:
        records = _reg.list_sessions(project_id=project_id)
    except Exception:
        return []
    # NOTE (Reviewers EV-1/F1): no Anchor-repo guard is needed here — unlike
    # project_move (which mutates the filesystem), this builder is PURE READ: it
    # calls only session_registry/effort_history/summarizer read accessors and
    # writes nothing, so it is safe on every project including the Anchor repo.
    # (The read-only purity is the real guarantee, covered by the read-only tests.)
    # Group by chain_id (default = own session_id → a singleton chain).
    groups = {}
    for rec in records:
        if not isinstance(rec, dict):
            continue
        sid = rec.get("session_id") or ""
        if not sid:
            continue
        cid = rec.get("chain_id") or sid
        groups.setdefault(cid, {})
        # Dedup within a chain: a session_id can only appear once even if the
        # registry somehow returned it twice. The migration-overlap is naturally
        # deduped because grouping is by chain_id — a member that is also a live
        # record IS the same record (same session_id), so it lands once.
        groups[cid][sid] = rec
    efforts = []
    for cid, by_sid in groups.items():
        members = sorted(by_sid.values(),
                         key=lambda r: (_stage_rank(_member_stage(r)),
                                        _created_at(r)))
        if not members:
            continue
        try:
            if _is_single_session_effort(members):
                eff = _effort_from_single_session(
                    folder_path, project_id, members[0])
            else:
                eff = _effort_from_chain(folder_path, project_id, cid, members)
        except Exception:
            continue
        efforts.append(eff)
    # Newest-first by the effort's (root) created_at; effort_id as a stable
    # tiebreaker so equal-created_at efforts have a DEFINED total order (F3).
    efforts.sort(key=lambda e: (-float(e.get("created_at") or 0.0),
                                e.get("effort_id", "")))
    return efforts


def effort_for_session(folder_path, project_id, session_id):
    """Return the effort dict the given ``session_id`` belongs to, or ``None``.

    Resolves the session's ``chain_id`` and returns the matching effort from
    :func:`build_effort_view` (so the returned shape is identical). ``None`` for
    an unknown session or when no effort contains it. Read-only; never raises.
    """
    if not session_id:
        return None
    try:
        rec = _reg.get_session(session_id)
    except Exception:
        rec = None
    if not isinstance(rec, dict):
        return None
    cid = rec.get("chain_id") or rec.get("session_id") or session_id
    for eff in build_effort_view(folder_path, project_id):
        if eff.get("chain_id") == cid:
            return eff
        for m in eff.get("members", []) or []:
            if m.get("session_id") == session_id:
                return eff
    return None
