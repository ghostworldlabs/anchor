// Overhaul Wave 2 — Crucible/Foreman Pipeline Integration: the PIPELINE ROUTER.
//
// Exercises the REAL Wave-2 source (src/pipeline-router.mjs), proving the wave's done-when:
// "All certification tasks bypass the legacy queue and are exclusively routed to the fast-path
// queue or Foreman background pipeline based on complexity." — and its Given/When/Then: an
// intercepted claim on the event bus is passed to the fast-path queue or the Foreman background
// worker, with legacy CertifierQueue logic completely bypassed.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { ClaimEventBus, CLAIM_EVENT_TOPIC } from '../src/claim-event-bus.mjs';
import { FASTPATH_LANE } from '../src/fastpath-queue.mjs';
import { FOREMAN_JOB_STATUS } from '../src/foreman-worker.mjs';
import { CERTIFIER_QUEUE_DISMANTLED } from '../src/certifier-queue.mjs';
import {
  PipelineRouter,
  PIPELINE,
  PIPELINES,
  PIPELINE_TOPIC,
  PIPELINE_STREAM_FIXTURE,
  classifyComplexity,
  runPipelineFixture,
} from '../src/pipeline-router.mjs';

/** A minimal Wave-1-shaped interception payload. */
function interception(overrides = {}) {
  return Object.freeze({
    id: 'w1::intercept-0',
    source: 'stream-interceptor',
    kind: 'mathematical',
    claim_type: 'proof-bearing',
    statement: 'Every even integer greater than 2 is the sum of two primes.',
    span: Object.freeze({ start: 0, end: 59 }),
    confidence: 0.9,
    reason: 'test payload',
    ...overrides,
  });
}

// =====================================================================================
// 0. The pinned pipeline + topic vocabulary.
// =====================================================================================

test('PIPELINE pins the two — and only two — pipeline arms', () => {
  assert.equal(PIPELINE.FAST_PATH, 'fast-path');
  assert.equal(PIPELINE.FOREMAN, 'foreman');
  assert.deepEqual(PIPELINES, ['fast-path', 'foreman']);
  assert.ok(Object.isFrozen(PIPELINE));
});

test('PIPELINE_TOPIC pins the Wave-2 bus topics (the Wave-1 vocabulary stays untouched)', () => {
  assert.equal(PIPELINE_TOPIC.ROUTED, 'claim:routed');
  assert.equal(PIPELINE_TOPIC.FASTPATH_SETTLED, 'claim:fastpath-settled');
  assert.equal(PIPELINE_TOPIC.FOREMAN_SETTLED, 'claim:foreman-settled');
  assert.ok(Object.isFrozen(PIPELINE_TOPIC));
});

// =====================================================================================
// 1. THE COMPLEXITY RULE — deterministic pipeline selection over (kind, claim_type).
// =====================================================================================

test('classifyComplexity: empirical -> fast path / empirical-sandbox (never Lean/z3)', () => {
  const d = classifyComplexity({ kind: 'empirical', claim_type: 'empirical' });
  assert.equal(d.pipeline, PIPELINE.FAST_PATH);
  assert.equal(d.lane, FASTPATH_LANE.EMPIRICAL_SANDBOX);
  assert.equal(d.quarantine, false);
  assert.match(d.reason, /never Lean\/z3/);
});

test('classifyComplexity: mathematical computational -> fast path / exact-arithmetic', () => {
  const d = classifyComplexity({ kind: 'mathematical', claim_type: 'computational' });
  assert.equal(d.pipeline, PIPELINE.FAST_PATH);
  assert.equal(d.lane, FASTPATH_LANE.EXACT_ARITHMETIC);
});

test('classifyComplexity: mathematical proof-bearing and conceptual -> Foreman (multi-step agentic)', () => {
  for (const claim_type of ['proof-bearing', 'conceptual']) {
    const d = classifyComplexity({ kind: 'mathematical', claim_type });
    assert.equal(d.pipeline, PIPELINE.FOREMAN, claim_type);
    assert.equal(d.lane, null);
  }
});

test('classifyComplexity: an unrecognized mathematical subtype fails TOWARD the stronger multi-step arm', () => {
  const d = classifyComplexity({ kind: 'mathematical', claim_type: 'exotic' });
  assert.equal(d.pipeline, PIPELINE.FOREMAN);
  assert.match(d.reason, /stronger multi-step arm/);
});

