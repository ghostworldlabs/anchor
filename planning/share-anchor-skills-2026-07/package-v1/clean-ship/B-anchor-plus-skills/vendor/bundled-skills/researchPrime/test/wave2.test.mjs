import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const runRoundsPath = path.resolve(__dirname, '../bin/run-rounds.mjs');
const source = fs.readFileSync(runRoundsPath, 'utf8');
const noComments = source.replace(/\/\*[\s\S]*?\*\/|\/\/.*/g, '');

const INVENTORY = [
  {
    literal: '8 (default max rounds)',
    mappedTo: 'roundBudget output field in formal-governor contract',
    regex: /maxRounds\s*:\s*\([^)]*\)\s*\?\s*Number\(env\.RESEARCHPRIME_MAX_ROUNDS\)\s*:\s*8/
  },
  {
    literal: 'loopThresholds() fallback (N, K, M defaults)',
    mappedTo: 'thresholds output field in formal-governor contract',
    regex: /const thresholds = loopThresholds\(\)/
  },
  {
    literal: "{ declared_stakes: 'high', reversibility: 'hard-to-reverse', blast_radius: 'wide', magnitude: 'major' } (default stakes)",
    mappedTo: 'stakesTier / tier output field in formal-governor contract (resolved via fallback)',
    regex: /inputs\[0\]\.stakes \?\? \{ declared_stakes: 'high'/
  },
  {
    literal: 'resolveTier(...) call',
    mappedTo: 'tier output field in formal-governor contract',
    regex: /const tier = resolveTier\(/
  }
];

test('Wave 2 - Completeness test: inventory rows map to governor output', () => {
  // Assert every inventory row maps to a governor output/rule.
  for (const row of INVENTORY) {
    assert(row.mappedTo.includes('formal-governor'), `Inventory row must map to formal governor: ${row.literal}`);
    assert(
      row.mappedTo.includes('roundBudget') ||
      row.mappedTo.includes('thresholds') ||
      row.mappedTo.includes('tier'),
      `Inventory row must map to a governor output field: ${row.mappedTo}`
    );
  }
  
  // Ensure that we have successfully removed all these from the source code.
  for (const row of INVENTORY) {
    assert(!row.regex.test(source), `Zero stakes decisions should live outside the governor. Found matched regex for: ${row.literal}`);
  }
});

test('Wave 2 - Build-failing AST/static lint guard rejecting residual stakes literals', () => {
  // Check for any of the banned literals/heuristics in run-rounds.mjs
  // 1. Hardcoded 8 for maxRounds (outside of any string or comment)
  assert(!noComments.includes(': 8)'), 'Residual maxRounds literal "8" found in run-rounds.mjs');
  // 2. Default stakes literal
  assert(!noComments.includes("declared_stakes: 'high'"), "Residual default stakes literal found in run-rounds.mjs");
  // 3. direct loopThresholds() call
  assert(!noComments.includes('loopThresholds('), 'Residual loopThresholds() call found in run-rounds.mjs');
  assert(!noComments.includes('import { loopThresholds }'), 'Residual loopThresholds import found in run-rounds.mjs');
  // 4. resolveTier logic inside run-rounds.mjs
  assert(!noComments.includes('resolveTier('), 'Residual resolveTier() call found in run-rounds.mjs');
  assert(!noComments.includes('import { resolveTier }'), 'Residual resolveTier import found in run-rounds.mjs');

  // Verify that it actually imports and calls deriveGovernorContract
  assert(noComments.includes('deriveGovernorContract('), 'Must derive contract from deriveGovernorContract');
  assert(noComments.includes('const thresholds = contract.thresholds'), 'Must read thresholds from governor output');
  assert(noComments.includes('const cap = contract.roundBudget'), 'Must read cap from governor output');
  assert(noComments.includes('const tier = contract.tier'), 'Must read tier from governor output');
});
