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
### Wave 3 — First-class session windows (maximize + free resize) — GREEN (2026-06-14)

**Built (UI):** Each session panel header gains a **maximize** (▢) control next to
minimize; toggling adds `.panel.maxd` (position:fixed, fills the viewport, z-index
9000) and restores the prior freely-resized rect. The whole panel body (`.pin`) is now
`resize:both` (drag the corner → width AND height), persisted per session in a new
`_panelRects` map. Maximize/restore AND resize re-fit the xterm via the existing
`_fitPanelTerminal` (FitAddon when present; stub path recomputes cols/rows). v5
minimize / close-to-tile / hard-kill kept exactly; layout stays the stacked column (no
floating windows).

**Orchestrator verification:** (a) DOM/source asserts (5) — maxBtn built + wired to
`maximizePanel`; v5 controls unchanged; `.pin{resize:both}` + `.panel.maxd` present;
`_panelRects` persistence; **negative** — resize no longer terminal-pane-only. (b) Real
Playwright/Chromium test (1) — boot throwaway server + stub PTY, open panel, maximize
→ fills ≥90% viewport + terminal cols/rows grew, restore → re-fit back, free-resize →
re-fit + rect persisted, **no JS console errors**. (c) **Screenshots reviewed by the
orchestrator** — `_devtest/wave3_normal.png` (four distinct controls + corner handle)
and `wave3_maxed.png` (panel fills viewport, maximize toggle highlighted, terminal
reflowed to full width) — match the mockup Step 2.

**Honest nuance (for John):** dragging the panel *taller* grows the summary scroll area
rather than terminal rows; *width* resize and *maximize* both re-fit the terminal
correctly (the headline behavior). Candidate polish if you want vertical drag to grow
the terminal instead.

**Gate:** **753 passed, 1 skipped** (+6). `tests/test_window_controls_v6.py` (6) +
`test_cockpit_paradigm2.py` render-guard GREEN. ⚠️ **Pending John's UI sign-off before
merge.** Commit: scoped (anchor_gui.py + test + log; `_devtest/` screenshots not
committed).

<!-- WAVE 3 done -->
### Wave 4 — Tile lifecycle (new-session=new-tile + keep finished) — GREEN (2026-06-14)

**Built (UI):** (a) Audited all five start paths (`newTermSession`, `continueSession`,
`promoteGrass`, `developGrass`, `pullGrass`) — each already mints a distinct
`MANAGED[sid]` tile on a fresh server id; a JS-source test locks it in. (b) Finished
tiles now stay: `repopulate` splits live → `MANAGED` (colored) vs done/failed →
`FINISHED` (greyed); `renderSessionBar` shows per-lane the most-recent finished as a
prominent greyed tile and collapses older ones under a `<details>` **"previously done
(N)"** expander; clicking a finished tile opens its read-only summary panel; closing
keeps the tile, only hard-kill removes it. The `term_sessions` SAFE projection now also
carries the Wave-2 lineage fields (still NO worktree_path/branch). Preserved the v5
contract via a client `_KILLED` set: deliberate kill = gone forever; natural finish/
reconcile-dead = greyed tile kept (this is what kept `test_run_lifecycle` GREEN).

**Orchestrator verification:** (a) DOM/source asserts (positive+negative — the old
`_isTerminalStatus` skip is gone; SAFE projection has no worktree_path/branch). (b) Real
Playwright/Chromium — start THREE research sessions → 3 distinct tiles; finish the two
oldest → both greyed + kept, newest-finished prominent, oldest under "previously done";
click grouped finished tile → panel opens; no JS console errors. (c) **Screenshot
reviewed** — `_devtest/wave4_tiles.png` shows `● research 3` (live) · `○ research ✓`
(prominent finished) · `previously done (1)` expander + the grouped older tile — matches
mockup Step 1 + Step 5.

**Gate:** **760 passed, 1 skipped** (+7). `tests/test_tile_lifecycle_v6.py` (7) +
cockpit/run-lifecycle guards GREEN. ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 4 done -->
### Wave 5 — Manual advance research→planning + chain breadcrumb — GREEN (2026-06-14)

**Built (UI + endpoints):** `POST /api/rnd/advance_session` (token-gated) — body
`{project_id, source_session, to_lane?}`; builds the seed from the source's cached
summary via the read-only `_build_continue_seed`, then
`start_session(to_lane, parent_session_id=source, seed_context=…)`; returns the new
record (continue_session shape); **source record never mutated**. `GET /api/rnd/chain`
(token via `?token=`) — ordered `chain_members` SAFE projection (session_id/lane/label/
status/parent/chain only; no worktree_path/branch). JS: a green **"Advance to Planning
→"** bar in `openPanel` shown ONLY for a research lane (mockup Step 3); `advanceSession`
mints a new linked planning tile + opens it; a clickable **chain breadcrumb** in the
panel header from `GET /api/rnd/chain` (each node → openPanel). Reused `_build_continue_seed`,
`chain_for`/`chain_members`, `start_session(parent_session_id=)` — no forks.

**Orchestrator verification:** (a) endpoint tests — auth (401/403), missing→400, new
planning session has parent==source + inherited chain_id + non-empty seed, **source
byte-identical after**; chain GET token-gated + SAFE. (b) DOM positive+negative — advance
bar only for research, not plan/build; breadcrumb present. (c) Real Playwright — research
panel shows advance → click → new planning tile + ≥2-node breadcrumb → click research
node → research panel; no console errors. (d) **Screenshot reviewed** —
`_devtest/wave5_advance.png` shows the green "Advance to Planning →" bar on the research
panel, matching mockup Step 3.

**Gate:** **766 passed, 1 skipped** (+6). `tests/test_advance_research_to_plan.py` (6) +
continue/cockpit guards GREEN. ⚠️ **Pending John's UI sign-off before merge.** Commit:
scoped.

<!-- WAVE 5 done -->
<!-- WAVE 6 — Auto advance planning→build (gated on a real plan) -->
<!-- WAVE 7 — Main dashboard reflects project activity -->
<!-- WAVE 8 — CLI mirror + healthcheck v6 + distro + docs (PROJECT DONE) -->
