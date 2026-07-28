// test/rp-facet-coverage.test.mjs — Wave 4: researchPrime pre-Phase-2 facet coverage.
//
// Pins IMPLEMENTATION-PLAN.md Wave 4 acceptance:
//   • 2-branch approved plan post-plan-gate → run record includes facetCoverage
//     with both facets and hits BEFORE Phase-2 depth/verification starts.
//   • When oranges pruning runs with facetCoverage present → only answer-branches
//     are pruned; facets are not modeled or pruned as answer branches.
//   • Empty branches → honest no-breadth stamp; no silent facets; Phase-2 path proceeds.
//
// Exercises the skill-local implementation (src/rpFacetCoverage.mjs) and the RP
// seam (researchPrime/bin/facet-coverage.mjs) via the Wave-1 resolve helper.

import { test, describe } from 'node:test';
import assert from 'node:assert';

import {
  runPrePhase2FacetCoverage,
  answerPlanForOranges,
  runOrangesOnAnswerBranches,
  attachFacetCoverageToRunRecord,
  mergeCoverageHits,
  buildFacetCoverage,
  isFacetRecord,
  FACET_COVERAGE_VERSION,
  FACET_COVERAGE_EVENTS,
  FACET_COVERAGE_REQUIRES_DECISION,
} from '../src/rpFacetCoverage.mjs';
import { BREADTH_STAMPS } from '../src/facetsFromPlan.mjs';
import { importRp } from './_wave1-trio-resolve.mjs';

