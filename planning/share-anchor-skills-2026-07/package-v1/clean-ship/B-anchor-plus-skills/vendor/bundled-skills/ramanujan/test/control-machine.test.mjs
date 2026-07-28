// Wave 17 — Metacognitive CONTROL state machine + ABANDON fixture (C3).
//
// Exercises the REAL Wave-17 source (src/control-machine.mjs) against the REAL A1 ledger, proving the
// done-when:
//
//   on the pinned canned non-converging fixture the machine ABANDONs via the GAP-FUNCTION strictly
//   before step 8 (reason=gap-function, NOT budget-exhausted), leaving the claim UNVERIFIED/CONJECTURAL.
//
// The defining Given/When/Then: given the pinned non-converging fixture, when CONTROL runs, then it
// ABANDONs with reason=gap-function before step 8. We also pin the S1 thresholds, the gap-function
// itself, the consecutive-switch rule (one switch + recovery never abandons), the converged HANDOFF,
// and the honesty-law invariant that CONTROL never raises a rung.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  CONTROL_THRESHOLDS,
  CONTROL_STATE,
  CONTROL_STATES,
  ABANDON_REASON,
  CONTROL_TRANSITION,
  gapFunction,
  ControlMachine,
  runControl,
  NON_CONVERGING_FIXTURE,
  CONVERGING_FIXTURE,
  BUDGET_EXHAUSTED_FIXTURE,
  runNonConvergingFixture,
} from '../src/control-machine.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';

// =====================================================================================
// 0. The pinned S1 thresholds + the state/reason vocabulary.
// =====================================================================================

test('S1 thresholds are pinned: budget=8, switch-window=3, abandon-switches=2', () => {
  assert.equal(CONTROL_THRESHOLDS.BUDGET, 8);
  assert.equal(CONTROL_THRESHOLDS.SWITCH_WINDOW, 3);
  assert.equal(CONTROL_THRESHOLDS.ABANDON_SWITCHES, 2);
  assert.ok(Object.isFrozen(CONTROL_THRESHOLDS));
});

test('CONTROL_STATE + ABANDON_REASON carry the pinned vocabulary', () => {
  assert.deepEqual(CONTROL_STATES, ['running', 'abandoned', 'handoff']);
  assert.equal(CONTROL_STATE.ABANDONED, 'abandoned');
  assert.equal(CONTROL_STATE.HANDOFF, 'handoff');
  assert.equal(ABANDON_REASON.GAP_FUNCTION, 'gap-function');
  assert.equal(ABANDON_REASON.BUDGET_EXHAUSTED, 'budget-exhausted');
});

// =====================================================================================
// 1. THE DONE-WHEN — the pinned non-converging fixture ABANDONs via the gap-function before step 8.
// =====================================================================================

test('done-when / GWT: on the pinned non-converging fixture CONTROL ABANDONs reason=gap-function STRICTLY before step 8, claim left UNVERIFIED', () => {
  const out = runNonConvergingFixture();

  assert.equal(out.state, CONTROL_STATE.ABANDONED, 'must ABANDON');
  assert.equal(out.reason, ABANDON_REASON.GAP_FUNCTION, 'must abandon via the gap-function, NOT budget-exhausted');
  assert.notEqual(out.reason, ABANDON_REASON.BUDGET_EXHAUSTED);
  assert.ok(out.exitStep < CONTROL_THRESHOLDS.BUDGET, `must exit before the budget (got step ${out.exitStep})`);
  assert.equal(out.exitStep, 6, 'the gap-function fires at step 6 (2 consecutive switches at steps 3 and 6)');

  // The two done-when invariants the result self-reports.
  assert.equal(out.abandonedByGapFunction, true);
  assert.equal(out.beforeBudget, true);

  // The claim is left UNVERIFIED / CONJECTURAL — CONTROL settles nothing.
  assert.equal(out.claim_rung, RUNG.UNVERIFIED);
  assert.equal(out.claim_belief, BELIEF.CONJECTURAL);
  assert.equal(out.claimLeftUnverified, true);
});

