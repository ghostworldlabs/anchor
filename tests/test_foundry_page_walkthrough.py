"""Real route/resource contracts and built-browser Foundry walkthrough checks.

Hermetic source roots and an ephemeral Anchor HTTP server; no model calls,
cockpit event reads, sleep POSTs or production session activation.
"""
import hashlib
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
import foundry_page as page


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content) if not isinstance(content, str) else content, encoding='utf-8')
    return path


@pytest.fixture
def rig(tmp_path, monkeypatch):
    foundry = tmp_path / 'foundry'
    skills = foundry / 'skills'
    trio = tmp_path / 'trio'
    steward = tmp_path / 'steward'
    content = foundry / 'Foundry page and knowledge maps'
    instruction = write(trio / 'researchPrime/SKILL.md', '---\nname: researchPrime\ndescription: Research a question.\n---\n## North Star\nFind a supported answer.\n## Entry\nStart here.\n<unsafe>\n')
    program = write(trio / 'researchPrime/bin/run.mjs', 'export function runRounds() {\n  return "checked";\n}\n')
    write(trio / 'researchPrime/HUMAN.md', '# researchPrime\n**One sentence:** Research a question.\n## How it works\nScope, research and review.\n')
    write(skills / 'gandalf/SKILL.md', '---\nname: Gandalf\n---\n## North Star\nInspect the artifact.\n')
    write(skills / 'hidden/SKILL.md', '---\nfoundry: false\n---\nNot listed.\n')
    write(skills / 'templates/SKILL.md', '# Template')
    write(steward / 'SKILL.md', '---\nname: ecgberht\n---\n## North Star\nSteward an effort.\n')
    monkeypatch.setattr(page.api, 'FOUNDRY_ROOT', str(foundry))
    monkeypatch.setattr(page.api, 'SKILLS_ROOT', str(skills))
    monkeypatch.setattr(page.api, '_load_manifest', lambda: [])
    monkeypatch.setattr(page.api, 'load_north_star', lambda: 'Foundry North Star')
    monkeypatch.setenv('FOUNDRY_TRIO_ROOT', str(trio))
    monkeypatch.setenv('FOUNDRY_STEWARD_ROOT', str(steward))
    monkeypatch.setenv('FOUNDRY_PAGE_CONTENT_ROOT', str(content))
    original_profile = page.anchor_settings.steward_profile
    monkeypatch.setattr(page.anchor_settings, 'steward_profile', lambda: original_profile({'steward_type': 'aladdin'}))
    monkeypatch.setenv('ANCHOR_DATA_DIR', str(tmp_path / 'anchor-data'))
    monkeypatch.setenv('TEMP', str(tmp_path))
    monkeypatch.setenv('TMP', str(tmp_path))
    monkeypatch.setenv('ANCHOR_PROACTIVE_SUMMARY', '0')
    monkeypatch.delenv('ANCHOR_TOKEN', raising=False)
    return dict(root=tmp_path, content=content, instruction=instruction, program=program, skills=skills)


def legacy(rig):
    base = rig['content'] / 'researchprime'
    write(base / 'library.json', {'resources': [
        {'id': 'guide', 'title': 'Research guide', 'category': 'material', 'path': str(rig['instruction'])},
        {'id': 'gandalf', 'title': 'Gandalf', 'skill': 'gandalf'},
        {'id': 'paper', 'title': 'Paper reference', 'category': 'references', 'url': 'https://example.org/paper'},
    ]})
    write(base / 'process-map.json', {'steps': [
        {'id': 'entry', 'title': 'First program', 'kind': 'program', 'code': {'path': str(rig['program']), 'symbol': 'runRounds'}, 'instructions': {'path': str(rig['instruction']), 'heading': '## Entry'}},
        {'id': 'review', 'title': 'Human feedback', 'kind': 'human', 'code': {'type': 'no-code'}, 'instructions': {'path': str(rig['instruction']), 'heading': '## Entry'}},
    ], 'edges': [{'from': 'entry', 'to': 'review', 'label': 'Review ready'}], 'exits': ['Human review']})
    write(base / 'knowledge-map.json', {'nodes': [
        {'id': 'root', 'name': 'Supported answer', 'resource_id': 'guide', 'ring': 0},
        {'id': 'scope', 'name': 'Scope question', 'resource_id': 'guide', 'parent_ids': ['root'], 'ring': 1},
    ]})
    return base


