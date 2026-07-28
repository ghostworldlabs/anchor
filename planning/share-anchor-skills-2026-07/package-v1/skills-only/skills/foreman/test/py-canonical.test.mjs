// py-canonical.test.mjs — Phase-3d acceptance suite: the SAME gate-integrity
// guarantees as the JS engine, but with `python -m pytest -v` as the gate of
// record. Run with: node --test test/py-canonical.test.mjs
//
// Every test runs the REAL engine against a fresh temp copy of the Python
// canonical fixture (so the shipped fixture stays red) and proves a Phase-3d
// criterion against REAL pytest output — the orchestrator-run gate is ground
// truth exactly as for JS.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { locateDocs, parseWaves, discoverTestCommand, normalizePytestGate, readCheckpoint, HaltError } from '../bin/foreman-lib.mjs';
import { runWave, runGate, _internals } from '../bin/wave-engine.mjs';
import { makeScriptedDriver } from '../bin/drivers/scripted-driver.mjs';

const FIXTURE = path.resolve(import.meta.dirname, '../fixtures/py-canonical');
const PYTEST = 'python -m pytest -v';
// The LAST `return a + b` in calc.py is subtract's planted bug (add's stays correct).
const CALC_REPAIR = { file: 'calc.py', findLast: 'return a + b', replace: 'return a - b' };

function freshCopy() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-py-'));
  fs.cpSync(FIXTURE, dir, { recursive: true });
  return dir;
}
function cleanup(dir) { fs.rmSync(dir, { recursive: true, force: true }); }

function contractOf(dir) {
  const docs = locateDocs(dir);
  const planText = fs.readFileSync(docs.plan, 'utf8');
  const waves = parseWaves(planText);
  const testCmd = discoverTestCommand(planText, dir);
  return { docs, waves, testCmd, wave: waves[waves.length - 1] };
}

// A minimal on-disk project with NO test files (pytest will collect 0 -> exit 5).
function tmpProjectNoTests() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-pyvac-'));
  fs.writeFileSync(path.join(dir, 'calc.py'), 'def add(a, b):\n    return a + b\n');
  return dir;
}

test('Phase 3d end-to-end: planted pytest bug is RED then driven GREEN (gate = python -m pytest -v)', async () => {
  const dir = freshCopy();
  try {
    const { docs, waves, testCmd, wave } = contractOf(dir);
    assert.equal(testCmd.command, PYTEST, 'gate command discovered from the plan');
    // precondition: the shipped copy carries the bug
    assert.match(fs.readFileSync(path.join(dir, 'calc.py'), 'utf8'), /subtract[\s\S]*return a \+ b/);

    const driver = makeScriptedDriver({ repairs: [CALC_REPAIR] });
    const result = await runWave({
      projectDir: dir, testCommand: testCmd.command, wave, totalWaves: waves.length,
      planPath: docs.plan, driver, reviewerCount: 2, fixIterCap: 4,
    });

    assert.equal(result.status, 'GO', 'wave converged');
    assert.equal(result.iterations, 1, 'one fix iteration (first gate was RED) — proves red->green');
    assert.equal(result.gate.green, true, 'final orchestrator gate is GREEN');
    assert.equal(result.gate.tap.tests, 3, 'derived tests = passed(3)+failed(0)');
    assert.equal(result.gate.tap.pass, 3);
    assert.equal(result.gate.tap.fail, 0);
    assert.equal(result.gate.written_by, 'orchestrator', 'gate artifact is orchestrator-owned');
    // the fix actually edited the source (subtract now subtracts)
    assert.match(fs.readFileSync(path.join(dir, 'calc.py'), 'utf8'), /subtract[\s\S]*return a - b/);

    const cp = readCheckpoint(result.checkpointPath);
    assert.equal(cp.last_verdict, 'GO');
    assert.equal(cp.current_wave, wave.n);
    assert.equal(cp.status, 'done'); // terminal wave GREEN
    assert.equal(fs.existsSync(result.checkpointPath + '.tmp'), false, 'no stray .tmp');
  } finally { cleanup(dir); }
});

