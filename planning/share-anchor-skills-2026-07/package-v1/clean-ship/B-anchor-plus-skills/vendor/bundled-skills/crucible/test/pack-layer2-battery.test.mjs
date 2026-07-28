// crucible/test/pack-layer2-battery.test.mjs — Phase 2.3: the evidence-faithfulness
// battery. Positive control (planted-bad caught), negative control (entailed passes),
// and the stated minima gate (>=90% caught, <=10% false-positive). A reject-all judge
// must FAIL the minima (so the gate isn't vacuously green).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { assessEvidenceFaithfulness, runEntailmentBattery } from '../bin/packs/layer2-evidence.mjs';
import { testDocPack, battery, stubEntail, stubEntailRejectAll } from './pack-fixtures.mjs';

test('positive control: a fabricated citation + an over-claim are both flagged', async () => {
  const r = await assessEvidenceFaithfulness({
    claims: [...battery.fabricated, ...battery.overclaimed],
    sources: battery.sources, entail: stubEntail, pack: testDocPack,
  });
  assert.equal(r.pass, false);
  assert.equal(r.flagged.length, 2);
  // the fabricated one is caught specifically by the cross-ref (no model needed)
  assert.equal(r.results.find((x) => x.id === 'f1').citationResolved, false);
});

test('negative control: genuinely entailed claims pass clean (no false positives)', async () => {
  const r = await assessEvidenceFaithfulness({
    claims: battery.entailed, sources: battery.sources, entail: stubEntail, pack: testDocPack,
  });
  assert.equal(r.pass, true);
  assert.equal(r.flagged.length, 0);
});

test('the labeled battery MEETS the pack minima (>=90% caught, <=10% FP)', async () => {
  const b = await runEntailmentBattery({ battery, entail: stubEntail, pack: testDocPack });
  assert.equal(b.catchRate, 1);            // 2/2 planted-bad caught
  assert.equal(b.falsePositiveRate, 0);    // 0/2 entailed flagged
  assert.equal(b.meetsMinima, true);
  assert.deepEqual(b.minima, { catch_rate_min: 0.9, false_positive_max: 0.1 });
});

test('a reject-all judge FAILS the minima (false-positive rate blows the bar)', async () => {
  const b = await runEntailmentBattery({ battery, entail: stubEntailRejectAll, pack: testDocPack });
  assert.equal(b.falsePositiveRate, 1);    // flags both entailed claims
  assert.equal(b.meetsMinima, false);
});

test('the entailment-judge model is the one the pack names (attestation source)', async () => {
  const r = await assessEvidenceFaithfulness({
    claims: battery.entailed, sources: battery.sources, entail: stubEntail, pack: testDocPack,
  });
  assert.equal(r.model, 'claude-opus-4-8');
});
