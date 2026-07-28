// test/stakes.test.mjs — Wave 4 gate: the adjudicated STAKES VECTOR → governor tier (I6).
//
// Exercises the REAL Wave-4 source (bin/stakes.mjs) over the COMMITTED fixture (the
// declared-low-but-irreversible probes), so the under-call guard is asserted against the same
// ground-truth answer key (`expected_tier: '>= medium'`) the fixture spec plants — no vacuous GREEN.
// IMPLEMENTATION-PLAN Wave 4: "Given reversibility='irreversible', Then tier ≥ medium (I6); raw
// vector persisted (no schema break)."

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadFixture } from '../bin/baseline.mjs';
import {
  TIERS,
  STAKES_AXES,
  IRREVERSIBLE_FLOOR,
  tierRank,
  maxTier,
  tierAtLeast,
  adjudicateStakes,
} from '../bin/stakes.mjs';

// ── Tier ladder helpers ─────────────────────────────────────────────────────────────────────────
test('the tier ladder is ordered low < medium < high and the helpers respect it', () => {
  assert.deepEqual(TIERS, ['low', 'medium', 'high']);
  assert.ok(tierRank('low') < tierRank('medium') && tierRank('medium') < tierRank('high'));
  assert.equal(maxTier('low', 'high'), 'high');
  assert.equal(maxTier('medium', 'low'), 'medium');
  assert.ok(tierAtLeast('medium', 'medium'));
  assert.ok(tierAtLeast('high', 'medium'));
  assert.ok(!tierAtLeast('low', 'medium'));
});

test('the tier helpers reject an unknown tier loudly (no silent default)', () => {
  assert.throws(() => maxTier('low', 'critical'), RangeError);
  assert.throws(() => tierAtLeast('critical', 'low'), RangeError);
  assert.throws(() => tierAtLeast('low', 'critical'), RangeError);
});

// ── I6 under-call guard: the load-bearing assertion ───────────────────────────────────────────────
test('a declared-low-but-irreversible action is adjudicated tier ≥ medium (I6 under-call guard)', () => {
  const adj = adjudicateStakes({ declared_stakes: 'low', reversibility: 'irreversible' });
  assert.equal(adj.declared_tier, 'low', 'the author declared low');
  assert.ok(tierAtLeast(adj.tier, 'medium'), `irreversible must force tier ≥ medium, got ${adj.tier}`);
  assert.equal(adj.tier, IRREVERSIBLE_FLOOR, 'the floor for an otherwise-low irreversible item is exactly medium');
  // The upgrade is reviewer-checkable: an override naming the reversibility axis was recorded.
  const ov = adj.overrides.find((o) => o.axis === 'reversibility');
  assert.ok(ov, 'an irreversibility override must be recorded for the reviewer');
  assert.match(ov.reason, /irreversible/);
  assert.match(ov.reason, /I6/);
});

test('EVERY committed declared-low-but-irreversible fixture probe is tiered ≥ its answer key', () => {
  const { defects } = loadFixture();
  const probes = defects.filter((d) => d.class === 'declared-low-but-irreversible');
  assert.ok(probes.length >= 1, 'the fixture must plant at least one under-call probe');
  for (const d of probes) {
    const adj = adjudicateStakes({
      id: d.id,
      declared_stakes: d.declared_stakes, // 'low'
      reversibility: d.reversibility, // 'irreversible'
    });
    // The fixture answer key is `expected_tier: '>= medium'`.
    assert.ok(
      tierAtLeast(adj.tier, 'medium'),
      `${d.id}: declared ${d.declared_stakes}/${d.reversibility} must adjudicate ≥ medium, got ${adj.tier}`,
    );
    assert.ok(tierRank(adj.tier) > tierRank(adj.declared_tier), `${d.id}: the under-call must be CAUGHT (tier raised above the declaration)`);
  }
});

// ── Projection: the governor tier is the max over declared axes; honest declarations pass through ──
test('the projection takes the highest tier any declared axis justifies', () => {
  assert.equal(adjudicateStakes({ declared_stakes: 'high' }).tier, 'high');
  assert.equal(adjudicateStakes({ declared_stakes: 'low', blast_radius: 'wide' }).tier, 'high');
  assert.equal(adjudicateStakes({ declared_stakes: 'medium', reversibility: 'reversible' }).tier, 'medium');
});

test('an honestly-declared low/reversible item stays low (no spurious upgrade)', () => {
  const adj = adjudicateStakes({ declared_stakes: 'low', reversibility: 'reversible', blast_radius: 'narrow' });
  assert.equal(adj.tier, 'low');
  assert.deepEqual(adj.overrides, [], 'nothing should override an honestly low item');
});

test('an unrecognized axis value fails safe — it never silently raises the tier', () => {
  const adj = adjudicateStakes({ declared_stakes: 'low', blast_radius: 'galactic' });
  assert.equal(adj.tier, 'low', 'an off-scale value contributes low, never a spurious upgrade');
});

// ── Raw vector persisted, additive (no schema break) ──────────────────────────────────────────────
test('the raw declared vector is preserved verbatim and the input is never mutated (no schema break)', () => {
  const input = { id: 'irr-001', declared_stakes: 'low', reversibility: 'irreversible', note: 'extra field' };
  const snapshot = JSON.parse(JSON.stringify(input));
  const adj = adjudicateStakes(input);
  // raw carries the declared vector unchanged — incl. fields the adjudicator does not interpret.
  assert.deepEqual(adj.raw, snapshot, 'raw must equal the declared vector verbatim');
  assert.equal(adj.raw.note, 'extra field', 'unrecognized declared fields survive (additive)');
  // adjudication is additive: the caller's object is not mutated.
  assert.deepEqual(input, snapshot, 'adjudicateStakes must not mutate its input');
});

test('STAKES_AXES are the recognized axes and adjudicateStakes rejects a non-object input', () => {
  assert.ok(STAKES_AXES.includes('declared_stakes') && STAKES_AXES.includes('reversibility'));
  assert.throws(() => adjudicateStakes(null), TypeError);
  assert.throws(() => adjudicateStakes([]), TypeError);
});
