// W3 / P1 — Four-leg quad skeleton + fail-SAFE matrix under shadow.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  evaluateQuad,
  failSafeMatrixEntry,
  LEG_POSITIVE,
  LEG_NEGATIVE,
  LEG_UNCERTAIN,
  VERDICT_WOULD_BE_RED,
  VERDICT_KEEP,
  VERDICT_ABSTAIN,
} = require('../src/quad.js');

const {
  lookupOwnership,
  OWNERSHIP_IPC_FAIL_CLOSED,
  OWNERSHIP_NOT_REGISTERED,
} = require('../src/ownership.js');

const {
  evaluateDualWriteSurfaces,
  assertNoActionableRedUnderShadow,
  SURFACES,
} = require('../src/dual-write.js');

const { resolveClassifierMode, isActionableRedAllowed } = require('../src/mode.js');
const { isKnownReasonCode } = require('../src/reason-catalog.js');

/** All four legs positive orphan shape. */
function jointPositiveLegs(overrides = {}) {
  return {
    engine: { isEnginePositive: true, isE1: true, reason: 'E1_CLOSED_ALLOWLIST' },
    spend: { spendingNow: true },
    supervision: {
      status: 'UNSUPERVISED',
      unsupervised: true,
      supervised: false,
      reason: 'WALK_COMPLETE_SYSTEM_ROOT',
    },
    ownership: lookupOwnership({ pid: 9001 }, { registry: [] }),
    ...overrides,
  };
}

test('quad joint positive = engine ∧ spend ∧ unsupervised ∧ not owned', () => {
  const q = evaluateQuad(jointPositiveLegs());
  assert.strictEqual(q.verdict, VERDICT_WOULD_BE_RED);
  assert.strictEqual(q.jointPositive, true);
  assert.strictEqual(q.wouldBeActionableRed, true);
  assert.strictEqual(q.abstain, false);
  assert.strictEqual(q.keep, false);
  assert.ok(q.reasonCodes.includes('QUAD_JOINT_POSITIVE'));
  assert.ok(q.reasonCodes.includes('VERDICT_WOULD_BE_RED'));
  assert.strictEqual(q.legs.engine.status, LEG_POSITIVE);
  assert.strictEqual(q.legs.spend.status, LEG_POSITIVE);
  assert.strictEqual(q.legs.supervision.status, LEG_POSITIVE);
  assert.strictEqual(q.legs.ownership.status, LEG_POSITIVE);
  assert.ok(q.reasonCodes.includes(OWNERSHIP_NOT_REGISTERED));
});

test('Given any leg UNCERTAIN — quad abstains, no actionable RED under shadow', () => {
  const cases = [
    {
      name: 'supervision',
      legs: jointPositiveLegs({
        supervision: { status: 'UNCERTAIN', reason: 'MISSING_PARENT' },
      }),
    },
    {
      name: 'spend',
      legs: jointPositiveLegs({
        spend: { spendUncertain: true },
      }),
    },
    {
      name: 'engine',
      legs: jointPositiveLegs({
        engine: { isEnginePositive: false, reason: 'INVALID_PROC' },
      }),
    },
  ];

  const mode = resolveClassifierMode({ requestedMode: 'shadow', receipt: null });
  assert.strictEqual(isActionableRedAllowed(mode.mode), false);

  for (const c of cases) {
    const q = evaluateQuad(c.legs);
    // INVALID_PROC maps to ENGINE_UNCERTAIN → ABSTAIN
    assert.strictEqual(q.verdict, VERDICT_ABSTAIN, c.name);
    assert.strictEqual(q.wouldBeActionableRed, false, c.name);
    assert.strictEqual(q.abstain, true, c.name);
    assert.ok(q.uncertainLegs.length >= 1, c.name);
    assert.ok(q.reasonCodes.includes('QUAD_ABSTAIN_UNCERTAIN_LEG'), c.name);
    assert.ok(q.reasonCodes.includes('VERDICT_ABSTAIN'), c.name);
    for (const code of q.reasonCodes) {
      assert.ok(isKnownReasonCode(code), `${c.name} code closed: ${code}`);
    }

    const matrix = failSafeMatrixEntry(q, mode.mode, false);
    assert.strictEqual(matrix.actionableRed, false, c.name);
    assert.strictEqual(matrix.observeOnly, true, c.name);

    // Dual-write: even if we pretend observe would-be from a bad client, shadow darks RED.
    const dual = evaluateDualWriteSurfaces({
      classifierMode: mode.mode,
      legacyWouldBeZombies: q.wouldBeActionableRed
        ? [{ id: 'x', name: 'claude.exe', count: 1, providers: [], root: 'services.exe', supervised: false }]
        : [],
      extraReasonCodes: q.reasonCodes,
    });
    assert.strictEqual(dual.anySurfaceActionableRed, false, c.name);
    assert.ok(assertNoActionableRedUnderShadow(dual), c.name);
    for (const s of SURFACES) {
      assert.strictEqual(dual.surfaces[s].actionableRed, false, `${c.name}/${s}`);
    }
  }
});

test('supervised or owned never joint-positive', () => {
  const sup = evaluateQuad(jointPositiveLegs({
    supervision: { status: 'SUPERVISED', supervised: true, reason: 'HOST_ALLOWLIST_ANCESTOR' },
  }));
  assert.strictEqual(sup.verdict, VERDICT_KEEP);
  assert.strictEqual(sup.wouldBeActionableRed, false);
  assert.strictEqual(sup.keep, true);

  const owned = evaluateQuad(jointPositiveLegs({
    ownership: lookupOwnership({ pid: 1 }, { registry: [1] }),
  }));
  assert.strictEqual(owned.verdict, VERDICT_KEEP);
  assert.strictEqual(owned.wouldBeActionableRed, false);

  const failClosed = evaluateQuad(jointPositiveLegs({
    ownership: lookupOwnership({ pid: 2 }, { forceTimeout: true }),
  }));
  assert.strictEqual(failClosed.verdict, VERDICT_KEEP);
  assert.ok(failClosed.reasonCodes.includes(OWNERSHIP_IPC_FAIL_CLOSED));
});

test('spend-negative or engine-negative is KEEP not RED', () => {
  const noSpend = evaluateQuad(jointPositiveLegs({
    spend: { spendingNow: false },
  }));
  assert.strictEqual(noSpend.verdict, VERDICT_KEEP);
  assert.strictEqual(noSpend.wouldBeActionableRed, false);

  const noEng = evaluateQuad(jointPositiveLegs({
    engine: { isEnginePositive: false, reason: 'NOT_ENGINE' },
  }));
  assert.strictEqual(noEng.verdict, VERDICT_KEEP);
  assert.strictEqual(noEng.wouldBeActionableRed, false);
});

test('fail-SAFE matrix: joint positive still non-actionable under shadow', () => {
  const q = evaluateQuad(jointPositiveLegs());
  assert.strictEqual(q.wouldBeActionableRed, true);
  const shadow = failSafeMatrixEntry(q, 'shadow', false);
  assert.strictEqual(shadow.actionableRed, false);
  assert.strictEqual(shadow.jointPositive, true);
  assert.strictEqual(shadow.wouldBeActionableRed, true);

  // Armed path only allows actionable when scare flag true (receipt path — W1+).
  const armed = failSafeMatrixEntry(q, 'armed', true);
  assert.strictEqual(armed.actionableRed, true);
});
