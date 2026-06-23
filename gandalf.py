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

import json
import os
import subprocess
import time
from pathlib import Path

import paths as _paths
import job_runner as _jr
import summarizer as _summarizer


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
DEFAULT_TIMEOUT = 600.0

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

def _run_stage_a(folder_path, env=None):
    """Run Stage A → ``(raw_draft_dict, reason)``.

    On any failure (job failed/timed-out, no parseable JSON) returns
    ``(None, "<reason>")``. Never raises.
    """
    folder = str(folder_path)
    prompt = _build_prompt(folder)
    try:
        rec = _jr.launch("research", cwd=folder, prompt=prompt,
                         output_dir=folder, env=(env or None))
    except Exception:
        return None, "launch-failed"
    jid = rec["job_id"]
    _jr.wait(jid, timeout=_timeout())
    final = _jr.load_record(jid) or {}
    if final.get("status") != _jr.STATUS_DONE:
        return None, "stage-a-run-failed:" + str(final.get("status") or "unknown")
    lines = _jr.all_lines(jid)
    text_lines = _jr.extract_assistant_text(lines)
    draft = _last_balanced_json("\n".join(text_lines))
    if not isinstance(draft, dict):
        return None, "stage-a-unparseable-draft"
    return draft, None


# ── Stage B — run the host, recover the graded output ────────────────────────

def _run_stage_b(raw_draft):
    """Run Stage B (the host) on the raw draft → ``(graded_dict, reason)``.

    Feeds the raw draft on stdin, captures the graded advisor-output.json on
    stdout. A non-zero exit / absent host / unparseable output is an honest
    error (returns ``(None, "<reason>")``). Never raises.
    """
    argv = _host_cmd_argv()
    payload = json.dumps(raw_draft, ensure_ascii=False)
    try:
        proc = subprocess.run(
            argv,
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_timeout(),
        )
    except FileNotFoundError:
        return None, "host-unavailable"
    except (OSError, subprocess.SubprocessError):
        return None, "host-spawn-failed"
    except subprocess.TimeoutExpired:
        return None, "host-timeout"
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        reason = "host-nonzero-exit"
        if err:
            reason += ":" + err[-1][:200]
        return None, reason
    graded = _last_balanced_json(proc.stdout or "")
    if not isinstance(graded, dict):
        return None, "host-unparseable-output"
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in graded]
    if missing:
        return None, "host-output-missing-keys:" + ",".join(missing)
    return graded, None


# ── Render helpers ───────────────────────────────────────────────────────────

def _one_line_verdict(graded) -> str:
    """The cleaned one-line verdict (pinned to the top-level ``verdict`` field)."""
    if not isinstance(graded, dict):
        return ""
    verdict = graded.get("verdict") or ""
    return _summarizer.short_summary_text(str(verdict))


def _severity_rank(item) -> int:
    order = {"critical": 0, "major": 1, "minor": 2}
    return order.get(str((item or {}).get("severity") or "").lower(), 3)


def _render_full_report(graded, *, run_id="", when=None) -> str:
    """Render the full graded schema as readable markdown. Defensive .get()."""
    g = graded if isinstance(graded, dict) else {}
    lines = ["# Gandalf read"]
    if run_id:
        lines.append("")
        lines.append(f"> Run `{run_id}`"
                     + (f" · {time.strftime('%Y-%m-%d %H:%M', time.localtime(when))}"
                        if when else ""))
    verdict = str(g.get("verdict") or "").strip()
    if verdict:
        lines += ["", "## Verdict", "", verdict]
    chips = []
    if g.get("degraded"):
        chips.append("degraded")
    chips.append("cross_model:" + ("true" if g.get("cross_model") else "false"))
    lines += ["", "## Honesty", "", "- " + " · ".join(chips)]
    reasoning = str(g.get("reasoning") or "").strip()
    if reasoning:
        lines += ["", "## Reasoning", "", reasoning]

    findings = [f for f in (g.get("findings") or []) if isinstance(f, dict)]
    if findings:
        lines += ["", "## Findings", ""]
        for f in sorted(findings, key=_severity_rank):
            sev = str(f.get("severity") or "").strip()
            kind = str(f.get("kind") or "").strip()
            rung = str(f.get("rung") or "").strip()
            tag = " · ".join(x for x in (kind, sev, rung) if x)
            fid = str(f.get("id") or "").strip()
            head = f"- **{fid}**" + (f" ({tag})" if tag else "")
            lines.append(head)
            v = str(f.get("verdict") or "").strip()
            if v:
                lines.append(f"  - {v}")

    elevations = [e for e in (g.get("elevations") or []) if isinstance(e, dict)]
    if elevations:
        lines += ["", "## Elevations", ""]
        for e in elevations:
            eid = str(e.get("id") or "").strip()
            tier = str(e.get("tier") or "").strip()
            val = str(e.get("value_if_true") or "").strip()
            tag = " · ".join(x for x in (tier, val) if x)
            head = f"- **{eid}**" + (f" ({tag})" if tag else "")
            lines.append(head)
            v = str(e.get("verdict") or "").strip()
            if v:
                lines.append(f"  - {v}")

    nitpicks = [n for n in (g.get("nitpicks") or []) if isinstance(n, dict)]
    if nitpicks:
        lines += ["", "## Nitpicks", ""]
        for n in nitpicks:
            nid = str(n.get("id") or "").strip()
            v = str(n.get("verdict") or "").strip()
            lines.append(f"- **{nid}** {v}".rstrip())

    risk = [r for r in (g.get("risk_labels") or []) if isinstance(r, dict)]
    if risk:
        lines += ["", "## Risk labels", ""]
        for r in risk:
            leg = str(r.get("leg") or "").strip()
            tier = str(r.get("tier") or "").strip()
            lines.append(f"- {leg}: {tier}".rstrip())

    return "\n".join(lines) + "\n"


