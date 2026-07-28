// Overhaul Wave 2 — Crucible/Foreman Pipeline Integration: the DISMANTLED CertifierQueue.
//
// Exercises the REAL Wave-2 source (src/certifier-queue.mjs), proving the dismantling is
// STRUCTURAL: no CertifierQueue instance can exist, every legacy queue verb hard-faults with the
// typed dismantled error, and the dismantling marker (the per-claim bypass stamp's provenance)
// points at the replacement Crucible/Foreman pipeline surfaces.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  CertifierQueue,
  CertifierQueueDismantledError,
  CERTIFIER_QUEUE_DISMANTLED,
  CERTIFIER_QUEUE_REPLACEMENT,
} from '../src/certifier-queue.mjs';

// =====================================================================================
// 1. Construction is unreachable — no instance of the legacy queue can ever exist.
// =====================================================================================

test('done-when (dismantling arm): constructing the legacy CertifierQueue hard-faults with the typed dismantled error', () => {
  assert.throws(
    () => new CertifierQueue(),
    (e) =>
      e instanceof CertifierQueueDismantledError &&
      e.dismantled === true &&
      e.operation === 'constructor' &&
      /DISMANTLED/.test(e.message) &&
      /Crucible\/Foreman pipeline/.test(e.message),
  );
});

test('every legacy queue verb hard-faults — a residual call path can never silently queue a task', () => {
  for (const verb of ['enqueue', 'dequeue', 'push', 'drain', 'flush']) {
    assert.throws(
      () => CertifierQueue[verb]({ id: 'legacy-task' }),
      (e) => e instanceof CertifierQueueDismantledError && e.operation === verb,
      `CertifierQueue.${verb}() must fault`,
    );
  }
});

test('the fault points the residual caller at the replacement pipeline surfaces', () => {
  try {
    CertifierQueue.enqueue();
    assert.fail('enqueue must throw');
  } catch (e) {
    assert.match(e.message, /PipelineRouter/);
    assert.match(e.message, /FastPathQueue/);
    assert.match(e.message, /ForemanWorker/);
    assert.equal(e.replaced_by, CERTIFIER_QUEUE_REPLACEMENT);
  }
});

// =====================================================================================
// 2. The dismantling marker — the provenance stamped into every routed record.
// =====================================================================================

test('CERTIFIER_QUEUE_DISMANTLED is a frozen marker naming the legacy queue, the wave, and the replacement', () => {
  assert.ok(Object.isFrozen(CERTIFIER_QUEUE_DISMANTLED));
  assert.equal(CERTIFIER_QUEUE_DISMANTLED.legacy, 'CertifierQueue');
  assert.equal(CERTIFIER_QUEUE_DISMANTLED.dismantled, true);
  assert.match(CERTIFIER_QUEUE_DISMANTLED.wave, /Wave 2/);
  assert.equal(CERTIFIER_QUEUE_DISMANTLED.replaced_by, CERTIFIER_QUEUE_REPLACEMENT);
});

test('the replacement map is frozen and names all three Wave-2 pipeline surfaces', () => {
  assert.ok(Object.isFrozen(CERTIFIER_QUEUE_REPLACEMENT));
  assert.match(CERTIFIER_QUEUE_REPLACEMENT.router, /pipeline-router/);
  assert.match(CERTIFIER_QUEUE_REPLACEMENT.fast_path, /fastpath-queue/);
  assert.match(CERTIFIER_QUEUE_REPLACEMENT.foreman, /foreman-worker/);
});

test('the dismantled error is a real Error with a stable name (distinguishable in any audit)', () => {
  const e = new CertifierQueueDismantledError('enqueue');
  assert.ok(e instanceof Error);
  assert.equal(e.name, 'CertifierQueueDismantledError');
  assert.equal(e.operation, 'enqueue');
});
