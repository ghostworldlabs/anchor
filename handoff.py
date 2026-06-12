#!/usr/bin/env python3
"""Anchor stage handoffs — Wave 7 of v3 "Mission Control".

When the user launches a **build / execution** session, the most useful thing
Anchor can do is hand off the *most-recent plan set* (a MASTER-PLAN +
IMPLEMENTATION-PLAN pair, plus the rest of that plan's docs) into the new
session's worktree so the user/terminal can immediately "execute on this plan".

This module is the faithful stage→stage handoff (MASTER-PLAN §G). It is
deliberately **surface + record, never run**:

  - ``discover_recent_plan_set`` — find the newest plan set from the planning
    lane's sessions (``sessions.list_sessions(.., "planning")``, newest-first),
    falling back to the newest ``by_lane.planning`` group in the per-project
    ``discovery.json``. A ``source_session_id`` (the Wave-6 ``seed_session``)
    OVERRIDES the "newest" preference to point at a specific session's plan.
  - ``propose_handoff`` — a read-only proposal ("Execute on this plan set?")
    the UI can show BEFORE launching a build session.
  - ``prime_worktree`` — write a small **HANDOFF reference file** into the
    session worktree ROOT listing the plan doc paths (which ALREADY EXIST inside
    the checkout — a worktree is a checkout of the repo) + the execute context.
    It does NOT copy plan contents and it does NOT auto-seed a skill (the Wave-3
    terminal is a bare interactive PTY).
  - ``record_handoff`` — record the handoff context (structure-only, safe to
    commit) by appending to a ``handoffs`` list in ``discovery.json`` under
    ``paths.WRITE_LOCK``.

Key fact: the git worktree IS a checkout of the project repo, so committed plan
docs (``planning/rnd-v3/MASTER-PLAN.md`` etc.) already physically exist inside
the worktree. "Pre-stage the worktree primed with those plan paths" therefore
means SURFACE + RECORD the paths — not copy file contents.

Stdlib only. Reuses ``sessions``, ``effort_history`` and ``anchor_marker``;
never forks their storage.
"""

import json
import time
from pathlib import Path, PurePosixPath

import paths as _paths
import sessions as _sessions
import anchor_marker as _marker

#: The handoff reference file written into a primed worktree root.
HANDOFF_FILENAME = "HANDOFF.md"

#: Lanes that receive a build→plan handoff (the "execute on a plan" lanes).
BUILD_LANES = ("build",)

#: Fragments identifying the two anchor docs of a plan set.
_MASTER_FRAGS = ("master-plan", "master plan", "masterplan")
_IMPL_FRAGS = ("implementation-plan", "implementation plan", "impl-plan",
               "implementationplan")


# ── small helpers ────────────────────────────────────────────────────────────

def _rel_of(member):
    """The folder-relative POSIX artifact path of a session member, or ``""``."""
    rel = (member.get("artifact_path") or "").strip()
    return rel.replace("\\", "/") if rel else ""


def _basename_lower(rel):
    return PurePosixPath(rel).name.lower() if rel else ""


def _is_master(rel, member):
    blob = f"{_basename_lower(rel)} {member.get('title', '')} {member.get('kind', '')}".lower()
    return any(f in blob for f in _MASTER_FRAGS)


def _is_impl(rel, member):
    blob = f"{_basename_lower(rel)} {member.get('title', '')} {member.get('kind', '')}".lower()
    return any(f in blob for f in _IMPL_FRAGS)


def _plan_dir_of(doc_rels):
    """Common parent dir (folder-relative POSIX) of a plan set's docs, or ``""``."""
    parents = set()
    for r in doc_rels:
        p = PurePosixPath(r).parent.as_posix()
        if p in (".", "", "/"):
            p = ""
        parents.add(p)
    if len(parents) == 1:
        return next(iter(parents))
    # Mixed dirs: pick the shallowest common one (the master-plan's dir is the
    # natural anchor; callers pass master first so [0] is a good fallback).
    return PurePosixPath(doc_rels[0]).parent.as_posix() if doc_rels else ""


