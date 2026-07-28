// test/engine-save.test.mjs — Wave 2, the SAVE finding class.
//
// Frozen acceptance criterion covered here:
//
//   "Given a repo containing an untracked .env file with an AWS key and an
//    untracked useful script, when the save-detection and triage stages run,
//    then the script is offered as a SAVE finding with its porcelain record
//    while the .env is hard-blocked from SAVE with the specific trigger text and
//    the three alternatives, and no approval control exists for it"
//
// Plus the properties the plan states in prose and this suite turns into
// assertions: .gitignore'd files are never offered; dirty-overlap gating shows
// the exact would-be-committed diff; staged paths are flagged rather than
// silently folded in; and blind `git add` is structurally impossible.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';

import { runPipeline } from '../engine/pipeline.mjs';
import { parsePorcelainV2, TRACKING, unquotePath } from '../engine/porcelain.mjs';
import { SAVE_OP_KIND } from '../engine/stages/save.stage.mjs';
import {
  makeTempRoot, rmTempRoot, initRepo, write, commitAll, git,
  recordingAgent, cooperativeResponder, FAKE_AWS_KEY_ID,
} from './helpers/git-fixture.mjs';

let root;
let repo;
let envelope;

before(async () => {
  root = await makeTempRoot('tidy-idy-save-');
  repo = path.join(root, 'repo');
  await initRepo(repo);

  await write(repo, 'NORTH-STAR.md', '# North Star\n\nShip the importer.\n');
  await write(repo, 'src/importer.mjs', 'export const run = () => 1;\n');
  await write(repo, 'src/settings.json', '{"retries": 3}\n');
  await write(repo, 'src/staged-thing.mjs', 'export const staged = 1;\n');
  await write(repo, '.gitignore', 'ignored-output/\n*.tmp\n');
  await commitAll(repo, 'baseline');

  // 1. an untracked file worth keeping
  await write(repo, 'tools/backup.sh', '#!/bin/sh\n# genuinely useful, never committed\ntar czf backup.tgz src\n');
  // 2. an untracked file carrying a credential
  await write(repo, '.env', `AWS_ACCESS_KEY_ID=${FAKE_AWS_KEY_ID}\n`);
  // 3. a tracked file with UNSTAGED modifications
  await write(repo, 'src/settings.json', '{"retries": 5}\n');
  // 4. a tracked file with STAGED modifications
  await write(repo, 'src/staged-thing.mjs', 'export const staged = 2;\n');
  await git(repo, ['add', 'src/staged-thing.mjs']);
  // 5. content git deliberately ignores
  await write(repo, 'ignored-output/report.txt', 'regenerable\n');
  await write(repo, 'scratch.tmp', 'scratch\n');

  const agent = recordingAgent(cooperativeResponder({ suspects: [], removePaths: [] }));
  envelope = await runPipeline({ rootPath: repo, agent });
});

after(async () => { await rmTempRoot(root); });

const saves = () => envelope.findings.filter((f) => f.action === 'save');
const saveFor = (p) => saves().find((f) => f.path === p);

describe('SAVE findings come from real porcelain and carry it verbatim', () => {
  test('the run completed', () => {
    assert.notStrictEqual(envelope.status, 'failed', JSON.stringify(envelope.errors, null, 2));
    const save = envelope.stages.find((s) => s.stage === 'save');
    assert.ok(save, 'the save stage must be in the registry');
    assert.strictEqual(save.status, 'ok');
  });

  test('the untracked useful script is offered as a SAVE with its porcelain record', () => {
    const f = saveFor('tools/backup.sh');
    assert.ok(f, `tools/backup.sh should be a SAVE candidate; got ${JSON.stringify(saves().map((s) => s.path))}`);
    assert.strictEqual(f.trackingClass, TRACKING.UNTRACKED);
    assert.ok(f.porcelain && f.porcelain.startsWith('? '),
      `the finding must carry git's own line verbatim, got: ${JSON.stringify(f.porcelain)}`);
    assert.ok(f.porcelain.includes('tools/backup.sh'));
    assert.ok(f.contentHash && f.contentHash.startsWith('sha256:'),
      'the content hash is recorded into snapshot S at emission — Apply revalidates against it');
  });

  test('the tracked-with-unstaged-changes file is offered as a SAVE', () => {
    const f = saveFor('src/settings.json');
    assert.ok(f, 'a modified tracked file is a SAVE candidate — git holds an older version only');
    assert.strictEqual(f.trackingClass, TRACKING.TRACKED_MODIFIED);
    assert.ok(f.porcelain.startsWith('1 '), 'an ordinary changed entry, verbatim');
  });

  test('the .env with a live-looking key is NOT in the SAVE class at all', () => {
    assert.strictEqual(saveFor('.env'), undefined,
      'a secret-flagged path must have no SAVE finding — there must be nothing for an approval control to attach to');
    const blocked = envelope.findings.find((f) => f.kind === 'secret-blocked' && f.path === '.env');
    assert.ok(blocked, 'it must instead surface as a BLOCKED tile');
    assert.strictEqual(blocked.approvable, false);
    assert.match(blocked.maskedTriggerText, /AWS access key ID/);
    // The three alternatives.
    assert.ok(blocked.remediation.ops.some((o) => o.kind === 'add-to-gitignore'), 'alternative 1: the approvable ignore op');
    assert.ok(blocked.remediation.relocation, 'alternative 2: relocation guidance');
    assert.ok(blocked.remediation.configOverride, 'alternative 3: the next-run .tidy-idy.toml override');
  });
});

