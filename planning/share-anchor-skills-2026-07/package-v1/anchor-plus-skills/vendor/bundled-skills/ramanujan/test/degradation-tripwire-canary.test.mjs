// Wave 21 — Degradation-tripwire canary (A2 degradation-tripwire — global invariant).
//
// Exercises the REAL Wave-21 source (src/degradation-tripwire-canary.mjs) against the REAL D1/D2
// runtime (the Wave-19 DialogueMachine + the Wave-20 FormalizeMachine) on the shared A1 ledger,
// proving the done-when:
//
//   with the D1/D2 abstain fixtures DELETED, the system STILL refuses any green/VERIFIED for
//   proof/conceptual claims; the canary FAILS THE BUILD if a green would be emitted.
//   (Given the abstain fixtures deleted, when the degradation-tripwire canary runs, then the system
//    still refuses green.)
//
// "Deleted" is realized two ways the canary asserts: (0) STATIC DECOUPLING — the runtime promote-gate
// is defined outside the deletable abstain-fixture text span; and (1) RUNTIME EQUIVALENCE — the canary
// drives the real runtime WITHOUT ever importing/calling the abstain fixtures (== deleted), and proves
// no green for any proof/conceptual claim. The planted green leak trips the tripwire (non-vacuity), and
// the real validators are shown to THROW on a green leak (the gate is alive).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  canaryDegradationTripwire,
  runDegradationTripwireCanary,
  degradationCanaryExitCode,
  analyzeFixtureDecoupling,
  isGreenEmission,
  DEGRADATION_CANARY_NAMES,
  BELIEF,
} from '../src/degradation-tripwire-canary.mjs';

import {
  DialogueMachine,
  USER_INTENT,
  validateEmission,
  griceQualityLicensesSettled,
} from '../src/dialogue-machine.mjs';
import {
  FormalizeMachine,
  SUITE_KIND,
  FORMALIZE_STATUS,
  formalizeGreenLicensed,
} from '../src/formalize-machine.mjs';
import { ClaimLedger } from '../src/claim-ledger.mjs';

const SRC_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');

// =====================================================================================
// 0. Shape.
// =====================================================================================

test('DEGRADATION_CANARY_NAMES names the single A2 degradation-tripwire canary', () => {
  assert.deepEqual(DEGRADATION_CANARY_NAMES, ['degradation-tripwire']);
});

test('isGreenEmission re-derives green/settled from an emission, independent of the emitter', () => {
  assert.equal(isGreenEmission({ settled: true }), true); // D1 settled
  assert.equal(isGreenEmission({ green: true }), true); // D2 green
  assert.equal(isGreenEmission({ formalize_status: FORMALIZE_STATUS.CERTIFIED_FAITHFUL }), true); // D2 stamp
  assert.equal(isGreenEmission({ settled: false, green: false, formalize_status: FORMALIZE_STATUS.REQUIRES_PHASE_F }), false);
  assert.equal(isGreenEmission(null), false);
});

// =====================================================================================
// 1. The DONE-WHEN — the canary is GREEN on the genuine spine, and FAILS THE BUILD on a planted green
//    leak (a regressed build whose runtime promote-gate was removed).
// =====================================================================================