def _plan_set_from_session(session):
    """Build a plan-set dict from a planning session, or ``None``.

    A session qualifies as a plan set when its members include a MASTER-PLAN
    (the implementation plan is preferred but not strictly required — a master
    plan alone is still a usable plan set). Returns the canonical shape or
    ``None`` if no master-plan-like member exists.
    """
    members = session.get("member_files") or []
    doc_rels = []
    master_rel = ""
    impl_rel = ""
    for m in members:
        rel = _rel_of(m)
        if not rel:
            continue
        doc_rels.append(rel)
        if not master_rel and _is_master(rel, m):
            master_rel = rel
        elif not impl_rel and _is_impl(rel, m):
            impl_rel = rel
    if not master_rel:
        return None
    # Order: master first, impl second, then the remaining docs (stable).
    ordered = [master_rel]
    if impl_rel:
        ordered.append(impl_rel)
    for r in doc_rels:
        if r not in ordered:
            ordered.append(r)
    plan_dir = _plan_dir_of(ordered)
    return {
        "plan_session_id": session.get("session_id", ""),
        "plan_dir": plan_dir,
        "master_plan_rel": master_rel,
        "impl_plan_rel": impl_rel,
        "doc_rels": ordered,
        "title": session.get("title", "") or PurePosixPath(plan_dir).name,
        "when": float(session.get("timestamp", 0.0) or 0.0),
    }


# ── discovery.json fallback ─────────────────────────────────────────────────

def _load_discovery(folder_path, project_id):
    """Load the per-project ``discovery.json`` dict, or ``{}``."""
    p = _marker.sidecar_path(folder_path, project_id)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _plan_set_from_discovery(folder_path, project_id):
    """Fallback: newest ``by_lane.planning`` group (grouped by parent dir).

    Groups the discovery sidecar's planning artifacts by their parent directory
    (e.g. ``planning/rnd-v3/``), picks the group whose newest member mtime is
    greatest, and returns a plan-set dict requiring a MASTER-PLAN-like doc.
    Returns ``None`` when no qualifying group exists.
    """
    disc = _load_discovery(folder_path, project_id)
    by_lane = disc.get("by_lane") or {}
    planning = by_lane.get("planning") or []
    if not planning:
        return None
    groups = {}  # parent_dir -> [artifacts]
    for art in planning:
        rel = (art.get("rel") or "").replace("\\", "/")
        if not rel:
            continue
        parent = PurePosixPath(rel).parent.as_posix()
        if parent in (".", "", "/"):
            parent = ""
        groups.setdefault(parent, []).append(art)
    best = None
    for parent, arts in groups.items():
        doc_rels = []
        master_rel = ""
        impl_rel = ""
        newest = 0.0
        for a in arts:
            rel = (a.get("rel") or "").replace("\\", "/")
            doc_rels.append(rel)
            newest = max(newest, float(a.get("mtime", 0.0) or 0.0))
            if not master_rel and _is_master(rel, a):
                master_rel = rel
            elif not impl_rel and _is_impl(rel, a):
                impl_rel = rel
        if not master_rel:
            continue
        ordered = [master_rel]
        if impl_rel:
            ordered.append(impl_rel)
        for r in doc_rels:
            if r not in ordered:
                ordered.append(r)
        cand = {
            "plan_session_id": "",  # discovery fallback has no session id
            "plan_dir": parent,
            "master_plan_rel": master_rel,
            "impl_plan_rel": impl_rel,
            "doc_rels": ordered,
            "title": PurePosixPath(parent).name or master_rel,
            "when": newest,
        }
        if best is None or cand["when"] > best["when"]:
            best = cand
    return best


# ── public API ───────────────────────────────────────────────────────────────

