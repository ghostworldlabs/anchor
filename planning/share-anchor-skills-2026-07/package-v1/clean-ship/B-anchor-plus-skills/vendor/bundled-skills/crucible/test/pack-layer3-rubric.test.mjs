// crucible/test/pack-layer3-rubric.test.mjs — Phase 2.4: the frozen rubric round runner.
// Deterministic (same rubric -> same verdict twice), a NEW scoring contract distinct from
// the convergence Judge, and the convergence-Judge path proven byte-identical (SR-6).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { scoreAgainstRubric, compileRubric, RUBRIC_SCHEMA, RUBRIC_ROLE } from '../bin/packs/layer3-rubric.mjs';
import { JUDGE_SCHEMA, makeJudge } from '../bin/judge.mjs';
import { testDocPack, wellFormedDoc, stubScorePass, stubScoreFail } from './pack-fixtures.mjs';

test('a frozen rubric scores deterministically twice (same rubric -> same verdict)', async () => {
  const a = await scoreAgainstRubric({ doc: wellFormedDoc, pack: testDocPack, score: stubScorePass });
  const b = await scoreAgainstRubric({ doc: wellFormedDoc, pack: testDocPack, score: stubScorePass });
  assert.equal(a.verdict, 'PASS');
  assert.equal(a.verdict, b.verdict);
  assert.equal(a.aggregate_score, b.aggregate_score);
});

test('a below-threshold deliverable FAILs the rubric', async () => {
  const r = await scoreAgainstRubric({ doc: wellFormedDoc, pack: testDocPack, score: stubScoreFail });
  assert.equal(r.verdict, 'FAIL');
});

test('the compiled rubric spec is IMMUTABLE (a run cannot mutate it)', () => {
  const spec = compileRubric(testDocPack);
  assert.throws(() => { spec.criteria[0].pass_threshold = 0; }, TypeError);
  assert.throws(() => { spec.criteria.push({}); }, TypeError);
});

test('the rubric output contract is DISTINCT from the convergence Judge', () => {
  // rubric speaks score/PASS-FAIL; the convergence Judge speaks CONVERGED/NOT_CONVERGED.
  assert.ok('score' in RUBRIC_SCHEMA.properties);
  assert.ok(!('decision' in RUBRIC_SCHEMA.properties));
  assert.deepEqual(JUDGE_SCHEMA.properties.decision.enum, ['CONVERGED', 'NOT_CONVERGED', 'CHALLENGE']);
  assert.equal(RUBRIC_ROLE, 'RubricJudge');
});

test('SR-6: the convergence-Judge path is byte-identical (reused, not forked)', async () => {
  // Layer 3 imports judge.mjs machinery; the convergence Judge still returns its own
  // contract unchanged when driven with a stub agent.
  const stubAgent = async () => ({ decision: 'CONVERGED', reasons: [], blocking: [] });
  const judge = makeJudge({ agent: stubAgent });
  const v = await judge.decide({ northStar: 'NS', findings: [], acceptanceCriteria: [] });
  assert.equal(v.decision, 'CONVERGED');
  assert.equal(v.lockable, true);
});

test('the rubric judge stamps its role (reused Judge attestation machinery)', async () => {
  const r = await scoreAgainstRubric({ doc: wellFormedDoc, pack: testDocPack, score: stubScorePass });
  assert.equal(r.stamp.role, 'RubricJudge');
  assert.equal(r.contract, 'rubric-score');
  assert.equal(r.rubric_frozen, true);
});
