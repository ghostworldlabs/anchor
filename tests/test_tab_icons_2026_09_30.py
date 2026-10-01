"""The tab icons (John, 2026-09-30, twice: "where did the icons go for the web page tabs?" / "The icons in the web page tabs
are missing, can you please put those back?"): the High Seat and the Campaign page linked the stewards' 1024-px JPEGs
(0.7-0.9 MB) as the tab icon, which a browser tab does not take. A small PNG made from each steward's two images stands
as the tab icon; the pages link it with its type and size; an SVG is linked as it is."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import campaign_page as cpg  # noqa: E402
import high_seat_page as hsp  # noqa: E402
import test_active_set_w1_2026_09_29 as w1  # noqa: E402
import test_active_set_w2_2026_09_29 as w2  # noqa: E402
import test_high_seat_page_2026_09_26 as base  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(HERE, "vendor", "brand")


def test_every_steward_s_two_images_have_a_small_png_beside_them():
    for stem in ("aladdin-high-seat-cave", "aladdin-seal-lamp", "jarvis-high-seat-hat", "jarvis-seal-salver", "ecgberht-portfolio-high-seat", "ecgberht-project-seal"):
        png = os.path.join(BRAND, stem + ".png")
        assert os.path.isfile(png) and 200 < os.path.getsize(png) < 60000, stem
        with open(png, "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n", stem


def test_the_pages_link_the_small_png_as_the_tab_icon():
    assert hsp.tab_icon_link("aladdin-high-seat-cave.jpg", "b1") == '<link rel="icon" href="/vendor/brand/aladdin-high-seat-cave.png?v=b1" type="image/png" sizes="64x64">'
    assert hsp.tab_icon_link("gwl-m-icon.svg", "b1") == '<link rel="icon" href="/vendor/brand/gwl-m-icon.svg?v=b1" type="image/svg+xml">'
    assert hsp.tab_icon_link("no-such-image.jpg", "b1") == '<link rel="icon" href="/vendor/brand/no-such-image.jpg?v=b1" type="image/jpeg">', "no PNG: the image as it is"
    assert hsp.tab_icon_link(None, "b1").startswith('<link rel="icon" href="/vendor/brand/gwl-m-icon.svg')
    html = hsp.render_high_seat_html(base._ctx())
    assert '<link rel="icon" href="/vendor/brand/jarvis-high-seat-hat.png?v=test" type="image/png" sizes="64x64">' in html
    ctx = w2._ctx(w1._steps()); ctx["steward"] = dict(ctx["steward"], seal="aladdin-seal-lamp.jpg")
    html = cpg.render_campaign_html(ctx)
    assert '<link rel="icon" href="/vendor/brand/aladdin-seal-lamp.png?v=' in html and ".jpg?v=" not in html[:html.index("<body")]


def test_the_two_page_icons_are_legible_at_tab_size():
    """John, 2026-10-01: "put the icons back up in the tabs of the web pages" - the pages linked the PNGs all along and
    the browsers fetched them, but the shrunken paintings read as dark squares on a dark tab bar. The icons are now
    bright amber tiles with the steward's initial: 64 px (the size the link declares) and bright at 16 px. The two tabs
    are told apart by a mark that survives tab size (Grok W3): the High Seat's is a SQUARE tile (the hall), a project's
    seal is a ROUND one - at 16 px the seal's corners are transparent and the tile's are not."""
    import pytest
    PIL = pytest.importorskip("PIL.Image")
    corners = {}
    for stem in ("aladdin-high-seat-cave", "aladdin-seal-lamp"):
        im = PIL.open(os.path.join(BRAND, stem + ".png")).convert("RGBA")
        assert im.size == (64, 64), stem
        small = im.resize((16, 16))
        px = [p for p in small.getdata() if p[3] > 0]
        lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _a in px) / len(px)
        assert lum >= 100, "%s reads dark at tab size: %d" % (stem, lum)
        corners[stem] = small.getpixel((0, 0))[3]
    assert corners["aladdin-high-seat-cave"] > 128 and corners["aladdin-seal-lamp"] == 0, "the square tile and the round seal must read apart at 16 px: %r" % corners
    assert 'sizes="64x64"' in hsp.tab_icon_link("aladdin-high-seat-cave.jpg", "b1")
