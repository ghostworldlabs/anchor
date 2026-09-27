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
                    "href": r.get("href") or "", "status": str(p.get("status") or ""),
                    "broken": bool(r.get("broken")) if ref else False, "gap": r.get("gap") or "",
                    "needs_you": "waiting on you" in str(state).lower(),
                })
        open_parts = [p for p in parts if p["status"] not in ("done", "parked") and not p["broken"]]
        dates = sorted(p["date"] for p in open_parts if p["date"])
        out.append({
            "id": sid, "name": s.get("name") or sid, "tier": int(s["tier"]) if s.get("tier") in (1, 2, 3) else None,
            "order": int((own or {}).get("order") or 0), "area": str(s.get("area") or ""),
            "done_when": s.get("done_when") or "", "status": s.get("status") or "",
            "parts": parts, "next": open_parts[0] if open_parts else None,
            "needs": [p for p in parts if p["needs_you"]], "next_deadline": dates[0] if dates else "",
            "done_count": sum(1 for p in parts if p["status"] == "done"),
        })
    out.sort(key=lambda i: (i["tier"] or 9, i["order"], i["name"]))   # an untiered initiative sorts last, its tier shown as missing
    for n, i in enumerate(out, 1):
        i["number"] = n
    return out


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


def _rail(ctx):
    st = ctx["steward"]
    counts = ctx.get("counts") or {}
    n_camp = len(ctx.get("initiatives") or [])
    n_needs = sum(1 for f in ctx["facts"].values() if f.get("needs_you"))
    n_park = len(ctx.get("parked") or [])
    n_bench = int(counts.get("running") or 0)
    cap_rows = "".join(
        '<div class="cr"><div class="cr-top"><span class="cr-n">%s</span><span class="cr-none">%s</span></div>'
        '<div class="cr-sub">%s</div></div>' % (esc(c["name"]), esc(c["state"]), esc(c["note"]))
        for c in ctx.get("capacity") or ())
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
        '<li><button data-rail="needs"><span class="n"><span class="mark-wait">&#9873;</span> Needs you</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="week"><span class="n">This week</span><span class="c">%s</span></button></li>'
        '<li><button data-rail="desk"><span class="n">Desk</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="parked"><span class="n">Parked</span><span class="c">%d</span></button></li>'
        '<li><button data-rail="calendar"><span class="n">Calendar</span><span class="c">not connected</span></button></li>'
        '<li><button data-rail="email"><span class="n">Email</span><span class="c">not connected</span></button></li>'
        '<li><button data-rail="bench"><span class="n">Workbench</span><span class="c">%d</span></button></li>'
        '</ul>'
        '<div class="cap"><h3>Capacity &middot; window and week</h3><div id="capList">%s</div></div>'
        '</nav>'
    ) % (_brand_img(ctx["build"], "gwl-m-icon.svg"), _brand_img(ctx["build"], "gwl-m-icon.svg"),
         _brand_img(ctx["build"], st["high_seat"], ""), esc(st["high_seat_name"]),
         esc(st["high_seat_name"]), (str(n_camp) if ctx.get("campaign") else "not yet"), n_needs,
         esc(ctx["week_short"]), int(ctx.get("tasks_open") or 0), n_park, n_bench, cap_rows)


def _masthead(ctx):
    b = ctx["build"]
    return (
        '<div class="masthead"><div class="mh-title"><span class="a">&#9875;</span>Anchor</div><div class="mh-div"></div>'
        '<div class="mh-lock">%s<div><div class="mh-w1">Ghost World <span class="gwl-accent">Labs</span></div>'
        '<div class="mh-w2">R&amp;D Mission Control</div></div></div><div class="mh-sp"></div>'
        '<div class="mh-pill">AI Cockpit %s</div></div>'
    ) % (_brand_img(b, "gwl-m-icon.svg"), _brand_img(b, "gwl-m-icon.svg"))


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


