// test/engine-tripwire.test.mjs — Wave 1, Tier 1 of the two-tier tripwire.
//
// Covers the frozen acceptance criterion:
//   "Given an analysis run during which a stage attempts any write under the
//    project root outside reportDir, when the write-audit facade intercepts the
//    call, then the run terminates status=failed naming the offending stage and
//    path — and in hermetic CI fixtures any post-analysis metadata delta vs S
//    likewise fails the build, so no fake-clean result is producible."

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import { existsSync, constants as fsConstants } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { createWriteAudit, WriteAuditViolation, opensForWrite } from '../engine/write-audit.mjs';
import { runPipeline } from '../engine/pipeline.mjs';
import { makeStageResult, STATUS } from '../engine/envelope.mjs';

let root;
let reportDir;

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-tripwire-'));
  reportDir = path.join(root, '.tidy-idy');
  await fs.mkdir(reportDir, { recursive: true });
  await fs.writeFile(path.join(root, 'content.txt'), 'project content\n');
});

afterEach(async () => {
  if (root) await fs.rm(root, { recursive: true, force: true, maxRetries: 5 });
});

describe('Tier 1 — the write-audit facade blocks AT THE CALL SITE', () => {
  test('a write under the root outside reportDir is BLOCKED (the file is never created)', async () => {
    const audit = createWriteAudit({ rootPath: root, reportDir });
    audit.enterStage('analyze');
    const target = path.join(root, 'engine-wrote-this.txt');

    await assert.rejects(
      () => audit.fs.writeFile(target, 'nope'),
      (err) => err instanceof WriteAuditViolation
        && err.stage === 'analyze'
        && err.target === target
        && /ZERO-WRITE INVARIANT VIOLATED/.test(err.message)
        && /analyze/.test(err.message),
      'the violation must name the offending stage AND path');

    assert.strictEqual(existsSync(target), false,
      'BLOCKED means blocked: detecting the damage afterwards would mean the tool already corrupted the tree it promised not to touch');
    assert.strictEqual(audit.violations.length, 1);
  });

  test('reportDir is the SOLE exception', async () => {
    const audit = createWriteAudit({ rootPath: root, reportDir });
    audit.enterStage('archive');
    await audit.fs.writeFile(path.join(reportDir, 'envelope.json'), '{}');
    assert.ok(existsSync(path.join(reportDir, 'envelope.json')));
    assert.strictEqual(audit.violations.length, 0);
  });

  test('writes OUTSIDE the root are none of this tripwire\'s business', async () => {
    const audit = createWriteAudit({ rootPath: root, reportDir });
    const outside = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-outside-'));
    try {
      await audit.fs.writeFile(path.join(outside, 'scratch.txt'), 'fine');
      assert.strictEqual(audit.violations.length, 0);
    } finally {
      await fs.rm(outside, { recursive: true, force: true });
    }
  });

  test('every mutating fs entry point is guarded, not just writeFile', async () => {
    const audit = createWriteAudit({ rootPath: root, reportDir });
    audit.enterStage('scan');
    const inside = path.join(root, 'content.txt');
    await assert.rejects(() => audit.fs.rm(inside), WriteAuditViolation);
    await assert.rejects(() => audit.fs.unlink(inside), WriteAuditViolation);
    await assert.rejects(() => audit.fs.mkdir(path.join(root, 'newdir')), WriteAuditViolation);
    await assert.rejects(() => audit.fs.appendFile(inside, 'x'), WriteAuditViolation);
    await assert.rejects(() => audit.fs.rename(inside, path.join(root, 'moved.txt')), WriteAuditViolation);
    await assert.rejects(() => audit.fs.open(inside, 'w'), WriteAuditViolation);
    assert.ok(existsSync(inside), 'not one of those calls may have taken effect');
  });

  test('open() is guarded in its NUMERIC flag form too, not only the string form', async () => {
    const audit = createWriteAudit({ rootPath: root, reportDir });
    audit.enterStage('scan');
    const target = path.join(root, 'numeric-open.txt');

    // The hole this closes: String(O_WRONLY|O_CREAT) is '65', which contains no
    // 'w', 'a', 'x' or '+', so a purely string-based guard waved it through.
    await assert.rejects(
      () => audit.fs.open(target, fsConstants.O_WRONLY | fsConstants.O_CREAT),
      WriteAuditViolation,
      'a numeric write-open under the root must be blocked exactly like open(p, "w")');
    assert.strictEqual(existsSync(target), false, 'O_CREAT must not have created the file');

    // …and the predicate itself agrees on both notations.
    assert.strictEqual(opensForWrite('r'), false);
    assert.strictEqual(opensForWrite('rs'), false);
    assert.strictEqual(opensForWrite('w'), true);
    assert.strictEqual(opensForWrite('r+'), true);
    assert.strictEqual(opensForWrite(fsConstants.O_RDONLY), false);
    assert.strictEqual(opensForWrite(fsConstants.O_WRONLY | fsConstants.O_CREAT), true);
    assert.strictEqual(opensForWrite(fsConstants.O_RDWR), true);
    assert.strictEqual(opensForWrite(fsConstants.O_APPEND | fsConstants.O_WRONLY), true);
  });

  test('reads pass through untouched', async () => {
    const audit = createWriteAudit({ rootPath: root, reportDir });
    assert.strictEqual(await audit.fs.readFile(path.join(root, 'content.txt'), 'utf8'), 'project content\n');
    const entries = await audit.fs.readdir(root);
    assert.ok(entries.includes('content.txt'));
    assert.ok(await audit.fs.stat(path.join(root, 'content.txt')));
    assert.strictEqual(audit.violations.length, 0);
    // Reading with 'r' is not a write.
    const fh = await audit.fs.open(path.join(root, 'content.txt'), 'r');
    await fh.close();
  });

  test('child-process spawns are LOGGED so a native tool\'s write is attributable', async () => {
    const calls = [];
    const audit = createWriteAudit({
      rootPath: root,
      reportDir,
      baseExecFile: async (cmd, args) => { calls.push([cmd, args]); return { stdout: 'ok', stderr: '' }; },
    });
    audit.enterStage('hygiene');
    await audit.execFile('git', ['status', '--porcelain'], { cwd: root });
    assert.strictEqual(audit.spawns.length, 1);
    assert.strictEqual(audit.spawns[0].cmd, 'git');
    assert.strictEqual(audit.spawns[0].stage, 'hygiene');
    assert.strictEqual(audit.spawns[0].ok, true);
    assert.deepStrictEqual(calls, [['git', ['status', '--porcelain']]]);
  });
});

