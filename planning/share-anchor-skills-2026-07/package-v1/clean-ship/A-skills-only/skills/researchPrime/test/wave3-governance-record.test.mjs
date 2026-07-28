import test from 'node:test';
import assert from 'node:assert';
import crypto from 'node:crypto';
import { 
  canonicalizeRecord, 
  validateGovernanceRecord, 
  SCHEMA_VERSION 
} from '../bin/governance-record.mjs';

function deterministicStringify(obj) {
  if (obj === null || typeof obj !== 'object') {
    return JSON.stringify(obj);
  }
  if (Array.isArray(obj)) {
    return '[' + obj.map(deterministicStringify).join(',') + ']';
  }
  const keys = Object.keys(obj).sort();
  const parts = keys.map(k => JSON.stringify(k) + ':' + deterministicStringify(obj[k]));
  return '{' + parts.join(',') + '}';
}

function createValidResearchPrimeRecord() {
  const lockedGovernorOutput = {
    roundBudget: 8,
    bounds: {},
    thresholds: { N: 1, K: 3, M: 0 },
    tier: 'high',
    provenance: { inputsHash: 'fakehash', contractVersion: 1 }
  };
  
  const lockedGovernorHash = crypto.createHash('sha256').update(deterministicStringify(lockedGovernorOutput)).digest('hex');

  return {
    schema_version: SCHEMA_VERSION,
    skill_name: 'researchPrime',
    triage_artifact_hash: 'triagehash123',
    gate_1_decision: 'APPROVE',
    plan_artifact_hash: 'planhash123',
    gate_2_decision: 'APPROVE',
    locked_governor_output: lockedGovernorOutput,
    locked_governor_hash: lockedGovernorHash,
    host_approval_provider: 'tty',
    ext_research_target: 'some-target'
  };
}

test('Wave 3: Valid governance record passes validation', () => {
  const record = createValidResearchPrimeRecord();
  const result = validateGovernanceRecord(record);
  assert.strictEqual(result.valid, true, `Validation should pass, but failed with: ${result.errors.join(', ')}`);
});

test('Wave 3: Canonicalization and adversarial serialization (key reorder, CRLF, extra field)', () => {
  const validRecord = createValidResearchPrimeRecord();
  
  // Re-serialize with reordered keys
  const reorderedKeys = Object.keys(validRecord).reverse();
  let reorderedJson = '{';
  for (let i = 0; i < reorderedKeys.length; i++) {
    const key = reorderedKeys[i];
    reorderedJson += `"${key}": ${JSON.stringify(validRecord[key])}`;
    if (i < reorderedKeys.length - 1) reorderedJson += ',';
  }
  // Add CRLF line endings and an extra optional field
  reorderedJson += ',\r\n"unknown_optional_field": "something"\r\n}';

  const { canonicalString, parsedObject, warnings } = canonicalizeRecord(reorderedJson);
  
  const validationResult = validateGovernanceRecord(parsedObject);
  
  assert.strictEqual(validationResult.valid, true, 'Validation passes on canonicalized form');
  assert.strictEqual(warnings.length, 1, 'Should have 1 warning for unexpected-but-safe extra field');
  assert.match(warnings[0], /unknown_optional_field/, 'Warning should mention the unknown field');
  
  // Ensure the record's identity binding (locked_governor_hash) is unchanged and still valid
  assert.strictEqual(validationResult.errors.length, 0);
  assert.strictEqual(parsedObject.locked_governor_hash, validRecord.locked_governor_hash);
});

test('Wave 3: Malformed or unparseable governance record signals HALT', () => {
  const malformedJson = '{ "schema_version": 1, "skill_name": "researchPrime", '; // truncated

  assert.throws(() => {
    canonicalizeRecord(malformedJson);
  }, /HALT: Unparseable governance record/);
});

test('Wave 3: Missing core fields or invalid hash binding signals errors', () => {
  const record = createValidResearchPrimeRecord();
  record.locked_governor_hash = 'wronghash'; // Break the hash binding

  const validationResult = validateGovernanceRecord(record);
  assert.strictEqual(validationResult.valid, false, 'Should be invalid with wrong hash');
  assert.ok(validationResult.errors.some(e => e.includes('mismatch')), 'Error should mention hash mismatch');
});
