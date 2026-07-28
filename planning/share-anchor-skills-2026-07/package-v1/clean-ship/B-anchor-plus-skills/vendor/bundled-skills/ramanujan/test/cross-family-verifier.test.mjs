// Wave 3 — F1b: cross-family VERIFIER -> PLAUSIBILITY-CORROBORATED (router-wired).
//
// Two tiers, per the build-gate isolation contract (DESCRIPTION-INC2 §v2.1/§v2.2):
//
//  * FAST tier (always runs; the Foreman `node --test test/` gate). Drives the panel + the
//    independence-canary re-run with INJECTED async stubs — NO server, cannot hang — and proves the
//    Wave-3 done-when end to end:
//      - a quorum Qwen+Llama agreement LIFTS the claim to PLAUSIBILITY-CORROBORATED (stamped soft-check),
//        NOT OBSERVED and NEVER VERIFIED;
//      - a Claude(-containing) panel HARD-FAULTS (the Honesty Law boundary);
//      - a FORGED artifact (a recorded verdict the model would NOT give) is caught by the canary's
//        independent re-run from the stored prompt;
//      - a REPLAYED / cross-claim artifact fails the claim-binding;
//      - a DISAGREEING panel leaves the claim CONJECTURAL;
//      - a certifier that did NOT pass F0's proof-judging sentinel cannot corroborate;
//      - an un-exercised canary (no re-run capability) WITHHOLDS the lift.
//
//  * TOOL lane (env-gated RAMANUJAN_TOOL_TESTS=1, serial). Starts the persistent ollama server +
//    warms BOTH families ONCE, drives the REAL Qwen+Llama panel, and asserts the verdict-level
//    mechanism + a model-independent forgery rejection (a tampered recorded verdict).

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';

import { toolLaneSkip } from './tool-lane.mjs';
import {
  loadManifest,
  startOllamaServer,
  stopOllamaServer,
  warmUp,
  createOllamaGenerate,
} from '../src/phasef-probe.mjs';
import { HEX64, promptHash, TIER } from '../src/cross-family-driver.mjs';
import {
  buildCorroborationPrompt,
  makeQuorumArtifact,
  runCrossFamilyPanel,
  adjudicateCrossFamily,
  liftToPlausibilityCorroborated,
  liftCrossFamily,
  familyOfRecord,
  CrossFamilyVerifierError,
  CROSS_FAMILY_STATUS,
  PLAUSIBILITY_CORROBORATED_RUNG,
  CORROBORATED_RUNG,
  FRONTIER_MODEL,
  MIN_QUORUM,
} from '../src/cross-family-verifier.mjs';
import { VerifyRouter, ROUTE_VERDICT } from '../src/verify-router.mjs';
import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';

// ---------------------------------------------------------------------------
// Fixtures + stub generators (pure async — no network).
// ---------------------------------------------------------------------------

const PROOF_CLAIM = Object.freeze({
  id: 'pf::sum-1-2-3',
  type: 'proof-bearing',
  statement: '1 + 2 + 3 = 6',
  meta: { proof: '1+2 = 3, and 3+3 = 6, therefore 1+2+3 = 6.' },
});

const OTHER_CLAIM = Object.freeze({
  id: 'pf::other',
  type: 'proof-bearing',
  statement: 'every even integer > 2 is a sum of two primes',
  meta: { proof: 'it has been checked for many small cases.' },
});

const QWEN = { model: 'qwen2.5:7b-instruct-q4_K_M', family: 'qwen' };
const LLAMA = { model: 'llama3:latest', family: 'llama' };
/** The PINNED frontier Gemini member (the v3 PRIMARY — earns the stronger CORROBORATED rung). */
const GEMINI = { model: FRONTIER_MODEL, family: 'gemini', tier: TIER.FRONTIER };

/** A generate stub that returns a fixed answer regardless of prompt. */
const fixedGen = (answer) => async () => answer;

/** A single-member frontier-Gemini panel returning the given answer. */
const frontierPanel = (geminiAnswer) => [{ ...GEMINI, generate: fixedGen(geminiAnswer) }];
const GEMINI_TRUSTED = Object.freeze({ gemini: true });
const geminiRerun = (answer) => ({ gemini: fixedGen(answer) });

