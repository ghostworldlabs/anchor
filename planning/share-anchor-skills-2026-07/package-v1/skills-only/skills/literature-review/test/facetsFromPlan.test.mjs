// test/facetsFromPlan.test.mjs — Wave 1: Facet materialization (facetsFromPlan).
//
// Pins the Wave-1 acceptance (IMPLEMENTATION-PLAN.md):
//   • N≥2 branches → exactly N facets, stamp breadth:from-branches, each
//     traces to a sourceBranchId; stable order.
//   • 0 / empty / unusable branches → no invented facets; stamp breadth:none
//     (axis never materializes Facet records).
//   • Same plan object twice → identical facet ids and order (deterministic).
// Pure helper only — no I/O, no pipeline wiring (Wave 2).

import { test, describe } from 'node:test';
import assert from 'node:assert';

import {
  facetsFromPlan,
  BREADTH_STAMPS,
  FACETS_FROM_PLAN_VERSION,
} from '../src/facetsFromPlan.mjs';

/** Minimal plan-shaped fixture with N branches (question-only is enough). */
function planWithBranches(questions, extra = {}) {
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
    ...extra,
  };
}

describe('Wave 1 — facetsFromPlan module surface', () => {
  test('exports pure mapper, stamp vocabulary, and version', () => {
    assert.equal(typeof facetsFromPlan, 'function');
    assert.equal(FACETS_FROM_PLAN_VERSION, 'facets-from-plan/1');
    assert.deepStrictEqual(
      { ...BREADTH_STAMPS },
      {
        FROM_BRANCHES: 'breadth:from-branches',
        AXIS_ONLY: 'breadth:axis-only',
        NONE: 'breadth:none',
      },
    );
  });
});

