"""Wave 3 — single-instance project window.

Opening project id X twice returns the same instance id (no duplicate window).
"""
import importlib

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


def _record_discovered(eh, folder, pid, lane, rel, ts, title="", kind=""):
    """Helper: record one DISCOVERED planning effort under ``rel`` (folder-rel)."""
    jid = eh.discovered_job_id(lane, rel)
    eh.record_effort(
        folder, pid, lane, jid,
        skill="crucible",
        extra={
            "source": eh.SOURCE_DISCOVERED,
            "artifact_path": rel,
            "created_at": ts,
            "title": title or rel,
            "kind": kind,
        },
    )
    return jid


def test_single_instance_returns_same_id(gui, tmp_path):
    folder = tmp_path / "P"
    folder.mkdir()
    e = gui.select_existing_project("P", str(folder))
    pid = e["entry"]["id"]

    first = gui.open_project_instance(pid)
    assert first["reused"] is False
    second = gui.open_project_instance(pid)
    assert second["reused"] is True
    assert second["instance_id"] == first["instance_id"]


def test_distinct_projects_distinct_instances(gui, tmp_path):
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    a = gui.select_existing_project("A", str(tmp_path / "A"))["entry"]["id"]
    b = gui.select_existing_project("B", str(tmp_path / "B"))["entry"]["id"]
    ia = gui.open_project_instance(a)["instance_id"]
    ib = gui.open_project_instance(b)["instance_id"]
    assert ia != ib


def test_close_then_reopen_is_fresh(gui, tmp_path):
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("P", str(folder))["entry"]["id"]
    first = gui.open_project_instance(pid)["instance_id"]
    assert gui.close_project_instance(pid) is True
    second = gui.open_project_instance(pid)["instance_id"]
    assert second != first


