// Wave 6 — Phase-F oracle: the certifiers are load-bearing, CATEGORICALLY (proof-verification ENABLED,
// honestly bounded). Exercises the REAL Wave-6 Phase-F corpus + scorer (src/oracle-corpus.mjs +
// src/oracle-scorer.mjs) against the REAL Increment-2 certifier spine (lean-certifier / smt-faithfulness /
// cross-family-verifier, wired through the REAL VERIFY router), proving the Wave-6 done-when:
//
//   with the certifiers ON vs the ABLATION (OFF ⇒ the deferred Increment-1 abstain arm):
//     • EVERY planted-unfaithful formalization is OBSERVED-BLOCKED ON / ABSTAINED OFF;
//     • EVERY false-Lean theorem REJECTS ON / ABSTAINS OFF;
//     • EVERY cross-family-disagreement stays CONJECTURAL (no lift) ON and OFF;
//     • EVERY quarantine case has its lift DISABLED ON and OFF;
//     • forged/replayed/cross-claim artifacts are BLOCKED; a plausible-but-wrong proof earns no corroboration;
//     • the GENUINE positive arm LIFTS ON but only ABSTAINS OFF (the ablation is LOAD-BEARING);
//     • honest bounds: a correlated cross-family agreement stays SOFT (< OBSERVED); an out-of-z3-decidable
//       formalization fails-CLOSED (OBSERVED WITHHELD); ≥k fixtures per class.
//
// FAST tier only (no tool, cannot hang — the injected-stub isolation contract the Wave-2…5 fast tiers use;
// the REAL lean/z3/ollama tools run in the env-gated serial lane those waves' tool-lanes already own).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  loadPhaseFCorpus,
  runPhaseFFixture,
  plantedUnfaithfulIsNecessaryNotSufficient,
  PHASEF_OUTCOME,
  PHASEF_CLASSES,
  PHASEF_DEFECT_CLASSES,
  PHASEF_POSITIVE_CLASSES,
  PHASEF_BOUND_CLASSES,
  OBSERVED_RUNG,
  PLAUSIBILITY_CORROBORATED_RUNG,
  RUNG,
} from '../src/oracle-corpus.mjs';
import { compareRungs } from '../src/claim-ledger.mjs';
import { runPhaseFOracleGate, PHASEF_MIN_PER_CLASS } from '../src/oracle-scorer.mjs';

// =====================================================================================
// 0. The Phase-F vocabulary + class rosters are pinned + frozen.
// =====================================================================================

test('E-F vocabulary: PHASEF_OUTCOME carries the normalized adjudicator outcomes and is frozen', () => {
  assert.deepEqual(
    [...Object.values(PHASEF_OUTCOME)].sort(),
    ['ABSTAIN', 'BLOCKED', 'CORROBORATED', 'OBSERVED', 'REJECTED', 'WITHHELD'],
  );
  assert.ok(Object.isFrozen(PHASEF_OUTCOME));
});

test('E-F vocabulary: the defect / positive / bound class rosters are pinned + frozen', () => {
  assert.deepEqual([...PHASEF_DEFECT_CLASSES].sort(), [
    'phasef-false-lean',
    'phasef-forged-replayed',
    'phasef-planted-unfaithful',
    'phasef-plausible-but-wrong',
    'phasef-quarantine',
    'phasef-xfam-disagreement',
  ]);
  assert.deepEqual([...PHASEF_POSITIVE_CLASSES].sort(), ['phasef-observed-sound', 'phasef-xfam-sound']);
  assert.deepEqual([...PHASEF_BOUND_CLASSES].sort(), ['phasef-correlated-failure', 'phasef-out-of-envelope']);
  for (const r of [PHASEF_DEFECT_CLASSES, PHASEF_POSITIVE_CLASSES, PHASEF_BOUND_CLASSES, PHASEF_CLASSES]) assert.ok(Object.isFrozen(r));
});

// =====================================================================================
// 1. THE CORPUS LOADS, is fully labeled, and has ≥k per defect/positive class (the done-when's ≥k).
// =====================================================================================

