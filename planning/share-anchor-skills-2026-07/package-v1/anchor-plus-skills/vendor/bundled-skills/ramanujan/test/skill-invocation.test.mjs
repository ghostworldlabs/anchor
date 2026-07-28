// Wave 27 — invocation smoke test + 5-gate productionization checklist (E3) — project-DONE.
//
// Exercises the REAL Wave-27 source (src/skill-invocation.mjs), which drives the REAL autonomous
// orchestrator + the REAL VERIFY router — no stubs. Proves the Wave-27 done-when:
//   "an invocation smoke test (a canned input) produces a correctly-stamped abstain/route through
//    the REAL router; the SKILL.md states the Increment-1 acceptance boundary; the 5-gate
//    productionization checklist + manifest checker pass."
// and the Given/When/Then:
//   "Given a canned proof-bearing input, when the skill is invoked end-to-end, then it returns a
//    CONJECTURAL+routed result with an honest per-claim rung+verifier-family stamp + advisory
//    payload, and the SKILL.md headline declares NS3-lift/NS4/NS7 as Increment-2."

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  invokeSkill,
  runProductionizationChecklist,
  CANNED_PROOF_INPUT,
} from '../src/skill-invocation.mjs';
import { ROUTE_VERDICT } from '../src/verify-router.mjs';
import { BELIEF, RUNG } from '../src/claim-ledger.mjs';
import { DISPATCH_DISPOSITION } from '../src/orchestrator.mjs';
import { checkManifest, DEFAULT_SKILL_PATH } from '../src/manifest-checker.mjs';

// --- THE SMOKE TEST (Given/When/Then): the canned proof input, end-to-end through the REAL router ---

test('GWT: the canned proof-bearing input ABSTAINs to CONJECTURAL + routes + advisory + honest stamp', () => {
  const summary = invokeSkill();

  // It went through the orchestrator's VERIFY DISPATCH (a real end-to-end run, not an ASK).
  assert.equal(summary.handled.disposition, DISPATCH_DISPOSITION.DISPATCH);
  assert.equal(summary.handled.output.kind, 'route');
  assert.equal(summary.results.length, 1);

  const r = summary.results[0];
  assert.equal(r.claim_type, 'proof-bearing');
  // ABSTAIN + routed — never a settled verdict.
  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.routed, true);
  assert.equal(r.settled, false);
  // CONJECTURAL belief at the UNVERIFIED floor (the honest rung).
  assert.equal(r.belief, BELIEF.CONJECTURAL);
  assert.equal(r.rung, RUNG.UNVERIFIED);

  // An honest per-claim stamp (NS5): NO verifier-family is claimed without an artifact.
  assert.equal(r.stamp.verifier_family, null);
  assert.equal(r.stamp.artifact_backed, false);
  assert.equal(r.stamp.rung, RUNG.UNVERIFIED);

  // An advisory payload that routes out-of-model + carries an emit-not-dispatch commission.
  assert.notEqual(r.advisory, null);
  assert.equal(r.advisory.route, 'out-of-model');
  assert.equal(r.advisory.belief, BELIEF.CONJECTURAL);
  assert.equal(r.advisory.needs_verification, true);
  assert.ok(r.advisory.commission, 'advisory must carry a commission envelope');
  assert.equal(r.advisory.commission.dispatched, false, 'commission is EMITTED, never dispatched');

  // The whole-run honesty summary.
  assert.equal(summary.settledAny, false);
  assert.equal(summary.allRouted, true);
  assert.equal(summary.allAdvisory, true);
  assert.equal(summary.honestStamps, true);
  assert.equal(summary.held, true, 'no commission-id dispatched + no rung-flip on the smoke path');
});

test('the smoke run NEVER raises a VERIFIED rung for the proof claim (THE HONESTY LAW)', () => {
  const summary = invokeSkill();
  for (const r of summary.results) {
    assert.notEqual(r.verdict, ROUTE_VERDICT.VERIFIED);
    assert.notEqual(r.belief, BELIEF.VERIFIED);
    assert.notEqual(r.rung, RUNG.OBSERVED);
  }
});

test('the canned input is a frozen proof-bearing VERIFY request', () => {
  assert.equal(CANNED_PROOF_INPUT.pillar, 'verify');
  assert.equal(CANNED_PROOF_INPUT.claims[0].type, 'proof-bearing');
  assert.ok(Object.isFrozen(CANNED_PROOF_INPUT));
  assert.throws(() => {
    'use strict';
    CANNED_PROOF_INPUT.pillar = 'solve';
  });
});

// --- THE 5-GATE PRODUCTIONIZATION CHECKLIST ---

