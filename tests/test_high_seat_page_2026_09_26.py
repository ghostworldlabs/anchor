"""high_seat_page — the High Seat rendered from facts (W1b). Pure: a synthetic context, no server."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import high_seat_page as hsp  # noqa: E402

TODAY = date(2026, 9, 26)


def _steps():
    mba = "6765ece4b3bc43b0b0b0907b92b17280"
    return [
        {"id": "mba-teaching", "name": "MBA Teaching, Fall 2026", "status": "proposed", "tier": 1, "area": "professional",
         "done_when": "HMBA lectures 3-4 taught Oct 10",
         "navigation": {"path": ["mba-teaching"], "groups": [{"id": "mba-teaching", "label": "MBA Teaching, Fall 2026", "order": 0, "parent_id": None}]}},
        {"id": "mba-project", "name": "MBA Teaching AI (the project)", "status": "proposed", "ref": "project:" + mba, "navigation": {"path": ["mba-teaching"]}},
        {"id": "lectures-3-4", "name": "Lectures 3 + 4", "status": "proposed", "ref": "step:%s/lectures-3-4-revision" % mba, "navigation": {"path": ["mba-teaching"]}},
        {"id": "lecture-99", "name": "A reference that does not exist", "status": "proposed", "ref": "step:%s/lecture-99" % mba, "navigation": {"path": ["mba-teaching"]}},
        {"id": "trusts", "name": "The trusts", "status": "proposed", "tier": 2, "area": "family",
         "navigation": {"path": ["trusts"], "groups": [{"id": "trusts", "label": "The trusts", "order": 0, "parent_id": None}]}},
        {"id": "hw", "name": "retool homework 2", "status": "planned", "due": "2026-10-27", "navigation": {"path": ["mba-teaching"]}},
    ]


def _resolved():
    mba = "6765ece4b3bc43b0b0b0907b92b17280"
    return {
        "mba-project": {"kind": "project", "name": "MBA Teaching AI", "what": "", "state": "waiting on you: approve the Lecture 3 AI supplement", "date": "2026-10-10", "href": "/project/" + mba, "broken": False, "gap": ""},
        "lectures-3-4": {"kind": "step", "name": "MBA Teaching AI", "what": "Lectures 3 + 4 revised, with AI supplements", "state": "waiting", "date": "2026-10-10", "href": "/project/" + mba, "broken": False, "gap": ""},
        "lecture-99": {"kind": "step", "name": "MBA Teaching AI", "what": "", "state": "", "date": "", "href": "", "broken": True, "gap": "no step 'lecture-99' in MBA Teaching AI"},
    }


def _ctx(campaign=True):
    mba = "6765ece4b3bc43b0b0b0907b92b17280"
    entries = [
        {"id": mba, "name": "MBA Teaching AI", "folder_path": "C:/x/mba", "blurb": "The course.", "group": "Teaching", "state": "active"},
        {"id": "9405abe0", "name": "Family <Trusts>", "folder_path": "C:/x/trusts", "blurb": "", "group": "Personal", "state": "active"},
        {"id": "quiet", "name": "Quiet one", "folder_path": "C:/x/q", "blurb": "", "group": "Ungrouped", "state": "active"},
    ]
    facts = {
        mba: {"id": mba, "name": "MBA Teaching AI", "href": "/project/" + mba, "needs_you": "approve the Lecture 3 AI supplement", "next": "Lecture 4", "why": "", "summary": None, "summary_age_s": None,
              "dated": [{"step_id": "lec", "name": "Lectures 3 + 4 revised", "due": "2026-10-10", "status": "waiting", "project_id": mba, "project_name": "MBA Teaching AI"},
                        {"step_id": "old", "name": "Block 1 quiz", "due": "2026-09-20", "status": "planned", "project_id": mba, "project_name": "MBA Teaching AI"}], "nearest_due": "2026-09-20", "has_record": True},
        "9405abe0": {"id": "9405abe0", "name": "Family <Trusts>", "href": "/project/9405abe0", "needs_you": "", "next": "Send the valuations", "why": "the package closes on them", "summary": None, "summary_age_s": None,
                     "dated": [{"step_id": "v", "name": "Valuations", "due": "2026-11-30", "status": "active", "project_id": "9405abe0", "project_name": "Family <Trusts>"}], "nearest_due": "2026-11-30", "has_record": True},
        "quiet": {"id": "quiet", "name": "Quiet one", "href": "/project/quiet", "needs_you": "", "next": "", "why": "", "summary": None, "summary_age_s": None, "dated": [], "nearest_due": "", "has_record": False},
    }
    rows = [{"rule": "needs-you", "rule_label": "the steward's record waits on you", "severity": "red", "text": "MBA Teaching AI is waiting on you", "why": "approve the Lecture 3 AI supplement", "href": "/project/" + mba, "kind": "project", "project_id": mba},
            {"rule": "due-soon", "rule_label": "due within five weeks", "severity": "amber", "text": "Lectures 3 + 4 revised", "why": "due Oct 10 · MBA Teaching AI", "href": "/project/" + mba, "kind": "step", "project_id": mba}]
    initiatives = hsp.campaign_initiatives(_steps(), _resolved()) if campaign else []
    return {"today": TODAY, "today_str": "Saturday, September 26, 2026", "week": "this week Sep 21–27", "week_short": "Sep 21–27",
            "brief_when": "18:30 · Saturday 26 September", "build": "test", "steward": {"key": "jarvis", "label": "Jarvis", "high_seat": "jarvis-high-seat-hat.jpg", "high_seat_name": "Tip of the Hat", "seal_name": "Server"},
            "prefs_html": "<span id='prefs-here'></span>", "entries": entries, "groups": {"Teaching": [entries[0]], "Personal": [entries[1]], "Ungrouped": [entries[2]]},
            "facts": facts, "rows": rows, "bullets": ["MBA Teaching AI is waiting on you — approve the Lecture 3 AI supplement.", "You can act from here."],
            "counts": {"open": 3, "running": 1, "need_you": 1, "folders": 3}, "live": [{"text": "a build session", "project_id": mba, "lane": "build"}],
            "parked": [], "tasks_open": 13, "campaign": {"pid": "df56", "name": "Campaign"} if campaign else None, "initiatives": initiatives, "seeds": 0,
            "capacity": [{"name": "ChatGPT", "state": "not measured yet", "note": "W4"}]}


def test_campaign_initiatives_are_heading_steps_with_their_parts_in_tier_order():
    inits = hsp.campaign_initiatives(_steps(), _resolved())
    assert [i["name"] for i in inits] == ["MBA Teaching, Fall 2026", "The trusts"]
    assert [i["number"] for i in inits] == [1, 2] and inits[0]["tier"] == 1 and inits[1]["tier"] == 2
    mba = inits[0]
    assert [p["kind"] for p in mba["parts"]] == ["project", "step", "step", "task"]
    assert mba["parts"][1]["text"] == "Lectures 3 + 4 revised, with AI supplements" and mba["parts"][1]["date"] == "2026-10-10"
    assert mba["parts"][2]["broken"] and mba["parts"][2]["gap"].startswith("no step")
    assert mba["parts"][3]["text"] == "retool homework 2" and mba["parts"][3]["date"] == "2026-10-27"
    assert mba["next"]["kind"] == "project" and mba["needs"][0]["kind"] == "project"
    assert mba["next_deadline"] == "2026-10-10"


def test_the_ruler_buckets_dates_by_the_weeks_of_the_page():
    facts = list(_ctx()["facts"].values())
    weeks, buckets, beyond, overdue = hsp.ruler_markers(facts, TODAY)
    assert weeks[0]["label"] == "Sep 21–27" and weeks[0]["name"] == "this week"
    assert buckets[0] == []                                                                     # a date before this Monday is not this week's delivery
    assert [m["name"] for m in overdue] == ["Block 1 quiz"] and overdue[0]["overdue"]          # it is named overdue, with its real date
    assert [m["name"] for m in buckets[2]] == ["Lectures 3 + 4 revised"]                       # Oct 10 is week 3
    assert [m["name"] for m in beyond] == ["Valuations"]                                        # Nov 30 is beyond the ruler


def test_the_page_renders_from_facts_and_escapes_them():
    html = hsp.render_high_seat_html(_ctx())
    assert "<title>The Tip of the Hat" in html and "high-seat-page.css" in html and "high-seat-page.js" in html
    assert "this week Sep 21–27" in html and "id='prefs-here'" in html
    assert "Family &lt;Trusts&gt;" in html and "Family <Trusts>" not in html
    # the Campaign tile: the Tier 1 line, one tile with its parts and the broken reference named
    assert "<b>Tier 1:</b> MBA Teaching, Fall 2026" in html and 'href="/project/df56"' in html
    assert "broken reference: no step &#x27;lecture-99&#x27; in MBA Teaching AI" in html
    assert "Tier 2</b> &middot; 1" in html
    # the shelves: the waiting project on Needs you, the next one on Continuing, the quiet one counted off the board
    assert 'id="card-6765ece4b3bc43b0b0b0907b92b17280"' in html and "Needs you:</span>approve the Lecture 3 AI supplement" in html
    quiet = html[html.index('id="shQuiet"'):html.index('id="shPark"')]
    assert 'id="card-9405abe0"' in html and 'id="card-quiet"' in quiet and "no steward record yet" in quiet     # the record-less one has its own card on its own shelf
    # the ruler and the panel
    assert "due Oct 10" in html and "Overdue, before this week:" in html and "Block 1 quiz" in html and "Tasks &middot; <span id=\"taskTotal\">13</span>" in html
    assert "Later this week" in html and "Dated soonest first" in html and "href=\"/project/__dashboard__?classic=1\"" in html
    assert "MBA Teaching AI is waiting on you" in html and "raised by: the steward&#x27;s record waits on you" in html
    assert "Sample data" not in html


def test_the_page_boots_with_the_campaign_id_and_an_undo_on_its_receipt_line():
    html = hsp.render_high_seat_html(_ctx(campaign=True))
    assert 'window.ANCHOR_BOOT = {build_id: "test", campaign_pid: "df56"}' in html and 'id="undoBtn" hidden' in html
    assert 'campaign_pid: ""' in hsp.render_high_seat_html(_ctx(campaign=False))


def test_without_a_campaign_the_tile_says_so_honestly():
    html = hsp.render_high_seat_html(_ctx(campaign=False))
    assert "not stood up yet" in html and "Show Tier 1" not in html


def test_the_board_names_the_effort_a_card_reads_and_shelves_the_record_less_projects():
    ctx = _ctx(campaign=True)
    html = hsp.render_high_seat_html(ctx)
    assert 'id="shQuiet"' in html and "No record yet" in html
    assert 'class="mh-mark"' in html                                                  # the masthead mark carries its size class
    # a fact that reads an effort one folder down names it on the card and hands it to the card's parts
    e = {"id": "eff1", "name": "Skill Foundry", "blurb": "the foundry"}
    f = {"has_record": True, "effort": "steward-refinement", "touched_s": 3600.0 * 5, "next": "Fold the handback", "needs_you": ""}
    c = hsp._card(e, f, "")
    assert 'data-dir="steward-refinement"' in c and "effort &middot; <b>steward-refinement</b> &middot; touched 5 h ago" in c
    assert c.count('data-dir="steward-refinement"') == 5                            # the card, Status and the three acts
    q = hsp._card({"id": "q1", "name": "Quiet one", "blurb": "nothing yet"}, {"has_record": False}, "")
    assert 'class="tile quiet"' in q and "no steward record yet" in q and "Open cockpit" in q and "statusbtn" not in q
