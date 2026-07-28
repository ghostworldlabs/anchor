// test/render-prose.test.mjs — Wave 3: golden prose snapshots for renderPlanProse
// (trio-shared/brownfield-intake/renderPlanProse.mjs, resolved via the Wave-1 pinned trio
// home — docs/DECISION-RECEIPT-shared-location.md).
//
// Pins the Wave-3 acceptance: a PlanArtifact (3 seeds, 4 branches, sources-to-beat,
// foresight receipt) renders deterministically — two calls are byte-identical — into a
// human-readable prose plan body with a LABELED prose section for every schema field and
// ONE line per seed showing identifier + title. The exact output bytes are pinned by
// golden snapshots (test/golden/render-prose/*.golden.md). Anchors never appear in the
// body: coverage is an advisory sidecar (test/coverage-sidecar-advisory.test.mjs).

import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';

const GOLDEN_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'golden',
  'render-prose',
);

/**
 * Read a pinned golden snapshot. Only the FILE read is CRLF-normalized (so a future
 * checkout under a CRLF-converting git config cannot fake a renderer diff); the renderer
 * output itself is asserted byte-stable separately, with no normalization.
 */
function readGolden(name) {
  return readFileSync(path.join(GOLDEN_DIR, name), 'utf8').replace(/\r\n/g, '\n');
}

/** The acceptance-GWT artifact: 3 seeds, 4 candidate branches, sources-to-beat, foresight. */
function makeFullArtifact() {
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
      {
        question: 'How does citation grounding affect clinician trust?',
        rationale: 'The draft ties adoption to verifiable citations.',
        anchors: [{ sourceId: 'notes/clinical-draft.md', quote: 'verifiable citations' }],
      },
      {
        question: 'What latency budget keeps RAG viable at the bedside?',
        rationale: 'The methods notes cap acceptable latency at two seconds.',
        anchors: [{ sourceId: 'notes/corpus-notes.md', quote: 'acceptable latency at two seconds' }],
      },
    ],
    sourcesToBeat: [
      {
        title: 'Zakka et al. 2024 (Almanac)',
        why: 'The strongest published clinical-RAG evaluation to date.',
        anchors: [{ sourceId: 'notes/corpus-notes.md', quote: 'strongest published clinical-RAG evaluation' }],
      },
      {
        title: 'Singhal et al. 2023 (Med-PaLM 2)',
        why: 'The non-retrieval baseline all clinical LLM work is measured against.',
        anchors: [{ sourceId: 'notes/clinical-draft.md', quote: 'non-retrieval baseline' }],
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
      { idType: 'pmid', id: '37460753', title: 'Large Language Models Encode Clinical Knowledge' },
      { idType: 'arxiv', id: '2305.09617', title: 'Towards Expert-Level Medical Question Answering' },
    ],
  });
}

/** IDENTICAL content to makeFullArtifact, built in a scrambled key insertion order. */
function makeFullArtifactScrambled() {
  const full = makeFullArtifact();
  const scrambleAnchor = (a) => ({ quote: a.quote, sourceId: a.sourceId });
  return {
    seeds: full.seeds.map((s) => ({ title: s.title, id: s.id, idType: s.idType })),
    foresight: {
      anchors: full.foresight.anchors.map(scrambleAnchor),
      stamp: full.foresight.stamp,
      counterfactualCost: full.foresight.counterfactualCost,
      dropped: full.foresight.dropped,
    },
    sourcesToBeat: full.sourcesToBeat.map((s) => ({
      anchors: s.anchors.map(scrambleAnchor),
      why: s.why,
      title: s.title,
    })),
    branches: full.branches.map((b) => ({
      anchors: b.anchors.map(scrambleAnchor),
      rationale: b.rationale,
      question: b.question,
    })),
    scope: {
      anchors: full.scope.anchors.map(scrambleAnchor),
      axis: full.scope.axis,
      statement: full.scope.statement,
    },
    artifactVersion: full.artifactVersion,
  };
}

/** Minimal corpus member: empty branches/sourcesToBeat/seeds (all schema-valid empties). */
function makeMinimalArtifact() {
  return structuredClone({
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Survey the evidence base before committing to a research direction.',
      axis: 'A direction is viable only if at least one replicated result supports it.',
      anchors: [{ sourceId: 'intent', quote: 'evidence base' }],
    },
    branches: [],
    sourcesToBeat: [],
    foresight: {
      dropped: 'Nothing was dropped or reordered.',
      counterfactualCost: 'None — no branch was excluded.',
      stamp: 'no foresight value added',
      anchors: [{ sourceId: 'intent', quote: 'research direction' }],
    },
    seeds: [],
  });
}

