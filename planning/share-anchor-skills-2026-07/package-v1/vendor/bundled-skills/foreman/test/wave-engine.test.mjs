// wave-engine.test.mjs — Phase-1 acceptance suite for the one-wave engine.
// Run with: node --test test/wave-engine.test.mjs
//
// Every test runs the REAL engine against a fresh temp copy of the canonical
// fixture (so the shipped fixture stays red) and proves a Phase-1 criterion with
// the orchestrator-run gate (the real `node --test`) as ground truth.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { locateDocs, parseWaves, discoverTestCommand, readCheckpoint, HaltError } from '../bin/foreman-lib.mjs';
import { runWave, runGate, judge, collectFindings, _internals } from '../bin/wave-engine.mjs';
import { makeScriptedDriver } from '../bin/drivers/scripted-driver.mjs';
import { makeAgentDriver } from '../bin/wave-workflow.js';

const FIXTURE = path.resolve(import.meta.dirname, '../fixtures/canonical-project');
const CALC_REPAIR = { file: 'src/calc.js', findLast: 'return a + b;', replace: 'return a - b;' };

function freshCopy() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-wave-'));
  fs.cpSync(FIXTURE, dir, { recursive: true });
  return dir;
}
function cleanup(dir) { fs.rmSync(dir, { recursive: true, force: true }); }

/** Resolve the contract from a project dir the same way run-wave does. */
function contractOf(dir) {
  const docs = locateDocs(dir);
  const planText = fs.readFileSync(docs.plan, 'utf8');
  const waves = parseWaves(planText);
  const testCmd = discoverTestCommand(planText, dir);
  return { docs, waves, testCmd, wave: waves[waves.length - 1] };
}

test('end-to-end: planted bug is RED then driven GREEN by the fix loop (gate = ground truth)', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    // precondition: the shipped copy is buggy
    assert.match(fs.readFileSync(path.join(dir, 'src/calc.js'), 'utf8'), /return a \+ b;[\s\S]*\}\s*$/);

    const driver = makeScriptedDriver({ repairs: [CALC_REPAIR] });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 4,
    });

    assert.equal(result.status, 'GO', 'wave converged');
    assert.equal(result.iterations, 1, 'one fix iteration (first gate was RED, proving red->green)');
    assert.equal(result.gate.green, true, 'final orchestrator gate is GREEN');
    assert.equal(result.gate.tap.tests, 3);
    assert.equal(result.gate.tap.pass, 3);
    assert.equal(result.gate.tap.fail, 0);
    assert.equal(result.gate.written_by, 'orchestrator', 'gate artifact is orchestrator-owned');
    // the fix actually edited the source
    assert.match(fs.readFileSync(path.join(dir, 'src/calc.js'), 'utf8'), /subtract[\s\S]*return a - b;/);

    // checkpoint written atomically + round-trips, no stray .tmp
    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.last_verdict, 'GO');
    assert.equal(cp.current_wave, wave.n);
    assert.equal(cp.status, 'done'); // terminal wave GREEN
    assert.equal(fs.existsSync(result.checkpointPath + '.tmp'), false, 'no stray .tmp');
    assert.deepEqual(readCheckpoint(result.checkpointPath), cp, 'checkpoint round-trips byte-identical');
  } finally { cleanup(dir); }
});

test('bounded fix loop HALTs at the cap on an unfixable wave (no infinite loop)', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    const driver = makeScriptedDriver({ repairs: [] }); // no repair => never fixable
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 3,
    });
    assert.equal(result.status, 'HALT');
    assert.equal(result.iterations, 3, 'exactly cap fix iterations, then halt');
    assert.match(result.haltReason, /non-convergence HALT: hit MAX_ITERS=3/);
    assert.equal(result.gate.green, false);
    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.status, 'halted');
    assert.equal(cp.last_verdict, 'HALT');
    assert.ok(cp.pending_action && cp.pending_action.length > 0, 'halt records a recommended next action');
  } finally { cleanup(dir); }
});

