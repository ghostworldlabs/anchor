// crucible/test/judge-panel.test.mjs — Wave 3 (Front 3) gate for the CROSS-FAMILY judge panel.
//
// Drives the panel over the SAME Wave-2 lit-review rubric gate (the real clean deliverable +
// the deterministic, label-blind rubric scorer) with INJECTED dispatcher attestations — no
// subprocess, fully reproducible. Proves the wave's done-when:
//   - the panel fires >=2 judges across DISTINCT attested families and records ALL stamps;
//   - TWO attested families judge one rubric gate (each model_attested:true, distinct families)
//     with countIndependentOrigins >= 2 derived from DISPATCHER-attested stamps (not argv);
//   - the RED probes: a single-family run FAILS the two-family assertion — incl. an argv-claims-
//     two-but-served-one run (proving the count is NOT from argv), a Gemini-only enhanced run,
//     a degraded second family, and two off-enum families collapsing under the closed lineage enum;
//   - SR-6: the convergence-Judge path stays byte-identical (judge.mjs imported, not forked).
//
// Model-free + additive: this file only ADDS gates (SR-1 superset holds).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  runRubricPanel,
  requireTwoFamilies,
  summarizePanelArtifact,
  familyOfServedModel,
  PANEL_ROLE,
} from '../bin/judge-panel.mjs';
import { makeJudge } from '../bin/judge.mjs';
import { HaltError } from '../bin/crucible-lib.mjs';
import { loadPack } from '../bin/packs/registry.mjs';
import { hasAttestation, attestStamp } from '../../drivers/attest.mjs';
import { litReviewClean, litRubricScore } from './lit-review-e2e-fixtures.mjs';

const pack = loadPack('literature-review');

// Helper: a judge member that REQUESTS `family` and is SERVED `servedModel`, scoring the gate
// with the deterministic Wave-2 rubric scorer. `attest` overrides the dispatcher stamp directly.
const member = ({ family, servedModel, attest, probeCrossModel }) => ({
  family, servedModel, attest, probeCrossModel, score: litRubricScore,
});

// --- familyOfServedModel: the dispatcher (served-model) family mapping --------------------

test('familyOfServedModel maps SERVED model ids to lineages (and degrades on junk)', () => {
  assert.equal(familyOfServedModel('claude-opus-4-8'), 'claude');
  assert.equal(familyOfServedModel('gemini-3.1-pro-preview'), 'gemini');
  assert.equal(familyOfServedModel('gpt-5'), 'gpt');
  assert.equal(familyOfServedModel('o3-mini'), 'gpt');
  assert.equal(familyOfServedModel('grok-3'), 'grok');
  assert.equal(familyOfServedModel(null), null);
  assert.equal(familyOfServedModel(''), null);
});

// --- GREEN: two attested families judge one rubric gate -----------------------------------

test('GREEN: the panel fires TWO judges across DISTINCT attested families and records all stamps', async () => {
  const panel = await runRubricPanel({
    doc: litReviewClean, pack,
    members: [
      member({ family: 'claude', servedModel: 'claude-opus-4-8' }),
      member({ family: 'gemini', servedModel: 'gemini-3.1-pro-preview' }),
    ],
  });

  // >=2 judges, each with a recorded role stamp AND a recorded dispatcher attestation.
  assert.equal(panel.role, PANEL_ROLE);
  assert.equal(panel.members.length, 2);
  assert.equal(panel.stamps.length, 2, 'every role stamp recorded');
  assert.equal(panel.attestations.length, 2, 'every dispatcher stamp recorded');

  // Each member is dispatcher-attested (model_attested:true) and the two families are distinct.
  for (const m of panel.members) {
    assert.equal(m.attestation.model_attested, true);
    assert.equal(hasAttestation(m.attestation), true, 'each stamp is a well-formed SR-5 triple');
  }
  assert.deepEqual(panel.attestedFamilies, ['claude', 'gemini']);

  // countIndependentOrigins >= 2 from the DISPATCHER-attested stamps; two-family verdict holds.
  assert.ok(panel.independentOrigins >= 2, `origins ${panel.independentOrigins} >= 2`);
  assert.equal(panel.crossFamily, true);
  assert.deepEqual(requireTwoFamilies(panel), { ok: true, independentOrigins: 2, attestedFamilies: ['claude', 'gemini'] });

  // Both judged the SAME gate deterministically PASS -> the panel verdict is PASS.
  assert.deepEqual(panel.member_verdicts, ['PASS', 'PASS']);
  assert.equal(panel.verdict, 'PASS');
});

