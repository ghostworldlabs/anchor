// test/frozen-gate-bytes.test.mjs — Wave 4: plan-gate.mjs + two-gate.mjs byte hashes are
// unchanged by EVERYTHING in this wave.
//
// The hashes of both frozen gate files are taken FIRST, then the entire Wave-4 surface
// is exercised in-process — importing rederiveFromProse.mjs + verbatimAnchorCheck.mjs +
// approvedProseBinding.mjs, running the APPROVE-verbatim path, an APPROVE-with-EDITs
// RUN, a schema-invalid ABORT, an anchor-invalid ABORT, a binding-invalid ABORT, an
// over-budget ABORT, the standalone deterministic checks, and a real drive of the
// frozen gate through its EDIT-once-then-APPROVE flow — and the hashes are asserted
// byte-identical afterwards. The bounded re-derive lives entirely OUTSIDE the frozen
// gate files.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { rpFile, importRp, fileSha256, sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import {
  makeGroundedSources,
  makeFullArtifact,
  rewordBranchEdit,
  artifactWithRewordedBranch,
  brokenArtifactMissingForesight,
  brokenArtifactFabricatedQuote,
  brokenArtifactUnrelatedPlan,
  makeCountingParse,
  makeForbiddenParse,
} from './_wave4-rederive-fixtures.mjs';

const GATE_FILES = ['bin/plan-gate.mjs', 'bin/two-gate.mjs'];

describe('Wave 4 — frozen-gate bytes unchanged by everything in this wave', () => {
  const hashesBefore = {};
  const runDirs = [];
  const exercised = [];

  before(async () => {
    // Hash FIRST — before any Wave-4 module is even imported.
    for (const f of GATE_FILES) hashesBefore[f] = fileSha256(rpFile(f));

    const indexUrl = await sharedBrownfieldUrl();
    const rd = await import(new URL('rederiveFromProse.mjs', indexUrl).href);
    const vac = await import(new URL('verbatimAnchorCheck.mjs', indexUrl).href);
    const apb = await import(new URL('approvedProseBinding.mjs', indexUrl).href);
    const r = await import(new URL('renderPlanProse.mjs', indexUrl).href);
    const twoGate = await importRp('bin/two-gate.mjs');

    const derived = makeFullArtifact();
    const renderedProse = r.renderPlanProse(derived);
    const editedProse = rewordBranchEdit(renderedProse);
    const grounded = makeGroundedSources();

    // 1. APPROVE-verbatim (zero parse calls).
    exercised.push(
      await rd.resolveApprovedPlan({
        derivedArtifact: derived,
        approvedProse: renderedProse,
        groundedSources: grounded,
        parse: makeForbiddenParse().parse,
      }),
    );

    // 2. APPROVE-with-EDITs RUN.
    exercised.push(
      await rd.resolveApprovedPlan({
        derivedArtifact: derived,
        approvedProse: editedProse,
        groundedSources: grounded,
        parse: makeCountingParse(() => artifactWithRewordedBranch()).parse,
      }),
    );

    // 3. Schema-invalid ABORT, 4. anchor-invalid ABORT, 5. binding-invalid ABORT.
    for (const emission of [
      brokenArtifactMissingForesight,
      brokenArtifactFabricatedQuote,
      brokenArtifactUnrelatedPlan,
    ]) {
      exercised.push(
        await rd.rederiveFromProse({
          editedProse,
          groundedSources: grounded,
          parse: makeCountingParse(() => emission()).parse,
        }),
      );
    }

    // 6. Over-budget ABORT (the parse is never invoked).
    exercised.push(
      await rd.rederiveFromProse({
        editedProse,
        groundedSources: grounded,
        parse: makeForbiddenParse().parse,
        maxInputChars: 16,
      }),
    );

    // 7. The deterministic anchor check on its own, 8. the binding check on its own.
    exercised.push(vac.verbatimAnchorCheck(derived, grounded));
    exercised.push(apb.approvedProseBinding(derived, renderedProse));

    // 9. A REAL drive of the frozen gate: EDIT accepted once, then APPROVE.
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'litrev-w4-gatebytes-'));
    runDirs.push(runDir);
    let presentations = 0;
    exercised.push(
      await twoGate.runTwoGateMachine(
        { objective: 'Wave-4 frozen-gate byte fence', planProse: renderedProse },
        {
          runDir,
          buildPlan: ({ inputs }) => ({
            planVersion: 'litreview-brownfield-plan/rederive-wave4-1',
            body: inputs.planProse,
          }),
          promptGate1: async () => 'APPROVE',
          promptGate2: async () => {
            presentations += 1;
            return presentations === 1 ? 'EDIT' : 'APPROVE';
          },
          onEditedPlan: async (inputs) => ({ ...inputs, planProse: editedProse }),
        },
      ),
    );
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  test('the whole Wave-4 surface actually ran (the fence is not vacuous)', () => {
    assert.equal(exercised.length, 9);
    const outcomes = exercised.slice(0, 6).map((d) => `${d.outcome}/${d.path}/${d.parseCalls}`);
    assert.deepStrictEqual(outcomes, [
      'RUN/approve-verbatim/0',
      'RUN/approve-with-edits/1',
      'ABORT/approve-with-edits/1',
      'ABORT/approve-with-edits/1',
      'ABORT/approve-with-edits/1',
      'ABORT/approve-with-edits/0',
    ]);
    assert.equal(exercised[6].ok, true, 'the anchor check passed on the coherent corpus');
    assert.equal(exercised[7].ok, true, 'the binding check passed on the rendered prose');
    assert.ok(exercised[8].planHash, 'the frozen gate resolved a hash-bound APPROVE');
  });

  test('acceptance GWT: plan-gate.mjs and two-gate.mjs byte hashes are unchanged by everything in this wave', () => {
    for (const f of GATE_FILES) {
      assert.equal(
        fileSha256(rpFile(f)),
        hashesBefore[f],
        `${f} must be byte-identical after the full Wave-4 exercise (the re-derive lives OUTSIDE the frozen gate)`,
      );
    }
  });
});
