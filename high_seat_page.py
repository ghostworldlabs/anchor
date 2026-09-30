"""high_seat_page — the High Seat: Anchor's home as the steward's portfolio surface.

W1b of the High Seat plan (2026-09-26). The approved design is the mockup
``Skill Foundry/planning/high-seat-2026-09-24/ideation/mockups/r5/10-high-seat.html`` (John's
picks of 2026-09-25/26); its stylesheet is ``static/high-seat-page.css`` ported as it is. This
module renders that page from FACTS — the registry, each project's steward record (home_rows),
the ranked rows and the brief (home_attention), the session registry, the Campaign record when
it exists — with no model call and no bridge spawn on the request. Pure: it takes a context
dict the application builds (``anchor_gui._high_seat_context``) and returns HTML. Every number
on the page is read from a record or is an honest "not connected / not measured yet".
"""
from __future__ import annotations

import html
import re
from datetime import date, timedelta

import home_rows as _hr

_OPEN = ("proposed", "planned", "active", "waiting")
_TIER_WORDS = {1: "do first", 2: "next in line", 3: "when there is room"}


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _short(d):
    return _hr.short_date(d) if d else ""


# ── the Campaign record → initiatives with their parts ─────────────────────────────────────────

def campaign_initiatives(steps, resolved=None):
    """The Campaign's heading steps (each defines its own root group) with their parts.

    An initiative = a step that defines a root navigation group whose id is its own id (PLAN §3);
    its parts = the steps whose navigation path starts with that id. A part's kind comes from its
    ``ref`` prefix (project · step · deliverable · calendar) or is a native task; its text, state,
    date and link come from the resolver when it points at another record."""
    resolved = resolved or {}
    steps = [s for s in (steps or ()) if isinstance(s, dict)]
    heads = []
    for s in steps:
        nav = s.get("navigation") if isinstance(s.get("navigation"), dict) else {}
        groups = nav.get("groups") or []
        own = next((g for g in groups if isinstance(g, dict) and g.get("id") == s.get("id") and g.get("parent_id") is None), None)
        if own is not None:
            heads.append((s, own))
    out = []
    for s, own in heads:
        sid = s.get("id")
        parts = []
        for p in steps:
            if p is s:
                continue
            nav = p.get("navigation") if isinstance(p.get("navigation"), dict) else {}
            path = nav.get("path") or []
            if path and path[0] == sid:
                r = resolved.get(str(p.get("id"))) or {}
                ref = str(p.get("ref") or "")
                kind = ref.split(":", 1)[0] if ref else "task"
                state = r.get("state") or ("" if r.get("broken") else str(p.get("status") or ""))
                parts.append({
                    "id": p.get("id"), "kind": kind, "text": r.get("what") or p.get("name") or "",
                    "target": r.get("name") or "", "state": state, "date": r.get("date") or p.get("due") or "",
                    "pid": str(r.get("pid") or ""), "lead": str(r.get("lead") or ""), "dir": str(r.get("dir") or ""),
                    "href": r.get("href") or "", "status": str(p.get("status") or ""),
                    "target_status": str(r.get("target_status") or ""),
                    "broken": bool(r.get("broken")) if ref else False, "gap": r.get("gap") or "",
                    "waiting_on": str(p.get("waiting_on") or "") if not ref else "",
                    "needs_you": "waiting on you" in str(state).lower() or (
                        not ref and str(p.get("status") or "") == "waiting"
                        and bool(re.search(r"\b(john|you|me)\b", str(p.get("waiting_on") or "").lower()))),
                    # the seat (2026-09-30, his three levels): a component he works interactively — a cockpit, an
                    # effort, a desk item — sits in its goal (""), on deck, or active, in his order
                    "seat": str(p.get("seat")) if p.get("seat") in ("active", "deck") else "",
                    "seat_order": int(p["seat_order"]) if isinstance(p.get("seat_order"), int) else None,
                    "goal": sid, "goal_name": s.get("name") or sid,
                })
        # W1 (2026-09-28): a referenced part is closed when its RESOLVED target is — done, cancelled, dropped or
        # parked — not only when the wrapper's own status says so (Grok's live replay, 2026-09-27: a done target
        # stayed the open "next" part while its wrapper was planned). An unavailable target is broken: named, never
        # next. Every reader of a part (the light, the rows, the board's chips and ticks) reads these two flags,
        # never the wrapper's status alone (Grok W1).
        for p in parts:
            p["done"] = p["status"] == "done" or p["target_status"] == "done"
            p["closed"] = p["status"] in ("done", "parked") or p["target_status"] in ("done", "cancelled", "dropped", "parked")
        open_parts = [p for p in parts if not p["closed"] and not p["broken"]]
        dates = sorted(p["date"] for p in open_parts if p["date"])
        out.append({
            "id": sid, "name": s.get("name") or sid, "tier": int(s["tier"]) if s.get("tier") in (1, 2, 3) else None,
            "order": int((own or {}).get("order") or 0), "area": str(s.get("area") or ""),
            "done_when": s.get("done_when") or "", "status": s.get("status") or "",
            "parts": parts, "next": open_parts[0] if open_parts else None,
            "needs": [p for p in parts if p["needs_you"]], "next_deadline": dates[0] if dates else "",
            "done_count": sum(1 for p in parts if p["done"]),
            # the pace he drives the goal toward (2026-09-29); the parts' progress. The goal itself has no seat: its
            # components do (his three levels, 2026-09-30)
            "pace": str(s.get("pace") or ""),
            "open_count": len(open_parts), "part_count": sum(1 for p in parts if not p["broken"]),
        })
    out.sort(key=lambda i: (i["tier"] or 9, i["order"], i["name"]))   # an untiered initiative sorts last, its tier shown as missing
    for n, i in enumerate(out, 1):
        i["number"] = n
    return out


INITIATIVE_KINDS = ("project", "effort", "task")   # a component he works interactively: a cockpit, an effort, a desk item


def is_initiative(part):
    return part.get("kind") in INITIATIVE_KINDS and not part.get("broken")


def part_name(part):
    """An initiative's own name: the project or effort it points at, else the desk item's words."""
    return str(part.get("target") or part.get("text") or "")


def seated(initiatives, seat):
    """The components sitting in a seat — (goal, part) pairs in his order (seat_order; then the goal's tier and
    order; then the name). The one sort for Active and On deck (the head, the pick-up, the shelves)."""
    out = []
    for i in initiatives or ():
        for p in i.get("parts") or ():
            if p.get("seat") == seat and not p.get("closed"):
                out.append((i, p))
    return sorted(out, key=lambda t: (t[1].get("seat_order") if isinstance(t[1].get("seat_order"), int) else 999, t[0].get("tier") or 9, int(t[0].get("order") or 0), part_name(t[1]).lower()))


# ── an initiative's light, its one line, its status (the home's Campaign tile and the Campaign page share these) ──

LIGHTS = {"needs": ("&#9873;", "needs you"), "working": ("&#9679;", "working"), "waiting": ("&#9679;", "waiting"), "idle": ("&#9675;", "idle")}


def initiative_light(i, working=None):
    """One word for an initiative, read from its parts (John, 2026-09-27: "whether action is needed — working, waiting,
    idle"): ``needs`` when a part waits on him; ``working`` when a referenced project has a running session or a busy
    steward (``ctx["working"]``); ``waiting`` when an open part waits on something else; else ``idle``."""
    working = working or set()
    if i.get("needs"):
        return "needs"
    open_parts = [p for p in i.get("parts") or () if not p.get("closed", p.get("status") in ("done", "parked")) and not p.get("broken")]
    if any(p.get("pid") and p["pid"] in working for p in open_parts):
        return "working"
    if any(str(p.get("state") or "").startswith("waiting") or p.get("status") == "waiting" for p in open_parts):
        return "waiting"
    return "idle"


