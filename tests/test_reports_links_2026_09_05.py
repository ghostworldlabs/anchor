"""Every report is a link — in the plan outline and in the deliverables register (John, 2026-09-05).

The gate file for planning/reports-links-2026-09-05. Wave 1: the register
understands contained Anchor routes (/report/…, /artifact/…) and run: markers,
and both render surfaces (the deliverables tile + the plan-outline step
expansion, via the ONE delivRow renderer; cockpit loadDeliv) read the same
classified rows. Hostile Where cells NEVER classify (route None, openable
False — they render as text); a run: cell stores the literal command string,
never parsed, never evaluated. Documents without routes or run: parse
byte-identically to before.

Wave 2 (STUB GATE): a finished run registers itself — ONE registrar module
(``deliverables_register``: register/effort_dir_for/where_for/active_step;
idempotent on (what, where), WRITE_LOCK + unique-temp + os.replace, header
minted on a fresh dir, never raises) and three one-line hooks
(gandalf.run_gandalf ok-only · job_runner._finalize STATUS_DONE research/plan
· commission_session.finish_run PRODUCED, human-facing doc roles only), each
journaling ``{register: written|dup|reason}`` on the existing
deliverable-pinned event. Failed or cancelled runs never register. Fully
stubbed (runner stubs + temp project folders) — never live claude / :8777.
"""
import importlib
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402

import deliverables_register as dreg  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "steward_cockpit" / "static"
AGENTIC_STUB = (Path(__file__).resolve().parent
                / "stub_gandalf_agentic.py").as_posix()


def _register(td, rows):
    """Write a DELIVERABLES.md per the header contract | What | Where | Date | Step |."""
    Path(td, "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n"
        + "".join("| %s | %s | 2026-09-05 | %s |\n" % r for r in rows),
        encoding="utf-8")


def test_register_reader_exists_and_file_rows_stay_contained():
    td = tempfile.mkdtemp(prefix="reports-links-seed-")
    Path(td, "DELIVERABLES.md").write_text(
        "| What | Where | Date |\n|---|---|---|\n| outside | `../secret.md` | 2026-09-05 |\n", encoding="utf-8")
    got = campaign.read_deliverables(td)
    assert got["exists"] is True
    it = got["items"][0]
    assert it["openable"] is False      # containment: outside the effort, never a link
    # wave 1: every item carries route/run keys, None when absent
    assert it["route"] is None
    assert it["run"] is None


def test_report_and_artifact_routes_are_openable():
    td = tempfile.mkdtemp(prefix="reports-links-routes-")
    _register(td, [
        ("Gandalf read", "`/artifact/pid-1?path=gandalf/run-1/report.md`", ""),
        ("research run", "/report/pid-1/research/job-1", "2"),
    ])
    items = campaign.read_deliverables(td)["items"]
    art = items[0]
    assert art["route"] == "/artifact/pid-1?path=gandalf/run-1/report.md"
    assert art["path"] is None
    assert art["openable"] is True
    assert art["run"] is None
    rep = items[1]
    assert rep["route"] == "/report/pid-1/research/job-1"
    assert rep["path"] is None
    assert rep["openable"] is True
    assert rep["step"] == "2"      # the outline keys the row under step 2


HOSTILE_WHERE = [
    "/artifact/pid-1?path=../../x",
    "/artifact/pid-1?path=C:/x",
    "http://evil",
    "//evil",
    "../outside.md",
    "/report/pid-1/../x",
]


def test_hostile_where_cells_never_classify_stub_gate():
    """STUB GATE (wave 1, negative containment): every hostile Where cell yields
    route None and openable False — it renders as TEXT in the tile, the plan
    outline and loadDeliv, never as a link."""
    td = tempfile.mkdtemp(prefix="reports-links-hostile-")
    _register(td, [("h%d" % i, w, "") for i, w in enumerate(HOSTILE_WHERE)])
    items = campaign.read_deliverables(td)["items"]
    assert len(items) == len(HOSTILE_WHERE)
    for w, it in zip(HOSTILE_WHERE, items):
        assert it["route"] is None, w
        assert it["openable"] is False, w
    for w in HOSTILE_WHERE:
        assert campaign.classify_route(w) is None, w


