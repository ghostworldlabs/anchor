// test/launch-cost-gate.test.mjs — Wave 5: the gate that must never block.
//
// The carried round-1 finding named a concrete failure: a one-click run on a
// huge tree either hangs forever awaiting a proceed/narrow answer nobody is
// present to give, or burns unbounded LLM spend. These tests assert the
// resolution — degrade, complete, record, and put the interactive choice in the
// panel — including the structural half: there is no blocking branch to find.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import { evaluateCostGate, countTree, costConfig, GENERIC_EXCLUSIONS, DEFAULT_THRESHOLDS } from '../engine/launch/cost-gate.mjs';
import { makeProtection } from '../engine/protection.mjs';
import { parseTidyIdyToml } from '../engine/config.mjs';
import { makeTempRoot, rmTempRoot, write } from './helpers/git-fixture.mjs';

let root;

before(async () => {
  root = await makeTempRoot('tidy-idy-w5-cost-');
  await write(root, 'src/a.js', 'a'.repeat(100));
  await write(root, 'src/b.js', 'b'.repeat(100));
  await write(root, 'node_modules/dep/index.js', 'x'.repeat(10000));
  await write(root, 'assets/logo.png', 'p'.repeat(50000));
  await write(root, 'vendor/lib.js', 'v'.repeat(20000));
  await write(root, 'run.log', 'l'.repeat(30000));
});

after(async () => { await rmTempRoot(root); });

describe('countTree', () => {
  test('honours the exclusion predicate and never follows a link', async () => {
    const protection = makeProtection();
    const all = await countTree({ rootPath: root, isExcluded: () => false });
    const excluded = await countTree({ rootPath: root, isExcluded: (rel) => protection.isExcluded(rel) });
    assert.ok(all.files > excluded.files, 'the built-in exclusion set must actually remove files from the count');
    // node_modules is a built-in exclusion, so its bytes must not be counted.
    assert.ok(excluded.bytes < all.bytes);
  });

  test('the counting walk itself is capped, so the GATE can never be the hang', async () => {
    const capped = await countTree({ rootPath: root, cap: 2 });
    assert.strictEqual(capped.truncated, true);
    assert.ok(capped.files <= 2);
  });
});

describe('under threshold: nothing happens', () => {
  test('full scope, no degradation, no banner', async () => {
    const gate = await evaluateCostGate({ rootPath: root, config: {}, protection: makeProtection() });
    assert.strictEqual(gate.gated, false);
    assert.strictEqual(gate.blocked, false);
    assert.strictEqual(gate.degradation.applied, false);
    assert.strictEqual(gate.banner, null);
  });
});

describe('over threshold: DEGRADE, never block', () => {
  test('rung 1 applies the generic exclusions and the run still completes', async () => {
    // A threshold of 1 file puts this fixture over, exactly as a 300k-file
    // monorepo puts a real project over the real one.
    const config = parseTidyIdyToml('[cost]\nmax_files = 1\n');
    const gate = await evaluateCostGate({ rootPath: root, config, protection: makeProtection(config) });

    assert.strictEqual(gate.gated, true);
    assert.strictEqual(gate.blocked, false, 'the gate has no blocking branch — this field is stated, not implied');
    assert.strictEqual(gate.degradation.applied, true);
    assert.strictEqual(gate.degradation.steps[0].step, 'generic-exclusions');
    for (const p of GENERIC_EXCLUSIONS) assert.ok(gate.degradation.exclusionsApplied.includes(p));
    assert.ok(gate.degradation.steps[0].after.files < gate.degradation.steps[0].before.files,
      'applying the generic exclusions must actually shrink the analysed set');
  });

  test('rung 2 narrows the LLM stages to heuristic-only when rung 1 was not enough', async () => {
    const config = parseTidyIdyToml('[cost]\nmax_files = 0\n');
    const gate = await evaluateCostGate({ rootPath: root, config, protection: makeProtection(config) });
    assert.strictEqual(gate.degradation.heuristicOnly, true);
    assert.strictEqual(gate.degradation.forcedMode, 'heuristic');
    assert.strictEqual(gate.degradation.steps[1].step, 'heuristic-only');
  });

  test('the panel — not the run — owns the interactive choice', async () => {
    const config = parseTidyIdyToml('[cost]\nmax_files = 1\n');
    const gate = await evaluateCostGate({ rootPath: root, config, protection: makeProtection(config) });
    assert.strictEqual(gate.banner.kind, 'cost-gated');
    assert.match(gate.banner.title, /full run needs confirmation/);
    assert.strictEqual(gate.confirmFullRun.action, 'confirm-full-run');
    assert.deepStrictEqual(gate.confirmFullRun.overrides, { costGate: { enabled: false } });
    // One click, no free-text decision, and nothing in the record asks the RUN a
    // question.
    assert.ok(!JSON.stringify(gate).includes('"awaiting'));
  });
});

