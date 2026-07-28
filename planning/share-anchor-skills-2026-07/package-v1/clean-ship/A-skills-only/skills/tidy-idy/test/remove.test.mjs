import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { runRemoval, isProtected, PROTECTED_PATTERNS, REMOVAL_CONFIRM_THRESHOLD } from '../bin/remove.mjs';

/** Fake exec that records every command and answers rev-parse with a fixed sha. */
function createFakeExec() {
  const commands = [];
  const execFn = async (cmd, opts) => {
    commands.push(cmd);
    if (cmd.includes('git rev-parse --short HEAD')) {
      return { stdout: 'abc1234\n' };
    }
    return { stdout: '' };
  };
  return { execFn, commands };
}

/** Minimal writable sink for options.stdout (only .write is used). */
function createSink() {
  let data = '';
  return {
    stream: { write(chunk) { data += String(chunk); return true; } },
    getData: () => data
  };
}

describe('Removal Engine Unit Tests (git is the archive)', () => {
  let tempDir;

  beforeEach(async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-remove-test-'));
  });

  afterEach(async () => {
    if (tempDir) {
      await fs.rm(tempDir, { recursive: true, force: true });
    }
  });

  test('deletes a REMOVE-verdict file and commits it via git (recovery: git revert)', async () => {
    const deadFile = path.join(tempDir, 'dead.js');
    await fs.writeFile(deadFile, 'console.log("dead");');

    const { execFn, commands } = createFakeExec();
    const { stream, getData } = createSink();

    const result = await runRemoval(tempDir, [
      { filepath: 'dead.js', verdict: 'REMOVE', reasoning: 'dead code' }
    ], { exec: execFn, stdout: stream, interactive: false });

    // File is gone from disk and reported in removed[] with its relative path
    await assert.rejects(fs.access(deadFile));
    assert.strictEqual(result.removed.length, 1);
    assert.strictEqual(result.removed[0].filepath, 'dead.js');
    assert.strictEqual(result.removed[0].reasoning, 'dead code');
    assert.strictEqual(result.protectedSkips.length, 0);
    assert.strictEqual(result.skipped.length, 0);
    assert.strictEqual(result.commit, 'abc1234');

    // git saw: add -A, then the tidy-idy removal commit, then rev-parse
    assert.strictEqual(commands[0], 'git add -A');
    assert.match(commands[1], /^git commit -m "tidy-idy: remove/);
    assert.match(commands[2], /git rev-parse --short HEAD/);
    assert.match(getData(), /git revert abc1234/);
  });

  test('PROTECTED file classes are NEVER removed, even with a REMOVE verdict', async () => {
    const protectedRels = [
      'SKILL.md',
      'NORTH-STAR.md',
      path.join('journal', 'entry.md'),
      'engine.test.mjs',
      path.join('bin', 'tool.mjs')
    ];
    await fs.mkdir(path.join(tempDir, 'journal'));
    await fs.mkdir(path.join(tempDir, 'bin'));
    for (const rel of protectedRels) {
      await fs.writeFile(path.join(tempDir, rel), 'protected content');
    }

    const { execFn, commands } = createFakeExec();
    const judgments = protectedRels.map((rel) => ({
      filepath: rel, verdict: 'REMOVE', reasoning: 'judge says remove'
    }));

    const result = await runRemoval(tempDir, judgments, {
      exec: execFn, stdout: createSink().stream, interactive: false
    });

    assert.strictEqual(result.removed.length, 0);
    assert.strictEqual(result.protectedSkips.length, protectedRels.length);
    assert.strictEqual(result.commit, null);
    assert.strictEqual(commands.length, 0); // nothing removed — no git activity
    for (const skip of result.protectedSkips) {
      assert.match(skip.why, /PROTECTED/);
    }
    // Every protected file is still on disk
    for (const rel of protectedRels) {
      await fs.access(path.join(tempDir, rel));
    }

    // The exported predicate and pattern set agree
    for (const rel of protectedRels) {
      assert.strictEqual(isProtected(rel), true);
    }
    assert.strictEqual(isProtected('lib/helper.js'), false);
    assert.ok(Array.isArray(PROTECTED_PATTERNS) && PROTECTED_PATTERNS.length > 0);
  });

  test('path containment: a judgment pointing outside the project is skipped, never deleted', async () => {
    const outsidePath = path.resolve(tempDir, '../outside.txt');
    await fs.writeFile(outsidePath, 'outside the project');
    try {
      const { execFn, commands } = createFakeExec();
      const result = await runRemoval(tempDir, [
        { filepath: '../outside.txt', verdict: 'REMOVE', reasoning: 'attempted escape' }
      ], { exec: execFn, stdout: createSink().stream, interactive: false });

      assert.strictEqual(result.removed.length, 0);
      assert.strictEqual(result.skipped.length, 1);
      assert.match(result.skipped[0].why, /path containment/);
      assert.strictEqual(result.commit, null);
      assert.strictEqual(commands.length, 0);
      await fs.access(outsidePath); // untouched
    } finally {
      await fs.rm(outsidePath, { force: true });
    }
  });

  test('RETAIN verdicts and nonexistent files land in skipped', async () => {
    const keeper = path.join(tempDir, 'keeper.js');
    await fs.writeFile(keeper, 'console.log("keep");');

    const { execFn, commands } = createFakeExec();
    const result = await runRemoval(tempDir, [
      { filepath: 'keeper.js', verdict: 'RETAIN', reasoning: 'still useful' },
      { filepath: 'ghost.js', verdict: 'REMOVE', reasoning: 'does not exist' }
    ], { exec: execFn, stdout: createSink().stream, interactive: false });

    assert.strictEqual(result.removed.length, 0);
    assert.strictEqual(result.commit, null);
    assert.strictEqual(commands.length, 0);
    assert.strictEqual(result.skipped.length, 2);

    const retainSkip = result.skipped.find((s) => s.filepath === 'keeper.js');
    assert.match(retainSkip.why, /verdict not REMOVE/);
    const ghostSkip = result.skipped.find((s) => s.filepath === 'ghost.js');
    assert.match(ghostSkip.why, /does not exist/);

    await fs.access(keeper); // RETAIN'd file untouched
  });

  test('more than REMOVAL_CONFIRM_THRESHOLD removals are ALL deferred when non-interactive', async () => {
    assert.strictEqual(REMOVAL_CONFIRM_THRESHOLD, 10);

    const count = REMOVAL_CONFIRM_THRESHOLD + 1;
    const judgments = [];
    for (let i = 0; i < count; i++) {
      const rel = `dead-${i}.js`;
      await fs.writeFile(path.join(tempDir, rel), `console.log(${i});`);
      judgments.push({ filepath: rel, verdict: 'REMOVE', reasoning: `dead ${i}` });
    }

    const { execFn, commands } = createFakeExec();
    const { stream, getData } = createSink();

    const result = await runRemoval(tempDir, judgments, {
      exec: execFn, stdout: stream, interactive: false
    });

    assert.strictEqual(result.removed.length, 0);
    assert.strictEqual(result.commit, null);
    assert.strictEqual(commands.length, 0);
    assert.strictEqual(result.skipped.length, count);
    for (const skip of result.skipped) {
      assert.match(skip.why, /10/); // the 10-file gate is named in the why
    }
    // Nothing was deleted
    for (let i = 0; i < count; i++) {
      await fs.access(path.join(tempDir, `dead-${i}.js`));
    }
    assert.match(getData(), /REMOVAL DEFERRED/);
  });

  test('throws a HARD error when the removal commit fails', async () => {
    const deadFile = path.join(tempDir, 'dead.js');
    await fs.writeFile(deadFile, 'console.log("dead");');

    const failingExec = async (cmd) => {
      if (cmd.includes('git commit')) {
        throw new Error('hook rejected the commit');
      }
      return { stdout: '' };
    };

    await assert.rejects(
      runRemoval(tempDir, [
        { filepath: 'dead.js', verdict: 'REMOVE', reasoning: 'dead' }
      ], { exec: failingExec, stdout: createSink().stream, interactive: false }),
      /removal commit FAILED/
    );
  });
});
