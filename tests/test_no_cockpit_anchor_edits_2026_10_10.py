"""John 2026-10-10: a cockpit never changes Anchor's own code (he makes those changes from outside Anchor), and a code
job's processes never carry Anchor's key."""
import os
import sys

import anchor_settings
from steward_cockpit import code_jobs
from steward_cockpit import steward_engine as se


def test_every_steward_is_told_the_rule():
    for duty in (se.SMALL_DUTY, se.EFFORT_DUTY):
        assert "never changed from a cockpit" in duty
    assert "any change to an Anchor application file" not in se.SMALL_DUTY


def test_a_code_jobs_commands_never_carry_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "secret-for-test")
    out = tmp_path / "out.txt"
    with out.open("wb") as fh:
        run = code_jobs._popen_contained([sys.executable, "-c", "import os; print(os.environ.get('ANCHOR_TOKEN'))"],
                                         str(tmp_path), dict(os.environ), fh)
        run.proc.wait(timeout=60)
        if run.wjob is not None:
            run.wjob.close()
    assert out.read_text().strip() == "None"


def test_a_coder_never_carries_the_key_but_a_steward_does(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "secret-for-test")
    monkeypatch.setattr(se, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": "claude", "settings_revision": 1})
    eng = se.Engine(str(tmp_path), fake=True)
    assert eng._spawn_env().get("ANCHOR_TOKEN") == "secret-for-test"      # stewards start jobs with it
    eng.code_job = {"cdir": str(tmp_path), "id": "x"}
    assert "ANCHOR_TOKEN" not in eng._spawn_env()
