# Anchor R&D Surface v10 — "Live Handoff & Boneyard" — Execution Log

> Foreman appends per-wave EXECUTE / ADVERSARIAL-REVIEW / FIX / JUDGE history here.
> Frozen design: `MASTER-PLAN.md`. Build plan: `IMPLEMENTATION-PLAN.md`.
> Branch `foreman/rnd-surface-v10` off master `b33c74a` (v9 merged `9baabf0` + the
> Build→Planning tie commit). Baseline at branch cut: GREEN 1068, 1 skipped.

<!-- Foreman writes below this line. -->

## Wave 1 — Paste-NOT-submit handoff substrate (backend) — ✅ GREEN (2 iters)

- **EXECUTE.** Added `paste_prompt=` to `terminal_session.start_session` (phase-1 seed still submitted; the prompt recorded as `pending_paste`, not written); `_flush_pending_paste` writes it to the PTY unsent, once, after the greet; wired into `attach`/`read_since`. `session_registry._normalize` + `update_session` allow-list gain `pending_paste:str=""` / `paste_flushed:bool=False`. New `tests/test_pending_paste_v10.py`.
- **GATE 1.** Full suite GREEN 1080/1 — but review flagged the gate did not actually verify "after the greet".
- **REVIEW (2 independent, refute).** Both corroborated: **BLOCKER** premature flush — the greet marker is a literal substring of the echoed seed, so the paste fired before the model greeted (concrete repro, zero model greet); **MAJOR** double-paste TOCTOU under `ThreadingHTTPServer`; **MINOR** no newline strip (a `NEXT-PROMPT.md` ending in `\n` would auto-submit).
- **FIX iter 1.** Greet detection now = marker occurrences **beyond** the seed's own (`base = seed_text.count(marker)`; flush iff buffer count > base) — non-vacuous (the "no premature flush" test fails against the old logic). Double-paste closed by a compare-and-set under the reentrant `paths.WRITE_LOCK` (claim `paste_flushed=True` before the PTY write; loser no-ops). `pending.rstrip("\r\n")` before write. Tests grew 8→11 (added no-premature-flush, newline-strip, 2-thread concurrency).
- **GATE 2 (orchestrator-run, of record).** `python -m pytest -q` → **GREEN 1083 passed, 1 skipped**. Closure verified in code (`terminal_session.py:547-575`).
- **VERDICT: GO.** Commit scoped (terminal_session.py, session_registry.py, tests/test_pending_paste_v10.py).

## Wave 2 — Both-artifact advance + paste-in-panel (UI) — ✅ GREEN (awaiting John's UI sign-off)

- **EXECUTE.** `handoff.build_next_stage_prompt` (reviewable prompt, real doc paths) + `write_next_prompt` → `NEXT-PROMPT.md`. `terminal_session.auto_advance_planning_to_build` (+ reconcile_and_advance + finish_to_build path) now start the next session with `paste_prompt=` (Wave-1 pending paste, UNSENT) instead of the auto-submitted seed; both artifacts written. `/api/rnd/advance_session` (research→plan) delivers the paste + records the stage edge + `_flashPendingPasteHint`. Mockup `_mockups/advance_paste.html`. New tests + Playwright `test_advance_paste_ui_v10.py`.
- **GATE 1.** Found 3 regressions in `test_handoff_docs_v8.py` (the build-seed assertions — the task content correctly moved seed→paste). **FIX:** relocated those 3 tests to assert the real paths + Foreman in `pending_paste` + `NEXT-PROMPT.md` (plan-cited per D6; strictly stronger, none weakened). Playwright header test was case (a) — header correctly shows Foreman.
- **REVIEW (2 independent, refute).** Corroborated (≥2): the Playwright POSITIVE token (`"Crucible"`) also appears in the echoed phase-1 seed → non-discriminating; no RENDERED negative for not-auto-submitted (v4 standard gap). Plus: `finish_to_build` marks planning DONE without `kill` → docs not persisted → build checkout can lack the paths `NEXT-PROMPT.md` references (North-Star hole). Plus LOW: redundant "Load the skill" in the reviewable paste.
- **FIX iter 1.** (1) UI test now asserts a paste-ONLY token (`research/run-1/REPORT.md`, absent from the seed) is visible in the xterm DOM + a rendered negative (cursor stays on the paste row; no submitted row below) — **proven non-vacuous by sabotaging `_flush_pending_paste` with `\n` (test FAILED), then reverting**; added a non-Playwright DOM positive+negative leg. (2) `finish_to_build` now `capture_session_docs` (persist+commit to main, NO reap — tile stays) BEFORE advancing, so the build worktree contains the docs; new test asserts `(build_wt/impl).is_file()` + main commit. (3) `handoff.clean_paste_opener` strips the redundant load-prefix from the paste only ("With Foreman loaded, …"); seeds unchanged; skill name + paths + read-first preserved. (Recovered from an accidental `git checkout` of terminal_session.py — reconstruction verified by the full gate.)
- **GATE 2 (orchestrator-run, of record).** `python -m pytest -q` → **GREEN 1094 passed, 1 skipped**.
- **VERDICT: GO — committed to branch; HALT for John's screenshot sign-off** (`_devtest/wave2_advance_paste.png`) before the wave counts done / any merge.
