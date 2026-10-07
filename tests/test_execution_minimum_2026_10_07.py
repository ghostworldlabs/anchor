"""The execution minimum set (PROPOSAL v1.1, 2026-10-07). Item 1: Next steps stable and complete, the narrow cockpit,
open at the newest message. Hermetic: a throwaway server on a free port with a temp data dir (never :8777)."""
import time

from playwright.sync_api import expect

from steward_cockpit import steward_campaign as sc
from tests.test_steward_refinement_browser import campaign_server, cockpit
from tests.test_cockpit_selected_b import open_surface


# ---------- item 1: every current product is its own row; the formats of one product are one row ----------

def test_format_tags_strip_every_spelling_the_registers_use():
    for raw, want in [("NYU Viva quick start - Refinement 1 MD", "NYU Viva quick start - Refinement 1"),
                      ("Quiz 1 - Bank - Draft 3 (PDF)", "Quiz 1 - Bank - Draft 3"),
                      ("Quiz 1 - Bank - Draft 3 (browser)", "Quiz 1 - Bank - Draft 3"),
                      ("Verification, Draft 1 (browser reading)", "Verification, Draft 1"),
                      ("Instructor Materials (TA download)", "Instructor Materials"),
                      ("Quiz-1-Viva-Guide-PDF", "Quiz-1-Viva-Guide"),
                      ("Teaching-Calendar-Report", "Teaching-Calendar-Report"),
                      ("Thermopdf", "Thermopdf")]:          # a word that merely ends in a format name keeps it
        assert sc._strip_format_tag(raw) == want, raw


def test_review_acts_one_row_per_product_with_companions():
    items = [
        {"what": "Guide - Refinement 1 MD", "path": "q/Guide - Refinement 1.md", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Refinement 1 PDF", "path": "q/Guide - Refinement 1.pdf", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Refinement 1 HTML", "path": "q/Guide - Refinement 1.html", "step": "s1", "date": "2026-10-07"},
        {"what": "Calendar (accepted).ics", "path": "q/Calendar (accepted).ics", "step": "s1", "date": "2026-10-07"},
        {"what": "Viva-Guide-PDF", "product_id": "Viva-Guide-PDF", "managed": True, "phase": "awaiting_review", "presentation_id": "viva-1",
         "path": "deliverables/Viva-Guide-PDF/a.pdf", "step": "s2"},
        {"what": "Viva-Guide-HTML", "product_id": "Viva-Guide-HTML", "managed": True, "phase": "awaiting_review", "presentation_id": "viva-1",
         "path": "deliverables/Viva-Guide-HTML/b.html", "step": "s2"},
        {"what": "Bank (PDF)", "managed": True, "phase": "awaiting_review", "path": "deliverables/Bank/c.pdf", "step": "s3"},
    ]
    acts = [a for a in sc.review_acts({}, items) if a["act"] != "Next"]
    rows = [(a["act"], a["label"], a["path"], len(a.get("companions") or [])) for a in acts]
    assert rows == [
        ("Review", "Viva Guide", "deliverables/Viva-Guide-PDF/a.pdf", 1),       # reviews first; PDF is the face
        ("Review", "Bank", "deliverables/Bank/c.pdf", 0),
        ("Open", "Guide - Refinement 1", "q/Guide - Refinement 1.pdf", 2),       # three formats, one decision
        ("Open", "Calendar (accepted).ics", "q/Calendar (accepted).ics", 0),
    ]
    assert [c["path"] for c in acts[2]["companions"]] == ["q/Guide - Refinement 1.html", "q/Guide - Refinement 1.md"]
    assert acts[2]["companions"][0]["item"]["what"] == "Guide - Refinement 1 HTML"


