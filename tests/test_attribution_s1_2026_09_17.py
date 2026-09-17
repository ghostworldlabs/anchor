"""codex-discipline Wave 2 S1 (2026-09-17) — attribution: one honest seam, ids on every row.

STUB GATE for the first slice of John's fit contract ("everything should have an
ID that flows back up to the particular project in an AI cockpit so we know how
much is being spent"):

- ``usage_capture.ingest_usage``: a missing price stays ``None`` (never a priced
  $0); states are honest (measured / unpriced / unknown); write-once in the
  ledger AND in the per-project index (a replay repairs, never double counts).
- a delegated job with no project id is attributed to the registered project at
  or above the folder it ran in; an empty envelope is an ``unknown`` row, never
  dropped; a bare launch never becomes an effort pointer record.
- a steward's finalized turn writes one ledger row carrying project_id,
  folder_path, effort_dir, the engine session and the provider's invocation id;
  a duplicate final adds nothing.
- the rollup shows delegated jobs as a source of their own, joined by folder,
  with honest states; the total carries them exactly once; steward turns stay
  sourced from cockpit state (history + in-flight), never summed twice.
"""
import importlib
import io
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
INVOCATION = "956f7cb6-404f-4cdb-8820-9d6ed2c7d189"
JOB_UUID = "6f5f2f1e-0d8e-4c7c-9a1b-2d3e4f5a6b7c"
OTHER_UUID = "7a6b5c4d-3e2f-4a1b-8c9d-0e1f2a3b4c5d"


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "journal", "usage_ledger", "usage_index", "usage_capture",
                "job_runner", "rnd_registry", "session_registry", "sessions",
                "effort_history", "summarizer", "effort_view"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    project = tmp_path / "proj"
    effort = project / "planning" / "eff-1"
    effort.mkdir(parents=True)
    pid = rnd_registry.add_project("Attribution", str(project), scaffold=False)["id"]
    return {"pid": pid, "project": str(project), "effort": str(effort)}


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


# ── the seam ──────────────────────────────────────────────────────────────────

def test_ingest_usage_keeps_null_cost_derives_states_and_writes_once(env):
    import usage_capture as uc
    import usage_index as ui
    import usage_ledger as ul
    pid = env["pid"]
    key = uc.turn_key(SESSION, "t1")
    assert uc.ingest_usage(SESSION, key, source=uc.SOURCE_STEWARD_TURN, native_id="t1",
                           tokens=120, cost_usd=None, project_id=pid,
                           folder_path=env["project"], effort_dir=env["effort"],
                           cli="chatgpt") == 1
    row = ul.ledger_entries(SESSION)[0]
    assert row["cost_usd"] is None
    assert row["usage_state"] == "unpriced"
    assert row["project_id"] == pid and row["effort_dir"] == env["effort"]
    assert row["engine_session_uuid"] == SESSION and row["source"] == "steward-turn"
    assert uc.usage_state_for(10, 0.5) == "measured"
    assert uc.usage_state_for(10, 0.0) == "unpriced"
    assert uc.usage_state_for(10, None) == "unpriced"
    assert uc.usage_state_for(0, None) == "unknown"
    assert uc.usage_state_for(0, 0.3) == "unknown"
    # write-once: a replay with different figures adds nothing anywhere
    assert uc.ingest_usage(SESSION, key, source=uc.SOURCE_STEWARD_TURN, native_id="t1",
                           tokens=999, cost_usd=5.0, project_id=pid) == 0
    rows = ui.load_rows(pid)
    assert len(rows) == 1 and rows[0]["tokens"] == 120 and rows[0]["cost_usd"] is None
    assert len(ul.ledger_entries(SESSION)) == 1
    assert "usage" not in rows[0]          # the index keeps the compact row only


def test_replay_repairs_a_missing_index_row_without_a_second_count(env):
    import usage_capture as uc
    import usage_index as ui
    pid = env["pid"]
    key = uc.turn_key(SESSION, "t2")
    assert uc.ingest_usage(SESSION, key, source=uc.SOURCE_JOB, native_id="j",
                           tokens=5, cost_usd=0.1, project_id=pid) == 1
    ui.index_path(pid).unlink()
    assert uc.ingest_usage(SESSION, key, source=uc.SOURCE_JOB, native_id="j",
                           tokens=5, cost_usd=0.1, project_id=pid) == 0
    assert len(ui.load_rows(pid)) == 1


def test_resolve_project_picks_the_nearest_registered_folder(env):
    import usage_capture as uc
    pid, folder = uc.resolve_project(env["effort"])
    assert pid == env["pid"] and _same(folder, env["project"])
    assert uc.resolve_project(env["project"])[0] == env["pid"]
    assert uc.resolve_project(str(Path(env["project"]).parent)) == (None, None)
    assert uc.resolve_project(None) == (None, None)
    assert uc.resolve_project(str(Path(env["project"] + "-sibling"))) == (None, None)


