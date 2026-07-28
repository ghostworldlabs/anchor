// Wave 4 — Foreman inherit only + band alignment.
//
// Proves:
//   · Foreman inherits depth from handoff only (spy call-count 0 on assess)
//   · LITE / LIGHT reviewers ≥ 1 (never zero)
//   · triage_track FULL is recognized
//   · FULL / LITE / SPIKE-FIRST map consistently
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { DEPTH_BANDS, recommend } from '../core.mjs';
import { assessComplexity } from '../crucible-wire.mjs';
import {
  NS01_WAVE4_STAMP,
  MIN_REVIEWERS,
  REVIEWERS_BY_DEPTH,
  normalizeInheritedDepth,
  isRecognizedTriageTrack,
  inheritDepthFromHandoff,
  reviewersForDepth,
  inheritReviewerCount,
} from '../foreman-wire.mjs';
import {
  buildHandoffTriageEmit,
  createLockRecord,
} from '../index.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(here, '..');

test('NS01_WAVE4_STAMP is exported on the Foreman-inherit surface', () => {
  assert.equal(NS01_WAVE4_STAMP, 'ns01-w4-foreman-inherit');
});

test('pin depths map consistently: LITE=1, FULL=2, SPIKE-FIRST=2; floor ≥ 1', () => {
  assert.equal(MIN_REVIEWERS, 1);
  assert.equal(REVIEWERS_BY_DEPTH[DEPTH_BANDS.LITE], 1);
  assert.equal(REVIEWERS_BY_DEPTH[DEPTH_BANDS.FULL], 2);
  assert.equal(REVIEWERS_BY_DEPTH[DEPTH_BANDS.SPIKE_FIRST], 2);

  assert.equal(reviewersForDepth('LITE'), 1);
  assert.equal(reviewersForDepth('FULL'), 2);
  assert.equal(reviewersForDepth('SPIKE-FIRST'), 2);
  assert.ok(reviewersForDepth('LITE') >= 1);
  assert.ok(reviewersForDepth('LIGHT') >= 1);
  assert.ok(reviewersForDepth(DEPTH_BANDS.LITE) >= MIN_REVIEWERS);
});

test('LITE / LIGHT never map to zero reviewers', () => {
  for (const track of ['LITE', 'LIGHT', 'lite', 'light']) {
    const n = reviewersForDepth(track);
    assert.ok(n != null && n >= 1, `${track} must yield ≥1 reviewers, got ${n}`);
    const inherited = inheritReviewerCount({ triage_track: track });
    assert.equal(inherited.applied, true);
    assert.equal(inherited.depth, DEPTH_BANDS.LITE);
    assert.ok(inherited.reviewers >= 1, `${track} inherit must floor ≥1`);
  }
});

test('triage_track FULL is recognized (band alignment)', () => {
  assert.equal(isRecognizedTriageTrack('FULL'), true);
  assert.equal(normalizeInheritedDepth('FULL'), DEPTH_BANDS.FULL);
  assert.equal(normalizeInheritedDepth('full'), DEPTH_BANDS.FULL);

  const fromTrack = inheritReviewerCount({ triage_track: 'FULL' });
  assert.equal(fromTrack.applied, true);
  assert.equal(fromTrack.depth, DEPTH_BANDS.FULL);
  assert.equal(fromTrack.reviewers, 2);
  assert.equal(fromTrack.source, 'inherit');
});

test('legacy aliases: LIGHT→LITE, HEAVY→FULL, MID/STANDARD→lean; SPIKE-FIRST recognized', () => {
  assert.equal(normalizeInheritedDepth('LIGHT'), DEPTH_BANDS.LITE);
  assert.equal(normalizeInheritedDepth('HEAVY'), DEPTH_BANDS.FULL);
  assert.equal(normalizeInheritedDepth('MID'), DEPTH_BANDS.LITE);
  assert.equal(normalizeInheritedDepth('STANDARD'), DEPTH_BANDS.LITE);
  assert.equal(normalizeInheritedDepth('SPIKE-FIRST'), DEPTH_BANDS.SPIKE_FIRST);
  assert.equal(normalizeInheritedDepth('SPIKE_FIRST'), DEPTH_BANDS.SPIKE_FIRST);

  assert.equal(inheritReviewerCount({ triage_track: 'HEAVY' }).reviewers, 2);
  assert.equal(inheritReviewerCount({ triage_track: 'SPIKE-FIRST' }).reviewers, 2);
  assert.equal(inheritReviewerCount({ triage_track: 'MID' }).reviewers, 1);
});

test('inherit prefers triage.depth over triage_track when both present', () => {
  const cfg = {
    triage_track: 'FULL',
    triage: {
      locked: true,
      tier: 'Standard',
      depth: 'LITE',
      rationale: 'user locked lite',
      source: 'interactive',
    },
  };
  assert.equal(inheritDepthFromHandoff(cfg), DEPTH_BANDS.LITE);
  assert.equal(inheritReviewerCount(cfg).reviewers, 1);
});

