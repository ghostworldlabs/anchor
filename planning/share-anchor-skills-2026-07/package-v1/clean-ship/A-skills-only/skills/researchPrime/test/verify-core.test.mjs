// test/verify-core.test.mjs — Wave 6 gate: the EVIDENCED VERIFICATION CORE (Phase C-1).
//
// IMPLEMENTATION-PLAN Wave 6 done-when, asserted as concrete `node --test` checks:
//   - G1 CoVe independence, G2 self-consistency (precision-only), G7 invariant — each a test;
//   - recall measured by LOADING the Wave-3 baseline BY HASH, broken out by source gate AND CBS class;
//   - origin counts come from the shared independence-accounting module (Wave 2).
// Plus the two Given/Then locks:
//   - the audit tries to raise a ladder level without a new pointer ⇒ it throws (I4) in BOTH modes;
//   - a G2-only recall gain ⇒ the crit-1 accuracy number does not move (I5 attribution).
//
// Every assertion exercises the real Wave-6 source (bin/verify-core) over the committed on-disk
// fixture + the frozen baseline — no vacuous GREEN.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { loadFixture } from '../bin/baseline.mjs';
import { RECALL_CLASSES } from '../bin/fixture.mjs';
// The G7 audit operates on the engine's OWNED ladder — reuse the Wave-5 `makeLadder` (not a fork).
import { makeLadder } from '../bin/engine.mjs';
import {
  meetsQuorum,
  countIndependentOrigins,
  STATIC_QUORUM_FLOOR,
} from '../bin/trio-core/independence-accounting.mjs';
import {
  ACCURACY_GATES,
  PRECISION_GATES,
  CBS_CLASS,
  MODES,
  CORE_LINEAGE,
  CBS_CEILING_STAMP,
  g1Verify,
  g1Catches,
  g2SelfConsistency,
  runG7Audit,
  attributeRecall,
  measureRecall,
} from '../bin/verify-core.mjs';

// The FROZEN Wave-3 baseline hash this wave PINS (load-by-hash). Committed here so the core cannot be
// silently measured against a regenerated baseline — any drift moves the hash and turns this gate RED
// (the same pin baseline.test.mjs froze in Wave 3).
const EXPECTED_BASELINE_HASH = '67792c6f6f78b4c9f58b2d2c4158921a540465a9400cbbc248e81d3119f4221d';

// ── G1 — CoVe fresh-fetch independence (ACCURACY) ───────────────────────────────────────────────────

test('G1 CoVe catches ordinary defects at ANY severity, misses CBS (I1) and the probes', () => {
  const { defects } = loadFixture();
  const ordinary = defects.filter((d) => d.class === 'ordinary');
  const cbs = defects.filter((d) => d.class === CBS_CLASS);

  // Every ordinary (single-origin) defect is caught — incl. the low-severity ones the single pass
  // missed (that is the accuracy gain). Each catch yields a FRESH fetched pointer (the new bit).
  for (const d of ordinary) {
    const v = g1Verify(d);
    assert.equal(v.caught, true, `${d.id} (ordinary, severity ${d.severity}) must be caught by G1 CoVe`);
    assert.equal(typeof v.pointer, 'string', `${d.id}: a G1 catch must yield a fresh fetched pointer`);
  }
  // I1: a same-lineage fresh fetch can NEVER recover a correlated-blind-spot, and a miss yields no pointer.
  for (const d of cbs) {
    const v = g1Verify(d);
    assert.equal(v.caught, false, `${d.id} (CBS) must NOT be caught by the same-lineage G1 (I1)`);
    assert.equal(v.pointer, null, `${d.id}: a miss must yield no pointer`);
  }
  // Probes are not recall defects.
  for (const d of defects.filter((x) => !RECALL_CLASSES.includes(x.class))) {
    assert.equal(g1Catches(d), false, `${d.id} (probe) is not a recall defect`);
  }
});

test('G1 CoVe produces a real accuracy recall GAIN over the single-pass baseline', () => {
  const res = measureRecall({ baselineHash: EXPECTED_BASELINE_HASH, gates: ['G1'] });
  // Ordinary recall closes to 1.0 (vs the baseline 0.5) and overall crit-1 accuracy beats the
  // baseline overall (0.25) — a measured gain, not an asserted one.
  assert.equal(res.loop.by_class.ordinary.recall, 1);
  assert.ok(
    res.crit1_accuracy_recall > res.baseline_recall.overall,
    `crit-1 accuracy ${res.crit1_accuracy_recall} must beat single-pass overall ${res.baseline_recall.overall}`,
  );
  assert.ok(res.loop.by_class.ordinary.recall > res.baseline_recall.by_class.ordinary);
});

// ── G2 — self-consistency (PRECISION-ONLY, I5) ──────────────────────────────────────────────────────

