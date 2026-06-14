#!/usr/bin/env python3
"""Anchor effort history + cost rollup + per-effort auto-commit (Wave 7).

An *effort* is one research/plan/build run for a project lane. Wave 6 records a
launch pointer-record per lane dir; Wave 7 turns efforts into **job-id-scoped
pointer-records** so a lane accumulates a *versioned history* (D5 — iterative,
nothing lost): re-running a lane appends a new effort record and NEVER deletes a
prior one. History reads return records **NEWEST-FIRST** (index 0 = most recent;
"current on top" — C5).

Storage layout (under the per-project store from ``rnd_registry``):

    <folder>/.anchor/projects/<id>/<lane-subdir>/
        efforts/
            <job_id>.pointer.json     ← one pointer-record per effort
        index.json                    ← ordered list of job_ids (append-only)

The pointer-record is a small JSON dict carrying the effort's identity, its
artifact filenames (``report.md`` / ``report.pdf`` when present), and — once the
job completes — the cost/usage/duration captured from the job's stream-json
``result`` envelope (``total_cost_usd`` / tokens / ``duration_ms``).

Cost rolls up: per-effort → per-lane → per-project (C — the tile + dashboard
rollup).

C9 backup: when an effort is *finalized*, its ``.anchor/`` pointer-record is
**auto-committed** (one commit per effort) in the PROJECT'S OWN folder repo,
reconciled with the ``.gitignore`` tracking policy (track small pointer-records;
ignore raw logs / PDFs / jobs). The commit is scoped strictly to the project's
folder path — NEVER the Anchor repo itself.

All writes run under ``paths.WRITE_LOCK``. Stdlib only (``git`` invoked as a
subprocess is allowed; it is a system tool, not a Python dependency).
"""

import hashlib
import json
import subprocess
import time
from pathlib import Path

import paths as _paths
import rnd_registry as _rnd

#: Marker on a pointer-record that was DISCOVERED from a pre-existing on-disk
#: artifact (brownfield), as opposed to an Anchor-RUN effort. Discovered records
#: carry real metadata only (rel path, mtime->created_at, title, kind) and NEVER
#: fabricated cost/tokens/session_id. They are derived (reconcilable): a rescan
#: PRUNES a discovered record whose artifact no longer exists on disk.
SOURCE_DISCOVERED = "discovered"
SOURCE_RUN = "run"

#: job_id prefix for discovered records (a stable, content-addressed hash of the
#: artifact's lane + relative path, so rescans are idempotent — no duplicates).
DISCOVERED_PREFIX = "disc-"

# Map the trio lane names → the per-project store subdir they write into. This
# mirrors ``lanes.LaneDef.output_subdir`` but is kept here so effort_history has
# no import dependency on the lanes module (which imports job_runner). Both the
# trio lane name ("plan") and the store subdir name ("planning") are accepted.
LANE_SUBDIR = {
    "research": "research",
    "plan": "planning",
    "planning": "planning",
    "build": "build",
    "deliverables": "deliverables",
    "grass": "grass",
}

#: Every CONTENT lane that holds effort records (cost-bearing rollup lanes PLUS
#: the cost-free ``grass`` ideas lane). This is the set used when MOVING/FOLDING
#: a project's full effort history (sibling adoption + the destructive
#: ``rnd_registry.reconcile_folder`` fold-then-delete), so grass ideas are never
#: silently lost when a folded sibling id is hard-deleted. NOTE: grass is
#: deliberately EXCLUDED from :data:`ROLLUP_LANES` (the COST rollup) because
#: grass ideas carry no cost — only the fold/adopt iteration uses this set.
FOLD_LANES = ("research", "planning", "build", "deliverables", "grass")

#: Subdirectory under a lane dir holding the per-effort pointer-records.
EFFORTS_DIRNAME = "efforts"
#: The append-only ordered index of effort job_ids for a lane.
INDEX_NAME = "index.json"
#: Pointer-record filename suffix (matches the .gitignore allow-list).
POINTER_SUFFIX = ".pointer.json"

#: Canonical report artifact filenames the viewer looks for.
REPORT_MD = "report.md"
REPORT_PDF = "report.pdf"


# ── Path helpers ────────────────────────────────────────────────────────────

def _resolve_subdir(lane: str) -> str:
    """Resolve a lane name (trio or store form) to its store subdir name."""
    return LANE_SUBDIR.get(lane, lane)


def lane_dir(folder_path, project_id: str, lane: str) -> Path:
    """``<folder>/.anchor/projects/<id>/<lane-subdir>/`` (not created)."""
    return _rnd.project_store_dir(folder_path, project_id) / _resolve_subdir(lane)


def efforts_dir(folder_path, project_id: str, lane: str) -> Path:
    """The ``efforts/`` dir holding per-effort pointer-records (not created)."""
    return lane_dir(folder_path, project_id, lane) / EFFORTS_DIRNAME


def _index_path(folder_path, project_id: str, lane: str) -> Path:
    return lane_dir(folder_path, project_id, lane) / INDEX_NAME


def _pointer_path(folder_path, project_id: str, lane: str, job_id: str) -> Path:
    return efforts_dir(folder_path, project_id, lane) / f"{job_id}{POINTER_SUFFIX}"


# ── Index (append-only, preserves order; newest-first is computed on read) ──

def _load_index(folder_path, project_id: str, lane: str) -> list:
    """Load the ordered list of effort job_ids (oldest-first on disk)."""
    p = _index_path(folder_path, project_id, lane)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def _save_index(folder_path, project_id: str, lane: str, order: list) -> None:
    p = _index_path(folder_path, project_id, lane)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(list(order), indent=2), encoding="utf-8")
    tmp.replace(p)


# ── Effort pointer-record CRUD (append/version — never delete; D5) ──────────

def record_effort(folder_path, project_id: str, lane: str, job_id: str,
                  skill: str = None, prompt_seed: str = None,
                  extra: dict = None) -> dict:
    """Create (or update-in-place) the pointer-record for an effort.

    APPEND semantics (D5): a *new* job_id appends a new effort to the lane's
    history and never disturbs prior efforts. Calling again with the SAME job_id
    updates that one record in place (e.g. to stamp cost on completion) without
    creating a duplicate or re-ordering history. Returns the stored record.

    All writes under ``paths.WRITE_LOCK``.
    """
    with _paths.WRITE_LOCK:
        ed = efforts_dir(folder_path, project_id, lane)
        ed.mkdir(parents=True, exist_ok=True)
        ppath = _pointer_path(folder_path, project_id, lane, job_id)
        if ppath.exists():
            try:
                rec = json.loads(ppath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                rec = {}
        else:
            rec = {}
        rec.setdefault("job_id", job_id)
        rec.setdefault("project_id", project_id)
        rec.setdefault("lane", _resolve_subdir(lane))
        rec.setdefault("created_at", time.time())
        if skill is not None:
            rec["skill"] = skill
        if prompt_seed is not None:
            rec["prompt_seed"] = prompt_seed
        if extra:
            rec.update(extra)
        ppath.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                         encoding="utf-8")
        # Append to the index iff this job_id is new (preserve prior order).
        order = _load_index(folder_path, project_id, lane)
        if job_id not in order:
            order.append(job_id)
            _save_index(folder_path, project_id, lane, order)
        return rec


