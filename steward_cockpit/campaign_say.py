"""campaign_say — the Campaign verbs spoken in a composer: the engine names the act, the Campaign's own writer applies it.

W5 of the High Seat plan (2026-09-26). "move <initiative> to tier n" · "add a part to <initiative>: <text> [due <date>]"
· "make <seed> an initiative [in tier n] [under <area>]" · "park <part> until <trigger>" · "unpark <part>" · "what needs
me [this week|today]". The engine's dialogue act table compiles the words (the destructive guard first; nothing is
written there); this module resolves the names against the Campaign record — an exact name or id, else the one part
that contains the words, else a refusal that names the candidates — and applies the act through
``steward_cockpit/campaign_acts`` (the same receipts with undo the pages use). Anything that is not a Campaign verb
answers None and the steward takes it as before. Only the Campaign record is ever written.
"""
from __future__ import annotations

import calendar as _cal
import json
import os
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

DIALOGUE = "file:///C:/dev/Ecgberht/engine/dialogue.mjs"
AREAS = ("family", "professional", "writing", "research", "tools", "personal")
_STOP = {"the", "a", "an", "to", "of", "for", "and", "my", "our"}
_JS = ("import { compileUtterance, CAMPAIGN_ACT_IDS } from '%s';"
       "const r = compileUtterance(process.argv[1] || '');"
       "console.log(JSON.stringify({ok: !!r.compiled, act: r.act || null, args: r.args || {},"
       " campaign: !!(r.compiled && CAMPAIGN_ACT_IDS.includes(r.act)), refused: r.utterance_kind || null}));")


def campaign_dir():
    import paths as _paths
    return Path(_paths.data_dir()).resolve().parent / "Campaign"


def is_campaign_folder(folder):
    try:
        return Path(str(folder)).resolve() == campaign_dir()
    except Exception:
        return False


