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
