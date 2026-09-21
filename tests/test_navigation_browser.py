import json
import re
from pathlib import Path
from playwright.sync_api import expect
from tests.test_steward_refinement_browser import campaign_server, cockpit


def test_legacy_components_current_links_and_persistent_navigation(cockpit):
    page, server = cockpit
    root = server.campaign.parent / 'Navigation project'
    root.mkdir()
    (root/'ECGBERHT.md').write_text('# Navigation project\n\n## North star\nA usable weekly tracker.\n', encoding='utf-8')
    product = {'id': 'tracker', 'name': 'Weekly tracker', 'components': [
        {'id': 'calendar', 'name': 'Calendar'}, {'id': 'strength', 'name': 'Strength log'}]}
    (root/'roadmap.json').write_text(json.dumps({'roadmap_events': [
        {'kind': 'kickoff_proposal', 'proposal_id': 'p1', 'proposal_hash': 'hash1', 'version': 1, 'work_product': product},
        {'kind': 'kickoff_confirm', 'proposal_id': 'p1', 'proposal_hash': 'hash1', 'version': 1}],
        'roadmap_projection': [{'id': 'live', 'name': 'Build tracker', 'status': 'active', 'component_ids': ['calendar', 'strength']},
                               {'id': 'research', 'name': 'Research', 'status': 'active', 'navigation': {'role': 'support'}}]}), encoding='utf-8')
    register = '| What | Where | Date | Step |\n| --- | --- | --- | --- |\n' + \
        '| START HERE — Working tracker | `current.html` | 2026-09-13 | LIVE |\n' + \
        '| Earlier workbook | `old.html` | 2026-09-12 | live |\n' + \
        '| START HERE: supporting evidence | `support.html` | 2026-09-13 | research |\n' + \
        '| Unassigned reference | `orphan.html` | 2026-09-13 | unresolved |\n'
    (root/'DELIVERABLES.md').write_text(register, encoding='utf-8')
    for name in ('current', 'old', 'support', 'orphan'):
        (root/(name+'.html')).write_text('<h1>'+name+' tracker example</h1>', encoding='utf-8')
    page.reload()

    def open_surface():
        page.locator('[data-efforts] .efrow').filter(has_text='Navigation project').first.click()
        surface = page.frame_locator('[data-fsframe]')
        expect(surface.locator('[data-say]')).to_be_visible()
        panel = surface.locator('[data-delivmount] .blk.deliv')
        expect(panel).to_be_visible()
        folded = panel.locator(':scope.folded > .who')
        if folded.count(): folded.click()
        expect(panel.locator('.navpin')).to_be_visible()
        return surface, panel

    surface, panel = open_surface()
    donow = surface.locator('.blk.status.latest .sdonow')                # Do now sits under the status lead (Wave E, 2026-09-21)
    expect(donow).to_contain_text('Do now')
    expect(donow.locator('.navfile')).to_have_count(1)                   # the current file is the one Open act
    expect(donow).to_contain_text('Working tracker')
    expect(panel.locator('.navpin')).to_contain_text('Working tracker')            # the pin block lists the current files
    expect(surface.locator('[data-steps] .notdone')).to_contain_text('Not done')    # the red-flag list at the bottom of the plan
    expect(panel.locator('summary').filter(has_text='Approved deliverables · 0')).to_be_visible()
    expect(panel.locator('.nav-choice[data-group-id="tracker"]')).to_be_visible()
    sections = panel.locator('summary').filter(has_text='Sections and deliverables')
    sections.click()
    panel.locator('.nav-choice[data-group-id="calendar"]').click()
    expect(panel.locator('.nav-inspect h3')).to_have_text('Calendar')
    panel.locator('.nav-inspect summary').filter(has_text='Shared work and deliverables').click()
    expect(panel.locator('.nav-inspect .navfilelink a').first).to_be_visible()
    expect(panel.locator('.nav-inspect')).to_contain_text('Working tracker')
    expect(panel.locator('.nav-inspect')).to_contain_text('Earlier workbook')
    expect(panel.locator('.nav-inspect .nav-accept')).to_have_count(0)
    with page.expect_popup() as opened:
        donow.locator('.navfilelink a').first.click()
    popup = opened.value
    popup.wait_for_load_state('domcontentloaded')
    assert 'current tracker example' in popup.content()
    popup.close()
    # Change the register to force its periodic repaint, without changing ownership.
    (root/'DELIVERABLES.md').write_text(register.replace('Earlier workbook', 'Earlier workbook retained'), encoding='utf-8')
    expect(panel.locator('.nav-inspect')).to_contain_text('Earlier workbook retained', timeout=20000)
    expect(panel.locator('.nav-inspect h3')).to_have_text('Calendar')
    expect(surface.locator('[data-say]')).to_be_visible()
    page.reload()
    surface, panel = open_surface()
    expect(panel.locator('.nav-inspect h3')).to_have_text('Calendar')
    expect(panel.locator('.nav-choice[data-group-id="calendar"]')).to_be_visible()
    panel.locator('.nav-choice[data-group-id="unclassified"]').click()
    expect(panel.locator('.nav-inspect')).to_contain_text('Unassigned reference')
    assert not (root/'Finished Deliverables').exists()


def test_empty_campaign_uses_same_panel_order(cockpit):
    page, server = cockpit
    root = server.campaign.parent / 'Empty campaign'
    root.mkdir()
    (root/'ECGBERHT.md').write_text('# Empty campaign\n\n## North star\nNo plan confirmed yet.\n', encoding='utf-8')
    (root/'roadmap.json').write_text('{"roadmap_events":[],"roadmap_projection":[]}', encoding='utf-8')
    page.reload()
    page.locator('[data-efforts] .efrow').filter(has_text='Empty campaign').first.click()
    surface = page.frame_locator('[data-fsframe]')
    expect(surface.locator('[data-say]')).to_be_visible()
    panel = surface.locator('[data-delivmount] .blk.deliv')
    expect(panel).to_be_visible()
    folded = panel.locator(':scope.folded > .who')
    if folded.count(): folded.click()
    expect(panel.locator('.navpin')).to_contain_text('No files awaiting review.')
    expect(surface.locator('.blk.status.latest .sdonow')).to_contain_text('Nothing waits on you; the steward has not stated a next step.')
    expect(panel.locator('summary').filter(has_text='Approved deliverables · 0')).to_be_visible()
    expect(panel.locator('.nav-choice[data-group-id="compat-root"]')).to_be_visible()
    expect(surface.locator('[data-steps] .navgroup > summary').first).to_contain_text('Empty campaign')
    order = panel.locator('.body').evaluate("e=>[...e.children].map(c=>c.className)")
    assert order.index('navpin') < order.index('navgroup') < order.index('nav-select')
