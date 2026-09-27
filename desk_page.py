"""desk_page — the Desk view of the Campaign record: John's own tasks with the steward, in the cockpit's own shape.

W3b of the High Seat plan (2026-09-26). The approved design is the mockup
``Skill Foundry/planning/high-seat-2026-09-24/ideation/mockups/desk/desk-A.html`` (Desk A); its stylesheet is
``static/desk-page.css`` ported as it is. Three columns, each keeping the job it has in a project cockpit: LEFT the
tasks (the plan's place) — every native task on the Campaign record, grouped Today · This week · Later · Parked ·
Done, each with its initiative chip (the admin initiative's tasks are the Desk's own), editable where it sits;
CENTRE the steward's brief, the composer right below it (John, 2026-09-27), then the last exchanges; RIGHT Calendar and Email closed above the open
status and the capacity lines. Calendar and Email are drawn empty with the reason in words — no account is
connected; the marks on the calendar are the record's own dated tasks. Pure: a context dict in, HTML out; every
count is counted from the record. The acts go through ``steward_cockpit/campaign_acts`` (the same route the
Campaign page uses); a tick on a native task waits on John's word on the close law.
"""
from __future__ import annotations

import calendar as _cal
from datetime import timedelta

import home_rows as _hr
from campaign_page import _needs
from high_seat_page import esc, _brand_img, _masthead, capacity_row_html

GROUPS = ("today", "week", "later", "parked", "done")


def _short(d):
    return _hr.short_date(d) if d else ""


def admin_initiative(initiatives):
    """The Desk's own initiative — the one named admin (the sample's Personal admin); None until it exists."""
    hits = [i for i in initiatives if "admin" in str(i.get("name") or "").lower() or "admin" in str(i.get("id") or "").lower()]
    return hits[0] if hits else None


def desk_tasks(initiatives):
    """Every native task on the record, flattened with its initiative. A referenced part is not a task here — it is
    done in its own cockpit — and is left out."""
    admin = admin_initiative(initiatives)
    out = []
    for i in initiatives:
        for p in i["parts"]:
            if p["kind"] != "task":
                continue
            out.append({"id": p["id"], "text": p["text"], "date": p["date"] or "", "status": p["status"], "needs_you": bool(p["needs_you"]),
                        "waiting_on": p.get("waiting_on") or "", "initiative": i["id"], "initiative_name": i["name"], "tier": i["tier"],
                        "admin": admin is not None and i["id"] == admin["id"]})
    return out


def group_of(t, today, week_end):
    if t["status"] == "done":
        return "done"
    if t["status"] == "parked":
        return "parked"
    if t["needs_you"] or t["status"] == "active":
        return "today"
    d = _hr._iso(t["date"]) if t["date"] else None
    if d and d <= today:
        return "today"
    if d and d <= week_end:
        return "week"
    return "later"


def rank(tasks):
    """Dated soonest, then needs-you, then the rest — the brief's order."""
    return sorted(tasks, key=lambda t: (0 if t["date"] else 1, t["date"] or "", 0 if t["needs_you"] else 1, t["text"].lower()))


def _open(tasks):
    return [t for t in tasks if t["status"] not in ("done", "parked")]


# ── LEFT: the tasks ────────────────────────────────────────────────────────────────────────────