def load_effort(folder_path, project_id: str, lane: str, job_id: str):
    """Return one effort's pointer-record dict, or ``None``."""
    p = _pointer_path(folder_path, project_id, lane, job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_efforts(folder_path, project_id: str, lane: str) -> list:
    """Return the lane's effort pointer-records, **NEWEST-FIRST** (AC1).

    index 0 == the most recent effort ("current on top", C5). Nothing is ever
    deleted by reads or re-runs — the index is append-only and reversed here.
    Pointer-records that are missing/corrupt are skipped (best-effort).
    """
    order = _load_index(folder_path, project_id, lane)
    out = []
    for job_id in reversed(order):  # newest-first
        rec = load_effort(folder_path, project_id, lane, job_id)
        if rec is not None:
            out.append(rec)
    return out


def latest_effort(folder_path, project_id: str, lane: str):
    """Return the most-recent effort pointer-record (index 0), or ``None``."""
    efforts = list_efforts(folder_path, project_id, lane)
    return efforts[0] if efforts else None


# ── Grass Catchers content feeds (Wave 5) ───────────────────────────────────

#: job_id prefix for an Anchor-CREATED grass idea (manual add / inbox promote).
#: Distinct from the discovered prefix so an idea card is honestly an Anchor
#: artifact, NOT a brownfield-discovered one.
IDEA_PREFIX = "idea-"

#: The Grass idea lifecycle (v5 Wave 5). An idea is captured RAW; developing it
#: with a tool (research/plan in the workbench terminal) yields a saved
#: refinement and marks it REFINED; promoting it into a lane marks it PROMOTED
#: and links the idea to the run it became. The legacy stored value ``"idea"``
#: is normalized to RAW so pre-v5 records keep working.
GRASS_RAW = "raw"
GRASS_REFINED = "refined"
GRASS_PROMOTED = "promoted"
GRASS_STATUSES = (GRASS_RAW, GRASS_REFINED, GRASS_PROMOTED)

#: Allowed status transitions. A forward walk (raw->refined->promoted) plus the
#: idempotent self-transition and the practical back-steps (re-refining a
#: promoted idea, or re-developing a refined one) — but never an unknown status.
_GRASS_TRANSITIONS = {
    GRASS_RAW: {GRASS_RAW, GRASS_REFINED, GRASS_PROMOTED},
    GRASS_REFINED: {GRASS_RAW, GRASS_REFINED, GRASS_PROMOTED},
    GRASS_PROMOTED: {GRASS_REFINED, GRASS_PROMOTED},
}

#: Subdir under the grass lane dir holding per-idea versioned refinements.
GRASS_REFINEMENTS_DIRNAME = "refinements"


def grass_status(rec: dict) -> str:
    """Normalize a grass idea record's lifecycle status to a GRASS_STATUSES value.

    Maps the legacy ``"idea"`` (and any missing/unknown value) to :data:`GRASS_RAW`
    so pre-v5 idea cards render with an honest status.
    """
    st = (rec or {}).get("status", "") or ""
    return st if st in GRASS_STATUSES else GRASS_RAW


def _new_idea_job_id() -> str:
    """A fresh, unique job_id for a manual/promoted grass idea."""
    return f"{IDEA_PREFIX}{hashlib.sha1(f'{time.time_ns()}'.encode()).hexdigest()[:16]}"


def grass_short_id(idea_id: str) -> str:
    """A short, stable, display-friendly id for an idea (mockup ``grass-1a2b``).

    Derived deterministically from the idea's stored job_id so the same idea
    always shows the same short id. The canonical ``idea_id`` (the stored
    ``job_id``) remains the lookup key; this is purely cosmetic.
    """
    raw = (idea_id or "").strip()
    if not raw:
        return "grass-0000"
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:4]
    return f"grass-{h}"