def _render_exec_summary(graded, *, run_id="", when=None) -> str:
    """Render the executive summary: verdict + top findings-by-severity + top
    elevations. Defensive .get() everywhere."""
    g = graded if isinstance(graded, dict) else {}
    lines = ["# Gandalf — executive summary"]
    if run_id:
        lines.append("")
        lines.append(f"> Run `{run_id}`"
                     + (f" · {time.strftime('%Y-%m-%d %H:%M', time.localtime(when))}"
                        if when else ""))
    verdict = str(g.get("verdict") or "").strip()
    if verdict:
        lines += ["", "## Verdict", "", verdict]
    chips = []
    if g.get("degraded"):
        chips.append("degraded")
    chips.append("cross_model:" + ("true" if g.get("cross_model") else "false"))
    lines += ["", "_" + " · ".join(chips) + "_"]

    findings = [f for f in (g.get("findings") or []) if isinstance(f, dict)]
    top = sorted(findings, key=_severity_rank)[:5]
    if top:
        lines += ["", "## Top findings", ""]
        for f in top:
            sev = str(f.get("severity") or "").strip()
            fid = str(f.get("id") or "").strip()
            v = str(f.get("verdict") or "").strip()
            head = f"- **{fid}**" + (f" ({sev})" if sev else "")
            if v:
                head += f" — {v}"
            lines.append(head)

    elevations = [e for e in (g.get("elevations") or []) if isinstance(e, dict)][:5]
    if elevations:
        lines += ["", "## Top elevations", ""]
        for e in elevations:
            eid = str(e.get("id") or "").strip()
            v = str(e.get("verdict") or "").strip()
            head = f"- **{eid}**" + (f" — {v}" if v else "")
            lines.append(head)

    return "\n".join(lines) + "\n"


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

def run_gandalf(folder_path, project_id, *, force=False, env=None) -> dict:
    """Run one full two-stage Gandalf analysis and store the result.

    Stage A (model, through ``ANCHOR_RUNNER_CMD``) → the RAW draft → Stage B (the
    host, through ``ANCHOR_GANDALF_HOST_CMD``) → the GRADED advisor-output. Render
    ``report.md`` + ``exec-summary.md``, write them + ``advisor-output.json`` to
    ``<folder>/gandalf/run-<ts>/``, append a SAFE record to the internal index.

    Returns a dict carrying at least ``{ok, run_id, ts, reason?}``. On a Stage-A
    or Stage-B failure an honest **error run** is recorded (``ok:false`` + a
    ``reason``, no fabricated verdict) and still appended to the index so the tab
    can show the honest failed row. NEVER raises to the caller. ``force`` is
    accepted for signature parity (every call is a fresh run — history accumulates).
    """
    folder = str(folder_path)
    pid = str(project_id)
    ts = time.time()
    # A run id stable + filesystem-safe: run-<unix-ms>.
    run_id = "run-" + str(int(ts * 1000))
    run_rel = f"{GANDALF_DIRNAME}/{run_id}"

    draft, reason = _run_stage_a(folder, env=env)
    graded = None
    if draft is not None:
        graded, reason = _run_stage_b(draft)

    ok = graded is not None

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
    }
    if not ok:
        record["reason"] = reason or "unknown"

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


def run_gandalf_if_absent(folder_path, project_id, env=None) -> dict:
    """First-scan idempotent: run Gandalf ONLY if no prior run exists.

    Returns ``{ok:True, skipped:True}`` when a prior run is present (no model
    call), else delegates to :func:`run_gandalf`. Never raises.
    """
    try:
        if _load_index(folder_path, project_id):
            return {"ok": True, "skipped": True, "reason": "prior-run-exists"}
    except Exception:
        pass
    return run_gandalf(folder_path, project_id, env=env)


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
    """Newest-first SAFE projections of the project's Gandalf runs.

    Each: ``ts · run_id · verdict · cross_model · degraded · ok · report_rel ·
    exec_rel · advisor_rel · reason?`` — NEVER an absolute path. Normalizes
    older/missing-schema records with honest defaults. Read-only; never raises.
    """
    runs = _load_index(folder_path, project_id)
    return [_safe_run_view(r) for r in runs]


def get_run(folder_path, project_id, run_id) -> dict:
    """The SAFE projection of one run by id, or ``None``. Read-only."""
    for r in _load_index(folder_path, project_id):
        if str(r.get("run_id") or "") == str(run_id):
            return _safe_run_view(r)
    return None
