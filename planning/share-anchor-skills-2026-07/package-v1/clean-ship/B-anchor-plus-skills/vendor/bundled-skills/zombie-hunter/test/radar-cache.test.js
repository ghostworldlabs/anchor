// W7 / SC4 — Cache-first radar, JSON-safe sweep, Why min payload.

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  hasUnsafeControlChars,
  sanitizeControlChars,
  sanitizeProcessFields,
  jsonSafeStringify,
  parseSweepJson,
} = require('../src/json-safe.js');

const {
  PAINT_BUDGET_MS,
  LAST_KNOWN_SCHEMA,
  RECOMMENDED_NEXT,
  computeCacheAgeMs,
  buildLastKnownSnapshot,
  writeDurableLastKnown,
  loadDurableLastKnown,
  suppressActionableCachedRed,
  recommendNext,
  buildWhyMinPayload,
  buildRadarServerFields,
  paintRadarFromCache,
  identityActionGate,
  crossSurfaceNoRedOnAbstain,
} = require('../src/radar-cache.js');

const {
  evaluateDualWriteSurfaces,
  applyDualWriteToBuckets,
  assertNoActionableRedUnderShadow,
} = require('../src/dual-write.js');

const { isActionableRedAllowed } = require('../src/mode.js');
const { isKnownReasonCode } = require('../src/reason-catalog.js');

function tmpPath(name) {
  return path.join(os.tmpdir(), `zh-w7-${process.pid}-${Date.now()}-${name}`);
}

function wouldBeZombieGroup() {
  return [{
    id: 'orphan-claude',
    name: 'claude.exe',
    path: 'C:\\Users\\x\\claude.exe',
    count: 2,
    providers: ['anthropic'],
    root: 'services.exe',
    supervised: false,
    parentAlive: true,
    pids: ['9001', '9002'],
    conns: 2,
    spendAgoMin: 0,
    sample: 'claude.exe -p',
    reasonCodes: ['WOULD_BE_ACTIONABLE_RED', 'QUAD_JOINT_POSITIVE'],
    quadVerdict: 'WOULD_BE_RED',
    wouldBeActionableRed: true,
  }];
}

// ── test_cache_no_actionable_red ──
test('test_cache_no_actionable_red', () => {
  const legacy = wouldBeZombieGroup();

  // Shadow: dual-write already dark
  const shadow = suppressActionableCachedRed(
    { zombie: legacy, active: [], idleCount: 0 },
    { classifierMode: 'shadow', fromCache: true },
  );
  assert.deepStrictEqual(shadow.zombie, []);
  assert.strictEqual(shadow.actionableRed, false);
  assert.strictEqual(shadow.anySurfaceActionableRed, false);
  assert.ok(shadow.observe.wouldBeActionableRed, 'dark ≠ silence');
  assert.ok(assertNoActionableRedUnderShadow(shadow.dualWrite));

  // Warm cache with RED-shaped rows + sweepError ⇒ still no actionable RED
  const errSup = suppressActionableCachedRed(
    { zombie: legacy, active: [], idleCount: 0 },
    { classifierMode: 'armed', sweepError: 'parse failed', fromCache: true, forceNonActionable: true },
  );
  assert.deepStrictEqual(errSup.zombie, []);
  assert.strictEqual(errSup.actionableRed, false);
  assert.strictEqual(errSup.suppressReason, 'sweep_error_abstain');

  // Durable snapshot forces non-actionable
  const snap = buildLastKnownSnapshot({
    buckets: applyDualWriteToBuckets(
      { zombie: legacy, active: [], idleCount: 1 },
      'shadow',
    ),
    lastSweepAt: new Date().toISOString(),
    classifierMode: 'shadow',
  });
  assert.strictEqual(snap.actionableRed, false);
  assert.strictEqual(snap.counts.zombieActionable, 0);
  assert.ok(snap.tiles.every((t) => t.actionable === false));

  // Cache-only identity refused for freeze/kill
  const gate = identityActionGate({ pid: 9001, fromCache: true, cacheOnly: true });
  assert.strictEqual(gate.allow, false);
  assert.strictEqual(gate.reason, 'CACHE_ONLY_IDENTITY_REFUSED');
  const incomplete = identityActionGate({ pid: 9001 });
  assert.strictEqual(incomplete.allow, false);
  const complete = identityActionGate({
    pid: 9001,
    createTime: 1_700_000_000_000,
    imagePath: 'C:\\lab\\claude.exe',
  });
  assert.strictEqual(complete.allow, true);
});