/** A panel where each family returns the given answer ('VALID' -> YES, 'INVALID' -> NO). */
function panelOf(qwenAnswer, llamaAnswer) {
  return [
    { ...QWEN, generate: fixedGen(qwenAnswer) },
    { ...LLAMA, generate: fixedGen(llamaAnswer) },
  ];
}

const BOTH_TRUSTED = Object.freeze({ qwen: true, llama: true });
const rerunOf = (qwenAnswer, llamaAnswer) => ({ qwen: fixedGen(qwenAnswer), llama: fixedGen(llamaAnswer) });

/** Decompose a claim into a fresh router/ledger and return { ledger, router, snap }. */
function freshRouterWith(claim) {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.decompose(claim);
  return { ledger, router, snap: ledger.get(claim.id) };
}

// ===========================================================================
// FAST TIER — the deterministic corroboration prompt (the binding payload).
// ===========================================================================

test('buildCorroborationPrompt is deterministic from the claim and distinguishes distinct claims', () => {
  const p = buildCorroborationPrompt(PROOF_CLAIM);
  assert.equal(p, buildCorroborationPrompt({ ...PROOF_CLAIM, id: 'different-id-same-text' }), 'prompt depends on (statement, proof), not id');
  assert.notEqual(p, buildCorroborationPrompt(OTHER_CLAIM));
  assert.match(p, /VALID or INVALID/);
  assert.match(p, /1 \+ 2 \+ 3 = 6/);
  assert.throws(() => buildCorroborationPrompt(null), CrossFamilyVerifierError);
});

// ===========================================================================
// FAST TIER — the quorum artifact.
// ===========================================================================

test('runCrossFamilyPanel + makeQuorumArtifact mint a claim-bound, >=2-family quorum artifact', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));
  assert.equal(artifact.claim_id, PROOF_CLAIM.id);
  assert.equal(artifact.rung, PLAUSIBILITY_CORROBORATED_RUNG);
  assert.equal(artifact.soft_check, true);
  assert.equal(artifact.prompt_hash, promptHash(artifact.prompt));
  assert.equal(artifact.prompt_hash, promptHash(buildCorroborationPrompt(PROOF_CLAIM)), 'prompt is the one THIS claim generates');
  assert.deepEqual(artifact.families, ['llama', 'qwen']);
  assert.equal(artifact.members.length, 2);
  assert.equal(artifact.quorum_verdict, 'YES'); // both said VALID -> YES (provenance only)
  for (const m of artifact.members) {
    assert.match(m.prompt_hash, HEX64);
    assert.equal(m.prompt_hash, artifact.prompt_hash, 'every member was asked the SAME prompt');
    assert.notEqual(m.family, 'claude');
  }
});

test('familyOfRecord is a stable sorted non-Claude stamp', () => {
  assert.equal(familyOfRecord(['llama', 'qwen']), 'cross-family:llama+qwen');
  assert.equal(familyOfRecord(['qwen', 'llama', 'qwen']), 'cross-family:llama+qwen');
});

// ===========================================================================
// FAST TIER — adjudication PASS + the lift.
// ===========================================================================

test('adjudicateCrossFamily PASSES on a trusted, claim-bound, re-run-agreeing quorum', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));
  const result = await adjudicateCrossFamily({
    artifact,
    claim: PROOF_CLAIM,
    rerun: rerunOf('VALID', 'VALID'),
    probeTrust: BOTH_TRUSTED,
  });
  assert.equal(result.status, CROSS_FAMILY_STATUS.CORROBORATED);
  assert.equal(result.quorum_verdict, 'YES');
  assert.deepEqual(result.families, ['llama', 'qwen']);
  assert.equal(result.family_of_record, 'cross-family:llama+qwen');
  assert.equal(result.soft_check, true);
  assert.ok(result.reexec.every((r) => r.agrees));
});

