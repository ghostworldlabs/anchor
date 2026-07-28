// crucible/test/pack-lit-review.test.mjs — Wave 1: literature-review pack definition +
// Layer-1 doc-contract. The pack registers + loads by id; provenance carries the SR-5
// `pack` field with its named judge models; the model-free Layer-1 validator passes a
// well-formed lit-review fixture (exit 0) and goes RED (exit 1) NAMING the missing
// section, deterministically across two runs. NO model is invoked (Layer 1 is pure).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { validatePackSchema } from '../bin/packs/pack-schema.mjs';
import { loadPack, listPacks, provenanceStamp } from '../bin/packs/registry.mjs';
import { literatureReviewPack } from '../bin/packs/literature-review-pack.mjs';
import { validateDocContract, runLayer1Cli } from '../bin/packs/layer1-contract.mjs';
import { litReviewWellFormed, litReviewMissingPrisma } from './pack-fixtures.mjs';

test('Wave 1: the literature-review pack is a well-formed doc pack (PRISMA sections, 3-7 rubric, named judges)', () => {
  const { ok, errors } = validatePackSchema(literatureReviewPack);
  assert.equal(ok, true, errors.join('; '));
  assert.equal(literatureReviewPack.kind, 'doc');
  // PRISMA-style contract includes the Methods and PRISMA Flow sections.
  const sectionIds = literatureReviewPack.doc_contract.required_sections.map((s) => s.id);
  assert.ok(sectionIds.includes('methods'));
  assert.ok(sectionIds.includes('prisma-flow'));
  // frozen rubric is within the 3-7 bound.
  const n = literatureReviewPack.rubric.criteria.length;
  assert.ok(n >= 3 && n <= 7, `rubric criteria count ${n} within 3-7`);
});

test('Wave 1: the lit-review pack REGISTERS + LOADS by id', () => {
  assert.ok(listPacks().includes('literature-review'), 'seeded in the registry');
  const p = loadPack('literature-review');
  assert.equal(p.id, 'literature-review');
  assert.equal(p.kind, 'doc');
});

test('Wave 1: provenanceStamp carries the SR-5 `pack` field + the named entailment/rubric judge models', () => {
  const prov = provenanceStamp(loadPack('literature-review'));
  assert.equal(prov.pack, 'literature-review');
  assert.equal(prov.pack_kind, 'doc');
  assert.equal(prov.pack_version, '1.0.0');
  assert.equal(prov.entailment_judge_model, 'claude-fable-5');
  assert.equal(prov.rubric_judge_model, 'claude-fable-5');
});

test('Wave 1: Layer 1 GREEN — a well-formed lit-review passes (exit 0), deterministically twice (model-free)', () => {
  const pack = loadPack('literature-review');
  const r1 = validateDocContract({ doc: litReviewWellFormed, pack });
  const r2 = validateDocContract({ doc: litReviewWellFormed, pack });
  assert.equal(r1.pass, true);
  assert.equal(r1.exitCode, 0);
  assert.equal(r1.checked, 5);
  assert.deepEqual(r1, r2, 'same (doc,pack) => identical verdict');
});

test('Wave 1: Layer 1 RED — the missing PRISMA-flow section fails (exit 1) and is NAMED, deterministically twice', () => {
  const pack = loadPack('literature-review');
  const r1 = validateDocContract({ doc: litReviewMissingPrisma, pack });
  const r2 = validateDocContract({ doc: litReviewMissingPrisma, pack });
  assert.equal(r1.pass, false);
  assert.equal(r1.exitCode, 1);
  assert.deepEqual(r1.missing, [{ id: 'prisma-flow', title: 'PRISMA Flow' }]);
  assert.deepEqual(r1, r2, 'same (doc,pack) => identical verdict');
});

test('Wave 1: Layer 1 CLI exits 0 on the well-formed lit-review, 1 on the missing-section one — NO model invoked', async () => {
  // The CLI seam takes loadPack + readFile ONLY — there is structurally no agent/model
  // seam to invoke. A throwing trap proves it: if anything tried to spawn a model the
  // run would reject. Nothing here can.
  const trap = () => { throw new Error('NO model may be invoked at Layer 1'); };
  const okCode = await runLayer1Cli(['literature-review', 'ok.md'], {
    loadPack, readFile: () => litReviewWellFormed, log: () => {}, agent: trap,
  });
  const badCode = await runLayer1Cli(['literature-review', 'bad.md'], {
    loadPack, readFile: () => litReviewMissingPrisma, log: () => {}, agent: trap,
  });
  assert.equal(okCode, 0);
  assert.equal(badCode, 1);
});
