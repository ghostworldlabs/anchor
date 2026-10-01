"""W2e the card's cockpit (2026-09-30 14:1x, his words on the Cave of Wonders): "anything on the Cave of Wonders, active
or on deck … I should have a light … green light working, red light there's a problem, gray light idle, orange light
needs attention … when Artificial Magi is done it should flash … a little thin line around the edge … a gentle pulse
saying hey, this is ready for you … open it up and interact from the Cave of Wonders level within the expanded tile …
the current dialogue with the steward that's happening inside the cockpit … interject there … deliverables … next
steps". W2e-2, his word on the preview (14:5x): "there should be a little window for dialogue and if you start a
dialogue then that expands … there should always be the key material, summary of the decision — with a recommendation,
a link to anything that needs to be reviewed … The user should not have to go and hunt". And his cockpit's "not
delivered - your text is back in the box": a send while the steward cannot wake is kept. W2e-3, his word on the
opened tile (15:2x): "you could just have that red banner with the top line request and if it is clicked on you get the
description and recommendation, which can be clicked on or you can click on a talk about it link"; the banner "can be a
tile/rectangle on the left of the top of the open tile"; then (16:0x) "up on the same level as the in, run and next
section, but over on the right side … the cockpit steward dialogue should be able to expand with a click on a very thin
tile, but I want the context of the first web page there first". W2e-6 (19:0x): "add the ability to drop in a file in an
initiative tile (when it is opened, made large) so that it will end up in the associated project (like the AI Cockpit
feature)" - the open tile takes a file drop through the cockpit's own upload verb into the opened cockpit's folder.
W2e-7 (19:1x): the dots mapped wrong (two busy cockpits gray, an open question gray) - a seated card's dot is its OWN
cockpit's light, the cockpit's source and palette; the dialogue rows take the cockpit's colours. W2e-8 (19:2x): "status
for the expanded tile is not keeping up" - the open tile re-reads itself when the record's stamp moves."""
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


def test_every_project_has_a_light_in_his_words(tmp_path, monkeypatch):
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
    assert lights["c"] == {"light": "orange", "word": "needs you", "why": "the reason for c"}, "blocked = waiting on an answer: orange, as the cockpit says it (W2e-7)"
    assert lights["d"] == {"light": "orange", "word": "needs you", "why": "approve the draft"}, "the wait the facts carry is the orange"
    assert lights["e"] == {"light": "green", "word": "working", "why": ""}, "a running session is working; no record file is fine"
    # W2e-7 (his word: the dots did not map): a SEATED card takes its own cockpit's light - the cockpit's source, by directory
    (tmp_path / "a" / "lec").mkdir()
    seen = []
    def fake_engine_light(cdir):
        seen.append(str(cdir)); base = os.path.basename(str(cdir))
        return {"a": {"light": "green", "question": ""}, "lec": {"light": "quiet", "question": ""}, "d": {"light": "quiet", "question": ""}, "c": {"light": "red", "question": ""}, "b": {"light": "orange", "question": "Accept the draft?"}}.get(base, {"light": "", "question": ""})
    monkeypatch.setattr(ag, "_engine_light", fake_engine_light)
    lights = ag._project_lights(entries, facts, working=set(), seats=[("a", ""), ("a", "lec"), ("c", ""), ("d", ""), ("b", "")])
    assert lights["a"] == {"light": "green", "word": "working", "why": "the reason for a"}, "the engine says working: green even with no session in the working set"
    assert lights["a|lec"] == {"light": "gray", "word": "idle", "why": ""}, "the effort's OWN cockpit is quiet: gray, whatever the project's flag says"
    assert lights["c"] == {"light": "red", "word": "a problem", "why": "the reason for c"}, "the engine's red leads"
    assert lights["d"] == {"light": "orange", "word": "needs you", "why": "approve the draft"}, "quiet engine, but the record carries a wait: the dot never contradicts the card's line"
    assert lights["b"] == {"light": "orange", "word": "needs you", "why": "Accept the draft?"}, "the cockpit's open question is the reason, as the cockpit shows it"
    assert sorted(os.path.basename(x) for x in seen) == ["a", "b", "c", "d", "lec"], "the engine asked once per seated card, never for the unseated"
    assert lights["e"]["light"] == "gray", "an unseated project keeps the record-only rule"