test('GWT: a quorum Qwen+Llama agreement LIFTS to PLAUSIBILITY-CORROBORATED (stamped soft-check), not OBSERVED', async () => {
  const { ledger, router, snap } = freshRouterWith(PROOF_CLAIM);
  const artifact = await runCrossFamilyPanel(snap, panelOf('VALID', 'VALID'));

  const r = await router.routeCrossFamily(PROOF_CLAIM.id, {
    crossFamily: { artifact, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED },
  });

  // the soft lift — a NEW rung strictly below OBSERVED, projecting CORROBORATED (never VERIFIED).
  assert.equal(r.verdict, ROUTE_VERDICT.CORROBORATED);
  assert.equal(r.lifted, true);
  assert.equal(r.settled, false);
  assert.equal(r.rung, PLAUSIBILITY_CORROBORATED_RUNG);
  assert.equal(r.rung, 'PLAUSIBILITY-CORROBORATED');
  assert.notEqual(r.rung, RUNG.OBSERVED);
  assert.equal(r.belief, BELIEF.CORROBORATED);
  assert.notEqual(r.belief, BELIEF.VERIFIED);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), PLAUSIBILITY_CORROBORATED_RUNG);

  // the honest stamp: an artifact-backed, SOFT-check, non-Claude family-of-record.
  assert.equal(r.stamp.soft_check, true);
  assert.equal(r.stamp.artifact_backed, true);
  assert.equal(r.stamp.verifier_family, 'cross-family:llama+qwen');
  assert.notEqual(r.stamp.verifier_family, 'claude');
  // the lift is auditably BOUND to the specific cross-family artifact (the prompt the canary re-ran).
  assert.ok(r.stamp.cross_family && r.stamp.cross_family.prompt_hash === artifact.prompt_hash);
  assert.deepEqual(r.stamp.cross_family.families, ['llama', 'qwen']);
  assert.equal(r.stamp.cross_family.quorum_verdict, 'YES');

  // a soft advisory toward the STRONGER OBSERVED (Lean) arm — not a "could not verify" route.
  assert.ok(r.advisory && r.advisory.soft_check === true);
  assert.match(r.advisory.target, /Lean|OBSERVED/);
  assert.equal(r.advisory.belief, BELIEF.CORROBORATED);

  // the lift is idempotent (a second pass HOLDS the soft rung — never lowers / double-promotes).
  const again = await router.routeCrossFamily(PROOF_CLAIM.id, {
    crossFamily: { artifact, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED },
  });
  assert.equal(again.rung, PLAUSIBILITY_CORROBORATED_RUNG);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), PLAUSIBILITY_CORROBORATED_RUNG);
});

test('liftToPlausibilityCorroborated requires a CORROBORATED result and a real ledger', async () => {
  const ledger = new ClaimLedger();
  ledger.assert({ id: PROOF_CLAIM.id, type: 'proof-bearing' });
  assert.throws(() => liftToPlausibilityCorroborated(ledger, PROOF_CLAIM, { status: CROSS_FAMILY_STATUS.ABSTAIN }), CrossFamilyVerifierError);
  assert.throws(() => liftToPlausibilityCorroborated(null, PROOF_CLAIM, { status: CROSS_FAMILY_STATUS.CORROBORATED, family_of_record: 'x', reason: 'r' }), CrossFamilyVerifierError);
});

// ===========================================================================
// FAST TIER — the Honesty Law boundary: a Claude verdict HARD-FAULTS.
// ===========================================================================

test('a Claude(-containing) panel HARD-FAULTS — a same-family verdict can never corroborate', async () => {
  const genuine = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));
  // splice a `claude` member into an otherwise well-formed artifact.
  const claudeMember = {
    model: 'opus',
    family: 'claude',
    prompt_hash: genuine.prompt_hash,
    verdict: 'YES',
    normalized_answer_hash: genuine.members[0].normalized_answer_hash,
    transcript_hash: genuine.members[0].transcript_hash,
  };
  const tampered = { ...genuine, members: [genuine.members[0], claudeMember] };

  await assert.rejects(
    () => adjudicateCrossFamily({ artifact: tampered, claim: PROOF_CLAIM, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED }),
    /claude/i,
  );

  // and through the router seam — the hard-fault propagates (it is NOT silently downgraded).
  const { router } = freshRouterWith(PROOF_CLAIM);
  await assert.rejects(
    () => router.routeCrossFamily(PROOF_CLAIM.id, { crossFamily: { artifact: tampered, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED } }),
    CrossFamilyVerifierError,
  );
});

