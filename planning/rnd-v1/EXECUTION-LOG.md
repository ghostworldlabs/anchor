# Anchor R&D Control Surface — Execution Log

Foreman appends wave-by-wave execution state here (EXECUTE → REVIEW → FIX → RE-REVIEW →
gate verdict per wave). Seeded empty at Crucible handoff.

## Pre-Foreman status
- Spike-0: COMPLETE (see `MASTER-PLAN.md` → Spike-0). Keystone mechanism proven.
- SETUP.md human gate: **PENDING** — must be completed (service-as-john, Tailscale, orphan
  reap, dup-supervisor close; the real-Crucible go/no-go that emits the Wave-5 fixture)
  before invoking Foreman to build.

## Wave log

### Wave 1 — Establish the pytest gate + test harness — GO (2026-06-08)
- EXECUTE: created `pyproject.toml` (`[tool.pytest.ini_options]`, `testpaths=["tests"]`, no runtime deps, pytest under dev extra), `tests/__init__.py`, `tests/conftest.py` (sys.path bootstrap), `tests/test_smoke.py` (5 real tests exercising `anchor.parse_tasks_from_md`). No existing source modified.
- GATE (orchestrator-run `python -m pytest -v`): **GREEN, 5 passed**, exit 0.
- REVIEW (2 independent, refute-prompted): both GO. Shared finding MINOR-1.
- OPEN FINDING (carried to Wave 2): **MINOR-1** — `anchor.py:35` `LOGS_DIR.mkdir(exist_ok=True)` runs at import (idempotent, touches no data files); a test docstring overstates "side-effect free." Resolve when Wave 2 introduces `paths.py`/`ANCHOR_DATA_DIR`.

### Wave 2 — Foundations (code only) — GO after 1 fix iter (2026-06-08)
- EXECUTE: new `paths.py` (lazy `ANCHOR_DATA_DIR` resolution, `ensure_data_dirs()`, process-wide re-entrant `WRITE_LOCK`, `auth_ok()`/`expected_token()`, `bind_with_retry()`, idempotent `migrate_data()`). `anchor_gui.py` → `ThreadingHTTPServer`, `@_with_write_lock` on all mutators, token gate atop `do_POST`, `make_server()`. `anchor.py`/`anchor_healthcheck.py` route paths via `paths`; MINOR-1 closed (import-time mkdir removed, now lazy). Tests: test_paths/test_threading_locks/test_auth/test_migration.
- GATE (orchestrator-run): GREEN, 22 passed.
- REVIEW (2 independent, refute): A=GO (2 minors). B=NO-GO, **MAJOR W2-M1** w/ repro: healthcheck round-trip posts tokenless → 401 under configured `ANCHOR_TOKEN` (breaks "healthcheck preserved" + SETUP §6). Honored despite single-reviewer (hard repro tied to done-when).
- FIX iter 1: healthcheck `_post()` attaches `X-Anchor-Token` when configured + adds SETUP §6 unauth-rejection (tokenless POST asserted 401, skipped when no token); removed dead `/api/shutdown` POST (W2-m2); `capture_inbox` creates `INBOX.md` when absent → zero-loss on fresh data dir (W2-m3, both CLI+GUI). New tests: test_healthcheck_auth, test_capture_fresh_dir.
- RE-GATE: GREEN, **27 passed**, 0 skip/xfail. RE-REVIEW: all 3 findings CLOSED with reproduced evidence → GO.
- Carried MINORs (non-blocking, not Wave-2 scope): legacy `anchor_server.py` imports flask (out of product surface — quarantine later); module-level path constants snapshot env at import (documented "set env before import" contract).

### Wave 3 — Registry + New Project flow + per-project store + folder-grouped window — GO after 1 fix iter (2026-06-08)
- EXECUTE: `rnd_registry.py` (id-keyed; folder_path non-unique; CRUD + group_by_folder + lifecycle retain-not-delete + path-missing + scaffold `.anchor/projects/<id>/{research,planning,build,deliverables,jobs}/` + tracking-policy `.gitignore`/README + idempotent legacy-id assignment; JSON under `ANCHOR_DATA_DIR`, all writes under `paths.WRITE_LOCK`). `dir_browser.py` (stdlib server-side dir browser, no-crash on missing). `anchor_gui.py`: New-Project flow (create-folder w/ optional git init + select-existing), `/project/<id>` route, folder-grouped tiles + 4-state status line, single-instance open map (lock-guarded), `/api/rnd/*` endpoints behind token gate. `Project:` field parse/preserve added to both `anchor_gui.py` and `anchor.py` (no-op until Wave 9). Tests: test_registry/test_new_project/test_project_window.
- GATE (orchestrator-run): GREEN, 52 passed.
- REVIEW (2 independent, refute): B=GO (all 7 criteria verified, no findings). A=GO-with-fixes: **F1 MAJOR** (project-window `<style>` used doubled braces in non-f-string literals → literal `{{`/`}}` in served CSS, stylesheet dropped; test only checked substrings = vacuous-GREEN gap) + **F2 MINOR** (`Project:` whole-line `raw_text` fallback mis-parses a task titled "...Project: X" → Wave 9 landmine).
- FIX iter 1: F1 → single-brace static CSS literals (adjacent real f-strings untouched); F2 → honor `Project:` only in trailing metadata segment in both parsers. New tests: CSS no-literal-brace guard + `Project:`-only-from-metadata in both parsers.
- RE-GATE: GREEN, **55 passed**, 0 skip/xfail. F1 closure verified by orchestrator (rendered HTML has single-brace CSS, no `{{`/`}}`). → GO.
- Hygiene: added `foreman-checkpoint.json` to `.gitignore` (transient orchestration artifact).