def _row(t, initiatives, today, tick_allowed):
    tid = esc(t["id"])
    done = t["status"] == "done"
    d = _hr._iso(t["date"]) if t["date"] else None
    soon = bool(d) and d <= today + timedelta(days=10)
    lab = _short(t["date"]) + ((" %d" % d.year) if d and d.year != today.year else "")
    date_chip = (('<button class="mchip dated%s" data-act="date" data-id="%s">%s</button>' % (" soon" if soon else "", tid, esc(lab)))
                 if t["date"] else '<button class="mchip" data-act="date" data-id="%s">&middot; no date</button>' % tid)
    opts = "".join('<option value="%s"%s>%s</option>' % (esc(i["id"]), " selected" if i["id"] == t["initiative"] else "",
                                                          "admin" if admin_initiative([i]) is not None else esc(i["name"])) for i in initiatives)
    sel = '<select class="psel%s" data-retag="%s" aria-label="Initiative">%s</select>' % (" admin" if t["admin"] else "", tid, opts)
    flag = ('<button class="mchip%s" data-act="%s" data-id="%s">&#9873; %s</button>' % (
        " flagon" if t["needs_you"] else "", "unflag" if t["needs_you"] else "flag", tid, "needs you" if t["needs_you"] else "flag")) if not done else ""
    park = ("" if done else (('<button class="mchip" data-act="unpark" data-id="%s">unpark</button>' % tid) if t["status"] == "parked"
                             else '<button class="mchip" data-act="park" data-id="%s">park</button>' % tid))
    state = ('<span class="rdone">&#10003; done</span>' if done else
             ('<span class="rstate">parked%s</span>' % ((" until " + esc(t["waiting_on"])) if t["waiting_on"] else "") if t["status"] == "parked" else
              ('<span class="rstate">&#9679; in progress</span>' if t["status"] == "active" else "")))
    tick = '<button class="tick%s" data-act="tick" data-id="%s" aria-label="%s"%s></button>' % (
        " on" if done else "", tid, "Reopen" if done else "Mark done", "" if tick_allowed else ' disabled title="a tick waits on your word on the close law"')
    return ('<li class="row%s" data-row="%s" data-needs="%d" data-dated="%d" data-admin="%d">%s<div class="rb">'
            '<div class="rt" data-act="text" data-id="%s" title="Click to rename">%s</div><div class="rm">%s%s%s%s%s</div></div>'
            '<button class="rx" data-act="del" data-id="%s" aria-label="Remove">&#10005;</button></li>' % (
                " done" if done else "", tid, 1 if t["needs_you"] else 0, 1 if t["date"] else 0, 1 if t["admin"] else 0, tick,
                tid, esc(t["text"]), date_chip, sel, flag, park, state, tid))


def _group(key, title, sub, empty, tasks, initiatives, today, tick_allowed):
    rows = "".join(_row(t, initiatives, today, tick_allowed) for t in tasks)
    return ('<div class="grp" data-group="%s"><div class="gk"><h4>%s</h4><span class="gc" data-gc="%s">%d</span></div>%s%s</div>' % (
        key, title, key, len(tasks), ('<div class="gsub">%s</div>' % sub) if sub else "",
        ('<ul class="rows">%s</ul>' % rows) if rows else '<p class="gempty" data-empty="%s">%s</p>' % (key, empty)))


