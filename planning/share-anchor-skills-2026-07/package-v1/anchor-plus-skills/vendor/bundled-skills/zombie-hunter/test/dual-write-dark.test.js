// G0 / Wave 1 — Dual-write dark + shadow-mode force.
// Production modules: mode.js + dual-write.js (server/classify path imports the same).

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  resolveClassifierMode,
  receiptMatches,
  currentHashes,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  getModePublicStatus,
  CLASSIFIER_VERSION,
} = require('../src/mode.js');

const {
  SURFACES,
  buildObserveDualRun,
  evaluateDualWriteSurfaces,
  applyDualWriteToBuckets,
  assertNoActionableRedUnderShadow,
  observeOnlyBannerCopy,
  assertCrossSurfaceDualWriteFinal,
} = require('../src/dual-write.js');

/** Synthetic legacy would-be zombie groups (spending + unsupervised shape). */
function fakeWouldBeZombies(n = 2) {
  return [
    {
      id: 'claude-orphan',
      name: 'claude.exe',
      path: 'C:\\Users\\x\\claude.exe',
      count: n,
      providers: ['anthropic'],
      root: 'services.exe',
      supervised: false,
      parentAlive: true,
      pids: Array.from({ length: n }, (_, i) => String(9000 + i)),
      conns: 3,
      spendAgoMin: 0,
      sample: 'claude.exe -p',
    },
  ];
}

test('test_dual_write_legacy_and_new_red_dark_until_armed', () => {
  // Default / shadow: every dual-write surface non-actionable; observe dual-run still lit.
  const mode = resolveClassifierMode({ requestedMode: 'shadow', receipt: null });
  assert.strictEqual(mode.mode, 'shadow');
  assert.strictEqual(isActionableRedAllowed(mode.mode), false);

  const legacy = fakeWouldBeZombies(2);
  const neu = fakeWouldBeZombies(2);
  const dual = evaluateDualWriteSurfaces({
    classifierMode: mode.mode,
    legacyWouldBeZombies: legacy,
    newWouldBeZombies: neu,
  });

  assert.strictEqual(dual.observe.wouldBeActionableRed, true, 'dark ≠ silence: would-be still visible');
  assert.ok(dual.observe.wouldBeCount >= 2);
  assert.ok(dual.observe.reasonCodes.includes('SHADOW_OBSERVE_ONLY'));
  assert.strictEqual(dual.anySurfaceActionableRed, false);
  assert.strictEqual(dual.freezeKillChrome, false);

  for (const name of SURFACES) {
    const s = dual.surfaces[name];
    assert.ok(s, `surface ${name} present`);
    assert.strictEqual(s.actionableRed, false, `${name} must not be actionable under shadow`);
    assert.strictEqual(s.actionableCount, 0, `${name} actionableCount 0`);
    assert.strictEqual(s.scareLanguageAllowed, false, `${name} no scare language`);
    assert.strictEqual(s.observeOnly, true);
  }

  // Server bucket path: actionable zombie list emptied; observe retained.
  const buck = applyDualWriteToBuckets(
    { zombie: legacy, active: [], idleCount: 0 },
    'shadow',
  );
  assert.deepStrictEqual(buck.zombie, [], 'legacy radar actionable tiles dark');
  assert.strictEqual(buck.observe.wouldBeActionableRed, true);
  assert.ok(assertNoActionableRedUnderShadow(buck.dualWrite));

  // New classifier surface same law (dual-write matrix).
  assert.strictEqual(buck.dualWrite.surfaces.new_classifier.actionableRed, false);
  assert.strictEqual(buck.dualWrite.surfaces.dashboard_zombie_banner.actionableRed, false);
  assert.strictEqual(buck.dualWrite.surfaces.reaper_health_scare.actionableRed, false);
  assert.strictEqual(buck.dualWrite.surfaces.legacy_radar.actionableRed, false);

  // Banner copy must not use actionable zombie scare under shadow.
  const copy = observeOnlyBannerCopy(buck.observe);
  assert.ok(/observe-only/i.test(copy), 'observe-only copy');
  assert.ok(!/token-spending zombie/i.test(copy), 'no scare zombie language on observe banner');
});

