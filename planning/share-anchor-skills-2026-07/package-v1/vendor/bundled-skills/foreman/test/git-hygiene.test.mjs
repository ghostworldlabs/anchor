// git-hygiene.test.mjs — Foreman Phase 3c: git hygiene + git-resume reconciliation.
//
// Every test runs against a REAL throwaway git repo in an OS temp dir (created
// with `git init -b main` + a baseline commit), drives the engine with the
// deterministic scripted driver, and asserts against REAL `git log`/`git status`
// output. NO git operation ever touches the Foreman source tree or C:\dev.
//
// The gate inside each wave is a real `node --test` run in the temp project; the
// finding-M fix (strip NODE_TEST_CONTEXT) lets it run even though THIS suite is
// itself spawned under `node --test`.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

import { runProject } from '../bin/project-engine.mjs';
import { makeGitContext, _internals, commitMessage } from '../bin/git-hygiene.mjs';
import { HaltError, readCheckpoint, writeCheckpointAtomic } from '../bin/foreman-lib.mjs';

function git(dir, args) {
  const r = spawnSync('git', args, { cwd: dir, encoding: 'utf8' });
  return { ok: r.status === 0, status: r.status, out: (r.stdout || '').trim(), err: (r.stderr || '').trim() };
}

/** Create a real git project at its green baseline (committed on `main`). */
function makeGitProject(waveCount = 2) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fmn-git-'));
  fs.mkdirSync(path.join(dir, 'src'), { recursive: true });
  fs.mkdirSync(path.join(dir, 'test'), { recursive: true });
  // a covered baseline so the repo starts green and has a real source file
  fs.writeFileSync(path.join(dir, 'src', 'base.js'), 'export const base = () => 1;\n');
  fs.writeFileSync(path.join(dir, 'test', 'base.test.mjs'),
    "import {test} from 'node:test'; import assert from 'node:assert';\n" +
    "import {base} from '../src/base.js';\n" +
    "test('base', () => assert.equal(base(), 1));\n");
  let plan = '# Plan\n\ntest-command: `node --test`\n\n';
  for (let n = 1; n <= waveCount; n++) plan += `## Wave ${n} — feature ${n}\nDeliver feature ${n}.\n\n`;
  fs.writeFileSync(path.join(dir, 'IMPLEMENTATION-PLAN.md'), plan);
  fs.writeFileSync(path.join(dir, 'DESCRIPTION.md'), '# Description\n\nA tiny test project.\n');
  fs.writeFileSync(path.join(dir, 'EXECUTION-LOG.md'), '# Execution log\n');
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ name: 'fmn-git-fixture', scripts: { test: 'node --test' } }, null, 2) + '\n');

  assert.ok(git(dir, ['init', '-b', 'main']).ok, 'git init');
  git(dir, ['config', 'user.email', 'foreman-test@local']);
  git(dir, ['config', 'user.name', 'Foreman Test']);
  git(dir, ['config', 'commit.gpgsign', 'false']); // throwaway repo: don't block on signing
  assert.ok(git(dir, ['add', '-A']).ok, 'git add baseline');
  assert.ok(git(dir, ['commit', '-m', 'baseline']).ok, 'git commit baseline');
  const baseline = git(dir, ['rev-parse', 'HEAD']).out;
  return { dir, baseline };
}

/** A per-wave driver: EXECUTE writes a NEW covered source+test for wave n. */
function driverFor(wave) {
  const n = wave.n;
  return {
    async execute(ctx) {
      const src = path.join(ctx.projectDir, 'src', `f${n}.js`);
      const tst = path.join(ctx.projectDir, 'test', `f${n}.test.mjs`);
      if (!fs.existsSync(src)) fs.writeFileSync(src, `export const f${n} = () => ${n};\n`);
      if (!fs.existsSync(tst)) fs.writeFileSync(tst,
        "import {test} from 'node:test'; import assert from 'node:assert';\n" +
        `import {f${n}} from '../src/f${n}.js';\n` +
        `test('f${n}', () => assert.equal(f${n}(), ${n}));\n`);
      return { note: `implement feature ${n}` };
    },
    async review(ctx, gate) {
      return { reviewer: `r${ctx.reviewerIndex}`, answerable: 'yes',
        claim: gate.green ? 'green' : 'red', findings: [] };
    },
    async fix() { return { note: 'noop' }; },
  };
}

function rmrf(dir) { try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* ignore */ } }

// ---------------------------------------------------------------------------

