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
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui


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
    assert "none-yet" in html


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