// ===========================================================================
// FAST TIER — the independence canary: a FORGED artifact is rejected by the re-run.
// ===========================================================================

test('GWT: a FORGED artifact (recorded YES the model would NOT give) is caught by the independent re-run', async () => {
  const { ledger, router, snap } = freshRouterWith(PROOF_CLAIM);
  // the artifact RECORDS YES (driven with VALID)...
  const artifact = await runCrossFamilyPanel(snap, panelOf('VALID', 'VALID'));
  assert.equal(artifact.quorum_verdict, 'YES');

  // ...but the models, re-run from the stored prompt, actually say INVALID (NO) — the forgery.
  const r = await router.routeCrossFamily(PROOF_CLAIM.id, {
    crossFamily: { artifact, rerun: rerunOf('INVALID', 'INVALID'), probeTrust: BOTH_TRUSTED },
  });

  assert.equal(r.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(r.lifted, false);
  assert.equal(r.settled, false);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), RUNG.UNVERIFIED, 'a forged artifact NEVER flips the rung');
  assert.match(r.advisory.reason, /forged|re-run|DISAGREE/i);
});

test('a single forged member (the other genuinely agrees) still FLAGs the artifact', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));
  const result = await adjudicateCrossFamily({
    artifact,
    claim: PROOF_CLAIM,
    rerun: rerunOf('VALID', 'INVALID'), // qwen agrees, llama's recorded YES is forged
    probeTrust: BOTH_TRUSTED,
  });
  assert.equal(result.status, CROSS_FAMILY_STATUS.FLAG);
  assert.match(result.reason, /llama/);
});

// ===========================================================================
// FAST TIER — anti-replay: a cross-claim artifact fails the claim-binding.
// ===========================================================================

test('a REPLAYED / cross-claim artifact (minted for another claim) is FLAGged by the binding', async () => {
  // mint a genuine, re-run-agreeing artifact for PROOF_CLAIM...
  const artifactForA = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));

  // ...then present it for a DIFFERENT claim B.
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.decompose(OTHER_CLAIM);
  const r = await router.routeCrossFamily(OTHER_CLAIM.id, {
    crossFamily: { artifact: artifactForA, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED },
  });

  assert.equal(r.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(ledger.rungOf(OTHER_CLAIM.id), RUNG.UNVERIFIED);
  assert.match(r.advisory.reason, /not bound|replay|cross-claim/i);
});

test('a tampered prompt (prompt_hash no longer matches the stored prompt) is FLAGged', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));
  const tampered = { ...artifact, prompt: `${artifact.prompt} (smuggled)` };
  const result = await adjudicateCrossFamily({ artifact: tampered, claim: PROOF_CLAIM, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED });
  assert.equal(result.status, CROSS_FAMILY_STATUS.FLAG);
  assert.match(result.reason, /prompt_hash|tampered|bound/i);
});

// ===========================================================================
// FAST TIER — a disagreeing panel leaves the claim CONJECTURAL.
// ===========================================================================

test('a DISAGREEING panel earns NO lift — the claim stays CONJECTURAL (UNVERIFIED)', async () => {
  const { ledger, router, snap } = freshRouterWith(PROOF_CLAIM);
  const artifact = await runCrossFamilyPanel(snap, panelOf('VALID', 'INVALID')); // qwen YES, llama NO
  const r = await router.routeCrossFamily(PROOF_CLAIM.id, {
    crossFamily: { artifact, rerun: rerunOf('VALID', 'INVALID'), probeTrust: BOTH_TRUSTED },
  });

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.lifted, false);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), RUNG.UNVERIFIED);
  assert.equal(ledger.beliefOf(PROOF_CLAIM.id), BELIEF.CONJECTURAL);
  assert.match(r.advisory.reason, /quorum|CONJECTURAL|disagree/i);
});

test('a panel that AGREES the proof is INVALID does not lift either (a NO quorum is not a corroboration)', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('INVALID', 'INVALID'));
  const result = await adjudicateCrossFamily({ artifact, claim: PROOF_CLAIM, rerun: rerunOf('INVALID', 'INVALID'), probeTrust: BOTH_TRUSTED });
  assert.equal(result.status, CROSS_FAMILY_STATUS.ABSTAIN);
});

