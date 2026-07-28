// Wave 16 — Claim-type dispatch classifier (C2).
//
// Exercises the REAL Wave-16 source (src/dispatch-classifier.mjs) against the REAL shared spine — the
// Wave-3 A1 ledger, the Wave-8 closed grammar recognizer, and the Wave-7 VERIFY router — proving the
// done-when:
//
//   ambiguous/borderline claims escalate CONSERVATIVELY to the proof route (ABSTAIN+route), NEVER
//   silently to autonomous-VERIFIED.
//
// The defining Given/When/Then: given a borderline claim, when C2 runs, then it routes to the proof
// route (ABSTAIN), never to autonomous-VERIFIED. Proven at two depths: (1) the SEPARATE-PASS
// classifier marks every borderline claim route=PROOF / autonomous_eligible=false; (2) routed THROUGH
// the real Wave-7 router (even with an adjudication dispatcher present) every borderline claim comes
// back ABSTAIN and never VERIFIED.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DISPATCH_ROUTE,
  DISPATCH_ROUTES,
  DISPATCH_DECISION,
  classifyDispatch,
  DispatchClassifier,
  dispatchClaims,
  dispatchAndRoute,
  BORDERLINE_DISPATCH_FIXTURE,
  CLEAR_DISPATCH_FIXTURE,
  DISPATCH_FIXTURE,
  runFixtureDispatch,
} from '../src/dispatch-classifier.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import { ROUTE_VERDICT, VerifyRouter } from '../src/verify-router.mjs';
import { int, add, mul, div, variable, sum } from '../src/firewall-grammar.mjs';

// A minimal stub adjudication dispatcher — present but NEVER reached for a borderline claim. Its mere
// presence proves the abstain is the GRAMMAR/route gate, not just "no minter wired".
const STUB_DISPATCHER = Object.freeze({
  family: 'firewall-subprocess',
  validateAndConsume() {
    throw new Error('the dispatcher must never be reached for a borderline/escalated claim');
  },
});

// =====================================================================================
// 0. Constants / route + decision vocabulary.
// =====================================================================================

test('DISPATCH_ROUTE is the pinned 3-way route enum; only autonomous-firewall is autonomous-eligible', () => {
  assert.deepEqual(DISPATCH_ROUTES, ['autonomous-firewall', 'proof', 'conceptual']);
  assert.equal(DISPATCH_ROUTE.AUTONOMOUS_FIREWALL, 'autonomous-firewall');
  assert.equal(DISPATCH_ROUTE.PROOF, 'proof');
  assert.equal(DISPATCH_ROUTE.CONCEPTUAL, 'conceptual');
});

test('DISPATCH_DECISION carries the autonomous-candidate vs abstain-and-route distinction', () => {
  assert.equal(DISPATCH_DECISION.AUTONOMOUS_CANDIDATE, 'autonomous-candidate');
  assert.equal(DISPATCH_DECISION.ABSTAIN_AND_ROUTE, 'abstain-and-route');
});

// =====================================================================================
// 1. THE DONE-WHEN (classifier arm) — borderline claims escalate to the proof route, never autonomous.
// =====================================================================================

test('done-when: EVERY borderline claim escalates to the PROOF route (ABSTAIN), never autonomous-VERIFIED', () => {
  for (const claim of BORDERLINE_DISPATCH_FIXTURE) {
    const d = classifyDispatch(claim);
    assert.equal(d.route, DISPATCH_ROUTE.PROOF, `${claim.id}: route ${d.route} != proof`);
    assert.equal(d.decision, DISPATCH_DECISION.ABSTAIN_AND_ROUTE, `${claim.id}: must ABSTAIN+route`);
    assert.equal(d.escalated, true, `${claim.id}: must be a conservative escalation`);
    assert.equal(d.autonomous_eligible, false, `${claim.id}: a borderline claim is NEVER autonomous-eligible`);
    assert.equal(d.inGrammar, false, `${claim.id}: a borderline claim is never in-grammar`);
    assert.equal(d.claim_type, 'proof-bearing', `${claim.id}: escalation re-types to proof-bearing`);
    assert.equal(typeof d.reason, 'string');
    assert.ok(d.reason.length > 0);
  }
});

