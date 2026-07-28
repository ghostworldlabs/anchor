// Wave 5 — F5: human GATE -> the GROUNDED rung (attested, >=OBSERVED-class), router-wired.
//
// FAST tier (always runs; the Foreman `node --test test/` gate). Drives the gate with INJECTED async lean/z3
// stubs (NO tool, cannot hang) to mint a REAL OBSERVED tool result, then exercises the human gate end to end
// against REAL Ed25519 attestation signatures (node:crypto) — proving the Wave-5 done-when:
//   - a Lean-OBSERVED formalization + a VALID attested assent bound to it reaches GROUNDED;
//   - a FORGED / WRONG-KEY / REPLAYED / CROSS-CLAIM assent is REFUSED (the claim never lifts past OBSERVED);
//   - absent assent it stays OBSERVED;
//   - a human "assent" on a tool-REJECTED claim does NOT lift it (the override law);
//   - liftToGrounded is STRUCTURALLY unreachable without a GROUNDED adjudication result;
//   - the router `routeHumanGate` seam grants / withholds / flags / abstains accordingly.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadManifest } from '../src/phasef-probe.mjs';
import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from '../src/verify-router.mjs';
import {
  formalizeEquation,
  certifyLean,
  adjudicateObserved,
  OBSERVED_STATUS,
} from '../src/lean-certifier.mjs';
import { certifyFaithfulness } from '../src/smt-faithfulness.mjs';
import {
  HEX64,
  GROUNDED_RUNG,
  GROUNDED_FAMILY,
  GROUNDED_STATUS,
  ASSENT_TOKEN,
  ASSENT_ARTIFACT_FIELDS,
  HumanGateError,
  generateAssentKeyPair,
  observedBindingHash,
  AssentSigner,
  AssentReplayGuard,
  validateAssentArtifact,
  adjudicateGrounded,
  liftToGrounded,
} from '../src/human-gate.mjs';

// ---------------------------------------------------------------------------
// Fixtures + injected stubs (pure async — no tool) + a real out-of-band signer.
// ---------------------------------------------------------------------------

const PINNED = loadManifest().faithfulness_instance_battery;
const PINNED_COUNT = PINNED.default_count;
const DOMAIN = PINNED.bounded_domain;
const LEAN_VERSION = '4.31.0-stub';
const Z3_VERSION = '4.16.0-stub';

const TRUE_CLAIM = Object.freeze({ id: 'pf::1+1=2', type: 'proof-bearing', statement: '1 + 1 = 2', meta: { equation: { a: 1, op: '+', b: 1, c: 2 } } });
const OTHER_CLAIM = Object.freeze({ id: 'pf::2+2=4', type: 'proof-bearing', statement: '2 + 2 = 4', meta: { equation: { a: 2, op: '+', b: 2, c: 4 } } });
const FALSE_CLAIM = Object.freeze({ id: 'pf::1+1=3', type: 'proof-bearing', statement: '1 + 1 = 3', meta: { equation: { a: 1, op: '+', b: 1, c: 3 } } });

const leanCertifyStub = (exitCode) => async () => ({ exitCode, oleanHash: exitCode === 0 ? '0'.repeat(64) : null });
const leanRerunStub = (exitCode) => async () => exitCode;

function kindOf(smt2) {
  const m = /ramanujan-faithfulness-kind:\s*(\S+)/.exec(smt2);
  return m ? m[1] : null;
}
const faithfulSolve = async (smt2) => {
  const k = kindOf(smt2);
  // differential + instances unsat (no disagreement); vacuity sat (non-vacuous).
  return k === 'vacuity-true' || k === 'vacuity-false' ? 'sat' : 'unsat';
};

