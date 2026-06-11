# Anchor R&D Surface v2 — Execution Log

> Foreman appends per-wave EXECUTE / REVIEW / FIX / JUDGE entries here. Seeded by
> the Crucible→Foreman handoff on 2026-06-11. Frozen design: `MASTER-PLAN.md`.
> Plan: `IMPLEMENTATION-PLAN.md`. Ground-truth gate: `python -m pytest -v`.

## Handoff (2026-06-11)

- Crucible Stage 0 (North Star locked), Stage 1 (Master Plan approved), Stage 2
  (8-wave plan, internal Shark-Tank converged with no ≥2-agree blocker) complete.
- User decisions: one comprehensive build (not phased); interactive terminal =
  stream-json REPL (stdlib-honoring, no ConPTY); reconcile folds retired sibling
  history into the active id then hard-deletes the test ids; summaries generated
  once with multi-run validation and cached.
- Awaiting Foreman Wave 1.

---

## Wave 1 — Session model + grouping — GO (2026-06-11)

- EXECUTE: new `sessions.py` wrapping `effort_history` (no UI touched, storage unforked); `list_sessions` groups run efforts by job_id, discovered by parent dir, fallback skill+timestamp cluster; `merge_sessions`/`split_session` via `sessions-overrides.json` sidecar; `tests/test_sessions.py` (11 tests).
- GATE (orchestrator-run): 295 passed, 1 skipped.
- REVIEW (2 independent): both agreed test_sessions.py:96 OR-assertion was loose (confirmed). Single-reviewer findings: missing-job_id run grouping (A), `*-overrides.json` not in .gitignore allow-list (B) — neither a ≥2-agree blocker nor gate-failing, but both legitimate + cheap → fixed. Reviewer-A "test against live store" MAJOR rejected (hermetic tests are mandated).
- FIX (1 iter): .gitignore allow-lists `*-overrides.json` (C9); empty-job_id run efforts → unique stable session each (Wave-6 cache determinism); tightened the ordering assertion; +1 test.
- RE-GATE (orchestrator-run): **296 passed, 1 skipped**. Converged.
- Acceptance proven: active-project planning fixture (7 discovered files / 2 dirs) → exactly 2 sessions, newest-first, no dup/dropped members.

---

## Wave 2 — Folder-history unification + reconcile + deliverable pinning — GO (2026-06-11)

- EXECUTE: sibling-store adoption (`effort_history.sibling_store_ids`/`adopt_sibling_sessions`), `rnd_registry.reconcile_folder(active_id, apply=False|True)` (preview-then-fold-then-hard-delete, all under WRITE_LOCK, never touches active or different-folder ids), new `deliverables.py` (Anchor.md marker parse + pin), `POST /api/rnd/pin_deliverable`. Ids read from registry by folder at runtime (not hard-coded). New `tests/test_reconcile.py` + extended `tests/test_deliverables.py`/`test_brownfield_adopt.py`.
- GATE (orchestrator-run): 312 passed, 1 skipped. Live registry untouched (hermetic tests).
- REVIEW (2 independent): Reviewer A raised a path-traversal BLOCKER in `deliverables._relpath` (relative `..` stored unvalidated); Reviewer B independently judged path handling safe → not a ≥2-agree blocker, and serve-time guard (`test_artifact_route_safety`) already limits exploitability. Fixed anyway (defense-in-depth, data-sensitive wave). Idempotency test-gap (A major / B minor) also closed.
- FIX (1 iter): `_relpath` now resolves against the folder and raises ValueError on any escape (reusing the report_viewer/`/artifact` containment pattern); endpoint returns 400 not 500; +2 tests (traversal-reject, fallback-jid idempotent). One resolved ambiguity: malicious-Anchor.md hardening left out — Anchor.md is a trusted repo-committed file; ValueError still can't crash the endpoint. Sound default, no user HALT.
- RE-GATE (orchestrator-run): **314 passed, 1 skipped**. Converged.

---

## Wave 3 — First-class imported history (status-line, tiles, blurb) — GO (2026-06-11)

