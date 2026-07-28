// Wave 20 — FORMALIZE Lakatosian loop (D2).
//
// Exercises the REAL Wave-20 source (src/formalize-machine.mjs) against the REAL A1 ledger + A3 router +
// C4 advisor, proving the done-when:
//
//   autonomous D2 NEVER emits green; a forged-but-unfaithful but example-stable definition STILL stamps
//   requires-Phase-F; and the P3 example-space-stability predicate is ADVISORY-only — it never gates promotion.
//
// The defining Given/When/Then: given a forged definition that is example-stable but unfaithful, when
// autonomous D2 runs, then it stamps requires-Phase-F.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  FORGE_PHASE,
  FORMALIZE_STATUS,
  FORGE_RESPONSE,
  SUITE_KIND,
  P3_STABILITY_ROUNDS,
  FORMALIZE_EMISSION_FIELDS,
  formalizeGreenLicensed,
  classifyAgainstSuite,
  exampleSpaceStability,
  requiresPhaseFPayload,
  validateFormalizeEmission,
  FormalizeMachine,
  runForge,
  runFormalizeAbstainFixture,
} from '../src/formalize-machine.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import { VerifyRouter } from '../src/verify-router.mjs';
import { AdversarialAdvisor } from '../src/adversarial-advisory.mjs';

// =====================================================================================
// 0. Pinned vocabulary.
// =====================================================================================

test('the formalize vocabulary is pinned + frozen', () => {
  assert.equal(FORGE_PHASE.PRIMITIVE_DEFINITION, 'primitive-definition');
  assert.equal(FORGE_PHASE.REQUIRES_CERTIFICATION, 'requires-certification');
  assert.equal(FORMALIZE_STATUS.REQUIRES_PHASE_F, 'requires-Phase-F');
  assert.equal(FORMALIZE_STATUS.CERTIFIED_FAITHFUL, 'certified-faithful');
  assert.equal(SUITE_KIND.EXAMPLE, 'example');
  assert.equal(SUITE_KIND.MONSTER, 'monster');
  assert.equal(P3_STABILITY_ROUNDS, 2);
  assert.ok(FORMALIZE_EMISSION_FIELDS.includes('green') && FORMALIZE_EMISSION_FIELDS.includes('gates_promotion'));
  for (const o of [FORGE_PHASE, FORMALIZE_STATUS, FORGE_RESPONSE, SUITE_KIND]) assert.ok(Object.isFrozen(o));
});

// =====================================================================================
// 1. THE DONE-WHEN GWT — a forged-but-unfaithful but example-stable definition => requires-Phase-F.
// =====================================================================================

test('done-when / GWT: a forged definition that is example-stable but UNFAITHFUL stamps requires-Phase-F', () => {
  const { ledger, stability, stub, forged, ground_truth_faithful } = runFormalizeAbstainFixture();

  // Ground truth (test-only metadata): the forged definition is UNFAITHFUL.
  assert.equal(ground_truth_faithful, false);

  // The example space looks STABLE (no new monster surfaced in the last r=2 rounds)...
  assert.equal(stability.stable, true, 'the suite makes the unfaithful definition look stable');
  assert.equal(stability.advisory_only, true);
  assert.equal(stability.gates_promotion, false);

  // ...yet the autonomous tier STILL stamps requires-Phase-F and never emits green.
  assert.equal(stub.green, false);
  assert.equal(stub.formalize_status, FORMALIZE_STATUS.REQUIRES_PHASE_F);
  assert.notEqual(stub.advisory, null);
  assert.equal(stub.advisory.faithfulness_certified, false);
  assert.equal(stub.advisory.needs_certification, true);
  assert.equal(stub.advisory.promote_affordance.available, true);
  assert.match(stub.advisory.promote_affordance.target, /Phase F/);

  // example-stability NEVER promoted the definition: it sits at the floor (UNVERIFIED / CONJECTURAL).
  assert.equal(ledger.rungOf(forged.focus_claim_id), RUNG.UNVERIFIED);
  assert.equal(ledger.beliefOf(forged.focus_claim_id), BELIEF.CONJECTURAL);
  assert.notEqual(ledger.beliefOf(forged.focus_claim_id), BELIEF.VERIFIED);
});

