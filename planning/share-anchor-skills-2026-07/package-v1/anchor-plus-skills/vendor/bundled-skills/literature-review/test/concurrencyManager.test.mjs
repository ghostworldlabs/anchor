// Wave 2 (concurrency half): the literature-review engine manages its OWN
// execution concurrency via a bounded, FIFO, self-contained manager —
// explicitly decoupled from Foreman's internal WorkerPool.
import { test, describe } from 'node:test';
import assert from 'node:assert';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { ConcurrencyManager } from '../src/concurrencyManager.mjs';

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

describe('ConcurrencyManager - bounded custom concurrency', () => {
  test('rejects invalid limits', () => {
    for (const limit of [undefined, 0, -1, 1.5, '3', null]) {
      assert.throws(() => new ConcurrencyManager({ limit }), TypeError,
        `limit ${JSON.stringify(limit)} must be rejected`);
    }
  });

  test('never exceeds the configured limit and completes every task', async () => {
    const manager = new ConcurrencyManager({ limit: 3 });
    let live = 0;
    let observedMax = 0;
    const results = await Promise.all(Array.from({ length: 10 }, (_, i) =>
      manager.run(async () => {
        live += 1;
        observedMax = Math.max(observedMax, live);
        await wait(10);
        live -= 1;
        return i;
      })
    ));
    assert.deepEqual(results, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    assert.ok(observedMax <= 3, `observed ${observedMax} concurrent tasks under a limit of 3`);
    assert.equal(manager.maxActive, 3); // 10 tasks fully saturate a limit of 3
    assert.equal(manager.active, 0);
    assert.equal(manager.pending, 0);
  });

  test('queued tasks start in strict FIFO order', async () => {
    const manager = new ConcurrencyManager({ limit: 1 });
    const started = [];
    await Promise.all([...Array(5).keys()].map((i) =>
      manager.run(async () => {
        started.push(i);
        await wait(5);
      })
    ));
    assert.deepEqual(started, [0, 1, 2, 3, 4]);
  });

  test('a throwing task releases its slot and rejects only its own run()', async () => {
    const manager = new ConcurrencyManager({ limit: 1 });
    const boom = manager.run(async () => { throw new Error('task exploded'); });
    const after = manager.run(async () => 'still-scheduled');
    await assert.rejects(boom, /task exploded/);
    assert.equal(await after, 'still-scheduled');
    assert.equal(manager.active, 0);
    assert.equal(manager.pending, 0);
  });

  test('run() rejects non-function work without consuming a slot', async () => {
    const manager = new ConcurrencyManager({ limit: 1 });
    await assert.rejects(manager.run('not a function'), TypeError);
    assert.equal(manager.active, 0);
  });

  test('onIdle resolves once all queued work has drained', async () => {
    const manager = new ConcurrencyManager({ limit: 2 });
    let done = 0;
    const tasks = [];
    for (let i = 0; i < 4; i++) {
      tasks.push(manager.run(async () => {
        await wait(10);
        done += 1;
      }));
    }
    await manager.onIdle();
    assert.equal(done, 4);
    assert.equal(manager.active, 0);
    await Promise.all(tasks);
  });
});

describe('Wave 2 modules - decoupled from Foreman', () => {
  test('the scheduler and concurrency manager import nothing from Foreman', async () => {
    for (const rel of ['../src/concurrencyManager.mjs', '../src/matrixScheduler.mjs']) {
      const source = await readFile(fileURLToPath(new URL(rel, import.meta.url)), 'utf8');
      const specifiers = [...source.matchAll(/from\s+['"]([^'"]+)['"]/g)].map((m) => m[1]);
      assert.ok(specifiers.length > 0, `${rel} must have import specifiers to inspect`);
      for (const spec of specifiers) {
        assert.doesNotMatch(spec, /foreman/i, `${rel} must not import from Foreman: ${spec}`);
        assert.doesNotMatch(spec, /workerpool/i, `${rel} must not reuse a WorkerPool: ${spec}`);
      }
    }
  });
});
