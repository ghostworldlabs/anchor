// test/engine-protection.test.mjs — Wave 1.
//
// Covers the frozen acceptance criterion:
//   "Given a fuzzed .tidy-idy.toml config, when the protection monotonicity
//    property test evaluates protected(defaults) vs protected(defaults + config),
//    then the built-in protected set is provably a subset of the configured set
//    — no config can narrow it — and a parse error yields a failed stage, not a
//    silent fallback."

import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { makeProtection, BUILTIN_PROTECTED, isProtectedByDefault } from '../engine/protection.mjs';
import { parseTidyIdyToml, loadConfig, ConfigParseError, SUBTRACTIVE_KEYS } from '../engine/config.mjs';
import { runPipeline } from '../engine/pipeline.mjs';
import { makeStageResult, STATUS } from '../engine/envelope.mjs';

describe('protection — deny by default', () => {
  const mustBeProtected = [
    'SKILL.md', 'NORTH-STAR.md', 'INTENT.md', 'README.md', 'LICENSE',
    'bin/tidy.mjs', 'engine/pipeline.mjs', 'test/scanner.test.mjs',
    'src/thing.test.mjs', 'journal/runs/2026.json', 'docs/design.md',
    '.github/workflows/ci.yml', 'Makefile', 'package.json', '.env.example',
    'nested/pkg/tests/helper.mjs', 'CHANGELOG.md',
  ];
  for (const p of mustBeProtected) {
    test(`'${p}' is protected with no config at all`, () => {
      assert.ok(isProtectedByDefault(p), `${p} must be protected by the built-in set`);
    });
  }

  test('ordinary project content is NOT protected (the predicate is a set, not a blanket)', () => {
    for (const p of ['src/old-thing.mjs', 'notes/scratch.txt', 'tmp/out.log', 'assets/logo.png']) {
      assert.strictEqual(isProtectedByDefault(p), false, `${p} should not be protected`);
    }
  });

  test('classify() names the pattern and class so a withheld path can say WHY', () => {
    const v = makeProtection().classify('test/scanner.test.mjs');
    assert.strictEqual(v.protected, true);
    assert.ok(v.pattern, 'a protected verdict must name the matching pattern');
    assert.ok(v.class, 'a protected verdict must name the protected class');
    assert.ok(v.why && v.why.length > 0);
  });

  test('filter() withholds actionable findings on protected paths and logs the reason', () => {
    const protection = makeProtection();
    const { kept, withheld } = protection.filter([
      { action: 'remove', path: 'bin/tidy.mjs' },
      { action: 'remove', path: 'src/dead.mjs' },
      // A non-actionable observation about a protected file still surfaces —
      // the panel may SAY a README looks stale; it may never offer to delete it.
      { action: 'inspect', path: 'README.md' },
    ]);
    assert.deepStrictEqual(kept.map((f) => f.path), ['src/dead.mjs', 'README.md']);
    assert.strictEqual(withheld.length, 1);
    assert.strictEqual(withheld[0].path, 'bin/tidy.mjs');
    assert.match(withheld[0].why, /PROTECTED/);
  });
});

