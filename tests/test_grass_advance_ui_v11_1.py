"""v11.1 Wave 2 — Grass "Advance to Plan" opens on a CONVERSATION (Playwright).

DEV-ONLY (``pytest.importorskip("playwright.sync_api")``; SKIPs cleanly where
Playwright/Chromium is absent — never imported by product code).

The behavior under test (the failure John reported, now fixed): in the grass
workbench the user develops a RESEARCH dev session that is a CONVERSATION (content
appears in the terminal, NO file is written), then clicks "➜ Advance to Plan". The
contained grass PLAN terminal must OPEN (no "no materials" toast) and its
pasted-but-UNSENT prompt must NAME the snapshotted ``research/<sid>-transcript.md``.

DISCRIMINATING TOKEN: the transcript path ``research/<sid>-transcript.md`` appears
in the plan terminal's pasted prompt ONLY if the W1 snapshot + W2 advance worked.
Pre-W2 the empty/conversation advance refused → no plan terminal, no token.

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` + fake runner + temp git repo + tmp data +
tmp worktree base; a free port != 8777; ``ANCHOR_PROACTIVE_SUMMARY`` OFF. NEVER
binds ``:8777`` / touches real data / network.
"""
import importlib
import subprocess
import threading
import time
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()
_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"

#: A simulated MODEL greet line — writing it onto the stub PTY echoes it into the
#: read buffer, the "model greeted" signal the pending-paste flush requires.
GREET_LINE = "✓ Crucible loaded — what would you like to do?"

#: Simulated research CONVERSATION — written LIVE onto the research session's PTY
#: read buffer (no file, no record_effort), the exact conversation-only path.
TRANSCRIPT = (
    "\nResearcher: Which coolant loop maximizes thermal margin?\n"
    "Assistant: The molten-salt loop wins — a 40C transient tolerance with no\n"
    "scram and the simplest pump topology. Prototype the pump seal.\n"
)


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


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import terminal_session
    import session_registry
    import rnd_registry
    import pty_manager

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    pid = proj["id"]
    idea = effort_history.add_idea(str(repo), pid,
                                   "Passive autonomous cooling loop",
                                   notes="A natural-circulation decay-heat loop.")
    bundle = {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "eh": effort_history, "rnd": rnd_registry, "pty": pty_manager,
        "repo": repo, "pid": pid, "idea_id": idea.get("job_id") or idea.get("id"),
    }
    yield bundle
    try:
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


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


def test_grass_advance_conversation_opens_plan_in_browser(server):
    """Open the grass workbench, Develop Research, produce CONVERSATION content
    LIVE in its PTY buffer (no file), click "Advance to Plan" → the contained PLAN
    terminal OPENS (no "no materials" toast) and its pasted prompt shows the
    captured research/<sid>-transcript.md path (the discriminating token).
    Screenshot → _devtest/wave_v11_1_grass_advance.png. No JS console errors."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    pid, idea_id = env["pid"], env["idea_id"]
    ts, eh, reg, pty = env["ts"], env["eh"], env["reg"], env["pty"]

    # Pre-create the research dev session (the browser Develop click dedupes onto
    # the live one) and seed its PTY buffer with a CONVERSATION — write NO file,
    # NO record_effort. The discriminating token is the snapshot path the W1
    # keystone will write; it appears in the paste ONLY if the snapshot+advance ran.
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    pty.write(rsid, TRANSCRIPT)
    transcript_token = f"research/{rsid[:12]}-transcript.md"

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave_v11_1_grass_advance.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        dialogs = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        # A "no materials" toast would be an alert() dialog — capture + dismiss it
        # so a regression (refusal) is observable rather than hanging the test.
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")

        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel .gli', timeout=8000)
        pg.eval_on_selector('#grassPanel .gli', "e=>e.click()")
        pg.wait_for_selector('#grassPanel .gwork .gterm[data-lane="research"]',
                             timeout=8000)

        # Develop Research → binds the live (idea, 'research') dev session.
        pg.click('#grassPanel button[data-dev="research"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"research\"] "
            "[data-grass-term]') && document.querySelector('#grassPanel "
            ".gterm[data-lane=\"research\"] [data-grass-term]')"
            ".getAttribute('data-session')", timeout=10000)
        pg.wait_for_function(
            "(()=>{var b=document.querySelector('#grassPanel .gterm"
            "[data-lane=\"research\"] button[data-advance=\"research\"]');"
            "return b && !b.disabled;})()", timeout=8000)

        # Click Advance → the plan terminal opens + a plan dev session binds.
        # (No "no materials" alert must fire — checked after.)
        pg.click('#grassPanel .gterm[data-lane="research"] '
                 'button[data-advance="research"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"plan\"] "
            "[data-grass-term]') && document.querySelector('#grassPanel "
            ".gterm[data-lane=\"plan\"] [data-grass-term]')"
            ".getAttribute('data-session')", timeout=12000)
        # The plan terminal is OPEN (no refusal).
        assert pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="plan"]',
            "e=>e.classList.contains('collapsed')") is False, \
            "Advance must open the plan terminal (no refusal)"
        psid = pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="plan"] [data-grass-term]',
            "e=>e.getAttribute('data-session')")
        assert psid and psid != rsid, "plan dev session must be distinct"

        # No "no materials" toast was raised.
        assert not dialogs, f"an alert/toast fired on advance: {dialogs}"

        # Server truth: linked + grass_origin + the pending paste NAMES the
        # snapshotted transcript (the discriminating token).
        prec = reg.get_session(psid)
        assert prec["parent_session_id"] == rsid
        assert prec["grass_origin"] == idea_id
        assert prec["pending_paste"], "the plan session must carry a pending paste"
        assert transcript_token in prec["pending_paste"], \
            "the prompt must name the snapshotted transcript (W1+W2 token)"
        assert prec["paste_flushed"] is False

        # Drive the greet so the pending paste flushes UNSENT, then wait for the
        # transcript token to render in the plan terminal.
        pty.write(psid, GREET_LINE)
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"plan\"] "
            "[data-grass-term]').innerText.indexOf("
            + repr(transcript_token) + ") !== -1", timeout=12000)

        # RENDERED NEGATIVE: the paste is present but NOT auto-submitted.
        full = pty.read_since(psid, 0)["text"]
        assert transcript_token in full
        assert prec["pending_paste"] + "\n" not in full, \
            "the advance paste must NOT be auto-submitted"

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists(), "screenshot not written"

    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
