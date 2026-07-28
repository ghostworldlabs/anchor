// test/shark-tank.test.mjs — Wave 2 gate for the Shark-Tank round engine.
// Drives the full round through an INJECTED (stubbed) agent — no subprocess —
// and proves: cross-Shark id normalization, ≥2-agree BLOCKER vs dry-round
// verdicts, inclusion-test demotion, North-Star + rotated-angle prompt embedding,
// and file-based verdict artifacts. Exercises REAL source in bin/shark-tank.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  SHARK_ROLES,
  PM_CRITIQUE_ANGLES,
  angleForShark,
  normalizeTopic,
  normalizeFindingId,
  tallyFindings,
  makeSharkDriver,
  runSharkTank,
  writeRoundArtifacts,
  SHARK_SCHEMA,
} from '../bin/shark-tank.mjs';

// --- helpers ---------------------------------------------------------------

function mkTmp(prefix) { return fs.mkdtempSync(path.join(os.tmpdir(), prefix)); }
function rm(dir) { try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* best-effort */ } }

/**
 * Build a stub agent() that returns scripted findings keyed by Shark role. The
 * `byRole` map is `{ Skeptic:[...findings], Contrarian:[...], Analyst:[...] }`.
 * Also records every (prompt, opts) it was called with for prompt assertions.
 */
function scriptedAgent(byRole) {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    const role = (opts.label || '').split(':')[1]; // shark:<Role>:r<round>
    const findings = (byRole[role] || []);
    return { answerable: 'yes', findings };
  }
  agent.calls = calls;
  return agent;
}

const NORTH_STAR = 'NORTH-STAR-SENTINEL: ship a Foreman-ready plan that never drifts.';
const DRAFT = 'A draft plan with several arguable decisions.';

// --- normalization ---------------------------------------------------------

test('normalizeTopic is order- and wording-insensitive (drops stopwords, sorts)', () => {
  assert.equal(
    normalizeTopic('North Star is ambiguous about scope'),
    normalizeTopic('ambiguous scope in the North Star'),
    'same issue, different wording/order ⇒ same key',
  );
  assert.notEqual(
    normalizeTopic('ambiguous scope'),
    normalizeTopic('missing rollback plan'),
    'distinct issues ⇒ distinct keys',
  );
});

test('normalizeFindingId keys on topic, collapsing cross-Shark wording', () => {
  const a = normalizeFindingId({ topic: 'North Star is ambiguous about scope', section: 'S1' });
  const b = normalizeFindingId({ topic: 'ambiguous scope in the North Star', section: 'S2' });
  assert.equal(a, b, 'same issue ⇒ same id even with different sections/wording');
  // Falls back to a Foreman-style location id when no topic is given.
  const c = normalizeFindingId({ section: 'gates.mjs', rule: 'missing ENOENT handling' });
  assert.match(c, /^loc:/);
});

test('normalizeFindingId: an explicit claim_id BEATS the topic slug (identity precedence)', () => {
  // Same claim, three different topic wordings — the exact shape of the
  // 2026-07-06 false-DRY (researchPrime journal 0001).
  const a = normalizeFindingId({ claim_id: 'C3', topic: 'heartbeat cadence is unsourced' });
  const b = normalizeFindingId({ claim_id: 'C3', topic: 'no citation for the cadence claim' });
  const c = normalizeFindingId({ claimId: ' C3 ', topic: 'cadence figure lacks evidence' });
  assert.equal(a, b, 'same claim_id ⇒ same id regardless of topic wording');
  assert.equal(a, c, 'claimId alias + case/whitespace-insensitive canonicalization');
  assert.match(a, /^claim:/);
  // Different claims stay distinct even with identical topics.
  const d = normalizeFindingId({ claim_id: 'C4', topic: 'heartbeat cadence is unsourced' });
  assert.notEqual(a, d, 'distinct claim ids ⇒ distinct identities');
  // No claim_id ⇒ unchanged legacy behavior (topic slug).
  const e = normalizeFindingId({ topic: 'heartbeat cadence is unsourced' });
  assert.match(e, /^topic:/);
  // Order preserved: claim ids are identifiers, not prose (no token sorting).
  assert.notEqual(
    normalizeFindingId({ claim_id: 'ab-cd' }),
    normalizeFindingId({ claim_id: 'cd-ab' }),
    'claim id token order is significant',
  );
});

