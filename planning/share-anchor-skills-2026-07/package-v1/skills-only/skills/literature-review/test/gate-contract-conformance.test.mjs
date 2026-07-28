// test/gate-contract-conformance.test.mjs — Wave 1 frozen-gate contract conformance
// (permanent standalone CI artifact, promoted from the spike).
//
// Empirical claim under test: researchPrime's bin/plan-gate.mjs + bin/two-gate.mjs, at their
// committed bytes and with ZERO edits, accept a hand-authored synthetic NON-researchPrime plan
// rendered as human-readable prose into the gate's generic plan body (the injectable
// `buildPlan` seam — the SAME seam plan-gate.mjs itself uses to inject the RP Phase-1 plan):
//   - APPROVE proceeds to a hash-bound governance record,
//   - EDIT is accepted (bounded) and produces a NEW governance hash,
//   - ABORT halts,
//   - a run with no APPROVE never reaches execution,
//   - and the gate reads NO RP-specific field off the plan (the synthetic plan carries ONLY
//     { planVersion, body } — no objective/tier/stakes/foresight — and still round-trips).
// A byte-hash of both gate files is taken before and re-checked after the suite to prove the
// suite itself never modified them.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';

import { rpFile, importRp, fileSha256 } from './_wave1-trio-resolve.mjs';

// ── The hand-authored synthetic non-RP prose plan (the gate's generic plan body) ──────────
const PROSE_V1 = [
  '# Research Plan — synthetic non-RP prose plan (Wave-1 gate-contract spike)',
  '',
  '## Scope / AXIS',
  'Map the empirical evidence on spaced-repetition scheduling in medical curricula.',
  'AXIS: a candidate approach is FALSIFIED if it cannot cite at least one controlled trial.',
  '',
  '## Candidate branches / questions',
  '- Does expanding-interval scheduling beat fixed-interval scheduling on 6-month retention?',
  '- Do retrieval-practice effects survive transfer to clinical reasoning tasks?',
  '',
  '## Sources to beat',
  '- Cepeda et al. 2006 — the distributed-practice meta-analysis (current best-in-class).',
  '',
  '## Foresight receipt',
  'Dropped the "mobile-app telemetry" branch; counterfactual cost: we lose in-the-wild',
  'adherence data but avoid an unbounded instrumentation effort.',
  '',
  '## Seeds',
  '- (seed) 10.1000/example-doi-1 — Example Seed Paper One',
  '- (seed) PMID:12345678 — Example Seed Paper Two',
].join('\n');

const PROSE_V2 = PROSE_V1 + '\n\n## User edit\n- Added branch: interleaving vs blocking in anatomy drills.\n';

// Pure function of `inputs` (the two-gate EDIT re-hash discipline requires this): the plan is
// a NON-RP shape — a generic markdown prose body plus a version tag, nothing else.
function buildProsePlan({ inputs }) {
  return {
    planVersion: 'litreview-brownfield-plan/prose-spike-1',
    body: inputs.planProse,
  };
}

const INPUTS_V1 = Object.freeze({
  objective: 'Wave-1 synthetic non-RP plan spike (literature-review)',
  planProse: PROSE_V1,
});

function sha256(str) {
  return crypto.createHash('sha256').update(str).digest('hex');
}

function tmpRunDir(tag) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `litrev-w1-${tag}-`));
}

