"""campaign_page — the Campaign, version D: John's initiatives in three priority tiers, and the same record
against the five-week ruler behind one button.

W3c of the High Seat plan (2026-09-26). The approved design is the mockup
``Skill Foundry/planning/high-seat-2026-09-24/ideation/mockups/campaign/campaign-D.html``; its stylesheet is
``static/campaign-page.css`` ported as it is. This module renders that page from the Campaign record —
the initiatives (heading steps with tier, area, outcome, their root group's order), their parts (steps whose
path starts with the initiative; a ``ref`` part read through the resolver), the strip's seeds — plus the
steward livery and the effort's own conversation. Pure: a context dict in, HTML out. Every count on the
page is counted from the record. The acts on the page go through ``steward_cockpit/campaign_acts``.
"""
from __future__ import annotations

from datetime import timedelta

import home_rows as _hr
from high_seat_page import esc, _brand_img, _masthead, ruler_weeks, LIGHTS, initiative_light, initiative_line, initiative_status_html, active_set, bench_of
import home_attention as _ha

TIER_WORDS = {1: "do first", 2: "next in line", 3: "when there is room"}
TIER_COLOURS = {1: "#6c9cfc", 2: "#8b93a6", 3: "#5f6674"}
AREA_COLOURS = {"family": "#e78aa6", "professional": "#6c9cfc", "writing": "#a78bfa", "research": "#4fc9c2",
                "tools": "#94a3b8", "personal": "#d0975f"}
AREAS = ("family", "professional", "writing", "research", "tools", "personal")


def _short(d):
    return _hr.short_date(d) if d else ""


def _needs(n, noun="part"):
    """"⚑ 2 parts need you" — the noun said (Grok R8: the board counts parts, a tier header counts initiatives)."""
    return "&#9873; %d %s%s need%s you" % (n, noun, "" if n == 1 else "s", "s" if n == 1 else "")


def _part_state(p):
    # W1 (2026-09-28): a referenced part's done/closed comes from the RESOLVED target too (campaign_initiatives'
    # `done` / `closed` flags), never the wrapper's status alone
    if p["broken"]:
        return "broken reference"
    if p.get("done", p["status"] == "done"):
        return "done"
    if p["status"] == "parked" or p.get("target_status") == "parked":
        return "parked"
    if p["needs_you"]:
        return "needs you"
    return p["state"] or p["status"] or "open"


# ── the board: grouped view ────────────────────────────────────────────────────────────────────

def _part_row(i, p, today, tick_allowed):
    pid = esc(p["id"])
    done = bool(p.get("done", p["status"] == "done"))
    ref = p["kind"] != "task"
    date_chip = (('<button class="mchip dated" data-act="date" data-part="%s">%s</button>' % (pid, esc(_short(p["date"])))) if p["date"] else
                 ('<button class="mchip" data-act="date" data-part="%s">no date</button>' % pid)) if not ref else (
        ('<span class="mchip dated" title="its date lives in its own record">%s</span>' % esc(_short(p["date"]))) if p["date"] else '<span class="mchip" title="its date lives in its own record">no date</span>')
    state = _part_state(p)
    state_chip = ('<span class="mchip donew">&#10003; done</span>' if done else
                  ('<span class="mchip flagon">&#9873; needs you</span>' if p["needs_you"] else
                   ('<span class="mchip state" style="color:var(--amber-t)">%s</span>' % esc("broken reference: " + p["gap"]) if p["broken"] else
                    '<span class="mchip state">%s</span>' % esc(state))))
    flag_chip = ("" if ref or done else (
        ('<button class="mchip flagon" data-act="unflag" data-part="%s">&#9873; needs you &middot; clear</button>' % pid) if p["needs_you"] else
        ('<button class="mchip" data-act="flag" data-part="%s">&#9873; flag it</button>' % pid)))
    link = ('<a class="mchip proj" href="%s" target="_blank" rel="noopener">%s &rarr; cockpit</a>' % (esc(p["href"]), esc(p["target"] or p["kind"]))) if p["href"] else ""
    park = (('<button class="mchip" data-act="unpark" data-part="%s">unpark</button>' % pid) if p["status"] == "parked" else
            ('<button class="mchip" data-act="park" data-part="%s">park</button>' % pid)) if not ref else ""
    tick = (('<button class="tick%s" data-act="tick" data-part="%s" aria-label="mark done"%s></button>' % (
        " on" if done else "", pid, "" if (tick_allowed and not ref) else ' disabled title="a tick waits on your word on the close law"'))
            if not ref else (('<a class="tickpad%s" href="%s" target="_blank" rel="noopener" title="done or parked in its own record &mdash; open it"></a>' % (" on" if done else "", esc(p["href"])))
                             if p["href"] else '<span class="tickpad" title="a referenced part is closed in its own record"></span>'))
    name = ('<span class="rt" data-act="name" data-part="%s">%s</span>' % (pid, esc(p["text"]))) if not ref else ('<span class="rt">%s</span>' % esc(p["text"]))
    return ('<li class="row%s%s" data-part="%s">%s<div class="rb">%s<div class="rm">'
            '<span class="mchip kind">%s</span>%s%s%s%s%s'
            '</div></div></li>' % (
                " done" if done else "", " pparked" if p["status"] == "parked" else "", pid, tick, name,
                esc(p["kind"]), date_chip, flag_chip, state_chip, link, park))


