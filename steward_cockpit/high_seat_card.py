"""high_seat_card — a project card's parts on the High Seat, from the cockpit's own readers.

W2 of the High Seat plan (2026-09-26). A card on the home opens in place to what the cockpit
shows for that project's root effort — Status (the persisted or freshly composed ten-row
status with its lead line), Next steps (the open decision, what it depends on, the acts and
the next steps of the plan), Deliverables (the register), Plan (the steps with their marks and
the Not done list) — composed here from the same Python readers the cockpit uses
(``steward_campaign``), so the card and the cockpit can never disagree. No model call, no
bridge spawn; an effort without a steward record yields an honest line, never a blank.
"""
from __future__ import annotations

import html
from pathlib import Path

from . import steward_campaign as campaign

PARTS = ("status", "next", "deliverables", "plan")


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _effort_dir(folder):
    """The project's root effort (the folder itself) when it carries a Face; else None."""
    root = Path(str(folder or ""))
    if root.is_dir() and (root / "ECGBERHT.md").is_file():
        return str(root)
    return None


def _no_record(pid, name):
    return ('<div class="cp-quiet">No steward record for %s yet &mdash; open the cockpit and stand it up. '
            '<a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div>' % (esc(name), esc(pid)))


def status_html(cdir, pid):
    last = campaign.read_last_status(cdir)
    data = last if last is not None else campaign.compose_status(cdir, None)
    facts = ((data.get("compact") or {}).get("facts") if isinstance(data.get("compact"), dict) else None) or []
    rows = "".join('<tr><th>%s</th><td>%s</td></tr>' % (esc(f.get("label")), esc(f.get("value")))
                   for f in facts if isinstance(f, dict) and f.get("label"))
    lead = data.get("lead_line") or campaign.lead_line(data.get("plan"))
    at = str(data.get("at") or "")
    stale = " &middot; the record, not a live run" if data.get("stale") else ""
    return ('<div class="cp-status"><div class="cp-lead">%s</div><div class="cp-when">last update %s%s</div>'
            '<table class="cp-facts">%s</table>'
            '<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></div>'
            % (esc(lead), esc(at[-16:]) if at else "unknown", stale, rows or '<tr><td>No status recorded yet.</td></tr>', esc(pid)))


def _item_link(it, pid):
    route = str(it.get("route") or "")
    what = esc(it.get("what") or it.get("path") or "")
    if route.startswith("/"):
        return '<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(route), what)
    return what


def next_html(cdir, pid):
    m = campaign.read_map(cdir)
    last = campaign.read_last_status(cdir) or {}
    compact = last.get("compact") if isinstance(last.get("compact"), dict) else {}
    question = (compact.get("question") or (last.get("plan") or {}).get("waiting_on_you")
                or (m.get("heartbeat") or {}).get("human_wait") or m.get("human_wait_face") or "")
    if isinstance(question, dict):
        question = question.get("question") or question.get("text") or ""
    try:
        reg = campaign.read_deliverables(cdir)
        items = reg.get("items") or []
    except Exception:
        items = []
    current = campaign.current_review_items(m, items)
    acts = campaign.review_acts(m, current)
    focused, _w = campaign._focused_step(m)
    steps = [s for s in m.get("steps") or [] if s.get("status") not in ("done", "parked", "cancelled", "dropped")]
    start = next((i for i, s in enumerate(steps) if focused and s.get("id") == focused.get("id")), 0)
    plan = steps[start:start + 3]
    out = ['<div class="cp-next">']
    if question:
        out.append('<div class="cp-q"><span class="k">Decide</span>%s</div>' % esc(" ".join(str(question).split())[:400]))
        if current:
            out.append('<div class="cp-dep"><span class="k">Depends on</span>%s</div>' % " &middot; ".join(_item_link(it, pid) for it in current[:6]))
    else:
        out.append('<div class="cp-quiet">Nothing waits on your word here.</div>')
    if acts:
        out.append('<div class="cp-acts"><span class="k">Acts</span>%s</div>' % "".join(
            '<div class="cp-act"><b>%s</b> %s</div>' % (esc(a.get("act")), _item_link(a.get("item") or {"what": a.get("label"), "route": ""}, pid) if a.get("item") else esc(a.get("label")))
            for a in acts[:6]))
    if plan:
        out.append('<div class="cp-plan"><span class="k">Next in the plan</span>%s</div>' % "".join(
            '<div class="cp-step">%s%s</div>' % (esc((s.get("navigation") or {}).get("label") or s.get("name")), (' <span class="dim">&middot; due %s</span>' % esc(s.get("due"))) if s.get("due") else "")
            for s in plan))
    out.append('<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></div>' % esc(pid))
    return "".join(out)


