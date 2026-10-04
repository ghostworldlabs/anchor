"""Verify the registered license through normal live Anchor controls; no session restarts."""
import sys, json, os
from pathlib import Path

sys.path.insert(0, r'C:\dev\Anchor')
import launch_anchor_dashboard as launcher
from playwright.sync_api import sync_playwright

out = Path(__file__).parent
origin = 'http://127.0.0.1:8777'
pid = 'f69f6d66171f4dbd95c8c45db6846d97'
rel = 'Distribution%20and%20Collaboration'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1365, 'height': 1000})
    page = context.new_page()
    token = (os.environ.get('ANCHOR_TOKEN') or '').strip() or launcher.sob.read_onboard_token()

    def ordinary_open(url):
        page.goto(url, wait_until='domcontentloaded', timeout=25000)
        page.wait_for_function("!new URL(location.href).searchParams.has('token')", timeout=20000)

    launcher.ensure_dashboard_running(url=origin, token=token, open_fn=ordinary_open,
        start_fn=lambda: {'blocked': 'No service restart'}, retries=1)
    token = None
    page.goto(origin + '/steward/v1?pid=' + pid + '&dir=' + rel,
              wait_until='domcontentloaded', timeout=20000)
    page.locator('[data-wptile]').click()
    page.wait_for_timeout(300)
    license_link = page.locator('[data-nav-focus="deliverables:pin:file:GHOST-WORLD-LAB-LICENSE-v1.md"]')
    license_link.wait_for(state='visible', timeout=10000)
    with page.expect_popup(timeout=10000) as opening:
        license_link.click()
    reader = opening.value
    reader.wait_for_load_state('domcontentloaded')
    reader.wait_for_function("document.body.innerText.includes('Plain-English companion')", timeout=15000)
    reader_text = reader.locator('body').inner_text()
    reader.screenshot(path=str(out/'license-reader.png'), full_page=True)
    report = {'workflow_title': page.title(), 'license_pin_opened': True,
        'reader_path': reader.url.replace(origin, ''),
        'instrument_present': 'End of proposed instrument' in reader_text,
        'companion_present': 'Plain-English companion' in reader_text,
        'clauses_present': 'Compliance and termination' in reader_text,
        'no_horizontal_overflow': reader.evaluate('document.documentElement.scrollWidth <= innerWidth')}
    assert all(report[k] for k in ('instrument_present','companion_present','clauses_present','no_horizontal_overflow'))
    artifact = context.new_page()
    exact = '/artifact/' + pid + '?path=Distribution%20and%20Collaboration%2FGHOST-WORLD-LAB-LICENSE-v1.md&render=1'
    response = artifact.goto(origin+exact, wait_until='domcontentloaded', timeout=20000)
    report['conversation_link'] = exact
    report['conversation_target_status'] = response.status
    report['conversation_target_has_license'] = 'Ghost World Lab License' in artifact.locator('body').inner_text()
    report['conversation_target_heading'] = artifact.locator('h1').all_text_contents()
    artifact.screenshot(path=str(out/'conversation-target.png'), full_page=True)
    review_link = page.locator('[data-nav-focus="deliverables:pin:file:LEGAL-BEAGLE-REVIEW-v1.md"]')
    review_link.wait_for(state='visible', timeout=10000)
    with page.expect_popup(timeout=10000) as review_opening:
        review_link.click()
    review_reader = review_opening.value
    review_reader.wait_for_load_state('domcontentloaded')
    review_reader.wait_for_function("document.body.innerText.includes('Citation receipt')", timeout=15000)
    review_text = review_reader.locator('body').inner_text()
    report['review_pin_opened'] = True
    report['review_completed_visible'] = 'no new material wording findings' in review_text.lower()
    report['review_receipt_visible'] = 'legal-beagle receipt' in review_text
    report['review_has_no_overflow'] = review_reader.evaluate('document.documentElement.scrollWidth <= innerWidth')
    review_reader.screenshot(path=str(out/'review-reader.png'),full_page=True)
    review_exact = '/artifact/' + pid + '?path=Distribution%20and%20Collaboration%2FLEGAL-BEAGLE-REVIEW-v1.md&render=1'
    review_target = context.new_page()
    review_response = review_target.goto(origin+review_exact,wait_until='domcontentloaded',timeout=20000)
    report['review_conversation_link'] = review_exact
    report['review_conversation_status'] = review_response.status
    report['review_conversation_has_heading'] = any('Legal-Beagle' in h for h in review_target.locator('h1').all_text_contents())
    report['refinement_visible'] = 'Version 1, Refinement 1' in reader_text
    assert all(report[k] for k in ('refinement_visible','review_pin_opened','review_completed_visible','review_receipt_visible','review_has_no_overflow','review_conversation_has_heading'))
    assert report['conversation_target_status']==report['review_conversation_status']==200
    (out/'reader-proof.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))
    browser.close()
