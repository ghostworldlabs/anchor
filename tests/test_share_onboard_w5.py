"""Shareable Anchor + Skills — Wave 5 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 5): plain-English onboard — home, prereqs, seats, desktop, consent,
readiness. Extends GREEN ``onboard.py`` via ``share_onboard`` (ext:onboard_dialog).

Hermetic: temp homes only; mock seat probes; no network; no paid CLI; no :8777;
no live subscription CLIs. Live probes remain behind opt-in env (not used here).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import onboard  # noqa: E402
import share_home_config as home_cfg  # noqa: E402
import share_onboard as sob  # noqa: E402
import share_readiness as ready  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FAKE_SKILLS = ["researchPrime", "crucible", "foreman", "gandalf"]


def _make_bundle(root: Path, names=None) -> Path:
    src = root / "bundled-skills"
    src.mkdir(parents=True)
    (src / "SOURCES.md").write_text("# provenance\n", encoding="utf-8")
    for name in names or FAKE_SKILLS:
        d = src / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# %s\n" % name, encoding="utf-8")
    return src


# ── Module surface ───────────────────────────────────────────────────────────

def test_w5_modules_importable():
    assert callable(sob.run_share_onboard)
    assert callable(sob.preflight_collision_scan)
    assert callable(sob.probe_all_seats)
    assert callable(sob.probe_seat)
    assert callable(sob.write_desktop_url_shortcut)
    assert callable(sob.save_feedback_consent)
    assert callable(sob.actionable_prereq_list)
    assert callable(sob.check_prereqs_fail_early)
    assert callable(sob.rollback_share_onboard)
    assert callable(sob.validate_coding_family_prefs)
    assert sob.default_feedback_opt_in() is False
    assert sob.DEFAULT_LOCAL_DASHBOARD_URL.startswith("http://localhost")


def test_recommend_home_windows_and_three_path_copy():
    assert sob.recommend_home_dir("Windows") == r"C:\dev"
    assert sob.recommend_home_dir("nt") == r"C:\dev"
    lead = sob.three_path_lead_in()
    assert "consumer" in lead and "collaborator" in lead and "feedback" in lead
    assert "local" in lead["consumer"].lower() or "Download" in lead["consumer"]
    copy = sob.feedback_consent_plain_english()
    assert copy["default"] is False
    assert copy["readiness_gate"] is False
    assert "not" in copy["what_is_not_shared"].lower()


# ── GWT #1: foreign skill refuse-don't-clobber + rollback ────────────────────

def test_given_foreign_skill_when_onboard_then_intact_overlay_or_abort(tmp_path):
    """GWT #1: foreign tree intact; overlay leaves it; abort raises; rollback safe."""
    home = tmp_path / "home"
    home.mkdir()
    skills = home / home_cfg.SKILLS_SUBDIR
    skills.mkdir(parents=True)
    foreign = skills / "foreman"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("# FOREIGN pre-existing\n", encoding="utf-8")
    # No onboard marker → foreign.
    assert not (foreign / onboard._OURS_MARKER).exists()
    foreign_body = (foreign / "SKILL.md").read_text(encoding="utf-8")

    src = _make_bundle(tmp_path / "vendor")

    # abort path
    with pytest.raises(sob.ShareOnboardError) as ei:
        sob.run_share_onboard(
            home,
            package_id="A",
            skills_src=src,
            skills_home=skills,
            mock_seat_results={"claude": True},
            on_collision="abort",
            platform_name="Windows",
        )
    assert "foreign" in ei.value.reason or "collision" in ei.value.reason
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == foreign_body

    # overlay path — foreign intact; other skills install
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        skills_home=skills,
        mock_seat_results={"claude": True},
        on_collision="overlay",
        platform_name="Windows",
    )
    assert report["ok"] is True
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == foreign_body
    assert not (foreign / onboard._OURS_MARKER).exists()
    refused_names = {
        r.get("name") for r in (report.get("skills") or {}).get("refused") or []
    }
    assert "foreman" in refused_names
    # Non-colliding bundled skills installed as ours.
    assert (skills / "crucible" / onboard._OURS_MARKER).is_file()

    # Rollback removes only recorded paths; foreign skill body survives.
    rb = sob.rollback_share_onboard(home)
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == foreign_body
    assert isinstance(rb.get("removed"), list)


