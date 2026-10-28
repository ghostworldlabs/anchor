"""Verification suite for the October 27, 2026 Anchor Wave:
1. Option 1: Cave In-Place step-rename headline fix + Wave 14 anchor_gui modular decomposition
2. Option 2: 7-Step Onboarding & Setup / Mother Ship readiness
3. Option 3: Merrill Liechty Collaborator Mothership 1-Click Peer-Handshake readiness
4. Foundry-Style Shield Icon for Aegis across vendor/brand, Skill Foundry, and Cockpit surfaces
5. Dictate (faster-whisper-base.en only when browser mic active) & Talk Mode (Windows SAPI WAV TTS + visible spoken banner)
6. Effortless Email & Calendar Connection on Cave of Wonders (#caveCommsConnectModal) & Setup (/setup?section=comms)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import comms_connector
import high_seat_page
from steward_cockpit import dictation_engine, steward_routes

ROOT = Path(__file__).resolve().parent.parent


def test_workstream_1_cave_step_rename_precedence():
    """Verify high_seat_page._card prioritizes step['name'] over effort['name'] after an in-place step rename."""
    step = {"id": "step-1", "name": "Renamed Initiative Headline", "lane": "active"}
    effort = {
        "id": "eff-1",
        "pid": "proj-1",
        "project": "Anchor",
        "name": "Original Effort Name",
        "effort_dir": ".ecgberht/eff-1",
        "href": "/steward/v1?pid=proj-1&effort=.ecgberht/eff-1",
    }
    card_html = high_seat_page._card(step, effort, {})
    assert "Renamed Initiative Headline" in card_html


def test_workstream_3_merrill_collaborator_preset_on_cave():
    """Verify the Cave of Wonders collaboration modal includes the 1-click Merrill Liechty preset button & handler."""
    ctx = {"campaign_pid": "camp-1", "steward": {"id": "aladdin", "name": "Aladdin"}}
    html = high_seat_page._mothership_collab_html(ctx)
    assert 'id="btnCollabPresetMerrill"' in html
    assert 'data-collab-preset-merrill="1"' in html
    js = (ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    assert "[data-collab-preset-merrill]" in js
    assert "merrill-mothership" in js
    assert "Merrill Liechty (Collaborator Mothership)" in js


def test_workstream_4_aegis_foundry_shield_icon_installed():
    """Verify the Foundry-style Aegis shield icon is installed in vendor/brand and wired across Cockpit surfaces."""
    for rel in (
        "vendor/brand/aegis-icon.jpg",
        "vendor/brand/aegis-icon.png",
        "vendor/brand/aegis-icon-64.png",
        "vendor/bundled-skills/aegis/assets/icon.jpg",
        "vendor/bundled-skills/aegis/assets/icon.png",
    ):
        p = ROOT / rel
        assert p.is_file() and p.stat().st_size > 1024, f"Missing or empty icon asset: {rel}"

    v1_html = (ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
    aegis_html = (ROOT / "steward_cockpit" / "static" / "aegis.html").read_text(encoding="utf-8")
    skill_icons_js = (ROOT / "steward_cockpit" / "static" / "skill-icons.js").read_text(encoding="utf-8")
    assert "/vendor/brand/aegis-icon.jpg" in v1_html
    assert "/vendor/brand/aegis-icon.jpg" in aegis_html
    assert "aegis-icon.jpg" in skill_icons_js


def test_workstream_5_dictate_and_talk_mode_tts():
    """Verify Dictation avoids parallel System.Speech racing and Talk Mode exposes WAV TTS synthesis."""
    assert hasattr(dictation_engine, "synthesize_speech_wav")
    empty_res = dictation_engine.synthesize_speech_wav("")
    assert empty_res["ok"] is False

    # Verify steward_routes handles action == 'tts'
    with patch.object(
        dictation_engine,
        "synthesize_speech_wav",
        return_value={"ok": True, "audio_b64": "UklGRg==", "mime": "audio/wav", "engine": "windows-sapi-wav"},
    ):
        res, code = steward_routes.handle_post(
            ROOT, "dictate", {"action": "tts", "text": "Hello John, status is green.", "rate": 1}
        )
        assert code == 200
        assert res["ok"] is True
        assert res["audio_b64"] == "UklGRg=="
        assert res["engine"] == "windows-sapi-wav"

    shared_js = (ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    cave_js = (ROOT / "static" / "steward-dialogue.js").read_text(encoding="utf-8")
    shell_py = (ROOT / "shell" / "anchor_shell.py").read_text(encoding="utf-8")

    # Verify browser mic exclusivity and spoken summary banner + WAV TTS playback
    assert "steward-spoken-summary-banner" in shared_js
    assert "action: 'tts'" in shared_js or 'action: "tts"' in shared_js
    assert "caveSpokenSummaryBanner" in cave_js
    assert "PermissionRequested" in shell_py


def test_workstream_6_cave_inline_comms_connect_and_helpers():
    """Verify Cave of Wonders renders the inline Quick-Connect Drawer, 1-click links, App Password space stripping, and Local Outlook auto-connect."""
    ctx = {"campaign_pid": "camp-1", "steward": {"id": "aladdin", "name": "Aladdin"}}
    pulse_html = high_seat_page._comms_pulse_html(ctx)
    triage_html = high_seat_page._proactive_triage_strip(ctx)

    assert 'id="caveCommsConnectModal"' in pulse_html
    assert 'id="btnCaveCommsQuickConnect"' in pulse_html
    assert 'id="btnCaveCommsAutoOutlook"' in pulse_html
    assert "https://myaccount.google.com/apppasswords" in pulse_html
    assert "https://account.live.com/proofs/AppPassword" in pulse_html
    assert "https://calendar.google.com/calendar/u/0/r/settings" in pulse_html
    assert 'id="btnTriageConnectComms"' in triage_html

    # Verify PKCE returns both top-level and nested 'pkce' keys
    pkce = comms_connector.build_oauth2_pkce_challenge("gmail", "john@example.com")
    assert pkce["ok"] is True
    assert "authorize_url" in pkce
    assert "pkce" in pkce and pkce["pkce"]["authorize_url"] == pkce["authorize_url"]

    # Verify auto_connect_local_outlook is callable via handle_comms_post
    with patch.object(
        comms_connector,
        "auto_connect_local_outlook",
        return_value={"ok": True, "outlook_running": False, "events": [], "emails": [], "message": "Not running"},
    ):
        out_res, status_code = comms_connector.handle_comms_post({"action": "auto_connect_local_outlook"})
        assert status_code == 200
        assert out_res["ok"] is True
        assert out_res["outlook_running"] is False
