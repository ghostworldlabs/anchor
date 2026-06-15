# Anchor R&D Surface v6 — "Linked Pipeline" — Execution Log

> Per-wave EXECUTE / REVIEW / FIX / GATE history for the Foreman build of v6.
> Frozen plan: `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` (this folder). Branch:
> `foreman/rnd-surface-v6` (off master `32c5a83`; base commit `a43273d` = the
> cherry-picked summarizer stream-json parse fix `1bd8b85`).

## Baseline

- **2026-06-14** — Branch `foreman/rnd-surface-v6` created off master. Cherry-picked
  `1bd8b85` (summarizer discarded all prod stream-json text → blank summaries) as the
  branch base. Full suite: **724 passed, 1 skipped** (the skip is the pre-existing
  host symlink/git skip). This is the GREEN floor; every wave must hold or grow it.

## Wave records

_(appended as each wave reaches GREEN — one record per wave: what was built, the
adversarial-review findings, fixes, the gate result/count, and the commit.)_

### Wave 1 — Summaries that actually work — GREEN (2026-06-14)

**Built:** Verified the cherry-picked stream-json parse fix (`a43273d`) fully
satisfies the wave — the v5 content code (`_session_skill`/`_session_prompts`/
`_session_actions`, `project_extraction_seed` objective seed, generate-twice +
grounding filter, `SUMMARY_SCHEMA_VERSION=2` cache heal on `load_cached` /
`load_cached_project`, background regen on `rescan`) was correct all along; only the
parse layer was discarding prod output. So Wave 1 = land the fix (done as branch base)
+ prove it. Added `tests/test_summary_content_v6.py` (5 tests, 24 asserts) driving the
summarizer through the **stream-json stub**: session summary carries skill/prompts/
actions; project summary is a grounded objective; the grounding filter drops a
hallucinated claim; a schema-version-stale empty cache **heals via the real rescan
path** (background daemon, polled); bare-line back-compat still parses.

**Review/risks:** No product-code change needed (verified, not assumed). Stale-cache
test exercises a real background thread (polled, non-flaky over 3 runs); hermetic
(temp `ANCHOR_DATA_DIR`, runner via stub, no `:8777`).

**Gate:** `ANCHOR_PTY_BACKEND=stub python -m pytest -q` → **729 passed, 1 skipped**
(+5). Commit: scoped (test file + this log).

<!-- WAVE 1 done -->
<!-- WAVE 2 — Session linkage backbone -->
<!-- WAVE 3 — First-class session windows (maximize + free resize) -->
<!-- WAVE 4 — Tile lifecycle (new-session=new-tile + keep finished) -->
<!-- WAVE 5 — Manual advance research→planning + chain breadcrumb -->
<!-- WAVE 6 — Auto advance planning→build (gated on a real plan) -->
<!-- WAVE 7 — Main dashboard reflects project activity -->
<!-- WAVE 8 — CLI mirror + healthcheck v6 + distro + docs (PROJECT DONE) -->
