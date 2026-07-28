// test/apply-bootstrap.test.mjs — Wave 4: secret-safe Bootstrap (Amendment B).
//
// Frozen acceptance criteria under test, verbatim:
//   • "a plain folder containing source files and a .env with an API key … secret
//      triage runs before any `git add`, the .env path is written into the
//      starter .gitignore and surfaced, and baseline commit B verifiably does not
//      contain the .env content"
//   • "a folder whose pre-existing .gitignore Bootstrap appended to … undo
//      restores the prior .gitignore content byte-for-byte from the journal (it is
//      never deleted), removes only files Bootstrap created from nothing plus
//      .git, and refuses entirely once HEAD has moved past B"
//
// "BEFORE any `git add`" is tested as an ORDERING FACT, not as a comment: the
// journal is append-only with a monotonic seq, so the triage record's position
// relative to the git-add record is a checkable claim about what actually
// happened in what order.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  planBootstrap, buildBootstrapTile, applyBootstrap, undoBootstrap, canUndoBootstrap,
  BOOTSTRAP_STATUS, BOOTSTRAP_REFUSAL,
} from '../engine/apply/bootstrap.mjs';
import { readJournal } from '../engine/apply/journal.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';

import {
  makeTempRoot, rmTempRoot, write, git, initRepo, commitAll, listFiles,
} from './helpers/apply-fixture.mjs';
import { FAKE_AWS_KEY_ID, FAKE_AWS_SECRET } from './helpers/git-fixture.mjs';

const RUN = 'run-bootstrap-0001';

const tempRoots = [];
async function newRoot(prefix = 'tidy-idy-w4-boot-') {
  const root = await makeTempRoot(prefix);
  tempRoots.push(root);
  return root;
}
after(async () => { for (const r of tempRoots) await rmTempRoot(r); });

/** A plain folder: real source, and one .env holding a live-shaped credential. */
async function folderWithSecret({ gitignore = null } = {}) {
  const root = await newRoot();
  await write(root, 'src/main.mjs', 'export const go = () => 42;\n');
  await write(root, 'README.md', '# a real project\n');
  await write(root, '.env', `AWS_ACCESS_KEY_ID=${FAKE_AWS_KEY_ID}\naws_secret_access_key=${FAKE_AWS_SECRET}\n`);
  if (gitignore !== null) await write(root, '.gitignore', gitignore);
  return root;
}

async function readOrNull(abs) {
  try { return (await fs.readFile(abs)).toString('utf8'); } catch { return null; }
}

async function exists(abs) {
  try { await fs.stat(abs); return true; } catch { return false; }
}

async function journalRecords(reportDir, kind = 'bootstrap') {
  const j = await readJournal({ reportDir, runId: RUN, kind });
  return j ? j.records : [];
}

describe('planBootstrap is pure analysis — it looks, it does not act', () => {
  let root;
  before(async () => { root = await folderWithSecret(); });

  test('it flags the .env, names the ignore lines, and writes nothing', async () => {
    const before = await listFiles(root);
    const plan = await planBootstrap({ rootPath: root });

    assert.deepStrictEqual(plan.secretPaths, ['.env']);
    assert.ok(plan.gitignore.linesAdded.includes('.env'));
    assert.ok(plan.gitignore.linesAdded.includes('.tidy-idy/'), 'the tool keeps its own state out of the baseline too');
    assert.ok(!plan.baselineIncludes.includes('.env'), 'the .env is excluded from what the baseline would hold');
    assert.ok(plan.baselineIncludes.includes('src/main.mjs'));

    assert.deepStrictEqual(await listFiles(root), before, 'planning wrote nothing');
    assert.strictEqual(await exists(path.join(root, '.git')), false, 'and initialised nothing');
  });

  test('the approval tile discloses the exact .gitignore text it will write', async () => {
    const tile = buildBootstrapTile(await planBootstrap({ rootPath: root }));
    const ignoreOp = tile.ops.find((o) => o.kind === 'starter-gitignore');
    assert.strictEqual(ignoreOp.disclosesIgnoreRuleWrite, true);
    assert.match(ignoreOp.exactContent, /^\.env$/m, 'the secret line is on the tile, verbatim');
    assert.match(tile.consentScope, /only tile/i, 'and the tile says why it is the one operation allowed to do this');
    assert.deepStrictEqual(tile.secretsExcluded.map((s) => s.path), ['.env']);
    assert.ok(tile.secretsExcluded[0].why, 'the reason is surfaced, masked — not the matched bytes');
  });
});

