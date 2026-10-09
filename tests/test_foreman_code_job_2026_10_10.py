"""Foreman as a code job's worker (John 2026-10-09: "route Foreman through the code-job path"). The final review of
the night of 2026-10-10 held Foreman because, started as a skill job, it wrote the project directly. Now it builds
inside the job's own worktree and its work goes through the code job's finish: the job's check, a review by a family
that wrote none of it, and the locked, verified landing. Foreman is never a skill job. Hermetic: a fake run-live.mjs
(tests/fake_foreman.mjs) and the fake reviewer (tests/fake_review.py); throwaway repositories only."""
import json
import os
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
        (root / name).parent.mkdir(parents=True, exist_ok=True)
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
    monkeypatch.setattr(code_jobs, "foreman_seat_family", lambda: "claude")       # the dashboard's Coder seat
    monkeypatch.setattr(code_jobs, "_routing_journal", lambda: tmp_path / "model-routing.jsonl")
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


def test_the_coder_seat_names_the_author_even_when_foremans_log_says_nothing(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "no-routing")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is True and job["authors"] == ["claude"], job["land_note"]


def test_a_failover_journaled_during_the_job_makes_that_family_an_author(env, monkeypatch):
    # fcj review r1 BLOCKER 1: a seat that failed over wrote too - the reviewer of that family may not pass it
    repo, cdir, tmp = env
    import datetime
    at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    (tmp / "model-routing.jsonl").write_text(json.dumps({"schema": "trio.model-routing.v1", "at": at,
                                                         "action": "failover", "from": "claude", "to": "chatgpt-cli"}) + "\n",
                                             encoding="utf-8")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["authors"] == ["chatgpt", "claude"]
    assert job["landed"] is False and "author's own family" in job["land_note"]


def test_an_unknown_family_anywhere_means_no_record_and_no_landing(env, monkeypatch):
    repo, cdir, tmp = env
    (tmp / "model-routing.jsonl").write_text(json.dumps({"action": "failover", "at": "9999", "to": "mystery"}) + "\n",
                                             encoding="utf-8")
    job = _wait(cdir, _start(repo, cdir)["job"])
    assert job["landed"] is False and "which model family wrote it" in job["land_note"]


