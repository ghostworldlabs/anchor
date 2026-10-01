"""His anchor on EVERY tab (John, 2026-10-01 14:1x, his fourth ask: "where are my icons in Chrome tabs? I have asked for
this a number of times"). What his tab strip showed when it was captured, not what the server sent: the anchor WAS on
the two live Cave of Wonders tabs, but his export scaled to 16 px is a dark stroke on black on a dark tab strip - it read
as no icon; the Desk still linked the lamp painting; the cockpit linked /anchor.ico with no version (Chrome keeps a tab
icon it has seen for a week); the status pages and previews open from disk carried no icon at all.

Here: one rule at the one door every page leaves by (``with_tab_icon`` in ``_send_html``), the Desk on the same link as
the other two pages, and the tab drawing of his anchor (anchor-tab.*) worn in the tab when it is there."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import desk_page as dpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_desk_page_2026_09_26 as desk  # noqa: E402
from test_tab_icons_2026_09_30 import anchor_set  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(HERE, "vendor", "brand")
STEM = hsp.anchor_tab_stem()


def test_a_page_with_no_icon_gets_the_anchor_set_right_after_its_head_opens():
    page = '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>A report</title></head><body>x</body></html>'
    out = hsp.with_tab_icon(page, "b7")
    assert out == page.replace('<head>', '<head>' + anchor_set(STEM, "b7")), out[:400]
    assert hsp.with_tab_icon(out, "b7") == out, "said once: a page that wears the set is left"


def test_the_old_anchor_links_become_the_set_with_the_build_in_the_address():
    cockpit = open(os.path.join(HERE, "steward_cockpit", "static", "cockpit.html"), encoding="utf-8").read()
    assert '<link rel="icon" href="/anchor.ico" type="image/x-icon">' in cockpit, "the cockpit's own link, with no version"
    out = hsp.with_tab_icon(cockpit, "b7")
    head = out[:out.index("</head")]
    assert anchor_set(STEM, "b7") in head and "/anchor.ico" not in head
    dash = ('<html><head>\n<title>Anchor</title>\n<link rel="icon" href="/anchor.ico?v=b6" type="image/x-icon">\n'
            '<link rel="icon" href="/anchor.png?v=b6" type="image/png" sizes="256x256">\n<link rel="apple-touch-icon" href="/anchor-touch.png?v=2026-05-11">\n</head><body></body></html>')
    out = hsp.with_tab_icon(dash, "b7")
    assert out.count('rel="icon"') == 3 and out.count("apple-touch-icon") == 1 and "/anchor.ico" not in out and "/anchor.png" not in out and "anchor-touch" not in out


def test_a_page_with_a_mark_of_its_own_keeps_it_and_a_fragment_is_left():
    tool = '<!doctype html><html><head><title>Tidy</title><link rel="icon" href="/vendor/brand/tidy-idy-icon.jpg" type="image/jpeg"/></head><body></body></html>'
    assert hsp.with_tab_icon(tool, "b7") == tool
    assert hsp.with_tab_icon("<div>a part of a page</div>", "b7") == "<div>a part of a page</div>"
    late = "<html><head><title>t</title></head><body>" + ("x" * 9000) + '<link rel="icon" href="/x.png"></body></html>'
    assert anchor_set(STEM, "b7") in hsp.with_tab_icon(late, "b7"), "only the head is read"


def test_the_desk_wears_the_same_link_as_the_high_seat_and_the_campaign():
    html = dpg.render_desk_html(desk._ctx())
    head = html[:html.index("<body")]
    assert "<title>The Desk</title>" + anchor_set(STEM, "test") in head and ".jpg?v=" not in head


def test_the_one_door_and_the_default_favicon_are_wired():
    gui = open(os.path.join(HERE, "anchor_gui.py"), encoding="utf-8").read()
    door = gui[gui.index("    def _send_html(self, html_text, cookie=None):"):]
    door = door[:door.index("    def _send_bytes(")]
    assert "html_text = _with_tab_icon(html_text, BUILD_ID)" in door and door.index("_with_tab_icon(html_text, BUILD_ID)") < door.index('body = html_text.encode("utf-8")')
    assert '_tab_ico = ANCHOR_DIR / "vendor" / "brand" / "anchor-tab.ico"' in gui, "/favicon.ico serves the tab drawing when it is there"


def test_the_tab_drawing_is_worn_when_it_is_there_and_his_export_otherwise(tmp_path):
    for f in ("anchor-icon.ico", "anchor-icon-32.png"):
        (tmp_path / f).write_bytes(b"x")
    assert hsp.anchor_tab_stem(tmp_path) == "anchor-icon"
    for f in ("anchor-tab.ico", "anchor-tab-32.png"):
        (tmp_path / f).write_bytes(b"x")
    assert hsp.anchor_tab_stem(tmp_path) == "anchor-icon", "a half-made tab set is not worn"
    (tmp_path / "anchor-tab-16.png").write_bytes(b"x")
    assert hsp.anchor_tab_stem(tmp_path) == "anchor-tab"
    assert hsp.anchor_tab_stem(tmp_path / "nowhere") is None


def test_the_tab_drawing_reads_at_tab_size():
    """The measure his export failed: at 16 px, on a dark tab strip, the icon must be a bright shape. Runs once the tab
    drawing is installed (his pick among the candidates, 2026-10-01)."""
    import pytest
    PIL = pytest.importorskip("PIL.Image")
    if STEM != "anchor-tab":
        pytest.skip("the tab drawing is not installed yet")
    for n in (16, 32):
        im = PIL.open(os.path.join(BRAND, "anchor-tab-%d.png" % n)).convert("RGBA")
        assert im.size == (n, n)
        px = [p for p in im.getdata() if p[3] > 0]
        lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _a in px) / len(px)
        assert lum >= 90, "the %d px drawing reads dark: %d" % (n, lum)
    his = PIL.open(os.path.join(BRAND, "anchor-icon-16.png")).convert("RGBA")
    dark = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _a in his.getdata()) / (16 * 16)
    assert dark < 60, "his export at 16 px is the dark one the drawing stands in for (%d)" % dark
    with open(os.path.join(BRAND, "anchor-tab.ico"), "rb") as f:
        assert f.read(4) == b"\x00\x00\x01\x00", "an ICO"
