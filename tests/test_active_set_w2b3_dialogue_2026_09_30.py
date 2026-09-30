"""W2b-3 of the active set (2026-09-30) - the Campaign page's DIALOGUE. His word: he spoke to the Campaign's steward
and "it didn't do anything. That dialogue should open up and fill the whole open space on the right below the brief,
it should be interactive and able for me to follow what is going on, ask, discuss". What the service log showed: his
sends came from a tab older than the server's build (the build-mismatch 409 - the page had no watch for a new build)
and the Campaign's steward was parked with one of his messages kept for it. So: the column is the brief, the composer
under it, then the dialogue filling the rest - the one log (the last 40 turns, a goal's chip on a turn said from a
goal's place), live from the open (the cockpit's own stream and its own soft start), with the steward's state at its
head; a build other than the page's reloads it once, never while he types; a refused send is said in the dialogue."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import test_active_set_w1_2026_09_29 as w1  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402

W = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _turns(n):
    out = []
    for k in range(n):
        out.append({"you": k % 2 == 0, "text": "turn %d" % k, "at": "10:%02d" % (k % 60), "goal": "trusts" if k % 5 == 0 else ""})
    return out


def test_the_panel_is_the_brief_the_composer_then_the_dialogue_of_the_whole_log():
    ctx = w2._ctx(w1._steps())
    ctx["turns"] = _turns(45)[-40:]; ctx["n_turns"] = 45; ctx["goal_names"] = {"trusts": "The trusts and the holding company"}
    html = cpg.render_campaign_html(ctx)
    panel = html[html.index('<aside class="panel"'):html.index("</aside>")]
    assert panel.index('id="brief"') < panel.index('class="composer"') < panel.index('id="dialogue"'), "brief, composer, then the dialogue"
    assert panel.count('class="exrow') == 40 and "the last 40 of 45" in panel, "the last 40 turns of the log, and said so"
    assert 'class="gchip" data-open="trusts"' in panel and "about The trusts and the holding company" in panel, "a turn said from a goal's place carries the goal's chip, which opens the goal"
    assert 'id="exState"' in panel and 'id="exScroll"' in panel, "the steward's state at the head; the list scrolls inside"
    assert "exfade" not in panel
    assert 'steward: "Ecgberht"' in html or 'steward: "' in html, "the boot carries the steward's label for the live lines"
    ctx["turns"] = []; ctx["n_turns"] = 0
    html = cpg.render_campaign_html(ctx)
    assert "Nothing said here yet" in html and "the same conversation as the Campaign" in html


def test_the_script_is_live_from_the_open_watches_the_build_and_says_a_refusal():
    js = open(os.path.join(W, "static", "campaign-page.js"), encoding="utf-8").read()
    assert "primeSeq().then(pollLoop)" in js, "the stream is polled from the moment the page opens"
    assert "'/api/version'" in js and "campaign_reloaded_for" in js and "typing()" in js, "a new build reloads the page once, never while he types"
    assert "'build-mismatch'" in js and "renewed" in js, "a send from a stale tab renews the page and keeps the draft"
    assert "function catchUp" in js and "/api/steward/history" in js, "a turn that ended before the page saw its words is read from the log"
    assert "showState(j.state)" in js and "parked" in js and "listening" in js, "the steward's state from the same poll"
    assert "pair.mi = put(main" in js, "a line sent from a goal's brainstorm lands in the panel's dialogue too (one log, two views)"
    assert "Not sent \\u2014" in js or "Not sent —" in js, "a refused send is said in the dialogue, not only in the receipt"
    assert "a page view never" not in js
    r = subprocess.run(["node", "--check", os.path.join(W, "static", "campaign-page.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    css = open(os.path.join(W, "static", "campaign-page.css"), encoding="utf-8").read()
    assert ".panel{display:flex;flex-direction:column;min-height:0;overflow:hidden" in css, "the column does not scroll as a whole"
    assert ".exwrap{flex:1 1 auto" in css and ".exwrap .scroll{flex:1 1 auto;min-height:0;overflow-y:auto}" in css, "the dialogue fills the column and scrolls inside"
    assert '.exstate[data-state="busy"]' in css and ".gchip{" in css
