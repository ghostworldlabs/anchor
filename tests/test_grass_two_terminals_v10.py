"""v10 Wave 3 — grass workbench: two independently-toggleable terminals (DOM).

The grass workbench's right pane (``.gwork``) is built CLIENT-SIDE by the
``selectGrassIdea`` function inside ``anchor_gui._PROJECT_WINDOW_JS`` (a RAW
single-brace JS string). These tests reconstruct the static markup that
``selectGrassIdea`` emits for a selected idea — by extracting the function's
single-quoted HTML literals from the JS source and joining them — then parse it
with ``html.parser.HTMLParser`` (the test convention in
``test_cockpit_paradigm2.py`` / ``test_build_planning_tie.py``), NOT a string grep.

POSITIVE — the workbench renders TWO distinct, labeled terminal host containers
(one ``data-lane="research"``, one ``data-lane="plan"``), each its own
``.gterm`` with a collapsible toggle (``.car`` caret + a ``[data-grass-term]``
host keyed by lane).

NEGATIVE — a freshly-selected idea renders BOTH ``.gterm`` containers
``collapsed`` with NO mounted/bound terminal (``[data-grass-term]`` host carries
no ``data-session``), and the two hosts are DISTINCT elements (lane="research" !=
lane="plan"), never one shared host.

The Playwright interaction test (real Chromium) lives below, DEV-ONLY via
``pytest.importorskip``.
"""
import importlib
import re
import subprocess
import threading
import time
from html.parser import HTMLParser
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


# ── Extract the selectGrassIdea HTML template from the JS source ────────────────

def _select_grass_idea_html():
    """Reconstruct the static markup selectGrassIdea() emits, by joining the
    single-quoted string literals in its ``var html = '' + ...;`` template. We
    drop the JS variable interpolations (they carry idea text, not structure) so
    the structural assertions test the literal DOM the function builds."""
    import anchor_gui
    js = anchor_gui._PROJECT_WINDOW_JS
    # Isolate the function body.
    m = re.search(r"function selectGrassIdea\(ideaId\)\s*\{([\s\S]*?)\n\}\n", js)
    assert m, "selectGrassIdea not found in _PROJECT_WINDOW_JS"
    body = m.group(1)
    # Isolate the `var html = '' ... ;` template-string assignment.
    hm = re.search(r"var html = ''([\s\S]*?);\n\s*work\.innerHTML = html;", body)
    assert hm, "selectGrassIdea html template not found"
    tmpl = hm.group(1)
    # Pull every single-quoted literal (handles escaped \' inside) and join.
    lits = re.findall(r"'((?:\\.|[^'\\])*)'", tmpl)
    joined = "".join(s.replace("\\'", "'") for s in lits)
    return joined


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        self.els.append((tag, dict(attrs)))


def _parse(html):
    c = _Collector()
    c.feed(html)
    return c.els


# ── POSITIVE: two distinct, labeled, collapsible terminal hosts ────────────────

def test_two_terminal_hosts_research_and_plan():
    html = _select_grass_idea_html()
    els = _parse(html)
    # Two .gterm containers, one per lane.
    gterms = [d for t, d in els
              if "gterm" in (d.get("class") or "").split()]
    lanes = sorted(d.get("data-lane") for d in gterms)
    assert lanes == ["plan", "research"], \
        f"expected one research + one plan .gterm, got {lanes}"
    # Each .gterm carries its own terminal host keyed by lane.
    hosts = [d for t, d in els if d.get("data-grass-term")]
    host_lanes = sorted(d.get("data-grass-term") for d in hosts)
    assert host_lanes == ["plan", "research"], \
        f"expected per-lane [data-grass-term] hosts, got {host_lanes}"
    # The two hosts are DISTINCT (not one shared host).
    assert len(hosts) == 2 and hosts[0] is not hosts[1]


def test_each_terminal_has_a_collapse_toggle_caret():
    html = _select_grass_idea_html()
    els = _parse(html)
    # Each .gterm has a .car caret control (the collapse/expand toggle).
    carets_in_terms = []
    # Walk: a .car inside a .gterm bar. We assert at least one caret per lane via
    # the rendered text (the JS sets ▸/▾); structurally, two .car spans exist in
    # the devbar buttons AND two in the term bars → >= 4 .car elements.
    cars = [d for t, d in els if "car" in (d.get("class") or "").split()]
    assert len(cars) >= 4, f"expected toggle carets on buttons + term bars, got {len(cars)}"
    # The two Develop buttons carry a data-dev lane each (the toggle triggers).
    devbtns = sorted(d.get("data-dev") for t, d in els if d.get("data-dev"))
    assert devbtns == ["plan", "research"]


# ── NEGATIVE: fresh idea → both collapsed, no bound/mounted terminal ───────────

