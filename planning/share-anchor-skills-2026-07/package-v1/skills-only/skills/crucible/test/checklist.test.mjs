// test/checklist.test.mjs — Wave 11 gate for bin/checklist.mjs.
//
// The 5-gate Skill Productionization Checklist = the five North-Star criteria
// (MASTER-PLAN §1), made checkable. These tests exercise each gate's PASS and FAIL
// path (a checklist that can only ever pass proves nothing), the aggregate tally, the
// assert-or-HALT helper, and the SKILL.md manifest checker (frontmatter parse + the
// real repo manifest).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  PRODUCTIONIZATION_GATES,
  checkForemanReadyOutput,
  checkConvergenceApproval,
  checkNoUntrackedDrift,
  checkAutonomousResume,
  checkIndependence,
  runProductionizationChecklist,
  renderChecklist,
  assertProductionized,
  parseSkillFrontmatter,
  checkSkillManifest,
} from '../bin/checklist.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..');

// A complete, all-passing evidence bundle the tests then perturb per gate.
function goodEvidence() {
  return {
    wellFormedness: { pass: true, status: 0, report: { total_waves: 2 } },
    waves: [{ n: 1, doneWhen: 'tests pass' }, { n: 2, doneWhen: 'docs render' }],
    convergence: { proved: true, findingRound: { round: 1, blockers: 1 }, dryRound: { round: 2 } },
    approval: { approved: true },
    drift: { active: true, surfaced: [{ topic: 'x', tracked: true }], untracked: 0 },
    checkpointResume: { halted: true, pendingAction: 'master-plan-approval', validated: true, resumed: true },
    stamps: [
      { role: 'Synthesizer', model: 'claude', family: 'claude', mode: 'default', cross_model: false },
      { role: 'Judge', model: 'claude', family: 'claude', mode: 'default', cross_model: false },
    ],
  };
}

// --- the gate definition --------------------------------------------------

test('the checklist has exactly 5 gates, one per North-Star criterion (1..5)', () => {
  assert.equal(PRODUCTIONIZATION_GATES.length, 5);
  assert.deepEqual(PRODUCTIONIZATION_GATES.map((g) => g.criterion), [1, 2, 3, 4, 5]);
  assert.deepEqual(PRODUCTIONIZATION_GATES.map((g) => g.id), ['G1', 'G2', 'G3', 'G4', 'G5']);
});

// --- G1 Foreman-ready output ----------------------------------------------

test('G1 passes on a zero-HALT gate with done-whens; fails on a HALT or a missing done-when', () => {
  const e = goodEvidence();
  assert.equal(checkForemanReadyOutput(e).pass, true);

  assert.equal(checkForemanReadyOutput({ ...e, wellFormedness: { pass: false, status: 3 } }).pass, false, 'locate-plan HALT ⇒ FAIL');
  assert.equal(checkForemanReadyOutput({ ...e, wellFormedness: { pass: true, status: 0 }, waves: [{ n: 1, doneWhen: '' }] }).pass, false, 'a wave with no done-when ⇒ FAIL');
  assert.equal(checkForemanReadyOutput({ ...e, waves: [] }).pass, false, 'no waves ⇒ FAIL');
});

// --- G2 convergence + approval --------------------------------------------

test('G2 passes only when a finding round precedes a dry round AND the user approved', () => {
  const e = goodEvidence();
  assert.equal(checkConvergenceApproval(e).pass, true);

  // No finding ever tallied — a vacuous "dry from round 1" cannot prove convergence.
  assert.equal(checkConvergenceApproval({ ...e, convergence: { findingRound: null, dryRound: { round: 1 } } }).pass, false);
  // A finding but no SUBSEQUENT dry round.
  assert.equal(checkConvergenceApproval({ ...e, convergence: { findingRound: { round: 2, blockers: 1 }, dryRound: { round: 1 } } }).pass, false);
  // Converged model-side but the user did not approve (the user is the authority).
  assert.equal(checkConvergenceApproval({ ...e, approval: { approved: false } }).pass, false);
});

// --- G3 zero untracked drift ----------------------------------------------

test('G3 passes when drift detection is active and nothing is untracked; fails otherwise', () => {
  const e = goodEvidence();
  assert.equal(checkNoUntrackedDrift(e).pass, true);
  assert.equal(checkNoUntrackedDrift({ ...e, drift: { active: false, surfaced: [], untracked: 0 } }).pass, false, 'detection off ⇒ FAIL');
  assert.equal(checkNoUntrackedDrift({ ...e, drift: { active: true, surfaced: [{ tracked: false }], untracked: 1 } }).pass, false, 'silent drift ⇒ FAIL');
});