// ── test_radar_cold_paint_under_1s ──
test('test_radar_cold_paint_under_1s', () => {
  const paint = paintRadarFromCache({
    // no snapshot, no lastKnownPath ⇒ pure cold skeleton
    classifierMode: 'shadow',
    freezeCapability: false,
    sweepInProgress: true,
  });
  assert.strictEqual(paint.paintPath, 'cold');
  assert.strictEqual(paint.shell.skeleton, true);
  assert.strictEqual(paint.shell.actionableRed, false);
  assert.strictEqual(paint.blockedOnFullSweep, false);
  assert.strictEqual(paint.fullSweepBackgroundOnly, true);
  assert.ok(paint.paintMs <= PAINT_BUDGET_MS, `cold paint ${paint.paintMs}ms > ${PAINT_BUDGET_MS}`);
  assert.ok(paint.withinBudget);
  assert.ok(paint.serverFields.cacheAge == null || paint.serverFields.cacheAge >= 0);
  assert.strictEqual(paint.serverFields.classifierMode, 'shadow');
  // Shell UI copy keys present
  assert.ok(paint.shell.uiCopy.uncertainNotRed);
  assert.ok(paint.shell.uiCopy.freezeBeforeKill);
});

// ── test_radar_warm_paint_under_1s ──
test('test_radar_warm_paint_under_1s', () => {
  const file = tmpPath('last-known.json');
  try {
    const legacy = wouldBeZombieGroup();
    const buckets = applyDualWriteToBuckets(
      { zombie: legacy, active: [{ id: 'a', name: 'code.exe', count: 1, path: 'C:\\code.exe' }], idleCount: 3 },
      'shadow',
    );
    const written = writeDurableLastKnown(file, {
      buckets,
      lastSweepAt: new Date(Date.now() - 5_000).toISOString(),
      lastSweepMs: 12_000,
      classifierMode: 'shadow',
      atlasHealth: 'OK',
      reasonCodes: ['SHADOW_OBSERVE_ONLY'],
    });
    assert.strictEqual(written.ok, true);

    const paint = paintRadarFromCache({
      lastKnownPath: file,
      classifierMode: 'shadow',
      freezeCapability: false,
      atlasHealth: 'OK',
      canaryReceipt: { present: false, valid: false },
    });
    assert.strictEqual(paint.paintPath, 'warm');
    assert.strictEqual(paint.shell.skeleton, false);
    assert.strictEqual(paint.shell.hasLastKnown, true);
    assert.strictEqual(paint.shell.actionableRed, false);
    assert.strictEqual(paint.shell.counts.actionableRed, 0);
    assert.ok(paint.paintMs <= PAINT_BUDGET_MS, `warm paint ${paint.paintMs}ms > ${PAINT_BUDGET_MS}`);
    assert.ok(paint.withinBudget);
    assert.ok(paint.serverFields.cacheAge != null);
    assert.strictEqual(paint.serverFields.atlasHealth, 'OK');
    // Staleness visible
    assert.ok(paint.serverFields.cacheAgeMs >= 0);
    // No actionable RED on dual-write surfaces
    assert.ok(crossSurfaceNoRedOnAbstain(paint));
  } finally {
    try { fs.unlinkSync(file); } catch (_) {}
  }
});

