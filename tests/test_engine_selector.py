"""Per-effort ENGINE selector (Claude / Gemini) for the R&D control surface.

Policy (from the user):
- Claude is the DEFAULT engine and is available on ALL lanes (research/plan/build).
- Gemini is available ONLY for the research lane (researchPrime is portable);
  plan/build are Claude-only (Crucible/Foreman are Claude Code engines Gemini
  can't run).

CRITICAL test invariant: ``ANCHOR_RUNNER_CMD``, when set, overrides the runner
command for EVERY backend — that is how the whole suite drives the mock
``tests/fake_claude.py`` regardless of engine. These tests prove that is intact
AND that, with the override UNSET, the resolver returns a claude-shaped command
for claude and a gemini-shaped command for gemini.

NEVER invokes live ``claude`` or live ``gemini`` — launches route through
ANCHOR_RUNNER_CMD → tests/fake_claude.py. Throwaway server on an OS-assigned free
port (port=0); 8777 / the live service / real data are never touched. All
spawned procs are reaped.
"""
import importlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


# ── Fixtures (reload the stack against a tmp data dir + the mock runner) ──────

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_GEMINI_CMD", raising=False)
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import lanes
    importlib.reload(lanes)
    yield lanes
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_GEMINI_CMD", raising=False)
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
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


@pytest.fixture
def server(gui_env):
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


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


# ── launch_lane backend policy ───────────────────────────────────────────────

def test_research_gemini_launches_and_records_engine(env, tmp_path):
    lanes = env
    import job_runner
    proj = _mkproject(tmp_path / "rg", "Alpha")
    rec = lanes.launch_lane(proj["id"], "research", backend="gemini",
                            extra_args=["--lines", "1"])
    assert rec["backend"] == "gemini"
    # The engine is stamped on the durable record AND the launch pointer-record.
    out = Path(rec["output_dir"]) / lanes.LAUNCH_RECORD_NAME
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["backend"] == "gemini"
    job_runner.wait(rec["job_id"], timeout=30)


def test_plan_gemini_refused_with_clear_policy_error(env, tmp_path):
    lanes = env
    proj = _mkproject(tmp_path / "pg", "Beta")
    with pytest.raises(lanes.EngineNotAllowedError) as ei:
        lanes.launch_lane(proj["id"], "plan", backend="gemini")
    assert ei.value.lane == "plan"
    assert ei.value.backend == "gemini"
    assert "Gemini" in str(ei.value) and "Research" in str(ei.value)


def test_build_gemini_refused(env, tmp_path):
    lanes = env
    proj = _mkproject(tmp_path / "bg", "Gamma")
    with pytest.raises(lanes.EngineNotAllowedError):
        lanes.launch_lane(proj["id"], "build", backend="gemini")


def test_claude_works_on_all_three_lanes(env, tmp_path):
    lanes = env
    import job_runner
    for i, lane in enumerate(("research", "plan", "build")):
        proj = _mkproject(tmp_path / f"c{i}", lane)
        rec = lanes.launch_lane(proj["id"], lane, backend="claude",
                                extra_args=["--lines", "1"])
        assert rec["backend"] == "claude"
        job_runner.wait(rec["job_id"], timeout=30)


def test_default_backend_is_claude(env, tmp_path):
    lanes = env
    import job_runner
    proj = _mkproject(tmp_path / "def", "Delta")
    rec = lanes.launch_lane(proj["id"], "research", extra_args=["--lines", "1"])
    assert rec["backend"] == "claude"
    job_runner.wait(rec["job_id"], timeout=30)


# ── Runner command resolution ────────────────────────────────────────────────

def test_runner_cmd_override_wins_for_both_backends(env, monkeypatch):
    """With ANCHOR_RUNNER_CMD SET, BOTH backends resolve to the mock — proving
    the test indirection is never broken by the gemini branch."""
    import job_runner
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    claude_cmd = job_runner.resolve_runner_cmd(backend="claude")
    gemini_cmd = job_runner.resolve_runner_cmd(backend="gemini")
    # Both backends resolve to the mock runner — the override wins for each.
    assert FAKE in " ".join(claude_cmd)
    assert FAKE in " ".join(gemini_cmd)
    # The override never resolves to the real claude/gemini default commands.
    assert claude_cmd[0] != "claude" and gemini_cmd[0] != "gemini"


def test_runner_cmd_unset_resolves_per_backend(env, monkeypatch):
    """With ANCHOR_RUNNER_CMD UNSET, claude resolves to a claude-shaped command
    and gemini to a gemini-shaped one (contains 'gemini' and '-p'). Env is
    restored by monkeypatch after the test."""
    import job_runner
    monkeypatch.delenv("ANCHOR_RUNNER_CMD", raising=False)
    monkeypatch.delenv("ANCHOR_GEMINI_CMD", raising=False)

    claude_cmd = job_runner.resolve_runner_cmd(backend="claude")
    assert claude_cmd[0] == "claude"
    assert "-p" in claude_cmd

    gemini_cmd = job_runner.resolve_runner_cmd(backend="gemini")
    assert "gemini" in gemini_cmd
    assert "-p" in gemini_cmd
    # Read-only approval posture (research is non-mutating).
    assert "--approval-mode" in gemini_cmd
    # Spike finding (2026-06-09): jobs run inside the project folder, so the
    # gemini default MUST carry --skip-trust or gemini refuses agentic work.
    assert "--skip-trust" in gemini_cmd