// ===========================================================================
// FAST TIER — the proof-judging gate: only F0-TRUSTED certifiers count.
// ===========================================================================

test('a certifier that did NOT pass F0 proof-judging is dropped -> no >=2 quorum -> NO lift', async () => {
  const { ledger, router, snap } = freshRouterWith(PROOF_CLAIM);
  const artifact = await runCrossFamilyPanel(snap, panelOf('VALID', 'VALID'));
  // llama is QUARANTINED (failed proof-judging): only qwen is trusted -> single trusted family.
  const r = await router.routeCrossFamily(PROOF_CLAIM.id, {
    crossFamily: { artifact, rerun: rerunOf('VALID', 'VALID'), probeTrust: { qwen: true, llama: false } },
  });

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), RUNG.UNVERIFIED);
  assert.match(r.advisory.reason, /proof-judging|TRUSTED|quorum/i);
});

test('FAIL-CLOSED: with NO probe-trust supplied, nothing is trusted and the lift is withheld', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));
  const result = await adjudicateCrossFamily({ artifact, claim: PROOF_CLAIM, rerun: rerunOf('VALID', 'VALID') });
  assert.equal(result.status, CROSS_FAMILY_STATUS.ABSTAIN);
  assert.match(result.reason, /TRUSTED|proof-judging/i);
});

test('an un-exercised canary (no re-run capability) WITHHOLDS the lift', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));
  const result = await adjudicateCrossFamily({ artifact, claim: PROOF_CLAIM, probeTrust: BOTH_TRUSTED }); // no rerun
  assert.equal(result.status, CROSS_FAMILY_STATUS.ABSTAIN);
  assert.match(result.reason, /canary|re-run|stubbed/i);
});

// ===========================================================================
// FAST TIER — router wiring guards.
// ===========================================================================

test('routeCrossFamily without a crossFamily artifact ABSTAINs + routes (the deferred arm)', async () => {
  const { ledger, router } = freshRouterWith(PROOF_CLAIM);
  const r = await router.routeCrossFamily(PROOF_CLAIM.id, {});
  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.routed, true);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), RUNG.UNVERIFIED);
  assert.match(r.advisory.reason, /no cross-family|panel/i);
});

test('routeCrossFamily on a non-applicable (computational) claim ABSTAINs', async () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.decompose({ id: 'c1', type: 'computational' });
  const r = await router.routeCrossFamily('c1', { crossFamily: { artifact: {}, probeTrust: BOTH_TRUSTED } });
  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.match(r.advisory.reason, /does not apply/i);
});

test('a malformed artifact (no members) FLAGs; an empty artifact ABSTAINs (deferred)', async () => {
  const noMembers = await adjudicateCrossFamily({ artifact: { claim_id: PROOF_CLAIM.id }, claim: PROOF_CLAIM, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED });
  assert.equal(noMembers.status, CROSS_FAMILY_STATUS.FLAG);
  const empty = await adjudicateCrossFamily({ artifact: null, claim: PROOF_CLAIM, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED });
  assert.equal(empty.status, CROSS_FAMILY_STATUS.ABSTAIN);
});

test('MIN_QUORUM is >=2 (the pinned cross-family quorum)', () => {
  assert.ok(MIN_QUORUM >= 2);
});

// ===========================================================================
// FAST TIER — v3 PER-VERIFIER rung: frontier Gemini -> CORROBORATED;
// ollama fallback -> PLAUSIBILITY-CORROBORATED; tier is CANARY-DERIVED.
// ===========================================================================

test('FRONTIER_MODEL is bound to the manifest pinned Gemini model (single source of truth, no drift)', () => {
  const manifest = loadManifest();
  assert.equal(FRONTIER_MODEL, manifest.tools.gemini.model);
  assert.equal(CORROBORATED_RUNG, 'CORROBORATED');
  assert.notEqual(CORROBORATED_RUNG, PLAUSIBILITY_CORROBORATED_RUNG);
});

