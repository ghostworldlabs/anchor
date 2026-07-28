// test/rederive-roundtrip.test.mjs — Wave 4: property test over the PlanArtifact corpus
// for the bounded re-derive round-trip (trio-shared/brownfield-intake/rederiveFromProse.mjs
// + verbatimAnchorCheck.mjs + approvedProseBinding.mjs, resolved via the Wave-1 pinned
// trio home).
//
// Pins the Wave-4 acceptance:
//   - an UNEDITED render executes the already-derived artifact byte-for-byte with the
//     re-derive LLM parse invoked ZERO times;
//   - rederive(edit(render(P))) for realistic human edits (branch reworded, source-to-beat
//     added, seed line altered) runs exactly ONE bounded parse, validates its emission
//     exactly once against the module-owned schema AND the deterministic verbatim-anchor
//     check AND the deterministic approved-prose binding check, and on success executes
//     the re-derived artifact;
//   - a schema-invalid, anchor-invalid, or binding-invalid emission cleanly ABORTs with
//     a stamped reason — no partial artifact escapes, nothing in between RUN and ABORT;
//   - the binding check is BIJECTIVE and PER SLOT: an emission that DROPS approved
//     plan elements (fewer branches / sources-to-beat / seeds than the approved prose
//     lists) ABORTs naming the dropped slots, and an emission that re-pairs approved
//     values across slots (swapped seed titles, a branch given another branch's
//     rationale) ABORTs with a slot-alignment binding failure;
//   - "word-for-word" is the DEFINED check: >= DEFAULT_MIN_QUOTE_LENGTH collapsed chars
//     (reusing lit-review's src/quoteExtractor.mjs constant, 10) and token-boundary
//     alignment — a sub-minimum or mid-word span is an anchor FAILURE.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';

import { DEFAULT_MIN_QUOTE_LENGTH as LITREVIEW_MIN_QUOTE_LENGTH } from '../src/quoteExtractor.mjs';
import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import {
  makeGroundedSources,
  makeFullArtifact,
  makeMinimalArtifact,
  rewordBranchEdit,
  artifactWithRewordedBranch,
  REWORDED_BRANCH_QUESTION,
  addSourceToBeatEdit,
  artifactWithAddedSource,
  alterSeedLineEdit,
  artifactWithAlteredSeed,
  ALTERED_SEED_TITLE,
  addBranchToMinimalEdit,
  minimalArtifactWithBranch,
  brokenArtifactMissingForesight,
  brokenArtifactFabricatedQuote,
  brokenArtifactUnrelatedPlan,
  brokenArtifactDroppedSlots,
  brokenArtifactCrossWired,
  brokenArtifactScopeExchanged,
  brokenArtifactForesightExchanged,
  brokenArtifactStampCrossSlot,
  makeCountingParse,
  makeForbiddenParse,
  makeValidationCounters,
} from './_wave4-rederive-fixtures.mjs';

