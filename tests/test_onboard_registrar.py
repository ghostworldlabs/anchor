import os
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import onboard

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("ANCHOR_SERVICE_CMD", raising=False)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path / "data"))
    return {"tmp": tmp_path, "monkeypatch": monkeypatch}

def test_onboard_uses_registrar_when_seam_unset(env):
    tval = "fake_token"
    
    # We'll mock the registrar inside onboard to just return a dummy unit
    # but the implementation actually calls it, so let's mock the actual function
    import anchor.registrar as reg
    orig = reg.build_registrar_unit
    
    called = []
    def mock_build(executable, port, tok):
        called.append(True)
        return {"text": "dummy unit text"}
    
    env["monkeypatch"].setattr(reg, "build_registrar_unit", mock_build)
    
    res = onboard.register_service(tval)
    assert res["status"] == "registered"
    assert "unit" in res
    assert len(called) == 1
    
    # Assert unit file was written to data dir
    unit_file = Path(env["tmp"]) / "data" / ".anchor" / "service-unit"
    assert unit_file.exists()
    assert unit_file.read_text(encoding="utf-8") == "dummy unit text"
