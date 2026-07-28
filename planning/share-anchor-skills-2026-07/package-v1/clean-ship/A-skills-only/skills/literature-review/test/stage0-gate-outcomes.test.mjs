// test/stage0-gate-outcomes.test.mjs — Wave 9: every Stage-0 gate outcome through the
// FROZEN researchPrime one-shot gate, driven from the serialized HALT boundary.
//
// Pins the done-when clauses: APPROVE-verbatim executes the already-derived artifact
// with ZERO parse calls; EDIT is accepted once, RE-HASHES, and re-derives exactly
// once; ABORT halts; execution is blocked entirely without APPROVE; the headless
// approvalProvider path resolves with no isTTY halt; a parse-FAIL re-derive ABORTs
// with a stamped reason WITHOUT re-presenting the gate; and plan-gate.mjs /
// two-gate.mjs stay byte-identical through it all.
//
// Harness: each case seeds a runDir with a serialized HALTED pipeline state built
// from the Wave-4 fixture corpus (a full PlanArtifact + its grounded sources), then
// resumes Stage-0 with the gate wiring under test — zero intake calls, so the gate
// round-trip is exercised in isolation.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { sharedBrownfieldUrl, rpFile, importRp, fileSha256 } from './_wave1-trio-resolve.mjs';
import {
  makeFullArtifact,
  makeGroundedSources,
  rewordBranchEdit,
  artifactWithRewordedBranch,
  brokenArtifactMissingForesight,
  makeCountingParse,
  makeForbiddenParse,
  REWORDED_BRANCH_QUESTION,
} from './_wave4-rederive-fixtures.mjs';
import {
  runStage0Plan,
  stage0AllowsExecution,
  buildHeadlessApproval,
  STAGE0_STATUSES,
} from '../src/stage0-plan.mjs';
import {
  initializePipelineState,
  writePipelineState,
  readPipelineState,
  PIPELINE_STATUSES,
} from '../src/pipeline-state.mjs';

const GATE_FILES = ['bin/plan-gate.mjs', 'bin/two-gate.mjs'];