test('GWT: a frontier-Gemini verdict LIFTS to CORROBORATED (stamped frontier cross-family, NOT soft), below OBSERVED', async () => {
  const { ledger, router, snap } = freshRouterWith(PROOF_CLAIM);
  const artifact = await runCrossFamilyPanel(snap, frontierPanel('VALID'));
  // the artifact's provenance tier/rung is frontier (the adjudicator still DERIVES it, never trusts it).
  assert.equal(artifact.tier, TIER.FRONTIER);
  assert.equal(artifact.rung, CORROBORATED_RUNG);
  assert.deepEqual(artifact.families, ['gemini']);

  const r = await router.routeCrossFamily(PROOF_CLAIM.id, {
    crossFamily: { artifact, rerun: geminiRerun('VALID'), probeTrust: GEMINI_TRUSTED },
  });

  // the STRONGER cross-family rung — CORROBORATED, strictly below OBSERVED, never VERIFIED.
  assert.equal(r.verdict, ROUTE_VERDICT.CORROBORATED);
  assert.equal(r.lifted, true);
  assert.equal(r.settled, false);
  assert.equal(r.observed, false);
  assert.equal(r.rung, CORROBORATED_RUNG);
  assert.equal(r.rung, RUNG.CORROBORATED);
  assert.notEqual(r.rung, RUNG.OBSERVED);
  assert.equal(r.belief, BELIEF.CORROBORATED);
  assert.notEqual(r.belief, BELIEF.VERIFIED);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), RUNG.CORROBORATED);

  // a frontier corroboration is NOT a soft check (that label is for the ollama fallback only).
  assert.equal(r.stamp.soft_check, false);
  assert.equal(r.stamp.artifact_backed, true);
  assert.equal(r.stamp.verifier_family, 'cross-family:gemini');
  assert.notEqual(r.stamp.verifier_family, 'claude');
  assert.equal(r.advisory.soft_check, false);
  assert.equal(r.advisory.tier, TIER.FRONTIER);
  assert.match(r.advisory.target, /OBSERVED/);
});

test('GWT: Gemini unavailable (429) so the ollama fallback runs -> lifts ONLY to PLAUSIBILITY-CORROBORATED (weak fallback tier)', async () => {
  const { ledger, router, snap } = freshRouterWith(PROOF_CLAIM);
  // the fallback panel = qwen + llama (tier defaults to fallback) — exactly what F0 falls back to on 429.
  const artifact = await runCrossFamilyPanel(snap, panelOf('VALID', 'VALID'));
  assert.equal(artifact.tier, TIER.FALLBACK);

  const r = await router.routeCrossFamily(PROOF_CLAIM.id, {
    crossFamily: { artifact, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED },
  });

  assert.equal(r.verdict, ROUTE_VERDICT.CORROBORATED);
  assert.equal(r.rung, PLAUSIBILITY_CORROBORATED_RUNG);
  assert.notEqual(r.rung, RUNG.CORROBORATED); // the weaker tier — NEVER the frontier rung on the fallback path.
  assert.notEqual(r.rung, RUNG.OBSERVED);
  assert.equal(r.stamp.soft_check, true);
  assert.equal(r.advisory.soft_check, true);
  assert.equal(r.advisory.tier, TIER.FALLBACK);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), PLAUSIBILITY_CORROBORATED_RUNG);
});

test('TIER IS CANARY-DERIVED: an ollama (qwen) verdict whose artifact LIES tier=frontier is FLAGged (tier/identity mismatch)', async () => {
  const genuine = await runCrossFamilyPanel(PROOF_CLAIM, panelOf('VALID', 'VALID'));
  // forge: stamp tier=frontier on a qwen member whose backend identity is NOT the pinned frontier model.
  const lying = { ...genuine, members: [{ ...genuine.members[0], tier: TIER.FRONTIER }, genuine.members[1]] };
  const result = await adjudicateCrossFamily({
    artifact: lying,
    claim: PROOF_CLAIM,
    rerun: rerunOf('VALID', 'VALID'),
    probeTrust: BOTH_TRUSTED,
  });
  assert.equal(result.status, CROSS_FAMILY_STATUS.FLAG);
  assert.match(result.reason, /tier|identity|frontier/i);

  // and through the router seam — the lie NEVER reaches the frontier (or any) rung.
  const { ledger, router } = freshRouterWith(PROOF_CLAIM);
  const r = await router.routeCrossFamily(PROOF_CLAIM.id, {
    crossFamily: { artifact: lying, rerun: rerunOf('VALID', 'VALID'), probeTrust: BOTH_TRUSTED },
  });
  assert.equal(r.verdict, ROUTE_VERDICT.FLAG);
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), RUNG.UNVERIFIED);
});