test('G2 self-consistency confirms a strict-majority finding and suppresses a flaky minority one', () => {
  // 3 samples of the same reviewer: f1 in all 3 (majority), f2 in 1 (minority/flaky), f3 in 2 (majority).
  const out = g2SelfConsistency([['f1', 'f3'], ['f1', 'f2'], ['f1', 'f3']]);
  assert.deepEqual(out.confirmed, ['f1', 'f3']);
  assert.deepEqual(out.suppressed, ['f2']);
});

test('G2 injects NO new external bits: a finding in no sample is neither confirmed nor suppressed', () => {
  const out = g2SelfConsistency([['f1'], ['f1'], ['f1']]);
  assert.equal(out.confirmed.includes('ghost'), false);
  assert.equal(out.suppressed.includes('ghost'), false);
  assert.deepEqual(out.confirmed, ['f1']);
  assert.throws(() => g2SelfConsistency('nope'), TypeError);
  assert.throws(() => g2SelfConsistency([['f1'], 'bad']), TypeError);
});

test('G2 yields NO fresh pointer, so it CANNOT raise the evidence ladder (precision-only, I5)', () => {
  const out = g2SelfConsistency([['f1'], ['f1'], ['f1']]);
  assert.equal(out.pointer, null, 'self-consistency fetches nothing new — the null pointer is the contract');
  // Trying to raise the ladder from G2's (absent) pointer throws — exactly the I5 "cannot raise the ladder".
  const ladder = makeLadder();
  assert.throws(
    () => runG7Audit(ladder, { action: 'raise', pointer: out.pointer }),
    /fresh fetched pointer/,
  );
  assert.equal(ladder.level(), 0, 'a precision-only gate must not have moved the ladder');
});

// ── G7 — invariant / evidence-ladder audit (DOWNGRADE-ONLY, I4; BOTH modes) ─────────────────────────

test('G7 audit raises ONLY on a fresh pointer; a raise without one THROWS in BOTH modes (I4)', () => {
  assert.deepEqual([...MODES], ['engine', 'degraded'], 'I4 is asserted for both run modes');

  for (const mode of MODES) {
    const ladder = makeLadder();
    // A raise without a new pointer THROWS — identically in engine AND degraded (the guard is in the
    // shared ladder primitive; no mode can bypass it).
    assert.throws(() => runG7Audit(ladder, { mode, action: 'raise', pointer: null }), /fresh fetched pointer/);
    assert.throws(() => runG7Audit(ladder, { mode, action: 'raise' }), /fresh fetched pointer/);
    assert.equal(ladder.level(), 0, `${mode}: a refused raise must not move the ladder`);

    // A raise with a FRESH (G1-style) pointer succeeds; re-using it is not new evidence ⇒ throws.
    const ptr = g1Verify({ class: 'ordinary', detectable_by: ['G1'], location: `claims/${mode}.md` }).pointer;
    const raised = runG7Audit(ladder, { mode, action: 'raise', pointer: ptr });
    assert.equal(raised.level, 1);
    assert.equal(raised.raised, true);
    assert.throws(() => runG7Audit(ladder, { mode, action: 'raise', pointer: ptr }), /already used/);

    // A downgrade needs no new pointer (an audit may always lower its claim).
    const lowered = runG7Audit(ladder, { mode, action: 'lower' });
    assert.equal(lowered.level, 0);
    // A bare audit inspects without changing the level.
    assert.equal(runG7Audit(ladder, { mode }).level, 0);
  }

  assert.throws(() => runG7Audit(makeLadder(), { mode: 'bogus', action: 'audit' }), /unknown mode/);
  assert.throws(() => runG7Audit(null, { action: 'audit' }), /requires a ladder/);
});

// ── recall measured by LOADING the Wave-3 baseline BY HASH, broken out by gate AND CBS class ─────────

test('measureRecall LOADS the frozen baseline by hash and rejects a wrong/regenerated one', () => {
  assert.ok(measureRecall({ baselineHash: EXPECTED_BASELINE_HASH }));
  assert.throws(() => measureRecall({ baselineHash: '0'.repeat(64) }), /baseline hash mismatch/);
  assert.throws(() => measureRecall({}), /requires the frozen baselineHash/);
});

test('recall is broken out BY SOURCE GATE and BY CLASS (incl. the CBS class)', () => {
  const res = measureRecall({ baselineHash: EXPECTED_BASELINE_HASH });

  // BY GATE: the accuracy catches are attributed to G1 (24 ordinary). No defect is detectable_by G2.
  assert.equal(res.loop.by_gate.G1, 24);
  assert.equal(res.loop.by_gate.G2, undefined, 'no real planted defect is caught by precision-only G2');

  // BY CLASS: both recall classes present, with exact numbers from the frozen fixture.
  assert.deepEqual(res.loop.by_class.ordinary, { planted: 24, caught: 24, recall: 1 });
  assert.deepEqual(res.loop.by_class[CBS_CLASS], { planted: 24, caught: 0, recall: 0 });
  assert.equal(res.recall_class_planted, 48);
});

