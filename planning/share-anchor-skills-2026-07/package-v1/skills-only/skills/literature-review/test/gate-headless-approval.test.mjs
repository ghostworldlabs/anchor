// test/gate-headless-approval.test.mjs — Wave 1 headless approvalProvider conformance.
//
// Empirical claim under test: researchPrime's frozen gate resolves a decision through EACH of
// the three headless approvalProvider routes — signed token, explicit policy grant, and a
// replayed prior decision — WITHOUT any hard isTTY halt on the Node path, and emits the
// hash-bound governance record. Every run here sets `ttyAllowed: false`, making the TTY route
// unreachable, so a pass PROVES the decision came from the headless route (the asserted
// hostApprovalProvider identity string names which one).
//
// The NON-Node path cannot be executed under `node --test` (it is by definition the path taken
// on a host without Node). Its contract is the documented prose stamp in researchPrime's
// SKILL.md; the final test pins that documented stamp text so drift in the non-Node contract
// still fails this suite. Stamp: that assertion is doc-anchored, not an execution of a
// non-Node host.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { rpFile, importRp, fileSha256 } from './_wave1-trio-resolve.mjs';

const PROSE = [
  '# Research Plan — headless-approval spike (Wave 1)',
  '',
  'Scope: exercise the token / policy-grant / replay approval routes with no human channel.',
].join('\n');

// Pure function of inputs — deterministic planHash, which the replay route depends on.
function buildProsePlan({ inputs }) {
  return { planVersion: 'litreview-brownfield-plan/prose-spike-1', body: inputs.planProse };
}

const INPUTS = Object.freeze({
  objective: 'Wave-1 headless approval spike (literature-review)',
  planProse: PROSE,
});

function tmpRunDir(tag) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `litrev-w1-headless-${tag}-`));
}

