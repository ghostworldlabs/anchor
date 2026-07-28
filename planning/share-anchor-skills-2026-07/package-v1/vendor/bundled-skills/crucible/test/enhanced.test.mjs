// test/enhanced.test.mjs — Wave W6 gate: the CROSS-FAMILY verification seam (the 5:1 split).
//
// bin/enhanced.mjs was RETIRED in W6 from a competing API-key MODEL_REGISTRY path (hardcoded
// `gemini-deep-think`, GEMINI_API_KEY/spawnSync) into a thin shim over the shared trio role
// router (makeRoleRoutedAgent) + the gemini-cli TRIO_TIER ladder. Every assertion here runs over
// the REAL bin/enhanced.mjs + bin/shark-tank.mjs source with an INJECTED STUB agent that tags
// which family serves each role — NO live `agy` call is ever made. The gate proves:
//   (W6-a) the VERIFICATION seats (shark / judge) route to a NON-drafter (Gemini) family, while
//          synthesizer / drafter / default stay on Claude (the route table + the routing guard);
//   (W6-b) the reached-family provenance is DERIVED from the seats actually dispatched — including
//          through a REAL runSharkTank round — never a hardcoded list;
//   (W6-c) the live-Gemini concurrency cap holds (≤ cap in flight; Claude ungated);
//   (W6-d) HONEST DEGRADE — a down/unattested Gemini seat (a HaltError) makes the call HALT, is
//          NEVER recorded as reached, and is NEVER silently retried onto Claude (no self-review);
//   (W6-e) the retired module NO LONGER provisions a hardcoded / API-key cross-model path.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { HaltError } from '../bin/crucible-lib.mjs';
import { runSharkTank } from '../bin/shark-tank.mjs';
import * as enhanced from '../bin/enhanced.mjs';
import {
  DRAFTER_FAMILY,
  VERIFICATION_ROLES,
  DEFAULT_CRUCIBLE_ROUTES,
  SINGLE_FAMILY_ROUTES,
  SelfReviewHalt,
  familyFromDriver,
  familyFromRoute,
  resolveRoleKey,
  resolveGeminiCap,
  makeSemaphore,
  makeReachedFamilyTracker,
  instrumentCrucibleAgent,
  assertCrossFamilyRouting,
  DEFAULT_GEMINI_CAP,
  MAX_GEMINI_CAP,
  GEMINI_CAP_ENV,
} from '../bin/enhanced.mjs';

// ── (W6-a) the verification seats route to a NON-drafter (Gemini) family ──────────────────────────────

test('(W6-a) shark/judge resolve to Gemini; synthesizer/drafter/default stay Claude', () => {
  assert.equal(DRAFTER_FAMILY, 'claude');
  assert.deepEqual([...VERIFICATION_ROLES], ['shark', 'judge']);
  for (const role of VERIFICATION_ROLES) {
    assert.equal(familyFromRoute(DEFAULT_CRUCIBLE_ROUTES, role), 'gemini', `${role} must be a cross-family (Gemini) seat`);
  }
  assert.equal(familyFromRoute(DEFAULT_CRUCIBLE_ROUTES, 'synthesizer'), 'claude', 'the Synthesizer STEERS on Claude');
  // Drafter / stage-author roles have no explicit route → fall to the Claude default.
  assert.equal(familyFromRoute(DEFAULT_CRUCIBLE_ROUTES, 'stage0'), 'claude', 'stage authoring stays Claude');
  assert.equal(familyFromRoute(DEFAULT_CRUCIBLE_ROUTES, 'stage1'), 'claude');
  assert.equal(familyFromRoute(DEFAULT_CRUCIBLE_ROUTES, 'stage2'), 'claude');
  assert.equal(familyFromRoute(DEFAULT_CRUCIBLE_ROUTES, 'other'), 'claude', 'an unrouted role falls to the Claude default');
  // familyFromDriver is a STRICT leading-token match (never a substring).
  assert.equal(familyFromDriver('gemini-cli'), 'gemini');
  assert.equal(familyFromDriver('claude'), 'claude');
  assert.equal(familyFromDriver('claude-x-gemini-fallback'), 'claude');
  assert.equal(familyFromDriver(''), null);
  // resolveRoleKey mirrors makeRoleRoutedAgent: opts.role wins, else the label prefix.
  assert.equal(resolveRoleKey({ role: 'shark' }), 'shark');
  assert.equal(resolveRoleKey({ label: 'judge:r0:model' }), 'judge');
  assert.equal(resolveRoleKey({ label: 'stage1:phased-plan' }), 'stage1');
});

