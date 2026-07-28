// Wave 10 — Comprehension protocol (B1).
//
// Exercises the REAL Wave-10 source (src/comprehension.mjs) against the REAL shared spine — the
// Wave-3 A1 ledger, the Wave-7 VERIFY router, the Wave-8 closed grammar, the Wave-9 out-of-model
// firewall subprocess, and the Wave-4 adjudication substrate over the REAL inherited durability
// substrate — proving the done-when:
//
//   a fixture method with a COMPUTABLE and a PROOF-BEARING sub-claim yields a laddered comprehension
//   whose claims land in the ledger at the EXPECTED rung per claim class: the computable sub-claim
//   lands OBSERVED-via-firewall (belief VERIFIED, artifact-backed), and the proof-bearing sub-claim
//   lands CONJECTURAL/ABSTAIN (rung UNVERIFIED) — NEVER VERIFIED.
//
// Also pins the Step-0 firewall-applicability classifier (the 3-way enum + its fail-safe default-deny
// behaviour), the 5-step spine's statelessness, and the Honesty-Law / no-silent-pass invariants.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  FIREWALL_APPLICABILITY,
  FIREWALL_APPLICABILITY_VALUES,
  COMPREHENSION_STEPS,
  classifyFirewallApplicability,
  parseMethod,
  ComprehensionProtocol,
  comprehend,
  FIXTURE_METHOD,
  runFixtureComprehension,
  ROUTE_VERDICT,
} from '../src/comprehension.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import {
  loadDurabilitySubstrate,
  DurableNonceStore,
  AdjudicationDispatcher,
} from '../src/adjudication.mjs';
import { FIREWALL_FAMILY } from '../src/firewall-subprocess.mjs';
import { int, rational, mul, add, variable, sum, pow } from '../src/firewall-grammar.mjs';

// The REAL inherited durability substrate, resolved via the pinned manifest (matches Wave-4/6/8/9 setup).
const substrate = await loadDurabilitySubstrate();

let fileSeq = 0;
const scratchDirs = [];
function tmpFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w10-'));
  scratchDirs.push(dir);
  return path.join(dir, `nonce-store-${fileSeq++}.checkpoint.json`);
}
function freshDispatcher() {
  return new AdjudicationDispatcher({ store: DurableNonceStore.load(substrate, tmpFile()), family: FIREWALL_FAMILY });
}
after(() => {
  for (const d of scratchDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best-effort cleanup */ }
  }
});

// sum_{k=1}^{3} (k*2) = 12 — the canonical in-class literal computation.
const COMPUTABLE = sum('k', int(1), int(3), mul(variable('k'), int(2)));
const OUT_OF_GRAMMAR = { type: 'limit', var: 'n', to: 'infinity', body: variable('n') };

// =====================================================================================
// 0. The Step-0 firewall-applicability classifier (the 3-way enum + fail-safe default-deny).
// =====================================================================================

test('the 3-way firewall-applicability enum has exactly APPLICABLE / INAPPLICABLE / INDETERMINATE', () => {
  assert.deepEqual(FIREWALL_APPLICABILITY_VALUES.slice().sort(), [
    'firewall-applicable', 'firewall-inapplicable', 'firewall-indeterminate',
  ].sort());
  assert.equal(FIREWALL_APPLICABILITY_VALUES.length, 3);
});

test('Step-0: a recognized literal computation is APPLICABLE (and emits as computational)', () => {
  const c = classifyFirewallApplicability({ type: 'computational', expr: COMPUTABLE });
  assert.equal(c.applicability, FIREWALL_APPLICABILITY.APPLICABLE);
  assert.equal(c.claim_type, 'computational');
  assert.equal(c.inGrammar, true);
});

test('Step-0: a proof-bearing / conceptual claim is INAPPLICABLE (no autonomous verifier)', () => {
  const p = classifyFirewallApplicability({ type: 'proof-bearing', statement: 'converges' });
  assert.equal(p.applicability, FIREWALL_APPLICABILITY.INAPPLICABLE);
  assert.equal(p.claim_type, 'proof-bearing');
  assert.equal(p.inGrammar, false);

  const k = classifyFirewallApplicability({ type: 'conceptual', statement: 'is a generalization of X' });
  assert.equal(k.applicability, FIREWALL_APPLICABILITY.INAPPLICABLE);
  assert.equal(k.claim_type, 'conceptual');
});

