"""W1 of the active set (2026-09-29): the initiatives carry his active set, its order, the pace, the goal and the parts'
progress; four receipted acts with undo (activate · bench · order · pace); the three spoken verbs applied; the head
reads the active set first; the pick-up while the set runs."""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import high_seat_page as hsp  # noqa: E402
import home_attention as ha  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402
from steward_cockpit import campaign_say as say  # noqa: E402

TODAY = date(2026, 9, 29)


def _steps():
    def head(sid, name, tier, order, **more):
        return dict({"id": sid, "name": name, "status": "proposed", "tier": tier, "done_when": name + " done",
                     "navigation": {"path": [sid], "groups": [{"id": sid, "label": name, "order": order, "parent_id": None}]}}, **more)

    def part(sid, head_id, name, **more):
        return dict({"id": sid, "name": name, "status": "planned", "navigation": {"path": [head_id]}}, **more)
    return [
        head("magi", "Artificial Magi", 1, 1, active=True, active_order=0, pace="2026-12-15"),
        part("magi-ch2", "magi", "Chapter 2 scenes", ref="project:p-magi"),
        head("mba", "MBA Teaching, Fall 2026", 1, 2, active=True, active_order=1, pace="2026-10-10"),
        part("mba-lec", "mba", "Lectures 3 + 4", ref="project:p-mba", due="2026-10-10"),
        head("trusts", "The trusts and the holding company", 1, 0),
        part("trusts-pkg", "trusts", "Send the Stanford package", status="waiting", waiting_on="John to send it", due="2026-10-08"),
        head("paper", "Paper 1", 2, 0),
        part("paper-draft", "paper", "Draft the paper"),
    ]


def _inits(resolved=None):
    return hsp.campaign_initiatives(_steps(), resolved or {
        "magi-ch2": {"what": "Chapter 2 scenes", "state": "active", "pid": "p-magi"},
        "mba-lec": {"what": "Lectures 3 + 4", "state": "active", "pid": "p-mba", "date": "2026-10-10"},
    })


def test_the_initiatives_carry_the_set_the_pace_the_goal_and_the_progress():
    inits = _inits()
    by = {i["id"]: i for i in inits}
    assert by["magi"]["active"] and by["magi"]["active_order"] == 0 and by["magi"]["pace"] == "2026-12-15"
    assert by["mba"]["active"] and by["mba"]["active_order"] == 1 and by["mba"]["pace"] == "2026-10-10"
    assert not by["trusts"]["active"] and by["trusts"]["active_order"] is None and by["trusts"]["pace"] == ""
    assert by["magi"]["done_when"] == "Artificial Magi done" and by["magi"]["open_count"] == 1 and by["magi"]["part_count"] == 1
    assert [i["id"] for i in hsp.active_set(inits)] == ["magi", "mba"], "the set in his order"
    assert [i["id"] for i in hsp.bench_of(inits)] == ["trusts", "paper"], "the bench by the nearest date, then the tiers"


