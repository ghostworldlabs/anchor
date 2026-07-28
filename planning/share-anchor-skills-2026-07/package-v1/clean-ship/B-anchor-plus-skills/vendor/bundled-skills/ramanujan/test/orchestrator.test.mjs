// Wave 23 — Autonomous orchestrator (D4).
//
// Exercises the REAL Wave-23 orchestrator (src/orchestrator.mjs) against the REAL spine — the six pillars
// over the A1 ledger + A3 router — proving the done-when:
//
//   the orchestrator routes read-only; it cannot settle or commission-dispatch a verdict (no commission-id,
//   no rung-flip) on ANY orchestrator path.
//
// Pins, in addition: the three Wave-23 deliverables — USER-EXPLICIT dispatch, the ADVISORY classifier
// (a suggestion, never a dispatch), and the FAIL-SAFE ASK — plus the structural read-only guard and the
// fact that the orchestrator re-uses (grows) the Wave-14 shim's EXACT no-dispatch predicate.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  PILLAR,
  PILLARS,
  ORCHESTRATOR_MODE,
  DISPATCH_DISPOSITION,
  AutonomousOrchestrator,
  orchestrate,
  classifyPillar,
  collectCommissionsDeep,
  checkShimInvariants,
} from '../src/orchestrator.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import { FIXTURE_METHOD } from '../src/comprehension.mjs';
import { FIXTURE_PROBLEM } from '../src/generation.mjs';
import { USER_INTENT } from '../src/dialogue-machine.mjs';
import { SUITE_KIND } from '../src/formalize-machine.mjs';
import { OBJECT_KIND } from '../src/contextualize-machine.mjs';
import { int, mul, variable, sum } from '../src/firewall-grammar.mjs';
import { isEmittedNotDispatched } from '../src/commission-emitters.mjs';

const IN_CLASS = sum('k', int(1), int(3), mul(variable('k'), int(2))); // = 12

// A read-only DISPATCH per pillar — exhaustive over the multi-pillar surface.
const PILLAR_REQUESTS = {
  [PILLAR.UNDERSTAND]: { pillar: PILLAR.UNDERSTAND, method: FIXTURE_METHOD },
  [PILLAR.SOLVE]: { pillar: PILLAR.SOLVE, problem: FIXTURE_PROBLEM },
  [PILLAR.VERIFY]: {
    pillar: PILLAR.VERIFY,
    claims: [
      { id: 'o::rh', type: 'proof-bearing', statement: 'every nontrivial zero has real part 1/2' },
      { id: 'o::sum', type: 'computational', statement: 'sum = 12', expr: IN_CLASS },
    ],
  },
  [PILLAR.DIALOGUE]: {
    pillar: PILLAR.DIALOGUE,
    turns: [
      { intent: USER_INTENT.PROPOSE_CONJECTURE, claim: { id: 'o::collatz', type: 'proof-bearing', statement: 'Collatz holds' } },
      { intent: USER_INTENT.ASK_STATUS, claim: 'o::collatz', utterance: 'is this settled?' },
    ],
  },
  [PILLAR.FORMALIZE]: {
    pillar: PILLAR.FORMALIZE,
    forge: {
      claim: { id: 'o::even', type: 'conceptual', statement: 'even := divisible by 2', definition: (n) => Number.isInteger(n) && n % 2 === 0 },
      suite: [
        { id: 'four', kind: SUITE_KIND.EXAMPLE, item: 4 },
        { id: 'three', kind: SUITE_KIND.MONSTER, item: 3 },
      ],
      certificate: { tier: 'out-of-model', faithful: true },
    },
  },
  [PILLAR.CONTEXTUALIZE]: {
    pillar: PILLAR.CONTEXTUALIZE,
    connection: {
      id: 'o::pi1~galois',
      source: { id: 'fundamental-group', name: 'pi_1', kind: OBJECT_KIND.CONCEPT, domain: 'algebraic-topology', constraints: ['acts-on-fibers', 'subgroup-lattice', 'deck-transformations'] },
      target: { id: 'galois-group', name: 'Gal', kind: OBJECT_KIND.CONCEPT, domain: 'field-theory', constraints: ['acts-on-roots', 'subgroup-lattice', 'field-automorphisms'] },
      correspondence: {
        answer: 'covers ~ field extensions',
        correspondences: [
          { source_relation: 'deck group acts on fibers', target_relation: 'Galois group acts on roots' },
          { source_relation: 'subgroups <-> covers', target_relation: 'subgroups <-> intermediate fields' },
        ],
      },
    },
  },
};

// =====================================================================================
// 0. Constants + the multi-pillar surface.
// =====================================================================================

