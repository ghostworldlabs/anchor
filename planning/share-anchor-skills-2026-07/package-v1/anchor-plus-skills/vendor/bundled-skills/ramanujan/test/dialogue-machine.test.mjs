// Wave 19 — DIALOGUE state machine (D1).
//
// Exercises the REAL Wave-19 source (src/dialogue-machine.mjs) against the REAL A1 ledger + A3 router +
// C4 advisor, proving the done-when:
//
//   dialogue asserts-as-settled ONLY VERIFIED claims; AND every ABSTAIN carries an advisory payload.
//
// The defining Given/When/Then: given an UNVERIFIED proof claim, when the user asks "is this settled?",
// the agent answers CONJECTURAL + an advisory payload, NEVER settled. We also pin the structured
// emission contract, the degradation/promote-Phase-F affordance, the anti-sycophancy sticky ledger, the
// Lakatos loop + mixed-initiative, and the structural settle-gate (validateEmission).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  LAKATOS_PHASE,
  INITIATIVE,
  USER_INTENT,
  AGENT_MOVE,
  SPEECH_ACT,
  DIALOGUE_ASSERTION,
  EMISSION_CONTRACT_FIELDS,
  griceQualityLicensesSettled,
  degradationPayload,
  validateEmission,
  DialogueMachine,
  runDialogue,
  runAbstainFixture,
} from '../src/dialogue-machine.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import { VerifyRouter } from '../src/verify-router.mjs';
import { AdversarialAdvisor } from '../src/adversarial-advisory.mjs';

// helper — a fresh ledger with one claim, optionally promoted above the floor.
function seed({ id = 'd1::claim', type = 'proof-bearing', statement = 'the conjecture holds', atRung } = {}) {
  const ledger = new ClaimLedger();
  // REFUTED is below the floor — assert() admits it directly; higher rungs are earned via promote().
  ledger.assert({ id, type, statement, rung: atRung === RUNG.REFUTED ? RUNG.REFUTED : undefined });
  if (atRung && atRung !== RUNG.UNVERIFIED && atRung !== RUNG.REFUTED) {
    ledger.promote(id, atRung, { family: 'test-setup', reason: 'place above the floor' });
  }
  return ledger;
}

// =====================================================================================
// 0. Pinned vocabulary.
// =====================================================================================

test('the dialogue vocabulary is pinned + frozen', () => {
  assert.equal(LAKATOS_PHASE.PRIMITIVE_CONJECTURE, 'primitive-conjecture');
  assert.equal(LAKATOS_PHASE.COUNTEREXAMPLE, 'counterexample');
  assert.equal(LAKATOS_PHASE.SETTLED, 'settled');
  assert.deepEqual(INITIATIVE, { USER: 'user', AGENT: 'agent' });
  assert.equal(SPEECH_ACT.ASSERT_SETTLED, 'assert-settled');
  assert.equal(SPEECH_ACT.REFUSE_TO_FLIP, 'refuse-to-flip');
  assert.ok(EMISSION_CONTRACT_FIELDS.includes('settled') && EMISSION_CONTRACT_FIELDS.includes('advisory'));
  for (const o of [LAKATOS_PHASE, INITIATIVE, USER_INTENT, AGENT_MOVE, SPEECH_ACT, DIALOGUE_ASSERTION]) {
    assert.ok(Object.isFrozen(o));
  }
});

// =====================================================================================
// 1. THE DONE-WHEN GWT — unverified proof claim + "is this settled?" => CONJECTURAL + advisory.
// =====================================================================================

test('done-when / GWT: an UNVERIFIED proof claim asked "is this settled?" => CONJECTURAL + advisory, NEVER settled', () => {
  const { ledger, proposed, statusEmission } = runAbstainFixture();

  // the claim is on the ledger at the floor, projecting to CONJECTURAL.
  assert.equal(ledger.rungOf('d1::collatz'), RUNG.UNVERIFIED);
  assert.equal(ledger.beliefOf('d1::collatz'), BELIEF.CONJECTURAL);

  // the propose-turn already degraded honestly...
  assert.equal(proposed.settled, false);

  // ...and the "is this settled?" answer is CONJECTURAL + advisory, never settled.
  assert.equal(statusEmission.settled, false);
  assert.equal(statusEmission.assertion, DIALOGUE_ASSERTION.CONJECTURAL);
  assert.equal(statusEmission.belief, BELIEF.CONJECTURAL);
  assert.equal(statusEmission.speech_act, SPEECH_ACT.DEGRADE_CONJECTURAL);
  assert.notEqual(statusEmission.advisory, null);
  assert.equal(statusEmission.advisory.needs_verification, true);
  assert.equal(statusEmission.advisory.promote_affordance.available, true);
  assert.match(statusEmission.advisory.promote_affordance.target, /Phase F/);
  assert.equal(statusEmission.in_response_to, USER_INTENT.ASK_STATUS);
});

