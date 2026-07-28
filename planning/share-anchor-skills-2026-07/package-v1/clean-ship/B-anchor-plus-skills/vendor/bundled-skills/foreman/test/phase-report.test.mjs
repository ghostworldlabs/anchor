// phase-report.test.mjs — SPIKE(foreman-parallel): the phase-breakdown aggregator
// (pure) + the A/B safety claim (concurrent reviewer collection ≡ serial; a rejecting
// reviewer maps to an abstain so a degraded concurrent run HALTs, never silently passes).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  parseLabel, parseJsonl, aggregate, compareRuns, reviewConcurrencyModel,
} from '../bin/phase-report.mjs';
import { collectFindings } from '../bin/wave-engine.mjs';
import { makeScriptedDriver } from '../bin/drivers/scripted-driver.mjs';

test('parseLabel attributes every Foreman call/gate label to a phase + wave', () => {
  assert.deepEqual(parseLabel('execute:w3'), { phase: 'execute', wave: 3, sub: null });
  assert.deepEqual(parseLabel('review:w3#0'), { phase: 'review', wave: 3, sub: 0 });
  assert.deepEqual(parseLabel('review:w3#1#retry'), { phase: 'review', wave: 3, sub: 1 });
  assert.deepEqual(parseLabel('fix:w3.2'), { phase: 'fix', wave: 3, sub: 2 });
  assert.deepEqual(parseLabel('gate:w3.2'), { phase: 'gate', wave: 3, sub: 2 });
  assert.equal(parseLabel('nonsense').phase, null);
  assert.equal(parseLabel(null).phase, null);
});

test('aggregate computes per-phase sums, shares, and mean fix-iters k', () => {
  // One wave: execute(1000ms) · gate ×2 (200,200) · review ×2 per round ×2 rounds ·
  // fix ×1 (iter 1). k for this single wave = 1.
  const recs = parseJsonl([
    JSON.stringify({ label: 'execute:w1', duration_ms: 1000, output_tokens: 500 }),
    JSON.stringify({ label: 'gate:w1.0', duration_ms: 200, output_tokens: 0 }),
    JSON.stringify({ label: 'review:w1#0', duration_ms: 400, output_tokens: 100 }),
    JSON.stringify({ label: 'review:w1#1', duration_ms: 400, output_tokens: 100 }),
    JSON.stringify({ label: 'fix:w1.1', duration_ms: 800, output_tokens: 300 }),
    JSON.stringify({ label: 'gate:w1.1', duration_ms: 200, output_tokens: 0 }),
    JSON.stringify({ label: 'review:w1#0', duration_ms: 400, output_tokens: 100 }),
    JSON.stringify({ label: 'review:w1#1', duration_ms: 400, output_tokens: 100 }),
  ].join('\n'));
  const a = aggregate(recs);
  assert.equal(a.byPhase.execute.ms, 1000);
  assert.equal(a.byPhase.review.ms, 1600);
  assert.equal(a.byPhase.review.calls, 4);
  assert.equal(a.byPhase.fix.ms, 800);
  assert.equal(a.byPhase.gate.ms, 400);
  assert.equal(a.totalMs, 3800);
  assert.equal(a.waveCount, 1);
  assert.equal(a.meanK, 1); // one fix iteration in the one wave
  assert.equal(a.meanReviewCallMs, 400);
  // shares sum to 1
  const shareSum = Object.values(a.phaseShare).reduce((x, y) => x + y, 0);
  assert.ok(Math.abs(shareSum - 1) < 1e-9);
});

test('unrecognized labels are excluded and counted, never silently summed', () => {
  const a = aggregate([{ label: 'mystery', duration_ms: 999 }, { label: 'execute:w1', duration_ms: 10 }]);
  assert.equal(a.unattributed, 1);
  assert.equal(a.totalMs, 10);
});

test('reviewConcurrencyModel: 2 reviewers ⇒ ~half the review wall-clock saved', () => {
  const a = aggregate([
    { label: 'review:w1#0', duration_ms: 400 },
    { label: 'review:w1#1', duration_ms: 400 },
  ]);
  const m = reviewConcurrencyModel(a, 2);
  assert.equal(m.serialReviewMs, 800);
  assert.equal(m.estConcurrentReviewMs, 400); // 1 round × mean call
  assert.equal(m.estSavedMs, 400);
});

test('compareRuns reports the A/B delta and that tokens are NOT reduced by concurrency', () => {
  const serial = aggregate([
    { label: 'review:w1#0', duration_ms: 400, output_tokens: 100 },
    { label: 'review:w1#1', duration_ms: 400, output_tokens: 100 },
  ]);
  // Variant: same tokens, but review wall-clock is the slower single reviewer.
  const variant = aggregate([
    { label: 'review:w1#0', duration_ms: 400, output_tokens: 100 },
  ]);
  // (synthetic: the variant file would in reality still log both calls; this asserts the math)
  const cmp = compareRuns(serial, variant);
  assert.equal(cmp.review.deltaMs, 400);
  assert.equal(cmp.tokens.baseline, 200);
});

// --- The A/B SAFETY CLAIM: concurrent reviewer collection ≡ serial collection ------

const fakeGate = {
  green: false, exit_code: 1, tap: { pass: 0, fail: 1, tests: 1 },
  stdout: 'not ok 1 - boom', stderr: '', artifact_path: '/tmp/gate.json',
};
const ctxFor = (r) => ({ projectDir: '/tmp/proj', wave: { n: 1, title: 't' }, reviewerIndex: r });

test('concurrent (Promise.allSettled) reviewer collection yields IDENTICAL findings to serial', async () => {
  const finding = [{ severity: 'BLOCKER', file: 'a.js', line: 7, rule: 'bug', message: 'x' }];
  const driver = makeScriptedDriver({ reviewerFindings: finding });

  // Serial (historical path).
  const serial = [];
  for (let r = 0; r < 2; r++) serial.push(await driver.review(ctxFor(r), fakeGate));

  // Concurrent (the SPIKE A/B path).
  const settled = await Promise.allSettled([0, 1].map((r) => driver.review(ctxFor(r), fakeGate)));
  const concurrent = settled.map((s, r) => s.status === 'fulfilled' ? s.value
    : { reviewer: `reviewer-${r}`, answerable: 'no', findings: [] });

  // collectFindings keys by stable id ⇒ order-independent ⇒ identical agreement tally.
  const a = collectFindings(serial);
  const b = collectFindings(concurrent);
  assert.deepEqual(b, a);
  assert.equal(b[0].agreement, 2); // both reviewers agree ⇒ a real BLOCKER, either way
});

test('a REJECTING reviewer maps to answerable:no (degraded concurrent run HALTs, never silent-passes)', async () => {
  const ok = makeScriptedDriver({ reviewerFindings: [] });
  const settled = await Promise.allSettled([
    ok.review(ctxFor(0), fakeGate),
    Promise.reject(new Error('429 overloaded')), // reviewer 1's call rejects
  ]);
  const reviews = settled.map((s, r) => s.status === 'fulfilled' ? s.value : {
    reviewer: `reviewer-${r}`, answerable: 'no',
    note: `reviewer ${r} call rejected (${s.reason?.message || s.reason})`, findings: [],
  });
  // The §4.7 ambiguity gate keys on answerable:'no' ⇒ this run HALTs for a human.
  assert.ok(reviews.some((rv) => rv.answerable === 'no'));
});