test('forged "GREEN" in a sub-agent claim does NOT produce GO — only the gate decides', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    // reviewers lie that everything is green; NO repair is applied, so the real
    // gate stays RED. The engine must never reach GO.
    const driver = makeScriptedDriver({ repairs: [], forgeGreenClaim: true });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 2,
    });
    assert.equal(result.status, 'HALT', 'forged green never converges');
    assert.notEqual(result.verdict, 'GO');
    assert.equal(result.gate.green, false, 'gate of record stayed RED despite the forged claim');
  } finally { cleanup(dir); }
});

test('judge reads only the gate: a RED gate is never GO even with a green-claiming review', () => {
  const redGate = { green: false, exit_code: 1, tap: { tests: 3, pass: 2, fail: 1 } };
  // a reviewer claims green and reports nothing
  const findings = collectFindings([{ reviewer: 'r0', claim: 'GREEN all pass', findings: [] },
    { reviewer: 'r1', claim: 'GREEN all pass', findings: [] }]);
  assert.equal(judge(redGate, findings).go, false);
  // and a GREEN gate with a single (non-agreed) MAJOR is still GO (needs >=2 + repro)
  const greenGate = { green: true, exit_code: 0, tap: { tests: 3, pass: 3, fail: 0 } };
  const solo = collectFindings([{ reviewer: 'r0', findings: [{ severity: 'MAJOR', file: 'x.js', line: 1, rule: 'taste' }] }]);
  assert.equal(judge(greenGate, solo).go, true, 'single un-agreed finding does not block GREEN');
});

test('anti-test-weakening: deleting a test HALTs (no plan citation)', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    const driver = makeScriptedDriver({
      repairs: [CALC_REPAIR],
      onExecute: (ctx) => {
        // remove the subtract test entirely -> test count drops 3 -> 2
        const tf = path.join(ctx.projectDir, 'test/calc.test.mjs');
        let txt = fs.readFileSync(tf, 'utf8');
        txt = txt.replace(/test\('subtract[\s\S]*$/, '');
        fs.writeFileSync(tf, txt);
      },
    });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(result.status, 'HALT');
    assert.match(result.haltReason, /test-integrity HALT: test count dropped 3 -> 2/);
  } finally { cleanup(dir); }
});

test('test-immutability (Wave 7): a FIX that edits a test file HALTs (no count drop, no citation)', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    // The fix both repairs the source AND rewrites a test file (prepends a comment:
    // same test/assert count, so the anti-weakening guard would NOT catch it). The
    // immutability guard must HALT on the test-file edit by the fix loop.
    const driver = makeScriptedDriver({
      repairs: [
        CALC_REPAIR,
        { file: 'test/calc.test.mjs', findLast: 'import test from', replace: '/* fix-touch */ import test from' },
      ],
    });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(result.status, 'HALT');
    assert.match(result.haltReason, /test-immutability HALT: fix agent modified test file test\/calc\.test\.mjs/);
  } finally { cleanup(dir); }
});

test('test-immutability (Wave 7): a plan citation authorizes a fix-time test change (no false HALT)', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    // Same test edit, but the driver carries a plan citation — the change is
    // authorized, so the wave converges normally (source repaired, gate GREEN).
    const driver = makeScriptedDriver({
      citation: 'plan §X authorizes the test update',
      repairs: [
        CALC_REPAIR,
        { file: 'test/calc.test.mjs', findLast: 'import test from', replace: '/* authorized */ import test from' },
      ],
    });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(result.status, 'GO', 'a cited test change is authorized — no immutability HALT');
    assert.equal(result.gate.green, true);
  } finally { cleanup(dir); }
});

test('vacuous-GREEN guard: a GREEN gate that exercises no changed source HALTs (unit)', () => {
  const dir = freshCopy();
  try {
    const foremanDir = path.join(dir, '.foreman');
    // changed file IS imported by the test -> not vacuous
    assert.equal(_internals.checkVacuousGreen(dir, foremanDir, ['src/calc.js']), null);
    // a changed source file no test reaches -> vacuous HALT reason
    fs.writeFileSync(path.join(dir, 'src/orphan.js'), 'export const x = 1;\n');
    const reason = _internals.checkVacuousGreen(dir, foremanDir, ['src/orphan.js']);
    assert.match(reason || '', /did not exercise any changed source file/);
  } finally { cleanup(dir); }
});

