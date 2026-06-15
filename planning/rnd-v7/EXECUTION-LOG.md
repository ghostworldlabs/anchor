# Anchor R&D Surface v7 — "Integrated Board" — Execution Log

> Per-wave EXECUTE / REVIEW / FIX / GATE history for the Foreman build of v7. Frozen
> plan: `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` (this folder). Branch:
> `foreman/rnd-surface-v7` (off master `5ae3c2e`, which has v6 merged).

## Baseline

- **2026-06-15** — Branch `foreman/rnd-surface-v7` created off master (v6 merged).
  v6 baseline = **816 passed, 1 skipped**. This is the GREEN floor; every wave holds or
  grows it.

## Wave records

### Wave 1 — Short, clean summaries (normalizer + caps) — GREEN (2026-06-15)

**Built (backend):** `summarizer.short_summary_text(in, max_chars=140)` + `tile_blurb(in,
max_chars=64)` (+ private `_strip_markdown_controls`/`_strip_decorative`/`_normalize_plain`/
`_coerce_summary_input`). Strips markdown (`** __ ~~ `` ` `` `, headings, list markers,
`[t](u)`→`t`, blockquotes; standalone inline `#…` but preserves `C#`) and a decorative
glyph set (`✓ → ☢ • ● ▼ ⋮ …` + generic Unicode symbol/control/format categories → emoji +
box-drawing), normalizes dash family → `-`, collapses whitespace, word-boundary cap with
`…`. A clean in-cap sentence is returned UNCHANGED (apostrophes/quotes/parens/digits/`?`
preserved). Applied at the two SHORT objective sites (home row `_project_summary_text` +
project-window header); the `/summary` full markdown is untouched. `tile_blurb` added +
unit-tested for Wave 3.

**Orchestrator verification:** `tests/test_summary_shorten_v7.py` (16) — each glyph/markdown
class stripped while words survive; clean sentence unchanged; word-boundary truncation;
render sites use it (glyph-laden cache → clean); `/summary` markdown still intact. v6
guards (`test_summary_content_v6`, `test_dashboard_reflection_v6`) stay GREEN.

**Gate:** **831 passed, 1 skipped** (+15). Backend-only (no UI structure change). Commit:
scoped.

<!-- WAVE 1 done -->
<!-- WAVE 2 — Summarize each session on finish -->
<!-- WAVE 3 — Live sessions integrated into the lane columns -->
<!-- WAVE 4 — "Open terminal" general session button -->
<!-- WAVE 5 — CLI mirror + healthcheck v7 + distro + docs (PROJECT DONE) -->