# ── delegated jobs ────────────────────────────────────────────────────────────

def _job_rec(jid, **over):
    rec = {"job_id": jid, "lane": "research", "status": "running", "started_at": 1.0,
           "exit_code": None, "session_id": None, "backend": "claude", "cost": None}
    rec.update(over)
    return rec


def test_job_without_project_is_attributed_by_the_folder_it_ran_in(env):
    import effort_history as eh
    import job_runner as jr
    import usage_index as ui
    import usage_ledger as ul
    jid = "job-bare-1"
    jr._write_record(_job_rec(jid, cwd=env["effort"], metadata_only=True))
    jr._finalize(jid, 0, result_envelope={
        "type": "result", "session_id": JOB_UUID, "total_cost_usd": 0.42,
        "duration_ms": 5000, "usage": {"input_tokens": 100, "output_tokens": 200}})
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "job" and row["native_id"] == jid
    assert row["project_id"] == env["pid"] and _same(row["folder_path"], env["project"])
    assert row["effort_dir"] == env["effort"]
    assert row["usage_state"] == "measured" and row["cost_usd"] == 0.42
    assert row["tokens"] == 300 and row["metadata_only"] is True and row["cli"] == "claude"
    assert row["engine_session_uuid"] == JOB_UUID
    entry = ul.ledger_entries(JOB_UUID)[0]
    assert entry["job_id"] == jid and entry["total_cost_usd"] == 0.42
    assert entry["input_tokens"] == 100 and entry["output_tokens"] == 200
    # a bare launch never becomes an effort pointer record (no fake effort on the board)
    for lane in eh.ROLLUP_LANES:
        assert eh.list_efforts(env["project"], env["pid"], lane) == []
    # and a re-finalize (restart replay) counts nothing twice
    jr._finalize(jid, 0, result_envelope={
        "type": "result", "session_id": JOB_UUID, "total_cost_usd": 0.42,
        "duration_ms": 5000, "usage": {"input_tokens": 100, "output_tokens": 200}})
    assert len(ui.load_rows(env["pid"])) == 1 and len(ul.ledger_entries(JOB_UUID)) == 1


def test_subscription_job_is_unpriced_and_an_empty_envelope_is_unknown(env):
    import job_runner as jr
    import usage_index as ui
    import usage_ledger as ul
    jr._write_record(_job_rec("job-sub", cwd=env["project"]))
    jr._finalize("job-sub", 0, result_envelope={
        "type": "result", "session_id": JOB_UUID, "cost_state": "subscription_covered",
        "billing_mode": "subscription", "usage": {"input_tokens": 10, "output_tokens": 5}})
    jr._write_record(_job_rec("job-empty", cwd=env["project"]))
    jr._finalize("job-empty", 0, result_envelope={
        "type": "result", "session_id": OTHER_UUID, "total_cost_usd": 0.0, "usage": {}})
    by_id = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert by_id["job-sub"]["cost_usd"] is None
    assert by_id["job-sub"]["usage_state"] == "unpriced" and by_id["job-sub"]["tokens"] == 15
    assert by_id["job-empty"]["usage_state"] == "unknown" and by_id["job-empty"]["tokens"] == 0
    assert len(ul.ledger_entries(OTHER_UUID)) == 1        # never dropped
    assert ul.ledger_entries(JOB_UUID)[0]["total_cost_usd"] is None   # never a priced $0


def test_job_outside_every_registered_project_stays_in_the_ledger_only(env):
    import job_runner as jr
    import usage_index as ui
    import usage_ledger as ul
    outside = str(Path(env["project"]).parent / "elsewhere")
    Path(outside).mkdir()
    jr._write_record(_job_rec("job-out", cwd=outside))
    jr._finalize("job-out", 0, result_envelope={
        "type": "result", "session_id": OTHER_UUID, "total_cost_usd": 0.05,
        "usage": {"input_tokens": 1, "output_tokens": 1}})
    entry = ul.ledger_entries(OTHER_UUID)[0]
    assert entry["project_id"] is None and entry["effort_dir"] == outside
    assert ui.load_rows(env["pid"]) == []


# ── steward turns ─────────────────────────────────────────────────────────────

@pytest.fixture
def cockpit(env, monkeypatch, tmp_path):
    import anchor_settings
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings",
                        lambda: {"default_cli": "chatgpt", "settings_revision": 1})
    engine = engine_mod.Engine(env["effort"], fake=True)
    engine.cli = "chatgpt"
    engine.session_id = SESSION
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(engine, "_status_update", lambda **kwargs: None)
    return engine


def _result(**extra):
    return {"type": "result", "subtype": "success", "session_id": SESSION,
            "usage_invocation_id": INVOCATION,
            "usage": {"input_tokens": 150, "output_tokens": 30, "cached_input_tokens": 90},
            "token_status": "reported", "usage_source": "codex-turn-completed",
            "total_cost_usd": 0.25, "duration_ms": 2000, **extra}


