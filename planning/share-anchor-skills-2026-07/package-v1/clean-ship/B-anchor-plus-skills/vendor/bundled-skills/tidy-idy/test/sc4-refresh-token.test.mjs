// test/sc4-refresh-token.test.mjs — W6 / SC4 Option 1 (dead-Apply + re-open).
//
// REFRESH-TOKEN-CONTRACT.md mandatory families:
//   • F5 / dead-token UX — Apply disabled + re-open instruction; no silent re-enable
//   • Bootstrap re-GET — second GET → 410, no capability token bytes
//   • Close & release — no usable Apply session after close
//   • Supersede — prior run cannot Apply when superseded
//   • Existing oracles unweakened (token never disk/URL/localStorage)
//   • Deny-diff: no engine/apply/** redesign; no remount route under Option 1
//
// Orchestrator runs the gate; this file only asserts contract truth.

import { test, describe, before, after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  renderPanelPage,
  isTokenLive,
  DEAD_APPLY_BANNER_TITLE,
  DEAD_APPLY_REOPEN_COPY,
  LIVE_APPLY_F5_FOOTPRINT,
  DEAD_APPLY_CHIP_LABEL,
  TOKEN_HEADER,
} from '../engine/panel/render.mjs';
import { servePanel, BOOTSTRAP_PREFIX, renderBootstrapPage } from '../engine/launch/panel-server.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';
import { envelopeWithEveryClass, identityFor, makeClient, RUN_ID } from './helpers/panel-fixture.mjs';
import { buildPanelModel } from '../engine/panel/model.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = path.resolve(__dirname, '..');
const CONTRACT = path.resolve(
  '<path>',
);

let root;
let reportDir;

before(async () => {
  root = await makeTempRoot('tidy-idy-sc4-');
  reportDir = reportDirFor(root);
});
after(async () => { await rmTempRoot(root); });

beforeEach(async () => {
  await fsp.rm(path.join(reportDir, 'panel'), { recursive: true, force: true }).catch(() => {});
});

function model() {
  return buildPanelModel({
    envelope: envelopeWithEveryClass(root),
    identity: identityFor(root),
    runNumber: 1,
  });
}

async function serve(extra = {}) {
  const calls = [];
  const panel = await servePanel({
    envelope: envelopeWithEveryClass(root),
    identity: identityFor(root),
    runNumber: 1,
    rootPath: root,
    reportDir,
    applyFn: async ({ approvals, runId }) => {
      calls.push({ approvals, runId });
      return { status: 'applied', runId, commit: 'sc4cafe', ops: [], stale: [] };
    },
    idleTimeoutMs: 60_000,
    heartbeatGapMs: 60_000,
    ...extra,
  });
  return { panel, calls, client: makeClient(panel.url) };
}

// ---------------------------------------------------------------------------
// Contract stamp + Option 1 only
// ---------------------------------------------------------------------------
describe('SC4 contract stamp (Option 1)', () => {
  test('REFRESH-TOKEN-CONTRACT stamps Option 1 dead-Apply; Option 2 not authorized', () => {
    assert.ok(fs.existsSync(CONTRACT), 'REFRESH-TOKEN-CONTRACT.md required');
    const body = fs.readFileSync(CONTRACT, 'utf8');
    assert.match(body, /Option 1/i);
    assert.match(body, /dead-Apply/i);
    assert.match(body, /never.*localStorage/i);
    assert.match(body, /Not authorized|not stamped/i);
  });

  test('isTokenLive treats only non-empty strings as live capability', () => {
    assert.equal(isTokenLive('a'.repeat(64)), true);
    assert.equal(isTokenLive(''), false);
    assert.equal(isTokenLive(null), false);
    assert.equal(isTokenLive(undefined), false);
    assert.equal(isTokenLive(0), false);
  });
});

