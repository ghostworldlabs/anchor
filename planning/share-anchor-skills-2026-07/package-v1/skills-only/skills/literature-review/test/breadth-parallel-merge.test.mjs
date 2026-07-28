// test/breadth-parallel-merge.test.mjs — Wave 3: parallel per-facet workers + merge/dedupe.
//
// Pins IMPLEMENTATION-PLAN.md Wave 3 acceptance:
//   • APPROVED plan with 2 facets + overlapping paper identities → merged corpus
//     has one entry per stable identity; merge order is facet.order then paper id.
//   • One facet worker fails mid-gather → honest error stamp; siblings complete
//     and still contribute to the merge.
//   • Default concurrency: ≥3 facets scheduled → at most 2–3 workers concurrent.
//
// Also pins: multi-seed S shared across facets; ConcurrencyManager scheduling;
// optional IsolatedWorker stack via injectable workerFactory.

import { test, describe } from 'node:test';
import assert from 'node:assert';
import { EventEmitter } from 'node:events';

import {
  runPostApproveBreadth,
  mergeBreadthCorpus,
  resolveFacetConcurrency,
  paperIdentityKey,
  DEFAULT_FACET_CONCURRENCY,
  BREADTH_STAGE_EVENTS,
  BREADTH_STAGE_VERSION,
} from '../src/breadthStage.mjs';
import { BREADTH_STAMPS } from '../src/facetsFromPlan.mjs';
import { ConcurrencyManager } from '../src/concurrencyManager.mjs';

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Minimal plan-shaped fixture with N branch questions. */
function planWithBranches(questions) {
  return {
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Map evidence on a topic.',
      axis: 'A candidate is falsified without a replicated benchmark.',
      anchors: [{ sourceId: 'notes.md', quote: 'topic' }],
    },
    branches: questions.map((question) => ({
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

const MULTI_SEEDS = Object.freeze([
  Object.freeze({ idType: 'doi', id: '10.1000/a', title: 'Seed Alpha' }),
  Object.freeze({ idType: 'arxiv', id: '2401.00001', title: 'Seed Beta' }),
]);

describe('Wave 3 — surface: concurrency defaults + merge helpers', () => {
  test('default facet concurrency is in the plan band ≤2–3', () => {
    assert.ok(
      DEFAULT_FACET_CONCURRENCY >= 2 && DEFAULT_FACET_CONCURRENCY <= 3,
      `DEFAULT_FACET_CONCURRENCY=${DEFAULT_FACET_CONCURRENCY} must be in [2,3]`,
    );
    assert.equal(resolveFacetConcurrency(undefined), DEFAULT_FACET_CONCURRENCY);
    assert.equal(resolveFacetConcurrency(3), 3);
    assert.equal(resolveFacetConcurrency(0), DEFAULT_FACET_CONCURRENCY);
    assert.equal(resolveFacetConcurrency('nope'), DEFAULT_FACET_CONCURRENCY);
  });

  test('paperIdentityKey uses exact paperId (no fuzzy merge key)', () => {
    assert.equal(paperIdentityKey({ paperId: 'P1' }), 'paperId:P1');
    assert.equal(paperIdentityKey({ paperId: 'P1' }, 9), 'paperId:P1');
    assert.equal(paperIdentityKey({ title: 'no id' }, 3), 'no-id:3');
    assert.notEqual(paperIdentityKey({}, 0), paperIdentityKey({}, 1));
  });

  test('mergeBreadthCorpus is pure: facet.order then paperId; exact paperId dedupe', () => {
    const facetResults = [
      {
        facetId: 'facet:1',
        order: 1,
        hits: [
          { paperId: 'paper-z', title: 'Z from facet1' },
          { paperId: 'paper-shared', title: 'Shared from facet1 (kept — lower order)' },
        ],
        error: null,
      },
      {
        facetId: 'facet:0',
        order: 0,
        hits: [
          { paperId: 'paper-a', title: 'A from facet0' },
          { paperId: 'paper-shared', title: 'Shared from facet0 (should win)' },
        ],
        error: null,
      },
    ];
    // Deliberately reverse input order — merge must not depend on array order.
    const corpus = mergeBreadthCorpus(facetResults);
    assert.equal(corpus.totalHitsSeen, 4);
    assert.equal(corpus.uniqueCount, 3);
    assert.deepStrictEqual(
      corpus.entries.map((e) => e.paperId),
      ['paper-a', 'paper-shared', 'paper-z'],
      'merge order: facet.order 0 (a, shared) then facet.order 1 (z); shared kept once',
    );
    assert.equal(corpus.entries[1].sourceFacetId, 'facet:0');
    assert.equal(corpus.entries[1].title, 'Shared from facet0 (should win)');
    assert.equal(corpus.merges.length, 1);
    assert.equal(corpus.merges[0].paperId, 'paper-shared');
    assert.equal(corpus.merges[0].keptFacetId, 'facet:0');
    assert.deepStrictEqual(corpus.merges[0].absorbedFacetIds, ['facet:1']);
  });

  test('breadth stage version is Wave-3 (parallel + merge)', () => {
    assert.equal(BREADTH_STAGE_VERSION, 'breadth-stage/2');
  });
});

describe('Wave 3 — GWT: 2 facets + overlapping papers → single corpus entry per identity', () => {
  test('acceptance: parallel breadth gather + merge yields one entry per stable paperId; order facet.order then paper id', async () => {
    const plan = planWithBranches([
      'What does scaling law literature say about compute-optimal training?',
      'Which evaluation protocols detect train-test contamination?',
    ]);

    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: MULTI_SEEDS,
      gatherFacet: async ({ facet, seeds }) => {
        // Shared multi-seed S on every facet (not |S|×|facets|).
        assert.equal(seeds.length, MULTI_SEEDS.length);
        // Overlapping identity "paper-overlap" appears in BOTH facets.
        const base = [
          {
            paperId: 'paper-overlap',
            title: `Overlap seen by ${facet.id}`,
            year: 2024,
          },
          {
            paperId: `paper-only-${facet.order}`,
            title: `Unique to order ${facet.order}`,
            year: 2023,
          },
        ];
        // Within-facet paperId order is not sorted yet; merge must sort.
        if (facet.order === 0) {
          return {
            hits: [base[1], base[0]],
            seedCount: seeds.length,
            resolvableSeedCount: seeds.length,
            preBiasCount: 2,
            scopeBias: facet.question,
          };
        }
        return {
          hits: base,
          seedCount: seeds.length,
          resolvableSeedCount: seeds.length,
          preBiasCount: 2,
          scopeBias: facet.question,
        };
      },
    });

    assert.equal(outcome.ran, true);
    assert.equal(outcome.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(outcome.facets.length, 2);
    assert.equal(outcome.facetResults.length, 2);
    // facetResults ordered by facet.order regardless of completion order.
    assert.equal(outcome.facetResults[0].order, 0);
    assert.equal(outcome.facetResults[1].order, 1);

    // Each facet saw 2 hits including the overlap → 4 hits seen, 3 unique.
    assert.equal(outcome.corpus.totalHitsSeen, 4);
    assert.equal(outcome.corpus.uniqueCount, 3);
    assert.deepStrictEqual(
      outcome.corpus.entries.map((e) => e.paperId),
      ['paper-only-0', 'paper-overlap', 'paper-only-1'],
      'merge order: facet.order then paperId; overlap once',
    );
    const overlap = outcome.corpus.entries.find((e) => e.paperId === 'paper-overlap');
    assert.equal(overlap.sourceFacetOrder, 0, 'first facet.order wins the kept entry');
    assert.equal(outcome.corpus.merges.length, 1);
    assert.equal(outcome.corpus.merges[0].paperId, 'paper-overlap');

    // Shared S identity across gathers.
    assert.equal(outcome.sharedSeeds.length, 2);
    assert.equal(outcome.concurrency, DEFAULT_FACET_CONCURRENCY);
  });
});

describe('Wave 3 — GWT: one facet fails; siblings complete and merge', () => {
  test('acceptance: failed facet records honest error; other facets contribute to corpus', async () => {
    const plan = planWithBranches([
      'Facet zero succeeds',
      'Facet one explodes',
      'Facet two succeeds',
    ]);

    let live = 0;
    let observedMax = 0;
    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: MULTI_SEEDS,
      options: { concurrency: 3 },
      gatherFacet: async ({ facet, seeds }) => {
        live += 1;
        observedMax = Math.max(observedMax, live);
        await wait(15);
        live -= 1;
        if (facet.order === 1) {
          throw new Error(`simulated gather failure for ${facet.id}`);
        }
        return {
          hits: Object.freeze([
            { paperId: `ok-${facet.order}`, title: facet.question },
            { paperId: 'paper-shared-ok', title: 'Seen by successful facets' },
          ]),
          seedCount: seeds.length,
          resolvableSeedCount: seeds.length,
          preBiasCount: 2,
          scopeBias: facet.question,
        };
      },
    });

    assert.equal(outcome.ran, true);
    assert.equal(outcome.facetResults.length, 3);

    const failed = outcome.facetResults.find((r) => r.order === 1);
    assert.ok(failed.error, 'failed facet must carry an honest error stamp');
    assert.match(failed.error, /simulated gather failure/);
    assert.deepStrictEqual(failed.hits, []);

    const ok0 = outcome.facetResults.find((r) => r.order === 0);
    const ok2 = outcome.facetResults.find((r) => r.order === 2);
    assert.equal(ok0.error, null);
    assert.equal(ok2.error, null);
    assert.equal(ok0.hits.length, 2);
    assert.equal(ok2.hits.length, 2);

    // DONE events: one with error, two without.
    const done = outcome.events.filter((e) => e.type === BREADTH_STAGE_EVENTS.FACET_GATHER_DONE);
    assert.equal(done.length, 3);
    assert.equal(done.filter((e) => e.error).length, 1);
    assert.equal(done.filter((e) => e.error == null).length, 2);

    // Corpus only from successful facets (shared deduped once).
    assert.equal(outcome.corpus.uniqueCount, 3); // ok-0, paper-shared-ok, ok-2
    assert.deepStrictEqual(
      outcome.corpus.entries.map((e) => e.paperId).sort(),
      ['ok-0', 'ok-2', 'paper-shared-ok'].sort(),
    );
    assert.ok(
      !outcome.corpus.entries.some((e) => e.sourceFacetOrder === 1),
      'failed facet must not contribute corpus entries',
    );
    assert.ok(observedMax >= 1);
  });
});

describe('Wave 3 — GWT: concurrency cap enforced for ≥3 facets', () => {
  test('acceptance: default concurrency settings — at most DEFAULT_FACET_CONCURRENCY workers concurrent', async () => {
    const plan = planWithBranches([
      'Facet A concurrency probe',
      'Facet B concurrency probe',
      'Facet C concurrency probe',
      'Facet D concurrency probe',
    ]);
    assert.ok(plan.branches.length >= 3);

    let live = 0;
    let observedMax = 0;
    const started = [];

    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: MULTI_SEEDS,
      // Default concurrency (do not pass options.concurrency).
      gatherFacet: async ({ facet, seeds }) => {
        live += 1;
        observedMax = Math.max(observedMax, live);
        started.push(facet.id);
        await wait(40);
        live -= 1;
        return {
          hits: [{ paperId: `p-${facet.order}`, title: facet.question }],
          seedCount: seeds.length,
          resolvableSeedCount: seeds.length,
          preBiasCount: 1,
          scopeBias: facet.question,
        };
      },
    });

    assert.equal(outcome.ran, true);
    assert.equal(outcome.facetResults.length, 4);
    assert.equal(outcome.concurrency, DEFAULT_FACET_CONCURRENCY);
    assert.ok(
      observedMax <= DEFAULT_FACET_CONCURRENCY,
      `observed ${observedMax} concurrent facet gathers under default cap ${DEFAULT_FACET_CONCURRENCY}`,
    );
    assert.ok(
      outcome.maxActive <= DEFAULT_FACET_CONCURRENCY,
      `manager.maxActive ${outcome.maxActive} must not exceed cap ${DEFAULT_FACET_CONCURRENCY}`,
    );
    // Cap is meaningful: with 4 facets and hold time, we should saturate the limit.
    assert.equal(
      outcome.maxActive,
      DEFAULT_FACET_CONCURRENCY,
      'four facets should fully saturate the default concurrency cap',
    );
    assert.ok(DEFAULT_FACET_CONCURRENCY <= 3, 'plan: default cap ≤2–3');
    assert.equal(started.length, 4);
  });

  test('explicit concurrency: 3 is still within the plan band and is enforced', async () => {
    const plan = planWithBranches(['q0', 'q1', 'q2', 'q3', 'q4']);
    let live = 0;
    let observedMax = 0;
    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: MULTI_SEEDS,
      options: { concurrency: 3 },
      gatherFacet: async ({ facet }) => {
        live += 1;
        observedMax = Math.max(observedMax, live);
        await wait(25);
        live -= 1;
        return { hits: [{ paperId: `x-${facet.order}` }], seedCount: 2, scopeBias: facet.question };
      },
    });
    assert.equal(outcome.concurrency, 3);
    assert.ok(observedMax <= 3);
    assert.equal(outcome.maxActive, 3);
  });
});