def _gtile(i, ctx, band):
    """One goal on the board (W2 v2, his lock of 11:0x): its number, its name (opens its place), its tier and light,
    the goal in a line, the next thing, and the facts — progress, pace, next deadline, what waits on him. It drags."""
    today = ctx["today"]
    glyph, word = LIGHTS[initiative_light(i, ctx.get("working") or set())]
    one, kind = initiative_line(i)
    n, done = len(i["parts"]), int(i.get("done_count") or 0)
    pct = int(round(100.0 * done / n)) if n else 0
    nd = i.get("next_deadline") or ""
    nd_d = _hr._iso(nd) if nd else None
    dcls = ("over" if nd_d and nd_d < today else ("soon" if nd_d and (nd_d - today).days <= 7 else ""))
    return (
        '<article class="gtile%s%s" draggable="true" data-lane="%s" data-band="%s" style="--areac:%s">'
        '<div class="ihead"><span class="pnum" title="priority %d of %d">%d</span><button class="iname" data-open="%s" title="open its place">%s</button>'
        '<span class="gtier">tier %s</span><span class="ilight %s" title="the light: needs you · working · waiting · idle, read from its parts">%s %s</span></div>'
        '<div class="ggoal" title="%s">%s</div>%s'
        '<div class="gfacts"><span class="gprog"><span class="bar"><i style="width:%d%%"></i></span>%d of %d</span><span class="%s">%s</span><span class="gdl %s">%s</span>%s</div></article>'
    ) % (" needs" if i["needs"] else "", " active" if i.get("active") else "", esc(i["id"]), band, AREA_COLOURS.get(i["area"], "#8b93a6"),
         i["number"], ctx["n_total"], i["number"], esc(i["id"]), esc(i["name"]), i["tier"] or "?",
         initiative_light(i, ctx.get("working") or set()), glyph, word,
         esc(i["done_when"]), esc(i["done_when"]) or '<span class="dim">no goal written yet</span>',
         ('<div class="iline %s">%s</div>' % (kind, one)) if kind in ("wait", "next") else "",      # never the goal twice
         pct, done, n, "" if i.get("pace") else "dim", ("pace " + esc(_short(i["pace"]))) if i.get("pace") else "no pace",
         dcls, (("overdue " if dcls == "over" else "next ") + esc(_short(nd))) if nd else "no deadline",
         (' <span class="am">&#9873; %s</span>' % _needs(len(i["needs"]))) if i["needs"] else "")


def _band(key, label, note, items, ctx, cls=""):
    tiles = "".join(_gtile(i, ctx, key) for i in items)
    empty = ('nothing active yet &mdash; drag a goal here, or tell the steward &ldquo;make &hellip; active&rdquo;' if key == "active" else "nothing in this tier")
    return ('<section class="band%s" data-band="%s"><h4 class="band-h">%s <span class="c">%s</span></h4>'
            '<div class="tiles">%s</div></section>' % ((" " + cls) if cls else "", key, label, note, tiles or '<div class="empty">%s</div>' % empty))


def _bands(ctx):
    """The goal board: bands Active (his set, his order) · Tier 1 · 2 · 3 (his tiers, his order) · no tier yet."""
    inits = ctx["initiatives"]
    act = active_set(inits)
    rest = [i for i in inits if not i.get("active")]
    out = [_band("active", "Active", "what you are on now, in your order &middot; drag a goal in or out, whatever its tier", act, ctx, "active")]
    for t in (1, 2, 3):
        mine = [i for i in rest if i["tier"] == t]
        needs = sum(1 for i in mine if i["needs"])
        out.append(_band(str(t), "Tier %d" % t, "%s &middot; %d goal%s%s" % (TIER_WORDS[t], len(mine), "" if len(mine) == 1 else "s",
                         (' &middot; <span class="am">%s</span>' % _needs(needs, "goal")) if needs else ""), mine, ctx))
    untiered = [i for i in rest if i["tier"] is None]
    if untiered:
        out.append(_band("none", "No tier yet", "give each a tier &mdash; drag it into one", untiered, ctx))
    return '<div class="bands" id="viewGrouped">%s</div>' % "".join(out)


