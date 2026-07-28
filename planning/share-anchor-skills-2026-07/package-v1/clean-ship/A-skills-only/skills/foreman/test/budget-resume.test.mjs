// budget-resume.test.mjs — Phase-3b acceptance suite: budget enforcement as a
// HARD pre-flight gate (§4.6/§6.1) + intra-wave resume (§8), NO git (Phase 3c).
// Run with: node --test test/budget-resume.test.mjs
//
// Every test runs the REAL engine (runProject/runWave) against a fresh temp
// project, with the orchestrator-run gate (the real test command) as ground truth.
// The budget's clock is injectable so wall-clock stops are deterministic.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  makeBudget, newCheckpoint, writeCheckpointAtomic, readCheckpoint, HaltError,
} from '../bin/foreman-lib.mjs';
import { runProject } from '../bin/project-engine.mjs';
import { makeScriptedDriver } from '../bin/drivers/scripted-driver.mjs';

function cleanup(dir) { fs.rmSync(dir, { recursive: true, force: true }); }

/** A deterministic, SATURATING clock: returns each value once, then sticks on the last. */
function clockOf(values) {
  let i = 0;
  return () => (i < values.length ? values[i++] : values[values.length - 1]);
}

/** Build an N-wave project whose docs + plan parse; no source/test files yet. */
function makeWaveProject({ testCommand = 'node --test', waveCount = 3 } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-bud-'));
  let plan = '# Plan\n\ntest-command: `' + testCommand + '`\n\n';
  for (let i = 1; i <= waveCount; i++) plan += `## Wave ${i} — feature ${i}\n\nDo wave ${i}.\n\n`;
  fs.writeFileSync(path.join(dir, 'DESCRIPTION.md'), '# Desc\n');
  fs.writeFileSync(path.join(dir, 'IMPLEMENTATION-PLAN.md'), plan);
  fs.writeFileSync(path.join(dir, 'EXECUTION-LOG.md'), '# Log\n');
  return dir;
}

/**
 * Per-wave driver: wave k's EXECUTE writes src/fk.js (a real, test-covered source
 * change) + test/fk.test.mjs (a passing test). So each wave is a genuine GO in 0
 * fix iters (F2-9: deliverable demonstrably exercised), and later waves' tests do
 * not exist until their wave runs (so the gate is green at each step).
 */
function incrementalDriverFor(dir) {
  return (wave) => makeScriptedDriver({
    repairs: [],
    note: `implement wave ${wave.n}`,
    onExecute: () => {
      const n = wave.n;
      fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
      fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
      fs.writeFileSync(path.join(dir, `src/f${n}.js`), `export const f${n} = () => ${n};\n`);
      fs.writeFileSync(path.join(dir, `test/f${n}.test.mjs`),
        "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
        `import { f${n} } from '../src/f${n}.js';\ntest('f${n}', () => { assert.equal(f${n}(), ${n}); });\n`);
    },
  });
}

/** A single-wave project that is RED until src/calc.js is repaired a+b -> a-b. */
function makeRepairableProject() {
  const dir = makeWaveProject({ testCommand: 'node --test', waveCount: 1 });
  fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'src/calc.js'), 'export const sub = (a, b) => a + b;\n'); // BUG
  fs.writeFileSync(path.join(dir, 'test/calc.test.mjs'),
    "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
    "import { sub } from '../src/calc.js';\ntest('sub', () => { assert.equal(sub(7, 3), 4); });\n");
  return dir;
}
const SUB_REPAIR = { file: 'src/calc.js', findLast: 'a + b', replace: 'a - b' };

// ---------------------------------------------------------------------------
// makeBudget unit — the pre-flight gate + the conservative-telemetry fallback.
// ---------------------------------------------------------------------------

test('makeBudget: wave dimension — refuses to START a wave once the count is spent', () => {
  const b = makeBudget({ maxWaves: 2 });
  assert.equal(b.canStartWave().ok, true); b.startWave();
  assert.equal(b.canStartWave().ok, true); b.startWave();
  const pf = b.canStartWave();
  assert.equal(pf.ok, false);
  assert.equal(pf.dimension, 'waves');
  assert.match(pf.reason, /wave budget exhausted/);
  assert.equal(b.snapshotForCheckpoint().waves, 0);
});

