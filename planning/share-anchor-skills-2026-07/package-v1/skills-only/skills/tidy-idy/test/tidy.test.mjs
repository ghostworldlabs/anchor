import { test, describe, before, after, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { Readable, Writable } from 'node:stream';
import { runOrchestration } from '../bin/tidy.mjs';

function createMockStreams(inputs = []) {
  const stdin = Readable.from(inputs);
  let stdoutData = '';
  const stdout = new Writable({
    write(chunk, encoding, callback) {
      stdoutData += chunk.toString();
      callback();
    }
  });
  return {
    stdin,
    stdout,
    getStdout: () => stdoutData
  };
}

const createGitMock = (responses) => {
  return async (cmd) => {
    for (const key of Object.keys(responses)) {
      if (cmd.includes(key)) {
        const resp = responses[key];
        if (resp.error) {
          throw new Error(resp.error);
        }
        return { stdout: resp.stdout, stderr: resp.stderr || '' };
      }
    }
    throw new Error(`Unmocked command: ${cmd}`);
  };
};

describe('Orchestrator Unit Tests', () => {
  let tempDir;

  before(async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-tidy-test-'));
  });

  after(async () => {
    if (tempDir) {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  });

  describe('Single-project full pipeline execution', () => {
    let projectDir;
    let file1;
    let file2;
    let agentPath;
    let historyPath;
    let stateDir;

    beforeEach(async () => {
      // 1. Create a mock project
      projectDir = await fs.mkdtemp(path.join(tempDir, 'proj-'));

      // Create North Star / INTENT.md
      await fs.writeFile(path.join(projectDir, 'INTENT.md'), 'Objective: Maintain clean utilities.');

      // Create some test files
      file1 = path.join(projectDir, 'utility1.js');
      await fs.writeFile(file1, 'console.log("utility1");');

      file2 = path.join(projectDir, 'obsolete.js');
      await fs.writeFile(file2, 'console.log("obsolete");');

      // Create agent.md and agent_hist.md
      agentPath = path.join(projectDir, 'agent.md');
      await fs.writeFile(agentPath, 'Goal: Clean code.\nDetails about minor task to be archived.\nAnother line of details.');

      historyPath = path.join(projectDir, 'agent_hist.md');
      await fs.writeFile(historyPath, 'History log line 1.');

      // State now lives INSIDE the target dir (not the CWD)
      stateDir = path.join(projectDir, '.tidy-idy');
    });

    afterEach(async () => {
      await fs.rm(projectDir, { recursive: true, force: true }).catch(() => {});
    });

    test('orchestrates all waves successfully on a clean repo', async () => {
      // Git is clean
      const gitMock = createGitMock({
        'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
        'git status --porcelain': { stdout: '' },
        'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
        'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
        'git cherry': { stdout: '' },
        'git rev-parse --short HEAD': { stdout: 'abc1234\n' },
        'git add -A': { stdout: '' },
        'git commit': { stdout: '' }
      });

      // Mock agent for batched analysis, single-pass debate, and compression
      const mockAgent = async (prompt, opts) => {
        if (opts.label && opts.label.startsWith('hygiene-analysis-b')) {
          // Identify obsolete.js as suspect
          return [
            { filepath: 'obsolete.js', reason: 'obsolete file' }
          ];
        }
        if (opts.label === 'attacker-case') {
          return [
            { filepath: 'obsolete.js', case_for_removal: 'obsolete', strength: 'strong' }
          ];
        }
        if (opts.label === 'judge-decision') {
          // Judge decides to REMOVE obsolete.js
          return [
            { filepath: 'obsolete.js', decision: 'REMOVE', rationale: 'It is obsolete' }
          ];
        }
        if (opts.label === 'compress-agent') {
          return {
            executiveSummary: 'Goal: Clean code.',
            historyToAppend: 'Archived detail.'
          };
        }
        return null;
      };

      const { stdin, stdout, getStdout } = createMockStreams([]);

      const result = await runOrchestration(projectDir, {
        exec: gitMock,
        captureRuns: false,
        agent: mockAgent,
        stdin,
        stdout,
        interactive: false,
        throwOnError: true
      });

      // New return shape: { projects, removed, protectedSkips, skipped, failed, compression }
      assert.strictEqual(result.projects.length, 1);
      assert.ok(!('archived' in result));
      assert.ok(!('deleted' in result));
      assert.ok(Array.isArray(result.removed));
      assert.ok(Array.isArray(result.protectedSkips));
      assert.strictEqual(result.failed.length, 0);
      assert.strictEqual(result.compression.length, 1);
      assert.strictEqual(result.compression[0].agentCompressed, true);

      // END-TO-END REMOVAL: the debate's REMOVE `decision` flows through
      // runRemoval (which accepts decision|verdict — the field mismatch the
      // test-adaptation pass caught before it shipped a tool that never removed
      // anything) and the file is deleted, with the commit hash reported.
      assert.strictEqual(result.removed.length, 1);
      assert.match(result.removed[0].filepath, /obsolete\.js/);
      assert.strictEqual(result.removed[0].commit, 'abc1234');
      assert.strictEqual(result.skipped.length, 0);
      await assert.rejects(fs.access(file2), 'obsolete.js was removed from disk');

      // Verify context compression updated files
      const agentContent = await fs.readFile(agentPath, 'utf8');
      assert.strictEqual(agentContent.trim(), 'Goal: Clean code.');

      const historyContent = await fs.readFile(historyPath, 'utf8');
      assert.strictEqual(historyContent.trim(), 'History log line 1.\nArchived detail.');

      // Verify structured report output (new section names)
      const report = getStdout();
      assert.match(report, /# tidy-idy Hygiene Report/);
      assert.match(report, /## Operations Summary/);
      assert.match(report, /### Removed \(recovery: git revert the named commit\)/);
      assert.match(report, /### Protected skips/);
      assert.match(report, /### Other skips/);
      assert.match(report, /### Projects skipped \(error\/refusal\)/);

      // Verify state files exist INSIDE the target dir
      const projectsJson = JSON.parse(await fs.readFile(path.join(stateDir, 'projects.json'), 'utf8'));
      assert.strictEqual(projectsJson.length, 1);
      assert.strictEqual(projectsJson[0].path, path.resolve(projectDir));

      const suspectsJson = JSON.parse(await fs.readFile(path.join(stateDir, 'suspects_batch.json'), 'utf8'));
      assert.strictEqual(suspectsJson.length, 1);
      assert.strictEqual(suspectsJson[0].filepath, path.resolve(file2));

      const judgmentsJson = JSON.parse(await fs.readFile(path.join(stateDir, 'judgments.json'), 'utf8'));
      assert.strictEqual(judgmentsJson.length, 1);
      assert.strictEqual(judgmentsJson[0].filepath, path.resolve(file2));
      assert.strictEqual(judgmentsJson[0].decision, 'REMOVE');
    });

    test('a dirty git repo lands in failed[] and does not abort the batch', async () => {
      // Git is dirty
      const gitMock = createGitMock({
        'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
        'git status --porcelain': { stdout: ' M dirtyfile.js\n' },
        'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
        'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
        'git cherry': { stdout: '' }
      });

      const { stdin, stdout, getStdout } = createMockStreams([]);

      // Per-project isolation: the orchestration RESOLVES (no throw); the
      // hygiene failure is recorded in failed[] and reported.
      const result = await runOrchestration(projectDir, {
        exec: gitMock,
        captureRuns: false,
        stdin,
        stdout,
        interactive: false,
        throwOnError: true
      });

      assert.strictEqual(result.failed.length, 1);
      assert.strictEqual(result.failed[0].project, path.resolve(projectDir));
      assert.match(result.failed[0].error, /Git hygiene check failed/);
      assert.strictEqual(result.removed.length, 0);

      const out = getStdout();
      assert.match(out, /!! SKIPPED/);
      assert.match(out, /### Projects skipped \(error\/refusal\)/);
    });
  });

  describe('Per-project isolation', () => {
    test('a non-git project is refused and the batch continues to the next project', async () => {
      const batchDir = await fs.mkdtemp(path.join(tempDir, 'batch-'));
      const projA = path.join(batchDir, 'a-nongit');
      const projB = path.join(batchDir, 'b-clean');
      await fs.mkdir(projA);
      await fs.mkdir(projB);
      await fs.writeFile(path.join(projA, 'INTENT.md'), 'Objective: A.');
      await fs.writeFile(path.join(projB, 'INTENT.md'), 'Objective: B.');

      // cwd-aware git mock: project A is not a git repo, project B is clean
      const execMock = async (cmd, opts = {}) => {
        if (opts.cwd === path.resolve(projA) && cmd.includes('git rev-parse --is-inside-work-tree')) {
          throw new Error('fatal: not a git repository');
        }
        if (cmd.includes('git rev-parse --is-inside-work-tree')) return { stdout: 'true\n' };
        if (cmd.includes('git status --porcelain')) return { stdout: '' };
        if (cmd.includes('git rev-parse --abbrev-ref HEAD')) return { stdout: 'main\n' };
        if (cmd.includes('@{u}')) return { stdout: 'origin/main\n' };
        if (cmd.includes('git cherry')) return { stdout: '' };
        return { stdout: '' };
      };

      const mockAgent = async (prompt, opts) => {
        if (opts.label && opts.label.startsWith('hygiene-analysis-b')) {
          return []; // clean project — no suspects
        }
        return null;
      };

      const { stdin, stdout, getStdout } = createMockStreams([]);

      const result = await runOrchestration(batchDir, {
        exec: execMock,
        captureRuns: false,
        agent: mockAgent,
        stdin,
        stdout,
        interactive: false,
        throwOnError: true
      });

      assert.strictEqual(result.projects.length, 2);

      // Project A: hygiene refusal (non-git) lands in failed[]
      assert.strictEqual(result.failed.length, 1);
      assert.strictEqual(result.failed[0].project, path.resolve(projA));
      assert.match(result.failed[0].error, /hygiene refusal/);
      assert.match(result.failed[0].error, /not a git repository/);

      // Project B still completed its pipeline (compression ran for it)
      assert.strictEqual(result.compression.length, 1);
      assert.strictEqual(result.compression[0].path, path.resolve(projB));

      const out = getStdout();
      assert.match(out, /!! SKIPPED/);
      assert.match(out, /### Projects skipped \(error\/refusal\)/);

      await fs.rm(batchDir, { recursive: true, force: true });
    });
  });

  describe('Empty scan handling', () => {
    test('gracefully handles zero discovered projects', async () => {
      // Create empty folder with no project files
      const emptyDir = await fs.mkdtemp(path.join(tempDir, 'empty-'));

      const { stdin, stdout, getStdout } = createMockStreams([]);

      const result = await runOrchestration(emptyDir, {
        captureRuns: false,
        stdin,
        stdout,
        interactive: false,
        throwOnError: true
      });

      assert.strictEqual(result.projects.length, 0);
      assert.strictEqual(result.removed.length, 0);

      const report = getStdout();
      assert.match(report, /No active Foundry projects found in target directory/);

      await fs.rm(emptyDir, { recursive: true, force: true });
    });
  });
});
