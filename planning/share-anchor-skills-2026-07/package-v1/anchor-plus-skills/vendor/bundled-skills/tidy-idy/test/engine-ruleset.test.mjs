// test/engine-ruleset.test.mjs — Wave 1: the ruleset-version stamp.
//
// Deliverable: "Ruleset-version stamp on every report and cache key".
//
// The stamp's job is to make a verdict INTERPRETABLE and INVALIDATABLE. A cached
// REMOVE verdict was produced under some protected set, some exclusion set and
// some prompt text; change any of those and the verdict no longer means what it
// meant. So the stamp must be:
//
//   • DETERMINISTIC   — the same ruleset always stamps the same, or old reports
//                       become unreadable and every cache entry misses;
//   • ORDER-INSENSITIVE — two configs listing the same patterns in a different
//                       order are the same ruleset and must share a cache;
//   • CHANGE-SENSITIVE — any change to any of the three inputs changes the stamp,
//                       or a stale verdict silently survives a rule change. That
//                       last one is the dangerous direction: a cache that fails
//                       to invalidate hands the panel a verdict the current rules
//                       would not have produced.

import { test, describe } from 'node:test';
import assert from 'node:assert';

import {
  computeRulesetVersion,
  verdictCacheKey,
  PROMPT_VERSION,
  RULESET_STAMP_FORMAT,
} from '../engine/ruleset.mjs';
import { makeProtection } from '../engine/protection.mjs';

const base = () => ({
  protectedPatterns: ['SKILL.md', 'bin/**', 'test/**'],
  exclusionPatterns: ['node_modules/**', 'dist/**'],
  promptVersion: PROMPT_VERSION,
});

describe('ruleset stamp', () => {
  test('is deterministic and carries its format prefix', () => {
    const a = computeRulesetVersion(base());
    const b = computeRulesetVersion(base());
    assert.strictEqual(a, b);
    assert.ok(a.startsWith(`${RULESET_STAMP_FORMAT}-`), `stamp '${a}' must name the format that produced it`);
    assert.match(a, /^rs1-[0-9a-f]{16}$/);
  });

  test('is ORDER-insensitive (the same ruleset written in another order is the same ruleset)', () => {
    const shuffled = {
      ...base(),
      protectedPatterns: ['test/**', 'SKILL.md', 'bin/**'],
      exclusionPatterns: ['dist/**', 'node_modules/**'],
    };
    assert.strictEqual(computeRulesetVersion(base()), computeRulesetVersion(shuffled));
  });

  test('duplicate patterns do not change the ruleset', () => {
    const dupes = { ...base(), protectedPatterns: [...base().protectedPatterns, 'SKILL.md'] };
    assert.strictEqual(computeRulesetVersion(base()), computeRulesetVersion(dupes));
  });

  test('ANY change to ANY of the three inputs changes the stamp', () => {
    const original = computeRulesetVersion(base());
    const mutations = {
      'added protected pattern': { ...base(), protectedPatterns: [...base().protectedPatterns, 'docs/**'] },
      'removed protected pattern': { ...base(), protectedPatterns: ['SKILL.md', 'bin/**'] },
      'added exclusion': { ...base(), exclusionPatterns: [...base().exclusionPatterns, 'vendor/**'] },
      'bumped prompt version': { ...base(), promptVersion: 'tidy-idy/prompts@99' },
    };
    for (const [what, mutated] of Object.entries(mutations)) {
      assert.notStrictEqual(computeRulesetVersion(mutated), original,
        `${what} left the stamp unchanged — a cached verdict would silently survive a rule change`);
    }
  });

  test('an additive .tidy-idy.toml changes the stamp (so its verdicts do not reuse the unconfigured cache)', () => {
    const plain = makeProtection();
    const configured = makeProtection({ protect: { patterns: ['src/sacred/**'] } });
    const stampOf = (p) => computeRulesetVersion({ protectedPatterns: p.patterns, exclusionPatterns: p.exclusions });
    assert.notStrictEqual(stampOf(configured), stampOf(plain));
  });
});

describe('verdict cache key', () => {
  test('is (content hash, ruleset version) — both, always', () => {
    const key = verdictCacheKey({ contentHash: 'sha256:abc', rulesetVersion: 'rs1-0123456789abcdef' });
    assert.ok(key.includes('sha256:abc'), 'the cache key must bind the content it judged');
    assert.ok(key.includes('rs1-0123456789abcdef'), 'the cache key must bind the ruleset that judged it');
  });

  test('the same content under a different ruleset is a DIFFERENT key (no stale reuse)', () => {
    const k1 = verdictCacheKey({ contentHash: 'sha256:abc', rulesetVersion: 'rs1-aaaaaaaaaaaaaaaa' });
    const k2 = verdictCacheKey({ contentHash: 'sha256:abc', rulesetVersion: 'rs1-bbbbbbbbbbbbbbbb' });
    assert.notStrictEqual(k1, k2);
  });

  test('a missing half is a loud refusal, never a partial key', () => {
    assert.throws(() => verdictCacheKey({ rulesetVersion: 'rs1-x' }), /contentHash/);
    assert.throws(() => verdictCacheKey({ contentHash: 'sha256:abc' }), /rulesetVersion/);
  });
});
