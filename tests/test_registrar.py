import os
import stat
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from anchor import registrar

def test_registrar_nssm(monkeypatch):
    monkeypatch.setattr(registrar.platform, "system", lambda: "Windows")
    res = registrar.build_registrar_unit("python", 8777, "fake_token")
    assert res["type"] == "nssm"
    assert "anchor.server" in res["argv"]
    assert res["env"]["ANCHOR_TOKEN"] == "fake_token"
    assert res["restrictive_acl_requested"] is True

def test_registrar_systemd(monkeypatch, tmp_path):
    monkeypatch.setattr(registrar.platform, "system", lambda: "Linux")
    res = registrar.build_registrar_unit("python", 8777, "fake_token")
    assert res["type"] == "systemd"
    assert "anchor.server 8777" in res["text"]
    assert "ANCHOR_TOKEN=fake_token" in res["text"]
    
    # Test POSIX restrictive mode
    unit_file = tmp_path / "anchor.service"
    unit_file.write_text(res["text"])
    os.chmod(unit_file, 0o600)
    mode = unit_file.stat().st_mode
    assert mode & 0o077 == 0

def test_registrar_launchd(monkeypatch, tmp_path):
    monkeypatch.setattr(registrar.platform, "system", lambda: "Darwin")
    res = registrar.build_registrar_unit("python", 8777, "fake_token")
    assert res["type"] == "launchd"
    assert "anchor.server" in res["text"]
    assert "ANCHOR_TOKEN" in res["text"]
    assert "fake_token" in res["text"]
    
    # Test POSIX restrictive mode
    plist_file = tmp_path / "com.anchor.local.plist"
    plist_file.write_text(res["text"])
    os.chmod(plist_file, 0o600)
    mode = plist_file.stat().st_mode
    assert mode & 0o077 == 0