def deliverables_html(cdir, pid):
    try:
        reg = campaign.read_deliverables(cdir)
        items = reg.get("items") or []
    except Exception:
        items = []
    if not items:
        return '<div class="cp-quiet">No deliverables registered yet.</div>'
    rows = "".join('<div class="cp-deliv%s">%s<span class="dim">%s%s</span></div>' % (
        " current" if it.get("is_current") else "", _item_link(it, pid),
        (" &middot; " + esc(it.get("date"))) if it.get("date") else "",
        " &middot; awaiting your review" if it.get("is_current") else "") for it in items[:20])
    more = ('<div class="dim">&hellip; %d more in the cockpit</div>' % (len(items) - 20)) if len(items) > 20 else ""
    return '<div class="cp-delivs">%s%s<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open the register in the cockpit</a></div></div>' % (rows, more, esc(pid))


def plan_html(cdir, pid):
    m = campaign.read_map(cdir)
    steps = m.get("steps") or []
    focused, _w = campaign._focused_step(m)
    fid = (focused or {}).get("id")
    marks = {"done": "&#10003;", "waiting": "&#9873;"}

    def mark(s):
        if s.get("id") == fid:
            return "&#9679;"
        return marks.get(s.get("status"), "&middot;")
    shown = [s for s in steps if s.get("status") not in ("cancelled", "dropped")]
    rows = "".join('<div class="cp-step s-%s%s"><span class="mk">%s</span>%s%s</div>' % (
        esc(s.get("status")), " now" if s.get("id") == fid else "", mark(s),
        esc((s.get("navigation") or {}).get("label") or s.get("name")),
        (' <span class="dim">&middot; due %s</span>' % esc(s.get("due"))) if s.get("due") else "") for s in shown[:40])
    more = ('<div class="dim">&hellip; %d more in the cockpit</div>' % (len(shown) - 40)) if len(shown) > 40 else ""
    open_steps = [s for s in shown if s.get("status") not in ("done", "parked")]
    waits = [s for s in open_steps if s.get("status") == "waiting"]
    notdone = "".join('<div class="cp-step"><span class="mk">%s</span>%s%s</div>' % (
        "&#9873;" if s in waits else "&middot;", esc((s.get("navigation") or {}).get("label") or s.get("name")),
        (' <span class="dim">&middot; waiting on %s</span>' % esc(s.get("waiting_on"))) if s.get("waiting_on") else "")
        for s in (waits + [s for s in open_steps if s not in waits])[:12])
    return ('<div class="cp-planpane"><div class="cp-when">%d of %d steps done</div>%s%s'
            '<div class="cp-notdone"><span class="k">Not done &middot; %d</span>%s</div>'
            '<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open the plan in the cockpit</a></div></div>'
            % (m.get("steps_done", 0), m.get("steps_total", 0), rows, more, len(open_steps), notdone, esc(pid)))


def card_part(pid, part, folder, name=""):
    """One card part as HTML — ``{"ok", "pid", "part", "html"}``; unknown parts and missing
    records answer honestly."""
    part = str(part or "").strip().lower()
    if part not in PARTS:
        return {"ok": False, "pid": pid, "part": part, "error": "unknown part", "html": ""}
    cdir = _effort_dir(folder)
    if cdir is None:
        return {"ok": True, "pid": pid, "part": part, "html": _no_record(pid, name or pid[:8])}
    try:
        fn = {"status": status_html, "next": next_html, "deliverables": deliverables_html, "plan": plan_html}[part]
        return {"ok": True, "pid": pid, "part": part, "html": fn(cdir, pid)}
    except Exception as e:  # never a blank on the page
        return {"ok": True, "pid": pid, "part": part,
                "html": '<div class="cp-quiet">This part could not be read: %s</div>' % esc("%s: %s" % (type(e).__name__, e))}
