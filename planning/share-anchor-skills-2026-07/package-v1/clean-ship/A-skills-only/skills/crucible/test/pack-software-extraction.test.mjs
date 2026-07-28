// crucible/test/pack-software-extraction.test.mjs — Phase 2.5 (SR-6 runtime proof).
// The software pack routes through the SAME pack shell as doc packs, but as the extracted
// REFERENCE it runs ONLY the machine well-formedness gate: Layers 2-3 are PROVABLY never
// invoked, and its pass/fail mirrors the injected machine gate byte-for-byte.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { runPackGate } from '../bin/packs/pack-gate.mjs';
import { loadPack } from '../bin/packs/registry.mjs';

test('software pack: machine gate runs, Layers 2-3 are NEVER invoked', async () => {
  let layer2Touched = false, layer3Touched = false;
  const r = await runPackGate({
    pack: loadPack('software'),
    machineGate: () => ({ pass: true, suite: 'frozen-software-473' }),
    // sentinels that MUST stay untouched for a software pack
    entail: () => { layer2Touched = true; return { entailed: true }; },
    score: () => { layer3Touched = true; return { score: 1 }; },
  });
  assert.equal(r.kind, 'software');
  assert.equal(r.pass, true);
  assert.equal(r.layers_invoked.layer2, false);
  assert.equal(r.layers_invoked.layer3, false);
  assert.equal(r.layers_invoked.machineGate, true);
  assert.equal(layer2Touched, false, 'no entailment spawn for software');
  assert.equal(layer3Touched, false, 'no rubric spawn for software');
});

test('software pack pass/fail mirrors the machine gate byte-for-byte (both directions)', async () => {
  const pass = await runPackGate({ pack: loadPack('software'), machineGate: () => ({ pass: true }) });
  const fail = await runPackGate({ pack: loadPack('software'), machineGate: () => ({ pass: false }) });
  assert.equal(pass.pass, true);
  assert.equal(fail.pass, false);
  // still no doc-layer involvement on the failing path
  assert.equal(fail.layers_invoked.layer2, false);
  assert.equal(fail.layers_invoked.layer3, false);
});
