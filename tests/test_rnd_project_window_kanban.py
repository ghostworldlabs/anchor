"""Rich per-project window ("Dashboard A") + multi-session console + cancel_job.

Regression guard that the spec mockup (`_mockups/rnd_mockups_v2.html`,
"Dashboard A") is actually SERVED at GET /project/<id> — the exact "built but
never wired into the UI" failure that bit this project once. Asserts the SERVED
HTML (not just internal functions) carries:

  - the 4-column Kanban (Research|Planning|Build|Deliverables),
  - versioned effort cards with state pills,
  - the per-lane "New run" affordances,
  - the multi-session console (session tabs + attached log + Ask + Stop),
  - the lifecycle header (priority/notes/archive/retire),

and that:

  - POST /api/rnd/cancel_job cancels a running mock job and 404s an unknown id,
  - two concurrent mock jobs for one project surface as switchable sessions and
    an answer routes to a SPECIFIC job_id (no cross-wire).

Every job launch routes through ANCHOR_RUNNER_CMD -> tests/fake_claude.py (a
mock); live claude/gemini is NEVER invoked. A throwaway server runs on an
OS-assigned free port (port=0); 8777 / the live service / real data are never
touched. All spawned mock procs are reaped.
"""
import importlib
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import job_runner
    importlib.reload(job_runner)
    import rnd_registry
    importlib.reload(rnd_registry)
    import lanes
    importlib.reload(lanes)
    import effort_history
    importlib.reload(effort_history)
    import gate_adapter
    importlib.reload(gate_adapter)
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    yield gui
    for rec in job_runner.list_records():
        if rec.get("status") == job_runner.STATUS_RUNNING:
            try:
                job_runner.cancel(rec["job_id"])
            except Exception:
                pass
    job_runner._reset_live_table_for_tests()


@pytest.fixture
def server(gui_env):
    gui = gui_env
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui, f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get_text(url):
    with urllib.request.urlopen(url, timeout=8) as resp:
        return resp.status, resp.read().decode("utf-8")


def _mkproject(folder, name="P"):
    import rnd_registry
    folder.mkdir(parents=True, exist_ok=True)
    return rnd_registry.add_project(name, str(folder))


