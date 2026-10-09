"""W4 (2026-10-10): every forecast Anchor shows is kept with its issue time, the job or skill it is about, its basis
and the milestone it names ("worker finished"); when that same milestone happens, its actual time is recorded beside
it. So "accurate updates and estimates" (John, 2026-10-08) can be measured, not asserted - only for forecasts whose
milestone was observed.

One append-only file per effort: <effort>/.ecgberht/forecasts.jsonl. A forecast is written only when it CHANGES for
its subject (the status pane recomposes every few seconds); an actual is written once. Never raises.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

MILESTONE = "worker finished"
_CLOCK = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_LOCK = threading.Lock()


def _path(cdir):
    return Path(cdir) / ".ecgberht" / "forecasts.jsonl"


def _rows(cdir):
    try:
        lines = _path(cdir).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-2000:]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _append(cdir, row):
    p = _path(cdir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def clock_epoch(text, now=None):
    """The epoch of the first HH:MM in a forecast's text (the next such time at or after 12 h before now), or None."""
    m = _CLOCK.search(str(text or ""))
    if not m:
        return None
    now = time.time() if now is None else now
    lt = time.localtime(now)
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, mi, 0, 0, 0, -1))
    if t < now - 12 * 3600:
        t += 86400
    return t


def note(cdir, subject, kind, text, basis="", now=None):
    """Record a forecast for ``subject`` (a job id or skill run id) when its text changed; a forecast with no clock
    time ("no basis ...") is recorded too - it is what John was told."""
    if not subject or not text:
        return False
    now = time.time() if now is None else now
    try:
        with _LOCK:
            last = None
            for row in reversed(_rows(cdir)):
                if row.get("subject") == subject and row.get("type") == "forecast":
                    last = row
                    break
            if last and last.get("text") == text:
                return False
            _append(cdir, {"type": "forecast", "subject": subject, "kind": kind, "milestone": MILESTONE,
                           "issued_at": round(now, 1), "text": text, "forecast_epoch": clock_epoch(text, now),
                           "basis": basis})
            return True
    except Exception:
        return False


def observe(cdir, subject, actual_epoch):
    """Record the milestone's actual time for a subject that was forecast, once."""
    if not subject or not actual_epoch:
        return False
    try:
        with _LOCK:
            rows = _rows(cdir)
            if not any(r.get("subject") == subject and r.get("type") == "forecast" for r in rows):
                return False
            if any(r.get("subject") == subject and r.get("type") == "actual" for r in rows):
                return False
            _append(cdir, {"type": "actual", "subject": subject, "milestone": MILESTONE,
                           "actual_epoch": round(float(actual_epoch), 1), "recorded_at": round(time.time(), 1)})
            return True
    except Exception:
        return False


def pending(cdir):
    """The subjects forecast but with no actual recorded yet."""
    rows = _rows(cdir)
    done = {r.get("subject") for r in rows if r.get("type") == "actual"}
    return {r.get("subject") for r in rows if r.get("type") == "forecast"} - done


def observe_finished(cdir, epoch_of):
    """For every pending subject, read its job record (code-jobs.json / skill-jobs.json) and record the finish it
    reached. ``epoch_of`` turns a record's stamp into an epoch."""
    subjects = pending(cdir)
    if not subjects:
        return 0
    n = 0
    for name, prefix in (("code-jobs.json", "code:"), ("skill-jobs.json", "skill:")):
        try:
            raw = json.loads((Path(cdir) / ".ecgberht" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for jid, rec in (raw.items() if isinstance(raw, dict) else []):
            subject = prefix + str((rec or {}).get("id") or jid)
            if subject in subjects and isinstance(rec, dict) and rec.get("finished"):
                if observe(cdir, subject, epoch_of(rec.get("finished"))):
                    n += 1
    return n


def accuracy(cdir):
    """[{subject, kind, issued_at, text, forecast_epoch, actual_epoch, error_min}] for every forecast with a clock
    time whose milestone was observed (the last forecast issued before the actual)."""
    rows = _rows(cdir)
    actual = {r["subject"]: r["actual_epoch"] for r in rows if r.get("type") == "actual" and r.get("actual_epoch")}
    out = []
    for subject, act in actual.items():
        fc = [r for r in rows if r.get("type") == "forecast" and r.get("subject") == subject
              and r.get("forecast_epoch") and r.get("issued_at", 0) <= act]
        if not fc:
            continue
        last = fc[-1]
        out.append({"subject": subject, "kind": last.get("kind"), "issued_at": last["issued_at"], "text": last["text"],
                    "forecast_epoch": last["forecast_epoch"], "actual_epoch": act,
                    "error_min": round((act - last["forecast_epoch"]) / 60.0, 1)})
    return out