def test_run_marker_is_the_literal_command_and_the_document_keeps_its_link():
    td = tempfile.mkdtemp(prefix="reports-links-run-")
    Path(td, "notes.md").write_text("hi", encoding="utf-8")
    _register(td, [
        ("both", "`notes.md` run: python -c \"print('hi')\"", ""),
        ("hostile run", "run: <script>alert(1)</script>", ""),
    ])
    items = campaign.read_deliverables(td)["items"]
    both = items[0]
    # the exact command string — no shell parsing, no evaluation
    assert both["run"] == "python -c \"print('hi')\""
    # the document's open target is unchanged beside the run: marker
    assert both["path"] == "notes.md"
    assert both["openable"] is True
    host = items[1]
    assert host["run"] == "<script>alert(1)</script>"   # literal, inert string
    assert host["route"] is None
    assert host["openable"] is False


def test_renderers_have_the_route_branch_and_never_innerhtml():
    """Source-level (jsdom-free): delivRow carries the route anchor branch
    (target _blank, rel noopener, page token appended), stepDelivLine reuses
    delivRow (one renderer, both places), loadDeliv carries the MATCHING
    anchor branch labelled with the deliverable's name — NEVER a
    window.open(it.route): the cockpit shim rewrites window.open("/report…")
    to /steward/report…, which serve_page_doc 404s (wave-1 amendment,
    2026-09-05) — and register content never goes through innerHTML."""
    js = (STATIC / "shared.js").read_text(encoding="utf-8")
    deliv = js.split("function delivRow(it)")[1].split("function actLabel")[0]
    assert "it.route" in deliv
    assert 'a.target = "_blank"' in deliv
    assert 'a.rel = "noopener"' in deliv
    assert "encodeURIComponent(window.STEWARD_TOKEN)" in deliv
    assert "innerHTML" not in deliv
    step = js.split("function stepDelivLine(it)")[1].split("function paintStepsList")[0]
    assert "delivRow(it)" in step     # the outline reuses the ONE renderer
    assert "innerHTML" not in step
    html = (STATIC / "cockpit.html").read_text(encoding="utf-8")
    ld = html.split("async function loadDeliv()")[1].split("async function loadFiles()")[0]
    assert "it.route" in ld
    assert "window.open(it.route" not in ld   # a route NEVER goes through the shim
    assert "fn.href = it.route" in ld         # the anchor branch instead
    assert 'fn.target = "_blank"' in ld
    assert 'fn.rel = "noopener"' in ld
    assert '"• " + it.what' in ld             # the tile label is the NAME
    assert "encodeURIComponent(window.STEWARD_TOKEN)" in ld
    assert "innerHTML" not in ld


