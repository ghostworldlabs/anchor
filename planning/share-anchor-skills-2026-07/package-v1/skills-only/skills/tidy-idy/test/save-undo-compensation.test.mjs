// test/save-undo-compensation.test.mjs — Wave 9: SAVE-undo compensation round-trips.
//
// The frozen deliverable, verbatim: "the SAVE-undo compensation round-trips
// (untracked and dirty-modified pre-states restored bit-identical) wired into
// the same CI run."
//
// Decision #8 (see engine/apply/undo.mjs): a tidy commit containing SAVE
// operations does NOT undo to "the file is gone / old" — it undoes to the exact
// PRE-APPLY state, which was DIRTY. A SAVE'd untracked file was untracked; a
// SAVE'd modified-tracked file had an unstaged modification. So after the clean
// revert, each SAVE'd path is re-materialised from `<C>:<path>` into the working
// tree UNSTAGED — the precise state it was in before Apply.
//
// This suite proves the round-trip for BOTH pre-states the criterion names,
// asserting not only the bytes (bit-identical) but the git TRACKING CLASS the
// path returns to — because "restored" means the pre-Apply state in full, and a
// file that came back staged, or committed, would be a different state wearing
// the right bytes.
//
// (The protection-monotonicity property test — the other half of this
// deliverable — lives in test/engine-protection.test.mjs and runs in the same
// `node --test` invocation; it is not duplicated here.)

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import { applyApproved, APPLY_STATUS } from '../engine/apply/executor.mjs';
import { undoApply, UNDO_STATUS } from '../engine/apply/undo.mjs';
import { TRACKING } from '../engine/porcelain.mjs';

import {
  makeTempRoot, rmTempRoot, write, git, initRepo, commitAll,
  scanFixture, makeFinding, stamp, approvalsFor,
} from './helpers/apply-fixture.mjs';

const RUN = 'run-save-undo-0001';

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

/** The git status line for one path (porcelain v1), or null if not reported. */
async function statusFor(root, rel) {
  const out = await git(root, ['status', '--porcelain', '--', rel]);
  const line = out.split('\n').find((l) => l.trim().endsWith(rel));
  return line || null;
}

/**
 * A folder with the two pre-states the criterion names:
 *   • an UNTRACKED useful script;
 *   • a tracked file with an UNSTAGED modification (dirty-modified).
 */
async function folderWithSaveCandidates() {
  const root = await newRoot('tidy-idy-w9-save-undo-');
  await initRepo(root);
  await write(root, 'settings.json', '{"retries": 3}\n');
  await commitAll(root, 'baseline');
  // pre-state A: untracked content git has never seen
  await write(root, 'tools/backup.sh', '#!/bin/sh\ntar czf backup.tgz src\n');
  // pre-state B: a tracked file, modified but unstaged
  await write(root, 'settings.json', '{"retries": 5}\n');
  return root;
}

const UNTRACKED = 'tools/backup.sh';
const UNTRACKED_BYTES = '#!/bin/sh\ntar czf backup.tgz src\n';
const MODIFIED = 'settings.json';
const MODIFIED_BYTES = '{"retries": 5}\n';

describe('a SAVE Apply commits the current content of both pre-states', () => {
  let root;
  let applied;

  before(async () => {
    root = await folderWithSaveCandidates();
    const scan = await scanFixture(root, { runId: RUN });
    // The fixture snapshot captured both files as they are NOW — untracked and
    // modified — so revalidation compares against the exact bytes on the tiles.
    assert.strictEqual(scan.porcelain.classify(UNTRACKED), TRACKING.UNTRACKED);
    assert.strictEqual(scan.porcelain.classify(MODIFIED), TRACKING.TRACKED_MODIFIED);

    const findings = stamp([
      makeFinding(scan, { action: 'save', path: UNTRACKED }),
      makeFinding(scan, { action: 'save', path: MODIFIED }),
    ], RUN);
    applied = await applyApproved({
      rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot,
      findings, approvals: approvalsFor(findings),
    });
  });

  test('both SAVEs land in ONE commit and the tree is clean afterwards', async () => {
    assert.strictEqual(applied.status, APPLY_STATUS.APPLIED, JSON.stringify(applied, null, 2));
    assert.ok(applied.commit, 'the SAVE became a commit');
    // Committed: git now holds both, clean.
    assert.strictEqual(await statusFor(root, UNTRACKED), null, 'the untracked file was committed — no longer reported');
    assert.strictEqual(await statusFor(root, MODIFIED), null, 'the modification was committed — no longer reported');
  });

  test('undo re-materialises BOTH pre-states into the working tree, unstaged and bit-identical', async () => {
    const undone = await undoApply({ rootPath: root, git: (await scanFixture(root, { runId: RUN })).git, commit: applied.commit, runId: RUN });

    assert.strictEqual(undone.status, UNDO_STATUS.REVERTED, undone.message);
    assert.strictEqual(undone.compensated.length, 2, 'both SAVE paths were compensated (decision #8)');
    for (const c of undone.compensated) assert.strictEqual(c.staged, false, `${c.path} must come back UNSTAGED`);

    // pre-state A restored bit-identical AND back to untracked.
    assert.strictEqual(await readOrNull(path.join(root, UNTRACKED)), UNTRACKED_BYTES, 'the untracked script came back byte-for-byte');
    const untrackedStatus = await statusFor(root, UNTRACKED);
    assert.ok(untrackedStatus && untrackedStatus.startsWith('??'),
      `the SAVE'd untracked file must return to the UNTRACKED class, got: ${JSON.stringify(untrackedStatus)}`);

    // pre-state B restored bit-identical AND back to tracked-but-modified (unstaged).
    assert.strictEqual(await readOrNull(path.join(root, MODIFIED)), MODIFIED_BYTES, 'the modified file came back byte-for-byte');
    const modifiedStatus = await statusFor(root, MODIFIED);
    assert.ok(modifiedStatus && /^ M/.test(modifiedStatus),
      `the SAVE'd modification must return as an UNSTAGED modification (index at baseline, worktree modified), got: ${JSON.stringify(modifiedStatus)}`);
  });
});

describe('the compensation writes only git-held content, so it can lose nothing', () => {
  test('a SAVE undo restores the exact committed bytes, not whatever is on disk at undo time', async () => {
    const root = await folderWithSaveCandidates();
    const scan = await scanFixture(root, { runId: RUN });
    const findings = stamp([makeFinding(scan, { action: 'save', path: UNTRACKED })], RUN);
    const applied = await applyApproved({ rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(applied.status, APPLY_STATUS.APPLIED, applied.message);

    const undone = await undoApply({ rootPath: root, git: scan.git, commit: applied.commit, runId: RUN });
    assert.strictEqual(undone.status, UNDO_STATUS.REVERTED, undone.message);
    // The source of the compensation is `<commit>:<path>` — the content git holds
    // — which is exactly why the compensation itself cannot lose anything.
    assert.strictEqual(await readOrNull(path.join(root, UNTRACKED)), UNTRACKED_BYTES);
  });
});