test('the orchestrator exposes all SIX pillars in read-only mode', () => {
  assert.deepEqual(PILLARS, ['understand', 'solve', 'verify', 'dialogue', 'formalize', 'contextualize']);
  assert.equal(PILLARS.length, 6);
  assert.equal(ORCHESTRATOR_MODE, 'read-only');
  assert.deepEqual(DISPATCH_DISPOSITION, { DISPATCH: 'dispatch', ASK: 'ask' });
  const o = new AutonomousOrchestrator({ ledger: new ClaimLedger() });
  assert.deepEqual(o.pillars, PILLARS);
});

// =====================================================================================
// 1. THE DONE-WHEN — read-only DISPATCH on every pillar: no commission-id, no rung-flip.
// =====================================================================================

for (const pillar of PILLARS) {
  test(`done-when: read-only dispatch holds (no commission-id, no rung-flip) — pillar: ${pillar}`, () => {
    const ledger = new ClaimLedger();
    const handled = orchestrate(PILLAR_REQUESTS[pillar], { ledger });

    // It dispatched read-only to the user-named pillar.
    assert.equal(handled.disposition, 'dispatch');
    assert.equal(handled.pillar, pillar);
    assert.equal(handled.mode, 'read-only');
    assert.equal(handled.read_only, true);

    // The EXACT Wave-23 / Wave-14 predicate holds on this orchestrator path.
    assert.equal(handled.held, true, `invariants violated: ${handled.invariants.violations.join(' | ')}`);
    assert.equal(handled.noCommissionIdEmitted, true);
    assert.equal(handled.noRungFlip, true);
    assert.equal(handled.rungFlips.length, 0);
    assert.deepEqual(handled.invariants.dispatchedCommissionIds, []);

    // No rung in the real ledger left the floor (UNVERIFIED): the read-only route settled nothing.
    for (const id of ledger.ids()) {
      assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED, `${id} left the floor on a read-only orchestrator path`);
      assert.notEqual(ledger.beliefOf(id), BELIEF.VERIFIED);
    }

    // Every commission the pillar produced is EMIT-not-dispatch (no live dispatch, no dispatched id).
    for (const c of handled.commissions) {
      assert.equal(isEmittedNotDispatched(c), true);
    }
  });
}

test('done-when, aggregate: re-deriving the predicate via checkShimInvariants confirms held on every pillar', () => {
  for (const pillar of PILLARS) {
    const handled = orchestrate(PILLAR_REQUESTS[pillar], { ledger: new ClaimLedger() });
    const v = checkShimInvariants({ commissions: handled.commissions, rungFlips: handled.rungFlips });
    assert.equal(v.held, true, `${pillar}: ${v.violations.join(' | ')}`);
  }
});

test('the VERIFY/CONTEXTUALIZE pillars really emit an emit-not-dispatch commission (non-vacuous)', () => {
  const verify = orchestrate(PILLAR_REQUESTS[PILLAR.VERIFY], { ledger: new ClaimLedger() });
  const context = orchestrate(PILLAR_REQUESTS[PILLAR.CONTEXTUALIZE], { ledger: new ClaimLedger() });
  // A proof-bearing route + a conceptual connection each carry at least one commission envelope.
  assert.ok(verify.commissions.length >= 1, 'verify produced no commission');
  assert.ok(context.commissions.length >= 1, 'contextualize produced no commission');
  for (const c of [...verify.commissions, ...context.commissions]) assert.equal(isEmittedNotDispatched(c), true);
});

// =====================================================================================
// 2. USER-EXPLICIT dispatch + the ADVISORY classifier (a suggestion, never a dispatch).
// =====================================================================================

test('the ADVISORY classifier SUGGESTS a pillar but is pure + deterministic', () => {
  const a = classifyPillar('please solve and compute the value');
  assert.equal(a.suggestion, PILLAR.SOLVE);
  assert.equal(a.confident, true);
  // pure: same input => same output.
  assert.deepEqual(classifyPillar('please solve and compute the value'), a);
  // no cue match => null suggestion (fail-safe names no default).
  const none = classifyPillar('xyzzy plugh');
  assert.equal(none.suggestion, null);
  assert.equal(none.confident, false);
  // non-string utterance is tolerated (advisory).
  assert.equal(classifyPillar(undefined).suggestion, null);
});

test('a CONFIDENT advisory classification NEVER auto-dispatches: with no explicit pillar the orchestrator ASKs', () => {
  const ledger = new ClaimLedger();
  // An utterance the classifier confidently maps to a pillar — but no explicit pillar is named.
  const handled = orchestrate({ utterance: 'verify and check whether this is correct' }, { ledger });
  assert.equal(handled.disposition, 'ask');
  assert.equal(handled.pillar, null);
  // The advisory suggestion is surfaced for the user to confirm — but it did NOT dispatch.
  assert.equal(handled.ask.suggestion, PILLAR.VERIFY);
  assert.equal(handled.ask.advisory.confident, true);
  // The ASK touched NOTHING: no claim, no commission, no rung-flip.
  assert.equal(ledger.size, 0);
  assert.equal(handled.held, true);
  assert.deepEqual(handled.commissions, []);
  assert.deepEqual(handled.rungFlips, []);
});