def add_idea(folder_path, project_id: str, text: str, notes: str = "") -> dict:
    """Record a manual Grass Catchers idea as a grass-lane effort card (Wave 5).

    A real Anchor-CREATED idea (``source=SOURCE_RUN``, ``kind="idea"``) — NOT a
    brownfield-discovered artifact. It carries the user's ``text`` as its title
    and an optional ``notes`` blob; it has NO cost / tokens / session_id (it is
    not a trio run). Appends a new grass effort, newest-first; nothing is
    overwritten. Returns the stored pointer-record. All writes under WRITE_LOCK
    (via :func:`record_effort`).
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("idea text required")
    jid = _new_idea_job_id()
    extra = {
        "source": SOURCE_RUN,
        "kind": "idea",
        "title": text,
        "notes": (notes or "").strip(),
        # v5 Wave 5: ideas carry a raw->refined->promoted lifecycle status. A
        # freshly captured idea is RAW. (The legacy value ``"idea"`` is treated
        # as RAW by :func:`grass_status` so old records keep working.)
        "status": GRASS_RAW,
    }
    return record_effort(folder_path, project_id, "grass", jid, extra=extra)


def promote_inbox(folder_path, project_id: str, inbox_item_text: str,
                  inbox_items=None) -> dict:
    """Promote an EXISTING INBOX.md item into a project's Grass Catchers (Wave 5).

    Reads the existing inbox (the caller supplies ``inbox_items`` parsed by the
    GUI/CLI's existing ``parse_inbox_from_md`` — no new inbox format is invented)
    and creates a grass card from the matching item. Matching is by exact text,
    then case-insensitive, then substring (first match wins).

    COPY-BY-DEFAULT (non-destructive): the inbox item is NOT removed from
    INBOX.md — the idea is COPIED into the project's grass lane so the inbox
    remains the user's untouched capture log. (The frozen plan does not direct a
    move/remove; copy is the safe default, leaving INBOX.md as the source of
    truth.) Returns the stored grass pointer-record.

    Raises ``ValueError`` if the item is not found in the supplied inbox.
    """
    want = (inbox_item_text or "").strip()
    if not want:
        raise ValueError("inbox item text required")
    items = inbox_items or []
    match = None
    for it in items:
        if (it.get("text") or "").strip() == want:
            match = it
            break
    if match is None:
        low = want.lower()
        for it in items:
            if (it.get("text") or "").strip().lower() == low:
                match = it
                break
    if match is None:
        low = want.lower()
        for it in items:
            if low in (it.get("text") or "").strip().lower():
                match = it
                break
    if match is None:
        raise ValueError(f"inbox item not found: {inbox_item_text}")

    jid = _new_idea_job_id()
    note_bits = []
    if match.get("date"):
        note_bits.append(f"from INBOX {match['date']}")
    if match.get("domain"):
        note_bits.append(f"[{match['domain']}]")
    extra = {
        "source": SOURCE_RUN,
        "kind": "idea",
        "title": (match.get("text") or "").strip(),
        "notes": " ".join(note_bits),
        "status": GRASS_RAW,
        "promoted_from": "inbox",
    }
    return record_effort(folder_path, project_id, "grass", jid, extra=extra)


#: The lanes a grass idea may be promoted into (v4 Wave 6). Only the two TRIO
#: starting lanes — a Research run or a Plan run — make sense as a seeded launch.
PROMOTE_LANES = ("research", "plan")


def get_grass_idea(folder_path, project_id: str, idea_id: str):
    """Return ONE grass idea pointer-record by its ``job_id``, or ``None``.

    Matches against the grass lane's effort records (manual adds, INBOX
    promotions, discovered idea-docs). Best-effort: an unknown id returns
    ``None`` (never raises).
    """
    want = (idea_id or "").strip()
    if not want:
        return None
    for rec in list_efforts(folder_path, project_id, "grass"):
        if (rec.get("job_id") or "") == want:
            return rec
    return None


def promote_grass_to_lane(project_id: str, idea_id: str, lane: str,
                          folder_path=None, backend=None) -> dict:
    """Promote a Grass Catcher idea into a NEW seeded session in ``lane`` (Wave 6).

    Looks up the grass idea by ``idea_id``, then starts a brand-new terminal
    session in the target lane (``research`` | ``plan``) **seeded with the idea
    text** by REUSING the Wave-1 seed path: it delegates to
    ``terminal_session.start_session(..., seed_context=<idea text>)``, so the
    single opening turn loads the lane's trio skill (researchPrime / Crucible)
    AND carries the idea as the thing to work on. The Wave-1 seed-once /
    no-re-emit discipline is inherited unchanged.

    COPY, NEVER DESTROY: the idea record is left untouched in the grass lane (a
    promotion is a copy). Returns the NEW session's registry record.

    Raises ``ValueError`` for an invalid lane (not research/plan) or an idea that
    is not found in the project's grass lane.
    """
    lane = (lane or "").strip()
    if lane not in PROMOTE_LANES:
        raise ValueError(
            "promote lane must be one of %s, got %r"
            % (", ".join(PROMOTE_LANES), lane))
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")

    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    idea_text = (idea.get("title") or "").strip()
    if not idea_text:
        raise ValueError("grass idea has no text: %s" % (idea_id,))

    # Reuse the Wave-1 seed path (do NOT fork seed logic): start_session writes
    # the lane skill seed + the idea exactly once. Lazy import to keep
    # effort_history free of a hard dependency on the terminal stack.
    import terminal_session as _ts
    label = "from grass: " + (idea_text[:40])
    kwargs = {"label": label, "seed_context": idea_text}
    if backend is not None:
        kwargs["backend"] = backend
    record = _ts.start_session(project_id, lane, **kwargs)
    # The idea REMAINS in grass — promotion copies, never moves. We only
    # ANNOTATE the idea record in place (status -> promoted + a link to the run
    # it became); nothing here deletes or rewrites the idea's identity/title.
    try:
        set_grass_status(folder_path, project_id, idea_id, GRASS_PROMOTED,
                         promoted_to_session=record.get("session_id"),
                         promoted_to_lane=lane)
    except Exception:
        # A failed annotation must never tear down a live, seeded session.
        pass
    return record


# ── Grass idea lifecycle: status + versioned refinements + develop/pull (W5) ─

def set_grass_status(folder_path, project_id: str, idea_id: str, status: str,
                     promoted_to_session: str = None,
                     promoted_to_lane: str = None) -> dict:
    """Set a grass idea's lifecycle status (raw/refined/promoted), validated.

    Rejects an unknown target status and an illegal transition (see
    :data:`_GRASS_TRANSITIONS`) with ``ValueError`` — so an idea can never land
    in a bogus state. When promoting, ``promoted_to_session`` / ``promoted_to_lane``
    are stored on the idea so a PROMOTED idea LINKS to the run it became.

    Updates the idea's pointer-record IN PLACE (same job_id) — the idea's
    identity/title/history are untouched (COPY-never-destroy). Returns the
    updated record. Raises ``ValueError`` for an unknown idea or status.
    """
    status = (status or "").strip()
    if status not in GRASS_STATUSES:
        raise ValueError(
            "grass status must be one of %s, got %r"
            % (", ".join(GRASS_STATUSES), status))
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    cur = grass_status(idea)
    if status not in _GRASS_TRANSITIONS.get(cur, set()):
        raise ValueError(
            "illegal grass status transition %s -> %s" % (cur, status))
    extra = {"status": status}
    if status == GRASS_PROMOTED:
        if promoted_to_session:
            extra["promoted_to_session"] = promoted_to_session
        if promoted_to_lane:
            extra["promoted_to_lane"] = promoted_to_lane
    return record_effort(folder_path, project_id, "grass",
                         idea.get("job_id", idea_id), extra=extra)


def _refinements_dir(folder_path, project_id: str, idea_id: str) -> Path:
    """``<grass-lane>/refinements/<sanitized-idea-id>/`` (not created)."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "_"
                   for c in (idea_id or "x"))
    return (lane_dir(folder_path, project_id, "grass")
            / GRASS_REFINEMENTS_DIRNAME / safe)


def _refinement_id(idea_id: str, n: int) -> str:
    """The logical, display id for refinement version ``n`` (``grass-<id>/dev-N``)."""
    return "%s/dev-%d" % (grass_short_id(idea_id), n)


def list_grass_refinements(folder_path, project_id: str, idea_id: str) -> list:
    """Return an idea's versioned refinements, **NEWEST-FIRST** (highest dev-N).

    Each refinement is a small JSON record:
    ``{refinement_id, idea_id, version, label, text, artifacts, session_id,
       created_at}``. Best-effort: a missing dir / corrupt file yields ``[]`` /
    is skipped. Never raises.
    """
    d = _refinements_dir(folder_path, project_id, idea_id)
    if not d.exists():
        return []
    out = []
    try:
        entries = list(d.glob("dev-*.json"))
    except OSError:
        return []
    for p in entries:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    out.sort(key=lambda r: int(r.get("version", 0) or 0), reverse=True)
    return out


