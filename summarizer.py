#!/usr/bin/env python3
"""Anchor R&D session summarizer — validated, cached summaries (v2, Wave 6).

Clicking a session should open a nicely rendered markdown **summary** (goal ·
key decisions · files-with-links · findings · errors-overcome), generated **once
with multi-run validation** and **cached** so the same summary appears every time
— never the raw execution log (MASTER-PLAN §B).

Pipeline (frozen design — MASTER-PLAN "B. Cached, validated summaries"):

  a. EXTRACTION-SEED — deterministically pull anchors from the session's member
     docs (read each member's on-disk artifact, bounded): planning → North-Star /
     goal heading + key decisions; research → research question + findings
     section; build → what-was-built + Crucible docs referenced + errors /
     obstacles. The heading/title extraction reuses the brownfield_scan style
     (first markdown heading), stdlib only.
  b. GENERATE TWICE — run a bounded model call **through job_runner** (the
     ``ANCHOR_RUNNER_CMD`` seam, so ``tests/fake_claude.py`` drives it in tests
     — NEVER live ``claude`` directly) two times, each seeded by (a), producing
     two candidate structured summaries.
  c. VALIDATION PASS — drop any claim/line NOT grounded in the member docs (a
     claim is grounded iff its key terms appear in the seed / member text). This
     is a DETERMINISTIC grounding check in Python; it needs no model.
  d. CACHE — write ``summary.json`` (structured) + ``summary.md`` (rendered-ready
     markdown) under the session's store (small git-trackable JSON per C9; raw
     model logs stay ignored per C10). Return the cached structured summary.
  e. CACHE SEMANTICS — a second ``summarize_session`` for the same session
     returns the CACHED result WITHOUT running the model again (run-once). A
     ``force=True`` (regenerate) path re-runs the model and overwrites the cache.

Stdlib only. All model calls go through ``job_runner`` so they are exercised via
``fake_claude.py`` and the gate never invokes a live CLI.
"""

import json
import re
import threading
import time
from pathlib import Path

import paths as _paths
import effort_history as _eh
import job_runner as _jr
import report_viewer as _rv

#: Subdir (under a lane store dir) holding per-session cached summaries. A small
#: git-trackable JSON + rendered markdown live under ``summaries/<session_id>/``.
SUMMARIES_DIRNAME = "summaries"
SUMMARY_JSON = "summary.json"
SUMMARY_MD = "summary.md"

#: How many member docs to read, and how many bytes per doc, for the extraction
#: seed (bounded — mirrors brownfield_scan's conservative reads).
MAX_SEED_DOCS = 12
MAX_SEED_BYTES = 16 * 1024

#: How many model candidate runs to fuse (frozen design: generate TWICE).
GENERATE_RUNS = 2

#: Provenance marker for an IMPORTED (brownfield-discovered) session — its effort
#: is honestly ``None`` ("imported — no run metrics"), never fabricated (Wave 6).
#: Mirrors ``sessions.PROV_IMPORTED`` without a hard import cycle.
_SESS_IMPORTED = "imported"

#: A claim is grounded iff at least this fraction of its KEY TERMS (>=3 chars,
#: alphanumeric tokens) appear in the combined seed/member text. Raised from the
#: original 0.5 to a stricter 0.7 (FIX 3) so a claim must share a clear majority
#: of its content terms with the corpus, not merely half.
GROUNDING_MIN_RATIO = 0.7
#: Minimum number of GROUNDED key terms a claim must carry to be checkable /
#: kept at all (FIX 3). A claim with fewer than this many key terms found in the
#: corpus is treated as ungrounded — a single incidental shared word ("the",
#: "session") is not enough to anchor a whole claim.
GROUNDING_MIN_TERMS = 2


# ── Per-session generation lock (FIX 1: run-once under concurrency) ───────────
# The server is a ThreadingHTTPServer, so two requests for the SAME uncached
# session can race: both miss the cache and both run the model (2x GENERATE_RUNS).
# We serialize the cache-check → generate → write sequence PER (pid, lane,
# session_id) with a dedicated per-session lock, so unrelated summaries still run
# concurrently. ``_SESSION_LOCKS`` maps a session key → its Lock; ``_LOCKS_GUARD``
# is a tiny global lock that only guards creation/lookup of those per-session
# locks (held briefly, never across a model run).
_LOCKS_GUARD = threading.Lock()
_SESSION_LOCKS = {}


def _session_lock(folder_path, project_id, lane, session_id):
    """Return the dedicated Lock for one (folder, pid, lane, session) tuple.

    A process-wide registry of per-session locks (FIX 1). The global guard is
    held only for the dict lookup/insert — never while the model runs — so two
    DIFFERENT sessions never serialize against each other.
    """
    key = (str(folder_path), str(project_id), str(lane), str(session_id))
    with _LOCKS_GUARD:
        lk = _SESSION_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _SESSION_LOCKS[key] = lk
        return lk


# ── Lane-specific shape ──────────────────────────────────────────────────────
# Per MASTER-PLAN §B the seed shape is lane-specific:
#   research → question · findings · reports
#   planning → goal · key decisions · files-produced(links)
#   build    → what-was-built · Crucible docs referenced · errors-overcome · files
# We normalize the trio/store lane name first.

def _lane_kind(lane: str) -> str:
    sub = _eh._resolve_subdir(lane)
    if sub == "research":
        return "research"
    if sub == "planning":
        return "planning"
    if sub == "build":
        return "build"
    return sub


# ── Member artifact resolution (on-disk path for a member effort) ────────────

def _member_path(folder_path, project_id, lane, member) -> Path:
    """Resolve a member effort's on-disk artifact path (best-effort).

    - DISCOVERED members carry a folder-relative ``artifact_path`` → resolve
      against the project folder.
    - RUN members store their report under the effort dir / lane dir → use
      ``effort_history.detect_artifacts`` (report.md preferred).

    Returns a ``Path`` (may not exist) or ``None`` when nothing resolves.
    """
    rel = (member.get("artifact_path") or "").strip()
    if rel:
        try:
            return Path(folder_path) / rel
        except (TypeError, ValueError):
            return None
    jid = (member.get("job_id") or "").strip()
    arts = _eh.detect_artifacts(folder_path, project_id, lane, jid or None)
    if arts.get("md_path"):
        return Path(arts["md_path"])
    return None


