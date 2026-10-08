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
STUB_CHECK = """import os, pathlib
pathlib.Path(os.environ["ANCHOR_HEALTH_REPORT_OUT"]).write_text(
    "# Anchor Health Report\\n\\nStatus: OK\\nTarget: " + os.environ.get("ANCHOR_HEALTHCHECK_TARGET", "") + "\\n", encoding="utf-8")
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
    _report(reports, "2026-10-08.md", GREEN)        # the owed re-check of the running code passes
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