describe('Bootstrap requires approval and refuses inside an existing repo', () => {
  test('an unapproved call does nothing', async () => {
    const root = await folderWithSecret();
    const result = await applyBootstrap({ rootPath: root, runId: RUN });
    assert.strictEqual(result.status, BOOTSTRAP_STATUS.REFUSED);
    assert.strictEqual(result.code, BOOTSTRAP_REFUSAL.NOT_APPROVED);
    assert.strictEqual(await exists(path.join(root, '.git')), false);
  });

  test('a folder that already has a repository is refused, not nested into', async () => {
    const root = await newRoot();
    await write(root, 'a.txt', 'a\n');
    await initRepo(root);
    await commitAll(root, 'baseline');

    const result = await applyBootstrap({ rootPath: root, runId: RUN, approved: true });
    assert.strictEqual(result.status, BOOTSTRAP_STATUS.REFUSED);
    assert.strictEqual(result.code, BOOTSTRAP_REFUSAL.ALREADY_A_REPO);
    assert.match(result.message, /gitlink/, 'the refusal explains the consequence it is avoiding');
  });
});

describe('the baseline commit provably does not contain the secret', () => {
  let root;
  let reportDir;
  let result;

  before(async () => {
    root = await folderWithSecret();
    reportDir = reportDirFor(root);
    result = await applyBootstrap({ rootPath: root, runId: RUN, approved: true });
  });

  test('Bootstrap succeeded and surfaced the excluded path', () => {
    assert.strictEqual(result.status, BOOTSTRAP_STATUS.BOOTSTRAPPED, result.message);
    assert.deepStrictEqual(result.secretsExcluded.map((s) => s.path), ['.env']);
    assert.strictEqual(result.secretsExcluded[0].inBaseline, false);
    assert.match(result.message, /verifiably absent/);
  });

  test('triage ran BEFORE any `git add` — asserted from the journal\'s own order', async () => {
    const records = await journalRecords(reportDir);
    const triage = records.find((r) => r.type === 'secret-triage');
    const add = records.find((r) => r.type === 'git-add');
    const ignoreWrite = records.find((r) => r.type === 'gitignore-write');

    assert.ok(triage && add && ignoreWrite, 'all three steps are journaled');
    assert.strictEqual(triage.beforeAnyGitAdd, true);
    assert.ok(triage.seq < ignoreWrite.seq, 'triage precedes the ignore write it feeds');
    assert.ok(ignoreWrite.seq < add.seq, 'the ignore write precedes the add it constrains');
    assert.deepStrictEqual(triage.flagged.map((f) => f.path), ['.env']);
  });

  test('.env is in .gitignore and is NOT in the tree of B', async () => {
    assert.match(await readOrNull(path.join(root, '.gitignore')), /^\.env$/m);

    const tree = await git(root, ['ls-tree', '-r', '--name-only', result.commit]);
    assert.ok(!tree.split('\n').includes('.env'), `B must not contain .env:\n${tree}`);
    assert.ok(tree.split('\n').includes('src/main.mjs'), 'the real source IS committed');
    assert.ok(!/\.tidy-idy/.test(tree), 'and the tool\'s own state stayed out of it');
  });

  test('no blob reachable from B contains the credential bytes', async () => {
    // The strongest available form of the criterion: not "the path is absent"
    // but "the CONTENT is absent", searched across every blob in the commit.
    await assert.rejects(
      git(root, ['grep', '--fixed-strings', FAKE_AWS_KEY_ID, result.commit]),
      'the key must not be findable anywhere in the baseline commit',
    );
  });

  test('the .env itself is untouched on disk — it was ignored, not moved or edited', async () => {
    const content = await readOrNull(path.join(root, '.env'));
    assert.match(content, new RegExp(FAKE_AWS_KEY_ID));
  });

  test('the journal records the verification, not just the intention', async () => {
    const records = await journalRecords(reportDir);
    const verification = records.find((r) => r.type === 'verification');
    assert.strictEqual(verification.state, 'ok');
    assert.deepStrictEqual(verification.checked, ['.env']);
  });
});

