"""The conversation -> commission JOIN (steward run-loop W5, 2026-08-06).

commission_session.py is the one place the existing seams meet:
propose -> confirm -> managed session -> run loop -> run record -> ingest
bridge (report + raise) -> hand-back re-arm. These tests drive the join with
every external seam stubbed: the Node bridge via ANCHOR_ECGBERHT_BRIDGE_CMD
(fake_ecgberht_bridge.py — NEVER real Node / a seat call), the session via an
injected start_session_fn, and the PTY via injected read/write fns.

The laws under test are the effort's hard-won ones:
  - the steward NEVER answers the skill's question (write_fn sees only the
    work turn + Enter, nothing after ASKED)
  - a run that stopped is brought home: durable record + ingest call
  - hand-back re-arms WITHOUT sending anything, past the old question
  - a skill with no session lane is refused by name, never half-launched
"""
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import commission_runner as cr
import commission_session as cs


# ── Harness ─────────────────────────────────────────────────────────────────

class InlineThread:
    """A 'thread' that runs the target synchronously on start().

    The watcher normally rides a daemon thread of the service; tests want the
    whole join to finish before asserting, so start() just calls the fn.
    """

    def __init__(self, fn):
        self._fn = fn
        self.daemon = True

    def start(self):
        self._fn()

    def is_alive(self):
        return False


def inline_thread_factory(fn):
    return InlineThread(fn)


class ScriptedPty:
    """read_fn/write_fn pair scripted like a real commissioned session."""

    def __init__(self, chunks, status="running"):
        # chunks: list of strings appended to the stream one poll at a time.
        self.chunks = list(chunks)
        self.stream = ""
        self.status = status
        self.writes = []

    def read_fn(self, session_id, cursor):
        if self.chunks:
            self.stream += self.chunks.pop(0)
        return {"text": self.stream[cursor:], "next": len(self.stream),
                "status": self.status}

    def write_fn(self, session_id, data):
        self.writes.append(data)


def fast_runner_kwargs():
    return {
        "poll_seconds": 0,
        "max_seconds": 30,
        "quiet_seconds": 5,
        "sleep_fn": lambda s: None,
    }


@pytest.fixture()
def bridge_env(tmp_path, monkeypatch):
    """Route commission_session's bridge at the python stub, recording calls."""
    stub = Path(__file__).resolve().parent / "fake_ecgberht_bridge.py"
    rec = tmp_path / "bridge-rec"
    monkeypatch.setenv("ANCHOR_ECGBERHT_BRIDGE_CMD",
                       f'"{sys.executable}" "{stub}"')
    monkeypatch.setenv("FAKE_BRIDGE_DIR", str(rec))
    return rec


def bridge_calls(rec_dir):
    f = Path(rec_dir) / "calls.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]


def fake_start_session(project_id, lane, backend="claude", label="",
                       seed_context=None, lean_worktree=True, **_kw):
    return {
        "session_id": "sess-t1",
        "pid": 4242,
        "proc_create_time": 123.456,
        "backend": backend,
        "command": ["claude"],
        "worktree_path": "C:/wt/sess-t1",
        "seed_context": seed_context,
        "lane": lane,
    }


PROPOSAL = {
    "kind": "commission_proposal",
    "requires_confirm": True,
    "proposal_id": "prop-1",
    "step_id": "s1",
    "skill": "Crucible",
    "step": {"name": "Order the syllabus decisions", "done_when": "locked"},
}


# ── Propose ─────────────────────────────────────────────────────────────────

def test_propose_crosses_the_bridge_on_stdin(tmp_path, bridge_env):
    out = cs.propose(str(tmp_path), step_id="s1")
    assert out["ok"] is True
    assert out["requires_confirm"] is True
    calls = bridge_calls(bridge_env)
    assert calls[0]["mode"] == "propose-active"
    assert calls[0]["payload"]["project"] == str(tmp_path)
    assert calls[0]["payload"]["step_id"] == "s1"


# ── The join: confirm -> launch -> drive -> record -> ingest ────────────────

