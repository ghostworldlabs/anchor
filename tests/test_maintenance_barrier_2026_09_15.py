"""codex-discipline-2026-09-15 Wave 1.6 — the service-wide maintenance barrier
(hermetic: injected probes, fast poll, tmp state)."""
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from steward_cockpit import maintenance as mt  # noqa: E402
from steward_cockpit import steward_engine as eng  # noqa: E402
from steward_cockpit import steward_routes as routes  # noqa: E402


@pytest.fixture(autouse=True)
def tmp_state(monkeypatch, tmp_path):
    monkeypatch.setattr(mt, "STATE_FILE", tmp_path / "maintenance-state.json")
    mt.cancel("test reset")
    yield
    mt.cancel("test reset")


def _wait_until(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_barrier_waits_for_turns_and_jobs_then_restarts_once():
    busy = {"engines": ["C:/x/Book 1"], "jobs": ["job-1"]}
    restarts = []
    state = mt.begin("activate wave 1", busy_engines=lambda: list(busy["engines"]),
                     running_jobs=lambda: list(busy["jobs"]),
                     restart=lambda reason: restarts.append(reason), poll_seconds=0.02)
    assert state["active"] is True and mt.is_active()
    assert _wait_until(lambda: mt.status().get("checks", 0) >= 2)
    assert restarts == []
    assert set(mt.status()["waiting_on"]) == {"steward:C:/x/Book 1", "job:job-1"}
    # a second begin while the watcher is alive is idempotent
    again = mt.begin("again", busy_engines=lambda: [], running_jobs=lambda: [],
                     restart=lambda r: restarts.append(r), poll_seconds=0.02)
    assert again["reason"] == "activate wave 1"
    busy["engines"].clear()
    assert _wait_until(lambda: mt.status().get("checks", 0) >= 4)
    assert restarts == []  # the job still holds it
    busy["jobs"].clear()
    assert _wait_until(lambda: restarts == ["activate wave 1"])
    assert mt.status()["restart_called"] is True


def test_barrier_gives_up_visibly_after_max_wait():
    state = mt.begin("never drains", busy_engines=lambda: ["stuck"], running_jobs=lambda: [],
                     restart=lambda r: pytest.fail("must not restart while busy"),
                     poll_seconds=0.02, max_wait=0.1)
    assert state["active"] is True
    assert _wait_until(lambda: not mt.is_active())
    assert "max wait" in mt.status()["cleared_reason"]


def test_cancel_and_boot_clear():
    mt.begin("x", busy_engines=lambda: ["b"], running_jobs=lambda: [],
             restart=lambda r: None, poll_seconds=0.02)
    assert mt.is_active()
    mt.cancel("operator")
    assert not mt.is_active() and mt.status()["cleared_reason"] == "operator"
    mt.begin("y", busy_engines=lambda: ["b"], running_jobs=lambda: [],
             restart=lambda r: None, poll_seconds=0.02)
    mt.boot_clear()
    assert not mt.is_active() and mt.status()["cleared_reason"] == "fresh boot"


def test_probe_failure_never_counts_as_drained():
    restarts = []

    def broken():
        raise RuntimeError("registry unreadable")
    mt.begin("z", busy_engines=broken, running_jobs=lambda: [],
             restart=lambda r: restarts.append(r), poll_seconds=0.02)
    assert _wait_until(lambda: mt.status().get("checks", 0) >= 2)
    assert restarts == []
    assert mt.status()["waiting_on"] == ["probe-error:RuntimeError"]


# ── engine behaviour behind the barrier ───────────────────────────────────

@pytest.fixture
def engine(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="steward-barrier-")
    monkeypatch.setattr(eng, "STATE_FILE", Path(tmp) / "state.json")
    return eng.Engine(tmp, fake=True)


def test_wake_is_refused_behind_the_barrier(engine, monkeypatch):
    monkeypatch.setattr(mt, "is_active", lambda: True)
    monkeypatch.setattr(engine, "_wake_locked", lambda *a, **k: pytest.fail("must not spawn"))
    ok, why = engine.wake()
    assert ok is False and why == "maintenance in progress"


def test_say_queues_durably_behind_the_barrier(engine, monkeypatch):
    monkeypatch.setattr(mt, "is_active", lambda: True)
    monkeypatch.setattr(engine, "_record_conversation", lambda who, text: True)
    result = engine.say("keep this for after the restart")
    assert result == {"ok": True, "queued": True, "maintenance": True}
    assert engine.queue == ["keep this for after the restart"]
    assert eng._read_state_entry(engine.skey())["pending_queue"] == engine.queue


def test_maintenance_route_status_begin_and_cancel(monkeypatch):
    status, code = routes.maintenance_post({"op": "status"})
    assert code == 200 and status["ok"] is True and status["active"] is False
    refused, code = routes.maintenance_post({"op": "begin", "reason": "test"})
    assert code == 409 and refused["error"] == "not_supervised"
    restarted = []
    monkeypatch.setattr(routes, "_restart_for_activation", lambda reason: restarted.append(reason))
    monkeypatch.setattr(routes, "_busy_engine_keys", lambda: [])
    monkeypatch.setattr(routes, "_running_job_ids", lambda: [])
    monkeypatch.setattr(mt, "POLL_SECONDS", 0.02)
    began, code = routes.maintenance_post({"op": "begin", "reason": "test", "force": True})
    assert code == 200 and began["active"] is True
    assert _wait_until(lambda: restarted == ["test"])
    cancelled, code = routes.maintenance_post({"op": "cancel"})
    assert code == 200 and cancelled["active"] is False


def test_begin_rearms_a_dead_watcher():
    mt.begin("first", busy_engines=lambda: ["b"], running_jobs=lambda: [], restart=lambda r: None, poll_seconds=0.02)
    gen = mt.status()["generation"]
    mt._THREAD = None  # simulate a watcher that died
    again = mt.begin("second", busy_engines=lambda: ["b"], running_jobs=lambda: [], restart=lambda r: None, poll_seconds=0.02)
    assert again["generation"] == gen + 1 and again["reason"] == "second"


def test_no_job_of_any_kind_launches_behind_the_barrier(monkeypatch):
    import job_runner as jr
    monkeypatch.setattr(mt, "is_active", lambda: True)
    with pytest.raises(ValueError, match="maintenance-barrier"):
        jr.launch("research", command=[sys.executable, "-c", "pass"])
    with pytest.raises(ValueError, match="maintenance-barrier"):
        jr.launch("research", backend="claude", prompt="x")
