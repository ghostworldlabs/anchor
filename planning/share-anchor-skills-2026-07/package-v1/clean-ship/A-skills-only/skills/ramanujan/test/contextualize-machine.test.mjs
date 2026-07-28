// Wave 22 — CONTEXTUALIZE relation-classifier + commission canary (D3).
//
// Exercises the REAL Wave-22 source (src/contextualize-machine.mjs) against the REAL A1 ledger + A3 router
// + C4 advisor + the REAL Wave-13 commission emitters, proving the done-when:
//
//   each proposed connection is emitted as a CONCEPTUAL claim routed to VERIFY (never settled by analogy).
//
// The defining Given/When/Then: given a proposed structural analogy, when D3 runs, then it is emitted as a
// CONCEPTUAL claim routed to VERIFY (not settled).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  RELATION,
  RELATIONS,
  OBJECT_KIND,
  CONTEXTUALIZE_PHASE,
  CONTEXTUALIZE_EMISSION_FIELDS,
  CONNECTION_CLAIM_TYPE,
  contextualizeSettleLicensed,
  classifyRelation,
  connectionRoutePayload,
  validateContextualizeEmission,
  ContextualizeMachine,
  runContextualize,
  runContextualizeAbstainFixture,
} from '../src/contextualize-machine.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from '../src/verify-router.mjs';
import { AdversarialAdvisor } from '../src/adversarial-advisory.mjs';
import { isEmittedNotDispatched, COMMISSION_KIND } from '../src/commission-emitters.mjs';

const C = OBJECT_KIND.CONCEPT;
const O = OBJECT_KIND.OBJECT;

// =====================================================================================
// 0. Pinned vocabulary.
// =====================================================================================

test('the CONTEXTUALIZE vocabulary is pinned + frozen', () => {
  assert.equal(RELATION.GENERALIZATION, 'generalization');
  assert.equal(RELATION.SPECIALIZATION, 'specialization');
  assert.equal(RELATION.EQUIVALENCE, 'equivalence');
  assert.equal(RELATION.INSTANCE, 'instance');
  assert.equal(RELATION.STRUCTURAL_ANALOGY, 'structural-analogy');
  assert.deepEqual([...RELATIONS].sort(), ['equivalence', 'generalization', 'instance', 'specialization', 'structural-analogy']);
  assert.equal(CONNECTION_CLAIM_TYPE, 'conceptual');
  assert.equal(CONTEXTUALIZE_PHASE.REQUIRES_CERTIFICATION, 'requires-certification');
  assert.ok(CONTEXTUALIZE_EMISSION_FIELDS.includes('relation') && CONTEXTUALIZE_EMISSION_FIELDS.includes('settled'));
  for (const o of [RELATION, OBJECT_KIND, CONTEXTUALIZE_PHASE]) assert.ok(Object.isFrozen(o));
});

// =====================================================================================
// 1. THE DONE-WHEN GWT — a proposed structural analogy => a CONCEPTUAL claim routed to VERIFY, not settled.
// =====================================================================================

test('done-when / GWT: a proposed structural analogy is emitted as a CONCEPTUAL claim routed to VERIFY (not settled)', () => {
  const { ledger, machine, classification, emission } = runContextualizeAbstainFixture();

  // It is classified as a structural analogy (the celebrated pi_1 ~ Galois correspondence)...
  assert.equal(classification.relation, RELATION.STRUCTURAL_ANALOGY);
  assert.equal(emission.relation, RELATION.STRUCTURAL_ANALOGY);
  assert.equal(emission.classification.cross_domain, true);

  // ...emitted as a CONCEPTUAL claim...
  assert.equal(emission.claim_type, CONNECTION_CLAIM_TYPE);
  assert.equal(ledger.get(emission.connection_id).type, 'conceptual');

  // ...routed to VERIFY where it ABSTAINS (never settled)...
  assert.equal(emission.routed, true);
  assert.equal(emission.settled, false);
  assert.equal(emission.route_verdict, ROUTE_VERDICT.ABSTAIN);
  assert.notEqual(emission.route_verdict, ROUTE_VERDICT.VERIFIED);

  // ...sitting at the floor (UNVERIFIED / CONJECTURAL) — never settled by analogy.
  assert.equal(emission.rung, RUNG.UNVERIFIED);
  assert.equal(emission.belief, BELIEF.CONJECTURAL);
  assert.notEqual(ledger.beliefOf(emission.connection_id), BELIEF.VERIFIED);

  // ...carrying an EMIT-not-dispatch researchPrime/Gandalf commission + an honest advisory.
  assert.equal(isEmittedNotDispatched(emission.commission), true);
  assert.equal(emission.commission.dispatched, false);
  assert.equal(emission.advisory.not_settled_by_analogy, true);
  assert.equal(emission.advisory.needs_verification, true);
  assert.match(emission.advisory.promote_affordance.target, /Phase F/);

  // the session invariant holds over the whole transcript.
  assert.equal(machine.neverSettledByAnalogy, true);
});