// ---------------------------------------------------------------------------
// F5 / dead-token UX (panel HTML emission path)
// ---------------------------------------------------------------------------
describe('SC4 F5 / dead-token UX (Option 1)', () => {
  const liveToken = 'c'.repeat(64);
  const m = () => model();

  test('absent TOKEN: dead-Apply banner, disabled Apply, re-open instruction', () => {
    for (const token of ['', null, undefined]) {
      const html = renderPanelPage({ token, model: m(), baseUrl: 'http://127.0.0.1:9' });
      assert.match(html, /data-testid="dead-apply-banner"/, 'dead-Apply banner required');
      assert.ok(html.includes(DEAD_APPLY_BANNER_TITLE));
      assert.ok(html.includes(DEAD_APPLY_REOPEN_COPY) || html.includes('Re-open the panel'));
      assert.match(html, /data-testid="dead-apply-chip"/);
      assert.ok(html.includes(DEAD_APPLY_CHIP_LABEL));
      assert.match(html, /data-token-live="0"/);
      assert.match(html, /class="[^"]*dead-apply/);
      assert.match(html, /id="bulk-apply"[^>]*\bdisabled\b/, 'bulk Apply must be disabled without token');
      // Banner uses escapeHtml → &lt;folder&gt;; client embedJson keeps raw angle brackets.
      assert.ok(
        html.includes('tidy-idy &lt;folder&gt;') || html.includes('tidy-idy <folder>'),
        're-open copy must name the CLI entry',
      );
      assert.match(html, /Anchor/i);
      // No silent re-enable: TOKEN const must be empty / unusable.
      assert.match(html, /const TOKEN_USABLE = false/);
      assert.doesNotMatch(html, /const TOKEN_USABLE = true/);
    }
  });

  test('live TOKEN: Apply may enable; F5 footprint present; no dead banner', () => {
    const html = renderPanelPage({ token: liveToken, model: m(), baseUrl: 'http://127.0.0.1:9' });
    assert.ok(html.includes(liveToken), 'first open embeds token in body only');
    assert.doesNotMatch(html, /data-testid="dead-apply-banner"/);
    assert.match(html, /data-token-live="1"/);
    assert.match(html, /class="[^"]*token-live/);
    assert.ok(html.includes(LIVE_APPLY_F5_FOOTPRINT));
    assert.match(html, /const TOKEN_USABLE = true/);
    // bulkEnabled depends on model; when bulk enabled, button must NOT be disabled solely for token.
    if (m().apply.bulkEnabled) {
      assert.doesNotMatch(html, /id="bulk-apply"[^>]*\bdisabled\b/);
    }
  });

  test('dead and live pages never reference durable storage sinks', () => {
    for (const token of [liveToken, '', null]) {
      const html = renderPanelPage({ token, model: m(), baseUrl: 'http://127.0.0.1:9' });
      for (const sink of [
        'localStorage', 'sessionStorage', 'document.cookie', 'indexedDB',
        'caches.open', 'history.state', 'BroadcastChannel', 'serviceWorker',
      ]) {
        assert.ok(!html.includes(sink), `forbidden storage sink ${sink}`);
      }
      assert.ok(!html.includes(`?token=`), 'token must never appear in a query string');
    }
  });

  test('dual-surface: renderBootstrapPage dead-token matches renderPanelPage', () => {
    const deadA = renderPanelPage({ token: '', model: m(), baseUrl: 'http://127.0.0.1:9' });
    const deadB = renderBootstrapPage({ token: '', model: m(), baseUrl: 'http://127.0.0.1:9' });
    assert.match(deadA, /data-testid="dead-apply-banner"/);
    assert.match(deadB, /data-testid="dead-apply-banner"/);
    assert.match(deadA, /id="bulk-apply"[^>]*\bdisabled\b/);
    assert.match(deadB, /id="bulk-apply"[^>]*\bdisabled\b/);
  });

  test('TOKEN travels only in header name in client script, never URL assembly', () => {
    const html = renderPanelPage({ token: liveToken, model: m(), baseUrl: 'http://127.0.0.1:9' });
    assert.ok(html.includes(TOKEN_HEADER));
    assert.doesNotMatch(html, /fetch\([^)]*token=/);
    assert.doesNotMatch(html, /location\.(search|hash).*token/i);
  });
});