def test_confirm_and_launch_drives_to_asked_and_brings_it_home(tmp_path, bridge_env):
    pty = ScriptedPty([
        "\u2713 Crucible loaded \u2014 what would you like to do?",
        "",  # runner sends the work turn here
        "Reading the project\u2026 ",
        "Here are 8 ordered decisions. Which of the three revamp options "
        "do you want as the North Star? I will stop here until you decide.",
    ])

    out = cs.confirm_and_launch(
        str(tmp_path), PROPOSAL,
        project_id="proj-1",
        start_session_fn=fake_start_session,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is True, out
    assert out["session_id"] == "sess-t1"
    assert out["lane"] == "plan"
    assert out["watching"] is True

    # The work turn went in as TYPE then ENTER, and NOTHING after the question
    # — the steward never answers on John's behalf.
    assert len(pty.writes) == 2
    assert pty.writes[0].startswith("Begin the commissioned work now")
    assert pty.writes[1] == "\r"

    # Durable run record: outcome asked, report from the ingest bridge.
    rec = cs.load_run_record(str(tmp_path), "sess-t1")
    assert rec["outcome"] == "asked"
    assert rec["ran"] is True
    assert rec["skill"] == "Crucible"
    assert rec["watch_count"] == 1
    assert "North Star" in rec["transcript_tail"]
    assert rec["report"]["needs"] == "Which option?"
    assert rec["raised"] is True

    # The seam saw confirm THEN ingest-run, with the transcript riding stdin.
    modes = [c["mode"] for c in bridge_calls(bridge_env)]
    assert modes == ["confirm", "ingest-run"]
    ingest = bridge_calls(bridge_env)[1]["payload"]
    assert ingest["run"]["outcome"] == "asked"
    assert "North Star" in ingest["run"]["transcript"]
    assert ingest["run"]["session_id"] == "sess-t1"


def test_skill_without_a_session_lane_is_refused_by_name(tmp_path, bridge_env):
    prop = {**PROPOSAL, "skill": "Gandalf"}
    # The stub's confirm echoes the proposal's skill back.
    out = cs.confirm_and_launch(
        str(tmp_path), prop, project_id="p",
        start_session_fn=fake_start_session,
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is False
    assert out["error"] == "skill_has_no_session_lane"
    assert cs.load_run_record(str(tmp_path), "sess-t1") is None, \
        "a refused commission must not leave a run record"


def test_confirm_failure_stops_everything(tmp_path, bridge_env):
    (Path(bridge_env)).mkdir(parents=True, exist_ok=True)
    (Path(bridge_env) / "fail-confirm").write_text("x")
    out = cs.confirm_and_launch(
        str(tmp_path), PROPOSAL, project_id="p",
        start_session_fn=fake_start_session,
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is False
    assert cs.load_run_record(str(tmp_path), "sess-t1") is None


# ── Hand it back: watch-only re-arm ─────────────────────────────────────────

def test_rearm_watch_snaps_past_the_old_question_and_sees_produced(tmp_path, bridge_env):
    # First: a run that stopped at ASKED (record on disk).
    pty = ScriptedPty([
        "greeting", "", "Which option do you want? I will stop here until you answer.",
    ])
    cs.confirm_and_launch(
        str(tmp_path), PROPOSAL, project_id="p",
        start_session_fn=fake_start_session,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    assert cs.load_run_record(str(tmp_path), "sess-t1")["outcome"] == "asked"

    # John answered IN the session; new output continues the same stream.
    pty.chunks = [
        "",  # the snap read — cursor moves past everything already on screen
        "Good \u2014 locking option 2. Working\u2026 ",
        "Wrote MASTER-PLAN.md with 6 stages.",
    ]
    out = cs.rearm_watch(
        str(tmp_path), "p", "sess-t1",
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    assert out["ok"] is True

    rec = cs.load_run_record(str(tmp_path), "sess-t1")
    assert rec["outcome"] == "produced"
    assert rec["watch_count"] == 2
    # The re-armed watch NEVER typed anything into the session.
    assert len(pty.writes) == 2, "watch-only must not write"

    # And the old question was NOT re-classified: the transcript the ingest saw
    # starts after the snap.
    ingest_payloads = [c["payload"] for c in bridge_calls(bridge_env)
                      if c["mode"] == "ingest-run"]
    assert "Which option do you want" not in ingest_payloads[-1]["run"]["transcript"]


def test_rearm_unknown_session_refused(tmp_path, bridge_env):
    out = cs.rearm_watch(str(tmp_path), "p", "nope")
    assert out["ok"] is False
    assert out["error"] == "unknown_run"


# ── watch_only in the runner itself ─────────────────────────────────────────

def test_runner_watch_only_never_writes_and_classifies_new_output_only():
    pty = ScriptedPty([
        "old question? I will stop here until you answer.",
        "new work \u2014 wrote handback.json",
    ])
    result = cr.run_commissioned_session(
        "s", "SHOULD NEVER BE SENT",
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        watch_only=True,
        poll_seconds=0, max_seconds=10, quiet_seconds=5,
        sleep_fn=lambda s: None,
    )
    assert pty.writes == []
    assert result["outcome"] == cr.RUN_PRODUCED
    assert "old question" not in result["transcript"]


def test_runner_watch_only_dead_session_is_died():
    def read_dead(sid, cursor):
        return {"text": "", "next": 0, "status": "dead"}
    result = cr.run_commissioned_session(
        "s", "x", read_fn=read_dead, write_fn=lambda *a: None,
        watch_only=True, poll_seconds=0, max_seconds=5,
        sleep_fn=lambda s: None,
    )
    assert result["outcome"] == cr.RUN_DIED


# ── Listings stay SAFE ──────────────────────────────────────────────────────

def test_list_runs_is_safe_and_newest_first(tmp_path, bridge_env):
    pty = ScriptedPty(["greeting", "", "asked? I will stop here until you answer."])
    cs.confirm_and_launch(
        str(tmp_path), PROPOSAL, project_id="p",
        start_session_fn=fake_start_session,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    rows = cs.list_runs(str(tmp_path))
    assert len(rows) == 1
    row = rows[0]
    assert row["session_id"] == "sess-t1"
    assert row["outcome"] == "asked"
    assert "worktree_path" not in row
    assert "transcript_tail" not in row
    assert row["report"]["say"]


def test_ingest_bridge_failure_is_a_fact_john_gets(tmp_path, bridge_env):
    (Path(bridge_env)).mkdir(parents=True, exist_ok=True)
    (Path(bridge_env) / "fail-ingest-run").write_text("x")
    pty = ScriptedPty(["greeting", "", "asked? I will stop here until you answer."])
    cs.confirm_and_launch(
        str(tmp_path), PROPOSAL, project_id="p",
        start_session_fn=fake_start_session,
        read_fn=pty.read_fn, write_fn=pty.write_fn,
        runner_kwargs=fast_runner_kwargs(),
        thread_factory=inline_thread_factory,
    )
    rec = cs.load_run_record(str(tmp_path), "sess-t1")
    assert rec["outcome"] == "asked"
    assert rec["ingest_error"] == "forced_failure"
    assert "could not read it back" in rec["report"]["say"]
