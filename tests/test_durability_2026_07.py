"""Anchor durability (2026-07 review) — Wave 1: re-launchable job specs.

An ``interrupted`` job must be re-launchable in ONE call from its durable
record: ``launch()`` persists a complete ``relaunch_spec`` on the job record
(seam env seeds only — never the full environment; ``project_id`` /
``folder_path`` carried per the approved 2026-07-02 amendment), and
``relaunch(job_id)`` starts an equivalent job from disk state alone THROUGH
``launch_guarded()`` — the concurrency policy and project-metadata propagation
apply to a relaunch exactly as to a first launch — linking the two records both
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
        # A direct (unguarded) launch has no policy context to persist.
        "project_id": None,
        "folder_path": None,
    }


def test_guarded_launch_spec_carries_project_metadata(runner, tmp_path):
    """A launch_guarded() job's spec carries the policy context (amendment)."""
    folder = tmp_path / "guardproj"
    folder.mkdir()
    rec = runner.launch_guarded(
        "research", project_id="proj-1", folder_path=folder,
        cwd=str(folder), env={"FAKE_CLAUDE_LINES": "1"},
        backend="claude", prompt="guarded seed",
    )
    runner.wait(rec["job_id"], timeout=30)

    spec = runner.load_record(rec["job_id"])["relaunch_spec"]
    assert spec["project_id"] == "proj-1"
    assert spec["folder_path"] == str(folder)
    assert spec["lane"] == "research"
    assert spec["prompt"] == "guarded seed"


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


def test_relaunch_propagates_project_metadata_via_launch_guarded(runner, tmp_path):
    """Amendment: a relaunch re-drives launch_guarded with the spec's policy
    context, so the NEW record is stamped project_id/folder_path exactly like a
    first guarded launch (and its own spec carries them forward)."""
    folder = tmp_path / "metaproj"
    folder.mkdir()
    rec = runner.launch_guarded(
        "research", project_id="proj-meta", folder_path=folder,
        cwd=str(folder), env={"FAKE_CLAUDE_LINES": "2"}, prompt="carry meta")
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    runner._update_record(jid, status=runner.STATUS_INTERRUPTED)

    out = runner.relaunch(jid)
    assert out["ok"] is True
    new_id = out["job_id"]
    final = runner.wait(new_id, timeout=30)
    assert final["status"] == runner.STATUS_DONE
    # Project metadata propagated onto the new record (launch_guarded stamp)…
    new_rec = runner.load_record(new_id)
    assert new_rec["project_id"] == "proj-meta"
    assert new_rec["folder_path"] == str(folder)
    # …and into the new record's own spec, so a relaunch-of-a-relaunch works.
    assert new_rec["relaunch_spec"]["project_id"] == "proj-meta"
    assert new_rec["relaunch_spec"]["folder_path"] == str(folder)


def test_relaunch_applies_concurrency_policy_same_lane_busy(runner, tmp_path):
    """Amendment: the same-lane serialization refuses a relaunch exactly as it
    would a first launch — as an honest string reason, never an exception."""
    folder = tmp_path / "busyproj"
    folder.mkdir()
    rec = runner.launch_guarded(
        "research", project_id="proj-busy", folder_path=folder,
        cwd=str(folder), env={"FAKE_CLAUDE_LINES": "1"})
    jid = rec["job_id"]
    runner.wait(jid, timeout=30)
    runner._update_record(jid, status=runner.STATUS_INTERRUPTED)

    # Occupy the (project, lane) slot with a live job.
    holder = runner.launch_guarded(
        "research", project_id="proj-busy", folder_path=folder,
        cwd=str(folder),
        env={"FAKE_CLAUDE_LINES": "1", "FAKE_CLAUDE_SLEEP": "5"})
    try:
        out = runner.relaunch(jid)
        assert out["ok"] is False
        assert out["reason"] == runner.REFUSED_SAME_LANE
        assert out["holder"] == holder["job_id"]
        # The refused relaunch minted nothing and linked nothing.
        assert "relaunched_as" not in runner.load_record(jid)
    finally:
        runner.cancel(holder["job_id"])


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