test('CBS recall is reported as a MEASURED CEILING (I1), never a closed result', () => {
  const res = measureRecall({ baselineHash: EXPECTED_BASELINE_HASH });
  assert.equal(res.cbs.recall, 0);
  assert.equal(res.cbs.ceiling, true);
  assert.equal(res.cbs.stamp, CBS_CEILING_STAMP);
  assert.match(res.cbs.stamp, /measured ceiling/);
  assert.equal(res.cross_model, false, 'the default same-lineage core has no cross-lineage origin (I3)');
});

test('gap-closure is the accuracy catches among the single-pass misses (crit-1 denominator)', () => {
  const res = measureRecall({ baselineHash: EXPECTED_BASELINE_HASH });
  // The single pass missed 36 (12 low-severity ordinary + 24 CBS). G1 (accuracy) closes the 12
  // ordinary; CBS stays open (Enhanced/G8 closes it in Wave 7). Full ≥G closure is the Wave-11 gate.
  assert.equal(res.gap_closure.single_pass_misses, 36);
  assert.equal(res.gap_closure.closed, 12);
  assert.ok(Math.abs(res.gap_closure.fraction - 12 / 36) < 1e-12);
});

// ── origin counts come from the SHARED module (Wave 2) ──────────────────────────────────────────────

test('independent-origin counts route through the shared module (the sole counter), not a re-impl', () => {
  const res = measureRecall({ baselineHash: EXPECTED_BASELINE_HASH });
  // The reported quorum is byte-for-byte what the shared module returns for the core's one
  // same-lineage reviewer family — proving it is the module's count, not a re-implemented one.
  const fromModule = meetsQuorum([{ lineage: CORE_LINEAGE }], { staticFloor: STATIC_QUORUM_FLOOR });
  assert.deepEqual(res.quorum, fromModule);
  // The default core is ONE origin and does NOT meet the ≥2 quorum on its own (needs Wave-7 reviewers).
  assert.deepEqual(res.quorum, { origins: 1, required: STATIC_QUORUM_FLOOR, met: false });
  // And the shared module's invariant holds: two SAME-lineage reviewers still add only ONE origin (I3).
  assert.equal(countIndependentOrigins([{ lineage: CORE_LINEAGE }, { lineage: CORE_LINEAGE }]), 1);
});

// ── I5 — a G2-only recall gain must NOT move the crit-1 accuracy number ──────────────────────────────

test('I5 attribution: a G2-only recall gain raises the blended recall but NEVER the crit-1 accuracy', () => {
  const planted = 48;
  // Baseline: only G1 (accuracy) catches — 24 ordinary defects.
  const g1Catches24 = Array.from({ length: 24 }, (_v, i) => ({ id: `ord-${i}`, class: 'ordinary', gates: ['G1'] }));
  const a = attributeRecall(g1Catches24, { planted });

  // Now G2 reports an ADDITIONAL recall gain (3 CBS findings caught ONLY by the precision gate G2 —
  // exactly the case I5 guards: even if self-consistency claims a catch, it is precision, not accuracy).
  const g2OnlyGain = [
    { id: 'cbs-x1', class: CBS_CLASS, gates: ['G2'] },
    { id: 'cbs-x2', class: CBS_CLASS, gates: ['G2'] },
    { id: 'cbs-x3', class: CBS_CLASS, gates: ['G2'] },
  ];
  const b = attributeRecall([...g1Catches24, ...g2OnlyGain], { planted });

  // The crit-1 ACCURACY number is IDENTICAL — the G2 gain did not move it (I5).
  assert.equal(b.crit1_accuracy_recall, a.crit1_accuracy_recall);
  assert.equal(b.accuracy_caught, a.accuracy_caught);
  // …while the blended recall DID move, and the gain landed entirely in the precision bucket.
  assert.ok(b.blended_recall > a.blended_recall, 'the G2 gain must show up in the blended recall');
  assert.equal(b.precision_only_caught, 3);
  assert.equal(a.precision_only_caught, 0);
});

test('a catch by BOTH an accuracy and a precision gate counts as accuracy (precision adds nothing)', () => {
  const both = attributeRecall([{ id: 'd1', class: 'ordinary', gates: ['G1', 'G2'] }], { planted: 10 });
  assert.equal(both.accuracy_caught, 1);
  assert.equal(both.precision_only_caught, 0);
  assert.equal(both.crit1_accuracy_recall, 0.1);
});

test('the gate taxonomy is the locked accuracy/precision split (G1 accuracy, G2 precision-only)', () => {
  assert.deepEqual([...ACCURACY_GATES], ['G1']);
  assert.deepEqual([...PRECISION_GATES], ['G2']);
  assert.throws(() => attributeRecall([], { planted: 0 }), RangeError);
  assert.throws(() => attributeRecall('nope', { planted: 1 }), TypeError);
});
