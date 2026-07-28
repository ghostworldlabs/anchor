// Overhaul Wave 1 — Semantic Interception & Event Bus Dispatch: the SEMANTIC CLASSIFIER.
//
// Exercises the REAL Wave-1 source (src/semantic-classifier.mjs), proving the classifier arm of the
// done-when: the semantic classifier ACCURATELY intercepts Claim<Empirical> and mathematical
// assertions — across paraphrase-diverse phrasings no single regex template would cover (the
// replacement of legacy regex interception) — while questions, hedges, and claim-free prose are
// never intercepted, and empirical claims are typed OUTSIDE the formal ledger vocabulary so they
// can never reach the formal certifiers.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  CLAIM_KIND,
  CLAIM_KINDS,
  extractFeatures,
  classifySentence,
  segmentSentences,
  interceptClaims,
  MATH_ASSERTION_FIXTURE,
  EMPIRICAL_CLAIM_FIXTURE,
  NON_CLAIM_FIXTURE,
  CLASSIFIER_FIXTURE,
  runFixtureClassification,
} from '../src/semantic-classifier.mjs';

import { CLAIM_TYPES } from '../src/claim-ledger.mjs';

// =====================================================================================
// 0. The pinned kind vocabulary.
// =====================================================================================

test('CLAIM_KIND is the pinned 3-way interception vocabulary', () => {
  assert.deepEqual(CLAIM_KINDS, ['mathematical', 'empirical', 'none']);
  assert.equal(CLAIM_KIND.MATHEMATICAL, 'mathematical');
  assert.equal(CLAIM_KIND.EMPIRICAL, 'empirical');
  assert.equal(CLAIM_KIND.NONE, 'none');
});

// =====================================================================================
// 1. THE DONE-WHEN (classifier arm) — accurate interception over the full fixture battery.
// =====================================================================================

test('done-when: the fixture battery is classified accurately (all math + all empirical intercepted, zero false interceptions)', () => {
  const run = runFixtureClassification();
  assert.equal(run.allMathIntercepted, true, 'every mathematical assertion must be intercepted');
  assert.equal(run.allEmpiricalIntercepted, true, 'every Claim<Empirical> must be intercepted');
  assert.equal(run.noFalseInterceptions, true, 'claim-free prose must never be intercepted');
  assert.equal(run.mathematical.length, MATH_ASSERTION_FIXTURE.length);
  assert.equal(run.empirical.length, EMPIRICAL_CLAIM_FIXTURE.length);
  assert.equal(run.none.length, NON_CLAIM_FIXTURE.length);
});

test('every mathematical assertion carries a downstream-compatible subtype, a confidence, and a reason', () => {
  for (const statement of MATH_ASSERTION_FIXTURE) {
    const c = classifySentence(statement);
    assert.equal(c.kind, CLAIM_KIND.MATHEMATICAL, `${statement}: kind ${c.kind}`);
    assert.ok(CLAIM_TYPES.includes(c.claim_type), `${statement}: subtype ${c.claim_type} must be a ledger claim type`);
    assert.ok(c.confidence > 0 && c.confidence <= 0.95);
    assert.equal(typeof c.reason, 'string');
    assert.ok(Object.isFrozen(c));
    assert.ok(Object.isFrozen(c.features));
  }
});

test('every Claim<Empirical> is typed OUTSIDE the formal ledger vocabulary — it can never masquerade as a formal claim', () => {
  for (const statement of EMPIRICAL_CLAIM_FIXTURE) {
    const c = classifySentence(statement);
    assert.equal(c.kind, CLAIM_KIND.EMPIRICAL, `${statement}: kind ${c.kind}`);
    assert.equal(c.claim_type, 'empirical');
    assert.equal(CLAIM_TYPES.includes('empirical'), false, 'empirical is deliberately NOT a formal ledger claim type');
    assert.ok(c.confidence > 0);
  }
});

test('questions, hedges, and mundane prose are NEVER intercepted (nothing asserted, nothing to gate)', () => {
  for (const statement of NON_CLAIM_FIXTURE) {
    const c = classifySentence(statement);
    assert.equal(c.kind, CLAIM_KIND.NONE, `${statement}: kind ${c.kind}`);
    assert.equal(c.claim_type, null);
    assert.equal(c.confidence, 0);
  }
});

// =====================================================================================
// 2. REPLACING REGEX — paraphrases of one claim all intercept; no single template covers them.
// =====================================================================================

test('paraphrase diversity: the same mathematical fact intercepts under symbolic, spelled-out, and descriptive phrasing', () => {
  const paraphrases = [
    '2 + 2 = 4.',
    'Two plus two equals four.',
    'The number four is the sum of two and two.',
  ];
  for (const p of paraphrases) {
    assert.equal(classifySentence(p).kind, CLAIM_KIND.MATHEMATICAL, `${p}: must intercept regardless of phrasing`);
  }
});