def test_fresh_idea_both_collapsed_no_mounted_host():
    html = _select_grass_idea_html()
    els = _parse(html)
    gterms = [d for t, d in els
              if "gterm" in (d.get("class") or "").split()]
    # Both .gterm start COLLAPSED.
    for d in gterms:
        assert "collapsed" in (d.get("class") or "").split(), \
            f"a fresh idea's {d.get('data-lane')} terminal should render collapsed"
    # No terminal host is bound to a session yet (no data-session on any host).
    hosts = [d for t, d in els if d.get("data-grass-term")]
    assert hosts, "the two grass term hosts should exist in the markup"
    for d in hosts:
        assert "data-session" not in d, \
            "a fresh idea must not pre-bind a terminal host to a session"


def test_hosts_are_distinct_not_one_shared():
    """Guard the v9-and-earlier single-shared-host regression: the workbench must
    NOT render exactly one [data-grass-term] host reused between lanes."""
    html = _select_grass_idea_html()
    hosts = [d for t, d in _parse(html) if d.get("data-grass-term")]
    seen = [d.get("data-grass-term") for d in hosts]
    assert len(seen) == 2 and len(set(seen)) == 2, \
        f"expected two DISTINCT lane hosts, got {seen}"
    # The literal single shared marker `data-grass-term="1"` must be gone.
    assert "1" not in seen


# ── POSITIVE/NEGATIVE: PER-LANE Save-refinement controls (Defect 2) ────────────

def test_each_lane_has_its_own_save_refinement_control():
    """POSITIVE: each terminal lane renders its OWN Save-refinement control keyed
    by lane (data-save-lane="research" and data-save-lane="plan")."""
    html = _select_grass_idea_html()
    els = _parse(html)
    saves = [d for t, d in els if d.get("data-save-lane")]
    save_lanes = sorted(d.get("data-save-lane") for d in saves)
    assert save_lanes == ["plan", "research"], \
        f"expected one per-lane Save control per lane, got {save_lanes}"
    # Two DISTINCT save controls (not one reused).
    assert len(saves) == 2 and saves[0] is not saves[1]
    # Each Save control is a .gsave button so existing styling/affordance applies.
    for d in saves:
        assert "gsave" in (d.get("class") or "").split()


def test_no_single_shared_save_control():
    """NEGATIVE: there must be NO lane-ambiguous shared/global Save control — every
    .gsave button is bound to a specific lane via data-save-lane (the old single
    global ``.gsave`` in the devbar with no lane is gone)."""
    html = _select_grass_idea_html()
    els = _parse(html)
    gsaves = [d for t, d in els if "gsave" in (d.get("class") or "").split()]
    # Every .gsave must declare a lane — none lane-ambiguous.
    assert gsaves, "expected per-lane .gsave Save controls"
    for d in gsaves:
        assert d.get("data-save-lane") in ("research", "plan"), \
            "a .gsave with no data-save-lane is a lane-ambiguous global save"
    # Exactly two (one per lane), never a third global one.
    assert len(gsaves) == 2, f"expected exactly two per-lane saves, got {len(gsaves)}"


# ── Playwright (DEV-ONLY): real two-terminal toggle behavior ───────────────────

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "gate_adapter", "handoff",
                "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

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
    pid = proj["id"]
    # Seed a grass idea so the workbench has something to select.
    import effort_history as eh
    idea = eh.add_idea(str(repo), pid, "Passive autonomous cooling loop",
                       notes="A natural-circulation decay-heat loop.")
    bundle = {"gui": gui, "pid": pid, "repo": repo,
              "idea_id": idea.get("job_id") or idea.get("id")}
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


