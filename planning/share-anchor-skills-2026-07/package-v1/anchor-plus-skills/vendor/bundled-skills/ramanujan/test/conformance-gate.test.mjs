// Wave 5 — Inheritance CONFORMANCE gate (A0.5b) tests.
//
// Exercises the REAL Wave-5 source (src/conformance-gate.mjs) against the REAL inherited seams
// (resolved through inherits.manifest.json) and the REAL A1 ledger + A1.5 adjudication
// substrate, proving the done-when:
//   1. each inherited seam passes its conformance fixture (the shipped manifest is GREEN);
//   2. a PLANTED non-conforming seam — one that would PASS Wave-2's interface/shape gate but
//      VIOLATES the A1/A3 contract behaviourally — fails the gate NON-ZERO, NAMING the seam;
//   3. the gate is the Phase-B entry gate (exit code maps green->0 / any non-conformance->1).
//
// The explicit Given/When/Then from the plan is the last test block.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  runConformanceGate,
  resolveSeam,
  verdictExitCode,
  CONFORMANCE_FIXTURES,
} from '../src/conformance-gate.mjs';
import { loadManifest, DEFAULT_MANIFEST_PATH } from '../src/inherits-gate.mjs';

// =====================================================================================
// 1. GREEN: every shipped inherited seam conforms.
// =====================================================================================

test('the shipped inherited seams all conform to the A1/A3 contract (GREEN, exit 0)', async () => {
  const result = await runConformanceGate();
  assert.equal(result.ok, true, `expected GREEN; failures:\n${result.failures.join('\n')}`);
  assert.equal(result.failures.length, 0);
  assert.equal(verdictExitCode(result), 0);

  // every manifest seam was exercised and conformed, with real pinned assertions (not vacuous).
  assert.ok(result.seams.length >= 8, 'all manifest seams exercised');
  for (const s of result.seams) {
    assert.equal(s.ok, true, `seam ${s.logical_name} did not conform: ${s.failures.join('; ')}`);
    assert.ok(s.assertions.length > 0, `seam ${s.logical_name} ran at least one pinned assertion`);
    assert.ok(s.assertions.every((a) => a.ok), `seam ${s.logical_name} has a failed assertion`);
  }
});

test('every manifest entry has a registered conformance fixture (no seam silently un-exercised)', () => {
  const manifest = loadManifest();
  for (const entry of manifest.entries) {
    assert.equal(
      typeof CONFORMANCE_FIXTURES[entry.logical_name],
      'function',
      `no conformance fixture registered for inherited seam "${entry.logical_name}"`,
    );
  }
});

// =====================================================================================
// 2. PLANTED non-conforming seams — each fails NON-ZERO, naming the seam.
//
// The plants pass Wave-2's interface/shape check (right export names + types / right JSON keys)
// but VIOLATE the behavioural contract — exactly what an interface gate is blind to and a
// conformance gate must catch.
// =====================================================================================

// A gandalf seam that self-CORROBORATES (violates the single-family honesty cap: a same-family
// SITUATE finding must cap at CLAIMED, never self-promote to CORROBORATED).
function plantedSelfCorroboratingGandalf(real) {
  return {
    ...real,
    SITUATE_SELF_MAX_RUNG: 'CORROBORATED', // the violation
    composeSituate(cfg) {
      const finding = real.composeSituate(cfg);
      return { ...finding, rung: 'CORROBORATED' }; // launders a same-family finding past the cap
    },
  };
}

test('PLANTED: a self-CORROBORATING gandalf seam fails the gate NON-ZERO, naming the seam', async () => {
  const real = await resolveSeam(DEFAULT_MANIFEST_PATH, { kind: 'module', path: gandalfRelPath() });
  const result = await runConformanceGate(DEFAULT_MANIFEST_PATH, {
    overrides: { 'gandalf-commission-seam': plantedSelfCorroboratingGandalf(real) },
  });
  assert.equal(result.ok, false);
  assert.equal(verdictExitCode(result), 1);
  assert.ok(
    result.failures.some((f) => f.startsWith('gandalf-commission-seam:') && /CLAIMED|CORROBORATED|self-CORROBORATED/.test(f)),
    `failures must name the gandalf seam + the honesty-cap violation; got:\n${result.failures.join('\n')}`,
  );
  // the conforming seams are NOT dragged down — only the planted seam is reported failing.
  const gandalf = result.seams.find((s) => s.logical_name === 'gandalf-commission-seam');
  assert.equal(gandalf.ok, false);
  assert.ok(result.seams.filter((s) => s.logical_name !== 'gandalf-commission-seam').every((s) => s.ok));
});