test('Phase 3d: the shipped (unfixed) fixture is a genuine RED under real pytest (green=false, exit 1)', () => {
  const dir = freshCopy();
  const foremanDir = path.join(dir, '.foreman');
  try {
    const g = runGate({ projectDir: dir, foremanDir, wave: { n: 2 }, iteration: 0, testCommand: PYTEST });
    assert.equal(g.green, false, 'planted bug => not green');
    assert.equal(g.exit_code, 1, 'real pytest failure exits 1');
    assert.equal(g.vacuous_reason, null, 'a genuine failure is RED, NOT vacuous (keeps the fix-loop path)');
    assert.equal(g.tap.tests, 3);
    assert.equal(g.tap.pass, 2);
    assert.equal(g.tap.fail, 1);
  } finally { cleanup(dir); }
});

test('Phase 3d: a genuine GREEN pytest run => green=true with correct derived tap (unit, real pytest)', () => {
  const dir = freshCopy();
  const foremanDir = path.join(dir, '.foreman');
  try {
    // fix the bug on disk (the LAST `return a + b` is subtract's), then gate
    const calc = path.join(dir, 'calc.py');
    const src = fs.readFileSync(calc, 'utf8');
    const i = src.lastIndexOf('return a + b');
    fs.writeFileSync(calc, src.slice(0, i) + 'return a - b' + src.slice(i + 'return a + b'.length));
    const g = runGate({ projectDir: dir, foremanDir, wave: { n: 2 }, iteration: 1, testCommand: PYTEST });
    assert.equal(g.green, true, 'all 3 pass => GREEN');
    assert.equal(g.vacuous_reason, null);
    assert.equal(g.tap.tests, 3);
    assert.equal(g.tap.pass, 3);
    assert.equal(g.tap.fail, 0);
  } finally { cleanup(dir); }
});

test('Phase 3d: pytest exit-5 / "no tests ran" => vacuous HALT (never GREEN)', async () => {
  const dir = tmpProjectNoTests();
  try {
    const wave = { n: 1, title: 'no-tests probe', line: 1 };
    const r = await runWave({
      projectDir: dir, testCommand: PYTEST, wave, totalWaves: 1, planPath: 'PLAN.md',
      driver: makeScriptedDriver({ repairs: [] }), reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'HALT', 'no tests collected must HALT, never GO');
    assert.match(r.haltReason, /vacuous-GREEN HALT/);
    assert.match(r.haltReason, /no real tests/);
    assert.equal(r.gate.green, false);
    assert.equal(r.gate.exit_code, 5, 'pytest exits 5 when 0 tests are collected');
  } finally { cleanup(dir); }
});

test('Phase 3d: a Python source changed but imported by NO test => checkVacuousGreen HALT', () => {
  const dir = freshCopy();
  const foremanDir = path.join(dir, '.foreman');
  try {
    // calc.py IS imported by test_calc.py -> reachable -> not vacuous
    assert.equal(_internals.checkVacuousGreen(dir, foremanDir, ['calc.py']), null,
      'changed source reachable from a test => passes the guard');
    // an orphan module no test reaches -> vacuous HALT reason
    fs.writeFileSync(path.join(dir, 'orphan.py'), 'X = 1\n');
    const reason = _internals.checkVacuousGreen(dir, foremanDir, ['orphan.py']);
    assert.match(reason || '', /did not exercise any changed source file/);
  } finally { cleanup(dir); }
});

test('Phase 3d: reachability follows Python imports (absolute + relative)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-pyreach-'));
  try {
    // package layout: pkg/__init__.py, pkg/core.py, helper.py at root, and a
    // test that imports both an absolute module and a relative one.
    fs.mkdirSync(path.join(dir, 'pkg'));
    fs.writeFileSync(path.join(dir, 'pkg', '__init__.py'), '');
    fs.writeFileSync(path.join(dir, 'pkg', 'core.py'), 'def f():\n    return 1\n');
    fs.writeFileSync(path.join(dir, 'helper.py'), 'def g():\n    return 2\n');
    fs.writeFileSync(path.join(dir, 'unreached.py'), 'def z():\n    return 3\n');
    fs.writeFileSync(path.join(dir, 'test_thing.py'),
      'from helper import g\nfrom pkg.core import f\n\n' +
      'def test_g():\n    assert g() == 2\n\ndef test_f():\n    assert f() == 1\n');
    const reach = _internals.reachableFromTests(dir, path.join(dir, '.foreman'));
    assert.ok(reach.has('helper.py'), 'absolute `from helper import g` resolved');
    assert.ok(reach.has('pkg/core.py'), 'dotted `from pkg.core import f` resolved');
    assert.ok(!reach.has('unreached.py'), 'an unimported module is NOT reachable');
  } finally { cleanup(dir); }
});