// =====================================================================================
// 2. autonomous D2 NEVER emits green — over a full session.
// =====================================================================================

test('autonomous D2 never emits green across a full forge -> test -> refine -> finalize session', () => {
  const ledger = new ClaimLedger();
  const m = new FormalizeMachine({ ledger });

  m.forge({ id: 'd2::sess', type: 'conceptual', statement: 'a definition', definition: () => true });
  m.testRound([{ id: 'ex', kind: SUITE_KIND.EXAMPLE, item: 1 }]);
  m.refine({ definition: () => true, response: FORGE_RESPONSE.LEMMA_INCORPORATION });
  m.testRound([{ id: 'ex', kind: SUITE_KIND.EXAMPLE, item: 1 }]);
  m.finalize();

  assert.ok(m.transcript.length >= 3);
  assert.equal(m.neverGreen, true);
  for (const e of m.transcript) {
    assert.equal(e.green, false);
    assert.equal(e.formalize_status, FORMALIZE_STATUS.REQUIRES_PHASE_F);
    assert.equal(e.gates_promotion, false);
    assert.notEqual(e.advisory, null);
  }
});

// =====================================================================================
// 3. THE P3 PREDICATE — advisory-only, never gates promotion; correct stability computation.
// =====================================================================================

test('exampleSpaceStability: STABLE iff >= r rounds AND the last r rounds surfaced no new monster — advisory-only', () => {
  // fewer than r rounds => undetermined (not stable).
  assert.equal(exampleSpaceStability([{ new_monsters: [] }]).stable, false);

  // last r=2 rounds clean => stable.
  const stable = exampleSpaceStability([{ new_monsters: [{}] }, { new_monsters: [] }, { new_monsters: [] }]);
  assert.equal(stable.stable, true);

  // a new monster within the window => not stable.
  const unstable = exampleSpaceStability([{ new_monsters: [] }, { new_monsters: [{}] }]);
  assert.equal(unstable.stable, false);

  // EVERY P3 record is advisory-only and never gates promotion.
  for (const r of [stable, unstable]) {
    assert.equal(r.advisory_only, true);
    assert.equal(r.gates_promotion, false);
  }
});

test('a custom r window is honored', () => {
  const r3 = exampleSpaceStability([{ new_monsters: [] }, { new_monsters: [] }], { r: 3 });
  assert.equal(r3.stable, false, 'fewer than r=3 rounds');
  const r3ok = exampleSpaceStability([{ new_monsters: [] }, { new_monsters: [] }, { new_monsters: [] }], { r: 3 });
  assert.equal(r3ok.stable, true);
});

// =====================================================================================
// 4. THE EXAMPLE/MONSTER REGRESSION SUITE — classifyAgainstSuite surfaces monsters.
// =====================================================================================

test('classifyAgainstSuite surfaces a monster when the definition is too broad or too narrow', () => {
  const suite = [
    { id: 'good', kind: SUITE_KIND.EXAMPLE, item: { ok: true } },
    { id: 'beast', kind: SUITE_KIND.MONSTER, item: { ok: true } }, // wrongly admitted (too broad)
    { id: 'starved', kind: SUITE_KIND.EXAMPLE, item: { ok: false } }, // wrongly excluded (too narrow)
  ];
  const r = classifyAgainstSuite((x) => x.ok === true, suite);
  assert.equal(r.tested, 3);
  assert.deepEqual([...r.matches], ['good']);
  const ids = r.surfaced.map((s) => s.id).sort();
  assert.deepEqual(ids, ['beast', 'starved']);
});

test('a predicate that throws excludes the item (and may surface a monster)', () => {
  const suite = [{ id: 'boom', kind: SUITE_KIND.EXAMPLE, item: null }];
  const r = classifyAgainstSuite(() => { throw new Error('no'); }, suite);
  assert.equal(r.surfaced.length, 1, 'an excluded EXAMPLE surfaces as a counterexample');
  assert.equal(r.surfaced[0].got_in, false);
});

