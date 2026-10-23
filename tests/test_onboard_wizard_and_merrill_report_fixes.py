"""Comprehensive tests for Merrill's 2026-10-22 diagnostic report fixes and the
7-Step Guided Onboarding & First-Run Setup Wizard (+ Sandbox Walkthrough Mode).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


# ==============================================================================
# 1. _ecgberht_root() multi-candidate resolution across all 5 modules
# ==============================================================================

def test_ecgberht_root_resolves_parent_skills_ecgberht(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When Ecgberht is installed at <parent>/skills/ecgberht (Merrill's layout),
    paths.ecgberht_root() and all 4 caller modules resolve it and set ECGBERHT_ROOT."""
    import paths
    import anchor_gui
    import chamber_close_report
    import commission_session
    from steward_cockpit import campaign_acts

    monkeypatch.delenv("ECGBERHT_ROOT", raising=False)
    monkeypatch.delenv("ECGBERHT_DIR", raising=False)
    monkeypatch.delenv("SKILLS_ROOT", raising=False)

    fake_dev = tmp_path / "workspace"
    fake_anchor = fake_dev / "Anchor"
    fake_anchor.mkdir(parents=True)
    merrill_ecg = fake_dev / "skills" / "ecgberht"
    (merrill_ecg / "scripts").mkdir(parents=True)
    (merrill_ecg / "scripts" / "seal-chamber-bridge.mjs").write_text("// stub\n", encoding="utf-8")
    (merrill_ecg / "scripts" / "ecgberht.mjs").write_text("// stub\n", encoding="utf-8")

    resolved, checked = paths.resolve_ecgberht_root(anchor_root=fake_anchor)
    assert resolved == merrill_ecg.resolve()
    assert len(checked) >= 2
    assert os.environ.get("ECGBERHT_ROOT") == str(merrill_ecg.resolve())

    # Now all caller modules should resolve to that exact directory
    assert anchor_gui._ecgberht_root() == merrill_ecg.resolve()
    assert chamber_close_report._ecgberht_root() == merrill_ecg.resolve()
    assert commission_session._ecgberht_root() == merrill_ecg.resolve()
    assert campaign_acts._ecgberht_root() == merrill_ecg.resolve()


def test_ecgberht_root_resolves_skills_root_and_bundled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test SKILLS_ROOT/ecgberht and vendor/bundled-skills/ecgberht fallbacks."""
    import paths

    monkeypatch.delenv("ECGBERHT_ROOT", raising=False)
    monkeypatch.delenv("ECGBERHT_DIR", raising=False)

    fake_anchor = tmp_path / "isolated" / "Anchor"
    fake_anchor.mkdir(parents=True)

    custom_skills = tmp_path / "custom_skills"
    skill_ecg = custom_skills / "ecgberht"
    (skill_ecg / "scripts").mkdir(parents=True)
    (skill_ecg / "scripts" / "seal-chamber-bridge.mjs").write_text("// stub\n", encoding="utf-8")
    monkeypatch.setenv("SKILLS_ROOT", str(custom_skills))

    resolved, _ = paths.resolve_ecgberht_root(anchor_root=fake_anchor)
    assert resolved == skill_ecg.resolve()

    # Now test bundled fallback when SKILLS_ROOT is unset
    monkeypatch.delenv("ECGBERHT_ROOT", raising=False)
    monkeypatch.delenv("SKILLS_ROOT", raising=False)
    bundled_ecg = fake_anchor / "vendor" / "bundled-skills" / "ecgberht"
    (bundled_ecg / "scripts").mkdir(parents=True)
    (bundled_ecg / "scripts" / "seal-chamber-bridge.mjs").write_text("// stub\n", encoding="utf-8")

    resolved_bundled, _ = paths.resolve_ecgberht_root(anchor_root=fake_anchor)
    assert resolved_bundled == bundled_ecg.resolve()


def test_ecgberht_bridge_missing_includes_checked_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When seal-chamber-bridge.mjs is missing, _ecgberht_bridge returns checked_paths."""
    import anchor_gui
    import paths

    empty_dir = tmp_path / "missing_ecg"
    empty_dir.mkdir(parents=True)
    monkeypatch.setenv("ECGBERHT_ROOT", str(empty_dir))
    monkeypatch.setattr(paths, "CODE_DIR", tmp_path / "fake_anchor")

    res = anchor_gui._ecgberht_bridge(["status"])
    assert res["ok"] is False
    assert res["error"] == "ecgberht_engine_missing"
    assert isinstance(res.get("checked_paths"), list)
    assert any("missing_ecg" in p for p in res["checked_paths"])
    assert "checked:" in res["message"]


