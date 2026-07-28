// test/engine-snapshot.test.mjs — Wave 1: snapshot S and the Tier-2 sweep.
//
// Covers the frozen acceptance criterion:
//   "Given a background run over a live project during which the user edits one
//    finding's file and one non-finding file mid-scan, when the post-analysis
//    sweep compares metadata against S, then the run COMPLETES (external drift
//    never aborts a background pass), the edited finding is marked STALE in the
//    envelope, the non-finding edit lands in the drift log, and Apply-time
//    revalidation later drops the stale item unless re-validated."

import { test, describe, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { captureSnapshot, ensureHash, sweepSnapshot, applyStaleness } from '../engine/snapshot.mjs';

let dir;

beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'tidy-idy-snap-'));
  await fs.writeFile(path.join(dir, 'finding.txt'), 'the file a finding points at\n');
  await fs.writeFile(path.join(dir, 'other.txt'), 'an unrelated file\n');
  await fs.writeFile(path.join(dir, 'quiet.txt'), 'nobody touches this\n');
});

afterEach(async () => {
  if (dir) await fs.rm(dir, { recursive: true, force: true, maxRetries: 5 });
});

/** Guarantee an mtime delta on filesystems with coarse timestamps. */
async function editWithDistinctMtime(file, content) {
  await fs.writeFile(file, content);
  const future = new Date(Date.now() + 5000);
  await fs.utimes(file, future, future);
}

describe('snapshot S', () => {
  test('records HEAD (or null), the in-scope path set and per-path size+mtime', async () => {
    const S = await captureSnapshot({ rootPath: dir, head: null, paths: ['finding.txt', 'other.txt'] });
    assert.strictEqual(S.head, null, 'a gitless run records head=null, not an absence of the field');
    assert.deepStrictEqual(Object.keys(S.paths).sort(), ['finding.txt', 'other.txt']);
    assert.ok(S.paths['finding.txt'].size > 0);
    assert.ok(Number.isFinite(S.paths['finding.txt'].mtimeMs));
    assert.ok(S.capturedAt, 'S is the time authority and must stamp when it was taken');
  });

  test('content hashes are LAZY — absent until a path becomes a finding', async () => {
    const S = await captureSnapshot({ rootPath: dir, paths: ['finding.txt', 'other.txt'] });
    assert.deepStrictEqual(S.hashes, {}, 'snapshotting a large tree must not hash every file');

    const h = await ensureHash(S, 'finding.txt');
    assert.match(h, /^sha256:[0-9a-f]{64}$/);
    assert.deepStrictEqual(Object.keys(S.hashes), ['finding.txt']);

    // Idempotent: asking again returns the same recorded hash.
    assert.strictEqual(await ensureHash(S, 'finding.txt'), h);
  });
});

describe('Tier 2 sweep — production background run (external drift NEVER aborts)', () => {
  test('a finding-path edit is STALE, a non-finding edit is DRIFT, and the run completes', async () => {
    const S = await captureSnapshot({ rootPath: dir, paths: ['finding.txt', 'other.txt', 'quiet.txt'] });

    await editWithDistinctMtime(path.join(dir, 'finding.txt'), 'the user kept working during the background pass\n');
    await editWithDistinctMtime(path.join(dir, 'other.txt'), 'so did they here\n');

    const sweep = await sweepSnapshot(S, { findingPaths: ['finding.txt'], hermetic: false });

    assert.notStrictEqual(sweep.status, 'failed', 'external drift must NEVER abort a production background run');
    assert.strictEqual(sweep.status, 'partial');
    assert.deepStrictEqual(sweep.stale, ['finding.txt']);
    assert.deepStrictEqual(sweep.drift.map((d) => d.path), ['other.txt']);
    assert.strictEqual(sweep.hermeticFailure, false);

    const findings = [{ path: 'finding.txt', action: 'remove' }, { path: 'quiet.txt', action: 'remove' }];
    assert.strictEqual(applyStaleness(findings, sweep.stale), 1);
    assert.strictEqual(findings[0].stale, true);
    assert.match(findings[0].staleReason, /Apply-time revalidation will drop it/);
    assert.strictEqual(findings[1].stale, undefined, 'an untouched finding must not be marked stale');
  });

  test('a deleted in-scope path is a delta, not a crash', async () => {
    const S = await captureSnapshot({ rootPath: dir, paths: ['finding.txt', 'quiet.txt'] });
    await fs.rm(path.join(dir, 'quiet.txt'));
    const sweep = await sweepSnapshot(S, { findingPaths: [] });
    assert.deepStrictEqual(sweep.drift.map((d) => [d.path, d.kind]), [['quiet.txt', 'deleted']]);
  });

  test('no drift at all → ok', async () => {
    const S = await captureSnapshot({ rootPath: dir, paths: ['finding.txt', 'other.txt'] });
    const sweep = await sweepSnapshot(S, { findingPaths: ['finding.txt'] });
    assert.strictEqual(sweep.status, 'ok');
    assert.deepStrictEqual(sweep.deltas, []);
  });
});

describe('Tier 2 sweep — HERMETIC CI fixture (ANY delta fails the build)', () => {
  test('a delta with no external editor present is a zero-write-invariant failure', async () => {
    const S = await captureSnapshot({ rootPath: dir, paths: ['finding.txt', 'other.txt'] });
    await editWithDistinctMtime(path.join(dir, 'other.txt'), 'only the engine could have done this\n');

    const sweep = await sweepSnapshot(S, { findingPaths: ['finding.txt'], hermetic: true });
    assert.strictEqual(sweep.hermeticFailure, true);
    assert.strictEqual(sweep.status, 'failed', 'in a hermetic fixture ANY delta is a build failure — this is what verifies the zero-write invariant');
    assert.match(sweep.note, /HERMETIC FIXTURE/);
  });

  test('a hermetic fixture with a genuinely untouched tree passes', async () => {
    const S = await captureSnapshot({ rootPath: dir, paths: ['finding.txt', 'other.txt', 'quiet.txt'] });
    const sweep = await sweepSnapshot(S, { hermetic: true });
    assert.strictEqual(sweep.status, 'ok');
    assert.strictEqual(sweep.hermeticFailure, false);
  });
});
