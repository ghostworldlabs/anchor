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


def _effort_dir(folder, rel=""):
    """The effort the card names, resolved ONLY through the cockpit's own discovery (``discover_efforts``: the project
    root when it carries a Face, plus one level of subfolders with their own Face, none retired in place) — the same
    guard the cockpit's routes use. Anything discovery does not list (a path, a dot-name, a foreign drive such as
    ``D:foo``, a plain subfolder) is None, and the card says "No steward record"."""
    folder = str(folder or "")
    rel = str(rel or "").strip()
    if not folder:
        return None
    try:
        efforts = campaign.discover_efforts(folder) or []
    except Exception:
        return None
    for e in efforts:
        if str((e or {}).get("rel") or "") == rel:
            return str(Path(folder) / rel) if rel else str(Path(folder))
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
    # W1 (2026-09-28): the ONE next-in-the-plan rule, shared with the cockpit and the status composer — the declared
    # focus, then what follows it; never a guess from the first active step
    plan, plan_why = campaign.next_in_plan(m, 3)
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
    elif plan_why:
        out.append('<div class="cp-plan"><span class="k">Next in the plan</span><div class="cp-step dim">%s</div></div>' % esc(plan_why))
    out.append('<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open cockpit</a></div></div>' % esc(pid))
    return "".join(out)


def _node_html(node, pid, depth=0, current_ids=()):
    """One work-stream node as the cockpit's Deliverables panel groups it: its mark, its label, its items (each openable
    through the deliverable-file route), then its children; a node whose work is all done folds closed."""
    mark = node.get("mark") or {}
    items = [it for it in node.get("items") or [] if it]
    rows = "".join('<div class="cp-deliv%s">%s<span class="dim">%s%s</span></div>' % (
        " current" if id(it) in current_ids or it.get("is_current") else "", _item_link(it, pid),
        (" &middot; " + esc(campaign._item_summary(it))) if campaign._item_summary(it) else "",
        " &middot; awaiting your review" if (id(it) in current_ids or it.get("is_current")) else "") for it in items)
    more = ""
    kids = "".join(_node_html(c, pid, depth + 1, current_ids) for c in node.get("children") or [])
    done = mark.get("cls") == "done"
    return ('<details class="cp-node d%d %s"%s><summary><span class="mk %s">%s</span>%s<span class="dim"> &middot; %d</span></summary>%s%s%s</details>' % (
        depth, esc(mark.get("cls") or "todo"), "" if done else " open", esc(mark.get("cls") or "todo"), esc(mark.get("glyph") or "&#9655;"),
        esc(node.get("label") or node.get("id") or "work"), len(items), rows or ('<div class="dim">nothing registered here yet</div>' if not kids else ""), more, kids))


def deliverables_html(cdir, pid):
    """The cockpit's Deliverables organisation (John, 2026-09-11): current work and review first, a folded Approved list
    below it, then the whole work hierarchy by domain — the same view the cockpit's panel paints
    (steward_campaign.effort_deliverable_view)."""
    try:
        view = campaign.effort_deliverable_view(cdir)
    except Exception as e:
        return '<div class="cp-quiet">The register could not be read: %s</div>' % esc("%s: %s" % (type(e).__name__, e))
    items = view.get("items") or []
    if not items and not view.get("approved"):
        return '<div class="cp-quiet">No deliverables registered yet.</div>'
    current = view.get("current") or []
    cur_ids = {id(it) for it in current}
    out = ['<div class="cp-delivs">']
    out.append('<div class="cp-sec"><span class="k">Current work and review &middot; %d</span>%s</div>' % (
        len(current), "".join('<div class="cp-deliv current">%s<span class="dim">%s &middot; awaiting your review</span></div>' % (
            _item_link(it, pid), (" &middot; " + esc(campaign._item_summary(it))) if campaign._item_summary(it) else "") for it in current)
        or '<div class="dim">Nothing is pinned for your review.</div>'))
    approved = view.get("approved") or []
    out.append('<details class="cp-fold"><summary><span class="k">Approved &middot; %d</span></summary>%s</details>' % (
        len(approved), "".join('<div class="cp-deliv">%s<span class="dim">%s</span></div>' % (
            _item_link(it, pid), (" &middot; " + esc(it.get("date"))) if it.get("date") else "") for it in approved)
        or '<div class="dim">Nothing accepted yet.</div>'))
    streams = view.get("streams") or []
    out.append('<div class="cp-sec"><span class="k">All the work, by domain</span>%s</div>' % (
        "".join(_node_html(n, pid, 0, cur_ids) for n in streams) or '<div class="dim">The plan has no domains yet.</div>'))
    out.append('<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open the register in the cockpit</a></div></div>' % esc(pid))
    return "".join(out)


def _why(s):
    """The words beside a flag: the cockpit's wait phrase, else the step's own waiting_on (an active step can carry one)."""
    return _waits(s) or " ".join(str(s.get("waiting_on") or "").split())[:90]


