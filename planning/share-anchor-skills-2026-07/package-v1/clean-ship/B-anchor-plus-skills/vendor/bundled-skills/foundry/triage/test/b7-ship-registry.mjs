// Track B7 W4 — fail-if-missing ship-gate cell registry (B7-C1..C4).
//
// Sole SC5 close predicate: every REQUIRED cell id appears as a registered
// node:test name under the ship-gate suite files. Missing name → fail closed
// (never soft-skip under --test-name-pattern=B7-C).

import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
export const TRIAGE_PKG_ROOT = join(__dirname, '..');
export const FOUNDRY_ROOT = join(TRIAGE_PKG_ROOT, '..', '..');
export const LIT_REVIEW_ROOT = join(FOUNDRY_ROOT, 'skills', 'literature-review');

/**
 * Canonical ship-gate cell ids (MASTER-PLAN Contract 5 / IMPLEMENTATION-PLAN W4).
 * @type {ReadonlyArray<string>}
 */
export const REQUIRED_B7_CELL_IDS = Object.freeze([
  'B7-C1-control-plane',
  'B7-C2-lean',
  'B7-C3-floor',
  'B7-C4-compose',
]);

/**
 * Suite files that must carry B7-C* tests for the sole Foreman ship-gate command:
 *   node --test --test-name-pattern=B7-C foundry/triage/test/b7-literature-review.test.mjs
 *     skills/literature-review/test/b7-*.test.mjs
 * @type {ReadonlyArray<string>}
 */
export const B7_SHIP_GATE_TEST_FILES = Object.freeze([
  join(TRIAGE_PKG_ROOT, 'test', 'b7-literature-review.test.mjs'),
  join(LIT_REVIEW_ROOT, 'test', 'b7-c2-lean.test.mjs'),
  join(LIT_REVIEW_ROOT, 'test', 'b7-c3-floor.test.mjs'),
  join(LIT_REVIEW_ROOT, 'test', 'b7-c4-compose.test.mjs'),
]);

/**
 * Extract node:test names from suite source (test('name' / test("name")).
 * @param {string} source
 * @returns {string[]}
 */
export function extractTestNames(source) {
  const names = [];
  const re = /\btest\s*\(\s*(['"`])([^'"`]+)\1/g;
  let m;
  while ((m = re.exec(source)) !== null) {
    names.push(m[2]);
  }
  return names;
}

/**
 * Fail-closed: every REQUIRED_B7_CELL_IDS entry must appear as a test-name
 * prefix in the ship-gate suite sources. Missing cell → throw B7_CELL_MISSING.
 * @returns {{ ok: true, ids: string[], files: string[], coverage: Record<string, string[]> }}
 */
export function assertB7CellRegistryPresent() {
  assert.equal(
    REQUIRED_B7_CELL_IDS.length,
    4,
    'ship gate requires exactly four B7-C cells',
  );

  /** @type {string[]} */
  const missingFiles = [];
  /** @type {string[]} */
  const allNames = [];
  /** @type {Record<string, string[]>} */
  const coverage = {};

  for (const file of B7_SHIP_GATE_TEST_FILES) {
    if (!existsSync(file)) {
      missingFiles.push(file);
      continue;
    }
    const text = readFileSync(file, 'utf8');
    const names = extractTestNames(text);
    allNames.push(...names);
  }

  assert.equal(
    missingFiles.length,
    0,
    `B7 ship-gate suite file(s) missing (fail-closed):\n${missingFiles.join('\n')}`,
  );

  /** @type {string[]} */
  const missingCells = [];
  for (const id of REQUIRED_B7_CELL_IDS) {
    const hits = allNames.filter(
      (n) => n === id || n.startsWith(`${id}:`) || n.startsWith(`${id} `),
    );
    coverage[id] = hits;
    if (hits.length === 0) {
      missingCells.push(id);
    }
  }

  if (missingCells.length > 0) {
    const err = new Error(
      `B7 cell registry fail-closed: missing registered cell name(s): ${missingCells.join(', ')}`,
    );
    /** @type {any} */ (err).code = 'B7_CELL_MISSING';
    /** @type {any} */ (err).missing = missingCells;
    throw err;
  }

  return {
    ok: true,
    ids: [...REQUIRED_B7_CELL_IDS],
    files: [...B7_SHIP_GATE_TEST_FILES],
    coverage,
  };
}

/**
 * Run one named cell presence check. Missing id fails closed.
 * @param {string} cellId
 * @returns {{ ok: true, cell: string, hits: string[] }}
 */
export function assertB7CellPresent(cellId) {
  const reg = assertB7CellRegistryPresent();
  if (!REQUIRED_B7_CELL_IDS.includes(cellId)) {
    const err = new Error(
      `B7 cell registry fail-closed: unknown cell ${cellId}`,
    );
    /** @type {any} */ (err).code = 'B7_CELL_MISSING';
    /** @type {any} */ (err).cellId = cellId;
    throw err;
  }
  const hits = reg.coverage[cellId] || [];
  assert.ok(hits.length >= 1, `${cellId} must have ≥1 registered test name`);
  return { ok: true, cell: cellId, hits };
}
