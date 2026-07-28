// Wave 24 — Gradeable oracle, part A: fixture corpus + red-team set (E1a).
//
// Exercises the REAL Wave-24 corpus (src/oracle-corpus.mjs) against the REAL spine, proving the
// done-when:
//
//   the corpus LOADS; every fixture is LABELED with its `class` + `expected_verdict`; and the red-team
//   forged-artifact / cross-claim / same-claim / across-restart replay / crash-mid-mint attempts are
//   each PRESENT and individually asserted as MUST-reject by the spine.
//
// The defining Given/When/Then: given the red-team set, when E1a's assertions run, then the
// forged-artifact, cross-claim, same-claim, across-restart replay, and crash-mid-mint fixtures are each
// rejected by the P9 adjudication spine.
//
// We also pin the i–xiv union (6 planted-defect classes × ≥3 instances + the FIXED 6-fixture SOUND
// subset + the ref-fn-independence / forged-unfaithful-definition / abstain-payload singletons + the A4
// laundering / recall rosters) and spot-check (cheaply, in-process — no subprocess spawned) that each
// planted defect is GENUINELY a defect and each sound fixture is GENUINELY sound (non-vacuity).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  ORACLE_VERDICT,
  ORACLE_VERDICT_VALUES,
  DEFECT_CLASSES,
  CORPUS_CLASSES,
  RED_TEAM_ATTACKS,
  SUBSET,
  SOUND_SUBSET_CARDINALITY,
  loadCorpus,
  flattenCorpus,
  trueResultOf,
  resultsEqual,
  runRedTeam,
  RED_TEAM_RUNNERS,
  computationalDefectIsReal,
  soundFixtureIsConsistent,
  dimensionalDefectIsCaught,
  convergenceDefectIsCaught,
  comprehensionDefectIsCaught,
  firewallInapplicableIsCaught,
  forgedUnfaithfulIsCaught,
  abstainPayloadIsHonest,
} from '../src/oracle-corpus.mjs';

import { loadDurabilitySubstrate } from '../src/adjudication.mjs';
import { LAUNDERING_BATTERY } from '../src/firewall-grammar.mjs';
import { POSITIVE_RECALL_ROSTER } from '../src/firewall-subprocess.mjs';

// =====================================================================================
// 0. The label vocabulary + the class / attack rosters are pinned + frozen.
// =====================================================================================

test('E1a vocabulary: ORACLE_VERDICT carries the six honest labels and is frozen', () => {
  assert.deepEqual([...ORACLE_VERDICT_VALUES].sort(), ['ABSTAIN', 'CAP_CLAIMED', 'CATCH', 'REJECT', 'REQUIRES_PHASE_F', 'SETTLE']);
  assert.ok(Object.isFrozen(ORACLE_VERDICT));
});

test('E1a vocabulary: the 6 planted-defect classes are exactly the R1 set', () => {
  assert.deepEqual(
    [...DEFECT_CLASSES].sort(),
    ['comprehension-narrative', 'convergence-stability', 'derivation-error', 'dimensional', 'firewall-inapplicable', 'off-by-one'],
  );
  assert.equal(DEFECT_CLASSES.length, 6);
  assert.ok(Object.isFrozen(DEFECT_CLASSES));
});

test('E1a vocabulary: the five named red-team attacks are pinned + frozen', () => {
  assert.deepEqual(
    [...RED_TEAM_ATTACKS].sort(),
    ['across-restart-replay', 'crash-mid-mint', 'cross-claim-replay', 'forged-artifact', 'same-claim-replay'],
  );
  assert.equal(RED_TEAM_ATTACKS.length, 5);
  assert.ok(Object.isFrozen(RED_TEAM_ATTACKS));
});

// =====================================================================================
// 1. THE CORPUS LOADS + every fixture is LABELED with its class + expected verdict (the done-when).
// =====================================================================================

test('done-when: the corpus loads (a frozen, fully-assembled structure)', () => {
  const corpus = loadCorpus();
  assert.ok(corpus && typeof corpus === 'object');
  assert.ok(Object.isFrozen(corpus));
  assert.ok(corpus.defects && corpus.sound && corpus.rosters && corpus.redTeam);
  for (const klass of DEFECT_CLASSES) assert.ok(Array.isArray(corpus.defects[klass]), `defects.${klass} present`);
});

test('done-when: EVERY fixture is labeled with a known class + a known expected_verdict + a subset', () => {
  const flat = flattenCorpus();
  assert.ok(flat.length > 0, 'corpus is non-empty');
  for (const f of flat) {
    assert.ok(typeof f.id === 'string' && f.id.length > 0, `fixture has an id: ${JSON.stringify(f)}`);
    assert.ok(CORPUS_CLASSES.includes(f.class) || f.class === 'red-team', `fixture ${f.id} has a known class (got ${f.class})`);
    assert.ok(ORACLE_VERDICT_VALUES.includes(f.expected_verdict), `fixture ${f.id} has a known expected_verdict (got ${f.expected_verdict})`);
    assert.ok(Object.values(SUBSET).includes(f.subset), `fixture ${f.id} has a known subset (got ${f.subset})`);
  }
});

