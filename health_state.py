"""health_state - the banner tells the truth (W3 of the overnight plan of 2026-10-08; John that day: "I want it to
diagnose, resolve health issues and have the banner go down once that is done").

ONE store and ONE reading of it for every banner (the Cave's, the classic dashboard's, the Doctor's card):
``paths.health_reports_dir()``, where only a dated report (``YYYY-MM-DD.md``) is ever taken as "the newest" - never
README.md, a soak ledger or a candidate's report.

Two states, never mixed:
  - the RUNNING revision's health: the newest dated report. It is written by the daily self-test and by the
    Doctor's re-run, both of which check the code the service runs (W1a: nothing writes the running checkout in
    place any more). Red stays red until such a run passes.
  - a CANDIDATE's health: a fix landed on anchor-next, checked in a throwaway worktree of that exact revision on a
    private port (``check_candidate``). A pass is recorded in ``candidate.json`` - revision, status, run, the issue
    it answers - and the red banner then says "fix verified on <revision>, live after your restart". It never
    clears the banner. A candidate whose revision is no longer anchor-next's head, or that is already running, or
    that is older than the newest report, is stale and ignored.

After the restart that makes the candidate live, ``recheck_needed`` is true (the running build carries the verified
revision but the newest report predates it): the server starts one re-run of the check against the code it runs,
and only that pass clears the banner.

Stdlib only; never raises.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DATED = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
CANDIDATE_FILE = "candidate.json"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def reports_dir():
    import paths as _paths
    return _paths.health_reports_dir()


def dated_reports():
    """The dated reports, newest first (by name - the date)."""
    try:
        return sorted((p for p in reports_dir().glob("*.md") if p.is_file() and DATED.match(p.name)),
                      key=lambda p: p.name, reverse=True)
    except OSError:
        return []


def status_of(body):
    """red | yellow | green | unknown, per the locked severity rule (correctness red; timing notes yellow)."""
    body = body or ""
    if "Status: ISSUES FOUND" in body:
        return "red"
    m = re.search(r"^## Warnings[^\n]*\n+(.*?)(?=^## |\Z)", body, re.S | re.M)
    if m and m.group(1).strip() and m.group(1).strip() != "(none)":
        return "yellow"
    if re.search(r"^Status: OK\s*$", body, re.M):
        return "green"
    return "unknown"


def field(body, name):
    m = re.search(r"^%s:\s*(.+)$" % re.escape(name), body or "", re.M)
    return m.group(1).strip() if m else ""


def latest():
    """(path, body) of the newest dated report of the RUNNING target (a report naming another target is skipped; one
    written before targets were named counts as running), or (None, "")."""
    for p in dated_reports():
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if field(body, "Target") in ("", "running"):
            return p, body
    return None, ""


def issues_of(body):
    """The report's issue lines - the identity a candidate's pass answers."""
    m = re.search(r"^## Issues[^\n]*\n+(.*?)(?=^## |\Z)", body or "", re.S | re.M)
    return [ln.strip()[2:].strip() for ln in (m.group(1).splitlines() if m else []) if ln.strip().startswith("- ")][:20]


def _git(repo, *args):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW)
        return r.returncode, (r.stdout or "").strip()
    except Exception:
        return 1, ""


def running_head():
    return (os.environ.get("ANCHOR_RUNNING_HEAD") or "").strip()


def is_live(revision, repo=None):
    """Does the running build carry ``revision``?"""
    run = running_head()
    if not revision or not run:
        return False
    root = repo or _served()
    return _git(root, "merge-base", "--is-ancestor", revision, run)[0] == 0


def _served():
    try:
        import anchor_next
        return anchor_next.served_root()
    except Exception:
        return Path(__file__).resolve().parent


def read_candidate():
    try:
        rec = json.loads((reports_dir() / CANDIDATE_FILE).read_text(encoding="utf-8"))
        return rec if isinstance(rec, dict) else None
    except Exception:
        return None


def write_candidate(rec):
    try:
        d = reports_dir()
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / (CANDIDATE_FILE + ".tmp")
        tmp.write_text(json.dumps(rec, indent=1), encoding="utf-8")
        os.replace(str(tmp), str(d / CANDIDATE_FILE))
        return True
    except Exception:
        return False


def verified_candidate():
    """The candidate pass the red banner may name, or None (stale, failed, already live, or older than the report)."""
    c = read_candidate()
    if not c or c.get("target") != "candidate" or c.get("status") not in ("green", "yellow"):
        return None
    rev = str(c.get("revision") or "")
    try:
        import anchor_next
        nxt = anchor_next.head_of(_served(), "refs/heads/" + anchor_next.BRANCH)
    except Exception:
        nxt = ""
    if not rev or rev != nxt:                       # anchor-next moved since: that pass was for another revision
        return None
    if is_live(rev):                                # running now: only a re-check of the running build counts
        return None
    path, body = latest()
    if path is not None and float(c.get("at") or 0) < path.stat().st_mtime:
        return None                                 # a newer report has been written since the candidate ran
    answers = c.get("answers") or {}
    if path is None or answers.get("report") != path.name or answers.get("issues") != issues_of(body):
        return None                                 # it answered another report's issues
    return c


def _answers_this_report(c, path, body):
    answers = (c or {}).get("answers") or {}
    return path is not None and answers.get("report") == path.name and answers.get("issues") == issues_of(body)


def recheck_needed():
    """The running build carries a verified candidate's revision, and the newest report is still red and older than
    this build's start: one re-run of the check against the running code is owed."""
    c = read_candidate()
    path, body = latest()
    if not c or path is None or status_of(body) != "red" or c.get("status") not in ("green", "yellow"):
        return False
    if c.get("target") != "candidate" or c.get("rechecked_for"):
        return False                                # one obligation per verified candidate, consumed when launched
    if not _answers_this_report(c, path, body):
        return False
    if not is_live(str(c.get("revision") or "")):
        return False
    started = float(os.environ.get("ANCHOR_STARTED_AT") or 0)
    return path.stat().st_mtime < started if started else True