@pytest.fixture
def server(gui_env):
    gui = gui_env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui_env, f"http://127.0.0.1:{port}", port
    finally:
        # Robust teardown: the Playwright browser/page (and thus its WS/SSE
        # client sockets) is already closed by the test's ``with
        # sync_playwright()`` block exiting BEFORE this finalizer runs. Give any
        # still-draining stream handler thread a brief grace, then shut the
        # server down GUARDED so a benign teardown race can't fail the test.
        time.sleep(0.1)
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_grass_two_terminals_toggle_in_browser(server):
    """Open the grass workbench, select the idea, click Research → its terminal
    host mounts; click Plan → a SEPARATE plan host mounts (two distinct hosts,
    two distinct session ids); collapse Research → ONLY research collapses while
    Plan + both sessions stay live. Screenshot → _devtest/wave3_grass_two_terminals.png.
    No JS console errors."""
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]

    import session_registry as reg
    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave3_grass_two_terminals.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")

        # Open the grass workbench panel (the grass lane tile → openGrassWorkbench()).
        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel', timeout=8000)
        # Select the idea (first idea row).
        pg.wait_for_selector('#grassPanel .gli', timeout=8000)
        pg.eval_on_selector('#grassPanel .gli', "e=>e.click()")
        pg.wait_for_selector('#grassPanel .gwork .gterm[data-lane="research"]',
                             timeout=8000)

        # Both terminals start collapsed.
        assert pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="research"]',
            "e=>e.classList.contains('collapsed')") is True
        assert pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="plan"]',
            "e=>e.classList.contains('collapsed')") is True

        # Click 🔬 Research → its host expands + a session binds.
        pg.click('#grassPanel button[data-dev="research"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"research\"] "
            "[data-grass-term]') && document.querySelector('#grassPanel "
            ".gterm[data-lane=\"research\"] [data-grass-term]')"
            ".getAttribute('data-session')", timeout=10000)
        assert pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="research"]',
            "e=>e.classList.contains('collapsed')") is False
        rsid = pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="research"] [data-grass-term]',
            "e=>e.getAttribute('data-session')")
        assert rsid, "research terminal did not bind a session"

        # Click 📐 Plan → a SEPARATE host expands + a DIFFERENT session binds.
        pg.click('#grassPanel button[data-dev="plan"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"plan\"] "
            "[data-grass-term]') && document.querySelector('#grassPanel "
            ".gterm[data-lane=\"plan\"] [data-grass-term]')"
            ".getAttribute('data-session')", timeout=10000)
        psid = pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="plan"] [data-grass-term]',
            "e=>e.getAttribute('data-session')")
        assert psid, "plan terminal did not bind a session"
        assert rsid != psid, \
            "research and plan must be DIFFERENT sessions (two concurrent dev sessions)"

        # Two distinct host ELEMENTS (not one swapped host).
        two = pg.eval_on_selector_all(
            '#grassPanel .gwork [data-grass-term]', "els=>els.length")
        assert two == 2, f"expected two distinct term hosts, got {two}"

        # Both research + plan registry sessions are live before the collapse.
        live = {r["session_id"] for r in reg.list_sessions(project_id=pid)
                if r.get("status") == "running"}
        assert rsid in live and psid in live, \
            "both dev sessions should be live before collapsing one"

        # Toggle Research CLOSED → only research collapses; plan stays expanded.
        pg.click('#grassPanel button[data-dev="research"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"research\"]')"
            ".classList.contains('collapsed')", timeout=6000)
        assert pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="plan"]',
            "e=>e.classList.contains('collapsed')") is False, \
            "collapsing Research must NOT collapse Plan"

        # Collapse does NOT kill: both sessions remain live in the registry.
        live2 = {r["session_id"] for r in reg.list_sessions(project_id=pid)
                 if r.get("status") == "running"}
        assert rsid in live2 and psid in live2, \
            "collapsing a terminal must NOT kill its (or the other's) session"

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists(), "screenshot not written"

    import terminal_session as ts
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass


@pytest.mark.skipif(not _have_git(), reason="git not on PATH")
def test_grass_save_refinement_per_lane_in_browser(server):
    """Defect-1 + Defect-2 coverage: open the workbench, Develop Research, click
    THAT lane's Save-refinement control, and assert (a) NO JS console error — this
    would have caught the ``panel is not defined`` ReferenceError that the prior
    code threw on every successful save — and (b) the idea's list-row ``data-status``
    flips to ``refined`` (and the workbench chip reads 'refined')."""
    pytest.importorskip("playwright.sync_api")
    bundle, base, _ = server
    pid = bundle["pid"]

    import session_registry as reg
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        page_errors = []
        pg.on("pageerror", lambda e: page_errors.append(str(e)))
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")

        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel .gli', timeout=8000)
        pg.eval_on_selector('#grassPanel .gli', "e=>e.click()")
        pg.wait_for_selector('#grassPanel .gwork .gterm[data-lane="research"]',
                             timeout=8000)

        # Develop Research → its session binds + its per-lane Save enables.
        pg.click('#grassPanel button[data-dev="research"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"research\"] "
            "[data-grass-term]') && document.querySelector('#grassPanel "
            ".gterm[data-lane=\"research\"] [data-grass-term]')"
            ".getAttribute('data-session')", timeout=10000)
        # The research lane's OWN Save control is now enabled.
        pg.wait_for_function(
            "(()=>{var b=document.querySelector('#grassPanel .gterm"
            "[data-lane=\"research\"] button[data-save-lane=\"research\"]');"
            "return b && !b.disabled;})()", timeout=8000)

        # Click research's Save-refinement, then wait for the refinement to land
        # (history row rendered) + the row status flip.
        pg.click('#grassPanel .gterm[data-lane="research"] '
                 'button[data-save-lane="research"]')
        pg.wait_for_function(
            "(()=>{var r=document.querySelector('#grassPanel .gli');"
            "return r && r.getAttribute('data-status')==='refined';})()",
            timeout=10000)

        # (a) No JS console error — the pre-fix `panel is not defined` would fire here.
        assert not errors, f"JS console errors on save: {errors}"
        assert not page_errors, f"uncaught page errors on save: {page_errors}"

        # (b) The list row + workbench chip both read 'refined'.
        row_status = pg.eval_on_selector(
            '#grassPanel .gli', "e=>e.getAttribute('data-status')")
        assert row_status == "refined", \
            f"idea list-row status should flip to refined, got {row_status}"
        chip = pg.eval_on_selector(
            '#grassPanel .gwork h3 .stchip', "e=>e.textContent")
        assert chip == "refined", f"workbench chip should read refined, got {chip}"
        b.close()

    import terminal_session as ts
    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
