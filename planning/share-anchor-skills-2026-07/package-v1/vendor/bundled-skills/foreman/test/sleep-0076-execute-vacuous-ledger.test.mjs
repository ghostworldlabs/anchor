// Sleep 0076 packages — unit coverage (2026-07-23)
// North Star: vacuous-GREEN stays hard; execute gets plan contract; ledger never logs.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  writeWaveProvenLedger,
  readWaveProvenLedger,
  creditPriorWaveAttempt,
  isRuntimeNoisePath,
  isProvenDeliverablePath,
  _internals,
} from '../bin/wave-engine.mjs';
import { _internals as wf } from '../bin/wave-workflow.js';
import { clearHaltedCheckpoint } from '../bin/project-engine.mjs';
import { newCheckpoint, writeCheckpointAtomic } from '../bin/foreman-lib.mjs';

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-sleep-0076-'));
}

test('package 6: isRuntimeNoisePath flags foreman logs', () => {
  assert.equal(isRuntimeNoisePath('_foreman-status.log'), true);
  assert.equal(isRuntimeNoisePath('_out-20260723-120000.log'), true);
  assert.equal(isRuntimeNoisePath('src/wire/decimal-string.mjs'), false);
});

test('package 6: writeWaveProvenLedger strips logs; keeps source', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  try {
    writeWaveProvenLedger(foreman, 1, {
      changed: ['_foreman-status.log', 'src/a.mjs', '_out-foo.log'],
      pass: 1,
      tests: 1,
    });
    const led = readWaveProvenLedger(foreman, 1);
    assert.deepEqual(led.changed, ['src/a.mjs']);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('package 6: writeWaveProvenLedger does not poison with log-only write', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  try {
    writeWaveProvenLedger(foreman, 2, { changed: ['src/good.mjs'] });
    const r = writeWaveProvenLedger(foreman, 2, {
      changed: ['_foreman-status.log', '_out-x.log'],
    });
    assert.equal(r, path.join(foreman, 'wave-2-proven.json')); // kept prior path
    const led = readWaveProvenLedger(foreman, 2);
    assert.deepEqual(led.changed, ['src/good.mjs']);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('package 6: creditPriorWaveAttempt ignores log paths in ledger', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  try {
    fs.mkdirSync(foreman, { recursive: true });
    fs.writeFileSync(path.join(dir, '_foreman-status.log'), 'x\n');
    // write raw ledger (bypass filter) to simulate old poison
    fs.writeFileSync(
      path.join(foreman, 'wave-1-proven.json'),
      JSON.stringify({ version: 1, wave: 1, changed: ['_foreman-status.log'] }) + '\n',
    );
    const r = creditPriorWaveAttempt(dir, foreman, 1, {
      reach: new Set(),
      exercisedByName: () => true,
    });
    assert.equal(r.ok, false);
    assert.match(r.note, /no live code|filtered/i);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('package 1: extractWaveSection pulls deliverables/done-when', () => {
  const plan = [
    '# Plan',
    'test-command: node scripts/run-all-tests.mjs',
    '',
    '## Wave 1 — First',
    '',
    '**Deliverables:** foo.mjs',
    '',
    '**done-when:** foo works',
    '',
    '## Wave 2 — Second',
    '',
    '**Deliverables:** bar.mjs',
    '',
  ].join('\n');
  const sec = wf.extractWaveSection(plan, 1);
  assert.match(sec, /Deliverables:\*\*\s*foo/);
  assert.match(sec, /done-when:\*\*\s*foo works/i);
  assert.ok(!sec.includes('bar.mjs'));
  // Final wave (no following ## Wave) must also extract (JS has no \Z).
  const sec2 = wf.extractWaveSection(plan, 2);
  assert.match(sec2, /bar\.mjs/);
});

test('package 1: executePrompt includes wave contract block', () => {
  const plan = [
    '## Wave 3 — Wire',
    '**Deliverables:** src/wire.mjs and tests',
    '**done-when:** round-trip green',
  ].join('\n');
  const prompt = wf.executePrompt({
    projectDir: 'C:\\proj',
    planPath: 'C:\\proj\\IMPLEMENTATION-PLAN.md',
    planText: plan,
    testCommand: 'node scripts/run-all-tests.mjs',
    wave: { n: 3, title: 'Wire' },
  });
  assert.match(prompt, /BEGIN WAVE CONTRACT/);
  assert.match(prompt, /src\/wire\.mjs/);
  assert.match(prompt, /round-trip green/);
  assert.match(prompt, /ORCHESTRATOR GATE/);
  assert.match(prompt, /vacuous-GREEN/);
});

test('package 3: clearHaltedCheckpoint refuses vacuous without force', () => {
  const dir = tmpDir();
  const cpPath = path.join(dir, 'foreman-checkpoint.json');
  try {
    const cp = newCheckpoint({ plan_path: '/p/IMPLEMENTATION-PLAN.md', total_waves: 3 });
    cp.status = 'halted';
    cp.current_wave = 2;
    cp.pending_action = 'vacuous-GREEN HALT: wave reached green without proving…';
    writeCheckpointAtomic(cpPath, cp);
    const r = clearHaltedCheckpoint(cpPath, { log: () => {} });
    assert.equal(r.cleared, false);
    assert.equal(r.refused, true);
    assert.equal(r.status, 'halted');
    const still = JSON.parse(fs.readFileSync(cpPath, 'utf8'));
    assert.equal(still.status, 'halted');
    assert.match(still.pending_action, /REFUSED|do NOT|vacuous/i);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('package 3: clearHaltedCheckpoint vacuous with force re-enters execute', () => {
  const dir = tmpDir();
  const cpPath = path.join(dir, 'foreman-checkpoint.json');
  try {
    const cp = newCheckpoint({ plan_path: '/p/IMPLEMENTATION-PLAN.md', total_waves: 3 });
    cp.status = 'halted';
    cp.current_wave = 2;
    cp.iteration = 1;
    cp.pending_action = 'vacuous-GREEN HALT: empty delta';
    writeCheckpointAtomic(cpPath, cp);
    const r = clearHaltedCheckpoint(cpPath, { log: () => {}, force: true });
    assert.equal(r.cleared, true);
    assert.equal(r.reentry, 'execute');
    const next = JSON.parse(fs.readFileSync(cpPath, 'utf8'));
    assert.equal(next.status, 'budget_stopped');
    assert.equal(next.intra_wave_step, 'execute');
    assert.equal(next.iteration, 0);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('package 6: isProvenDeliverablePath rejects logs', () => {
  assert.equal(isProvenDeliverablePath('_out-foo.log'), false);
  assert.equal(isProvenDeliverablePath('src/x.mjs'), true);
});

// Package 5 (engine side): runtime noise excluded from hash-diff so re-running a
// green suite / status log thrash does not look like a wave delta.
test('package 5: changedSince ignores runtime noise paths', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
  fs.mkdirSync(foreman, { recursive: true });
  fs.writeFileSync(path.join(dir, 'src', 'a.mjs'), 'export const a = 1;\n');
  try {
    const start = _internals.snapshotHashes(dir, foreman);
    fs.writeFileSync(path.join(dir, '_foreman-status.log'), 'tick\n');
    fs.writeFileSync(path.join(dir, '_out-20260723-120000.log'), 'noise\n');
    fs.writeFileSync(path.join(dir, 'src', 'a.mjs'), 'export const a = 2;\n'); // real delta
    const ch = _internals.changedSince(dir, foreman, start);
    assert.ok(ch.includes('src/a.mjs'), 'real source delta visible');
    assert.ok(!ch.some((f) => f.includes('_foreman-status') || f.includes('_out-')), 'logs not in delta');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('package 4: preflight refuses bare node --test test/', async () => {
  const { preflightTestCommand, isBadNodeTestDirectoryCommand, HaltError } =
    await import('../bin/foreman-lib.mjs');
  assert.equal(isBadNodeTestDirectoryCommand('node --test test/'), true);
  assert.throws(
    () => preflightTestCommand({ command: 'node --test test/', source: 'plan declaration' }),
    (e) => e instanceof HaltError && /known-broken|run-all-tests/i.test(e.detail || e.message || ''),
  );
});