test('makeBudget: wall-clock dimension — refuses once the deadline has passed', () => {
  // construct@0; canStartWave reads 10 (<1000 ok); canStartFixIter reads 999999 (>=1000 stop)
  const b = makeBudget({ maxWallClockMs: 1000, now: clockOf([0, 10, 999999]) });
  assert.equal(b.canStartWave().ok, true);
  const pf = b.canStartFixIter();
  assert.equal(pf.ok, false);
  assert.equal(pf.dimension, 'wall-clock');
  assert.match(pf.reason, /wall-clock budget exhausted/);
});

test('makeBudget CONSERVATIVE fallback: an unreadable clock HALTs (never runs unbounded)', () => {
  assert.throws(() => makeBudget({ maxWallClockMs: 1000, now: () => { throw new Error('no clock'); } }),
    (e) => e instanceof HaltError && /telemetry unreadable/.test(e.reason) && /unbounded/.test(e.reason));
  // a non-finite clock value is equally refused
  assert.throws(() => makeBudget({ maxWallClockMs: 1000, now: () => NaN }),
    (e) => e instanceof HaltError && /non-finite/.test(e.reason));
  // a malformed cap is a contract error, not "unlimited"
  assert.throws(() => makeBudget({ maxWaves: -1 }),
    (e) => e instanceof HaltError && /invalid/.test(e.reason));
});

// ---------------------------------------------------------------------------
// A. Budget enforced as a HARD GATE: the unaffordable unit never BEGINS.
// ---------------------------------------------------------------------------

test('A1 — wave budget: a run that cannot afford the next wave STOPS before starting it (resumable checkpoint)', async () => {
  const dir = makeWaveProject({ waveCount: 3 });
  try {
    const budget = makeBudget({ maxWaves: 2 }); // real clock, no wall-clock cap
    const result = await runProject({ projectDir: dir, driverFor: incrementalDriverFor(dir), budget });

    assert.equal(result.status, 'BUDGET-STOP', 'budget stop is its own status, not a DONE/HALT');
    assert.equal(result.dimension, 'waves');
    assert.equal(result.stoppedAt, 3, 'stopped BEFORE wave 3');
    assert.equal(result.waveResults.length, 2, 'only waves 1 and 2 ran');
    assert.deepEqual(result.waveResults.map((w) => w.status), ['GO', 'GO']);

    // PROOF the unaffordable unit never began: wave 3's deliverable was never written.
    assert.equal(fs.existsSync(path.join(dir, 'src/f3.js')), false, 'wave 3 EXECUTE never ran');
    assert.equal(fs.existsSync(path.join(dir, 'test/f3.test.mjs')), false);

    // Budget-stop state is distinguishable in the checkpoint, and is resumable.
    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.status, 'budget_stopped', 'distinct from "halted" (error) and "done"');
    assert.equal(cp.last_verdict, 'BUDGET-STOP');
    assert.equal(cp.current_wave, 3, 'records the un-started wave to resume into');
    assert.equal(cp.intra_wave_step, 'execute', 'wave 3 never started -> resume from EXECUTE');
    assert.equal(cp.iteration, 0);
    assert.equal(cp.budget_remaining.waves, 0, 'budget snapshot recorded');
    assert.ok(cp.pending_action && /resumable/.test(cp.pending_action));

    // atomic: no stray .tmp; byte-identical round-trip.
    assert.equal(fs.existsSync(result.checkpointPath + '.tmp'), false, 'no stray .tmp');
    assert.deepEqual(readCheckpoint(result.checkpointPath), cp, 'checkpoint round-trips');
  } finally { cleanup(dir); }
});

test('A2 — resuming a wave-level budget stop finishes the run to DONE (only the un-run waves run)', async () => {
  const dir = makeWaveProject({ waveCount: 3 });
  try {
    const r1 = await runProject({ projectDir: dir, driverFor: incrementalDriverFor(dir),
      budget: makeBudget({ maxWaves: 2 }) });
    assert.equal(r1.status, 'BUDGET-STOP');

    // Resume with a FRESH budget (a new window) large enough to finish.
    const r2 = await runProject({ projectDir: dir, driverFor: incrementalDriverFor(dir),
      resume: true, budget: makeBudget({ maxWaves: 5 }) });
    assert.equal(r2.status, 'DONE');
    assert.equal(r2.waveResults.length, 1, 'only wave 3 ran on resume (waves 1-2 not redone)');
    assert.equal(r2.waveResults[0].wave, 3);
    assert.equal(fs.existsSync(path.join(dir, 'src/f3.js')), true, 'wave 3 deliverable now written');
    assert.equal(readCheckpoint(r2.checkpointPath).status, 'done');
  } finally { cleanup(dir); }
});

