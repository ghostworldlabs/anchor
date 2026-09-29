"""campaign_acts — what John does on the Campaign page, written into the Campaign's own record through the
engine's writer (the CLI and its spine), each act a receipt with its inverse.

W3c of the High Seat plan (2026-09-26), trimmed by its Rabbit read. Acts: move_tier · rank (up/down within a
tier) · rename · date · park (with its trigger) · unpark · flag / unflag (a native part's "needs you") · add (a
task, or a project part by reference) · promote (a seed, by id → an initiative, with the tier and the area he
picked) · withdraw / restore (the inverse of add and promote: the record is append-only, so a step is never
deleted — its navigation is cleared, which takes it off the board while the ordinary cockpit still shows it;
restore puts the navigation back). A tick on a native part waits on John's word on the close law (PLAN §9.6)
and is refused here with that sentence. The Campaign never writes another record: a date or a flip on a
referenced part is refused by the engine and the refusal is the receipt.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .campaign_seeds import seed_by_id

ECG = Path(r"C:\dev\Ecgberht\bin\ecgberht.mjs")
SPINE = "file:///C:/dev/Ecgberht/engine/ledger-spine.mjs"
WHO = "john"


def _cli(project, *args):
    r = subprocess.run(["node", str(ECG), *args, "--project", str(project)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        return json.loads(r.stdout or "{}")
    except Exception:
        return {"ok": False, "error": "engine answered no json", "raw": (r.stdout or r.stderr)[:200]}


def _spine_set(project, step_id, fields):
    js = ("import { appendRoadmapEventThroughSpine } from '%s';"
          "const r = appendRoadmapEventThroughSpine(%s, {kind:'step_set', step_id:%s, fields:%s});"
          "console.log(JSON.stringify({ok:r.ok, error:r.error||null}));") % (
        SPINE, json.dumps(str(project).replace("\\", "/")), json.dumps(step_id), json.dumps(fields))
    r = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "error": (r.stderr or r.stdout)[:200] or "the spine answered nothing"}


def _projection(project):
    try:
        d = json.loads((Path(project) / "roadmap.json").read_text(encoding="utf-8"))
        return d.get("roadmap_projection") or []
    except Exception:
        return []


def _step(project, sid):
    return next((s for s in _projection(project) if s.get("id") == sid), None)


def _own_group(s):
    nav = s.get("navigation") if isinstance(s.get("navigation"), dict) else {}
    return next((g for g in nav.get("groups") or [] if isinstance(g, dict) and g.get("id") == s.get("id") and g.get("parent_id") is None), None)


def _initiatives(project):
    out = []
    for s in _projection(project):
        g = _own_group(s)
        if g is not None:
            out.append((s, g))
    return out


def _parts_of(project, sid):
    out = []
    for p in _projection(project):
        nav = p.get("navigation") if isinstance(p.get("navigation"), dict) else {}
        path = nav.get("path") or []
        if p.get("id") != sid and path and path[0] == sid:
            out.append(p)
    return out


def _slug(text, prefix=""):
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:48].strip("-") or "part"
    return (prefix[:12] + "-" + s) if prefix else s


def _ok(receipt, undo=None, **extra):
    return {"ok": True, "receipt": receipt, "undo": undo, **extra}


def _no(text, **extra):
    return {"ok": False, "receipt": text, **extra}


def _write_nav(project, s, order=None):
    """Write the heading step's navigation back whole, with only its own group's order changed."""
    nav = dict(s.get("navigation") or {})
    groups = [dict(g) for g in nav.get("groups") or []]
    for g in groups:
        if g.get("id") == s.get("id") and order is not None:
            g["order"] = int(order)
    nav["groups"] = groups
    nav.setdefault("path", [s.get("id")])
    return _spine_set(project, s["id"], {"navigation": nav})


def _foot(project, tier, except_id=None):
    return max([int(g.get("order") or 0) for x, g in _initiatives(project) if x.get("tier") == tier and x.get("id") != except_id] or [-1]) + 1


# ── the acts ───────────────────────────────────────────────────────────────────────────────────

def move_tier(project, step, tier, order=None):
    """Move an initiative to a tier: one step_set of its tier, then its place — the foot of that tier, or the
    order the undo carries (so a head of a tier comes back as its head, not at the bottom with a new number)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    try:
        tier = int(tier)
    except Exception:
        return _no("a tier is 1, 2 or 3")
    if tier not in (1, 2, 3):
        return _no("a tier is 1, 2 or 3")
    old = s.get("tier")
    old_order = int(_own_group(s).get("order") or 0)
    if old == tier:
        return _no("%s is already in tier %d" % (s.get("name"), tier))
    r = _cli(project, "roadmap-set", "--step", step, "--tier", str(tier))
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    place = int(order) if order is not None else _foot(project, tier, except_id=step)
    r2 = _write_nav(project, _step(project, step), order=place)
    if not r2.get("ok"):
        return _no("%s moved to tier %d, but its place there was refused: %s — it keeps its old order number" % (s.get("name"), tier, r2.get("error")))
    return _ok("%s moved to tier %d (from %s), %s" % (s.get("name"), tier, ("tier %d" % old) if old else "no tier",
                                                      ("at its foot" if order is None else "back in its place")),
               undo={"act": "move_tier", "step": step, "tier": old, "order": old_order} if old else None)


