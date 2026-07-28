// Wave 4 — F2 (+F3 atomic): Lean CERTIFIER -> OBSERVED, gated by SMT bounded faithfulness, router-wired.
//
// Two tiers, per the build-gate isolation contract (DESCRIPTION-INC2 §v2.1/§v2.2):
//
//  * FAST tier (always runs; the Foreman `node --test test/` gate). Drives the certifier + the lean/z3
//    independence canaries with INJECTED async stubs — NO lean, NO z3, cannot hang — and proves the
//    Wave-4 done-when end to end (atomic F2+F3):
//      - a TRUE formalizable theorem whose formalization passes bounded faithfulness reaches OBSERVED
//        (the canary re-runs lean+z3 to the same result), a re-executable lean+z3 artifact;
//      - a FALSE theorem (lean exit non-zero) is REJECTED (an honest reject, no OBSERVED);
//      - a Lean-valid proof of a DIFFERENT statement FAILS faithfulness and the OBSERVED lift HARD-FAULTS
//        (no green proof of a wrong statement);
//      - z3 `unknown` => OBSERVED WITHHELD (fail-CLOSED);
//      - a FORGED / cross-claim lean artifact is caught by the independent lean re-run;
//      - an un-exercised lean/z3 canary WITHHOLDS; one gate alone NEVER reaches OBSERVED (atomicity);
//      - liftToObserved is STRUCTURALLY unreachable without an OBSERVED adjudication result;
//      - the router `routeProofCertifier` seam lifts/abstains/flags accordingly.
//
//  * TOOL lane (env-gated RAMANUJAN_TOOL_TESTS=1, serial). Spawns the REAL lean + z3 by manifest
//    absolute path: the translated `1+1=2 := by decide` + a faithful query reaches OBSERVED, canary
//    re-running both tools; a false theorem is rejected.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { toolLaneSkip } from './tool-lane.mjs';
import { loadManifest } from '../src/phasef-probe.mjs';
import { ClaimLedger, RUNG, BELIEF, compareRungs } from '../src/claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from '../src/verify-router.mjs';
import {
  HEX64,
  OBSERVED_RUNG,
  OBSERVED_STATUS,
  OBSERVED_FAMILY,
  LEAN_ARTIFACT_FIELDS,
  OUT_OF_ENVELOPE_REASON,
  LeanCertifierError,
  SmtFaithfulnessError,
  statementHash,
  formalizeEquation,
  makeLeanArtifact,
  validateLeanArtifact,
  certifyLean,
  adjudicateObserved,
  liftToObserved,
  certifyObserved,
  createLeanCertify,
  createLeanRerun,
} from '../src/lean-certifier.mjs';
import {
  FAITHFULNESS_KIND,
  certifyFaithfulness,
  makePrngBattery,
  createZ3Solve,
} from '../src/smt-faithfulness.mjs';

// ---------------------------------------------------------------------------
// Fixtures + injected stubs (pure async — no tool).
// ---------------------------------------------------------------------------

const PINNED = loadManifest().faithfulness_instance_battery;
const PINNED_COUNT = PINNED.default_count; // 16
const DOMAIN = PINNED.bounded_domain; // { min: -64, max: 64 }
const LEAN_VERSION = '4.31.0-stub';
const Z3_VERSION = '4.16.0-stub';

/** A true, formalizable, decidable-arithmetic claim (1+1=2) — the in-repo translator's supported class. */
const TRUE_CLAIM = Object.freeze({
  id: 'pf::1+1=2',
  type: 'proof-bearing',
  statement: '1 + 1 = 2',
  meta: { equation: { a: 1, op: '+', b: 1, c: 2 } },
});

/** A false claim (1+1=3) — the translator emits `by decide` over it; lean will reject (exit non-zero). */
const FALSE_CLAIM = Object.freeze({
  id: 'pf::1+1=3',
  type: 'proof-bearing',
  statement: '1 + 1 = 3',
  meta: { equation: { a: 1, op: '+', b: 1, c: 3 } },
});

/** An async lean `certify` / `leanRerun` stub: exit 0 typechecks, non-zero rejects. */
const leanCertifyStub = (exitCode) => async () => ({ exitCode, oleanHash: exitCode === 0 ? '0'.repeat(64) : null });
const leanRerunStub = (exitCode) => async () => exitCode;