def test_grouping_never_merges_different_products_or_versions():
    items = [
        {"what": "FOR REVIEW: Summary (PDF)", "path": "a/Summary.pdf", "step": "s1"},
        {"what": "FOR REVIEW: Summary (PDF)", "path": "b/Summary.pdf", "step": "s1"},          # another folder
        {"what": "Guide-PDF", "product_id": "Guide-PDF", "managed": True, "phase": "awaiting_review",
         "round": 2, "path": "deliverables/Guide-PDF/x.pdf", "step": "s1"},
        {"what": "Guide-HTML", "product_id": "Guide-HTML", "managed": True, "phase": "awaiting_review",
         "round": 1, "path": "deliverables/Guide-HTML/y.html", "step": "s1"},                  # an older round
        {"what": "Bank (PDF; held)", "path": "q/Bank.pdf", "step": "s1"},
        {"what": "Bank (browser; held)", "path": "q/Bank.html", "step": "s1"},
    ]
    acts = [a for a in sc.review_acts({}, items) if a["act"] != "Next"]
    assert len(acts) == 5
    bank = [a for a in acts if a["label"].startswith("Bank")]
    assert len(bank) == 1 and bank[0]["label"] == "Bank (held)" and len(bank[0]["companions"]) == 1


def test_a_newer_unrelated_product_does_not_hide_an_older_pending_one():
    step = {"id": "s1", "name": "Step", "status": "active", "navigation": {"current": True, "role": "primary"}}
    map_ = {"steps": [step]}                                              # the one pinned step is the focus
    items = [
        {"what": "Guide - Draft 1", "path": "g/Guide - Draft 1.pdf", "step": "s1", "date": "2026-10-05"},
        {"what": "Guide - Draft 2", "path": "g/Guide - Draft 2.pdf", "step": "s1", "date": "2026-10-06"},
        {"what": "Calendar", "path": "c/Calendar.pdf", "step": "s1", "date": "2026-10-07"},
    ]
    assert sc._focused_step(map_)[0] is step
    whats = {it["what"] for it in sc.current_review_items(map_, items)}
    assert whats == {"Guide - Draft 2", "Calendar"}


# ---------- browser: the cockpit as John sees it ----------

def _frame(page):
    return page.frame_locator('[data-fsframe]')


def test_next_steps_rows_are_not_rebuilt_by_the_clock(cockpit):
    """A row's node survives the 1 s busy-clock repaint (it used to be rebuilt every second: icons re-created,
    clicks that spanned a rebuild swallowed, focus lost)."""
    page, server = cockpit
    surface = open_surface(page)
    body = surface.locator('[data-delivmount] .blk.next .body')
    expect(body).to_have_count(1)
    body.evaluate("b => { b.__marker = 'kept'; Array.from(b.querySelectorAll('*')).forEach(n => n.__marker = 'kept'); }")
    time.sleep(3.2)
    survivors = body.evaluate("b => Array.from(b.querySelectorAll('*')).filter(n => n.__marker === 'kept').length")
    total = body.evaluate("b => b.querySelectorAll('*').length")
    assert total > 0 and survivors == total


def test_dialogue_follows_the_newest_until_john_scrolls_up(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    scroll = surface.locator('.scroll').first
    # content arriving with no scroll event of its own (a late render) keeps the newest in view
    scroll.evaluate("""s => { for (let i = 0; i < 40; i++) { const d = document.createElement('div');
        d.style.height = '60px'; d.textContent = 'line ' + i; s.appendChild(d); } }""")
    page.wait_for_timeout(300)
    gap = scroll.evaluate("s => s.scrollHeight - s.scrollTop - s.clientHeight")
    assert gap < 5, gap
    # John scrolls up - even a little: arriving content no longer moves him
    scroll.hover()
    page.mouse.wheel(0, -60)
    page.wait_for_timeout(300)
    top = scroll.evaluate("s => s.scrollTop")
    scroll.evaluate("""s => { const d = document.createElement('div'); d.style.height = '400px'; d.textContent = 'late';
        s.appendChild(d); }""")
    page.wait_for_timeout(300)
    assert abs(scroll.evaluate("s => s.scrollTop") - top) < 2


def test_narrow_cockpit_closes_rail_and_status_for_now_only(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    app = surface.locator('.app')
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    saved = surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')")
    page.set_viewport_size({"width": 900, "height": 1000})
    expect(app).not_to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    expect(app).to_have_class(__import__('re').compile(r'\brailhide\b'))
    # reopened while narrow, the status pane overlays the dialogue instead of squeezing it
    surface.locator('[data-statustoggle]:visible,[data-statustoggle2]:visible').first.click()
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    assert surface.locator('.rightcol').evaluate("e => getComputedStyle(e).position") == "fixed"
    assert surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')") == saved
    surface.locator('[data-statustoggle]:visible,[data-statustoggle2]:visible').first.click()
    page.set_viewport_size({"width": 1700, "height": 1050})
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))   # his wide layout comes back as it was
    assert surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')") == saved