test('done-when: fixture ids are unique across the whole corpus', () => {
  const flat = flattenCorpus();
  const ids = flat.map((f) => f.id);
  assert.equal(new Set(ids).size, ids.length, 'no duplicate fixture ids');
});

// =====================================================================================
// 2. THE i–xiv UNION — the 6 planted-defect classes × ≥3 instances, all in the SCORED subset.
// =====================================================================================

test('union: each of the 6 planted-defect classes has ≥3 instances, all labeled CATCH in the SCORED subset', () => {
  const corpus = loadCorpus();
  for (const klass of DEFECT_CLASSES) {
    const fixtures = corpus.defects[klass];
    assert.ok(fixtures.length >= 3, `class ${klass} has ≥3 instances (got ${fixtures.length})`);
    for (const f of fixtures) {
      assert.equal(f.class, klass);
      assert.equal(f.expected_verdict, ORACLE_VERDICT.CATCH, `${f.id} is a CATCH`);
      assert.equal(f.subset, SUBSET.SCORED, `${f.id} is in the scored subset`);
    }
  }
});

test('union: the FIXED 6-fixture SOUND subset is exactly 6, all SETTLE, in the SOUND subset (the FP/k′ term)', () => {
  const corpus = loadCorpus();
  assert.equal(corpus.sound.length, SOUND_SUBSET_CARDINALITY);
  assert.equal(corpus.sound.length, 6);
  for (const f of corpus.sound) {
    assert.equal(f.class, 'sound');
    assert.equal(f.expected_verdict, ORACLE_VERDICT.SETTLE);
    assert.equal(f.subset, SUBSET.SOUND);
  }
});

test('union: the ref-fn-independence, forged-unfaithful-definition, and abstain-payload singletons are present + labeled', () => {
  const corpus = loadCorpus();
  assert.equal(corpus.refFnIndependence.class, 'ref-fn-independence');
  assert.equal(corpus.refFnIndependence.expected_verdict, ORACLE_VERDICT.CAP_CLAIMED);
  assert.equal(corpus.forgedUnfaithfulDefinition.class, 'forged-unfaithful-definition');
  assert.equal(corpus.forgedUnfaithfulDefinition.expected_verdict, ORACLE_VERDICT.REQUIRES_PHASE_F);
  assert.equal(corpus.abstainPayload.class, 'abstain-payload');
  assert.equal(corpus.abstainPayload.expected_verdict, ORACLE_VERDICT.ABSTAIN);
});

test('union: the A4 laundering + recall rosters are composed verbatim from Wave 8 / Wave 9 (not re-built)', () => {
  const corpus = loadCorpus();
  assert.equal(corpus.rosters.laundering.length, LAUNDERING_BATTERY.length);
  assert.ok(corpus.rosters.laundering.length >= 8, 'the laundering battery has ≥8 smuggles');
  for (const f of corpus.rosters.laundering) {
    assert.equal(f.class, 'firewall-laundering');
    assert.equal(f.expected_verdict, ORACLE_VERDICT.CATCH);
  }
  assert.equal(corpus.rosters.recall.length, POSITIVE_RECALL_ROSTER.length);
  assert.ok(corpus.rosters.recall.length >= 8, 'the recall roster has ≥8 computations');
  for (const f of corpus.rosters.recall) {
    assert.equal(f.class, 'firewall-recall');
    assert.equal(f.expected_verdict, ORACLE_VERDICT.SETTLE);
  }
});

// =====================================================================================
// 3. NON-VACUITY — each planted defect is GENUINELY a defect; each sound fixture is GENUINELY sound.
//    (All checks are in-process / pure — no firewall subprocess is spawned.)
// =====================================================================================

test('non-vacuity: every derivation-error + off-by-one fixture asserts a result ≠ its true (re-executed) value', () => {
  const corpus = loadCorpus();
  for (const klass of ['derivation-error', 'off-by-one']) {
    for (const f of corpus.defects[klass]) {
      assert.ok(computationalDefectIsReal(f), `${f.id}: asserted ${JSON.stringify(f.asserted_result)} must differ from true ${JSON.stringify(trueResultOf(f.expr))}`);
    }
  }
});

test('non-vacuity: every sound fixture asserts EXACTLY its true (re-executed) value', () => {
  for (const f of loadCorpus().sound) {
    assert.ok(soundFixtureIsConsistent(f), `${f.id}: asserted ${JSON.stringify(f.asserted_result)} must equal true ${JSON.stringify(trueResultOf(f.expr))}`);
  }
});

test('non-vacuity: every dimensional defect is REFUSED by the firewall builder (violated dimensional anchor)', () => {
  for (const f of loadCorpus().defects.dimensional) {
    assert.ok(dimensionalDefectIsCaught(f), `${f.id} must be REFUSED (rung_cap UNVERIFIED)`);
  }
});

