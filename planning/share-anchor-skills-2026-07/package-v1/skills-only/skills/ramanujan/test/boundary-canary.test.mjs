// Wave 13 — No-inline-reimplementation BOUNDARY CANARY (B3).
//
// Exercises the REAL Wave-13 canary (src/boundary-canary.mjs) against the REAL emitter module and the
// manifest-pinned inherited seam, proving the done-when arm "the boundary canary fails the build on an
// inline reimplementation":
//
//   Given an inline researchPrime/Gandalf reimplementation, when the boundary canary runs, then the
//   build fails — caught BOTH ways: import-graph (no edge to the inherited seam) AND forbidden-symbol
//   (a local definition of a seam-owned function).
//
// Also pins the green spine (the genuine commission-emitters module imports the seam and inline-
// reimplements nothing; no src module inline-reimplements a seam-owned symbol) and the discrimination
// (the plant trips ONLY the planted arms — the genuine/repo-wide assertions stay green).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  BOUNDARY_CANARY_NAMES,
  BOUNDARY_TARGETS,
  INHERITED_SEAM_LOGICAL_NAME,
  FORBIDDEN_INLINE_SYMBOLS,
  PLANTED_INLINE_REIMPL,
  extractStaticImports,
  findInlineDefinitions,
  checkBoundaryModule,
  canaryNoInlineBoundary,
  runNoInlineBoundaryCanary,
  boundaryCanaryExitCode,
} from '../src/boundary-canary.mjs';
import { loadManifest, resolveEntryPath, DEFAULT_MANIFEST_PATH } from '../src/inherits-gate.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = path.join(__dirname, '..', 'src');

function seamAbsPath() {
  const manifest = loadManifest(DEFAULT_MANIFEST_PATH);
  const entry = manifest.entries.find((e) => e.logical_name === INHERITED_SEAM_LOGICAL_NAME);
  return resolveEntryPath(DEFAULT_MANIFEST_PATH, entry);
}

// =====================================================================================
// 0. Names + the static-analysis primitives.
// =====================================================================================

test('BOUNDARY_CANARY_NAMES names the single no-inline-boundary canary', () => {
  assert.deepEqual(BOUNDARY_CANARY_NAMES, ['no-inline-boundary']);
  assert.deepEqual(BOUNDARY_TARGETS, ['commission-emitters.mjs']);
});

test('extractStaticImports finds import / export-from / bare specifiers, and ignores dynamic import()', () => {
  const src = `
    import a from './x.mjs';
    import { b } from "../y.mjs";
    export { c } from './z.mjs';
    import './side-effect.mjs';
    const lazy = await import('./dynamic.mjs');
  `;
  const specs = extractStaticImports(src);
  assert.ok(specs.includes('./x.mjs'));
  assert.ok(specs.includes('../y.mjs'));
  assert.ok(specs.includes('./z.mjs'));
  assert.ok(specs.includes('./side-effect.mjs'));
  assert.ok(!specs.includes('./dynamic.mjs'), 'dynamic import() must NOT count as a static edge');
});

test('findInlineDefinitions flags local DEFINITIONS but never imports / re-exports / property access', () => {
  // local definitions (each a distinct binding form) ARE inline reimplementations.
  assert.deepEqual(findInlineDefinitions('function commissionResearchPrime(){}', ['commissionResearchPrime']), ['commissionResearchPrime']);
  assert.deepEqual(findInlineDefinitions('const composeSituate = () => {}', ['composeSituate']), ['composeSituate']);
  assert.deepEqual(findInlineDefinitions('export async function composeSituate(){}', ['composeSituate']), ['composeSituate']);
  assert.deepEqual(findInlineDefinitions('class abstractEffort {}', ['abstractEffort']), ['abstractEffort']);

  // imports, re-exports, and property access are COMPOSITION, never flagged.
  assert.deepEqual(findInlineDefinitions("import { commissionResearchPrime } from '../seam.mjs';", ['commissionResearchPrime']), []);
  assert.deepEqual(findInlineDefinitions("export { composeSituate } from '../seam.mjs';", ['composeSituate']), []);
  assert.deepEqual(findInlineDefinitions('const e = seam.commissionResearchPrime({});', ['commissionResearchPrime']), []);
  assert.deepEqual(findInlineDefinitions('seam.composeSituate(x);', ['composeSituate']), []);
});

test('FORBIDDEN_INLINE_SYMBOLS covers the seam-owned commission functions', () => {
  for (const s of ['commissionResearchPrime', 'composeSituate', 'independentOriginCredit', 'needsVerificationHandoff']) {
    assert.ok(FORBIDDEN_INLINE_SYMBOLS.includes(s), `missing forbidden symbol ${s}`);
  }
});

