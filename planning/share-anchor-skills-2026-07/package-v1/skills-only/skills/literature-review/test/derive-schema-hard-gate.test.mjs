// test/derive-schema-hard-gate.test.mjs — Wave 8: the derive hard gate.
//
// A derive output failing the module-owned schema, the deterministic verbatim-anchor
// check, OR the deterministic SEED-IDENTITY RECONCILIATION (exact (idType,id) multiset
// equality against the upstream validated seed set — literal identity comparison,
// never semantic; seeds carry no anchors by design, so the anchor check provably
// cannot cover them) produces NO artifact — derivation FAILS; no partial/degraded
// artifact escapes to the caller. Validation is EXACTLY once per check (instrument
// counters), and the offending elements are surfaced in the advisory plan-readiness
// preview (display only) rather than silently executed — the Wave-8 acceptance GWTs
// for an invented source-to-beat and for an invented/dropped/altered seed identity.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';

let deriveMod;
let previewMod;

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  deriveMod = await import(new URL('derivePlan.mjs', indexUrl).href);
  previewMod = await import(new URL('planReadinessPreview.mjs', indexUrl).href);
});

const SUMMARY =
  'The held-out perplexity improved monotonically with data quality filtering. ' +
  'Aggressive near-duplicate removal improves zero-shot transfer on average.';

/** A schema-valid artifact fully anchored into the summary source. */
function validArtifact() {
  const anchors = [
    {
      sourceId: deriveMod.SUMMARY_SOURCE_ID,
      quote: 'held-out perplexity improved monotonically with data quality filtering',
    },
  ];
  return {
    artifactVersion: 'plan-artifact/1',
    scope: { statement: 'Study data-quality effects.', axis: 'Perplexity wins.', anchors },
    branches: [{ question: 'Does filtering help?', rationale: 'Summary says so.', anchors }],
    sourcesToBeat: [{ title: 'Near-duplicate removal work', why: 'Best baseline.', anchors }],
    foresight: {
      dropped: 'nothing dropped',
      counterfactualCost: 'no cost',
      stamp: 'no foresight value added',
      anchors,
    },
    seeds: [],
  };
}

function instrumented() {
  const counts = { schema: 0, anchor: 0, seeds: 0 };
  return {
    counts,
    instrument: {
      onSchemaValidated: () => { counts.schema += 1; },
      onAnchorChecked: () => { counts.anchor += 1; },
      onSeedsReconciled: () => { counts.seeds += 1; },
    },
  };
}