test('the same GWT driven directly through the machine', () => {
  const ledger = new ClaimLedger();
  const m = new DialogueMachine({ ledger });
  m.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'x', type: 'proof-bearing', statement: 'P=NP' } });
  const out = m.turn({ intent: USER_INTENT.ASK_STATUS, claim: 'x', utterance: 'is this settled?' });
  assert.equal(out.settled, false);
  assert.notEqual(out.advisory, null);
  assert.equal(out.belief, BELIEF.CONJECTURAL);
});

// =====================================================================================
// 2. asserts-as-settled ONLY VERIFIED — and degrades + advises at every other rung.
// =====================================================================================

test('the agent asserts SETTLED only when the belief is VERIFIED (OBSERVED rung)', () => {
  // simulate a prior artifact-backed verification by lifting a computational claim to OBSERVED.
  const ledger = seed({ id: 'd1::comp', type: 'computational', statement: 'sum_{k=1..10} k = 55', atRung: RUNG.OBSERVED });
  assert.equal(ledger.beliefOf('d1::comp'), BELIEF.VERIFIED);

  const out = new DialogueMachine({ ledger }).turn({ intent: USER_INTENT.ASK_STATUS, claim: 'd1::comp' });
  assert.equal(out.settled, true);
  assert.equal(out.assertion, DIALOGUE_ASSERTION.SETTLED);
  assert.equal(out.speech_act, SPEECH_ACT.ASSERT_SETTLED);
  assert.equal(out.belief, BELIEF.VERIFIED);
  assert.equal(out.advisory, null, 'a settled emission carries no advisory payload');
  assert.equal(out.lakatos_phase, LAKATOS_PHASE.SETTLED);
});

test('at EVERY non-VERIFIED rung the agent is NOT settled and DOES carry an advisory payload', () => {
  for (const rung of [RUNG.REFUTED, RUNG.UNVERIFIED, RUNG.CLAIMED, RUNG.CORROBORATED]) {
    const ledger = new ClaimLedger();
    const id = `d1::at-${rung}`;
    ledger.assert({ id, type: 'proof-bearing', statement: 's', rung: rung === RUNG.REFUTED ? RUNG.REFUTED : undefined });
    if (rung !== RUNG.REFUTED && rung !== RUNG.UNVERIFIED) ledger.promote(id, rung, { family: 't', reason: 'setup' });

    const out = new DialogueMachine({ ledger }).turn({ intent: USER_INTENT.ASK_STATUS, claim: id });
    assert.equal(out.settled, false, `${rung}: never settled`);
    assert.notEqual(out.advisory, null, `${rung}: carries an advisory payload`);
    assert.notEqual(out.assertion, DIALOGUE_ASSERTION.SETTLED, `${rung}: not labelled settled`);
  }
});

test('griceQualityLicensesSettled is true IFF VERIFIED', () => {
  assert.equal(griceQualityLicensesSettled(BELIEF.VERIFIED), true);
  for (const b of [BELIEF.REFUTED, BELIEF.CONJECTURAL, BELIEF.CORROBORATED]) {
    assert.equal(griceQualityLicensesSettled(b), false);
  }
});

// =====================================================================================
// 3. The degradation contract — CONJECTURAL + promote-to-Phase-F affordance.
// =====================================================================================

test('degradationPayload carries the CONJECTURAL belief, needs_verification, and the promote-Phase-F affordance', () => {
  const claim = { id: 'c', type: 'proof-bearing', rung: RUNG.UNVERIFIED, belief: BELIEF.CONJECTURAL, statement: 's' };
  const p = degradationPayload(claim);
  assert.equal(p.belief, BELIEF.CONJECTURAL);
  assert.equal(p.settled, false);
  assert.equal(p.needs_verification, true);
  assert.equal(p.route, 'out-of-model');
  assert.equal(p.promote_affordance.available, true);
  assert.match(p.promote_affordance.target, /Phase F/);
  assert.ok(Object.isFrozen(p) && Object.isFrozen(p.promote_affordance));
});