def test_the_card_carries_its_light_and_the_ready_mark_and_the_acts_are_the_details():
    ctx = w2c._ctx()
    ctx["lights"] = {MBA: {"light": "orange", "word": "needs you", "why": "approve the Lecture 3 AI supplement"}, MBA + "|lectures": {"light": "green", "word": "working", "why": "lecture 4"}}
    html = hsp.render_high_seat_html(ctx)
    active = html[html.index('id="shActive"'):html.index('id="shDeck"')]
    card = active[active.index('id="card-%s"' % MBA):active.index("</article>")]
    assert '<span class="tlight orange" title="needs you: approve the Lecture 3 AI supplement"></span><h3 class="t-name">' in card, "the light in his words, before the name"
    assert 'data-ready="' in card, "a wait he has not looked at is marked, by the wait's own words"
    assert 'data-part="talk"' not in card and 'data-part="plan"' in card, "the dialogue is always in the opened tile (W2e-2); the acts are the details"
    assert '</div><div class="t-face"><div class="t-goal">' in card and '</div></div><div class="t-acts">' in card, "the card's own lines wrapped, so the opened tile lays the rectangle beside them (W2e-4)"
    eff = active[active.index('id="card-%s-mba-lectures"' % MBA):]
    assert 'data-part="plan" data-pid="%s" data-dir="lectures"' % MBA in eff and 'class="tlight green" title="working: lecture 4"' in eff, "an effort's card takes ITS OWN cockpit's light, keyed by its directory (W2e-7), not the project's wait"
    deck = html[html.index('id="shDeck"'):html.index('id="ptile"')]
    assert '<article class="tile desk" id="card-hw" data-step="hw" data-name="retool homework 2" draggable="true"><div class="t-top"><span class="tlight gray" title="idle"></span>' in deck, "a desk card has a light too (Grok W2e)"
    ctx["lights"] = {MBA: {"light": "green", "word": "working", "why": ""}}
    html = hsp.render_high_seat_html(ctx)
    card = html[html.index('id="card-%s"' % MBA):html.index("</article>", html.index('id="card-%s"' % MBA))]
    assert 'class="tlight green" title="working"' in card and "data-ready" not in card, "working: no mark"
    ctx["lights"] = {}
    html = hsp.render_high_seat_html(ctx)
    card = html[html.index('id="card-%s"' % MBA):html.index("</article>", html.index('id="card-%s"' % MBA))]
    assert 'class="tlight gray" title="idle"' in card, "no light known: idle, said so"


def test_the_decision_brief_is_the_key_material_in_one_place(tmp_path, monkeypatch):
    from steward_cockpit import high_seat_card as hc, steward_engine
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    proj = tmp_path / "Magi"; (proj / ".ecgberht").mkdir(parents=True)
    (proj / "ECGBERHT.md").write_text("# Artificial Magi\n", encoding="utf-8")
    (proj / "roadmap.json").write_text(json.dumps({"roadmap_events": [], "roadmap_projection": [{"id": "ch2", "name": "Chapter 2", "status": "waiting", "waiting_on": "John"}]}), encoding="utf-8")
    (proj / "strip.json").write_text(json.dumps({"human_wait": "John: read the chapter 2 revision · since 10:00", "next_recommended": "Chapter 3 outline"}), encoding="utf-8")
    steward_engine._update_state(str(proj), {"question_context": {"question": "Accept the chapter 2 revision?", "context": "The pacing dragged in v2. The scenes now land in v3. Accept the chapter 2 revision? I recommend accepting it; the pacing is fixed.", "recommendation": "I recommend accepting it; the pacing is fixed", "why": "the scenes now land", "asked_at": 1790800000.0,
                                                                     "authorization_scope": {"request_id": "q1", "members": ["drafts/chapter-2-v3.md"]}, "alternatives": ["hold for one more pass"]}})
    r = hc.card_part("p-magi", "brief", str(proj), "Artificial Magi", "")
    assert r["ok"] and r["part"] == "brief"
    h = r["html"]
    assert '<div class="cbrief ask">' in h, "the brief is the red rectangle when something is asked"
    assert '<button class="cb-ask" type="button" aria-expanded="false"><span class="cb-flag">decision</span><span class="cb-line">Accept the chapter 2 revision?</span>' in h, "the ask as the cockpit's banner: one line, the question"
    body = h[h.index('<div class="cb-body" hidden>'):h.index('<div class="cb-next">')]   # the banner's body, before the next line and the To review line
    assert '<div class="cb-desc">The pacing dragged in v2. The scenes now land in v3.</div>' in body, "the description: the sentences the question stands on"
    assert "&#9873; John: read the chapter 2 revision" in body, "the wait, when it is not the ask itself"
    import re as _re
    assert _re.search(r'class="cb-accept" type="button" data-qid="[^"]+" data-rec="I recommend accepting it; the pacing is fixed"', body) and "the scenes now land" in body, "one Accept (the question's own stable id), the recommendation and its why"
    assert 'href="/api/steward/deliverable-file?pid=p-magi&amp;dir=&amp;path=drafts/chapter-2-v3.md"' in h and ">chapter-2-v3.md</a>" in h, "the material to review, as a link"
    assert "cb-mat" not in h and h.index('<div class="cmat"><span class="k">To review</span>') > h.index("</div>", h.index('<div class="cb-next">')), "W2e-5: the material on its own line after the rectangle (under the dialogue's strip on the tile)"
    assert "or: hold for one more pass" in body and '<a class="cb-talk" href="#" data-ask="Accept the chapter 2 revision?">talk about it</a>' in body and "To review" not in body
    assert '<span class="k">Next</span>Chapter 3 outline' in h
    steward_engine._update_state(str(proj), {"question_context": None})
    h2 = hc.card_part("p-magi", "brief", str(proj), "Artificial Magi", "")["html"]
    assert '<span class="cb-flag">needs you</span><span class="cb-line">John: read the chapter 2 revision</span>' in h2 and "cb-accept" not in h2, "no open question: the wait is the ask, no recommendation"
    (proj / "strip.json").write_text(json.dumps({"human_wait": "", "next_recommended": "Chapter 3 outline"}), encoding="utf-8")
    h3 = hc.card_part("p-magi", "brief", str(proj), "Artificial Magi", "")["html"]
    assert '<div class="cbrief">' in h3 and "Nothing waits on you here." in h3 and "cb-ask" not in h3
    assert hc.card_part("p-magi", "nope", str(proj), "Artificial Magi", "")["ok"] is False


