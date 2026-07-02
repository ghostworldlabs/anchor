"""Anchor durability (2026-07 review) — Wave 1: re-launchable job specs.

An ``interrupted`` job must be re-launchable in ONE call from its durable
record: ``launch()`` persists a complete ``relaunch_spec`` on the job record
(seam env seeds only — never the full environment), and ``relaunch(job_id)``
starts an equivalent job from disk state alone, linking the two records both
ways. ``reconcile_on_startup()`` still only RECONCILES — it never auto-relaunches.

Hermetic: temp ``ANCHOR_DATA_DIR``, ``ANCHOR_RUNNER_CMD`` → the deterministic
``tests/fake_claude.py`` mock — never real claude / node / port 8777.
"""
import importlib
import sys
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    # Point the indirection at the deterministic mock — never live claude.
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {FAKE}")
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    yield job_runner
    job_runner._reset_live_table_for_tests()


# ── AC1: the record carries a complete relaunch_spec ─────────────────────────

def test_launch_persists_complete_relaunch_spec_field_by_field(runner, tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    outdir = tmp_path / "out"
    outdir.mkdir()
    rec = runner.launch(
        "research",
        cwd=str(proj),
        env={"FAKE_CLAUDE_LINES": "1", "SECRET_TOKEN": "hush"},
        backend="claude",
        prompt="seed prompt",
        output_dir=str(outdir),
        gated=False,
        permission_mode="plan",
    )
    runner.wait(rec["job_id"], timeout=30)

    persisted = runner.load_record(rec["job_id"])
    spec = persisted.get("relaunch_spec")
    # Complete, field by field, against the launch args — and ONLY the seam
    # env seed is kept (the secret never reaches the durable record).
    assert spec == {
        "lane": "research",
        "cwd": str(proj),
        "prompt": "seed prompt",
        "output_dir": str(outdir),
        "gated": False,
        "permission_mode": "plan",
        "backend": "claude",
        "env_keys": {"FAKE_CLAUDE_LINES": "1"},
    }


def test_relaunch_spec_env_seed_keeps_only_runner_seam_vars(runner):
    seed = runner._relaunch_env_seed({
        "ANCHOR_RUNNER_CMD": "python fake.py",
        "STUB_THING": "1",
        "FAKE_CLAUDE_LINES": "2",
        "ANCHOR_GANDALF_HOST_CMD": "python host.py",
        "AWS_SECRET_ACCESS_KEY": "nope",
        "PATH": "C:/bin",
    })
    assert seed == {
        "ANCHOR_RUNNER_CMD": "python fake.py",
        "STUB_THING": "1",
        "FAKE_CLAUDE_LINES": "2",
        "ANCHOR_GANDALF_HOST_CMD": "python host.py",
    }


# ── AC2: relaunch() on an interrupted record runs to DONE with links ─────────

def test_relaunch_interrupted_runs_to_done_and_links_both_ways(runner):
    rec = runner.launch("research", env={"FAKE_CLAUDE_LINES": "4"},
                        prompt="carry on")
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    # Simulate a restart-orphaned job (the reconcile outcome).
    runner._update_record(jid, status=runner.STATUS_INTERRUPTED)

    out = runner.relaunch(jid)
    assert out["ok"] is True
    new_id = out["job_id"]
    assert new_id != jid
    assert out["relaunch_of"] == jid

    final = runner.wait(new_id, timeout=30)
    assert final["status"] == runner.STATUS_DONE
    # The seam env seed drove the stub: the relaunched job replayed the spec.
    assert runner._lines_from_log(new_id) == [f"fake-line {i}" for i in range(4)]
    # Links persisted both ways on disk.
    assert runner.load_record(jid)["relaunched_as"] == new_id
    assert runner.load_record(new_id)["relaunch_of"] == jid


# ── AC3: honest refusals ─────────────────────────────────────────────────────

def test_relaunch_refuses_running_then_cancelled(runner):
    rec = runner.launch("research",
                        env={"FAKE_CLAUDE_LINES": "1", "FAKE_CLAUDE_SLEEP": "5"})
    jid = rec["job_id"]
    out = runner.relaunch(jid)
    assert out["ok"] is False
    assert isinstance(out["reason"], str)
    assert out["reason"].startswith(runner.RELAUNCH_REASON_NOT_INTERRUPTED)
    assert runner.STATUS_RUNNING in out["reason"]

    runner.cancel(jid)
    out = runner.relaunch(jid)
    assert out["ok"] is False
    assert runner.STATUS_CANCELLED in out["reason"]


def test_relaunch_refuses_done(runner):
    rec = runner.launch("research", env={"FAKE_CLAUDE_LINES": "1"})
    runner.wait(rec["job_id"], timeout=30)
    out = runner.relaunch(rec["job_id"])
    assert out["ok"] is False
    assert runner.STATUS_DONE in out["reason"]


def test_relaunch_refuses_unknown_id(runner):
    out = runner.relaunch("no-such-job")
    assert out == {"ok": False, "reason": runner.RELAUNCH_REASON_UNKNOWN}


def test_relaunch_refuses_legacy_record_without_spec(runner):
    runner._write_record({"job_id": "legacy-1",
                          "status": runner.STATUS_INTERRUPTED})
    out = runner.relaunch("legacy-1")
    assert out == {"ok": False, "reason": "no-relaunch-spec"}


# ── reconcile_on_startup: unchanged contract, no auto-relaunch ───────────────

def test_reconcile_returns_ids_and_never_auto_relaunches(runner):
    rec = runner.launch("research", env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    # Rewind the record to "running" with the (now-dead) pid — the restart shape.
    runner._update_record(jid, status=runner.STATUS_RUNNING)

    changed = runner.reconcile_on_startup()
    assert changed == [jid]
    assert runner.load_record(jid)["status"] == runner.STATUS_INTERRUPTED
    # No auto-relaunch: no new job record appeared, and nothing links back.
    records = runner.list_records()
    assert len(records) == 1
    assert all("relaunch_of" not in r for r in records)
