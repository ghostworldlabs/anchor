"""W3 of the night of 2026-10-08 (John that day: "I want it to diagnose, resolve health issues and have the banner go
down once that is done"): the banner tells the truth.

Two states never mixed: red stays while the RUNNING revision's newest report fails; a fix landed on anchor-next and
checked at its own revision on a private port says "fix verified, live after your restart" without clearing it; after
the restart one re-check of the running code is owed and only its pass clears it. One report store; the live probe
counts an error status as a failure; the health check never kills the running service; the Doctor's code repair is
off. Every proof runs on throwaway repositories and data folders - never C:\\dev\\Anchor, never :8777."""
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import anchor_next  # noqa: E402
import health_state as hs  # noqa: E402

RED = "# Anchor Health Report\n\nStatus: ISSUES FOUND\nTarget: running\nRevision: x\n\n## Issues\n- [server] /api/status 500\n"
GREEN = "# Anchor Health Report\n\nStatus: OK\nTarget: running\nRevision: y\n\n## Warnings\n(none)\n"
STUB_CHECK = """import os, pathlib, subprocess
rev = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
pathlib.Path(os.environ["ANCHOR_HEALTH_REPORT_OUT"]).write_text(
    "# Anchor Health Report\\n\\nStatus: OK\\nTarget: " + os.environ.get("ANCHOR_HEALTHCHECK_TARGET", "") + "\\nRevision: " + rev
    + "\\nData: " + os.environ.get("ANCHOR_DATA_DIR", "") + "\\nCwd: " + os.getcwd() + "\\n", encoding="utf-8")
"""


def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def world(tmp_path, monkeypatch):
    served = tmp_path / "Anchor"
    served.mkdir()
    for args in (["init", "-q", "-b", "master"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        _g(served, *args)
    (served / "server.py").write_text("BROKEN = True\n", encoding="utf-8")
    (served / "anchor_healthcheck.py").write_text(STUB_CHECK, encoding="utf-8")
    _g(served, "add", "-A")
    _g(served, "commit", "-q", "-m", "start")
    data = tmp_path / "data"
    (data / "health_reports").mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_SERVED_ROOT", str(served))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_RUNNING_HEAD", _g(served, "rev-parse", "HEAD"))
    monkeypatch.setenv("ANCHOR_STARTED_AT", str(time.time() - 3600))
    return served, data / "health_reports"


def _report(reports, name, body, age_s=0):
    p = reports / name
    p.write_text(body, encoding="utf-8")
    t = time.time() - age_s
    os.utime(str(p), (t, t))
    return p


def _land_fix(served):
    ip, why = anchor_next.ensure_integration(served)
    assert ip is not None, why
    (Path(ip) / "server.py").write_text("BROKEN = False\n", encoding="utf-8")
    _g(ip, "commit", "-qam", "the fix")
    return _g(ip, "rev-parse", "HEAD")


def test_only_dated_reports_count_and_one_reading_classifies_them(world):
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=60)
    _report(reports, "README.md", GREEN)
    _report(reports, "soak-2026-10-09.md", GREEN)
    _report(reports, "candidate-abc.md", GREEN)
    path, body = hs.latest()
    assert path.name == "2026-10-08.md" and hs.status_of(body) == "red"
    assert hs.status_of(GREEN) == "green" and hs.status_of("Status: OK\n\n## Warnings\n- slow home page\n") == "yellow"
    assert hs.status_of("nonsense") == "unknown"


def test_red_stays_until_the_running_code_passes_and_a_verified_fix_says_so(world):
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=120)
    assert hs.banner()["why"].endswith("Doctor can diagnose it")
    rev = _land_fix(served)
    rec = hs.check_candidate()                      # its own worktree, a private port, the stub check
    assert rec["status"] == "green" and rec["revision"] == rev and rec["target"] == "candidate", rec
    assert hs.read_candidate()["revision"] == rev
    assert not list((served.parent / "jobs").glob("candidate-*")), "the throwaway worktree is gone"
    assert _g(served, "rev-parse", "HEAD") != rev and (served / "server.py").read_text(encoding="utf-8") == "BROKEN = True\n"
    b = hs.banner()
    assert b is not None and b["status"] == "red", "a candidate pass never clears the banner"
    assert "fix verified on %s, live after your restart" % rev[:10] in b["why"]
    assert not hs.recheck_needed()
    # the restart: the running checkout takes anchor-next and the service starts again on it
    assert anchor_next.activate(served)["ok"]
    os.environ["ANCHOR_RUNNING_HEAD"] = _g(served, "rev-parse", "HEAD")
    os.environ["ANCHOR_STARTED_AT"] = str(time.time())
    b = hs.banner()
    assert b is not None and "verified" not in b["why"], "after the restart only a re-check of the running code counts"
    assert hs.recheck_needed()
    _report(reports, "2026-10-08.md", GREEN + "Service-Boot: %s\n" % os.environ["ANCHOR_STARTED_AT"])   # THIS instance's pass
    assert hs.banner() is None and not hs.recheck_needed()