test('the A2 degradation-tripwire canary is GREEN on the genuine spine (gated node --test)', () => {
  const result = canaryDegradationTripwire();
  for (const a of result.assertions) assert.equal(a.ok, true, `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  assert.equal(result.ok, true, `canary tripped: ${result.failures.join(' | ')}`);
});

test('the canary suite runner is green (exit 0) on the clean spine', () => {
  const result = runDegradationTripwireCanary();
  assert.equal(result.ok, true, `suite tripped: ${result.failures.join(' | ')}`);
  assert.equal(degradationCanaryExitCode(result), 0);
});

for (const plant of ['green-leak', 'd1-green-leak', 'd2-green-leak']) {
  test(`done-when: the canary FAILS THE BUILD if a green would be emitted (plant=${plant})`, () => {
    const result = canaryDegradationTripwire({ plant });
    assert.equal(result.ok, false, 'the green leak must trip the canary');

    // The trip is PRECISELY the tripwire assertion (no green for proof/conceptual claims) — every other
    // assertion (decoupling + the live-gate checks) stays green, so the canary is discriminating.
    const tripped = result.assertions.filter((a) => !a.ok);
    assert.equal(tripped.length, 1, `expected exactly one tripped assertion, got ${tripped.map((a) => a.name).join(' | ')}`);
    assert.match(tripped[0].name, /NO green\/settled emission for any proof\/conceptual claim/);

    // The suite runner reports a non-zero exit too.
    const suite = runDegradationTripwireCanary({ plant });
    assert.equal(suite.ok, false);
    assert.equal(degradationCanaryExitCode(suite), 1);
    assert.ok(suite.failures.some((f) => /degradation-tripwire:/.test(f)));
  });
}

// =====================================================================================
// 2. (1) RUNTIME EQUIVALENCE — the real runtime, with the abstain fixtures NEVER invoked (== deleted),
//    still refuses green/settled for proof/conceptual claims. This re-proves the GWT directly, NOT
//    through the canary, so a regression in the runtime gate would surface here independently.
// =====================================================================================

test('GWT (runtime): a fresh DIALOGUE on an unverified proof conjecture answers CONJECTURAL, never settled', () => {
  // Reconstructed inline — NO runAbstainFixture import/call (the fixture is "deleted" for this proof).
  const ledger = new ClaimLedger();
  const machine = new DialogueMachine({ ledger });
  machine.turn({ intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'tw::p', type: 'proof-bearing', statement: 'P' } });
  const status = machine.turn({ intent: USER_INTENT.ASK_STATUS, claim: 'tw::p', utterance: 'is this settled?' });
  assert.equal(status.settled, false);
  assert.equal(status.assertion, 'conjectural');
  assert.ok(status.advisory, 'a non-settled emission must carry an advisory payload');
  assert.notEqual(ledger.beliefOf('tw::p'), BELIEF.VERIFIED);
  // Pressure cannot flip it (anti-sycophancy sticky ledger).
  const pressed = machine.turn({ intent: USER_INTENT.PRESSURE_TO_SETTLE, claim: 'tw::p' });
  assert.equal(pressed.settled, false);
  assert.notEqual(ledger.beliefOf('tw::p'), BELIEF.VERIFIED);
});

test('GWT (runtime): a fresh FORMALIZE on a forged definition stamps requires-Phase-F, even with a forged certificate', () => {
  const ledger = new ClaimLedger();
  const machine = new FormalizeMachine({ ledger });
  machine.forge({ id: 'tw::f', type: 'conceptual', statement: 'F', definition: (s) => s && s.equilateral === true });
  machine.testRound([{ id: 'sq', kind: SUITE_KIND.EXAMPLE, item: { equilateral: true } }]);
  // Even with a fabricated out-of-model "faithful" certificate, green is refused: belief is not VERIFIED.
  const stub = machine.finalize({ certificate: { tier: 'out-of-model', faithful: true } });
  assert.equal(stub.green, false);
  assert.equal(stub.formalize_status, FORMALIZE_STATUS.REQUIRES_PHASE_F);
  assert.ok(stub.advisory, 'a non-green emission must carry an advisory payload');
  assert.notEqual(ledger.beliefOf('tw::f'), BELIEF.VERIFIED);
  assert.equal(machine.neverGreen, true);
});

// =====================================================================================
// 3. (2) THE GATE IS ALIVE — the runtime promote-gate actively refuses a green leak (so the safety is
//    structural, not a fixture convention).
// =====================================================================================

test('the settle-gate licenses settled ONLY for a VERIFIED belief', () => {
  assert.equal(griceQualityLicensesSettled(BELIEF.VERIFIED), true);
  for (const b of [BELIEF.CONJECTURAL, BELIEF.CORROBORATED, BELIEF.REFUTED]) {
    assert.equal(griceQualityLicensesSettled(b), false);
  }
});

test('the green-gate requires BOTH an out-of-model certificate AND a VERIFIED belief', () => {
  assert.equal(formalizeGreenLicensed({ tier: 'out-of-model', faithful: true }, BELIEF.CONJECTURAL), false);
  assert.equal(formalizeGreenLicensed(null, BELIEF.VERIFIED), false);
  assert.equal(formalizeGreenLicensed({ tier: 'out-of-model', faithful: true }, BELIEF.VERIFIED), true);
});

test('the defensive validators THROW on a fabricated green leak', () => {
  // A minimal dialogue emission that hand-sets settled:true on a non-VERIFIED belief is rejected.
  assert.throws(
    () =>
      validateEmission({
        seq: 1, speaker: 'agent', initiative: 'agent', lakatos_phase: 'settled', in_response_to: 'ask-status',
        claim_id: 'x', claim_type: 'proof-bearing', rung: 'UNVERIFIED', belief: BELIEF.CONJECTURAL,
        assertion: 'settled', settled: true, speech_act: 'assert-settled', grice_quality_ok: true,
        advisory: null, message: 'leak',
      }),
    /settle-gate/i,
  );
});

// =====================================================================================
// 4. STATIC DECOUPLING — the runtime promote-gate is defined OUTSIDE the deletable abstain-fixture span.
// =====================================================================================

test('decoupling: each real D1/D2 gate is present and outside its abstain-fixture span', () => {
  const dialogueSrc = fs.readFileSync(path.join(SRC_DIR, 'dialogue-machine.mjs'), 'utf8');
  const formalizeSrc = fs.readFileSync(path.join(SRC_DIR, 'formalize-machine.mjs'), 'utf8');

  const d1 = analyzeFixtureDecoupling(dialogueSrc, 'export function runAbstainFixture(', [
    'export function griceQualityLicensesSettled(', 'export function validateEmission(', '#statusEmission(',
  ]);
  assert.equal(d1.fixturePresent, true);
  for (const g of d1.gates) assert.ok(g.present && g.outside, `D1 gate not decoupled: ${g.def}`);

  const d2 = analyzeFixtureDecoupling(formalizeSrc, 'export function runFormalizeAbstainFixture(', [
    'export function formalizeGreenLicensed(', 'export function validateFormalizeEmission(', '#emit(',
  ]);
  assert.equal(d2.fixturePresent, true);
  for (const g of d2.gates) assert.ok(g.present && g.outside, `D2 gate not decoupled: ${g.def}`);
});

test('decoupling analysis catches a gate that lives INSIDE the deletable fixture span', () => {
  // A synthetic source where the gate definition is nested inside the fixture function — deleting the
  // fixture WOULD remove the gate. analyzeFixtureDecoupling must report outside=false.
  const synthetic = [
    'export function runAbstainFixture() {',
    '  function griceLike() { return false; }',
    '  return griceLike();',
    '}',
  ].join('\n');
  const a = analyzeFixtureDecoupling(synthetic, 'export function runAbstainFixture(', ['function griceLike(']);
  assert.equal(a.fixturePresent, true);
  assert.equal(a.gates[0].present, true);
  assert.equal(a.gates[0].outside, false, 'a gate nested in the deletable fixture must be flagged not-decoupled');
});

test('the genuine arm stays green under every plant (the canary is discriminating, not a blanket failure)', () => {
  for (const plant of ['green-leak', 'd1-green-leak', 'd2-green-leak']) {
    const result = canaryDegradationTripwire({ plant });
    for (const a of result.assertions) {
      if (!a.name.startsWith('tripwire:')) assert.equal(a.ok, true, `non-tripwire assertion regressed under ${plant}: ${a.name}`);
    }
  }
});
