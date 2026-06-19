"""v10 Wave 5 — Grass research→plan live handoff (within the workbench).

From a grass RESEARCH dev session, the user can push research → plan using the
SAME paste-NOT-submit seeded handoff as the project-level advance (Wave 1/2),
staying INSIDE the grass workbench, linked. ``advance_grass_research_to_plan``:

  * resolves the idea's CONTAINED ``(idea, 'research')`` dev session,
  * persists its produced docs + builds the research→plan prompt (Crucible + the
    REAL research doc paths + "read these first, then plan") via
    ``handoff.build_next_stage_prompt``,
  * starts (or FOCUSES) the CONTAINED ``(idea, 'plan')`` dev session with that
    prompt delivered as a v10 PENDING PASTE (held UNSENT until Enter), LINKED to
    the research dev session (``parent_session_id`` + shared ``chain_id``) and
    carrying ``grass_origin == idea_id``,
  * records the ``research->plan`` stage edge.

Covers the Wave-5 Given/When/Then:
  (a) advance a research dev session with material → a grass PLAN dev session
      opens; its ``pending_paste`` == the generated prompt (research doc paths +
      Crucible, UNSENT/``paste_flushed`` False); it is linked + carries
      ``grass_origin``; it is CONTAINED (GRASS_DEV_LABEL_PREFIX → excluded from
      the board lane columns + top strip);
  (b) negative: advancing with NO research material → honest result (reason), NO
      plan dev session minted, no fabricated prompt;
  (c) re-advance FOCUSES the SAME plan dev session (dedupe) — no second minted.

Plus the rendered-DOM positive+negative for the "Advance to Plan →" control and a
DEV-ONLY Playwright leg.

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` + the fake runner + a temp git repo + a tmp
data dir + tmp worktree base. NEVER binds ``:8777``; NEVER a worktree off the real
``C:\\dev\\Anchor`` repo; no network.
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

#: A simulated MODEL greet line — writing it onto the stub PTY echoes it into the
#: read buffer, which is the "model actually greeted" signal the pending-paste
#: flush requires.
GREET_LINE = "✓ Crucible loaded — what would you like to do?"


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
    """Tmp data dir + worktree base + stub PTY + fake runner + a temp git repo +
    a registered project + a seeded grass idea. The full stack is reloaded against
    the isolated env so every worktree is off the TEMP repo (never C:\\dev\\Anchor)."""
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
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "handoff", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import effort_history
    import handoff
    import terminal_session
    import session_registry
    import rnd_registry

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
        "handoff": handoff, "eh": effort_history, "rnd": rnd_registry,
        "repo": repo, "pid": pid, "wbase": wbase, "data": data,
        "idea_id": idea.get("job_id") or idea.get("id"),
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _produce_research_doc(reg, rsid, rel="research/run-1/REPORT.md"):
    """Author a REAL research report doc LIVE in the research dev session's
    worktree (uncommitted to main) so the advance's persist resolves it."""
    rec = reg.get_session(rsid)
    wt = Path(rec["worktree_path"])
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Cooling report\n## Findings\nNatural circulation adequate.\n",
                 encoding="utf-8")
    return rel


# ════════════════════════════════════════════════════════════════════════════
# (a) advance with material → linked, contained grass PLAN dev session + pending
# ════════════════════════════════════════════════════════════════════════════