def test_a_stale_candidate_is_ignored(world):
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=120)
    _land_fix(served)
    hs.check_candidate()
    ip, _ = anchor_next.ensure_integration(served)
    (Path(ip) / "other.py").write_text("x = 1\n", encoding="utf-8")
    _g(ip, "add", "-A")
    _g(ip, "commit", "-qm", "anchor-next moved")
    assert "verified" not in hs.banner()["why"], "a pass for an older revision is stale"


def test_a_newer_report_outranks_an_older_candidate(world):
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=120)
    _land_fix(served)
    hs.check_candidate()
    time.sleep(0.05)
    _report(reports, "2026-10-08.md", RED)          # a re-run after the candidate, still red
    assert "verified" not in hs.banner()["why"]


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        code = int(self.path.strip("/") or 200)
        self.send_response(code)
        self.end_headers()

    def log_message(self, *a):
        pass


def test_the_live_probe_counts_an_error_status_as_a_failure(monkeypatch):
    import anchor_gui
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANCHOR_PORT", str(srv.server_address[1]))
        assert anchor_gui._doctor_live_probe("/200")["ok"] is True
        for code in ("401", "404", "500"):
            r = anchor_gui._doctor_live_probe("/" + code)
            assert r["ok"] is False and r["code"] == int(code), r
    finally:
        srv.shutdown()


def test_the_health_check_never_kills_the_running_service(monkeypatch):
    import anchor_healthcheck as hc
    netstat = ("  TCP    0.0.0.0:8777     0.0.0.0:0   LISTENING   4242\n"
               "  TCP    0.0.0.0:%d     0.0.0.0:0   LISTENING   5151\n"
               "  TCP    127.0.0.1:51515  127.0.0.1:8778  ESTABLISHED   4242\n") % hc.TEST_PORT
    killed = []

    def fake_run(argv, **kw):
        if argv[0] == "taskkill":
            killed.append(int(argv[-1]))
        class R:
            stdout = "2026-01-01T00:00:00"
        return R()
    monkeypatch.setattr(hc.sys, "platform", "win32")
    monkeypatch.setattr(hc.subprocess, "check_output", lambda *a, **k: netstat)
    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    monkeypatch.delenv("ANCHOR_HEALTHCHECK_KILL_STALE_SERVICE", raising=False)
    hc.cleanup_stale_processes(hc.Report())
    assert killed == [5151], "only the test port's listener; never 8777 (pid 4242), never by a substring match"


def test_a_report_names_its_target_and_revision(tmp_path):
    import anchor_healthcheck as hc
    out = tmp_path / "r.md"
    hc.Report().write(out)
    text = out.read_text(encoding="utf-8")
    assert "\nTarget: running\n" in text and "\nRevision: " in text


def test_the_doctors_code_repair_is_off(monkeypatch):
    import anchor_gui
    sent = []

    class H:
        def _send_json(self, obj, code=200):
            sent.append((code, obj))
    monkeypatch.setattr(anchor_gui._aset, "get_launch_settings",
                        lambda: {"default_cli": "claude", "coding_family": "claude", "review_family": "chatgpt", "settings_revision": 1})
    monkeypatch.setattr(anchor_gui, "_w8_shared_session_start_plan", lambda **k: {"engine": "claude"})
    anchor_gui.handle_doctor_session_start(H(), "/api/doctor/session_start", {"resolve": True, "issue": {"message": "x"}})
    assert sent and sent[0][0] == 409 and sent[0][1]["status"] == "repair_off"
    src = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert "resolve: true" not in src.split("_DOCTOR_PAGE_TEMPLATE", 1)[1], "the Doctor page never asks for a write session"



# ---------- ChatGPT review round 1 ----------

def test_a_candidate_runs_on_its_own_throwaway_data_and_leaves_nothing(world):
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=120)
    _land_fix(served)
    rec = hs.check_candidate()
    assert rec["status"] == "green", rec
    body = (reports / rec["report"]).read_text(encoding="utf-8")
    data, cwd = hs.field(body, "Data"), hs.field(body, "Cwd")
    assert data and os.path.normcase(os.path.realpath(data)) == os.path.normcase(os.path.realpath(cwd)), "its data folder is its own worktree"
    assert os.path.normcase(str(reports.parent)) not in os.path.normcase(data), "never the live data folder"
    assert not os.path.exists(cwd), "the throwaway worktree is gone"
    assert "wt" not in _g(served, "worktree", "list")


