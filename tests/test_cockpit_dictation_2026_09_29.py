"""Dictation into the say box (John, 2026-09-29): Win+H and Siri write phrases and press Enter for "new line";
while a phrase is arriving or has just arrived, Enter is that new line, never Send. Typed text still sends on Enter."""
import json
import time

from playwright.sync_api import expect

from tests.test_steward_refinement_browser import campaign_server, cockpit
from tests.test_cockpit_selected_b import open_surface


def _dictate(surface, phrase):
    """A dictation engine's phrase: the text lands as one multi-word insertText (Win+H) or a composition (Siri)."""
    surface.locator('[data-say]').evaluate("""(ta, phrase) => {
        ta.focus();
        ta.value += phrase;
        ta.dispatchEvent(new InputEvent('input', {inputType: 'insertText', data: phrase, bubbles: true}));
    }""", phrase)


def test_enter_right_after_a_dictated_phrase_is_a_new_line_not_send(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    posted = []
    def respond(route):
        posted.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True}))
    page.route('**/api/steward/say?*', respond)
    box = surface.locator('[data-say]')
    _dictate(surface, 'Move the sample size slide before the confidence interval one')
    box.press('Enter')                                                   # Win+H "new line" a moment after the phrase
    expect(box).to_have_value('Move the sample size slide before the confidence interval one\n')
    assert posted == []                                                  # nothing sent mid-dictation
    _dictate(surface, 'and keep the oatmeal example')
    expect(box).to_have_value('Move the sample size slide before the confidence interval one\nand keep the oatmeal example')
    time.sleep(2.2)                                                      # the dictation window closes
    box.press('Enter')                                                   # John's own Enter sends
    expect(box).to_have_value('', timeout=5000)
    assert len(posted) == 1 and posted[0]['text'].startswith('Move the sample size slide')
    assert 'keep the oatmeal example' in posted[0]['text']


def test_a_composition_in_flight_also_holds_enter(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    posted = []
    page.route('**/api/steward/say?*', lambda route: (posted.append(1), route.fulfill(status=200, content_type='application/json', body='{"ok": true}')))
    box = surface.locator('[data-say]')
    box.evaluate("""(ta) => {
        ta.focus();
        ta.dispatchEvent(new CompositionEvent('compositionstart', {bubbles: true}));
        ta.value = 'siri is still listening';
        ta.dispatchEvent(new InputEvent('input', {inputType: 'insertCompositionText', data: 'siri is still listening', isComposing: true, bubbles: true}));
        ta.dispatchEvent(new CompositionEvent('compositionend', {bubbles: true}));
    }""")
    box.press('Enter')
    expect(box).to_have_value('siri is still listening\n')
    assert posted == []


def test_typed_text_still_sends_on_enter(cockpit):
    page, server = cockpit
    surface = open_surface(page)
    posted = []
    def respond(route):
        posted.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True}))
    page.route('**/api/steward/say?*', respond)
    box = surface.locator('[data-say]')
    box.click()
    box.type('ok go ahead')                                              # one character at a time: typing
    box.press('Enter')
    expect(box).to_have_value('', timeout=5000)
    assert len(posted) == 1 and posted[0]['text'] == 'ok go ahead'
