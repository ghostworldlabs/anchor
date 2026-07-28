// test/launch-identity.test.mjs — Wave 5: folder-agnostic project identity.
//
// The property under test is a NEGATIVE one: nothing in identity resolution
// consults an Anchor registry, so a plain folder outside Anchor is identified
// exactly as fully as an Anchor project.

import { test, describe } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';

import { projectIdentity, formatIdentity, sameProject } from '../engine/launch/identity.mjs';

describe('project identity is derived from the FOLDER', () => {
  test('a plain folder with no repo is fully identified', () => {
    const id = projectIdentity({ rootPath: path.join('/tmp', 'some folder'), git: null });
    assert.strictEqual(id.name, 'some folder');
    assert.strictEqual(id.path, path.resolve('/tmp/some folder'));
    assert.strictEqual(id.git.present, false);
    assert.match(id.git.note, /no repository/);
    assert.match(id.label, /some folder/);
    assert.match(id.label, /no git repository/);
  });

  test('a git-backed folder carries branch, short sha and dirty count', () => {
    const id = projectIdentity({
      rootPath: '/tmp/proj',
      git: { toplevel: path.resolve('/tmp/proj'), rootIsToplevel: true, head: 'a'.repeat(40), branch: 'main' },
      gitSummary: { branch: 'main', dirtyCount: 3, dirty: true },
    });
    assert.strictEqual(id.git.present, true);
    assert.strictEqual(id.git.shortSha, 'aaaaaaa');
    assert.strictEqual(id.git.dirtyCount, 3);
    assert.match(id.label, /main @ aaaaaaa @ 3 dirty/);
  });

  test('an Anchor project id is an ANNOTATION and never the identity', () => {
    const withAnchor = projectIdentity({ rootPath: '/tmp/proj', git: null, anchor: { projectId: 'p-123', dispatched: true } });
    const without = projectIdentity({ rootPath: '/tmp/proj', git: null });
    assert.strictEqual(withAnchor.anchor.projectId, 'p-123');
    assert.strictEqual(without.anchor.projectId, null);
    // The identity itself — the thing the header and the archive key off — is
    // BYTE-IDENTICAL with and without Anchor. That is the standalone claim.
    assert.strictEqual(withAnchor.name, without.name);
    assert.strictEqual(withAnchor.path, without.path);
    assert.strictEqual(withAnchor.label, without.label);
    assert.deepStrictEqual(withAnchor.git, without.git);
  });

  test('two folders with the same basename are NOT the same project', () => {
    const a = projectIdentity({ rootPath: '/tmp/one/src', git: null });
    const b = projectIdentity({ rootPath: '/tmp/two/src', git: null });
    assert.strictEqual(a.name, b.name);
    assert.strictEqual(sameProject(a, b), false, 'identity must be path equality, never name equality');
    assert.strictEqual(sameProject(a, projectIdentity({ rootPath: '/tmp/one/src', git: null })), true);
  });

  test('formatIdentity is the one header string, used on every launch path', () => {
    const line = formatIdentity({ name: 'x', path: '/p', git: { present: true, branch: null, shortSha: 'abc1234', dirtyCount: 0 } });
    assert.match(line, /detached @ abc1234 @ clean tree/);
  });
});
