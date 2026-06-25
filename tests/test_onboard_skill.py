import os
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import distro

def test_onboard_skill_exported(tmp_path):
    report = distro.build_distro(output_dir=tmp_path / "export", emit_readme_file=True, cleanup_on_fail=False)
    staging = report["staging"]
    
    skill_path = staging / ".claude" / "skills" / "onboard" / "SKILL.md"
    assert skill_path.exists()
    
    content = skill_path.read_text(encoding="utf-8")
    assert "python onboard.py" in content
    assert "name: onboard" in content