def initiative_line(i):
    """The one sentence a compact initiative tile carries (Grok R8: the action, not the part's name): when a part waits
    on him, the wait itself — a project part's "waiting on you: …" without its prefix, a native part's trigger, else
    the part's text; else the next open part; else what done looks like. Returns (html, kind)."""
    if i.get("needs"):
        p = i["needs"][0]
        state = str(p.get("state") or "")
        low = state.lower()
        if "waiting on you:" in low:
            words = state[low.index("waiting on you:") + len("waiting on you:"):].strip()
        elif p.get("waiting_on") and str(p["waiting_on"]).strip().lower() not in ("john", "you", "me"):
            words = "%s &mdash; %s" % (esc(p.get("text") or ""), esc(p["waiting_on"]))
            return "&#9873; " + words, "wait"
        else:
            words = ""
        text = esc(words) if words else esc(p.get("text") or p.get("target") or "")
        return "&#9873; " + text, "wait"
    nxt = i.get("next")
    if nxt:
        return "Next: " + esc(nxt.get("text") or "") + ((" &middot; " + esc(_short(nxt["date"]))) if nxt.get("date") else ""), "next"
    if i.get("done_when"):
        return "Done looks like: " + esc(i["done_when"]), "done"
    return "nothing open", "none"


def initiative_status_html(i):
    """The Status of an opened initiative (John: "the status is missing"): each project part's own steward status —
    its last lead line, read from its record. Only that (Grok R8): the wait and the counts are already on the tile.
    A part without a recorded status says so."""
    rows = []
    for p in i.get("parts") or ():
        if p.get("kind") != "project":
            continue
        lead = " ".join(str(p.get("lead") or "").split())[:220]
        rows.append('<div class="isrow"><a href="%s" target="_blank" rel="noopener">%s</a> &mdash; %s</div>' % (
            esc(p.get("href") or "#"), esc(p.get("target") or p.get("text") or "project"), esc(lead) or "no status recorded yet"))
    return '<div class="istatus"><span class="k">Status</span>%s</div>' % (
        "".join(rows) or '<div class="isrow dim">No project part yet &mdash; the parts below carry their own states.</div>')


# ── the ruler ──────────────────────────────────────────────────────────────────────────────────

def ruler_weeks(today):
    mon = today - timedelta(days=today.weekday())
    weeks = []
    for k in range(5):
        a = mon + timedelta(days=7 * k)
        b = a + timedelta(days=6)
        label = "%s–%d" % (_hr.short_date(a.isoformat()), b.day) if a.month == b.month else "%s–%s" % (_hr.short_date(a.isoformat()), _hr.short_date(b.isoformat()))
        weeks.append({"start": a, "end": b, "label": label, "name": "this week" if k == 0 else "week %d" % (k + 1)})
    return weeks


def ruler_markers(facts, today):
    """Every open dated step across the records, bucketed into the five weeks and beyond; a date
    already past sits in this week and says overdue."""
    weeks = ruler_weeks(today)
    buckets = {k: [] for k in range(5)}
    beyond, overdue = [], []
    for f in facts or ():
        if not isinstance(f, dict):
            continue
        for st in f.get("dated") or ():
            d = _hr._iso(st.get("due"))
            if d is None:
                continue
            m = {"date": st["due"], "name": st.get("name", ""), "project_id": f.get("id", ""),
                 "project_name": f.get("name", ""), "needs": bool(f.get("needs_you")),
                 "overdue": d < today, "label": _hr.due_label(st["due"], today)}
            if d < weeks[0]["start"]:
                overdue.append(m)          # before this Monday: overdue, not this week's delivery
                continue
            placed = False
            for k, w in enumerate(weeks):
                if w["start"] <= d <= w["end"]:
                    buckets[k].append(m); placed = True; break
            if not placed:
                beyond.append(m)
    for k in buckets:
        buckets[k].sort(key=lambda m: (m["date"], m["name"]))
    beyond.sort(key=lambda m: (m["date"], m["name"]))
    overdue.sort(key=lambda m: (m["date"], m["name"]))
    return weeks, buckets, beyond, overdue


# ── pieces ─────────────────────────────────────────────────────────────────────────────────────

def _brand_img(build, name, cls=""):
    return '<img%s src="/vendor/brand/%s?v=%s" alt="" onerror="this.style.display=\'none\'">' % (
        (' class="%s"' % cls) if cls else "", esc(name), esc(build))


def capacity_row_html(c):
    """One capacity line (W4): the name, the two bars when a run reported the account's windows (amber over 80%),
    the state in words, the note that says what the row cannot see."""
    bars = "".join(
        '<span class="wbar"><span class="wl">%s</span><span class="bar%s"><b style="width:%d%%"></b></span><span class="p%s">%s</span></span>' % (
            esc(b.get("label")), " warn" if b.get("warn") else "",
            int(b.get("pct") or 0), " warn" if b.get("warn") else "", ("%d%%" % int(b["pct"])) if b.get("pct") is not None else "?")
        for b in (c.get("bars") or []) if isinstance(b, dict))
    sub = (('<span class="amberword">%s</span> &middot; ' % esc(c.get("amber"))) if c.get("amber") else "") + esc(c.get("note"))
    state = esc(c.get("state"))
    short = len(str(c.get("state") or "")) <= 24 and not bars     # a short state sits beside the name, as the mockup's rows do
    return ('<div class="cr"><div class="cr-top"><span class="cr-n">%s</span>%s%s</div>%s<div class="cr-sub">%s</div></div>'
            % (esc(c.get("name")), bars, ('<span class="cr-none">%s</span>' % state) if short else "",
               "" if short else '<div class="cr-state">%s</div>' % state, sub))


def _rail(ctx):
    st = ctx["steward"]
    counts = ctx.get("counts") or {}
    n_camp = len(ctx.get("initiatives") or [])
    live_inits = [i for i in ctx.get("initiatives") or [] if i.get("status") not in ("done", "parked")]
    n_active, n_deck = len(seated(live_inits, "active")), len(seated(live_inits, "deck"))     # W2c: the shelves
    n_bench = int(counts.get("running") or 0)
    cap_rows = "".join(capacity_row_html(c) for c in ctx.get("capacity") or ())
    return (
        '<nav class="rail">'
        '<div class="lockup">%s<div class="wordmark">Ghost World <span class="gwl-accent">Labs</span></div></div>'
        '<div class="gwl-badge">Powered by NextGen Nuclear %s</div>'
        '<div class="railseat">%s<h1><span class="a">&#9875;</span> The %s</h1></div>'
        '<div class="sub">Anchor &middot; the whole portfolio, ranked</div>'
        '<div class="navk">Destinations</div>'
        '<ul class="nav" id="railNav">'
        '<li><button data-rail="seat"><span class="n">%s</span><span class="c">brief</span></button></li>'
        '<li><button data-rail="campaign"><span class="n">Campaign</span><span class="c">%s</span></button></li>'
        '<li><button data-rail="active"><span class="n">Active</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="week"><span class="n">This week</span><span class="c">%s</span></button></li>'
        '<li><button data-rail="desk"><span class="n">Desk</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="deck"><span class="n">On deck</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="calendar"><span class="n">Calendar</span><span class="c">not connected</span></button></li>'
        '<li><button data-rail="email"><span class="n">Email</span><span class="c">not connected</span></button></li>'
        '<li><button data-rail="bench"><span class="n">Workbench</span><span class="c">%d</span></button></li>'
        '</ul>'
        '<div class="cap"><h3>Capacity &middot; window and week</h3><div id="capList">%s</div></div>'
        '</nav>'
    ) % (_brand_img(ctx["build"], "gwl-m-icon.svg"), _brand_img(ctx["build"], "gwl-m-icon.svg"),
         _brand_img(ctx["build"], st["high_seat"], ""), esc(st["high_seat_name"]),
         esc(st["high_seat_name"]), (str(n_camp) if ctx.get("campaign") else "not yet"), n_active,
         esc(ctx["week_short"]), int(ctx.get("tasks_open") or 0), n_deck, n_bench, cap_rows)


