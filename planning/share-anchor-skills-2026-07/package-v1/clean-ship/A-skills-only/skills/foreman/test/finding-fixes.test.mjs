// finding-fixes.test.mjs — regressions for the 2026-06-04 Skill-Foundry-run findings.
//   Finding A: inventory double-counted Python skips, and the test-weakening guard
//   HALTed on a static skip-marker rise even when NO test was actually skipped.
// (Finding B's regression lives in git-hygiene.test.mjs, which has the git harness.)

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { _internals } from '../bin/wave-engine.mjs';

const { inventory, checkTestWeakening } = _internals;

function tmp() { return fs.mkdtempSync(path.join(os.tmpdir(), 'fmn-find-')); }
function rmrf(d) { try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* ignore */ } }

test('Finding A1: a single pytest.skip( counts ONCE, not twice (no .skip/pytest.skip double-count)', () => {
  const d = tmp();
  try {
    fs.mkdirSync(path.join(d, 'tests'), { recursive: true });
    fs.writeFileSync(path.join(d, 'tests', 'test_x.py'),
      'import shutil, pytest\n' +
      'def test_a():\n' +
      '    if not shutil.which("node"):\n' +
      '        pytest.skip("no node on this host")\n' +
      '    assert True\n');
    const inv = inventory(d, path.join(d, '.foreman'));
    assert.equal(inv.skips, 1, 'one pytest.skip( must count as exactly 1 (the bug counted it as 2)');
    assert.equal(inv.tests, 1, 'one def test_ counts as 1');
  } finally { rmrf(d); }
});

test('Finding A1: JS test.skip( still counts as 1', () => {
  const d = tmp();
  try {
    fs.mkdirSync(path.join(d, 'test'), { recursive: true });
    fs.writeFileSync(path.join(d, 'test', 'a.test.mjs'),
      "import {test} from 'node:test';\ntest.skip('x', () => {});\n");
    const inv = inventory(d, path.join(d, '.foreman'));
    assert.equal(inv.skips, 1, 'one JS test.skip counts as 1');
  } finally { rmrf(d); }
});

test('Finding A2: a never-firing env-guard skip (0 actually skipped) does NOT HALT', () => {
  const before = { files: 1, tests: 5, asserts: 5, skips: 1 };
  const after = { files: 1, tests: 6, asserts: 6, skips: 2 }; // +1 dormant env-guard skip, +1 test
  assert.equal(checkTestWeakening(before, after, null, 0), null,
    'a skip-marker rise with 0 tests actually skipped is not weakening');
});

test('Finding A2: a real skip that hides a test (>=1 actually skipped) STILL HALTs', () => {
  const before = { files: 1, tests: 5, asserts: 5, skips: 0 };
  const after = { files: 1, tests: 5, asserts: 5, skips: 1 };
  const r = checkTestWeakening(before, after, null, 1);
  assert.ok(r && /skip/.test(r), 'a marker rise WITH a real skip must still HALT');
});

test('Finding A2: a genuine test-count DROP still HALTs (unchanged behavior)', () => {
  const r = checkTestWeakening(
    { files: 1, tests: 6, asserts: 6, skips: 0 },
    { files: 1, tests: 5, asserts: 6, skips: 0 }, null, 0);
  assert.ok(r && /test count dropped/.test(r));
});
