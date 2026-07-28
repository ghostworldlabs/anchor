// test/panel-get-audit.test.mjs — Wave 6: no GET is a credential, none mutates.
//
// The threat: a hostile local process crawls every endpoint after the panel has
// opened, hoping some GET hands it a capability that an Apply POST will accept.
// This suite replays that crawl and asserts it comes up empty — the worst any
// GET yields is report content the process could read off disk anyway.
//
// The crawl is driven by the SERVER'S OWN exported route table (GET_ENDPOINTS),
// not a hand-maintained copy, so a future endpoint added without a matching
// audit entry fails here rather than shipping unaudited.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';

import { servePanel, GET_ENDPOINTS, BOOTSTRAP_PREFIX } from '../engine/launch/panel-server.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';
import { envelopeWithEveryClass, identityFor, makeClient, RUN_ID } from './helpers/panel-fixture.mjs';

let root;

before(async () => { root = await makeTempRoot('tidy-idy-w6-audit-'); });
after(async () => { await rmTempRoot(root); });

async function serve() {
  return servePanel({
    envelope: envelopeWithEveryClass(root),
    identity: identityFor(root),
    runNumber: 1,
    rootPath: root,
    reportDir: reportDirFor(root),
    nonceFile: true,
    idleTimeoutMs: 60_000,
    heartbeatGapMs: 60_000,
  });
}

describe('the bootstrap nonce', () => {
  test('the first GET redeems it, unlinks the temp file, and embeds the token; a second GET is refused', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      const nonceFile = panel.nonceFile;
      assert.ok(nonceFile);
      // Before redemption the 0600 file holds the URL — never the token.
      const before = await fs.readFile(nonceFile, 'utf8');
      assert.ok(!before.includes(panel.token), 'the nonce file must never carry the capability token');

      const url = new URL(panel.bootstrapUrl);
      const first = await client.get(url.pathname);
      assert.strictEqual(first.status, 200);
      assert.match(first.headers['content-type'], /text\/html/);
      assert.match(first.headers['cache-control'], /no-store/);
      assert.ok(first.text.includes(panel.token), 'the redeemed page is the ONE place the token appears');

      await assert.rejects(fs.stat(nonceFile), /ENOENT/, 'the nonce temp file is unlinked on redemption');

      const second = await client.get(url.pathname);
      assert.strictEqual(second.status, 410, 'a second GET of the bootstrap URL is GONE, not merely not-found');
      assert.ok(!second.text.includes(panel.token));
    } finally {
      await panel.close();
    }
  });

  test('a wrong nonce is 404 and never leaks the token', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      const r = await client.get(`${BOOTSTRAP_PREFIX}deadbeef`);
      assert.strictEqual(r.status, 404);
      assert.ok(!r.text.includes(panel.token));
    } finally {
      await panel.close();
    }
  });
});

describe('the GET audit', () => {
  test('every GET in the route table is side-effect-free and token-free', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      // Redeem the panel first, so the crawl happens AFTER it has opened —
      // exactly the window the threat model cares about.
      await client.get(new URL(panel.bootstrapUrl).pathname);
      const stateBefore = JSON.stringify(await panel.model());

      for (const ep of GET_ENDPOINTS) {
        // Crawl WITHOUT a token (the hostile process has none) and WITH the
        // token (proving even an authenticated GET is side-effect-free).
        for (const token of [null, panel.token]) {
          const r = await client.get(ep.route, token ? { token } : {});
          assert.notStrictEqual(r.status, 500, `${ep.route} errored`);
          if (r.text) {
            assert.ok(!r.text.includes(panel.token), `${ep.route} leaked the capability token`);
          }
          if (ep.auth === 'token' && !token) {
            assert.strictEqual(r.status, 401, `${ep.route} is declared token-gated but answered without one`);
          }
        }
      }

      // Nothing the crawl did changed the server's state.
      const stateAfter = JSON.stringify(await panel.model());
      assert.strictEqual(stateAfter, stateBefore, 'a GET crawl must not mutate any state');

      // And no GET yields a credential an Apply POST accepts.
      const apply = await client.post('/api/apply', { headers: { origin: panel.url }, body: { runId: RUN_ID, approvals: [] } });
      assert.strictEqual(apply.status, 401, 'without the header token, Apply is refused — no GET supplied a usable credential');
    } finally {
      await panel.close();
    }
  });

  test('the /api/lock GET redacts the lock ownership token', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      const r = await client.get('/api/lock');
      assert.strictEqual(r.status, 200);
      if (r.json && r.json.held) {
        assert.ok(!('token' in r.json), 'the lock ownership token would let any local process release our lock');
      }
    } finally {
      await panel.close();
    }
  });

  test('the audit route table matches the server’s real GET surface', async () => {
    const panel = await serve();
    const client = makeClient(panel.url);
    try {
      // Every declared route answers something other than 404-not-found.
      for (const ep of GET_ENDPOINTS) {
        const r = await client.get(ep.route, ep.auth === 'token' ? { token: panel.token } : {});
        assert.notStrictEqual(r.status, 404, `declared endpoint ${ep.route} does not exist on the server`);
      }
    } finally {
      await panel.close();
    }
  });
});