# ---------- item 2: reading and links, made mechanical ----------

import report_viewer
import deliverables_register as dr
from steward_cockpit import steward_engine


def test_reader_renders_tables_and_links_that_survive_spaces_and_parentheses():
    md = "\n".join(["| Week | File |", "|---|:--:|",
                    "| 1 | [Calendar](BA 815/Calendar (accepted).ics) |", "",
                    "See [y](<My Doc.md>) and [bad](javascript:alert(1)) and [z](https://e.com/a_(b))"])
    out = report_viewer.markdown_to_html(md)
    assert "<table>" in out and "<th>Week</th>" in out and "<td>1</td>" in out
    assert 'href="BA%20815/Calendar%20(accepted).ics"' in out
    assert 'href="My%20Doc.md"' in out and 'href="https://e.com/a_(b)"' in out
    assert "javascript" not in out and ">bad<" not in out


def test_reading_target_is_one_encoded_url_per_kind(tmp_path):
    eff = tmp_path / "MBA Teaching AI"
    (eff / "q").mkdir(parents=True)
    for name in ("Guide (v1).md", "Guide (v1).pdf", "Deck.pptx", "Talk.pptx", "Talk.pdf", "Cal (accepted).ics"):
        (eff / "q" / name).write_text("x", encoding="utf-8")
    t = lambda p: dr.reading_target({"path": p}, pid="p 1", effort_rel="MBA Teaching AI", effort_dir=eff)
    md = t("q/Guide (v1).md")
    assert md["read"] == ("/api/steward/deliverable-file?pid=p%201&dir=MBA%20Teaching%20AI"
                          "&path=q%2FGuide%20%28v1%29.md&render=1")
    assert t("q/Guide (v1).pdf")["read"].endswith("Guide%20%28v1%29.pdf")
    deck = t("q/Deck.pptx")
    assert deck["read"] is None and deck["preparing"] and deck["download"].endswith("&download=1")
    assert t("q/Talk.pptx")["read"].endswith("path=q%2FTalk.pdf")          # its PDF companion is the reading copy
    assert t("q/Cal (accepted).ics")["download"]
    assert t("q/missing.md")["read"] is None                                # nothing on disk: no link


def _receipt_engine(tmp_path, monkeypatch, rows):
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n" + "".join(rows), encoding="utf-8")
    eng = steward_engine.Engine.__new__(steward_engine.Engine)
    eng.dir, eng.general, eng._deliv_seen = str(eff), False, None
    said, emitted = [], []
    eng.skey = lambda: "test"
    eng._record_conversation = lambda role, text, turn_id=None, goal=None: said.append((role, text, turn_id)) or True
    eng._emit = lambda ev: emitted.append(ev)
    monkeypatch.setattr(steward_engine, "_update_state", lambda key, patch: True)
    monkeypatch.setattr(dr, "project_and_rel", lambda folder: ("p1", "eff"))
    return eng, eff, said, emitted


