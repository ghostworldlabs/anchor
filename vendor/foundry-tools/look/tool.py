"""look: screenshots of a page or HTML file at phone and desktop size, and whether named elements are visibly laid out.

  ft.py look <file.html|url> [--check "<css>"]... [--click "<css>"]... [--size phone|tablet|desktop|WxH]...
             [--out <folder>] [--full] [--wait-ms N]

Prints one line per size: the screenshot path, page errors, and for each --check selector whether it is LAID OUT
VISIBLY (non-zero size, not display:none / visibility:hidden / opacity 0 on it or a parent) and, when on screen,
whether something else covers its centre - John's rule: verify what is shown, never the attribute. Look at the
screenshot for the rest. This is a fresh browser, not John's own window. Screenshots go to a temp folder by default,
never into the repository. Anchor's own pages (port 8777) are refused unless --allow-anchor: opening a cockpit page
can wake its steward."""
import argparse
import os
import re
import urllib.parse
import json
import sys
import tempfile
import time
from pathlib import Path

MAX_HOPS = 10
REDIRECTS = (301, 302, 303, 307, 308)
ANCHOR_PORT = int(os.environ.get("LOOK_ANCHOR_PORT") or 8777)    # tests point it at a stand-in
SIZES = {"phone": (390, 844), "tablet": (820, 1180), "desktop": (1440, 900)}

PAINTED_JS = """sel => Array.from(document.querySelectorAll(sel)).slice(0, 20).map(el => {
  const cs = getComputedStyle(el), r = el.getBoundingClientRect();
  // visibility is inherited and a child may override it, so only the element's own computed value counts (review r9);
  // display:none and opacity:0 on any ancestor hide it whatever it says
  let hiddenBy = (cs.visibility === 'hidden' || cs.visibility === 'collapse') ? 'visibility:' + cs.visibility : null;
  for (let n = el; !hiddenBy && n && n.nodeType === 1; n = n.parentElement) {
    const s = getComputedStyle(n);
    if (s.display === 'none') { hiddenBy = 'display:none on ' + (n.id ? '#' + n.id : n.tagName.toLowerCase()); break; }
    if (parseFloat(s.opacity) === 0) { hiddenBy = 'opacity:0 on ' + (n.id ? '#' + n.id : n.tagName.toLowerCase()); break; }
  }
  const sized = r.width > 0 && r.height > 0;
  let coveredBy = null;
  if (!hiddenBy && sized) {
    const cx = Math.min(Math.max(r.left + r.width / 2, 0), innerWidth - 1), cy = Math.min(Math.max(r.top + r.height / 2, 0), innerHeight - 1);
    const top = (r.bottom > 0 && r.top < innerHeight) ? document.elementFromPoint(cx, cy) : null;
    if (top && top !== el && !el.contains(top) && !top.contains(el))
      coveredBy = top.id ? '#' + top.id : top.tagName.toLowerCase() + (top.className && typeof top.className === 'string' ? '.' + top.className.split(' ')[0] : '');
  }
  return {painted: !hiddenBy && sized, coveredBy, hiddenBy: hiddenBy || (sized ? null : 'zero size'),
          hiddenAttr: el.hasAttribute('hidden'), display: cs.display,
          box: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
          onScreen: r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth,
          text: (el.innerText || '').trim().slice(0, 60)};
})"""


# A screenshot needs no live connection. Turned off in every page and frame before its scripts run, so no WebSocket,
# worker or event stream can reach Anchor (Playwright's WebSocket routing hangs page loads here, and Chromium's URL
# blocking does not cover WebSockets - both tried 2026-10-12).
LIVE_OFF = """(() => { const off = name => { try { Object.defineProperty(globalThis, name, { value: function () {
  throw new Error('look: ' + name + ' is off in screenshots'); }, configurable: false, writable: false }); } catch (e) {} };
  ['WebSocket', 'WebSocketStream', 'Worker', 'SharedWorker', 'WebTransport', 'EventSource'].forEach(off); })();"""


def unsafe(url):
    """Refused: Anchor itself, or an address a browser might read differently from Python (review r4 #1) - a
    backslash, an '@' (user info), whitespace or control characters - so no parser disagreement can reach Anchor."""
    if is_anchor(url):
        return True
    if "\\" in url or any(ord(c) < 33 or ord(c) == 127 for c in url):
        return True
    rest = url.split("://", 1)[1] if "://" in url else ""
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    return "@" in authority


def is_anchor(url):
    """Anchor's own server: port 8777 however it is written (08777 normalises to it) - checked for the page and for
    every request it makes, redirects included (review r1 #3)."""
    try:
        parts = urllib.parse.urlsplit(url)
        return parts.scheme in ("http", "https", "ws", "wss") and parts.port == ANCHOR_PORT
    except ValueError:
        return False