test('subtype mapping: explicit numeric relations are computational; quantified claims are proof-bearing; bare properties are conceptual', () => {
  assert.equal(classifySentence('2 + 2 = 4.').claim_type, 'computational');
  assert.equal(classifySentence('The sum of the first 100 positive integers equals 5050.').claim_type, 'computational');
  assert.equal(classifySentence('Every even integer greater than 2 is the sum of two primes.').claim_type, 'proof-bearing');
  assert.equal(classifySentence('There exists a prime larger than 10^80.').claim_type, 'proof-bearing');
  assert.equal(classifySentence('The harmonic series diverges.').claim_type, 'conceptual');
});

test('proof burden wins ties: a quantified statement with a numeric relation is proof-bearing, not computational', () => {
  const c = classifySentence('For all n, the sum 1 + 2 + n equals n + 3.');
  assert.equal(c.kind, CLAIM_KIND.MATHEMATICAL);
  assert.equal(c.claim_type, 'proof-bearing');
});

test('a hedged MATHEMATICAL statement is not intercepted — a hedge means it was never asserted', () => {
  assert.equal(classifySentence('Maybe 2 + 2 = 5.').kind, CLAIM_KIND.NONE);
  assert.equal(classifySentence('I think the harmonic series diverges.').kind, CLAIM_KIND.NONE);
});

test('a question about mathematics is not an assertion', () => {
  assert.equal(classifySentence('Does the harmonic series converge or diverge?').kind, CLAIM_KIND.NONE);
});

// =====================================================================================
// 3. Feature extraction (transparency: the decision is a feature combination, not a template).
// =====================================================================================

test('extractFeatures exposes the independent semantic features the decision combines', () => {
  const f = extractFeatures('For all n, the product n * (n + 1) is even.');
  assert.equal(f.quantifiers >= 1, true);
  assert.equal(f.assertive, true);
  assert.ok(f.math_terms >= 1);
  assert.ok(f.math_symbols >= 1);
  assert.equal(f.digits, true);
  assert.equal(f.hedged, false);
  assert.equal(f.question, false);
  assert.ok(Object.isFrozen(f));
});

test('extractFeatures and classifySentence reject non-string input', () => {
  assert.throws(() => extractFeatures(42), /must be a string/);
  assert.throws(() => classifySentence(null), /must be a string/);
});

// =====================================================================================
// 4. Sentence segmentation — spans reconstruct; decimals never split.
// =====================================================================================

test('segmentSentences returns spans that reconstruct each statement from the original text', () => {
  const text = 'The harmonic series diverges. Is 7 prime? Hello!';
  const segments = segmentSentences(text);
  assert.equal(segments.length, 3);
  for (const { statement, span } of segments) {
    assert.equal(text.slice(span.start, span.end), statement);
  }
  assert.equal(segments[0].statement, 'The harmonic series diverges.');
  assert.equal(segments[1].statement, 'Is 7 prime?');
});

test('a decimal point never splits a sentence', () => {
  const segments = segmentSentences('The value 3.14 is close to 22/7.');
  assert.equal(segments.length, 1);
  assert.equal(segments[0].statement, 'The value 3.14 is close to 22/7.');
});

test('newlines are sentence boundaries; a trailing unterminated fragment is still a segment; base offsets spans', () => {
  const text = 'First line\nsecond fragment';
  const segments = segmentSentences(text, { base: 100 });
  assert.equal(segments.length, 2);
  assert.equal(segments[0].statement, 'First line');
  assert.equal(segments[0].span.start, 100);
  assert.equal(segments[1].statement, 'second fragment');
  assert.equal(text.slice(segments[1].span.start - 100, segments[1].span.end - 100), 'second fragment');
});

// =====================================================================================
// 5. interceptClaims — whole-text interception.
// =====================================================================================

test('interceptClaims intercepts ONLY the claims in mixed text, with sequential ids and reconstructing spans', () => {
  const text =
    'Hello there. Every even integer greater than 2 is the sum of two primes. ' +
    'We benchmarked the sieve and it averaged 40 milliseconds. See you tomorrow.';
  const claims = interceptClaims(text);
  assert.equal(claims.length, 2);
  assert.equal(claims[0].kind, CLAIM_KIND.MATHEMATICAL);
  assert.equal(claims[1].kind, CLAIM_KIND.EMPIRICAL);
  assert.deepEqual(claims.map((c) => c.id), ['sem::claim-0', 'sem::claim-1']);
  for (const c of claims) {
    assert.equal(text.slice(c.span.start, c.span.end), c.statement);
    assert.ok(Object.isFrozen(c));
  }
});

test('interceptClaims on claim-free text returns an empty (frozen) array', () => {
  const claims = interceptClaims('Hello! How are you today? See you at lunch.');
  assert.equal(claims.length, 0);
  assert.ok(Object.isFrozen(claims));
});

// =====================================================================================
// 6. The fixture batteries themselves are pinned and frozen.
// =====================================================================================

test('the fixture batteries are frozen and paraphrase-diverse (no empty batteries)', () => {
  assert.ok(Object.isFrozen(CLASSIFIER_FIXTURE));
  assert.ok(MATH_ASSERTION_FIXTURE.length >= 5);
  assert.ok(EMPIRICAL_CLAIM_FIXTURE.length >= 3);
  assert.ok(NON_CLAIM_FIXTURE.length >= 4);
});
