#!/usr/bin/env python3
"""Anchor R&D project registry — thin, id-keyed (stdlib only).

Wave 3 of the R&D control surface. This is a NEW, parallel registry distinct
from the existing life-domain projects in ``PROJECTS.md`` (Master Plan D5).

Frozen design (MASTER-PLAN.md "Architecture (frozen)" + D5):
- An R&D project = ``{id, name, folder_path, priority, state}``.
- The registry is keyed by **id**; ``folder_path`` is **NOT** unique, so N
  projects may share one folder. The view groups projects by folder.
- Persisted as JSON under ``ANCHOR_DATA_DIR`` (resolved via ``paths``), never a
  hard-coded location. Every mutation runs under ``paths.WRITE_LOCK`` so
  concurrent ``ThreadingHTTPServer`` writers cannot lose an update.
- Per-project artifacts live under ``<folder>/.anchor/projects/<id>/`` =
  ``research/ planning/ build/ deliverables/ jobs/`` so folder-sharing projects
  never collide.
- Lifecycle states (C7): priority change, archive, future-work are **retained,
  not deleted**. A folder that has gone missing yields a ``path-missing`` state
  (best-effort, surfaced on read — not a crash).

Stdlib only. No third-party imports.
"""

import json
import uuid
from pathlib import Path

import paths as _paths

# Registry JSON filename, stored at the data-dir root.
REGISTRY_NAME = "rnd_registry.json"

# Lane subdirectories scaffolded under each project's namespace.
LANE_DIRS = ("research", "planning", "build", "deliverables", "jobs")

# Canonical lifecycle states. ``active`` is the default; ``archived`` and
# ``future`` are retained (not deleted); ``path-missing`` is computed on read
# when a project's folder has disappeared.
STATE_ACTIVE = "active"
STATE_ARCHIVED = "archived"
STATE_FUTURE = "future"
STATE_RETIRED = "retired"          # cancelled / done-with (kept, reviewable)
STATE_PATH_MISSING = "path-missing"

VALID_STORED_STATES = {STATE_ACTIVE, STATE_ARCHIVED, STATE_FUTURE, STATE_RETIRED}
#: States that are NOT active (shown on the Archive/Inactive view, not the main one).
INACTIVE_STATES = {STATE_ARCHIVED, STATE_FUTURE, STATE_RETIRED}

# The four R&D lanes shown on the project status line (UX design: 4-state
# status line for Research / Planning / Build / Deliverables).
STATUS_LANES = ("research", "planning", "build", "deliverables")
STATUS_NONE_YET = "none-yet"


# ── Persistence ─────────────────────────────────────────────────────────

def registry_path() -> Path:
    """Absolute path to the registry JSON file under ANCHOR_DATA_DIR."""
    return _paths.data_dir() / REGISTRY_NAME


def _new_id() -> str:
    """Generate a fresh, stable, collision-resistant id (stdlib uuid4 hex)."""
    return uuid.uuid4().hex


def load_registry() -> dict:
    """Load the registry as a dict ``{id: entry}``.

    Returns an empty dict if the file does not exist or is unreadable/corrupt
    (best-effort — a corrupt registry must not crash the dashboard). The JSON
    on disk is a list of entries; this returns them keyed by id for O(1) lookup.
    """
    p = registry_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and e.get("id"):
                out[e["id"]] = _normalize(e)
    elif isinstance(raw, dict):
        # Tolerate an already-keyed dict form too.
        for k, e in raw.items():
            if isinstance(e, dict):
                e = dict(e)
                e.setdefault("id", k)
                out[e["id"]] = _normalize(e)
    return out


def _normalize(entry: dict) -> dict:
    """Coerce an entry to the canonical ``{id,name,folder_path,priority,state}``."""
    folder = entry.get("folder_path", "")
    try:
        folder_path = str(Path(folder)) if folder else ""
    except (TypeError, ValueError):
        folder_path = str(folder)
    state = entry.get("state", STATE_ACTIVE)
    if state not in VALID_STORED_STATES and state != STATE_PATH_MISSING:
        state = STATE_ACTIVE
    try:
        priority = int(entry.get("priority", 2))
    except (TypeError, ValueError):
        priority = 2
    return {
        "id": entry.get("id"),
        "name": entry.get("name", ""),
        "folder_path": folder_path,
        "priority": priority,
        "state": state,
        "notes": (entry.get("notes") or ""),
    }