test('vacuous-GREEN guard: doc/data-only diff HALTs even when tests mention the filename (wave-6 false-GO regression)', () => {
  // Live failure 2026-07-03/04 (Anchor rearchitecture wave 6): the gate run
  // itself refreshed a tracked generated .json whose name appears in test text,
  // the name-match rescue counted that side effect as a covered deliverable,
  // and a NO-OP wave converged repeatedly. Doc/data changes must never prove a
  // wave; a real code change alongside them still passes.
  const dir = freshCopy();
  try {
    const foremanDir = path.join(dir, '.foreman');
    fs.writeFileSync(path.join(dir, 'INVENTORY.json'), '{}\n');
    // make the artifact's name appear in test text (the rescue's old loophole)
    fs.appendFileSync(path.join(dir, 'test/calc.test.mjs'),
      '\n// regenerates INVENTORY.json as a side effect\n');
    const reason = _internals.checkVacuousGreen(dir, foremanDir, ['INVENTORY.json']);
    assert.match(reason || '', /only doc\/data artifacts/,
      'a doc/data-only diff must HALT, not converge');
    assert.equal(_internals.checkVacuousGreen(dir, foremanDir, ['src/calc.js', 'INVENTORY.json']), null,
      'code change alongside the artifact still passes');
  } finally { cleanup(dir); }
});

// --- T4 (2026-07-11): honest test-only path through the vacuous-GREEN guard ---
// Live failure (Anchor-zombie-build 2026-06-28): terminal acceptance wave 10/10
// HALTed "changed no source file reachable by an executed test" after 6 GO waves
// — but a test-only wave's deliverable IS its tests, and the engine already held
// the proof (inventory rose + the green gate ran the larger suite).

function testOnlyProject() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-testonly-'));
  fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'src', 'calc.js'), 'export const add = (a, b) => a + b;\n');
  fs.writeFileSync(path.join(dir, 'test', 'base.test.mjs'),
    "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
    "import { add } from '../src/calc.js';\n" +
    "test('add works', () => { assert.equal(add(1, 2), 3); });\n");
  return dir;
}

test('T4 REGRESSION: an acceptance wave that only ADDS a test reaches GO (inventory rose + gate ran the larger suite)', async () => {
  const dir = testOnlyProject();
  try {
    const wave = { n: 1, title: 'acceptance: end-to-end coverage', line: 1 };
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test', wave, totalWaves: 1, planPath: 'PLAN.md',
      driver: makeScriptedDriver({
        repairs: [],
        onExecute: async (ctx) => {
          fs.writeFileSync(path.join(ctx.projectDir, 'test', 'acceptance.test.mjs'),
            "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
            "import { add } from '../src/calc.js';\n" +
            "test('acceptance: add end-to-end', () => { assert.equal(add(40, 2), 42); });\n");
        },
      }),
      reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'GO', 'a genuine test-only deliverable must converge, not dead-stop');
    assert.equal(r.gate.green, true);
    assert.equal(r.gate.tap.tests, 2, 'the green gate executed the LARGER suite');
  } finally { cleanup(dir); }
});

test('T4: a modify-only test wave HALTs untagged, GOes with a [test-only] title tag', async () => {
  const editBaseTest = async (ctx) => {
    const f = path.join(ctx.projectDir, 'test', 'base.test.mjs');
    fs.writeFileSync(f, fs.readFileSync(f, 'utf8').replace('add(1, 2), 3', 'add(2, 2), 4'));
  };
  // untagged: no net-new tests -> the evidence bar fails -> HALT with the exact reason
  let dir = testOnlyProject();
  try {
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test',
      wave: { n: 1, title: 'tighten expectations', line: 1 }, totalWaves: 1, planPath: 'PLAN.md',
      driver: makeScriptedDriver({ repairs: [], onExecute: editBaseTest }),
      reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'HALT');
    assert.match(r.haltReason, /test-only evidence bar did not pass/,
      'the HALT explains exactly which leg failed');
  } finally { cleanup(dir); }
  // tagged: the human declared a modify-only test wave -> did-not-shrink + full gate suffices
  dir = testOnlyProject();
  try {
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test',
      wave: { n: 1, title: 'tighten expectations [test-only]', line: 1 }, totalWaves: 1, planPath: 'PLAN.md',
      driver: makeScriptedDriver({ repairs: [], onExecute: editBaseTest }),
      reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'GO', 'the [test-only] tag is the human channel for modify-only test waves');
  } finally { cleanup(dir); }
});

