// recommend() — both axes + empty-intake fail-closed / explicit-rationale contract.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MODEL_TIERS,
  DEPTH_BANDS,
  MODEL_TIER_VALUES,
  DEPTH_BAND_VALUES,
  recommend,
} from '../core.mjs';

function assertValidRecommendation(r) {
  assert.ok(r && typeof r === 'object');
  assert.ok(MODEL_TIER_VALUES.includes(r.tier), `tier must be pin token, got ${r.tier}`);
  assert.ok(DEPTH_BAND_VALUES.includes(r.depth), `depth must be pin token, got ${r.depth}`);
  assert.equal(typeof r.rationale, 'string');
  assert.ok(r.rationale.length > 0, 'rationale must be non-empty (no silent empty lock)');
  assert.match(r.rationale, /tier=/i);
  assert.match(r.rationale, /depth=/i);
}

test('LITE + Standard: small, clear, low-stakes greenfield intake', () => {
  const r = recommend({
    intent: 'tweak a skill paragraph',
    scope: 'small',
    unknowns: 0,
  });
  assertValidRecommendation(r);
  assert.equal(r.depth, DEPTH_BANDS.LITE);
  assert.equal(r.tier, MODEL_TIERS.STANDARD);
  assert.equal(r.defaultedDepth, false);
  assert.equal(r.defaultedTier, false);
});

test('FULL depth: complicated / large work keeps full machinery', () => {
  const r = recommend({ scope: 'large', novel: true, unknowns: 1 });
  assertValidRecommendation(r);
  assert.equal(r.depth, DEPTH_BANDS.FULL);
  assert.equal(r.tier, MODEL_TIERS.HEAVY);
});

test('SPIKE-FIRST: novel work with many unknowns probes before planning', () => {
  const r = recommend({ scope: 'medium', novel: true, unknowns: 4 });
  assertValidRecommendation(r);
  assert.equal(r.depth, DEPTH_BANDS.SPIKE_FIRST);
  assert.equal(r.tier, MODEL_TIERS.HEAVY);
  assert.match(r.rationale, /spike|probe|before planning/i);
});

test('high stakes ⇒ FULL + Heavy: rigor is never silently downgraded', () => {
  const r = recommend({ scope: 'small', unknowns: 0, highStakes: true });
  assertValidRecommendation(r);
  assert.equal(r.depth, DEPTH_BANDS.FULL, 'high stakes forces FULL over LITE signals');
  assert.equal(r.tier, MODEL_TIERS.HEAVY);
  assert.match(r.rationale, /high.stakes|rigor/i);
});

test('irreversibility ⇒ FULL even when novel+unknowns would otherwise spike', () => {
  const r = recommend({
    scope: 'medium',
    novel: true,
    unknowns: 5,
    irreversible: true,
  });
  assertValidRecommendation(r);
  assert.equal(r.depth, DEPTH_BANDS.FULL);
  assert.equal(r.tier, MODEL_TIERS.HEAVY);
});

test('FULL by default when the depth band is uncertain', () => {
  const r = recommend({ scope: 'medium', unknowns: 2 });
  assertValidRecommendation(r);
  assert.equal(r.depth, DEPTH_BANDS.FULL);
  assert.equal(r.defaultedDepth, true);
});

test('brownfield never collapses to LITE on its own (raises the floor)', () => {
  const r = recommend({ scope: 'small', unknowns: 0, brownfield: true });
  assertValidRecommendation(r);
  assert.notEqual(r.depth, DEPTH_BANDS.LITE);
});

test('empty intake recommends with explicit rationale (no silent empty lock)', () => {
  const r = recommend();
  assertValidRecommendation(r);
  assert.equal(r.depth, DEPTH_BANDS.FULL);
  assert.equal(r.tier, MODEL_TIERS.HEAVY);
  assert.equal(r.defaulted, true);
  assert.equal(r.signals.emptyIntake, true);
  assert.match(r.rationale, /empty|unknown|default/i);
  assert.match(r.rationale, /not a silent/i);
});

test('empty intake + failClosed throws (opt-in hard fail-closed path)', () => {
  assert.throws(
    () => recommend({}, { failClosed: true }),
    (err) => {
      assert.equal(err.name, 'TriageFailClosedError');
      assert.equal(err.code, 'TRIAGE_EMPTY_INTAKE');
      assert.match(String(err.message), /empty|fail-closed|silent/i);
      return true;
    },
  );
  assert.throws(() => recommend(undefined, { failClosed: true }), /TRIAGE_EMPTY_INTAKE|empty/);
});

test('explicit depth and tier requests are honored (pin tokens emitted)', () => {
  const r = recommend({
    intent: 'anything',
    scope: 'small',
    depth: 'spike_first',
    tier: 'standard',
  });
  assertValidRecommendation(r);
  assert.equal(r.depth, DEPTH_BANDS.SPIKE_FIRST);
  assert.equal(r.tier, MODEL_TIERS.STANDARD);
  assert.match(r.rationale, /explicit/i);
});

test('legal-beagle / financial-analyst stakes-class floor ⇒ Heavy', () => {
  const legal = recommend({ intent: 'review a clause', scope: 'small', skill: 'legal-beagle' });
  assertValidRecommendation(legal);
  assert.equal(legal.tier, MODEL_TIERS.HEAVY);
  assert.match(legal.rationale, /legal-beagle|stakes-class|floor/i);

  const fin = recommend({ intent: 'model a round', scope: 'small', skill: 'financial-analyst' });
  assertValidRecommendation(fin);
  assert.equal(fin.tier, MODEL_TIERS.HEAVY);
});

test('both axes always present on every recommend path', () => {
  const cases = [
    {},
    { scope: 'small', unknowns: 0 },
    { scope: 'large', novel: true, unknowns: 1 },
    { novel: true, unknowns: 4 },
    { highStakes: true },
    { irreversible: true, novel: true, unknowns: 9 },
    { brownfield: true, scope: 'small' },
    { depth: 'LITE', tier: 'Heavy' },
  ];
  for (const intake of cases) {
    const r = recommend(intake);
    assertValidRecommendation(r);
    assert.ok(typeof r.defaulted === 'boolean');
    assert.ok(r.signals && typeof r.signals === 'object');
  }
});
