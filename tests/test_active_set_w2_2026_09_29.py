"""W2 of the active set (2026-09-29, A1 + C1): the goals band - every initiative's goal, pace, next deadline and
progress; the active set as one list in his order, the bench as another by nearest date; the rows drag and every
drop is one act with undo; the composer directly under the brief; the brief's lead the set's sentence."""
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_active_set_w1_2026_09_29 as w1  # noqa: E402
import test_campaign_page_2026_09_26 as base  # noqa: E402
from steward_cockpit import campaign_acts as acts  # noqa: E402

TODAY = date(2026, 9, 29)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ctx(steps=None, working=None):
    ctx = base._ctx()
    ctx["today"] = TODAY
    ctx["initiatives"] = hsp.campaign_initiatives(steps or w1._steps(), {
        "magi-ch2": {"what": "Chapter 2 scenes", "state": "active", "pid": "p-magi"},
        "mba-lec": {"what": "Lectures 3 + 4", "state": "active", "pid": "p-mba", "date": "2026-10-10"}})
    ctx["working"] = working if working is not None else {"p-magi", "p-mba"}
    return ctx


def test_the_goals_band_shows_the_set_first_then_the_bench_with_goal_pace_deadline_and_progress():
    html = cpg.render_campaign_html(_ctx())
    band = html[html.index('<section class="goals"'):html.index('<div class="colk"><h3 id="viewTitle">')]
    assert band.index('data-list="active"><h4>') < band.index('data-list="bench"><h4>'), "Active above the bench"
    rows = re.findall(r'data-init="([^"]+)" data-list="([^"]+)"', band)
    assert rows == [("magi", "active"), ("mba", "active"), ("trusts", "bench"), ("paper", "bench")], "his order, then the bench by nearest date"
    assert band.count('draggable="true"') == 4
    magi = band[band.index('data-init="magi"'):band.index('data-init="mba"')]
    assert "Artificial Magi done" in magi and "by Dec 15" in magi and 'class="gd dim">&mdash;' in magi and "0 of 1 part" in magi
    mba = band[band.index('data-init="mba"'):band.index('data-init="trusts"')]
    assert "by Oct 10" in mba and "Oct 10 &middot; Lectures 3 + 4" in mba and 'class="glight working"' in mba
    trusts = band[band.index('data-init="trusts"'):band.index('data-init="paper"')]
    assert "no pace set" in trusts and 'class="gd">Oct 8 &middot; Send the Stanford package' in trusts and "a part waits on you" in trusts
    assert 'data-goto="trusts"' in trusts, "the name opens its tile"
    assert "Active <b>2</b>" in band and "the bench <b>2</b>" in band and "wider than three" not in band
    # the tiers below are as they were
    assert "Initiatives by tier" in html and 'data-lane="magi"' in html


def test_a_set_wider_than_three_is_named_never_refused_and_an_empty_set_says_so():
    steps = [dict(s, active=True, active_order=k) if s.get("navigation", {}).get("groups") else s for k, s in enumerate(w1._steps())]
    html = cpg.render_campaign_html(_ctx(steps))
    assert "4 active is wider than three &mdash; the steward would keep to three" in html
    steps = [dict((k, v) for k, v in s.items() if k not in ("active", "active_order")) for s in w1._steps()]
    html = cpg.render_campaign_html(_ctx(steps))
    assert "nothing active yet &mdash; drag an initiative here" in html