test('A3 — wall-clock budget stops a run mid-fix-loop (intra-wave) with a resumable checkpoint', async () => {
  const dir = makeRepairableProject();
  try {
    // construct@0; canStartWave@0 (ok); canStartFixIter#1@0 (ok, before fix 1);
    // canStartFixIter#2@999999 (>=1000 -> STOP, after 1 fix iter); snapshot saturates.
    const budget = makeBudget({ maxWallClockMs: 1000, now: clockOf([0, 0, 0, 999999]) });
    const result = await runProject({
      projectDir: dir,
      driver: makeScriptedDriver({ repairs: [] }), // no repair -> stays RED, loop keeps trying
      fixIterCap: 4, budget,
    });
    assert.equal(result.status, 'BUDGET-STOP');
    assert.equal(result.dimension, 'wall-clock');
    assert.equal(result.stoppedAt, 1);

    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.status, 'budget_stopped');
    assert.equal(cp.last_verdict, 'BUDGET-STOP');
    assert.equal(cp.current_wave, 1);
    assert.equal(cp.intra_wave_step, 'gate', 'resume must re-enter at the GATE');
    assert.equal(cp.iteration, 1, 'one fix iteration was consumed before the stop');
    assert.equal(fs.existsSync(result.checkpointPath + '.tmp'), false, 'atomic: no stray .tmp');
    assert.deepEqual(readCheckpoint(result.checkpointPath), cp, 'round-trips byte-identical');
  } finally { cleanup(dir); }
});

// ---------------------------------------------------------------------------
// B. Intra-wave resume PRESERVES TRUTH: re-enters the gate; GO only on real green.
// ---------------------------------------------------------------------------

test('B1 — intra-wave resume re-enters the gate and reaches GO only on REAL green', async () => {
  const dir = makeRepairableProject();
  try {
    // 1) stop mid-fix-loop via wall-clock (no repair -> RED), iteration 1.
    const r1 = await runProject({
      projectDir: dir, driver: makeScriptedDriver({ repairs: [] }),
      budget: makeBudget({ maxWallClockMs: 1000, now: clockOf([0, 0, 0, 999999]) }),
    });
    assert.equal(r1.status, 'BUDGET-STOP');
    assert.equal(readCheckpoint(r1.checkpointPath).iteration, 1);
    // bug still on disk (the no-op fix never repaired it)
    assert.match(fs.readFileSync(path.join(dir, 'src/calc.js'), 'utf8'), /a \+ b/);

    // 2) resume with a REAL repair + a fresh budget. Resume re-enters the gate,
    //    re-proves the red->green transition, and only then GOes.
    const r2 = await runProject({
      projectDir: dir, driver: makeScriptedDriver({ repairs: [SUB_REPAIR] }),
      resume: true, budget: makeBudget({ maxWallClockMs: 60000 }),
    });
    assert.equal(r2.status, 'DONE');
    assert.equal(r2.waveResults.length, 1, 'only the resumed wave ran');
    const w = r2.waveResults[0];
    assert.equal(w.wave, 1);
    assert.equal(w.green, true, 'GO came from a real GREEN gate');
    assert.deepEqual([w.tap.tests, w.tap.pass, w.tap.fail], [1, 1, 0]);
    // no double-apply: the repair landed exactly once (single a - b, no leftover a + b)
    const calc = fs.readFileSync(path.join(dir, 'src/calc.js'), 'utf8');
    assert.match(calc, /a - b/);
    assert.equal(/a \+ b/.test(calc), false, 'bug fully replaced, not double-applied');
  } finally { cleanup(dir); }
});

