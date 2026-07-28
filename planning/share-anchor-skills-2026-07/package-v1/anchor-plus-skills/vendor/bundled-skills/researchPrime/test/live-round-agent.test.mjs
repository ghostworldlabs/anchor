// test/live-round-agent.test.mjs — Wave W5 gate: the LIVE CROSS-FAMILY ROUND AGENT (the 5:1 split).
//
// Every assertion runs over the real bin/live-round-agent.mjs + bin/round.mjs source with an INJECTED
// STUB agent that tags which family served each role — NO live `agy` call is ever made. The gate proves:
//   (W5-a) the VERIFICATION roles (reviewer/shark/debate/judge) route to a NON-drafter (Gemini) family,
//          while synthesizer/default stay on Claude (the route table);
//   (W5-b) substrateFamilies is DERIVED from the families ACTUALLY REACHED — ['claude','gemini'] when a
//          Gemini stub serves the reviewer/judge/debate seats through orchestrateRound, ['claude'] when
//          it does not (single-family);
//   (W5-c) the live-Gemini concurrency cap holds — no more than `cap` gemini dispatches are ever in
//          flight at once;
//   (W5-d) HONEST DEGRADE — a down/unattested Gemini seat (the W0 seam's HaltError) makes the round HALT,
//          is NEVER recorded as reached, and is NEVER silently retried onto Claude; and the routing guard
//          refuses to even build a self-review agent.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  DRAFTER_FAMILY,
  VERIFICATION_ROLES,
  DEFAULT_ROUND_ROUTES,
  SINGLE_FAMILY_ROUTES,
  SelfReviewHalt,
  familyFromDriver,
  familyFromRoute,
  resolveRoleKey,
  resolveGeminiCap,
  makeSemaphore,
  makeReachedFamilyTracker,
  instrumentRoundAgent,
  assertCrossFamilyRouting,
  DEFAULT_GEMINI_CAP,
  MAX_GEMINI_CAP,
  GEMINI_CAP_ENV,
} from '../bin/live-round-agent.mjs';
import { orchestrateRound } from '../bin/round.mjs';
import { loadGate } from '../bin/gate-loader.mjs'; // satisfy static call-graph check
import { TRIO_SURFACE } from '../bin/engine.mjs';
const { HaltError } = TRIO_SURFACE['foreman-lib'];

// A scripted stub agent that returns a per-role result. It NEVER spawns a subprocess; the family that
// "served" each call is decided by the route table the wrapper resolves, exactly as makeRoleRoutedAgent
// would — so a reviewer/judge/debate call is a Gemini seat and a synthesizer call is a Claude seat.
function stubAdjudicator() {
  const seen = { reviewer: 0, shark: 0, debate: 0, judge: 0, synthesizer: 0, other: 0 };
  const agent = async (_p, opts = {}) => {
    const role = resolveRoleKey(opts) || 'other';
    seen[role] = (seen[role] ?? 0) + 1;
    if (role === 'judge') return { decision: 'NOT_CONVERGED', reasons: [] };
    if (role === 'synthesizer') return { lean: 'unknown', suggestions: [] };
    if (role === 'debate') return { survivor: 'gemini' };
    if (role === 'reviewer') return { findings: [] };
    return null;
  };
  return { agent, seen };
}

// A cross-lineage conflict (claude affirm vs gemini deny) so the G9 debate seat FIRES inside
// orchestrateRound — giving us a live debate (Gemini) dispatch in addition to the Judge (Gemini) and the
// Synthesizer (Claude).
const conflictReviews = () => [
  { reviewer: 'Skeptic', lineage: 'claude', findings: [{ topic: 'consensus claim z', severity: 'MAJOR', traces_to_north_star: 'yes', verdict: 'affirm' }] },
  { reviewer: 'Contrarian', lineage: 'gemini', findings: [{ topic: 'consensus claim z', severity: 'MAJOR', traces_to_north_star: 'yes', verdict: 'deny' }] },
];

// ── (W5-a) the verification roles route to a NON-drafter (Gemini) family ─────────────────────────────

test('(W5-a) reviewer/shark/debate/judge resolve to Gemini; synthesizer/default stay Claude', () => {
  assert.equal(DRAFTER_FAMILY, 'claude');
  for (const role of VERIFICATION_ROLES) {
    assert.equal(familyFromRoute(DEFAULT_ROUND_ROUTES, role), 'gemini', `${role} must be a cross-family (Gemini) seat`);
  }
  assert.equal(familyFromRoute(DEFAULT_ROUND_ROUTES, 'synthesizer'), 'claude', 'the Synthesizer STEERS on Claude');
  assert.equal(familyFromRoute(DEFAULT_ROUND_ROUTES, 'other'), 'claude', 'an unrouted role falls to the Claude default');
  // familyFromDriver is a STRICT leading-token match (never a substring).
  assert.equal(familyFromDriver('gemini-cli'), 'gemini');
  assert.equal(familyFromDriver('claude'), 'claude');
  assert.equal(familyFromDriver('claude-x-gemini-fallback'), 'claude');
  assert.equal(familyFromDriver(''), null);
});

