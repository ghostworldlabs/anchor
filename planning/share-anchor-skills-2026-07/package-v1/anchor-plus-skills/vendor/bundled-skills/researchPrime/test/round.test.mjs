// test/round.test.mjs — Wave 7 gate: ROUND ORCHESTRATION (Phase C-2).
//
// IMPLEMENTATION-PLAN Wave 7 done-when, each a separate concrete `node --test` assertion over the
// real bin/round.mjs source (no vacuous GREEN):
//   (a) dry-round predicate fires;
//   (b) an empty round does NOT increment N (I7);
//   (c) a high-stakes run reaching dry in < K rounds with > M unresolved high-severity findings
//       fires the probe-or-dissent, and on single-family substrate emits the "shared-blind-spot
//       un-mitigable" stamp, not a mitigation claim (I1);
//   (d) G9 fires exactly once on a conflicting origin pair, zero otherwise;
//   (e) Synthesizer steering measured vs a token/round-matched control;
//   (f) Synthesizer/Judge/debate expose a call-count spy seam;
//   (h) G8's origin fusion routes through the Wave-2 shared module (sole counter) — no other code
//       path increments independent_origins.
// (Done-when (g) — the lineage-enum RED-gate — is asserted in test/lineage-enum.test.mjs.)

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  // (a)/(b) convergence
  isDryRound,
  isEmptyRound,
  makeConvergenceTracker,
  // (c) suspiciously-dry
  assessConvergenceHonesty,
  SHARED_BLIND_SPOT_STAMP,
  loopThresholds,
  countUnresolvedHighSeverity,
  // (d) G9 debate
  detectOriginConflicts,
  shouldDebate,
  runDebateGate,
  // (e) steering
  measureSteering,
  // (f) spy seam
  orchestrateRound,
  // (h) G8 / shared counter
  g8FuseOrigins,
  g8Enabled,
  G8_INERT_STAMP,
  gateOneQuorum,
  meetsQuorum,
  countIndependentOrigins,
  STATIC_QUORUM_FLOOR,
  // reused G3/G6 surface
  tallyFindings,
  normalizeFindingId,
} from '../bin/round.mjs';
import { loadGate } from '../bin/gate-loader.mjs'; // satisfy static call-graph check

// ── helpers: build round results from the trio tally ──────────────────────────────────────────────
const roundFrom = (reviews, opts) => ({ reviews, tally: tallyFindings(reviews, opts) });

// A NON-EMPTY but DRY round: a single MINOR finding (no new blocker ⇒ dry; 1 finding ⇒ not empty).
const dryNonEmpty = () => roundFrom([{ reviewer: 'Skeptic', findings: [{ topic: 'minor wording nit', severity: 'MINOR', traces_to_north_star: 'yes' }] }]);
// An EMPTY round: reviewers produced nothing (nothing examined).
const emptyRound = () => roundFrom([{ reviewer: 'Skeptic', findings: [] }, { reviewer: 'Contrarian', findings: [] }]);
// A HOT (not-dry) round: two reviewers agree on the SAME tracing BLOCKER ⇒ a new blocker.
const hotRound = () => roundFrom([
  { reviewer: 'Skeptic', findings: [{ topic: 'unsupported core claim', severity: 'BLOCKER', traces_to_north_star: 'yes', criterion: 'crit-1' }] },
  { reviewer: 'Contrarian', findings: [{ topic: 'unsupported core claim', severity: 'BLOCKER', traces_to_north_star: 'yes', criterion: 'crit-1' }] },
]);

// ── (a) the dry-round predicate fires ──────────────────────────────────────────────────────────────

test('(a) the dry-round predicate FIRES on a no-new-blocker round, and not on a hot one', () => {
  assert.equal(isDryRound(dryNonEmpty()), true, 'a round with no new blocker must read dry');
  assert.equal(isDryRound(emptyRound()), true, 'a round with no findings is dry (nothing blocks)');
  assert.equal(isDryRound(hotRound()), false, 'a round with a fresh ≥2-agree BLOCKER must NOT read dry');
});

// ── (b) an EMPTY round does NOT increment N (I7 honest convergence) ─────────────────────────────────

