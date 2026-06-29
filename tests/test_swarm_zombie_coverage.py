"""zombie-hunter v2 — swarm-job session coverage (DESIGN.md gap closure).

Locks the functional fix for the known coverage gap: ``job_runner`` swarm jobs
historically wrote their identity (pid / proc_create_time / crypt_token) ONLY to
the job store, so ``zombie_hunter.sweep`` — which reads
``session_registry.load_sessions()`` — could not see them. The fix registers a
RUNNING ``session_registry`` record (lane ``"swarm"``) at spawn carrying that
same identity, and clears it out of RUNNING when the job exits (the gandalf
finally-reset analog).

Asserts, end-to-end through the real ``job_runner.launch`` (driven by the mock
runner, never live ``claude``):

  1. a launched swarm job registers a session with the EXACT identity the
     hunter's ``classify`` requires (lane=swarm, RUNNING, pid, proc_create_time,
     crypt_token);
  2. on completion the session is mirrored OUT of RUNNING (done / failed);
  3. a cancel mirrors the session to cancelled;
  4. the hunter's ``sweep`` reaps a registered-but-orphaned swarm session
     (verdict kill → killer called once on the right pid → record → idle);
  5. the hunter ABSTAINS on a swarm session whose identity is missing — it
     NEVER kills the wrong thing.

Hermetic: a temp ``ANCHOR_DATA_DIR`` so it never touches the live ``.anchor``
store or any real process beyond the deterministic mock. Stdlib + pytest only.
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


# ── Fakes (no real process needed for the pure classify/sweep path) ──────────

class FakeProbe:
    """Stand-in for ``proc_probe``: pid -> creation_time lookup."""

    def __init__(self, times=None):
        self.times = dict(times or {})

    def creation_time(self, pid):
        return self.times.get(pid)


class FakeKiller:
    """Records every ``killer(pid)`` call; reports success."""

    def __init__(self, ok=True):
        self.calls = []
        self.ok = ok

    def __call__(self, pid):
        self.calls.append(pid)
        return self.ok


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A temp ANCHOR_DATA_DIR + mock runner; reload the stack in dependency order."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import job_runner
    importlib.reload(job_runner)
    import zombie_hunter
    importlib.reload(zombie_hunter)
    yield {"jr": job_runner, "reg": session_registry, "zh": zombie_hunter}
    job_runner._reset_live_table_for_tests()


# ── 1. spawn registers a sweepable session with the hunter's identity ────────

def test_swarm_launch_registers_session_with_identity(env):
    jr, reg = env["jr"], env["reg"]
    # Keep the job alive briefly so the session is observably RUNNING at spawn.
    rec = jr.launch("build", extra_args=["--lines", "1", "--sleep", "1.0"])
    jid = rec["job_id"]

    sess = reg.get_session(jid)
    assert sess is not None, "swarm job did not register a session"
    assert sess["lane"] == jr.SWARM_LANE == "swarm"
    assert sess["status"] == reg.STATUS_RUNNING
    # The EXACT identity fields the hunter's classify needs, equal to the job's.
    assert sess["pid"] == rec["pid"]
    assert sess["crypt_token"] == rec["crypt_token"]
    assert sess["crypt_token"]  # non-empty
    assert sess["proc_create_time"] == rec["proc_create_time"]

    jr.wait(jid, timeout=30)


# ── 2. completion mirrors the session out of RUNNING (finally-reset) ─────────

def test_swarm_completion_clears_running(env):
    jr, reg = env["jr"], env["reg"]
    rec = jr.launch("research", extra_args=["--lines", "2", "--exit-code", "0"])
    jid = rec["job_id"]
    jr.wait(jid, timeout=30)
    assert reg.get_session(jid)["status"] == reg.STATUS_DONE


def test_swarm_failure_mirrors_failed(env):
    jr, reg = env["jr"], env["reg"]
    rec = jr.launch("plan", extra_args=["--lines", "1", "--exit-code", "5"])
    jid = rec["job_id"]
    jr.wait(jid, timeout=30)
    assert reg.get_session(jid)["status"] == reg.STATUS_FAILED


# ── 3. cancel mirrors the session to cancelled ───────────────────────────────

def test_swarm_cancel_mirrors_cancelled(env):
    jr, reg = env["jr"], env["reg"]
    rec = jr.launch("build", extra_args=["--lines", "1", "--sleep", "5.0"])
    jid = rec["job_id"]
    jr.cancel(jid)
    assert reg.get_session(jid)["status"] == reg.STATUS_CANCELLED


# ── 4. the hunter reaps a registered-but-orphaned swarm session ──────────────

def test_hunter_reaps_orphaned_swarm_session(env):
    reg, zh = env["reg"], env["zh"]
    # Simulate a swarm child orphaned by a server crash: a RUNNING swarm session
    # whose process is still alive (identity matches) but is NOT attached.
    reg.register_session(
        "", "swarm", status=reg.STATUS_RUNNING,
        session_id="orphan", pid=4242, proc_create_time=1234.0,
        crypt_token="tok")
    probe = FakeProbe({4242: 1234.0})  # alive, creation-time matches → ours
    killer = FakeKiller()

    report = zh.sweep(set(), probe=probe, killer=killer, apply=True)

    assert killer.calls == [4242]              # killed exactly the orphan's pid
    assert report["killed"] == ["orphan"]
    assert reg.get_session("orphan")["status"] == reg.STATUS_IDLE  # reaped


# ── 5. the hunter ABSTAINS on a swarm session with missing identity ──────────

def test_hunter_abstains_on_swarm_session_missing_identity(env):
    reg, zh = env["reg"], env["zh"]
    # A swarm session whose crypt_token never got stamped → unidentifiable.
    reg.register_session(
        "", "swarm", status=reg.STATUS_RUNNING, session_id="noid",
        pid=4243, proc_create_time=1234.0, crypt_token="")
    probe = FakeProbe({4243: 1234.0})
    killer = FakeKiller()

    report = zh.sweep(set(), probe=probe, killer=killer, apply=True)

    assert killer.calls == []                    # NEVER kills the wrong thing
    assert report["abstained"] == ["noid"]
    assert reg.get_session("noid")["status"] == reg.STATUS_RUNNING  # untouched