def _step_row(s, now_id):
    """A step as the cockpit marks it: ✓ done, ⚑ needs attention (the cockpit's own rule — a wait, a block, a review
    handoff, even on an active step), ● the current step, ▷ otherwise; the wait's words beside the flag."""
    if _done(s):
        g, cls = "&#10003;", "s-done"
    elif campaign._step_needs_attention(s):
        g, cls = "&#9873;", "s-waiting"
    elif s.get("id") == now_id:
        g, cls = "&#9679;", "now"
    else:
        g, cls = "&#9655;", "s-" + esc(s.get("status") or "planned")
    return '<div class="cp-step %s"><span class="mk">%s</span>%s%s%s</div>' % (
        cls, g, esc(_step_label(s)), (' <span class="dim">&middot; due %s</span>' % esc(s.get("due"))) if s.get("due") else "",
        (' <span class="dim">&middot; %s</span>' % esc(_why(s))) if _why(s) else "")


def _plan_node_html(node, now_id, depth=0):
    mark = node.get("mark") or {}
    steps = [s for s in node.get("steps") or [] if s.get("status") not in ("cancelled", "dropped")]
    done_n = sum(1 for s in steps if _done(s))
    kids = "".join(_plan_node_html(c, now_id, depth + 1) for c in node.get("children") or [])
    done = mark.get("cls") == "done"
    return ('<details class="cp-node d%d %s"%s><summary><span class="mk %s">%s</span>%s<span class="dim"> &middot; %d of %d done</span></summary>%s%s</details>' % (
        depth, esc(mark.get("cls") or "todo"), "" if done else " open", esc(mark.get("cls") or "todo"), esc(mark.get("glyph") or "&#9655;"),
        esc(node.get("label") or node.get("id") or "work"), done_n, len(steps), "".join(_step_row(s, now_id) for s in steps), kids))


def plan_html(cdir, pid):
    """The cockpit's Plan organisation (John, 2026-09-11): the domain hierarchy, each domain with the cockpit's mark
    (✓ all done · ▷ unfinished · ⚑ something waits on you), its steps marked the same way, done domains folded; then
    the Not-done list as the cockpit holds it, what waits on you first."""
    m = campaign.read_map(cdir)
    steps = [s for s in m.get("steps") or [] if s.get("status") not in ("cancelled", "dropped")]
    now_id = m.get("now_step_id")
    try:
        items = (campaign.read_deliverables(cdir) or {}).get("items") or []
    except Exception:
        items = []
    try:
        roots = (campaign.work_stream_model(m, items) or {}).get("roots") or []
    except Exception:
        roots = []
    tree = "".join(_plan_node_html(n, now_id) for n in roots) or "".join(_step_row(s, now_id) for s in steps)

    # Not done, as the cockpit holds it: not done and not held out (parked or supporting, unless it is the current step)
    def supporting(s):
        return ((s.get("navigation") or {}).get("role") == "support")

    def held_out(s):
        return (not _done(s)) and s.get("id") != now_id and (s.get("status") == "parked" or supporting(s))
    open_rows = [(i, s) for i, s in enumerate(steps) if not _done(s) and not held_out(s)]

    def rank(pair):
        i, s = pair
        return (0 if campaign._step_needs_attention(s) else 1 if s.get("id") == now_id else 2 if s.get("status") == "active" else 3, i)
    open_rows.sort(key=rank)
    notdone = "".join('<div class="cp-step"><span class="mk">%s</span>%s%s</div>' % (
        "&#9873;" if campaign._step_needs_attention(s) else ("&#9679;" if s.get("id") == now_id else "&middot;"), esc(_step_label(s)),
        (' <span class="dim">&middot; %s</span>' % esc(_why(s))) if _why(s) else "") for i, s in open_rows)
    done_n = sum(1 for s in steps if _done(s))
    return ('<div class="cp-planpane"><div class="cp-when">%d of %d steps done &middot; &#10003; done &middot; &#9655; unfinished &middot; &#9873; waits on you &middot; &#9679; now</div>'
            '<div class="cp-sec"><span class="k">The plan, by domain</span>%s</div>'
            '<div class="cp-notdone"><span class="k">Not done &middot; %d</span>%s</div>'
            '<div class="cp-foot"><a href="/project/%s" target="_blank" rel="noopener">Open the plan in the cockpit</a></div></div>'
            % (done_n, len(steps), tree, len(open_rows), notdone, esc(pid)))


def card_part(pid, part, folder, name="", rel=""):
    """One card part as HTML — ``{"ok", "pid", "part", "html"}``; unknown parts and missing records answer honestly.
    ``rel`` names the effort one folder down when the card reads one (home_rows.current_effort)."""
    part = str(part or "").strip().lower()
    if part not in PARTS:
        return {"ok": False, "pid": pid, "part": part, "error": "unknown part", "html": ""}
    cdir = _effort_dir(folder, rel)
    if cdir is None:
        return {"ok": True, "pid": pid, "part": part, "html": _no_record(pid, name or pid[:8])}
    try:
        fn = {"status": status_html, "next": next_html, "deliverables": deliverables_html, "plan": plan_html}[part]
        return {"ok": True, "pid": pid, "part": part, "html": fn(cdir, pid)}
    except Exception as e:  # never a blank on the page
        return {"ok": True, "pid": pid, "part": part,
                "html": '<div class="cp-quiet">This part could not be read: %s</div>' % esc("%s: %s" % (type(e).__name__, e))}
