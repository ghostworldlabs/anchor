# Anchor R&D Surface v5 — "Durable Work" — Execution Log

> Foreman appends per-wave EXECUTE / REVIEW / FIX / GATE history here. Seeded by
> Crucible at handoff 2026-06-14. Frozen design: `MASTER-PLAN.md` +
> `IMPLEMENTATION-PLAN.md` (this folder).

## Handoff (Crucible → Foreman) — 2026-06-14

- Builds on the merged v4.1 "Project Cockpit" + the terminal fixes (full-width fit,
  Ctrl+V paste, no-freeze pump).
- 6 waves, terminal wave = 6. test-command: `python -m pytest -v`.
- Grass design = the approved B+C hybrid (`_mockups/grass_catcher_refined.html`).
- **Verification is mandatory per UI wave:** rendered-DOM (positive+negative) +
  a real Playwright/Chromium interaction test + an orchestrator screenshot vs the
  mockup + user sign-off before merge. A string-grep gate is an automatic HALT.
  (Playwright is installed as a dev-only test dep; `pytest.importorskip`.)

<!-- Foreman: append wave records below this line -->

## Wave 1 — Run lifecycle: close-to-tile vs. deliberate hard-kill — GREEN (2026-06-14)

- **EXECUTE** (fresh sub-agent): panel header rebuilt to THREE distinct controls
  (`–` minimize · `×` CLOSE close-to-tile · `🗑` KILL, confirm-gated → term_kill).
  Re-added `#sessionBar` as the reopen vector for LIVE managed sessions (not
  server-rendered board tiles); `closePanel` (non-killing) vs `killPanel`
  (confirm + term_kill + `_removeSessionTile`); `renderSessionBar` rebuilds
  reopenable chips from MANAGED. New `tests/test_run_lifecycle.py` (DOM +
  Playwright + backend registry/PTY + token gate). Flipped the stale v4.1
  `sessionBar`-absent negative in `test_project_window.py` (FWM negatives intact).
- **GATE (orchestrator-run, stub PTY):** 651 passed, 1 skipped (baseline 643+1, +8).
- **REVIEW (adversarial, prompted to refute): 1 BLOCKER** — a hard-killed session
  is marked `done` (terminal) but its record is kept; `repopulate()` (term_sessions
  returns every status) re-synced it into the live bar ~400ms after kill, so the
  killed chip REAPPEARED. The Playwright test raced past it (closed the browser
  before `setTimeout(repopulate,400)` fired) → GREEN on broken behavior (the v4
  timing-blind-gate trap). All other 6 scrutiny points CONFIRMED-OK (close never
  reaps; kill reaps no orphan; reopen re-attaches live PTY; stdlib-only; no
  Playwright in product; never :8777).
- **FIX (orchestrator):** `repopulate()` excludes terminal-status sessions
  (`_isTerminalStatus` mirrors `session_registry.TERMINAL_STATUSES` = {done,
  failed}) from the live bar; a session that just went terminal is evicted from
  MANAGED. Strengthened the Playwright kill assertion to wait 900ms (past the
  repopulate) and re-assert the chip + panel stay gone.
- **RE-GATE (orchestrator-run, stub PTY):** 651 passed, 1 skipped. UI verified:
  rendered-DOM (positive `#sessionBar`/`#panelStack` + negative old `× == kill`),
  real Playwright open→close→reopen→kill, and an orchestrator screenshot of the
  panel header showing the grey `×` and a distinct red `🗑` (visually confirmed).
- **COMMIT (scoped):** `dd08c6b` — anchor_gui.py + test_run_lifecycle.py +
  test_project_window.py only (no runtime churn).

## Wave 2 — Past-session view: real summary + "Continue in a live session" — GREEN (2026-06-14)

- **EXECUTE** (fresh sub-agent): (A) `summarizer.summarize_session` extended with
  three DETERMINISTIC source-grounded fields — `skill` / `prompts` / `actions`
  (read straight off session+member records, NEVER through the model → zero
  fabrication; honest empty/placeholder when absent). Model `claims` still go
  through generate-twice + grounding filter; failed-runner branch still skips the
  cache (no poison). (B) Historical panel JS (`_mountReadOnlyBody` rewritten →
  `_renderPastSession`/`_fillPastSessionDetail`) replaces the "session complete"
  dead-end with skill+prompts+files+doc-role links. (C) New token-gated
  `POST /api/rnd/continue_session` (+ `_build_continue_seed`) → `start_session` in
  the SAME lane seeded with the prior summary; original never mutated (R2).