def discover_recent_plan_set(folder_path, project_id, source_session_id=None):
    """Find the MOST-RECENT plan set for a project (MASTER-PLAN §G).

    Strategy:
      1. If ``source_session_id`` is given (the Wave-6 ``seed_session``), prefer
         THAT planning session's plan docs — the user launched from a specific
         session and the handoff should honor it.
      2. Otherwise the newest **planning session** (``sessions.list_sessions``,
         newest-first) whose members include a MASTER-PLAN.
      3. Fallback: the newest ``by_lane.planning`` group in ``discovery.json``.

    Returns ``{plan_session_id, plan_dir, master_plan_rel, impl_plan_rel,
    doc_rels:[...], title, when}`` (rels are folder-relative POSIX), or ``None``
    if no plan set exists. Never raises.
    """
    try:
        plan_sessions = _sessions.list_sessions(folder_path, project_id, "planning")
    except Exception:
        plan_sessions = []

    # 1. seed_session override — honor the specific session the user launched from.
    if source_session_id:
        for s in plan_sessions:
            if s.get("session_id") == source_session_id:
                ps = _plan_set_from_session(s)
                if ps is not None:
                    return ps
                break  # found the session but it isn't a plan set → fall through

    # 2. Newest planning session that IS a plan set (list is newest-first).
    for s in plan_sessions:
        ps = _plan_set_from_session(s)
        if ps is not None:
            return ps

    # 3. Fallback to the discovery.json planning groups.
    return _plan_set_from_discovery(folder_path, project_id)


def propose_handoff(folder_path, project_id, lane, source_session_id=None):
    """Build a read-only handoff proposal for a lane (shown BEFORE launching).

    For a build/execution lane: discover the most-recent plan set and return
    ``{has_plan_set, plan_set, message}`` where ``message`` is a short human
    "Execute on this plan set? (<title>, <impl_plan_rel>)". When no plan set
    exists, ``{has_plan_set: False}``.

    For a non-build lane: ``{has_plan_set: False}`` (the build→plan handoff the
    Done-when requires is intentionally focused; a general prior-stage seed is a
    later refinement). Never raises.
    """
    if lane not in BUILD_LANES:
        return {"has_plan_set": False}
    plan_set = discover_recent_plan_set(folder_path, project_id, source_session_id)
    if not plan_set:
        return {"has_plan_set": False}
    impl = plan_set.get("impl_plan_rel") or plan_set.get("master_plan_rel") or ""
    title = plan_set.get("title") or plan_set.get("plan_dir") or "plan set"
    message = "Execute on this plan set? (%s, %s)" % (title, impl)
    return {"has_plan_set": True, "plan_set": plan_set, "message": message}


def _within(base, target):
    """True iff ``target`` resolves to inside ``base`` (traversal guard)."""
    try:
        base_r = Path(base).resolve()
        tgt_r = Path(target).resolve()
        tgt_r.relative_to(base_r)
        return True
    except (ValueError, OSError):
        return False


