"""Clickable review links in Deliverables and Next steps (wave 1, 2026-10-07).

John's standard (turns cab78cce / 174395b4, journaled as the default): every
review target in conversation, Next steps and Deliverables is DIRECTLY
clickable — a PDF, HTML or Markdown document, or the live page itself. The
observed break: ``steward_campaign._read_deliverables`` recognized only
``/report/`` and ``/artifact/`` as contained routes, so the supervising
register's ``/foundry?skill=researchprime|gandalf|steward-project|
steward-portfolio`` rows rendered as plain FOR REVIEW text.

Pins:
  (1) ``classify_route`` validates the live Foundry review page grammar
      ``/foundry?skill=<id>`` — and ONLY that grammar: hostile or unsupported
      route cells (second query keys, traversal, schemes, ``/foundry/source``,
      prefix-shaped lookalikes) never classify;
  (2) the REAL supervising-register rows (bare ``/foundry?skill=…`` tokens,
      FOR REVIEW labels, the backticked plan PDF, an ``/artifact`` row) parse
      openable through the one register reader — and the uncorrected
      Refinement-2 ``researchprime/`` folder row stays HONESTLY non-openable
      (that row's fix is the correction artifact, tested below);
  (3) Next steps (the server-side acts the tile paints) carries the classified
      route item;
  (4) the shared renderer stays route-generic and names a Foundry route by its
      skill (source-level, both delivRow and loadDeliv);
  (5) the loaded steward delivery instructions carry the rule: no FOR REVIEW
      claim without an openable same-version target registered and linked;
  (6) the correction artifact for the supervising effort's first Refinement-2
      row is parser-compatible and classifies openable;
  (7) REAL-BROWSER (the v4/chamber lesson — a gate that cannot see what the
      user sees is not a gate): a hermetic server (throwaway port, never
      :8777) serves the actual cockpit; Deliverables AND Next steps expose
      real anchors; a click lands on the Foundry page; the plan PDF link
      serves application/pdf — on a desktop and a phone viewport, with
      ordinary browser authentication (the page token), screenshots and the
      exact tested links recorded under ``.foreman-job/wave1-proof/``.

Live (:8777) verification is deliberately NOT here: the running service needs
activation first (John's no-restart instruction is active); source changes are
reported separately from live results.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# REQUIRED, never importorskip'd (the chamber-page precedent): a missing
# Playwright must fail loudly, or the pixels stop being checked.
from playwright.sync_api import sync_playwright  # noqa: E402

from steward_cockpit import steward_campaign as campaign   # noqa: E402
from steward_cockpit import steward_engine as engine       # noqa: E402
from steward_cockpit import steward_routes as routes       # noqa: E402

PROOF = REPO / ".foreman-job" / "wave1-proof"

FOUNDRY_ROUTES = [
    "/foundry?skill=researchprime",
    "/foundry?skill=gandalf",
    "/foundry?skill=steward-project",
    "/foundry?skill=steward-portfolio",
]

HOSTILE_OR_UNSUPPORTED = [
    "/foundry?skill=../../etc",                 # traversal-shaped id
    "/foundry?skill=a/b",                       # path separator in id
    "/foundry?skill=a\\b",                      # backslash in id
    "/foundry?skill=a&redirect=//evil",         # second query key
    "/foundry?evil=researchprime",              # wrong key
    "/foundry?skill=",                          # empty id
    "/foundry",                                 # bare — not a review target
    "/foundry/",
    "/foundry/source?skill=x&path=../../x",     # per-anchor link, never a register target
    "/foundrybogus?skill=x",                    # prefix-shaped lookalike
    "/foundry?skill=a%2F..%2Fb",                # percent escape
    "/foundry?skill=a#frag",                    # fragment
    "/foundry?skill=javascript:alert(1)",       # scheme-shaped id
    "http://evil/foundry?skill=x",              # absolute URL
    "//evil/foundry?skill=x",                   # protocol-relative
    "../foundry?skill=x",                       # relative traversal
]

# The supervising register's rows, shape-faithful (bare route tokens, the
# FOR REVIEW designations, the folder-pointing Refinement-2 row, the plan
# PDF, an /artifact route) — dates as in the real register so the acts
# ordering below mirrors what John's page would compute.
REGISTER = """# Deliverables

