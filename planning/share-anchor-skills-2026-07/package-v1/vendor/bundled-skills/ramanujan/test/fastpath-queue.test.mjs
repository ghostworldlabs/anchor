// Overhaul Wave 2 — Crucible/Foreman Pipeline Integration: the FAST-PATH WASM QUEUE.
//
// Exercises the REAL Wave-2 source (src/fastpath-queue.mjs): synchronous non-blocking enqueue,
// background (microtask) execution through an injected local runtime, the honest awaiting-runtime
// hold when no runtime is attached (the Wave-3 seam), per-job failure isolation, FIFO order, and
// bounded backpressure that refuses loudly instead of losing silently.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  FastPathQueue,
  FASTPATH_LANE,
  FASTPATH_LANES,
  FASTPATH_JOB_STATUS,
  DEFAULT_MAX_QUEUED,
} from '../src/fastpath-queue.mjs';

const CLAIM = Object.freeze({ id: 'c-fast-1', kind: 'mathematical', claim_type: 'computational' });

// =====================================================================================
// 0. The pinned lane vocabulary.
// =====================================================================================

test('FASTPATH_LANE pins the two local lanes: exact-arithmetic and empirical-sandbox', () => {
  assert.equal(FASTPATH_LANE.EXACT_ARITHMETIC, 'exact-arithmetic');
  assert.equal(FASTPATH_LANE.EMPIRICAL_SANDBOX, 'empirical-sandbox');
  assert.deepEqual(FASTPATH_LANES, ['exact-arithmetic', 'empirical-sandbox']);
  assert.ok(Object.isFrozen(FASTPATH_LANE));
  assert.equal(DEFAULT_MAX_QUEUED, 4096);
});

// =====================================================================================
// 1. Non-blocking enqueue — synchronous ticket, NO runtime work inside the call.
// =====================================================================================