describe('Wave 9 — Stage-0 gate outcomes over the frozen gate', () => {
  const runDirs = [];
  const hashesBefore = {};
  let renderer;
  let rederiveMod;
  let validateMod;
  let twoGate;
  let approval;
  let HaltError;

  before(async () => {
    for (const f of GATE_FILES) hashesBefore[f] = fileSha256(rpFile(f));
    const indexUrl = await sharedBrownfieldUrl();
    renderer = await import(new URL('renderPlanProse.mjs', indexUrl).href);
    rederiveMod = await import(new URL('rederiveFromProse.mjs', indexUrl).href);
    validateMod = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
    twoGate = await importRp('bin/two-gate.mjs');
    approval = await importRp('bin/approval-provider.mjs');
    ({ HaltError } = await importRp('bin/trio-core/contract-core.mjs'));
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  /** Seed a runDir with a serialized HALTED state (the Wave-4 fixture plan). */
  async function seedHaltedRun(tag) {
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), `litrev-w9-gate-${tag}-`));
    runDirs.push(runDir);
    const artifact = makeFullArtifact();
    const groundedSources = makeGroundedSources();
    const planBody = renderer.renderPlanProse(artifact);
    const state = initializePipelineState({
      artifact,
      planBody,
      coverageSidecar: null,
      groundedSources,
      route: 'content',
    });
    writePipelineState(path.join(runDir, 'pipeline-state.json'), state);
    return { runDir, artifact, groundedSources, planBody };
  }

  test('APPROVE-verbatim: the already-derived artifact executes with ZERO parse calls', async () => {
    const { runDir, artifact } = await seedHaltedRun('approve');
    const forbidden = makeForbiddenParse();

    const stage0 = await runStage0Plan({
      runDir,
      parse: forbidden.parse,
      gate: { decision: 'APPROVE' },
    });

    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0.resumed, true, 'the gate round-trip runs from the serialized state');
    assert.equal(stage0AllowsExecution(stage0), true);
    assert.equal(stage0.decision.path, 'approve-verbatim');
    assert.equal(stage0.decision.parseCalls, 0);
    assert.equal(forbidden.calls(), 0, 'APPROVE-verbatim must invoke the bounded parse ZERO times');
    assert.deepStrictEqual(stage0.executionArtifact, artifact, 'the derived artifact executes byte-for-byte');

    // Hash-bound governance record with the caller-registered skill tag.
    const gov = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.equal(gov.planHash, stage0.planHash);
    assert.equal(gov.gate2Decision, 'APPROVE');
    assert.equal(gov.skill, 'literature-review');
    assert.equal(stage0.governanceRecord.skill, 'literature-review');

    // The serialized state advanced to APPROVED, bound to the plan hash.
    const state = readPipelineState(stage0.statePath);
    assert.equal(state.status, PIPELINE_STATUSES.APPROVED);
    assert.equal(state.plan.planHash, stage0.planHash);
    assert.equal(state.plan.approvedPath, 'approve-verbatim');
  });

  test('EDIT re-hashes then re-derives exactly ONCE; the re-derived artifact is what executes', async () => {
    const { runDir, planBody } = await seedHaltedRun('edit');
    const editedProse = rewordBranchEdit(planBody);
    const counting = makeCountingParse(() => artifactWithRewordedBranch());
    const presentedHashes = [];
    const decisions = ['EDIT', 'APPROVE'];

    const stage0 = await runStage0Plan({
      runDir,
      parse: counting.parse,
      gate: {
        promptGate2: async ({ planHash }) => {
          presentedHashes.push(planHash);
          return decisions.shift();
        },
        editedProse,
      },
    });

    // EDIT re-presented the re-built plan exactly once, under a NEW hash.
    assert.equal(presentedHashes.length, 2, 'EDIT re-presents exactly once');
    assert.notEqual(presentedHashes[0], presentedHashes[1], 'EDIT must produce a NEW plan hash');
    assert.equal(stage0.planHash, presentedHashes[1]);

    // Exactly ONE bounded re-derive parse, fed the APPROVEd edited prose.
    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0.decision.path, 'approve-with-edits');
    assert.equal(stage0.decision.parseCalls, 1);
    assert.equal(counting.calls(), 1, 'the bounded parse runs exactly once');
    assert.equal(counting.seen[0].editedProse, editedProse);

    // The RE-DERIVED artifact (canonically ordered) is what executes.
    assert.equal(stage0.executionArtifact.branches[0].question, REWORDED_BRANCH_QUESTION);
    assert.equal(
      validateMod.canonicalStringifyPlanArtifact(stage0.executionArtifact),
      validateMod.canonicalStringifyPlanArtifact(artifactWithRewordedBranch()),
    );

    const state = readPipelineState(stage0.statePath);
    assert.equal(state.status, PIPELINE_STATUSES.APPROVED);
    assert.equal(state.plan.approvedPath, 'approve-with-edits');
  });

  test('ABORT halts: no governance record, durable HALT-RECORD, snowball stays locked', async () => {
    const { runDir } = await seedHaltedRun('abort');
    const forbidden = makeForbiddenParse();

    const stage0 = await runStage0Plan({
      runDir,
      parse: forbidden.parse,
      gate: { decision: 'ABORT' },
    });

    assert.equal(stage0.status, STAGE0_STATUSES.ABORTED);
    assert.equal(stage0AllowsExecution(stage0), false);
    assert.equal(stage0.executionArtifact, null);
    assert.equal(forbidden.calls(), 0);
    assert.match(stage0.reason, /decision ABORT/);
    assert.ok(fs.existsSync(path.join(runDir, 'HALT-RECORD.json')));
    assert.equal(fs.existsSync(path.join(runDir, 'governance.json')), false, 'ABORT never reaches execution');

    const state = readPipelineState(stage0.statePath);
    assert.equal(state.status, PIPELINE_STATUSES.ABORTED);
    assert.equal(state.abort.stamp, 'litreview-stage0/gate-abort/1');
  });

  test('execution is blocked entirely without APPROVE: a no-response run halts and the gate records refuse execution', async () => {
    const { runDir } = await seedHaltedRun('noresp');

    const stage0 = await runStage0Plan({ runDir, parse: makeForbiddenParse().parse });

    assert.equal(stage0.status, STAGE0_STATUSES.HALTED);
    assert.equal(stage0AllowsExecution(stage0), false);
    assert.equal(fs.existsSync(path.join(runDir, 'governance.json')), false);

    // Direct block check against the frozen machine's own execution validator.
    const gate1 = JSON.parse(fs.readFileSync(path.join(runDir, 'gate1-record.json'), 'utf8'));
    const gate2 = JSON.parse(fs.readFileSync(path.join(runDir, 'gate2-record.json'), 'utf8'));
    assert.throws(
      () => twoGate.validateExecutionState(runDir, gate1.triageHash, gate2.planHash),
      (err) => err instanceof HaltError && /Execution blocked/.test(err.message),
    );
  });

  test('headless approvalProvider (signed token): resolves with no isTTY halt and a hash-bound governance record', async () => {
    const { runDir, artifact } = await seedHaltedRun('token');
    const token = approval.issueDevToken(runDir, 'wave9-stage0');
    const provider = await buildHeadlessApproval({ runDir, token });

    const stage0 = await runStage0Plan({
      runDir,
      parse: makeForbiddenParse().parse,
      gate: { approvalProvider: provider },
    });

    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0.governanceRecord.hostApprovalProvider, 'Token:wave9-stage0');
    assert.equal(stage0.decision.path, 'approve-verbatim');
    assert.deepStrictEqual(stage0.executionArtifact, artifact);
    const gov = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.equal(gov.planHash, stage0.planHash, 'headless governance record must be hash-bound');
    assert.equal(gov.skill, 'literature-review');
  });

  test('headless policy-grant route also resolves headlessly', async () => {
    const { runDir } = await seedHaltedRun('policy');
    const provider = await buildHeadlessApproval({ runDir, policyGrantIdentity: 'no-human-host' });

    const stage0 = await runStage0Plan({
      runDir,
      parse: makeForbiddenParse().parse,
      gate: { approvalProvider: provider },
    });

    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0.governanceRecord.hostApprovalProvider, 'PolicyGrant:no-human-host');
  });

  test('parse-FAIL on APPROVE-with-EDITs ABORTs with a stamped reason and NEVER re-presents the gate', async () => {
    const { runDir, planBody } = await seedHaltedRun('parsefail');
    const editedProse = rewordBranchEdit(planBody);
    const counting = makeCountingParse(() => brokenArtifactMissingForesight());
    let gatePresentations = 0;
    const decisions = ['EDIT', 'APPROVE'];

    const stage0 = await runStage0Plan({
      runDir,
      parse: counting.parse,
      gate: {
        promptGate2: async () => {
          gatePresentations += 1;
          return decisions.shift();
        },
        editedProse,
      },
    });

    assert.equal(stage0.status, STAGE0_STATUSES.ABORTED);
    assert.equal(stage0AllowsExecution(stage0), false);
    assert.equal(stage0.executionArtifact, null);
    assert.equal(counting.calls(), 1, 'exactly one bounded parse, never retried');
    assert.equal(stage0.abort.stamp, rederiveMod.REDERIVE_ABORT_STAMP, 'the abort carries the shared stamped reason');
    assert.match(stage0.abort.reason, /schema/);
    assert.equal(
      gatePresentations,
      2,
      'the gate is presented exactly twice (initial + the one bounded EDIT re-present) and NEVER after the abort',
    );

    const state = readPipelineState(stage0.statePath);
    assert.equal(state.status, PIPELINE_STATUSES.ABORTED);
    assert.equal(state.abort.stamp, rederiveMod.REDERIVE_ABORT_STAMP);
  });

  test('a missing parse adapter on an edited approval fail-to-ABORTs honestly (no fabricated re-derive)', async () => {
    const { runDir, planBody } = await seedHaltedRun('noparse');
    const stage0 = await runStage0Plan({
      runDir,
      gate: { decision: 'EDIT', editedProse: rewordBranchEdit(planBody) },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.ABORTED);
    assert.equal(stage0.abort.stamp, rederiveMod.REDERIVE_ABORT_STAMP);
    assert.match(stage0.abort.reason, /no bounded re-derive parse adapter/);
  });

  test('frozen-gate byte hashes are unchanged after every Stage-0 outcome', () => {
    for (const f of GATE_FILES) {
      assert.equal(
        fileSha256(rpFile(f)),
        hashesBefore[f],
        `${f} must be byte-identical before and after the Stage-0 outcome suite`,
      );
    }
  });
});
