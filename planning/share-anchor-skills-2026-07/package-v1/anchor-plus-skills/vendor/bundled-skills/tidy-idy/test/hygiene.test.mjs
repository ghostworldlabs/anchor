import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { exec } from 'node:child_process';
import { promisify } from 'node:util';
import { Readable, Writable } from 'node:stream';
import { checkProjectHygiene, runHygieneCheck } from '../bin/hygiene.mjs';

const execAsync = promisify(exec);

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
    // Look for command sub-strings to match
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

describe('Git Hygiene Unit Tests (Mocked)', () => {
  let tempDir;

  before(async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-hygiene-mock-'));
  });

  after(async () => {
    if (tempDir) {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  });

  test('detects a perfectly clean repository', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: '' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
      'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
      'git cherry': { stdout: '' }
    });

    const status = await checkProjectHygiene(tempDir, { exec: gitMock });
    assert.strictEqual(status.isGit, true);
    assert.strictEqual(status.isDirty, false);
    assert.strictEqual(status.hasUnpushedBranch, false);
    assert.strictEqual(status.hasUnpushedCommits, false);
    assert.strictEqual(status.currentBranch, 'main');
    assert.strictEqual(status.error, null);
  });

  test('detects uncommitted changes', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: ' M file.txt\n?? newfile.js\n' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
      'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
      'git cherry': { stdout: '' }
    });

    const status = await checkProjectHygiene(tempDir, { exec: gitMock });
    assert.strictEqual(status.isGit, true);
    assert.strictEqual(status.isDirty, true);
    assert.strictEqual(status.hasUnpushedBranch, false);
    assert.strictEqual(status.hasUnpushedCommits, false);
  });

  test('detects unpushed branch (no upstream)', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: '' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'feature-branch\n' },
      'git rev-parse --abbrev-ref @{u}': { error: 'fatal: no upstream configured for branch feature-branch' },
      'git cherry': { stdout: '' }
    });

    const status = await checkProjectHygiene(tempDir, { exec: gitMock });
    assert.strictEqual(status.isGit, true);
    assert.strictEqual(status.isDirty, false);
    assert.strictEqual(status.hasUnpushedBranch, true);
    assert.strictEqual(status.hasUnpushedCommits, false);
  });

  test('detects unpushed commits (ahead of upstream)', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: '' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
      'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
      'git cherry': { stdout: '+ a1b2c3d\n+ e5f6g7h\n' }
    });

    const status = await checkProjectHygiene(tempDir, { exec: gitMock });
    assert.strictEqual(status.isGit, true);
    assert.strictEqual(status.isDirty, false);
    assert.strictEqual(status.hasUnpushedBranch, false);
    assert.strictEqual(status.hasUnpushedCommits, true);
  });

  test('detects non-git directory', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { error: 'fatal: not a git repository' }
    });

    const status = await checkProjectHygiene(tempDir, { exec: gitMock });
    assert.strictEqual(status.isGit, false);
    assert.strictEqual(status.isDirty, false);
    assert.strictEqual(status.hasUnpushedBranch, false);
    assert.strictEqual(status.hasUnpushedCommits, false);
  });

  test('runHygieneCheck HARD-refuses a non-git directory even in interactive mode (no force-proceed)', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { error: 'fatal: not a git repository' }
    });

    // Feed a "force proceed" answer — it must never be consulted for non-git.
    const { stdin, stdout, getStdout } = createMockStreams(['2\n']);
    await assert.rejects(
      runHygieneCheck(tempDir, {
        exec: gitMock,
        stdin,
        stdout,
        interactive: true,
        throwOnError: true
      }),
      /hygiene refusal.*not a git repository/
    );

    const out = getStdout();
    assert.match(out, /REFUSED/);
    assert.doesNotMatch(out, /=== HUMAN DECISION REQUIRED ===/);
  });

  test('runHygieneCheck passes on clean repo without prompting', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: '' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
      'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
      'git cherry': { stdout: '' }
    });

    const { stdin, stdout, getStdout } = createMockStreams([]);
    const res = await runHygieneCheck(tempDir, {
      exec: gitMock,
      stdin,
      stdout,
      interactive: true,
      throwOnError: true
    });

    assert.strictEqual(res, true);
    assert.match(getStdout(), /Git hygiene check passed/);
  });

  test('runHygieneCheck throws error on dirty repo in non-interactive mode', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: ' M file.txt\n' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
      'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
      'git cherry': { stdout: '' }
    });

    const { stdin, stdout, getStdout } = createMockStreams([]);
    await assert.rejects(
      runHygieneCheck(tempDir, {
        exec: gitMock,
        stdin,
        stdout,
        interactive: false,
        throwOnError: true
      }),
      /Git hygiene check failed/
    );

    const out = getStdout();
    assert.match(out, /=== GIT HYGIENE PRE-FLIGHT ALERT \(NON-INTERACTIVE\) ===/);
    assert.match(out, /\[Question\]/);
    assert.match(out, /\[Context\]/);
    assert.match(out, /\[Explanation\]/);
    assert.match(out, /\[Options\]/);
    assert.match(out, /\[Recommendation\]/);
  });

  test('runHygieneCheck allows force-proceed in interactive mode (option 2)', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: ' M file.txt\n' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
      'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
      'git cherry': { stdout: '' }
    });

    const { stdin, stdout, getStdout } = createMockStreams(['2\n']);
    const res = await runHygieneCheck(tempDir, {
      exec: gitMock,
      stdin,
      stdout,
      interactive: true,
      throwOnError: true
    });

    assert.strictEqual(res, true);
    const out = getStdout();
    assert.match(out, /=== HUMAN DECISION REQUIRED ===/);
    assert.match(out, /Proceeding with tidy-idy execution despite Git hygiene warnings/);
  });

  test('runHygieneCheck supports auto-stash in interactive mode (option 3)', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: ' M file.txt\n' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
      'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
      'git cherry': { stdout: '' },
      'git stash push': { stdout: 'Saved working directory and index state WIP on main' }
    });

    const { stdin, stdout, getStdout } = createMockStreams(['3\n']);
    const res = await runHygieneCheck(tempDir, {
      exec: gitMock,
      stdin,
      stdout,
      interactive: true,
      throwOnError: true
    });

    assert.strictEqual(res, true);
    const out = getStdout();
    assert.match(out, /Attempting to automatically stash changes/);
    assert.match(out, /Changes stashed successfully/);
  });

  test('runHygieneCheck aborts in interactive mode (option 1)', async () => {
    const gitMock = createGitMock({
      'git rev-parse --is-inside-work-tree': { stdout: 'true\n' },
      'git status --porcelain': { stdout: ' M file.txt\n' },
      'git rev-parse --abbrev-ref HEAD': { stdout: 'main\n' },
      'git rev-parse --abbrev-ref @{u}': { stdout: 'origin/main\n' },
      'git cherry': { stdout: '' }
    });

    const { stdin, stdout, getStdout } = createMockStreams(['1\n']);
    await assert.rejects(
      runHygieneCheck(tempDir, {
        exec: gitMock,
        stdin,
        stdout,
        interactive: true,
        throwOnError: true
      }),
      /Aborted by user request/
    );

    const out = getStdout();
    assert.match(out, /Aborted by user request/);
  });
});