def _read_bounded(path: Path) -> str:
    """Read up to MAX_SEED_BYTES of a small text file; never raises."""
    try:
        if not path.is_file():
            return ""
        if path.stat().st_size > 256 * 1024:
            # Bounded: only sip the head of a large doc.
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                return fh.read(MAX_SEED_BYTES)
        return path.read_text(encoding="utf-8", errors="ignore")[:MAX_SEED_BYTES]
    except OSError:
        return ""


# ── (a) Extraction seed ──────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
#: Section headings whose body we lift for each lane kind (case-insensitive
#: substring match on the heading text).
_SECTION_SIGNALS = {
    "research": ("research question", "question", "findings", "finding",
                 "conclusion", "summary", "results"),
    "planning": ("north star", "north-star", "goal", "objective", "decision",
                 "decisions", "key decision"),
    "build": ("what was built", "built", "deliverable", "crucible", "error",
              "errors", "obstacle", "obstacles", "overcome", "fix"),
}


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        m = _HEADING_RE.match(line.strip())
        if m:
            t = m.group(2).strip()
            if t:
                return t
    return ""


def _lift_sections(text: str, signals) -> list:
    """Return ``[(heading, body_excerpt)]`` for headings matching ``signals``.

    Body excerpt = the non-blank lines under the heading until the next heading,
    bounded to a few lines so the seed stays small.
    """
    lines = text.splitlines()
    out = []
    i = 0
    n = len(lines)
    while i < n:
        m = _HEADING_RE.match(lines[i].strip())
        if not m:
            i += 1
            continue
        heading = m.group(2).strip()
        hl = heading.lower()
        if any(sig in hl for sig in signals):
            body = []
            j = i + 1
            while j < n and not _HEADING_RE.match(lines[j].strip()):
                s = lines[j].strip()
                if s:
                    body.append(s)
                if len(body) >= 8:
                    break
                j += 1
            out.append((heading, " ".join(body)[:600]))
        i += 1
    return out


#: Heading signals (case-insensitive substring) whose body is the session's
#: North-Star / goal — lifted from a MASTER-PLAN member if present (v3 Wave 6).
_NORTH_STAR_SIGNALS = ("north star", "north-star", "objective", "goal",
                       "mission")


def extraction_seed(folder_path, project_id, lane, session) -> dict:
    """Deterministically pull anchors from the session's member docs (step a).

    Reads each member's on-disk artifact (bounded) and lifts lane-appropriate
    anchors: titles/first-headings of every member, plus the bodies of sections
    whose heading matches the lane signal set. Returns a structured seed::

        {"lane", "title", "members": [{job_id, title, rel}],
         "anchors": [{"heading", "body", "from"}], "when_run", "what_was_asked",
         "north_star", "text": "<combined text>"}

    ``text`` is the combined grounding corpus the validation pass checks claims
    against. The v3 Wave 6 fields — ``when_run`` (session date), ``what_was_asked``
    (the seed/intent from ``prompt_seed`` / first member), and ``north_star``
    (lifted from a MASTER-PLAN member's North-Star/goal heading) — are derived
    deterministically here so they survive into the cache. Stdlib only; never
    raises.
    """
    kind = _lane_kind(lane)
    signals = _SECTION_SIGNALS.get(kind, _SECTION_SIGNALS["planning"])
    members_out = []
    anchors = []
    corpus_parts = []
    north_star = ""
    members = session.get("member_files", []) or []
    for member in members[:MAX_SEED_DOCS]:
        path = _member_path(folder_path, project_id, lane, member)
        title = (member.get("title") or "").strip()
        rel = (member.get("artifact_path") or "").strip()
        text = _read_bounded(path) if path is not None else ""
        if text:
            corpus_parts.append(text)
            if not title:
                title = _first_heading(text)
            for heading, body in _lift_sections(text, signals):
                anchors.append({"heading": heading, "body": body,
                                "from": title or rel or
                                (member.get("job_id") or "")})
            # North-Star: prefer a MASTER-PLAN-like member's goal/north-star
            # section (reuses _lift_sections). First non-empty wins.
            if not north_star:
                is_master = ("master" in (title or "").lower()
                             or "master" in rel.lower()
                             or "master" in (member.get("kind") or "").lower())
                for _h, body in _lift_sections(text, _NORTH_STAR_SIGNALS):
                    if body and (is_master or not anchors):
                        north_star = body
                        break
                # Fall back to ANY member's north-star section if no master one.
                if not north_star:
                    for _h, body in _lift_sections(text, _NORTH_STAR_SIGNALS):
                        if body:
                            north_star = body
                            break
        if title:
            corpus_parts.append(title)
        members_out.append({
            "job_id": (member.get("job_id") or ""),
            "title": title,
            "rel": rel,
        })
    return {
        "lane": kind,
        "title": (session.get("title") or "").strip(),
        "members": members_out,
        "anchors": anchors,
        "when_run": _session_when_run(session),
        "what_was_asked": _session_what_was_asked(session, members_out),
        "north_star": north_star.strip(),
        "text": "\n".join(corpus_parts),
    }