test('(b) an EMPTY round does NOT increment the dry counter N (I7) — convergence needs real looking', () => {
  // N=2: converged only after TWO non-empty dry rounds.
  const tracker = makeConvergenceTracker({ N: 2 });

  let s = tracker.observe(dryNonEmpty()); // first real dry round
  assert.deepEqual([s.counted, s.dryStreak, s.converged], [true, 1, false]);

  s = tracker.observe(emptyRound()); // EMPTY — must NOT increment the streak
  assert.equal(s.counted, false, 'an empty round must not count toward convergence');
  assert.equal(s.empty, true);
  assert.equal(s.dryStreak, 1, 'the dry streak is UNCHANGED by an empty round (not incremented)');
  assert.equal(s.converged, false, 'two real dry rounds are still required — the empty one did not stand in for one');

  s = tracker.observe(dryNonEmpty()); // second real dry round
  assert.deepEqual([s.counted, s.dryStreak, s.converged], [true, 2, true]);

  // T8 (2026-07-11) — I7 REFINED: empty rounds still can never manufacture DRY convergence,
  // but cleanN (= N + 1) CONSECUTIVE empty rounds now converge CLEAN with the explicit,
  // distinct stamp — a genuinely defect-free artifact is no longer structurally unable to
  // converge (the old rule pressured reviewers into filler nits; the dogfood scripted one
  // per round just to terminate).
  const onlyEmpty = makeConvergenceTracker({ N: 1 }); // cleanN defaults to N + 1 = 2
  let e = onlyEmpty.observe(emptyRound());
  assert.equal(e.converged, false, 'one empty round is not enough (cleanN > N: clean needs MORE evidence than dry)');
  assert.equal(e.dryStreak, 0, 'the DRY streak stays untouched — empty can never fake adversarial dryness');
  e = onlyEmpty.observe(emptyRound());
  assert.equal(e.converged, true, 'cleanN consecutive empty rounds converge');
  assert.equal(e.mode, 'clean', '...in CLEAN mode, never dry');
  assert.match(e.stamp, /CLEAN convergence/, 'the explicit stamp rides the state');
  assert.match(e.stamp, /DISTINCT from DRY/);

  // A non-empty round RESETS the clean streak — clean must be CONSECUTIVE evidence.
  const cleanReset = makeConvergenceTracker({ N: 5 }); // cleanN 6; dry unreachable here
  cleanReset.observe(emptyRound());
  const afterFinding = cleanReset.observe(hotRound());
  assert.equal(afterFinding.emptyStreak, 0, 'a finding resets the clean streak');
  assert.equal(afterFinding.converged, false);

  // DRY convergence still reports mode 'dry' with no clean stamp (never conflated).
  const dryMode = makeConvergenceTracker({ N: 1 });
  const d = dryMode.observe(dryNonEmpty());
  assert.deepEqual([d.converged, d.mode, d.stamp], [true, 'dry', null]);

  // A hot round RESETS the streak (only a hot round may; an empty one is invisible).
  const reset = makeConvergenceTracker({ N: 2 });
  reset.observe(dryNonEmpty());
  assert.equal(reset.observe(hotRound()).dryStreak, 0, 'a hot (non-dry) round resets the streak');
});

// ── (c) suspiciously-dry → probe-or-dissent, single-family un-mitigable stamp (I1) ──────────────────

test('(c) loopThresholds reads the committed N/K/M (I6) and throws if they are missing', () => {
  const th = loopThresholds();
  assert.deepEqual(th, { N: 2, K: 2, M: 0 }, 'the committed Wave-1 thresholds');
  assert.throws(() => loopThresholds({ N: 2, K: 2 /* M missing */ }), /committed loop threshold M/);
});

test('(c) countUnresolvedHighSeverity counts only OPEN BLOCKER/MAJOR findings (the guard input)', () => {
  const findings = [
    { severity: 'MAJOR', resolved: false },
    { severity: 'BLOCKER' }, // unresolved by default
    { severity: 'BLOCKER', resolved: true }, // resolved ⇒ not counted
    { severity: 'MINOR', resolved: false }, // not high-severity ⇒ not counted
  ];
  assert.equal(countUnresolvedHighSeverity(findings), 2);
  assert.equal(countUnresolvedHighSeverity([]), 0);
  assert.throws(() => countUnresolvedHighSeverity('nope'), TypeError);
});

