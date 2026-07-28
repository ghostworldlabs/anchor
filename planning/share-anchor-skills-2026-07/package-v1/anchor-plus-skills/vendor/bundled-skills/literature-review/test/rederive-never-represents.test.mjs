// test/rederive-never-represents.test.mjs — Wave 4: parse-FAIL -> ABORT, NEVER a
// re-present (the one-shot gate is never self-violated).
//
// Pins the Wave-4 acceptance across schema-invalid, anchor-invalid, and binding-invalid
// parse outputs:
//   - the frozen one-shot gate is never re-invoked by a failing re-derive — a real gate
//     flow (EDIT accepted once, then APPROVE) presents exactly twice, and every stamped
//     ABORT afterwards leaves those counters untouched;
//   - no coverage table is ever hand-reconciled — a parse emission that smuggles a
//     coverage field is refused WHOLESALE (advisory-sidecar schema rejection), never
//     merged, and no decision ever carries a coverage field;
//   - the re-derive module is structurally incapable of re-presenting: its source holds
//     no reference to the frozen gate at all.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { importRp, sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import {
  makeGroundedSources,
  makeFullArtifact,
  rewordBranchEdit,
  artifactWithRewordedBranch,
  brokenArtifactMissingForesight,
  brokenArtifactExtraField,
  brokenArtifactWithCoverageTable,
  brokenArtifactFabricatedQuote,
  brokenArtifactUnknownSourceId,
  brokenArtifactUnrelatedPlan,
  brokenArtifactDroppedSlots,
  brokenArtifactCrossWired,
  brokenArtifactScopeExchanged,
  brokenArtifactForesightExchanged,
  brokenArtifactStampCrossSlot,
  makeCountingParse,
} from './_wave4-rederive-fixtures.mjs';

/** Non-RP prose plan builder — pure function of inputs (the gate's re-hash discipline). */
function buildProsePlan({ inputs }) {
  return {
    planVersion: 'litreview-brownfield-plan/rederive-wave4-1',
    body: inputs.planProse,
  };
}