test('non-vacuity: every convergence-stability defect is ABANDONed by CONTROL, claim left UNVERIFIED', () => {
  for (const f of loadCorpus().defects['convergence-stability']) {
    assert.ok(convergenceDefectIsCaught(f), `${f.id} must ABANDON and leave the claim UNVERIFIED`);
  }
});

test('non-vacuity: every comprehension-narrative defect resolves to NOT firewall-applicable (never the VERIFIED path)', () => {
  for (const f of loadCorpus().defects['comprehension-narrative']) {
    assert.ok(comprehensionDefectIsCaught(f), `${f.id} must classify as NOT firewall-applicable`);
  }
});

test('non-vacuity: every firewall-inapplicable defect is rejected by the closed default-deny grammar', () => {
  for (const f of loadCorpus().defects['firewall-inapplicable']) {
    assert.ok(firewallInapplicableIsCaught(f), `${f.id} must be out-of-grammar`);
  }
});

test('non-vacuity: the forged-unfaithful definition stamps requires-Phase-F and never greens (P3 advisory-only)', () => {
  assert.ok(forgedUnfaithfulIsCaught(), 'FORMALIZE must stamp requires-Phase-F / green:false / gates_promotion:false');
});

test('non-vacuity: the abstain-payload fixture ABSTAINs through the router with a well-formed advisory payload', () => {
  assert.ok(abstainPayloadIsHonest(loadCorpus().abstainPayload), 'must ABSTAIN + route with an advisory commission envelope');
});

test('non-vacuity: trueResultOf + resultsEqual are exact (bigint, no float)', () => {
  assert.ok(resultsEqual({ num: '22', den: '7' }, { num: '44', den: '14' }), 'unreduced equal rationals compare equal');
  assert.ok(!resultsEqual({ num: '1', den: '3' }, { num: '1', den: '4' }));
});

// =====================================================================================
// 4. THE RED-TEAM SET — each attack is PRESENT and individually MUST-reject by the spine (the GWT).
// =====================================================================================

// Owns one durability substrate + scratch dir for every red-team assertion in this file.
let redTeamReport = null;
let redTeamScratch = null;

test('red-team: the corpus carries all five named attacks, each labeled REJECT in the red-team subset', () => {
  const corpus = loadCorpus();
  assert.equal(corpus.redTeam.length, 5);
  const names = corpus.redTeam.map((r) => r.attack).sort();
  assert.deepEqual(names, ['across-restart-replay', 'crash-mid-mint', 'cross-claim-replay', 'forged-artifact', 'same-claim-replay']);
  for (const r of corpus.redTeam) {
    assert.equal(r.class, 'red-team');
    assert.equal(r.expected_verdict, ORACLE_VERDICT.REJECT);
    assert.equal(r.subset, SUBSET.RED_TEAM);
    assert.ok(typeof RED_TEAM_RUNNERS[r.attack] === 'function', `${r.attack} has a runner`);
  }
});

test('red-team: run the WHOLE set against the real spine (setup)', async () => {
  const substrate = await loadDurabilitySubstrate();
  redTeamScratch = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-e1a-'));
  redTeamReport = await runRedTeam({ substrate, scratchDir: redTeamScratch });
  assert.ok(redTeamReport && redTeamReport.attacks, 'red-team report produced');
});

// Each red-team attack gets its OWN MUST-reject assertion (the done-when: "each ... individually
// asserted as MUST-reject"). The GWT: each is rejected by the P9 adjudication spine (verdict ABSTAIN,
// the target claim never reaches OBSERVED).
for (const name of ['forged-artifact', 'cross-claim-replay', 'same-claim-replay', 'across-restart-replay', 'crash-mid-mint']) {
  test(`red-team GWT: the ${name} attempt is REJECTED by the spine (ABSTAIN, no lift)`, () => {
    const r = redTeamReport.attacks[name];
    assert.ok(r, `${name} ran`);
    assert.equal(r.rejected, true, `${name} must be rejected: verdict=${r.verdict}, reason=${r.reason}`);
    assert.equal(r.verdict, 'ABSTAIN', `${name} verdict must be ABSTAIN`);
  });
}

test('red-team: the replay/crash attacks are NON-VACUOUS (the artifact was genuinely usable once / the crash really fired)', () => {
  assert.equal(redTeamReport.attacks['same-claim-replay'].non_vacuous, true, 'same-claim: first presentation was VERIFIED');
  assert.equal(redTeamReport.attacks['across-restart-replay'].non_vacuous, true, 'restart: first presentation was VERIFIED');
  assert.equal(redTeamReport.attacks['crash-mid-mint'].non_vacuous, true, 'crash: the mint threw at the durability boundary with a captured nonce');
});

test('red-team done-when: ALL five attacks are rejected (allRejected)', () => {
  assert.equal(redTeamReport.allRejected, true, 'every red-team attack must be rejected by the spine');
  // cleanup the owned scratch dir.
  if (redTeamScratch) {
    try { fs.rmSync(redTeamScratch, { recursive: true, force: true }); } catch { /* best-effort */ }
  }
});
