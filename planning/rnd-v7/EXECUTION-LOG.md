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
### Wave 2 — Summarize each session on finish — GREEN (2026-06-15)

**Built (backend):** `_trigger_session_summary_on_finish` (non-blocking, idempotent,
best-effort wrapper over the Wave-6 background daemon) wired into the three finish
transitions: `term_kill` (killed session), `finish_to_build` (finished planning session,
only when a plan set exists), and the `term_sessions` reconcile-dead path (iterates
`reconcile_and_advance` → `report.reconcile.marked`, schedules each). Each hook is its own
try/except, runs before the response, never blocks it; idempotent (skips if cached); a
failed runner leaves no cache (summarizer FIX 2). Added `summarizer.session_blurb(...)` —
pure cached read → `tile_blurb`(first grounded claim → what_was_asked → title), honest
`""` when uncached, never a model call. Gated by `_PROACTIVE_SUMMARY_ENABLED` (off in
tests unless opted-in; on in the live server).

**Orchestrator verification:** `tests/test_summary_on_finish_v7.py` (+ `tests/stub_fail_runner.py`)
— kill schedules exactly one background summary + non-blocking + idempotent; injected raise
still 200s; failed runner → no cache; `session_blurb` clean/capped/honest-absent + no model
call; finish_to_build + reconcile-dead end-to-end + wiring guards. v6 guards
(`test_v6_polish`, `test_auto_advance_plan_to_build`, `test_summary_content_v6`) GREEN.

**Honest note:** a killed live-PTY session with no effort members is grounding-empty (cached
but `session_blurb`="" until real members exist) — intended; Wave 3 shows running intent
until a summary lands.

**Gate:** **840 passed, 1 skipped** (+9). Backend-only. Commit: scoped.

<!-- WAVE 2 done -->
<!-- WAVE 3 — Live sessions integrated into the lane columns -->
<!-- WAVE 4 — "Open terminal" general session button -->
<!-- WAVE 5 — CLI mirror + healthcheck v7 + distro + docs (PROJECT DONE) -->
