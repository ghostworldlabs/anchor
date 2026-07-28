// foreman/test/induced-kill.test.mjs — Wave-7 done-when: the induced-mid-wave-kill probe
// with REAL processes (closes the "durability/induced-kill-coverage" MAJOR — the prior
// probe used a simulated signal). It spawns a real long-lived child through the same
// spawnGuarded + registry the live runner uses, then runs the exact `killAll()` that the
// orchestrator's exit/SIGINT/SIGTERM teardown invokes, and asserts ZERO child PIDs
// survive. Plus: the run lock releases on teardown and a stale (dead-pid) lock is
// reclaimed — so a killed orchestrator never wedges the next run. No model, deterministic.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { makeChildRegistry, spawnGuarded, isPidAlive, acquireLock } from '../bin/proc-guard.mjs';

test('induced-kill (REAL process): a tracked child is SIGKILLed and ZERO survive', async () => {
  const registry = makeChildRegistry();
  // A real, long-lived child (no model): a node process that idles indefinitely.
  const { child, done } = spawnGuarded({
    command: process.execPath, args: ['-e', 'setInterval(() => {}, 1e9)'], registry,
  });
  assert.ok(child && child.pid, 'child spawned with a pid');
  const pid = child.pid;
  assert.equal(isPidAlive(pid), true, 'the child is alive before the induced kill');
  assert.equal(registry.size(), 1, 'the child is tracked by the registry');

  // Induce exactly what an orchestrator teardown (clean exit OR SIGINT/SIGTERM) runs.
  const killed = registry.killAll();
  assert.equal(killed, 1, 'killAll SIGKILLed the one tracked child');

  await done; // the child's 'close' fires after the SIGKILL
  // Poll until the OS reports the pid gone (robust to reap timing across platforms).
  for (let i = 0; i < 40 && isPidAlive(pid); i++) await new Promise((r) => setTimeout(r, 25));
  assert.equal(isPidAlive(pid), false, 'ZERO child PIDs survive the induced kill');
  assert.equal(registry.size(), 0, 'the registry is drained');
});

test('induced-kill: the run lock RELEASES on teardown and a stale (dead-pid) lock is reclaimed', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'foreman-lock-'));
  const lockPath = path.join(dir, 'run.lock');
  try {
    // Hold the lock, then release (teardown) -> the lockfile is gone.
    const h = acquireLock(lockPath, { pid: process.pid });
    assert.equal(fs.existsSync(lockPath), true, 'lock acquired');
    h.release();
    assert.equal(fs.existsSync(lockPath), false, 'lock releases on teardown');

    // A lock LEFT BY A DEAD pid is stale -> reclaimable (a killed run never wedges the next).
    fs.writeFileSync(lockPath, JSON.stringify({ pid: 2 ** 30, started_at: 1 }));
    const h2 = acquireLock(lockPath, { pid: process.pid });
    assert.equal(h2.pid, process.pid, 'stale (dead-pid) lock reclaimed by the new run');
    h2.release();

    // A lock held by a LIVE, different pid refuses a concurrent run (HALT).
    fs.writeFileSync(lockPath, JSON.stringify({ pid: process.pid, started_at: 1 }));
    assert.throws(() => acquireLock(lockPath, { pid: process.pid + 1 }), /another Foreman run holds the lock/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