describe('protection — MONOTONICITY property (no config can narrow the built-in set)', () => {
  // A deterministic fuzzer: no Math.random, so a failure is always reproducible.
  function* fuzzedConfigs() {
    const patternPool = [
      '**/*.mjs', 'src/**', '*', '**', 'README.md', 'bin/**', 'nothing-matches-this',
      'a/b/c.txt', '*.md', 'test/**', '', '   ', 'weird[unclosed', '../escape/**',
    ];
    const exclusionPool = ['vendor/**', 'coverage/**', '*', '**/*.png'];
    for (let i = 0; i < patternPool.length; i++) {
      for (let j = 0; j < exclusionPool.length; j++) {
        yield {
          protect: { patterns: [patternPool[i], patternPool[(i + 3) % patternPool.length]] },
          exclude: { patterns: [exclusionPool[j]] },
        };
      }
    }
    // Degenerate shapes.
    yield {};
    yield { protect: { patterns: [] } };
    yield { exclude: { patterns: [] } };
    yield { protect: { patterns: patternPool } };
  }

  const probePaths = [
    ...BUILTIN_PROTECTED.map((r) => r.pattern.replace(/\*\*/g, 'x').replace(/\*/g, 'y').replace(/\/$/, '')),
    'SKILL.md', 'bin/tidy.mjs', 'test/a.test.mjs', 'journal/x.json', 'docs/a.md',
    'src/app.mjs', 'notes.txt', 'assets/img.png', 'deep/nested/thing.mjs',
  ];

  test('protected(defaults) ⊆ protected(defaults + config) for every fuzzed config', () => {
    const base = makeProtection();
    let configs = 0;
    for (const config of fuzzedConfigs()) {
      configs++;
      const merged = makeProtection(config);
      for (const p of probePaths) {
        if (base.isProtected(p)) {
          assert.ok(merged.isProtected(p),
            `MONOTONICITY VIOLATED: '${p}' is protected by default but NOT under config ${JSON.stringify(config)} — a config narrowed the built-in protected set`);
        }
      }
      // The built-in patterns themselves must all survive into the merged set.
      for (const r of BUILTIN_PROTECTED) {
        assert.ok(merged.patterns.includes(r.pattern),
          `MONOTONICITY VIOLATED: built-in pattern '${r.pattern}' is missing from the merged set under ${JSON.stringify(config)}`);
      }
    }
    assert.ok(configs > 20, `expected a meaningful number of fuzzed configs, ran ${configs}`);
  });

  test('an additive config genuinely ADDS (the union is not a no-op)', () => {
    const merged = makeProtection({ protect: { patterns: ['src/keepme/**'] } });
    assert.strictEqual(makeProtection().isProtected('src/keepme/a.mjs'), false);
    assert.strictEqual(merged.isProtected('src/keepme/a.mjs'), true);
  });
});

describe('protection runs BEFORE emission, inside the pipeline', () => {
  // Unit-testing filter() proves the predicate; this proves the ORCHESTRATOR
  // actually applies it, which is the property the plan states ("filtering
  // findings before emission and logging withheld paths"). A protected path must
  // never reach envelope.findings — not merely be marked there.
  const greedyStage = {
    name: 'greedy',
    requiresGit: false,
    gitNull: { status: STATUS.OK, findings: 0, note: 'test double' },
    async run() {
      return makeStageResult({
        stage: 'greedy',
        status: STATUS.OK,
        coverage: { scanned: 3, skipped: 0, errored: 0 },
        findings: [
          { action: 'remove', path: 'SKILL.md' },
          { action: 'remove', path: 'bin/tidy.mjs' },
          { action: 'remove', path: 'junk.txt' },
        ],
      });
    },
  };

  test('protected paths never reach envelope.findings and ARE logged with a reason', async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-prot-pipe-'));
    try {
      await fs.mkdir(path.join(dir, 'bin'), { recursive: true });
      await fs.writeFile(path.join(dir, 'SKILL.md'), '# skill\n');
      await fs.writeFile(path.join(dir, 'bin', 'tidy.mjs'), '// entry point\n');
      await fs.writeFile(path.join(dir, 'junk.txt'), 'junk\n');

      const envelope = await runPipeline({
        rootPath: dir, git: null, agent: async () => [], stages: [greedyStage],
      });

      assert.deepStrictEqual(envelope.findings.map((f) => f.path), ['junk.txt'],
        'a protected path must be withheld BEFORE emission, not offered and then flagged');

      const withheldPaths = envelope.protectionWithheld.map((w) => w.path).sort();
      assert.deepStrictEqual(withheldPaths, ['SKILL.md', 'bin/tidy.mjs']);
      for (const w of envelope.protectionWithheld) {
        assert.strictEqual(w.stage, 'greedy', 'the withheld log must attribute the path to the stage that proposed it');
        assert.ok(w.pattern, 'the log must name the pattern that matched');
        assert.match(w.why, /PROTECTED/);
      }

      // The surviving finding carries its content hash — lazily entered into S
      // at emission time, which is what Wave 3 revalidates against.
      assert.match(envelope.findings[0].contentHash, /^sha256:[0-9a-f]{64}$/);

      // Ruleset stamp: on the report, derived from the sets actually in force.
      assert.match(envelope.ruleset.version, /^rs1-[0-9a-f]{16}$/,
        'every report carries the ruleset-version stamp that produced it');
    } finally {
      await fs.rm(dir, { recursive: true, force: true, maxRetries: 5 });
    }
  });
});