// ── test_sweep_json_control_char_safe ──
test('test_sweep_json_control_char_safe', () => {
  const dirtyCmd = 'claude.exe -p \u0000evil\u0007\u001b[31m';
  const dirtyPath = 'C:\\x\\bin\u0001\\claude.exe';
  assert.ok(hasUnsafeControlChars(dirtyCmd));
  assert.ok(hasUnsafeControlChars(dirtyPath));

  const cleanCmd = sanitizeControlChars(dirtyCmd);
  const cleanPath = sanitizeControlChars(dirtyPath);
  assert.ok(!hasUnsafeControlChars(cleanCmd));
  assert.ok(!hasUnsafeControlChars(cleanPath));
  assert.ok(cleanCmd.includes('\uFFFD'));

  const payload = sanitizeProcessFields({
    ok: true,
    engines: [{
      pid: '1',
      name: 'claude.exe',
      path: dirtyPath,
      cmd: dirtyCmd,
      wouldBeActionableRed: true,
    }],
    hiddenSample: ['x\u0000y'],
  });
  const raw = jsonSafeStringify(payload);
  // Must parse without throw
  const round = JSON.parse(raw);
  assert.strictEqual(round.ok, true);
  assert.ok(!hasUnsafeControlChars(round.engines[0].cmd));
  assert.ok(!hasUnsafeControlChars(round.engines[0].path));

  // Parse fail ⇒ sweepError + empty engines (never invent RED)
  const bad = parseSweepJson('NOT JSON {{{');
  assert.strictEqual(bad.ok, false);
  assert.ok(bad.sweepError);
  assert.deepStrictEqual(bad.engines, []);
  assert.strictEqual(bad.parseFailed, true);

  // Empty / control-char-only garbage
  const empty = parseSweepJson('');
  assert.strictEqual(empty.ok, false);
  assert.deepStrictEqual(empty.engines, []);

  // Worker error shape
  const fail = parseSweepJson(jsonSafeStringify({
    ok: false,
    error: 'worker crashed',
    engines: [{ name: 'fake-zombie', wouldBeActionableRed: true }],
  }));
  assert.strictEqual(fail.ok, false);
  assert.ok(fail.sweepError);
  assert.deepStrictEqual(fail.engines, [], 'never invent zombies on worker error');
  assert.strictEqual(fail.abstain, true);

  // Happy path with dirty fields survives round-trip
  const good = parseSweepJson(raw);
  assert.strictEqual(good.ok, true);
  assert.strictEqual(good.sweepError, null);
  assert.strictEqual(good.engines.length, 1);
});

// ── test_why_min_payload_from_cache ──
test('test_why_min_payload_from_cache', () => {
  const candidate = {
    pid: '9001',
    name: 'claude.exe',
    wouldBeActionableRed: true,
    quadVerdict: 'WOULD_BE_RED',
    reasonCodes: ['WOULD_BE_ACTIONABLE_RED', 'QUAD_JOINT_POSITIVE'],
    supervisionStatus: 'UNSUPERVISED',
    spendStatus: 'SPEND_POSITIVE',
    ownership: { owned: false, keep: false, failClosed: false },
    ownershipBadge: { owned: false, keep: false, label: 'not owned' },
  };
  const why = buildWhyMinPayload(candidate, {
    classifierMode: 'shadow',
    freezeCapability: false,
    lastSweepAt: Date.now() - 2000,
    now: Date.now(),
  });
  assert.strictEqual(why.fromCache, true);
  assert.strictEqual(why.blocksFirstPaint, false);
  assert.strictEqual(why.requiresFullSweep, false);
  assert.ok(Array.isArray(why.reasonCodes) && why.reasonCodes.length > 0);
  assert.strictEqual(why.lastVerdict, 'WOULD_BE_RED');
  assert.ok(why.cacheAgeMs >= 0);
  assert.strictEqual(why.freezeCapability, false);
  assert.strictEqual(why.classifierMode, 'shadow');
  assert.ok(RECOMMENDED_NEXT.includes(why.recommendedNext));
  // Shadow ⇒ never FREEZE_THEN_KILL scare
  assert.notStrictEqual(why.recommendedNext, 'FREEZE_THEN_KILL');
  assert.strictEqual(why.recommendedNext, 'OBSERVE_ONLY');
  assert.ok(why.legSummary.supervision);
  assert.ok(why.uiCopy.uncertainNotRed);
  assert.ok(why.uiCopy.freezeBeforeKill);

  // Owned ⇒ OWNED_NO_KILL
  const ownedWhy = buildWhyMinPayload({
    ...candidate,
    ownership: { owned: true, keep: true },
  }, { classifierMode: 'shadow', freezeCapability: true });
  assert.strictEqual(ownedWhy.recommendedNext, 'OWNED_NO_KILL');

  // Armed + freezeCapability + would-be ⇒ FREEZE_THEN_KILL
  const armedWhy = buildWhyMinPayload(candidate, {
    classifierMode: 'armed',
    freezeCapability: true,
  });
  // recommendNext uses isActionableRedAllowed which needs real armed mode resolution;
  // pass through recommendNext directly with mode string 'armed'
  assert.strictEqual(
    recommendNext(candidate, { classifierMode: 'armed', freezeCapability: true }),
    'FREEZE_THEN_KILL',
  );
  // freezeCapability false under armed scare ⇒ INVESTIGATE not FREEZE_THEN_KILL sole path
  assert.strictEqual(
    recommendNext(candidate, { classifierMode: 'armed', freezeCapability: false }),
    'INVESTIGATE',
  );

  // Server fields shape
  const fields = buildRadarServerFields({
    sweepError: null,
    lastSweepAt: Date.now() - 1000,
    freezeCapability: true,
    atlasHealth: 'OK',
    reasonCodes: ['SHADOW_OBSERVE_ONLY'],
    classifierMode: 'shadow',
    canaryReceipt: { present: false, valid: false },
  });
  assert.ok('sweepError' in fields);
  assert.ok('cacheAge' in fields);
  assert.ok('freezeCapability' in fields);
  assert.ok('atlasHealth' in fields);
  assert.ok('reasonCodes' in fields);
  assert.ok('classifierMode' in fields);
  assert.ok('canaryReceipt' in fields || 'canaryReceiptStatus' in fields);
  assert.strictEqual(fields.canaryReceiptStatus, 'none');

  // New reason codes closed
  for (const c of ['SWEEP_ERROR', 'CACHE_ONLY_IDENTITY_REFUSED', 'CACHED_NON_ACTIONABLE']) {
    assert.ok(isKnownReasonCode(c), c);
  }
});