/** Pull the faithfulness-kind marker out of an emitted `.smt2` (the documented fast-tier seam). */
function kindOf(smt2) {
  const m = /ramanujan-faithfulness-kind:\s*(\S+)/.exec(smt2);
  return m ? m[1] : null;
}
function makeSolve(byKind) {
  return async (smt2) => {
    const k = kindOf(smt2);
    if (!(k in byKind)) throw new Error(`stub solve has no canned result for kind ${JSON.stringify(k)}`);
    return byKind[k];
  };
}
const D = FAITHFULNESS_KIND.DIFFERENTIAL;
const I = FAITHFULNESS_KIND.INSTANCE;
const VT = FAITHFULNESS_KIND.VACUITY_TRUE;
const VF = FAITHFULNESS_KIND.VACUITY_FALSE;
const faithfulSolve = makeSolve({ [D]: 'unsat', [I]: 'unsat', [VT]: 'sat', [VF]: 'sat' });
const unfaithfulSolve = makeSolve({ [D]: 'sat', [I]: 'unsat', [VT]: 'sat', [VF]: 'sat' });
const unknownSolve = makeSolve({ [D]: 'unknown', [I]: 'unsat', [VT]: 'sat', [VF]: 'sat' });

/** Mint a Lean record for a claim via the stub certify at the given exit code. */
function leanRecordFor(claim, exitCode) {
  const { leanSource } = formalizeEquation(claim, { domain: DOMAIN, batteryCount: PINNED_COUNT });
  return certifyLean({ claim, leanSource, leanVersion: LEAN_VERSION }, { certify: leanCertifyStub(exitCode) });
}

/** Mint a faithful SMT record for a claim via the stub producer solve. */
function smtRecordFor(claim, { producerSolve = faithfulSolve } = {}) {
  const { faithfulness } = formalizeEquation(claim, { domain: DOMAIN, batteryCount: PINNED_COUNT });
  return certifyFaithfulness(
    { claim, query: faithfulness.query, battery: faithfulness.battery, z3Version: Z3_VERSION, pinnedDefaultCount: PINNED_COUNT },
    { solve: producerSolve },
  );
}

/** An UNFAITHFUL SMT record: the formalization commits to a DIFFERENT value (3) than the claim states (2). */
async function unfaithfulSmtRecordFor(claim) {
  const query = { vars: ['probe'], smt_logic: 'QF_LIA', domain: DOMAIN, informal: '(= (+ 1 1) probe)', formal: '(= 3 probe)' };
  const battery = makePrngBattery(query, { count: PINNED_COUNT });
  return certifyFaithfulness(
    { claim, query, battery, z3Version: Z3_VERSION, pinnedDefaultCount: PINNED_COUNT },
    { solve: unfaithfulSolve },
  );
}

// ===========================================================================
// FAST TIER — the informal -> Lean TRANSLATION (NOT pre-written Lean) + the artifact.
// ===========================================================================

test('formalizeEquation TRANSLATES a structured claim into Lean (by decide) + a matching faithfulness query', () => {
  const { leanSource, faithfulness, translated } = formalizeEquation(TRUE_CLAIM, { domain: DOMAIN, batteryCount: PINNED_COUNT });
  assert.equal(translated, true);
  assert.match(leanSource, /example : \(1 : Nat\) \+ 1 = 2 := by decide/);
  // the faithfulness query pairs the CLAIM's asserted equation (parsed from claim.statement) with the
  // FORMALIZATION's equation (from meta.equation) — each the full ground equation as a contingent predicate.
  assert.equal(faithfulness.query.informal, '(and (= (+ 1 1) 2) (= probe 2))');
  assert.equal(faithfulness.query.formal, '(and (= (+ 1 1) 2) (= probe 2))');
  assert.equal(faithfulness.battery.count, PINNED_COUNT);
  assert.notEqual(faithfulness.battery.provenance, 'claude');
  assert.throws(() => formalizeEquation({ meta: {} }), LeanCertifierError);
  // a statement outside the supported ground-equation form throws (the translator's class is bounded).
  assert.throws(() => formalizeEquation({ statement: 'not an equation', meta: { equation: { a: 1, op: '+', b: 1, c: 2 } } }), LeanCertifierError);
});

