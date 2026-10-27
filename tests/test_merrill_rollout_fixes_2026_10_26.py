"""Regression tests for Merrill rollout feedback (2026-10-26, v1.4.5):
1. Shipping tools/ (fence_guard.py, steward_code_job.py, steward_skill.py, gitguard/, reading_copy.py) and vendor/foundry-tools/ in dist_manifest.txt.
2. Auto-seeding and resolving foundry-tools (ft.py, INDEX.json, tiers.json, docx-redline) via paths.foundry_tools_dir().
3. Graceful degradation in steward_engine.fence_settings() when fence_guard.py is absent + doctor.probe_cockpit_tools().
4. Code-job support for non-git folders (e.g., OneDrive course/exam folders) via managed scratch git repositories + sync-back on land.
5. Preventing about:blank from reaching Windows ShellExecute ("Get an app to open this 'about' link") in shell/anchor_shell.py and app-frame openers.
6. Dynamic window.USER_DISPLAY_NAME in cockpit pages.
"""
from __future__ import annotations

import os
from pathlib import Path

import distro
import doctor
import paths
from steward_cockpit import code_jobs, foundry_tools, steward_engine, steward_routes


ROOT = Path(__file__).resolve().parent.parent


def test_manifest_ships_cockpit_tools_and_vendored_foundry_tools():
    sel = set(distro.select_shippable(ROOT))
    expected = {
        "tools/__init__.py",
        "tools/doctor_fix.py",
        "tools/fence_guard.py",
        "tools/reading_copy.py",
        "tools/review_diff.mjs",
        "tools/steward_code_job.py",
        "tools/steward_review.mjs",
        "tools/steward_skill.py",
        "tools/gitguard/__init__.py",
        "tools/gitguard/git",
        "tools/gitguard/git.cmd",
        "tools/gitguard/gitguard.py",
        "tools/gitguard/install.py",
        "vendor/foundry-tools/ft.py",
        "vendor/foundry-tools/INDEX.json",
        "vendor/foundry-tools/tiers.json",
        "vendor/foundry-tools/docx-redline/tool.py",
    }
    missing = expected - sel
    assert not missing, f"Expected cockpit tools missing from dist_manifest.txt selection: {sorted(missing)}"

    pairs = [(rel, ROOT / rel) for rel in sel]
    assert distro.scan_third_party_imports(pairs) == []
    assert distro.scan_import_closure(pairs, root=ROOT) == []
    assert distro.scan_scrub_residue(pairs) == []


def test_foundry_tools_auto_seeds_and_resolves(tmp_path, monkeypatch):
    target_ft = tmp_path / "foundry-tools"
    monkeypatch.setenv("ANCHOR_FOUNDRY_TOOLS_DIR", str(target_ft))
    monkeypatch.delenv("ANCHOR_FOUNDRY_TOOLS_INDEX", raising=False)

    seeded = paths.ensure_foundry_tools(anchor_root=ROOT, target_dir=target_ft)
    assert seeded == target_ft.resolve()
    assert (target_ft / "ft.py").is_file()
    assert (target_ft / "INDEX.json").is_file()
    assert (target_ft / "tiers.json").is_file()
    assert (target_ft / "docx-redline" / "tool.py").is_file()

    monkeypatch.setattr(foundry_tools, "DEFAULT_INDEX", tmp_path / "nonexistent" / "INDEX.json")
    assert foundry_tools.index_path() == target_ft.resolve() / "INDEX.json"
    assert len(foundry_tools.tools()) >= 5
    assert code_jobs.tiers_path() == target_ft.resolve() / "tiers.json"


def test_cockpit_degrades_cleanly_when_fence_tools_missing_and_doctor_checks_them(tmp_path, monkeypatch):
    # 1. Live repo has all tools present
    probe_live = doctor.probe_cockpit_tools(ROOT)
    assert probe_live["ok"] is True, probe_live

    # 2. When FENCE_GUARD is absent, fence_settings returns ("", {}) instead of a broken PreToolUse hook
    monkeypatch.setattr(steward_engine, "FENCE_GUARD", tmp_path / "missing_fence_guard.py")
    settings_json, env = steward_engine.fence_settings(shell=True, root=str(tmp_path))
    assert settings_json == ""
    assert env == {}

    # 3. Doctor detects missing cockpit tools on an incomplete install root
    fake_root = tmp_path / "incomplete_anchor"
    fake_root.mkdir()
    monkeypatch.setenv("ANCHOR_FOUNDRY_TOOLS_DIR", str(tmp_path / "missing_ft"))
    probe_bad = doctor.probe_cockpit_tools(fake_root)
    assert probe_bad["ok"] is False
    assert "tools/fence_guard.py" in probe_bad["missing"]
    assert "tools/steward_code_job.py" in probe_bad["missing"]
    assert "foundry-tools/ft.py" in probe_bad["missing"]