def _thread(i, ctx):
    turns = (ctx.get("goal_turns") or {}).get(i["id"]) or []
    if not turns:
        return '<li class="exfade">Nothing said about this goal yet.</li>'
    return "".join('<li class="exrow %s"><div class="exw %s">%s<span class="t">%s</span></div><div class="ext">%s</div></li>' % (
        "you" if t["you"] else "st", "you" if t["you"] else "st", "You" if t["you"] else esc(ctx["steward"]["label"]), esc(t["at"]), esc(t["text"][:900])) for t in turns[-12:])


def _place(i, ctx):
    """The goal's place (fit 10): the goal to revise, where it stands, the pace and the deadlines, the workflow
    (the parts with their acts, as the tile's body had them), the projects and cockpits, and the goal's own
    conversation. Rendered for every goal, shown for the one he opens — UNDER the bands, which stay at the top
    with their tiles shortened to a name (his 13:2x word: the list of goals first, the large details on a click)."""
    today = ctx["today"]
    glyph, word = LIGHTS[initiative_light(i, ctx.get("working") or set())]
    tier_opts = "".join('<option value="%d"%s>%d &middot; %s</option>' % (t, " selected" if i["tier"] == t else "", t, TIER_WORDS[t]) for t in (1, 2, 3))
    rows = "".join(_part_row(i, p, today, ctx.get("tick_allowed", False)) for p in i["parts"])
    projects = "".join('<option value="%s">%s</option>' % (esc(e.get("id")), esc(e.get("name"))) for e in ctx.get("projects") or [])
    n, done = len(i["parts"]), int(i.get("done_count") or 0)
    waits = [p for p in i["needs"]]
    nxt = i["next"]
    dated = sorted([p for p in i["parts"] if p["date"] and not p["broken"] and p["status"] not in ("done", "parked")], key=lambda p: p["date"])
    stands = "%s%s%s%s%s." % (
        ("%d of %d part%s done" % (done, n, "" if n == 1 else "s")) if n else "no parts yet",
        ('; <span class="am">%d wait%s on you &mdash; %s</span>' % (len(waits), "s" if len(waits) == 1 else "", esc(waits[0]["text"]))) if waits else "",
        ("; the next deadline is <b>%s</b>" % esc(_short(i["next_deadline"]))) if i["next_deadline"] else "; nothing dated",
        ("; the pace is <b>%s</b>" % esc(_short(i["pace"]))) if i.get("pace") else "; no pace set",
        (". Next: <b>%s</b>" % esc(nxt["text"])) if nxt else "")
    projs = [p for p in i["parts"] if p["kind"] == "project"]
    proj_html = "".join('<div class="proj">%s<span class="st">%s</span></div>' % (
        ('<a href="%s" target="_blank" rel="noopener">%s &#8599;</a>' % (esc(p["href"]), esc(p["target"] or p["text"]))) if p.get("href") else esc(p["target"] or p["text"]),
        esc(p["state"] or p["status"] or "")) for p in projs) or '<div class="proj dim">no project yet &mdash; add one as a part (kind: project)</div>'
    return (
        '<article class="place" id="place-%s" data-goal="%s" hidden style="--areac:%s"><div class="ptop"><span class="pname">%s</span>'
        '<span class="ilight %s">%s %s</span><div class="imore"><span class="larea">%s</span><span class="tierpick">Tier <select class="tsel" data-tiersel="%s">%s</select></span></div>'
        '<span class="pact">%s</span><button class="mini" data-close="1">close</button></div>'
        '<div class="pcols"><div>'
        '<div class="k">The goal &middot; done when <span class="h">(click to revise &mdash; one line with undo)</span></div><div class="g" data-goal-text="%s">%s</div>'
        '<div class="k">Where it stands</div><div class="stand">%s</div>%s'
        '<div class="facts3"><div class="fact"><div class="k">Pace</div><span class="v click" data-pace="%s">%s</span></div>'
        '<div class="fact"><div class="k">Deadlines</div><span class="v">%s</span></div></div>'
        '<div class="obody"><div class="plist"><div class="pl-h"><h4>The workflow &middot; the parts in order</h4><span class="c">%d &middot; %d dated%s</span>'
        '<span class="hint">Click a name to rename, a date to move it. A referenced part is read from its own record.</span></div>'
        '<ul class="rows">%s</ul>'
        '<div class="addline"><select data-add="kind"><option value="task">task</option><option value="project">project</option></select>'
        '<input class="at" data-add="text" data-lane="%s" type="text" autocomplete="off" placeholder="Add a part">'
        '<select data-add="project" style="display:none"><option value="">which project</option>%s</select>'
        '<input class="ad" data-add="date" type="text" autocomplete="off" placeholder="2026-10-27 &middot; blank">'
        '<button class="mk" data-act="add" data-lane="%s">Add</button>'
        '<span class="ah">Enter adds it. No date and it sits in the <b>no date</b> column of the calendar view.</span></div></div></div>'
        '<div class="k">Projects and cockpits <span class="h">(the projects this goal runs through)</span></div>%s'
        '</div><div>'
        '<div class="k" style="margin-top:0">The conversation about this goal <span class="h">(dictate; a verb acts on this goal, talk goes to the steward told which goal; both answer here)</span></div>'
        '<div class="gconv"><ul class="ex gthread" data-thread="%s">%s</ul>'
        '<div class="composer gcomp"><label class="sr" for="gsay-%s">Tell the steward about this goal</label>'
        '<textarea id="gsay-%s" class="gsay" data-goal="%s" rows="2" placeholder="add a part: &hellip; &middot; pace by Oct 10 &middot; make it active &middot; tier 2 &middot; goal: &hellip; &middot; summarize &middot; or just talk"></textarea>'
        '<div class="comp-row"><span class="hint">Ctrl+Enter sends &middot; inside this goal nothing needs its name &middot; the answer appears here</span><button class="send gsend" data-goal="%s">Send</button></div>'
        '<div class="chips"><button data-say="summarize where this goal stands">summarize</button><button data-say="what is the next step?">what is the next step?</button><button data-say="what is starving here?">what is starving?</button></div></div></div>'
        '</div></div></article>'
    ) % (esc(i["id"]), esc(i["id"]), AREA_COLOURS.get(i["area"], "#8b93a6"), esc(i["name"]),
         initiative_light(i, ctx.get("working") or set()), glyph, word, esc(i["area"].title() or "no area"), esc(i["id"]), tier_opts,
         ('active &middot; <button class="linkish" data-bench="%s">bench it</button>' % esc(i["id"])) if i.get("active") else ('<button class="linkish" data-activate="%s">make it active</button>' % esc(i["id"])),
         esc(i["id"]), esc(i["done_when"]) or '<span class="dim">not written yet &mdash; say what done looks like</span>',
         stands, initiative_status_html(i),
         esc(i["id"]), ("by " + esc(_short(i["pace"]))) if i.get("pace") else "set a pace",
         "<br>".join('<span class="%s">%s</span> %s' % ("over" if (_hr._iso(p["date"]) or today) < today else ("soon" if (_hr._iso(p["date"]) - today).days <= 7 else ""), esc(_short(p["date"])), esc(p["text"][:36]) + ("&hellip;" if len(p["text"]) > 36 else "")) for p in dated[:4]) or "none dated",
         n, len(dated), (' &middot; <span class="am">%s</span>' % _needs(len(i["needs"]))) if i["needs"] else "",
         rows or '<li class="row"><div class="rb"><span class="rt dim">no parts yet</span></div></li>', esc(i["id"]), projects, esc(i["id"]),
         proj_html,
         esc(i["id"]), _thread(i, ctx), esc(i["id"]), esc(i["id"]), esc(i["id"]), esc(i["id"]))


