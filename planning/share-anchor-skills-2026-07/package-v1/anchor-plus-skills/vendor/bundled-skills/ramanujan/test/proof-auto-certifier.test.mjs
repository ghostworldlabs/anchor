// W2 (Scope B) — the proof AUTO-CERTIFIER orchestration: takes a covered proof-bearing claim + a tool
// CAPABILITY, FORMALIZES it, mints the lean+z3 certificates, and routes them through the router's OBSERVED
// seam so a true+faithful claim lifts to OBSERVED — or honestly ABSTAINs (no capability / outside the
// ground-equation class) or is rejected (lean reject), with the ledger rung NEVER flipped on a non-pass.
//
// FAST tier ONLY (the Foreman `node --test test/` gate). Everything here drives autoCertifyProof with
// INJECTED deterministic stub certify/solve fns — NO lean, NO z3, cannot hang. It reuses the PROVEN
// OBSERVED-pass stub shape from lean-certifier.test.mjs / smt-faithfulness.test.mjs: an async lean
// `certify(leanSource) -> { exitCode, oleanHash }` + its canary `leanRerun(leanSource) -> exitCode` that
// AGREE on the exit code, and a kind-aware `solve(smt2)` (both producer + z3 canary) that answers per the
// embedded `; ramanujan-faithfulness-kind: <kind>` marker so the differential is `unsat` (FAITHFUL).
// buildCertifiersFromManifest is exercised ONLY for its wiring contract (throws on a missing tool path;
// returns a bundle of functions) — its returned tool fns are NEVER invoked in the fast tier.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadManifest } from '../src/phasef-probe.mjs';
import { ClaimLedger, RUNG } from '../src/claim-ledger.mjs';
import { VerifyRouter, ROUTE_VERDICT } from '../src/verify-router.mjs';
import { OBSERVED_RUNG, OBSERVED_FAMILY } from '../src/lean-certifier.mjs';
import { FAITHFULNESS_KIND } from '../src/smt-faithfulness.mjs';
import {
  autoCertifyProof,
  buildCertifiersFromManifest,
  isCoveredProofClaim,
  DEFAULT_PINNED_BATTERY_COUNT,
  ProofAutoCertifierError,
} from '../src/proof-auto-certifier.mjs';

// ---------------------------------------------------------------------------
// Fixtures + injected stubs (pure async — no tool). Same shape lean-certifier.test.mjs proves.
// ---------------------------------------------------------------------------

const PINNED = loadManifest().faithfulness_instance_battery;
const PINNED_COUNT = PINNED.default_count; // 16
const DOMAIN = PINNED.bounded_domain; // { min: -64, max: 64 }
const LEAN_VERSION = '4.31.0-stub';
const Z3_VERSION = '4.16.0-stub';

/** formalizeOpts every covered call uses (bounds + a full-size battery so the §v2.2 integrity check passes). */
const FORMALIZE_OPTS = { domain: DOMAIN, batteryCount: PINNED_COUNT };

/** A true, formalizable, decidable-arithmetic claim (1+1=2) — the in-repo translator's supported class. */
const COVERED_TRUE = Object.freeze({
  id: 'p1',
  type: 'proof-bearing',
  statement: '1 + 1 = 2',
  meta: { equation: { a: 1, op: '+', b: 1, c: 2 } },
});

/** A false covered claim (1+1=3) — the translator emits `by decide` over it; lean rejects (exit non-zero). */
const COVERED_FALSE = Object.freeze({
  id: 'p2',
  type: 'proof-bearing',
  statement: '1 + 1 = 3',
  meta: { equation: { a: 1, op: '+', b: 1, c: 3 } },
});

/** A proof-bearing claim OUTSIDE the ground-equation translator class (no meta.equation) — not covered. */
const NOT_COVERED = Object.freeze({
  id: 'p3',
  type: 'proof-bearing',
  statement: 'for all n, n + 0 = n',
});

/** An async lean `certify` stub: exit 0 typechecks, non-zero rejects. (Same shape as the proven house stub.) */
const leanCertifyStub = (exitCode) => async () => ({ exitCode, oleanHash: exitCode === 0 ? '0'.repeat(64) : null });
/** The lean independence-canary re-run: returns the SAME exit code (a divergence would be FLAGged as forged). */
const leanRerunStub = (exitCode) => async () => exitCode;

/** Pull the faithfulness-kind marker out of an emitted `.smt2` (the documented fast-tier seam). */
function kindOf(smt2) {
  const m = /ramanujan-faithfulness-kind:\s*(\S+)/.exec(smt2);
  return m ? m[1] : null;
}
/** Build an async `solve(smt2)` that answers per the FAITHFULNESS_KIND marker (no z3). */
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
// no disagreeing model, every instance agrees, informal is contingent => FAITHFUL.
const faithfulSolve = makeSolve({ [D]: 'unsat', [I]: 'unsat', [VT]: 'sat', [VF]: 'sat' });

/** The full stub certifier bundle for an OBSERVED lift (lean exit 0 + faithful z3, both canary-agreeing). */
function observedCertifiers({ exitCode = 0 } = {}) {
  return {
    certify: leanCertifyStub(exitCode),
    leanRerun: leanRerunStub(exitCode),
    solve: faithfulSolve,
    z3Rerun: faithfulSolve,
    leanVersion: LEAN_VERSION,
    z3Version: Z3_VERSION,
    pinnedDefaultCount: PINNED_COUNT,
  };
}

/** A fresh ledger+router with `claim` decomposed in at the floor (UNVERIFIED). */
function freshRouterWith(claim) {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  router.decompose(claim);
  return { ledger, router };
}

// ===========================================================================
// 1. OBSERVED pass — a covered true+faithful claim auto-certifies to OBSERVED.
// ===========================================================================