def _campaign_tile(ctx):
    camp = ctx.get("campaign")
    inits = ctx.get("initiatives") or []
    if not camp:
        return ('<section class="camp" id="camp"><div class="camp-h" id="campHead"><span class="k">Campaign</span>'
                '<span class="d">&middot; not stood up yet &mdash; the record arrives with the import, after your seed check</span>'
                '<span class="sp"></span></div></section>')
    t1 = [i for i in inits if i["tier"] == 1]
    t2 = sum(1 for i in inits if i["tier"] == 2)
    t3 = sum(1 for i in inits if i["tier"] == 3)
    untiered = sum(1 for i in inits if i["tier"] is None)
    t1_dates = sorted(i["next_deadline"] for i in t1 if i["next_deadline"])
    nearest = ""
    if t1_dates:
        who = next(i for i in t1 if i["next_deadline"] == t1_dates[0])
        nearest = "%s, %s" % (esc((who["next"] or {}).get("text") or who["name"]), esc(_short(t1_dates[0])))
    line = ('&middot; your initiatives &middot; <b>Tier 1:</b> %s &middot; next deadline: <b>%s</b> &middot; <b>%d</b> seeds' % (
        esc(", ".join(i["name"] for i in t1)) if t1 else "none yet", nearest or "none dated", int(ctx.get("seeds") or 0)))
    tiles = []
    for i in t1:
        nxt = i["next"]
        wait = i["needs"][0] if i["needs"] else None
        def _part_row(p):
            state = ("broken reference: " + p["gap"]) if p["broken"] else (p["state"] or p["status"])
            crit = " crit" if (p["broken"] or p["needs_you"]) else ""
            date = _hr.due_label(p["date"], ctx["today"]) if p["date"] else "no date"
            return (
                '<div class="ptr%s"><span class="pt-kind %s">%s</span><span class="pt-what">%s%s</span>'
                '<span class="pt-state%s">%s</span><span class="pt-date%s">%s</span>%s</div>' % (
                    " pdone" if p["status"] == "done" else "", esc(p["kind"]), esc(p["kind"]), esc(p["text"]),
                    (' <span class="dim">&middot; %s</span>' % esc(p["target"])) if p["target"] and p["kind"] != "task" else "",
                    crit, esc(state), " none" if not p["date"] else (" soon" if date.startswith(("due today", "overdue")) else ""), esc(date),
                    (' <a class="pt-open" href="%s" target="_blank" rel="noopener">open the cockpit</a>' % esc(p["href"])) if p["href"] else ""))
        rows = ('<div class="pt-legend">Its parts, as the Campaign holds them &mdash; kind &middot; what &middot; its state in its own record &middot; its date. '
                'Read-only here; the Campaign page is where they move.</div>' + "".join(_part_row(p) for p in i["parts"]))
        tiles.append(
            '<article class="ini-tile%s" data-ini="%d"><div class="it-top"><span class="it-no">%d</span>'
            '<h4 class="it-name">%s</h4>%s</div>'
            '<div class="it-done"><span class="k">Done looks like</span>%s</div>'
            '<div class="it-next"><span class="k">Next</span>%s</div>%s'
            '<div class="it-foot"><span class="dl %s">%s</span><span class="cnt">%d parts &middot; %d need you</span></div>'
            '<div class="it-parts">%s</div></article>' % (
                " needs" if i["needs"] else "", i["number"], i["number"], esc(i["name"]),
                ('<span class="it-area">%s</span>' % esc(i["area"].title())) if i["area"] else "",
                esc(i["done_when"]) or "not written yet &mdash; say what done looks like",
                (esc(nxt["text"]) + ' <span class="dim">&middot; %s</span>' % esc(nxt["kind"])) if nxt else "nothing open",
                ('<div class="it-wait"><span class="mk">&#9873; Needs you:</span>%s</div>' % esc(wait["text"])) if wait else "",
                "soon" if i["next_deadline"] else "none",
                ("next deadline " + esc(_short(i["next_deadline"]))) if i["next_deadline"] else "no deadline",
                len(i["parts"]), len(i["needs"]), rows))
    body = (
        '<div class="camp-note"><b>Tier 1 &middot; do first &middot; %d initiative%s</b> &middot; &#9873; %d need you &mdash; click one to see its specifics. '
        'The tiers, the re-ranking and the calendar view are in the Campaign.</div>'
        '<div class="t1grid">%s</div>'
        '<div class="camp-tiers"><span><b>Tier 2</b> &middot; %d &middot; <b>Tier 3</b> &middot; %d%s &mdash; <span class="rest">open the Campaign for the rest</span></span></div>'
    ) % (len(t1), "" if len(t1) == 1 else "s", sum(1 for i in t1 if i["needs"]), "".join(tiles) or '<div class="camp-note">No Tier 1 initiative yet.</div>', t2, t3,
         (" &middot; <b>no tier yet</b> &middot; %d" % untiered) if untiered else "")
    return (
        '<section class="camp" id="camp"><div class="camp-h" id="campHead"><span class="k">Campaign</span>'
        '<span class="d" id="campLine">%s</span><span class="sp"></span><span class="tog" id="campTog">Show Tier 1</span>'
        '<a class="camp-open" href="/project/%s" target="_blank" rel="noopener">Open the Campaign</a></div>'
        '<div class="camp-body" id="campBody">%s</div></section>'
    ) % (line, esc(camp["pid"]), body)


