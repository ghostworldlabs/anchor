// W5 / G4–G6 — SC1 canary pack, residual attestation, arm receipt.

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  runRecordedHostTreesZeroRed,
  runOrphanPositiveControl,
  runLiveInteractiveCanary,
  runResidualAttestationOrLiveMatrix,
  runSc1CanaryGate,
  writeSc1CanaryReceiptFromGate,
  runtimeArmRequiresVersionMatchedCanaryReceipt,
  shadowToArmedRequiresSc1Canary,
  runAtlasBumpForcesReshadow,
  evaluateHostAttestation,
  loadHostAttestation,
  loadHostClassArmEligibility,
  loadOperatorLabChecklist,
  buildCanaryReceipt,
  writeCanaryReceipt,
  currentHashes,
  resolveClassifierMode,
  receiptMatches,
  receiptAllowsArm,
  isActionableRedAllowed,
  isFreezeKillAllowed,
  SURFACES,
  DEFAULT_ATTESTATION_PATH,
  SC1_RECORDED_HOST_CLASSES,
} = require('../src/sc1-canary.js');

const {
  getModePublicStatus,
  defaultReceiptPath,
} = require('../src/mode.js');

test('test_sc1_recorded_host_trees_zero_red', () => {
  const pack = runRecordedHostTreesZeroRed();
  assert.strictEqual(pack.ok, true, 'all recorded interactive trees must KEEP with zero dual-run RED');
  assert.strictEqual(pack.redCount, 0);
  assert.ok(pack.results.length >= 4, 'VS Code, Cursor, WT, Anchor');
  const classes = new Set(pack.results.map((r) => r.hostClass));
  for (const hc of SC1_RECORDED_HOST_CLASSES) {
    assert.ok(classes.has(hc), `missing host class ${hc}`);
  }
  for (const r of pack.results) {
    assert.strictEqual(r.supervised, true, `${r.fixtureId} SUPERVISED`);
    assert.strictEqual(r.wouldBeActionableRed, false, `${r.fixtureId} dual-run would-be RED must be 0`);
    assert.strictEqual(r.anySurfaceActionableRed, false, `${r.fixtureId} no actionable chrome`);
    assert.strictEqual(r.bannerRed, false);
    assert.strictEqual(r.tileRed, false);
    assert.strictEqual(r.reaperRed, false);
    assert.ok(
      r.quadVerdict === 'KEEP',
      `${r.fixtureId} must KEEP (not dark-only theater), got ${r.quadVerdict}`,
    );
  }
});

test('test_sc1_interactive_zero_red', () => {
  // Live canary harness on operator-visible banner + tile surfaces.
  const live = runLiveInteractiveCanary();
  assert.strictEqual(live.found, true);
  assert.strictEqual(live.ok, true, 'live/live-shaped interactive zero false RED');
  assert.strictEqual(live.falseRedCount, 0);
  assert.strictEqual(live.actionableRedCount, 0);
  assert.ok(live.surfaces.includes('legacy_radar'));
  assert.ok(live.surfaces.includes('dashboard_zombie_banner'));
  assert.ok(live.surfaces.includes('reaper_health_scare'));
  if (live.bannerTileSurfaces) {
    assert.strictEqual(live.bannerTileSurfaces.dashboard_zombie_banner.actionableRed, false);
    assert.strictEqual(live.bannerTileSurfaces.legacy_radar.actionableRed, false);
    assert.strictEqual(live.bannerTileSurfaces.reaper_health_scare.actionableRed, false);
  }
});

test('sc1_canary_gate OL1 orphan positive control ORPHAN_DETACHED_SPENDER', () => {
  const orphan = runOrphanPositiveControl();
  assert.strictEqual(orphan.ok, true);
  assert.strictEqual(orphan.name, 'ORPHAN_DETACHED_SPENDER');
  assert.strictEqual(orphan.unsupervised, true);
  assert.strictEqual(orphan.wouldBeActionableRed, true, 'dual-run would-be RED required (not vacuous SC1)');
  assert.strictEqual(orphan.dualRunWouldBe, true);
  assert.strictEqual(orphan.surfacesDark, true, 'shadow surfaces stay non-actionable');
  assert.strictEqual(orphan.quadVerdict, 'WOULD_BE_RED');
});

