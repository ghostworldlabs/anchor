// Wave 2 — inheritance presence/interface gate tests (A0.5a).
//
// Exercises the real Wave-2 source (src/inherits-gate.mjs) against the real
// inherits.manifest.json and the REAL inherited modules, proving the done-when:
//   1. the gate passes GREEN (every entry resolves + version-checks + interface-shape-checks)
//      and round-trips a counter/spent-nonce through the inherited durability substrate;
//   2. it FAILS FAST (non-zero), naming the offending entry, on any unresolvable path /
//      version mismatch / interface (export-shape, missing-key) mismatch;
//   3. the durability round-trip survives a SIMULATED RELOAD from disk (not an in-memory
//      stub): the value is gone if you read a fresh location, and present if you reload the
//      persisted one.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  runGate,
  loadManifest,
  checkEntry,
  resolveEntryPath,
  findPackageVersion,
  roundTripDurability,
  verdictExitCode,
  DEFAULT_MANIFEST_PATH,
  DURABILITY_ROLE,
} from '../src/inherits-gate.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, '..');

// Write a synthetic manifest to a scratch file and return its path (auto-cleaned by tmpdir).
function writeSyntheticManifest(name, manifestObj) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w2-syn-'));
  const p = path.join(dir, name);
  fs.writeFileSync(p, JSON.stringify(manifestObj, null, 2));
  return p;
}

// A baseline real-resolving entry (the durability substrate) we can clone + corrupt per test.
// Paths are relative to the REPO ROOT, so a synthetic manifest must live where `../trio/...`
// still resolves the same way. We instead point synthetic manifests' relative paths at the
// REPO ROOT by giving them absolute paths computed here — simplest + robust on win32.
const ABS = (rel) => path.resolve(REPO_ROOT, rel);
const realDurabilityEntry = () => ({
  logical_name: 'phase0-durability',
  role: DURABILITY_ROLE,
  kind: 'module',
  path: ABS('../../../trio/foreman/bin/foreman-lib.mjs'),
  version: { from: 'packageJson', expected: '0.0.0' },
  exports: [
    { name: 'newCheckpoint', type: 'function' },
    { name: 'writeCheckpointAtomic', type: 'function' },
    { name: 'readCheckpoint', type: 'function' },
  ],
});

// =====================================================================================
// 1. GREEN: the shipped manifest passes end-to-end.
// =====================================================================================

test('the shipped inherits.manifest.json passes the gate GREEN (resolve+version+shape+durability)', async () => {
  const result = await runGate();
  assert.equal(result.ok, true, `expected GREEN; failures:\n${result.failures.join('\n')}`);
  assert.equal(result.failures.length, 0);
  assert.equal(verdictExitCode(result), 0);
  // durability round-trip ran and survived two simulated restarts
  assert.ok(result.durability, 'durability result present');
  assert.equal(result.durability.ok, true);
  assert.equal(result.durability.intact, true);
  assert.equal(result.durability.monotone, true);
});

test('the shipped manifest names all SEVEN+ inherited seams, incl. a durability-substrate', () => {
  const manifest = loadManifest();
  const names = manifest.entries.map((e) => e.logical_name);
  // Phase-0 handoff/journal/sleep + durability + Gandalf seam + dive-1/2/3
  for (const required of [
    'phase0-handoff',
    'phase0-journal',
    'phase0-sleep',
    'gandalf-commission-seam',
    'dive-1-understand-firewall',
    'dive-2-solve-verify',
    'dive-3-interactive-partner',
  ]) {
    assert.ok(names.includes(required), `manifest must pin "${required}"`);
  }
  const durEntries = manifest.entries.filter((e) => e.role === DURABILITY_ROLE);
  assert.equal(durEntries.length, 1, 'exactly one durability-substrate entry');
});

test('every shipped manifest entry individually resolves + version + interface-shape checks', async () => {
  const manifest = loadManifest();
  for (const entry of manifest.entries) {
    const r = await checkEntry(DEFAULT_MANIFEST_PATH, entry);
    assert.equal(r.ok, true, `entry ${entry.logical_name} failed: ${r.failures.join('; ')}`);
    assert.ok(fs.existsSync(r.resolvedPath), `resolved path exists for ${entry.logical_name}`);
  }
});

// =====================================================================================
// 2. FAIL-FAST arms — each names the offending entry.
// =====================================================================================

test('an UNRESOLVABLE path fails fast, naming the offending entry', async () => {
  const bad = realDurabilityEntry();
  bad.logical_name = 'phantom-seam';
  bad.path = ABS('../trio/foreman/bin/__does_not_exist__.mjs');
  const mPath = writeSyntheticManifest('inherits.manifest.json', { manifest_version: 1, entries: [bad] });
  const result = await runGate(mPath);
  assert.equal(result.ok, false);
  assert.equal(verdictExitCode(result), 1);
  assert.ok(
    result.failures.some((f) => f.startsWith('phantom-seam:') && /unresolvable path/.test(f)),
    `failures should name the unresolvable entry; got:\n${result.failures.join('\n')}`,
  );
});

test('a CHANGED export shape (missing export) fails fast, naming the entry + missing export', async () => {
  const bad = realDurabilityEntry();
  bad.exports = [{ name: 'thisExportDoesNotExist', type: 'function' }];
  const mPath = writeSyntheticManifest('inherits.manifest.json', { manifest_version: 1, entries: [bad] });
  const result = await runGate(mPath);
  assert.equal(result.ok, false);
  assert.ok(
    result.failures.some((f) => /phase0-durability:.*missing export: thisExportDoesNotExist/.test(f)),
    `failures should name the missing export; got:\n${result.failures.join('\n')}`,
  );
});