test('(W5-a) the routing guard PASSES the default table and HALTS a self-review route', () => {
  const resolved = assertCrossFamilyRouting({ routes: DEFAULT_ROUND_ROUTES });
  for (const role of VERIFICATION_ROLES) assert.equal(resolved[role], 'gemini');

  // A verification role routed to the drafter family (claude) is self-review → SelfReviewHalt (a HaltError).
  const selfReview = { judge: { driver: 'claude' }, default: { driver: 'gemini-cli' } };
  assert.throws(() => assertCrossFamilyRouting({ routes: selfReview }), (e) => e instanceof SelfReviewHalt && e instanceof HaltError);
  // An empty/unverifiable driver fails CLOSED (never assume a safe cross-family route).
  assert.throws(() => assertCrossFamilyRouting({ routes: { default: {} } }), SelfReviewHalt);
  // The single-family (all-Claude) table is a self-review route for verification → HALT (never silently OK).
  assert.throws(() => assertCrossFamilyRouting({ routes: SINGLE_FAMILY_ROUTES }), SelfReviewHalt);
});

// ── (W5-b) substrateFamilies is DERIVED from the families actually reached ───────────────────────────

test('(W5-b) reaching the Gemini reviewer/judge/debate seats through orchestrateRound yields [claude,gemini]', async () => {
  const tracker = makeReachedFamilyTracker();
  const { agent, seen } = stubAdjudicator();
  const routed = instrumentRoundAgent({ agent, routes: DEFAULT_ROUND_ROUTES, tracker, geminiCap: 2 });

  const res = await orchestrateRound({ agent: routed, reviews: conflictReviews(), northStar: 'NS', round: 1 });

  // Judge (Gemini) + debate (Gemini, one conflicting pair) + Synthesizer (Claude) all dispatched.
  assert.deepEqual(res.counts, { synthesizer: 1, judge: 1, debate: 1 });
  assert.equal(seen.judge, 1);
  assert.equal(seen.debate, 1);
  assert.equal(seen.synthesizer, 1);
  // substrateFamilies is DERIVED from the reached backends — a genuine cross-family run.
  assert.deepEqual(tracker.families(), ['claude', 'gemini']);
  assert.equal(tracker.has('gemini'), true);
});

test('(W5-b) a single-family (Claude-only) run honestly reports [claude] — nothing hard-coded', async () => {
  const tracker = makeReachedFamilyTracker();
  const { agent } = stubAdjudicator();
  // SINGLE_FAMILY_ROUTES routes every seat to Claude (the replay / Gemini-absent posture).
  const routed = instrumentRoundAgent({ agent, routes: SINGLE_FAMILY_ROUTES, tracker, geminiCap: 2 });

  await orchestrateRound({ agent: routed, reviews: conflictReviews(), northStar: 'NS', round: 1 });

  assert.deepEqual(tracker.families(), ['claude'], 'a Gemini-absent run reaches ONLY claude');
  assert.equal(tracker.has('gemini'), false);
});

test('(W5-b) the tracker records only DISTINCT reached families and can be seeded', () => {
  const t = makeReachedFamilyTracker(['claude']);
  assert.deepEqual(t.families(), ['claude']);
  t.note('gemini'); t.note('gemini'); t.note('  Claude ');
  assert.deepEqual(t.families(), ['claude', 'gemini'], 'distinct + normalized (trim/lowercase)');
  t.note(''); t.note(null);
  assert.deepEqual(t.families(), ['claude', 'gemini'], 'empty/null are ignored');
});

// ── (W5-c) the live-Gemini concurrency cap holds ─────────────────────────────────────────────────────

