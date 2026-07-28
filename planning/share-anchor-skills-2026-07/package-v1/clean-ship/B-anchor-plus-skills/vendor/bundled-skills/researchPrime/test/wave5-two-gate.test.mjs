import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import { runTwoGateMachine, validateExecutionState } from '../bin/two-gate.mjs';
import { HaltError } from '../bin/trio-core/contract-core.mjs';

test('Wave 5 — Two-gate approval state machine with hash-bound decisions and bounded EDIT', async (t) => {

  await t.test('A run reaches execution only after two recorded, hash-bound APPROVE decisions', async () => {
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-w5-'));
    
    const inputs = { query: 'test objective 1' };
    
    const result = await runTwoGateMachine(inputs, {
      runDir,
      promptGate1: async () => 'APPROVE',
      promptGate2: async () => 'APPROVE'
    });
    
    assert.ok(result.triageHash);
    assert.ok(result.planHash);
    assert.equal(result.governanceRecord.gate1Decision, 'APPROVE');
    assert.equal(result.governanceRecord.gate2Decision, 'APPROVE');
    
    assert.doesNotThrow(() => validateExecutionState(runDir, result.triageHash, result.planHash));
    
    fs.rmSync(runDir, { recursive: true, force: true });
  });

  await t.test('A run with a Gate-1 APPROVE but no Gate-2 decision refuses to reach rounds', async () => {
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-w5-'));
    
    // Simulate Gate 1 APPROVE
    fs.writeFileSync(path.join(runDir, 'gate1-record.json'), JSON.stringify({
      triageHash: 'mock-triage-hash',
      gate1Decision: 'APPROVE'
    }));
    
    // Validate missing Gate 2
    assert.throws(
      () => validateExecutionState(runDir, 'mock-triage-hash', 'mock-plan-hash'),
      /Gate 2 record missing/
    );
    
    fs.rmSync(runDir, { recursive: true, force: true });
  });

  await t.test('A human who EDITs the plan at Gate 2 causes re-run and fresh hash-bound approval', async () => {
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-w5-'));
    
    const inputs = { query: 'test objective 2' };
    
    let gate2Count = 0;
    const planHashes = [];
    
    await runTwoGateMachine(inputs, {
      runDir,
      promptGate1: async () => 'APPROVE',
      promptGate2: async ({ planHash }) => {
        gate2Count++;
        planHashes.push(planHash);
        if (gate2Count === 1) return 'EDIT';
        return 'APPROVE';
      },
      onEditedPlan: async (inp) => {
        return { ...inp, query: inp.query + ' edited' };
      }
    });
    
    assert.equal(gate2Count, 2, 'Gate 2 should have been prompted twice');
    assert.notEqual(planHashes[0], planHashes[1], 'Plan hash should change after edit');
    
    const gate2Record = JSON.parse(fs.readFileSync(path.join(runDir, 'gate2-record.json'), 'utf8'));
    assert.equal(gate2Record.planHash, planHashes[1], 'Gate 2 record should bind to the edited plan hash');
    assert.equal(gate2Record.gate2Decision, 'APPROVE');
    
    fs.rmSync(runDir, { recursive: true, force: true });
  });

  await t.test('A Gate-1 approval whose recorded hash does not match current triage artifact is rejected', async () => {
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-w5-'));
    
    fs.writeFileSync(path.join(runDir, 'gate1-record.json'), JSON.stringify({
      triageHash: 'old-triage-hash',
      gate1Decision: 'APPROVE'
    }));
    fs.writeFileSync(path.join(runDir, 'gate2-record.json'), JSON.stringify({
      planHash: 'mock-plan-hash',
      gate2Decision: 'APPROVE'
    }));
    
    // Provide a mismatched triage hash
    assert.throws(
      () => validateExecutionState(runDir, 'current-triage-hash', 'mock-plan-hash'),
      /Gate 1 approval not bound to current triage artifact hash/
    );
    
    fs.rmSync(runDir, { recursive: true, force: true });
  });

  await t.test('Execution blocked if a decision is not APPROVE', async () => {
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-w5-'));
    
    fs.writeFileSync(path.join(runDir, 'gate1-record.json'), JSON.stringify({
      triageHash: 'thash',
      gate1Decision: 'EDIT'
    }));
    fs.writeFileSync(path.join(runDir, 'gate2-record.json'), JSON.stringify({
      planHash: 'phash',
      gate2Decision: 'APPROVE'
    }));
    
    assert.throws(
      () => validateExecutionState(runDir, 'thash', 'phash'),
      /Gate 1 decision is EDIT, expected APPROVE/
    );
    
    fs.rmSync(runDir, { recursive: true, force: true });
  });
  
});