def test_advance_grass_research_to_plan_opens_linked_contained_pending(env):
    ts, eh, reg, repo, pid, idea_id = (
        env["ts"], env["eh"], env["reg"], env["repo"], env["pid"],
        env["idea_id"])

    # Develop the contained (idea, 'research') dev session + produce a report doc.
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    rel = _produce_research_doc(reg, rsid)

    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is True, out
    assert out["research_session_id"] == rsid
    prec = out["session"]
    psid = prec["session_id"]

    # The plan dev session is in the PLAN lane and a DISTINCT session.
    assert prec["lane"] == "plan"
    assert psid != rsid

    # LINKED: parent + shared chain.
    assert prec["parent_session_id"] == rsid
    assert prec["chain_id"] == reg.chain_for(rsid)

    # grass_origin rides the chain back to the idea.
    full = reg.get_session(psid)
    assert full["grass_origin"] == idea_id

    # pending_paste == the generated Crucible prompt (real research doc path),
    # delivered UNSENT (paste_flushed False initially); phase-1 greet still fired.
    paste = full["pending_paste"]
    assert paste, "the plan dev session must carry a pending paste"
    assert "Crucible" in paste
    assert rel in paste, "the prompt must name the REAL research doc path"
    assert "plan" in paste.lower()
    assert not paste.endswith("\n"), "a reviewable paste must not end in newline"
    assert full["paste_flushed"] is False
    assert full["seeded"] is True
    assert full["seed_text"].endswith("\n")

    # CONTAINED: the GRASS_DEV_LABEL_PREFIX label → excluded from the board +
    # top strip (the board bridge predicate recognizes it).
    assert full["label"].startswith(eh.GRASS_DEV_LABEL_PREFIX)
    assert eh.is_grass_dev_label(full["label"]) is True

    # The (idea, 'plan') -> session map is persisted on the idea record (dedupe).
    idea_rec = eh.get_grass_idea(repo, pid, idea_id)
    assert eh._grass_dev_sessions(idea_rec).get("plan") == psid

    # The research->plan stage edge was recorded (rescan-durable).
    links = env["handoff"].list_stage_links(repo, pid)
    assert any(l["from_session_id"] == rsid and l["to_session_id"] == psid
               and l["kind"] == "research->plan" for l in links)

    # After the greet, the pending paste flushes UNSENT (no trailing newline).
    import pty_manager
    pty_manager.write(psid, GREET_LINE)
    ts.read_since(psid, 0)
    buf = pty_manager.read_since(psid, 0)["text"]
    assert paste in buf
    assert paste + "\n" not in buf, "paste must NOT auto-submit"
    assert reg.get_session(psid)["paste_flushed"] is True

    ts.kill(psid)
    ts.kill(rsid)


# ════════════════════════════════════════════════════════════════════════════
# (b) negative: no research material → honest, NO plan session minted
# ════════════════════════════════════════════════════════════════════════════

def test_advance_grass_no_research_session_is_honest(env):
    """No research dev session at all → honest reason, nothing minted."""
    eh, reg, pid, idea_id = env["eh"], env["reg"], env["pid"], env["idea_id"]
    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is False
    assert out["session"] is None
    assert out["reason"] == "no-research-session"
    # No plan dev session minted.
    plans = [s for s in reg.list_sessions(project_id=pid)
             if s.get("lane") == "plan"]
    assert not plans


def test_advance_grass_no_research_material_is_honest(env):
    """A research dev session that produced NO docs → honest 'no-research-
    material' (no fabricated prompt), and NO plan dev session minted."""
    ts, eh, reg, pid, idea_id = (
        env["ts"], env["eh"], env["reg"], env["pid"], env["idea_id"])
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    # Deliberately produce NOTHING in the research worktree.

    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is False
    assert out["session"] is None
    assert out["reason"] == "no-research-material"
    # No plan dev session minted (no fabrication).
    plans = [s for s in reg.list_sessions(project_id=pid)
             if s.get("lane") == "plan"]
    assert not plans
    # The idea record was NOT stamped with a plan dev session.
    idea_rec = eh.get_grass_idea(env["repo"], pid, idea_id)
    assert "plan" not in eh._grass_dev_sessions(idea_rec)

    ts.kill(rsid)


# ════════════════════════════════════════════════════════════════════════════
# (c) re-advance FOCUSES the same plan dev session (dedupe) — no second minted
# ════════════════════════════════════════════════════════════════════════════

def test_re_advance_focuses_same_plan_session_no_second(env):
    ts, eh, reg, pid, idea_id = (
        env["ts"], env["eh"], env["reg"], env["pid"], env["idea_id"])
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    _produce_research_doc(reg, rsid)

    out1 = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out1["ok"] is True
    psid1 = out1["session"]["session_id"]

    out2 = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out2["ok"] is True
    psid2 = out2["session"]["session_id"]
    assert psid2 == psid1, "re-advance must focus the SAME plan dev session"
    assert out2["reason"] == "focused-existing"

    # Exactly ONE plan session in the registry (no second minted).
    plans = [s for s in reg.list_sessions(project_id=pid)
             if s.get("lane") == "plan"]
    assert len(plans) == 1

    ts.kill(psid1)
    ts.kill(rsid)


# ════════════════════════════════════════════════════════════════════════════
# (d) DEFECT 1 — develop-PLAN-FIRST → advance must still DELIVER the handoff
#     onto the pre-existing BARE plan dev session (non-vacuous: FAILS pre-fix).
# ════════════════════════════════════════════════════════════════════════════

