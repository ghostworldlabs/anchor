"""W1a of the night of 2026-10-08: "landed" and "live" are two places, and the lander can never write the running
Anchor (John's D1 that day: "work on a separate branch, isolated and then once done do a clean merge"; "Land on its own
is fine and does not go live until restart").

Every proof runs on a throwaway repository standing in for the running checkout (ANCHOR_SERVED_ROOT) - never
C:\\dev\\Anchor, never :8777."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import anchor_next  # noqa: E402
import git_safety  # noqa: E402
from steward_cockpit import code_jobs  # noqa: E402

PASS = [sys.executable, "-c", "pass"]


def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def served(tmp_path, monkeypatch):
    """A throwaway repository playing the running Anchor: a served page and a helper the service would load."""
    repo = tmp_path / "Anchor"
    repo.mkdir()
    for args in (["init", "-q", "-b", "master"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _g(repo, *args)
    (repo / "static").mkdir()
    (repo / "static" / "page.js").write_text("var build = 'one';\n", encoding="utf-8")
    (repo / "helper.py").write_text("WHO = 'one'\n", encoding="utf-8")
    (repo / "records.json").write_text("{}\n", encoding="utf-8")
    _g(repo, "add", "-A")
    _g(repo, "commit", "-q", "-m", "start")
    monkeypatch.setenv("ANCHOR_SERVED_ROOT", str(repo))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_SERVED_CODE_JOBS", "1")        # John's Decision 1, accepted for these proofs
    return repo


class _Coder:
    def __init__(self, wt, writes):
        self.wt, self.writes = wt, writes
        self.written_ok, self.on_turn_done, self.code_job, self.policy_override = [], None, None, None
        self.cli = "claude"

    def wake(self, fresh=False, seed=None):
        for name, text in self.writes.items():
            Path(self.wt, name).parent.mkdir(parents=True, exist_ok=True)
            Path(self.wt, name).write_text(text, encoding="utf-8")
            self.written_ok.append(str(Path(self.wt, name)))
        self.on_turn_done({"text": "done", "error": ""})
        return True, "awake"

    def stop(self):
        pass


def _run_job(tmp_path, monkeypatch, repo, writes, check=PASS, name="steward"):
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("claude", None))
    cdir = tmp_path / name
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(repo), "Change the page.", check, engine_factory=lambda wt: _Coder(wt, writes))
    assert out["ok"], out
    for _ in range(400):
        j = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            return j
        time.sleep(0.1)
    raise AssertionError(code_jobs.read_jobs(str(cdir)))


def test_the_running_checkout_is_never_a_landing_target(served):
    _g(served, "checkout", "-q", "-b", "job")
    (served / "helper.py").write_text("WHO = 'two'\n", encoding="utf-8")
    _g(served, "commit", "-qam", "job")
    cand = _g(served, "rev-parse", "HEAD")
    _g(served, "checkout", "-q", "master")
    ok, note = git_safety.land(str(served), cand, ["helper.py"], "a direct landing")
    assert ok is False and "is the running Anchor" in note and anchor_next.BRANCH in note
    assert (served / "helper.py").read_text(encoding="utf-8") == "WHO = 'one'\n"


def test_a_job_lands_on_anchor_next_and_the_running_tree_keeps_its_revision(tmp_path, monkeypatch, served):
    head = _g(served, "rev-parse", "HEAD")
    job = _run_job(tmp_path, monkeypatch, served, {"static/page.js": "var build = 'two';\n"})
    assert job["landed"] is True and job["land_to"], job.get("land_note")
    # the running checkout: same HEAD, same bytes - a page opened now and a helper launched now get the old revision
    assert _g(served, "rev-parse", "HEAD") == head
    assert (served / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'one';\n"
    out = subprocess.run([sys.executable, "-c", "import helper; print(helper.WHO)"], cwd=str(served), capture_output=True, text=True)
    assert out.stdout.strip() == "one"
    # anchor-next carries it, and it waits for a restart
    assert _g(served, "show", "anchor-next:static/page.js") == "var build = 'two';"
    assert [s for s, _ in anchor_next.waiting(served)] == [job["landed_commit"]]
    ip = Path(job["land_to"])
    assert ip.resolve() != served.resolve() and str(ip).startswith(str(tmp_path / "jobs"))


def test_the_restart_makes_it_live_and_brings_in_the_running_branchs_own_commits(tmp_path, monkeypatch, served):
    job = _run_job(tmp_path, monkeypatch, served, {"static/page.js": "var build = 'two';\n"})
    assert job["landed"] is True, job.get("land_note")
    (served / "records.json").write_text('{"checkpoint": 1}\n', encoding="utf-8")       # a steward's record checkpoint
    _g(served, "commit", "-qam", "steward checkpoint on sleep")
    pre = anchor_next.check(served)
    assert pre["ok"] and not pre["blockers"], pre
    r = anchor_next.activate(served)
    assert r["ok"], r
    assert (served / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'two';\n"
    assert (served / "records.json").read_text(encoding="utf-8") == '{"checkpoint": 1}\n'
    assert _g(served, "rev-parse", "HEAD") == _g(served, "rev-parse", "anchor-next")
    assert anchor_next.waiting(served) == []


def test_an_uncommitted_file_the_restart_would_overwrite_stops_it_before_any_change(tmp_path, monkeypatch, served):
    job = _run_job(tmp_path, monkeypatch, served, {"static/page.js": "var build = 'two';\n"})
    assert job["landed"] is True, job.get("land_note")
    (served / "static" / "page.js").write_text("var build = 'the Doctor was here';\n", encoding="utf-8")
    head = _g(served, "rev-parse", "HEAD")
    pre = anchor_next.check(served)
    assert pre["ok"] is False and pre["blockers"] == ["static/page.js"] and "would be overwritten" in pre["why"]
    r = anchor_next.activate(served)
    assert r["ok"] is False and r["blockers"] == ["static/page.js"]
    assert _g(served, "rev-parse", "HEAD") == head
    assert (served / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'the Doctor was here';\n"


def test_a_conflict_between_the_branches_stops_the_restart_before_any_change(tmp_path, monkeypatch, served):
    job = _run_job(tmp_path, monkeypatch, served, {"helper.py": "WHO = 'two'\n"})
    assert job["landed"] is True, job.get("land_note")
    (served / "helper.py").write_text("WHO = 'committed by hand'\n", encoding="utf-8")
    _g(served, "commit", "-qam", "a hand commit")
    head = _g(served, "rev-parse", "HEAD")
    r = anchor_next.activate(served)
    assert r["ok"] is False and "helper.py" in " ".join(r["conflicts"]) and "conflict" in r["why"]
    assert _g(served, "rev-parse", "HEAD") == head and (served / "helper.py").read_text(encoding="utf-8") == "WHO = 'committed by hand'\n"


def test_every_landing_needs_an_explicit_passing_check(tmp_path, monkeypatch, served):
    job = _run_job(tmp_path, monkeypatch, served, {"static/page.js": "var build = 'two';\n"}, check="", name="nocheck")
    assert job["landed"] is False and "no check was given" in job["land_note"] and job["kept_worktree"]
    job = _run_job(tmp_path, monkeypatch, served, {"static/page.js": "var build = 'three';\n"},
                   check=[sys.executable, "-c", "raise SystemExit(4)"], name="badcheck")
    assert job["landed"] is False and "check failed" in job["land_note"]
    assert not anchor_next.waiting(served)


def test_one_lock_for_every_checkout_of_a_repository(tmp_path, monkeypatch, served):
    ip, why = anchor_next.ensure_integration(served)
    assert ip is not None, why
    assert git_safety._lock_path(str(served)) == git_safety._lock_path(str(ip))
    with git_safety.repo_lock(str(served), wait_s=0) as held:
        assert held
        with git_safety.repo_lock(str(ip), wait_s=0) as again:
            assert again is False                      # the lander's checkout waits on the running checkout's lock


def test_the_landers_checkout_written_by_someone_else_is_refused_never_cleaned(tmp_path, monkeypatch, served):
    ip, _ = anchor_next.ensure_integration(served)
    (Path(ip) / "helper.py").write_text("WHO = 'stray'\n", encoding="utf-8")
    again, why = anchor_next.ensure_integration(served)
    assert again is None and "nobody committed" in why
    assert (Path(ip) / "helper.py").read_text(encoding="utf-8") == "WHO = 'stray'\n"


def test_a_steward_inside_the_running_anchor_cannot_write_code_there():
    from steward_cockpit import steward_engine as se
    assert "Edit(./**/*.py)" in se.SERVED_CODE_DENY and "Edit(./**/*.js)" in se.SERVED_CODE_DENY
    assert "Edit(./**/*.css)" in se.SERVED_CODE_DENY
    assert se._in_served(str(se._SERVED / "Setup and Mother Ship")) and not se._in_served(str(ROOT.parent / "elsewhere"))
    src = (ROOT / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    assert '"plan" if read_only else ("fenced" if fenced else self.permission_mode)' in src
    assert '*(SERVED_CODE_DENY if (fenced and in_served) else ())' in src


def test_the_restart_script_checks_before_it_stops_and_activates_only_a_stopped_service():
    ps = (ROOT / "restart_anchor.ps1").read_text(encoding="utf-8")
    order = [ps.index('"anchor_next.py" check'), ps.index('tools\\pre_restart_drain.py'), ps.index("& $Nssm stop anchor"),
             ps.index('"anchor_next.py" activate'), ps.index("& $Nssm start anchor")]
    assert order == sorted(order)
    assert "RESTART STOPPED BEFORE ANY CHANGE" in ps and "reset --hard" not in ps


# ---------- ChatGPT review round 1 ----------

def test_the_running_checkout_is_the_main_worktree_wherever_this_is_imported_from(monkeypatch):
    monkeypatch.delenv("ANCHOR_SERVED_ROOT", raising=False)
    main = subprocess.run(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"], capture_output=True, text=True).stdout.splitlines()[0][len("worktree "):]
    assert anchor_next._norm(anchor_next.served_root()) == anchor_next._norm(main)
    assert not anchor_next.is_served_checkout(str(ROOT)) or anchor_next._norm(ROOT) == anchor_next._norm(main)


def test_an_ignored_local_file_or_a_folder_in_the_way_blocks_the_activation(tmp_path, monkeypatch, served):
    (served / ".gitignore").write_text("local.cfg\n", encoding="utf-8")
    _g(served, "add", ".gitignore")
    _g(served, "commit", "-qm", "ignore")
    ip, _ = anchor_next.ensure_integration(served)
    (Path(ip) / "local.cfg").write_text("shipped\n", encoding="utf-8")
    (Path(ip) / "assets").write_text("a file\n", encoding="utf-8")
    _g(ip, "add", "-f", "local.cfg", "assets")
    _g(ip, "commit", "-qm", "adds a tracked local.cfg and a file named assets")
    (served / "local.cfg").write_text("John's own settings\n", encoding="utf-8")       # ignored, local
    (served / "assets").mkdir()
    (served / "assets" / "mine.txt").write_text("untracked\n", encoding="utf-8")      # a folder where a file comes
    pre = anchor_next.check(served)
    assert pre["ok"] is False and set(pre["blockers"]) == {"local.cfg", "assets"}, pre
    r = anchor_next.activate(served)
    assert r["ok"] is False and (served / "local.cfg").read_text(encoding="utf-8") == "John's own settings\n"


def test_a_refused_fast_forward_is_restored_and_verified(tmp_path, monkeypatch, served):
    job = _run_job(tmp_path, monkeypatch, served, {"static/page.js": "var build = 'two';\n"})
    assert job["landed"] is True, job.get("land_note")
    head = _g(served, "rev-parse", "HEAD")
    gitdir = Path(_g(served, "rev-parse", "--absolute-git-dir"))
    lock = gitdir / "refs" / "heads" / "master.lock"
    lock.write_text("held\n", encoding="utf-8")                  # git checks out, then cannot move the branch
    try:
        r = anchor_next.activate(served)
    finally:
        lock.unlink()
    assert r["ok"] is False and r["unverified"] == [] and "restored and verified" in r["why"], r
    assert _g(served, "rev-parse", "HEAD") == head
    assert (served / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'one';\n"
    assert _g(served, "status", "--porcelain") == ""


def test_a_kept_jobs_rows_are_never_announced_one_by_one(tmp_path, monkeypatch):
    """ChatGPT W1a r2: the generic publisher never announces a kept code job's rows - its one line does (atomic: no
    window between a registration and a suppression)."""
    from steward_cockpit import steward_engine as se
    import deliverables_register as dr
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "ECGBERHT.md").write_text("# cockpit\n", encoding="utf-8")
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", ""))
    se.receipt_baseline(str(eff))
    (eff / "code-job-outputs").mkdir()
    for n in ("a.pdf", "b.pdf"):
        (eff / "code-job-outputs" / n).write_bytes(b"%PDF-1.4")
        assert dr.register(eff, "Code job J1 kept (not landed): " + n, "`code-job-outputs/%s`" % n, notify=False)["written"]
    lines = []
    se.publish_delivery_receipts(str(eff), record=lambda line, rid: lines.append(line), emit=None)
    assert lines == []


# ---------- ChatGPT review round 2 ----------

def test_recovery_restores_only_what_the_activation_wrote(tmp_path, monkeypatch, served):
    """A save made by someone else to an incoming file between the check and the fast-forward is KEPT, and the
    refusal is unverified (the service is not started)."""
    job = _run_job(tmp_path, monkeypatch, served, {"static/page.js": "var build = 'two';\n"})
    assert job["landed"] is True, job.get("land_note")
    head = _g(served, "rev-parse", "HEAD")
    real_check = anchor_next.check

    def check_then_save(root=None):
        out = real_check(root)
        (served / "static" / "page.js").write_text("var build = 'his save';\n", encoding="utf-8")   # after the check
        return out
    monkeypatch.setattr(anchor_next, "check", check_then_save)
    r = anchor_next.activate(served)
    assert r["ok"] is False and r["unverified"], r
    assert (served / "static" / "page.js").read_text(encoding="utf-8") == "var build = 'his save';\n"
    assert _g(served, "rev-parse", "HEAD") == head


def test_recovery_reads_file_names_literally(tmp_path, monkeypatch, served):
    (served / "a1.txt").write_text("tracked\n", encoding="utf-8")
    (served / "a[1].txt").write_text("tracked too\n", encoding="utf-8")
    _g(served, "add", "-A")
    _g(served, "commit", "-qm", "two names a pattern could confuse")
    ip, _ = anchor_next.ensure_integration(served)
    (Path(ip) / "a[1].txt").write_text("next\n", encoding="utf-8")
    _g(ip, "commit", "-qam", "changes a[1].txt only")
    (served / "a1.txt").write_text("his local edit\n", encoding="utf-8")       # dirty, but not incoming
    lock = Path(_g(served, "rev-parse", "--absolute-git-dir")) / "refs" / "heads" / "master.lock"
    lock.write_text("held\n", encoding="utf-8")
    try:
        r = anchor_next.activate(served)
    finally:
        lock.unlink()
    assert r["ok"] is False and r["unverified"] == [], r
    assert (served / "a1.txt").read_text(encoding="utf-8") == "his local edit\n"
    assert (served / "a[1].txt").read_text(encoding="utf-8") == "tracked too\n"


def test_the_restart_starts_only_on_success_or_a_verified_refusal():
    ps = (ROOT / "restart_anchor.ps1").read_text(encoding="utf-8")
    assert "if ($act -ne 0 -and $act -ne 3) {" in ps and "SERVICE LEFT STOPPED" in ps


@pytest.mark.parametrize("who,cmd,refused", [
    ("steward", "git diff --stat", False), ("steward", "git diff --output=C:/dev/Anchor/static/x.js", True),
    ("steward", 'git diff "--output=x"', True), ("steward", "git diff $'--output=x'", True),
    ("steward", "git status > C:/dev/Anchor/a.py", True), ("steward", "git log -c core.pager=x", True),
    ("steward", 'python C:/dev/Anchor/tools/steward_code_job.py start --repo C:/dev/Anchor --brief "fix a; b > c"', False),
    ("steward", 'python C:/dev/Anchor/tools/steward_code_job.py start --brief "$(rm -rf x)"', True),
    ("steward", "rm -rf C:/dev/Anchor", True), ("steward", "git diff a\\b", True),
    ("coder", "pytest -q tests/test_a.py", False), ("coder", "cp x C:/dev/Anchor/static/a.js", True),
    ("coder", "cd /c/dev/Anchor && ls", True), ("coder", "cd ../../../../dev && ls", True),
])
def test_the_fence_guard_grammar(who, cmd, refused, tmp_path):
    env = dict(os.environ, **({"ANCHOR_FENCE_SHELL": "1"} if who == "steward" else
                              {"ANCHOR_FENCE_ROOT": str(tmp_path), "ANCHOR_FENCE_SERVED": "C:/dev/Anchor"}))
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "fence_guard.py")],
                       input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}), capture_output=True, text=True, env=env)
    assert (r.returncode == 2) is refused, (cmd, r.returncode, r.stderr)


def test_a_chatgpt_coder_is_not_given_the_running_anchors_code(tmp_path, monkeypatch, served):
    monkeypatch.setattr(code_jobs, "choose_coder", lambda requested="": ("chatgpt", None))
    cdir = tmp_path / "s"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(served), "x", PASS, engine_factory=lambda wt: _Coder(wt, {}))
    assert out["ok"] is False and "Claude coder" in out["error"]


def test_declared_outputs_are_normalized_and_one_the_check_made_lands(tmp_path, monkeypatch):
    assert code_jobs.declared_outputs(["./out//report.pdf", "out/report.pdf"]) == (["out/report.pdf"], None)
    assert code_jobs.declared_outputs(["out/../../x"])[0] is None



# ---------- ChatGPT review round 3 ----------

def test_a_declared_output_is_validated_after_normalizing():
    for bad in ("roadmap.json/.", "./strip.json", "x/../roadmap.json", ".ecgberht/./state.json"):
        assert code_jobs.declared_outputs([bad])[0] is None, bad


def test_every_coder_launch_on_the_running_anchors_repository_is_claudes(monkeypatch, served):
    from steward_cockpit import steward_engine as se
    monkeypatch.delenv("ANCHOR_UNCONFINED_CODERS", raising=False)
    assert se._unconfined_ok({"repo": str(served)}) is False
    assert se._unconfined_ok({"repo": ""}) is False, "unknown counts as the running Anchor's"
    monkeypatch.setenv("ANCHOR_UNCONFINED_CODERS", "1")
    assert se._unconfined_ok({"repo": str(served)}) is True
    src = (ROOT / "steward_cockpit" / "steward_engine.py").read_text(encoding="utf-8")
    assert 'if self.code_job is not None and self.cli != "claude" and not _unconfined_ok(self.code_job):' in src



def test_code_jobs_on_the_running_anchor_are_off_until_john_turns_them_on(tmp_path, monkeypatch, served):
    monkeypatch.delenv("ANCHOR_SERVED_CODE_JOBS", raising=False)
    cdir = tmp_path / "off"
    cdir.mkdir()
    out = code_jobs.start(str(cdir), str(served), "x", PASS, engine_factory=lambda wt: _Coder(wt, {}))
    assert out["ok"] is False and "ANCHOR_SERVED_CODE_JOBS=1" in out["error"]
