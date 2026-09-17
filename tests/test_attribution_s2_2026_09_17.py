"""codex-discipline Wave 2 S2 (2026-09-17) — sub-agent child rows.

STUB GATE for John's sub-agent rule ("agents spawn sub-agents ... every one
carries an ID that flows back up to the particular project"):

- Codex children: rollout threads whose header names the steward's thread as
  parent (a chain for grandchildren) are found from header reads alone; their
  usage is the last cumulative token_count; unrelated threads are ignored.
- Claude children: the subagents/agent-*.jsonl transcripts beside the session's
  sidecar; usage through the ledger's own per-message parser.
- One write-once row per child under the steward's effort, unpriced when tokens
  are known, index-only unknown when not (upgraded once usage appears); a
  replay adds nothing; the parent's own turn row is untouched (no folding).
- The rollup shows children as their own bucket with the rows the line lists.
"""
import importlib
import io
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

SESSION = "01a08260-068d-76a1-99f6-5a7bdf3aaab8"      # the steward's Codex thread / Claude session
INVOCATION = "956f7cb6-404f-4cdb-8820-9d6ed2c7d189"
C1 = "01a0b0c6-1a0b-7b50-a38b-b91aad841455"
C2 = "01a0b0c6-2222-7b50-a38b-b91aad842222"
G1 = "01a0b0c6-3333-7b50-a38b-b91aad843333"
OTHER = "01a0b0c6-4444-7b50-a38b-b91aad844444"
OTHER_PARENT = "01a0b0c6-5555-7b50-a38b-b91aad845555"


def _rollout(path, thread_id, parent=None, label=None, depth=1, model="gpt-6-astra", totals=None):
    meta = {"timestamp": "2026-09-17T19:09:28.077Z", "type": "session_meta",
            "payload": {"id": thread_id, "model_provider": "openai", "cwd": "C:\\\\x",
                        "parent_thread_id": parent,
                        "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent, "depth": depth,
                                                                  "agent_nickname": label}}} if parent else "cli"}}
    lines = [json.dumps(meta)]
    lines.append(json.dumps({"type": "turn_context", "payload": {"model": model, "effort": "ultra"}}))
    if totals is not None:
        for t in (max(1, totals // 2), totals):
            lines.append(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": t - 10, "cached_input_tokens": 5, "output_tokens": 10,
                                      "reasoning_output_tokens": 2, "total_tokens": t}}}}))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    codex_home = tmp_path / "codex-home"
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    sidecars = tmp_path / "sidecars"
    (sidecars / "slug").mkdir(parents=True)
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(sidecars))
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
    day = codex_home / "sessions" / time.strftime("%Y", time.gmtime()) / time.strftime("%m", time.gmtime()) / time.strftime("%d", time.gmtime())
    return {"pid": pid, "project": str(project), "effort": str(effort), "day": day,
            "codex_root": codex_home / "sessions", "sidecars": sidecars}


def _codex_tree(env, c2_totals=None):
    d = env["day"]
    _rollout(d / f"rollout-2026-09-17T19-00-00-{SESSION}.jsonl", SESSION)                       # the steward
    _rollout(d / f"rollout-2026-09-17T19-09-28-{C1}.jsonl", C1, parent=SESSION, label="Chandrasekhar", totals=1000)
    _rollout(d / f"rollout-2026-09-17T19-10-00-{C2}.jsonl", C2, parent=SESSION, label="Noether", totals=c2_totals)
    _rollout(d / f"rollout-2026-09-17T19-11-00-{G1}.jsonl", G1, parent=C1, label="Ramanujan", depth=2, totals=200)
    _rollout(d / f"rollout-2026-09-17T19-12-00-{OTHER}.jsonl", OTHER, parent=OTHER_PARENT, label="Stranger", totals=999)


# ── discovery ─────────────────────────────────────────────────────────────────

