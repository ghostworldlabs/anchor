// crucible/test/pack-investment-memo-e2e.test.mjs — Wave 4: the investment-memo pack run
// end-to-end (Front 1, SECOND pack) on the DEFAULT (Claude) substrate.
//
// Proves the wave's done-when over ONE real investment memo:
//   - it passes Layers 1/2/3 end-to-end (all three layers invoked, rubric verdict PASS);
//   - the memo's doc-contract + evidence standard are PACK-CONFIG ONLY (no gate-engine fork
//     — the inclusion test): the SAME engine modules the lit-review pack uses drive the memo,
//     and registering the memo pack leaves the software-pack regression byte-identical (no
//     shared-shell drift);
//   - the Given/When/Then: the real memo passes end-to-end, and a deliberately planted
//     fabricated citation is flagged RED at Layer 2 (the gate stops before Layer 3).
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
  memoClean, memoPlanted, memoSources, memoCleanClaims, memoPlantedClaims,
  memoBattery, memoEntail, memoRubricScore,
} from './investment-memo-e2e-fixtures.mjs';

const pack = loadPack('investment-memo');

test('Wave 4: the real investment-memo PASSES Layers 1/2/3 end-to-end (battery-gated Layer 2 + rubric PASS)', async () => {
  const r = await runPackGate({
    pack, doc: memoClean,
    battery: memoBattery, claims: memoCleanClaims, sources: memoSources,
    entail: memoEntail, score: memoRubricScore,
  });
  assert.equal(r.pass, true);
  assert.equal(r.stoppedAt, null);
  assert.deepEqual(r.layers_invoked, { layer1: true, layer2: true, layer3: true, machineGate: false });
  assert.equal(r.layer1.pass, true);
  assert.equal(r.layer2.meetsMinima, true);
  // Layer 2 evaluated the DELIVERABLE's own claims (not only the calibration battery).
  assert.equal(r.layer2.deliverable.pass, true, 'the memo\'s own financial claims are evidence-faithful');
  assert.equal(r.layer2.deliverable.flagged.length, 0);
  assert.equal(r.layer3.verdict, 'PASS');
  // SR-5: the result carries the governing pack + its named judge models.
  assert.equal(r.provenance.pack, 'investment-memo');
  assert.equal(r.provenance.entailment_judge_model, 'claude-fable-5');
  assert.equal(r.provenance.rubric_judge_model, 'claude-fable-5');
});

test('Wave 4: the COMMITTED labeled N+N+N battery re-runs GREEN — measured rates meet the committed minima', async () => {
  // The battery is genuinely N+N+N (not just one planted citation).
  assert.ok(memoBattery.entailed.length >= 3, 'N entailed controls');
  assert.ok(memoBattery.fabricated.length >= 3, 'N fabricated (unresolved-citation) planted-bad');
  assert.ok(memoBattery.overclaimed.length >= 3, 'N over-claimed (unsupported) planted-bad');

  const b = await runEntailmentBattery({ battery: memoBattery, entail: memoEntail, pack });
  assert.equal(b.plantedBad, 6, 'full planted-bad set (3 fabricated + 3 over-claimed)');
  assert.equal(b.entailedCount, 5);
  assert.ok(b.catchRate >= 0.9, `catch rate ${b.catchRate} >= 0.90`);
  assert.ok(b.falsePositiveRate <= 0.1, `false-positive rate ${b.falsePositiveRate} <= 0.10`);
  assert.equal(b.meetsMinima, true);
  assert.deepEqual(b.minima, { catch_rate_min: 0.9, false_positive_max: 0.1 });
});

test('Wave 4: a label-blind reject-all judge FAILS the minima (the battery gate is not vacuously green)', async () => {
  const b = await runEntailmentBattery({ battery: memoBattery, entail: () => ({ entailed: false }), pack });
  assert.ok(b.falsePositiveRate > 0.1, 'flags entailed controls -> blows the FP bar');
  assert.equal(b.meetsMinima, false);
});