def _projects_tile(ctx):
    groups = ctx.get("groups") or {}
    facts = ctx["facts"]
    on_board = ctx.get("on_board") or set()
    folds = []
    for folder in sorted(groups, key=lambda g: (g == "Ungrouped", g.lower())):
        entries = groups[folder] or []
        waits = sum(1 for e in entries if (facts.get(e.get("id")) or {}).get("needs_you"))
        rows = []
        for e in entries:
            f = facts.get(e.get("id")) or {}
            lead = ""
            summ = f.get("summary") if isinstance(f.get("summary"), dict) else None
            if summ and summ.get("lead_line"):
                lead = str(summ["lead_line"])[:160]
            elif f.get("next"):
                lead = ("Next: " + f["next"])[:160]
            rows.append(
                '<div class="prow" data-pid="%s"><div class="pn">%s%s</div><div class="pb">%s</div><div class="pl"><span class="q">%s:</span> %s</div></div>' % (
                    esc(e.get("id")), esc(e.get("name")),
                    '<button class="go" data-goto="%s">on the board</button>' % esc(e.get("id")) if e.get("id") in on_board else '<span class="nocard">no card today</span>',
                    esc((e.get("blurb") or "").strip()[:200]) or "&mdash;", esc(ctx["steward"]["label"]), esc(lead) or "No next step registered."))
        folds.append(
            '<div class="fold open"><button class="fold-h" data-fold="%s"><span class="fn">%s</span><span class="fc">%d</span><span class="tw">%s</span></button>'
            '<div class="fold-rows">%s</div></div>' % (esc(folder), esc(folder), len(entries), ("&#9873; %d waiting on you" % waits) if waits else "", "".join(rows)))
    n = sum(len(v) for v in groups.values())
    return (
        '<section class="ptile" id="ptile"><button class="ptile-h" id="ptileToggle"><span class="k">Projects</span>'
        '<span class="n" id="ptileCount">&middot; as they are now &middot; %d in %d folders</span><span class="sp"></span><span class="tog" id="ptileTog">Show all</span></button>'
        '<div class="ptile-body"><div class="ptile-note">The registry as it stands &mdash; every project in its folder, ranked by nobody. The board below is the same projects, ranked.</div>'
        '<div class="addbox"><h4>Add a project</h4><div class="addrow">'
        '<input id="apName" type="text" placeholder="Project name" autocomplete="off">'
        '<a class="mk" id="apCreate" href="/dashboard" target="_blank" rel="noopener">Create on the dashboard</a></div>'
        '<div class="addhint" id="apHint">A new project is still made and confirmed on the old dashboard; this page shows it on the next look.</div></div>'
        '<div id="folders">%s</div></div></section>'
    ) % (n, len(groups), "".join(folds))


def _card(e, f, cls):
    pid = esc(e.get("id"))
    return (
        '<article class="tile%s" id="card-%s" data-tile="%s"><div class="t-top"><h3 class="t-name">%s</h3>'
        '<button class="statusbtn" data-part="status" data-pid="%s">Status</button></div><div class="t-desc">%s</div>'
        '<div class="t-next"><span class="k">Next</span>%s</div>%s'
        '<div class="t-acts"><button data-part="next" data-pid="%s">Next steps</button><button data-part="deliverables" data-pid="%s">Deliverables</button>'
        '<button data-part="plan" data-pid="%s">Plan</button><a class="t-open" href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div>'
        '<div class="t-body" hidden></div></article>'
    ) % (cls, pid, pid, esc(e.get("name")), pid,
         esc((e.get("blurb") or "").strip()[:220]) or "&mdash;",
         esc((f.get("next") or "")[:140]) or "not stated",
         ('<div class="t-wait"><span class="mk">&#9873; Needs you:</span>%s</div>' % esc(" ".join(str(f["needs_you"]).split())[:140])) if f.get("needs_you") else "",
         pid, pid, pid, pid)


def _shelf(sid, title, count_text, note, cards_html, foot=""):
    return (
        '<section class="shelf" id="%s"><div class="shelf-h"><h3>%s</h3><span class="c">%s</span><span class="rule"></span><span class="note">%s</span></div>'
        '<div class="grid">%s</div>%s</section>' % (sid, esc(title), esc(count_text), note, cards_html, ('<div class="shelf-foot">%s</div>' % foot) if foot else ""))