describe('Wave 4 — fail-to-ABORT never re-presents (schema-invalid and anchor-invalid parse outputs)', () => {
  const runDirs = [];
  let twoGate;
  let rd;
  let r;
  let indexUrl;

  before(async () => {
    twoGate = await importRp('bin/two-gate.mjs');
    indexUrl = await sharedBrownfieldUrl();
    rd = await import(new URL('rederiveFromProse.mjs', indexUrl).href);
    r = await import(new URL('renderPlanProse.mjs', indexUrl).href);
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  test('acceptance GWT: a real gate flow presents exactly twice; every failing re-derive afterwards ABORTs without re-invoking the gate', async () => {
    const derived = makeFullArtifact();
    const renderedProse = r.renderPlanProse(derived);
    const editedProse = rewordBranchEdit(renderedProse);

    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'litrev-w4-norepresent-'));
    runDirs.push(runDir);

    // Drive the FROZEN gate through its own one-shot EDIT-once-then-APPROVE flow.
    let machineRuns = 0;
    let presentations = 0;
    let approvedProse = null;

    machineRuns += 1;
    const gateResult = await twoGate.runTwoGateMachine(
      { objective: 'Wave-4 never-re-present flow', planProse: renderedProse },
      {
        runDir,
        buildPlan: buildProsePlan,
        promptGate1: async () => 'APPROVE',
        promptGate2: async ({ plan }) => {
          presentations += 1;
          approvedProse = plan.body;
          return presentations === 1 ? 'EDIT' : 'APPROVE';
        },
        onEditedPlan: async (inputs) => ({ ...inputs, planProse: editedProse }),
      },
    );

    assert.ok(gateResult.planHash, 'the gate resolved to an APPROVEd, hash-bound plan');
    assert.equal(presentations, 2, 'one-shot gate: initial presentation + the single bounded EDIT re-present');
    assert.strictEqual(approvedProse, editedProse, 'the APPROVEd body is the edited prose');

    // Now every failing re-derive of that approved-but-edited prose must ABORT with a
    // stamp and must NOT touch the gate again — the counters stay frozen at 1 run / 2
    // presentations for the remainder of this flow.
    const badEmissions = [
      ['schema-invalid (foresight dropped)', brokenArtifactMissingForesight],
      ['anchor-invalid (fabricated quote)', brokenArtifactFabricatedQuote],
      ['binding-invalid (schema-valid, anchored, unrelated plan)', brokenArtifactUnrelatedPlan],
      ['binding-invalid (drops approved slots)', brokenArtifactDroppedSlots],
      ['binding-invalid (cross-wires approved values between slots)', brokenArtifactCrossWired],
      ['binding-invalid (exchanges scope.statement with scope.axis)', brokenArtifactScopeExchanged],
      ['binding-invalid (exchanges foresight fields)', brokenArtifactForesightExchanged],
      ["binding-invalid (foresight.stamp carries another slot's approved text)", brokenArtifactStampCrossSlot],
    ];
    for (const [name, emission] of badEmissions) {
      const counting = makeCountingParse(() => emission());
      const decision = await rd.resolveApprovedPlan({
        derivedArtifact: derived,
        approvedProse,
        groundedSources: makeGroundedSources(),
        parse: counting.parse,
      });
      assert.equal(decision.outcome, 'ABORT', name);
      assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP, name);
      assert.equal(counting.calls(), 1, `${name}: one bounded parse, no retry`);
      assert.equal(machineRuns, 1, `${name}: the gate machine is never re-run`);
      assert.equal(presentations, 2, `${name}: the gate is never re-presented`);
    }

    // A throwing parse is treated identically: stamped ABORT, gate untouched.
    const throwing = await rd.resolveApprovedPlan({
      derivedArtifact: derived,
      approvedProse,
      groundedSources: makeGroundedSources(),
      parse: async () => {
        throw new Error('parse transport failure');
      },
    });
    assert.equal(throwing.outcome, 'ABORT');
    assert.equal(machineRuns, 1);
    assert.equal(presentations, 2);
  });

  test('across schema-invalid and anchor-invalid parse outputs: stamped ABORT, no artifact, no re-present affordance', async () => {
    const derived = makeFullArtifact();
    const editedProse = rewordBranchEdit(r.renderPlanProse(derived));
    const table = [
      ['missing foresight receipt', brokenArtifactMissingForesight, /schema/],
      ['extra field on the artifact', brokenArtifactExtraField, /schema/],
      ['coverage table smuggled onto the artifact', brokenArtifactWithCoverageTable, /schema/],
      ['fabricated anchor quote', brokenArtifactFabricatedQuote, /word-for-word/],
      ['anchor naming an unknown sourceId', brokenArtifactUnknownSourceId, /word-for-word/],
      ['unrelated plan not bound to the approved prose', brokenArtifactUnrelatedPlan, /binding/],
      ['approved slots dropped by the emission', brokenArtifactDroppedSlots, /binding/],
      ['approved values cross-wired between slots', brokenArtifactCrossWired, /binding/],
      ['scope.statement exchanged with scope.axis', brokenArtifactScopeExchanged, /binding/],
      ['foresight.dropped exchanged with foresight.counterfactualCost', brokenArtifactForesightExchanged, /binding/],
      ["foresight.stamp set to another slot's approved text", brokenArtifactStampCrossSlot, /binding/],
    ];

    for (const [name, emission, reasonPattern] of table) {
      const counting = makeCountingParse(() => emission());
      const decision = await rd.rederiveFromProse({
        editedProse,
        groundedSources: makeGroundedSources(),
        parse: counting.parse,
      });

      assert.equal(decision.outcome, 'ABORT', name);
      assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP, name);
      assert.match(decision.abort.reason, reasonPattern, name);
      assert.ok(decision.abort.failures.length > 0, `${name}: the stamped failures name the defect`);
      assert.equal(counting.calls(), 1, `${name}: exactly one parse, never retried`);
      assert.equal('artifact' in decision, false, `${name}: no partial artifact escapes`);
      // The decision surface offers ABORT and nothing else: no retry/re-present affordance.
      assert.deepStrictEqual(
        Object.keys(decision).sort(),
        ['abort', 'outcome', 'parseCalls', 'path'],
        `${name}: the only affordance is the stamped ABORT`,
      );
    }
  });

  test('no coverage table is ever hand-reconciled: a smuggled coverage field is refused wholesale, and no decision carries coverage', async () => {
    const derived = makeFullArtifact();
    const editedProse = rewordBranchEdit(r.renderPlanProse(derived));

    // The refusal path: coverage on the emission is an advisory-sidecar schema rejection.
    const counting = makeCountingParse(() => brokenArtifactWithCoverageTable());
    const refused = await rd.rederiveFromProse({
      editedProse,
      groundedSources: makeGroundedSources(),
      parse: counting.parse,
    });
    assert.equal(refused.outcome, 'ABORT');
    const coverageFailure = refused.abort.failures.find((f) => f.path === 'coverage');
    assert.ok(coverageFailure, 'the stamped failure names the coverage key');
    assert.match(coverageFailure.reason, /advisory sidecar/);
    assert.equal('coverage' in refused, false);

    // The success path: a RUN decision's artifact never carries a coverage field either.
    const good = await rd.rederiveFromProse({
      editedProse,
      groundedSources: makeGroundedSources(),
      parse: async () => artifactWithRewordedBranch(),
    });
    assert.equal(good.outcome, 'RUN');
    assert.equal('coverage' in good.artifact, false);
    assert.equal('provenance' in good.artifact, false);
  });

  test('the re-derive module is structurally incapable of re-presenting: no gate reference in its source', () => {
    for (const moduleName of ['rederiveFromProse.mjs', 'verbatimAnchorCheck.mjs', 'approvedProseBinding.mjs']) {
      const source = fs.readFileSync(fileURLToPath(new URL(moduleName, indexUrl)), 'utf8');
      for (const gateToken of ['two-gate', 'plan-gate', 'runTwoGateMachine', 'promptGate']) {
        assert.equal(
          source.includes(gateToken),
          false,
          `${moduleName} must hold no reference to the frozen gate ("${gateToken}")`,
        );
      }
    }
  });
});