describe('Wave 1 — N≥2 branches → N facets (breadth:from-branches)', () => {
  test('acceptance GWT: N≥2 branches yield exactly N facets with sourceBranchId and from-branches stamp', () => {
    const plan = planWithBranches([
      'Do compute-optimal ratios transfer below 1B parameters?',
      'Which data-quality filters dominate the scaling exponent?',
      'Does multilingual transfer change the scaling curve?',
    ]);

    const result = facetsFromPlan(plan);

    assert.equal(result.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.equal(result.facets.length, 3);

    for (let i = 0; i < 3; i++) {
      const f = result.facets[i];
      assert.equal(typeof f.id, 'string');
      assert.ok(f.id.length > 0, 'facet.id must be non-empty');
      assert.equal(f.question, plan.branches[i].question);
      assert.equal(typeof f.sourceBranchId, 'string');
      assert.ok(f.sourceBranchId.length > 0, 'sourceBranchId must be non-empty');
      assert.equal(typeof f.order, 'number');
    }

    // Path-stable default ids when branches have no explicit id.
    assert.deepStrictEqual(
      result.facets.map((f) => f.sourceBranchId),
      ['branch:0', 'branch:1', 'branch:2'],
    );
    assert.deepStrictEqual(
      result.facets.map((f) => f.id),
      ['facet:branch:0', 'facet:branch:1', 'facet:branch:2'],
    );
  });

  test('stable order follows array index when branch.order is absent', () => {
    const plan = planWithBranches(['Q-alpha', 'Q-beta']);
    const { facets } = facetsFromPlan(plan);
    assert.deepStrictEqual(
      facets.map((f) => f.order),
      [0, 1],
    );
    assert.deepStrictEqual(
      facets.map((f) => f.question),
      ['Q-alpha', 'Q-beta'],
    );
  });

  test('explicit branch.id becomes sourceBranchId; facet.id is path-stable from it', () => {
    const plan = planWithBranches(['A?', 'B?']);
    plan.branches[0].id = 'br-alpha';
    plan.branches[1].id = 'br-beta';
    const { facets, stamp } = facetsFromPlan(plan);
    assert.equal(stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.deepStrictEqual(
      facets.map((f) => ({ id: f.id, sourceBranchId: f.sourceBranchId })),
      [
        { id: 'facet:br-alpha', sourceBranchId: 'br-alpha' },
        { id: 'facet:br-beta', sourceBranchId: 'br-beta' },
      ],
    );
  });

  test('explicit branch.order sorts facets ascending (ties broken by id)', () => {
    const plan = planWithBranches(['first-written', 'second-written']);
    plan.branches[0].order = 10;
    plan.branches[1].order = 1;
    const { facets } = facetsFromPlan(plan);
    assert.deepStrictEqual(
      facets.map((f) => f.question),
      ['second-written', 'first-written'],
    );
    assert.deepStrictEqual(
      facets.map((f) => f.order),
      [1, 10],
    );
  });
});

describe('Wave 1 — empty / unusable branches → no invented facets (breadth:none)', () => {
  test('acceptance GWT: empty branches → facets=[] and stamp breadth:none (axis present does not invent)', () => {
    const plan = planWithBranches([]);
    assert.ok(plan.scope.axis.length > 0, 'fixture carries axis so we can prove it is not used');

    const result = facetsFromPlan(plan);

    assert.equal(result.stamp, BREADTH_STAMPS.NONE);
    assert.deepStrictEqual(result.facets, []);
    // Axis must never become a Facet record.
    assert.equal(
      result.facets.some((f) => f.question === plan.scope.axis),
      false,
    );
    // v1 does not emit axis-only as a facet path (done-when: never invent when empty).
    assert.notEqual(result.stamp, BREADTH_STAMPS.AXIS_ONLY);
  });

  test('missing branches field → breadth:none, empty facets', () => {
    const plan = planWithBranches(['x']);
    delete plan.branches;
    const result = facetsFromPlan(plan);
    assert.equal(result.stamp, BREADTH_STAMPS.NONE);
    assert.deepStrictEqual(result.facets, []);
  });

  test('null / undefined / non-object plan → breadth:none, empty facets', () => {
    for (const plan of [null, undefined, 42, 'plan', true]) {
      const result = facetsFromPlan(plan);
      assert.equal(result.stamp, BREADTH_STAMPS.NONE, `plan=${String(plan)}`);
      assert.deepStrictEqual(result.facets, []);
    }
  });

  test('all branches unusable (empty questions) → no synthetic replacements, breadth:none', () => {
    const plan = planWithBranches(['ok']);
    plan.branches = [
      { question: '', rationale: 'empty', anchors: [{ sourceId: 'n', quote: 'x' }] },
      { question: '   ', rationale: 'ws', anchors: [{ sourceId: 'n', quote: 'x' }] },
      { rationale: 'no-question-field', anchors: [{ sourceId: 'n', quote: 'x' }] },
    ];
    const result = facetsFromPlan(plan);
    assert.equal(result.stamp, BREADTH_STAMPS.NONE);
    assert.deepStrictEqual(result.facets, []);
  });

  test('mixed valid/invalid branches materialize only the usable ones (no silent pad)', () => {
    const plan = planWithBranches(['keep-me', 'also-keep']);
    plan.branches[0].question = 'keep-me';
    plan.branches.splice(1, 0, { question: '', rationale: 'drop', anchors: [] });
    // branches: keep-me, '', also-keep  — only 2 usable
    plan.branches[2] = {
      question: 'also-keep',
      rationale: 'r',
      anchors: [{ sourceId: 'n', quote: 'a' }],
    };

    const result = facetsFromPlan(plan);
    assert.equal(result.stamp, BREADTH_STAMPS.FROM_BRANCHES);
    assert.deepStrictEqual(
      result.facets.map((f) => f.question),
      ['keep-me', 'also-keep'],
    );
    assert.equal(result.facets.length, 2);
  });
});

describe('Wave 1 — determinism and purity', () => {
  test('acceptance GWT: same plan twice → identical facet ids, order, and stamp', () => {
    const plan = planWithBranches([
      'Do compute-optimal ratios transfer below 1B parameters?',
      'Which data-quality filters dominate the scaling exponent?',
    ]);

    const a = facetsFromPlan(plan);
    const b = facetsFromPlan(plan);

    assert.deepStrictEqual(
      a.facets.map((f) => ({ id: f.id, order: f.order, sourceBranchId: f.sourceBranchId, question: f.question })),
      b.facets.map((f) => ({ id: f.id, order: f.order, sourceBranchId: f.sourceBranchId, question: f.question })),
    );
    assert.equal(a.stamp, b.stamp);
    assert.equal(a.stamp, BREADTH_STAMPS.FROM_BRANCHES);
  });

  test('does not mutate the input plan', () => {
    const plan = planWithBranches(['Q1', 'Q2']);
    const before = structuredClone(plan);
    facetsFromPlan(plan);
    assert.deepStrictEqual(plan, before);
  });

  test('returned facets and result object are frozen', () => {
    const { facets, stamp } = facetsFromPlan(planWithBranches(['Q1', 'Q2']));
    assert.ok(Object.isFrozen(facets));
    assert.ok(facets.every((f) => Object.isFrozen(f)));
    assert.equal(typeof stamp, 'string');
  });
});
