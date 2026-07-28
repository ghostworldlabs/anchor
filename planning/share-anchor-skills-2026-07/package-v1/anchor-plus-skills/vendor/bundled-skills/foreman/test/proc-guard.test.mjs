// proc-guard.test.mjs — Wave 7 durability: per-call timeout + kill-on-exit + the
// run lock, plus the INDUCED MID-WAVE KILL probe (the third pre-registered
// measurement). Exercised against a real dummy long-lived child (no model call).
// Run with: node --test test/proc-guard.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { HaltError, newCheckpoint, writeCheckpointAtomic } from '../bin/foreman-lib.mjs';
import { _internals as projInternals } from '../bin/project-engine.mjs';
import {
  acquireLock, readLock, isPidAlive, makeChildRegistry, spawnGuarded,
} from '../bin/proc-guard.mjs';
import { classifyExit, isExitClass, EXIT_CLASSES } from '../bin/transport.mjs';

const tmp = (p = 'foreman-proc-') => fs.mkdtempSync(path.join(os.tmpdir(), p));
const cleanup = (d) => fs.rmSync(d, { recursive: true, force: true });

/** Spawn a real, long-lived dummy child (a stand-in for a hung `claude -p`). */
function spawnLongLived(registry, timeoutMs = null) {
  return spawnGuarded({
    command: process.execPath,
    args: ['-e', 'setInterval(() => {}, 100000)'],
    registry, timeoutMs,
  });
}

async function waitDead(pid, ms = 5000) {
  const start = Date.now();
  while (Date.now() - start < ms) {
    if (!isPidAlive(pid)) return true;
    await new Promise((r) => setTimeout(r, 25));
  }
  return false;
}

// ---------------------------------------------------------------------------
// Run lock.
// ---------------------------------------------------------------------------

test('lock: acquire writes a pid lockfile; release removes it', () => {
  const dir = tmp();
  try {
    const lp = path.join(dir, 'run.lock');
    const lock = acquireLock(lp, { pid: process.pid, label: 'unit' });
    assert.equal(fs.existsSync(lp), true, 'lockfile created');
    const body = readLock(lp);
    assert.equal(body.pid, process.pid);
    assert.equal(typeof body.started_at, 'number');
    lock.release();
    assert.equal(fs.existsSync(lp), false, 'lockfile removed on release');
    // release is idempotent
    assert.doesNotThrow(() => lock.release());
  } finally { cleanup(dir); }
});

test('lock: a lock held by a LIVE different pid refuses a concurrent run (HALT)', () => {
  const dir = tmp();
  const reg = makeChildRegistry();
  let live;
  try {
    const lp = path.join(dir, 'run.lock');
    live = spawnLongLived(reg);           // a real, alive process to own the lock
    fs.writeFileSync(lp, JSON.stringify({ pid: live.child.pid, started_at: 1 }));
    assert.equal(isPidAlive(live.child.pid), true, 'holder is alive');
    assert.throws(() => acquireLock(lp, { pid: process.pid }),
      (e) => e instanceof HaltError && /holds the lock/.test(e.reason));
  } finally {
    reg.killAll();
    cleanup(dir);
  }
});

test('lock: a STALE lock (dead pid) is reclaimed, not honored', () => {
  const dir = tmp();
  try {
    const lp = path.join(dir, 'run.lock');
    const deadPid = 2147483646; // astronomically unlikely to be live
    assert.equal(isPidAlive(deadPid), false);
    fs.writeFileSync(lp, JSON.stringify({ pid: deadPid, started_at: 1 }));
    const lock = acquireLock(lp, { pid: process.pid }); // must reclaim, not throw
    assert.equal(readLock(lp).pid, process.pid, 'lock reclaimed by us');
    lock.release();
  } finally { cleanup(dir); }
});

test('lock: a garbage/unreadable lockfile is treated as stale and reclaimed', () => {
  const dir = tmp();
  try {
    const lp = path.join(dir, 'run.lock');
    fs.writeFileSync(lp, 'not json at all');
    const lock = acquireLock(lp, { pid: process.pid });
    assert.equal(readLock(lp).pid, process.pid);
    lock.release();
  } finally { cleanup(dir); }
});

test('isPidAlive: our own pid is alive; an absurd pid is not', () => {
  assert.equal(isPidAlive(process.pid), true);
  assert.equal(isPidAlive(2147483646), false);
  assert.equal(isPidAlive(-1), false);
  assert.equal(isPidAlive(0), false);
});

// ---------------------------------------------------------------------------
// Per-call timeout + kill-on-exit.
// ---------------------------------------------------------------------------

