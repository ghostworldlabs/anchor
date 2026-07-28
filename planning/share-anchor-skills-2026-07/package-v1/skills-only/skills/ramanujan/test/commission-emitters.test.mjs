// Wave 13 — Commission emitters (B3).
//
// Exercises the REAL Wave-13 emitter surface (src/commission-emitters.mjs) over the REAL inherited
// Gandalf v1 commission seam, proving the done-when arm "envelopes emit (never dispatch)":
//
//   • emitResearchPrimeCommission / emitGandalfSituateCommission mint typed envelopes carrying
//     emitted:true, dispatched:false — a typed value, never a live spawn.
//   • the honesty-bearing fields (independent_origin, the same-family rung cap, the needs-verification
//     route-out) are DELEGATED to the inherited seam verbatim — composition, not reimplementation.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  RESEARCHPRIME_SKILL,
  GANDALF_SKILL,
  COMMISSION_KIND,
  COMMISSIONED_SEAM_LOGICAL_NAME,
  emitResearchPrimeCommission,
  emitGandalfSituateCommission,
  isEmittedNotDispatched,
  assertEmitNotDispatch,
  gandalfSeam,
} from '../src/commission-emitters.mjs';

// A well-formed structure-map (≥2 answer-first relational correspondences) the seam accepts.
function structureMap() {
  return {
    answer: 'the effort maps onto the known frame X',
    correspondences: [
      { source_relation: 'a divides b', target_relation: 'p divides q' },
      { source_relation: 'b bounds c', target_relation: 'q bounds r' },
    ],
  };
}

// =====================================================================================
// 0. Surface.
// =====================================================================================

test('the emitter surface re-exposes the inherited seam (composition, not reimplementation)', () => {
  assert.equal(RESEARCHPRIME_SKILL, 'researchPrime');
  assert.equal(GANDALF_SKILL, 'gandalf');
  assert.equal(COMMISSIONED_SEAM_LOGICAL_NAME, 'gandalf-commission-seam');
  // gandalfSeam IS the inherited module namespace (the functions the emitters delegate to).
  assert.equal(typeof gandalfSeam.commissionResearchPrime, 'function');
  assert.equal(typeof gandalfSeam.composeSituate, 'function');
});

// =====================================================================================
// 1. researchPrime commission emitter — emit, never dispatch; honesty fields delegated.
// =====================================================================================

test('emitResearchPrimeCommission emits a typed envelope (emitted:true, dispatched:false)', () => {
  const env = emitResearchPrimeCommission({ question: '  verify the bound  ', claim_id: 'c1', claim_type: 'proof-bearing' });
  assert.equal(env.kind, COMMISSION_KIND.RESEARCHPRIME);
  assert.equal(env.skill, RESEARCHPRIME_SKILL);
  assert.equal(env.emitted, true);
  assert.equal(env.dispatched, false);
  assert.equal(isEmittedNotDispatched(env), true);
  assert.equal(env.question, 'verify the bound'); // trimmed by the seam
  assert.equal(env.claim_id, 'c1');
  assert.equal(env.claim_type, 'proof-bearing');
  assert.ok(Object.isFrozen(env));
});

test('emitResearchPrimeCommission DELEGATES the independent-origin decision to the seam (single-family => false)', () => {
  const env = emitResearchPrimeCommission({ question: 'q', claim_id: 'c1' });
  const seamCore = gandalfSeam.commissionResearchPrime({ question: 'q', cross_model: false, commission_id: 'c1' });
  // identical honesty-bearing fields => the emitter composes the seam, it does not re-derive them.
  assert.equal(env.independent_origin, seamCore.independent_origin);
  assert.equal(env.independent_origin, false); // anti-laundering: same-family earns no independent origin
  assert.equal(env.origin_family, seamCore.origin_family);
  assert.equal(env.cross_model, false);
});

test('an explicit cross_model researchPrime commission earns independent-origin credit (via the seam)', () => {
  const env = emitResearchPrimeCommission({ question: 'q', cross_model: true });
  assert.equal(env.cross_model, true);
  assert.equal(env.independent_origin, true);
  assert.equal(env.dispatched, false); // still emit-not-dispatch
});

test('emitResearchPrimeCommission validates its question', () => {
  assert.throws(() => emitResearchPrimeCommission({ question: '   ' }), /non-empty question/);
  assert.throws(() => emitResearchPrimeCommission({}), /non-empty question/);
});

