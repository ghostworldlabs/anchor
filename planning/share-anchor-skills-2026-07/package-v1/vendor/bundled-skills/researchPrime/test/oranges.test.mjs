// test/oranges.test.mjs — Wave 4 gate: the Oranges FORESIGHT receipt (crit-3 re-aim).
//
// Exercises the REAL Wave-4 source (bin/oranges.mjs) against the COMMITTED fixture's planted
// path-defects, so the crit-3 equality assertion is made on the same ground-truth branch + cost the
// fixture spec plants — no vacuous GREEN. IMPLEMENTATION-PLAN Wave 4: "Given a fixture with a
// planted path defect, Then foresight drops/reorders that exact branch (equality assertion, crit-3
// re-aim); a no-op pass is stamped 'no foresight value added' and crit-3 reported NOT satisfied."

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadFixture } from '../bin/baseline.mjs';
import {
  FORESIGHT_GATE,
  NO_VALUE_STAMP,
  VALUE_STAMP,
  buildResearchPlan,
  runForesight,
} from '../bin/oranges.mjs';

function pathDefects() {
  return loadFixture().defects.filter((d) => d.class === 'path-defect');
}

// ── crit-3: foresight drops the EXACT planted branch + names its counterfactual cost ──────────────
test('foresight drops exactly the planted path-defect branches, by economics not by flag', () => {
  const defects = pathDefects();
  assert.ok(defects.length >= 1, 'the fixture must plant at least one path-defect (crit-3 probe)');

  const plan = buildResearchPlan(defects);
  const receipt = runForesight(plan);

  assert.equal(receipt.gate, FORESIGHT_GATE);

  // Equality assertion (crit-3 re-aim): the set of dropped branches equals the planted wrong branches.
  const droppedBranches = receipt.dropped.map((d) => d.branch).sort();
  const plantedBranches = defects.map((d) => d.wrong_branch).sort();
  assert.deepEqual(droppedBranches, plantedBranches, 'foresight must drop exactly the planted wrong branches');

  // …and each dropped branch carries the EXACT counterfactual cost from the answer key.
  for (const d of defects) {
    const entry = receipt.dropped.find((x) => x.branch === d.wrong_branch);
    assert.ok(entry, `branch ${d.wrong_branch} must appear in the receipt`);
    assert.equal(
      entry.counterfactual_cost,
      d.counterfactual_cost,
      `${d.wrong_branch}: receipt must name the planted counterfactual cost exactly`,
    );
  }
});

test('a plan containing a planted path-defect adds value and SATISFIES crit-3', () => {
  const receipt = runForesight(buildResearchPlan(pathDefects()));
  assert.ok(receipt.value_added, 'dropping a wasteful branch is foresight value');
  assert.equal(receipt.stamp, VALUE_STAMP);
  assert.equal(receipt.crit3_satisfied, true);
});

// ── The sound branches survive and are kept in optimal order ──────────────────────────────────────
test('sound branches are kept (not dropped) and ordered highest-net-value first', () => {
  const receipt = runForesight(buildResearchPlan(pathDefects(), 3));
  assert.deepEqual(receipt.kept, ['G1', 'G2', 'G3'], 'positive-net branches survive in optimal order');
  for (const k of receipt.kept) {
    assert.ok(!receipt.dropped.some((d) => d.branch === k), `${k} must not be dropped`);
  }
});

// ── The honesty floor: a no-op pass is stamped, and crit-3 is reported NOT satisfied ──────────────
test('a no-op pass (no wasteful or mis-ordered branch) is stamped "no foresight value added"', () => {
  // A plan of only sound branches already in optimal (descending net value) order.
  const plan = { branches: [
    { id: 'G1', est_value: 10, est_cost: 1 },
    { id: 'G2', est_value: 9, est_cost: 1 },
    { id: 'G3', est_value: 8, est_cost: 1 },
  ] };
  const receipt = runForesight(plan);
  assert.deepEqual(receipt.dropped, []);
  assert.deepEqual(receipt.reordered, []);
  assert.equal(receipt.value_added, false);
  assert.equal(receipt.stamp, NO_VALUE_STAMP);
  assert.equal(receipt.crit3_satisfied, false, 'a value-free pass must NOT report crit-3 satisfied');
});

test('an empty plan is a no-op pass, not a crash or a silent success', () => {
  const receipt = runForesight({ branches: [] });
  assert.equal(receipt.stamp, NO_VALUE_STAMP);
  assert.equal(receipt.crit3_satisfied, false);
});

// ── Reorder branch: a mis-ordered sound plan is re-aimed (drop OR reorder + cost) ─────────────────
test('a mis-ordered sound plan is reordered with a counterfactual cost and satisfies crit-3', () => {
  // Lower-value branch placed first ⇒ foresight reorders, dropping nothing.
  const plan = { branches: [
    { id: 'G1', est_value: 5, est_cost: 1 }, // net 4 — placed first but worth less
    { id: 'G2', est_value: 10, est_cost: 1 }, // net 9 — should run first
  ] };
  const receipt = runForesight(plan);
  assert.deepEqual(receipt.dropped, [], 'nothing wasteful to drop');
  assert.ok(receipt.reordered.length >= 1, 'the mis-ordered branch must be reordered');
  assert.equal(receipt.kept[0], 'G2', 'the higher-value branch runs first after re-aim');
  for (const r of receipt.reordered) {
    assert.ok(typeof r.counterfactual_cost === 'string' && r.counterfactual_cost.length > 0, 'a reorder must name its cost');
  }
  assert.equal(receipt.value_added, true);
  assert.equal(receipt.crit3_satisfied, true);
});

// ── crit-3 cannot be gamed: a drop with no quantified cost does not pass ──────────────────────────
test('a drop with no counterfactual cost does NOT satisfy crit-3 (no hollow claim)', () => {
  const plan = { branches: [
    { id: 'B9', est_value: 0, est_cost: 1 }, // wasteful, but NO counterfactual_cost field
    { id: 'G1', est_value: 10, est_cost: 1 },
  ] };
  const receipt = runForesight(plan);
  assert.ok(receipt.dropped.some((d) => d.branch === 'B9'), 'the wasteful branch is still dropped');
  assert.equal(receipt.value_added, true, 'a drop is an action');
  assert.equal(receipt.crit3_satisfied, false, 'but with no quantified cost it cannot satisfy crit-3');
});
