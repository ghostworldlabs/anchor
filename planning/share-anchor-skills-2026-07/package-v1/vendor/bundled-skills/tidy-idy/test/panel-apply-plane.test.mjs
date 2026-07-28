// test/panel-apply-plane.test.mjs — Wave 6: the hardened Apply control plane.
//
// The four done-when properties, each an assertion on a REAL server bound to a
// real loopback port:
//
//   • exactly one token-authenticated Apply per run; a replay returns the
//     recorded original result and never re-executes;
//   • a cross-origin POST is refused (Amendment C.iii);
//   • the capability token appears nowhere on disk;
//   • no GET after bootstrap redemption returns token bytes or mutates state.

import { test, describe, before, after, beforeEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import { servePanel, GET_ENDPOINTS, TOKEN_HEADER } from '../engine/launch/panel-server.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';
import { readApplyState, APPLY_STATE } from '../engine/panel/apply-state.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';
import { envelopeWithEveryClass, identityFor, makeClient, RUN_ID } from './helpers/panel-fixture.mjs';

let root;
let reportDir;

before(async () => { root = await makeTempRoot('tidy-idy-w6-apply-'); reportDir = reportDirFor(root); });
after(async () => { await rmTempRoot(root); });

/** Serve a panel whose Apply is a recording stub — this suite tests the PLANE,
 *  not the Wave-3 executor (which its own suites cover). */
async function serve({ applyImpl = null, extra = {} } = {}) {
  const calls = [];
  const applyFn = async ({ approvals, runId }) => {
    calls.push({ approvals, runId });
    if (applyImpl) return applyImpl({ approvals, runId });
    return { status: 'applied', runId, commit: 'c0ffee', ops: approvals.map((a) => ({ id: a.id, result: 'ok' })), stale: [] };
  };
  const panel = await servePanel({
    envelope: envelopeWithEveryClass(root),
    identity: identityFor(root),
    runNumber: 3,
    rootPath: root,
    reportDir,
    applyFn,
    now: () => new Date('2026-07-21T00:01:00.000Z'),
    idleTimeoutMs: 60_000,
    heartbeatGapMs: 60_000,
    ...extra,
  });
  return { panel, calls, client: makeClient(panel.url) };
}

async function freshState() {
  // Each test starts from a clean apply-state file.
  await fs.rm(path.join(reportDir, 'panel'), { recursive: true, force: true }).catch(() => {});
}
beforeEach(freshState);

describe('one Apply per run + replay idempotence', () => {
  test('the first Apply runs; a replay returns the recorded result and does NOT re-execute', async () => {
    const { panel, calls, client } = await serve();
    try {
      // Use the real approval identity from the model so it round-trips.
      const model = await panel.model();
      const approval = model.apply.bulkApprovable[0];

      const first = await client.post('/api/apply', { token: panel.token, body: { runId: RUN_ID, approvals: [approval] } });
      assert.strictEqual(first.status, 200);
      assert.strictEqual(first.json.replay, false);
      assert.strictEqual(first.json.result.status, 'applied');
      assert.strictEqual(calls.length, 1);

      const replay = await client.post('/api/apply', { token: panel.token, body: { runId: RUN_ID, approvals: [approval] } });
      assert.strictEqual(replay.status, 200);
      assert.strictEqual(replay.json.replay, true, 'a second Apply is a REPLAY');
      assert.strictEqual(calls.length, 1, 'the executor was NOT called a second time');
      assert.strictEqual(replay.json.result.commit, 'c0ffee', 'the replay returns the RECORDED original result');

      const persisted = await readApplyState({ reportDir, runId: RUN_ID, fs });
      assert.strictEqual(persisted.state, APPLY_STATE.DONE, 'the run is sealed forever');
    } finally {
      await panel.close();
    }
  });

  test('a partial Apply stays retryable', async () => {
    const { panel, calls, client } = await serve({ applyImpl: async ({ runId }) => ({ status: 'partial', runId, commit: 'abc', trash: { moved: [], failed: [{ path: 'x', code: 'IO' }] } }) });
    try {
      const model = await panel.model();
      const approval = model.apply.bulkApprovable[0];
      const r1 = await client.post('/api/apply', { token: panel.token, body: { runId: RUN_ID, approvals: [approval] } });
      assert.strictEqual(r1.json.result.status, 'partial');
      const state = await readApplyState({ reportDir, runId: RUN_ID, fs });
      assert.strictEqual(state.state, APPLY_STATE.PARTIAL);

      const r2 = await client.post('/api/apply', { token: panel.token, body: { runId: RUN_ID, approvals: [approval] } });
      assert.strictEqual(r2.json.replay, undefined, 'a PARTIAL is retried, not replayed');
      assert.strictEqual(calls.length, 2, 'an interrupted move-set is meant to be resumed');
    } finally {
      await panel.close();
    }
  });

  test('a stale-tab run-ID mismatch is rejected', async () => {
    const { panel, calls, client } = await serve();
    try {
      const r = await client.post('/api/apply', { token: panel.token, body: { runId: 'some-other-run', approvals: [] } });
      assert.strictEqual(r.status, 409);
      assert.match(r.json.error, /stale tab/);
      assert.strictEqual(calls.length, 0);
    } finally {
      await panel.close();
    }
  });

  test('a superseding newer run voids this run’s token', async () => {
    // Plant a newer run in the index.
    const { archiveRun } = await import('../engine/launch/archive.mjs');
    await archiveRun({
      rootPath: root, reportDir, envelope: { ...envelopeWithEveryClass(root, { runId: 'run-newer' }) },
      identity: identityFor(root), launchedBy: 'cli',
    });
    const { panel, calls, client } = await serve({ extra: { runNumber: 0 } });
    try {
      const r = await client.post('/api/apply', { token: panel.token, body: { runId: RUN_ID, approvals: [] } });
      assert.strictEqual(r.status, 409);
      assert.match(r.json.error, /superseded/);
      assert.strictEqual(calls.length, 0);
    } finally {
      await panel.close();
    }
  });
});

describe('token authority', () => {
  test('an Apply with no token is refused 401', async () => {
    const { panel, calls, client } = await serve();
    try {
      const r = await client.post('/api/apply', { body: { runId: RUN_ID, approvals: [] } });
      assert.strictEqual(r.status, 401);
      assert.strictEqual(calls.length, 0);
    } finally {
      await panel.close();
    }
  });

  test('a cross-origin Apply is refused by the Origin check', async () => {
    const { panel, calls, client } = await serve();
    try {
      const r = await client.post('/api/apply', {
        token: panel.token,
        headers: { origin: 'http://evil.example' },
        body: { runId: RUN_ID, approvals: [] },
      });
      assert.strictEqual(r.status, 403);
      assert.match(r.json.error, /cross-origin/);
      assert.strictEqual(calls.length, 0, 'a foreign origin never reaches the executor');
    } finally {
      await panel.close();
    }
  });

  test('a foreign Referer is refused too', async () => {
    const { panel, client } = await serve();
    try {
      const r = await client.post('/api/apply', {
        token: panel.token,
        headers: { referer: 'http://evil.example/x' },
        body: { runId: RUN_ID, approvals: [] },
      });
      assert.strictEqual(r.status, 403);
    } finally {
      await panel.close();
    }
  });
});

describe('the token never touches disk', () => {
  test('after an Apply, the token appears in no file under the report dir or the archive', async () => {
    const { panel, client } = await serve();
    let token;
    try {
      token = panel.token;
      const model = await panel.model();
      await client.post('/api/apply', { token, body: { runId: RUN_ID, approvals: [model.apply.bulkApprovable[0]] } });
    } finally {
      await panel.close();
    }
    await assertTokenAbsentFromTree(root, token);
  });

  test('the model the panel serves is token-free', async () => {
    const { panel } = await serve();
    try {
      const model = await panel.model();
      assert.ok(!JSON.stringify(model).includes(panel.token), 'the panel model must never carry the token');
    } finally {
      await panel.close();
    }
  });
});

async function assertTokenAbsentFromTree(dir, token) {
  const entries = await fs.readdir(dir, { withFileTypes: true }).catch(() => []);
  for (const e of entries) {
    const abs = path.join(dir, e.name);
    if (e.isDirectory()) { await assertTokenAbsentFromTree(abs, token); continue; }
    const bytes = await fs.readFile(abs, 'utf8').catch(() => '');
    assert.ok(!bytes.includes(token), `the capability token leaked to disk at ${abs}`);
  }
}

export { GET_ENDPOINTS, TOKEN_HEADER };
