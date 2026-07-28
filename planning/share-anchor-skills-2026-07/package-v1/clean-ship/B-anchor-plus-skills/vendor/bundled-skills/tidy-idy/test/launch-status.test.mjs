// launch-status.test.mjs — status.json + status page for live progress / re-open.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import {
  writeStatus, readStatus, renderStatusPage, PHASE,
} from '../engine/launch/run-status.mjs';
import { serveRunStatus } from '../engine/launch/status-server.mjs';

async function withTempDir(fn) {
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), 'tidy-status-'));
  try {
    return await fn(dir);
  } finally {
    await fsp.rm(dir, { recursive: true, force: true });
  }
}

function get(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        resolve({
          status: res.statusCode,
          headers: res.headers,
          body: Buffer.concat(chunks).toString('utf8'),
        });
      });
    }).on('error', reject);
  });
}

test('writeStatus merges and stamps updatedAt', async () => {
  await withTempDir(async (dir) => {
    await writeStatus(dir, { phase: PHASE.STARTING, message: 'hi', projectName: 'p' });
    await writeStatus(dir, { phase: PHASE.SCANNING, message: 'scan' });
    const st = await readStatus(dir);
    assert.equal(st.phase, PHASE.SCANNING);
    assert.equal(st.message, 'scan');
    assert.equal(st.projectName, 'p');
    assert.ok(st.updatedAt);
    assert.ok(st.startedAt);
  });
});

test('renderStatusPage includes poll client, favicon, progress bar, openUrl redirect', () => {
  const html = renderStatusPage({ title: 'Tidy-Idy — demo', pollUrl: '/api/status' });
  assert.match(html, /Tidy-Idy/);
  assert.match(html, /\/api\/status/);
  assert.match(html, /openUrl/);
  assert.match(html, /panel-ready/);
  assert.match(html, /rel="icon"/);
  assert.match(html, /id="barFill"/);
  assert.match(html, /id="pct"/);
  assert.match(html, /id="alive"/);
});

test('writeStatus stamps progress from step', async () => {
  await withTempDir(async (dir) => {
    const st = await writeStatus(dir, {
      phase: PHASE.ANALYZING,
      step: 'debate',
      message: 'Running debate…',
    });
    assert.equal(st.progress, 78);
    assert.equal(st.step, 'debate');
  });
});

test('forceNewRun resets startedAt so elapsed is not from a prior session', async () => {
  await withTempDir(async (dir) => {
    await writeStatus(dir, {
      phase: PHASE.PANEL_READY,
      startedAt: '2020-01-01T00:00:00.000Z',
      message: 'old',
    });
    const st = await writeStatus(dir, {
      phase: PHASE.STARTING,
      forceNewRun: true,
      startedAt: '2026-07-22T12:00:00.000Z',
      message: 'new run',
    });
    assert.equal(st.startedAt, '2026-07-22T12:00:00.000Z');
    assert.equal(st.phase, PHASE.STARTING);
    assert.equal(st.forceNewRun, undefined);
  });
});

test('serveRunStatus serves HTML and live JSON', async () => {
  await withTempDir(async (dir) => {
    await writeStatus(dir, {
      phase: PHASE.ANALYZING,
      message: 'Analyzing…',
      projectName: 'demo',
      findings: 3,
    });
    const srv = await serveRunStatus({ reportDir: dir, title: 'Tidy-Idy — demo' });
    try {
      const page = await get(srv.url);
      assert.equal(page.status, 200);
      assert.match(page.headers['content-type'] || '', /text\/html/);
      assert.match(page.body, /Tidy-Idy/);

      const api = await get(`${srv.baseUrl}/api/status`);
      assert.equal(api.status, 200);
      const st = JSON.parse(api.body);
      assert.equal(st.phase, PHASE.ANALYZING);
      assert.equal(st.findings, 3);
      assert.match(st.message, /Analyzing/);
    } finally {
      await srv.close();
    }
  });
});