test('T4 unit: the evidence bar stays conservative — a partial gate or a no-op wave still HALTs', () => {
  const dir = testOnlyProject();
  try {
    const foremanDir = path.join(dir, '.foreman');
    const extra = (over = {}) => ({
      invBefore: { files: 1, tests: 1, asserts: 1, skips: 0 },
      invNow: { files: 2, tests: 2, asserts: 2, skips: 0 },
      gateTap: { tests: 2, pass: 2, fail: 0 }, waveTitle: '', ...over,
    });
    // full evidence -> accepted
    assert.equal(_internals.checkVacuousGreen(dir, foremanDir, ['test/extra.test.mjs'], extra()), null);
    // gate ran only a SUBSET of the new inventory -> conservative HALT
    assert.match(_internals.checkVacuousGreen(dir, foremanDir, ['test/extra.test.mjs'],
      extra({ gateTap: { tests: 1, pass: 1, fail: 0 } })) || '', /evidence bar did not pass/);
    // inventory SHRANK -> even a [test-only] tag does not accept it
    assert.match(_internals.checkVacuousGreen(dir, foremanDir, ['test/extra.test.mjs'],
      extra({ invNow: { files: 1, tests: 0, asserts: 0, skips: 0 }, waveTitle: 'x [test-only]' })) || '',
      /evidence bar did not pass/);
    // a wave that changed NOTHING keeps the original F2-9 no-op HALT untouched
    assert.match(_internals.checkVacuousGreen(dir, foremanDir, [], extra()) || '',
      /changed no source file reachable/);
    // and with NO evidence supplied (legacy 3-arg call) behavior is unchanged
    assert.match(_internals.checkVacuousGreen(dir, foremanDir, ['test/extra.test.mjs']) || '',
      /evidence bar did not pass|changed no source file reachable/);
  } finally { cleanup(dir); }
});

test('finding identity: same finding from 2 reviewers gets agreement=2 and a stable id', () => {
  const f = { severity: 'MAJOR', file: 'src/calc.js', line: 17, rule: 'assertion-failed' };
  const merged = collectFindings([
    { reviewer: 'r0', findings: [f] },
    { reviewer: 'r1', findings: [{ ...f }] },
  ]);
  assert.equal(merged.length, 1, 'deduped by id');
  assert.equal(merged[0].id, 'src/calc.js:17+assertion-failed');
  assert.equal(merged[0].agreement, 2);
});

test('dashboard renders with telemetry marked best-effort (§10)', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    const driver = makeScriptedDriver({ repairs: [CALC_REPAIR] });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver,
    });
    assert.match(result.dashboard, /\(best-effort\)/);
    assert.match(result.dashboard, /window OK/);
    assert.match(result.dashboard, /converged/);
  } finally { cleanup(dir); }
});

test('finding J: cross-role doc collision HALTs; canonical fixture does NOT false-positive', () => {
  // collision fixture: design-plan.md binds to BOTH description and plan
  const collisionDir = path.resolve(import.meta.dirname, 'neg-doc-collision');
  assert.throws(() => locateDocs(collisionDir),
    (e) => e instanceof HaltError && /two roles/.test(e.reason));
  // canonical fixture resolves cleanly via heuristic (no false positive)
  const docs = locateDocs(FIXTURE);
  assert.equal(docs.source, 'heuristic');
  assert.match(docs.description, /DESCRIPTION\.md$/);
  assert.match(docs.plan, /IMPLEMENTATION-PLAN\.md$/);
  assert.match(docs.execution_log, /EXECUTION-LOG\.md$/);
});

