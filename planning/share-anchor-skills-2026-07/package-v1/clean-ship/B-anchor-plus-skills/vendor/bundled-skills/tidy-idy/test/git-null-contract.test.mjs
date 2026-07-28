// test/git-null-contract.test.mjs — Wave 1, the named git:null contract test.
//
// Frozen acceptance criterion:
//   "Given a ctx with git=null, when git-null-contract.test.mjs runs every stage
//    against it, then each stage exhibits its declared no-op/advisory semantics
//    (e.g. save-detection: status=ok, zero findings, coverage note) and any
//    undeclared behavior fails the test."
//
// The contract is DECLARATIVE: every stage in the registry must publish a
// `gitNull` block, and this test runs the stage against a gitless ctx and holds
// it to its own declaration. A stage that quietly acquires a git dependency in
// a later wave fails here, not in production on someone's plain folder.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { STAGES } from '../engine/stages/index.mjs';
import { createContext } from '../engine/context.mjs';
import { checkTopology } from '../engine/topology.mjs';
import { captureSnapshot } from '../engine/snapshot.mjs';
import { runPipeline } from '../engine/pipeline.mjs';
import { STATUS } from '../engine/envelope.mjs';

let root;

before(async () => {
  root = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-gitnull-'));
  // A North-Star marker so the LLM stages take their REAL branch rather than
  // being excused by heuristic mode — the contract must hold on the live path.
  await fs.writeFile(path.join(root, 'NORTH-STAR.md'), '# North Star\n\nBuild the thing.\n');
  await fs.writeFile(path.join(root, 'agent.md'), '# agent\n\nActive goal: ship Wave 1.\n\n## Old log\n2019: things happened\n');
  await fs.writeFile(path.join(root, 'stale-note.txt'), 'an old scratch note\n');
});

after(async () => {
  if (root) await fs.rm(root, { recursive: true, force: true, maxRetries: 5 });
});

/** A ctx with git EXPLICITLY null, wired far enough for any stage to run. */
async function gitlessCtx(agent) {
  const ctx = await createContext({ rootPath: root, git: null, agent });
  ctx.state.topology = await checkTopology({
    rootPath: root, git: null, fs: ctx.fs, reportDir: ctx.reportDir,
    isExcluded: (rel) => ctx.protection.isExcluded(rel),
  });
  ctx.state.inScope = ctx.state.topology.inScope;
  ctx.state.snapshot = await captureSnapshot({ rootPath: root, head: null, paths: ctx.state.inScope, fs: ctx.fs });
  return ctx;
}

/** A cooperative agent double so the LLM stages exercise their real code path. */
const agentDouble = async (prompt, callOpts = {}) => {
  const label = String(callOpts.label || '');
  if (label.startsWith('hygiene-analysis')) return [{ filepath: 'stale-note.txt', reason: 'an old scratch note that serves nothing' }];
  if (label.startsWith('attacker')) return [{ filepath: 'stale-note.txt', case_for_removal: 'dead weight', strength: 'strong' }];
  if (label.startsWith('judge')) return [{ filepath: 'stale-note.txt', decision: 'REMOVE', rationale: 'no relationship to the North Star' }];
  if (label.startsWith('compress')) return { executiveSummary: '# agent\n\nActive goal: ship Wave 1.\n', historyToAppend: '2019: things happened\n' };
  return [];
};

describe('git:null contract — every stage declares its gitless behaviour', () => {
  for (const stage of STAGES) {
    test(`${stage.name} publishes a gitNull declaration`, () => {
      assert.ok(stage.gitNull, `stage '${stage.name}' has no gitNull declaration — every stage must state what it does without a repo`);
      assert.ok(['ok', 'partial', 'failed'].includes(stage.gitNull.status),
        `stage '${stage.name}' declares an invalid gitNull.status`);
      // Either an exact cap (0 for a stage whose findings are git-derived, e.g.
      // Wave-2 save-detection) or the literal 'unchanged' for a stage whose
      // findings do not depend on git at all. Anything else is undeclared.
      assert.ok(typeof stage.gitNull.findings === 'number' || stage.gitNull.findings === 'unchanged',
        `stage '${stage.name}' must declare its gitless finding behaviour as a number or 'unchanged'`);
      assert.ok(typeof stage.gitNull.note === 'string' && stage.gitNull.note.length > 0,
        `stage '${stage.name}' must carry a human-readable coverage note for the gitless case`);
    });
  }

  for (const stage of STAGES) {
    test(`${stage.name} HONOURS its declaration against a gitless ctx`, async () => {
      const ctx = await gitlessCtx(agentDouble);
      // Stages downstream of analyze need its output; run the prefix in order.
      for (const prior of STAGES) {
        if (prior === stage) break;
        await prior.run(ctx).catch(() => {});
      }

      let result;
      try {
        result = await stage.run(ctx);
      } catch (err) {
        assert.fail(`stage '${stage.name}' THREW against ctx.git=null: ${err.message} — a gitless folder is a declared, supported state, never an exception`);
      }

      assert.strictEqual(result.status, stage.gitNull.status,
        `stage '${stage.name}' declared gitless status='${stage.gitNull.status}' but returned '${result.status}' — undeclared behaviour`);

      if (stage.gitNull.findings === 0) {
        assert.strictEqual(result.findings.length, 0,
          `stage '${stage.name}' declared it emits no findings without a repo but emitted ${result.findings.length}`);
      } else {
        assert.ok(result.findings.length <= stage.gitNull.findings,
          `stage '${stage.name}' emitted more findings than its gitless declaration allows`);
      }

      assert.ok(result.coverage, `stage '${stage.name}' must always report coverage`);
      assert.strictEqual(typeof result.coverage.scanned, 'number');
      assert.strictEqual(typeof result.coverage.skipped, 'number');
      assert.strictEqual(typeof result.coverage.errored, 'number');
    });
  }

  test('no stage reads ctx.git without checking it (a gitless whole-pipeline run completes)', async () => {
    const envelope = await runPipeline({ rootPath: root, git: null, agent: agentDouble });

    assert.notStrictEqual(envelope.status, STATUS.FAILED,
      `a gitless run must COMPLETE, not fail: ${JSON.stringify(envelope.errors, null, 2)}`);
    assert.strictEqual(envelope.git.present, false, 'the envelope states plainly that there was no repository');
    const hygiene = envelope.stages.find((s) => s.stage === 'hygiene');
    assert.strictEqual(hygiene.status, STATUS.OK);
    assert.match(hygiene.coverage.note, /no repo/i);
    assert.strictEqual(envelope.snapshot.head, null, 'snapshot S records head=null for a gitless run');
  });
});

describe('git:null contract — the declared advisory semantics are visible in the envelope', () => {
  test('the run states no-repo in a way a renderer can show without inventing anything', async () => {
    const envelope = await runPipeline({ rootPath: root, git: null, agent: agentDouble });
    const hygiene = envelope.stages.find((s) => s.stage === 'hygiene');
    assert.ok(hygiene.notes.some((n) => /declared, supported state/.test(n)),
      'the gitless case must be stated as supported, not surfaced as a defect');
    assert.ok(hygiene.notes.some((n) => /Trash/.test(n)),
      'the note must say what the non-git undo story is, so the panel never implies a destructive delete');
  });
});
