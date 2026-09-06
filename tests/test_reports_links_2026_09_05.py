"""Every report is a link — in the plan outline and in the deliverables register (John, 2026-09-05).

The gate file for planning/reports-links-2026-09-05. Wave 1: the register
understands contained Anchor routes (/report/…, /artifact/…) and run: markers,
and both render surfaces (the deliverables tile + the plan-outline step
expansion, via the ONE delivRow renderer; cockpit loadDeliv) read the same
classified rows. Hostile Where cells NEVER classify (route None, openable
False — they render as text); a run: cell stores the literal command string,
never parsed, never evaluated. Documents without routes or run: parse
byte-identically to before.
"""
import json
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_campaign as campaign  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "steward_cockpit" / "static"


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
