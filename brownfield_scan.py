#!/usr/bin/env python3
"""Anchor brownfield discovery scanner (pure, stdlib only).

When an R&D project is registered/opened on an existing folder, this module
performs an INSTANT, local, token-free scan of that folder for genuine
pre-existing trio artifacts (research / planning / build / deliverables) and
classifies them by **trio provenance signals** — NOT broad globs.

The scan is deliberately conservative + bounded:
  - skips ``.git`` / ``node_modules`` / ``_archive`` AND the project's own
    ``.anchor`` store (so we never re-import real efforts as discovered),
  - caps recursion depth (~6) and total file count (~5000),
  - ignores large binaries,
  - never hangs/raises on a missing / huge / UNC / mistyped path — it returns an
    empty :class:`ScanResult` instead.

Classification (provenance signals, in priority order):
  - ``build``        — ``foreman-checkpoint.json`` / ``foreman.config.json``.
  - ``planning``     — trio planning docs under ``planning/**`` (and at the root):
                       ``*MASTER-PLAN*`` / ``*IMPLEMENTATION-PLAN*`` /
                       ``*EXECUTION-LOG*`` / ``*DECISION-LOG*``.
  - ``research``     — ``report.md`` / ``report.pdf`` under a research store
                       (a dir named ``research`` or a researchPrime store).
  - ``deliverables`` — declared output dir (``deliverables/**``).
  - ``docs``         — everything else that is *plausibly* a doc but carries NO
                       trio provenance: a generic ``*.pdf`` or a root
                       ``*PLAN*.md`` that is not one of the named trio docs.
                       These are LISTED (so ``Anchor.md`` can mention them) but
                       are NOT adopted as effort cards.

The result is a pure data object; adoption / rendering / marker-writing live in
other modules. Stdlib only.
"""

import os
import time
from pathlib import Path

# ── Bounds ──────────────────────────────────────────────────────────────────
MAX_DEPTH = 6
MAX_FILES = 5000
#: Files larger than this are treated as opaque binaries (not parsed; a *.pdf
#: still classifies as docs/research by NAME, but we never read its bytes).
MAX_BINARY_BYTES = 64 * 1024 * 1024

#: Directory names never descended into.
SKIP_DIRS = frozenset({".git", "node_modules", "_archive", ".anchor",
                       "__pycache__", ".venv", "venv", ".mypy_cache",
                       ".pytest_cache"})

# Lane keys used in ``by_lane``.
LANE_BUILD = "build"
LANE_PLANNING = "planning"
LANE_RESEARCH = "research"
LANE_DELIVERABLES = "deliverables"
LANES = (LANE_RESEARCH, LANE_PLANNING, LANE_BUILD, LANE_DELIVERABLES)

# Build-provenance filenames (exact, case-insensitive).
_BUILD_FILES = frozenset({"foreman-checkpoint.json", "foreman.config.json"})

# Planning-provenance name fragments (case-insensitive substring of the stem).
_PLANNING_FRAGMENTS = ("master-plan", "implementation-plan", "execution-log",
                       "decision-log")

# Research store dir names.
_RESEARCH_DIRS = frozenset({"research"})
# Research artifact basenames (case-insensitive).
_RESEARCH_FILES = frozenset({"report.md", "report.pdf"})


