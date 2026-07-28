// plan-amendment.test.mjs — F3 acceptance: the PLAN-AMENDMENT-PROPOSAL halt sub-type.
//
// F3 adds a BOUNDED halt sub-type: when a build-time discovery shows the FROZEN
// plan is wrong/incomplete for the current wave (distinct from mere ambiguity), a
// review/execute agent may attach a concrete proposed resolution — a proposed diff
// to the plan doc + a rationale. Foreman STILL HALTs (no silent re-planning) and
// records the proposal in the checkpoint `pending_action` for one-click approval.
//
// ANTI-DRIFT proven here:
//   - the proposal HALTs (never GO) and carries the diff + rationale;
//   - ordinary ambiguity (`answerable:'no'`) STILL hard-halts as bare ambiguity,
//     NOT as a plan-amendment proposal;
//   - a malformed proposal (missing diff or rationale) does NOT become a special
//     halt — the wave proceeds on its normal path.
//
// Run with: node --test test/plan-amendment.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { locateDocs, parseWaves, discoverTestCommand, readCheckpoint } from '../bin/foreman-lib.mjs';
import { runWave } from '../bin/wave-engine.mjs';
import { makeScriptedDriver } from '../bin/drivers/scripted-driver.mjs';

const FIXTURE = path.resolve(import.meta.dirname, '../fixtures/canonical-project');
const CALC_REPAIR = { file: 'src/calc.js', findLast: 'return a + b;', replace: 'return a - b;' };

function freshCopy() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-f3-'));
  fs.cpSync(FIXTURE, dir, { recursive: true });
  return dir;
}
function cleanup(dir) { fs.rmSync(dir, { recursive: true, force: true }); }

function contractOf(dir) {
  const docs = locateDocs(dir);
  const planText = fs.readFileSync(docs.plan, 'utf8');
  const waves = parseWaves(planText);
  const testCmd = discoverTestCommand(planText, dir);
  return { docs, waves, testCmd, wave: waves[waves.length - 1] };
}

test('F3: a reviewer plan-amendment proposal HALTs with diff + rationale in pending_action', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    const amendment = {
      proposed_diff:
        '--- a/IMPLEMENTATION-PLAN.md\n+++ b/IMPLEMENTATION-PLAN.md\n' +
        '@@\n-subtract uses a + b\n+subtract uses a - b\n',
      rationale: 'the plan assumed subtract = a + b, but the frozen test proves the API is a - b',
    };
    // The driver could repair the wave green, but the reviewer attaches a plan
    // amendment — that HALT must fire BEFORE any GO (the plan is wrong, human in loop).
    const driver = makeScriptedDriver({ repairs: [CALC_REPAIR], planAmendment: amendment });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 4,
    });

    assert.equal(result.status, 'HALT', 'a plan-amendment proposal is a HALT (no silent re-planning), never GO');
    assert.equal(result.verdict, 'HALT');
    assert.equal(result.haltSubType, 'PLAN-AMENDMENT-PROPOSAL', 'the halt carries the F3 sub-type');
    assert.match(result.haltReason, /PLAN-AMENDMENT-PROPOSAL HALT/);

    // The structured proposal is surfaced on the result …
    assert.ok(result.amendment, 'the proposal object is attached to the result');
    assert.equal(result.amendment.proposed_diff, amendment.proposed_diff);
    assert.equal(result.amendment.rationale, amendment.rationale);
    assert.equal(result.amendment.target, docs.plan, 'target defaults to the plan doc');

    // … and the diff + rationale are recorded in the checkpoint pending_action
    // (for one-click human approval), with status halted.
    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.status, 'halted');
    assert.equal(cp.last_verdict, 'HALT');
    assert.match(cp.pending_action, /PLAN-AMENDMENT-PROPOSAL/);
    assert.match(cp.pending_action, /the plan assumed subtract = a \+ b/, 'rationale is in pending_action');
    assert.match(cp.pending_action, /subtract uses a - b/, 'proposed diff is in pending_action');
    assert.match(cp.pending_action, /HALT \(no silent re-planning\)/, 'anti-drift wording preserved');
  } finally { cleanup(dir); }
});

test('F3 anti-drift: ordinary ambiguity STILL hard-halts as bare ambiguity, NOT a plan-amendment proposal', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    // answerable:'no' with NO plan_amendment attached — the §4.7 ambiguity gate
    // must fire exactly as before; it must not be reclassified as F3.
    const driver = makeScriptedDriver({ repairs: [CALC_REPAIR], answerable: 'no' });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 4,
    });

    assert.equal(result.status, 'HALT', 'ambiguity still halts');
    assert.match(result.haltReason, /ambiguity HALT/, 'it is the bare ambiguity halt');
    assert.notEqual(result.haltSubType, 'PLAN-AMENDMENT-PROPOSAL', 'ambiguity is NOT a plan-amendment proposal');
    assert.equal(result.amendment, null, 'no amendment is attached to a bare ambiguity halt');
  } finally { cleanup(dir); }
});

test('F3 anti-drift: a malformed proposal (missing rationale) does NOT become the special halt', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    // proposed_diff but no rationale — not a well-formed proposal, so the F3 gate
    // must NOT fire. With the wave repaired green, the run converges normally; the
    // point is only that haltSubType is never PLAN-AMENDMENT-PROPOSAL here.
    const driver = makeScriptedDriver({
      repairs: [CALC_REPAIR],
      planAmendment: { proposed_diff: 'some diff', rationale: '   ' },
    });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.notEqual(result.haltSubType, 'PLAN-AMENDMENT-PROPOSAL',
      'a malformed proposal must not raise the F3 halt sub-type');
    assert.equal(result.status, 'GO', 'with the wave repaired and no valid proposal, the wave converges normally');
  } finally { cleanup(dir); }
});