def _masthead(ctx):
    """The masthead every High Seat page shares: Anchor, the Ghost World Labs lockup, then — at the very top, beside the
    AI Cockpit pill (John, 2026-09-27) — the steward: its High Seat image, the seat's name, who serves."""
    b = ctx["build"]
    st = ctx.get("steward") or {}
    stew = ('<div class="mh-stew" title="your steward">%s<div><b>The %s</b><span>%s &middot; your steward</span></div></div>' % (
        _brand_img(b, st.get("high_seat") or "", "mh-seat"), esc(st.get("high_seat_name") or "High Seat"), esc(st.get("label") or "the steward"))) if st else ""
    return (
        '<div class="masthead"><div class="mh-title"><span class="a">&#9875;</span>Anchor</div><div class="mh-div"></div>'
        '<div class="mh-lock">%s<div><div class="mh-w1">Ghost World <span class="gwl-accent">Labs</span></div>'
        '<div class="mh-w2">R&amp;D Mission Control</div></div></div><div class="mh-sp"></div>%s'
        '<div class="mh-pill">AI Cockpit %s</div></div>'
    ) % (_brand_img(b, "gwl-m-icon.svg", "mh-mark"), stew, _brand_img(b, "gwl-m-icon.svg"))


def _hdr(ctx):
    st = ctx["steward"]
    b = ctx["build"]
    return (
        '<div class="hdr"><h2>%s</h2><span class="who">%s</span>'
        '<button class="tool doctor" data-tool="doctor">&#10010; Anchor Doctor</button>'
        '<button class="tool" data-tool="zombie">%sZombie Hunter</button>'
        '<button class="tool" data-tool="foundry">%sSkill Foundry</button>'
        '<a class="tool" href="/dashboard" title="the dashboard as it was">the old dashboard</a>'
        '<div class="date">%s &middot; %s</div></div>'
    ) % (esc(st["high_seat_name"]), esc(st["label"]), _brand_img(b, "zombie-hunter-radar.jpg"),
         _brand_img(b, "skill-foundry-icon.jpg"), esc(ctx["today_str"]), esc(ctx["week"]))


KIND_WORDS = {"project": "cockpit", "effort": "cockpit within", "task": "desk item", "step": "a step of a project", "deliverable": "deliverable", "calendar": "date"}
SEAT_WORDS = {"active": "active", "deck": "on deck"}
SEAT_NAMES = {"active": "Active", "deck": "On deck"}


def _goal_rows(ctx, live, camp_pid):
    """The goals expanded (W2c, 2026-09-30, his three levels): each goal a row that opens to its components. An
    initiative in its goal (a cockpit, a cockpit within a project, a desk item) drags out to a shelf or takes a button;
    a seated one is marked and comes back; an element (a step, a deliverable, a date) rides inside its goal."""
    working = ctx.get("working") or set()
    rows = []
    for i in live:
        comps = [p for p in i["parts"] if not p.get("closed")]
        out = [p for p in comps if p.get("seat")]
        home = [p for p in comps if not p.get("seat")]      # what is still inside the goal: every open component with no seat (Grok's read of W2c)
        light = initiative_light(i, working)
        glyph, word = LIGHTS[light]

        def irow(p):
            kind = KIND_WORDS.get(p["kind"], p["kind"])
            name = esc(part_name(p))
            if p.get("broken"):
                return '<div class="irow broken"><span class="kind">%s</span><span class="nm">%s</span><span class="el">broken reference: %s</span></div>' % (kind, esc(p.get("text") or name), esc(p.get("gap") or ""))
            if not is_initiative(p):      # an element is named for what it is, its project as the suffix
                where = (' <span class="dim">&middot; %s</span>' % esc(p["target"])) if p.get("target") else ""
                return '<div class="irow el"><span class="kind">%s</span><span class="nm">%s%s</span><span class="el">rides inside &mdash; not pulled out on its own</span></div>' % (kind, esc(p.get("text") or name), where)
            if p.get("seat"):
                return ('<div class="irow seated" data-step="%s"><span class="kind">%s</span><span class="nm">%s</span><span class="seat %s">%s</span>'
                        '<button class="mini" data-home="%s" title="back into this goal">back</button></div>') % (
                    esc(p["id"]), kind, name, p["seat"], SEAT_WORDS[p["seat"]], esc(p["id"]))
            need = ' <span class="need">&#9873; needs you</span>' if p.get("needs_you") else ""
            return ('<div class="irow" draggable="true" data-step="%s" data-name="%s"><span class="kind">%s</span><span class="nm">%s%s</span>'
                    '<span class="acts"><button class="mini" data-seat="deck" data-step="%s">&rarr; on deck</button><button class="mini" data-seat="active" data-step="%s">&rarr; active</button></span></div>') % (
                esc(p["id"]), name, kind, name, need, esc(p["id"]), esc(p["id"]))
        tier_word = ("tier %d" % i["tier"]) if i["tier"] in (1, 2) else "seed goal"
        n_act, n_deck = sum(1 for p in out if p["seat"] == "active"), sum(1 for p in out if p["seat"] == "deck")
        summary = "%d in the goal" % len(home) + ((" &middot; out: %s" % ", ".join(x for x in (("%d active" % n_act) if n_act else "", ("%d on deck" % n_deck) if n_deck else "") if x)) if out else "")
        rows.append(
            '<div class="grow%s" data-g="%s"><div class="gh"><b class="gn">%s</b><span class="t">%s</span><span class="ilight %s">%s %s</span><span class="c">%s</span>'
            '<a class="gopen" href="/project/%s?open=%s" target="_blank" rel="noopener" title="its place on the Campaign page">its place &#8599;</a></div>'
            '<div class="inits">%s</div></div>' % (
                " needs" if i["needs"] else "", esc(i["id"]), esc(i["name"]), tier_word, light, glyph, word, summary,
                esc(camp_pid), esc(i["id"]),
                "".join(irow(p) for p in comps) or '<div class="irow el"><span class="el">no component yet &mdash; add one in its place on the Campaign page</span></div>'))
    return "".join(rows)