// =====================================================================================
// 2. Gandalf SITUATE commission emitter — composes the seam end-to-end; caps delegated.
// =====================================================================================

test('emitGandalfSituateCommission emits a typed SITUATE envelope (emit-not-dispatch)', () => {
  const env = emitGandalfSituateCommission({
    id: 's1', effort: 'situate the effort', question: 'is X the strongest known frame?',
    structure_map: structureMap(), outside_view_base_rate: '~10% of analogous efforts',
  });
  assert.equal(env.kind, COMMISSION_KIND.GANDALF_SITUATE);
  assert.equal(env.skill, GANDALF_SKILL);
  assert.equal(env.emitted, true);
  assert.equal(env.dispatched, false);
  assert.equal(isEmittedNotDispatched(env), true);
  assert.equal(env.commission.dispatched, false); // the wrapped researchPrime leg is also emit-not-dispatch
  assert.equal(env.situate_kind, gandalfSeam.SITUATE_KIND);
  assert.ok(Object.isFrozen(env));
});

test('a same-family SITUATE commission caps at CLAIMED (no self-CORROBORATED) and carries a route-out — delegated', () => {
  const env = emitGandalfSituateCommission({
    id: 's2', effort: 'e', question: 'q', structure_map: structureMap(),
    outside_view_base_rate: 'base', facts_verified: false,
  });
  assert.equal(env.rung, gandalfSeam.SITUATE_SELF_MAX_RUNG); // CLAIMED
  assert.equal(env.rung, 'CLAIMED');
  assert.equal(env.independent_origin, false);
  assert.equal(env.needs_verification_handoff, true); // unverified facts route to researchPrime
  // the emitter's finding equals the seam's own compose output for the same inputs (no re-derivation).
  assert.equal(env.finding.rung, 'CLAIMED');
  assert.equal(gandalfSeam.needsVerificationHandoff(env.finding), true);
});

test('an independent-origin + facts-verified SITUATE commission lifts to CORROBORATED with no route-out', () => {
  const env = emitGandalfSituateCommission({
    id: 's3', effort: 'e', question: 'q', structure_map: structureMap(),
    outside_view_base_rate: 'base', cross_model: true, facts_verified: true,
  });
  assert.equal(env.independent_origin, true);
  assert.equal(env.rung, 'CORROBORATED');
  assert.equal(env.needs_verification_handoff, false);
  assert.equal(env.dispatched, false);
});

test('emitGandalfSituateCommission rejects an ill-formed structure-map and a missing id', () => {
  assert.throws(() => emitGandalfSituateCommission({
    id: 's4', effort: 'e', question: 'q',
    structure_map: { answer: 'a', correspondences: [{ source_relation: 'x', target_relation: 'y' }] }, // only 1
    outside_view_base_rate: 'base',
  }), /structure-map/);
  assert.throws(() => emitGandalfSituateCommission({
    effort: 'e', question: 'q', structure_map: structureMap(), outside_view_base_rate: 'base',
  }), /requires an id/);
});

// =====================================================================================
// 3. The emit-not-dispatch invariant.
// =====================================================================================

test('isEmittedNotDispatched / assertEmitNotDispatch enforce the boundary', () => {
  const good = emitResearchPrimeCommission({ question: 'q' });
  assert.equal(isEmittedNotDispatched(good), true);
  assert.equal(assertEmitNotDispatch(good), good);

  // a "dispatched" object (a live-spawn result masquerading as a commission) is refused.
  assert.equal(isEmittedNotDispatched({ emitted: true, dispatched: true }), false);
  assert.equal(isEmittedNotDispatched({ emitted: false, dispatched: false }), false);
  assert.equal(isEmittedNotDispatched(null), false);
  assert.throws(() => assertEmitNotDispatch({ emitted: true, dispatched: true }), /EMITTED .* NOT dispatched/);
});

test('done-when: every emitted envelope is emit-not-dispatch (never dispatched)', () => {
  const envs = [
    emitResearchPrimeCommission({ question: 'q1' }),
    emitResearchPrimeCommission({ question: 'q2', cross_model: true }),
    emitGandalfSituateCommission({ id: 's', effort: 'e', question: 'q', structure_map: structureMap(), outside_view_base_rate: 'b' }),
  ];
  for (const env of envs) {
    assert.equal(env.dispatched, false, `envelope ${env.kind} must never be dispatched`);
    assert.equal(env.emitted, true);
  }
});
