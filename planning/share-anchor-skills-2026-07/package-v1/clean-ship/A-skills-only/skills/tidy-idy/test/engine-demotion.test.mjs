// test/engine-demotion.test.mjs — Wave 1: the two stage demotions.
//
// Frozen deliverable (as amended): "hygiene demoted to a read-only reporting
// stage, and compress demoted to an in-memory proposal stage emitting a diff
// finding".
//
// Both demotions exist to remove a WRITE from the analysis pass, and each was a
// different kind of wrong before:
//
//   compress — bin/compress.mjs REWRITES agent.md in place. A lossy LLM rewrite
//     of a project's context file is exactly the sort of change a human should
//     approve before it lands, not something a background scan does on its way
//     past. Demoted, it computes the rewrite in memory and emits the DIFF; the
//     bytes the human approves are the bytes Wave 3 hashes into the temp index
//     (Amendment C.iv — never re-read from the working tree).
//
//   hygiene — bin/hygiene.mjs mutated the index/worktree (git stash) and
//     hard-refused non-git folders by throwing, with process.exit(1) on some
//     library paths. It modifies no FILE BYTES, so it has no diff to propose:
//     the honest demotion is to a read-only REPORTER that records repo state in
//     the envelope. (This asymmetry is why the plan was amended; the test states
//     it so the distinction cannot quietly erode.)

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { createContext } from '../engine/context.mjs';
import { compressStage } from '../engine/stages/compress.stage.mjs';
import { hygieneStage } from '../engine/stages/hygiene.stage.mjs';
import { STATUS } from '../engine/envelope.mjs';

const AGENT_BEFORE = [
  '# agent',
  '',
  'Active goal: ship Wave 1.',
  '',
  '## Old log',
  '2019: things happened',
  '2020: more things happened',
  '',
].join('\n');

let root;

/** Every file under `dir` as path -> bytes, for a bit-identical comparison. */
async function readTree(dir) {
  const out = {};
  for (const entry of await fs.readdir(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      for (const [k, v] of Object.entries(await readTree(p))) out[`${entry.name}/${k}`] = v;
    } else {
      out[entry.name] = await fs.readFile(p);
    }
  }
  return out;
}

beforeEach(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-demote-'));
  await fs.writeFile(path.join(root, 'agent.md'), AGENT_BEFORE);
});

afterEach(async () => {
  if (root) await fs.rm(root, { recursive: true, force: true, maxRetries: 5 });
});

describe('compress is DEMOTED to an in-memory proposal emitting a diff finding', () => {
  const compressingAgent = async () => ({
    executiveSummary: '# agent\n\nActive goal: ship Wave 1.\n',
    historyToAppend: '2019: things happened\n2020: more things happened\n',
  });

  test('emits a proposal finding carrying a real diff — and writes NOTHING', async () => {
    const before = await readTree(root);

    const ctx = await createContext({ rootPath: root, git: null, agent: compressingAgent });
    ctx.audit.enterStage('compress');
    const result = await compressStage.run(ctx);

    assert.strictEqual(result.status, STATUS.OK);
    assert.ok(result.findings.length >= 1, 'a changed agent.md must surface as a proposal');

    const proposal = result.findings.find((f) => f.path === 'agent.md');
    assert.ok(proposal, 'the agent.md proposal must be emitted');
    assert.strictEqual(proposal.action, 'propose-content',
      'a proposal is not an action — it is an offer the human accepts or declines');
    assert.strictEqual(proposal.kind, 'compression-proposal');

    // The diff is the deliverable: the panel must be able to show WHAT changes.
    assert.match(proposal.proposal.diff, /^--- a\/agent\.md/m);
    assert.match(proposal.proposal.diff, /^\+\+\+ b\/agent\.md/m);
    assert.match(proposal.proposal.diff, /^@@ /m);
    assert.ok(proposal.proposal.diff.split('\n').some((l) => l.startsWith('-2019: things happened')),
      'the diff must show the history lines leaving agent.md');
    assert.ok(proposal.proposal.stats.removed > 0, 'the stats must summarise the change for the tile');

    // The approved bytes travel WITH the finding (Amendment C.iv): Wave 3 hashes
    // these, and never re-reads the working tree, so what was approved is what
    // is committed even if the file changes in between.
    assert.strictEqual(proposal.proposal.content, '# agent\n\nActive goal: ship Wave 1.\n');

    // The whole point of the demotion.
    assert.deepStrictEqual(await readTree(root), before,
      'the analysis pass must leave the tree bit-identical — compress no longer writes agent.md');
    assert.strictEqual(ctx.audit.violations.length, 0,
      'and it must achieve that without tripping the tripwire (i.e. it never even attempts the write)');
  });

  test('the history append is proposed as its own finding, and agent_hist.md is NOT created', async () => {
    const ctx = await createContext({ rootPath: root, git: null, agent: compressingAgent });
    const result = await compressStage.run(ctx);

    const history = result.findings.find((f) => f.path === 'agent_hist.md');
    assert.ok(history, 'the history to move out of agent.md must be its own proposal');
    assert.strictEqual(history.proposal.createsFile, true,
      'the tile must be able to say this proposal CREATES a file');
    await assert.rejects(() => fs.stat(path.join(root, 'agent_hist.md')), /ENOENT/,
      'proposing a new file must not create it');
  });

  test('an unusable agent reply is PARTIAL and loud — never a silent success', async () => {
    const ctx = await createContext({ rootPath: root, git: null, agent: async () => ({ nonsense: true }) });
    const result = await compressStage.run(ctx);

    assert.strictEqual(result.status, STATUS.PARTIAL);
    assert.strictEqual(result.findings.length, 0);
    assert.ok(result.errors.length > 0, 'a failed proposal must carry its error, not vanish');
    assert.strictEqual((await fs.readFile(path.join(root, 'agent.md'), 'utf8')), AGENT_BEFORE);
  });

  test('no agent.md at all is an honest no-op, not an error', async () => {
    await fs.rm(path.join(root, 'agent.md'));
    const ctx = await createContext({ rootPath: root, git: null, agent: compressingAgent });
    const result = await compressStage.run(ctx);
    assert.strictEqual(result.status, STATUS.OK);
    assert.strictEqual(result.findings.length, 0);
    assert.match(result.coverage.note, /nothing to compress/);
  });
});

