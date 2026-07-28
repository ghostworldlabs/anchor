// test/planArtifact-canonical-order.test.mjs — Wave 2: canonical field-ordering.
//
// Two PlanArtifacts with the SAME content built in DIFFERENT key insertion orders must
// serialize BYTE-IDENTICALLY after canonical ordering (deterministic key order per
// trio-shared/brownfield-intake/planArtifact.schema.mjs CANONICAL_KEY_ORDER). Byte-stable
// serialization is what later waves hash, snapshot, and golden-diff against.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';

/** The artifact in canonical construction order. */
function makeArtifactCanonicalOrder() {
  return {
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Map the evidence on transformer scaling laws for low-resource domains.',
      axis: 'A candidate is falsified if its claimed scaling gain lacks a replicated benchmark.',
      anchors: [
        { sourceId: 'notes/draft-intro.md', quote: 'scaling laws for low-resource domains' },
        { sourceId: 'notes/methods.md', quote: 'replicated benchmark' },
      ],
    },
    branches: [
      {
        question: 'Do compute-optimal ratios transfer below 1B parameters?',
        rationale: 'The draft flags the sub-1B regime as its central unknown.',
        anchors: [{ sourceId: 'notes/draft-intro.md', quote: 'the sub-1B regime' }],
      },
    ],
    sourcesToBeat: [
      {
        title: 'Hoffmann et al. 2022 (Chinchilla)',
        why: 'The compute-optimal baseline every candidate is compared against.',
        anchors: [{ sourceId: 'notes/methods.md', quote: 'compute-optimal baseline' }],
      },
    ],
    foresight: {
      dropped: 'A multilingual-transfer branch was dropped.',
      counterfactualCost: 'Misses cross-lingual scaling evidence if the domain turns multilingual.',
      stamp: 'foresight recorded at derive time',
      anchors: [{ sourceId: 'notes/draft-intro.md', quote: 'multilingual transfer' }],
    },
    seeds: [
      { idType: 'doi', id: '10.1000/example.2022.001', title: 'Training Compute-Optimal LLMs' },
      { idType: 'arxiv', id: '2203.15556', title: 'An Empirical Analysis of Scaling' },
    ],
  };
}

/** IDENTICAL content, but every object level built in a scrambled insertion order. */
function makeArtifactScrambledOrder() {
  return {
    seeds: [
      { title: 'Training Compute-Optimal LLMs', id: '10.1000/example.2022.001', idType: 'doi' },
      { id: '2203.15556', title: 'An Empirical Analysis of Scaling', idType: 'arxiv' },
    ],
    foresight: {
      anchors: [{ quote: 'multilingual transfer', sourceId: 'notes/draft-intro.md' }],
      stamp: 'foresight recorded at derive time',
      counterfactualCost: 'Misses cross-lingual scaling evidence if the domain turns multilingual.',
      dropped: 'A multilingual-transfer branch was dropped.',
    },
    sourcesToBeat: [
      {
        anchors: [{ quote: 'compute-optimal baseline', sourceId: 'notes/methods.md' }],
        why: 'The compute-optimal baseline every candidate is compared against.',
        title: 'Hoffmann et al. 2022 (Chinchilla)',
      },
    ],
    branches: [
      {
        anchors: [{ quote: 'the sub-1B regime', sourceId: 'notes/draft-intro.md' }],
        rationale: 'The draft flags the sub-1B regime as its central unknown.',
        question: 'Do compute-optimal ratios transfer below 1B parameters?',
      },
    ],
    scope: {
      anchors: [
        { quote: 'scaling laws for low-resource domains', sourceId: 'notes/draft-intro.md' },
        { sourceId: 'notes/methods.md', quote: 'replicated benchmark' },
      ],
      axis: 'A candidate is falsified if its claimed scaling gain lacks a replicated benchmark.',
      statement: 'Map the evidence on transformer scaling laws for low-resource domains.',
    },
    artifactVersion: 'plan-artifact/1',
  };
}