describe('Wave 3 — IsolatedWorker stack seam (injectable workerFactory)', () => {
  test('when workerFactory is provided, each facet runs through the worker slot under the concurrency cap', async () => {
    const plan = planWithBranches(['worker facet 0', 'worker facet 1', 'worker facet 2']);
    let live = 0;
    let observedMax = 0;
    let workerSeq = 0;
    const startedOrders = [];

    function fakeWorkerFactory({ input }) {
      const worker = new EventEmitter();
      worker.workerId = `fake-facet-${workerSeq++}`;
      worker.state = 'created';
      worker.run = () =>
        new Promise((resolve, reject) => {
          worker.state = 'running';
          live += 1;
          observedMax = Math.max(observedMax, live);
          startedOrders.push(input.facet.order);
          setTimeout(() => {
            live -= 1;
            if (input.facet.order === 1) {
              worker.state = 'failed';
              reject(new Error(`worker failed for order ${input.facet.order}`));
              return;
            }
            worker.state = 'completed';
            resolve({
              hits: [{ paperId: `w-${input.facet.order}`, title: input.facet.question }],
              seedCount: input.seeds.length,
              resolvableSeedCount: input.seeds.length,
              preBiasCount: 1,
              scopeBias: input.facet.question,
            });
          }, 20);
        });
      return worker;
    }

    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: MULTI_SEEDS,
      options: { concurrency: 2 },
      workerFactory: fakeWorkerFactory,
      taskModule: 'fake-task-module',
    });

    assert.equal(outcome.ran, true);
    assert.equal(outcome.facetResults.length, 3);
    assert.ok(outcome.facetResults[1].error);
    assert.match(outcome.facetResults[1].error, /worker failed for order 1/);
    assert.equal(outcome.facetResults[0].error, null);
    assert.equal(outcome.facetResults[2].error, null);
    assert.ok(observedMax <= 2);
    assert.equal(outcome.maxActive, 2);
    assert.equal(outcome.corpus.uniqueCount, 2);
    assert.deepStrictEqual(
      outcome.corpus.entries.map((e) => e.paperId),
      ['w-0', 'w-2'],
    );
    assert.equal(startedOrders.length, 3);
  });
});

describe('Wave 3 — ConcurrencyManager is the engine-owned cap (not Foreman WorkerPool)', () => {
  test('breadth stage imports and saturates ConcurrencyManager independently', async () => {
    // Sanity: the same class MatrixScheduler uses is what we bound.
    const mgr = new ConcurrencyManager({ limit: 2 });
    let live = 0;
    let max = 0;
    await Promise.all(
      [1, 2, 3, 4].map((i) =>
        mgr.run(async () => {
          live += 1;
          max = Math.max(max, live);
          await wait(10);
          live -= 1;
          return i;
        }),
      ),
    );
    assert.equal(max, 2);
    assert.equal(mgr.maxActive, 2);
  });
});
