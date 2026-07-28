// test/planArtifact-schema.test.mjs — Wave 2: valid/invalid corpus for the module-owned
// PlanArtifact schema + runtime validator (trio-shared/brownfield-intake/*, resolved via
// the Wave-1 pinned trio home — docs/DECISION-RECEIPT-shared-location.md).
//
// Pins the Wave-2 acceptance: a complete artifact validates; removing the foresight
// receipt fails with a structured reason NAMING it; missing/empty anchors fail; extra
// fields fail (coverage/provenance with the advisory-sidecar reason); empty seeds are
// VALID; and coverage/provenance is NOT required to validate (advisory, never a gate).

import { test, describe, before } from 'node:test';
import assert from 'node:assert';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';

/** A complete, schema-valid PlanArtifact (fresh deep copy per call). */
function makeValidArtifact() {
  return structuredClone({
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Map the evidence on transformer scaling laws for low-resource domains.',
      axis: 'A candidate is falsified if its claimed scaling gain lacks a replicated benchmark.',
      anchors: [
        { sourceId: 'notes/draft-intro.md', quote: 'scaling laws for low-resource domains' },
      ],
    },
    branches: [
      {
        question: 'Do compute-optimal ratios transfer below 1B parameters?',
        rationale: 'The draft flags the sub-1B regime as its central unknown.',
        anchors: [{ sourceId: 'notes/draft-intro.md', quote: 'the sub-1B regime' }],
      },
      {
        question: 'Which data-quality filters dominate the scaling exponent?',
        rationale: 'The notes attribute most variance to filtering choices.',
        anchors: [{ sourceId: 'notes/methods.md', quote: 'most variance to filtering choices' }],
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
  });
}

describe('Wave 2 — PlanArtifact schema + runtime validator', () => {
  let schema;
  let v;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    schema = await import(new URL('planArtifact.schema.mjs', indexUrl).href);
    v = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
  });

  test('schema module exports the module-owned contract tables', () => {
    assert.equal(typeof schema.PLAN_ARTIFACT_SCHEMA_VERSION, 'string');
    assert.deepStrictEqual([...schema.SEED_ID_TYPES], ['doi', 'pmid', 'arxiv', 'title-hash']);
    assert.deepStrictEqual(
      [...schema.CANONICAL_KEY_ORDER.artifact],
      ['artifactVersion', 'scope', 'branches', 'sourcesToBeat', 'foresight', 'seeds'],
    );
    assert.deepStrictEqual([...schema.ADVISORY_ONLY_KEYS], ['coverage', 'provenance']);
  });

  test('a complete PlanArtifact validates with zero reasons', () => {
    const res = v.validatePlanArtifact(makeValidArtifact());
    assert.deepStrictEqual(res, { ok: true, reasons: [] });
  });

  test('acceptance GWT: removing the foresight receipt fails, naming it', () => {
    const complete = makeValidArtifact();
    const mutated = makeValidArtifact();
    delete mutated.foresight;

    assert.equal(v.validatePlanArtifact(complete).ok, true);
    const res = v.validatePlanArtifact(mutated);
    assert.equal(res.ok, false);
    assert.ok(
      res.reasons.some(
        (r) =>
          r.path === 'foresight' && /missing/i.test(r.reason) && /foresight receipt/i.test(r.reason),
      ),
      `expected a structured reason naming the missing foresight receipt, got: ${JSON.stringify(res.reasons)}`,
    );
  });

  test('acceptance GWT: coverage/provenance is NOT required — absence validates', () => {
    const artifact = makeValidArtifact();
    // The valid artifact carries NO coverage/provenance field at all…
    assert.equal('coverage' in artifact, false);
    assert.equal('provenance' in artifact, false);
    // …and validation passes: coverage is advisory, never a schema gate.
    assert.equal(v.validatePlanArtifact(artifact).ok, true);
  });

  test('coverage/provenance PRESENT as a field is rejected with the advisory-sidecar reason', () => {
    for (const key of ['coverage', 'provenance']) {
      const artifact = makeValidArtifact();
      artifact[key] = { anything: true };
      const res = v.validatePlanArtifact(artifact);
      assert.equal(res.ok, false, `${key} must never be an artifact field`);
      assert.ok(
        res.reasons.some((r) => r.path === key && /advisory sidecar/i.test(r.reason)),
        `expected an advisory-sidecar reason for "${key}", got: ${JSON.stringify(res.reasons)}`,
      );
    }
  });

  test('extra fields are rejected, top-level and nested', () => {
    const top = makeValidArtifact();
    top.surprise = 'x';
    const resTop = v.validatePlanArtifact(top);
    assert.equal(resTop.ok, false);
    assert.ok(resTop.reasons.some((r) => r.path === 'surprise' && /unexpected field/i.test(r.reason)));

    const nested = makeValidArtifact();
    nested.scope.surprise = 'x';
    const resNested = v.validatePlanArtifact(nested);
    assert.equal(resNested.ok, false);
    assert.ok(
      resNested.reasons.some((r) => r.path === 'scope.surprise' && /unexpected field/i.test(r.reason)),
    );

    const seedExtra = makeValidArtifact();
    seedExtra.seeds[0].abstract = 'not a schema field';
    const resSeed = v.validatePlanArtifact(seedExtra);
    assert.equal(resSeed.ok, false);
    assert.ok(resSeed.reasons.some((r) => r.path === 'seeds[0].abstract'));
  });

  test('missing or empty anchors fail on every element kind', () => {
    const cases = [
      ['scope.anchors', (a) => delete a.scope.anchors],
      ['scope.anchors', (a) => (a.scope.anchors = [])],
      ['branches[0].anchors', (a) => delete a.branches[0].anchors],
      ['branches[1].anchors', (a) => (a.branches[1].anchors = [])],
      ['sourcesToBeat[0].anchors', (a) => delete a.sourcesToBeat[0].anchors],
      ['foresight.anchors', (a) => (a.foresight.anchors = [])],
    ];
    for (const [path, mutate] of cases) {
      const artifact = makeValidArtifact();
      mutate(artifact);
      const res = v.validatePlanArtifact(artifact);
      assert.equal(res.ok, false, `expected failure for ${path}`);
      assert.ok(
        res.reasons.some((r) => r.path === path),
        `expected a reason at ${path}, got: ${JSON.stringify(res.reasons)}`,
      );
    }
  });

  test('malformed anchors fail with per-field reasons', () => {
    const artifact = makeValidArtifact();
    artifact.scope.anchors = [{ sourceId: 'notes/draft-intro.md', quote: '' }];
    const res = v.validatePlanArtifact(artifact);
    assert.equal(res.ok, false);
    assert.ok(res.reasons.some((r) => r.path === 'scope.anchors[0].quote'));

    const extra = makeValidArtifact();
    extra.branches[0].anchors = [{ sourceId: 's', quote: 'q', similarity: 0.9 }];
    const resExtra = v.validatePlanArtifact(extra);
    assert.equal(resExtra.ok, false, 'anchors admit no extra fields (no semantic-match metadata)');
    assert.ok(resExtra.reasons.some((r) => r.path === 'branches[0].anchors[0].similarity'));
  });

  test('empty seeds are VALID (intent-only route derives a plan with zero seeds)', () => {
    const artifact = makeValidArtifact();
    artifact.seeds = [];
    assert.equal(v.validatePlanArtifact(artifact).ok, true);
  });

  test('empty branches/sourcesToBeat arrays are structurally valid (seeds-only bootstrap)', () => {
    const artifact = makeValidArtifact();
    artifact.branches = [];
    artifact.sourcesToBeat = [];
    assert.equal(v.validatePlanArtifact(artifact).ok, true);
  });

  test('malformed seeds fail with per-field reasons', () => {
    const badType = makeValidArtifact();
    badType.seeds[0].idType = 'isbn';
    const resType = v.validatePlanArtifact(badType);
    assert.equal(resType.ok, false);
    assert.ok(resType.reasons.some((r) => r.path === 'seeds[0].idType'));

    const emptyId = makeValidArtifact();
    emptyId.seeds[1].id = '';
    const resId = v.validatePlanArtifact(emptyId);
    assert.equal(resId.ok, false);
    assert.ok(resId.reasons.some((r) => r.path === 'seeds[1].id'));

    const noTitle = makeValidArtifact();
    delete noTitle.seeds[0].title;
    const resTitle = v.validatePlanArtifact(noTitle);
    assert.equal(resTitle.ok, false);
    assert.ok(resTitle.reasons.some((r) => r.path === 'seeds[0].title'));
  });

  test('empty/blank required strings fail', () => {
    const artifact = makeValidArtifact();
    artifact.scope.statement = '   ';
    artifact.foresight.stamp = '';
    const res = v.validatePlanArtifact(artifact);
    assert.equal(res.ok, false);
    assert.ok(res.reasons.some((r) => r.path === 'scope.statement'));
    assert.ok(res.reasons.some((r) => r.path === 'foresight.stamp'));
  });

  test('non-object inputs return a structured fail, never throw', () => {
    for (const bad of [null, undefined, 42, 'plan', [], true]) {
      const res = v.validatePlanArtifact(bad);
      assert.equal(res.ok, false);
      assert.equal(res.reasons.length, 1);
      assert.equal(res.reasons[0].path, 'artifact');
    }
  });

  test('every reported reason is structured: string path + string reason', () => {
    const artifact = makeValidArtifact();
    delete artifact.foresight;
    delete artifact.scope.axis;
    artifact.rogue = 1;
    const res = v.validatePlanArtifact(artifact);
    assert.equal(res.ok, false);
    assert.ok(res.reasons.length >= 3);
    for (const r of res.reasons) {
      assert.equal(typeof r.path, 'string');
      assert.equal(typeof r.reason, 'string');
      assert.ok(r.path.length > 0 && r.reason.length > 0);
    }
    const paths = res.reasons.map((r) => r.path);
    assert.ok(paths.includes('foresight'));
    assert.ok(paths.includes('scope.axis'));
    assert.ok(paths.includes('rogue'));
  });
});