def test_the_composer_sits_under_the_brief_and_the_brief_leads_with_the_set():
    html = cpg.render_campaign_html(_ctx())
    panel = html[html.index('<aside class="panel"'):]
    assert panel.index('id="brief"') < panel.index('class="composer"') < panel.index('class="exwrap"'), "brief, composer, then the conversation"
    lead = panel[panel.index('<li class="lead">'):panel.index('<li class="fold">')]
    assert lead.startswith('<li class="lead">Tier 1 ') and "The trusts and the holding company: Send the Stanford package" in lead, "the set is quiet and a Tier-1 part needs him: the tiers lead, as W1 says"
    # the trusts part does not need him: the set runs, the pick-up leads
    quiet = [dict(s, status="planned", waiting_on=None) if s["id"] == "trusts-pkg" else s for s in w1._steps()]
    html = cpg.render_campaign_html(_ctx(quiet))
    panel = html[html.index('<aside class="panel"'):]
    lead = panel[panel.index('<li class="lead">'):panel.index('<li class="fold">')]
    assert lead.startswith('<li class="lead">Active: Artificial Magi and MBA Teaching, Fall 2026 are running. While they run: pick up The trusts and the holding company')
    assert 'data-goto="trusts">open</button>' in lead
    assert "<summary>the rest, by tier</summary>" in panel and "<b>Tier 1</b> holds" in panel, "the rest folded, not lost"
    # a set with a part needing him inside it: that leads
    steps = w1._steps() + [{"id": "mba-hw", "name": "Homework 1 to grade", "status": "waiting", "waiting_on": "John to grade", "navigation": {"path": ["mba"]}}]
    html = cpg.render_campaign_html(_ctx(steps, working=set()))
    assert '<li class="lead">Active &middot; MBA Teaching, Fall 2026: Homework 1 to grade' in html.replace("·", "&middot;") or "Active · MBA Teaching, Fall 2026: Homework 1 to grade" in html
    # no set: the lead is the tiers' line as before
    steps = [dict((k, v) for k, v in s.items() if k not in ("active", "active_order")) for s in w1._steps()]
    html = cpg.render_campaign_html(_ctx(steps))
    assert '<li class="lead"><b>Tier 1</b> holds' in html


def test_lint_a_drop_is_one_act_with_the_record_s_words():
    js = open(os.path.join(HERE, "static", "campaign-page.js"), encoding="utf-8").read()
    drag = js[js.index("var dragId"):js.index("// the tools")]
    assert "act({ act: 'bench', step: id })" in drag and "act({ act: 'order', step: id, position: k })" in drag and "act({ act: 'activate', step: id, order: k })" in drag
    assert drag.count("act({") == 3, "three drops, three acts, nothing else"
    assert "location.reload" not in drag, "the page changes only when the record has (the act's own reload)"
    css = open(os.path.join(HERE, "static", "campaign-page.css"), encoding="utf-8").read()
    assert ".grow[draggable]{cursor:grab" in css and ".glist.over{" in css


def test_a_drop_into_active_at_a_position_inserts_and_the_others_close_up(tmp_path, monkeypatch):
    d = w1._record(tmp_path)
    monkeypatch.setattr(acts, "_cli", _fake_cli(tmp_path))
    r = acts.act(d, {"act": "activate", "step": "trusts", "order": 0})
    assert r["ok"] and r["undo"] == {"act": "bench", "step": "trusts"}
    assert [(x["id"], x.get("active_order")) for x, g in acts._active(d)] == [("trusts", 0), ("magi", 1), ("mba", 2)]
    r = acts.act(d, {"act": "order", "step": "mba", "position": 0})
    assert r["ok"] and r["undo"] == {"act": "order", "step": "mba", "position": 2}
    assert [x["id"] for x, g in acts._active(d)] == ["mba", "trusts", "magi"]


def _fake_cli(tmp_path):
    def fake_cli(project, *args):
        steps = json.loads((tmp_path / "Campaign" / "roadmap.json").read_text(encoding="utf-8"))
        sid = args[args.index("--step") + 1]
        for s in steps["roadmap_projection"]:
            if s["id"] == sid:
                if "--active" in args:
                    if args[args.index("--active") + 1] == "on": s["active"] = True
                    else: s.pop("active", None); s.pop("active_order", None)
                if "--active-order" in args: s["active_order"] = int(args[args.index("--active-order") + 1])
        (tmp_path / "Campaign" / "roadmap.json").write_text(json.dumps(steps), encoding="utf-8")
        return {"ok": True}
    return fake_cli