def test_steward_turn_writes_one_attributed_ledger_row(env, cockpit):
    import usage_index as ui
    import usage_ledger as ul
    cockpit.turn_text = "Completed response."
    cockpit._handle(_result(), cockpit.proc)
    rows = [r for r in ul.ledger_entries(SESSION) if r.get("source") == "steward-turn"]
    assert len(rows) == 1
    row = rows[0]
    assert row["native_id"] == INVOCATION and row["project_id"] == env["pid"]
    assert _same(row["folder_path"], env["project"]) and row["effort_dir"] == env["effort"]
    assert row["cli"] == "chatgpt" and row["engine_session_uuid"] == SESSION
    assert row["tokens"] == 180 and row["cost_usd"] == 0.25
    assert row["usage_state"] == "measured" and row["duration_ms"] == 2000
    assert row["turn_id"].startswith("chatgpt:" + SESSION) and row["tick"] is False
    assert [r["native_id"] for r in ui.load_rows(env["pid"])] == [INVOCATION]
    cockpit.turn_text = "Completed response."
    cockpit._handle(_result(), cockpit.proc)      # a duplicate final adds nothing
    assert len(ul.ledger_entries(SESSION)) == 1 and len(ui.load_rows(env["pid"])) == 1


def test_unpriced_steward_turn_keeps_cost_null(env, cockpit):
    import usage_ledger as ul
    cockpit.turn_text = "Done."
    cockpit._handle(_result(total_cost_usd=None), cockpit.proc)
    row = ul.ledger_entries(SESSION)[0]
    assert row["cost_usd"] is None and row["usage_state"] == "unpriced"
    assert row["tokens"] == 180


# ── the reader ────────────────────────────────────────────────────────────────

def test_rollup_shows_delegated_jobs_by_folder_with_honest_states(env):
    import usage_capture as uc
    from steward_cockpit import steward_routes
    pid, project, effort = env["pid"], env["project"], env["effort"]
    other_effort = str(Path(project) / "planning" / "eff-2")
    uc.ingest_usage("a1", "k1", source="job", native_id="j1", tokens=1000, cost_usd=0.5,
                    project_id=pid, folder_path=project, effort_dir=effort, cli="claude",
                    duration_ms=4000)
    uc.ingest_usage("a2", "k2", source="job", native_id="j2", tokens=2000, cost_usd=None,
                    project_id=pid, folder_path=project, effort_dir=effort, cli="chatgpt")
    uc.ingest_usage("a3", "k3", source="job", native_id="j3", tokens=0, cost_usd=None,
                    project_id=pid, folder_path=project, effort_dir=other_effort, cli="chatgpt")
    # a steward turn row is attribution, not a second sum: cockpit state stays its source
    uc.ingest_usage("a4", "k4", source="steward-turn", native_id="t", tokens=50, cost_usd=0.1,
                    project_id=pid, folder_path=project, effort_dir=effort, cli="claude")
    r = steward_routes._usage_rollup(effort, estate={})
    jobs = r["jobs"]
    assert jobs["count"] == 2 and jobs["unknown"] == 0
    assert jobs["tokens"] == 3000 and jobs["reported_spend"] == 0.5
    assert jobs["unpriced_turns"] == 1 and jobs["secs"] == 4
    assert jobs["cost_status"] == "partial" and jobs["token_status"] == "reported"
    assert "$0.50" in jobs["cost_text"] and "ChatGPT subscription" in jobs["cost_text"]
    assert r["total"]["tokens"] == 3000 and r["total"]["reported_spend"] == 0.5
    assert r["total"]["unpriced_turns"] == 1
    whole = steward_routes._usage_rollup(project, estate={})
    assert whole["jobs"]["count"] == 3 and whole["jobs"]["unknown"] == 1
    assert whole["jobs"]["tokens"] == 3000 and whole["jobs"]["token_status"] == "partial"
    empty = steward_routes._usage_rollup(str(Path(project) / "planning" / "eff-3"), estate={})
    assert empty["jobs"]["count"] == 0 and empty["total"]["tokens"] == 0
    assert empty["jobs"]["cost_status"] == "unavailable"


def test_rollup_without_any_index_is_unchanged(env):
    from steward_cockpit import steward_routes
    r = steward_routes._usage_rollup(env["effort"], estate={})
    assert r["jobs"]["count"] == 0 and r["jobs"]["unknown"] == 0
    assert r["total"]["tokens"] == 0 and r["total"]["cost_status"] == "unavailable"
    assert set(r) == {"steward", "terms", "jobs", "total"}


def test_spend_line_names_delegated_jobs_only_when_rows_exist():
    js = (Path(__file__).resolve().parents[1] / "steward_cockpit" / "static"
          / "shared.js").read_text(encoding="utf-8")
    assert "st.usage_rollup.jobs" in js
    assert "jobsUsage.count > 0" in js          # shown only when rows exist
    assert "unknown usage" in js               # unknown is a count, never a zero
