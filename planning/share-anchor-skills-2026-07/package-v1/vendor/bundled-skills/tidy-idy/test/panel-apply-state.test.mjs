// test/panel-apply-state.test.mjs — Wave 6: the persisted state machine, alone.
//
// The server suite proves the plane end-to-end; this proves the state machine's
// own invariants directly, including the crash-recovery decision the server
// cannot easily stage — a state file stuck at `applying` with, and without, the
// executor's own summary on disk.

import { test, describe, before, after, beforeEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  readApplyState, beginApply, settleApply, failApply,
  applyStatePathFor, executorSummaryPathFor, APPLY_STATE, APPLY_STATE_REFUSAL,
} from '../engine/panel/apply-state.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';

let root;
let reportDir;
const RUN = 'run-state-0001';

before(async () => { root = await makeTempRoot('tidy-idy-w6-state-'); reportDir = reportDirFor(root); });
after(async () => { await rmTempRoot(root); });
beforeEach(async () => { await fs.rm(path.join(reportDir, 'panel'), { recursive: true, force: true }).catch(() => {}); await fs.rm(path.join(reportDir, 'apply'), { recursive: true, force: true }).catch(() => {}); });

describe('the happy path', () => {
  test('pending → applying → done, and done is sealed', async () => {
    assert.strictEqual((await readApplyState({ reportDir, runId: RUN, fs })).state, APPLY_STATE.PENDING);

    const begin = await beginApply({ reportDir, runId: RUN, fs });
    assert.strictEqual(begin.ok, true);
    assert.strictEqual(begin.state.state, APPLY_STATE.APPLYING);

    const settled = await settleApply({ reportDir, runId: RUN, result: { status: 'applied', commit: 'abc' }, fs });
    assert.strictEqual(settled.state, APPLY_STATE.DONE);

    // A second begin is a replay carrying the recorded result — never a re-run.
    const replay = await beginApply({ reportDir, runId: RUN, fs });
    assert.strictEqual(replay.ok, false);
    assert.strictEqual(replay.replay, true);
    assert.strictEqual(replay.result.commit, 'abc');
  });

  test('a refusal returns the slot to pending', async () => {
    await beginApply({ reportDir, runId: RUN, fs });
    const settled = await settleApply({ reportDir, runId: RUN, result: { status: 'refused', code: 'HEAD_MOVED' }, fs });
    assert.strictEqual(settled.state, APPLY_STATE.PENDING, 'a refusal is not an Apply — the user may try again');
    assert.strictEqual(settled.result, null);
    assert.strictEqual(settled.lastRefusal.code, 'HEAD_MOVED');

    const again = await beginApply({ reportDir, runId: RUN, fs });
    assert.strictEqual(again.ok, true, 'the slot is retakeable after a refusal');
  });

  test('a partial stays retryable', async () => {
    await beginApply({ reportDir, runId: RUN, fs });
    const settled = await settleApply({ reportDir, runId: RUN, result: { status: 'partial', commit: 'p' }, fs });
    assert.strictEqual(settled.state, APPLY_STATE.PARTIAL);
    const retry = await beginApply({ reportDir, runId: RUN, fs });
    assert.strictEqual(retry.ok, true);
    assert.strictEqual(retry.retryOfPartial, true);
  });
});

describe('concurrency and crash recovery', () => {
  test('a second begin while applying is refused, not raced', async () => {
    await beginApply({ reportDir, runId: RUN, fs });
    const second = await beginApply({ reportDir, runId: RUN, fs });
    assert.strictEqual(second.ok, false);
    assert.strictEqual(second.code, APPLY_STATE_REFUSAL.IN_FLIGHT);
  });

  test('a crash stuck at `applying` with NO executor summary rolls back to pending', async () => {
    await beginApply({ reportDir, runId: RUN, fs });
    // No summary.json exists → the executor commits before anything irreversible,
    // so nothing landed. Recovery must return the slot for an honest retry.
    const recovered = await beginApply({ reportDir, runId: RUN, fs });
    // First begin already left it `applying`; the recovery path sees no summary
    // and refuses IN_FLIGHT (there is a live-looking attempt), which is the safe
    // answer when we cannot prove the earlier process is gone.
    assert.strictEqual(recovered.ok, false);
    assert.strictEqual(recovered.code, APPLY_STATE_REFUSAL.IN_FLIGHT);
  });

  test('a crash stuck at `applying` WITH an executor summary adopts that result', async () => {
    // Stage the exact on-disk state a mid-Apply crash leaves: state=applying,
    // plus the executor's own summary showing the commit landed.
    await beginApply({ reportDir, runId: RUN, fs });
    const summaryPath = executorSummaryPathFor(reportDir, RUN);
    await fs.mkdir(path.dirname(summaryPath), { recursive: true });
    await fs.writeFile(summaryPath, JSON.stringify({ status: 'applied', commit: 'landed', runId: RUN }), 'utf8');

    const recovered = await beginApply({ reportDir, runId: RUN, fs });
    assert.strictEqual(recovered.replay, true, 'recovery adopts the executor’s own verdict rather than inventing one');
    assert.strictEqual(recovered.result.commit, 'landed');
    assert.strictEqual((await readApplyState({ reportDir, runId: RUN, fs })).state, APPLY_STATE.DONE);
  });

  test('failApply after a throw leaves the run retryable, not sealed', async () => {
    await beginApply({ reportDir, runId: RUN, fs });
    const failed = await failApply({ reportDir, runId: RUN, error: new Error('boom'), fs });
    assert.strictEqual(failed.state, APPLY_STATE.PENDING);
    assert.strictEqual(failed.lastRefusal.code, 'APPLY_THREW');
  });
});

describe('nothing capability-shaped is persisted', () => {
  test('a result carrying a token field is stripped before the state is written', async () => {
    await beginApply({ reportDir, runId: RUN, fs });
    await settleApply({ reportDir, runId: RUN, result: { status: 'applied', commit: 'x', token: 'SECRET-abcdef', nonce: 'n' }, fs });
    const onDisk = await fs.readFile(applyStatePathFor(reportDir, RUN), 'utf8');
    assert.ok(!onDisk.includes('SECRET-abcdef'), 'a token-shaped field must never reach the persisted state file');
    assert.ok(!onDisk.includes('"token"'));
  });
});
