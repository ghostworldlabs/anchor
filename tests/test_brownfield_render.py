"""Wave 3 — render honesty for discovered (brownfield-imported) efforts.

Proves IMPLEMENTATION-PLAN.md "## Wave 3":

GIVEN a project with 2 real research efforts AND 1 discovered planning doc, WHEN
the window/tile render, THEN:
  - the real research cards still read >v2< / >v1< (locked kanban test stays green
    WITH a discovered card present),
  - the discovered card contains data-discovered="1" and NO >v< token,
  - the tile/rollup text contains "1 imported".

Machine-asserted (no human "subtle" judgement). Throwaway state under tmp DATA_DIR.
"""
import importlib

import pytest

import brownfield_scan as bscan


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import lanes
    importlib.reload(lanes)
    import anchor_gui
    return importlib.reload(anchor_gui)


def _seed(folder):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "planning"
    p.mkdir()
    (p / "MASTER-PLAN.md").write_text("# Master Plan\n", encoding="utf-8")
    return folder


def test_real_vN_present_and_discovered_has_no_vN(gui, tmp_path):
    import effort_history as eh
    import rnd_registry as rnd
    folder = tmp_path / "proj"
    _seed(folder)
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]

    # 2 real research efforts (versioned v1/v2).
    eh.record_effort(folder, pid, "research", "r1", skill="researchPrime")
    eh.record_effort(folder, pid, "research", "r2", skill="researchPrime")
    # 1 discovered planning doc.
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))

    html = gui.render_project_window_html(pid)

    # v4.1 cockpit-render: lanes render Paradigm-2 tiles. Real research efforts
    # keep their version labels (shown in the tile's .lane row).
    assert ">v2<" in html
    assert ">v1<" in html
    # The discovered session's tile is present and honestly marked "imported"
    # (grey light, no run metrics — never masqueraded as a run).
    assert "imported" in html
    assert "data-light=\"grey\"" in html

    # The discovered session's tile must NOT carry a vN version label. Isolate the
    # planning-lane tile(s) and assert no version token inside.
    import re
    plan_tiles = re.findall(
        r"<div class='tile lane-tile[^>]*data-lane=\"plan\"[^>]*>.*?</div></div></div>",
        html, re.S)
    assert plan_tiles, "no planning tile rendered"
    for tile in plan_tiles:
        assert re.search(r">v\d", tile) is None, \
            f"discovered tile has a vN: {tile!r}"
        # The discovered tile shows the imported state, not a version label.
        assert "imported" in tile


def test_tile_and_rollup_show_imported_count(gui, tmp_path):
    import effort_history as eh
    import rnd_registry as rnd
    folder = tmp_path / "proj"
    _seed(folder)
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))

    entry = rnd.get_project(pid)
    tile = gui.render_project_tile_html(entry)
    assert "1 imported" in tile

    rollup = gui.render_cost_rollup_html(pid, str(folder))
    assert "1 imported" in rollup


def test_discovered_card_not_done_and_not_live(gui, tmp_path):
    import effort_history as eh
    import rnd_registry as rnd
    folder = tmp_path / "proj"
    _seed(folder)
    proj = rnd.add_project("Brown", str(folder))
    pid = proj["id"]
    eh.adopt_discovered(folder, pid, bscan.scan(str(folder)))
    views = gui._gather_project_efforts(str(folder), pid)
    plan = views["plan"]
    assert len(plan) == 1
    v = plan[0]
    assert v["discovered"] is True
    assert v["is_live"] is False
    assert v["is_done"] is False
    assert v["ver"] == ""
    assert v["cost_usd"] == 0.0
    assert v["artifact_path"] == "planning/MASTER-PLAN.md"
