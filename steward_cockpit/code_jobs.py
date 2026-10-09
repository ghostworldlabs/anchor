"""R3 of the steward-responsiveness plan (Ecgberht/planning/steward-responsiveness-2026-10-04, John 2026-10-04: "It is
fine to have the Cave Steward and the Star Steward both hand off to other agents ... but I don't want to have it not
use the best model at the fullest effort for hard problems").

A steward hands real work to a CODE JOB and stays free to talk. A code job is a workbench-terminal engine (the same
bridges, the same latest-model / highest-effort policy as every steward) running in its own git worktree of the
repository that owns the files, given the steward's brief as its first message. When its turn ends the job is
checked (the brief's check command, when one was given), committed on its branch, and landed into the repository
when that is clean; then the steward that commissioned it is woken with the result and reports it to John.

One writer: while a job runs on a repository, the steward does not write there (the engine's tool guard reads
``active_repos``). His "stop" kills the job; a change he asks for is held for the result turn, never piped into the
running job. One coder by default; a swarm only when his brief asks for one (the coder may fan out itself).

Records: ``<steward folder>/.ecgberht/code-jobs.json`` {job_id: {...}}. Never raises to a caller; every failure is a
record field and a line to the steward.

Execution minimum item 3 (PROPOSAL v1.1, 2026-10-07) - one commit: preservation, safe checks, the Foreman/Crucible
hold, and the review gate.
- HOLD: a code job is always a coder; Foreman never starts from here (nor Crucible) until John lifts the hold after a
  separate best-in-class review (ANCHOR_FOREMAN_CRUCIBLE_HOLD=0). This claims Anchor's managed entries only.
- CHECKS: an argument list, or the full command text run from a temp script - never cut, never re-quoted - in the
  job's OWN tree; the live tree is touched only by the landing itself.
- MANIFEST: only the paths the coder's tools wrote are staged and placed (no ``git add -A``); any other changed path
  blocks the landing and the worktree is KEPT with everything in it, listed; foreman.config.json never lands; after
  a landing every placed file is verified in the repository before the worktree goes.
- REVIEW GATE: ``land`` refuses unless a review record (tools/steward_review.mjs, the trio's runAgent review role)
  names a family other than the author's AND the exact candidate tree; an error, the author's own family, a missing
  family or a changed tree keeps the worktree and says why. A change after review (integrating newer commits) gets a
  review of that delta only.
- SEATS: the coder's family is the job's choice, else the dashboard's Coder seat; a family known to be exhausted is
  not called again (the other family may run); model preferences are never written.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

JOBS_FILE = ".ecgberht/code-jobs.json"
CHECK_TIMEOUT_S = 900
_LOCK = threading.RLock()


def jobs_base():
    """Where the worktrees live: outside every repository, beside the Anchor checkout under C:\\dev (backed up)."""
    import paths as _paths      # under C:\dev, beside the checkout (John, 2026-10-08: C:\dev is backed up)
    root = _paths.code_jobs_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _git(repo, *args, timeout=120):
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, "", "git %s timed out after %ss" % (args[0] if args else "", timeout)
    except Exception as e:
        return 1, "", "git could not run: %s" % e
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def _git_raw(repo, *args, timeout=600):
    """git with its stdout exactly as written (no strip): porcelain status columns start with a space."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
    except Exception as e:
        return 1, "", str(e)
    return r.returncode, r.stdout or "", (r.stderr or "").strip()


def porcelain_paths(repo):
    """Every changed or untracked path of ``repo`` (no renames), parsed from NUL-delimited porcelain v1; None on
    failure."""
    code, out, _ = _git_raw(repo, "-c", "core.quotepath=false", "status", "--porcelain=v1", "-z", "--untracked-files=all",
                            "--no-renames")
    if code != 0:
        return None
    return [rec[3:] for rec in out.split("\0") if len(rec) > 3]


def _path(cdir):
    return Path(cdir) / JOBS_FILE


def read_jobs(cdir):
    try:
        d = json.loads(_path(cdir).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _write_job(cdir, job):
    with _LOCK:
        d = read_jobs(cdir)
        d[job["id"]] = job
        p = _path(cdir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(p))


LIVE = ("running", "finishing")


def _busy_path():
    return jobs_base() / "busy.json"


def _busy_read():
    try:
        d = json.loads(_busy_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _busy_write(d):
    p = _busy_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(p))


def _norm(path):
    return os.path.normcase(str(Path(path).resolve()))


def busy_repos():
    """Every repository a live code job owns, across all stewards: {repo: {"job", "cdir"}} (stale entries dropped)."""
    out = {}
    for repo, info in _busy_read().items():
        j = read_jobs(info.get("cdir", "")).get(info.get("job", ""), {})
        if j.get("status") in LIVE:
            out[repo] = info
    return out


def active_repos(cdir=None):
    """The repositories live code jobs own (all stewards: one writer per repository)."""
    return list(busy_repos())


def inside(path, repo):
    """True when ``path`` is ``repo`` or under it, on a path boundary (C:\\dev\\Anchor never matches C:\\dev\\Anchor-x)."""
    p, r = _norm(path), _norm(repo)
    return p == r or p.startswith(r.rstrip(os.sep) + os.sep)


def _transition(cdir, job_id, expect, **updates):
    """One locked status change: applies ``updates`` only when the job's status is in ``expect``; returns the job
    after the change, or None when it was not in that state (finish and stop never both win)."""
    with _LOCK:
        d = read_jobs(cdir)
        j = d.get(job_id)
        if not j or j.get("status") not in expect:
            return None
        j.update(updates)
        d[job_id] = j
        p = _path(cdir)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(p))
        if j.get("status") not in LIVE:
            b = _busy_read()
            if b.get(_norm(j["repo"]), {}).get("job") == job_id:
                b.pop(_norm(j["repo"]), None)
                _busy_write(b)
        return dict(j)


def _repo_root(path):
    code, out, _ = _git(path, "rev-parse", "--show-toplevel")
    return Path(out).resolve() if code == 0 and out else None


# ── The Foreman/Crucible hold (execution minimum item 3) ────────────────────────────────────────────────────────────
def foreman_crucible_held():
    """True while Foreman and Crucible may not start from Anchor's managed entries (John's binding, 2026-10-07:
    off until a separate Gandalf + researchPrime best-in-class review). ANCHOR_FOREMAN_CRUCIBLE_HOLD=0 lifts it."""
    return os.environ.get("ANCHOR_FOREMAN_CRUCIBLE_HOLD", "1").strip() != "0"


HOLD_REASON = ("Foreman and Crucible are on hold in Anchor until their best-in-class review (John, 2026-10-07); "
               "a code job is a coder in its own worktree, and Anchor did not start Foreman or Crucible")


# ── Seats: the coder's family, never the model preferences ─────────────────────────────────────────────────────────
FAMILIES = ("claude", "chatgpt", "grok", "gemini")
CLI_FAMILY = {"claude": "claude", "codex": "chatgpt", "chatgpt": "chatgpt", "grok": "grok", "gemini": "gemini"}
EXHAUSTED_FOR_S = 5 * 3600
_LIMIT_WORDS = re.compile(r"usage limit|rate limit|quota|session limit|limit reached|too many requests|exhausted", re.I)


def _exhausted_path():
    return jobs_base() / "exhausted.json"


def exhausted_families():
    """Families whose last code-job turn hit a usage limit within EXHAUSTED_FOR_S - not called again until then."""
    try:
        d = json.loads(_exhausted_path().read_text(encoding="utf-8"))
    except Exception:
        return set()
    now = time.time()
    return {f for f, until in (d.items() if isinstance(d, dict) else []) if isinstance(until, (int, float)) and until > now}