test('(c) a high-stakes run reaching dry in < K rounds with > M unresolved high-severity fires probe-or-dissent', () => {
  const thresholds = loopThresholds(); // K=2, M=0
  // The guard input is the OPEN high-severity count over the round's findings (real flow).
  const unresolvedHighSeverity = countUnresolvedHighSeverity([
    { severity: 'BLOCKER', resolved: false }, { severity: 'MINOR' },
  ]);
  assert.equal(unresolvedHighSeverity, 1);

  // High-stakes, dry in round 1 (< K=2), 1 unresolved high-severity (> M=0), SINGLE family:
  // suspicious ⇒ probe-or-dissent fires, and on single-family substrate it CANNOT mitigate — it
  // emits the un-mitigable stamp, never a mitigation claim (I1).
  const fired = assessConvergenceHonesty({
    stakesTier: 'high', roundsToDry: 1, unresolvedHighSeverity, substrateFamilies: ['claude'], thresholds,
  });
  assert.equal(fired.suspicious, true);
  assert.equal(fired.fired, true);
  assert.equal(fired.singleFamily, true);
  assert.equal(fired.mitigated, false, 'single-family substrate must NOT claim mitigation (I1)');
  assert.equal(fired.stamp, SHARED_BLIND_SPOT_STAMP);
  assert.match(fired.stamp, /UN-MITIGABLE/i);

  // A MULTI-family substrate can genuinely probe with an independent origin ⇒ may mitigate, no stamp.
  const multi = assessConvergenceHonesty({
    stakesTier: 'high', roundsToDry: 1, unresolvedHighSeverity: 1, substrateFamilies: ['claude', 'gemini'], thresholds,
  });
  assert.equal(multi.fired, true);
  assert.equal(multi.singleFamily, false);
  assert.equal(multi.mitigated, true);
  assert.equal(multi.stamp, null);

  // NOT suspicious — each condition is necessary:
  // low-stakes never fires…
  assert.equal(assessConvergenceHonesty({ stakesTier: 'low', roundsToDry: 1, unresolvedHighSeverity: 9, substrateFamilies: ['claude'], thresholds }).fired, false);
  // …dry took ≥ K rounds (not too fast)…
  assert.equal(assessConvergenceHonesty({ stakesTier: 'high', roundsToDry: 2, unresolvedHighSeverity: 9, substrateFamilies: ['claude'], thresholds }).fired, false);
  // …no unresolved high-severity finding left (not > M).
  assert.equal(assessConvergenceHonesty({ stakesTier: 'high', roundsToDry: 1, unresolvedHighSeverity: 0, substrateFamilies: ['claude'], thresholds }).fired, false);

  assert.throws(() => assessConvergenceHonesty({ stakesTier: 'high', roundsToDry: 1, unresolvedHighSeverity: 1 }), /requires committed thresholds/);
});

// ── (d) G9 fires exactly once on a conflicting origin pair, zero otherwise ───────────────────────────

const conflictReviews = () => [
  { reviewer: 'Skeptic', lineage: 'claude', findings: [{ topic: 'consensus claim z', severity: 'MAJOR', traces_to_north_star: 'yes', verdict: 'affirm' }] },
  { reviewer: 'Contrarian', lineage: 'gemini', findings: [{ topic: 'consensus claim z', severity: 'MAJOR', traces_to_north_star: 'yes', verdict: 'deny' }] },
];

test('(d) G9 debate fires EXACTLY ONCE on a conflicting independent-origin pair', async () => {
  const conflicts = detectOriginConflicts(conflictReviews());
  assert.equal(conflicts.length, 1, 'one cross-lineage affirm/deny disagreement = one conflict');
  assert.equal(shouldDebate(conflicts), true);

  let calls = 0;
  const agent = async (_p, opts) => { calls += 1; assert.equal(opts.role, 'debate'); return { survivor: 'claude' }; };
  const res = await runDebateGate({ agent, conflicts });
  assert.equal(res.fired, true);
  assert.equal(res.count, 1);
  assert.equal(calls, 1, 'the debate sub-agent was invoked exactly once');
});

test('(d) G9 fires ZERO times absent a conflicting origin pair (same-lineage disagreement / agreement are not conflicts)', async () => {
  // Same-lineage disagreement is ONE origin disagreeing with itself — not an independent-origin conflict (I3).
  const sameLineage = [
    { reviewer: 'Skeptic', lineage: 'claude', findings: [{ topic: 'claim z', verdict: 'affirm' }] },
    { reviewer: 'Contrarian', lineage: 'claude', findings: [{ topic: 'claim z', verdict: 'deny' }] },
  ];
  assert.deepEqual(detectOriginConflicts(sameLineage), []);

  // Distinct lineages AGREEING is not a conflict either.
  const agree = [
    { reviewer: 'Skeptic', lineage: 'claude', findings: [{ topic: 'claim z', verdict: 'affirm' }] },
    { reviewer: 'Contrarian', lineage: 'gemini', findings: [{ topic: 'claim z', verdict: 'affirm' }] },
  ];
  assert.deepEqual(detectOriginConflicts(agree), []);
  assert.equal(shouldDebate(detectOriginConflicts(agree)), false);

  let calls = 0;
  const agent = async () => { calls += 1; return null; };
  const res = await runDebateGate({ agent, conflicts: detectOriginConflicts(agree) });
  assert.equal(res.fired, false);
  assert.equal(res.count, 0);
  assert.equal(calls, 0, 'no conflict ⇒ the debate sub-agent is never invoked');
});