describe('Wave 1 — frozen-gate contract conformance (plan-gate.mjs + two-gate.mjs unchanged)', () => {
  const GATE_FILES = ['bin/plan-gate.mjs', 'bin/two-gate.mjs'];
  const hashesBefore = {};
  const runDirs = [];
  let twoGate; // { runTwoGateMachine, validateExecutionState }
  let planGate; // { runPlanReviewGate, buildResearchPlan, RESEARCH_PLAN_VERSION }
  let HaltError;

  before(async () => {
    for (const f of GATE_FILES) hashesBefore[f] = fileSha256(rpFile(f));
    twoGate = await importRp('bin/two-gate.mjs');
    planGate = await importRp('bin/plan-gate.mjs');
    ({ HaltError } = await importRp('bin/trio-core/contract-core.mjs'));
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  test('APPROVE proceeds: the non-RP prose plan is presented verbatim and yields a hash-bound governance record', async () => {
    const runDir = tmpRunDir('approve');
    runDirs.push(runDir);
    const presented = [];

    const res = await twoGate.runTwoGateMachine(INPUTS_V1, {
      runDir,
      buildPlan: buildProsePlan,
      promptGate1: async () => 'APPROVE',
      promptGate2: async ({ plan, planPath, planHash }) => {
        presented.push({ plan, planPath, planHash });
        return 'APPROVE';
      },
    });

    // The gate presented OUR plan object untouched — prose body byte-for-byte, and NO
    // RP-specific field was added or required (no objective/tier/stakes/foresight on the plan).
    assert.equal(presented.length, 1);
    assert.deepStrictEqual(presented[0].plan, {
      planVersion: 'litreview-brownfield-plan/prose-spike-1',
      body: PROSE_V1,
    });
    for (const rpField of ['objective', 'tier', 'stakes', 'foresight', 'branches', 'baselines']) {
      assert.equal(rpField in presented[0].plan, false, `gate must not require RP field "${rpField}"`);
    }

    // Hash binding: planHash = sha256 of the exact serialized plan bytes the gate persisted.
    const planStr = fs.readFileSync(presented[0].planPath, 'utf8');
    assert.equal(res.planHash, sha256(planStr));
    assert.equal(res.planHash, presented[0].planHash);
    assert.equal(planStr, JSON.stringify(buildProsePlan({ inputs: INPUTS_V1 }), null, 2));

    // Durable records: gate2-record bound to the same hash; canonical governance record emitted.
    const gate2 = JSON.parse(fs.readFileSync(path.join(runDir, 'gate2-record.json'), 'utf8'));
    assert.deepStrictEqual(gate2, { planHash: res.planHash, gate2Decision: 'APPROVE' });
    const gov = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.equal(gov.planHash, res.planHash);
    assert.equal(gov.gate2Decision, 'APPROVE');
    assert.equal(gov.gate1Decision, 'APPROVE');
  });

  test('EDIT is accepted once and RE-HASHES: the edited prose produces a new governance hash', async () => {
    const runDir = tmpRunDir('edit');
    runDirs.push(runDir);
    const presentedHashes = [];
    let decisions = ['EDIT', 'APPROVE'];

    const res = await twoGate.runTwoGateMachine(INPUTS_V1, {
      runDir,
      buildPlan: buildProsePlan,
      promptGate1: async () => 'APPROVE',
      promptGate2: async ({ planHash }) => {
        presentedHashes.push(planHash);
        return decisions.shift();
      },
      onEditedPlan: async (inputs) => ({ ...inputs, planProse: PROSE_V2 }),
    });

    assert.equal(presentedHashes.length, 2, 'EDIT re-presents the re-built plan exactly once');
    assert.notEqual(presentedHashes[0], presentedHashes[1], 'EDIT must produce a NEW plan hash');
    assert.equal(presentedHashes[0], sha256(JSON.stringify({ planVersion: 'litreview-brownfield-plan/prose-spike-1', body: PROSE_V1 }, null, 2)));
    assert.equal(res.planHash, sha256(JSON.stringify({ planVersion: 'litreview-brownfield-plan/prose-spike-1', body: PROSE_V2 }, null, 2)));

    // The approved (edited) plan is the one bound into the governance record.
    const gov = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.equal(gov.planHash, res.planHash);
  });

  test('EDIT is BOUNDED: with maxEdits=1 a second EDIT halts instead of looping', async () => {
    const runDir = tmpRunDir('editcap');
    runDirs.push(runDir);

    await assert.rejects(
      twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir,
        maxEdits: 1,
        buildPlan: buildProsePlan,
        promptGate1: async () => 'APPROVE',
        promptGate2: async () => 'EDIT',
        onEditedPlan: async (inputs) => ({ ...inputs }),
      }),
      (err) => err instanceof HaltError && /exceeded max EDIT cycles \(1\)/.test(err.message),
    );
    assert.equal(fs.existsSync(path.join(runDir, 'governance.json')), false);
  });

  test('ABORT halts: HaltError, durable HALT-RECORD, and execution is never reached', async () => {
    const runDir = tmpRunDir('abort');
    runDirs.push(runDir);

    await assert.rejects(
      twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir,
        buildPlan: buildProsePlan,
        promptGate1: async () => 'APPROVE',
        promptGate2: async () => 'ABORT',
      }),
      (err) => err instanceof HaltError && /Run halted at Gate 2 with decision ABORT/.test(err.message),
    );

    const halt = JSON.parse(fs.readFileSync(path.join(runDir, 'HALT-RECORD.json'), 'utf8'));
    assert.equal(halt.status, 'HALTED');
    assert.equal(fs.existsSync(path.join(runDir, 'governance.json')), false, 'ABORT must never reach execution');

    // Direct block check: the gate2 ABORT record can never validate into execution.
    assert.throws(
      () => {
        const gate2 = JSON.parse(fs.readFileSync(path.join(runDir, 'gate2-record.json'), 'utf8'));
        const gate1 = JSON.parse(fs.readFileSync(path.join(runDir, 'gate1-record.json'), 'utf8'));
        twoGate.validateExecutionState(runDir, gate1.triageHash, gate2.planHash);
      },
      (err) => err instanceof HaltError && /Execution blocked/.test(err.message),
    );
  });

  test('execution is blocked without APPROVE: a no-response run never reaches execution, and missing records block', async () => {
    const runDir = tmpRunDir('noresp');
    runDirs.push(runDir);

    // "No response" — the prompt yields nothing; the machine halts rather than defaulting on.
    await assert.rejects(
      twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir,
        buildPlan: buildProsePlan,
        promptGate1: async () => 'APPROVE',
        promptGate2: async () => undefined,
      }),
      (err) => err instanceof HaltError && /Run halted at Gate 2/.test(err.message),
    );
    assert.equal(fs.existsSync(path.join(runDir, 'governance.json')), false);

    // A bare runDir with no gate records at all is blocked outright.
    const emptyDir = tmpRunDir('empty');
    runDirs.push(emptyDir);
    assert.throws(
      () => twoGate.validateExecutionState(emptyDir, 'x', 'y'),
      (err) => err instanceof HaltError && /Execution blocked: Gate 1 record missing/.test(err.message),
    );
  });

  test('governance skill tag: unknown skills are refused; a caller-registered extension admits them (no RP file edit)', async () => {
    // Empirical finding for Wave 9: the governance record's `skill` field must either stay the
    // default ('researchPrime') or the caller must register an extension validator IN MEMORY via
    // the public registerExtension() seam — never by editing researchPrime files.
    const governance = await importRp('bin/governance.mjs');

    const blockedDir = tmpRunDir('skillblock');
    runDirs.push(blockedDir);
    await assert.rejects(
      twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir: blockedDir,
        skill: 'literature-review',
        buildPlan: buildProsePlan,
        promptGate1: async () => 'APPROVE',
        promptGate2: async () => 'APPROVE',
      }),
      (err) => err instanceof HaltError && /no extension validator registered for skill literature-review/.test(err.message),
    );

    governance.registerExtension('literature-review', () => true);
    const okDir = tmpRunDir('skillok');
    runDirs.push(okDir);
    const res = await twoGate.runTwoGateMachine(INPUTS_V1, {
      runDir: okDir,
      skill: 'literature-review',
      buildPlan: buildProsePlan,
      promptGate1: async () => 'APPROVE',
      promptGate2: async () => 'APPROVE',
    });
    assert.equal(res.governanceRecord.skill, 'literature-review');
  });

  test('plan-gate.mjs (the wrapper) still runs unmodified over the same two-gate machine', async () => {
    // plan-gate injects the RP Phase-1 builder through the SAME buildPlan seam the synthetic
    // non-RP plan used above — proving the seam is the wrapper's own supported entry, not a
    // side door. No researchPrime file is edited to make either path work.
    const runDir = tmpRunDir('plangate');
    runDirs.push(runDir);
    const presented = [];

    const res = await planGate.runPlanReviewGate(
      { objective: 'plan-gate wrapper conformance check', branches: ['b1'], baselines: ['base1'] },
      {
        runDir,
        promptGate1: async () => 'APPROVE',
        promptGate2: async ({ plan }) => {
          presented.push(plan);
          return 'APPROVE';
        },
      },
    );

    assert.equal(presented.length, 1);
    assert.equal(presented[0].planVersion, planGate.RESEARCH_PLAN_VERSION);
    assert.equal(presented[0].objective, 'plan-gate wrapper conformance check');
    assert.ok(res.planHash);
    assert.ok(fs.existsSync(path.join(runDir, 'governance.json')));
  });

  test('frozen-gate byte hashes are unchanged after the whole suite', () => {
    for (const f of GATE_FILES) {
      assert.equal(
        fileSha256(rpFile(f)),
        hashesBefore[f],
        `${f} must be byte-identical before and after the conformance suite (ZERO edits to the frozen gate)`,
      );
    }
  });
});
