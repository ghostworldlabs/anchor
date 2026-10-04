"""The steward's hand-off tool (steward-responsiveness R3, 2026-10-04): start, stop or list a CODE JOB for the steward
conversation whose folder is the current directory. A code job is a coder on the best model at full effort in its own
worktree of --repo; it lands its work when clean and wakes this steward with the result.

  python C:/dev/Anchor/tools/steward_code_job.py start --repo C:/dev/Anchor --brief-file brief.md [--check "<cmd>"]
  python C:/dev/Anchor/tools/steward_code_job.py stop [--job <id>]
  python C:/dev/Anchor/tools/steward_code_job.py list
"""
import argparse, json, os, sys, urllib.request
from pathlib import Path

ANCHOR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ANCHOR))


def project_for(cwd):
    import rnd_registry
    here = Path(cwd).resolve()
    best = None
    for p in rnd_registry.list_projects(include_archived=True, include_future=True, include_retired=False):
        fp = p.get("folder_path")
        if not fp:
            continue
        root = Path(fp).resolve()
        if here == root or root in here.parents:
            if best is None or len(str(root)) > len(str(best[1])):
                best = (p.get("id"), root)
    if best is None:
        raise SystemExit("this folder is not inside a registered Anchor project: %s" % here)
    rel = "" if here == best[1] else str(here.relative_to(best[1])).replace("\\", "/")
    return best[0], rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "stop", "list"))
    ap.add_argument("--repo"); ap.add_argument("--brief-file"); ap.add_argument("--brief")
    ap.add_argument("--check", default=""); ap.add_argument("--job")
    ap.add_argument("--port", default=os.environ.get("ANCHOR_PORT", "8777"))
    a = ap.parse_args()
    pid, rel = project_for(os.getcwd())
    body = {"dir": rel, "action": a.action}
    if a.action == "start":
        brief = a.brief or (Path(a.brief_file).read_text(encoding="utf-8") if a.brief_file else "")
        if not (a.repo and brief.strip()):
            raise SystemExit("start needs --repo and --brief-file (or --brief)")
        body.update(repo=a.repo, brief=brief, check=a.check)
    if a.job:
        body["job"] = a.job
    req = urllib.request.Request("http://127.0.0.1:%s/api/steward/code_job?pid=%s" % (a.port, pid),
                                 data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + os.environ.get("ANCHOR_TOKEN", "")})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            print(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(e.read().decode("utf-8", "replace")); sys.exit(1)


if __name__ == "__main__":
    main()
