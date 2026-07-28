// phase-a-efficiency.test.mjs — prior-attempt credit + plan-amendment re-entry (2026-07-22)
// North-Star: orchestrator gate still required; never auto-GO without green; FIX immutability untouched.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  _internals,
  writeWaveProvenLedger,
  readWaveProvenLedger,
  creditPriorWaveAttempt,
} from '../bin/wave-engine.mjs';

const vacGuard = _internals.checkVacuousGreen;

import { newCheckpoint, writeCheckpointAtomic, readCheckpoint } from '../bin/foreman-lib.mjs';
import { clearHaltedCheckpoint } from '../bin/project-engine.mjs';

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-phase-a-'));
}

test('wave proven ledger round-trips', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  try {
    writeWaveProvenLedger(foreman, 3, { changed: ['src/a.js'], pass: 2, tests: 2 });
    const led = readWaveProvenLedger(foreman, 3);
    assert.equal(led.wave, 3);
    assert.deepEqual(led.changed, ['src/a.js']);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('creditPriorWaveAttempt: credits when prior code exists and is name-exercised', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  try {
    fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'src', 'calc.js'), 'export const x = 1;\n');
    fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'test', 'calc.test.mjs'), 'import "../src/calc.js";\n');
    writeWaveProvenLedger(foreman, 1, { changed: ['src/calc.js'], pass: 1, tests: 1 });
    const r = creditPriorWaveAttempt(dir, foreman, 1, {
      reach: new Set(),
      exercisedByName: (f) => f.includes('calc'),
    });
    assert.equal(r.ok, true, r.note);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('creditPriorWaveAttempt: refuses when prior file is gone', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  try {
    writeWaveProvenLedger(foreman, 1, { changed: ['src/missing.js'] });
    const r = creditPriorWaveAttempt(dir, foreman, 1, {
      reach: new Set(['src/missing.js']),
      exercisedByName: () => true,
    });
    assert.equal(r.ok, false);
    assert.match(r.note, /missing/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('checkVacuousGreen: credits prior attempt when this-diff is empty', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  try {
    fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'src', 'calc.js'), 'export function add(a,b){return a+b}\n');
    fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
    // Import path so reachableFromTests can find it
    fs.writeFileSync(
      path.join(dir, 'test', 'calc.test.mjs'),
      `import { add } from '../src/calc.js';\nimport test from 'node:test';\ntest('a',()=>{});\n`,
    );
    writeWaveProvenLedger(foreman, 2, { changed: ['src/calc.js'], pass: 1, tests: 1 });
    const reason = vacGuard(dir, foreman, [], {
      invBefore: { tests: 1 },
      invNow: { tests: 1 },
      gateTap: { tests: 1, pass: 1 },
      waveTitle: 'Wave 2',
      waveN: 2,
    });
    assert.equal(reason, null, `expected credit, got: ${reason}`);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('checkVacuousGreen: still HALTs empty wave with no ledger', () => {
  const dir = tmpDir();
  const foreman = path.join(dir, '.foreman');
  fs.mkdirSync(foreman, { recursive: true });
  try {
    const reason = vacGuard(dir, foreman, [], {
      invBefore: { tests: 1 },
      invNow: { tests: 1 },
      gateTap: { tests: 1, pass: 1 },
      waveTitle: 'Wave 1',
      waveN: 1,
    });
    assert.ok(reason, 'must still vacuous-HALT without prior credit');
    assert.match(reason, /no source file|deliverable/i);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('clearHaltedCheckpoint: PLAN-AMENDMENT re-enters at execute', () => {
  const dir = tmpDir();
  const cpPath = path.join(dir, 'foreman-checkpoint.json');
  try {
    const cp = newCheckpoint({ plan_path: 'PLAN.md', total_waves: 5, reviewer_count: 2 });
    cp.status = 'halted';
    cp.current_wave = 3;
    cp.iteration = 2;
    cp.pending_action = 'PLAN-AMENDMENT-PROPOSAL for wave 3. Rationale: fix test cmd';
    writeCheckpointAtomic(cpPath, cp);
    const r = clearHaltedCheckpoint(cpPath);
    assert.equal(r.cleared, true);
    assert.equal(r.reentry, 'execute');
    const back = readCheckpoint(cpPath);
    assert.equal(back.status, 'budget_stopped');
    assert.equal(back.intra_wave_step, 'execute');
    assert.equal(back.iteration, 0);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('clearHaltedCheckpoint: ordinary (non-vacuous) halt still re-enters at gate', () => {
  const dir = tmpDir();
  const cpPath = path.join(dir, 'foreman-checkpoint.json');
  try {
    const cp = newCheckpoint({ plan_path: 'PLAN.md', total_waves: 5, reviewer_count: 2 });
    cp.status = 'halted';
    cp.current_wave = 2;
    cp.iteration = 1;
    // Sleep 0076 package 3: vacuous-GREEN is no longer "ordinary" clear — use a transport halt.
    cp.pending_action = 'review transport: all reviewers failed';
    writeCheckpointAtomic(cpPath, cp);
    const r = clearHaltedCheckpoint(cpPath);
    assert.equal(r.cleared, true);
    assert.equal(r.reentry, 'gate');
    const back = readCheckpoint(cpPath);
    assert.equal(back.intra_wave_step, 'gate');
    assert.equal(back.iteration, 1, 'ordinary clear preserves iteration');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
