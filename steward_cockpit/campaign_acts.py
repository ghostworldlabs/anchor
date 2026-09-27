"""campaign_acts — what John does on the Campaign page, written into the Campaign's own record through the
engine's writer (the CLI and its spine), each act a receipt with its inverse.

W3c of the High Seat plan (2026-09-26). Acts: move_tier · rank (up/down within a tier) · rename · date ·
park (with its trigger) · unpark · flag / unflag (a native part's "needs you") · add (a task, or a project part
by reference) · promote (a seed → an initiative, asking the tier and the area). A tick on a native part waits on
John's word on the close law (PLAN §9.6) and is refused here with that sentence. The Campaign never writes another
record: a date or a flip on a referenced part is refused by the engine and the refusal is the receipt.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

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


# ── the acts ───────────────────────────────────────────────────────────────────────────────────

def move_tier(project, step, tier):
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
    if old == tier:
        return _no("%s is already in tier %d" % (s.get("name"), tier))
    r = _cli(project, "roadmap-set", "--step", step, "--tier", str(tier))
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    # it lands at the foot of its new tier
    foot = max([int(_own_group(x).get("order") or 0) for x, g in _initiatives(project) if x.get("tier") == tier and x.get("id") != step] or [-1]) + 1
    _write_nav(project, _step(project, step), order=foot)
    return _ok("%s moved to tier %d (from %s), at its foot" % (s.get("name"), tier, ("tier %d" % old) if old else "no tier"),
               undo={"act": "move_tier", "step": step, "tier": old} if old else None)


def rank(project, step, direction):
    s = _step(project, step)
    if s is None or _own_group(s) is None:
        return _no("no such initiative")
    same = sorted([(int(g.get("order") or 0), x) for x, g in _initiatives(project) if x.get("tier") == s.get("tier")], key=lambda t: (t[0], t[1].get("name") or ""))
    idx = next((k for k, (o, x) in enumerate(same) if x.get("id") == step), None)
    if idx is None:
        return _no("not in a tier")
    j = idx - 1 if direction == "up" else idx + 1
    if j < 0 or j >= len(same):
        return _no("%s is already at the %s of its tier \u2014 the Tier menu moves it between tiers" % (s.get("name"), "top" if direction == "up" else "foot"))
    a, b = same[idx], same[j]
    oa, ob = a[0], b[0]
    if oa == ob:
        ob = oa + 1 if direction == "up" else oa - 1
    r1 = _write_nav(project, a[1], order=ob)
    r2 = _write_nav(project, b[1], order=oa)
    if not (r1.get("ok") and r2.get("ok")):
        return _no("the engine refused: %s" % (r1.get("error") or r2.get("error")))
    return _ok("%s moved %s within tier %s, past %s" % (s.get("name"), direction, s.get("tier"), b[1].get("name")),
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
        return _no("a referenced part takes its date from its own record \u2014 set it in that cockpit")
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
        return _no("a referenced part is parked in its own record \u2014 open that cockpit")
    trigger = " ".join(str(waiting_on or "").split())
    if not trigger:
        return _no("a park carries its trigger \u2014 say until when, or what")
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
    return _no("a tick on a native part waits on your word on the close law \u2014 the question in the approval; say it and the tick lands")


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
    return _ok("added \u2018%s\u2019 to %s%s" % (text, head.get("name"), (" \u00b7 due " + str(due)) if due else ""), undo={"act": "park", "step": sid, "waiting_on": "undone"}, step=sid)


def promote(project, seed_text, tier, area, done_when=None):
    text = " ".join(str(seed_text or "").split())
    if not text:
        return _no("which seed?")
    try:
        tier = int(tier) if str(tier).strip() else 3
    except Exception:
        return _no("a tier is 1, 2 or 3")
    sid = _slug(text)
    if _step(project, sid) is not None:
        return _no("an initiative with that name exists already")
    args = ["roadmap-propose", "--step", sid, "--name", text, "--tier", str(tier), "--done-when", done_when or "not written yet \u2014 say what done looks like"]
    if area:
        args += ["--area", str(area)]
    r = _cli(project, *args)
    if not r.get("ok"):
        return _no("the engine refused: %s" % r.get("error"))
    foot = max([int(g.get("order") or 0) for x, g in _initiatives(project) if x.get("tier") == tier] or [-1]) + 1
    r2 = _spine_set(project, sid, {"navigation": {"path": [sid], "groups": [{"id": sid, "label": text, "order": foot, "parent_id": None}], "role": "primary"}})
    if not r2.get("ok"):
        return _no("the heading was written but not grouped: %s" % r2.get("error"))
    _cli(project, "grasscatch", "--deferred", text, "--reason", "promoted to an initiative (%s) by John on the Campaign" % sid)
    return _ok("%s is now an initiative in tier %d%s" % (text, tier, (" \u00b7 " + str(area)) if area else ""), undo={"act": "park", "step": sid, "waiting_on": "undone \u2014 a seed again"}, step=sid)


ACTS = {"move_tier", "rank", "rename", "date", "park", "unpark", "flag", "unflag", "tick", "add", "promote"}


def act(project, body):
    """Dispatch one act from the page; every answer is a receipt sentence, ok or refused."""
    body = body if isinstance(body, dict) else {}
    a = str(body.get("act") or "")
    if a not in ACTS:
        return _no("no such act")
    try:
        if a == "move_tier":
            return move_tier(project, body.get("step"), body.get("tier"))
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
    except Exception as e:
        return _no("that did not go through: %s" % e)
    return _no("no such act")