def test_the_script_opens_the_tile_to_its_brief_and_dialogue_and_the_dialogue_grows():
    js = open(os.path.join(HERE, "static", "high-seat-page.js"), encoding="utf-8").read()
    for s in ("function openTile(card, pid, dir)", "fetchPart(pid, 'brief', dir, false, true)", "function closeTile(card)", "function startTalk(card, pid, dir)", "function stopTalk(card)",
              "if (!card.classList.contains('open')) openTile(card, pid, dir);", "var det = $('.cdetail', card);",
              "function grow(card) { var d = $('.cdlg', card); if (d) { d.classList.remove('thin'); d.classList.add('big');", "function shrink(card)",
              '<div class="cdlg thin" id="', 'class="dlg-bar"', 'class="dlg-gist"', "function gist() {", "if (bar) bar.addEventListener('click', function (e) { e.stopPropagation(); if ($('.cdlg', card).classList.contains('thin')) grow(card); else shrink(card); });",
              "loginBox({ receiptKey: 'highseat_receipt' })", "if (j.kept) { b.disabled = false;", "else if ((card.getAttribute('data-open-dir') || '') !== dir) { closeTile(card); openTile(card, pid, dir); }",
              "if (e && e.auth) showLogin('This cockpit", "function isFileDrag(e)", "fetch('/api/steward/upload', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: pid, dir: dir, name: f.name, data_b64: b64, mode: 'new', sub: '' }) })",
              "if (f.size > 30000000)", "card.classList.add('dropping')", "function refreshTile(card, pid, dir)", "onStamp: function () { refreshTile(card, pid, dir); }",
              "new DOMParser().parseFromString(html, 'text/html')", "if (f0 && f1 && f0.innerHTML !== f1.innerHTML) f0.innerHTML = f1.innerHTML;", "fetchPart(pid, 'brief', dir, false, false)", "if (drag || !isFileDrag(e) || !card.classList.contains('open')) return;", "if (!e.target.closest('.tile.open')) receipt('Open a card first",
              "e.target.closest('.cb-accept')", "question_id: b.getAttribute('data-qid') || null", "text: 'Accept recommendation: ' + (b.getAttribute('data-rec') || '')",
              "if (card.classList.contains('open')) closeTile(card); else openTile(card, pid, card.getAttribute('data-dir') || '');",
              "window.StewardDialogue.init({ pid: pid, dir: dir, headers: headers, receipt: receipt, receiptKey: 'highseat_receipt', list: '#' + id + ' .ex', state: '#' + id + ' .exstate'",
              "c.classList.add('ready')", "localStorage.setItem('hs_seen_' + card.id, tok)",
              "var a = e.target.closest('.cb-ask');", "var t = e.target.closest('.cb-talk');", "box.value = 'About: ' + (t.getAttribute('data-ask') || '')",
              "$$('.tile.open').forEach(function (c) { if (c !== card) closeTile(c); });", "window.StewardDialogue.authHeaders(headers())"):
        assert s in js, s
    assert "openTalk" not in js and "part === 'talk'" not in js and "tokenQ2" not in js, "one token helper, the module's (Grok W2e)"
    assert js.count("function stopTalk(card)") == 1 and "function doLogin()" not in js, "one stopTalk (Grok W2e-3 cut the dead one); the login script is the module's"
    assert "=== 'busy') grow(card)" not in js and "card.getAttribute('data-open-dir') !== null ? card.getAttribute('data-open-dir')" in js and "var f = $('.exfade', list); g.textContent = f ? f.textContent.trim()" in js, "Grok W2e-4: the strip opens on his acts only; Accept goes to the opened cockpit; the gist carries the list's one sentence"
    dlg = open(os.path.join(HERE, "static", "steward-dialogue.js"), encoding="utf-8").read()
    assert "function stop() { live.stopped = true; }" in dlg and "if (live.stopped) { live.polling = false; return; }" in dlg and "stop: stop" in dlg, "a tile's dialogue stops when the tile closes"
    assert "if (j.kept) appendLine('sys', 'the steward could not wake just now" in dlg and "init: init, authHeaders: authHeaders" in dlg, "a kept send is said as kept (Grok W2e); the token helper is the module's"
    assert "if (j.stamp && !BOOT_STAMP && o.onStamp) BOOT_STAMP = j.stamp;" in dlg and "if (o.onStamp) { BOOT_STAMP = j.stamp; try { o.onStamp(j.stamp); } catch (err) {} }" in dlg, "a tile's dialogue learns the stamp and calls back; the pages keep the reload (W2e-8)"
    dcss = open(os.path.join(HERE, "static", "steward-dialogue.css"), encoding="utf-8").read()
    for s in (".exw.you{color:#e8c268}", ".exw.st{color:#6c9cfc}", ".ext{font-size:15px", '.exstate[data-state="busy"]{color:#4ade80}', '.exstate[data-state="idle"]{color:#8995a7}'):
        assert s in dcss, s + " - the cockpit's palette (W2e-7)"
    for f in ("high-seat-page.js", "steward-dialogue.js"):
        r = subprocess.run(["node", "--check", os.path.join(HERE, "static", f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    css = open(os.path.join(HERE, "static", "high-seat-page.css"), encoding="utf-8").read()
    for s in (".tlight.green{background:#4ade80", ".tlight.orange{background:#fbbf24", ".tlight.red{background:#e05f5f", ".tlight.gray{background:#8995a7", ".tile.ready{animation:readyedge", ".cbrief{", ".cbrief.ask{", ".cb-ask{", ".cb-accept{", ".cb-talk{",
              '.tile.open{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,42%);grid-template-areas:"top top" "face brief" "acts brief" "detail detail" "dlg dlg"', ".tile.open>.t-face{grid-area:face}", ".tile.open>.t-body{display:contents}", ".tile.open .cbrief{grid-area:brief",
              ".cdlg .dlg-bar{", ".cdlg .dlg-gist{", ".cdlg.thin .scroll,.cdlg.thin .composer{display:none}", '"dlg dlg" "mat mat" "drop drop"', ".tile.open .cmat{grid-area:mat}", ".tile.open .cdrop{grid-area:drop}", ".cdrop{", ".tile.open.dropping{outline:2px dashed",
              ".cdlg .scroll{max-height:20vh", ".cdlg.big .scroll{max-height:58vh}", ".tile.talking .cdetail{display:none}"):
        assert s in css, s


def test_a_send_that_cannot_reach_the_steward_is_kept_and_goes_when_it_wakes(tmp_path, monkeypatch):
    from steward_cockpit import steward_engine
    monkeypatch.setattr(steward_engine, "STATE_FILE", tmp_path / "state.json")
    (tmp_path / ".ecgberht").mkdir()
    eng = steward_engine.Engine(str(tmp_path), fake=True, general=False, tid=None)
    monkeypatch.setattr(eng, "alive", lambda: False)
    monkeypatch.setattr(eng, "wake", lambda *a, **k: (False, "chatgpt CLI not found"))
    monkeypatch.setattr(eng, "_record_conversation", lambda *a, **k: True)
    r = eng.say("keep the images in the homework instructions")
    assert r == {"ok": True, "queued": True, "kept": True}, "a wake that failed keeps his words: never 'not delivered'"
    assert eng.queue and eng.queue[-1].startswith("keep the images")
    assert steward_engine._read_state_entry(eng.skey()).get("pending_queue") == list(eng.queue), "kept durably: it goes on the next wake"
    assert any(ev.get("t") == "sys" and "kept and goes when it wakes" in str(ev.get("text")) and "chatgpt CLI not found" in str(ev.get("text")) for ev in eng.events)
    # a live steward whose pipe fails answers not delivered - a queue on an awake, idle steward would never drain (Grok W2e)
    monkeypatch.setattr(eng, "alive", lambda: True); eng.busy = False
    monkeypatch.setattr(eng, "_attention", lambda: {})
    monkeypatch.setattr(eng, "_send_locked", lambda *a, **k: False)
    assert eng.say("and the tables") == {"ok": False, "error": "delivery failed - your text was not sent"}
