// test/breadth-honesty-telemetry.test.mjs — Wave 5: breadth honesty stamps in
// run telemetry for literature-review and researchPrime.
//
// Pins IMPLEMENTATION-PLAN.md Wave 5 acceptance:
//   • multi-facet lit-review + multi-branch RP runs stamp breadth stage
//     (from-branches / none / facet errors) with no invented facets;
//   • partial-failure sets incompleteCoverage + facetErrors;
//   • records are pure, assertable, and attachable to run records.
//
// Does not weaken or re-run full dual suites here — see dual-suite-gate.test.mjs.

import { test, describe } from 'node:test';
import assert from 'node:assert';

import {
  buildBreadthTelemetry,
  assertBreadthTelemetry,
  attachBreadthTelemetryToRunRecord,
  BREADTH_TELEMETRY_VERSION,
  BREADTH_TELEMETRY_FIELDS,
  BREADTH_TELEMETRY_SKILLS,
  MATRIX_SCHEDULER_V1_SCOPE,
  BreadthTelemetryError,
} from '../src/breadthTelemetry.mjs';
import { BREADTH_STAMPS } from '../src/facetsFromPlan.mjs';
import { runPostApproveBreadth } from '../src/breadthStage.mjs';
import {
  runPrePhase2FacetCoverage,
  attachFacetCoverageToRunRecord,
} from '../src/rpFacetCoverage.mjs';

function planWithBranches(questions) {
  return {
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Map evidence on a topic.',
      axis: 'A candidate is falsified without a replicated benchmark.',
      anchors: [{ sourceId: 'notes.md', quote: 'topic' }],
    },
    branches: questions.map((question, i) => ({
      id: `B${i + 1}`,
      question,
      rationale: `Why: ${question}`,
      anchors: [{ sourceId: 'notes.md', quote: question.slice(0, 12) || 'q' }],
    })),
    sourcesToBeat: [],
    foresight: {
      dropped: 'none',
      counterfactualCost: 'n/a',
      stamp: 'foresight recorded',
      anchors: [{ sourceId: 'notes.md', quote: 'none' }],
    },
    seeds: [],
  };
}

const SEEDS = Object.freeze([
  Object.freeze({ idType: 'doi', id: '10.1000/a', title: 'Seed Alpha' }),
  Object.freeze({ idType: 'arxiv', id: '2401.00001', title: 'Seed Beta' }),
]);

describe('Wave 5 — breadthTelemetry surface', () => {
  test('exports version, fields, skills, matrixScheduler v1.1 non-goal, and builders', () => {
    assert.equal(BREADTH_TELEMETRY_VERSION, 'breadth-telemetry/1');
    assert.ok(BREADTH_TELEMETRY_FIELDS.includes('stamp'));
    assert.ok(BREADTH_TELEMETRY_FIELDS.includes('incompleteCoverage'));
    assert.ok(BREADTH_TELEMETRY_FIELDS.includes('inventedFacets'));
    assert.deepStrictEqual([...BREADTH_TELEMETRY_SKILLS], ['literature-review', 'researchPrime']);
    assert.equal(MATRIX_SCHEDULER_V1_SCOPE.status, 'v1.1-non-goal-follow-on');
    assert.equal(MATRIX_SCHEDULER_V1_SCOPE.primaryForV1, false);
    assert.match(MATRIX_SCHEDULER_V1_SCOPE.note, /matrixScheduler/);
    assert.equal(typeof buildBreadthTelemetry, 'function');
    assert.equal(typeof assertBreadthTelemetry, 'function');
    assert.equal(typeof attachBreadthTelemetryToRunRecord, 'function');
  });

  test('null outcome → honest no-run record (no invented facets)', () => {
    const rec = buildBreadthTelemetry({ skill: 'literature-review', outcome: null });
    assert.equal(rec.ran, false);
    assert.equal(rec.stamp, null);
    assert.equal(rec.inventedFacets, false);
    assert.equal(rec.facetCount, 0);
    assert.equal(rec.incompleteCoverage, false);
    assertBreadthTelemetry(rec);
  });

  test('unknown skill throws', () => {
    assert.throws(
      () => buildBreadthTelemetry({ skill: 'gandalf', outcome: null }),
      BreadthTelemetryError,
    );
  });
});

