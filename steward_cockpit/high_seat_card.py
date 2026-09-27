"""high_seat_card — a project card's parts on the High Seat, from the cockpit's own readers.

W2 of the High Seat plan (2026-09-26; trimmed by its Rabbit read). A card on the home opens in place
to what the cockpit shows for that project's root effort — Status (the same branch the cockpit's
status verb takes: a live engine's state into compose_status, else the persisted record), Next steps
(the live decision — the persisted decision record's question with its recommendation, else the
engine's open question, else the strip's wait — what it depends on as the record names it, the acts,
and the next three open steps sliced the way the tile slices them), Deliverables (the register, each
openable row linked through the deliverable-file route), Plan (the steps with the cockpit's mark
order and its Not done set) — composed here from the same Python readers the cockpit uses, so the
card and the cockpit cannot disagree. No model call, no bridge spawn; every open fetches afresh; an
effort without a steward record yields an honest line, never a blank.
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


def _live_engine(cdir):
    """The engine the cockpit would use — the same map the status verb consults; None when none is awake."""
    try:
        from . import steward_routes as routes
        return routes.ENGINES.get(cdir)
    except Exception:
        return None


def _decision(cdir):
    """The effort's live decision, as the cockpit's panel reads it: the persisted decision record (question,
    recommendation, depends_on), else the engine's open question; ``found`` says whether a state entry existed."""
    try:
        from .steward_engine import _read_state_entry
        from .question_context import normalize_question_context
        entry = _read_state_entry(str(cdir))
    except Exception:
        entry = {}
    found = bool(entry)
    rec = normalize_question_context(entry.get("question_context")) if entry.get("question_context") else None
    if rec:
        return {"found": True, "question": rec.get("question") or "", "recommendation": rec.get("recommendation") or "",
                "depends_on": list(rec.get("depends_on") or [])}
    q = str(entry.get("open_question") or "").strip() if entry else ""
    return {"found": found, "question": q, "recommendation": "", "depends_on": []}


def _step_label(s):
    return (s.get("navigation") or {}).get("label") or s.get("name") or s.get("id") or ""


def _waits(s):
    """The cockpit's stepWaitsOnJohn, from structured facts only."""
    r = s.get("refinement") if isinstance(s.get("refinement"), dict) else None
    if r and r.get("phase") == "awaiting_review":
        return "awaiting your review"
    if r and r.get("phase") == "blocked":
        return "blocked"
    if s.get("status") == "blocked":
        return "blocked"
    if s.get("status") == "waiting":
        w = s.get("waiting_on")
        return (" ".join(str(w).split())[:90]) if w else "waiting"
    return ""


def _done(s):
    r = s.get("refinement") if isinstance(s.get("refinement"), dict) else None
    if r:
        return r.get("phase") == "done"
    return s.get("status") == "done"


def status_html(cdir, pid):
    eng = _live_engine(cdir)
    if eng is not None:
        data = campaign.compose_status(cdir, eng.state())
    else:
        data = campaign.read_last_status(cdir) or campaign.compose_status(cdir, None)
    facts = ((data.get("compact") or {}).get("facts") if isinstance(data.get("compact"), dict) else None) or []
    rows = "".join('<tr><th>%s</th><td>%s</td></tr>' % (esc(f.get("label")), esc(f.get("value")))
                   for f in facts if isinstance(f, dict) and f.get("label"))
    lead = data.get("lead_line") or campaign.lead_line(data.get("plan"))
    at = str(data.get("at") or "")
    stale = " &middot; the record, not a live run" if data.get("stale") else (" &middot; live" if eng is not None else "")
    return ('<div class="cp-status"><div class="cp-lead">%s</div><div class="cp-when">last update %s%s</div>'
            '<table class="cp-facts">%s</table>'
            '<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></div>'
            % (esc(lead), esc(at[-16:]) if at else "unknown", stale, rows or '<tr><td>No status recorded yet.</td></tr>', esc(pid)))


def _item_link(it, pid):
    """The cockpit's own link for a register row: a route stays a route; an openable path goes through the
    deliverable-file route; anything else is text."""
    what = esc(it.get("what") or it.get("path") or "")
    route = str(it.get("route") or "")
    path = str(it.get("path") or "")
    if route.startswith("/"):
        return '<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(route), what)
    if path and it.get("openable", True) and not path.startswith(("http://", "https://")):
        return '<a href="/api/steward/deliverable-file?pid=%s&amp;dir=&amp;path=%s" target="_blank" rel="noopener">%s</a>' % (esc(pid), esc(path), what)
    return what


def _open_steps(m):
    return [s for s in m.get("steps") or [] if not _done(s) and s.get("status") not in ("cancelled", "dropped")]


