// test/shared-import-parity.test.mjs — Wave 1 lit-review-side import of the shared stub.
//
// literature-review consumes the shared brownfield-intake module from the PINNED trio
// shared-code home (<TRIO_ROOT>/trio-shared/brownfield-intake/index.mjs — see
// docs/DECISION-RECEIPT-shared-location.md) and asserts the returned plan-artifact-shaped
// object is consumed UNMODIFIED: exact field surface, deterministic byte-stable canonical
// serialization, no adapter/reshaping between the module and the consumer.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl, SHARED_BROWNFIELD_SPEC } from './_wave1-trio-resolve.mjs';

describe('Wave 1 — shared-import parity (literature-review side)', () => {
  let sharedUrl;
  let shared;

  before(async () => {
    sharedUrl = await sharedBrownfieldUrl();
    shared = await import(sharedUrl.href);
  });

  test('the shared module exists at the pinned trio shared-code home', () => {
    const onDisk = fileURLToPath(sharedUrl);
    assert.ok(fs.existsSync(onDisk), `pinned shared home missing on disk: ${onDisk}`);
    assert.ok(
      sharedUrl.href.endsWith(SHARED_BROWNFIELD_SPEC),
      'shared module URL must end with the pinned trio-relative specifier',
    );
  });

  test('the stub returns the plan-artifact-shaped object with the exact field surface', () => {
    assert.equal(typeof shared.makePlanArtifactStub, 'function');
    assert.equal(typeof shared.BROWNFIELD_INTAKE_VERSION, 'string');

    const artifact = shared.makePlanArtifactStub();
    assert.deepStrictEqual(
      Object.keys(artifact),
      ['artifactVersion', 'scope', 'branches', 'sourcesToBeat', 'foresight', 'seeds'],
      'plan-artifact shape: scope/AXIS, branches, sources-to-beat, foresight receipt, seeds[]',
    );
    assert.equal(artifact.artifactVersion, shared.BROWNFIELD_INTAKE_VERSION);
    assert.equal(typeof artifact.scope.statement, 'string');
    assert.equal(typeof artifact.scope.axis, 'string');
    assert.ok(Array.isArray(artifact.branches));
    assert.ok(Array.isArray(artifact.sourcesToBeat));
    assert.ok(Array.isArray(artifact.seeds));
    assert.equal(typeof artifact.foresight.dropped, 'string');
    assert.equal(typeof artifact.foresight.counterfactualCost, 'string');
    // Coverage/provenance is the Wave-1 subtractive decision: advisory sidecar, NEVER a field.
    assert.equal('coverage' in artifact, false);
    assert.equal('provenance' in artifact, false);
  });

  test('the object is consumed unmodified and serializes byte-stably (canonical JSON)', () => {
    const a = shared.makePlanArtifactStub();
    const b = shared.makePlanArtifactStub();
    const canonicalA = JSON.stringify(a, null, 2);
    const canonicalB = JSON.stringify(b, null, 2);
    assert.equal(canonicalA, canonicalB, 'two calls must serialize byte-identically');
    assert.notEqual(a, b, 'each call returns a fresh object (no shared mutable state)');
    // The consumer performs NO adaptation: a JSON round-trip reproduces the object exactly.
    assert.deepStrictEqual(JSON.parse(canonicalA), a);
  });
});