def _save_registry(reg: dict) -> None:
    """Persist the registry (dict keyed by id) as a JSON list, under the lock."""
    with _paths.WRITE_LOCK:
        _paths.data_dir().mkdir(parents=True, exist_ok=True)
        items = [reg[k] for k in reg]
        registry_path().write_text(
            json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8"
        )


# ── Per-project store scaffold ──────────────────────────────────────────

def project_store_dir(folder_path, project_id: str) -> Path:
    """Return ``<folder>/.anchor/projects/<id>/`` (not created)."""
    return Path(folder_path) / ".anchor" / "projects" / project_id


def scaffold_project_store(folder_path, project_id: str) -> Path:
    """Create ``<folder>/.anchor/projects/<id>/{lanes}/`` + the tracking policy.

    Idempotent. Returns the project store dir. Writes a minimal ``.gitignore``
    + ``README`` at the ``.anchor/`` root that reconciles C9 (git-trackable
    pointer-records) with C10 (no personal-data leak): pointer-record JSON is
    trackable, but heavy/raw artifacts and any logs are ignored.
    """
    with _paths.WRITE_LOCK:
        store = project_store_dir(folder_path, project_id)
        for lane in LANE_DIRS:
            (store / lane).mkdir(parents=True, exist_ok=True)
        _write_tracking_policy(Path(folder_path) / ".anchor")
        return store


_GITIGNORE_BODY = """# Anchor R&D per-project store — tracking policy (reconciles C9 + C10).
#
# C9 (durable/git-trackable): the lightweight JSON *pointer-records* that index
#   each project's efforts ARE meant to be committed so history survives.
# C10 (no personal-data leak / shareable distro): raw run logs, large engine
#   outputs, and anything that may carry absolute paths / tokens / personal
#   data are git-IGNORED here and excluded by the distribution scan (Wave 8).
#
# Default: ignore the heavy/volatile artifacts; allow-list the pointer records.

projects/*/jobs/
projects/*/**/*.log
projects/*/**/*.pdf
projects/*/**/raw/

# Re-include the small pointer-record JSON index files (git-trackable).
!projects/*/**/index.json
!projects/*/**/*.pointer.json
"""

_README_BODY = """# .anchor/ — Anchor R&D per-project store

This directory is created and managed by Anchor's R&D control surface. Each
registered project gets an isolated namespace at:

    .anchor/projects/<project-id>/
        research/      planning/      build/      deliverables/      jobs/

Multiple projects may share one folder; each has its own `<project-id>` subtree,
so their stores never collide.

## Tracking policy (C9 git-trackable vs C10 no-leak)

- **Tracked (C9):** small JSON *pointer-records* that index efforts/versions —
  these are committed so effort history is durable across restarts.
- **Ignored (C10):** raw job logs, large generated artifacts (PDF), and any
  `raw/` payloads that could carry absolute paths, tokens, or personal data.
  The distribution build (Wave 8) additionally scans for and refuses to ship
  anything under `.anchor/`.

See the sibling `.gitignore` for the exact rules.
"""


def _write_tracking_policy(anchor_dir: Path) -> None:
    """Write the .anchor/.gitignore + .anchor/README if absent (idempotent)."""
    anchor_dir.mkdir(parents=True, exist_ok=True)
    gi = anchor_dir / ".gitignore"
    if not gi.exists():
        gi.write_text(_GITIGNORE_BODY, encoding="utf-8")
    rd = anchor_dir / "README"
    if not rd.exists():
        rd.write_text(_README_BODY, encoding="utf-8")


# ── CRUD ────────────────────────────────────────────────────────────────

