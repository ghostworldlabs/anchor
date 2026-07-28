// Wave 7 — VERIFY router skeleton (A3) tests.
//
// Exercises the REAL Wave-7 source (src/verify-router.mjs) against the REAL A1 ledger
// (src/claim-ledger.mjs) + the A1.5 adjudication gate (src/adjudication.mjs) over the REAL
// inherited Phase-0 durability substrate (resolved via inherits.manifest.json), proving the
// done-when:
//   - any decomposed claim routes to an applicable verifier OR ABSTAINS+routes with an advisory
//     payload; there is NO silent pass;
//   - the explicit GWT: a proof-bearing claim with no autonomous verifier ABSTAINS to CONJECTURAL,
//     routes out-of-model, and emits an advisory payload.
// plus DECOMPOSE/DISPATCH/STAMP and the router arm of THE FLIP LAW.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  VerifyRouter,
  ROUTE_VERDICT,
  VERIFIER_TIER,
  BUILTIN_VERIFIERS,
  FIREWALL_FAMILY,
  routeClaims,
} from '../src/verify-router.mjs';
import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import {
  DurableNonceStore,
  AdjudicationDispatcher,
  canonicalStdoutHash,
  loadDurabilitySubstrate,
} from '../src/adjudication.mjs';

// The REAL inherited durability substrate, resolved via the pinned manifest.
const substrate = await loadDurabilitySubstrate();
const scratchDirs = [];
function scratch() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w7t-'));
  scratchDirs.push(dir);
  return dir;
}
after(() => {
  for (const d of scratchDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best-effort cleanup */ }
  }
});

let fileSeq = 0;
function freshDispatcher(family = FIREWALL_FAMILY) {
  const store = DurableNonceStore.load(substrate, path.join(scratch(), `w7-${fileSeq++}.checkpoint.json`));
  return new AdjudicationDispatcher({ store, family });
}

// A valid 64-hex stdout hash a Wave-9 firewall subprocess would emit (the gate does not re-execute;
// it shape-checks + freshness-checks the artifact, so any genuine digest reaches VERIFIED).
const STDOUT_HASH = canonicalStdoutHash({ computation: 'sum_{k=1}^{3} k', result: '6' });

function mintArtifactFor(dispatcher, claim_id, domain = 'arithmetic') {
  return dispatcher.mintArtifact(claim_id, domain, { stdout_hash: STDOUT_HASH, exit_code: 0 });
}

// =====================================================================================
// DECOMPOSE — typed claims land in the ledger at the FLOOR rung (UNVERIFIED).
// =====================================================================================

test('DECOMPOSE admits typed claims into the A1 ledger at UNVERIFIED (CONJECTURAL)', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  const ids = router.decompose([
    { id: 'c1', type: 'computational', statement: 'sum_{k=1}^{3} k = 6' },
    { id: 'p1', type: 'proof-bearing', statement: 'every even n>2 is a sum of two primes' },
    { id: 'k1', type: 'conceptual', statement: 'this is a generalization of X' },
  ]);
  assert.deepEqual(ids, ['c1', 'p1', 'k1']);
  for (const id of ids) {
    assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED, `${id} must enter at the floor rung`);
    assert.equal(ledger.beliefOf(id), BELIEF.CONJECTURAL, `${id} must project to CONJECTURAL`);
  }
});

test('DECOMPOSE is sticky for an already-admitted claim and accepts an existing id string', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.decompose({ id: 'c1', type: 'computational' });
  // re-decompose by id (must already exist) + by spec (sticky — no flip, no error).
  assert.deepEqual(router.decompose('c1'), ['c1']);
  assert.deepEqual(router.decompose({ id: 'c1', type: 'computational', statement: 'refresh' }), ['c1']);
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED);
  assert.throws(() => router.decompose('nope'), /unknown claim id/);
});

// =====================================================================================
// DISPATCH — the strongest APPLICABLE generator-INDEPENDENT verifier, by claim type.
// =====================================================================================

