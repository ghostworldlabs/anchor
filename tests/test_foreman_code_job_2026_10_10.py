"""Foreman as a code job's worker (John 2026-10-09: "route Foreman through the code-job path"). The final review of
the night of 2026-10-10 held Foreman because, started as a skill job, it wrote the project directly. Now it builds
inside the job's own worktree and its work goes through the code job's finish: the job's check, a review by a family
that wrote none of it, and the locked, verified landing. Foreman is never a skill job. Hermetic: a fake run-live.mjs
(tests/fake_foreman.mjs) and the fake reviewer (tests/fake_review.py); throwaway repositories only."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward_cockpit import code_jobs, skill_jobs  # noqa: E402

FAKE = ROOT / "tests" / "fake_foreman.mjs"
PASS = [sys.executable, "-c", "pass"]
PLAN = "# Plan\n\n## Wave 1 - change a.txt\n\nWrite two.\n"


def _repo(root, files=None):
    root.mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    for name, text in (files or {"a.txt": "one\n"}).items():
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "start"], check=True)
    return root


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "FOREMAN_RUN_LIVE", FAKE)
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    monkeypatch.setenv("FAKE_REVIEW_LOG", str(tmp_path / "review.log"))
    monkeypatch.setenv("FAKE_FOREMAN_LOG", str(tmp_path / "foreman.log"))
    monkeypatch.delenv("ANCHOR_FOREMAN_CODE_JOBS", raising=False)
    monkeypatch.delenv("ANCHOR_UNCONFINED_CODERS", raising=False)
    repo, cdir = _repo(tmp_path / "repo"), tmp_path / "steward"
    cdir.mkdir()
    return repo, cdir, tmp_path


def _wait(cdir, job_id):
    for _ in range(600):
        j = code_jobs.read_jobs(str(cdir)).get(job_id) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            return j
        time.sleep(0.1)
    raise AssertionError("the job never finished")


def _start(repo, cdir, **kw):
    kw.setdefault("check", PASS)
    return code_jobs.start(str(cdir), str(repo), "Change a.txt to two.", kw.pop("check"), worker="foreman", **kw)


def _tracked(repo):
    return subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True).stdout.split()


# ---- the protected lifecycle ----

def test_foreman_builds_in_the_worktree_and_lands_only_through_check_and_review(env):
    repo, cdir, tmp = env
    out = _start(repo, cdir)
    assert out["ok"] and out["worker"] == "foreman", out
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"      # nothing written in the project meanwhile
    job = _wait(cdir, out["job"])
    assert job["landed"] is True, job["land_note"]
    assert job["worker"] == "foreman" and job["skill"] == "Foreman" and job["foreman_profile"] == "slim"
    assert job["files"] == ["a.txt"] and job["authors"] == ["claude"]
    assert job["check_ok"] is True and job["review"]["verdict"] == "PASS"
    assert (repo / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert _tracked(repo) == ["a.txt"]                                   # Anchor's documents and config never land
    assert not (repo / "foreman.config.json").exists() and not (repo / ".foreman-job").exists()
    call = json.loads((tmp / "foreman.log").read_text(encoding="utf-8").splitlines()[0])
    assert call["argv"][0] == job["worktree"] and call["argv"][1:] == ["--profile", "slim"]    # never --git
    assert call["docs"]["plan"] == ".foreman-job/IMPLEMENTATION-PLAN.md" and call["profile"] == "slim"
    assert "## Wave 1" in call["plan"] and "test-command:" in call["plan"]
    review = json.loads((tmp / "review.log").read_text(encoding="utf-8").splitlines()[0])
    assert review[review.index("--author-family") + 1] == "claude"


def test_an_approved_plan_is_used_as_written_with_the_check_as_its_gate(env):
    repo, cdir, tmp = env
    job = _wait(cdir, _start(repo, cdir, plan=PLAN, profile="standard")["job"])
    assert job["landed"] is True and job["plan_given"] is True, job["land_note"]
    call = json.loads((tmp / "foreman.log").read_text(encoding="utf-8").splitlines()[0])
    plan = call["plan"].replace(chr(13), "")
    assert plan.endswith(PLAN) and plan.startswith("test-command: `")
    assert call["argv"][1:] == ["--profile", "standard"]


def test_a_halted_run_never_lands_and_its_work_is_kept(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "halt")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is False and job["status"] == "failed"
    assert "Foreman HALT" in job["error"] and "no-progress" in job["error"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "one\n"
    assert (Path(job["kept_worktree"]) / "a.txt").read_text(encoding="utf-8") == "two\n"


def test_no_record_of_the_writing_family_means_no_landing(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "no-routing")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is False and "which model family wrote it" in job["land_note"]


def test_a_review_by_the_writing_family_never_lands(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_REVIEW_FAMILY", "claude")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is False and "author's own family" in job["land_note"]


def test_a_failing_check_never_lands(env):
    repo, cdir, _ = env
    job = _wait(cdir, _start(repo, cdir, check=[sys.executable, "-c", "raise SystemExit(1)"])["job"])
    assert job["landed"] is False and "check failed" in job["land_note"]


def test_a_write_into_the_source_repository_blocks_the_landing(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "stray")
    monkeypatch.setenv("FAKE_FOREMAN_STRAY", str(repo / "stray.py"))
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is False and "stray.py" in job["land_note"]


def test_stop_ends_the_foreman_tree_and_the_restart_check_counts_it_until_it_is_gone(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "sleep")
    out = _start(repo, cdir)
    wt = Path(out["worktree"])
    for _ in range(100):
        if (wt / ".foreman" / "started").exists():
            break
        time.sleep(0.1)
    proc = code_jobs._FOREMAN_PROCS[out["job"]]
    from steward_cockpit import steward_routes
    assert "foreman:" + out["job"] in steward_routes._running_job_ids()
    assert code_jobs.stop(str(cdir), out["job"], actor="John")["ok"]
    proc.wait(timeout=30)
    for _ in range(100):
        if out["job"] not in code_jobs._FOREMAN_PROCS:
            break
        time.sleep(0.1)
    assert "foreman:" + out["job"] not in steward_routes._running_job_ids()
    job = code_jobs.read_jobs(str(cdir))[out["job"]]
    assert job["status"] == "stopped" and not job.get("landed")
    assert not (wt / "foreman.config.json").exists()                  # Anchor's file goes; the work is kept


# ---- refusals before anything starts ----

@pytest.mark.parametrize("kw, why", [
    ({"check": ""}, "test command"),
    ({"plan": "no waves here"}, "Wave N"),
    ({"profile": "huge"}, "slim or standard"),
])
def test_refused_before_a_worktree_is_made(env, kw, why):
    repo, cdir, tmp = env
    out = _start(repo, cdir, **kw)
    assert not out["ok"] and why in out["error"]
    assert not (tmp / "jobs").exists() or not [p for p in (tmp / "jobs").iterdir() if p.name != "checks"]


def test_switched_off_by_hand(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("ANCHOR_FOREMAN_CODE_JOBS", "0")
    assert "are off" in _start(repo, cdir)["error"]


def test_a_repository_with_its_own_foreman_config_is_refused(tmp_path, env):
    _, cdir, _ = env
    repo = _repo(tmp_path / "own", {"a.txt": "one\n", "foreman.config.json": "{}"})
    out = _start(repo, cdir)
    assert not out["ok"] and "its own foreman.config.json" in out["error"]


def test_anchors_own_code_is_refused_unless_unconfined_coders_are_allowed(env, monkeypatch):
    repo, cdir, _ = env
    import anchor_next
    monkeypatch.setattr(anchor_next, "is_served_repo", lambda path: True)
    monkeypatch.setenv("ANCHOR_SERVED_CODE_JOBS", "1")
    out = _start(repo, cdir)
    assert not out["ok"] and "cannot be confined" in out["error"]


# ---- never a skill job; the steward is told ----

def test_foreman_is_never_a_skill_job_and_crucible_keeps_its_hold(tmp_path, monkeypatch):
    root = tmp_path / "skills"
    for name in ("foreman", "crucible", "gandalf"):
        (root / name / "bin").mkdir(parents=True)
        (root / name / "bin" / "run.mjs").write_text("", encoding="utf-8")
    monkeypatch.setattr(skill_jobs, "skill_roots", lambda: [root])
    for hold in ("1", "0"):
        monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", hold)
        ok, why = skill_jobs.validate(["node", str(root / "foreman" / "bin" / "run.mjs")])
        assert not ok and "--worker foreman" in why
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")
    assert not skill_jobs.validate(["node", str(root / "crucible" / "bin" / "run.mjs")])[0]
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "0")
    assert skill_jobs.validate(["node", str(root / "crucible" / "bin" / "run.mjs")]) == (True, "")


def test_the_steward_sizes_the_work_and_starts_foreman_as_a_code_job(monkeypatch):
    import importlib
    import steward_cockpit.steward_engine as se
    monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
    se = importlib.reload(se)
    try:
        for text in (se.CONTRACT, se.EFFORT_DUTY, se.EFFORT_RULES):
            assert "SIZE THE WORK" in text and "--worker foreman" in text
        assert "Crucible is on hold" in se.SIZE_OR_HOLD and "run-live.mjs" not in se.SIZE_OR_HOLD
    finally:
        monkeypatch.delenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", raising=False)
        importlib.reload(se)


def test_the_authors_come_from_foremans_own_routing_line():
    line = "[10:00:00] model routing: execute=claude:x · review=gemini-cli:y · fix=chatgpt-cli:z\n"
    assert code_jobs.foreman_authors(line) == ["claude", "chatgpt"]
    assert code_jobs.foreman_authors("no routing here") == []
    assert code_jobs.foreman_authors("model routing: execute=mystery:x · fix=claude:y") == []
