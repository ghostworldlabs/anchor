// test/review-seat-labels.test.mjs — Wave 5: ban API-style Gemini product ids;
// review seats via gemini-cli / family labels only.
//
// Pins IMPLEMENTATION-PLAN.md Wave 5 GWT:
//   Given review/check seats in either skill path, when model labels are
//   resolved, then no API-style Gemini product ids; gemini-cli / family labels only.

import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  isApiStyleGeminiProductId,
  reviewSeatLineage,
  assertNoApiStyleGeminiIds,
  assertReviewSeatRoutes,
  findApiStyleGeminiIdsInSource,
  GEMINI_CLI_DRIVER,
  ALLOWED_DRIVERS,
  ALLOWED_FAMILIES,
  ReviewSeatLabelError,
} from '../src/reviewSeatLabels.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.resolve(TEST_DIR, '..');

describe('Wave 5 — review seat label surface', () => {
  test('exports gemini-cli driver, allowlists, and helpers', () => {
    assert.equal(GEMINI_CLI_DRIVER, 'gemini-cli');
    assert.ok(ALLOWED_DRIVERS.includes('gemini-cli'));
    assert.ok(ALLOWED_FAMILIES.includes('gemini'));
    assert.equal(typeof isApiStyleGeminiProductId, 'function');
    assert.equal(typeof reviewSeatLineage, 'function');
    assert.equal(typeof assertNoApiStyleGeminiIds, 'function');
    assert.equal(typeof assertReviewSeatRoutes, 'function');
  });
});

describe('Wave 5 — API-style Gemini product ids are banned', () => {
  test('detects common API / Vertex product strings', () => {
    const banned = [
      'gemini-1.5-pro',
      'gemini-1.5-flash',
      'gemini-2.0-flash',
      'gemini-2.5-pro-preview-05-06',
      'gemini-pro',
      'gemini-pro-vision',
      'gemini-flash',
      'gemini-ultra',
      'models/gemini-1.5-pro',
      'google/gemini-1.5-pro',
    ];
    for (const id of banned) {
      assert.equal(
        isApiStyleGeminiProductId(id),
        true,
        `expected API-style ban for ${id}`,
      );
    }
  });

  test('allows family, gemini-cli driver, and lineage tags', () => {
    const allowed = [
      'gemini',
      'gemini-cli',
      'gemini-cli:0',
      'gemini-cli:1',
      'review_family',
      'REVIEW_FAMILY',
      'review_family:gemini',
      'family:gemini',
      'claude',
      'grok-cli',
    ];
    for (const id of allowed) {
      assert.equal(
        isApiStyleGeminiProductId(id),
        false,
        `expected allow for ${id}`,
      );
    }
  });

  test('assertNoApiStyleGeminiIds throws naming the offenders', () => {
    assert.throws(
      () => assertNoApiStyleGeminiIds(['gemini-cli', 'gemini-1.5-pro', 'claude']),
      (err) =>
        err instanceof ReviewSeatLabelError &&
        /gemini-1\.5-pro/.test(err.message),
    );
    assert.equal(assertNoApiStyleGeminiIds(['gemini-cli', 'gemini-cli:0', 'gemini']), true);
  });
});

describe('Wave 5 — reviewSeatLineage is gemini-cli form only', () => {
  test('produces gemini-cli:N lineage tags', () => {
    assert.equal(reviewSeatLineage(0), 'gemini-cli:0');
    assert.equal(reviewSeatLineage(2), 'gemini-cli:2');
  });

  test('refuses product ids in driver/family opts', () => {
    assert.throws(
      () => reviewSeatLineage(0, { driver: 'gemini-1.5-pro' }),
      ReviewSeatLabelError,
    );
  });
});

describe('Wave 5 — routes tables reject product model fields on review seats', () => {
  test('historical DEFAULT_ROUND_ROUTES shape (gemini-cli drivers) is clean', () => {
    const routes = {
      reviewer: { driver: 'gemini-cli' },
      shark: { driver: 'gemini-cli' },
      debate: { driver: 'gemini-cli' },
      judge: { driver: 'gemini-cli' },
      synthesizer: { driver: 'claude' },
    };
    assert.equal(assertReviewSeatRoutes(routes), true);
  });

  test('product model on a reviewer seat fails closed', () => {
    assert.throws(
      () =>
        assertReviewSeatRoutes({
          reviewer: { driver: 'gemini-cli', model: 'gemini-1.5-pro' },
        }),
      ReviewSeatLabelError,
    );
  });
});

describe('Wave 5 — lit-review CLI uses gemini-cli labels (no product ids)', () => {
  test('bin/cli.mjs has no API-style Gemini product ids and uses reviewSeatLineage', () => {
    const cliSrc = fs.readFileSync(path.join(SKILL_DIR, 'bin', 'cli.mjs'), 'utf8');
    const offenders = findApiStyleGeminiIdsInSource(cliSrc);
    assert.deepStrictEqual(
      offenders,
      [],
      `CLI source must not hard-code API-style Gemini product ids; found: ${offenders.join(', ')}`,
    );
    assert.match(cliSrc, /reviewSeatLineage/, 'CLI must use reviewSeatLineage for multi-agree tags');
    assert.match(cliSrc, /from ['"]\.\.\/src\/reviewSeatLabels\.mjs['"]/);
    // Old product-ish lineage form must not remain.
    assert.doesNotMatch(
      cliSrc,
      /lineage:\s*`gemini-\$\{/,
      'must not use bare gemini-${i} lineage (use gemini-cli labels)',
    );
  });
});