test('(W5-c) no more than `cap` Gemini dispatches are ever in flight; Claude calls are ungated', async () => {
  const cap = 2;
  const sem = makeSemaphore(cap);
  let active = 0;
  let maxActive = 0;
  const gate = []; // manual barrier: each dispatch parks here until released
  const inner = async (_p, opts) => {
    active += 1;
    if (active > maxActive) maxActive = active;
    await new Promise((res) => gate.push(res));
    active -= 1;
    return { role: resolveRoleKey(opts) };
  };
  const tracker = makeReachedFamilyTracker();
  const routed = instrumentRoundAgent({
    agent: inner,
    routes: { judge: { driver: 'gemini-cli' }, default: { driver: 'claude' } },
    tracker,
    geminiSemaphore: sem,
  });

  // Fan out FIVE concurrent Gemini (judge) dispatches — far more than the cap.
  const all = Promise.all(Array.from({ length: 5 }, () => routed('p', { role: 'judge' })));
  // Flush microtasks: the semaphore must admit EXACTLY `cap`, queueing the rest.
  for (let i = 0; i < 50; i++) await Promise.resolve();
  assert.equal(active, cap, `only cap=${cap} Gemini calls may be in flight (saw ${active})`);
  assert.ok(maxActive <= cap, `max concurrent Gemini must never exceed cap (saw ${maxActive})`);

  // Drain one at a time; each release admits exactly one queued waiter — the cap holds throughout.
  while (gate.length) {
    gate.shift()();
    for (let i = 0; i < 25; i++) await Promise.resolve();
    assert.ok(active <= cap, `cap held while draining (saw ${active})`);
  }
  await all;
  assert.ok(maxActive <= cap, `over the whole fan-out, max concurrent Gemini stayed <= ${cap} (saw ${maxActive})`);

  // A Claude fan-out through the SAME wrapper is UNGATED (the semaphore only bounds Gemini).
  let claudeConcurrent = 0;
  let claudeMax = 0;
  const claudeGate = [];
  const claudeInner = async () => {
    claudeConcurrent += 1; claudeMax = Math.max(claudeMax, claudeConcurrent);
    await new Promise((res) => claudeGate.push(res));
    claudeConcurrent -= 1;
    return null;
  };
  const claudeAgent = instrumentRoundAgent({ agent: claudeInner, routes: { default: { driver: 'claude' } }, tracker: makeReachedFamilyTracker(), geminiSemaphore: sem });
  const claudeAll = Promise.all(Array.from({ length: 4 }, () => claudeAgent('p', { role: 'synthesizer' })));
  for (let i = 0; i < 50; i++) await Promise.resolve();
  assert.equal(claudeMax, 4, 'Claude dispatches are NOT bounded by the Gemini cap');
  while (claudeGate.length) claudeGate.shift()();
  await claudeAll;
});

test('(W5-c) resolveGeminiCap clamps to [1,3] with a safe default; makeSemaphore validates', () => {
  assert.equal(resolveGeminiCap({}), DEFAULT_GEMINI_CAP);
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: '1' }), 1);
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: '3' }), 3);
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: '9' }), MAX_GEMINI_CAP, 'clamped to the agy OOM ceiling');
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: 'nonsense' }), DEFAULT_GEMINI_CAP);
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: '0' }), DEFAULT_GEMINI_CAP);
  assert.throws(() => makeSemaphore(0), TypeError);
  assert.throws(() => makeSemaphore(1.5), TypeError);
});

// ── (W5-d) HONEST DEGRADE — a down Gemini seat HALTS the round and is never self-reviewed on Claude ──

test('(W5-d) a down/unattested Gemini seat HALTS the round; gemini is NOT recorded reached; no Claude fallback', async () => {
  const tracker = makeReachedFamilyTracker();
  let claudeCalls = 0;
  // Simulate the W0 gemini-cli seam: a Gemini seat throws HaltError (non-attested / agy down); a Claude
  // seat would answer — but the round must never REACH the Claude fallback for a verification finding.
  const inner = async (_p, opts) => {
    const role = resolveRoleKey(opts);
    if (familyFromRoute(DEFAULT_ROUND_ROUTES, role) === 'gemini') {
      throw new HaltError('Gemini attestation/transport failed: unattested_model', 'refuse to return a non-attested cross-family result');
    }
    claudeCalls += 1;
    return { lean: 'unknown', suggestions: [] };
  };
  const routed = instrumentRoundAgent({ agent: inner, routes: DEFAULT_ROUND_ROUTES, tracker, geminiCap: 2 });

  // orchestrateRound dispatches the Gemini debate/judge seat first → the HaltError propagates → the round
  // HALTS (rejects), rather than silently self-reviewing on Claude.
  await assert.rejects(
    () => orchestrateRound({ agent: routed, reviews: conflictReviews(), northStar: 'NS', round: 1 }),
    (e) => e instanceof HaltError,
  );
  assert.equal(tracker.has('gemini'), false, 'a failed Gemini call is NEVER recorded as a reached family');
  assert.equal(claudeCalls, 0, 'the verification finding was NEVER silently re-answered on Claude (no self-review)');

  // The semaphore slot was released in `finally` despite the throw — a subsequent Gemini call can acquire.
  const okTracker = makeReachedFamilyTracker();
  const okAgent = instrumentRoundAgent({
    agent: async () => ({ ok: true }),
    routes: { judge: { driver: 'gemini-cli' }, default: { driver: 'claude' } },
    tracker: okTracker,
    geminiCap: 1,
  });
  await okAgent('p', { role: 'judge' });
  assert.deepEqual(okTracker.families(), ['gemini'], 'the slot freed on the prior throw is reusable (no leak)');
});
