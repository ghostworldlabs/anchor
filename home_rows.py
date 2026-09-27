"""home_rows — the facts each project row on the home is made of.

W1a of the High Seat plan (2026-09-26). Every row on the home is a fact from a project's
steward record — its strip (the human wait, the next step and why), its last persisted
status (the lead line), its roadmap (the open steps that carry a date) — never task
markdown, never steward prose. Three small reads per project, no scan, no model, no
bridge spawn on GET /. Never raises; a project without a record yields honest empties.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

_OPEN = ("proposed", "planned", "active", "waiting")


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def _iso(v):
    try:
        return date.fromisoformat(str(v or "")[:10])
    except Exception:
        return None


def project_facts(entry, today=None):
    """One registry entry → the facts its home row is made of.

    ``needs_you``  the strip's human wait, else the last status's "waiting on you" (the fact
                   behind a needs-you row); ``next`` / ``why`` the strip's next step and its reason;
                   ``summary`` the last persisted status, parsed once, with ``summary_age_s`` (the
                   row's steward line reads it from here, not from the file again); ``dated`` the
                   open steps that carry a ``due`` (soonest first, each with its project);
                   ``nearest_due`` the first of them; ``has_record`` whether any file existed.
    """
    today = today or date.today()
    entry = entry if isinstance(entry, dict) else {}
    pid = str(entry.get("id") or "")
    name = str(entry.get("name") or pid[:8])
    folder = str(entry.get("folder_path") or "").strip()
    out = {"id": pid, "name": name, "href": ("/project/%s" % pid) if pid else "",
           "needs_you": "", "next": "", "why": "", "summary": None, "summary_age_s": None, "dated": [],
           "nearest_due": "", "has_record": False, "folder": folder, "projection": None}
    if not folder or not pid:
        return out
    root = Path(folder)
    # the record may live one folder down (the cockpit's own discovery: the root, or a subfolder with a Face);
    # the card reads the effort touched last and names it (John, 2026-09-27: "I don't see many efforts")
    rel = current_effort(folder)
    if rel:
        root = root / rel
        out["effort"] = rel
    else:
        out["effort"] = ""
    out["effort_dir"] = str(root)
    out["touched_s"] = _touched_age(root)
    strip = _read_json(root / "strip.json")
    if isinstance(strip, dict):
        out["has_record"] = True
        out["needs_you"] = str(strip.get("human_wait") or "").strip()
        out["next"] = str(strip.get("next_recommended") or "").strip()
        out["why"] = str(strip.get("why_next") or "").strip()
    sfile = root / ".ecgberht" / "status-summary.json"
    summ = _read_json(sfile)
    if isinstance(summ, dict):
        out["has_record"] = True
        out["summary"] = summ
        try:
            out["summary_age_s"] = max(0.0, time.time() - sfile.stat().st_mtime)
        except Exception:
            out["summary_age_s"] = None
        plan = summ.get("plan") if isinstance(summ.get("plan"), dict) else {}
        if not out["needs_you"]:
            out["needs_you"] = str(plan.get("waiting_on_you") or "").strip()
    rm = _read_json(root / "roadmap.json")
    if isinstance(rm, dict):
        out["has_record"] = True
        if not rel:
            out["projection"] = rm.get("roadmap_projection") or []   # the ROOT record only: a resolver in the same request keys on the project folder
        dated = []
        for s in rm.get("roadmap_projection") or []:
            if not isinstance(s, dict) or s.get("status") not in _OPEN:
                continue
            d = _iso(s.get("due")) if s.get("due") else None
            if d is None:
                continue
            dated.append({"step_id": str(s.get("id") or ""), "name": str(s.get("name") or ""),
                          "due": d.isoformat(), "status": str(s.get("status") or ""),
                          "project_id": pid, "project_name": name})
        dated.sort(key=lambda x: (x["due"], x["name"]))
        out["dated"] = dated
        out["nearest_due"] = dated[0]["due"] if dated else ""
    return out


_RECORD_FILES = ("strip.json", "roadmap.json", str(Path(".ecgberht") / "status-summary.json"))


def _touched(d):
    """The newest record file's mtime under an effort folder, or 0."""
    best = 0.0
    for n in _RECORD_FILES:
        try:
            best = max(best, (Path(d) / n).stat().st_mtime)
        except OSError:
            pass
    return best


def _touched_age(d):
    t = _touched(d)
    return max(0.0, time.time() - t) if t else None


def current_effort(folder):
    """The effort the card shows: of the efforts the cockpit discovers (the root when it has a Face, plus one level
    of subfolders with their own ECGBERHT.md), the one whose record was touched last; "" for the root or when no
    effort exists. Read-only; never raises."""
    try:
        from steward_cockpit.steward_campaign import discover_efforts
        efforts = discover_efforts(str(folder)) or []
    except Exception:
        return ""
    best, best_t = "", -1.0
    for e in efforts:
        rel = str((e or {}).get("rel") or "")
        t = _touched(Path(folder) / rel if rel else Path(folder))
        if t > best_t:
            best, best_t = rel, t
    return best


def all_project_facts(entries, today=None):
    """The facts for every entry, in the entries' order; a bad entry is skipped, never fatal."""
    out = []
    for e in entries or ():
        try:
            out.append(project_facts(e, today))
        except Exception:
            continue
    return out


def week_in_words(today=None):
    """The week header in words: 'this week Sep 22–28' (Monday to Sunday of today's week)."""
    today = today or date.today()
    mon = today - timedelta(days=today.weekday())
    sun = mon + timedelta(days=6)

    def md(d):
        return "%s %d" % (d.strftime("%b"), d.day)
    if mon.month == sun.month:
        return "this week %s–%d" % (md(mon), sun.day)
    return "this week %s – %s" % (md(mon), md(sun))


def due_label(iso, today=None):
    """'overdue since Sep 20' · 'due today' · 'due Oct 8' — the same date, said against today."""
    d = _iso(iso)
    if not d:
        return ""
    today = today or date.today()
    if d < today:
        return "overdue since " + short_date(iso)
    if d == today:
        return "due today"
    return "due " + short_date(iso)


def short_date(iso):
    """'2026-10-08' → 'Oct 8'; anything else comes back as it is."""
    d = _iso(iso)
    return ("%s %d" % (d.strftime("%b"), d.day)) if d else str(iso or "")
