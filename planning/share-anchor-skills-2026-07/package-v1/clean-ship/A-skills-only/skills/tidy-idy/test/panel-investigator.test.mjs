// test/panel-investigator.test.mjs — Wave 7: the investigator tile's control plane.
//
// The tile is an ACTIVE panel control now, so it lives under the same rules every
// mutating POST does: token in a header, same-origin only, run-ID checked. And
// the slot the page renders from must reflect what the launcher configured
// (default engine, choices, briefing path) — the panel adds no claims of its own.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';

import { servePanel, POST_ENDPOINTS } from '../engine/launch/panel-server.mjs';
import { investigatorSlotDescriptor } from '../engine/launch/investigator.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';
import { envelopeWithEveryClass, identityFor, makeClient, RUN_ID } from './helpers/panel-fixture.mjs';

let root;
before(async () => { root = await makeTempRoot('tidy-idy-w7-panel-'); });
after(async () => { await rmTempRoot(root); });

function makeHook() {
  const calls = [];
  const hook = async ({ engine, runId, rootPath }) => {
    calls.push({ engine, runId, rootPath });
    return { spec: { engine: engine || 'claude', cwd: rootPath }, opened: { opened: true, by: 'terminal' }, message: `investigator terminal opened (${engine || 'claude'})` };
  };
  return { hook, calls };
}

async function serve({ onInvestigate = null } = {}) {
  return servePanel({
    envelope: envelopeWithEveryClass(root),
    identity: identityFor(root),
    runNumber: 3,
    archive: { runNumber: 3, dir: `${root}/reports/tidy/run-003` },
    rootPath: root,
    reportDir: reportDirFor(root),
    investigator: investigatorSlotDescriptor({ archive: { dir: `${root}/reports/tidy/run-003` } }),
    onInvestigate,
    idleTimeoutMs: 60_000,
    heartbeatGapMs: 60_000,
  });
}

describe('POST /api/investigate', () => {
  test('is in the POST route table', () => {
    assert.ok(POST_ENDPOINTS.includes('/api/investigate'));
  });

  test('opens the terminal for the current run when the launcher supplied a hook', async () => {
    const { hook, calls } = makeHook();
    const panel = await serve({ onInvestigate: hook });
    const client = makeClient(panel.url);
    try {
      const r = await client.post('/api/investigate', { token: panel.token, headers: { origin: panel.url }, body: { runId: RUN_ID, engine: 'gemini' } });
      assert.strictEqual(r.status, 202);
      assert.strictEqual(r.json.ok, true);
      assert.match(r.json.message, /gemini/);
      assert.strictEqual(calls.length, 1);
      assert.strictEqual(calls[0].engine, 'gemini');
      assert.strictEqual(calls[0].runId, RUN_ID);
      assert.strictEqual(path.resolve(calls[0].rootPath), path.resolve(root));
    } finally {
      await panel.close();
    }
  });

  test('refuses without the capability token', async () => {
    const { hook } = makeHook();
    const panel = await serve({ onInvestigate: hook });
    const client = makeClient(panel.url);
    try {
      const r = await client.post('/api/investigate', { headers: { origin: panel.url }, body: { runId: RUN_ID } });
      assert.strictEqual(r.status, 401);
    } finally {
      await panel.close();
    }
  });

  test('refuses a cross-origin POST', async () => {
    const { hook } = makeHook();
    const panel = await serve({ onInvestigate: hook });
    const client = makeClient(panel.url);
    try {
      const r = await client.post('/api/investigate', { token: panel.token, headers: { origin: 'http://evil.example' }, body: { runId: RUN_ID } });
      assert.strictEqual(r.status, 403);
    } finally {
      await panel.close();
    }
  });

  test('rejects a stale tab naming a different run', async () => {
    const { hook } = makeHook();
    const panel = await serve({ onInvestigate: hook });
    const client = makeClient(panel.url);
    try {
      const r = await client.post('/api/investigate', { token: panel.token, headers: { origin: panel.url }, body: { runId: 'run-someone-else' } });
      assert.strictEqual(r.status, 409);
    } finally {
      await panel.close();
    }
  });

  test('answers honestly when no investigator hook was supplied', async () => {
    const panel = await serve({ onInvestigate: null });
    const client = makeClient(panel.url);
    try {
      const r = await client.post('/api/investigate', { token: panel.token, headers: { origin: panel.url }, body: { runId: RUN_ID } });
      assert.strictEqual(r.status, 501);
      assert.strictEqual(r.json.performed, false);
      assert.match(r.json.message, /open a terminal/);
    } finally {
      await panel.close();
    }
  });
});

describe('the investigator slot the page renders from', () => {
  test('is active, engine-configured, and carries the briefing path — served token-free through the model', async () => {
    const panel = await serve({ onInvestigate: makeHook().hook });
    const client = makeClient(panel.url);
    try {
      const r = await client.get('/api/panel', { token: panel.token });
      assert.strictEqual(r.status, 200);
      const inv = r.json.slots.investigator;
      assert.strictEqual(inv.active, true);
      assert.strictEqual(inv.reserved, false);
      assert.strictEqual(inv.endpoint, '/api/investigate');
      assert.strictEqual(inv.defaultEngine, 'claude');
      assert.deepStrictEqual(inv.engines.map((e) => e.id), ['claude', 'gemini', 'grok']);
      assert.ok(inv.briefing.path.replace(/\\/g, '/').endsWith('run-003/briefing.md'));
      // The model never carries the capability token.
      assert.ok(!JSON.stringify(r.json).includes(panel.token));
    } finally {
      await panel.close();
    }
  });

  test('the rendered page wires the investigate button and engine radios', async () => {
    const panel = await serve({ onInvestigate: makeHook().hook });
    const client = makeClient(panel.url);
    try {
      const first = await client.get(new URL(panel.bootstrapUrl).pathname);
      assert.strictEqual(first.status, 200);
      assert.ok(first.text.includes('id="investigate"'), 'the investigate button is present');
      assert.ok(first.text.includes('name="investigator-engine"'), 'the engine toggle is present');
      assert.ok(first.text.includes('/api/investigate'), 'the button posts to the investigate endpoint');
    } finally {
      await panel.close();
    }
  });
});