/** PlanArtifact-shaped fixture with N branch questions (and optional economics for oranges). */
function planWithBranches(questions, { withEconomics = false } = {}) {
  return {
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Map evidence on a topic.',
      axis: 'A candidate is falsified without a replicated benchmark.',
      anchors: [{ sourceId: 'notes.md', quote: 'topic' }],
    },
    branches: questions.map((question, i) => {
      const base = {
        id: `B${i + 1}`,
        question,
        rationale: `Why: ${question}`,
        anchors: [{ sourceId: 'notes.md', quote: question.slice(0, 12) || 'q' }],
      };
      if (withEconomics) {
        // Positive net for B1…; last branch wasteful so oranges can drop it.
        if (i === questions.length - 1 && questions.length >= 2) {
          return { ...base, est_value: 0, est_cost: 1, counterfactual_cost: 'wasted last branch' };
        }
        return { ...base, est_value: 10 - i, est_cost: 1 };
      }
      return base;
    }),
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

function hitFor(facetId, paperId, title) {
  return Object.freeze({ paperId, title, year: 2024, abstract: `${title} abstract` });
}

describe('Wave 4 — rpFacetCoverage module surface', () => {
  test('exports version, events, APPROVE gate, and helpers', () => {
    assert.equal(FACET_COVERAGE_VERSION, 'rp-facet-coverage/1');
    assert.equal(FACET_COVERAGE_REQUIRES_DECISION, 'APPROVE');
    assert.equal(typeof runPrePhase2FacetCoverage, 'function');
    assert.equal(typeof answerPlanForOranges, 'function');
    assert.equal(typeof runOrangesOnAnswerBranches, 'function');
    assert.equal(typeof attachFacetCoverageToRunRecord, 'function');
    assert.equal(typeof mergeCoverageHits, 'function');
    assert.equal(typeof buildFacetCoverage, 'function');
    assert.equal(typeof isFacetRecord, 'function');
    assert.deepStrictEqual(FACET_COVERAGE_EVENTS, {
      FACETS_MATERIALIZED: 'facets-materialized',
      FACET_GATHER_START: 'facet-gather-start',
      FACET_GATHER_DONE: 'facet-gather-done',
      COVERAGE_SKIPPED: 'coverage-skipped',
      COVERAGE_RECORDED: 'coverage-recorded',
      PHASE2_READY: 'phase2-ready',
    });
  });
});

describe('Wave 4 — GWT: 2-branch approved plan records facetCoverage before Phase-2', () => {
  test('run record includes facetCoverage with both facets and hits before phase2-ready', async () => {
    const plan = planWithBranches([
      'How do scaling laws behave under data filtering?',
      'What evaluation protocols survive held-out contamination?',
    ]);
    const timeline = [];
    let phase2Started = false;

    const outcome = await runPrePhase2FacetCoverage({
      planGateDecision: 'APPROVE',
      plan,
      gatherFacet: async ({ facet }) => {
        timeline.push(`gather:${facet.id}`);
        assert.equal(phase2Started, false, 'Phase-2 must not start during facet gather');
        return {
          hits: [
            hitFor(facet.id, `paper-${facet.id}`, `Evidence for ${facet.question}`),
            hitFor(facet.id, 'shared-overlap', 'Shared paper across facets'),
          ],
        };
      },
      log: (msg) => timeline.push(`log:${msg.slice(0, 40)}`),
    });

    // Mark Phase-2 start only after outcome says ready (caller's contract).
    assert.equal(outcome.phase2Ready, true);
    assert.equal(outcome.ran, true);
    phase2Started = true;
    timeline.push('phase2-depth-start');

    const eventTypes = outcome.events.map((e) => e.type);
    assert.ok(eventTypes.includes(FACET_COVERAGE_EVENTS.FACETS_MATERIALIZED));
    assert.ok(eventTypes.includes(FACET_COVERAGE_EVENTS.COVERAGE_RECORDED));
    assert.ok(eventTypes.includes(FACET_COVERAGE_EVENTS.PHASE2_READY));

    const recordedIdx = eventTypes.indexOf(FACET_COVERAGE_EVENTS.COVERAGE_RECORDED);
    const phase2Idx = eventTypes.indexOf(FACET_COVERAGE_EVENTS.PHASE2_READY);
    assert.ok(recordedIdx >= 0 && phase2Idx > recordedIdx, 'facetCoverage recorded before Phase-2 ready');

    // facetCoverage has both facets and hits
    const fc = outcome.facetCoverage;
    assert.ok(fc, 'facetCoverage must be present');
    assert.equal(fc.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(fc.facets.length, 2, 'both branches become facets');
    assert.ok(fc.hits.length >= 2, 'hits recorded for coverage');
    assert.ok(fc.facets.every((f) => isFacetRecord(f)), 'coverage axes are Facet records');

    // Run record attachment
    const runRecord = attachFacetCoverageToRunRecord(
      { stage: 'post-plan-gate', planHash: 'abc' },
      outcome,
    );
    assert.equal(runRecord.facetCoverage.facets.length, 2);
    assert.ok(Array.isArray(runRecord.facetCoverage.hits));
    assert.equal(runRecord.facetCoverage.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.ok(runRecord.coverageSubstrate);
    assert.equal(runRecord.coverageSubstrate.uniqueCount, fc.hits.length);

    // shared-overlap deduped once in merged hits
    const overlap = fc.hits.filter((h) => h.paperId === 'shared-overlap');
    assert.equal(overlap.length, 1, 'overlapping paper identity merges to one hit');

    assert.ok(timeline.includes('phase2-depth-start'));
    assert.ok(timeline.some((t) => t.startsWith('gather:')));
  });
});

describe('Wave 4 — GWT: oranges prunes answer-branches only; never facets', () => {
  test('answerPlanForOranges never surfaces facet records; runForesight only sees answer branches', async () => {
    const plan = planWithBranches(
      [
        'Sound research branch on scaling',
        'Wasteful branch that should be pruned',
      ],
      { withEconomics: true },
    );

    const coverage = await runPrePhase2FacetCoverage({
      planGateDecision: 'APPROVE',
      plan,
      gatherFacet: async ({ facet }) => ({
        hits: [hitFor(facet.id, `p-${facet.id}`, facet.question)],
      }),
    });
    assert.equal(coverage.facetCoverage.facets.length, 2);
    assert.ok(coverage.facetCoverage.facets.every(isFacetRecord));

    const orangesPlan = answerPlanForOranges(plan);
    assert.ok(Array.isArray(orangesPlan.branches));
    assert.equal(orangesPlan.branches.length, 2);
    // Facet-shaped records must not appear as oranges branches
    for (const b of orangesPlan.branches) {
      assert.equal(isFacetRecord(b), false, 'oranges branches must not be Facet records');
      assert.ok(!String(b?.id ?? '').startsWith('facet:'), 'oranges must not receive facet:* ids');
    }

    // Load real RP oranges and prove pruning only touches answer branches
    const oranges = await importRp('bin/oranges.mjs');
    const receipt = runOrangesOnAnswerBranches(plan, oranges.runForesight);
    assert.ok(receipt);
    assert.ok(Array.isArray(receipt.dropped));
    assert.ok(Array.isArray(receipt.kept));

    // Dropped/kept refer to answer-branch ids (B1/B2), never facet:* coverage axes
    for (const d of receipt.dropped) {
      assert.ok(!String(d.branch).startsWith('facet:'), 'oranges must not prune facet ids');
    }
    for (const k of receipt.kept) {
      assert.ok(!String(k).startsWith('facet:'), 'oranges kept set must not include facet ids');
    }

    // Facet coverage substrate remains intact after oranges — separate channel
    assert.equal(coverage.facetCoverage.facets.length, 2);
    assert.ok(coverage.facetCoverage.hits.length >= 1);

    // Injecting facets as branches would be wrong; prove the helper does not do it
    const wrongIfFacets = answerPlanForOranges({
      branches: coverage.facetCoverage.facets,
    });
    // If someone mistakenly put facets into plan.branches, isFacetRecord would flag them —
    // the normal path (answerPlanForOranges(plan)) does not.
    assert.equal(
      orangesPlan.branches.some(isFacetRecord),
      false,
      'normal plan path must not model facets as answer branches',
    );
    // Document the hazard: facets-as-branches would look like facets
    assert.ok(wrongIfFacets.branches.every(isFacetRecord));
  });
});

describe('Wave 4 — GWT: empty branches → honest stamp; Phase-2 proceeds', () => {
  test('empty branches: breadth:none, no silent facets, phase2Ready', async () => {
    const plan = planWithBranches([]);
    let gatherCalls = 0;
    const outcome = await runPrePhase2FacetCoverage({
      planGateDecision: 'APPROVE',
      plan,
      gatherFacet: async () => {
        gatherCalls += 1;
        return { hits: [] };
      },
    });

    assert.equal(outcome.ran, false);
    assert.equal(outcome.reason, 'no-facets');
    assert.equal(outcome.stamp, BREADTH_STAMPS.NONE);
    assert.equal(outcome.facets.length, 0);
    assert.equal(gatherCalls, 0, 'no gather when there are no facets');
    assert.equal(outcome.phase2Ready, true, 'existing Phase-2 path proceeds');
    assert.ok(outcome.facetCoverage);
    assert.equal(outcome.facetCoverage.stamp, BREADTH_STAMPS.NONE);
    assert.equal(outcome.facetCoverage.facets.length, 0);
    assert.equal(outcome.facetCoverage.hits.length, 0);

    const eventTypes = outcome.events.map((e) => e.type);
    assert.ok(eventTypes.includes(FACET_COVERAGE_EVENTS.FACETS_MATERIALIZED));
    assert.ok(eventTypes.includes(FACET_COVERAGE_EVENTS.COVERAGE_RECORDED));
    assert.ok(eventTypes.includes(FACET_COVERAGE_EVENTS.PHASE2_READY));
  });

  test('plan gate not APPROVE: coverage skipped; no invented facets', async () => {
    const plan = planWithBranches(['Would invent if run']);
    let gatherCalls = 0;
    const outcome = await runPrePhase2FacetCoverage({
      planGateDecision: 'EDIT',
      plan,
      gatherFacet: async () => {
        gatherCalls += 1;
        return { hits: [{ paperId: 'x' }] };
      },
    });
    assert.equal(outcome.ran, false);
    assert.equal(outcome.reason, 'plan-gate-not-approved');
    assert.equal(outcome.facetCoverage, null);
    assert.equal(outcome.facets.length, 0);
    assert.equal(gatherCalls, 0);
    assert.equal(outcome.phase2Ready, true);
  });
});

describe('Wave 4 — researchPrime seam re-exports the stage', () => {
  test('RP bin/facet-coverage.mjs loads and runs pre-Phase-2 coverage', async () => {
    const seam = await importRp('bin/facet-coverage.mjs');
    assert.equal(typeof seam.runPrePhase2FacetCoverage, 'function');
    assert.equal(typeof seam.runOrangesOnAnswerBranches, 'function');
    assert.equal(typeof seam.attachFacetCoverageToRunRecord, 'function');
    assert.equal(seam.RP_FACET_COVERAGE_SEAM, 'researchPrime/facet-coverage/1');

    const plan = planWithBranches(['RP seam branch A', 'RP seam branch B']);
    const outcome = await seam.runPrePhase2FacetCoverage({
      planGateDecision: 'APPROVE',
      plan,
      gatherFacet: async ({ facet }) => ({
        hits: [hitFor(facet.id, `rp-${facet.id}`, facet.question)],
      }),
    });
    assert.equal(outcome.ran, true);
    assert.equal(outcome.facetCoverage.facets.length, 2);
    assert.ok(outcome.facetCoverage.hits.length >= 2);

    const record = await seam.attachFacetCoverageToRunRecord({ runId: 'rp-test' }, outcome);
    assert.equal(record.facetCoverage.facets.length, 2);

    // Oranges via RP seam: real runForesight, answer branches only
    const receipt = await seam.runOrangesOnAnswerBranches(
      planWithBranches(['G1 sound', 'G2 waste'], { withEconomics: true }),
    );
    assert.ok(receipt);
    assert.ok(!JSON.stringify(receipt).includes('facet:'));
  });
});