test('test_sc1_host_attestation_or_live_matrix', () => {
  // Residual via on-disk attestation
  const residual = runResidualAttestationOrLiveMatrix();
  assert.strictEqual(residual.ok, true, residual.reason);
  assert.strictEqual(residual.canMintGlobalArm, false, 'attestation cannot mint global arm');
  assert.ok(residual.hosts.length >= 1);

  // Live matrix alternative
  const matrix = runResidualAttestationOrLiveMatrix({
    liveMatrix: {
      hosts: [
        { hostClass: 'code-insiders', zeroRed: true },
        { hostClass: 'openconsole', zeroRed: true },
      ],
    },
  });
  assert.strictEqual(matrix.ok, true);
  assert.strictEqual(matrix.source, 'live_matrix');
  assert.strictEqual(matrix.canMintGlobalArm, false);

  // Schema validation on loaded file
  const att = loadHostAttestation(DEFAULT_ATTESTATION_PATH);
  assert.ok(att);
  const ev = evaluateHostAttestation(att);
  assert.strictEqual(ev.ok, true);
  assert.strictEqual(ev.canMintGlobalArm, false);
});

test('sc1_canary_gate green (recorded ∧ live ∧ orphan ∧ residual)', () => {
  const gate = runSc1CanaryGate();
  assert.strictEqual(gate.green, true, JSON.stringify(gate.summary));
  assert.strictEqual(gate.sc1_canary_gate, true);
  assert.strictEqual(gate.sc1Claimed, true);
  assert.strictEqual(gate.recorded.ok, true);
  assert.strictEqual(gate.live.ok, true);
  assert.strictEqual(gate.orphan.ok, true);
  assert.strictEqual(gate.residual.ok, true);
  assert.strictEqual(gate.summary.residualCannotMintGlobalArm, true);
  assert.strictEqual(gate.summary.freezeKillEnabled, false);
  assert.ok(gate.evidencePaths.length >= 4, 'G5 evidence paths present');
  assert.ok(gate.checklist.ok, 'OL3 checklist');
  const armMeta = loadHostClassArmEligibility();
  assert.strictEqual(armMeta.residualCannotMintGlobalArm, true);
  assert.strictEqual(armMeta.globalArmRequiresSc1Gate, true);
  const checklist = loadOperatorLabChecklist();
  assert.ok(Array.isArray(checklist.items) && checklist.items.length >= 5);
});

test('canaryReceipt writer matches hash tuple + G5 evidence path', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'zh-sc1-receipt-'));
  const receiptPath = path.join(dir, 'canaryReceipt.json');
  const evidenceDir = path.join(dir, 'evidence');
  try {
    const out = writeSc1CanaryReceiptFromGate({ receiptPath, evidenceDir });
    assert.strictEqual(out.ok, true, out.reason);
    assert.ok(out.write && out.write.receipt);
    const r = out.write.receipt;
    const h = currentHashes();
    assert.strictEqual(r.classifierVersion, h.classifierVersion);
    assert.strictEqual(r.hostAllowlistHash, h.hostAllowlistHash);
    assert.strictEqual(r.engineAtlasHash, h.engineAtlasHash);
    assert.strictEqual(r.spendAtlasHash, h.spendAtlasHash);
    assert.strictEqual(r.sc1CanaryGreen, true);
    assert.ok(Array.isArray(r.evidencePaths) && r.evidencePaths.length > 0);
    assert.strictEqual(r.freezeKillEnabled, false);
    assert.ok(receiptMatches(r, h));
    assert.ok(receiptAllowsArm(r, h));

    // Disk round-trip
    const loaded = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
    const armed = resolveClassifierMode({
      requestedMode: 'armed',
      receipt: loaded,
    });
    assert.strictEqual(armed.mode, 'armed');
    assert.strictEqual(armed.sc1Claimed, true);
    // W6: SC1 arm does not alone enable Freeze/Kill without capability.
    assert.strictEqual(isFreezeKillAllowed(armed.mode, false), false);
    assert.strictEqual(isFreezeKillAllowed(armed.mode, true), true);
  } finally {
    try { fs.unlinkSync(receiptPath); } catch (_) {}
    try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) {}
  }
});

