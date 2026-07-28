// test/baseline.test.mjs — Wave 3 gate: the single-pass baseline is captured as a NAMED, HASHED
// artifact, the fixture is sized by the power calc, and the artifact is FROZEN so later waves can
// load it by hash (IMPLEMENTATION-PLAN Wave 3 done-when). Every assertion exercises the real Wave-3
// source (bin/power-calc, bin/fixture, bin/baseline) over the committed on-disk artifact — no
// vacuous GREEN.
//
// "regeneration ⇒ RED" is enforced two ways: (1) the on-disk fixture must equal what the
// deterministic generator re-derives, and (2) the artifact's payload must hash to the FROZEN
// expected name below. Change the fixture/model and the payload changes ⇒ the hash moves ⇒ this
// gate (and every later load-by-hash) goes RED.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import { powerCalc, sampleForProportion } from '../bin/power-calc.mjs';
import { FIXTURE_COUNTS } from '../bin/fixture-counts.mjs';
import {
  generateFixture,
  singlePassCatches,
  RECALL_CLASSES,
  PROBE_CLASSES,
} from '../bin/fixture.mjs';
import {
  CORPUS_FILE,
  DEFECTS_FILE,
  BASELINE_FILE,
  loadFixture,
  computeBaseline,
  buildBaseline,
  hashPayload,
  canonicalize,
  loadBaselineArtifact,
  loadBaselineByHash,
} from '../bin/baseline.mjs';

// The FROZEN content name of the single-pass baseline (sha256 of its canonical payload). This is
// the hash later waves pin via loadBaselineByHash. It is committed HERE so the baseline cannot be
// silently regenerated: any change to the fixture, the single-pass model, or the recall calc moves
// this hash and turns the gate RED (IMPLEMENTATION-PLAN Wave 3: "regeneration ⇒ RED").
const EXPECTED_BASELINE_HASH = '67792c6f6f78b4c9f58b2d2c4158921a540465a9400cbbc248e81d3119f4221d';

// ── Existence ─────────────────────────────────────────────────────────────────────────────────
test('the frozen fixture (corpus + manifest) and the named baseline artifact exist', () => {
  assert.ok(fs.existsSync(CORPUS_FILE), 'fixtures/corpus.jsonl must exist (Wave 3 capture)');
  assert.ok(fs.existsSync(DEFECTS_FILE), 'fixtures/defects.jsonl must exist (Wave 3 capture)');
  assert.ok(fs.existsSync(BASELINE_FILE), 'baseline/single-pass-baseline.json must exist');
});

// ── Power calc: the fixture is sized so G and C_min are statistically reachable ──────────────────
test('the power calc reads the committed thresholds and sizes from them (not invented)', () => {
  const pc = powerCalc();
  // CBS sample sized around the committed C_min; misses sized around the committed G.
  assert.equal(pc.minCbs, sampleForProportion(pc.C_min, pc.design.cbsHalfWidth));
  assert.equal(pc.minSinglePassMisses, sampleForProportion(pc.G, pc.design.closureHalfWidth));
  assert.ok(pc.minCbs >= 1 && pc.minSinglePassMisses >= 1, 'sizing must be a real positive count');
});

test('sampleForProportion follows the Wald formula and rejects out-of-range inputs', () => {
  // ⌈ z² · p(1-p) / hw² ⌉ at p=0.5, hw=0.1, z≈1.96 → ⌈96.04⌉ = 97.
  assert.equal(sampleForProportion(0.5, 0.1), 97);
  assert.throws(() => sampleForProportion(0, 0.1), RangeError);
  assert.throws(() => sampleForProportion(0.5, 0), RangeError);
  assert.throws(() => sampleForProportion(0.5, 1), RangeError);
});

test('the fixture meets every power-calc minimum (well-powered for crit-1 and I2)', () => {
  const pc = powerCalc();
  const { defects } = loadFixture();
  const cbsCount = defects.filter((d) => d.class === 'correlated-blind-spot').length;
  const singlePassMisses = defects
    .filter((d) => RECALL_CLASSES.includes(d.class))
    .filter((d) => !singlePassCatches(d)).length;

  assert.ok(cbsCount >= pc.minCbs, `CBS count ${cbsCount} must be ≥ power-calc minimum ${pc.minCbs} (I2)`);
  assert.ok(
    singlePassMisses >= pc.minSinglePassMisses,
    `single-pass misses ${singlePassMisses} must be ≥ power-calc minimum ${pc.minSinglePassMisses} (crit-1 denominator)`,
  );
});

// ── Mandatory classes + their required fields (FIXTURE-SPEC) are actually planted ───────────────
test('all four mandatory defect classes are present at the committed counts', () => {
  const { defects } = loadFixture();
  const count = (c) => defects.filter((d) => d.class === c).length;
  assert.equal(count('ordinary'), FIXTURE_COUNTS.ordinaryCaught + FIXTURE_COUNTS.ordinaryMissed);
  assert.equal(count('correlated-blind-spot'), FIXTURE_COUNTS.cbs);
  assert.equal(count('path-defect'), FIXTURE_COUNTS.pathDefect);
  assert.equal(count('declared-low-but-irreversible'), FIXTURE_COUNTS.irreversible);
  for (const c of PROBE_CLASSES) assert.ok(count(c) >= 1, `at least one ${c} probe is mandatory`);
});

