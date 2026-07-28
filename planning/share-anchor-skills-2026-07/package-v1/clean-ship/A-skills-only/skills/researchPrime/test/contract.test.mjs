// test/contract.test.mjs — Wave 1 import GO/NO-GO gate.
//
// Exercises the REAL source module bin/contract.mjs (IMPLEMENTATION-PLAN Wave 1
// done-when (a),(b)): smoke-imports the trio surface from researchPrime's directory and
// asserts every crossed symbol resolves. GREEN = GO (build on the trio directly).
// If any crossed symbol is dropped/renamed upstream this goes RED = NO-GO → Phase 0.5
// (owned trio-core extraction), NOT a fork.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  TRIO_MODULES,
  CROSSED_SYMBOLS,
  importTrioSurface,
  verifyContractSurface,
  runImportSpike,
} from '../bin/contract.mjs';

test('smoke import: all five trio modules load from researchPrime/ and expose a namespace object', async () => {
  const surface = await importTrioSurface();
  for (const key of Object.keys(TRIO_MODULES)) {
    assert.ok(surface[key], `module did not import: ${key}`);
    assert.equal(typeof surface[key], 'object', `namespace not an object: ${key}`);
  }
});

test('GO/NO-GO: every crossed symbol resolves with the expected kind', async () => {
  const surface = await importTrioSurface();
  const { ok, missing } = verifyContractSurface(surface);
  assert.deepEqual(missing, [], `NO-GO — missing/renamed crossed symbols: ${JSON.stringify(missing)}`);
  assert.ok(ok, 'contract surface verified');
});

test('runImportSpike() reports GO with the full crossed-symbol count', async () => {
  const verdict = await runImportSpike();
  assert.equal(verdict.go, true, `import spike NO-GO: ${JSON.stringify(verdict.missing)}`);
  assert.equal(verdict.modules.length, 5);
  const expected = Object.values(CROSSED_SYMBOLS).reduce((n, s) => n + s.length, 0);
  assert.equal(verdict.crossedCount, expected);
  assert.ok(verdict.crossedCount > 0, 'the crossed-symbol list is non-empty (recorded)');
});

test('NO-GO detection works: a fabricated missing symbol is reported (the gate can fail)', () => {
  // A contract gate that can only ever pass proves nothing. Inject a surface missing a
  // crossed symbol and assert verifyContractSurface flags it.
  const broken = {};
  for (const [mod, symbols] of Object.entries(CROSSED_SYMBOLS)) {
    broken[mod] = {};
    for (const { name } of symbols) broken[mod][name] = () => {};
  }
  // Drop one known crossed symbol.
  delete broken['judge'].makeJudge;
  const { ok, missing } = verifyContractSurface(broken);
  assert.equal(ok, false);
  assert.ok(missing.some((m) => m.module === 'judge' && m.name === 'makeJudge'));
});
