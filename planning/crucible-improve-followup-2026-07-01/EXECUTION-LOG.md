# Execution Log — Crucible-Improve Follow-up (Foreman)

Status: IN PROGRESS — driven by Foreman (Claude/Opus orchestrating).
Gate: `python -m pytest -q` (orchestrator-run, full suite).

| Wave | Title | State |
|------|-------|-------|
| 1 | Claude-first session launch | GREEN |
| 2 | Unified dock controls (× + 🪦) [UI sign-off] | pending |
| 3 | Bridge job cost onto the effort record | pending |
| 4 | Triage & fix pre-existing baseline reds (~59) | pending |

## Wave 1 — Claude-first session launch — GREEN (2026-07-01)

**EXECUTE.** Made Claude the launch default at every real site in `anchor_gui.py`
(the earlier investigation found more than the two originally reported):
`newTermSession` default, `newEffort` payload, the grass workbench `_grassEngine`,
the `_buildEngineToggle` highlight default, four `rec.backend || 'gemini'` MANAGED
display-fallbacks, and the legacy kanban research launcher. Confirmed the
server-side default is already Claude and the `backend="gemini"` at :16741 is a
correct claude-first fallback (only when the `claude` CLI is absent). New gate:
`tests/test_claude_first_launch_w1.py`.

**REVIEW (2 independent, refute-prompted).** Reviewer B: no regression (the server
is the source of truth for `backend`; the `repopulate()` re-sync uses an
empty-string, not claude, fallback; the engine toggle is live-only). Reviewer A:
found a REAL gap — `promoteGrass` / `continueSession` sent no backend, so the
server resolved to the project's **sticky `last_engine_for_project`**; after any
per-session Gemini toggle, an unrelated promote/continue would silently open on
Gemini (violating the policy). Reviewer A also flagged the first test cut as
string-only (blind to that path).

**FIX.** Threaded an explicit Claude default through both paths: client payloads
now send `backend:'claude'`, and the `promote_grass`/`continue_session` handlers
default to `DEFAULT_ENGINE` (never the sticky last_engine); `advance_session` is
intentionally left inheriting its own effort's engine (legitimate continuity —
its source was explicitly toggled). Added 3 behavioral (stub-PTY) tests that set
`last_engine=gemini` and prove promote/continue still open Claude, plus a
"witness" test documenting the sticky leak at the source. `test_engine_persist` /
`test_cli_v4` (the intentional sticky-engine semantics) stay green — no global
behavior change.

**GATE (orchestrator-run full suite).** 60 failed / 1616 passed. Delta vs the
59-red baseline: my 11 new tests all pass; exactly ONE pre-existing test flipped
red — `test_project_window.py::test_summary_panel_no_leaked_braces`. Verified it
is a **full-suite ORDER/isolation flake, NOT a Wave-1 regression**: it passes in
isolation AND passes when run immediately after the new test file; my edits are
brace-free raw-string value swaps to a panel I never touched. Per the gate rule (a
red that does not reproduce in isolation cannot block GREEN) Wave 1 is GREEN.
→ **Added to Wave 4 triage: `test_summary_panel_no_leaked_braces` (test-pollution
/ order-flake category).**

**Also noted for Wave 4:** `_render_kanban_html` is dead code (no live caller;
`/api/rnd/board_html` renders `_render_layoutd_html`) — candidate for removal.

## Baseline (pre-Wave-1)

Full suite `python -m pytest -q`: **59 failed / 1606 passed** (15m15s). The prior
crucible-improve build gated on a subset, so these were not caught. Probed sample
confirms the majority are stale W6 control-scheme tests (assert removed
`hardkill`/🗑/`panelbtn delete`) + environmental browser tests. Full categorized
list captured for Wave 4. My waves 1–3 gate on "no NEW reds beyond this baseline";
Wave 4 clears the baseline itself.

---

(Per-wave EXECUTE → GATE → REVIEW → FIX records are appended below as each wave runs.)