def _session_when_run(session) -> str:
    """The session's run date (ISO ``YYYY-MM-DD``) from its timestamp, or ''.

    Uses the session ``timestamp`` (= ``max(created_at)`` across members, set by
    ``sessions.list_sessions``); falls back to the max member ``created_at``.
    """
    ts = session.get("timestamp")
    if not ts:
        for m in (session.get("member_files", []) or []):
            try:
                c = float(m.get("created_at", 0.0) or 0.0)
            except (TypeError, ValueError):
                c = 0.0
            if c > (ts or 0):
                ts = c
    try:
        ts = float(ts or 0.0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    except (ValueError, OSError):
        return ""


#: Max chars of the seed/intent surfaced as "what was asked" (bounded).
MAX_WHAT_ASKED = 500


def _session_what_was_asked(session, members_out) -> str:
    """The session's seed/intent (bounded): a member ``prompt_seed`` else title.

    Reads the first member carrying a ``prompt_seed`` (the run's intent); falls
    back to the session title / first member title. Bounded to ``MAX_WHAT_ASKED``.
    """
    for m in (session.get("member_files", []) or []):
        seed = (m.get("prompt_seed") or "").strip()
        if seed:
            return seed[:MAX_WHAT_ASKED]
    title = (session.get("title") or "").strip()
    if title:
        return title[:MAX_WHAT_ASKED]
    for m in members_out:
        t = (m.get("title") or "").strip()
        if t:
            return t[:MAX_WHAT_ASKED]
    return ""


def _aggregate_effort(session) -> dict:
    """Aggregate the session's run effort from its members' cost records.

    Returns ``{"tokens", "wall_clock_ms", "cost_usd", "runs"}`` summed over the
    session's RUN members' ``cost`` blocks (via ``effort_history`` accumulation),
    OR ``None`` for an IMPORTED session (``provenance == "imported"``) so the UI
    honestly shows "imported — no run metrics" — NEVER fabricated metrics.

    A session whose members carry no cost yet (run with no captured envelope)
    yields a zeroed-but-present effort (``runs`` = member count) — that is honest
    (the run happened; cost simply wasn't captured), distinct from imported=null.
    """
    if (session.get("provenance") or "") == _SESS_IMPORTED:
        return None
    members = session.get("member_files", []) or []
    # Defensive: a session whose every member is a discovered (brownfield) effort
    # is effectively imported — no run metrics, even if provenance wasn't set.
    if members and all(_eh.is_discovered(m) for m in members):
        return None
    acc = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
           "duration_ms": 0, "total_cost_usd": 0.0}
    runs = 0
    for m in members:
        if _eh.is_discovered(m):
            continue
        runs += 1
        cost = m.get("cost") or {}
        acc["input_tokens"] += int(cost.get("input_tokens", 0) or 0)
        acc["output_tokens"] += int(cost.get("output_tokens", 0) or 0)
        acc["total_tokens"] += int(cost.get("total_tokens", 0) or 0)
        acc["duration_ms"] += int(cost.get("duration_ms", 0) or 0)
        try:
            acc["total_cost_usd"] += float(cost.get("total_cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
    tokens = acc["total_tokens"] or (acc["input_tokens"] + acc["output_tokens"])
    return {
        "tokens": tokens,
        "wall_clock_ms": acc["duration_ms"],
        "cost_usd": round(acc["total_cost_usd"], 6),
        "runs": runs,
    }


def _seed_prompt(seed: dict) -> str:
    """Render the extraction seed as the bounded model prompt (step b input)."""
    lines = [
        f"Summarize this {seed['lane']} trio session as grounded bullet claims.",
        f"Title: {seed.get('title', '')}",
        "Anchors from the member documents:",
    ]
    for a in seed.get("anchors", []):
        lines.append(f"- {a['heading']}: {a['body']}")
    lines.append("Member documents:")
    for m in seed.get("members", []):
        lines.append(f"- {m.get('title') or m.get('rel') or m.get('job_id')}")
    return "\n".join(lines)


# ── (b) Generate (through the runner / ANCHOR_RUNNER_CMD seam) ────────────────

#: Sentinel returned by ``_run_model_once`` when the runner job FAILED or timed
#: out (FIX 2). Distinct from ``[]`` (the model ran OK but emitted no content):
#: a FAILED run must NEVER poison the cache — it is retryable.
RUN_FAILED = object()


def _run_model_once(folder_path, seed: dict):
    """Run ONE bounded model call through job_runner and return its claim lines.

    The model is invoked via ``job_runner.launch`` which resolves the command
    from ``ANCHOR_RUNNER_CMD`` (the test seam → ``tests/fake_claude.py`` / a
    tailored stub) so the gate NEVER calls live ``claude``. We pass the seed as
    the ``prompt`` (appended as a trailing arg the mock tolerates) so the gated/
    stdin contract is exercised without a real CLI.

    The job's captured stdout lines are the candidate summary: each non-JSON
    content line is taken as one candidate claim (stream-json ``result`` /
    envelope lines are skipped). Stdlib only.

    FIX 2 — failure detection: after the job finishes we inspect its record's
    status. A FAILED or timed-out runner job (non-zero exit, killed, interrupted)
    returns the ``RUN_FAILED`` sentinel so the caller refuses to cache a poisoned
    summary. A successful run that simply emitted nothing returns ``[]``.
    """
    prompt = _seed_prompt(seed)
    rec = _jr.launch("research", cwd=str(folder_path), prompt=prompt)
    jid = rec["job_id"]
    _jr.wait(jid, timeout=60)
    # FIX 2: a failed/timed-out/killed job is retryable — never cache its output.
    final = _jr.load_record(jid) or {}
    status = final.get("status")
    if status != _jr.STATUS_DONE:
        return RUN_FAILED
    claims = []
    for line in _jr.all_lines(jid):
        s = (line or "").strip()
        if not s:
            continue
        # Skip stream-json envelope lines (result / assistant frames).
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and obj.get("type"):
                    continue
            except (json.JSONDecodeError, ValueError):
                pass
        # Strip a leading bullet marker so claims normalize.
        claims.append(re.sub(r"^[-*+]\s+", "", s))
    return claims


def _generate_candidates(folder_path, seed: dict, runs: int):
    """Generate ``runs`` candidate claim-lists (step b — generate TWICE).

    Returns ``(candidates, failed)`` where ``candidates`` is the list of
    successful per-run claim-lists and ``failed`` is True iff ANY run returned the
    ``RUN_FAILED`` sentinel (FIX 2 — a failed run must not be cached as success).
    """
    candidates = []
    failed = False
    for _ in range(max(1, runs)):
        out = _run_model_once(folder_path, seed)
        if out is RUN_FAILED:
            failed = True
            continue
        candidates.append(out)
    return candidates, failed


# ── (c) Validation pass: deterministic grounding ─────────────────────────────

_TERM_RE = re.compile(r"[A-Za-z0-9]{3,}")


def _key_terms(claim: str) -> list:
    """The alphanumeric key terms (>=3 chars) of a claim, lowercased."""
    return [t.lower() for t in _TERM_RE.findall(claim or "")]


def is_grounded(claim: str, corpus_lower: str,
                min_ratio: float = GROUNDING_MIN_RATIO) -> bool:
    """Best-effort HINT FILTER: True iff a claim looks grounded (step c).

    This is a DETERMINISTIC, best-effort grounding HINT that removes obviously
    ungrounded claims (terms that simply never appear in the member docs). It is
    **NOT a semantic guarantee** — it cannot tell that a claim's *meaning*
    matches the corpus, only that its content words overlap. No LLM judge is
    involved by design (FIX 3 keeps it deterministic and cheap).

    A claim is treated as grounded when BOTH hold (FIX 3 — modest strengthen so
    the filter is less gameable):

    * at least ``min_ratio`` (default 0.7) of its unique key terms appear in the
      lowercased member-doc corpus, AND
    * at least ``GROUNDING_MIN_TERMS`` (default 2) of those key terms are
      actually found in the corpus.

    A claim with no key terms, or one resting on a single incidental shared word,
    is ungrounded — nothing meaningful anchors it.
    """
    uniq = set(_key_terms(claim))
    if not uniq:
        return False
    hits = sum(1 for t in uniq if t in corpus_lower)
    if hits < GROUNDING_MIN_TERMS:
        return False
    return (hits / len(uniq)) >= min_ratio


def _validate(candidates: list, seed: dict) -> list:
    """Fuse candidate claim-lists, drop ungrounded claims, dedupe (step c).

    Cross-run fusion: union the candidates (a claim that appears in ANY run is a
    candidate), then keep only the grounded ones, deduped by normalized text,
    order-stable.
    """
    corpus_lower = (seed.get("text") or "").lower()
    seen = set()
    kept = []
    for run in candidates:
        for claim in run:
            norm = re.sub(r"\s+", " ", (claim or "").strip()).lower()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            if is_grounded(claim, corpus_lower):
                kept.append(claim.strip())
    return kept


# ── (d) Cache layout + render ────────────────────────────────────────────────

def summary_dir(folder_path, project_id, lane, session_id) -> Path:
    """``<lane>/summaries/<session_id>/`` — the per-session cache dir."""
    safe_sid = _safe_segment(session_id)
    return (_eh.lane_dir(folder_path, project_id, lane)
            / SUMMARIES_DIRNAME / safe_sid)


def _safe_segment(seg: str) -> str:
    """Filesystem-safe form of a session_id (it contains ``::`` etc.)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(seg or "")) or "session"


def _summary_json_path(folder_path, project_id, lane, session_id) -> Path:
    return summary_dir(folder_path, project_id, lane, session_id) / SUMMARY_JSON


def _summary_md_path(folder_path, project_id, lane, session_id) -> Path:
    return summary_dir(folder_path, project_id, lane, session_id) / SUMMARY_MD


def load_cached(folder_path, project_id, lane, session_id):
    """Return the cached structured summary dict, or ``None``."""
    p = _summary_json_path(folder_path, project_id, lane, session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _member_links(seed: dict, project_id: str, lane: str) -> list:
    """Build working links to each member doc for the rendered summary (step 2).

    DISCOVERED members link to ``/artifact/<pid>?path=<rel>``; RUN members link
    to ``/report/<pid>/<lane>/<job_id>`` (the existing routes). Returns
    ``[{label, href}]``.
    """
    from urllib.parse import quote as _q
    out = []
    for m in seed.get("members", []):
        rel = (m.get("rel") or "").strip()
        jid = (m.get("job_id") or "").strip()
        label = m.get("title") or rel or jid or "member"
        if rel:
            href = f"/artifact/{_q(project_id, safe='')}?path={_q(rel, safe='')}"
        elif jid:
            href = (f"/report/{_q(project_id, safe='')}/"
                    f"{_q(lane, safe='')}/{_q(jid, safe='')}")
        else:
            continue
        out.append({"label": label, "href": href})
    return out


# ── Per-lane document roles (v4 Wave 3) ──────────────────────────────────────
#
# The v4 cockpit summary panel shows each session's member docs **tagged by
# ROLE** (not a flat link list). Roles are LANE-SPECIFIC and locked:
#
#   research → exec (executive summary)   · report (full report/PDF)
#              · agent (agent-readable JSON) · provenance (refs.bib / run.log)
#   planning → master (MASTER-PLAN.md) · impl (IMPLEMENTATION-PLAN.md)
#              · northstar (North-Star* / NORTH-STAR*)
#   build    → northstar · deliverable (the project's pinned/linked deliverable)
#              · execlog (EXECUTION-LOG.md) · plan (the plan it executes — handoff)
#
# Each role's ``href`` reuses the EXISTING routes (``/report/<pid>/<lane>/<job>``
# for run docs, ``/artifact/<pid>?path=<rel>`` for discovered/on-disk files).
# Roles whose document is ABSENT are OMITTED — never fabricated. Stdlib only.


def _artifact_href(project_id: str, rel: str) -> str:
    """``/artifact/<pid>?path=<rel>`` — the existing discovered-file route."""
    from urllib.parse import quote as _q
    return f"/artifact/{_q(str(project_id), safe='')}?path={_q(rel, safe='')}"


def _report_href(project_id: str, lane: str, job_id: str) -> str:
    """``/report/<pid>/<lane>/<job_id>`` — the existing run-report route."""
    from urllib.parse import quote as _q
    return (f"/report/{_q(str(project_id), safe='')}/"
            f"{_q(str(lane), safe='')}/{_q(str(job_id), safe='')}")


def _member_href(project_id: str, lane: str, member: dict):
    """The working route for one session member, or ``None``.

    DISCOVERED / on-disk members (carry ``artifact_path``) → ``/artifact`` route;
    RUN members (carry a ``job_id``) → ``/report`` route. Mirrors
    :func:`_member_links` so role hrefs use exactly the same existing routes.
    """
    rel = (member.get("artifact_path") or "").strip()
    if rel:
        return _artifact_href(project_id, rel.replace("\\", "/"))
    jid = (member.get("job_id") or "").strip()
    if jid:
        return _report_href(project_id, lane, jid)
    return None


def _member_basename(member: dict) -> str:
    """Lowercased basename of a member's artifact path (POSIX), or ''."""
    from pathlib import PurePosixPath
    rel = (member.get("artifact_path") or "").strip().replace("\\", "/")
    if not rel:
        return ""
    return PurePosixPath(rel).name.lower()


def _member_label(member: dict) -> str:
    """A human label for a member doc (title → basename → job_id)."""
    title = (member.get("title") or "").strip()
    if title:
        return title
    base = _member_basename(member)
    if base:
        return base
    return (member.get("job_id") or "").strip() or "member"


def _research_roles(project_id, store_lane, members) -> dict:
    """Resolve research roles: exec / report / agent / provenance.

    First match per role wins (members are newest-first). report.* / *.pdf →
    report; an executive/summary markdown → exec; *.json → agent; refs.bib or
    run.log → provenance. Absent roles are simply not added.
    """
    roles = {}
    for m in members:
        base = _member_basename(m)
        href = _member_href(project_id, store_lane, m)
        if href is None:
            continue
        label = _member_label(m)
        suffix = base.rsplit(".", 1)[-1] if "." in base else ""
        # report — the full report. Either a discovered file named report.* /
        # *.pdf, OR a RUN member (no artifact_path) whose report.md/.pdf the
        # ``/report`` route serves directly (the run-session common case).
        rel = (m.get("artifact_path") or "").strip()
        jid = (m.get("job_id") or "").strip()
        if "report" not in roles and (
                suffix == "pdf" or base.startswith("report.") or base == "report"
                or (not rel and jid)):
            roles["report"] = {"label": label, "href": href}
            continue
        # exec — an executive summary markdown (exec/summary in the name)
        if "exec" not in roles and suffix in ("md", "markdown", "txt") and (
                "exec" in base or "summary" in base):
            roles["exec"] = {"label": label, "href": href}
            continue
        # agent — an agent-readable JSON
        if "agent" not in roles and suffix == "json":
            roles["agent"] = {"label": label, "href": href}
            continue
        # provenance — refs.bib / run.log (citations + the raw run log)
        if "provenance" not in roles and (base in ("refs.bib", "run.log")
                                          or suffix in ("bib", "log")):
            roles["provenance"] = {"label": label, "href": href}
            continue
    return roles


def _planning_roles(project_id, store_lane, members) -> dict:
    """Resolve planning roles: master / impl / northstar (by filename)."""
    roles = {}
    for m in members:
        base = _member_basename(m)
        href = _member_href(project_id, store_lane, m)
        if href is None:
            continue
        label = _member_label(m)
        if "master" not in roles and base.startswith("master-plan"):
            roles["master"] = {"label": label, "href": href}
            continue
        if "impl" not in roles and base.startswith("implementation-plan"):
            roles["impl"] = {"label": label, "href": href}
            continue
        if "northstar" not in roles and base.startswith("north-star"):
            roles["northstar"] = {"label": label, "href": href}
            continue
    return roles


def _build_roles(folder_path, project_id, store_lane, members) -> dict:
    """Resolve build roles: northstar / execlog / deliverable / plan.

    northstar + execlog come from the session's own member files (by filename).
    deliverable is the project's pinned/linked deliverable (``deliverables.py``);
    plan is the most-recent plan set this build would execute on (``handoff.py``)
    — both link via the existing routes. Absent roles are omitted.
    """
    roles = {}
    for m in members:
        base = _member_basename(m)
        href = _member_href(project_id, store_lane, m)
        if href is None:
            continue
        label = _member_label(m)
        if "northstar" not in roles and base.startswith("north-star"):
            roles["northstar"] = {"label": label, "href": href}
            continue
        if "execlog" not in roles and base.startswith("execution-log"):
            roles["execlog"] = {"label": label, "href": href}
            continue

    # deliverable — the project's pinned/linked deliverable (newest pinned wins).
    try:
        import deliverables as _deliv
        pinned = _deliv.list_pinned_deliverables(folder_path, project_id)
        if pinned:
            rec = pinned[0]
            rel = (rec.get("artifact_path") or "").strip().replace("\\", "/")
            if rel:
                roles["deliverable"] = {
                    "label": rec.get("title") or rel,
                    "href": _artifact_href(project_id, rel),
                }
    except Exception:
        pass

    # plan — the most-recent plan set a build session executes on (handoff).
    try:
        import handoff as _handoff
        plan_set = _handoff.discover_recent_plan_set(folder_path, project_id)
        if plan_set:
            rel = (plan_set.get("master_plan_rel")
                   or plan_set.get("impl_plan_rel") or "").strip()
            rel = rel.replace("\\", "/")
            if rel:
                roles["plan"] = {
                    "label": plan_set.get("title") or rel,
                    "href": _artifact_href(project_id, rel),
                }
    except Exception:
        pass
    return roles


def _find_session(folder_path, project_id, store_lane, session_id):
    """Return the session record for ``session_id`` in a lane, or ``None``."""
    import sessions as _sessions
    for s in _sessions.list_sessions(folder_path, project_id, store_lane):
        if s.get("session_id") == session_id:
            return s
    return None


def session_doc_roles(project_id, lane, session_id, folder_path=None) -> dict:
    """Per-lane ROLE→doc map for one session (v4 Wave 3, MASTER-PLAN cockpit).

    Maps the session's member docs (by filename) to the LANE'S locked role set
    and returns ``{role: {"label": str, "href": str}}`` where each ``href`` uses
    the EXISTING routes (``/report`` for run docs, ``/artifact`` for discovered/
    on-disk files; the deliverable/plan roles also resolve via those routes).

    Role sets:
      - research → exec · report · agent · provenance
      - planning → master · impl · northstar
      - build    → northstar · deliverable · execlog · plan

    Roles whose document is ABSENT are OMITTED — never fabricated. ``folder_path``
    is resolved from the registry when omitted (mirrors ``project_rollup``).
    Stdlib only; never raises (returns ``{}`` on any resolution failure).
    """
    if folder_path is None:
        import rnd_registry as _rnd2
        proj = _rnd2.get_project(project_id)
        folder_path = (proj or {}).get("folder_path", "")
    store_lane = _eh._resolve_subdir(lane)
    try:
        session = _find_session(folder_path, project_id, store_lane, session_id)
    except Exception:
        session = None
    if not session:
        return {}
    members = session.get("member_files", []) or []
    kind = _lane_kind(store_lane)
    if kind == "research":
        return _research_roles(project_id, store_lane, members)
    if kind == "planning":
        return _planning_roles(project_id, store_lane, members)
    if kind == "build":
        return _build_roles(folder_path, project_id, store_lane, members)
    return {}


def render_markdown(structured: dict) -> str:
    """Render the structured summary to cache-ready markdown (step d).

    Shape: a title, a lane-labelled claims list (goal · key decisions ·
    findings · errors), and a Files section with links to each member doc.
    """
    lane = structured.get("lane", "")
    title = structured.get("title") or f"{lane} session summary"
    lines = [f"# {title}", ""]
    if lane:
        lines.append(f"*Lane: {lane} · validated, cached summary*")
        lines.append("")
    # v3 Wave 6 — locked content shape: when-run · what-was-asked · North-Star ·
    # effort (tokens + wall-clock; imported → "no run metrics").
    when_run = (structured.get("when_run") or "").strip()
    what_asked = (structured.get("what_was_asked") or "").strip()
    north_star = (structured.get("north_star") or "").strip()
    if when_run:
        lines.append(f"**When run:** {when_run}")
        lines.append("")
    if what_asked:
        lines.append(f"**What was asked:** {what_asked}")
        lines.append("")
    if north_star:
        lines.append(f"**North Star:** {north_star}")
        lines.append("")
    effort = structured.get("effort", None)
    if effort is None and "effort" in structured:
        lines.append("**Effort:** imported — no run metrics")
        lines.append("")
    elif isinstance(effort, dict):
        secs = (effort.get("wall_clock_ms", 0) or 0) / 1000.0
        lines.append(
            f"**Effort:** {effort.get('tokens', 0)} tokens · "
            f"{secs:.1f}s wall-clock · {effort.get('runs', 0)} run(s)")
        lines.append("")
    claims = structured.get("claims", []) or []
    if claims:
        heading = {
            "planning": "## Goal & key decisions",
            "research": "## Question & findings",
            "build": "## What was built & errors overcome",
        }.get(lane, "## Summary")
        lines.append(heading)
        lines.append("")
        for c in claims:
            lines.append(f"- {c}")
        lines.append("")
    elif structured.get("no_grounded_claims"):
        # FIX 2 — honest, explicit note instead of a silent blank summary.
        lines.append("## Summary")
        lines.append("")
        lines.append("_No grounded claims could be extracted from the member "
                     "documents for this session. You may **Regenerate** to try "
                     "again._")
        lines.append("")
    links = structured.get("member_links", []) or []
    if links:
        lines.append("## Files")
        lines.append("")
        for lk in links:
            lines.append(f"- [{lk['label']}]({lk['href']})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_cache(folder_path, project_id, lane, session_id,
                 structured: dict) -> dict:
    """Write summary.json + summary.md under the session cache dir (under lock)."""
    with _paths.WRITE_LOCK:
        d = summary_dir(folder_path, project_id, lane, session_id)
        d.mkdir(parents=True, exist_ok=True)
        md = render_markdown(structured)
        structured["markdown"] = md
        jp = d / SUMMARY_JSON
        tmp = jp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(structured, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(jp)
        (d / SUMMARY_MD).write_text(md, encoding="utf-8")
    return structured


# ── Public entry: summarize_session (run-once + regenerate) ──────────────────

def summarize_session(folder_path, project_id, lane, session,
                      force: bool = False) -> dict:
    """Summarize ONE session → validated, cached structured summary (MASTER §B).

    Run-once semantics (step e): unless ``force`` is set, a cached summary for
    this session is returned WITHOUT running the model again. ``force=True``
    (the Regenerate path) re-runs the model and overwrites the cache.

    Pipeline: extraction-seed (a) → generate twice through the runner seam (b) →
    deterministic grounding validation (c) → cache summary.json + summary.md (d).

    Returns the structured summary dict::

        {"session_id", "lane", "title", "claims": [...], "member_links": [...],
         "markdown": "<rendered>", "generated_at": <epoch>, "runs": N}
    """
    session_id = session.get("session_id") or ""
    store_lane = _eh._resolve_subdir(lane)
    if not force:
        cached = load_cached(folder_path, project_id, store_lane, session_id)
        if cached is not None:
            return cached

    # FIX 1 — run-once under concurrency: serialize cache-check → generate →
    # write PER session. Two concurrent calls for the SAME uncached session must
    # together run the model exactly GENERATE_RUNS times, not 2×.
    lock = _session_lock(folder_path, project_id, store_lane, session_id)
    with lock:
        # Double-checked locking: a racing caller may have just written the
        # cache while we waited for the lock — serve it instead of regenerating.
        if not force:
            cached = load_cached(folder_path, project_id, store_lane,
                                 session_id)
            if cached is not None:
                return cached

        seed = extraction_seed(folder_path, project_id, store_lane, session)
        effort = _aggregate_effort(session)
        candidates, failed = _generate_candidates(folder_path, seed,
                                                  GENERATE_RUNS)
        # FIX 2 — no cache poisoning on failure: if a runner job FAILED/timed
        # out, OR no run produced ANY usable output, surface a retryable error
        # state WITHOUT writing the cache so a later call/Regenerate can retry.
        if failed or not candidates:
            return {
                "session_id": session_id,
                "lane": seed["lane"],
                "title": seed.get("title", ""),
                "claims": [],
                "member_links": _member_links(seed, project_id, store_lane),
                "when_run": seed.get("when_run", ""),
                "what_was_asked": seed.get("what_was_asked", ""),
                "north_star": seed.get("north_star", ""),
                "effort": effort,
                "error": "generation_failed",
                "generated_at": time.time(),
                "runs": len(candidates),
            }

        claims = _validate(candidates, seed)
        structured = {
            "session_id": session_id,
            "lane": seed["lane"],
            "title": seed.get("title", ""),
            "claims": claims,
            "member_links": _member_links(seed, project_id, store_lane),
            "when_run": seed.get("when_run", ""),
            "what_was_asked": seed.get("what_was_asked", ""),
            "north_star": seed.get("north_star", ""),
            "effort": effort,
            "generated_at": time.time(),
            "runs": len(candidates),
        }
        # FIX 2 — all-ungrounded behavior: the model ran successfully but every
        # claim was filtered out as ungrounded. We CACHE this (the run-once
        # contract holds — a successful run shouldn't re-burn the model) but flag
        # it so the page renders an explicit honest note instead of a blank.
        if not claims:
            structured["no_grounded_claims"] = True
        return _write_cache(folder_path, project_id, store_lane, session_id,
                            structured)


def render_summary_page(folder_path, project_id, lane, session_id,
                        session=None) -> dict:
    """Resolve + render a session's cached summary as an HTML page (route core).

    Reuses ``report_viewer.markdown_to_html`` / ``reader_html`` so markdown is
    rendered exactly like the report viewer (vendored KaTeX, dark theme). If no
    cache exists yet and a ``session`` record is supplied, the summary is
    generated first (run-once). Returns
    ``{"mode", "content_type", "body", "found"}`` for the GUI route to write.
    """
    store_lane = _eh._resolve_subdir(lane)
    cached = load_cached(folder_path, project_id, store_lane, session_id)
    if cached is None and session is not None:
        cached = summarize_session(folder_path, project_id, store_lane, session)
    # FIX 2 — failed generation surfaces a non-cached, honest, retryable error
    # page (the model failed / nothing usable came back). It is NOT cached, so a
    # later view / Regenerate genuinely retries instead of serving a poisoned
    # blank.
    if isinstance(cached, dict) and cached.get("error"):
        notice = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Summary unavailable</title></head>"
            "<body style='background:#0f1117;color:#e6e8ee;"
            "font-family:sans-serif;padding:40px'>"
            "<h2 style='color:#fc8c6c'>Summary could not be generated</h2>"
            "<p>The model run failed or returned no grounded content. "
            "Nothing was cached &mdash; use <b>Regenerate</b> to retry.</p>"
            "</body></html>"
        )
        return {"mode": "error",
                "content_type": "text/html; charset=utf-8",
                "body": notice, "found": False}
    if cached is None:
        notice = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>No summary</title></head>"
            "<body style='background:#0f1117;color:#e6e8ee;"
            "font-family:sans-serif;padding:40px'>"
            "<h2 style='color:#6c9cfc'>No summary yet</h2>"
            "<p>This session has no cached summary.</p></body></html>"
        )
        return {"mode": "missing",
                "content_type": "text/html; charset=utf-8",
                "body": notice, "found": False}
    md = cached.get("markdown") or render_markdown(cached)
    title = cached.get("title") or f"{store_lane} session summary"
    page = _rv.reader_html(md, title)
    return {"mode": "reader",
            "content_type": "text/html; charset=utf-8",
            "body": page, "found": True}


# ─────────────────────────────────────────────────────────────────────────────
# PROJECT summary (v3 Wave 5) — an accurate, cached, validated description of
# WHAT A PROJECT IS, mirroring the session-summary pipeline above (do NOT fork).
#
# MASTER-PLAN §A/§B: the thin project row's summary text must be an accurate
# cached project summary that REPLACES the weak first-paragraph blurb. It is
# generated ONCE (proactively on rescan) from the project's CLAUDE.md/README/
# Anchor.md (what the project IS) + the most-recent plan docs + declared/pinned
# deliverables, validated by the SAME deterministic grounding filter, and cached
# as small git-trackable JSON under the project's ``.anchor`` store. The render
# path only READS the cache — it NEVER runs the model synchronously.
# ─────────────────────────────────────────────────────────────────────────────

#: File names probed (in order) for the "what the project IS" seed corpus.
PROJECT_SEED_FILES = ("CLAUDE.md", "README.md", "README", "Anchor.md")
#: Glob-ish relative locations of the most-recent plan docs to seed from.
PROJECT_PLAN_DOC_NAMES = ("MASTER-PLAN.md", "IMPLEMENTATION-PLAN.md")
PROJECT_PLAN_DIR = "planning"
#: How many plan docs to fold into the seed (bounded).
MAX_PROJECT_PLAN_DOCS = 4
#: Cache file names for the per-project summary.
PROJECT_SUMMARY_JSON = "project-summary.json"
PROJECT_SUMMARY_MD = "project-summary.md"

# Per-project generation lock (mirror of the per-session lock — run-once under
# the ThreadingHTTPServer when two rescans race the same project).
_PROJECT_LOCKS_GUARD = threading.Lock()
_PROJECT_LOCKS = {}


def _project_lock(folder_path, project_id):
    key = (str(folder_path), str(project_id))
    with _PROJECT_LOCKS_GUARD:
        lk = _PROJECT_LOCKS.get(key)
        if lk is None:
            lk = threading.Lock()
            _PROJECT_LOCKS[key] = lk
        return lk


def _project_store_dir(folder_path, project_id) -> Path:
    """``<folder>/.anchor/projects/<id>/`` — the per-project store (not created)."""
    return Path(folder_path) / ".anchor" / "projects" / str(project_id)


def _project_summary_json_path(folder_path, project_id) -> Path:
    return _project_store_dir(folder_path, project_id) / PROJECT_SUMMARY_JSON


def _project_summary_md_path(folder_path, project_id) -> Path:
    return _project_store_dir(folder_path, project_id) / PROJECT_SUMMARY_MD


def _recent_plan_docs(folder_path) -> list:
    """Best-effort: find the most-recent plan docs under ``planning/``.

    Returns up to ``MAX_PROJECT_PLAN_DOCS`` ``Path``s named like a MASTER-PLAN /
    IMPLEMENTATION-PLAN, newest-first by mtime (so ``rnd-v3`` wins over ``rnd-v1``).
    Stdlib only; never raises.
    """
    out = []
    try:
        base = Path(folder_path) / PROJECT_PLAN_DIR
        if not base.is_dir():
            return out
        cand = []
        for p in base.rglob("*.md"):
            try:
                if p.name in PROJECT_PLAN_DOC_NAMES and p.is_file():
                    cand.append((p.stat().st_mtime, p))
            except OSError:
                continue
        cand.sort(key=lambda t: t[0], reverse=True)
        out = [p for _, p in cand[:MAX_PROJECT_PLAN_DOCS]]
    except OSError:
        pass
    return out


def project_extraction_seed(folder_path, project_id) -> dict:
    """Deterministically build the PROJECT seed corpus (mirror of extraction_seed).

    Folds three bounded sources into one grounding corpus + anchor list:
      1. the project's CLAUDE.md/README/Anchor.md (what the project IS),
      2. the most-recent plan docs under ``planning/`` (goal / north-star), and
      3. declared/pinned deliverables (what it ships).

    Returns ``{"kind": "project", "title", "sources": [...], "anchors": [...],
    "deliverables": [...], "text": "<combined corpus>"}``. Stdlib only; never
    raises.
    """
    folder = Path(folder_path)
    title = ""
    sources = []
    anchors = []
    corpus_parts = []

    # 1. "What the project IS" — first existing identity doc (bounded read).
    for name in PROJECT_SEED_FILES:
        path = folder / name
        text = _read_bounded(path)
        if text:
            sources.append(name)
            corpus_parts.append(text)
            if not title:
                title = _first_heading(text)
            for heading, body in _lift_sections(text, _SECTION_SIGNALS["planning"]):
                anchors.append({"heading": heading, "body": body, "from": name})
            break

    # 2. Most-recent plan docs (goal / north-star / key decisions).
    for path in _recent_plan_docs(folder):
        text = _read_bounded(path)
        if not text:
            continue
        rel = path.name
        try:
            rel = str(path.relative_to(folder))
        except (ValueError, OSError):
            pass
        sources.append(rel)
        corpus_parts.append(text)
        for heading, body in _lift_sections(text, _SECTION_SIGNALS["planning"]):
            anchors.append({"heading": heading, "body": body, "from": rel})

    # 3. Declared / pinned deliverables (what the project ships).
    deliverables = []
    try:
        import deliverables as _deliv
        for rec in _deliv.list_pinned_deliverables(folder, project_id):
            label = (rec.get("name") or rec.get("artifact_path")
                     or rec.get("path") or "").strip()
            if label:
                deliverables.append(label)
                corpus_parts.append(label)
                desc = (rec.get("description") or rec.get("desc") or "").strip()
                if desc:
                    corpus_parts.append(desc)
    except Exception:
        pass

    if not title and sources:
        title = sources[0]
    return {
        "kind": "project",
        "title": title,
        "sources": sources,
        "anchors": anchors,
        "deliverables": deliverables,
        "text": "\n".join(corpus_parts),
    }


def _project_seed_prompt(seed: dict) -> str:
    """Render the project seed as the bounded model prompt (mirror of _seed_prompt)."""
    lines = [
        "Summarize what this project IS in a few grounded bullet claims "
        "(its purpose, what it does, and what it ships).",
        f"Title: {seed.get('title', '')}",
        "Anchors from the project documents:",
    ]
    for a in seed.get("anchors", []):
        lines.append(f"- {a['heading']}: {a['body']}")
    delivs = seed.get("deliverables", [])
    if delivs:
        lines.append("Declared deliverables:")
        for d in delivs:
            lines.append(f"- {d}")
    return "\n".join(lines)


def _run_project_model_once(folder_path, seed: dict, runner_env: dict = None):
    """Run ONE bounded project-summary model call through the runner seam.

    Identical contract to ``_run_model_once`` (RUN_FAILED sentinel on a
    failed/timed-out job; ``[]`` on a clean run that emitted nothing), but seeded
    with the PROJECT prompt. All model calls go through ``job_runner`` /
    ``ANCHOR_RUNNER_CMD`` — NEVER live ``claude``.

    ``runner_env`` (optional): when the generation is kicked off from a BACKGROUND
    thread (proactive on-rescan generation), the caller snapshots the runner-seam
    env (``ANCHOR_RUNNER_CMD`` + any test ``STUB_*`` vars) at trigger time and
    forwards it here so the spawned job uses the runner/counter that were
    configured THEN — not whatever the process env happens to be when the late
    background thread finally runs. This keeps a late daemon thread from a prior
    test from contaminating a later test's runner-call counter (test isolation).
    """
    prompt = _project_seed_prompt(seed)
    rec = _jr.launch("research", cwd=str(folder_path), prompt=prompt,
                     env=(runner_env or None))
    jid = rec["job_id"]
    _jr.wait(jid, timeout=60)
    final = _jr.load_record(jid) or {}
    if final.get("status") != _jr.STATUS_DONE:
        return RUN_FAILED
    claims = []
    for line in _jr.all_lines(jid):
        s = (line or "").strip()
        if not s:
            continue
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
                if isinstance(obj, dict) and obj.get("type"):
                    continue
            except (json.JSONDecodeError, ValueError):
                pass
        claims.append(re.sub(r"^[-*+]\s+", "", s))
    return claims


def _generate_project_candidates(folder_path, seed: dict, runs: int,
                                 runner_env: dict = None):
    """Generate ``runs`` project-summary candidate claim-lists (mirror)."""
    candidates = []
    failed = False
    for _ in range(max(1, runs)):
        out = _run_project_model_once(folder_path, seed, runner_env=runner_env)
        if out is RUN_FAILED:
            failed = True
            continue
        candidates.append(out)
    return candidates, failed


def render_project_markdown(structured: dict) -> str:
    """Render a structured PROJECT summary to cache-ready markdown."""
    title = structured.get("title") or "Project summary"
    lines = [f"# {title}", "", "*Project summary · validated, cached*", ""]
    claims = structured.get("claims", []) or []
    if claims:
        lines.append("## What this project is")
        lines.append("")
        for c in claims:
            lines.append(f"- {c}")
        lines.append("")
    elif structured.get("no_grounded_claims"):
        lines.append("## What this project is")
        lines.append("")
        lines.append("_No grounded description could be extracted from the "
                     "project documents. You may rescan/regenerate to try again._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _summary_text(structured: dict) -> str:
    """Compact one-line summary text for the thin project row (claims joined)."""
    claims = structured.get("claims", []) or []
    return " ".join(c.strip() for c in claims if c and c.strip()).strip()


def _write_project_cache(folder_path, project_id, structured: dict) -> dict:
    """Write project-summary.json + .md under the project store (under lock)."""
    with _paths.WRITE_LOCK:
        d = _project_store_dir(folder_path, project_id)
        d.mkdir(parents=True, exist_ok=True)
        md = render_project_markdown(structured)
        structured["markdown"] = md
        structured["summary_text"] = _summary_text(structured)
        jp = d / PROJECT_SUMMARY_JSON
        tmp = jp.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(structured, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(jp)
        (d / PROJECT_SUMMARY_MD).write_text(md, encoding="utf-8")
    return structured


def load_cached_project(folder_path, project_id):
    """Return the cached structured PROJECT summary dict, or ``None``.

    ``None`` means "not generated yet" — the row falls back to the blurb. This
    function NEVER runs the model, so it is safe on the dashboard render path.
    """
    p = _project_summary_json_path(folder_path, project_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def summarize_project(folder_path, project_id, force: bool = False,
                      runner_env: dict = None) -> dict:
    """Summarize a PROJECT → validated, cached structured summary (Wave 5).

    Run-once semantics (mirror of ``summarize_session``): unless ``force`` is set,
    a cached project summary is returned WITHOUT running the model again.
    ``force=True`` re-runs the model and overwrites the cache.

    Pipeline: project extraction-seed → generate twice through the runner seam →
    deterministic grounding validation → cache project-summary.json + .md.

    A failed runner job (or no usable output) returns a retryable error state and
    does NOT write the cache (no poisoning). An all-ungrounded successful run is
    cached but flagged ``no_grounded_claims`` (run-once still holds).

    This MAY run the model, so it must be called OFF the render path (e.g. from
    the rescan handler / a background thread), never during a dashboard render.
    """
    if not force:
        cached = load_cached_project(folder_path, project_id)
        if cached is not None:
            return cached

    lock = _project_lock(folder_path, project_id)
    with lock:
        if not force:
            cached = load_cached_project(folder_path, project_id)
            if cached is not None:
                return cached

        seed = project_extraction_seed(folder_path, project_id)
        candidates, failed = _generate_project_candidates(
            folder_path, seed, GENERATE_RUNS, runner_env=runner_env)
        if failed or not candidates:
            return {
                "project_id": str(project_id),
                "kind": "project",
                "title": seed.get("title", ""),
                "claims": [],
                "summary_text": "",
                "sources": seed.get("sources", []),
                "error": "generation_failed",
                "generated_at": time.time(),
                "runs": len(candidates),
            }

        claims = _validate(candidates, seed)
        structured = {
            "project_id": str(project_id),
            "kind": "project",
            "title": seed.get("title", ""),
            "claims": claims,
            "sources": seed.get("sources", []),
            "generated_at": time.time(),
            "runs": len(candidates),
        }
        if not claims:
            structured["no_grounded_claims"] = True
        return _write_project_cache(folder_path, project_id, structured)