test('happy path — each GO wave makes exactly one commit on the dedicated branch; main untouched; no push', async () => {
  const { dir, baseline } = makeGitProject(3);
  try {
    const res = await runProject({ projectDir: dir, driverFor, git: true });
    assert.equal(res.status, 'DONE', 'project DONE');

    // current branch is the dedicated work branch
    assert.equal(git(dir, ['rev-parse', '--abbrev-ref', 'HEAD']).out, 'foreman/run');
    // commit count on the work branch = baseline + exactly 3 wave commits
    assert.equal(git(dir, ['rev-list', '--count', 'foreman/run']).out, '4');
    // each wave commit subject is meaningful (NOT "Wave X complete")
    const subjects = git(dir, ['log', '--format=%s', 'foreman/run']).out.split('\n');
    assert.equal(subjects.filter((s) => /^foreman: wave \d+ "feature \d+" GREEN \(gate \d+\/\d+\)$/.test(s)).length, 3, subjects.join('|'));
    assert.equal(subjects.filter((s) => /Wave \d+ complete/i.test(s)).length, 0);
    // default branch main is UNTOUCHED (still at baseline)
    assert.equal(git(dir, ['rev-parse', 'main']).out, baseline, 'main untouched');
    // NO remote, so NO push could have happened
    assert.equal(git(dir, ['remote']).out, '', 'no remote');
    // reflog has no push/fetch entries
    assert.equal(git(dir, ['reflog']).out.match(/\bpush\b/) ? 'has-push' : 'clean', 'clean');
    // checkpoint.last_commit == HEAD (commit recorded after it landed, §8)
    const cp = readCheckpoint(path.join(dir, 'foreman-checkpoint.json'));
    assert.equal(cp.last_commit, git(dir, ['rev-parse', 'HEAD']).out, 'checkpoint last_commit == HEAD');
    assert.equal(cp.status, 'done');
    // working tree clean (Foreman state excluded via .git/info/exclude)
    assert.equal(git(dir, ['status', '--porcelain']).out, '', 'tree clean (foreman state excluded)');
  } finally { rmrf(dir); }
});

test('no commit on unproven green — a vacuous (exit-0/no-TAP) gate HALTs and creates NO commit', async () => {
  const { dir, baseline } = makeGitProject(2);
  try {
    // poison the gate to the R2-3 vacuous vector
    fs.writeFileSync(path.join(dir, 'IMPLEMENTATION-PLAN.md'),
      '# Plan\n\ntest-command: `cmd /c exit 0`\n\n## Wave 1 — f1\n\n## Wave 2 — f2\n');
    git(dir, ['commit', '-am', 'use vacuous gate']);
    const after = git(dir, ['rev-parse', 'HEAD']).out;
    const res = await runProject({ projectDir: dir, driverFor, git: true });
    assert.equal(res.status, 'HALT', 'vacuous wave HALTs');
    assert.match(res.haltReason, /vacuous-GREEN/);
    // foreman/run was created off `after`, but NO wave commit landed
    assert.equal(git(dir, ['rev-list', '--count', 'foreman/run']).out, '2', 'baseline + gate-change only; no wave commit');
    assert.equal(git(dir, ['rev-parse', 'foreman/run']).out, after, 'HEAD did not advance');
    void baseline;
  } finally { rmrf(dir); }
});

test('dirty-tree policy — refuse to START on an unexpectedly dirty tree (HALT, no clobber)', async () => {
  const { dir } = makeGitProject(2);
  try {
    const dirtyPath = path.join(dir, 'src', 'base.js');
    const userEdit = 'export const base = () => 999; // user work in progress\n';
    fs.writeFileSync(dirtyPath, userEdit); // unexpected uncommitted change
    await assert.rejects(
      () => runProject({ projectDir: dir, driverFor, git: true }),
      (e) => e instanceof HaltError && /dirty working tree/.test(e.reason),
    );
    // the user's change was NOT clobbered
    assert.equal(fs.readFileSync(dirtyPath, 'utf8'), userEdit, 'user change preserved');
    // still on main (never switched to a work branch on a dirty start)
    assert.equal(git(dir, ['rev-parse', '--abbrev-ref', 'HEAD']).out, 'main');
  } finally { rmrf(dir); }
});