test('Phase 3d: a forged echo-only pytest summary line (no real per-test event) is REFUSED', async () => {
  const dir = tmpProjectNoTests();
  try {
    const wave = { n: 1, title: 'forge probe', line: 1 };
    const r = await runWave({
      projectDir: dir, testCommand: 'cmd /c "echo 1 passed in 0.01s& exit 0"',
      wave, totalWaves: 1, planPath: 'PLAN.md',
      driver: makeScriptedDriver({ repairs: [] }), reviewerCount: 2, fixIterCap: 4,
    });
    assert.equal(r.status, 'HALT', 'an echoed summary must never manufacture GO');
    assert.match(r.haltReason, /vacuous-GREEN HALT/);
    assert.match(r.haltReason, /no real per-test events/);
    assert.equal(r.gate.green, false);
    assert.equal(r.gate.exit_code, 0, 'exit 0 — proving the forged-echo path, not a RED gate');
  } finally { cleanup(dir); }
});

test('Phase 3d unit — countTestEvents on real mixed pytest output: no double-count of summary lines', () => {
  // A captured real `python -m pytest -v` mixed stream: 2 PASSED, 1 FAILED, 1
  // ERROR, plus SKIPPED/XFAIL/XPASS, AND the trailing summary-section lines
  // (`FAILED path::name`, `ERROR path`). Only the per-test events must be counted.
  const out = [
    'test_a.py::test_pass_one PASSED                                          [ 14%]',
    'test_a.py::test_pass_two PASSED                                          [ 28%]',
    'test_a.py::test_fail_one FAILED                                          [ 42%]',
    'test_a.py::test_skipped SKIPPED (demo)                                   [ 57%]',
    'test_a.py::test_xfailed XFAIL (known)                                    [ 71%]',
    'test_a.py::test_xpassed XPASS (surprise)                                 [ 85%]',
    'test_a.py::test_error_one ERROR                                          [100%]',
    '=========================== short test summary info ===========================',
    'FAILED test_a.py::test_fail_one - assert 2 == 3',
    'ERROR test_a.py::test_error_one',
    '==== 1 failed, 2 passed, 1 skipped, 1 xfailed, 1 xpassed, 1 error in 0.08s ====',
  ].join('\n');
  const ev = _internals.countTestEvents(out);
  assert.equal(ev.pass, 2, 'only the two PASSED events count as passes (XPASS/SKIPPED/XFAIL excluded)');
  assert.equal(ev.fail, 2, 'FAILED + ERROR per-test events; the summary-section lines are NOT double-counted');
  // and the derived tap from parsePytestCount agrees with the summary banner
  assert.equal(_internals.parsePytestCount(out, 'pass'), 2);
  assert.equal(_internals.parsePytestCount(out, 'fail'), 2, 'failed(1) + error(1)');
  assert.equal(_internals.parsePytestCount(out, 'tests'), 4, 'passed(2)+failed(1)+error(1)');
});

test('Phase 3d unit — looksLikePytest detects pytest output but NOT node TAP/spec output', () => {
  assert.equal(_internals.looksLikePytest('test_a.py::test_x PASSED [100%]'), true);
  assert.equal(_internals.looksLikePytest('==== 2 passed in 0.01s ===='), true);
  assert.equal(_internals.looksLikePytest('no tests ran in 0.00s'), true);
  // node TAP / spec output must NOT be misclassified (keeps the JS path intact)
  assert.equal(_internals.looksLikePytest('# pass 3\n# fail 0\nok 1 - add'), false);
  assert.equal(_internals.looksLikePytest('ℹ tests 3\nℹ pass 3\n✔ add'), false);
});