test('F3 is NON-tautological / gate-independent: informal is parsed from claim.statement, formal from meta.equation', () => {
  // When the claim statement and its formalization AGREE, the two predicates render identically (the
  // correct result of agreement) — but they are built from INDEPENDENT sources.
  const agree = formalizeEquation(TRUE_CLAIM, { domain: DOMAIN, batteryCount: PINNED_COUNT });
  assert.equal(agree.faithfulness.query.informal, agree.faithfulness.query.formal);

  // A Lean-VALID formalization of a DIFFERENT (also-true) equation than the statement says: the `.lean`
  // proves 2+2=4 (would typecheck) but the claim states 1+1=2. informal (from statement) and formal (from
  // meta.equation) DIVERGE — so the F3 differential has real discriminating power over the translated
  // class (it is NOT subsumed by / tautological with the F2 lean gate).
  const laundering = Object.freeze({ id: 'pf::launder', type: 'proof-bearing', statement: '1 + 1 = 2', meta: { equation: { a: 2, op: '+', b: 2, c: 4 } } });
  const f = formalizeEquation(laundering, { domain: DOMAIN, batteryCount: PINNED_COUNT });
  assert.match(f.leanSource, /\(2 : Nat\) \+ 2 = 4 := by decide/); // F2 would accept this true theorem...
  assert.equal(f.faithfulness.query.informal, '(and (= (+ 1 1) 2) (= probe 2))'); // ...but F3 sees the claim says 1+1=2
  assert.equal(f.faithfulness.query.formal, '(and (= (+ 2 2) 4) (= probe 4))'); // while the formalization encodes 2+2=4
  assert.notEqual(f.faithfulness.query.informal, f.faithfulness.query.formal); // -> differential disagrees -> UNFAITHFUL
});

test('makeLeanArtifact mints the EXACT field set and validateLeanArtifact shape-checks it', () => {
  const artifact = makeLeanArtifact({ claim: TRUE_CLAIM, leanVersion: LEAN_VERSION, exitCode: 0, oleanHash: 'a'.repeat(64) });
  assert.deepEqual(Object.keys(artifact).sort(), [...LEAN_ARTIFACT_FIELDS].sort());
  assert.equal(artifact.statement_hash, statementHash(TRUE_CLAIM.statement));
  assert.match(artifact.statement_hash, HEX64);
  assert.equal(validateLeanArtifact(artifact).ok, true);
  assert.equal(validateLeanArtifact({ ...artifact, exit_code: 'x' }).ok, false);
  // olean_hash may be null (no .olean produced), but a non-hex string is rejected.
  assert.equal(validateLeanArtifact({ ...artifact, olean_hash: null }).ok, true);
  assert.equal(validateLeanArtifact({ ...artifact, olean_hash: 'nope' }).ok, false);
});

test('certifyLean runs the formalization through the injected lean subprocess and binds the artifact to the claim', async () => {
  const record = await leanRecordFor(TRUE_CLAIM, 0);
  assert.equal(record.claim_id, TRUE_CLAIM.id);
  assert.equal(record.artifact.exit_code, 0);
  assert.equal(record.artifact.statement_hash, statementHash(TRUE_CLAIM.statement));
  assert.match(record.lean_source, /by decide/);
  await assert.rejects(() => certifyLean({ claim: TRUE_CLAIM, leanSource: '', leanVersion: LEAN_VERSION }, { certify: leanCertifyStub(0) }), LeanCertifierError);
});

// ===========================================================================
// FAST TIER — the ATOMIC OBSERVED adjudication (the Wave-4 done-when bullets).
// ===========================================================================