test('a WRONG export TYPE (shape mismatch) fails fast, naming the entry', async () => {
  const bad = realDurabilityEntry();
  // newCheckpoint is a function; assert it is a string -> shape mismatch
  bad.exports = [{ name: 'newCheckpoint', type: 'string' }];
  const mPath = writeSyntheticManifest('inherits.manifest.json', { manifest_version: 1, entries: [bad] });
  const result = await runGate(mPath);
  assert.equal(result.ok, false);
  assert.ok(
    result.failures.some((f) => /phase0-durability:.*newCheckpoint has wrong shape.*expected string.*got function/.test(f)),
    `failures should name the shape mismatch; got:\n${result.failures.join('\n')}`,
  );
});

test('a VERSION mismatch fails fast, naming the entry', async () => {
  const bad = realDurabilityEntry();
  bad.version = { from: 'packageJson', expected: '9.9.9' };
  const mPath = writeSyntheticManifest('inherits.manifest.json', { manifest_version: 1, entries: [bad] });
  const result = await runGate(mPath);
  assert.equal(result.ok, false);
  assert.ok(
    result.failures.some((f) => /phase0-durability:.*version mismatch: expected 9\.9\.9/.test(f)),
    `failures should name the version mismatch; got:\n${result.failures.join('\n')}`,
  );
});

test('a JSON dive-engine with a MISSING required key fails fast, naming the entry + key', async () => {
  const badJson = {
    logical_name: 'dive-broken',
    kind: 'json',
    path: ABS('planning/research/run/DELIVERABLE-ENGINE.json'),
    version: { from: 'none' },
    keys: [{ name: 'this_key_is_not_in_the_artifact' }],
  };
  // include a real durability entry too so the round-trip still runs (and this fails on the key only)
  const mPath = writeSyntheticManifest('inherits.manifest.json', {
    manifest_version: 1,
    entries: [realDurabilityEntry(), badJson],
  });
  const result = await runGate(mPath);
  assert.equal(result.ok, false);
  assert.ok(
    result.failures.some((f) => /dive-broken:.*missing key: this_key_is_not_in_the_artifact/.test(f)),
    `failures should name the missing JSON key; got:\n${result.failures.join('\n')}`,
  );
});

test('a manifest with NO durability-substrate entry fails (the round-trip cannot be proven)', async () => {
  const onlyJson = {
    logical_name: 'dive-3-interactive-partner',
    kind: 'json',
    path: ABS('planning/research-partner-layer/run/DELIVERABLE-ENGINE.json'),
    version: { from: 'none' },
    keys: [{ name: 'deliverable' }],
  };
  const mPath = writeSyntheticManifest('inherits.manifest.json', { manifest_version: 1, entries: [onlyJson] });
  const result = await runGate(mPath);
  assert.equal(result.ok, false);
  assert.ok(
    result.failures.some((f) => new RegExp(`no entry marked role="${DURABILITY_ROLE}"`).test(f)),
    `failures should flag the missing durability substrate; got:\n${result.failures.join('\n')}`,
  );
});

// =====================================================================================
// 3. Durability round-trip — Given/When/Then (the across-restart proof).
// =====================================================================================

test('Given the inherited durability substrate, When a counter/spent-nonce is written and reloaded across a simulated restart, Then it round-trips intact (and is monotone)', async () => {
  const manifest = loadManifest();
  const durEntry = manifest.entries.find((e) => e.role === DURABILITY_ROLE);
  const checked = await checkEntry(DEFAULT_MANIFEST_PATH, durEntry);
  assert.equal(checked.ok, true, `durability entry must resolve: ${checked.failures.join('; ')}`);
  const substrate = checked.exports;

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w2-rt-'));
  try {
    const rt = roundTripDurability(substrate, dir);
    assert.equal(rt.ok, true, 'round-trip ok');
    assert.equal(rt.intact, true, 'first reload preserved the written counter+spent');
    assert.equal(rt.monotone, true, 'second reload preserved the monotone bump');
    assert.equal(rt.reloaded_counter, 42);
    assert.equal(rt.reloaded_spent.length, 2);

    // It is genuinely DISK-backed, not an in-memory stub: the persisted file exists on
    // disk and a fresh read of it (no carried state) returns the value...
    assert.ok(fs.existsSync(rt.file), 'the substrate wrote a real file to disk');
    const reread = substrate.readCheckpoint(rt.file);
    assert.equal(reread.nonce_state.counter, 42, 'a brand-new read from disk sees the persisted counter');

    // ...whereas a DIFFERENT (never-written) location has no such value — proving the
    // value comes from persistence, not a constant / in-memory singleton.
    assert.throws(
      () => substrate.readCheckpoint(path.join(dir, 'never-written.json')),
      'reading an unwritten location must not yield a phantom value',
    );
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// =====================================================================================
// Helper-unit coverage (resolution + version walk).
// =====================================================================================

test('resolveEntryPath resolves entry paths relative to the manifest file', () => {
  const abs = resolveEntryPath(DEFAULT_MANIFEST_PATH, { path: '../../../trio/foreman/bin/foreman-lib.mjs' });
  assert.ok(path.isAbsolute(abs));
  assert.ok(abs.endsWith(path.join('trio', 'foreman', 'bin', 'foreman-lib.mjs')));
});

test('findPackageVersion walks up to the nearest package.json version', () => {
  const foremanLib = resolveEntryPath(DEFAULT_MANIFEST_PATH, { path: '../../../trio/foreman/bin/foreman-lib.mjs' });
  const v = findPackageVersion(path.dirname(foremanLib));
  assert.equal(typeof v, 'string', 'a version string is found for the inherited durability substrate');
});