// ---------------------------------------------------------------------------
// R2-3 regression: a gate that exits 0 WITHOUT demonstrating real passing tests
// must HALT (vacuous-GREEN), exit 3, NEVER GO. Covers every vector the boundary
// re-review used. Each drives the REAL runWave; the no-op driver never repairs,
// so the only thing under test is the gate/judge green predicate.
// ---------------------------------------------------------------------------

/** Minimal on-disk project (gate command is overridden, so its own files don't run). */
function tmpProject(files = { 'src/x.js': 'export const x = 1;\n' }) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-vac-'));
  for (const [rel, content] of Object.entries(files)) {
    const abs = path.join(dir, rel);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return dir;
}

/** Drive one wave with a forced gate command + a driver that never repairs. */
function runVac(dir, testCommand) {
  const wave = { n: 1, title: 'vacuous-GREEN probe', line: 1 };
  return runWave({
    projectDir: dir, testCommand, wave, totalWaves: 1, planPath: 'PLAN.md',
    driver: makeScriptedDriver({ repairs: [] }), reviewerCount: 2, fixIterCap: 4,
  });
}

const VACUOUS_VECTORS = [
  ['vector 1 — exit 0, no TAP at all',              'cmd /c exit 0'],
  ['vector 2 — forged `echo # pass 99`, no events', 'cmd /c "echo # pass 99 & exit 0"'],
  ['vector 4 — `1..0` empty plan, exit 0',          'cmd /c "echo TAP version 13& echo 1..0& exit 0"'],
  ['vector 5 — skip-only (pass 0 / skip 1), exit 0',
    'cmd /c "echo # tests 1& echo # pass 0& echo # fail 0& echo # skipped 1& exit 0"'],
];

for (const [label, cmd] of VACUOUS_VECTORS) {
  test(`R2-3 ${label}: HALTs vacuous-GREEN (exit 3, not GO)`, async () => {
    const dir = tmpProject();
    try {
      const r = await runVac(dir, cmd);
      assert.equal(r.status, 'HALT', 'must HALT, never GO');
      assert.equal(r.verdict, 'HALT');
      assert.match(r.haltReason, /vacuous-GREEN HALT/);
      assert.match(r.haltReason, /refusing vacuous GREEN/);
      assert.equal(r.gate.green, false, 'gate is not GREEN');
      assert.equal(r.gate.exit_code, 0, 'exit 0 — proving this is the vacuous (not RED) path');
      // run-wave.mjs maps any non-GO result to process exit 3.
      assert.notEqual(r.status, 'GO');
    } finally { cleanup(dir); }
  });
}

test('R2-3 vector 3 — bare `node --test` with NO test files (tests 0) HALTs vacuous-GREEN', async () => {
  // A real node run (not a forged echo) that legitimately ran zero tests.
  const dir = tmpProject(); // src/x.js only — no test/ files for node --test to find
  try {
    const r = await runVac(dir, 'node --test');
    assert.equal(r.status, 'HALT', 'zero real tests must HALT, never GO');
    assert.match(r.haltReason, /vacuous-GREEN HALT/);
    assert.equal(r.gate.green, false);
    assert.equal(r.gate.exit_code, 0, 'node --test with no files exits 0');
    assert.equal(r.gate.tap.tests, 0, 'really ran node and saw zero tests');
  } finally { cleanup(dir); }
});

test('R2-3 forge defense — even a FULL fake count line (tests/pass/fail) HALTs without real events', async () => {
  // Hardens beyond the proposed count-only predicate: echoed counts that satisfy
  // tests>0 && pass>0 && fail===0 still HALT because no per-test event ran.
  const dir = tmpProject();
  try {
    const r = await runVac(dir, 'cmd /c "echo # tests 1& echo # pass 1& echo # fail 0& exit 0"');
    assert.equal(r.status, 'HALT', 'forged complete counts must not manufacture GO');
    assert.match(r.haltReason, /no real per-test events/);
    assert.equal(r.gate.green, false);
  } finally { cleanup(dir); }
});