describe('Wave 8 — derive schema/anchor hard gate: failure produces NO artifact', () => {
  test('control: a schema-valid, verbatim-anchored emission passes with exactly-once validation', async () => {
    const { counts, instrument } = instrumented();
    const res = await deriveMod.derivePlan({
      summary: SUMMARY,
      derive: () => validArtifact(),
      instrument,
    });
    assert.equal(res.ok, true, res.reason);
    assert.equal(res.deriveCalls, 1);
    assert.ok(res.artifact);
    assert.equal(counts.schema, 1, 'schema validated exactly once');
    assert.equal(counts.anchor, 1, 'anchors checked exactly once');
    assert.equal(counts.seeds, 1, 'seed identities reconciled exactly once');
    // Canonical ordering on the returned artifact.
    assert.deepStrictEqual(
      Object.keys(res.artifact),
      ['artifactVersion', 'scope', 'branches', 'sourcesToBeat', 'foresight', 'seeds'],
    );
  });

  test('a schema-invalid emission (missing foresight) FAILS: no artifact, structured reasons, anchor check never reached', async () => {
    const bad = validArtifact();
    delete bad.foresight;
    const { counts, instrument } = instrumented();
    const res = await deriveMod.derivePlan({ summary: SUMMARY, derive: () => bad, instrument });

    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 1);
    assert.equal(res.artifact, null, 'NO partial artifact escapes a schema failure');
    assert.equal(res.stamp, deriveMod.DERIVE_FAIL_STAMP);
    assert.match(res.reason, /module-owned PlanArtifact schema/);
    assert.ok(
      res.failures.some((f) => /foresight/.test(`${f.path} ${f.reason}`)),
      'the structured reasons name the missing foresight receipt',
    );
    assert.equal(counts.schema, 1, 'schema validated exactly once');
    assert.equal(counts.anchor, 0, 'a schema failure never reaches the anchor check');
  });

  test('acceptance GWT: an invented source-to-beat with a non-verbatim anchor FAILS derivation; the offending element is surfaced in the advisory preview, never executed', async () => {
    const invented = validArtifact();
    invented.sourcesToBeat.push({
      title: 'The moon dataset',
      why: 'Claims 99% accuracy.',
      anchors: [
        {
          sourceId: deriveMod.SUMMARY_SOURCE_ID,
          quote: 'the moon dataset proves accuracy is 99%',
        },
      ],
    });
    const { counts, instrument } = instrumented();
    const res = await deriveMod.derivePlan({ summary: SUMMARY, derive: () => invented, instrument });

    assert.equal(res.ok, false);
    assert.equal(res.artifact, null, 'no partial artifact is returned to the caller');
    assert.match(res.reason, /word-for-word/);
    const offending = res.failures.find((f) => f.path === 'sourcesToBeat[1].anchors[0]');
    assert.ok(offending, 'the failure names the invented element by path');
    assert.equal(counts.schema, 1);
    assert.equal(counts.anchor, 1, 'anchors checked exactly once — no re-validation');

    // Surfaced in the advisory sidecar/preview (DISPLAY only), rather than silently executed.
    const preview = previewMod.planReadinessPreview({ failures: res.failures });
    assert.ok(preview.includes(previewMod.PLAN_READINESS_MARKER));
    assert.match(preview, /display only/);
    assert.ok(preview.includes('sourcesToBeat[1].anchors[0]'));
    assert.ok(preview.includes('the moon dataset proves accuracy is 99%'));
  });

  test('a sub-minimum or mid-word anchor span is an anchor FAILURE, not a pass', async () => {
    const short = validArtifact();
    short.scope.anchors = [{ sourceId: deriveMod.SUMMARY_SOURCE_ID, quote: 'held-out' }];
    const res = await deriveMod.derivePlan({ summary: SUMMARY, derive: () => short });
    assert.equal(res.ok, false);
    assert.equal(res.artifact, null);
    assert.ok(res.failures.some((f) => f.path === 'scope.anchors[0]'));
  });

  test('an emission naming an unknown sourceId FAILS: nothing grounds outside the fenced context', async () => {
    const rogue = validArtifact();
    rogue.branches[0].anchors = [
      { sourceId: 'source X', quote: 'held-out perplexity improved monotonically' },
    ];
    const res = await deriveMod.derivePlan({ summary: SUMMARY, derive: () => rogue });
    assert.equal(res.ok, false);
    assert.equal(res.artifact, null);
    assert.ok(res.failures.some((f) => /unknown sourceId/.test(f.reason)));
  });

  test('a non-serializable or oversized emission is refused wholesale', async () => {
    const cyclic = {};
    cyclic.self = cyclic;
    const res1 = await deriveMod.derivePlan({ summary: SUMMARY, derive: () => cyclic });
    assert.equal(res1.ok, false);
    assert.equal(res1.artifact, null);
    assert.match(res1.reason, /JSON-serializable/);

    const res2 = await deriveMod.derivePlan({
      summary: SUMMARY,
      derive: () => validArtifact(),
      maxOutputChars: 10,
    });
    assert.equal(res2.ok, false);
    assert.equal(res2.artifact, null);
    assert.match(res2.reason, /output budget/);
  });

  const VALIDATED_SEEDS = [
    { idType: 'doi', id: '10.1234/example.5678', title: 'A validated seed paper' },
    { idType: 'pmid', id: '12345678', title: 'Second validated seed' },
  ];

  /** A fully-anchored, schema-valid emission carrying the given artifact.seeds. */
  function artifactWithSeeds(seeds) {
    const artifact = validArtifact();
    artifact.seeds = seeds;
    return artifact;
  }

  test('acceptance GWT: SEED-IDENTITY RECONCILIATION — an INVENTED (idType,id) FAILS by exact multiset inequality; no artifact, mismatch stamped', async () => {
    const emitted = [
      ...VALIDATED_SEEDS.map(({ idType, id, title }) => ({ idType, id, title })),
      { idType: 'arxiv', id: '9999.99999', title: 'Invented out of thin air' },
    ];
    const { counts, instrument } = instrumented();
    const res = await deriveMod.derivePlan({
      summary: SUMMARY,
      seeds: VALIDATED_SEEDS,
      derive: () => artifactWithSeeds(emitted),
      instrument,
    });

    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 1);
    assert.equal(res.artifact, null, 'an emission whose seeds do not equal the validated set can never RUN');
    assert.equal(res.stamp, deriveMod.DERIVE_FAIL_STAMP, 'the mismatch is stamped');
    assert.match(res.reason, /SEED-IDENTITY RECONCILIATION/);
    assert.match(res.reason, /multiset/);
    assert.ok(
      res.failures.some((f) => f.path === 'seeds[2]' && /\(arxiv,9999\.99999\)/.test(f.reason)),
      'the failure names the invented identity',
    );
    // The fourth check is deterministic and exactly-once, AFTER schema and anchors.
    assert.equal(counts.schema, 1);
    assert.equal(counts.anchor, 1);
    assert.equal(counts.seeds, 1);
  });

  test('SEED-IDENTITY RECONCILIATION — a DROPPED seed FAILS: fewer identities than the validated set never RUN', async () => {
    const emitted = [VALIDATED_SEEDS[0]].map(({ idType, id, title }) => ({ idType, id, title }));
    const res = await deriveMod.derivePlan({
      summary: SUMMARY,
      seeds: VALIDATED_SEEDS,
      derive: () => artifactWithSeeds(emitted),
    });
    assert.equal(res.ok, false);
    assert.equal(res.artifact, null);
    assert.match(res.reason, /SEED-IDENTITY RECONCILIATION/);
    assert.ok(
      res.failures.some((f) => /\(pmid,12345678\)/.test(f.reason) && /dropped/.test(f.reason)),
      'the failure names the dropped identity',
    );
  });

  test('SEED-IDENTITY RECONCILIATION — an ALTERED seed id FAILS both ways (one invented + one dropped)', async () => {
    const emitted = [
      { ...VALIDATED_SEEDS[0] },
      { idType: 'pmid', id: '87654321', title: VALIDATED_SEEDS[1].title },
    ];
    const res = await deriveMod.derivePlan({
      summary: SUMMARY,
      seeds: VALIDATED_SEEDS,
      derive: () => artifactWithSeeds(emitted),
    });
    assert.equal(res.ok, false);
    assert.equal(res.artifact, null);
    assert.ok(res.failures.some((f) => /\(pmid,87654321\)/.test(f.reason)), 'altered id surfaces as invented');
    assert.ok(res.failures.some((f) => /\(pmid,12345678\)/.test(f.reason)), 'original id surfaces as dropped');
  });

  test('SEED-IDENTITY RECONCILIATION — reordered but identical identities PASS (multiset equality, literal identity only, never semantic)', async () => {
    const emitted = [...VALIDATED_SEEDS].reverse().map(({ idType, id, title }) => ({ idType, id, title }));
    const res = await deriveMod.derivePlan({
      summary: SUMMARY,
      seeds: VALIDATED_SEEDS,
      derive: () => artifactWithSeeds(emitted),
    });
    assert.equal(res.ok, true, res.reason);
    assert.ok(res.artifact);
  });

  test('the preview renders a schema-invalid artifact as failures too — display only, never a throw', () => {
    const bad = validArtifact();
    delete bad.scope;
    const preview = previewMod.planReadinessPreview({ artifact: bad, groundedSources: {} });
    assert.ok(preview.includes('schema-invalid'));
    assert.ok(preview.includes(previewMod.PLAN_READINESS_MARKER));
  });
});