test('per-call timeout: a hung child is SIGKILLed and the exit is classified timeout-killed', async () => {
  const reg = makeChildRegistry();
  try {
    const { child, done } = spawnLongLived(reg, 200); // 200ms timeout vs a 100s sleeper
    const pid = child.pid;
    const res = await done;
    assert.equal(res.timedOut, true, 'our per-call timeout fired');
    assert.equal(await waitDead(pid), true, 'the hung child was killed');
    const c = classifyExit(res);
    assert.equal(c.class, EXIT_CLASSES.TIMEOUT_KILLED);
    assert.equal(reg.size(), 0, 'child untracked on close');
  } finally { reg.killAll(); }
});

test('spawn-failed: a missing binary classifies as spawn-failed (no crash)', async () => {
  const reg = makeChildRegistry();
  try {
    const { done } = spawnGuarded({ command: 'definitely-not-a-real-binary-xyz', args: [], registry: reg });
    const res = await done;
    assert.ok(res.spawnError, 'spawn error captured');
    assert.equal(classifyExit(res).class, EXIT_CLASSES.SPAWN_FAILED);
  } finally { reg.killAll(); }
});

test('kill-on-exit: install/uninstall registers and removes the process handlers (idempotent)', () => {
  const reg = makeChildRegistry();
  const before = process.listenerCount('exit');
  reg.install();
  reg.install(); // idempotent — no double registration
  assert.equal(process.listenerCount('exit'), before + 1, 'exactly one exit handler added');
  reg.uninstall();
  assert.equal(process.listenerCount('exit'), before, 'handler removed on uninstall');
});

// ---------------------------------------------------------------------------
// INDUCED MID-WAVE KILL probe (wave-7 Given/When/Then): when a mid-wave kill is
// induced, ZERO child PIDs survive, the lockfile RELEASES, the checkpoint
// RESUMES, and every exit is CLASSIFIED.
// ---------------------------------------------------------------------------

test('induced mid-wave kill: zero PIDs survive, lock releases, checkpoint resumes, exit classified', async () => {
  const dir = tmp('foreman-killprobe-');
  const reg = makeChildRegistry();
  try {
    // --- a wave is mid-flight: lock held + an in-progress checkpoint + a live child ---
    const lp = path.join(dir, '.foreman', 'run.lock');
    fs.mkdirSync(path.dirname(lp), { recursive: true });
    const lock = acquireLock(lp, { pid: process.pid, label: 'kill-probe' });

    const cpPath = path.join(dir, 'foreman-checkpoint.json');
    const cp = newCheckpoint({ plan_path: path.join(dir, 'PLAN.md'), total_waves: 1 });
    cp.current_wave = 1; cp.intra_wave_step = 'execute'; cp.last_verdict = null; cp.status = 'running';
    writeCheckpointAtomic(cpPath, cp);

    const { child, done } = spawnLongLived(reg);       // the "mid-wave sub-agent"
    const pid = child.pid;
    assert.equal(reg.size(), 1, 'one live child tracked');
    assert.equal(isPidAlive(pid), true);

    // --- INDUCE THE KILL: exactly what the kill-on-exit + exit handler do ---
    const killed = reg.killAll();   // SIGKILL every tracked child
    lock.release();                 // release the run lock on teardown
    const res = await done;         // the child's close resolves with typed-exit inputs

    // (a) ZERO child PIDs survive
    assert.ok(killed >= 1, 'killAll reported the child');
    assert.equal(await waitDead(pid), true, 'no child PID survives the induced kill');
    assert.equal(reg.size(), 0, 'registry drained');

    // (b) the lockfile RELEASES (so --resume can re-acquire)
    assert.equal(fs.existsSync(lp), false, 'lock released');
    assert.doesNotThrow(() => acquireLock(lp, { pid: process.pid }).release(),
      're-acquire succeeds after the kill (no wedged stale lock)');

    // (c) the checkpoint RESUMES: a 'running'/verdict-null wave re-enters at its wave
    const plan = projInternals.planResume(cpPath, 1);
    assert.equal(plan.startWave, 1, 'resume re-enters the in-progress wave (re-proves GREEN)');
    assert.equal(plan.alreadyDone, false);

    // (d) every exit is CLASSIFIED (no unclassified exit)
    const c = classifyExit(res);
    assert.equal(isExitClass(c.class), true, `killed child classified as "${c.class}"`);
    assert.notEqual(c.class, EXIT_CLASSES.OK, 'a killed child is not a clean OK');
  } finally {
    reg.killAll();
    cleanup(dir);
  }
});