def compile_utterance(text, dialogue=None):
    """The engine's word: ``{"ok", "act", "args", "campaign", "refused"}`` or None when the engine could not answer."""
    text = " ".join(str(text or "").split())
    if not text:
        return None
    try:
        r = subprocess.run(["node", "--input-type=module", "-e", _JS % (dialogue or DIALOGUE), "--", text],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return None


# ── names ──────────────────────────────────────────────────────────────────────────────────────

def _norm(s):
    s = " ".join(str(s or "").lower().split()).strip(" .!?,\u2019'\"")
    return re.sub(r"^(?:the|an|a) ", "", s)


def _find(cands, phrase, what):
    """``cands`` = [(id, name, ...)]; the exact name or id, else the one candidate containing the words either way."""
    key = _norm(phrase)
    if not key:
        return None, "which %s? say its name" % what
    exact = [c for c in cands if _norm(c[1]) == key or _norm(c[0]) == key]
    if len(exact) == 1:
        return exact[0], None
    words = {w for w in re.split(r"[^a-z0-9]+", key) if w and w not in _STOP}
    byword = [c for c in cands if words and words <= {w for w in re.split(r"[^a-z0-9]+", _norm(c[1])) if w}]
    if len(byword) == 1:
        return byword[0], None
    part = [c for c in cands if key in _norm(c[1]) or _norm(c[1]) in key]
    if len(part) == 1:
        return part[0], None
    if len(byword) > 1 and not exact:
        part = byword
    if not part and not exact:
        names = ", ".join("\u2018%s\u2019" % c[1] for c in cands[:6])
        return None, "no %s named \u2018%s\u2019%s" % (what, phrase, (" \u2014 the record has " + names) if names else "")
    names = " or ".join("\u2018%s\u2019" % c[1] for c in (exact or part)[:5])
    return None, "\u2018%s\u2019 could be %s \u2014 say which" % (phrase, names)


_MONTHS = {m.lower(): k for k, m in enumerate(_cal.month_abbr) if m}
_MONTHS.update({m.lower(): k for k, m in enumerate(_cal.month_name) if m})
_DAYS = {d.lower(): k for k, d in enumerate(_cal.day_abbr)}
_DAYS.update({d.lower(): k for k, d in enumerate(_cal.day_name)})


def parse_due(s, today=None):
    """YYYY-MM-DD · today · tomorrow · Tuesday · Oct 27 · 27 Oct (this year, as typed) — or None when the calendar has
    no such day (the same rule the Desk's own editor keeps)."""
    today = today or date.today()
    s = " ".join(str(s or "").lower().split()).strip(" .!")
    if not s:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    if s == "today":
        return today.isoformat()
    if s == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if s in _DAYS:
        ahead = (_DAYS[s] - today.weekday()) % 7 or 7
        return (today + timedelta(days=ahead)).isoformat()
    m = re.fullmatch(r"([a-z]+)\.? (\d{1,2})", s) or re.fullmatch(r"(\d{1,2}) ([a-z]+)\.?", s)
    if m:
        a, b = m.group(1), m.group(2)
        mon, day = (a, b) if a.isalpha() else (b, a)
        k = _MONTHS.get(mon) or _MONTHS.get(mon[:3])
        if k:
            try:
                return date(today.year, k, int(day)).isoformat()
            except ValueError:
                return None
    return None


# ── the answer ─────────────────────────────────────────────────────────────────────────────────

def _answer(r, act):
    out = {"ok": bool(r.get("ok")), "say": r.get("receipt") or "", "receipt": r.get("receipt") or "", "undo": r.get("undo"),
           "act": act, "campaign_act": True, "model_called": False}
    if r.get("step"):
        out["step"] = r["step"]
    return out


def _refuse(text, act):
    return {"ok": False, "say": text, "receipt": text, "undo": None, "act": act, "campaign_act": True, "model_called": False}


def _needs(folder, span, today):
    """What needs him: the parts flagged needs-you, and the dated parts inside the span — read from the record."""
    try:
        import high_seat_page as _hsp
        from .campaign_parts import resolve_parts
        from .steward_campaign import read_map
        steps = (read_map(str(folder)) or {}).get("steps") or []
        inits = _hsp.campaign_initiatives(steps, resolve_parts(steps, cache={}, with_lead=False))
    except Exception as e:
        return _refuse("the Campaign record could not be read: %s" % e, "campaign_needs")
    needs = [(p, i) for i in inits for p in i["needs"]]
    monday = today - timedelta(days=today.weekday())
    end = today if span == "today" else monday + timedelta(days=6)
    dated = sorted(((p["date"], p, i) for i in inits for p in i["parts"]
                    if p["date"] and not p["broken"] and p["status"] not in ("done", "parked") and p["date"] <= end.isoformat()), key=lambda x: x[0])
    bits = []
    if needs:
        bits.append("%d need%s your word: %s" % (len(needs), "s" if len(needs) == 1 else "", "; ".join("%s (%s, tier %s)" % (p["text"], i["name"], i["tier"] or "?") for p, i in needs[:5])))
    else:
        bits.append("nothing waits on your word")
    label = "today" if span == "today" else "this week"
    if dated:
        bits.append("dated by %s: %s" % (label, "; ".join("%s (%s, %s)" % (p["text"], i["name"], p["date"]) for d, p, i in dated[:5])))
    else:
        bits.append("nothing on the Campaign is dated %s" % ("today or earlier" if span == "today" else "inside this week"))
    return {"ok": True, "say": "; ".join(bits) + ".", "receipt": "", "undo": None, "act": "campaign_needs", "campaign_act": True, "read_only": True, "model_called": False}


def say_campaign(folder, text, dialogue=None, today=None):
    """None when the words are not a Campaign verb (the steward takes them); else the act's answer."""
    c = compile_utterance(text, dialogue)
    if not c or not c.get("campaign"):
        return None
    from . import campaign_acts as acts
    act, a = c["act"], c.get("args") or {}
    today = today or date.today()
    inits = [(s["id"], s.get("name") or s["id"]) for s, g in acts._initiatives(folder)]
    heads = {i for i, _ in inits}
    parts = [(p["id"], p.get("name") or p["id"]) for p in acts._projection(folder)
             if p.get("id") not in heads and isinstance(p.get("navigation"), dict) and (p["navigation"].get("path") or [])]
    if act == "campaign_move_tier":
        hit, why = _find(inits, a.get("initiative"), "initiative")
        return _refuse(why, act) if hit is None else _answer(acts.move_tier(folder, hit[0], a.get("tier")), act)
    if act == "campaign_add_part":
        hit, why = _find(inits, a.get("initiative"), "initiative")
        if hit is None:
            return _refuse(why, act)
        due = None
        if a.get("due"):
            due = parse_due(a["due"], today)
            if due is None:
                return _refuse("I could not read \u2018%s\u2019 as a date \u2014 Oct 3, Tuesday, today or 2026-10-03; nothing was added" % a["due"], act)
        return _answer(acts.add(folder, hit[0], "task", a.get("text"), due), act)
    if act == "campaign_promote_seed":
        from .campaign_seeds import read_seeds
        seeds = [(s["id"], s["text"]) for s in read_seeds(folder)]
        hit, why = _find(seeds, a.get("seed"), "seed")
        if hit is None:
            return _refuse(why if seeds else "no seeds above the board yet", act)
        area = str(a.get("area") or "").lower() or None
        if area and area not in AREAS:
            return _refuse("the life areas are %s \u2014 which?" % ", ".join(AREAS), act)
        return _answer(acts.promote(folder, hit[0], a.get("tier") or 3, area), act)
    if act == "campaign_park":
        hit, why = _find(parts, a.get("part"), "part")
        if hit is None:
            return _refuse(why, act)
        if not a.get("trigger"):
            return _refuse("a park carries its trigger \u2014 say \u2018park %s until January\u2019, or what it waits for" % hit[1], act)
        return _answer(acts.park(folder, hit[0], a["trigger"]), act)
    if act == "campaign_unpark":
        hit, why = _find(parts, a.get("part"), "part")
        return _refuse(why, act) if hit is None else _answer(acts.unpark(folder, hit[0]), act)
    if act == "campaign_needs":
        return _needs(folder, a.get("span") or "week", today)
    return None