def test_the_engine_announces_each_new_product_once_with_its_read_link(tmp_path, monkeypatch):
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")                                     # baseline: announces nothing
    assert said == []
    (eff / "Report (final).md").write_text("# r", encoding="utf-8")
    (eff / "Report (final).pdf").write_text("x", encoding="utf-8")
    (eff / "Deck.pptx").write_text("x", encoding="utf-8")
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| Report (final) MD | `Report (final).md` | 2026-10-07 | 1 |\n"
                 "| Report (final) PDF | `Report (final).pdf` | 2026-10-07 | 1 |\n"
                 "| Deck | `Deck.pptx` | 2026-10-07 | 1 |\n")
    eng._publish_delivery_receipt("t1")
    lines = [text for _role, text, _tid in said]
    assert len(lines) == 2, lines                                           # the md+pdf pair is ONE product
    report = next(l for l in lines if "Report" in l)
    assert "ready to read: [Report (final)](/api/steward/deliverable-file?pid=p1&dir=eff&path=Report%20%28final%29.pdf)" in report
    assert "[MD](/api/steward/deliverable-file?pid=p1&dir=eff&path=Report%20%28final%29.md&render=1)" in report
    deck = next(l for l in lines if "Deck" in l)
    assert "preparing a reading copy: Deck" in deck and "ready" not in deck and "[Download](" in deck
    assert [e["t"] for e in emitted] == ["receipt", "receipt"]
    eng._publish_delivery_receipt("t2")                                     # nothing new: nothing said again
    assert len(said) == 2


