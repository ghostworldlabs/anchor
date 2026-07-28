// test/apply-reorg.test.mjs — Wave 8: Reorg Proposals (Gated, With Individual Override).
//
// This suite is the wave's INTEGRATION MATRIX. It instantiates every row of the
// crash-at-every-step table (docs/reorg-two-phase-crash-table.md) with a test
// whose title matches the "Named test" column verbatim, plus the frozen
// acceptance criteria:
//
//   • a zero-hit leaf/asset move applies inside the single tidy commit via
//     temp-index re-pathing, and `git revert` restores the original tree
//     byte-for-byte;
//   • a non-zero-hit proposal is excluded from bulk-approve and applyable ONLY
//     through its own explicit 'Apply anyway — I'll fix the references' override
//     (Amendment C.i);
//   • a MIXED-directory apply (tracked half → commit, untracked half → journaled
//     move-set) resolves under ANY crash to exactly fully-applied OR bit-identical
//     — never a third state;
//   • an untracked-in-repo move never changes a path's git tracking class (the
//     consent-scope porcelain-class diff), with journaled move-back undo.
//
// INTERRUPTION IS SIMULATED BY BUILDING THE STATE A KILL WOULD LEAVE, exactly as
// the Wave-4 Trash suite does: the two-phase journal record plus the on-disk / in-git
// facts a crash at that point leaves behind are constructed, then handed to a fresh
// recoverReorgApply() call. A real SIGKILL would be timing-dependent and prove
// nothing repeatable; the recovery rule ("last durable state + one git fact") is
// a pure function of those constructed facts.

import { test, describe, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  applyReorgMove, recoverReorgApply, undoReorgMove,
  partitionReorgMove, classifyReorgMember, preflightReorgFs,
  REORG_STATUS, REORG_RECOVERY, REORG_REFUSAL, REORG_APPLY_STATE,
  REORG_CONTENT_CLASS, REORG_EXECUTOR, REORG_UNDO,
} from '../engine/apply/reorg.mjs';
import { reorgStage } from '../engine/stages/reorg.stage.mjs';
import { buildTile, TILE_CLASS } from '../engine/panel/tiles.mjs';
import { openJournal } from '../engine/apply/journal.mjs';
import { TRACKING } from '../engine/porcelain.mjs';
import { openGit } from '../engine/git.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';

import {
  makeTempRoot, rmTempRoot, write, git, initRepo, commitAll,
  scanFixture, listFiles, commitCount,
} from './helpers/apply-fixture.mjs';

const RUN = 'run-reorg-0001';

// A move-set is stateful, so every test gets a FRESH folder; roots are tracked
// centrally and removed once at the end rather than racing per-block teardown.
const tempRoots = [];
async function newRoot(prefix) {
  const root = await makeTempRoot(prefix);
  tempRoots.push(root);
  return root;
}
after(async () => { for (const r of tempRoots) await rmTempRoot(r); });

async function read(root, rel) {
  try { return (await fs.readFile(path.join(root, rel))).toString('utf8'); } catch { return null; }
}

async function contentsOf(root) {
  const files = await listFiles(root);
  const out = {};
  for (const f of files) out[f] = await read(root, f);
  return out;
}

async function currentRef(root) {
  return (await git(root, ['symbolic-ref', 'HEAD'])).trim();
}
async function head(root) {
  return (await git(root, ['rev-parse', 'HEAD'])).trim();
}

/** A finding shaped exactly like reorgStage emits, with real members + hashes. */
function makeReorgFinding(scan, { from, to, eligible = true, hitCount = 0, hits = [], id = null }) {
  const members = scan.paths.filter((p) => p === from || p.startsWith(`${from}/`)).sort();
  return {
    stage: 'reorg',
    kind: 'reorg-proposal',
    action: 'reorg',
    path: from,
    move: { from, to },
    members,
    referenceScan: { hitCount, hits, truncated: false, scannedFiles: 0, scope: 'test' },
    eligible,
    overrideRequired: !eligible,
    bulkApprovable: eligible,
    defaultChecked: false,
    ...(id ? { id } : {}),
  };
}

// ────────────────────────────────────────────────────────────────────────────
// 1. The content-class partition — pure, per-path, computed at compile time.
// ────────────────────────────────────────────────────────────────────────────