test('done-when: a TRUE theorem + a FAITHFUL formalization reaches OBSERVED (canary re-runs lean+z3 to agreement)', async () => {
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0);
  const smtRecord = await smtRecordFor(TRUE_CLAIM);
  const r = await adjudicateObserved({
    claim: TRUE_CLAIM,
    leanRecord,
    smtRecord,
    leanRerun: leanRerunStub(0),
    z3Rerun: faithfulSolve,
    pinnedDefaultCount: PINNED_COUNT,
  });
  assert.equal(r.status, OBSERVED_STATUS.OBSERVED);
  assert.equal(r.ok, true);
  assert.equal(r.family, OBSERVED_FAMILY);
  // a re-executable lean+z3 artifact reference (both tools' provenance bound in).
  assert.equal(r.artifact_ref.statement_hash, statementHash(TRUE_CLAIM.statement));
  assert.equal(r.artifact_ref.lean_exit_code, 0);
  assert.equal(r.artifact_ref.differential_result, 'unsat');
  assert.equal(r.artifact_ref.battery_provenance, 'prng');
  assert.equal(r.artifact_ref.battery_count, PINNED_COUNT);
});

test('done-when: a FALSE theorem (lean exit non-zero) is REJECTED — an honest reject, no OBSERVED', async () => {
  const leanRecord = await leanRecordFor(FALSE_CLAIM, 1);
  const smtRecord = await smtRecordFor(FALSE_CLAIM);
  const r = await adjudicateObserved({
    claim: FALSE_CLAIM,
    leanRecord,
    smtRecord,
    leanRerun: leanRerunStub(1),
    z3Rerun: faithfulSolve,
    pinnedDefaultCount: PINNED_COUNT,
  });
  assert.equal(r.status, OBSERVED_STATUS.REJECTED);
  assert.equal(r.ok, false);
  assert.equal(r.flagged, false);
});

test('done-when: a Lean-valid proof of a DIFFERENT statement FAILS faithfulness and OBSERVED HARD-FAULTS (no green proof of a wrong statement)', async () => {
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0); // lean accepts (exit 0)...
  const smtRecord = await unfaithfulSmtRecordFor(TRUE_CLAIM); // ...but it formalizes a DIFFERENT statement
  const r = await adjudicateObserved({
    claim: TRUE_CLAIM,
    leanRecord,
    smtRecord,
    leanRerun: leanRerunStub(0),
    z3Rerun: unfaithfulSolve,
    pinnedDefaultCount: PINNED_COUNT,
  });
  assert.equal(r.status, OBSERVED_STATUS.FLAG);
  assert.equal(r.flagged, true);
  assert.match(r.reason, /faithfulness|hard-fault|wrong statement/i);
});

test('done-when: z3 `unknown` => OBSERVED WITHHELD (fail-closed)', async () => {
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0);
  const smtRecord = await smtRecordFor(TRUE_CLAIM, { producerSolve: unknownSolve });
  const r = await adjudicateObserved({
    claim: TRUE_CLAIM,
    leanRecord,
    smtRecord,
    leanRerun: leanRerunStub(0),
    z3Rerun: unknownSolve,
    pinnedDefaultCount: PINNED_COUNT,
  });
  assert.equal(r.status, OBSERVED_STATUS.WITHHELD);
  assert.equal(r.ok, false);
});

test('a FORGED lean artifact (recorded exit 0, the independent re-run exits non-zero) is FLAGged', async () => {
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0); // RECORDS exit 0...
  const smtRecord = await smtRecordFor(TRUE_CLAIM);
  const r = await adjudicateObserved({
    claim: TRUE_CLAIM,
    leanRecord,
    smtRecord,
    leanRerun: leanRerunStub(1), // ...but the independent lean re-run from the stored .lean exits 1
    z3Rerun: faithfulSolve,
    pinnedDefaultCount: PINNED_COUNT,
  });
  assert.equal(r.status, OBSERVED_STATUS.FLAG);
  assert.match(r.reason, /forged|re-run/i);
});

test('a cross-claim lean artifact (bound to another claim) is FLAGged by the statement-hash binding', async () => {
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0);
  const smtRecord = await smtRecordFor(TRUE_CLAIM);
  const r = await adjudicateObserved({
    claim: { ...TRUE_CLAIM, id: 'pf::other', statement: 'a totally different statement' },
    leanRecord,
    smtRecord,
    leanRerun: leanRerunStub(0),
    z3Rerun: faithfulSolve,
    pinnedDefaultCount: PINNED_COUNT,
  });
  assert.equal(r.status, OBSERVED_STATUS.FLAG);
  assert.match(r.reason, /cross-claim|not bound|replay|statement_hash/i);
});

