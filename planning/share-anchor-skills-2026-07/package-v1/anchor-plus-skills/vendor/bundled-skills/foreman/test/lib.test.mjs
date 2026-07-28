// lib.test.mjs — focused unit tests for foreman-lib parsers.
// Run with: node --test
// Added in Phase 0.5 to carry the finding-I regression assertion (Phase 0 was
// verified via the CLIs; this is the first node:test file).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { parseWaves, newCheckpoint, writeCheckpointAtomic, HaltError } from '../bin/foreman-lib.mjs';

test('parseWaves parses contiguous ascending waves in order', () => {
  const waves = parseWaves('## Wave 1 — a\n## Wave 2 — b\n## Wave 3 — c\n');
  assert.deepEqual(waves.map((w) => w.n), [1, 2, 3]);
});

test('parseWaves HALTs when there are no waves', () => {
  assert.throws(() => parseWaves('no headings here\n'), HaltError);
});

test('parseWaves HALTs on non-contiguous waves', () => {
  assert.throws(() => parseWaves('## Wave 1\n## Wave 3\n'), HaltError);
});

// Finding I regression: a contiguous-but-out-of-order declaration must no longer
// return [2,1]; Foreman HALTs instead of silently reordering.
test('parseWaves HALTs on non-ascending declaration (finding I)', () => {
  assert.throws(
    () => parseWaves('## Wave 2 — second\n## Wave 1 — first\n'),
    (e) => e instanceof HaltError && /ascending/i.test(e.message),
  );
});

// Finding K (durability): after tmp->fsync->rename, the atomic write also fsyncs
// the PARENT DIRECTORY so the rename is crash-durable on POSIX. The dir-fsync is
// best-effort — on Windows/NTFS opening a directory for fsync is typically
// unsupported and the helper tolerates the failure — so the assertable invariant
// is that the parent-dir fsync is ATTEMPTED on every write, and the write still
// succeeds regardless of platform support. We prove the attempt by spying on
// fs.openSync (the same fs object the helper imports) for the parent-dir open.
test('K (durability): writeCheckpointAtomic attempts a parent-directory fsync after rename', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-kfsync-'));
  const file = path.join(dir, 'foreman-checkpoint.json');
  const cp = newCheckpoint({ plan_path: 'PLAN.md', total_waves: 1 });
  const origOpen = fs.openSync;
  const opened = [];
  fs.openSync = (p, ...rest) => { opened.push(String(p)); return origOpen(p, ...rest); };
  try {
    writeCheckpointAtomic(file, cp); // synchronous; spy active only for this call
  } finally {
    fs.openSync = origOpen;
  }
  const parent = path.dirname(path.resolve(file));
  assert.ok(opened.includes(parent),
    `parent directory ${parent} was opened for the durability fsync (attempt made)`);
  assert.ok(fs.existsSync(file),
    'the checkpoint write still succeeds even where dir-fsync is unsupported');
  fs.rmSync(dir, { recursive: true, force: true });
});