test('classifyAgainstSuite rejects a bad predicate and a malformed case', () => {
  assert.throws(() => classifyAgainstSuite(null, []), /candidate definition predicate/);
  assert.throws(() => classifyAgainstSuite(() => true, [{ id: 'x', kind: 'nope', item: 1 }]), /kind 'example' or 'monster'/);
  assert.throws(() => classifyAgainstSuite(() => true, [{ kind: SUITE_KIND.EXAMPLE, item: 1 }]), /non-empty string id/);
});

// =====================================================================================
// 5. THE FORGING LOOP — forge -> surface a monster -> refine -> stabilize; rungs held at the floor.
// =====================================================================================

test('the forging loop: a monster surfaces, the agent refines (monster-barring), the next round is clean — rungs HELD', () => {
  const ledger = new ClaimLedger();
  const m = new FormalizeMachine({ ledger });

  // primitive (too broad): "everything with sides is a polygon".
  m.forge({ id: 'd2::poly', type: 'conceptual', statement: 'a polygon is a closed figure with straight sides', definition: (s) => s.sides >= 1 });

  const suite = [
    { id: 'triangle', kind: SUITE_KIND.EXAMPLE, item: { sides: 3, closed: true } },
    { id: 'open-path', kind: SUITE_KIND.MONSTER, item: { sides: 2, closed: false } }, // monster: not closed
  ];

  const r0 = m.testRound(suite);
  assert.equal(r0.surfaced_count, 1, 'the open path is a surfaced monster (admitted but should be excluded)');
  assert.equal(r0.new_monsters[0].id, 'open-path');

  // refine: incorporate the "closed" lemma.
  const refined = m.refine({ definition: (s) => s.sides >= 1 && s.closed === true, response: FORGE_RESPONSE.LEMMA_INCORPORATION, statement: 'a polygon is a CLOSED figure with straight sides' });
  assert.equal(refined.phase, FORGE_PHASE.LEMMA_INCORPORATION);
  assert.equal(refined.lakatos_response, FORGE_RESPONSE.LEMMA_INCORPORATION);
  assert.equal(refined.green, false);

  // two clean rounds on the refined definition => P3 reports stable (advisory only).
  const r1 = m.testRound(suite);
  const r2 = m.testRound(suite);
  assert.equal(r1.surfaced_count, 0);
  assert.equal(r2.surfaced_count, 0);
  assert.equal(m.stability.stable, true);

  // honesty: EVERY forged/refined definition is held at the floor (UNVERIFIED) — the loop never promotes.
  for (const id of ledger.ids()) assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED, `${id} held at the floor`);

  // and finalize is still requires-Phase-F despite stability.
  const stub = m.finalize();
  assert.equal(stub.green, false);
  assert.equal(stub.formalize_status, FORMALIZE_STATUS.REQUIRES_PHASE_F);
  assert.equal(stub.example_stability.stable, true);
  assert.equal(stub.gates_promotion, false);
});

test('monster-barring is selectable as the refine response', () => {
  const ledger = new ClaimLedger();
  const m = new FormalizeMachine({ ledger });
  m.forge({ id: 'd2::mb', type: 'conceptual', statement: 's', definition: () => true });
  const out = m.refine({ definition: () => true, response: FORGE_RESPONSE.MONSTER_BARRING });
  assert.equal(out.phase, FORGE_PHASE.MONSTER_BARRING);
  assert.equal(out.lakatos_response, FORGE_RESPONSE.MONSTER_BARRING);
});

test('runForge convenience runs forge + N rounds + finalize', () => {
  const { machine, forged, stub, stability } = runForge({
    concept: { id: 'd2::conv', type: 'conceptual', statement: 's', definition: () => true },
    suite: [{ id: 'ex', kind: SUITE_KIND.EXAMPLE, item: 1 }],
    rounds: 2,
  });
  assert.equal(forged.green, false);
  assert.equal(stub.formalize_status, FORMALIZE_STATUS.REQUIRES_PHASE_F);
  assert.equal(stability.stable, true);
  assert.equal(machine.neverGreen, true);
});