def _campaign_tile(ctx):
    """The goals on the home (W2c, 2026-09-30, his lock of the three levels): ONE thin line — Tier 1 named, Tier 2 and
    the seed goals counted, how many initiatives are out — that expands to the goals and their components (each goal a
    row that opens). The tile is where a seated initiative is dropped to go home, and a goal's row is where a registry
    project is dropped to become its component. Closed by default; the head toggles it."""
    camp = ctx.get("campaign")
    inits = ctx.get("initiatives") or []
    if not camp:
        return ('<section class="camp" id="camp"><div class="camp-h" id="campHead"><span class="k">Goals</span>'
                '<span class="d">&middot; not stood up yet &mdash; the record arrives with the import, after your seed check</span>'
                '<span class="sp"></span></div></section>')
    live = [i for i in inits if i["status"] not in ("done", "parked")]
    t1 = [i for i in live if i["tier"] == 1]
    t2 = [i for i in live if i["tier"] == 2]
    seedy = [i for i in live if i["tier"] not in (1, 2)]
    act = seated(live, "active")
    deck = seated(live, "deck")
    line = ('&middot; <b>Tier 1:</b> %s &middot; <b>Tier 2:</b> %d &middot; <b>seed goals:</b> %d &middot; <b>out:</b> %d active, %d on deck' % (
        esc(" · ".join(i["name"] for i in t1)) if t1 else "none yet", len(t2), len(seedy) + int(ctx.get("seeds") or 0), len(act), len(deck)))      # one seed-goal count (Grok W2c): the goals not in tier 1 or 2, and the seeds
    body = '<div class="grows">%s</div>' % (_goal_rows(ctx, live, camp["pid"]) or '<div class="camp-note">No goal yet &mdash; the Campaign page makes one.</div>')
    return (
        '<section class="camp" id="camp" data-drop="home"><div class="camp-h" id="campHead"><span class="k">Goals</span>'
        '<span class="d" id="campLine">%s</span><span class="sp"></span><span class="tog" id="campTog">Expand</span>'
        '<a class="camp-open" href="/project/%s" target="_blank" rel="noopener">Open the Campaign</a></div>'
        '<div class="camp-body" id="campBody">%s</div></section>'
    ) % (line, esc(camp["pid"]), body)


def _desk_card(ctx, g, p):
    """A desk item's card (W2c): the item, its goal, its state and date; the × sends it home; it is talked through at the
    Desk — the Campaign's own cockpit in its Desk view (Grok's read of W2c: the door the Desk line already opens)."""
    if p.get("needs_you"):
        line = '<div class="t-line wait"><span class="mk">&#9873; Needs you:</span>%s</div>' % esc(p.get("waiting_on") or p.get("state") or "")
    else:
        line = '<div class="t-line"><span class="k">State</span>%s</div>' % esc(p.get("state") or p.get("status") or "planned")
    date = (' &middot; %s' % esc(_hr.due_label(p["date"], ctx["today"]))) if p.get("date") else ""
    return (
        '<article class="tile desk%s" id="card-%s" data-step="%s" data-name="%s" draggable="true"><div class="t-top"><h3 class="t-name"><span class="t-nm">%s</span><span class="t-eff">at the desk%s</span></h3>'
        '<button class="t-x" data-home="%s" title="back to its goal">&times;</button></div><div class="t-goal">in <b>%s</b></div>%s'
        '<div class="t-acts"><a class="t-talk" href="/project/%s?view=desk" target="_blank" rel="noopener">talk to the desk &#8599;</a></div></article>'
    ) % (" need" if p.get("needs_you") else "", esc(p["id"]), esc(p["id"]), esc(part_name(p)), esc(part_name(p)), date, esc(p["id"]), esc(g["name"]), line,
         esc((ctx.get("campaign") or {}).get("pid") or ""))


def _zone(sid, seat, title, n, note, cards, empty):
    return (
        '<section class="shelf zone" id="%s" data-seat="%s"><div class="shelf-h"><h3>%s</h3><span class="c">%d</span><span class="rule"></span><span class="note">%s</span></div>'
        '<div class="grid">%s</div></section>' % (sid, seat, title, n, note, cards or ('<div class="empty">%s</div>' % empty)))


def _seat_shelves(ctx):
    """ACTIVE and ON DECK (W2c): two shelves of initiative cards in his order — the project card as today (the light,
    what needs him, Status · Next steps · Deliverables · Plan · Resume · the cockpit), a cockpit within a project on
    its own effort, a desk item's card that talks to the desk — each naming its goal, each with a × that sends it home.
    No cap: a wide Active is named, never refused."""
    inits = [i for i in ctx.get("initiatives") or [] if i["status"] not in ("done", "parked")]
    entries = {e.get("id"): e for e in ctx.get("entries") or []}
    facts = ctx["facts"]

    def cards(seat):
        out = []
        for g, p in seated(inits, seat):
            if p["kind"] in ("project", "effort") and entries.get(p["pid"]):
                e = entries[p["pid"]]
                f = facts.get(p["pid"]) or {}
                if p["kind"] == "effort":      # the card reads THAT effort: its directory, its own wait and next (Grok's read of W2c)
                    st_ = str(p.get("state") or "")
                    wait = re.sub(r"^waiting on you[:\s]*", "", st_, flags=re.I).strip(" .") if st_.lower().startswith("waiting on you") else ""
                    f = dict(f, effort=p.get("dir") or f.get("effort") or "", needs_you=wait or ("" if st_ else f.get("needs_you") or ""), needs_you_effort="", other_waits=[],
                             wait_age_days=None, next=p.get("lead") or p.get("text") or f.get("next") or "", repair_proposals=[], efforts_gap="")
                out.append(_card(e, f, "", goal=g, step=p))
            else:
                out.append(_desk_card(ctx, g, p))
        return "".join(out)
    a, d = cards("active"), cards("deck")
    n_a, n_d = len(seated(inits, "active")), len(seated(inits, "deck"))
    return (
        _zone("shActive", "active", "Active", n_a, "what you are working on now, in your order &mdash; drag an initiative here from a goal above or from On deck", a,
              "nothing active &mdash; pull an initiative out of a goal above, or drag one up from On deck")
        + _zone("shDeck", "deck", "On deck", n_d, "out of its goal, not active &mdash; needs attention; the pick-up reads from here", d, "nothing on deck"))


def _projects_tile(ctx):
    """The Projects tile: the registry as it stands, in the OLD dashboard's own list (John, 2026-09-27: "the same look
    and feel, and all of the folders closed") — `ctx["projects_html"]` is that list, rendered by the old dashboard's
    renderer in `anchor_gui`; the head counts the projects and the folders."""
    groups = ctx.get("groups") or {}
    n = sum(len(v) for v in groups.values())
    quiet_n = int(ctx.get("quiet_n") or 0)
    # R11 (2026-09-28, John: "I do not want to go to the old Anchor Dashboard … just the button that links to the
    # folder creation GUI … with an option to place it in a folder"): ONE control on the tile's own line opens the
    # old dashboard's dialog ALONE in a small window; the folders here feed the composer's confirm card
    named = [g for g in groups.keys() if g and g != "Ungrouped"]
    group_opts = "".join('<option value="%s">%s</option>' % (esc(g), esc(g)) for g in named) + '<option value="" selected>Ungrouped</option>'
    return (
        '<section class="ptile" id="ptile"><div class="ptile-line"><button class="ptile-h" id="ptileToggle"><span class="k">Projects</span>'
        '<span class="n" id="ptileCount">&middot; %d project%s in %d folder%s%s</span><span class="sp"></span>'
        '<span class="tog" id="ptileTog">Show all</span></button>'
        '<button type="button" class="tog np" id="apNew" title="the folder-creation dialog, in a small window">&#65291; New project</button></div>%s'
        '<div class="ptile-body"><div class="addbox"><h4>Add a project</h4>'
        '<div class="addhint" id="apHint">Say it to the steward above (&ldquo;start a new project called &lt;name&gt; at &lt;folder&gt;&rdquo;) and confirm the card, '
        'or press New project: the dialog opens in a small window and puts it in a folder of your choosing.</div>'
        '<select id="apGroups" hidden>%s</select></div>'
        '<div id="folders">%s</div></div></section>'
    ) % (n, "" if n == 1 else "s", len(groups), "" if len(groups) == 1 else "s",
         (" &middot; <b>%d</b> with no steward record yet" % quiet_n) if quiet_n else "",
         _orphans_line(ctx), group_opts, ctx.get("projects_html") or '<p class="ptile-note">No project list was handed to the page.</p>')


