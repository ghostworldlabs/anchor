"""W2 of the steward revision (2026-09-28): his tiers order the day; the head is ONE act; the urgent lower-tier
exception (his Q3); the age of a wait from the record; the page-open boundary and "since you last opened"."""
import importlib
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import high_seat_page as hsp  # noqa: E402
import home_attention as ha  # noqa: E402
import home_rows as hr  # noqa: E402

TODAY = date(2026, 9, 28)


def _init(name, tier, order, parts):
    return {"id": name.lower(), "name": name, "tier": tier, "order": order, "done_when": "the %s outcome" % name,
            "parts": parts, "needs": [p for p in parts if p.get("needs_you")]}


def _part(text, **kw):
    p = {"id": text.lower(), "kind": "step", "text": text, "target": "MBA Teaching AI", "pid": "p1", "href": "/project/p1",
         "state": "", "date": "", "status": "planned", "target_status": "planned", "broken": False, "needs_you": False}
    p.update(kw)
    return p


def test_the_head_is_the_first_tier_one_part_that_needs_him_in_his_order():
    inits = [
        _init("Trusts", 1, 0, [_part("Sign the letter"), _part("Valuations", needs_you=True, state="waiting on you")]),
        _init("MBA", 1, 1, [_part("Supplement 4", needs_you=True, state="waiting on you")]),
        _init("Magi", 2, 0, [_part("Chapter 2", needs_you=True, state="waiting on you")]),
    ]
    act = ha.head_act(inits, [], today=TODAY)
    assert act["kind"] == "tier1" and act["initiative"] == "Trusts" and act["text"] == "Valuations"
    s = ha.head_sentence(act)
    assert s.startswith("Tier 1 · Trusts: Valuations (MBA Teaching AI) — waiting on you")
    # a done target is never the pick even when its wrapper is flagged
    inits[0]["parts"][1]["target_status"] = "done"
    assert ha.head_act(inits, [], today=TODAY)["initiative"] == "MBA"


def test_a_lower_tier_part_due_today_leads_only_as_the_marked_exception():
    inits = [
        _init("Trusts", 1, 0, [_part("Valuations", needs_you=True, state="waiting on you")]),
        _init("Magi", 3, 0, [_part("Send the chapter", date="2026-09-28"), _part("Later", date="2026-10-20")]),
    ]
    act = ha.head_act(inits, [], today=TODAY)
    assert act["kind"] == "exception" and act["text"] == "Send the chapter" and act["due"] == "2026-09-28" and act["overdue"] is False
    s = ha.head_sentence(act)
    assert s.startswith("Exception, due today: Send the chapter (Magi, tier 3) — it decides: the Magi outcome. Your order is untouched.")
    # overdue reads as overdue; a Tier-1 part due today means no exception fires
    inits[1]["parts"][0]["date"] = "2026-09-20"
    assert ha.head_sentence(ha.head_act(inits, [], today=TODAY)).startswith("Exception, overdue since Sep 20:")
    inits[0]["parts"][0]["date"] = "2026-09-28"
    assert ha.head_act(inits, [], today=TODAY)["kind"] == "tier1"


def test_with_no_tier_one_need_the_oldest_wait_leads_with_its_age_and_nothing_is_a_list():
    facts = [{"id": "a", "name": "Bread", "href": "/project/a", "needs_you": "approve the loaf", "wait_age_days": 2, "effort": ""},
             {"id": "b", "name": "DARPA", "href": "/project/b", "needs_you": "sign the form", "wait_age_days": 9, "needs_you_effort": "phase2"}]
    act = ha.head_act([], facts, today=TODAY)
    assert act["kind"] == "oldest-wait" and act["pid"] == "b" and act["dir"] == "phase2"
    assert ha.head_sentence(act) == "DARPA: sign the form · waiting 9 days."
    assert ha.head_act([], [], today=TODAY) is None
    assert ha.head_sentence(None) == "Nothing is waiting on you."
    assert ha.head_sentence(None, overnight=[{"name": "Draft 5"}, {"name": "Outline v7"}]) == \
        "Nothing is waiting on you. Since you last opened: 2 steps closed — Draft 5, Outline v7."