def test_the_head_reads_the_active_set_first_and_the_pick_up_while_it_runs():
    inits = _inits()
    # nothing in the set needs him and both are running: the pick-up is the bench's nearest date
    act = ha.head_act(inits, [], today=TODAY)
    assert act is not None and act["kind"] == "tier1" and act["initiative"].startswith("The trusts"), "the tiers still lead when the set is quiet and a Tier-1 part needs him"
    # the same, but the trusts part does not need him: the head is None and the pick-up names the trusts by its deadline
    quiet = hsp.campaign_initiatives([dict(s, status="planned", waiting_on=None) if s["id"] == "trusts-pkg" else s for s in _steps()],
                                     {"magi-ch2": {"what": "Chapter 2 scenes", "state": "active", "pid": "p-magi"}, "mba-lec": {"what": "Lectures 3 + 4", "state": "active", "pid": "p-mba", "date": "2026-10-10"}})
    assert ha.head_act(quiet, [], today=TODAY) is None
    pk = ha.pick_up(quiet, [], working={"p-magi", "p-mba"}, today=TODAY)
    assert pk and pk["initiative"].startswith("The trusts") and pk["why"] == "due Oct 8" and pk["active"] == ["Artificial Magi", "MBA Teaching, Fall 2026"]
    s = ha.head_sentence(None, overnight=[], pickup=pk)
    assert s.startswith("Active: Artificial Magi and MBA Teaching, Fall 2026 are running. While they run: pick up The trusts and the holding company")
    assert "(due Oct 8)" in s
    # one runs, the other only waits on someone else: the sentence says so (Grok W1: never "running" for a wait)
    mixed = hsp.campaign_initiatives([dict(s, status="planned", waiting_on=None) if s["id"] == "trusts-pkg" else s for s in _steps()],
                                     {"magi-ch2": {"what": "Chapter 2 scenes", "state": "active", "pid": "p-magi"}, "mba-lec": {"what": "Lectures 3 + 4", "state": "waiting on Ryan", "pid": "p-mba", "date": "2026-10-10"}})
    pk = ha.pick_up(mixed, [], working={"p-magi"}, today=TODAY)
    assert pk and pk["running"] == ["Artificial Magi"] and pk["waiting"] == ["MBA Teaching, Fall 2026"]
    assert ha.head_sentence(None, pickup=pk).startswith("Active: Artificial Magi is running; MBA Teaching, Fall 2026 is waiting on someone else. Meanwhile: pick up The trusts")
    pk = ha.pick_up(mixed, [], working=set(), today=TODAY)
    assert pk is None, "Magi has a free hand: his next act, not a pick-up"
    only_wait = hsp.campaign_initiatives([dict(s, status="planned", waiting_on=None) if s["id"] == "trusts-pkg" else s for s in _steps()],
                                         {"magi-ch2": {"what": "Chapter 2 scenes", "state": "waiting on the editor", "pid": "p-magi"}, "mba-lec": {"what": "Lectures 3 + 4", "state": "waiting on Ryan", "pid": "p-mba"}})
    assert ha.head_sentence(None, pickup=ha.pick_up(only_wait, [], working=set(), today=TODAY)).startswith("Active: Artificial Magi and MBA Teaching, Fall 2026 are waiting on someone else. While they wait: pick up")
    # an active initiative with a free hand: no pick-up (that is his next act)
    assert ha.pick_up(quiet, [], working={"p-magi"}, today=TODAY) is None
    # a part that needs him INSIDE the set leads everything, whatever the tier order says
    needs = hsp.campaign_initiatives(_steps() + [
        {"id": "mba-hw", "name": "Homework 1 to grade", "status": "waiting", "waiting_on": "John to grade", "navigation": {"path": ["mba"]}}], {})
    act = ha.head_act(needs, [], today=TODAY)
    assert act["kind"] == "active" and act["initiative"] == "MBA Teaching, Fall 2026" and act["text"] == "Homework 1 to grade"
    assert ha.head_sentence(act).startswith("Active · MBA Teaching, Fall 2026: Homework 1 to grade")
    # an empty set: no pick-up, ever
    assert ha.pick_up([i for i in inits if not i["active"]], [], working=set(), today=TODAY) is None
    # an undated need inside the set outranks a due exception outside it (the outside deadline is W3's nudge)
    exc = hsp.campaign_initiatives(_steps() + [
        {"id": "mba-hw", "name": "Homework 1 to grade", "status": "waiting", "waiting_on": "John to grade", "navigation": {"path": ["mba"]}},
        {"id": "paper-fee", "name": "Pay the submission fee", "status": "waiting", "waiting_on": "John", "due": "2026-09-29", "navigation": {"path": ["paper"]}}], {})
    act = ha.head_act(exc, [], today=TODAY)
    assert act["kind"] == "active" and act["text"] == "Homework 1 to grade"
    # two due needs inside the set: HIS order, not the earlier date; the sentence says the date
    two = hsp.campaign_initiatives(_steps() + [
        {"id": "magi-edit", "name": "Read the editor's notes", "status": "waiting", "waiting_on": "John", "due": "2026-09-28", "navigation": {"path": ["magi"]}},
        {"id": "mba-hw", "name": "Homework 1 to grade", "status": "waiting", "waiting_on": "John to grade", "due": "2026-09-20", "navigation": {"path": ["mba"]}}], {})
    act = ha.head_act(two, [], today=TODAY)
    assert act["initiative"] == "Artificial Magi" and act["text"] == "Read the editor's notes" and act["overdue"] is True
    assert ha.head_sentence(act).startswith("Active \u00b7 Artificial Magi: Read the editor's notes \u2014 waiting on you, overdue since Sep 28.")