def add_project(name: str, folder_path, priority: int = 2,
                state: str = STATE_ACTIVE, scaffold: bool = True,
                notes: str = "") -> dict:
    """Register a new project with a FRESH id. Returns the stored entry.

    ``folder_path`` is non-unique — adding another project for an
    already-registered folder is allowed (1 folder : N projects). When
    ``scaffold`` is true, the per-project ``.anchor/projects/<id>/`` tree is
    created.
    """
    with _paths.WRITE_LOCK:
        reg = load_registry()
        pid = _new_id()
        while pid in reg:  # astronomically unlikely; cheap safety
            pid = _new_id()
        entry = _normalize({
            "id": pid,
            "name": name,
            "folder_path": str(folder_path),
            "priority": priority,
            "state": state,
            "notes": notes,
        })
        reg[pid] = entry
        _save_registry(reg)
        if scaffold:
            scaffold_project_store(entry["folder_path"], pid)
        return entry


def get_project(project_id: str):
    """Return the entry for ``project_id`` or ``None``."""
    return load_registry().get(project_id)


def update_project(project_id: str, **fields) -> dict:
    """Update allowed fields (name, folder_path, priority, state). Returns entry.

    Raises ``KeyError`` if the id is unknown.
    """
    allowed = {"name", "folder_path", "priority", "state", "notes"}
    with _paths.WRITE_LOCK:
        reg = load_registry()
        if project_id not in reg:
            raise KeyError(project_id)
        entry = dict(reg[project_id])
        for k, v in fields.items():
            if k in allowed and v is not None:
                entry[k] = v
        entry = _normalize(entry)
        entry["id"] = project_id
        reg[project_id] = entry
        _save_registry(reg)
        return entry


def set_priority(project_id: str, priority: int) -> dict:
    """Change a project's priority (lifecycle op C7)."""
    return update_project(project_id, priority=int(priority))


def archive_project(project_id: str) -> dict:
    """Archive a project — RETAINED in the registry, not deleted (C7)."""
    return update_project(project_id, state=STATE_ARCHIVED)


def mark_future(project_id: str) -> dict:
    """Mark a project as future-work — RETAINED, not deleted (C7)."""
    return update_project(project_id, state=STATE_FUTURE)


def retire_project(project_id: str) -> dict:
    """Retire/cancel a project — RETAINED in the registry, not deleted (C7)."""
    return update_project(project_id, state=STATE_RETIRED)


def reactivate_project(project_id: str) -> dict:
    """Move an archived/future/retired project back to active."""
    return update_project(project_id, state=STATE_ACTIVE)


def set_notes(project_id: str, notes: str) -> dict:
    """Set the free-text notes for a project (like a task's Notes field)."""
    return update_project(project_id, notes=("" if notes is None else str(notes)))


def remove_project(project_id: str) -> bool:
    """Hard-delete an entry (NOT used by archive/future ops). Returns success.

    Provided for completeness; lifecycle ops use archive/future which retain.
    """
    with _paths.WRITE_LOCK:
        reg = load_registry()
        if project_id in reg:
            del reg[project_id]
            _save_registry(reg)
            return True
        return False


# ── Read / view helpers ─────────────────────────────────────────────────

def _effective_state(entry: dict) -> str:
    """Compute the surfaced state: ``path-missing`` overrides if folder is gone.

    Archived/future are retained states and are reported as-is even if the
    folder is also missing; only otherwise-live entries flip to path-missing.
    """
    fp = entry.get("folder_path", "")
    if entry.get("state") in INACTIVE_STATES:
        return entry["state"]
    if fp and not Path(fp).exists():
        return STATE_PATH_MISSING
    return entry.get("state", STATE_ACTIVE)


def list_projects(include_archived: bool = True, include_future: bool = True,
                  include_retired: bool = True,
                  with_effective_state: bool = True) -> list:
    """Return entries as a list. ``state`` reflects path-missing when applicable.

    Archived/future/retired entries are included by default (retained,
    reviewable); the active dashboard passes all three flags False to show only
    live projects, while the Archive view shows only the inactive ones.
    """
    reg = load_registry()
    out = []
    for e in reg.values():
        e = dict(e)
        if with_effective_state:
            e["state"] = _effective_state(e)
        stored = reg[e["id"]]["state"]
        if not include_archived and stored == STATE_ARCHIVED:
            continue
        if not include_future and stored == STATE_FUTURE:
            continue
        if not include_retired and stored == STATE_RETIRED:
            continue
        out.append(e)
    out.sort(key=lambda x: (x.get("priority", 2), x.get("name", "").lower()))
    return out