def _desk_line(ctx):
    return (
        '<section class="deskline" id="deskline"><div class="dl-row"><span class="dl-k">Desk</span><span class="dl-d">&middot; admin, no project</span>'
        '<button class="dchip" id="chipTasks" data-desk="tasks">Tasks &middot; <span id="taskTotal">%d</span></button>'
        '<button class="dchip muted" data-desk="cal">Calendar</button><button class="dchip muted" data-desk="mail">Email</button>'
        '<span class="dl-sp"></span><span class="dl-open muted" title="The Desk cockpit is not built yet">Open the Desk cockpit &mdash; not yet</span></div>'
        '<div class="dl-body" id="deskBody"><p class="ptile-note">The task list still lives on the old dashboard until the Desk exists.</p></div></section>'
    ) % int(ctx.get("tasks_open") or 0)


def _ruler(ctx):
    weeks, buckets, beyond, overdue = ruler_markers(list(ctx["facts"].values()), ctx["today"])
    head = "".join('<div%s><b>%s</b><span class="sm">%s</span></div>' % (' class="now"' if k == 0 else "", esc(w["label"]), esc(w["name"])) for k, w in enumerate(weeks))
    head += '<div class="beyond"><b>%s&ndash;</b><span class="sm">beyond the ruler</span></div>' % esc(_hr.short_date((weeks[-1]["end"] + timedelta(days=1)).isoformat()))
    on_board = ctx.get("on_board") or set()

    def marker(m):
        where = "&#9873; its card is on Needs you" if m["needs"] else ("its card is on Continuing" if m["project_id"] in on_board else "in the Projects tile")
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
        '<span class="note">Each marker is a dated open step in a project&rsquo;s record. Click one to open its cockpit.</span></div>'
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
    return (
        '<section class="shelf" id="shBench"><div class="shelf-h"><h3>Workbench</h3><span class="c">%d running</span><span class="rule"></span></div>'
        '<div class="bench" id="bench">%s<span class="dim">Terminals, runs and registers stay in the cockpit. This board does not repeat them.</span>'
        '<span style="flex:1"></span><a class="dbtn cockpit" href="/project/__dashboard__?classic=1" target="_blank" rel="noopener">Open cockpit</a></div>%s</section>'
    ) % (n, items or '<span class="dim">nothing running</span>', ('<div class="bench-sys">%s</div>' % sys_html) if sys_html else "")


def _panel(ctx):
    st = ctx["steward"]
    bullets = "".join('<li%s>%s</li>' % (' class="lead"' if k == 0 else "", esc(b)) for k, b in enumerate(ctx.get("bullets") or []))
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
    later_block = ('<div class="blockk">Later this week &middot; %s&ndash;%s</div>%s' % (
        esc(_short((today + timedelta(days=1)).isoformat())), esc(_short(week_end.isoformat())),
        ('<ul class="tlist">%s</ul>' % later_html) if later_html else
        ('<p class="emptyline"><b>Nothing is dated inside the rest of this week.</b>%s</p>' % (
            (" The next dated step is %s (%s, %s)." % (esc(nearest[1].get("name")), esc(_short(nearest[1].get("due"))), esc(nearest[2].get("name")))) if nearest else ""))))
    return (
        '<aside class="panel"><section class="stew" id="stewBlock">%s<span class="nm"><b id="stewTitle">The %s</b><span id="stewName">%s &middot; your steward</span></span><span class="tag">Steward</span></section>'
        '<div class="seedbar"><button class="seedbtn" id="seedBtn"><span>Seeds</span><span class="cnt" id="seedCount">%d</span></button><span class="lbl" id="seedLbl">%s</span></div>'
        '<section class="brief" id="brief"><div class="kicker">The brief <span class="k-when" id="briefWhen">%s</span></div><ul class="blist" id="briefList">%s</ul></section>'
        '<section class="composer"><label class="sr" for="say">Tell the steward what to do</label>'
        '<textarea id="say" rows="2" placeholder="Tell %s what to do &mdash; it acts on the whole portfolio"></textarea>'
        '<div class="comp-row"><span class="hint">Ctrl+Enter sends &middot; start a new project called &lt;name&gt; at &lt;folder&gt; &middot; what next?</span><button class="send" id="sendBtn">Send</button></div>'
        '<div class="receipt" id="receipt" hidden><span class="r-mark">&#10003;</span><span id="receiptText"></span></div></section>'
        '<section class="today" id="todayBlock"><div class="today-h"><h3>Today</h3><span class="c">%d raised</span></div>'
        '<div class="today-sub">What needs you, and what is due soonest &mdash; every row a fact from a record, each saying what raised it.</div>'
        '<ul class="tlist">%s</ul>%s</section></aside>'
    ) % (_brand_img(ctx["build"], st["high_seat"]), esc(st["high_seat_name"]), esc(st["label"]), seeds,
         "ideas that could start a project" if seeds else "no seeds yet",
         esc(ctx["brief_when"]), bullets, esc(st["label"]), n_today, today_rows or '<li class="trow"><span class="tb"><span class="tt">Nothing is waiting on you.</span></span></li>', later_block)