def save_grass_refinement(folder_path, project_id: str, idea_id: str,
                          text: str = "", label: str = "",
                          artifacts=None, session_id: str = None) -> dict:
    """Append a NEW versioned refinement (``grass-<id>/dev-N``) for an idea (W5).

    The version ``N`` auto-increments (1-based) over the idea's existing
    refinements — nothing is overwritten (append-only history, newest-first on
    read). The refinement references produced ``text`` and/or ``artifacts`` (a
    list of folder-relative paths) and, when developed live, the ``session_id``
    that produced it. Saving a refinement marks the idea REFINED (raw->refined).

    Returns the stored refinement record. Raises ``ValueError`` for an unknown
    idea. All writes under WRITE_LOCK.
    """
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)
    with _paths.WRITE_LOCK:
        d = _refinements_dir(folder_path, project_id, jid)
        d.mkdir(parents=True, exist_ok=True)
        existing = list_grass_refinements(folder_path, project_id, jid)
        version = (max((int(r.get("version", 0) or 0) for r in existing),
                       default=0) + 1)
        rec = {
            "refinement_id": _refinement_id(jid, version),
            "idea_id": jid,
            "version": version,
            "label": (label or "").strip(),
            "text": (text or "").strip(),
            "artifacts": list(artifacts or []),
            "session_id": session_id or "",
            "created_at": time.time(),
        }
        p = d / ("dev-%d.json" % version)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
    # Mark the idea refined (idempotent if already refined; promoted stays
    # promoted — a promoted idea can still gain refinements without demotion).
    if grass_status(idea) == GRASS_RAW:
        try:
            set_grass_status(folder_path, project_id, jid, GRASS_REFINED)
        except ValueError:
            pass
    return rec


def _grass_develop_seed(idea: dict, refinements) -> str:
    """Build the seed_context for a develop/pull session: the idea text + its
    latest refinement(s), so the workbench session resumes from prior work."""
    bits = []
    title = (idea.get("title") or "").strip()
    if title:
        bits.append("Idea: " + title)
    notes = (idea.get("notes") or "").strip()
    if notes:
        bits.append("Notes: " + notes)
    for r in (refinements or [])[:3]:  # newest-first; cap context size
        rid = r.get("refinement_id", "")
        txt = (r.get("text") or "").strip()
        if txt:
            bits.append("Prior refinement %s: %s" % (rid, txt))
    return "\n".join(bits)


def develop_grass_idea(project_id: str, idea_id: str, lane: str,
                       folder_path=None, backend=None) -> dict:
    """DEVELOP a grass idea in a seeded workbench session (v5 Wave 5).

    Starts a NEW live terminal session in the target lane (``research`` | ``plan``)
    SEEDED (``seed_context``) with the idea text PLUS its latest refinements
    (reuses the Wave-1 seed path via ``terminal_session.start_session`` — never
    forks seed logic). The idea STAYS in grass (copy, never destroy). Returns the
    NEW session's registry record (the workbench terminal attaches to it).

    Unlike :func:`promote_grass_to_lane` (which marks the idea PROMOTED), develop
    keeps the idea available for further iteration; the *saved refinement* (via
    :func:`save_grass_refinement`) is what marks it REFINED.

    Raises ``ValueError`` for an invalid lane or an unknown idea.
    """
    lane = (lane or "").strip()
    if lane not in PROMOTE_LANES:
        raise ValueError(
            "develop lane must be one of %s, got %r"
            % (", ".join(PROMOTE_LANES), lane))
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    refinements = list_grass_refinements(folder_path, project_id,
                                         idea.get("job_id", idea_id))
    seed = _grass_develop_seed(idea, refinements)
    if not seed.strip():
        raise ValueError("grass idea has no text: %s" % (idea_id,))
    import terminal_session as _ts
    label = "develop: " + ((idea.get("title") or "")[:40])
    kwargs = {"label": label, "seed_context": seed}
    if backend is not None:
        kwargs["backend"] = backend
    return _ts.start_session(project_id, lane, **kwargs)


def pull_grass_refinement(project_id: str, idea_id: str, refinement_id: str,
                          lane: str, folder_path=None, backend=None) -> dict:
    """PULL a chosen refinement version into a NEW seeded session (v5 Wave 5).

    Seeds a fresh ``research`` | ``plan`` session with the chosen refinement's
    content (reuses the Wave-1 seed path) — "pull a refinement into another
    effort". The idea + refinement are left untouched. Returns the NEW session
    record.

    Raises ``ValueError`` for an invalid lane, unknown idea, or unknown
    refinement id.
    """
    lane = (lane or "").strip()
    if lane not in PROMOTE_LANES:
        raise ValueError(
            "pull lane must be one of %s, got %r"
            % (", ".join(PROMOTE_LANES), lane))
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)
    want = (refinement_id or "").strip()
    chosen = None
    for r in list_grass_refinements(folder_path, project_id, jid):
        if r.get("refinement_id") == want or str(r.get("version")) == want:
            chosen = r
            break
    if chosen is None:
        raise ValueError("refinement not found: %s" % (refinement_id,))
    title = (idea.get("title") or "").strip()
    rtext = (chosen.get("text") or "").strip()
    seed_bits = []
    if title:
        seed_bits.append("Idea: " + title)
    seed_bits.append("Pulled refinement %s: %s"
                     % (chosen.get("refinement_id", want), rtext or "(no text)"))
    seed = "\n".join(seed_bits)
    import terminal_session as _ts
    label = "pull %s" % (chosen.get("refinement_id", want))
    kwargs = {"label": label, "seed_context": seed}
    if backend is not None:
        kwargs["backend"] = backend
    return _ts.start_session(project_id, lane, **kwargs)


def grass_workbench_data(folder_path, project_id: str) -> list:
    """Aggregate the project's grass ideas for the workbench UI (read-only, W5).

    Returns a list (the grass lane order, newest-first) of dicts:
    ``{idea_id, short_id, title, notes, status, source, promoted_to_session,
       promoted_to_lane, refinements:[…newest-first…]}``. Best-effort; never
    raises.
    """
    out = []
    try:
        efforts = list_efforts(folder_path, project_id, "grass")
    except Exception:
        efforts = []
    for eff in efforts:
        jid = eff.get("job_id", "") or ""
        refs = list_grass_refinements(folder_path, project_id, jid)
        if is_discovered(eff):
            source = "discovered"
        elif (eff.get("promoted_from") or "") == "inbox":
            source = "inbox"
        else:
            source = "manual"
        out.append({
            "idea_id": jid,
            "short_id": grass_short_id(jid),
            "title": (eff.get("title") or "").strip(),
            "notes": (eff.get("notes") or "").strip(),
            "status": grass_status(eff),
            "source": source,
            "promoted_to_session": eff.get("promoted_to_session", ""),
            "promoted_to_lane": eff.get("promoted_to_lane", ""),
            "refinements": refs,
        })
    return out


# ── Honest brownfield discovery: adopt + reconcile (Wave 2) ─────────────────