describe('Git Hygiene Integration Tests (Real Git)', () => {
  let tempDir;

  before(async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-hygiene-integration-'));
  });

  after(async () => {
    if (tempDir) {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  });

  test('integration: refuses not-git, then detects dirty git repo', async () => {
    const projectDir = path.join(tempDir, 'proj');
    await fs.mkdir(projectDir);

    // HOST QUIRK (the pre-existing baseline failure on this machine): the OS temp
    // dir can itself sit INSIDE a git work tree (observed live: a git-inited
    // %TEMP%), which makes every mkdtemp dir read as isGit:true — the not-git leg
    // is then untestable here. `git rev-parse --is-inside-work-tree` is still the
    // RIGHT production check (Foundry skills are subdirs of the foundry repo and
    // must read as git). The refusal behavior itself is covered by the mocked
    // non-git test above; skip only this leg when the host quirk is present.
    const status1 = await checkProjectHygiene(projectDir);
    if (status1.isGit) {
      console.log('  ~ not-git leg SKIPPED: the OS temp dir is inside a git work tree on this host');
    } else {
      // 1b. runHygieneCheck on a non-git dir is a HARD refusal — no interactive
      //     force-proceed exists for non-git anymore.
      const { stdin, stdout, getStdout } = createMockStreams(['2\n']);
      await assert.rejects(
        runHygieneCheck(projectDir, {
          stdin,
          stdout,
          interactive: true,
          throwOnError: true
        }),
        /hygiene refusal.*not a git repository/
      );
      assert.match(getStdout(), /REFUSED/);
    }

    // 2. Initialize real git repository
    try {
      await execAsync('git init', { cwd: projectDir });
    } catch {
      // If git CLI is not available in test environment, skip rest of integration test
      return;
    }

    // 3. Check again - now it is inside a git repo but clean (no files yet)
    const status2 = await checkProjectHygiene(projectDir);
    assert.strictEqual(status2.isGit, true);
    assert.strictEqual(status2.isDirty, false);

    // 4. Create an untracked file to make it dirty
    await fs.writeFile(path.join(projectDir, 'dummy.txt'), 'hello world');

    // 5. Check again - should be dirty
    const status3 = await checkProjectHygiene(projectDir);
    assert.strictEqual(status3.isGit, true);
    assert.strictEqual(status3.isDirty, true);
  });
});