describe('Wave 2 — PlanArtifact canonical ordering (byte-stable serialization)', () => {
  let schema;
  let v;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    schema = await import(new URL('planArtifact.schema.mjs', indexUrl).href);
    v = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
  });

  test('both constructions are schema-valid and genuinely differ in raw key order', () => {
    assert.equal(v.validatePlanArtifact(makeArtifactCanonicalOrder()).ok, true);
    assert.equal(v.validatePlanArtifact(makeArtifactScrambledOrder()).ok, true);
    // The scramble is real: RAW serialization (insertion order) differs…
    assert.notEqual(
      JSON.stringify(makeArtifactCanonicalOrder(), null, 2),
      JSON.stringify(makeArtifactScrambledOrder(), null, 2),
    );
    // …while the content is the same.
    assert.deepStrictEqual(makeArtifactCanonicalOrder(), makeArtifactScrambledOrder());
  });

  test('acceptance GWT: same content, different key order — byte-identical after canonical ordering', () => {
    const a = v.canonicalStringifyPlanArtifact(makeArtifactCanonicalOrder());
    const b = v.canonicalStringifyPlanArtifact(makeArtifactScrambledOrder());
    assert.equal(a, b, 'canonical serialization must be byte-identical');
  });

  test('canonical output follows the schema-declared key order at every level', () => {
    const canon = v.canonicalizePlanArtifact(makeArtifactScrambledOrder());
    assert.deepStrictEqual(Object.keys(canon), [...schema.CANONICAL_KEY_ORDER.artifact]);
    assert.deepStrictEqual(Object.keys(canon.scope), [...schema.CANONICAL_KEY_ORDER.scope]);
    assert.deepStrictEqual(Object.keys(canon.branches[0]), [...schema.CANONICAL_KEY_ORDER.branch]);
    assert.deepStrictEqual(
      Object.keys(canon.sourcesToBeat[0]),
      [...schema.CANONICAL_KEY_ORDER.sourceToBeat],
    );
    assert.deepStrictEqual(Object.keys(canon.foresight), [...schema.CANONICAL_KEY_ORDER.foresight]);
    assert.deepStrictEqual(Object.keys(canon.seeds[0]), [...schema.CANONICAL_KEY_ORDER.seed]);
    assert.deepStrictEqual(
      Object.keys(canon.scope.anchors[0]),
      [...schema.CANONICAL_KEY_ORDER.anchor],
    );
  });

  test('canonicalization is idempotent and deterministic across calls', () => {
    const once = v.canonicalizePlanArtifact(makeArtifactScrambledOrder());
    const twice = v.canonicalizePlanArtifact(once);
    assert.equal(JSON.stringify(once, null, 2), JSON.stringify(twice, null, 2));
    assert.equal(
      v.canonicalStringifyPlanArtifact(makeArtifactScrambledOrder()),
      v.canonicalStringifyPlanArtifact(makeArtifactScrambledOrder()),
      'two calls on the same content must be byte-identical',
    );
  });

  test('canonicalization never mutates its input', () => {
    const input = makeArtifactScrambledOrder();
    const rawBefore = JSON.stringify(input, null, 2);
    const canon = v.canonicalizePlanArtifact(input);
    assert.equal(JSON.stringify(input, null, 2), rawBefore, 'input bytes unchanged');
    assert.notEqual(canon, input, 'a NEW object is returned');
    assert.deepStrictEqual(canon, input, 'content preserved exactly');
  });

  test('canonical serialization round-trips: parse(canonicalStringify(x)) equals x in content', () => {
    const artifact = makeArtifactScrambledOrder();
    const parsed = JSON.parse(v.canonicalStringifyPlanArtifact(artifact));
    assert.deepStrictEqual(parsed, artifact);
    assert.equal(v.validatePlanArtifact(parsed).ok, true);
  });
});
