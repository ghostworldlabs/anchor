# Changelog

## 2026-07 — Rearchitecture

### W10 (C5) — Markdown-parser de-fork + dead-server deletion
- **Removed `anchor_server.py`** — the dead legacy Flask app (port 5000, retired
  "Anchor PSU" dual-folder layout, ignored `paths.py`, imported by nothing,
  never shipped; superseded by `anchor_gui.py`). Pre-deletion sweep results:
  `docs/anchor_server-predeletion-sweep.md`.
- Extracted the task/project/inbox/archived markdown parsers (and
  `serialize_task_line`) into the single shared module **`anchor_md.py`**,
  imported by both `anchor_gui.py` and `anchor.py`; the byte-identical twin
  parsers are de-forked to one source of truth. Golden-corpus gate:
  `tests/test_anchor_md_defork_w10.py` proves identical parses of the real
  markdown files pre/post de-fork.