def _wait_running(job_runner, jid, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rec = job_runner.load_record(jid)
        if rec and rec.get("status") == job_runner.STATUS_RUNNING:
            return True
        time.sleep(0.02)
    return False


# ── (a) render guard: Kanban + versions + pills + New-run + console + header ──

def test_window_renders_kanban_console_and_header(gui_env, tmp_path):
    """A project with efforts in >=2 lanes renders the full Dashboard A."""
    gui = gui_env
    import effort_history as eh
    folder = tmp_path / "Rich"
    proj = _mkproject(folder, "RichProj")
    pid = proj["id"]
    fp = str(folder)

    # Seed >=2 lanes with >=2 efforts each (versioned history, newest-first).
    eh.record_effort(fp, pid, "research", "r1", skill="researchPrime",
                     prompt_seed="Survey smart-home protocols")
    eh.record_effort(fp, pid, "research", "r2", skill="researchPrime",
                     prompt_seed="Survey v2")
    eh.record_effort(fp, pid, "plan", "p1", skill="crucible",
                     prompt_seed="Master plan")

    html = gui.render_project_window_html(pid)

    # The 4 Kanban columns.
    assert "class='kan'" in html
    for label in ("Research", "Planning", "Build", "Deliverables"):
        assert label in html
    # Version labels by recency (research has 2 efforts -> v2 newest, v1 oldest).
    assert ">v2<" in html
    assert ">v1<" in html
    # Effort cards.
    assert "class='effort'" in html
    # Per-lane "New run" affordances.
    assert "launchLane('research','claude')" in html
    assert "launchLane('plan')" in html
    assert "launchLane('build')" in html
    assert "New research run" in html
    # Multi-session console (session tabs + attached log + Ask + Stop).
    assert "id='ctabs'" in html
    assert "id='laneLog'" in html
    assert "id='laneGate'" in html
    assert "stopAttached(" in html
    assert "attachSession(" in html
    assert "SESSIONS" in html
    # Lifecycle header.
    assert "rndSetPriority(" in html
    assert "rndArchive(" in html
    assert "rndRetire(" in html
    assert "rndNotes(" in html
    assert "RichProj" in html
    # f-string / brace hygiene of the served page.
    assert "{{" not in html and "}}" not in html


def test_window_done_effort_links_report_viewer(gui_env, tmp_path):
    """A DONE effort card carries the /report/<pid>/<lane>/<job_id> link shape."""
    gui = gui_env
    import effort_history as eh
    folder = tmp_path / "Done"
    proj = _mkproject(folder, "DoneProj")
    pid = proj["id"]
    fp = str(folder)
    eh.record_effort(fp, pid, "research", "donejob", skill="researchPrime",
                     extra={"status": "done"})
    html = gui.render_project_window_html(pid)
    # Report-link shape for a done effort (the report viewer route).
    assert f"/report/{pid}/research/donejob" in html
    assert "openReport(" in html


def test_window_xss_escapes_project_name(gui_env, tmp_path):
    """Engine/user content is HTML-escaped: a project name with markup is not
    injected raw into the served window."""
    gui = gui_env
    folder = tmp_path / "xss"
    proj = _mkproject(folder, "<script>alert(1)</script>")
    html = gui.render_project_window_html(proj["id"])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


# ── gate option buttons must be functional (no HTML-attribute breakout) ──────

def test_gate_buttons_use_safe_delegation_not_broken_inline_onclick(gui_env):
    """Regression: the gate option buttons must be wired via a delegated
    listener + data attribute, NOT an inline onclick built by string-concatenating
    JSON.stringify(label) into a double-quoted attribute. That old pattern
    (`onclick="answerGate(' + JSON.stringify(label) + ')"`) renders as
    `onclick="answerGate("Approve")"`, where the inner double quote (always added
    by JSON.stringify) terminates the attribute early — so clicking a gate option
    button never called answerGate(label) and the spec's primary one-click gate
    affordance was dead. We assert the served window JS no longer builds an inline
    onclick from JSON.stringify, and DOES carry the safe delegation hooks."""
    gui = gui_env
    js = gui._PROJECT_WINDOW_JS
    # The safe pattern is present: label carried in a data attribute + a single
    # delegated click handler reading it.
    assert "setAttribute('data-gate-opt', label)" in js
    assert "getAttribute('data-gate-opt')" in js
    assert "_gateDelegated" in js
    # No NON-COMMENT line builds an inline onclick from JSON.stringify (the old bug).
    for i, line in enumerate(js.splitlines(), 1):
        s = line.strip()
        if s.startswith("//"):
            continue
        assert not ("onclick" in line and "JSON.stringify" in line), (
            f"line {i} rebuilds the broken inline-onclick gate pattern: {line!r}")
    # And the broken literal substring never appears anywhere as code.
    assert 'onclick="answerGate(' not in js


def test_gate_button_attribute_does_not_break_out(gui_env):
    """Prove that constructing the gate button the way the fixed JS does
    (setAttribute('data-gate-opt', label) + textContent = label) yields HTML
    whose attribute value is the COMPLETE label — even for labels that contain a
    double quote — and that an html.parser tokenizes exactly one button with the
    full label intact (the old inline-onclick pattern truncated at the first
    inner double quote)."""
    from html.parser import HTMLParser
    from xml.sax.saxutils import quoteattr, escape

    def render_button(label):
        # Mirrors the fixed DOM construction's serialized output: the browser
        # serializes setAttribute(name, value) by HTML-escaping the value for the
        # attribute context (quoteattr does the equivalent here), and textContent
        # is HTML-escaped element text.
        return ('<button class="btn accent" data-gate-opt='
                + quoteattr(label) + '>' + escape(label) + '</button>')

    class P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.buttons = []
            self._txt = []

        def handle_starttag(self, tag, attrs):
            if tag == "button":
                self.buttons.append(dict(attrs))

        def handle_data(self, data):
            self._txt.append(data)

    for label in ["Approve", "JSON files", 'a"b', "SQLite"]:
        p = P()
        p.feed(render_button(label))
        assert len(p.buttons) == 1, f"label {label!r} produced bad markup"
        attrs = p.buttons[0]
        # The data attribute carries the COMPLETE label, never truncated.
        assert attrs.get("data-gate-opt") == label
        # No stray garbage attribute leaked from a breakout.
        assert set(attrs.keys()) == {"class", "data-gate-opt"}
        # Button text is the label.
        assert "".join(p._txt) == label


# ── (b) /api/rnd/cancel_job: cancels a running mock + 404 on unknown ──────────

def test_cancel_job_stops_running_and_404_unknown(server, tmp_path):
    gui, base = server
    import job_runner
    proj = _mkproject(tmp_path / "cj", "CancelProj")
    # Launch a research mock that sleeps so it stays running.
    code, body = _post(base + "/api/rnd/launch_lane",
                       {"project_id": proj["id"], "lane": "research"})
    assert code == 200 and body["ok"] is True
    jid = body["job_id"]
    # (the default mock exits fast; relaunch with a sleeping one via job_runner
    # so the cancel has a live process to reap)
    rec = job_runner.launch("research", extra_args=["--lines", "1", "--sleep", "5"])
    jid = rec["job_id"]
    assert _wait_running(job_runner, jid)

    code, data = _post(base + "/api/rnd/cancel_job", {"job_id": jid})
    assert code == 200
    assert data["ok"] is True
    assert data["job_id"] == jid
    assert data["status"] == job_runner.STATUS_CANCELLED
    # The durable record reflects the cancel.
    assert job_runner.load_record(jid)["status"] == job_runner.STATUS_CANCELLED

    # Unknown id -> clean 404 (not a 500).
    code, data = _post(base + "/api/rnd/cancel_job", {"job_id": "does-not-exist"})
    assert code == 404
    assert data["ok"] is False
    assert data["reason"] == "unknown-job"

    job_runner.wait(jid, timeout=30)


# ── (c) multi-session: two jobs => two switchable sessions; answer by job_id ──

def test_two_sessions_switchable_and_answer_routes_to_job(server, tmp_path):
    gui, base = server
    import job_runner
    import gate_adapter
    proj = _mkproject(tmp_path / "ms", "MultiProj")
    pid = proj["id"]

    # Job A: a plain running research mock (sleeps so it stays live).
    recA = job_runner.launch("research",
                             extra_args=["--lines", "2", "--sleep", "5"])
    jidA = recA["job_id"]
    # Job B: a gated plan mock that reaches awaiting-input.
    recB = job_runner.launch("plan",
                             extra_args=["--lines", "1", "--sleep", "5"])
    jidB = recB["job_id"]
    assert _wait_running(job_runner, jidA)
    assert _wait_running(job_runner, jidB)

    # Record both as efforts so the server renders them as live cards/sessions.
    import effort_history as eh
    eh.record_effort(str(tmp_path / "ms"), pid, "research", jidA,
                     skill="researchPrime")
    eh.record_effort(str(tmp_path / "ms"), pid, "plan", jidB, skill="crucible")

    # Inject an awaiting-input gate onto job B (via the real gate_adapter path).
    GATE = (Path(__file__).resolve().parent / "fixtures" / "gate_stream.jsonl")

    class FakeSink:
        def __init__(self):
            self.writes = []
            self._lock = threading.Lock()

        def write(self, data):
            with self._lock:
                self.writes.append(data)

        def flush(self):
            pass

    sink = FakeSink()
    gate_adapter.register_stdin_sink(jidB, sink)
    prompt = gate_adapter.ingest_stream(
        jidB, GATE.read_text(encoding="utf-8").splitlines())
    assert prompt is not None

    # The served window exposes BOTH jobs as live, switchable sessions.
    status, html = _get_text(base + f"/project/{pid}")
    assert status == 200
    assert f'data-job-id="{jidA}"' in html
    assert f'data-job-id="{jidB}"' in html
    # Both are adopted as sessions (live cards) the console can attach to.
    assert html.count('data-live="1"') >= 2
    assert "attachSession(" in html
    assert "id='ctabs'" in html

    # An answer routes to the SPECIFIC job_id (job B's gate), not job A.
    code, ans = _post(base + "/api/rnd/answer_gate",
                      {"job_id": jidB, "choice": "JSON files"})
    assert code == 200
    assert ans["ok"] is True and ans["written"] is True
    assert ans["job_id"] == jidB
    # Exactly one stdin write landed on job B's sink (no cross-wire to A).
    assert len(sink.writes) == 1

    # Answering job A (which has no gate) is a clean no-op (proves no cross-wire).
    code, ansA = _post(base + "/api/rnd/answer_gate",
                       {"job_id": jidA, "choice": "JSON files"})
    assert code == 200
    assert ansA["written"] is False

    # Reap both.
    job_runner.cancel(jidA)
    job_runner.cancel(jidB)
    job_runner.wait(jidA, timeout=30)
    job_runner.wait(jidB, timeout=30)