// =====================================================================================
// 1. checkBoundaryModule — genuine vs planted.
// =====================================================================================

test('checkBoundaryModule: the genuine commission-emitters module imports the seam and defines no forbidden symbol', () => {
  const modulePath = path.join(SRC_DIR, 'commission-emitters.mjs');
  const source = fs.readFileSync(modulePath, 'utf8');
  const r = checkBoundaryModule({ source, modulePath, seamAbsPath: seamAbsPath() });
  assert.equal(r.importsSeam, true, 'genuine emitter must carry a static edge to the inherited seam');
  assert.deepEqual(r.forbiddenDefs, []);
  assert.equal(r.ok, true);
});

test('checkBoundaryModule: the planted inline reimplementation fails BOTH arms', () => {
  const modulePath = path.join(SRC_DIR, 'contextualize-inline-reimpl.PLANTED.mjs');
  const r = checkBoundaryModule({ source: PLANTED_INLINE_REIMPL, modulePath, seamAbsPath: seamAbsPath() });
  assert.equal(r.importsSeam, false, 'import-graph arm: the plant imports no inherited seam');
  assert.ok(r.forbiddenDefs.includes('commissionResearchPrime'), 'forbidden-symbol arm: the plant defines commissionResearchPrime');
  assert.ok(r.forbiddenDefs.includes('composeSituate'));
  assert.equal(r.ok, false);
});

// =====================================================================================
// 2. THE DONE-WHEN — green on the genuine spine; fails the build (import-graph + forbidden-symbol)
//    on the planted inline reimplementation.
// =====================================================================================

test('the no-inline boundary canary is GREEN on the genuine spine (gated node --test)', () => {
  const result = canaryNoInlineBoundary();
  for (const a of result.assertions) assert.equal(a.ok, true, `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  assert.equal(result.ok, true, `canary tripped: ${result.failures.join(' | ')}`);
});

test('the canary suite runner is green (exit 0) on the clean spine', () => {
  const result = runNoInlineBoundaryCanary();
  assert.equal(result.ok, true, `suite tripped: ${result.failures.join(' | ')}`);
  assert.equal(boundaryCanaryExitCode(result), 0);
});

test('done-when: the canary FAILS THE BUILD on an inline reimplementation — via import-graph AND forbidden-symbol', () => {
  const result = canaryNoInlineBoundary({ plant: 'inline-reimpl' });
  assert.equal(result.ok, false, 'the inline-reimpl plant must trip the canary');

  const tripped = result.assertions.filter((a) => !a.ok);
  // BOTH arms must fire (the GWT: "import-graph + forbidden-symbol").
  assert.ok(tripped.some((a) => /import-graph/.test(a.name)), 'the import-graph arm must trip on the plant');
  assert.ok(tripped.some((a) => /forbidden-symbol/.test(a.name)), 'the forbidden-symbol arm must trip on the plant');

  // the suite runner reports it as a non-zero exit too.
  const suite = runNoInlineBoundaryCanary({ plant: 'inline-reimpl' });
  assert.equal(suite.ok, false);
  assert.equal(boundaryCanaryExitCode(suite), 1);
  assert.ok(suite.failures.some((f) => /no-inline-boundary:/.test(f)));
});

test('the plant trips PRECISELY on the planted arms — the genuine/repo-wide arms stay green', () => {
  const result = canaryNoInlineBoundary({ plant: 'inline-reimpl' });
  for (const a of result.assertions) {
    if (a.name.startsWith('genuine:') || a.name.startsWith('repo-wide:') || a.name.startsWith('manifest')) {
      assert.equal(a.ok, true, `non-planted assertion regressed: ${a.name}`);
    }
  }
  assert.ok(result.assertions.some((a) => a.name.startsWith('planted:') && !a.ok));
});

// =====================================================================================
// 3. Repo-wide forbidden scan is un-exempted (covers the canary's own module).
// =====================================================================================

test('repo-wide: NO src module — including the canary itself — inline-reimplements a seam-owned symbol', () => {
  const result = canaryNoInlineBoundary();
  const repoWide = result.assertions.filter((a) => a.name.startsWith('repo-wide:'));
  assert.ok(repoWide.some((a) => /boundary-canary\.mjs/.test(a.name)), 'the canary module must itself be scanned');
  for (const a of repoWide) assert.equal(a.ok, true, a.name);
});
