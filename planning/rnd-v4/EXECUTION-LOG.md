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