test('test_red_impossible_until_joint_release', () => {
  // Skeleton + production: without armed+receipt, RED impossible on all surfaces
  // even when legacy would-be list is non-empty.
  const attempts = [
    resolveClassifierMode({ requestedMode: 'shadow', receipt: null }),
    resolveClassifierMode({ requestedMode: 'armed', receipt: null }),
    resolveClassifierMode({ requestedMode: 'armed', receipt: { classifierVersion: 'wrong' } }),
    resolveClassifierMode({ requestedMode: 'armed_partial', receipt: null }),
    resolveClassifierMode({ requestedMode: 'armed_global', receipt: {} }),
  ];
  for (const r of attempts) {
    assert.strictEqual(r.mode, 'shadow', `mode forced shadow for reason=${r.reason}`);
    assert.strictEqual(isActionableRedAllowed(r.mode), false);
    const dual = evaluateDualWriteSurfaces({
      classifierMode: r.mode,
      legacyWouldBeZombies: fakeWouldBeZombies(5),
    });
    assert.strictEqual(dual.anySurfaceActionableRed, false, r.reason);
    assert.ok(assertNoActionableRedUnderShadow(dual));
    assert.strictEqual(isFreezeKillAllowed(r.mode, false), false);
    assert.strictEqual(isFreezeKillAllowed(r.mode, true), false, 'shadow + capability still refuses Freeze/Kill');
  }

  // Perfect SC1 canary receipt allows armed RED chrome; Freeze/Kill still need freezeCapability.
  const hashes = currentHashes();
  const goodReceipt = {
    ...hashes,
    evidencePaths: ['g0'],
    issuedAt: new Date().toISOString(),
    sc1CanaryGreen: true,
    sc1Gate: { green: true },
  };
  assert.ok(receiptMatches(goodReceipt, hashes));
  const armed = resolveClassifierMode({ requestedMode: 'armed', receipt: goodReceipt });
  assert.strictEqual(armed.mode, 'armed');
  assert.strictEqual(armed.receiptValid, true);
  // Actionable RED allowed only when armed+receipt — joint release path open for chrome later.
  assert.strictEqual(isActionableRedAllowed(armed.mode), true);
  // W6: Freeze/Kill require freezeCapability on the sole boundary (not SC1 alone).
  assert.strictEqual(isFreezeKillAllowed(armed.mode, false), false);
  assert.strictEqual(isFreezeKillAllowed(armed.mode, true), true);
});

test('armed without version-matched canaryReceipt is forced back to shadow', () => {
  const hashes = currentHashes();
  const bad = {
    classifierVersion: 'other',
    hostAllowlistHash: hashes.hostAllowlistHash,
    engineAtlasHash: hashes.engineAtlasHash,
    spendAtlasHash: hashes.spendAtlasHash,
  };
  const r = resolveClassifierMode({ requestedMode: 'armed', receipt: bad });
  assert.strictEqual(r.mode, 'shadow');
  assert.strictEqual(r.forced, true);
  assert.strictEqual(r.reason, 'refuse_armed_without_version_matched_receipt');
  assert.strictEqual(r.receiptValid, false);

  // Env path: ZH_CLASSIFIER_MODE=armed with no receipt file → shadow.
  const prev = process.env.ZH_CLASSIFIER_MODE;
  const prevPath = process.env.ZH_CANARY_RECEIPT_PATH;
  try {
    process.env.ZH_CLASSIFIER_MODE = 'armed';
    delete process.env.ZH_CANARY_RECEIPT_PATH;
    const envR = resolveClassifierMode({});
    assert.strictEqual(envR.mode, 'shadow');
    assert.strictEqual(envR.forced, true);
  } finally {
    if (prev === undefined) delete process.env.ZH_CLASSIFIER_MODE;
    else process.env.ZH_CLASSIFIER_MODE = prev;
    if (prevPath === undefined) delete process.env.ZH_CANARY_RECEIPT_PATH;
    else process.env.ZH_CANARY_RECEIPT_PATH = prevPath;
  }
});

test('version-matched canaryReceipt on disk allows armed eligibility resolve', () => {
  const hashes = currentHashes();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zh-receipt-'));
  const receiptPath = path.join(dir, 'canaryReceipt.json');
  fs.writeFileSync(receiptPath, JSON.stringify({
    ...hashes,
    evidencePaths: ['test'],
    issuedAt: new Date().toISOString(),
    sc1CanaryGreen: true,
    sc1Gate: { green: true },
  }));
  try {
    const r = resolveClassifierMode({
      requestedMode: 'armed',
      receiptPath,
    });
    assert.strictEqual(r.mode, 'armed');
    assert.strictEqual(r.forced, false);
    assert.strictEqual(r.receiptValid, true);
    assert.strictEqual(CLASSIFIER_VERSION, hashes.classifierVersion);

    // Public status under forced default (no env) stays shadow.
    const pub = getModePublicStatus({ requestedMode: 'shadow', receipt: null });
    assert.strictEqual(pub.classifierMode, 'shadow');
    assert.strictEqual(pub.freezeKillEnabled, false);
    assert.strictEqual(pub.actionableRedAllowed, false);
  } finally {
    try { fs.unlinkSync(receiptPath); } catch (_) {}
    try { fs.rmdirSync(dir); } catch (_) {}
  }
});

test('buildObserveDualRun empty and non-empty', () => {
  const empty = buildObserveDualRun({ legacyWouldBeZombies: [] });
  assert.strictEqual(empty.wouldBeActionableRed, false);
  assert.ok(empty.reasonCodes.includes('NO_WOULD_BE_RED'));

  const lit = buildObserveDualRun({ legacyWouldBeZombies: fakeWouldBeZombies(1) });
  assert.strictEqual(lit.wouldBeActionableRed, true);
  assert.ok(lit.reasonCodes.includes('WOULD_BE_ACTIONABLE_RED'));
  assert.ok(lit.items.every((it) => it.observeOnly && it.actionable === false));
});

// W10 / P7 — cross-surface dual-write final asserts
test('test_cross_surface_dual_write_final', () => {
  const final = assertCrossSurfaceDualWriteFinal({
    classifierMode: 'shadow',
    legacyWouldBeZombies: fakeWouldBeZombies(2),
  });
  assert.strictEqual(final.ok, true, (final.failures || []).join(','));
  assert.strictEqual(final.final, true);
  assert.strictEqual(final.dual.anySurfaceActionableRed, false);
  assert.ok(final.dual.observe.wouldBeActionableRed);
});
