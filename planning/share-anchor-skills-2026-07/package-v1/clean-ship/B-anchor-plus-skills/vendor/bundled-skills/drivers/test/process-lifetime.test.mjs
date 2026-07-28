// process-lifetime guards — F-H sleep fix unit tests (no live agents).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { installProcessLifetimeGuards, withPhaseProgress } from '../process-lifetime.mjs';

test('installProcessLifetimeGuards writes heartbeat and uninstalls cleanly', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pl-'));
  const heartbeatPath = path.join(dir, 'heartbeat.json');
  const crashPath = path.join(dir, 'last-crash.json');
  const lines = [];
  const g = installProcessLifetimeGuards({
    log: (s) => lines.push(s),
    heartbeatPath,
    crashPath,
    label: 'unit-test',
  });
  assert.equal(g.installed, true);
  g.beat({ phase: 'test' });
  assert.ok(fs.existsSync(heartbeatPath));
  const hb = JSON.parse(fs.readFileSync(heartbeatPath, 'utf8'));
  assert.equal(hb.label, 'unit-test');
  assert.equal(hb.phase, 'test');
  assert.equal(hb.alive, true);
  g.uninstall();
  assert.ok(lines.some((l) => /guards installed/.test(l)));
  assert.ok(lines.some((l) => /guards uninstalled/.test(l)));
});

test('withPhaseProgress stamps start/done and rethrows errors', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pl-'));
  const progressPath = path.join(dir, 'progress.json');
  const lines = [];
  const out = await withPhaseProgress({
    phase: 'phased-plan',
    log: (s) => lines.push(s),
    progressPath,
    fn: async () => 42,
  });
  assert.equal(out, 42);
  const done = JSON.parse(fs.readFileSync(progressPath, 'utf8'));
  assert.equal(done.phase, 'phased-plan');
  assert.equal(done.status, 'done');

  await assert.rejects(
    () => withPhaseProgress({
      phase: 'phased-plan',
      log: (s) => lines.push(s),
      progressPath,
      fn: async () => { throw new Error('boom'); },
    }),
    /boom/,
  );
  const err = JSON.parse(fs.readFileSync(progressPath, 'utf8'));
  assert.equal(err.status, 'error');
  assert.match(err.error, /boom/);
});

test('benign EPIPE/EIO never fatal-exits (stdout closed by parent)', () => {
  // 2026-07-24: live Foreman died mid-status-emit when parent closed the pipe.
  // isBenignIoError must swallow EPIPE/EIO so file status log keeps working.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pl-'));
  const crashPath = path.join(dir, 'last-crash.json');
  const lines = [];
  const g = installProcessLifetimeGuards({
    log: (s) => lines.push(s),
    crashPath,
    label: 'epipe-unit',
  });
  const epipe = Object.assign(new Error('write EPIPE'), { code: 'EPIPE' });
  g.fatal('uncaughtException', epipe, 2);
  assert.ok(!fs.existsSync(crashPath), 'EPIPE must not write last-crash.json');
  assert.ok(lines.some((l) => /benign.*EPIPE|benign uncaughtException/i.test(l)),
    `expected benign-ignore log, got: ${lines.join(' | ')}`);
  // Must not have scheduled process.exit via exitCode from this path
  // (fatal returns early before setting exitCode for benign IO).
  g.uninstall();
});

test('onFatal hook fires for non-benign fatal (Crucible HALT.json seam)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pl-'));
  const crashPath = path.join(dir, 'last-crash.json');
  const seen = [];
  const g = installProcessLifetimeGuards({
    log: () => {},
    crashPath,
    label: 'onfatal-unit',
    onFatal: (p) => seen.push(p),
  });
  // fatal schedules process.exit — stub so the unit suite is not killed.
  const realExit = process.exit;
  process.exit = () => {};
  try {
    g.fatal('uncaughtException', new Error('real boom'), 2);
    assert.equal(seen.length, 1);
    assert.equal(seen[0].kind, 'uncaughtException');
    assert.ok(fs.existsSync(crashPath));
  } finally {
    g.uninstall({ disarm: true });
    process.exit = realExit;
  }
});
