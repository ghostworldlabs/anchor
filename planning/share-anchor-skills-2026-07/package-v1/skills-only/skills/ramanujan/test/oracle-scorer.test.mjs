// Wave 25 — Gradeable oracle, part B: Metric-G scorer + canned baseline + ablation (E1b).
//
// Exercises the REAL Wave-25 scorer (src/oracle-scorer.mjs) over the REAL Wave-24 corpus + spine,
// proving the done-when (every pinned constant cited):
//
//   • G(battery-on) > G(better-stub-baseline) + 0.30 (STRICT) AND the ablation arm scores measurably
//     lower (G drops below battery-on by more than 0.30 — the battery is load-bearing);
//   • per-class catch floors: derivation/dimensional/off-by-one = 100%,
//       convergence-stability/comprehension-narrative/firewall-inapplicable ≥ 2/3 each;
//   • k′ = at most 1 false positive on the FIXED 6-fixture SOUND subset;
//   • ABSTAIN-correctness = 100% of proof/conceptual arms ABSTAIN.
//
// The two defining Given/When/Thens:
//   • given the ablation arm (battery disabled), when the scorer runs on the SCORED SUBSET, then G
//     drops below battery-on by more than 0.30 (battery is load-bearing);
//   • given either stub baseline, when the scorer runs, then battery-on G exceeds the better stub's G
//     by > 0.30, and all per-class floors + k′ + the 100% abstain floor hold (else the wave HALTs).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  G_EPSILON,
  PER_CLASS_CATCH_FLOORS,
  K_PRIME_MAX,
  ABSTAIN_CORRECTNESS_FLOOR,
  SCORER,
  STUB_SCORERS,
  SCORER_NAMES,
  realBatteryFlags,
  scoredSubset,
  soundSubset,
  scoreScorer,
  proofConceptualAbstainArms,
  measureAbstainCorrectness,
  runOracleGate,
} from '../src/oracle-scorer.mjs';

import { loadCorpus, DEFECT_CLASSES, SUBSET, SOUND_SUBSET_CARDINALITY, trueResultOf } from '../src/oracle-corpus.mjs';

// =====================================================================================
// 0. The pinned constants are exactly the R1 / Metric-G values and are frozen.
// =====================================================================================

test('E1b constants: the epsilon is the pinned 0.30 (strict)', () => {
  assert.equal(G_EPSILON, 0.3);
});

test('E1b constants: the per-class catch floors are exactly the R1 set (exact fractions, frozen)', () => {
  assert.deepEqual(PER_CLASS_CATCH_FLOORS['derivation-error'], { num: 1, den: 1 });
  assert.deepEqual(PER_CLASS_CATCH_FLOORS.dimensional, { num: 1, den: 1 });
  assert.deepEqual(PER_CLASS_CATCH_FLOORS['off-by-one'], { num: 1, den: 1 });
  assert.deepEqual(PER_CLASS_CATCH_FLOORS['convergence-stability'], { num: 2, den: 3 });
  assert.deepEqual(PER_CLASS_CATCH_FLOORS['comprehension-narrative'], { num: 2, den: 3 });
  assert.deepEqual(PER_CLASS_CATCH_FLOORS['firewall-inapplicable'], { num: 2, den: 3 });
  assert.ok(Object.isFrozen(PER_CLASS_CATCH_FLOORS));
  // every defect class has a pinned floor.
  for (const klass of DEFECT_CLASSES) assert.ok(PER_CLASS_CATCH_FLOORS[klass], `${klass} has a floor`);
});

test('E1b constants: k′ ≤ 1 and the abstain floor = 100%', () => {
  assert.equal(K_PRIME_MAX, 1);
  assert.equal(ABSTAIN_CORRECTNESS_FLOOR, 1);
});

test('E1b constants: the four pinned scorers (battery-on, ablation, two canned stubs) are present + frozen', () => {
  assert.deepEqual([...SCORER_NAMES].sort(), ['ablation', 'battery-on', 'stub-always-abstain', 'stub-always-flag']);
  assert.deepEqual([...STUB_SCORERS].sort(), ['stub-always-abstain', 'stub-always-flag']);
  assert.ok(Object.isFrozen(SCORER));
  assert.ok(Object.isFrozen(STUB_SCORERS));
});

// =====================================================================================
// 1. The SCORED + SOUND subsets are selected per the canonical token (catch denominator = SCORED only).
// =====================================================================================

