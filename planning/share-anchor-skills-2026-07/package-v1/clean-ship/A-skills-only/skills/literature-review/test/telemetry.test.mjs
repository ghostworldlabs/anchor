// test/telemetry.test.mjs — Wave 11: every day-one telemetry field is emitted for
// each run path.
//
// Pins the acceptance GWT: runs exercising brownfield-content, intent-only,
// seeds-only-bootstrap, and zero-input-fail-fast — one of which takes an EDIT that
// parse-FAILs to ABORT — each emit path taken, EDIT-round count, the stamped
// parse-FAIL->ABORT event, ABORT-restart, seed presence/validation/derive-fed
// counts, verbatim-anchor-check failures surfaced in the sidecar, and the budget
// fail-fast-vs-auto-truncate outcome. Records are built from REAL runStage0Plan
// results (the frozen gate, the shared intake module, the serialized HALT boundary
// — the same harness as test/stage0-gate-outcomes.test.mjs); the only synthetic
// stage0 inputs are the invariant-negative checks in the final test.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import {
  makeFullArtifact,
  makeGroundedSources,
  rewordBranchEdit,
  brokenArtifactMissingForesight,
  brokenArtifactFabricatedQuote,
  makeCountingParse,
  makeForbiddenParse,
} from './_wave4-rederive-fixtures.mjs';
import { runStage0Plan, STAGE0_STATUSES } from '../src/stage0-plan.mjs';
import { initializePipelineState, writePipelineState } from '../src/pipeline-state.mjs';
import {
  TELEMETRY_VERSION,
  TELEMETRY_FIELDS,
  TELEMETRY_SEED_FIELDS,
  TELEMETRY_BUDGET_FIELDS,
  RUN_PATHS,
  REDERIVE_ABORT_STAMP,
  buildRunTelemetry,
  assertTelemetryRecord,
  createTelemetrySession,
  TelemetryError,
} from '../src/telemetry.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const CONTENT_FIXTURES = path.join(TEST_DIR, 'fixtures', 'adversarial-intake');

/** Two strictly-valid seeds + one malformed (rejected at the Wave-6 checkpoint). */
const VALID_SEED_A = { idType: 'doi', id: '10.5555/telemetry.a', title: 'Telemetry Seed Alpha' };
const VALID_SEED_B = { idType: 'pmid', id: '424242', title: 'Telemetry Seed Beta' };
const MALFORMED_SEED = { idType: 'doi', id: 'not-a-doi', title: 'Telemetry Seed Broken' };

