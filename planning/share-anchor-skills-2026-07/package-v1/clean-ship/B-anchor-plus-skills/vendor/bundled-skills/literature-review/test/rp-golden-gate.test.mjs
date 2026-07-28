// test/rp-golden-gate.test.mjs — Wave 5: golden-output regression fence over researchPrime's
// LIVE gate behavior.
//
// Waves 1 and 4 proved the frozen gate ACCEPTS the lit-review flows and pinned the gate files'
// BYTES. This suite pins the gate's OUTPUTS — every durable record (triage artifact,
// gate1/gate2 records, governance record, HALT-RECORD, persisted plan file), every stamp
// (HaltError messages, blocked-execution messages, approval-provider identities), and every
// prompt payload the gate presents through its injectable seams — as golden fixtures under
// test/golden/rp-gate/. ANY later change to researchPrime that alters one of these outputs
// fails CI with a diff naming the changed output.
//
// Volatile values are normalized to placeholders before comparison: run directories to
// <RUN_DIR>, ISO timestamps to <TIMESTAMP>, and the run's sha256 hashes to named
// placeholders. The hash VALUES are not lost to normalization — a dedicated test re-derives
// them from the pinned inputs (sha256 of the exact serialized artifact bytes) and asserts
// the gate reported exactly those, so drift in the gate's serialization or hashing
// discipline fails loudly too.
//
// Fixture maintenance: run with RP_GOLDEN_UPDATE=1 to regenerate the fixtures after an
// INTENDED researchPrime change, then commit them. The final test asserts the flag is NOT
// set, so an update run can never itself pass CI.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

import { rpFile, importRp, fileSha256 } from './_wave1-trio-resolve.mjs';

const GOLDEN_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), 'golden', 'rp-gate');
const UPDATE = process.env.RP_GOLDEN_UPDATE === '1';

// Behavior pinned by goldens; bytes hashed before/after to prove THIS suite never edits them.
const FROZEN_FILES = [
  'bin/plan-gate.mjs',
  'bin/two-gate.mjs',
  'bin/intake.mjs',
  'bin/governance.mjs',
  'bin/approval-provider.mjs',
];

// ── Pinned synthetic non-RP prose plan (the lit-review-shaped flow through the gate) ──────
const PLAN_VERSION = 'litreview-brownfield-plan/golden-wave5-1';

const PROSE_V1 = [
  '# Research Plan — Wave-5 RP golden gate fence',
  '',
  '## Scope / AXIS',
  'Pin the frozen researchPrime plan-review gate behind a golden-output regression fence.',
  'AXIS: any drift in a gate record, stamp, or prompt payload FAILS the suite.',
  '',
  '## Seeds',
  '- (seed) 10.1000/wave5-golden-doi — Golden Fence Seed Paper',
].join('\n');

const PROSE_V2 = PROSE_V1 + '\n\n## User edit\n- Added branch: perturbation-detection sharpness.';

const INPUTS_V1 = Object.freeze({
  objective: 'Wave-5 RP golden gate fence (literature-review)',
  planProse: PROSE_V1,
});

// Pure function of `inputs` (the gate's EDIT re-hash discipline requires this).
function buildProsePlan({ inputs }) {
  return { planVersion: PLAN_VERSION, body: inputs.planProse };
}

// ── Pinned RP-native Phase-1 inputs (plan-gate.mjs's OWN buildResearchPlan path) ──────────
const RP_INPUTS = Object.freeze({
  objective: 'Wave-5 golden: pin the live researchPrime Phase-1 plan artifact',
  axis: 'A candidate approach is FALSIFIED if it cannot cite a controlled trial.',
  branches: [
    { id: 'B1', goal: 'high-value branch B1', est_value: 5, est_cost: 1 },
    {
      id: 'B2',
      goal: 'wasteful branch B2',
      est_value: 0,
      est_cost: 1,
      counterfactual_cost: '3 reviewer-hours wasted on a dead end',
    },
  ],
  baselines: ['Cepeda et al. 2006 distributed-practice meta-analysis'],
  stakes: { id: 'w5-stakes', declared_stakes: 'low', reversibility: 'irreversible' },
});