def discovered_job_id(lane: str, rel: str) -> str:
    """Stable, content-addressed job_id for a discovered artifact.

    Derived purely from the (store) lane + the artifact's folder-relative path,
    so adopting the same artifact twice yields the SAME job_id (idempotent
    rescans — no duplicates). Never random.
    """
    h = hashlib.sha1(f"{_resolve_subdir(lane)}::{rel}".encode("utf-8")).hexdigest()
    return f"{DISCOVERED_PREFIX}{h[:16]}"


def is_discovered(rec: dict) -> bool:
    """True iff a pointer-record was discovered (brownfield), not Anchor-run."""
    return bool(rec) and rec.get("source") == SOURCE_DISCOVERED


def _delete_effort_record(folder_path, project_id: str, lane: str,
                          job_id: str) -> bool:
    """Remove ONE pointer-record + drop its id from the index (under lock).

    Only ever called for DISCOVERED records during reconciliation — real efforts
    are never pruned. Returns True if a record was removed.
    """
    with _paths.WRITE_LOCK:
        ppath = _pointer_path(folder_path, project_id, lane, job_id)
        removed = False
        try:
            if ppath.exists():
                ppath.unlink()
                removed = True
        except OSError:
            pass
        order = _load_index(folder_path, project_id, lane)
        if job_id in order:
            order = [j for j in order if j != job_id]
            _save_index(folder_path, project_id, lane, order)
            removed = True
        return removed


def adopt_discovered(folder_path, project_id: str, scan_result) -> dict:
    """Create/update DISCOVERED pointer-records for a folder's scanned artifacts.

    For every adoptable artifact in ``scan_result.by_lane`` (research / planning /
    build / deliverables) this upserts a pointer-record with:
      - a STABLE path-hash ``job_id`` (idempotent: rescans never duplicate),
      - ``source="discovered"``,
      - ``created_at`` = the artifact's mtime,
      - real ``title`` / ``kind`` / ``artifact_path`` (folder-relative),
      - NO cost / tokens / session_id (honesty contract).

    Then RECONCILES: any *previously discovered* record in those lanes whose
    artifact is no longer present in this scan is PRUNED (discovered records are
    derived). Real (run) efforts are NEVER touched. Returns a small report.

    All writes run under ``paths.WRITE_LOCK``.
    """
    adopted = []
    pruned = []
    with _paths.WRITE_LOCK:
        by_lane = getattr(scan_result, "by_lane", None) or {}
        for store_lane, artifacts in by_lane.items():
            # Desired discovered job_ids for this lane after this scan.
            desired = {}
            for art in artifacts:
                rel = art.get("rel", "")
                if not rel:
                    continue
                jid = discovered_job_id(store_lane, rel)
                desired[jid] = art
            # Upsert each desired discovered record.
            for jid, art in desired.items():
                extra = {
                    "source": SOURCE_DISCOVERED,
                    "kind": art.get("kind", ""),
                    "title": art.get("title", ""),
                    "artifact_path": art.get("rel", ""),
                    "status": "imported",
                }
                # created_at from the artifact mtime (real metadata only).
                rec = record_effort(folder_path, project_id, store_lane, jid,
                                    extra=extra)
                # Force created_at to the artifact mtime (record_effort defaults
                # to now() only when absent; ensure it reflects on-disk reality).
                mtime = art.get("mtime")
                if mtime:
                    rec = _set_created_at(folder_path, project_id, store_lane,
                                          jid, float(mtime))
                adopted.append(rec)
            # Reconcile: prune discovered records in this lane not in `desired`.
            for existing in list_efforts(folder_path, project_id, store_lane):
                if not is_discovered(existing):
                    continue  # never touch real efforts
                ejid = existing.get("job_id", "")
                if ejid and ejid not in desired:
                    if _delete_effort_record(folder_path, project_id,
                                             store_lane, ejid):
                        pruned.append(ejid)
        # Reconcile lanes that had discovered records but appear with ZERO
        # artifacts in this scan (handled by the loop above only if the lane key
        # is present in by_lane; ensure all standard lanes are reconciled).
        scanned_lanes = set(by_lane.keys())
        for store_lane in ROLLUP_LANES:
            if store_lane in scanned_lanes:
                continue
            for existing in list_efforts(folder_path, project_id, store_lane):
                if is_discovered(existing):
                    ejid = existing.get("job_id", "")
                    if ejid and _delete_effort_record(folder_path, project_id,
                                                      store_lane, ejid):
                        pruned.append(ejid)
    return {"adopted": len(adopted), "pruned": len(pruned),
            "pruned_ids": pruned}


def _set_created_at(folder_path, project_id: str, lane: str, job_id: str,
                    ts: float) -> dict:
    """Stamp ``created_at`` on an existing pointer-record (under lock)."""
    with _paths.WRITE_LOCK:
        ppath = _pointer_path(folder_path, project_id, lane, job_id)
        if not ppath.exists():
            return {}
        try:
            rec = json.loads(ppath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        rec["created_at"] = ts
        ppath.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                         encoding="utf-8")
        return rec


def reconcile_discovered(folder_path, project_id: str) -> dict:
    """Prune DISCOVERED records whose on-disk artifact no longer exists.

    Independent of a fresh scan: checks each discovered record's
    ``artifact_path`` against the folder and removes the record if the file is
    gone. Real efforts are never touched. Returns ``{"pruned": n,
    "pruned_ids": [...]}``.
    """
    pruned = []
    folder = Path(folder_path)
    with _paths.WRITE_LOCK:
        for store_lane in ROLLUP_LANES:
            for existing in list_efforts(folder_path, project_id, store_lane):
                if not is_discovered(existing):
                    continue
                rel = existing.get("artifact_path", "")
                exists = False
                if rel:
                    try:
                        exists = (folder / rel).exists()
                    except OSError:
                        exists = False
                if not exists:
                    ejid = existing.get("job_id", "")
                    if ejid and _delete_effort_record(folder_path, project_id,
                                                      store_lane, ejid):
                        pruned.append(ejid)
    return {"pruned": len(pruned), "pruned_ids": pruned}


# ── Sibling-store adoption (Wave 2: folder-history unification) ──────────────

def _projects_root(folder_path) -> Path:
    """``<folder>/.anchor/projects/`` — the parent of every per-project store."""
    return Path(folder_path) / ".anchor" / "projects"