def _tasks_col(ctx):
    today = ctx["today"]
    monday = today - timedelta(days=today.weekday())
    week_end = monday + timedelta(days=6)
    inits = ctx["initiatives"]
    tasks = desk_tasks(inits)
    admin = admin_initiative(inits)
    open_ = _open(tasks)
    by = {k: rank([t for t in tasks if group_of(t, today, week_end) == k]) for k in GROUPS}
    near = next((t for t in rank([t for t in open_ if t["date"] and _hr._iso(t["date"]) and _hr._iso(t["date"]) > week_end])), None)
    filters = (("all", "All", len(tasks)), ("needs", "&#9873; needs you", sum(1 for t in tasks if t["needs_you"])),
               ("dated", "dated", sum(1 for t in tasks if t["date"])), ("admin", "admin", sum(1 for t in tasks if t["admin"])))
    fbtns = "".join('<button data-filter="%s"%s>%s<span class="n">%d</span></button>' % (k, ' class="on"' if k == "all" else "", lab, n) for k, lab, n in filters)
    week_lab = "%s&ndash;%s" % (esc(_short(monday.isoformat())), esc(_short(week_end.isoformat())))
    groups = (
        _group("today", "Today", "What needs your word, what is moving, and anything dated today or earlier.", "Nothing needs your word and nothing is dated today.", by["today"], inits, today, ctx.get("tick_allowed", False))
        + _group("week", "This week &middot; " + week_lab, "", "<b>Nothing is dated inside this week.</b>" + ((" The nearest is %s, %s." % (esc(near["text"]), esc(_short(near["date"])))) if near else " Nothing else carries a date."), by["week"], inits, today, ctx.get("tick_allowed", False))
        + _group("later", "Later", "Dated past Sunday, or carrying no date at all.", "Nothing sits in Later.", by["later"], inits, today, ctx.get("tick_allowed", False))
        + _group("parked", "Parked", "Each with the trigger that brings it back; unpark brings one back now.", "Nothing is parked.", by["parked"], inits, today, ctx.get("tick_allowed", False))
        + _group("done", "Done", "", "Nothing is ticked yet.", by["done"], inits, today, ctx.get("tick_allowed", False)))
    if inits:
        opts = "".join('<option value="%s"%s>%s</option>' % (esc(i["id"]), " selected" if (admin is not None and i["id"] == admin["id"]) else "",
                                                              "admin" if (admin is not None and i["id"] == admin["id"]) else esc(i["name"])) for i in inits)
        addline = ('<div class="addline"><div class="r1"><input id="addText" type="text" autocomplete="off" placeholder="Add a task &mdash; what needs doing"><button class="mk" id="addBtn">Add</button></div>'
                   '<div class="r2"><input id="addDate" type="text" autocomplete="off" placeholder="2026-10-03 &middot; Oct 3 &middot; or blank"><select id="addProj">%s</select></div>'
                   '<div class="ah">Enter adds it to the initiative chosen &mdash; %s.</div></div>' % (
                       opts, "<b>admin</b> is the Desk&rsquo;s own" if admin is not None else "no admin initiative exists yet, so it goes under the one you pick"))
    else:
        addline = '<div class="addline"><div class="ah">No initiative on the Campaign yet &mdash; the import brings Personal admin, and a task needs an initiative to sit under.</div></div>'
    source = ('The tasks here are the Campaign record&rsquo;s own; <b>admin</b> rows belong to the Desk itself.'
              if admin is not None else
              'The tasks here are the Campaign record&rsquo;s native tasks. <b>No admin initiative yet</b> &mdash; the import brings Personal admin.')
    return (
        '<section class="col" aria-label="Tasks"><div class="colk"><h3>Tasks</h3><span class="c" id="tkCount">%d open &middot; %d parked &middot; %d done</span><span class="rule"></span></div>'
        '<div class="tkbox"><div class="filters" id="filters">%s<div class="fnote" id="fnote">%s</div></div>'
        '<div class="scroll" style="flex:1"><div class="tklist" id="tkList">%s</div></div>%s'
        '<div class="tklegend"><b>&#10003; done</b> waits on your word on the close law &middot; <b>&#9873; needs you</b> &middot; <b>&#9679; in progress</b> &middot; <b>&middot; no date</b> &middot; '
        '<b>&#10005;</b> takes a task off the Desk (the record keeps it; Undo puts it back). Click the text to rename it, the date to change it, the chip to move it to another initiative. '
        '%s</div></div></section>'
    ) % (len(open_), len(by["parked"]), len(by["done"]), fbtns, "Every task, grouped by when it is wanted. Parked and Done fall to the bottom.", groups, addline, source)


# ── CENTRE: the steward ────────────────────────────────────────────────────────────────────────

def brief_bullets(ctx):
    today = ctx["today"]
    monday = today - timedelta(days=today.weekday())
    week_end = monday + timedelta(days=6)
    tasks = desk_tasks(ctx["initiatives"])
    open_ = rank(_open(tasks))
    needs = [t for t in open_ if t["needs_you"]]
    admin = [t for t in open_ if t["admin"]]
    dated = [t for t in open_ if t["date"] and _hr._iso(t["date"])]
    out = []
    if needs:
        out.append("&#9873; <b>%s</b> waits on your word%s." % (esc(needs[0]["text"]), (" &mdash; and %d more" % (len(needs) - 1)) if len(needs) > 1 else ""))
    elif dated:
        out.append("Nearest on the Desk: <b>%s</b>, %s." % (esc(dated[0]["text"]), esc(_short(dated[0]["date"]))))
    else:
        out.append("Nothing on the Desk waits on your word and nothing is dated.")
    out.append('<span class="n">%d</span> open on the Desk: <span class="n">%d</span> need your word, <span class="n">%d</span> are admin, <span class="n">%d</span> belong to other initiatives.' % (
        len(open_), len(needs), len(admin), len(open_) - len(admin)))
    wk = [t for t in dated if monday <= _hr._iso(t["date"]) <= week_end]
    near = next((t for t in dated if _hr._iso(t["date"]) > week_end), None)
    if wk:
        out.append("This week, %s: %s." % (esc(_hr.week_in_words(today).replace("this week ", "")), "; ".join("%s (%s)" % (esc(t["text"]), esc(_short(t["date"]))) for t in wk[:4])))
    else:
        out.append("This week, %s: <b>nothing on the Desk is dated inside it</b>.%s" % (
            esc(_hr.week_in_words(today).replace("this week ", "")), (" The nearest is %s, %s." % (esc(near["text"]), esc(_short(near["date"])))) if near else " Nothing carries a date at all."))
    ten = [t for t in dated if today <= _hr._iso(t["date"]) <= today + timedelta(days=10)]
    out.append(("Inside ten days: " + " &middot; ".join('%s <span class="n">%s</span>' % (esc(t["text"]), esc(_short(t["date"]))) for t in ten[:5]) + ".") if ten else "Nothing is dated inside the next ten days.")
    out.append("Calendar and Email are drawn empty because <b>no account is connected</b>, not because there is nothing in them. The marks on the calendar are the Campaign&rsquo;s own dated tasks.")
    return out