test('done-when: the Phase-F corpus loads (frozen) and every fixture is labeled with a known class + outcome', () => {
  const corpus = loadPhaseFCorpus();
  assert.ok(Object.isFrozen(corpus) && Object.isFrozen(corpus.flat));
  assert.ok(corpus.flat.length > 0);
  const ids = corpus.flat.map((f) => f.id);
  assert.equal(new Set(ids).size, ids.length, 'no duplicate Phase-F fixture ids');
  for (const f of corpus.flat) {
    assert.ok(PHASEF_CLASSES.includes(f.class), `${f.id} has a known class (got ${f.class})`);
    assert.ok(Object.values(PHASEF_OUTCOME).includes(f.expected_outcome), `${f.id} has a known expected_outcome`);
    assert.ok(['proof', 'cross-family'].includes(f.verifier), `${f.id} names a verifier`);
  }
});

test('done-when: ≥k fixtures per defect + positive class (every fixture stays in the z3-decidable envelope)', () => {
  const corpus = loadPhaseFCorpus();
  for (const klass of [...PHASEF_DEFECT_CLASSES, ...PHASEF_POSITIVE_CLASSES]) {
    assert.ok(corpus.byClass[klass].length >= PHASEF_MIN_PER_CLASS, `${klass} has ≥${PHASEF_MIN_PER_CLASS} fixtures (got ${corpus.byClass[klass].length})`);
  }
});

// =====================================================================================
// 2. THE CATEGORICAL DONE-WHEN — every fixture, ON vs the ablation OFF. (Each clause its own GWT.)
// =====================================================================================

// One shared run of the whole corpus (the real adjudicators) for the per-fixture assertions.
let RESULTS = null;
test('run the whole Phase-F corpus through the certifier ON + the ablation OFF (setup)', async () => {
  const corpus = loadPhaseFCorpus();
  RESULTS = {};
  for (const f of corpus.flat) RESULTS[f.id] = { fixture: f, result: await runPhaseFFixture(f) };
  assert.ok(Object.keys(RESULTS).length === corpus.flat.length);
});

function forClass(klass) {
  return Object.values(RESULTS).filter((e) => e.fixture.class === klass);
}
const isLifted = (rung) => compareRungs(rung, RUNG.UNVERIFIED) > 0;
const isSettled = (rung) => compareRungs(rung, OBSERVED_RUNG) >= 0;

test('GWT: EVERY planted-unfaithful case is OBSERVED-BLOCKED ON / ABSTAINED OFF (no green proof of a wrong statement)', () => {
  const entries = forClass('phasef-planted-unfaithful');
  assert.ok(entries.length >= PHASEF_MIN_PER_CLASS);
  for (const { fixture, result } of entries) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.BLOCKED, `${fixture.id}: OBSERVED hard-faults ON`);
    assert.ok(!isSettled(result.on.rung), `${fixture.id}: never reaches OBSERVED`);
    assert.equal(result.off.outcome, PHASEF_OUTCOME.ABSTAIN, `${fixture.id}: abstains under the ablation`);
  }
});

test('GWT: EVERY planted-unfaithful case is NECESSARY-NOT-SUFFICIENT (passes the instance battery; the bounded differential catches it)', async () => {
  for (const f of loadPhaseFCorpus().byClass['phasef-planted-unfaithful']) {
    assert.ok(await plantedUnfaithfulIsNecessaryNotSufficient(f), `${f.id}: the finite battery agrees but the differential disagrees`);
  }
});

test('GWT: EVERY false-Lean theorem REJECTS ON / ABSTAINS OFF', () => {
  const entries = forClass('phasef-false-lean');
  assert.ok(entries.length >= PHASEF_MIN_PER_CLASS);
  for (const { fixture, result } of entries) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.REJECTED, `${fixture.id}: the Lean kernel rejects ON`);
    assert.ok(!isLifted(result.on.rung), `${fixture.id}: never lifted`);
    assert.equal(result.off.outcome, PHASEF_OUTCOME.ABSTAIN, `${fixture.id}: abstains OFF`);
  }
});