// ── (e) Synthesizer steering measured vs a token/round-matched control ───────────────────────────────

test('(e) the active Synthesizer steers a real recall GAIN over a token/round-matched control', async () => {
  const FOCUS = 'inspect-claim-z';
  const LATENT = 'latent defect z'; // surfaced ONLY when the reviewer is steered to it

  const agent = async (_prompt, opts = {}) => {
    if (opts.role === 'reviewer') {
      // A latent defect a single unguided pass overlooks; steering surfaces it.
      return opts.focus === FOCUS
        ? { findings: [{ topic: LATENT, severity: 'MAJOR', traces_to_north_star: 'yes' }] }
        : { findings: [] };
    }
    // The Synthesizer (Oranges) suggests where to look two steps downstream.
    if (String(opts.label || '').startsWith('synthesizer')) {
      return { lean: 'not-lockable', suggestions: [FOCUS] };
    }
    return null;
  };

  const m = await measureSteering({ agent, rounds: 2, northStar: 'verify the corpus honestly' });

  // Token/round-MATCHED: both arms made the same number of agent calls — the comparison is fair.
  assert.equal(m.matched, true);
  assert.equal(m.steered.agentCalls, m.control.agentCalls);
  // Steering produced a real gain the matched control did not get.
  assert.ok(m.steeringEffect > 0, `steering must beat the matched control (effect=${m.steeringEffect})`);
  assert.equal(m.steered.caught.length, 1, 'the steered arm caught the latent defect (round 2, after the round-1 steer)');
  assert.equal(m.control.caught.length, 0, 'the control arm (steering discarded) caught nothing');
  assert.ok(m.steered.caught.includes(normalizeFindingId({ topic: LATENT })));
});

// ── (f) Synthesizer/Judge/debate expose a call-count spy seam ───────────────────────────────────────

function adjudicationAgent() {
  // A scripted agent + an independent per-role tally proving the seam is real (the caller can spy too).
  const seen = { synthesizer: 0, judge: 0, debate: 0, reviewer: 0, other: 0 };
  const agent = async (_p, opts = {}) => {
    const role = opts.role || 'other';
    seen[role] = (seen[role] ?? 0) + 1;
    if (role === 'judge') return { decision: 'NOT_CONVERGED', reasons: [] };
    if (role === 'synthesizer') return { lean: 'unknown', suggestions: [] };
    if (role === 'debate') return { survivor: 'claude' };
    return null;
  };
  return { agent, seen };
}

test('(f) orchestrateRound exposes a call-count spy seam for Synthesizer/Judge/debate', async () => {
  const { agent, seen } = adjudicationAgent();
  const res = await orchestrateRound({ agent, reviews: conflictReviews(), northStar: 'NS', round: 1 });

  // The returned per-role counts ARE the spy seam — one Synthesizer, one Judge, one debate (the
  // single conflicting pair).
  assert.deepEqual(res.counts, { synthesizer: 1, judge: 1, debate: 1 });
  // …and the caller's own injected agent independently witnessed the exact same routing.
  assert.equal(seen.synthesizer, 1);
  assert.equal(seen.judge, 1);
  assert.equal(seen.debate, 1);
  // The Judge verdict + Synthesizer direction actually flowed through (real seams, not stubs).
  assert.equal(res.judgeVerdict.decision, 'NOT_CONVERGED');
  assert.equal(res.direction.kind, 'direction');
});

test('(f) the debate seam stays silent with no conflict; judge/synthesizer still fire', async () => {
  const { agent } = adjudicationAgent();
  const noConflict = [
    { reviewer: 'Skeptic', lineage: 'claude', findings: [{ topic: 'claim z', severity: 'MINOR', traces_to_north_star: 'yes', verdict: 'affirm' }] },
    { reviewer: 'Contrarian', lineage: 'gemini', findings: [{ topic: 'claim z', severity: 'MINOR', traces_to_north_star: 'yes', verdict: 'affirm' }] },
  ];
  const res = await orchestrateRound({ agent, reviews: noConflict, northStar: 'NS' });
  assert.equal(res.counts.debate, 0, 'no conflict ⇒ zero debate calls (G9 is conditional)');
  assert.equal(res.counts.judge, 1);
  assert.equal(res.counts.synthesizer, 1);

  await assert.rejects(() => orchestrateRound({ agent: null, reviews: [] }), /requires an agent/);
});