def render_high_seat_html(ctx) -> str:
    """The whole page from the context dict (see the module docstring)."""
    facts = ctx["facts"]
    entries = ctx.get("entries") or []
    by_id = {e.get("id"): e for e in entries}
    needs = [e for e in entries if (facts.get(e.get("id")) or {}).get("needs_you")]
    parked = ctx.get("parked") or []
    parked_ids = {e.get("id") for e in parked}
    # the locked order (v2.2): needs-you first, then dated inside the five weeks soonest first, then the rest
    horizon = (ctx["today"] + timedelta(days=35)).isoformat()

    def _soon(e):
        f = facts.get(e.get("id")) or {}
        d = f.get("nearest_due") or ""
        return d if d and d <= horizon else ""
    dated = sorted([e for e in entries if e.get("id") not in parked_ids and e not in needs and _soon(e)], key=lambda e: (_soon(e), str(e.get("name") or "")))
    rest = [e for e in entries if e.get("id") not in parked_ids and e not in needs and e not in dated
            and ((facts.get(e.get("id")) or {}).get("next") or (facts.get(e.get("id")) or {}).get("summary") or (facts.get(e.get("id")) or {}).get("dated"))]
    cont = dated + rest
    quiet = [e for e in entries if e not in needs and e not in cont and e.get("id") not in parked_ids]
    ctx["on_board"] = {e.get("id") for e in needs} | {e.get("id") for e in cont} | parked_ids
    board = (
        '<div class="board">' + _campaign_tile(ctx) + _projects_tile(ctx)
        + _shelf("shNeeds", "Needs you", "%d project%s" % (len(needs), "" if len(needs) == 1 else "s"),
                 "Click a card to open its cockpit. Status sits beside the name.",
                 "".join(_card(e, facts.get(e.get("id")) or {}, " need") for e in needs) or '<div class="ptile-note">Nothing waits on you.</div>')
        + _desk_line(ctx) + _ruler(ctx)
        + _shelf("shCont", "Continuing", "%d project%s" % (len(cont), "" if len(cont) == 1 else "s"),
                 "Dated soonest first, then the rest. Moving shelves never makes a second card.",
                 "".join(_card(e, facts.get(e.get("id")) or {}, "") for e in cont) or '<div class="ptile-note">No project carries a next step yet.</div>',
                 ("%d registry project%s no open next step and no card on the board today &mdash; they are in the Projects tile above, in their folders." % (len(quiet), " has" if len(quiet) == 1 else "s have")) if quiet else "")
        + _shelf("shPark", "Parked", "%d project%s" % (len(parked), "" if len(parked) == 1 else "s"), "Off the shelves, still one card each.",
                 "".join(_card(e, facts.get(e.get("id")) or {}, " parked") for e in parked) or '<div class="ptile-note">Nothing is parked.</div>')
        + _workbench(ctx) + '</div>')
    page = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>The %s &middot; Anchor</title><link rel="icon" href="/vendor/brand/gwl-m-icon.svg">'
        '<link rel="stylesheet" href="/static/high-seat-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s"};</script></head>'
        '<body><div class="app">%s<div class="main">%s%s<div class="prefs">%s</div><div class="canvas">%s%s</div>'
        '<div class="foot">%s<span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span>'
        '<span>&mdash; every row on this page is read from a record; where nothing is connected or measured, it says so.</span></div></div></div>'
        '<script src="/static/high-seat-page.js?v=%s"></script></body></html>'
    ) % (esc(ctx["steward"]["high_seat_name"]), esc(ctx["build"]), esc(ctx["build"]), _rail(ctx), _masthead(ctx), _hdr(ctx),
         ctx.get("prefs_html") or "", board, _panel(ctx), _brand_img(ctx["build"], "gwl-m-icon.svg"), esc(ctx["build"]))
    return page