describe('Wave 11 — day-one telemetry: every field, every run path', () => {
  const runDirs = [];
  let renderer;
  let rederiveMod;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    renderer = await import(new URL('renderPlanProse.mjs', indexUrl).href);
    rederiveMod = await import(new URL('rederiveFromProse.mjs', indexUrl).href);
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  function makeRunDir(tag) {
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), `litrev-w11-telemetry-${tag}-`));
    runDirs.push(runDir);
    return runDir;
  }

  /** Seed a runDir with a serialized HALTED state (the Wave-4 fixture plan). */
  function seedHaltedRun(tag, { route = 'content', truncated = false } = {}) {
    const runDir = makeRunDir(tag);
    const artifact = makeFullArtifact();
    const planBody = renderer.renderPlanProse(artifact);
    const state = initializePipelineState({
      artifact,
      planBody,
      coverageSidecar: null,
      groundedSources: makeGroundedSources(),
      route,
      truncated,
      truncationStamp: truncated ? { stamp: 'intake-truncated (telemetry fixture)' } : null,
    });
    writePipelineState(path.join(runDir, 'pipeline-state.json'), state);
    return { runDir, artifact, planBody };
  }

  test('the local rederive-abort stamp is byte-identical to the shared module export (parity pin)', () => {
    assert.equal(REDERIVE_ABORT_STAMP, rederiveMod.REDERIVE_ABORT_STAMP);
  });

  test('brownfield-content path, APPROVE-verbatim: path, zero edit rounds, zero parse calls, clean budget', async () => {
    const { runDir, artifact } = seedHaltedRun('content-approve');
    const stage0 = await runStage0Plan({
      runDir,
      parse: makeForbiddenParse().parse,
      gate: { decision: 'APPROVE' },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.RUN);

    const record = buildRunTelemetry({ stage0 });
    assert.equal(record.telemetryVersion, TELEMETRY_VERSION);
    assert.equal(record.runPath, 'content');
    assert.equal(record.status, 'RUN');
    assert.equal(record.editRounds, 0);
    assert.equal(record.rederiveParseCalls, 0);
    assert.equal(record.rederiveParseFailAbort, false);
    assert.equal(record.abortRestart, false);
    assert.equal(record.anchorCheckFailures, 0);
    assert.deepStrictEqual(record.budget, { overBudgetFailFast: false, autoTruncated: false });
    // Resumed run: seed counts come from the serialized artifact's pinned seed set.
    assert.deepStrictEqual(record.seeds, {
      present: artifact.seeds.length,
      passedValidation: artifact.seeds.length,
      rejected: 0,
      fedToDerive: artifact.seeds.length,
    });
  });

  test('an EDIT that parse-FAILs to ABORT emits editRounds=1 and the stamped parse-FAIL event; the next run is an ABORT-restart', async () => {
    const session = createTelemetrySession();

    const abortRun = seedHaltedRun('content-parsefail');
    const stage0Abort = await runStage0Plan({
      runDir: abortRun.runDir,
      parse: makeCountingParse(() => brokenArtifactMissingForesight()).parse,
      gate: { decision: 'EDIT', editedProse: rewordBranchEdit(abortRun.planBody) },
    });
    assert.equal(stage0Abort.status, STAGE0_STATUSES.ABORTED);
    const abortRecord = session.recordRun(stage0Abort);
    assert.equal(abortRecord.editRounds, 1, 'the one bounded EDIT round is counted');
    assert.equal(abortRecord.rederiveParseCalls, 1);
    assert.equal(abortRecord.rederiveParseFailAbort, true, 'the stamped re-derive abort is the parse-FAIL event');
    assert.equal(abortRecord.abortRestart, false, 'the first run of the session is no restart');
    assert.equal(abortRecord.anchorCheckFailures, 0, 'a SCHEMA failure is not an anchor-check failure');

    // The user restarts after the ABORT: the very next recorded run carries the signal.
    const restartRun = seedHaltedRun('content-restart');
    const stage0Restart = await runStage0Plan({
      runDir: restartRun.runDir,
      parse: makeForbiddenParse().parse,
      gate: { decision: 'APPROVE' },
    });
    const restartRecord = session.recordRun(stage0Restart);
    assert.equal(restartRecord.abortRestart, true, 'a run recorded after an ABORTED run is an ABORT-restart');

    const summary = session.summary();
    assert.equal(summary.totalRuns, 2);
    assert.equal(summary.rederiveParseFailAborts, 1);
    assert.equal(summary.abortRestarts, 1);
    assert.equal(summary.editRounds, 1);
  });

  test('a gate ABORT (no re-derive involved) is NOT counted as a parse-FAIL abort', async () => {
    const { runDir } = seedHaltedRun('gate-abort');
    const stage0 = await runStage0Plan({
      runDir,
      parse: makeForbiddenParse().parse,
      gate: { decision: 'ABORT' },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.ABORTED);
    const record = buildRunTelemetry({ stage0 });
    assert.equal(record.rederiveParseFailAbort, false, 'a plain gate ABORT carries no rederive stamp');
    assert.equal(record.rederiveParseCalls, 0);
  });

  test('verbatim-anchor-check failures surfaced by a fabricated-quote re-derive are counted', async () => {
    const { runDir, planBody } = seedHaltedRun('anchor-fail');
    const stage0 = await runStage0Plan({
      runDir,
      parse: makeCountingParse(() => brokenArtifactFabricatedQuote()).parse,
      gate: { decision: 'EDIT', editedProse: rewordBranchEdit(planBody) },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.ABORTED);
    assert.equal(stage0.abort.stamp, REDERIVE_ABORT_STAMP);
    const record = buildRunTelemetry({ stage0 });
    assert.equal(record.rederiveParseFailAbort, true);
    assert.ok(
      record.anchorCheckFailures >= 1,
      'the fabricated-quote anchor failure must be surfaced in the telemetry count',
    );
  });

  test('intent-only path emits its route token', async () => {
    const { runDir } = seedHaltedRun('intent', { route: 'intent-only' });
    const stage0 = await runStage0Plan({
      runDir,
      parse: makeForbiddenParse().parse,
      gate: { decision: 'APPROVE' },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    const record = buildRunTelemetry({ stage0 });
    assert.equal(record.runPath, 'intent-only');
    assert.equal(record.status, 'RUN');
  });

  test('seeds-only-bootstrap path (real deterministic route): present / passedValidation / rejected / fedToDerive', async () => {
    const runDir = makeRunDir('seeds-only');
    const stage0 = await runStage0Plan({
      runDir,
      intake: { seeds: [VALID_SEED_A, VALID_SEED_B, MALFORMED_SEED] },
      gate: { decision: 'APPROVE' },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0.route, 'seeds-only-bootstrap');

    const record = buildRunTelemetry({ stage0 });
    assert.equal(record.runPath, 'seeds-only-bootstrap');
    assert.deepStrictEqual(record.seeds, {
      present: 3,
      passedValidation: 2,
      rejected: 1,
      // The deterministic bootstrap consumed the accepted seeds (zero derive calls).
      fedToDerive: 2,
    });
    assert.equal(record.rederiveParseCalls, 0);
    assert.deepStrictEqual(record.budget, { overBudgetFailFast: false, autoTruncated: false });
  });

  test('zero-input-fail-fast path: FAILED, route token emitted, nothing fed to derive', async () => {
    const runDir = makeRunDir('zero-input');
    const stage0 = await runStage0Plan({ runDir, intake: {} });
    assert.equal(stage0.status, STAGE0_STATUSES.FAILED);

    const record = buildRunTelemetry({ stage0 });
    assert.equal(record.runPath, 'zero-input-fail-fast');
    assert.equal(record.status, 'FAILED');
    assert.deepStrictEqual(record.seeds, {
      present: 0,
      passedValidation: 0,
      rejected: 0,
      fedToDerive: 0,
    });
  });

  test('over-budget FAIL-FAST at the intake door is emitted as the budget event', async () => {
    const runDir = makeRunDir('budget-failfast');
    const stage0 = await runStage0Plan({
      runDir,
      intake: { roots: [CONTENT_FIXTURES], budgetTokens: 1 },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.FAILED);
    assert.equal(stage0.intake.ingest.decision, 'fail-fast');

    const record = buildRunTelemetry({ stage0 });
    assert.equal(record.runPath, 'content');
    assert.deepStrictEqual(record.budget, { overBudgetFailFast: true, autoTruncated: false });
  });

  test('an auto-truncated intake stamp survives the HALT boundary into telemetry', async () => {
    const { runDir } = seedHaltedRun('truncated', { truncated: true });
    const stage0 = await runStage0Plan({
      runDir,
      parse: makeForbiddenParse().parse,
      gate: { decision: 'APPROVE' },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    const record = buildRunTelemetry({ stage0 });
    assert.deepStrictEqual(record.budget, { overBudgetFailFast: false, autoTruncated: true });
  });

  test('acceptance GWT: every listed telemetry field (and sub-field) is emitted for each of the four run paths', async () => {
    const session = createTelemetrySession();

    // brownfield-content (resumed halted state), with an EDIT that parse-FAILs to ABORT.
    const contentRun = seedHaltedRun('gwt-content');
    session.recordRun(
      await runStage0Plan({
        runDir: contentRun.runDir,
        parse: makeCountingParse(() => brokenArtifactMissingForesight()).parse,
        gate: { decision: 'EDIT', editedProse: rewordBranchEdit(contentRun.planBody) },
      }),
    );
    // intent-only.
    const intentRun = seedHaltedRun('gwt-intent', { route: 'intent-only' });
    session.recordRun(
      await runStage0Plan({
        runDir: intentRun.runDir,
        parse: makeForbiddenParse().parse,
        gate: { decision: 'APPROVE' },
      }),
    );
    // seeds-only-bootstrap (real deterministic route).
    session.recordRun(
      await runStage0Plan({
        runDir: makeRunDir('gwt-seeds'),
        intake: { seeds: [VALID_SEED_A, VALID_SEED_B] },
        gate: { decision: 'APPROVE' },
      }),
    );
    // zero-input-fail-fast.
    session.recordRun(await runStage0Plan({ runDir: makeRunDir('gwt-zero'), intake: {} }));

    const records = session.records();
    assert.equal(records.length, 4);
    assert.deepStrictEqual(
      records.map((r) => r.runPath),
      ['content', 'intent-only', 'seeds-only-bootstrap', 'zero-input-fail-fast'],
      'the four run paths are each represented',
    );
    for (const record of records) {
      assert.equal(assertTelemetryRecord(record), true);
      for (const field of TELEMETRY_FIELDS) {
        assert.ok(Object.hasOwn(record, field), `record for path ${record.runPath} emits "${field}"`);
      }
      for (const field of TELEMETRY_SEED_FIELDS) {
        assert.ok(Object.hasOwn(record.seeds, field), `record for path ${record.runPath} emits seeds.${field}`);
      }
      for (const field of TELEMETRY_BUDGET_FIELDS) {
        assert.ok(Object.hasOwn(record.budget, field), `record for path ${record.runPath} emits budget.${field}`);
      }
      assert.ok(Object.isFrozen(record), 'records are deep-frozen');
    }

    // The parse-FAIL->ABORT event from the content run is in the session aggregate.
    const summary = session.summary();
    assert.equal(summary.totalRuns, 4);
    assert.equal(summary.rederiveParseFailAborts, 1);
    assert.equal(summary.abortRestarts, 1, 'the run recorded after the ABORT counts as a restart');
    for (const pathName of RUN_PATHS) {
      assert.equal(summary.byPath[pathName], 1, `summary counts one ${pathName} run`);
    }
  });

  test('a partial record can never escape: the invariant names any missing field', () => {
    assert.throws(() => buildRunTelemetry({ stage0: null }), TelemetryError);
    assert.throws(() => buildRunTelemetry({ stage0: { noStatus: true } }), TelemetryError);
    const good = buildRunTelemetry({ stage0: { status: 'FAILED', route: 'zero-input-fail-fast' } });
    assert.equal(assertTelemetryRecord(good), true);
    const mutilated = { ...good };
    delete mutilated.seeds;
    assert.throws(
      () => assertTelemetryRecord(mutilated),
      (err) => err instanceof TelemetryError && /"seeds"/.test(err.message),
    );
    assert.throws(
      () => assertTelemetryRecord({ ...good, runPath: 'not-a-route' }),
      (err) => err instanceof TelemetryError && /runPath/.test(err.message),
    );
  });
});
