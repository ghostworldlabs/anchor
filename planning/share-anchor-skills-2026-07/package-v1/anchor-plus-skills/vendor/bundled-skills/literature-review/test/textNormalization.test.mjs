// Wave 3 — exact text normalization: NFKC, case-folding, whitespace
// consolidation, and the offset map that anchors every normalized character
// back to its verbatim raw span. Non-ASCII test inputs use explicit \u
// escapes so the fixtures are unambiguous.
import { test, describe } from 'node:test';
import assert from 'node:assert';
import { normalizeText, buildNormalizedView, rawSpanForMatch } from '../src/textNormalization.mjs';

describe('normalizeText - Unicode NFKC', () => {
  test('folds compatibility forms to their canonical equivalents', () => {
    assert.equal(normalizeText('ﬁle'), 'file'); // LATIN SMALL LIGATURE FI
    assert.equal(normalizeText('Ｆｕｌｌ'), 'full'); // full-width forms
    assert.equal(normalizeText('x²'), 'x2'); // superscript two
  });

  test('composes combining marks across code points', () => {
    // decomposed e + COMBINING ACUTE === precomposed é
    assert.equal(normalizeText('Café'), normalizeText('Café'));
    assert.equal(normalizeText('Café'), 'café');
  });

  test('strips invisible format characters (ZWSP, soft hyphen, BOM)', () => {
    assert.equal(normalizeText('foo​bar'), 'foobar');
    assert.equal(normalizeText('co­operate'), 'cooperate');
    assert.equal(normalizeText('﻿lead'), 'lead');
  });
});

describe('normalizeText - case-folding and whitespace consolidation', () => {
  test('case-folds to lowercase', () => {
    assert.equal(normalizeText('MiXeD CaSe TEXT'), 'mixed case text');
  });

  test('consolidates every whitespace run to a single space and trims', () => {
    assert.equal(normalizeText('  a\t\tb\r\nc  d　e  '), 'a b c d e');
    assert.equal(normalizeText('nbsp joined'), 'nbsp joined');
  });

  test('empty and whitespace-only inputs normalize to the empty string', () => {
    assert.equal(normalizeText(''), '');
    assert.equal(normalizeText(' \t\r\n '), '');
    assert.equal(normalizeText(null), '');
  });
});

describe('buildNormalizedView - offset map back into the raw source', () => {
  const raw = '  The\tQUICK  ﬁx\r\n works ';
  const view = buildNormalizedView(raw);

  test('normalized text is the canonical form', () => {
    assert.equal(view.text, 'the quick fix works');
    assert.equal(view.source, raw);
    assert.equal(view.starts.length, view.text.length);
    assert.equal(view.ends.length, view.text.length);
  });

  test('a normalized match recovers its exact verbatim raw span', () => {
    const q = view.text.indexOf('quick');
    const span = rawSpanForMatch(view, q, q + 'quick'.length);
    assert.equal(span.verbatim, 'QUICK');
    assert.equal(raw.slice(span.start, span.end), 'QUICK');
  });

  test('a match through a ligature maps back to the raw ligature bytes', () => {
    const f = view.text.indexOf('fix');
    const span = rawSpanForMatch(view, f, f + 'fix'.length);
    assert.equal(span.verbatim, 'ﬁx');
  });

  test('re-normalizing a recovered span reproduces the matched text exactly', () => {
    for (const needle of ['the quick', 'fix works', 'quick fix works']) {
      const at = view.text.indexOf(needle);
      assert.notEqual(at, -1, `needle '${needle}' must exist in the normalized view`);
      const span = rawSpanForMatch(view, at, at + needle.length);
      assert.equal(normalizeText(span.verbatim), needle);
    }
  });

  test('rejects out-of-range normalized offsets', () => {
    assert.throws(() => rawSpanForMatch(view, -1, 3), RangeError);
    assert.throws(() => rawSpanForMatch(view, 3, 3), RangeError);
    assert.throws(() => rawSpanForMatch(view, 0, view.text.length + 1), RangeError);
  });
});
