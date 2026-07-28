// W3 / P1 — Ownership KEEP, badge scaffolding, IPC fail-closed stub.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  lookupOwnership,
  productionOwnershipLeg,
  ownershipStubContract,
  buildOwnershipBadge,
  OWNERSHIP_IPC_STUB,
  OWNERSHIP_IPC_FAIL_CLOSED,
  OWNERSHIP_REGISTERED_KEEP,
  OWNERSHIP_NOT_REGISTERED,
  OWNERSHIP_STUB_MAX_WAVE,
  OWNERSHIP_STUB_VERSION,
} = require('../src/ownership.js');

const {
  evaluateQuad,
  failSafeMatrixEntry,
} = require('../src/quad.js');

const {
  productionOwnership,
  productionQuad,
  evaluateQuad: evaluateQuadFromClassify,
  OWNERSHIP_IPC_FAIL_CLOSED: FAIL_CLOSED_EXPORT,
} = require('../src/classify.js');

const {
  evaluateDualWriteSurfaces,
  assertNoActionableRedUnderShadow,
} = require('../src/dual-write.js');

const { resolveClassifierMode, isActionableRedAllowed } = require('../src/mode.js');

test('ownership KEEP/badge scaffolding — registered pid is KEEP', () => {
  const reg = [{ pid: 4242, createTime: 1000 }];
  const r = lookupOwnership(
    { pid: 4242, createTime: 1000, imagePath: 'C:\\bin\\claude.exe' },
    { registry: reg },
  );
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.owned, true);
  assert.strictEqual(r.keep, true);
  assert.strictEqual(r.failClosed, false);
  assert.strictEqual(r.reason, OWNERSHIP_REGISTERED_KEEP);
  assert.ok(r.reasonCodes.includes(OWNERSHIP_IPC_STUB));
  assert.ok(r.reasonCodes.includes(OWNERSHIP_REGISTERED_KEEP));
  assert.ok(r.badge);
  assert.strictEqual(r.badge.owned, true);
  assert.strictEqual(r.badge.keep, true);
  assert.match(r.badge.label, /Anchor-owned/i);
  assert.strictEqual(r.stub, true);
  assert.strictEqual(r.stubMaxWave, OWNERSHIP_STUB_MAX_WAVE);
});

test('test_ownership_stub_registered_keep', () => {
  const r = productionOwnershipLeg(
    { pid: 99, createTime: 50, imagePath: 'claude.exe' },
    { registry: new Set([99]) },
  );
  assert.strictEqual(r.owned, true);
  assert.strictEqual(r.keep, true);
  assert.strictEqual(r.reason, OWNERSHIP_REGISTERED_KEEP);
});

test('test_ownership_stub_unowned_lab_pid_allows_destructive_gate', () => {
  // Non-registered lab/orphan PID + healthy registry read ⇒ owned=false (not always-KEEP theater).
  const r = lookupOwnership(
    { pid: 7777, createTime: 2000, imagePath: 'C:\\lab\\claude.exe' },
    { registry: [] },
  );
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.owned, false);
  assert.strictEqual(r.keep, false);
  assert.strictEqual(r.failClosed, false);
  assert.strictEqual(r.reason, OWNERSHIP_NOT_REGISTERED);
  assert.ok(r.reasonCodes.includes(OWNERSHIP_NOT_REGISTERED));
});

test('test_ownership_ipc_stub_fail_closed', () => {
  const timeout = lookupOwnership({ pid: 1 }, { forceTimeout: true });
  assert.strictEqual(timeout.owned, true);
  assert.strictEqual(timeout.keep, true);
  assert.strictEqual(timeout.failClosed, true);
  assert.strictEqual(timeout.reason, OWNERSHIP_IPC_FAIL_CLOSED);
  assert.ok(timeout.reasonCodes.includes(OWNERSHIP_IPC_FAIL_CLOSED));
  assert.ok(timeout.reasonCodes.includes(OWNERSHIP_IPC_STUB));
  assert.match(timeout.badge.label, /KEEP/i);

  const err = lookupOwnership({ pid: 2 }, { forceError: true });
  assert.strictEqual(err.reason, OWNERSHIP_IPC_FAIL_CLOSED);
  assert.strictEqual(err.owned, true);

  const unauth = lookupOwnership({ pid: 3 }, { authenticated: false });
  assert.strictEqual(unauth.reason, OWNERSHIP_IPC_FAIL_CLOSED);
  assert.strictEqual(unauth.owned, true);
});

