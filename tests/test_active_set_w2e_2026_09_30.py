"""W2e the card's cockpit (2026-09-30 14:1x, his words on the Cave of Wonders): "anything on the Cave of Wonders, active
or on deck … I should have a light … green light working, red light there's a problem, gray light idle, orange light
needs attention … when Artificial Magi is done it should flash … a little thin line around the edge … a gentle pulse
saying hey, this is ready for you … open it up and interact from the Cave of Wonders level within the expanded tile …
the current dialogue with the steward that's happening inside the cockpit … interject there … deliverables … next
steps". And his cockpit's "not delivered - your text is back in the box": a send that cannot reach the steward is kept."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import high_seat_page as hsp  # noqa: E402
import test_active_set_w2c_2026_09_30 as w2c  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MBA = "6765ece4b3bc43b0b0b0907b92b17280"


def test_every_project_has_a_light_in_his_words(tmp_path):
    import anchor_gui as ag
    folders = {}
    for name, state in (("a", "working"), ("b", "needs_you"), ("c", "blocked"), ("d", "")):
        d = tmp_path / name; (d / ".ecgberht").mkdir(parents=True); folders[name] = str(d)
        if state:
            (d / ".ecgberht" / "attention.json").write_text(json.dumps({"state": state, "reason": "the reason for " + name}), encoding="utf-8")
    entries = [{"id": n, "folder_path": folders[n]} for n in ("a", "b", "c", "d")] + [{"id": "e", "folder_path": str(tmp_path / "nowhere")}]
    facts = {"d": {"needs_you": "approve the draft"}, "e": {}}
    lights = ag._project_lights(entries, facts, working={"e"})
    assert lights["a"] == {"light": "green", "word": "working", "why": "the reason for a"}
    assert lights["b"] == {"light": "orange", "word": "needs you", "why": "the reason for b"}
    assert lights["c"]["light"] == "red" and lights["c"]["word"] == "a problem"
    assert lights["d"] == {"light": "orange", "word": "needs you", "why": "approve the draft"}, "the wait the facts carry is the orange"
    assert lights["e"] == {"light": "green", "word": "working", "why": ""}, "a running session is working; no record file is fine"


def test_the_card_carries_its_light_the_ready_mark_and_the_talk_act():
    ctx = w2c._ctx()
    ctx["lights"] = {MBA: {"light": "orange", "word": "needs you", "why": "approve the Lecture 3 AI supplement"}}
    html = hsp.render_high_seat_html(ctx)
    active = html[html.index('id="shActive"'):html.index('id="shDeck"')]
    card = active[active.index('id="card-%s"' % MBA):active.index("</article>")]
    assert '<span class="tlight orange" title="needs you: approve the Lecture 3 AI supplement"></span><h3 class="t-name">' in card, "the light in his words, before the name"
    assert 'data-ready="' in card, "a wait he has not looked at is marked, by the wait's own words"
    assert '<button data-part="talk" data-pid="%s" data-dir="">Talk</button>' % MBA in card, "the cockpit's dialogue, in the card"
    eff = active[active.index('id="card-%s-mba-lectures"' % MBA):]
    assert '<button data-part="talk" data-pid="%s" data-dir="lectures">Talk</button>' % MBA in eff, "an effort's card talks to that effort's steward"
    assert 'class="tlight orange"' in eff, "the light is the project's until the effort has its own record"
    ctx["lights"] = {MBA: {"light": "green", "word": "working", "why": ""}}
    html = hsp.render_high_seat_html(ctx)
    card = html[html.index('id="card-%s"' % MBA):html.index("</article>", html.index('id="card-%s"' % MBA))]
    assert 'class="tlight green" title="working"' in card and "data-ready" not in card, "working: no mark"
    ctx["lights"] = {}
    html = hsp.render_high_seat_html(ctx)
    card = html[html.index('id="card-%s"' % MBA):html.index("</article>", html.index('id="card-%s"' % MBA))]
    assert 'class="tlight gray" title="idle"' in card, "no light known: idle, said so"


def test_the_script_opens_the_cockpit_s_dialogue_in_the_card_and_marks_the_look():
    js = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    for s in ("function openTalk(card, pid, dir, btn, key)", "if (part === 'talk') { openTalk(card, pid, dir, btn, key); return; }", "stopTalk(card); seen(card);",
              "window.StewardDialogue.init({ pid: pid, dir: dir, headers: headers, receipt: receipt, receiptKey: 'highseat_receipt', list: '#' + id + ' .ex', state: '#' + id + ' .exstate'",
              "'/api/steward/history?pid=' + encodeURIComponent(pid) + '&dir=' + encodeURIComponent(dir) + tokenQ2()", "c.classList.add('ready')", "localStorage.setItem('hs_seen_' + card.id, tok)"):
        assert s in js, s
    dlg = open(os.path.join(HERE, "static", "steward-dialogue.js"), encoding="utf-8").read()
    assert "function stop() { live.stopped = true; }" in dlg and "if (live.stopped) { live.polling = false; return; }" in dlg and "stop: stop" in dlg, "a card's dialogue stops when the card closes"
    for f in ("high-seat-page.js", "steward-dialogue.js"):
        r = subprocess.run(["node", "--check", os.path.join(HERE, "static", f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    css = open(os.path.join(HERE, "static", "high-seat-page.css"), encoding="utf-8").read()
    for s in (".tlight.green{", ".tlight.orange{", ".tlight.red{", ".tile.ready{animation:readyedge", ".cdlg .scroll{max-height:42vh"):
        assert s in css, s


def test_a_send_that_cannot_reach_the_steward_is_kept_and_goes_when_it_wakes(tmp_path, monkeypatch):
    from steward_cockpit import steward_engine
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    (tmp_path / ".ecgberht").mkdir()
    eng = steward_engine.Engine(str(tmp_path), fake=True, general=False, tid=None)
    monkeypatch.setattr(eng, "alive", lambda: True)
    eng.busy = False
    monkeypatch.setattr(eng, "_attention", lambda: {})
    monkeypatch.setattr(eng, "_record_conversation", lambda *a, **k: True)
    monkeypatch.setattr(eng, "_send_locked", lambda *a, **k: False)
    r = eng.say("keep the images in the homework instructions")
    assert r == {"ok": True, "queued": True, "kept": True}, "never 'not delivered': the text is kept"
    assert eng.queue and eng.queue[-1].startswith("keep the images")
    assert steward_engine._read_state_entry(eng.skey()).get("pending_queue") == list(eng.queue), "kept durably: it goes when the steward wakes"
    assert any(ev.get("t") == "sys" and "kept and goes when the steward wakes" in str(ev.get("text")) for ev in eng.events)