def test_the_panel_leads_with_the_head_and_folds_the_rest(tmp_path):
    ctx = {"steward": {"label": "Ecgberht", "high_seat_name": "High Seat"}, "brief_when": "10:00", "rows": [], "facts": {},
           "bullets": ["Exception, due today: Send the chapter (Magi, tier 3). Your order is untouched.", "2 wait on you: A, B.", "This week: nothing.", "You can act from here."],
           "head": {"kind": "exception", "pid": "p1", "dir": ""}, "seed_rows": [], "seeds": 0, "campaign": None, "initiatives": [],
           "live": [], "counts": {"open": 0, "running": 0, "need_you": 0, "folders": 0}, "capacity": [], "today": TODAY}
    html = hsp._head_li(ctx)
    assert html.startswith('<li class="lead exc">Exception, due today')
    assert 'class="h-open" data-part="status" data-pid="p1"' in html
    assert '<details class="brief-more"><summary>more</summary>' in html and "2 wait on you" in html


def test_the_wait_age_comes_from_the_record_never_the_strips_last_touch(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    strip = {"human_wait": "approve Draft 5", "instruments": [
        {"as_of": "2026-09-20", "human_wait": "approve Draft 4"},
        {"as_of": "2026-09-24", "human_wait": "approve Draft 5"},
        {"as_of": "2026-09-27", "human_wait": "approve Draft 5"}]}
    (d / "strip.json").write_text(json.dumps(strip), encoding="utf-8")
    f = hr.project_facts({"id": "p", "name": "P", "folder_path": str(d)}, TODAY)
    assert f["wait_age_days"] == 4, "since the earliest instrument of the current wait's run, not the last"
    strip2 = {"human_wait": "approve Draft 5", "instruments": []}
    (d / "strip.json").write_text(json.dumps(strip2), encoding="utf-8")
    (d / ".ecgberht").mkdir()
    (d / ".ecgberht" / "status-summary.json").write_text(json.dumps({"at": "2026-09-28T10:00", "plan": {"waiting_on_you": "approve Draft 5", "waiting_since": "2026-09-26T09:00"}}), encoding="utf-8")
    assert hr.project_facts({"id": "p", "name": "P", "folder_path": str(d)}, TODAY)["wait_age_days"] == 2, "the composer's waiting_since, not the summary's own time"
    (d / ".ecgberht" / "status-summary.json").write_text(json.dumps({"at": "2026-09-26T09:00", "plan": {"waiting_on_you": "approve Draft 5"}}), encoding="utf-8")
    assert hr.project_facts({"id": "p", "name": "P", "folder_path": str(d)}, TODAY)["wait_age_days"] is None, "no number without a reader: the summary's at is a ten-minute clock"
    html = hsp._card({"id": "p", "name": "P"}, dict(f, wait_age_days=4), "")
    assert "&middot; 4 days" in html


def test_closed_recent_reads_the_receipts_own_date(tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    (d / "strip.json").write_text(json.dumps({"human_wait": "none"}), encoding="utf-8")
    (d / "roadmap.json").write_text(json.dumps({"roadmap_projection": [{"id": "s1", "name": "Draft 5", "status": "done"}, {"id": "s2", "name": "Old", "status": "done"}],
        "roadmap_events": [{"kind": "status_flip", "step_id": "s1", "to": "done", "receipt": {"who": "john", "when": "2026-09-27"}},
                           {"kind": "status_flip", "step_id": "s2", "to": "done", "receipt": {"who": "john", "when": "2026-09-01"}},
                           {"kind": "status_flip", "step_id": "s1", "to": "parked", "receipt": {"who": "john", "when": "2026-09-27"}}]}), encoding="utf-8")
    f = hr.project_facts({"id": "p", "name": "P", "folder_path": str(d)}, TODAY)
    assert [x["name"] for x in f["closed_recent"]] == ["Draft 5"]


def test_the_page_open_boundary_returns_the_previous_open(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    from steward_cockpit import presence
    importlib.reload(presence)
    assert presence.note_page_open(now=100.0) is None
    assert presence.note_page_open(now=200.0) == 100.0
    presence.note_open("mba", now=250.0)
    assert presence.read_presence()["high_seat_at"] == 200.0, "a project open keeps the page-open time"