test('GWT: a borderline claim (declared computational, expression out of grammar) routes to PROOF, never autonomous', () => {
  // The single canonical Given/When/Then: an out-of-grammar smuggle masquerading as computational.
  const borderline = { id: 'smuggle', type: 'computational', expr: add(int(2), mul(int(3), variable('z'))) };
  const d = classifyDispatch(borderline);
  assert.equal(d.route, DISPATCH_ROUTE.PROOF);
  assert.equal(d.autonomous_eligible, false);
  assert.equal(d.escalated, true);
  assert.match(d.reason, /not in the closed firewall grammar|smuggle/i);
});

// =====================================================================================
// 2. The fail-safe / default-deny gate — autonomous ONLY for a closed-grammar-recognized computation.
// =====================================================================================

test('a declared-computational claim with an IN-GRAMMAR expression is the autonomous-firewall candidate', () => {
  const d = classifyDispatch({ id: 'ok', type: 'computational', expr: sum('k', int(1), int(10), variable('k')) });
  assert.equal(d.route, DISPATCH_ROUTE.AUTONOMOUS_FIREWALL);
  assert.equal(d.decision, DISPATCH_DECISION.AUTONOMOUS_CANDIDATE);
  assert.equal(d.autonomous_eligible, true);
  assert.equal(d.inGrammar, true);
  assert.equal(d.escalated, false);
  assert.equal(d.claim_type, 'computational');
});

test('the GRAMMAR is the gate, not the label: an UNTYPED claim with an in-grammar expr is autonomous-eligible', () => {
  const d = classifyDispatch({ id: 'untyped-ok', expr: div(mul(int(6), int(7)), int(2)) });
  assert.equal(d.route, DISPATCH_ROUTE.AUTONOMOUS_FIREWALL);
  assert.equal(d.autonomous_eligible, true);
  assert.equal(d.inGrammar, true);
  assert.equal(d.declared_type, null); // it was untyped — the grammar admitted it, not the label
});

test('a declared-computational claim with NO expression escalates to PROOF (cannot confirm a literal computation)', () => {
  const d = classifyDispatch({ id: 'no-expr', type: 'computational' });
  assert.equal(d.route, DISPATCH_ROUTE.PROOF);
  assert.equal(d.autonomous_eligible, false);
  assert.equal(d.escalated, true);
  assert.match(d.reason, /no expression/i);
});

test('a DEEP-NESTED smuggle (free var buried in an otherwise-valid tree) escalates to PROOF', () => {
  // 1 + (2 + (3 * x)) — valid arithmetic with one free variable deep inside.
  const expr = add(int(1), add(int(2), mul(int(3), variable('x'))));
  const d = classifyDispatch({ id: 'deep', type: 'computational', expr });
  assert.equal(d.route, DISPATCH_ROUTE.PROOF);
  assert.equal(d.autonomous_eligible, false);
  assert.equal(d.escalated, true);
});

test('a float literal (no exact arithmetic) escalates to PROOF', () => {
  const d = classifyDispatch({ id: 'float', type: 'computational', expr: int(1.5) });
  assert.equal(d.route, DISPATCH_ROUTE.PROOF);
  assert.equal(d.autonomous_eligible, false);
});

test('an unbounded sum (non-literal upper bound) escalates to PROOF', () => {
  const d = classifyDispatch({ id: 'unbounded', type: 'computational', expr: sum('k', int(1), { type: 'infinity' }, variable('k')) });
  assert.equal(d.route, DISPATCH_ROUTE.PROOF);
  assert.equal(d.autonomous_eligible, false);
});

// =====================================================================================
// 3. Clear claims route to their honest route (no over-escalation).
// =====================================================================================