def _orphans_line(ctx):
    """W2c (fit 10): a registry project in no goal is visible here only; dragging it onto a goal above makes it a
    component of that goal, and so an initiative he can seat."""
    orphans = ctx.get("orphans") or []
    if not ctx.get("campaign") or not orphans:
        return ""
    chips = "".join('<span class="orphan" draggable="true" data-proj="%s" data-name="%s" title="a registry project in no goal &mdash; drag it onto a goal above">%s</span>' % (
        esc(e.get("id")), esc(e.get("name")), esc(e.get("name"))) for e in orphans)
    return ('<div class="orphans"><span class="ok">In no goal &middot; %d</span>%s<span class="oh">drag one onto a goal above to make it a component of that goal</span></div>'
            % (len(orphans), chips))


_ACTS = (("status", "Status"), ("next", "Next steps"), ("deliverables", "Deliverables"), ("plan", "Plan"))


def _resume_act(pid, rel, r):
    """W5 (2026-09-28): Resume — where he left this record (W0's leave receipt), opened in the cockpit AT that step
    (`?step=` opens the plan's fold that holds it, scrolls to it and marks it once); the act's title says the step
    and when, and "nothing moved since" when the roadmap has not moved (the count itself stays on the fact — a
    number with no decision behind it is not for the card, Grok W5). No receipt, no act."""
    if not isinstance(r, dict) or not r.get("at"):
        return ""
    since = r.get("events_since")
    moved = " &middot; nothing moved since" if since == 0 else ""     # the count stays on the fact; the title says only the zero (Grok W5)
    href = "/project/%s?dir=%s%s" % (pid, esc(rel), ("&amp;step=%s" % esc(r.get("step_id"))) if r.get("step_id") else "")
    return ('<a class="t-resume" href="%s" target="_blank" rel="noopener" title="you left at %s (%s)%s">&#8617; Resume <span class="t-age">%s</span></a>'
            % (href, esc(r.get("step") or "where you were"), esc(r.get("ago") or r.get("at")), moved, esc(r.get("ago") or "")))


def _card(e, f, cls, goal=None, step=None):
    """A project's one card, compact (John, 2026-09-27: "the tiles still seem larger than needed"): the name with the
    effort it reads as a small suffix, ONE line — the Needs-you sentence when there is one, else the next step —
    clamped to two lines, and the acts on one line, Status first (his word: "there should also be a status option");
    the cockpit link sits by the name. The description and the next step behind a wait show only once the card
    opens (the effort is named by the suffix and again by the Status part — no third line, Grok R7). The name
    ellipsizes; the suffix stays whole (Grok R7: the effort is the datum the suffix exists for). The parts are read
    from the cockpit's own readers on the effort the card names (home_rows.current_effort → ``data-dir``). A project
    with no record is a quiet card: the name, its blurb, the cockpit."""
    pid = esc(e.get("id"))
    rel = esc(f.get("effort") or "")
    name = esc(e.get("name"))
    # W2c (2026-09-30): on a shelf the card is a seated initiative — it carries its step, drags, has its × and names
    # its goal; a cockpit within a project is its own card on its own effort
    cid = pid if not (step and step.get("kind") == "effort") else "%s-%s" % (pid, esc(step["id"]))
    attr = (' data-step="%s" data-name="%s" draggable="true"' % (esc(step["id"]), name)) if step else ""
    xbtn = ('<button class="t-x" data-home="%s" title="back to its goal">&times;</button>' % esc(step["id"])) if step else ""
    goal_line = ('<div class="t-goal">in <b>%s</b> &middot; %s</div>' % (esc(goal["name"]), "a cockpit within the project" if step.get("kind") == "effort" else "the project&rsquo;s cockpit")) if (goal and step) else ""
    if not f.get("has_record"):
        return (
            '<article class="tile quiet%s" id="card-%s" data-tile="%s"%s><div class="t-top"><h3 class="t-name">%s</h3>%s</div>%s'
            '<div class="t-desc">%s</div><div class="t-quiet">no steward record yet &middot; <a class="t-open" href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></article>'
        ) % (cls, cid, pid, attr, name, xbtn, goal_line, esc((e.get("blurb") or "").strip()[:160]) or "&mdash;", pid)
    wait = " ".join(str(f.get("needs_you") or "").split())[:160]
    nxt = esc((f.get("next") or "")[:160]) or "not stated"
    # W1 (2026-09-28): EVERY effort's wait, each opening its own record (the Status part on that effort) — a
    # project's second effort no longer disappears behind the one touched last. A wait promoted from another
    # effort (the shown one has none) is that effort's line, with its open; the rest follow it.
    promoted = str(f.get("needs_you_effort") or "")
    other_waits = [x for x in (f.get("other_waits") or []) if isinstance(x, dict)]

    def _eff_line(x):
        a = x.get("age_days")
        a_s = (' <span class="t-age">&middot; %d day%s</span>' % (int(a), "" if int(a) == 1 else "s")) if isinstance(a, (int, float)) and a >= 1 else ""
        return ('<div class="t-line wait"><span class="mk">&#9873; %s:</span>%s%s '
                '<button class="t-eff-open" data-part="status" data-pid="%s" data-dir="%s">open</button></div>') % (
            esc(x.get("name")), esc(" ".join(str(x.get("needs_you") or "").split())[:160]), a_s, pid, esc(x.get("rel")))
    lead_x = next((x for x in other_waits if str(x.get("rel") or "") == promoted), None) if (wait and promoted) else None
    if lead_x is not None:
        line = _eff_line(lead_x)
        # the Next line is the SHOWN effort's, named, so a promoted wait never reads as that effort's next (Grok W1)
        more_next = '<div class="t-next"><span class="k">Next &middot; %s</span>%s</div>' % (rel or "root", nxt)
    elif wait:
        # W2 (2026-09-28): the age of the wait, from the record (home_rows._wait_age_days) — nothing when unknown
        age = f.get("wait_age_days")
        age_s = (' <span class="t-age">&middot; %d day%s</span>' % (int(age), "" if int(age) == 1 else "s")) if isinstance(age, (int, float)) and age >= 1 else ""
        line = '<div class="t-line wait"><span class="mk">&#9873; Needs you:</span>%s%s</div>' % (esc(wait), age_s)
        more_next = '<div class="t-next"><span class="k">Next</span>%s</div>' % nxt
    else:
        line = '<div class="t-line"><span class="k">Next</span>%s</div>' % nxt
        more_next = ""
    for x in other_waits:
        if x is lead_x:
            continue
        line += _eff_line(x).replace('class="t-line wait"', 'class="t-line wait other"', 1)
    if f.get("efforts_gap"):
        line += '<div class="t-line dim">&#9888; %s</div>' % esc(f["efforts_gap"])   # never a silent empty list (Grok W1)
    # W4 (2026-09-28): a repair PROPOSED after an acceptance waits on his word — "proposed: N corrections"; the Status
    # part shows the set with accept and dismiss; nothing inside approved work changes before (his Q2)
    props = [p for p in (f.get("repair_proposals") or []) if isinstance(p, dict)]
    if props:
        n = sum(int(p.get("count") or 0) for p in props)
        line += ('<div class="t-line prop"><span class="mk">&#9881; proposed:</span>%d correction%s '
                 '<button class="t-eff-open" data-part="status" data-pid="%s" data-dir="%s">see</button></div>') % (n, "" if n == 1 else "s", pid, rel)
    acts = "".join('<button data-part="%s" data-pid="%s" data-dir="%s">%s</button>' % (part, pid, rel, label) for part, label in _ACTS)
    acts += _resume_act(pid, rel, f.get("resume"))
    return (
        '<article class="tile%s" id="card-%s" data-tile="%s" data-dir="%s"%s><div class="t-top"><h3 class="t-name"><span class="t-nm">%s</span>%s</h3>'
        '<a class="t-go" href="%s" target="_blank" rel="noopener" title="Open the cockpit">cockpit &#8599;</a>%s</div>%s'
        '%s<div class="t-more"><div class="t-desc">%s</div>%s</div>'
        '<div class="t-acts">%s</div>'
        '<div class="t-body" hidden></div></article>'
    ) % (cls, cid, pid, rel, attr, name, ('<span class="t-eff">&middot; %s</span>' % rel) if rel else "", esc(step["href"]) if (step and step.get("kind") == "effort" and step.get("href")) else "/project/%s" % pid, xbtn, goal_line,
         line, esc((e.get("blurb") or "").strip()[:220]) or "&mdash;", more_next, acts)



