// W3 / P1 — Versioned closed reason + Doctor issue catalog seed.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  REASON_CATALOG_VERSION,
  DOCTOR_ISSUE_CATALOG_VERSION,
  CLASSIFIER_REASON_CODES,
  DOCTOR_ISSUE_IDS,
  isKnownReasonCode,
  filterKnownReasonCodes,
  getDoctorIssue,
  getCatalogsPublicPayload,
  assertCodesClosed,
} = require('../src/reason-catalog.js');

const {
  getCatalogsPublicPayload: catalogsFromClassify,
  REASON_CATALOG_VERSION: verFromClassify,
  CLASSIFIER_REASON_CODES: codesFromClassify,
} = require('../src/classify.js');

const {
  evaluateDualWriteSurfaces,
  buildObserveDualRun,
  assertNoActionableRedUnderShadow,
  SURFACES,
} = require('../src/dual-write.js');

const { resolveClassifierMode } = require('../src/mode.js');

const {
  OWNERSHIP_IPC_FAIL_CLOSED,
  OWNERSHIP_IPC_STUB,
  OWNERSHIP_REGISTERED_KEEP,
  OWNERSHIP_NOT_REGISTERED,
} = require('../src/ownership.js');

test('test_reason_issue_catalog_closed_versioned', () => {
  assert.ok(REASON_CATALOG_VERSION && String(REASON_CATALOG_VERSION).length > 0);
  assert.ok(DOCTOR_ISSUE_CATALOG_VERSION && String(DOCTOR_ISSUE_CATALOG_VERSION).length > 0);
  assert.ok(Array.isArray(CLASSIFIER_REASON_CODES));
  assert.ok(CLASSIFIER_REASON_CODES.length >= 20, 'closed catalog non-trivial size');

  // No duplicates
  const set = new Set(CLASSIFIER_REASON_CODES);
  assert.strictEqual(set.size, CLASSIFIER_REASON_CODES.length, 'reason codes unique');

  // Membership
  assert.strictEqual(isKnownReasonCode(OWNERSHIP_IPC_FAIL_CLOSED), true);
  assert.strictEqual(isKnownReasonCode(OWNERSHIP_IPC_STUB), true);
  assert.strictEqual(isKnownReasonCode(OWNERSHIP_REGISTERED_KEEP), true);
  assert.strictEqual(isKnownReasonCode(OWNERSHIP_NOT_REGISTERED), true);
  assert.strictEqual(isKnownReasonCode('QUAD_ABSTAIN_UNCERTAIN_LEG'), true);
  assert.strictEqual(isKnownReasonCode('SHADOW_OBSERVE_ONLY'), true);
  assert.strictEqual(isKnownReasonCode('NOT_A_REAL_CODE_XYZ'), false);

  // filter drops unknowns
  assert.deepStrictEqual(
    filterKnownReasonCodes([OWNERSHIP_IPC_STUB, 'FAKE_CODE', 'SPEND_POSITIVE']),
    [OWNERSHIP_IPC_STUB, 'SPEND_POSITIVE'],
  );

  // Doctor issue seed
  assert.ok(DOCTOR_ISSUE_IDS.length >= 5);
  const ids = new Set(DOCTOR_ISSUE_IDS.map((x) => x.id));
  assert.strictEqual(ids.size, DOCTOR_ISSUE_IDS.length);
  for (const issue of DOCTOR_ISSUE_IDS) {
    assert.ok(issue.id && issue.component && issue.message);
    assert.ok(Array.isArray(issue.suggestedChecks));
  }
  assert.ok(getDoctorIssue('ZH_OWNERSHIP_IPC_FAIL'));
  assert.strictEqual(getDoctorIssue('NO_SUCH_ISSUE'), null);

  // Public payload shape (server /api/state seed)
  const pub = getCatalogsPublicPayload();
  assert.strictEqual(pub.reasonCatalogVersion, REASON_CATALOG_VERSION);
  assert.strictEqual(pub.doctorIssueCatalogVersion, DOCTOR_ISSUE_CATALOG_VERSION);
  assert.ok(pub.reasonCodes.includes(OWNERSHIP_IPC_FAIL_CLOSED));
  assert.ok(pub.doctorIssues.some((d) => d.id === 'ZH_QUAD_ABSTAIN'));

  // Production export parity via classify.js
  assert.strictEqual(verFromClassify, REASON_CATALOG_VERSION);
  assert.ok(codesFromClassify.includes('QUAD_JOINT_POSITIVE'));
  const fromCls = catalogsFromClassify();
  assert.strictEqual(fromCls.reasonCatalogVersion, REASON_CATALOG_VERSION);

  // Closed assert helper
  const closed = assertCodesClosed([OWNERSHIP_IPC_STUB, 'SHADOW_OBSERVE_ONLY']);
  assert.strictEqual(closed.ok, true);
  const open = assertCodesClosed(['TOTALLY_INVENTED']);
  assert.strictEqual(open.ok, false);
});

test('residual dual-write dark asserts with new reason fields', () => {
  const mode = resolveClassifierMode({ requestedMode: 'shadow', receipt: null });
  assert.strictEqual(mode.mode, 'shadow');

  const observe = buildObserveDualRun({
    legacyWouldBeZombies: [{
      id: '1',
      name: 'claude.exe',
      path: 'C:\\x\\claude.exe',
      count: 1,
      providers: ['anthropic'],
      root: 'services.exe',
      supervised: false,
      reasonCodes: [OWNERSHIP_NOT_REGISTERED, 'QUAD_JOINT_POSITIVE'],
    }],
    extraReasonCodes: [
      OWNERSHIP_IPC_STUB,
      'QUAD_JOINT_POSITIVE',
      'VERDICT_WOULD_BE_RED',
      'SHADOW_OBSERVE_ONLY',
    ],
  });

  // New reason fields present and closed-catalog legal
  for (const c of observe.reasonCodes) {
    assert.ok(isKnownReasonCode(c), `observe reason must be closed: ${c}`);
  }
  assert.ok(observe.reasonCodes.includes('SHADOW_OBSERVE_ONLY')
    || observe.reasonCodes.includes('WOULD_BE_ACTIONABLE_RED'));

  const dual = evaluateDualWriteSurfaces({
    classifierMode: mode.mode,
    observe,
  });
  assert.strictEqual(dual.anySurfaceActionableRed, false);
  assert.ok(assertNoActionableRedUnderShadow(dual));
  for (const name of SURFACES) {
    assert.strictEqual(dual.surfaces[name].actionableRed, false);
    // Surfaces carry reason codes including new ownership/quad fields when provided
    assert.ok(Array.isArray(dual.surfaces[name].reasonCodes));
  }
});