test('REGRESSION (false-DRY, journal 0001): three reviewers, same claim_id, divergent slugs ⇒ ≥2-agree fires', () => {
  const reviews = [
    { reviewer: 'Skeptic', findings: [
      { severity: 'BLOCKER', claim_id: 'C3', topic: 'heartbeat cadence unsourced', traces_to_north_star: 'yes', criterion: 'C1' }] },
    { reviewer: 'Contrarian', findings: [
      { severity: 'BLOCKER', claim_id: 'C3', topic: 'cadence number has no citation', traces_to_north_star: 'yes', criterion: 'C1' }] },
    { reviewer: 'Analyst', findings: [
      { severity: 'MAJOR', claim_id: 'C3', topic: 'evidence missing for cadence figure', traces_to_north_star: 'yes', criterion: 'C1' }] },
  ];
  // Pre-fix, these slugged to three distinct topic ids: agreement 1 each ⇒ DRY.
  const t = tallyFindings(reviews);
  assert.equal(t.verdict, 'BLOCKED', 'the shared claim_id makes the quorum register');
  assert.equal(t.blockers.length, 1);
  assert.equal(t.blockers[0].agreement, 3);
  assert.equal(t.blockers[0].severity, 'BLOCKER', 'max severity raised across reviewers');
  assert.match(t.blockers[0].id, /^claim:c3$/);
});

// --- quorum floor (2026-07-17): <2 parseable reviewers ⇒ inconclusive -------

test('tallyFindings: fewer than 2 answering reviewers ⇒ inconclusive (a "dry" would be a false convergence)', () => {
  const reviews = [
    { reviewer: 'Skeptic', answerable: 'no', findings: [] },   // abstained (unparseable/rejected)
    { reviewer: 'Contrarian', answerable: 'no', findings: [] },
    { reviewer: 'Analyst', answerable: 'yes', findings: [
      { severity: 'BLOCKER', topic: 'real issue', traces_to_north_star: 'yes', criterion: 'C1' }] },
  ];
  const t = tallyFindings(reviews);
  assert.equal(t.answered, 1);
  assert.equal(t.inconclusive, true, 'only 1 reviewer answered — cannot form a >=2 BLOCKER quorum');
});

test('tallyFindings: 2 answering reviewers ⇒ NOT inconclusive (one abstain is tolerated)', () => {
  const reviews = [
    { reviewer: 'Skeptic', answerable: 'no', findings: [] },
    { reviewer: 'Contrarian', answerable: 'yes', findings: [] },
    { reviewer: 'Analyst', answerable: 'yes', findings: [] },
  ];
  const t = tallyFindings(reviews);
  assert.equal(t.answered, 2);
  assert.equal(t.inconclusive, false, 'two answering reviewers still form a valid quorum');
});

// --- angle rotation --------------------------------------------------------

test('angleForShark rotates across Sharks and rounds, always within the 8 angles', () => {
  const seen = new Set();
  for (let round = 0; round < 3; round++) {
    for (let i = 0; i < SHARK_ROLES.length; i++) {
      const a = angleForShark(round, i);
      assert.ok(PM_CRITIQUE_ANGLES.includes(a), `${a} is a valid PM angle`);
      seen.add(a);
    }
  }
  // Three rounds × three Sharks touch a diverse set, not one repeated angle.
  assert.ok(seen.size >= 5, `rotation should be diverse, saw ${seen.size}`);
  // A given (round, shark) is deterministic.
  assert.equal(angleForShark(0, 0), angleForShark(0, 0));
});

// --- driver guard ----------------------------------------------------------

test('makeSharkDriver HALTs without an agent() function (mirrors makeAgentDriver)', () => {
  assert.throws(() => makeSharkDriver({}), (e) => e instanceof HaltError);
  assert.throws(() => makeSharkDriver({ agent: 'nope' }), (e) => e instanceof HaltError);
});