test('the 5-gate productionization checklist passes (project-DONE)', () => {
  const report = runProductionizationChecklist();
  assert.equal(report.total, 5, 'there must be exactly five gates');
  assert.equal(
    report.ok,
    true,
    `checklist failed: ${report.gates.filter((g) => !g.ok).map((g) => `${g.id} (${g.detail})`).join('; ')}`,
  );
  assert.equal(report.passed, 5);
  // Each gate id is present and individually green.
  const ids = report.gates.map((g) => g.id);
  assert.deepEqual(ids, [
    'G1-manifest',
    'G2-usage-contract',
    'G3-acceptance-boundary',
    'G4-invocation-smoke',
    'G5-honesty-law-no-green',
  ]);
  for (const g of report.gates) assert.equal(g.ok, true, `${g.id} must pass: ${g.detail}`);
});

test('the manifest checker passes on the real SKILL.md', () => {
  const result = checkManifest();
  assert.equal(result.ok, true, `manifest missing: ${result.missing.join(', ')}`);
  assert.equal(result.path, DEFAULT_SKILL_PATH);
});

// --- SKILL.md content: the full headline + per-pillar contract + acceptance boundary ---

test('SKILL.md carries the tiered-scope headline + a per-pillar usage contract for all six pillars', () => {
  const content = fs.readFileSync(DEFAULT_SKILL_PATH, 'utf8');
  assert.match(content, /no autonomous proof verification/i);
  assert.match(content, /ACCEPT = computational sub-claim/i);
  assert.match(content, /per-pillar usage contract/i);
  for (const pillar of ['Understand', 'Solve', 'Verify', 'Dialogue', 'Formalize', 'Contextualize']) {
    assert.match(content, new RegExp(`\\b${pillar}\\b`, 'i'), `usage contract must name ${pillar}`);
  }
});

test('SKILL.md declares the Increment-1 acceptance boundary (NS3-lift/NS4/NS7 = Increment-2)', () => {
  const content = fs.readFileSync(DEFAULT_SKILL_PATH, 'utf8');
  assert.match(content, /NS abstain-arms DONE/i);
  assert.match(content, /Increment-2/);
  assert.match(content, /NS3/);
  assert.match(content, /NS4/);
  assert.match(content, /NS7/);
});

// --- NEGATIVE ARMS: each gate must FAIL on a planted violation (the gates are load-bearing) ---

test('G1 manifest gate FAILS on a SKILL.md missing a pillar', () => {
  const tmp = `${DEFAULT_SKILL_PATH}.__g1probe__.md`;
  // names everything except "Formalize" + the Honesty Law
  fs.writeFileSync(tmp, '# probe\nUnderstand Solve Verify Dialogue Contextualize. Honesty Law.\n');
  try {
    const report = runProductionizationChecklist({ skillPath: tmp });
    const g1 = report.gates.find((g) => g.id === 'G1-manifest');
    assert.equal(g1.ok, false);
    assert.match(g1.detail, /Formalize/);
    assert.equal(report.ok, false, 'a failing gate must fail the whole checklist');
  } finally {
    fs.rmSync(tmp, { force: true });
  }
});

test('G2 usage-contract gate FAILS when the per-pillar contract heading is absent', () => {
  const tmp = `${DEFAULT_SKILL_PATH}.__g2probe__.md`;
  // names all pillars + Honesty Law + the headline, but NO "per-pillar usage contract" heading
  fs.writeFileSync(
    tmp,
    '# probe\nno autonomous proof verification. ACCEPT = computational sub-claim.\n' +
      'Understand Solve Verify Dialogue Formalize Contextualize. THE HONESTY LAW.\n' +
      'NS abstain-arms DONE; NS3 NS4 NS7 Increment-2.\n',
  );
  try {
    const report = runProductionizationChecklist({ skillPath: tmp });
    const g2 = report.gates.find((g) => g.id === 'G2-usage-contract');
    assert.equal(g2.ok, false);
    assert.match(g2.detail, /per-pillar usage contract/i);
  } finally {
    fs.rmSync(tmp, { force: true });
  }
});

test('G3 acceptance-boundary gate FAILS when the Increment-2 declaration is absent', () => {
  const tmp = `${DEFAULT_SKILL_PATH}.__g3probe__.md`;
  // full headline + usage contract, but NO "NS abstain-arms DONE" / NS3-NS4-NS7 declaration
  fs.writeFileSync(
    tmp,
    '# probe\nno autonomous proof verification. ACCEPT = computational sub-claim.\n' +
      '## Per-pillar usage contract\nUnderstand Solve Verify Dialogue Formalize Contextualize. THE HONESTY LAW.\n',
  );
  try {
    const report = runProductionizationChecklist({ skillPath: tmp });
    const g3 = report.gates.find((g) => g.id === 'G3-acceptance-boundary');
    assert.equal(g3.ok, false);
    // G4/G5 (which run the real invocation) are unaffected by the SKILL.md probe and still pass.
    const g4 = report.gates.find((g) => g.id === 'G4-invocation-smoke');
    const g5 = report.gates.find((g) => g.id === 'G5-honesty-law-no-green');
    assert.equal(g4.ok, true);
    assert.equal(g5.ok, true);
  } finally {
    fs.rmSync(tmp, { force: true });
  }
});
