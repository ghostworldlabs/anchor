#!/usr/bin/env bash
# Foreman gate wrapper — runs under git-bash so the per-wave glob expands
# (cmd.exe, which Foreman's spawnSync uses, does NOT expand globs). nullglob
# means a non-matching wave glob disappears instead of erroring pytest.
cd "$(dirname "$0")" || exit 2
shopt -s nullglob
exec python -m pytest -v \
  tests/test_zombie_hunter.py tests/test_swarm_zombie_coverage.py tests/test_cancel_liveness.py \
  tests/test_session_registry.py tests/test_history.py tests/test_session_continue.py \
  tests/test_effort_view_v12.py tests/test_context_handoff_v12.py tests/test_deliverables.py \
  tests/test_build_deliverable.py tests/test_engine_persist.py tests/test_engine_selector.py \
  tests/test_lanes_concurrency.py tests/test_terminal_session.py tests/test_terminal_seed.py \
  tests/test_gandalf_endpoints.py tests/test_gandalf_engine.py tests/test_worktrees.py \
  tests/test_*_w[0-9].py \
  --deselect tests/test_session_continue.py::test_historical_panel_shows_summary_and_continue_works \
  --deselect tests/test_build_deliverable.py::test_build_deliverable_in_lane_and_panel_playwright
