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
}

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
    every effort in every rollup lane is upserted into ``target_id``'s matching
    lane store via :func:`_import_record_into`. The target therefore SEES trio
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
    by_lane = {lane: 0 for lane in ROLLUP_LANES}
    used_sources = []
    with _paths.WRITE_LOCK:
        for sid in source_ids:
            touched = False
            for store_lane in ROLLUP_LANES:
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