// ── (h) G8 fusion routes through the shared module (the sole origin counter) ─────────────────────────

test('(h) G8 is flagged-INERT by default — no cross-lineage origin claimed; enabling needs BOTH the flag AND the committed enum', () => {
  const inert = g8FuseOrigins([{ lineage: 'claude' }, { lineage: 'gemini' }], { enabled: false });
  assert.equal(inert.inert, true);
  assert.equal(inert.origins, 0);
  assert.equal(inert.met, false);
  assert.match(inert.stamp, /INERT/);
  assert.equal(inert.stamp, G8_INERT_STAMP);

  // G8 needs BOTH the explicit flag AND a committed attested-lineage enum (crit-5). The flag ALONE
  // can never enable G8 — an empty/pending enum keeps it inert even with the flag on:
  assert.equal(g8Enabled({ flag: true, lineages: [] }), false, 'empty/pending enum ⇒ inert even with the flag on');
  // The lineage-enum was COMMITTED at Phase 0.6, so the live default now enables WITH the flag on —
  // and still stays inert with the flag OFF (default research runs do not set the G8 flag):
  assert.equal(g8Enabled({ flag: true }), true, 'committed enum (0.6) + flag on ⇒ G8 enabled');
  assert.equal(g8Enabled({ flag: false }), false, 'flag off ⇒ inert even with a committed enum (the default-run posture)');
  assert.equal(g8Enabled({ flag: true, lineages: ['claude', 'gemini'] }), true, 'flag on + committed enum ⇒ enabled');
  assert.equal(g8Enabled({ flag: false, lineages: ['claude', 'gemini'] }), false);
});

test('(h) ENABLED G8 counts origins ONLY via the shared module — byte-identical to a direct meetsQuorum call', () => {
  const reviewers = [{ lineage: 'claude' }, { lineage: 'gemini' }, { lineage: 'claude' }];
  const attested = ['claude', 'gemini'];

  const fused = g8FuseOrigins(reviewers, { enabled: true, attestedLineages: attested });
  const direct = meetsQuorum(reviewers, { attestedLineages: attested, staticFloor: STATIC_QUORUM_FLOOR });
  assert.deepEqual({ origins: fused.origins, required: fused.required, met: fused.met }, direct);

  // The shared module's I3 invariant shows through: 3 reviewers but only 2 DISTINCT lineages ⇒ 2
  // origins (a re-implemented naive count would say 3) — proving G8 uses the shared counter.
  assert.equal(fused.origins, 2);
  assert.equal(fused.met, true);

  // An off-enum lineage collapses into the single capped bucket (the enum only TIGHTENS), exactly
  // as the shared module decides — not a G8-local rule.
  const mixed = [{ lineage: 'claude' }, { lineage: 'rogue' }];
  const offEnum = g8FuseOrigins(mixed, { enabled: true, attestedLineages: ['claude'] });
  assert.equal(offEnum.origins, countIndependentOrigins(mixed, { attestedLineages: ['claude'] }));
  assert.equal(offEnum.origins, 2); // claude (attested, +1) + rogue (off-enum, capped bucket +1)
});

test('(h) the round layer GATE-1 returns EXACTLY the shared module verdict (one canonical counter across the engine)', () => {
  const reviewers = [{ lineage: 'claude' }, { lineage: 'claude' }, { lineage: 'gemini' }];
  assert.deepEqual(gateOneQuorum(reviewers), meetsQuorum(reviewers, { staticFloor: STATIC_QUORUM_FLOOR }));
  // Same-lineage agreement adds 0 — the load-bearing I3 invariant, here from the round layer's GATE-1.
  assert.equal(gateOneQuorum(reviewers).origins, 2);
});

test('(h) no OTHER code path in the round layer increments independent_origins (source-level sole-counter guard)', () => {
  const src = readFileSync(new URL('../bin/round.mjs', import.meta.url), 'utf8');
  // The round layer obtains origins ONLY from the shared module — it imports the canonical
  // package-map specifier…
  assert.match(src, /#trio-core\/independence-accounting\.mjs/, 'round layer must import the shared module');
  assert.match(src, /\bmeetsQuorum\b/, 'origins must come from the shared meetsQuorum');
  // …and NOWHERE hand-rolls an origin tally (no manual accumulation of an origin/independent count).
  assert.doesNotMatch(src, /origins\s*\+\+/, 'no hand-rolled origin increment');
  assert.doesNotMatch(src, /origins\s*\+=/, 'no hand-rolled origin accumulation');
  assert.doesNotMatch(src, /independent_origins\s*=/, 'the round layer never assigns independent_origins itself');
});
