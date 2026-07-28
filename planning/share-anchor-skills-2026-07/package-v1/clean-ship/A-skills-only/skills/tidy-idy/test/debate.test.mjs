import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { runDebate } from '../bin/debate.mjs';

describe('Debate Engine Unit Tests', () => {
  let tempDir;
  let intentFile;
  let file1;
  let file2;
  let file3;
  let nestedFile;

  before(async () => {
    // Setup temporary directory structure for project fixtures
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-debate-test-'));

    // Create INTENT.md
    intentFile = path.join(tempDir, 'INTENT.md');
    await fs.writeFile(intentFile, 'Objective: Maintain a clean project.');

    // Create test files
    file1 = path.join(tempDir, 'file1.js');
    await fs.writeFile(file1, 'console.log("file1");');

    file2 = path.join(tempDir, 'file2.js');
    await fs.writeFile(file2, 'console.log("file2");');

    file3 = path.join(tempDir, 'file3.js');
    await fs.writeFile(file3, 'console.log("file3");');

    // A nested file whose basename collides with nothing at the root —
    // used to prove exact relative-path matching (no basename fallback).
    await fs.mkdir(path.join(tempDir, 'sub'));
    nestedFile = path.join(tempDir, 'sub', 'util.js');
    await fs.writeFile(nestedFile, 'console.log("nested util");');
  });

  after(async () => {
    // Cleanup temporary directory structure
    if (tempDir) {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  });

  test('runs the single-pass debate (attacker-case then judge-decision) successfully', async () => {
    const agentsCalled = [];
    const mockAgent = async (prompt, opts) => {
      agentsCalled.push({ label: opts.label, prompt });
      if (opts.label === 'attacker-case') {
        return [
          { filepath: 'file1.js', case_for_removal: 'No real case — clearly used.', strength: 'none' },
          { filepath: 'file2.js', case_for_removal: 'Entirely unused artifact.', strength: 'strong' }
        ];
      }
      if (opts.label === 'judge-decision') {
        return [
          { filepath: 'file1.js', decision: 'RETAIN', rationale: 'Necessary' },
          { filepath: 'file2.js', decision: 'REMOVE', rationale: 'Unused' }
        ];
      }
      throw new Error(`Unexpected agent label: ${opts.label}`);
    };

    const suspects = [
      { filepath: file1, reason: 'Unused file 1' },
      { filepath: file2, reason: 'Unused file 2' }
    ];

    const results = await runDebate(tempDir, suspects, {
      agent: mockAgent,
      northStarFile: intentFile,
      chunkSize: 10
    });

    // Verify judgments are correctly mapped
    assert.strictEqual(results.length, 2);
    assert.strictEqual(results[0].filepath, file1);
    assert.strictEqual(results[0].decision, 'RETAIN');
    assert.strictEqual(results[1].filepath, file2);
    assert.strictEqual(results[1].decision, 'REMOVE');

    // Single pass: exactly TWO agent calls per chunk — attacker then judge.
    // No defender-round-*/attacker-round-* labels exist anymore.
    const labels = agentsCalled.map(a => a.label);
    assert.deepStrictEqual(labels, ['attacker-case', 'judge-decision']);
    assert.ok(labels.every(l => !/round/.test(l)));

    // Verify prompt content includes project configuration context
    assert.match(agentsCalled[0].prompt, /Objective: Maintain a clean project/);
    // The Judge sees the attacker's structured case
    assert.match(agentsCalled[1].prompt, /The Attacker's case per file/);
    assert.match(agentsCalled[1].prompt, /Entirely unused artifact/);
  });

  test('makes exactly two agent calls per chunk', async () => {
    const agentsCalled = [];
    const mockAgent = async (prompt, opts) => {
      agentsCalled.push({ label: opts.label, prompt });
      if (opts.label === 'judge-decision') {
        return [
          { filepath: 'file1.js', decision: 'RETAIN', rationale: 'Necessary' }
        ];
      }
      return [];
    };

    const suspects = [
      { filepath: file1, reason: 'Unused file 1' }
    ];

    await runDebate(tempDir, suspects, {
      agent: mockAgent,
      northStarFile: intentFile
    });

    const labels = agentsCalled.map(a => a.label);
    assert.deepStrictEqual(labels, ['attacker-case', 'judge-decision']);
  });

  test('chunks suspects into batches (min 5, max 10) and keeps judgments in chunk order despite concurrency', async () => {
    const agentsCalled = [];
    const mockAgent = async (prompt, opts) => {
      agentsCalled.push({ label: opts.label });
      if (opts.label === 'judge-decision') {
        // Capture the chunk's suspect reasons from the prompt
        const reasons = [...prompt.matchAll(/Reason for suspicion: (Suspect \d+)/g)].map(m => m[1]);
        const n = parseInt(reasons[0].replace('Suspect ', ''), 10);
        // Later chunks answer FASTER — output order must still be chunk order
        await new Promise(r => setTimeout(r, Math.max(0, (13 - n) * 10)));
        return [{ filepath: 'file1.js', decision: 'RETAIN', rationale: reasons[0] }];
      }
      return [];
    };

    // Create list of 12 suspects
    const suspects = [];
    for (let i = 1; i <= 12; i++) {
      suspects.push({ filepath: file1, reason: `Suspect ${i}` });
    }

    // Set chunk size to 5. 12 suspects / 5 per batch = 3 batches
    const results = await runDebate(tempDir, suspects, {
      agent: mockAgent,
      northStarFile: intentFile,
      chunkSize: 5
    });

    const judgeCalls = agentsCalled.filter(a => a.label === 'judge-decision');
    assert.strictEqual(judgeCalls.length, 3);
    assert.strictEqual(agentsCalled.filter(a => a.label === 'attacker-case').length, 3);

    // Chunk order preserved: chunk 1 = Suspects 1-5, chunk 2 = 6-10, chunk 3 = 11-12
    assert.strictEqual(results.length, 12);
    assert.strictEqual(results[0].rationale, 'Suspect 1');
    assert.strictEqual(results[5].rationale, 'Suspect 6');
    assert.strictEqual(results[10].rationale, 'Suspect 11');
  });

  test('safely defaults all files in the batch to RETAIN if Judge violates schema or throws', async () => {
    const mockAgentThrow = async (prompt, opts) => {
      if (opts.label === 'judge-decision') {
        throw new Error('LLM API Error');
      }
      return 'Arguments';
    };

    const suspects = [
      { filepath: file1, reason: 'Unused file 1' },
      { filepath: file2, reason: 'Unused file 2' }
    ];

    const resultsThrow = await runDebate(tempDir, suspects, {
      agent: mockAgentThrow,
      northStarFile: intentFile
    });

    assert.strictEqual(resultsThrow.length, 2);
    assert.strictEqual(resultsThrow[0].decision, 'RETAIN');
    assert.strictEqual(resultsThrow[0].rationale.includes('Schema violation'), true);
    assert.strictEqual(resultsThrow[1].decision, 'RETAIN');

    // Verify invalid schema structure defaults to RETAIN
    const mockAgentInvalid = async (prompt, opts) => {
      if (opts.label === 'judge-decision') {
        return { invalid: 'object structure' };
      }
      return 'Arguments';
    };

    const resultsInvalid = await runDebate(tempDir, suspects, {
      agent: mockAgentInvalid,
      northStarFile: intentFile
    });

    assert.strictEqual(resultsInvalid.length, 2);
    assert.strictEqual(resultsInvalid[0].decision, 'RETAIN');
    assert.strictEqual(resultsInvalid[1].decision, 'RETAIN');
  });

  test('exact relative-path matching only: a basename-only judge reply defaults that suspect to RETAIN', async () => {
    const mockAgent = async (prompt, opts) => {
      if (opts.label === 'judge-decision') {
        return [
          { filepath: 'file1.js', decision: 'REMOVE', rationale: 'Remove file1' },
          // Basename only — the retired fallback would have matched sub/util.js;
          // the safe behavior is NO match, so the suspect defaults to RETAIN.
          { filepath: 'util.js', decision: 'REMOVE', rationale: 'Remove util' }
        ];
      }
      return [];
    };

    const suspects = [
      { filepath: file1, reason: 'Unused file 1' },
      { filepath: nestedFile, reason: 'Unused nested util' }
    ];

    const results = await runDebate(tempDir, suspects, {
      agent: mockAgent,
      northStarFile: intentFile
    });

    assert.strictEqual(results.length, 2);
    assert.strictEqual(results[0].filepath, file1);
    assert.strictEqual(results[0].decision, 'REMOVE'); // exact match 'file1.js'
    assert.strictEqual(results[1].filepath, nestedFile);
    assert.strictEqual(results[1].decision, 'RETAIN'); // basename-only reply is not a match
    assert.match(results[1].rationale, /did not return an exact-path decision/);
  });

  test('defaults missed files in Judge output to RETAIN', async () => {
    const mockAgentMissed = async (prompt, opts) => {
      if (opts.label === 'judge-decision') {
        return [
          { filepath: 'file1.js', decision: 'REMOVE', rationale: 'Remove file1' }
        ];
      }
      return 'Arguments';
    };

    const suspects = [
      { filepath: file1, reason: 'Unused file 1' },
      { filepath: file2, reason: 'Unused file 2' }
    ];

    const results = await runDebate(tempDir, suspects, {
      agent: mockAgentMissed,
      northStarFile: intentFile
    });

    assert.strictEqual(results.length, 2);
    assert.strictEqual(results[0].filepath, file1);
    assert.strictEqual(results[0].decision, 'REMOVE');
    assert.strictEqual(results[1].filepath, file2);
    assert.strictEqual(results[1].decision, 'RETAIN');
    assert.match(results[1].rationale, /did not return an exact-path decision/);
  });
});