def _record(tmp_path):
    d = tmp_path / "Campaign"; d.mkdir()
    (d / "roadmap.json").write_text(json.dumps({"schema": "x", "roadmap_events": [], "roadmap_projection": _steps()}), encoding="utf-8")
    return str(d)


def test_the_four_acts_write_through_the_engine_with_undo(tmp_path, monkeypatch):
    d = _record(tmp_path)
    calls = []

    def fake_cli(project, *args):
        calls.append(list(args))
        # mirror the engine's effect on the stored projection so the next read sees it
        steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))
        sid = args[args.index("--step") + 1]
        for s in steps["roadmap_projection"]:
            if s["id"] == sid:
                if "--active" in args:
                    if args[args.index("--active") + 1] == "on": s["active"] = True
                    else: s.pop("active", None); s.pop("active_order", None)
                if "--active-order" in args: s["active_order"] = int(args[args.index("--active-order") + 1])
                if "--pace" in args:
                    v = args[args.index("--pace") + 1]
                    if v == "none": s.pop("pace", None)
                    else: s["pace"] = v
        (tmp_path / "Campaign" / "roadmap.json").write_text(json.dumps(steps), encoding="utf-8")
        return {"ok": True}
    monkeypatch.setattr(acts, "_cli", fake_cli)
    r = acts.act(d, {"act": "activate", "step": "trusts"})
    assert r["ok"] and r["receipt"].startswith("The trusts and the holding company is active") and r["undo"] == {"act": "bench", "step": "trusts"}
    assert calls[-1] == ["roadmap-set", "--step", "trusts", "--active", "on", "--active-order", "2"], "at the foot of the set"
    r = acts.act(d, {"act": "activate", "step": "paper"})
    assert "wider than three" in r["receipt"], "a fourth is named, never refused (his word: no cap)"
    r = acts.act(d, {"act": "order", "step": "trusts", "position": 0})
    assert r["ok"] and r["receipt"].startswith("The trusts and the holding company is first in the set") and r["undo"] == {"act": "order", "step": "trusts", "position": 2}
    assert [x["id"] for x, g in acts._active(d)] == ["trusts", "magi", "mba", "paper"]
    r = acts.act(d, {"act": "bench", "step": "magi"})
    assert r["ok"] and r["undo"] == {"act": "activate", "step": "magi", "order": 1}
    assert [x["id"] for x, g in acts._active(d)] == ["trusts", "mba", "paper"] and [x.get("active_order") for x, g in acts._active(d)] == [0, 1, 2], "the set closes up"
    assert acts._step(d, "magi").get("pace") == "2026-12-15", "the pace stays on a benched initiative"
    r = acts.act(d, {"act": "pace", "step": "magi", "when": "2027-01-31"})
    assert r["ok"] and r["receipt"] == "Artificial Magi: the pace is now 2027-01-31" and r["undo"] == {"act": "pace", "step": "magi", "when": "2026-12-15"}
    r = acts.act(d, {"act": "pace", "step": "magi", "when": "none"})
    assert r["ok"] and r["receipt"].endswith("cleared")
    assert not acts.act(d, {"act": "bench", "step": "magi"})["ok"], "benching a benched one is refused"
    assert not acts.act(d, {"act": "order", "step": "magi", "position": 0})["ok"], "ordering a benched one is refused"
    # the undo of a bench puts it back at its index and the others shift, no tie (Grok W1)
    r = acts.act(d, {"act": "activate", "step": "magi", "order": 1})
    assert r["ok"] and [(x["id"], x["active_order"]) for x, g in acts._active(d)] == [("trusts", 0), ("magi", 1), ("mba", 2), ("paper", 3)]
    # one outcome per act: when the set cannot close up after a bench, the receipt is refused and carries no undo
    real = acts._cli
    def failing(project, *args):
        if "--active-order" in args:
            return {"ok": False, "error": "disk full"}
        return real(project, *args)
    monkeypatch.setattr(acts, "_cli", failing)
    r = acts.act(d, {"act": "bench", "step": "trusts"})
    assert not r["ok"] and "could not close up" in r["receipt"] and not r.get("undo")


