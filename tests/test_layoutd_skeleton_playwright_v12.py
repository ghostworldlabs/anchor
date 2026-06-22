"""v12 Wave 2 — Layout-D static skeleton: real Chromium interaction test.

Machine-checkable: loading the rendered project window in Chromium and clicking a
zone's shelf "Hide/Show all" toggle flips the shelf's `collapsed` class (and the
shelf little-tiles' visibility). This is the falsifiable interaction the static
skeleton ships this wave (the live effort-view + bottom-dock transport is W10).

DEV-ONLY: gated by pytest.importorskip("playwright.sync_api") so the suite skips
cleanly where Playwright is absent. Playwright is NEVER imported by product code.

Hermetic: temp data/project dirs, stub PTY, an OS-assigned port (asserted
!= 8777), never real data / network.
"""
import importlib
import threading
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "lanes",
                "effort_history", "summarizer", "gate_adapter"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    yield importlib.reload(anchor_gui)


@pytest.fixture
def server(gui_env):
    gui = gui_env
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui, f"http://127.0.0.1:{port}", port
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def test_shelf_toggle_flips_collapsed_class(server, tmp_path):
    """Clicking a zone's shelf 'Hide/Show all' toggle flips its .collapsed class
    (machine-checkable) and updates the caption."""
    pytest.importorskip("playwright.sync_api")
    gui, base, _ = server
    import effort_history as eh
    folder = tmp_path / "Shelf"
    pid = _mkproject(folder, "Shelf")["id"]
    fp = str(folder)
    # >1 research session so a collapsible shelf (with a toggle) is rendered.
    eh.record_effort(fp, pid, "research", "r1", skill="researchPrime",
                     prompt_seed="Coolant trade study")
    eh.record_effort(fp, pid, "research", "r2", skill="researchPrime",
                     prompt_seed="Cladding alloy survey")
    eh.record_effort(fp, pid, "research", "r3", skill="researchPrime",
                     prompt_seed="Decay-heat removal")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="domcontentloaded")

        # the research shelf wrapper + its toggle.
        pg.wait_for_selector("#shelf_research", timeout=5000)
        toggle = pg.query_selector("#tgl_research")
        assert toggle is not None, "no research shelf toggle rendered"

        # starts EXPANDED (mockup default): no .collapsed class.
        collapsed0 = pg.eval_on_selector(
            "#shelf_research", "e => e.classList.contains('collapsed')")
        assert collapsed0 is False, "shelf should start expanded"

        # click → collapses (class added).
        toggle.click()
        collapsed1 = pg.eval_on_selector(
            "#shelf_research", "e => e.classList.contains('collapsed')")
        assert collapsed1 is True, "click did not collapse the shelf"
        cap1 = pg.eval_on_selector("#tgl_research", "e => e.textContent")
        assert "Show all" in cap1, f"caption not updated on collapse: {cap1!r}"

        # click again → expands (class removed).
        toggle.click()
        collapsed2 = pg.eval_on_selector(
            "#shelf_research", "e => e.classList.contains('collapsed')")
        assert collapsed2 is False, "second click did not expand the shelf"
        cap2 = pg.eval_on_selector("#tgl_research", "e => e.textContent")
        assert "Hide" in cap2, f"caption not restored on expand: {cap2!r}"

        b.close()
