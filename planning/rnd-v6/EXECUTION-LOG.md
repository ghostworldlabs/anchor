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
### Wave 2 — Session linkage backbone — GREEN (2026-06-14)

**Built:** Durable session lineage. `session_registry._normalize` + `register_session`
gain `parent_session_id` (str, "" for a root) and `chain_id` (defaults to the
record's OWN session_id → existing records become singleton chains, back-compat
holds); both added to the `update_session` allow-list. New `chain_for(session_id)` and
`chain_members(chain_id)` (ordered via `_CHAIN_LANE_ORDER` research→plan→build→…, then
created_at). `terminal_session.start_session(..., parent_session_id=None)` resolves the
parent's chain and sets both fields (unknown parent → fresh chain; parent record never
mutated). `handoff.record_stage_link` / `list_stage_links` add a generic, rescan-
durable `stage_links` edge in `discovery.json` (generalizes plan→build to research→plan;
coexists with the existing `handoffs`).

**Review/risks:** chain_id defaulting is belt-and-suspenders (both register + normalize)
so a record is never chain-less. Unknown parent silently starts a fresh chain (tested).
Scoped to 3 product files + 1 test file.

**Gate:** `ANCHOR_PTY_BACKEND=stub python -m pytest -q` → **747 passed, 1 skipped**
(+18). `tests/test_session_chain.py` (18 tests): defaults/back-compat, inherit+order,
chain_for/members, stage-edge persist across reload + rescan, start_session(parent)
through stub PTY. Commit: scoped.

<!-- WAVE 2 done -->
<!-- WAVE 3 — First-class session windows (maximize + free resize) -->
<!-- WAVE 4 — Tile lifecycle (new-session=new-tile + keep finished) -->
<!-- WAVE 5 — Manual advance research→planning + chain breadcrumb -->
<!-- WAVE 6 — Auto advance planning→build (gated on a real plan) -->
<!-- WAVE 7 — Main dashboard reflects project activity -->
<!-- WAVE 8 — CLI mirror + healthcheck v6 + distro + docs (PROJECT DONE) -->
