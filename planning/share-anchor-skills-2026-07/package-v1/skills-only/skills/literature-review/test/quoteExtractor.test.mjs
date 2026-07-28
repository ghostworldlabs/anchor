// Wave 3 — verbatim quote extraction: a candidate quote is grounded ONLY by
// strict exact-string matching against the normalized source, and a grounded
// quote is returned with the exact raw span it came from (the evidence
// lineage). Ungrounded quotes are rejected explicitly, never silently.
import { test, describe } from 'node:test';
import assert from 'node:assert';
import { groundQuote, extractVerbatimQuotes, DEFAULT_MIN_QUOTE_LENGTH } from '../src/quoteExtractor.mjs';
import { normalizeText, buildNormalizedView } from '../src/textNormalization.mjs';

// Erratic whitespace, mixed case, a ligature, and a repeated phrase.
const SOURCE = [
  'The   Model\tACHIEVES  94.2% accuracy on the held-out set.',
  'A ﬁne-grained ablation conﬁrms the result. The model achieves',
  '94.2% accuracy under replication as well.'
].join('\r\n');

describe('groundQuote - strict matching in normalized space', () => {
  test('grounds a quote despite erratic whitespace and case differences', () => {
    const res = groundQuote(SOURCE, 'the  model   achieves 94.2%  ACCURACY');
    assert.equal(res.matched, true);
    // Strict exact-string property: the normalized quote appears verbatim in
    // the normalized source, and the recovered raw span re-normalizes to it.
    assert.ok(normalizeText(SOURCE).includes(res.normalizedQuote));
    assert.equal(normalizeText(res.verbatimQuote), res.normalizedQuote);
    // Raw lineage: the span really is a verbatim slice of the raw source.
    assert.equal(SOURCE.slice(res.start, res.end), res.verbatimQuote);
    assert.equal(res.verbatimQuote, 'The   Model\tACHIEVES  94.2% accuracy');
  });

  test('grounds a quote across a ligature difference (NFKC)', () => {
    const res = groundQuote(SOURCE, 'a fine-grained ablation confirms the result');
    assert.equal(res.matched, true);
    assert.equal(res.verbatimQuote, 'A ﬁne-grained ablation conﬁrms the result');
  });

  test('counts every occurrence of a repeated quote', () => {
    const res = groundQuote(SOURCE, 'achieves 94.2% accuracy');
    assert.equal(res.matched, true);
    assert.equal(res.occurrences, 2);
  });

  test('rejects a paraphrase — near-miss wording is not verbatim', () => {
    const res = groundQuote(SOURCE, 'the model reaches 94.2% accuracy');
    assert.deepEqual({ matched: res.matched, reason: res.reason }, { matched: false, reason: 'not-in-source' });
  });

  test('rejects empty and too-short quotes with distinct reasons', () => {
    assert.equal(groundQuote(SOURCE, '').reason, 'empty-quote');
    assert.equal(groundQuote(SOURCE, ' \t ').reason, 'empty-quote');
    assert.equal(groundQuote(SOURCE, 'model').reason, 'too-short');
    assert.ok('the model'.length < DEFAULT_MIN_QUOTE_LENGTH);
    // The threshold is overridable.
    assert.equal(groundQuote(SOURCE, 'the model', { minLength: 4 }).matched, true);
  });

  test('accepts a prebuilt view so batch callers normalize the source once', () => {
    const view = buildNormalizedView(SOURCE);
    const res = groundQuote(view, 'accuracy under replication as well');
    assert.equal(res.matched, true);
    assert.equal(SOURCE.slice(res.start, res.end), res.verbatimQuote);
  });
});

describe('extractVerbatimQuotes - batch grounding, nothing silently dropped', () => {
  test('partitions every candidate into grounded or rejected', () => {
    const candidates = [
      { claimId: 'c-acc', statement: 'The model hits 94.2%.', quote: 'The model ACHIEVES 94.2% accuracy' },
      { claimId: 'c-abl', statement: 'Ablation confirms.', quote: 'a fine-grained ablation confirms the result' },
      { claimId: 'c-fake', statement: 'Fabricated.', quote: 'the model generalizes to every domain imaginable' },
      { claimId: 'c-short', statement: 'Too weak.', quote: 'model' }
    ];
    const { grounded, rejected, normalizedSource } = extractVerbatimQuotes(SOURCE, candidates);

    assert.equal(grounded.length + rejected.length, candidates.length);
    assert.deepEqual(grounded.map((g) => g.claimId), ['c-acc', 'c-abl']);
    assert.deepEqual(rejected.map((r) => [r.claimId, r.reason]), [
      ['c-fake', 'not-in-source'],
      ['c-short', 'too-short']
    ]);
    // Every grounded record satisfies the strict-match property.
    for (const g of grounded) {
      assert.ok(normalizedSource.includes(g.normalizedQuote));
      assert.equal(normalizeText(SOURCE.slice(g.start, g.end)), g.normalizedQuote);
    }
    // Rejected records keep the failed quote for the audit trail.
    assert.equal(rejected[0].quote, 'the model generalizes to every domain imaginable');
  });

  test('handles bare-string candidates and empty batches', () => {
    const one = extractVerbatimQuotes(SOURCE, ['accuracy on the held-out set']);
    assert.equal(one.grounded.length, 1);
    assert.equal(one.grounded[0].claimId, 'c-0');

    const none = extractVerbatimQuotes(SOURCE, []);
    assert.deepEqual([none.grounded, none.rejected], [[], []]);
  });
});