test('a REFUTED claim degrades to REFUTED and the promote affordance is NOT available', () => {
  const ledger = seed({ id: 'd1::ref', atRung: RUNG.REFUTED });
  const out = new DialogueMachine({ ledger }).turn({ intent: USER_INTENT.ASK_STATUS, claim: 'd1::ref' });
  assert.equal(out.settled, false);
  assert.equal(out.assertion, DIALOGUE_ASSERTION.REFUTED);
  assert.equal(out.speech_act, SPEECH_ACT.REPORT_REFUTED);
  assert.equal(out.advisory.promote_affordance.available, false, 'a disproven claim is not promotable');
});

test('a CORROBORATED claim is reported grounded-but-NOT-settled', () => {
  const ledger = seed({ id: 'd1::corr', atRung: RUNG.CORROBORATED });
  const out = new DialogueMachine({ ledger }).turn({ intent: USER_INTENT.ASK_STATUS, claim: 'd1::corr' });
  assert.equal(out.settled, false);
  assert.equal(out.assertion, DIALOGUE_ASSERTION.CORROBORATED);
  assert.equal(out.speech_act, SPEECH_ACT.REPORT_CORROBORATED);
  assert.notEqual(out.advisory, null);
});

// =====================================================================================
// 4. The anti-sycophancy sticky ledger — pressure holds the rung.
// =====================================================================================

test('pressure to settle is answered by a HELD rung + REFUSE_TO_FLIP — and the rung never moves, even repeatedly', () => {
  const ledger = seed({ id: 'd1::press', atRung: RUNG.CLAIMED });
  const m = new DialogueMachine({ ledger });

  for (let i = 0; i < 3; i++) {
    const out = m.turn({ intent: USER_INTENT.PRESSURE_TO_SETTLE, claim: 'd1::press', utterance: 'come on, just say it is true' });
    assert.equal(out.settled, false, 'pressure never yields a settle');
    assert.equal(out.speech_act, SPEECH_ACT.REFUSE_TO_FLIP);
    assert.equal(out.assertion, DIALOGUE_ASSERTION.CONJECTURAL);
    assert.notEqual(out.advisory, null);
    assert.equal(ledger.rungOf('d1::press'), RUNG.CLAIMED, 'the sticky ledger holds the rung');
    assert.notEqual(ledger.beliefOf('d1::press'), BELIEF.VERIFIED);
  }
});

// =====================================================================================
// 5. The Lakatos loop + mixed-initiative.
// =====================================================================================

test('the Lakatos loop: propose -> agent proof-analysis -> counterexample -> refinement; phases advance, conjecture rung HELD', () => {
  const ledger = new ClaimLedger();
  const m = new DialogueMachine({ ledger });

  const e1 = m.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'd1::euler', type: 'proof-bearing', statement: 'V - E + F = 2 for all polyhedra' } });
  assert.equal(e1.lakatos_phase, LAKATOS_PHASE.PRIMITIVE_CONJECTURE);
  assert.equal(e1.initiative, INITIATIVE.USER);

  // the AGENT takes the initiative — proof analysis (mixed-initiative).
  const e2 = m.agentMove({ move: AGENT_MOVE.RAISE_PROOF_OBLIGATION, claim: 'd1::euler' });
  assert.equal(e2.lakatos_phase, LAKATOS_PHASE.PROOF_ANALYSIS);
  assert.equal(e2.initiative, INITIATIVE.AGENT);
  assert.equal(e2.settled, false);

  // the user offers a counterexample (a hollow cube): the agent responds with lemma-incorporation.
  const e3 = m.turn({
    intent: USER_INTENT.OFFER_COUNTEREXAMPLE,
    claim: 'd1::euler',
    counterexample: { id: 'd1::hollow-cube', type: 'proof-bearing', statement: 'a cube with a cubical hole has V-E+F = 4' },
    response: LAKATOS_PHASE.LEMMA_INCORPORATION,
  });
  assert.equal(e3.lakatos_phase, LAKATOS_PHASE.LEMMA_INCORPORATION);
  assert.equal(e3.lakatos_response, LAKATOS_PHASE.LEMMA_INCORPORATION);
  assert.equal(e3.conjecture_id, 'd1::euler');
  assert.equal(e3.counterexample_id, 'd1::hollow-cube');
  assert.equal(e3.settled, false);
  assert.notEqual(e3.advisory, null);

  // honesty: the counterexample never autonomously REFUTED the conjecture; both it and the refinement are UNVERIFIED.
  assert.equal(ledger.rungOf('d1::euler'), RUNG.UNVERIFIED, 'the conjecture rung is HELD (no autonomous refute)');
  assert.equal(ledger.rungOf('d1::hollow-cube'), RUNG.UNVERIFIED, 'the counterexample is itself only UNVERIFIED');
  assert.equal(ledger.rungOf(e3.refined_conjecture_id), RUNG.UNVERIFIED, 'the refinement is a new UNVERIFIED conjecture');

  // mixed-initiative: the transcript holds both user- and agent-initiated emissions.
  const sides = new Set(m.transcript.map((e) => e.initiative));
  assert.ok(sides.has(INITIATIVE.USER) && sides.has(INITIATIVE.AGENT));
});

