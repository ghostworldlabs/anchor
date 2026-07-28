// Wave 4 — F3: SMT BOUNDED-FAITHFULNESS (z3) — the second half of the ATOMIC OBSERVED lift.
//
// Two tiers, per the build-gate isolation contract (DESCRIPTION-INC2 §v2.1/§v2.2):
//
//  * FAST tier (always runs; the Foreman `node --test test/` gate). Drives the bounded-faithfulness
//    logic + the independence-canary z3 re-run with INJECTED async `solve` stubs — NO z3, cannot hang —
//    keyed off the FAITHFULNESS_KIND marker the builders embed in each `.smt2`. It proves the F3
//    done-when end to end:
//      - a FAITHFUL formalization (no disagreeing model + battery agrees + non-vacuous) -> FAITHFUL;
//      - a formalization of a DIFFERENT statement (a disagreeing model) -> UNFAITHFUL;
//      - z3 `unknown`/timeout on ANY query -> WITHHELD (fail-CLOSED);
//      - a VACUOUS (constant) informal predicate -> WITHHELD (no discriminating power);
//      - an out-of-z3-decidable (quantified) formalization -> WITHHELD with the envelope reason code;
//      - a FORGED artifact (recorded `result` the independent re-run disagrees with) -> FLAG;
//      - a cross-claim / tampered / malformed artifact -> FLAG;
//      - an un-exercised canary (no z3 re-run) -> WITHHELD;
//      - a Claude-sourced / undersized battery HARD-FAULTS (the §v2.2 artifact-keyed integrity throw).
//
//  * TOOL lane (env-gated RAMANUJAN_TOOL_TESTS=1, serial). Spawns the REAL z3 by manifest absolute
//    path and asserts the differential mechanism: a genuinely faithful formalization is FAITHFUL and a
//    genuinely unfaithful one (a different statement) is UNFAITHFUL, both canary-re-run.

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import { toolLaneSkip } from './tool-lane.mjs';
import { loadManifest } from '../src/phasef-probe.mjs';
import { formalizeEquation } from '../src/lean-certifier.mjs';
import {
  HEX64,
  SMT_ARTIFACT_FIELDS,
  BATTERY_PROVENANCE_SOURCES,
  Z3_RESULT,
  FAITHFULNESS_VERDICT,
  FAITHFULNESS_STATUS,
  DECIDABLE_LOGICS,
  OUT_OF_ENVELOPE_REASON,
  FAITHFULNESS_KIND,
  SmtFaithfulnessError,
  smt2Hash,
  isDecidableEnvelope,
  buildDifferentialSmt2,
  buildInstanceSmt2,
  buildVacuitySmt2,
  makePrngBattery,
  validateBatteryIntegrity,
  makeSmtArtifact,
  validateSmtArtifact,
  computeFaithfulness,
  certifyFaithfulness,
  adjudicateFaithfulness,
  createZ3Solve,
} from '../src/smt-faithfulness.mjs';

// ---------------------------------------------------------------------------
// Fixtures + the kind-keyed injected `solve` stub (the documented fast-tier seam).
// ---------------------------------------------------------------------------

const PINNED = loadManifest().faithfulness_instance_battery;
const PINNED_COUNT = PINNED.default_count; // 16
const DOMAIN = PINNED.bounded_domain; // { min: -64, max: 64 }
const Z3_VERSION = '4.16.0-stub';

const FAITHFUL_CLAIM = Object.freeze({
  id: 'pf::1+1=2',
  type: 'proof-bearing',
  statement: '1 + 1 = 2',
  meta: { equation: { a: 1, op: '+', b: 1, c: 2 } },
});

/** The faithful (a+b == c) query + battery the in-repo translator emits for 1+1=2. */
function faithfulQueryAndBattery() {
  const { faithfulness } = formalizeEquation(FAITHFUL_CLAIM, { domain: DOMAIN, batteryCount: PINNED_COUNT });
  return faithfulness; // { query, battery }
}

/** A DIFFERENT-statement query: informal commits to (+ 1 1) = probe, the formalization to 3 = probe. */
function unfaithfulQuery() {
  return {
    vars: ['probe'],
    smt_logic: 'QF_LIA',
    domain: DOMAIN,
    informal: '(= (+ 1 1) probe)', // the claim's stated value (2)
    formal: '(= 3 probe)', // the value a mis-formalization commits to (3) — a DIFFERENT statement
  };
}

