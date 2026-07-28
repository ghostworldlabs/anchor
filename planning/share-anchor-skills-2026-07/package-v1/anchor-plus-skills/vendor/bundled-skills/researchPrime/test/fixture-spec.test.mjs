// test/fixture-spec.test.mjs — Wave 1 fixture-spec gate (done-when (c)).
//
// The fixture spec must be AUTHORED in Wave 1 and must include the two mandatory hard
// cases the design hinges on: a correlated-blind-spot (CBS) class (I2 gating recall) and a
// declared-low-but-irreversible case (I6 under-call guard), plus the planted-path-defect
// probe for crit-3. This test asserts the spec exists and names each, so (c) is
// machine-checked rather than vacuous. (Sizing/capture is Wave 3, not asserted here.)

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const SPEC = new URL('../FIXTURE-SPEC.md', import.meta.url);

function specText() {
  return fs.readFileSync(SPEC, 'utf8');
}

test('the fixture spec file is authored', () => {
  assert.ok(fs.existsSync(SPEC), 'FIXTURE-SPEC.md must exist (Wave 1 done-when (c))');
  assert.ok(specText().trim().length > 0, 'FIXTURE-SPEC.md must not be empty');
});

test('spec includes the mandatory correlated-blind-spot (CBS) class (I2)', () => {
  const t = specText().toLowerCase();
  assert.ok(t.includes('correlated-blind-spot'), 'CBS class must be specified');
  assert.ok(t.includes('c_min'), 'CBS recall must be gated by C_min (I2)');
  assert.ok(t.includes('lineage'), 'CBS must explain the same-lineage co-miss structure');
});

test('spec includes the mandatory declared-low-but-irreversible case (I6)', () => {
  const t = specText().toLowerCase();
  assert.ok(t.includes('declared-low-but-irreversible'), 'under-call guard case must be specified');
  assert.ok(t.includes('irreversible'), 'reversibility must be named');
  assert.ok(/tier\s*[>≥]=?\s*medium/.test(t), 'irreversible ⇒ tier ≥ medium must be the answer key');
});

test('spec includes the planted-path-defect probe for crit-3 foresight', () => {
  const t = specText().toLowerCase();
  assert.ok(t.includes('path-defect') || t.includes('path defect'), 'path-defect probe must be specified');
  assert.ok(t.includes('counterfactual cost'), 'crit-3 requires naming the counterfactual cost');
});