test('the non-converging fixture is the full budget of no-progress steps (so the budget COULD be the exit, but the gap fires first)', () => {
  assert.equal(NON_CONVERGING_FIXTURE.length, CONTROL_THRESHOLDS.BUDGET);
  assert.ok(NON_CONVERGING_FIXTURE.every((p) => p === false));
});

test('the abandon trace shows two SWITCHes (steps 3 and 6) and a terminal ABANDON at step 6', () => {
  const out = runNonConvergingFixture();
  const switchSteps = out.trace.filter((t) => t.transition === CONTROL_TRANSITION.SWITCH || t.transition === CONTROL_TRANSITION.ABANDON).map((t) => t.step);
  // step 3 = first switch; step 6 = second switch which IS the abandon.
  assert.deepEqual(switchSteps, [3, 6]);
  assert.equal(out.switches, 2);

  const last = out.trace[out.trace.length - 1];
  assert.equal(last.step, 6);
  assert.equal(last.transition, CONTROL_TRANSITION.ABANDON);
  assert.equal(last.consecutiveSwitches, 2);
});

// =====================================================================================
// 2. The gap-function (pure) — only a FULL window of all-no-progress is "stuck".
// =====================================================================================

test('gapFunction: a full window of 3 no-progress steps is stuck; a shorter or progress-bearing window is not', () => {
  assert.equal(gapFunction([false, false, false]), true);
  assert.equal(gapFunction([false, false]), false, 'a window shorter than m=3 is never stuck');
  assert.equal(gapFunction([false, true, false]), false, 'a progress step in the window clears the gap');
  assert.equal(gapFunction([true, true, true]), false);
  assert.equal(gapFunction([]), false);
});

// =====================================================================================
// 3. The consecutive-switch rule — one switch + recovery never abandons (budget-exhausted is distinct).
// =====================================================================================

test('a single switch followed by real progress resets the streak: the run reaches the budget and ABANDONs budget-exhausted (NOT gap-function)', () => {
  const out = runControl('c3::sporadic', BUDGET_EXHAUSTED_FIXTURE, { ledger: seedLedger('c3::sporadic') });
  assert.equal(out.state, CONTROL_STATE.ABANDONED);
  assert.equal(out.reason, ABANDON_REASON.BUDGET_EXHAUSTED, 'one switch + recovery never abandons by gap-function');
  assert.notEqual(out.reason, ABANDON_REASON.GAP_FUNCTION);
  assert.equal(out.exitStep, CONTROL_THRESHOLDS.BUDGET, 'it ran the full budget');
  assert.equal(out.beforeBudget, false);
  assert.equal(out.abandonedByGapFunction, false);
  // Even at budget exhaustion the claim is left UNVERIFIED.
  assert.equal(out.claimLeftUnverified, true);
});

test('the budget-exhausted fixture makes a single switch (at step 3) then recovers — switches===1', () => {
  const out = runControl('c3::sporadic2', BUDGET_EXHAUSTED_FIXTURE, { ledger: seedLedger('c3::sporadic2') });
  assert.equal(out.switches, 1, 'exactly one switch — the progress at step 4 resets the consecutive streak');
});

// =====================================================================================
// 4. The converged HANDOFF — CONTROL hands a candidate to VERIFY and still settles nothing.
// =====================================================================================

test('a converging attempt exits HANDOFF (handed to the VERIFY router) and the claim is STILL left UNVERIFIED', () => {
  const out = runControl('c3::converge', CONVERGING_FIXTURE, { ledger: seedLedger('c3::converge') });
  assert.equal(out.state, CONTROL_STATE.HANDOFF);
  assert.equal(out.reason, null, 'a handoff is not an abandon — no abandon reason');
  assert.equal(out.exitStep, 3);
  assert.equal(out.trace[out.trace.length - 1].transition, CONTROL_TRANSITION.CONVERGE);
  // The honesty law: CONTROL never settles. The router is the sole settler.
  assert.equal(out.claim_rung, RUNG.UNVERIFIED);
  assert.equal(out.claim_belief, BELIEF.CONJECTURAL);
  assert.equal(out.claimLeftUnverified, true);
});

