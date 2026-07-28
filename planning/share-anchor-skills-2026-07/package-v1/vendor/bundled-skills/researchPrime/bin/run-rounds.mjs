#!/usr/bin/env node
// bin/run-rounds.mjs — THE canonical Phase-3 round driver (T9, 2026-07-11).
//
// Promoted from the root-level run-ramanujan-round.mjs (which every real run had to
// discover by archaeology — journal 0001 hand-rolled a ConPTY harness, the 2026-06-19
// run role-played the engine's rules in sub-agents instead of running the engine).
// This is the documented operator path; the old filename remains as a thin shim.
//
// Faithful ENGINE mode: fresh-context sub-agents produce the cognition (reviewer
// findings, Judge verdict, Synthesizer steer, debate); this driver replays those
// through the REAL trio gates (tallyFindings >=2-agree, gateOneQuorum independence,
// the honest convergence tracker incl. the T8 CLEAN path, the suspiciously-dry
// guard) and assembles the deliverable. No re-implemented gate logic.
//
// Usage:
//   node bin/run-rounds.mjs <runDir> [--max-rounds N]
//     <runDir> holds round-<N>-input.json files:
//       { round, northStar, stakes:{...}|tier,
//         reviews:[{reviewer,angle,lineage,findings:[{claim_id?,topic,severity,traces_to_north_star,message}]}],
//         adjudications:{ judge:{...}, synthesizer:{...}, debate:{...} } }   (replay mode)
//   RESEARCHPRIME_LIVE_ROUND=1  -> reviewer/debate/judge seats go LIVE to Gemini via agy
//     (5:1; agy down => honest HaltError, never Claude self-review).
//   --max-rounds (default 8, env RESEARCHPRIME_MAX_ROUNDS): the HARD round budget — at
//     the cap the run stops with an honest NOT-CONVERGED state file; it never loops
//     unbounded and never fabricates convergence.
//
// Outputs in <runDir>: round-<N>-result.json per round; DELIVERABLE-ENGINE.json on
// convergence (dry OR clean, stamped); RUN-STATE.json always (resume = add the next
// round-input and re-run — every paid result is on disk, nothing is discarded).

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  orchestrateRound,
  makeConvergenceTracker,
  assessConvergenceHonesty,
  countUnresolvedHighSeverity,
} from './round.mjs';
import { deriveGovernorContract } from './formal-governor.mjs';
import { assembleDeliverable } from './deliverable.mjs';
import { loadGate } from './gate-loader.mjs';
import { HaltError } from './trio-core/contract-core.mjs';
import {
  makeReachedFamilyTracker,
  instrumentRoundAgent,
  buildLiveRoundAgent,
  DEFAULT_ROUND_ROUTES,
  SINGLE_FAMILY_ROUTES,
} from './live-round-agent.mjs';

