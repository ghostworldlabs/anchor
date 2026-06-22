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

## Wave 2 — Layout-D static skeleton render (UI-gated) — GREEN ✅ (John signed off)

- **EXECUTE:** `render_project_window_html` swapped to `_render_layoutd_html` (Latest-Research headline +
  collapsible older-research shelf; Latest-Plan/Build headline + shelf; persistent right column with Grass +
  Deliverables; inert bottom-dock chrome; "+ New effort" disabled/labeled "(wired in W10)"). New renderers
  `_layoutd_zones`/`_render_layoutd_*`; `toggleShelf` JS (flips `.collapsed`); `/api/rnd/board_html`
  repointed. Driven by the EXISTING `_gather_project_sessions` (no effort_view/advance dependency).
  ~17 prior UI tests migrated from the retired 5-col `.p2lanes` board to Layout-D landmarks (intent
  preserved; refreshBoard/one-tile-per-session/status-dedup/seeded term_start/panel-open all kept). New
  `tests/test_layoutd_skeleton_v12.py` (render-smoke brace-balance + DOM pos/neg) +
  `tests/test_layoutd_skeleton_playwright_v12.py` (Chromium shelf-toggle `.collapsed` flip).
- **GATE (orchestrator-run, authoritative):** 1280 passed, 1 skipped.
- **REVIEW (2 independent, adversarial):** both GO-WITH-NITS, zero BLOCKERs. Acted on:
  **F1 (MAJOR, R2):** Plan/Build headline picked the OLDEST plan (effort views had no epoch → merge
  sort degenerate) → fixed by stamping `_eff_created_at` on the effort view + using it in `_sv_created_at`;
  + regression test (newer build beats older plan for the headline). **W2-R1 (MINOR, R1):** the
  engine-selector migration left a dead-token positive assertion (`assert 'engtog' in html`) → made honest
  (kept real negatives; the rendered engine affordance is re-asserted in W10). Dead `.p2lanes`/kanban
  helpers left in place (W10 reuses the tile helpers).
- **RE-GATE:** 1281 passed, 1 skipped. **Converged + UI sign-off (screenshot `_mockups/w2_layoutd_screenshot.png`).**

## Wave 3 — Keystone A: per-stage baseline commit + stage-scoped persist + stage deliverable — GREEN ✅

- **EXECUTE:** `effort_history.record_stage_baseline` (HEAD sha as baseline) + `persist_session_stage_docs`
  (EXACT git: `diff <base>..HEAD` ∪ `diff <base> --` ∪ `status --porcelain -uall` additions, MINUS
  prior closed-stage paths via `efforts_for_session_stage`; tags efforts by `(session_id, stage)`;
  best-effort, idempotent) + `efforts_for_session_stage`. `deliverables.resolve_build_deliverable`/`backfill`
  stage-scoped for efforts (build-stage docs only; honest unresolved off-build; legacy path byte-unchanged).
  Build stage also persists products (not just docs). New `tests/test_stage_baseline_persist_v12.py` +
  `tests/test_stage_deliverable_v12.py` incl. the Shark-B1 legacy-superset falsification + B2 uncommitted
  build product + deliverable decoy. Legacy `persist_session_docs`/`_produced_doc_rels` untouched.
- **GATE:** 1291 passed, 1 skipped.
- **REVIEW (2 independent):** both GO-WITH-NITS. Two MAJORs = two sides of the build-accept heuristic:
  **W3-R1** over-capture (swept `.pyc`/`.dll`/`.coverage`/bundle trees) + **W3-R2** under-capture (dropped
  a ROOT product like `anchor_gui.py`, the canonical Anchor deliverable). Fixed: build-accept switched from
  a dir-allowlist to a **junk denylist** (`_BUILD_JUNK_EXT` + dotfiles excluded) accepting root + any-depth
  products, PLUS a bundle-sweep cap (`_MAX_BUILD_PRODUCTS=25` non-doc → docs-only, rely on explicit pin).
  +3 tests (root captured / junk excluded / bundle capped). W3-N1 (prior-stage lane coupling) = documented
  forward-note for the W6 wiring (callers must pass the canonical store_lane). Verified good: git mechanic,
  falsification genuineness, legacy byte-unchanged, idempotency, backfill C6 protection, distro clean.
- **RE-GATE:** 1294 passed, 1 skipped. **Converged.** (Keystone unwired until W6 — by design.)