// =====================================================================================
// 5. The honesty law — CONTROL never raises a rung, on ANY exit path.
// =====================================================================================

test('CONTROL never raises a rung: across abandon, budget, and handoff the bound claim stays at UNVERIFIED', () => {
  for (const [id, stream] of [
    ['h::abandon', NON_CONVERGING_FIXTURE],
    ['h::budget', BUDGET_EXHAUSTED_FIXTURE],
    ['h::handoff', CONVERGING_FIXTURE],
  ]) {
    const ledger = new ClaimLedger();
    ledger.assert({ id, type: 'proof-bearing' });
    const before = ledger.rungOf(id);
    const out = runControl(id, stream, { ledger });
    assert.equal(before, RUNG.UNVERIFIED);
    assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED, `${id}: rung must be held at UNVERIFIED`);
    assert.equal(out.claimLeftUnverified, true, `${id}: result must report the claim left UNVERIFIED`);
  }
});

test('run() with a claim SPEC emits it at the floor (UNVERIFIED) in the bound ledger', () => {
  const ledger = new ClaimLedger();
  runControl({ id: 'c3::spec', type: 'computational', statement: 'driven by control' }, NON_CONVERGING_FIXTURE, { ledger });
  assert.equal(ledger.has('c3::spec'), true);
  assert.equal(ledger.rungOf('c3::spec'), RUNG.UNVERIFIED);
});

// =====================================================================================
// 6. Robustness — malformed input, an unbound id, and a thresholds override.
// =====================================================================================

test('run() rejects a non-array stream and a malformed step entry', () => {
  const m = new ControlMachine();
  assert.throws(() => m.run('x', 'not-an-array'), /must be an array/);
  assert.throws(() => m.run('x', [false, 42]), /must be a boolean/);
});

test('run() with a bound ledger rejects an id that is not present (no silent miss)', () => {
  const ledger = new ClaimLedger();
  const m = new ControlMachine({ ledger });
  assert.throws(() => m.run('missing-id', NON_CONVERGING_FIXTURE), /not in the bound ledger/);
});

test('ControlMachine rejects a non-ledger ledger argument', () => {
  assert.throws(() => new ControlMachine({ ledger: {} }), /must be an A1 ClaimLedger/);
});

test('without a bound ledger, CONTROL still runs (no settle possible) and reports UNVERIFIED by construction', () => {
  const out = runControl({ id: 'no-ledger' }, NON_CONVERGING_FIXTURE);
  assert.equal(out.state, CONTROL_STATE.ABANDONED);
  assert.equal(out.reason, ABANDON_REASON.GAP_FUNCTION);
  assert.equal(out.claim_id, 'no-ledger');
  assert.equal(out.claimLeftUnverified, true);
});

test('a thresholds override is honored (focused unit control), but the pinned defaults drive the fixture', () => {
  // With abandon-switches lowered to 1, a single full no-progress window abandons at step 3.
  const out = runControl('t::override', [false, false, false, false], { ledger: seedLedger('t::override'), thresholds: { ABANDON_SWITCHES: 1 } });
  assert.equal(out.state, CONTROL_STATE.ABANDONED);
  assert.equal(out.reason, ABANDON_REASON.GAP_FUNCTION);
  assert.equal(out.exitStep, 3);
});

// ------------------------------------------------------------------------------------
// helper — seed a ledger with a claim at the floor so run(id) can resolve it.
function seedLedger(id) {
  const ledger = new ClaimLedger();
  ledger.assert({ id, type: 'proof-bearing' });
  return ledger;
}
