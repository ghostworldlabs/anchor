"""W1a's restart proof on a THROWAWAY service (plan of 2026-10-08; ChatGPT review round 1): a clone of the branch plays
the running Anchor on a free port (never 8777). A change lands on anchor-next; a page fetched now and a helper launched
now still get the running revision; the controlled restart (stop -> activate -> start) brings the new one.

usage: python tools/prove_restart_throwaway.py <scratch folder> [branch]   -> JSON lines; exit 0 when every step holds."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARK = ".w1a-proof-marker{color:#123456}"


def page_has_marker(port):
    """A REAL browser page (ChatGPT W1a r2): the Cave opened in Chromium - does its stylesheet carry the marker rule?"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        try:
            pg = b.new_page()
            pg.goto("http://127.0.0.1:%d/high-seat" % port, wait_until="load", timeout=120000)
            return pg.evaluate("""() => Array.from(document.styleSheets).some(s => { try { return Array.from(s.cssRules)
                .some(r => r.selectorText === '.w1a-proof-marker'); } catch (e) { return false; } })""")
        finally:
            b.close()


def g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def get(port, path):
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=15) as r:
        return r.read().decode("utf-8", "replace")


def start(served, port, env):
    proc = subprocess.Popen([sys.executable, str(served / "anchor_gui.py"), "--port", str(port), "--no-browser"],
                            cwd=str(served), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    deadline = time.time() + 400
    while time.time() < deadline:
        try:
            return proc, json.loads(get(port, "/api/version"))["version"]
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("the throwaway service exited %s" % proc.returncode)
            time.sleep(2)
    proc.kill()
    raise RuntimeError("the throwaway service never answered")


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=30)


def main():
    scratch = Path(sys.argv[1]).resolve()
    branch = sys.argv[2] if len(sys.argv) > 2 else g(ROOT, "rev-parse", "--abbrev-ref", "HEAD")
    served = scratch / "served"
    if not served.exists():
        subprocess.run(["git", "clone", "-q", "--branch", branch, "--single-branch", str(ROOT), str(served)], check=True)
        g(served, "config", "user.email", "proof@anchor.local")
        g(served, "config", "user.name", "proof")
    port = free_port()
    assert port != 8777
    env = dict(os.environ, ANCHOR_SERVED_ROOT=str(served), ANCHOR_CODE_JOBS_DIR=str(scratch / "jobs"),
               ANCHOR_DATA_DIR=str(served), ANCHOR_PORT=str(port), STEWARD_COCKPIT_FAKE="1")
    env.pop("ANCHOR_TOKEN", None)
    os.environ.update({k: env[k] for k in ("ANCHOR_SERVED_ROOT", "ANCHOR_CODE_JOBS_DIR")})
    sys.path.insert(0, str(ROOT))
    import anchor_next
    rows, ok = [], True
    proc, build0 = start(served, port, env)
    try:
        rows.append({"step": "running", "build": build0, "marker_in_a_page": page_has_marker(port)})
        ip, why = anchor_next.ensure_integration(served)            # a landing on anchor-next (the landing path is
        assert ip is not None, why                                   # proven by prove_anchor_next_real.py)
        p = Path(ip) / "static" / "high-seat-page.css"
        p.write_text(p.read_text(encoding="utf-8") + "\n" + MARK + "\n", encoding="utf-8")
        g(ip, "commit", "-qam", "W1a proof: a landed change")
        in_page = page_has_marker(port)
        helper = subprocess.run([sys.executable, "-c", "print(open('static/high-seat-page.css', encoding='utf-8').read().count(%r))" % MARK],
                                cwd=str(served), capture_output=True, text=True).stdout.strip()
        r1 = {"step": "landed, before the restart", "marker_served_to_a_new_page": in_page,
              "marker_seen_by_a_new_helper": helper != "0", "waiting": len(anchor_next.waiting(served))}
        rows.append(r1)
        ok = ok and not r1["marker_served_to_a_new_page"] and not r1["marker_seen_by_a_new_helper"] and r1["waiting"] == 1
    finally:
        stop(proc)
    act = anchor_next.activate(served)
    rows.append({"step": "activate (service stopped)", "ok": act["ok"], "why": act.get("why"), "to": act.get("to", "")[:12]})
    ok = ok and act["ok"]
    proc, build2 = start(served, port, env)
    try:
        r3 = {"step": "after the restart", "build": build2, "marker_served": page_has_marker(port),
              "new_build": build2 != build0, "waiting": len(anchor_next.waiting(served))}
        rows.append(r3)
        ok = ok and r3["marker_served"] and r3["new_build"] and r3["waiting"] == 0
    finally:
        stop(proc)
    for r in rows:
        print(json.dumps(r))
    print(json.dumps({"ok": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
