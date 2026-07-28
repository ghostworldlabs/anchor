// test/coverage-sidecar-advisory.test.mjs — Wave 3: the coverage receipt is an ADVISORY
// sidecar (trio-shared/brownfield-intake/renderCoverageSidecar.mjs, resolved via the
// Wave-1 pinned trio home — docs/DECISION-RECEIPT-shared-location.md §3).
//
// Pins the Wave-3 acceptance: the sidecar is emitted OUTSIDE the plan body (a separate
// display-only string the user is SHOWN but never asked to hand-edit), and removing or
// altering it — or the anchors it is derived from — NEVER affects the rendered plan body
// bytes. Coverage never enters the editable surface.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';

/** Corpus artifact: full plan with anchors on every element (fresh deep copy per call). */
function makeArtifact() {
  return structuredClone({
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Map the evidence on retrieval-augmented generation for clinical decision support.',
      axis: 'A candidate is falsified if it lacks a prospective clinical evaluation.',
      anchors: [
        {
          sourceId: 'notes/clinical-draft.md',
          quote: 'retrieval-augmented generation for clinical decision support',
        },
      ],
    },
    branches: [
      {
        question: 'Does retrieval grounding reduce hallucinated dosages?',
        rationale: 'The draft names dosage hallucination as the primary safety risk.',
        anchors: [{ sourceId: 'notes/clinical-draft.md', quote: 'dosage hallucination' }],
      },
      {
        question: 'Which retrieval corpus curation policies transfer across hospitals?',
        rationale: 'The notes flag cross-site transfer as unresolved.',
        anchors: [{ sourceId: 'notes/corpus-notes.md', quote: 'cross-site transfer' }],
      },
    ],
    sourcesToBeat: [
      {
        title: 'Zakka et al. 2024 (Almanac)',
        why: 'The strongest published clinical-RAG evaluation to date.',
        anchors: [{ sourceId: 'notes/corpus-notes.md', quote: 'strongest published clinical-RAG evaluation' }],
      },
    ],
    foresight: {
      dropped: 'A multimodal-imaging branch was dropped.',
      counterfactualCost: 'Misses radiology-report evidence if imaging becomes central.',
      stamp: 'foresight recorded at derive time',
      anchors: [{ sourceId: 'notes/clinical-draft.md', quote: 'multimodal imaging' }],
    },
    seeds: [
      {
        idType: 'doi',
        id: '10.1056/AIoa2300068',
        title: 'Almanac: Retrieval-Augmented Language Models for Clinical Medicine',
      },
      { idType: 'arxiv', id: '2305.09617', title: 'Towards Expert-Level Medical Question Answering' },
    ],
  });
}

/** Same plan CONTENT, but every anchor rewritten (different sourceIds and quotes). */
function makeArtifactWithAlteredAnchors() {
  const artifact = makeArtifact();
  let n = 0;
  const rewrite = (element) => {
    n += 1;
    element.anchors = [{ sourceId: `altered/source-${n}.md`, quote: `altered verbatim span ${n}` }];
  };
  rewrite(artifact.scope);
  artifact.branches.forEach(rewrite);
  artifact.sourcesToBeat.forEach(rewrite);
  rewrite(artifact.foresight);
  return artifact;
}

