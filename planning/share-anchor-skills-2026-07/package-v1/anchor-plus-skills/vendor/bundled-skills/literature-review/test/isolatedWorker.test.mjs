// Wave 1 done-when: spawn an isolated worker process, receive authenticated
// IPC telemetry events, and verify strict memory and network isolation.
import { test, describe } from 'node:test';
import assert from 'node:assert';
import { fileURLToPath } from 'node:url';
import { IsolatedWorker, WorkerFailedError } from '../src/isolatedWorker.mjs';
import { signEvent, createIpcSecret } from '../src/ipcAuth.mjs';

const fixture = (name) => fileURLToPath(new URL(`./fixtures/tasks/${name}`, import.meta.url));

describe('IsolatedWorker - authenticated telemetry lifecycle', () => {
  test('spawns a worker, streams authenticated telemetry, and returns the result', async () => {
    const worker = new IsolatedWorker({
      taskModule: fixture('echoTask.mjs'),
      input: { label: 'wave-1', steps: 3 }
    });

    const states = [];
    const progress = [];
    const telemetry = [];
    const logs = [];
    worker.on('state', (s) => states.push(s));
    worker.on('progress', (p) => progress.push(p));
    worker.on('telemetry', (e) => telemetry.push(e));
    worker.on('log', (l) => logs.push(l));

    const result = await worker.run();

    assert.deepEqual(result, { echoed: 'wave-1', steps: 3, workerId: worker.workerId });
    assert.deepEqual(states, ['spawning', 'running', 'completed']);
    assert.equal(worker.state, 'completed');

    assert.equal(progress.length, 3);
    assert.deepEqual(progress.map(p => p.completed), [1, 2, 3]);
    assert.equal(progress[2].fraction, 1);
    assert.match(logs[0].message, /echo task started: wave-1/);

    // Every event surfaced by the wrapper carries a valid HMAC signature.
    assert.ok(telemetry.length >= 5); // running, log, 3x progress, result, completed
    for (const event of telemetry) {
      assert.equal(worker.verifyTelemetry(event), true, `event seq ${event.seq} must be authentic`);
      assert.equal(event.dir, 'w2p');
      assert.equal(event.workerId, worker.workerId);
    }
    // Sequence numbers are strictly increasing (no replays possible).
    for (let i = 1; i < telemetry.length; i++) {
      assert.ok(telemetry[i].seq > telemetry[i - 1].seq);
    }
  });

  test('rejects forged, malformed, and replayed IPC messages', async () => {
    const worker = new IsolatedWorker({
      taskModule: fixture('echoTask.mjs'),
      input: { label: 'auth-check', steps: 1 }
    });
    const telemetry = [];
    const rejected = [];
    worker.on('telemetry', (e) => telemetry.push(e));
    worker.on('unauthenticated', (r) => rejected.push(r));

    await worker.run();
    const stateBefore = worker.state;
    const violationsBefore = worker.violations.length;

    // Forged: well-formed envelope signed with an attacker's secret.
    const forged = signEvent({
      v: 1,
      dir: 'w2p',
      workerId: worker.workerId,
      seq: 999,
      ts: Date.now(),
      type: 'violation',
      payload: { kind: 'network', api: 'fake', target: 'fake', message: 'forged' }
    }, createIpcSecret());
    assert.equal(worker.handleRawMessage(forged), false);

    // Malformed: not even the right shape.
    assert.equal(worker.handleRawMessage({ hello: 'world' }), false);

    // Replayed: a genuine, correctly signed event injected a second time.
    assert.equal(worker.handleRawMessage(telemetry[0]), false);

    assert.deepEqual(rejected.map(r => r.reason), ['bad-signature', 'malformed', 'replayed-seq']);
    // None of the rejected messages had any effect on worker state.
    assert.equal(worker.state, stateBefore);
    assert.equal(worker.violations.length, violationsBefore);
  });

  test('a failing task rejects with the worker error and a failed state', async () => {
    const worker = new IsolatedWorker({ taskModule: fixture('crashTask.mjs') });
    const workerErrors = [];
    worker.on('worker-error', (e) => workerErrors.push(e));

    await assert.rejects(worker.run(), (err) => {
      assert.ok(err instanceof WorkerFailedError);
      assert.equal(err.state, 'failed');
      assert.match(err.lastError.message, /intentional crash for testing/);
      return true;
    });
    assert.equal(worker.state, 'failed');
    assert.match(workerErrors[0].message, /intentional crash/);
  });

  test('a hung task is killed at the timeout and lands in the killed state', async () => {
    const worker = new IsolatedWorker({
      taskModule: fixture('hangTask.mjs'),
      timeoutMs: 2000
    });
    await assert.rejects(worker.run(), (err) => {
      assert.ok(err instanceof WorkerFailedError);
      assert.equal(err.state, 'killed');
      return true;
    });
    assert.equal(worker.state, 'killed');
  });
});

describe('IsolatedWorker - strict network isolation', () => {
  test('a worker with an empty allowlist cannot reach any network endpoint', async () => {
    const worker = new IsolatedWorker({ taskModule: fixture('netProbeTask.mjs') });
    const violationEvents = [];
    worker.on('violation', (v) => violationEvents.push(v));

    const report = await worker.run();

    for (const surface of ['fetch', 'http', 'net', 'dns']) {
      assert.equal(report[surface].blocked, true, `${surface} must be blocked`);
      assert.equal(report[surface].name, 'NetworkAccessDeniedError');
    }
    // Each denial also arrived as authenticated violation telemetry.
    assert.ok(violationEvents.length >= 4);
    assert.ok(violationEvents.every(v => v.kind === 'network'));
    assert.deepEqual(worker.violations, violationEvents);
  });
});

describe('IsolatedWorker - strict memory isolation', () => {
  test('worker memory is a separate process with no unified shared memory', async () => {
    globalThis.__litreviewCanary = 'parent-value';
    try {
      const worker = new IsolatedWorker({ taskModule: fixture('memoryProbeTask.mjs') });
      const report = await worker.run();

      // Separate OS process.
      assert.notEqual(report.pid, process.pid);
      // The worker never saw the parent's global...
      assert.equal(report.canaryBefore, null);
      assert.equal(report.canaryAfter, 'worker-mutated');
      // ...and the worker's mutation never leaked back into the parent.
      assert.equal(globalThis.__litreviewCanary, 'parent-value');
      // Unified shared memory primitives are denied inside the worker.
      assert.equal(report.sharedArrayBuffer.blocked, true);
      assert.equal(report.sharedArrayBuffer.name, 'SharedMemoryDeniedError');
      assert.equal(report.wasmSharedMemory.blocked, true);
    } finally {
      delete globalThis.__litreviewCanary;
    }
  });
});
