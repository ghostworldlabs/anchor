"""v7 Wave 4 gate — "Open terminal" general session button (#4).

John's choice B: a general terminal is a BUTTON at the top of the project window,
NOT a 6th board lane column. The North-Star contract (IMPLEMENTATION-PLAN Wave 4):

  (a) ``general`` is a VALID lane (``terminal_session._valid_lanes``) that maps to
      NO trio skill — ``seed_for_lane('general')`` returns ``None`` → a BARE PTY
      (like ``grass``). A started general session has ``seeded`` False / empty
      ``seed_text`` (vs a research session, which IS seeded).
  (b) A general session is EXCLUDED from the trio board columns
      (``anchor_gui._REGISTRY_LANE_TO_COLUMN`` has no ``general`` entry) and from
      the auto-advance chain (``auto_advance_planning_to_build`` only fires for a
      planning lane — a general session never advances, even with a plan set).
  (c) The project window renders an "Open terminal" button; there is NO ``general``
      board lane column (negative).
  (d) Clicking "Open terminal" starts a bare general session → opens an inline
      panel AND a chip in ``#sessionBar`` — and adds NO new trio board tile.

Un-gameable v4.1 gate model: backend assertions + rendered-DOM (positive +
negative) + a real Playwright/Chromium interaction test + a screenshot for
orchestrator review. Never :8777, never real data — stub PTY, temp data dir +
worktree base, a throwaway temp git repo.
"""
import importlib
import re
import subprocess
import threading
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


