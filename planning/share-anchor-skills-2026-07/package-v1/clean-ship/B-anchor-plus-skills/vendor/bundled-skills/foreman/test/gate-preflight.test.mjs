// gate-preflight.test.mjs — cf-slick gate honesty (journals 0038/0047/0049)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  HaltError,
  isBadNodeTestDirectoryCommand,
  preflightTestCommand,
  preflightDualRootImports,
} from '../bin/foreman-lib.mjs';

test('isBadNodeTestDirectoryCommand catches known-broken forms', () => {
  assert.equal(isBadNodeTestDirectoryCommand('node --test test/'), true);
  assert.equal(isBadNodeTestDirectoryCommand('node --test test'), true);
  assert.equal(isBadNodeTestDirectoryCommand('node --test "./test/"'), true);
  assert.equal(isBadNodeTestDirectoryCommand('node --test test/a.test.mjs'), false);
  assert.equal(isBadNodeTestDirectoryCommand('npm test'), false);
});

test('preflightTestCommand HALTs on bare test/ directory gate', () => {
  assert.throws(
    () => preflightTestCommand({ command: 'node --test test/', source: 'plan declaration' }),
    (e) => e instanceof HaltError && /known-broken/i.test(e.reason || e.message),
  );
});

test('preflightTestCommand passes explicit files', () => {
  const r = preflightTestCommand({
    command: 'node --test test/a.test.mjs test/b.test.mjs',
    source: 'plan declaration',
  });
  assert.equal(r.command.includes('a.test.mjs'), true);
  assert.ok(Array.isArray(r.warnings));
});

test('preflightTestCommand HALTs when package suite is larger than plan gate (0049)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-preflight-'));
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({
    type: 'module',
    scripts: {
      test: 'node --test test/a.test.mjs test/b.test.mjs test/c.test.mjs',
    },
  }));
  assert.throws(
    () => preflightTestCommand({
      command: 'node --test test/a.test.mjs',
      source: 'plan declaration',
    }, dir),
    (e) => e instanceof HaltError && /under-gate|0049|package/i.test(e.reason || e.message),
  );
});

test('preflightDualRootImports flags outside relative imports (0048)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-dual-'));
  fs.mkdirSync(path.join(dir, 'test'));
  // Import escapes project root
  fs.writeFileSync(path.join(dir, 'test', 'x.test.mjs'),
    `import { x } from '../../../outside/core.mjs';\n`);
  const r = preflightDualRootImports(dir, 'node --test test/x.test.mjs');
  assert.ok(r.outside.length >= 1, JSON.stringify(r));
});

test('preflightTestCommand HALTs on dual-root imports', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-dual2-'));
  fs.mkdirSync(path.join(dir, 'test'));
  fs.writeFileSync(path.join(dir, 'package.json'), JSON.stringify({ type: 'module' }));
  fs.writeFileSync(path.join(dir, 'test', 'x.test.mjs'),
    `import { x } from '../../../outside/core.mjs';\n`);
  assert.throws(
    () => preflightTestCommand({
      command: 'node --test test/x.test.mjs',
      source: 'plan declaration',
    }, dir),
    (e) => e instanceof HaltError && /outside the Foreman project root|0048/i.test(e.reason || e.message || e.detail || ''),
  );
});
