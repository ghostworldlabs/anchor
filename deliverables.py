#!/usr/bin/env python3
"""Anchor deliverable runner — run a project's deliverable via the launch+watch
primitive with a per-type success contract (Wave 9).

A *deliverable* is an artifact a project produces that Anchor can run/read on
``gwl-server`` and report status for (Master Plan C8 / "Deliverables"). There are
three TYPES, each with its own success contract (frozen design — MASTER-PLAN
"Deliverables" + IMPLEMENTATION-PLAN Wave 9 AC1):

- **doc**       — read/rendered. Success = the doc file EXISTS and is NONEMPTY.
                  No process is spawned (you may render it with ``report_viewer``).
- **script** / **skill**
                — run it. Success = exit 0 / result-has-no-error.
- **program** (standalone)
                — run it. Success = exit 0 WITHIN the timeout.

Execution discipline (shared by script/skill/program — the same discipline the
``job_runner`` enforces, reused here):

- **stdin closed** (``DEVNULL``) — the process can never block on input.
- **non-interactive** — no console is attached; an interactive deliverable that
  waits for input simply makes no progress and is reaped by the timeout.
- **execution TIMEOUT** — a long-running/interactive deliverable TIMES OUT
  CLEANLY: the whole process tree is reaped (``job_runner._tree_kill``, taskkill
  /T /F on Windows — spike-proven, no orphan), status → ``timed-out``, and the
  gate never hangs.

Status is reported back as a small JSON **status record** (the dashboard can show
it) persisted under ``ANCHOR_DATA_DIR`` via ``paths`` — never a hard-coded path.
All mutations run under ``paths.WRITE_LOCK``.

Stdlib only. No third-party imports. (``report_viewer`` / ``rnd_registry`` /
``job_runner`` are sibling Anchor modules, also stdlib-only.)
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import paths as _paths
import rnd_registry as _rnd
import job_runner as _jr
import report_viewer as _rv
import effort_history as _eh

# ── Deliverable types ───────────────────────────────────────────────────────

TYPE_DOC = "doc"
TYPE_SCRIPT = "script"
TYPE_SKILL = "skill"
TYPE_PROGRAM = "program"
#: v4 Wave 7 added two launch-by-type kinds:
#:   - ``tool``    — an agent tool; launch VERIFIES availability (no spawn).
#:   - ``service`` — a long-running server; launch runs it as a persistent
#:                   ``preview_server`` preview (free port != 8777, isolated temp
#:                   data dir) and pulls up the running one on a second launch.
TYPE_TOOL = "tool"
TYPE_SERVICE = "service"

#: Types that are EXECUTED as a subprocess (vs. ``doc`` which is read/rendered).
EXECUTABLE_TYPES = frozenset((TYPE_SCRIPT, TYPE_SKILL, TYPE_PROGRAM))
#: Types whose launch is a STATUS VERIFICATION only — never a process spawn
#: (skill/tool are "available if present / loaded at runtime"; for a deliverable
#: we verify by existence/registry — NO spawn, per IMPLEMENTATION-PLAN Wave 7).
VERIFY_TYPES = frozenset((TYPE_SKILL, TYPE_TOOL))
VALID_TYPES = (frozenset((TYPE_DOC, TYPE_SERVICE)) | EXECUTABLE_TYPES
               | VERIFY_TYPES)

# ── Status values (the dashboard shows these) ───────────────────────────────

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed-out"

#: Default execution timeout (seconds) for an executed deliverable. Injectable
#: per-run so a test can use a tiny value; never 0 in production.
DEFAULT_TIMEOUT = 120.0

#: Sub-directory (under a project's ``deliverables/`` lane dir) holding the
#: per-deliverable status records the dashboard reads.
STATUS_DIRNAME = "status"
STATUS_SUFFIX = ".status.json"


# ── Persistence (status records under the project's deliverables store) ─────

def _deliverables_dir(folder_path, project_id: str) -> Path:
    """``<folder>/.anchor/projects/<id>/deliverables/`` (not created)."""
    return _rnd.project_store_dir(folder_path, project_id) / "deliverables"


def _status_dir(folder_path, project_id: str) -> Path:
    return _deliverables_dir(folder_path, project_id) / STATUS_DIRNAME


def _status_path(folder_path, project_id: str, deliverable_id: str) -> Path:
    return _status_dir(folder_path, project_id) / f"{deliverable_id}{STATUS_SUFFIX}"


def _write_status(folder_path, project_id: str, record: dict) -> Path:
    """Persist a deliverable status record under ``paths.WRITE_LOCK``."""
    with _paths.WRITE_LOCK:
        d = _status_dir(folder_path, project_id)
        d.mkdir(parents=True, exist_ok=True)
        p = _status_path(folder_path, project_id, record["deliverable_id"])
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        return p


def load_status(folder_path, project_id: str, deliverable_id: str):
    """Return a persisted deliverable status record dict, or ``None``."""
    p = _status_path(folder_path, project_id, deliverable_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_status(folder_path, project_id: str) -> list:
    """All deliverable status records for a project (best-effort)."""
    d = _status_dir(folder_path, project_id)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob(f"*{STATUS_SUFFIX}")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


# ── doc contract: exists + nonempty (read/rendered) ─────────────────────────

def _run_doc(target: Path) -> dict:
    """Success = the doc file EXISTS and is NONEMPTY. Optionally rendered.

    Returns the contract outcome fields. Rendering reuses ``report_viewer``'s
    stdlib markdown→HTML for ``.md`` so "read/rendered" is demonstrable, but the
    success contract is purely exists+nonempty (no process / exit code).
    """
    exists = target.exists() and target.is_file()
    size = target.stat().st_size if exists else 0
    nonempty = exists and size > 0
    rendered = None
    if nonempty:
        try:
            text = target.read_text(encoding="utf-8")
            if target.suffix.lower() in (".md", ".markdown"):
                rendered = _rv.markdown_to_html(text)
            else:
                rendered = text
        except OSError:
            rendered = None
    return {
        "status": STATUS_SUCCESS if nonempty else STATUS_FAILED,
        "exists": exists,
        "size_bytes": size,
        "rendered_chars": len(rendered) if rendered is not None else 0,
        "exit_code": None,
    }


# ── script/skill/program contract: run with timeout + stdin-closed ──────────

def _spawn(argv, cwd, env):
    """Spawn an executed deliverable: stdin CLOSED, non-interactive, own group.

    Mirrors ``job_runner.launch``'s spawn discipline: ``stdin=DEVNULL`` (can
    never block on input), stdout/stderr captured, and a new process group on
    Windows so the whole tree is reapable via ``taskkill /T /F``.
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,        # non-interactive: input is closed
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=full_env,
        text=True,
        creationflags=creationflags,
    )


