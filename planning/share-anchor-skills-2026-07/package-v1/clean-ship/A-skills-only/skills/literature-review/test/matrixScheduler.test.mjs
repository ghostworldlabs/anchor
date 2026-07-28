// Wave 2 done-when: the scheduler queues and executes a multi-node matrix
// exploration in parallel across isolated workers, streaming live real-time
// telemetry for all active threads.
import { test, describe } from 'node:test';
import assert from 'node:assert';
import { EventEmitter } from 'node:events';
import { fileURLToPath } from 'node:url';
import { MatrixScheduler, planBroadFirstBatches } from '../src/matrixScheduler.mjs';
import { ValidationError } from '../src/validateSchema.mjs';

const fixture = (name) => fileURLToPath(new URL(`./fixtures/tasks/${name}`, import.meta.url));

function matrixOf(rowCount, columns = ['method', 'sample-size']) {
  return {
    columns,
    rows: Array.from({ length: rowCount }, (_, i) => ({
      paperId: `paper-${i + 1}`,
      title: `Primary Source ${i + 1}`,
      values: Object.fromEntries(columns.map((c) => [c, `${c}-of-paper-${i + 1}`]))
    }))
  };
}

// A worker double matching the IsolatedWorker surface the scheduler and
// TelemetryHub rely on (workerId, state, EventEmitter, run()). Used only for
// the deterministic ordering/bounding/failure tests; the done-when test below
// uses real isolated processes.
function fakeWorkerFactory({ started = [], holdMs = 10, failPaperIds = new Set() } = {}) {
  let seq = 0;
  return (options) => {
    const worker = new EventEmitter();
    worker.workerId = `fake-${seq++}`;
    worker.state = 'created';
    worker.run = () => new Promise((resolve, reject) => {
      worker.state = 'running';
      worker.emit('state', 'running');
      started.push({
        batchId: options.input.batchId,
        paperId: options.input.paperId,
        depth: options.input.depth
      });
      setTimeout(() => {
        if (failPaperIds.has(options.input.paperId)) {
          worker.state = 'failed';
          worker.emit('state', 'failed');
          reject(new Error(`extraction failed for ${options.input.paperId}`));
        } else {
          worker.state = 'completed';
          worker.emit('state', 'completed');
          resolve({ ok: options.input.paperId, depth: options.input.depth });
        }
      }, holdMs);
    });
    return worker;
  };
}

describe('planBroadFirstBatches - bounded broad-first expansion', () => {
  test('defaults to one batch per primary source, in row order', () => {
    const batches = planBroadFirstBatches(matrixOf(3));
    assert.equal(batches.length, 3);
    assert.deepEqual(batches.map((b) => b.paperId), ['paper-1', 'paper-2', 'paper-3']);
    assert.ok(batches.every((b) => b.depth === 0));
    assert.deepEqual(batches[0].columns, ['method', 'sample-size']);
    assert.deepEqual(batches[0].values, {
      method: 'method-of-paper-1',
      'sample-size': 'sample-size-of-paper-1'
    });
  });

  test('bounded batches are ordered breadth-across-sources before depth', () => {
    const matrix = matrixOf(3, ['c1', 'c2', 'c3', 'c4']);
    const batches = planBroadFirstBatches(matrix, { batchColumns: 2 });
    assert.equal(batches.length, 6);
    // Every source's depth-0 batch precedes ANY source's depth-1 batch.
    assert.deepEqual(
      batches.map((b) => `${b.paperId}@${b.depth}`),
      ['paper-1@0', 'paper-2@0', 'paper-3@0', 'paper-1@1', 'paper-2@1', 'paper-3@1']
    );
    assert.deepEqual(batches[0].columns, ['c1', 'c2']);
    assert.deepEqual(batches[3].columns, ['c3', 'c4']);
    assert.deepEqual(batches[3].values, { c3: 'c3-of-paper-1', c4: 'c4-of-paper-1' });
    // batchIds are the deterministic execution order.
    assert.deepEqual(batches.map((b) => b.batchId), [0, 1, 2, 3, 4, 5]);
  });

  test('rejects a non-integer batch bound', () => {
    assert.throws(() => planBroadFirstBatches(matrixOf(1), { batchColumns: 0 }), TypeError);
    assert.throws(() => planBroadFirstBatches(matrixOf(1), { batchColumns: 2.5 }), TypeError);
  });
});

describe('MatrixScheduler - construction guards', () => {
  test('rejects a malformed research matrix with a ValidationError', () => {
    assert.throws(
      () => new MatrixScheduler({ matrix: { columns: 'nope' }, taskModule: fixture('matrixExtractTask.mjs') }),
      ValidationError
    );
  });

  test('requires a task module and a sane concurrency bound', () => {
    assert.throws(() => new MatrixScheduler({ matrix: matrixOf(1) }), TypeError);
    assert.throws(
      () => new MatrixScheduler({ matrix: matrixOf(1), taskModule: fixture('matrixExtractTask.mjs'), concurrency: 0 }),
      TypeError
    );
  });
});

