import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { ApprovalProvider } from '../bin/approval-provider.mjs';
import { runTwoGateMachine } from '../bin/two-gate.mjs';
import { HaltError } from '../bin/trio-core/contract-core.mjs';
import crypto from 'node:crypto';

describe('Wave 8 — Replay-bound approval fixtures', () => {
  let tempDir;

  before(() => {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-w8-'));
  });

  after(() => {
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  test('Valid replay fixture bound to run A satisfies the gate', async () => {
    const runDir = path.join(tempDir, 'run-replay-a');
    fs.mkdirSync(runDir, { recursive: true });

    // We will generate the triageHash and planHash first, or just let runTwoGateMachine run, but
    // a replay fixture must exist ahead of time with the EXACT hashes.
    // However, runTwoGateMachine determines the hashes internally during execution,
    // so we can use a mock onEditedScope/promptGate1 to force specific hashes, OR
    // just intercept and pre-calculate them. 
    // Intake hash:
    const inputs = { query: 'objective A' };
    
    // We need to know the hashes to create the fixture.
    // Let's create a minimal provider that intercepts or we just let it run once, capture hashes, and replay.
    // To make it simple, we use a custom test harness:
    let actualTriageHash = '';
    let actualPlanHash = '';
    
    // First run with TTY to capture hashes
    try {
      await runTwoGateMachine(inputs, { 
        runDir, 
        promptGate1: async (intake) => { actualTriageHash = intake.triageHash; return 'APPROVE'; },
        promptGate2: async ({ planHash }) => { actualPlanHash = planHash; return 'APPROVE'; },
        approvalProvider: new ApprovalProvider({ ttyAllowed: true, runDir })
      });
    } catch(e) { }
    
    // Now we have the hashes for A.
    const fixtureA = {
      provenance: 'replay',
      triageHash: actualTriageHash,
      planHash: actualPlanHash
    };

    const providerA = new ApprovalProvider({ replayFixture: fixtureA, runDir });
    const inputsA = { query: 'objective A' };
    
    const result = await runTwoGateMachine(inputsA, { runDir, approvalProvider: providerA });
    assert.equal(result.triageHash, actualTriageHash);
    assert.equal(result.planHash, actualPlanHash);
    
    const govRecord = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.ok(govRecord.hostApprovalProvider.startsWith('ReplayFixture'));
  });

  test('Replay fixture bound to run A is rejected for run B', async () => {
    const runDirA = path.join(tempDir, 'run-a2');
    fs.mkdirSync(runDirA, { recursive: true });
    
    let actualTriageHashA = '';
    let actualPlanHashA = '';
    await runTwoGateMachine({ query: 'objective A2' }, { 
      runDir: runDirA, 
      promptGate1: async (intake) => { actualTriageHashA = intake.triageHash; return 'APPROVE'; },
      promptGate2: async ({ planHash }) => { actualPlanHashA = planHash; return 'APPROVE'; },
      approvalProvider: new ApprovalProvider({ ttyAllowed: true, runDir: runDirA })
    });

    const fixtureA = {
      provenance: 'replay',
      triageHash: actualTriageHashA,
      planHash: actualPlanHashA
    };

    const runDirB = path.join(tempDir, 'run-b');
    fs.mkdirSync(runDirB, { recursive: true });
    
    const providerB = new ApprovalProvider({ replayFixture: fixtureA, runDir: runDirB });
    const inputsB = { query: 'objective B' }; // Different objective -> different planHash
    
    await assert.rejects(
      async () => await runTwoGateMachine(inputsB, { runDir: runDirB, approvalProvider: providerB }),
      (err) => err instanceof HaltError && err.message.includes('Replay fixture hashes do not match')
    );
  });
});
