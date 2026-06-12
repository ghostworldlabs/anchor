# Anchor R&D Surface v4 — "Project Cockpit" — Execution Log

> Foreman appends per-wave EXECUTE / REVIEW / FIX / JUDGE history here. Seeded by
> Crucible at handoff 2026-06-12. Frozen design: `MASTER-PLAN.md` +
> `IMPLEMENTATION-PLAN.md` (this folder).

## Handoff (Crucible → Foreman) — 2026-06-12

- Design locked by the user across three review rounds; canonical spec =
  `_mockups/project_window_proposals.html` (Paradigm 2) +
  `_mockups/branding_proposals.html` (Option B).
- Terminal substrate proven by `_prototypes/term_harness/` (real ConPTY × WebSocket
  × xterm.js; `pty_smoke.py`, `ws_client_test.py`, `claude_interactive_capture.py`
  all pass).
- 9 waves, terminal wave = Wave 9. test-command: `python -m pytest -v`.

<!-- Foreman: append wave records below this line -->

## Wave 1 — One terminal substrate: skill auto-load-once + greet-once — ✅ GREEN

- **EXECUTE:** added per-lane skill-seed map (research→researchPrime · plan/planning→Crucible · build→Foreman) + `seed_for_lane()` (env-overridable) in `terminal_session.py`; `start_session` writes the seed as exactly ONE stdin turn after PTY launch and records `seeded`/`seed_text` (new fields in `session_registry.py`, normalized + atomic). New `tests/test_terminal_seed.py` (11 tests).
- **REVIEW (refute):** items 1–4 VERIFIED (seed-once integrity, no test-weakening, lane→skill map, persistence). **MAJOR-CONCERN:** Done-when "no rnd_terminal in cockpit wiring" unmet — `anchor_gui.py` lane "+ New run" still wired the unseeded v2 REPL (`openTerminal`/`start_terminal`).
- **FIX iter 1:** repointed the cockpit lane-launch affordance to the seeded path (`newTermSession`→`/api/rnd/term_start`); added `tests/test_cockpit_substrate.py` (asserts seeded wiring, no `start_terminal` in lane launch); updated 3 existing tests that encoded the old buggy wiring (legitimate — same structure/guards, repointed to `newTermSession`).
- **GATE (orchestrator-run):** `python -m pytest -q` → **542 passed, 1 skipped** (baseline 529 + 13 new; the skip is a pre-existing host symlink/git skip). No test weakened. Converged in 1 fix iter.

## Wave 2 — Engine persistence + toggle — ✅ GREEN

- **EXECUTE:** `terminal_session.py` — `last_engine_for_project`/`set_last_engine_for_project` (persist to `.anchor/projects/<id>/engine.json`, atomic under WRITE_LOCK, default `claude`); `start_session` defaults backend to the project's last engine (`_UNSET` sentinel) + records it on success; `switch_engine(session_id, engine)` reaps the PTY and rebinds a new one under the SAME session_id+worktree (policy-checked via existing `lanes.check_engine_allowed` BEFORE reaping; rollback to a consistent record on failure). `POST /api/rnd/term_set_engine` in `do_POST` behind token auth (400 invalid-engine / 404 unknown-session). New `tests/test_engine_persist.py` (12 tests).
- **REVIEW (refute):** **GO** — all 5 items VERIFIED via live repros (orphan-safety: exactly one PTY, worktree reused; rollback leaves status=idle + prior backend; policy refusal uses canonical `lanes` source, no scope creep, leaves running session intact; persistence defaults on missing/corrupt; endpoint auth + validation). `git diff --stat tests/` empty — no existing test modified/weakened.
- **GATE (orchestrator-run):** **554 passed, 1 skipped** (+12 new). Converged in 0 fix iters.
