// test/rho-ledger.test.mjs — Wave 9 gate: ρ-CALIBRATION LEDGER + LEARNED QUORUM (MONOTONE-SAFE).
//
// IMPLEMENTATION-PLAN Wave 9 done-when, each a concrete `node --test` assertion over the real
// bin/rho-ledger.mjs source (no vacuous GREEN):
//   (a) a persistent ledger records per-lineage-pair co-miss vs independent-catch events ACROSS runs
//       (asserted by TWO simulated runs persisting + reloading + appending);
//   (b) the estimator ROUND-TRIPS a seeded ρ within the pre-registered tolerance T — an ARITHMETIC
//       check that does NOT validate ρ̂ against real reviewer correlation;
//   (c) MONOTONE-SAFETY (load-bearing): NO value of ρ̂ ever produces a quorum looser than the static ≥2
//       floor — ρ̂ may only raise the bar; lowering the floor itself is a human code change (I8/crit-7);
//   (d) ρ̂ is stamped a "censored lower-bound" in the run output (A5);
//   (e) I8 reproducibility: the run stamps the ledger hash + derived threshold + what the static rule
//       would have required, and a replay with the same (inputs + ledger-hash) yields an identical
//       verdict; default mode with the ledger DISABLED is a pure function of inputs.
// Plus the two Given/Then cases: cold-start fallback below N_min (never fabricate a ρ̂) and the
// bounded-overhead guarantee (the learning layer fires ZERO sub-agents).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  RHO_CENSORED_STAMP,
  RHO_UNESTIMATED_STAMP,
  LEDGER_SCHEMA_VERSION,
  EVENT_KINDS,
  LEARNED_QUORUM_OVERHEAD,
  STATIC_QUORUM_FLOOR,
  calibrationThresholds,
  pairKey,
  emptyLedger,
  appendEvent,
  recordRun,
  loadLedger,
  saveLedger,
  ledgerHash,
  estimateRho,
  requiredQuorum,
  learnedQuorum,
  calibrationVerdict,
  runCalibration,
} from '../bin/rho-ledger.mjs';
import { loadPreregistration } from '../bin/preregistration.mjs';

// The committed Wave-9 thresholds — read from the SAME pre-registration the module reads (I6: the test
// does not invent N_min / T, it reads what a human committed in Wave 1).
const { N_min, T } = calibrationThresholds();

let tmpSeq = 0;
function tmpFile(name) {
  return path.join(os.tmpdir(), `rp-rho-${process.pid}-${tmpSeq++}-${name}.json`);
}

/** Seed a lineage pair with exact co-miss / independent-catch counts via the REAL append path. */
function seedPair(ledger, a, b, coMiss, indep) {
  for (let i = 0; i < coMiss; i++) appendEvent(ledger, { lineages: [a, b], kind: 'co-miss' });
  for (let i = 0; i < indep; i++) appendEvent(ledger, { lineages: [a, b], kind: 'independent-catch' });
  return ledger;
}

// ── the thresholds are the committed pre-registration values (honesty, I6) ───────────────────────────

test('calibrationThresholds reads the committed N_min and T (never invents them)', () => {
  const prereg = loadPreregistration();
  assert.equal(N_min, prereg.N_min);
  assert.equal(T, prereg.T);
  assert.ok(Number.isInteger(N_min) && N_min >= 1, 'N_min must be a committed positive integer');
  assert.ok(T > 0 && T <= 1, 'T must be a committed tolerance in (0,1]');
});

// ── done-when (a): a PERSISTENT ledger accumulates co-miss vs independent-catch events ACROSS runs ──