def next_html(cdir, pid):
    m = campaign.read_map(cdir)
    d = _decision(cdir)
    question, rec = d["question"], d["recommendation"]
    if not question:
        question = str((m.get("heartbeat") or {}).get("human_wait") or m.get("human_wait_face") or "").strip()
    try:
        items = (campaign.read_deliverables(cdir) or {}).get("items") or []
    except Exception:
        items = []
    current = campaign.current_review_items(m, items)
    acts = campaign.review_acts(m, current)
    by_what = {str(it.get("what") or "").strip().lower(): it for it in items}
    # the cockpit's Next-in-the-plan: from the first active not-done step, three of them
    open_steps = _open_steps(m)
    start = next((i for i, s in enumerate(open_steps) if s.get("status") == "active"), 0)
    plan = open_steps[start:start + 3]
    out = ['<div class="cp-next">']
    if question:
        out.append('<div class="cp-q"><span class="k">Decide</span>%s%s</div>' % (
            esc(" ".join(str(question).split())[:400]),
            ('<div class="cp-rec"><span class="k">Recommended</span>%s</div>' % esc(" ".join(str(rec).split())[:240])) if rec else ""))
        if d["depends_on"]:
            out.append('<div class="cp-dep"><span class="k">Depends on</span>%s</div>' % " &middot; ".join(
                _item_link(by_what.get(n.lower()) or {"what": n, "route": "", "path": ""}, pid) for n in d["depends_on"]))
    elif not acts:
        out.append('<div class="cp-quiet">Nothing waits on your word here%s.</div>' % ("" if d["found"] else " &mdash; no decision record for this effort"))
    if acts:
        out.append('<div class="cp-acts"><span class="k">Acts</span>%s</div>' % "".join(
            '<div class="cp-act"><b>%s</b> %s</div>' % (esc(a.get("act")), _item_link(a.get("item"), pid) if a.get("item") else esc(a.get("label")))
            for a in acts[:6]))
    if plan:
        out.append('<div class="cp-plan"><span class="k">Next in the plan</span>%s</div>' % "".join(
            '<div class="cp-step">%s%s</div>' % (esc(_step_label(s)), (' <span class="dim">&middot; due %s</span>' % esc(s.get("due"))) if s.get("due") else "")
            for s in plan))
    out.append('<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></div>' % esc(pid))
    return "".join(out)


def deliverables_html(cdir, pid):
    try:
        items = (campaign.read_deliverables(cdir) or {}).get("items") or []
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
    steps = [s for s in m.get("steps") or [] if s.get("status") not in ("cancelled", "dropped")]
    now_id = m.get("now_step_id")

    def mark(s):   # the cockpit's order: done, then waiting on you, then the current step
        if _done(s):
            return "&#10003;", "s-done"
        if _waits(s):
            return "&#9873;", "s-waiting"
        if s.get("id") == now_id:
            return "&#9679;", "now"
        return "&middot;", "s-" + esc(s.get("status") or "planned")
    rows = []
    for s in steps[:40]:
        g, cls = mark(s)
        rows.append('<div class="cp-step %s"><span class="mk">%s</span>%s%s</div>' % (
            cls, g, esc(_step_label(s)), (' <span class="dim">&middot; due %s</span>' % esc(s.get("due"))) if s.get("due") else ""))
    more = ('<div class="dim">&hellip; %d more in the cockpit</div>' % (len(steps) - 40)) if len(steps) > 40 else ""

    # Not done, as the cockpit holds it: not done and not held out (parked or supporting, unless it is the current step)
    def supporting(s):
        return ((s.get("navigation") or {}).get("role") == "support")

    def held_out(s):
        return (not _done(s)) and s.get("id") != now_id and (s.get("status") == "parked" or supporting(s))
    open_rows = [(i, s) for i, s in enumerate(steps) if not _done(s) and not held_out(s)]

    def rank(pair):
        i, s = pair
        return (0 if _waits(s) else 1 if s.get("id") == now_id else 2 if s.get("status") == "active" else 3, i)
    open_rows.sort(key=rank)
    notdone = "".join('<div class="cp-step"><span class="mk">%s</span>%s%s</div>' % (
        "&#9873;" if _waits(s) else ("&#9679;" if s.get("id") == now_id else "&middot;"), esc(_step_label(s)),
        (' <span class="dim">&middot; %s</span>' % esc(_waits(s))) if _waits(s) else "") for i, s in open_rows[:12])
    done_n = sum(1 for s in steps if _done(s))
    return ('<div class="cp-planpane"><div class="cp-when">%d of %d steps done</div>%s%s'
            '<div class="cp-notdone"><span class="k">Not done &middot; %d</span>%s</div>'
            '<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open the plan in the cockpit</a></div></div>'
            % (done_n, len(steps), "".join(rows), more, len(open_rows), notdone, esc(pid)))


def card_part(pid, part, folder, name=""):
    """One card part as HTML — ``{"ok", "pid", "part", "html"}``; unknown parts and missing records answer honestly."""
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