test('a gemini member on a NON-pinned model claiming tier=frontier is FLAGged (only the pinned frontier model earns frontier)', async () => {
  const genuine = await runCrossFamilyPanel(PROOF_CLAIM, frontierPanel('VALID'));
  // swap the model to a non-pinned gemini variant but keep tier=frontier — derived tier becomes fallback.
  const lying = { ...genuine, members: [{ ...genuine.members[0], model: 'gemini-1.0-legacy' }] };
  const result = await adjudicateCrossFamily({
    artifact: lying,
    claim: PROOF_CLAIM,
    rerun: geminiRerun('VALID'),
    probeTrust: GEMINI_TRUSTED,
  });
  assert.equal(result.status, CROSS_FAMILY_STATUS.FLAG);
  assert.match(result.reason, /tier|identity|frontier/i);
});

test('a FORGED frontier-Gemini artifact (recorded YES the model would NOT give) is caught by the independent re-run', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, frontierPanel('VALID'));
  assert.equal(artifact.quorum_verdict, null); // a single family never forms the >=2 recorded provenance quorum
  const result = await adjudicateCrossFamily({
    artifact,
    claim: PROOF_CLAIM,
    rerun: geminiRerun('INVALID'), // the model, re-run from the stored prompt, actually says INVALID
    probeTrust: GEMINI_TRUSTED,
  });
  assert.equal(result.status, CROSS_FAMILY_STATUS.FLAG);
  assert.match(result.reason, /forged|DISAGREE/i);
});

test('a frontier Gemini certifier that did NOT pass F0 proof-judging is dropped -> NO lift (fail-closed on the frontier path too)', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, frontierPanel('VALID'));
  const result = await adjudicateCrossFamily({
    artifact,
    claim: PROOF_CLAIM,
    rerun: geminiRerun('VALID'),
    probeTrust: { gemini: false },
  });
  assert.equal(result.status, CROSS_FAMILY_STATUS.ABSTAIN);
  assert.match(result.reason, /TRUSTED|proof-judging/i);
});

test('a frontier-Gemini panel that re-runs INVALID earns NO lift (a frontier NO is not a corroboration)', async () => {
  const artifact = await runCrossFamilyPanel(PROOF_CLAIM, frontierPanel('INVALID'));
  const result = await adjudicateCrossFamily({
    artifact,
    claim: PROOF_CLAIM,
    rerun: geminiRerun('INVALID'),
    probeTrust: GEMINI_TRUSTED,
  });
  assert.equal(result.status, CROSS_FAMILY_STATUS.ABSTAIN);
});

test('liftCrossFamily targets the DERIVED rung (frontier -> CORROBORATED) and HOLDS a stronger existing rung', async () => {
  const ledger = new ClaimLedger();
  ledger.assert({ id: PROOF_CLAIM.id, type: 'proof-bearing' });
  liftCrossFamily(ledger, PROOF_CLAIM, {
    status: CROSS_FAMILY_STATUS.CORROBORATED,
    rung: CORROBORATED_RUNG,
    family_of_record: 'cross-family:gemini',
    reason: 'frontier',
  });
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), RUNG.CORROBORATED);
  // a weaker fallback result must NOT lower the stronger frontier rung (sticky / HOLD).
  liftCrossFamily(ledger, PROOF_CLAIM, {
    status: CROSS_FAMILY_STATUS.CORROBORATED,
    rung: PLAUSIBILITY_CORROBORATED_RUNG,
    family_of_record: 'cross-family:llama+qwen',
    reason: 'fallback',
  });
  assert.equal(ledger.rungOf(PROOF_CLAIM.id), RUNG.CORROBORATED, 'a fallback re-pass HOLDS the stronger frontier rung');
  // a non-CORROBORATED result is refused.
  assert.throws(() => liftCrossFamily(ledger, PROOF_CLAIM, { status: CROSS_FAMILY_STATUS.ABSTAIN }), CrossFamilyVerifierError);
});

