// Wave 12 — Coverage-stamp canary (B2b — A2 coverage-stamp).
//
// Exercises the REAL Wave-12 source (src/coverage-stamp-canary.mjs) against the REAL shared spine —
// the Wave-11 firewall builder, the Wave-3 A1 ledger, the Wave-9 out-of-model firewall subprocess,
// and the Wave-4 adjudication substrate over the REAL inherited durability substrate — proving the
// done-when:
//
//   the coverage-stamp canary FAILS THE BUILD on an over-trusted reduced-warranty pass.
//   (Given a firewall with warranty_excludes[] non-empty, when the coverage-stamp canary runs, then
//    a VERIFIED rung is refused — capped at CLAIMED.)
//
// Also pins the predicate_domain ⊇ claim_domain re-derivation from the execution trace, the
// CLAIMED ceiling on warranty_excludes[] != ∅ / anchor_coverage < full, and the non-vacuity of the
// green path (a fully-covered firewall legitimately settles OBSERVED).

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  coverageStamp,
  canaryCoverageStamp,
  runCoverageStampCanary,
  coverageCanaryExitCode,
  COVERAGE_CANARY_NAMES,
} from '../src/coverage-stamp-canary.mjs';

import {
  buildFirewall,
  applyFirewallCap,
  ANCHOR_NAMES,
  ANCHOR_COVERAGE,
  GENUINE_NARRATIVE,
  REDUCED_WARRANTY_NARRATIVE,
  NO_ANCHORS_NARRATIVE,
} from '../src/firewall-builder.mjs';
import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import {
  loadDurabilitySubstrate,
  DurableNonceStore,
  AdjudicationDispatcher,
} from '../src/adjudication.mjs';
import { FIREWALL_FAMILY } from '../src/firewall-subprocess.mjs';

// The REAL inherited durability substrate (matches the Wave-4/6/9/10/11 setup) — needed for the
// OBSERVED settlement path (the firewall positive path mints + adjudicates a real artifact).
const substrate = await loadDurabilitySubstrate();

let fileSeq = 0;
const scratchDirs = [];
function tmpFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w12t-'));
  scratchDirs.push(dir);
  return path.join(dir, `nonce-store-${fileSeq++}.checkpoint.json`);
}
function freshDispatcher() {
  return new AdjudicationDispatcher({ store: DurableNonceStore.load(substrate, tmpFile()), family: FIREWALL_FAMILY });
}
after(() => {
  for (const d of scratchDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best-effort cleanup */ }
  }
});

// =====================================================================================
// 0. Shape — the coverage stamp, re-derived from the execution trace.
// =====================================================================================

test('COVERAGE_CANARY_NAMES names the single A2 coverage-stamp canary', () => {
  assert.deepEqual(COVERAGE_CANARY_NAMES, ['coverage-stamp']);
});

test('coverageStamp on a GENUINE firewall: predicate_domain ⊇ claim_domain => full coverage, OBSERVED ceiling', () => {
  const build = buildFirewall(GENUINE_NARRATIVE);
  const stamp = coverageStamp(build);
  // claim_domain is the full reading-independent battery; predicate_domain covers it entirely.
  assert.deepEqual(stamp.claim_domain.slice().sort(), ANCHOR_NAMES.slice().sort());
  assert.deepEqual(stamp.predicate_domain.slice().sort(), ANCHOR_NAMES.slice().sort());
  assert.equal(stamp.covered, true);
  assert.deepEqual(stamp.warranty_excludes, []);
  assert.equal(stamp.anchor_coverage, ANCHOR_COVERAGE.FULL);
  assert.equal(stamp.rung_ceiling, RUNG.OBSERVED);
  // the re-derivation agrees with the build's OWN honest stamps (no silent divergence).
  assert.equal(stamp.anchor_coverage, build.anchor_coverage);
  assert.deepEqual(stamp.warranty_excludes, build.warranty_excludes);
});

test('coverageStamp on a REDUCED-WARRANTY firewall: predicate_domain does NOT ⊇ claim_domain => CLAIMED ceiling', () => {
  const build = buildFirewall(REDUCED_WARRANTY_NARRATIVE);
  const stamp = coverageStamp(build);
  assert.equal(stamp.covered, false);
  assert.deepEqual(stamp.warranty_excludes, ['closed-form']); // the unavailable anchor
  assert.ok(stamp.predicate_domain.length < stamp.claim_domain.length);
  assert.equal(stamp.anchor_coverage, ANCHOR_COVERAGE.PARTIAL);
  assert.equal(stamp.rung_ceiling, RUNG.CLAIMED);
  assert.notEqual(stamp.rung_ceiling, RUNG.OBSERVED);
  // mirrors the Wave-11 build stamp exactly (re-derived independently from the trace).
  assert.equal(stamp.anchor_coverage, build.anchor_coverage);
  assert.deepEqual(stamp.warranty_excludes, build.warranty_excludes);
});

