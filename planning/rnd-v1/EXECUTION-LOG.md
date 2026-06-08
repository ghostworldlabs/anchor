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