/** Pull the embedded `; ramanujan-faithfulness-kind: <kind>` marker out of an emitted `.smt2`. */
function kindOf(smt2) {
  const m = /ramanujan-faithfulness-kind:\s*(\S+)/.exec(smt2);
  return m ? m[1] : null;
}

/** Build an async `solve(smt2)` that answers per the FAITHFULNESS_KIND marker (no z3). */
function makeSolve(byKind) {
  return async (smt2) => {
    const k = kindOf(smt2);
    if (!(k in byKind)) throw new Error(`stub solve has no canned result for kind ${JSON.stringify(k)}`);
    const r = byKind[k];
    return typeof r === 'function' ? r(smt2) : r;
  };
}

const D = FAITHFULNESS_KIND.DIFFERENTIAL;
const I = FAITHFULNESS_KIND.INSTANCE;
const VT = FAITHFULNESS_KIND.VACUITY_TRUE;
const VF = FAITHFULNESS_KIND.VACUITY_FALSE;

// no disagreeing model, every instance agrees, informal is contingent => FAITHFUL.
const faithfulSolve = makeSolve({ [D]: 'unsat', [I]: 'unsat', [VT]: 'sat', [VF]: 'sat' });
// a disagreeing model exists in the box => UNFAITHFUL (a different statement).
const unfaithfulSolve = makeSolve({ [D]: 'sat', [I]: 'unsat', [VT]: 'sat', [VF]: 'sat' });
// differential agrees, but a concrete battery instance disagrees => UNFAITHFUL.
const batteryDisagreeSolve = makeSolve({ [D]: 'unsat', [I]: 'sat', [VT]: 'sat', [VF]: 'sat' });
// z3 cannot decide the differential => WITHHELD (fail-closed).
const unknownSolve = makeSolve({ [D]: 'unknown', [I]: 'unsat', [VT]: 'sat', [VF]: 'sat' });
// agrees everywhere + battery agrees, but the informal predicate is constant (only true-able) => VACUOUS.
const vacuousSolve = makeSolve({ [D]: 'unsat', [I]: 'unsat', [VT]: 'sat', [VF]: 'unsat' });

// ===========================================================================
// FAST TIER — constants + the z3-decidable envelope.
// ===========================================================================

test('the decidable-logic set + the envelope reason code are the pinned z3-decidable envelope', () => {
  for (const lg of ['QF_LIA', 'QF_LRA', 'QF_BV']) assert.ok(DECIDABLE_LOGICS.has(lg));
  assert.match(OUT_OF_ENVELOPE_REASON, /z3-decidable envelope/);
  assert.deepEqual([...BATTERY_PROVENANCE_SOURCES].sort(), ['cross-family', 'human', 'prng', 'tool']);
  assert.ok(!BATTERY_PROVENANCE_SOURCES.has('claude'));
});

test('isDecidableEnvelope accepts a QF arithmetic query and REJECTS a quantified one (the mathlib follow-on)', () => {
  const { query } = faithfulQueryAndBattery();
  assert.equal(isDecidableEnvelope(query), true);
  assert.equal(isDecidableEnvelope({ ...query, smt_logic: 'LIA' }), false); // not quantifier-free
  assert.equal(isDecidableEnvelope({ ...query, informal: '(exists ((p Int)) (= p probe))' }), false); // quantified token
});

// ===========================================================================
// FAST TIER — the .smt2 builders (bounded, QF — decidable by construction).
// ===========================================================================

test('buildDifferentialSmt2 asserts (xor informal formal), bounds the vars, and stamps its kind', () => {
  const { query } = faithfulQueryAndBattery();
  const smt2 = buildDifferentialSmt2(query);
  assert.equal(kindOf(smt2), FAITHFULNESS_KIND.DIFFERENTIAL);
  assert.match(smt2, /\(set-logic QF_LIA\)/);
  assert.match(smt2, /\(xor \(and \(= \(\+ 1 1\) 2\) \(= probe 2\)\) \(and \(= \(\+ 1 1\) 2\) \(= probe 2\)\)\)/);
  assert.match(smt2, /\(assert \(>= probe -64\)\)/);
  assert.match(smt2, /\(assert \(<= probe 64\)\)/);
  assert.match(smt2, /\(check-sat\)/);
});

