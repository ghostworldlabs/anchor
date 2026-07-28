// crucible/test/pack-lit-review-e2e.test.mjs — Wave 2: the literature-review pack run
// end-to-end (Front 1, first pack) on the DEFAULT (Claude) substrate.
//
// Proves the wave's done-when over ONE real lit-review deliverable:
//   - it passes Layers 1/2/3 end-to-end (all three layers invoked, rubric verdict PASS);
//   - the COMMITTED labeled N+N+N battery re-runs GREEN and the MEASURED rates meet the
//     pack's committed minima (>=90% planted-bad caught AND <=10% false-positive) over the
//     FULL labeled battery (not just one planted citation);
//   - the Layer-3 rubric scores the same deliverable DETERMINISTICALLY twice (same rubric
//     -> same verdict);
//   - the Given/When/Then: a planted fabricated citation is flagged RED at Layer 2, while a
//     clean version passes all three layers, with the rubric verdict reproducible.
//
// Model-free + deterministic by construction: the entailment judge and rubric scorer are
// injected label-blind heuristics (the live path swaps in the SR-5-attested agent seam the
// pack names). SR-1 stays GREEN because this file only ADDS gates (superset, never shrinks).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { runPackGate } from '../bin/packs/pack-gate.mjs';
import { assessEvidenceFaithfulness, runEntailmentBattery } from '../bin/packs/layer2-evidence.mjs';
import { scoreAgainstRubric } from '../bin/packs/layer3-rubric.mjs';
import { loadPack } from '../bin/packs/registry.mjs';
import {
  litReviewClean, litReviewPlanted, litSources, litCleanClaims, litPlantedClaims,
  litBattery, litEntail, litRubricScore,
} from './lit-review-e2e-fixtures.mjs';

const pack = loadPack('literature-review');

test('Wave 2: the clean lit-review PASSES Layers 1/2/3 end-to-end (battery-gated Layer 2 + rubric PASS)', async () => {
  const r = await runPackGate({
    pack, doc: litReviewClean,
    battery: litBattery, claims: litCleanClaims, sources: litSources,
    entail: litEntail, score: litRubricScore,
  });
  assert.equal(r.pass, true);
  assert.equal(r.stoppedAt, null);
  assert.deepEqual(r.layers_invoked, { layer1: true, layer2: true, layer3: true, machineGate: false });
  assert.equal(r.layer1.pass, true);
  assert.equal(r.layer2.meetsMinima, true);
  // Layer 2 evaluated the DELIVERABLE's own claims (not only the calibration battery).
  assert.equal(r.layer2.deliverable.pass, true, 'the deliverable\'s own claims are evidence-faithful');
  assert.equal(r.layer2.deliverable.flagged.length, 0);
  assert.equal(r.layer3.verdict, 'PASS');
  // SR-5: the result carries the governing pack + its named judge models.
  assert.equal(r.provenance.pack, 'literature-review');
  assert.equal(r.provenance.entailment_judge_model, 'claude-fable-5');
  assert.equal(r.provenance.rubric_judge_model, 'claude-fable-5');
});

test('Wave 2: the COMMITTED labeled N+N+N battery re-runs GREEN — measured rates meet the committed minima', async () => {
  // The battery is genuinely N+N+N (not just one planted citation).
  assert.ok(litBattery.entailed.length >= 3, 'N entailed controls');
  assert.ok(litBattery.fabricated.length >= 3, 'N fabricated (unresolved-citation) planted-bad');
  assert.ok(litBattery.overclaimed.length >= 3, 'N over-claimed (unsupported) planted-bad');

  const b = await runEntailmentBattery({ battery: litBattery, entail: litEntail, pack });
  assert.equal(b.plantedBad, 6, 'full planted-bad set (3 fabricated + 3 over-claimed)');
  assert.equal(b.entailedCount, 5);
  assert.ok(b.catchRate >= 0.9, `catch rate ${b.catchRate} >= 0.90`);
  assert.ok(b.falsePositiveRate <= 0.1, `false-positive rate ${b.falsePositiveRate} <= 0.10`);
  assert.equal(b.meetsMinima, true);
  assert.deepEqual(b.minima, { catch_rate_min: 0.9, false_positive_max: 0.1 });
});

test('Wave 2: a label-blind reject-all judge FAILS the minima (the battery gate is not vacuously green)', async () => {
  const b = await runEntailmentBattery({ battery: litBattery, entail: () => ({ entailed: false }), pack });
  assert.ok(b.falsePositiveRate > 0.1, 'flags entailed controls -> blows the FP bar');
  assert.equal(b.meetsMinima, false);
});

test('Wave 2 (Given/When/Then): a planted fabricated citation is flagged RED at Layer 2; the gate stops before Layer 3', async () => {
  let scoreCalled = false;
  const r = await runPackGate({
    pack, doc: litReviewPlanted, claims: litPlantedClaims, sources: litSources,
    entail: litEntail, score: (...a) => { scoreCalled = true; return litRubricScore(...a); },
  });
  assert.equal(r.pass, false);
  assert.equal(r.stoppedAt, 'layer2');
  assert.equal(r.layers_invoked.layer1, true, 'the planted doc is still well-formed (Layer 1 passes)');
  assert.equal(r.layers_invoked.layer3, false, 'no rubric call once Layer 2 fails');
  assert.equal(scoreCalled, false);
  // the fabricated citation ([S9]) is the one flagged, caught by the model-free cross-ref.
  const fab = r.layer2.flagged.find((f) => f.citation === 'S9');
  assert.ok(fab, 'the fabricated [S9] citation is flagged');
  assert.equal(fab.citationResolved, false, 'fabricated reference does not resolve to any source');
});

test('Wave 2 (Given/When/Then): the CLEAN deliverable\'s own claims are evidence-faithful (Layer 2 clean)', async () => {
  const r = await assessEvidenceFaithfulness({
    claims: litCleanClaims, sources: litSources, entail: litEntail, pack,
  });
  assert.equal(r.pass, true);
  assert.equal(r.flagged.length, 0);
  assert.equal(r.model, 'claude-fable-5', 'attests the entailment-judge model the pack names');
});

test('Wave 2: the Layer-3 rubric scores the deliverable DETERMINISTICALLY twice (same rubric -> same verdict)', async () => {
  const a = await scoreAgainstRubric({ doc: litReviewClean, pack, score: litRubricScore });
  const b = await scoreAgainstRubric({ doc: litReviewClean, pack, score: litRubricScore });
  assert.equal(a.verdict, 'PASS');
  assert.equal(a.verdict, b.verdict);
  assert.equal(a.aggregate_score, b.aggregate_score);
  assert.equal(a.rubric_frozen, true);
});

test('Wave 2: the full end-to-end gate verdict is reproducible across two runs', async () => {
  const run = () => runPackGate({ pack, doc: litReviewClean, battery: litBattery, entail: litEntail, score: litRubricScore });
  const a = await run();
  const b = await run();
  assert.equal(a.pass, b.pass);
  assert.equal(a.pass, true);
  assert.equal(a.layer3.verdict, b.layer3.verdict);
  assert.equal(a.layer3.aggregate_score, b.layer3.aggregate_score);
});