test('classifyComplexity: an unrecognized kind is quarantined — audited, never guessed into a pipeline', () => {
  for (const payload of [{ kind: 'astrological' }, {}, null, 'garbage']) {
    const d = classifyComplexity(payload);
    assert.equal(d.quarantine, true);
    assert.equal(d.pipeline, null);
  }
});

// =====================================================================================
// 2. THE GIVEN/WHEN/THEN — an intercepted claim on the bus lands on exactly one pipeline,
//    with the legacy CertifierQueue completely bypassed.
// =====================================================================================

test('G/W/T: a proof-bearing interception on the bus is passed to the Foreman background worker, legacy queue bypassed', async () => {
  const bus = new ClaimEventBus();
  const router = new PipelineRouter({ bus });
  router.attach();
  const routedEvents = [];
  bus.subscribe(PIPELINE_TOPIC.ROUTED, (e) => routedEvents.push(e));

  // GIVEN an intercepted claim residing on the event bus...
  const payload = interception();
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, payload);
  // WHEN the routing layer processes the event...
  await router.settle();

  // THEN the claim was passed to the Foreman background worker...
  assert.equal(router.foreman.jobs.length, 1);
  assert.equal(router.foreman.jobs[0].claim_id, payload.id);
  assert.equal(router.foreman.jobs[0].status, FOREMAN_JOB_STATUS.DONE);
  assert.equal(router.fastPath.jobs.length, 0);
  // ...and the routed record — published on the bus — carries the per-claim legacy bypass stamp.
  assert.equal(routedEvents.length, 1);
  const record = routedEvents[0].payload;
  assert.equal(record.claim_id, payload.id);
  assert.equal(record.pipeline, PIPELINE.FOREMAN);
  assert.equal(record.legacy_queue_bypassed, true);
  assert.equal(record.legacy_queue.dismantled, true);
  assert.equal(record.legacy_queue.legacy, CERTIFIER_QUEUE_DISMANTLED.legacy);
});

test('G/W/T: computational and empirical interceptions are passed to the fast-path queue on their lanes', async () => {
  const bus = new ClaimEventBus();
  const router = new PipelineRouter({ bus });
  router.attach();

  bus.publish(
    CLAIM_EVENT_TOPIC.INTERCEPTED,
    interception({ id: 'w1::intercept-1', claim_type: 'computational', statement: '2 + 2 = 4.' }),
  );
  bus.publish(
    CLAIM_EVENT_TOPIC.INTERCEPTED,
    interception({ id: 'w1::intercept-2', kind: 'empirical', claim_type: 'empirical' }),
  );
  await router.settle();

  assert.equal(router.foreman.jobs.length, 0);
  const jobs = router.fastPath.jobs;
  assert.equal(jobs.length, 2);
  assert.equal(jobs[0].claim_id, 'w1::intercept-1');
  assert.equal(jobs[0].lane, FASTPATH_LANE.EXACT_ARITHMETIC);
  assert.equal(jobs[1].claim_id, 'w1::intercept-2');
  assert.equal(jobs[1].lane, FASTPATH_LANE.EMPIRICAL_SANDBOX);
  assert.equal(router.routed.every((r) => r.legacy_queue_bypassed === true), true);
});

// =====================================================================================
// 3. THE DONE-WHEN, end to end — the full Wave-1 -> Wave-2 fixture flow: stream -> semantic
//    interception -> bus -> routing BY COMPLEXITY into both arms, legacy queue bypassed on
//    every record, results re-published for the Wave-3/4 listeners.
// =====================================================================================

