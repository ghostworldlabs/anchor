// test/apply-trash.test.mjs — Wave 4: the reversible Trash subsystem.
//
// Frozen acceptance criteria under test, verbatim:
//   • "a non-git folder with three junk files approved for removal … all three
//      move atomically into .tidy-idy/trash/<run-id>/ with a journal entry each,
//      the folder is otherwise untouched, and restore-from-Trash returns each
//      file bit-identical to its original path"
//   • "a Trash move-set interrupted mid-way … the journal drives an idempotent
//      resume completing the remaining moves, with no file lost and no file
//      duplicated"
//   • "a restore-from-Trash interrupted mid-way … the restore journal drives an
//      idempotent resume to fully-restored — every file back at its original
//      path bit-identical, none lost, none duplicated"
//   • "restore of a path whose location was since reoccupied handled safely
//      (refuse-with-explanation, never overwrite)"
//
// INTERRUPTION IS SIMULATED BY BUILDING THE STATE A KILL WOULD LEAVE, not by
// killing a process: a real SIGKILL in a test would be timing-dependent and
// would prove nothing repeatable. The two states that matter are (a) the move
// happened and its `done` record did not, and (b) some ops never started — and
// both are constructed exactly here, then handed to a fresh call.

import { test, describe, before, after, beforeEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  executeTrashMoveSet, restoreFromTrash, preflightTrashMoveSet, readTrashLedger,
  listTrash, emptyTrash, trashDirFor, trashFilesDirFor, TRASH_STATUS, TRASH_REFUSAL,
} from '../engine/apply/trash.mjs';
import { openJournal } from '../engine/apply/journal.mjs';
import { applyApproved, APPLY_REFUSAL, APPLY_STATUS } from '../engine/apply/executor.mjs';
import { undoApply, UNDO_STATUS, UNDO_BRANCH } from '../engine/apply/undo.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';

import {
  makeTempRoot, rmTempRoot, write, git, initRepo, commitAll,
  scanFixture, makeFinding, stamp, approvalsFor, listFiles, commitCount,
} from './helpers/apply-fixture.mjs';

const RUN = 'run-trash-0001';

// Several describes need a FRESH folder per test (a move-set is stateful), so
// roots are tracked centrally and removed once, rather than each block racing
// its own teardown against the next block's setup.
const tempRoots = [];
async function newRoot(prefix) {
  const root = await makeTempRoot(prefix);
  tempRoots.push(root);
  return root;
}
after(async () => { for (const r of tempRoots) await rmTempRoot(r); });

/** Three junk files with distinguishable content, plus a keeper. */
async function plainFolder() {
  const root = await newRoot('tidy-idy-w4-trash-');
  await write(root, 'junk-a.txt', 'AAAA\n');
  await write(root, 'nested/junk-b.log', 'BBBB\n');
  await write(root, 'nested/deeper/junk-c.tmp', 'CCCC\n');
  await write(root, 'keep-me.md', '# keep\n');
  return root;
}

const JUNK = ['junk-a.txt', 'nested/junk-b.log', 'nested/deeper/junk-c.tmp'];

const trashOps = (paths) => paths.map((p) => ({ id: `id-${p}`, path: p }));

async function readOrNull(abs) {
  try { return (await fs.readFile(abs)).toString('utf8'); } catch { return null; }
}