test('Step-0 is FAIL-SAFE: a computational claim with an OUT-OF-GRAMMAR expr is INDETERMINATE (not APPLICABLE)', () => {
  const c = classifyFirewallApplicability({ type: 'computational', expr: OUT_OF_GRAMMAR });
  assert.equal(c.applicability, FIREWALL_APPLICABILITY.INDETERMINATE);
  assert.equal(c.inGrammar, false);
  assert.match(c.reason, /closed firewall grammar/);
});

test('Step-0 is FAIL-SAFE: a computational claim with NO expr is INDETERMINATE', () => {
  const c = classifyFirewallApplicability({ type: 'computational' });
  assert.equal(c.applicability, FIREWALL_APPLICABILITY.INDETERMINATE);
  assert.equal(c.inGrammar, false);
});

test('Step-0: an UNTYPED sub-claim carrying a recognized computation is APPLICABLE (grammar is the gate, not the label)', () => {
  const c = classifyFirewallApplicability({ expr: pow(int(2), int(10)) });
  assert.equal(c.applicability, FIREWALL_APPLICABILITY.APPLICABLE);
  assert.equal(c.claim_type, 'computational');
});

test('Step-0: an unknown/garbage sub-claim is INDETERMINATE, conservatively conceptual (never APPLICABLE)', () => {
  for (const bad of [null, undefined, 42, 'a string', { type: 'mystery' }, { type: 'mystery', expr: OUT_OF_GRAMMAR }]) {
    const c = classifyFirewallApplicability(bad);
    assert.equal(c.applicability, FIREWALL_APPLICABILITY.INDETERMINATE);
    assert.notEqual(c.applicability, FIREWALL_APPLICABILITY.APPLICABLE);
  }
});

// =====================================================================================
// 1. Step 1 — PARSE.
// =====================================================================================

test('parseMethod normalizes sub-claims and derives a deterministic id from method id + position', () => {
  const parsed = parseMethod({ id: 'm1', subclaims: [{ type: 'proof-bearing', statement: 'p' }, { id: 'explicit', type: 'computational', expr: int(1) }] });
  assert.equal(parsed.length, 2);
  assert.equal(parsed[0].id, 'm1::sub-0'); // derived, no wall-clock
  assert.equal(parsed[1].id, 'explicit'); // explicit id preserved
});

test('parseMethod rejects a method with no sub-claims', () => {
  assert.throws(() => parseMethod({ id: 'm', subclaims: [] }), /no .subclaims/);
  assert.throws(() => parseMethod(null), /method must be an object/);
});

// =====================================================================================
// 2. THE DONE-WHEN — a fixture method's claims land at the EXPECTED rung per claim class.
// =====================================================================================

test('done-when: the FIXTURE_METHOD comprehension lands each claim at its EXPECTED rung+belief', () => {
  const ledger = new ClaimLedger();
  const comp = runFixtureComprehension({ ledger, dispatcher: freshDispatcher() });

  // Every pinned expectation is met (rung + belief per claim class).
  assert.equal(comp.expectationsMet, true);
  for (const c of comp.claims) {
    assert.equal(c.rung_matches_expected, true, `${c.id}: rung ${c.rung} != expected ${c.expected_rung}`);
    assert.equal(c.belief_matches_expected, true, `${c.id}: belief ${c.belief} != expected ${c.expected_belief}`);
  }

  // The 5-step spine is reported.
  assert.deepEqual(comp.steps, ['PARSE', 'CLASSIFY', 'EMIT', 'ROUTE', 'LADDER']);
});