test('a declared proof-bearing claim routes to PROOF (NOT flagged as an escalation — it is what it declares)', () => {
  const d = classifyDispatch({ id: 'proof', type: 'proof-bearing' });
  assert.equal(d.route, DISPATCH_ROUTE.PROOF);
  assert.equal(d.escalated, false); // a declared proof claim is not a borderline escalation
  assert.equal(d.autonomous_eligible, false);
  assert.equal(d.claim_type, 'proof-bearing');
});

test('a declared conceptual claim routes to CONCEPTUAL (not over-escalated to proof)', () => {
  const d = classifyDispatch({ id: 'concept', type: 'conceptual' });
  assert.equal(d.route, DISPATCH_ROUTE.CONCEPTUAL);
  assert.equal(d.escalated, false);
  assert.equal(d.autonomous_eligible, false);
  assert.equal(d.claim_type, 'conceptual');
});

// =====================================================================================
// 4. The SEPARATE-PASS classifier over the full fixture battery + the plan invariants.
// =====================================================================================

test('the separate pass classifies the whole battery and upholds the fail-safe plan invariants', () => {
  const plan = runFixtureDispatch();

  // The done-when invariants hold across the whole battery.
  assert.equal(plan.noSilentAutonomous, true, 'no claim is autonomous-eligible without an in-grammar recognition');
  assert.equal(plan.borderlineEscalatesToProof, true, 'every escalated claim went to the proof route');
  assert.equal(plan.allDecided, true, 'no silent pass — every non-autonomous claim ABSTAIN+routes');

  // Exactly the two in-grammar computations are autonomous candidates; nothing else.
  assert.deepEqual([...plan.autonomousCandidates].sort(), ['c2::clear-computational', 'c2::clear-untyped-computational'].sort());

  // Every borderline fixture id landed under the proof route + in the escalated set.
  for (const c of BORDERLINE_DISPATCH_FIXTURE) {
    assert.ok(plan.byRoute[DISPATCH_ROUTE.PROOF].includes(c.id), `${c.id} should be on the proof route`);
    assert.ok(plan.escalated.includes(c.id), `${c.id} should be escalated`);
  }

  // The clear conceptual claim is the only one on the conceptual route.
  assert.deepEqual(plan.byRoute[DISPATCH_ROUTE.CONCEPTUAL], ['c2::clear-conceptual']);
});

test('dispatchClaims accepts a single claim or an array, and the pass is read-only (touches no ledger rung)', () => {
  const single = dispatchClaims({ id: 'one', type: 'proof-bearing' });
  assert.equal(single.decisions.length, 1);
  assert.equal(single.decisions[0].route, DISPATCH_ROUTE.PROOF);

  // Read-only: classifying claims from a ledger never raises a rung.
  const ledger = new ClaimLedger();
  ledger.assert({ id: 'L::comp', type: 'computational', meta: { expr: sum('k', int(1), int(3), variable('k')) } });
  ledger.assert({ id: 'L::proof', type: 'proof-bearing' });
  const plan = dispatchClaims(['L::comp', 'L::proof'], { ledger });
  assert.equal(plan.decisions[0].autonomous_eligible, true); // expr pulled from meta
  assert.equal(plan.decisions[1].route, DISPATCH_ROUTE.PROOF);
  assert.equal(ledger.rungOf('L::comp'), RUNG.UNVERIFIED); // unchanged
  assert.equal(ledger.rungOf('L::proof'), RUNG.UNVERIFIED);
});

// =====================================================================================
// 5. END-TO-END through the REAL Wave-7 router — borderline -> ABSTAIN, never VERIFIED.
// =====================================================================================

