"""The Anchor app (static/app.html + app.js + app-frame.js), PLAN v2.2 S1/S2 of the app-shell cycle
(Skill Foundry/planning/anchor-app-shell-2026-09-29).

A throwaway stdlib server on a spare port (never :8777) serves the real app files and stand-in pages that carry
each pattern the adversarial review found in Anchor's code: target=_blank links on the Cave, a pre-opened
about:blank whose .location is set later, a cockpit whose own shim saves window.open early and rewrites /report,
nested frames, a named target, a New-project popup that answers through window.opener, downloads, and an app link.
Every assertion is on what is PAINTED (computed display / visibility), checked after the page settles.
"""
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
BRAND = ROOT / "vendor" / "brand"

SHIM = ('<script src="/static/app-frame.js"></script><script>var _op=window.open;window.open=function(u,t){'
        'if(typeof u==="string"&&u.indexOf("/report")===0){u="/steward"+u;}return _op(u,t);};</script>')

PAGES = {
    "/": """<!doctype html><html><head><title>Cave of Wonders</title></head><body>
<a id="ck1" href="/project/p1" target="_blank">cockpit</a>
<button id="pre" onclick="var w=window.open('about:blank','_blank');w.opener=null;w.location.replace('/project/p2');">resume</button>
<button id="np" onclick="window.open('/newproj','anchor-new-project','width=640,height=800')">new project</button>
<div id="got"></div>
<script>window.addEventListener('message',function(e){document.getElementById('got').textContent=e.data;});</script>
</body></html>""",
    "/project/p1": """<!doctype html><html><head><title>MBA Teaching AI</title></head><body>""" + SHIM + """
<textarea id="say"></textarea>
<a id="deliv" href="/api/steward/deliverable-file?pid=p1&path=Deck.pptx&view=1" target="_blank">deck</a>
<button id="rep" onclick="window.open('/report?dir=&path=notes.md')">notes</button>
<a id="dl" href="/api/steward/deliverable-file?pid=p1&path=Deck.pptx&download=1" target="_blank">download</a>
<a id="named" href="/report/x" target="anchor_report_window">named</a>
<a id="p3" href="/project/p3" target="_blank">other cockpit</a>
<iframe id="v1" src="/steward/v1?pid=p1" style="width:300px;height:80px"></iframe>
</body></html>""",
    "/project/p2": "<!doctype html><html><head><title>Artificial Magi</title></head><body>" + SHIM + "<p>magi</p></body></html>",
    "/project/p3": "<!doctype html><html><head><title>DARPA proposal</title></head><body>" + SHIM + "<p>darpa</p></body></html>",
    "/steward/v1": "<!doctype html><html><head><title>v1</title></head><body>" + SHIM
                   + '<a id="nested" href="/artifact/p1?path=fig.html" target="_blank">figure</a></body></html>',
    "/newproj": """<!doctype html><html><head><title>New project</title></head><body>
<button id="make" onclick="window.opener.postMessage('created','*');window.close();">create</button></body></html>""",
}
DOCS = ("/api/steward/deliverable-file", "/steward/report", "/report", "/artifact")


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path.startswith("/static/"):
            f = STATIC / path[len("/static/"):]
            ctype = {"js": "text/javascript", "css": "text/css", "html": "text/html"}.get(f.suffix[1:], "text/plain")
            return self._send(f.read_bytes(), ctype + "; charset=utf-8")
        if path.startswith("/vendor/brand/"):
            f = BRAND / path[len("/vendor/brand/"):]
            return self._send(f.read_bytes() if f.is_file() else b"", "image/png")
        if path in PAGES:
            return self._send(PAGES[path])
        if "download=1" in query:
            return self._send(b"PK", "application/octet-stream",
                              {"Content-Disposition": 'attachment; filename="Deck.pptx"'})
        if path.startswith(DOCS):
            return self._send("<!doctype html><title>doc %s</title><p>%s?%s</p>" % (path, path, query))
        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="module")
def base():
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % port
    srv.shutdown()


@pytest.fixture()
def page(base):
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 900}, accept_downloads=True)
        pg = ctx.new_page()
        pages_opened = []
        ctx.on("page", lambda np: pages_opened.append(np))
        pg.goto(base + "/static/app.html")
        pg.wait_for_function("() => { const f = document.querySelector('#stage iframe');"
                             " return f && f.contentDocument && f.contentDocument.getElementById('ck1'); }")
        pg.pages_opened = pages_opened
        yield pg
        b.close()


def _tiles(pg):
    return pg.eval_on_selector_all("#strip .tile", "els => els.map(e => e.querySelector('.name').textContent)")


def _painted_frames(pg):
    """Paths of the frames actually painted (display not none, non-zero box), top-level panes and the side pane."""
    return pg.evaluate("""() => [...document.querySelectorAll('#stage iframe')].filter(f => {
        const box = f.closest('.side') || f; const cs = getComputedStyle(box);
        return cs.display !== 'none' && f.getBoundingClientRect().width > 0;
      }).map(f => { try { return f.contentWindow.location.pathname; } catch (e) { return '?'; } })""")


def _cave(pg):
    return pg.frame_locator("#stage iframe >> nth=0")


def _focus_frame(pg, path):
    for fr in pg.frames:
        if fr.url.split("?")[0].endswith(path):
            return fr
    raise AssertionError("no frame at %s; frames: %s" % (path, [f.url for f in pg.frames]))


def _settle(pg, ms=600):
    pg.wait_for_timeout(ms)


def test_the_cave_is_first_alone_and_cannot_be_closed(page):
    assert _tiles(page) == ["Cave of Wonders"]
    assert page.locator("#strip .tile.cave .x").count() == 0
    assert _painted_frames(page) == ["/"]