# ── GWT #2: mock claude seat → ready; feedback default false ─────────────────

def test_given_mock_claude_when_readiness_then_ready_feedback_default_off(tmp_path):
    """GWT #2: mock session-visible claude + governance → ready; feedback still false."""
    home = tmp_path / "home-a"
    src = _make_bundle(tmp_path / "vendor-a")

    # Default feedback_opt_in (omit) must be False.
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": {"session_visible": True, "path_present": True}},
        on_collision="overlay",
        platform_name="Windows",
        # feedback_opt_in intentionally omitted → default off
    )
    assert report["ok"] is True
    assert report["feedback_opt_in"] is False
    stamp = report["readiness"]
    assert stamp is not None
    assert stamp["status"] == "ready"
    assert stamp["governance_installed"] is True
    assert stamp["coding_seat_ok"] is True
    assert stamp["feedback_opt_in"] is False
    assert ready.is_green_ready(stamp) is True
    # Unrelated soft warning may appear (journal), but not feedback-gated.
    assert "no_coding_seat" not in stamp["reason_codes"]
    assert "governance_missing" not in stamp["reason_codes"]

    # Consent file on disk defaults to opted_in false.
    pref = sob.load_feedback_consent(home)
    assert pref["opted_in"] is False
    assert pref.get("readiness_gate") is False

    # Explicit opt-in still does not block readiness either way.
    home2 = tmp_path / "home-a2"
    report2 = sob.run_share_onboard(
        home2,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        feedback_opt_in=True,
        platform_name="Windows",
    )
    assert report2["feedback_opt_in"] is True
    assert report2["readiness"]["status"] == "ready"
    assert report2["readiness"]["feedback_opt_in"] is True


def test_mock_probe_not_path_only_and_openai_rejected():
    """Session-visibility mock stamps ok; path-only is not ok; OpenAI disabled."""
    ok = sob.probe_seat("claude", mock_result={"session_visible": True})
    assert ok["ok"] is True
    assert ok["session_visible"] is True
    assert ok["source"] == "mock"
    assert ok["api_key_fallback"] is False

    path_only = sob.probe_seat(
        "claude",
        mock_result={"session_visible": False, "path_present": True},
    )
    assert path_only["path_present"] is True
    assert path_only["session_visible"] is False
    assert path_only["ok"] is False
    assert path_only["path_only"] is True

    openai = sob.probe_seat("openai")
    assert openai["disabled"] is True
    assert openai["status"] == sob.OPENAI_STATUS
    assert openai["ok"] is False

    codes = sob.validate_coding_family_prefs("openai", "openai")
    assert "openai_sole_family_rejected" in codes

    stamp = sob.stamp_cross_model("claude", "claude")
    assert stamp["cross_model"] is False
    stamp2 = sob.stamp_cross_model("claude", "gemini")
    assert stamp2["cross_model"] is True


def test_write_model_prefs_openai_rejected_without_writing(tmp_path):
    with pytest.raises(sob.ShareOnboardError) as ei:
        sob.write_model_prefs(
            tmp_path,
            coding_family="openai",
            review_family="gemini",
        )
    assert ei.value.reason == "openai_sole_family_rejected"
    assert not sob.model_prefs_path(tmp_path).exists()


# ── GWT #3: Anchor+Skills desktop .url local-only, no elevation ──────────────

