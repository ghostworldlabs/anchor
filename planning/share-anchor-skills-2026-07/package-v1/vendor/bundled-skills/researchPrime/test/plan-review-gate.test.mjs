// test/plan-review-gate.test.mjs — the Phase-1 plan is surfaced ONE-SHOT to the human at
// Gate 2 (APPROVE/EDIT/ABORT) before execution, and the approved artifact is the RICH
// research plan (AXIS/branches/baselines/stakes/foresight), not the generic planMatrix.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

import { buildResearchPlan, runPlanReviewGate } from '../bin/plan-gate.mjs';
import { validateExecutionState } from '../bin/two-gate.mjs';

const SAMPLE = {
  objective: 'Which vector DB gives the best recall/latency tradeoff at 10M vectors?',
  axis: 'recall@10 ≥ 0.95 AND p99 < 50ms; a candidate is FALSIFIED if it cannot sustain both under load',
  branches: ['pgvector/HNSW', 'Qdrant', 'Milvus'],
  baselines: ['brute-force exact recall', 'FAISS-IVF published numbers'],
  stakes: { impact: 'high', reversibility: 'reversible', blastRadius: 'team' },
};

test('buildResearchPlan yields the rich Phase-1 artifact and is deterministic', () => {
  const a = buildResearchPlan({ inputs: SAMPLE });
  const b = buildResearchPlan({ inputs: SAMPLE });
  assert.equal(a.planVersion, 'researchPrime-phase1/1');
  assert.equal(a.objective, SAMPLE.objective);
  assert.equal(a.axis, SAMPLE.axis);
  assert.deepEqual(a.branches, SAMPLE.branches);
  assert.deepEqual(a.baselines, SAMPLE.baselines);
  assert.ok(a.tier, 'carries a governor tier projected from the stakes vector');
  assert.ok(a.stakes, 'carries the adjudicated stakes vector');
  assert.ok(a.foresight, 'carries the Oranges foresight receipt');
  assert.equal(JSON.stringify(a), JSON.stringify(b), 'pure ⇒ identical bytes ⇒ identical planHash');
});

test('APPROVE at both gates reaches execution and binds to the RICH plan (not planMatrix)', async () => {
  const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-plangate-'));
  const res = await runPlanReviewGate(SAMPLE, {
    runDir,
    promptGate1: async () => 'APPROVE',
    promptGate2: async () => 'APPROVE',
  });

  assert.ok(res.planHash);
  assert.equal(res.governanceRecord.gate2Decision, 'APPROVE');
  assert.doesNotThrow(() => validateExecutionState(runDir, res.triageHash, res.planHash));

  // The artifact the human actually approved is the rich Phase-1 plan.
  const planFile = fs.readdirSync(runDir).find((f) => f.startsWith('plan-') && f.endsWith('.json'));
  const approved = JSON.parse(fs.readFileSync(path.join(runDir, planFile), 'utf8'));
  assert.equal(approved.planVersion, 'researchPrime-phase1/1');
  assert.equal(approved.axis, SAMPLE.axis, 'AXIS was surfaced to the human, not a boilerplate matrix');
  assert.ok(!('matrix' in approved), 'NOT the generic planMatrix artifact');

  fs.rmSync(runDir, { recursive: true, force: true });
});

test('EDIT at Gate 2 re-hashes the plan and only the edited plan is approved', async () => {
  const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-plangate-'));
  const hashes = [];
  let calls = 0;

  await runPlanReviewGate(SAMPLE, {
    runDir,
    promptGate1: async () => 'APPROVE',
    promptGate2: async ({ planHash }) => {
      hashes.push(planHash);
      calls++;
      return calls === 1 ? 'EDIT' : 'APPROVE';
    },
    onEditedPlan: async (inp) => ({ ...inp, branches: [...inp.branches, 'Weaviate'] }),
  });

  assert.equal(calls, 2, 'Gate 2 prompted again after EDIT');
  assert.notEqual(hashes[0], hashes[1], 'the edited plan re-hashes');
  const rec = JSON.parse(fs.readFileSync(path.join(runDir, 'gate2-record.json'), 'utf8'));
  assert.equal(rec.planHash, hashes[1], 'the record binds to the EDITED plan');
  assert.equal(rec.gate2Decision, 'APPROVE');

  fs.rmSync(runDir, { recursive: true, force: true });
});

test('ABORT at Gate 2 halts before execution', async () => {
  const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-plangate-'));
  await assert.rejects(
    runPlanReviewGate(SAMPLE, {
      runDir,
      promptGate1: async () => 'APPROVE',
      promptGate2: async () => 'ABORT',
    }),
    /halted at Gate 2/i,
  );
  fs.rmSync(runDir, { recursive: true, force: true });
});
