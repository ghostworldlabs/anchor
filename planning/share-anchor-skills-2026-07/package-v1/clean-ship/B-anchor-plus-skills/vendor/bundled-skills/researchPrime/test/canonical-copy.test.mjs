// test/canonical-copy.test.mjs — crit 6 ("reuse-not-fork: each imported module resolves to a
// single canonical path") as an orchestrator-runnable assertion (IMPLEMENTATION-PLAN Wave 2).
//
// It resolves every SHARED specifier and asserts EXACTLY ONE on-disk path for each:
//   - the trio-core modules researchPrime owns resolve — via BOTH the package `imports` alias
//     and the package `exports` self-reference — to one and the same file inside this repo
//     (proving the package map, not a `../../` reach, is the canonical route — and that the
//     deferred Crucible/Foreman adoption would import THIS copy, never a fork);
//   - the upstream trio modules resolve through the single TRIO_ROOT pin to one file OUTSIDE
//     this repo, and NO forked copy of any of them exists inside this repo.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, statSync } from 'node:fs';
import path from 'node:path';

import {
  TRIO_CORE_MODULES,
  TRIO_UPSTREAM_MODULES,
  resolvePackageSpecifier,
  resolveUpstreamSpecifier,
  repoRoot,
} from '../bin/trio-core/manifest.mjs';

const ROOT = repoRoot();

/** Every file basename under ROOT (excluding VCS/runtime dirs), for the anti-fork scan. */
function allBasenames() {
  const skip = new Set(['.git', 'node_modules', '.foreman']);
  const names = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (skip.has(entry.name)) continue;
        walk(path.join(dir, entry.name));
      } else if (entry.isFile()) {
        names.push(entry.name);
      }
    }
  };
  walk(ROOT);
  return names;
}

function isInsideRepo(p) {
  const rel = path.relative(ROOT, p);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
}

test('each trio-core shared module resolves — via imports AND exports — to ONE in-repo file', () => {
  const resolved = [];
  for (const { name, importsSpecifier, exportsSpecifier } of TRIO_CORE_MODULES) {
    const viaImports = resolvePackageSpecifier(importsSpecifier);
    const viaExports = resolvePackageSpecifier(exportsSpecifier);
    assert.equal(
      viaImports,
      viaExports,
      `${name}: the #imports alias and the package export disagree on the on-disk path`,
    );
    assert.ok(statSync(viaImports).isFile(), `${name}: canonical path is not a file: ${viaImports}`);
    assert.ok(isInsideRepo(viaImports), `${name}: trio-core module must live in-repo: ${viaImports}`);
    resolved.push(viaImports);
  }
  // Distinct shared modules must be distinct files (the routes collide per-module by design, not across).
  assert.equal(new Set(resolved).size, TRIO_CORE_MODULES.length, 'two trio-core modules collided to one file');
});

test('exactly one on-disk copy of each trio-core module exists in the repo (no fork/dupe)', () => {
  const basenames = allBasenames();
  for (const { name } of TRIO_CORE_MODULES) {
    const file = `${name}.mjs`;
    const count = basenames.filter((b) => b === file).length;
    assert.equal(count, 1, `expected exactly one ${file} in the repo, found ${count}`);
  }
});

test('each upstream trio module resolves through the single pin to ONE file OUTSIDE the repo', () => {
  const resolved = [];
  for (const { name, spec } of TRIO_UPSTREAM_MODULES) {
    const p = resolveUpstreamSpecifier(spec);
    assert.ok(statSync(p).isFile(), `${name}: upstream path is not a file: ${p}`);
    assert.equal(isInsideRepo(p), false, `${name}: upstream module must NOT be copied in-repo: ${p}`);
    resolved.push(p);
  }
  assert.equal(new Set(resolved).size, TRIO_UPSTREAM_MODULES.length, 'two upstream specifiers collided to one file');
});

test('no forked copy of any upstream trio module exists in this repo (imports, never forks)', () => {
  const basenames = new Set(allBasenames());
  for (const { name, spec } of TRIO_UPSTREAM_MODULES) {
    const base = path.basename(spec);
    assert.equal(
      basenames.has(base),
      false,
      `found an in-repo file named ${base} (${name}) — researchPrime forks nothing; it imports via the pin`,
    );
  }
});

test('the trio-core shared modules actually import (the canonical paths are live, not dead)', async () => {
  const ia = await import('../bin/trio-core/independence-accounting.mjs');
  assert.equal(typeof ia.countIndependentOrigins, 'function');
  assert.equal(typeof ia.requiredQuorum, 'function');
  const cc = await import('../bin/trio-core/contract-core.mjs');
  assert.equal(typeof cc.HaltError, 'function');
  assert.equal(typeof cc.stampRole, 'function');
  assert.ok(cc.REVIEW_SCHEMA && typeof cc.REVIEW_SCHEMA === 'object');
});