class ScanResult:
    """Immutable-ish result of a brownfield scan.

    Attributes:
      ``by_lane`` — ``{lane: [artifact, ...]}`` for the four trio lanes; each
        artifact is a dict ``{rel, kind, title, mtime, lane}`` with a folder-
        RELATIVE POSIX path. These are ADOPTABLE as discovered efforts.
      ``docs`` — ``[artifact, ...]`` of low-confidence docs (generic pdf / root
        ``*PLAN*.md``) that are LISTED but NOT adopted as effort cards.
      ``counts`` — ``{lane: int, "docs": int, "total": int}`` numeric tallies.
      ``generated_at`` — epoch seconds the scan completed.
    """

    __slots__ = ("by_lane", "docs", "counts", "generated_at", "root",
                 "truncated")

    def __init__(self, by_lane=None, docs=None, counts=None,
                 generated_at=None, root="", truncated=False):
        self.by_lane = by_lane if by_lane is not None else {
            lane: [] for lane in LANES}
        self.docs = docs if docs is not None else []
        self.counts = counts if counts is not None else self._compute_counts()
        self.generated_at = (generated_at if generated_at is not None
                             else time.time())
        self.root = root
        self.truncated = truncated

    def _compute_counts(self):
        counts = {lane: len(self.by_lane.get(lane, [])) for lane in LANES}
        counts["docs"] = len(self.docs)
        counts["total"] = sum(counts[lane] for lane in LANES) + counts["docs"]
        return counts

    def recompute_counts(self):
        self.counts = self._compute_counts()
        return self.counts

    def all_artifacts(self):
        """Iterate every adoptable artifact across all lanes (not docs)."""
        for lane in LANES:
            for art in self.by_lane.get(lane, []):
                yield art

    def to_dict(self) -> dict:
        """Plain-dict form for the machine sidecar (JSON-serializable)."""
        return {
            "by_lane": {lane: list(self.by_lane.get(lane, []))
                        for lane in LANES},
            "docs": list(self.docs),
            "counts": dict(self.counts),
            "generated_at": self.generated_at,
            "root": self.root,
            "truncated": self.truncated,
        }


# ── Classification helpers (pure, name-based) ───────────────────────────────

def _title_from(path: Path) -> str:
    """A human title from a file: first markdown heading if present, else stem.

    Reading is best-effort and bounded (only the first ~4KB of small text
    files). NEVER raises and NEVER reads big binaries.
    """
    name = path.name
    if path.suffix.lower() == ".md":
        try:
            if path.stat().st_size <= 256 * 1024:
                with path.open("r", encoding="utf-8", errors="ignore") as fh:
                    head = fh.read(4096)
                for line in head.splitlines():
                    s = line.strip()
                    if s.startswith("#"):
                        return s.lstrip("#").strip() or path.stem
        except OSError:
            pass
    return path.stem


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _is_planning_doc(stem_lower: str) -> bool:
    return any(frag in stem_lower for frag in _PLANNING_FRAGMENTS)


def _classify(path: Path, rel_posix: str, rel_parts):
    """Classify ONE file by trio provenance. Returns ``(lane_or_docs, kind)``
    or ``None`` to skip the file entirely.

    ``rel_parts`` is the tuple of folder-relative path components (lowercased
    for dir matching is done by the caller's signal, but we lowercase here).
    """
    name = path.name
    name_lower = name.lower()
    suffix = path.suffix.lower()
    stem_lower = path.stem.lower()
    parts_lower = [p.lower() for p in rel_parts]
    parent_dirs = set(parts_lower[:-1])  # dirs above the file

    # 1. Build provenance — foreman checkpoint/config.
    if name_lower in _BUILD_FILES:
        return (LANE_BUILD, "foreman-checkpoint"
                if "checkpoint" in name_lower else "foreman-config")

    # 2. Planning provenance — trio planning docs (named), under planning/ or
    #    at the root. EXECUTION-LOG.md etc.
    if suffix == ".md" and _is_planning_doc(stem_lower):
        return (LANE_PLANNING, "plan-doc")

    # 3. Research provenance — report.md / report.pdf under a research store.
    if name_lower in _RESEARCH_FILES:
        if parent_dirs & _RESEARCH_DIRS or "researchprime" in parts_lower:
            return (LANE_RESEARCH, "research-report")
        # report.md not under a research dir → still a doc, not adopted.
        return ("docs", "report-doc")

    # 4. Deliverables — declared output dir.
    if "deliverables" in parent_dirs:
        # Only meaningful payloads (skip empty placeholder dirs handled by walk).
        return (LANE_DELIVERABLES, "deliverable")

    # 5. Low-confidence docs (LISTED, NOT adopted): generic pdf or root *PLAN*.md.
    if suffix == ".pdf":
        return ("docs", "pdf")
    if suffix == ".md" and "plan" in stem_lower:
        # A root-level *PLAN*.md that is NOT a named trio doc (e.g. FUNDING-PLAN).
        return ("docs", "plan-md")

    return None


