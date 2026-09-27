"""campaign_page + campaign_acts — the Campaign page renders from the record; the acts write only the Campaign's record
through the engine (W3c, High Seat). The acts run the real engine CLI on a temp record."""
import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402

TODAY = date(2026, 9, 26)
MBA = "6765ece4b3bc43b0b0b0907b92b17280"


def _steps():
    return [
        {"id": "mba-teaching", "name": "MBA Teaching, Fall 2026", "status": "proposed", "tier": 1, "area": "professional", "done_when": "HMBA lectures 3-4 taught Oct 10",
         "navigation": {"path": ["mba-teaching"], "groups": [{"id": "mba-teaching", "label": "MBA Teaching, Fall 2026", "order": 0, "parent_id": None}]}},
        {"id": "mba-project", "name": "MBA Teaching AI (the project)", "status": "proposed", "ref": "project:" + MBA, "navigation": {"path": ["mba-teaching"]}},
        {"id": "lectures-3-4", "name": "Lectures 3 + 4", "status": "proposed", "ref": "step:%s/lectures-3-4-revision" % MBA, "navigation": {"path": ["mba-teaching"]}},
        {"id": "hw", "name": "retool homework 2", "status": "planned", "due": "2026-10-27", "navigation": {"path": ["mba-teaching"]}},
        {"id": "trusts", "name": "The trusts", "status": "proposed", "tier": 2, "area": "family",
         "navigation": {"path": ["trusts"], "groups": [{"id": "trusts", "label": "The trusts", "order": 0, "parent_id": None}]}},
    ]


def _resolved():
    return {
        "mba-project": {"kind": "project", "name": "MBA Teaching AI", "what": "", "state": "waiting on you: approve the supplement", "date": "2026-10-10", "href": "/project/" + MBA, "broken": False, "gap": ""},
        "lectures-3-4": {"kind": "step", "name": "MBA Teaching AI", "what": "Lectures 3 + 4 revised, with AI supplements", "state": "waiting", "date": "2026-10-10", "href": "/project/" + MBA, "broken": False, "gap": ""},
    }


def _ctx():
    return {"pid": "df56", "name": "Campaign", "today": TODAY, "today_str": "Saturday, September 26, 2026", "brief_when": "19:00 · Saturday 26 September",
            "build": "test", "steward": {"key": "jarvis", "label": "Jarvis", "high_seat": "jarvis-high-seat-hat.jpg", "seal": "jarvis-seal-salver.jpg", "high_seat_name": "Tip of the Hat", "seal_name": "Server"},
            "prefs_html": "<span id='prefs-here'></span>", "initiatives": hsp.campaign_initiatives(_steps(), _resolved()),
            "seeds": [{"id": "s0", "text": "An AI mechanics class with the group"}], "turns": [{"you": True, "text": "what does the Campaign say?", "at": "18:50"}, {"you": False, "text": "Tier 1 holds the teaching.", "at": "18:51"}],
            "projects": [{"id": MBA, "name": "MBA Teaching AI"}], "tick_allowed": False}


def test_the_page_renders_tiers_parts_seeds_calendar_and_brief_from_the_record():
    html = cpg.render_campaign_html(_ctx())
    assert "<title>The Campaign" in html and "campaign-page.css" in html and "campaign-page.js" in html
    assert "2 in priority order &middot; T1 1 / T2 1 / T3 0" in html
    assert 'data-lane="mba-teaching"' in html and 'data-lane="trusts"' in html and "priority 1 of 2" in html
    assert "retool homework 2" in html and "Oct 27" in html and "Lectures 3 + 4 revised, with AI supplements" in html
    assert 'data-act="date" data-part="hw"' in html                      # a native part's date can be moved here
    assert 'its date lives in its own record' in html                    # a referenced part's cannot
    assert 'disabled title="a tick waits on your word' in html           # the tick waits on his word
    assert "An AI mechanics class with the group" in html and 'data-act="promote"' in html
    assert 'id="viewCal"' in html and "beyond the ruler" in html and 'class="tierstrip"' in html
    assert "<b>Tier 1</b> holds MBA Teaching, Fall 2026." in html and "nearest hard date is <b>Oct 10</b>" in html
    assert "&#9873; 1 part need you" in html
    assert "what does the Campaign say?" in html and "Sample data" not in html


def test_an_untiered_initiative_gets_its_own_column_and_no_number_in_the_tiers():
    steps = _steps()
    steps[4].pop("tier")
    ctx = _ctx(); ctx["initiatives"] = hsp.campaign_initiatives(steps, _resolved())
    html = cpg.render_campaign_html(ctx)
    assert "No tier yet" in html and "T1 1 / T2 0 / T3 0" in html


# ── the acts, on a temp record through the real engine ────────────────────────────────────────

ECG = Path(r"C:\dev\Ecgberht\bin\ecgberht.mjs")


