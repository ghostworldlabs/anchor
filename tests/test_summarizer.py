"""Wave 6 — validated, cached session summaries.

Acceptance (frozen plan, "Wave 6 — Validated, cached summaries"):
  - clicking the brownfield-discovery planning session opens a CACHED markdown
    summary (goal · key decisions · files-with-links);
  - reopening serves the IDENTICAL cached summary WITHOUT re-running the model;
  - Regenerate re-runs and re-caches.

G/W/T: Given a session with member docs and a STUBBED runner, When the summary is
requested twice, Then the model runs ONCE (first request) and the second serves
cache; ungrounded claims emitted by the stub are ABSENT from summary.json.

Hermetic: ALL model calls go through ANCHOR_RUNNER_CMD → tests/stub_summarizer.py
(a STUB; never live claude). The runner subprocess is reaped after each test.
"""
import importlib
import json
from pathlib import Path

import pytest

STUB = (Path(__file__).resolve().parent / "stub_summarizer.py").as_posix()


@pytest.fixture
def mods(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {STUB}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import report_viewer
    importlib.reload(report_viewer)
    import summarizer
    importlib.reload(summarizer)
    yield job_runner, effort_history, rnd_registry, sessions, summarizer
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


def _planning_session_with_docs(rnd, eh, sessions, folder):
    """Build a discovered planning session (brownfield-discovery style) with two
    member docs on disk, then return (project_id, session)."""
    folder.mkdir(parents=True, exist_ok=True)
    # Two real planning docs under planning/brownfield-discovery/ → one session.
    bd = folder / "planning" / "brownfield-discovery"
    bd.mkdir(parents=True, exist_ok=True)
    (bd / "MASTER-PLAN.md").write_text(
        "# Brownfield Master Plan\n\n"
        "## North Star\n"
        "Make the surface a truthful memory of trio work.\n\n"
        "## Key decisions\n"
        "Group efforts into sessions and cache validated summaries.\n",
        encoding="utf-8")
    (bd / "IMPLEMENTATION-PLAN.md").write_text(
        "# Implementation Plan\n\n"
        "## Goal\n"
        "Render most-recent session with an expander.\n",
        encoding="utf-8")

    proj = rnd.add_project("Anchor", str(folder))
    pid = proj["id"]

    # Adopt the on-disk docs as DISCOVERED planning efforts.
    import brownfield_scan
    scan = brownfield_scan.scan(str(folder))
    eh.adopt_discovered(folder, pid, scan)

    sess_list = sessions.list_sessions(folder, pid, "planning")
    assert sess_list, "expected a discovered planning session"
    # The brownfield-discovery session is the one whose members live under that dir.
    session = None
    for s in sess_list:
        rels = [m.get("artifact_path", "") for m in s.get("member_files", [])]
        if any("brownfield-discovery" in r for r in rels):
            session = s
            break
    assert session is not None
    assert len(session["member_files"]) == 2
    return pid, session


# ── Extraction seed (step a) ─────────────────────────────────────────────────

def test_extraction_seed_pulls_anchors_from_member_docs(mods, tmp_path):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)

    seed = summ.extraction_seed(folder, pid, "planning", session)
    assert seed["lane"] == "planning"
    assert len(seed["members"]) == 2
    # The combined grounding corpus carries the member-doc text.
    assert "north star" in seed["text"].lower()
    assert "expander" in seed["text"].lower()
    # Section anchors were lifted (North Star / Goal / Key decisions headings).
    headings = " ".join(a["heading"].lower() for a in seed["anchors"])
    assert "north star" in headings or "goal" in headings or "decision" in headings


# ── Run-once cache + grounded-claim filtering (G/W/T) ────────────────────────