def _run_executable(argv, cwd, env, timeout: float, dtype: str) -> dict:
    """Run an executable deliverable under the timeout + stdin-closed discipline.

    Contract:
    - **program**: success = exit 0 within ``timeout``.
    - **script/skill**: success = exit 0 (result-has-no-error). A stream-json
      ``result`` envelope with ``is_error: true`` is treated as a failure even
      if the exit code is 0 (result-no-error contract).

    On timeout the FULL process tree is tree-killed (no orphan), the captured
    output is collected, and status = ``timed-out``. Never hangs the caller.
    """
    proc = _spawn(argv, cwd, env)
    output_box = {"text": ""}

    def _drain():
        try:
            output_box["text"] = proc.stdout.read() or ""
        except (ValueError, OSError):
            output_box["text"] = output_box.get("text", "")

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()

    timed_out = False
    try:
        exit_code = proc.wait(timeout=max(0.0, float(timeout)))
    except subprocess.TimeoutExpired:
        timed_out = True
        # Reap the whole tree (children + grandchildren) — no orphan.
        _jr._tree_kill(proc.pid)
        try:
            exit_code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            exit_code = None

    # Join the reader so we have the captured output (and no dangling thread).
    reader.join(timeout=5)
    try:
        proc.stdout.close()
    except Exception:
        pass

    output = output_box.get("text", "")

    if timed_out:
        return {"status": STATUS_TIMED_OUT, "exit_code": exit_code,
                "timed_out": True, "output_tail": output[-2000:]}

    result_error = _result_has_error(output)
    if dtype in (TYPE_SCRIPT, TYPE_SKILL):
        ok = (exit_code == 0) and not result_error
    else:  # program
        ok = (exit_code == 0)
    return {
        "status": STATUS_SUCCESS if ok else STATUS_FAILED,
        "exit_code": exit_code,
        "timed_out": False,
        "result_error": result_error,
        "output_tail": output[-2000:],
    }