/** The F2+F3 OBSERVED certification inputs for a claim (exit 0 = typechecks). */
async function proofInputs(claim, exitCode = 0) {
  const { leanSource, faithfulness } = formalizeEquation(claim, { domain: DOMAIN, batteryCount: PINNED_COUNT });
  const leanRecord = await certifyLean({ claim, leanSource, leanVersion: LEAN_VERSION }, { certify: leanCertifyStub(exitCode) });
  const smtRecord = await certifyFaithfulness(
    { claim, query: faithfulness.query, battery: faithfulness.battery, z3Version: Z3_VERSION, pinnedDefaultCount: PINNED_COUNT },
    { solve: faithfulSolve },
  );
  return { leanRecord, smtRecord, leanRerun: leanRerunStub(exitCode), z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT };
}

/** A real OBSERVED adjudication result (status OBSERVED + artifact_ref) for a true claim. */
async function observedResultFor(claim) {
  const inputs = await proofInputs(claim, 0);
  return adjudicateObserved({ claim, ...inputs });
}

/** A canonical out-of-band signer + the matching trusted public keyring. */
function freshAttestation(keyId = 'human-key-1', attestor = 'john.liechty') {
  const { publicKey, privateKey } = generateAssentKeyPair();
  const signer = new AssentSigner({ privateKey, keyId, attestor });
  const keyring = { [keyId]: publicKey };
  return { signer, keyring, publicKey };
}

// ===========================================================================
// FAST TIER — the OBSERVED binding + the attested assent artifact.
// ===========================================================================

test('observedBindingHash is a deterministic 64-hex digest of the OBSERVED artifact_ref (binds an assent to ONE certification)', async () => {
  const obs = await observedResultFor(TRUE_CLAIM);
  assert.equal(obs.status, OBSERVED_STATUS.OBSERVED);
  const h1 = observedBindingHash(obs.artifact_ref);
  const h2 = observedBindingHash(obs.artifact_ref);
  assert.match(h1, HEX64);
  assert.equal(h1, h2); // deterministic
  // a DIFFERENT claim's OBSERVED artifact binds to a DIFFERENT hash.
  const other = await observedResultFor(OTHER_CLAIM);
  assert.notEqual(observedBindingHash(other.artifact_ref), h1);
  assert.throws(() => observedBindingHash(null), HumanGateError);
});

test('AssentSigner mints the EXACT-field-set artifact and validateAssentArtifact shape-checks it', async () => {
  const obs = await observedResultFor(TRUE_CLAIM);
  const { signer } = freshAttestation();
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'n-1' });
  assert.deepEqual(Object.keys(assent).sort(), [...ASSENT_ARTIFACT_FIELDS].sort());
  assert.equal(assent.assent, ASSENT_TOKEN);
  assert.equal(assent.claim_id, TRUE_CLAIM.id);
  assert.equal(assent.observed_binding, observedBindingHash(obs.artifact_ref));
  assert.equal(validateAssentArtifact(assent).ok, true);
  assert.equal(validateAssentArtifact({ ...assent, signature: 'NOTHEX' }).ok, false);
  assert.equal(validateAssentArtifact({ ...assent, observed_binding: 'short' }).ok, false);
  // the signer REFUSES to mint without an OBSERVED result (assent can't be produced for a non-certified claim).
  assert.throws(() => signer.sign({ claim: TRUE_CLAIM, observed: { status: OBSERVED_STATUS.REJECTED }, nonce: 'n-x' }), HumanGateError);
});

// ===========================================================================
// FAST TIER — adjudicateGrounded: grant / override / forged / replayed / cross-claim / withheld.
// ===========================================================================

test('GWT: a Lean-OBSERVED formalization + a VALID attested assent bound to it reaches GROUNDED', async () => {
  const obs = await observedResultFor(TRUE_CLAIM);
  const { signer, keyring } = freshAttestation();
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'n-grant' });
  const guard = new AssentReplayGuard();
  const r = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent, keyring, replayGuard: guard });
  assert.equal(r.status, GROUNDED_STATUS.GROUNDED);
  assert.equal(r.ok, true);
  assert.equal(r.family, GROUNDED_FAMILY);
  assert.equal(r.attestation.attestor, 'john.liechty');
  assert.equal(r.attestation.key_id, 'human-key-1');
  assert.ok(r.artifact_ref); // bound to the lean+z3 OBSERVED artifact
});

