"""Check current registered readers without waking efforts or restarting Anchor."""
import json, os, sys
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, r'C:\dev\Anchor')
import launch_anchor_dashboard as launcher
from playwright.sync_api import sync_playwright

out = Path(__file__).parent
origin = 'http://127.0.0.1:8777'
pid = 'f69f6d66171f4dbd95c8c45db6846d97'
effort = 'Distribution%20and%20Collaboration'
blocked = []
proof = {'client': 'fresh driven browser; not John\'s existing native client', 'no_restart': True}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1365, 'height': 1000})

    def guard(route):
        request = route.request
        if request.method not in ('GET', 'HEAD') or 'events' in urlparse(request.url).path.lower():
            blocked.append({'method': request.method, 'path': urlparse(request.url).path})
            route.abort()
        else:
            route.continue_()

    context.route('**/*', guard)
    page = context.new_page()
    token = (os.environ.get('ANCHOR_TOKEN') or '').strip() or launcher.sob.read_onboard_token()

    def ordinary_open(url):
        page.goto(url, wait_until='domcontentloaded', timeout=25000)
        page.wait_for_function("!new URL(location.href).searchParams.has('token')", timeout=20000)

    launcher.ensure_dashboard_running(url=origin, token=token, open_fn=ordinary_open,
        start_fn=lambda: {'blocked': 'No service restart'}, retries=1)
    token = None
    page.goto(origin + '/steward/v1?pid=' + pid + '&dir=' + effort,
              wait_until='domcontentloaded', timeout=20000)
    page.locator('[data-wptile]').click()

    def open_pin(filename, expected, screenshot):
        link = page.locator('[data-nav-focus="deliverables:pin:file:' + filename + '"]')
        link.wait_for(state='visible', timeout=12000)
        with page.expect_popup(timeout=10000) as opening:
            link.click()
        reader = opening.value
        reader.wait_for_load_state('domcontentloaded')
        reader.wait_for_function('(text) => document.body.innerText.includes(text)', arg=expected, timeout=15000)
        text = reader.locator('body').inner_text()
        assert reader.evaluate('document.documentElement.scrollWidth <= innerWidth')
        reader.screenshot(path=str(out / screenshot), full_page=True)
        return reader, text

    license_reader, license_text = open_pin('GHOST-WORLD-LAB-LICENSE-v1.md',
        'Version 1, Refinement 2', 'license-reader.png')
    assert 'programming services actually performed for that customer' in license_text
    assert 'one-time price for a copy' in license_text
    assert 'continuing payments to the programmer' in license_text
    proof['license_pin'] = {'opened': True, 'refinement': 2, 'no_overflow': True,
        'path': license_reader.url.replace(origin, '')}
    review_reader, review_text = open_pin('LEGAL-BEAGLE-REVIEW-v1-REFINEMENT-2.md',
        'Citation receipt', 'review-reader.png')
    assert 'no new material payment-wording findings' in review_text.lower()
    assert 'legal-beagle receipt 6ea4054c7c0c' in review_text
    proof['review_pin'] = {'opened': True, 'completed': True, 'receipt_visible': True,
        'no_overflow': True, 'path': review_reader.url.replace(origin, '')}

    for name, expected in [
        ('GHOST-WORLD-LAB-LICENSE-v1.md', 'Version 1, Refinement 2'),
        ('LEGAL-BEAGLE-REVIEW-v1-REFINEMENT-2.md', 'no new material payment-wording findings'),
        ('versions%2FGHOST-WORLD-LAB-LICENSE-v1-REFINEMENT-1.md', 'Version 1, Refinement 1'),
        ('journal%2F0009-ghost-world-lab-license-2026-10-04.md', 'focused Refinement 2 payment review')]:
        target = context.new_page()
        route = '/artifact/' + pid + '?path=' + effort + '%2F' + name + '&render=1'
        response = target.goto(origin + route, wait_until='domcontentloaded', timeout=20000)
        assert response.status == 200
        assert expected.lower() in target.locator('body').inner_text().lower()
        proof[name] = {'status': 200, 'content_verified': True, 'path': route,
            'heading': target.locator('h1').all_text_contents()}

    # Follow the actual preserved-version link from the current license.
    history = license_reader.get_by_role('link', name='Earlier license Refinement 1', exact=True)
    history.wait_for(state='attached')
    with license_reader.expect_popup(timeout=10000) as earlier_open:
        history.click()
    earlier = earlier_open.value
    earlier.wait_for_load_state('domcontentloaded')
    assert 'Version 1, Refinement 1' in earlier.locator('body').inner_text()
    proof['history_link_opened'] = True
    proof['blocked_writes_and_event_soft_wakes'] = blocked
    (out / 'reader-proof.json').write_text(json.dumps(proof, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(proof))
    browser.close()
