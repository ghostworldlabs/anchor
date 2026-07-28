// W10 / P7 — G0–G7 named release suite + human SC1 sign-off bound to G5 evidence.
// Unit test-command green alone does not claim release; runReleaseSuite does.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  GATE_CATALOG,
  GATE_IDS,
  runReleaseSuite,
  runG0Pack,
  runG5Pack,
  runG6Pack,
  runG7Pack,
  evaluateHumanSc1Signoff,
  loadHumanSc1SignoffChecklist,
  buildSignoffBoundReceipt,
  DEFAULT_SIGNOFF_PATH,
} = require('../src/release-suite.js');

const {
  assertCrossSurfaceDualWriteFinal,
} = require('../src/dual-write.js');

const {
  computeClassifierHealthMetrics,
} = require('../src/health-metrics.js');

const {
  currentHashes,
  receiptMatches,
} = require('../src/mode.js');

test('GATE_CATALOG covers G0–G7 with named tests', () => {
  for (const id of GATE_IDS) {
    assert.ok(GATE_CATALOG[id], id);
    assert.ok(GATE_CATALOG[id].length >= 1, `${id} has named tests`);
  }
  assert.ok(GATE_CATALOG.G5.includes('sc1_canary_gate'));
  assert.ok(GATE_CATALOG.G0.includes('test_dual_write_legacy_and_new_red_dark_until_armed'));
  assert.ok(GATE_CATALOG.G7.includes('test_sole_freeze_kill_service_boundary'));
});

test('cross-surface dual-write final asserts (shadow + armed joint)', () => {
  const shadow = assertCrossSurfaceDualWriteFinal({
    classifierMode: 'shadow',
    legacyWouldBeZombies: [{
      id: '1', name: 'claude.exe', count: 1, path: 'C:\\x\\claude.exe',
      providers: ['anthropic'], root: 'services.exe', supervised: false,
    }],
  });
  assert.strictEqual(shadow.ok, true, shadow.failures.join(','));
  assert.strictEqual(shadow.final, true);

  const hashes = currentHashes();
  const { resolveClassifierMode } = require('../src/mode.js');
  const armed = resolveClassifierMode({
    requestedMode: 'armed',
    receipt: {
      ...hashes,
      sc1CanaryGreen: true,
      sc1Gate: { green: true },
      evidencePaths: ['e'],
    },
  });
  assert.strictEqual(armed.mode, 'armed');
  const joint = assertCrossSurfaceDualWriteFinal({
    classifierMode: armed.mode,
    legacyWouldBeZombies: [{
      id: '1', name: 'claude.exe', count: 2, path: 'C:\\x\\claude.exe',
      providers: ['anthropic'], root: 'services.exe', supervised: false,
    }],
  });
  assert.strictEqual(joint.ok, true, joint.failures.join(','));
  assert.strictEqual(joint.jointWouldBe, true);
});

test('abstain-rate / unsupervised-spend TP health fields', () => {
  const metrics = computeClassifierHealthMetrics([
    {
      quadVerdict: 'ABSTAIN',
      reasonCodes: ['VERDICT_ABSTAIN'],
      unsupervised: false,
      spendPositive: false,
    },
    {
      quadVerdict: 'WOULD_BE_RED',
      wouldBeActionableRed: true,
      unsupervised: true,
      supervisionStatus: 'UNSUPERVISED',
      spendPositive: true,
      spendingNow: true,
    },
    {
      quadVerdict: 'KEEP',
      ownership: { owned: true, keep: true },
    },
  ]);
  assert.strictEqual(metrics.engineCount, 3);
  assert.strictEqual(metrics.abstainCount, 1);
  assert.ok(Math.abs(metrics.abstainRate - 1 / 3) < 1e-9);
  assert.strictEqual(metrics.unsupervisedSpendTruePositiveCount, 1);
  assert.strictEqual(metrics.health.unsupervisedSpendTp, 1);
  assert.ok(metrics.version.startsWith('w10'));
});

test('G0 and G7 release packs green', () => {
  const g0 = runG0Pack();
  assert.strictEqual(g0.ok, true, JSON.stringify(g0.namedTests));
  const g7 = runG7Pack();
  assert.strictEqual(g7.ok, true, JSON.stringify(g7.namedTests));
  const g6 = runG6Pack();
  assert.strictEqual(g6.ok, true, JSON.stringify(g6.namedTests));
});

test('E2E G0–G7 release suite + sc1_canary_gate', () => {
  const suite = runReleaseSuite();
  assert.strictEqual(suite.unitTestCommandCannotClaimRelease, true);
  assert.strictEqual(suite.sc1CanaryGate, true, 'sc1_canary_gate must be green in release suite');
  assert.strictEqual(suite.skillContract.ok, true, (suite.skillContract.failures || []).join('|'));
  assert.strictEqual(suite.ownershipUi.ok, true, (suite.ownershipUi.failures || []).join('|'));
  assert.strictEqual(suite.ok, true, `release failures: ${(suite.failures || []).join(',')}`);
  assert.strictEqual(suite.releaseClaim, true);
  for (const id of GATE_IDS) {
    assert.ok(suite.gates[id], id);
    assert.strictEqual(suite.gates[id].ok, true, `${id}: ${JSON.stringify(suite.gates[id].namedTests || suite.gates[id])}`);
  }
  assert.ok(suite.evidencePaths.length >= 4, 'G5 evidence paths');
  assert.ok(suite.humanSc1Signoff.ok, JSON.stringify(suite.humanSc1Signoff));
});

test('human SC1 sign-off checklist bound to same G5 evidence paths + receipt hash', () => {
  const checklist = loadHumanSc1SignoffChecklist(DEFAULT_SIGNOFF_PATH);
  assert.strictEqual(checklist.missing, false);
  assert.ok(checklist.items.length >= 4);
  assert.ok(checklist.items.some((i) => i.id === 'receipt_hash_tuple'));
  assert.ok(checklist.items.some((i) => i.id === 'g5_evidence_paths_bound'));

  const g5 = runG5Pack();
  assert.strictEqual(g5.ok, true);
  const receipt = buildSignoffBoundReceipt(g5);
  assert.ok(receiptMatches(receipt, g5.hashes || currentHashes()));

  const signoff = evaluateHumanSc1Signoff({
    evidencePaths: g5.evidencePaths,
    hashes: g5.hashes,
    sc1GateGreen: true,
    receipt,
  });
  assert.strictEqual(signoff.ok, true, JSON.stringify(signoff.items));
  assert.strictEqual(signoff.receiptBound, true);
  assert.deepStrictEqual(signoff.evidencePaths, g5.evidencePaths);
  // Sign-off never claims Freeze/Kill enablement
  assert.ok(signoff.items.every((i) => i.id !== 'enable_freeze_kill'));
  const freezeItem = signoff.items.find((i) => i.id === 'freeze_kill_not_implied_by_signoff');
  assert.ok(freezeItem && freezeItem.pass);
});
