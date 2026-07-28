// project-engine.test.mjs — Phase-2 acceptance suite for the MULTI-WAVE engine.
// Run with: node --test test/project-engine.test.mjs
//
// Every test runs the REAL runProject() (which calls the UNCHANGED Phase-1
// runWave) against a fresh temp project, and proves a Phase-2 criterion with the
// orchestrator-run gate (the real test command) as ground truth:
//   - ascending multi-wave run -> project DONE (per-wave TAP counts asserted),
//   - truth-gated advance: a vacuous-GREEN wave HALTs the run; the next wave never runs,
//   - HALT propagation: a forced mid-plan HALT stops the run; later waves never run,
//   - ascending/gapped enforcement: a bad plan HALTs (never reordered),
//   - resume: clean checkpoint continues from the next wave; torn checkpoint HALTs;
//     a 'done' checkpoint reports complete.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { readCheckpoint, writeCheckpointAtomic, newCheckpoint, HaltError } from '../bin/foreman-lib.mjs';
import { runProject, clearHaltedCheckpoint, _internals } from '../bin/project-engine.mjs';
import { makeScriptedDriver } from '../bin/drivers/scripted-driver.mjs';

const FIXTURE = path.resolve(import.meta.dirname, '../fixtures/canonical-project');
const CALC_REPAIR = { file: 'src/calc.js', findLast: 'return a + b;', replace: 'return a - b;' };

function cleanup(dir) { fs.rmSync(dir, { recursive: true, force: true }); }