def test_codex_children_follow_the_parent_chain_from_headers_alone(env):
    import usage_capture as uc
    _codex_tree(env)
    kids = uc.codex_children(SESSION, root=env["codex_root"])
    assert [k["id"] for k in kids] == [C1, C2, G1]
    by = {k["id"]: k for k in kids}
    assert by[C1]["parent"] == SESSION and by[C1]["label"] == "Chandrasekhar" and by[C1]["depth"] == 1
    assert by[G1]["parent"] == C1 and by[G1]["depth"] == 2          # a grandchild reaches the steward
    assert uc.codex_children(OTHER_PARENT, root=env["codex_root"]) and \
        [k["id"] for k in uc.codex_children(OTHER_PARENT, root=env["codex_root"])] == [OTHER]
    assert uc.codex_children("not-a-thread", root=env["codex_root"]) == []
    u = uc.codex_rollout_usage(by[C1]["path"])
    assert u["tokens"] == 1000 and u["model"] == "gpt-6-astra" and u["usage"]["output_tokens"] == 10
    assert uc.codex_rollout_usage(by[C2]["path"]) == {"tokens": 0, "usage": None, "model": "gpt-6-astra"}


def test_claude_children_sit_beside_the_session_sidecar(env):
    import usage_capture as uc
    slug = env["sidecars"] / "slug"
    (slug / f"{SESSION}.jsonl").write_text('{"type":"user","message":{"role":"user","content":"hi"}}\n', encoding="utf-8")
    sub = slug / SESSION / "subagents"
    sub.mkdir(parents=True)
    lines = []
    for i, out in enumerate((100, 250)):
        lines.append(json.dumps({"type": "assistant", "sessionId": SESSION, "agentId": "a1",
                                 "message": {"id": f"msg_{i}", "role": "assistant", "model": "claude-fable-5-1",
                                             "usage": {"input_tokens": 10, "cache_creation_input_tokens": 0,
                                                       "cache_read_input_tokens": 1000, "output_tokens": out}}}))
    lines.append(lines[-1])                                              # a repeated message id collapses
    (sub / "agent-a1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    kids = uc.claude_children(SESSION, root=env["sidecars"])
    assert [k["id"] for k in kids] == ["a1"] and kids[0]["parent"] == SESSION
    u = uc.claude_agent_usage(kids[0]["path"])
    assert u["tokens"] == 2 * (10 + 1000) + 100 + 250 and u["model"] == "claude-fable-5-1"
    assert uc.claude_children("00000000-0000-0000-0000-000000000000", root=env["sidecars"]) == []


# ── rows ──────────────────────────────────────────────────────────────────────

def test_ingest_children_writes_one_row_per_child_and_upgrades_unknown_once(env):
    import usage_capture as uc
    import usage_index as ui
    import usage_ledger as ul
    _codex_tree(env)                                                     # C2 has no usage yet
    n = uc.ingest_children(SESSION, "chatgpt", project_id=env["pid"], folder_path=env["project"],
                           effort_dir=env["effort"], codex_root=env["codex_root"])
    assert n == 2                                                        # C1 + G1 reached the ledger; C2 is index-only
    rows = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert set(rows) == {C1, C2, G1}
    assert rows[C1]["source"] == "subagent" and rows[C1]["usage_state"] == "unpriced"
    assert rows[C1]["tokens"] == 1000 and rows[C1]["cost_usd"] is None
    assert rows[C1]["parent_id"] == SESSION and rows[C1]["label"] == "Chandrasekhar"
    assert rows[C1]["model"] == "gpt-6-astra" and rows[C1]["cli"] == "chatgpt"
    assert rows[G1]["parent_id"] == C1 and rows[G1]["tokens"] == 200      # attributed to the effort, parent named
    assert rows[C2]["usage_state"] == "unknown" and rows[C2]["engine_session_uuid"] is None
    ledger = {e["native_id"]: e for e in ul.ledger_entries(SESSION) if e.get("source") == "subagent"}
    assert set(ledger) == {C1, G1} and ledger[C1]["project_id"] == env["pid"]
    # replay: nothing new
    assert uc.ingest_children(SESSION, "chatgpt", project_id=env["pid"], folder_path=env["project"],
                              effort_dir=env["effort"], codex_root=env["codex_root"]) == 0
    assert len(ui.load_rows(env["pid"])) == 3
    # C2's usage arrives: the unknown placeholder upgrades once, the ledger gains its row
    _codex_tree(env, c2_totals=500)
    assert uc.ingest_children(SESSION, "chatgpt", project_id=env["pid"], folder_path=env["project"],
                              effort_dir=env["effort"], codex_root=env["codex_root"]) == 1
    rows = {r["native_id"]: r for r in ui.load_rows(env["pid"])}
    assert len(rows) == 3 and rows[C2]["usage_state"] == "unpriced" and rows[C2]["tokens"] == 500
    assert len([e for e in ul.ledger_entries(SESSION) if e.get("source") == "subagent"]) == 3


def test_children_without_a_project_reach_the_ledger_only(env):
    import usage_capture as uc
    import usage_index as ui
    import usage_ledger as ul
    _codex_tree(env)
    assert uc.ingest_children(SESSION, "chatgpt", effort_dir=str(Path(env["project"]).parent / "elsewhere"),
                              codex_root=env["codex_root"]) == 2
    assert ui.load_rows(env["pid"]) == []
    assert len([e for e in ul.ledger_entries(SESSION) if e.get("source") == "subagent"]) == 2


# ── the steward's turn end ────────────────────────────────────────────────────

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
            "total_cost_usd": None, "duration_ms": 2000, **extra}