test('GREEN: the recordable live artifact shows TWO attested families judging one rubric gate', async () => {
  const panel = await runRubricPanel({
    doc: litReviewClean, pack,
    members: [
      member({ family: 'claude', servedModel: 'claude-opus-4-8' }),
      member({ family: 'gemini', servedModel: 'gemini-3.1-pro-preview' }),
    ],
  });
  const art = summarizePanelArtifact(panel);
  assert.equal(art.cross_family, true);
  assert.equal(art.independent_origins, 2);
  assert.deepEqual(art.attested_families, ['claude', 'gemini']);
  // Two members, each attested true, with DISTINCT served families.
  assert.equal(art.members.length, 2);
  assert.ok(art.members.every((m) => m.model_attested === true && m.degraded === false));
  assert.equal(new Set(art.members.map((m) => m.family_served)).size, 2);
  assert.deepEqual(art.members.map((m) => m.model_served).sort(), ['claude-opus-4-8', 'gemini-3.1-pro-preview']);
});

// --- RED PROBE 1: argv claims two families, the dispatcher served ONE (count is NOT argv) --

test('RED: an argv-claims-two-but-SERVED-one run FAILS the two-family assertion (count is dispatcher, not argv)', async () => {
  // The second member REQUESTS gemini (its role stamp says cross-model gemini) but the DISPATCHER
  // served claude-opus-4-8 for it. If the count read argv it would see {claude, gemini} = 2; it
  // reads the SERVED stamps {claude, claude} = 1 and refuses to close.
  const panel = await runRubricPanel({
    doc: litReviewClean, pack,
    members: [
      member({ family: 'claude', servedModel: 'claude-opus-4-8' }),
      member({ family: 'gemini', probeCrossModel: () => ({ model: 'gemini-pro', family: 'gemini' }), servedModel: 'claude-opus-4-8' }),
    ],
  });

  // The role stamps DO claim two families (argv-side) — proving the divergence is real...
  assert.deepEqual(panel.stamps.map((s) => s.family).sort(), ['claude', 'gemini']);
  // ...but the DISPATCHER served claude both times, so only one attested origin is counted.
  assert.deepEqual(panel.attestedFamilies, ['claude']);
  assert.equal(panel.independentOrigins, 1);
  assert.equal(panel.crossFamily, false);
  assert.throws(() => requireTwoFamilies(panel), (e) => e instanceof HaltError);
});

// --- RED PROBE 2: a Gemini-only enhanced run cannot pass as cross-family -------------------

test('RED: a Gemini-only run (two distinct gemini models) FAILS the two-family assertion', async () => {
  const panel = await runRubricPanel({
    doc: litReviewClean, pack,
    members: [
      member({ family: 'gemini', servedModel: 'gemini-3.1-pro-preview' }),
      member({ family: 'gemini', servedModel: 'gemini-3.1-flash-preview' }),
    ],
  });
  // Both attested, but the SAME lineage -> same-lineage agreement adds 0 (one origin only).
  assert.ok(panel.attestations.every((a) => a.model_attested === true));
  assert.deepEqual(panel.attestedFamilies, ['gemini']);
  assert.equal(panel.independentOrigins, 1);
  assert.equal(panel.crossFamily, false);
  assert.throws(() => requireTwoFamilies(panel), (e) => e instanceof HaltError);
});

