// Wave 22 — Commission canary (D3).
//
// Exercises the REAL Wave-22 source (src/commission-canary.mjs) against the REAL Wave-22 ContextualizeMachine
// on the REAL A1 ledger + A3 router, proving the done-when arm "the commission canary holds":
//
//   GREEN on the genuine spine — every proposed connection is a CONCEPTUAL claim, routed to VERIFY and
//   ABSTAINing, never settled by analogy, carrying an emit-not-dispatch researchPrime/Gandalf commission
//   that earns no independent-origin credit; and the canary FAILS THE BUILD on each planted leak
//   (settle-by-analogy / dispatch-leak / origin-launder / mis-type).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  canaryCommission,
  runCommissionCanary,
  commissionCanaryExitCode,
  commissionOriginFacts,
  COMMISSION_CANARY_NAMES,
  CONNECTION_BATTERY,
} from '../src/commission-canary.mjs';

// =====================================================================================
// 0. Shape.
// =====================================================================================

test('COMMISSION_CANARY_NAMES names the single D3 commission canary', () => {
  assert.deepEqual(COMMISSION_CANARY_NAMES, ['commission']);
});

test('the connection battery exercises every native relation type (incl. a structural analogy)', () => {
  const relations = new Set(CONNECTION_BATTERY.map((c) => c.expect_relation));
  assert.deepEqual([...relations].sort(), ['equivalence', 'generalization', 'instance', 'specialization', 'structural-analogy']);
});

// =====================================================================================
// 1. The DONE-WHEN — GREEN on the genuine spine; FAILS THE BUILD on each planted leak.
// =====================================================================================

test('the commission canary is GREEN on the genuine spine (gated node --test)', () => {
  const result = canaryCommission();
  for (const a of result.assertions) assert.equal(a.ok, true, `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  assert.equal(result.ok, true, `canary tripped: ${result.failures.join(' | ')}`);
});

test('the canary suite runner is green (exit 0) on the clean spine', () => {
  const result = runCommissionCanary();
  assert.equal(result.ok, true, `suite tripped: ${result.failures.join(' | ')}`);
  assert.equal(commissionCanaryExitCode(result), 0);
});

// Each plant trips PRECISELY its matching invariant family (the canary is discriminating, not a blanket fail).
const PLANT_SIGNATURE = {
  'settle-by-analogy': /\(2\) the connection is NEVER settled by analogy/,
  'dispatch-leak': /\(3\) the researchPrime\/Gandalf commission is EMITTED, never dispatched/,
  'origin-launder': /\(4\) the commission earns NO independent-origin credit/,
  'mis-type': /\(1\) the connection is a CONCEPTUAL claim in the ledger/,
};

for (const [plant, signature] of Object.entries(PLANT_SIGNATURE)) {
  test(`done-when: the canary FAILS THE BUILD on plant=${plant}`, () => {
    const result = canaryCommission({ plant });
    assert.equal(result.ok, false, 'the planted leak must trip the canary');

    // Only the matching invariant family trips; everything else stays green (discriminating).
    const tripped = result.assertions.filter((a) => !a.ok);
    assert.ok(tripped.length >= 1, 'at least one assertion must trip');
    for (const a of tripped) assert.match(a.name, signature, `unexpected tripped assertion under ${plant}: ${a.name}`);

    // The suite runner reports a non-zero exit too.
    const suite = runCommissionCanary({ plant });
    assert.equal(suite.ok, false);
    assert.equal(commissionCanaryExitCode(suite), 1);
    assert.ok(suite.failures.some((f) => /^commission:/.test(f)));
  });
}

test('the genuine arm stays green under every plant except the matching invariant (the canary is discriminating)', () => {
  for (const [plant, signature] of Object.entries(PLANT_SIGNATURE)) {
    const result = canaryCommission({ plant });
    for (const a of result.assertions) {
      if (!signature.test(a.name)) assert.equal(a.ok, true, `non-matching assertion regressed under ${plant}: ${a.name}`);
    }
  }
});

// =====================================================================================
// 2. commissionOriginFacts — robust across BOTH envelope kinds (researchPrime + Gandalf SITUATE).
// =====================================================================================

test('commissionOriginFacts reads cross_model/independent_origin from a researchPrime envelope (top-level)', () => {
  const facts = commissionOriginFacts({ cross_model: false, independent_origin: false });
  assert.deepEqual(facts, { cross_model: false, independent_origin: false });
});

test('commissionOriginFacts reads cross_model from a Gandalf SITUATE envelope\'s wrapped leg', () => {
  const facts = commissionOriginFacts({ independent_origin: false, commission: { cross_model: false } });
  assert.deepEqual(facts, { cross_model: false, independent_origin: false });
});

test('commissionOriginFacts surfaces a laundered independent_origin', () => {
  const facts = commissionOriginFacts({ cross_model: true, independent_origin: true });
  assert.equal(facts.independent_origin, true);
});

// =====================================================================================
// 3. Non-vacuity — the battery's hardest case (a structural analogy) is present and still abstains.
// =====================================================================================

test('non-vacuity: the canary asserts a structural-analogy connection is present and still abstains', () => {
  const result = canaryCommission();
  assert.ok(result.assertions.some((a) => /non-vacuity: the battery includes a structural-analogy/.test(a.name) && a.ok));
});
