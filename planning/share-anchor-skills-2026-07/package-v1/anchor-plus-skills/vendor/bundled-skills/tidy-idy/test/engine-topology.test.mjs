// test/engine-topology.test.mjs — Wave 1: the run-start topology check.
//
// Deliverable: "Run-start topology check: toplevel resolution, nested .git/
// submodule/junction detection with hard subtree filtering; symlinks resolving
// outside root handled as link objects, never followed for read/SAVE
// (Amendment C.ii); junction escaping root aborts the run".

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { checkTopology, TOPOLOGY_STATUS } from '../engine/topology.mjs';
import { makeProtection } from '../engine/protection.mjs';
import { runPipeline } from '../engine/pipeline.mjs';
import { STATUS } from '../engine/envelope.mjs';

let tmp;
let root;
let outside;

beforeEach(async () => {
  tmp = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-topo-'));
  root = path.join(tmp, 'project');
  outside = path.join(tmp, 'outside');
  await fs.mkdir(root, { recursive: true });
  await fs.mkdir(outside, { recursive: true });
  await fs.writeFile(path.join(root, 'a.txt'), 'a\n');
  await fs.writeFile(path.join(outside, 'secret.txt'), 'not part of this project\n');
});

afterEach(async () => {
  if (tmp) await fs.rm(tmp, { recursive: true, force: true, maxRetries: 5 });
});

const protection = makeProtection();
const opts = () => ({ rootPath: root, isExcluded: (rel) => protection.isExcluded(rel) });

describe('topology — subtree filtering', () => {
  test("the root's own .git is excluded and never walked", async () => {
    await fs.mkdir(path.join(root, '.git', 'objects'), { recursive: true });
    await fs.writeFile(path.join(root, '.git', 'HEAD'), 'ref: refs/heads/main\n');
    const topo = await checkTopology(opts());
    assert.ok(topo.excludedSubtrees.some((e) => e.path === '.git' && e.reason === 'repo-metadata'));
    assert.ok(!topo.inScope.some((p) => p.startsWith('.git/')), 'repository metadata is never project content');
  });

  test('a NESTED repository is hard-filtered — its contents never enter scope', async () => {
    const nested = path.join(root, 'vendored-project');
    await fs.mkdir(path.join(nested, '.git'), { recursive: true });
    await fs.writeFile(path.join(nested, 'their-file.txt'), 'belongs to another history\n');
    const topo = await checkTopology(opts());
    assert.ok(topo.excludedSubtrees.some((e) => e.path === 'vendored-project' && e.reason === 'nested-repo'));
    assert.ok(!topo.inScope.some((p) => p.startsWith('vendored-project/')));
    assert.ok(topo.inScope.includes('a.txt'), 'the rest of the tree is unaffected');
  });

  test('a declared SUBMODULE is hard-filtered before it is even read', async () => {
    await fs.writeFile(path.join(root, '.gitmodules'), '[submodule "lib"]\n\tpath = lib\n\turl = https://example.invalid/lib.git\n');
    await fs.mkdir(path.join(root, 'lib'), { recursive: true });
    await fs.writeFile(path.join(root, 'lib', 'inner.txt'), 'submodule content\n');
    const topo = await checkTopology(opts());
    assert.ok(topo.excludedSubtrees.some((e) => e.path === 'lib' && e.reason === 'submodule'));
    assert.ok(!topo.inScope.some((p) => p.startsWith('lib/')));
  });

  test('the exclusion set filters node_modules and friends', async () => {
    await fs.mkdir(path.join(root, 'node_modules', 'left-pad'), { recursive: true });
    await fs.writeFile(path.join(root, 'node_modules', 'left-pad', 'index.js'), '//\n');
    const topo = await checkTopology(opts());
    assert.ok(topo.excludedSubtrees.some((e) => e.path === 'node_modules' && e.reason === 'exclusion-set'));
    assert.ok(!topo.inScope.some((p) => p.includes('node_modules')));
  });

  test('reportDir is excluded from scan (and is the tripwire\'s sole write exception)', async () => {
    const reportDir = path.join(root, '.tidy-idy');
    await fs.mkdir(reportDir, { recursive: true });
    await fs.writeFile(path.join(reportDir, 'previous-envelope.json'), '{}');
    const topo = await checkTopology({ ...opts(), reportDir });
    assert.ok(topo.excludedSubtrees.some((e) => e.path === '.tidy-idy' && e.reason === 'report-dir'));
    assert.ok(!topo.inScope.some((p) => p.startsWith('.tidy-idy')));
  });
});

describe('topology — links (Amendment C.ii)', () => {
  test('a FILE symlink resolving outside the root is a recorded link object, never followed', async (t) => {
    const linkPath = path.join(root, 'link-to-secret.txt');
    try {
      await fs.symlink(path.join(outside, 'secret.txt'), linkPath, 'file');
    } catch (err) {
      t.skip(`this host does not permit creating file symlinks (${err.code}) — the junction test below covers the escaping-link abort`);
      return;
    }
    const topo = await checkTopology(opts());
    assert.notStrictEqual(topo.status, TOPOLOGY_STATUS.ABORTED, 'an escaping FILE link is recorded, not an abort');
    const link = topo.links.find((l) => l.path === 'link-to-secret.txt');
    assert.ok(link, 'the link must be recorded as a link object');
    assert.strictEqual(link.escapes, true);
    assert.strictEqual(link.followed, false);
    assert.ok(!topo.inScope.includes('link-to-secret.txt'),
      'a link that resolves outside the root must never be readable or SAVEable as project content');
  });

  test('a DIRECTORY junction escaping the root ABORTS the run', async (t) => {
    const junctionPath = path.join(root, 'escape-hatch');
    try {
      await fs.symlink(outside, junctionPath, 'junction');
    } catch (err) {
      t.skip(`this host does not permit creating directory junctions/symlinks (${err.code})`);
      return;
    }

    const topo = await checkTopology(opts());
    assert.strictEqual(topo.aborted, true, 'a junction escaping the root would splice a foreign tree into scope');
    assert.strictEqual(topo.status, TOPOLOGY_STATUS.ABORTED);
    assert.match(topo.abortReason, /escape-hatch/);
    assert.match(topo.abortReason, /outside the run root/);

    // …and the abort is terminal for the whole run, not a warning.
    const envelope = await runPipeline({ rootPath: root, git: null, agent: async () => [] });
    assert.strictEqual(envelope.status, STATUS.FAILED);
    assert.strictEqual(envelope.isClean, false);
    const topoStage = envelope.stages.find((s) => s.stage === 'topology');
    assert.strictEqual(topoStage.status, STATUS.FAILED);
    assert.match(topoStage.errors[0].message, /aborted|outside the run root/i);
  });
});

describe('topology — toplevel resolution', () => {
  test('with no git handle, toplevel is simply not applicable (not an error)', async () => {
    const topo = await checkTopology({ ...opts(), git: null });
    assert.strictEqual(topo.toplevel, null);
    assert.strictEqual(topo.status, TOPOLOGY_STATUS.OK);
  });

  test('a root that is NOT its repo toplevel is recorded as partial with the reason', async () => {
    const topo = await checkTopology({
      ...opts(),
      git: { toplevel: path.join(tmp, 'enclosing'), rootIsToplevel: false },
    });
    assert.strictEqual(topo.status, TOPOLOGY_STATUS.PARTIAL);
    assert.ok(topo.errors.some((e) => e.kind === 'enclosing-repo'));
    assert.strictEqual(topo.aborted, false, 'read-only analysis of a subdirectory is legitimate; only Apply must refuse');
  });
});
