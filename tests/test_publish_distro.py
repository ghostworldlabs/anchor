import os
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import distro

@pytest.fixture
def env(tmp_path, monkeypatch):
    gh_log = tmp_path / "gh.log"
    gh_stub = tmp_path / "gh_stub.py"
    gh_stub.write_text(
        "import sys\n"
        "with open(r'%s', 'a') as f:\n"
        "    f.write(' '.join(sys.argv[1:]) + '\\n')\n" % str(gh_log).replace('\\', '\\\\'),
        encoding="utf-8"
    )
    monkeypatch.setenv("ANCHOR_GH_CMD", f"{sys.executable} {gh_stub}")
    return {"gh_log": gh_log, "tmp": tmp_path, "monkeypatch": monkeypatch}

def test_publish_distro_clean(env):
    res = distro.publish_distro(dest=env["tmp"] / "export")
    assert res["status"] == "published"
    assert env["gh_log"].exists()
    log_content = env["gh_log"].read_text()
    assert "repo create --private" in log_content
    assert "push" in log_content

def test_publish_distro_pii_hit(env):
    # Inject PII into the staging by placing it in a manifest-allowed file
    # We will temporarily alter the manifest logic to stage a dirty file, or just
    # create a PersonalDataError by monkeypatching build_distro.
    def mock_build(*args, **kwargs):
        raise distro.PersonalDataError([("fake.py", "email", "john@example.com")])
    env["monkeypatch"].setattr(distro, "build_distro", mock_build)
    
    with pytest.raises(distro.PersonalDataError):
        distro.publish_distro(dest=env["tmp"] / "export")
    
    assert not env["gh_log"].exists()

def test_publish_distro_gh_absent(env):
    env["monkeypatch"].delenv("ANCHOR_GH_CMD", raising=False)
    # mock shutil.which to return None for gh
    import shutil
    orig_which = shutil.which
    def mock_which(cmd):
        if cmd == "gh": return None
        return orig_which(cmd)
    env["monkeypatch"].setattr(shutil, "which", mock_which)
    
    # Needs to not crash
    res = distro.publish_distro(dest=env["tmp"] / "export2")
    assert res["status"] == "manual"