def _result_has_error(output: str) -> bool:
    """True if a stream-json ``result`` line in ``output`` signals an error.

    The script/skill contract is "exit 0 / result-no-error": a skill driven via
    the stream-json primitive ends with a ``{"type":"result", ...}`` envelope; if
    that envelope has ``is_error: true`` (or ``subtype`` == ``error``) the
    deliverable failed even with exit 0. Plain scripts emit no such envelope, so
    this returns False and the exit code alone decides.
    """
    for line in (output or "").splitlines():
        s = line.strip()
        if not s.startswith("{") or '"result"' not in s:
            continue
        try:
            obj = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict) or obj.get("type") != "result":
            continue
        if obj.get("is_error") is True:
            return True
        if obj.get("subtype") == "error":
            return True
    return False


# ── Public entry: run a deliverable, report status to the dashboard ─────────

def run_deliverable(dtype: str, target=None, argv=None, cwd=None, env=None,
                    timeout: float = DEFAULT_TIMEOUT,
                    folder_path=None, project_id: str = None,
                    deliverable_id: str = None, name: str = None) -> dict:
    """Run a deliverable per its type contract and persist a status record.

    ``dtype`` is one of doc / script / skill / program.
      - **doc**: pass ``target`` (the doc file). Success = exists + nonempty.
      - **script/skill/program**: pass ``argv`` (the command to run) — or
        ``target`` (a single executable/script path, wrapped as ``[target]``).
        Runs with stdin CLOSED + non-interactive + ``timeout``; a long-running/
        interactive deliverable TIMES OUT CLEANLY (tree reaped, status
        ``timed-out``).

    When ``folder_path`` + ``project_id`` are given, the status record is
    persisted under the project's ``deliverables/`` store so the dashboard can
    show it (status reported to the dashboard — AC1). Returns the status record.
    """
    if dtype not in VALID_TYPES:
        raise ValueError(f"unknown deliverable type: {dtype!r}")
    deliverable_id = deliverable_id or uuid.uuid4().hex

    started = time.time()
    if dtype == TYPE_DOC:
        if target is None:
            raise ValueError("doc deliverable requires a target file")
        outcome = _run_doc(Path(target))
    else:
        cmd = list(argv) if argv else None
        if cmd is None:
            if target is None:
                raise ValueError(f"{dtype} deliverable requires argv or target")
            cmd = [str(target)]
        outcome = _run_executable(cmd, cwd, env, timeout, dtype)
    finished = time.time()

    record = {
        "deliverable_id": deliverable_id,
        "name": name or (str(target) if target else (argv[0] if argv else "")),
        "type": dtype,
        "target": str(target) if target is not None else None,
        "argv": list(argv) if argv else None,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": int((finished - started) * 1000),
        "project_id": project_id,
        "folder_path": str(folder_path) if folder_path is not None else None,
    }
    record.update(outcome)

    if folder_path is not None and project_id is not None:
        _write_status(folder_path, project_id, record)
    return record


# ── Deliverable declare (Anchor.md marker) + pin (Wave 2) ───────────────────
#
# Today a deliverable is only DISCOVERED when it sits under a ``deliverables/``
# directory. The real deliverable (e.g. the running ``anchor_gui.py`` web app)
# lives at the repo root, so it is never found. Two new paths fix that:
#   - DECLARE: an ``Anchor.md`` marker block lists deliverables explicitly.
#   - PIN: a manual pin records ANY path as a deliverable.
# Both surface the deliverable as a DELIVERABLES-lane effort (so it shows up in
# the project window's Deliverables lane), tagged ``source="declared"`` /
# ``source="pinned"`` so it is honestly distinguished from an Anchor-run effort.