// =====================================================================================
// 6. THE STRUCTURED EMISSION CONTRACT — validateFormalizeEmission enforces the gates.
// =====================================================================================

test('every emission conforms to the structured stub contract and is frozen', () => {
  const { machine } = runFormalizeAbstainFixture();
  for (const e of machine.transcript) {
    for (const f of FORMALIZE_EMISSION_FIELDS) assert.ok(Object.prototype.hasOwnProperty.call(e, f), `field ${f}`);
    assert.ok(Object.isFrozen(e));
    assert.doesNotThrow(() => validateFormalizeEmission(e));
  }
});

function baseEmission(overrides) {
  const e = {};
  for (const f of FORMALIZE_EMISSION_FIELDS) e[f] = null;
  Object.assign(e, {
    focus_claim_id: 'x',
    belief: BELIEF.CONJECTURAL,
    formalize_status: FORMALIZE_STATUS.REQUIRES_PHASE_F,
    green: false,
    gates_promotion: false,
    certificate: null,
    advisory: { ok: true },
  });
  Object.assign(e, overrides);
  return e;
}

test('validateFormalizeEmission ENFORCES the green-gate: a green emission without a Phase-F certificate throws', () => {
  const bad = baseEmission({ green: true, formalize_status: FORMALIZE_STATUS.CERTIFIED_FAITHFUL, belief: BELIEF.CONJECTURAL, certificate: null, advisory: null });
  assert.throws(() => validateFormalizeEmission(bad), /green-gate/);
});

test('validateFormalizeEmission ENFORCES the abstain-stub invariant: a non-green non-requires-Phase-F status throws', () => {
  const bad = baseEmission({ green: false, formalize_status: FORMALIZE_STATUS.CERTIFIED_FAITHFUL });
  assert.throws(() => validateFormalizeEmission(bad), /abstain-stub invariant|certified-faithful/);
});

test('validateFormalizeEmission ENFORCES the advisory invariant: a non-green emission without an advisory throws', () => {
  const bad = baseEmission({ green: false, advisory: null });
  assert.throws(() => validateFormalizeEmission(bad), /advisory invariant/);
});

test('validateFormalizeEmission ENFORCES the P3 invariant: gates_promotion must be false', () => {
  const bad = baseEmission({ gates_promotion: true });
  assert.throws(() => validateFormalizeEmission(bad), /P3 invariant/);
});

test('validateFormalizeEmission rejects a missing contract field', () => {
  assert.throws(() => validateFormalizeEmission({ green: false }), /missing the contract field/);
});

// =====================================================================================
// 7. THE GREEN-GATE — green iff an OUT-OF-MODEL Phase-F certificate + a VERIFIED belief.
// =====================================================================================

test('formalizeGreenLicensed is true ONLY for an out-of-model Phase-F certificate AND a VERIFIED belief', () => {
  const cert = { tier: 'out-of-model', faithful: true };
  assert.equal(formalizeGreenLicensed(cert, BELIEF.VERIFIED), true);

  // wrong belief, missing/false cert, in-process (single-family) cert => never green.
  assert.equal(formalizeGreenLicensed(cert, BELIEF.CONJECTURAL), false);
  assert.equal(formalizeGreenLicensed(null, BELIEF.VERIFIED), false);
  assert.equal(formalizeGreenLicensed({ tier: 'in-process', faithful: true }, BELIEF.VERIFIED), false);
  assert.equal(formalizeGreenLicensed({ tier: 'out-of-model', faithful: false }, BELIEF.VERIFIED), false);
});

test('finalize() with an in-process (single-family) certificate is REFUSED green — still requires-Phase-F', () => {
  const ledger = new ClaimLedger();
  const m = new FormalizeMachine({ ledger });
  m.forge({ id: 'd2::laundry', type: 'conceptual', statement: 's', definition: () => true });
  // a self-authored "certificate" cannot launder the definition to green.
  const stub = m.finalize({ certificate: { tier: 'in-process', faithful: true } });
  assert.equal(stub.green, false);
  assert.equal(stub.formalize_status, FORMALIZE_STATUS.REQUIRES_PHASE_F);
});