def _places(ctx):
    return '<div id="placeSlot"></div>' + "".join(_place(i, ctx) for i in ctx["initiatives"])


# ── the board: calendar view (the same record, re-bucketed) ────────────────────────────────────

def _calendar(ctx):
    today = ctx["today"]
    weeks = ruler_weeks(today)
    inits = ctx["initiatives"]
    monday = weeks[0]["start"]

    # cells: 0 = no date (undated, and parked — a parked part is never on the ruler); 7 = before this week (a past
    # date: overdue while open, done with its date otherwise); 1–5 = the weeks; 6 = beyond the ruler
    def bucket(p):
        d = _hr._iso(p["date"]) if p["date"] else None
        if d is None or p["status"] == "parked":
            return 0
        if d < monday:
            return 7
        for k, w in enumerate(weeks):
            if w["start"] <= d <= w["end"]:
                return k + 1
        return 6
    counts = [0] * 8
    overdue = parked_dated = 0
    for i in inits:
        for p in i["parts"]:
            b = bucket(p)
            counts[b] += 1
            if b == 7 and p["status"] != "done" and not p["broken"]:
                overdue += 1
            if b == 0 and p["date"] and p["status"] == "parked":
                parked_dated += 1
    has_over = counts[7] > 0
    order = [0] + ([7] if has_over else []) + [1, 2, 3, 4, 5, 6]
    head = ['<div class=" nod"><b>No date</b><span class="sm">undated and parked parts</span><span class="cn">%d undated%s</span></div>' % (
        counts[0] - parked_dated, (" &middot; %d parked" % parked_dated) if parked_dated else "")]
    if has_over:
        head.append('<div class=" over"><b>Before this week</b><span class="sm">past dates</span><span class="cn">%s</span></div>' % (
            ("%d overdue" % overdue) if overdue else ("%d done" % counts[7])))
    for k, w in enumerate(weeks):
        head.append('<div class="%s"><b>%s</b><span class="sm">%s</span><span class="cn">%s</span></div>' % (
            "now" if k == 0 else "", esc(w["label"]), esc(w["name"]), ("%d dated" % counts[k + 1]) if counts[k + 1] else "nothing dated"))
    head.append('<div class=" beyond"><b>%s &rarr;</b><span class="sm">beyond the ruler</span><span class="cn">%s</span></div>' % (
        esc(_hr.short_date((weeks[-1]["end"] + timedelta(days=1)).isoformat())), ("%d dated" % counts[6]) if counts[6] else "nothing dated"))

    def chip(i, p, past):
        pdone = bool(p.get("done", p["status"] == "done"))
        pclosed = bool(p.get("closed", p["status"] in ("done", "parked")))
        late = past and not pclosed and not p["broken"]
        cls = " need" if p["needs_you"] else (" done" if pdone else (" over" if late else ""))
        tail = ('<span class="pc-f">&#9873; needs you</span>' if p["needs_you"] else
                ('<span class="pc-s ok">&#10003; done</span>' if pdone else
                 ('<span class="pc-f">overdue</span>' if late else ('<span class="pc-c">parked</span>' if (pclosed and not pdone) else ""))))
        return ('<button class="pc%s" data-act="chip" data-lane="%s" data-part="%s"><span class="pc-top"><span class="pc-d">%s</span><span class="pc-k">%s</span></span>'
                '<span class="pc-n">%s</span>%s</button>' % (cls, esc(i["id"]), esc(p["id"]), esc(_short(p["date"])) if p["date"] else "no date", esc(p["kind"]), esc(p["text"]), tail))

    def cell_class(k):
        return " now" if k == 1 else (" beyond" if k == 6 else (" over" if k == 7 else ""))

    def lane(i):
        cells = [[] for _ in range(8)]
        for p in i["parts"]:
            b = bucket(p)
            cells[b].append(chip(i, p, b == 7))
        track = "".join('<div class="cell%s">%s</div>' % (cell_class(k), "".join(cells[k])) for k in order)
        return (
            '<section class="lane" data-lane="%s" style="--areac:%s"><div class="lane-h"><div class="rankbox"><b class="rnum">%s</b></div>'
            '<button class="lane-t" data-act="toggle" data-lane="%s"><span class="lrow1"><span class="ln">%s</span><span class="larea" style="--areac:%s">%s</span></span>'
            '<span class="ldone"><span class="k">Done looks like</span>%s</span></button><span class="lmeta">%s%d parts &middot; %d dated</span></div>'
            '<div class="track">%s</div></section>' % (
                esc(i["id"]), AREA_COLOURS.get(i["area"], "#8b93a6"), i["number"] if i["tier"] else "&ndash;", esc(i["id"]), esc(i["name"]), AREA_COLOURS.get(i["area"], "#8b93a6"),
                esc(i["area"].title() or "no area"), esc(i["done_when"]) or "not written yet",
                ('<span class="fl">%s</span>' % _needs(len(i["needs"]))) if i["needs"] else "",
                len(i["parts"]), sum(1 for p in i["parts"] if p["date"] and p["status"] not in ("done", "parked") and not p["broken"]), track))

    def strip(label, word, colour, mine):
        needs = sum(1 for i in mine if i["needs"])
        dated = sum(1 for i in mine for p in i["parts"] if p["date"] and p["status"] not in ("done", "parked") and not p["broken"])
        return '<div class="tierstrip" style="--tierc:%s"><span class="tn">%s</span><span class="tw">%s</span><span class="tm">%d initiative%s &middot; %s &middot; %d dated part%s</span></div>' % (
            colour, label, word, len(mine), "" if len(mine) == 1 else "s", ('<span class="am">%s</span>' % _needs(needs, "initiative")) if needs else "no initiative needs you", dated, "" if dated == 1 else "s")
    lanes = []
    for t in (1, 2, 3):
        mine = [i for i in inits if i["tier"] == t]
        lanes.append(strip("Tier %d" % t, TIER_WORDS[t], TIER_COLOURS[t], mine))
        lanes.extend(lane(i) for i in mine)
    untiered = [i for i in inits if i["tier"] is None]
    if untiered:
        lanes.append(strip("No tier yet", "give each a tier", "#5f6674", untiered))
        lanes.extend(lane(i) for i in untiered)
    return '<div class="scroll%s" id="viewCal" style="flex:1;display:none"><div id="boardScroll"><div class="rl-head">%s</div>%s</div></div>' % (
        " has-over" if has_over else "", "".join(head), "".join(lanes))


