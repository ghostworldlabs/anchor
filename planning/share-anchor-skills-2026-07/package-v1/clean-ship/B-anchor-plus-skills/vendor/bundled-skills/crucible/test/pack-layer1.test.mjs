// crucible/test/pack-layer1.test.mjs — Phase 2.2: the model-free doc-contract validator.
// GREEN (exit 0) on a well-formed doc, RED (exit 1) naming the missing section, with NO
// model invoked, deterministic across two runs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { validateDocContract, runLayer1Cli } from '../bin/packs/layer1-contract.mjs';
import { testDocPack, wellFormedDoc, malformedDoc } from './pack-fixtures.mjs';

test('Layer 1 GREEN: a well-formed doc passes (exit 0), deterministically twice', () => {
  const r1 = validateDocContract({ doc: wellFormedDoc, pack: testDocPack });
  const r2 = validateDocContract({ doc: wellFormedDoc, pack: testDocPack });
  assert.equal(r1.pass, true);
  assert.equal(r1.exitCode, 0);
  assert.deepEqual(r1, r2, 'same (doc,pack) => identical verdict');
});

test('Layer 1 RED: a missing required section fails (exit 1) and is NAMED', () => {
  const r = validateDocContract({ doc: malformedDoc, pack: testDocPack });
  assert.equal(r.pass, false);
  assert.equal(r.exitCode, 1);
  assert.deepEqual(r.missing, [{ id: 'prisma', title: 'PRISMA Flow' }]);
});

test('Layer 1 CLI exits 0 on well-formed, 1 on malformed (model-free)', async () => {
  const loadPack = () => testDocPack;
  const okCode = await runLayer1Cli(['test-doc', 'ok.md'], { loadPack, readFile: () => wellFormedDoc, log: () => {} });
  const badCode = await runLayer1Cli(['test-doc', 'bad.md'], { loadPack, readFile: () => malformedDoc, log: () => {} });
  assert.equal(okCode, 0);
  assert.equal(badCode, 1);
});

test('a section pattern (regex) is honored over the default heading match', () => {
  const pack = { id: 'p', kind: 'doc', version: '1.0.0',
    doc_contract: { required_sections: [{ id: 'reg', title: 'Registration', pattern: 'PROSPERO|registered' }] },
    evidence_standard: { entailment_judge_model: 'm' },
    rubric: { rubric_judge_model: 'm', criteria: [
      { id: 'a', statement: 'x' }, { id: 'b', statement: 'y' }, { id: 'c', statement: 'z' }] } };
  assert.equal(validateDocContract({ doc: 'This review was registered in PROSPERO.', pack }).pass, true);
  assert.equal(validateDocContract({ doc: 'No registration info.', pack }).pass, false);
});
