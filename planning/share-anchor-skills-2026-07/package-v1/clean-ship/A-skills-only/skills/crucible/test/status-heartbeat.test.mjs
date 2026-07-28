// status-heartbeat.test.mjs — the engine-emitted 10-min Status table (2026-07-11).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { startStatusHeartbeat } from '../bin/status-heartbeat.mjs';

test('no-op when no logPath (tests/dogfood stay silent)', () => {
  const hb = startStatusHeartbeat({ snapshot: () => ({}) });
  assert.doesNotThrow(() => hb.stop());
});

test('writes a t=0 table on arm and a final table on stop, in the LOCKED shape', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-hb-'));
  const logPath = path.join(dir, '_crucible-status.log');
  try {
    let clock = 0;
    const hb = startStatusHeartbeat({
      logPath, label: 'Crucible Stage 1', intervalMs: 600000, now: () => clock,
      snapshot: () => ({
        doing: 'Shark-Tank round 2 · dry — checking lock', status: '1/5 rounds run',
        tests: 'last round: DRY', blocker: 'none', eta: '<= 4 more round(s) to cap',
      }),
    });
    clock = 600000; // exactly 10 min later
    hb.stop();
    const out = fs.readFileSync(logPath, 'utf8');

    // Two tables (t=0 + final), both with the locked field spine.
    assert.equal((out.match(/^\[\d{2}:\d{2}\] Crucible Stage 1/gm) || []).length, 2);
    assert.match(out, /· t=0/);
    assert.match(out, /· final/);
    for (const field of ['Effort', 'Doing', 'Status', 'Tests', 'Blocker', 'Procs', 'ETA', 'To do']) {
      assert.match(out, new RegExp('^' + field + '\\s', 'm'), `table carries ${field}`);
    }
    assert.match(out, /Shark-Tank round 2/);
    assert.match(out, /elapsed 10m/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('a snapshot that throws never crashes the heartbeat (best-effort logging)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-hb-'));
  try {
    const hb = startStatusHeartbeat({
      logPath: path.join(dir, 's.log'), snapshot: () => { throw new Error('boom'); }, now: () => 0,
    });
    assert.doesNotThrow(() => hb.stop());
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