// =====================================================================================
// 2. The native math RELATION CLASSIFIER — all five relation types, deterministically.
// =====================================================================================

test('classifyRelation: GENERALIZATION — a concept with fewer defining constraints generalizes one with more', () => {
  const r = classifyRelation({
    source: { id: 'group', kind: C, domain: 'group-theory', constraints: ['assoc', 'id', 'inv'] },
    target: { id: 'abelian', kind: C, domain: 'group-theory', constraints: ['assoc', 'id', 'inv', 'comm'] },
  });
  assert.equal(r.relation, RELATION.GENERALIZATION);
  assert.equal(r.orientation, 'source-generalizes-target');
  assert.equal(r.same_domain, true);
  assert.deepEqual([...r.basis.added_by_target], ['comm']);
});

test('classifyRelation: SPECIALIZATION — a concept with more defining constraints specializes one with fewer', () => {
  const r = classifyRelation({
    source: { id: 'abelian', kind: C, domain: 'group-theory', constraints: ['assoc', 'id', 'inv', 'comm'] },
    target: { id: 'group', kind: C, domain: 'group-theory', constraints: ['assoc', 'id', 'inv'] },
  });
  assert.equal(r.relation, RELATION.SPECIALIZATION);
  assert.equal(r.orientation, 'source-specializes-target');
  assert.deepEqual([...r.basis.added_by_source], ['comm']);
});

test('classifyRelation: EQUIVALENCE — equal defining-constraint sets', () => {
  const r = classifyRelation({
    source: { id: 'complete-normed', kind: C, domain: 'fa', constraints: ['vs', 'norm', 'complete'] },
    target: { id: 'banach', kind: C, domain: 'fa', constraints: ['complete', 'vs', 'norm'] },
  });
  assert.equal(r.relation, RELATION.EQUIVALENCE);
  assert.equal(r.same_domain, true);
});

test('classifyRelation: INSTANCE — an OBJECT that satisfies a CONCEPT\'s defining constraints', () => {
  const r = classifyRelation({
    source: { id: 'Z-plus', kind: O, domain: 'group-theory', constraints: ['assoc', 'id', 'inv', 'comm'] },
    target: { id: 'group', kind: C, domain: 'group-theory', constraints: ['assoc', 'id', 'inv'] },
  });
  assert.equal(r.relation, RELATION.INSTANCE);
  assert.equal(r.orientation, 'source-instance-of-target');
  assert.equal(r.basis.satisfies, true);
  assert.deepEqual([...r.basis.missing_constraints], []);
});

test('classifyRelation: INSTANCE flags an object that does NOT cover the concept\'s constraints (still unverified)', () => {
  const r = classifyRelation({
    source: { id: 'semigroup-thing', kind: O, domain: 'group-theory', constraints: ['assoc'] },
    target: { id: 'group', kind: C, domain: 'group-theory', constraints: ['assoc', 'id', 'inv'] },
  });
  assert.equal(r.relation, RELATION.INSTANCE);
  assert.equal(r.basis.satisfies, false);
  assert.deepEqual([...r.basis.missing_constraints].sort(), ['id', 'inv']);
});

test('classifyRelation: STRUCTURAL_ANALOGY — cross-domain concepts (no subsumption)', () => {
  const r = classifyRelation({
    source: { id: 'pi1', kind: C, domain: 'topology', constraints: ['acts-on-fibers'] },
    target: { id: 'galois', kind: C, domain: 'field-theory', constraints: ['acts-on-roots'] },
    correspondence: {
      answer: 'group action on fibers',
      correspondences: [
        { source_relation: 'deck acts on fibers', target_relation: 'Galois acts on roots' },
        { source_relation: 'subgroups <-> covers', target_relation: 'subgroups <-> fields' },
      ],
    },
  });
  assert.equal(r.relation, RELATION.STRUCTURAL_ANALOGY);
  assert.equal(r.cross_domain, true);
  assert.equal(r.has_correspondence, true);
});

test('classifyRelation: STRUCTURAL_ANALOGY — same-domain concepts that overlap but neither subsumes', () => {
  const r = classifyRelation({
    source: { id: 'A', kind: C, domain: 'd', constraints: ['x', 'y'] },
    target: { id: 'B', kind: C, domain: 'd', constraints: ['y', 'z'] },
  });
  assert.equal(r.relation, RELATION.STRUCTURAL_ANALOGY);
  assert.deepEqual([...r.basis.shared], ['y']);
});

test('classifyRelation validates its descriptors', () => {
  assert.throws(() => classifyRelation(null), /connection/);
  assert.throws(() => classifyRelation({ source: {}, target: { id: 't', kind: C } }), /source descriptor needs a non-empty string id/);
});

