// W2 (Scope B) — wire the REAL Lean+z3 OBSERVED certifier into the default proof path.
//
// THE GAP THIS CLOSES. verify-router already has the full ASYNC OBSERVED seam (routeProofCertifier ->
// adjudicateObserved -> liftToObserved), but it requires the CALLER to hand it a pre-built { leanRecord,
// smtRecord, leanRerun, z3Rerun }. Nothing yet takes a proof-bearing claim in the translator's covered
// class, FORMALIZES it, RUNS the real lean+z3, and feeds that seam — so in practice every proof claim
// ABSTAINed (the deferred stub). This module is that missing orchestration: given a covered claim + a
// tool CAPABILITY, it formalizes (informal -> Lean + the matching faithfulness query), mints both
// certificates from the real tools (or injected stubs), and routes them through routeProofCertifier so
// the claim lifts to OBSERVED — or honestly ABSTAINs (outside the ground-equation class / no capability)
// or WITHHOLDS fail-closed (z3 unknown / out-of-envelope), exactly as the atomic F2+F3 gate decides.
//
// CAPABILITY-GATED, HONESTY-LAW-PRESERVING. The OBSERVED lift is DETERMINISTIC out-of-model proof
// checking (the Lean kernel + bounded z3 faithfulness, both canary-re-run) — it never trusts a model, so
// it does NOT need the W3 autonomy capability token. It needs the TOOLS: absent an injected/real
// certifier bundle this seam ABSTAINs and spawns NOTHING (import-time + fast-gate safe — the tool
// producers do not spawn until their returned fn is invoked). buildCertifiersFromManifest() builds the
// real bundle from the pinned absolute paths (tool lane / a live run); the fast `node --test` gate
// injects deterministic stub certify/solve fns and never touches a tool.
//
// Tool-spawning orchestration lives HERE, deliberately OFF the verify-router "skeleton": the router keeps
// importing only the adjudication/lift functions, and this module composes the producers + the router.

import {
  formalizeEquation,
  certifyLean,
  createLeanCertify,
  createLeanRerun,
  LeanCertifierError,
} from './lean-certifier.mjs';
import { certifyFaithfulness, createZ3Solve } from './smt-faithfulness.mjs';
// B4 sole-resolve: production arm decision reads certifier only from frozen knobs
// (resolveRamanujanDepthKnobs / resolveRamanujanBand) — never env toggles, never freelanced true.
import {
  isCertifierArmed,
  resolveRamanujanBand,
  resolveRamanujanDepthKnobs,
} from './triage-band.mjs';

/** The default pinned faithfulness-battery count when the manifest omits it (matches tools.manifest.json). */
export const DEFAULT_PINNED_BATTERY_COUNT = 16;

/** A typed error so an auto-certifier wiring/usage bug is distinguishable from an honest ABSTAIN. */
export class ProofAutoCertifierError extends Error {
  constructor(message, extra = {}) {
    super(message);
    this.name = 'ProofAutoCertifierError';
    Object.assign(this, extra);
  }
}

/**
 * Build the REAL certifier bundle from the pinned manifest paths — the tool-lane / live capability.
 * Returns { certify, leanRerun, solve, z3Rerun, leanVersion, z3Version, pinnedDefaultCount }. The z3
 * `solve` (producer) and `z3Rerun` (canary) are INDEPENDENT createZ3Solve instances (a fresh spawn each),
 * so the canary re-run is genuinely independent of the producer run. Same for lean certify vs leanRerun.
 * Nothing spawns here — the returned fns spawn lean/z3 (by absolute path, no shell) only when invoked.
 */
