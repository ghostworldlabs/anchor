// generator-relative-ban.test.mjs — 2026-07: the Honesty Law's family ban is
// verifier ≠ GENERATOR, not "never Claude". Default generator stays 'claude'
// (every historical caller/behavior preserved, including the never-claude
// refusal); a claim authored by ANOTHER family may be verified by Claude — the
// strongest judge on this host — while same-family minting still hard-faults.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  makeVerdictRecord,
  validateArtifact,
  CrossFamilyDriverError,
} from '../src/cross-family-driver.mjs';

const BASE = {
  model: 'claude-fable-5',
  tier: 'frontier',
  prompt: 'Is 7 prime? Answer YES or NO.',
  rawAnswer: 'YES',
};

test('default (claude-authored): a claude verdict still hard-faults — historical behavior intact', () => {
  assert.throws(
    () => makeVerdictRecord({ ...BASE, verifier_family: 'claude' }),
    (e) => e instanceof CrossFamilyDriverError && /generator/i.test(e.message),
  );
});

test('a gemini-authored claim MAY be verified by claude (generator-relative)', () => {
  const rec = makeVerdictRecord({ ...BASE, verifier_family: 'claude', generator_family: 'gemini' });
  assert.equal(rec.artifact.verifier_family, 'claude');
  assert.equal(rec.verdict, 'YES');
  const v = validateArtifact(rec.artifact, { generator_family: 'gemini' });
  assert.equal(v.ok, true, v.failures.join('; '));
});

test('same-family minting hard-faults for ANY generator, not just claude', () => {
  assert.throws(
    () => makeVerdictRecord({ ...BASE, model: 'Gemini 3.1 Pro (High)', verifier_family: 'gemini', generator_family: 'gemini' }),
    (e) => e instanceof CrossFamilyDriverError,
  );
});

test('validateArtifact default keeps the historical never-claude check', () => {
  const rec = makeVerdictRecord({ ...BASE, verifier_family: 'claude', generator_family: 'gemini' });
  const v = validateArtifact(rec.artifact); // no generator passed => default 'claude'
  assert.equal(v.ok, false, 'a claude verdict without a declared non-claude generator must still fail');
  assert.ok(v.failures.some((f) => /generator/i.test(f)));
});

test('gemini verification of a claude-authored claim is unchanged (the historical happy path)', () => {
  const rec = makeVerdictRecord({ ...BASE, model: 'Gemini 3.1 Pro (High)', verifier_family: 'gemini' });
  assert.equal(validateArtifact(rec.artifact).ok, true);
});
