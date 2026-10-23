"""Comprehensive test suite for Wave 24 (`wave24-website-license-launch`):
Public Website, Ghost World Lab Non-Resale License v1, Download Portal & Feedback Loop.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import distro
import share_ci_ship_gate as ship_gate
import share_feedback_intake as fbi
import website_portal as wp

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPROVEMENT_ROOT = REPO_ROOT.parent / "Anchor-Improvement"


# ── 1. Non-Resale License v1 Spec & Zero-OSS-License-File Law ───────────────

def test_non_resale_license_spec_and_no_oss_license_stamp():
    spec = wp.get_non_resale_license_spec()
    assert spec["schema"] == "anchor.license.non_resale.v1"
    assert spec["license_id"] == "GHOST-WORLD-LAB-NON-RESALE-v1"
    assert spec["version"] == "1.0-r2"
    assert spec["not_open_source"] is True
    assert "not open source" in spec["rights_reserved_notice"].lower()

    # Operative clauses 1..10
    clauses = spec["operative_clauses"]
    assert len(clauses) == 10
    assert [c["section"] for c in clauses] == list(range(1, 11))

    # Plain-English Companion 1..10
    companion = spec["plain_english_companion"]
    assert len(companion) == 10
    assert [c["clause"] for c in companion] == list(range(1, 11))

    # Contractor Labor vs. Non-Resale Boundary table
    table = spec["contractor_vs_non_resale_table"]
    permitted_rows = [r for r in table if r["permitted"] is True]
    restricted_rows = [r for r in table if r["permitted"] is False]
    assert len(permitted_rows) >= 2
    assert len(restricted_rows) >= 4
    assert any("contractor" in r["transaction"].lower() for r in permitted_rows)
    assert any("one-time software price" in r["transaction"].lower() for r in restricted_rows)
    assert any("recurring" in r["transaction"].lower() for r in restricted_rows)
    assert any("hosted access" in r["transaction"].lower() for r in restricted_rows)

    # Verify share_ci_ship_gate.check_docs_and_rights_reserved() passes (zero OSS LICENSE files at root)
    gate_res = ship_gate.check_docs_and_rights_reserved(REPO_ROOT)
    assert gate_res["ok"] is True, f"Ship gate failed: {gate_res}"
    assert gate_res["no_oss_license"]["ok"] is True
    assert gate_res["no_oss_license"]["license_files"] == []


# ── 2. Click-Wrap License Acceptance Token Minting, HMAC & Tamper Rejection ─

def test_clickwrap_license_acceptance_and_hmac_verification(tmp_path):
    # Refuses fail-closed when accepted_non_resale is False or non-bool
    refused = wp.accept_non_resale_license(
        "Samwise Gamgee",
        accepted_non_resale=False,
        store_dir=tmp_path,
    )
    assert refused["ok"] is False
    assert refused["code"] == 400
    assert refused["error"] == "license_acceptance_required"

    refused_empty_handle = wp.accept_non_resale_license(
        "   ",
        accepted_non_resale=True,
        store_dir=tmp_path,
    )
    assert refused_empty_handle["ok"] is False
    assert refused_empty_handle["error"] == "pseudonym_required"

    # Mints signed receipt when accepted_non_resale is True
    accepted = wp.accept_non_resale_license(
        "Samwise Gamgee",
        accepted_non_resale=True,
        intended_use="personal_or_research",
        version="1.0-r2",
        store_dir=tmp_path,
    )
    assert accepted["ok"] is True
    assert accepted["code"] == 200
    receipt = accepted["receipt"]
    assert receipt["schema"] == "anchor.license.acceptance.v1"
    assert receipt["license_id"] == "GHOST-WORLD-LAB-NON-RESALE-v1"
    assert receipt["pseudonym"] == "Samwise Gamgee"
    assert receipt["accepted_non_resale"] is True
    assert len(receipt["hmac_sha256"]) == 64

    # Persisted in .anchor/license_acceptances.json
    store_file = wp.license_acceptances_path(tmp_path)
    assert store_file.is_file()

    # Verify by dict and by token_id lookup
    v_dict = wp.verify_license_acceptance_token(receipt, store_dir=tmp_path)
    assert v_dict["ok"] is True and v_dict["valid"] is True

    v_id = wp.verify_license_acceptance_token(receipt["token_id"], store_dir=tmp_path)
    assert v_id["ok"] is True and v_id["valid"] is True

    # Tamper with pseudonym -> HMAC verification must fail closed
    tampered = dict(receipt)
    tampered["pseudonym"] = "Saruman"
    v_tampered = wp.verify_license_acceptance_token(tampered, store_dir=tmp_path)
    assert v_tampered["ok"] is False
    assert v_tampered["code"] == 403
    assert v_tampered["error"] == "license_acceptance_required"
    assert v_tampered["reason"] == "hmac_signature_mismatch"

    # Tamper with hmac_sha256 directly -> must fail closed
    tampered_mac = dict(receipt)
    tampered_mac["hmac_sha256"] = "0" * 64
    v_bad_mac = wp.verify_license_acceptance_token(tampered_mac, store_dir=tmp_path)
    assert v_bad_mac["ok"] is False
    assert v_bad_mac["code"] == 403


# ── 3. Multi-Platform Download Portal Fail-Closed Enforcement ───────────────

def test_download_portal_fail_closed_and_multi_platform_matrix(tmp_path):
    catalog = wp.get_download_catalog()
    assert catalog["license_id"] == "GHOST-WORLD-LAB-NON-RESALE-v1"
    assert catalog["included_skills_count"] == 19
    assert catalog["cold_start_command"] == "python -m share_onboard"
    pkg_ids = {p["package_id"] for p in catalog["packages"]}
    assert {"gwl-skills", "gwl-anchor-and-skills", "gwl-collab-client"} <= pkg_ids

    # 1) Without license acceptance -> 403 license_acceptance_required
    unauthed = wp.authorize_package_download(
        "gwl-skills",
        "windows",
        license_token=None,
        store_dir=tmp_path,
    )
    assert unauthed["ok"] is False
    assert unauthed["code"] == 403
    assert unauthed["error"] == "license_acceptance_required"

    # Mint valid license receipt
    lic = wp.accept_non_resale_license(
        "Samwise Gamgi",
        accepted_non_resale=True,
        store_dir=tmp_path,
    )
    receipt = lic["receipt"]

    # 2) Forbidden anchor-only package -> 400 anchor_only_forbidden
    for forbidden_pkg in ("anchor-only", "anchor_only", "anchor", "share-anchor-only"):
        forb = wp.authorize_package_download(
            forbidden_pkg,
            "windows",
            license_token=receipt,
            store_dir=tmp_path,
        )
        assert forb["ok"] is False
        assert forb["code"] == 400
        assert forb["error"] == "anchor_only_forbidden"
        assert "anchor_only_forbidden" in forb["reason_codes"]

    # 3) Valid packages across windows, macos, linux once license is accepted -> 200
    for pkg_id in ("gwl-skills", "gwl-anchor-and-skills", "gwl-collab-client"):
        for plat in ("windows", "macos", "linux"):
            for arch in ("x64", "arm64", "universal"):
                dl = wp.authorize_package_download(
                    pkg_id,
                    plat,
                    license_token=receipt,
                    arch=arch,
                    store_dir=tmp_path,
                )
                assert dl["ok"] is True
                assert dl["code"] == 200
                assert dl["package_id"] == pkg_id
                assert dl["platform_os"] == plat
                assert dl["arch"] == arch
                assert dl["cold_start_command"] == "python -m share_onboard"
                assert dl["included_skills_count"] == 19
                assert dl["license_receipt_id"] == receipt["token_id"]
                assert len(dl["sha256_manifest_digest"]) == 64


# ── 4. Structured Opt-In Feedback Loop & Sleep-Cycle Triage ─────────────────

def test_structured_opt_in_feedback_loop_and_triage(tmp_path):
    intake_root = tmp_path / "feedback-intake"

    # 1) consent_granted=False rejected fail-closed
    no_consent = wp.submit_portal_feedback(
        {
            "consent_granted": False,
            "skill_id": "foreman",
            "skill_version": "1.0.0",
            "outcome": "friction",
            "structural_failure_codes": ["timeout"],
        },
        intake_root=intake_root,
    )
    assert no_consent["ok"] is False
    assert no_consent["code"] == 400
    assert no_consent["error"] == "consent_required_opt_in_only"
    assert no_consent["dropped"] is True

    # 2) PII / email / path / secret payloads dropped fail-closed
    synthetic_email = "researcher" + "@" + "private-lab" + ".io"
    pii_res = wp.submit_portal_feedback(
        {
            "consent_granted": True,
            "skill_id": "foreman",
            "skill_version": "1.0.0",
            "outcome": "friction",
            "structural_failure_codes": ["timeout"],
            "notes": f"Contact {synthetic_email} about this run",
        },
        intake_root=intake_root,
    )
    assert pii_res["ok"] is False
    assert pii_res["code"] == 422
    assert pii_res["error"] == "fail_closed_dropped"
    assert pii_res["dropped"] is True

    synthetic_win_path = "C:" + "\\Users\\" + "realuser\\secret_repo"
    path_res = wp.submit_portal_feedback(
        {
            "consent_granted": True,
            "skill_id": "crucible",
            "skill_version": "1.0.0",
            "outcome": "failed",
            "structural_failure_codes": ["gate_red"],
            " leaked_path": synthetic_win_path,
        },
        intake_root=intake_root,
    )
    assert path_res["ok"] is False
    assert path_res["code"] == 422
    assert path_res["error"] == "fail_closed_dropped"

    synthetic_key = "sk-" + ("A9b8C7d6" * 3)
    secret_res = wp.submit_portal_feedback(
        {
            "consent_granted": True,
            "skill_id": "researchprime",
            "skill_version": "1.0.0",
            "outcome": "failed",
            "structural_failure_codes": ["seat_failover"],
            "credential_leak": synthetic_key,
        },
        intake_root=intake_root,
    )
    assert secret_res["ok"] is False
    assert secret_res["code"] == 422
    assert secret_res["error"] == "fail_closed_dropped"

    # 3) Valid allowlisted skill-friction records stored in by_skill/<skill_id>/
    clean_1 = wp.submit_portal_feedback(
        {
            "consent_granted": True,
            "skill_id": "foreman",
            "skill_version": "1.2.4",
            "outcome": "friction",
            "structural_failure_codes": ["timeout", "seat_failover"],
            "duration_band": "5_30m",
            "complexity_band": "large",
            "os_class": "windows",
            "model_family_seats": ["claude", "gemini"],
            "workaround_codes": ["seat_switch"],
            "workaround_tokens": ["wave_retry"],
        },
        intake_root=intake_root,
    )
    assert clean_1["ok"] is True
    assert clean_1["code"] == 200
    assert clean_1["accepted"] is True
    assert clean_1["dropped"] is False
    assert clean_1["auto_merge"] is False
    assert clean_1["feedback_is_code_contribution"] is False
    assert clean_1["policy"] == fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION
    assert Path(clean_1["partition_path"]).is_file()
    assert "by_skill" in clean_1["partition_dir"] and "foreman" in clean_1["partition_dir"]

    clean_2 = wp.submit_portal_feedback(
        {
            "consent_granted": True,
            "skill_id": "anvil",
            "skill_version": "1.2.4",
            "outcome": "workaround",
            "structural_failure_codes": ["parse_error"],
            "os_class": "linux",
            "workaround_codes": ["manual_fix"],
        },
        intake_root=intake_root,
    )
    assert clean_2["ok"] is True

    # 4) Aggregated in sleep-cycle triage summary
    summary = wp.get_feedback_loop_summary(intake_root=intake_root)
    assert summary["total_sanitized_reports"] == 2
    assert set(summary["skill_ids"]) == {"anvil", "foreman"}
    assert summary["reports_by_skill"]["foreman"]["count"] == 1
    assert summary["reports_by_skill"]["anvil"]["count"] == 1
    assert summary["workaround_frequencies"]["seat_switch"] == 1
    assert summary["workaround_frequencies"]["manual_fix"] == 1
    assert summary["auto_merge_allowed"] is False

    recs = summary["foundry_sleep_cycle_triage_recommendations"]
    assert len(recs) == 2
    assert all(r["ad_hoc_patching_forbidden"] is True for r in recs)
    assert all(r["auto_merge_to_skill_sources"] is False for r in recs)


# ── 5. Website HTML Rendering, HTTP Routes & Distro Zero-PII Check ──────────

def test_website_html_rendering_and_distro_clean_scan():
    html = wp.render_public_website_html()
    assert "<!DOCTYPE html>" in html
    assert "GHOST-WORLD-LAB-NON-RESALE-v1" in html
    assert "All rights reserved" in html
    assert "gwl-skills" in html
    assert "gwl-anchor-and-skills" in html
    assert "Samwise Gamgee" in html
    assert "python -m share_onboard" in html

    # Preview HTML file exists in Anchor-Improvement
    preview_path = IMPROVEMENT_ROOT / "Distribution and Collaboration" / "WEBSITE-PORTAL-PREVIEW.html"
    assert preview_path.is_file()
    assert "GHOST-WORLD-LAB-NON-RESALE-v1" in preview_path.read_text(encoding="utf-8")

    # Roadmap Wave 24 marked done (all 24 of 24 waves done!)
    roadmap_path = IMPROVEMENT_ROOT / "roadmap.json"
    roadmap_doc = json.loads(roadmap_path.read_text(encoding="utf-8"))
    proj = roadmap_doc["roadmap_projection"]
    assert len(proj) == 24
    w24 = next(w for w in proj if w["id"] == "wave24-website-license-launch")
    assert w24["status"] == "done"
    assert all(w["status"] == "done" for w in proj)

    # Distro manifest includes website_portal.py and scan_paths is 100% clean
    manifest_entries = distro.load_manifest()
    assert "website_portal.py" in manifest_entries

    hits = distro.scan_paths([
        ("website_portal.py", REPO_ROOT / "website_portal.py"),
        ("tests/test_wave24_website_license_launch.py", Path(__file__).resolve()),
    ])
    assert hits == [], f"distro scan_paths found personal data or bad imports: {hits}"


def test_anchor_gui_website_http_routes(monkeypatch, tmp_path):
    import anchor_gui

    monkeypatch.setattr(wp, "_default_anchor_store_dir", lambda store_dir=None: tmp_path / ".anchor")

    class DummyRequestHandler:
        def __init__(self, path: str, body_dict: dict | None = None):
            self.path = path
            raw_bytes = json.dumps(body_dict).encode("utf-8") if body_dict is not None else b""
            self.headers = {"Content-Length": str(len(raw_bytes))}
            self.rfile = io.BytesIO(raw_bytes)
            self.wfile = io.BytesIO()
            self.sent_html = None
            self.sent_json = None
            self.sent_code = None

        def _strangler_dispatch(self, method, path_only, body):
            return False

        def _data_plane_gate(self, method, path_only):
            return False

        def _send_html(self, html_str, code=200, cookie=None):
            self.sent_html = html_str
            self.sent_code = code

        def _send_json(self, obj, code=200):
            self.sent_json = obj
            self.sent_code = code

    # GET /website and /download-portal
    for route in ("/website", "/download-portal"):
        h_get = DummyRequestHandler(route)
        anchor_gui.AnchorHandler.do_GET(h_get)
        assert h_get.sent_code == 200
        assert "GHOST-WORLD-LAB-NON-RESALE-v1" in h_get.sent_html

    # GET /api/website/catalog
    h_cat = DummyRequestHandler("/api/website/catalog")
    anchor_gui.AnchorHandler.do_GET(h_cat)
    assert h_cat.sent_code == 200
    assert h_cat.sent_json["ok"] is True
    assert h_cat.sent_json["license"]["license_id"] == "GHOST-WORLD-LAB-NON-RESALE-v1"

    # POST /api/website/download without license -> 403
    h_dl_403 = DummyRequestHandler(
        "/api/website/download",
        {"package_id": "gwl-skills", "platform_os": "windows"},
    )
    anchor_gui.AnchorHandler.do_POST(h_dl_403)
    assert h_dl_403.sent_code == 403
    assert h_dl_403.sent_json["error"] == "license_acceptance_required"

    # POST /api/website/license/accept -> 200
    h_acc = DummyRequestHandler(
        "/api/website/license/accept",
        {"pseudonym_or_handle": "Samwise Gamgee", "accepted_non_resale": True},
    )
    anchor_gui.AnchorHandler.do_POST(h_acc)
    assert h_acc.sent_code == 200
    assert h_acc.sent_json["ok"] is True
    minted_receipt = h_acc.sent_json["receipt"]

    # POST /api/website/download with forbidden anchor-only -> 400
    h_dl_400 = DummyRequestHandler(
        "/api/website/download",
        {"package_id": "anchor-only", "platform_os": "windows", "license_token": minted_receipt},
    )
    anchor_gui.AnchorHandler.do_POST(h_dl_400)
    assert h_dl_400.sent_code == 400
    assert h_dl_400.sent_json["error"] == "anchor_only_forbidden"

    # POST /api/website/download with valid license & package -> 200
    h_dl_200 = DummyRequestHandler(
        "/api/website/download",
        {"package_id": "gwl-anchor-and-skills", "platform_os": "macos", "license_token": minted_receipt},
    )
    anchor_gui.AnchorHandler.do_POST(h_dl_200)
    assert h_dl_200.sent_code == 200
    assert h_dl_200.sent_json["ok"] is True
    assert h_dl_200.sent_json["package_id"] == "gwl-anchor-and-skills"

    # POST /api/website/feedback -> 200 on clean opt-in, 400 on consent=False
    h_fb_400 = DummyRequestHandler(
        "/api/website/feedback",
        {"consent_granted": False, "skill_id": "foreman", "outcome": "friction"},
    )
    anchor_gui.AnchorHandler.do_POST(h_fb_400)
    assert h_fb_400.sent_code == 400

    h_fb_200 = DummyRequestHandler(
        "/api/website/feedback",
        {
            "consent_granted": True,
            "skill_id": "foreman",
            "skill_version": "1.2.4",
            "outcome": "friction",
            "structural_failure_codes": ["timeout"],
            "workaround_codes": ["retry"],
        },
    )
    anchor_gui.AnchorHandler.do_POST(h_fb_200)
    assert h_fb_200.sent_code == 200
    assert h_fb_200.sent_json["ok"] is True
