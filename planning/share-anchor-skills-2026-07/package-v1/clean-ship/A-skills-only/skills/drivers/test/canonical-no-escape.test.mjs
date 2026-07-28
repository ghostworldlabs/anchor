// drivers/test/canonical-no-escape.test.mjs — Phase 1.1 done-when (a)+(b):
// canonical diff-check GREEN (no production import escapes the trio tree) + injected-
// divergence RED (the detector flags the BLOCKER-1 archive import). Registered in the
// Phase-0.4 gate-inventory manifest so the run-live.mjs:129 regression cannot reopen.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { isEscapingSpecifier, extractSpecifiers, scanTreeForEscapes } from '../canonical-scan.mjs';

// drivers/test/ -> trio root
const TRIO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

test('no-escape GREEN: zero production imports resolve outside the canonical trio tree', () => {
  const escapes = scanTreeForEscapes(TRIO_ROOT);
  assert.deepEqual(escapes, [], `escaping imports found: ${JSON.stringify(escapes, null, 2)}`);
});

test('injected-divergence RED: the detector flags the archive import + absolute paths', () => {
  assert.equal(isEscapingSpecifier('fil<path>'), true);
  assert.equal(isEscapingSpecifier('<path>'), true);
  assert.equal(isEscapingSpecifier('<path>'), true);
  assert.equal(isEscapingSpecifier('/usr/lib/x.mjs'), true);
  // in-tree specifiers are NOT escapes
  assert.equal(isEscapingSpecifier('./project-engine.mjs'), false);
  assert.equal(isEscapingSpecifier('../../drivers/index.mjs'), false);
  assert.equal(isEscapingSpecifier('node:fs'), false);
});

test('injected-divergence RED: extractSpecifiers detects the escape inside an import()', () => {
  const sample = "const { runProject } = await import('fil<path>');";
  const specs = extractSpecifiers(sample);
  assert.ok(specs.includes('fil<path>'));
  assert.equal(specs.filter(isEscapingSpecifier).length, 1, 'the archive import is detected as an escape');
});