test('GWT: EVERY cross-family-disagreement stays CONJECTURAL (no lift) ON and OFF', () => {
  const entries = forClass('phasef-xfam-disagreement');
  assert.ok(entries.length >= PHASEF_MIN_PER_CLASS);
  for (const { fixture, result } of entries) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.ABSTAIN, `${fixture.id}: a split panel earns no lift`);
    assert.ok(!isLifted(result.on.rung), `${fixture.id}: stays at the UNVERIFIED floor (CONJECTURAL)`);
    assert.equal(result.off.outcome, PHASEF_OUTCOME.ABSTAIN);
  }
});

test('GWT: EVERY quarantine case has its lift DISABLED (no ≥2-family trusted quorum) ON and OFF', () => {
  const entries = forClass('phasef-quarantine');
  assert.ok(entries.length >= PHASEF_MIN_PER_CLASS);
  for (const { fixture, result } of entries) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.ABSTAIN, `${fixture.id}: a quarantined certifier cannot lift`);
    assert.ok(!isLifted(result.on.rung));
    assert.equal(result.off.outcome, PHASEF_OUTCOME.ABSTAIN);
  }
});

test('GWT: forged / replayed / cross-claim artifacts are BLOCKED ON (caught by the independent re-run / binding)', () => {
  const entries = forClass('phasef-forged-replayed');
  assert.ok(entries.length >= PHASEF_MIN_PER_CLASS);
  for (const { fixture, result } of entries) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.BLOCKED, `${fixture.id}: the forgery/replay is FLAGged`);
    assert.ok(!isLifted(result.on.rung), `${fixture.id}: never flips the rung`);
    assert.equal(result.off.outcome, PHASEF_OUTCOME.ABSTAIN);
  }
});

test('GWT: a plausible-but-wrong proof earns NO corroboration (the cross-family verifier rejects it)', () => {
  const entries = forClass('phasef-plausible-but-wrong');
  assert.ok(entries.length >= PHASEF_MIN_PER_CLASS);
  for (const { fixture, result } of entries) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.ABSTAIN, `${fixture.id}: a NO quorum is not a corroboration`);
    assert.ok(!isLifted(result.on.rung));
    assert.equal(result.off.outcome, PHASEF_OUTCOME.ABSTAIN);
  }
});

// =====================================================================================
// 3. THE POSITIVE ARM + THE ABLATION — the now-enabled lift; the certifier is LOAD-BEARING.
// =====================================================================================

test('GWT: the GENUINE positive arm LIFTS ON (OBSERVED / soft-CORROBORATED) but only ABSTAINS OFF (load-bearing)', () => {
  for (const klass of PHASEF_POSITIVE_CLASSES) {
    const entries = forClass(klass);
    assert.ok(entries.length >= PHASEF_MIN_PER_CLASS, `${klass} has ≥${PHASEF_MIN_PER_CLASS}`);
    for (const { fixture, result } of entries) {
      assert.ok(
        result.on.outcome === PHASEF_OUTCOME.OBSERVED || result.on.outcome === PHASEF_OUTCOME.CORROBORATED,
        `${fixture.id}: lifts with the certifier ON (got ${result.on.outcome})`,
      );
      assert.ok(isLifted(result.on.rung), `${fixture.id}: the ledger rung is lifted ON`);
      // the ablation collapses the lift to ABSTAIN — the certifier is what did the lifting.
      assert.equal(result.off.outcome, PHASEF_OUTCOME.ABSTAIN, `${fixture.id}: ablation reverts to abstain`);
      assert.ok(!isLifted(result.off.rung), `${fixture.id}: the rung is NOT lifted under the ablation`);
      assert.notEqual(result.on.outcome, result.off.outcome, `${fixture.id}: ON ≠ OFF (the lift is load-bearing)`);
    }
  }
});

test('observed-sound lifts to OBSERVED specifically; xfam-sound lifts only to the SOFT rung (< OBSERVED)', () => {
  for (const { fixture, result } of forClass('phasef-observed-sound')) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.OBSERVED, fixture.id);
    assert.equal(result.on.rung, RUNG.OBSERVED, fixture.id);
  }
  for (const { fixture, result } of forClass('phasef-xfam-sound')) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.CORROBORATED, fixture.id);
    assert.equal(result.on.rung, PLAUSIBILITY_CORROBORATED_RUNG, fixture.id);
    assert.ok(!isSettled(result.on.rung), `${fixture.id}: a soft cross-family check is strictly below OBSERVED`);
  }
});