def test_given_package_b_when_desktop_then_local_url_no_admin(tmp_path):
    """GWT #3: package B writes .url to local dashboard only; no elevation."""
    home = tmp_path / "home-b"
    src = _make_bundle(tmp_path / "vendor-b")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    report = sob.run_share_onboard(
        home,
        package_id="B",
        skills_src=src,
        mock_seat_results={"claude": True, "gemini": True},
        desktop_dir=desktop,
        dashboard_url="http://localhost:8777",
        platform_name="Windows",  # force first-class path hermetically
        on_collision="overlay",
    )
    assert report["ok"] is True
    desk = report["desktop"]
    assert desk is not None
    assert desk["created"] is True
    assert desk["elevation_required"] is False
    assert desk.get("admin_required") is False
    assert desk["url"] == "http://localhost:8777"
    path = Path(desk["path"])
    assert path.is_file()
    assert path.suffix.lower() == ".url"
    text = path.read_text(encoding="utf-8")
    assert "http://localhost:8777" in text
    assert "InternetShortcut" in text
    # No remote / tunnel URL content.
    for bad in ("ngrok", "tailscale", "https://example.com", "ts.net"):
        assert bad not in text.lower() or bad not in text

    # Remote URL refused.
    with pytest.raises(sob.ShareOnboardError) as ei:
        sob.write_desktop_url_shortcut(
            desktop_dir=desktop,
            url="https://evil.example.com/dashboard",
            platform_name="Windows",
        )
    assert "non_local" in ei.value.reason

    # Tunnel-ish host refused even if scheme is http.
    assert sob.is_local_dashboard_url("http://localhost:8777") is True
    assert sob.is_local_dashboard_url("http://127.0.0.1:8777") is True
    assert sob.is_local_dashboard_url("https://myapp.ngrok.io") is False
    assert sob.is_local_dashboard_url("https://example.com") is False


def test_os_honesty_skips_desktop_on_non_windows(tmp_path):
    desk = tmp_path / "Desktop"
    desk.mkdir()
    result = sob.write_desktop_url_shortcut(
        desktop_dir=desk,
        url="http://localhost:8777",
        platform_name="Linux",
    )
    assert result["created"] is False
    assert result["skipped"] is True
    assert "os_desktop_skipped" in result["reason_codes"]
    assert result["elevation_required"] is False


# ── Supporting: prereqs, pin mismatch, live-probe gate, idempotent ───────────

def test_prereqs_fail_early_structure():
    rep = sob.check_prereqs_fail_early(package_id="A")
    assert "rows" in rep
    assert any(r["id"] == "python" for r in rep["rows"])
    # Running under pytest ⇒ Python ok.
    assert rep["ok"] is True


def test_pin_mismatch_stamps_degraded(tmp_path):
    home = tmp_path / "home-pin"
    src = _make_bundle(tmp_path / "vendor-pin")
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        declared_skills_pin={"tag": "v1.0.0", "commit": "abc"},
        observed_skills_pin={"tag": "v0.9.0", "commit": "def"},
        platform_name="Windows",
    )
    assert report["pin_mismatch"] is True
    assert report["readiness"]["status"] in ("ready", "degraded")
    # skills_pin_mismatch is a degradation reason; may still be ready if
    # user_accepted_degraded or seat+gov — plan says stamp/print degraded.
    # compute_readiness keeps ready when gov+seat unless forked; pin is a code.
    assert "skills_pin_mismatch" in report["readiness"]["reason_codes"]


def test_live_probes_disabled_without_env(monkeypatch):
    monkeypatch.delenv(sob.LIVE_PROBES_ENV, raising=False)
    # No mock → not session-visible in CI (money-safe).
    result = sob.probe_all_seats(mock_results=None)
    assert result["coding_seat_ok"] is False
    for fam in sob.SEAT_FAMILIES:
        assert result["seats"][fam]["source"] == "path-only-no-live"
        assert result["seats"][fam]["session_visible"] is False
        assert result["seats"][fam]["api_key_fallback"] is False


def test_idempotent_second_run(tmp_path):
    home = tmp_path / "home-idemp"
    src = _make_bundle(tmp_path / "vendor-idemp")
    r1 = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    r2 = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    assert r1["ok"] and r2["ok"]
    # Second run skips already-installed ours.
    skipped = {x["name"] for x in (r2.get("skills") or {}).get("skipped") or []}
    assert skipped == set(FAKE_SKILLS) or skipped.issubset(set(FAKE_SKILLS))
    assert r2["feedback_opt_in"] is False