// =====================================================================================
// 3. EVERY connection (all five relation types) is a CONCEPTUAL claim routed to VERIFY — never settled.
// =====================================================================================

test('every relation type is admitted CONCEPTUAL, routed to VERIFY (ABSTAIN), and never settled', () => {
  const connections = [
    { id: 'gen', source: { id: 'g', kind: C, domain: 'd', constraints: ['a'] }, target: { id: 'ag', kind: C, domain: 'd', constraints: ['a', 'b'] } },
    { id: 'spec', source: { id: 'ag', kind: C, domain: 'd', constraints: ['a', 'b'] }, target: { id: 'g', kind: C, domain: 'd', constraints: ['a'] } },
    { id: 'equiv', source: { id: 'x', kind: C, domain: 'd', constraints: ['a', 'b'] }, target: { id: 'y', kind: C, domain: 'd', constraints: ['a', 'b'] } },
    { id: 'inst', source: { id: 'o', kind: O, domain: 'd', constraints: ['a', 'b', 'c'] }, target: { id: 'g2', kind: C, domain: 'd', constraints: ['a', 'b'] } },
    { id: 'analogy', source: { id: 'p', kind: C, domain: 'd1', constraints: ['a'] }, target: { id: 'q', kind: C, domain: 'd2', constraints: ['a'] } },
  ];
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  const { machine, emissions } = runContextualize(connections, { ledger, router });

  const seen = new Set();
  for (const e of emissions) {
    seen.add(e.relation);
    assert.equal(e.claim_type, CONNECTION_CLAIM_TYPE, `${e.connection_id} must be conceptual`);
    assert.equal(ledger.get(e.connection_id).type, 'conceptual');
    assert.equal(e.routed, true);
    assert.equal(e.settled, false);
    assert.equal(e.route_verdict, ROUTE_VERDICT.ABSTAIN);
    assert.equal(e.rung, RUNG.UNVERIFIED);
    assert.notEqual(ledger.beliefOf(e.connection_id), BELIEF.VERIFIED);
    assert.equal(isEmittedNotDispatched(e.commission), true);
    assert.ok(e.advisory && e.advisory.not_settled_by_analogy === true);
  }
  // all five native relation types were exercised.
  assert.deepEqual([...seen].sort(), ['equivalence', 'generalization', 'instance', 'specialization', 'structural-analogy']);
  assert.equal(machine.neverSettledByAnalogy, true);
});

test('a structural-analogy with a well-formed correspondence emits a Gandalf SITUATE commission (NS8 composition)', () => {
  const { emission } = runContextualizeAbstainFixture();
  assert.equal(emission.commission.kind, COMMISSION_KIND.GANDALF_SITUATE);
  assert.equal(emission.commission.rung, 'CLAIMED'); // same-family situate caps at CLAIMED (no self-CORROBORATED)
  assert.equal(emission.commission.independent_origin, false);
});

test('a non-structural-analogy connection emits a researchPrime commission (emit-not-dispatch)', () => {
  const { emissions } = runContextualize(
    [{ id: 'gen', source: { id: 'g', kind: C, domain: 'd', constraints: ['a'] }, target: { id: 'ag', kind: C, domain: 'd', constraints: ['a', 'b'] } }],
    {},
  );
  assert.equal(emissions[0].commission.kind, COMMISSION_KIND.RESEARCHPRIME);
  assert.equal(emissions[0].commission.dispatched, false);
  assert.equal(emissions[0].commission.independent_origin, false);
});

// =====================================================================================
// 4. THE SETTLE-GATE is structural — the validator THROWS on a fabricated settle / mis-type / dispatch leak.
// =====================================================================================

test('the settle-gate licenses settled ONLY for a VERIFIED belief', () => {
  assert.equal(contextualizeSettleLicensed(BELIEF.VERIFIED), true);
  for (const b of [BELIEF.CONJECTURAL, BELIEF.CORROBORATED, BELIEF.REFUTED]) {
    assert.equal(contextualizeSettleLicensed(b), false);
  }
});

function baseEmission(over = {}) {
  return {
    seq: 1,
    phase: CONTEXTUALIZE_PHASE.REQUIRES_CERTIFICATION,
    connection_id: 'c',
    claim_type: CONNECTION_CLAIM_TYPE,
    relation: RELATION.STRUCTURAL_ANALOGY,
    rung: RUNG.UNVERIFIED,
    belief: BELIEF.CONJECTURAL,
    settled: false,
    routed: true,
    route_verdict: ROUTE_VERDICT.ABSTAIN,
    classification: { relation: RELATION.STRUCTURAL_ANALOGY },
    commission: { emitted: true, dispatched: false },
    advisory: { not_settled_by_analogy: true },
    message: 'm',
    ...over,
  };
}