def test_run_once_cache_and_grounding(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    # One grounded claim (terms appear in the docs) + one ungrounded claim.
    grounded = "North Star: cache validated summaries for each session"
    ungrounded = "Quux frobnicate zzyzx wibble bogus unrelated claim"
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", grounded + "\n" + ungrounded)

    # FIRST request → model runs (GENERATE_RUNS calls), writes cache.
    s1 = summ.summarize_session(folder, pid, "planning", session)
    first_calls = counter.read_text(encoding="utf-8") if counter.exists() else ""
    assert len(first_calls) == summ.GENERATE_RUNS, (
        "model should run GENERATE_RUNS times on the first request")

    # Grounded claim kept; ungrounded claim dropped from summary.json.
    joined = " ".join(s1["claims"]).lower()
    assert "validated summaries" in joined
    assert "frobnicate" not in joined
    assert "zzyzx" not in joined

    # The cache files exist and are git-trackable (.json + .md).
    jp = summ._summary_json_path(folder, pid, "planning", session["session_id"])
    mp = summ._summary_md_path(folder, pid, "planning", session["session_id"])
    assert jp.exists() and mp.exists()
    on_disk = json.loads(jp.read_text(encoding="utf-8"))
    assert "frobnicate" not in json.dumps(on_disk).lower()
    # Rendered markdown carries goal/decisions + files-with-links.
    md = mp.read_text(encoding="utf-8")
    assert "## Files" in md
    assert "/artifact/" in md  # discovered member links

    # SECOND request → served from cache, model NOT run again (run-once).
    s2 = summ.summarize_session(folder, pid, "planning", session)
    second_calls = counter.read_text(encoding="utf-8") if counter.exists() else ""
    assert len(second_calls) == len(first_calls), (
        "second summarize must serve cache without re-running the model")
    assert s2["claims"] == s1["claims"]
    assert s2.get("generated_at") == s1.get("generated_at")


# ── Regenerate re-runs + re-caches ───────────────────────────────────────────

def test_regenerate_reruns_and_recaches(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    monkeypatch.setenv(
        "STUB_SUMMARIZER_CLAIMS",
        "North Star: truthful memory of trio work")

    s1 = summ.summarize_session(folder, pid, "planning", session)
    n1 = len(counter.read_text(encoding="utf-8"))
    assert n1 == summ.GENERATE_RUNS

    # Cache hit: no new calls.
    summ.summarize_session(folder, pid, "planning", session)
    assert len(counter.read_text(encoding="utf-8")) == n1

    # Regenerate (force) → re-runs the model and overwrites the cache.
    monkeypatch.setenv(
        "STUB_SUMMARIZER_CLAIMS",
        "Goal: render most-recent session with an expander")
    s2 = summ.summarize_session(folder, pid, "planning", session, force=True)
    n2 = len(counter.read_text(encoding="utf-8"))
    assert n2 == n1 + summ.GENERATE_RUNS, "regenerate must re-run the model"

    joined1 = " ".join(s1["claims"]).lower()
    joined2 = " ".join(s2["claims"]).lower()
    assert "truthful memory" in joined1
    assert "expander" in joined2
    # The on-disk cache now reflects the regenerated content.
    cached = summ.load_cached(folder, pid, "planning", session["session_id"])
    assert "expander" in json.dumps(cached).lower()


# ── render_summary_page reuses report_viewer (no reinvented markdown) ─────────

def test_summary_page_renders_via_report_viewer(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "North Star: cache validated summaries")

    out = summ.render_summary_page(folder, pid, "planning",
                                   session["session_id"], session=session)
    assert out["found"] is True
    assert out["content_type"].startswith("text/html")
    # report_viewer.reader_html signature: links the vendored KaTeX assets.
    assert "/vendor/katex" in out["body"]
    assert "anchor-reader" in out["body"]


# ── FIX 1 — run-once under CONCURRENCY (per-session lock) ─────────────────────

def test_concurrent_summarize_runs_model_once(mods, tmp_path, monkeypatch):
    """Two threads summarize the SAME uncached session at once. The per-session
    lock + double-checked cache re-read must make the model run exactly
    GENERATE_RUNS times total (not 2x), and both callers get the SAME summary."""
    import threading
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "North Star: cache validated summaries for each session")

    results = {}
    barrier = threading.Barrier(2)

    def worker(name):
        barrier.wait()  # maximize the race: both enter summarize together
        results[name] = summ.summarize_session(folder, pid, "planning", session)

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start(); t2.start()
    t1.join(timeout=120); t2.join(timeout=120)
    assert not t1.is_alive() and not t2.is_alive(), "summarize threads hung"

    calls = counter.read_text(encoding="utf-8") if counter.exists() else ""
    assert len(calls) == summ.GENERATE_RUNS, (
        f"model must run GENERATE_RUNS={summ.GENERATE_RUNS} times total under "
        f"concurrency, not 2x; got {len(calls)} calls")
    # Both callers got the identical (cached) summary.
    assert results["a"]["claims"] == results["b"]["claims"]
    assert results["a"].get("generated_at") == results["b"].get("generated_at")
    assert "validated summaries" in " ".join(results["a"]["claims"]).lower()


# ── FIX 2 — a FAILED model run must NOT poison the cache (retryable) ──────────

def test_failed_run_does_not_poison_cache(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    # Make the runner job FAIL (exit non-zero, no usable output).
    monkeypatch.setenv("STUB_SUMMARIZER_FAIL", "1")
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", "ignored on failure")

    out = summ.summarize_session(folder, pid, "planning", session)
    # An honest, retryable error state — NOT a successful summary.
    assert out.get("error") == "generation_failed"
    assert out["claims"] == []
    # No cache file was written → a later call genuinely retries.
    jp = summ._summary_json_path(folder, pid, "planning", session["session_id"])
    assert not jp.exists(), "failed generation must NOT write a poisoned cache"
    assert summ.load_cached(folder, pid, "planning",
                            session["session_id"]) is None

    # The /summary page renders the honest 'could not be generated' message.
    page = summ.render_summary_page(folder, pid, "planning",
                                    session["session_id"], session=session)
    assert page["found"] is False
    assert "could not be generated" in page["body"].lower()

    # Now the model recovers → a real, cached summary is produced on retry.
    monkeypatch.delenv("STUB_SUMMARIZER_FAIL", raising=False)
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "North Star: cache validated summaries")
    good = summ.summarize_session(folder, pid, "planning", session)
    assert "error" not in good
    assert "validated summaries" in " ".join(good["claims"]).lower()
    assert jp.exists(), "successful retry must write the cache"


# ── FIX 2 — ALL-UNGROUNDED claims → honest note, not a silent blank ──────────

def test_all_ungrounded_claims_render_honest_note(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid, session = _planning_session_with_docs(rnd, eh, sessions, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    # Emit only claims whose terms never appear in the member docs.
    monkeypatch.setenv(
        "STUB_SUMMARIZER_CLAIMS",
        "Quux frobnicate zzyzx wibble\nbogus xylophone kumquat narwhal")

    out = summ.summarize_session(folder, pid, "planning", session)
    assert out["claims"] == []
    # The model ran successfully, so this IS cached (run-once) but flagged.
    assert out.get("no_grounded_claims") is True
    assert "error" not in out
    jp = summ._summary_json_path(folder, pid, "planning", session["session_id"])
    assert jp.exists()

    # Rendered page shows the explicit honest note, not a silent blank.
    page = summ.render_summary_page(folder, pid, "planning",
                                    session["session_id"], session=session)
    assert page["found"] is True
    assert "no grounded claims" in page["body"].lower()


# ── ZERO MEMBER FILES — no crash, honest empty/retry state ───────────────────

def test_zero_member_files_no_crash(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    proj = rnd.add_project("Empty", str(folder))
    pid = proj["id"]
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "North Star: cache validated summaries")

    session = {"session_id": "empty::session", "title": "Empty session",
               "member_files": []}
    # With no member docs there is no grounding corpus, so all claims are
    # ungrounded → honest 'no grounded claims' state, no crash.
    out = summ.summarize_session(folder, pid, "planning", session)
    assert out["claims"] == []
    assert out.get("no_grounded_claims") is True
    page = summ.render_summary_page(folder, pid, "planning",
                                    "empty::session", session=session)
    assert "no grounded claims" in page["body"].lower()


# ── GROUNDING unit tests: is_grounded / _key_terms edge cases ────────────────

def test_grounding_unit_edge_cases(mods):
    jr, eh, rnd, sessions, summ = mods
    corpus = ("the north star is a truthful memory of trio work; cache "
              "validated summaries for each session").lower()

    # Empty claim → ungrounded (nothing anchors it).
    assert summ.is_grounded("", corpus) is False
    # Punctuation-only claim → no key terms → ungrounded.
    assert summ.is_grounded("!!! ??? ...", corpus) is False
    # All terms missing from the corpus → ungrounded.
    assert summ.is_grounded("frobnicate zzyzx wibble quux", corpus) is False
    # A single incidental shared word is not enough (GROUNDING_MIN_TERMS=2).
    assert summ.is_grounded("cache flarp zzyzx wibblewobble", corpus) is False
    # Strong overlap → grounded (>= ratio AND >= min grounded terms).
    assert summ.is_grounded("cache validated summaries session", corpus) is True

    # _key_terms: lowercased alphanumeric >=3-char tokens; punctuation dropped.
    assert summ._key_terms("Cache, Validated! summaries.") == [
        "cache", "validated", "summaries"]
    assert summ._key_terms("a an of") == []  # all <3 chars
    assert summ._key_terms("!!! ???") == []


# ─────────────────────────────────────────────────────────────────────────────
# v3 Wave 5 — PROJECT summary (generate-once + cache + force + grounding).
# IMPLEMENTATION-PLAN lines 124-141: a background project-summary generator that
# mirrors the session pipeline, seeded from CLAUDE.md + recent plan docs +
# deliverables, validated by the SAME grounding filter, cached under .anchor.
# ─────────────────────────────────────────────────────────────────────────────

def _project_with_identity_docs(rnd, folder):
    """A project whose CLAUDE.md + recent plan doc form the grounding corpus."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "CLAUDE.md").write_text(
        "# Anchor\n\n"
        "## What this project is\n"
        "Anchor is a productivity system that manages markdown task files.\n",
        encoding="utf-8")
    plan = folder / "planning" / "rnd-v3"
    plan.mkdir(parents=True, exist_ok=True)
    (plan / "MASTER-PLAN.md").write_text(
        "# Mission Control\n\n"
        "## North Star\n"
        "Make the surface a truthful memory of trio work.\n",
        encoding="utf-8")
    proj = rnd.add_project("Anchor", str(folder))
    return proj["id"]


def test_project_summary_generate_once_and_cache(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity_docs(rnd, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    grounded = "Anchor is a productivity system managing markdown task files"
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", grounded)

    # FIRST call → model runs GENERATE_RUNS times, writes the cache.
    s1 = summ.summarize_project(folder, pid)
    first = counter.read_text(encoding="utf-8") if counter.exists() else ""
    assert len(first) == summ.GENERATE_RUNS
    assert s1.get("kind") == "project"
    assert "productivity system" in " ".join(s1["claims"]).lower()
    # summary_text (the row's text) is the joined grounded claims.
    assert "productivity system" in s1["summary_text"].lower()

    # Cache files are written + git-trackable (.json + .md).
    jp = summ._project_summary_json_path(folder, pid)
    mp = summ._project_summary_md_path(folder, pid)
    assert jp.exists() and mp.exists()

    # SECOND call → served from cache, model NOT re-run (run-once).
    s2 = summ.summarize_project(folder, pid)
    second = counter.read_text(encoding="utf-8") if counter.exists() else ""
    assert len(second) == len(first), "second call must serve cache, not re-run"
    assert s2["claims"] == s1["claims"]
    assert s2.get("generated_at") == s1.get("generated_at")

    # load_cached_project (the render-path read) returns the same thing, no run.
    cached = summ.load_cached_project(folder, pid)
    assert cached["claims"] == s1["claims"]
    assert len(counter.read_text(encoding="utf-8")) == len(first)


def test_project_summary_force_reruns(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity_docs(rnd, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Anchor is a productivity system for task files")
    s1 = summ.summarize_project(folder, pid)
    n1 = len(counter.read_text(encoding="utf-8"))
    assert n1 == summ.GENERATE_RUNS

    # Cache hit: no new model calls.
    summ.summarize_project(folder, pid)
    assert len(counter.read_text(encoding="utf-8")) == n1

    # force=True re-runs + overwrites with the new grounded content.
    monkeypatch.setenv(
        "STUB_SUMMARIZER_CLAIMS",
        "North Star: a truthful memory of trio work")
    s2 = summ.summarize_project(folder, pid, force=True)
    n2 = len(counter.read_text(encoding="utf-8"))
    assert n2 == n1 + summ.GENERATE_RUNS, "force must re-run the model"
    assert "truthful memory" in " ".join(s2["claims"]).lower()
    on_disk = summ.load_cached_project(folder, pid)
    assert "truthful memory" in json.dumps(on_disk).lower()


def test_project_summary_grounding_drops_ungrounded(mods, tmp_path, monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity_docs(rnd, folder)

    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(tmp_path / "calls.txt"))
    grounded = "Anchor is a productivity system for markdown task files"
    ungrounded = "Quux frobnicate zzyzx wibble bogus unrelated claim"
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", grounded + "\n" + ungrounded)

    s = summ.summarize_project(folder, pid)
    joined = " ".join(s["claims"]).lower()
    assert "productivity system" in joined
    assert "frobnicate" not in joined
    assert "zzyzx" not in joined
    # The on-disk cache is clean of the hallucinated terms too.
    jp = summ._project_summary_json_path(folder, pid)
    assert "frobnicate" not in jp.read_text(encoding="utf-8").lower()


def test_project_summary_failed_run_does_not_poison_cache(mods, tmp_path,
                                                          monkeypatch):
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity_docs(rnd, folder)

    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(tmp_path / "calls.txt"))
    monkeypatch.setenv("STUB_SUMMARIZER_FAIL", "1")
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS", "ignored on failure")

    out = summ.summarize_project(folder, pid)
    assert out.get("error") == "generation_failed"
    assert out["claims"] == []
    jp = summ._project_summary_json_path(folder, pid)
    assert not jp.exists(), "failed run must NOT write a poisoned cache"
    assert summ.load_cached_project(folder, pid) is None

    # Recovery → a real cached summary on retry.
    monkeypatch.delenv("STUB_SUMMARIZER_FAIL", raising=False)
    monkeypatch.setenv("STUB_SUMMARIZER_CLAIMS",
                       "Anchor is a productivity system for task files")
    good = summ.summarize_project(folder, pid)
    assert "error" not in good
    assert "productivity system" in " ".join(good["claims"]).lower()
    assert jp.exists(), "successful retry must write the cache"


# ── project run-once under CONCURRENCY (per-project lock) ─────────────────────

def test_concurrent_summarize_project_runs_model_once(mods, tmp_path,
                                                      monkeypatch):
    """Two threads summarize the SAME uncached PROJECT at once. Mirrors the
    session-level test_concurrent_summarize_runs_model_once: the per-project
    lock + double-checked cache re-read must make the model run exactly
    GENERATE_RUNS times total (not 2x), both callers get the SAME cached
    summary, and the cache is written once."""
    import threading
    jr, eh, rnd, sessions, summ = mods
    folder = tmp_path / "proj"
    pid = _project_with_identity_docs(rnd, folder)

    counter = tmp_path / "calls.txt"
    monkeypatch.setenv("STUB_SUMMARIZER_COUNTER", str(counter))
    monkeypatch.setenv(
        "STUB_SUMMARIZER_CLAIMS",
        "Anchor is a productivity system managing markdown task files")

    results = {}
    barrier = threading.Barrier(2)

    def worker(name):
        barrier.wait()  # maximize the race: both enter summarize together
        results[name] = summ.summarize_project(folder, pid)

    t1 = threading.Thread(target=worker, args=("a",))
    t2 = threading.Thread(target=worker, args=("b",))
    t1.start(); t2.start()
    t1.join(timeout=120); t2.join(timeout=120)
    assert not t1.is_alive() and not t2.is_alive(), "summarize threads hung"

    calls = counter.read_text(encoding="utf-8") if counter.exists() else ""
    assert len(calls) == summ.GENERATE_RUNS, (
        f"model must run GENERATE_RUNS={summ.GENERATE_RUNS} times total under "
        f"concurrency, not 2x; got {len(calls)} calls")
    # Both callers got the identical (cached) summary.
    assert results["a"]["claims"] == results["b"]["claims"]
    assert results["a"].get("generated_at") == results["b"].get("generated_at")
    assert "productivity system" in " ".join(results["a"]["claims"]).lower()
    # The cache was written exactly once (.json + .md present, single content).
    jp = summ._project_summary_json_path(folder, pid)
    mp = summ._project_summary_md_path(folder, pid)
    assert jp.exists() and mp.exists()
    on_disk = summ.load_cached_project(folder, pid)
    assert on_disk["claims"] == results["a"]["claims"]