def test_a_target_blank_link_on_the_cave_opens_a_tile_in_focus_not_a_window(page):
    _cave(page).locator("#ck1").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]
    assert _painted_frames(page) == ["/project/p1"]
    assert page.locator("#strip .tile.focus .name").text_content() == "MBA Teaching AI"
    assert page.pages_opened == []                      # nothing escaped to a browser window


def test_a_preopened_blank_window_gets_its_page_through_location_replace(page):
    _cave(page).locator("#pre").click()
    page.wait_for_function("() => [...document.querySelectorAll('#strip .tile .name')].some(n => n.textContent === 'Artificial Magi')")
    _settle(page)
    assert _painted_frames(page) == ["/project/p2"]
    assert page.pages_opened == []


def test_new_project_popup_answers_its_opener_and_closes_its_tile(page):
    _cave(page).locator("#np").click()
    page.wait_for_function("() => [...document.querySelectorAll('#strip .tile .name')].some(n => n.textContent === 'New project')")
    _focus_frame(page, "/newproj").locator("#make").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 1")
    _settle(page)
    assert _cave(page).locator("#got").text_content() == "created"
    assert _painted_frames(page) == ["/"]


def _open_p1(page):
    _cave(page).locator("#ck1").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    _focus_frame(page, "/project/p1").wait_for_selector("#say")
    return _focus_frame(page, "/project/p1")


def test_a_deliverable_opens_beside_its_cockpit_and_a_second_replaces_it(page):
    p1 = _open_p1(page)
    p1.locator("#deliv").click()
    page.wait_for_function("() => document.getElementById('stage').classList.contains('split')")
    _settle(page)
    assert _painted_frames(page) == ["/project/p1", "/api/steward/deliverable-file"]
    p1.locator("#rep").click()                          # the cockpit's own shim rewrites /report -> /steward/report
    page.wait_for_function("() => { const f = document.querySelector('.side iframe');"
                           " try { return f.contentWindow.location.pathname === '/steward/report'; } catch (e) { return false; } }")
    assert _painted_frames(page) == ["/project/p1", "/steward/report"]
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]      # no tile for a deliverable
    page.locator(".side .x").click()
    _settle(page, 200)
    assert _painted_frames(page) == ["/project/p1"]


def test_a_nested_frame_link_and_a_named_target_land_in_the_app(page):
    p1 = _open_p1(page)
    _focus_frame(page, "/steward/v1").locator("#nested").click()
    page.wait_for_function("() => document.getElementById('stage').classList.contains('split')")
    assert _painted_frames(page)[-1] == "/artifact/p1"
    p1.locator("#named").click()
    page.wait_for_function("() => { const f = document.querySelector('.side iframe');"
                           " try { return f.contentWindow.location.pathname === '/report/x'; } catch (e) { return false; } }")
    assert page.pages_opened == []


def test_a_download_is_not_a_tile(page):
    p1 = _open_p1(page)
    with page.expect_download() as dl:
        p1.locator("#dl").click()
    assert dl.value.suggested_filename == "Deck.pptx"
    _settle(page, 300)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]
    assert not page.evaluate("document.getElementById('stage').classList.contains('split')")


def test_cockpit_to_cockpit_keeps_the_caller_until_the_new_one_loads_then_comes_back_from_its_address(page):
    p1 = _open_p1(page)
    p1.locator("#say").fill("half a sentence")
    p1.locator("#p3").click()
    page.wait_for_function("() => [...document.querySelectorAll('#strip .tile .name')].some(n => n.textContent === 'DARPA proposal')")
    _settle(page)
    assert _painted_frames(page) == ["/project/p3"]
    # the old cockpit's frame was dropped once DARPA loaded; a click brings it back from its address
    assert page.evaluate("document.querySelectorAll('#stage > iframe').length") == 2     # the Cave + the focus
    page.locator("#strip .tile", has_text="MBA Teaching AI").click()
    page.wait_for_function("() => [...document.querySelectorAll('#stage > iframe')].some(f => { try { return f.contentWindow.location.pathname === '/project/p1' && getComputedStyle(f).display !== 'none'; } catch (e) { return false; } })")
    assert page.locator("#strip .tile.focus .name").text_content() == "MBA Teaching AI"


def test_close_returns_focus_and_drag_reorders_but_never_past_the_cave(page):
    _cave(page).locator("#ck1").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 2")
    page.locator("#strip .tile.cave").click()
    _cave(page).locator("#pre").click()
    page.wait_for_function("() => document.querySelectorAll('#strip .tile').length === 3")
    _settle(page)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI", "Artificial Magi"]
    magi = page.locator("#strip .tile", has_text="Artificial Magi").bounding_box()
    mba = page.locator("#strip .tile", has_text="MBA Teaching AI").bounding_box()
    cave = page.locator("#strip .tile.cave").bounding_box()
    page.mouse.move(magi["x"] + 20, magi["y"] + 10)
    page.mouse.down()
    page.mouse.move(mba["x"] + 10, mba["y"] + 10, steps=6)
    page.mouse.move(cave["x"] + 10, cave["y"] + 10, steps=6)                  # over the Cave: no move past it
    page.mouse.up()
    _settle(page, 200)
    assert _tiles(page) == ["Cave of Wonders", "Artificial Magi", "MBA Teaching AI"]
    page.locator("#strip .tile", has_text="Artificial Magi").locator(".x").click()
    _settle(page, 300)
    assert _tiles(page) == ["Cave of Wonders", "MBA Teaching AI"]
    assert page.locator("#strip .tile.focus").count() == 1
