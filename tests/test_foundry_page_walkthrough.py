"""Real route/resource contracts and built-browser Foundry walkthrough checks.

Hermetic source roots and an ephemeral Anchor HTTP server; no model calls,
cockpit event reads, sleep POSTs or production session activation.
"""
import hashlib
import json
import os
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import quote

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
    return dict(root=tmp_path, content=content, instruction=instruction, program=program, skills=skills,
                profile=original_profile)


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


def role_bundle(rig, role='steward-project'):
    _, doc = combined(rig)
    doc['skill_id'] = role
    base = rig['content'] / page.ROLE_CONTENT[role]
    write(base / 'maps.json', doc)
    return base, doc


@pytest.mark.parametrize('persona', ['aladdin', 'jarvis', 'ecgberht'])
@pytest.mark.parametrize('role', list(page.ROLE_CONTENT))
def test_trusted_role_directories_keep_identity_and_selected_persona(rig, monkeypatch, persona, role):
    resolver = rig['profile']
    monkeypatch.setattr(page.anchor_settings, 'steward_profile', lambda: resolver({'steward_type': persona}))
    base, doc = role_bundle(rig, role)
    detail = page.skill_detail(role)
    assert detail['skill']['id'] == role
    profile = resolver({'steward_type': persona})
    field = {'steward-project': 'seal_name', 'steward-portfolio': 'high_seat_name', 'steward-starchart': 'campaign_name'}[role]
    assert detail['skill']['name'] == profile['label'] + '-' + profile[field]
    assert detail['librarySource'] == str(base / 'maps.json')
    assert detail['processMap']['status'] == 'source-anchored draft'
    assert detail['knowledgeMap']['nodes'][0]['href'] == detail['libraryResources'][0]['href']
    for other in page.ROLE_CONTENT.keys() - {role}:
        assert page.skill_detail(other)['processMap']['status'] == 'unfinished'
    doc['skill_id'] = next(r for r in page.ROLE_CONTENT if r != role)
    write(base / 'maps.json', doc)
    assert 'different-skill' in ' '.join(page.skill_detail(role)['libraryIssues'])


def provenance_bundle(rig, source):
    base, doc = role_bundle(rig)
    doc['sources'] = [dict(id='instructions', **source), doc['sources'][1]]
    doc['anchors'][0].update(start=1, end=1, sha256=hashlib.sha256(b'Captured example').hexdigest())
    write(base / 'maps.json', doc)
    return base, doc


def test_exact_engine_and_global_inventory_does_not_broaden_roots(rig, monkeypatch):
    engine = write(rig['root'] / 'Anchor/steward_cockpit/steward_engine.py', 'Captured example\n')
    global_rules = write(rig['root'] / 'home/.claude/AGENTS.md', 'Captured example\n')
    monkeypatch.setattr(Path, 'home', lambda: rig['root'] / 'home')
    for origin in (engine, global_rules):
        base, doc = provenance_bundle(rig, dict(origin=str(origin), freshness='current-source',
            sha256=hashlib.sha256(origin.read_bytes()).hexdigest(), captured_at='2026-10-05T23:40:00+00:00',
            captured_from=str(origin), applicability='On-disk code is not activation proof.'))
        detail = page.skill_detail('steward-project')
        assert not detail['libraryIssues']
        markup = page.source_page('steward-project', str(origin), '1')
        assert 'On-disk code is not activation proof.' in markup
        assert page.source_page('steward-portfolio', str(origin)) is None
        assert not page._allowed(origin)
        origin.write_text('Later source\n', encoding='utf-8')
        assert 'Source changed' in ' '.join(page.skill_detail('steward-project')['libraryIssues'])
        assert 'Source changed since capture' in page.source_page('steward-project', str(origin))
    for outside in (rig['root'] / 'Anchor/private.py', rig['root'] / 'home/.claude/private.md',
                    rig['root'] / 'home/notes.md'):
        write(outside, 'Captured example\n')
        provenance_bundle(rig, dict(origin=str(outside)))
        assert page.source_page('steward-project', str(outside)) is None
        assert page.skill_detail('steward-project')['libraryIssues']