# ── env / fixtures (stub PTY, temp data+worktree, hermetic git repo) ─────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + tmp worktree base + stub PTY + the fake runner + a temp git
    repo + a registered project. Reloads the full stack against the isolated env
    so start_session creates a real worktree off the TEMP repo (never C:\\dev)."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    # Make sure no stray seed override leaks a seed into the bare general lane.
    for var in list(__import__("os").environ):
        if var.startswith("ANCHOR_SEED_PROMPT_") or var == "ANCHOR_TERMINAL_SEED":
            monkeypatch.delenv(var, raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "summarizer", "handoff", "gate_adapter", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import terminal_session as ts
    import session_registry as reg
    import effort_history as eh
    import handoff as ho

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    import rnd_registry
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    bundle = {"gui": gui, "ts": ts, "reg": reg, "eh": eh, "handoff": ho,
              "data": data, "wbase": wbase, "repo": repo, "pid": proj["id"]}
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _add_plan_session(eh, repo, pid, plan_dir="planning/rnd-x", created_at=2000.0):
    """Record a discovered planning session with a REAL MASTER+IMPL plan set
    committed into the repo so discovery would find it (used to PROVE a general
    session never advances even when a plan set exists)."""
    master_rel = f"{plan_dir}/MASTER-PLAN.md"
    impl_rel = f"{plan_dir}/IMPLEMENTATION-PLAN.md"
    for rel, body in [(master_rel, "# Master Plan\n"),
                      (impl_rel, "# Implementation Plan\n")]:
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    for i, (rel, title) in enumerate(
            [(master_rel, "Master Plan"), (impl_rel, "Implementation Plan")]):
        jid = eh.discovered_job_id("planning", rel)
        eh.record_effort(
            repo, pid, "planning", jid, skill="Crucible",
            extra={"source": eh.SOURCE_DISCOVERED, "kind": "plan-doc",
                   "title": title, "artifact_path": rel, "status": "imported",
                   "created_at": created_at + i * 0.001})


def _strip(html):
    b = re.sub(r"<style[\s\S]*?</style>", "", html)
    b = re.sub(r"<script[\s\S]*?</script>", "", b)
    m = re.search(r"<body[^>]*>([\s\S]*)</body>", b)
    return m.group(1) if m else b


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        self.els.append((tag, (d.get("class") or "").split(), d))


def _parse(body):
    c = _Collector()
    c.feed(body)
    return c.els


def _col_tiles(body, trio_lane):
    """The .tile elements inside one lane column (#cards_<lane> slice)."""
    start = body.find("id='cards_%s'" % trio_lane)
    if start < 0:
        start = body.find('id="cards_%s"' % trio_lane)
    assert start >= 0, "no cards_%s container in body" % trio_lane
    rest = body[start:]
    nxt = re.search(r"data-col-lane=", rest[5:])
    end = (nxt.start() + 5) if nxt else len(rest)
    seg = rest[:end]
    return [(classes, attrs) for tag, classes, attrs in _parse(seg)
            if tag == "div" and "tile" in classes]


# ════════════════════════════════════════════════════════════════════════════
# (A) BACKEND — a bare, valid, excluded `general` lane
# ════════════════════════════════════════════════════════════════════════════

def test_general_is_a_valid_lane(env):
    """``general`` validates in the canonical lane set (so term_start accepts it),
    while a typo still does not."""
    ts = env["ts"]
    assert "general" in ts._valid_lanes()
    assert "planx" not in ts._valid_lanes()


def test_general_lane_has_no_seed(env):
    """seed_for_lane('general') is None (bare PTY), unlike a trio lane."""
    ts = env["ts"]
    assert ts.seed_for_lane("general") is None
    assert "general" not in ts.LANE_SKILL
    # The trio lanes DO resolve a seed (sanity contrast).
    assert ts.seed_for_lane("research") is not None


def test_general_session_starts_bare_no_seed(env):
    """A started general session is BARE — seeded False / empty seed_text —
    whereas a research session IS seeded (the un-gameable contrast)."""
    ts, reg = env["ts"], env["reg"]
    pid = env["pid"]

    gen = ts.start_session(pid, "general", backend="claude")
    gsid = gen["session_id"]
    grec = reg.get_session(gsid)
    assert grec["lane"] == "general"
    assert grec["status"] == reg.STATUS_RUNNING
    assert grec.get("seeded") is False, "general session must NOT be seeded"
    assert (grec.get("seed_text") or "") == "", "general session has no seed_text"

    res = ts.start_session(pid, "research", backend="claude")
    rrec = reg.get_session(res["session_id"])
    assert rrec.get("seeded") is True, "research session SHOULD be seeded (contrast)"
    assert (rrec.get("seed_text") or "") != ""

    ts.kill(gsid)
    ts.kill(res["session_id"])


def test_general_not_in_registry_lane_to_column(env):
    """NEGATIVE: the board's registry→column map has NO 'general' entry, so a
    general session never produces a trio board tile."""
    gui = env["gui"]
    assert "general" not in gui._REGISTRY_LANE_TO_COLUMN
    # The map's values are only the trio/deliverables columns.
    assert set(gui._REGISTRY_LANE_TO_COLUMN.values()) <= {
        "research", "plan", "build", "deliverables"}
    # And _registry_session_view for a general record maps to trio_lane "".
    view = gui._registry_session_view(
        {"session_id": "x", "lane": "general", "status": "running",
         "label": "", "created_at": 0.0})
    assert view["trio_lane"] == "", "general session view leaked a trio column"


def test_general_session_never_auto_advances_even_with_plan_set(env):
    """A general session is NOT a planning lane → auto_advance_planning_to_build
    returns None and opens NO build, EVEN when a real plan set is discoverable."""
    ts, reg, eh, repo, pid = (env["ts"], env["reg"], env["eh"],
                              env["repo"], env["pid"])
    _add_plan_session(eh, repo, pid)  # a real plan set exists in the repo

    gen = ts.start_session(pid, "general", backend="claude")
    gsid = gen["session_id"]
    ts.kill(gsid)  # → terminal/DONE, like the hard-kill transition
    assert reg.get_session(gsid)["status"] in reg.TERMINAL_STATUSES

    out = ts.auto_advance_planning_to_build(pid, gsid)
    assert out is None, "a general session must never advance to build"
    assert [s for s in reg.list_sessions(project_id=pid)
            if s.get("lane") == "build"] == [], "a build was opened for general!"


def test_grass_behavior_unchanged(env):
    """Regression: ``grass`` is still a valid, bare (un-seeded) lane."""
    ts = env["ts"]
    assert "grass" in ts._valid_lanes()
    assert ts.seed_for_lane("grass") is None


# ════════════════════════════════════════════════════════════════════════════
# (B) DOM — the "Open terminal" button + NO general board column (negative)
# ════════════════════════════════════════════════════════════════════════════

def test_open_terminal_button_present(env):
    """The project window header renders an "Open terminal" affordance that
    launches a general session via newTermSession('general', ...)."""
    gui = env["gui"]
    html = gui.render_project_window_html(env["pid"])
    body = _strip(html)
    # The button is present in the rendered (style/script-stripped) body.
    found = [(c, a) for tag, c, a in _parse(body)
             if tag == "button" and a.get("id") == "openTermBtn"]
    assert len(found) == 1, "the Open terminal button is not in the header"
    # Its onclick (raw HTML, survives the script strip since it's an attribute)
    # launches a bare general session.
    assert "newTermSession('general'" in html, \
        "Open terminal button does not launch a general session"
    # Human-meaningful label.
    assert "Open terminal" in html


def test_no_general_board_lane_column(env):
    """NEGATIVE: the board has EXACTLY the trio + deliverables + grass columns —
    there is NO 'general' lane column tile container."""
    gui = env["gui"]
    body = _strip(gui.render_project_window_html(env["pid"]))
    cols = sorted({a.get("data-col-lane") for tag, c, a in _parse(body)
                   if a.get("data-col-lane")})
    assert cols == ["build", "deliverables", "grass", "plan", "research"], \
        "board columns changed (general must NOT be a board lane): %s" % cols
    assert "id='cards_general'" not in body and 'id="cards_general"' not in body, \
        "a general lane column container was rendered"


def test_general_session_makes_no_trio_board_tile(env):
    """A started general session does NOT add a tile to any trio board column."""
    gui, ts = env["gui"], env["ts"]
    pid = env["pid"]
    gen = ts.start_session(pid, "general", backend="claude")
    gsid = gen["session_id"]
    body = _strip(gui.render_project_window_html(pid))
    for lane in ("research", "plan", "build", "deliverables"):
        present = [a for c, a in _col_tiles(body, lane)
                   if a.get("data-session") == gsid]
        assert present == [], "general session leaked into the %s column" % lane
    ts.kill(gsid)


# ════════════════════════════════════════════════════════════════════════════
# (C) REAL Playwright + Chromium interaction test (dev-only)
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def server(env):
    gui = env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        srv.shutdown(); srv.server_close(); t.join(timeout=5)


def test_playwright_open_terminal_opens_bare_general_session(server):
    """End to end in a real browser:

      1. Load the project window; click "Open terminal".
      2. A bare general session starts → an inline panel opens in #panelStack AND
         a live chip appears in #sessionBar (data-lane='general').
      3. NO new tile is added to any trio board lane column for it.
      4. No JS console errors.

    Screenshot saved to _devtest/wave4_general.png for orchestrator review.
    """
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")

        # Baseline: no general column tiles anywhere on the trio board.
        for lane in ("research", "plan", "build"):
            assert pg.eval_on_selector_all(
                "#cards_%s .tile" % lane, "e=>e.length") == 0, \
                "trio board not empty before launch"

        # 1) Click the "Open terminal" button.
        pg.wait_for_selector("#openTermBtn", timeout=8000)
        pg.click("#openTermBtn")

        # 2) A live chip for a GENERAL session appears in the top active strip.
        chip_sel = "#sessionBar .live-chip[data-lane='general']"
        pg.wait_for_selector(chip_sel, timeout=8000)
        assert pg.eval_on_selector_all(chip_sel, "e=>e.length") == 1, \
            "expected exactly one general chip in the active strip"
        gsid = pg.eval_on_selector(
            chip_sel, "e=>e.getAttribute('data-session')")
        assert gsid, "general chip has no session id"

        # An inline panel opened for it in the panel stack.
        pg.wait_for_selector(
            "#panelStack .panel[data-session='%s']" % gsid, timeout=8000)

        # 3) NO trio board column tile was created for the general session.
        for lane in ("research", "plan", "build", "deliverables"):
            assert pg.eval_on_selector_all(
                "#cards_%s .tile[data-session='%s']" % (lane, gsid),
                "e=>e.length") == 0, \
                "general session created a %s board tile" % lane

        _DEVTEST.mkdir(exist_ok=True)
        pg.screenshot(path=str(_DEVTEST / "wave4_general.png"), full_page=True)

        assert not errors, f"JS console errors on Open terminal: {errors}"
        b.close()