def _desk_line(ctx):
    return (
        '<section class="deskline" id="deskline"><div class="dl-row"><span class="dl-k">Desk</span><span class="dl-d">&middot; admin, no project</span>'
        '<button class="dchip" id="chipTasks" data-desk="tasks">Tasks &middot; <span id="taskTotal">%d</span></button>'
        '<span class="dl-sp"></span>%s</div>'
        '<div class="dl-body" id="deskBody"><p class="ptile-note">%s</p></div></section>'
    ) % (int(ctx.get("tasks_open") or 0),
         ('<a class="dl-open" href="/project/%s?view=desk" target="_blank" rel="noopener" title="the Desk view of the Campaign record">Open the Desk cockpit &rarr;</a>' % esc((ctx.get("campaign") or {}).get("pid")))
         if ctx.get("campaign") else '<span class="dl-open muted" title="The Desk reads the Campaign record, which is not stood up yet">Open the Desk cockpit &mdash; after the Campaign exists</span>',
         "The Desk reads the Campaign record&rsquo;s tasks; this old task list stays on the old dashboard until your word." if ctx.get("campaign")
         else "The task list still lives on the old dashboard until the Campaign exists.")


def _ruler(ctx):
    weeks, buckets, beyond, overdue = ruler_markers(list(ctx["facts"].values()), ctx["today"])
    head = "".join('<div%s><b>%s</b><span class="sm">%s</span></div>' % (' class="now"' if k == 0 else "", esc(w["label"]), esc(w["name"])) for k, w in enumerate(weeks))
    head += '<div class="beyond"><b>%s&ndash;</b><span class="sm">beyond the ruler</span></div>' % esc(_hr.short_date((weeks[-1]["end"] + timedelta(days=1)).isoformat()))
    on_board = ctx.get("on_board") or set()

    def marker(m):
        where = ("&#9873; " if m["needs"] else "") + (("seated on %s" % on_board[m["project_id"]]) if m["project_id"] in on_board else "in the Projects tile")      # W2c: the shelves are the seats
        return ('<a class="mkcard%s" href="/project/%s" target="_blank" rel="noopener"><span class="mk-date">%s</span><span class="mk-what">%s%s</span>'
                '<span class="mk-proj">%s</span><span class="mk-where">%s</span></a>' % (
                    " late" if m["overdue"] else "", esc(m["project_id"]), esc(_short(m["date"])), esc(m["name"]),
                    " &middot; overdue" if m["overdue"] else (" &middot; &#9873; needs you" if m["needs"] else ""), esc(m["project_name"]), where))
    cols = []
    for k in range(5):
        inner = "".join(marker(m) for m in buckets[k])
        if k == 0 and not inner:
            nearest = next((m for kk in range(1, 5) for m in buckets[kk]), None) or (beyond[0] if beyond else None)
            inner = '<p class="empty-week"><b>This week, %s</b>No registered delivery this week. %s</p>' % (
                esc(weeks[0]["label"]), ("Nearest: %s, %s." % (esc(nearest["name"]), esc(_short(nearest["date"])))) if nearest else "Nothing carries a date yet.")
        cols.append('<div%s id="week%d">%s</div>' % (' class="now"' if k == 0 else "", k + 1, inner))
    cols.append('<div class="beyond" id="weekBeyond">%s</div>' % "".join(marker(m) for m in beyond[:8]))
    total = sum(len(v) for v in buckets.values()) + len(beyond) + len(overdue)
    late = ('<div class="shelf-foot late">Overdue, before this week: %s.</div>' % "; ".join(
        '<a href="/project/%s" target="_blank" rel="noopener">%s</a> (%s, %s)' % (esc(m["project_id"]), esc(m["name"]), esc(_short(m["date"])), esc(m["project_name"]))
        for m in overdue[:6])) if overdue else ""
    return (
        '<section class="shelf" id="shDated"><div class="shelf-h"><h3>Dated deliveries</h3><span class="c">%d dated step%s</span><span class="rule"></span>'
        '<span class="note">Each marker is a dated open step in a project&rsquo;s record. Click one to balloon it open.</span></div>'
        '<div class="ruler" id="ruler"><div class="rl-head">%s</div><div class="rl-marks" id="rlMarks">%s</div></div>'
        '%s<div class="shelf-foot">Each marker points at the one card that owns it &mdash; no project has a second card.</div>'
        '<section class="cal" id="cal"><button class="cal-h" id="calHead"><span class="k">Calendar</span><span class="state">&middot; not connected</span>'
        '<span class="cal-tab" id="tabCal">Calendar</span><span class="cal-tab" id="tabMail">Email</span><span class="sp"></span><span class="tog" id="calTog">Open</span></button>'
        '<div class="cal-body" id="calBody"><p class="conn-zero">No account is connected, so there is nothing to show &mdash; nothing here is sample data. '
        'Connecting means two app registrations (Google, Microsoft) and a sign-in per account; Anchor would read before it ever writes, and every send or calendar change would ask you first.</p></div></section>'
        '</section>'
    ) % (total, "" if total == 1 else "s", head, "".join(cols), late)


def _workbench(ctx):
    live = ctx.get("live") or []
    n = len(live)
    items = "".join('<span class="live">&#9679; live</span><span>%s</span>' % esc(l.get("text")) for l in live[:3])
    # health and failed rows belong to this line and the Doctor, not to Today (fit line 2)
    sys_rows = [r for r in ctx.get("rows") or () if r.get("rule") in ("health", "failed")]
    sys_html = "".join('<a class="bench-row %s" href="%s"%s>%s <span class="dim">&middot; %s</span></a>' % (
        esc(r.get("severity")), esc(r.get("href")), ' target="_blank" rel="noopener"' if str(r.get("href", "")).startswith("/") else "",
        esc(r.get("text")), esc(r.get("why"))) for r in sys_rows[:4])
    if not live and not sys_rows:
        # W5 (2026-09-28): nothing running and nothing failed — one line, not a box saying so (fit contract 7)
        return ('<section class="shelf" id="shBench"><div class="shelf-h"><h3>Workbench</h3><span class="c">nothing running</span><span class="rule"></span>'
                '<a class="dbtn cockpit" href="/project/__dashboard__?classic=1" target="_blank" rel="noopener">Open cockpit</a></div></section>')
    return (
        '<section class="shelf" id="shBench"><div class="shelf-h"><h3>Workbench</h3><span class="c">%d running</span><span class="rule"></span></div>'
        '<div class="bench" id="bench">%s<span class="dim">Terminals, runs and registers stay in the cockpit. This board does not repeat them.</span>'
        '<span style="flex:1"></span><a class="dbtn cockpit" href="/project/__dashboard__?classic=1" target="_blank" rel="noopener">Open cockpit</a></div>%s</section>'
    ) % (n, items or '<span class="dim">nothing running</span>', ('<div class="bench-sys">%s</div>' % sys_html) if sys_html else "")