def _steward_col(ctx):
    st = ctx["steward"]
    bullets = "".join('<li%s>%s</li>' % (' class="lead"' if k == 0 else "", b) for k, b in enumerate(brief_bullets(ctx)))
    turns = ctx.get("turns") or []
    ex = "".join('<li class="exrow"><div class="exw %s">%s<span class="t">%s</span></div><div class="ext">%s</div></li>' % (
        "you" if t["you"] else "st", "You" if t["you"] else esc(st["label"]), esc(t["at"]), esc(t["text"][:600])) for t in turns[-6:])
    return (
        '<section class="col" aria-label="The steward"><section class="brief" id="brief"><div class="kicker">The brief <span class="k-when">%s</span></div><ul class="blist" id="briefList">%s</ul></section>'
        '<section class="composer"><label class="sr" for="say">Tell the steward what to do</label>'
        '<textarea id="say" rows="2" placeholder="Tell %s what to do &mdash; it runs the Desk from the Campaign record"></textarea>'
        '<div class="comp-row"><span class="hint">Ctrl+Enter sends &middot; the steward answers here and acts on the record; the list shows what changed on the next look</span><button class="send" id="sendBtn">Send</button></div>'
        '<div class="receipt none" id="receipt"><span class="r-mark">&middot;</span><span id="receiptText">No change yet. Every change lands here as one line, with Undo.</span> <button class="mini" id="undoBtn" hidden>undo</button></div></section>'
        '<div class="exwrap"><div class="exhead"><h3>%s &mdash; the last exchanges</h3><span class="note" id="exNote">%s</span></div>'
        '<div class="scroll" style="flex:1"><ul class="ex" id="exList">%s<li class="exfade">%s</li></ul></div></div></section>'
    ) % (esc(ctx["brief_when"]), bullets, esc(st["label"]),
         esc(st["label"]), ("%d shown" % min(6, len(turns))) if turns else "no transcript kept",
         ex, "Only the last few exchanges are kept here. What the steward actually did is in the list." if turns else "Nothing said here yet. The cockpit&rsquo;s conversation is the same one.")


# ── RIGHT: Calendar, Email, the status, capacity ───────────────────────────────────────────────