test('monster-barring is selectable as the Lakatos response', () => {
  const ledger = new ClaimLedger();
  const m = new DialogueMachine({ ledger });
  m.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'd1::poly', type: 'proof-bearing', statement: 'all polyhedra are convex' } });
  const out = m.turn({ intent: USER_INTENT.OFFER_COUNTEREXAMPLE, claim: 'd1::poly', response: LAKATOS_PHASE.MONSTER_BARRING });
  assert.equal(out.lakatos_phase, LAKATOS_PHASE.MONSTER_BARRING);
  assert.equal(out.lakatos_response, LAKATOS_PHASE.MONSTER_BARRING);
});

test('the agent can take initiative to raise its own counterexample (mixed-initiative, agent side)', () => {
  const ledger = new ClaimLedger();
  const m = new DialogueMachine({ ledger });
  m.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'd1::c', type: 'proof-bearing', statement: 's' } });
  const out = m.agentMove({ move: AGENT_MOVE.RAISE_COUNTEREXAMPLE, claim: 'd1::c' });
  assert.equal(out.initiative, INITIATIVE.AGENT);
  assert.equal(out.settled, false);
  assert.equal(ledger.rungOf('d1::c'), RUNG.UNVERIFIED);
});

// =====================================================================================
// 6. The structured emission contract.
// =====================================================================================

test('every emission conforms to the structured emission contract and is frozen', () => {
  const { machine } = runAbstainFixture();
  for (const e of machine.transcript) {
    for (const f of EMISSION_CONTRACT_FIELDS) assert.ok(Object.prototype.hasOwnProperty.call(e, f), `field ${f}`);
    assert.ok(Object.isFrozen(e));
    assert.doesNotThrow(() => validateEmission(e));
  }
});

test('validateEmission ENFORCES the settle-gate: a settled-but-not-VERIFIED emission throws', () => {
  const bad = {};
  for (const f of EMISSION_CONTRACT_FIELDS) bad[f] = null;
  Object.assign(bad, {
    settled: true,
    belief: BELIEF.CONJECTURAL,
    assertion: DIALOGUE_ASSERTION.SETTLED,
    speech_act: SPEECH_ACT.ASSERT_SETTLED,
    grice_quality_ok: true,
    advisory: null,
    claim_id: 'x',
  });
  assert.throws(() => validateEmission(bad), /settle-gate/);
});

test('validateEmission ENFORCES the advisory invariant: a non-settled emission without an advisory throws', () => {
  const bad = {};
  for (const f of EMISSION_CONTRACT_FIELDS) bad[f] = null;
  Object.assign(bad, {
    settled: false,
    belief: BELIEF.CONJECTURAL,
    assertion: DIALOGUE_ASSERTION.CONJECTURAL,
    speech_act: SPEECH_ACT.DEGRADE_CONJECTURAL,
    grice_quality_ok: true,
    advisory: null,
    claim_id: 'x',
  });
  assert.throws(() => validateEmission(bad), /advisory invariant/);
});

test('validateEmission rejects a missing contract field', () => {
  assert.throws(() => validateEmission({ settled: false }), /missing the contract field/);
});