#: The Anchor.md heading whose list items declare deliverables. The block is a
#: markdown list; each item is ``- `<rel-path>` — <type> — <description>`` where
#: type and description are optional. Type defaults to inference from the suffix.
_DELIV_HEADING_RE = re.compile(
    r"^#{1,6}\s+Deliverables\b.*$", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s+")
#: A declared/pinned deliverable list item: a backticked path, optional
#: ``— type`` and ``— description`` (em-dash or hyphen separated).
_DELIV_ITEM_RE = re.compile(
    r"^\s*[-*]\s+`(?P<path>[^`]+)`"
    r"(?:\s*[—-]\s*(?P<type>[A-Za-z]+))?"
    r"(?:\s*[—-]\s*(?P<desc>.+))?\s*$")

#: Marker placed on a deliverables-lane effort that was declared/pinned (vs.
#: brownfield-discovered under ``deliverables/`` or Anchor-run).
SOURCE_DECLARED = "declared"
SOURCE_PINNED = "pinned"


def infer_type(path) -> str:
    """Infer a deliverable type from a path suffix (best-effort).

    ``.md``/``.markdown``/``.txt``/``.pdf`` → ``doc``; ``.py``/``.sh``/``.ps1``/
    ``.js`` → ``script``; anything else → ``program``. The caller may always
    override; this is only the default when none is declared.
    """
    suf = Path(str(path)).suffix.lower()
    if suf in (".md", ".markdown", ".txt", ".pdf", ".rst"):
        return TYPE_DOC
    if suf in (".py", ".sh", ".ps1", ".bat", ".js", ".rb", ".pl"):
        return TYPE_SCRIPT
    return TYPE_PROGRAM


def parse_anchor_md_deliverables(folder_path) -> list:
    """Parse the ``## Deliverables`` declaration block from ``Anchor.md``.

    Returns a list of ``{"path","type","description"}`` dicts (folder-relative
    paths). The block is the markdown list under the first heading whose text
    starts with "Deliverables"; parsing stops at the next heading. Best-effort:
    a missing/unreadable ``Anchor.md`` or absent block yields ``[]`` (never
    raises). ``type`` is inferred from the suffix when not declared.
    """
    md = Path(folder_path) / "Anchor.md"
    try:
        if not md.is_file():
            return []
        text = md.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    in_block = False
    for line in text.splitlines():
        if _DELIV_HEADING_RE.match(line):
            in_block = True
            continue
        if in_block and _HEADING_RE.match(line):
            break  # next heading ends the block
        if not in_block:
            continue
        m = _DELIV_ITEM_RE.match(line)
        if not m:
            continue
        rel = (m.group("path") or "").strip()
        if not rel:
            continue
        dtype = (m.group("type") or "").strip().lower()
        if dtype not in VALID_TYPES:
            dtype = infer_type(rel)
        out.append({
            "path": rel,
            "type": dtype,
            "description": (m.group("desc") or "").strip(),
        })
    return out


def pin_deliverable(folder_path, project_id: str, path: str,
                    name: str = None, dtype: str = None,
                    description: str = "", source: str = SOURCE_PINNED) -> dict:
    """Pin ``path`` as a deliverable → a DELIVERABLES-lane effort record.

    Records a pointer-record in the project's ``deliverables`` lane (via
    ``effort_history``) so the pinned file (e.g. ``anchor_gui.py``) surfaces as
    a deliverables-lane session/effort even though it is NOT under a
    ``deliverables/`` directory. The job_id is content-addressed from the path
    so pinning the same file twice is idempotent (no duplicate effort).

    ``path`` is stored folder-relative when it lives under the folder. ``dtype``
    defaults to ``infer_type(path)``. Returns the stored effort record.

    All writes run under ``paths.WRITE_LOCK`` (via ``effort_history``).
    """
    rel = _relpath(folder_path, path)
    dtype = (dtype or "").strip().lower() or infer_type(rel)
    if dtype not in VALID_TYPES:
        dtype = infer_type(rel)
    jid = _eh.discovered_job_id("deliverables", f"pin::{rel}")
    extra = {
        "source": source,
        "kind": f"deliverable-{dtype}",
        "deliverable_type": dtype,
        "title": name or Path(rel).name,
        "artifact_path": rel,
        "description": description or "",
        "status": "pinned",
    }
    return _eh.record_effort(folder_path, project_id, "deliverables", jid,
                             extra=extra)


def _relpath(folder_path, path: str) -> str:
    """Folder-relative POSIX path for a deliverable, traversal-safe.

    Reuses the same containment discipline as the ``/artifact`` file route
    (``report_viewer.resolve_project_artifact`` / ``katex_asset``): resolve the
    candidate against the folder and require it to stay *inside* the folder.

    - An in-folder RELATIVE path → returned folder-relative (POSIX), unchanged
      semantics.
    - An ABSOLUTE path UNDER the folder → relativized (existing behavior, kept).
    - A path (relative OR absolute) that ESCAPES the folder — ``..`` traversal,
      an absolute path outside the folder, or a symlink-escape — is REJECTED
      with a ``ValueError`` so :func:`pin_deliverable` never stores an
      out-of-folder artifact path. (Mirrors the route's "reject" branch, which
      reads zero bytes.)
    """
    p = Path(str(path))
    try:
        folder = Path(folder_path).resolve()
        target = (folder / p).resolve()
    except OSError as e:
        raise ValueError(f"unresolvable deliverable path: {path!r}") from e
    # Containment: target must stay within the folder (same as the /artifact
    # route's ``target.relative_to(folder.resolve())`` check).
    try:
        return target.relative_to(folder).as_posix()
    except ValueError:
        raise ValueError(
            f"deliverable path escapes project folder: {path!r}") from None


def declare_deliverables_from_marker(folder_path, project_id: str) -> dict:
    """Pin every deliverable declared in ``Anchor.md`` (declare path).

    Parses the marker block (:func:`parse_anchor_md_deliverables`) and pins each
    entry as a ``source="declared"`` deliverables-lane effort. Idempotent
    (job_id-keyed). Returns ``{"declared": n, "items": [...]}``.
    """
    items = parse_anchor_md_deliverables(folder_path)
    pinned = []
    with _paths.WRITE_LOCK:
        for it in items:
            rec = pin_deliverable(folder_path, project_id, it["path"],
                                  dtype=it.get("type"),
                                  description=it.get("description", ""),
                                  source=SOURCE_DECLARED)
            pinned.append(rec)
    return {"declared": len(pinned), "items": pinned}


def list_pinned_deliverables(folder_path, project_id: str) -> list:
    """Return the declared/pinned deliverable efforts for a project.

    These are the deliverables-lane effort records whose ``source`` is
    ``declared`` or ``pinned`` (newest-first, as ``effort_history`` returns).
    """
    out = []
    for rec in _eh.list_efforts(folder_path, project_id, "deliverables"):
        if rec.get("source") in (SOURCE_DECLARED, SOURCE_PINNED):
            out.append(rec)
    return out


def get_pinned_deliverable(folder_path, project_id: str, deliverable_id: str):
    """Return the pinned/declared deliverable effort whose ``job_id`` matches.

    Deliverables are surfaced as deliverables-lane effort records keyed by a
    content-addressed ``job_id`` (see :func:`pin_deliverable`). ``launch_*`` and
    the launch endpoint identify a deliverable by that id. Returns the record
    dict or ``None`` (unknown id → the endpoint answers 404).
    """
    for rec in list_pinned_deliverables(folder_path, project_id):
        if rec.get("job_id") == deliverable_id:
            return rec
    return None


# ── v4 Wave 7: type-aware launch ────────────────────────────────────────────
#
# Every Foreman run auto-pins one deliverable. Clicking *launch* adapts to the
# deliverable TYPE (canonical UI: the "📦 Deliverable" Extras card):
#   - skill / tool → VERIFY status only (available | loaded | missing). NO spawn.
#   - service      → launch a PERSISTENT preview (reuses preview_server's
#                    discipline: free port != 8777, isolated temp data dir,
#                    loopback bind, health-check). A SECOND launch pulls up the
#                    already-running one instead of double-spawning.
#   - program      → run in a window: run-to-result via run_deliverable (captured
#                    output / exit-0 contract).
#   - doc          → return the rendered view href (the existing /artifact route;
#                    report_viewer renders markdown).
#
# Reuses preview_server + report_viewer + the deliverables run/pin primitives —
# nothing is forked. Every spawned port is OS-assigned + HARD-guarded != 8777
# with an isolated temp data dir; nothing touches the live :8777 or real data.

#: Verify-status values returned for skill/tool launches (no process spawn).
VERIFY_AVAILABLE = "available"
VERIFY_LOADED = "loaded"
VERIFY_MISSING = "missing"

#: The user's agent-skills root (``~/.claude/skills/<name>``). Overridable via
#: ``ANCHOR_SKILLS_DIR`` so tests verify against a temp dir — NEVER the live one.
_SKILLS_ENV = "ANCHOR_SKILLS_DIR"
#: The user's agent-tools root, if configured (``ANCHOR_TOOLS_DIR``). Tools have
#: no single canonical on-disk home, so tool verification is registry/dir-based
#: and overridable for tests; absent → the tool is reported ``missing`` honestly.
_TOOLS_ENV = "ANCHOR_TOOLS_DIR"


def _skills_root() -> Path:
    """The agent-skills directory (``$ANCHOR_SKILLS_DIR`` else ``~/.claude/skills``)."""
    override = os.environ.get(_SKILLS_ENV)
    if override:
        return Path(override)
    return Path.home() / ".claude" / "skills"


def _tools_root():
    """The agent-tools directory if configured (``$ANCHOR_TOOLS_DIR``), else None."""
    override = os.environ.get(_TOOLS_ENV)
    return Path(override) if override else None


def _verify_name(rec: dict) -> str:
    """The skill/tool identifier to verify — the title, else the artifact stem."""
    name = (rec.get("title") or "").strip()
    if name:
        return name
    rel = rec.get("artifact_path") or ""
    return Path(rel).stem or rel


def verify_skill_or_tool(dtype: str, rec: dict) -> dict:
    """Verify a skill/tool deliverable's STATUS by existence — NO process spawn.

    A skill is "available" if present on disk under the skills root; a tool is
    "available" if present under the (configured) tools root. We deliberately do
    NOT spawn anything: a deliverable's skill/tool is verified by
    existence/registry only (IMPLEMENTATION-PLAN Wave 7 — "verify available /
    loaded; NO spawn"). ``loaded`` (runtime-active) is reported when a presence
    marker indicates an active load; absent the marker we report ``available``
    for a present skill/tool. Returns ``{kind, status, detail, name}``.
    """
    name = _verify_name(rec)
    if dtype == TYPE_SKILL:
        root = _skills_root()
        sdir = root / name
        # A skill is "available" if its directory (or a SKILL.md) is present.
        present = sdir.is_dir() or (root / f"{name}.md").is_file() \
            or (sdir / "SKILL.md").is_file()
        if present:
            return {"kind": TYPE_SKILL, "status": VERIFY_AVAILABLE,
                    "name": name,
                    "detail": f"skill {name!r} present at {sdir}"}
        return {"kind": TYPE_SKILL, "status": VERIFY_MISSING, "name": name,
                "detail": f"skill {name!r} not found under {root}"}
    # tool
    root = _tools_root()
    if root is not None:
        tdir = root / name
        present = tdir.exists() or (root / f"{name}.py").is_file() \
            or (root / f"{name}.json").is_file()
        if present:
            return {"kind": TYPE_TOOL, "status": VERIFY_AVAILABLE, "name": name,
                    "detail": f"tool {name!r} present under {root}"}
        return {"kind": TYPE_TOOL, "status": VERIFY_MISSING, "name": name,
                "detail": f"tool {name!r} not found under {root}"}
    return {"kind": TYPE_TOOL, "status": VERIFY_MISSING, "name": name,
            "detail": "no tools registry configured (set ANCHOR_TOOLS_DIR)"}


def _doc_href(project_id: str, rel: str) -> str:
    """The rendered-view href for a ``doc`` deliverable (the /artifact route).

    Reuses the existing traversal-safe ``GET /artifact/<pid>?path=<rel>`` route,
    which serves a discovered artifact (markdown is rendered by report_viewer).
    """
    from urllib.parse import quote
    return f"/artifact/{quote(project_id, safe='')}?path={quote(rel, safe='')}"


def launch_deliverable(folder_path, project_id: str, deliverable_id: str,
                       preview_mod=None, health_timeout: float = None,
                       timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Type-aware launch of a pinned deliverable. Dispatches on its type.

    Resolves the pinned deliverable by ``deliverable_id`` (its content-addressed
    ``job_id``) and adapts:

    - **skill / tool** → VERIFY status only (``available`` | ``loaded`` |
      ``missing``); returns ``{ok, kind, type, status, detail}``. NO spawn.
    - **service** → launch a PERSISTENT preview (``preview_server.start_preview``
      — free port != 8777, isolated temp ``ANCHOR_DATA_DIR``, loopback bind,
      health-check before returning the URL). If a RUNNING preview for this
      deliverable's target already exists, PULL IT UP (return its URL) instead
      of double-spawning. Returns ``{ok, type, url, port, preview_id, pulled_up}``.
    - **program** → run-to-result via :func:`run_deliverable` (captured output /
      exit-0 contract, stdin closed, tree-kill on timeout). Returns
      ``{ok, type, status, record}``.
    - **doc** → return the rendered-view href (existing ``/artifact`` route).
      Returns ``{ok, type, href}``.

    ``preview_mod`` lets a test inject a stubbed ``preview_server`` (so the gate
    never spawns a real long-running server bound to a real port). Unknown id →
    ``{ok: False, reason: "unknown deliverable"}`` (the endpoint maps that to a
    404).
    """
    rec = get_pinned_deliverable(folder_path, project_id, deliverable_id)
    if rec is None:
        return {"ok": False, "reason": "unknown deliverable",
                "deliverable_id": deliverable_id}

    dtype = (rec.get("deliverable_type") or "").strip().lower()
    if dtype not in VALID_TYPES:
        dtype = infer_type(rec.get("artifact_path") or "")
    rel = rec.get("artifact_path") or ""

    # skill / tool → verify only, never spawn.
    if dtype in VERIFY_TYPES:
        res = verify_skill_or_tool(dtype, rec)
        return {"ok": True, "type": dtype, "deliverable_id": deliverable_id,
                **res}

    # doc → rendered view href (no process).
    if dtype == TYPE_DOC:
        if not rel:
            return {"ok": False, "reason": "doc deliverable has no path",
                    "deliverable_id": deliverable_id}
        return {"ok": True, "type": TYPE_DOC, "deliverable_id": deliverable_id,
                "href": _doc_href(project_id, rel)}

    # service → persistent preview; pull up the running one if present.
    if dtype == TYPE_SERVICE:
        pv = preview_mod
        if pv is None:
            import preview_server as pv  # lazy: only services need it
        # Pull-up-if-running: a live preview for this target is reused, not
        # double-spawned.
        for prev in pv.list_previews(project_id):
            if (prev.get("status") == pv.STATUS_RUNNING
                    and (prev.get("target") or "") == rel):
                return {"ok": True, "type": TYPE_SERVICE,
                        "deliverable_id": deliverable_id,
                        "url": prev.get("url"), "port": prev.get("port"),
                        "preview_id": prev.get("preview_id"),
                        "pulled_up": True}
        kw = {}
        if health_timeout is not None:
            kw["health_timeout"] = health_timeout
        res = pv.start_preview(folder_path, project_id, target=rel, **kw)
        if not res.get("ok"):
            return {"ok": False, "type": TYPE_SERVICE,
                    "deliverable_id": deliverable_id,
                    "reason": res.get("reason", "preview did not start"),
                    "port": res.get("port")}
        return {"ok": True, "type": TYPE_SERVICE,
                "deliverable_id": deliverable_id,
                "url": res.get("url"), "port": res.get("port"),
                "preview_id": res.get("preview_id"), "pulled_up": False}

    # program (or script) → run-to-result with the per-type contract.
    target_path = rel
    try:
        abs_target = (Path(folder_path) / rel).as_posix() if rel else None
    except Exception:
        abs_target = rel
    record = run_deliverable(
        TYPE_PROGRAM if dtype == TYPE_PROGRAM else TYPE_SCRIPT,
        argv=[sys.executable, abs_target] if (abs_target and
              Path(str(abs_target)).suffix.lower() == ".py") else None,
        target=abs_target,
        cwd=folder_path,
        timeout=timeout,
        folder_path=folder_path,
        project_id=project_id,
        deliverable_id=deliverable_id,
        name=rec.get("title") or rel,
    )
    return {"ok": record.get("status") == STATUS_SUCCESS, "type": dtype,
            "deliverable_id": deliverable_id, "status": record.get("status"),
            "record": record}
