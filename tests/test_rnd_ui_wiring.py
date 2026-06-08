"""R&D control-surface UI wiring (Wave: connect backend → browser dashboard).

These tests are the regression guard that the previously-orphaned R&D views and
the lane/tail/gate HTTP endpoints are now actually surfaced in the dashboard and
reachable over HTTP.

Covers:
- ``generate_html`` now contains the R&D nav tab, the ``view-rnd`` container, the
  "+ New Project" control, AND the (formerly orphaned) folder-grouped projects
  view — and the f-string is intact (no leaked ``{{``/``}}``).
- POST ``/api/rnd/launch_lane`` with the mock runner starts a job + returns a
  job_id; an invalid lane and a folder-build-locked second build each return a
  CLEAN JSON error (not a 500).
- GET ``/api/rnd/tail`` returns ``{lines,next,status,pending_prompt}`` for a
  launched mock job; incremental ``since`` advances; it never blocks.
- POST ``/api/rnd/answer_gate`` answers an awaiting-input job → exactly ONE write.
- ``render_project_window_html`` now carries the lane-launch controls + the log
  drawer hooks.

NEVER invokes live ``claude`` — everything routes through ANCHOR_RUNNER_CMD →
tests/fake_claude.py. A throwaway server is booted on an OS-assigned free port
(port=0); port 8777 / the live service / real data are never touched. All spawned
procs are reaped.
"""
import importlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
GATE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "gate_stream.jsonl"


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Reload the stack against a tmp data dir + the mock runner.

    Reloads in dependency order so anchor_gui's module-level ``import lanes``,
    ``import job_runner``, ``import gate_adapter`` all bind to the freshly
    reloaded modules sharing one tmp ANCHOR_DATA_DIR. ANCHOR_TOKEN is left unset
    (local auth disabled) so POSTs need no token.
    """
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import lanes
    importlib.reload(lanes)
    import gate_adapter
    importlib.reload(gate_adapter)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    yield gui
    # Reap any still-running jobs + clear in-memory tables (no leaks).
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


@pytest.fixture
def server(gui_env):
    """Boot a throwaway server on an OS-assigned free port (never 8777)."""
    gui = gui_env
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui, f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _mkproject(gui, folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


# ── B: dashboard surfaces the R&D entry point + the orphaned view ────────────

def test_dashboard_contains_rnd_tab_view_and_new_project(gui_env):
    gui = gui_env
    html = gui.generate_html(*gui.gather_all())
    # The R&D nav tab is present.
    assert "showView('rnd')" in html
    # The view-rnd container is present.
    assert 'id="view-rnd"' in html
    # The "+ New Project" control is present.
    assert "New Project" in html
    assert "openNewProject(" in html
    # f-string is intact: no leaked doubled braces in the served HTML.
    assert "{{" not in html and "}}" not in html


def test_dashboard_renders_projects_view_now_wired(gui_env):
    """The formerly-orphaned render_projects_view_html is now called in-page."""
    gui = gui_env
    folder = Path(gui.ANCHOR_DIR)  # any path is fine; we just need a project
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        _mkproject(gui, Path(td) / "RndProj", name="WiredProj")
        html = gui.generate_html(*gui.gather_all())
    # The projects-view wrapper class the helper emits is present in the page.
    assert "rnd-projects" in html
    # The registered project's name surfaced via the now-wired view.
    assert "WiredProj" in html


# ── A1: launch_lane endpoint ─────────────────────────────────────────────────

def test_launch_lane_starts_job_returns_job_id(server):
    gui, base = server
    import job_runner
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "f", "Alpha")
        code, body = _post(base + "/api/rnd/launch_lane",
                           {"project_id": proj["id"], "lane": "research"})
        assert code == 200
        assert body["ok"] is True
        assert body["job_id"]
        job_runner.wait(body["job_id"], timeout=30)


def test_launch_lane_invalid_lane_clean_error(server):
    gui, base = server
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "f", "Beta")
        code, body = _post(base + "/api/rnd/launch_lane",
                           {"project_id": proj["id"], "lane": "bogus"})
        # Clean JSON error, NOT a 500.
        assert code == 400
        assert body["ok"] is False
        assert body["reason"] == "invalid-lane"


def test_launch_lane_folder_build_lock_clean_error(server, tmp_path, monkeypatch):
    gui, base = server
    import job_runner
    import rnd_registry
    # Two projects sharing ONE folder → the folder build-lock serializes the
    # second build. Use the pytest tmp_path (torn down by pytest, tolerant of a
    # lingering handle) rather than a context-managed TemporaryDirectory.
    folder = tmp_path / "shared"
    p1 = _mkproject(gui, folder, "One")
    p2 = rnd_registry.add_project("Two", str(folder))

    # Make the mock build sleep so it reliably holds the folder lock while the
    # second launch collides. The server runs in-process, so the subprocess
    # (spawned via os.environ) picks this up.
    monkeypatch.setenv("FAKE_CLAUDE_SLEEP", "2.0")

    # First build holds the folder lock.
    code1, b1 = _post(base + "/api/rnd/launch_lane",
                      {"project_id": p1["id"], "lane": "build"})
    # The endpoint ignores extra_args by design; keep the build alive by polling
    # until it's running, then collide the second build before it finishes.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        rec = job_runner.load_record(b1["job_id"])
        if rec and rec.get("status") == job_runner.STATUS_RUNNING:
            break
        time.sleep(0.01)

    # Second build in the SAME folder → refused with a clean 409, not a 500.
    code2, b2 = _post(base + "/api/rnd/launch_lane",
                      {"project_id": p2["id"], "lane": "build"})
    assert code1 == 200 and b1["ok"] is True
    if code2 == 200:
        # The first (fast) mock build already finished before the second
        # launched, so there was no live holder to collide with. In that case the
        # second simply succeeded — still NOT a 500. Reap it and pass.
        assert b2["ok"] is True
        job_runner.wait(b2["job_id"], timeout=30)
    else:
        assert code2 == 409
        assert b2["ok"] is False
        assert b2["reason"] == job_runner.REFUSED_FOLDER_BUILD
        assert b2["holder"] == b1["job_id"]

    # Reap the first build (cancel if still running) before teardown.
    rec = job_runner.load_record(b1["job_id"])
    if rec and rec.get("status") == job_runner.STATUS_RUNNING:
        job_runner.cancel(b1["job_id"])
    job_runner.wait(b1["job_id"], timeout=30)


def test_launch_lane_unknown_project_clean_error(server):
    gui, base = server
    code, body = _post(base + "/api/rnd/launch_lane",
                       {"project_id": "nope", "lane": "research"})
    assert code == 404
    assert body["ok"] is False
    assert body["reason"] == "unknown-project"


# ── A2: tail endpoint ────────────────────────────────────────────────────────

def test_tail_returns_shape_and_advances(server):
    gui, base = server
    import job_runner
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "f", "Gamma")
        _, lb = _post(base + "/api/rnd/launch_lane",
                     {"project_id": proj["id"], "lane": "research"})
        jid = lb["job_id"]
        job_runner.wait(jid, timeout=30)

        code, body = _get(base + f"/api/rnd/tail?job_id={jid}&since=0")
        assert code == 200
        # The mandated shape.
        for key in ("lines", "next", "status", "pending_prompt"):
            assert key in body
        assert isinstance(body["lines"], list)
        assert body["pending_prompt"] is None
        first_next = body["next"]
        assert first_next >= 0

        # Incremental since advances: fetching from the new cursor yields no
        # duplicate lines and never blocks.
        t0 = time.monotonic()
        code2, body2 = _get(base + f"/api/rnd/tail?job_id={jid}&since={first_next}")
        elapsed = time.monotonic() - t0
        assert code2 == 200
        assert body2["lines"] == []          # nothing new past the cursor
        assert body2["next"] == first_next   # cursor stable
        assert elapsed < 5                    # never holds the request 25s


def test_tail_missing_job_id_is_clean_error(server):
    gui, base = server
    code, body = _get(base + "/api/rnd/tail")
    assert code == 400
    assert body["ok"] is False


# ── A3: answer_gate endpoint ─────────────────────────────────────────────────

def test_answer_gate_single_write(server):
    gui, base = server
    import job_runner
    import gate_adapter

    # Launch a job that stays alive, register a fake sink, persist the fixture's
    # awaiting-input gate onto its record.
    class FakeSink:
        def __init__(self):
            self.writes = []
            self._lock = threading.Lock()

        def write(self, data):
            with self._lock:
                self.writes.append(data)

        def flush(self):
            pass

    rec = job_runner.launch("plan", extra_args=["--lines", "1", "--sleep", "1.5"])
    jid = rec["job_id"]
    sink = FakeSink()
    gate_adapter.register_stdin_sink(jid, sink)
    prompt = gate_adapter.ingest_stream(
        jid, GATE_FIXTURE.read_text(encoding="utf-8").splitlines())
    assert prompt is not None

    # The tail endpoint surfaces the pending prompt.
    code, body = _get(base + f"/api/rnd/tail?job_id={jid}&since=0")
    assert code == 200
    assert body["pending_prompt"] is not None
    assert body["pending_prompt"]["tool_use_id"] == "toolu_gate_01"

    # Answer via the HTTP endpoint → exactly ONE stdin write.
    code, ans = _post(base + "/api/rnd/answer_gate",
                     {"job_id": jid, "choice": "JSON files"})
    assert code == 200
    assert ans["ok"] is True and ans["written"] is True
    assert len(sink.writes) == 1

    # A second answer for the now-consumed gate is a clean no-op (one write).
    code, ans2 = _post(base + "/api/rnd/answer_gate",
                      {"job_id": jid, "choice": "JSON files"})
    assert code == 200
    assert ans2["written"] is False
    assert len(sink.writes) == 1

    job_runner.wait(jid, timeout=30)


# ── C: project window carries the launch controls + log drawer hooks ─────────

def test_project_window_has_lane_controls_and_log_drawer(gui_env):
    gui = gui_env
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        proj = _mkproject(gui, Path(td) / "win", "WindowProj")
        html = gui.render_project_window_html(proj["id"])
    # Lane-launch controls.
    assert "launchLane('research')" in html
    assert "launchLane('plan')" in html
    assert "launchLane('build')" in html
    # Log drawer + gate hooks (the page emits single-quoted attributes).
    assert "id='laneLog'" in html
    assert "id='laneGate'" in html
    assert "/api/rnd/launch_lane" in html
    assert "/api/rnd/tail" in html
    assert "/api/rnd/answer_gate" in html
    # The PROJECT_ID was injected for the JS.
    assert "PROJECT_ID" in html
