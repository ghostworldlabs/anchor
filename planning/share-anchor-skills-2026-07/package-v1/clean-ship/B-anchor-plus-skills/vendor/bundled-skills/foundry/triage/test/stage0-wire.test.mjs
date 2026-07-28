// Wave 3 — Crucible Stage-0 wire + handoff emit.
//
// Proves:
//   · Stage-0 without a validating lock fails (no silent proceed)
//   · shared recommend/assessComplexity is on the live Stage-0 path
//   · handoff emit shape matches the Foreman consumer (triage_track string + triage {tier,depth})
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  DEPTH_BANDS,
  MODEL_TIERS,
  recommend,
} from '../core.mjs';
import {
  createLockRecord,
  getLockedBand,
  lockFromHeadless,
} from '../lock.mjs';
import {
  NS01_WAVE3_STAMP,
  COMPLEXITY_BANDS,
  assessComplexity,
  resolveStage0TriageLock,
  buildHandoffTriageEmit,
  mergeTriageIntoForemanConfig,
  assertForemanConsumerShape,
  isForemanTriageTrack,
  depthToLegacyBand,
  legacyBandToDepth,
} from '../crucible-wire.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(here, '..');

test('NS01_WAVE3_STAMP is exported on the Stage-0 wire surface', () => {
  assert.equal(NS01_WAVE3_STAMP, 'ns01-w3-stage0-wire');
});

test('assessComplexity routes through shared recommend (both axes + pin tokens)', () => {
  const r = assessComplexity({
    intent: 'tweak a skill paragraph',
    scope: 'small',
    unknowns: 0,
  });
  assert.equal(r.band, COMPLEXITY_BANDS.LITE);
  assert.equal(r.depth, COMPLEXITY_BANDS.LITE); // legacy C3 field
  assert.equal(r.nsDepth, DEPTH_BANDS.LITE); // NS pin
  assert.ok(r.nsTier === MODEL_TIERS.STANDARD || r.nsTier === MODEL_TIERS.HEAVY);
  assert.ok(r.recommendation);
  assert.equal(r.recommendation.depth, DEPTH_BANDS.LITE);
  assert.equal(typeof r.rationale, 'string');
  assert.ok(r.rationale.length > 0);
  assert.equal(r.defaultedToFull, false);
  assert.ok(r.halt);
  assert.equal(r.halt.pending_action, 'confirm-complexity-band');
  assert.equal(r.halt.halt_for_human, true);

  // Same intake via recommend() must agree on pin depth (single source of truth).
  const rec = recommend({ intent: 'tweak a skill paragraph', scope: 'small', unknowns: 0 });
  assert.equal(r.nsDepth, rec.depth);
  assert.equal(r.nsTier, rec.tier);
});

test('assessComplexity: high stakes / empty / brownfield match shared core floors', () => {
  const high = assessComplexity({ scope: 'small', unknowns: 0, highStakes: true });
  assert.equal(high.nsDepth, DEPTH_BANDS.FULL);
  assert.equal(high.band, COMPLEXITY_BANDS.FULL);

  const empty = assessComplexity();
  assert.equal(empty.nsDepth, DEPTH_BANDS.FULL);
  assert.ok(empty.rationale.length > 0);

  const bf = assessComplexity({ scope: 'small', unknowns: 0, brownfield: true });
  assert.notEqual(bf.nsDepth, DEPTH_BANDS.LITE);
  assert.notEqual(bf.band, COMPLEXITY_BANDS.LITE);

  const spike = assessComplexity({ scope: 'medium', novel: true, unknowns: 4 });
  assert.equal(spike.nsDepth, DEPTH_BANDS.SPIKE_FIRST);
  assert.equal(spike.band, COMPLEXITY_BANDS.SPIKE_FIRST);
});

test('Stage-0 without lock fails (resolveStage0TriageLock)', () => {
  assert.throws(
    () => resolveStage0TriageLock({ intake: { scope: 'small', unknowns: 0 } }),
    (err) => {
      assert.equal(err.pending_action, 'confirm-complexity-band');
      assert.equal(err.halt_for_human, true);
      return true;
    },
  );
  assert.throws(
    () => resolveStage0TriageLock({ intake: {} }),
    (err) => err.pending_action === 'confirm-complexity-band' || err.code === 'TRIAGE_UNLOCKED',
  );
  // getLockedBand remains the sole reader failure mode for bare unlock.
  assert.throws(() => getLockedBand(null), (err) => err.code === 'TRIAGE_UNLOCKED');
  assert.throws(() => buildHandoffTriageEmit(null), (err) => err.code === 'TRIAGE_UNLOCKED');
});

test('Stage-0 lock succeeds with confirmed depth (interactive confirm path)', () => {
  const { lock, band, complexity } = resolveStage0TriageLock({
    intake: { intent: 'ship a small doc tweak', scope: 'small', unknowns: 0 },
    confirmedDepth: 'LITE',
  });
  assert.equal(lock.locked, true);
  assert.equal(band.depth, DEPTH_BANDS.LITE);
  assert.equal(band.tier, complexity.nsTier);
  assert.equal(lock.source, 'interactive');
  assert.equal(getLockedBand(lock).depth, DEPTH_BANDS.LITE);
});