describe('config — strictly additive vocabulary and loud parse errors', () => {
  for (const key of SUBTRACTIVE_KEYS) {
    test(`\`${key}\` is REFUSED, not ignored`, () => {
      assert.throws(
        () => parseTidyIdyToml(`[protect]\n${key} = ["README.md"]\n`),
        (err) => err instanceof ConfigParseError && /strictly additive/i.test(err.message),
        `${key} must be a loud refusal — silently ignoring it would lie to the user who wrote it`);
    });
  }

  test('a well-formed additive config parses', () => {
    const cfg = parseTidyIdyToml([
      '# tidy-idy config',
      '[protect]',
      'patterns = ["src/sacred/**", "notes/*.md"]',
      '',
      '[exclude]',
      'patterns = [',
      '  "vendor/**",',
      '  "coverage/**",',
      ']',
      '',
      '[limits]',
      'max_files = 50000',
    ].join('\n'));
    assert.deepStrictEqual(cfg.protect.patterns, ['src/sacred/**', 'notes/*.md']);
    assert.deepStrictEqual(cfg.exclude.patterns, ['vendor/**', 'coverage/**']);
    assert.strictEqual(cfg.limits.max_files, 50000);
  });

  test('unknown tables and keys are parse errors (a typo must not silently do nothing)', () => {
    assert.throws(() => parseTidyIdyToml('[protectt]\npatterns = ["a"]\n'), ConfigParseError);
    assert.throws(() => parseTidyIdyToml('[protect]\npatternz = ["a"]\n'), ConfigParseError);
    assert.throws(() => parseTidyIdyToml('patterns = ["a"]\n'), ConfigParseError);
    assert.throws(() => parseTidyIdyToml('[protect]\npatterns = "a"\n'), ConfigParseError);
    assert.throws(() => parseTidyIdyToml('[protect]\nthis is not toml\n'), ConfigParseError);
  });

  test('a MISSING config is not an error — defaults apply', async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-cfg-'));
    try {
      const { config, present } = await loadConfig(dir);
      assert.strictEqual(present, false);
      assert.deepStrictEqual(config, {});
    } finally {
      await fs.rm(dir, { recursive: true, force: true });
    }
  });

  test('a MALFORMED config yields a FAILED stage — never a silent fallback to defaults', async () => {
    const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-cfg-bad-'));
    try {
      await fs.writeFile(path.join(dir, '.tidy-idy.toml'), '[protect]\nunprotect = ["README.md"]\n');
      const envelope = await runPipeline({ rootPath: dir, git: null, agent: async () => [] });
      assert.strictEqual(envelope.status, STATUS.FAILED, 'a config parse error must fail the run');
      assert.strictEqual(envelope.isClean, false, 'a run that could not read its config can never be clean');
      const configStage = envelope.stages.find((s) => s.stage === 'config');
      assert.ok(configStage, 'the failure must be attributed to a named config stage');
      assert.match(configStage.errors[0].message, /strictly additive/i);
    } finally {
      await fs.rm(dir, { recursive: true, force: true });
    }
  });
});