export function buildCertifiersFromManifest(manifest, { exec, leanTimeoutMs, z3TimeoutMs } = {}) {
  const tools = manifest && manifest.tools;
  const lean = tools && tools.lean;
  const z3 = tools && tools.z3;
  if (!lean || typeof lean.path !== 'string') {
    throw new ProofAutoCertifierError('manifest.tools.lean.path is required to build the lean certifier');
  }
  if (!z3 || typeof z3.path !== 'string') {
    throw new ProofAutoCertifierError('manifest.tools.z3.path is required to build the z3 solver');
  }
  const leanOpts = exec ? { exec, ...(leanTimeoutMs ? { timeoutMs: leanTimeoutMs } : {}) } : (leanTimeoutMs ? { timeoutMs: leanTimeoutMs } : {});
  const z3Opts = exec ? { exec, ...(z3TimeoutMs ? { timeoutMs: z3TimeoutMs } : {}) } : (z3TimeoutMs ? { timeoutMs: z3TimeoutMs } : {});
  const battery = manifest && manifest.faithfulness_instance_battery;
  return {
    certify: createLeanCertify(lean.path, leanOpts),
    leanRerun: createLeanRerun(lean.path, leanOpts),
    solve: createZ3Solve(z3.path, z3Opts),
    z3Rerun: createZ3Solve(z3.path, z3Opts),
    leanVersion: typeof lean.version === 'string' && lean.version ? lean.version : 'lean',
    z3Version: typeof z3.version === 'string' && z3.version ? z3.version : 'z3',
    pinnedDefaultCount: battery && Number.isInteger(battery.default_count) ? battery.default_count : DEFAULT_PINNED_BATTERY_COUNT,
  };
}

/** Whether a claim is even eligible for the ground-equation translator (proof-bearing + a meta.equation). */
export function isCoveredProofClaim(claim) {
  return Boolean(
    claim &&
      claim.type === 'proof-bearing' &&
      claim.meta &&
      claim.meta.equation &&
      typeof claim.statement === 'string',
  );
}

/**
 * AUTO-CERTIFY a proof-bearing claim to OBSERVED via the real Lean+z3 certifier, then route it through the
 * router's OBSERVED seam so the ledger lift + honest stamp happen. Behavior:
 *   - NOT proof-bearing / no capability bundle -> delegate to router.routeProofCertifier with no proof
 *     (an honest ABSTAIN + out-of-model route; spawns NOTHING).
 *   - proof-bearing but OUTSIDE the ground-equation translator class (formalizeEquation throws) -> honest
 *     ABSTAIN + route (the mathlib follow-on; the claim stays CONJECTURAL, never a bare reject).
 *   - covered class -> formalize, mint leanRecord + smtRecord from the (real or stub) tools, and route:
 *     OBSERVED on a lean-exit-0 + faithful + canary-agree PASS; ABSTAIN on a lean reject / z3 unknown /
 *     out-of-envelope (fail-closed); FLAG on an unfaithful/forged/cross-claim artifact.
 *
 * @param {VerifyRouter} router  the verify-router (its routeProofCertifier does the lift + stamp)
 * @param {object} claim         the resolved claim snapshot (needs id + statement + meta.equation)
 * @param {object} [o]
 * @param {object} [o.certifiers] { certify, leanRerun, solve, z3Rerun, leanVersion, z3Version, pinnedDefaultCount }
 *                                (from buildCertifiersFromManifest, or injected stubs in the fast tier)
 * @param {object} [o.formalizeOpts]  passed to formalizeEquation ({ domain, batteryCount, seed, provenance })
 * @param {Readonly<{ depth: string, verifyArms: number, certifier: boolean }>} [o.knobs]
 *   Frozen knobs from resolveRamanujanDepthKnobs (production sole-resolve). When present,
 *   certifier spend arms only if knobs.certifier === true — never from env or freelanced true.
 * @param {object} [o.band]  resolveRamanujanBand result (uses band.resolved / band.knobs)
 * @param {string} [o.depth]  production depth pin → resolveRamanujanBand when knobs/band omitted
 * @param {object} [o.triageLock]  existing triage lock for production resolve
 * @param {object} [o.env]  env surface for production depth lock (FOUNDRY_TRIAGE_DEPTH / RAMANUJAN_DEPTH)
 * @returns {Promise<object>} the router result (verdict OBSERVED | ABSTAIN | FLAG, with the honest stamp)
 */