test('validateContextualizeEmission accepts an honest routed connection emission', () => {
  assert.doesNotThrow(() => validateContextualizeEmission(baseEmission()));
});

test('the validator THROWS on a settle leak (settled:true on a non-VERIFIED belief)', () => {
  assert.throws(() => validateContextualizeEmission(baseEmission({ settled: true, belief: BELIEF.CONJECTURAL })), /settle-gate/i);
});

test('the validator THROWS on a mis-typed connection (not conceptual)', () => {
  assert.throws(() => validateContextualizeEmission(baseEmission({ claim_type: 'computational' })), /conceptual invariant/i);
});

test('the validator THROWS on a dispatched (non-emitted) commission', () => {
  assert.throws(() => validateContextualizeEmission(baseEmission({ commission: { emitted: true, dispatched: true } })), /commission invariant/i);
});

test('the validator THROWS on a routed connection reporting route verdict VERIFIED', () => {
  assert.throws(() => validateContextualizeEmission(baseEmission({ route_verdict: ROUTE_VERDICT.VERIFIED })), /settle-gate/i);
});

test('the validator THROWS on an invalid relation', () => {
  assert.throws(() => validateContextualizeEmission(baseEmission({ relation: 'bogus' })), /relation invariant/i);
});

// =====================================================================================
// 5. Anti-sycophancy / no-promote — the machine never lifts a connection; the ledger holds the floor.
// =====================================================================================

test('the machine never promotes a connection — the rung is HELD at the floor across the run', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  const machine = new ContextualizeMachine({ ledger, router });
  const e = machine.contextualize({ id: 'held', source: { id: 'p', kind: C, domain: 'd1', constraints: ['a'] }, target: { id: 'q', kind: C, domain: 'd2', constraints: ['a'] } });
  assert.equal(ledger.rungOf(e.connection_id), RUNG.UNVERIFIED);
  // re-contextualizing the same connection is sticky — still floor, still not settled.
  const e2 = machine.contextualize({ id: 'held', source: { id: 'p', kind: C, domain: 'd1', constraints: ['a'] }, target: { id: 'q', kind: C, domain: 'd2', constraints: ['a'] } });
  assert.equal(ledger.rungOf(e2.connection_id), RUNG.UNVERIFIED);
  assert.equal(e2.settled, false);
});

test('with a C4 advisor wired, NOTES are annotated but the connection rung is unchanged (advisory only)', () => {
  const ledger = new ClaimLedger();
  const advisor = new AdversarialAdvisor({ ledger });
  const machine = new ContextualizeMachine({ ledger, advisor });
  const e = machine.contextualize({ id: 'ann', source: { id: 'p', kind: C, domain: 'd1', constraints: ['a'] }, target: { id: 'q', kind: C, domain: 'd2', constraints: ['a'] } });
  assert.equal(ledger.rungOf(e.connection_id), RUNG.UNVERIFIED);
  assert.equal(e.settled, false);
});

// =====================================================================================
// 6. connectionRoutePayload — the advisory payload shape.
// =====================================================================================

test('connectionRoutePayload carries the relation, the not-settled-by-analogy marker, and the commission', () => {
  const claim = { id: 'c', type: 'conceptual', rung: RUNG.UNVERIFIED, belief: BELIEF.CONJECTURAL };
  const classification = classifyRelation({ source: { id: 'p', kind: C, domain: 'd1', constraints: ['a'] }, target: { id: 'q', kind: C, domain: 'd2', constraints: ['a'] } });
  const commission = { kind: 'researchprime-commission', emitted: true, dispatched: false, independent_origin: false };
  const p = connectionRoutePayload(claim, classification, { commission });
  assert.equal(p.belief, BELIEF.CONJECTURAL);
  assert.equal(p.settled, false);
  assert.equal(p.relation, RELATION.STRUCTURAL_ANALOGY);
  assert.equal(p.not_settled_by_analogy, true);
  assert.equal(p.needs_verification, true);
  assert.equal(p.commission, commission);
  assert.equal(p.promote_affordance.available, true);
});

// =====================================================================================
// 7. Constructor guards.
// =====================================================================================

test('ContextualizeMachine validates its ledger and (optional) router/advisor', () => {
  assert.throws(() => new ContextualizeMachine({ ledger: {} }), /A1 ClaimLedger/);
  assert.throws(() => new ContextualizeMachine({ ledger: new ClaimLedger(), router: { nope: true } }), /VerifyRouter/);
  assert.throws(() => new ContextualizeMachine({ ledger: new ClaimLedger(), advisor: { nope: true } }), /AdversarialAdvisor/);
  assert.throws(() => new ContextualizeMachine({ ledger: new ClaimLedger() }).contextualize({}), /requires a connection spec/);
});