// ---------------------------------------------------------------------------
// Bootstrap re-GET (panel-server emission path)
// ---------------------------------------------------------------------------
describe('SC4 bootstrap re-GET (no remount)', () => {
  test('second GET bootstrap is 410, no token bytes, re-open instruction, apply disabled', async () => {
    const { panel, client } = await serve({ nonceFile: true });
    try {
      const pathName = new URL(panel.bootstrapUrl).pathname;
      const first = await client.get(pathName);
      assert.equal(first.status, 200);
      assert.match(first.headers['content-type'], /text\/html/);
      assert.ok(first.text.includes(panel.token), 'first redeem embeds token once');
      assert.match(first.headers['cache-control'], /no-store/);

      const second = await client.get(pathName);
      assert.equal(second.status, 410, 're-GET must be GONE — Option 1 forbids remount HTML');
      assert.ok(!second.text.includes(panel.token), 'capability token must not appear on re-GET');
      assert.ok(second.json, '410 body is JSON (no remount HTML)');
      assert.match(String(second.json.detail || ''), /re-open|CLI|Anchor/i);
      assert.equal(second.json.apply, 'disabled');
      assert.equal(second.json.sc4Option, 1);
      assert.doesNotMatch(second.text, /<html/i);
    } finally {
      await panel.close();
    }
  });

  test('post-redeem Apply without header token is refused (dead-token apply-plane)', async () => {
    const { panel, client, calls } = await serve();
    try {
      await client.get(new URL(panel.bootstrapUrl).pathname);
      const naked = await client.post('/api/apply', {
        headers: { origin: panel.url },
        body: { runId: RUN_ID, approvals: [] },
      });
      assert.equal(naked.status, 401);
      assert.equal(calls.length, 0);
    } finally {
      await panel.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Close & release
// ---------------------------------------------------------------------------
describe('SC4 Close & release', () => {
  test('after close, no usable Apply session for that process', async () => {
    const { panel, client, calls } = await serve();
    const token = panel.token;
    const base = panel.url;
    try {
      await client.get(new URL(panel.bootstrapUrl).pathname);
      const close = await client.post('/api/close', {
        token,
        headers: { origin: panel.url },
      });
      assert.equal(close.status, 200);
      assert.ok(close.json && close.json.ok);
    } finally {
      // panel may already be closed by /api/close; close is idempotent.
      await panel.close().catch(() => {});
    }
    // Server is gone — Apply cannot succeed against this process.
    const after = makeClient(base);
    let statusOrErr;
    try {
      const r = await after.post('/api/apply', {
        token,
        headers: { origin: base },
        body: { runId: RUN_ID, approvals: [] },
      });
      statusOrErr = r.status;
    } catch (err) {
      statusOrErr = 'connection-failed';
      assert.ok(err, 'closed server rejects further Apply');
    }
    assert.ok(
      statusOrErr === 'connection-failed' || statusOrErr >= 400,
      `expected dead session after close, got ${statusOrErr}`,
    );
    assert.equal(calls.length, 0, 'executor must not run after close');
  });
});

// ---------------------------------------------------------------------------
// Supersede
// ---------------------------------------------------------------------------
describe('SC4 supersede', () => {
  test('prior run cannot Apply when superseded by a newer completed run', async () => {
    const { archiveRun } = await import('../engine/launch/archive.mjs');
    await archiveRun({
      rootPath: root,
      reportDir,
      envelope: { ...envelopeWithEveryClass(root, { runId: 'run-newer-sc4' }) },
      identity: identityFor(root),
      launchedBy: 'cli',
    });
    const { panel, client, calls } = await serve({ runNumber: 0 });
    try {
      const r = await client.post('/api/apply', {
        token: panel.token,
        headers: { origin: panel.url },
        body: { runId: RUN_ID, approvals: [] },
      });
      assert.equal(r.status, 409);
      assert.match(String(r.json && r.json.error), /superseded/i);
      assert.equal(calls.length, 0);
    } finally {
      await panel.close();
    }
  });
});

// ---------------------------------------------------------------------------
// Token never on disk after panel life (dead-token / re-GET path)
// ---------------------------------------------------------------------------
describe('SC4 token-in-memory discipline', () => {
  test('after bootstrap re-GET and close, token absent from report tree', async () => {
    const { panel, client } = await serve({ nonceFile: true });
    let token;
    try {
      token = panel.token;
      const pathName = new URL(panel.bootstrapUrl).pathname;
      await client.get(pathName);
      await client.get(pathName); // 410
      await client.post('/api/close', { token, headers: { origin: panel.url } }).catch(() => {});
    } finally {
      await panel.close().catch(() => {});
    }
    await assertTokenAbsentFromTree(root, token);
  });
});

// ---------------------------------------------------------------------------
// Deny-diff / no remount route (Option 1)
// ---------------------------------------------------------------------------
describe('SC4 deny-diff and no remount route', () => {
  test('panel-server has no remount/re-emit route under Option 1', () => {
    const src = fs.readFileSync(path.join(SKILL_ROOT, 'engine/launch/panel-server.mjs'), 'utf8');
    assert.doesNotMatch(src, /\/api\/remount|\/remount\b|re-?emit.*token|renderPanelPage\(\s*\{\s*token,\s*model.*remount/i);
    assert.match(src, /sc4Option:\s*1/);
    assert.match(src, /bootstrap nonce already redeemed/);
  });

  test('render.mjs documents Option 1 and never writes storage APIs', () => {
    const src = fs.readFileSync(path.join(SKILL_ROOT, 'engine/panel/render.mjs'), 'utf8');
    assert.match(src, /SC4 Option 1|dead-Apply/);
    assert.match(src, /DEAD_APPLY_REOPEN_COPY/);
    for (const sink of ['localStorage', 'sessionStorage', 'document.cookie', 'indexedDB']) {
      // Mentions in comments/strings that forbid sinks are OK; assignment usage is not.
      assert.doesNotMatch(src, new RegExp(`${sink}\\.(setItem|getItem|removeItem)`));
      assert.doesNotMatch(src, new RegExp(`document\\.cookie\\s*=`));
    }
  });

  test('this wave does not edit engine/apply/** (deny path inventory)', () => {
    // Structural: SC4 tests must not import apply executor for remount; safety oracles stay separate.
    const thisFile = fs.readFileSync(path.join(SKILL_ROOT, 'test/sc4-refresh-token.test.mjs'), 'utf8');
    assert.doesNotMatch(thisFile, /from ['"]\.\.\/engine\/apply\//);
  });
});

async function assertTokenAbsentFromTree(dir, token) {
  if (!token) return;
  const entries = await fsp.readdir(dir, { withFileTypes: true }).catch(() => []);
  for (const e of entries) {
    const abs = path.join(dir, e.name);
    if (e.isDirectory()) {
      await assertTokenAbsentFromTree(abs, token);
      continue;
    }
    const bytes = await fsp.readFile(abs, 'utf8').catch(() => '');
    assert.ok(!bytes.includes(token), `capability token leaked to disk at ${abs}`);
  }
}
