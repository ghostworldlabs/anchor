"""R14 (John, 2026-09-29, "I try and set the token (click that button) and nothing happens"): the token is pasted
INTO the page — the High Seat's login box and the old dashboard's token modal — never into a browser pop-up, which
his desktop browser suppressed."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anchor_gui  # noqa: E402
import high_seat_page as hsp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_high_seat_has_a_login_box_and_no_browser_prompt():
    js = open(os.path.join(ROOT, "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "window.prompt(" not in js, "no browser pop-up anywhere on the High Seat"
    assert "function showLogin(" in js and "function doLogin()" in js and "loginGo.addEventListener('click', doLogin)" in js
    assert "window.ANCHOR_BOOT.auth_required && !token() && !window.ANCHOR_BOOT.logged_in) showLogin('')" in js, "the box opens on load when a token is required and none is held"
    assert "'That token was refused" in js and "localStorage.removeItem('anchor_token')" in js, "a refused token is said and forgotten"
    css = open(os.path.join(ROOT, "static", "steward-dialogue.css"), encoding="utf-8").read()
    assert ".loginbox{" in css, "the box's look lives with the dialogue: both pages mount it (Grok's read of W2c-3)"
    assert ".loginbox{" not in open(os.path.join(ROOT, "static", "high-seat-page.css"), encoding="utf-8").read(), "one copy"


def test_the_page_carries_the_box_and_tells_the_script_whether_a_token_is_required():
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import test_high_seat_page_2026_09_26 as t
    ctx = t._ctx(); ctx["auth_required"] = True
    html = hsp.render_high_seat_html(ctx)
    assert '<div class="loginbox" id="loginBox" hidden>' in html and 'id="loginTok" type="password"' in html and 'id="loginGo"' in html
    assert "auth_required: true" in html
    ctx["auth_required"] = False
    assert "auth_required: false" in hsp.render_high_seat_html(ctx)
    src = inspect.getsource(anchor_gui._high_seat_context)
    assert '"auth_required": bool(_paths.expected_token())' in src


def test_the_old_dashboard_uses_a_modal_never_a_prompt():
    src = inspect.getsource(anchor_gui.generate_html)
    assert 'id="tokenModal"' in src and 'id="tokenInput"' in src and "function saveAnchorToken()" in src
    body = src.split("function setAnchorToken(opts)")[1].split("function saveAnchorToken()")[0]
    assert "window.prompt(" not in body, "the token modal replaced the browser prompt"
    assert "return false;" in body and "modal.classList.add('open')" in body
    assert "inp.value = rejected ? '' : cur;" in body, "a rejected token is never offered back"