test('DISPATCH picks the strongest applicable verifier per claim type', () => {
  const router = new VerifyRouter({ ledger: new ClaimLedger() });

  const comp = router.dispatch({ type: 'computational' });
  assert.equal(comp.verifier.name, 'firewall-subprocess');
  assert.equal(comp.verifier.tier, VERIFIER_TIER.AUTONOMOUS);
  assert.equal(comp.autonomousApplies, true);

  const proof = router.dispatch({ type: 'proof-bearing' });
  // proof-bearing has NO autonomous verifier; the strongest applicable is an out-of-model certifier.
  assert.equal(proof.verifier.name, 'proof-certifier');
  assert.equal(proof.verifier.tier, VERIFIER_TIER.OUT_OF_MODEL);
  assert.equal(proof.autonomousApplies, false);

  const concept = router.dispatch({ type: 'conceptual' });
  assert.equal(concept.verifier.name, 'cross-family-corroborator');
  assert.equal(concept.autonomousApplies, false);

  assert.throws(() => router.dispatch({ type: 'nonsense' }), /no valid type/);
});

test('DISPATCH refuses to route to a same-family / generator-dependent verifier (THE HONESTY LAW)', () => {
  // A planted same-family "verifier" with the HIGHEST strength — it must NEVER be dispatched.
  const sameFamily = {
    name: 'same-family-self-verifier',
    family: 'same-family:model',
    tier: VERIFIER_TIER.AUTONOMOUS,
    strength: 999,
    appliesTo: ['computational', 'proof-bearing', 'conceptual'],
    generator_independent: false, // <- the proposing family; the router filters it out
    route_target: 'self',
    increment: 'Increment-1',
    verify: () => ({ verdict: ROUTE_VERDICT.VERIFIED, family: 'same-family:model', artifact_backed: true }),
  };
  const router = new VerifyRouter({ ledger: new ClaimLedger(), verifiers: [sameFamily, ...BUILTIN_VERIFIERS] });
  for (const type of ['computational', 'proof-bearing', 'conceptual']) {
    const d = router.dispatch({ type });
    assert.ok(d.verifier, `a generator-independent verifier must still apply for ${type}`);
    assert.notEqual(d.verifier.name, 'same-family-self-verifier', `${type} must not route to the same-family verifier`);
    assert.ok(d.applicable.every((v) => v.generator_independent === true), 'only generator-independent verifiers are applicable');
  }
});

// =====================================================================================
// ROUTE (computational) — VERIFIED only through an artifact-backed adjudication.
// =====================================================================================

test('ROUTE computational with a fresh adjudication artifact reaches VERIFIED (OBSERVED) + stamps the out-of-model family', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });

  router.decompose({ id: 'c1', type: 'computational', statement: 'sum_{k=1}^{3} k = 6' });
  const artifact = mintArtifactFor(dispatcher, 'c1');
  const r = router.route('c1', { artifact });

  assert.equal(r.verdict, ROUTE_VERDICT.VERIFIED);
  assert.equal(r.settled, true);
  assert.equal(r.routed, false);
  assert.equal(r.rung, RUNG.OBSERVED);
  assert.equal(r.belief, BELIEF.VERIFIED);
  assert.equal(ledger.rungOf('c1'), RUNG.OBSERVED);
  // the honest stamp: an artifact-backed out-of-model family-of-record (NOT the proposing model).
  assert.equal(r.stamp.artifact_backed, true);
  assert.equal(r.stamp.verifier_family, FIREWALL_FAMILY);
  assert.notEqual(r.stamp.verifier_family, 'same-family:model');
  assert.equal(r.advisory, null); // a settled claim is not routed out
});

test('ROUTE computational with NO dispatcher ABSTAINS+routes (no minter — honest)', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger }); // no dispatcher
  const r = router.route({ id: 'c1', type: 'computational' });

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.routed, true);
  assert.equal(r.rung, RUNG.UNVERIFIED);
  assert.equal(r.belief, BELIEF.CONJECTURAL);
  assert.ok(r.advisory && r.advisory.needs_verification === true);
  assert.equal(r.stamp.verifier_family, null); // no family claimed without an artifact
  assert.equal(r.stamp.artifact_backed, false);
});

test('ROUTE computational with a dispatcher but NO artifact ABSTAINS+routes', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });
  const r = router.route({ id: 'c1', type: 'computational' }); // no artifact in ctx

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.routed, true);
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED);
  assert.match(r.advisory.reason, /artifact/i);
});

