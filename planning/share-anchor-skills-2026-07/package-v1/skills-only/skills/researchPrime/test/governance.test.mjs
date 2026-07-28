// test/governance.test.mjs — Wave 3 Governance Tests
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { canonicalize, validate, CURRENT_SCHEMA_VERSION } from '../bin/governance.mjs';
import { HaltError } from '../bin/trio-core/contract-core.mjs';
import crypto from 'node:crypto';

test('canonicalize and validate: valid governance record', () => {
  const validRecord = {
    schemaVersion: CURRENT_SCHEMA_VERSION,
    triageHash: 'deadbeef',
    gate1Decision: 'APPROVE',
    planHash: 'cafebabe',
    gate2Decision: 'APPROVE',
    lockedGovernorOutput: { hash: 'hash123', serialized: '{}' },
    skill: 'researchPrime',
    hostApprovalProvider: 'tty'
  };

  // Re-serialize with reordered keys, CRLF line endings, and an extra optional field
  const recordWithExtra = {
    planHash: 'cafebabe',
    gate1Decision: 'APPROVE',
    schemaVersion: CURRENT_SCHEMA_VERSION,
    skill: 'researchPrime',
    extraField: 'someValue',
    triageHash: 'deadbeef',
    lockedGovernorOutput: { hash: 'hash123', serialized: '{}' },
    gate2Decision: 'APPROVE',
    hostApprovalProvider: 'tty'
  };

  // Create a JSON string with CRLF
  const jsonStr = JSON.stringify(recordWithExtra, null, 2).replace(/\n/g, '\r\n');

  const { canonicalObj, canonicalStr, warnings } = canonicalize(jsonStr);

  assert.ok(warnings.includes('unexpected-but-safe: extra fields present'), 'should warn about extra field');
  assert.equal(canonicalObj.extraField, 'someValue');
  
  // Verify key order: core fields first in exact order, then extra fields
  const keys = Object.keys(canonicalObj);
  assert.deepEqual(keys, [
    'schemaVersion',
    'triageHash',
    'gate1Decision',
    'planHash',
    'gate2Decision',
    'lockedGovernorOutput',
    'hostApprovalProvider',
    'skill',
    'extraField'
  ]);

  // Validation passes
  assert.equal(validate(canonicalObj), true);

  // Identity/hash binding unchanged check (hash of canonicalStr)
  const hash1 = crypto.createHash('sha256').update(canonicalStr).digest('hex');
  const { canonicalStr: canonicalStr2 } = canonicalize(JSON.stringify(recordWithExtra)); // No CRLF this time
  const hash2 = crypto.createHash('sha256').update(canonicalStr2).digest('hex');
  assert.equal(hash1, hash2, "CRLF vs LF should canonicalize to the same string (hash matches)");
});

test('canonicalize and validate: malformed or unparseable governance record', () => {
  assert.throws(() => {
    canonicalize('not a json object');
  }, HaltError, 'unparseable governance record -> HALT');

  assert.throws(() => {
    canonicalize('{"schemaVersion": 1,');
  }, HaltError, 'invalid JSON -> HALT');
});

test('canonicalize and validate: unsafe governance record', () => {
  const invalidDecision = {
    schemaVersion: CURRENT_SCHEMA_VERSION,
    triageHash: 'deadbeef',
    gate1Decision: 'MAYBE',
    planHash: 'cafebabe',
    gate2Decision: 'APPROVE',
    lockedGovernorOutput: { hash: 'hash123', serialized: '{}' },
    skill: 'researchPrime',
    hostApprovalProvider: 'tty'
  };

  const { canonicalObj } = canonicalize(JSON.stringify(invalidDecision));
  assert.throws(() => {
    validate(canonicalObj);
  }, HaltError, 'unsafe governance record: invalid gate1Decision -> HALT');
});