test('subsets: the SCORED subset is exactly the planted-defect fixtures (6 classes × ≥3), all SUBSET.SCORED', () => {
  const corpus = loadCorpus();
  const scored = scoredSubset(corpus);
  assert.equal(scored.length, 18, 'six defect classes × 3 instances');
  for (const f of scored) assert.equal(f.subset, SUBSET.SCORED, `${f.id} in SCORED`);
  // the SOUND subset is NOT in the catch denominator.
  for (const f of scored) assert.notEqual(f.class, 'sound');
});

test('subsets: the SOUND subset is the FIXED 6-fixture FP/k′ term (excluded from the catch denominator)', () => {
  const corpus = loadCorpus();
  const sound = soundSubset(corpus);
  assert.equal(sound.length, SOUND_SUBSET_CARDINALITY);
  assert.equal(sound.length, 6);
  for (const f of sound) assert.equal(f.subset, SUBSET.SOUND);
});

// =====================================================================================
// 2. BATTERY-ON — the real spine catches every defect and false-flags no sound fixture.
// =====================================================================================

test('battery-on: catch-rate = 1.0 over the SCORED subset (the real spine catches every planted defect)', () => {
  const s = scoreScorer(SCORER.BATTERY_ON);
  assert.equal(s.scored.total, 18);
  assert.equal(s.scored.caught, 18);
  assert.equal(s.scored.catchRate, 1);
});

test('battery-on: every per-class catch rate meets its floor (the deterministic 3 = 100%, the soft 3 ≥ 2/3)', () => {
  const s = scoreScorer(SCORER.BATTERY_ON);
  for (const klass of DEFECT_CLASSES) {
    const pc = s.perClass[klass];
    const floor = PER_CLASS_CATCH_FLOORS[klass];
    assert.ok(pc.caught * floor.den >= floor.num * pc.total, `${klass}: ${pc.caught}/${pc.total} ≥ ${floor.num}/${floor.den}`);
  }
});

test('battery-on: ZERO false positives on the SOUND subset (k′ = 0 ≤ 1) ⇒ fpRate 0, G = 1.0', () => {
  const s = scoreScorer(SCORER.BATTERY_ON);
  assert.equal(s.sound.falsePositives, 0);
  assert.equal(s.sound.kPrime, 0);
  assert.ok(s.sound.kPrime <= K_PRIME_MAX);
  assert.equal(s.sound.fpRate, 0);
  assert.equal(s.G, 1);
});

test('battery-on: realBatteryFlags flags every defect and NO sound fixture (non-vacuity of the battery)', () => {
  const corpus = loadCorpus();
  for (const f of scoredSubset(corpus)) assert.equal(realBatteryFlags(f), true, `${f.id} (defect) is flagged`);
  for (const f of soundSubset(corpus)) assert.equal(realBatteryFlags(f), false, `${f.id} (sound) is NOT flagged`);
});

// =====================================================================================
// 3. THE CANNED STUB BASELINES — both content-blind constants score G = 0 (identical formula).
// =====================================================================================

test('stubs: always-ABSTAIN and always-FLAG each catch all defects AND false-flag all sound ⇒ G = 0', () => {
  for (const name of STUB_SCORERS) {
    const s = scoreScorer(name);
    assert.equal(s.scored.catchRate, 1, `${name} catches every defect (content-blind)`);
    assert.equal(s.sound.fpRate, 1, `${name} false-flags every sound fixture`);
    assert.equal(s.sound.kPrime, 6, `${name} k′ = all 6 sound fixtures`);
    assert.equal(s.G, 0, `${name} G = catchRate − fpRate = 0`);
  }
});

test('stubs: the two baselines are scored by the IDENTICAL formula and coincide at G = 0', () => {
  const a = scoreScorer(SCORER.STUB_ALWAYS_ABSTAIN);
  const f = scoreScorer(SCORER.STUB_ALWAYS_FLAG);
  assert.equal(a.G, f.G);
  assert.equal(Math.max(a.G, f.G), 0, 'the better stub is still 0');
});

// =====================================================================================
// 4. THE ABLATION ARM — battery disabled ⇒ catch-rate collapses ⇒ G collapses (load-bearing).
// =====================================================================================

test('ablation: the battery disabled greens everything ⇒ catch-rate 0, fpRate 0, G = 0', () => {
  const s = scoreScorer(SCORER.ABLATION);
  assert.equal(s.scored.catchRate, 0, 'no defect is caught with the battery off');
  assert.equal(s.sound.fpRate, 0, 'sound fixtures are still greened (not false-flagged)');
  assert.equal(s.G, 0);
});