describe('hygiene is DEMOTED to read-only REPORTING (it has no diff to propose)', () => {
  /** A git handle double: the stage may only ever READ through it. */
  const gitDouble = (summary) => ({
    toplevel: root,
    rootIsToplevel: true,
    head: 'a'.repeat(40),
    branch: 'main',
    summary: async () => summary,
  });

  test('a DIRTY tree is RECORDED, never refused — the scan is not blocked', async () => {
    const ctx = await createContext({ rootPath: root, git: null, agent: async () => [] });
    ctx.git = gitDouble({ branch: 'main', head: 'a'.repeat(40), shortHead: 'aaaaaaa', dirtyCount: 3, dirty: true });

    const result = await hygieneStage.run(ctx);

    assert.strictEqual(result.status, STATUS.OK, 'a dirty working tree is a recorded fact, not a failure');
    assert.strictEqual(result.findings.length, 0, 'a reporting stage proposes nothing — it has no file bytes to change');
    assert.ok(result.notes.some((n) => /dirty=3/.test(n)), 'the dirty count must reach the envelope');
    assert.ok(result.notes.some((n) => /DIRTY/.test(n) && /read-only/.test(n)));
    assert.deepStrictEqual(result.data.git.dirtyCount, 3);
  });

  test('a root that is not the repo toplevel is reported, and flagged for Apply to refuse', async () => {
    const ctx = await createContext({ rootPath: root, git: null, agent: async () => [] });
    ctx.git = {
      ...gitDouble({ branch: 'main', head: 'b'.repeat(40), shortHead: 'bbbbbbb', dirtyCount: 0, dirty: false }),
      rootIsToplevel: false,
      toplevel: path.dirname(root),
    };

    const result = await hygieneStage.run(ctx);
    assert.strictEqual(result.status, STATUS.OK);
    assert.ok(result.notes.some((n) => /NOT the repository toplevel/.test(n) && /Apply must refuse/.test(n)));
  });

  test('an unreadable git status is PARTIAL — the stage never throws and never exits the process', async () => {
    const ctx = await createContext({ rootPath: root, git: null, agent: async () => [] });
    ctx.git = { ...gitDouble(null), summary: async () => { throw new Error('git exploded'); } };

    const result = await hygieneStage.run(ctx);
    assert.strictEqual(result.status, STATUS.PARTIAL,
      'a background run must degrade to partial, never take the host process down (the legacy process.exit path)');
    assert.match(result.errors[0].message, /git exploded/);
  });

  test('the tree is bit-identical afterwards (no stash, no index write, no worktree mutation)', async () => {
    const before = await readTree(root);
    const ctx = await createContext({ rootPath: root, git: null, agent: async () => [] });
    ctx.git = gitDouble({ branch: 'main', head: 'c'.repeat(40), shortHead: 'ccccccc', dirtyCount: 1, dirty: true });
    await hygieneStage.run(ctx);
    assert.deepStrictEqual(await readTree(root), before);
    assert.strictEqual(ctx.audit.violations.length, 0);
  });
});