test('reconciliation — COMMIT-THEN-CRASH: HEAD ahead of checkpoint.last_commit ⇒ adopt HEAD, no double-commit', async () => {
  const { dir, baseline } = makeGitProject(1);
  try {
    // Run wave 1 to GO: the commit (C1) lands and the checkpoint records it.
    const r1 = await runProject({ projectDir: dir, driverFor, git: true });
    assert.equal(r1.status, 'DONE');
    const c1 = git(dir, ['rev-parse', 'HEAD']).out;
    assert.notEqual(c1, baseline);
    const countAfterWave1 = git(dir, ['rev-list', '--count', 'foreman/run']).out; // '2'

    // Simulate commit-then-crash: C1 landed on disk/git, but the checkpoint had
    // NOT yet been updated to record wave 1 as GO — rewind it to the prior state.
    const cpPath = path.join(dir, 'foreman-checkpoint.json');
    const cp = readCheckpoint(cpPath);
    cp.last_commit = baseline;     // checkpoint still points at the prior commit
    cp.last_verdict = null;        // wave 1 not yet recorded GO
    cp.status = 'running';
    cp.current_wave = 1;
    cp.intra_wave_step = 'execute';
    writeCheckpointAtomic(cpPath, cp);

    // Resume: reconcile must adopt HEAD (commit-then-crash) and the idempotent
    // commit must NOT create a duplicate.
    const r2 = await runProject({ projectDir: dir, driverFor, git: true, resume: true });
    assert.equal(r2.status, 'DONE', 'resume completes');
    assert.equal(git(dir, ['rev-list', '--count', 'foreman/run']).out, countAfterWave1, 'NO double-commit');
    assert.equal(git(dir, ['rev-parse', 'HEAD']).out, c1, 'HEAD unchanged (adopted)');
  } finally { rmrf(dir); }
});

test('reconciliation — CRASH-BEFORE-COMMIT: wave work uncommitted, HEAD==last_commit ⇒ re-enter gate, then commit', async () => {
  const { dir, baseline } = makeGitProject(1);
  try {
    // Model an in-progress wave 1 whose work is on disk but NOT committed.
    fs.writeFileSync(path.join(dir, 'src', 'f1.js'), 'export const f1 = () => 1;\n');
    fs.writeFileSync(path.join(dir, 'test', 'f1.test.mjs'),
      "import {test} from 'node:test'; import assert from 'node:assert';\n" +
      "import {f1} from '../src/f1.js';\n" +
      "test('f1', () => assert.equal(f1(), 1));\n");
    // switch to the work branch (where Foreman would have been) and leave dirty
    git(dir, ['checkout', '-b', 'foreman/run']);
    assert.notEqual(git(dir, ['status', '--porcelain']).out, '', 'tree is dirty (in-progress work)');
    // checkpoint says wave 1 in progress, last_commit == baseline (no commit yet)
    const cpPath = path.join(dir, 'foreman-checkpoint.json');
    writeCheckpointAtomic(cpPath, {
      plan_path: path.join(dir, 'IMPLEMENTATION-PLAN.md'), current_wave: 1, total_waves: 1,
      intra_wave_step: 'fix', iteration: 0, reviewer_count: 2,
      budget_remaining: { waves: 1, fix_iters: 4, wall_clock_min: null },
      last_verdict: null, last_commit: baseline, open_findings: [], pending_action: null,
      stash_ref: null, status: 'running',
    });

    const res = await runProject({ projectDir: dir, driverFor, git: true, resume: true });
    assert.equal(res.status, 'DONE', 'resume re-enters gate and finishes');
    // the in-progress work is now committed exactly once
    assert.equal(git(dir, ['rev-list', '--count', 'foreman/run']).out, '2', 'baseline + 1 wave commit');
    assert.match(git(dir, ['log', '-1', '--format=%s']).out, /^foreman: wave 1 "feature 1" GREEN/, 'wave-1 commit present');
    assert.equal(git(dir, ['status', '--porcelain']).out, '', 'tree clean after commit');
  } finally { rmrf(dir); }
});

test('reconciliation — DIVERGED history (amended commit) ⇒ HALT, no blind-proceed', async () => {
  const { dir } = makeGitProject(1);
  try {
    const r1 = await runProject({ projectDir: dir, driverFor, git: true });
    assert.equal(r1.status, 'DONE');
    const cpPath = path.join(dir, 'foreman-checkpoint.json');
    const recorded = readCheckpoint(cpPath).last_commit; // C1
    // rewrite history: amend C1 -> C1' (sibling, not a descendant of C1)
    git(dir, ['commit', '--amend', '-m', 'rewritten history']);
    assert.notEqual(git(dir, ['rev-parse', 'HEAD']).out, recorded);
    await assert.rejects(
      () => runProject({ projectDir: dir, driverFor, git: true, resume: true }),
      (e) => e instanceof HaltError && /diverged/.test(e.reason),
    );
  } finally { rmrf(dir); }
});