test('done-when (end-to-end): routed through the REAL router WITH a dispatcher present, every borderline claim ABSTAINs and is NEVER VERIFIED', () => {
  const out = dispatchAndRoute(BORDERLINE_DISPATCH_FIXTURE, { dispatcher: STUB_DISPATCHER });

  assert.equal(out.noBorderlineVerified, true, 'no borderline claim may reach VERIFIED');
  assert.equal(out.borderlineAbstains, true, 'every borderline claim comes back ABSTAIN');
  assert.equal(out.noSilentAutonomous, true);
  assert.equal(out.allRouted, true);

  for (const r of out.routed) {
    assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN, `${r.claim_id}: ${r.verdict} != ABSTAIN`);
    assert.notEqual(r.belief, BELIEF.VERIFIED, `${r.claim_id}: belief must never be VERIFIED`);
    assert.notEqual(r.rung, RUNG.OBSERVED, `${r.claim_id}: rung must never be OBSERVED`);
    // escalated to the proof route => dispatched to the proof certifier, never the firewall.
    assert.equal(r.verifier.name, 'proof-certifier', `${r.claim_id}: must route to the proof certifier`);
  }
});

test('end-to-end: the in-grammar computations are dispatched to the firewall verifier but still ABSTAIN (no artifact) — never silently VERIFIED', () => {
  const out = dispatchAndRoute(CLEAR_DISPATCH_FIXTURE, { dispatcher: STUB_DISPATCHER });
  const by = Object.fromEntries(out.routed.map((r) => [r.claim_id, r]));

  for (const id of ['c2::clear-computational', 'c2::clear-untyped-computational']) {
    const r = by[id];
    assert.equal(r.dispatch.autonomous_eligible, true);
    assert.equal(r.verifier.name, 'firewall-subprocess'); // C2 dispatched it to the autonomous route...
    assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN); // ...but with no artifact it honestly ABSTAINs (not VERIFIED).
    assert.notEqual(r.belief, BELIEF.VERIFIED);
  }
  // The proof + conceptual clear claims route out-of-model.
  assert.equal(by['c2::clear-proof'].verifier.name, 'proof-certifier');
  assert.equal(by['c2::clear-proof'].verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(by['c2::clear-conceptual'].verdict, ROUTE_VERDICT.ABSTAIN);
});

test('DEFENSE-IN-DEPTH: even routed AS computational (no C2 re-type), an out-of-grammar smuggle never reaches VERIFIED — the firewall grammar gate FLAGs/ABSTAINs', () => {
  // Bypass C2's escalation: hand the smuggle to the REAL router directly as a computational claim,
  // WITH a dispatcher present. The Wave-8 grammar front-end must still refuse it.
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger, dispatcher: STUB_DISPATCHER });
  const smuggle = { id: 'raw-smuggle', type: 'computational', expr: add(int(2), mul(int(3), variable('z'))) };
  const result = router.route(smuggle, {});
  assert.equal(result.verdict, ROUTE_VERDICT.ABSTAIN); // grammar reject => abstain, before any adjudication
  assert.notEqual(result.belief, BELIEF.VERIFIED);
  assert.equal(ledger.rungOf('raw-smuggle'), RUNG.UNVERIFIED);
});

// =====================================================================================
// 6. Robustness — malformed inputs are conservatively escalated, never crashed-into-autonomy.
// =====================================================================================

test('a malformed (non-object) input is conservatively escalated to the proof route, never autonomous', () => {
  for (const bad of [null, undefined, 42, 'a string', []]) {
    const d = classifyDispatch(bad);
    assert.equal(d.route, DISPATCH_ROUTE.PROOF, `${JSON.stringify(bad)} should escalate to proof`);
    assert.equal(d.autonomous_eligible, false);
    assert.equal(d.escalated, true);
  }
});

test('classify() carries the claim id; an id passed without a bound ledger throws (no silent miss)', () => {
  const c = new DispatchClassifier();
  assert.equal(c.classify({ id: 'x', type: 'conceptual' }).claim_id, 'x');
  assert.throws(() => c.classify('some-id'), /no ledger is bound/);
});

test('DispatchClassifier rejects a non-ledger ledger argument', () => {
  assert.throws(() => new DispatchClassifier({ ledger: {} }), /must be an A1 ClaimLedger/);
});

test('the combined DISPATCH_FIXTURE is the borderline battery followed by the clear claims', () => {
  assert.equal(DISPATCH_FIXTURE.length, BORDERLINE_DISPATCH_FIXTURE.length + CLEAR_DISPATCH_FIXTURE.length);
});