// ── test_cross_surface_no_red_on_abstain ──
test('test_cross_surface_no_red_on_abstain', () => {
  const legacy = wouldBeZombieGroup();

  // Quad ABSTAIN-shaped observe (no would-be)
  const abstainDual = evaluateDualWriteSurfaces({
    classifierMode: 'shadow',
    observe: {
      wouldBeActionableRed: false,
      wouldBeCount: 0,
      reasonCodes: ['QUAD_ABSTAIN_UNCERTAIN_LEG', 'VERDICT_ABSTAIN'],
      items: [],
    },
  });
  assert.strictEqual(abstainDual.anySurfaceActionableRed, false);
  assert.ok(crossSurfaceNoRedOnAbstain(abstainDual));
  assert.ok(assertNoActionableRedUnderShadow(abstainDual));

  // sweepError path via suppress
  const errPaint = suppressActionableCachedRed(
    { zombie: legacy, active: [], idleCount: 0 },
    { classifierMode: 'shadow', sweepError: 'boom', fromCache: true },
  );
  assert.ok(crossSurfaceNoRedOnAbstain(errPaint));
  for (const name of Object.keys(errPaint.dualWrite.surfaces)) {
    assert.strictEqual(errPaint.dualWrite.surfaces[name].actionableRed, false, name);
  }

  // Uncertain candidate recommendNext
  assert.strictEqual(
    recommendNext({ supervisionStatus: 'UNCERTAIN', wouldBeActionableRed: false }, { classifierMode: 'shadow' }),
    'ABSTAIN_WAIT',
  );

  // Durable load after write survives restart shape
  const file = tmpPath('restart.json');
  try {
    writeDurableLastKnown(file, {
      buckets: applyDualWriteToBuckets({ zombie: legacy, active: [], idleCount: 0 }, 'shadow'),
      lastSweepAt: new Date().toISOString(),
      classifierMode: 'shadow',
    });
    const loaded = loadDurableLastKnown(file);
    assert.strictEqual(loaded.ok, true);
    assert.strictEqual(loaded.snapshot.schema, LAST_KNOWN_SCHEMA);
    assert.strictEqual(loaded.snapshot.actionableRed, false);
    const paint = paintRadarFromCache({ lastKnownPath: file, classifierMode: 'shadow' });
    assert.strictEqual(paint.shell.actionableRed, false);
    assert.ok(crossSurfaceNoRedOnAbstain(paint));
  } finally {
    try { fs.unlinkSync(file); } catch (_) {}
  }

  assert.ok(computeCacheAgeMs(Date.now() - 500) >= 0);
  assert.strictEqual(computeCacheAgeMs(null), null);
  assert.ok(isActionableRedAllowed('shadow') === false);
});