def _seed_panel(ctx):
    """What the Seeds button opens (John, 2026-09-27: "nothing happens. Something should happen"): the Campaign's
    seeds, each with Make it an initiative — which puts the steward's own verb into the composer ("make <seed> an
    initiative in tier 3"), his Send being the word — and the way to the Campaign, where the tier and the life area
    are asked on the card. Nothing here writes."""
    rows = ctx.get("seed_rows") or []
    camp = ctx.get("campaign") or {}
    if not camp:
        body = '<div class="sd"><span class="st dim">The Campaign is not stood up yet; seeds arrive with it.</span></div>'
    elif not rows:
        body = '<div class="sd"><span class="st dim">No seeds yet.<em>Tell the steward &ldquo;seed: &hellip;&rdquo; here, or in a cockpit&rsquo;s grasscatcher.</em></span></div>'
    else:
        body = "".join(
            '<div class="sd" data-seed="%s"><span class="st">%s<em>%s</em></span>'
            '<button class="go" data-seed-text="%s" title="puts the verb in the composer; Send is the word">Make it a goal</button></div>' % (
                esc(r.get("id")), esc(r.get("text")), ("caught " + esc(_hr.short_date(r.get("at")))) if r.get("at") else "from the grasscatcher", esc(r.get("text")))
            for r in rows)
    foot = ('<div class="hint">A seed becomes a goal in tier 3 unless you say the tier and the life area &mdash; '
            '<a href="/project/%s" target="_blank" rel="noopener">the Campaign</a> asks both on the card.</div>' % esc(camp.get("pid"))) if camp else ""
    return '<section class="seedpanel" id="seedPanel"><h4>Seeds &middot; %d</h4>%s%s</section>' % (len(rows), body, foot)


def _head_li(ctx):
    """W2 (2026-09-28): the head — ONE act as the lead, rendered from the head itself (so the sentence can never
    diverge from its button): the sentence, then the act that opens its record (the Status part on that project's
    card — on the card's own effort unless the act names one), marked when it is the exception. Under it, only the
    week's dates, folded and named for what they hold (Grok W2: the old count brief is gone)."""
    import home_attention as _ha
    head = ctx.get("head") if isinstance(ctx.get("head"), dict) else None
    pickup = ctx.get("pickup") if isinstance(ctx.get("pickup"), dict) else None   # W1 of the active set: while the set runs, what to pick up
    lead = esc(_ha.head_sentence(head, overnight=ctx.get("overnight") or (), pickup=pickup))
    cls = "lead exc" if head and head.get("kind") == "exception" else "lead"
    act = ""
    if head and head.get("pid"):
        dir_attr = (' data-dir="%s"' % esc(head["dir"])) if head.get("dir") else ""   # only an act that names its effort
        act = ' <button class="h-open" data-part="status" data-pid="%s"%s>open</button>' % (esc(head["pid"]), dir_attr)
    elif head is None and pickup and pickup.get("pid"):
        act = ' <button class="h-open" data-part="status" data-pid="%s">open</button>' % esc(pickup["pid"])   # the pick-up opens its project
    week = [b for b in (ctx.get("bullets") or [])[1:] if str(b).startswith(("This week", "Nothing is due this week", "Nothing carries a date"))]
    more = ('<details class="brief-more"><summary>this week</summary><ul>%s</ul></details>' % "".join('<li>%s</li>' % esc(b) for b in week)) if week else ""
    return '<li class="%s">%s%s</li>%s' % (cls, lead, act, ('<li class="fold">%s</li>' % more) if more else "")


def _dialogue(ctx):
    """The steward's dialogue on the High Seat (W2c-2, 2026-09-30, his word: both dialogues "need to engage the steward
    and then show the dialogue between the user and the steward"): the Campaign's one conversation log — the last 40
    turns, a turn said from a goal's place with the goal's chip — under the composer, live from the open through the
    cockpit's stream (static/steward-dialogue.js, the one mechanism the Campaign page uses), the steward's state at its
    head. Nothing here without a Campaign."""
    if not ctx.get("campaign"):
        return ""
    st = ctx["steward"]
    turns = (ctx.get("turns") or [])[-40:]
    n_all = int(ctx.get("n_turns") or len(turns))
    names = ctx.get("goal_names") or {}
    camp_pid = esc((ctx.get("campaign") or {}).get("pid") or "")

    def chip(t):
        g = str(t.get("goal") or "")
        if not g:
            return ""
        return '<a class="gchip" href="/project/%s?open=%s" target="_blank" rel="noopener" title="its place on the Campaign page">about %s</a>' % (camp_pid, esc(g), esc(names.get(g) or g))
    ex = "".join('<li class="exrow %s"><div class="exw %s">%s%s<span class="t">%s</span></div><div class="ext">%s</div></li>' % (
        "you" if t["you"] else "st", "you" if t["you"] else "st", "You" if t["you"] else esc(st["label"]), chip(t), esc(t["at"]), esc(t["text"][:1600])) for t in turns)
    note = ("the last %d of %d" % (len(turns), n_all)) if n_all > len(turns) else (("%d turn%s" % (n_all, "" if n_all == 1 else "s")) if n_all else "")
    return (
        '<section class="exwrap" id="dialogue" aria-live="polite"><div class="exhead"><h3>%s &mdash; the conversation</h3><span class="exstate" id="exState" data-state="">&hellip;</span><span class="note" id="exNote">%s</span></div>'
        '<div class="scroll" id="exScroll"><ul class="ex" id="exList">%s%s</ul></div></section>'
    ) % (esc(st["label"]), note, ex, "" if turns else '<li class="exfade">Nothing said here yet. This is the same conversation as the Campaign page and its cockpit.</li>')


