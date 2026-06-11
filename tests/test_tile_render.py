"""Wave 3 — first-class imported history: tile per-lane summary line + blurb.

Covers the Wave 3 contract changes:
  - ``rnd_registry.status_line`` returns per-lane SESSION counts + provenance
    (``{lane: {count, imported, running}}``), built from ``sessions.list_sessions``
    so N discovered files that group into 1 session count as 1 — not N.
  - The dashboard tile renders a real per-lane summary line
    ("Research: 1 · Planning: 2 (1 imported) · ...") and NEVER renders the old
    "import" / "none-yet" lane state when sessions exist.
  - A per-project blurb field: seeded once from CLAUDE.md/README/Anchor.md,
    user-editable via ``set_blurb`` / ``POST /api/rnd/set_blurb``, rendered on
    the tile + project window.

Hermetic: temp ANCHOR_DATA_DIR, no live claude, no network.
"""
import importlib
import json
import threading
import urllib.error
import urllib.request

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui, rnd_registry, effort_history, sessions


# ── status_line shape ─────────────────────────────────────────────────────

def test_status_line_returns_per_lane_counts(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]

    line = rnd.status_line(pid)
    # Every lane present with the count/imported/running shape, all zero.
    for lane in rnd.STATUS_LANES:
        assert set(line[lane].keys()) == {"count", "imported", "running"}
        assert line[lane] == {"count": 0, "imported": 0, "running": 0}


def test_status_line_counts_sessions_not_raw_efforts(env, tmp_path):
    """7 discovered planning files in 2 dirs → 2 planning SESSIONS, not 7."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]

    # Two discovered "sessions" (two parent dirs) under planning.
    for i in range(4):
        eh.record_effort(folder, pid, "planning", f"d-bf-{i}",
                         skill="crucible",
                         extra={"source": "discovered",
                                "artifact_path": f"planning/brownfield/{i}.md"})
    for i in range(3):
        eh.record_effort(folder, pid, "planning", f"d-v1-{i}",
                         skill="crucible",
                         extra={"source": "discovered",
                                "artifact_path": f"planning/rnd-v1/{i}.md"})

    line = rnd.status_line(pid)
    assert line["planning"]["count"] == 2          # sessions, not 7 efforts
    assert line["planning"]["imported"] == 2       # both discovered
    assert line["planning"]["running"] == 0


def test_status_line_run_vs_imported(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    # A real run effort (no source:discovered) → one non-imported session.
    eh.record_effort(folder, pid, "research", "job-1", skill="researchPrime")
    line = rnd.status_line(pid)
    assert line["research"]["count"] == 1
    assert line["research"]["imported"] == 0


# ── tile + status-line rendering ───────────────────────────────────────────

def test_tile_renders_per_lane_summary_no_import_state(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    entry = rnd.add_project("P", str(folder))
    pid = entry["id"]
    # 1 research run + 2 planning imported sessions + 1 build run.
    eh.record_effort(folder, pid, "research", "r1", skill="researchPrime")
    eh.record_effort(folder, pid, "planning", "p-a-0", skill="crucible",
                     extra={"source": "discovered",
                            "artifact_path": "planning/a/0.md"})
    eh.record_effort(folder, pid, "planning", "p-b-0", skill="crucible",
                     extra={"source": "discovered",
                            "artifact_path": "planning/b/0.md"})
    eh.record_effort(folder, pid, "build", "b1", skill="foreman")

    line_html = gui.render_status_line_html(pid)
    assert "Research: 1" in line_html
    assert "Planning: 2" in line_html
    assert "(2 imported)" in line_html
    assert "Build: 1" in line_html
    # The old masquerade states must be gone when sessions exist.
    assert "none-yet" not in line_html
    assert ">import<" not in line_html
    assert "Planning: import" not in line_html

    tile = gui.render_project_tile_html(rnd.get_project(pid))
    assert "Research: 1" in tile
    assert "Planning: 2" in tile


# ── blurb seeding + editing ────────────────────────────────────────────────

def test_blurb_seeds_from_claude_md(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "CLAUDE.md").write_text(
        "# My Project\n\nThis project is a control tower for trio R&D.\n",
        encoding="utf-8")
    pid = rnd.add_project("P", str(folder))["id"]

    seeded = rnd.seed_blurb(pid)
    assert "control tower for trio R&D" in seeded["blurb"]
    # Idempotent: a second seed does not overwrite (no force).
    rnd.set_blurb(pid, "user-edited blurb")
    again = rnd.seed_blurb(pid)
    assert again["blurb"] == "user-edited blurb"


def test_blurb_seed_source_order_readme_fallback(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    # No CLAUDE.md; README.md is next in BLURB_SEED_FILES.
    (folder / "README.md").write_text(
        "# Readme Title\n\nReadme paragraph describing the thing.\n",
        encoding="utf-8")
    pid = rnd.add_project("P", str(folder))["id"]
    seeded = rnd.seed_blurb(pid)
    assert "Readme paragraph describing the thing." in seeded["blurb"]


def test_blurb_seed_missing_folder_no_crash(env, tmp_path):
    gui, rnd, eh, _sess = env
    # Folder does not exist on disk → best-effort no-op, no exception.
    pid = rnd.add_project("P", str(tmp_path / "gone"), scaffold=False)["id"]
    seeded = rnd.seed_blurb(pid)
    assert seeded is not None
    assert seeded.get("blurb", "") == ""


def test_set_blurb_persists_and_renders(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]
    rnd.set_blurb(pid, "A crisp one-line blurb.")
    assert rnd.get_project(pid)["blurb"] == "A crisp one-line blurb."
    tile = gui.render_project_tile_html(rnd.get_project(pid))
    assert "A crisp one-line blurb." in tile
    assert "rnd-blurb" in tile


def test_blurb_renders_in_project_window(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("ShinyProj", str(folder))["id"]
    rnd.set_blurb(pid, "Window blurb text.")
    html = gui.render_project_window_html(pid)
    assert "Window blurb text." in html
    # No lane masquerade in the window status line.
    assert "none-yet" not in html


def test_blurb_is_html_escaped_in_tile_and_window(env, tmp_path):
    """A blurb with a <script> payload must be HTML-escaped in BOTH renders."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("XSSProj", str(folder))["id"]
    payload = "<script>alert('xss')</script>"
    rnd.set_blurb(pid, payload)

    tile = gui.render_project_tile_html(rnd.get_project(pid))
    assert payload not in tile
    assert "&lt;script&gt;" in tile

    window = gui.render_project_window_html(pid)
    assert payload not in window
    assert "&lt;script&gt;" in window


def test_set_blurb_endpoint(env, tmp_path):
    """POST /api/rnd/set_blurb persists the blurb (mirrors set_notes wiring)."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("P", str(folder))["id"]

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/rnd/set_blurb",
            data=json.dumps({"id": pid, "blurb": "via endpoint"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
        assert data["ok"] is True
        assert data["entry"]["blurb"] == "via endpoint"
        assert rnd.get_project(pid)["blurb"] == "via endpoint"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
