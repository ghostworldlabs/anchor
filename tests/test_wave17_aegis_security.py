"""test_wave17_aegis_security.py — Wave 17 Aegis Security Vulnerability Scanner & Auto-Remediation Test Suite."""
from __future__ import annotations

from pathlib import Path

from steward_cockpit import aegis_session, steward_routes
import vendor_skills


_SYNTH_TOKEN = "sk-" + ("x" * 24)
_KEY_VAR = "api" + "_key"

VULNERABLE_SAMPLE = f'''import hashlib
import os
import subprocess
import urllib.request
import yaml

{_KEY_VAR} = "{_SYNTH_TOKEN}"

def run_cmd(user_cmd):
    return subprocess.run(user_cmd, shell=True)

def parse_cfg(raw_yaml):
    val = eval("1 + 2")
    return yaml.load(raw_yaml)

def read_user_file(base_dir, rel_name):
    with open(os.path.join(base_dir, rel_name)) as fh:
        return fh.read()

def fetch_remote(dynamic_url):
    return urllib.request.urlopen(dynamic_url).read()

def check_auth(secret_token, expected_token, user_password):
    digest = hashlib.md5(user_password.encode()).hexdigest()
    if secret_token == expected_token:
        return digest
    return ""
'''


def test_aegis_engine_detects_all_six_cwe_families():
    eng = aegis_session._load_aegis_engine()
    findings = eng.scan_python_source(VULNERABLE_SAMPLE, rel_path="vuln_app.py")
    rule_ids = {f["rule_id"] for f in findings}
    assert {"AEG-01", "AEG-02", "AEG-03", "AEG-04", "AEG-05", "AEG-06"} <= rule_ids


def test_aegis_auto_remediation_applies_valid_python_patches(tmp_path: Path):
    vuln_file = tmp_path / "service.py"
    vuln_file.write_text(VULNERABLE_SAMPLE, encoding="utf-8")

    scan_res = aegis_session.run_cockpit_aegis_scan(tmp_path)
    assert scan_res["ok"] is True
    assert scan_res["session"]["scan"]["verdict"] == "BLOCK"
    assert scan_res["session"]["scan"]["auto_fixable_count"] >= 5
    assert (tmp_path / "AEGIS-SECURITY-REPORT.md").is_file()

    # Verify frontier model seating stamp
    seating = scan_res["session"]["model_seating"]
    assert seating["coding_model_id"] == "gemini-4-argon"
    assert seating["review_model_id"] == "claude-fable-5-1"

    # Apply auto-remediation
    rem_res = aegis_session.run_cockpit_aegis_remediate(tmp_path, apply=True)
    assert rem_res["ok"] is True
    assert rem_res["session"]["last_remediation"]["applied"] is True
    assert rem_res["session"]["last_remediation"]["patches_count"] >= 5

    patched_code = vuln_file.read_text(encoding="utf-8")
    assert "shell=False" in patched_code
    assert "ast.literal_eval(" in patched_code
    assert "yaml.safe_load(" in patched_code
    assert "hmac.compare_digest(" in patched_code
    assert 'os.environ.get("API_KEY"' in patched_code


def test_aegis_registered_in_steward_routes_and_vendor_skills():
    assert "Aegis" in steward_routes.SKILLS
    skill_names = {s[0] for s in vendor_skills.SKILL_SOURCES}
    assert "aegis" in skill_names
    assert Path(r"C:\dev\Skill Foundry\skills\aegis\SKILL.md").is_file()
    assert Path(r"C:\dev\Skill Foundry\skills\aegis\HUMAN.md").is_file()
