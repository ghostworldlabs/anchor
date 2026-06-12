"""v4 Wave 1 — the cockpit lane-launch uses the SEEDED v3 substrate.

Locks the Wave-1 Done-when at the RENDER level: the project-window's lane
"+ New <lane> run" affordance must launch the seeded ConPTY path
(``newTermSession`` → ``POST /api/rnd/term_start`` →
``terminal_session.start_session``), NOT the v2 unseeded stream-json REPL
(``openTerminal`` → ``POST /api/rnd/start_terminal`` → ``rnd_terminal``) that
caused the repeating-prompt bug.

String-level assertions over ``render_project_window_html`` (no browser),
mirroring the project-window render tests in ``tests/test_project_window.py``.
The seed substrate itself (``terminal_session`` / ``session_registry``) is
covered by ``tests/test_terminal_seed.py`` and is intentionally not touched here.
"""
import importlib
import re

import pytest


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    import paths
    importlib.reload(paths)
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui


def _make_window_html(gui, tmp_path, name="Cockpit"):
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project(name, str(folder))["entry"]["id"]
    return gui.render_project_window_html(pid)


def test_lane_launch_uses_seeded_term_start_not_start_terminal(gui, tmp_path):
    """(a) The lane "+ New run" affordances launch the seeded path
    (newTermSession / term_start). (b) NO lane-launch affordance wires the v2
    unseeded openTerminal / start_terminal path."""
    html = _make_window_html(gui, tmp_path)

    # (a) Every Kanban lane "+ New run" affordance routes to newTermSession.
    #     research offers Claude + Gemini; plan/build are bare newTermSession.
    assert "newTermSession('research','claude')" in html
    assert "newTermSession('research','gemini')" in html
    assert "newTermSession('plan')" in html
    assert "newTermSession('build')" in html
    # The seeded endpoint is the launch target.
    assert "/api/rnd/term_start" in html

    # (b) The cockpit lane-launch must NOT invoke the v2 unseeded REPL.
    #     openTerminal(...) must not appear as a lane-launch onclick handler, and
    #     no lane-launch wiring may reference start_terminal.
    assert "onclick=\"openTerminal(" not in html
    assert "onclick='openTerminal(" not in html
    # No lane-launch affordance calls the v2 start_terminal endpoint. (The v2
    # function/endpoint may still exist on disk for the legacy console drawer,
    # but the Kanban lane launch no longer routes through it.)
    addnew_onclicks = re.findall(r"class='addnew'[^>]*onclick=\"([^\"]*)\"", html)
    for handler in addnew_onclicks:
        assert "openTerminal" not in handler, (
            "lane '+ New run' affordance still wires the v2 unseeded path: "
            + handler)
        assert "start_terminal" not in handler


def test_seeded_lane_launch_brace_hygiene(gui, tmp_path):
    """The repointed affordance must not leak doubled braces into the served
    HTML (the surrounding render is f-string-generated)."""
    html = _make_window_html(gui, tmp_path)
    assert "{{" not in html
    assert "}}" not in html
