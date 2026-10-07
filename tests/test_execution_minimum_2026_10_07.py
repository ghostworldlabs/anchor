"""The execution minimum set (PROPOSAL v1.1, 2026-10-07). Item 1: Next steps stable and complete, the narrow cockpit,
open at the newest message. Hermetic: a throwaway server on a free port with a temp data dir (never :8777)."""
import time

from playwright.sync_api import expect

from steward_cockpit import steward_campaign as sc
from tests.test_steward_refinement_browser import campaign_server, cockpit
from tests.test_cockpit_selected_b import open_surface


# ---------- item 1: every current product is its own row; the formats of one product are one row ----------

def test_format_tags_strip_every_spelling_the_registers_use():
    for raw, want in [("NYU Viva quick start - Refinement 1 MD", "NYU Viva quick start - Refinement 1"),
                      ("Quiz 1 - Bank - Draft 3 (PDF)", "Quiz 1 - Bank - Draft 3"),
                      ("Quiz 1 - Bank - Draft 3 (browser)", "Quiz 1 - Bank - Draft 3"),
                      ("Verification, Draft 1 (browser reading)", "Verification, Draft 1"),
                      ("Instructor Materials (TA download)", "Instructor Materials"),
                      ("Quiz-1-Viva-Guide-PDF", "Quiz-1-Viva-Guide"),
                      ("Teaching-Calendar-Report", "Teaching-Calendar-Report"),
                      ("Thermopdf", "Thermopdf")]:          # a word that merely ends in a format name keeps it
        assert sc._strip_format_tag(raw) == want, raw


def test_review_acts_one_row_per_product_with_companions():
    items = [
        {"what": "Guide - Refinement 1 MD", "path": "q/Guide - Refinement 1.md", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Refinement 1 PDF", "path": "q/Guide - Refinement 1.pdf", "step": "s1", "date": "2026-10-07"},
        {"what": "Guide - Refinement 1 HTML", "path": "q/Guide - Refinement 1.html", "step": "s1", "date": "2026-10-07"},
        {"what": "Calendar (accepted).ics", "path": "q/Calendar (accepted).ics", "step": "s1", "date": "2026-10-07"},
        {"what": "Viva-Guide-PDF", "product_id": "Viva-Guide-PDF", "managed": True, "phase": "awaiting_review",
         "path": "deliverables/Viva-Guide-PDF/a.pdf", "step": "s2"},
        {"what": "Viva-Guide-HTML", "product_id": "Viva-Guide-HTML", "managed": True, "phase": "awaiting_review",
         "path": "deliverables/Viva-Guide-HTML/b.html", "step": "s2"},
        {"what": "Bank (PDF)", "managed": True, "phase": "awaiting_review", "path": "deliverables/Bank/c.pdf", "step": "s3"},
    ]
    acts = [a for a in sc.review_acts({}, items) if a["act"] != "Next"]
    rows = [(a["act"], a["label"], a["path"], len(a.get("companions") or [])) for a in acts]
    assert rows == [
        ("Review", "Viva Guide", "deliverables/Viva-Guide-PDF/a.pdf", 1),       # reviews first; PDF is the face
        ("Review", "Bank", "deliverables/Bank/c.pdf", 0),
        ("Open", "Guide - Refinement 1", "q/Guide - Refinement 1.pdf", 2),       # three formats, one decision
        ("Open", "Calendar (accepted).ics", "q/Calendar (accepted).ics", 0),
    ]
    assert [c["path"] for c in acts[2]["companions"]] == ["q/Guide - Refinement 1.html", "q/Guide - Refinement 1.md"]
    assert acts[2]["companions"][0]["item"]["what"] == "Guide - Refinement 1 HTML"


# ---------- browser: the cockpit as John sees it ----------

def _frame(page):
    return page.frame_locator('[data-fsframe]')


def test_next_steps_rows_are_not_rebuilt_by_the_clock(cockpit):
    """A row's node survives the 1 s busy-clock repaint (it used to be rebuilt every second: icons re-created,
    clicks that spanned a rebuild swallowed, focus lost)."""
    page, server = cockpit
    surface = open_surface(page)
    body = surface.locator('[data-delivmount] .blk.next .body')
    expect(body).to_have_count(1)
    body.evaluate("b => { b.__marker = 'kept'; Array.from(b.querySelectorAll('*')).forEach(n => n.__marker = 'kept'); }")
    time.sleep(3.2)
    survivors = body.evaluate("b => Array.from(b.querySelectorAll('*')).filter(n => n.__marker === 'kept').length")
    total = body.evaluate("b => b.querySelectorAll('*').length")
    assert total > 0 and survivors == total


def test_dialogue_follows_the_newest_until_john_scrolls_up(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    scroll = surface.locator('.scroll').first
    # content arriving with no scroll event of its own (a late render) keeps the newest in view
    scroll.evaluate("""s => { for (let i = 0; i < 40; i++) { const d = document.createElement('div');
        d.style.height = '60px'; d.textContent = 'line ' + i; s.appendChild(d); } }""")
    page.wait_for_timeout(300)
    gap = scroll.evaluate("s => s.scrollHeight - s.scrollTop - s.clientHeight")
    assert gap < 5, gap
    # John scrolls up: arriving content no longer moves him
    scroll.hover()
    page.mouse.wheel(0, -600)
    page.wait_for_timeout(300)
    top = scroll.evaluate("s => s.scrollTop")
    scroll.evaluate("""s => { const d = document.createElement('div'); d.style.height = '400px'; d.textContent = 'late';
        s.appendChild(d); }""")
    page.wait_for_timeout(300)
    assert abs(scroll.evaluate("s => s.scrollTop") - top) < 2


def test_narrow_cockpit_closes_rail_and_status_for_now_only(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    app = surface.locator('.app')
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    saved = surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')")
    page.set_viewport_size({"width": 900, "height": 1000})
    expect(app).not_to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    expect(app).to_have_class(__import__('re').compile(r'\brailhide\b'))
    # reopened while narrow, the status pane overlays the dialogue instead of squeezing it
    surface.locator('[data-statustoggle]:visible,[data-statustoggle2]:visible').first.click()
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))
    assert surface.locator('.rightcol').evaluate("e => getComputedStyle(e).position") == "fixed"
    assert surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')") == saved
    surface.locator('[data-statustoggle]:visible,[data-statustoggle2]:visible').first.click()
    page.set_viewport_size({"width": 1700, "height": 1050})
    expect(app).to_have_class(__import__('re').compile(r'\bstatusopen\b'))   # his wide layout comes back as it was
    assert surface.locator('body').evaluate("() => localStorage.getItem('steward_status_pane')") == saved
