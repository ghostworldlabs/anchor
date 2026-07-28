// Wave 1 — manifest-checker tests.
//
// Exercises the real Wave-1 source (src/manifest-checker.mjs) against the real SKILL.md
// and against synthetic content, so the gate proves the done-when:
//   "Given a fresh checkout, when the manifest checker runs, then it finds SKILL.md
//    naming all six pillars + the Honesty Law and exits 0."

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  checkManifest,
  checkManifestContent,
  PILLARS,
  HONESTY_LAW,
  DEFAULT_SKILL_PATH,
} from '../src/manifest-checker.mjs';

// --- Given/When/Then: the real SKILL.md on a fresh checkout ---

test('the shipped SKILL.md passes the manifest checker (exits OK, nothing missing)', () => {
  const result = checkManifest();
  assert.equal(result.ok, true, `expected SKILL.md to pass; missing: ${result.missing.join(', ')}`);
  assert.deepEqual(result.missing, []);
  assert.equal(result.path, DEFAULT_SKILL_PATH);
});

test('the shipped SKILL.md names every one of the six pillars + the Honesty Law', () => {
  assert.equal(PILLARS.length, 6, 'there must be exactly six pillars');
  for (const pillar of [...PILLARS, HONESTY_LAW]) {
    const result = checkManifestContent(`prefix ${pillar} suffix`);
    // sanity: each required token is individually detectable
    assert.equal(result.ok, false, `single-token probe should be incomplete for ${pillar}`);
  }
  // and the real file names all of them
  const result = checkManifest();
  assert.deepEqual(result.missing, []);
});

test('the shipped SKILL.md states the tiered-scope headline', () => {
  const content = fs.readFileSync(DEFAULT_SKILL_PATH, 'utf8');
  assert.match(content, /no autonomous proof verification/i);
  assert.match(content, /ACCEPT = computational sub-claim/i);
});

// --- Negative arms: the gate must FAIL (and name the gap) when something is absent ---

test('content missing a pillar fails and names the offending pillar', () => {
  // a manifest that names everything except "Formalize"
  const tokens = [...PILLARS.filter((p) => p !== 'Formalize'), HONESTY_LAW];
  const content = tokens.join(' and ');
  const result = checkManifestContent(content);
  assert.equal(result.ok, false);
  assert.deepEqual(result.missing, ['Formalize']);
});

test('content missing the Honesty Law fails and names it', () => {
  const content = PILLARS.join(' and ');
  const result = checkManifestContent(content);
  assert.equal(result.ok, false);
  assert.deepEqual(result.missing, [HONESTY_LAW]);
});

test('a missing SKILL.md file is itself a failure (not a crash)', () => {
  const result = checkManifest('./__definitely_not_a_real_manifest__.md');
  assert.equal(result.ok, false);
  assert.equal(result.missing.length, 1);
  assert.match(result.missing[0], /file not found/);
});

test('checkManifestContent rejects non-string input', () => {
  assert.throws(() => checkManifestContent(null), TypeError);
});
