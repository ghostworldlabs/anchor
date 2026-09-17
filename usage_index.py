#!/usr/bin/env python3
"""Anchor usage index — one small file per project: the reader's file for delegated jobs.

codex-discipline Wave 2 S1 (2026-09-17). The usage ledger (``usage_ledger.py``)
holds the per-engine-session detail, write-once per entry, but nothing in it
says which project an engine session belongs to; a cockpit poll cannot open
4,000+ docs, and of 16,000+ job records only 120 carry a project id. This index
is the projection the cockpit sums: one JSON-lines file per project id, one
compact write-once row per attributed job, each naming its job, its ledger doc,
the folder it ran in (stamped in comparable form) and the honest figures
(tokens, cost_usd or null, usage_state).

Written only through ``usage_capture.ingest_usage``. Same discipline as the
ledger: ``paths.WRITE_LOCK`` + ``journal.pairing()``; first write wins per key.
A row is one appended line (fsynced), so a project with 8,000 jobs is never
rewritten whole; a torn last line from a crash is skipped on read and repaired
by the seam's next replay. Stdlib only.
"""

import json
import os
import re
from pathlib import Path

import paths as _paths
import journal as _journal

INDEX_DIRNAME = "usage_index"
ANCHOR_DIRNAME = ".anchor"

_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def index_dir() -> Path:
    """Absolute path to the index dir (``.anchor/usage_index/``). Not created."""
    return _paths.data_dir() / ANCHOR_DIRNAME / INDEX_DIRNAME


def _safe_id(project_id) -> str:
    s = _UNSAFE_NAME_RE.sub("_", str(project_id or "").strip())
    return s or "unknown"


def index_path(project_id) -> Path:
    """Absolute path to one project's index file. Not created."""
    return index_dir() / f"{_safe_id(project_id)}.jsonl"


def _rows(project_id) -> dict:
    """``{key: row}`` in first-write order; malformed lines are skipped."""
    p = index_path(project_id)
    out = {}
    if not p.exists():
        return out
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("key") and row["key"] not in out:
            out[row["key"]] = row
    return out


def append_rows(project_id, rows) -> int:
    """Idempotently append rows for a project. Returns the count actually added.

    Each row MUST carry a ``"key"`` (the ledger entry key). A key already present
    is a no-op (first write wins), so a replayed finalize never counts twice.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("key")]
    if not project_id or not rows:
        return 0
    with _paths.WRITE_LOCK, _journal.pairing():
        have = _rows(project_id)
        fresh = []
        for row in rows:
            if row["key"] in have or any(row["key"] == f["key"] for f in fresh):
                continue
            fresh.append(row)
        if fresh:
            index_dir().mkdir(parents=True, exist_ok=True)
            path = index_path(project_id)
            torn = False
            try:
                if path.exists() and path.stat().st_size:
                    with open(path, "rb") as fh:
                        fh.seek(-1, os.SEEK_END)
                        torn = fh.read(1) != b"\n"
            except OSError:
                torn = False
            with open(path, "a", encoding="utf-8", newline="\n") as fh:
                if torn:
                    fh.write("\n")   # end a line a crash left open; it stays skipped
                for row in fresh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return len(fresh)


def load_rows(project_id) -> list:
    """The project's rows in first-write order. Never raises."""
    if not project_id:
        return []
    return list(_rows(project_id).values())