describe('Wave 3 — renderCoverageSidecar (advisory, display-only, outside the plan body)', () => {
  let v;
  let r;
  let sc;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    v = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
    r = await import(new URL('renderPlanProse.mjs', indexUrl).href);
    sc = await import(new URL('renderCoverageSidecar.mjs', indexUrl).href);
  });

  test('the corpus artifacts are schema-valid, including the altered-anchor variant', () => {
    assert.equal(v.validatePlanArtifact(makeArtifact()).ok, true);
    assert.equal(v.validatePlanArtifact(makeArtifactWithAlteredAnchors()).ok, true);
  });

  test('acceptance GWT: plan body bytes are IDENTICAL with and without the sidecar enabled', () => {
    const artifact = makeArtifact();
    const withSidecar = r.renderPlanPresentation(artifact, { includeCoverageSidecar: true });
    const withoutSidecar = r.renderPlanPresentation(artifact, { includeCoverageSidecar: false });

    assert.strictEqual(
      withSidecar.planBody,
      withoutSidecar.planBody,
      'enabling the sidecar must not change one byte of the editable plan body',
    );
    assert.strictEqual(withSidecar.planBody, r.renderPlanProse(artifact));
    assert.equal(typeof withSidecar.coverageSidecar, 'string');
    assert.ok(withSidecar.coverageSidecar.length > 0);
    assert.strictEqual(withoutSidecar.coverageSidecar, null);
  });

  test('the sidecar is emitted OUTSIDE the plan body, as a separate display-only string', () => {
    const artifact = makeArtifact();
    const { planBody, coverageSidecar } = r.renderPlanPresentation(artifact);

    assert.notStrictEqual(coverageSidecar, planBody);
    assert.ok(
      !planBody.includes(sc.COVERAGE_SIDECAR_MARKER),
      'the plan body never contains the sidecar marker',
    );
    assert.ok(
      !planBody.includes(coverageSidecar),
      'the sidecar text is never embedded inside the plan body',
    );
    assert.ok(
      coverageSidecar.startsWith(`> ${sc.COVERAGE_SIDECAR_MARKER}`),
      'the sidecar announces itself with the advisory marker',
    );
  });

  test('the sidecar carries the advisory display-only framing (never a field to hand-edit)', () => {
    const sidecar = sc.renderCoverageSidecar(makeArtifact());
    assert.ok(sidecar.includes('display only'));
    assert.ok(sidecar.includes('never part of the editable plan body'));
    assert.ok(sidecar.includes('editing or removing it has no effect on the plan'));
  });

  test('the sidecar is derived from the anchors: every element covered, spans quoted', () => {
    const artifact = makeArtifact();
    const sidecar = sc.renderCoverageSidecar(artifact);

    assert.ok(sidecar.includes('- scope: 1 anchor(s)'));
    artifact.branches.forEach((branch, i) => {
      assert.ok(sidecar.includes(`- branches[${i}] (${branch.question}): 1 anchor(s)`));
    });
    artifact.sourcesToBeat.forEach((source, i) => {
      assert.ok(sidecar.includes(`- sourcesToBeat[${i}] (${source.title}): 1 anchor(s)`));
    });
    assert.ok(sidecar.includes('- foresight: 1 anchor(s)'));
    assert.ok(
      sidecar.includes('- seeds: 2 seed(s) — user-supplied identity, no anchors by design'),
    );

    const anchors = [
      ...artifact.scope.anchors,
      ...artifact.branches.flatMap((b) => b.anchors),
      ...artifact.sourcesToBeat.flatMap((s) => s.anchors),
      ...artifact.foresight.anchors,
    ];
    for (const anchor of anchors) {
      assert.ok(sidecar.includes(`- ${anchor.sourceId}: "${anchor.quote}"`));
    }
  });

  test('acceptance GWT: altering the anchors changes the sidecar but NEVER the plan body bytes', () => {
    const original = makeArtifact();
    const altered = makeArtifactWithAlteredAnchors();

    assert.strictEqual(
      r.renderPlanProse(altered),
      r.renderPlanProse(original),
      'anchor content must be invisible to the editable plan body',
    );
    assert.notStrictEqual(
      sc.renderCoverageSidecar(altered),
      sc.renderCoverageSidecar(original),
      'the sidecar IS derived from the anchors, so it must reflect the alteration',
    );
  });

  test('removing or altering the emitted sidecar text has no effect on the plan body', () => {
    const artifact = makeArtifact();
    const before = r.renderPlanPresentation(artifact);

    // A user "hand-edits" or discards the displayed sidecar — a display-only copy.
    const tampered = before.coverageSidecar.replace(/anchor/g, 'HAND-EDITED');
    assert.notStrictEqual(tampered, before.coverageSidecar);

    const after = r.renderPlanPresentation(artifact);
    assert.strictEqual(after.planBody, before.planBody);
    assert.strictEqual(after.coverageSidecar, before.coverageSidecar);
    assert.strictEqual(r.renderPlanProse(artifact), before.planBody);
  });

  test('the sidecar renders deterministically: two calls are byte-identical', () => {
    const artifact = makeArtifact();
    assert.strictEqual(sc.renderCoverageSidecar(artifact), sc.renderCoverageSidecar(artifact));
    assert.strictEqual(sc.renderCoverageSidecar(makeArtifact()), sc.renderCoverageSidecar(artifact));
  });

  test('empty collections still render an honest sidecar (zero seeds reported as such)', () => {
    const artifact = makeArtifact();
    artifact.branches = [];
    artifact.sourcesToBeat = [];
    artifact.seeds = [];
    const sidecar = sc.renderCoverageSidecar(artifact);
    assert.ok(sidecar.includes('- scope: 1 anchor(s)'));
    assert.ok(sidecar.includes('- foresight: 1 anchor(s)'));
    assert.ok(
      sidecar.includes('- seeds: 0 seed(s) — user-supplied identity, no anchors by design'),
    );
    assert.ok(!sidecar.includes('- branches['));
    assert.ok(!sidecar.includes('- sourcesToBeat['));
  });

  test('a schema-invalid artifact is refused (the sidecar never renders garbage coverage)', () => {
    const noAnchors = makeArtifact();
    noAnchors.scope.anchors = [];
    assert.throws(() => sc.renderCoverageSidecar(noAnchors), /scope\.anchors/);

    const withCoverageField = makeArtifact();
    withCoverageField.coverage = { hand: 'maintained' };
    assert.throws(() => sc.renderCoverageSidecar(withCoverageField), /advisory sidecar/);
  });
});
