import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { ApprovalProvider, issueDevToken, validateDevToken } from '../bin/approval-provider.mjs';
import { runTwoGateMachine } from '../bin/two-gate.mjs';
import { HaltError } from '../bin/trio-core/contract-core.mjs';

describe('Wave 7 — Approval-provider interface', () => {
  let tempDir;

  before(() => {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-w7-'));
  });

  after(() => {
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  test('Valid pre-authorized signed approval token satisfies the gate and records identity', async () => {
    const runDir = path.join(tempDir, 'run-token');
    fs.mkdirSync(runDir, { recursive: true });

    const token = issueDevToken(runDir, 'dev-alice');
    const provider = new ApprovalProvider({ token, ttyAllowed: false, runDir });
    
    const inputs = { query: 'test objective token' };
    const result = await runTwoGateMachine(inputs, { runDir, approvalProvider: provider });

    const govRecord = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.equal(govRecord.hostApprovalProvider, 'Token:dev-alice');
    assert.equal(govRecord.gate1Decision, 'APPROVE');
    assert.equal(govRecord.gate2Decision, 'APPROVE');
  });

  test('--dev-approve issues a real signed token and validates it at the gate', async () => {
    const runDir = path.join(tempDir, 'run-dev-approve');
    fs.mkdirSync(runDir, { recursive: true });

    // Issue the token
    const token = issueDevToken(runDir, 'dev-bob');
    assert.equal(validateDevToken(token, runDir), 'dev-bob');

    // Use it at the gate
    const provider = new ApprovalProvider({ token, ttyAllowed: false, runDir });
    const inputs = { query: 'test objective dev-approve' };
    const result = await runTwoGateMachine(inputs, { runDir, approvalProvider: provider });

    const govRecord = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.equal(govRecord.hostApprovalProvider, 'Token:dev-bob');
  });

  test('Policy grant satisfies the gate and records identity', async () => {
    const runDir = path.join(tempDir, 'run-policy');
    fs.mkdirSync(runDir, { recursive: true });

    const provider = new ApprovalProvider({ policyGrant: { identity: 'ci-runner' }, ttyAllowed: false, runDir });
    const inputs = { query: 'test objective policy' };
    const result = await runTwoGateMachine(inputs, { runDir, approvalProvider: provider });

    const govRecord = JSON.parse(fs.readFileSync(path.join(runDir, 'governance.json'), 'utf8'));
    assert.equal(govRecord.hostApprovalProvider, 'PolicyGrant:ci-runner');
  });

  test('Absence of valid artifact/grant HALTs only that run', async () => {
    const runDir = path.join(tempDir, 'run-halt');
    fs.mkdirSync(runDir, { recursive: true });

    const provider = new ApprovalProvider({ ttyAllowed: false, runDir });
    const inputs = { query: 'test objective halt' };

    await assert.rejects(
      async () => await runTwoGateMachine(inputs, { runDir, approvalProvider: provider }),
      (err) => err instanceof HaltError && err.message.includes('No valid approval provider grant')
    );
  });
});