test('GWT: the computable sub-claim lands OBSERVED-via-firewall; the proof-bearing one lands CONJECTURAL/ABSTAIN (never VERIFIED)', () => {
  const ledger = new ClaimLedger();
  const comp = runFixtureComprehension({ ledger, dispatcher: freshDispatcher() });
  const by = Object.fromEntries(comp.claims.map((c) => [c.id, c]));

  // The COMPUTABLE sub-claim: OBSERVED, belief VERIFIED, artifact-backed, family = firewall-subprocess.
  const computable = by['fm::partial-sum-equals-12'];
  assert.equal(computable.applicability, FIREWALL_APPLICABILITY.APPLICABLE);
  assert.equal(computable.verdict, ROUTE_VERDICT.VERIFIED);
  assert.equal(computable.rung, RUNG.OBSERVED);
  assert.equal(computable.belief, BELIEF.VERIFIED);
  assert.equal(computable.artifact_backed, true);
  assert.equal(computable.verifier_family, FIREWALL_FAMILY);
  // and the LEDGER itself reflects it (the claim truly landed there).
  assert.equal(ledger.rungOf('fm::partial-sum-equals-12'), RUNG.OBSERVED);
  assert.equal(ledger.beliefOf('fm::partial-sum-equals-12'), BELIEF.VERIFIED);

  // The PROOF-BEARING sub-claim: ABSTAIN, rung UNVERIFIED, belief CONJECTURAL, NEVER VERIFIED, advisory present.
  const proof = by['fm::series-converges'];
  assert.equal(proof.applicability, FIREWALL_APPLICABILITY.INAPPLICABLE);
  assert.equal(proof.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(proof.rung, RUNG.UNVERIFIED);
  assert.equal(proof.belief, BELIEF.CONJECTURAL);
  assert.notEqual(proof.belief, BELIEF.VERIFIED);
  assert.equal(proof.artifact_backed, false);
  assert.equal(proof.verifier_family, null); // no family stamped without an artifact
  assert.ok(proof.advisory && proof.advisory.needs_verification === true, 'an ABSTAIN must carry an advisory payload');
  assert.equal(ledger.beliefOf('fm::series-converges'), BELIEF.CONJECTURAL);
});

test('the conceptual + INDETERMINATE("looks computational" limit) sub-claims also ABSTAIN to CONJECTURAL — never laundered to VERIFIED', () => {
  const ledger = new ClaimLedger();
  const comp = runFixtureComprehension({ ledger, dispatcher: freshDispatcher() });
  const by = Object.fromEntries(comp.claims.map((c) => [c.id, c]));

  const conceptual = by['fm::generalizes-partial-fractions'];
  assert.equal(conceptual.applicability, FIREWALL_APPLICABILITY.INAPPLICABLE);
  assert.equal(conceptual.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(conceptual.belief, BELIEF.CONJECTURAL);

  // The smuggle: declared computational but a non-literal limit. Step-0 = INDETERMINATE; the firewall
  // grammar front-end rejects it; it ABSTAINs and is NEVER VERIFIED (no artifact ever minted for it).
  const smuggle = by['fm::tail-limit-is-zero'];
  assert.equal(smuggle.applicability, FIREWALL_APPLICABILITY.INDETERMINATE);
  assert.equal(smuggle.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(smuggle.rung, RUNG.UNVERIFIED);
  assert.equal(smuggle.belief, BELIEF.CONJECTURAL);
  assert.notEqual(smuggle.belief, BELIEF.VERIFIED);
});

// =====================================================================================
// 3. The Honesty-Law + no-silent-pass invariants over the comprehension.
// =====================================================================================

test('the laddered comprehension holds THE HONESTY LAW: no proof/conceptual claim is OBSERVED/VERIFIED', () => {
  const ledger = new ClaimLedger();
  const comp = runFixtureComprehension({ ledger, dispatcher: freshDispatcher() });
  assert.equal(comp.honestyLawHeld, true);
  for (const c of comp.claims) {
    if (c.claim_type !== 'computational') {
      assert.notEqual(c.rung, RUNG.OBSERVED);
      assert.notEqual(c.belief, BELIEF.VERIFIED);
    }
  }
});

test('NO SILENT PASS: every claim is an artifact-backed VERIFIED or a routed ABSTAIN with an advisory payload', () => {
  const ledger = new ClaimLedger();
  const comp = runFixtureComprehension({ ledger, dispatcher: freshDispatcher() });
  assert.equal(comp.noSilentPass, true);
  // exactly one VERIFIED (the single computable claim); the other three are routed.
  assert.equal(comp.claims.filter((c) => c.belief === BELIEF.VERIFIED).length, 1);
  assert.equal(comp.anyVerified, true);
  // the ladder buckets: one OBSERVED, three UNVERIFIED.
  assert.deepEqual(comp.ladder[RUNG.OBSERVED], ['fm::partial-sum-equals-12']);
  assert.equal(comp.ladder[RUNG.UNVERIFIED].length, 3);
});

// =====================================================================================
// 4. The no-minter honest arm + statelessness.
// =====================================================================================

test('with NO dispatcher present, even the APPLICABLE computation ABSTAINs (honest no-minter arm) — no VERIFIED rung', () => {
  const ledger = new ClaimLedger();
  const comp = comprehend(FIXTURE_METHOD, { ledger /* no dispatcher */ });
  const computable = comp.claims.find((c) => c.id === 'fm::partial-sum-equals-12');
  assert.equal(computable.applicability, FIREWALL_APPLICABILITY.APPLICABLE); // still recognized in-class
  assert.equal(computable.verdict, ROUTE_VERDICT.ABSTAIN); // ...but cannot settle without a minter
  assert.equal(computable.rung, RUNG.UNVERIFIED);
  assert.equal(computable.belief, BELIEF.CONJECTURAL);
  assert.equal(comp.anyVerified, false);
  // still no silent pass, and the Honesty Law trivially holds.
  assert.equal(comp.noSilentPass, true);
  assert.equal(comp.honestyLawHeld, true);
});

test('the 5-step spine is STATELESS: two comprehensions on fresh ledgers are independent + identical', () => {
  const a = runFixtureComprehension({ ledger: new ClaimLedger(), dispatcher: freshDispatcher() });
  const b = runFixtureComprehension({ ledger: new ClaimLedger(), dispatcher: freshDispatcher() });
  // the laddered shape (rung/belief/verdict per claim) is reproducible across independent runs.
  const shape = (comp) => comp.claims.map((c) => [c.id, c.rung, c.belief, c.verdict, c.applicability]);
  assert.deepEqual(shape(a), shape(b));
  assert.equal(a.expectationsMet, true);
  assert.equal(b.expectationsMet, true);
});

test('re-comprehending the SAME method on the SAME ledger is STICKY: the settled rung is held (no flip, no double-promote)', () => {
  const ledger = new ClaimLedger();
  const first = runFixtureComprehension({ ledger, dispatcher: freshDispatcher() });
  assert.equal(first.expectationsMet, true);
  // A second comprehension over the same ledger re-asserts the same claim ids. The computable claim is
  // already OBSERVED; the sticky ledger holds it (a fresh artifact is NOT minted/promoted on top), and
  // the proof/conceptual claims remain CONJECTURAL.
  const second = new ComprehensionProtocol({ ledger, dispatcher: freshDispatcher() }).comprehend(FIXTURE_METHOD);
  assert.equal(ledger.rungOf('fm::partial-sum-equals-12'), RUNG.OBSERVED);
  assert.equal(ledger.beliefOf('fm::partial-sum-equals-12'), BELIEF.VERIFIED);
  assert.equal(ledger.beliefOf('fm::series-converges'), BELIEF.CONJECTURAL);
  assert.equal(second.honestyLawHeld, true);
});

// =====================================================================================
// 5. Constructor + emission contract.
// =====================================================================================

test('ComprehensionProtocol requires an A1 ledger', () => {
  assert.throws(() => new ComprehensionProtocol({}), /requires an A1 ClaimLedger/);
  assert.throws(() => new ComprehensionProtocol({ ledger: {} }), /requires an A1 ClaimLedger/);
});

test('every comprehended sub-claim is EMITTED into the shared A1 ledger as a typed claim', () => {
  const ledger = new ClaimLedger();
  runFixtureComprehension({ ledger, dispatcher: freshDispatcher() });
  // all four sub-claims are present in the ledger with their resolved types.
  assert.equal(ledger.size, 4);
  assert.equal(ledger.get('fm::partial-sum-equals-12').type, 'computational');
  assert.equal(ledger.get('fm::series-converges').type, 'proof-bearing');
  assert.equal(ledger.get('fm::generalizes-partial-fractions').type, 'conceptual');
  assert.equal(ledger.get('fm::tail-limit-is-zero').type, 'computational');
});

test('COMPREHENSION_STEPS is the pinned 5-step spine, in order', () => {
  assert.deepEqual(COMPREHENSION_STEPS, ['PARSE', 'CLASSIFY', 'EMIT', 'ROUTE', 'LADDER']);
});

// a custom ad-hoc method (not the pinned fixture) also ladders honestly: an in-class rational sum settles,
// a free-symbol "computation" does not.
test('an ad-hoc method ladders honestly: in-class rational arithmetic settles; a free-symbol computation ABSTAINs', () => {
  const ledger = new ClaimLedger();
  const method = {
    id: 'adhoc',
    subclaims: [
      { id: 'adhoc::rat', type: 'computational', expr: add(rational(1, 2), rational(1, 3)), expected_rung: RUNG.OBSERVED },
      { id: 'adhoc::free', type: 'computational', expr: add(variable('x'), int(1)), expected_rung: RUNG.UNVERIFIED },
    ],
  };
  const comp = comprehend(method, { ledger, dispatcher: freshDispatcher() });
  assert.equal(comp.expectationsMet, true);
  assert.equal(ledger.rungOf('adhoc::rat'), RUNG.OBSERVED);
  assert.equal(ledger.rungOf('adhoc::free'), RUNG.UNVERIFIED);
  const free = comp.claims.find((c) => c.id === 'adhoc::free');
  assert.equal(free.applicability, FIREWALL_APPLICABILITY.INDETERMINATE);
});
