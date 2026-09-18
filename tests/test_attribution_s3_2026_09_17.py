"""codex-discipline Wave 2 S3 (2026-09-17) — ids into children, skill seats under the effort.

STUB GATE for the third slice of John's rule ("the skills they call spawn
agents ... every one carries an ID that flows back up to the particular
project"). Behaviours only:

- the ids a child inherits by environment name (project, effort dir, job or
  engine session, where to drop receipts) are on a delegated job's environment,
  a steward's, and a terminal session's.
- a receipt file a trio seat dropped becomes one row through the seam: keyed by
  the seat's native session, attributed by the inherited ids (else by the folder
  it ran in), priced when the seat reported a charge, unpriced when only tokens,
  unknown when nothing; the job wins on the same engine session; a consumed
  file is removed; a replay adds nothing.
- the rollup shows seats as a bucket beside jobs and children.
"""
import importlib
import io
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"
SEAT_A = "3f2c1b0a-9d8e-4c7b-8a6f-5e4d3c2b1a09"
SEAT_B = "01a0af74-186b-7262-b53e-ece8c5b956a7"
JOB_UUID = "6f5f2f1e-0d8e-4c7c-9a1b-2d3e4f5a6b7c"


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(tmp_path / "sidecars"))
    (tmp_path / "sidecars").mkdir()
    for mod in ("paths", "journal", "usage_ledger", "usage_index", "usage_capture",
                "job_runner", "rnd_registry", "session_registry", "sessions",
                "effort_history", "summarizer", "effort_view", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    project = tmp_path / "proj"
    effort = project / "planning" / "eff-1"
    effort.mkdir(parents=True)
    pid = rnd_registry.add_project("Attribution", str(project), scaffold=False)["id"]
    return {"pid": pid, "project": str(project), "effort": str(effort), "data": data}


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _receipt(root, *, native=SEAT_A, family="claude", model="claude-fable-5-1", usage=None,
             cost=None, env_ids=None, cwd=None, name=None, at="2026-09-17T20:00:00Z"):
    root.mkdir(parents=True, exist_ok=True)
    body = {"schema": "anchor.receipt.v1", "at": at, "driver": family if family != "chatgpt" else "chatgpt-cli",
            "family": family, "label": "reviewer", "kind": "initial", "outcome": "accepted", "ok": True,
            "status": "success", "requested_model": model, "model_served": model, "model_attested": True,
            "native_id": native, "usage": usage, "cost_usd": cost, "duration_ms": 1200,
            "cwd": cwd, "pid": 4242, "env": env_ids or {}}
    p = root / ((name or native or "r") + ".json")
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


# ── ids into children ─────────────────────────────────────────────────────────

def test_attribution_env_names_the_ids_a_child_inherits(env):
    import usage_capture as uc
    e = uc.attribution_env(effort_dir=env["effort"], job_id="job-9")
    assert e["ANCHOR_PROJECT_ID"] == env["pid"] and e["ANCHOR_EFFORT_DIR"] == env["effort"]
    assert e["ANCHOR_JOB_ID"] == "job-9" and "ANCHOR_SESSION_ID" not in e
    assert _same(e["ANCHOR_RECEIPTS_DIR"], str(env["data"] / ".anchor" / "receipts"))
    e = uc.attribution_env(project_id="explicit", session_id=SESSION)
    assert e["ANCHOR_PROJECT_ID"] == "explicit" and e["ANCHOR_SESSION_ID"] == SESSION and "ANCHOR_EFFORT_DIR" not in e
    e = uc.attribution_env(effort_dir=str(Path(env["project"]).parent / "elsewhere"))
    assert "ANCHOR_PROJECT_ID" not in e and e["ANCHOR_EFFORT_DIR"].endswith("elsewhere")


def test_a_delegated_job_launches_with_the_ids_in_its_environment(env, monkeypatch):
    import job_runner as jr
    seen = {}

    class FakeProc:
        pid = 4321
        stdout = io.StringIO("")
        stdin = None

        def poll(self):
            return 0

    def fake_popen(argv, **kw):
        seen["env"] = kw.get("env") or {}
        return FakeProc()
    monkeypatch.setattr(jr.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(jr, "_register_swarm_session", lambda *a, **k: None)
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", "python -c pass")
    try:
        jr.launch("research", cwd=env["effort"], prompt="hi", job_id="job-env-1", backend="claude",
                  project_id=env["pid"], folder_path=env["project"])
    except Exception:
        pass                                                   # the fake process ends the launch early
    e = seen.get("env") or {}
    assert e.get("ANCHOR_PROJECT_ID") == env["pid"] and e.get("ANCHOR_EFFORT_DIR") == env["effort"]
    assert e.get("ANCHOR_JOB_ID") == "job-env-1" and e.get("ANCHOR_RECEIPTS_DIR")


def test_a_terminal_session_env_carries_the_ids(env):
    import terminal_session as ts
    e = ts._model_launch_env({"model": "x"}, project_id=env["pid"], session_id=SESSION)
    assert e["ANCHOR_PROJECT_ID"] == env["pid"] and _same(e["ANCHOR_EFFORT_DIR"], env["project"])
    assert e["ANCHOR_SESSION_ID"] == SESSION and e["ANCHOR_RECEIPTS_DIR"]
    e = ts._model_launch_env(None, project_id=env["pid"], session_id=SESSION)
    assert e["ANCHOR_PROJECT_ID"] == env["pid"] and "PATH" in e or "Path" in e


def test_the_steward_process_env_carries_the_ids(env, monkeypatch, tmp_path):
    import anchor_settings
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": "claude", "settings_revision": 1})
    engine = engine_mod.Engine(env["effort"], fake=True)
    e = engine._spawn_env()
    assert e["ANCHOR_PROJECT_ID"] == env["pid"] and e["ANCHOR_EFFORT_DIR"] == env["effort"]
    assert "ANCHOR_SESSION_ID" not in e and e["ANCHOR_RECEIPTS_DIR"]


# ── seat receipts through the seam ────────────────────────────────────────────

def test_receipts_become_seat_rows_priced_unpriced_and_unknown(env):
    import usage_capture as uc
    import usage_index as ui
    import usage_ledger as ul
    root = env["data"] / ".anchor" / "receipts"
    ids = {"project_id": env["pid"], "effort_dir": env["effort"], "session_id": SESSION}
    _receipt(root, native=SEAT_A, family="claude", cost=0.37,
             usage={"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 0}, env_ids=ids)
    _receipt(root, native="01a0b0c6-2222-7b50-a38b-b91aad842222", family="chatgpt", model="gpt-6-astra",
             usage={"input_tokens": 10, "cached_input_tokens": 5, "output_tokens": 3, "reasoning_output_tokens": 1}, env_ids=ids)
    _receipt(root, native=SEAT_B, family="grok", model="grok-4.6-build", usage=None, env_ids=ids)
    assert uc.ingest_receipts() == 2                            # two seats reached a ledger doc
    rows = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert set(rows) == {SEAT_A, "01a0b0c6-2222-7b50-a38b-b91aad842222", SEAT_B}
    a = rows[SEAT_A]
    assert a["source"] == "seat" and a["usage_state"] == "measured" and a["cost_usd"] == 0.37
    assert a["tokens"] == 1150 and a["cli"] == "claude" and a["parent_id"] == SESSION
    assert a["effort_dir"] == env["effort"] and a["recorded_at"] == "2026-09-17T20:00:00Z"
    assert rows["01a0b0c6-2222-7b50-a38b-b91aad842222"]["usage_state"] == "unpriced"
    assert rows["01a0b0c6-2222-7b50-a38b-b91aad842222"]["tokens"] == 19 and rows["01a0b0c6-2222-7b50-a38b-b91aad842222"]["cli"] == "chatgpt"
    assert rows[SEAT_B]["usage_state"] == "unknown" and rows[SEAT_B]["engine_session_uuid"] is None
    assert ul.ledger_entries(SEAT_A)[0]["model"] == "claude-fable-5-1"      # the seat's own engine session is its doc
    assert list(root.glob("*.json")) == []                       # consumed
    assert uc.ingest_receipts() == 0 and len(ui.load_rows(env["pid"])) == 3


def test_a_receipt_without_ids_attributes_by_the_folder_it_ran_in(env):
    import usage_capture as uc
    import usage_index as ui
    root = env["data"] / ".anchor" / "receipts"
    _receipt(root, native=SEAT_A, cwd=env["effort"], usage={"input_tokens": 5, "output_tokens": 5}, cost=0.01)
    _receipt(root, native=SEAT_B, cwd=str(Path(env["project"]).parent / "elsewhere"), usage={"input_tokens": 1, "output_tokens": 1}, name="outside")
    uc.ingest_receipts()
    rows = ui.load_rows(env["pid"])
    assert [r["native_id"] for r in rows] == [SEAT_A] and rows[0]["effort_dir"] == env["effort"] and rows[0]["parent_id"] is None
    assert list(root.glob("*.json")) == []                       # the unattributed one still reached the ledger and was consumed


def test_the_job_wins_on_the_same_engine_session(env):
    import usage_capture as uc
    import usage_index as ui
    root = env["data"] / ".anchor" / "receipts"
    uc.ingest_usage(JOB_UUID, "job-key", source="job", native_id="job-1", tokens=500, cost_usd=0.5,
                    project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"], cli="claude")
    _receipt(root, native=JOB_UUID, cost=0.5, usage={"input_tokens": 400, "output_tokens": 100},
             env_ids={"project_id": env["pid"], "effort_dir": env["effort"]})
    assert uc.ingest_receipts() == 0
    rows = ui.load_rows(env["pid"])
    assert len(rows) == 1 and rows[0]["source"] == "job"
    assert list(root.glob("*.json")) == []


def test_a_torn_young_receipt_waits_and_an_old_one_is_dropped(env):
    import usage_capture as uc
    root = env["data"] / ".anchor" / "receipts"
    root.mkdir(parents=True)
    torn = root / "torn.json"
    torn.write_text('{"schema": "anchor.receipt.v1", "native_id": "x"', encoding="utf-8")
    uc.ingest_receipts()
    assert torn.exists()                                          # young: left for the next sweep
    uc.ingest_receipts(now=time.time() + 120)
    assert not torn.exists()                                      # old: dropped


# ── the steward sweeps receipts at its turn end ───────────────────────────────

def test_turn_end_sweeps_receipts(env, monkeypatch, tmp_path):
    import anchor_settings
    import usage_index as ui
    from steward_cockpit import steward_engine as engine_mod
    monkeypatch.setattr(engine_mod, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(anchor_settings, "load_settings", lambda: {"default_cli": "chatgpt", "settings_revision": 1})
    engine = engine_mod.Engine(env["effort"], fake=True)
    engine.cli = "chatgpt"
    engine.session_id = SESSION
    engine.proc = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    monkeypatch.setattr(engine, "_status_update", lambda **kwargs: None)
    _receipt(env["data"] / ".anchor" / "receipts", native=SEAT_A, cost=0.2, usage={"input_tokens": 9, "output_tokens": 1},
             env_ids={"project_id": env["pid"], "effort_dir": env["effort"], "session_id": SESSION})
    engine.turn_text = "Reviewed."
    engine._handle({"type": "result", "subtype": "success", "session_id": SESSION,
                    "usage": {"input_tokens": 150, "output_tokens": 30, "cached_input_tokens": 90},
                    "total_cost_usd": None, "duration_ms": 2000}, engine.proc)
    rows = {r["source"]: r for r in ui.load_rows(env["pid"])}
    assert set(rows) == {"seat"} and rows["seat"]["native_id"] == SEAT_A and rows["seat"]["parent_id"] == SESSION


# ── the reader ────────────────────────────────────────────────────────────────

def test_rollup_shows_seats_beside_jobs_and_children(env):
    import usage_capture as uc
    from steward_cockpit import steward_routes
    root = env["data"] / ".anchor" / "receipts"
    ids = {"project_id": env["pid"], "effort_dir": env["effort"]}
    _receipt(root, native=SEAT_A, cost=0.37, usage={"input_tokens": 100, "output_tokens": 50}, env_ids=ids)
    _receipt(root, native=SEAT_B, family="grok", usage=None, env_ids=ids)
    uc.ingest_receipts()
    uc.ingest_usage("a1", "k1", source="job", native_id="j1", tokens=1000, cost_usd=0.5,
                    project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"], cli="claude")
    r = steward_routes._usage_rollup(env["effort"], estate={})
    seats = r["seats"]
    assert seats["count"] == 2 and seats["unknown"] == 1 and seats["tokens"] == 150
    assert seats["reported_spend"] == 0.37 and seats["cost_status"] == "partial"
    assert r["jobs"]["count"] == 1 and r["jobs"]["reported_spend"] == 0.5    # seats never leak into jobs
    assert r["children"]["count"] == 0 and r["total"]["tokens"] == 0