def test_a_candidate_report_must_be_this_runs_and_this_revisions(world, monkeypatch):
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=120)
    rev = _land_fix(served)
    ip, _ = anchor_next.ensure_integration(served)
    (Path(ip) / "anchor_healthcheck.py").write_text(
        "import os, pathlib\npathlib.Path(os.environ['ANCHOR_HEALTH_REPORT_OUT']).write_text("
        "'Status: OK\\nTarget: candidate\\nRevision: 0000000\\n', encoding='utf-8')\n", encoding="utf-8")
    _g(ip, "commit", "-qam", "a check that reports another revision")
    rec = hs.check_candidate()
    assert rec["status"] == "unknown" and "not this candidate" in rec["why"], rec
    assert "verified" not in hs.banner()["why"]


def test_the_owed_recheck_starts_from_the_server_start_once_and_only_after_it_launched(world, monkeypatch):
    import anchor_gui
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=120)
    _land_fix(served)
    hs.check_candidate()
    assert anchor_next.activate(served)["ok"]
    monkeypatch.setenv("ANCHOR_RUNNING_HEAD", _g(served, "rev-parse", "HEAD"))
    monkeypatch.setenv("ANCHOR_STARTED_AT", str(time.time()))
    assert hs.recheck_needed()
    src = (ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    body = src[src.index("def latest_health_report"):src.index("def ", src.index("def latest_health_report") + 10)]
    assert "_health_recheck_if_owed" not in body, "rendering never starts a check"
    launches = []
    monkeypatch.setattr(anchor_gui, "_doctor_start_healthcheck_run", lambda: launches.append(1) or {"ok": False, "error": "no log"})
    anchor_gui._health_recheck_if_owed()
    assert launches == [1] and hs.recheck_needed(), "a failed launch does not use up the owed re-check"
    monkeypatch.setattr(anchor_gui, "_doctor_start_healthcheck_run", lambda: launches.append(2) or {"ok": True})
    anchor_gui._health_recheck_if_owed()
    anchor_gui._health_recheck_if_owed()
    assert launches == [1, 2] and not hs.recheck_needed(), "owed once, durably"
    monkeypatch.setenv("ANCHOR_HEALTHCHECK", "1")
    hs_c = hs.read_candidate(); hs_c.pop("rechecked_for"); hs.write_candidate(hs_c)
    anchor_gui._health_recheck_if_owed()
    assert launches == [1, 2], "never inside a health check's own processes"


def test_8777_is_never_a_test_port(monkeypatch):
    import anchor_healthcheck as hc
    netstat = "  TCP    0.0.0.0:8777     0.0.0.0:0   LISTENING   4242\n"
    killed = []
    monkeypatch.setattr(hc, "TEST_PORT", 8777)
    monkeypatch.setattr(hc.sys, "platform", "win32")
    monkeypatch.setattr(hc.subprocess, "check_output", lambda *a, **k: netstat)
    monkeypatch.setattr(hc.subprocess, "run", lambda argv, **k: killed.append(argv) or type("R", (), {"stdout": "2026-01-01T00:00:00"})())
    monkeypatch.delenv("ANCHOR_HEALTHCHECK_KILL_STALE_SERVICE", raising=False)
    hc.cleanup_stale_processes(hc.Report())
    assert not [a for a in killed if a[0] == "taskkill"]
    monkeypatch.setattr(hc, "TARGET", "candidate")
    monkeypatch.setenv("ANCHOR_HEALTHCHECK_KILL_STALE_SERVICE", "1")
    hc.cleanup_stale_processes(hc.Report())
    assert not [a for a in killed if a[0] == "taskkill"], "a candidate check never runs the killer"


class _Version(http.server.BaseHTTPRequestHandler):
    build = "abc1234+ff"

    def do_GET(self):
        body = json.dumps({"version": self.build}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_a_running_pass_needs_the_running_service_on_the_checked_code(monkeypatch):
    """The served SOURCES' fingerprint decides (ChatGPT hardening): a steward's record checkpoint moves HEAD without
    changing the code - still a pass; different code running - a failure; nothing running - a failure."""
    import anchor_healthcheck as hc

    def server(build):
        h = type("V", (_Version,), {"build": build})
        s = http.server.HTTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        return s
    running, checked = server("aaaaaaa+fp1"), server("bbbbbbb+fp1")      # another commit, the same code
    try:
        monkeypatch.setenv("ANCHOR_HEALTHCHECK_LIVE_PORT", str(running.server_address[1]))
        monkeypatch.setattr(hc, "TEST_PORT", checked.server_address[1])
        monkeypatch.setattr(hc, "_previous_issue_paths", lambda: [])
        r = hc.Report()
        hc.check_running_service(r)
        assert any(c[0] == "the running service runs the checked code" and c[1] for c in r.checks), r.checks
        checked.RequestHandlerClass.build = "bbbbbbb+fp2"                 # different code
        r = hc.Report()
        hc.check_running_service(r)
        assert any(c[0] == "the running service runs the checked code" and not c[1] for c in r.checks)
        monkeypatch.setenv("ANCHOR_HEALTHCHECK_LIVE_PORT", "1")
        r = hc.Report()
        hc.check_running_service(r)
        assert r.has_issues, "no running service, no pass"
    finally:
        running.shutdown()
        checked.shutdown()


class _Service(http.server.BaseHTTPRequestHandler):
    build = "abc1234+ff"
    broken = "/api/status"

    def do_GET(self):
        if self.path == "/api/version":
            body = json.dumps({"version": self.build}).encode()
            self.send_response(200)
        elif self.path.startswith("/api/") and not self.headers.get("Authorization"):
            body = b"no"                                   # a protected read, asked without the service's token
            self.send_response(401)
        elif self.path.split("?")[0] == self.broken:
            body = b"boom"
            self.send_response(500)
        else:
            body = b"ok"
            self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_the_running_service_must_answer_its_own_pages_not_only_its_version(monkeypatch):
    import anchor_healthcheck as hc
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Service)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANCHOR_HEALTHCHECK_LIVE_PORT", str(srv.server_address[1]))
        monkeypatch.setenv("ANCHOR_TOKEN", "t")
        monkeypatch.setattr(hc, "RUN_REVISION", "abc1234def")
        r = hc.Report()
        hc.check_running_service(r)
        assert r.has_issues and any("GET /api/status" in c[0] and not c[1] for c in r.checks), r.checks
        _Service.broken = "/nothing"
        r = hc.Report()
        hc.check_running_service(r)
        assert not r.has_issues, r.checks
    finally:
        _Service.broken = "/api/status"
        srv.shutdown()


def test_an_older_run_never_overwrites_a_newer_runs_report(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    today = tmp_path / ("%s.md" % hc.TODAY)
    today.write_text("Status: OK\nRun: %.3f\n" % (time.time() + 100), encoding="utf-8")
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % time.time())
    assert hc._newer_run_published(today) is True
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % (time.time() + 200))
    assert hc._newer_run_published(today) is False