describe('Wave 1 — headless approvalProvider (token / policy-grant / replay, no isTTY halt)', () => {
  const runDirs = [];
  let twoGate;
  let approval; // { ApprovalProvider, issueDevToken }
  let HaltError;
  let gateHashesBefore = {};

  before(async () => {
    for (const f of ['bin/plan-gate.mjs', 'bin/two-gate.mjs']) gateHashesBefore[f] = fileSha256(rpFile(f));
    twoGate = await importRp('bin/two-gate.mjs');
    approval = await importRp('bin/approval-provider.mjs');
    ({ HaltError } = await importRp('bin/trio-core/contract-core.mjs'));
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
    // The suite itself must never have touched the frozen gate files.
    for (const [f, h] of Object.entries(gateHashesBefore)) {
      assert.equal(fileSha256(rpFile(f)), h, `${f} byte-hash changed during headless suite`);
    }
  });

  test('signed-token route resolves headlessly to a hash-bound governance record', async () => {
    const runDir = tmpRunDir('token');
    runDirs.push(runDir);
    const token = approval.issueDevToken(runDir, 'wave1-headless');
    const provider = new approval.ApprovalProvider({ token, runDir, ttyAllowed: false });

    const res = await twoGate.runTwoGateMachine(INPUTS, {
      runDir,
      approvalProvider: provider,
      buildPlan: buildProsePlan,
    });

    assert.equal(res.governanceRecord.hostApprovalProvider, 'Token:wave1-headless');
    const gov = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.equal(gov.planHash, res.planHash, 'governance record must be hash-bound to the plan');
    assert.equal(gov.triageHash, res.triageHash);
    assert.equal(gov.gate2Decision, 'APPROVE');
  });

  test('policy-grant route (explicit no-human-channel grant) resolves headlessly', async () => {
    const runDir = tmpRunDir('policy');
    runDirs.push(runDir);
    const provider = new approval.ApprovalProvider({
      policyGrant: { identity: 'no-human-host' },
      runDir,
      ttyAllowed: false,
    });

    const res = await twoGate.runTwoGateMachine(INPUTS, {
      runDir,
      approvalProvider: provider,
      buildPlan: buildProsePlan,
    });

    assert.equal(res.governanceRecord.hostApprovalProvider, 'PolicyGrant:no-human-host');
    assert.ok(fs.existsSync(path.join(runDir, 'governance.json')));
  });

  test('replay route: a replayed prior decision resolves when hash-bound, halts on mismatch', async () => {
    // First, a policy-grant run captures the deterministic triage/plan hashes to replay.
    const priorDir = tmpRunDir('replay-prior');
    runDirs.push(priorDir);
    const prior = await twoGate.runTwoGateMachine(INPUTS, {
      runDir: priorDir,
      approvalProvider: new approval.ApprovalProvider({
        policyGrant: { identity: 'no-human-host' },
        runDir: priorDir,
        ttyAllowed: false,
      }),
      buildPlan: buildProsePlan,
    });

    // Replay the recorded decision against a FRESH run of the same frozen inputs.
    const replayDir = tmpRunDir('replay');
    runDirs.push(replayDir);
    const res = await twoGate.runTwoGateMachine(INPUTS, {
      runDir: replayDir,
      approvalProvider: new approval.ApprovalProvider({
        replayFixture: {
          provenance: 'replay',
          id: 'wave1-replay',
          triageHash: prior.triageHash,
          planHash: prior.planHash,
        },
        runDir: replayDir,
        ttyAllowed: false,
      }),
      buildPlan: buildProsePlan,
    });
    assert.equal(res.governanceRecord.hostApprovalProvider, 'ReplayFixture:wave1-replay');
    assert.equal(res.planHash, prior.planHash, 'replay binds to the identical deterministic plan hash');

    // A replay fixture whose hashes do not match the current run is refused (hash binding is real).
    const badDir = tmpRunDir('replay-bad');
    runDirs.push(badDir);
    await assert.rejects(
      twoGate.runTwoGateMachine(INPUTS, {
        runDir: badDir,
        approvalProvider: new approval.ApprovalProvider({
          replayFixture: {
            provenance: 'replay',
            id: 'wave1-bad',
            triageHash: prior.triageHash,
            planHash: 'not-the-real-plan-hash',
          },
          runDir: badDir,
          ttyAllowed: false,
        }),
        buildPlan: buildProsePlan,
      }),
      (err) => err instanceof HaltError && /Replay fixture hashes do not match current run/.test(err.message),
    );
  });

  test('no hard isTTY halt: failure modes are clean per-run HaltErrors, never a TTY requirement', async () => {
    // Invalid token → a named HaltError about the token, not about a missing TTY.
    const badTokenDir = tmpRunDir('badtoken');
    runDirs.push(badTokenDir);
    await assert.rejects(
      twoGate.runTwoGateMachine(INPUTS, {
        runDir: badTokenDir,
        approvalProvider: new approval.ApprovalProvider({
          token: 'garbage.not-a-signature',
          runDir: badTokenDir,
          ttyAllowed: false,
        }),
        buildPlan: buildProsePlan,
      }),
      (err) => err instanceof HaltError && /Invalid or expired signed approval token/.test(err.message),
    );

    // No route at all → the documented per-run halt naming the missing grant (isTTY is never
    // consulted because ttyAllowed:false removes the TTY route entirely).
    const noneDir = tmpRunDir('none');
    runDirs.push(noneDir);
    await assert.rejects(
      twoGate.runTwoGateMachine(INPUTS, {
        runDir: noneDir,
        approvalProvider: new approval.ApprovalProvider({ runDir: noneDir, ttyAllowed: false }),
        buildPlan: buildProsePlan,
      }),
      (err) =>
        err instanceof HaltError &&
        /No valid approval provider grant \(no human channel, no token\)/.test(err.message),
    );
  });

  test('non-Node path contract: the documented prose stamp is pinned in researchPrime SKILL.md', () => {
    // Doc-anchored assertion (the non-Node path cannot execute under node --test): the SKILL.md
    // prose-gate contract must keep both the prose fallback and its literal stamp text.
    const skillMd = fs.readFileSync(rpFile('SKILL.md'), 'utf8');
    assert.match(skillMd, /On a host without Node/i);
    assert.ok(
      skillMd.includes('plan-gate: prose, not hash-bound'),
      'researchPrime SKILL.md must document the non-Node prose stamp "plan-gate: prose, not hash-bound"',
    );
  });
});
