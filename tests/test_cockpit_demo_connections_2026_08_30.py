"""Deterministic contract for the empty cockpit connection demo.

The morning slice is intentionally presentation-only: no provider transport,
credentials, account identifiers, mailbox rows, or calendar events.
"""
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from steward_cockpit import steward_routes as routes
from tests.chamber_harness import TEST_TOKEN, boot_server


REPO = Path(__file__).resolve().parent.parent
COCKPIT = REPO / "steward_cockpit" / "static" / "cockpit.html"
DEMO_JS = REPO / "steward_cockpit" / "static" / "connections-demo.js"


def _connection_surface(html: str) -> str:
    start = html.index("<!-- BEGIN SYNTHETIC CONNECTION SURFACES -->")
    end = html.index("<!-- END SYNTHETIC CONNECTION SURFACES -->")
    return html[start:end]


def test_calendar_and_email_are_explicit_empty_synthetic_states():
    html = COCKPIT.read_text(encoding="utf-8")
    surface = _connection_surface(html)

    assert surface.count('data-synthetic-state="empty"') == 2
    assert "No calendar events" in surface
    assert "No email messages" in surface
    assert "does not read a calendar" in surface
    assert "does not read a mailbox" in surface
    assert "data-calendar-event" not in surface
    assert "data-email-message" not in surface


def test_guided_setup_dialog_offers_only_the_two_named_providers():
    html = COCKPIT.read_text(encoding="utf-8")

    assert 'data-setup-dialog hidden' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert html.count('data-connect-provider="gmail"') == 1
    assert html.count('data-connect-provider="outlook"') == 1
    assert "Connect Gmail" in html
    assert "Connect Outlook" in html


def test_connection_preview_has_no_transport_persistence_or_account_payload():
    html = COCKPIT.read_text(encoding="utf-8")
    surface = _connection_surface(html)
    js = DEMO_JS.read_text(encoding="utf-8")

    assert "<input" not in surface
    assert "@" not in surface
    assert "data-account" not in surface
    assert "data-calendar-event" not in surface
    assert "data-email-message" not in surface
    for forbidden in (
            "fetch(", "XMLHttpRequest", "WebSocket", "localStorage",
            "sessionStorage", "document.cookie", "STEWARD_TOKEN",
            "Authorization", "client_secret", "access_token", "refresh_token"):
        assert forbidden not in js


def test_default_served_cockpit_contains_the_demo_and_rewritten_asset():
    html = routes.serve_cockpit_doc("demo-project")

    assert routes._PAGES["cockpit"] == "cockpit.html"
    assert 'window.STEWARD_PID = "demo-project";' in html
    assert 'data-synthetic-state="empty"' in html
    assert 'src="/steward-static/connections-demo.js"' in html


def test_root_workbench_exposes_a_clear_cookie_authenticated_cockpit_link():
    source = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
    start = source.index('id="dashboard-workbench-details"')
    end = source.index('id="tile-tasks"', start)
    workbench = source[start:end]

    assert 'href="/project/__dashboard__"' in workbench
    assert 'iframe src="/project/__dashboard__?classic=1"' in workbench
    assert "Open cockpit" in workbench
    assert "token=" not in workbench
    assert "render_model_prefs_controls()" in source


def test_demo_script_ships_with_the_cockpit_assets():
    manifest = (REPO / "dist_manifest.txt").read_text(encoding="utf-8")

    assert "steward_cockpit/static/connections-demo.js" in manifest
    assert DEMO_JS.is_file()


def test_dashboard_project_defaults_to_cockpit_and_keeps_classic_escape(tmp_path):
    server = boot_server(tmp_path, token=TEST_TOKEN, auth_mode="enforce")
    try:
        base = server["base"] + "/project/__dashboard__"
        with urlopen(base + "?token=" + TEST_TOKEN, timeout=10) as response:
            cockpit = response.read().decode("utf-8")
        with urlopen(base + "?classic=1&token=" + TEST_TOKEN,
                     timeout=10) as response:
            classic = response.read().decode("utf-8")

        assert 'window.STEWARD_PID = "__dashboard__";' in cockpit
        assert "data-connection-surfaces" in cockpit
        assert "Connect Gmail" in cockpit
        assert "Connect Outlook" in cockpit
        assert "project-window.js" not in cockpit

        assert "Project Cockpit" in classic
        assert "id='tile-workbench'" in classic
        assert "data-connection-surfaces" not in classic
        assert "window.STEWARD_PID" not in classic
    finally:
        server["stop"]()


def test_setup_popup_is_an_interactive_local_only_preview(tmp_path):
    server = boot_server(tmp_path, token=TEST_TOKEN, auth_mode="enforce")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.route("**/api/**", lambda route: route.fulfill(
                status=200, content_type="application/json", body="{}"))
            page.goto(server["base"] + "/project/__dashboard__?token=" +
                      TEST_TOKEN, wait_until="domcontentloaded")

            dialog = page.locator("[data-setup-dialog]")
            expect(dialog).to_be_hidden()
            page.locator("[data-tile-calendar] [data-connect-open]").click()
            expect(dialog).to_be_visible()
            assert page.evaluate(
                "document.activeElement.dataset.connectProvider") == "gmail"

            page.locator('[data-connect-provider="outlook"]').click()
            expect(page.locator("[data-setup-notice]")).to_contain_text(
                "guided preview only")
            expect(page.locator("[data-calendar-empty]")).to_be_visible()
            expect(page.locator("[data-email-empty]")).to_be_visible()

            page.keyboard.press("Escape")
            expect(dialog).to_be_hidden()
            context.close()
            browser.close()
    finally:
        server["stop"]()