def test_the_spoken_verbs_apply_and_a_bare_by_that_names_no_initiative_goes_to_the_steward(tmp_path, monkeypatch):
    d = _record(tmp_path)
    monkeypatch.setattr(acts, "_cli", lambda project, *args: {"ok": True})
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_activate", "args": {"initiative": "paper 1"}})
    r = say.say_campaign(d, "make paper 1 active", today=TODAY)
    assert r and r["ok"] and r["act"] == "campaign_activate" and r["campaign_act"]
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_bench", "args": {"initiative": "artificial magi"}})
    r = say.say_campaign(d, "bench artificial magi", today=TODAY)
    assert r and r["ok"] and r["act"] == "campaign_bench"
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_pace", "args": {"initiative": "mba teaching", "pace": "Oct 10"}})
    r = say.say_campaign(d, "set the pace of mba teaching to Oct 10", today=TODAY)
    assert r and r["ok"] and r["act"] == "campaign_pace" and "2026-10-10" in r["receipt"]
    # the bare "<name> by <date>" is read by the applier against the names (the engine's grammar no longer carries it):
    # the whole name or the start of exactly one name writes; an interior word or no name goes to the steward
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": False, "campaign": False})
    written = []
    monkeypatch.setattr(acts, "_cli", lambda project, *args: (written.append(list(args)), {"ok": True})[1])
    r = say.say_campaign(d, "MBA by Oct 10", today=TODAY)
    assert r and r["ok"] and r["act"] == "campaign_pace" and written[-1] == ["roadmap-set", "--step", "mba", "--pace", "2026-10-10"]
    r = say.say_campaign(d, "the trusts by Oct 8.", today=TODAY)
    assert r and r["ok"] and written[-1][2] == "trusts"
    n = len(written)
    assert say.say_campaign(d, "teaching by Monday", today=TODAY) is None, "an interior word names nothing"
    assert say.say_campaign(d, "review the draft by tuesday", today=TODAY) is None, "no initiative named: the steward takes the words"
    assert say.say_campaign(d, "MBA by the end of the world", today=TODAY) is None, "not a date: the steward takes the words"
    assert len(written) == n, "nothing written for any of them"
    monkeypatch.setattr(say, "compile_utterance", lambda text, dialogue=None: {"ok": True, "campaign": True, "act": "campaign_pace", "args": {"initiative": "nothing here", "pace": "tuesday"}})
    r = say.say_campaign(d, "set the pace of nothing here to tuesday", today=TODAY)
    assert r and not r["ok"], "an explicit pace verb that names no initiative is refused with the names"


def test_the_page_leads_with_the_pick_up_while_the_set_runs():
    """The brief's lead is rendered by the page from the head itself; with no head and a pick-up, the pick-up leads
    and its button opens the picked project."""
    import sys as _s; _s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import test_high_seat_page_2026_09_26 as t
    ctx = t._ctx(); ctx["head"] = None
    ctx["pickup"] = {"initiative": "The trusts and the holding company", "id": "trusts", "why": "due Oct 8", "text": "Send the Stanford package", "pid": "p-trusts", "active": ["Artificial Magi", "MBA Teaching, Fall 2026"]}
    html = hsp.render_high_seat_html(ctx)
    i = html.index('class="lead"')
    lead = html[i:i + 400]
    assert "Active: Artificial Magi and MBA Teaching, Fall 2026 are running. While they run: pick up The trusts" in lead
    assert 'data-pid="p-trusts"' in lead, "the pick-up's button opens the picked project"
    ctx["pickup"] = None
    html = hsp.render_high_seat_html(ctx)
    assert "Nothing is waiting on you." in html[html.index('class="lead"'):][:200]