def test_develop_plan_first_then_advance_delivers_handoff(env):
    """A user who clicks "Plan"/Develop FIRST mints a BARE (idea, 'plan') dev
    session (seeded with the idea text, ``pending_paste == ''``,
    ``paste_flushed`` False). A subsequent Advance hits the focus-existing branch
    — and MUST still deliver the generated research→plan handoff prompt onto that
    bare session (queue it as a fresh pending paste, UNSENT). Pre-fix the focus
    branch silently returned the bare session and the handoff was DROPPED, so this
    assertion FAILS against the pre-fix code (non-vacuous)."""
    ts, eh, reg, repo, pid, idea_id = (
        env["ts"], env["eh"], env["reg"], env["repo"], env["pid"],
        env["idea_id"])

    # Research dev session + a real research doc (so the advance has material).
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    rel = _produce_research_doc(reg, rsid)

    # Develop PLAN FIRST → a BARE plan dev session, NO handoff yet.
    prec0 = eh.develop_grass_idea(pid, idea_id, "plan", backend="claude")
    psid = prec0["session_id"]
    bare = reg.get_session(psid)
    assert (bare.get("pending_paste") or "") == "", \
        "the develop-first plan session must start BARE (no handoff)"
    assert bare.get("paste_flushed") is False

    # Now Advance. It focuses the SAME plan session (dedupe) AND delivers the
    # handoff as a fresh pending paste.
    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is True
    assert out["reason"] == "focused-existing"
    assert out["session"]["session_id"] == psid, "must FOCUS the same plan session"
    assert out.get("paste_delivered") is True, \
        "advance onto a bare plan session must DELIVER the handoff (DEFECT 1)"

    # The bare plan session now carries the REAL research→plan prompt, UNSENT.
    full = reg.get_session(psid)
    paste = full["pending_paste"]
    assert paste, "the handoff must be delivered onto the bare plan session"
    assert "Crucible" in paste
    assert rel in paste, "the delivered prompt must name the REAL research doc path"
    assert not paste.endswith("\n"), "a reviewable paste must not auto-submit"
    assert full["paste_flushed"] is False

    # Still EXACTLY ONE plan session (no second minted).
    plans = [s for s in reg.list_sessions(project_id=pid)
             if s.get("lane") == "plan"]
    assert len(plans) == 1

    # The session already greeted (develop seeds + greets) — so on the next read
    # the queued paste flushes UNSENT into the PTY.
    import pty_manager
    pty_manager.write(psid, GREET_LINE)
    ts.read_since(psid, 0)
    buf = pty_manager.read_since(psid, 0)["text"]
    assert paste in buf
    assert paste + "\n" not in buf, "delivered paste must NOT auto-submit"
    assert reg.get_session(psid)["paste_flushed"] is True

    ts.kill(psid)
    ts.kill(rsid)


def test_re_advance_does_not_double_deliver_paste(env):
    """advance→advance (re-advance) must NOT deliver a SECOND paste. The first
    advance mints the plan session WITH the handoff (pending). A second advance
    focuses it and — because it already carries a pending (or flushed) handoff —
    delivers NOTHING (``paste_delivered`` False), so exactly ONE handoff lands."""
    ts, eh, reg, pid, idea_id = (
        env["ts"], env["eh"], env["reg"], env["pid"], env["idea_id"])
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    _produce_research_doc(reg, rsid)

    out1 = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out1["ok"] is True and out1["reason"] == "advanced"
    psid = out1["session"]["session_id"]
    assert out1.get("paste_delivered") is True
    first_paste = reg.get_session(psid)["pending_paste"]
    assert first_paste, "the first advance must deliver a handoff"

    # PRE-FLUSH re-advance: the pending paste is still set → no second delivery.
    out2 = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out2["ok"] is True and out2["reason"] == "focused-existing"
    assert out2["session"]["session_id"] == psid
    assert out2.get("paste_delivered") is False, \
        "re-advance must NOT double-deliver a paste"
    assert reg.get_session(psid)["pending_paste"] == first_paste, \
        "the pending paste must be UNCHANGED by a re-advance"

    # POST-FLUSH re-advance: drive the greet so the paste flushes, then re-advance
    # — a session that already RECEIVED+flushed a handoff must not get a second.
    import pty_manager
    pty_manager.write(psid, GREET_LINE)
    ts.read_since(psid, 0)
    assert reg.get_session(psid)["paste_flushed"] is True
    out3 = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out3["ok"] is True and out3["reason"] == "focused-existing"
    assert out3.get("paste_delivered") is False, \
        "re-advance after flush must NOT queue a second paste"
    assert (reg.get_session(psid)["pending_paste"] or "") == "", \
        "no new pending paste after a flushed handoff"

    ts.kill(psid)
    ts.kill(rsid)