def sibling_store_ids(folder_path, exclude_id: str = None) -> list:
    """Project-ids that have an on-disk store under THIS folder's ``.anchor``.

    Reads ``<folder>/.anchor/projects/*`` directory names — these are the
    project-ids whose effort stores physically live alongside ``exclude_id`` for
    the SAME folder. ``exclude_id`` (typically the target/active id) is omitted.

    This is how sibling adoption finds same-folder stores: trio runs recorded
    under one project-id's store are invisible to a sibling id for the same
    folder until they are adopted across. Best-effort: a missing/unreadable
    ``.anchor`` yields ``[]``. Returns sorted ids for determinism.
    """
    root = _projects_root(folder_path)
    out = []
    try:
        if not root.is_dir():
            return []
        for child in root.iterdir():
            try:
                if child.is_dir() and child.name and child.name != exclude_id:
                    out.append(child.name)
            except OSError:
                continue
    except OSError:
        return []
    return sorted(out)


def _import_record_into(folder_path, target_id: str, lane: str,
                        rec: dict) -> dict:
    """Upsert ONE sibling effort-record into ``target_id``'s lane store.

    The record is imported as a DISCOVERED (imported) effort so it never
    fabricates cost into the target's real-effort rollup (honesty contract).
    Its identity (``job_id``) is preserved so re-importing is idempotent — the
    same sibling effort never duplicates under the target. Real run-cost is kept
    as readable metadata but the record is flagged discovered for rollups.
    Returns the stored record.
    """
    jid = (rec.get("job_id") or "").strip()
    if not jid:
        # Stable fallback id from the record's identity so re-import is idempotent.
        h = hashlib.sha1(
            "\x00".join(str(rec.get(k, "")) for k in
                        ("artifact_path", "created_at", "skill", "kind",
                         "title")).encode("utf-8")).hexdigest()
        jid = f"{DISCOVERED_PREFIX}sib-{h[:16]}"
    extra = {k: v for k, v in rec.items()
             if k not in ("job_id", "project_id", "lane")}
    # Mark as imported (folded-in) history; preserve the original provenance and
    # owning id so the move is auditable and rollups stay honest.
    extra.setdefault("imported_from", rec.get("project_id", ""))
    extra["source"] = SOURCE_DISCOVERED
    stored = record_effort(folder_path, target_id, lane, jid, extra=extra)
    ca = rec.get("created_at")
    if ca:
        try:
            stored = _set_created_at(folder_path, target_id, lane, jid,
                                     float(ca))
        except (TypeError, ValueError):
            pass
    return stored


def adopt_sibling_sessions(folder_path, target_id: str,
                           source_ids=None) -> dict:
    """Fold sibling project-ids' real efforts into ``target_id`` as imported.

    For each sibling id (default: every OTHER on-disk store under this folder),
    every effort in every CONTENT lane (:data:`FOLD_LANES` — the rollup lanes
    PLUS the cost-free ``grass`` ideas lane) is upserted into ``target_id``'s
    matching lane store via :func:`_import_record_into`. Folding the grass lane
    too means manually-added / adopted grass IDEAS are migrated before any
    hard-delete and are never silently lost. The target therefore SEES trio
    work that was originally recorded under a different project-id for the SAME
    folder — fixing the bug where research run under one id is invisible to a
    sibling id for the same folder.

    Idempotent: importing the same sibling effort twice does not duplicate it
    (job_id-keyed upsert). The sibling stores are NOT modified or deleted here —
    that hard-delete is the explicit, reviewable :func:`rnd_registry.reconcile_folder`
    step. Returns ``{"imported": n, "from": [...], "by_lane": {...}}``.

    All writes run under ``paths.WRITE_LOCK``.
    """
    if source_ids is None:
        source_ids = sibling_store_ids(folder_path, exclude_id=target_id)
    else:
        source_ids = [s for s in source_ids if s and s != target_id]
    imported = 0
    by_lane = {lane: 0 for lane in FOLD_LANES}
    used_sources = []
    with _paths.WRITE_LOCK:
        for sid in source_ids:
            touched = False
            for store_lane in FOLD_LANES:
                for rec in list_efforts(folder_path, sid, store_lane):
                    _import_record_into(folder_path, target_id, store_lane, rec)
                    imported += 1
                    by_lane[store_lane] += 1
                    touched = True
            if touched:
                used_sources.append(sid)
    return {"imported": imported, "from": used_sources, "by_lane": by_lane}


# ── Attaching cost from a completed job's result envelope ───────────────────

def attach_cost(folder_path, project_id: str, lane: str, job_id: str,
                job_record: dict) -> dict:
    """Stamp the completed job's cost/usage/duration onto its effort record.

    ``job_record`` is the durable record from ``job_runner`` (which captured the
    stream-json ``result`` envelope into ``record["cost"]``). The cost block —
    ``total_cost_usd`` / tokens / ``duration_ms`` — is copied onto the effort
    pointer-record and the report-artifact presence (report.md / report.pdf) is
    refreshed. Returns the updated effort record.
    """
    cost = (job_record or {}).get("cost") or {}
    extra = {
        "status": (job_record or {}).get("status"),
        "cost": {
            "total_cost_usd": float(cost.get("total_cost_usd", 0.0) or 0.0),
            "duration_ms": int(cost.get("duration_ms", 0) or 0),
            "input_tokens": int(cost.get("input_tokens", 0) or 0),
            "output_tokens": int(cost.get("output_tokens", 0) or 0),
            "total_tokens": int(cost.get("total_tokens", 0) or 0),
        },
        "session_id": (job_record or {}).get("session_id"),
        "finished_at": (job_record or {}).get("finished_at"),
        "artifacts": detect_artifacts(folder_path, project_id, lane, job_id),
    }
    return record_effort(folder_path, project_id, lane, job_id, extra=extra)


def detect_artifacts(folder_path, project_id: str, lane: str,
                     job_id: str = None) -> dict:
    """Report which report artifacts exist for an effort's lane dir.

    The viewer's PDF-default detection keys off this. Artifacts for an effort
    live either directly in the lane dir (single-effort convenience) or under an
    effort-scoped ``efforts/<job_id>/`` dir. Both are checked; the effort-scoped
    location wins when present.

    Returns ``{"report_md": bool, "report_pdf": bool, "md_path": str|None,
    "pdf_path": str|None}``.
    """
    ld = lane_dir(folder_path, project_id, lane)
    candidates = []
    if job_id:
        candidates.append(efforts_dir(folder_path, project_id, lane) / job_id)
    candidates.append(ld)
    md_path = None
    pdf_path = None
    for base in candidates:
        m = base / REPORT_MD
        p = base / REPORT_PDF
        if md_path is None and m.exists():
            md_path = m
        if pdf_path is None and p.exists():
            pdf_path = p
    return {
        "report_md": md_path is not None,
        "report_pdf": pdf_path is not None,
        "md_path": str(md_path) if md_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
    }


# ── Cost rollups: per-effort → per-lane → per-project ───────────────────────

def _empty_rollup() -> dict:
    return {
        "total_cost_usd": 0.0,
        "duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "effort_count": 0,
        # Discovered (brownfield-imported) efforts are counted SEPARATELY and
        # NEVER contribute to effort_count / cost (honesty contract). They carry
        # no real cost, so discovered_cost is always 0.
        "discovered_count": 0,
        "discovered_cost": 0.0,
    }


