"""Inspect the exact registered prototype through Anchor's normal signed-in route."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8777'
PID = 'f69f6d66171f4dbd95c8c45db6846d97'
ROOT = Path(__file__).resolve().parent.parent
COCKPIT = f'/steward/v1?pid={PID}&dir=Setup%20and%20Mother%20Ship'
checks = []
errors = []
requests = []

def check(name, condition):
    checks.append({'check': name, 'passed': bool(condition)})
    assert condition, name

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1500, 'height': 1050})
    page = context.new_page()
    page.goto(BASE + '/high-seat', wait_until='domcontentloaded')
    if page.locator('#loginBox').is_visible():
        page.locator('#loginTok').fill(os.environ['ANCHOR_TOKEN'])
        with page.expect_navigation(wait_until='domcontentloaded'):
            page.locator('#loginGo').click()
    context.route('**/api/**', lambda route: route.abort() if route.request.method != 'GET' else route.continue_())
    page.goto(BASE + COCKPIT, wait_until='domcontentloaded')
    link = page.locator('[data-delivmount] a').filter(has_text='Provider setup mockup').first
    link.wait_for(state='visible', timeout=20000)
    check('exact Initial draft visible in Current work', 'Initial draft' in link.inner_text())
    with context.expect_page() as opening:
        link.click()
    mock = opening.value
    mock.wait_for_load_state('domcontentloaded')
    mock.locator('#routing-best').wait_for(state='visible')
    parsed = urlsplit(mock.url)
    query = parse_qs(parsed.query)
    check('workflow opens exact HTML route and effort', parsed.path == '/api/steward/deliverable-file' and query.get('path') == ['mockups/PROVIDER-SETUP-initial.html'] and query.get('pid') == [PID] and query.get('dir') == ['Setup and Mother Ship'])
    mock.on('pageerror', lambda e: errors.append(str(e)))
    mock.on('request', lambda r: requests.append({'method': r.method, 'url': r.url, 'resource_type': r.resource_type}))
    text = lambda selector: mock.locator(selector).inner_text()
    cls = lambda selector: mock.locator(selector).get_attribute('class')
    check('example labels and best-available default', 'Initial draft' in text('.mockup-banner') and mock.locator('#routing-best').is_checked())
    check('initial subscription allowance and separate unknown API cost', '64%' in text('#subscription-value') and text('#api-value') == 'Not reported')
    check('Cave capacity and model controls stay within the desktop viewport', mock.locator('#capacity-tile').bounding_box()['y'] + mock.locator('#capacity-tile').bounding_box()['height'] <= 1050 and mock.locator('#model-control').bounding_box()['y'] + mock.locator('#model-control').bounding_box()['height'] <= 1050)
    mock.screenshot(path=str(ROOT / '.ecgberht/provider-mockup-desktop.png'), full_page=True)
    for situation, expected in [('near', 'status-near'), ('out', 'status-out'), ('unknown', 'status-unknown'), ('usable', 'status-good')]:
        mock.locator('#situation-select').select_option(situation)
        check(situation + ' changes the compact tile', expected in cls('#capacity-tile'))
        if situation == 'unknown':
            check('unknown capacity remains separate from signed-in state', text('#tile-value') == 'Not reported' and 'Connected' in text('#auth-status') and 'Not reported' in text('#subscription-window'))
        if situation == 'out':
            check('exhausted subscription offers a connected alternate', mock.locator('#use-alternate').is_visible() and 'ChatGPT' in text('#use-alternate'))
    mock.locator('#route-api').click()
    check('subscription and API sign-in states separate', 'Not connected' in text('#auth-status') and '64%' in text('#subscription-value'))
    mock.locator('#demo-connect').click()
    check('API demo connects without credentials', 'Connected' in text('#auth-status') and text('#api-value') == '$3.42' and '128k' in text('#api-usage') and 'Balance · Not reported' in text('#api-usage'))
    check('API capacity explicitly means own budget', 'personal api budget' in text('#tile-route').casefold() and '$20 personal budget' in text('#api-budget'))
    mock.locator('#refresh-demo').click()
    check('missing report leaves cost and capacity unknown', text('#api-value') == 'Not reported' and text('#tile-value') == 'Not reported' and 'Source: no usage report' in text('#report-source'))
    mock.locator('#provider-gemini').click()
    check('provider authentication state independent', 'Not connected' in text('#auth-status'))
    mock.locator('#demo-connect').click()
    mock.locator('#routing-manual').check()
    mock.locator('#manual-provider').select_option('gemini')
    mock.locator('#model-select').select_option('Balanced (example)')
    mock.locator('#reasoning-select').select_option('Extended')
    check('chosen model and reasoning update Cave control', 'Balanced' in text('#chip-model') and 'Gemini' in text('#chip-provider') and 'Extended' in text('#chip-provider'))
    mock.locator('#situation-select').select_option('out')
    check('manual exhausted provider excluded from confirmed capacity', 'No provider with confirmed capacity' in text('#model-readout'))
    mock.locator('#use-alternate').click()
    check('alternate switches model provider', 'ChatGPT' in text('#chip-provider'))
    mock.locator('#setup-open').click()
    check('Setup reuses connected providers', mock.locator('#setup-view').is_visible() and 'subscription' in text('#setup-subscription-summary') and 'API connection' in text('#setup-api-summary'))
    mock.locator('#panel-done').click()
    mock.locator('#setup-reopen').click()
    check('Setup completion and reopening use same demo', mock.locator('#setup-done').is_visible() and mock.locator('#provider-panel').is_visible())
    mock.locator('#mode-cave').click()
    mock.locator('#capacity-tile').click()
    mock.keyboard.press('Escape')
    check('Escape dismisses detail and returns focus', mock.locator('#provider-panel').is_hidden() and mock.evaluate('document.activeElement.id') == 'capacity-tile')
    mock.locator('#capacity-tile').click()
    mock.locator('#provider-chatgpt').focus()
    mock.keyboard.press('ArrowRight')
    check('keyboard navigation selects next provider', mock.locator('#provider-gemini').get_attribute('aria-selected') == 'true')
    check('desktop has no horizontal overflow', mock.evaluate('document.documentElement.scrollWidth <= innerWidth'))
    mock.reload(wait_until='domcontentloaded')
    mock.set_viewport_size({'width': 400, 'height': 900})
    check('phone has no horizontal overflow', mock.evaluate('document.documentElement.scrollWidth <= innerWidth'))
    mock.screenshot(path=str(ROOT / '.ecgberht/provider-mockup-mobile.png'), full_page=True)
    prototype_requests = [r for r in requests if r['resource_type'] != 'document']
    check('interactive prototype made no network requests', not prototype_requests)
    check('no JavaScript errors during interactions', not errors)
    route = parsed.path + '?' + parsed.query
    receipt = {'checked_at': datetime.now(timezone.utc).isoformat(), 'surface': 'normal authenticated fresh Chromium, exact Anchor Current work click and sandboxed HTML route', 'route': route, 'checks': checks, 'errors': errors, 'prototype_requests': prototype_requests, 'document_requests': [r for r in requests if r['resource_type'] == 'document'], 'screenshots': ['.ecgberht/provider-mockup-desktop.png', '.ecgberht/provider-mockup-mobile.png'], 'limitations': 'Fresh driven browser; not a capture of John\'s already-open client. Example values only; no live provider authentication/usage tested. Human design acceptance remains open.'}
    (ROOT / '.ecgberht/provider-mockup-check.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': len(checks), 'route': route, 'screenshots': receipt['screenshots']}))
    browser.close()
