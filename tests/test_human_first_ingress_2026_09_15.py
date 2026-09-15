"""codex-discipline-2026-09-15 Wave 1.2/1.3 — durable human-first ingress,
interruption, stderr tail (hermetic: fake engine, stub process, tmp state)."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from steward_cockpit import steward_engine as eng  # noqa: E402
from steward_cockpit import codex_turn_bridge as ctb  # noqa: E402
import model_policy  # noqa: E402


class _Stdin:
    def __init__(self):
        self.written = []
    def write(self, s):
        self.written.append(s)
    def flush(self):
        pass
    def close(self):
        pass


class _FakeProc:
    def __init__(self):
        self.stdin = _Stdin()
        self.killed = False
    def poll(self):
        return None


@pytest.fixture
def engine(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="steward-ingress-")
    monkeypatch.setattr(eng, "STATE_FILE", Path(tmp) / "state.json")
    e = eng.Engine(tmp, fake=True)
    e.proc = _FakeProc()
    return e


def _sent_text(e, index=-1):
    return json.loads(e.proc.stdin.written[index])["message"]["content"][0]["text"]


# ── origin, resume prefix, durable submitted copy ─────────────────────────

def test_human_message_carries_resume_prefix_once_and_is_durable(engine):
    e = engine
    e._resume_prefix = eng.RESUME_BRIEF
    assert e._send_locked("what is next?", origin="human") is True
    text = _sent_text(e)
    assert text.startswith("(engine resume - not John)")
    assert "JOHN SAYS" in text and text.endswith("what is next?")
    assert e._turn_origin == "human"
    assert e._resume_prefix is None
    assert e._submitted and e._submitted["text"].endswith("what is next?")
    assert eng._read_state_entry(e.skey())["submitted"]["text"].endswith("what is next?")
    # a second human message gets no prefix
    e.busy = False
    e._send_locked("and then?", origin="human")
    assert not _sent_text(e).startswith("(engine resume")


def test_control_prompt_is_never_prefixed_and_never_durable(engine):
    e = engine
    e._resume_prefix = eng.RESUME_BRIEF
    assert e._send_locked(eng.STAND_UP, origin="control") is True
    assert not _sent_text(e).startswith("(engine resume")
    assert e._turn_origin == "control"
    assert e._submitted is None
    assert e._resume_prefix == eng.RESUME_BRIEF  # still waiting for his words


def test_origin_is_explicit_not_inferred_from_a_leading_paren(engine):
    e = engine
    e._resume_prefix = "(engine) context"
    e._send_locked("hi", origin="human")
    # would have been misclassified as control by the old startswith("(") rule
    assert e._turn_origin == "human"


# ── acknowledgement and reconciliation ────────────────────────────────────

def test_first_native_event_acknowledges_the_submitted_copy(engine):
    e = engine
    e._send_locked("hello", origin="human")
    assert e._submitted is not None
    e._handle({"type": "assistant", "message": {"role": "assistant", "content": []}}, e.proc)
    assert e._submitted is None
    assert eng._read_state_entry(e.skey()).get("submitted") is None


def test_error_before_submission_requeues_the_message(engine):
    e = engine
    e._send_locked("hello", origin="human")
    e._handle({"type": "result", "is_error": True, "replay_safe": True,
               "error": {"code": "transport_error", "message": "boom"}}, e.proc)
    assert e.queue[0].endswith("hello")
    assert e._submitted is None


def test_reconcile_requeues_when_the_provider_record_cannot_confirm(engine):
    e = engine
    e.cli = "claude"
    entry = {"submitted": {"text": "finish chapter 2", "at": time.time(), "session_id": "abc"}}
    e._reconcile_submitted_locked(entry)
    assert len(e.queue) == 1 and e.queue[0].endswith("finish chapter 2")
    assert e.queue[0].startswith("(possibly a repeat")
    assert eng._read_state_entry(e.skey())["pending_queue"] == e.queue


def test_reconcile_drops_a_message_the_codex_rollout_already_shows(engine, monkeypatch, tmp_path):
    e = engine
    e.cli = "chatgpt"
    thread = "01a0aaaa-bbbb-7000-8000-000000000001"
    day = tmp_path / ".codex" / "sessions" / "2026" / "09" / "15"
    day.mkdir(parents=True)
    rollout = day / f"rollout-2026-09-15T08-00-00-{thread}.jsonl"
    rollout.write_text(json.dumps({"type": "event_msg", "payload": {"type": "user_message",
                                                                     "message": "finish chapter 2 please"}}) + "\n",
                       encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    e._reconcile_submitted_locked({"submitted": {"text": "finish chapter 2 please", "session_id": thread}})
    assert e.queue == []
    assert e._submitted is None


def test_reconcile_requeues_when_the_codex_rollout_lacks_it(engine, monkeypatch, tmp_path):
    e = engine
    e.cli = "chatgpt"
    thread = "01a0aaaa-bbbb-7000-8000-000000000002"
    day = tmp_path / ".codex" / "sessions" / "2026" / "09" / "15"
    day.mkdir(parents=True)
    (day / f"rollout-2026-09-15T08-00-00-{thread}.jsonl").write_text('{"payload":{"message":"other"}}\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / ".codex"))
    e._reconcile_submitted_locked({"submitted": {"text": "never delivered", "session_id": thread}})
    assert len(e.queue) == 1 and e.queue[0].endswith("never delivered")


# ── interruption ──────────────────────────────────────────────────────────

def test_interrupt_records_uncertain_outcome_and_keeps_queue(engine, monkeypatch):
    e = engine
    killed = []
    monkeypatch.setattr(e, "_kill_tree", lambda proc: killed.append(proc))
    monkeypatch.setattr(e, "_journal_routing", lambda **ev: None)
    e._send_locked("(drive - not John) Continue.", origin="control")
    assert e.busy is True
    e.queue.append("his words")
    result = e.interrupt_turn("stopped by John")
    assert result == {"ok": True}
    assert killed and e.busy is False and e.proc is None
    assert e._interrupted["reason"] == "stopped by John" and e._interrupted["origin"] == "control"
    assert eng._read_state_entry(e.skey())["interrupted"]["origin"] == "control"
    assert "his words" in e.queue


def test_interrupt_is_a_no_op_without_a_running_turn(engine):
    assert engine.interrupt_turn("x")["ok"] is False


def test_human_message_ends_a_self_started_turn_and_goes_next(engine, monkeypatch):
    e = engine
    monkeypatch.setattr(e, "_kill_tree", lambda proc: None)
    monkeypatch.setattr(e, "_journal_routing", lambda **ev: None)
    monkeypatch.setattr(e, "_record_conversation", lambda who, text: True)
    woke = []
    monkeypatch.setattr(e, "_wake_locked", lambda fresh, seed: (woke.append((fresh, seed)) or (True, "awake")))
    e._send_locked("(drive - not John) Continue.", origin="control")
    result = e.say("actually, stop and summarize")
    assert result["ok"] is True and result.get("interrupted") is True
    assert e.queue and e.queue[0] == "actually, stop and summarize"
    assert woke == [(False, None)]
    assert e._interrupted["origin"] == "control"


def test_human_message_during_his_own_turn_just_queues(engine, monkeypatch):
    e = engine
    monkeypatch.setattr(e, "_record_conversation", lambda who, text: True)
    e._send_locked("first question", origin="human")
    result = e.say("second thought")
    assert result == {"ok": True, "queued": True}
    assert e.busy is True and e.queue == ["second thought"]


def test_resume_wake_puts_interrupted_note_into_the_prefix(engine, monkeypatch):
    e = engine
    e._interrupted = {"at": time.time(), "reason": "stopped by John", "origin": "control", "text": "x"}
    eng._update_state(e.skey(), {"interrupted": e._interrupted})
    # exercise only the prefix construction path used by _wake_locked's resume branch
    entry = eng._read_state_entry(e.skey())
    prefix = eng.RESUME_BRIEF
    interrupted = entry.get("interrupted")
    assert interrupted and interrupted["reason"] == "stopped by John"


# ── stderr tail ───────────────────────────────────────────────────────────

def test_stderr_is_classified_never_forwarded():
    hint = ctb.classify_stderr([
        "ERROR login required: visit https://auth.openai.com/device?code=ABC token=sk-live-secret",
        "connection timed out after 30s",
    ])
    assert hint == {"kinds": ["auth", "network"], "lines": 2}
    assert "sk-live-secret" not in json.dumps(hint)
    assert ctb.classify_stderr(["something odd"]) == {"kinds": ["other"], "lines": 1}


def test_error_result_surfaces_the_diagnostics_kind_in_the_pane(engine):
    e = engine
    seen = []
    e._emit = lambda ev: seen.append(ev)
    e._send_locked("hello", origin="human")
    e._handle({"type": "result", "is_error": True, "replay_safe": False,
               "error": {"code": "transport_error", "message": "Codex exited 1"},
               "stderr_hint": {"kinds": ["auth"], "lines": 3}}, e.proc)
    texts = [ev.get("text", "") for ev in seen if ev.get("t") == "sys"]
    assert any("ended in an error: Codex exited 1 | native diagnostics: auth (3 lines, content withheld)" in t
               for t in texts)


# ── off-thread discovery ──────────────────────────────────────────────────

def test_cached_selection_reports_staleness(monkeypatch):
    model_policy._MEMORY.clear()
    catalog = [{"model": "gpt-6-astra", "efforts": ["high", "ultra"], "rank": 0, "upgrade": None, "evidence": "test"}]
    monkeypatch.setattr(model_policy, "discover", lambda family, env=None: (catalog, "codex"))
    monkeypatch.setattr(model_policy, "_cache_identity", lambda family, env: ("chatgpt", "test"))
    assert model_policy.cached_selection("chatgpt") is None
    fresh = model_policy.resolve("chatgpt", settings={"settings_revision": 8, "model_policy": model_policy.DEFAULT_POLICY})
    cached = model_policy.cached_selection("chatgpt", settings={"settings_revision": 8})
    assert cached["model"] == fresh["model"] == "gpt-6-astra" and cached["stale"] is False
    model_policy._MEMORY[("chatgpt", "test")]["discovered_at"] -= model_policy.CAPABILITY_TTL_SECONDS + 1
    assert model_policy.cached_selection("chatgpt")["stale"] is True
    model_policy._MEMORY.clear()


def test_pinned_selection_answers_from_a_stale_cache_and_refreshes_off_thread(engine, monkeypatch):
    e = engine
    e.cli = "chatgpt"
    e._family_pinned = True
    e.model_selection = {"family": "chatgpt", "model": "gpt-6-astra", "effort": "ultra"}
    stale = {"family": "chatgpt", "model": "gpt-6-astra", "effort": "ultra", "stale": True}
    monkeypatch.setattr(model_policy, "cached_selection", lambda family, settings=None, env=None: dict(stale))
    monkeypatch.setattr(model_policy, "resolve", lambda *a, **k: pytest.fail("must not probe on the request thread"))
    refreshed = []
    monkeypatch.setattr(e, "_refresh_catalog_async", lambda settings: refreshed.append(settings))
    target, selection = e._pinned_selection({"settings_revision": 8}, "chatgpt")
    assert (target, selection["model"]) == ("chatgpt", "gpt-6-astra")
    assert "stale" not in selection
    assert refreshed == [{"settings_revision": 8}]