export async function runRounds(runDir, { maxRounds = null, env = process.env, log = console.log } = {}) {
  const started = new Date().toISOString();
  const t0 = Date.now();

  let governanceRecord;
  try {
    governanceRecord = loadGate(runDir);
  } catch (e) {
    if (e && (e.name === 'HaltError' || e instanceof Error)) {
      const haltRecord = {
        status: 'HALTED',
        reason: e.message,
        timestamp: new Date().toISOString()
      };
      fs.writeFileSync(path.join(runDir, 'HALT-RECORD.json'), JSON.stringify(haltRecord, null, 2));
    }
    throw e;
  }

  const allInputs = fs.readdirSync(runDir)
    .filter((f) => /^round-\d+-input\.json$/.test(f))
    .sort((a, b) => parseInt(a.match(/\d+/)[0]) - parseInt(b.match(/\d+/)[0]))
    .map((f) => JSON.parse(fs.readFileSync(path.join(runDir, f), 'utf8')));
  if (!allInputs.length) throw new Error(`no round-*-input.json found in ${runDir}`);

  const contract = governanceRecord.lockedGovernorOutput || deriveGovernorContract(allInputs[0]);
  const thresholds = contract.thresholds;
  const cap = contract.roundBudget;
  const tier = contract.tier;

  // The HARD budget: never process past the cap; say so loudly (no silent truncation).
  const inputs = allInputs.slice(0, cap);
  const capped = allInputs.length > inputs.length;
  if (capped) log(`!! round budget: processing ${inputs.length}/${allInputs.length} inputs (--max-rounds ${cap})`);

  function replayAgent(adj) {
    return async (_prompt, opts = {}) => {
      const role = opts.role || 'other';
      if (role === 'judge') return adj.judge ?? { decision: 'NOT_CONVERGED', reasons: [] };
      if (role === 'synthesizer') return adj.synthesizer ?? { lean: 'unknown', suggestions: [] };
      if (role === 'debate') return adj.debate ?? { survivor: null };
      return null;
    };
  }

  const tracker = makeConvergenceTracker({ N: thresholds.N });
  const priorBlockerIds = new Set();
  const roundResults = [];
  let roundsToDry = null;

  const reached = makeReachedFamilyTracker();
  const LIVE_ROUND = env.RESEARCHPRIME_LIVE_ROUND === '1';
  const liveAgent = LIVE_ROUND
    ? await buildLiveRoundAgent({ tracker: reached, env }) // prefs-aware (CODING/REVIEW_FAMILY)
    : null;
  if (LIVE_ROUND) {
    log('LIVE cross-family round: seats from coding/review family prefs (omit routes → ~/.anchor/model_prefs.json).');
  }

  for (const inp of inputs) {
    const agent = LIVE_ROUND
      ? liveAgent
      : instrumentRoundAgent({ agent: replayAgent(inp.adjudications ?? {}), routes: SINGLE_FAMILY_ROUTES, tracker: reached });
    const result = await orchestrateRound({
      agent,
      round: inp.round,
      northStar: inp.northStar,
      reviews: inp.reviews,
      priorBlockerIds: [...priorBlockerIds],
    });
    const obs = tracker.observe(result);
    for (const b of result.tally.blockers) priorBlockerIds.add(b.id);
    if (result.dry && !result.empty && roundsToDry == null) roundsToDry = obs.countedRounds;

    const summary = {
      round: result.round,
      verdict: result.tally.verdict,
      dry: result.dry,
      empty: result.empty,
      newBlockers: result.tally.newBlockers.map((b) => ({ id: b.id, severity: b.severity, agreement: b.agreement, message: b.message })),
      allBlockers: result.tally.blockers.map((b) => b.id),
      demoted: result.tally.demoted.map((d) => ({ id: d.id, message: d.message })),
      quorum: result.quorum,
      conflicts: result.conflicts,
      debateFired: result.debate?.fired ?? false,
      judgeVerdict: result.judgeVerdict,
      direction: result.direction,
      counts: result.counts,
      trackerState: obs,
    };
    roundResults.push(result);
    fs.writeFileSync(path.join(runDir, `round-${result.round}-result.json`), JSON.stringify(summary, null, 2));
    log(`round ${result.round}: ${result.tally.verdict} | dry=${result.dry} empty=${result.empty} | newBlockers=${result.tally.newBlockers.length} | dryStreak=${obs.dryStreak}/${thresholds.N} emptyStreak=${obs.emptyStreak} | converged=${obs.converged}${obs.mode ? ` (${obs.mode})` : ''}`);
    if (obs.converged) break; // convergence reached — no need to consume further inputs
  }

  const finalState = tracker.state();
  const convergence = {
    converged: finalState.converged,
    mode: finalState.mode,                       // 'dry' | 'clean' | null — never conflated
    stamp: finalState.stamp,                     // the explicit CLEAN stamp when mode==='clean'
    dryStreak: finalState.dryStreak,
    emptyStreak: finalState.emptyStreak,
    countedRounds: finalState.countedRounds,
    rounds: finalState.rounds,
    N: thresholds.N,
    roundBudget: cap,
    roundBudgetHit: capped && !finalState.converged,
  };

  const substrateFamilies = reached.families().length ? reached.families() : ['claude'];
  const finalRound = roundResults[roundResults.length - 1];
  const unresolvedHigh = countUnresolvedHighSeverity(finalRound.tally.findings);
  const honesty = assessConvergenceHonesty({
    stakesTier: tier,
    roundsToDry: roundsToDry ?? finalState.countedRounds,
    unresolvedHighSeverity: unresolvedHigh,
    substrateFamilies,
    thresholds,
  });

  log(`\nTIER=${tier} | convergence=${JSON.stringify(convergence)} | unresolvedHigh=${unresolvedHigh} | substrateFamilies=${JSON.stringify(substrateFamilies)}`);
  log(`HONESTY GUARD: ${JSON.stringify(honesty)}`);

  let deliverable = null;
  if (finalState.converged) {
    deliverable = assembleDeliverable({
      mode: 'engine',
      rounds: roundResults,
      convergence,
      calibration: null,
      substrateFamilies,
      northStar: inputs[0].northStar,
    });
    const out = { deliverable, convergence, honesty, tier, thresholds, unresolvedHigh };
    fs.writeFileSync(path.join(runDir, 'DELIVERABLE-ENGINE.json'), JSON.stringify(out, null, 2));
    log(`\nCONVERGED (${convergence.mode}). cross_model=${deliverable.cross_model} verified=${deliverable.verified}. Wrote DELIVERABLE-ENGINE.json`);
  } else {
    log(capped
      ? `\nROUND BUDGET HIT (${cap}) without convergence — honest stop; open blockers are in RUN-STATE.json (nothing discarded).`
      : `\nNOT converged yet — need dryStreak ${thresholds.N} (or ${thresholds.N + 1} consecutive clean rounds); add the next round-input after fixing blockers and re-run.`);
  }

  // RUN-STATE.json: the durable state — this file IS the resume mechanism (SKILL.md's
  // honest durability story: round inputs/results on disk, re-run to continue).
  const runState = {
    convergence, honesty, tier, thresholds, unresolvedHigh, substrateFamilies,
    openBlockers: [...priorBlockerIds],
    processedRounds: roundResults.map((r) => r.round),
  };
  fs.writeFileSync(path.join(runDir, 'RUN-STATE.json'), JSON.stringify(runState, null, 2));

  // Run capture for training (Skill Foundry AGENTS.md "Run capture") — best-effort.
  try {
    const skillDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
    const dir = path.join(skillDir, 'journal', 'runs');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `${started.replace(/[:.]/g, '-')}-${Math.abs(Date.now() % 100000)}.json`),
      JSON.stringify({
        skill: 'researchPrime', tier: LIVE_ROUND ? 'live-cross-family' : 'replay',
        started, ended: new Date().toISOString(),
        input: runDir, params: { maxRounds: cap, live: LIVE_ROUND, stakesTier: tier },
        output: finalState.converged ? path.join(runDir, 'DELIVERABLE-ENGINE.json') : path.join(runDir, 'RUN-STATE.json'),
        result: finalState.converged ? `converged (${convergence.mode})` : (capped ? 'round budget hit — honest stop' : 'not converged — awaiting next round'),
        cross_model: deliverable?.cross_model ?? (substrateFamilies.length > 1),
        models: substrateFamilies,
        duration_s: Math.round((Date.now() - t0) / 1000),
        journal_ref: null,
      }, null, 2) + '\n');
  } catch { /* capture is best-effort */ }

  return { convergence, honesty, tier, deliverable, runState };
}

// ---- CLI ----
function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(entry); } catch { return false; }
}
if (invokedDirectly()) {
  const argv = process.argv.slice(2);
  const runDir = argv.find((a) => !a.startsWith('--'));
  const mrIdx = argv.indexOf('--max-rounds');
  const maxRounds = mrIdx >= 0 ? Number(argv[mrIdx + 1]) : null;
  if (!runDir) { console.error('usage: node bin/run-rounds.mjs <runDir> [--max-rounds N]'); process.exit(2); }
  runRounds(runDir, { maxRounds }).catch((err) => {
    console.error(`run-rounds: ${err?.message ?? err}`);
    process.exit(1);
  });
}