test('R2-3 unit — runGate green predicate: structured pass ⇒ green; vacuous shapes ⇒ vacuous_reason', () => {
  const dir = tmpProject();
  const foremanDir = path.join(dir, '.foreman');
  const wave = { n: 1 };
  try {
    // positive: TAP test-point event (`ok 1`, ASCII so it survives cmd echo) +
    // positive counts ⇒ green, no vacuous_reason. (The end-to-end test above is
    // the integration positive control over a real spec-reporter `✔` green.)
    const g1 = runGate({ projectDir: dir, foremanDir, wave, iteration: 0,
      testCommand: 'cmd /c "echo ok 1 - add& echo # tests 1& echo # pass 1& echo # fail 0& exit 0"' });
    assert.equal(g1.green, true, 'real events + positive pass + 0 fail ⇒ GREEN');
    assert.equal(g1.vacuous_reason, null);
    // negative: exit 0, nothing ⇒ not green, vacuous_reason set
    const g2 = runGate({ projectDir: dir, foremanDir, wave, iteration: 1, testCommand: 'cmd /c exit 0' });
    assert.equal(g2.green, false);
    assert.match(g2.vacuous_reason || '', /refusing vacuous GREEN/);
    // a genuine RED (exit 1) is NOT vacuous — it keeps the normal fix-loop path
    const g3 = runGate({ projectDir: dir, foremanDir, wave, iteration: 2, testCommand: 'cmd /c exit 1' });
    assert.equal(g3.green, false);
    assert.equal(g3.vacuous_reason, null, 'non-zero exit is RED, never vacuous');
  } finally { cleanup(dir); }
});

// ---------------------------------------------------------------------------
// F2-9: a wave must demonstrate its OWN deliverable was exercised. A NO-OP wave
// (no changed source) on an already-green suite must HALT (it proves nothing),
// while a genuine wave that changes AND covers a source file must still GO.
// ---------------------------------------------------------------------------

const GREEN_FILES = {
  'src/m.js': 'export const inc = (n) => n + 1;\n',
  'test/m.test.mjs':
    "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
    "import { inc } from '../src/m.js';\ntest('inc', () => { assert.equal(inc(1), 2); });\n",
};

test('F2-9 (no-op): a no-op wave on an already-green suite HALTs — deliverable not proved', async () => {
  // The suite genuinely passes (real `node --test`), but the driver changes NO
  // source file. The gate is GREEN, yet the wave proved nothing about its work.
  const dir = tmpProject(GREEN_FILES);
  try {
    const r = await runVac(dir, 'node --test');
    assert.equal(r.status, 'HALT', 'a no-op wave must HALT, never GO/auto-advance');
    assert.match(r.haltReason, /vacuous-GREEN HALT/);
    assert.match(r.haltReason, /without proving its own deliverable was exercised/);
    // Prove this is the F2-9 path (green gate), NOT a red-gate halt.
    assert.equal(r.gate.green, true, 'the suite really passed — this is the deliverable-coverage halt');
    assert.equal(r.gate.exit_code, 0);
  } finally { cleanup(dir); }
});

test('F2-9 (positive): a wave that CHANGES and COVERS a source file still GOes', async () => {
  // Same green suite, but src/m.js starts wrong (inc returns n) and the driver
  // repairs it: a real, test-covered source change ⇒ deliverable demonstrably ran.
  const dir = tmpProject({
    ...GREEN_FILES,
    'src/m.js': 'export const inc = (n) => n + 0;\n', // wrong: test wants n + 1
  });
  try {
    const wave = { n: 1, title: 'inc', line: 1 };
    const driver = makeScriptedDriver({ repairs: [{ file: 'src/m.js', findLast: 'n + 0', replace: 'n + 1' }] });
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test', wave, totalWaves: 1,
      planPath: 'PLAN.md', driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'GO', 'a genuine change+cover wave converges to GO (no false-HALT)');
    assert.equal(r.gate.green, true);
    assert.equal(r.iterations, 1, 'red -> green in one fix iteration');
  } finally { cleanup(dir); }
});

// ---------------------------------------------------------------------------
// BRR-5: a hand-forged stream emitting a REAL `not ok 1` failing test point while
// lying `# fail 0` (exit 0) must HALT — the emitted failures exceed the claimed
// fail count, so the summary is internally inconsistent. A clean real green GOes.
// ---------------------------------------------------------------------------