def test_turn_end_records_children_without_folding_them_into_the_parent(env, cockpit):
    import usage_index as ui
    import usage_ledger as ul
    _codex_tree(env)
    cockpit.turn_text = "Delegated and done."
    cockpit._handle(_result(), cockpit.proc)
    entries = ul.ledger_entries(SESSION)
    turn = [e for e in entries if e.get("source") == "steward-turn"]
    kids = [e for e in entries if e.get("source") == "subagent"]
    assert len(turn) == 1 and turn[0]["tokens"] == 180          # the parent's own turn, children excluded
    assert {e["native_id"] for e in kids} == {C1, G1}
    assert cockpit.tokens == 180                                 # the cockpit sum never absorbs a child
    rows = ui.load_rows(env["pid"])
    assert sorted(r["native_id"] for r in rows) == sorted([C1, C2, G1])
    assert all(r["source"] == "subagent" and _same(r["effort_dir"], env["effort"]) for r in rows)
    cockpit.turn_text = "Again."
    cockpit._handle(_result(), cockpit.proc)                    # duplicate final: nothing new
    assert len(ul.ledger_entries(SESSION)) == 3 and len(ui.load_rows(env["pid"])) == 3


def _same(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


# ── the reader ────────────────────────────────────────────────────────────────

def test_rollup_lists_children_beside_jobs_and_the_steward_total(env):
    import usage_capture as uc
    from steward_cockpit import steward_routes
    _codex_tree(env)
    uc.ingest_children(SESSION, "chatgpt", project_id=env["pid"], folder_path=env["project"],
                       effort_dir=env["effort"], codex_root=env["codex_root"])
    uc.ingest_usage("a1", "k1", source="job", native_id="j1", tokens=1000, cost_usd=0.5,
                    project_id=env["pid"], folder_path=env["project"], effort_dir=env["effort"], cli="claude")
    r = steward_routes._usage_rollup(env["effort"], estate={})
    kids = r["children"]
    assert kids["count"] == 3 and kids["unknown"] == 1 and kids["tokens"] == 1200
    assert kids["unpriced_turns"] == 2 and kids["cost_status"] == "unavailable"
    assert kids["billing_mode"] == "subscription" and kids["billing_family"] == "chatgpt"
    assert kids["token_status"] == "partial"                     # one child's usage is unknown
    labels = {row["label"] for row in kids["rows"]}
    assert labels == {"Chandrasekhar", "Noether", "Ramanujan"}
    assert {row["state"] for row in kids["rows"]} == {"unpriced", "unknown"}
    assert r["jobs"]["count"] == 1 and r["total"]["tokens"] == 0  # jobs and children stay beside the total
    other = steward_routes._usage_rollup(str(Path(env["project"]) / "planning" / "eff-2"), estate={})
    assert other["children"]["count"] == 0 and other["children"]["rows"] == []