describe(".gitignore'd content is never offered", () => {
  for (const ignored of ['ignored-output/report.txt', 'scratch.tmp']) {
    test(`'${ignored}' is not a SAVE candidate`, () => {
      assert.strictEqual(saveFor(ignored), undefined,
        'git does not report ignored content as untracked, so it never enters the candidate set');
    });
  }
});

describe('dirty-overlap gating shows exactly what a commit WOULD contain', () => {
  test('a modified tracked file carries git\'s own diff of the would-be-committed change', () => {
    const f = saveFor('src/settings.json');
    assert.strictEqual(f.dirtyOverlap.available, true);
    assert.match(f.dirtyOverlap.source, /git diff HEAD/);
    assert.match(f.dirtyOverlap.diff, /-\{"retries": 3\}/);
    assert.match(f.dirtyOverlap.diff, /\+\{"retries": 5\}/);
  });

  test('an untracked file renders as an all-additions diff', () => {
    const f = saveFor('tools/backup.sh');
    assert.strictEqual(f.dirtyOverlap.available, true);
    assert.match(f.dirtyOverlap.diff, /\+tar czf backup\.tgz src/);
    assert.strictEqual(f.dirtyOverlap.staged, false);
  });

  test('a STAGED path is flagged, never silently folded into the commit', () => {
    const f = saveFor('src/staged-thing.mjs');
    assert.ok(f, 'a staged change is still an unsaved change');
    assert.strictEqual(f.hasStagedChanges, true);
    assert.ok(f.stagedWarning && /STAGED/.test(f.stagedWarning),
      'approving this tile commits the staged content, and the tile has to say so');
    assert.match(f.dirtyOverlap.diff, /export const staged = 2;/);
  });
});

describe('blind `git add` is structurally impossible', () => {
  test('every SAVE finding names CONTENT (by hash), never just a path to add', () => {
    assert.ok(saves().length > 0, 'there must be SAVE findings for this to mean anything');
    for (const f of saves()) {
      assert.ok(f.op, `${f.path} must carry an explicit op`);
      assert.strictEqual(f.op.kind, SAVE_OP_KIND,
        `${f.path} carries op kind '${f.op.kind}' — the only permitted SAVE op names the content, not the path`);
      assert.ok(f.op.contentHash, `${f.path}'s op must name the exact content hash Apply has to realise`);
      const serialised = JSON.stringify(f);
      assert.ok(!/git add/.test(serialised),
        `${f.path} carries a 'git add' instruction — a SAVE must never be able to mean "commit whatever is on disk at Apply time"`);
    }
  });

  test('SAVE findings default to unchecked', () => {
    for (const f of saves()) {
      assert.strictEqual(f.defaultChecked, false, `${f.path} must not be pre-approved`);
    }
  });
});

describe('the dirty tree was recorded, never refused', () => {
  test('the envelope states the dirty count and that the scan was not blocked', () => {
    assert.ok(envelope.dirty, 'the envelope must carry the dirty-tree record');
    assert.strictEqual(envelope.dirty.present, true);
    assert.strictEqual(envelope.dirty.dirty, true);
    assert.ok(envelope.dirty.count > 0);
    assert.strictEqual(envelope.dirty.blockedScan, false,
      'a dirty tree must never block a scan — that is the encoded policy');
  });
});

describe('the porcelain=v2 parser', () => {
  test('parses each record type and preserves the raw line', () => {
    const text = [
      '# branch.oid 1111111111111111111111111111111111111111',
      '# branch.head main',
      '1 .M N... 100644 100644 100644 aaa bbb src/mod.mjs',
      '1 M. N... 100644 100644 100644 aaa bbb src/staged.mjs',
      '2 R. N... 100644 100644 100644 aaa bbb R100 new/name.mjs\told/name.mjs',
      'u UU N... 100644 100644 100644 100644 aaa bbb ccc conflicted.mjs',
      '? untracked thing.txt',
      '! ignored.log',
      '',
    ].join('\n');
    const { branch, byPath } = parsePorcelainV2(text);

    assert.strictEqual(branch.head, 'main');
    assert.strictEqual(byPath.get('src/mod.mjs').trackingClass, TRACKING.TRACKED_MODIFIED);
    assert.strictEqual(byPath.get('src/staged.mjs').trackingClass, TRACKING.STAGED);
    assert.strictEqual(byPath.get('new/name.mjs').origPath, 'old/name.mjs');
    assert.strictEqual(byPath.get('conflicted.mjs').trackingClass, TRACKING.UNMERGED);
    assert.strictEqual(byPath.get('untracked thing.txt').trackingClass, TRACKING.UNTRACKED,
      'a path containing a space must survive parsing intact');
    assert.strictEqual(byPath.get('ignored.log').trackingClass, TRACKING.IGNORED);
    assert.ok(byPath.get('src/mod.mjs').raw.startsWith('1 .M'), 'the verbatim line is preserved');
  });

  test('C-quoted paths are unquoted rather than shifting the field split', () => {
    assert.strictEqual(unquotePath('"a\\tb.txt"'), 'a\tb.txt');
    assert.strictEqual(unquotePath('plain.txt'), 'plain.txt');
  });
});