test('test_ownership_stub_max_lifetime_documented', () => {
  const c = ownershipStubContract();
  assert.strictEqual(c.stub, true);
  assert.strictEqual(c.reasonCode, OWNERSHIP_IPC_STUB);
  assert.strictEqual(c.failClosedReason, OWNERSHIP_IPC_FAIL_CLOSED);
  assert.strictEqual(c.stubMaxWave, 11);
  assert.ok(c.stubVersion);
  assert.ok(c.forbidden.includes('always_owned_without_consult'));
  assert.ok(c.forbidden.includes('always_unowned_without_consult'));
  assert.strictEqual(OWNERSHIP_STUB_VERSION, c.stubVersion);
});

test('Given Anchor-registered or IPC timeout — classification KEEP / not RED', () => {
  // Registered → KEEP
  const owned = productionOwnership(
    { pid: 5001, createTime: 10, imagePath: 'claude.exe' },
    { registry: [5001] },
  );
  const qOwned = productionQuad({
    engine: { isEnginePositive: true, reason: 'E1_CLOSED_ALLOWLIST' },
    spend: { spendingNow: true },
    supervision: { status: 'UNSUPERVISED', unsupervised: true, reason: 'WALK_COMPLETE_SYSTEM_ROOT' },
    ownership: owned,
  });
  assert.strictEqual(qOwned.verdict, 'KEEP');
  assert.strictEqual(qOwned.wouldBeActionableRed, false);
  assert.strictEqual(qOwned.keep, true);
  assert.ok(qOwned.reasonCodes.includes(OWNERSHIP_REGISTERED_KEEP));

  // IPC timeout → KEEP + OWNERSHIP_IPC_FAIL_CLOSED
  const fail = productionOwnership(
    { pid: 5002, createTime: 10, imagePath: 'claude.exe' },
    { forceTimeout: true },
  );
  assert.strictEqual(fail.reason, FAIL_CLOSED_EXPORT);
  const qFail = evaluateQuadFromClassify({
    engine: true,
    spend: true,
    supervision: { status: 'UNSUPERVISED', unsupervised: true },
    ownership: fail,
  });
  assert.strictEqual(qFail.verdict, 'KEEP');
  assert.strictEqual(qFail.wouldBeActionableRed, false);
  assert.ok(qFail.reasonCodes.includes(OWNERSHIP_IPC_FAIL_CLOSED));

  // Dual-write surfaces stay non-actionable under shadow even if legacy list is lit.
  const mode = resolveClassifierMode({ requestedMode: 'shadow', receipt: null });
  const dual = evaluateDualWriteSurfaces({
    classifierMode: mode.mode,
    legacyWouldBeZombies: [],
    extraReasonCodes: fail.reasonCodes,
  });
  assert.strictEqual(dual.anySurfaceActionableRed, false);
  assert.ok(assertNoActionableRedUnderShadow(dual));
});

test('buildOwnershipBadge reflects fail-closed label', () => {
  const badge = buildOwnershipBadge({
    owned: true,
    keep: true,
    failClosed: true,
    reason: OWNERSHIP_IPC_FAIL_CLOSED,
    reasonCodes: [OWNERSHIP_IPC_STUB, OWNERSHIP_IPC_FAIL_CLOSED],
  });
  assert.strictEqual(badge.failClosed, true);
  assert.match(badge.label, /uncertain/i);
});
