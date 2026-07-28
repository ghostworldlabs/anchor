// test/trio-green.test.mjs — makes the cross-repo claim an ORCHESTRATOR-RUNNABLE assertion, not
// prose (IMPLEMENTATION-PLAN Wave 2). Wave 2 re-homes the shared trio-core module and re-points
// specifiers with NO behavioral change to Crucible/Foreman; the guard for "no behavioral change"
// is that BOTH engines' own suites stay GREEN. This test shells out to run Crucible's AND
// Foreman's suites and performs a Foreman-side smoke import, asserting all GREEN.
//
// These are separate `node` processes (a nested test runner is fine) so a regression in either
// engine surfaces HERE, in researchPrime's gate, exactly as the cross-repo invariant requires.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { TRIO_ROOT } from '../bin/contract.mjs';

const CRUCIBLE_ROOT = fileURLToPath(new URL('crucible/', TRIO_ROOT));
const FOREMAN_ROOT = fileURLToPath(new URL('foreman/', TRIO_ROOT));
const FOREMAN_LIB_URL = new URL('foreman/bin/foreman-lib.mjs', TRIO_ROOT).href;

const SHELL_TIMEOUT_MS = 120_000;

// This test file is itself run under `node --test`, which sets NODE_TEST_CONTEXT in the
// environment. A child `node --test` that inherits it detects "recursive run" and SKIPS running
// the files (0 tests). Strip it so each shelled-out suite runs as a fresh, top-level runner.
const CLEAN_ENV = { ...process.env };
delete CLEAN_ENV.NODE_TEST_CONTEXT;

/** Pull the TAP summary counters out of a `node --test` run's output. */
function tapCounters(output) {
  const grab = (label) => {
    const m = output.match(new RegExp(`# ${label} (\\d+)`));
    return m ? Number(m[1]) : null;
  };
  return { tests: grab('tests'), pass: grab('pass'), fail: grab('fail') };
}

/** Run a `node --test` suite and assert it is GREEN and non-vacuous. */
function assertSuiteGreen(label, args, cwd) {
  // Force the TAP reporter so the summary counters are deterministic to parse regardless of the
  // host Node's default reporter (Node 26's default is the spec reporter even when piped).
  const r = spawnSync(process.execPath, ['--test', '--test-reporter=tap', ...args], {
    cwd,
    encoding: 'utf8',
    timeout: SHELL_TIMEOUT_MS,
    env: CLEAN_ENV,
  });
  const out = `${r.stdout || ''}\n${r.stderr || ''}`;
  assert.equal(
    r.status,
    0,
    `${label} suite is not GREEN (exit ${r.status}, signal ${r.signal}). Tail:\n${out.slice(-1500)}`,
  );
  const { tests, fail } = tapCounters(out);
  assert.ok(tests !== null && tests > 0, `${label} suite ran 0 tests (vacuous GREEN). Tail:\n${out.slice(-800)}`);
  assert.equal(fail, 0, `${label} suite reported ${fail} failing tests`);
  return { tests };
}

test("Crucible's own suite is GREEN (Wave 2 made no behavioral change to it)", () => {
  // Crucible has a package.json + test/index.mjs entry, so `node --test test/` is its native gate.
  const { tests } = assertSuiteGreen('Crucible', ['test/'], CRUCIBLE_ROOT);
  assert.ok(tests >= 1);
});

test("Foreman's own suite is GREEN (Wave 2 made no behavioral change to it)", () => {
  // Foreman has no package.json, so `node --test test/` cannot resolve the dir as a module —
  // enumerate its *.test.mjs files and run them by absolute path (its native invocation).
  const files = readdirSync(path.join(FOREMAN_ROOT, 'test'))
    .filter((f) => f.endsWith('.test.mjs'))
    .map((f) => path.join(FOREMAN_ROOT, 'test', f));
  assert.ok(files.length > 0, 'no Foreman test files found — wrong TRIO_ROOT?');
  const { tests } = assertSuiteGreen('Foreman', files, FOREMAN_ROOT);
  assert.ok(tests >= 1);
});

test('Foreman-side smoke import: foreman-lib loads from the Foreman tree and exposes its primitives', () => {
  // A genuinely Foreman-SIDE import: a fresh process whose cwd is the Foreman root dynamically
  // imports foreman-lib and verifies the HALT primitive is a callable — proving the module loads
  // independently of researchPrime, not just transitively through our own contract import.
  const probe =
    `import('${FOREMAN_LIB_URL}')` +
    `.then(m => process.exit(typeof m.HaltError === 'function' && typeof m.makeBudget === 'function' ? 0 : 3))` +
    `.catch(e => { console.error(e); process.exit(4); })`;
  const r = spawnSync(process.execPath, ['-e', probe], {
    cwd: FOREMAN_ROOT,
    encoding: 'utf8',
    timeout: SHELL_TIMEOUT_MS,
    env: CLEAN_ENV,
  });
  assert.equal(
    r.status,
    0,
    `Foreman-side smoke import failed (exit ${r.status}): ${(r.stderr || '').slice(-800)}`,
  );
});