def mark_rechecked(run):
    """The owed re-check was LAUNCHED for this running build: recorded on the candidate, so it is owed once."""
    c = read_candidate()
    if c is not None:
        c["rechecked_for"], c["recheck_run"] = running_head(), run
        write_candidate(c)


def banner():
    """None, or the banner's facts: {"status", "date", "report", "verified": candidate-or-None, "text", "why"}."""
    path, body = latest()
    if path is None:
        return None
    st = status_of(body)
    if st != "red":
        return None
    v = verified_candidate()
    why = "%s — Doctor can diagnose it" % path.stem
    if v:
        why = "%s — fix verified on %s, live after your restart" % (path.stem, str(v.get("revision") or "")[:10])
    return {"status": st, "date": path.stem, "report": path.name, "verified": v,
            "text": "Health check found issues", "why": why}


def signature():
    """An opaque fingerprint of what the banner says (no content leaves): the newest report's name, time and status,
    and the candidate's verdict. A page compares it to know its banner is stale."""
    import hashlib
    path, body = latest()
    parts = [path.name if path else "", str(int(path.stat().st_mtime)) if path else "", status_of(body)]
    v = verified_candidate() if path is not None and status_of(body) == "red" else None
    parts.append(str((v or {}).get("revision") or ""))
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _kill_tree(proc):
    """The whole process tree a check owns (the health check and the throwaway server it started)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=60,
                           creationflags=_NO_WINDOW)
        else:
            proc.kill()
        proc.wait(timeout=60)
    except Exception:
        pass


def check_candidate(log=None, timeout=3600):
    """Check anchor-next's head in a throwaway worktree that is ALSO its data folder (ChatGPT W3 r1: never the live
    data, the live worktrees or the code-jobs folder - its server's boot maintenance and the synthetic checks write
    only there), on a private port, with the process killer off. One report per run (candidate-<rev>-<run>.md); the
    pass counts only when the run completed and its report names target "candidate" and this revision. The verdict,
    with the report and issues it answers, goes to candidate.json. The running checkout and the lander's checkout are
    never touched; the whole process tree is killed on a timeout; a cleanup that fails is said."""
    import anchor_next
    import shutil
    import tempfile
    served = anchor_next.served_root()
    rev = anchor_next.head_of(served, "refs/heads/" + anchor_next.BRANCH)
    run = time.strftime("%Y%m%d-%H%M%S")
    path, body = latest()
    rec = {"target": "candidate", "revision": rev, "status": "unknown", "at": time.time(), "run": run, "why": "",
           "answers": {"report": path.name if path else "", "issues": issues_of(body)}}
    if not rev:
        rec["why"] = "nothing has landed on %s" % anchor_next.BRANCH
        return rec
    if is_live(rev):
        rec["why"] = "%s is already running - the daily check and the Doctor's re-run check it" % rev[:10]
        return rec
    scratch = Path(tempfile.mkdtemp(prefix="anchor-candidate-"))
    wt = scratch / "wt"
    out = reports_dir() / ("candidate-%s-%s.md" % (rev[:12], run))
    try:
        code, _ = _git(served, "worktree", "add", "--detach", str(wt), rev)
        if code != 0:
            rec["why"] = "could not make a worktree of %s" % rev[:10]
            return rec
        env = dict(os.environ, ANCHOR_HEALTHCHECK_TARGET="candidate", ANCHOR_HEALTH_REPORT_OUT=str(out),
                   ANCHOR_HEALTHCHECK_PORT="0", ANCHOR_DATA_DIR=str(wt), ANCHOR_CODE_JOBS_DIR=str(scratch / "jobs"),
                   ANCHOR_WORKTREE_BASE=str(scratch / "worktrees"))
        for k in ("ANCHOR_HEALTHCHECK_KILL_STALE_SERVICE", "ANCHOR_HEALTHCHECK_LIVE_PORT"):
            env.pop(k, None)
        proc = subprocess.Popen([sys.executable, str(wt / "anchor_healthcheck.py")], cwd=str(wt), env=env,
                                stdout=log or subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                creationflags=_NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        try:
            rc = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            rec["why"] = "the check ran longer than %ss and was stopped" % timeout
            return rec
        try:
            report = out.read_text(encoding="utf-8", errors="replace")
        except OSError:
            report = ""
        if rc not in (0, 1) or not report:
            rec["why"] = "the check did not complete (exit %s)" % rc
        elif field(report, "Target") != "candidate" or not field(report, "Revision").startswith(rev):
            rec["why"] = "the report is not this candidate's (target %s, revision %s)" % (field(report, "Target"), field(report, "Revision")[:12])
        else:
            rec["status"], rec["report"] = status_of(report), out.name
    finally:
        _git(served, "worktree", "remove", "--force", str(wt))
        shutil.rmtree(str(scratch), ignore_errors=True)
        _git(served, "worktree", "prune")
        if scratch.exists():
            rec["why"] = (rec["why"] + "; " if rec["why"] else "") + "the throwaway folder %s could not be removed" % scratch
        rec["at"] = time.time()
        write_candidate(rec)
    return rec


def _data_dir():
    try:
        import paths as _paths
        return _paths.data_dir()
    except Exception:
        return _served()
