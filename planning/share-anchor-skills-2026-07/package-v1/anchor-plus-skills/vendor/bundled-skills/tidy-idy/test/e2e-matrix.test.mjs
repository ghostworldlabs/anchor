// test/e2e-matrix.test.mjs — Wave 9: the end-to-end acceptance matrix.
//
// The frozen deliverable: the CI end-to-end matrix
//
//   {Foundry git repo, plain git repo, non-git folder, non-git inside an
//    enclosing repo, dirty tree, nested repo/junction}
//     × {scan, approve subset, Apply, revert/restore}
//
// with EACH CELL asserting its invariant:
//   • scan is zero-write (the metadata tripwire proves it, not a comment);
//   • one commit per Apply, plus one atomic Trash move-set for non-git content;
//   • a mixed-batch failure commits NOTHING;
//   • an excluded subtree is untouched and recorded;
//   • git:null semantics — a repo-less Apply refuses only what genuinely needs
//     git, and never touches an enclosing repository's history;
//   • revert/restore returns the working tree byte-for-byte;
//   • the consent-scope porcelain-class diff holds after every Apply;
//   • an undo-refusal branch leaves the working tree exactly as it was.
//
// These cells are built on the SAME library surface the panel calls (scanFixture
// → applyApproved → undoApply), so a green cell is a claim about the shipping
// code, not about a test double. The adversarial losing-sequence cells live in
// test/acceptance-adversarial.test.mjs; the reorg crash matrix in
// test/apply-reorg.test.mjs. Together they are the acceptance spec.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import { runPipeline } from '../engine/pipeline.mjs';
import { scanStage } from '../engine/stages/scan.stage.mjs';
import { hygieneStage } from '../engine/stages/hygiene.stage.mjs';
import { heuristicStage } from '../engine/stages/heuristic.stage.mjs';
import { applyApproved, APPLY_STATUS, APPLY_REFUSAL } from '../engine/apply/executor.mjs';
import { undoApply, UNDO_STATUS, UNDO_BRANCH, UNDO_REFUSAL } from '../engine/apply/undo.mjs';
import { trashFilesDirFor } from '../engine/apply/trash.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';

import {
  makeTempRoot, rmTempRoot, write, git, initRepo, commitAll,
  scanFixture, makeFinding, stamp, approvalsFor, listFiles, commitCount, repoState,
} from './helpers/apply-fixture.mjs';

const SCAN_STAGES = [scanStage, hygieneStage, heuristicStage];

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

/** A comparable snapshot of the working tree (files + bytes), git-agnostic. */
async function workingTree(root) {
  const files = await listFiles(root);
  const contents = {};
  for (const f of files) contents[f] = await readOrNull(path.join(root, f));
  return { files, contents };
}

/** Prove a scan wrote nothing: the tripwire recorded no violation and the tree is intact. */
async function assertZeroWriteScan(root, { mode } = {}) {
  const before = await workingTree(root);
  const envelope = await runPipeline({ rootPath: root, ...(mode ? { mode } : {}), agent: async () => [], stages: SCAN_STAGES });
  assert.notStrictEqual(envelope.status, 'failed', JSON.stringify(envelope.stages.flatMap((s) => s.errors || []), null, 2));
  assert.deepStrictEqual(envelope.tripwire.violations, [],
    'the metadata tripwire must record ZERO write attempts during a scan');
  assert.deepStrictEqual(await workingTree(root), before, 'a scan must not change a single byte of the tree');
  return envelope;
}

// ────────────────────────────────────────────────────────────────────────────
// Row 1 — a Foundry git repo (has a North-Star; governance surfaces protected).
// ────────────────────────────────────────────────────────────────────────────

