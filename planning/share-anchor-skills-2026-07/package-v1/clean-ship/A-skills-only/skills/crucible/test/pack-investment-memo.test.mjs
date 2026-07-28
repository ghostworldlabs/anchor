// crucible/test/pack-investment-memo.test.mjs — Wave 4: the investment-memo pack
// definition + Layer-1 doc-contract, built by REUSING the Wave-1 kit. The pack registers +
// loads by id; provenance carries the SR-5 `pack` field with its named judge models; the
// model-free Layer-1 validator passes a well-formed memo (exit 0) and goes RED (exit 1)
// NAMING the missing section, deterministically across two runs. NO model is invoked.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { validatePackSchema } from '../bin/packs/pack-schema.mjs';
import { loadPack, listPacks, provenanceStamp } from '../bin/packs/registry.mjs';
import { investmentMemoPack } from '../bin/packs/investment-memo-pack.mjs';
import { validateDocContract, runLayer1Cli } from '../bin/packs/layer1-contract.mjs';
import { memoWellFormed, memoMissingValuation } from './investment-memo-e2e-fixtures.mjs';

test('Wave 4: the investment-memo pack is a well-formed doc pack (VC sections, 3-7 rubric, named judges)', () => {
  const { ok, errors } = validatePackSchema(investmentMemoPack);
  assert.equal(ok, true, errors.join('; '));
  assert.equal(investmentMemoPack.kind, 'doc');
  // The canonical VC contract includes the Investment Thesis and Valuation sections.
  const sectionIds = investmentMemoPack.doc_contract.required_sections.map((s) => s.id);
  assert.ok(sectionIds.includes('thesis'));
  assert.ok(sectionIds.includes('valuation'));
  // frozen rubric is within the 3-7 bound.
  const n = investmentMemoPack.rubric.criteria.length;
  assert.ok(n >= 3 && n <= 7, `rubric criteria count ${n} within 3-7`);
});

test('Wave 4: audited filings/data are the PRIMARY evidence, with as-of + jurisdiction required fields', () => {
  const ev = investmentMemoPack.evidence_standard;
  // Audited/regulated disclosures are the named primary-source kinds.
  assert.ok(ev.primary_source_kinds.includes('audited-financial-statement'));
  assert.ok(ev.primary_source_kinds.includes('regulatory-filing'));
  // Every primary source must carry an as-of date AND a jurisdiction (pack-config, not a fork).
  assert.deepEqual(ev.required_source_fields, ['as_of', 'jurisdiction']);
});

test('Wave 4: the investment-memo pack REGISTERS + LOADS by id', () => {
  assert.ok(listPacks().includes('investment-memo'), 'seeded in the registry');
  const p = loadPack('investment-memo');
  assert.equal(p.id, 'investment-memo');
  assert.equal(p.kind, 'doc');
});

test('Wave 4: provenanceStamp carries the SR-5 `pack` field + the named entailment/rubric judge models', () => {
  const prov = provenanceStamp(loadPack('investment-memo'));
  assert.equal(prov.pack, 'investment-memo');
  assert.equal(prov.pack_kind, 'doc');
  assert.equal(prov.pack_version, '1.0.0');
  assert.equal(prov.entailment_judge_model, 'claude-fable-5');
  assert.equal(prov.rubric_judge_model, 'claude-fable-5');
});

test('Wave 4: Layer 1 GREEN — a well-formed memo passes (exit 0), deterministically twice (model-free)', () => {
  const pack = loadPack('investment-memo');
  const r1 = validateDocContract({ doc: memoWellFormed, pack });
  const r2 = validateDocContract({ doc: memoWellFormed, pack });
  assert.equal(r1.pass, true);
  assert.equal(r1.exitCode, 0);
  assert.equal(r1.checked, 7);
  assert.deepEqual(r1, r2, 'same (doc,pack) => identical verdict');
});

test('Wave 4: Layer 1 RED — the missing Valuation section fails (exit 1) and is NAMED, deterministically twice', () => {
  const pack = loadPack('investment-memo');
  const r1 = validateDocContract({ doc: memoMissingValuation, pack });
  const r2 = validateDocContract({ doc: memoMissingValuation, pack });
  assert.equal(r1.pass, false);
  assert.equal(r1.exitCode, 1);
  assert.deepEqual(r1.missing, [{ id: 'valuation', title: 'Valuation' }]);
  assert.deepEqual(r1, r2, 'same (doc,pack) => identical verdict');
});

test('Wave 4: Layer 1 CLI exits 0 on the well-formed memo, 1 on the missing-section one — NO model invoked', async () => {
  // The CLI seam takes loadPack + readFile ONLY — there is structurally no agent/model seam
  // to invoke. A throwing trap proves it: if anything tried to spawn a model the run would
  // reject. Nothing here can.
  const trap = () => { throw new Error('NO model may be invoked at Layer 1'); };
  const okCode = await runLayer1Cli(['investment-memo', 'ok.md'], {
    loadPack, readFile: () => memoWellFormed, log: () => {}, agent: trap,
  });
  const badCode = await runLayer1Cli(['investment-memo', 'bad.md'], {
    loadPack, readFile: () => memoMissingValuation, log: () => {}, agent: trap,
  });
  assert.equal(okCode, 0);
  assert.equal(badCode, 1);
});