test('BRR-5: a forged stream (`not ok 1` + `# fail 0` + exit 0) HALTs — inconsistent, never GO', async () => {
  const dir = tmpProject();
  try {
    const r = await runVac(dir,
      'cmd /c "echo not ok 1 - forged& echo # tests 1& echo # pass 1& echo # fail 0& exit 0"');
    assert.equal(r.status, 'HALT', 'a self-contradicting stream must not reach GO');
    assert.match(r.haltReason, /inconsistent with emitted test events/);
    assert.match(r.haltReason, /refusing GREEN/);
    assert.equal(r.gate.green, false);
    assert.equal(r.gate.exit_code, 0, 'exit 0 — proving the inconsistency path, not a RED gate');
  } finally { cleanup(dir); }
});

test('BRR-5 unit — runGate: passing event ⇒ green; `not ok` with `# fail 0` ⇒ refused; counts-only ⇒ refused', () => {
  const dir = tmpProject();
  const foremanDir = path.join(dir, '.foreman');
  const wave = { n: 1 };
  try {
    // honest single pass: ok 1 + # fail 0 + exit 0 ⇒ green, no vacuous_reason
    const g1 = runGate({ projectDir: dir, foremanDir, wave, iteration: 0,
      testCommand: 'cmd /c "echo ok 1 - p& echo # tests 1& echo # pass 1& echo # fail 0& exit 0"' });
    assert.equal(g1.green, true, 'a real passing event + consistent counts ⇒ GREEN');
    assert.equal(g1.vacuous_reason, null);
    // forged: a real `not ok 1` but the summary lies `# fail 0`, exit 0 ⇒ inconsistent
    const g2 = runGate({ projectDir: dir, foremanDir, wave, iteration: 1,
      testCommand: 'cmd /c "echo not ok 1 - forged& echo # tests 1& echo # pass 1& echo # fail 0& exit 0"' });
    assert.equal(g2.green, false);
    assert.match(g2.vacuous_reason || '', /inconsistent with emitted test events/);
    // counts only, no per-test event ran ⇒ refused (no real passing event)
    const g3 = runGate({ projectDir: dir, foremanDir, wave, iteration: 2,
      testCommand: 'cmd /c "echo # tests 1& echo # pass 1& echo # fail 0& exit 0"' });
    assert.equal(g3.green, false);
    assert.match(g3.vacuous_reason || '', /no real per-test events/);
  } finally { cleanup(dir); }
});

test('production agent-driver seam maps an injected agent() to the driver contract', async () => {
  // prove the production seam shape without a live Workflow run: inject a fake agent.
  const calls = [];
  const fakeAgent = async (prompt, opts) => {
    calls.push(opts?.label || 'execute');
    if (opts?.schema) return { answerable: 'yes', findings: [{ severity: 'MAJOR', file: 'a.js', line: 1, rule: 'x' }] };
    return 'ok';
  };
  const drv = makeAgentDriver({ agent: fakeAgent });
  const ctx = { wave: { n: 1, title: 't' }, reviewerIndex: 0, projectDir: '/p', iteration: 1 };
  assert.equal((await drv.execute(ctx)).note, 'agent execute complete');
  const rv = await drv.review(ctx, { artifact_path: '/p/.foreman/g.json', exit_code: 1, tap: { pass: 2, tests: 3 } });
  assert.equal(rv.answerable, 'yes');
  assert.equal(rv.findings.length, 1);
  assert.equal(rv.claim, undefined, 'production review carries no forgeable claim');
  assert.equal((await drv.fix(ctx, { artifact_path: '/p/.foreman/g.json' }, [])).note, 'agent fix complete');
  assert.throws(() => makeAgentDriver({}), TypeError);
});

// --- T10 (2026-07-11): transport failures degrade; the reviewer fan-out is stakes-gated ---