// A "durability" substrate with the right export SHAPE (all functions present) but a no-op
// writer — it does NOT actually persist, so nothing survives a restart.
function plantedNonDurableSubstrate(real) {
  return {
    ...real,
    newCheckpoint: real.newCheckpoint,
    validateCheckpoint: real.validateCheckpoint,
    readCheckpoint: real.readCheckpoint,
    writeCheckpointAtomic() { /* no-op: silently drops the write (never persists) */ },
  };
}

test('PLANTED: a non-durable "durability" substrate fails the gate NON-ZERO, naming the seam', async () => {
  const real = await resolveSeam(DEFAULT_MANIFEST_PATH, { kind: 'module', path: durabilityRelPath() });
  const result = await runConformanceGate(DEFAULT_MANIFEST_PATH, {
    overrides: { 'phase0-durability': plantedNonDurableSubstrate(real) },
  });
  assert.equal(result.ok, false);
  assert.equal(verdictExitCode(result), 1);
  assert.ok(
    result.failures.some((f) => f.startsWith('phase0-durability:') && /survive|durab|restart|counter/i.test(f)),
    `failures must name the durability seam + the non-persistence; got:\n${result.failures.join('\n')}`,
  );
});

// A dive deliverable that never converged (the A3 router only composes a converged deliverable).
test('PLANTED: a non-converged dive deliverable fails the gate NON-ZERO, naming the seam', async () => {
  const real = await resolveSeam(DEFAULT_MANIFEST_PATH, { kind: 'json', path: dive1RelPath() });
  const nonConverged = { ...real, convergence: { ...real.convergence, converged: false } };
  const result = await runConformanceGate(DEFAULT_MANIFEST_PATH, {
    overrides: { 'dive-1-understand-firewall': nonConverged },
  });
  assert.equal(result.ok, false);
  assert.equal(verdictExitCode(result), 1);
  assert.ok(
    result.failures.some((f) => f.startsWith('dive-1-understand-firewall:') && /converg/i.test(f)),
    `failures must name the dive seam + the convergence violation; got:\n${result.failures.join('\n')}`,
  );
});

// =====================================================================================
// 3. The explicit Given/When/Then.
// =====================================================================================

test('GWT: Given an inherited seam violating the A1/A3 contract, When the conformance gate runs, Then it fails non-zero naming the seam', async () => {
  // Given: an inherited gandalf seam that violates the A3/honesty contract (self-CORROBORATES).
  const real = await resolveSeam(DEFAULT_MANIFEST_PATH, { kind: 'module', path: gandalfRelPath() });
  const violating = plantedSelfCorroboratingGandalf(real);

  // When: the conformance gate runs.
  const result = await runConformanceGate(DEFAULT_MANIFEST_PATH, {
    overrides: { 'gandalf-commission-seam': violating },
  });

  // Then: it fails non-zero, naming the offending seam.
  assert.equal(result.ok, false);
  assert.equal(verdictExitCode(result), 1, 'a non-conforming seam must produce a non-zero exit (gates Phase B+)');
  assert.ok(
    result.failures.some((f) => f.startsWith('gandalf-commission-seam:')),
    `the failure must name the offending seam; got:\n${result.failures.join('\n')}`,
  );
});

// --- path helpers: the manifest's relative paths for the seams the planted tests resolve. ----
function manifestEntryPath(logical_name) {
  const entry = loadManifest().entries.find((e) => e.logical_name === logical_name);
  assert.ok(entry, `manifest must pin "${logical_name}"`);
  return entry.path;
}
function gandalfRelPath() { return manifestEntryPath('gandalf-commission-seam'); }
function durabilityRelPath() { return manifestEntryPath('phase0-durability'); }
function dive1RelPath() { return manifestEntryPath('dive-1-understand-firewall'); }
