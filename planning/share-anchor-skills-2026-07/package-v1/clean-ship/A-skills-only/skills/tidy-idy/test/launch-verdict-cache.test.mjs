// test/launch-verdict-cache.test.mjs — Wave 5: the content-hash verdict cache.
//
// The cache exists to make the staleness loop affordable. The thing it must
// never do is serve a verdict about bytes it was not made about — so the tests
// below are mostly about MISSES: an edited file, a changed ruleset, a different
// debate scope.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import { openVerdictCache, nullVerdictCache, verdictKey, cachePathFor } from '../engine/launch/verdict-cache.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';

let dir;
before(async () => { dir = await makeTempRoot('tidy-idy-w5-cache-'); });
after(async () => { await rmTempRoot(dir); });

const HASH_A = 'sha256:aaa';
const HASH_B = 'sha256:bbb';

describe('the key', () => {
  test('is (content hash, ruleset version, scope) — and nothing else', () => {
    const base = { contentHash: HASH_A, rulesetVersion: 'rs1', scope: 'alignment' };
    assert.strictEqual(verdictKey(base), verdictKey({ ...base }));
    assert.notStrictEqual(verdictKey(base), verdictKey({ ...base, contentHash: HASH_B }));
    assert.notStrictEqual(verdictKey(base), verdictKey({ ...base, rulesetVersion: 'rs2' }));
    assert.notStrictEqual(verdictKey(base), verdictKey({ ...base, scope: 'evidence-sufficiency' }));
    assert.strictEqual(verdictKey({ contentHash: null, rulesetVersion: 'rs1' }), null);
  });
});

describe('hit and miss semantics', () => {
  test('same bytes hit; changed bytes MISS', async () => {
    const cache = await openVerdictCache({ reportDir: dir, rulesetVersion: 'rs1' });
    cache.set({ contentHash: HASH_A, scope: 'alignment', path: 'a.txt', verdict: { decision: 'REMOVE', rationale: 'because' } });
    assert.deepStrictEqual(cache.get({ contentHash: HASH_A, scope: 'alignment' }), { decision: 'REMOVE', rationale: 'because' });
    assert.strictEqual(cache.get({ contentHash: HASH_B, scope: 'alignment' }), null,
      'an edited file has no cached verdict, by construction');
    await cache.save();
  });

  test('a bumped ruleset version invalidates every prior verdict', async () => {
    const cache = await openVerdictCache({ reportDir: dir, rulesetVersion: 'rs2-different-prompt' });
    assert.strictEqual(cache.get({ contentHash: HASH_A, scope: 'alignment' }), null,
      'the same bytes are a DIFFERENT QUESTION under a different ruleset');
  });

  test('a scope change misses too', async () => {
    const cache = await openVerdictCache({ reportDir: dir, rulesetVersion: 'rs1' });
    assert.ok(cache.get({ contentHash: HASH_A, scope: 'alignment' }));
    assert.strictEqual(cache.get({ contentHash: HASH_A, scope: 'evidence-sufficiency' }), null);
  });
});

describe('persistence', () => {
  test('survives a reopen and lands under reportDir (tool state, not project content)', async () => {
    const reopened = await openVerdictCache({ reportDir: dir, rulesetVersion: 'rs1' });
    assert.strictEqual(reopened.stats.loaded, true);
    assert.ok(reopened.get({ contentHash: HASH_A, scope: 'alignment' }));
    assert.strictEqual(cachePathFor(dir), path.join(dir, 'verdict-cache.json'));
  });

  test('a corrupt cache degrades to a full pass, never to a wrong verdict', async () => {
    const other = await makeTempRoot('tidy-idy-w5-cache2-');
    try {
      await fs.writeFile(cachePathFor(other), 'not json at all');
      const cache = await openVerdictCache({ reportDir: other, rulesetVersion: 'rs1' });
      assert.strictEqual(cache.stats.loaded, false);
      assert.strictEqual(cache.get({ contentHash: HASH_A }), null);
    } finally {
      await rmTempRoot(other);
    }
  });

  test('a cache from another schema version is DROPPED, not migrated', async () => {
    const other = await makeTempRoot('tidy-idy-w5-cache3-');
    try {
      await fs.writeFile(cachePathFor(other), JSON.stringify({ version: 999, entries: { x: { verdict: { decision: 'REMOVE' } } } }));
      const cache = await openVerdictCache({ reportDir: other, rulesetVersion: 'rs1' });
      assert.strictEqual(cache.stats.loaded, false);
    } finally {
      await rmTempRoot(other);
    }
  });

  test('the recorded path is forensic only — it can never be matched on', async () => {
    const other = await makeTempRoot('tidy-idy-w5-cache4-');
    try {
      const cache = await openVerdictCache({ reportDir: other, rulesetVersion: 'rs1' });
      cache.set({ contentHash: HASH_A, path: 'a.txt', verdict: { decision: 'RETAIN' } });
      await cache.save();
      const raw = JSON.parse(await fs.readFile(cachePathFor(other), 'utf8'));
      const [entry] = Object.values(raw.entries);
      assert.strictEqual(entry.path, 'a.txt');
      // The stored path is not part of any key, so a file MOVED to that path with
      // different content cannot pick up this verdict.
      const reopened = await openVerdictCache({ reportDir: other, rulesetVersion: 'rs1' });
      assert.strictEqual(reopened.get({ contentHash: HASH_B }), null);
    } finally {
      await rmTempRoot(other);
    }
  });
});

describe('disabled', () => {
  test('a disabled cache always misses and writes nothing', async () => {
    const other = await makeTempRoot('tidy-idy-w5-cache5-');
    try {
      const cache = await openVerdictCache({ reportDir: other, rulesetVersion: 'rs1', enabled: false });
      assert.strictEqual(cache.set({ contentHash: HASH_A, verdict: { decision: 'REMOVE' } }), false);
      assert.strictEqual(cache.get({ contentHash: HASH_A }), null);
      assert.deepStrictEqual(await cache.save(), { written: false });
      await assert.rejects(fs.stat(cachePathFor(other)), /ENOENT/);
    } finally {
      await rmTempRoot(other);
    }
  });

  test('the null cache has the same shape', () => {
    const cache = nullVerdictCache();
    assert.strictEqual(cache.get({ contentHash: HASH_A }), null);
    assert.strictEqual(cache.summary().enabled, false);
  });
});