export async function autoCertifyProof(
  router,
  claim,
  {
    certifiers,
    formalizeOpts = {},
    knobs = null,
    band = null,
    depth = undefined,
    triageLock = undefined,
    env = undefined,
  } = {},
) {
  if (!router || typeof router.routeProofCertifier !== 'function') {
    throw new ProofAutoCertifierError('autoCertifyProof requires a VerifyRouter with routeProofCertifier');
  }
  const claimRef = claim && typeof claim.id === 'string' ? claim.id : claim;

  // B4 production arm: when band surface is in play, certifier decision is knobs-only
  // (resolveRamanujanDepthKnobs). Tier env alone cannot arm; LITE never spends.
  let frozen = knobs ?? band?.resolved ?? band?.knobs ?? null;
  if (
    frozen == null &&
    (depth != null ||
      triageLock != null ||
      (env &&
        typeof env === 'object' &&
        (env.FOUNDRY_TRIAGE_DEPTH || env.RAMANUJAN_DEPTH)))
  ) {
    const resolvedBand = resolveRamanujanBand({ depth, triageLock, env });
    frozen = resolvedBand.resolved;
  }
  if (frozen != null && !isCertifierArmed(frozen)) {
    // Locked LITE (or explicit certifier:false) — honest ABSTAIN, spawn nothing.
    return router.routeProofCertifier(claimRef, { knobs: frozen });
  }

  // No tool capability, or not a covered proof claim -> honest ABSTAIN via the router's deferred arm
  // (no proof supplied). This spawns nothing and preserves the "no silent pass" contract.
  if (!certifiers || typeof certifiers.certify !== 'function' || typeof certifiers.solve !== 'function') {
    return router.routeProofCertifier(claimRef, frozen != null ? { knobs: frozen } : {});
  }
  if (!isCoveredProofClaim(claim)) {
    return router.routeProofCertifier(claimRef, frozen != null ? { knobs: frozen } : {});
  }

  // FORMALIZE: informal statement + meta.equation -> Lean source + the matching faithfulness query.
  // A statement outside the ground-equation class throws LeanCertifierError -> honest ABSTAIN (mathlib
  // follow-on). Any OTHER error is a real wiring bug and propagates.
  let formal;
  try {
    formal = formalizeEquation(claim, formalizeOpts);
  } catch (e) {
    if (e instanceof LeanCertifierError) {
      return router.routeProofCertifier(claimRef, frozen != null ? { knobs: frozen } : {});
    }
    throw e;
  }

  // MINT the two certificates from the (real or stub) tools. certifyFaithfulness HARD-FAULTS (throws) on a
  // Claude-sourced / undersized battery — the §v2.2 integrity boundary — which we let propagate.
  const leanRecord = await certifyLean(
    { claim, leanSource: formal.leanSource, leanVersion: certifiers.leanVersion || 'lean' },
    { certify: certifiers.certify },
  );
  const smtRecord = await certifyFaithfulness(
    {
      claim,
      query: formal.faithfulness.query,
      battery: formal.faithfulness.battery,
      z3Version: certifiers.z3Version || 'z3',
      pinnedDefaultCount: certifiers.pinnedDefaultCount,
    },
    { solve: certifiers.solve },
  );

  // ROUTE through the OBSERVED seam: it re-runs lean+z3 via the canary (leanRerun/z3Rerun), adjudicates
  // the ATOMIC F2+F3 gate, and — only on a genuine PASS — lifts the claim to OBSERVED + writes the stamp.
  // Forward frozen knobs so the router never freelances certifier:true mid-call.
  return router.routeProofCertifier(claimRef, {
    proof: {
      leanRecord,
      smtRecord,
      leanRerun: certifiers.leanRerun,
      z3Rerun: certifiers.z3Rerun,
      pinnedDefaultCount: certifiers.pinnedDefaultCount,
    },
    knobs: frozen ?? undefined,
  });
}

export { isCertifierArmed, resolveRamanujanBand, resolveRamanujanDepthKnobs };