test('ROUTE computational FLAGs a defective artifact (malformed / cross-claim / replayed) — never a silent pass', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });

  // (a) malformed artifact -> FLAG
  router.decompose({ id: 'c1', type: 'computational' });
  const bad = router.route('c1', { artifact: { claim_id: 'c1' } });
  assert.equal(bad.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(bad.routed, true);
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED); // not flipped
  assert.match(bad.advisory.reason, /malformed/i);

  // (b) cross-claim artifact (minted for OTHER, presented for c2) -> FLAG
  router.decompose({ id: 'c2', type: 'computational' });
  const forOther = mintArtifactFor(dispatcher, 'OTHER');
  const cross = router.route('c2', { artifact: { ...forOther, claim_id: 'c2' } });
  assert.equal(cross.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(ledger.rungOf('c2'), RUNG.UNVERIFIED);

  // (c) replayed (spent) artifact -> FLAG, and the rung is HELD at OBSERVED (sticky / single-use).
  router.decompose({ id: 'c3', type: 'computational' });
  const art = mintArtifactFor(dispatcher, 'c3');
  const ok = router.route('c3', { artifact: art });
  assert.equal(ok.verdict, ROUTE_VERDICT.VERIFIED);
  assert.equal(ledger.rungOf('c3'), RUNG.OBSERVED);
  const replay = router.route('c3', { artifact: art }); // re-present the spent artifact
  assert.equal(replay.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(ledger.rungOf('c3'), RUNG.OBSERVED); // held — the flip law
});

// =====================================================================================
// ROUTE (proof-bearing / conceptual) — the honest abstain+route arm + advisory payload.
// =====================================================================================

test('GWT: a proof-bearing claim with no autonomous verifier ABSTAINS to CONJECTURAL, routes out-of-model, and emits an advisory payload', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher(); // even WITH an autonomous adjudicator present...
  const router = new VerifyRouter({ ledger, dispatcher });

  // ...a proof-bearing claim has NO autonomous verifier, so it must abstain+route.
  const r = router.route({ id: 'p1', type: 'proof-bearing', statement: 'Goldbach' });

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.belief, BELIEF.CONJECTURAL, 'ABSTAINs to CONJECTURAL, never VERIFIED');
  assert.equal(r.routed, true);
  assert.equal(ledger.rungOf('p1'), RUNG.UNVERIFIED);
  // routes OUT of model with an advisory payload.
  assert.ok(r.advisory, 'an advisory payload is emitted');
  assert.equal(r.advisory.route, 'out-of-model');
  assert.equal(r.advisory.needs_verification, true);
  assert.equal(r.advisory.increment, 'Increment-2');
  assert.match(r.advisory.target, /proof/i);
  // the advisory carries an EMITTED (never dispatched) commission envelope.
  assert.ok(r.advisory.commission, 'the advisory carries a commission envelope');
  assert.equal(r.advisory.commission.dispatched, false);
  assert.equal(r.advisory.commission.cross_model, false);
  // no family-of-record is stamped without an artifact.
  assert.equal(r.stamp.verifier_family, null);
  assert.equal(r.stamp.artifact_backed, false);
});

test('ROUTE conceptual ABSTAINS+routes and emits a researchPrime commission envelope (built-in, emit-not-dispatch)', () => {
  const ledger = new ClaimLedger();
  const r = new VerifyRouter({ ledger }).route({ id: 'k1', type: 'conceptual', statement: 'X is a specialization of Y' });
  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.routed, true);
  assert.equal(r.advisory.commission.skill, 'researchPrime');
  assert.equal(r.advisory.commission.dispatched, false);
  assert.equal(r.advisory.commission.independent_origin, false);
  assert.match(r.advisory.commission.question, /k1/);
});

test('an injected commissioner mints the advisory commission envelope (emit, not dispatch)', () => {
  const seen = [];
  const commissioner = (args) => {
    seen.push(args);
    return { skill: 'researchPrime', researchprime_commission_id: 'rp-123', dispatched: false, cross_model: args.cross_model, question: args.question };
  };
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger, commissioner });
  const r = router.route({ id: 'p1', type: 'proof-bearing' });
  assert.equal(r.advisory.commission.researchprime_commission_id, 'rp-123');
  assert.equal(seen.length, 1);
  assert.equal(seen[0].cross_model, false);
  assert.equal(seen[0].claim_id, 'p1');
});

// =====================================================================================
// THE FLIP LAW (router arm) — the router raises a rung ONLY through the adjudication gate.
// =====================================================================================