test('Stage-0 lock succeeds with explicit triageLock / headless inherit', () => {
  const record = createLockRecord({
    tier: 'Heavy',
    depth: 'FULL',
    rationale: 'fixture lock',
    source: 'config',
  });
  const a = resolveStage0TriageLock({ triageLock: record });
  assert.equal(a.band.depth, DEPTH_BANDS.FULL);
  assert.equal(a.band.tier, MODEL_TIERS.HEAVY);

  const b = resolveStage0TriageLock({
    headless: true,
    triageInherit: {
      tier: 'Standard',
      depth: 'SPIKE-FIRST',
      rationale: 'upstream Stage-0',
    },
  });
  assert.equal(b.band.depth, DEPTH_BANDS.SPIKE_FIRST);
  assert.equal(b.band.tier, MODEL_TIERS.STANDARD);
  assert.equal(b.lock.source, 'inherit');

  assert.throws(
    () => resolveStage0TriageLock({ headless: true }),
    (err) => err.code === 'TRIAGE_HEADLESS_UNLOCKED',
  );
});

test('handoff emit shape matches Foreman consumer (triage_track + triage {tier,depth})', () => {
  const lock = createLockRecord({
    tier: MODEL_TIERS.HEAVY,
    depth: DEPTH_BANDS.FULL,
    rationale: 'emit fixture',
    source: 'interactive',
  });
  const emit = buildHandoffTriageEmit(lock);
  assert.equal(emit.triage_track, 'FULL');
  assert.equal(typeof emit.triage_track, 'string');
  assert.ok(isForemanTriageTrack(emit.triage_track));
  assert.equal(emit.triage.locked, true);
  assert.equal(emit.triage.tier, 'Heavy');
  assert.equal(emit.triage.depth, 'FULL');
  assert.ok(emit.triage.rationale);
  assert.ok(emit.triage.source);
  assert.ok(emit.triage.lockedAt);
  assertForemanConsumerShape(emit);

  // LITE / SPIKE also valid Foreman tracks (SPIKE-FIRST input canonicalizes to SPIKE)
  for (const depth of ['LITE', 'SPIKE', 'SPIKE-FIRST']) {
    const e = buildHandoffTriageEmit(
      createLockRecord({
        tier: 'Standard',
        depth,
        rationale: 'band',
        source: 'config',
      }),
    );
    const expected = depth === 'SPIKE-FIRST' ? 'SPIKE' : depth;
    assert.equal(e.triage_track, expected);
    assertForemanConsumerShape(e);
  }

  // merge into foreman.config.json shape (docs block preserved)
  const cfg = mergeTriageIntoForemanConfig(
    {
      docs: {
        description: 'DESCRIPTION.md',
        plan: 'IMPLEMENTATION-PLAN.md',
        execution_log: 'EXECUTION-LOG.md',
      },
    },
    lock,
  );
  assert.equal(cfg.triage_track, 'FULL');
  assert.equal(cfg.triage.tier, 'Heavy');
  assert.equal(cfg.docs.plan, 'IMPLEMENTATION-PLAN.md');
  assertForemanConsumerShape(cfg);

  // historical HEAVY-as-track is recognized but new emits never produce it
  assert.equal(isForemanTriageTrack('HEAVY'), true);
  assert.notEqual(emit.triage_track, 'HEAVY');
});

test('legacy band ↔ pin token mapping is bidirectional for the three depths', () => {
  assert.equal(depthToLegacyBand(DEPTH_BANDS.FULL), COMPLEXITY_BANDS.FULL);
  assert.equal(depthToLegacyBand(DEPTH_BANDS.LITE), COMPLEXITY_BANDS.LITE);
  assert.equal(depthToLegacyBand(DEPTH_BANDS.SPIKE_FIRST), COMPLEXITY_BANDS.SPIKE_FIRST);
  assert.equal(legacyBandToDepth('lite'), DEPTH_BANDS.LITE);
  assert.equal(legacyBandToDepth('full'), DEPTH_BANDS.FULL);
  assert.equal(legacyBandToDepth('spike-first'), DEPTH_BANDS.SPIKE_FIRST);
  assert.equal(legacyBandToDepth('LIGHT'), DEPTH_BANDS.LITE);
  assert.equal(legacyBandToDepth(DEPTH_BANDS.FULL), DEPTH_BANDS.FULL);
});

test('wire module is on the public surface and calls shared core (source contract)', () => {
  const wire = readFileSync(join(pkgRoot, 'crucible-wire.mjs'), 'utf8');
  assert.match(wire, /from '\.\/core\.mjs'/);
  assert.match(wire, /from '\.\/lock\.mjs'/);
  assert.match(wire, /recommend\(/);
  assert.match(wire, /getLockedBand/);
  assert.match(wire, /buildHandoffTriageEmit/);
  assert.match(wire, /resolveStage0TriageLock/);

  const index = readFileSync(join(pkgRoot, 'index.mjs'), 'utf8');
  assert.match(index, /crucible-wire/);
  assert.match(index, /assessComplexity/);
  assert.match(index, /buildHandoffTriageEmit/);
  assert.match(index, /NS01_WAVE3_STAMP/);
});

test('headless lockFromHeadless still available for Stage-0 engine hosts', () => {
  const lock = lockFromHeadless({
    config: { tier: 'Heavy', depth: 'FULL', rationale: 'cfg' },
  });
  const emit = buildHandoffTriageEmit(lock);
  assert.equal(emit.triage_track, 'FULL');
  assert.equal(emit.triage.source, 'config');
});
