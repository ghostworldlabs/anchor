// crucible/test/pack-gate.test.mjs — the three-layer orchestrator end-to-end + the
// Layer-1 short-circuit (a malformed doc never spends a model call).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { runPackGate } from '../bin/packs/pack-gate.mjs';
import {
  testDocPack, wellFormedDoc, malformedDoc, battery, stubEntail, stubScorePass,
} from './pack-fixtures.mjs';

test('doc pack PASSES end-to-end with all three layers invoked', async () => {
  const r = await runPackGate({
    pack: testDocPack, doc: wellFormedDoc,
    battery, entail: stubEntail, score: stubScorePass,
  });
  assert.equal(r.pass, true);
  assert.deepEqual(r.layers_invoked, { layer1: true, layer2: true, layer3: true, machineGate: false });
  assert.equal(r.layer3.verdict, 'PASS');
  assert.equal(r.provenance.pack, 'test-doc');
});

test('Layer 1 short-circuits a malformed doc — Layers 2/3 are NEVER invoked', async () => {
  let entailCalled = false, scoreCalled = false;
  const r = await runPackGate({
    pack: testDocPack, doc: malformedDoc, battery,
    entail: (...a) => { entailCalled = true; return stubEntail(...a); },
    score: (...a) => { scoreCalled = true; return stubScorePass(...a); },
  });
  assert.equal(r.pass, false);
  assert.equal(r.stoppedAt, 'layer1');
  assert.equal(r.layers_invoked.layer2, false);
  assert.equal(r.layers_invoked.layer3, false);
  assert.equal(entailCalled, false, 'no model call on a malformed doc');
  assert.equal(scoreCalled, false);
});

test('a Layer-2 minima miss stops before Layer 3', async () => {
  const r = await runPackGate({
    pack: testDocPack, doc: wellFormedDoc,
    battery, entail: () => ({ entailed: false }), // reject-all => minima miss
    score: stubScorePass,
  });
  assert.equal(r.pass, false);
  assert.equal(r.stoppedAt, 'layer2');
  assert.equal(r.layers_invoked.layer3, false);
});