def test_gemini_default_includes_skip_trust(env, monkeypatch):
    """The built-in gemini default command carries --skip-trust (spike finding):
    gemini treats untrusted project dirs as read-only and overrides the approval
    mode unless --skip-trust is passed, and jobs run inside the project folder.
    claude's default is unaffected."""
    import job_runner
    monkeypatch.delenv("ANCHOR_RUNNER_CMD", raising=False)
    monkeypatch.delenv("ANCHOR_GEMINI_CMD", raising=False)
    gemini_cmd = job_runner.resolve_runner_cmd(backend="gemini")
    assert "--skip-trust" in gemini_cmd
    assert "gemini" in gemini_cmd and "-p" in gemini_cmd
    # The raw default constant also reflects the flag.
    assert "--skip-trust" in job_runner.DEFAULT_GEMINI_CMD
    # Claude default is unchanged — no --skip-trust leaked into it.
    claude_cmd = job_runner.resolve_runner_cmd(backend="claude")
    assert "--skip-trust" not in claude_cmd
    assert claude_cmd[0] == "claude"


def test_runner_cmd_override_wins_over_skip_trust_default(env, monkeypatch):
    """ANCHOR_RUNNER_CMD precedence is intact: when set, it wins for the gemini
    backend too, so the --skip-trust default is NOT used (the mock runner drives
    every test)."""
    import job_runner
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_GEMINI_CMD", raising=False)
    gemini_cmd = job_runner.resolve_runner_cmd(backend="gemini")
    assert "--skip-trust" not in gemini_cmd
    assert FAKE in " ".join(gemini_cmd)


def test_gemini_cmd_env_override(env, monkeypatch):
    """ANCHOR_GEMINI_CMD overrides the built-in gemini default (when
    ANCHOR_RUNNER_CMD is unset)."""
    import job_runner
    monkeypatch.delenv("ANCHOR_RUNNER_CMD", raising=False)
    monkeypatch.setenv("ANCHOR_GEMINI_CMD", "gemini -p -m custom-model")
    cmd = job_runner.resolve_runner_cmd(backend="gemini")
    assert cmd == ["gemini", "-p", "-m", "custom-model"]


# ── /api/rnd/launch_lane endpoint ────────────────────────────────────────────

def test_endpoint_research_gemini_ok(server, tmp_path):
    gui, base = server
    import job_runner
    proj = _mkproject(tmp_path / "ep_rg", "Epsilon")
    code, body = _post(base + "/api/rnd/launch_lane",
                       {"project_id": proj["id"], "lane": "research",
                        "backend": "gemini"})
    assert code == 200
    assert body["ok"] is True
    assert body["job_id"]
    assert body["backend"] == "gemini"
    job_runner.wait(body["job_id"], timeout=30)


def test_endpoint_build_gemini_clean_error(server, tmp_path):
    gui, base = server
    proj = _mkproject(tmp_path / "ep_bg", "Zeta")
    code, body = _post(base + "/api/rnd/launch_lane",
                       {"project_id": proj["id"], "lane": "build",
                        "backend": "gemini"})
    # Clean JSON error, NOT a 500.
    assert code == 400
    assert body["ok"] is False
    assert body["reason"] == "engine-not-allowed"


def test_endpoint_default_backend_is_claude(server, tmp_path):
    gui, base = server
    import job_runner
    proj = _mkproject(tmp_path / "ep_def", "Eta")
    code, body = _post(base + "/api/rnd/launch_lane",
                       {"project_id": proj["id"], "lane": "plan"})
    assert code == 200
    assert body["ok"] is True
    assert body["backend"] == "claude"
    job_runner.wait(body["job_id"], timeout=30)


# ── render: project window offers Gemini for research, not plan/build ─────────

def test_project_window_offers_gemini_for_research_only(gui_env, tmp_path):
    gui = gui_env
    proj = _mkproject(tmp_path / "win", "WindowProj")
    html = gui.render_project_window_html(proj["id"])
    # Research offers an engine choice (Claude + Gemini buttons). Wave 7: the
    # "+ New run" affordances open the interactive TERMINAL (openTerminal),
    # replacing the old raw-log launch console (launchLane); the engine policy
    # surfaced by the affordance text is unchanged.
    assert "openTerminal('research','claude')" in html
    assert "openTerminal('research','gemini')" in html
    # Plan/Build stay Claude-only — no engine choice.
    assert "openTerminal('plan')" in html
    assert "openTerminal('build')" in html
    assert "openTerminal('plan','gemini')" not in html
    assert "openTerminal('build','gemini')" not in html
    # A Gemini option is offered somewhere in the window.
    assert "gemini" in html.lower()
    # f-string intact: no leaked doubled braces.
    assert "{{" not in html and "}}" not in html