test('(a) the ledger persists, reloads and APPENDS across TWO simulated runs', () => {
  const file = tmpFile('persist');
  try {
    // RUN 1 — three defects examined by claude + gemini. defect-1 both miss (co-miss); defect-2 claude
    // catches, gemini misses (independent-catch); defect-3 both catch (skipped — not informative).
    const run1 = recordRun(emptyLedger(), [
      { defectId: 'cbs-1', byLineage: { claude: 'miss', gemini: 'miss' } },
      { defectId: 'ord-1', byLineage: { claude: 'catch', gemini: 'miss' } },
      { defectId: 'ord-2', byLineage: { claude: 'catch', gemini: 'catch' } },
    ]);
    saveLedger(run1, file);

    // RUN 2 — a SEPARATE run reloads the persisted ledger and appends more events to the SAME pair.
    const reloaded = loadLedger(file);
    assert.equal(reloaded.schema_version, LEDGER_SCHEMA_VERSION);
    const run2 = recordRun(reloaded, [
      { defectId: 'cbs-2', byLineage: { claude: 'miss', gemini: 'miss' } },
      { defectId: 'ord-3', byLineage: { claude: 'miss', gemini: 'catch' } },
    ]);
    saveLedger(run2, file);

    // The cross-run accumulation is visible on a fresh reload: co-miss 1+1=2, independent-catch 1+1=2.
    const final = loadLedger(file);
    const key = pairKey('claude', 'gemini');
    assert.deepEqual(final.pairs[key], { co_miss: 2, independent_catch: 2 }, 'events accumulated across the two runs');
    // The pair key is order-invariant — {claude,gemini} is the same pair as {gemini,claude}.
    assert.equal(pairKey('gemini', 'claude'), key);
    assert.equal(Object.keys(final.pairs).length, 1, 'only the one examined pair was recorded');
  } finally {
    fs.rmSync(file, { force: true });
  }
});

test('appendEvent / recordRun / pairKey reject malformed input (a same-lineage pair carries no signal)', () => {
  assert.throws(() => pairKey('claude', 'claude'), /DISTINCT/);
  assert.throws(() => pairKey('claude', ''), /non-empty/);
  assert.throws(() => appendEvent(emptyLedger(), { lineages: ['a'], kind: 'co-miss' }), /lineages:\[a,b\]/);
  assert.throws(() => appendEvent(emptyLedger(), { lineages: ['a', 'b'], kind: 'bogus' }), /kind must be one of/);
  assert.deepEqual([...EVENT_KINDS], ['co-miss', 'independent-catch']);
  // A defect both lineages CATCH is not an informative correlation event (skipped, not recorded).
  const led = recordRun(emptyLedger(), [{ defectId: 'x', byLineage: { a: 'catch', b: 'catch' } }]);
  assert.equal(Object.keys(led.pairs).length, 0);
});

// ── done-when (b): the estimator ARITHMETICALLY round-trips a seeded ρ within tolerance T ────────────

test('(b) the ρ̂ estimator round-trips a seeded ρ within the pre-registered tolerance T (ARITHMETIC)', () => {
  // IMPORTANT (the honesty line, A5): this is an ARITHMETIC round-trip — it proves only that the
  // estimator inverts its OWN definition ρ̂ = co_miss / (co_miss + independent_catch). It does NOT
  // validate ρ̂ against real reviewer correlation. Real calibration is against the planted-CBS fixture's
  // KNOWN co-miss events (FIXTURE-SPEC §2), never the live ledger's self-reported catches.
  const N = 100; // ≥ N_min, and large enough that integer-count rounding error is ≪ T
  for (const rho of [0.0, 0.05, 0.2, 0.4, 0.5, 0.75, 0.9]) {
    const coMiss = Math.round(rho * N);
    const ledger = seedPair(emptyLedger(), 'claude', 'gpt', coMiss, N - coMiss);
    const est = estimateRho(ledger, { N_min });
    assert.equal(est.estimated, true, `n=${N} ≥ N_min must estimate`);
    assert.equal(est.n, N);
    assert.ok(Math.abs(est.rhoHat - rho) <= T, `round-trip ρ=${rho} → ρ̂=${est.rhoHat} must be within ±${T}`);
  }
});

test('(b) the estimator pools across pairs and exposes a per-pair breakout', () => {
  const ledger = emptyLedger();
  seedPair(ledger, 'a', 'b', 30, 10); // ρ̂ pair = 0.75
  seedPair(ledger, 'a', 'c', 10, 50); // ρ̂ pair = 0.1667
  const est = estimateRho(ledger, { N_min });
  assert.equal(est.coMiss, 40);
  assert.equal(est.independentCatch, 60);
  assert.equal(est.n, 100);
  assert.equal(est.rhoHat, 0.4); // pooled 40/100
  assert.equal(est.byPair[pairKey('a', 'b')].rhoHat, 0.75);
});