# ── seeds, areas, the panel ────────────────────────────────────────────────────────────────────

def _seedband(ctx):
    """The seeds as a tile (John, 2026-09-27): closed by default with the count in its head; the head toggles it open to
    the seed row as it was — each seed with Make it an initiative and its two questions on the card."""
    seeds = ctx.get("seeds") or []
    if not seeds:
        row = '<div class="seed"><div class="st dim">No seeds yet.</div><div class="sw">Tell the steward &ldquo;seed: &hellip;&rdquo; on the home, or in the cockpit&rsquo;s grasscatcher.</div></div>'
    else:
        tiers = "".join('<button data-picktier="%d"%s>Tier %d%s</button>' % (t, ' class="on"' if t == 3 else "", t, " &middot; suggested" if t == 3 else "") for t in (1, 2, 3))
        areas = "".join('<button data-pickarea="%s">%s</button>' % (a, a.title()) for a in AREAS) + '<button data-pickarea="" class="on">none yet</button>'
        row = "".join('<div class="seed" data-seed="%s"><div class="st">%s</div><div class="sw">would suit <b>tier 3</b> &mdash; you choose the tier and the life area</div>'
                      '<button class="mk" data-act="promote" data-seed="%s">Make it an initiative</button>'
                      '<div class="pick" hidden><div class="q">Which tier?</div><div class="prow">%s</div><div class="q">Which life area?</div><div class="prow">%s</div>'
                      '<div class="prow"><button class="go" data-pickgo="%s">Create it in tier 3</button><button class="cancel" data-pickcancel="1">cancel</button></div></div></div>'
                      % (esc(s["id"]), esc(s["text"]), esc(s["id"]), tiers, areas, esc(s["id"])) for s in seeds)
    return ('<section class="seedband" id="seedband" aria-label="Seeds"><button class="sb-h" id="seedToggle" aria-expanded="false"><span class="t">Seeds</span>'
            '<span class="c" id="seedCount"><b>%d</b> idea%s, not yet initiatives</span>'
            '<span class="note">Making one an initiative asks for its tier and its life area on the card &mdash; nothing is created until Create it.</span>'
            '<span class="tog" id="seedTog">Show</span></button><div class="seedrow" id="seedRow">%s</div></section>'
            % (len(seeds), "" if len(seeds) == 1 else "s", row))