- EXECUTE: `status_line` reshaped to per-lane `{count, imported, running}` built from `sessions.list_sessions` (session = unit, so 7 discovered planning files = 2); all callers + 3 dependent tests updated; tile/window render a real per-lane summary line + per-lane "imported" chip (no more "import"/"none-yet" masquerade); per-project `blurb` field + `POST /api/rnd/set_blurb` + `seed_blurb` (CLAUDE.md→README→Anchor.md, bounded, escaped). New `tests/test_tile_render.py`.
- GATE (orchestrator-run): 326 passed, 1 skipped; `import anchor_gui` clean (f-string discipline held).
- REVIEW (2 independent): no BLOCKERs; both confirm HTML escaping correct, counts session-based, graceful degradation, acceptance renders exactly per spec. Single-reviewer MAJORs (B): CSS inconsistency across the two style blocks; benign idempotent blurb-seed race. "running always 0 for discovered" rejected (correct behavior).
- FIX (1 iter): aligned `.rnd-status-line`/`.rnd-lane`/`.rnd-imported` across both style blocks (brace conventions preserved); added XSS-escaping regression test. Seed-race left as-is (idempotent, exception-guarded).
- RE-GATE (orchestrator-run): **327 passed, 1 skipped**. Converged.

---

## Wave 4 — Project window restructure — GO (2026-06-11)

- EXECUTE: Kanban now renders SESSIONS (Wave-1 list_sessions) as most-recent card + "previous sessions (N)" expander per lane (one trio run = one card, multi-file collapses behind "files (N)"); 5th "Grass Catchers" column added (structure only; grass added to LANE_DIRS + effort_history LANE_SUBDIR); dead "no tasks linked yet" replaced by a working linked-tasks strip (Link/Unlink via existing link_task). Extended tests/test_project_window.py.
- GATE (orchestrator-run): 334 passed, 1 skipped; imports clean.
- REVIEW (2 independent): Reviewer B GREEN/zero-blockers (verified ordering, integration w/ W2-3, crash-resilience, XSS escaping, scope-tight). Reviewer A single-reviewer BLOCKER on rndUnlinkTask — mechanism muddled but underlying defect real (inline onclick string arg breaks for task text with apostrophes/quotes). Fixed.
- FIX (1 iter): task identity now rides via HTML-escaped data-attributes (`data-task`/`data-project`) + `rndUnlinkTask(this)`/`rndLinkTask(this)` reading `el.dataset` — no inline JS string arg carries task text; backend by-text match now round-trips for special chars; +1 test (`Fix it's "weird" bug`).
- RE-GATE (orchestrator-run): **335 passed, 1 skipped**. Converged.

---

## Wave 5 — Grass Catchers content sources — GO (2026-06-11)

- EXECUTE: `add_idea` + `POST /api/rnd/add_idea` (real source=run grass card, honesty contract kept); `promote_inbox` + `POST /api/rnd/promote_inbox` (reuses existing inbox parser, copy-by-default/non-destructive); brownfield `_classify` grass rules (SAVED_FOR_LATER, bare PLAN.md stubs → grass) ordered AFTER the named-trio planning check so real trio docs are never demoted; grass column affordances wired; CLI mirror in anchor.py. New tests/test_grass_catchers.py + extended test_brownfield_scan.py.
- GATE (orchestrator-run): 351 passed, 1 skipped.
- REVIEW (2 independent): Reviewer A full PASS (classification conservatism, honesty contract, auth, distro-scan integrity — tok-123 is a pre-existing allowlisted placeholder, no scan weakened). Reviewer B single-reviewer MAJOR-1: reconcile/sibling-adoption folded only cost-rollup lanes, so a retired id's grass ideas would be hard-deleted without folding — data-loss path contradicting the locked "fold history then delete" decision.
- FIX (1 iter): added `FOLD_LANES` (rollup lanes + grass); `adopt_sibling_sessions` + `reconcile_folder` now fold ALL content lanes incl. grass before hard-delete; COST rollup (`ROLLUP_LANES`) deliberately unchanged (grass has no cost); +1 test proving grass ideas survive reconcile and add no cost.
- RE-GATE (orchestrator-run): **352 passed, 1 skipped**. Converged.

---
