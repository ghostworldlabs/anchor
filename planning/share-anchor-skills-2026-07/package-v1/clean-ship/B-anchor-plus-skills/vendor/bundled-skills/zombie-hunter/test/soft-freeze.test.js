// W6: SoftFreeze path deleted. Coverage lives in freeze.test.js (G7 pack).
// This file remains so the historical filename still points at the W6 law:
// SoftFreeze / Thread.Suspend is gone; sole boundary is freeze.js.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  FREEZE_METHOD,
  assertNoThreadSuspendSoftFreeze,
  readBoundarySources,
  soleFreezeKillServiceBoundary,
} = require('../src/freeze.js');

test('Wave 3 Soft Freeze State Machine — superseded by W6 NtSuspend sole boundary', () => {
  const { freezeSrc, softSrc, softExists } = readBoundarySources();
  assert.strictEqual(FREEZE_METHOD, 'NtSuspendProcess');
  assert.strictEqual(assertNoThreadSuspendSoftFreeze(freezeSrc).ok, true);
  const boundary = soleFreezeKillServiceBoundary();
  assert.ok(boundary.forbidden.includes('SoftFreeze'));
  assert.ok(boundary.forbidden.includes('Thread.Suspend'));

  if (softExists) {
    assert.throws(() => {
      const { SoftFreeze } = require('../src/soft-freeze.js');
      SoftFreeze();
    }, /SoftFreeze removed|sole|NtSuspendProcess/i);
    assert.ok(!/\$thread\.Suspend/i.test(softSrc || ''));
  }

  // State-machine freeze tracking is owned by server frozenPids + freeze.js results,
  // not SoftFreeze.frozenProcesses.
  assert.ok(typeof boundary.entrypoints.includes === 'function');
  assert.ok(boundary.entrypoints.includes('freezeCandidate'));
  assert.ok(boundary.entrypoints.includes('unfreezeCandidate'));
});