def _areas(ctx):
    inits = ctx["initiatives"]
    counts = {a: sum(1 for i in inits if i["area"] == a) for a in AREAS}
    chips = "".join('<button class="ac" data-area="%s" style="--c:%s"><i></i>%s <b>%d</b></button>' % (a, AREA_COLOURS[a], a.title(), counts[a]) for a in AREAS if counts[a])
    t = {k: sum(1 for i in inits if i["tier"] == k) for k in (1, 2, 3)}
    top = max(AREAS, key=lambda a: counts[a]) if inits else None
    note = "%d initiative%s &middot; tier 1 %d &middot; tier 2 %d &middot; tier 3 %d%s Click an area to hold all three tiers to it." % (
        len(inits), "" if len(inits) == 1 else "s", t[1], t[2], t[3],
        (" &mdash; <b style=\"color:%s\">%s</b> carries %d." % (AREA_COLOURS[top], top.title(), counts[top])) if top and counts[top] > 1 else "")
    return '<div class="areas" id="areas">%s<span class="note">%s</span></div>' % (chips or '<span class="note">no areas yet</span>', note)


def brief_bullets(ctx):
    inits = ctx["initiatives"]
    today = ctx["today"]
    out = []
    t1 = [i for i in inits if i["tier"] == 1]
    dated = sorted(((p["date"], p, i) for i in inits for p in i["parts"] if p["date"] and not p["broken"] and p["status"] not in ("done", "parked")), key=lambda x: x[0])
    ahead = next(((d, p, i) for d, p, i in dated if _hr._iso(d) and _hr._iso(d) >= today), None)
    if t1:
        out.append("<b>Tier 1</b> holds %s.%s" % (" &middot; ".join(esc(i["name"]) for i in t1),
                   (" The nearest hard date is <b>%s</b>, on <b>%s</b> in %s (tier %d)." % (esc(_short(ahead[0])), esc(ahead[1]["text"]), esc(ahead[2]["name"]), ahead[2]["tier"])) if ahead else " Nothing in the Campaign carries a date yet."))
    else:
        out.append("No Tier 1 initiative yet &mdash; give one a tier.")
    mon = today - timedelta(days=today.weekday()); sun = mon + timedelta(days=6)
    week = [(d, p, i) for d, p, i in dated if _hr._iso(d) and mon <= _hr._iso(d) <= sun]
    if week:
        out.append("This week, %s: %s." % (esc(_hr.week_in_words(today).replace("this week ", "")), "; ".join("%s (%s, %s)" % (esc(p["text"]), esc(_short(d)), esc(i["name"])) for d, p, i in week[:3])))
    else:
        out.append("This week, %s: <b>nothing in the Campaign is dated inside it</b>.%s" % (
            esc(_hr.week_in_words(today).replace("this week ", "")), (" The first mark is %s." % esc(_short(ahead[0]))) if ahead else ""))
    needs = [(p, i) for i in inits for p in i["needs"]]
    if needs:
        out.append('<span class="amberword">&#9873; %d part%s need%s you</span>, %d with no date. In tier order: %s%s.' % (
            len(needs), "" if len(needs) == 1 else "s", "s" if len(needs) == 1 else "", sum(1 for p, i in needs if not p["date"]),
            " &middot; ".join('<button class="goto" data-goto="%s">%s</button> (tier %s)' % (esc(i["id"]), esc(p["text"]), i["tier"] or "?") for p, i in needs[:3]),
            (" &hellip; and %d more" % (len(needs) - 3)) if len(needs) > 3 else ""))
    else:
        out.append("Nothing in the Campaign waits on your word.")
    counts = {a: sum(1 for i in inits if i["area"] == a) for a in AREAS}
    out.append("Across your life: %s. <span class=\"n\">%d</span> seed%s wait%s above the board." % (
        " &middot; ".join("%s <span class=\"n\">%d</span>" % (a.title(), counts[a]) for a in AREAS if counts[a]) or "no areas yet",
        len(ctx.get("seeds") or []), "" if len(ctx.get("seeds") or []) == 1 else "s", "s" if len(ctx.get("seeds") or []) == 1 else ""))
    return out


