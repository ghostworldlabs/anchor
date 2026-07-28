// test/self-run.test.mjs — Wave 11 gate for bin/self-run.mjs (the dogfood self-run).
//
// Drives bin/self-run.mjs with the deterministic SCRIPTED agent (no model, no
// subprocess for the model steps) and proves the done-when + G/W/T of Wave 11:
//   · the self-run transcript shows CONVERGENCE — a real finding tallied in one round
//     followed by a SUBSEQUENT dry round;
//   · a USER-GATE HALT + RESUME — the Master-Plan approval gate HALTs, a Crucible
//     checkpoint is written + RE-VALIDATED on read, and the run resumes;
//   · a ZERO-HALT DOC-TRIO — Stage 2 emits the trio + foreman.config.json into a
//     dedicated isolated dir that the REAL well-formedness gate (spawning Foreman's
//     locate-plan.mjs) accepts with exit 0;
//   · the 5-gate Skill Productionization Checklist passes (5/5);
//   · the runnable entrypoint (main) exits 0 on a full pass.
// Plus the wave's distributed negative/HALT fixture (a config-less multi-.md dir HALTs)
// and the REAL buildable-project brownfield fixture (it builds GREEN + selects Tier 2).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { HaltError, readCheckpoint } from '../bin/crucible-lib.mjs';
import { runWellFormednessGate } from '../bin/gates.mjs';
import { selectTier, runIngest, TIERS } from '../bin/stage0.mjs';
import {
  SELF_RUN_INTENT,
  makeScriptedSelfRunAgent,
  dogfoodSelfRun,
  main,
} from '../bin/self-run.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(HERE, 'fixtures', 'buildable-project');

function tmpDir(tag) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `crucible-${tag}-`));
}

// --- the dogfood self-run, end-to-end -------------------------------------