describe('a non-git folder: three approved removals become one journaled move-set', () => {
  let root;
  let reportDir;

  beforeEach(async () => {
    root = await plainFolder();
    reportDir = reportDirFor(root);
  });

  test('all three move into .tidy-idy/trash/<run-id>/, each with a journal entry', async () => {
    const before = await listFiles(root);

    const result = await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });

    assert.strictEqual(result.status, TRASH_STATUS.OK, result.message);
    assert.strictEqual(result.moved.length, 3);
    assert.deepStrictEqual(result.failed, []);

    // Gone from the folder…
    const after = await listFiles(root);
    assert.deepStrictEqual(after, before.filter((p) => !JUNK.includes(p)),
      'exactly the approved paths left the folder — nothing else moved, and nothing else appeared');

    // …and present, byte-identical, in the run's trash directory.
    const filesDir = trashFilesDirFor(reportDir, RUN);
    assert.strictEqual(await readOrNull(path.join(filesDir, 'junk-a.txt')), 'AAAA\n');
    assert.strictEqual(await readOrNull(path.join(filesDir, 'nested/junk-b.log')), 'BBBB\n');
    assert.strictEqual(await readOrNull(path.join(filesDir, 'nested/deeper/junk-c.tmp')), 'CCCC\n');

    // A journal entry EACH — the plural in the criterion is the assertion.
    const { journal } = await readTrashLedger({ reportDir, runId: RUN });
    for (const rel of JUNK) {
      const done = journal.records.filter((r) => r.type === 'move' && r.path === rel && r.state === 'done');
      assert.strictEqual(done.length, 1, `expected exactly one 'done' move record for ${rel}`);
      assert.ok(done[0].hash, 'the record carries the content hash the restore is checked against');
    }
  });

  test('the keeper file is untouched, byte-for-byte', async () => {
    await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });
    assert.strictEqual(await readOrNull(path.join(root, 'keep-me.md')), '# keep\n');
  });

  test('restore-from-Trash returns every file bit-identical to its original path', async () => {
    const before = await listFiles(root);
    const contents = {};
    for (const p of before) contents[p] = await readOrNull(path.join(root, p));

    await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });
    const restore = await restoreFromTrash({ rootPath: root, reportDir, runId: RUN });

    assert.strictEqual(restore.status, TRASH_STATUS.OK, restore.message);
    assert.deepStrictEqual(restore.refused, []);
    assert.deepStrictEqual(await listFiles(root), before, 'the folder is exactly as it was');
    for (const p of before) {
      assert.strictEqual(await readOrNull(path.join(root, p)), contents[p], `${p} came back bit-identical`);
    }
    for (const r of restore.restored) {
      assert.notStrictEqual(r.bitIdentical, false, `${r.path} was restored with a different hash than it was trashed with`);
    }
  });

  test('nothing was deleted: the Trash still holds the record after a restore', async () => {
    await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });
    await restoreFromTrash({ rootPath: root, reportDir, runId: RUN });
    const { runs } = await listTrash({ reportDir });
    const run = runs.find((r) => r.runId === RUN);
    assert.strictEqual(run.items, 3);
    assert.strictEqual(run.held, 0, 'all three are back at their original paths');
    assert.strictEqual(run.restored, 3);
  });
});

describe('an interrupted move-set resumes idempotently', () => {
  let root;
  let reportDir;

  beforeEach(async () => {
    root = await plainFolder();
    reportDir = reportDirFor(root);
  });

  test('a retry completes only the outstanding moves — none lost, none duplicated', async () => {
    // The kill landed after the first file's move-set entry completed.
    const first = await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps([JUNK[0]]) });
    assert.strictEqual(first.moved.length, 1);

    // The retry is handed the WHOLE approved set, exactly as a re-Apply would be.
    const retry = await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });

    assert.strictEqual(retry.status, TRASH_STATUS.OK, retry.message);
    assert.strictEqual(retry.moved.length, 3, 'every approved path ends up in the Trash');
    assert.strictEqual(retry.resumed, 1, 'the already-moved file was recognised, not moved again');

    const filesDir = trashFilesDirFor(reportDir, RUN);
    assert.strictEqual(await readOrNull(path.join(filesDir, 'junk-a.txt')), 'AAAA\n', 'no duplication, no truncation');
    assert.deepStrictEqual(await listFiles(root), ['keep-me.md']);

    // Exactly one 'done' record per path: a resume must not double-journal either.
    const { journal } = await readTrashLedger({ reportDir, runId: RUN });
    for (const rel of JUNK) {
      assert.strictEqual(journal.records.filter((r) => r.type === 'move' && r.path === rel && r.state === 'done').length, 1);
    }
  });

  test('a move that completed WITHOUT its done record is reconciled, not repeated', async () => {
    // The exact state a kill between the rename and the flush leaves behind.
    const rel = JUNK[1];
    const dest = path.join(trashFilesDirFor(reportDir, RUN), rel);
    const ledger = await openJournal({ reportDir, runId: RUN, kind: 'trash' });
    await ledger.append('move', { path: rel, trashRel: rel, state: 'started', hash: null, size: 5 });
    await fs.mkdir(path.dirname(dest), { recursive: true });
    await fs.rename(path.join(root, rel), dest);

    const result = await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });

    assert.strictEqual(result.status, TRASH_STATUS.OK, result.message);
    assert.strictEqual(result.moved.length, 3);
    assert.strictEqual(await readOrNull(dest), 'BBBB\n', 'the already-moved bytes were left exactly as they were');

    const { journal } = await readTrashLedger({ reportDir, runId: RUN });
    const done = journal.records.filter((r) => r.type === 'move' && r.path === rel && r.state === 'done');
    assert.strictEqual(done.length, 1);
    assert.match(String(done[0].reconciled), /had completed/, 'the record says it was reconciled rather than performed');
  });
});