def test_a_failed_recheck_launch_is_tried_again_and_the_obligation_is_per_candidate(world, monkeypatch):
    import anchor_gui
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=120)
    _land_fix(served)
    hs.check_candidate()
    assert anchor_next.activate(served)["ok"]
    monkeypatch.setenv("ANCHOR_RUNNING_HEAD", _g(served, "rev-parse", "HEAD"))
    monkeypatch.setenv("ANCHOR_STARTED_AT", str(time.time()))
    scheduled = []
    monkeypatch.setattr(anchor_gui, "_schedule_health_recheck", lambda delay_s=90: scheduled.append(delay_s))
    monkeypatch.setattr(anchor_gui, "_RECHECK_TRIES", [0])
    monkeypatch.setattr(anchor_gui, "_doctor_start_healthcheck_run", lambda: {"ok": False, "error": "no log"})
    anchor_gui._health_recheck_if_owed()
    assert scheduled == [120] and hs.recheck_needed(), "tried again later"
    monkeypatch.setattr(anchor_gui, "_doctor_start_healthcheck_run", lambda: {"ok": True})
    anchor_gui._health_recheck_if_owed()
    assert not hs.recheck_needed()
    ip, _ = anchor_next.ensure_integration(served)
    (Path(ip) / "later.py").write_text("x = 1\n", encoding="utf-8")
    _g(ip, "add", "-A")
    _g(ip, "commit", "-qm", "a later landing")
    anchor_next.activate(served)
    monkeypatch.setenv("ANCHOR_RUNNING_HEAD", _g(served, "rev-parse", "HEAD"))
    assert not hs.recheck_needed(), "a later restart does not revive a consumed candidate's obligation"


