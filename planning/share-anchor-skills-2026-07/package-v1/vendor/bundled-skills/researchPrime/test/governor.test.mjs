// test/governor.test.mjs — Wave 8 gate: GOVERNOR WIRING + INCLUSION-TEST ENFORCEMENT (Phase D).
//
// IMPLEMENTATION-PLAN Wave 8 done-when, each a concrete `node --test` assertion over the real
// bin/governor.mjs source (no vacuous GREEN):
//   - a LOW-stakes run fires ZERO Synthesizer/Judge/debate sub-agents (call-count 0 via the Wave-7
//     spy seam);
//   - a HIGH-stakes run fires call-count > 0 (the positive control);
//   - a zero-AXIS-finding round is provably skipped/demoted.
// Plus the supporting policy / tier-resolution / inclusion-test units the three rest on.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ADJUDICATION_TIER_FLOOR,
  HIGH_TIER_AGENTS,
  ZERO_AXIS_SKIP_STAMP,
  governorPolicy,
  resolveTier,
  axisServingFindings,
  isZeroAxisFindingRound,
  runGovernedRound,
  tallyFindings,
} from '../bin/governor.mjs';

// ── A scripted adjudication agent + an independent per-role tally (proves the seam is real) ──────────
function adjudicationAgent() {
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

// ── Review fixtures ─────────────────────────────────────────────────────────────────────────────────
// AXIS-serving + a cross-lineage CONFLICT (so debate is also eligible to fire at medium+).
const axisConflictReviews = () => [
  { reviewer: 'Skeptic', lineage: 'claude', findings: [{ topic: 'unsupported core claim', severity: 'MAJOR', traces_to_north_star: 'yes', criterion: 'crit-1', verdict: 'affirm' }] },
  { reviewer: 'Contrarian', lineage: 'gemini', findings: [{ topic: 'unsupported core claim', severity: 'MAJOR', traces_to_north_star: 'yes', criterion: 'crit-1', verdict: 'deny' }] },
];
// Findings exist but NONE traces to the North Star ⇒ all demoted ⇒ zero AXIS-serving findings.
const allDemotedReviews = () => [
  { reviewer: 'Skeptic', lineage: 'claude', findings: [{ topic: 'style nit out of scope', severity: 'MINOR', traces_to_north_star: 'no', verdict: 'affirm' }] },
];
// An EMPTY round: reviewers produced nothing (also zero AXIS-serving findings).
const emptyReviews = () => [{ reviewer: 'Skeptic', findings: [] }];

// ── supporting unit: the inclusion policy (which tier admits the high-tier agents) ───────────────────

test('governorPolicy: low EXCLUDES all high-tier agents; medium+ INCLUDES them (Synthesizer is medium+)', () => {
  assert.equal(ADJUDICATION_TIER_FLOOR, 'medium');
  assert.deepEqual(HIGH_TIER_AGENTS, ['synthesizer', 'judge', 'debate']);

  const low = governorPolicy('low');
  assert.deepEqual([low.include, low.synthesize, low.judge, low.debate], [false, false, false, false]);
  assert.match(low.reason, /EXCLUDED/);

  for (const tier of ['medium', 'high']) {
    const p = governorPolicy(tier);
    assert.deepEqual([p.include, p.synthesize, p.judge, p.debate], [true, true, true, true], `${tier} must include the high-tier agents`);
    assert.match(p.reason, /INCLUDED/);
  }

  assert.throws(() => governorPolicy('bogus'), /unknown governor tier/);
});

// ── supporting unit: tier resolution from a tier string OR a Wave-4 stakes vector (I6 floor) ─────────

test('resolveTier accepts a tier string AND adjudicates a stakes vector (irreversible ⇒ ≥ medium, I6)', () => {
  assert.equal(resolveTier('high'), 'high');
  assert.equal(resolveTier('low'), 'low');
  // The Wave-4 under-call guard flows through the governor: a declared-LOW but IRREVERSIBLE vector
  // resolves to ≥ medium — the author cannot under-declare to dodge the high-tier adjudication.
  assert.equal(resolveTier({ declared_stakes: 'low', reversibility: 'irreversible' }), 'medium');
  assert.throws(() => resolveTier('nope'), /unknown tier string/);
  assert.throws(() => resolveTier(42), /requires a governor tier/);
});

// ── supporting unit: the inclusion test (which findings serve the AXIS / North Star) ─────────────────

test('axisServingFindings / isZeroAxisFindingRound read the trio inclusion test (non-demoted = AXIS-serving)', () => {
  const axis = tallyFindings(axisConflictReviews());
  assert.equal(axisServingFindings(axis).length, 1, 'a North-Star-tracing finding serves the AXIS');
  assert.equal(isZeroAxisFindingRound(axis), false);

  const demoted = tallyFindings(allDemotedReviews());
  assert.equal(axisServingFindings(demoted).length, 0, 'a non-tracing finding is demoted ⇒ does not serve the AXIS');
  assert.equal(isZeroAxisFindingRound(demoted), true);

  const empty = tallyFindings(emptyReviews());
  assert.equal(isZeroAxisFindingRound(empty), true, 'an empty round is zero-AXIS-finding');
});

// ── DONE-WHEN (1): a LOW-stakes run fires ZERO Synthesizer/Judge/debate sub-agents ──────────────────

test('(done-when) a LOW-stakes run fires ZERO Synthesizer/Judge/debate sub-agents (spy seam = 0)', async () => {
  const { agent, seen } = adjudicationAgent();
  // AXIS-serving reviews with a real conflict — at medium+ this WOULD fire all three; at low it fires
  // none. So the zero is the STAKES gate, not an empty round (the round is NOT skipped).
  const res = await runGovernedRound({ agent, stakes: 'low', reviews: axisConflictReviews(), northStar: 'NS' });

  assert.equal(res.tier, 'low');
  assert.equal(res.skipped, false, 'the round has AXIS-serving findings ⇒ not skipped; the zero is the stakes gate');
  assert.deepEqual(res.counts, { synthesizer: 0, judge: 0, debate: 0 }, 'low stakes ⇒ zero high-tier sub-agent calls');
  // The caller's own injected agent independently witnessed zero high-tier calls.
  assert.equal(seen.synthesizer, 0);
  assert.equal(seen.judge, 0);
  assert.equal(seen.debate, 0);
});

// ── DONE-WHEN (2): a HIGH-stakes run fires call-count > 0 (the positive control) ────────────────────

test('(done-when) a HIGH-stakes run fires call-count > 0 (positive control)', async () => {
  const { agent, seen } = adjudicationAgent();
  const res = await runGovernedRound({ agent, stakes: 'high', reviews: axisConflictReviews(), northStar: 'NS' });

  assert.equal(res.tier, 'high');
  assert.equal(res.skipped, false);
  const total = res.counts.synthesizer + res.counts.judge + res.counts.debate;
  assert.ok(total > 0, `high stakes must fire > 0 high-tier sub-agents (got ${total})`);
  // Synthesizer + Judge always fire at medium+; debate fires because the reviews carry a cross-origin conflict.
  assert.equal(res.counts.synthesizer, 1);
  assert.equal(res.counts.judge, 1);
  assert.equal(res.counts.debate, 1, 'the cross-lineage affirm/deny conflict fires G9 debate exactly once');
  assert.deepEqual({ s: seen.synthesizer, j: seen.judge, d: seen.debate }, { s: 1, j: 1, d: 1 });
  // The real seams flowed through (not stubs).
  assert.equal(res.judgeVerdict.decision, 'NOT_CONVERGED');
  assert.equal(res.direction.kind, 'direction');

  // A MEDIUM-stakes run is also a positive control (Synthesizer is "medium+").
  const { agent: agent2 } = adjudicationAgent();
  const med = await runGovernedRound({ agent: agent2, stakes: 'medium', reviews: axisConflictReviews(), northStar: 'NS' });
  assert.ok(med.counts.synthesizer + med.counts.judge + med.counts.debate > 0, 'medium stakes also fires the high-tier agents');
});

// ── DONE-WHEN (3): a zero-AXIS-finding round is provably skipped/demoted ─────────────────────────────

test('(done-when) a zero-AXIS-finding round is SKIPPED/DEMOTED — even at HIGH stakes, with ZERO agent calls', async () => {
  // HIGH stakes (so the stakes gate would otherwise ADMIT the agents) but every finding fails the
  // inclusion test ⇒ the round is skipped: the high-tier adjudication provably never fires.
  const { agent, seen } = adjudicationAgent();
  const res = await runGovernedRound({ agent, stakes: 'high', reviews: allDemotedReviews(), northStar: 'NS' });

  assert.equal(res.tier, 'high', 'tier is high — so the SKIP is the inclusion test, not the stakes gate');
  assert.equal(res.skipped, true);
  assert.equal(res.demoted, true);
  assert.equal(res.axisFindingCount, 0);
  assert.equal(res.reason, ZERO_AXIS_SKIP_STAMP);
  assert.match(res.reason, /inclusion test/i);
  assert.deepEqual(res.counts, { synthesizer: 0, judge: 0, debate: 0 });
  // Provably skipped BEFORE any sub-agent could fire: the spy agent saw nothing at all.
  assert.deepEqual(seen, { synthesizer: 0, judge: 0, debate: 0, reviewer: 0, other: 0 });

  // An EMPTY round is skipped the same way.
  const { agent: agent2, seen: seen2 } = adjudicationAgent();
  const empty = await runGovernedRound({ agent: agent2, stakes: 'high', reviews: emptyReviews() });
  assert.equal(empty.skipped, true);
  assert.deepEqual(empty.counts, { synthesizer: 0, judge: 0, debate: 0 });
  assert.equal(seen2.synthesizer + seen2.judge + seen2.debate, 0);
});

// ── end-to-end: the Wave-4 stakes VECTOR drives inclusion through the governor wiring (I6) ───────────

test('a declared-LOW but IRREVERSIBLE stakes VECTOR resolves to ≥ medium ⇒ high-tier agents fire (I6, no under-call)', async () => {
  const { agent } = adjudicationAgent();
  const res = await runGovernedRound({
    agent,
    stakes: { declared_stakes: 'low', reversibility: 'irreversible' }, // author under-declared
    reviews: axisConflictReviews(),
    northStar: 'NS',
  });
  assert.equal(res.tier, 'medium', 'the irreversibility floor over-rode the low declaration (I6)');
  assert.ok(res.counts.synthesizer + res.counts.judge + res.counts.debate > 0, 'the adjudication ran because the adjudicated tier is medium, not the declared low');
});

// ── guards ───────────────────────────────────────────────────────────────────────────────────────────

test('runGovernedRound HALTs without an agent seam or a reviews[] array', async () => {
  await assert.rejects(() => runGovernedRound({ agent: null, stakes: 'high', reviews: [] }), /requires an agent/);
  await assert.rejects(() => runGovernedRound({ agent: async () => null, stakes: 'high', reviews: 'nope' }), /requires a reviews\[\] array/);
});
