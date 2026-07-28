// test/stage2.test.mjs — Wave 8 gate for Stage 2: Implementation Plan + handoff.
//
// Drives bin/stage2.mjs with an INJECTED (stubbed) agent seam — no live model — and
// proves the done-when + G/W/T:
//   · wave DECOMPOSITION (PM heuristics) turns an approved Master Plan into ordered
//     waves, each with a one-line done-when, non-trivial waves with G/W/T;
//   · the renderer emits `## Wave N` (contiguous), a `test-command:` line, and the
//     hybrid acceptance criteria — and assigns wave numbers itself (never trusts the
//     model's numbering);
//   · writeDocTrio emits the three docs + a `foreman.config.json` that names them;
//   · the Shark-Tank loop drives to model-side convergence (reusing Stage-1's loop);
//   · the user-approval HALT gate (implementation-plan-approval) HALTs until approved;
//   · the handoff is guarded by the well-formedness gate (FAIL ⇒ HALT, no handoff);
//   · done-when / G/W/T — a scripted approved Master Plan runs through Stage 2 to an
//     emitted doc-trio (+ config) that PASSES the Wave-4 well-formedness gate (the REAL
//     gate, spawning Foreman's locate-plan.mjs) with ZERO HALTs.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { HaltError } from '../bin/crucible-lib.mjs';
import { runWellFormednessGate } from '../bin/gates.mjs';
import {
  WAVE_DECOMP_SCHEMA,
  DEFAULT_DOC_FILENAMES,
  DEFAULT_TEST_COMMAND,
  normalizeWaves,
  decomposeIntoWaves,
  renderImplementationPlan,
  renderDescriptionDoc,
  renderExecutionLog,
  writeDocTrio,
  runHandoffGate,
  approveImplementationPlan,
  runStage2,
  parseWavesFromMarkdown,
} from '../bin/stage2.mjs';

const NORTH_STAR = 'STAGE2-NS-SENTINEL: emit a vetted, Foreman-ready doc-trio that locate-plan accepts.';
const CRITERIA = ['emits a zero-HALT doc-trio', 'every wave has a done-when'];
const MASTER_PLAN = `# Master Plan\n\n**North Star:** ${NORTH_STAR}\n\n## Phase 1 — Engine\n- import foreman-lib\n`;

// Two waves: a non-trivial one (with G/W/T) and a trivial one (done-when only).
const DEFAULT_DECOMP = [
  {
    title: 'Engine skeleton',
    intent: 'stand up the Node engine importing Foreman primitives',
    deliverables: ['package.json', 'bin/lib.mjs', 'a smoke test'],
    dependsOn: null,
    doneWhen: 'node --test test/ passes the import smoke-test',
    nonTrivial: true,
    gwt: [{ given: 'the imports', when: 'the smoke test runs', then: 'every primitive is a function' }],
  },
  {
    title: 'Docs polish',
    deliverables: ['README.md'],
    dependsOn: 'Engine skeleton',
    doneWhen: 'the README renders',
    nonTrivial: false,
    gwt: [],
  },
];

/** A label-routed stub agent covering Stage-2 decomposition + the reused loop. */
function makeStage2Agent({ decomp = DEFAULT_DECOMP, blockedUntilRound = 1, distinctBlockerPerRound = false } = {}) {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    const label = opts.label || '';

    if (label === 'stage2:decompose') return { waves: decomp };
    if (label.startsWith('stage1:revise')) {
      return { draft: `# Implementation Plan (revised)\n\n**North Star:** ${NORTH_STAR}\n`, changelog: ['addressed the blocker'] };
    }
    if (label.startsWith('shark:')) {
      const parts = label.split(':'); // shark:Role:rN
      const role = parts[1];
      const round = parseInt(String(parts[2] || 'r0').slice(1), 10) || 0;
      if (round < blockedUntilRound && (role === 'Skeptic' || role === 'Contrarian')) {
        // A distinct topic per round defeats anti-oscillation so cap tests never converge.
        const topic = distinctBlockerPerRound
          ? `decomposition underspecified r${round}` : 'decomposition underspecified';
        return {
          answerable: 'yes',
          findings: [{ severity: 'BLOCKER', topic, section: 'waves', tag: 'refinement', traces_to_north_star: 'yes', criterion: 'C1', message: 'a wave lacks acceptance criteria' }],
        };
      }
      return { answerable: 'yes', findings: [] };
    }
    if (label.startsWith('synthesizer:direct')) return { lean: 'lockable', openDisputes: [], riskRegister: [], probingBrief: 'press the gate', suggestions: [] };
    if (label.includes('fresh-eyes')) return { lean: 'lockable', concerns: [], note: 'cold read concurs' };
    if (label.startsWith('judge:')) return { decision: 'CONVERGED', reasons: ['dry round, no open blocker'] };
    return {};
  }
  agent.calls = calls;
  return agent;
}