test('reconciliation — resume on the WRONG branch ⇒ HALT', async () => {
  const { dir } = makeGitProject(1);
  try {
    const r1 = await runProject({ projectDir: dir, driverFor, git: true });
    assert.equal(r1.status, 'DONE');
    git(dir, ['checkout', 'main']); // operator left HEAD on the wrong branch
    await assert.rejects(
      () => runProject({ projectDir: dir, driverFor, git: true, resume: true }),
      (e) => e instanceof HaltError && /wrong git branch/.test(e.reason),
    );
  } finally { rmrf(dir); }
});

test('repo-boundary (§9) — a changed file under a NESTED .git repo HALTs', async () => {
  const { dir } = makeGitProject(1);
  try {
    const ctx = makeGitContext({ repoDir: dir });
    // create a nested repo with a file
    const sub = path.join(dir, 'vendor');
    fs.mkdirSync(sub, { recursive: true });
    assert.ok(git(sub, ['init', '-b', 'main']).ok);
    fs.writeFileSync(path.join(sub, 'x.js'), 'export const x = 1;\n');
    assert.throws(
      () => _internals.assertRepoBoundary(ctx.repoTop, ['vendor/x.js']),
      (e) => e instanceof HaltError && /nested \.git|more than one git toplevel/.test(e.reason),
    );
  } finally { rmrf(dir); }
});

test('containment guard — refuses any repo overlapping the Foreman source in either direction; work-branch cannot be main/master', async () => {
  // assertContainment HALTs for the Foreman root and for C:\dev (its parent)
  const { assertContainment } = await import('../bin/git-hygiene.mjs');
  assert.throws(() => assertContainment(_internals.FOREMAN_ROOT),
    (e) => e instanceof HaltError && /contains the Foreman source/.test(e.reason));
  assert.throws(() => assertContainment(path.resolve(_internals.FOREMAN_ROOT, '..')),
    (e) => e instanceof HaltError && /contains the Foreman source/.test(e.reason));
  // C3-8: the guard is BIDIRECTIONAL — a repo nested INSIDE the Foreman tree is
  // refused too (the prior directional guard let this through).
  assert.throws(() => assertContainment(path.join(_internals.FOREMAN_ROOT, 'sub')),
    (e) => e instanceof HaltError && /nested inside the Foreman source/.test(e.reason));
  assert.throws(() => assertContainment(path.join(_internals.FOREMAN_ROOT, 'fixtures', 'canonical-project')),
    (e) => e instanceof HaltError && /nested inside the Foreman source/.test(e.reason));
  // a normal external target (OS temp dir, neither containing nor inside Foreman)
  // is still allowed — the guard must not over-refuse.
  const { dir: external } = makeGitProject(1);
  try {
    assert.doesNotThrow(() => assertContainment(external));
  } finally { rmrf(external); }
  // a dedicated work branch named main/master is refused
  const { dir } = makeGitProject(1);
  try {
    assert.throws(() => makeGitContext({ repoDir: dir, workBranch: 'main' }),
      (e) => e instanceof HaltError && /default\/main branch/.test(e.reason));
  } finally { rmrf(dir); }
});

test('git off (default) — runProject makes NO commits and leaves git state untouched', async () => {
  const { dir, baseline } = makeGitProject(2);
  try {
    const res = await runProject({ projectDir: dir, driverFor }); // no git
    assert.equal(res.status, 'DONE');
    // still on main, still at baseline — the engine touched no git
    assert.equal(git(dir, ['rev-parse', '--abbrev-ref', 'HEAD']).out, 'main');
    assert.equal(git(dir, ['rev-parse', 'HEAD']).out, baseline, 'no commit made');
    assert.equal(git(dir, ['branch', '--list', 'foreman/run']).out, '', 'no work branch created');
    const cp = readCheckpoint(path.join(dir, 'foreman-checkpoint.json'));
    assert.equal(cp.last_commit, null, 'last_commit stays null without git');
  } finally { rmrf(dir); }
});