test('buildInstanceSmt2 pins every var and buildVacuitySmt2 asserts the informal predicate (or its negation)', () => {
  const { query } = faithfulQueryAndBattery();
  const inst = buildInstanceSmt2(query, { probe: 2 });
  assert.equal(kindOf(inst), FAITHFULNESS_KIND.INSTANCE);
  assert.match(inst, /\(assert \(= probe 2\)\)/);
  assert.equal(kindOf(buildVacuitySmt2(query, true)), FAITHFULNESS_KIND.VACUITY_TRUE);
  assert.match(buildVacuitySmt2(query, false), /\(assert \(not \(and \(= \(\+ 1 1\) 2\) \(= probe 2\)\)\)\)/);
  assert.throws(() => buildInstanceSmt2(query, { probe: 1.5 }), SmtFaithfulnessError);
  assert.throws(() => buildDifferentialSmt2({ ...query, domain: { min: 5, max: 1 } }), SmtFaithfulnessError);
});

// ===========================================================================
// FAST TIER — the PRNG battery + the §v2.2 artifact-keyed integrity HARD-FAULT.
// ===========================================================================

test('makePrngBattery is a deterministic, in-domain, provenance-stamped (non-Claude) battery', () => {
  const { query } = faithfulQueryAndBattery();
  const a = makePrngBattery(query, { count: PINNED_COUNT, seed: 1 });
  const b = makePrngBattery(query, { count: PINNED_COUNT, seed: 1 });
  assert.equal(a.provenance, 'prng');
  assert.equal(a.count, PINNED_COUNT);
  assert.deepEqual(a.instances, b.instances, 'fixed seed => reproducible (no Math.random)');
  for (const inst of a.instances) {
    assert.ok(Number.isInteger(inst.probe) && inst.probe >= DOMAIN.min && inst.probe <= DOMAIN.max);
  }
});

test('validateBatteryIntegrity HARD-FAULTS on a Claude battery and on an undersized battery (artifact-keyed)', () => {
  const { query } = faithfulQueryAndBattery();
  const claude = makePrngBattery(query, { count: PINNED_COUNT, provenance: 'claude' });
  assert.throws(() => validateBatteryIntegrity(claude, PINNED_COUNT), /claude/i);
  const small = makePrngBattery(query, { count: PINNED_COUNT - 1 });
  assert.throws(() => validateBatteryIntegrity(small, PINNED_COUNT), /< pinned default/);
  const ok = makePrngBattery(query, { count: PINNED_COUNT });
  assert.deepEqual(validateBatteryIntegrity(ok, PINNED_COUNT), { provenance: 'prng', count: PINNED_COUNT });
});

// ===========================================================================
// FAST TIER — the artifact (the EXACT §v2.2 field set, battery provenance bound IN).
// ===========================================================================

test('makeSmtArtifact mints the EXACT §v2.2 field set and validateSmtArtifact shape-checks it', () => {
  const { query } = faithfulQueryAndBattery();
  const smt2 = buildDifferentialSmt2(query);
  const artifact = makeSmtArtifact({
    smt2,
    z3Version: Z3_VERSION,
    result: Z3_RESULT.UNSAT,
    batteryProvenance: 'prng',
    batteryCount: PINNED_COUNT,
    boundedDomain: query.domain,
  });
  assert.deepEqual(Object.keys(artifact).sort(), [...SMT_ARTIFACT_FIELDS].sort());
  assert.match(artifact.smt2_hash, HEX64);
  assert.equal(artifact.smt2_hash, smt2Hash(smt2));
  assert.deepEqual(artifact.bounded_domain, { min: DOMAIN.min, max: DOMAIN.max });
  assert.equal(validateSmtArtifact(artifact).ok, true);
  // a Claude provenance is rejected at the structural layer too.
  assert.equal(validateSmtArtifact({ ...artifact, battery_provenance: 'claude' }).ok, false);
});