// --- tally: ≥2-agree BLOCKER on the same normalized id ----------------------

test('two Sharks whose findings normalize to the same id ⇒ BLOCKER', () => {
  const reviews = [
    { reviewer: 'Skeptic', findings: [
      { severity: 'BLOCKER', topic: 'North Star is ambiguous about scope', traces_to_north_star: 'yes', criterion: 'C1' }] },
    { reviewer: 'Contrarian', findings: [
      { severity: 'BLOCKER', topic: 'ambiguous scope in the North Star', traces_to_north_star: 'yes', criterion: 'C1' }] },
  ];
  const t = tallyFindings(reviews);
  assert.equal(t.verdict, 'BLOCKED');
  assert.equal(t.blockers.length, 1);
  assert.equal(t.blockers[0].agreement, 2, 'cross-Shark normalization made the two agree on one id');
  assert.deepEqual(t.blockers[0].raisedBy.sort(), ['Contrarian', 'Skeptic']);
});

test('a single Shark BLOCKER (agreement 1) is NOT a blocker ⇒ dry round (needs ≥2)', () => {
  const reviews = [
    { reviewer: 'Skeptic', findings: [
      { severity: 'BLOCKER', topic: 'unrebutted lone concern', traces_to_north_star: 'yes', criterion: 'C1' }] },
    { reviewer: 'Contrarian', findings: [] },
    { reviewer: 'Analyst', findings: [] },
  ];
  const t = tallyFindings(reviews);
  assert.equal(t.blockers.length, 0, 'one Shark is not ≥2 agreement');
  assert.equal(t.verdict, 'DRY');
});

// --- inclusion-test demotion -----------------------------------------------

test('a finding that does not trace to the North Star is DEMOTED and cannot hold the loop open', () => {
  const reviews = [
    { reviewer: 'Skeptic', findings: [
      { severity: 'BLOCKER', topic: 'shiny unrelated idea', traces_to_north_star: 'no' }] },
    { reviewer: 'Contrarian', findings: [
      { severity: 'BLOCKER', topic: 'shiny unrelated idea', traces_to_north_star: 'no' }] },
  ];
  const t = tallyFindings(reviews);
  assert.equal(t.demoted.length, 1, 'the non-tracing finding is demoted');
  assert.equal(t.demoted[0].demoted, true);
  assert.equal(t.demoted[0].isBlocker, false, 'demoted ⇒ never a blocker even at ≥2 agreement + BLOCKER severity');
  assert.equal(t.verdict, 'DRY', 'a demoted finding cannot keep the loop open');
});

test('one Shark tracing rescues an issue the other left untraced (issue-level inclusion)', () => {
  const reviews = [
    { reviewer: 'Skeptic', findings: [
      { severity: 'MAJOR', topic: 'rollback path unspecified', traces_to_north_star: 'no' }] },
    { reviewer: 'Analyst', findings: [
      { severity: 'MAJOR', topic: 'rollback path unspecified', traces_to_north_star: 'yes', criterion: 'C3' }] },
  ];
  const t = tallyFindings(reviews);
  assert.equal(t.blockers.length, 1, 'any Shark tracing it to a criterion keeps it in scope');
  assert.equal(t.blockers[0].criterion, 'C3');
  assert.equal(t.verdict, 'BLOCKED');
});

// --- dry-round detection + anti-oscillation --------------------------------

test('no findings ⇒ dry round', () => {
  const t = tallyFindings([
    { reviewer: 'Skeptic', findings: [] },
    { reviewer: 'Contrarian', findings: [] },
    { reviewer: 'Analyst', findings: [] },
  ]);
  assert.equal(t.dry, true);
  assert.equal(t.verdict, 'DRY');
});