// --- canonical fixture staged to its honest wave-1 baseline (mirrors run-project --demo-canonical) ---
// F2-9: wave 1 must produce a COVERED deliverable (not be a no-op on an already-
// green suite, which now HALTs). So multiply is staged UN-implemented and wave 1's
// EXECUTE writes it — a real, test-covered source change. (Harness scaffolding.)
const MULTIPLY_DONE = 'return a * b;';
const MULTIPLY_STUB = 'return undefined; // wave 1 to implement: a * b';
function stageCanonical() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-proj-'));
  fs.cpSync(FIXTURE, dir, { recursive: true });
  const testFile = path.join(dir, 'test/calc.test.mjs');
  const calcFile = path.join(dir, 'src/calc.js');
  const original = fs.readFileSync(testFile, 'utf8');
  let cut = original.search(/\n\/\/ This is the test the planted bug breaks/);
  if (cut < 0) cut = original.search(/\ntest\('subtract/);
  const subtractBlock = original.slice(cut);
  fs.writeFileSync(testFile, original.slice(0, cut) + '\n'); // wave-1 baseline: add + multiply only
  const calcSrc = fs.readFileSync(calcFile, 'utf8');
  fs.writeFileSync(calcFile, calcSrc.replace(MULTIPLY_DONE, MULTIPLY_STUB)); // hold back multiply for wave 1
  const driverFor = (wave) => wave.n === 2
    ? makeScriptedDriver({
        repairs: [CALC_REPAIR],
        onExecute: () => {
          const cur = fs.readFileSync(testFile, 'utf8');
          if (!/test\('subtract/.test(cur)) fs.writeFileSync(testFile, cur + subtractBlock);
        },
      })
    : makeScriptedDriver({
        repairs: [],
        onExecute: () => {
          const cur = fs.readFileSync(calcFile, 'utf8');
          if (cur.includes(MULTIPLY_STUB)) fs.writeFileSync(calcFile, cur.replace(MULTIPLY_STUB, MULTIPLY_DONE));
        },
      });
  return { dir, driverFor };
}

// --- a minimal N-wave project with a chosen gate command ---
function makeProject({ testCommand, waveCount = 2, files = {} }) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-proj-'));
  let plan = '# Plan\n\ntest-command: `' + testCommand + '`\n\n';
  for (let i = 1; i <= waveCount; i++) plan += `## Wave ${i} — feature ${i}\n\nDo wave ${i}.\n\n`;
  fs.writeFileSync(path.join(dir, 'DESCRIPTION.md'), '# Desc\n');
  fs.writeFileSync(path.join(dir, 'IMPLEMENTATION-PLAN.md'), plan);
  fs.writeFileSync(path.join(dir, 'EXECUTION-LOG.md'), '# Log\n');
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return dir;
}

// A real, honestly-passing test file (so `node --test` is a non-vacuous GREEN).
const PASSING_TEST = {
  'test/ok.test.mjs':
    "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
    "test('truth', () => { assert.equal(1 + 1, 2); });\n",
};

test('multi-wave: 2 waves driven ascending to project DONE (per-wave TAP counts)', async () => {
  const { dir, driverFor } = stageCanonical();
  try {
    const result = await runProject({ projectDir: dir, driverFor, reviewerCount: 2, fixIterCap: 4 });

    assert.equal(result.status, 'DONE', 'project reaches DONE only after the final wave');
    assert.equal(result.totalWaves, 2);
    assert.equal(result.waveResults.length, 2, 'both waves ran');

    // ascending order
    assert.deepEqual(result.waveResults.map((w) => w.wave), [1, 2]);

    // per-wave TAP counts (NOT exit codes alone)
    const [w1, w2] = result.waveResults;
    assert.equal(w1.status, 'GO');
    assert.deepEqual([w1.tap.tests, w1.tap.pass, w1.tap.fail], [2, 2, 0], 'wave 1 gate: 2/2');
    assert.equal(w1.iterations, 0, 'wave 1 green after EXECUTE implements multiply (0 fix iters)');
    assert.equal(w2.status, 'GO');
    assert.deepEqual([w2.tap.tests, w2.tap.pass, w2.tap.fail], [3, 3, 0], 'wave 2 gate: 3/3 after fix');
    assert.equal(w2.iterations, 1, 'wave 2 took one fix iteration (red -> green)');

    // checkpoint coherently encodes multi-wave progress + project-DONE
    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.current_wave, 2);
    assert.equal(cp.total_waves, 2);
    assert.equal(cp.last_verdict, 'GO');
    assert.equal(cp.status, 'done');
    assert.equal(fs.existsSync(result.checkpointPath + '.tmp'), false, 'no stray .tmp across waves');
    assert.deepEqual(readCheckpoint(result.checkpointPath), cp, 'checkpoint round-trips');
  } finally { cleanup(dir); }
});

test('truth-gated advance: a VACUOUS-GREEN wave HALTs the run; the next wave never runs', async () => {
  // wave 1 gate exits 0 with no real tests -> vacuous-GREEN HALT (R2-3).
  const dir = makeProject({ testCommand: 'cmd /c exit 0', waveCount: 2 });
  try {
    const result = await runProject({
      projectDir: dir, driver: makeScriptedDriver({ repairs: [] }), fixIterCap: 4,
    });
    assert.equal(result.status, 'HALT', 'a vacuous-green wave must HALT, never advance');
    assert.equal(result.stoppedAt, 1, 'stopped at wave 1');
    assert.match(result.haltReason, /vacuous-GREEN HALT/);
    assert.equal(result.waveResults.length, 1, 'wave 2 was NEVER attempted');
    assert.equal(result.waveResults[0].wave, 1);

    // checkpoint reflects the stopped state at wave 1 (not wave 2)
    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.current_wave, 1);
    assert.equal(cp.status, 'halted');
    assert.equal(cp.last_verdict, 'HALT');
    assert.ok(cp.pending_action && cp.pending_action.length > 0);
  } finally { cleanup(dir); }
});