test('OVERRIDE LAW: a human assent on a tool-REJECTED claim does NOT lift it (FLAG)', async () => {
  // The tool tier REJECTED the false theorem (lean exit non-zero).
  const inputs = await proofInputs(FALSE_CLAIM, 1);
  const rejected = await adjudicateObserved({ claim: FALSE_CLAIM, ...inputs });
  assert.equal(rejected.status, OBSERVED_STATUS.REJECTED);
  // A real, validly-signed assent (minted for a genuinely-OBSERVED claim) is replayed onto the rejected one.
  const obsTrue = await observedResultFor(TRUE_CLAIM);
  const { signer, keyring } = freshAttestation();
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obsTrue, nonce: 'n-override' });
  const r = adjudicateGrounded({ claim: FALSE_CLAIM, observed: rejected, assent, keyring, replayGuard: new AssentReplayGuard() });
  assert.equal(r.status, GROUNDED_STATUS.FLAG);
  assert.match(r.reason, /never overrides a tool rejection|did not certify OBSERVED/i);
});

test('a FORGED assent (tampered signature / untrusted key) is REFUSED (FLAG)', async () => {
  const obs = await observedResultFor(TRUE_CLAIM);
  const { signer, keyring } = freshAttestation();
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'n-forge' });

  // (a) tampered signature (flip the last hex nibble) — does not verify against the trusted key.
  const tamperedSig = assent.signature.slice(0, -1) + (assent.signature.endsWith('a') ? 'b' : 'a');
  const forged = { ...assent, signature: tamperedSig };
  const rForged = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent: forged, keyring, replayGuard: new AssentReplayGuard() });
  assert.equal(rForged.status, GROUNDED_STATUS.FLAG);
  assert.match(rForged.reason, /forged|signature does not verify/i);

  // (b) a signature from an UNTRUSTED key (not in the keyring) — fail-closed.
  const rogue = freshAttestation('rogue-key', 'attacker');
  const rogueAssent = rogue.signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'n-rogue' });
  const rRogue = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent: rogueAssent, keyring, replayGuard: new AssentReplayGuard() });
  assert.equal(rRogue.status, GROUNDED_STATUS.FLAG);
  assert.match(rRogue.reason, /not in the trusted keyring|untrusted/i);

  // (c) NO keyring at all — fail-closed (a no-op verifier cannot be stubbed away).
  const rNoKeyring = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent, replayGuard: new AssentReplayGuard() });
  assert.equal(rNoKeyring.status, GROUNDED_STATUS.FLAG);
});

test('a REPLAYED assent (same single-use nonce) is REFUSED on re-presentation (FLAG)', async () => {
  const obs = await observedResultFor(TRUE_CLAIM);
  const { signer, keyring } = freshAttestation();
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'n-once' });
  const guard = new AssentReplayGuard();
  const first = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent, keyring, replayGuard: guard });
  assert.equal(first.status, GROUNDED_STATUS.GROUNDED);
  // re-presenting the SAME assent (same nonce) through the same guard is rejected.
  const second = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent, keyring, replayGuard: guard });
  assert.equal(second.status, GROUNDED_STATUS.FLAG);
  assert.match(second.reason, /replay|already consumed/i);
});

test('a CROSS-CLAIM assent (bound to a different OBSERVED artifact) is REFUSED (FLAG)', async () => {
  const obsTrue = await observedResultFor(TRUE_CLAIM);
  const obsOther = await observedResultFor(OTHER_CLAIM);
  const { signer, keyring } = freshAttestation();
  // an assent genuinely signed for OTHER_CLAIM, presented against TRUE_CLAIM's gate.
  const assentOther = signer.sign({ claim: OTHER_CLAIM, observed: obsOther, nonce: 'n-cross' });
  const r = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obsTrue, assent: assentOther, keyring, replayGuard: new AssentReplayGuard() });
  assert.equal(r.status, GROUNDED_STATUS.FLAG);
  assert.match(r.reason, /cross-claim|bound to claim/i);
});