test('autoCertifyProof lifts a COVERED true+faithful claim to OBSERVED (stub lean exit 0 + faithful z3)', async () => {
  const { ledger, router } = freshRouterWith(COVERED_TRUE);
  const r = await autoCertifyProof(router, COVERED_TRUE, {
    certifiers: observedCertifiers(),
    formalizeOpts: FORMALIZE_OPTS,
  });

  assert.equal(r.verdict, ROUTE_VERDICT.OBSERVED);
  assert.equal(r.observed, true);
  assert.equal(r.rung, RUNG.OBSERVED);
  // the shared ledger reflects the OBSERVED lift (belief VERIFIED projection).
  assert.equal(ledger.rungOf(COVERED_TRUE.id), OBSERVED_RUNG);
  // the honest stamp is artifact-backed and carries the lean+z3 family-of-record + the bound artifact ref.
  assert.equal(r.stamp.artifact_backed, true);
  assert.equal(r.stamp.verifier_family, OBSERVED_FAMILY);
  assert.ok(r.stamp.proof_certifier, 'the OBSERVED lift is bound to a re-executable lean+z3 artifact ref');
});

// ===========================================================================
// 2. Lean REJECT — a false covered claim (lean exit non-zero) ABSTAINs; the rung stays at the floor.
// ===========================================================================

test('autoCertifyProof ABSTAINS (never OBSERVED) on a lean REJECT — the rung stays at the floor', async () => {
  const { ledger, router } = freshRouterWith(COVERED_FALSE);
  // certify + leanRerun BOTH return exit 1 (a genuine lean reject of a false theorem — canaries AGREE).
  const r = await autoCertifyProof(router, COVERED_FALSE, {
    certifiers: observedCertifiers({ exitCode: 1 }),
    formalizeOpts: FORMALIZE_OPTS,
  });

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.observed, false);
  // honest reject: the claim is routed out-of-model, the rung NEVER flips to OBSERVED.
  assert.equal(r.rung, RUNG.UNVERIFIED);
  assert.equal(ledger.rungOf(COVERED_FALSE.id), RUNG.UNVERIFIED);
  assert.notEqual(ledger.rungOf(COVERED_FALSE.id), OBSERVED_RUNG);
});

// ===========================================================================
// 3. Out-of-envelope / not covered — a non-ground-equation proof claim ABSTAINs and spawns nothing.
// ===========================================================================

test('autoCertifyProof ABSTAINS on a NOT-covered proof claim (no meta.equation) — rung unchanged, nothing spawned', async () => {
  // isCoveredProofClaim gates the whole class: false here, true for the case-1 ground-equation claim.
  assert.equal(isCoveredProofClaim(NOT_COVERED), false);
  assert.equal(isCoveredProofClaim(COVERED_TRUE), true);

  const { ledger, router } = freshRouterWith(NOT_COVERED);
  // Even WITH a full tool capability, an out-of-class claim routes to the deferred arm (spawns no tool).
  const r = await autoCertifyProof(router, NOT_COVERED, {
    certifiers: observedCertifiers(),
    formalizeOpts: FORMALIZE_OPTS,
  });

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.observed, false);
  assert.equal(r.rung, RUNG.UNVERIFIED);
  assert.equal(ledger.rungOf(NOT_COVERED.id), RUNG.UNVERIFIED);
});

// ===========================================================================
// 4. No capability — without a certifier bundle the auto-certifier can never settle a claim.
// ===========================================================================

test('autoCertifyProof ABSTAINS with NO certifier capability — it never certifies without the tools', async () => {
  const { ledger, router } = freshRouterWith(COVERED_TRUE);
  // no certifiers => the honest no-capability arm (routeProofCertifier with no proof).
  const r = await autoCertifyProof(router, COVERED_TRUE, {});

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.observed, false);
  assert.equal(r.rung, RUNG.UNVERIFIED);
  assert.equal(ledger.rungOf(COVERED_TRUE.id), RUNG.UNVERIFIED);
});

// ===========================================================================
// 5. buildCertifiersFromManifest — the wiring contract (throws on a missing tool path; returns fn bundle).
//    The returned tool fns are NEVER invoked in the fast tier (they would spawn lean/z3).
// ===========================================================================

test('buildCertifiersFromManifest THROWS on a missing lean/z3 path and returns a function bundle when both are present', () => {
  // missing tool paths -> a typed wiring error (distinguishable from an honest ABSTAIN).
  assert.throws(() => buildCertifiersFromManifest({ tools: {} }), ProofAutoCertifierError);
  assert.throws(() => buildCertifiersFromManifest({ tools: { lean: { path: '/x/lean' } } }), ProofAutoCertifierError);

  const manifest = {
    tools: {
      lean: { path: '/opt/lean/bin/lean', version: '4.31.0' },
      z3: { path: '/opt/z3/bin/z3', version: '4.16.0' },
    },
    faithfulness_instance_battery: { default_count: 16 },
  };
  const bundle = buildCertifiersFromManifest(manifest);
  // the bundle wires BOTH the producers and the independent canaries as (uncalled) functions.
  assert.equal(typeof bundle.certify, 'function');
  assert.equal(typeof bundle.leanRerun, 'function');
  assert.equal(typeof bundle.solve, 'function');
  assert.equal(typeof bundle.z3Rerun, 'function');
  assert.equal(bundle.leanVersion, '4.31.0');
  assert.equal(bundle.z3Version, '4.16.0');
  // the pinned faithfulness-battery default is read from the manifest (== the module's exported default).
  assert.equal(bundle.pinnedDefaultCount, 16);
  assert.equal(bundle.pinnedDefaultCount, DEFAULT_PINNED_BATTERY_COUNT);
});