describe('the per-path content-class partition names an executor and undo per class', () => {
  const clean = { classify: () => TRACKING.TRACKED_CLEAN };
  const dirty = { classify: () => TRACKING.TRACKED_MODIFIED };
  const untracked = { classify: () => TRACKING.UNTRACKED };

  test('no repository → every member is non-git, moved by the journaled move-set', () => {
    const c = classifyReorgMember({ rel: 'a/x.png', porcelain: null, git: null });
    assert.strictEqual(c.contentClass, REORG_CONTENT_CLASS.NON_GIT);
    assert.strictEqual(c.eligible, true);
    assert.strictEqual(REORG_EXECUTOR[c.contentClass], 'wave4-journaled-move-set');
    assert.strictEqual(REORG_UNDO[c.contentClass], 'journaled-move-back');
  });

  test('tracked-and-clean → the Wave-3 single-commit plan, undo = git revert', () => {
    const c = classifyReorgMember({ rel: 'a/x.png', porcelain: clean, git: {} });
    assert.strictEqual(c.contentClass, REORG_CONTENT_CLASS.TRACKED);
    assert.strictEqual(REORG_EXECUTOR[c.contentClass], 'wave3-single-commit-plan');
    assert.strictEqual(REORG_UNDO[c.contentClass], 'git-revert');
  });

  test('untracked-in-repo → journaled move-set, undo = journaled move-back', () => {
    const c = classifyReorgMember({ rel: 'a/x.png', porcelain: untracked, git: {} });
    assert.strictEqual(c.contentClass, REORG_CONTENT_CLASS.UNTRACKED);
    assert.strictEqual(c.eligible, true);
  });

  test('a tracked-but-dirty member is INELIGIBLE — a move would risk work git has never seen', () => {
    const c = classifyReorgMember({ rel: 'a/x.png', porcelain: dirty, git: {} });
    assert.strictEqual(c.eligible, false);
    assert.strictEqual(c.contentClass, null);
    assert.match(c.reason, /older version/);
  });

  test('a MIXED directory partitions into both halves, each with its executor', () => {
    const porcelain = {
      classify: (p) => (p.endsWith('.tracked') ? TRACKING.TRACKED_CLEAN : TRACKING.UNTRACKED),
    };
    const part = partitionReorgMove({
      move: { from: 'bundle', to: 'assets/bundle' },
      members: ['bundle/a.tracked', 'bundle/b.tracked', 'bundle/c.untracked'],
      porcelain, git: {},
    });
    assert.strictEqual(part.mixed, true);
    assert.strictEqual(part.hasGit, true);
    assert.strictEqual(part.hasFs, true);
    assert.strictEqual(part.gitMoves.length, 2);
    assert.strictEqual(part.fsMoves.length, 1);
    assert.strictEqual(part.gitMoves[0].to, 'assets/bundle/a.tracked');
    assert.strictEqual(part.fsMoves[0].to, 'assets/bundle/c.untracked');
  });
});

