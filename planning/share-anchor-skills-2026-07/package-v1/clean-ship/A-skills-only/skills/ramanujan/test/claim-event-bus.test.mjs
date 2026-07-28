// Overhaul Wave 1 — Semantic Interception & Event Bus Dispatch: the CLAIM EVENT BUS.
//
// Exercises the REAL Wave-1 source (src/claim-event-bus.mjs), proving the dispatch arm of the
// done-when: publish is SYNCHRONOUS AND NON-BLOCKING (no subscriber runs inside the publish call),
// delivery is asynchronous (microtask), a throwing subscriber never reaches the publisher and never
// starves the other subscribers, and every publish — subscribed or not — lands on the audit history.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { ClaimEventBus, CLAIM_EVENT_TOPIC, CLAIM_EVENT_TOPICS } from '../src/claim-event-bus.mjs';

// =====================================================================================
// 0. The pinned topic vocabulary.
// =====================================================================================

test('CLAIM_EVENT_TOPIC pins the Wave-1 interception topic', () => {
  assert.equal(CLAIM_EVENT_TOPIC.INTERCEPTED, 'claim:intercepted');
  assert.deepEqual(CLAIM_EVENT_TOPICS, ['claim:intercepted']);
  assert.ok(Object.isFrozen(CLAIM_EVENT_TOPIC));
});

// =====================================================================================
// 1. THE NON-BLOCKING CONTRACT — synchronous publish, asynchronous (microtask) delivery.
// =====================================================================================

test('done-when (dispatch arm): publish returns synchronously; NO subscriber runs inside the publish call', async () => {
  const bus = new ClaimEventBus();
  const received = [];
  bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, (e) => received.push(e));

  const event = bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, { id: 'c-1' });

  // The envelope came back synchronously...
  assert.equal(event.topic, CLAIM_EVENT_TOPIC.INTERCEPTED);
  assert.deepEqual(event.payload, { id: 'c-1' });
  // ...and NOTHING was delivered yet — the publisher never waited on a subscriber.
  assert.equal(received.length, 0, 'no delivery may happen inside publish()');
  assert.equal(bus.pending, true);

  await bus.settle();
  assert.equal(received.length, 1);
  assert.equal(received[0], event);
  assert.equal(bus.pending, false);
});

test('envelopes are deep-frozen and seq is monotonic', async () => {
  const bus = new ClaimEventBus();
  const a = bus.publish('t', { nested: { x: 1 } });
  const b = bus.publish('t', { y: 2 });
  assert.ok(Object.isFrozen(a));
  assert.ok(Object.isFrozen(a.payload));
  assert.ok(Object.isFrozen(a.payload.nested));
  assert.ok(b.seq > a.seq);
  await bus.settle();
});

// =====================================================================================
// 2. Error isolation — a throwing subscriber never reaches the publisher, never starves the rest.
// =====================================================================================

test('a throwing subscriber is isolated: publisher never throws, other subscribers still delivered, error audited', async () => {
  const bus = new ClaimEventBus();
  const survived = [];
  bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, () => {
    throw new Error('subscriber blew up');
  });
  bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, (e) => survived.push(e));

  // publish() must NOT throw even though a subscriber will.
  const event = bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, { id: 'c-err' });
  await bus.settle();

  assert.equal(survived.length, 1, 'the healthy subscriber still received the event');
  assert.equal(bus.errors.length, 1);
  assert.equal(bus.errors[0].event, event);
  assert.match(bus.errors[0].error.message, /blew up/);
});

// =====================================================================================
// 3. Audit history — every publish is recorded, subscribed or not; nothing is silently lost.
// =====================================================================================

test('a publish with ZERO subscribers is still audited (subscriber_count 0), never silently lost', async () => {
  const bus = new ClaimEventBus();
  const event = bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, { id: 'orphan' });
  await bus.settle();
  assert.equal(bus.history.length, 1);
  assert.equal(bus.history[0].event, event);
  assert.equal(bus.history[0].subscriber_count, 0);
});

test('history records subscriber_count at publish time', async () => {
  const bus = new ClaimEventBus();
  bus.subscribe('t', () => {});
  bus.subscribe('t', () => {});
  bus.publish('t', 1);
  await bus.settle();
  assert.equal(bus.history[0].subscriber_count, 2);
});

// =====================================================================================
// 4. Subscription semantics — snapshot at publish, unsubscribe, topic isolation.
// =====================================================================================

test('a subscriber added AFTER publish never sees the earlier event (no replay)', async () => {
  const bus = new ClaimEventBus();
  bus.publish('t', 'early');
  const late = [];
  bus.subscribe('t', (e) => late.push(e));
  await bus.settle();
  assert.equal(late.length, 0);
  bus.publish('t', 'now');
  await bus.settle();
  assert.equal(late.length, 1);
  assert.equal(late[0].payload, 'now');
});

test('unsubscribe stops future deliveries', async () => {
  const bus = new ClaimEventBus();
  const seen = [];
  const off = bus.subscribe('t', (e) => seen.push(e));
  bus.publish('t', 1);
  await bus.settle();
  off();
  assert.equal(bus.subscriberCount('t'), 0);
  bus.publish('t', 2);
  await bus.settle();
  assert.equal(seen.length, 1);
});

test('topics are isolated: a subscriber on one topic never receives another topic', async () => {
  const bus = new ClaimEventBus();
  const a = [];
  const b = [];
  bus.subscribe('topic:a', (e) => a.push(e));
  bus.subscribe('topic:b', (e) => b.push(e));
  bus.publish('topic:a', 'A');
  await bus.settle();
  assert.equal(a.length, 1);
  assert.equal(b.length, 0);
});

// =====================================================================================
// 5. settle() drains cascades — a handler that re-publishes keeps the bus pending until done.
// =====================================================================================

test('settle() waits for deliveries scheduled BY handlers (a re-publishing cascade fully drains)', async () => {
  const bus = new ClaimEventBus();
  const order = [];
  bus.subscribe('first', (e) => {
    order.push(e.topic);
    bus.publish('second', 'chained');
  });
  bus.subscribe('second', (e) => order.push(e.topic));
  bus.publish('first', 'start');
  await bus.settle();
  assert.deepEqual(order, ['first', 'second']);
});

test('settle() on an idle bus resolves immediately', async () => {
  const bus = new ClaimEventBus();
  await bus.settle();
  assert.equal(bus.pending, false);
});

// =====================================================================================
// 6. Validation.
// =====================================================================================

test('bad topics and handlers are rejected with clear errors', () => {
  const bus = new ClaimEventBus();
  assert.throws(() => bus.publish('', 1), /topic must be a non-empty string/);
  assert.throws(() => bus.publish(null, 1), /topic must be a non-empty string/);
  assert.throws(() => bus.subscribe('t', 'not-a-function'), /handler must be a function/);
  assert.throws(() => bus.subscriberCount(42), /topic must be a non-empty string/);
});
