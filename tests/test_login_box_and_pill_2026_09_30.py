"""W2c-4 (2026-09-30, his words): "I am logged into Anchor, but there is still that 'browser not logged in to Anchor'
tile below the brief … That tile should disappear when Anchor is logged in." and "top upper right corner, what is that
AI Cockpit tile … we can get rid of that tile." The server knows a logged-in browser by its login cookie; the page learns
it from the boot and shows its box only when the request was not logged in. The pill leaves the masthead; the footer
keeps the tagline. And a draft in a box no longer pins a stale page: the build watch waits only while he types."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import high_seat_page as hsp  # noqa: E402
import test_high_seat_page_2026_09_26 as base  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_boot_says_whether_this_request_was_logged_in_and_the_box_follows_it():
    ctx = base._ctx(); ctx["auth_required"] = True; ctx["logged_in"] = True
    html = hsp.render_high_seat_html(ctx)
    assert "auth_required: true, logged_in: true," in html and 'id="loginBox" hidden' in html
    ctx["logged_in"] = False
    assert "auth_required: true, logged_in: false," in hsp.render_high_seat_html(ctx)
    js = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    assert "if (window.ANCHOR_BOOT && window.ANCHOR_BOOT.auth_required && !token() && !window.ANCHOR_BOOT.logged_in) showLogin('');" in js, "the box only when the server did not know this browser"
    src = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    assert src.count("render_high_seat_page(logged_in=self._term_token_ok())") == 2, "both routes tell the page (the same gate the reads use: query token, Authorization, the cookie)"
    assert 'ctx["logged_in"] = bool(logged_in)' in src


def test_the_ai_cockpit_pill_left_the_masthead_and_the_footer_keeps_the_tagline():
    html = hsp.render_high_seat_html(base._ctx())
    head = html[:html.index('<div class="canvas">')]
    assert "mh-pill" not in head and "AI Cockpit" not in head
    assert "Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty" in html, "the tagline stays in the footer (never scrubbed)"
    import campaign_page as cpg, test_active_set_w1_2026_09_29 as w1, test_active_set_w2_2026_09_29 as w2
    chtml = cpg.render_campaign_html(w2._ctx(w1._steps()))
    assert "mh-pill" not in chtml[:chtml.index('<div class="canvas">')] and "AI Cockpit &middot; J.C. Liechty" in chtml


def test_a_draft_never_pins_a_stale_page():
    for f in ("high-seat-page.js", "campaign-page.js"):
        js = open(os.path.join(HERE, "static", f), encoding="utf-8").read()
        assert "function typing() { return Date.now() - lastKey < 10000; }" in js and "document.addEventListener('keydown', function () { lastKey = Date.now(); });" in js, f
        assert "(a.value || '').trim()" not in js, "the old rule (a box holding text) is gone: it pinned a tab with a draft to the old build"