describe('an interrupted restore resumes idempotently', () => {
  let root;
  let reportDir;

  beforeEach(async () => {
    root = await plainFolder();
    reportDir = reportDirFor(root);
    await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });
  });

  test('a retry after one of three converges to fully-restored', async () => {
    const partial = await restoreFromTrash({ rootPath: root, reportDir, runId: RUN, paths: [JUNK[0]] });
    assert.strictEqual(partial.restored.length, 1);

    const retry = await restoreFromTrash({ rootPath: root, reportDir, runId: RUN });

    assert.strictEqual(retry.status, TRASH_STATUS.OK, retry.message);
    assert.deepStrictEqual(retry.refused, []);
    assert.deepStrictEqual(await listFiles(root), ['junk-a.txt', 'keep-me.md', 'nested/deeper/junk-c.tmp', 'nested/junk-b.log'].sort());
    assert.strictEqual(await readOrNull(path.join(root, JUNK[0])), 'AAAA\n', 'the already-restored file was not touched again');
    assert.strictEqual(await readOrNull(path.join(root, JUNK[2])), 'CCCC\n');
  });

  test('a move-back that completed WITHOUT its done record is reconciled', async () => {
    const rel = JUNK[2];
    const src = path.join(trashFilesDirFor(reportDir, RUN), rel);
    const ledger = await openJournal({ reportDir, runId: RUN, kind: 'trash' });
    await ledger.append('restore', { path: rel, trashRel: rel, state: 'started', hash: null });
    await fs.mkdir(path.dirname(path.join(root, rel)), { recursive: true });
    await fs.rename(src, path.join(root, rel));

    const retry = await restoreFromTrash({ rootPath: root, reportDir, runId: RUN });

    assert.strictEqual(retry.status, TRASH_STATUS.OK, retry.message);
    assert.deepStrictEqual(retry.refused, [], 'a file already back at its path is NOT a no-clobber refusal');
    assert.strictEqual(retry.restored.length, 3);
    assert.strictEqual(await readOrNull(path.join(root, rel)), 'CCCC\n', 'nothing was duplicated or lost');
  });
});

describe('NO-CLOBBER: a reoccupied original path is refused, never overwritten', () => {
  let root;
  let reportDir;

  before(async () => {
    root = await plainFolder();
    reportDir = reportDirFor(root);
    await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });
    // The user made a NEW file where one of the removed ones used to be.
    await write(root, JUNK[0], 'MY NEW WORK\n');
  });

  test('the occupied path is refused with an explanation and a copyable command', async () => {
    const restore = await restoreFromTrash({ rootPath: root, reportDir, runId: RUN });

    assert.strictEqual(restore.status, TRASH_STATUS.PARTIAL, restore.message);
    assert.strictEqual(restore.refused.length, 1);
    const refusal = restore.refused[0];
    assert.strictEqual(refusal.path, JUNK[0]);
    assert.strictEqual(refusal.code, TRASH_REFUSAL.DEST_OCCUPIED);
    assert.match(refusal.message, /NO-CLOBBER/);
    assert.ok(refusal.manualCommand.command, 'a copyable command is offered');
    assert.strictEqual(refusal.manualCommand.destructive, true, 'and it is labelled destructive, because it is');
  });

  test('the user\'s new content is untouched and the trashed copy is still in the Trash', async () => {
    await restoreFromTrash({ rootPath: root, reportDir, runId: RUN });
    assert.strictEqual(await readOrNull(path.join(root, JUNK[0])), 'MY NEW WORK\n');
    assert.strictEqual(await readOrNull(path.join(trashFilesDirFor(reportDir, RUN), JUNK[0])), 'AAAA\n');
  });

  test('the OTHER paths still restore — one refusal does not block the batch', async () => {
    await restoreFromTrash({ rootPath: root, reportDir, runId: RUN });
    assert.strictEqual(await readOrNull(path.join(root, JUNK[1])), 'BBBB\n');
    assert.strictEqual(await readOrNull(path.join(root, JUNK[2])), 'CCCC\n');
  });
});