test('test_runtime_arm_requires_version_matched_canary_receipt', () => {
  const r = runtimeArmRequiresVersionMatchedCanaryReceipt();
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.missing.mode, 'shadow');
  assert.strictEqual(r.mismatched.mode, 'shadow');
  assert.strictEqual(r.armed.mode, 'armed');
  assert.strictEqual(isActionableRedAllowed(r.armed.mode), true);
  assert.strictEqual(isFreezeKillAllowed(r.armed.mode, false), false);
  assert.strictEqual(isFreezeKillAllowed(r.armed.mode, true), true);
});

test('test_shadow_to_armed_requires_sc1_canary', () => {
  const r = shadowToArmedRequiresSc1Canary();
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.withoutSc1.mode, 'shadow');
  assert.strictEqual(r.withoutSc1.reason, 'refuse_armed_without_sc1_canary');
  assert.strictEqual(r.withSc1.mode, 'armed');
  assert.strictEqual(r.withSc1.sc1Claimed, true);

  // Hash-matched receipt without SC1 green still forces shadow at runtime.
  const hashes = currentHashes();
  const hashOnly = { ...hashes, evidencePaths: ['x'] };
  assert.ok(receiptMatches(hashOnly, hashes));
  assert.strictEqual(receiptAllowsArm(hashOnly, hashes), false);
  const mode = resolveClassifierMode({ requestedMode: 'armed', receipt: hashOnly });
  assert.strictEqual(mode.mode, 'shadow');
});

test('test_atlas_bump_forces_reshadow', () => {
  const r = runAtlasBumpForcesReshadow();
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.match.forceReshadow, false);
  assert.strictEqual(r.bumpedSpend.forceReshadow, true);
  assert.ok(r.bumpedSpend.bumped.includes('spendAtlasHash'));
  assert.strictEqual(r.reshadow.mode, 'shadow');
  assert.strictEqual(r.reshadow.forced, true);
});

test('residual attestation alone cannot mint global arm / receipt', () => {
  const residualOk = runResidualAttestationOrLiveMatrix();
  assert.strictEqual(residualOk.ok, true);
  assert.strictEqual(residualOk.canMintGlobalArm, false);

  // Force residual-only path: gate with failing recorded by empty hostClasses
  // is not used; instead assert writeCanaryReceipt refuses without sc1 green.
  const refused = writeCanaryReceipt(path.join(os.tmpdir(), 'zh-no-write-receipt.json'), {
    sc1CanaryGreen: false,
    sc1Gate: { green: false },
    evidencePaths: [],
  });
  assert.strictEqual(refused.ok, false);
  assert.strictEqual(refused.reason, 'refuse_write_without_sc1_canary_green');
});

test('SC1 owned + arm-eligible only after operator arm; Freeze/Kill still off', () => {
  const gate = runSc1CanaryGate();
  assert.strictEqual(gate.sc1Claimed, true);

  const good = buildCanaryReceipt({
    sc1CanaryGreen: true,
    sc1Gate: gate.summary,
    evidencePaths: gate.evidencePaths,
  });
  // Receipt present does not auto-arm — default/requested shadow stays shadow.
  const shadow = resolveClassifierMode({ requestedMode: 'shadow', receipt: good });
  assert.strictEqual(shadow.mode, 'shadow');
  assert.strictEqual(shadow.sc1Claimed, true);
  assert.strictEqual(isActionableRedAllowed(shadow.mode), false);

  // Operator arm with valid SC1 receipt → armed eligible
  const armed = resolveClassifierMode({ requestedMode: 'armed', receipt: good });
  assert.strictEqual(armed.mode, 'armed');
  assert.strictEqual(armed.receiptValid, true);

  const pub = getModePublicStatus({
    requestedMode: 'armed',
    receipt: good,
    freezeCapability: false,
  });
  assert.strictEqual(pub.sc1Claimed, true);
  assert.strictEqual(pub.freezeKillEnabled, false);
  assert.strictEqual(pub.canaryReceipt.valid, true);
  assert.strictEqual(pub.canaryReceipt.sc1CanaryGreen, true);

  // defaultReceiptPath is under skill root (not auto-written in this unit)
  assert.ok(defaultReceiptPath().endsWith('canaryReceipt.json'));
  for (const s of SURFACES) {
    assert.ok(typeof s === 'string');
  }
});
