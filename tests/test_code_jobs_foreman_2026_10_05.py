"""Foreman as the code worker (his word, 2026-10-05: no generic coder - Foundry skills): a code job whose check is a
real test run is built by Foreman in its worktree; its DONE or HALT is the job's result."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from steward_cockpit import code_jobs as cj  # noqa: E402


def test_a_real_test_run_is_a_foreman_gate():
    assert cj.is_test_gate("python -m pytest tests/x.py") and cj.is_test_gate("node --test test/a.test.mjs")
    assert cj.is_test_gate("npm test") and cj.is_test_gate("npm run test")
    assert not cj.is_test_gate("python tools/look.py") and not cj.is_test_gate("")


def test_the_documents_are_one_wave_gated_by_the_check():
    d, p, l = cj.foreman_docs({"id": "J", "brief": "# Do X\n## detail\nmore", "check": "python -m pytest -q t.py"})
    assert "test-command: `python -m pytest" in p and " -q" not in p, "Foreman refuses -q"
    assert p.count("## Wave") == 1 and "## Wave 1 - Do X" in p and "\n## detail" not in p, "the brief's headings are flattened"
    assert "Do X" in d and l.startswith("# Code job J")


def test_done_is_the_result_and_halt_is_an_error():
    ok = cj.foreman_result('x\nRUN_JSON_START {"status": "DONE", "waveResults": [{"wave": 1, "status": "GREEN"}]} RUN_JSON_END\n', 0)
    assert ok["error"] == "" and "wave 1 GREEN" in ok["text"]
    bad = cj.foreman_result('RUN_JSON_START {"status": "HALT", "haltReason": "vacuous green"} RUN_JSON_END', 0)
    assert "HALT" in bad["error"] and "vacuous green" in bad["error"]
    assert "did not finish" in cj.foreman_result("no record", None)["error"]