def _panel(ctx):
    st = ctx["steward"]
    bullets = _head_li(ctx)
    rows = ctx.get("rows") or []
    facts = ctx["facts"]

    def trow(r):
        href = r.get("href") or ""
        proj = facts.get(r.get("project_id")) or {}
        meta = []
        if proj.get("name"):
            meta.append('<a class="src" href="/project/%s" target="_blank" rel="noopener">%s</a>' % (esc(r.get("project_id")), esc(proj["name"])))
        if r.get("rule") in ("overdue", "due-today", "due-soon"):
            meta.append('<span class="due soon">%s</span>' % esc(r.get("why")))
        elif r.get("why"):
            meta.append('<span class="st">%s</span>' % esc(r.get("why")[:120]))
        if r.get("rule") == "needs-you":
            meta.append('<span class="wm">&#9873; needs you</span>')
        meta.append('<span class="st">raised by: %s</span>' % esc(r.get("rule_label")))
        return '<li class="trow"><span class="tb"><span class="tt">%s</span><span class="tm">%s</span></span></li>' % (
            ('<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(href), esc(r.get("text")))) if href.startswith("/") else esc(r.get("text")), "".join(meta))
    today_rows = "".join(trow(r) for r in rows if r.get("rule") not in ("health", "failed"))
    n_today = sum(1 for r in rows if r.get("rule") not in ("health", "failed"))
    seeds = int(ctx.get("seeds") or 0)
    # Later this week: dated open steps after today, through Sunday
    today = ctx["today"]
    week_end = today + timedelta(days=6 - today.weekday())
    later = []
    for f in facts.values():
        for stp in f.get("dated") or ():
            d = _hr._iso(stp.get("due"))
            if d is not None and today < d <= week_end:
                later.append((d, stp, f))
    later.sort(key=lambda x: (x[0], x[1].get("name", "")))
    later_html = "".join('<li class="trow"><span class="tb"><span class="tt"><a href="/project/%s" target="_blank" rel="noopener">%s</a></span>'
                         '<span class="tm"><span class="src">%s</span><span class="due soon">due %s</span></span></span></li>' % (
                             esc(f.get("id")), esc(stp.get("name")), esc(f.get("name")), esc(_short(stp.get("due")))) for d, stp, f in later[:6])
    nearest = None
    for f in facts.values():
        for stp in f.get("dated") or ():
            d = _hr._iso(stp.get("due"))
            if d is not None and d > week_end and (nearest is None or d < nearest[0]):
                nearest = (d, stp, f)
    span_start = today + timedelta(days=1)
    span = _short(span_start.isoformat()) if span_start >= week_end else "%s&ndash;%s" % (esc(_short(span_start.isoformat())), esc(_short(week_end.isoformat())))
    later_block = ('<div class="blockk">Later this week &middot; %s</div>%s' % (
        span if span_start <= week_end else "the week is over",
        ('<ul class="tlist">%s</ul>' % later_html) if later_html else
        ('<p class="emptyline"><b>Nothing is dated inside the rest of this week.</b>%s</p>' % (
            (" The next dated step is %s (%s, %s)." % (esc(nearest[1].get("name")), esc(_short(nearest[1].get("due"))), esc(nearest[2].get("name")))) if nearest else ""))))
    return (
        '<aside class="panel"><div class="seedbar"><button class="seedbtn" id="seedBtn" aria-expanded="false" aria-controls="seedPanel"><span>Seeds</span><span class="cnt" id="seedCount">%d</span></button><span class="lbl" id="seedLbl">%s</span></div>%s'
        '<section class="brief" id="brief"><div class="kicker">The brief <span class="k-when" id="briefWhen">%s</span></div><ul class="blist" id="briefList">%s</ul></section>'
        # R14 (2026-09-29): the token is pasted INTO the page — a browser pop-up (window.prompt) is what his desktop
        # browser suppressed ("I click that button and nothing happens"); the box is hidden until it is needed
        '<div class="loginbox" id="loginBox" hidden><span class="lb-t">This browser is not logged in to Anchor.</span>'
        '<input id="loginTok" type="password" placeholder="paste the token here" autocomplete="off" spellcheck="false">'
        '<button class="mini" id="loginGo">Log in</button><span class="lb-msg" id="loginMsg"></span></div>'
        '<section class="composer"><label class="sr" for="say">Tell the steward what to do</label>'
        '<textarea id="say" rows="2" placeholder="Tell %s what to do &mdash; it acts on the whole portfolio"></textarea>'
        '<div class="comp-row"><span class="hint">Ctrl+Enter sends &middot; start a new project called &lt;name&gt; at &lt;folder&gt; &middot; what next?</span><button class="send" id="sendBtn">Send</button></div>'
        '<div class="receipt" id="receipt" hidden><span class="r-mark">&#10003;</span><span id="receiptText"></span> <button class="mini" id="undoBtn" hidden>undo</button></div></section>'
        '%s'
        '<section class="today" id="todayBlock"><div class="today-h"><h3>Today</h3><span class="c">%d raised</span></div>'
        '<div class="today-sub">What needs you, and what is due soonest &mdash; every row a fact from a record, each saying what raised it.</div>'
        '<ul class="tlist">%s</ul>%s</section></aside>'
    ) % (seeds, "ideas that could start a project" if seeds else "no seeds yet", _seed_panel(ctx),
         esc(ctx["brief_when"]), bullets, esc(st["label"]), _dialogue(ctx), n_today, today_rows or '<li class="trow"><span class="tb"><span class="tt">Nothing is waiting on you.</span></span></li>', later_block)


def render_high_seat_html(ctx) -> str:
    """The whole page from the context dict (see the module docstring)."""
    facts = ctx["facts"]
    entries = ctx.get("entries") or []
    by_id = {e.get("id"): e for e in entries}
    parked = ctx.get("parked") or []
    parked_ids = {e.get("id") for e in parked}
    inits = ctx.get("initiatives") or []
    live_inits = [i for i in inits if i.get("status") not in ("done", "parked")]
    # W2c (2026-09-30, his three levels): the goals as a thin tile, then ACTIVE and ON DECK as shelves of initiative
    # cards; the Projects tile (the registry) with its projects in no goal; the Desk, the ruler and the Workbench as
    # before. The old shelves (Needs you · Continuing · Parked) are gone: a project is on a shelf because he seated
    # it, and every project is in the Projects tile.
    in_goal = {p["pid"] for i in inits for p in i.get("parts") or () if p.get("kind") in ("project", "effort") and p.get("pid")}
    camp_pid = (ctx.get("campaign") or {}).get("pid")
    ctx["orphans"] = [e for e in entries if e.get("id") and e["id"] not in in_goal and e["id"] != camp_pid and e["id"] not in parked_ids]
    ctx["quiet_n"] = sum(1 for e in entries if not (facts.get(e.get("id")) or {}).get("has_record") and e.get("id") not in parked_ids)
    ctx["on_board"] = {p["pid"]: SEAT_NAMES[seat] for seat in ("deck", "active") for g, p in seated(live_inits, seat) if p.get("pid")}      # Active wins when a project has cards on both (Grok's read of W2c)
    board = ('<div class="board">' + _campaign_tile(ctx) + _seat_shelves(ctx) + _projects_tile(ctx)
             + _desk_line(ctx) + _ruler(ctx) + _workbench(ctx) + '</div>')
    page = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>%s</title><link rel="icon" href="/vendor/brand/%s?v=%s">'
        '<link rel="stylesheet" href="/static/steward-dialogue.css?v=%s"><link rel="stylesheet" href="/static/high-seat-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s", auth_required: %s, steward: "%s", stamp: "%s"};</script></head>'
        '<body><div class="app">%s<div class="main">%s%s<div class="prefs">%s</div><div class="canvas">%s%s</div>'
        '<div class="foot">%s<span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span>'
        '<span>&mdash; every row on this page is read from a record; where nothing is connected or measured, it says so.</span></div></div></div>'
        '<script src="/static/steward-dialogue.js?v=%s"></script><script src="/static/high-seat-page.js?v=%s"></script></body></html>'
    ) % (esc(ctx["steward"]["high_seat_name"]), esc(ctx["steward"].get("high_seat") or "gwl-m-icon.svg"), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc((ctx.get("campaign") or {}).get("pid") or ""), "true" if ctx.get("auth_required") else "false",
         esc(ctx["steward"]["label"]), esc(str(ctx.get("stamp") or "")), _rail(ctx), _masthead(ctx), _hdr(ctx),
         ctx.get("prefs_html") or "", board, _panel(ctx), _brand_img(ctx["build"], "gwl-m-icon.svg"), esc(ctx["build"]), esc(ctx["build"]))
    return page
