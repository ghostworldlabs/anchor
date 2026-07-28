// test/phase1-seam.test.mjs — Wave 4 gate: the Phase-1 SEAM emits ONE persisted receipt that
// carries the governor tier (from the stakes vector) AND the Oranges foresight receipt
// (IMPLEMENTATION-PLAN Wave 4 done-when: "Phase-1 emits a persisted stakes vector → governor tier,
// and an Oranges receipt"). The "raw vector persisted (no schema break)" clause is asserted across
// a real on-disk write/read round-trip — not just an in-memory object.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { loadFixture } from '../bin/baseline.mjs';
import { tierAtLeast } from '../bin/stakes.mjs';
import { buildResearchPlan } from '../bin/oranges.mjs';
import { runPhase1, persistPhase1, loadPhase1, PHASE1_SCHEMA_VERSION } from '../bin/phase1.mjs';

function tmpFile(name) {
  return path.join(os.tmpdir(), `rp-phase1-${process.pid}-${name}.json`);
}

// Build one realistic Phase-1 item straight from the committed fixture: a declared-low-but-
// irreversible recommendation (I6 probe) plus a research plan carrying a planted path-defect (crit-3).
function fixtureItem() {
  const { defects } = loadFixture();
  const irr = defects.find((d) => d.class === 'declared-low-but-irreversible');
  const paths = defects.filter((d) => d.class === 'path-defect');
  return {
    stakes: { id: irr.id, declared_stakes: irr.declared_stakes, reversibility: irr.reversibility },
    plan: buildResearchPlan(paths),
  };
}

test('runPhase1 emits the governor tier (from the stakes vector) and the Oranges receipt together', () => {
  const receipt = runPhase1(fixtureItem());
  assert.equal(receipt.schema_version, PHASE1_SCHEMA_VERSION);
  // The tier is the projection of the stakes vector — and for the under-call probe it is ≥ medium (I6).
  assert.equal(receipt.tier, receipt.stakes.tier);
  assert.ok(tierAtLeast(receipt.tier, 'medium'), `irreversible item must drive tier ≥ medium, got ${receipt.tier}`);
  // The foresight receipt re-aimed the plan (crit-3) — same module asserted in oranges.test.mjs.
  assert.ok(receipt.foresight.value_added);
  assert.equal(receipt.foresight.crit3_satisfied, true);
});

test('the Phase-1 receipt PERSISTS and round-trips with the RAW stakes vector intact (no schema break)', () => {
  const file = tmpFile('roundtrip');
  try {
    const receipt = runPhase1(fixtureItem());
    persistPhase1(receipt, file);
    assert.ok(fs.existsSync(file), 'persistPhase1 must write the receipt to disk');

    const loaded = loadPhase1(file);
    // Full fidelity: the persisted receipt equals what was emitted.
    assert.deepEqual(loaded, receipt, 'the persisted receipt must round-trip byte-faithfully');
    // The RAW declared stakes vector survives persistence verbatim — a consumer that only knows the
    // declared axes still reads them after the round-trip (additive; no schema break).
    assert.equal(loaded.stakes.raw.declared_stakes, receipt.stakes.raw.declared_stakes);
    assert.equal(loaded.stakes.raw.reversibility, receipt.stakes.raw.reversibility);
    assert.deepEqual(loaded.stakes.raw, receipt.stakes.raw);
  } finally {
    fs.rmSync(file, { force: true });
  }
});

test('persistPhase1 publishes atomically — no leftover temp file after a successful write', () => {
  const file = tmpFile('atomic');
  try {
    persistPhase1(runPhase1(fixtureItem()), file);
    assert.ok(!fs.existsSync(`${file}.tmp`), 'the temp file must be renamed away (atomic publish)');
  } finally {
    fs.rmSync(file, { force: true });
  }
});

test('runPhase1 defaults missing parts safely (empty stakes ⇒ low; empty plan ⇒ no-op foresight)', () => {
  const receipt = runPhase1({});
  assert.equal(receipt.tier, 'low');
  assert.equal(receipt.foresight.value_added, false);
  assert.equal(receipt.foresight.crit3_satisfied, false);
  assert.throws(() => runPhase1(null), TypeError);
});
