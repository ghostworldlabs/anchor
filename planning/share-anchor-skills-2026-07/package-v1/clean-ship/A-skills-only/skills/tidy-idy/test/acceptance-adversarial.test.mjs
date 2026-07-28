// test/acceptance-adversarial.test.mjs — Wave 9: the adversarial acceptance cells.
//
// The frozen deliverable: "Adversarial cells, one per canonical-table row plus
// Trash, Bootstrap, and reorg rows: edit-during-Apply, stage-during-Apply,
// undo-after-later-commits, Bootstrap-undo-after-new-work, kill-mid-Trash,
// restore-onto-reoccupied-path, post-Apply-edit-then-undo run separately against
// EVERY undo/restore path (git-revert undo, SAVE compensation, Trash restore,
// reorg move-back, Bootstrap undo — each must refuse per the no-clobber
// invariant, never overwrite the edit), mixed-reorg-kill-after-commit (must roll
// forward), mixed-reorg-kill-before-commit (must roll back bit-identical) — any
// sequence losing content git holds (or Trash holds) is a release blocker."
//
// Each test below CONSTRUCTS A CONCRETE LOSING SEQUENCE of user actions and
// asserts the tool loses nothing git or the Trash holds, and overwrites no
// post-Apply edit. Interruptions are simulated by BUILDING THE STATE A KILL
// LEAVES (the two-phase journal record plus the on-disk / in-git facts), exactly
// as the Wave-4 and Wave-8 suites do — a real SIGKILL would be timing-dependent
// and prove nothing repeatable.
//
// Several of these sequences are also instantiated in the per-wave suites
// (apply-trash, apply-bootstrap, apply-reorg). They are re-asserted here as ONE
// acceptance sweep because the release-blocker claim — "no losing sequence
// survives, across EVERY undo path" — is a property of the whole system, and an
// acceptance harness that trusted each wave to have covered its own corner would
// not actually be asserting it.