def test_authed_get_steward_deliverables_carries_route_and_run(tmp_path):
    """Authed GET /api/steward/deliverables: every item (register rows AND auto
    plan rows) carries route/run keys through the HTTP layer; tokenless is 401."""
    from tests.chamber_harness import TEST_TOKEN, boot_server
    srv = boot_server(tmp_path, token=TEST_TOKEN)
    try:
        import rnd_registry
        folder = tmp_path / "proj"
        effort = folder / "effort"
        effort.mkdir(parents=True)
        (effort / "ECGBERHT.md").write_text("# face", encoding="utf-8")
        (effort / "notes.md").write_text("hi", encoding="utf-8")
        (effort / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        _register(effort, [
            ("doc", "`notes.md`", ""),
            ("read", "`/artifact/pid-x?path=gandalf/run-1/report.md`", "2"),
            ("runner", "run: python -c \"print('hi')\"", ""),
        ])
        pid = rnd_registry.add_project("Reports Links", str(folder),
                                       scaffold=False)["id"]
        base = srv["base"]
        url = base + "/api/steward/deliverables?pid=" + pid + "&dir=effort"
        try:
            urllib.request.urlopen(url, timeout=30)
            raise AssertionError("tokenless GET must 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        with urllib.request.urlopen(url + "&token=" + TEST_TOKEN,
                                    timeout=30) as r:
            got = json.loads(r.read().decode("utf-8"))
        assert got["exists"] is True
        assert len(got["items"]) >= 4      # 3 register rows + the auto plan row
        for it in got["items"]:
            assert "route" in it, it
            assert "run" in it, it
        by = {it["what"]: it for it in got["items"]}
        assert by["read"]["route"] == "/artifact/pid-x?path=gandalf/run-1/report.md"
        assert by["read"]["openable"] is True
        assert by["runner"]["run"] == "python -c \"print('hi')\""
        assert by["doc"]["route"] is None
        assert by["doc"]["openable"] is True
    finally:
        srv["stop"]()


# ═════════════════════════════════════════════════════════════════════════════
# Wave 2 — a finished run registers itself: ONE registrar, three hooks
# ═════════════════════════════════════════════════════════════════════════════

def test_register_mints_header_active_step_and_dedups_whitespace(tmp_path):
    """A fresh effort dir gets the header + one row whose Step is the ACTIVE
    map step's 1-based index (no hint given); the same (what, where) — exact
    OR whitespace-variant — registered again leaves ONE row, honest dup."""
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "roadmap.json").write_text(json.dumps({
        "roadmap_projection": [
            {"id": "s1", "name": "one", "status": "done"},
            {"id": "s2", "name": "two", "status": "done"},
            {"id": "s3", "name": "three", "status": "active"},
        ]}), encoding="utf-8")
    out = dreg.register(str(eff), "Gandalf read standard — solid",
                        "`gandalf/run-1/report.md`")
    assert out == {"written": True, "reason": "written"}
    text = (eff / "DELIVERABLES.md").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "| What | Where | Date | Step |"
    items = campaign.read_deliverables(str(eff))["items"]
    assert len(items) == 1
    assert items[0]["step"] == "3"       # the active step, matched by NUMBER
    exact = dreg.register(str(eff), "Gandalf read standard — solid",
                          "`gandalf/run-1/report.md`")
    assert exact == {"written": False, "reason": "dup"}
    variant = dreg.register(str(eff), "Gandalf  read   standard — solid",
                            "  `gandalf/run-1/report.md` ")
    assert variant == {"written": False, "reason": "dup"}
    assert len(campaign.read_deliverables(str(eff))["items"]) == 1


def test_register_step_hint_wins_over_the_map(tmp_path):
    eff = tmp_path / "eff"
    eff.mkdir()
    (eff / "roadmap.json").write_text(json.dumps({
        "roadmap_projection": [{"id": "s1", "name": "one",
                                "status": "active"}]}), encoding="utf-8")
    dreg.register(str(eff), "a doc", "`doc.md`", step="s9")
    assert campaign.read_deliverables(str(eff))["items"][0]["step"] == "s9"


def test_register_two_threads_concurrently_yield_one_row(tmp_path):
    """STUB GATE (W2 durability/concurrency): two threads registering the same
    (what, where) at once — WRITE_LOCK + unique temp + os.replace — yield ONE
    row: one 'written', one 'dup', never a torn file (WinError-5 class)."""
    eff = tmp_path / "eff"
    eff.mkdir()
    results = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait(timeout=10)
        results.append(dreg.register(str(eff), "same thing", "`doc.md`"))

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(r["reason"] for r in results) == ["dup", "written"]
    assert len(campaign.read_deliverables(str(eff))["items"]) == 1


def test_effort_dir_for_campaign_vs_root(tmp_path):
    proj = tmp_path / "proj"
    camp = proj / "planning" / "eff"
    camp.mkdir(parents=True)
    (camp / "ECGBERHT.md").write_text("# face", encoding="utf-8")
    (proj / "gandalf").mkdir()
    real = os.path.realpath
    # the run's target folder carries the marker → the campaign dir
    assert real(dreg.effort_dir_for(str(camp), str(proj))) == real(str(camp))
    # a run dir UNDER the campaign walks up to the campaign dir
    assert real(dreg.effort_dir_for(str(camp / "gandalf"),
                                    str(proj))) == real(str(camp))
    # no marker anywhere up the walk → the project root
    assert real(dreg.effort_dir_for(str(proj / "gandalf"),
                                    str(proj))) == real(str(proj))
    # a run folder OUTSIDE the project folder → the project root (containment)
    assert real(dreg.effort_dir_for(str(tmp_path / "elsewhere"),
                                    str(proj))) == real(str(proj))