def _lead(ctx):
    """The brief's lead when a set exists: the head as the High Seat reads it - a part that needs him in an active
    initiative, else the tiers, else the pick-up while the set runs - with an open to its tile."""
    inits = ctx["initiatives"]
    if not any(i.get("active") for i in inits):
        return None
    working = ctx.get("working") or set()
    head = _ha.head_act(inits, [], today=ctx["today"])
    pk = _ha.pick_up(inits, [], working=working, today=ctx["today"])
    name = (head or {}).get("initiative") or (pk or {}).get("initiative") or ""
    hit = next((i for i in inits if i["name"] == name), None)
    goto = (' <button class="goto" data-goto="%s">open</button>' % esc(hit["id"])) if hit else ""
    return esc(_ha.head_sentence(head, pickup=pk)) + goto


def _panel(ctx):
    st = ctx["steward"]
    rest = brief_bullets(ctx)
    lead = _lead(ctx)
    if lead is None:
        lead, rest = rest[0], rest[1:]
    # the brief shrinks to its lead plus a fold (A1): the composer sits directly under it
    bullets = '<li class="lead">%s</li><li class="fold"><details class="brief-more"><summary>the rest, by tier</summary><ul>%s</ul></details></li>' % (
        lead, "".join('<li>%s</li>' % b for b in rest))
    turns = ctx.get("turns") or []
    ex = "".join('<li class="exrow %s"><div class="exw %s">%s<span class="t">%s</span></div><div class="ext">%s</div></li>' % (
        "you" if t["you"] else "st", "you" if t["you"] else "st", "You" if t["you"] else esc(st["label"]), esc(t["at"]), esc(t["text"][:600])) for t in turns[-6:])
    return (
        '<aside class="panel" aria-label="The steward"><section class="brief" id="brief"><div class="kicker">The brief <span class="k-when">%s</span></div><ul class="blist" id="briefList">%s</ul></section>'
        '<section class="composer"><label class="sr" for="say">Tell the steward what to do</label>'
        '<textarea id="say" rows="2" placeholder="Tell %s what to do &mdash; it runs the Campaign: make &hellip; active, bench &hellip;, &hellip; by Oct 10"></textarea>'
        '<div class="comp-row"><span class="hint">Ctrl+Enter sends &middot; the steward answers here and acts on the record; the board shows what changed on the next look</span><button class="send" id="sendBtn">Send</button></div>'
        '<div class="receipt" id="receipt" hidden><span class="r-mark">&#10003;</span><span id="receiptText"></span> <button class="mini" id="undoBtn" hidden>undo</button></div></section>'
        '<div class="exwrap"><div class="exhead"><h3>%s &mdash; the conversation</h3><span class="note" id="exNote">%s</span></div>'
        '<div class="scroll" style="flex:1"><ul class="ex" id="exList">%s<li class="exfade">%s</li></ul></div></div></aside>'
    ) % (esc(ctx["brief_when"]), bullets, esc(st["label"]), esc(st["label"]), ("%d shown" % min(6, len(turns))) if turns else "no transcript kept",
         ex, "Only the last few exchanges are kept here. What the steward actually did is on the board." if turns else "Nothing said here yet. The cockpit's conversation is the same one.")