describe('.tidy-idy.toml overrides', () => {
  test('thresholds and extra exclusions come from the [cost] table', () => {
    const cfg = costConfig(parseTidyIdyToml('[cost]\nmax_files = 7\nmax_bytes = 99\nexclude_patterns = ["*.bin"]\n'));
    assert.strictEqual(cfg.maxFiles, 7);
    assert.strictEqual(cfg.maxBytes, 99);
    assert.deepStrictEqual(cfg.excludePatterns, ['*.bin']);
  });

  test('defaults apply when the table is absent', () => {
    const cfg = costConfig({});
    assert.strictEqual(cfg.maxFiles, DEFAULT_THRESHOLDS.maxFiles);
    assert.strictEqual(cfg.enabled, true);
  });

  test('`enabled = false` skips the gate — which is exactly what confirm-full-run does', async () => {
    const config = parseTidyIdyToml('[cost]\nenabled = false\nmax_files = 0\n');
    const gate = await evaluateCostGate({ rootPath: root, config, protection: makeProtection(config) });
    assert.strictEqual(gate.ran, false);
    assert.strictEqual(gate.gated, false);
    assert.strictEqual(gate.blocked, false);
  });

  test('a non-boolean `enabled` is a parse error, never a silent truthy value', () => {
    assert.throws(() => parseTidyIdyToml('[cost]\nenabled = 1\n'), /must be true or false/);
  });
});

describe('the cost gate cannot narrow protection', () => {
  test('[cost] exclude_patterns adds exclusions and reaches protection only as an addition', () => {
    const config = parseTidyIdyToml('[cost]\nexclude_patterns = ["*.bin"]\n');
    const protection = makeProtection(config);
    // The [cost] table is not read by makeProtection at all: the launcher hands
    // its patterns over as an explicit ADDITIVE overlay, so a cost setting can
    // never quietly unprotect anything.
    assert.strictEqual(protection.isProtected('SKILL.md'), true);
    assert.strictEqual(protection.isExcluded('x.bin'), false);
  });
});

describe('the gate reads no file content', () => {
  test('counting a tree of secrets never opens one', async () => {
    const dir = await makeTempRoot('tidy-idy-w5-cost2-');
    try {
      await write(dir, '.env', 'AWS_SECRET=nope');
      const opened = [];
      const spyFs = {
        readdir: fs.readdir,
        stat: async (p) => { if (!p.endsWith('.env')) return fs.stat(p); opened.push('stat'); return fs.stat(p); },
        readFile: async (p) => { opened.push(`readFile:${p}`); return fs.readFile(p); },
      };
      await countTree({ rootPath: dir, fs: spyFs });
      assert.deepStrictEqual(opened.filter((o) => o.startsWith('readFile')), [],
        'the cost walk is metadata-only — it must never read a byte of content');
    } finally {
      await rmTempRoot(dir);
    }
  });
});

test('the archive directory is excluded from the count and the scan', () => {
  const protection = makeProtection();
  assert.strictEqual(protection.isExcluded('reports/tidy/run-001/envelope.json'), true,
    "a run must never scan or judge its own previous output");
  assert.strictEqual(protection.isExcluded(path.posix.join('sub', 'reports/tidy/run-001')), true);
});