| What | Where | Date | Step |
| --- | --- | --- | --- |
| researchPrime Refinement 2 — source bundle verified; activation reported by the other session, live browser verification pending | `researchprime/` (activated by the other session; live browser verification pending) | 2026-10-07 | gwl-walk-researchprime |
| ecgberht Current Foundry working plan - PDF review copy 1, for reading and feedback | `planning/working-plan/PLAN-review-copy-1.pdf` | 2026-10-05 | gwl-page |
| FOR REVIEW — researchPrime Library and maps, Refinement 1 of mockup v7; open resources and compare the process with its sources | /foundry?skill=researchprime | 2026-10-04 | gwl-walk-researchprime |
| FOR REVIEW — Gandalf Library, navigable knowledge map and program/process map — Initial draft | /foundry?skill=gandalf | 2026-10-05 | gwl-walk-gandalf |
| FOR REVIEW — Aladdin-Lamp Library, navigable knowledge map and actual process map — Initial draft | /foundry?skill=steward-project | 2026-10-05 | gwl-walk-steward-lamp |
| FOR REVIEW — Aladdin-Cave of Wonders Library, navigable knowledge map and actual portfolio process map — Initial draft | /foundry?skill=steward-portfolio | 2026-10-05 | gwl-walk-steward-cave |
| Preserved Foundry page mockup v7 — original, unaccepted review foundation | /artifact/30ffba93f3614ce48aeda6252b74cf42?path=planning%2Ffoundry-page-2026-10-02%2Fmockup%2Ffoundry-mockup.html | 2026-10-04 | gwl-page |
"""

ROADMAP = {
    "roadmap_projection": [
        {"id": "gwl-page", "name": "Foundry page", "status": "done"},
        {"id": "gwl-walk-researchprime", "name": "researchPrime walkthrough",
         "status": "active"},
        {"id": "gwl-walk-gandalf", "name": "Gandalf walkthrough",
         "status": "proposed"},
        {"id": "gwl-walk-steward-lamp", "name": "Lamp walkthrough",
         "status": "proposed"},
        {"id": "gwl-walk-steward-cave", "name": "Cave walkthrough",
         "status": "proposed"},
    ]
}


def _effort(root):
    """A supervising-shaped effort dir: register + roadmap + the real PDF."""
    eff = Path(root) / "effort"
    (eff / "planning" / "working-plan").mkdir(parents=True)
    (eff / "ECGBERHT.md").write_text("# effort face", encoding="utf-8")
    (eff / "DELIVERABLES.md").write_text(REGISTER, encoding="utf-8")
    (eff / "roadmap.json").write_text(json.dumps(ROADMAP), encoding="utf-8")
    (eff / "planning" / "working-plan" / "PLAN-review-copy-1.pdf").write_bytes(
        b"%PDF-1.4 fake plan review copy")
    return eff


# ─── (1) the route grammar ───────────────────────────────────────────────────

def test_foundry_review_routes_classify():
    for r in FOUNDRY_ROUTES:
        assert campaign.classify_route(r) == r, r
    # whitespace-padded cells classify to the stripped route
    assert campaign.classify_route("  /foundry?skill=gandalf  ") == \
        "/foundry?skill=gandalf"


def test_existing_report_and_artifact_grammars_unchanged():
    assert campaign.classify_route("/report/pid-1/research/job-1") == \
        "/report/pid-1/research/job-1"
    art = "/artifact/pid-1?path=gandalf/run-1/report.md"
    assert campaign.classify_route(art) == art


def test_hostile_and_unsupported_routes_never_classify():
    for w in HOSTILE_OR_UNSUPPORTED:
        assert campaign.classify_route(w) is None, w


# ─── (2) the real register rows ──────────────────────────────────────────────

def test_supervising_register_rows_parse_openable():
    td = tempfile.mkdtemp(prefix="steward-register-w1-")
    eff = _effort(td)
    got = campaign.read_deliverables(str(eff))
    assert got["exists"] is True
    by = {it["what"].split(" — ")[0].split(" - ")[0].strip(): it
          for it in got["items"]}
    # every /foundry review row is now an openable ROUTE (the FOR REVIEW fix)
    foundry_rows = [it for it in got["items"]
                    if (it.get("route") or "").startswith("/foundry?skill=")]
    assert sorted(it["route"] for it in foundry_rows) == sorted(FOUNDRY_ROUTES)
    for it in foundry_rows:
        assert it["openable"] is True, it["what"]
        assert it["path"] is None, it["what"]
    # the /artifact row keeps working exactly as before
    art = by["Preserved Foundry page mockup v7"]
    assert art["openable"] is True and art["route"].startswith("/artifact/")
    # the plan PDF opens as a contained file
    pdf = by["ecgberht Current Foundry working plan"]
    assert pdf["openable"] is True
    assert pdf["path"] == "planning/working-plan/PLAN-review-copy-1.pdf"
    # the uncorrected Refinement-2 row points at a FOLDER — honestly
    # non-openable (its fix is the correction artifact, tested below)
    r2 = by["researchPrime Refinement 2"]
    assert r2["openable"] is False and r2["route"] is None
    # step ids survive untouched (independent feedback stays attached)
    for it in foundry_rows:
        assert it["step"].startswith("gwl-")


def test_api_dispatch_layer_carries_the_routes():
    """The 2026-08-25 lesson: test the layer the page actually hits."""
    td = tempfile.mkdtemp(prefix="steward-register-w1-api-")
    _effort(td)
    d, code = routes.api_get(td, "deliverables", {"dir": "effort"})
    assert code == 200
    routed = {it["route"] for it in d["items"] if it.get("route")}
    for r in FOUNDRY_ROUTES:
        assert r in routed


# ─── (3) Next steps carries the route item ───────────────────────────────────

def test_next_steps_acts_carry_the_foundry_route():
    td = tempfile.mkdtemp(prefix="steward-register-w1-acts-")
    eff = _effort(td)
    got = campaign.read_deliverables(str(eff))
    opens = [a for a in got["acts"] if a.get("act") == "Open" and a.get("item")]
    assert opens, "the FOR REVIEW rows must surface an Open act"
    act = opens[0]
    # newest FOR REVIEW row (2026-10-05, file order) → the Gandalf page
    assert act["item"]["route"] == "/foundry?skill=gandalf"
    assert act["item"]["openable"] is True
    # and the register rows flagged current include the foundry review rows
    current = [it for it in got["items"] if it.get("is_current")]
    assert any((it.get("route") or "").startswith("/foundry?skill=")
               for it in current)


# ─── (4) the shared renderer stays route-generic ─────────────────────────────

def test_renderers_stay_route_generic_and_name_foundry_routes():
    js = (REPO / "steward_cockpit" / "static" / "shared.js").read_text(
        encoding="utf-8")
    deliv = js.split("function delivRow(it)")[1].split("function actLabel")[0]
    # ONE generic route branch — anchors from whatever the server classified,
    # never a client-side prefix allowlist that would re-break new grammars
    assert "it.route" in deliv
    assert '"/report/' not in deliv and '"/artifact/' not in deliv \
        and '"/foundry' not in deliv
    assert "innerHTML" not in deliv
    # a Foundry route is named by its skill — the live page it opens
    name = js.split("function routeName(r)")[1].split("function delivRow")[0]
    assert "foundry\\?skill=" in name
    # loadDeliv (cockpit.html) keeps its matching generic anchor branch
    ld = (REPO / "steward_cockpit" / "static" / "cockpit.html").read_text(
        encoding="utf-8").split("async function loadDeliv()")[1].split(
        "async function loadFiles()")[0]
    assert "fn.href = it.route" in ld
    assert "innerHTML" not in ld


# ─── (5) the rule rides in the loaded delivery instructions ──────────────────

def test_delivery_instructions_carry_the_review_link_rule():
    rules = engine.EFFORT_RULES
    assert "/foundry?skill=<id>" in rules
    assert "never claim FOR REVIEW" in rules
    assert "openable same-version target registered and linked" in rules


# ─── (6) the correction artifact for the supervising register ────────────────

def test_correction_artifact_row_parses_openable():
    art = REPO / ".foreman-job" / "DELIVERABLES-rows-correction.md"
    assert art.is_file(), "the steward-applicable correction artifact ships with this wave"
    text = art.read_text(encoding="utf-8")
    # no host-absolute paths ride in the artifact
    assert "C:\\" not in text and "/Users/" not in text
    corrected = [ln for ln in text.splitlines()
                 if ln.startswith("| researchPrime Refinement 2")
                 and "/foundry?skill=researchprime" in ln]
    assert len(corrected) == 1, "exactly one corrected row, paste-ready"
    row = corrected[0]
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[3] == "gwl-walk-researchprime"   # step id intact
    assert "`" not in cells[1], "the corrected Where cell must stay backtick-free"
    td = tempfile.mkdtemp(prefix="steward-register-w1-fix-")
    eff = Path(td) / "effort"
    eff.mkdir()
    (eff / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n" + row + "\n",
        encoding="utf-8")
    it = campaign.read_deliverables(str(eff))["items"][0]
    assert it["route"] == "/foundry?skill=researchprime"
    assert it["openable"] is True


# ─── (7) the real browser: cockpit render + click-through, desktop & phone ───

@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    from tests.chamber_harness import TEST_TOKEN, boot_server
    tmp = tmp_path_factory.mktemp("register-w1-browser")
    handle = boot_server(tmp, token=TEST_TOKEN)
    try:
        import rnd_registry
        folder = tmp / "proj"
        folder.mkdir()
        _effort(folder)
        pid = rnd_registry.add_project("Review Links W1", str(folder),
                                       scaffold=False)["id"]
        yield {"base": handle["base"], "pid": pid, "token": TEST_TOKEN}
    finally:
        handle["stop"]()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def _open_cockpit(ctx, srv):
    pg = ctx.new_page()
    pg.goto("%s/steward/v1?pid=%s&dir=effort&token=%s"
            % (srv["base"], srv["pid"], srv["token"]), wait_until="load")
    pg.wait_for_selector(".blk.deliv", timeout=20000)
    pg.wait_for_selector(".blk.next", timeout=20000)
    # both tiles start folded by design — open them the way John does
    for sel in (".blk.deliv > .who", ".blk.next > .who"):
        who = pg.locator(sel)
        who.scroll_into_view_if_needed()
        who.click()
    pg.wait_for_timeout(300)
    return pg


def _assert_anchors(pg):
    """Both surfaces expose REAL anchors for the classified routes."""
    deliv_foundry = pg.locator(".blk.deliv a[href^='/foundry?skill=']")
    assert deliv_foundry.count() >= 4, \
        "all four /foundry review rows must render as anchors in Deliverables"
    next_foundry = pg.locator(".blk.next a[href^='/foundry?skill=']")
    assert next_foundry.count() >= 1, \
        "Next steps must link the current FOR REVIEW page"
    pdf = pg.locator(".blk.deliv a[href*='deliverable-file']").first
    href = pdf.get_attribute("href")
    assert href and "PLAN-review-copy-1.pdf" in href and "token=" in href
    return href


def _mask(link, srv):
    return link.replace(srv["token"], "<token>")


_TESTED = []


def test_browser_desktop_renders_anchors_and_clicks_through(srv, browser):
    PROOF.mkdir(parents=True, exist_ok=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(
        "try{localStorage.setItem('anchor_token','%s')}catch(e){}" % srv["token"])
    try:
        pg = _open_cockpit(ctx, srv)
        pdf_href = _assert_anchors(pg)
        pg.screenshot(path=str(PROOF / "desktop-cockpit.png"), full_page=True)
        # click through from NEXT STEPS to the live Foundry page
        link = pg.locator(".blk.next a[href^='/foundry?skill=']").first
        clicked_href = link.get_attribute("href")
        with ctx.expect_page() as pop:
            link.click()
        page2 = pop.value
        page2.wait_for_load_state()
        assert "/foundry?skill=gandalf" in page2.url
        assert page2.evaluate(
            "() => !!document.body && document.body.innerHTML.length > 0")
        page2.screenshot(path=str(PROOF / "desktop-foundry.png"))
        page2.close()
        # the same URL answers 200 (not an error document)
        r = pg.request.get(srv["base"] + clicked_href)
        assert r.status == 200
        # the register's other review pages answer from the same origin
        for route in FOUNDRY_ROUTES:
            rr = pg.request.get(
                srv["base"] + route + "&token=" + srv["token"])
            assert rr.status == 200, route
        # the existing plan PDF really serves as a PDF through its own anchor
        rp = pg.request.get(srv["base"] + pdf_href)
        assert rp.status == 200
        assert "pdf" in (rp.headers.get("content-type") or "").lower()
        assert rp.body().startswith(b"%PDF")
        _TESTED.extend([
            "desktop · Next steps click-through: " + _mask(clicked_href, srv),
            "desktop · plan PDF anchor: " + _mask(pdf_href, srv),
        ] + ["desktop · 200 OK: " + r_ for r_ in FOUNDRY_ROUTES])
    finally:
        ctx.close()


def test_browser_phone_renders_anchors_and_clicks_through(srv, browser):
    PROOF.mkdir(parents=True, exist_ok=True)
    ctx = browser.new_context(viewport={"width": 390, "height": 844},
                              is_mobile=True, has_touch=True,
                              device_scale_factor=2)
    ctx.add_init_script(
        "try{localStorage.setItem('anchor_token','%s')}catch(e){}" % srv["token"])
    try:
        pg = _open_cockpit(ctx, srv)
        pdf_href = _assert_anchors(pg)
        pg.screenshot(path=str(PROOF / "phone-cockpit.png"), full_page=True)
        link = pg.locator(".blk.next a[href^='/foundry?skill=']").first
        link.scroll_into_view_if_needed()
        clicked_href = link.get_attribute("href")
        with ctx.expect_page() as pop:
            link.click()
        page2 = pop.value
        page2.wait_for_load_state()
        assert "/foundry?skill=" in page2.url
        page2.screenshot(path=str(PROOF / "phone-foundry.png"))
        page2.close()
        rp = pg.request.get(srv["base"] + pdf_href)
        assert rp.status == 200 and rp.body().startswith(b"%PDF")
        _TESTED.extend([
            "phone · Next steps click-through: " + _mask(clicked_href, srv),
            "phone · plan PDF anchor: " + _mask(pdf_href, srv),
        ])
    finally:
        ctx.close()


def test_record_exact_tested_links():
    """The proof record the wave demands: screenshots + the exact links."""
    assert _TESTED, "the browser legs must run before the record is written"
    PROOF.mkdir(parents=True, exist_ok=True)
    shots = sorted(p.name for p in PROOF.glob("*.png"))
    assert {"desktop-cockpit.png", "desktop-foundry.png",
            "phone-cockpit.png", "phone-foundry.png"} <= set(shots)
    (PROOF / "LINKS-TESTED.md").write_text(
        "# Wave 1 — exact links tested (hermetic server, OS-assigned port, "
        "never :8777)\n\n"
        "Origin: a throwaway Anchor server booted by the gate "
        "(`tests/chamber_harness.boot_server`); `<token>` is the page token "
        "the cockpit itself appends (ordinary browser authentication). "
        "Live-:8777 verification requires activation and is reported "
        "separately per the no-restart instruction.\n\n"
        + "".join("- %s\n" % t for t in _TESTED)
        + "\nScreenshots: " + ", ".join(shots) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