# ── The scanner ─────────────────────────────────────────────────────────────

def scan(folder_path, store_subpath=".anchor") -> ScanResult:
    """Scan ``folder_path`` for trio artifacts. Always returns a ScanResult.

    Robust to a missing / huge / UNC / mistyped path: any failure to even begin
    walking yields an empty ScanResult (no hang, no raise). ``store_subpath`` is
    the project's own Anchor store dir name to skip (default ``.anchor``).
    """
    empty = lambda trunc=False: ScanResult(
        by_lane={lane: [] for lane in LANES}, docs=[],
        counts={**{lane: 0 for lane in LANES}, "docs": 0, "total": 0},
        generated_at=time.time(),
        root=str(folder_path) if folder_path else "", truncated=trunc)

    if not folder_path:
        return empty()
    try:
        root = Path(folder_path)
    except (TypeError, ValueError):
        return empty()
    try:
        if not root.exists() or not root.is_dir():
            return empty()
    except OSError:
        return empty()

    try:
        root_resolved = root.resolve()
    except OSError:
        root_resolved = root

    by_lane = {lane: [] for lane in LANES}
    docs = []
    file_count = 0
    truncated = False

    # os.walk is bounded by SKIP_DIRS pruning + a depth cap + a file cap.
    try:
        walker = os.walk(str(root), topdown=True, followlinks=False)
    except OSError:
        return empty()

    for dirpath, dirnames, filenames in walker:
        # Depth cap relative to root.
        try:
            rel_dir = Path(dirpath).resolve().relative_to(root_resolved)
            depth = len(rel_dir.parts)
        except (OSError, ValueError):
            rel_dir = Path(dirpath)
            depth = len(rel_dir.parts)
        if depth >= MAX_DEPTH:
            dirnames[:] = []  # do not descend further
        # Prune skip-dirs in place (so os.walk never enters them).
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        for fname in filenames:
            if file_count >= MAX_FILES:
                truncated = True
                break
            fpath = Path(dirpath) / fname
            try:
                rel = fpath.resolve().relative_to(root_resolved)
            except (OSError, ValueError):
                try:
                    rel = fpath.relative_to(root)
                except ValueError:
                    continue
            rel_parts = rel.parts
            # Defensive: skip anything under a skip-dir (e.g. symlinked-in).
            if any(p in SKIP_DIRS for p in rel_parts):
                continue
            file_count += 1
            try:
                klass = _classify(fpath, rel.as_posix(), rel_parts)
            except OSError:
                klass = None
            if klass is None:
                continue
            lane_or_docs, kind = klass
            artifact = {
                "rel": rel.as_posix(),
                "kind": kind,
                "title": _title_from(fpath),
                "mtime": _mtime(fpath),
            }
            if lane_or_docs == "docs":
                docs.append(artifact)
            else:
                artifact["lane"] = lane_or_docs
                by_lane[lane_or_docs].append(artifact)
        if truncated:
            break

    # Deterministic ordering (rel path) so rescans are stable.
    for lane in LANES:
        by_lane[lane].sort(key=lambda a: a["rel"])
    docs.sort(key=lambda a: a["rel"])

    counts = {lane: len(by_lane[lane]) for lane in LANES}
    counts["docs"] = len(docs)
    counts["total"] = sum(counts[lane] for lane in LANES) + counts["docs"]
    return ScanResult(by_lane=by_lane, docs=docs, counts=counts,
                      generated_at=time.time(), root=str(root),
                      truncated=truncated)
