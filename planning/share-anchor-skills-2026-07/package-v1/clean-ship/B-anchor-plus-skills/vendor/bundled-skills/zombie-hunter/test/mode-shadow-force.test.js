// G0 / Wave 1 — classifierMode force + freeze/kill refuse scaffolding.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  resolveClassifierMode,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  getModePublicStatus,
  currentHashes,
  receiptMatches,
  loadCanaryReceipt,
} = require('../src/mode.js');

const { applyDualWriteToBuckets } = require('../src/dual-write.js');

test('default mode is shadow with no receipt', () => {
  const r = resolveClassifierMode({ requestedMode: undefined, receipt: null });
  assert.strictEqual(r.mode, 'shadow');
  assert.strictEqual(isActionableRedAllowed(r.mode), false);
  const pub = getModePublicStatus({ requestedMode: 'shadow', receipt: null, freezeCapability: false });
  assert.strictEqual(pub.classifierMode, 'shadow');
  assert.strictEqual(pub.freezeKillEnabled, false);
  assert.strictEqual(pub.freezeCapability, false);
  assert.deepStrictEqual(pub.canaryReceipt, {
    present: false,
    valid: false,
    matchedHashes: false,
    sc1CanaryGreen: false,
  });
  assert.strictEqual(pub.sc1Claimed, false);
});

test('loadCanaryReceipt missing path returns null', () => {
  assert.strictEqual(loadCanaryReceipt(null), null);
  assert.strictEqual(loadCanaryReceipt('C:\\definitely\\not\\a\\receipt-zh-g0.json'), null);
});

test('receiptMatches requires full hash tuple', () => {
  const h = currentHashes();
  assert.strictEqual(receiptMatches(null, h), false);
  assert.strictEqual(receiptMatches({}, h), false);
  assert.strictEqual(receiptMatches(h, h), true);
  assert.strictEqual(receiptMatches({ ...h, spendAtlasHash: 'x' }, h), false);
});

test('server dual-write buckets export: shadow empties zombies', () => {
  const raw = {
    zombie: [{ id: 'z1', name: 'claude.exe', count: 1, pids: ['1'], ages: [1], providers: ['anthropic'], root: 'services.exe', supervised: false }],
    active: [{ id: 'a1', name: 'claude.exe', count: 1, pids: ['2'], ages: [1], providers: ['anthropic'], root: 'Code.exe', supervised: true }],
    idleCount: 3,
  };
  const out = applyDualWriteToBuckets(raw, 'shadow');
  assert.strictEqual(out.zombie.length, 0);
  assert.strictEqual(out.active.length, 1);
  assert.strictEqual(out.idleCount, 3);
  assert.strictEqual(out.classifierMode, 'shadow');
  assert.strictEqual(out.dualWrite.surfaces.dashboard_zombie_banner.actionableRed, false);
  assert.strictEqual(out.dualWrite.surfaces.reaper_health_scare.actionableRed, false);

  // When armed (caller already resolved mode), actionable list passes through.
  const armedOut = applyDualWriteToBuckets(raw, 'armed');
  assert.strictEqual(armedOut.zombie.length, 1);
  assert.strictEqual(armedOut.dualWrite.surfaces.legacy_radar.actionableRed, true);
  // W6: Freeze/Kill allowed only when armed + freezeCapability proven.
  assert.strictEqual(isFreezeKillAllowed('armed', false), false);
  assert.strictEqual(isFreezeKillAllowed('armed', true), true);
  assert.strictEqual(isFreezeKillAllowed('shadow', true), false);
});