describe('Wave 4 — bounded re-derive round-trip (property test over the PlanArtifact corpus)', () => {
  let rd; // rederiveFromProse.mjs
  let vac; // verbatimAnchorCheck.mjs
  let r; // renderPlanProse.mjs
  let v; // validatePlanArtifact.mjs

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    rd = await import(new URL('rederiveFromProse.mjs', indexUrl).href);
    vac = await import(new URL('verbatimAnchorCheck.mjs', indexUrl).href);
    r = await import(new URL('renderPlanProse.mjs', indexUrl).href);
    v = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
  });

  /** The RUN-outcome edit scenarios: realistic human edits + the matching emission. */
  const runScenarios = [
    {
      name: 'branch reworded (full artifact)',
      base: makeFullArtifact,
      edit: rewordBranchEdit,
      emission: artifactWithRewordedBranch,
      assertApplied: (artifact) =>
        assert.equal(artifact.branches[0].question, REWORDED_BRANCH_QUESTION),
    },
    {
      name: 'source-to-beat added (full artifact)',
      base: makeFullArtifact,
      edit: addSourceToBeatEdit,
      emission: artifactWithAddedSource,
      assertApplied: (artifact) => {
        assert.equal(artifact.sourcesToBeat.length, 3);
        assert.equal(artifact.sourcesToBeat[2].title, 'Bedside latency guideline');
      },
    },
    {
      name: 'seed line altered (full artifact)',
      base: makeFullArtifact,
      edit: alterSeedLineEdit,
      emission: artifactWithAlteredSeed,
      assertApplied: (artifact) => assert.equal(artifact.seeds[0].title, ALTERED_SEED_TITLE),
    },
    {
      name: 'branch added where none existed (minimal artifact)',
      base: makeMinimalArtifact,
      edit: addBranchToMinimalEdit,
      emission: minimalArtifactWithBranch,
      assertApplied: (artifact) => {
        assert.equal(artifact.branches.length, 1);
        assert.equal(artifact.branches[0].question, 'Which replicated results actually exist?');
      },
    },
  ];

  test('the corpus is coherent: artifacts are schema-valid and fully verbatim-anchored', () => {
    const grounded = makeGroundedSources();
    for (const make of [makeFullArtifact, makeMinimalArtifact]) {
      const artifact = make();
      assert.equal(v.validatePlanArtifact(artifact).ok, true);
      assert.deepStrictEqual(vac.verbatimAnchorCheck(artifact, grounded), { ok: true, failures: [] });
    }
    for (const scenario of runScenarios) {
      const emission = scenario.emission();
      assert.equal(v.validatePlanArtifact(emission).ok, true, scenario.name);
      assert.equal(vac.verbatimAnchorCheck(emission, grounded).ok, true, scenario.name);
    }
  });

  test('acceptance GWT: APPROVE-verbatim executes the already-derived artifact byte-for-byte, ZERO parse calls', async () => {
    for (const make of [makeFullArtifact, makeMinimalArtifact]) {
      const derived = make();
      const derivedBytes = v.canonicalStringifyPlanArtifact(derived);
      const forbidden = makeForbiddenParse();

      const decision = await rd.resolveApprovedPlan({
        derivedArtifact: derived,
        approvedProse: r.renderPlanProse(derived),
        groundedSources: makeGroundedSources(),
        parse: forbidden.parse,
      });

      assert.equal(decision.outcome, 'RUN');
      assert.equal(decision.path, 'approve-verbatim');
      assert.equal(decision.parseCalls, 0);
      assert.equal(forbidden.calls(), 0, 'the re-derive LLM parse must be invoked zero times');
      assert.strictEqual(
        decision.artifact,
        derived,
        'the ORIGINALLY-derived artifact object executes, unmodified',
      );
      assert.strictEqual(
        v.canonicalStringifyPlanArtifact(decision.artifact),
        derivedBytes,
        'byte-for-byte unchanged',
      );
    }
  });

  test('the verbatim short-circuit is byte-strict: ANY byte difference takes the re-derive path', async () => {
    const derived = makeFullArtifact();
    const counting = makeCountingParse(() => makeFullArtifact());

    const decision = await rd.resolveApprovedPlan({
      derivedArtifact: derived,
      approvedProse: r.renderPlanProse(derived) + ' ', // one trailing byte of "edit"
      groundedSources: makeGroundedSources(),
      parse: counting.parse,
    });

    assert.equal(decision.outcome, 'RUN');
    assert.equal(decision.path, 'approve-with-edits');
    assert.equal(decision.parseCalls, 1);
    assert.equal(counting.calls(), 1);
  });

  test('acceptance GWT: realistic human edits — exactly ONE parse, validated exactly once, the re-derived artifact runs', async () => {
    for (const scenario of runScenarios) {
      const derived = scenario.base();
      const rendered = r.renderPlanProse(derived);
      const edited = scenario.edit(rendered);
      assert.notStrictEqual(edited, rendered, `${scenario.name}: the edit must change the prose`);

      const counting = makeCountingParse(() => scenario.emission());
      const { counts, instrument } = makeValidationCounters();

      const decision = await rd.resolveApprovedPlan({
        derivedArtifact: derived,
        approvedProse: edited,
        groundedSources: makeGroundedSources(),
        parse: counting.parse,
        instrument,
      });

      assert.equal(decision.outcome, 'RUN', scenario.name);
      assert.equal(decision.path, 'approve-with-edits', scenario.name);
      assert.equal(decision.parseCalls, 1, scenario.name);
      assert.equal(counting.calls(), 1, `${scenario.name}: exactly one LLM parse call`);
      assert.strictEqual(
        counting.seen[0].editedProse,
        edited,
        `${scenario.name}: the parse reads the EDITED prose`,
      );
      assert.equal(counts.schema, 1, `${scenario.name}: schema validated exactly once`);
      assert.equal(counts.anchors, 1, `${scenario.name}: verbatim-anchor check ran exactly once`);
      assert.equal(counts.binding, 1, `${scenario.name}: approved-prose binding check ran exactly once`);

      // The re-derived artifact — not the original derived one — is what executes.
      scenario.assertApplied(decision.artifact);
      assert.strictEqual(
        v.canonicalStringifyPlanArtifact(decision.artifact),
        v.canonicalStringifyPlanArtifact(scenario.emission()),
        `${scenario.name}: the emission executes, canonically ordered`,
      );
      assert.equal(v.validatePlanArtifact(decision.artifact).ok, true, scenario.name);
      assert.equal(
        vac.verbatimAnchorCheck(decision.artifact, makeGroundedSources()).ok,
        true,
        scenario.name,
      );
    }
  });

  test('property: rederive(edit(render(P))) either RUNs schema-valid + verbatim-anchored, or cleanly ABORTs — nothing in between', async () => {
    const allScenarios = [
      ...runScenarios.map((s) => ({ ...s, expect: 'RUN' })),
      {
        name: 'schema-invalid emission (foresight dropped)',
        base: makeFullArtifact,
        edit: rewordBranchEdit,
        emission: brokenArtifactMissingForesight,
        expect: 'ABORT',
      },
      {
        name: 'anchor-invalid emission (fabricated quote)',
        base: makeFullArtifact,
        edit: rewordBranchEdit,
        emission: brokenArtifactFabricatedQuote,
        expect: 'ABORT',
      },
      {
        name: 'binding-invalid emission (schema-valid, anchored, but an unrelated plan)',
        base: makeFullArtifact,
        edit: rewordBranchEdit,
        emission: brokenArtifactUnrelatedPlan,
        expect: 'ABORT',
      },
      {
        name: 'binding-invalid emission (drops approved slots)',
        base: makeFullArtifact,
        edit: rewordBranchEdit,
        emission: brokenArtifactDroppedSlots,
        expect: 'ABORT',
      },
      {
        name: 'binding-invalid emission (cross-wires approved values between slots)',
        base: makeFullArtifact,
        edit: rewordBranchEdit,
        emission: brokenArtifactCrossWired,
        expect: 'ABORT',
      },
      {
        name: 'binding-invalid emission (exchanges scope.statement with scope.axis)',
        base: makeFullArtifact,
        edit: rewordBranchEdit,
        emission: brokenArtifactScopeExchanged,
        expect: 'ABORT',
      },
      {
        name: 'binding-invalid emission (exchanges foresight.dropped with foresight.counterfactualCost)',
        base: makeFullArtifact,
        edit: rewordBranchEdit,
        emission: brokenArtifactForesightExchanged,
        expect: 'ABORT',
      },
      {
        name: 'binding-invalid emission (foresight.stamp set to another slot\'s approved text)',
        base: makeFullArtifact,
        edit: rewordBranchEdit,
        emission: brokenArtifactStampCrossSlot,
        expect: 'ABORT',
      },
    ];

    for (const scenario of allScenarios) {
      const derived = scenario.base();
      const counting = makeCountingParse(() => scenario.emission());
      const decision = await rd.resolveApprovedPlan({
        derivedArtifact: derived,
        approvedProse: scenario.edit(r.renderPlanProse(derived)),
        groundedSources: makeGroundedSources(),
        parse: counting.parse,
      });

      assert.ok(['RUN', 'ABORT'].includes(decision.outcome), scenario.name);
      assert.equal(decision.outcome, scenario.expect, scenario.name);
      assert.equal(counting.calls(), 1, `${scenario.name}: the parse is bounded to one call either way`);
      if (decision.outcome === 'RUN') {
        assert.equal(v.validatePlanArtifact(decision.artifact).ok, true, scenario.name);
        assert.equal(
          vac.verbatimAnchorCheck(decision.artifact, makeGroundedSources()).ok,
          true,
          scenario.name,
        );
        assert.equal('abort' in decision, false, scenario.name);
      } else {
        assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP, scenario.name);
        assert.equal(typeof decision.abort.reason, 'string', scenario.name);
        assert.ok(decision.abort.reason.length > 0, scenario.name);
        assert.equal(
          'artifact' in decision,
          false,
          `${scenario.name}: no partial artifact escapes an ABORT`,
        );
      }
    }
  });

  test('acceptance GWT: a schema-invalid emission ABORTs with a stamped reason naming the defect', async () => {
    const { counts, instrument } = makeValidationCounters();
    const counting = makeCountingParse(() => brokenArtifactMissingForesight());

    const decision = await rd.rederiveFromProse({
      editedProse: rewordBranchEdit(r.renderPlanProse(makeFullArtifact())),
      groundedSources: makeGroundedSources(),
      parse: counting.parse,
      instrument,
    });

    assert.equal(decision.outcome, 'ABORT');
    assert.equal(decision.parseCalls, 1);
    assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP);
    assert.match(decision.abort.reason, /schema/);
    assert.ok(
      decision.abort.failures.some((f) => f.path === 'foresight'),
      'the stamped failures name the missing foresight receipt',
    );
    assert.equal(counts.schema, 1, 'schema validated exactly once — never re-validated');
    assert.equal(counts.anchors, 0, 'the anchor check never runs on a schema-invalid emission');
    assert.equal(counts.binding, 0, 'the binding check never runs on a schema-invalid emission');
    assert.equal('artifact' in decision, false);
  });

  test('acceptance GWT: an anchor-invalid emission ABORTs naming the offending anchor', async () => {
    const { counts, instrument } = makeValidationCounters();
    const counting = makeCountingParse(() => brokenArtifactFabricatedQuote());

    const decision = await rd.rederiveFromProse({
      editedProse: rewordBranchEdit(r.renderPlanProse(makeFullArtifact())),
      groundedSources: makeGroundedSources(),
      parse: counting.parse,
      instrument,
    });

    assert.equal(decision.outcome, 'ABORT');
    assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP);
    assert.match(decision.abort.reason, /word-for-word/);
    const failure = decision.abort.failures.find((f) => f.path === 'branches[0].anchors[0]');
    assert.ok(failure, 'the stamped failures name the offending anchor path');
    assert.equal(failure.quote, 'a fabricated span that appears in no grounded source');
    assert.equal(counts.schema, 1, 'validated exactly once');
    assert.equal(counts.anchors, 1, 'anchor-checked exactly once');
    assert.equal(counts.binding, 0, 'the binding check never runs on an anchor-invalid emission');
    assert.equal('artifact' in decision, false);
  });

  test('acceptance GWT: a schema-valid, fully-anchored emission describing a DIFFERENT plan ABORTs with a stamped binding failure', async () => {
    const grounded = makeGroundedSources();
    // The emission is schema-valid and fully verbatim-anchored — ONLY the deterministic
    // approved-prose binding check stands between it and execution.
    assert.equal(v.validatePlanArtifact(brokenArtifactUnrelatedPlan()).ok, true);
    assert.equal(vac.verbatimAnchorCheck(brokenArtifactUnrelatedPlan(), grounded).ok, true);

    const { counts, instrument } = makeValidationCounters();
    const counting = makeCountingParse(() => brokenArtifactUnrelatedPlan());

    const decision = await rd.rederiveFromProse({
      editedProse: rewordBranchEdit(r.renderPlanProse(makeFullArtifact())),
      groundedSources: grounded,
      parse: counting.parse,
      instrument,
    });

    assert.equal(decision.outcome, 'ABORT');
    assert.equal(decision.parseCalls, 1);
    assert.equal(counting.calls(), 1, 'one bounded parse, no retry');
    assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP);
    assert.match(decision.abort.reason, /binding/, 'the stamped reason names the binding failure');
    assert.ok(
      decision.abort.failures.some((f) => f.path === 'scope.statement'),
      'the stamped failures name the unbound scope statement',
    );
    assert.equal(counts.schema, 1, 'schema validated exactly once');
    assert.equal(counts.anchors, 1, 'anchor-checked exactly once');
    assert.equal(counts.binding, 1, 'binding-checked exactly once');
    assert.equal('artifact' in decision, false, 'the unrelated artifact never executes');
  });

  test('acceptance GWT: an emission that DROPS approved plan elements ABORTs naming the dropped slots — the truncated artifact never executes', async () => {
    const grounded = makeGroundedSources();
    // The approved prose lists 4 branches, 2 sources-to-beat and 3 seeds; the emission
    // is schema-valid, fully verbatim-anchored, and every SURVIVING value appears
    // verbatim in that prose — but it retains only 1 branch and zero sources/seeds.
    const approvedProse = rewordBranchEdit(r.renderPlanProse(makeFullArtifact()));
    const emission = brokenArtifactDroppedSlots();
    assert.equal(v.validatePlanArtifact(emission).ok, true);
    assert.equal(vac.verbatimAnchorCheck(emission, grounded).ok, true);
    assert.equal(emission.branches.length, 1);
    assert.equal(emission.sourcesToBeat.length, 0);
    assert.equal(emission.seeds.length, 0);

    const { counts, instrument } = makeValidationCounters();
    const counting = makeCountingParse(() => brokenArtifactDroppedSlots());
    const decision = await rd.rederiveFromProse({
      editedProse: approvedProse,
      groundedSources: grounded,
      parse: counting.parse,
      instrument,
    });

    assert.equal(decision.outcome, 'ABORT');
    assert.equal(decision.parseCalls, 1);
    assert.equal(counting.calls(), 1, 'one bounded parse, no retry');
    assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP);
    assert.match(decision.abort.reason, /binding/, 'the stamped reason is a binding failure');
    for (const droppedPath of [
      'branches[1]',
      'branches[2]',
      'branches[3]',
      'sourcesToBeat[0]',
      'sourcesToBeat[1]',
      'seeds[0]',
      'seeds[1]',
      'seeds[2]',
    ]) {
      const failure = decision.abort.failures.find((f) => f.path === droppedPath);
      assert.ok(failure, `the stamped failures name the dropped slot ${droppedPath}`);
      assert.match(failure.reason, /dropped slot/, droppedPath);
    }
    assert.equal(counts.schema, 1, 'validated exactly once');
    assert.equal(counts.anchors, 1, 'anchor-checked exactly once');
    assert.equal(counts.binding, 1, 'binding-checked exactly once');
    assert.equal('artifact' in decision, false, 'the truncated artifact never executes');
  });

  test('acceptance GWT: an emission that re-pairs approved values across slots ABORTs with a slot-alignment binding failure', async () => {
    const grounded = makeGroundedSources();
    // Same approved prose; the emission keeps every approved value and every approved
    // slot count, but swaps two seeds' titles and gives branch 0 branch 1's rationale.
    const approvedProse = rewordBranchEdit(r.renderPlanProse(makeFullArtifact()));
    const emission = brokenArtifactCrossWired();
    assert.equal(v.validatePlanArtifact(emission).ok, true);
    assert.equal(vac.verbatimAnchorCheck(emission, grounded).ok, true);

    const { counts, instrument } = makeValidationCounters();
    const counting = makeCountingParse(() => brokenArtifactCrossWired());
    const decision = await rd.rederiveFromProse({
      editedProse: approvedProse,
      groundedSources: grounded,
      parse: counting.parse,
      instrument,
    });

    assert.equal(decision.outcome, 'ABORT');
    assert.equal(decision.parseCalls, 1);
    assert.equal(counting.calls(), 1, 'one bounded parse, no retry');
    assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP);
    assert.match(decision.abort.reason, /binding/, 'the stamped reason is a binding failure');
    for (const crossWiredPath of ['seeds[0].title', 'seeds[1].title', 'branches[0].rationale']) {
      const failure = decision.abort.failures.find((f) => f.path === crossWiredPath);
      assert.ok(failure, `the stamped failures name the cross-wired value ${crossWiredPath}`);
      assert.match(failure.reason, /slot-alignment/, crossWiredPath);
    }
    // No dropped-slot or soundness failures muddy the verdict — this is purely re-pairing.
    assert.ok(
      decision.abort.failures.every((f) => /slot-alignment/.test(f.reason)),
      'every stamped failure is a slot-alignment failure',
    );
    assert.equal(counts.binding, 1, 'binding-checked exactly once');
    assert.equal('artifact' in decision, false, 'the cross-wired artifact never executes');
  });

  test('acceptance GWT: an emission that exchanges SINGLE-SLOT values (scope.statement<->scope.axis, foresight fields) ABORTs with a slot-alignment binding failure', async () => {
    const grounded = makeGroundedSources();
    const approvedProse = rewordBranchEdit(r.renderPlanProse(makeFullArtifact()));
    // Each emission keeps every approved value verbatim in the prose — only the
    // per-LABELED-LINE alignment of the single-slot elements can refuse the exchange.
    const table = [
      {
        name: 'scope.statement exchanged with scope.axis',
        emission: brokenArtifactScopeExchanged,
        crossWiredPaths: ['scope.statement', 'scope.axis'],
      },
      {
        name: 'foresight.dropped exchanged with foresight.counterfactualCost',
        emission: brokenArtifactForesightExchanged,
        crossWiredPaths: ['foresight.dropped', 'foresight.counterfactualCost'],
      },
      {
        name: "foresight.stamp set to another slot's approved text",
        emission: brokenArtifactStampCrossSlot,
        crossWiredPaths: ['foresight.stamp'],
      },
    ];

    for (const { name, emission, crossWiredPaths } of table) {
      assert.equal(v.validatePlanArtifact(emission()).ok, true, `${name}: schema-valid`);
      assert.equal(
        vac.verbatimAnchorCheck(emission(), grounded).ok,
        true,
        `${name}: fully verbatim-anchored`,
      );

      const { counts, instrument } = makeValidationCounters();
      const counting = makeCountingParse(() => emission());
      const decision = await rd.rederiveFromProse({
        editedProse: approvedProse,
        groundedSources: grounded,
        parse: counting.parse,
        instrument,
      });

      assert.equal(decision.outcome, 'ABORT', name);
      assert.equal(counting.calls(), 1, `${name}: one bounded parse, no retry`);
      assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP, name);
      assert.match(decision.abort.reason, /binding/, `${name}: a stamped binding failure`);
      for (const path of crossWiredPaths) {
        const failure = decision.abort.failures.find((f) => f.path === path);
        assert.ok(failure, `${name}: the stamped failures name ${path}`);
        assert.match(failure.reason, /slot-alignment/, `${name}: ${path}`);
      }
      assert.ok(
        decision.abort.failures.every((f) => /slot-alignment/.test(f.reason)),
        `${name}: every stamped failure is a slot-alignment failure — pure single-slot re-pairing`,
      );
      assert.equal(counts.binding, 1, `${name}: binding-checked exactly once`);
      assert.equal('artifact' in decision, false, `${name}: the cross-wired artifact never executes`);
    }
  });

  test('the parse is budget-capped: over-budget edited prose ABORTs with ZERO parse calls', async () => {
    const forbidden = makeForbiddenParse();
    const decision = await rd.rederiveFromProse({
      editedProse: 'x'.repeat(100),
      groundedSources: makeGroundedSources(),
      parse: forbidden.parse,
      maxInputChars: 64,
    });

    assert.equal(decision.outcome, 'ABORT');
    assert.equal(decision.parseCalls, 0);
    assert.equal(forbidden.calls(), 0, 'an over-budget input never spends an LLM call');
    assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP);
    assert.match(decision.abort.reason, /budget/);
  });

  test('an oversized parse emission is refused by the output budget cap', async () => {
    const counting = makeCountingParse(() => {
      const artifact = makeFullArtifact();
      artifact.scope.statement = 'y'.repeat(10_000);
      return artifact;
    });
    const decision = await rd.rederiveFromProse({
      editedProse: rewordBranchEdit(r.renderPlanProse(makeFullArtifact())),
      groundedSources: makeGroundedSources(),
      parse: counting.parse,
      maxOutputChars: 2_000,
    });

    assert.equal(decision.outcome, 'ABORT');
    assert.equal(decision.parseCalls, 1);
    assert.match(decision.abort.reason, /output budget/);
    assert.equal('artifact' in decision, false);
  });

  test('a throwing parse fails to ABORT — the error never escapes and the call is never retried', async () => {
    let calls = 0;
    const decision = await rd.rederiveFromProse({
      editedProse: rewordBranchEdit(r.renderPlanProse(makeFullArtifact())),
      groundedSources: makeGroundedSources(),
      parse: async () => {
        calls += 1;
        throw new Error('LLM transport exploded');
      },
    });

    assert.equal(decision.outcome, 'ABORT');
    assert.equal(decision.parseCalls, 1);
    assert.equal(calls, 1, 'no retry — the bounded parse is attempted exactly once');
    assert.equal(decision.abort.stamp, rd.REDERIVE_ABORT_STAMP);
    assert.match(decision.abort.reason, /LLM transport exploded/);
  });

  test('word-for-word means whitespace-tolerant verbatim — never semantic', () => {
    const grounded = makeGroundedSources();
    const draft = grounded['notes/clinical-draft.md'];

    assert.equal(vac.isVerbatimSpan('dosage hallucination', draft), true, 'exact span');
    assert.equal(
      vac.isVerbatimSpan('retrieval-augmented generation for clinical decision support in real wards', draft),
      true,
      'a span crossing the source line wrap still matches',
    );
    assert.equal(
      vac.isVerbatimSpan('dosage  hallucination', draft),
      true,
      'whitespace runs in the quote are tolerated',
    );
    assert.equal(vac.isVerbatimSpan('Dosage hallucination', draft), false, 'case is significant');
    assert.equal(
      vac.isVerbatimSpan('dosage hallucinations', draft),
      false,
      'a near-miss inflection is not verbatim',
    );
    assert.equal(
      vac.isVerbatimSpan('hallucinated dosage risks', draft),
      false,
      'a paraphrase is never matched semantically',
    );
    assert.equal(vac.isVerbatimSpan('', draft), false, 'an empty quote never matches');
    assert.equal(vac.isVerbatimSpan('   ', draft), false, 'a blank quote never matches');
  });

  test('word-for-word is DEFINED: min quote length reuses lit-review\'s src/quoteExtractor.mjs constant (10)', () => {
    assert.equal(
      vac.DEFAULT_MIN_QUOTE_LENGTH,
      LITREVIEW_MIN_QUOTE_LENGTH,
      'the shared check reuses literature-review\'s existing minimum (src/quoteExtractor.mjs:14)',
    );
    assert.equal(vac.DEFAULT_MIN_QUOTE_LENGTH, 10);

    const draft = makeGroundedSources()['notes/clinical-draft.md'];
    assert.equal(
      vac.isVerbatimSpan('dosage', draft),
      false,
      'a sub-minimum span (< 10 collapsed chars) is an anchor FAILURE even though verbatim',
    );
    assert.equal(
      vac.isVerbatimSpan('real ward', draft),
      false,
      'a 9-char verbatim span is still sub-minimum',
    );
    assert.equal(vac.isVerbatimSpan('point of care', draft), true, 'a >=10-char aligned span passes');
    assert.equal(
      vac.classifyVerbatimSpan('dosage', draft).ok,
      false,
      'classifyVerbatimSpan refuses sub-minimum spans',
    );
    assert.match(vac.classifyVerbatimSpan('dosage', draft).reason, /minimum/);
  });

  test('word-for-word is DEFINED: the match must be token-boundary-aligned — a mid-word span is an anchor FAILURE', () => {
    const grounded = makeGroundedSources();
    const draft = grounded['notes/clinical-draft.md'];

    assert.equal(
      vac.isVerbatimSpan('osage hallucination', draft),
      false,
      'a span starting mid-word ("d|osage") is a failure despite being a >=10-char substring',
    );
    assert.equal(
      vac.isVerbatimSpan('dosage hallucinatio', draft),
      false,
      'a span ending mid-word ("hallucinatio|n") is a failure',
    );
    assert.equal(
      vac.isVerbatimSpan('acceptable latency at two seconds', grounded['notes/corpus-notes.md']),
      true,
      'a span ending at punctuation ("seconds.") is boundary-aligned — punctuation is not a word character',
    );
    assert.match(vac.classifyVerbatimSpan('osage hallucination', draft).reason, /token-boundary|mid-word/);

    // The failure surfaces through verbatimAnchorCheck as an anchor FAILURE, not a pass.
    const subMinimum = makeFullArtifact();
    subMinimum.branches[0].anchors[0].quote = 'dosage';
    const subRes = vac.verbatimAnchorCheck(subMinimum, grounded);
    assert.equal(subRes.ok, false);
    assert.ok(
      subRes.failures.some((f) => f.path === 'branches[0].anchors[0]' && /minimum/.test(f.reason)),
      'the sub-minimum anchor fails with a reason naming the minimum-length rule',
    );

    const midWord = makeFullArtifact();
    midWord.branches[0].anchors[0].quote = 'osage hallucination as';
    const midRes = vac.verbatimAnchorCheck(midWord, grounded);
    assert.equal(midRes.ok, false);
    assert.ok(
      midRes.failures.some(
        (f) => f.path === 'branches[0].anchors[0]' && /token-boundary|mid-word/.test(f.reason),
      ),
      'the mid-word anchor fails with a reason naming the token-boundary rule',
    );
  });

  test('re-derive never mutates its inputs', async () => {
    const derived = makeFullArtifact();
    const grounded = makeGroundedSources();
    const edited = rewordBranchEdit(r.renderPlanProse(derived));
    const derivedBytes = JSON.stringify(derived);
    const groundedBytes = JSON.stringify(grounded);

    await rd.resolveApprovedPlan({
      derivedArtifact: derived,
      approvedProse: edited,
      groundedSources: grounded,
      parse: async () => artifactWithRewordedBranch(),
    });

    assert.strictEqual(JSON.stringify(derived), derivedBytes);
    assert.strictEqual(JSON.stringify(grounded), groundedBytes);
  });
});