// --- (1) decomposition ------------------------------------------------------

test('decomposeIntoWaves is schema-forced, North-Star-bound, and numbers waves itself (1..N)', async () => {
  const agent = makeStage2Agent();
  const waves = await decomposeIntoWaves({ agent, northStar: NORTH_STAR, criteria: CRITERIA, masterPlan: MASTER_PLAN });

  assert.equal(agent.calls[0].opts.schema, WAVE_DECOMP_SCHEMA);
  assert.match(agent.calls[0].prompt, /STAGE2-NS-SENTINEL/, 'the North Star is embedded');
  assert.match(agent.calls[0].prompt, /APPROVED MASTER PLAN/, 'the Master Plan is handed in');
  assert.equal(waves.length, 2);
  assert.deepEqual(waves.map((w) => w.n), [1, 2], 'numbered 1..N by position');
  assert.equal(waves[0].nonTrivial, true);
  assert.ok(waves[0].gwt.length >= 1, 'non-trivial wave keeps its G/W/T');
});

test('normalizeWaves re-numbers contiguously even if the model mis-numbers, and HALTs on a missing done-when', () => {
  const renumbered = normalizeWaves([
    { title: 'B', n: 7, doneWhen: 'b passes' },
    { title: 'A', n: 2, doneWhen: 'a passes' },
  ]);
  assert.deepEqual(renumbered.map((w) => w.n), [1, 2], 'positions win over the model numbers');

  assert.throws(
    () => normalizeWaves([{ title: 'no criteria', doneWhen: '' }]),
    (e) => e instanceof HaltError && e.pending_action === 'rerun-decomposition',
  );
  assert.throws(
    () => normalizeWaves([]),
    (e) => e instanceof HaltError && e.pending_action === 'rerun-decomposition',
  );
});

// --- (2) rendering ----------------------------------------------------------

