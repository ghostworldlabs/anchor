// W4 — tests for the gated-dispatch canary: GREEN on the genuine spine, TRIPS on each planted violation.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  canaryGatedDispatch,
  runGatedDispatchCanary,
  gatedDispatchCanaryExitCode,
  GATED_DISPATCH_CANARY_NAMES,
} from '../src/gated-dispatch-canary.mjs';

test('gated-dispatch canary is GREEN on the genuine spine (open-gate teeth + closed-gate control + Honesty Law)', () => {
  const r = canaryGatedDispatch();
  assert.equal(r.ok, true, `unexpected failures: ${r.failures.join(' | ')}`);
  // closed control + open teeth + 4 honesty cases + unforgeable + non-vacuity => a broad battery.
  assert.ok(r.assertions.length >= 8, `expected >=8 assertions, got ${r.assertions.length}`);
  // The positive teeth must be non-vacuous: an open-gate settle actually happened.
  assert.ok(r.assertions.some((a) => /non-vacuity/.test(a.name) && a.ok));
});

for (const plant of ['closed-gate-settles', 'open-gate-inert', 'honesty-flip', 'forge-opens']) {
  test(`gated-dispatch canary TRIPS on plant='${plant}' (the assertion has teeth)`, () => {
    const r = canaryGatedDispatch({ plant });
    assert.equal(r.ok, false, `plant '${plant}' did NOT trip the canary`);
    assert.ok(r.failures.length >= 1);
  });
}

test('an unknown plant leaves the canary green (no accidental trip)', () => {
  const r = canaryGatedDispatch({ plant: 'not-a-real-plant' });
  assert.equal(r.ok, true, r.failures.join(' | '));
});

test('runner + exit code: green=0, tripped=1', () => {
  const clean = runGatedDispatchCanary();
  assert.equal(clean.ok, true, clean.failures.join(' | '));
  assert.equal(gatedDispatchCanaryExitCode(clean), 0);
  const tripped = runGatedDispatchCanary({ plant: 'honesty-flip' });
  assert.equal(tripped.ok, false);
  assert.equal(gatedDispatchCanaryExitCode(tripped), 1);
  assert.deepEqual(GATED_DISPATCH_CANARY_NAMES, ['gated-dispatch']);
});