describe('the fs preflight refuses what it cannot do before anything moves', () => {
  test('a case-colliding destination is refused on a case-insensitive filesystem', () => {
    const pre = preflightReorgFs({
      rootPath: '/tmp/x',
      fsMoves: [{ from: 'a/One.png', to: 'assets/One.png' }, { from: 'a/one.png', to: 'assets/one.png' }],
      ignorecase: true,
    });
    assert.strictEqual(pre.ok, false);
    assert.strictEqual(pre.problems[0].code, REORG_REFUSAL.CASE_COLLISION);
  });

  test('a destination escaping the run root is refused', () => {
    const pre = preflightReorgFs({
      rootPath: '/tmp/x',
      fsMoves: [{ from: 'a/x.png', to: '../escape/x.png' }],
      ignorecase: false,
    });
    assert.strictEqual(pre.ok, false);
    assert.strictEqual(pre.problems[0].code, REORG_REFUSAL.OUTSIDE_ROOT);
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 2. The reorg STAGE: leaf/asset proposals + whole-tree reference scan + gating.
// ────────────────────────────────────────────────────────────────────────────

function stageCtx(scan, root) {
  return {
    rootPath: root,
    git: scan.git,
    fs,
    protection: { isProtected: () => false },
    state: { inScope: scan.paths, snapshot: scan.snapshot, llmBlocked: new Set(), porcelain: scan.porcelain },
  };
}

describe('the reorg stage: zero-hit leaf/asset moves are approvable, referenced ones are advisory', () => {
  test('a leaf asset directory with ZERO references is an approvable, bulk-eligible proposal', async () => {
    const root = await newRoot('tidy-idy-w8-stage-zero-');
    await initRepo(root);
    await write(root, 'sprites/a.png', 'PNG-A\n');
    await write(root, 'sprites/b.png', 'PNG-B\n');
    await write(root, 'main.js', 'console.log(1)\n');
    await write(root, 'README.md', '# hi\n');
    await commitAll(root, 'baseline');

    const scan = await scanFixture(root, { runId: RUN });
    const result = await reorgStage.run(stageCtx(scan, root));

    const finding = result.findings.find((f) => f.path === 'sprites');
    assert.ok(finding, 'sprites was proposed as a leaf/asset move');
    assert.strictEqual(finding.referenceScan.hitCount, 0);
    assert.strictEqual(finding.eligible, true);
    assert.strictEqual(finding.overrideRequired, false);
    assert.strictEqual(finding.bulkApprovable, true);
    assert.deepStrictEqual(finding.move, { from: 'sprites', to: 'assets/sprites' });
    assert.deepStrictEqual(finding.before.entries, ['sprites/a.png', 'sprites/b.png']);
    assert.deepStrictEqual(finding.after.entries, ['assets/sprites/a.png', 'assets/sprites/b.png']);

    // The tile renders a before→after tree with a hit-count badge and IS bulk-approvable.
    const tile = buildTile({ ...finding, id: 'reorg-1' });
    assert.strictEqual(tile.class, TILE_CLASS.REORG);
    assert.strictEqual(tile.bulkApprovable, true);
    assert.ok(tile.evidence.before && tile.evidence.after, 'the tile carries both trees');
    assert.strictEqual(tile.evidence.referenceScan.hitCount, 0);
    assert.ok(tile.badges.includes('0 reference hits'));
  });

  test('a directory referenced 3 times in tsconfig.json is ADVISORY: excluded from bulk, override-only', async () => {
    const root = await newRoot('tidy-idy-w8-stage-hits-');
    await initRepo(root);
    await write(root, 'icons/logo.svg', '<svg/>\n');
    await write(root, 'icons/hero.png', 'PNG\n');
    // Three lines that each reference the directory or a member — hitCount 3.
    await write(root, 'tsconfig.json', [
      '{',
      '  "include": ["icons"],',
      '  "references": ["icons/logo.svg"],',
      '  "extra": ["icons/hero.png"]',
      '}',
      '',
    ].join('\n'));
    await write(root, 'keep.md', '# keep\n');
    await commitAll(root, 'baseline');

    const scan = await scanFixture(root, { runId: RUN });
    const result = await reorgStage.run(stageCtx(scan, root));

    const finding = result.findings.find((f) => f.path === 'icons');
    assert.ok(finding, 'icons was proposed');
    assert.strictEqual(finding.referenceScan.hitCount, 3, JSON.stringify(finding.referenceScan.hits, null, 2));
    assert.strictEqual(finding.eligible, false);
    assert.strictEqual(finding.overrideRequired, true);
    assert.strictEqual(finding.bulkApprovable, false);
    assert.ok(finding.referenceScan.hits.some((h) => h.path === 'tsconfig.json'), 'the hit list names tsconfig.json');

    // The tile is excluded from bulk-approve and offers the explicit override only.
    const tile = buildTile({ ...finding, id: 'reorg-2' });
    assert.strictEqual(tile.bulkApprovable, false, 'a referenced move can never ride bulk-approve');
    assert.ok(tile.confirmIndividually && tile.confirmIndividually.override === true);
    assert.match(tile.confirmIndividually.label, /Apply anyway/);
    assert.strictEqual(tile.approval.override, true, 'the override travels on the approval so the server can require it');
    assert.ok(tile.badges.includes('override required — not bulk'));
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 3. Acceptance criterion 1 — a tracked zero-hit move lands in ONE commit and
//    `git revert` restores the original tree byte-for-byte.
// ────────────────────────────────────────────────────────────────────────────

describe('a zero-hit tracked leaf move: one commit via temp-index re-pathing, undo = git revert', () => {
  async function trackedRepo() {
    const root = await newRoot('tidy-idy-w8-tracked-');
    await initRepo(root);
    await write(root, 'icons/a.svg', '<svg>a</svg>\n');
    await write(root, 'icons/b.svg', '<svg>b</svg>\n');
    await write(root, 'keep.md', '# keep\n');
    await commitAll(root, 'baseline');
    return root;
  }

  test('the move lands inside the single tidy commit and undo restores the tree byte-for-byte', async () => {
    const root = await trackedRepo();
    const reportDir = reportDirFor(root);
    const scan = await scanFixture(root, { runId: RUN });
    const before = await contentsOf(root);
    const commitsBefore = await commitCount(root);

    const finding = makeReorgFinding(scan, { from: 'icons', to: 'assets/icons' });
    const applied = await applyReorgMove({
      rootPath: root, git: scan.git, runId: RUN, reportDir,
      finding, snapshot: scan.snapshot, porcelain: scan.porcelain,
    });

    assert.strictEqual(applied.status, REORG_STATUS.APPLIED, JSON.stringify(applied, null, 2));
    assert.ok(applied.commit, 'the tracked half produced a commit');
    assert.strictEqual(applied.fsMoved.length, 0, 'nothing untracked, so no fs move-set');
    assert.strictEqual(await commitCount(root), commitsBefore + 1, 'exactly ONE commit for the whole move');
    assert.deepStrictEqual(await listFiles(root), ['assets/icons/a.svg', 'assets/icons/b.svg', 'keep.md']);
    assert.strictEqual(applied.consentScope.ok, true, JSON.stringify(applied.consentScope.violations, null, 2));

    const undone = await undoReorgMove({ rootPath: root, git: scan.git, runId: RUN, reportDir, commit: applied.commit });
    assert.strictEqual(undone.status, REORG_STATUS.ROLLED_BACK, undone.message);
    assert.ok(undone.revert && undone.revert.commit, 'undo is a git revert of the tidy commit');
    assert.deepStrictEqual(await contentsOf(root), before, 'the original tree is back byte-for-byte');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 4. Acceptance criterion 2 — a referenced move applies ONLY via the individual
//    override, never in bulk.
// ────────────────────────────────────────────────────────────────────────────

describe("a referenced move is applyable only through the individual 'Apply anyway' override", () => {
  async function referencedRepo() {
    const root = await newRoot('tidy-idy-w8-override-');
    await initRepo(root);
    await write(root, 'icons/logo.svg', '<svg/>\n');
    await write(root, 'tsconfig.json', '{ "include": ["icons"] }\n');
    await write(root, 'keep.md', '# keep\n');
    await commitAll(root, 'baseline');
    return root;
  }

  test('without the override it is REFUSED, naming the reference-scan hits', async () => {
    const root = await referencedRepo();
    const reportDir = reportDirFor(root);
    const scan = await scanFixture(root, { runId: RUN });
    const finding = makeReorgFinding(scan, { from: 'icons', to: 'assets/icons', eligible: false, hitCount: 1 });

    const result = await applyReorgMove({
      rootPath: root, git: scan.git, runId: RUN, reportDir,
      finding, snapshot: scan.snapshot, porcelain: scan.porcelain, override: false,
    });

    assert.strictEqual(result.status, REORG_STATUS.REFUSED);
    assert.strictEqual(result.code, REORG_REFUSAL.NOT_ELIGIBLE);
    assert.match(result.message, /Apply anyway/);
    assert.deepStrictEqual(await listFiles(root), ['icons/logo.svg', 'keep.md', 'tsconfig.json'], 'NOTHING moved');
  });

  test('WITH the explicit per-proposal override the same move applies', async () => {
    const root = await referencedRepo();
    const reportDir = reportDirFor(root);
    const scan = await scanFixture(root, { runId: RUN });
    const finding = makeReorgFinding(scan, { from: 'icons', to: 'assets/icons', eligible: false, hitCount: 1 });

    const result = await applyReorgMove({
      rootPath: root, git: scan.git, runId: RUN, reportDir,
      finding, snapshot: scan.snapshot, porcelain: scan.porcelain, override: true,
    });

    assert.strictEqual(result.status, REORG_STATUS.APPLIED, JSON.stringify(result, null, 2));
    const files = await listFiles(root);
    assert.ok(files.includes('assets/icons/logo.svg'), 'the overridden move landed at its new path');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 5. Acceptance criterion 4 — an untracked-in-repo move never changes tracking
//    class; undo is a journaled move-back.
// ────────────────────────────────────────────────────────────────────────────

describe('an untracked-in-repo move keeps the tracking class unchanged (consent-scope) and move-backs cleanly', () => {
  test('git status shows the file still untracked at its new path — no index write, no .gitignore', async () => {
    const root = await newRoot('tidy-idy-w8-untracked-');
    await initRepo(root);
    await write(root, 'keep.md', '# keep\n');
    await commitAll(root, 'baseline');
    await write(root, 'pics/p.png', 'P\n');   // untracked
    await write(root, 'pics/q.png', 'Q\n');   // untracked
    const reportDir = reportDirFor(root);
    const scan = await scanFixture(root, { runId: RUN });
    const before = await contentsOf(root);

    const finding = makeReorgFinding(scan, { from: 'pics', to: 'assets/pics' });
    const applied = await applyReorgMove({
      rootPath: root, git: scan.git, runId: RUN, reportDir,
      finding, snapshot: scan.snapshot, porcelain: scan.porcelain,
    });

    assert.strictEqual(applied.status, REORG_STATUS.APPLIED, JSON.stringify(applied, null, 2));
    assert.strictEqual(applied.commit, null, 'no tracked members, so no commit');
    assert.strictEqual(applied.fsMoved.length, 2, 'both untracked files moved by the journaled move-set');
    assert.strictEqual(applied.consentScope.ok, true, JSON.stringify(applied.consentScope.violations, null, 2));

    const status = await git(root, ['status', '--porcelain=v2', '--untracked-files=all']);
    assert.match(status, /\? assets\/pics\/p\.png/, 'still untracked, now at the new path');
    assert.match(status, /\? assets\/pics\/q\.png/);
    assert.strictEqual(await read(root, 'pics/p.png'), null, 'the old path is gone');
    assert.strictEqual(await read(root, 'pics/q.png'), null);
    assert.strictEqual(await read(root, '.gitignore'), null, 'a Move never writes .gitignore');

    // Undo = journaled move-back, no revert (there was no commit).
    const undone = await undoReorgMove({ rootPath: root, git: scan.git, runId: RUN, reportDir });
    assert.strictEqual(undone.status, REORG_STATUS.ROLLED_BACK, undone.message);
    assert.strictEqual(undone.revert, null, 'nothing was committed, so nothing to revert');
    assert.deepStrictEqual(await contentsOf(root), before, 'both files came back bit-identical to their original paths');
  });

  test('move-back onto a REOCCUPIED original path is refused, never overwritten (no-clobber)', async () => {
    const root = await newRoot('tidy-idy-w8-untracked-clobber-');
    await initRepo(root);
    await write(root, 'keep.md', '# keep\n');
    await commitAll(root, 'baseline');
    await write(root, 'pics/p.png', 'P\n');
    await write(root, 'pics/q.png', 'Q\n');
    const reportDir = reportDirFor(root);
    const scan = await scanFixture(root, { runId: RUN });

    const finding = makeReorgFinding(scan, { from: 'pics', to: 'assets/pics' });
    await applyReorgMove({ rootPath: root, git: scan.git, runId: RUN, reportDir, finding, snapshot: scan.snapshot, porcelain: scan.porcelain });

    // The user created NEW work where one of the moved files used to be.
    await write(root, 'pics/p.png', 'MY NEW WORK\n');

    const undone = await undoReorgMove({ rootPath: root, git: scan.git, runId: RUN, reportDir });
    assert.strictEqual(undone.status, REORG_STATUS.PARTIAL, undone.message);
    assert.strictEqual(undone.refused.length, 1);
    assert.strictEqual(undone.refused[0].path, 'pics/p.png');
    assert.strictEqual(await read(root, 'pics/p.png'), 'MY NEW WORK\n', "the user's new content is untouched");
    assert.strictEqual(await read(root, 'pics/q.png'), 'Q\n', 'the OTHER path still moved back');
    assert.strictEqual(await read(root, 'assets/pics/p.png'), 'P\n', 'the moved copy stays where it was');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 6. The mixed-directory happy path + crash-table row 10 (DONE is a no-op).
// ────────────────────────────────────────────────────────────────────────────

async function mixedRepo(prefix = 'tidy-idy-w8-mixed-') {
  const root = await newRoot(prefix);
  await initRepo(root);
  await write(root, 'keep.md', '# keep\n');
  await write(root, 'bundle/t1.png', 'T1\n');
  await write(root, 'bundle/t2.png', 'T2\n');
  await write(root, 'bundle/t3.png', 'T3\n');
  await commitAll(root, 'baseline');            // t1..t3 tracked-clean
  await write(root, 'bundle/u1.png', 'U1\n');   // untracked
  await write(root, 'bundle/u2.png', 'U2\n');
  return root;
}

const MIXED_APPLIED = ['assets/bundle/t1.png', 'assets/bundle/t2.png', 'assets/bundle/t3.png', 'assets/bundle/u1.png', 'assets/bundle/u2.png', 'keep.md'];
const MIXED_ORIGINAL = ['bundle/t1.png', 'bundle/t2.png', 'bundle/t3.png', 'bundle/u1.png', 'bundle/u2.png', 'keep.md'];

describe('a mixed directory applies as one commit (tracked) PLUS one journaled move-set (untracked)', () => {
  test('both halves land, tracking classes hold, and undo restores the whole tree', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const scan = await scanFixture(root, { runId: RUN });
    const before = await contentsOf(root);
    const commitsBefore = await commitCount(root);

    const finding = makeReorgFinding(scan, { from: 'bundle', to: 'assets/bundle' });
    const applied = await applyReorgMove({
      rootPath: root, git: scan.git, runId: RUN, reportDir,
      finding, snapshot: scan.snapshot, porcelain: scan.porcelain,
    });

    assert.strictEqual(applied.status, REORG_STATUS.APPLIED, JSON.stringify(applied, null, 2));
    assert.strictEqual(applied.mixed, true);
    assert.ok(applied.commit, 'the tracked half committed');
    assert.strictEqual(applied.fsMoved.length, 2, 'the untracked half moved via the journaled move-set');
    assert.strictEqual(await commitCount(root), commitsBefore + 1, 'still exactly one commit');
    assert.deepStrictEqual(await listFiles(root), MIXED_APPLIED);
    assert.strictEqual(applied.consentScope.ok, true, JSON.stringify(applied.consentScope.violations, null, 2));

    // crash-table row 10: recovering a DONE apply is a no-op.
    const gitHandle = await openGit(root);
    const recovered = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(recovered.status, REORG_STATUS.APPLIED, 'crash@DONE is a no-op');
    assert.strictEqual(recovered.recovery, REORG_RECOVERY.NONE);
    assert.deepStrictEqual(await listFiles(root), MIXED_APPLIED, 'a DONE recovery changed nothing');

    const undone = await undoReorgMove({ rootPath: root, git: scan.git, runId: RUN, reportDir, commit: applied.commit });
    assert.strictEqual(undone.status, REORG_STATUS.ROLLED_BACK, undone.message);
    assert.deepStrictEqual(await contentsOf(root), before, 'undo = git revert + journaled move-back, whole tree bit-identical');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 7. THE CRASH-AT-EVERY-STEP TABLE. One test per row, titled to match the
//    "Named test" column of docs/reorg-two-phase-crash-table.md.
//
//    A crash is simulated by authoring the two-phase journal to the state a kill
//    at that point leaves, arranging the matching on-disk / in-git facts, then
//    calling recoverReorgApply(). The recovery rule is a pure function of "last
//    durable state + is the journaled commit at the ref?".
// ────────────────────────────────────────────────────────────────────────────

const FS_MOVES = [
  { from: 'bundle/u1.png', to: 'assets/bundle/u1.png' },
  { from: 'bundle/u2.png', to: 'assets/bundle/u2.png' },
];
const GIT_MOVES = [
  { from: 'bundle/t1.png', to: 'assets/bundle/t1.png' },
  { from: 'bundle/t2.png', to: 'assets/bundle/t2.png' },
  { from: 'bundle/t3.png', to: 'assets/bundle/t3.png' },
];

/** Author reorg journal records in order (fsync-before-act, exactly as apply does). */
async function journal(reportDir, records) {
  const j = await openJournal({ reportDir, runId: RUN, kind: 'reorg' });
  for (const [type, data] of records) await j.append(type, data);
  return j;
}

async function plannedRecord(root) {
  return ['state', {
    state: REORG_APPLY_STATE.PLANNED,
    move: { from: 'bundle', to: 'assets/bundle' }, mixed: true,
    classes: [REORG_CONTENT_CLASS.TRACKED, REORG_CONTENT_CLASS.UNTRACKED],
    head: await head(root), ref: await currentRef(root),
    fsMoves: FS_MOVES, gitMoves: GIT_MOVES, override: false,
  }];
}

/** Move one untracked file onto its new path (the fs half doing its work). */
async function fsMove(root, mv) {
  await fs.mkdir(path.join(root, path.dirname(mv.to)), { recursive: true });
  await fs.rename(path.join(root, mv.from), path.join(root, mv.to));
}

/** Commit the tracked re-pathing so the branch tip genuinely IS commit C. */
async function commitTrackedMove(root) {
  for (const mv of GIT_MOVES) {
    // `git mv` does not create the destination's leading directory; a real apply
    // does (checkout --no-overlay / moveFile's mkdir), so mirror that here — the
    // same mkdir-before-move the sibling fsMove() helper already performs.
    await fs.mkdir(path.join(root, path.dirname(mv.to)), { recursive: true });
    await git(root, ['mv', mv.from, mv.to]);
  }
  await git(root, ['commit', '-m', 'tidy-idy reorg: move bundle → assets/bundle']);
  return head(root);
}

describe('crash-at-every-step: the two-phase apply resolves to fully-applied OR bit-identical, never a third', () => {
  // ---- ROLL-BACK rows (the commit never landed) ---------------------------

  test('crash@PLANNED rolls back to bit-identical', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const before = await contentsOf(root);
    await journal(reportDir, [await plannedRecord(root)]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_BACK);
    assert.strictEqual(r.status, REORG_STATUS.ROLLED_BACK);
    assert.deepStrictEqual(await contentsOf(root), before, 'nothing had moved; nothing changed');
  });

  test('crash@PREFLIGHTED rolls back to bit-identical', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const before = await contentsOf(root);
    await journal(reportDir, [
      await plannedRecord(root),
      ['state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree: 'deadbeef', head: await head(root), ref: await currentRef(root) }],
    ]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_BACK);
    assert.deepStrictEqual(await listFiles(root), MIXED_ORIGINAL);
    assert.deepStrictEqual(await contentsOf(root), before);
  });

  test('crash@FS_MOVING rolls completed fs moves back', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const before = await contentsOf(root);
    // 1 of 2 untracked files moved; no commit.
    await fsMove(root, FS_MOVES[0]);
    await journal(reportDir, [
      await plannedRecord(root),
      ['state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree: 'deadbeef' }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', hash: null, size: 3, method: 'rename', k: 1, n: 2 }],
    ]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_BACK);
    assert.deepStrictEqual(await listFiles(root), MIXED_ORIGINAL, 'the moved file was rolled back');
    assert.deepStrictEqual(await contentsOf(root), before);
  });

  test('crash@FS_MOVING with torn journal reconciles then rolls back', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const before = await contentsOf(root);
    // The rename completed but its `done` record was lost (only `started` is on disk).
    await fsMove(root, FS_MOVES[0]);
    await journal(reportDir, [
      await plannedRecord(root),
      ['state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree: 'deadbeef' }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'started', hash: null, size: 3 }],
    ]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_BACK);
    assert.deepStrictEqual(await contentsOf(root), before, 'the torn move was reconciled from disk, then rolled back');
  });

  test('crash@FS_DONE rolls the whole fs half back', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const before = await contentsOf(root);
    await fsMove(root, FS_MOVES[0]);
    await fsMove(root, FS_MOVES[1]);
    await journal(reportDir, [
      await plannedRecord(root),
      ['state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree: 'deadbeef' }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['fs-move', { from: FS_MOVES[1].from, to: FS_MOVES[1].to, state: 'done', k: 2, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.FS_DONE, moved: 2 }],
    ]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_BACK);
    assert.deepStrictEqual(await listFiles(root), MIXED_ORIGINAL);
    assert.deepStrictEqual(await contentsOf(root), before);
  });

  test('crash@COMMITTED before ref rolls back bit-identical', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const before = await contentsOf(root);
    const parent = await head(root);
    const ref = await currentRef(root);

    // A real commit C is written, then the branch is moved back so C is UNREFERENCED
    // (the ref never advanced) — exactly the "COMMITTED, ref NOT advanced" state.
    const C = await commitTrackedMove(root);
    await git(root, ['reset', '--hard', parent]);   // branch → parent, C now dangling, tracked back at bundle/
    // The fs half had completed before the (never-landing) commit.
    await fsMove(root, FS_MOVES[0]);
    await fsMove(root, FS_MOVES[1]);
    await journal(reportDir, [
      ['state', { state: REORG_APPLY_STATE.PLANNED, move: { from: 'bundle', to: 'assets/bundle' }, mixed: true, head: parent, ref, fsMoves: FS_MOVES, gitMoves: GIT_MOVES }],
      ['state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree: 'deadbeef' }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['fs-move', { from: FS_MOVES[1].from, to: FS_MOVES[1].to, state: 'done', k: 2, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.FS_DONE, moved: 2 }],
      ['state', { state: REORG_APPLY_STATE.COMMITTED, commit: C, tree: 'deadbeef', parent, ref }],
    ]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_BACK, 'the journaled commit is not at the ref → it never landed');
    assert.strictEqual(await head(root), parent, 'HEAD is untouched');
    assert.deepStrictEqual(await listFiles(root), MIXED_ORIGINAL, 'the fs half rolled back to bit-identical');
    assert.deepStrictEqual(await contentsOf(root), before);
  });

  // ---- ROLL-FORWARD rows (the commit landed) ------------------------------

  test('crash@COMMITTED after ref (record lost) rolls forward', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const parent = await head(root);
    const ref = await currentRef(root);
    const C = await commitTrackedMove(root);   // C IS the branch tip
    await fsMove(root, FS_MOVES[0]);
    await fsMove(root, FS_MOVES[1]);
    // COMMITTED is journaled but the REF_ADVANCED record was lost before it flushed.
    await journal(reportDir, [
      ['state', { state: REORG_APPLY_STATE.PLANNED, move: { from: 'bundle', to: 'assets/bundle' }, mixed: true, head: parent, ref, fsMoves: FS_MOVES, gitMoves: GIT_MOVES }],
      ['state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree: 'deadbeef' }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['fs-move', { from: FS_MOVES[1].from, to: FS_MOVES[1].to, state: 'done', k: 2, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.FS_DONE, moved: 2 }],
      ['state', { state: REORG_APPLY_STATE.COMMITTED, commit: C, parent, ref }],
    ]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_FORWARD, 'the journaled commit IS at the ref → it landed');
    assert.strictEqual(r.status, REORG_STATUS.APPLIED);
    assert.deepStrictEqual(await listFiles(root), MIXED_APPLIED, 'fully applied — no file lost, none duplicated');
  });

  test('crash@REF_ADVANCED rolls forward to fully-applied', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const parent = await head(root);
    const ref = await currentRef(root);
    const C = await commitTrackedMove(root);
    await fsMove(root, FS_MOVES[0]);
    await fsMove(root, FS_MOVES[1]);
    // The working-tree realization had not finished: one committed tracked file is
    // missing from the working tree (checkout --no-overlay had not run yet). The
    // roll-forward must restore it from C.
    await fs.rm(path.join(root, 'assets/bundle/t1.png'));
    await journal(reportDir, [
      ['state', { state: REORG_APPLY_STATE.PLANNED, move: { from: 'bundle', to: 'assets/bundle' }, mixed: true, head: parent, ref, fsMoves: FS_MOVES, gitMoves: GIT_MOVES }],
      ['state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree: 'deadbeef' }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['fs-move', { from: FS_MOVES[1].from, to: FS_MOVES[1].to, state: 'done', k: 2, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.FS_DONE, moved: 2 }],
      ['state', { state: REORG_APPLY_STATE.COMMITTED, commit: C, parent, ref }],
      ['state', { state: REORG_APPLY_STATE.REF_ADVANCED, commit: C, ref }],
    ]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_FORWARD);
    assert.strictEqual(r.status, REORG_STATUS.APPLIED);
    assert.deepStrictEqual(await listFiles(root), MIXED_APPLIED, 'realization was finished forward');
  });

  test('crash after commit lands, fs incomplete, rolls forward', async () => {
    const root = await mixedRepo();
    const reportDir = reportDirFor(root);
    const parent = await head(root);
    const ref = await currentRef(root);
    const C = await commitTrackedMove(root);
    // Only ONE of the two untracked files was moved before the crash.
    await fsMove(root, FS_MOVES[0]);
    await journal(reportDir, [
      ['state', { state: REORG_APPLY_STATE.PLANNED, move: { from: 'bundle', to: 'assets/bundle' }, mixed: true, head: parent, ref, fsMoves: FS_MOVES, gitMoves: GIT_MOVES }],
      ['state', { state: REORG_APPLY_STATE.PREFLIGHTED, gitTree: 'deadbeef' }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.COMMITTED, commit: C, parent, ref }],
      ['state', { state: REORG_APPLY_STATE.REF_ADVANCED, commit: C, ref }],
    ]);

    const gitHandle = await openGit(root);
    const r = await recoverReorgApply({ rootPath: root, git: gitHandle, runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_FORWARD);
    assert.strictEqual(r.status, REORG_STATUS.APPLIED);
    assert.deepStrictEqual(await listFiles(root), MIXED_APPLIED, 'the outstanding fs move was completed forward');
    assert.strictEqual(await read(root, 'assets/bundle/u2.png'), 'U2\n', 'the not-yet-moved file was carried forward, not lost');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 8. Acceptance criterion 3, stated in its own words: mixed kill-after-commit
//    rolls FORWARD, kill-before-commit rolls BACK bit-identical.
// ────────────────────────────────────────────────────────────────────────────

describe('acceptance criterion 3: a mixed move killed around the commit resolves to exactly one of two states', () => {
  test('killed AFTER the commit lands but before the fs move-set completes → fully-applied', async () => {
    const root = await mixedRepo('tidy-idy-w8-crit3-fwd-');
    const reportDir = reportDirFor(root);
    const parent = await head(root);
    const ref = await currentRef(root);
    const C = await commitTrackedMove(root);   // three tracked files committed
    await fsMove(root, FS_MOVES[0]);           // one of two untracked moved; then killed
    await journal(reportDir, [
      ['state', { state: REORG_APPLY_STATE.PLANNED, move: { from: 'bundle', to: 'assets/bundle' }, mixed: true, head: parent, ref, fsMoves: FS_MOVES, gitMoves: GIT_MOVES }],
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.COMMITTED, commit: C, parent, ref }],
      ['state', { state: REORG_APPLY_STATE.REF_ADVANCED, commit: C, ref }],
    ]);

    const r = await recoverReorgApply({ rootPath: root, git: await openGit(root), runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_FORWARD);
    assert.deepStrictEqual(await listFiles(root), MIXED_APPLIED, 'no file lost, none duplicated');
  });

  test('killed BEFORE the commit → completed fs moves roll back, tree bit-identical, nothing committed', async () => {
    const root = await mixedRepo('tidy-idy-w8-crit3-back-');
    const reportDir = reportDirFor(root);
    const before = await contentsOf(root);
    const baseline = await head(root);
    // The fs half ran; the commit never happened (no COMMITTED record).
    await fsMove(root, FS_MOVES[0]);
    await fsMove(root, FS_MOVES[1]);
    await journal(reportDir, [
      await plannedRecord(root),
      ['state', { state: REORG_APPLY_STATE.FS_MOVING, total: 2 }],
      ['fs-move', { from: FS_MOVES[0].from, to: FS_MOVES[0].to, state: 'done', k: 1, n: 2 }],
      ['fs-move', { from: FS_MOVES[1].from, to: FS_MOVES[1].to, state: 'done', k: 2, n: 2 }],
      ['state', { state: REORG_APPLY_STATE.FS_DONE, moved: 2 }],
    ]);

    const r = await recoverReorgApply({ rootPath: root, git: await openGit(root), runId: RUN, reportDir });
    assert.strictEqual(r.recovery, REORG_RECOVERY.ROLL_BACK);
    assert.strictEqual(await head(root), baseline, 'nothing was committed');
    assert.deepStrictEqual(await contentsOf(root), before, 'bit-identical to pre-apply');
  });
});
