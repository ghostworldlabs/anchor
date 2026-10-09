"""Skill jobs (two-lane step 3, John 2026-10-06 "build 3 anyway ... see how it performs"): a FENCED steward cannot
run a Foundry skill in its own turn (its edits and shell are fenced to its effort folder), so it asks the server, and
the server - outside any fence - starts the skill in the effort folder, keeps its log, and wakes the steward with the
result, the way a code job does. Only a skill's own run script under a skill root is accepted (node or python + a
script inside C:/dev/trio or C:/dev/Skill Foundry/skills); the record is .ecgberht/skill-jobs.json."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

JOBS_FILE = ".ecgberht/skill-jobs.json"
LOG_DIR = ".ecgberht/skill-jobs"
TIMEOUT_S = int(os.environ.get("ANCHOR_SKILL_JOB_TIMEOUT_S", str(6 * 3600)))
_LOCK = threading.RLock()
_PROCS = {}


def skill_roots():
    env = os.environ.get("ANCHOR_SKILL_ROOTS")
    roots = env.split(os.pathsep) if env else [r"C:\dev\trio", r"C:\dev\Skill Foundry\skills"]
    return [Path(r).resolve() for r in roots if r]


def _path(cdir):
    return Path(cdir) / JOBS_FILE


def read_jobs(cdir):
    try:
        data = json.loads(_path(cdir).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_job(cdir, job):
    with _LOCK:
        jobs = read_jobs(cdir)
        jobs[job["id"]] = job
        p = _path(cdir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp-%s" % uuid.uuid4().hex[:6])
        tmp.write_text(json.dumps(jobs, indent=1), encoding="utf-8")
        os.replace(tmp, p)


def validate(argv):
    """(ok, reason): node|python + a script inside a skill root; no shell, no other program."""
    if not isinstance(argv, list) or len(argv) < 2 or not all(isinstance(a, str) and a for a in argv):
        return False, "argv must be a list: node|python <a skill's script> [args]"
    if Path(argv[0]).name.lower().replace(".exe", "") not in ("node", "python"):
        return False, "only node or python may start a skill"
    try:
        script = Path(argv[1]).resolve()
    except Exception:
        return False, "the script path does not resolve"
    if not script.is_file():
        return False, "no such script: %s" % argv[1]
    from steward_cockpit import code_jobs as _cj
    parts = [part.lower() for part in script.parts]
    if "foreman" in parts:          # 2026-10-09: Foreman writes a project, so it runs only as a code job, never here
        return False, _cj.FOREMAN_AS_SKILL
    if _cj.foreman_crucible_held() and "crucible" in parts:
        return False, _cj.HOLD_REASON
    for root in skill_roots():
        try:
            script.relative_to(root)
            return True, ""
        except ValueError:
            continue
    return False, "the script is not inside a skill root (%s)" % ", ".join(str(r) for r in skill_roots())


def running(cdir):
    return [j for j in read_jobs(cdir).values() if j.get("status") == "running"]


class _Reserved:
    """A place in _PROCS taken before the drain question is asked (final review r2): a restart that begins between
    the question and the spawn still sees a skill job about to run."""
    pid = None

    def poll(self):
        return None


def start(cdir, argv, label=""):
    ok, why = validate(argv)
    if not ok:
        return {"ok": False, "error": why}
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    _PROCS[job_id] = _Reserved()
    try:
        from steward_cockpit import maintenance
        if maintenance.is_active():
            _PROCS.pop(job_id, None)
            return {"ok": False, "error": "Anchor is draining for a restart; start the skill when it is back"}
    except ImportError:
        pass
    log_rel = "%s/%s.log" % (LOG_DIR, job_id)
    log_path = Path(cdir) / log_rel
    job = {"id": job_id, "label": (label or Path(argv[1]).stem)[:120], "argv": argv, "status": "running",
           "started": time.strftime("%Y-%m-%d %H:%M:%S"), "log": log_rel}
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)          # subscription billing, as every skill launcher does
    env["CRUCIBLE_AGENT_LIVE"] = "1"
    # final review r3: every step after the reservation either succeeds or gives the reservation back - a failed
    # start never leaves a phantom "running" skill holding off every graceful restart
    out = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        out = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(argv, cwd=str(cdir), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except Exception as e:
        if out is not None:
            out.close()
        _PROCS.pop(job_id, None)
        return {"ok": False, "error": "could not start: %s" % e}
    job["pid"] = proc.pid
    try:
        _write_job(cdir, job)
    except Exception as e:                      # spawned but unrecorded: end it, so nothing runs that nobody owns
        _PROCS[job_id] = proc                   # counted by the restart check until it is SEEN to end (review r4)
        _kill_tree(proc)
        try:
            proc.wait(timeout=30)
        except Exception:
            pass
        if proc.poll() is None:                 # it would not stop: keep it counted, and let a reaper drop it on exit
            def reap():
                try:
                    proc.wait()
                finally:
                    out.close()
                    _PROCS.pop(job_id, None)
            threading.Thread(target=reap, name="skill-job-reap-" + job_id, daemon=True).start()
            return {"ok": False, "error": "could not record the skill job (%s), and it did not stop when asked - it is "
                                          "still counted as running until it ends (pid %s)" % (e, proc.pid)}
        out.close()
        _PROCS.pop(job_id, None)
        return {"ok": False, "error": "could not record the skill job, so it was stopped: %s" % e}
    _PROCS[job_id] = proc

    def wait():
        try:
            rc = proc.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            rc = None
        finally:
            out.close()
            _PROCS.pop(job_id, None)
        cur = read_jobs(cdir).get(job_id) or job
        if cur.get("status") != "running":
            return                                  # stopped by John: already recorded
        cur.update(status="done" if rc == 0 else "failed", rc=rc, finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                   tail=_tail(log_path))
        _write_job(cdir, cur)
        _report(cdir, cur)
    threading.Thread(target=wait, name="skill-job-" + job_id, daemon=True).start()
    return {"ok": True, "job": job_id, "log": log_rel}


def _tail(path, n=1500):
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-n:]
    except Exception:
        return ""


def _kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            proc.kill()
    except Exception:
        pass


def stop(cdir, job_id=None):
    jobs = [j for j in running(cdir) if not job_id or j["id"] == job_id]
    if not jobs:
        return {"ok": False, "error": "no skill job is running"}
    job = sorted(jobs, key=lambda j: j["started"])[-1]
    job.update(status="stopped", finished=time.strftime("%Y-%m-%d %H:%M:%S"))
    _write_job(cdir, job)
    proc = _PROCS.get(job["id"])          # stays registered until its wait() sees it end (final review r2)
    if proc is not None and not isinstance(proc, _Reserved):
        _kill_tree(proc)
    return {"ok": True, "job": job["id"]}


def _report(cdir, job):
    """He sees the end at once (the engine's own line); the steward is woken to read the result and tell him."""
    lines = ["(skill job %s finished - not John) %s: %s (exit %s)." % (job["id"], job["label"], job["status"], job.get("rc")),
             "Its log: %s (read it; the skill's outputs are in this folder)." % job["log"],
             "Log tail: " + (job.get("tail") or "")[-600:],
             "Tell John the result in two or three plain sentences, with links to what it produced."]
    try:
        from steward_cockpit import steward_routes as _sr
        eng = _sr.get_engine(str(cdir))
        if eng is not None:
            try:
                eng._emit({"t": "sys", "text": "skill job %s %s - %s" % (job["id"], "finished" if job["status"] == "done" else "failed", job["label"])})
            except Exception:
                pass
            if not eng.alive():
                eng.wake(fresh=False)
            eng.say("\n".join(lines), human=False)
    except Exception:
        pass