def test_where_for_every_form_round_trips_openable(tmp_path):
    """Every Where form where_for emits — in-effort backticked rel,
    /artifact/<pid>?path=<rel>, /report/<pid>/<lane>/<job_id> — round-trips
    through read_deliverables as openable; outside the project → honest ''."""
    proj = tmp_path / "proj"
    eff = proj / "planning" / "eff"
    (eff / "gandalf" / "run-1").mkdir(parents=True)
    (eff / "gandalf" / "run-1" / "report.md").write_text("# r",
                                                        encoding="utf-8")
    (proj / "research").mkdir()
    (proj / "research" / "out.md").write_text("# o", encoding="utf-8")
    pid = "pid-w2"

    inside = dreg.where_for(
        str(eff), str(proj), pid,
        abs_path=str(eff / "gandalf" / "run-1" / "report.md"))
    assert inside == "`gandalf/run-1/report.md`"
    outside = dreg.where_for(str(eff), str(proj), pid,
                             abs_path=str(proj / "research" / "out.md"))
    assert outside == "/artifact/pid-w2?path=research/out.md"
    lane_job = dreg.where_for(str(eff), str(proj), pid, lane="research",
                              job_id="job-9")
    assert lane_job == "/report/pid-w2/research/job-9"

    for i, where in enumerate((inside, outside, lane_job)):
        assert dreg.register(str(eff), "thing %d" % i, where)["written"] is True
    items = campaign.read_deliverables(str(eff))["items"]
    assert len(items) == 3
    for it in items:
        assert it["openable"] is True, it
    # an artifact outside the PROJECT folder is honestly not linkable
    stray = tmp_path / "stray.md"
    stray.write_text("x", encoding="utf-8")
    assert dreg.where_for(str(eff), str(proj), pid, abs_path=str(stray)) == ""
    # and register refuses an empty where with a returned reason, never a raise
    refused = dreg.register(str(eff), "stray", "")
    assert refused["written"] is False
    assert refused["reason"] == "empty-what-or-where"


# ── Hook A — gandalf.run_gandalf (ok-only, after the terminal index) ─────────