def test_the_cave_acknowledges_only_the_fingerprint_a_placed_request_carried():
    js = (ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    assert "if (h && h !== healthSig) { healthPending = h; renewInPlace(); }" in js
    assert "var sig = healthPending;   // the fingerprint THIS request will place" in js
    assert "if (sig) { healthSig = sig; if (healthPending === sig) healthPending = ''; }" in js
    assert "if (placeAgain || (healthPending" not in js, "a failed repaint waits for the next poll, never loops"


# ---------- ChatGPT review round 3 ----------

def test_a_run_without_the_services_token_never_passes_while_issues_are_open(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Service)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("ANCHOR_HEALTHCHECK_LIVE_PORT", str(srv.server_address[1]))
        monkeypatch.setattr(hc, "RUN_REVISION", "abc1234def")
        monkeypatch.setattr(hc, "REPORTS_DIR", tmp_path)
        (tmp_path / "2026-10-07.md").write_text("Status: ISSUES FOUND\n\n## Issues\n- [HTTP endpoints] GET /api/status: 500\n- [x] GET /a GET /b GET /c GET /d GET /e GET /f GET /g GET /h GET /i\n", encoding="utf-8")
        assert len(hc._previous_issue_paths()) == 10, "every affected target, no cap"
        monkeypatch.setattr(hc, "_TOKEN_MINTED", True)       # the daily task: the throwaway's token is never used live
        r = hc.Report()
        hc.check_running_service(r)
        assert r.has_issues and any("not verifiable without the service's token" in c[2] for c in r.checks)
        monkeypatch.setattr(hc, "_TOKEN_MINTED", False)
        monkeypatch.setenv("ANCHOR_TOKEN", "the-service-token")
        _Service.broken = "/i"                                 # the ninth/tenth affected endpoint still fails
        r = hc.Report()
        hc.check_running_service(r)
        assert r.has_issues and any(c[0].endswith("GET /i") and not c[1] for c in r.checks)
    finally:
        _Service.broken = "/api/status"
        srv.shutdown()


def test_publication_is_one_locked_step_and_an_older_run_never_overwrites(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    path = tmp_path / ("%s.md" % hc.TODAY)
    newer_id = "%.3f" % (time.time() + 100)
    monkeypatch.setattr(hc, "RUN_ID", newer_id)
    hc._publish(hc.Report(), path)
    assert ("\nRun: %s\n" % newer_id) in path.read_text(encoding="utf-8")
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % time.time())     # an OLDER run finishing later
    hc._publish(hc.Report(), path)
    assert ("\nRun: %s\n" % newer_id) in path.read_text(encoding="utf-8"), "the newer run's report stands"
    assert list(tmp_path.glob("superseded-*.md")), "kept beside it, never over it"
    assert not (tmp_path / ".publish.lock").exists()



# ---------- the hardening round ----------

def test_a_pass_from_an_earlier_service_instance_does_not_cancel_the_owed_recheck(world, monkeypatch):
    served, reports = world
    _report(reports, "2026-10-08.md", RED, age_s=120)
    _land_fix(served)
    hs.check_candidate()
    assert anchor_next.activate(served)["ok"]
    monkeypatch.setenv("ANCHOR_RUNNING_HEAD", _g(served, "rev-parse", "HEAD"))
    monkeypatch.setenv("ANCHOR_STARTED_AT", "2000.0")                  # this instance
    _report(reports, "2026-10-08.md", GREEN + "Service-Boot: 1000.0\n")   # a pass of the instance BEFORE the restart
    assert hs.recheck_needed(), "only this instance's own pass counts"
    _report(reports, "2026-10-08.md", GREEN + "Service-Boot: 2000.0\n")
    assert not hs.recheck_needed()


def test_without_its_lock_a_run_never_publishes_the_report(tmp_path, monkeypatch):
    import anchor_healthcheck as hc
    path = tmp_path / ("%s.md" % hc.TODAY)
    path.write_text("Status: ISSUES FOUND\n", encoding="utf-8")
    (tmp_path / ".publish.lock").write_text("held", encoding="utf-8")      # a fresh lock another run holds
    monkeypatch.setattr(hc.time, "sleep", lambda s: None)
    real_time = hc.time.time
    clock = [real_time()]
    monkeypatch.setattr(hc.time, "time", lambda: clock.__setitem__(0, clock[0] + 5) or clock[0])
    monkeypatch.setattr(hc, "RUN_ID", "%.3f" % real_time())
    hc._publish(hc.Report(), path)
    assert path.read_text(encoding="utf-8") == "Status: ISSUES FOUND\n", "the report another run holds is untouched"
    assert list(tmp_path.glob("unpublished-*.md"))