- **GATE (orchestrator-run, stub PTY):** 660 passed, 1 skipped (baseline 651+1, +9).
- **REVIEW (adversarial, prompted to refute): SHIP — 0 BLOCKER, 2 MINOR.** All 7
  scrutiny points CONFIRMED-OK: R3 grounding intact (skill/prompts/actions are real
  reads; `frobnicate`/`zzyzx` ungrounded claims still dropped); cache generate-once
  + force + no-poison-on-failure; R2 original byte-identical after continue + fresh
  worktree; endpoint token-gated; UI gate is a REAL Playwright click→panel→summary→
  continue test (NOT grep-only); stdlib-only; never :8777. MINOR: produced-file
  labels not hyperlinked (doc links live in the summary block above — honest, not
  dangling); handler covered via Playwright rather than a dedicated HTTP unit test.
  Neither blocks. No FIX required.
- **UI VERIFY (orchestrator):** screenshot of a discovered planning session's panel
  — confirmed it shows the summary header + PLAN DOCUMENTS role links + "Skill
  invoked: not recorded" + "Prompts asked: none recorded" + "Files produced:
  Master Plan / Impl Plan" + the blue "▶ Continue in a live session" button
  (honest placeholders for the imported case; `ro-sec`=3).
- **COMMIT (scoped):** `6b781aa` — summarizer.py + anchor_gui.py +
  test_session_continue.py only (no runtime churn).

## Wave 3 — Better project summaries (objective/purpose) + folded dashboard reflection — GREEN (2026-06-14)

> Scope note: this wave ALSO delivers a user request raised mid-build — "project-
> window changes should reflect on the main dashboard timely" — folded in here
> because it touches the same dashboard-row/summary render path.

- **EXECUTE** (fresh sub-agent): PART 1 — `summarizer.project_extraction_seed` adds
  per-lane activity; `_project_seed_prompt` rewritten to ask for a grounded 1-2
  sentence OBJECTIVE; `render_project_markdown` → prose `## Objective`; project
  header renders the cached `Objective:` line; render path is cache-only (proven by
  stub-counter). PART 2 (folded) — read-only `GET /api/rnd/projects_html` (reuses
  `render_projects_view_html`), `#rndProjectsRows` container, `rndRowsRefresh()`
  poll(~15s)+visibilitychange+showView('rnd') in-place swap (diff-before-swap,
  hidden-view guard, failure-tolerant, no page reload).
- **GATE (orchestrator-run, stub PTY):** 670 passed, 1 skipped (baseline 660+1, +10).
- **REVIEW (adversarial, prompted to refute): SHIP — 0 BLOCKER, 1 MINOR (F1).** All
  7 points CONFIRMED-OK: cache-only render with a NON-VACUOUS counter proof (counter
  increments on a real run, stays put across renders); R3 grounding intact (per-lane
  activity is deterministic, ungrounded claims still dropped, honest "No summary yet",
  failed run no-poison); generate-once/force; the dashboard refresh swaps in place
  with real guards; UI gate is a REAL Playwright in-place-refresh test (NOT grep);
  stdlib-only + distro scan clean; never :8777. **F1 (MINOR):** the 15s poll
  re-rendered the default fragment, reverting a user's 30d rollup toggle + closing an
  open kebab.
- **FIX (orchestrator):** `rndRowsRefresh` now skips the swap while a kebab is open
  and preserves the active rollup window across the swap (capture before, re-apply
  after). New regression test `test_refresh_preserves_rollup_toggle_and_open_kebab`
  (scoped to `#rndProjectsRows` — the toggle markup also appears in a hidden view).
- **RE-GATE (orchestrator-run, stub PTY):** 671 passed, 1 skipped. UI verified:
  rendered-DOM (`#rndProjectsRows` + JS present), real Playwright in-place refresh +
  toggle/kebab preservation, and an orchestrator screenshot of the project header
  showing the grounded objective line ("…energy-aware HVAC scheduler that pre-cools
  before peak prices").
- **COMMIT (scoped):** `3bcac71` — summarizer.py + anchor_gui.py +
  test_project_summary_v5.py only (no runtime churn).
