// test/formal-governor.test.mjs — Wave 1: Formal stakes governor

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  INPUT_CLASSIFICATION,
  lockGovernorOutput,
  canonicalSerialize,
  hashLockedOutput
} from '../bin/formal-governor.mjs';

test('(done-when) Given A fixed set of Stage-1-known stakes inputs, when The governor is invoked twice with identical inputs, then Both runs emit byte-identical locked-output serializations with the same hash and identical roundBudget/bounds/thresholds', () => {
  const inputs1 = { stakesTier: 'high', N: 4, K: 5, M: 3, maxRounds: 10 };
  const inputs2 = { N: 4, stakesTier: 'high', maxRounds: 10, M: 3, K: 5 }; // different object property order
  
  const out1 = lockGovernorOutput(inputs1);
  const out2 = lockGovernorOutput(inputs2);
  
  // Identical output contract structure
  assert.deepEqual(out1, out2);
  assert.equal(out1.roundBudget, 10);
  assert.equal(out1.thresholds.N, 4);
  assert.deepEqual(out1.bounds, {});
  
  // Byte-identical locked-output serialization
  assert.equal(canonicalSerialize(out1), canonicalSerialize(out2));
  
  // Same hash
  assert.equal(hashLockedOutput(out1), hashLockedOutput(out2));
});

test('(done-when) Given An input flagged emergent-during-rounds in the classification table, when The initial budget is locked, then The lock is computed from Stage-1-known inputs only and the emergent input does not affect the initial roundBudget', () => {
  assert.equal(INPUT_CLASSIFICATION['emergentItem'], 'emergent-during-rounds');
  assert.equal(INPUT_CLASSIFICATION['stakesTier'], 'known-by-Stage-1');

  const stage1Inputs = { stakesTier: 'high', N: 4, maxRounds: 12 };
  const emergentInputs = { stakesTier: 'high', N: 4, maxRounds: 12, emergentItem: 'something unexpected' };
  
  const out1 = lockGovernorOutput(stage1Inputs);
  const out2 = lockGovernorOutput(emergentInputs);
  
  // The emergent input is stripped before computing the lock and inputsHash
  assert.deepEqual(out1, out2);
  assert.equal(out1.roundBudget, 12);
  assert.equal(out2.roundBudget, 12);
  assert.equal(hashLockedOutput(out1), hashLockedOutput(out2));
});

test('deterministic canonical serialization', () => {
  const a = { a: 1, b: { z: 9, y: 8 } };
  const b = { b: { y: 8, z: 9 }, a: 1 };
  assert.equal(canonicalSerialize(a), canonicalSerialize(b));
  assert.equal(canonicalSerialize(a), '{"a":1,"b":{"y":8,"z":9}}');
});

test('hash stability', () => {
  const output = {
    roundBudget: 8,
    bounds: {},
    thresholds: { N: 3, K: 4, M: 2 },
    provenance: { inputsHash: 'somehash', contractVersion: 1 }
  };
  const hash1 = hashLockedOutput(output);
  const hash2 = hashLockedOutput(output);
  assert.equal(hash1, hash2);
  // Ensure the hash logic doesn't throw or produce undefined
  assert.match(hash1, /^[a-f0-9]{64}$/);
});
