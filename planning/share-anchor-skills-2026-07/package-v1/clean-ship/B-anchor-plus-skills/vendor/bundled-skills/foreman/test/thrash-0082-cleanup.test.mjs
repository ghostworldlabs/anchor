// thrash-0082-cleanup.test.mjs — unit proof for remaining 0082 backlog items
// landed 2026-07-24 (agent heartbeat, wave-scoped gate, syntax smoke, doctor,
// proven-ledger helpers, parseWaves gate-command).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  withAgentHeartbeat,
  preGateSyntaxSmoke,
  resolveWaveGateCommand,
  writeWaveProvenLedger,
  readWaveProvenLedger,
} from '../bin/wave-engine.mjs';
import { parseWaves, doctorTestCommand } from '../bin/foreman-lib.mjs';
import { acquireLock, isPidAlive } from '../bin/proc-guard.mjs';

test('withAgentHeartbeat emits waiting-on-agent lines', async () => {
  const lines = [];
  const out = await withAgentHeartbeat(
    (s) => lines.push(s),
    'execute',
    async () => {
      await new Promise((r) => setTimeout(r, 30));
      return 42;
    },
    10, // fast interval for unit test
  );
  assert.equal(out, 42);
  assert.ok(lines.some((l) => /waiting on agent:execute/.test(l)),
    `expected heartbeat lines, got: ${lines.join(' | ')}`);
});

test('resolveWaveGateCommand prefers wave.gateCommand', () => {
  assert.equal(
    resolveWaveGateCommand({ gateCommand: 'pytest -v tests/ -k foo' }, 'pytest -v'),
    'pytest -v tests/ -k foo',
  );
  assert.equal(resolveWaveGateCommand({}, 'pytest -v'), 'pytest -v');
});

test('parseWaves captures per-wave gate-command', () => {
  const plan = [
    '# Plan',
    '',
    'test-command: pytest -v',
    '',
    '## Wave 1 — one',
    'gate-command: pytest -v tests/ -k share_',
    'done-when: green',
    '',
    '## Wave 2 — two',
    'done-when: also green',
  ].join('\n');
  const waves = parseWaves(plan);
  assert.equal(waves[0].gateCommand, 'pytest -v tests/ -k share_');
  assert.equal(waves[1].gateCommand, undefined);
});

test('preGateSyntaxSmoke catches broken JS', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fm-smoke-'));
  try {
    fs.writeFileSync(path.join(dir, 'bad.js'), 'function ({\n', 'utf8');
    const reason = preGateSyntaxSmoke(dir, ['bad.js']);
    assert.ok(reason && /syntax smoke failed/.test(reason), reason);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('preGateSyntaxSmoke accepts valid JS', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fm-smoke-ok-'));
  try {
    fs.writeFileSync(path.join(dir, 'ok.js'), 'export const x = 1;\n', 'utf8');
    assert.equal(preGateSyntaxSmoke(dir, ['ok.js']), null);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('writeWaveProvenLedger + readWaveProvenLedger round-trip code paths', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fm-led-'));
  try {
    const p = writeWaveProvenLedger(dir, 3, {
      changed: ['share_onboard.py', '_foreman-status.log', 'README.md'],
      tests: 10, pass: 10,
    });
    assert.ok(p);
    const led = readWaveProvenLedger(dir, 3);
    assert.deepEqual(led.changed, ['share_onboard.py']);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('doctorTestCommand fails empty and passes node --test on a real file', () => {
  assert.equal(doctorTestCommand('').ok, false);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fm-doc-'));
  try {
    fs.writeFileSync(path.join(dir, 't.test.mjs'),
      "import { test } from 'node:test';\nimport assert from 'node:assert';\ntest('x', () => assert.equal(1,1));\n",
      'utf8');
    const d = doctorTestCommand('node --test t.test.mjs', dir);
    assert.equal(d.ok, true, d.note);
    assert.ok(d.tests > 0, d.note);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('acquireLock onStale fires for dead-pid lock', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fm-lock-'));
  const lockPath = path.join(dir, 'run.lock');
  // Use a pid that is almost certainly dead
  let deadPid = 999999;
  while (isPidAlive(deadPid)) deadPid--;
  fs.writeFileSync(lockPath, JSON.stringify({ pid: deadPid, started_at: 1 }), 'utf8');
  const seen = [];
  const h = acquireLock(lockPath, {
    onStale: (prev) => seen.push(prev.pid),
  });
  assert.deepEqual(seen, [deadPid]);
  h.release();
  fs.rmSync(dir, { recursive: true, force: true });
});