describe('TTL and empty semantics — retention is offered, never enforced', () => {
  let root;
  let reportDir;

  before(async () => {
    root = await plainFolder();
    reportDir = reportDirFor(root);
    await executeTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });
  });

  test('a fresh run is listed as held and NOT expired', async () => {
    const { runs } = await listTrash({ reportDir });
    const run = runs.find((r) => r.runId === RUN);
    assert.strictEqual(run.held, 3);
    assert.strictEqual(run.expired, false);
    assert.ok(run.bytes > 0, 'the panel can show what emptying would reclaim');
  });

  test('a run past its TTL is LABELLED expired — and is still there', async () => {
    const later = () => new Date(Date.now() + 40 * 24 * 60 * 60 * 1000);
    const { runs } = await listTrash({ reportDir, now: later });
    assert.strictEqual(runs.find((r) => r.runId === RUN).expired, true);
    assert.strictEqual(await readOrNull(path.join(trashFilesDirFor(reportDir, RUN), JUNK[0])), 'AAAA\n',
      'listing never deletes: expiry is a label the user acts on, not a timer that acts for them');
  });

  test('expiredOnly leaves a fresh run alone', async () => {
    const result = await emptyTrash({ reportDir, expiredOnly: true });
    assert.deepStrictEqual(result.purged, []);
    assert.strictEqual(await readOrNull(path.join(trashFilesDirFor(reportDir, RUN), JUNK[0])), 'AAAA\n');
  });

  test('an explicit empty of one run purges exactly that run', async () => {
    const result = await emptyTrash({ reportDir, runId: RUN });
    assert.strictEqual(result.purged.length, 1);
    assert.strictEqual(result.purged[0].runId, RUN);
    assert.strictEqual(await readOrNull(path.join(trashFilesDirFor(reportDir, RUN), JUNK[0])), null);
    await assert.rejects(fs.stat(trashDirFor(reportDir, RUN)));
  });
});

describe('the pre-flight refuses what it cannot do, before anything moves', () => {
  let root;
  let reportDir;

  beforeEach(async () => {
    root = await plainFolder();
    reportDir = reportDirFor(root);
  });

  test('a vanished source is a problem, not a silent skip', async () => {
    await fs.rm(path.join(root, JUNK[0]));
    const pre = await preflightTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });
    assert.strictEqual(pre.ok, false);
    assert.strictEqual(pre.problems[0].code, TRASH_REFUSAL.SOURCE_MISSING);
  });

  test('an already-occupied Trash slot is refused rather than overwritten', async () => {
    await write(path.join(trashFilesDirFor(reportDir, RUN)), JUNK[0], 'SOMETHING ELSE\n');
    const pre = await preflightTrashMoveSet({ rootPath: root, reportDir, runId: RUN, ops: trashOps(JUNK) });
    assert.strictEqual(pre.ok, false);
    assert.strictEqual(pre.problems[0].code, TRASH_REFUSAL.SLOT_OCCUPIED);
  });
});

describe('Apply on a plain folder: removals are un-gated by git (Amendment A)', () => {
  let root;

  beforeEach(async () => { root = await plainFolder(); });
  test('an approved trash removal applies with NO repository at all', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    assert.strictEqual(scan.git, null, 'the fixture really has no repository');

    const findings = stamp(JUNK.map((p) => makeFinding(scan, { action: 'trash', path: p })), RUN);
    const result = await applyApproved({
      rootPath: root, git: null, runId: RUN, snapshot: scan.snapshot,
      findings, approvals: approvalsFor(findings),
    });

    assert.strictEqual(result.status, APPLY_STATUS.APPLIED, JSON.stringify(result, null, 2));
    assert.strictEqual(result.commit, null, 'there is no repository, so there is no commit — and that is not an error');
    assert.strictEqual(result.trash.status, TRASH_STATUS.OK);
    assert.strictEqual(result.trash.moved.length, 3);
    assert.deepStrictEqual(await listFiles(root), ['keep-me.md']);
    assert.match(result.undo.how, /restore-from-Trash/);
  });

  test('undo of a repo-less Apply is restore-from-Trash', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const findings = stamp(JUNK.map((p) => makeFinding(scan, { action: 'trash', path: p })), RUN);
    await applyApproved({ rootPath: root, git: null, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });

    const undone = await undoApply({ rootPath: root, git: null, commit: null, runId: RUN });

    assert.strictEqual(undone.status, UNDO_STATUS.RESTORED, undone.message);
    assert.strictEqual(undone.branch, UNDO_BRANCH.TRASH_RESTORE);
    assert.strictEqual(await readOrNull(path.join(root, JUNK[0])), 'AAAA\n');
    assert.strictEqual(await readOrNull(path.join(root, JUNK[1])), 'BBBB\n');
    assert.strictEqual(await readOrNull(path.join(root, JUNK[2])), 'CCCC\n');
  });

  test('an operation that genuinely needs git is still refused, naming it', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const findings = stamp([makeFinding(scan, { action: 'save', path: 'keep-me.md' })], RUN);
    const result = await applyApproved({
      rootPath: root, git: null, runId: RUN, snapshot: scan.snapshot,
      findings, approvals: approvalsFor(findings),
    });

    assert.strictEqual(result.status, APPLY_STATUS.REFUSED);
    assert.strictEqual(result.code, APPLY_REFUSAL.NO_GIT);
    assert.match(result.message, /keep-me\.md/, 'the refusal names the operation it refused');
    assert.match(result.message, /optional upgrade/, 'and states that Bootstrap is not a gate');
  });
});

