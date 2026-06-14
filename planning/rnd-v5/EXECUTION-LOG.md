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
