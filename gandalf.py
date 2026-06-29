#!/usr/bin/env python3
"""Anchor ⇄ Gandalf integration — the two-stage runtime engine (v1, Wave 1).

Give each Anchor project an honest "what's really going on here" read by invoking
the **existing** Gandalf skill through Anchor's runner seam, then grading the
result with Gandalf's **own** Tier-1 host. Anchor is integration glue only —
Gandalf's reasoning + grading are never reimplemented here.

The flow is two stages, both injectable + STUBBED in tests (never real claude /
real node):

  Stage A (model) — build a prompt = the Gandalf ``SKILL.md`` protocol (read from
    ``ANCHOR_GANDALF_SKILL_DIR``) + "analyze the project at <folder> and emit ONLY
    the RAW draft JSON per ``runtime/RAW-DRAFT-CONTRACT.md`` as your final message;
    do NOT self-assign tiers/stamps". Launched through ``job_runner`` /
    ``ANCHOR_RUNNER_CMD`` with ``cwd=folder``, ``--add-dir folder``, an
    ``ANCHOR_GANDALF_TIMEOUT`` (default 600s), and the forwarded env. The raw
    draft is recovered via ``job_runner.extract_assistant_text`` + parsing the
    last balanced top-level JSON object.

  Stage B (host) — run ``ANCHOR_GANDALF_HOST_CMD`` (default
    ``node "<skilldir>/runtime/gandalf-run.mjs"``) feeding the raw draft on stdin,
    capturing the GRADED ``advisor-output.json`` on stdout. ``node`` is an
    EXTERNAL CLI through a seam (like git/gh) — never a Python dep. A parse
    failure / non-zero exit / absent host is an honest **error run**
    (``ok:false``, ``reason``) — never fabricated, never raised to the caller,
    never crashes a render.

Store layout (decision #3 — served artifacts MUST live at PROJECT ROOT because
``report_viewer.resolve_project_artifact`` hard-rejects any path under
``.anchor``):

  <folder>/gandalf/run-<ts>/report.md          (full rendered schema)
  <folder>/gandalf/run-<ts>/exec-summary.md     (verdict + top findings/elevations)
  <folder>/gandalf/run-<ts>/advisor-output.json (the graded schema, audit truth)

The internal INDEX lives at ``.anchor/projects/<id>/gandalf/index.json`` (read
directly by the GET endpoint, never via ``/artifact``), newest-first, stamped
with ``GANDALF_INDEX_SCHEMA_VERSION``, written under ``paths.WRITE_LOCK``.

Stdlib only. No third-party imports.
"""

import fnmatch
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import paths as _paths
import job_runner as _jr
import summarizer as _summarizer


# ── Active-run registry (Wave 1: active cancel) ──────────────────────────────
#: In-flight Gandalf runs, keyed by run_id → {"job_id", "proc", "cancelled"}.
#: Mutated only under ``_ACTIVE_RUNS_LOCK``. ``run_gandalf`` registers a run on
#: start and pops it in its ``finally``; ``cancel_run`` flips ``cancelled`` and
#: tree-kills the live Stage-A job / Stage-B subprocess.
_ACTIVE_RUNS: dict = {}
_ACTIVE_RUNS_LOCK = threading.Lock()


# ── Constants / seams ────────────────────────────────────────────────────────

#: Env var pointing at the on-disk Gandalf skill folder (its ``SKILL.md`` +
#: ``runtime/gandalf-run.mjs`` live here). Resolves BLOCKER B — ``/gandalf`` is
#: not auto-discoverable, so the protocol is read from this dir.
SKILL_DIR_ENV = "ANCHOR_GANDALF_SKILL_DIR"
DEFAULT_SKILL_DIR = r"C:\dev\Skill Foundry\skills\gandalf"

#: Env var overriding the Stage-B host command. When unset, the default is
#: ``node "<skilldir>/runtime/gandalf-run.mjs"``. ``node`` is an external CLI
#: through a seam (like git/gh) — never a Python dep. Tests point this at a
#: Python stub emitting a canned graded advisor-output.json.
HOST_CMD_ENV = "ANCHOR_GANDALF_HOST_CMD"