// ===========================================================================
// FAST TIER — computeFaithfulness (the shared bounded check, all verdicts).
// ===========================================================================

test('computeFaithfulness: FAITHFUL when no disagreeing model, battery agrees, and the informal is contingent', async () => {
  const { query, battery } = faithfulQueryAndBattery();
  const r = await computeFaithfulness(query, battery, faithfulSolve);
  assert.equal(r.verdict, FAITHFULNESS_VERDICT.FAITHFUL);
  assert.equal(r.differentialResult, Z3_RESULT.UNSAT);
});

test('computeFaithfulness: UNFAITHFUL on a disagreeing model (a DIFFERENT statement) — no green proof of a wrong statement', async () => {
  const { query, battery } = faithfulQueryAndBattery();
  const r = await computeFaithfulness(query, battery, unfaithfulSolve);
  assert.equal(r.verdict, FAITHFULNESS_VERDICT.UNFAITHFUL);
  assert.equal(r.differentialResult, Z3_RESULT.SAT);
});

test('computeFaithfulness: UNFAITHFUL when a concrete battery instance disagrees (necessary-not-sufficient)', async () => {
  const { query, battery } = faithfulQueryAndBattery();
  const r = await computeFaithfulness(query, battery, batteryDisagreeSolve);
  assert.equal(r.verdict, FAITHFULNESS_VERDICT.UNFAITHFUL);
  assert.ok(Array.isArray(r.disagreements) && r.disagreements.length > 0);
});

test('computeFaithfulness: WITHHELD (fail-closed) on z3 `unknown`', async () => {
  const { query, battery } = faithfulQueryAndBattery();
  const r = await computeFaithfulness(query, battery, unknownSolve);
  assert.equal(r.verdict, FAITHFULNESS_VERDICT.WITHHELD);
  assert.match(r.reason, /unknown|fail-closed/i);
});

test('computeFaithfulness: WITHHELD on a VACUOUS informal predicate (no discriminating power)', async () => {
  const { query, battery } = faithfulQueryAndBattery();
  const r = await computeFaithfulness(query, battery, vacuousSolve);
  assert.equal(r.verdict, FAITHFULNESS_VERDICT.WITHHELD);
  assert.equal(r.vacuous, true);
});

test('computeFaithfulness: WITHHELD with the envelope reason code on an out-of-z3-decidable (quantified) query', async () => {
  const battery = makePrngBattery({ ...unfaithfulQuery() }, { count: PINNED_COUNT });
  const out = { ...unfaithfulQuery(), informal: '(exists ((p Int)) (= p probe))' };
  const r = await computeFaithfulness(out, battery, faithfulSolve);
  assert.equal(r.verdict, FAITHFULNESS_VERDICT.WITHHELD);
  assert.equal(r.reason, OUT_OF_ENVELOPE_REASON);
  assert.equal(r.outOfEnvelope, true);
});

// ===========================================================================
// FAST TIER — certifyFaithfulness (the producer) + adjudicateFaithfulness (the canary).
// ===========================================================================

async function faithfulRecord({ producerSolve = faithfulSolve } = {}) {
  const { query, battery } = faithfulQueryAndBattery();
  return certifyFaithfulness(
    { claim: FAITHFUL_CLAIM, query, battery, z3Version: Z3_VERSION, pinnedDefaultCount: PINNED_COUNT },
    { solve: producerSolve },
  );
}

test('certifyFaithfulness mints a re-executable record bound to the claim; its differential self-hashes', async () => {
  const record = await faithfulRecord();
  assert.equal(record.claim_id, FAITHFUL_CLAIM.id);
  assert.equal(record.artifact.result, Z3_RESULT.UNSAT);
  assert.equal(record.artifact.battery_provenance, 'prng');
  assert.equal(record.artifact.battery_count, PINNED_COUNT);
  assert.equal(smt2Hash(record.differential_smt2), record.artifact.smt2_hash);
});

test('certifyFaithfulness HARD-FAULTS on a Claude / undersized battery (the §v2.2 integrity throw)', async () => {
  const { query } = faithfulQueryAndBattery();
  const claude = makePrngBattery(query, { count: PINNED_COUNT, provenance: 'claude' });
  await assert.rejects(
    () => certifyFaithfulness({ claim: FAITHFUL_CLAIM, query, battery: claude, z3Version: Z3_VERSION, pinnedDefaultCount: PINNED_COUNT }, { solve: faithfulSolve }),
    /claude/i,
  );
});