def test_no_coder_seat_no_job(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setattr(code_jobs, "foreman_seat_family", lambda: "")
    assert "Coder seat cannot be read" in _start(repo, cdir)["error"]


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


@pytest.mark.skipif(sys.platform != "win32", reason="the pid re-check reads Windows process command lines")
def test_after_a_restart_stop_still_ends_foreman_by_its_rechecked_pid(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "sleep")
    out = _start(repo, cdir)
    wt = Path(out["worktree"])
    for _ in range(100):
        if (wt / ".foreman" / "started").exists():
            break
        time.sleep(0.1)
    proc = code_jobs._FOREMAN_PROCS.pop(out["job"])                 # the service restarted: the handle is gone
    job = code_jobs.read_jobs(str(cdir))[out["job"]]
    assert job["foreman_pid"] == proc.pid and code_jobs.foreman_left_running(job) == proc.pid
    assert code_jobs.foreman_left_running(dict(job, foreman_pid=os.getpid())) is None     # never another process
    assert code_jobs.stop(str(cdir), out["job"], actor="John")["ok"]
    proc.wait(timeout=30)
    assert proc.returncode is not None


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
    assert not out["ok"] and "tracks files a Foreman code job writes" in out["error"] and "foreman.config.json" in out["error"]


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


def test_the_authors_are_a_union_that_nothing_in_the_worktree_can_shrink(tmp_path, monkeypatch):
    monkeypatch.setattr(code_jobs, "foreman_seat_family", lambda: "claude")
    monkeypatch.setattr(code_jobs, "_routing_journal", lambda: tmp_path / "none.jsonl")
    job = {"foreman_family": "claude", "started_utc": "2026-10-09T00:00:00"}
    forged = "model routing: execute=claude:x · fix=claude:y\n: model routing: execute=grok-cli fix=grok-cli\n"
    assert code_jobs.foreman_authors(job, forged) == ["claude", "grok"]           # a later line only ADDS
    assert code_jobs.foreman_authors(job, "model routing: execute=mystery:x") == []
    assert code_jobs.foreman_authors(dict(job, foreman_family=""), "") == []


# ---- fcj review r1: one writer, byproducts, Anchor's own files ----

def test_what_the_check_makes_by_itself_is_never_foremans_work(env):
    # MAJOR 5: the check writes report.json in the untouched worktree; present at the end it refuses the landing
    repo, cdir, _ = env
    check = [sys.executable, "-c", "open('report.json','w').write('{}')"]
    job = _wait(cdir, _start(repo, cdir, check=check)["job"])
    assert job["check_byproducts"] == ["report.json"]
    assert job["landed"] is False and "report.json" in job["land_note"]
    assert "report.json" not in _tracked(repo)


def test_a_declared_byproduct_may_land(env):
    repo, cdir, _ = env
    check = [sys.executable, "-c", "open('report.json','w').write('{}')"]
    job = _wait(cdir, _start(repo, cdir, check=check, outputs=["report.json"])["job"])
    assert job["landed"] is True, job["land_note"]


def test_foremans_own_files_never_land_whatever_git_ignores():
    # MAJOR 4: never by the ignore rules alone
    for p in (".foreman-job/DESCRIPTION.md", ".foreman/run-record.json", "_foreman-status.log",
              "foreman-checkpoint.json", "FOREMAN.CONFIG.JSON", "sub/foreman.config.json"):
        assert code_jobs.never_lands(p), p
    assert not code_jobs.never_lands("src/foreman/x.py") and not code_jobs.never_lands("docs/.foreman-job.md")


def test_a_repository_tracking_a_foreman_job_folder_is_refused(tmp_path, env):
    _, cdir, _ = env
    repo = _repo(tmp_path / "own2", {"a.txt": "one\n", ".foreman-job/DESCRIPTION.md": "theirs"})
    out = _start(repo, cdir)
    assert not out["ok"] and ".foreman-job/DESCRIPTION.md" in out["error"]


def test_a_stop_during_the_check_means_foreman_never_launches(env, monkeypatch):
    # BLOCKER 2: Stop before the launch is honoured by the launch itself
    repo, cdir, tmp = env
    out = _start(repo, cdir, check=[sys.executable, "-c", "import time; time.sleep(3)"])
    assert code_jobs.stop(str(cdir), out["job"], actor="John")["ok"]
    for _ in range(100):
        if out["job"] not in code_jobs._FOREMAN_PROCS:
            break
        time.sleep(0.1)
    time.sleep(0.5)
    assert out["job"] not in code_jobs._FOREMAN_PROCS and not (tmp / "foreman.log").exists()
    assert code_jobs.read_jobs(str(cdir))[out["job"]]["status"] == "stopped"


def test_a_stop_that_cannot_see_foreman_end_keeps_the_repository(env, monkeypatch):
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "sleep")
    out = _start(repo, cdir)
    real = code_jobs.end_foreman
    monkeypatch.setattr(code_jobs, "end_foreman", lambda job, wait_s=60: (False, "Foreman did not end when asked"))
    res = code_jobs.stop(str(cdir), out["job"], actor="John")
    assert not res["ok"] and "did not end" in res["error"]
    assert code_jobs._norm(str(repo)) in code_jobs.busy_repos()                     # still the one writer
    assert code_jobs.read_jobs(str(cdir))[out["job"]]["status"] == "running"
    monkeypatch.setattr(code_jobs, "end_foreman", real)
    assert code_jobs.stop(str(cdir), out["job"], actor="John")["ok"]


@pytest.mark.skipif(sys.platform != "win32", reason="reads Windows process command lines")
def test_a_foreman_lost_to_a_restart_and_gone_is_marked_interrupted_and_frees_the_repository(env, monkeypatch):
    # BLOCKER 3
    repo, cdir, _ = env
    monkeypatch.setenv("FAKE_FOREMAN_MODE", "sleep")
    out = _start(repo, cdir)
    wt = Path(out["worktree"])
    for _ in range(200):
        if (wt / ".foreman" / "started").exists():
            break
        time.sleep(0.1)
    proc = code_jobs._FOREMAN_PROCS[out["job"]]
    code_jobs._FOREMAN_STOPPING.add(out["job"])           # its own thread must not finish it: we play the restart
    code_jobs._FOREMAN_PROCS.pop(out["job"])
    assert code_jobs._norm(str(repo)) in code_jobs.busy_repos()                     # alive: it keeps the repository
    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    proc.wait(timeout=30)
    code_jobs._ORPHAN_SEEN.clear()
    assert code_jobs._norm(str(repo)) not in code_jobs.busy_repos()
    job = code_jobs.read_jobs(str(cdir))[out["job"]]
    assert job["status"] == "failed" and "restarted" in job["error"] and job["kept_worktree"] == str(wt)


def test_the_job_runner_never_starts_foreman_whatever_the_hold(tmp_path, monkeypatch):
    # spec gap: the legacy build lane and a direct Foreman command refuse even with the hold lifted
    import job_runner
    for hold in ("1", "0"):
        monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", hold)
        with pytest.raises(ValueError, match="foreman-code-job-only"):
            job_runner.launch("build", cwd=str(tmp_path), prompt="x")
        with pytest.raises(ValueError, match="foreman-code-job-only"):
            job_runner.launch("general", cwd=str(tmp_path), command=["node", "C:/dev/trio/foreman/bin/run-live.mjs"])
    monkeypatch.setenv("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1")
    with pytest.raises(ValueError, match="foreman-crucible-hold"):
        job_runner.launch("plan", cwd=str(tmp_path), prompt="x")