# ==============================================================================
# 2. Dynamic user name & pseudonym personalization (Merrill != John)
# ==============================================================================

def test_user_identity_and_prompt_personalization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting display_name='Merrill' and pseudonym='Aladdin' personalizes steward prompts
    so Anchor addresses Merrill by name and callsign instead of 'John'."""
    import onboard_wizard
    import paths
    from steward_cockpit import steward_engine

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    saved = onboard_wizard.save_user_identity(
        display_name="Merrill",
        pseudonym="Aladdin",
        steward_persona="Aladdin",
        sandbox=False,
        base_dir=tmp_path,
    )
    assert saved["ok"] is True
    prof = onboard_wizard.get_active_user_profile(sandbox=False, base_dir=tmp_path)
    assert prof["display_name"] == "Merrill"
    assert prof["pseudonym"] == "Aladdin"
    assert prof["configured"] is True

    sample_prompt = (
        "Your name in this interface is Ecgberht - John picked that persona; answer to it. "
        "Do not substitute a short summary for John's original instructions."
    )
    personalized = steward_engine._personalize_prompt_for_user(sample_prompt)
    assert "[ACTIVE HUMAN USER PROFILE]" in personalized
    assert "Merrill" in personalized
    assert "Aladdin" in personalized
    assert "Merrill's original instructions" in personalized
    assert "John picked" not in personalized
    assert "John's original" not in personalized


# ==============================================================================
# 3. Silent onboard readiness fix (live probes skipped != seat_probe_failed)
# ==============================================================================

def test_silent_onboard_live_probes_disabled_not_marked_failed() -> None:
    """When seats are configured on PATH and live probes are disabled (silent onboard),
    probe_all_seats reports live-probes-disabled rather than a failed probe, and
    readiness_human_explanation is clear and non-alarmist."""
    import share_onboard
    import share_readiness

    def fake_which(binary: str) -> str:
        return f"/usr/local/bin/{binary}"

    seat_out = share_onboard.probe_all_seats(
        env={},
        which_fn=fake_which,
    )
    assert seat_out["coding_seat_ok"] is False
    assert seat_out["seats"]["claude"]["status"] == "live-probes-disabled"
    assert seat_out["seats"]["claude"]["path_present"] is True

    doc = {
        "schema": share_readiness.READINESS_SCHEMA,
        "schema_version": 1,
        "status": "not-ready",
        "reason_codes": ["no_coding_seat"],
        "notes": share_readiness.LIVE_PROBES_SKIPPED_NOTE,
    }
    explanation = share_readiness.readiness_human_explanation(doc)
    assert "Live CLI probes were skipped" in explanation
    assert "Onboarding Wizard" in explanation


# ==============================================================================
# 4. Sandbox Walkthrough Mode isolation, reset, and apply-to-live
# ==============================================================================

def test_sandbox_walkthrough_isolation_and_reset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sandbox mode (sandbox=True) writes only to onboard_sandbox/ without touching
    live files, ignores live processes, and supports reset_sandbox + apply_sandbox_to_live."""
    import onboard_wizard
    import paths

    live_dir = tmp_path / "live_data"
    live_dir.mkdir(parents=True)
    monkeypatch.setattr(paths, "data_dir", lambda: live_dir)

    # Pre-seed live user profile as John
    onboard_wizard.save_user_identity(
        display_name="John",
        pseudonym="Samwise Gamgee",
        steward_persona="Ecgberht",
        sandbox=False,
        base_dir=live_dir,
    )

    # Modify identity inside sandbox
    res = onboard_wizard.save_user_identity(
        display_name="SandboxTester",
        pseudonym="Voyager",
        steward_persona="Jarvis",
        sandbox=True,
        base_dir=live_dir,
    )
    assert res["ok"] is True
    assert res["profile"]["sandbox"] is True

    # Live profile must be untouched
    live_prof = onboard_wizard.get_active_user_profile(sandbox=False, base_dir=live_dir)
    assert live_prof["display_name"] == "John"

    # Sandbox profile has the new identity
    sb_prof = onboard_wizard.get_active_user_profile(sandbox=True, base_dir=live_dir)
    assert sb_prof["display_name"] == "SandboxTester"
    assert sb_prof["pseudonym"] == "Voyager"

    # Apply sandbox to live
    applied = onboard_wizard.apply_sandbox_to_live(base_dir=live_dir)
    assert applied["ok"] is True
    assert onboard_wizard.get_active_user_profile(sandbox=False, base_dir=live_dir)["display_name"] == "SandboxTester"

    # Reset sandbox
    reset_res = onboard_wizard.reset_sandbox(base_dir=live_dir)
    assert reset_res["ok"] is True
    sb_prof_after = onboard_wizard.get_active_user_profile(sandbox=True, base_dir=live_dir)
    assert sb_prof_after["configured"] is False