// ── Helpers ───────────────────────────────────────────────────────────────────────────────

function sha256(str) {
  return crypto.createHash('sha256').update(str).digest('hex');
}

function tmpRunDir(tag) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `litrev-w5-golden-${tag}-`));
}

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

function goldenPath(name) {
  return path.join(GOLDEN_DIR, name);
}

function loadGolden(name) {
  // CRLF-normalize only the FILE read (a CRLF-converting git config must not fake a diff).
  return JSON.parse(fs.readFileSync(goldenPath(name), 'utf8').replace(/\r\n/g, '\n'));
}

const ISO_TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

/**
 * Deep-clone a captured value (via JSON round-trip, matching how the gate persists it) and
 * replace every volatile substring with a stable placeholder so the result is byte-stable
 * across runs: run directories → <RUN_DIR>, the run's hashes → named placeholders, full ISO
 * timestamps → <TIMESTAMP>. Path separators inside <RUN_DIR> paths normalize to '/'.
 */
function normalize(value, { runDirs = [], hashes = {} }) {
  const substitute = (input) => {
    let out = input;
    for (const dir of runDirs) {
      out = out.split(dir).join('<RUN_DIR>');
      out = out.split(dir.replace(/\\/g, '/')).join('<RUN_DIR>');
    }
    if (out.includes('<RUN_DIR>')) out = out.replace(/\\/g, '/');
    for (const [hash, placeholder] of Object.entries(hashes)) {
      out = out.split(hash).join(placeholder);
    }
    if (ISO_TIMESTAMP_RE.test(out)) out = '<TIMESTAMP>';
    return out;
  };
  const walk = (v) => {
    if (typeof v === 'string') return substitute(v);
    if (Array.isArray(v)) return v.map(walk);
    if (v && typeof v === 'object') {
      const o = {};
      for (const [k, val] of Object.entries(v)) o[k] = walk(val);
      return o;
    }
    return v;
  };
  return walk(JSON.parse(JSON.stringify(value)));
}

function typeName(v) {
  if (v === null) return 'null';
  if (Array.isArray(v)) return 'array';
  return typeof v;
}

function shortValue(v) {
  const s = JSON.stringify(v);
  return s === undefined ? 'undefined' : s.length > 80 ? s.slice(0, 77) + '...' : s;
}

/**
 * Structural diff of a normalized capture against a golden fixture. Returns a list of
 * human-readable entries, each NAMING the path of the changed output — the fence's teeth.
 */
function deepDiff(expected, actual, base = '', out = []) {
  const label = base || '(root)';
  const te = typeName(expected);
  const ta = typeName(actual);
  if (te !== ta) {
    out.push(`${label}: expected ${te} ${shortValue(expected)}, got ${ta} ${shortValue(actual)}`);
    return out;
  }
  if (te === 'array') {
    if (expected.length !== actual.length) {
      out.push(`${label}.length: expected ${expected.length}, got ${actual.length}`);
    }
    const n = Math.min(expected.length, actual.length);
    for (let i = 0; i < n; i++) deepDiff(expected[i], actual[i], `${label}[${i}]`, out);
    return out;
  }
  if (te === 'object') {
    for (const key of Object.keys(expected)) {
      const p = base ? `${base}.${key}` : key;
      if (!(key in actual)) out.push(`${p}: missing from actual output`);
      else deepDiff(expected[key], actual[key], p, out);
    }
    for (const key of Object.keys(actual)) {
      if (!(key in expected)) {
        const p = base ? `${base}.${key}` : key;
        out.push(`${p}: unexpected new field ${shortValue(actual[key])}`);
      }
    }
    return out;
  }
  if (!Object.is(expected, actual)) {
    out.push(`${label}: expected ${shortValue(expected)}, got ${shortValue(actual)}`);
  }
  return out;
}

/** Compare only — never writes; used by the perturbation-sharpness test. */
function diffAgainstGolden(name, actual) {
  return deepDiff(loadGolden(name), actual);
}