// ===========================================================================
// TOOL LANE — env-gated, serial, against the REAL persistent ollama server.
// ===========================================================================

describe('F1b tool lane (real Qwen+Llama panel)', { skip: toolLaneSkip(), concurrency: 1 }, () => {
  const manifest = loadManifest();
  const ollamaSpec = manifest.tools.ollama;
  const qwen = ollamaSpec.models.find((m) => m.family === 'qwen');
  const llama = ollamaSpec.models.find((m) => m.family === 'llama');
  let server = null;

  before(async () => {
    server = await startOllamaServer(ollamaSpec);
    await warmUp(ollamaSpec, qwen.name, server.baseUrl);
    await warmUp(ollamaSpec, llama.name, server.baseUrl);
  }, { timeout: manifest.wall_clock_budget_ms.cross_family_warmup * 2 + 60000 });

  after(async () => {
    await stopOllamaServer(server);
  });

  test('the real panel drives + adjudicates without error and is verdict-level coherent', {
    timeout: manifest.wall_clock_budget_ms.cross_family_sentinel + 60000,
  }, async () => {
    const ledger = new ClaimLedger();
    const router = new VerifyRouter({ ledger });
    router.decompose(PROOF_CLAIM);
    const snap = ledger.get(PROOF_CLAIM.id);

    const panel = [
      { ...QWEN, generate: createOllamaGenerate(ollamaSpec, qwen.name, server.baseUrl) },
      { ...LLAMA, generate: createOllamaGenerate(ollamaSpec, llama.name, server.baseUrl) },
    ];
    const artifact = await runCrossFamilyPanel(snap, panel);
    assert.equal(artifact.members.length, 2);

    // the independence canary re-runs the REAL panel from the stored prompt (deterministic decoding).
    const rerun = {
      qwen: createOllamaGenerate(ollamaSpec, qwen.name, server.baseUrl),
      llama: createOllamaGenerate(ollamaSpec, llama.name, server.baseUrl),
    };
    const r = await router.routeCrossFamily(PROOF_CLAIM.id, {
      crossFamily: { artifact, rerun, probeTrust: BOTH_TRUSTED },
    });

    // the mechanism produced a coherent verdict (no throw); a genuine artifact never FLAGs as forged.
    assert.ok([ROUTE_VERDICT.CORROBORATED, ROUTE_VERDICT.ABSTAIN].includes(r.verdict), `unexpected verdict ${r.verdict}: ${r.advisory && r.advisory.reason}`);
    if (r.verdict === ROUTE_VERDICT.CORROBORATED) {
      assert.equal(r.rung, PLAUSIBILITY_CORROBORATED_RUNG);
      assert.notEqual(r.rung, RUNG.OBSERVED);
      assert.equal(r.stamp.soft_check, true);
    }
  });

  test('a TAMPERED recorded verdict is rejected by the real independent re-run (forgery, model-independent)', {
    timeout: manifest.wall_clock_budget_ms.cross_family_sentinel + 60000,
  }, async () => {
    const panel = [
      { ...QWEN, generate: createOllamaGenerate(ollamaSpec, qwen.name, server.baseUrl) },
      { ...LLAMA, generate: createOllamaGenerate(ollamaSpec, llama.name, server.baseUrl) },
    ];
    const genuine = await runCrossFamilyPanel(PROOF_CLAIM, panel);
    // FLIP one member's recorded verdict — the real re-run will disagree, whatever the model said.
    const flipped = genuine.members[0].verdict === 'YES' ? 'NO' : 'YES';
    const tamperedMembers = [{ ...genuine.members[0], verdict: flipped }, genuine.members[1]];
    const tampered = { ...genuine, members: tamperedMembers };

    const rerun = {
      qwen: createOllamaGenerate(ollamaSpec, qwen.name, server.baseUrl),
      llama: createOllamaGenerate(ollamaSpec, llama.name, server.baseUrl),
    };
    const result = await adjudicateCrossFamily({ artifact: tampered, claim: PROOF_CLAIM, rerun, probeTrust: BOTH_TRUSTED });
    assert.equal(result.status, CROSS_FAMILY_STATUS.FLAG);
    assert.match(result.reason, /forged|DISAGREE/i);
  });
});
