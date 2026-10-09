"""The final review of the night of 2026-10-10 (reviews/final1010-anchor.md): the fixes it asked for, proven."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import code_jobs, link_check, skill_jobs  # noqa: E402
from steward_cockpit import steward_campaign as sc  # noqa: E402
from steward_cockpit import steward_routes as sr  # noqa: E402


def test_a_failed_integration_check_stops_the_stage_line_there():
    j = {"files": ["a.py"], "check": "pytest", "check_ok": True, "review": {"verdict": "PASS"},
         "integration_check_ok": False, "landed": False}
    assert code_jobs.stage_line(j) == "made → checked → reviewed → integration check failed"
    src = (ROOT / "steward_cockpit" / "code_jobs.py").read_text(encoding="utf-8")
    assert 'fields["integration_check_ok"] = ok is True' in src


def test_a_stopped_code_jobs_flag_is_left_alone(tmp_path):
    (tmp_path / ".ecgberht").mkdir()
    (tmp_path / ".ecgberht" / "code-jobs.json").write_text(json.dumps({"c1": {"id": "c1", "status": "stopped"}}))
    (tmp_path / ".ecgberht" / "attention.json").write_text(json.dumps({"state": "working", "reason": "x", "job": "c1"}))
    assert sc.clear_stale_job_flag(tmp_path) is None


def test_the_restart_check_counts_a_running_skill_job_and_none_starts_mid_drain(monkeypatch, tmp_path):
    class Alive:
        def poll(self):
            return None
    monkeypatch.setitem(skill_jobs._PROCS, "k-test", Alive())
    import job_runner
    monkeypatch.setattr(job_runner, "jobs_dir", lambda: tmp_path)
    try:
        assert "skill:k-test" in sr._running_job_ids()
    finally:
        skill_jobs._PROCS.pop("k-test", None)
    from steward_cockpit import maintenance
    monkeypatch.setattr(maintenance, "is_active", lambda: True)
    monkeypatch.setattr(skill_jobs, "validate", lambda argv: (True, ""))
    out = skill_jobs.start(str(tmp_path), ["node", "x.mjs"])
    assert out["ok"] is False and "draining" in out["error"]


def test_a_malformed_anchor_link_still_records_no_credential():
    out, _ = link_check.check_reply("[bad](http://localhost:99999/x?path=a&token=SECRET2)", ".", hosts={"localhost"})
    assert "SECRET2" not in out


def test_the_serving_size_limit_is_respected(tmp_path, monkeypatch):
    proj = tmp_path / "P"
    eff = proj / "E"
    eff.mkdir(parents=True)
    (eff / "ECGBERHT.md").write_text("# x", encoding="utf-8")
    big = eff / "big.pdf"
    big.write_bytes(b"%PDF")
    monkeypatch.setattr(link_check, "_project_folder", lambda pid: str(proj))
    real_stat = Path.stat

    def fake_stat(self, *a, **k):
        st = real_stat(self, *a, **k)
        if self.name == "big.pdf":
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, st.st_nlink, st.st_uid, st.st_gid,
                                   60 * 1024 * 1024, int(st.st_atime), int(st.st_mtime), int(st.st_ctime)))
        return st
    monkeypatch.setattr(Path, "stat", fake_stat)
    assert link_check.check_route("/api/steward/deliverable-file?pid=p&dir=E&path=big.pdf") == "unavailable now"