test('HALT propagation: a forced mid-plan HALT (non-convergence) stops the run; later waves never run', async () => {
  // wave 1 gate is genuinely RED and the driver has no repair -> non-convergence
  // HALT at wave 1. Wave 2 must never run.
  const dir = makeProject({
    testCommand: 'node --test',
    waveCount: 2,
    files: {
      'test/fail.test.mjs':
        "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
        "test('always fails', () => { assert.equal(1, 2); });\n",
    },
  });
  try {
    const result = await runProject({
      projectDir: dir, driver: makeScriptedDriver({ repairs: [] }), fixIterCap: 2,
    });
    assert.equal(result.status, 'HALT');
    assert.equal(result.stoppedAt, 1);
    assert.match(result.haltReason, /non-convergence HALT: hit MAX_ITERS=2/);
    assert.equal(result.waveResults.length, 1, 'wave 2 never ran after the wave-1 HALT');

    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.current_wave, 1);
    assert.equal(cp.status, 'halted');
  } finally { cleanup(dir); }
});

test('ascending enforcement: a NON-ASCENDING plan HALTs (not reordered)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-proj-'));
  try {
    fs.writeFileSync(path.join(dir, 'DESCRIPTION.md'), '# Desc\n');
    fs.writeFileSync(path.join(dir, 'EXECUTION-LOG.md'), '# Log\n');
    fs.writeFileSync(path.join(dir, 'IMPLEMENTATION-PLAN.md'),
      '# Plan\n\ntest-command: `node --test`\n\n## Wave 2 — second\n\nx\n\n## Wave 1 — first\n\ny\n');
    await assert.rejects(
      runProject({ projectDir: dir, driver: makeScriptedDriver({ repairs: [] }) }),
      (e) => e instanceof HaltError && /ascending/i.test(e.reason),
      'non-ascending plan must HALT, never reorder',
    );
  } finally { cleanup(dir); }
});

test('ascending enforcement: a GAPPED plan HALTs (not filled)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-proj-'));
  try {
    fs.writeFileSync(path.join(dir, 'DESCRIPTION.md'), '# Desc\n');
    fs.writeFileSync(path.join(dir, 'EXECUTION-LOG.md'), '# Log\n');
    fs.writeFileSync(path.join(dir, 'IMPLEMENTATION-PLAN.md'),
      '# Plan\n\ntest-command: `node --test`\n\n## Wave 1 — a\n\nx\n\n## Wave 3 — c\n\ny\n');
    await assert.rejects(
      runProject({ projectDir: dir, driver: makeScriptedDriver({ repairs: [] }) }),
      (e) => e instanceof HaltError && /contiguous/i.test(e.reason),
    );
  } finally { cleanup(dir); }
});

test('resume: a CLEAN checkpoint (wave 1 GO) continues from wave 2, not wave 1', async () => {
  // The resumed wave 2 makes a real, test-covered source change (src/r.js starts
  // wrong; the driver repairs it red->green), so it proves its own deliverable per
  // F2-9 — a no-op resumed wave would (correctly) HALT, which is not what this
  // test exercises (it exercises resume mechanics).
  const dir = makeProject({
    testCommand: 'node --test', waveCount: 2,
    files: {
      'src/r.js': 'export const dbl = (n) => n + n + 1;\n', // wrong: test wants n + n
      'test/r.test.mjs':
        "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
        "import { dbl } from '../src/r.js';\ntest('dbl', () => { assert.equal(dbl(3), 6); });\n",
    },
  });
  try {
    const checkpointPath = path.join(dir, 'foreman-checkpoint.json');
    // simulate "wave 1 converged, session died before wave 2"
    const cp = newCheckpoint({ plan_path: path.join(dir, 'IMPLEMENTATION-PLAN.md'), total_waves: 2 });
    cp.current_wave = 1; cp.last_verdict = 'GO'; cp.status = 'running';
    writeCheckpointAtomic(checkpointPath, cp);

    const result = await runProject({
      projectDir: dir,
      driver: makeScriptedDriver({ repairs: [{ file: 'src/r.js', findLast: 'n + n + 1', replace: 'n + n' }] }),
      resume: true,
    });
    assert.equal(result.status, 'DONE');
    assert.equal(result.waveResults.length, 1, 'only wave 2 ran on resume');
    assert.equal(result.waveResults[0].wave, 2, 'resumed at wave 2, did NOT redo wave 1');
    assert.equal(readCheckpoint(checkpointPath).status, 'done');
  } finally { cleanup(dir); }
});