def _calendar(ctx, tasks):
    today = ctx["today"]
    monday = today - timedelta(days=today.weekday())
    dated = [t for t in _open(tasks) if t["date"] and _hr._iso(t["date"])]
    on = {}
    for t in dated:
        on.setdefault(t["date"], []).append(t)
    days = []
    for k in range(7):
        d = monday + timedelta(days=k)
        marks = "".join('<div class="tmark">%s</div>' % esc(t["text"]) for t in on.get(d.isoformat(), []))
        days.append('<div class="d%s"><span class="dn">%s%s <b>%s</b></span><div class="none">no events</div>%s</div>' % (
            " today" if d == today else "", d.strftime("%a"), " &middot; today" if d == today else "", esc(_short(d.isoformat())), marks))
    in_week = sum(len(on.get((monday + timedelta(days=k)).isoformat(), [])) for k in range(7))
    near = next((t for t in rank(dated) if _hr._iso(t["date"]) > monday + timedelta(days=6)), None)
    zero_week = ('<p class="zero"><b>No account is connected &mdash; set up is not yet available.</b> The week is drawn empty because nothing can be read, not because the week is free. %s</p>' % (
        ("The %d mark%s shown %s the Campaign&rsquo;s own dated task%s, not an event." % (in_week, "" if in_week == 1 else "s", "is" if in_week == 1 else "are", "" if in_week == 1 else "s")) if in_week
        else ("No task on the Desk is dated inside it either" + ((" &mdash; the nearest is %s, %s." % (esc(near["text"]), esc(_short(near["date"])))) if near else "."))))
    months = []
    for m in range(2):
        y, mo = today.year + ((today.month - 1 + m) // 12), (today.month - 1 + m) % 12 + 1
        first_wd, ndays = _cal.monthrange(y, mo)
        cells = "".join('<div class="hd">%s</div>' % d for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")) + '<div class="c pad"></div>' * first_wd
        total = 0
        for i in range(1, ndays + 1):
            iso = "%04d-%02d-%02d" % (y, mo, i)
            marks = on.get(iso, [])
            total += len(marks)
            cells += '<div class="c%s"><span class="num">%d</span>%s</div>' % (" today" if iso == today.isoformat() else "", i, "".join('<span class="dot">&#9679; %s</span>' % esc(t["text"]) for t in marks))
        lab = "%s %d" % (_cal.month_name[mo], y)
        months.append('<div class="calview month" data-month="%d" hidden><div class="mogrid">%s</div><p class="zero"><b>No account is connected &mdash; set up is not yet available.</b> No event is drawn in %s because none can be read. %s</p></div>' % (
            m, cells, esc(lab), ("The %d mark%s shown %s dated task%s of the Campaign." % (total, "" if total == 1 else "s", "is a" if total == 1 else "are", "" if total == 1 else "s")) if total else "No task on the Desk is dated in this month either."))
        months[-1] = months[-1].replace('data-month="%d"' % m, 'data-month="%d" data-label="%s"' % (m, esc(lab)))
    week_lab = "%s&ndash;%s" % (esc(_short(monday.isoformat())), esc(_short((monday + timedelta(days=6)).isoformat())))
    return (
        '<section class="tile" id="calTile"><button class="tile-h" id="calHead"><span class="k">Calendar</span><span class="state">&middot; not connected &middot; 0 events &middot; <span id="calCount">%d dated task%s</span></span><span class="sp"></span><span class="tog" id="calTog">Open</span></button>'
        '<div class="tile-b" id="calBody" hidden><div class="caltabs"><button class="caltab on" data-cal="week">Week</button><button class="caltab" data-cal="month">Month</button>'
        '<span class="calnav"><button data-mo="-1" hidden>&#8249;</button><span class="mlab" id="calLab">%s</span><button data-mo="1" hidden>&#8250;</button></span></div>'
        '<div class="calview week" data-week="1"><div class="wkgrid">%s</div>%s</div>%s</div></section>'
    ) % (len(dated), "" if len(dated) == 1 else "s", week_lab, "".join(days), zero_week, "".join(months))


def _mail():
    return ('<section class="tile" id="mailTile"><button class="tile-h" id="mailHead"><span class="k">Email</span><span class="state">&middot; not connected &middot; 0 messages</span><span class="sp"></span><span class="tog" id="mailTog">Open</span></button>'
            '<div class="tile-b" id="mailBody" hidden><div class="inbox">No messages &mdash; nothing is being read.</div>'
            '<p class="zero"><b>No account is connected &mdash; set up is not yet available.</b> When an inbox is connected, what needs you would arrive as a task in the list on the left, not as a pile here.</p>'
            '<div class="mailbar"><button class="mailbtn" data-mail="compose">Compose</button><button class="mailbtn" data-mail="connect">Connect an account</button></div></div></section>')


def _status(ctx):
    s = ctx.get("status") or {}
    facts = s.get("facts") or []
    rows = "".join('<div class="srow"><dt>%s</dt><dd>%s</dd></div>' % (esc(l), esc(v) if v else "<i>nothing recorded</i>") for l, v in facts)
    stamp = esc(s.get("at") or ("read failed" if s.get("failed") else "no report yet"))
    lead = esc(s.get("lead") or "No status recorded on the Campaign yet &mdash; the steward writes one on its first turn.")
    kind = " &middot; live" if s.get("live") else (" &middot; the record, not a live run" if s.get("stale") else "")
    return ('<section class="status"><div class="st-h">Status &mdash; the Campaign&rsquo;s latest report<span class="stamp">%s%s</span></div><p class="st-lead" id="stLead">%s</p><dl id="stRows">%s</dl>'
            '<p class="st-fine">%s</p></section>' % (stamp, kind, lead, rows or '<div class="srow"><dt>Status</dt><dd>nothing recorded</dd></div>',
                                                    "The rows are the cockpit&rsquo;s own status facts; a row with nothing in it says so." if facts else (
                                                        "The status could not be read this time; the Desk still renders from the record." if s.get("failed") else
                                                        "The Desk runs no build: its status is the Campaign record&rsquo;s, once the steward has written one.")))


def _capacity(ctx):
    rows = "".join(capacity_row_html(c) for c in ctx.get("capacity") or [])
    return '<section class="cap"><h3>Capacity &middot; window and week</h3><div id="capList">%s</div><p class="cap-foot">A percentage is the account&rsquo;s own window as the newest Claude run reported it; a token count is what Anchor launched.</p></section>' % (
        rows or '<div class="cr"><div class="cr-top"><span class="cr-n">no subscription read</span></div></div>')


def _right_col(ctx, tasks):
    return ('<aside class="col" aria-label="Calendar, Email and the status"><div class="colk"><h3>Calendar &middot; Email &middot; Status</h3><span class="c">two tiles, closed &mdash; the report stays open</span><span class="rule"></span></div>'
            '<div class="scroll" style="flex:1">%s%s%s%s</div></aside>' % (_calendar(ctx, tasks), _mail(), _status(ctx), _capacity(ctx)))


# ── the page ───────────────────────────────────────────────────────────────────────────────────

def render_desk_html(ctx) -> str:
    st = ctx["steward"]
    tasks = desk_tasks(ctx["initiatives"])
    hdr = (
        '<div class="hdr"><a class="back" href="/high-seat">&larr; %s</a><h2>Desk</h2>'
        '<button class="tool doctor" data-tool="doctor">&#10010; Anchor Doctor</button><button class="tool" data-tool="zombie">%sZombie Hunter</button><button class="tool" data-tool="foundry">%sSkill Foundry</button>'
        '<a class="tool" href="/project/%s" title="the Campaign, this record in tiers">the Campaign</a><a class="tool" href="/project/%s?doc=1" title="the ordinary cockpit of this record">the cockpit</a><div class="date">%s</div></div>'
    ) % (esc(st["high_seat_name"]),
         _brand_img(ctx["build"], "zombie-hunter-radar.jpg"), _brand_img(ctx["build"], "skill-foundry-icon.jpg"), esc(ctx["pid"]), esc(ctx["pid"]), esc(ctx["today_str"]))
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>The Desk</title><link rel="icon" href="/vendor/brand/%s?v=%s">'
        '<link rel="stylesheet" href="/static/desk-page.css?v=%s">'
        '<script>window.ANCHOR_BOOT = {build_id: "%s", campaign_pid: "%s", today: "%s"};</script></head>'
        '<body><div class="page">%s%s<div class="prefs">%s</div><div class="cockpit">%s%s%s</div>'
        '<div class="foot">%s<span>A <b class="gwl-accent">Ghost World Labs</b> tool &middot; Powered by NextGen Nuclear &middot; AI Cockpit &middot; J.C. Liechty</span>'
        '<span>&mdash; every task, date and count on this page is read from the Campaign record; Calendar and Email are not connected, and say so.</span></div></div>'
        '<script src="/static/desk-page.js?v=%s"></script></body></html>'
    ) % (esc((ctx.get("steward") or {}).get("seal") or "gwl-m-icon.svg"), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["build"]), esc(ctx["pid"]), ctx["today"].isoformat(), _masthead(ctx), hdr, ctx.get("prefs_html") or "",
         _tasks_col(ctx), _steward_col(ctx), _right_col(ctx, tasks), _brand_img(ctx["build"], "gwl-m-icon.svg"), esc(ctx["build"]))