// ── done-when (c): MONOTONE-SAFETY — no ρ̂ EVER loosens the quorum below the static floor ────────────

test('(c) MONOTONE-SAFETY: requiredQuorum(ρ̂) ≥ static floor for EVERY ρ̂, and is non-decreasing', () => {
  // The floor is a module CONSTANT (a reserved code change to lower), not a ledger-tunable value.
  assert.equal(STATIC_QUORUM_FLOOR, 2);

  // Sweep the whole real line plus the pathological values a corrupt/coerced ρ̂ could take. NONE may
  // ever drop the required quorum below the floor — loosening is impossible by construction.
  const pathological = [null, undefined, NaN, Infinity, -Infinity, -1, -0.5, 0, 1, 1.5, 100];
  for (const r of pathological) {
    assert.ok(requiredQuorum(r) >= STATIC_QUORUM_FLOOR, `ρ̂=${String(r)} must NOT loosen below the floor`);
  }
  const grid = [];
  for (let r = 0; r < 1; r += 0.02) grid.push(Number(r.toFixed(2)));
  let prev = -Infinity;
  for (const r of grid) {
    const req = requiredQuorum(r);
    assert.ok(req >= STATIC_QUORUM_FLOOR, `ρ̂=${r} dropped below the floor`);
    assert.ok(req >= prev, `requiredQuorum must be non-decreasing in ρ̂ (broke at ${r})`);
    prev = req;
  }
  // And the tightening is REAL, not a no-op that always returns the floor: high correlation demands more.
  assert.ok(requiredQuorum(0.9) > requiredQuorum(0.5), 'higher ρ̂ must require MORE origins (real tightening)');
  assert.ok(requiredQuorum(0.5) > STATIC_QUORUM_FLOOR, 'ρ̂=0.5 must tighten above the floor');
});

test('(c) the LEARNED quorum never reports met with fewer origins than the static floor demands', () => {
  // One lineage = one origin. NO ledger / ρ̂ can make a single origin meet the ≥2 floor.
  for (const seed of [
    () => emptyLedger(), // cold start
    () => seedPair(emptyLedger(), 'a', 'b', 80, 20), // high ρ̂ (tightens further)
    () => seedPair(emptyLedger(), 'a', 'b', 0, 100), // ρ̂ = 0 (floor)
  ]) {
    const lq = learnedQuorum([{ lineage: 'claude' }, { lineage: 'claude' }], { ledger: seed() });
    assert.equal(lq.origins, 1, 'same-lineage agreement is ONE origin (I3, invariant under any ρ̂)');
    assert.equal(lq.met, false, 'a single origin can NEVER meet the floor, whatever ρ̂ says');
    assert.ok(lq.required >= STATIC_QUORUM_FLOOR);
    assert.equal(lq.staticRequired, STATIC_QUORUM_FLOOR);
  }
  // Two DISTINCT origins meet the floor at ρ̂≈0, but a high ρ̂ TIGHTENS the bar above 2 ⇒ no longer met.
  const reviewers = [{ lineage: 'claude' }, { lineage: 'gemini' }];
  const lqLow = learnedQuorum(reviewers, { ledger: seedPair(emptyLedger(), 'a', 'b', 0, 100) });
  assert.deepEqual([lqLow.origins, lqLow.required, lqLow.met], [2, 2, true]);
  const lqHigh = learnedQuorum(reviewers, { ledger: seedPair(emptyLedger(), 'a', 'b', 80, 20) });
  assert.equal(lqHigh.origins, 2);
  assert.ok(lqHigh.required > 2, 'ρ̂=0.8 tightens the bar above 2');
  assert.equal(lqHigh.met, false, 'tightening can only make the bar HARDER to meet, never looser');
});

// ── done-when (d): ρ̂ is stamped a "censored lower-bound" in the run output (A5) ──────────────────────