describe('Wave 5 — GWT: multi-facet lit-review run stamps from-branches', () => {
  test('acceptance: successful multi-facet breadth → stamp from-branches, no invented facets, funnel present', async () => {
    const plan = planWithBranches([
      'What does scaling literature say about compute-optimal training?',
      'Which evaluation protocols detect train-test contamination?',
    ]);
    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: SEEDS,
      gatherFacet: async ({ facet, seeds }) => ({
        hits: [
          {
            paperId: `p-${facet.order}`,
            title: `Hit for ${facet.id}`,
            year: 2024,
            abstract: facet.question,
          },
        ],
        seedCount: seeds.length,
        resolvableSeedCount: seeds.length,
        preBiasCount: 1,
        scopeBias: facet.question,
      }),
    });

    const telemetry = buildBreadthTelemetry({
      outcome,
      skill: 'literature-review',
    });

    assert.equal(telemetry.skill, 'literature-review');
    assert.equal(telemetry.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(telemetry.ran, true);
    assert.equal(telemetry.inventedFacets, false);
    assert.equal(telemetry.facetCount, 2);
    assert.equal(telemetry.attempted, 2);
    assert.equal(telemetry.succeeded, 2);
    assert.equal(telemetry.failed, 0);
    assert.equal(telemetry.incompleteCoverage, false);
    assert.equal(telemetry.facetErrors.length, 0);
    assert.ok(telemetry.funnel);
    assert.equal(telemetry.funnel.uniqueCount, 2);
    assert.equal(telemetry.funnel.totalHitsSeen, 2);

    const runRecord = attachBreadthTelemetryToRunRecord({ runId: 'lit-1' }, telemetry);
    assert.equal(runRecord.breadthTelemetry.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(runRecord.breadthTelemetryVersion, BREADTH_TELEMETRY_VERSION);
  });
});

describe('Wave 5 — GWT: empty facets stamp none; facet failures mark incompleteCoverage', () => {
  test('acceptance: APPROVED + 0 facets → breadth:none, no invented facets', async () => {
    const plan = planWithBranches([]);
    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: SEEDS,
      gatherFacet: async () => {
        throw new Error('gather must not run when facets are empty');
      },
    });
    const telemetry = buildBreadthTelemetry({ outcome, skill: 'literature-review' });
    assert.equal(telemetry.stamp, BREADTH_STAMPS.NONE);
    assert.equal(telemetry.ran, false);
    assert.equal(telemetry.reason, 'no-facets');
    assert.equal(telemetry.inventedFacets, false);
    assert.equal(telemetry.facetCount, 0);
    assert.equal(telemetry.incompleteCoverage, false);
  });

  test('acceptance: one facet fails → incompleteCoverage + facetErrors; stamp still from-branches', async () => {
    const plan = planWithBranches(['Facet zero succeeds', 'Facet one explodes']);
    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: SEEDS,
      gatherFacet: async ({ facet, seeds }) => {
        if (facet.order === 1) throw new Error(`simulated failure ${facet.id}`);
        return {
          hits: [{ paperId: 'ok', title: 'OK', year: 2024 }],
          seedCount: seeds.length,
          resolvableSeedCount: seeds.length,
          preBiasCount: 1,
          scopeBias: facet.question,
        };
      },
    });
    const telemetry = buildBreadthTelemetry({ outcome, skill: 'literature-review' });
    assert.equal(telemetry.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(telemetry.attempted, 2);
    assert.equal(telemetry.succeeded, 1);
    assert.equal(telemetry.failed, 1);
    assert.equal(telemetry.incompleteCoverage, true);
    assert.equal(telemetry.facetErrors.length, 1);
    assert.match(telemetry.facetErrors[0].error, /simulated failure/);
    assert.equal(telemetry.inventedFacets, false);
  });
});