def list_inactive_projects() -> list:
    """Return ONLY archived/future/retired projects (for the Archive view)."""
    reg = load_registry()
    out = []
    for e in reg.values():
        if reg[e["id"]]["state"] in INACTIVE_STATES:
            e = dict(e)
            e["state"] = _effective_state(e)
            out.append(e)
    out.sort(key=lambda x: (x.get("state", ""), x.get("name", "").lower()))
    return out


def group_by_folder(include_archived: bool = True,
                    include_future: bool = True,
                    include_retired: bool = True) -> dict:
    """Group projects by ``folder_path`` → list of entries (ordered).

    The projects view renders this: a collapsible folder header → its tiles.
    Two projects sharing a folder appear under the same key with distinct ids.
    """
    groups = {}
    for e in list_projects(include_archived=include_archived,
                           include_future=include_future,
                           include_retired=include_retired):
        groups.setdefault(e["folder_path"], []).append(e)
    return groups


#: Lane status values beyond ``none-yet``.
STATUS_IMPORTED = "imported"   # only discovered (brownfield) artifacts present
STATUS_HAS_RUNS = "has-runs"   # >=1 real Anchor-run effort
STATUS_RUNNING = "running"     # a live job in this lane


def status_line(project_id: str) -> dict:
    """Return the 4-state status line for a project (Research/Plan/Build/Deliv).

    Reflects ADOPTED (discovered) + REAL efforts per lane, computed from the
    per-project effort store (best-effort — never crashes if a lane is unread):
      - ``has-runs`` if the lane has >=1 real (Anchor-run) effort,
      - else ``imported`` if it has >=1 discovered (brownfield) effort,
      - else ``none-yet``.

    Imported is kept distinct from has-runs so the UI never masquerades a
    discovered artifact as an Anchor-run effort.
    """
    proj = get_project(project_id)
    folder = (proj or {}).get("folder_path", "")
    out = {}
    # Local import to avoid a hard import cycle (effort_history imports this
    # module). Resolved lazily, per call.
    try:
        import effort_history as _eh
    except Exception:
        return {lane: STATUS_NONE_YET for lane in STATUS_LANES}
    for lane in STATUS_LANES:
        state = STATUS_NONE_YET
        try:
            efforts = _eh.list_efforts(folder, project_id, lane)
        except Exception:
            efforts = []
        has_real = any(not _eh.is_discovered(e) for e in efforts)
        has_disc = any(_eh.is_discovered(e) for e in efforts)
        if has_real:
            state = STATUS_HAS_RUNS
        elif has_disc:
            state = STATUS_IMPORTED
        out[lane] = state
    return out


# ── Folder-history unification: reconcile (Wave 2) ───────────────────────

def _same_folder_ids(active_id: str):
    """Return ``(active_entry, [sibling_entries])`` for the active id's folder.

    Siblings are OTHER registered projects whose ``folder_path`` matches the
    active project's folder EXACTLY (normalized via ``Path``). A project on a
    DIFFERENT folder (e.g. the unrelated "BF Test" temp-folder id) is never a
    sibling here, so ``reconcile_folder`` can never fold/delete it.
    """
    reg = load_registry()
    active = reg.get(active_id)
    if active is None:
        return None, []
    target = active.get("folder_path", "")
    try:
        target_norm = str(Path(target)) if target else ""
    except (TypeError, ValueError):
        target_norm = str(target)
    siblings = []
    for e in reg.values():
        if e["id"] == active_id:
            continue
        fp = e.get("folder_path", "")
        try:
            fp_norm = str(Path(fp)) if fp else ""
        except (TypeError, ValueError):
            fp_norm = str(fp)
        if fp_norm and fp_norm == target_norm:
            siblings.append(e)
    siblings.sort(key=lambda x: (x.get("priority", 2), x.get("name", "").lower()))
    return active, siblings