test('absent assent it stays OBSERVED (WITHHELD, not a defect); an un-exercised replay guard WITHHOLDS', async () => {
  const obs = await observedResultFor(TRUE_CLAIM);
  const { signer, keyring } = freshAttestation();
  // (a) no assent at all -> WITHHELD (stays OBSERVED).
  const none = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent: null, keyring, replayGuard: new AssentReplayGuard() });
  assert.equal(none.status, GROUNDED_STATUS.WITHHELD);
  assert.equal(none.flagged, false);
  // (b) a valid assent but NO replay guard -> WITHHELD (an un-exercised single-use check is treated as stubbed).
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'n-noguard' });
  const noGuard = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent, keyring });
  assert.equal(noGuard.status, GROUNDED_STATUS.WITHHELD);
  assert.match(noGuard.reason, /replay guard not exercised|stubbed/i);
  // (c) a non-positive assent (a dissent) -> WITHHELD (stays OBSERVED), not a lift.
  const dissent = signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'n-dissent', assent: 'DISSENT' });
  const dis = adjudicateGrounded({ claim: TRUE_CLAIM, observed: obs, assent: dissent, keyring, replayGuard: new AssentReplayGuard() });
  assert.equal(dis.status, GROUNDED_STATUS.WITHHELD);
});

test('absent any OBSERVED tool result and NO assent -> WITHHELD (the claim is simply not OBSERVED yet)', () => {
  const r = adjudicateGrounded({ claim: TRUE_CLAIM, observed: { status: OBSERVED_STATUS.WITHHELD }, assent: null, keyring: {}, replayGuard: new AssentReplayGuard() });
  assert.equal(r.status, GROUNDED_STATUS.WITHHELD);
  assert.equal(r.flagged, false);
});

// ===========================================================================
// FAST TIER — liftToGrounded: STRUCTURALLY unreachable without a GROUNDED result.
// ===========================================================================

test('liftToGrounded HARD-FAULTS on any non-GROUNDED result and lifts (sticky) on a GROUNDED one', async () => {
  const ledger = new ClaimLedger();
  ledger.assert({ id: TRUE_CLAIM.id, type: TRUE_CLAIM.type, statement: TRUE_CLAIM.statement });
  for (const status of [GROUNDED_STATUS.WITHHELD, GROUNDED_STATUS.FLAG, 'nonsense', undefined]) {
    assert.throws(() => liftToGrounded(ledger, TRUE_CLAIM, { status }), HumanGateError);
  }
  assert.throws(() => liftToGrounded(null, TRUE_CLAIM, { status: GROUNDED_STATUS.GROUNDED }), HumanGateError);

  const ok = { status: GROUNDED_STATUS.GROUNDED, family: GROUNDED_FAMILY, reason: 'test' };
  const snap = liftToGrounded(ledger, TRUE_CLAIM, ok);
  assert.equal(snap.rung, GROUNDED_RUNG);
  assert.equal(snap.belief, BELIEF.VERIFIED);
  // idempotent HOLD — lifting again never lowers / re-promotes.
  const again = liftToGrounded(ledger, TRUE_CLAIM, ok);
  assert.equal(again.rung, GROUNDED_RUNG);
});

// ===========================================================================
// FAST TIER — the router seam (routeHumanGate): grant / stays-OBSERVED / override / forged / abstain.
// ===========================================================================

function freshRouterWith(claim) {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.decompose(claim);
  return { ledger, router };
}