test('inherit from Wave-3 handoff emit shape (Stage-0 consumer contract)', () => {
  const lock = createLockRecord({
    tier: 'Heavy',
    depth: 'FULL',
    rationale: 'Stage-0 locked both axes',
    source: 'interactive',
  });
  const emit = buildHandoffTriageEmit(lock);
  assert.equal(emit.triage_track, 'FULL');

  const inherited = inheritReviewerCount(emit);
  assert.equal(inherited.applied, true);
  assert.equal(inherited.depth, DEPTH_BANDS.FULL);
  assert.equal(inherited.reviewers, 2);
});

test('inherit spy call-count 0 on assess — never re-triages', () => {
  let assessCalls = 0;
  const assessSpy = (...args) => {
    assessCalls += 1;
    // If someone wired re-triage by mistake, this would fire.
    return assessComplexity(...args);
  };

  const configs = [
    { triage_track: 'LITE' },
    { triage_track: 'FULL' },
    { triage_track: 'SPIKE-FIRST' },
    { triage_track: 'LIGHT' },
    {
      triage_track: 'FULL',
      triage: { depth: 'LITE', tier: 'Standard', locked: true, rationale: 'x', source: 'config' },
    },
    {},
    null,
  ];

  for (const cfg of configs) {
    inheritDepthFromHandoff(cfg, { assess: assessSpy });
    inheritReviewerCount(cfg, { assess: assessSpy, defaultCount: 2 });
  }

  assert.equal(assessCalls, 0, 'inherit path must never call assess (re-triage forbidden)');
});

test('inherit path does not import or call recommend / assessComplexity (source contract)', () => {
  const wire = readFileSync(join(pkgRoot, 'foreman-wire.mjs'), 'utf8');
  assert.match(wire, /from '\.\/core\.mjs'/);
  assert.doesNotMatch(wire, /assessComplexity/);
  assert.doesNotMatch(wire, /recommend\s*\(/);
  assert.doesNotMatch(wire, /crucible-wire/);
  assert.match(wire, /never re-triage|NEVER re-triage|inherit only/i);

  // recommend remains available on the package but is not used by inherit.
  const rec = recommend({ intent: 'x', scope: 'small', unknowns: 0 });
  assert.ok(rec.depth);
  // Calling recommend must not be required for inherit to work:
  const inherited = inheritReviewerCount({ triage_track: rec.depth });
  assert.equal(inherited.applied, true);
  assert.ok(inherited.reviewers >= MIN_REVIEWERS);
});

test('missing / unknown track leaves defaultCount (floored); does not invent a band', () => {
  const a = inheritReviewerCount({}, { defaultCount: 3 });
  assert.equal(a.applied, false);
  assert.equal(a.depth, null);
  assert.equal(a.reviewers, 3);
  assert.equal(a.source, null);

  const b = inheritReviewerCount({ triage_track: 'NOT-A-BAND' }, { defaultCount: 2 });
  assert.equal(b.applied, false);
  assert.equal(b.reviewers, 2);

  // Zero / negative default still floors at MIN_REVIEWERS when applied is false path with bad default
  const c = inheritReviewerCount({}, { defaultCount: 0 });
  assert.equal(c.applied, false);
  assert.equal(c.reviewers, 2, 'invalid default falls back to 2');
});

test('wire module is on the public surface (source contract)', () => {
  const index = readFileSync(join(pkgRoot, 'index.mjs'), 'utf8');
  assert.match(index, /foreman-wire/);
  assert.match(index, /inheritReviewerCount|inheritDepthFromHandoff/);
  assert.match(index, /NS01_WAVE4_STAMP/);

  const pkg = JSON.parse(readFileSync(join(pkgRoot, 'package.json'), 'utf8'));
  assert.ok(
    String(pkg.scripts?.test || '').includes('foreman-inherit.test.mjs'),
    'package test script must include Wave-4 foreman-inherit tests',
  );
});

test('live Foreman run-live uses inheritReviewerCount (no dark LIGHT→0 path)', () => {
  // Soft live-path check: same pin pattern as Wave 3 Stage-0 wire into trio.
  const candidates = [
    '<path>',
    'C:\\Users\\john\\.claude\\skills\\foreman\\bin\\run-live.mjs',
  ];
  let checked = 0;
  for (const p of candidates) {
    let src;
    try {
      src = readFileSync(p, 'utf8');
    } catch {
      continue;
    }
    checked += 1;
    assert.match(src, /inheritReviewerCount/, `${p} must call inheritReviewerCount`);
    assert.match(src, /foreman-wire\.mjs/, `${p} must import @foundry/triage foreman-wire`);
    // Dark path gone: no assignment of reviewers to 0 from triage_track.
    assert.doesNotMatch(
      src,
      /REVIEWERS\s*=\s*0/,
      `${p} must not zero REVIEWERS`,
    );
    // Inline LIGHT/LITE fan-out replaced by shared inherit.
    assert.doesNotMatch(
      src,
      /track === 'LITE' \|\| track === 'LIGHT'/,
      `${p} must not keep the pre-Wave-4 inline triage_track switch`,
    );
  }
  assert.ok(
    checked >= 1,
    'expected at least one live Foreman run-live.mjs at the pinned trio/skill paths',
  );
});