test('stale index.lock (P1) — a lock left by a prior crash is cleared on context creation', async () => {
  const { dir } = makeGitProject(1);
  try {
    const lock = path.join(dir, '.git', 'index.lock');
    fs.writeFileSync(lock, ''); // simulate a crash-leftover lock from a prior interrupted commit
    assert.ok(fs.existsSync(lock), 'precondition: stale lock present');
    const logs = [];
    makeGitContext({ repoDir: dir, log: (m) => logs.push(m) });
    assert.ok(!fs.existsSync(lock), 'stale lock removed on context creation');
    assert.ok(logs.some((l) => /stale .*index\.lock/i.test(l)), 'removal was logged');
  } finally { rmrf(dir); }
});

test('crash-resilience (P1) — an IN-PROGRESS checkpoint exists DURING wave execute, not only after', async () => {
  const { dir, baseline } = makeGitProject(2);
  const seen = [];
  function probingDriverFor(wave) {
    const base = driverFor(wave);
    return {
      async execute(ctx) {
        // capture the on-disk checkpoint at the moment execute runs (i.e. the
        // state a crash here would leave behind)
        try { seen.push({ n: wave.n, cp: readCheckpoint(path.join(ctx.projectDir, 'foreman-checkpoint.json')) }); }
        catch { seen.push({ n: wave.n, cp: null }); }
        return base.execute(ctx);
      },
      review: base.review,
      fix: base.fix,
    };
  }
  try {
    const res = await runProject({ projectDir: dir, driverFor: probingDriverFor, git: true });
    assert.equal(res.status, 'DONE');
    const w1 = seen.find((s) => s.n === 1);
    assert.ok(w1 && w1.cp, 'wave-1 checkpoint exists DURING execute (P1: previously none until wave end)');
    assert.equal(w1.cp.status, 'running');
    assert.equal(w1.cp.last_verdict, null, 'last_verdict null ⇒ reconcile re-enters at the gate on resume');
    assert.equal(w1.cp.current_wave, 1);
    assert.equal(w1.cp.last_commit, baseline, 'last_commit anchored at HEAD before wave 1 commits');
  } finally { rmrf(dir); }
});

test('Fix B: a tree change made AFTER the changed-set snapshot (e.g. by a reviewer) is still committed; no uncommitted residue', async () => {
  // Reproduces the Skill-Foundry wave gap: a reviewer mutated the tree AFTER the
  // engine snapshotted the changed set, so the (stale) commit dropped it and it sat
  // uncommitted. The fix re-measures the changed set AT COMMIT TIME and asserts the
  // tree is clean afterward.
  const { dir } = makeGitProject(1);
  let mutated = false;
  function driverForReviewMutates(wave) {
    const base = driverFor(wave);
    return {
      execute: base.execute,
      async review(ctx, gate) {
        if (!mutated) { // simulate a reviewer writing a file after the snapshot
          mutated = true;
          fs.writeFileSync(path.join(ctx.projectDir, 'reviewer-added.txt'), 'added during review\n');
        }
        return base.review(ctx, gate);
      },
      fix: base.fix,
    };
  }
  try {
    const res = await runProject({ projectDir: dir, driverFor: driverForReviewMutates, git: true });
    assert.equal(res.status, 'DONE', 'wave still GOes');
    assert.ok(git(dir, ['cat-file', '-e', 'HEAD:reviewer-added.txt']).ok,
      'the post-snapshot reviewer change was captured in the commit (re-measured at commit time)');
    assert.equal(git(dir, ['status', '--porcelain']).out, '',
      'tree clean after commit — no uncommitted residue (the completeness guard would HALT otherwise)');
  } finally { rmrf(dir); }
});

test('Fix B root cause: changedVsHead/dirtyEntries parse a space-status (" M") line WITHOUT mangling the path', () => {
  // The real bug: git() trimmed stdout, stripping the leading status space of the
  // first porcelain line (" M path" -> "M path"), so slice(3) dropped a char and
  // commitWave silently skipped the (nonexistent) mangled path. This is why
  // map.json — first among the modified files — was never committed.
  const { dir } = makeGitProject(1);
  try {
    // modify a TRACKED file -> porcelain " M src/base.js" (a space-status line).
    fs.writeFileSync(path.join(dir, 'src', 'base.js'), 'export const base = () => 2;\n');
    const ctx = makeGitContext({ repoDir: dir });
    assert.ok(ctx.changedVsHead().includes('src/base.js'),
      `changedVsHead must return the exact path; got ${JSON.stringify(ctx.changedVsHead())} (the bug yielded "rc/base.js")`);
    assert.ok(ctx.dirtyEntries().includes('src/base.js'),
      `dirtyEntries must return the exact path; got ${JSON.stringify(ctx.dirtyEntries())}`);
  } finally { rmrf(dir); }
});