@pytest.fixture
def gandalf_env(tmp_path, monkeypatch):
    """Mirrors test_gandalf_agentic's env: temp data dir, journal ON, runner →
    stub_gandalf_agentic.py. NEVER live claude / node / :8777."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_JOURNAL", "on")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"{sys.executable} {AGENTIC_STUB}")
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(tmp_path / "no-skill"))
    monkeypatch.delenv("ANCHOR_GANDALF_MODE", raising=False)
    monkeypatch.delenv("STUB_GANDALF_AGENTIC_NOREPORT", raising=False)
    monkeypatch.delenv("STUB_GANDALF_AGENTIC_ADVISOR", raising=False)
    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import summarizer
    importlib.reload(summarizer)
    import gandalf
    gandalf = importlib.reload(gandalf)
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    eff = proj / "planning" / "eff"
    eff.mkdir(parents=True)
    (eff / "ECGBERHT.md").write_text("# face", encoding="utf-8")
    return {"gandalf": gandalf, "proj": proj, "eff": eff, "pid": "pid-gw2"}


def test_ok_gandalf_run_registers_one_openable_row_in_its_effort(gandalf_env):
    """STUB GATE (W2 Hook A): an OK run inside a cockpit-commissioned effort
    (store = the ECGBERHT.md campaign dir) appends ONE row 'Gandalf read
    <tier> — <verdict>' whose Where re-parses as openable, and journals
    {register: written} on the existing deliverable-pinned event."""
    g = gandalf_env["gandalf"]
    proj, eff, pid = gandalf_env["proj"], gandalf_env["eff"], gandalf_env["pid"]
    out = g.run_gandalf(str(proj), pid, store_folder=str(eff), tier="standard")
    assert out["ok"] is True
    rows = [it for it in campaign.read_deliverables(str(eff))["items"]
            if it["what"].startswith("Gandalf read")]
    assert len(rows) == 1
    it = rows[0]
    assert "standard" in it["what"] and out["verdict"] in it["what"]
    assert it["openable"] is True, it
    import journal
    evs = [e for e in journal.read_events(pid, folder_path=str(proj))
           if e.get("type") == journal.EV_DELIVERABLE_PINNED]
    assert evs and evs[-1]["payload"]["register"] == "written"


def test_failed_and_cancelled_gandalf_register_nothing(gandalf_env,
                                                       monkeypatch):
    """A run that fails (no report) or is cancelled writes NO register row —
    an honest register lists only real artifacts."""
    g = gandalf_env["gandalf"]
    proj, eff, pid = gandalf_env["proj"], gandalf_env["eff"], gandalf_env["pid"]
    monkeypatch.setenv("STUB_GANDALF_AGENTIC_NOREPORT", "1")
    out = g.run_gandalf(str(proj), pid, store_folder=str(eff), tier="standard")
    assert out["ok"] is False
    monkeypatch.setattr(g, "_run_stage_agentic",
                        lambda *a, **k: {"ok": False, "reason": "cancelled"})
    out2 = g.run_gandalf(str(proj), pid, store_folder=str(eff),
                         tier="standard")
    assert out2["ok"] is False
    assert out2["status"] == "cancelled"
    assert not [it for it in campaign.read_deliverables(str(eff))["items"]
                if it["what"].startswith("Gandalf read")]


# ── Hook B — job_runner._finalize (STATUS_DONE, research/plan lanes only) ────

@pytest.fixture
def jobs_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_JOURNAL", "on")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    for mod in ("paths", "job_runner", "rnd_registry", "session_registry",
                "sessions", "effort_history", "summarizer"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import rnd_registry
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd_registry.add_project("Reports W2", str(folder),
                                   scaffold=False)["id"]
    return {"pid": pid, "folder": str(folder)}


def _job_rec(jid, **over):
    rec = {"job_id": jid, "lane": "research", "status": "running",
           "started_at": 1.0, "exit_code": None, "session_id": None,
           "backend": "claude", "cost": None}
    rec.update(over)
    return rec


def test_status_done_lane_job_registers_project_root_row_failed_none(jobs_env):
    """STUB GATE (W2 Hook B): a STATUS_DONE research job with no effort_dir
    lands ONE row in the PROJECT-ROOT register with Where
    /report/<pid>/research/<job_id>; re-finalizing adds none (journal shows
    written then dup); STATUS_FAILED and non-research/plan lanes land none."""
    import job_runner as jr
    import journal
    pid, folder = jobs_env["pid"], jobs_env["folder"]
    jr._write_record(_job_rec("job-w2-a", project_id=pid, folder_path=folder))
    jr._finalize("job-w2-a", 0)
    items = campaign.read_deliverables(folder)["items"]
    rows = [it for it in items if it["what"] == "research run — job-w2-a"]
    assert len(rows) == 1
    assert rows[0]["route"] == "/report/%s/research/job-w2-a" % pid
    assert rows[0]["openable"] is True
    jr._finalize("job-w2-a", 0)      # idempotent: the re-run adds none
    items = campaign.read_deliverables(folder)["items"]
    assert len([it for it in items
                if it["what"] == "research run — job-w2-a"]) == 1
    regs = [e["payload"]["register"]
            for e in journal.read_events(pid, folder_path=folder)
            if e.get("type") == journal.EV_DELIVERABLE_PINNED]
    assert regs == ["written", "dup"]
    # a FAILED job never registers; nor does a done job outside research/plan
    jr._write_record(_job_rec("job-w2-b", project_id=pid, folder_path=folder))
    jr._finalize("job-w2-b", 1)
    jr._write_record(_job_rec("job-w2-c", project_id=pid, folder_path=folder,
                              lane="build"))
    jr._finalize("job-w2-c", 0)
    items = campaign.read_deliverables(folder)["items"]
    assert not [it for it in items
                if "job-w2-b" in it["what"] or "job-w2-c" in it["what"]]


# ── Hook C — commission_session.finish_run (PRODUCED, human-facing roles) ────

def _disc(eh, folder, pid, lane, rel):
    jid = eh.discovered_job_id(lane, rel)
    return eh.record_effort(folder, pid, lane, jid, extra={
        "source": eh.SOURCE_DISCOVERED, "kind": "", "title": "",
        "artifact_path": rel, "status": "imported"})


def test_finish_run_produced_registers_human_docs_only_idempotently(
        tmp_path, monkeypatch):
    """STUB GATE (W2 Hook C): a commissioned run that came home PRODUCED
    registers one row per HUMAN-FACING doc role (research: report + exec) —
    NEVER agent/provenance — under the commission record's step; the watcher's
    second finish_run adds none (journal written→dup); a non-produced outcome
    registers nothing. Bridge fully stubbed (fake_ecgberht_bridge)."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_JOURNAL", "on")
    stub = Path(__file__).resolve().parent / "fake_ecgberht_bridge.py"
    monkeypatch.setenv("ANCHOR_ECGBERHT_BRIDGE_CMD",
                       f'"{sys.executable}" "{stub}"')
    monkeypatch.setenv("FAKE_BRIDGE_DIR", str(tmp_path / "bridge-rec"))
    for mod in ("paths", "rnd_registry", "effort_history", "sessions",
                "summarizer"):
        importlib.reload(importlib.import_module(mod))
    import commission_session as cs
    cs = importlib.reload(cs)
    import effort_history as eh
    import journal
    import rnd_registry
    import sessions as sess

    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd_registry.add_project("Commission W2", str(folder),
                                   scaffold=False)["id"]
    d = "research/topic-w2"
    for rel in (f"{d}/report.pdf", f"{d}/executive-summary.md",
                f"{d}/agent.json", f"{d}/run.log"):
        _disc(eh, folder, pid, "research", rel)
    sid = None
    for s in sess.list_sessions(folder, pid, "research"):
        if any((m.get("artifact_path") or "").replace("\\", "/").startswith(
                d + "/") for m in s["member_files"]):
            sid = s["session_id"]
    assert sid is not None

    record = {"session_id": sid, "commission_id": "c-w2",
              "skill": "researchPrime", "step_id": "s2", "lane": "research",
              "project_id": pid, "outcome": "running", "watch_count": 0}
    result = {"outcome": "produced", "ran": True, "elapsed_s": 1.0,
              "transcript": "work happened", "transcript_chars": 13}
    out1 = cs.finish_run(str(folder), pid, dict(record), dict(result))
    assert out1["ok"] is True
    items = campaign.read_deliverables(str(folder))["items"]
    reg_rows = [it for it in items
                if it["what"].startswith("researchPrime — ")]
    assert sorted(it["what"] for it in reg_rows) == [
        "researchPrime — exec: executive-summary.md",
        "researchPrime — report: report.pdf"]
    for it in reg_rows:
        assert it["openable"] is True, it
        assert it["step"] == "s2"       # the commission record's step wins
    assert not [it for it in items
                if "— agent:" in it["what"] or "— provenance:" in it["what"]]

    # resume: the re-armed watcher's second finish_run adds NOTHING
    out2 = cs.finish_run(str(folder), pid, dict(record), dict(result))
    assert out2["ok"] is True
    items = campaign.read_deliverables(str(folder))["items"]
    assert len([it for it in items
                if it["what"].startswith("researchPrime — ")]) == 2
    regs = [e["payload"]["register"]
            for e in journal.read_events(pid, folder_path=str(folder))
            if e.get("type") == journal.EV_DELIVERABLE_PINNED]
    assert regs == ["written", "written", "dup", "dup"]

    # a run that came home ASKED (not produced) never registers
    out3 = cs.finish_run(str(folder), pid, dict(record),
                         {"outcome": "asked", "transcript": "q?",
                          "transcript_chars": 2})
    assert out3["ok"] is True
    items = campaign.read_deliverables(str(folder))["items"]
    assert len([it for it in items
                if it["what"].startswith("researchPrime — ")]) == 2