def test_cockpit_links_survive_spaces_and_parentheses_and_markdown_opens_formatted(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    (server.campaign / "notes (draft).md").write_text("# Notes\n\n| A | B |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    links = surface.locator('.scroll').first.evaluate("""s => {
        const box = document.createElement('div'); s.appendChild(box);
        mdRender(box, 'Read [the notes](/api/steward/deliverable-file?pid=p&dir=d&path=notes (draft).md) and ' +
                      '[bare path](C:/x/y.md) and [web](https://e.com/a_(b))');
        return Array.from(box.querySelectorAll('a')).map(a => a.getAttribute('href'));
    }""")
    assert len(links) == 2, links                                   # a bare path never becomes a link
    from urllib.parse import urlsplit, parse_qs
    q = parse_qs(urlsplit(links[0]).query)
    assert q["path"] == ["notes (draft).md"] and q["render"] == ["1"]
    assert links[1] == "https://e.com/a_(b)"
    # the canonical reading URL renders the markdown formatted, with its table
    from urllib.parse import quote
    url = (f"{server.origin}/api/steward/deliverable-file?pid={quote(server.project_id, safe='')}"
           f"&dir={quote(server.campaign.name, safe='')}&path={quote('notes (draft).md', safe='')}&render=1")
    reader = page.context.new_page()
    reader.goto(url)
    expect(reader.locator("table th").first).to_have_text("A")
    expect(reader.locator("h1")).to_have_text("Notes")
    reader.close()


def test_a_document_only_named_in_the_reply_still_gets_its_read_link(tmp_path, monkeypatch):
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    (eff / "x").mkdir()
    doc = eff / "x" / "Teaching Plan (v2).md"
    doc.write_text("# plan", encoding="utf-8")
    (eff / "ECGBERHT.md").write_text("record", encoding="utf-8")
    reply = "Done - it is at " + str(doc) + " and I updated ECGBERHT.md."
    eng._publish_delivery_receipt("t1", reply=reply, written=[str(doc), str(eff / "ECGBERHT.md"), str(eff / "x" / "other.md")])
    assert len(said) == 1, said
    assert "ready to read: [Teaching Plan (v2)](/api/steward/deliverable-file?pid=p1&dir=eff&path=x%2FTeaching%20Plan%20%28v2%29.md&render=1)" in said[0][1]


# ---------- item 1, review round 2: one identity rule ----------

def test_formats_pair_only_on_affirmative_evidence():
    items = [
        {"what": "Guide (PDF)", "path": "q/guide-v1.pdf", "step": "s1"},
        {"what": "Guide (HTML)", "path": "q/guide-v2.html", "step": "s1"},                     # another version
        {"what": "Plan-PDF", "product_id": "Plan-PDF", "managed": True, "phase": "awaiting_review",
         "presentation_id": "p-2", "path": "deliverables/Plan-PDF/a.pdf", "step": "s1"},
        {"what": "Plan-HTML", "product_id": "Plan-HTML", "managed": True, "phase": "awaiting_review",
         "presentation_id": "p-1", "path": "deliverables/Plan-HTML/b.html", "step": "s1"},      # an older presentation
        {"what": "Talk-PDF", "product_id": "Talk-PDF", "managed": True, "phase": "awaiting_review",
         "presentation_id": "p-9", "path": "deliverables/Talk-PDF/c.pdf", "step": "s1"},
        {"what": "Talk-HTML", "product_id": "Talk-HTML", "managed": True, "phase": "awaiting_review",
         "presentation_id": "p-9", "path": "deliverables/Talk-HTML/d.html", "step": "s1"},      # presented together
    ]
    acts = [a for a in sc.review_acts({}, items) if a["act"] != "Next"]
    assert len(acts) == 5
    talk = next(a for a in acts if a["label"] == "Talk")
    assert [c["item"]["product_id"] for c in talk["companions"]] == ["Talk-HTML"]


def test_one_family_keeps_only_its_newest_version_even_on_one_day():
    step = {"id": "s1", "name": "Step", "status": "active", "navigation": {"current": True, "role": "primary"}}
    items = [
        {"what": "Guide - Draft 1", "path": "g/Guide - Draft 1.pdf", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Draft 2", "path": "g/Guide - Draft 2.pdf", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Draft 2", "path": "g/Guide - Draft 2.html", "step": "s1", "date": "2026-10-07"},
        {"what": "Summary", "path": "a/Summary.pdf", "step": "s1", "date": "2026-10-06"},
        {"what": "Summary", "path": "b/Summary.pdf", "step": "s1", "date": "2026-10-07"},       # another folder
        {"what": "Bank - Draft 1", "path": "Quiz - Draft 1/Bank - Draft 1.pdf", "step": "s1", "date": "2026-10-01"},
        {"what": "Bank - Draft 3", "path": "Quiz - Draft 3/Bank - Draft 3.pdf", "step": "s1", "date": "2026-10-04"},
    ]
    paths = sorted(it["path"] for it in sc.current_review_items({"steps": [step]}, items))
    assert paths == ["Quiz - Draft 3/Bank - Draft 3.pdf", "a/Summary.pdf", "b/Summary.pdf",
                     "g/Guide - Draft 2.html", "g/Guide - Draft 2.pdf"]


def _add_rows(campaign, rows):
    reg = campaign / "DELIVERABLES.md"
    text = reg.read_text(encoding="utf-8")
    anchor = "| Earlier note | `legacy.txt` | 2026-09-01 | foundation |\n"
    assert anchor in text
    reg.write_text(text.replace(anchor, anchor + "".join(rows)), encoding="utf-8")


def _refresh(page):
    with page.expect_response(lambda r: "/deliverables?" in r.url and r.request.method == "GET"):
        page.frame_locator('[data-fsframe]').locator('body').evaluate(
            "() => window.dispatchEvent(new Event('anchor-notebooks-changed'))")


def test_a_changed_row_never_moves_the_focused_row_beside_it(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    for name in ("alpha.md", "beta.md"):
        (server.campaign / name).write_text("# " + name, encoding="utf-8")
    _add_rows(server.campaign, ["| FOR REVIEW: Alpha | `alpha.md` | 2026-10-07 | foundation |\n",
                                "| FOR REVIEW: Beta | `beta.md` | 2026-10-07 | foundation |\n"])
    _refresh(page)
    tile = surface.locator('[data-delivmount] .blk.next')
    if 'folded' in (tile.get_attribute('class') or ''):
        tile.locator('> .who').click()
    beta = tile.locator('.navact a', has_text='Beta').first
    expect(beta).to_be_visible()
    beta.evaluate("a => { a.__mark = 'same'; a.focus(); }")
    reg = server.campaign / "DELIVERABLES.md"
    reg.write_text(reg.read_text(encoding="utf-8").replace("FOR REVIEW: Alpha |", "FOR REVIEW: Alpha revised |"),
                   encoding="utf-8")
    _refresh(page)
    expect(tile.locator('.navact a', has_text='Alpha revised')).to_be_visible()
    assert surface.locator('body').evaluate("() => document.activeElement && document.activeElement.__mark") == "same"


# ---------- item 2, review round 1 fixes ----------

def test_reading_target_refuses_what_the_route_would_refuse_and_binds_decks_to_their_pdf(tmp_path):
    import os as _os
    eff = tmp_path / "eff"
    eff.mkdir()
    (tmp_path / "outside.pdf").write_text("x", encoding="utf-8")
    t = lambda it: dr.reading_target(it, pid="p", effort_rel="eff", effort_dir=eff)
    assert t({"path": "../outside.pdf"})["read"] is None                     # outside the effort: no link
    assert t({"path": "x.md", "openable": False})["read"] is None
    (eff / "Talk.pdf").write_text("old slides", encoding="utf-8")
    (eff / "Talk.pptx").write_text("new deck", encoding="utf-8")
    _os.utime(eff / "Talk.pdf", (1_000_000, 1_000_000))                     # yesterday's PDF, today's deck
    assert t({"path": "Talk.pptx"})["preparing"] is True
    _os.utime(eff / "Talk.pdf", None)                                       # a PDF made after the deck
    assert t({"path": "Talk.pptx"})["read"].endswith("path=Talk.pdf")
    managed = {"path": "Talk.pptx", "managed": True, "hash": "h"}
    assert t(managed)["preparing"] is True                                  # a managed deck: only its ledger PDF
    assert "view=1" in t({**managed, "visual_companion": {"path": "c.pdf"}})["read"]


def test_route_targets_are_rebuilt_encoded():
    hostile = "/artifact/p1?path=notes)[Other](/report/p/lane)"
    url = dr.reading_target({"route": hostile}, pid="p1", effort_rel="")["read"]
    assert ")" not in url and "[" not in url and url.startswith("/artifact/p1?path=")
    md = dr.reading_target({"route": "/artifact/p1?path=reports/Plan.md"}, pid="p1", effort_rel="")["read"]
    assert md == "/artifact/p1?path=reports%2FPlan.md&render=1"
    assert dr.reading_target({"route": "https://evil.example/x"}, pid="p1", effort_rel="")["read"] is None


def test_reader_takes_angle_targets_whole_and_tables_without_outer_pipes():
    out = report_viewer.markdown_to_html("[Read](<https://example.com/a)b>)\n\nA | B\n--- | ---\n1 | 2\n")
    assert 'href="https://example.com/a)b"' in out
    assert "<th>A</th>" in out and "<td>2</td>" in out


def test_a_receipt_that_could_not_be_saved_is_retried_not_lost(tmp_path, monkeypatch):
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    (eff / "R.pdf").write_text("x", encoding="utf-8")
    with open(eff / "DELIVERABLES.md", "a", encoding="utf-8") as fh:
        fh.write("| R | `R.pdf` | 2026-10-07 | 1 |\n")
    eng._record_conversation = lambda role, text, turn_id=None, goal=None: False      # the save fails
    eng._publish_delivery_receipt("t1")
    assert emitted == []
    eng._record_conversation = lambda role, text, turn_id=None, goal=None: said.append((role, text, turn_id)) or True
    eng._publish_delivery_receipt("t2")                                               # retried, once
    eng._publish_delivery_receipt("t3")
    assert len(said) == 1 and "ready to read: [R]" in said[0][1]


def test_a_shell_made_document_named_by_its_full_path_gets_a_link(tmp_path, monkeypatch):
    import time as _t
    eng, eff, said, emitted = _receipt_engine(tmp_path, monkeypatch, [])
    eng._publish_delivery_receipt("t0")
    eng.turn_started = _t.time() - 5
    (eff / "out dir").mkdir()
    doc = eff / "out dir" / "Week 3 Plan (draft).pdf"
    doc.write_text("x", encoding="utf-8")
    eng._publish_delivery_receipt("t1", reply="I rendered it to " + str(doc) + " for you.", written=[])
    assert len(said) == 1 and "path=out%20dir%2FWeek%203%20Plan%20%28draft%29.pdf" in said[0][1]
