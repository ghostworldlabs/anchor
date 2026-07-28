// test/breadth-stage.test.mjs — Wave 2: lit-review post-APPROVE breadth hook (sequential).
//
// Pins IMPLEMENTATION-PLAN.md Wave 2 acceptance:
//   • APPROVED + ≥1 facets + multi-seed S → facetsFromPlan first; per-facet gathers
//     use shared S (not |S|×|facets| cartesian); main-snowball marker only after breadth.
//   • APPROVED + 0 facets (breadth:none) → no invented facets; honest stamp; no gather.
//   • Plan not yet APPROVED → facet breadth gather does not run.
//   • CLI/path structural: post-APPROVE hook sits after the Stage-0 gate and before
//     the main performSnowballSearch call.

import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  runPostApproveBreadth,
  applyScopeBias,
  freezeSharedSeeds,
  BREADTH_STAGE_VERSION,
  BREADTH_STAGE_EVENTS,
  BREADTH_REQUIRES_STATUS,
} from '../src/breadthStage.mjs';
import { BREADTH_STAMPS } from '../src/facetsFromPlan.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.resolve(TEST_DIR, '..');

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

describe('Wave 2 — breadth stage surface', () => {
  test('exports version, event vocabulary, APPROVED gate constant, and helpers', () => {
    assert.equal(BREADTH_STAGE_VERSION, 'breadth-stage/2');
    assert.equal(BREADTH_REQUIRES_STATUS, 'APPROVED');
    assert.equal(typeof runPostApproveBreadth, 'function');
    assert.equal(typeof applyScopeBias, 'function');
    assert.equal(typeof freezeSharedSeeds, 'function');
    assert.deepStrictEqual(BREADTH_STAGE_EVENTS, {
      FACETS_MATERIALIZED: 'facets-materialized',
      FACET_GATHER_START: 'facet-gather-start',
      FACET_GATHER_DONE: 'facet-gather-done',
      BREADTH_SKIPPED: 'breadth-skipped',
      BREADTH_COMPLETE: 'breadth-complete',
    });
  });
});

describe('Wave 2 — applyScopeBias + freezeSharedSeeds', () => {
  test('scope bias re-ranks by facet-question token overlap (stable paperId ties)', () => {
    const candidates = [
      { paperId: 'p-low', title: 'Unrelated workshop notes', abstract: 'misc' },
      { paperId: 'p-high', title: 'Scaling laws for language models', abstract: 'compute scaling' },
      { paperId: 'p-mid', title: 'Language models overview', abstract: 'survey' },
    ];
    const ranked = applyScopeBias(candidates, 'language model scaling');
    assert.equal(ranked[0].paperId, 'p-high');
    assert.ok(ranked[0].scopeBiasScore >= ranked[1].scopeBiasScore);
    assert.equal(ranked[0].scopeBiasRank, 0);
    assert.equal(ranked[0].scopeBiasQuestion, 'language model scaling');
    assert.equal(ranked.length, 3, 'scope bias ranks; it does not invent or drop papers');
  });

  test('freezeSharedSeeds is read-only and preserves multi-seed identity order', () => {
    const frozen = freezeSharedSeeds(MULTI_SEEDS);
    assert.equal(frozen.length, 2);
    assert.equal(frozen[0].id, '10.1000/a');
    assert.equal(frozen[1].id, '2401.00001');
    assert.throws(() => {
      // @ts-expect-error intentional mutation attempt
      frozen.push({ idType: 'doi', id: 'x', title: 'nope' });
    });
  });
});