test('coverageStamp on a NO-ANCHORS firewall: empty predicate_domain => NONE coverage, CLAIMED ceiling', () => {
  const build = buildFirewall(NO_ANCHORS_NARRATIVE);
  const stamp = coverageStamp(build);
  assert.deepEqual(stamp.predicate_domain, []);
  assert.equal(stamp.anchor_coverage, ANCHOR_COVERAGE.NONE);
  assert.equal(stamp.covered, false);
  assert.equal(stamp.rung_ceiling, RUNG.CLAIMED);
  assert.deepEqual(stamp.warranty_excludes.slice().sort(), ANCHOR_NAMES.slice().sort());
});

test('coverageStamp validates its input', () => {
  assert.throws(() => coverageStamp(null), /a firewall build is required/);
});

// =====================================================================================
// 1. The GWT — a reduced-warranty firewall refuses a VERIFIED rung (capped at CLAIMED), through the
//    REAL applyFirewallCap with a LIVE dispatcher (so it is not merely a no-minter arm holding it).
// =====================================================================================

test('GWT: a firewall with warranty_excludes[] non-empty is refused a VERIFIED rung (capped at CLAIMED)', () => {
  const build = buildFirewall(REDUCED_WARRANTY_NARRATIVE);
  const stamp = coverageStamp(build);
  assert.ok(stamp.warranty_excludes.length > 0);

  const ledger = new ClaimLedger();
  const verdict = applyFirewallCap(build, ledger, { dispatcher: freshDispatcher() });
  assert.equal(verdict.rung, RUNG.CLAIMED);
  assert.notEqual(verdict.rung, RUNG.OBSERVED);
  assert.notEqual(verdict.belief, BELIEF.VERIFIED);
  assert.equal(ledger.beliefOf(build.claim_id), BELIEF.CONJECTURAL);
});

// =====================================================================================
// 2. THE DONE-WHEN — the canary is GREEN on the genuine spine, and FAILS THE BUILD on the planted
//    over-trusted reduced-warranty pass.
// =====================================================================================

test('the A2 coverage-stamp canary is GREEN on the genuine spine (gated node --test)', async () => {
  const result = await canaryCoverageStamp();
  for (const a of result.assertions) assert.equal(a.ok, true, `${a.name}${a.detail ? `: ${a.detail}` : ''}`);
  assert.equal(result.ok, true, `canary tripped: ${result.failures.join(' | ')}`);
});

test('the canary suite runner is green (exit 0) on the clean spine', async () => {
  const result = await runCoverageStampCanary();
  assert.equal(result.ok, true, `suite tripped: ${result.failures.join(' | ')}`);
  assert.equal(coverageCanaryExitCode(result), 0);
});

test('done-when: the canary FAILS THE BUILD on an over-trusted reduced-warranty pass', async () => {
  const result = await canaryCoverageStamp({ plant: 'over-trust' });
  assert.equal(result.ok, false, 'the over-trust plant must trip the canary');
  // the specific load-bearing assertion is the one that trips (the rung overshot its coverage ceiling).
  const tripped = result.assertions.find((a) => !a.ok);
  assert.ok(tripped, 'expected a tripped assertion');
  assert.match(tripped.name, /never exceeds the coverage ceiling|over-trusted reduced-warranty pass/);
  // the suite runner reports it as a non-zero exit too.
  const suite = await runCoverageStampCanary({ plant: 'over-trust' });
  assert.equal(suite.ok, false);
  assert.equal(coverageCanaryExitCode(suite), 1);
  assert.ok(suite.failures.some((f) => /coverage-stamp:/.test(f)));
});

test('the over-trust plant trips PRECISELY on the reduced-warranty arm — the genuine arm stays green', async () => {
  // Every tripped assertion must be a "reduced:" assertion; the "genuine:" assertions still pass, so
  // the canary is discriminating (it is the reduced-warranty over-trust, not a blanket failure).
  const result = await canaryCoverageStamp({ plant: 'over-trust' });
  for (const a of result.assertions) {
    if (a.name.startsWith('genuine:')) assert.equal(a.ok, true, `genuine arm regressed: ${a.name}`);
  }
  assert.ok(result.assertions.some((a) => a.name.startsWith('reduced:') && !a.ok));
});
