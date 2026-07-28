// test/wave4-intake.test.mjs
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { runIntake } from '../bin/intake.mjs';
import { HaltError } from '../bin/trio-core/contract-core.mjs';
import os from 'node:os';

test('Wave 4 - Stage-0 triage artifact emitted at intake before prompt (crash simulation)', async () => {
  const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-intake-test-'));
  
  const inputs = { query: 'test query 1' };

  let artifactPathFound = null;

  try {
    await runIntake(inputs, {
      runDir,
      onBeforePrompt: async ({ artifactPath }) => {
        // Assert the artifact exists on disk right now
        assert.ok(fs.existsSync(artifactPath), 'Artifact must exist on disk before prompt');
        artifactPathFound = artifactPath;
        // Simulate a crash/kill before prompting the human
        throw new Error('Simulated Crash');
      },
      promptHuman: async () => {
        assert.fail('Should not reach promptHuman if it crashes before');
      }
    });
  } catch (err) {
    assert.equal(err.message, 'Simulated Crash');
  }

  // The artifact should still be on disk
  assert.ok(artifactPathFound, 'Artifact path should have been passed to onBeforePrompt');
  assert.ok(fs.existsSync(artifactPathFound), 'Artifact must remain on disk after crash');
  
  const content = JSON.parse(fs.readFileSync(artifactPathFound, 'utf8'));
  assert.deepEqual(content.inputs, inputs, 'Artifact should contain the inputs');

  // cleanup
  fs.rmSync(runDir, { recursive: true, force: true });
});

test('Wave 4 - Human chooses ABORT at the very first opportunity', async () => {
  const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-intake-test-'));
  
  const inputs = { query: 'test query 2' };
  let artifactPathFound = null;

  try {
    await runIntake(inputs, {
      runDir,
      promptHuman: async ({ artifactPath }) => {
        artifactPathFound = artifactPath;
        return 'ABORT';
      }
    });
    assert.fail('runIntake should throw HaltError when ABORT is chosen');
  } catch (err) {
    assert.ok(err instanceof HaltError, 'Should throw HaltError on ABORT');
  }

  assert.ok(artifactPathFound, 'Artifact path should have been passed to promptHuman');
  assert.ok(fs.existsSync(artifactPathFound), 'Artifact must still exist on disk when ABORT is chosen');
  
  // also verify that the abort is recorded
  const recordPath = path.join(runDir, 'gate1-record.json');
  assert.ok(fs.existsSync(recordPath), 'Gate1 record must be written on ABORT');
  const record = JSON.parse(fs.readFileSync(recordPath, 'utf8'));
  assert.equal(record.gate1Decision, 'ABORT');

  // cleanup
  fs.rmSync(runDir, { recursive: true, force: true });
});
