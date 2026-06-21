# Anchor R&D Surface v12 — "Efforts" — Execution Log

> Foreman appends per-wave EXECUTE / ADVERSARIAL-REVIEW / FIX / GATE history here.
> Frozen design: `MASTER-PLAN.md`. Build plan: `IMPLEMENTATION-PLAN.md`.
> Branch: `foreman/rnd-surface-v12` (off master `f2e0e40`, v11.1 merged + deployed). Baseline GREEN 1266.

## Wave 1 — Effort record: stage fields + `effort_managed` + `effort_id` passthrough + back-compat normalize — GREEN ✅

- **EXECUTE:** `session_registry._normalize` gains `kind`/`current_stage`/`stage_history`/`seeded_stages`/
  `effort_id`/`effort_managed` (back-compat defaults; `effort_managed` default False); `register_session`
  + `update_session` thread the new fields; new helpers `effort_root`/`stage_entry`/`set_current_stage`
  (closes prior active entry → appends new, under the re-entrant `WRITE_LOCK`). `terminal_session.start_session`
  gains `effort_id=`/`effort_managed=` passthrough (no behavior change for existing callers).
  `anchor_gui._effort_zone(record)` accessor (render unchanged this wave). New `tests/test_effort_record_v12.py`.
- **GATE (orchestrator-run):** `python -m pytest -q` → 1273 passed, 1 skipped (baseline 1266 + 7).
- **REVIEW (2 independent, adversarial):** both GO-WITH-NITS, zero BLOCKERs. Nits applied at source:
  R1-01 re-derive `current_stage` on `""` not just `None`; R2-1 deep-copy `stage_history` entries in
  `_normalize` (kill the W4/W5 aliasing hazard). +2 regression tests.
- **RE-GATE:** 1275 passed, 1 skipped. **Converged.**
- **Forward note (R2-2):** a freshly-started effort has `current_stage` but an empty `stage_history`;
  W3/W6 MUST establish the first stage entry (or consumers guard `stage_entry()==None`). R2-3: the only
  sanctioned stage flip is `set_current_stage` (keeps `current_stage`+`lane` in sync).

