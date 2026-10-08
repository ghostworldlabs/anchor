"""anchor_next - "landed" and "live" are two places (W1a of the overnight plan of 2026-10-08, John's decision D1 that day:
Anchor-revision cockpits "make changes to the Anchor code ... like you did ... work on a separate branch, isolated and
then once done do a clean merge"; "Land on its own is fine and does not go live until restart").

A code job on Anchor's own repository lands on the integration branch ``anchor-next``, in a checkout the lander owns
(under the code-jobs folder, never C:\\dev\\Anchor). The running checkout - the one the service serves from - is
never a landing target, whatever a caller passes (git_safety.land_locked refuses it). The only way a landed change
reaches John's screen is his restart, in this order (restart_anchor.ps1):

    check (nothing changes)  ->  drain  ->  stop the service  ->  activate  ->  start

``activate`` brings the running branch's own new commits (the stewards' record checkpoints) into ``anchor-next`` in
the lander's checkout, then fast-forwards the running checkout to it. If an uncommitted file in the running checkout
would be overwritten, or the two branches conflict, it stops before anything changes and lists why - never a reset.

Every function never raises; stdlib only. CLI: ``python anchor_next.py status|check|activate``.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

BRANCH = "anchor-next"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(repo, *args, timeout=600, strip=True):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=_NO_WINDOW)
        out = r.stdout or ""
        return r.returncode, (out.strip() if strip else out), (r.stderr or "").strip()
    except Exception as e:
        return 1, "", "git could not run: %s" % e


def _norm(p):
    try:
        return os.path.normcase(str(Path(p).resolve()))
    except Exception:
        return os.path.normcase(str(p))


def served_root():
    """The checkout the Anchor service serves from: this file's own folder in the service (C:\\dev\\Anchor), or
    ANCHOR_SERVED_ROOT (a throwaway repository in tests)."""
    return Path(os.environ.get("ANCHOR_SERVED_ROOT") or Path(__file__).resolve().parent)


def toplevel(path):
    code, out, _ = _git(path, "rev-parse", "--show-toplevel", timeout=60)
    return _norm(out) if code == 0 and out else ""


def common_dir(path):
    """The repository's shared git directory: the same for the running checkout and every worktree of it."""
    code, out, _ = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir", timeout=60)
    return _norm(out) if code == 0 and out else ""


def is_served_checkout(path):
    """True for the running checkout itself (by its working-tree root), never for a worktree of the same repository."""
    top = toplevel(path)
    return bool(top) and top == toplevel(served_root())


def is_served_repo(path):
    """True for the running checkout's repository - the checkout or any worktree of it."""
    c = common_dir(path)
    return bool(c) and c == common_dir(served_root())


def integration_dir(repo):
    base = Path(os.environ.get("ANCHOR_CODE_JOBS_DIR") or os.path.join(os.environ.get("LOCALAPPDATA") or str(Path.home()), "anchor-code-jobs"))
    return base / "integration" / hashlib.sha1(common_dir(repo).encode()).hexdigest()[:16]


def ensure_integration(repo):
    """(path, "") - the lander's own checkout of ``anchor-next`` for this repository, made when missing (the branch
    starts at the running checkout's HEAD) - or (None, why). A checkout that is not on the branch, or holds changes
    nobody committed, is refused, never cleaned: it is the lander's, and something else wrote there."""
    if not common_dir(repo):
        return None, "not a git repository: %s" % repo
    path = integration_dir(repo)
    code, _, _ = _git(repo, "rev-parse", "--verify", "-q", "refs/heads/" + BRANCH, timeout=60)
    if code != 0:
        code, head, err = _git(served_root() if is_served_repo(repo) else repo, "rev-parse", "HEAD", timeout=60)
        if code != 0:
            return None, "could not read the running checkout's HEAD: %s" % err[:200]
        code, _, err = _git(repo, "branch", BRANCH, head, timeout=60)
        if code != 0:
            return None, "could not make the %s branch: %s" % (BRANCH, err[:200])
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "worktree", "prune", timeout=120)
        code, _, err = _git(repo, "worktree", "add", str(path), BRANCH)
        if code != 0:
            return None, "could not make the lander's checkout of %s: %s" % (BRANCH, err[:300])
    code, branch, _ = _git(path, "symbolic-ref", "--short", "-q", "HEAD", timeout=60)
    if code != 0 or branch != BRANCH:
        return None, "the lander's checkout %s is not on %s (it is on %s) - nothing landed" % (path, BRANCH, branch or "a detached HEAD")
    code, dirt, _ = _git(path, "status", "--porcelain", "--untracked-files=all", timeout=120)
    if code != 0:
        return None, "could not read the lander's checkout %s" % path
    if dirt:
        return None, "the lander's checkout %s holds changes nobody committed (%s) - nothing landed" % (
            path, ", ".join(ln[3:] for ln in dirt.splitlines()[:6]))
    return path, ""


def head_of(repo, rev="HEAD"):
    code, out, _ = _git(repo, "rev-parse", "--verify", "-q", rev, timeout=60)
    return out if code == 0 else ""


def waiting(repo=None):
    """The commits landed on anchor-next that the running checkout does not carry yet: [(sha, subject)]."""
    root = Path(repo) if repo else served_root()
    code, out, _ = _git(root, "log", "--format=%H%x09%s", "HEAD.." + BRANCH, timeout=120)
    if code != 0:
        return []
    return [tuple(ln.split("\t", 1)) for ln in out.splitlines() if "\t" in ln]