def _add_cost(acc: dict, cost: dict) -> None:
    acc["total_cost_usd"] += float(cost.get("total_cost_usd", 0.0) or 0.0)
    acc["duration_ms"] += int(cost.get("duration_ms", 0) or 0)
    acc["input_tokens"] += int(cost.get("input_tokens", 0) or 0)
    acc["output_tokens"] += int(cost.get("output_tokens", 0) or 0)
    acc["total_tokens"] += int(cost.get("total_tokens", 0) or 0)


def effort_cost(effort: dict) -> dict:
    """Return one effort's cost block (zero-filled if it has none yet)."""
    cost = (effort or {}).get("cost") or {}
    out = _empty_rollup()
    out["effort_count"] = 1
    _add_cost(out, cost)
    return out


def lane_rollup(folder_path, project_id: str, lane: str) -> dict:
    """Aggregate cost across the REAL efforts in a lane (per-lane rollup).

    Honesty contract: DISCOVERED (brownfield-imported) efforts are EXCLUDED from
    ``effort_count`` and cost; they are tallied separately in
    ``discovered_count`` (and ``discovered_cost`` is always 0). ``list_efforts``
    still returns them for rendering — only this rollup excludes them.
    """
    acc = _empty_rollup()
    for effort in list_efforts(folder_path, project_id, lane):
        if is_discovered(effort):
            acc["discovered_count"] += 1
            continue
        cost = effort.get("cost") or {}
        _add_cost(acc, cost)
        acc["effort_count"] += 1
    return acc


#: The lanes whose efforts roll up into the project total.
ROLLUP_LANES = ("research", "planning", "build", "deliverables")


def project_rollup(project_id: str, folder_path=None) -> dict:
    """Aggregate cost across every lane of a project (per-project rollup).

    Returns ``{"total": <rollup>, "lanes": {lane: <rollup>}}`` so the tile can
    show the project total and the dashboard can show the per-lane breakdown.
    If ``folder_path`` is omitted it is resolved from the registry.
    """
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        folder_path = (proj or {}).get("folder_path", "")
    total = _empty_rollup()
    lanes_out = {}
    for lane in ROLLUP_LANES:
        lr = lane_rollup(folder_path, project_id, lane)
        lanes_out[lane] = lr
        total["total_cost_usd"] += lr["total_cost_usd"]
        total["duration_ms"] += lr["duration_ms"]
        total["input_tokens"] += lr["input_tokens"]
        total["output_tokens"] += lr["output_tokens"]
        total["total_tokens"] += lr["total_tokens"]
        total["effort_count"] += lr["effort_count"]
        total["discovered_count"] += lr["discovered_count"]
    return {"total": total, "lanes": lanes_out}


# ── Project cost/tokens/time rollup over RUN sessions (v4 Wave 3) ───────────
#
# The v4 cockpit shows a per-project ``Σ tokens · $ · time`` rollup with a
# lifetime / 30-day toggle. Unlike :func:`project_rollup` (which sums every real
# effort), this rollup is SESSION-SCOPED and honesty-bounded:
#
#   - It sums ``job_runner`` COST RECORDS for the project's RUN-PROVENANCE
#     sessions ONLY (``sessions.list_sessions`` groups efforts into sessions and
#     tags each ``provenance`` = "run" | "imported"). IMPORTED / DISCOVERED
#     sessions contribute ZERO — never fabricated.
#   - ``window='30d'`` excludes cost records older than 30 days relative to
#     ``now`` (injectable for deterministic tests; defaults to real ``time``).
#
# Returns ``{"tokens", "cost_usd", "wall_clock_ms", "sessions"}`` where
# ``sessions`` is the count of RUN sessions that contributed at least one
# in-window member. Stdlib only.

#: Seconds in the 30-day rolling window.
WINDOW_30D_SECONDS = 30 * 24 * 60 * 60.0

#: Accepted ``window`` values for :func:`project_effort_rollup`.
WINDOW_LIFETIME = "lifetime"
WINDOW_30D = "30d"


def _member_when(member: dict) -> float:
    """A member's cost timestamp for windowing: ``finished_at`` else ``created_at``.

    ``attach_cost`` stamps ``finished_at`` (job completion) alongside the cost
    block; we prefer it as the "when this cost was incurred" time and fall back
    to the effort's ``created_at`` (launch time) when a finish time is absent.
    Returns 0.0 when neither is parseable.
    """
    for key in ("finished_at", "created_at"):
        val = member.get(key)
        if val in (None, ""):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def project_effort_rollup(project_id: str, window: str = WINDOW_LIFETIME,
                          now=None, folder_path=None) -> dict:
    """Per-project cost/tokens/time rollup over RUN sessions (v4 Wave 3).

    Sums ``job_runner`` cost records for the project's RUN-provenance sessions
    only (imported/discovered sessions contribute 0 — never fabricated). With
    ``window='30d'`` only cost records whose timestamp is within the last 30 days
    of ``now`` are counted; ``window='lifetime'`` (default) counts all of them.

    ``now`` is injectable (a float epoch) for deterministic tests; it defaults to
    the real clock. ``folder_path`` is resolved from the registry when omitted
    (mirrors :func:`project_rollup`).

    Returns ``{"tokens": int, "cost_usd": float, "wall_clock_ms": int,
    "sessions": int}`` where ``sessions`` is the number of RUN sessions that
    contributed at least one in-window cost record. Stdlib only; never raises.
    """
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        folder_path = (proj or {}).get("folder_path", "")
    cutoff = None
    if window == WINDOW_30D:
        ref = float(now) if now is not None else time.time()
        cutoff = ref - WINDOW_30D_SECONDS

    # Lazy import to avoid the sessions↔effort_history cycle at module load.
    import sessions as _sessions

    tokens = 0
    cost_usd = 0.0
    wall_clock_ms = 0
    session_count = 0
    for lane in ROLLUP_LANES:
        try:
            lane_sessions = _sessions.list_sessions(folder_path, project_id, lane)
        except Exception:
            lane_sessions = []
        for sess in lane_sessions:
            # RUN-provenance only — imported/discovered sessions add nothing.
            if (sess.get("provenance") or "") != _sessions.PROV_RUN:
                continue
            contributed = False
            for member in (sess.get("member_files", []) or []):
                # Defensive: skip any discovered member inside a run session
                # (it carries no real cost — honesty contract).
                if is_discovered(member):
                    continue
                if cutoff is not None and _member_when(member) < cutoff:
                    continue
                cost = member.get("cost") or {}
                m_tokens = int(cost.get("total_tokens", 0) or 0)
                if not m_tokens:
                    m_tokens = (int(cost.get("input_tokens", 0) or 0)
                                + int(cost.get("output_tokens", 0) or 0))
                tokens += m_tokens
                wall_clock_ms += int(cost.get("duration_ms", 0) or 0)
                try:
                    cost_usd += float(cost.get("total_cost_usd", 0.0) or 0.0)
                except (TypeError, ValueError):
                    pass
                contributed = True
            if contributed:
                session_count += 1
    return {
        "tokens": tokens,
        "cost_usd": round(cost_usd, 6),
        "wall_clock_ms": wall_clock_ms,
        "sessions": session_count,
    }