describe('Apply in a repo: ONE commit for git-held content PLUS one Trash move-set', () => {
  let root;
  let reportDir;

  beforeEach(async () => {
    root = await makeTempRoot('tidy-idy-w4-mixed-');
    reportDir = reportDirFor(root);
    await initRepo(root);
    await write(root, 'tracked-junk.txt', 'tracked junk\n');
    await write(root, 'keep.md', '# keep\n');
    await commitAll(root, 'baseline');
    await write(root, 'untracked-junk.log', 'untracked junk\n');
  });

  test('both halves land together, and the commit count goes up by exactly one', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const before = await commitCount(root);

    const findings = stamp([
      makeFinding(scan, { action: 'remove', path: 'tracked-junk.txt' }),
      makeFinding(scan, { action: 'trash', path: 'untracked-junk.log' }),
    ], RUN);

    const result = await applyApproved({
      rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot,
      findings, approvals: approvalsFor(findings),
    });

    assert.strictEqual(result.status, APPLY_STATUS.APPLIED, JSON.stringify(result, null, 2));
    assert.ok(result.commit, 'the git-held removal became a commit');
    assert.strictEqual(await commitCount(root), before + 1, 'exactly ONE commit per Apply');
    assert.strictEqual(result.trash.status, TRASH_STATUS.OK);
    assert.deepStrictEqual(await listFiles(root), ['keep.md']);
    assert.strictEqual(result.consentScope.ok, true, JSON.stringify(result.consentScope.violations, null, 2));
  });

  test('the tool\'s own state directory is self-ignoring, so git never sees the Trash', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const findings = stamp([makeFinding(scan, { action: 'trash', path: 'untracked-junk.log' })], RUN);
    await applyApproved({ rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });

    const status = await git(root, ['status', '--porcelain']);
    assert.ok(!/\.tidy-idy/.test(status), `the Trash must not appear in git status:\n${status}`);
    // …and it did that WITHOUT editing the user's .gitignore (consent scope).
    assert.strictEqual(await readOrNull(path.join(root, '.gitignore')), null);
  });

  test('undo reverts the commit AND restores from the Trash, in one operation', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const findings = stamp([
      makeFinding(scan, { action: 'remove', path: 'tracked-junk.txt' }),
      makeFinding(scan, { action: 'trash', path: 'untracked-junk.log' }),
    ], RUN);
    const applied = await applyApproved({ rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });

    const undone = await undoApply({ rootPath: root, git: scan.git, commit: applied.commit, runId: RUN });

    assert.strictEqual(undone.status, UNDO_STATUS.REVERTED, undone.message);
    assert.strictEqual(await readOrNull(path.join(root, 'tracked-junk.txt')), 'tracked junk\n', 'git-held content came back by revert');
    assert.strictEqual(await readOrNull(path.join(root, 'untracked-junk.log')), 'untracked junk\n', 'non-git-held content came back from the Trash');
    assert.strictEqual(undone.trash.status, TRASH_STATUS.OK);
  });

  test('a Trash pre-flight failure aborts the WHOLE Apply — no commit, no move', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const findings = stamp([
      makeFinding(scan, { action: 'remove', path: 'tracked-junk.txt' }),
      makeFinding(scan, { action: 'trash', path: 'untracked-junk.log' }),
    ], RUN);
    // Someone has already put something in the Trash slot this Apply would use.
    await write(path.join(trashFilesDirFor(reportDir, RUN)), 'untracked-junk.log', 'SOMETHING ELSE\n');

    const before = await commitCount(root);
    const result = await applyApproved({
      rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot,
      findings, approvals: approvalsFor(findings),
    });

    assert.strictEqual(result.status, APPLY_STATUS.REFUSED);
    assert.strictEqual(result.code, APPLY_REFUSAL.TRASH_PREFLIGHT);
    assert.strictEqual(await commitCount(root), before, 'the git half was NOT applied — one Apply is all-or-nothing');
    assert.strictEqual(await readOrNull(path.join(root, 'tracked-junk.txt')), 'tracked junk\n');
    assert.strictEqual(await readOrNull(path.join(root, 'untracked-junk.log')), 'untracked junk\n');
  });
});