#: Env var overriding the Stage-A model timeout (seconds). Pointing Gandalf at a
#: whole project folder is an unbounded agentic run, so this is GENEROUS and
#: Gandalf-specific — NOT summarizer's 60s. An honest degraded run on timeout,
#: never a hang.
TIMEOUT_ENV = "ANCHOR_GANDALF_TIMEOUT"
# 900s (was 600): a real run on a LARGE repo (aurora) landed at ~515s with
# run-to-run variance that tripped the old 600s ceiling. The run is a background
# daemon (never blocks a render), so a generous default just lets big repos finish;
# override per-run via ANCHOR_GANDALF_TIMEOUT.
DEFAULT_TIMEOUT = 900.0

#: Project-root subdir holding the served run artifacts (NOT under .anchor, which
#: /artifact rejects). One ``run-<ts>/`` per run.
GANDALF_DIRNAME = "gandalf"

#: Internal index (under the per-project store) + its filenames. NEVER served via
#: /artifact — read directly by the GET endpoint.
INDEX_DIRNAME = "gandalf"
INDEX_FILENAME = "index.json"

#: Per-run artifact filenames.
REPORT_MD = "report.md"
EXEC_SUMMARY_MD = "exec-summary.md"
ADVISOR_OUTPUT_JSON = "advisor-output.json"

#: Index schema version. BUMP when a fix changes what a correct index record
#: looks like; ``list_runs`` normalizes older/missing versions with honest
#: defaults so stale indexes don't crash the read path.
GANDALF_INDEX_SCHEMA_VERSION = 1

#: The 9 required top-level keys of a graded advisor-output (per
#: ``schema/advisor-output.schema.json``). A graded output missing any of these
#: is a malformed host result → an honest error run.
_REQUIRED_TOP_KEYS = (
    "schema_version", "cross_model", "degraded", "reasoning", "verdict",
    "findings", "nitpicks", "elevations", "risk_labels",
)

#: How many bytes of SKILL.md to embed in the Stage-A prompt (bounded).
_MAX_SKILL_BYTES = 64 * 1024


# ── ContextSizer / Ignore Helpers (Wave 1) ──────────────────────────────────