describe('Bootstrap undo restores the prior state byte-for-byte', () => {
  test('a pre-existing .gitignore is restored exactly, never deleted', async () => {
    const prior = 'node_modules/\n*.log\n';
    const root = await folderWithSecret({ gitignore: prior });
    const before = await listFiles(root);

    const applied = await applyBootstrap({ rootPath: root, runId: RUN, approved: true });
    assert.strictEqual(applied.status, BOOTSTRAP_STATUS.BOOTSTRAPPED, applied.message);
    assert.strictEqual(applied.gitignore.mode, 'appended');
    assert.notStrictEqual(await readOrNull(path.join(root, '.gitignore')), prior, 'it really was changed');

    const undone = await undoBootstrap({ rootPath: root, runId: RUN });

    assert.strictEqual(undone.status, BOOTSTRAP_STATUS.UNDONE, undone.message);
    assert.strictEqual(await readOrNull(path.join(root, '.gitignore')), prior,
      'the prior .gitignore came back byte-for-byte — Bootstrap only ever appended to it');
    assert.strictEqual(await exists(path.join(root, '.git')), false, '.git was removed');
    assert.deepStrictEqual(await listFiles(root), before, 'the folder is exactly as Bootstrap found it');
  });

  test('a .gitignore Bootstrap created from nothing is removed', async () => {
    const root = await folderWithSecret();
    const before = await listFiles(root);

    await applyBootstrap({ rootPath: root, runId: RUN, approved: true });
    assert.strictEqual(await exists(path.join(root, '.gitignore')), true);

    const undone = await undoBootstrap({ rootPath: root, runId: RUN });

    assert.strictEqual(undone.status, BOOTSTRAP_STATUS.UNDONE, undone.message);
    assert.strictEqual(undone.restored[0].mode, 'removed-file-bootstrap-created');
    assert.strictEqual(await exists(path.join(root, '.gitignore')), false);
    assert.deepStrictEqual(await listFiles(root), before);
    assert.strictEqual(await readOrNull(path.join(root, 'src/main.mjs')), 'export const go = () => 42;\n',
      'files Bootstrap did not create are never touched by its undo');
  });

  test('undo is REFUSED entirely once HEAD has moved past B', async () => {
    const root = await folderWithSecret();
    const applied = await applyBootstrap({ rootPath: root, runId: RUN, approved: true });

    await write(root, 'new-work.txt', 'work git now holds\n');
    await git(root, ['add', '-A']);
    await git(root, ['-c', 'user.name=t', '-c', 'user.email=<email>', 'commit', '-m', 'later work']);

    const gate = await canUndoBootstrap({ rootPath: root, runId: RUN });
    assert.strictEqual(gate.ok, false);
    assert.strictEqual(gate.code, BOOTSTRAP_REFUSAL.HEAD_MOVED);

    const undone = await undoBootstrap({ rootPath: root, runId: RUN });
    assert.strictEqual(undone.status, BOOTSTRAP_STATUS.REFUSED);
    assert.strictEqual(undone.code, BOOTSTRAP_REFUSAL.HEAD_MOVED);
    assert.match(undone.message, /discard work/);
    assert.strictEqual(await exists(path.join(root, '.git')), true, 'nothing was removed');
    assert.notStrictEqual(applied.commit, (await git(root, ['rev-parse', 'HEAD'])).trim());
  });

  test('NO-CLOBBER: a .gitignore edited after Bootstrap is refused, not overwritten', async () => {
    const root = await folderWithSecret({ gitignore: 'node_modules/\n' });
    await applyBootstrap({ rootPath: root, runId: RUN, approved: true });

    const mine = 'node_modules/\n# my own edit, after the fact\ndist/\n';
    await write(root, '.gitignore', mine);

    const undone = await undoBootstrap({ rootPath: root, runId: RUN });

    assert.strictEqual(undone.status, BOOTSTRAP_STATUS.PARTIAL, undone.message);
    assert.strictEqual(undone.refused.length, 1);
    assert.strictEqual(undone.refused[0].path, '.gitignore');
    assert.match(undone.refused[0].message, /NO-CLOBBER/);
    assert.strictEqual(await readOrNull(path.join(root, '.gitignore')), mine,
      'the edit made after the Apply survives — an undo never silently overwrites it');
    assert.strictEqual(await exists(path.join(root, '.git')), false,
      'the rest of the undo still proceeded: one refused path does not block the others');
  });

  test('undo of a run that was never bootstrapped refuses instead of guessing', async () => {
    const root = await folderWithSecret();
    const undone = await undoBootstrap({ rootPath: root, runId: 'run-that-never-ran' });
    assert.strictEqual(undone.status, BOOTSTRAP_STATUS.REFUSED);
    assert.strictEqual(undone.code, BOOTSTRAP_REFUSAL.NO_JOURNAL);
  });
});

describe('Bootstrap self-check: a secret that reached the index takes the whole thing down', () => {
  test('a leak is caught before the commit is kept, and the folder is left as found', async () => {
    const root = await folderWithSecret();
    const before = await listFiles(root);

    // A .gitignore write that silently does nothing is exactly the failure mode
    // Amendment B's verification exists to catch, so that is what is injected:
    // the plan still names .env, and the ignore rule never reaches disk.
    const realFs = fs;
    const brokenFs = new Proxy(realFs, {
      get(target, prop, receiver) {
        if (prop !== 'writeFile') return Reflect.get(target, prop, receiver);
        return async (file, ...rest) => {
          if (path.basename(String(file)) === '.gitignore' && path.dirname(path.resolve(String(file))) === path.resolve(root)) {
            return undefined; // the write "succeeds" and changes nothing
          }
          return target.writeFile(file, ...rest);
        };
      },
    });

    const result = await applyBootstrap({ rootPath: root, runId: RUN, approved: true, fs: brokenFs });

    assert.strictEqual(result.status, BOOTSTRAP_STATUS.REFUSED, JSON.stringify(result, null, 2));
    assert.strictEqual(result.code, BOOTSTRAP_REFUSAL.SECRET_IN_BASELINE);
    assert.deepStrictEqual(result.leaked, ['.env']);
    assert.strictEqual(await exists(path.join(root, '.git')), false, 'the repository was removed — no commit survives a leak');
    assert.deepStrictEqual(await listFiles(root), before, 'and the folder is exactly as Bootstrap found it');
  });
});