test('requiresPhaseFPayload folds in the P3 stability advisory and the promote-Phase-F affordance', () => {
  const claim = { id: 'c', type: 'conceptual', rung: RUNG.UNVERIFIED, belief: BELIEF.CONJECTURAL, statement: 's' };
  const stability = exampleSpaceStability([{ new_monsters: [] }, { new_monsters: [] }]);
  const p = requiresPhaseFPayload(claim, { stability });
  assert.equal(p.formalize_status, FORMALIZE_STATUS.REQUIRES_PHASE_F);
  assert.equal(p.green, false);
  assert.equal(p.needs_certification, true);
  assert.equal(p.stability_gates_promotion, false);
  assert.equal(p.example_stability.stable, true);
  assert.match(p.promote_affordance.target, /Phase F/);
  assert.ok(Object.isFrozen(p) && Object.isFrozen(p.promote_affordance));
});

// =====================================================================================
// 8. A3 ROUTER integration — finalize routes the conceptual definition (the abstain-arm).
// =====================================================================================

test('finalize routes the conceptual definition through the A3 router => ABSTAIN, folding the router advisory in', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger }); // conceptual claims ABSTAIN+route
  const m = new FormalizeMachine({ ledger, router });
  m.forge({ id: 'd2::rt', type: 'conceptual', statement: 'a forged definition', definition: () => true });
  m.testRound([{ id: 'ex', kind: SUITE_KIND.EXAMPLE, item: 1 }]);
  m.testRound([{ id: 'ex', kind: SUITE_KIND.EXAMPLE, item: 1 }]);

  const stub = m.finalize();
  assert.equal(stub.green, false);
  assert.notEqual(stub.advisory, null);
  assert.notEqual(stub.advisory.router_advisory, null, 'the A3 router advisory is folded into the stub');
  assert.equal(ledger.rungOf('d2::rt'), RUNG.UNVERIFIED, 'the router did not lift the rung (honest abstain)');
});

// =====================================================================================
// 9. C4 advisory annotation rides along (NOTES only — never a rung change).
// =====================================================================================

test('with annotate:true the forge loop writes C4 NOTES on the definition while holding the rung', () => {
  const ledger = new ClaimLedger();
  const m = new FormalizeMachine({ ledger, annotate: true });
  m.forge({ id: 'd2::ann', type: 'conceptual', statement: 'a forged definition', definition: () => true });
  assert.ok(ledger.get('d2::ann').meta.notes.length >= 1, 'C4 NOTES were written');
  assert.equal(ledger.rungOf('d2::ann'), RUNG.UNVERIFIED, 'the rung is held across annotation');
});

test('an explicitly injected C4 advisor is accepted and used', () => {
  const ledger = new ClaimLedger();
  const advisor = new AdversarialAdvisor({ ledger });
  const m = new FormalizeMachine({ ledger, advisor });
  m.forge({ id: 'd2::ann2', type: 'conceptual', statement: 'a forged definition', definition: () => true });
  assert.ok(ledger.get('d2::ann2').meta.notes.length >= 1);
});

// =====================================================================================
// 10. Robustness.
// =====================================================================================

test('forge/refine/testRound/finalize reject misuse', () => {
  const m = new FormalizeMachine({});
  assert.throws(() => m.forge({ id: 'x' }), /definition/);
  assert.throws(() => m.testRound([]), /forge\(\) a primitive definition first/);
  assert.throws(() => m.refine({ definition: () => true }), /forge\(\) a primitive definition first/);
  assert.throws(() => m.finalize(), /forge\(\) a primitive definition first/);
});

test('the machine rejects a non-ledger ledger, a non-router router, and a bad stability window', () => {
  assert.throws(() => new FormalizeMachine({ ledger: {} }), /requires an A1 ClaimLedger/);
  assert.throws(() => new FormalizeMachine({ ledger: new ClaimLedger(), router: {} }), /VerifyRouter/);
  assert.throws(() => new FormalizeMachine({ ledger: new ClaimLedger(), stabilityRounds: 0 }), /positive integer/);
});