def _load_anchorignore(folder_path) -> list:
    """Read .anchorignore patterns if present."""
    ignore_path = Path(folder_path) / ".anchorignore"
    patterns = []
    if ignore_path.is_file():
        try:
            with open(ignore_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
        except OSError:
            pass
    return patterns


def _should_ignore(rel_path: Path, patterns: list) -> bool:
    """Determine if a relative path matches any ignore pattern or standard skip dirs."""
    parts_lower = [p.lower() for p in rel_path.parts]
    for skip in {".git", ".anchor", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".anchorignore", "gandalf"}:
        if skip in parts_lower:
            return True

    rel_str = rel_path.as_posix()
    rel_str_lower = rel_str.lower()

    for pattern in patterns:
        clean_pat = pattern.rstrip('/')
        clean_pat_lower = clean_pat.lower()

        # Check components of the path
        for part in rel_path.parts:
            part_lower = part.lower()
            if fnmatch.fnmatch(part, clean_pat) or fnmatch.fnmatch(part_lower, clean_pat_lower):
                return True

        # Check full relative path
        if fnmatch.fnmatch(rel_str, clean_pat) or fnmatch.fnmatch(rel_str_lower, clean_pat_lower):
            return True
        if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(rel_str_lower, pattern.lower()):
            return True

    return False


def scan_project_context(folder_path) -> float:
    """Recursively scan the directory (respecting .anchorignore) and compute total_bytes / 4."""
    root = Path(folder_path).resolve()
    if not root.is_dir():
        return 0.0

    patterns = _load_anchorignore(folder_path)
    total_bytes = 0

    for dirpath, dirnames, filenames in os.walk(str(root)):
        try:
            rel_dirpath = Path(dirpath).resolve().relative_to(root)
        except (ValueError, OSError):
            continue

        # Prune directories in-place
        keep_dirs = []
        for d in dirnames:
            rel_d = rel_dirpath / d
            if not _should_ignore(rel_d, patterns):
                keep_dirs.append(d)
        dirnames[:] = keep_dirs

        for fname in filenames:
            rel_file = rel_dirpath / fname
            if _should_ignore(rel_file, patterns):
                continue

            fpath = Path(dirpath) / fname
            try:
                total_bytes += fpath.stat().st_size
            except OSError:
                pass

    return total_bytes / 4.0


# ── Path helpers ─────────────────────────────────────────────────────────────

def _skill_dir() -> Path:
    raw = (os.environ.get(SKILL_DIR_ENV) or "").strip() or DEFAULT_SKILL_DIR
    return Path(raw)


def _timeout() -> float:
    raw = (os.environ.get(TIMEOUT_ENV) or "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT


def _runs_dir(folder_path) -> Path:
    """``<folder>/gandalf/`` — the project-root dir holding run-<ts>/ subdirs."""
    return Path(folder_path) / GANDALF_DIRNAME


def _index_path(folder_path, project_id) -> Path:
    """``<folder>/.anchor/projects/<id>/gandalf/index.json`` — the internal index."""
    return (_summarizer._project_store_dir(folder_path, project_id)
            / INDEX_DIRNAME / INDEX_FILENAME)


def _host_cmd_argv():
    """Resolve the Stage-B host command as an argv list.

    ``ANCHOR_GANDALF_HOST_CMD`` wins (tests point it at a Python stub); else the
    default ``node "<skilldir>/runtime/gandalf-run.mjs"``. Split survives Windows
    backslash paths (reuses job_runner's splitter).
    """
    override = (os.environ.get(HOST_CMD_ENV) or "").strip()
    if override:
        return _jr._shlex_split(override)
    host_mjs = _skill_dir() / "runtime" / "gandalf-run.mjs"
    return ["node", str(host_mjs)]


# ── Stage A — build the embedded-protocol prompt ─────────────────────────────

def _read_skill_protocol() -> str:
    """Read ``SKILL.md`` from the skill dir (bounded). Honest empty on absence."""
    try:
        p = _skill_dir() / "SKILL.md"
        if not p.is_file():
            return ""
        return p.read_text(encoding="utf-8", errors="replace")[:_MAX_SKILL_BYTES]
    except OSError:
        return ""


def _build_prompt(folder_path) -> str:
    """Stage-A prompt = the Gandalf protocol + the raw-draft instruction."""
    protocol = _read_skill_protocol()
    parts = []
    if protocol:
        parts.append("You are running the Gandalf deep-think advisor skill. Its "
                     "protocol follows verbatim:\n\n" + protocol)
    else:
        parts.append("You are running the Gandalf deep-think advisor skill.")
    parts.append(
        "Analyze the project at the following folder and emit ONLY the RAW draft "
        "JSON per the skill's runtime/RAW-DRAFT-CONTRACT.md as your FINAL message. "
        "Do NOT self-assign tiers or refutation stamps — the host applies them.\n\n"
        f"Project folder: {folder_path}")
    return "\n\n".join(parts)


# ── JSON extraction (last balanced top-level object) ─────────────────────────

def _last_balanced_json(text: str):
    """Locate + parse the LAST balanced top-level JSON object in ``text``.

    Scans for ``{`` ... matching ``}`` spans at brace-depth 0 (string/escape
    aware so braces inside strings don't confuse the depth count) and returns the
    parsed value of the LAST one that ``json.loads`` accepts. Returns ``None`` if
    none parse. Stdlib only; never raises.
    """
    if not text:
        return None
    spans = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append((start, i + 1))
                    start = -1
    for s, e in reversed(spans):
        try:
            obj = json.loads(text[s:e])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


# ── Stage A — run the model, recover the raw draft ───────────────────────────

def _run_stage_a(folder_path, env=None, run_id=None):
    """Run Stage A → ``(raw_draft_dict, reason)``.

    On any failure (job failed/timed-out, no parseable JSON) returns
    ``(None, "<reason>")``. Never raises.
    """
    folder = str(folder_path)
    prompt = _build_prompt(folder)
    try:
        rec = _jr.launch("research", cwd=folder, prompt=prompt,
                         output_dir=folder, env=(env or None),
                         permission_mode="plan")
    except Exception:
        return None, "launch-failed"
    jid = rec["job_id"]
    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS:
                if _ACTIVE_RUNS[run_id]["cancelled"]:
                    try:
                        _jr.cancel(jid)
                    except Exception:
                        pass
                    return None, "cancelled"
                _ACTIVE_RUNS[run_id]["job_id"] = jid
    _jr.wait(jid, timeout=_timeout())
    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS and _ACTIVE_RUNS[run_id]["cancelled"]:
                return None, "cancelled"
    final = _jr.load_record(jid) or {}
    if final.get("status") == "cancelled":
        return None, "cancelled"
    if final.get("status") != _jr.STATUS_DONE:
        return None, "stage-a-run-failed:" + str(final.get("status") or "unknown")
    lines = _jr.all_lines(jid)
    text_lines = _jr.extract_assistant_text(lines)
    draft = _last_balanced_json("\n".join(text_lines))
    if not isinstance(draft, dict):
        return None, "stage-a-unparseable-draft"
    return draft, None


# ── Stage B — run the host, recover the graded output ────────────────────────

def _run_stage_b(raw_draft, run_id=None):
    """Run Stage B (the host) on the raw draft → ``(graded_dict, reason)``.

    Feeds the raw draft on stdin, captures the graded advisor-output.json on
    stdout. A non-zero exit / absent host / unparseable output is an honest
    error (returns ``(None, "<reason>")``). Never raises.
    """
    argv = _host_cmd_argv()
    payload = json.dumps(raw_draft, ensure_ascii=False)
    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS and _ACTIVE_RUNS[run_id]["cancelled"]:
                return None, "cancelled"
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
    except FileNotFoundError:
        return None, "host-unavailable"
    except (OSError, subprocess.SubprocessError):
        return None, "host-spawn-failed"

    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS:
                if _ACTIVE_RUNS[run_id]["cancelled"]:
                    try:
                        import proc_probe
                        proc_probe.tree_kill(proc.pid)
                    except Exception:
                        pass
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return None, "cancelled"
                _ACTIVE_RUNS[run_id]["proc"] = proc

    try:
        stdout, stderr = proc.communicate(input=payload, timeout=_timeout())
    except subprocess.TimeoutExpired:
        try:
            import proc_probe
            proc_probe.tree_kill(proc.pid)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        return None, "host-timeout"
    except Exception:
        return None, "host-spawn-failed"

    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS and _ACTIVE_RUNS[run_id]["cancelled"]:
                return None, "cancelled"

    if proc.returncode != 0:
        err = (stderr or "").strip().splitlines()
        reason = "host-nonzero-exit"
        if err:
            reason += ":" + err[-1][:200]
        return None, reason
    graded = _last_balanced_json(stdout or "")
    if not isinstance(graded, dict):
        return None, "host-unparseable-output"
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in graded]
    if missing:
        return None, "host-output-missing-keys:" + ",".join(missing)
    return graded, None


# ── Render helpers ───────────────────────────────────────────────────────────

def _one_line_verdict(graded) -> str:
    """The cleaned one-line verdict (pinned to the top-level ``verdict`` field)."""
    val = graded.get("verdict") or ""
    # Strip any markdown / formatting.
    val = val.replace("*", "").replace("`", "").strip()
    return val[:200]


def _severity_rank(item) -> int:
    """Helper: order findings/nitpicks/elevations by severity."""
    r = item.get("severity") or ""
    if r == "critical":
        return 4
    if r == "high":
        return 3
    if r == "medium":
        return 2
    return 1


def _render_full_report(graded, *, run_id="", when=None) -> str:
    """Render the full markdown report."""
    date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when or time.time()))
    lines = [
        f"# Gandalf Read Report — {run_id or 'run'}\n",
        f"*Generated:* {date_str}\n",
        f"## Verdict\n**{_one_line_verdict(graded)}**\n",
        "## Reasoning\n",
        str(graded.get("reasoning") or ""),
        "\n## Findings & Risks\n",
    ]
    findings = sorted(graded.get("findings") or [], key=_severity_rank, reverse=True)
    if not findings:
        lines.append("*No major findings.*")
    for f in findings:
        sev = (f.get("severity") or "info").upper()
        lines.append(f"### [{sev}] {f.get('title') or 'Finding'}")
        lines.append(str(f.get("description") or ""))
        remedy = f.get("remedy")
        if remedy:
            lines.append(f"\n*Remedy:* {remedy}")
        lines.append("")
    return "\n".join(lines)