# ── the page ───────────────────────────────────────────────────────────────────────────────────

def render_campaign_html(ctx, open_id=None) -> str:
    st = ctx["steward"]
    inits = ctx["initiatives"]
    ctx["n_total"] = len(inits)
    tiers = {k: sum(1 for i in inits if i["tier"] == k) for k in (1, 2, 3)}
    n_parts = sum(len(i["parts"]) for i in inits)
    n_dated = sum(1 for i in inits for p in i["parts"] if p["date"] and not p["broken"] and p["status"] not in ("done", "parked"))
    n_needs = sum(len(i["needs"]) for i in inits)
    n_active = sum(1 for i in inits if i.get("active"))
    board = (
        '<section class="board" aria-label="The Campaign" data-place="%s"><div class="colk"><h3 id="viewTitle">The goals</h3>'
        '<span class="c" id="boardCount">%d in priority order &middot; Active %d &middot; T1 %d / T2 %d / T3 %d &middot; %d parts &middot; %d dated%s</span>'
        '<span class="rule"></span><button class="viewbtn" id="viewBtn">&#128197; Calendar view</button><button class="mini" id="closeAll">Close the goal</button></div>'
        '%s%s%s%s%s'
        '<p class="boardfoot" id="boardFoot">Drag a goal up or down in its band, into another tier, or into <b>Active</b>; click its name for its place &mdash; every change is one line with undo.</p></section>'
    ) % (esc(open_id or ""), len(inits), n_active, tiers[1], tiers[2], tiers[3], n_parts, n_dated, (' &middot; <span style="color:var(--amber-t);font-weight:700">%s</span>' % _needs(n_needs)) if n_needs else "",
         _seedband(ctx), _areas(ctx), _bands(ctx), _places(ctx), _calendar(ctx))
    hdr = (
        '<div class="hdr"><a class="back" href="/high-seat">&larr; %s</a><h2>The Campaign</h2>'
        '<button class="tool doctor" data-tool="doctor">&#10010; Anchor Doctor</button><button class="tool" data-tool="zombie">%sZombie Hunter</button><button class="tool" data-tool="foundry">%sSkill Foundry</button>'
        '<a class="tool" href="/project/%s?doc=1" title="the ordinary cockpit of this record">the cockpit</a><div class="date">%s</div></div>'
    ) % (esc(st["high_seat_name"]),
         _brand_img(ctx["build"], "zombie-hunter-radar.jpg"), _brand_img(ctx["build"], "skill-foundry-icon.jpg"), esc(ctx["pid"]), esc(ctx["today_str"]))
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>The Campaign</title><link rel="icon" href="/vendor/brand/%s?v=%s">'
        '<link rel="stylesheet" href="/static/campaign-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s"};</script></head>'
        '<body><div class="page">%s%s<div class="prefs">%s</div><div class="canvas">%s%s</div>'
        '<div class="foot">%s<span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span>'
        '<span>&mdash; every initiative, part, date and count on this page is read from the Campaign record; a project part is read from its own record.</span></div></div>'
        '<script src="/static/campaign-page.js?v=%s"></script></body></html>'
    ) % (esc(st.get("seal") or "gwl-m-icon.svg"), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["pid"]), _masthead(ctx), hdr, ctx.get("prefs_html") or "", board, _panel(ctx),
         _brand_img(ctx["build"], "gwl-m-icon.svg"), esc(ctx["build"]))