test('adjudicateFaithfulness: FAITHFUL on a genuine record whose independent z3 re-run agrees', async () => {
  const record = await faithfulRecord();
  const r = await adjudicateFaithfulness({ record, claim: FAITHFUL_CLAIM, z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(r.status, FAITHFULNESS_STATUS.FAITHFUL);
  assert.equal(r.ok, true);
});

test('adjudicateFaithfulness: UNFAITHFUL when the independent re-run finds a disagreeing model', async () => {
  // honest producer records the disagreement (sat); the canary re-run agrees it disagrees.
  const record = await faithfulRecord({ producerSolve: unfaithfulSolve });
  const r = await adjudicateFaithfulness({ record, claim: FAITHFUL_CLAIM, z3Rerun: unfaithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(r.status, FAITHFULNESS_STATUS.UNFAITHFUL);
});

test('adjudicateFaithfulness: WITHHELD (fail-closed) when z3 returns `unknown` (producer + canary agree it is undecided)', async () => {
  // the producer honestly records `unknown`; the independent re-run also returns `unknown` => fail-closed
  // (a producer that recorded `unsat` while the re-run says `unknown` is a FORGERY — tested separately).
  const record = await faithfulRecord({ producerSolve: unknownSolve });
  assert.equal(record.artifact.result, Z3_RESULT.UNKNOWN);
  const r = await adjudicateFaithfulness({ record, claim: FAITHFUL_CLAIM, z3Rerun: unknownSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(r.status, FAITHFULNESS_STATUS.WITHHELD);
});

test('adjudicateFaithfulness: a FORGED `result` (re-run disagrees with the recorded one) is FLAGged', async () => {
  // the producer LIES that the differential is unsat (faithful); the independent re-run says sat.
  const record = await faithfulRecord({ producerSolve: faithfulSolve });
  assert.equal(record.artifact.result, Z3_RESULT.UNSAT);
  const r = await adjudicateFaithfulness({ record, claim: FAITHFUL_CLAIM, z3Rerun: unfaithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(r.status, FAITHFULNESS_STATUS.FLAG);
  assert.match(r.reason, /forged|re-run/i);
});

test('adjudicateFaithfulness: an un-exercised canary (no z3 re-run) WITHHOLDS the lift (a stub is treated as unrun)', async () => {
  const record = await faithfulRecord();
  const r = await adjudicateFaithfulness({ record, claim: FAITHFUL_CLAIM, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(r.status, FAITHFULNESS_STATUS.WITHHELD);
  assert.match(r.reason, /canary|re-run|stubbed/i);
});

test('adjudicateFaithfulness: a cross-claim record and a tampered .smt2 are both FLAGged', async () => {
  const record = await faithfulRecord();
  const cross = await adjudicateFaithfulness({ record, claim: { ...FAITHFUL_CLAIM, id: 'pf::other' }, z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(cross.status, FAITHFULNESS_STATUS.FLAG);
  assert.match(cross.reason, /cross-claim|bound|replay/i);

  const tampered = { ...record, differential_smt2: `${record.differential_smt2}; smuggled\n` };
  const t = await adjudicateFaithfulness({ record: tampered, claim: FAITHFUL_CLAIM, z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(t.status, FAITHFULNESS_STATUS.FLAG);
  assert.match(t.reason, /smt2_hash|tamper/i);
});

test('adjudicateFaithfulness: a record whose query does NOT rebuild to its stored .smt2 is FLAGged (canary re-run source binding)', async () => {
  // Forge a record that is INTERNALLY self-consistent (the stored differential_smt2 hashes to the artifact
  // smt2_hash) yet whose `query` encodes a DIFFERENT differential than the stored one. The canary re-runs
  // from `query`, so the source it would feed z3 differs from the hash-verified `.smt2` — it must FLAG,
  // never silently re-run a different query than the one whose `.smt2` was attested.
  const record = await faithfulRecord();
  const otherDifferential = buildDifferentialSmt2(unfaithfulQuery()); // a DIFFERENT, self-consistent .smt2
  const forged = {
    ...record,
    differential_smt2: otherDifferential, // stored .smt2 swapped...
    artifact: { ...record.artifact, smt2_hash: smt2Hash(otherDifferential) }, // ...and its hash updated to match
  };
  const r = await adjudicateFaithfulness({ record: forged, claim: FAITHFUL_CLAIM, z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(r.status, FAITHFULNESS_STATUS.FLAG);
  assert.match(r.reason, /rebuild|source mismatch/i);
});

test('adjudicateFaithfulness: a malformed artifact FLAGs and re-checks battery integrity (HARD-FAULT on a smuggled Claude battery)', async () => {
  const bad = await adjudicateFaithfulness({ record: { artifact: { smt2_hash: 'nope' } }, claim: FAITHFUL_CLAIM, z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(bad.status, FAITHFULNESS_STATUS.FLAG);

  const record = await faithfulRecord();
  const smuggled = { ...record, battery: { ...record.battery, provenance: 'claude' } };
  await assert.rejects(
    () => adjudicateFaithfulness({ record: smuggled, claim: FAITHFUL_CLAIM, z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT }),
    /claude/i,
  );
});

test('adjudicateFaithfulness: an out-of-envelope (quantified) record WITHHOLDS with the envelope reason code', async () => {
  const q = { ...unfaithfulQuery(), informal: '(exists ((p Int)) (= p probe))' };
  const battery = makePrngBattery({ ...unfaithfulQuery() }, { count: PINNED_COUNT });
  const record = await certifyFaithfulness({ claim: FAITHFUL_CLAIM, query: q, battery, z3Version: Z3_VERSION, pinnedDefaultCount: PINNED_COUNT }, { solve: faithfulSolve });
  assert.equal(record.artifact.result, null); // never run z3 on an out-of-envelope query
  const r = await adjudicateFaithfulness({ record, claim: FAITHFUL_CLAIM, z3Rerun: faithfulSolve, pinnedDefaultCount: PINNED_COUNT });
  assert.equal(r.status, FAITHFULNESS_STATUS.WITHHELD);
  assert.equal(r.outOfEnvelope, true);
  assert.equal(r.reason, OUT_OF_ENVELOPE_REASON);
});

// ===========================================================================
// TOOL LANE — env-gated, serial, against the REAL z3 (manifest absolute path).
// ===========================================================================

describe('F3 tool lane (real z3 differential faithfulness)', { skip: toolLaneSkip(), concurrency: 1 }, () => {
  const manifest = loadManifest();
  const z3 = manifest.tools.z3;
  const solve = createZ3Solve(z3.path, { timeoutMs: 60000 });
  // createZ3Solve returns { result }; adjudicate accepts that shape directly as the z3Rerun.

  test('a genuinely FAITHFUL formalization (1+1=2) is FAITHFUL under the real z3', { timeout: 120000 }, async () => {
    const { query, battery } = faithfulQueryAndBattery();
    const record = await certifyFaithfulness(
      { claim: FAITHFUL_CLAIM, query, battery, z3Version: z3.version, pinnedDefaultCount: PINNED_COUNT },
      { solve },
    );
    const r = await adjudicateFaithfulness({ record, claim: FAITHFUL_CLAIM, z3Rerun: solve, pinnedDefaultCount: PINNED_COUNT });
    assert.equal(r.status, FAITHFULNESS_STATUS.FAITHFUL, r.reason);
  });

  test('a genuinely UNFAITHFUL formalization (a DIFFERENT statement) is UNFAITHFUL under the real z3', { timeout: 120000 }, async () => {
    const query = unfaithfulQuery();
    const battery = makePrngBattery(query, { count: PINNED_COUNT });
    const record = await certifyFaithfulness(
      { claim: FAITHFUL_CLAIM, query, battery, z3Version: z3.version, pinnedDefaultCount: PINNED_COUNT },
      { solve },
    );
    const r = await adjudicateFaithfulness({ record, claim: FAITHFUL_CLAIM, z3Rerun: solve, pinnedDefaultCount: PINNED_COUNT });
    assert.equal(r.status, FAITHFULNESS_STATUS.UNFAITHFUL, r.reason);
  });
});