def prime_worktree(worktree_path, plan_set, project_id=None):
    """Write a HANDOFF reference file into the worktree root surfacing the plan.

    The file lists the plan doc paths (which ALREADY EXIST in the checkout) and
    the "execute on this plan set" context, so the user/terminal can see exactly
    which plan to run. It does NOT copy plan contents and does NOT auto-seed a
    skill (Wave-3 bare-PTY contract).

    Traversal-safe: only ever writes ``HANDOFF.md`` directly inside
    ``worktree_path`` (the filename is a fixed constant — no caller-controlled
    path — but we still verify containment defensively). Returns
    ``{ok, handoff_file, referenced:[...]}``; ``ok=False`` with a ``reason`` on
    a missing worktree or no plan set. Never raises.
    """
    if not plan_set:
        return {"ok": False, "reason": "no-plan-set", "handoff_file": "",
                "referenced": []}
    try:
        wt = Path(worktree_path)
        if not wt.is_dir():
            return {"ok": False, "reason": "worktree-missing",
                    "handoff_file": "", "referenced": []}
    except OSError:
        return {"ok": False, "reason": "worktree-error",
                "handoff_file": "", "referenced": []}

    target = wt / HANDOFF_FILENAME
    if not _within(wt, target):  # defensive — fixed filename, can't escape
        return {"ok": False, "reason": "unsafe-path",
                "handoff_file": "", "referenced": []}

    doc_rels = list(plan_set.get("doc_rels") or [])
    master = plan_set.get("master_plan_rel", "")
    impl = plan_set.get("impl_plan_rel", "")
    title = plan_set.get("title", "") or plan_set.get("plan_dir", "")

    lines = [
        "# Stage Handoff — Execute on this plan set",
        "",
        "> Auto-generated by Anchor when this build session was launched."
        " **Structure only** — references to plan documents that already exist"
        " in this worktree checkout. No file contents are copied here.",
        "",
        "## Plan set",
        "",
        f"- title: {title}" if title else "- title: (untitled plan set)",
        f"- plan dir: `{plan_set.get('plan_dir', '')}`",
    ]
    if project_id:
        lines.append(f"- project: `{project_id}`")
    if plan_set.get("plan_session_id"):
        lines.append(f"- plan session: `{plan_set['plan_session_id']}`")
    lines += ["", "## Execute on these documents", ""]
    if master:
        lines.append(f"- **Master plan:** `{master}`")
    if impl:
        lines.append(f"- **Implementation plan:** `{impl}`")
    other = [r for r in doc_rels if r not in (master, impl)]
    if other:
        lines.append("- Supporting docs:")
        for r in other:
            lines.append(f"  - `{r}`")
    lines += [
        "",
        "These documents already exist in this checkout; open them to drive the"
        " build. (This is a reference only — no skill was auto-run.)",
        "",
    ]
    text = "\n".join(lines)
    try:
        target.write_text(text, encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "reason": f"write-failed: {exc}",
                "handoff_file": "", "referenced": []}
    return {"ok": True, "handoff_file": str(target), "referenced": doc_rels}


def record_handoff(folder_path, project_id, build_session_id, plan_set):
    """Record the handoff context in the per-project Anchor reference.

    Appends a structure-only entry to a ``handoffs`` list in ``discovery.json``
    (``{build_session_id, plan_session_id, plan_dir, doc_rels, when}``) under
    ``paths.WRITE_LOCK`` (atomic tmp+replace). Safe to commit — no file
    contents, no secrets. Idempotent-ish: re-recording the SAME
    (build_session_id, plan_session_id) pair updates the existing entry rather
    than duplicating it, so a retry never corrupts or bloats the file.

    Returns ``{ok, entry, count}`` or ``{ok: False, reason}``. Never raises.
    """
    if not plan_set:
        return {"ok": False, "reason": "no-plan-set"}
    entry = {
        "build_session_id": build_session_id or "",
        "plan_session_id": plan_set.get("plan_session_id", ""),
        "plan_dir": plan_set.get("plan_dir", ""),
        "doc_rels": list(plan_set.get("doc_rels") or []),
        "when": time.time(),
    }
    with _paths.WRITE_LOCK:
        p = _marker.sidecar_path(folder_path, project_id)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "reason": f"mkdir-failed: {exc}"}
        disc = {}
        if p.exists():
            try:
                loaded = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    disc = loaded
            except (json.JSONDecodeError, OSError):
                disc = {}
        handoffs = disc.get("handoffs")
        if not isinstance(handoffs, list):
            handoffs = []
        # Idempotent-ish upsert on (build_session_id, plan_session_id).
        replaced = False
        for i, h in enumerate(handoffs):
            if (isinstance(h, dict)
                    and h.get("build_session_id") == entry["build_session_id"]
                    and h.get("plan_session_id") == entry["plan_session_id"]):
                handoffs[i] = entry
                replaced = True
                break
        if not replaced:
            handoffs.append(entry)
        disc["handoffs"] = handoffs
        try:
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(disc, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(p)
        except OSError as exc:
            return {"ok": False, "reason": f"write-failed: {exc}"}
    return {"ok": True, "entry": entry, "count": len(handoffs)}