# ════════════════════════════════════════════════════════════════════════════
# Rendered-DOM positive + negative for the "Advance to Plan →" control
# ════════════════════════════════════════════════════════════════════════════

def _select_grass_idea_html():
    """Reconstruct the static markup selectGrassIdea() emits (join its single-
    quoted HTML literals) — the test convention from test_grass_two_terminals_v10."""
    import anchor_gui
    js = anchor_gui._PROJECT_WINDOW_JS
    m = re.search(r"function selectGrassIdea\(ideaId\)\s*\{([\s\S]*?)\n\}\n", js)
    assert m, "selectGrassIdea not found in _PROJECT_WINDOW_JS"
    body = m.group(1)
    hm = re.search(r"var html = ''([\s\S]*?);\n\s*work\.innerHTML = html;", body)
    assert hm, "selectGrassIdea html template not found"
    tmpl = hm.group(1)
    lits = re.findall(r"'((?:\\.|[^'\\])*)'", tmpl)
    return "".join(s.replace("\\'", "'") for s in lits)


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


def test_advance_to_plan_control_renders_on_research_lane_only():
    """POSITIVE: exactly ONE 'Advance to Plan' control, in the RESEARCH terminal
    bar (data-advance="research"), a .gadvance button."""
    els = _parse(_select_grass_idea_html())
    advs = [d for t, d in els if d.get("data-advance")]
    assert len(advs) == 1, f"expected exactly one Advance control, got {len(advs)}"
    assert advs[0].get("data-advance") == "research"
    assert "gadvance" in (advs[0].get("class") or "").split()


def test_no_advance_control_on_plan_lane():
    """NEGATIVE: there is NO 'Advance to Plan' control bound to the plan lane —
    only the research terminal carries it (you advance FROM research, not plan)."""
    els = _parse(_select_grass_idea_html())
    advs = [d for t, d in els if d.get("data-advance")]
    assert all(d.get("data-advance") != "plan" for d in advs), \
        "the plan terminal must NOT carry an Advance-to-Plan control"


def test_advance_helper_and_endpoint_wired_in_js():
    """The JS defines advanceGrassToPlan + wires the control to it, and POSTs the
    grass_advance endpoint; it delivers the prompt as a PENDING PASTE (flashes the
    unsent hint) and does NOT auto-submit (no term_input in its body)."""
    import anchor_gui
    js = anchor_gui._PROJECT_WINDOW_JS
    assert "async function advanceGrassToPlan(" in js
    assert "/api/rnd/grass_advance" in js
    assert "advanceGrassToPlan(ideaId)" in js, "the control must call the helper"
    m = re.search(r"async function advanceGrassToPlan\(([\s\S]*?)\n\}", js)
    assert m, "advanceGrassToPlan body not found"
    advbody = m.group(1)
    assert "_flashPendingPasteHint" in advbody, \
        "advance must flash the unsent pending-paste hint"
    assert "term_input" not in advbody, \
        "advance must NOT auto-submit the prompt (it is a pending paste)"


# ════════════════════════════════════════════════════════════════════════════
# Playwright (DEV-ONLY): real grass advance → plan terminal opens with the paste
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


