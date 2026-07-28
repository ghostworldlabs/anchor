// test/interface-parity-rp-consumer.test.mjs — Wave 8: the module's REAL PlanArtifact
// drives an RP-shaped consumer UNMODIFIED and is accepted.
//
// A SEPARATE consumer process, running from the researchPrime checkout and resolving
// the shared module the way researchPrime itself does (its OWN TRIO_ROOT pin in
// bin/contract.mjs — the Wave-1 proven path), receives the artifact produced by the
// shared module's real end-to-end entry, validates it against the MODULE-OWNED schema,
// and re-serializes it canonically. Acceptance + byte-identical canonical bytes on
// both sides prove the interface contract: ONE shared module, ONE artifact shape,
// consumed unmodified by both skills — no adapter, no reshaping.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import { spawnSync } from 'node:child_process';

import {
  resolveResearchPrimeRoot,
  sharedBrownfieldUrl,
} from './_wave1-trio-resolve.mjs';

const SEEDS = [
  { idType: 'doi', id: '10.1234/example.5678', title: 'A seed paper on deduplication' },
  { idType: 'pmid', id: '12345678', title: 'Second seed on data quality' },
];

let entryMod;
let deriveMod;
let validateMod;

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  entryMod = await import(indexUrl.href);
  deriveMod = await import(new URL('derivePlan.mjs', indexUrl).href);
  validateMod = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
});

/**
 * The RP-shaped consumer: a child Node process whose cwd is the researchPrime
 * checkout. It resolves the shared module via researchPrime's OWN pin, reads the
 * artifact JSON from stdin UNMODIFIED, validates it against the module-owned schema,
 * and prints an acceptance verdict plus the canonical serialization. No lit-review
 * code, path, or object crosses into the child.
 */
function runRpConsumer(artifact) {
  const rpRoot = resolveResearchPrimeRoot();
  const childScript = [
    "import path from 'node:path';",
    "import { pathToFileURL } from 'node:url';",
    "const contract = await import(pathToFileURL(path.resolve('bin/contract.mjs')).href);",
    "const validateMod = await import(new URL('trio-shared/brownfield-intake/validatePlanArtifact.mjs', contract.TRIO_ROOT).href);",
    'const chunks = [];',
    'for await (const chunk of process.stdin) chunks.push(chunk);',
    "const artifact = JSON.parse(Buffer.concat(chunks).toString('utf8'));",
    'const verdict = validateMod.validatePlanArtifact(artifact);',
    'process.stdout.write(JSON.stringify({',
    '  accepted: verdict.ok,',
    '  reasons: verdict.reasons ?? [],',
    '  canonical: validateMod.canonicalStringifyPlanArtifact(artifact),',
    '}));',
  ].join('\n');

  const child = spawnSync(process.execPath, ['--input-type=module', '-e', childScript], {
    cwd: rpRoot,
    input: JSON.stringify(artifact),
    encoding: 'utf8',
  });
  assert.equal(child.status, 0, `RP-shaped consumer process failed (stderr):\n${child.stderr}`);
  return JSON.parse(child.stdout);
}

describe('Wave 8 — interface parity: an RP-shaped consumer accepts the real PlanArtifact unmodified', () => {
  test('the seeds-only bootstrap artifact (pure end-to-end module output, zero mocks) is accepted byte-identically', async () => {
    const res = await entryMod.brownfieldIntake({ seeds: SEEDS });
    assert.equal(res.ok, true, res.reason);
    assert.equal(res.route, 'seeds-only-bootstrap');

    const consumer = runRpConsumer(res.artifact);
    assert.equal(consumer.accepted, true, JSON.stringify(consumer.reasons));
    // Byte-identical canonical serialization on both sides: consumed UNMODIFIED.
    assert.equal(consumer.canonical, validateMod.canonicalStringifyPlanArtifact(res.artifact));
    // …and the round-trip reproduces the artifact exactly (no reshaping anywhere).
    assert.deepStrictEqual(JSON.parse(consumer.canonical), res.artifact);
  });

  test('a derive-produced artifact (intent route) drives the same consumer unmodified and is accepted', async () => {
    const intent = 'compare deduplication thresholds across pretraining corpora';
    const derive = (payload) => {
      const anchors = [
        { sourceId: deriveMod.INTENT_SOURCE_ID, quote: payload.groundedSources[deriveMod.INTENT_SOURCE_ID] },
      ];
      return {
        artifactVersion: 'plan-artifact/1',
        scope: { statement: 'Derived scope.', axis: 'Derived AXIS.', anchors },
        branches: [{ question: 'Derived question?', rationale: 'Derived rationale.', anchors }],
        sourcesToBeat: [{ title: 'Derived baseline', why: 'Best current source.', anchors }],
        foresight: {
          dropped: 'nothing dropped',
          counterfactualCost: 'no cost',
          stamp: 'no foresight value added',
          anchors,
        },
        seeds: SEEDS.map(({ idType, id, title }) => ({ idType, id, title })),
      };
    };

    const res = await entryMod.brownfieldIntake({ intent, seeds: SEEDS, derive });
    assert.equal(res.ok, true, res.reason);
    assert.equal(res.route, 'intent-only');

    const consumer = runRpConsumer(res.artifact);
    assert.equal(consumer.accepted, true, JSON.stringify(consumer.reasons));
    assert.equal(consumer.canonical, validateMod.canonicalStringifyPlanArtifact(res.artifact));
    assert.deepStrictEqual(JSON.parse(consumer.canonical), res.artifact);
  });
});
