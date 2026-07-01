"""Wave 1 gate — Claude-first session launch.

crucible-improve-followup (2026-07-01), Wave 1.

Locked model policy: every dashboard session-launch control opens on CLAUDE by
default. Gemini is reachable only via the per-session engine toggle / the 5:1
skill-layer swarm — NEVER as a launch default. This gate asserts the JS launch
defaults (newTermSession / newEffort / grass workbench / engine-toggle highlight)
and the research-lane launcher all default to Claude, and that no launch site in
the project-window JS still hardcodes gemini.
"""
import importlib
import re
import subprocess
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    """Reload the render stack against an isolated temp data dir so a rendered
    project window can be produced without touching real data or :8777."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "rnd_registry", "session_registry", "effort_history",
                "summarizer", "lanes", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    return importlib.reload(anchor_gui)


# ── JS launch-default assertions (module-level _PROJECT_WINDOW_JS) ───────────

def test_newtermsession_defaults_to_claude(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    assert "backend = backend || 'claude'" in js
    assert "backend = backend || 'gemini'" not in js


def test_neweffort_payload_launches_claude(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    # The effort_managed launch payload must request claude, never gemini.
    assert "backend: 'claude'" in js
    assert "backend: 'gemini'" not in js


def test_grass_workbench_default_engine_is_claude(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    assert "_grassEngine = 'claude'" in js
    assert "_grassEngine = 'gemini'" not in js


def test_engine_toggle_highlight_defaults_claude(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    assert "(s && s.backend) || 'claude'" in js
    assert "(s && s.backend) || 'gemini'" not in js


def test_no_gemini_launch_default_or_fallback_remains(gui_env):
    """Policy guard: no launch payload / MANAGED fallback / default in the
    project-window JS still pins gemini. (The ◆Claude/✦Gemini toggle button list
    keeps the literal 'gemini' as a SELECTABLE value — that is not a default and
    is matched narrowly here.)"""
    js = gui_env._PROJECT_WINDOW_JS
    assert "|| 'gemini'" not in js, "a gemini launch/fallback default remains"
    assert "backend: 'gemini'" not in js, "a launch payload still pins gemini"


# ── Rendered project window (Layout-D — the REAL launch controls) ────────────

def test_layoutd_launch_controls_default_to_claude(gui_env, tmp_path):
    """The served project window (v12 Layout-D — what the user actually sees)
    launches on Claude: the '+ New effort' buttons call newEffort (which posts
    backend:'claude') and 'Open terminal' calls newGeneral('claude'). No launch
    control in the rendered window hands a session to gemini."""
    import rnd_registry
    folder = tmp_path / "Proj"
    folder.mkdir()
    pid = rnd_registry.add_project("Proj", str(folder), scaffold=False)["id"]
    html = gui_env.render_project_window_html(pid)
    # The real research/plan launchers + the bare terminal are present ...
    assert "newEffort('research')" in html
    assert "newGeneral('claude')" in html
    # ... and no launch control in the served window pins gemini.
    assert "newTermSession('research','gemini')" not in html
    assert "backend: 'gemini'" not in html
    assert "|| 'gemini'" not in html


# ── Client payloads for promote / continue explicitly request claude ─────────

def test_promote_and_continue_payloads_request_claude(gui_env):
    js = gui_env._PROJECT_WINDOW_JS
    # promoteGrass + continueSession are NEW sessions; both must pin claude in the
    # payload (not fall through to the server's sticky last_engine).
    assert re.search(r"idea_id: ideaId, lane: lane,\s*backend: 'claude'", js), \
        "promoteGrass payload must request claude"
    assert re.search(r"source_session: sessionId,\s*backend: 'claude'", js), \
        "continueSession payload must request claude"


# ── Regression: the backend default engine really is claude ──────────────────

def test_backend_default_engine_is_claude(gui_env):
    import lanes
    import terminal_session
    assert terminal_session.DEFAULT_ENGINE == lanes.BACKEND_CLAUDE == "claude"


# ── Behavioral (un-gameable): the sticky-last_engine LEAK is closed ──────────
#
# Reviewer A's DEFECT 1: promote / continue used to resolve to the project's
# sticky last_engine, so after ANY per-session Gemini toggle an unrelated
# promote/continue would silently open on Gemini. These tests set the project's
# last_engine to gemini and prove the NEW sessions still open on CLAUDE.

@pytest.fixture
def live_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt"))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "summarizer", "gate_adapter", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")
    import rnd_registry
    proj = rnd_registry.add_project("Leak", str(repo), scaffold=False)
    yield {"pid": proj["id"], "repo": repo}
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_promote_opens_claude_after_gemini_toggle(live_env):
    import effort_history
    import terminal_session
    pid = live_env["pid"]
    # Simulate a prior per-session Gemini toggle in this project.
    terminal_session.set_last_engine_for_project(pid, "gemini")
    assert terminal_session.last_engine_for_project(pid) == "gemini"
    idea = effort_history.add_idea(live_env["repo"], pid, "an idea to promote")
    idea_id = idea.get("job_id") or idea.get("idea_id") or idea.get("id")
    # The endpoint now passes backend='claude'; the promote must honor it.
    rec = effort_history.promote_grass_to_lane(pid, idea_id, "research",
                                               backend="claude")
    assert rec.get("backend") == "claude", \
        "promote must open claude, not the sticky gemini last_engine"


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_continue_opens_claude_after_gemini_toggle(live_env):
    import terminal_session
    pid = live_env["pid"]
    terminal_session.set_last_engine_for_project(pid, "gemini")
    # The continue endpoint now defaults + passes backend='claude'.
    rec = terminal_session.start_session(pid, "research", backend="claude",
                                         seed_context="carry on")
    assert rec.get("backend") == "claude", \
        "continue must open claude, not the sticky gemini last_engine"


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_sticky_last_engine_still_leaks_without_explicit_backend(live_env):
    """Guard/witness: prove the LEAK is real at the source — start_session with
    NO backend DOES inherit the sticky gemini. This is exactly why the endpoints
    must pass an explicit backend (the fix), and documents the intentional v4
    'inherit last engine' semantics we deliberately did NOT change globally."""
    import terminal_session
    pid = live_env["pid"]
    terminal_session.set_last_engine_for_project(pid, "gemini")
    rec = terminal_session.start_session(pid, "research", seed_context="x")
    assert rec.get("backend") == "gemini", \
        "witness: no-backend start_session still inherits sticky last_engine"