@pytest.fixture
def record(tmp_path):
    if not ECG.is_file() or shutil.which("node") is None:
        pytest.skip("the engine CLI is not on this machine")
    d = tmp_path / "Campaign"
    d.mkdir()
    (d / "ECGBERHT.md").write_text("# Ecgberht\n\n## North star\n\n> the Campaign.\n", encoding="utf-8")

    def cli(*args):
        r = subprocess.run(["node", str(ECG), *args, "--project", str(d)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        return json.loads(r.stdout)
    for sid, name, tier, area, order in (("a", "Initiative A", 1, "family", 0), ("b", "Initiative B", 1, "writing", 1), ("c", "Initiative C", 2, "tools", 0)):
        assert cli("roadmap-propose", "--step", sid, "--name", name, "--tier", str(tier), "--area", area)["ok"]
        assert acts._spine_set(d, sid, {"navigation": {"path": [sid], "groups": [{"id": sid, "label": name, "order": order, "parent_id": None}], "role": "primary"}})["ok"]
    assert cli("roadmap-propose", "--step", "a-part", "--name", "a native part")["ok"]
    assert acts._spine_set(d, "a-part", {"navigation": {"path": ["a"]}})["ok"]
    assert cli("roadmap-propose", "--step", "a-ref", "--name", "a referenced part", "--ref", "project:%s" % MBA)["ok"]
    assert acts._spine_set(d, "a-ref", {"navigation": {"path": ["a"]}})["ok"]
    return d


def _inits(d):
    return {s["id"]: s for s, g in acts._initiatives(d)}


def test_move_tier_rank_and_their_undo_write_one_event_each(record):
    r = acts.act(record, {"act": "move_tier", "step": "b", "tier": 2})
    assert r["ok"] and "moved to tier 2" in r["receipt"] and r["undo"] == {"act": "move_tier", "step": "b", "tier": 1}
    b = acts._step(record, "b")
    assert b["tier"] == 2 and acts._own_group(b)["order"] == 1          # at the foot of tier 2, after c
    back = acts.act(record, r["undo"])
    assert back["ok"] and acts._step(record, "b")["tier"] == 1
    r2 = acts.act(record, {"act": "rank", "step": "b", "direction": "up"})
    assert r2["ok"] and "moved up within tier 1" in r2["receipt"]
    assert acts._own_group(acts._step(record, "b"))["order"] < acts._own_group(acts._step(record, "a"))["order"]
    top = acts.act(record, {"act": "rank", "step": "b", "direction": "up"})
    assert top["ok"] is False and "already at the top" in top["receipt"]
    assert acts.act(record, {"act": "move_tier", "step": "a", "tier": 7})["ok"] is False


def test_native_parts_take_names_dates_parks_and_flags_and_referenced_parts_refuse(record):
    assert acts.act(record, {"act": "rename", "step": "a-part", "name": "a better name"})["ok"]
    assert acts._step(record, "a-part")["name"] == "a better name"
    d = acts.act(record, {"act": "date", "step": "a-part", "due": "2026-10-08"})
    assert d["ok"] and acts._step(record, "a-part")["due"] == "2026-10-08" and d["undo"]["due"] == "none"
    assert acts.act(record, {"act": "date", "step": "a-ref", "due": "2026-10-08"})["ok"] is False      # its date lives in its own record
    assert acts.act(record, {"act": "park", "step": "a-part", "waiting_on": ""})["ok"] is False        # a park carries its trigger
    p = acts.act(record, {"act": "park", "step": "a-part", "waiting_on": "January"})
    assert p["ok"] and acts._step(record, "a-part")["status"] == "parked" and acts._step(record, "a-part")["waiting_on"] == "January"
    assert acts.act(record, p["undo"])["ok"] and acts._step(record, "a-part")["status"] == "planned"
    f = acts.act(record, {"act": "flag", "step": "a-part"})
    assert f["ok"] and acts._step(record, "a-part")["status"] == "waiting" and acts._step(record, "a-part")["waiting_on"] == "John"
    assert acts.act(record, {"act": "tick", "step": "a-part"})["ok"] is False                           # waits on his word
    assert acts.act(record, {"act": "park", "step": "a-ref", "waiting_on": "later"})["ok"] is False


def test_add_and_promote_place_new_steps_under_their_initiative(record):
    a = acts.act(record, {"act": "add", "initiative": "a", "kind": "task", "text": "Sign the engagement letter", "due": "2026-10-01"})
    assert a["ok"] and "added" in a["receipt"]
    s = acts._step(record, a["step"])
    assert s["due"] == "2026-10-01" and s["navigation"]["path"] == ["a"]
    p = acts.act(record, {"act": "add", "initiative": "a", "kind": "project", "text": "", "project_id": "abc123"})
    assert p["ok"] and acts._step(record, p["step"])["ref"] == "project:abc123"
    dup = acts.act(record, {"act": "add", "initiative": "a", "kind": "project", "text": "again", "project_id": MBA})
    assert dup["ok"] is False and "duplicate_ref" in dup["receipt"]
    pr = acts.act(record, {"act": "promote", "seed": "An AI mechanics class", "tier": "3", "area": "professional"})
    assert pr["ok"] and "tier 3" in pr["receipt"]
    head = acts._step(record, pr["step"])
    assert head["tier"] == 3 and head["area"] == "professional" and acts._own_group(head) is not None
