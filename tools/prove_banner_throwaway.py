"""W3's end-to-end proof on a THROWAWAY service (plan of 2026-10-08; ChatGPT W3 review round 1): a planted failure on
a clone of the branch running on a free port (never 8777); the real health check goes red and the Cave shows the
banner; a fix lands on anchor-next; the real candidate check passes on its own throwaway data; the Cave says "fix
verified, live after your restart" and stays red; the controlled restart (stop -> activate -> start); the owed
re-check starts by itself and checks the running service; the banner goes down.

usage: python tools/prove_banner_throwaway.py <scratch folder> [branch]   -> JSON lines; exit 0 when every step holds.
The real health check takes minutes; this proof takes roughly 15-25."""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANT = '    """GET /api/status — coarse task/project/inbox counts for the page header."""\n'
BROKEN = PLANT + '    raise RuntimeError("W3 proof: a planted failure")\n'


def g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(port, path, timeout=30):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
            return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def banner(port):
    """What a REAL browser shows (ChatGPT W3 r2): the Cave opened in Chromium; the painted banner's words, or ""."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page()
            pg.goto("http://127.0.0.1:%d/high-seat" % port, wait_until="load", timeout=180000)
            bar = pg.query_selector(".healthbar")
            return bar.inner_text() if bar and bar.is_visible() else ""
        finally:
            b.close()


def start(served, port, env):
    proc = subprocess.Popen([sys.executable, str(served / "anchor_gui.py"), "--port", str(port), "--no-browser"],
                            cwd=str(served), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.time() + 400
    while time.time() < deadline:
        code, _ = get(port, "/api/version", timeout=10)
        if code == 200:
            return proc
        if proc.poll() is not None:
            raise RuntimeError("the throwaway service exited %s" % proc.returncode)
        time.sleep(2)
    raise RuntimeError("the throwaway service never answered")


def stop(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.terminate()
    proc.wait(timeout=60)


def main():
    scratch = Path(sys.argv[1]).resolve()
    branch = sys.argv[2] if len(sys.argv) > 2 else g(ROOT, "rev-parse", "--abbrev-ref", "HEAD")
    served = scratch / "served"
    if not served.exists():
        subprocess.run(["git", "clone", "-q", "--branch", branch, "--single-branch", str(ROOT), str(served)], check=True)
        g(served, "config", "user.email", "proof@anchor.local")
        g(served, "config", "user.name", "proof")
        src = (served / "anchor_gui.py").read_text(encoding="utf-8")
        assert src.count(PLANT) == 1
        (served / "anchor_gui.py").write_text(src.replace(PLANT, BROKEN), encoding="utf-8")
        g(served, "commit", "-qam", "W3 proof: a planted failure (/api/status raises)")
    port = free_port()
    assert port != 8777
    env = dict(os.environ, ANCHOR_SERVED_ROOT=str(served), ANCHOR_CODE_JOBS_DIR=str(scratch / "jobs"),
               ANCHOR_DATA_DIR=str(served), ANCHOR_PORT=str(port), STEWARD_COCKPIT_FAKE="1",
               ANCHOR_WORKTREE_BASE=str(scratch / "worktrees"))
    env.pop("ANCHOR_TOKEN", None)
    os.environ.update({k: env[k] for k in ("ANCHOR_SERVED_ROOT", "ANCHOR_CODE_JOBS_DIR", "ANCHOR_DATA_DIR")})
    sys.path.insert(0, str(ROOT))
    import anchor_next
    import health_state as hs
    rows, ok = [], True

    def say(row):
        rows.append(row)
        print(json.dumps(row), flush=True)

    proc = start(served, port, env)
    try:
        code, _ = get(port, "/api/status")
        say({"step": "the planted failure, on the running service", "api_status": code})
        r = subprocess.run([sys.executable, str(served / "anchor_healthcheck.py")], cwd=str(served),
                           env=dict(env, ANCHOR_HEALTHCHECK_LIVE_PORT=str(port)), capture_output=True, text=True, timeout=1800)
        path, body = hs.latest()
        red = hs.status_of(body)
        b1 = banner(port)
        say({"step": "the real health check of the running revision", "exit": r.returncode, "status": red,
             "issues": hs.issues_of(body)[:4], "banner": b1[:160]})
        ok = ok and red == "red" and "Health check found issues" in b1
        ip, why = anchor_next.ensure_integration(served)
        assert ip is not None, why
        src = (Path(ip) / "anchor_gui.py").read_text(encoding="utf-8")
        (Path(ip) / "anchor_gui.py").write_text(src.replace(BROKEN, PLANT), encoding="utf-8")
        g(ip, "commit", "-qam", "W3 proof: the fix")
        rec = hs.check_candidate(timeout=1800)
        b2 = banner(port)
        say({"step": "the fix landed on anchor-next; the real candidate check", "status": rec["status"], "why": rec.get("why"),
             "banner": b2[:200]})
        ok = ok and rec["status"] in ("green", "yellow") and "fix verified" in b2 and "live after your restart" in b2
    finally:
        stop(proc)
    act = anchor_next.activate(served)
    say({"step": "activate (service stopped)", "ok": act["ok"], "why": act.get("why")})
    ok = ok and act["ok"]
    proc = start(served, port, env)
    try:
        code, _ = get(port, "/api/status")
        say({"step": "after the restart: the running service", "api_status": code})
        deadline, last = time.time() + 1800, ""
        while time.time() < deadline:
            path, body = hs.latest()
            if path is not None and hs.status_of(body) != "red":
                break
            time.sleep(15)
        path, body = hs.latest()
        b3 = banner(port)
        say({"step": "the owed re-check ran by itself", "status": hs.status_of(body), "target": hs.field(body, "Target"),
             "revision": hs.field(body, "Revision")[:12], "banner": b3[:160] or "(no banner)",
             "running_service_checked": "the running service answers" in body})
        ok = ok and hs.status_of(body) in ("green", "yellow") and not b3 and "the running service answers" in body
    finally:
        stop(proc)
    print(json.dumps({"ok": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