# ==============================================================================
# 5. Step 2: Tailscale detection & Mothership topology configuration
# ==============================================================================

def test_step2_tailscale_and_mothership_topology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify Tailscale detection and Mothership / Remote Peer topology configuration."""
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    ts = onboard_wizard.detect_or_install_tailscale(sandbox=True)
    assert ts["sandbox_ignored_live"] is True
    assert "winget install" in ts["install_command"]

    topo = onboard_wizard.configure_mothership_topology(
        mode="connect_remote_mothership",
        remote_address="http://100.64.0.1:8777",
        sandbox=True,
        base_dir=tmp_path,
    )
    assert topo["ok"] is True
    assert topo["topology"]["mode"] == "connect_remote_mothership"
    assert topo["topology"]["remote_mothership_url"] == "http://100.64.0.1:8777"


# ==============================================================================
# 6. Step 3: 4-Service AI status, connection config, CLI update, live test -> ready
# ==============================================================================

def test_step3_ai_services_and_live_test_promotes_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuring and testing an AI service in Step 3 updates readiness.json to status='ready'."""
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    status = onboard_wizard.detect_ai_services_status(sandbox=True, base_dir=tmp_path)
    assert len(status["services"]) == 4
    assert set(status["services"].keys()) == {"claude", "gemini", "grok", "chatgpt"}

    conn = onboard_wizard.configure_service_connection(
        family="claude",
        auth_mode="subscription",
        tier_level="frontier",
        sandbox=True,
        base_dir=tmp_path,
    )
    assert conn["ok"] is True
    assert conn["service"]["tier_level"] == "frontier"

    cli_check = onboard_wizard.check_or_update_cli(family="claude", sandbox=True, base_dir=tmp_path)
    assert cli_check["ok"] is True
    assert cli_check["up_to_date"] is True

    live_res = onboard_wizard.run_service_live_test(family="claude", sandbox=True, base_dir=tmp_path)
    assert live_res["ok"] is True
    assert live_res["readiness"]["status"] == "ready"
    assert "seat_probe_failed" not in live_res["readiness"].get("reason_codes", [])


# ==============================================================================
# 7. Step 4: Star Chart & Goal Organization with Steward
# ==============================================================================