function passingProject() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-t10-'));
  fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'src', 'calc.js'), 'export const add = (a, b) => a + b;\n');
  fs.writeFileSync(path.join(dir, 'test', 'base.test.mjs'),
    "import test from 'node:test';\nimport assert from 'node:assert/strict';\n" +
    "import { add } from '../src/calc.js';\ntest('add', () => { assert.equal(add(1, 2), 3); });\n");
  return dir;
}
// execute touches src so the vacuous guard passes; review behavior injectable per call.
function t10Driver(reviewImpl) {
  let calls = 0;
  return {
    driver: {
      async execute(ctx) {
        const f = path.join(ctx.projectDir, 'src', 'calc.js');
        fs.writeFileSync(f, fs.readFileSync(f, 'utf8') + '// touched\n');
        return { note: 'touch', citation: null };
      },
      async review(ctx, gate) { calls += 1; return reviewImpl(ctx, gate, calls); },
      async fix() { return { note: 'no-op' }; },
    },
    reviewCalls: () => calls,
  };
}

test('T10a: ONE transport-failed reviewer is dropped loudly; the wave still GOes on the survivor', async () => {
  const dir = passingProject();
  try {
    const { driver } = t10Driver((ctx) => ctx.reviewerIndex === 0
      ? { reviewer: 'r0', answerable: 'transport-failed', transport_failed: true, note: 'agy exit 1', findings: [] }
      : { reviewer: 'r1', answerable: 'yes', claim: 'green', findings: [] });
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test', wave: { n: 1, title: 'w', line: 1 }, totalWaves: 1,
      planPath: 'PLAN.md', driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'GO', 'a lone dead reviewer cannot sink a verified wave');
    assert.equal(r.verdict, 'GO');
    assert.ok(!r.haltReason, 'no transport/ambiguity halt fired for a single dead reviewer');
  } finally { cleanup(dir); }
});

test('T10a: ALL reviewers transport-failed => transport HALT (nothing verified), not an ambiguity HALT', async () => {
  const dir = passingProject();
  try {
    const { driver } = t10Driver(() =>
      ({ reviewer: 'r', answerable: 'transport-failed', transport_failed: true, note: 'backend down', findings: [] }));
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test', wave: { n: 1, title: 'w', line: 1 }, totalWaves: 1,
      planPath: 'PLAN.md', driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'HALT');
    assert.match(r.haltReason, /review transport HALT/);
    assert.match(r.haltReason, /nothing verified/);
    assert.ok(!/ambiguity/.test(r.haltReason), 'a transport problem never masquerades as a plan problem');
  } finally { cleanup(dir); }
});

test('T10a: a GENUINE answerable:no still halts as ambiguity (the §4.7 gate is untouched)', async () => {
  const dir = passingProject();
  try {
    const { driver } = t10Driver(() =>
      ({ reviewer: 'r', answerable: 'no', note: 'the plan does not define the expected rounding', findings: [] }));
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test', wave: { n: 1, title: 'w', line: 1 }, totalWaves: 1,
      planPath: 'PLAN.md', driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'HALT');
    assert.match(r.haltReason, /ambiguity HALT/);
  } finally { cleanup(dir); }
});

test('T10b: ordinary mid-run wave runs a LEAN panel (1 reviewer); the terminal wave gets the full panel', async () => {
  // mid-run: wave 1 of 2 -> 1 review call
  let dir = passingProject();
  try {
    const { driver, reviewCalls } = t10Driver(() => ({ reviewer: 'r', answerable: 'yes', findings: [] }));
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test', wave: { n: 1, title: 'w', line: 1 }, totalWaves: 2,
      planPath: 'PLAN.md', driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'GO');
    assert.equal(reviewCalls(), 1, 'ordinary clean wave: second reviewer stakes-gated away');
  } finally { cleanup(dir); }
  // terminal: wave 2 of 2 -> full panel
  dir = passingProject();
  try {
    const { driver, reviewCalls } = t10Driver(() => ({ reviewer: 'r', answerable: 'yes', findings: [] }));
    const r = await runWave({
      projectDir: dir, testCommand: 'node --test', wave: { n: 2, title: 'w', line: 1 }, totalWaves: 2,
      planPath: 'PLAN.md', driver, reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'GO');
    assert.equal(reviewCalls(), 2, 'terminal wave: full adversarial panel');
  } finally { cleanup(dir); }
});
