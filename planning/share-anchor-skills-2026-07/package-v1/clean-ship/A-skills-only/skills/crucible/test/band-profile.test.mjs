// band-profile.test.mjs — complexity bands for cf-slick (2026-07-22)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeBandDepth,
  resolveBandProfile,
  bandProfileStamp,
} from '../bin/band-profile.mjs';

test('normalizeBandDepth: pin + aliases', () => {
  assert.equal(normalizeBandDepth('LITE'), 'LITE');
  assert.equal(normalizeBandDepth('light'), 'LITE');
  assert.equal(normalizeBandDepth('SPIKE-FIRST'), 'SPIKE-FIRST');
  assert.equal(normalizeBandDepth('spike'), 'SPIKE-FIRST');
  assert.equal(normalizeBandDepth('MID'), 'SPIKE-FIRST', 'MID is mid-band not silent LITE');
  assert.equal(normalizeBandDepth('STANDARD'), 'SPIKE-FIRST');
  assert.equal(normalizeBandDepth('FULL'), 'FULL');
  assert.equal(normalizeBandDepth(''), 'FULL');
});

test('LITE profile: short ceremony (journal 0022)', () => {
  const p = resolveBandProfile('LITE');
  assert.equal(p.depth, 'LITE');
  assert.equal(p.roundCap, 1);
  assert.equal(p.skipFullOrangesBrainstorm, true);
  assert.equal(p.requireSpikeProbe, false);
  assert.ok(p.maxModelCallsHint <= 12);
  assert.ok(p.sharkRoles >= 2, 'pair still allows ≥2-agree when Sharks run');
  assert.equal(p.foremanReviewersDefault, 1);
});

test('SPIKE-FIRST profile: probe required, mid caps', () => {
  const p = resolveBandProfile('SPIKE-FIRST');
  assert.equal(p.requireSpikeProbe, true);
  assert.equal(p.skipFullOrangesBrainstorm, false);
  assert.equal(p.roundCap, 2);
  assert.ok(p.maxModelCallsHint > resolveBandProfile('LITE').maxModelCallsHint);
});

test('FULL profile: full ceremony', () => {
  const p = resolveBandProfile('FULL');
  assert.equal(p.skipFullOrangesBrainstorm, false);
  assert.equal(p.roundCap, 5);
  assert.equal(p.sharkRoles, 3);
  assert.equal(p.foremanReviewersDefault, 2);
});

test('LITE is strictly lighter than FULL on key axes', () => {
  const L = resolveBandProfile('LITE');
  const F = resolveBandProfile('FULL');
  assert.ok(L.roundCap < F.roundCap);
  assert.ok(L.maxModelCallsHint < F.maxModelCallsHint);
  assert.notEqual(L.skipFullOrangesBrainstorm, F.skipFullOrangesBrainstorm);
});

test('bandProfileStamp is journal-safe', () => {
  const s = bandProfileStamp(resolveBandProfile('LITE'));
  assert.equal(s.depth, 'LITE');
  assert.equal(typeof s.band_profile, 'string');
  assert.equal(s.skipFullOrangesBrainstorm, true);
});

test('overrides win for explicit operator extend', () => {
  const p = resolveBandProfile('LITE', { roundCap: 3 });
  assert.equal(p.roundCap, 3);
  assert.equal(p.depth, 'LITE');
});

test('runStage1 SPIKE without probe HALTs (Wave D)', async () => {
  const { runStage1 } = await import('../bin/stage1.mjs');
  const { HaltError } = await import('../bin/crucible-lib.mjs');
  await assert.rejects(
    () => runStage1({
      agent: async () => ({}),
      northStar: 'NS',
      depth: 'SPIKE-FIRST',
      approved: false,
    }),
    (e) => e instanceof HaltError && /spikeProbe|SPIKE-FIRST/i.test(e.reason || e.message || ''),
  );
});