test('resume: a TORN checkpoint HALTs (never best-effort parse)', async () => {
  const dir = makeProject({ testCommand: 'node --test', waveCount: 2, files: PASSING_TEST });
  try {
    const checkpointPath = path.join(dir, 'foreman-checkpoint.json');
    fs.writeFileSync(checkpointPath, '{ "plan_path": "x", "current_wave": 1, "tot'); // truncated/torn
    await assert.rejects(
      runProject({ projectDir: dir, driver: makeScriptedDriver({ repairs: [] }), resume: true }),
      (e) => e instanceof HaltError && /torn|invalid/i.test(e.reason),
      'a torn checkpoint must HALT on resume',
    );
  } finally { cleanup(dir); }
});

test('resume: a HALTED checkpoint is NOT auto-resumed (requires human)', async () => {
  const dir = makeProject({ testCommand: 'node --test', waveCount: 2, files: PASSING_TEST });
  try {
    const checkpointPath = path.join(dir, 'foreman-checkpoint.json');
    const cp = newCheckpoint({ plan_path: path.join(dir, 'IMPLEMENTATION-PLAN.md'), total_waves: 2 });
    cp.current_wave = 1; cp.last_verdict = 'HALT'; cp.status = 'halted';
    cp.pending_action = 'fix the thing';
    writeCheckpointAtomic(checkpointPath, cp);
    await assert.rejects(
      runProject({ projectDir: dir, driver: makeScriptedDriver({ repairs: [] }), resume: true }),
      (e) => e instanceof HaltError && /HALTED state/i.test(e.reason),
    );
  } finally { cleanup(dir); }
});

test('resume: a DONE checkpoint reports the project already complete (no waves re-run)', async () => {
  const dir = makeProject({ testCommand: 'node --test', waveCount: 2, files: PASSING_TEST });
  try {
    const checkpointPath = path.join(dir, 'foreman-checkpoint.json');
    const cp = newCheckpoint({ plan_path: path.join(dir, 'IMPLEMENTATION-PLAN.md'), total_waves: 2 });
    cp.current_wave = 2; cp.last_verdict = 'GO'; cp.status = 'done';
    writeCheckpointAtomic(checkpointPath, cp);
    const result = await runProject({
      projectDir: dir, driver: makeScriptedDriver({ repairs: [] }), resume: true,
    });
    assert.equal(result.status, 'DONE');
    assert.equal(result.waveResults.length, 0, 'no wave re-run when already done');
    assert.equal(result.resumed, true);
  } finally { cleanup(dir); }
});

test('planResume unit: maps checkpoint state -> start wave', () => {
  const dir = makeProject({ testCommand: 'node --test', waveCount: 3, files: PASSING_TEST });
  try {
    const cpPath = path.join(dir, 'cp.json');
    const base = newCheckpoint({ plan_path: 'p', total_waves: 3 });
    // wave 1 GO running -> start wave 2
    writeCheckpointAtomic(cpPath, { ...base, current_wave: 1, last_verdict: 'GO', status: 'running' });
    assert.equal(_internals.planResume(cpPath, 3).startWave, 2);
    // wave 2 running, no verdict -> re-run wave 2
    writeCheckpointAtomic(cpPath, { ...base, current_wave: 2, last_verdict: null, status: 'running' });
    assert.equal(_internals.planResume(cpPath, 3).startWave, 2);
    // done -> alreadyDone
    writeCheckpointAtomic(cpPath, { ...base, current_wave: 3, last_verdict: 'GO', status: 'done' });
    assert.equal(_internals.planResume(cpPath, 3).alreadyDone, true);
    // halted -> throws
    writeCheckpointAtomic(cpPath, { ...base, current_wave: 2, last_verdict: 'HALT', status: 'halted' });
    assert.throws(() => _internals.planResume(cpPath, 3), (e) => e instanceof HaltError);
  } finally { cleanup(dir); }
});