# ── Hook C amendment (2026-09-05) — cockpit Gandalf + capture-before-roles ───

def _commission_env(tmp_path, monkeypatch):
    """The shared Hook C env: temp data dir, journal on, bridge → fake stub."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_JOURNAL", "on")
    stub = Path(__file__).resolve().parent / "fake_ecgberht_bridge.py"
    monkeypatch.setenv("ANCHOR_ECGBERHT_BRIDGE_CMD",
                       f'"{sys.executable}" "{stub}"')
    monkeypatch.setenv("FAKE_BRIDGE_DIR", str(tmp_path / "bridge-rec"))
    for mod in ("paths", "rnd_registry", "effort_history", "sessions",
                "summarizer"):
        importlib.reload(importlib.import_module(mod))
    import commission_session as cs
    return importlib.reload(cs)


def test_finish_run_gandalf_general_registers_the_read_directly(
        tmp_path, monkeypatch):
    """STUB GATE (W2 second amendment): the cockpit's 'Commission a Gandalf
    read' maps skill Gandalf to lane 'general' — HUMAN_FACING_DOC_ROLES has no
    'general' key and session_doc_roles is empty for it — and the commissioned
    session runs in an ISOLATED WORKTREE, so at PRODUCED time its
    gandalf/**/report.md is NOT under the campaign folder. finish_run resolves
    THIS run's report.md + exec-summary.md from record.worktree_path, PERSISTS
    them into MAIN (gandalf/ is a persistable _DOC_DIRS dir), and registers
    the MAIN path with Hook A's what-string ('Gandalf read <tier> — <verdict>',
    verdict from the exec summary's first content line). A sibling run already
    sitting under the campaign folder is NEVER mtime-bound; the second finish
    adds none (journal written→dup)."""
    cs = _commission_env(tmp_path, monkeypatch)
    import effort_history as eh
    import journal
    import rnd_registry

    assert "gandalf" in eh._DOC_DIRS    # the persistable-doc-dir amendment

    proj = tmp_path / "proj"
    camp = proj / "planning" / "g-eff"
    camp.mkdir(parents=True)
    (camp / "ECGBERHT.md").write_text("# face", encoding="utf-8")
    # a SIBLING (older) read already under the campaign folder — not this
    # run's to register; it must never be bound by newest-mtime scanning
    sib = camp / "gandalf" / "run-0"
    sib.mkdir(parents=True)
    (sib / "report.md").write_text("# older sibling read\n", encoding="utf-8")
    # THIS run's artifacts live in the session's isolated worktree
    wt = tmp_path / "wt-gw2"
    run_dir = wt / "gandalf" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "report.md").write_text("# Gandalf report\n\nBottom line.\n",
                                       encoding="utf-8")
    (run_dir / "exec-summary.md").write_text(
        "# Gandalf executive summary\n\nSolid substance; two gaps named.\n",
        encoding="utf-8")
    pid = rnd_registry.add_project("Gandalf W2", str(proj),
                                   scaffold=False)["id"]

    record = {"session_id": "term-gw2", "commission_id": "c-g1",
              "skill": "Gandalf", "step_id": "s1", "lane": "general",
              "project_id": pid, "outcome": "running", "watch_count": 0,
              "worktree_path": str(wt)}
    result = {"outcome": "produced", "ran": True, "elapsed_s": 1.0,
              "transcript": "read done", "transcript_chars": 9}
    out1 = cs.finish_run(str(camp), pid, dict(record), dict(result))
    assert out1["ok"] is True
    # persisted into MAIN before registering — the register points at real files
    assert (proj / "gandalf" / "run-1" / "report.md").is_file()
    assert (proj / "gandalf" / "run-1" / "exec-summary.md").is_file()
    items = campaign.read_deliverables(str(camp))["items"]
    rows = [it for it in items if it["what"].startswith("Gandalf read")]
    assert len(rows) == 2
    for it in rows:
        # tier unknown on a commission record → the collapsed Hook A form
        assert it["what"] == "Gandalf read — Solid substance; two gaps named."
        assert it["openable"] is True, it
        assert it["step"] == "s1"       # the commission record's step
    # the MAIN path, outside the campaign dir → the /artifact route form
    assert sorted((it.get("route") or "") for it in rows) == [
        "/artifact/%s?path=gandalf/run-1/exec-summary.md" % pid,
        "/artifact/%s?path=gandalf/run-1/report.md" % pid]
    # the sibling run under the campaign folder was never registered
    assert not [it for it in items if "run-0" in (it.get("route") or "")]
    # never keyed on the lane role table (empty for 'general')
    assert not [it for it in items
                if "— report:" in it["what"] or "— exec:" in it["what"]]

    out2 = cs.finish_run(str(camp), pid, dict(record), dict(result))
    assert out2["ok"] is True
    assert len([it for it in campaign.read_deliverables(str(camp))["items"]
                if it["what"].startswith("Gandalf read")]) == 2
    regs = [e["payload"]["register"]
            for e in journal.read_events(pid, folder_path=str(proj))
            if e.get("type") == journal.EV_DELIVERABLE_PINNED]
    assert regs == ["written", "written", "dup", "dup"]

    # no worktree on the record (and no registry row) → nothing new registers,
    # even though the campaign folder still holds a sibling read on disk
    no_wt = {**record, "session_id": "term-gw2-b", "worktree_path": ""}
    out3 = cs.finish_run(str(camp), pid, dict(no_wt), dict(result))
    assert out3["ok"] is True
    assert len([it for it in campaign.read_deliverables(str(camp))["items"]
                if it["what"].startswith("Gandalf read")]) == 2


def test_finish_run_captures_docs_before_roles_for_live_session(
        tmp_path, monkeypatch):
    """STUB GATE (W2 amendment): at PRODUCED time nothing is persisted yet
    (capture runs only on kill/close), so finish_run calls
    terminal_session.capture_session_docs FIRST and only then role-resolves —
    here the docs EXIST only after the capture spy runs, and they are grouped
    under a dir:: computed session id while the record carries the MANAGED id,
    so the rows landing proves both the capture-first order and the v8
    session_id-tag bridge."""
    cs = _commission_env(tmp_path, monkeypatch)
    import effort_history as eh
    import rnd_registry
    import terminal_session as ts

    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd_registry.add_project("Live W2", str(folder),
                                   scaffold=False)["id"]
    sid = "term-live-w2"     # the MANAGED session id on the commission record
    captured = []

    def fake_capture(session_id, project_id=None, record=None):
        # Simulate persist_session_docs: the docs land in MAIN + per-doc
        # DISCOVERED efforts tagged with the managed session id (v8 keystone).
        captured.append((session_id, project_id))
        d = "research/live-w2"
        (folder / d).mkdir(parents=True, exist_ok=True)
        for rel in (f"{d}/report.pdf", f"{d}/executive-summary.md"):
            (folder / rel).write_text("x", encoding="utf-8")
            jid = eh.discovered_job_id("research", rel)
            eh.record_effort(folder, pid, "research", jid, extra={
                "source": eh.SOURCE_DISCOVERED, "kind": "", "title": "",
                "artifact_path": rel, "status": "imported",
                "session_id": session_id})
        return {"ok": True, "persisted": [f"{d}/report.pdf",
                                          f"{d}/executive-summary.md"]}

    monkeypatch.setattr(ts, "capture_session_docs", fake_capture)
    record = {"session_id": sid, "commission_id": "c-live",
              "skill": "researchPrime", "step_id": "s2", "lane": "research",
              "project_id": pid, "outcome": "running", "watch_count": 0}
    out = cs.finish_run(str(folder), pid, dict(record),
                        {"outcome": "produced", "ran": True, "elapsed_s": 1.0,
                         "transcript": "work", "transcript_chars": 4})
    assert out["ok"] is True
    assert captured == [(sid, pid)]     # capture ran, with the managed id
    items = campaign.read_deliverables(str(folder))["items"]
    rows = sorted(it["what"] for it in items
                  if it["what"].startswith("researchPrime — "))
    assert rows == ["researchPrime — exec: executive-summary.md",
                    "researchPrime — report: report.pdf"]
    for it in items:
        if it["what"].startswith("researchPrime — "):
            assert it["openable"] is True, it
            assert it["step"] == "s2"