describe('Wave 5 — GWT: multi-branch RP run stamps facetCoverage + breadthTelemetry', () => {
  test('acceptance: 2-branch RP coverage → from-branches on run record; no invented facets', async () => {
    const plan = planWithBranches([
      'RP coverage axis A: scaling laws',
      'RP coverage axis B: contamination protocols',
    ]);
    const coverage = await runPrePhase2FacetCoverage({
      planGateDecision: 'APPROVE',
      plan,
      seeds: SEEDS,
      gatherFacet: async ({ facet }) => ({
        hits: [
          {
            paperId: `rp-${facet.order}`,
            title: `RP hit ${facet.id}`,
            year: 2024,
          },
        ],
      }),
    });

    assert.equal(coverage.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(coverage.facetCoverage.stamp, BREADTH_STAMPS.FROM_BRANCHES);

    const runRecord = attachFacetCoverageToRunRecord({ phase: 'pre-phase-2' }, coverage);
    assert.ok(runRecord.facetCoverage);
    assert.ok(runRecord.breadthTelemetry);
    assert.equal(runRecord.breadthTelemetry.skill, 'researchPrime');
    assert.equal(runRecord.breadthTelemetry.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(runRecord.breadthTelemetry.facetCount, 2);
    assert.equal(runRecord.breadthTelemetry.inventedFacets, false);
    assert.equal(runRecord.breadthTelemetry.incompleteCoverage, false);
    assert.ok(runRecord.breadthTelemetry.funnel);
    assert.equal(runRecord.breadthTelemetry.funnel.uniqueCount, 2);
  });

  test('acceptance: RP empty branches → breadth:none; Phase-2 ready; no invented facets', async () => {
    const coverage = await runPrePhase2FacetCoverage({
      planGateDecision: 'APPROVE',
      plan: planWithBranches([]),
      seeds: SEEDS,
    });
    const runRecord = attachFacetCoverageToRunRecord({}, coverage);
    assert.equal(runRecord.breadthTelemetry.stamp, BREADTH_STAMPS.NONE);
    assert.equal(runRecord.breadthTelemetry.facetCount, 0);
    assert.equal(runRecord.breadthTelemetry.inventedFacets, false);
    assert.equal(coverage.phase2Ready, true);
  });

  test('acceptance: RP facet failure → incompleteCoverage stamped on run record', async () => {
    const plan = planWithBranches(['ok facet', 'boom facet']);
    const coverage = await runPrePhase2FacetCoverage({
      planGateDecision: 'APPROVE',
      plan,
      seeds: SEEDS,
      gatherFacet: async ({ facet }) => {
        if (facet.order === 1) throw new Error('rp facet boom');
        return { hits: [{ paperId: 'only-ok', title: 'Only OK', year: 2024 }] };
      },
    });
    const runRecord = attachFacetCoverageToRunRecord({}, coverage);
    assert.equal(runRecord.breadthTelemetry.incompleteCoverage, true);
    assert.equal(runRecord.breadthTelemetry.failed, 1);
    assert.equal(runRecord.breadthTelemetry.succeeded, 1);
    assert.match(runRecord.breadthTelemetry.facetErrors[0].error, /rp facet boom/);
  });
});

describe('Wave 5 — dishonest stamp combinations refuse to escape', () => {
  test('from-branches with zero facets throws', () => {
    assert.throws(
      () =>
        buildBreadthTelemetry({
          skill: 'literature-review',
          outcome: {
            ran: true,
            stamp: BREADTH_STAMPS.FROM_BRANCHES,
            reason: null,
            facets: [],
            facetResults: [],
            corpus: { totalHitsSeen: 0, uniqueCount: 0 },
          },
        }),
      BreadthTelemetryError,
    );
  });

  test('assertBreadthTelemetry rejects inventedFacets: true', () => {
    assert.throws(() => {
      assertBreadthTelemetry({
        telemetryVersion: BREADTH_TELEMETRY_VERSION,
        skill: 'literature-review',
        stamp: BREADTH_STAMPS.NONE,
        ran: false,
        reason: 'no-facets',
        inventedFacets: true,
        facetCount: 0,
        facetIds: [],
        attempted: 0,
        succeeded: 0,
        failed: 0,
        incompleteCoverage: false,
        facetErrors: [],
        funnel: null,
      });
    }, BreadthTelemetryError);
  });
});