test('B2 — resume is NOT a backdoor to GREEN: a resumed wave whose gate is vacuous still HALTs (R2-3)', async () => {
  // A budget_stopped checkpoint says "resume wave 1 at the gate". But the gate
  // command is vacuous (exit 0, no real tests). Resume must re-run the gate and
  // refuse a vacuous GREEN — never auto-advance/GO on a wave it cannot re-prove.
  const dir = makeWaveProject({ testCommand: 'cmd /c exit 0', waveCount: 1 });
  try {
    const checkpointPath = path.join(dir, 'foreman-checkpoint.json');
    const cp = newCheckpoint({ plan_path: path.join(dir, 'IMPLEMENTATION-PLAN.md'), total_waves: 1 });
    cp.current_wave = 1; cp.iteration = 1; cp.intra_wave_step = 'gate';
    cp.last_verdict = 'BUDGET-STOP'; cp.status = 'budget_stopped';
    writeCheckpointAtomic(checkpointPath, cp);

    const result = await runProject({
      projectDir: dir, driver: makeScriptedDriver({ repairs: [] }), resume: true,
    });
    assert.equal(result.status, 'HALT', 'a resumed wave that cannot re-prove green must HALT, never GO');
    assert.equal(result.stoppedAt, 1);
    assert.match(result.haltReason, /vacuous-GREEN HALT/);
    assert.equal(result.waveResults.length, 1);
    assert.notEqual(result.waveResults[0].status, 'GO', 'resume did not back-door a GO');
    // the wave ran the gate (re-entered it) — proven by the vacuous-GREEN refusal.
    assert.equal(readCheckpoint(checkpointPath).status, 'halted', 'now an error halt, not a clean budget stop');
  } finally { cleanup(dir); }
});

// ---------------------------------------------------------------------------
// C. Conservative fallback through the engine + no false-stop on a big budget.
// ---------------------------------------------------------------------------

test('C1 — runProject with budgetConfig + an unreadable clock HALTs (conservative, not unbounded)', async () => {
  const dir = makeWaveProject({ waveCount: 2 });
  try {
    await assert.rejects(
      runProject({
        projectDir: dir, driver: makeScriptedDriver({ repairs: [] }),
        budgetConfig: { maxWallClockMs: 1000, now: () => { throw new Error('no clock'); } },
      }),
      (e) => e instanceof HaltError && /telemetry unreadable/.test(e.reason),
      'an unreadable budget clock must HALT before running any wave',
    );
  } finally { cleanup(dir); }
});

test('C2 — a budget large enough to finish does NOT falsely stop: full run reaches DONE', async () => {
  const dir = makeWaveProject({ waveCount: 3 });
  try {
    const result = await runProject({
      projectDir: dir, driverFor: incrementalDriverFor(dir),
      budget: makeBudget({ maxWaves: 10, maxWallClockMs: 600000 }),
    });
    assert.equal(result.status, 'DONE', 'a generous budget must not false-stop a healthy run');
    assert.equal(result.waveResults.length, 3);
    assert.deepEqual(result.waveResults.map((w) => w.status), ['GO', 'GO', 'GO']);
    // real per-wave TAP counts captured
    for (const w of result.waveResults) assert.equal(w.green, true);
    assert.equal(readCheckpoint(result.checkpointPath).status, 'done');
  } finally { cleanup(dir); }
});

// ---------------------------------------------------------------------------
// D. No regression to the existing resume states (halted/done/running).
// ---------------------------------------------------------------------------

test('D1 — an ERROR halt checkpoint is STILL not auto-resumed (distinct from a budget stop)', async () => {
  const dir = makeWaveProject({ waveCount: 2 });
  try {
    const checkpointPath = path.join(dir, 'foreman-checkpoint.json');
    const cp = newCheckpoint({ plan_path: path.join(dir, 'IMPLEMENTATION-PLAN.md'), total_waves: 2 });
    cp.current_wave = 1; cp.last_verdict = 'HALT'; cp.status = 'halted'; cp.pending_action = 'fix it';
    writeCheckpointAtomic(checkpointPath, cp);
    await assert.rejects(
      runProject({ projectDir: dir, driver: makeScriptedDriver({ repairs: [] }), resume: true }),
      (e) => e instanceof HaltError && /HALTED state/.test(e.reason),
      'an error halt still requires a human (only budget stops auto-resume)',
    );
  } finally { cleanup(dir); }
});