test('enqueue is synchronous and returns a frozen QUEUED job ticket', () => {
  const q = new FastPathQueue();
  const job = q.enqueue(CLAIM, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  assert.ok(Object.isFrozen(job));
  assert.equal(job.claim_id, 'c-fast-1');
  assert.equal(job.claim, CLAIM);
  assert.equal(job.lane, FASTPATH_LANE.EXACT_ARITHMETIC);
  assert.equal(job.status, FASTPATH_JOB_STATUS.QUEUED);
  assert.equal(q.size, 1);
});

test('with a runtime attached, NO execution happens inside enqueue — it runs on the microtask queue', async () => {
  const ran = [];
  const q = new FastPathQueue({ runtime: (job) => ran.push(job.claim_id) });
  q.enqueue(CLAIM, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  // The enqueue call returned and NOTHING has executed yet — the enqueuer never waited.
  assert.equal(ran.length, 0, 'no runtime work may happen inside enqueue()');
  assert.equal(q.pending, true);
  await q.settle();
  assert.equal(ran.length, 1);
  assert.deepEqual(ran, ['c-fast-1']);
  assert.equal(q.pending, false);
  assert.equal(q.size, 0);
});

// =====================================================================================
// 2. The honest awaiting-runtime hold — the Wave-3 seam, never a fake execution.
// =====================================================================================

test('without a runtime, jobs are HELD and drain() reports awaiting_runtime honestly (nothing lost, nothing faked)', async () => {
  const q = new FastPathQueue();
  q.enqueue(CLAIM, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  q.enqueue({ id: 'c-fast-2' }, { lane: FASTPATH_LANE.EMPIRICAL_SANDBOX });
  const summary = await q.drain();
  assert.equal(summary.drained, 0);
  assert.equal(summary.awaiting_runtime, 2);
  assert.match(summary.reason, /Wave-3/);
  // The jobs are still queued — held, not dropped.
  assert.equal(q.size, 2);
  assert.equal(q.settled.length, 0);
  assert.equal(q.jobs.every((j) => j.status === FASTPATH_JOB_STATUS.QUEUED), true);
});

test('an explicit runtime passed to drain() executes the held jobs (Wave 3 attaches here)', async () => {
  const q = new FastPathQueue();
  q.enqueue(CLAIM, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  const summary = await q.drain({ runtime: async (job) => ({ ok: true, lane: job.lane }) });
  assert.equal(summary.drained, 1);
  assert.equal(summary.settled, 1);
  assert.equal(q.size, 0);
  assert.equal(q.settled.length, 1);
  assert.deepEqual(q.settled[0].result, { ok: true, lane: 'exact-arithmetic' });
  assert.equal(q.settled[0].job.status, FASTPATH_JOB_STATUS.SETTLED);
});

// =====================================================================================
// 3. FIFO order + onResult delivery.
// =====================================================================================

test('jobs execute FIFO and each settlement is delivered to onResult', async () => {
  const order = [];
  const q = new FastPathQueue({
    runtime: (job) => job.claim_id,
    onResult: (s) => order.push(s.result),
  });
  q.enqueue({ id: 'a' }, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  q.enqueue({ id: 'b' }, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  q.enqueue({ id: 'c' }, { lane: FASTPATH_LANE.EMPIRICAL_SANDBOX });
  await q.settle();
  assert.deepEqual(order, ['a', 'b', 'c']);
});

// =====================================================================================
// 4. Failure isolation — a throwing runtime fails ONE job, audited, and draining continues.
// =====================================================================================

test('a throwing runtime never propagates: the job FAILS onto the audit and the next job still settles', async () => {
  const q = new FastPathQueue({
    runtime: (job) => {
      if (job.claim_id === 'boom') throw new Error('runtime blew up');
      return 'ok';
    },
  });
  q.enqueue({ id: 'boom' }, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  q.enqueue({ id: 'fine' }, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  await q.settle();
  assert.equal(q.failures.length, 1);
  assert.equal(q.failures[0].job.claim_id, 'boom');
  assert.equal(q.failures[0].stage, 'runtime');
  assert.match(q.failures[0].error.message, /blew up/);
  assert.equal(q.settled.length, 1);
  assert.equal(q.settled[0].job.claim_id, 'fine');
});

test('a throwing onResult is isolated onto the failure audit — the settlement itself still lands', async () => {
  const q = new FastPathQueue({
    runtime: () => 'ok',
    onResult: () => {
      throw new Error('listener blew up');
    },
  });
  q.enqueue(CLAIM, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  await q.settle();
  assert.equal(q.settled.length, 1);
  assert.equal(q.failures.length, 1);
  assert.equal(q.failures[0].stage, 'on-result');
});

// =====================================================================================
// 5. Bounded backpressure — refuse loudly, never lose silently.
// =====================================================================================

test('enqueue past maxQueued throws (bounded backpressure)', () => {
  const q = new FastPathQueue({ maxQueued: 2 });
  q.enqueue({ id: '1' }, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  q.enqueue({ id: '2' }, { lane: FASTPATH_LANE.EXACT_ARITHMETIC });
  assert.throws(
    () => q.enqueue({ id: '3' }, { lane: FASTPATH_LANE.EXACT_ARITHMETIC }),
    /fast-path queue is full .*maxQueued=2/,
  );
  assert.equal(q.size, 2, 'the refused job was never queued');
});

// =====================================================================================
// 6. Validation.
// =====================================================================================

test('bad lanes, claims, runtimes, and bounds are rejected with clear errors', () => {
  assert.throws(() => new FastPathQueue({ runtime: 'not-a-fn' }), /runtime .* must be a function/);
  assert.throws(() => new FastPathQueue({ onResult: 42 }), /onResult .* must be a function/);
  assert.throws(() => new FastPathQueue({ maxQueued: 0 }), /maxQueued must be a positive integer/);
  const q = new FastPathQueue();
  assert.throws(() => q.enqueue(null, { lane: FASTPATH_LANE.EXACT_ARITHMETIC }), /claim must be an object/);
  assert.throws(() => q.enqueue(CLAIM, { lane: 'lean-kernel' }), /lane must be one of/);
  assert.throws(() => q.enqueue(CLAIM, {}), /lane must be one of/);
});
