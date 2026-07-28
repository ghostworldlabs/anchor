// calc.test.mjs — the canonical fixture's test suite (the ground-truth gate).
// Run with: node --test   (declared in the plan and package.json).
import test from 'node:test';
import assert from 'node:assert/strict';
import { add, subtract, multiply } from '../src/calc.js';

test('add: 2 + 3 === 5', () => {
  assert.equal(add(2, 3), 5);
});

test('multiply: 4 * 5 === 20', () => {
  assert.equal(multiply(4, 5), 20);
});

// This is the test the planted bug breaks. It is RED in the shipped fixture and
// turns GREEN once `subtract` is fixed to `a - b`.
test('subtract: 7 - 3 === 4', () => {
  assert.equal(subtract(7, 3), 4);
});