describe('Tier 1 — a violating stage FAILS THE RUN', () => {
  const rogueStage = {
    name: 'rogue',
    requiresGit: false,
    gitNull: { status: STATUS.OK, findings: 0, note: 'test double' },
    async run(ctx) {
      await ctx.fs.writeFile(path.join(ctx.rootPath, 'rogue-output.txt'), 'I should not exist');
      return makeStageResult({ stage: 'rogue', status: STATUS.OK, coverage: { scanned: 1, skipped: 0, errored: 0 } });
    },
  };

  test('run terminates status=failed, names the stage and path, and cannot be clean', async () => {
    const envelope = await runPipeline({ rootPath: root, git: null, agent: async () => [], stages: [rogueStage] });

    assert.strictEqual(envelope.status, STATUS.FAILED);
    assert.strictEqual(envelope.isClean, false, 'no fake-clean result is producible from a violating run');

    const failed = envelope.stages.find((s) => s.stage === 'rogue');
    assert.ok(failed, 'the failure must be attributed to the offending stage');
    assert.strictEqual(failed.status, STATUS.FAILED);
    assert.match(failed.errors[0].message, /ZERO-WRITE INVARIANT VIOLATED/);
    assert.match(failed.errors[0].message, /rogue-output\.txt/);

    assert.strictEqual(existsSync(path.join(root, 'rogue-output.txt')), false);
    assert.strictEqual(envelope.tripwire.tier1Violations.length, 1);
  });

  test('a well-behaved run over a hermetic fixture leaves the tree bit-identical and passes the sweep', async () => {
    const quietStage = {
      name: 'quiet',
      requiresGit: false,
      gitNull: { status: STATUS.OK, findings: 0, note: 'test double' },
      async run(ctx) {
        await ctx.fs.readFile(path.join(ctx.rootPath, 'content.txt'), 'utf8');
        return makeStageResult({ stage: 'quiet', status: STATUS.OK, coverage: { scanned: 1, skipped: 0, errored: 0 } });
      },
    };
    const envelope = await runPipeline({ rootPath: root, git: null, hermetic: true, agent: async () => [], stages: [quietStage] });
    assert.strictEqual(envelope.status, STATUS.OK, JSON.stringify(envelope.errors));
    assert.strictEqual(envelope.isClean, true);
    const sweep = envelope.stages.find((s) => s.stage === 'sweep');
    assert.strictEqual(sweep.status, STATUS.OK);
  });
});