def mark_exhausted(family):
    if family not in FAMILIES:
        return
    try:
        d = json.loads(_exhausted_path().read_text(encoding="utf-8")) if _exhausted_path().is_file() else {}
    except Exception:
        d = {}
    d[family] = time.time() + EXHAUSTED_FOR_S
    tmp = _exhausted_path().with_suffix(".json.%s.tmp" % uuid.uuid4().hex[:6])
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(str(tmp), str(_exhausted_path()))


# consensus C3: a coder family must report its completed file writes (the manifest) - Claude and Codex do; the Grok
# and Gemini bridges do not yet, so their jobs could never land. Refused, honestly, until their bridges report writes.
CODE_JOB_FAMILIES = ("claude", "chatgpt")
NO_MANIFEST = "%s cannot run a code job yet: its bridge does not report which files it wrote, so its work could never land"


def choose_coder(requested=""):
    """(family, None) or (None, reason): the job's own choice, else the Coder seat, else the Terminal seat - never a
    family known to be exhausted. Reads the dashboard settings; writes nothing."""
    try:
        import anchor_settings
        settings = anchor_settings.get_launch_settings()
    except Exception as exc:
        return None, "the dashboard settings could not be read: %s" % exc
    tired = exhausted_families()
    asked = str(requested or "").strip().lower()
    if asked:
        if asked not in FAMILIES:
            return None, "unknown coder family %r" % asked
        if asked not in CODE_JOB_FAMILIES:
            return None, NO_MANIFEST % asked
        if asked in tired:
            return None, "%s hit its usage limit recently; choose another family or wait" % asked
        return asked, None
    for fam in (settings.get("coding_family"), settings.get("default_cli"), settings.get("review_family")):
        fam = str(fam or "").lower()
        if fam in CODE_JOB_FAMILIES and fam not in tired:
            return fam, None
    return None, "no configured code-job family (Claude or ChatGPT) is available now"


# ── Checks: an argument list or a temp script; never cut, never re-quoted ──────────────────────────────────────────
CHECK_MAX = 20000


def normalize_check(check):
    """(check, None) or (None, reason). A list is an argument list (no shell); a string is the full command text."""
    if isinstance(check, (list, tuple)):
        argv = [str(a) for a in check]
        if not argv or not all(a.strip() for a in argv):
            return None, "a check given as a list needs a program and its arguments"
        return argv, None
    text = str(check or "")
    if len(text) > CHECK_MAX:
        return None, "the check is %d characters - put it in a script file in the repository" % len(text)
    return text, None