describe('Wave 2 — APPROVED + ≥1 facets: facets first, shared S, then complete before depth', () => {
  test('acceptance GWT: facetsFromPlan runs first; per-facet gathers share S; depth marker only after breadth', async () => {
    const plan = planWithBranches([
      'How do scaling laws behave under data filtering?',
      'What evaluation protocols survive held-out contamination?',
    ]);
    const gatherCalls = [];
    const timeline = [];

    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: MULTI_SEEDS,
      gatherFacet: async ({ facet, seeds }) => {
        gatherCalls.push({
          facetId: facet.id,
          question: facet.question,
          seedIds: seeds.map((s) => `${s.idType}:${s.id}`),
          seedRef: seeds,
        });
        timeline.push(`gather:${facet.id}`);
        return {
          hits: Object.freeze([{ paperId: `hit-for-${facet.id}`, title: facet.question, scopeBiasRank: 0 }]),
          seedCount: seeds.length,
          resolvableSeedCount: seeds.length,
          preBiasCount: 1,
          scopeBias: facet.question,
        };
      },
    });

    // Breadth ran; stamp from branches.
    assert.equal(outcome.ran, true);
    assert.equal(outcome.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(outcome.facets.length, 2);
    assert.equal(outcome.reason, null);

    // Event skeleton (Wave 3 parallel may interleave START/DONE across facets):
    // materialize first → both facets gather (START+DONE each) → complete last.
    const types = outcome.events.map((e) => e.type);
    assert.equal(types[0], BREADTH_STAGE_EVENTS.FACETS_MATERIALIZED);
    assert.equal(types[types.length - 1], BREADTH_STAGE_EVENTS.BREADTH_COMPLETE);
    assert.equal(outcome.events[0].facetCount, 2);
    assert.equal(
      types.filter((t) => t === BREADTH_STAGE_EVENTS.FACET_GATHER_START).length,
      2,
      'one START per facet',
    );
    assert.equal(
      types.filter((t) => t === BREADTH_STAGE_EVENTS.FACET_GATHER_DONE).length,
      2,
      'one DONE per facet',
    );

    // Exactly one gather per facet (not |S|×|facets| cartesian jobs).
    assert.equal(gatherCalls.length, 2, 'one gather per facet');
    const expectedSeedIds = ['doi:10.1000/a', 'arxiv:2401.00001'];
    for (const call of gatherCalls) {
      assert.deepStrictEqual(
        call.seedIds,
        expectedSeedIds,
        'every facet gather must receive the full shared multi-seed set S',
      );
    }
    // Same frozen snapshot identity across facets (shared S, not re-forked per facet).
    assert.strictEqual(gatherCalls[0].seedRef, gatherCalls[1].seedRef);
    assert.strictEqual(gatherCalls[0].seedRef, outcome.sharedSeeds);

    // Simulate caller's contract: main snowball/depth starts only after breadth completes.
    timeline.push('main-snowball');
    assert.equal(timeline[timeline.length - 1], 'main-snowball');
    assert.equal(timeline.length, 3, 'both facet gathers + main-snowball marker');
    assert.ok(
      timeline.includes(`gather:${outcome.facets[0].id}`),
      'first facet gathered before main snowball',
    );
    assert.ok(
      timeline.includes(`gather:${outcome.facets[1].id}`),
      'second facet gathered before main snowball',
    );
    assert.ok(
      types.indexOf(BREADTH_STAGE_EVENTS.BREADTH_COMPLETE) === types.length - 1,
      'breadth-complete is the terminal breadth event before main snowball',
    );
  });
});