def rank(project, step, direction):
    """Move an initiative up or down within its tier. The tier is first renumbered to its sorted positions
    (a write only where an order differs — equal orders would otherwise make Up sort later), then the two
    neighbours swap; a refused second write puts the first back."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    same = sorted([(int(g.get("order") or 0), x) for x, g in _initiatives(project) if x.get("tier") == s.get("tier")], key=lambda t: (t[0], t[1].get("name") or ""))
    idx = next((k for k, (o, x) in enumerate(same) if x.get("id") == step), None)
    if idx is None:
        return _no("not in a tier")
    j = idx - 1 if direction == "up" else idx + 1
    if j < 0 or j >= len(same):
        return _no("%s is already at the %s of its tier — the Tier menu moves it between tiers" % (s.get("name"), "top" if direction == "up" else "foot"))
    for k, (o, x) in enumerate(same):
        if o != k:
            r0 = _write_nav(project, x, order=k)
            if not r0.get("ok"):
                return _no("the tier could not be renumbered: %s" % r0.get("error"))
    mover, other = same[idx][1], same[j][1]
    r1 = _write_nav(project, other, order=idx)
    if not r1.get("ok"):
        return _no("the engine refused: %s" % r1.get("error"))
    r2 = _write_nav(project, mover, order=j)
    if not r2.get("ok"):
        _write_nav(project, other, order=j)
        return _no("the engine refused: %s — nothing moved" % r2.get("error"))
    return _ok("%s moved %s within tier %s, past %s" % (s.get("name"), direction, s.get("tier"), other.get("name")),
               undo={"act": "rank", "step": step, "direction": "down" if direction == "up" else "up"})


def rename(project, step, name):
    s = _step(project, step)
    name = " ".join(str(name or "").split())
    if s is None:
        return _no("no such part")
    if not name:
        return _no("a name is needed")
    r = _cli(project, "roadmap-set", "--step", step, "--name", name)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("renamed \u2018%s\u2019 to \u2018%s\u2019" % (s.get("name"), name), undo={"act": "rename", "step": step, "name": s.get("name")})


def date(project, step, due):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if s.get("ref"):
        return _no("a referenced part takes its date from its own record — set it in that cockpit")
    due = str(due or "").strip() or "none"
    r = _cli(project, "roadmap-set", "--step", step, "--due", due)
    if not r.get("ok"):
        return _no("the engine refused: %s (a date is YYYY-MM-DD)" % r.get("error"))
    old = s.get("due") or "none"
    return _ok("%s now %s" % (s.get("name"), ("due " + due) if due != "none" else "carries no date"), undo={"act": "date", "step": step, "due": old})


def _flip(project, step, status, why, waiting_on=None):
    if waiting_on is not None:
        r0 = _cli(project, "roadmap-set", "--step", step, "--waiting-on", waiting_on)
        if not r0.get("ok"):
            return r0
    return _cli(project, "roadmap-set", "--step", step, "--status", status, "--who", WHO, "--reason", why)


def park(project, step, waiting_on):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if s.get("ref"):
        return _no("a referenced part is parked in its own record — open that cockpit")
    trigger = " ".join(str(waiting_on or "").split())
    if not trigger:
        return _no("a park carries its trigger — say until when, or what")
    r = _flip(project, step, "parked", "parked by John on the Campaign until " + trigger, waiting_on=trigger)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("%s parked until %s" % (s.get("name"), trigger), undo={"act": "unpark", "step": step})


def unpark(project, step):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if s.get("ref"):
        return _no("a referenced part is flipped in its own record")
    r = _flip(project, step, "planned", "unparked by John on the Campaign")
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("%s is back in play" % s.get("name"), undo={"act": "park", "step": step, "waiting_on": s.get("waiting_on") or "later"})


def flag(project, step, on=True):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if s.get("ref"):
        return _no("a referenced part's wait lives in its own record")
    if on:
        r = _flip(project, step, "waiting", "flagged by John on the Campaign: it needs him", waiting_on="John")
        text = "%s now needs you" % s.get("name")
    else:
        r = _flip(project, step, "planned", "unflagged by John on the Campaign")
        text = "%s no longer waits on you" % s.get("name")
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok(text, undo={"act": "unflag" if on else "flag", "step": step})


def tick(project, step):
    return _no("a tick on a native part waits on your word on the close law — the question in the approval; say it and the tick lands")


def add(project, initiative, kind, text, due=None, project_id=None):
    head = _step(project, initiative)
    if head is None or _own_group(head) is None:
        return _no("no such initiative")
    kind = str(kind or "task")
    text = " ".join(str(text or "").split())
    if kind == "project":
        if not project_id:
            return _no("which project?")
        ref = "project:%s" % project_id
        text = text or ("%s (the project)" % project_id[:8])
        sid = _slug(text, initiative)
        r = _cli(project, "roadmap-propose", "--step", sid, "--name", text, "--ref", ref)
    else:
        if not text:
            return _no("say what the part is")
        sid = _slug(text, initiative)
        args = ["roadmap-propose", "--step", sid, "--name", text]
        if due:
            args += ["--due", str(due).strip()]
        r = _cli(project, *args)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    r2 = _spine_set(project, sid, {"navigation": {"path": [initiative]}})
    if not r2.get("ok"):
        return _no("the part was written but not placed: %s" % r2.get("error"))
    return _ok("added \u2018%s\u2019 to %s%s" % (text, head.get("name"), (" · due " + str(due)) if due else ""), undo={"act": "withdraw", "step": sid}, step=sid)


def promote(project, seed_id, tier, area, done_when=None):
    """A seed (by its id on the strip) becomes an initiative: the heading step with the tier and area he picked,
    its root group at the foot of that tier, and the seed spent by one later receipt that cites its id."""
    seed = seed_by_id(project, seed_id)
    if seed is None:
        return _no("no such seed — the row above the board is the list")
    text = seed["text"]
    try:
        tier = int(tier) if str(tier or "").strip() else 3
    except Exception:
        return _no("a tier is 1, 2 or 3")
    if tier not in (1, 2, 3):
        return _no("a tier is 1, 2 or 3")
    sid = _slug(text)
    if _step(project, sid) is not None:
        return _no("an initiative with that name exists already")
    args = ["roadmap-propose", "--step", sid, "--name", text, "--tier", str(tier), "--done-when", done_when or "not written yet — say what done looks like"]
    if area:
        args += ["--area", str(area)]
    r = _cli(project, *args)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    r2 = _spine_set(project, sid, {"navigation": {"path": [sid], "groups": [{"id": sid, "label": text, "order": _foot(project, tier), "parent_id": None}], "role": "primary"}})
    if not r2.get("ok"):
        return _no("the heading was written but not grouped: %s" % r2.get("error"))
    r3 = _cli(project, "grasscatch", "--deferred", text, "--reason", "promoted seed %s → the initiative %s, by John on the Campaign" % (seed["id"], sid))
    spent = " — but the seed could not be spent on the strip: %s" % r3.get("error") if not r3.get("ok") else ""
    return _ok("%s is now an initiative in tier %d%s%s" % (text, tier, (" · " + str(area)) if area else "", spent),
               undo={"act": "withdraw", "step": sid, "seed": seed["id"]}, step=sid)


def retag(project, step, initiative):
    """A part moves to another initiative: one step_set of its navigation path. A heading is refused."""
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if _own_group(s) is not None:
        return _no("%s is an initiative, not a part — the Tier menu moves it" % s.get("name"))
    head = _step(project, initiative)
    if head is None or _own_group(head) is None:
        return _no("no such initiative")
    nav = dict(s.get("navigation") or {})
    old = list(nav.get("path") or [])
    if old and old[0] == initiative:
        return _no("%s is already under %s" % (s.get("name"), head.get("name")))
    nav["path"] = [initiative]
    r = _spine_set(project, step, {"navigation": nav})
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("%s moved to %s" % (s.get("name"), head.get("name")), undo={"act": "retag", "step": step, "initiative": old[0]} if old else None)


def withdraw(project, step, seed=None):
    """The inverse of add and promote. The record is append-only, so nothing is deleted: the step's navigation
    is cleared (one step_set), which takes it off the board; the ordinary cockpit still shows it. A heading that
    has parts is refused (the engine would refuse their paths). With a seed id, the seed is given back."""
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    old_nav = s.get("navigation")
    if not old_nav:
        return _no("%s is already off the board" % s.get("name"))
    if _own_group(s) is not None and _parts_of(project, step):
        return _no("%s has parts now — move them first, then withdraw it" % s.get("name"))
    r = _spine_set(project, step, {"navigation": None})
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    back = ""
    if seed:
        r2 = _cli(project, "grasscatch", "--deferred", s.get("name") or "", "--reason", "restored seed %s — the initiative %s was undone by John on the Campaign" % (seed, step))
        back = " and the seed is back above the board" if r2.get("ok") else " — but the seed could not be restored on the strip: %s" % r2.get("error")
    return _ok("%s withdrawn — off the board; the record keeps it (the cockpit shows it)%s" % (s.get("name"), back),
               undo={"act": "restore", "step": step, "navigation": old_nav, "seed": seed})


def restore(project, step, navigation, seed=None):
    s = _step(project, step)
    if s is None:
        return _no("no such part")
    if not isinstance(navigation, dict):
        return _no("nothing to restore it to")
    r = _spine_set(project, step, {"navigation": navigation})
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    spent = ""
    if seed:
        r2 = _cli(project, "grasscatch", "--deferred", s.get("name") or "", "--reason", "promoted seed %s → the initiative %s, by John on the Campaign (restored)" % (seed, step))
        spent = "" if r2.get("ok") else " — but the seed could not be spent on the strip: %s" % r2.get("error")
    return _ok("%s is back on the board%s" % (s.get("name"), spent), undo={"act": "withdraw", "step": step, "seed": seed})


ACTS = {"move_tier", "rank", "rename", "date", "park", "unpark", "flag", "unflag", "tick", "add", "promote", "withdraw", "restore", "retag",
        "activate", "bench", "order", "pace", "done_when", "place"}


# ── the active set (2026-09-29, John: "the active group") ─────────────────────────────────────────────────────────

def _active(project):
    """The active initiatives (step, group) in the set's order."""
    act = [(x, g) for x, g in _initiatives(project) if x.get("active") is True]
    return sorted(act, key=lambda t: (t[0].get("active_order") if isinstance(t[0].get("active_order"), int) else 999, t[0].get("tier") or 9, int(t[1].get("order") or 0)))