def test_step4_organize_goals_with_starchart_steward(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Step 4 structures raw brain-dump lines into Strategic Arenas and Tier-1/Tier-2 goals."""
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    onboard_wizard.save_user_identity(display_name="Merrill", pseudonym="Aladdin", sandbox=True, base_dir=tmp_path)

    raw_goals = "\n".join([
        "Ship Anchor v1.5 onboarding wizard",
        "Publish flagship neuroscience research paper",
        "Deliver MBA AI course materials",
        "Manage family trust operations",
    ])
    res = onboard_wizard.organize_goals_with_starchart_steward(
        raw_text=raw_goals,
        mission_statement="Advance research, teaching, and AI systems",
        sandbox=True,
        base_dir=tmp_path,
    )
    assert res["ok"] is True
    items = res["goals"]["items"]
    assert len(items) == 4
    assert sum(1 for g in items if g["tier"] == 1) == 3
    assert sum(1 for g in items if g["tier"] == 2) == 1
    assert len(res["goals"]["arenas"]) >= 2


# ==============================================================================
# 8. Step 5: Orphaned .anchor/projects/<id> re-adoption, exclusions, starter cockpit
# ==============================================================================

def test_step5_project_scan_orphan_readoption_and_cockpit_provision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 5 discovers candidate projects, re-adopts orphaned .anchor/projects/<id>
    stores, filters excluded directories, and provisions starter AI cockpits."""
    import onboard_wizard
    import paths

    data_root = tmp_path / "data"
    monkeypatch.setattr(paths, "data_dir", lambda: data_root)

    ws_root = tmp_path / "dev_workspace"
    ws_root.mkdir(parents=True)

    # Create a candidate project with an orphaned .anchor/projects/<id> store
    proj_a = ws_root / "alpha-engine"
    (proj_a / ".git").mkdir(parents=True)
    (proj_a / "README.md").write_text("# Alpha Engine\nCore simulation engine.\n", encoding="utf-8")
    orphan_store = proj_a / ".anchor" / "projects" / "legacy-merrill-id-001"
    orphan_store.mkdir(parents=True)

    # Create a second project that we will exclude
    proj_b = ws_root / "scratch-throwaway"
    proj_b.mkdir(parents=True)

    # Create an excluded noise directory
    junk = ws_root / "node_modules"
    junk.mkdir(parents=True)

    scan_res = onboard_wizard.scan_and_propose_projects(
        roots=[str(ws_root)],
        excluded_paths=[str(proj_b)],
        sandbox=True,
        base_dir=data_root,
    )
    assert scan_res["ok"] is True
    by_name = {p["name"]: p for p in scan_res["discovered"]}
    assert "alpha-engine" in by_name
    assert "node_modules" not in by_name
    assert by_name["alpha-engine"]["id"] == "legacy-merrill-id-001"
    assert by_name["alpha-engine"]["source"] == "re_adopted_store"
    assert by_name["scratch-throwaway"]["excluded"] is True

    # Provision selected projects in sandbox
    prov_res = onboard_wizard.provision_projects_and_cockpits(
        selected_projects=scan_res["discovered"],
        sandbox=True,
        base_dir=data_root,
    )
    assert prov_res["ok"] is True
    assert prov_res["count"] == 1
    p0 = prov_res["provisioned"][0]
    assert p0["id"] == "legacy-merrill-id-001"
    cockpit_dir = Path(p0["sandbox_cockpit_path"])
    assert (cockpit_dir / "ECGBERHT.md").is_file()
    assert (cockpit_dir / "roadmap.json").is_file()
    assert (cockpit_dir / "strip.json").is_file()
    assert (cockpit_dir / "DELIVERABLES.md").is_file()


# ==============================================================================
# 9. HTTP Routes integration (/onboard-wizard, /api/onboard-wizard/state & action)
# ==============================================================================

def test_http_routes_onboard_wizard_and_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify anchor_gui wires GET /onboard-wizard, GET /api/onboard-wizard/state,
    and POST /api/onboard-wizard/action for both live and sandbox modes."""
    import anchor_gui
    import onboard_wizard
    import paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)

    html_live = onboard_wizard.render_onboard_wizard_html(sandbox=False, base_dir=tmp_path)
    assert "Anchor Guided Onboarding &amp; Setup Wizard" in html_live
    assert "Step 1" in html_live

    html_sb = onboard_wizard.render_onboard_wizard_html(sandbox=True, base_dir=tmp_path)
    assert "SANDBOX WALKTHROUGH MODE" in html_sb

    state = onboard_wizard.get_wizard_full_state(sandbox=True, base_dir=tmp_path)
    assert state["ok"] is True
    assert state["sandbox"] is True
    assert "receipt" in state

    act_res = onboard_wizard.dispatch_wizard_action(
        "save_identity",
        {"display_name": "Merrill", "pseudonym": "Aladdin", "steward_persona": "Aladdin"},
        sandbox=True,
        base_dir=tmp_path,
    )
    assert act_res["ok"] is True
    assert act_res["profile"]["display_name"] == "Merrill"

    # Confirm anchor_gui contains the route handlers
    gui_src = Path(anchor_gui.__file__).read_text(encoding="utf-8")
    assert '"/onboard-wizard"' in gui_src
    assert '"/api/onboard-wizard/state"' in gui_src
    assert '"/api/onboard-wizard/action"' in gui_src


# ==============================================================================
# 10. Steward Persona Consistency (Cave of Wonders <-> AI Cockpit)
# ==============================================================================

def test_steward_persona_consistency_cave_to_cockpit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the user selects Jarvis, Ecgberht, or Aladdin, anchor_settings.steward_profile(),
    steward_routes._persona_name(), serve_page_doc(window.STEWARD_NAME), and CONFIG['steward']
    all stay 100% consistent across Cave of Wonders and AI Cockpit."""
    import anchor_settings as aset
    import onboard_wizard
    import paths
    from steward_cockpit import steward_routes as sr

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(aset, "settings_path", lambda: tmp_path / "settings.json")

    for key, expected_label in (("jarvis", "Jarvis"), ("ecgberht", "Ecgberht"), ("aladdin", "Aladdin")):
        onboard_wizard.save_user_identity(
            display_name="Merrill",
            pseudonym="Aladdin",
            steward_persona=expected_label,
            sandbox=False,
        )
        prof = aset.steward_profile()
        assert prof["label"] == expected_label
        assert prof["name"] == expected_label
        assert sr._persona_name() == expected_label
        assert sr.CONFIG["steward"] == expected_label

        doc_html = sr.serve_page_doc("cockpit", pid="test-proj")
        assert f'window.STEWARD_NAME="{expected_label}"' in doc_html
        assert 'window.USER_DISPLAY_NAME="Merrill"' in doc_html


# ==============================================================================
# 11. Claude Model Selection, ~/.claude/settings.json Forwarding & Credit-Gate Fallback
# ==============================================================================

def test_claude_catalog_models_and_credit_gate_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify:
    1) model_policy.normalize_catalog('claude', ...) exposes best, opus, sonnet, haiku
       while keeping 'best' as rank 0 default;
    2) steward_engine._spawn_env forwards ANTHROPIC_DEFAULT_FABLE_MODEL from CLAUDE_CONFIG_DIR/settings.json;
    3) steward_engine._try_claude_credit_gate_fallback steps down 'best' -> 'opus' -> 'sonnet'
       when 'Fable 5.1 requires usage credits' is returned."""
    import anchor_settings as aset
    import model_policy
    import paths
    from steward_cockpit import steward_engine as se

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(aset, "settings_path", lambda: tmp_path / "settings.json")

    cat = model_policy.normalize_catalog("claude", {"efforts": ["low", "medium", "high", "max"]})
    models = [row["model"] for row in cat]
    assert models == ["best", "opus", "sonnet", "haiku"]
    assert model_policy.select_model("claude", cat)["model"] == "best"

    # Test ~/.claude/settings.json env forwarding in _spawn_env
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_DEFAULT_FABLE_MODEL": "claude-sonnet-5-5"}}),
        encoding="utf-8",
    )
    import provider_native
    monkeypatch.setattr(
        provider_native,
        "account_env",
        lambda conn=None: {"CLAUDE_CONFIG_DIR": str(claude_dir)},
    )

    cdir = tmp_path / "cockpit_test"
    cdir.mkdir(parents=True)
    eng = se.Engine(str(cdir), fake=True, steward="Jarvis")
    eng.cli = "claude"
    spawn_env = eng._spawn_env()
    assert spawn_env.get("ANTHROPIC_DEFAULT_FABLE_MODEL") == "claude-sonnet-5-5"

    # Test automatic credit-gate fallback: best -> opus -> sonnet
    eng.model_selection = {"family": "claude", "cli": "claude", "model": "best", "effort": "max", "cli_args": ["--model", "best", "--effort", "max"]}
    assert eng._try_claude_credit_gate_fallback("Fable 5.1 requires usage credits. Please switch to another model.") is True
    assert eng.model_selection["model"] == "opus"
    assert aset.read_settings_state()["settings"]["provider_preferences"]["quality"]["claude"]["model"] == "opus"

    assert eng._try_claude_credit_gate_fallback("Opus requires usage credits.") is True
    assert eng.model_selection["model"] == "sonnet"
    assert aset.read_settings_state()["settings"]["provider_preferences"]["quality"]["claude"]["model"] == "sonnet"


# ==============================================================================
# 12. Dynamic User Display Name in Aegis Session & Full Portfolio Manifest
# ==============================================================================

def test_aegis_session_uses_configured_display_name_and_landed_skills_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify aegis_session uses the configured user's display name (e.g. 'MERRILL')
    and share_onboard._landed_skill_names includes all valid skill directories in skills_home."""
    import onboard_wizard
    import paths
    import share_onboard
    from steward_cockpit import aegis_session

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    onboard_wizard.save_user_identity(
        display_name="Merrill",
        pseudonym="Aladdin",
        steward_persona="Aladdin",
        sandbox=False,
        base_dir=tmp_path,
    )

    cdir = tmp_path / "proj_aegis"
    cdir.mkdir(parents=True)
    state = aegis_session.chat_in_aegis_session(cdir, "What is our security posture?")
    turns = state["session"]["dialogue"]
    user_turns = [t for t in turns if t.get("role") == "user"]
    assert user_turns and user_turns[-1]["who"] == "MERRILL"

    # Verify _landed_skill_names unions skill_report with existing valid skill dirs on disk
    skills_home = tmp_path / "skills_root"
    for sname in ("anvil", "aegis", "ecgberht", "foreman", "crucible"):
        sdir = skills_home / sname
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text(f"# {sname}\n", encoding="utf-8")

    landed = share_onboard._landed_skill_names(
        {"installed": [{"name": "anvil"}], "skipped": [], "refused": []},
        skills_home=skills_home,
    )
    assert set(landed) == {"anvil", "aegis", "ecgberht", "foreman", "crucible"}

