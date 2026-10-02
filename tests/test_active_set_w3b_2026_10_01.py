"""W3b (his word, 2026-10-01 12:3x): "the tile when they're open shouldn't collapse automatically, I should be able to
dictate in that"; "when I click on the dialog ... take me to the bottom"; "the steward dialog that's automatically up
... you should be at the bottom of that, not the top"; "use my name instead of You". The page renews itself only when no
tile is open and he is quiet; the open tile and his unsent words survive a renewal; the conversation opens at its foot;
his name in the rows on both pages."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402
import test_active_set_w2c_2026_09_30 as w2c  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _turns(n=4):
    return [{"you": i % 2 == 0, "text": "turn %d" % i, "at": "10:%02d" % i, "goal": ""} for i in range(n)]


def test_his_name_in_every_dialogue_row_on_both_pages_and_in_the_boot():
    assert hsp.HIS_NAME == "John"
    ctx = w2c._ctx(); ctx["turns"] = _turns(); ctx["n_turns"] = 4; ctx["stamp"] = "s1"
    html = hsp.render_high_seat_html(ctx)
    ex = html[html.index('<ul class="ex" id="exList"'):html.index("</ul>", html.index('<ul class="ex" id="exList"'))]
    assert ex.count('<div class="exw you">John<span class="t">') == 2 and ">You<" not in ex, "his rows carry his name, the AI Cockpit's way"
    assert 'steward: "Aladdin", stamp: "s1", you: "John"};' in html or 'stamp: "s1", you: "John"};' in html, "the script learns the name from the boot"
    cctx = w2._ctx(); cctx["turns"] = _turns(); cctx["n_turns"] = 4; cctx["stamp"] = "s1"
    cctx["goal_turns"] = {"trusts": [{"you": True, "text": "about the trusts", "at": "10:10"}, {"you": False, "text": "noted", "at": "10:11"}]}
    chtml = cpg.render_campaign_html(cctx, open_id="trusts")
    cex = chtml[chtml.index('<ul class="ex" id="exList"'):chtml.index("</ul>", chtml.index('<ul class="ex" id="exList"'))]
    assert cex.count('<div class="exw you">John<span class="t">') == 2 and ">You<" not in cex
    place = chtml[chtml.index('id="place-trusts"'):chtml.index("</article>", chtml.index('id="place-trusts"'))]
    assert '<div class="exw you">John<span class="t">10:10</span></div>' in place, "the goal's thread too"
    assert 'you: "John"};</script>' in chtml


def test_the_scripts_renew_only_when_no_tile_is_open_and_he_is_quiet_and_keep_the_open_tile():
    hs = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    # the one gate for the record's stamp and a new build
    assert "function typingNow() { var a = document.activeElement; return (Date.now() - lastKey < 10000) || !!(a && a.tagName === 'TEXTAREA' && a.value && a.value.trim()); }" in hs
    assert "function tileOpen() { return !!$('.tile.open'); }" in hs and "function renew(text, key) {\n    var k = key ? String(key) : '';" in hs and "if (tileOpen() || typingNow()) {\n      pendingRenew = text || pendingRenew" in hs
    # once per STAMP, judged per call and only for a stamp (Grok W3b): a new build and the close-the-card renewal are never swallowed
    assert "try { if (k && sessionStorage.getItem('highseat_renewed_for') === k) return; } catch (e) {}" in hs and "var stampKey = k || pendingKey; pendingRenew = null; pendingKey = '';" in hs and "if (stampKey) sessionStorage.setItem('highseat_renewed_for', stampKey);" in hs
    assert "renewKey" not in hs and "renewSaid" not in hs
    assert "function heldLine(card) {" in hs and "card._heldSaid = true; card._talk.appendLine('sys', 'the record moved \\u2014 this page renews itself when you close the card', 'dim');" in hs and "open.forEach(heldLine);" in hs
    assert ".then(function () { if (pendingRenew) heldLine(card); })" in hs and "card._heldSaid = false;" in hs, "a card he switches to hears the held line too, once"
    assert "document.addEventListener('input', markKey, true);" in hs, "dictated text counts as typing"
    assert "you: YOU, onStamp: function (st) { renew('The steward changed the record \\u2014 the page is renewed.', st); }" in hs, "the page's own dialogue renews through the gate"
    assert "renewVersion = String(v); renew('A new build is live \\u2014 the page is renewed.');" in hs and "function typing()" not in hs
    assert "setInterval(function () { if (pendingRenew && !tileOpen() && !typingNow()) renew(pendingRenew); }, 5000);" in hs, "a held renewal finishes when he is quiet"
    assert "if (!another && pendingRenew) renew(pendingRenew);   // the renewal the open tile held back" in hs and "closeTile(c, true); }" in hs
    # in place meanwhile: the open tile's brief and detail, every card's lines and light, the brief's list and the nudge
    assert "open.forEach(function (c) { refreshTile(c, c.getAttribute('data-tile'), openDir(c)); }); else refreshFaces();" in hs
    assert "var b0 = $('#brief'), b1 = doc.getElementById('brief');" in hs and "if (b0 && b1 && !b0.contains(document.activeElement)) {" in hs
    assert "var b = e.target.closest('[data-nudge-act]'); if (!b) return;" in hs, "a nudge re-rendered in place keeps its click (delegated)"
    assert "var b = e.target.closest('.tile[data-tile] [data-part]'); if (!b || b.classList.contains('h-open')) return;" in hs and "$$('[data-part]', card).forEach" not in hs, "a card's act buttons and its wait line's open/see survive a face re-rendered in place (Grok W3b)"
    # the open tile and his words survive a renewal
    assert "sessionStorage.setItem('highseat_open_tile', JSON.stringify({ id: card.id, dir: openDir(card), big: !!big }))" in hs and "function forgetTile()" in hs
    assert "openTile(card, card.getAttribute('data-tile'), kept.dir || '');\n    if (kept.big) grow(card);" in hs
    assert "var DK = 'anchor:draft:tile:' + pid + ':' + (dir || ''), dkT = null;" in hs and "dlg.send(t, null, list, sendBtn, box, DK); }" in hs
    # opening the conversation takes him to its foot; his name in the tile's rows
    assert "if (comp) comp.scrollIntoView({ block: 'end', behavior: 'smooth' }); if (was && ta && document.activeElement !== ta) ta.focus({ preventScroll: true });" in hs
    assert "li.querySelector('.w').textContent = you ? YOU : STEWARD_NAME;" in hs and "(last.classList.contains('you') ? YOU + ': ' : STEWARD_NAME + ': ')" in hs   # by name (2026-10-02)
    assert "var rows = $$('.exrow', list).filter(function (r) { return !r.classList.contains('sysl'); })" in hs, "the strip's gist is the last turn, never the held line"
    cp = open(os.path.join(HERE, "static", "campaign-page.js"), encoding="utf-8").read()
    assert "if (typingNow()) { pendingRenew = text || pendingRenew || 'The record moved \\u2014 the page is renewed.'; if (k) pendingKey = k; return; }" in cp and "if (k && sessionStorage.getItem('campaign_renewed_for') === k) return;" in cp and "if (stampKey) sessionStorage.setItem('campaign_renewed_for', stampKey);" in cp and "renewKey" not in cp
    assert "you: YOU, onStamp: function (st) { renew('The steward changed the record \\u2014 the page is renewed.', st); }" in cp and "function typing()" not in cp
    assert "var b = e.target.closest('[data-nudge-act]'); if (!b) return;" in cp
    m = open(os.path.join(HERE, "static", "steward-dialogue.js"), encoding="utf-8").read()
    assert "YOU = o.you || 'You';" in m and "li.querySelector('.w').textContent = who === 'you' ? YOU : (who === 'st' ? STEWARD : '');" in m
    assert "(function () { var ml = mainList(); if (!ml) return; settle(ml); setTimeout(function () { settle(ml); }, 300); })();" in m, "the dialogue opens at its latest turn"
    for f in ("high-seat-page.js", "campaign-page.js", "steward-dialogue.js"):
        assert subprocess.run(["node", "--check", os.path.join(HERE, "static", f)], capture_output=True, text=True).returncode == 0, f