def size_of(s):
    if s in SIZES:
        return s, SIZES[s]
    w, h = s.lower().split("x")
    return s, (int(w), int(h))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target")
    ap.add_argument("--check", action="append", default=[])
    ap.add_argument("--click", action="append", default=[])
    ap.add_argument("--size", action="append", default=[])
    ap.add_argument("--out")
    ap.add_argument("--full", action="store_true", help="the whole page, not just the screen")
    ap.add_argument("--wait-ms", type=int, default=300)
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    ap.add_argument("--allow-anchor", action="store_true", help="allow Anchor's own pages on port 8777")
    a = ap.parse_args(argv)
    p = Path(a.target)
    url = p.resolve().as_uri() if p.exists() else a.target
    if is_anchor(url) and not a.allow_anchor:
        print("refused: %s is Anchor itself - opening a cockpit page can wake its steward; add --allow-anchor if "
              "that is intended" % url)
        return 2
    out = Path(a.out) if a.out else Path(tempfile.mkdtemp(prefix="look-"))
    out.mkdir(parents=True, exist_ok=True)
    stem = (p.stem if p.exists() else "page")[:40]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("look needs Python Playwright (pip install playwright; playwright install chromium)")
        return 1
    results = []
    t0 = time.time()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for name, (w, h) in [size_of(s) for s in (a.size or ["phone", "desktop"])]:
                # the guard sits on the whole context (popups included) with service workers blocked; every request
                # and every redirect hop is checked - a redirect toward Anchor aborts the navigation (review r2 #2)
                ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
                ctx.add_init_script(LIVE_OFF)              # review r5 #1: no live connection can leave a screenshot
                blocked, hops, skipped = [], {}, []
                if not a.allow_anchor:
                    # review r3 #1: Chromium never follows a redirect here. look fetches every http(s) response
                    # itself without following redirects and walks the chain hop by hop (each hop checked, at most
                    # MAX_HOPS, an unfinished chain refused). A sub-resource gets the chain's final response; a page
                    # navigation is stopped at the redirect and look opens the checked next address itself.
                    def guard(route, _request=None, blocked=blocked, hops=hops):
                        req = route.request
                        url = req.url
                        main_nav = req.is_navigation_request() and req.frame == page.main_frame
                        if unsafe(url):
                            blocked.append(url)
                            if main_nav:
                                hops["exhausted"] = True          # review r12 #1: a refused page is never shot
                            route.abort()
                            return
                        if not url.lower().startswith(("http:", "https:")):
                            route.continue_()
                            return
                        try:
                            resp = route.fetch(max_redirects=0)
                        except Exception:
                            route.abort()
                            return
                        loc = resp.headers.get("location")
                        if resp.status in REDIRECTS and loc:                # review r13 #2: 300 is a page, not a redirect
                            nxt = urllib.parse.urljoin(url, loc)
                            if main_nav and "#" not in loc and hops.get("frag"):
                                nxt += "#" + hops["frag"]          # review r12 #2: a redirect keeps the '#part' asked for
                            if unsafe(nxt) or not nxt.lower().startswith(("http:", "https:")):   # review r10 #1
                                blocked.append(nxt)
                                if req.is_navigation_request() and req.frame == page.main_frame:
                                    hops["exhausted"] = True          # review r11 #1: the page is refused, not shot
                                route.abort()
                            elif req.method != "GET" and resp.status in (307, 308):
                                skipped.append(url + " (a form redirect that would resend its data; not followed)")
                                route.abort()               # review r5 #2: never replay a form's data
                            elif req.is_navigation_request() and req.frame == page.main_frame:
                                hops["next"] = nxt          # an empty page now; look opens nxt itself next
                                route.fulfill(status=200, content_type="text/html", body="")
                            else:
                                skipped.append(url)         # a redirected image or script is left out, and said
                                route.abort()
                            return
                        route.fulfill(response=resp)
                    ctx.route("**/*", guard)

                page = ctx.new_page()
                page.on("popup", lambda pg: pg.close())
                errors = []
                page.on("pageerror", lambda e, errors=errors: errors.append(str(e)[:200]))
                page.on("console", lambda m, errors=errors: errors.append(m.text[:200]) if m.type == "error" else None)
                def visit(target, first=True):
                    """Open target (or, after a click, the page it led to), following checked redirects."""
                    try:
                        for _ in range(MAX_HOPS + 2):
                            if first:
                                hops.pop("next", None)
                                hops["frag"] = urllib.parse.urlsplit(target).fragment
                                page.goto(target, wait_until="load", timeout=30000)
                            first = True
                            if "next" not in hops:
                                return
                            target = hops.pop("next")
                            hops["frag"] = urllib.parse.urlsplit(target).fragment
                            page.goto("about:blank")              # review r11 #2: a '#part' redirect loads a document
                        raise RuntimeError("more than %d redirects" % MAX_HOPS)
                    except Exception:
                        hops["exhausted"] = True             # review r7/r8: remembered even when a caller catches it
                        raise

                failed = None
                try:
                    visit(url)
                except Exception as e:
                    failed = e
                if failed is not None:
                    if blocked and not blocked[0].lower().startswith(("http:", "https:", "ws:", "wss:")):
                        why = "refused: it redirects to a local address (%s), not a web page" % blocked[0]
                    elif blocked:
                        why = "refused: it redirects to Anchor itself (%s)" % blocked[0]
                    else:
                        why = "could not open: %s" % str(failed).splitlines()[0][:200]
                    results.append({"size": name, "error": why})
                    ctx.close()
                    continue
                for c in a.click:
                    try:
                        hops.pop("next", None)
                        hops["frag"] = ""                       # review r13 #1: a click's own address decides its '#part'
                        page.click(c, timeout=5000)
                        page.wait_for_load_state("load", timeout=10000)
                        visit(None, first=False)          # a click that redirected: follow it, checked (review r4 #3)
                    except Exception as e:
                        errors.append("click %s failed: %s" % (c, str(e).splitlines()[0][:150]))
                hops["frag"] = ""                               # a timer's navigation: no inherited '#part' either
                page.wait_for_timeout(a.wait_ms)
                for _ in range(3):                         # review r5 #3: a late redirect is followed before looking
                    if "next" not in hops:
                        break
                    try:
                        visit(None, first=False)
                        page.wait_for_timeout(a.wait_ms)
                    except Exception as e:
                        errors.append("a late redirect could not be followed: %s" % str(e).splitlines()[0][:150])
                        break
                if "next" in hops or hops.get("exhausted"):   # review r6 #2, r7: never a blank placeholder passed off as the page
                    if blocked:
                        why = "refused: it redirects to %s (%s); no screenshot" % (
                            "Anchor itself" if is_anchor(blocked[-1]) else "an address look will not open", blocked[-1])
                    else:
                        why = ("the page's redirect did not finish - it kept redirecting or failed (%s); no screenshot"
                               % hops.get("next", "see the errors above"))
                    results.append({"size": name, "error": why})
                    ctx.close()
                    continue
                shot = out / ("%s-%s.png" % (stem, name))
                page.screenshot(path=str(shot), full_page=a.full)
                checks = {c: page.evaluate(PAINTED_JS, c) for c in a.check}
                errors += ["blocked a request to Anchor itself: %s" % u for u in blocked[:3]]
                errors += ["left out a redirected resource: %s" % u for u in skipped[:3]]
                results.append({"size": name, "viewport": [w, h], "screenshot": str(shot), "errors": errors,
                                "checks": checks})
                ctx.close()
        finally:
            browser.close()
    if a.json:
        print(json.dumps({"seconds": round(time.time() - t0, 1), "results": results}, indent=1))
        return 0 if all("error" not in r for r in results) else 1
    bad = False
    for r in results:
        if "error" in r:
            bad = True
            print("%-8s %s" % (r["size"], r["error"]))
            continue
        print("%-8s %s  (page errors: %d)" % (r["size"], r["screenshot"], len(r["errors"])))
        for e in r["errors"][:5]:
            print("           error: %s" % e)
        for sel, els in r["checks"].items():
            if not els:
                print("           %s: NOT FOUND" % sel)
                continue
            for i, el in enumerate(els):
                tag = "" if len(els) == 1 else "[%d]" % i
                if el["painted"] and el.get("coveredBy"):
                    print("           %s%s: laid out, but %s is on top at its centre (a hit test - check the screenshot)" % (sel, tag, el["coveredBy"]))
                elif el["painted"]:
                    print("           %s%s: visible %s%s%s" % (sel, tag, "x".join(map(str, el["box"][2:])),
                                                           "" if el["onScreen"] else " (below the fold)",
                                                           " - SHOWN DESPITE its hidden attribute (display:%s)"
                                                           % el["display"] if el["hiddenAttr"] else ""))
                else:
                    print("           %s%s: NOT visible (%s)%s" % (sel, tag, el["hiddenBy"],
                                                               "; has hidden attribute" if el["hiddenAttr"] else ""))
    print("done in %.1f s" % (time.time() - t0))
    return 1 if bad else 0


def guarded(argv):
    """review r14 #1: a page can stall the browser forever (a script that never returns). look runs itself as a
    child with a hard time limit and, on expiry, ends the child and its browser and says so - it never hangs."""
    limit = float(os.environ.get("LOOK_MAX_S") or 120)
    import subprocess
    child = subprocess.Popen([sys.executable, os.path.abspath(__file__)] + argv,
                             env=dict(os.environ, LOOK_CHILD="1"))
    try:
        return child.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True)
        else:
            child.kill()
        child.wait()
        print("look gave up after %.0f s - the page never finished (nothing was captured)" % limit)
        return 3


if __name__ == "__main__":
    sys.exit(main() if os.environ.get("LOOK_CHILD") else guarded(sys.argv[1:]))