test('GWT: routeHumanGate lifts a Lean-OBSERVED proof + a valid attested assent to GROUNDED (belief VERIFIED)', async () => {
  const { ledger, router } = freshRouterWith(TRUE_CLAIM);
  const inputs = await proofInputs(TRUE_CLAIM, 0);
  const obs = await adjudicateObserved({ claim: TRUE_CLAIM, ...inputs });
  const { signer, keyring } = freshAttestation();
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'r-grant' });
  const r = await router.routeHumanGate(TRUE_CLAIM.id, {
    human: { ...inputs, assent, keyring, replayGuard: new AssentReplayGuard() },
  });
  assert.equal(r.verdict, ROUTE_VERDICT.GROUNDED);
  assert.equal(r.grounded, true);
  assert.equal(r.rung, GROUNDED_RUNG);
  assert.equal(r.belief, BELIEF.VERIFIED);
  assert.equal(ledger.rungOf(TRUE_CLAIM.id), GROUNDED_RUNG);
  assert.equal(r.stamp.verifier_family, GROUNDED_FAMILY);
  assert.ok(r.stamp.human_attestation && r.stamp.human_attestation.attestor === 'john.liechty');
  assert.ok(r.stamp.proof_certifier); // still bound to the lean+z3 artifact
  assert.equal(r.advisory, null); // settled-class apex — no out-of-model route
});

test('routeHumanGate WITHOUT assent leaves the claim at OBSERVED (the tool tier still certified it)', async () => {
  const { ledger, router } = freshRouterWith(TRUE_CLAIM);
  const inputs = await proofInputs(TRUE_CLAIM, 0);
  const r = await router.routeHumanGate(TRUE_CLAIM.id, { human: { ...inputs, assent: null, keyring: {}, replayGuard: new AssentReplayGuard() } });
  assert.equal(r.verdict, ROUTE_VERDICT.OBSERVED);
  assert.equal(r.observed, true);
  assert.equal(r.grounded, false);
  assert.equal(ledger.rungOf(TRUE_CLAIM.id), RUNG.OBSERVED);
  assert.equal(r.belief, BELIEF.VERIFIED);
});

test('routeHumanGate FLAGs a forged assent — the claim holds at OBSERVED (never lifted to GROUNDED)', async () => {
  const { ledger, router } = freshRouterWith(TRUE_CLAIM);
  const inputs = await proofInputs(TRUE_CLAIM, 0);
  const obs = await adjudicateObserved({ claim: TRUE_CLAIM, ...inputs });
  const { signer, keyring } = freshAttestation();
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obs, nonce: 'r-forge' });
  const forged = { ...assent, signature: assent.signature.slice(0, -1) + (assent.signature.endsWith('a') ? 'b' : 'a') };
  const r = await router.routeHumanGate(TRUE_CLAIM.id, { human: { ...inputs, assent: forged, keyring, replayGuard: new AssentReplayGuard() } });
  assert.equal(r.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(r.grounded, false);
  // the tool tier genuinely certified OBSERVED, so the claim holds there; the forged assent never lifts it.
  assert.equal(ledger.rungOf(TRUE_CLAIM.id), RUNG.OBSERVED);
});

test('routeHumanGate on a tool-REJECTED claim with an assent FLAGs (override attempt) — rung untouched', async () => {
  const { ledger, router } = freshRouterWith(FALSE_CLAIM);
  const inputs = await proofInputs(FALSE_CLAIM, 1); // lean rejects the false theorem
  const obsTrue = await observedResultFor(TRUE_CLAIM);
  const { signer, keyring } = freshAttestation();
  const assent = signer.sign({ claim: TRUE_CLAIM, observed: obsTrue, nonce: 'r-override' });
  const r = await router.routeHumanGate(FALSE_CLAIM.id, { human: { ...inputs, assent, keyring, replayGuard: new AssentReplayGuard() } });
  assert.equal(r.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(ledger.rungOf(FALSE_CLAIM.id), RUNG.UNVERIFIED); // never lifted
});

test('routeHumanGate without inputs ABSTAINs + routes; a non-proof claim ABSTAINs (does not apply)', async () => {
  const { router } = freshRouterWith(TRUE_CLAIM);
  const deferred = await router.routeHumanGate(TRUE_CLAIM.id, {});
  assert.equal(deferred.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(deferred.routed, true);
  assert.match(deferred.advisory.reason, /no human-gate inputs/i);

  const ledger = new ClaimLedger();
  const router2 = new VerifyRouter({ ledger });
  router2.decompose({ id: 'c1', type: 'computational' });
  const na = await router2.routeHumanGate('c1', { human: {} });
  assert.equal(na.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.match(na.advisory.reason, /does not apply/i);
});