def test_historical_reader_uses_only_qualified_immutable_snapshot(rig):
    base = rig['content'] / 'steward-lamp'
    snapshot = write(base / 'sources/example.md', 'Captured example\n')
    original = write(rig['root'] / 'home/private.md', 'Changed live state\n')
    source = dict(origin=str(original), snapshot='sources/example.md', freshness='frozen-example',
                  sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                  captured_at='2026-10-05T23:34:00+00:00', captured_from=str(original),
                  applicability='Historical record; not current campaign state.')
    base, doc = provenance_bundle(rig, source)
    markup = page.source_page('steward-project', str(snapshot), '1')
    assert 'Captured example' in markup and 'Historical record; not current campaign state.' in markup
    assert '2026-10-05T23:34:00+00:00' in markup and source['sha256'] in markup
    assert 'Changed live state' not in markup
    assert page.source_page('steward-project', str(original)) is None
    original.write_text('A newer decision\n', encoding='utf-8')
    assert not page.skill_detail('steward-project')['libraryIssues']
    snapshot.write_text('Corrupted snapshot\n', encoding='utf-8')
    assert 'snapshot hash mismatch' in ' '.join(page.skill_detail('steward-project')['libraryIssues'])
    assert page.source_page('steward-project', str(snapshot)) is None


@pytest.mark.parametrize('snapshot', ['../outside.md', '/outside.md', 'sources/../../outside.md', '.ecgberht/history.json'])
def test_snapshot_and_request_traversal_fail_closed(rig, snapshot):
    outside = write(rig['root'] / 'outside.md', 'Captured example\n')
    provenance_bundle(rig, dict(origin=str(outside), snapshot=snapshot, freshness='frozen-example',
        sha256=hashlib.sha256(outside.read_bytes()).hexdigest(), captured_at='2026-10-05',
        captured_from=str(outside), applicability='Historical.'))
    assert page.source_page('steward-project', str(outside)) is None
    assert page.skill_detail('steward-project')['libraryIssues']
    combined(rig)
    assert page.source_page('researchprime', str(rig['program'].parent / '../bin/run.mjs')) is None


def test_declared_symlink_to_outside_is_rejected(rig):
    outside = write(rig['root'] / 'outside.md', 'Captured example\n')
    base = rig['content'] / 'steward-lamp'
    link = base / 'sources/example.md'
    link.parent.mkdir(parents=True)
    try:
        os.symlink(outside, link)
    except OSError:
        pytest.skip('symlink creation unavailable')
    provenance_bundle(rig, dict(origin=str(outside), snapshot='sources/example.md', freshness='frozen-example',
        sha256=hashlib.sha256(outside.read_bytes()).hexdigest(), captured_at='2026-10-05',
        captured_from=str(outside), applicability='Historical.'))
    assert page.source_page('steward-project', str(link)) is None
    assert page.skill_detail('steward-project')['libraryIssues']


@pytest.fixture
def opening(rig, monkeypatch):
    import anchor_gui
    pid = 'fixture-foundry'
    monkeypatch.setattr(anchor_gui._rnd, 'get_project', lambda p: {'id': pid, 'folder_path': str(rig['content'].parent)} if p == pid else None)
    monkeypatch.setattr(page, '_review_project_id', lambda: pid)
    base, doc = role_bundle(rig)
    write(base / 'index.html', '''<!doctype html><html><head><link rel="stylesheet" href="../shared/maps.css">
<script defer src="display.js"></script></head><body><img src="assets/lamp.svg"><div id="panel"></div></body></html>''')
    write(base / 'display.js', "document.querySelector('#panel').innerHTML='<h1>Lamp Library</h1><a href=\"resources/plan.html\">Open resource</a>';")
    write(rig['content'] / 'shared/maps.css', 'body{background:rgb(20, 30, 40);color:white}')
    write(base / 'assets/lamp.svg', '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="gold"/></svg>')
    write(base / 'resources/plan.html', '<!doctype html><link rel="stylesheet" href="../../shared/maps.css"><h1>Reusable research plan</h1><a href="../sources/example.md">Exact captured source</a>')
    write(base / 'sources/example.md', 'An exact captured source.\n')
    doc['resources'][0]['target'] = 'resources/plan.html'
    write(base / 'maps.json', doc)
    rel = base.relative_to(rig['content'].parent).as_posix() + '/index.html'
    return '/artifact/' + pid + '?path=' + quote(rel, safe=''), base


