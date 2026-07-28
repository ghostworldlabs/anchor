// src/calc.mjs — the buildable-project fixture's source under test.
// A trivially-real module so the brownfield fixture genuinely builds + tests GREEN.

/** Sum a list of numbers. */
export function sum(nums = []) {
  return nums.reduce((acc, n) => acc + n, 0);
}

/** Multiply two numbers. */
export function product(a, b) {
  return a * b;
}