test('ATOMICITY: one gate alone never reaches OBSERVED — an un-exercised lean OR z3 canary WITHHOLDS', async () => {
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0);
  const smtRecord = await smtRecordFor(TRUE_CLAIM);
  // no leanRerun => lean canary un-exercised.
  const noLean = await adjudicateObserved({ claim: TRUE_CLAIM, leanRecord, smtRecord, z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(noLean.status, OBSERVED_STATUS.WITHHELD);
  // lean canary passes, but no z3Rerun => faithfulness canary un-exercised.
  const noZ3 = await adjudicateObserved({ claim: TRUE_CLAIM, leanRecord, smtRecord, leanRerun: leanRerunStub(0), pinnedDefaultCount: PINNED_COUNT });
  assert.equal(noZ3.status, OBSERVED_STATUS.WITHHELD);
  // no SMT record at all => OBSERVED requires the bounded-faithfulness gate (atomic F2+F3).
  const noSmt = await adjudicateObserved({ claim: TRUE_CLAIM, leanRecord, leanRerun: leanRerunStub(0), z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(noSmt.status, OBSERVED_STATUS.WITHHELD);
});

test('a Claude-sourced faithfulness battery HARD-FAULTS at adjudication (the §v2.2 integrity throw propagates)', async () => {
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0);
  const smtRecord = await smtRecordFor(TRUE_CLAIM);
  const smuggled = { ...smtRecord, battery: { ...smtRecord.battery, provenance: 'claude' } };
  await assert.rejects(
    () => adjudicateObserved({ claim: TRUE_CLAIM, leanRecord, smtRecord: smuggled, leanRerun: leanRerunStub(0), z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT }),
    SmtFaithfulnessError,
  );
});

// ===========================================================================
// FAST TIER — liftToObserved: STRUCTURALLY unreachable without an OBSERVED result.
// ===========================================================================

test('liftToObserved HARD-FAULTS on any non-OBSERVED result and lifts (sticky) on an OBSERVED one', async () => {
  const ledger = new ClaimLedger();
  ledger.assert({ id: TRUE_CLAIM.id, type: 'proof-bearing' });
  // every non-OBSERVED status is structurally refused (the atomicity guarantee).
  for (const status of [OBSERVED_STATUS.REJECTED, OBSERVED_STATUS.WITHHELD, OBSERVED_STATUS.FLAG, undefined]) {
    assert.throws(() => liftToObserved(ledger, TRUE_CLAIM, { status }), LeanCertifierError);
  }
  assert.throws(() => liftToObserved(null, TRUE_CLAIM, { status: OBSERVED_STATUS.OBSERVED }), LeanCertifierError);

  const ok = { status: OBSERVED_STATUS.OBSERVED, family: OBSERVED_FAMILY, reason: 'both gates passed' };
  const snap = liftToObserved(ledger, TRUE_CLAIM, ok);
  assert.equal(snap.rung, RUNG.OBSERVED);
  assert.equal(ledger.rungOf(TRUE_CLAIM.id), OBSERVED_RUNG);
  assert.equal(ledger.beliefOf(TRUE_CLAIM.id), BELIEF.VERIFIED);
  // idempotent: a second lift HOLDS the rung (never lowers / double-promotes).
  liftToObserved(ledger, TRUE_CLAIM, ok);
  assert.equal(ledger.rungOf(TRUE_CLAIM.id), OBSERVED_RUNG);
  assert.ok(compareRungs(OBSERVED_RUNG, RUNG.CORROBORATED) > 0, 'OBSERVED is strictly above CORROBORATED');
});

test('certifyObserved runs the full F2+F3 certification end to end (producer mints + atomic adjudication)', async () => {
  const { leanSource, faithfulness } = formalizeEquation(TRUE_CLAIM, { domain: DOMAIN, batteryCount: PINNED_COUNT });
  const { leanRecord, smtRecord, result } = await certifyObserved(
    { claim: TRUE_CLAIM, leanSource, leanVersion: LEAN_VERSION, faithfulness, z3Version: Z3_VERSION, pinnedDefaultCount: PINNED_COUNT },
    { certify: leanCertifyStub(0), solve: faithfulSolve, leanRerun: leanRerunStub(0), z3Rerun: faithfulSolve },
  );
  assert.equal(leanRecord.artifact.exit_code, 0);
  assert.equal(result.status, OBSERVED_STATUS.OBSERVED);
});

// ===========================================================================
// FAST TIER — the router seam (routeProofCertifier): lift / reject / hard-fault / abstain.
// ===========================================================================

function freshRouterWith(claim) {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.decompose(claim);
  return { ledger, router };
}

test('GWT: routeProofCertifier lifts a TRUE + FAITHFUL proof to OBSERVED (belief VERIFIED), bound to the lean+z3 artifact', async () => {
  const { ledger, router } = freshRouterWith(TRUE_CLAIM);
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0);
  const smtRecord = await smtRecordFor(TRUE_CLAIM);
  const r = await router.routeProofCertifier(TRUE_CLAIM.id, {
    proof: { leanRecord, smtRecord, leanRerun: leanRerunStub(0), z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT },
  });
  assert.equal(r.verdict, ROUTE_VERDICT.OBSERVED);
  assert.equal(r.observed, true);
  assert.equal(r.settled, false); // OBSERVED is settled-CLASS but not the autonomous firewall VERIFIED verdict
  assert.equal(r.rung, RUNG.OBSERVED);
  assert.equal(r.belief, BELIEF.VERIFIED);
  assert.equal(ledger.rungOf(TRUE_CLAIM.id), OBSERVED_RUNG);
  assert.equal(r.stamp.verifier_family, OBSERVED_FAMILY);
  assert.ok(r.stamp.proof_certifier && r.stamp.proof_certifier.statement_hash === statementHash(TRUE_CLAIM.statement));
  assert.equal(r.advisory, null, 'a settled-class OBSERVED lift carries no out-of-model "needs verification" route');
  // idempotent through the seam.
  const again = await router.routeProofCertifier(TRUE_CLAIM.id, {
    proof: { leanRecord, smtRecord, leanRerun: leanRerunStub(0), z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT },
  });
  assert.equal(again.rung, RUNG.OBSERVED);
});

test('routeProofCertifier FLAGs a different-statement formalization — the OBSERVED lift never flips the rung', async () => {
  const { ledger, router } = freshRouterWith(TRUE_CLAIM);
  const leanRecord = await leanRecordFor(TRUE_CLAIM, 0);
  const smtRecord = await unfaithfulSmtRecordFor(TRUE_CLAIM);
  const r = await router.routeProofCertifier(TRUE_CLAIM.id, {
    proof: { leanRecord, smtRecord, leanRerun: leanRerunStub(0), z3Rerun: unfaithfulSolve, pinnedDefaultCount: PINNED_COUNT },
  });
  assert.equal(r.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(r.observed, false);
  assert.equal(ledger.rungOf(TRUE_CLAIM.id), RUNG.UNVERIFIED);
});

test('routeProofCertifier ABSTAINS+routes on a Lean reject and on z3 `unknown` (fail-closed) — rung untouched', async () => {
  // false theorem (lean reject)
  const { ledger: lA, router: rtA } = freshRouterWith(FALSE_CLAIM);
  const rejected = await rtA.routeProofCertifier(FALSE_CLAIM.id, {
    proof: { leanRecord: await leanRecordFor(FALSE_CLAIM, 1), smtRecord: await smtRecordFor(FALSE_CLAIM), leanRerun: leanRerunStub(1), z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT },
  });
  assert.equal(rejected.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(rejected.routed, true);
  assert.equal(lA.rungOf(FALSE_CLAIM.id), RUNG.UNVERIFIED);

  // z3 unknown (fail-closed)
  const { ledger: lB, router: rtB } = freshRouterWith(TRUE_CLAIM);
  const withheld = await rtB.routeProofCertifier(TRUE_CLAIM.id, {
    proof: { leanRecord: await leanRecordFor(TRUE_CLAIM, 0), smtRecord: await smtRecordFor(TRUE_CLAIM, { producerSolve: unknownSolve }), leanRerun: leanRerunStub(0), z3Rerun: unknownSolve, pinnedDefaultCount: PINNED_COUNT },
  });
  assert.equal(withheld.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(lB.rungOf(TRUE_CLAIM.id), RUNG.UNVERIFIED);
});

test('routeProofCertifier without a proof certificate ABSTAINs + routes (the deferred arm); a non-proof claim ABSTAINs', async () => {
  const { router } = freshRouterWith(TRUE_CLAIM);
  const deferred = await router.routeProofCertifier(TRUE_CLAIM.id, {});
  assert.equal(deferred.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(deferred.routed, true);
  assert.match(deferred.advisory.reason, /no Lean\+SMT|certificate/i);

  const ledger = new ClaimLedger();
  const router2 = new VerifyRouter({ ledger });
  router2.decompose({ id: 'c1', type: 'computational' });
  const na = await router2.routeProofCertifier('c1', { proof: {} });
  assert.equal(na.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.match(na.advisory.reason, /does not apply/i);
});

// ===========================================================================
// TOOL LANE — env-gated, serial, against the REAL lean + z3 (manifest absolute paths).
// ===========================================================================

describe('F2+F3 tool lane (real lean kernel + real z3)', { skip: toolLaneSkip(), concurrency: 1 }, () => {
  const manifest = loadManifest();
  const leanPath = manifest.tools.lean.path;
  const z3Path = manifest.tools.z3.path;
  const certify = createLeanCertify(leanPath, { timeoutMs: 120000 });
  const leanRerun = createLeanRerun(leanPath, { timeoutMs: 120000 });
  const solve = createZ3Solve(z3Path, { timeoutMs: 60000 });

  test('a TRUE translated theorem (1+1=2 := by decide) + a faithful query reaches OBSERVED (canary re-runs lean+z3)', { timeout: 300000 }, async () => {
    const { leanSource, faithfulness } = formalizeEquation(TRUE_CLAIM, { domain: DOMAIN, batteryCount: PINNED_COUNT });
    const { result } = await certifyObserved(
      { claim: TRUE_CLAIM, leanSource, leanVersion: manifest.tools.lean.version, faithfulness, z3Version: manifest.tools.z3.version, pinnedDefaultCount: PINNED_COUNT },
      { certify, solve, leanRerun, z3Rerun: solve },
    );
    assert.equal(result.status, OBSERVED_STATUS.OBSERVED, result.reason);
  });

  test('a FALSE translated theorem (1+1=3 := by decide) is REJECTED by the real lean kernel (no OBSERVED)', { timeout: 300000 }, async () => {
    const { leanSource, faithfulness } = formalizeEquation(FALSE_CLAIM, { domain: DOMAIN, batteryCount: PINNED_COUNT });
    const { result } = await certifyObserved(
      { claim: FALSE_CLAIM, leanSource, leanVersion: manifest.tools.lean.version, faithfulness, z3Version: manifest.tools.z3.version, pinnedDefaultCount: PINNED_COUNT },
      { certify, solve, leanRerun, z3Rerun: solve },
    );
    assert.equal(result.status, OBSERVED_STATUS.REJECTED, result.reason);
  });

  test('a Lean-VALID proof of a DIFFERENT equation than the claim states FAILS faithfulness under real z3 (OBSERVED hard-faults)', { timeout: 300000 }, async () => {
    // The `.lean` proves 2+2=4 (the real kernel ACCEPTS it, exit 0) but the claim states 1+1=2 — F3's
    // real-z3 differential must catch the mismatch so no green proof of a wrong statement reaches OBSERVED.
    const launder = Object.freeze({ id: 'pf::launder', type: 'proof-bearing', statement: '1 + 1 = 2', meta: { equation: { a: 2, op: '+', b: 2, c: 4 } } });
    const { leanSource, faithfulness } = formalizeEquation(launder, { domain: DOMAIN, batteryCount: PINNED_COUNT });
    const { result } = await certifyObserved(
      { claim: launder, leanSource, leanVersion: manifest.tools.lean.version, faithfulness, z3Version: manifest.tools.z3.version, pinnedDefaultCount: PINNED_COUNT },
      { certify, solve, leanRerun, z3Rerun: solve },
    );
    assert.equal(result.status, OBSERVED_STATUS.FLAG, result.reason);
    assert.match(result.reason, /faithfulness|wrong statement/i);
  });
});