def combined(rig):
    def source(path, sid, kind):
        return dict(id=sid, origin=str(path), kind=kind, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    def anchor(path, aid, sid, line):
        quote = path.read_text(encoding='utf-8').splitlines()[line - 1]
        return dict(id=aid, source_id=sid, start=line, end=line, quote=quote, sha256=hashlib.sha256(quote.encode()).hexdigest())
    doc = dict(schema='foundry-skill-display/v1', skill_id='researchprime',
               sources=[source(rig['instruction'], 'instructions', 'instructions'), source(rig['program'], 'code', 'code')],
               anchors=[anchor(rig['instruction'], 'a1', 'instructions', 7), anchor(rig['program'], 'a2', 'code', 1)],
               resources=[dict(id='plan', title='Reusable research plan', category='Reusable material', anchor_id='a1', usage={'count': 999, 'status': 'frequent'})],
               knowledge={'nodes': [dict(id='answer', title='Supported answer', resource_id='plan', parent_id=None, ring=0, facets=['instructions'], process_ids=['entry'])]},
               process={'steps': [dict(id='entry', title='Entry program', kind='program', anchors=['a2', 'a1'], code_status='anchored', instruction_status='anchored', summary='Build the plan.'), dict(id='done', title='Human review', kind='human', anchors=['a1'], code_status='instructions-only', instruction_status='anchored')],
                        'edges': [dict(source='entry', target='done', label='Ready for feedback', anchor_id='a1')], 'terminals': ['done'],
                        'disagreements': [dict(title='Reports are session work', fact='Program and instructions differ.', anchors=['a1', 'a2'])]})
    path = write(rig['content'] / 'researchprime/maps.json', doc)
    return path, doc


def test_disk_discovery_and_three_persona_roles(rig):
    catalog = page.catalog()
    names = [r['name'] for r in catalog['skills']]
    assert names == sorted(names, key=str.casefold)
    assert not {'hidden', 'templates'} & {r['id'] for r in catalog['skills']}
    roles = [r for r in catalog['skills'] if r['role']]
    assert [r['name'] for r in roles] == ['Aladdin-Cave of Wonders', 'Aladdin-Lamp', 'Aladdin-Star Chart']
    assert len({r['source'] for r in roles}) == 1
    assert len({r['icon'] for r in roles}) == 3
    assert catalog['walkthroughOrder'] == ['researchprime', 'gandalf', 'steward-project', 'steward-portfolio', 'steward-starchart']
    write(rig['skills'] / 'new/SKILL.md', '---\nname: A new skill\n---\nDiscovered from disk.')
    assert page.catalog()['skills'][0]['name'] == 'A new skill'


def test_missing_maps_stay_unfinished(rig):
    detail = page.skill_detail('gandalf')
    assert detail['processMap']['status'] == detail['knowledgeMap']['status'] == 'unfinished'
    assert detail['resources'] and not detail['knowledgeMap']['nodes']


def test_steward_roles_read_distinct_files_without_sharing_a_map(rig):
    steward = Path(page.find_skill('steward-project')['source'])
    write(steward / 'FLOW.project.json', {'steps': [
        {'id': 'lamp', 'title': 'Lamp dialogue', 'code': {'type': 'no-code'},
         'instructions': {'path': str(steward / 'SKILL.md'), 'heading': '## North Star'}}
    ]})
    assert page.skill_detail('steward-project')['processMap']['steps'][0]['id'] == 'lamp'
    assert page.skill_detail('steward-portfolio')['processMap']['status'] == 'unfinished'
    assert page.skill_detail('steward-starchart')['processMap']['status'] == 'unfinished'


def test_legacy_library_and_maps_open_real_resources(rig):
    legacy(rig)
    detail = page.skill_detail('researchprime')
    assert detail['processMap']['status'] == 'source-anchored draft'
    assert detail['knowledgeMap']['status'] == 'seeded draft'
    assert 'not calibrated or learned' in detail['knowledgeMap']['qualification']
    for node in detail['knowledgeMap']['nodes']:
        assert node['href'] == next(r['href'] for r in detail['resources'] if r['id'] == node['resourceId'])
    for step in detail['processMap']['steps']:
        assert step['instructionLink']['href'].startswith('/foundry/source?')
    assert next(r for r in detail['resources'] if r['id'] == 'gandalf')['href'] == '/foundry?skill=gandalf'


def test_combined_foundry_handoff_hashes_branches_and_disagreements(rig):
    combined(rig)
    detail = page.skill_detail('researchprime')
    assert not detail['libraryIssues'] and not detail['processMap']['issues']
    assert detail['processMap']['edges'][0]['to'] == 'done'
    assert len(detail['processMap']['disagreements'][0]['sourceLinks']) == 2
    assert detail['knowledgeMap']['nodes'][0]['resourceId'] == 'plan'
    assert next(r for r in detail['resources'] if r['id'] == 'plan')['frequency'] == 'Use not recorded'
    rig['program'].write_text('// source changed\n', encoding='utf-8')
    assert any('Source changed' in i for i in page.skill_detail('researchprime')['processMap']['issues'])


def test_frequency_requires_distinct_resource_use_records(rig):
    base = legacy(rig)
    record = {'id': 'guide', 'path': str(rig['instruction']), 'useEvidence': []}
    for name, doc in [('one', {'run_id': 'r1', 'resource_ids': ['guide']}), ('duplicate', {'run_id': 'r1', 'resource_ids': ['guide']}), ('unrelated', {'run_id': 'r2', 'resource_ids': ['other']})]:
        record['useEvidence'].append(str(write(base / f'journal/runs/{name}.json', doc)))
    record['useEvidence'].append(str(write(base / 'journal/entry.md', 'An ordinary journal entry.')))
    assert page._frequency(record, page.find_skill('researchprime'), base) == '1 recorded use'


def test_bad_hierarchy_edges_and_missing_targets_are_visible(rig):
    base = legacy(rig)
    write(base / 'knowledge-map.json', {'nodes': [{'id': 'loop', 'name': 'Broken', 'parent_ids': ['loop'], 'ring': 9, 'resource_id': 'missing'}]})
    detail = page.skill_detail('researchprime')
    assert detail['knowledgeMap']['status'] == 'needs checking'
    assert any('cyclic' in i for i in detail['knowledgeMap']['issues'])
    assert any('No real Library target' in i for i in detail['knowledgeMap']['issues'])
    assert any('Ring disagrees' in i for i in detail['knowledgeMap']['issues'])
    write(base / 'process-map.json', {'steps': [], 'edges': [{'from': 'missing', 'to': 'other'}]})
    assert 'Process edge has a missing step' in page.skill_detail('researchprime')['processMap']['issues']


@pytest.mark.parametrize('name,content', [('library.json', {'resources': 42}), ('process-map.json', {'steps': 42}), ('knowledge-map.json', {'nodes': 42}), ('maps.json', {'schema': 'foundry-skill-display/v1', 'skill_id': 'another'})])
def test_malformed_content_is_qualified_not_a_server_error(rig, name, content):
    write(rig['content'] / 'researchprime' / name, content)
    detail = page.skill_detail('researchprime')
    assert detail is not None
    assert detail['libraryIssues'] or detail['knowledgeMap']['issues'] or detail['processMap']['issues']


def test_source_reader_is_skill_scoped_contained_and_escaped(rig):
    legacy(rig)
    markup = page.source_page('researchprime', str(rig['instruction']), '## Entry')
    assert '&lt;unsafe&gt;' in markup and '<unsafe>' not in markup
    assert 'class="hit"' in markup
    assert page.source_page('gandalf', str(rig['instruction'])) is None
    assert page.source_page('researchprime', str(write(rig['root'] / 'outside.md', 'private'))) is None
    assert page.source_page('researchprime', str(rig['content'] / '../../outside.md')) is None


@pytest.fixture
def server(rig):
    import anchor_gui
    srv = anchor_gui.make_server('127.0.0.1', 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{srv.server_address[1]}'
    finally:
        srv.shutdown(); srv.server_close(); thread.join(timeout=5)


def test_actual_anchor_routes_and_built_assets(rig, server):
    combined(rig)
    with urlopen(server + '/api/foundry/page') as response:
        assert json.load(response)['walkthroughOrder'][0] == 'researchprime'
    with urlopen(server + '/api/foundry/skill?skill=researchprime') as response:
        detail = json.load(response)
    source = detail['knowledgeMap']['nodes'][0]['href']
    with urlopen(server + source) as response:
        assert 'class="hit"' in response.read().decode()
    with urlopen(server + '/foundry?skill=researchprime') as response:
        markup = response.read().decode()
    import re
    asset = re.search(r'src="(/assets/[^\"]+\.js)"', markup)[1]
    with urlopen(server + asset) as response:
        assert b'/api/foundry/page' in response.read()
    with pytest.raises(HTTPError) as err:
        urlopen(server + '/api/foundry/skill?skill=unknown')
    assert err.value.code == 404
    with pytest.raises(HTTPError) as err:
        urlopen(server + page.source_url('gandalf', rig['instruction']))
    assert err.value.code == 404


@pytest.mark.parametrize('verb', ['propose', 'apply', 'rollback'])
def test_existing_sleep_routes_still_dispatch_to_the_kernel(rig, server, monkeypatch, verb):
    seen = []
    def stub(body):
        seen.append(body)
        return {'ok': True, 'checked': verb}, 200
    monkeypatch.setattr(page.api, 'sleep_' + verb, stub)
    body = {'skill': 'gandalf', 'confirm': True}
    request = Request(server + '/api/foundry/sleep_session/' + verb,
                      data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(request) as response:
        assert json.load(response)['checked'] == verb
    assert seen == [body]


def test_built_desktop_and_phone_navigation_and_source_clicks(rig, server):
    playwright = pytest.importorskip('playwright.sync_api')
    combined(rig)
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                context = browser.new_context(viewport={'width': width, 'height': height})
                tab = context.new_page()
                errors, writes = [], []
                tab.on('pageerror', lambda e: errors.append(str(e)))
                tab.on('request', lambda r: writes.append(r.url) if r.method != 'GET' else None)
                tab.goto(server + '/foundry?skill=researchprime')
                tab.get_by_role('heading', name='researchPrime', exact=True).wait_for()
                tab.get_by_role('button', name='Concept: Supported answer', exact=True).click()
                with tab.expect_popup() as popup:
                    tab.get_by_role('link', name='Open Library resource', exact=True).click()
                popup.value.wait_for_load_state()
                assert popup.value.locator('.hit').count() == 1
                popup.value.close()
                tab.get_by_role('button', name='Outline', exact=True).click()
                assert tab.locator('.map-outline').is_visible()
                tab.locator('#process-map > summary').click()
                assert tab.get_by_role('link', name='Ready for feedback → Human review').is_visible()
                assert tab.get_by_role('link', name='Code: run.mjs · 1').is_visible()
                assert tab.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                if width < 780:
                    tab.get_by_role('button', name='Skills A–Z', exact=True).click()
                tab.locator('#skill-rail').get_by_role('button', name='Gandalf', exact=False).click()
                tab.get_by_role('heading', name='Gandalf', exact=True).wait_for()
                assert tab.get_by_text('Knowledge map unfinished.', exact=False).is_visible()
                assert not errors and not writes
                context.close()
        finally:
            browser.close()