def test_code_job_supports_non_git_folder_via_scratch_repo_and_syncs_back(tmp_path, monkeypatch):
    jobs_dir = tmp_path / "Anchor-code-jobs"
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(jobs_dir))

    # Simulate Merrill's non-git OneDrive Exams folder
    onedrive_exams = tmp_path / "OneDrive" / "STAT932" / "Exams"
    onedrive_exams.mkdir(parents=True)
    (onedrive_exams / "Midterm_Draft1.md").write_text("# Midterm Draft 1\nProblem 1.\n", encoding="utf-8")

    assert code_jobs._repo_root(str(onedrive_exams)) is None

    scratch_root, err = code_jobs._ensure_scratch_git_repo(onedrive_exams)
    assert err == "" and scratch_root is not None
    assert (scratch_root / ".git").is_dir()
    assert (scratch_root / "Midterm_Draft1.md").read_text(encoding="utf-8") == "# Midterm Draft 1\nProblem 1.\n"
    assert code_jobs.destination_error(scratch_root) == ""

    # Simulate landing updated and new files in scratch_root and syncing back to OneDrive folder
    (scratch_root / "Midterm_Draft1.md").write_text("# Midterm Draft 1 (Revised)\nProblem 1 updated.\n", encoding="utf-8")
    (scratch_root / "Midterm_Draft2.md").write_text("# Midterm Draft 2\nProblem 1 + Problem 2.\n", encoding="utf-8")
    fields = {}
    note = code_jobs._sync_scratch_landed_to_source(
        {"non_git_source_dir": str(onedrive_exams)},
        scratch_root,
        ["Midterm_Draft1.md", "Midterm_Draft2.md"],
        fields,
    )
    assert "synced 2 file(s) back to non-git folder" in note
    assert fields.get("synced_to_source_dir") == str(onedrive_exams.resolve())
    assert (onedrive_exams / "Midterm_Draft1.md").read_text(encoding="utf-8") == "# Midterm Draft 1 (Revised)\nProblem 1 updated.\n"
    assert (onedrive_exams / "Midterm_Draft2.md").read_text(encoding="utf-8") == "# Midterm Draft 2\nProblem 1 + Problem 2.\n"
    assert (onedrive_exams / "Midterm_Draft1.md.bak-1").is_file()


def test_shell_and_app_frame_never_hand_about_blank_to_windows():
    shell_src = (ROOT / "shell" / "anchor_shell.py").read_text(encoding="utf-8")
    assert 'if not uri or uri.lower().startswith("about:"):' in shell_src
    assert "args.set_Handled(True)" in shell_src

    af_src = (ROOT / "static" / "app-frame.js").read_text(encoding="utf-8")
    assert "if (!rawUrl || /^about:/i.test(rawUrl)) return null;" in af_src

    hp_src = (ROOT / "high_seat_page.py").read_text(encoding="utf-8")
    assert '/static/app-frame.js' in hp_src

    cp_src = (ROOT / "campaign_page.py").read_text(encoding="utf-8")
    assert '/static/app-frame.js' in cp_src

    for js_rel in ("static/high-seat-page.js", "static/campaign-page.js", "static/high-seat.js", "anchor_gui.py"):
        js_src = (ROOT / js_rel).read_text(encoding="utf-8")
        assert "window.top.ANCHOR_APP.open(" in js_src, js_rel


def test_cockpit_injects_dynamic_user_display_name(monkeypatch):
    import onboard_wizard
    monkeypatch.setattr(
        onboard_wizard,
        "get_active_user_profile",
        lambda: {"configured": True, "display_name": "Merrill"},
    )
    html = steward_routes.serve_page_doc("v1", "p1")
    assert 'window.USER_DISPLAY_NAME="Merrill";' in html