describe('Wave 2 — APPROVED + 0 facets (breadth:none)', () => {
  test('acceptance GWT: no invented facets; honest stamp; gather never called; existing path free', async () => {
    const plan = planWithBranches([]);
    let gatherCalls = 0;

    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: MULTI_SEEDS,
      gatherFacet: async () => {
        gatherCalls += 1;
        return { hits: [] };
      },
    });

    assert.equal(outcome.ran, false);
    assert.equal(outcome.reason, 'no-facets');
    assert.equal(outcome.stamp, BREADTH_STAMPS.NONE);
    assert.deepStrictEqual(outcome.facets, []);
    assert.deepStrictEqual(outcome.facetResults, []);
    assert.equal(gatherCalls, 0, 'no invented facets means no gather work');
    assert.equal(outcome.events[0].type, BREADTH_STAGE_EVENTS.FACETS_MATERIALIZED);
    assert.equal(outcome.events[0].stamp, BREADTH_STAMPS.NONE);
    assert.equal(outcome.events[1].type, BREADTH_STAGE_EVENTS.BREADTH_SKIPPED);
    assert.equal(outcome.events[1].reason, 'no-facets');
    // Shared seeds may still be snapshotted for honesty; no cartesian expansion.
    assert.equal(outcome.sharedSeeds.length, MULTI_SEEDS.length);
  });

  test('all-unusable branches also stamp breadth:none without gather', async () => {
    const plan = planWithBranches(['', '   ']);
    let gatherCalls = 0;
    const outcome = await runPostApproveBreadth({
      planStatus: 'APPROVED',
      plan,
      seeds: MULTI_SEEDS,
      gatherFacet: async () => {
        gatherCalls += 1;
        return { hits: [] };
      },
    });
    assert.equal(outcome.ran, false);
    assert.equal(outcome.stamp, BREADTH_STAMPS.NONE);
    assert.equal(gatherCalls, 0);
  });
});

describe('Wave 2 — plan not yet APPROVED', () => {
  test('acceptance GWT: facet breadth gather does not run', async () => {
    const plan = planWithBranches(['Should this even gather?']);
    let gatherCalls = 0;

    for (const planStatus of ['HALTED', 'ABORTED', null, undefined, 'PENDING']) {
      gatherCalls = 0;
      const outcome = await runPostApproveBreadth({
        planStatus,
        plan,
        seeds: MULTI_SEEDS,
        gatherFacet: async () => {
          gatherCalls += 1;
          return { hits: [{ paperId: 'should-not-exist' }] };
        },
      });
      assert.equal(outcome.ran, false, `status ${planStatus} must not run breadth`);
      assert.equal(outcome.reason, 'plan-not-approved');
      assert.equal(outcome.stamp, null, 'facetsFromPlan is not consulted when not APPROVED');
      assert.deepStrictEqual(outcome.facets, []);
      assert.equal(gatherCalls, 0);
      assert.equal(outcome.events[0].type, BREADTH_STAGE_EVENTS.BREADTH_SKIPPED);
      assert.equal(outcome.events[0].reason, 'plan-not-approved');
    }
  });
});

describe('Wave 2 — CLI/path structural ordering (post-APPROVE hook before main snowball)', () => {
  test('bin/cli.mjs calls runPostApproveBreadth after Stage-0 unlock and before main performSnowballSearch', () => {
    const cliSrc = fs.readFileSync(path.join(SKILL_DIR, 'bin', 'cli.mjs'), 'utf8');

    assert.match(cliSrc, /runPostApproveBreadth/, 'CLI must wire the Wave-2 breadth hook');
    assert.match(cliSrc, /from ['"]\.\.\/src\/breadthStage\.mjs['"]/);

    const gateIdx = cliSrc.indexOf('stage0AllowsExecution(stage0)');
    const breadthIdx = cliSrc.indexOf('runPostApproveBreadth(');
    const snowballIdx = cliSrc.indexOf('performSnowballSearch(');

    assert.ok(gateIdx > -1, 'Stage-0 gate present');
    assert.ok(breadthIdx > -1, 'breadth hook invocation present');
    assert.ok(snowballIdx > -1, 'main snowball still present');
    assert.ok(gateIdx < breadthIdx, 'breadth hook must sit after the Stage-0 APPROVE gate');
    assert.ok(
      breadthIdx < snowballIdx,
      'breadth stage must complete (be invoked) before the main snowball call',
    );

    // Non-RUN Stage-0 still returns before breadth and snowball.
    assert.match(
      cliSrc,
      /if \(!stage0AllowsExecution\(stage0\)\)[\s\S]*?return;/,
      'non-APPROVED Stage-0 must return before post-APPROVE breadth',
    );
  });
});