def run_check(job, tree):
    """Run the job's check in ``tree`` (the job's own worktree). (ok, output tail). A string runs from a temp script
    so its quotes and length reach the shell unchanged; a list runs with no shell at all."""
    check = job.get("check")
    if not check:
        return None, ""
    script = None
    try:
        if isinstance(check, list):
            argv = check
        else:
            d = jobs_base() / "checks"
            d.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                script = d / ("%s-%s.cmd" % (job["id"], uuid.uuid4().hex[:6]))
                script.write_text("@echo off\r\n" + check.replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n",
                                  encoding="utf-8")
                argv = ["cmd.exe", "/d", "/c", "call", str(script)]
            else:
                script = d / ("%s-%s.sh" % (job["id"], uuid.uuid4().hex[:6]))
                script.write_text(check + "\n", encoding="utf-8")
                argv = ["sh", str(script)]
        r = subprocess.run(argv, cwd=str(tree), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=CHECK_TIMEOUT_S, shell=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        return r.returncode == 0, ((r.stdout or "") + (r.stderr or ""))[-1200:]
    except subprocess.TimeoutExpired:
        return False, "the check ran longer than %ss" % CHECK_TIMEOUT_S
    except Exception as e:
        return False, "the check did not run: %s" % e
    finally:
        if script is not None:
            try:
                script.unlink()
            except OSError:
                pass


# ── The manifest: what the coder's tools wrote ─────────────────────────────────────────────────────────────────────
NEVER_LAND = {"foreman.config.json"}


def never_lands(path):
    """foreman.config.json never lands - in any letter case, at any depth (Windows opens FOREMAN.CONFIG.JSON too)."""
    return str(path).replace(chr(92), "/").rsplit("/", 1)[-1].casefold() in NEVER_LAND


def _rel_in(tree, raw):
    try:
        root = Path(tree).resolve()
        fp = Path(raw)
        fp = (fp if fp.is_absolute() else root / fp).resolve()
        return fp.relative_to(root).as_posix()
    except (OSError, ValueError):
        return None


def manifest_of(engine, tree):
    """The coder's own COMPLETED writes - a Write/Edit whose tool result came back without an error, a Codex
    file_change that completed - relative to its worktree. An attempted write that failed is not in it."""
    out = []
    for raw in list(getattr(engine, "written_ok", None) or []):
        rel = _rel_in(tree, raw)
        if rel and rel not in out:
            out.append(rel)
    return out


def authors_of(engine):
    """Every model family that actually served this coder (its provider can fall back mid-job), as family names."""
    used = set(getattr(engine, "families_used", None) or ()) | {str(getattr(engine, "cli", "") or "")}
    return sorted({CLI_FAMILY.get(c.lower(), c.lower()) for c in used if c})


def _landed_path():
    return jobs_base() / "landed-commits.json"


def record_landed_commit(commit):
    """Remember a commit a reviewed, verified code-job landing made (the only commits the served-code audit exempts)."""
    with _LOCK:
        try:
            d = json.loads(_landed_path().read_text(encoding="utf-8")) if _landed_path().is_file() else []
        except Exception:
            d = []
        if commit not in d:
            d = (d + [commit])[-2000:]
            tmp = _landed_path().with_suffix(".json.%s.tmp" % uuid.uuid4().hex[:6])
            tmp.write_text(json.dumps(d), encoding="utf-8")
            os.replace(str(tmp), str(_landed_path()))


def landed_commits():
    """Every verified landing's commit - the ledger here, and the one kept in the old %LOCALAPPDATA% folder."""
    out = set()
    import paths as _paths
    for p in (_landed_path(), _paths.legacy_code_jobs_dir() / "landed-commits.json"):
        try:
            out |= set(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


APP_CODE_EXT = (".py", ".js", ".mjs", ".css", ".ps1")


def is_app_file(path):
    """Application code of a repository: code files anywhere, HTML only in application folders (static/, templates/,
    ...). The ONE classifier the steward guard and the served-code audit share."""
    p = str(path).replace(chr(92), "/").lower()
    if p.endswith(APP_CODE_EXT):
        return True
    if p.endswith((".html", ".htm")):
        return bool(set(p.split("/")[:-1]) & APP_FOLDERS)
    return False


_RECORDS = re.compile(r"(?:^|/)\.ecgberht/|(?:^|/)\.anchor/|(?:^|/)(?:ECGBERHT|DELIVERABLES|STATUS[^/]*)\.md$"
                      r"|(?:^|/)(?:strip|roadmap)\.json$|(?:^|/)journal/|(?:^|/)code-job-outputs/", re.I)


def watched(path):
    """What the source audit protects (consensus C1): application code and agent-instruction files - never a
    cockpit's runtime records (its .ecgberht, strip, roadmap, register, journal), which change during every job when
    the cockpit lives inside the repository."""
    p = str(path).replace(chr(92), "/")
    try:
        import git_safety as _gs
        if _gs.is_runtime_path(p):
            return False
    except Exception:
        pass
    if _RECORDS.search(p):
        return False
    return is_app_file(p) or p.rsplit("/", 1)[-1].casefold() in INSTRUCTION_FILES


def dirty_snapshot(repo):
    """{path: content hash} of the source repository's changed or untracked WATCHED files right now (application code
    and instruction files; never runtime records). Hashed in one batch. Compared at finish/stop with the commits made
    since the job began. None when git cannot say."""
    paths = porcelain_paths(repo)
    if paths is None:
        return None
    paths = [p for p in paths if watched(p)]
    snap, present = {}, []
    for path in paths:
        if (Path(repo) / path).is_file():
            present.append(path)
        else:
            snap[path] = "(gone)"
    if present:
        try:
            r = subprocess.run(["git", "-C", str(repo), "hash-object", "--stdin-paths"], input="\n".join(present) + "\n",
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
            hashes = r.stdout.split() if r.returncode == 0 else []
        except Exception:
            hashes = []
        if len(hashes) != len(present):                  # one unreadable file must not spoil the batch: per path
            snap.update(dirty_snapshot_paths(repo, present))
        else:
            snap.update(dict(zip(present, hashes)))
    return snap


MAX_OUTPUTS = 80      # W1 (2026-10-09): exact paths named before the job starts; more is refused, never cut short


def _runtime(path):
    """A steward's runtime record (git_safety.is_runtime_path - the one rule): it never refuses a job and never enters
    its commit; a dirty one keeps the worktree. Fails closed (not runtime) when git_safety cannot be read."""
    try:
        import git_safety as _gs
        return bool(_gs.is_runtime_path(str(path).replace(" (ignored by git)", "").replace(chr(92), "/")))
    except Exception:
        return False


def _not_runtime(paths):
    return [p for p in paths if not _runtime(p)]


def declare_hint(path):
    """The declaration line that would admit ``path`` (a refusal is actionable, W1) - only when declared_outputs
    would accept it; otherwise why it cannot be declared."""
    p = str(path).replace(" (ignored by git)", "")
    ok, why = declared_outputs([p])
    return ("declare it: --output %s" % ok[0]) if ok else ("cannot be declared: %s" % why)


def refusal_detail(paths, limit=12):
    shown = ["%s [%s]" % (p, declare_hint(p)) for p in paths[:limit]]
    return "; ".join(shown) + (" ..." if len(paths) > limit else "")


_BOOKKEEPING = re.compile(r"^(?:\.anchor/|\.ecgberht/|\.foreman-job/|\.foreman/|_foreman-status\.log$|foreman-checkpoint\.json$)"
                          r"|(?:^|/)__pycache__/|(?:^|/)\.pytest_cache/|\.pyc$")


def ignored_outputs(tree):
    """Files git ignores in the worktree that are not the job's own bookkeeping - a coder's or a check's outputs
    (a fresh worktree has none), which removing the worktree would destroy."""
    code, out, _ = _git_raw(tree, "-c", "core.quotepath=false", "ls-files", "--others", "--ignored", "--exclude-standard", "-z",
                        timeout=600)
    if code != 0:
        return ["(git could not list ignored files)"]
    return [p for p in out.split("\0") if p.strip() and not _BOOKKEEPING.search(p.replace(chr(92), "/"))]


def changed_paths(tree, base):
    """Every path that differs from ``base`` in the worktree: committed, staged, unstaged and untracked (ignored
    files excepted). None when git cannot say."""
    code, out, _ = _git_raw(tree, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z", base, timeout=600)
    code2, untracked, _ = _git_raw(tree, "-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard", "-z",
                               timeout=600)
    if code != 0 or code2 != 0:
        return None
    names = [n for n in (out + "\0" + untracked).split("\0") if n.strip()]
    return sorted(set(names))


# ── The review gate ────────────────────────────────────────────────────────────────────────────────────────────────
REVIEW_TIMEOUT_S = int(os.environ.get("ANCHOR_CODE_REVIEW_TIMEOUT_S", "2400"))
DOCUMENT_EXTS = {".md", ".markdown", ".pdf", ".ics", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg"}
# instruction files steer agents - they are never "just documents"
INSTRUCTION_FILES = {"claude.md", "agents.md", "skill.md", "gemini.md", "copilot-instructions.md"}


APP_FOLDERS = {"static", "templates", "template", "public", "src", "app", "steward_cockpit", "vendor", "lib", "shell",
               "foundry-gui", "dist", "foundry-display"}   # consensus C5: served application HTML is code


def is_document(path):
    """A document never enters the review gate. HTML counts as one only outside application folders (a page in
    static/ or templates/ is application code)."""
    parts = str(path).replace(chr(92), "/").casefold().split("/")
    name = parts[-1]
    ext = os.path.splitext(name)[1]
    if name in INSTRUCTION_FILES:
        return False
    if ext in (".html", ".htm"):
        return not (set(parts[:-1]) & APP_FOLDERS)
    return ext in DOCUMENT_EXTS
REVIEW_TOOL = Path(__file__).resolve().parents[1] / "tools" / "steward_review.mjs"


def run_review(job, tree, head, delta_from=""):
    """One review of the candidate ``head`` in ``tree`` by a family other than the author's. Returns the review
    record; ``record["ok"]`` is False on ANY failure. ANCHOR_REVIEW_CMD (a JSON argv) is the test seam."""
    brief = jobs_base() / "checks" / ("%s-brief.md" % job["id"])
    try:
        brief.parent.mkdir(parents=True, exist_ok=True)
        brief.write_text(job.get("brief") or "", encoding="utf-8")
    except OSError:
        pass
    seam = os.environ.get("ANCHOR_REVIEW_CMD")
    try:
        cmd = json.loads(seam) if seam else ["node", str(REVIEW_TOOL)]
    except ValueError:
        return {"ok": False, "error": "ANCHOR_REVIEW_CMD is not a JSON argument list"}
    argv = cmd + ["--repo", str(tree), "--base", job["base"], "--head", head,
                  "--author-family", ",".join(job.get("authors") or [job.get("coder_family") or ""]), "--brief-file", str(brief),
                  "--exhausted", ",".join(sorted(exhausted_families()))]
    if delta_from:
        argv += ["--delta-from", delta_from]
    try:
        r = subprocess.run(argv, cwd=str(tree), capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=REVIEW_TIMEOUT_S, shell=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "the review ran longer than %ss" % REVIEW_TIMEOUT_S}
    except Exception as e:
        return {"ok": False, "error": "the review could not run: %s" % e}
    lines = [ln for ln in (r.stdout or "").splitlines() if ln.strip().startswith("{")]
    try:
        rec = json.loads(lines[-1]) if lines else None
    except ValueError:
        rec = None
    if not isinstance(rec, dict):
        return {"ok": False, "error": "the review gave no record (exit %s): %s" % (r.returncode, (r.stderr or "")[-300:])}
    rec["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rec["delta_from"] = delta_from or None
    if not rec.get("ok") and rec.get("family") and _LIMIT_WORDS.search(str(rec.get("error") or "")):
        mark_exhausted(str(rec["family"]).lower())        # the reviewer's family is not asked again for a while
    return rec


def review_blocks(job, rec, tree, head):
    """The reason this review does NOT allow landing, or "" when it does. Fail closed on every doubt."""
    if not isinstance(rec, dict) or not rec.get("ok"):
        return "the review failed: %s" % ((rec or {}).get("error") or "no record")
    fam = str(rec.get("family") or "").lower()
    if not fam:
        return "the review record names no family"
    authors = [a for a in (job.get("authors") or []) if a]
    if not authors:
        return "the job has no record of which model family wrote it"
    if fam in authors or fam == str(job.get("coder_family") or "").lower():
        return "the review was done by the author's own family (%s)" % fam
    blocking = [f for f in (rec.get("findings") or []) if isinstance(f, dict) and f.get("severity") in ("BLOCKER", "MAJOR")]
    if rec.get("verdict") == "PASS" and blocking:
        return "the review says PASS but lists a %s finding: %s" % (blocking[0].get("severity"), str(blocking[0].get("issue"))[:160])
    code, tree_hash, _ = _git(tree, "rev-parse", head + "^{tree}")
    if code != 0 or not tree_hash or rec.get("tree_hash") != tree_hash:
        return "the reviewed tree is not the candidate (reviewed %s, candidate %s)" % (rec.get("tree_hash"), tree_hash)
    if rec.get("verdict") != "PASS":
        found = "; ".join("%s %s" % (f.get("severity", "?"), str(f.get("issue", ""))[:160])
                          for f in (rec.get("findings") or [])[:4] if isinstance(f, dict))
        return "the %s reviewer did not pass it: %s" % (fam, found or "no findings given")
    return ""


def _kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            proc.kill()
    except Exception:
        pass


def declared_outputs(outputs):
    """([relative paths], None) or (None, why): the files a job names up front as its outputs (W2, 2026-10-08) - a
    plain path inside the repository, never a runtime record, never foreman.config.json, at most MAX_OUTPUTS (80).
    The whole declaration is validated; it is never cut short (W1, 2026-10-09)."""
    out = []
    for raw in list(outputs or []):
        p = str(raw or "").strip().replace(chr(92), "/")
        if not p:
            continue
        if p.startswith("/") or re.match(r"^[A-Za-z]:", p) or ".." in p.split("/") or "*" in p or "?" in p:
            return None, "a declared output is a plain path inside the repository: %s" % p
        import posixpath
        p = posixpath.normpath(p)          # normalized FIRST, then every exclusion applies to this exact path (ChatGPT r3)
        if p in (".", "") or p.startswith("../"):
            return None, "a declared output is a plain path inside the repository: %s" % raw
        try:
            import git_safety as _gs
            if _gs.is_runtime_path(p) or never_lands(p) or _RECORDS.search(p):
                return None, ("a declared output may not be a runtime record, a cockpit record (ECGBERHT, DELIVERABLES, "
                              "STATUS, strip, roadmap, journal) or foreman.config.json: %s" % p)
        except Exception:
            return None, "the declared outputs could not be checked"
        if p not in out:
            out.append(p)
    if len(out) > MAX_OUTPUTS:
        return None, "at most %d declared outputs (%d named)" % (MAX_OUTPUTS, len(out))
    return out, None


def start(cdir, repo, brief, check="", engine_factory=None, steward="", coder="", actor="", skill="", outputs=None):
    """Start a code job for the steward at ``cdir``: a worktree of ``repo`` and a coder engine given ``brief``.
    ``engine_factory(worktree) -> engine`` is the seam (steward_routes passes get_engine). ``coder`` is this job's
    family choice (else the Coder seat); ``check`` is an argument list or the full command text."""
    brief = str(brief or "").strip()
    if not brief:
        return {"ok": False, "error": "a code job needs a brief"}
    check, why = normalize_check(check)
    if why:
        return {"ok": False, "error": why}
    family, why = choose_coder(coder)
    if why:
        return {"ok": False, "error": why}
    outputs, why = declared_outputs(outputs)
    if why:
        return {"ok": False, "error": why}
    root = _repo_root(repo or "")
    if root is None:
        return {"ok": False, "error": "not a git repository: %s" % repo}
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    branch = "steward-job-" + job_id
    wt = jobs_base() / job_id
    with _LOCK:      # the check, the worktree and the busy entry: one step, so two stewards never both start
        if _norm(root) in busy_repos():
            return {"ok": False, "error": "a code job is already running on %s; one writer at a time" % root}
        # W1a (2026-10-08): a job on Anchor's own repository starts from anchor-next and lands there, in the lander's
        # own checkout - never in the running Anchor; John's restart makes it live
        land_to = ""
        try:
            import anchor_next
            if anchor_next.is_served_repo(root) and os.environ.get("ANCHOR_SERVED_CODE_JOBS") != "1":
                # John's Decision 1 (night report, 2026-10-08): a coder's SHELL has no OS boundary - it could write the
                # running Anchor before the audit refuses the landing. Code jobs on Anchor's own repository run only
                # once he accepts that (ANCHOR_SERVED_CODE_JOBS=1); until then none start (Grok's final review)
                return {"ok": False, "error": "no job started: code jobs on Anchor's own code are off until John turns them "
                        "on (ANCHOR_SERVED_CODE_JOBS=1) - a coder's shell cannot yet be held to its worktree"}
            if anchor_next.is_served_repo(root) and family != "claude" and os.environ.get("ANCHOR_UNCONFINED_CODERS") != "1":
                # W1a (ChatGPT r2): a job's worktree must be its only writable directory. Claude's coder is held there
                # by the fence guard; a ChatGPT/Grok/Gemini coder has no boundary under the service (the Codex sandbox
                # cannot start a shell there) - so Anchor's own code goes to a Claude coder (John's choice in the
                # morning report; ANCHOR_UNCONFINED_CODERS=1 lifts it)
                return {"ok": False, "error": "no job started: a %s coder cannot be confined to its worktree under the "
                        "service yet, so a change to Anchor's own code uses a Claude coder (--coder claude)" % family}
            if anchor_next.is_served_repo(root):
                ip, why = anchor_next.ensure_integration(root)
                if ip is None:
                    return {"ok": False, "error": "no job started: %s" % why}
                land_to = str(ip)
        except Exception as e:
            return {"ok": False, "error": "no job started: could not prepare anchor-next (%s)" % e}
        code, base, err = _git(land_to or root, "rev-parse", "HEAD")
        if code != 0:
            return {"ok": False, "error": "the repository has no commit to start from: %s" % err}
        code, _, err = _git(root, "worktree", "add", "-b", branch, str(wt), base, timeout=600)
        if code != 0:
            return {"ok": False, "error": "could not make the worktree: %s" % err[:300]}
        served_dirt = dirty_snapshot(root)
        if served_dirt is None:
            return {"ok": False, "error": "could not record the repository's own changes before starting; no job started"}
        job = {"id": job_id, "repo": str(root), "branch": branch, "worktree": str(wt), "base": base, "brief": brief[:8000],
               "repo_dirt": served_dirt,
               "check": check, "status": "running", "started": time.strftime("%Y-%m-%d %H:%M:%S"), "land_to": land_to, "outputs": outputs,
               "steward_dir": str(cdir), "steward": steward, "worker": "coder", "coder_family": family,
               "started_by": str(actor or "the steward")}
        # 2026-10-08 (John: "identify the actual skill being used"): a job that runs a skill says which, so the status
        # names it and its finish time is reckoned from that skill's own history - never from other coding jobs
        label = re.sub(r"[^A-Za-z0-9 ._-]", "", str(skill or "")).strip()[:40]
        if label:
            job["skill"] = label
        _write_job(cdir, job)
        b = _busy_read()
        b[_norm(root)] = {"job": job_id, "cdir": str(cdir)}
        _busy_write(b)
    # the coder's own folder record: one workbench terminal
    terms = Path(wt) / ".anchor" / "steward-terms.json"
    terms.parent.mkdir(parents=True, exist_ok=True)
    terms.write_text(json.dumps({"1": {"label": "code job " + job_id, "created": job["started"], "archived": False}}), encoding="utf-8")
    _exclude_local(wt)
    try:
        eng = engine_factory(str(wt)) if engine_factory else None
        if eng is None:
            raise RuntimeError("no engine slot for the coder")
        eng.code_job = {"cdir": str(cdir), "id": job_id, "repo": str(root)}
        try:   # this job's family, for this engine only (the dashboard's preferences are never written)
            import anchor_settings
            eng.policy_override = {"family": family, "revision": anchor_settings.get_launch_settings()["settings_revision"],
                                   "reason": "code_job_choice"}
        except Exception:
            pass
        eng.on_turn_done = lambda result: threading.Thread(
            target=finish, args=(cdir, job_id, dict(result or {}, manifest=manifest_of(eng, wt), authors=authors_of(eng),
                                                    failed_over=list((getattr(eng, "policy_override", None) or {}).get("failed_families") or []))),
            name="code-job-" + job_id, daemon=True).start()
        ok, why = eng.wake(fresh=True, seed=coder_brief(job))
        if not ok:
            raise RuntimeError(why)
        try:   # 2026-10-08: the status names the model and effort the coder was asked for, not only its family
            sel = getattr(eng, "model_selection", None) or {}
            asked = " ".join(str(x) for x in (sel.get("model"), sel.get("effort")) if x)
            if asked:
                _transition(cdir, job_id, LIVE, coder_model=asked[:60])
        except Exception:
            pass
    except Exception as e:
        j = _transition(cdir, job_id, LIVE, status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"), error="the coder could not start: %s" % e)
        _cleanup(j or job, keep_branch=False)
        return {"ok": False, "error": "the coder could not start: %s" % e, "job": job_id}
    return {"ok": True, "job": job_id, "branch": branch, "worktree": str(wt), "worker": "coder", "coder": family}


def _exclude_local(wt):
    """The coder's .anchor/.ecgberht bookkeeping never lands in the repository."""
    try:
        code, gitdir, _ = _git(wt, "rev-parse", "--git-common-dir")
        if code == 0:
            ex = Path(wt, gitdir) if not os.path.isabs(gitdir) else Path(gitdir)
            f = ex / "info" / "exclude"
            f.parent.mkdir(parents=True, exist_ok=True)
            cur = f.read_text(encoding="utf-8") if f.exists() else ""
            add = [x for x in ("/.anchor/", "/.ecgberht/", "/.foreman-job/", "/.foreman/",
                               "/_foreman-status.log", "/foreman-checkpoint.json", "__pycache__/", ".pytest_cache/",
                               "*.pyc") if x not in cur]
            if add:
                f.write_text(cur.rstrip("\n") + ("\n" if cur else "") + "\n".join(add) + "\n", encoding="utf-8")
    except Exception:
        pass


def coder_brief(job):
    return ("You are a CODE JOB commissioned by John's steward. Work only in this folder, a git worktree of "
            "%s on branch %s. Do the work in the brief below completely, at your best; you may use sub-agents if "
            "the brief asks for a swarm. Do not ask questions back: if something is genuinely John's to decide, "
            "stop and say so in your final message. Do not write plan pages, reports, journals or status files; "
            "edit the code with your file tools (only the files your tools write will land; anything else that "
            "changes keeps the work from landing), run the checks that apply, and end with a plain summary of what "
            "you changed and how you checked it. Do not commit; the job commits your files, a reviewer of another "
            "model family reviews them, and they land only if that review passes.%s%s\n\nBRIEF:\n%s") % (
        job["repo"], job["branch"], ("\nNamed up front as this job's outputs (they may land even when a command you ran "
                                     "wrote them, not your file tools): " + ", ".join(job["outputs"])) if job.get("outputs") else "",
        ("\nThe job will run this check after you finish: " + (
            " ".join(job["check"]) if isinstance(job["check"], list) else job["check"])) if job.get("check") else "", job["brief"])


def finish(cdir, job_id, result):
    """The coder's turn ended: check, commit, land when clean, wake the steward with the result. Never raises.
    The job is claimed first (running -> finishing): a stop that already won leaves it alone."""
    job = _transition(cdir, job_id, ("running",), status="finishing", finishing_at=time.time())
    if not job:
        return
    try:
        _finish(cdir, job_id, job, result)
    except Exception as e:      # never leave the repository owned by a finish that died
        j = _transition(cdir, job_id, ("finishing",), status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                        error="the job's finish failed: %s" % e, land_note="not landed; the work waits on branch %s" % job["branch"])
        if j:
            _report(cdir, j)


def _finish(cdir, job_id, job, result):
    wt, repo = job["worktree"], job["repo"]
    summary = str((result or {}).get("text") or "")[-1500:]
    err = str((result or {}).get("error") or "")
    if err and _LIMIT_WORDS.search(err):
        mark_exhausted(job.get("coder_family"))          # not called again for a while; the other family may run
    for fam in (result or {}).get("failed_over") or []:  # a family the engine failed over from mid-job
        mark_exhausted(CLI_FAMILY.get(str(fam).lower(), str(fam).lower()))
    job["authors"] = [a for a in ((result or {}).get("authors") or []) if a in FAMILIES]
    manifest = [p for p in ((result or {}).get("manifest") or []) if isinstance(p, str)]
    changed = changed_paths(wt, job["base"])
    fields = {"summary": summary, "manifest": manifest, "check_ok": None, "check_output": "", "files": [],
              "unexpected": [], "landed": False, "landed_commit": "", "review": None, "authors": job["authors"]}
    keep = True                                            # the worktree stays unless the work is safely placed
    if changed is None:
        note, status, error = "not landed: git could not list the changes; the worktree is kept at %s" % wt, "failed", "git status failed"
    elif not changed:
        note, status, error = "nothing changed", ("failed" if err else "done"), err
        left = _unlanded(wt, manifest)                 # an ignored output the coder wrote is still work: keep it
        keep = bool(left)
        if left:
            fields["unexpected"] = left
            note = "nothing landable changed; outputs git ignores are kept at %s (%s)" % (wt, ", ".join(left[:8]))
    else:
        # W2 (2026-10-08): only what the coder's tools recorded writing lands - plus a file the job named up front as
        # its declared output (a render a script made), still reviewed; the exclusions hold for both
        allowed = {p for p in manifest + list(job.get("outputs") or []) if not never_lands(p)}
        unexpected = [p for p in changed if p not in allowed and not _runtime(p)]     # W1: runtime never refuses
        files = [p for p in changed if p in allowed and not _runtime(p)]              # ... and never lands
        fields.update(unexpected=unexpected, files=files)
        status, error = ("failed" if err else "done"), err
        if err:
            note = "not landed: the coder's turn ended in an error; the work is kept at %s" % wt
        elif unexpected:
            note = ("not landed: %d changed path(s) the coder's tools did not write (%s); everything is kept at %s"
                    % (len(unexpected), refusal_detail(unexpected), wt))
        elif not files:
            note = "not landed: nothing the coder wrote changed; the worktree is kept at %s" % wt
        else:
            fields["check_ok"], fields["check_output"] = run_check(job, wt)
            after = changed_paths(wt, job["base"])
            late = sorted(set(after or []) - set(changed)) if after is not None else ["(git could not list the changes)"]
            late = _not_runtime(late)                    # W1: a runtime record the check touched never refuses
            made = [x for x in late if x in set(job.get("outputs") or []) and not never_lands(x)]
            if made:                                     # a declared output the check produced lands with the rest (W2)
                files = files + made
                fields["files"] = files
                late = [x for x in late if x not in made]
            late += [p + " (ignored by git)" for p in _not_runtime(ignored_outputs(wt))]
            served = _served_tree_changes(job)
            if late:
                fields["unexpected"] = sorted(set(fields["unexpected"]) | set(late))
            if fields["check_ok"] is None:       # W1a (2026-10-08): every landing needs an explicit passing check
                note = ("not landed: no check was given - every landing needs a passing check (start the job with "
                        "--check); the work is kept at %s" % wt)
            elif fields["check_ok"] is not True:
                note = "not landed: the check failed in the job's tree; the work is kept at %s" % wt
            elif late:
                fields["unexpected"] = sorted(set(fields["unexpected"]) | set(late))
                note = ("not landed: the check or the coder left changes outside the coder's own files (%s); everything "
                        "is kept at %s" % (refusal_detail(late), wt))
            elif served:
                fields["served_tree_changed"] = served
                note = ("not landed: %s changed during the job outside the landing (%s) - something wrote into it "
                        "directly; check those files; the work is kept at %s" % (job["repo"], ", ".join(served[:8]), wt))
            else:
                commit_err = _commit_manifest(wt, job, files)
                if commit_err:
                    note, status, error = "not landed: %s; the worktree is kept at %s" % (commit_err, wt), "failed", commit_err
                else:
                    landed, note, extra = land(job, files)
                    fields.update(extra)
                    fields["landed"] = landed
                    left = _unlanded(wt, manifest) if landed else ["not landed"]
                    keep = not (landed and extra.get("verified")) or bool(left)
                    if landed and left and left != ["not landed"]:
                        note += "; work the landing did not carry is kept at %s (%s)" % (wt, ", ".join(left[:6]))
    if not fields.get("landed"):                     # the complete preserved inventory, whatever check failed
        fields["unexpected"] = sorted(set(fields.get("unexpected") or [])
                                      | {p + " (ignored by git)" for p in ignored_outputs(wt)})
    served = _served_tree_changes(job)              # on every path: did anything write into the source repository?
    if served:
        fields["served_tree_changed"] = served
        if not fields.get("landed"):
            note += ("; ALSO: %s changed during the job outside any landing (%s) - check those files"
                     % (job["repo"], ", ".join(served[:8])))
    done = _transition(cdir, job_id, ("finishing",), status=status, finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                       error=error, land_note=note, kept_worktree=(wt if keep else ""), **fields)
    if done is None:
        return
    if not keep:
        _cleanup(done, keep_branch=False)
    _report(cdir, done)


def _unlanded(wt, manifest):
    """What in the worktree would be LOST if it were removed now: any uncommitted or untracked change (a check that
    wrote a file, an edit nobody committed), and any file the coder wrote that git ignores. [] when nothing."""
    left = []
    paths = porcelain_paths(wt)
    if paths is None:
        return ["git status failed"]
    left += paths
    left += [p + " (ignored by git)" for p in ignored_outputs(wt)]
    return left


def _served_tree_changes(job):
    """Watched source files new or changed since the job started - uncommitted (the dirty-file comparison, including
    a file dirty at the start and now clean or gone) or COMMITTED since the job's base (consensus C2), except commits a
    verified code-job landing recorded."""
    before = job.get("repo_dirt")
    now = dirty_snapshot(job["repo"])
    if before is None:
        return ["(no record of the repository's changes at the start)"]
    if now is None:
        return ["(git could not list the repository's changes)"]
    before = {p: h for p, h in before.items() if watched(p)}
    changed = {p for p, h in now.items() if before.get(p) != h}
    gone = [p for p in before if p not in now]
    if gone:
        cur = dirty_snapshot_paths(job["repo"], gone)
        changed |= {p for p in gone if cur.get(p) != before[p]}
    base = job.get("base")
    if base:
        verified = landed_commits()
        code, out, _ = _git_raw(job["repo"], "-c", "core.quotepath=false", "log", "--format=%x00%H", "--name-only",
                                "--no-renames", "%s..HEAD" % base)
        if code != 0:
            changed.add("(could not read the commits made during the job)")
        else:
            for block in out.split("\x00")[1:]:
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                if lines and lines[0] not in verified:
                    changed |= {"%s (committed %s)" % (p, lines[0][:10]) for p in lines[1:] if watched(p)}
    return sorted(changed)


def dirty_snapshot_paths(repo, paths):
    """Current content hashes of specific paths ("(gone)" when absent)."""
    out = {}
    for path in paths:
        full = Path(repo) / path
        if full.is_file():
            c, h, _ = _git(repo, "hash-object", "--", path)
            out[path] = h if c == 0 else "?"
        else:
            out[path] = "(gone)"
    return out


def _commit_manifest(wt, job, files):
    """Stage ONLY the coder's own changed paths, by literal path, and commit them on the job's branch."""
    files = _not_runtime(files)
    present = [p for p in files if (Path(wt) / p).exists()]
    gone = [p for p in files if p not in present]
    if present:
        code, _, err = _git(wt, "--literal-pathspecs", "add", "--", *present, timeout=600)
        if code != 0:
            return "git add failed: " + err[:250]
    if gone:
        code, _, err = _git(wt, "--literal-pathspecs", "rm", "-q", "--cached", "--ignore-unmatch", "--", *gone, timeout=600)
        if code != 0:
            return "git rm failed: " + err[:250]
    code, staged, err = _git(wt, "-c", "core.quotepath=false", "diff", "--cached", "--name-only", timeout=600)
    if code != 0:
        return "git diff failed: " + err[:250]
    held = [s for s in staged.splitlines() if s.strip() and _runtime(s)]
    if held:                                             # W1: kept in the worktree, absent from the commit
        code, _, err = _git(wt, "--literal-pathspecs", "reset", "-q", "--", *held, timeout=600)
        if code != 0:
            return "git reset of runtime records failed: " + err[:250]
        code, staged, err = _git(wt, "diff", "--cached", "--name-only", timeout=600)
        if code != 0:
            return "git diff failed: " + err[:250]
    if staged:
        code, out, err = _git(wt, "commit", "-q", "-m", "Code job %s for the steward\n\n%s" % (job["id"], job["brief"][:600]),
                              timeout=600)
        if code != 0:
            return "git commit failed: " + (err or out)[:250]
    return ""


def _stop_asked(job):
    return bool((read_jobs(job.get("steward_dir") or "").get(job["id"]) or {}).get("stop_requested"))


def land(job, files):
    """Bring the job's branch up to the repository's current HEAD inside the job's OWN worktree, review the candidate
    (and, when integration changed it, the delta), re-run the check there, then - under the repository's commit lock,
    with HEAD unchanged - place only the job's own files with git_safety.land_locked and verify each placed file.
    Returns (landed, note, fields)."""
    import git_safety as _gs
    wt = job["worktree"]
    # W1a (2026-10-08): the landing target - the lander's checkout of anchor-next for Anchor's own repository (named at
    # the job's start and checked again here), else the repository itself. The running Anchor is refused by land_locked.
    repo = job.get("land_to") or job["repo"]
    fields = {"verified": False}
    if job.get("land_to"):
        import anchor_next
        ip, why = anchor_next.ensure_integration(job["repo"])
        if ip is None or os.path.normcase(str(ip)) != os.path.normcase(str(job["land_to"])):
            return False, "not landed: %s; the work is kept at %s" % (why or "the lander's checkout moved", wt), fields
    code, cand, _ = _git(wt, "rev-parse", "HEAD")
    if code != 0:
        return False, "not landed: could not read the candidate; the work is kept at %s" % wt, fields
    if _stop_asked(job):
        return False, "not landed: John asked to stop it; the work is kept at %s" % wt, fields
    rec = run_review(job, wt, cand)           # W2 (2026-10-08): every job is reviewed by another family, documents too
    fields["review"] = rec
    why = review_blocks(job, rec, wt, cand)
    if why:
        return False, "not landed: %s; the work is kept at %s" % (why, wt), fields
    code, head, err = _git(repo, "rev-parse", "HEAD")
    if code != 0:
        return False, "not landed: could not read %s HEAD (%s)" % (repo, err[:120]), fields
    code, _, _ = _git(wt, "merge-base", "--is-ancestor", head, cand)
    if code != 0:                                          # newer commits in the repository: integrate in the job's tree
        code, _, _ = _git(wt, "merge", "--no-edit", head, timeout=600)
        if code != 0:
            _git(wt, "merge", "--abort")
            return False, "not landed: the work conflicts with newer changes in %s; it is kept at %s" % (repo, wt), fields
        code, merged, _ = _git(wt, "rev-parse", "HEAD")
        ok, out = run_check(job, wt)
        if ok is not True:                                 # a missing check is a failure too (W1a)
            return False, "not landed: the check did not pass after bringing in newer changes; the work is kept at %s" % wt, fields
        if _stop_asked(job):
            return False, "not landed: John asked to stop it; the work is kept at %s" % wt, fields
        delta = run_review(job, wt, merged, delta_from=cand)
        fields["delta_review"] = delta
        why = review_blocks(job, delta, wt, merged)
        if why:
            return False, "not landed (after integration): %s; the work is kept at %s" % (why, wt), fields
        cand = merged
    code2, names, _ = _git_raw(wt, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z", head, cand)
    land_files = [n for n in names.split("\0") if n.strip()]
    if code2 != 0 or not land_files:
        return False, "not landed: nothing changed beyond what %s already has" % repo, fields
    stray = [n for n in land_files if n not in set(files)]
    if stray:
        return False, "not landed: the candidate would place paths outside the job's own files (%s); kept at %s" % (
            ", ".join(stray[:8]), wt), fields
    with _gs.repo_lock(repo, wait_s=300, who="code job " + job["id"]) as held:
        if not held:
            return False, "not landed: the repository's commit lock is busy; the work is kept at %s" % wt, fields
        current = read_jobs(job.get("steward_dir") or "").get(job["id"]) or {}
        if current.get("stop_requested"):              # his Stop, honoured under the same lock placement holds
            return False, "not landed: %s asked to stop it; the work is kept at %s" % (
                current.get("stop_requested_by") or "John", wt), fields
        if current.get("status") != "finishing":       # a stop released it while it was being reviewed: no landing
            return False, "not landed: the job was stopped (%s) before placement; the work is kept at %s" % (
                current.get("stopped_by") or current.get("status") or "unknown", wt), fields
        code_h, now_head, _ = _git(wt, "rev-parse", "HEAD")
        if code_h != 0 or now_head != cand:           # something committed after the review: never place an older candidate
            return False, ("not landed: the job's branch moved after review (%s, reviewed %s); everything is kept at %s"
                           % (now_head[:12], cand[:12], wt)), fields
        left = _not_runtime(_unlanded(wt, files))      # a second check after integration made nothing extra (W1: runtime records aside)
        if left:
            fields["unexpected"] = sorted(set(fields.get("unexpected") or []) | set(left))
            return False, ("not landed: changes outside the coder's own files appeared before placement (%s); "
                           "everything is kept at %s" % (refusal_detail(left), wt)), fields
        served_now = _served_tree_changes(job)
        if served_now:
            fields["served_tree_changed"] = served_now
            return False, ("not landed: %s changed during the job outside the landing (%s); the work is kept at %s"
                           % (repo, ", ".join(served_now[:8]), wt)), fields
        code, now, _ = _git(repo, "rev-parse", "HEAD")
        if code != 0 or now != head:
            return False, "not landed: %s moved during the review; the work is kept at %s - start the landing again" % (
                repo, wt), fields
        landed, note = _gs.land_locked(repo, cand, land_files, "Code job %s for the steward\n\n%s" % (
            job["id"], job["brief"][:600]), who="code job " + job["id"], expect_head=head)
        if landed:                                      # recorded before the lock goes: a stop can no longer release it
            _transition(job.get("steward_dir") or "", job["id"], ("finishing",), placed=True)
            c, out, _ = _git(repo, "rev-parse", "HEAD")  # the landing commit itself: read while nothing else can commit
            fields["landed_commit"] = out.strip() if c == 0 else ""
    if not landed:
        return False, note + "; the work is kept at %s" % wt, fields
    # the placed tree is the reviewed one for every path the job touched - additions, edits AND deletions
    code, diff, _ = _git_raw(repo, "-c", "core.quotepath=false", "diff", "--no-renames", "--name-only", "-z",
                         fields["landed_commit"] or "HEAD", cand, "--", *land_files)
    bad = [n for n in diff.split("\0") if n.strip()] if code == 0 else ["(could not compare)"]
    if bad:
        return True, "landed, but %d placed file(s) differ from the candidate (%s); the worktree is kept at %s" % (
            len(bad), ", ".join(bad[:8]), wt), fields
    fields["verified"] = True
    if fields.get("landed_commit"):
        record_landed_commit(fields["landed_commit"])     # only a verified landing's own commit is ever exempt
    return True, note, fields


def _cleanup(job, keep_branch=True):
    """The worktree goes; the branch goes only when there is nothing on it worth keeping."""
    try:
        _git(job["repo"], "worktree", "remove", "--force", job["worktree"], timeout=300)
        if not keep_branch:
            _git(job["repo"], "branch", "-D", job["branch"])
    except Exception:
        pass


def live_state(job):
    """'live' | 'waits for a restart' | '' (not an Anchor landing, or unknown) - OBSERVED (two-lane step 6, 2026-10-05):
    the running build (ANCHOR_RUNNING_HEAD, set by the server at start) contains the commit the job landed."""
    if not job.get("landed"):
        return ""
    try:
        here = Path(__file__).resolve().parents[1]
        if Path(str(job.get("repo") or "")).resolve() != here:
            return ""
    except Exception:
        return ""
    running, landed = os.environ.get("ANCHOR_RUNNING_HEAD", ""), str(job.get("landed_commit") or "")
    if not running or not landed:
        return "waits for a restart"
    c, _, _ = _git(str(here), "merge-base", "--is-ancestor", landed, running)
    return "live" if c == 0 else "waits for a restart"


def live_note(job):
    """Landed is not live (his word, 2026-10-05: a tile repair 'landed with all 20 checks passing' and nothing on his
    screen changed - the running Anchor still had the old code and his page the old stylesheet). For a job landed in the
    repository the Anchor service runs from, the one sentence the steward must carry: it waits for a restart."""
    if live_state(job) != "waits for a restart":
        return ""
    return ("NOT LIVE YET: this landed in Anchor's repository, but John's screen runs the build that was started before "
            "it - the change shows only after Anchor restarts (an Anchor restart is John's word, or his standing "
            "'restart when idle'). Tell him it is landed and waits for a restart; never call it installed, live or done "
            "on his screen until the running build carries it.")


def _report(cdir, job):
    """Wake the steward that commissioned the job with its result (a control turn, not his words)."""
    lines = ["(code job %s finished - not John) Status: %s." % (job["id"], job["status"])]
    if job.get("error"):
        lines.append("Error: " + job["error"][:300])
    if job.get("files"):
        lines.append("Files: " + ", ".join(job["files"][:20]) + (" and %d more" % (len(job["files"]) - 20) if len(job["files"]) > 20 else ""))
    if job.get("check"):
        lines.append("Check `%s`: %s." % (job["check"], "passed" if job.get("check_ok") else "FAILED") + ((" Output tail: " + job["check_output"][-400:]) if job.get("check_ok") is False else ""))
    lines.append("Landing: " + job.get("land_note", ""))
    if job.get("kept_worktree") and (job.get("files") or job.get("unexpected")) and not job.get("landed"):
        links = announce_kept(cdir, job)
        lines.append("Kept (not landed): " + (("readable copies are linked in the dialogue: " + ", ".join(links))
                                               if links else ", ".join(str(Path(job["kept_worktree"]) / f) for f in job["files"][:10])))
    live = live_note(job)
    if live:
        lines.append(live)
    lines.append("The coder's summary: " + (job.get("summary") or "(none)"))
    lines.append("Tell John the result in two or three plain sentences; ask him only what is genuinely his to decide.")
    try:
        from steward_cockpit import steward_routes as _sr
        eng = _sr.get_engine(str(cdir))
        if eng is not None:
            try:   # two-lane step 5 (2026-10-05): he sees the result at once, in the engine's own words
                state = live_state(job)
                eng._emit({"t": "sys", "text": "code job %s %s%s%s" % (
                    job["id"], "finished" if job.get("status") == "done" else "failed",
                    (" \u2014 landed" + ((", " + state) if state else "")) if job.get("landed") else "",
                    (" \u2014 " + job.get("land_note")) if (job.get("land_note") and not job.get("landed")) else "")})
            except Exception:
                pass
            if not eng.alive():
                eng.wake(fresh=False)
            eng.say("\n".join(lines), human=False)
    except Exception:
        pass


def announce_kept(cdir, job):
    """The readable outputs of a job that did NOT land are copied into the steward's folder
    (code-job-outputs/<job>/...) and announced in its dialogue with their Read links - John can open the PDF the job
    made even though the code did not land. Returns the copied names."""
    import shutil as _sh
    try:
        from steward_cockpit import steward_engine as _se
        import deliverables_register as _dr
        pid, rel = _dr.project_and_rel(cdir)
        out, links, unlisted = Path(cdir) / "code-job-outputs" / job["id"], [], []
        preserved = list(job.get("files") or []) + [str(u).replace(" (ignored by git)", "") for u in job.get("unexpected") or []]
        for f in dict.fromkeys(preserved):
            src = Path(job["kept_worktree"]) / f
            if not src.is_file() or not (is_document(f) or os.path.splitext(f)[1].lower() in (".html", ".htm")):
                continue
            dst = out / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            _sh.copy2(str(src), str(dst))
            where = dst.relative_to(Path(cdir)).as_posix()
            t = _dr.reading_target({"path": where}, pid=pid, effort_rel=rel, effort_dir=cdir)
            if t["read"] or t["download"]:
                links.append(Path(f).name)
                _dr.register(cdir, "Code job %s kept (not landed): %s" % (job["id"], Path(f).name), "`%s`" % where, notify=False)
                unlisted.append("[%s](%s)" % (Path(f).name, t["read"] or t["download"]))
        # W2 (2026-10-08): ONE line for the job, never one per file - its register rows (Deliverables and Next steps
        # still carry each) are marked announced, and this line says them all
        if unlisted:
            line = "**Anchor** · kept from code job %s (not landed): %s" % (job["id"], ", ".join(unlisted))
            _se._default_record(cdir)(line, "receipt:kept:%s" % job["id"])
            try:
                from steward_cockpit import steward_routes as _sr
                eng = _sr.get_engine(str(cdir), create=False)
                if eng is not None:
                    (getattr(eng, "emit_receipt", None) or eng._emit)({"t": "receipt", "text": line, "id": "receipt:kept:%s" % job["id"]})
            except Exception:
                pass
        return links
    except Exception:
        return []


def stop(cdir, job_id=None, engine_lookup=None, actor="unknown"):
    """Stop the running job (the newest when no id) on behalf of ``actor`` (recorded as said - never assumed to be
    John). Nothing is committed or removed: the worktree is kept exactly as the coder left it."""
    jobs = [j for j in read_jobs(cdir).values() if j.get("status") in LIVE and (not job_id or j["id"] == job_id)]
    if not jobs:
        return {"ok": False, "error": "no code job is running"}
    job = sorted(jobs, key=lambda j: j["started"])[-1]
    who = str(actor or "unknown")
    if job.get("status") == "finishing":
        if time.time() - float(job.get("finishing_at") or 0) < 2 * (CHECK_TIMEOUT_S + REVIEW_TIMEOUT_S) + 900:
            # consensus C6: his Stop counts NOW - recorded with its actor; the finish checks it before every review and
            # under the placement lock, so the job does not land after it (a landing already placed stays placed)
            import git_safety as _gs
            # under the repository's commit lock - the lock placement holds while it re-reads the Stop and places - so
            # the answer is exact: recorded before placement (it will not land), or too late (it already landed)
            with _gs.repo_lock(job["repo"], wait_s=900, who="stop of code job " + job["id"]) as held:
                if not held:
                    return {"ok": False, "error": "the repository is busy landing; try the stop again in a moment"}
                if (read_jobs(cdir).get(job["id"]) or {}).get("placed"):
                    return {"ok": False, "error": "too late: it has already landed; its report is on the way"}
                asked = _transition(cdir, job["id"], ("finishing",), stop_requested=time.strftime("%Y-%m-%d %H:%M:%S"),
                                    stop_requested_by=who)
            if asked is None:
                return {"ok": False, "error": "the code job finished while the stop was asked; see its result"}
            return {"ok": True, "job": job["id"], "branch": job["branch"], "stop_requested": True, "kept": job["worktree"],
                    "note": "stop recorded; the job will not land and its work is kept"}
        import git_safety as _gs
        # the release happens under the repository's commit lock - the same lock placement holds - so a landing in
        # progress finishes first, and a landing not yet begun sees the release and refuses
        with _gs.repo_lock(job["repo"], wait_s=900, who="stop of code job " + job["id"]) as held:
            if not held:
                return {"ok": False, "error": "the repository is busy landing; try the stop again in a moment"}
            if (read_jobs(cdir).get(job["id"]) or {}).get("placed"):
                return {"ok": False, "error": "it has already landed; its report is on the way"}
            released = _transition(cdir, job["id"], ("finishing",), status="failed", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                                   error="the job's finish never completed", stopped_by=who, kept_worktree=job["worktree"],
                                   land_note="released by %s; the work is kept at %s" % (who, job["worktree"]))
        if released is None:
            return {"ok": False, "error": "the code job finished while the stop waited; see its result"}
        served = _served_tree_changes(job)
        if served:
            _transition(cdir, job["id"], ("failed",), served_tree_changed=served,
                        land_note=released["land_note"] + ("; ALSO: %s changed during the job outside any landing (%s) "
                                                           "- check those files" % (job["repo"], ", ".join(served[:8]))))
        return {"ok": True, "job": job["id"], "branch": job["branch"], "released": True, "kept": job["worktree"],
                "served_tree_changed": served}
    stopped = _transition(cdir, job["id"], ("running",), status="stopped", finished=time.strftime("%Y-%m-%d %H:%M:%S"),
                          stopped_by=who, kept_worktree=job["worktree"],
                          land_note="stopped by %s; nothing landed; the work so far is kept at %s (branch %s)" % (
                              who, job["worktree"], job["branch"]))
    if stopped is None:
        return {"ok": False, "error": "the code job is already finishing; its result is on the way"}
    try:
        eng = engine_lookup(job["worktree"]) if engine_lookup else None
        if eng is not None:
            eng.on_turn_done = None
            eng.stop()
    except Exception:
        pass
    served = _served_tree_changes(job)              # the finish will not run: audit the source repository here
    if served:
        _transition(cdir, job["id"], ("stopped",), served_tree_changed=served,
                    land_note=stopped["land_note"] + ("; ALSO: %s changed during the job outside any landing (%s) - "
                                                      "check those files" % (job["repo"], ", ".join(served[:8]))))
    return {"ok": True, "job": job["id"], "branch": job["branch"], "kept": job["worktree"], "stopped_by": who,
            "served_tree_changed": served}