import { test, describe, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import { applyApproved, APPLY_STATUS } from '../engine/apply/executor.mjs';
import { undoApply, UNDO_STATUS, UNDO_REFUSAL } from '../engine/apply/undo.mjs';
import { STALE_REASON } from '../engine/apply/revalidate.mjs';
import {
  applyReorgMove, undoReorgMove, recoverReorgApply,
  REORG_STATUS, REORG_RECOVERY, REORG_APPLY_STATE, REORG_CONTENT_CLASS,
} from '../engine/apply/reorg.mjs';
import { applyBootstrap, undoBootstrap, BOOTSTRAP_STATUS } from '../engine/apply/bootstrap.mjs';
import { openJournal } from '../engine/apply/journal.mjs';
import { openGit } from '../engine/git.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';

import {
  makeTempRoot, rmTempRoot, write, git, initRepo, commitAll,
  scanFixture, makeFinding, stamp, approvalsFor, listFiles,
} from './helpers/apply-fixture.mjs';

const tempRoots = [];
async function newRoot(prefix) {
  const root = await makeTempRoot(prefix);
  tempRoots.push(root);
  return root;
}
after(async () => { for (const r of tempRoots) await rmTempRoot(r); });

async function readOrNull(abs) {
  try { return (await fs.readFile(abs)).toString('utf8'); } catch { return null; }
}

// ────────────────────────────────────────────────────────────────────────────
// 1. Revalidation adversaries — a change between scan and Apply loses nothing.
// ────────────────────────────────────────────────────────────────────────────

describe('edit-during-Apply · a file edited after the scan is dropped as stale, never applied', () => {
  test('a REMOVE of a file edited after the scan does not fire; the edit survives', async () => {
    const root = await newRoot('tidy-idy-adv-edit-');
    await initRepo(root);
    await write(root, 'dead.mjs', 'v1 — the bytes on the tile\n');
    await commitAll(root, 'baseline');

    const scan = await scanFixture(root, { runId: 'run-edit' });
    const findings = stamp([makeFinding(scan, { action: 'remove', path: 'dead.mjs' })], 'run-edit');

    // The user edits dead.mjs AFTER approving, BEFORE Apply lands.
    await write(root, 'dead.mjs', 'v2 — forty minutes of new work git has never seen\n');

    const result = await applyApproved({
      rootPath: root, git: scan.git, runId: 'run-edit', snapshot: scan.snapshot,
      findings, approvals: approvalsFor(findings),
    });

    assert.strictEqual(result.status, APPLY_STATUS.NO_OP, JSON.stringify(result, null, 2));
    assert.strictEqual(result.stale[0].reason, STALE_REASON.CONTENT_CHANGED);
    assert.strictEqual(await readOrNull(path.join(root, 'dead.mjs')),
      'v2 — forty minutes of new work git has never seen\n',
      'the edit made between approval and Apply was never removed — the fail-safe direction is "do less"');
  });
});

describe('stage-during-Apply · a path STAGED after the scan is dropped, folding in nothing', () => {
  test('a REMOVE of a file staged after the scan does not fire; the staged content is intact', async () => {
    const root = await newRoot('tidy-idy-adv-stage-');
    await initRepo(root);
    await write(root, 'dead.mjs', 'v1\n');
    await commitAll(root, 'baseline');

    const scan = await scanFixture(root, { runId: 'run-stage' });
    const findings = stamp([makeFinding(scan, { action: 'remove', path: 'dead.mjs' })], 'run-stage');

    // The user stages a NEW version, then restores the working tree to the scanned
    // bytes: the content hash still matches S, but git's class is now STAGED — an
    // intention the tool was never shown.
    await write(root, 'dead.mjs', 'v2 — staged work\n');
    await git(root, ['add', 'dead.mjs']);
    await write(root, 'dead.mjs', 'v1\n');

    const result = await applyApproved({
      rootPath: root, git: scan.git, runId: 'run-stage', snapshot: scan.snapshot,
      findings, approvals: approvalsFor(findings),
    });

    assert.strictEqual(result.status, APPLY_STATUS.NO_OP, JSON.stringify(result, null, 2));
    assert.strictEqual(result.stale[0].reason, STALE_REASON.NEWLY_STAGED,
      'a newly-staged path is dropped rather than folded into a tidy commit the user never approved');
    assert.strictEqual((await git(root, ['show', ':dead.mjs'])), 'v2 — staged work\n',
      'the staged content git holds was never touched');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 2. undo-after-later-commits — a later commit is never discarded by an undo.
// ────────────────────────────────────────────────────────────────────────────

describe('undo-after-later-commits · undoing a tidy commit under later work is refused', () => {
  test('a commit made after the tidy commit is never discarded — undo refuses, naming the conflict', async () => {
    const root = await newRoot('tidy-idy-adv-later-');
    await initRepo(root);
    await write(root, 'dead.mjs', 'v1\n');
    await commitAll(root, 'baseline');

    const scan = await scanFixture(root, { runId: 'run-later' });
    const findings = stamp([makeFinding(scan, { action: 'remove', path: 'dead.mjs' })], 'run-later');
    const applied = await applyApproved({ rootPath: root, git: scan.git, runId: 'run-later', snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(applied.status, APPLY_STATUS.APPLIED, applied.message);

    // The user re-creates dead.mjs with DIFFERENT content and commits it — real
    // later work on the same path.
    await write(root, 'dead.mjs', 'brand new work, committed after the tidy commit\n');
    await commitAll(root, 'later work');
    const headAfterLater = (await git(root, ['rev-parse', 'HEAD'])).trim();

    const undone = await undoApply({ rootPath: root, git: scan.git, commit: applied.commit, runId: 'run-later' });

    assert.strictEqual(undone.status, UNDO_STATUS.REFUSED, JSON.stringify(undone, null, 2));
    assert.strictEqual(undone.code, UNDO_REFUSAL.LATER_COMMIT_CONFLICT);
    assert.strictEqual(await readOrNull(path.join(root, 'dead.mjs')), 'brand new work, committed after the tidy commit\n',
      'the later work is exactly as the user left it');
    assert.strictEqual((await git(root, ['rev-parse', 'HEAD'])).trim(), headAfterLater, 'no revert commit was written');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 3. post-Apply-edit-then-undo — run separately against EVERY undo/restore path.
//    Each path must REFUSE per the no-clobber invariant and overwrite nothing.
// ────────────────────────────────────────────────────────────────────────────

describe('post-Apply-edit-then-undo · no undo path overwrites content created after the Apply', () => {
  const EDIT = 'MY NEW WORK — the undo must not clobber this\n';

  test('git-revert undo path · a re-occupied removed path refuses, edit preserved', async () => {
    const root = await newRoot('tidy-idy-adv-noclobber-revert-');
    await initRepo(root);
    await write(root, 'dead.mjs', 'v1\n');
    await commitAll(root, 'baseline');
    const scan = await scanFixture(root, { runId: 'run-nc-revert' });
    const findings = stamp([makeFinding(scan, { action: 'remove', path: 'dead.mjs' })], 'run-nc-revert');
    const applied = await applyApproved({ rootPath: root, git: scan.git, runId: 'run-nc-revert', snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(applied.status, APPLY_STATUS.APPLIED, applied.message);

    await write(root, 'dead.mjs', EDIT); // the user re-created the path with new content

    const undone = await undoApply({ rootPath: root, git: scan.git, commit: applied.commit, runId: 'run-nc-revert' });
    assert.strictEqual(undone.status, UNDO_STATUS.REFUSED, JSON.stringify(undone, null, 2));
    assert.strictEqual(await readOrNull(path.join(root, 'dead.mjs')), EDIT);
  });

  test('SAVE compensation path · a re-edited SAVE\'d path refuses, edit preserved', async () => {
    const root = await newRoot('tidy-idy-adv-noclobber-save-');
    await initRepo(root);
    await write(root, 'keep.md', '# keep\n');
    await commitAll(root, 'baseline');
    await write(root, 'tools/backup.sh', '#!/bin/sh\ntar czf b.tgz src\n'); // untracked SAVE candidate

    const scan = await scanFixture(root, { runId: 'run-nc-save' });
    const findings = stamp([makeFinding(scan, { action: 'save', path: 'tools/backup.sh' })], 'run-nc-save');
    const applied = await applyApproved({ rootPath: root, git: scan.git, runId: 'run-nc-save', snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(applied.status, APPLY_STATUS.APPLIED, applied.message);

    await write(root, 'tools/backup.sh', EDIT); // the user edited the SAVE'd file after the Apply

    const undone = await undoApply({ rootPath: root, git: scan.git, commit: applied.commit, runId: 'run-nc-save' });
    assert.strictEqual(undone.status, UNDO_STATUS.REFUSED, JSON.stringify(undone, null, 2));
    assert.strictEqual(await readOrNull(path.join(root, 'tools/backup.sh')), EDIT,
      'the compensation never overwrote the post-Apply edit');
  });

  test('Trash restore path · a re-occupied original path refuses, edit preserved', async () => {
    const root = await newRoot('tidy-idy-adv-noclobber-trash-');
    await write(root, 'junk.txt', 'JUNK\n'); // non-git folder
    await write(root, 'keep.md', '# keep\n');

    const scan = await scanFixture(root, { runId: 'run-nc-trash' });
    const findings = stamp([makeFinding(scan, { action: 'trash', path: 'junk.txt' })], 'run-nc-trash');
    const applied = await applyApproved({ rootPath: root, git: null, runId: 'run-nc-trash', snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(applied.status, APPLY_STATUS.APPLIED, applied.message);

    await write(root, 'junk.txt', EDIT); // the user recreated a file at the removed path

    // The ONLY trashed path is reoccupied, so restore-from-Trash refuses it and
    // (nothing else to restore) the undo as a whole is REFUSED — touching nothing.
    const undone = await undoApply({ rootPath: root, git: null, commit: null, runId: 'run-nc-trash' });
    assert.strictEqual(undone.status, UNDO_STATUS.REFUSED, JSON.stringify(undone, null, 2));
    assert.strictEqual(undone.refused.length, 1);
    assert.strictEqual(await readOrNull(path.join(root, 'junk.txt')), EDIT,
      'restore-from-Trash refused rather than overwrite the user\'s new file');
  });

  test('reorg move-back path · a re-occupied original path refuses, edit preserved', async () => {
    const root = await newRoot('tidy-idy-adv-noclobber-reorg-');
    await initRepo(root);
    await write(root, 'keep.md', '# keep\n');
    await commitAll(root, 'baseline');
    await write(root, 'pics/p.png', 'P\n');
    await write(root, 'pics/q.png', 'Q\n');
    const reportDir = reportDirFor(root);
    const scan = await scanFixture(root, { runId: 'run-nc-reorg' });
    const members = scan.paths.filter((p) => p === 'pics' || p.startsWith('pics/')).sort();
    const finding = {
      stage: 'reorg', kind: 'reorg-proposal', action: 'reorg', path: 'pics',
      move: { from: 'pics', to: 'assets/pics' }, members,
      referenceScan: { hitCount: 0, hits: [], truncated: false }, eligible: true,
      overrideRequired: false, bulkApprovable: true, defaultChecked: false,
    };
    const applied = await applyReorgMove({ rootPath: root, git: scan.git, runId: 'run-nc-reorg', reportDir, finding, snapshot: scan.snapshot, porcelain: scan.porcelain });
    assert.strictEqual(applied.status, REORG_STATUS.APPLIED, JSON.stringify(applied, null, 2));

    await write(root, 'pics/p.png', EDIT); // the user recreated the original path

    const undone = await undoReorgMove({ rootPath: root, git: scan.git, runId: 'run-nc-reorg', reportDir });
    assert.strictEqual(undone.status, REORG_STATUS.PARTIAL, JSON.stringify(undone, null, 2));
    assert.strictEqual(undone.refused[0].path, 'pics/p.png');
    assert.strictEqual(await readOrNull(path.join(root, 'pics/p.png')), EDIT, 'the move-back never overwrote the edit');
    assert.strictEqual(await readOrNull(path.join(root, 'pics/q.png')), 'Q\n', 'the OTHER path still moved back');
  });

  test('Bootstrap undo path · a .gitignore edited after Bootstrap refuses, edit preserved', async () => {
    const root = await newRoot('tidy-idy-adv-noclobber-boot-');
    await write(root, 'src/main.mjs', 'export const go = 1;\n');
    await write(root, '.gitignore', 'node_modules/\n');
    const applied = await applyBootstrap({ rootPath: root, runId: 'run-nc-boot', approved: true });
    assert.strictEqual(applied.status, BOOTSTRAP_STATUS.BOOTSTRAPPED, applied.message);

    const mine = 'node_modules/\n# my own edit after Bootstrap\ndist/\n';
    await write(root, '.gitignore', mine);

    const undone = await undoBootstrap({ rootPath: root, runId: 'run-nc-boot' });
    assert.strictEqual(undone.status, BOOTSTRAP_STATUS.PARTIAL, JSON.stringify(undone, null, 2));
    assert.strictEqual(undone.refused[0].path, '.gitignore');
    assert.strictEqual(await readOrNull(path.join(root, '.gitignore')), mine,
      'the .gitignore edit made after Bootstrap survives — the undo never silently overwrote it');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 4. Bootstrap-undo-after-new-work — undo refuses once HEAD has moved past B.
// ────────────────────────────────────────────────────────────────────────────

describe('Bootstrap-undo-after-new-work · undo is refused once new commits stack on B', () => {
  test('committing new work after Bootstrap makes undo refuse entirely, discarding nothing', async () => {
    const root = await newRoot('tidy-idy-adv-boot-newwork-');
    await write(root, 'src/main.mjs', 'export const go = 1;\n');
    const applied = await applyBootstrap({ rootPath: root, runId: 'run-boot-nw', approved: true });
    assert.strictEqual(applied.status, BOOTSTRAP_STATUS.BOOTSTRAPPED, applied.message);

    await write(root, 'new-work.txt', 'work git now holds\n');
    await git(root, ['add', '-A']);
    await git(root, ['-c', 'user.name=t', '-c', 'user.email=<email>', 'commit', '-m', 'later work']);

    const undone = await undoBootstrap({ rootPath: root, runId: 'run-boot-nw' });
    assert.strictEqual(undone.status, BOOTSTRAP_STATUS.REFUSED, JSON.stringify(undone, null, 2));
    assert.strictEqual(await readOrNull(path.join(root, 'new-work.txt')), 'work git now holds\n', 'the later work is untouched');
    assert.strictEqual((await readOrNull(path.join(root, 'src/main.mjs'))), 'export const go = 1;\n');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 5. mixed-reorg kill-around-commit — resolves to fully-applied OR bit-identical.
//    Interruption is simulated by authoring the two-phase journal to the state a
//    kill leaves, plus the matching on-disk / in-git facts, then recovering.
// ────────────────────────────────────────────────────────────────────────────

async function mixedRepo(prefix) {
  const root = await newRoot(prefix);
  await initRepo(root);
  await write(root, 'keep.md', '# keep\n');
  await write(root, 'bundle/t1.png', 'T1\n');
  await write(root, 'bundle/t2.png', 'T2\n');
  await commitAll(root, 'baseline');          // t1,t2 tracked-clean
  await write(root, 'bundle/u1.png', 'U1\n'); // untracked
  await write(root, 'bundle/u2.png', 'U2\n');
  return root;
}
const MIXED_APPLIED = ['assets/bundle/t1.png', 'assets/bundle/t2.png', 'assets/bundle/u1.png', 'assets/bundle/u2.png', 'keep.md'];
const FS_MOVES = [
  { from: 'bundle/u1.png', to: 'assets/bundle/u1.png' },
  { from: 'bundle/u2.png', to: 'assets/bundle/u2.png' },
];
const GIT_MOVES = [
  { from: 'bundle/t1.png', to: 'assets/bundle/t1.png' },
  { from: 'bundle/t2.png', to: 'assets/bundle/t2.png' },
];

async function head(root) { return (await git(root, ['rev-parse', 'HEAD'])).trim(); }
async function ref(root) { return (await git(root, ['symbolic-ref', 'HEAD'])).trim(); }

async function contentsOf(root) {
  const out = {};
  for (const f of await listFiles(root)) out[f] = await readOrNull(path.join(root, f));
  return out;
}

async function fsMove(root, mv) {
  await fs.mkdir(path.join(root, path.dirname(mv.to)), { recursive: true });
  await fs.rename(path.join(root, mv.from), path.join(root, mv.to));
}

async function authorJournal(reportDir, runId, records) {
  const j = await openJournal({ reportDir, runId, kind: 'reorg' });
  for (const [type, data] of records) await j.append(type, data);
}

/** Commit the tracked re-pathing so the branch tip genuinely IS commit C. */
async function commitTrackedMove(root) {
  for (const mv of GIT_MOVES) {
    await fs.mkdir(path.join(root, path.dirname(mv.to)), { recursive: true });
    await git(root, ['mv', mv.from, mv.to]);
  }
  await git(root, ['commit', '-m', 'tidy-idy reorg: move bundle → assets/bundle']);
  return head(root);
}

describe('mixed-reorg-kill-after-commit · rolls FORWARD to fully-applied', () => {
  test('killed after the commit lands, one untracked file still un-moved → fully-applied, nothing lost', async () => {
    const RUN = 'run-adv-reorg-fwd';
    const root = await mixedRepo('tidy-idy-adv-reorg-fwd-');
    const reportDir = reportDirFor(root);
    const parent = await head(root);
    const r0 = await ref(root);
    const C = await commitTrackedMove(root);  // C IS the branch tip
    await fsMove(root, FS_MOVES[0]);          // one of two untracked moved; then killed

    await authorJournal(reportDir, RUN, [
      ['state', { state: REORG_APPLY_STATE.PLANNED, move: { from: 'bundle', to: 'assets/bundle' }, mixed: true, head: parent, ref: r0, fsMoves: FS_MOVES, gitMoves: GIT_MOVES }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.COMMITTED, commit: C, parent, ref: r0 }],
      ['state', { state: REORG_APPLY_STATE.REF_ADVANCED, commit: C, ref: r0 }],
    ]);

    const recovered = await recoverReorgApply({ rootPath: root, git: await openGit(root), runId: RUN, reportDir });
    assert.strictEqual(recovered.recovery, REORG_RECOVERY.ROLL_FORWARD, JSON.stringify(recovered, null, 2));
    assert.strictEqual(recovered.status, REORG_STATUS.APPLIED);
    assert.deepStrictEqual(await listFiles(root), MIXED_APPLIED, 'no file lost, none duplicated');
    assert.strictEqual(await readOrNull(path.join(root, 'assets/bundle/u2.png')), 'U2\n', 'the not-yet-moved file was carried forward');
  });
});

describe('mixed-reorg-kill-before-commit · rolls BACK to bit-identical', () => {
  test('killed before the commit landed → completed fs moves roll back, nothing committed', async () => {
    const RUN = 'run-adv-reorg-back';
    const root = await mixedRepo('tidy-idy-adv-reorg-back-');
    const reportDir = reportDirFor(root);
    const before = await contentsOf(root);
    const baseline = await head(root);

    // The fs half ran; the commit never happened (NO committed record).
    await fsMove(root, FS_MOVES[0]);
    await fsMove(root, FS_MOVES[1]);
    await authorJournal(reportDir, RUN, [
      ['state', { state: REORG_APPLY_STATE.PLANNED, move: { from: 'bundle', to: 'assets/bundle' }, mixed: true, head: baseline, ref: await ref(root), fsMoves: FS_MOVES, gitMoves: GIT_MOVES, classes: [REORG_CONTENT_CLASS.TRACKED, REORG_CONTENT_CLASS.UNTRACKED] }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['fs-move', { from: FS_MOVES[1].from, to: FS_MOVES[1].to, state: 'done', k: 2, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.FS_DONE, moved: 2 }],
    ]);

    const recovered = await recoverReorgApply({ rootPath: root, git: await openGit(root), runId: RUN, reportDir });
    assert.strictEqual(recovered.recovery, REORG_RECOVERY.ROLL_BACK, JSON.stringify(recovered, null, 2));
    assert.strictEqual(await head(root), baseline, 'nothing was committed');
    assert.deepStrictEqual(await contentsOf(root), before, 'the tree is bit-identical to before the reorg began');
  });
});
