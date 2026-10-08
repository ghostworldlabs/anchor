"""W1a's one real-engine proof (plan of 2026-10-08): a REAL Claude coder and a REAL ChatGPT coder each land a
tool-recorded change through the anchor-next path, on a throwaway repository standing in for the running Anchor
(ANCHOR_SERVED_ROOT) - never C:\\dev\\Anchor, never :8777. The review is the real cross-family review.

usage: python tools/prove_anchor_next_real.py <scratch folder> [claude|chatgpt ...]
Prints one JSON line per coder and exits 0 only when every coder's change landed on anchor-next, verified, while the
throwaway running checkout kept its revision."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def main():
    scratch = Path(sys.argv[1]).resolve()
    families = sys.argv[2:] or ["claude", "chatgpt"]
    scratch.mkdir(parents=True, exist_ok=True)
    served = scratch / "served"
    if not served.exists():
        served.mkdir()
        g(served, "init", "-q", "-b", "master")
        g(served, "config", "user.email", "proof@anchor.local")
        g(served, "config", "user.name", "proof")
        for fam in ("claude", "chatgpt"):
            (served / ("helper_%s.py" % fam)).write_text("WHO = 'one'\n", encoding="utf-8")
        g(served, "add", "-A")
        g(served, "commit", "-q", "-m", "start")
    os.environ["ANCHOR_SERVED_ROOT"] = str(served)
    os.environ["ANCHOR_CODE_JOBS_DIR"] = str(scratch / "jobs")
    os.environ["ANCHOR_SERVED_CODE_JOBS"] = "1"          # the proof accepts Decision 1 for its throwaway repository
    sys.path.insert(0, str(ROOT))
    import anchor_next
    from steward_cockpit import code_jobs
    from steward_cockpit.steward_routes import get_engine
    ok_all = True
    for fam in families:
        head = g(served, "rev-parse", "HEAD")
        cdir = scratch / ("steward-" + fam)
        cdir.mkdir(exist_ok=True)
        name = "helper_%s.py" % fam
        check = [sys.executable, "-c", "import %s as h; raise SystemExit(0 if h.WHO == 'two' else 5)" % name[:-3]]
        out = code_jobs.start(str(cdir), str(served), "In %s change the line WHO = 'one' to WHO = 'two'. Change nothing else; "
                              "use your file-editing tool, not a shell command." % name, check,
                              engine_factory=lambda wt: get_engine(wt, general=True, tid="1"), coder=fam, actor="the W1a proof")
        if not out.get("ok"):
            print(json.dumps({"family": fam, "started": False, "why": out}))
            ok_all = False
            continue
        job = {}
        for _ in range(1800):
            job = code_jobs.read_jobs(str(cdir)).get(out["job"]) or {}
            if job.get("status") in ("done", "failed", "stopped"):
                break
            time.sleep(1)
        on_next = subprocess.run(["git", "-C", str(served), "show", "anchor-next:" + name], capture_output=True, text=True).stdout.strip()
        row = {"family": fam, "coder": out.get("coder"), "status": job.get("status"), "landed": job.get("landed"),
               "verified_on_next": on_next == "WHO = 'two'", "manifest": job.get("manifest"), "files": job.get("files"),
               "review": {k: (job.get("review") or {}).get(k) for k in ("family", "verdict", "model")},
               "running_head_kept": g(served, "rev-parse", "HEAD") == head,
               "running_file_kept": (served / name).read_text(encoding="utf-8") == "WHO = 'one'\n",
               "land_to": job.get("land_to"), "note": job.get("land_note")}
        print(json.dumps(row), flush=True)
        ok_all = ok_all and bool(row["landed"] and row["verified_on_next"] and row["running_head_kept"] and row["running_file_kept"])
    print(json.dumps({"waiting_for_restart": anchor_next.waiting(served)}))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