test('FLIP LAW: an ABSTAIN/FLAG never flips a rung; only a fresh adjudicated artifact raises it', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });

  // ABSTAIN (no artifact) leaves UNVERIFIED.
  router.decompose({ id: 'c1', type: 'computational' });
  router.route('c1');
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED);

  // the SAME claim, now with a fresh artifact, is the ONLY way it rises — to OBSERVED.
  const art = mintArtifactFor(dispatcher, 'c1');
  const up = router.route('c1', { artifact: art });
  assert.equal(up.verdict, ROUTE_VERDICT.VERIFIED);
  assert.equal(ledger.rungOf('c1'), RUNG.OBSERVED);

  // a routed proof claim never reaches a settled belief, no matter how many times it is routed.
  router.decompose({ id: 'p1', type: 'proof-bearing' });
  for (let i = 0; i < 3; i++) router.route('p1');
  assert.equal(ledger.rungOf('p1'), RUNG.UNVERIFIED);
  assert.notEqual(ledger.beliefOf('p1'), BELIEF.VERIFIED);
});

// =====================================================================================
// STAMP — the per-claim stamp + advisory + NOTES are written into the ledger meta.
// =====================================================================================

test('STAMP: the router writes its stamp/advisory/notes into the claim meta (sticky — rung held)', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.route({ id: 'p1', type: 'proof-bearing', statement: 'P' });
  const meta = ledger.get('p1').meta.verify_router;
  assert.equal(meta.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(meta.routed, true);
  assert.equal(meta.stamp.rung, RUNG.UNVERIFIED);
  assert.ok(meta.advisory && meta.advisory.commission);
  assert.ok(Array.isArray(meta.notes) && meta.notes.length > 0);
  assert.equal(ledger.rungOf('p1'), RUNG.UNVERIFIED); // the re-assert held the rung
});

// =====================================================================================
// NO SILENT PASS — the headline done-when over a mixed batch.
// =====================================================================================

test('done-when: every decomposed claim routes to a verifier OR ABSTAINS+routes with an advisory payload (no silent pass)', () => {
  const dispatcher = freshDispatcher();
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger, dispatcher });

  // one computational claim WITH a fresh artifact (settles), plus proof + conceptual (abstain+route),
  // plus a computational claim WITHOUT an artifact (abstain+route).
  const claims = [
    { id: 'c1', type: 'computational' },
    { id: 'c2', type: 'computational' },
    { id: 'p1', type: 'proof-bearing' },
    { id: 'k1', type: 'conceptual' },
  ];
  const summary = router.verify(claims, { artifacts: { c1: mintArtifactFor(dispatcher, 'c1') } });

  assert.equal(summary.results.length, 4);
  assert.equal(summary.anyVerified, true);
  assert.equal(summary.allRouted, true);
  assert.equal(summary.noSilentPass, true, 'every claim is settled-by-artifact or routed+advisory');

  // every result carries an explicit verdict; non-VERIFIED ones are CONJECTURAL + routed + advisory.
  for (const r of summary.results) {
    assert.ok(Object.values(ROUTE_VERDICT).includes(r.verdict));
    if (r.verdict === ROUTE_VERDICT.VERIFIED) {
      assert.equal(r.belief, BELIEF.VERIFIED);
      assert.equal(r.stamp.artifact_backed, true);
    } else {
      assert.equal(r.routed, true);
      assert.notEqual(r.belief, BELIEF.VERIFIED);
      assert.ok(r.advisory && r.advisory.needs_verification === true);
    }
  }

  // c1 settled; the rest are honest abstains held at UNVERIFIED.
  assert.equal(ledger.rungOf('c1'), RUNG.OBSERVED);
  assert.equal(ledger.rungOf('c2'), RUNG.UNVERIFIED);
  assert.equal(ledger.rungOf('p1'), RUNG.UNVERIFIED);
  assert.equal(ledger.rungOf('k1'), RUNG.UNVERIFIED);
});

test('routeClaims convenience runs decompose+route end-to-end over a default ledger', () => {
  const { ledger, summary } = routeClaims([
    { id: 'p1', type: 'proof-bearing' },
    { id: 'k1', type: 'conceptual' },
  ]);
  assert.equal(summary.noSilentPass, true);
  assert.equal(summary.anyVerified, false);
  assert.equal(ledger.size, 2);
  for (const r of summary.results) {
    assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
    assert.ok(r.advisory.commission);
  }
});

// =====================================================================================
// Constructor guards.
// =====================================================================================

test('the router requires an A1 ledger and a non-empty verifier registry', () => {
  assert.throws(() => new VerifyRouter({}), /requires an A1 ClaimLedger/);
  assert.throws(() => new VerifyRouter({ ledger: new ClaimLedger(), verifiers: [] }), /non-empty verifier registry/);
});