test('(W6-a) the routing guard PASSES the default table and HALTS a self-review route', () => {
  const resolved = assertCrossFamilyRouting({ routes: DEFAULT_CRUCIBLE_ROUTES });
  for (const role of VERIFICATION_ROLES) assert.equal(resolved[role], 'gemini');

  // A verification role routed to the drafter family (claude) is self-review → SelfReviewHalt (a HaltError).
  const selfReview = { judge: { driver: 'claude' }, default: { driver: 'gemini-cli' } };
  assert.throws(() => assertCrossFamilyRouting({ routes: selfReview }), (e) => e instanceof SelfReviewHalt && e instanceof HaltError);
  // An empty/unverifiable driver fails CLOSED (never assume a safe cross-family route).
  assert.throws(() => assertCrossFamilyRouting({ routes: { default: {} } }), SelfReviewHalt);
  // The single-family (all-Claude) table is a self-review route for verification → HALT (never silently OK).
  assert.throws(() => assertCrossFamilyRouting({ routes: SINGLE_FAMILY_ROUTES }), SelfReviewHalt);
});

// ── (W6-b) reached-family provenance is DERIVED from the seats actually dispatched ─────────────────────

test('(W6-b) the instrumented agent derives reached families from the seats dispatched', async () => {
  const tracker = makeReachedFamilyTracker([DRAFTER_FAMILY]);
  const seen = [];
  const stub = async (_p, opts = {}) => { seen.push(resolveRoleKey(opts)); return { ok: true }; };
  const routed = instrumentCrucibleAgent({ agent: stub, routes: DEFAULT_CRUCIBLE_ROUTES, tracker, geminiCap: 2 });

  await routed('p', { role: 'shark', label: 'shark:Skeptic:r0' });
  await routed('p', { role: 'judge', label: 'judge:r0:m' });
  await routed('p', { role: 'synthesizer', label: 'synthesizer:direct:r0' });
  await routed('p', { label: 'stage1:phased-plan' }); // drafter seat → claude

  assert.deepEqual(seen, ['shark', 'judge', 'synthesizer', 'stage1']);
  // A genuine cross-family run: the Gemini shark/judge seats + the Claude seats were reached.
  assert.deepEqual(tracker.families(), ['claude', 'gemini']);
  assert.equal(tracker.has('gemini'), true);
});

test('(W6-b) a REAL runSharkTank round dispatches its Sharks through the Gemini seat', async () => {
  const tracker = makeReachedFamilyTracker();
  // A schema-shaped Shark stub (no finding) — runSharkTank calls it with role:'shark'.
  const stub = async () => ({ answerable: 'yes', findings: [] });
  const routed = instrumentCrucibleAgent({ agent: stub, routes: DEFAULT_CRUCIBLE_ROUTES, tracker, geminiCap: 3 });

  const verdict = await runSharkTank({ agent: routed, northStar: 'NS', draft: 'a draft', round: 0 });
  assert.equal(verdict.verdict, 'DRY');
  // The three Sharks all ran through the Gemini seat → gemini is the only reached family (no drafter seeded).
  assert.deepEqual(tracker.families(), ['gemini']);
  assert.equal(tracker.has('gemini'), true);
});

test('(W6-b) the tracker records only DISTINCT reached families and can be seeded', () => {
  const t = makeReachedFamilyTracker(['claude']);
  assert.deepEqual(t.families(), ['claude']);
  t.note('gemini'); t.note('gemini'); t.note('  Claude ');
  assert.deepEqual(t.families(), ['claude', 'gemini'], 'distinct + normalized (trim/lowercase)');
  t.note(''); t.note(null);
  assert.deepEqual(t.families(), ['claude', 'gemini'], 'empty/null are ignored');
});

// ── (W6-c) the live-Gemini concurrency cap holds ──────────────────────────────────────────────────────

test('(W6-c) no more than `cap` Gemini dispatches are ever in flight; Claude calls are ungated', async () => {
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
  const routed = instrumentCrucibleAgent({
    agent: inner,
    routes: { judge: { driver: 'gemini-cli' }, default: { driver: 'claude' } },
    tracker: makeReachedFamilyTracker(),
    geminiSemaphore: sem,
  });

  // Fan out FIVE concurrent Gemini (judge) dispatches — far more than the cap.
  const all = Promise.all(Array.from({ length: 5 }, () => routed('p', { role: 'judge' })));
  for (let i = 0; i < 50; i++) await Promise.resolve();
  assert.equal(active, cap, `only cap=${cap} Gemini calls may be in flight (saw ${active})`);
  assert.ok(maxActive <= cap, `max concurrent Gemini must never exceed cap (saw ${maxActive})`);

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
  const claudeAgent = instrumentCrucibleAgent({ agent: claudeInner, routes: { default: { driver: 'claude' } }, tracker: makeReachedFamilyTracker(), geminiSemaphore: sem });
  const claudeAll = Promise.all(Array.from({ length: 4 }, () => claudeAgent('p', { role: 'synthesizer' })));
  for (let i = 0; i < 50; i++) await Promise.resolve();
  assert.equal(claudeMax, 4, 'Claude dispatches are NOT bounded by the Gemini cap');
  while (claudeGate.length) claudeGate.shift()();
  await claudeAll;
});