test('done-when/G/W/T: the dogfood self-run converges (finding → dry round), HALTs+resumes at a user gate, and emits a zero-HALT doc-trio', async () => {
  const dir = tmpDir('selfrun');
  try {
    const { transcript, checklist, ok } = await dogfoodSelfRun({
      agent: makeScriptedSelfRunAgent(),
      outputDir: dir,
    });

    // CONVERGENCE — a real finding tallied at one round, a SUBSEQUENT dry round.
    assert.equal(transcript.convergence.proved, true);
    assert.ok(transcript.convergence.findingRound.blockers >= 1, 'a real BLOCKER was tallied');
    assert.ok(
      transcript.convergence.dryRound.round > transcript.convergence.findingRound.round,
      'the dry round follows the finding round',
    );

    // USER-GATE HALT + RESUME — at the canonical master-plan-approval gate, checkpointed.
    assert.equal(transcript.haltResume.halted, true);
    assert.equal(transcript.haltResume.pendingAction, 'master-plan-approval');
    assert.equal(transcript.haltResume.validated, true, 'the checkpoint re-validated on read');
    assert.equal(transcript.haltResume.resumed, true);
    // The checkpoint is a real, durable artifact that validates on its own.
    const cp = readCheckpoint(transcript.haltResume.checkpointPath);
    assert.equal(cp.status, 'halted');
    assert.equal(cp.pending_action, 'master-plan-approval');

    // ZERO-HALT DOC-TRIO — Stage 2 emitted into the isolated dir; locate-plan exit 0.
    assert.equal(transcript.gate.pass, true);
    assert.equal(transcript.gate.status, 0, 'locate-plan exited 0 (zero HALTs)');
    assert.equal(transcript.gate.total_waves, 2);
    assert.ok(fs.existsSync(transcript.docTrio.configPath), 'foreman.config.json emitted');
    assert.ok(transcript.waves.every((w) => w.doneWhen), 'every emitted wave has a done-when');
    assert.equal(transcript.drift.untracked, 0, 'no untracked post-lock drift');

    // The 5-gate checklist passes 5/5.
    assert.equal(ok, true);
    assert.equal(checklist.allPass, true);
    assert.equal(checklist.passed, 5);

    // The emitted dir stands alone under the REAL well-formedness gate (independent re-run).
    const reGate = runWellFormednessGate({ projectDir: transcript.docTrio.dir });
    assert.equal(reGate.pass, true, 'the isolated dir passes locate-plan on its own');
    assert.equal(reGate.status, 0);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('the self-run defaults to the canonical fixture intent and stamps both model-side roles (degraded-and-stamped)', async () => {
  const dir = tmpDir('selfrun-stamps');
  try {
    const { transcript } = await dogfoodSelfRun({ agent: makeScriptedSelfRunAgent(), outputDir: dir, intent: SELF_RUN_INTENT });
    const roles = transcript.stamps.map((s) => s.role).sort();
    assert.deepEqual(roles, ['Judge', 'Synthesizer']);
    assert.ok(transcript.stamps.every((s) => s.mode === 'default' && s.cross_model === false), 'Default mode ⇒ degraded-and-stamped');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('main (the runnable entrypoint) runs the dogfood and returns exit 0 on a full pass', async () => {
  const dir = tmpDir('selfrun-main');
  try {
    const code = await main([dir], { env: {}, log: () => {} });
    assert.equal(code, 0);
    assert.ok(fs.existsSync(path.join(dir, 'IMPLEMENTATION-PLAN.md')), 'doc-trio emitted to the given dir');
    assert.ok(fs.existsSync(path.join(dir, 'foreman.config.json')));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// --- wiring guards --------------------------------------------------------

test('dogfoodSelfRun HALTs without an agent seam or an output dir', async () => {
  await assert.rejects(() => dogfoodSelfRun({ outputDir: 'x' }), (e) => e instanceof HaltError);
  await assert.rejects(() => dogfoodSelfRun({ agent: makeScriptedSelfRunAgent() }), (e) => e instanceof HaltError);
});

// --- the negative/HALT fixture: why the isolated dir matters --------------

test('negative fixture: a config-less dir with two plan-ish *.md files HALTs locate-plan (the multi-.md-per-role hazard the isolated dir avoids)', () => {
  const dir = tmpDir('selfrun-ambig');
  try {
    // Two files both match the plan role and there is NO foreman.config.json to
    // disambiguate — exactly the ambiguous/multi-role HALT the self-run sidesteps by
    // emitting a named trio + config into a dedicated dir.
    fs.writeFileSync(path.join(dir, 'IMPLEMENTATION-PLAN.md'), '# plan A\n## Wave 1 — x\n');
    fs.writeFileSync(path.join(dir, 'MASTER-PLAN.md'), '# plan B\n');
    const gate = runWellFormednessGate({ projectDir: dir });
    assert.equal(gate.pass, false, 'ambiguous/config-less dir ⇒ gate FAIL');
    assert.notEqual(gate.status, 0, 'locate-plan did not exit 0');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// --- the real buildable-project brownfield fixture ------------------------

test('the brownfield fixture is a REAL buildable project (its own node --test is GREEN)', () => {
  assert.ok(fs.existsSync(path.join(FIXTURE, 'package.json')), 'fixture has a package.json');
  const r = spawnSync(process.execPath, ['--test', 'app-test.mjs'], { cwd: FIXTURE, encoding: 'utf8' });
  assert.equal(r.status, 0, `the fixture must build + test GREEN — exit ${r.status}\n${r.stdout}\n${r.stderr}`);
});

test('Stage-0 selects Tier 2 for the buildable-project repo, and runIngest produces a manifest', async () => {
  const sel = selectTier({ kind: 'brownfield', repoDir: FIXTURE });
  assert.equal(sel.tier, TIERS.TIER2, 'a brownfield project with a repo ⇒ Tier 2 (reproduce-first)');

  // A scripted ingest agent: inventory two items, reproduce-first true.
  async function agent(prompt, opts = {}) {
    const label = opts.label || '';
    if (label.includes('inventory')) {
      return { items: [{ id: 'i1', fact: 'exports sum/product', label: 'Confirmed', tested: true }], versions: [] };
    }
    if (label.includes('reproduce')) return { reproduces: true, note: 'node --test app-test.mjs is GREEN' };
    return {};
  }
  const intakeDir = tmpDir('selfrun-intake');
  try {
    const manifest = await runIngest({ tier: sel.tier, input: { repoDir: FIXTURE }, agent, intakeDir });
    assert.equal(manifest.tier, TIERS.TIER2);
    assert.equal(manifest.reproduces, true);
    assert.ok(manifest.items.length >= 1);
    assert.ok(fs.existsSync(manifest.manifestPath), 'an intake manifest is written');
  } finally {
    fs.rmSync(intakeDir, { recursive: true, force: true });
  }
});