test('Wave 4 (Given/When/Then): a planted fabricated citation is flagged RED at Layer 2; the gate stops before Layer 3', async () => {
  let scoreCalled = false;
  const r = await runPackGate({
    pack, doc: memoPlanted, claims: memoPlantedClaims, sources: memoSources,
    entail: memoEntail, score: (...a) => { scoreCalled = true; return memoRubricScore(...a); },
  });
  assert.equal(r.pass, false);
  assert.equal(r.stoppedAt, 'layer2');
  assert.equal(r.layers_invoked.layer1, true, 'the planted memo is still well-formed (Layer 1 passes)');
  assert.equal(r.layers_invoked.layer3, false, 'no rubric call once Layer 2 fails');
  assert.equal(scoreCalled, false);
  // the fabricated citation ([F9]) is the one flagged, caught by the model-free cross-ref.
  const fab = r.layer2.flagged.find((f) => f.citation === 'F9');
  assert.ok(fab, 'the fabricated [F9] citation is flagged');
  assert.equal(fab.citationResolved, false, 'fabricated reference does not resolve to any source');
});

test('Wave 4 (Given/When/Then): the CLEAN memo\'s own claims are evidence-faithful (Layer 2 clean)', async () => {
  const r = await assessEvidenceFaithfulness({
    claims: memoCleanClaims, sources: memoSources, entail: memoEntail, pack,
  });
  assert.equal(r.pass, true);
  assert.equal(r.flagged.length, 0);
  assert.equal(r.model, 'claude-fable-5', 'attests the entailment-judge model the pack names');
});

test('Wave 4: every audited PRIMARY source carries the pack-required as-of + jurisdiction fields', () => {
  // The "audited-filings/data with as-of + jurisdiction" requirement is honored as DATA over
  // the pack config — not by a memo-specific engine fork.
  const required = pack.evidence_standard.required_source_fields;
  const kinds = pack.evidence_standard.primary_source_kinds;
  for (const s of Object.values(memoSources)) {
    assert.ok(kinds.includes(s.kind), `source ${s.id} is an audited/regulated PRIMARY kind (${s.kind})`);
    for (const field of required) {
      assert.ok(typeof s[field] === 'string' && s[field].length > 0, `source ${s.id} carries a non-empty ${field}`);
    }
  }
});

test('Wave 4: the Layer-3 rubric scores the memo DETERMINISTICALLY twice (same rubric -> same verdict)', async () => {
  const a = await scoreAgainstRubric({ doc: memoClean, pack, score: memoRubricScore });
  const b = await scoreAgainstRubric({ doc: memoClean, pack, score: memoRubricScore });
  assert.equal(a.verdict, 'PASS');
  assert.equal(a.verdict, b.verdict);
  assert.equal(a.aggregate_score, b.aggregate_score);
  assert.equal(a.rubric_frozen, true);
});

test('Wave 4: the full end-to-end gate verdict is reproducible across two runs', async () => {
  const run = () => runPackGate({ pack, doc: memoClean, battery: memoBattery, entail: memoEntail, score: memoRubricScore });
  const a = await run();
  const b = await run();
  assert.equal(a.pass, b.pass);
  assert.equal(a.pass, true);
  assert.equal(a.layer3.verdict, b.layer3.verdict);
  assert.equal(a.layer3.aggregate_score, b.layer3.aggregate_score);
});

test('Wave 4 (inclusion test): the memo runs on the SAME engine and does NOT change software-pack behavior', async () => {
  // The memo pack and the lit-review pack route through the very same gate orchestrator —
  // the memo adds CONFIG, not an engine. Proof: the memo gate is the identical `runPackGate`
  // import, AND with the memo pack registered the software pack still routes machine-gate-only
  // (Layers 2-3 provably inert — no shared-shell drift).
  let layer2Touched = false, layer3Touched = false;
  const sw = await runPackGate({
    pack: loadPack('software'),
    machineGate: () => ({ pass: true, suite: 'frozen-software' }),
    entail: () => { layer2Touched = true; return { entailed: true }; },
    score: () => { layer3Touched = true; return { score: 1 }; },
  });
  assert.equal(sw.kind, 'software');
  assert.deepEqual(sw.layers_invoked, { layer1: false, layer2: false, layer3: false, machineGate: true });
  assert.equal(layer2Touched, false, 'no entailment spawn for software, even after the memo pack registered');
  assert.equal(layer3Touched, false, 'no rubric spawn for software, even after the memo pack registered');
  // The memo pack itself carries its contract/evidence/rubric as plain config (not engine code).
  assert.equal(pack.kind, 'doc');
  assert.ok(pack.doc_contract && pack.evidence_standard && pack.rubric, 'three-layer config present on the pack');
});