test('(W6-c) resolveGeminiCap clamps to [1,3] with a safe default; makeSemaphore validates', () => {
  assert.equal(resolveGeminiCap({}), DEFAULT_GEMINI_CAP);
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: '1' }), 1);
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: '3' }), 3);
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: '9' }), MAX_GEMINI_CAP, 'clamped to the agy OOM ceiling');
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: 'nonsense' }), DEFAULT_GEMINI_CAP);
  assert.equal(resolveGeminiCap({ [GEMINI_CAP_ENV]: '0' }), DEFAULT_GEMINI_CAP);
  assert.throws(() => makeSemaphore(0), TypeError);
  assert.throws(() => makeSemaphore(1.5), TypeError);
});

// ── (W6-d) HONEST DEGRADE — a down Gemini seat HALTS and is never self-reviewed on Claude ─────────────

test('(W6-d) a down/unattested Gemini seat HALTS; gemini is NOT recorded reached; no Claude fallback', async () => {
  const tracker = makeReachedFamilyTracker();
  let claudeCalls = 0;
  // Simulate the W0 gemini-cli seam: a Gemini seat throws HaltError (non-attested / agy down); a
  // Claude seat would answer — but a verification finding must NEVER reach the Claude fallback.
  const inner = async (_p, opts) => {
    const role = resolveRoleKey(opts);
    if (familyFromRoute(DEFAULT_CRUCIBLE_ROUTES, role) === 'gemini') {
      throw new HaltError('Gemini attestation/transport failed: unattested_model', 'refuse to return a non-attested cross-family result');
    }
    claudeCalls += 1;
    return { lean: 'unknown', suggestions: [] };
  };
  const routed = instrumentCrucibleAgent({ agent: inner, routes: DEFAULT_CRUCIBLE_ROUTES, tracker, geminiCap: 2 });

  // The judge (Gemini) seat throws → the HaltError propagates (the call HALTS), never self-reviewed.
  await assert.rejects(() => routed('p', { role: 'judge' }), (e) => e instanceof HaltError);
  assert.equal(tracker.has('gemini'), false, 'a failed Gemini call is NEVER recorded as a reached family');
  assert.equal(claudeCalls, 0, 'the verification finding was NEVER silently re-answered on Claude (no self-review)');

  // Claude seats still work — proving the throw above was a HALT, not a fallback onto Claude.
  await routed('p', { role: 'synthesizer' });
  assert.equal(claudeCalls, 1);
  assert.deepEqual(tracker.families(), ['claude']);

  // The semaphore slot was released in `finally` despite the throw — a subsequent Gemini call can acquire.
  const okTracker = makeReachedFamilyTracker();
  const okAgent = instrumentCrucibleAgent({
    agent: async () => ({ ok: true }),
    routes: { judge: { driver: 'gemini-cli' }, default: { driver: 'claude' } },
    tracker: okTracker,
    geminiCap: 1,
  });
  await okAgent('p', { role: 'judge' });
  assert.deepEqual(okTracker.families(), ['gemini'], 'the slot freed on the prior throw is reusable (no leak)');
});

// ── (W6-e) the RETIRED module no longer provisions a hardcoded / API-key cross-model path ─────────────

test('(W6-e) enhanced.mjs is RETIRED — no MODEL_REGISTRY / API-key / phantom-model provisioning remains', () => {
  // The old competing exports are GONE (no hardcoded registry, no capability probe, no provisioner).
  for (const gone of [
    'MODEL_REGISTRY', 'CLAUDE_SUBSTRATE', 'detectReachableModels', 'makeCrossModelProbe',
    'selectSynthesizerModel', 'provisionRoles', 'detectAndProvision', 'defaultProbeCli',
  ]) {
    assert.equal(enhanced[gone], undefined, `retired export ${gone} must no longer exist`);
  }
  // The single-seam replacement IS present.
  assert.equal(typeof enhanced.buildLiveCrucibleAgent, 'function');
  assert.equal(typeof enhanced.instrumentCrucibleAgent, 'function');

  // The source itself carries no API-key spawn / phantom-model id (the no-phantom-model + single-seam rules).
  const src = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'bin', 'enhanced.mjs'), 'utf8');
  assert.ok(!/spawnSync/.test(src), 'no spawnSync capability-probe remains');
  assert.ok(!/GEMINI_API_KEY|GOOGLE_API_KEY|OPENAI_API_KEY|XAI_API_KEY|GROK_API_KEY/.test(src), 'no API-key provisioning remains');
  assert.ok(!/gemini-deep-think|o-series/.test(src), 'no non-current / phantom model id remains (the ladder resolves the model)');
});