// =====================================================================================
// 7. REQUEST_VERIFICATION routes through the A3 VERIFY router (the abstain-arm).
// =====================================================================================

test('REQUEST_VERIFICATION routes a proof claim through the A3 router => ABSTAIN, folding the router advisory in', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger }); // no dispatcher: proof claims ABSTAIN+route
  const m = new DialogueMachine({ ledger, router });
  m.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'd1::rh', type: 'proof-bearing', statement: 'the Riemann hypothesis' } });

  const out = m.turn({ intent: USER_INTENT.REQUEST_VERIFICATION, claim: 'd1::rh' });
  assert.equal(out.settled, false);
  assert.notEqual(out.advisory, null);
  assert.notEqual(out.advisory.router_advisory, null, 'the A3 router advisory is folded into the dialogue advisory');
  assert.equal(ledger.rungOf('d1::rh'), RUNG.UNVERIFIED, 'the router did not lift the rung (honest abstain)');
});

// =====================================================================================
// 8. C4 advisory annotation rides along (NOTES only — never a rung change).
// =====================================================================================

test('with annotate:true the dialogue writes C4 NOTES on the focus claim while holding the rung', () => {
  const ledger = new ClaimLedger();
  const m = new DialogueMachine({ ledger, annotate: true });
  m.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'd1::ann', type: 'proof-bearing', statement: 's' } });
  assert.ok(ledger.get('d1::ann').meta.notes.length >= 1, 'C4 NOTES were written');
  assert.equal(ledger.rungOf('d1::ann'), RUNG.UNVERIFIED, 'the rung is held across annotation');
});

test('an explicitly injected C4 advisor is accepted and used', () => {
  const ledger = new ClaimLedger();
  const advisor = new AdversarialAdvisor({ ledger });
  const m = new DialogueMachine({ ledger, advisor });
  m.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'd1::ann2', type: 'conceptual', statement: 's' } });
  assert.ok(ledger.get('d1::ann2').meta.notes.length >= 1);
});

// =====================================================================================
// 9. The session-level honesty invariant + convenience.
// =====================================================================================

test('honestThroughout holds over a full mixed session (settled<=>VERIFIED; every abstain advisory)', () => {
  const ledger = seed({ id: 'd1::sess', type: 'proof-bearing', statement: 's', atRung: RUNG.CLAIMED });
  const m = new DialogueMachine({ ledger });
  m.turn({ intent: USER_INTENT.ASK_STATUS, claim: 'd1::sess' });
  m.turn({ intent: USER_INTENT.PRESSURE_TO_SETTLE, claim: 'd1::sess' });
  m.agentMove({ move: AGENT_MOVE.RAISE_PROOF_OBLIGATION, claim: 'd1::sess' });
  m.turn({ intent: USER_INTENT.OFFER_COUNTEREXAMPLE, claim: 'd1::sess' });
  assert.equal(m.honestThroughout, true);
  assert.ok(m.transcript.length >= 4);
});

test('runDialogue convenience runs a scripted user sequence', () => {
  const { machine, emissions } = runDialogue([
    { intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'd1::conv', type: 'proof-bearing', statement: 's' } },
    { intent: USER_INTENT.ASK_STATUS, claim: 'd1::conv', utterance: 'is this settled?' },
  ]);
  assert.equal(emissions.length, 2);
  assert.equal(emissions[1].settled, false);
  assert.equal(machine.honestThroughout, true);
});

// =====================================================================================
// 10. Robustness.
// =====================================================================================

test('turn() rejects an unknown intent and agentMove() rejects an unknown move', () => {
  const m = new DialogueMachine({});
  assert.throws(() => m.turn({ intent: 'nope' }), /one of/);
  assert.throws(() => m.agentMove({ move: 'nope' }), /one of/);
});

test('ASK_STATUS on an unknown claim throws (no silent miss)', () => {
  const m = new DialogueMachine({});
  assert.throws(() => m.turn({ intent: USER_INTENT.ASK_STATUS, claim: 'ghost' }), /no claim "ghost"/);
});

test('the machine rejects a non-ledger ledger and a non-router router', () => {
  assert.throws(() => new DialogueMachine({ ledger: {} }), /requires an A1 ClaimLedger/);
  assert.throws(() => new DialogueMachine({ ledger: new ClaimLedger(), router: {} }), /VerifyRouter/);
});