// --- RED PROBE 3: a degraded second family cannot manufacture cross-family -----------------

test('RED: a degraded (unattested) second judge cannot manufacture a second family', async () => {
  const panel = await runRubricPanel({
    doc: litReviewClean, pack,
    members: [
      member({ family: 'claude', servedModel: 'claude-opus-4-8' }),
      // requested gemini, but the envelope exposed NO served model -> degraded, model_attested:false.
      member({ family: 'gemini', probeCrossModel: () => ({ model: 'gemini-pro', family: 'gemini' }), attest: attestStamp(null) }),
    ],
  });
  assert.equal(panel.members[1].attestation.model_attested, false);
  assert.equal(panel.members[1].attestation.degraded, true);
  // Only the attested claude counts; the degraded member is excluded from the origin count.
  assert.deepEqual(panel.attestedFamilies, ['claude']);
  assert.equal(panel.independentOrigins, 1);
  assert.equal(panel.crossFamily, false);
  assert.throws(() => requireTwoFamilies(panel), (e) => e instanceof HaltError);
});

// --- RED PROBE 4: the closed lineage enum gates off-enum families --------------------------

test('RED: two OFF-ENUM attested families collapse to one capped origin (closed lineage enum gates them)', async () => {
  // Both attested, but neither lineage is in the committed enum [claude, gemini, gpt, grok] —
  // crit-5 collapses all off-enum lineages into ONE capped bucket, so they cannot furnish two
  // independent origins. (This is the committed-enum default, consumed here, not re-implemented.)
  const panel = await runRubricPanel({
    doc: litReviewClean, pack,
    members: [
      member({ family: 'mistral', probeCrossModel: () => ({ model: 'mistral-large', family: 'mistral' }), servedModel: 'mistral-large' }),
      member({ family: 'cohere', probeCrossModel: () => ({ model: 'command-r', family: 'cohere' }), servedModel: 'command-r' }),
    ],
  });
  assert.ok(panel.attestations.every((a) => a.model_attested === true), 'both are dispatcher-attested...');
  assert.equal(panel.independentOrigins, 1, '...but both are off the closed enum -> one capped origin');
  assert.equal(panel.crossFamily, false);
  assert.throws(() => requireTwoFamilies(panel), (e) => e instanceof HaltError);
});

// --- guards ------------------------------------------------------------------------------

test('the panel HALTs when fewer than two judges are provisioned', async () => {
  await assert.rejects(
    () => runRubricPanel({ doc: litReviewClean, pack, members: [member({ family: 'claude', servedModel: 'claude-opus-4-8' })] }),
    (e) => e instanceof HaltError,
  );
});

// --- SR-6: the convergence-Judge path is reused, never forked -----------------------------

test('SR-6: the panel reuses the rubric machinery; the convergence Judge path stays byte-identical', async () => {
  // The panel speaks the rubric contract (PASS/FAIL), DISTINCT from the convergence Judge's
  // CONVERGED/NOT_CONVERGED — which still returns its own contract unchanged via a stub agent.
  const panel = await runRubricPanel({
    doc: litReviewClean, pack,
    members: [
      member({ family: 'claude', servedModel: 'claude-opus-4-8' }),
      member({ family: 'gemini', servedModel: 'gemini-3.1-pro-preview' }),
    ],
  });
  for (const v of panel.member_verdicts) assert.ok(v === 'PASS' || v === 'FAIL');

  const stubAgent = async () => ({ decision: 'CONVERGED', reasons: [], blocking: [] });
  const judge = makeJudge({ agent: stubAgent });
  const verdict = await judge.decide({ northStar: 'NS', findings: [], acceptanceCriteria: [] });
  assert.equal(verdict.decision, 'CONVERGED');
  assert.equal(verdict.lockable, true);
});