test('GWT (ablation): G drops below battery-on by more than 0.30 (the battery is load-bearing)', () => {
  const on = scoreScorer(SCORER.BATTERY_ON).G;
  const off = scoreScorer(SCORER.ABLATION).G;
  assert.ok(on - off > G_EPSILON, `battery-on ${on} − ablation ${off} = ${on - off} must exceed ${G_EPSILON}`);
});

// =====================================================================================
// 5. ABSTAIN-CORRECTNESS — 100% of the proof/conceptual arms ABSTAIN through the REAL router.
// =====================================================================================

test('abstain: the proof/conceptual arms are non-empty (the abstain-payload + comprehension proof/conceptual subclaims)', () => {
  const arms = proofConceptualAbstainArms();
  assert.ok(arms.length >= 2, `expected ≥2 proof/conceptual arms, got ${arms.length}`);
  for (const a of arms) assert.ok(a.type === 'proof-bearing' || a.type === 'conceptual', `${a.id} is proof/conceptual`);
});

test('abstain: 100% of the proof/conceptual arms ABSTAIN + route through the real VerifyRouter', () => {
  const m = measureAbstainCorrectness();
  assert.equal(m.abstained, m.total);
  assert.equal(m.rate, 1);
  assert.ok(m.rate >= ABSTAIN_CORRECTNESS_FLOOR);
  for (const r of m.results) assert.equal(r.abstained, true, `${r.id} must ABSTAIN`);
});

// =====================================================================================
// 6. THE ORACLE GATE — the full Wave-25 done-when (HALT iff !pass). The two headline GWTs.
// =====================================================================================

test('GWT (baseline): battery-on G exceeds the better stub by > 0.30, and every floor + k′ + abstain holds', () => {
  const gate = runOracleGate();
  // the headline strict-epsilon comparison.
  assert.ok(gate.scores.batteryOn.G > gate.betterStubG + G_EPSILON, `${gate.scores.batteryOn.G} > ${gate.betterStubG} + ${G_EPSILON}`);
  assert.equal(gate.checks.beatsBaseline, true);
  // every other pinned floor.
  assert.equal(gate.checks.perClassFloorsMet, true);
  assert.equal(gate.checks.kPrimeMet, true);
  assert.equal(gate.checks.abstainMet, true);
});

test('oracle gate: pass === true (all checks green) — the wave does NOT HALT', () => {
  const gate = runOracleGate();
  assert.equal(gate.pass, true, `gate must pass; checks=${JSON.stringify(gate.checks)}`);
  assert.equal(gate.checks.beatsBaseline, true);
  assert.equal(gate.checks.ablationLoadBearing, true);
  assert.equal(gate.checks.perClassFloorsMet, true);
  assert.equal(gate.checks.kPrimeMet, true);
  assert.equal(gate.checks.abstainMet, true);
});

test('oracle gate: every per-class floor is individually reported as met (battery-on)', () => {
  const gate = runOracleGate();
  for (const klass of DEFECT_CLASSES) {
    assert.equal(gate.perClassFloors[klass].met, true, `${klass} floor met`);
  }
});

test('oracle gate: the report is frozen and carries the four scorer scores + the better-stub G', () => {
  const gate = runOracleGate();
  assert.ok(Object.isFrozen(gate));
  assert.ok(gate.scores.batteryOn && gate.scores.ablation && gate.scores.stubAbstain && gate.scores.stubFlag);
  assert.equal(gate.epsilon, G_EPSILON);
  assert.equal(gate.betterStubG, 0);
});

// =====================================================================================
// 7. NEGATIVE / HALT-arm — the gate genuinely HALTs when a floor is not met (the canary has teeth).
// =====================================================================================

test('HALT-arm: a corpus whose battery misses defects (sub-floor catch) makes the gate FAIL', () => {
  // Build a degraded corpus where one deterministic-floor class is entirely un-catchable by the real
  // battery: each fixture's asserted result is made CORRECT (== the re-executed true value), so
  // computationalDefectIsReal ⇒ false ⇒ the battery does NOT flag it ⇒ the 100% floor is missed.
  const base = loadCorpus();
  const brokenClass = base.defects['derivation-error'].map((f) => ({ ...f, asserted_result: trueResultOf(f.expr) }));
  // a frozen corpus clone with the broken class swapped in.
  const corpus = Object.freeze({
    ...base,
    defects: Object.freeze({ ...base.defects, 'derivation-error': Object.freeze(brokenClass) }),
  });
  const gate = runOracleGate({ corpus });
  assert.equal(gate.checks.perClassFloorsMet, false, 'the derivation-error floor (100%) must now fail');
  assert.equal(gate.pass, false, 'the gate must HALT when a per-class floor is missed');
});
