// test/_wave1-trio-resolve.mjs — Wave-1 resolution helper (NOT a test file: test/index.mjs
// auto-discovers only `*.test.mjs`, and this name matches no test pattern).
//
// Resolves (a) the frozen researchPrime gate files and (b) the pinned trio shared-code home,
// the SAME way researchPrime itself does: through researchPrime/bin/contract.mjs's TRIO_ROOT
// pin (env-overridable via RP_TRIO_ROOT). literature-review adds NO second convention of its
// own — one pin, one source of truth. See docs/DECISION-RECEIPT-shared-location.md.
//
// researchPrime itself is located via:
//   1. env RP_ROOT (explicit checkout override), else
//   2. the deployed-skill convention ~/.claude/skills/researchPrime.
// The result is realpath'd BEFORE any import so a deployed symlink (on this host
// ~/.claude/skills/researchPrime -> <path> resolves to the REAL trio
// checkout — otherwise contract.mjs's `new URL('../../', import.meta.url)` default would
// compute TRIO_ROOT against the symlink directory instead of the real trio root.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';

/** The pinned shared-module specifier, relative to TRIO_ROOT (the Wave-1 decision). */
export const SHARED_BROWNFIELD_SPEC = 'trio-shared/brownfield-intake/index.mjs';

/**
 * Resolve the researchPrime root directory (realpath'd; throws with guidance if absent).
 * @returns {string} absolute real path of the researchPrime checkout
 */
export function resolveResearchPrimeRoot() {
  const candidate = process.env.RP_ROOT
    ? path.resolve(process.env.RP_ROOT)
    : path.join(os.homedir(), '.claude', 'skills', 'researchPrime');
  let root = candidate;
  try {
    root = fs.realpathSync(candidate);
  } catch {
    // fall through to the existence check below with the un-realpath'd candidate
  }
  if (!fs.existsSync(path.join(root, 'bin', 'two-gate.mjs'))) {
    throw new Error(
      `researchPrime not found at ${root} — set RP_ROOT to a researchPrime checkout ` +
        '(the Wave-1 gate-contract tests exercise its frozen bin/plan-gate.mjs + bin/two-gate.mjs).',
    );
  }
  return root;
}

/** Absolute path of a file inside the researchPrime checkout. */
export function rpFile(...rel) {
  return path.join(resolveResearchPrimeRoot(), ...rel);
}

/** Import a researchPrime module by repo-relative path (e.g. 'bin/two-gate.mjs'). */
export async function importRp(rel) {
  return import(pathToFileURL(rpFile(rel)).href);
}

/**
 * The trio root as a URL — researchPrime's OWN pin (contract.mjs TRIO_ROOT), honoring
 * RP_TRIO_ROOT. Both parity tests resolve the shared module against THIS value, so the
 * lit-review side and the researchPrime side can never silently diverge.
 * @returns {Promise<URL>}
 */
export async function resolveTrioRootUrl() {
  const contract = await importRp('bin/contract.mjs');
  return contract.TRIO_ROOT;
}

/** URL of the pinned shared brownfield-intake module. */
export async function sharedBrownfieldUrl() {
  return new URL(SHARED_BROWNFIELD_SPEC, await resolveTrioRootUrl());
}

/** sha256 hex digest of a file's bytes (frozen-gate byte-hash assertions). */
export function fileSha256(p) {
  return crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
}