test('renderImplementationPlan emits a test-command, contiguous ## Wave N, done-when, and G/W/T', () => {
  const waves = normalizeWaves(DEFAULT_DECOMP);
  const md = renderImplementationPlan({ northStar: NORTH_STAR, criteria: CRITERIA, waves });

  assert.match(md, new RegExp(`^test-command: ${DEFAULT_TEST_COMMAND.replace(/\./g, '\\.')}$`, 'm'),
    'default Windows-safe expanding gate (0076 package 4)');
  assert.equal(DEFAULT_TEST_COMMAND, 'node scripts/run-all-tests.mjs');
  assert.match(md, /## Wave 1 — Engine skeleton/);
  assert.match(md, /## Wave 2 — Docs polish/);
  assert.match(md, /\*\*done-when:\*\* node --test test\/ passes the import smoke-test/);
  assert.match(md, /\*\*Given\*\* the imports, \*\*when\*\* the smoke test runs, \*\*then\*\* every primitive is a function/);
  assert.match(md, /\*\*Depends on:\*\* —/, 'first wave depends on nothing');
  assert.match(md, /\*\*Depends on:\*\* Engine skeleton/, 'second wave records its dependency');
});

test('writeDocTrio emits the three docs + foreman.config.json + scripts/run-all-tests.mjs', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-s2-trio-'));
  try {
    const waves = normalizeWaves(DEFAULT_DECOMP);
    const trio = writeDocTrio({
      outputDir: dir,
      plan: renderImplementationPlan({ northStar: NORTH_STAR, criteria: CRITERIA, waves }),
      description: renderDescriptionDoc({ northStar: NORTH_STAR, criteria: CRITERIA }),
      executionLog: renderExecutionLog({ waveCount: waves.length }),
    });
    for (const role of Object.keys(DEFAULT_DOC_FILENAMES)) {
      assert.ok(fs.existsSync(trio.files[role]), `${role} written`);
    }
    const cfg = JSON.parse(fs.readFileSync(trio.configPath, 'utf8'));
    assert.equal(cfg.docs.plan, DEFAULT_DOC_FILENAMES.plan);
    assert.equal(cfg.docs.description, DEFAULT_DOC_FILENAMES.description);
    assert.equal(cfg.docs.execution_log, DEFAULT_DOC_FILENAMES.execution_log);
    // Sleep 0076 package 4: helper must exist so default test-command is runnable.
    assert.ok(fs.existsSync(trio.files.run_all_tests), 'scripts/run-all-tests.mjs written');
    const helper = fs.readFileSync(trio.files.run_all_tests, 'utf8');
    assert.match(helper, /--test/);
    assert.match(helper, /\.test\.mjs/);
    assert.match(helper, /windowsHide:\s*true/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// --- (3) the handoff gate ---------------------------------------------------

test('runHandoffGate HALTs (no handoff) when the well-formedness gate fails', () => {
  // Stub the gate to FAIL — the handoff must refuse rather than hand off a bad trio.
  assert.throws(
    () => runHandoffGate({ projectDir: 'x', runGate: () => ({ pass: false, status: 3, stderr: 'HALT: no waves' }) }),
    (e) => e instanceof HaltError && e.pending_action === 'well-formedness-gate-failed',
  );
  const ok = runHandoffGate({ projectDir: 'x', runGate: () => ({ pass: true, status: 0, report: { total_waves: 2 } }) });
  assert.equal(ok.handed_off, true);
});

// --- (4) the user-approval HALT gate ----------------------------------------

test('approveImplementationPlan HALTs at the canonical implementation-plan-approval gate until approved', () => {
  const loop = { modelSideLockable: true, roundsRun: 1 };

  let halt;
  try {
    approveImplementationPlan({ loop, approved: false });
  } catch (e) {
    halt = e;
  }
  assert.ok(halt instanceof HaltError, 'unapproved ⇒ HALT');
  assert.equal(halt.pending_action, 'implementation-plan-approval', 'names the canonical stage2->done gate');

  const ok = approveImplementationPlan({ loop, approved: true });
  assert.equal(ok.approved, true);
  assert.equal(ok.gate, 'implementation-plan-approval');
});

test('approveImplementationPlan refuses a not-yet-converged loop', () => {
  assert.throws(
    () => approveImplementationPlan({ loop: { modelSideLockable: false }, approved: true }),
    (e) => e instanceof HaltError && e.pending_action === 'stage2-not-converged',
  );
});

// --- done-when + G/W/T: end-to-end, gated by the REAL well-formedness gate ---

test('done-when: a scripted approved Master Plan runs through Stage 2 to a doc-trio that PASSES the real well-formedness gate with zero HALTs', async () => {
  const agent = makeStage2Agent({ blockedUntilRound: 2 }); // one block→fix→dry loop
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-s2-e2e-'));
  try {
    const out = await runStage2({
      agent, northStar: NORTH_STAR, masterPlan: MASTER_PLAN, criteria: CRITERIA,
      outputDir: dir, acceptanceCriteria: ['every wave has a done-when'], approved: true,
    });

    // The loop converged model-side and the user approved.
    assert.equal(out.loop.modelSideLockable, true);
    assert.equal(out.loop.roundsRun, 2, 'one full Shark-Tank loop (block → fix → dry)');
    assert.equal(out.approval.approved, true);
    assert.equal(out.approval.gate, 'implementation-plan-approval');

    // The handoff gate (the REAL locate-plan spawn) passed with zero HALTs.
    assert.equal(out.handoff.handed_off, true);
    assert.equal(out.handoff.gate.pass, true, 'the well-formedness gate passed');
    assert.equal(out.handoff.gate.status, 0, 'locate-plan exited 0 (zero HALTs)');
    assert.equal(out.handoff.gate.report.total_waves, 2, 'locate-plan resolved both waves');

    // G/W/T: every wave has a done-when; the config + plan exist on disk.
    assert.ok(out.waves.every((w) => w.doneWhen), 'every wave has a done-when');
    assert.ok(fs.existsSync(out.docTrio.configPath), 'foreman.config.json written');
    assert.match(fs.readFileSync(out.docTrio.files.plan, 'utf8'), /## Wave 1 —/);

    // Independently re-run the real gate over the emitted dir to confirm it stands alone.
    const reGate = runWellFormednessGate({ projectDir: out.docTrio.dir });
    assert.equal(reGate.pass, true, 'the emitted dir passes locate-plan on its own');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('T5 REGRESSION: a Stage-2 round-cap EMITS the unapproved doc-trio, runs the machine gate, and HALTs with everything attached', async () => {
  const agent = makeStage2Agent({ blockedUntilRound: 99, distinctBlockerPerRound: true });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-s2cap-'));
  try {
    let halt = null;
    try {
      await runStage2({
        agent, northStar: NORTH_STAR, masterPlan: MASTER_PLAN, criteria: CRITERIA,
        outputDir: dir, roundCap: 2,
      });
    } catch (e) { halt = e; }
    assert.ok(halt instanceof HaltError && halt.pending_action === 'stage2-round-cap',
      'the shared loop HALTs under the Stage-2 name');
    assert.ok(halt.best_draft, 'the best draft rides on the HALT');
    assert.ok(halt.emitted, 'the doc-trio was emitted on the HALT path');
    // Emitted to an UNMISTAKABLY-unapproved draft dir — never the handoff target itself.
    const draftDir = path.join(dir, '_unapproved-cap-draft');
    assert.ok(fs.existsSync(path.join(draftDir, DEFAULT_DOC_FILENAMES.plan)), 'plan emitted');
    assert.ok(fs.existsSync(path.join(draftDir, DEFAULT_DOC_FILENAMES.description)), 'description emitted');
    assert.ok(fs.existsSync(path.join(draftDir, 'foreman.config.json')), 'config emitted');
    assert.equal(halt.emitted.wellFormedness.pass, true,
      'by-construction rendering passes the REAL well-formedness gate even unconverged');
    assert.match(halt.reason, /NOT the handoff/);
    // The real handoff target itself received no doc-trio (no unapproved handoff).
    assert.ok(!fs.existsSync(path.join(dir, DEFAULT_DOC_FILENAMES.plan)),
      'outputDir root stays clean — approval still gates the real handoff');
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('Stage 2 HALTs at the approval gate when unapproved (the user is the convergence authority)', async () => {
  const agent = makeStage2Agent({ blockedUntilRound: 1 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-s2-halt-'));
  try {
    await assert.rejects(
      () => runStage2({ agent, northStar: NORTH_STAR, masterPlan: MASTER_PLAN, criteria: CRITERIA, outputDir: dir, approved: false }),
      (e) => e instanceof HaltError && e.pending_action === 'implementation-plan-approval',
    );
    // Nothing was emitted before approval (no handoff of an unapproved plan).
    assert.ok(!fs.existsSync(path.join(dir, DEFAULT_DOC_FILENAMES.plan)), 'no doc-trio emitted before approval');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// --- wiring guards ----------------------------------------------------------

test('Stage-2 entrypoints HALT without an agent() seam, a North Star, a Master Plan, or an outputDir', async () => {
  await assert.rejects(() => decomposeIntoWaves({ northStar: NORTH_STAR, masterPlan: MASTER_PLAN }), (e) => e instanceof HaltError);
  await assert.rejects(() => runStage2({ agent: () => {}, northStar: null, masterPlan: MASTER_PLAN, outputDir: 'x' }), (e) => e instanceof HaltError);
  await assert.rejects(() => runStage2({ agent: () => {}, northStar: NORTH_STAR, masterPlan: null, outputDir: 'x' }), (e) => e instanceof HaltError);
  await assert.rejects(() => runStage2({ agent: () => {}, northStar: NORTH_STAR, masterPlan: MASTER_PLAN, outputDir: null }), (e) => e instanceof HaltError);
});

// ---------------------------------------------------------------------------
// parseWavesFromMarkdown — the raw-text recovery fallback (journal 0002).
// Schema stays the FIRST ask in decomposeIntoWaves; this parser only catches
// live drivers that answered in markdown. Garbage must HALT, never invent.
// ---------------------------------------------------------------------------

test('parseWavesFromMarkdown recovers titled waves with intent/deliverables/dependsOn/doneWhen/GWT', () => {
  const raw = [
    '## Wave 1: Build the parser',
    'Intent: recover waves from markdown',
    'Deliverables: parser.mjs; tests',
    'Depends On: null',
    'Done When: the suite is green',
    'Given: a markdown reply',
    'When: it is parsed',
    'Then: waves come back structured',
    '## Wave 2: Wire the fallback',
    'Intent: fallback only after schema fails',
    'Deliverables: stage2.mjs',
    'Depends On: Build the parser',
    'Done When: fallback covered by tests',
  ].join('\n');
  const waves = parseWavesFromMarkdown(raw);
  assert.equal(waves.length, 2);
  assert.equal(waves[0].title, 'Build the parser');
  assert.deepEqual(waves[0].deliverables, ['parser.mjs', 'tests']);
  assert.equal(waves[0].dependsOn, null);
  assert.equal(waves[0].doneWhen, 'the suite is green');
  assert.equal(waves[0].gwt.length, 1);
  assert.equal(waves[0].gwt[0].then, 'waves come back structured');
  assert.equal(waves[1].dependsOn, 'Build the parser');
  // The recovered waves survive normalizeWaves (the real gate they must pass).
  const normalized = normalizeWaves(waves);
  assert.equal(normalized.length, 2);
  assert.equal(normalized[1].n, 2);
});

test('a garbage raw-text decomposition HALTs — the fallback never invents a plan', async () => {
  const agent = async () => 'I could not produce a decomposition, sorry about that.';
  await assert.rejects(
    () => decomposeIntoWaves({ agent, northStar: NORTH_STAR, masterPlan: MASTER_PLAN }),
    (e) => e instanceof HaltError && /no waves/i.test(e.message),
  );
});

test('a markdown wave MISSING its done-when still HALTs through normalizeWaves (D16 holds on the fallback path)', async () => {
  const agent = async () => '## Wave 1: Sloppy wave\nIntent: no done-when given\nDeliverables: x';
  await assert.rejects(
    () => decomposeIntoWaves({ agent, northStar: NORTH_STAR, masterPlan: MASTER_PLAN }),
    (e) => e instanceof HaltError && /done-when/i.test(e.message),
  );
});