test('CBS records carry lineage_trap; irreversible records carry the under-call answer key', () => {
  const { defects } = loadFixture();
  for (const d of defects.filter((x) => x.class === 'correlated-blind-spot')) {
    assert.ok(typeof d.lineage_trap === 'string' && d.lineage_trap.length > 0, `${d.id} needs lineage_trap (I2)`);
  }
  for (const d of defects.filter((x) => x.class === 'declared-low-but-irreversible')) {
    assert.equal(d.declared_stakes, 'low', `${d.id} must declare low stakes`);
    assert.equal(d.reversibility, 'irreversible', `${d.id} must be irreversible`);
    assert.match(d.expected_tier, />=\s*medium/, `${d.id} answer key must be tier ≥ medium (I6)`);
  }
  for (const d of defects.filter((x) => x.class === 'path-defect')) {
    assert.ok(d.wrong_branch, `${d.id} must name the wrong branch (crit-3)`);
    assert.ok(d.counterfactual_cost, `${d.id} must name the counterfactual cost (crit-3)`);
  }
});

// ── Single-pass model honesty (I1): a same-lineage single pass recovers NO correlated blind spot ─
test('single-pass CBS recall is 0 (I1: default mode cannot close a shared blind spot)', () => {
  const payload = loadBaselineArtifact().payload;
  assert.equal(payload.single_pass.by_class['correlated-blind-spot'].recall, 0);
});

test('single-pass ordinary recall is a real, non-trivial baseline in (0, 1)', () => {
  const ord = loadBaselineArtifact().payload.single_pass.by_class.ordinary;
  assert.ok(ord.recall > 0 && ord.recall < 1, `ordinary recall ${ord.recall} must be in (0,1)`);
});

test('the manifest single_pass_caught field agrees with the model that produced it', () => {
  const { defects } = loadFixture();
  for (const d of defects) {
    assert.equal(
      d.single_pass_caught,
      singlePassCatches(d),
      `${d.id}: committed single_pass_caught must equal the model verdict`,
    );
  }
});

// ── Hash integrity + the FROZEN name ────────────────────────────────────────────────────────────
test('the artifact payload hashes to its own self-declared hash (integrity)', () => {
  const artifact = loadBaselineArtifact();
  assert.equal(hashPayload(artifact.payload), artifact.hash, 'payload no longer matches its hash');
});

test('the committed baseline hash equals the FROZEN expected name (no silent regeneration)', () => {
  const artifact = loadBaselineArtifact();
  assert.equal(artifact.hash, EXPECTED_BASELINE_HASH);
});

// ── Reproducibility: regenerating from the generator yields the identical payload ⇒ frozen ───────
test('computeBaseline over the on-disk fixture reproduces the committed payload exactly', () => {
  const recomputed = computeBaseline(loadFixture());
  const committed = loadBaselineArtifact().payload;
  assert.equal(canonicalize(recomputed), canonicalize(committed), 'recomputed payload drifted from committed');
  assert.equal(hashPayload(recomputed), EXPECTED_BASELINE_HASH);
});

test('the on-disk fixture equals what the deterministic generator re-derives (drift ⇒ RED)', () => {
  const gen = generateFixture();
  const stamped = gen.defects.map((d) => ({ ...d, single_pass_caught: singlePassCatches(d) }));
  const disk = loadFixture();
  assert.equal(canonicalize(disk.corpus), canonicalize(gen.corpus), 'corpus.jsonl drifted from the generator');
  assert.equal(canonicalize(disk.defects), canonicalize(stamped), 'defects.jsonl drifted from the generator');
  // And the generator-built payload still hashes to the frozen name.
  assert.equal(buildBaseline({ corpus: gen.corpus, defects: stamped }).hash, EXPECTED_BASELINE_HASH);
});

// ── The load-by-hash API later waves depend on ─────────────────────────────────────────────────
test('loadBaselineByHash returns the payload for the frozen hash and rejects a wrong one', () => {
  const payload = loadBaselineByHash(EXPECTED_BASELINE_HASH);
  assert.equal(payload.gap_closure_denominator.single_pass_misses, payload.single_pass.missed);
  assert.throws(
    () => loadBaselineByHash('0'.repeat(64)),
    /baseline hash mismatch/,
    'a wrong expected hash must be rejected (later waves must not measure against the wrong baseline)',
  );
});

// ── The gap-closure denominator is internally consistent ────────────────────────────────────────
test('the gap-closure denominator equals the single-pass miss count (what G is a fraction of)', () => {
  const sp = loadBaselineArtifact().payload.single_pass;
  const denom = loadBaselineArtifact().payload.gap_closure_denominator.single_pass_misses;
  assert.equal(denom, sp.missed);
  assert.equal(sp.planted, sp.caught + sp.missed);
});