test('done-when: every fixture certification task is routed EXCLUSIVELY to the fast-path queue or the Foreman pipeline', async () => {
  const run = await runPipelineFixture();
  assert.equal(run.routedEverything, true, 'every intercepted claim was routed; none quarantined, none errored');
  assert.equal(run.exclusivelyPipelines, true, 'no claim was routed anywhere but the two pipeline arms');
  assert.equal(run.legacyBypassed, true, 'every routed record carries the legacy-bypass stamp');

  // Split by complexity: the proof-bearing claim went to Foreman; the computational + empirical
  // claims went to the fast path on their lanes.
  assert.equal(run.foremanClaims.length, 1);
  assert.equal(run.foremanClaims[0].claim_type, 'proof-bearing');
  assert.equal(run.fastPathClaims.length, 2);
  assert.deepEqual(
    run.fastPathClaims.map((r) => r.lane).sort(),
    [FASTPATH_LANE.EMPIRICAL_SANDBOX, FASTPATH_LANE.EXACT_ARITHMETIC].sort(),
  );

  // The routed records were published on the bus (claim:routed) for downstream listeners.
  assert.equal(run.routedEvents.length, 3);
  // Pipeline results flowed back onto the bus: 2 fast-path settlements (stub runtime, honest
  // ABSTAIN — Wave 3 supplies the real sandbox) + 1 Foreman job (deferred plan, honest ABSTAIN).
  const fastpathSettled = run.settledEvents.filter((e) => e.topic === PIPELINE_TOPIC.FASTPATH_SETTLED);
  const foremanSettled = run.settledEvents.filter((e) => e.topic === PIPELINE_TOPIC.FOREMAN_SETTLED);
  assert.equal(fastpathSettled.length, 2);
  assert.equal(fastpathSettled.every((e) => e.payload.result.verdict === 'ABSTAIN'), true);
  assert.equal(foremanSettled.length, 1);
  assert.equal(foremanSettled[0].payload.status, FOREMAN_JOB_STATUS.DONE);
  assert.equal(
    foremanSettled[0].payload.steps.every((s) => s.result.verdict === 'ABSTAIN'),
    true,
    'the deferred Foreman plan never fakes a verdict',
  );
});

test('the fixture stream is the Wave-1 shape: claims split across chunk boundaries', () => {
  assert.ok(Object.isFrozen(PIPELINE_STREAM_FIXTURE));
  assert.ok(PIPELINE_STREAM_FIXTURE.length >= 3, 'multiple chunks so sentences span boundaries');
});

// =====================================================================================
// 4. No silent loss — quarantine, routing errors, and the double-attach guard.
// =====================================================================================

test('an unrecognizable payload on the interception topic is QUARANTINED (audited), never placed or dropped', async () => {
  const bus = new ClaimEventBus();
  const router = new PipelineRouter({ bus });
  router.attach();
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, { id: 'weird', kind: 'astrological' });
  await router.settle();
  assert.equal(router.quarantined.length, 1);
  assert.match(router.quarantined[0].reason, /quarantined/);
  assert.equal(router.routed.length, 0);
  assert.equal(router.fastPath.jobs.length, 0);
  assert.equal(router.foreman.jobs.length, 0);
});

test('a placement refusal (bounded backpressure) lands on the router error audit — never thrown into the bus, never silent', async () => {
  const bus = new ClaimEventBus();
  const { FastPathQueue } = await import('../src/fastpath-queue.mjs');
  const tiny = new FastPathQueue({ maxQueued: 1 });
  const router = new PipelineRouter({ bus, fastPath: tiny });
  router.attach();
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, interception({ id: 'e-1', kind: 'empirical', claim_type: 'empirical' }));
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, interception({ id: 'e-2', kind: 'empirical', claim_type: 'empirical' }));
  await router.settle();
  assert.equal(router.routed.length, 1);
  assert.equal(router.errors.length, 1);
  assert.match(router.errors[0].error.message, /queue is full/);
  assert.equal(bus.errors.length, 0, 'the refusal never leaked into the bus delivery');
});

test('attach() twice is a wiring bug (double-routing guard); detach() stops routing and is idempotent', async () => {
  const bus = new ClaimEventBus();
  const router = new PipelineRouter({ bus });
  router.attach();
  assert.equal(router.attached, true);
  assert.throws(() => router.attach(), /already attached/);

  router.detach();
  router.detach(); // idempotent
  assert.equal(router.attached, false);
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, interception());
  await bus.settle();
  assert.equal(router.routed.length, 0, 'a detached router routes nothing');
});

test('router validation: a bus is required', () => {
  assert.throws(() => new PipelineRouter(), /bus must be a ClaimEventBus-like/);
  assert.throws(() => new PipelineRouter({ bus: {} }), /bus must be a ClaimEventBus-like/);
});