test('a blocker already seen last round is not NEW ⇒ dry round (anti-oscillation)', () => {
  const reviews = [
    { reviewer: 'Skeptic', findings: [
      { severity: 'BLOCKER', topic: 'recurring scope ambiguity', traces_to_north_star: 'yes', criterion: 'C1' }] },
    { reviewer: 'Contrarian', findings: [
      { severity: 'BLOCKER', topic: 'recurring scope ambiguity', traces_to_north_star: 'yes', criterion: 'C1' }] },
  ];
  const fresh = tallyFindings(reviews);
  assert.equal(fresh.verdict, 'BLOCKED');
  const priorId = fresh.blockers[0].id;
  const repeat = tallyFindings(reviews, { priorBlockerIds: [priorId] });
  assert.equal(repeat.blockers.length, 1, 'still a tallied blocker...');
  assert.equal(repeat.newBlockers.length, 0, '...but not a NEW one');
  assert.equal(repeat.verdict, 'DRY', 'no new BLOCKER ⇒ dry round');
});

// --- full round through the stubbed agent ----------------------------------

test('runSharkTank: stubbed round produces a BLOCKED verdict and embeds North Star + angle in every prompt', async () => {
  const agent = scriptedAgent({
    Skeptic: [{ severity: 'BLOCKER', topic: 'North Star ambiguous on drift', traces_to_north_star: 'yes', criterion: 'C1' }],
    Contrarian: [{ severity: 'BLOCKER', topic: 'drift in the ambiguous North Star', traces_to_north_star: 'yes', criterion: 'C1' }],
    Analyst: [{ severity: 'NIT', topic: 'wording nit', traces_to_north_star: 'no' }],
  });
  const v = await runSharkTank({ agent, northStar: NORTH_STAR, draft: DRAFT, round: 1 });

  assert.equal(v.verdict, 'BLOCKED');
  assert.equal(v.blockers.length, 1);
  assert.equal(v.blockers[0].agreement, 2);

  // Three Sharks were each asked exactly once, with schema enforcement.
  assert.equal(agent.calls.length, 3);
  for (const c of agent.calls) {
    assert.equal(c.opts.schema, SHARK_SCHEMA, 'each Shark call is schema-forced');
    assert.ok(c.prompt.includes(NORTH_STAR), 'North Star embedded verbatim in every Shark prompt');
    const angle = c.opts.label.split(':')[1];
    assert.ok(c.prompt.includes(v.angles[angle]), 'the rotated PM angle is named in the prompt');
  }
});

test('runSharkTank: a clean round is DRY', async () => {
  const agent = scriptedAgent({}); // every Shark returns no findings
  const v = await runSharkTank({ agent, northStar: NORTH_STAR, draft: DRAFT, round: 0 });
  assert.equal(v.verdict, 'DRY');
  assert.equal(v.findings.length, 0);
});

// --- file-based verdict artifacts ------------------------------------------

test('writeRoundArtifacts emits verdict.json, per-Shark files, and SYNTHESIS.md', async () => {
  const dir = mkTmp('crucible-shark-');
  try {
    const agent = scriptedAgent({
      Skeptic: [{ severity: 'BLOCKER', topic: 'lock gate underspecified', traces_to_north_star: 'yes', criterion: 'C2', message: 'no lock criteria' }],
      Contrarian: [{ severity: 'BLOCKER', topic: 'underspecified lock gate', traces_to_north_star: 'yes', criterion: 'C2', message: 'lock gate vague' }],
    });
    const v = await runSharkTank({ agent, northStar: NORTH_STAR, draft: DRAFT, round: 2, artifactsDir: dir });

    const roundDir = path.join(dir, 'round-2');
    assert.equal(v.artifactPath, roundDir);
    const verdictJson = JSON.parse(fs.readFileSync(path.join(roundDir, 'verdict.json'), 'utf8'));
    assert.equal(verdictJson.verdict, 'BLOCKED');
    assert.equal(verdictJson.round, 2);

    for (const role of ['Skeptic', 'Contrarian', 'Analyst']) {
      assert.ok(fs.existsSync(path.join(roundDir, `shark-${role}.json`)), `shark-${role}.json written`);
    }
    const synth = fs.readFileSync(path.join(roundDir, 'SYNTHESIS.md'), 'utf8');
    assert.match(synth, /Shark-Tank Round 2 — BLOCKED/);
  } finally {
    rm(dir);
  }
});