test('(d) an estimated ρ̂ is stamped a CENSORED LOWER BOUND in the run output (A5)', () => {
  const ledger = seedPair(emptyLedger(), 'claude', 'gpt', 30, 70);
  const v = calibrationVerdict({ reviewers: [{ lineage: 'claude' }, { lineage: 'gpt' }], useLedger: true, ledger });
  assert.equal(v.rho_hat_kind, 'censored-lower-bound');
  assert.equal(v.stamp, RHO_CENSORED_STAMP);
  assert.match(v.stamp, /CENSORED LOWER BOUND/);
  assert.match(v.stamp, /only TIGHTEN/);
  assert.equal(typeof v.rho_hat, 'number');
});

// ── done-when (e): I8 reproducibility — stamps + identical replay; default mode is pure-of-inputs ────

test('(e) the ledger-mode verdict stamps the ledger hash, the derived threshold, and the static baseline', () => {
  const ledger = seedPair(emptyLedger(), 'claude', 'gemini', 60, 40); // ρ̂ = 0.6 ⇒ required = ceil(2/0.4) = 5
  const reviewers = [{ lineage: 'claude' }, { lineage: 'gemini' }];
  const v = calibrationVerdict({ reviewers, useLedger: true, ledger });

  assert.equal(v.ledger_used, true);
  assert.equal(v.ledger_hash, ledgerHash(ledger), 'stamps the exact ledger hash (binds the ledger into the replay key)');
  assert.equal(v.required, 5, 'the DERIVED (learned) threshold from ρ̂=0.6');
  assert.equal(v.static_would_require, STATIC_QUORUM_FLOOR, 'stamps what the STATIC rule alone would have required');
  assert.ok(v.required > v.static_would_require, 'the learned bar tightened above the static one');
  assert.equal(v.met, false, '2 origins < the learned requirement of 5');
});

test('(e) I8 replay: the SAME (inputs + ledger) yields an IDENTICAL verdict; a changed ledger changes the hash', () => {
  const reviewers = [{ lineage: 'claude' }, { lineage: 'gemini' }];
  const ledgerA = seedPair(emptyLedger(), 'claude', 'gemini', 30, 70);
  const v1 = calibrationVerdict({ reviewers, useLedger: true, ledger: ledgerA });
  const v2 = calibrationVerdict({ reviewers, useLedger: true, ledger: ledgerA });
  assert.deepEqual(v1, v2, 'replay with the same inputs + ledger is byte-identical (I8 reproducibility)');

  // The ledger hash actually BINDS the ledger: appending an event changes the hash (and the replay key).
  const ledgerB = seedPair(emptyLedger(), 'claude', 'gemini', 31, 70);
  const v3 = calibrationVerdict({ reviewers, useLedger: true, ledger: ledgerB });
  assert.notEqual(v3.ledger_hash, v1.ledger_hash, 'a changed ledger MUST change the stamped hash');

  // And the on-disk round-trip preserves the hash (the canonical hash is stable across save/load).
  const file = tmpFile('hash');
  try {
    saveLedger(ledgerA, file);
    assert.equal(ledgerHash(loadLedger(file)), v1.ledger_hash, 'persisted-then-reloaded ledger hashes identically');
  } finally {
    fs.rmSync(file, { force: true });
  }
});

test('(e) DEFAULT mode: the ledger is DISABLED and the verdict is a PURE function of inputs', () => {
  const reviewers = [{ lineage: 'claude' }, { lineage: 'gemini' }];
  const v = calibrationVerdict({ reviewers, useLedger: false });
  assert.equal(v.ledger_used, false);
  assert.equal(v.rho_hat, null);
  assert.equal(v.ledger_hash, null, 'default mode consults no ledger ⇒ no ledger hash');
  assert.deepEqual([v.origins, v.required, v.met], [2, STATIC_QUORUM_FLOOR, true]);

  // Pure function of inputs: the verdict is identical regardless of any ledger, because the ledger is
  // never read in default mode. Two DIFFERENT ledgers ⇒ the SAME default verdict.
  const withBigLedger = calibrationVerdict({ reviewers, useLedger: false, ledger: seedPair(emptyLedger(), 'a', 'b', 99, 1) });
  assert.deepEqual(withBigLedger, v, 'default mode ignores the ledger entirely (pure-of-inputs)');
});

// ── Given/Then: prior data below N_min (or none) ⇒ static ≥2 rule + "ρ unestimated" (never fabricate) ─

