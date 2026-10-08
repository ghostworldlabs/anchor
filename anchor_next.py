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


class ServedUnknown(RuntimeError):
    """The running checkout could not be identified: every caller refuses (fail closed)."""


def served_root():
    """The checkout the Anchor service serves from - ONE answer wherever this module is imported from (ChatGPT W1a
    r1: a job worktree or a development worktree must not take itself for the running Anchor): the MAIN worktree of
    the repository this file belongs to (C:\\dev\\Anchor for every worktree of it), or ANCHOR_SERVED_ROOT (a throwaway
    repository in tests). Raises ServedUnknown when git cannot say."""
    env = os.environ.get("ANCHOR_SERVED_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    code, out, _ = _git(here, "worktree", "list", "--porcelain", timeout=60)
    first = next((ln[len("worktree "):] for ln in out.splitlines() if ln.startswith("worktree ")), "") if code == 0 else ""
    if not first:
        raise ServedUnknown("git could not name the main worktree of %s" % here)
    return Path(first)


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
    """{path: status} for every path in the running checkout an activation must not overwrite: uncommitted, untracked
    and IGNORED (ChatGPT W1a r1: git's default would overwrite an ignored local file). An ignored folder is listed as
    ``dir/``."""
    code, out, _ = _git(root, "-c", "core.quotepath=false", "status", "--porcelain", "-z", "--untracked-files=all",
                        "--ignored=matching", timeout=300, strip=False)
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
    code, out, _ = _git(root, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z", "HEAD", rev,
                        timeout=300, strip=False)
    return None if code != 0 else [p for p in out.split("\0") if p]


def _incoming_tree(root, tree):
    code, out, _ = _git(root, "-c", "core.quotepath=false", "diff-tree", "-r", "--no-renames", "--name-only", "-z", "HEAD",
                        tree, timeout=300, strip=False)
    return None if code != 0 else [p for p in out.split("\0") if p]


def _collides(incoming, dirty):
    """Incoming paths that meet a path the checkout holds: the same path, or one inside the other (a file where a
    folder is, a folder where a file is)."""
    held = [d.rstrip("/") for d in dirty]
    out = set()
    for p in incoming:
        for d in held:
            if p == d or p.startswith(d + "/") or d.startswith(p + "/"):
                out.add(p)
    return sorted(out)


def check(repo=None):
    """What the restart would do, changing nothing: {"ok", "waiting", "blockers", "conflicts", "why", "incoming"}. A
    blocker is a path the fast-forward would write that the running checkout holds uncommitted, untracked or ignored
    (or a folder/file in its way); a conflict is a path where the running branch's own new commits and anchor-next
    disagree."""
    root = Path(repo) if repo else served_root()
    out = {"ok": False, "waiting": waiting(root), "blockers": [], "conflicts": [], "why": "", "incoming": []}
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
    out["incoming"] = incoming
    out["blockers"] = _collides(incoming, dirty)
    if out["blockers"]:
        out["why"] = "local files in %s would be overwritten: %s" % (root, ", ".join(out["blockers"][:12]))
        return out
    out["ok"] = True
    return out


def _blob(root, rev, path):
    code, out, _ = _git(root, "--literal-pathspecs", "rev-parse", "--verify", "-q", "%s:%s" % (rev, path), timeout=60)
    return out if code == 0 else ""


def _on_disk(root, path):
    """The blob id the file on disk would have (git's own filters), "" when absent."""
    if not (Path(root) / path).is_file():
        return ""
    code, out, _ = _git(root, "--literal-pathspecs", "hash-object", "--path=" + path, "--", path, timeout=60)
    return out if code == 0 else "?"


def _restore(root, head, want, incoming, before):
    """After a refused fast-forward (ChatGPT W1a r1-r2): put back ONLY what this activation wrote. For each incoming
    path the disk holds one of three things: HEAD's version (untouched - nothing to do), the version anchor-next would
    have written (git wrote it before it gave up - HEAD's version is put back, or the new file removed), or something
    else (someone else's save - kept as it is, and the result is unverified). Index entries are reset for restored
    paths only, by literal path. Returns what could not be verified ([] = restored and verified)."""
    unverified, restored = [], []
    for path in incoming:
        old, new, now = _blob(root, head, path), _blob(root, want, path), _on_disk(root, path)
        if now == old:
            continue
        if now == new:
            if old:
                code, _, _ = _git(root, "--literal-pathspecs", "checkout", head, "--", path, timeout=120)
                if code != 0:
                    unverified.append(path + " (could not be put back)")
                    continue
            else:
                try:
                    (Path(root) / path).unlink()
                except OSError:
                    unverified.append(path + " (could not be removed)")
                    continue
            restored.append(path)
        else:
            unverified.append(path + " (changed by someone else during the restart - kept as it is)")
    if restored:
        _git(root, "--literal-pathspecs", "reset", "-q", head, "--", *restored, timeout=300)
    after = _dirty(root)
    if after is None:
        return unverified + ["(git could not read the checkout)"]
    drift = sorted(set(after) ^ set(before)) + sorted(p for p in set(after) & set(before) if after[p] != before[p])
    return unverified + [d for d in drift if not any(d == u.split(" (")[0] for u in unverified)]


def activate(repo=None):
    """The restart's one change, run while the service is STOPPED: anchor-next takes the running branch's own new
    commits (a merge in the lander's checkout), then the running checkout is fast-forwarded to it, never overwriting
    an ignored file. Under the repository's commit lock. {"ok", "from", "to", "why", "blockers", "conflicts",
    "unverified"}. On a refusal the checkout is verified to hold what it held at the check; when it cannot be
    verified, ``unverified`` lists why and the service must NOT be started on it (ChatGPT W1a r1: git may write files
    before it fails to move HEAD)."""
    import git_safety as _gs
    root = Path(repo) if repo else served_root()
    out = {"ok": False, "from": head_of(root), "to": "", "why": "", "blockers": [], "conflicts": [], "unverified": []}
    if not head_of(root, "refs/heads/" + BRANCH):
        out.update(ok=True, to=out["from"], why="nothing has landed on %s" % BRANCH)
        return out
    with _gs.repo_lock(str(root), wait_s=300, who="the restart's activation") as held:
        if not held:
            out["why"] = ("the repository's commit lock is held (a landing in progress, or one cut off by the stop - such "
                          "a lock clears itself after an hour); nothing changed")
            return out
        pre = check(root)
        if not pre["ok"]:
            out.update(why=pre["why"], blockers=pre["blockers"], conflicts=pre["conflicts"])
            return out
        before = _dirty(root)
        ip, why = ensure_integration(root)
        if ip is None or before is None:
            out["why"] = why or "git could not read the running checkout"
            return out
        code, _, _ = _git(root, "merge-base", "--is-ancestor", "HEAD", BRANCH, timeout=60)
        if code != 0:
            code, _, err = _git(ip, "-c", "user.name=Anchor lander", "-c", "user.email=lander@anchor.local",
                                "merge", "--no-edit", "-m", "Bring the running branch's own commits into %s" % BRANCH, out["from"])
            if code != 0:
                _git(ip, "merge", "--abort")
                out["why"] = "%s and the running branch would not merge (%s); nothing changed" % (BRANCH, err[:200])
                return out
        incoming = _incoming(root, BRANCH) or []
        want = head_of(root, "refs/heads/" + BRANCH)
        code, _, err = _git(root, "merge", "--ff-only", "--no-overwrite-ignore", BRANCH)
        now = head_of(root)
        if code == 0 and now == want:
            out.update(ok=True, to=now)
            return out
        if now == out["from"]:
            out["unverified"] = _restore(root, out["from"], want, incoming, before)
            out["why"] = "the fast-forward was refused (%s); %s" % (err[:300], "the running checkout was restored and "
                         "verified - nothing changed" if not out["unverified"] else "the running checkout could NOT be "
                         "verified (%s) - do not start it until it is looked at" % ", ".join(out["unverified"][:8]))
        else:
            out["unverified"] = ["HEAD is at %s - neither the old build nor %s" % (now[:12], BRANCH)]
            out["why"] = out["unverified"][0] + " - do not start it until it is looked at"
        out["to"] = now
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
        return 0 if r["ok"] else (4 if r.get("unverified") else 3)     # 4: do not start on this checkout
    print("usage: python anchor_next.py status|check|activate")
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