def _dirty(root):
    """{path: status} for every uncommitted path in the running checkout, untracked included."""
    code, out, _ = _git(root, "-c", "core.quotepath=false", "status", "--porcelain", "-z", "--untracked-files=all", timeout=300, strip=False)
    if code != 0:
        return None
    paths, items = {}, out.split("\0")
    i = 0
    while i < len(items):
        it = items[i]
        if len(it) > 3:
            st, p = it[:2], it[3:]
            paths[p] = st
            if st[0] in "RC":       # a rename carries its source as the next field
                i += 1
                if i < len(items) and items[i]:
                    paths[items[i]] = st
        i += 1
    return paths


def _incoming(root, rev):
    """The paths the fast-forward to ``rev`` would write in the running checkout."""
    code, out, _ = _git(root, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z", "HEAD", rev, timeout=300)
    return None if code != 0 else [p for p in out.split("\0") if p]


def check(repo=None):
    """What the restart would do, changing nothing: {"ok", "waiting", "blockers", "conflicts", "why"}. A blocker is an
    uncommitted path in the running checkout that the fast-forward would write; a conflict is a path where the running
    branch's own new commits and anchor-next disagree."""
    root = Path(repo) if repo else served_root()
    out = {"ok": False, "waiting": waiting(root), "blockers": [], "conflicts": [], "why": ""}
    if not head_of(root, "refs/heads/" + BRANCH):
        out.update(ok=True, why="nothing has landed on %s; nothing to activate" % BRANCH)
        return out
    target = BRANCH
    code, _, _ = _git(root, "merge-base", "--is-ancestor", "HEAD", BRANCH, timeout=60)
    if code != 0:      # the running branch has commits of its own (record checkpoints): they are merged in first
        code, tree, err = _git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", BRANCH, "HEAD", timeout=300)
        if code != 0:
            lines = [ln for ln in tree.splitlines()[1:] if ln.strip()]
            out["conflicts"] = lines or [err[:200] or "the merge could not be computed"]
            out["why"] = "%s and the running branch conflict (%s)" % (BRANCH, ", ".join(out["conflicts"][:8]))
            return out
        target = tree.splitlines()[0] if tree else BRANCH       # the merged TREE: what the running checkout would hold
    incoming = _incoming_tree(root, target) if target != BRANCH else _incoming(root, BRANCH)
    dirty = _dirty(root)
    if incoming is None or dirty is None:
        out["why"] = "git could not compare the running checkout with %s" % BRANCH
        return out
    out["blockers"] = sorted(p for p in incoming if p in dirty)
    if out["blockers"]:
        out["why"] = "uncommitted changes in %s would be overwritten: %s" % (root, ", ".join(out["blockers"][:12]))
        return out
    out["ok"] = True
    return out


def _incoming_tree(root, tree):
    code, out, _ = _git(root, "-c", "core.quotepath=false", "diff-tree", "-r", "--no-renames", "--name-only", "-z", "HEAD", tree, timeout=300)
    return None if code != 0 else [p for p in out.split("\0") if p]


def activate(repo=None):
    """The restart's one change, run while the service is STOPPED: anchor-next takes the running branch's own new
    commits (a merge in the lander's checkout), then the running checkout is fast-forwarded to it. Under the
    repository's commit lock. {"ok", "from", "to", "why", "blockers", "conflicts"}; on any refusal nothing in the
    running checkout changed."""
    import git_safety as _gs
    root = Path(repo) if repo else served_root()
    out = {"ok": False, "from": head_of(root), "to": "", "why": "", "blockers": [], "conflicts": []}
    if not head_of(root, "refs/heads/" + BRANCH):
        out.update(ok=True, to=out["from"], why="nothing has landed on %s" % BRANCH)
        return out
    with _gs.repo_lock(str(root), wait_s=300, who="the restart's activation") as held:
        if not held:
            out["why"] = "the repository's commit lock is busy (a landing in progress); nothing changed"
            return out
        pre = check(root)
        if not pre["ok"]:
            out.update(why=pre["why"], blockers=pre["blockers"], conflicts=pre["conflicts"])
            return out
        ip, why = ensure_integration(root)
        if ip is None:
            out["why"] = why
            return out
        code, _, _ = _git(root, "merge-base", "--is-ancestor", "HEAD", BRANCH, timeout=60)
        if code != 0:
            code, _, err = _git(ip, "-c", "user.name=Anchor lander", "-c", "user.email=lander@anchor.local",
                                "merge", "--no-edit", "-m", "Bring the running branch's own commits into %s" % BRANCH, out["from"])
            if code != 0:
                _git(ip, "merge", "--abort")
                out["why"] = "%s and the running branch would not merge (%s); nothing changed" % (BRANCH, err[:200])
                return out
        code, _, err = _git(root, "merge", "--ff-only", BRANCH)
        if code != 0:
            out["why"] = "the fast-forward was refused (%s); nothing changed" % err[:300]
            return out
        out["to"] = head_of(root)
        out["ok"] = out["to"] == head_of(root, "refs/heads/" + BRANCH)
        if not out["ok"]:
            out["why"] = "the running checkout is at %s, not %s" % (out["to"][:12], BRANCH)
    return out


def _main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "status":
        w = waiting()
        print("%d change(s) landed on %s wait for a restart" % (len(w), BRANCH))
        for sha, subj in w[:20]:
            print("  %s %s" % (sha[:10], subj[:100]))
        return 0
    if cmd == "check":
        r = check()
        print(json.dumps(r, indent=1))
        return 0 if r["ok"] else 3
    if cmd == "activate":
        r = activate()
        print(json.dumps(r, indent=1))
        return 0 if r["ok"] else 3
    print("usage: python anchor_next.py status|check|activate")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