test('cold start: below N_min (or empty) it falls back to the static ≥2 rule and stamps "ρ unestimated"', () => {
  // No data at all.
  const empty = estimateRho(emptyLedger(), { N_min });
  assert.equal(empty.rhoHat, null, 'never fabricates a ρ̂ from zero samples');
  assert.equal(empty.estimated, false);
  assert.equal(empty.stamp, RHO_UNESTIMATED_STAMP);
  assert.match(empty.reason, /n<N_min/);

  // Just BELOW the committed floor — still unestimated (the boundary is honoured exactly).
  const below = estimateRho(seedPair(emptyLedger(), 'a', 'b', 1, N_min - 2), { N_min });
  assert.equal(below.n, N_min - 1);
  assert.equal(below.estimated, false, `n=${N_min - 1} < N_min=${N_min} must NOT estimate`);

  // Exactly AT the floor — now estimable.
  const at = estimateRho(seedPair(emptyLedger(), 'a', 'b', 1, N_min - 1), { N_min });
  assert.equal(at.n, N_min);
  assert.equal(at.estimated, true, `n=${N_min} == N_min must estimate`);

  // The run verdict in the cold-start case uses the STATIC floor and carries the unestimated stamp.
  const v = calibrationVerdict({ reviewers: [{ lineage: 'a' }, { lineage: 'b' }], useLedger: true, ledger: emptyLedger() });
  assert.equal(v.required, STATIC_QUORUM_FLOOR, 'cold start ⇒ the static ≥2 rule');
  assert.equal(v.rho_hat, null);
  assert.equal(v.estimated, false);
  assert.equal(v.stamp, RHO_UNESTIMATED_STAMP);
  assert.equal(v.met, true, 'two distinct origins still meet the static floor at cold start');
});

// ── Given/Then: the learning layer adds BOUNDED overhead (fires ZERO sub-agents) ─────────────────────

test('overhead: a ledger read/write run adds ZERO sub-agent calls and ≤ the stated IO bound', () => {
  const file = tmpFile('overhead');
  try {
    // Persist a real (high-stakes-sized) ledger first, then run a calibration that READS it.
    saveLedger(seedPair(emptyLedger(), 'claude', 'gemini', 50, 50), file);
    const { verdict, overhead } = runCalibration({
      reviewers: [{ lineage: 'claude' }, { lineage: 'gemini' }],
      useLedger: true,
      ledgerFile: file,
    });
    // The load-bearing cost (sub-agent calls) is ZERO — the learning layer is pure arithmetic + small IO.
    assert.equal(overhead.agentCalls, 0);
    assert.ok(overhead.agentCalls <= LEARNED_QUORUM_OVERHEAD.maxAgentCalls);
    assert.ok(overhead.ledgerReads <= LEARNED_QUORUM_OVERHEAD.maxLedgerReads, 'at most one ledger read per run');
    assert.ok(overhead.ledgerWrites <= LEARNED_QUORUM_OVERHEAD.maxLedgerWrites, 'at most one ledger write per run');
    assert.equal(verdict.ledger_used, true);

    // Default mode touches NO file at all (zero reads, zero writes, zero agents).
    const def = runCalibration({ reviewers: [{ lineage: 'claude' }, { lineage: 'gemini' }], useLedger: false });
    assert.deepEqual(def.overhead, { agentCalls: 0, ledgerReads: 0, ledgerWrites: 0 });
  } finally {
    fs.rmSync(file, { force: true });
  }
});

// ── corruption discipline: a present-but-broken ledger surfaces (never reads as a clean cold start) ──

test('loadLedger: ENOENT ⇒ empty cold-start ledger, but a present-but-malformed file SURFACES', () => {
  const missing = tmpFile('missing');
  fs.rmSync(missing, { force: true });
  assert.deepEqual(loadLedger(missing), emptyLedger(), 'an absent ledger is an honest empty cold start');

  const broken = tmpFile('broken');
  try {
    fs.writeFileSync(broken, '{ not json');
    assert.throws(() => loadLedger(broken), /not valid JSON/, 'a malformed ledger must not read as a clean cold start');
    fs.writeFileSync(broken, JSON.stringify({ no_pairs: true }));
    assert.throws(() => loadLedger(broken), /unexpected shape/);
  } finally {
    fs.rmSync(broken, { force: true });
  }
});