// --- clear-halt: the human acknowledgment path out of a HALT (T2, 2026-07-11) ---
// Previously go.ps1 appended a `--clear-halt` flag no code parsed, so every HALT
// meant hand-editing foreman-checkpoint.json. clearHaltedCheckpoint flips
// halted -> budget_stopped @ gate; resume then re-proves GREEN (never a backdoor).

test('clearHaltedCheckpoint: non-vacuous halt -> budget_stopped @ gate, iteration preserved, planResume resumes at the wave', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-clearhalt-'));
  try {
    const cpPath = path.join(dir, 'foreman-checkpoint.json');
    const base = newCheckpoint({ plan_path: 'p', total_waves: 3 });
    writeCheckpointAtomic(cpPath, {
      ...base, current_wave: 2, iteration: 2, intra_wave_step: 'fix',
      last_verdict: 'HALT', status: 'halted', pending_action: 'review transport: all reviewers failed',
    });

    const r = clearHaltedCheckpoint(cpPath);
    assert.equal(r.cleared, true);
    assert.equal(r.wave, 2);
    assert.match(r.clearedHalt, /review transport/);

    const cp = readCheckpoint(cpPath);
    assert.equal(cp.status, 'budget_stopped', 'cleared to the ordinary resumable stop state');
    assert.equal(cp.intra_wave_step, 'gate', 'resume re-enters AT THE GATE (re-proves GREEN)');
    assert.equal(cp.iteration, 2, 'remaining fix budget preserved');
    assert.match(cp.pending_action, /halt cleared by human/, 'audit trail records the human clear');
    assert.match(cp.pending_action, /review transport/, '...and what the halt was');

    // planResume now continues instead of throwing: same wave, intra-wave seed at the gate.
    const plan = _internals.planResume(cpPath, 3);
    assert.equal(plan.startWave, 2, 'resume re-enters the halted wave');
    assert.equal(plan.resumeFrom.intraStep, 'gate');
    assert.equal(plan.resumeFrom.iteration, 2);
  } finally { cleanup(dir); }
});

// Sleep 0076 package 3 / 0079: vacuous-GREEN clear-halt without force is thrash.
test('clearHaltedCheckpoint: vacuous-GREEN refuses without force (stays halted)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-clearhalt-vac-'));
  try {
    const cpPath = path.join(dir, 'foreman-checkpoint.json');
    const base = newCheckpoint({ plan_path: 'p', total_waves: 3 });
    writeCheckpointAtomic(cpPath, {
      ...base, current_wave: 2, iteration: 1, intra_wave_step: 'gate',
      last_verdict: 'HALT', status: 'halted',
      pending_action: 'vacuous-GREEN HALT: wave reached green without proving a deliverable',
    });
    const r = clearHaltedCheckpoint(cpPath);
    assert.equal(r.cleared, false);
    assert.equal(r.refused, true);
    assert.equal(r.status, 'halted');
    assert.equal(readCheckpoint(cpPath).status, 'halted');
  } finally { cleanup(dir); }
});

test('clearHaltedCheckpoint: idempotent no-op on non-halted checkpoints (safe to pass unconditionally)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-clearhalt-'));
  try {
    const cpPath = path.join(dir, 'foreman-checkpoint.json');
    const base = newCheckpoint({ plan_path: 'p', total_waves: 3 });
    for (const status of ['running', 'budget_stopped', 'done']) {
      const before = { ...base, current_wave: 1, status, last_verdict: status === 'done' ? 'GO' : null };
      writeCheckpointAtomic(cpPath, before);
      const r = clearHaltedCheckpoint(cpPath);
      assert.equal(r.cleared, false, `${status}: nothing to clear`);
      assert.equal(r.status, status);
      assert.deepEqual(readCheckpoint(cpPath), before, `${status}: checkpoint untouched`);
    }
    // A torn/invalid checkpoint still HALTs — clearing never guesses.
    fs.writeFileSync(cpPath, '{ "torn": tru');
    assert.throws(() => clearHaltedCheckpoint(cpPath), (e) => e instanceof HaltError);
  } finally { cleanup(dir); }
});