describe('Wave 3 — renderPlanProse (golden prose snapshots, deterministic and byte-stable)', () => {
  let schema;
  let v;
  let r;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    schema = await import(new URL('planArtifact.schema.mjs', indexUrl).href);
    v = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
    r = await import(new URL('renderPlanProse.mjs', indexUrl).href);
  });

  test('the corpus artifacts are schema-valid (the renderer contract is schema-valid input)', () => {
    assert.equal(v.validatePlanArtifact(makeFullArtifact()).ok, true);
    assert.equal(v.validatePlanArtifact(makeFullArtifactScrambled()).ok, true);
    assert.equal(v.validatePlanArtifact(makeMinimalArtifact()).ok, true);
    // The scramble is real (raw serialization differs) but content-identical.
    assert.notEqual(
      JSON.stringify(makeFullArtifact(), null, 2),
      JSON.stringify(makeFullArtifactScrambled(), null, 2),
    );
    assert.deepStrictEqual(makeFullArtifact(), makeFullArtifactScrambled());
  });

  test('acceptance GWT: rendering the same artifact twice is byte-identical', () => {
    const artifact = makeFullArtifact();
    const first = r.renderPlanProse(artifact);
    const second = r.renderPlanProse(artifact);
    assert.strictEqual(first, second, 'two renders of the same artifact must be byte-identical');
    assert.strictEqual(
      r.renderPlanProse(makeFullArtifact()),
      first,
      'a fresh deep copy of the same content must also render byte-identically',
    );
  });

  test('acceptance GWT: a labeled prose section for EVERY schema field', () => {
    const body = r.renderPlanProse(makeFullArtifact());
    const fieldLabels = {
      artifactVersion: '**Artifact version:**',
      scope: '## Scope',
      branches: '## Candidate branches / questions',
      sourcesToBeat: '## Sources to beat',
      foresight: '## Foresight receipt',
      seeds: '## Seeds',
    };
    for (const field of schema.CANONICAL_KEY_ORDER.artifact) {
      assert.ok(
        Object.hasOwn(fieldLabels, field),
        `schema field "${field}" has no pinned prose label — extend this test`,
      );
      assert.ok(
        body.includes(fieldLabels[field]),
        `plan body must contain a labeled section for schema field "${field}"`,
      );
    }
    assert.ok(body.includes('**AXIS (win condition):**'), 'the AXIS is labeled inside Scope');
  });

  test('acceptance GWT: one line per seed showing identifier + title', () => {
    const artifact = makeFullArtifact();
    const body = r.renderPlanProse(artifact);
    const seedLines = body.split('\n').filter((l) => /^- (doi|pmid|arxiv|title-hash):/.test(l));
    assert.equal(seedLines.length, artifact.seeds.length, 'exactly one line per seed');
    artifact.seeds.forEach((seed, i) => {
      assert.strictEqual(
        seedLines[i],
        `- ${seed.idType}:${seed.id} — ${seed.title}`,
        `seed ${i} renders as identifier + title on its own line`,
      );
    });
  });

  test('every plan element value appears verbatim in the prose body', () => {
    const artifact = makeFullArtifact();
    const body = r.renderPlanProse(artifact);
    const expected = [
      artifact.artifactVersion,
      artifact.scope.statement,
      artifact.scope.axis,
      ...artifact.branches.flatMap((b) => [b.question, b.rationale]),
      ...artifact.sourcesToBeat.flatMap((s) => [s.title, s.why]),
      artifact.foresight.dropped,
      artifact.foresight.counterfactualCost,
      artifact.foresight.stamp,
    ];
    for (const value of expected) {
      assert.ok(body.includes(value), `plan body must contain verbatim: ${value}`);
    }
  });

  test('golden snapshot: full corpus artifact matches test/golden/render-prose/full.golden.md', () => {
    assert.strictEqual(r.renderPlanProse(makeFullArtifact()), readGolden('full.golden.md'));
  });

  test('golden snapshot: minimal corpus artifact matches test/golden/render-prose/minimal.golden.md', () => {
    assert.strictEqual(r.renderPlanProse(makeMinimalArtifact()), readGolden('minimal.golden.md'));
  });

  test('rendering is key-order independent: scrambled insertion order renders byte-identically', () => {
    assert.strictEqual(
      r.renderPlanProse(makeFullArtifactScrambled()),
      r.renderPlanProse(makeFullArtifact()),
    );
  });

  test('empty branches/sources/seeds render labeled sections with explicit empty markers', () => {
    const body = r.renderPlanProse(makeMinimalArtifact());
    assert.ok(body.includes('## Candidate branches / questions\n\nNone derived.'));
    assert.ok(body.includes('## Sources to beat\n\nNone derived.'));
    assert.ok(body.includes('## Seeds\n\nNone provided.'));
  });

  test('anchor machinery never enters the prose body (coverage lives in the sidecar)', () => {
    const artifact = makeFullArtifact();
    const body = r.renderPlanProse(artifact);
    const sourceIds = new Set(
      [
        ...artifact.scope.anchors,
        ...artifact.branches.flatMap((b) => b.anchors),
        ...artifact.sourcesToBeat.flatMap((s) => s.anchors),
        ...artifact.foresight.anchors,
      ].map((a) => a.sourceId),
    );
    assert.ok(sourceIds.size > 0);
    for (const sourceId of sourceIds) {
      assert.ok(!body.includes(sourceId), `anchor sourceId "${sourceId}" must not be rendered`);
    }
    assert.ok(!/\banchors?\b/i.test(body), 'the body never mentions anchors');
  });

  test('renders never mutate the input artifact', () => {
    const artifact = makeFullArtifact();
    const bytesBefore = JSON.stringify(artifact, null, 2);
    r.renderPlanProse(artifact);
    assert.strictEqual(JSON.stringify(artifact, null, 2), bytesBefore);
  });

  test('a schema-invalid artifact is refused with the validator reasons (never rendered)', () => {
    const missingForesight = makeFullArtifact();
    delete missingForesight.foresight;
    assert.throws(() => r.renderPlanProse(missingForesight), /foresight/);

    const withCoverage = makeFullArtifact();
    withCoverage.coverage = { anything: true };
    assert.throws(() => r.renderPlanProse(withCoverage), /advisory sidecar/);
  });
});