# ── C9: per-effort auto-commit of the .anchor/ pointer-record ───────────────

def _git(folder: Path, *args, check=False, timeout=30) -> subprocess.CompletedProcess:
    """Run a git subcommand scoped to ``folder`` (``-C <folder>``).

    Never touches any repo other than ``folder``. ``check`` raises on non-zero.
    """
    cmd = ["git", "-C", str(folder), *args]
    return subprocess.run(cmd, capture_output=True, text=True,
                          check=check, timeout=timeout)


def _is_git_repo(folder: Path) -> bool:
    try:
        r = _git(folder, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def _is_anchor_repo(folder: Path, code: Path) -> bool:
    """True if ``folder`` is the Anchor code repo root (must not be committed).

    Compares the resolved path equality and, when both exist, also uses
    ``os.path.samefile`` to catch path aliasing (case differences, short paths,
    symlinks) so the guard cannot be sidestepped by an alternate spelling.
    """
    try:
        if folder.resolve() == code:
            return True
    except OSError:
        pass
    try:
        import os
        if folder.exists() and code.exists() and os.path.samefile(folder, code):
            return True
    except OSError:
        pass
    return False


def auto_commit_effort(folder_path, project_id: str, lane: str, job_id: str,
                       allow_init: bool = False) -> dict:
    """Auto-commit ONE effort's ``.anchor/`` pointer-record (C9, AC4).

    Commits exactly the effort's pointer-record + the lane index (the small,
    git-trackable files) in the PROJECT'S OWN folder repo — one commit per
    finalized effort. The ``.anchor/.gitignore`` tracking policy keeps raw
    logs / PDFs / jobs OUT of the commit (they are ignored), so only the
    pointer-records land in git (reconciling C9 git-trackable with C10 no-leak).

    SCOPE GUARANTEE: every git invocation is ``git -C <folder_path> ...`` — the
    commit is scoped strictly to the project's folder. This function must only
    ever be pointed at a project folder (a tmp repo in tests), NEVER the Anchor
    repo. It does NOT init a repo unless ``allow_init`` is explicitly set, and it
    never pushes.

    Returns ``{"committed": bool, "reason": str, "commit": <sha>|None}``.
    """
    folder = Path(folder_path)
    if not folder.exists():
        return {"committed": False, "reason": "folder-missing", "commit": None}

    # SCOPE GUARD (C9): never auto-commit the Anchor code repo itself. If the
    # project folder resolves to the Anchor code dir (e.g. Anchor dogfood-
    # registered with folder_path == C:\dev\Anchor), refuse outright — do not
    # stage or commit anything.
    code = _paths.CODE_DIR.resolve()
    if _is_anchor_repo(folder, code):
        return {"committed": False, "reason": "refused-anchor-repo",
                "commit": None}

    if not _is_git_repo(folder):
        if not allow_init:
            return {"committed": False, "reason": "not-a-git-repo", "commit": None}
        try:
            _git(folder, "init", check=True)
        except (OSError, subprocess.SubprocessError):
            return {"committed": False, "reason": "init-failed", "commit": None}

    # Paths to stage: this effort's pointer-record + the lane index. Both are
    # small git-trackable pointer files (the .gitignore allow-list re-includes
    # *.pointer.json and index.json even though jobs/logs/pdf are ignored).
    ppath = _pointer_path(folder, project_id, lane, job_id)
    ipath = _index_path(folder, project_id, lane)
    rel_targets = []
    for p in (ppath, ipath):
        if p.exists():
            try:
                rel_targets.append(str(p.relative_to(folder)))
            except ValueError:
                rel_targets.append(str(p))
    if not rel_targets:
        return {"committed": False, "reason": "nothing-to-commit", "commit": None}

    with _paths.WRITE_LOCK:
        # Stage only the pointer-record + index (respecting .gitignore via -f only
        # where the allow-list re-includes them; they are NOT ignored, so a plain
        # add suffices and ignored siblings are never staged).
        try:
            _git(folder, "add", "--", *rel_targets, check=True)
        except (OSError, subprocess.SubprocessError):
            return {"committed": False, "reason": "add-failed", "commit": None}

        # If nothing is actually staged (e.g. unchanged), report no-op rather
        # than producing an empty commit.
        diff = _git(folder, "diff", "--cached", "--name-only")
        if not (diff.stdout or "").strip():
            return {"committed": False, "reason": "no-staged-changes",
                    "commit": None}

        msg = f"anchor: effort {lane}/{job_id} ({project_id})"
        # Identity is set locally on the project repo so the commit never depends
        # on global git config (and never touches the Anchor repo's config).
        env_args = [
            "-c", "user.name=Anchor",
            "-c", "user.email=anchor@localhost",
            "-c", "commit.gpgsign=false",
        ]
        try:
            r = subprocess.run(
                ["git", "-C", str(folder), *env_args, "commit",
                 "--no-verify", "-m", msg, "--", *rel_targets],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return {"committed": False, "reason": "commit-failed", "commit": None}
        if r.returncode != 0:
            return {"committed": False, "reason": "commit-nonzero",
                    "commit": None, "stderr": r.stderr}

        sha = _git(folder, "rev-parse", "HEAD")
        return {"committed": True, "reason": "ok",
                "commit": (sha.stdout or "").strip()}


def finalize_effort(folder_path, project_id: str, lane: str, job_id: str,
                    job_record: dict, auto_commit: bool = True,
                    allow_init: bool = False) -> dict:
    """Finalize a completed effort: attach cost, then auto-commit (one commit).

    The single entry point a caller uses when a job reaches a terminal status:
    1. Attach the job's result-envelope cost/usage/duration onto the effort
       pointer-record (and refresh artifact presence).
    2. Auto-commit that pointer-record (C9, AC4) — scoped to the project folder.

    Returns ``{"effort": <record>, "commit": <auto_commit_effort result>}``.
    """
    effort = attach_cost(folder_path, project_id, lane, job_id, job_record)
    commit = {"committed": False, "reason": "skipped", "commit": None}
    if auto_commit:
        commit = auto_commit_effort(folder_path, project_id, lane, job_id,
                                    allow_init=allow_init)
    return {"effort": effort, "commit": commit}