def _set_line(project):
    names = [x.get("name") or x["id"] for x, g in _active(project)]
    n = len(names)
    line = "the set is " + (", ".join(names) if names else "empty")
    if n > 3:
        line += " — %d active is wider than three; the steward would keep to three" % n     # said, never refused (his word: no cap)
    return line


def activate(project, step, order=None):
    """Make an initiative active at the foot of the set (or at the order the undo carries)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    if s.get("active") is True and order is None:
        return _no("%s is already active" % s.get("name"))
    place = int(order) if order is not None else len(_active(project))
    r = _cli(project, "roadmap-set", "--step", step, "--active", "on", "--active-order", str(place))
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    if order is not None:
        err = _place(project, step, place)      # at a saved index (an undo) or a drop's position: the others close up around it
        if err:
            return _no("%s is active, but the set could not close up around it: %s — look at the board" % (s.get("name"), err))
    return _ok("%s is active — %s" % (s.get("name"), _set_line(project)), undo={"act": "bench", "step": step})


def bench(project, step):
    """Take an initiative off the set; the set closes up; the pace stays (it is his date, not the set's)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    if s.get("active") is not True:
        return _no("%s is not active" % s.get("name"))
    old_order = s.get("active_order") if isinstance(s.get("active_order"), int) else None
    r = _cli(project, "roadmap-set", "--step", step, "--active", "off")
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    err = _renumber_active(project)
    if err:      # one outcome per act (Grok W1): a failed close-up refuses the receipt and carries no undo
        return _no("%s is off the set, but the set could not close up: %s — look at the board" % (s.get("name"), err))
    return _ok("%s to the bench — %s" % (s.get("name"), _set_line(project)), undo={"act": "activate", "step": step, "order": old_order})


def _renumber_active(project):
    """Close the set up (0, 1, 2 …); the first refused write is the error, else None."""
    for k, (x, g) in enumerate(_active(project)):
        if x.get("active_order") != k:
            r = _cli(project, "roadmap-set", "--step", x["id"], "--active-order", str(k))
            if not r.get("ok"):
                return "the engine refused: %s" % r.get("error")
    return None


def _place(project, step, position):
    """Put an active initiative at a position; the others close up around it. The first refused write is the error."""
    ids = [x["id"] for x, g in _active(project) if x["id"] != step]
    position = max(0, min(int(position), len(ids)))
    ids.insert(position, step)
    for k, sid in enumerate(ids):
        cur = _step(project, sid)
        if cur.get("active_order") != k:
            r = _cli(project, "roadmap-set", "--step", sid, "--active-order", str(k))
            if not r.get("ok"):
                return "the engine refused: %s" % r.get("error")
    return None


def order(project, step, position):
    """Put an active initiative at a position in the set (a drag within Active); the others close up around it."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    if s.get("active") is not True:
        return _no("%s is not active — make it active first" % s.get("name"))
    try:
        position = int(position)
    except Exception:
        return _no("a position is a number")
    old = next((k for k, (x, g) in enumerate(_active(project)) if x["id"] == step), None)
    err = _place(project, step, position)
    if err:
        return _no(err)
    return _ok("%s is %s in the set — %s" % (s.get("name"), ("first" if position == 0 else "number %d" % (position + 1)), _set_line(project)),
               undo={"act": "order", "step": step, "position": old} if old is not None else None)


def pace(project, step, when):
    """The date he drives an initiative toward (YYYY-MM-DD, or none)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    when = str(when or "").strip() or "none"
    r = _cli(project, "roadmap-set", "--step", step, "--pace", when)
    if not r.get("ok"):
        return _no("the engine refused: %s (a pace is YYYY-MM-DD, or none)" % r.get("error"))
    old = s.get("pace") or "none"
    return _ok("%s: the pace is %s" % (s.get("name"), ("now " + when) if when != "none" else "cleared"), undo={"act": "pace", "step": step, "when": old})


def done_when(project, step, text):
    """Revise a goal — what done looks like — on its initiative (the goal's place, W2 v2)."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    text = " ".join(str(text or "").split())
    if not text:
        return _no("a goal is a sentence — say what done looks like")
    old = s.get("done_when") or ""
    if text == old:
        return _no("the goal of %s already reads so" % s.get("name"))
    r = _cli(project, "roadmap-set", "--step", step, "--done-when", text)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    return _ok("Goal of %s revised" % s.get("name"), undo={"act": "done_when", "step": step, "text": old} if old else None)


def _tier_ids(project, tier, except_id=None):
    same = sorted([(int(g.get("order") or 0), x.get("name") or "", x["id"]) for x, g in _initiatives(project) if x.get("tier") == tier and x["id"] != except_id])
    return [sid for _o, _n, sid in same]


def _place_tier(project, step, tier, position):
    """Put an initiative at a position in its tier's order; the others close up. The first refused write is the error."""
    ids = _tier_ids(project, tier, except_id=step)
    position = max(0, min(int(position), len(ids)))
    ids.insert(position, step)
    for k, sid in enumerate(ids):
        cur = _step(project, sid)
        if int((_own_group(cur) or {}).get("order") or 0) != k:
            r = _write_nav(project, cur, order=k)
            if not r.get("ok"):
                return "the engine refused: %s" % r.get("error")
    return None


def place(project, step, band, position):
    """ONE act for a drop on the goal board (W2 v2): into Active at a position (activate there, or reorder), or into
    a tier's band at a position (off the set if it was on it; the tier changed if it differs; its place in that
    tier). One receipt, one undo that puts it back where it was."""
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    band = str(band or "").strip().lower()
    try:
        position = int(position)
    except Exception:
        return _no("a position is a number")
    was_active = s.get("active") is True
    old_tier = s.get("tier") if s.get("tier") in (1, 2, 3) else None
    old_active_pos = next((k for k, (x, g) in enumerate(_active(project)) if x["id"] == step), None)
    old_tier_pos = _tier_ids(project, old_tier).index(step) if old_tier and step in _tier_ids(project, old_tier) else 0
    if band == "active":
        if was_active:
            r = order(project, step, position)
            if r.get("ok"):
                r["undo"] = {"act": "place", "step": step, "band": "active", "position": old_active_pos or 0}
            return r
        return activate(project, step, order=position)      # its undo, bench, puts it back in its tier as it was
    if band not in ("1", "2", "3"):
        return _no("a band is Active or a tier 1, 2 or 3")
    tier = int(band)
    said = []
    if was_active:
        r = bench(project, step)
        if not r.get("ok"):
            return r
        said.append("%s to the bench" % s.get("name"))
    if old_tier != tier:
        r = move_tier(project, step, tier, order=position)
        if not r.get("ok"):
            return r
        said.append(("moved to tier %d" % tier) if said else "%s moved to tier %d" % (s.get("name"), tier))
    err = _place_tier(project, step, tier, position)
    if err:
        return _no("%s — but its place in tier %d could not be set: %s — look at the board" % (", ".join(said) or s.get("name"), tier, err))
    where = "first" if position == 0 else "number %d" % (position + 1)
    if said:
        said.append("%s in tier %d" % (where, tier))
    else:
        said.append("%s is %s in tier %d" % (s.get("name"), where, tier))
    line = ", ".join(said) + ((" — " + _set_line(project)) if was_active else "")
    undo = {"act": "place", "step": step, "band": "active", "position": old_active_pos or 0} if was_active else \
        {"act": "place", "step": step, "band": str(old_tier), "position": old_tier_pos} if old_tier else None
    return _ok(line, undo=undo)


def act(project, body):
    """Dispatch one act from the page; every answer is a receipt sentence, ok or refused."""
    body = body if isinstance(body, dict) else {}
    a = str(body.get("act") or "")
    if a not in ACTS:
        return _no("no such act")
    try:
        if a == "move_tier":
            return move_tier(project, body.get("step"), body.get("tier"), body.get("order"))
        if a == "rank":
            return rank(project, body.get("step"), "up" if body.get("direction") == "up" else "down")
        if a == "rename":
            return rename(project, body.get("step"), body.get("name"))
        if a == "date":
            return date(project, body.get("step"), body.get("due"))
        if a == "park":
            return park(project, body.get("step"), body.get("waiting_on"))
        if a == "unpark":
            return unpark(project, body.get("step"))
        if a == "flag":
            return flag(project, body.get("step"), True)
        if a == "unflag":
            return flag(project, body.get("step"), False)
        if a == "tick":
            return tick(project, body.get("step"))
        if a == "add":
            return add(project, body.get("initiative"), body.get("kind"), body.get("text"), body.get("due"), body.get("project_id"))
        if a == "promote":
            return promote(project, body.get("seed"), body.get("tier"), body.get("area"), body.get("done_when"))
        if a == "retag":
            return retag(project, body.get("step"), body.get("initiative"))
        if a == "activate":
            return activate(project, body.get("step"), body.get("order"))
        if a == "bench":
            return bench(project, body.get("step"))
        if a == "order":
            return order(project, body.get("step"), body.get("position"))
        if a == "done_when":
            return done_when(project, body.get("step"), body.get("text"))
        if a == "place":
            return place(project, body.get("step"), body.get("band"), body.get("position"))
        if a == "pace":
            return pace(project, body.get("step"), body.get("when"))
        if a == "withdraw":
            return withdraw(project, body.get("step"), body.get("seed"))
        if a == "restore":
            return restore(project, body.get("step"), body.get("navigation"), body.get("seed"))
    except Exception as e:
        return _no("that did not go through: %s" % e)
    return _no("no such act")