// --- T3 (2026-07-11): trust the parsed summary; normalize pytest gates to -v ---
// Live misroute (Anchor-zombie 2026-06-28): a genuine RED under `pytest -q`
// (74 tests, 40 pass, 34 fail, exit 1) emitted NO per-test events, so the
// "nothing ran" heuristic HALTed it as vacuous with a wrong recommendation
// instead of routing it to the fix loop.

test('T3 REGRESSION: a genuine pytest RED with a summary but NO per-test events (-q shape) is RED, not vacuous', () => {
  const dir = tmpProjectNoTests();
  try {
    // Synthesize the -q output shape: a real summary banner, zero per-test events, exit 1.
    const g = runGate({
      projectDir: dir, foremanDir: path.join(dir, '.foreman'), wave: { n: 1 }, iteration: 0,
      testCommand: 'cmd /c "echo ==== 34 failed, 40 passed in 2.53s ====& exit 1"',
    });
    assert.equal(g.green, false, 'a RED is still RED');
    assert.equal(g.vacuous_reason, null,
      'the parsed summary (40 passed/34 failed) proves tests RAN — never "nothing ran"');
    assert.equal(g.tap.pass, 40);
    assert.equal(g.tap.fail, 34);
    assert.equal(g.exit_code, 1);
  } finally { cleanup(dir); }
});

test('T3: pytest output with NO summary and NO events (true nothing-ran) is still vacuous', () => {
  const dir = tmpProjectNoTests();
  try {
    const g = runGate({
      projectDir: dir, foremanDir: path.join(dir, '.foreman'), wave: { n: 1 }, iteration: 0,
      testCommand: 'cmd /c "echo ==== no tests ran in 0.01s ====& exit 5"',
    });
    assert.equal(g.green, false);
    assert.match(g.vacuous_reason || '', /no real tests/,
      'a genuinely empty run keeps the Phase 3d vacuous HALT');
  } finally { cleanup(dir); }
});

test('T3 unit — normalizePytestGate: bare pytest gains -v; -q HALTs at contract time; -v and non-pytest untouched', () => {
  // bare pytest -> -v inserted (the manifest-discovery self-sabotage fix)
  assert.equal(normalizePytestGate('pytest', 'plan declaration').command, 'pytest -v');
  assert.equal(normalizePytestGate('python -m pytest', 'plan').command, 'python -m pytest -v');
  assert.equal(normalizePytestGate('pytest tests/unit', 'plan').command, 'pytest -v tests/unit',
    '-v inserted after the pytest token, args preserved');
  assert.equal(normalizePytestGate('pip install -e . && pytest tests/', 'plan').command,
    'pip install -e . && pytest -v tests/', 'chained commands: -v lands on pytest, not the chain tail');
  // already verbose -> untouched
  assert.equal(normalizePytestGate('python -m pytest -v', 'plan').command, 'python -m pytest -v');
  assert.equal(normalizePytestGate('pytest -vv tests/', 'plan').command, 'pytest -vv tests/');
  // -q/--quiet -> HALT with the exact edit, BEFORE any execute call is spent
  assert.throws(() => normalizePytestGate('pytest -q', 'plan declaration'), (e) => e instanceof HaltError);
  assert.throws(() => normalizePytestGate('python -m pytest --quiet tests/', 'plan'), (e) => e instanceof HaltError);
  // non-pytest commands pass through byte-identical
  assert.equal(normalizePytestGate('node --test', 'plan').command, 'node --test');
  assert.equal(normalizePytestGate('npm test', 'plan').command, 'npm test');
});

test('T3: manifest-discovered pytest gate is born with -v (never a gate the engine cannot pass)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-pydisc-'));
  try {
    fs.writeFileSync(path.join(dir, 'pyproject.toml'), '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n');
    const r = discoverTestCommand('# Plan with no test-command line\n', dir);
    assert.equal(r.command, 'pytest -v');
    // and a plan-declared -q is refused at discovery (contract) time
    assert.throws(() => discoverTestCommand('test-command: `pytest -q`\n', dir), (e) => e instanceof HaltError);
  } finally { cleanup(dir); }
});