def _render_exec_summary(graded, *, run_id="", when=None) -> str:
    """Render the executive summary markdown (inline dashboard)."""
    lines = [
        f"**Verdict:** {_one_line_verdict(graded)}\n",
        "### Key Findings\n",
    ]
    findings = sorted(graded.get("findings") or [], key=_severity_rank, reverse=True)[:3]
    if not findings:
        lines.append("*No major findings.*")
    for f in findings:
        sev = (f.get("severity") or "info").upper()
        lines.append(f"- **[{sev}]** {f.get('title') or 'Finding'}")
    return "\n".join(lines)


# ── Index store ──────────────────────────────────────────────────────────────

def _load_index(folder_path, project_id) -> list:
    """Load the raw index list (newest-first). Honest empty on absence/corruption."""
    p = _index_path(folder_path, project_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        data = data.get("runs") or []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def _append_index(folder_path, project_id, record: dict) -> None:
    """Prepend a record (newest-first) to the index under the write lock."""
    with _paths.WRITE_LOCK:
        p = _index_path(folder_path, project_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        runs = _load_index(folder_path, project_id)
        runs.insert(0, record)
        
        # Cap / auto-prune to newest N (default 20, or env-override)
        max_runs_str = os.environ.get("ANCHOR_GANDALF_MAX_RUNS", "20").strip()
        try:
            max_runs = int(max_runs_str)
        except ValueError:
            max_runs = 20
        if max_runs > 0:
            runs = runs[:max_runs]
            
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(runs, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)


def _add_gitignore_best_effort(folder_path) -> None:
    """Best-effort: add ``gandalf/`` to the project ``.gitignore`` so regenerable
    analysis doesn't clutter git status. Never raises."""
    try:
        gi = Path(folder_path) / ".gitignore"
        existing = ""
        if gi.exists():
            existing = gi.read_text(encoding="utf-8", errors="replace")
        lines = [ln.strip() for ln in existing.splitlines()]
        if "gandalf/" in lines or "/gandalf/" in lines or "gandalf" in lines:
            return
        sep = "" if (existing == "" or existing.endswith("\n")) else "\n"
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(sep + "gandalf/\n")
    except OSError:
        pass


# ── Public engine ────────────────────────────────────────────────────────────

def run_gandalf(folder_path, project_id, *, force=False, env=None, status_cb=None) -> dict:
    """Run one full two-stage Gandalf analysis and store the result."""
    folder = str(folder_path)
    pid = str(project_id)
    ts = time.time()
    run_id = "run-" + str(int(ts * 1000))
    run_rel = f"{GANDALF_DIRNAME}/{run_id}"

    try:
        import session_registry
        session_registry.register_session(
            project_id=pid,
            lane="gandalf",
            status=session_registry.STATUS_RUNNING,
            session_id=run_id
        )
    except Exception:
        pass

    with _ACTIVE_RUNS_LOCK:
        # folder/project_id are carried so cancel_run can record the cancelled
        # outcome into the index without waiting for this worker to unwind.
        _ACTIVE_RUNS[run_id] = {
            "job_id": None, "proc": None, "cancelled": False,
            "folder": folder, "project_id": pid, "index_recorded": False,
        }

    ok = False
    reason = "unknown"
    graded = None
    
    try:
        # Check if cancelled early
        with _ACTIVE_RUNS_LOCK:
            is_cancelled = _ACTIVE_RUNS[run_id]["cancelled"]
        if is_cancelled:
            reason = "cancelled"
        else:
            if status_cb: status_cb("Reading files (Stage A)...")

            # Wave 1: ContextSizer & Dynamic Router
            context_size = scan_project_context(folder)
            frontier_max_str = os.environ.get("ANCHOR_FRONTIER_MAX", "100000").strip()
            try:
                frontier_max = float(frontier_max_str)
            except ValueError:
                frontier_max = 100000.0

            actual_env = dict(env) if env is not None else {}
            if context_size > frontier_max:
                actual_env["GEMINI_MODEL"] = "gemini-1.5-pro"
                actual_env["TRIO_MODEL"] = "gemini-1.5-pro"

            draft, reason = _run_stage_a(folder, env=actual_env, run_id=run_id)
            
            with _ACTIVE_RUNS_LOCK:
                is_cancelled = _ACTIVE_RUNS[run_id]["cancelled"]
            if is_cancelled:
                reason = "cancelled"
            elif draft is not None:
                if status_cb: status_cb("Synthesizing (Stage B)...")
                graded, reason = _run_stage_b(draft, run_id=run_id)

            with _ACTIVE_RUNS_LOCK:
                is_cancelled = _ACTIVE_RUNS[run_id]["cancelled"]
            if is_cancelled:
                reason = "cancelled"

        ok = (graded is not None) and (reason != "cancelled")

        report_rel = None
        exec_rel = None
        verdict = ""
        degraded = True
        cross_model = False

        if ok:
            verdict = _one_line_verdict(graded)
            degraded = bool(graded.get("degraded"))
            cross_model = bool(graded.get("cross_model"))
            try:
                run_dir = _runs_dir(folder) / run_id
                run_dir.mkdir(parents=True, exist_ok=True)
                report_md = _render_full_report(graded, run_id=run_id, when=ts)
                exec_md = _render_exec_summary(graded, run_id=run_id, when=ts)
                (run_dir / REPORT_MD).write_text(report_md, encoding="utf-8")
                (run_dir / EXEC_SUMMARY_MD).write_text(exec_md, encoding="utf-8")
                (run_dir / ADVISOR_OUTPUT_JSON).write_text(
                    json.dumps(graded, indent=2, ensure_ascii=False),
                    encoding="utf-8")
                report_rel = f"{run_rel}/{REPORT_MD}"
                exec_rel = f"{run_rel}/{EXEC_SUMMARY_MD}"
                _add_gitignore_best_effort(folder)
            except OSError as exc:
                ok = False
                reason = "artifact-write-failed:" + str(exc)[:160]
                report_rel = None
                exec_rel = None

        record = {
            "schema_version": GANDALF_INDEX_SCHEMA_VERSION,
            "run_id": run_id,
            "ts": ts,
            "ok": bool(ok),
            "verdict": verdict,
            "degraded": bool(degraded),
            "cross_model": bool(cross_model),
            "report_rel": report_rel,
            "exec_rel": exec_rel,
            "advisor_rel": (f"{run_rel}/{ADVISOR_OUTPUT_JSON}" if ok else None),
            "session_id": run_id,
            "status": "cancelled" if reason == "cancelled" else ("done" if ok else "failed"),
        }
        if not ok:
            record["reason"] = reason or "unknown"

        # If cancel_run already recorded the cancelled outcome in the index
        # (the worker may still be unwinding a killed Stage-A/B), don't write a
        # duplicate record for the same run_id.
        already_recorded = False
        with _ACTIVE_RUNS_LOCK:
            r = _ACTIVE_RUNS.get(run_id)
            if r and r.get("index_recorded"):
                already_recorded = True
        if not already_recorded:
            try:
                _append_index(folder, pid, record)
            except Exception:
                # Even if the index write somehow fails, return the honest result.
                pass

        out = dict(record)
        out["ok"] = bool(ok)
        if not ok:
            out["reason"] = reason or "unknown"
        return out

    finally:
        try:
            import session_registry
            with _ACTIVE_RUNS_LOCK:
                is_cancelled = _ACTIVE_RUNS[run_id]["cancelled"]
            if is_cancelled or reason == "cancelled":
                st = "cancelled"
            else:
                st = session_registry.STATUS_DONE if ok else session_registry.STATUS_FAILED
            session_registry.update_session(run_id, status=st)
        except Exception:
            pass

        with _ACTIVE_RUNS_LOCK:
            _ACTIVE_RUNS.pop(run_id, None)


def run_gandalf_if_absent(folder_path, project_id, env=None, status_cb=None) -> dict:
    """First-scan idempotent: run Gandalf ONLY if no prior run exists."""
    try:
        if _load_index(folder_path, project_id):
            return {"ok": True, "skipped": True, "reason": "prior-run-exists"}
    except Exception:
        pass
    return run_gandalf(folder_path, project_id, env=env, status_cb=status_cb)


# ── Read seams (SAFE projections — never absolute paths) ─────────────────────

def _safe_run_view(record: dict) -> dict:
    """SAFE projection of one index record (no absolute paths)."""
    r = record if isinstance(record, dict) else {}
    view = {
        "run_id": str(r.get("run_id") or ""),
        "ts": r.get("ts"),
        "ok": bool(r.get("ok")),
        "verdict": str(r.get("verdict") or ""),
        "degraded": bool(r.get("degraded", True)),
        "cross_model": bool(r.get("cross_model", False)),
        "report_rel": r.get("report_rel"),
        "exec_rel": r.get("exec_rel"),
        "advisor_rel": r.get("advisor_rel"),
    }
    reason = r.get("reason")
    if reason:
        view["reason"] = str(reason)
    return view


def list_runs(folder_path, project_id) -> list:
    """Newest-first SAFE projections of the project's Gandalf runs."""
    runs = _load_index(folder_path, project_id)
    return [_safe_run_view(r) for r in runs]


def get_run(folder_path, project_id, run_id) -> dict:
    """The SAFE projection of one run by id, or ``None``. Read-only."""
    for r in _load_index(folder_path, project_id):
        if str(r.get("run_id") or "") == str(run_id):
            return _safe_run_view(r)
    return None


def delete_run(folder_path, project_id, run_id) -> bool:
    """Remove a run from the index by run_id."""
    with _paths.WRITE_LOCK:
        runs = _load_index(folder_path, project_id)
        filtered = [r for r in runs if str(r.get("run_id") or "") != str(run_id)]
        if len(filtered) == len(runs):
            return False
        
        # Also remove the run directory on disk if it exists
        try:
            run_dir = _runs_dir(folder_path) / run_id
            if run_dir.is_dir():
                shutil.rmtree(str(run_dir), ignore_errors=True)
        except Exception:
            pass

        p = _index_path(folder_path, project_id)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(filtered, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        return True


def cancel_run(run_id: str) -> bool:
    """Active cancel (tree-kill) an in-flight Gandalf run."""
    with _ACTIVE_RUNS_LOCK:
        run = _ACTIVE_RUNS.get(run_id)
        if not run:
            try:
                import session_registry
                rec = session_registry.get_session(run_id)
                if rec and rec.get("status") == session_registry.STATUS_RUNNING:
                    session_registry.update_session(run_id, status="cancelled")
            except Exception:
                pass
            return False

        run["cancelled"] = True

        # 1) If in Stage A (job_runner job is active)
        job_id = run.get("job_id")
        if job_id:
            try:
                import job_runner
                job_runner.cancel(job_id)
            except Exception:
                pass

        # 2) If in Stage B (subprocess is active)
        proc = run.get("proc")
        if proc:
            try:
                pid = proc.pid
                if pid:
                    import proc_probe
                    proc_probe.tree_kill(pid)
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass

        # Update the session registry record to cancelled
        try:
            import session_registry
            session_registry.update_session(run_id, status="cancelled")
        except Exception:
            pass

        # Record the cancelled outcome in the gandalf index now (Wave 1: active
        # cancel "records the cancelled outcome"). The worker thread may still be
        # unwinding a tree-killed child, so record here and mark it so the worker
        # does not write a duplicate record for the same run_id.
        folder = run.get("folder")
        pid = run.get("project_id")
        if folder and pid:
            try:
                _append_index(folder, pid, {
                    "schema_version": GANDALF_INDEX_SCHEMA_VERSION,
                    "run_id": run_id,
                    "ts": time.time(),
                    "ok": False,
                    "verdict": "",
                    "degraded": True,
                    "cross_model": False,
                    "report_rel": None,
                    "exec_rel": None,
                    "advisor_rel": None,
                    "session_id": run_id,
                    "status": "cancelled",
                    "reason": "cancelled",
                })
                run["index_recorded"] = True
            except Exception:
                pass

        return True


def cancel_gandalf_run(project_id) -> bool:
    """Look up the running run by project_id and cancel it."""
    target_run_id = None
    with _ACTIVE_RUNS_LOCK:
        for run_id, run in _ACTIVE_RUNS.items():
            if str(run.get("project_id")) == str(project_id):
                target_run_id = run_id
                break
    if target_run_id:
        # Flip the cancelled flag + tree-kill (Stage-A job / Stage-B proc). Do NOT
        # pop _ACTIVE_RUNS here: the run_gandalf worker still reads the cancelled
        # flag to bail out, and its finally is what pops the entry and finalizes the
        # session registry. Popping early KeyErrors that finally (stuck "running")
        # and races the worker's cancel check (job runs to completion).
        return cancel_run(target_run_id)
    return False
