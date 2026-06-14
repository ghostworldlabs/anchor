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
