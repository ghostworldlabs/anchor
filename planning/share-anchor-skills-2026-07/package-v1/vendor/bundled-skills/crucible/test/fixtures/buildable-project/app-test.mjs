// app-test.mjs — the buildable-project fixture's own test (run with `node --test app-test.mjs`).
// Named WITHOUT a `.test.mjs` suffix so Crucible's own `test/index.mjs` discovery
// (which globs top-level `test/*.test.mjs`) never imports this nested fixture file.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { sum, product } from './src/calc.mjs';

test('sum adds a list of numbers', () => {
  assert.equal(sum([1, 2, 3]), 6);
  assert.equal(sum([]), 0);
});

test('product multiplies two numbers', () => {
  assert.equal(product(3, 4), 12);
});