describe('E2E · Foundry git repo', () => {
  let root;
  const RUN = 'run-e2e-foundry';

  before(async () => {
    root = await newRoot('tidy-idy-e2e-foundry-');
    await initRepo(root);
    await write(root, 'NORTH-STAR.md', '# North Star\n\nShip the thing.\n');
    await write(root, 'SKILL.md', '# skill\n');
    await write(root, 'src/keep.mjs', 'export const keep = 1;\n');
    await write(root, 'dead.mjs', '// superseded, tracked\n');
    await commitAll(root, 'baseline');
    await write(root, 'untracked-junk.log', 'junk\n');
  });

  test('scan · is zero-write (Foundry mode selected by the North-Star marker)', async () => {
    const envelope = await assertZeroWriteScan(root, { mode: 'north-star' });
    assert.strictEqual(envelope.mode, 'north-star', 'a folder with a North-Star runs in north-star mode');
  });

  test('Apply · ONE commit for the tracked half PLUS one Trash move-set, governance untouched', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const before = await commitCount(root);
    const findings = stamp([
      makeFinding(scan, { action: 'remove', path: 'dead.mjs' }),
      makeFinding(scan, { action: 'trash', path: 'untracked-junk.log' }),
    ], RUN);

    const result = await applyApproved({
      rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot,
      findings, approvals: approvalsFor(findings),
    });

    assert.strictEqual(result.status, APPLY_STATUS.APPLIED, JSON.stringify(result, null, 2));
    assert.strictEqual(await commitCount(root), before + 1, 'EXACTLY one commit per Apply');
    assert.strictEqual(result.consentScope.ok, true, JSON.stringify(result.consentScope, null, 2));
    // The North-Star and skill definition are protected — the tool never eats the
    // document it judges alignment against.
    assert.strictEqual(await readOrNull(path.join(root, 'NORTH-STAR.md')), '# North Star\n\nShip the thing.\n');
    assert.strictEqual(await readOrNull(path.join(root, 'SKILL.md')), '# skill\n');
    assert.deepStrictEqual(await listFiles(root), ['NORTH-STAR.md', 'SKILL.md', 'src/keep.mjs']);
  });

  test('revert · restores the working tree byte-for-byte across BOTH halves', async () => {
    const fresh = await newRoot('tidy-idy-e2e-foundry-rt-');
    await initRepo(fresh);
    await write(fresh, 'NORTH-STAR.md', '# ns\n');
    await write(fresh, 'dead.mjs', '// dead\n');
    await commitAll(fresh, 'baseline');
    await write(fresh, 'untracked-junk.log', 'junk\n');

    const pre = await workingTree(fresh);
    const scan = await scanFixture(fresh, { runId: RUN });
    const findings = stamp([
      makeFinding(scan, { action: 'remove', path: 'dead.mjs' }),
      makeFinding(scan, { action: 'trash', path: 'untracked-junk.log' }),
    ], RUN);
    const applied = await applyApproved({ rootPath: fresh, git: scan.git, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(applied.status, APPLY_STATUS.APPLIED, applied.message);

    const undone = await undoApply({ rootPath: fresh, git: scan.git, commit: applied.commit, runId: RUN });
    assert.strictEqual(undone.status, UNDO_STATUS.REVERTED, undone.message);
    assert.deepStrictEqual(await workingTree(fresh), pre,
      'both the git-held removal (by revert) and the trashed file (by move-back) came back byte-for-byte');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// Row 2 — a plain git repo (no governance surfaces); carries the mixed-batch cell.
// ────────────────────────────────────────────────────────────────────────────

describe('E2E · plain git repo', () => {
  let root;
  const RUN = 'run-e2e-plain';

  before(async () => {
    root = await newRoot('tidy-idy-e2e-plain-');
    await initRepo(root);
    await write(root, 'app.mjs', 'export const app = 1;\n');
    await write(root, 'dead.mjs', '// dead\n');
    await commitAll(root, 'baseline');
    await write(root, 'junk.log', 'junk\n');
  });

  test('scan · is zero-write', async () => { await assertZeroWriteScan(root); });

  test('Apply · one commit, consent-scope holds', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const before = await commitCount(root);
    const findings = stamp([makeFinding(scan, { action: 'remove', path: 'dead.mjs' })], RUN);
    const result = await applyApproved({ rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(result.status, APPLY_STATUS.APPLIED, JSON.stringify(result, null, 2));
    assert.strictEqual(await commitCount(root), before + 1);
    assert.strictEqual(result.consentScope.ok, true);
  });

  test('mixed-batch failure · a bad Trash half commits NOTHING (all-or-nothing)', async () => {
    const fresh = await newRoot('tidy-idy-e2e-plain-mixed-');
    await initRepo(fresh);
    await write(fresh, 'tracked-junk.txt', 'tracked\n');
    await write(fresh, 'keep.md', '# keep\n');
    await commitAll(fresh, 'baseline');
    await write(fresh, 'untracked-junk.log', 'untracked\n');

    const reportDir = reportDirFor(fresh);
    // Pre-occupy the exact Trash slot this Apply's move-set would need.
    await write(path.join(trashFilesDirFor(reportDir, RUN)), 'untracked-junk.log', 'SOMETHING ELSE\n');

    const scan = await scanFixture(fresh, { runId: RUN });
    const before = await commitCount(fresh);
    const findings = stamp([
      makeFinding(scan, { action: 'remove', path: 'tracked-junk.txt' }),
      makeFinding(scan, { action: 'trash', path: 'untracked-junk.log' }),
    ], RUN);
    const result = await applyApproved({ rootPath: fresh, git: scan.git, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });

    assert.strictEqual(result.status, APPLY_STATUS.REFUSED);
    assert.strictEqual(result.code, APPLY_REFUSAL.TRASH_PREFLIGHT);
    assert.strictEqual(await commitCount(fresh), before, 'the git half was NOT applied — one Apply is all-or-nothing');
    assert.strictEqual(await readOrNull(path.join(fresh, 'tracked-junk.txt')), 'tracked\n', 'nothing was removed');
    assert.strictEqual(await readOrNull(path.join(fresh, 'untracked-junk.log')), 'untracked\n', 'nothing was moved');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// Row 3 — a non-git folder (Amendment A: removals flow through the Trash).
// ────────────────────────────────────────────────────────────────────────────

describe('E2E · non-git folder', () => {
  let root;
  const RUN = 'run-e2e-nongit';

  before(async () => {
    root = await newRoot('tidy-idy-e2e-nongit-');
    await write(root, 'junk-a.txt', 'AAAA\n');
    await write(root, 'keep.md', '# keep\n');
  });

  test('scan · is zero-write with no repository at all', async () => {
    const before = await workingTree(root);
    await assertZeroWriteScan(root);
    assert.deepStrictEqual(await workingTree(root), before);
  });

  test('Apply · commits nothing (no repo) and moves the removal into the Trash', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    assert.strictEqual(scan.git, null, 'the fixture really has no repository');
    const findings = stamp([makeFinding(scan, { action: 'trash', path: 'junk-a.txt' })], RUN);
    const result = await applyApproved({ rootPath: root, git: null, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(result.status, APPLY_STATUS.APPLIED, JSON.stringify(result, null, 2));
    assert.strictEqual(result.commit, null, 'no repository means no commit — and that is not an error');
    assert.deepStrictEqual(await listFiles(root), ['keep.md']);
  });

  test('restore · undo of a repo-less Apply is restore-from-Trash, byte-for-byte', async () => {
    const fresh = await newRoot('tidy-idy-e2e-nongit-rt-');
    await write(fresh, 'junk-a.txt', 'AAAA\n');
    await write(fresh, 'keep.md', '# keep\n');
    const pre = await workingTree(fresh);
    const scan = await scanFixture(fresh, { runId: RUN });
    const findings = stamp([makeFinding(scan, { action: 'trash', path: 'junk-a.txt' })], RUN);
    await applyApproved({ rootPath: fresh, git: null, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });

    const undone = await undoApply({ rootPath: fresh, git: null, commit: null, runId: RUN });
    assert.strictEqual(undone.status, UNDO_STATUS.RESTORED, undone.message);
    assert.strictEqual(undone.branch, UNDO_BRANCH.TRASH_RESTORE);
    assert.deepStrictEqual(await workingTree(fresh), pre, 'restore-from-Trash returned the folder exactly as it was');
  });

  test('git:null semantics · an operation that genuinely needs git is refused, naming it', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const findings = stamp([makeFinding(scan, { action: 'save', path: 'keep.md' })], RUN);
    const result = await applyApproved({ rootPath: root, git: null, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(result.status, APPLY_STATUS.REFUSED);
    assert.strictEqual(result.code, APPLY_REFUSAL.NO_GIT);
    assert.match(result.message, /keep\.md/, 'the refusal names the operation it refused');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// Row 4 — a non-git folder INSIDE an enclosing repo. The one that must never
//         touch the enclosing repository's history.
// ────────────────────────────────────────────────────────────────────────────

describe('E2E · non-git folder inside an enclosing repo', () => {
  let parent;
  let target;
  const RUN = 'run-e2e-enclosed';

  before(async () => {
    parent = await newRoot('tidy-idy-e2e-enclosing-');
    await initRepo(parent);
    await write(parent, 'parent-file.txt', 'the enclosing project\n');
    await commitAll(parent, 'enclosing baseline');
    // The target is a plain subfolder, left UNTRACKED in the enclosing repo.
    target = path.join(parent, 'project');
    await write(target, 'junk.txt', 'JUNK\n');
    await write(target, 'keep.txt', 'KEEP\n');
  });

  test('scan · openGit refuses the enclosing repo — the target is treated as git:null', async () => {
    const scan = await scanFixture(target, { runId: RUN });
    assert.strictEqual(scan.git, null,
      'a folder whose toplevel is an ENCLOSING repo is the no-repository case — the tool never operates on a repo it merely sits inside');
  });

  test('Apply · makes NO commit into the enclosing repository', async () => {
    const enclosingCommitsBefore = await commitCount(parent);
    const scan = await scanFixture(target, { runId: RUN });
    const findings = stamp([makeFinding(scan, { action: 'trash', path: 'junk.txt' })], RUN);
    const result = await applyApproved({ rootPath: target, git: null, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });

    assert.strictEqual(result.status, APPLY_STATUS.APPLIED, JSON.stringify(result, null, 2));
    assert.strictEqual(result.commit, null, 'no commit was made — not into the target, and above all not into the enclosing repo');
    assert.strictEqual(await commitCount(parent), enclosingCommitsBefore,
      'the enclosing repository\'s history is UNCHANGED — the tool committed nothing to a repo it was never pointed at');
    assert.strictEqual(await readOrNull(path.join(parent, 'parent-file.txt')), 'the enclosing project\n');
  });

  test('restore · the trashed file comes back inside the target, byte-for-byte', async () => {
    const undone = await undoApply({ rootPath: target, git: null, commit: null, runId: RUN });
    assert.strictEqual(undone.status, UNDO_STATUS.RESTORED, undone.message);
    assert.strictEqual(await readOrNull(path.join(target, 'junk.txt')), 'JUNK\n');
    assert.strictEqual(await readOrNull(path.join(target, 'keep.txt')), 'KEEP\n');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// Row 5 — a dirty tree. Never blocks a scan; carries the undo-refusal cell.
// ────────────────────────────────────────────────────────────────────────────

describe('E2E · dirty tree', () => {
  let root;
  const RUN = 'run-e2e-dirty';

  before(async () => {
    root = await newRoot('tidy-idy-e2e-dirty-');
    await initRepo(root);
    await write(root, 'settings.json', '{"n":1}\n');
    await write(root, 'dead.mjs', '// dead\n');
    await commitAll(root, 'baseline');
    // Make the tree dirty: an unstaged modification to a tracked file.
    await write(root, 'settings.json', '{"n":2}\n');
    await write(root, 'junk.log', 'junk\n');
  });

  test('scan · a dirty tree is recorded, never refused', async () => {
    const envelope = await assertZeroWriteScan(root);
    assert.strictEqual(envelope.dirty.present, true);
    assert.strictEqual(envelope.dirty.dirty, true);
    assert.strictEqual(envelope.dirty.blockedScan, false, 'a dirty tree must NEVER block a scan — that is the encoded policy');
  });

  test('Apply · proceeds; the dirty tracked file is untouched by the Apply', async () => {
    const scan = await scanFixture(root, { runId: RUN });
    const findings = stamp([makeFinding(scan, { action: 'trash', path: 'junk.log' })], RUN);
    const result = await applyApproved({ rootPath: root, git: scan.git, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(result.status, APPLY_STATUS.APPLIED, JSON.stringify(result, null, 2));
    assert.strictEqual(result.consentScope.ok, true, JSON.stringify(result.consentScope, null, 2));
    assert.strictEqual(await readOrNull(path.join(root, 'settings.json')), '{"n":2}\n',
      'the user\'s uncommitted edit was never part of the Apply and is exactly as they left it');
  });

  test('undo-refusal · a re-occupied revert path leaves the working tree UNTOUCHED', async () => {
    const fresh = await newRoot('tidy-idy-e2e-dirty-undo-');
    await initRepo(fresh);
    await write(fresh, 'dead.mjs', '// dead\n');
    await commitAll(fresh, 'baseline');

    const scan = await scanFixture(fresh, { runId: RUN });
    const findings = stamp([makeFinding(scan, { action: 'remove', path: 'dead.mjs' })], RUN);
    const applied = await applyApproved({ rootPath: fresh, git: scan.git, runId: RUN, snapshot: scan.snapshot, findings, approvals: approvalsFor(findings) });
    assert.strictEqual(applied.status, APPLY_STATUS.APPLIED, applied.message);

    // The user creates NEW work exactly where the revert would restore.
    await write(fresh, 'dead.mjs', 'MY NEW WORK — do not clobber\n');
    const headBefore = (await git(fresh, ['rev-parse', 'HEAD'])).trim();

    const undone = await undoApply({ rootPath: fresh, git: scan.git, commit: applied.commit, runId: RUN });

    assert.strictEqual(undone.status, UNDO_STATUS.REFUSED, JSON.stringify(undone, null, 2));
    assert.strictEqual(undone.code, UNDO_REFUSAL.DIRTY_OVERLAP);
    assert.strictEqual(await readOrNull(path.join(fresh, 'dead.mjs')), 'MY NEW WORK — do not clobber\n',
      'an undo NEVER overwrites content the user created after the Apply — the refusal touched nothing');
    assert.strictEqual((await git(fresh, ['rev-parse', 'HEAD'])).trim(), headBefore, 'no revert commit was written');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// Row 6 — a tree with a NESTED repository. The excluded-subtree invariant.
// ────────────────────────────────────────────────────────────────────────────

describe('E2E · nested repository', () => {
  let root;

  before(async () => {
    root = await newRoot('tidy-idy-e2e-nested-');
    await initRepo(root);
    await write(root, 'app.mjs', 'export const app = 1;\n');
    await commitAll(root, 'baseline');
    // A whole other project living inside the tree.
    const nested = path.join(root, 'vendor', 'lib');
    await initRepo(nested);
    await write(nested, 'their-file.txt', 'belongs to another history\n');
    await commitAll(nested, 'their baseline');
  });

  test('scan · the nested repo is recorded as excluded and never scanned', async () => {
    const envelope = await assertZeroWriteScan(root);
    const excluded = envelope.topology.excludedSubtrees.find((e) => e.path === 'vendor/lib');
    assert.ok(excluded, `the nested repo must be recorded as an excluded subtree; saw ${JSON.stringify(envelope.topology.excludedSubtrees)}`);
    assert.strictEqual(excluded.reason, 'nested-repo');
    // The run states what it did NOT look at — nothing from the nested repo can be
    // in scope, so no finding could ever target it.
    const inScope = envelope.stages.find((s) => s.stage === 'scan').data.inScope;
    assert.ok(!inScope.some((p) => p.startsWith('vendor/lib/')), 'no path inside the nested repo may be in scope');
  });

  test('the nested repository\'s content is byte-identical after the scan', async () => {
    assert.strictEqual(await readOrNull(path.join(root, 'vendor', 'lib', 'their-file.txt')), 'belongs to another history\n');
  });
});