test('USER-EXPLICIT dispatch: only an explicitly-named valid pillar routes', () => {
  const ledger = new ClaimLedger();
  const handled = orchestrate({ pillar: PILLAR.UNDERSTAND, method: FIXTURE_METHOD, utterance: 'contextualize this' }, { ledger });
  // The EXPLICIT pillar wins — the (conflicting) utterance suggestion is ignored for routing.
  assert.equal(handled.disposition, 'dispatch');
  assert.equal(handled.pillar, PILLAR.UNDERSTAND);
});

// =====================================================================================
// 3. FAIL-SAFE ASK — no explicit pillar, or an unrecognized one.
// =====================================================================================

test('fail-safe ASK: no explicit pillar => ASK (never a guess)', () => {
  const handled = orchestrate({ utterance: 'hello there' }, { ledger: new ClaimLedger() });
  assert.equal(handled.disposition, 'ask');
  assert.equal(handled.pillar, null);
  assert.deepEqual(handled.ask.options, PILLARS);
  assert.match(handled.ask.reason, /no explicit pillar/);
});

test('fail-safe ASK: an explicit but UNRECOGNIZED pillar is refused (ASK, never silently re-routed)', () => {
  const ledger = new ClaimLedger();
  const handled = orchestrate({ pillar: 'teleport', method: FIXTURE_METHOD }, { ledger });
  assert.equal(handled.disposition, 'ask');
  assert.equal(handled.pillar, null);
  assert.match(handled.ask.reason, /unrecognized pillar/);
  assert.equal(ledger.size, 0); // refused — nothing ran
});

// =====================================================================================
// 4. The read-only STRUCTURAL guarantee + fail-safe input guards.
// =====================================================================================

test('the orchestrator settles NOTHING: every fixture claim stays at UNVERIFIED across all pillars', () => {
  for (const pillar of PILLARS) {
    const ledger = new ClaimLedger();
    orchestrate(PILLAR_REQUESTS[pillar], { ledger });
    for (const id of ledger.ids()) assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED, `${pillar}: ${id} off floor`);
  }
});

test('each pillar fail-safe rejects a missing payload (never silently routes an empty request)', () => {
  const o = new AutonomousOrchestrator({ ledger: new ClaimLedger() });
  assert.throws(() => o.handle({ pillar: PILLAR.UNDERSTAND }), /requires request\.method/);
  assert.throws(() => o.handle({ pillar: PILLAR.SOLVE }), /requires request\.problem/);
  assert.throws(() => o.handle({ pillar: PILLAR.VERIFY }), /requires request\.claims/);
  assert.throws(() => o.handle({ pillar: PILLAR.DIALOGUE }), /requires request\.turns/);
  assert.throws(() => o.handle({ pillar: PILLAR.FORMALIZE }), /requires request\.forge/);
  assert.throws(() => o.handle({ pillar: PILLAR.CONTEXTUALIZE }), /requires request\.connection/);
});

test('the orchestrator guards its constructor + request inputs', () => {
  assert.throws(() => new AutonomousOrchestrator({ ledger: {} }), /requires an A1 ClaimLedger/);
  const o = new AutonomousOrchestrator({ ledger: new ClaimLedger() });
  assert.throws(() => o.handle(null), /requires a request object/);
});

// =====================================================================================
// 5. collectCommissionsDeep — finds every emit-not-dispatch envelope, anywhere it nests.
// =====================================================================================

test('collectCommissionsDeep finds a nested commission envelope (deep walk) and dedupes by identity', () => {
  const leg = { kind: 'researchprime-commission', emitted: true, dispatched: false };
  const nested = { a: { b: [{ advisory: { commission: leg } }] }, c: leg };
  const found = collectCommissionsDeep(nested);
  assert.equal(found.length, 1); // same object reached twice => deduped
  assert.equal(found[0], leg);
  // a non-commission object is ignored.
  assert.deepEqual(collectCommissionsDeep({ settled: false, needs_verification: true }), []);
});

// =====================================================================================
// 6. Statelessness — two handles of the same request on fresh ledgers agree.
// =====================================================================================

test('the orchestrator is stateless: two dispatches of the same request on fresh ledgers agree (held)', () => {
  const a = orchestrate(PILLAR_REQUESTS[PILLAR.UNDERSTAND], { ledger: new ClaimLedger() });
  const b = orchestrate(PILLAR_REQUESTS[PILLAR.UNDERSTAND], { ledger: new ClaimLedger() });
  assert.equal(a.held, true);
  assert.equal(b.held, true);
  const shape = (h) => h.output.comprehension.claims.map((c) => [c.id, c.rung, c.belief, c.verdict]);
  assert.deepEqual(shape(a), shape(b));
});
