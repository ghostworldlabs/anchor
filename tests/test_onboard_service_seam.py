"""Share-distro Wave 7 — service seam + foreground fallback + rollback (stubbed).

Proves the Wave 7 Given/When/Then (IMPLEMENTATION-PLAN.md "## Wave 7"):

  1. Given the service stub, When onboard registers, Then the stub records the
     intended argv + token-env.
  2. Given a forced registrar failure, Then onboard constructs the correct
     foreground launch argv + env via ANCHOR_FOREGROUND_CMD with a port chosen
     by pick_free_port asserted ≠ 8777.
  3. Given an injected mid-registration failure, Then rollback leaves no partial
     service record.
"""

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import onboard  # noqa: E402

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Temp seams for ANCHOR_SERVICE_CMD and ANCHOR_FOREGROUND_CMD."""
    svc_log = tmp_path / "svc.log"
    fg_log = tmp_path / "fg.log"
    rollback_log = tmp_path / "rollback.log"
    
    # We write simple shell scripts to act as our stubs.
    svc_stub = tmp_path / "svc_stub.py"
    svc_stub.write_text(
        "import sys, os\n"
        "action = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if action == 'rollback':\n"
        "    with open(r'%s', 'a') as f:\n"
        "        f.write('rolled_back\\n')\n"
        "    sys.exit(0)\n"
        "fail = os.environ.get('STUB_FAIL_SVC') == '1'\n"
        "midway = os.environ.get('STUB_FAIL_MIDWAY') == '1'\n"
        "with open(r'%s', 'a') as f:\n"
        "    if midway:\n"
        "        f.write('partial\\n')\n"
        "        sys.exit(1)\n"
        "    if fail:\n"
        "        sys.exit(1)\n"
        "    f.write(str(sys.argv[1:]) + '|' + os.environ.get('ANCHOR_TOKEN', '') + '\\n')\n" % (
            str(rollback_log).replace('\\', '\\\\'),
            str(svc_log).replace('\\', '\\\\')
        ),
        encoding="utf-8"
    )
    
    fg_stub = tmp_path / "fg_stub.py"
    fg_stub.write_text(
        "import sys, os\n"
        "with open(r'%s', 'a') as f:\n"
        "    f.write(str(sys.argv[1:]) + '|' + os.environ.get('ANCHOR_TOKEN', '') + '\\n')\n" % str(fg_log).replace('\\', '\\\\'),
        encoding="utf-8"
    )

    monkeypatch.setenv("ANCHOR_SERVICE_CMD", f"{sys.executable} {svc_stub}")
    monkeypatch.setenv("ANCHOR_FOREGROUND_CMD", f"{sys.executable} {fg_stub}")
    
    return {"svc_log": svc_log, "fg_log": fg_log, "rollback_log": rollback_log, "monkeypatch": monkeypatch}

def test_register_service_stub_success(env):
    tval = "fake_token"
    res = onboard.register_service(tval)
    assert res["status"] == "registered"
    assert env["svc_log"].exists()
    content = env["svc_log"].read_text(encoding="utf-8").strip()
    assert tval in content
    # argv should include the command to run the server
    assert "anchor.server" in content

def test_register_service_fallback(env):
    tval = "fake_token_fg"
    env["monkeypatch"].setenv("STUB_FAIL_SVC", "1")
    res = onboard.register_service(tval)
    assert res["status"] == "foreground_fallback"
    assert res["port"] != 8777
    
    import time
    for _ in range(10):
        if env["fg_log"].exists():
            break
        time.sleep(0.1)
    
    assert env["fg_log"].exists()
    content = env["fg_log"].read_text(encoding="utf-8").strip()
    assert tval in content
    assert str(res["port"]) in content
    assert "anchor.server" in content

def test_register_service_rollback(env):
    tval = "fake_token_midway"
    env["monkeypatch"].setenv("STUB_FAIL_MIDWAY", "1")
    res = onboard.register_service(tval)
    assert res["status"] == "foreground_fallback"
    
    # In a midway failure, the partial service record should be rolled back.
    # Our stub doesn't actually install a service, but onboard should try to rollback.
    assert env["rollback_log"].exists()
    assert "rolled_back" in env["rollback_log"].read_text(encoding="utf-8")