def test_grass_advance_to_plan_in_browser(server):
    """Open the grass workbench, Develop Research, produce a research doc, click
    'Advance to Plan →' → the PLAN terminal opens and the PASTED prompt (a token
    that appears ONLY in the paste — the REAL research doc path) is visible in the
    plan terminal AND NOT auto-submitted. Screenshot → _devtest/wave5_grass_advance.png.
    No JS console errors."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    pid, idea_id = env["pid"], env["idea_id"]
    ts, eh, reg = env["ts"], env["eh"], env["reg"]

    # Pre-create the research dev session + produce a research doc so the advance
    # has REAL material. The browser flow then advances from it.
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    rel = _produce_research_doc(reg, rsid)
    # The unique paste-only token: the real research doc path. It is NOT in the
    # echoed phase-1 load+greet seed (that names the skill, not the doc path).
    paste_token = rel

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave5_grass_advance.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")

        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel .gli', timeout=8000)
        pg.eval_on_selector('#grassPanel .gli', "e=>e.click()")
        pg.wait_for_selector('#grassPanel .gwork .gterm[data-lane="research"]',
                             timeout=8000)

        # Develop Research → its dev session binds (re-uses the live one created
        # above; the backend dedupes on the live (idea, 'research') session).
        pg.click('#grassPanel button[data-dev="research"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"research\"] "
            "[data-grass-term]') && document.querySelector('#grassPanel "
            ".gterm[data-lane=\"research\"] [data-grass-term]')"
            ".getAttribute('data-session')", timeout=10000)
        # The research lane's Advance-to-Plan control is now enabled.
        pg.wait_for_function(
            "(()=>{var b=document.querySelector('#grassPanel .gterm"
            "[data-lane=\"research\"] button[data-advance=\"research\"]');"
            "return b && !b.disabled;})()", timeout=8000)

        # Click Advance → the plan terminal opens + a plan dev session binds.
        pg.click('#grassPanel .gterm[data-lane="research"] '
                 'button[data-advance="research"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"plan\"] "
            "[data-grass-term]') && document.querySelector('#grassPanel "
            ".gterm[data-lane=\"plan\"] [data-grass-term]')"
            ".getAttribute('data-session')", timeout=12000)
        # The plan terminal is OPEN (not collapsed).
        assert pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="plan"]',
            "e=>e.classList.contains('collapsed')") is False, \
            "Advance must open the plan terminal"
        psid = pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="plan"] [data-grass-term]',
            "e=>e.getAttribute('data-session')")
        assert psid and psid != rsid, "plan dev session must be a distinct session"

        # The plan dev session is linked + carries grass_origin (server truth).
        prec = reg.get_session(psid)
        assert prec["parent_session_id"] == rsid
        assert prec["grass_origin"] == idea_id
        assert prec["pending_paste"], "the plan session must carry a pending paste"
        assert paste_token in prec["pending_paste"]
        assert prec["paste_flushed"] is False

        # Drive the greet so the pending paste flushes UNSENT into the PTY, then
        # wait for the paste-only token to render in the plan terminal.
        import pty_manager
        pty_manager.write(psid, GREET_LINE)
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"plan\"] "
            "[data-grass-term]').innerText.indexOf("
            + repr(paste_token) + ") !== -1", timeout=12000)

        # RENDERED NEGATIVE: the paste is present but NOT auto-submitted — the
        # buffer contains the paste WITHOUT a trailing submitting newline.
        full = pty_manager.read_since(psid, 0)["text"]
        assert paste_token in full
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


# ════════════════════════════════════════════════════════════════════════════
# DEFECT 2 — grass-dev sessions must NOT leak onto the top strip.
# ════════════════════════════════════════════════════════════════════════════

def test_term_sessions_projection_excludes_grass_dev(env):
    """SERVER-SIDE (fast, no browser): after Advance, the project carries BOTH a
    grass RESEARCH and a grass PLAN dev session (GRASS_DEV_LABEL_PREFIX). The
    /api/rnd/term_sessions projection — which the top-strip repopulate() reads —
    must EXCLUDE every grass-dev session (they are mounted by session id directly
    in the workbench pane, never via the top strip). Pre-fix the projection
    returned them and they leaked onto #sessionBar on reload."""
    import json
    import urllib.request
    gui, ts, eh, reg, pid, idea_id = (
        env["gui"], env["ts"], env["eh"], env["reg"], env["pid"],
        env["idea_id"])

    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    _produce_research_doc(reg, rsid)
    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is True
    psid = out["session"]["session_id"]

    # Both grass-dev sessions exist in the registry...
    all_ids = {s["session_id"] for s in reg.list_sessions(project_id=pid)}
    assert rsid in all_ids and psid in all_ids

    # ...but the term_sessions projection (the top-strip source) excludes them.
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = ("http://127.0.0.1:%d/api/rnd/term_sessions?project_id=%s"
               % (port, pid))
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)

    assert data["ok"] is True
    proj_ids = {s["session_id"] for s in data["sessions"]}
    assert rsid not in proj_ids, "grass RESEARCH dev session leaked into projection"
    assert psid not in proj_ids, "grass PLAN dev session leaked into projection"
    # And the projection stays SAFE (never worktree_path/branch).
    for s in data["sessions"]:
        assert "worktree_path" not in s and "branch" not in s

    ts.kill(psid)
    ts.kill(rsid)