test('the ablation reverts EVERY Phase-F fixture (defect + positive + bound) to ABSTAIN', () => {
  for (const { fixture, result } of Object.values(RESULTS)) {
    assert.equal(result.off.outcome, PHASEF_OUTCOME.ABSTAIN, `${fixture.id}: certifiers OFF ⇒ abstain`);
  }
});

// =====================================================================================
// 4. THE HONEST BOUNDS — correlated-failure stays soft; out-of-envelope fails-closed.
// =====================================================================================

test('honest bound: a CORRELATED cross-family agreement stays SOFT (lifts, but strictly BELOW OBSERVED — never settled)', () => {
  const entries = forClass('phasef-correlated-failure');
  assert.ok(entries.length >= 1);
  for (const { fixture, result } of entries) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.CORROBORATED, fixture.id);
    assert.ok(isLifted(result.on.rung) && !isSettled(result.on.rung), `${fixture.id}: soft rung < OBSERVED (the correlated blind spot can't reach OBSERVED)`);
  }
});

test('honest bound: an out-of-z3-decidable (quantified) formalization fails-CLOSED (OBSERVED WITHHELD)', () => {
  const entries = forClass('phasef-out-of-envelope');
  assert.ok(entries.length >= 1);
  for (const { fixture, result } of entries) {
    assert.equal(result.on.outcome, PHASEF_OUTCOME.WITHHELD, fixture.id);
  }
});

// =====================================================================================
// 5. THE PHASE-F ORACLE GATE — the full categorical done-when (HALT iff !pass).
// =====================================================================================

test('oracle gate: pass === true (every categorical clause green) — the wave does NOT HALT', async () => {
  const gate = await runPhaseFOracleGate();
  assert.equal(gate.pass, true, `gate must pass; checks=${JSON.stringify(gate.checks)}`);
  for (const [name, ok] of Object.entries(gate.checks)) assert.equal(ok, true, `check ${name} must be green`);
});

test('oracle gate: every defect + positive + bound class is individually reported as met (all ON + all OFF abstain)', async () => {
  const gate = await runPhaseFOracleGate();
  for (const klass of [...PHASEF_DEFECT_CLASSES, ...PHASEF_POSITIVE_CLASSES, ...PHASEF_BOUND_CLASSES]) {
    assert.equal(gate.perClass[klass].met, true, `${klass} met`);
  }
  assert.ok(Object.isFrozen(gate));
});

// =====================================================================================
// 6. NEGATIVE / HALT-arm — the gate genuinely HALTs when a certifier is silently disabled (it has teeth).
// =====================================================================================

test('HALT-arm: a corpus whose planted-unfaithful class is silently down-graded to the sound (faithful) path makes the gate FAIL', async () => {
  // Re-label the planted-unfaithful fixtures' SCENARIO to the sound OBSERVED path (a faithful formalization
  // + lean exit 0). They would now reach OBSERVED instead of hard-faulting ⇒ the categorical
  // "planted-unfaithful is OBSERVED-BLOCKED" clause FAILS ⇒ the gate HALTs (the gate has teeth — a
  // certifier that no longer blocks an unfaithful formalization is caught, not greened).
  const base = loadPhaseFCorpus();
  const degraded = base.byClass['phasef-planted-unfaithful'].map((f) => Object.freeze({ ...f, scenario: 'observed-sound' }));
  const corpus = Object.freeze({
    flat: Object.freeze(base.flat.map((f) => (f.class === 'phasef-planted-unfaithful' ? degraded.find((d) => d.id === f.id) : f))),
    byClass: Object.freeze({ ...base.byClass, 'phasef-planted-unfaithful': Object.freeze(degraded) }),
  });
  const gate = await runPhaseFOracleGate({ corpus });
  assert.equal(gate.checks.plantedUnfaithfulBlocked, false, 'the down-graded fixtures now reach OBSERVED instead of hard-faulting');
  assert.equal(gate.pass, false, 'the gate must HALT when the certifier no longer blocks an unfaithful formalization');
});
