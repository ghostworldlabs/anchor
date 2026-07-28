// crucible/test/pack-schema.test.mjs — Phase 2.1: PACK_SCHEMA / validatePackSchema /
// registry (loadPack, provenance, software seeded).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PACK_SCHEMA, validatePackSchema } from '../bin/packs/pack-schema.mjs';
import { loadPack, registerPack, listPacks, provenanceStamp } from '../bin/packs/registry.mjs';
import { testDocPack } from './pack-fixtures.mjs';

test('PACK_SCHEMA names the three required top-level fields', () => {
  assert.deepEqual(PACK_SCHEMA.required, ['id', 'kind', 'version']);
});

test('a well-formed doc pack validates', () => {
  const { ok, errors } = validatePackSchema(testDocPack);
  assert.equal(ok, true, errors.join('; '));
});

test('a doc pack MUST have >=1 section, a 3-7 rubric, and named judge models', () => {
  const bad = JSON.parse(JSON.stringify(testDocPack));
  bad.doc_contract.required_sections = [];
  bad.rubric.criteria = bad.rubric.criteria.slice(0, 2); // <3
  delete bad.evidence_standard.entailment_judge_model;
  const { ok, errors } = validatePackSchema(bad);
  assert.equal(ok, false);
  assert.ok(errors.some((e) => e.includes('required_sections')));
  assert.ok(errors.some((e) => e.includes('rubric.criteria')));
  assert.ok(errors.some((e) => e.includes('entailment_judge_model')));
});

test('a software pack MUST NOT carry doc-layer config (SR-6: Layers 2-3 inert)', () => {
  const sneaky = { id: 'x', kind: 'software', version: '1.0.0', rubric: { criteria: [] } };
  const { ok, errors } = validatePackSchema(sneaky);
  assert.equal(ok, false);
  assert.ok(errors.some((e) => e.includes("must NOT carry 'rubric'")));
});

test('the software reference pack is seeded in the registry and resolves', () => {
  assert.ok(listPacks().includes('software'));
  const sw = loadPack('software');
  assert.equal(sw.kind, 'software');
});

test('loadPack accepts an object, HALTs on an unknown id', () => {
  registerPack(testDocPack);
  assert.equal(loadPack('test-doc').id, 'test-doc');
  assert.throws(() => loadPack('nope-not-a-pack'), /unknown pack/);
});

test('provenanceStamp carries the pack id + named judge models (SR-5 pack field)', () => {
  const p = provenanceStamp(testDocPack);
  assert.equal(p.pack, 'test-doc');
  assert.equal(p.entailment_judge_model, 'claude-opus-4-8');
  assert.equal(p.rubric_judge_model, 'claude-opus-4-8');
  // software pack: no doc-layer models named
  assert.equal(provenanceStamp(loadPack('software')).rubric_judge_model, null);
});