def reconcile_folder(active_id: str, apply: bool = False) -> dict:
    """Fold same-folder sibling ids into ``active_id``, then hard-delete them.

    This is the EXPLICIT, REVIEWABLE folder-history unification (MASTER-PLAN
    §D). It is **NOT** run silently on every rescan — a caller invokes it on
    purpose, first as a preview, then (separately) to apply.

    Two-step contract:

    - **Preview** (``apply=False``, the default): returns a PLAN of exactly what
      it WOULD do — which sibling ids (for the SAME folder only) would be folded
      into ``active_id``, how many real sessions/efforts each holds, and which
      ids would then be hard-deleted — WITHOUT mutating anything. So it can
      never silently destroy history.
    - **Apply** (``apply=True``): folds each sibling's REAL effort history into
      ``active_id`` (via ``effort_history.adopt_sibling_sessions``), then
      HARD-DELETES the folded sibling ids from the registry
      (``remove_project``). A sibling that holds nothing is still deleted (it is
      an empty same-folder duplicate). Ids on a DIFFERENT folder are never
      touched.

    Returns a report dict::

        {"ok": bool, "active_id": ..., "folder_path": ...,
         "applied": bool,
         "fold": [{"id","name","priority","efforts": {lane: n, ...},
                   "total_efforts": n}],
         "to_delete": [ids],
         "imported": n,            # apply only
         "deleted": [ids]}         # apply only

    Every registry mutation runs under ``paths.WRITE_LOCK`` (matching the
    module's existing pattern). Best-effort/honesty: an unknown ``active_id``
    yields ``{"ok": False, "reason": "unknown-active"}``.
    """
    import effort_history as _eh  # lazy: effort_history imports this module

    with _paths.WRITE_LOCK:
        active, siblings = _same_folder_ids(active_id)
        if active is None:
            return {"ok": False, "reason": "unknown-active",
                    "active_id": active_id}
        folder = active.get("folder_path", "")

        fold_plan = []
        for sib in siblings:
            sid = sib["id"]
            per_lane = {}
            total = 0
            for lane in _eh.ROLLUP_LANES:
                try:
                    n = len(_eh.list_efforts(folder, sid, lane))
                except Exception:
                    n = 0
                if n:
                    per_lane[lane] = n
                    total += n
            fold_plan.append({
                "id": sid,
                "name": sib.get("name", ""),
                "priority": sib.get("priority", 2),
                "state": sib.get("state", ""),
                "efforts": per_lane,
                "total_efforts": total,
            })
        to_delete = [p["id"] for p in fold_plan]

        report = {
            "ok": True,
            "active_id": active_id,
            "folder_path": folder,
            "applied": False,
            "fold": fold_plan,
            "to_delete": to_delete,
        }
        if not apply:
            return report

        # APPLY: fold each sibling's real sessions into the active id, then
        # hard-delete the sibling from the registry.
        source_ids = to_delete
        adopt = _eh.adopt_sibling_sessions(folder, active_id,
                                           source_ids=source_ids)
        deleted = []
        for sid in source_ids:
            if remove_project(sid):
                deleted.append(sid)
        report["applied"] = True
        report["imported"] = adopt.get("imported", 0)
        report["imported_by_lane"] = adopt.get("by_lane", {})
        report["deleted"] = deleted
        return report


# ── Legacy id assignment (idempotent) ───────────────────────────────────

def assign_legacy_ids(legacy_entries) -> list:
    """Assign stable ids to legacy R&D project records, idempotently.

    ``legacy_entries`` is an iterable of dicts that may lack an ``id``. Any
    entry missing/blank ``id`` gets a fresh uuid; entries that already have an
    id are left UNCHANGED. Running twice produces the same ids (idempotent) —
    because once persisted, the ids are already present on re-read.

    Returns the list of normalized entries and persists them. Existing
    registry entries are preserved (merged by id).
    """
    with _paths.WRITE_LOCK:
        reg = load_registry()
        result = []
        for raw in legacy_entries:
            e = dict(raw)
            pid = e.get("id")
            if not pid:
                pid = _new_id()
                while pid in reg:
                    pid = _new_id()
                e["id"] = pid
            entry = _normalize(e)
            reg[entry["id"]] = entry
            result.append(entry)
        _save_registry(reg)
        return result
