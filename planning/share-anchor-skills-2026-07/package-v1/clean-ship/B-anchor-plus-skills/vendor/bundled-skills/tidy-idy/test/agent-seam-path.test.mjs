// agent-seam-path.test.mjs — Windows drive paths must become file:// URLs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { driverImportSpec } from '../engine/agent-seam.mjs';

test('Windows absolute path becomes file:// URL (not c: scheme)', () => {
  const spec = driverImportSpec('<path>');
  assert.match(spec, /^file:\/\//i);
  assert.match(spec, /gemini-cli\.mjs$/);
  assert.doesNotMatch(spec, /^c:/i);
});

test('file: URL passes through', () => {
  const u = 'fil<path>';
  assert.equal(driverImportSpec(u), u);
});
