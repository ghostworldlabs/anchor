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
        assert os.path.isfile(png) and 2000 < os.path.getsize(png) < 60000, stem
        with open(png, "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n", stem


def test_the_pages_link_the_small_png_as_the_tab_icon():
    assert hsp.tab_icon_link("aladdin-high-seat-cave.jpg", "b1") == '<link rel="icon" href="/vendor/brand/aladdin-high-seat-cave.png?v=b1" type="image/png" sizes="128x128">'
    assert hsp.tab_icon_link("gwl-m-icon.svg", "b1") == '<link rel="icon" href="/vendor/brand/gwl-m-icon.svg?v=b1" type="image/svg+xml">'
    assert hsp.tab_icon_link("no-such-image.jpg", "b1") == '<link rel="icon" href="/vendor/brand/no-such-image.jpg?v=b1" type="image/jpeg">', "no PNG: the image as it is"
    assert hsp.tab_icon_link(None, "b1").startswith('<link rel="icon" href="/vendor/brand/gwl-m-icon.svg')
    html = hsp.render_high_seat_html(base._ctx())
    assert '<link rel="icon" href="/vendor/brand/jarvis-high-seat-hat.png?v=test" type="image/png" sizes="128x128">' in html
    ctx = w2._ctx(w1._steps()); ctx["steward"] = dict(ctx["steward"], seal="aladdin-seal-lamp.jpg")
    html = cpg.render_campaign_html(ctx)
    assert '<link rel="icon" href="/vendor/brand/aladdin-seal-lamp.png?v=' in html and ".jpg?v=" not in html[:html.index("<body")]
