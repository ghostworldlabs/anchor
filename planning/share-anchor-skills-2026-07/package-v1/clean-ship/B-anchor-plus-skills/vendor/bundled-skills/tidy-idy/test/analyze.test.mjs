import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { runAnalysis } from '../bin/analyze.mjs';

describe('Batch Analysis Unit Tests (Mocked)', () => {
  let tempDir;
  let goodFilePath;
  let obsoleteFilePath;
  let outsideFilePath;
  let intentFilePath;

  before(async () => {
    // Create temp directory for project fixture
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-analyze-test-'));

    // Create INTENT.md
    intentFilePath = path.join(tempDir, 'INTENT.md');
    await fs.writeFile(intentFilePath, 'Core Objective: Maintain a lean, clean repository of helper utilities.');

    // Create a good file (aligned with North Star)
    const binDir = path.join(tempDir, 'bin');
    await fs.mkdir(binDir);
    goodFilePath = path.join(binDir, 'good.js');
    await fs.writeFile(goodFilePath, 'export function help() { return "helpful utility"; }');

    // Create an obsolete/suspect file
    obsoleteFilePath = path.join(binDir, 'obsolete.js');
    await fs.writeFile(obsoleteFilePath, 'export function legacyGarbage() { return "distraction"; }');

    // Create a file outside the project directory
    outsideFilePath = path.join(os.tmpdir(), 'outside-file-test.js');
    await fs.writeFile(outsideFilePath, 'console.log("malicious or irrelevant file outside project");');

    // Create hidden files and directories to verify they are ignored
    const hiddenDir = path.join(tempDir, '.git');
    await fs.mkdir(hiddenDir);
    await fs.writeFile(path.join(hiddenDir, 'config'), 'git config data');

    const nodeModulesDir = path.join(tempDir, 'node_modules');
    await fs.mkdir(nodeModulesDir);
    await fs.writeFile(path.join(nodeModulesDir, 'package.json'), '{}');
  });

  after(async () => {
    // Cleanup temporary files and directories
    if (tempDir) {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
    try {
      await fs.unlink(outsideFilePath);
    } catch {}
  });

  test('successfully discovers files and targets suspect assets returned by LLM agent', async () => {
    let capturedPrompt = '';
    let capturedLabel = '';
    const mockAgent = async (prompt, opts) => {
      capturedPrompt = prompt;
      capturedLabel = opts.label;
      return [
        { filepath: 'bin/obsolete.js', reason: 'Unused legacy garbage' },
        { filepath: 'bin/nonexistent.js', reason: 'Non-existent file' },
        { filepath: outsideFilePath, reason: 'File outside project path' }
      ];
    };

    const suspects = await runAnalysis(tempDir, {
      agent: mockAgent,
      northStarFile: intentFilePath,
      throwOnError: true
    });

    // Assertions on the returned suspects
    // It should filter out nonexistent file and file outside the project path
    assert.strictEqual(suspects.length, 1);
    assert.strictEqual(suspects[0].filepath, path.resolve(obsoleteFilePath));
    assert.strictEqual(suspects[0].reason, 'Unused legacy garbage');

    // Small project fits in one batch: label is hygiene-analysis-b1
    assert.strictEqual(capturedLabel, 'hygiene-analysis-b1');

    // Assert that the compiled prompt contains files and North Star info
    assert.match(capturedPrompt, /Core Objective: Maintain a lean/);
    assert.match(capturedPrompt, /bin[\\\/]good\.js/);
    assert.match(capturedPrompt, /bin[\\\/]obsolete\.js/);

    // The prompt no longer claims a Gandalf persona
    assert.doesNotMatch(capturedPrompt, /Gandalf persona/);

    // Assert that it ignored hidden files and node_modules
    assert.doesNotMatch(capturedPrompt, /\.git[\\\/]config/);
    assert.doesNotMatch(capturedPrompt, /node_modules/);
  });

  test('batches file content (~200KB per agent call) with hygiene-analysis-b<N> labels', async () => {
    const bigDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-analyze-batch-'));
    try {
      const bigIntent = path.join(bigDir, 'INTENT.md');
      await fs.writeFile(bigIntent, 'Core Objective: exercise analysis batching.');
      // Two ~150KB files cannot share one ~200KB batch => exactly 2 agent calls
      await fs.writeFile(path.join(bigDir, 'big1.txt'), 'a'.repeat(150 * 1024));
      await fs.writeFile(path.join(bigDir, 'big2.txt'), 'b'.repeat(150 * 1024));

      const labels = [];
      const mockAgent = async (prompt, opts) => {
        labels.push(opts.label);
        return [];
      };

      const suspects = await runAnalysis(bigDir, {
        agent: mockAgent,
        northStarFile: bigIntent,
        throwOnError: true
      });

      assert.deepStrictEqual(suspects, []);
      assert.deepStrictEqual(labels, ['hygiene-analysis-b1', 'hygiene-analysis-b2']);
    } finally {
      await fs.rm(bigDir, { recursive: true, force: true });
    }
  });

  test('handles clean projects with no suspects gracefully', async () => {
    const mockAgent = async (prompt, opts) => {
      return [];
    };

    const suspects = await runAnalysis(tempDir, {
      agent: mockAgent,
      northStarFile: intentFilePath,
      throwOnError: true
    });

    assert.deepStrictEqual(suspects, []);
  });

  test('throws when the agent returns a non-array — the analysis did NOT run (throwOnError: true)', async () => {
    const nonArrayAgent = async (prompt, opts) => 'I refuse to emit the JSON array';

    await assert.rejects(
      runAnalysis(tempDir, {
        agent: nonArrayAgent,
        northStarFile: intentFilePath,
        throwOnError: true
      }),
      /the analysis did NOT run/
    );
  });

  test('non-array agent output with throwOnError falsy is caught by the outer handler and returns []', async () => {
    let logMessage = '';
    const nonArrayAgent = async (prompt, opts) => ({ not: 'an array' });

    const suspects = await runAnalysis(tempDir, {
      agent: nonArrayAgent,
      northStarFile: intentFilePath,
      log: (msg) => { logMessage = msg; }
    });

    assert.deepStrictEqual(suspects, []);
    assert.match(logMessage, /Analysis failed for/);
  });

  test('returns empty array and logs error on failed agent execution if throwOnError is false', async () => {
    let logMessage = '';
    const badAgent = async (prompt, opts) => {
      throw new Error('LLM rate limit reached');
    };

    const suspects = await runAnalysis(tempDir, {
      agent: badAgent,
      northStarFile: intentFilePath,
      throwOnError: false,
      log: (msg) => { logMessage = msg; }
    });

    assert.deepStrictEqual(suspects, []);
    assert.match(logMessage, /Analysis failed for/);
  });

  test('throws error on failed agent execution if throwOnError is true', async () => {
    const badAgent = async (prompt, opts) => {
      throw new Error('LLM api error');
    };

    await assert.rejects(
      runAnalysis(tempDir, {
        agent: badAgent,
        northStarFile: intentFilePath,
        throwOnError: true
      }),
      /LLM api error/
    );
  });
});