def test_project_window_html_renders(gui, tmp_path):
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("ShinyProj", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    assert "ShinyProj" in html
    # Wave 3 contract: empty lanes read "Lane: 0", NOT the old "none-yet" state.
    assert "none-yet" not in html
    assert "Research: 0" in html


def test_project_window_unknown_id_no_crash(gui):
    html = gui.render_project_window_html("nonexistent-id")
    assert "not found" in html.lower()


def test_project_window_css_has_single_braces(gui, tmp_path):
    """F1 regression guard: the /project/<id> <style> block must serve valid
    CSS with single braces — no literal ``{{``/``}}`` leaked from non-f-string
    literals that were wrongly brace-doubled."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("ShinyProj", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    # No literal doubled braces anywhere in the served HTML.
    assert "{{" not in html
    assert "}}" not in html
    # Known CSS rules render with correct single braces.
    assert "body{font-family" in html
    assert ".rnd-lane{" in html


def test_project_field_only_from_trailing_metadata(gui, tmp_path):
    """F2 regression guard (anchor_gui.py): "Project:" in the task body must NOT
    create a project link; a real trailing ``— Project: <id>`` field must parse
    AND round-trip unchanged through serialize_task_line."""
    md = tmp_path / "proj.md"
    md.write_text(
        "- [ ] Plan Project: Apollo milestones\n"
        "- [ ] Wire dashboard — Priority: 1 — energy: high — [academic] "
        "— Project: abc123\n",
        encoding="utf-8",
    )

    tasks = gui.parse_tasks_from_md(md)
    assert len(tasks) == 2

    # Body mention → no project link.
    assert not tasks[0]["project"]
    assert "Plan Project: Apollo milestones" in tasks[0]["text"]

    # Real trailing field → parsed and preserved on re-serialization.
    assert tasks[1]["project"] == "abc123"
    line = gui.serialize_task_line(tasks[1])
    assert "— Project: abc123" in line
    # Round-trip: parse the serialized line back, project survives unchanged.
    md2 = tmp_path / "proj2.md"
    md2.write_text(line + "\n", encoding="utf-8")
    assert gui.parse_tasks_from_md(md2)[0]["project"] == "abc123"


# ── Wave 4 — most-recent + expander, grass column, linked-tasks strip ────────

def test_kanban_columns_include_grass(gui):
    """The Kanban column set now includes a Grass Catchers column."""
    lanes = [c[0] for c in gui._KANBAN_COLUMNS]
    assert "grass" in lanes
    # Find the grass column tuple: (trio_lane, store_subdir, label, glyph, add).
    grass = next(c for c in gui._KANBAN_COLUMNS if c[0] == "grass")
    assert grass[1] == "grass"
    assert grass[2] == "Grass Catchers"


def test_grass_in_lane_dirs(gui):
    """rnd_registry scaffolds a grass lane dir so the store can hold it."""
    import rnd_registry
    assert "grass" in rnd_registry.LANE_DIRS


def test_grass_column_renders_in_window(gui, tmp_path):
    """An empty Grass Catchers column is present and does not break the others."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("Grassy", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    assert "Grass Catchers" in html
    assert "data-col-lane='grass'" in html
    # The 4 original columns still render.
    for lane in ("research", "plan", "build", "deliverables"):
        assert f"data-col-lane='{lane}'" in html


def test_most_recent_plus_previous_sessions_expander(gui, tmp_path):
    """G/W/T: given a lane with >=2 sessions, exactly 1 session card is visible
    and the remainder sit behind a 'previous sessions' toggle."""
    import effort_history as eh
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("MultiSess", str(folder))["entry"]["id"]
    # Session A (older): two files under brownfield-discovery/.
    _record_discovered(eh, str(folder), pid, "plan",
                       "planning/brownfield-discovery/MASTER-PLAN.md", 1000.0,
                       title="Master Plan", kind="master-plan")
    _record_discovered(eh, str(folder), pid, "plan",
                       "planning/brownfield-discovery/NOTES.md", 1001.0)
    # Session B (newer): one file under rnd-v1/.
    _record_discovered(eh, str(folder), pid, "plan",
                       "planning/rnd-v1/PLAN.md", 2000.0, title="v1 Plan")

    # Two sessions for the planning lane.
    import sessions as sess
    sess_list = sess.list_sessions(str(folder), pid, "plan")
    assert len(sess_list) == 2

    html = gui.render_project_window_html(pid)
    # Exactly one "previous sessions" expander for the lane with 2 sessions.
    assert "previous sessions (1)" in html
    assert html.count("previous sessions (") == 1
    # The multi-file session collapses its extra members behind a per-card
    # "files (N)" expander rather than rendering N separate cards.
    assert "files (2)" in html


def test_single_session_lane_has_no_previous_expander(gui, tmp_path):
    """A lane with one session shows the card with no 'previous sessions' toggle."""
    import effort_history as eh
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("OneSess", str(folder))["entry"]["id"]
    _record_discovered(eh, str(folder), pid, "build",
                       "build/foreman-run/report.md", 1000.0, title="Build")
    html = gui.render_project_window_html(pid)
    # Build lane has 1 session → no previous-sessions expander at all.
    assert "previous sessions (" not in html


def test_linked_tasks_strip_renders_with_link_affordance(gui, tmp_path):
    """The linked-tasks strip renders a working 'Link task' affordance and the
    Wave-4 strip replaces the old dead-end message."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("Linker", str(folder))["entry"]["id"]
    html = gui.render_project_window_html(pid)
    # Link affordance is present and wired to the existing endpoint via JS.
    assert "Link task" in html
    assert "rndLinkTask(" in html
    # JS function is defined in the project-window script.
    assert "function rndLinkTask" in html
    assert "/api/rnd/link_task" in html


def test_linked_tasks_strip_reflects_a_linked_task(gui, tmp_path):
    """A task carrying ``Project: <id>`` appears in the strip with an Unlink."""
    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("HasTasks", str(folder))["entry"]["id"]
    # Write a task linked to this project into a domain markdown file.
    gui.DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
    (gui.DOMAINS_DIR / "academic.md").write_text(
        f"- [ ] Wire the dashboard — Priority: 1 — energy: high — [academic] "
        f"— Project: {pid}\n",
        encoding="utf-8",
    )
    tasks = gui.project_tasks(pid)
    assert any("Wire the dashboard" in t.get("text", "") for t in tasks)
    html = gui.render_project_tasks_html(pid)
    assert "Wire the dashboard" in html
    assert "Unlink" in html
    assert "rndUnlinkTask(" in html


def test_linked_task_with_quote_and_apostrophe_roundtrips(gui, tmp_path):
    """Regression (Wave 4 fix): a task whose text contains BOTH an apostrophe
    AND a double-quote (e.g. ``Fix it's "weird" bug``) must (a) render in the
    strip with its text HTML-escaped and the identity carried in data-
    attributes — NOT as an inline JS string literal — and (b) round-trip
    cleanly through the link/unlink backend that the endpoint calls."""
    import html as html_lib

    folder = tmp_path / "P"
    folder.mkdir()
    pid = gui.select_existing_project("Tricky", str(folder))["entry"]["id"]

    task_text = 'Fix it\'s "weird" bug'

    # Write the task into a domain file already linked to this project.
    gui.DOMAINS_DIR.mkdir(parents=True, exist_ok=True)
    (gui.DOMAINS_DIR / "academic.md").write_text(
        f"- [ ] {task_text} — Priority: 2 — energy: med — [academic] "
        f"— Project: {pid}\n",
        encoding="utf-8",
    )

    # (a) Render: text appears HTML-escaped and rides in a data- attribute.
    html = gui.render_project_tasks_html(pid)
    # The Unlink button reads identity from the DOM (no inline string arg).
    assert "rndUnlinkTask(this)" in html
    # No inline onclick smuggles the raw breaking chars as a JS string arg.
    assert "rndUnlinkTask('" not in html
    assert f"rndUnlinkTask(\"{task_text}" not in html
    # The raw text travels via a data-task attribute, HTML-escaped.
    esc = html_lib.escape(task_text, quote=True)
    assert f'data-task="{esc}"' in html
    # Quotes/apostrophes are escaped in display — no raw breaking chars leak
    # into an attribute or inline string.
    assert "data-task=\"Fix it's" not in html  # apostrophe must be escaped

    # (b) Backend round-trip via the SAME function the endpoint calls.
    #   Already linked from the markdown above:
    assert any(t.get("text", "") == task_text for t in gui.project_tasks(pid))
    #   Unlink with the RAW (entity-decoded) text → empty project_id.
    assert gui.link_task(task_text, "") is True
    assert not any(t.get("text", "") == task_text for t in gui.project_tasks(pid))
    #   Re-link the same tricky text → it comes back.
    assert gui.link_task(task_text, pid) is True
    assert any(t.get("text", "") == task_text for t in gui.project_tasks(pid))
