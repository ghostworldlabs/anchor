// Wave 23 — A2(no-dispatch) canary (D4), regression-bound to the Wave-14 shim path.
//
// Exercises the REAL no-dispatch canary (src/no-dispatch-canary.mjs) against the REAL orchestrator + the
// REAL Wave-14 shim on the REAL A1/A3 spine, proving the done-when + the Given/When/Then:
//
//   the no-dispatch canary proves the orchestrator cannot settle or commission-dispatch a verdict
//   (no commission-id, no rung-flip) on ANY orchestrator OR Wave-14 shim path;
//
//   Given an attempt by the orchestrator (or the shim) to emit a commission-id or flip a rung, when the
//   no-dispatch canary runs, then the build fails.
//
// Pins the DISCRIMINATION (the canary has teeth): each plant — a dispatched-commission leak / a flipped
// rung, on EITHER the orchestrator OR the Wave-14 shim path — trips the canary; the clean run is green.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  NO_DISPATCH_CANARY_NAMES,
  ORCHESTRATOR_BATTERY,
  SHIM_BATTERY,
  canaryNoDispatch,
  runNoDispatchCanary,
  noDispatchCanaryExitCode,
} from '../src/no-dispatch-canary.mjs';
import { PILLARS, PILLAR } from '../src/orchestrator.mjs';

// =====================================================================================
// 0. The canary is GREEN on the genuine spine.
// =====================================================================================

test('the no-dispatch canary is GREEN on the genuine spine', () => {
  const result = canaryNoDispatch();
  assert.equal(result.name, 'no-dispatch');
  assert.equal(result.ok, true, `unexpected failures: ${result.failures.join(' | ')}`);
  assert.equal(result.failures.length, 0);
  // a meaningful number of pinned assertions actually ran (non-trivial).
  assert.ok(result.assertions.length >= 24, `expected a substantial battery, got ${result.assertions.length}`);
  assert.deepEqual(NO_DISPATCH_CANARY_NAMES, ['no-dispatch']);
});

test('the suite runner reports green + a zero exit code on the genuine spine', () => {
  const suite = runNoDispatchCanary();
  assert.equal(suite.ok, true);
  assert.deepEqual(suite.failures, []);
  assert.equal(suite.canaries.length, 1);
  assert.equal(noDispatchCanaryExitCode(suite), 0);
});

// =====================================================================================
// 1. THE GWT — a planted commission-id / rung-flip on EITHER surface fails the build.
// =====================================================================================

for (const plant of ['dispatch-leak', 'rung-flip', 'shim-dispatch-leak', 'shim-rung-flip']) {
  test(`GWT: plant='${plant}' TRIPS the canary (the build fails)`, () => {
    const result = canaryNoDispatch({ plant });
    assert.equal(result.ok, false, `the canary did not trip on plant='${plant}'`);
    assert.ok(result.failures.length >= 1);
    const suite = runNoDispatchCanary({ plant });
    assert.equal(suite.ok, false);
    assert.equal(noDispatchCanaryExitCode(suite), 1);
    assert.ok(suite.failures.every((f) => f.startsWith('no-dispatch: ')));
  });
}

test("the orchestrator dispatch-leak trips the NO-commission-id arm; the rung-flip trips the NO-rung-flip arm", () => {
  const disp = canaryNoDispatch({ plant: 'dispatch-leak' });
  assert.ok(disp.failures.some((f) => /NO commission-id dispatched/.test(f)));
  const flip = canaryNoDispatch({ plant: 'rung-flip' });
  assert.ok(flip.failures.some((f) => /NO rung-flip/.test(f)));
});

test('the shim regression arm trips on the SAME plants (regression-bound to the Wave-14 shim path)', () => {
  const disp = canaryNoDispatch({ plant: 'shim-dispatch-leak' });
  assert.ok(disp.failures.some((f) => /Wave-14 shim path/.test(f) && /commission-id/.test(f)));
  const flip = canaryNoDispatch({ plant: 'shim-rung-flip' });
  assert.ok(flip.failures.some((f) => /Wave-14 shim path/.test(f) && /rung-flip/.test(f)));
});

// =====================================================================================
// 2. NON-VACUITY — the battery covers all six pillars AND the Wave-14 shim path.
// =====================================================================================

test('the battery covers ALL six pillars (one read-only dispatch each)', () => {
  const covered = ORCHESTRATOR_BATTERY.map((f) => f.request.pillar);
  for (const p of PILLARS) assert.ok(covered.includes(p), `pillar ${p} not exercised`);
  assert.equal(ORCHESTRATOR_BATTERY.length, 6);
  // the canary itself asserts coverage of all pillars.
  const result = canaryNoDispatch();
  assert.ok(result.assertions.some((a) => /covered ALL .* pillars/.test(a.name) && a.ok));
});

test('the canary is regression-bound to the Wave-14 shim (the real shim path is in the battery)', () => {
  assert.ok(SHIM_BATTERY.length >= 1);
  const result = canaryNoDispatch();
  assert.ok(result.assertions.some((a) => /REGRESSION-BOUND to the Wave-14 shim/.test(a.name) && a.ok));
  // the shim arm's predicate assertions are present.
  assert.ok(result.assertions.some((a) => /Wave-14 shim path \(regression-bound\)/.test(a.name)));
});

test('the canary proves the read-only guard is ALIVE (promote() is structurally refused)', () => {
  const result = canaryNoDispatch();
  const guardAssertion = result.assertions.find((a) => /promote-guard THROWS/.test(a.name));
  assert.ok(guardAssertion && guardAssertion.ok);
});

test('the canary proves the fail-safe ASK never auto-dispatches off a confident classification', () => {
  const result = canaryNoDispatch();
  const askAssertion = result.assertions.find((a) => /fail-safe: with no explicit pillar/.test(a.name));
  assert.ok(askAssertion && askAssertion.ok);
});

// =====================================================================================
// 3. Discrimination is LOCAL — an unrelated plant key leaves the canary green.
// =====================================================================================

test('an unknown plant key does not trip the canary (the plant is specific, not a blanket failure)', () => {
  const result = canaryNoDispatch({ plant: 'not-a-real-plant' });
  assert.equal(result.ok, true);
});