def test_real_artifact_opening_redirect_assets_and_containment(rig, server, opening):
    route, base = opening
    with urlopen(server + route) as response:
        assert '/steward-lamp/index.html' in response.url
        assert 'sandbox' in response.headers['Content-Security-Policy']
        assert 'allow-same-origin' not in response.headers['Content-Security-Policy']
    with urlopen(server + route.replace('fixture-foundry?', 'fixture-foundry/?') + '&persona=jarvis') as response:
        assert response.url.endswith('/index.html?persona=jarvis')
    from steward_cockpit.steward_campaign import classify_route
    # This is the owner-applied Where-cell correction: keep the existing
    # query grammar, which now redirects to the contained document directory.
    assert classify_route(route) == route
    assert classify_route(route + '#handoff') == route + '#handoff'
    prefix = '/artifact/fixture-foundry/' + quote(base.relative_to(rig['content'].parent).as_posix(), safe='/')
    for relative, ctype in [('display.js', 'application/javascript'), ('../shared/maps.css', 'text/css'), ('assets/lamp.svg', 'image/svg+xml')]:
        # Browser URL resolution removes ordinary relative segments before GET.
        from urllib.parse import urljoin
        with urlopen(urljoin(server + prefix + '/index.html', relative)) as response:
            assert response.headers['Content-Type'].startswith(ctype)
    detail = page.skill_detail('steward-project')
    assert detail['libraryResources'][0]['href'].endswith('/resources/plan.html')
    assert detail['libraryResources'][0]['sourceHref'].startswith('/foundry/source?')
    write(rig['content'].parent / '.git/config', 'SECRET')
    for path in ('../../outside.md', '.git/config', str(rig['root'] / 'outside.md')):
        with pytest.raises(HTTPError) as err:
            urlopen(server + '/artifact/fixture-foundry?path=' + quote(path, safe=''))
        assert err.value.code in (400, 404)
    with pytest.raises(HTTPError) as err:
        urlopen(server + '/artifact/fixture-foundry/.git/config')
    assert err.value.code == 404


def test_authenticated_desktop_phone_library_loads_relative_assets(rig, server, opening, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('ANCHOR_TOKEN', 'foundry-test-cookie')
    route, _ = opening
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for width, height in [(1440, 1000), (390, 844)]:
                context = browser.new_context(viewport={'width': width, 'height': height})
                tab = context.new_page()
                # Use the normal local-page login, while guarding all Doctor
                # follow-up reads so no other effort can soft-wake.
                tab.route('**/*', lambda r: r.continue_() if r.request.is_navigation_request() and '/doctor' in r.request.url else r.abort())
                tab.goto(server + '/doctor')
                assert any(c['name'] == 'anchor_auth' and c['httpOnly'] for c in context.cookies())
                tab.unroute('**/*')
                errors, failed, writes = [], [], []
                tab.on('pageerror', lambda e: errors.append(str(e)))
                tab.on('requestfailed', lambda r: failed.append(r.url))
                tab.on('response', lambda r: failed.append(r.url) if r.status >= 400 else None)
                tab.on('request', lambda r: writes.append(r.url) if r.method != 'GET' else None)
                tab.goto(server + route)
                tab.get_by_role('heading', name='Lamp Library').wait_for()
                assert tab.locator('img').evaluate('(el) => el.complete && el.naturalWidth > 0')
                assert tab.locator('body').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(20, 30, 40)'
                tab.get_by_role('link', name='Open resource', exact=True).click()
                tab.get_by_role('heading', name='Reusable research plan').wait_for()
                tab.get_by_role('link', name='Exact captured source').click()
                assert 'An exact captured source.' in tab.locator('body').inner_text()
                assert not errors and not failed and not writes
                context.close()
        finally:
            browser.close()


def test_windows_journal_does_not_break_real_foundry_loading(rig, server, monkeypatch):
    journal = rig['skills'] / 'gandalf/journal/0001-legacy.md'
    journal.parent.mkdir(parents=True)
    journal.write_bytes('# Review — a historical entry\nRetained “quoted” context.'.encode('cp1252'))
    monkeypatch.setattr(page.api, '_load_manifest', lambda: [
        {'name': 'Gandalf', 'ref': 'gandalf', 'source': str(rig['skills'] / 'gandalf')}])
    events = page.api._journal_events(str(journal.parent.parent))
    assert events[0]['event'] == 'Review — a historical entry'
    assert events[0]['sourceEncoding'] == 'windows-1252'
    assert '“quoted”' in events[0]['details']
    for route in ('/api/skills', '/api/metrics'):
        with urlopen(server + route) as response:
            assert response.status == 200
            assert json.load(response)
    assert journal.read_bytes() == '# Review — a historical entry\nRetained “quoted” context.'.encode('cp1252')


def test_exact_inventory_and_resource_target_rejections(rig, opening):
    _, base = opening
    unknown = write(base / 'sources/undeclared.md', 'PRIVATE')
    assert page.source_page('steward-project', str(unknown)) is None
    assert page.source_page('steward-project', str(write(rig['root'] / 'Anchor/model_policy.py', 'PRIVATE'))) is None
    for target in ('../sources/undeclared.md', 'resources/../../outside.html', str(unknown), '.anchor/private.html'):
        assert page._library_target(target, base, 'fixture-foundry') is None