def test_repopulate_js_skips_grass_dev_before_managed():
    """The repopulate() JS guards grass-dev sessions out of the top strip BEFORE
    they enter MANAGED/FINISHED — the _isGrassDevLabel(s.label) skip sits ahead of
    the _KILLED/MANAGED bookkeeping, and the prefix is injected from the Python
    constant so the JS can't drift. (DOM/source assertion — the belt-and-braces
    second line behind the server-side projection filter.)"""
    import anchor_gui
    js = anchor_gui._PROJECT_WINDOW_JS
    assert "function _isGrassDevLabel(" in js
    m = re.search(r"async function repopulate\(\)\s*\{([\s\S]*?)\n\}\n", js)
    assert m, "repopulate not found"
    body = m.group(1)
    skip_at = body.find("_isGrassDevLabel(s.label)")
    managed_at = body.find("MANAGED[s.session_id] =")
    assert skip_at != -1, "repopulate must guard grass-dev sessions"
    assert managed_at != -1
    assert skip_at < managed_at, \
        "the grass-dev skip must precede adding to MANAGED"
    # The prefix is injected from the Python constant (no hard-coded drift).
    assert anchor_gui._eh.GRASS_DEV_LABEL_PREFIX == "[grass-dev] "


def test_grass_dev_not_on_top_strip_after_reload_in_browser(server):
    """DEFECT 2 (real Chromium): after Develop Research + Advance to Plan, RELOAD
    the page (repopulate() fires on load). The top strip (#sessionBar) must contain
    NO grass-dev chip — neither the grass research nor the grass plan dev session
    leaks onto the active strip — WHILE the grass workbench plan terminal still
    mounts (by session id). Refreshes _devtest/wave5_grass_advance.png."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    pid, idea_id = env["pid"], env["idea_id"]
    ts, eh, reg = env["ts"], env["eh"], env["reg"]

    # Build the two contained grass-dev sessions via the real advance path.
    rrec = eh.develop_grass_idea(pid, idea_id, "research", backend="claude")
    rsid = rrec["session_id"]
    _produce_research_doc(reg, rsid)
    out = eh.advance_grass_research_to_plan(pid, idea_id)
    assert out["ok"] is True
    psid = out["session"]["session_id"]
    grass_dev_ids = {rsid, psid}

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave5_grass_advance.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        # Load the project window — repopulate() runs on load and reads
        # /api/rnd/term_sessions to build the top strip.
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        # Give the on-load repopulate() a beat to (not) populate #sessionBar.
        # An EMPTY sessionBar is hidden by CSS — so wait for it ATTACHED (not
        # visible) and assert it carries no grass-dev chip.
        pg.wait_for_selector("#sessionBar", state="attached", timeout=8000)
        pg.wait_for_timeout(800)

        # The top strip must carry NO grass-dev chip (neither dev session id).
        chip_sessions = pg.eval_on_selector_all(
            "#sessionBar [data-session]",
            "els => els.map(e => e.getAttribute('data-session'))")
        leaked = [c for c in chip_sessions if c in grass_dev_ids]
        assert not leaked, f"grass-dev sessions leaked onto the top strip: {leaked}"

        # The grass workbench's OWN plan terminal still mounts (by session id).
        pg.wait_for_selector('[data-grass-tile="1"]', timeout=8000)
        pg.click('[data-grass-tile="1"]')
        pg.wait_for_selector('#grassPanel .gli', timeout=8000)
        pg.eval_on_selector('#grassPanel .gli', "e=>e.click()")
        pg.wait_for_selector('#grassPanel .gwork .gterm[data-lane="plan"]',
                             timeout=8000)
        # Re-open the plan dev terminal (it binds to the live plan dev session).
        pg.click('#grassPanel button[data-dev="plan"]')
        pg.wait_for_function(
            "document.querySelector('#grassPanel .gterm[data-lane=\"plan\"] "
            "[data-grass-term]') && document.querySelector('#grassPanel "
            ".gterm[data-lane=\"plan\"] [data-grass-term]')"
            ".getAttribute('data-session')", timeout=10000)
        bound = pg.eval_on_selector(
            '#grassPanel .gterm[data-lane="plan"] [data-grass-term]',
            "e=>e.getAttribute('data-session')")
        assert bound == psid, "the workbench plan terminal must mount its dev session"

        # The top strip STILL has no grass-dev chip after the workbench mount.
        chip_sessions2 = pg.eval_on_selector_all(
            "#sessionBar [data-session]",
            "els => els.map(e => e.getAttribute('data-session'))")
        assert not [c for c in chip_sessions2 if c in grass_dev_ids], \
            "grass-dev still must not appear on the top strip after workbench mount"

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists(), "screenshot not written"

    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass
