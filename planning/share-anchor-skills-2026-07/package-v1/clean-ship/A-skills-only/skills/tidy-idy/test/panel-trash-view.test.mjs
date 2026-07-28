// test/panel-trash-view.test.mjs — Wave 6: the Trash view and its one-click restore.
//
// The panel's Trash view lists what earlier runs MOVED (never deleted) and wires
// a one-click restore to the Wave-4 journaled move-back. This suite proves the
// end-to-end path: move real files into a run's Trash, open a panel, read the
// Trash view over the token-gated endpoint, POST a restore, and assert the file
// is back at its original path bit-identical.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import { servePanel } from '../engine/launch/panel-server.mjs';
import { executeTrashMoveSet, TRASH_STATUS } from '../engine/apply/trash.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';
import { cleanEnvelope, identityFor, makeClient, RUN_ID } from './helpers/panel-fixture.mjs';

let root;
let reportDir;
const TRASH_RUN = 'run-earlier-0001';

before(async () => {
  root = await makeTempRoot('tidy-idy-w6-trash-');
  reportDir = reportDirFor(root);
  // An earlier run moved two files into the Trash.
  await fs.writeFile(path.join(root, 'junk-a.txt'), 'AAAA\n');
  await fs.mkdir(path.join(root, 'nested'), { recursive: true });
  await fs.writeFile(path.join(root, 'nested', 'junk-b.log'), 'BBBB\n');
  const res = await executeTrashMoveSet({
    rootPath: root, reportDir, runId: TRASH_RUN,
    ops: [{ path: 'junk-a.txt' }, { path: 'nested/junk-b.log' }],
  });
  assert.strictEqual(res.status, TRASH_STATUS.OK);
});
after(async () => { await rmTempRoot(root); });

async function serve() {
  return servePanel({
    envelope: cleanEnvelope(root),
    identity: identityFor(root),
    runNumber: 2,
    rootPath: root,
    reportDir,
    idleTimeoutMs: 60_000,
    heartbeatGapMs: 60_000,
  });
}

describe('the Trash view', () => {
  test('lists the earlier run’s moved items, per run, over the token-gated endpoint', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      const unauth = await client.get('/api/trash');
      assert.strictEqual(unauth.status, 401, 'the Trash view carries file paths and is token-gated');

      const r = await client.get('/api/trash', { token: panel.token });
      assert.strictEqual(r.status, 200);
      const run = r.json.runs.find((x) => x.runId === TRASH_RUN);
      assert.ok(run, 'the earlier run appears in the Trash view');
      assert.strictEqual(run.held, 2);
      assert.deepStrictEqual(run.items.map((i) => i.path).sort(), ['junk-a.txt', 'nested/junk-b.log']);
      assert.ok(run.items.every((i) => i.restored === false));
    } finally {
      await panel.close();
    }
  });

  test('the panel model surfaces the Trash so the view renders from data', async () => {
    const panel = await serve();
    try {
      const model = await panel.model();
      assert.strictEqual(model.trash.totalHeld, 2);
      assert.ok(model.trash.runs.some((r) => r.runId === TRASH_RUN));
    } finally {
      await panel.close();
    }
  });
});

describe('one-click restore', () => {
  test('a restore POST moves one file back bit-identical and refuses a foreign origin', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      // A cross-origin restore is refused before it touches the Trash.
      const foreign = await client.post('/api/restore', {
        token: panel.token, headers: { origin: 'http://evil.example' },
        body: { runId: RUN_ID, trashRunId: TRASH_RUN, paths: ['junk-a.txt'] },
      });
      assert.strictEqual(foreign.status, 403);

      const r = await client.post('/api/restore', {
        token: panel.token,
        body: { runId: RUN_ID, trashRunId: TRASH_RUN, paths: ['junk-a.txt'] },
      });
      assert.strictEqual(r.status, 200);
      assert.strictEqual(r.json.result.status, TRASH_STATUS.OK);

      const restored = await fs.readFile(path.join(root, 'junk-a.txt'), 'utf8');
      assert.strictEqual(restored, 'AAAA\n', 'the file is back at its original path bit-identical');
    } finally {
      await panel.close();
    }
  });

  test('a restore with no token is refused', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      const r = await client.post('/api/restore', { body: { runId: RUN_ID, trashRunId: TRASH_RUN } });
      assert.strictEqual(r.status, 401);
    } finally {
      await panel.close();
    }
  });

  test('restoring all remaining files empties the run’s held count', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      // junk-a was restored above; restore the rest of the run.
      const r = await client.post('/api/restore', {
        token: panel.token,
        body: { runId: RUN_ID, trashRunId: TRASH_RUN, paths: null },
      });
      assert.strictEqual(r.status, 200);
      const back = await fs.readFile(path.join(root, 'nested', 'junk-b.log'), 'utf8');
      assert.strictEqual(back, 'BBBB\n');

      const view = await client.get('/api/trash', { token: panel.token });
      const run = view.json.runs.find((x) => x.runId === TRASH_RUN);
      assert.strictEqual(run.held, 0, 'everything moved by the earlier run is now restored');
    } finally {
      await panel.close();
    }
  });
});