// --- G4 autonomous between gates + checkpoint/resume ----------------------

test('G4 passes only on a HALT-at-gate + validated checkpoint + resume', () => {
  const e = goodEvidence();
  assert.equal(checkAutonomousResume(e).pass, true);
  assert.equal(checkAutonomousResume({ ...e, checkpointResume: { halted: false, pendingAction: null, validated: true, resumed: true } }).pass, false, 'never halted ⇒ FAIL');
  assert.equal(checkAutonomousResume({ ...e, checkpointResume: { halted: true, pendingAction: 'g', validated: false, resumed: true } }).pass, false, 'checkpoint did not validate ⇒ FAIL');
  assert.equal(checkAutonomousResume({ ...e, checkpointResume: { halted: true, pendingAction: 'g', validated: true, resumed: false } }).pass, false, 'never resumed ⇒ FAIL');
});

// --- G5 independence honored + stamped ------------------------------------

test('G5 passes on valid Judge + Synthesizer stamps; fails on a missing/lying stamp', () => {
  const e = goodEvidence();
  assert.equal(checkIndependence(e).pass, true);
  assert.equal(checkIndependence({ ...e, stamps: [e.stamps[0]] }).pass, false, 'missing the Judge stamp ⇒ FAIL');
  assert.equal(checkIndependence({ ...e, stamps: [] }).pass, false, 'no stamps ⇒ FAIL');
  // A Default-mode stamp that claims cross_model is a provenance lie — rejected.
  const lying = [{ role: 'Synthesizer', model: 'claude', family: 'claude', mode: 'default', cross_model: true }, e.stamps[1]];
  assert.equal(checkIndependence({ ...e, stamps: lying }).pass, false, 'default-mode cross_model:true ⇒ FAIL');
});

// --- the aggregate tally + assert helper ----------------------------------

test('runProductionizationChecklist tallies all 5 and allPass reflects every gate', () => {
  const e = goodEvidence();
  const ok = runProductionizationChecklist(e);
  assert.equal(ok.total, 5);
  assert.equal(ok.passed, 5);
  assert.equal(ok.allPass, true);
  assert.match(renderChecklist(ok), /5\/5 gate\(s\) pass/);
  assert.doesNotThrow(() => assertProductionized(ok));

  const bad = runProductionizationChecklist({ ...e, approval: { approved: false } });
  assert.equal(bad.allPass, false);
  assert.equal(bad.passed, 4);
  assert.throws(
    () => assertProductionized(bad),
    (err) => err instanceof HaltError && err.pending_action === 'productionization-checklist-failed',
  );
});

// --- SKILL.md manifest checker --------------------------------------------

test('parseSkillFrontmatter reads flat fields and folded block scalars', () => {
  const text = '---\nname: demo\ndescription: >-\n  line one\n  line two\n---\n# Body\nhello\n';
  const fm = parseSkillFrontmatter(text);
  assert.equal(fm.ok, true);
  assert.equal(fm.fields.name, 'demo');
  assert.equal(fm.fields.description, 'line one line two');
  assert.match(fm.body, /# Body/);

  assert.equal(parseSkillFrontmatter('no frontmatter here').ok, false);
});

test('checkSkillManifest passes on the real SKILL.md and fails on a malformed one', () => {
  const real = checkSkillManifest({ skillPath: path.join(REPO, 'SKILL.md') });
  assert.equal(real.pass, true, real.detail);
  assert.equal(real.name, 'crucible');
  assert.ok(real.description && real.description.length > 0);

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-skill-'));
  try {
    const noFm = path.join(dir, 'SKILL.md');
    fs.writeFileSync(noFm, '# Just a body, no frontmatter\n');
    assert.equal(checkSkillManifest({ skillPath: noFm }).pass, false);

    const noName = path.join(dir, 'SKILL2.md');
    fs.writeFileSync(noName, '---\ndescription: x\n---\n# Body\n');
    assert.equal(checkSkillManifest({ skillPath: noName }).pass, false);

    assert.equal(checkSkillManifest({ skillPath: path.join(dir, 'missing.md') }).pass, false, 'absent file ⇒ FAIL');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  assert.throws(() => checkSkillManifest({}), (e) => e instanceof HaltError);
});
