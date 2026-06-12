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

## Wave 3 — Per-lane doc roles + cost/tokens/time rollup (data layer) — ✅ GREEN

- **EXECUTE:** `summarizer.session_doc_roles(pid, lane, session_id)` — per-lane role→doc map (research: exec/report/agent/provenance · planning: master/impl/northstar · build: northstar/deliverable/execlog/plan), hrefs via existing `/report` + `/artifact` routes (same URL-quoting as `_member_links`), absent roles omitted. `effort_history.project_effort_rollup(pid, window, now)` — sums `attach_cost` records for RUN-provenance sessions only (imported/discovered → 0), 30d via injected `now` (finished_at else created_at, boundary-inclusive). Lazy `import sessions` to avoid the sessions↔effort_history cycle. New `tests/test_doc_roles.py` (8) + `tests/test_effort_rollup.py` (7).
- **REVIEW (refute):** **GO** — all 5 VERIFIED via repros: rollup field-extraction matches the real `attach_cost` shape (no phantom fields), run-only + discovered-skip double guard, 30d cutoff correct, doc-role hrefs use real routes + omission, lazy import dodges a real cycle, no fork. `git diff tests/` clean (2 new files only); no `anchor_gui.py` change (data-layer honored).
- **GATE (orchestrator-run):** **569 passed, 1 skipped** (+15 new). Converged in 0 fix iters.

## Wave 4 — Paradigm 2 project window: lane tiles + lights + inline expanding panels — ✅ GREEN

- **EXECUTE:** `anchor_gui.py` — removed the v3 floating window manager (`.termwin`/`.winlayer` CSS+DOM; JS `openSessionWindow`/`_toggleMinimize`/`_closeWindow`/`killSession`/`_wireDrag`/`_wireResize`/`WINDOWS`/`_winZ`); added the Paradigm-2 inline accordion: `.lane-tile` with status lights (`.lt green/amber/red/grey`), a `.panel-stack` host, and JS `openPanel`/`minimizePanel`(keeps session running)/`killPanel`(confirm-gated `term_kill`)/`repopulate`(reads `/api/rnd/term_sessions`)/`laneTileClick`. New Python `_session_light_class`. Seeded launch (`newTermSession`→`term_start`) + all transports preserved. New `tests/test_cockpit_render.py` (9); adapted `test_window_manager_markup_present` to the inline DOM.
- **REVIEW (refute):** **GO** — critical dangling-reference sweep clean (no removed symbol survives in a real 60 KB render; all new symbols defined; `loadSessions`→`repopulate` deferred-handler ordering safe); brace hygiene verified on a live render (no leaked `{{`/`}}`); test adaptation preserved + ADDED negative assertions, no drops/skips; `_session_light_class`/JS `_statusColor` share the locked session_registry buckets. Nits only (stale comment; two green hexes for two elements).
- **GATE (orchestrator-run):** **578 passed, 1 skipped** (+9 new). Converged in 0 fix iters.

## Wave 5 — Panel internals: stacked summary (equal-height split) + resizable terminal — ✅ GREEN

- **EXECUTE:** `anchor_gui.py` — `openPanel` now builds a stacked body: split summary on top (`.smat` materials left from `/api/rnd/session_summary` · `.slinks` role links right from Wave-3 `session_doc_roles`, both columns equal-height via `margin-top:auto` + grid `align-items:stretch`) and a full-width `.tpane` terminal below (`_mountTerminal` reused; `resize:vertical` + `_wirePanelResize`→`_fitPanelTerminal`→`term_resize`). New token-gated read-only GETs `/api/rnd/session_doc_roles` + `/api/rnd/project_rollup`. Header shows `Σ tokens · $ · time · N sessions` (`render_header_rollup_html`, real `project_effort_rollup` lifetime) + a lifetime/30d toggle. New `tests/test_panel_render.py` (12).
- **REVIEW (refute):** **GO** — live repros: 73 KB render with zero `{{`/`}}` leaks; both endpoints 401-on-no-token + 400-on-traversal, call the real Wave-3 fns; resize functional (POSTs `term_resize`); equal-height CSS matches the mockup; rollup run-only/honest; `git diff` source = anchor_gui.py only, test file new, nothing weakened. Cosmetic dead `p.fit` branch noted (working path unaffected).
- **GATE (orchestrator-run):** **590 passed, 1 skipped** (+12 new). Converged in 0 fix iters.
