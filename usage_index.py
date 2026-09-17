#!/usr/bin/env python3
"""Anchor usage index — one small doc per project: the reader's file for spend by source.

codex-discipline Wave 2 S1 (2026-09-17). The usage ledger (``usage_ledger.py``)
is the durable per-engine-session detail: one doc per engine session, write-once
per entry. Nothing in it says which project an engine session belongs to, and
finding a project's rows would mean opening every doc (4,000+) on every cockpit
poll. This index is the projection the cockpit reads instead: one JSON doc per
project id holding a compact write-once row per ledger entry that carried a
project (steward turns, delegated jobs). A row carries the ids that flow back to
the project (project_id, folder_path, effort_dir, engine session uuid, native
id) and the honest figures (tokens, cost_usd or null, usage_state).

Written only through ``usage_capture.ingest_usage`` (the one seam). Same
discipline as the ledger: ``paths.WRITE_LOCK`` + ``journal.pairing()`` + atomic
tmp->rename; first write wins per key. Reads are cached by the file's
(mtime, size), so a poll costs one ``stat`` when nothing changed.

Stdlib only. No third-party imports.
"""

import json
import re
import threading
from pathlib import Path

import paths as _paths
import journal as _journal

INDEX_DIRNAME = "usage_index"
ANCHOR_DIRNAME = ".anchor"

_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_CACHE = {}
_CACHE_LOCK = threading.Lock()


def index_dir() -> Path:
    """Absolute path to the index dir (``.anchor/usage_index/``). Not created."""
    return _paths.data_dir() / ANCHOR_DIRNAME / INDEX_DIRNAME


def _safe_id(project_id) -> str:
    s = _UNSAFE_NAME_RE.sub("_", str(project_id or "").strip())
    return s or "unknown"


def index_path(project_id) -> Path:
    """Absolute path to one project's index doc. Not created."""
    return index_dir() / f"{_safe_id(project_id)}.json"


def _read(project_id) -> dict:
    p = index_path(project_id)
    empty = {"project_id": str(project_id or ""), "rows": {}}
    if not p.exists():
        return empty
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return empty
    if not isinstance(raw, dict) or not isinstance(raw.get("rows"), dict):
        return empty
    return {"project_id": raw.get("project_id") or str(project_id or ""),
            "rows": raw["rows"]}


def append_rows(project_id, rows) -> int:
    """Idempotently append rows for a project. Returns the count actually added.

    Each row MUST carry a ``"key"`` (the ledger entry key). A key already present
    is a no-op (first write wins), so a replayed finalize or a re-ingested line
    never counts twice. Atomic + crash-safe like the ledger.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("key")]
    if not project_id or not rows:
        return 0
    with _paths.WRITE_LOCK, _journal.pairing():
        doc = _read(project_id)
        store = doc["rows"]
        added = 0
        for row in rows:
            if row["key"] in store:
                continue
            store[row["key"]] = row
            added += 1
        if added:
            index_dir().mkdir(parents=True, exist_ok=True)
            _paths.atomic_write_text(
                index_path(project_id),
                json.dumps(doc, indent=1, ensure_ascii=False))
        return added


def load_rows(project_id) -> list:
    """The project's rows in first-write order. Cached by (mtime, size); never raises."""
    if not project_id:
        return []
    p = index_path(project_id)
    try:
        st = p.stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    key = str(p)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and hit[0] == sig:
            return list(hit[1])
    rows = list(_read(project_id)["rows"].values()) if sig is not None else []
    with _CACHE_LOCK:
        _CACHE[key] = (sig, rows)
    return list(rows)