describe('Tier 2 — a hermetic-fixture delta FAILS THE BUILD (the other half of criterion 1)', () => {
  // The scenario Tier 2 exists for: a write Tier 1 could NOT see. A stage that
  // reaches around the facade — or, in production, a native tool spawned by one —
  // leaves no violation record, so the only thing that can catch it is the
  // post-analysis sweep against S. In a hermetic fixture no external editor
  // exists, so ANY delta can only have come from the engine, and the run must
  // fail rather than report a tree it silently modified.
  const smugglingStage = {
    name: 'smuggler',
    requiresGit: false,
    gitNull: { status: STATUS.OK, findings: 0, note: 'test double' },
    async run(ctx) {
      // Deliberately NOT ctx.fs — this is the unattributable write.
      const target = path.join(ctx.rootPath, 'content.txt');
      await fs.writeFile(target, 'the engine modified the tree behind the facade\n');
      const future = new Date(Date.now() + 5000);
      await fs.utimes(target, future, future);
      return makeStageResult({ stage: 'smuggler', status: STATUS.OK, coverage: { scanned: 1, skipped: 0, errored: 0 } });
    },
  };

  test('the run fails, names the drifted path, and no fake-clean result is producible', async () => {
    const envelope = await runPipeline({
      rootPath: root, git: null, hermetic: true, agent: async () => [], stages: [smugglingStage],
    });

    assert.strictEqual(envelope.status, STATUS.FAILED,
      'a hermetic fixture whose tree changed under the engine must fail the build');
    assert.strictEqual(envelope.isClean, false);

    const sweep = envelope.stages.find((s) => s.stage === 'sweep');
    assert.ok(sweep, 'the sweep must appear as a stage so the failure is attributable');
    assert.strictEqual(sweep.status, STATUS.FAILED);
    assert.match(sweep.coverage.note, /HERMETIC FIXTURE/);
    assert.ok(sweep.errors.some((e) => /content\.txt/.test(e.message)),
      'the failure must name the path that drifted');

    // Tier 1 recorded nothing — which is exactly why Tier 2 has to exist.
    assert.strictEqual(envelope.tripwire.tier1Violations.length, 0);
  });

  test('the SAME delta in a production (non-hermetic) run completes and is recorded as drift, never an abort', async () => {
    const envelope = await runPipeline({
      rootPath: root, git: null, hermetic: false, agent: async () => [], stages: [smugglingStage],
    });

    assert.notStrictEqual(envelope.status, STATUS.FAILED,
      'external drift during a background pass is expected behaviour, not an error');
    assert.ok(envelope.drift.some((d) => d.path === 'content.txt'),
      'the non-finding edit must land in the envelope drift log');
    assert.strictEqual(envelope.isClean, false, 'a run with drift still cannot claim clean');
  });
});