/** Assert a normalized capture matches its pinned fixture (or regenerate under UPDATE). */
function assertGolden(name, actual) {
  if (UPDATE) {
    fs.mkdirSync(GOLDEN_DIR, { recursive: true });
    fs.writeFileSync(goldenPath(name), JSON.stringify(actual, null, 2) + '\n', 'utf8');
    return;
  }
  const diffs = diffAgainstGolden(name, actual);
  assert.equal(
    diffs.length,
    0,
    `RP golden drift in ${name} — the live gate output changed:\n  ${diffs.join('\n  ')}`,
  );
}

/** Run a sync gate call expected to HALT; return the stamp (the HaltError message). */
function haltMessage(fn) {
  try {
    fn();
    return '<NO HALT>';
  } catch (err) {
    return err.message;
  }
}

/** Await a gate run expected to HALT; capture whether it was a HaltError plus its stamp. */
async function haltOf(promise, HaltErrorClass) {
  try {
    await promise;
    return { haltError: false, message: '<NO HALT>' };
  } catch (err) {
    return { haltError: err instanceof HaltErrorClass, message: err.message };
  }
}

// ── The suite ─────────────────────────────────────────────────────────────────────────────

describe('Wave 5 — RP golden-output regression fence (live gate records, stamps, prompts)', () => {
  const runDirs = [];
  const frozenHashesBefore = {};
  const cap = {};
  let twoGate;
  let planGate;
  let approval;
  let HaltError;

  before(async () => {
    for (const f of FROZEN_FILES) frozenHashesBefore[f] = fileSha256(rpFile(f));
    twoGate = await importRp('bin/two-gate.mjs');
    planGate = await importRp('bin/plan-gate.mjs');
    approval = await importRp('bin/approval-provider.mjs');
    ({ HaltError } = await importRp('bin/trio-core/contract-core.mjs'));

    // ── Scenario A: APPROVE-verbatim — every record + prompt payload of a clean run ──────
    {
      const runDir = tmpRunDir('approve');
      const emptyDir = tmpRunDir('approve-empty');
      runDirs.push(runDir, emptyDir);
      const gate1Prompts = [];
      const gate2Prompts = [];
      const res = await twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir,
        buildPlan: buildProsePlan,
        promptGate1: async (p) => {
          gate1Prompts.push(p);
          return 'APPROVE';
        },
        promptGate2: async (p) => {
          gate2Prompts.push(p);
          return 'APPROVE';
        },
      });
      const planFileStr = fs.readFileSync(path.join(runDir, `plan-${res.planHash}.json`), 'utf8');
      const governanceFile = readJson(path.join(runDir, 'governance.json'));
      cap.approve = {
        res,
        planFileStr,
        fixture: normalize(
          {
            gate1Prompt: gate1Prompts[0],
            gate1PromptCount: gate1Prompts.length,
            gate2Prompt: gate2Prompts[0],
            gate2PromptCount: gate2Prompts.length,
            triageArtifact: readJson(path.join(runDir, `triage-${res.triageHash}.json`)),
            planFile: JSON.parse(planFileStr),
            gate1Record: readJson(path.join(runDir, 'gate1-record.json')),
            gate2Record: readJson(path.join(runDir, 'gate2-record.json')),
            governance: governanceFile,
            returnValue: { triageHash: res.triageHash, planHash: res.planHash },
            returnGovernanceMatchesFile:
              JSON.stringify(res.governanceRecord) === JSON.stringify(governanceFile),
            executionUnblocked:
              twoGate.validateExecutionState(runDir, res.triageHash, res.planHash) === true,
            blockedStamps: {
              unboundTriage: haltMessage(() =>
                twoGate.validateExecutionState(runDir, 'not-the-triage-hash', res.planHash),
              ),
              unboundPlan: haltMessage(() =>
                twoGate.validateExecutionState(runDir, res.triageHash, 'not-the-plan-hash'),
              ),
              missingGate1Record: haltMessage(() =>
                twoGate.validateExecutionState(emptyDir, res.triageHash, res.planHash),
              ),
            },
          },
          {
            runDirs: [runDir, emptyDir],
            hashes: { [res.triageHash]: '<TRIAGE_HASH>', [res.planHash]: '<PLAN_HASH>' },
          },
        ),
      };
    }

    // ── Scenario B: EDIT accepted once and RE-HASHED, plus the bounded-EDIT halt stamp ───
    {
      const runDir = tmpRunDir('edit');
      const capDir = tmpRunDir('edit-cap');
      runDirs.push(runDir, capDir);
      const presented = [];
      const decisions = ['EDIT', 'APPROVE'];
      const res = await twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir,
        buildPlan: buildProsePlan,
        promptGate1: async () => 'APPROVE',
        promptGate2: async (p) => {
          presented.push(p);
          return decisions.shift();
        },
        onEditedPlan: async (inputs) => ({ ...inputs, planProse: PROSE_V2 }),
      });
      const hashV1 = presented[0].planHash;
      const hashV2 = presented[1].planHash;

      const bounded = await haltOf(
        twoGate.runTwoGateMachine(INPUTS_V1, {
          runDir: capDir,
          maxEdits: 1,
          buildPlan: buildProsePlan,
          promptGate1: async () => 'APPROVE',
          promptGate2: async () => 'EDIT',
          onEditedPlan: async (inputs) => ({ ...inputs }),
        }),
        HaltError,
      );

      cap.edit = {
        res,
        hashV1,
        hashV2,
        fixture: normalize(
          {
            presentedPlanHashes: [hashV1, hashV2],
            presentedPlans: presented.map((p) => p.plan),
            planFilesWritten: {
              v1: fs.existsSync(path.join(runDir, `plan-${hashV1}.json`)),
              v2: fs.existsSync(path.join(runDir, `plan-${hashV2}.json`)),
            },
            gate2RecordFinal: readJson(path.join(runDir, 'gate2-record.json')),
            governance: readJson(path.join(runDir, 'governance.json')),
            returnPlanHash: res.planHash,
            editBoundedHalt: {
              haltError: bounded.haltError,
              message: bounded.message,
              haltRecord: readJson(path.join(capDir, 'HALT-RECORD.json')),
              governanceWritten: fs.existsSync(path.join(capDir, 'governance.json')),
            },
          },
          {
            runDirs: [runDir, capDir],
            hashes: {
              [res.triageHash]: '<TRIAGE_HASH>',
              [hashV1]: '<PLAN_HASH_V1>',
              [hashV2]: '<PLAN_HASH_V2>',
            },
          },
        ),
      };
    }

    // ── Scenario C: ABORT at each gate + no-response + blocked-execution stamps ──────────
    {
      const abort2Dir = tmpRunDir('abort2');
      const abort1Dir = tmpRunDir('abort1');
      const noRespDir = tmpRunDir('noresp');
      runDirs.push(abort2Dir, abort1Dir, noRespDir);

      const gate2Halt = await haltOf(
        twoGate.runTwoGateMachine(INPUTS_V1, {
          runDir: abort2Dir,
          buildPlan: buildProsePlan,
          promptGate1: async () => 'APPROVE',
          promptGate2: async () => 'ABORT',
        }),
        HaltError,
      );
      const gate1Rec = readJson(path.join(abort2Dir, 'gate1-record.json'));
      const gate2Rec = readJson(path.join(abort2Dir, 'gate2-record.json'));

      const gate1Halt = await haltOf(
        twoGate.runTwoGateMachine(INPUTS_V1, {
          runDir: abort1Dir,
          buildPlan: buildProsePlan,
          promptGate1: async () => 'ABORT',
          promptGate2: async () => 'APPROVE',
        }),
        HaltError,
      );

      const noRespHalt = await haltOf(
        twoGate.runTwoGateMachine(INPUTS_V1, {
          runDir: noRespDir,
          buildPlan: buildProsePlan,
          promptGate1: async () => 'APPROVE',
          promptGate2: async () => undefined,
        }),
        HaltError,
      );

      cap.abort = {
        fixture: normalize(
          {
            gate2Abort: {
              halt: gate2Halt,
              haltRecord: readJson(path.join(abort2Dir, 'HALT-RECORD.json')),
              gate2Record: gate2Rec,
              governanceWritten: fs.existsSync(path.join(abort2Dir, 'governance.json')),
              blockedExecutionStamp: haltMessage(() =>
                twoGate.validateExecutionState(abort2Dir, gate1Rec.triageHash, gate2Rec.planHash),
              ),
            },
            gate1Abort: {
              halt: gate1Halt,
              haltRecord: readJson(path.join(abort1Dir, 'HALT-RECORD.json')),
              gate1Record: readJson(path.join(abort1Dir, 'gate1-record.json')),
              gate2RecordWritten: fs.existsSync(path.join(abort1Dir, 'gate2-record.json')),
              governanceWritten: fs.existsSync(path.join(abort1Dir, 'governance.json')),
            },
            noResponseHalt: {
              halt: noRespHalt,
              governanceWritten: fs.existsSync(path.join(noRespDir, 'governance.json')),
            },
          },
          {
            runDirs: [abort2Dir, abort1Dir, noRespDir],
            hashes: { [gate1Rec.triageHash]: '<TRIAGE_HASH>', [gate2Rec.planHash]: '<PLAN_HASH>' },
          },
        ),
      };
    }

    // ── Scenario D: headless approvalProvider routes — identities + failure stamps ───────
    {
      const tokenDir = tmpRunDir('hl-token');
      const policyDir = tmpRunDir('hl-policy');
      const replayDir = tmpRunDir('hl-replay');
      const badTokenDir = tmpRunDir('hl-badtoken');
      const noGrantDir = tmpRunDir('hl-nogrant');
      const badProvDir = tmpRunDir('hl-badprov');
      const mismatchDir = tmpRunDir('hl-mismatch');
      runDirs.push(tokenDir, policyDir, replayDir, badTokenDir, noGrantDir, badProvDir, mismatchDir);

      const token = approval.issueDevToken(tokenDir, 'wave5-golden');
      const tokenRes = await twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir: tokenDir,
        buildPlan: buildProsePlan,
        approvalProvider: new approval.ApprovalProvider({ token, runDir: tokenDir, ttyAllowed: false }),
      });

      const policyRes = await twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir: policyDir,
        buildPlan: buildProsePlan,
        approvalProvider: new approval.ApprovalProvider({
          policyGrant: { identity: 'no-human-host' },
          runDir: policyDir,
          ttyAllowed: false,
        }),
      });

      const replayRes = await twoGate.runTwoGateMachine(INPUTS_V1, {
        runDir: replayDir,
        buildPlan: buildProsePlan,
        approvalProvider: new approval.ApprovalProvider({
          replayFixture: {
            provenance: 'replay',
            id: 'wave5-replay',
            triageHash: policyRes.triageHash,
            planHash: policyRes.planHash,
          },
          runDir: replayDir,
          ttyAllowed: false,
        }),
      });

      const invalidToken = await haltOf(
        twoGate.runTwoGateMachine(INPUTS_V1, {
          runDir: badTokenDir,
          buildPlan: buildProsePlan,
          approvalProvider: new approval.ApprovalProvider({
            token: 'garbage.not-a-signature',
            runDir: badTokenDir,
            ttyAllowed: false,
          }),
        }),
        HaltError,
      );
      const noGrant = await haltOf(
        twoGate.runTwoGateMachine(INPUTS_V1, {
          runDir: noGrantDir,
          buildPlan: buildProsePlan,
          approvalProvider: new approval.ApprovalProvider({ runDir: noGrantDir, ttyAllowed: false }),
        }),
        HaltError,
      );
      const badProvenance = await haltOf(
        twoGate.runTwoGateMachine(INPUTS_V1, {
          runDir: badProvDir,
          buildPlan: buildProsePlan,
          approvalProvider: new approval.ApprovalProvider({
            replayFixture: { provenance: 'not-replay', id: 'wave5-badprov' },
            runDir: badProvDir,
            ttyAllowed: false,
          }),
        }),
        HaltError,
      );
      const replayHashMismatch = await haltOf(
        twoGate.runTwoGateMachine(INPUTS_V1, {
          runDir: mismatchDir,
          buildPlan: buildProsePlan,
          approvalProvider: new approval.ApprovalProvider({
            replayFixture: {
              provenance: 'replay',
              id: 'wave5-bad',
              triageHash: policyRes.triageHash,
              planHash: 'not-the-real-plan-hash',
            },
            runDir: mismatchDir,
            ttyAllowed: false,
          }),
        }),
        HaltError,
      );

      cap.headless = {
        fixture: normalize(
          {
            token: { governance: readJson(path.join(tokenDir, 'governance.json')) },
            policyGrant: { governance: readJson(path.join(policyDir, 'governance.json')) },
            replay: {
              governance: readJson(path.join(replayDir, 'governance.json')),
              planHashMatchesPrior: replayRes.planHash === policyRes.planHash,
            },
            failureStamps: {
              invalidToken: {
                ...invalidToken,
                haltRecordWritten: fs.existsSync(path.join(badTokenDir, 'HALT-RECORD.json')),
              },
              noGrant: {
                ...noGrant,
                haltRecordWritten: fs.existsSync(path.join(noGrantDir, 'HALT-RECORD.json')),
              },
              badProvenance: {
                ...badProvenance,
                haltRecordWritten: fs.existsSync(path.join(badProvDir, 'HALT-RECORD.json')),
              },
              replayHashMismatch: {
                ...replayHashMismatch,
                haltRecordWritten: fs.existsSync(path.join(mismatchDir, 'HALT-RECORD.json')),
              },
            },
          },
          {
            runDirs: [tokenDir, policyDir, replayDir, badTokenDir, noGrantDir, badProvDir, mismatchDir],
            hashes: { [tokenRes.triageHash]: '<TRIAGE_HASH>', [tokenRes.planHash]: '<PLAN_HASH>' },
          },
        ),
      };
    }

    // ── Scenario E: researchPrime's OWN Phase-1 plan artifact through plan-gate.mjs ──────
    {
      const runDir = tmpRunDir('rp-phase1');
      runDirs.push(runDir);
      const presented = [];
      const res = await planGate.runPlanReviewGate(RP_INPUTS, {
        runDir,
        promptGate1: async () => 'APPROVE',
        promptGate2: async (p) => {
          presented.push(p);
          return 'APPROVE';
        },
      });
      const planFileStr = fs.readFileSync(path.join(runDir, `plan-${res.planHash}.json`), 'utf8');
      cap.rp = {
        res,
        planFileStr,
        fixture: normalize(
          {
            planVersionConstant: planGate.RESEARCH_PLAN_VERSION,
            presentedPlan: presented[0].plan,
            governance: readJson(path.join(runDir, 'governance.json')),
          },
          {
            runDirs: [runDir],
            hashes: { [res.triageHash]: '<TRIAGE_HASH>', [res.planHash]: '<PLAN_HASH>' },
          },
        ),
      };
    }
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  test('hash discipline: gate hashes are sha256 of the exact pinned serializations (formula pin)', () => {
    const planV1 = { planVersion: PLAN_VERSION, body: PROSE_V1 };
    const planV2 = { planVersion: PLAN_VERSION, body: PROSE_V2 };
    assert.equal(
      cap.approve.res.triageHash,
      sha256(JSON.stringify({ inputs: INPUTS_V1 }, null, 2)),
      'triageHash must be sha256 of the 2-space serialized { inputs } wrapper',
    );
    assert.equal(
      cap.approve.res.planHash,
      sha256(JSON.stringify(planV1, null, 2)),
      'planHash must be sha256 of the 2-space serialized plan object',
    );
    assert.equal(
      cap.approve.planFileStr,
      JSON.stringify(planV1, null, 2),
      'the persisted plan file must be the exact hashed bytes',
    );
    assert.equal(cap.edit.hashV1, cap.approve.res.planHash, 'EDIT flow presents the same V1 hash first');
    assert.equal(cap.edit.hashV2, sha256(JSON.stringify(planV2, null, 2)), 'EDIT re-hash formula');
    assert.notEqual(cap.edit.hashV1, cap.edit.hashV2, 'EDIT must produce a NEW plan hash');
    assert.equal(
      cap.rp.res.planHash,
      sha256(cap.rp.planFileStr),
      'the RP Phase-1 planHash must be sha256 of the persisted plan file bytes',
    );
  });

  test('golden: APPROVE-verbatim flow (records, prompt payloads, blocked-execution stamps)', () => {
    assertGolden('approve-verbatim.golden.json', cap.approve.fixture);
  });

  test('golden: EDIT re-hash flow + bounded-EDIT halt stamp', () => {
    assertGolden('edit-rehash.golden.json', cap.edit.fixture);
  });

  test('golden: ABORT at each gate, no-response halt, and blocked-execution stamps', () => {
    assertGolden('abort-and-blocked.golden.json', cap.abort.fixture);
  });

  test('golden: headless approvalProvider identities and failure stamps', () => {
    assertGolden('headless-providers.golden.json', cap.headless.fixture);
  });

  test('golden: researchPrime Phase-1 plan artifact (values AND serialization key order)', () => {
    assertGolden('rp-phase1-plan.golden.json', cap.rp.fixture);
    // Byte + key-order pin: the persisted plan file must equal the canonical 2-space
    // serialization of the PINNED fixture plan (JSON.parse preserves fixture key order, so
    // a reordered or re-serialized RP plan fails here even though deep-equality would pass).
    const golden = loadGolden('rp-phase1-plan.golden.json');
    assert.equal(
      cap.rp.planFileStr,
      JSON.stringify(golden.presentedPlan, null, 2),
      'RP Phase-1 plan file bytes must equal the pinned serialization (values and key order)',
    );
  });

  test('acceptance GWT: an intentionally perturbed gate output FAILS with a diff naming the changed output; the unperturbed run passes', () => {
    const name = 'approve-verbatim.golden.json';
    assert.deepStrictEqual(
      diffAgainstGolden(name, cap.approve.fixture),
      [],
      'the unperturbed capture must match its golden exactly',
    );

    // Perturbation 1: a changed value.
    const changed = structuredClone(cap.approve.fixture);
    changed.governance.gate2Decision = 'TAMPERED';
    const d1 = diffAgainstGolden(name, changed);
    assert.ok(d1.length >= 1, 'a perturbed output must fail the golden comparison');
    assert.ok(
      d1.some((d) => d.startsWith('governance.gate2Decision')),
      `diff must NAME the changed output; got:\n  ${d1.join('\n  ')}`,
    );

    // Perturbation 2: an injected new field.
    const injected = structuredClone(cap.approve.fixture);
    injected.gate2Record.injectedField = 'drifted';
    const d2 = diffAgainstGolden(name, injected);
    assert.ok(
      d2.some((d) => d.startsWith('gate2Record.injectedField')),
      `diff must name an injected field; got:\n  ${d2.join('\n  ')}`,
    );

    // Perturbation 3: a dropped field.
    const dropped = structuredClone(cap.approve.fixture);
    delete dropped.gate1Record.triageHash;
    const d3 = diffAgainstGolden(name, dropped);
    assert.ok(
      d3.some((d) => d.startsWith('gate1Record.triageHash')),
      `diff must name a dropped field; got:\n  ${d3.join('\n  ')}`,
    );

    // And the assertion helper itself surfaces the fixture name + the named path.
    assert.throws(
      () => {
        const diffs = diffAgainstGolden(name, changed);
        assert.equal(diffs.length, 0, `RP golden drift in ${name}:\n  ${diffs.join('\n  ')}`);
      },
      (err) => err.message.includes(name) && err.message.includes('governance.gate2Decision'),
    );
  });

  test('fence integrity: frozen RP files byte-unchanged; RP_GOLDEN_UPDATE not set in CI', () => {
    for (const f of FROZEN_FILES) {
      assert.equal(
        fileSha256(rpFile(f)),
        frozenHashesBefore[f],
        `${f} must be byte-identical before and after the golden suite (the fence observes, never edits)`,
      );
    }
    assert.equal(
      UPDATE,
      false,
      'RP_GOLDEN_UPDATE=1 regenerates fixtures and must NEVER pass CI — commit the fixtures and re-run without the flag',
    );
  });
});