describe('MatrixScheduler - done-when: 5 primary sources in parallel isolated processes', () => {
  test('spins up 5 strictly isolated processes concurrently and streams live telemetry', async () => {
    const scheduler = new MatrixScheduler({
      matrix: matrixOf(5),
      taskModule: fixture('matrixExtractTask.mjs'),
      concurrency: 5
    });

    const queued = [];
    const startedEvents = [];
    const threadEvents = [];
    const telemetryEvents = [];
    scheduler.on('task-queued', (e) => queued.push(e));
    scheduler.on('task-started', (e) => startedEvents.push(e));
    scheduler.on('thread', (t) => threadEvents.push(t));
    scheduler.on('telemetry', (e) => telemetryEvents.push(e));

    const report = await scheduler.run();

    // All 5 matrix nodes queued, executed, and reported in deterministic order.
    assert.equal(queued.length, 5);
    assert.equal(report.batches, 5);
    assert.equal(report.failed.length, 0);
    assert.deepEqual(report.completed.map((c) => c.batchId), [0, 1, 2, 3, 4]);
    assert.deepEqual(report.completed.map((c) => c.paperId),
      ['paper-1', 'paper-2', 'paper-3', 'paper-4', 'paper-5']);

    // 5 strictly isolated sub-agent processes: distinct pids, none the parent.
    const pids = report.completed.map((c) => c.result.pid);
    assert.equal(new Set(pids).size, 5, 'each source must run in its own process');
    assert.ok(pids.every((pid) => pid !== process.pid), 'no source may run in the parent process');

    // ...running concurrently: the manager was fully saturated at 5.
    assert.equal(scheduler.maxActive, 5);
    assert.equal(startedEvents.length, 5);

    // Live telemetry streamed for ALL active threads while they ran.
    const workerIds = new Set(startedEvents.map((e) => e.workerId));
    assert.equal(workerIds.size, 5);
    for (const workerId of workerIds) {
      const states = threadEvents.filter((t) => t.workerId === workerId).map((t) => t.state);
      assert.ok(states.includes('running'), `${workerId} must stream a running state`);
      assert.ok(states.includes('completed'), `${workerId} must stream a completed state`);
      const progress = telemetryEvents.filter((e) => e.workerId === workerId && e.type === 'progress');
      assert.ok(progress.length >= 2, `${workerId} must stream per-column progress telemetry`);
      assert.equal(progress.at(-1).payload.fraction, 1);
    }

    // Each worker extracted its own row's values through the isolation boundary.
    for (const entry of report.completed) {
      assert.equal(entry.result.extracted.method, `method-of-${entry.paperId}`);
    }

    // The post-run snapshot exposes every thread to the UI/CLI.
    const snapshot = scheduler.snapshot();
    assert.equal(snapshot.threads.length, 5);
    assert.ok(snapshot.threads.every((t) => t.state === 'completed'));
    assert.equal(snapshot.active, 0);
    assert.equal(snapshot.maxActive, 5);
  });
});

describe('MatrixScheduler - scheduling semantics', () => {
  test('executes batches broad-first across sources when serialized', async () => {
    const started = [];
    const scheduler = new MatrixScheduler({
      matrix: matrixOf(3, ['c1', 'c2', 'c3', 'c4']),
      taskModule: fixture('matrixExtractTask.mjs'),
      batchColumns: 2,
      concurrency: 1,
      workerFactory: fakeWorkerFactory({ started, holdMs: 5 })
    });
    await scheduler.run();
    assert.deepEqual(
      started.map((s) => `${s.paperId}@${s.depth}`),
      ['paper-1@0', 'paper-2@0', 'paper-3@0', 'paper-1@1', 'paper-2@1', 'paper-3@1']
    );
  });

  test('holds parallelism at the configured bound', async () => {
    const scheduler = new MatrixScheduler({
      matrix: matrixOf(6),
      taskModule: fixture('matrixExtractTask.mjs'),
      concurrency: 2,
      workerFactory: fakeWorkerFactory({ holdMs: 15 })
    });
    const report = await scheduler.run();
    assert.equal(report.completed.length, 6);
    assert.equal(scheduler.maxActive, 2);
  });

  test('surfaces a failed batch explicitly without aborting the exploration', async () => {
    const failures = [];
    const scheduler = new MatrixScheduler({
      matrix: matrixOf(3),
      taskModule: fixture('matrixExtractTask.mjs'),
      concurrency: 3,
      workerFactory: fakeWorkerFactory({ failPaperIds: new Set(['paper-2']) })
    });
    scheduler.on('task-failed', (e) => failures.push(e));

    const report = await scheduler.run();

    assert.equal(report.completed.length, 2);
    assert.deepEqual(report.completed.map((c) => c.paperId), ['paper-1', 'paper-3']);
    assert.equal(report.failed.length, 1);
    assert.equal(report.failed[0].paperId, 'paper-2');
    assert.match(report.failed[0].error.message, /extraction failed for paper-2/);
    assert.equal(failures.length, 1);
    assert.equal(failures[0].batchId, report.failed[0].batchId);
  });

  test('run() is idempotent: repeat calls return the same exploration', async () => {
    const started = [];
    const scheduler = new MatrixScheduler({
      matrix: matrixOf(2),
      taskModule: fixture('matrixExtractTask.mjs'),
      workerFactory: fakeWorkerFactory({ started })
    });
    const first = scheduler.run();
    const second = scheduler.run();
    assert.equal(first, second);
    await first;
    assert.equal(started.length, 2);
  });
});
