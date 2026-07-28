// Overhaul Wave 1 — Semantic Interception & Event Bus Dispatch: the STREAM INTERCEPTOR.
//
// Exercises the REAL Wave-1 source (src/stream-interceptor.mjs) wired to the REAL Wave-1 event bus
// and semantic classifier, proving the wave's done-when END-TO-END:
//
//   Given a stream of incoming text containing mathematical or empirical claims, when the text is
//   processed, then text renders IMMEDIATELY without wait-states while claims are ASYNCHRONOUSLY
//   intercepted and dispatched to the event bus.
//
// Proven at three depths: (1) every chunk reaches the render sink synchronously inside write(),
// before ANY classification has run; (2) after settle(), every claim — including claims split
// across chunk boundaries — was intercepted exactly once and delivered on the bus; (3) the logical
// clock shows every classification ran strictly after the render it derives from (nonBlocking).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { StreamInterceptor, STREAM_FIXTURE, runFixtureStream } from '../src/stream-interceptor.mjs';
import { ClaimEventBus, CLAIM_EVENT_TOPIC } from '../src/claim-event-bus.mjs';
import { CLAIM_KIND } from '../src/semantic-classifier.mjs';

// =====================================================================================
// 1. THE DONE-WHEN — the wave's Given/When/Then, end-to-end on the real spine.
// =====================================================================================

test('done-when GWT: text renders immediately without wait-states while claims are asynchronously intercepted and dispatched to the event bus', async () => {
  const bus = new ClaimEventBus();
  const delivered = [];
  bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, (e) => delivered.push(e));
  const renderLog = [];
  const stream = new StreamInterceptor({ bus, renderSink: (chunk) => renderLog.push(chunk) });

  // GIVEN a stream of incoming text containing a mathematical and an empirical claim...
  // WHEN each chunk is written...
  let expected = '';
  for (const chunk of STREAM_FIXTURE) {
    stream.write(chunk);
    expected += chunk;
    // THEN the chunk is rendered INSIDE the write call — no wait-state, ever.
    assert.equal(renderLog.join(''), expected, 'every chunk must render synchronously inside write()');
  }

  // ...and NOTHING has been classified or dispatched yet (interception is strictly asynchronous).
  assert.equal(stream.classified.length, 0, 'no classification may run on the write path');
  assert.equal(stream.interceptions.length, 0);
  assert.equal(delivered.length, 0);

  stream.end();
  await stream.settle();

  // THEN the claims were asynchronously intercepted and dispatched to the event bus.
  assert.equal(stream.interceptions.length, 2, 'exactly the two claims are intercepted');
  assert.equal(delivered.length, 2, 'both interceptions were dispatched to the event bus');
  const [math, empirical] = stream.interceptions;
  assert.equal(math.kind, CLAIM_KIND.MATHEMATICAL);
  assert.equal(math.claim_type, 'proof-bearing');
  assert.equal(empirical.kind, CLAIM_KIND.EMPIRICAL);
  assert.equal(empirical.claim_type, 'empirical');
  assert.deepEqual(delivered.map((e) => e.payload), [...stream.interceptions]);

  // ...and the logical clock proves rendering never waited on interception.
  assert.equal(stream.nonBlocking, true, 'every classification must run strictly after its render');
  assert.equal(stream.renderedText, STREAM_FIXTURE.join(''));
});

test('runFixtureStream: the packaged end-to-end fixture run satisfies every done-when invariant', async () => {
  const run = await runFixtureStream();
  assert.equal(run.renderedEverything, true);
  assert.equal(run.nonBlocking, true);
  assert.equal(run.dispatchedToBus, true);
  assert.equal(run.delivered.length, 2);
});

// =====================================================================================
// 2. Chunk-boundary safety — a claim split across chunks intercepts exactly once, span intact.
// =====================================================================================

test('a claim split across chunk boundaries is intercepted exactly once, with a full-stream span that reconstructs it', async () => {
  const stream = new StreamInterceptor({});
  stream.write('The sum of the first 100 ');
  stream.write('positive integers ');
  stream.write('equals 5050. ');
  stream.end();
  await stream.settle();

  assert.equal(stream.interceptions.length, 1);
  const claim = stream.interceptions[0];
  assert.equal(claim.statement, 'The sum of the first 100 positive integers equals 5050.');
  const full = stream.renderedText;
  assert.equal(full.slice(claim.span.start, claim.span.end), claim.statement);
});

test('a bare trailing "." is held (it may be a decimal still streaming): "3." + "14" never splits', async () => {
  const stream = new StreamInterceptor({});
  stream.write('The value 3.');
  stream.write('14 is close to 22/7. Done');
  stream.end();
  await stream.settle();

  const statements = stream.classified.map((c) => c.statement);
  assert.deepEqual(statements, ['The value 3.14 is close to 22/7.', 'Done']);
});

test('end() flushes a trailing unterminated sentence to classification', async () => {
  const stream = new StreamInterceptor({});
  stream.write('The harmonic series diverges');
  assert.equal(stream.interceptions.length, 0);
  stream.end();
  await stream.settle();
  assert.equal(stream.interceptions.length, 1);
  assert.equal(stream.interceptions[0].kind, CLAIM_KIND.MATHEMATICAL);
});

// =====================================================================================
// 3. Claim-free streams — everything renders, nothing dispatches.
// =====================================================================================

test('claim-free prose renders in full and dispatches NOTHING to the bus (audit still records the classifications)', async () => {
  const bus = new ClaimEventBus();
  const stream = new StreamInterceptor({ bus });
  stream.write('Hello there. ');
  stream.write('See you at lunch tomorrow. ');
  stream.end();
  await stream.settle();

  assert.equal(stream.renderedText, 'Hello there. See you at lunch tomorrow. ');
  assert.equal(stream.interceptions.length, 0);
  assert.equal(bus.history.length, 0, 'nothing may be published for claim-free prose');
  assert.ok(stream.classified.length >= 2, 'the audit still shows every sentence was classified');
  assert.ok(stream.classified.every((c) => c.kind === CLAIM_KIND.NONE));
});

// =====================================================================================
// 4. Error isolation — neither path can sever the other.
// =====================================================================================

test('a throwing render sink never severs interception (error audited, claims still dispatched)', async () => {
  const bus = new ClaimEventBus();
  const stream = new StreamInterceptor({
    bus,
    renderSink: () => {
      throw new Error('render sink exploded');
    },
  });
  stream.write('2 + 2 = 4. ');
  stream.end();
  await stream.settle();

  assert.equal(stream.interceptions.length, 1, 'interception must survive a broken render sink');
  assert.ok(stream.errors.some((e) => e.stage === 'render'));
});

test('a throwing classifier never severs rendering (error audited, stream settles cleanly)', async () => {
  const renderLog = [];
  const stream = new StreamInterceptor({
    renderSink: (c) => renderLog.push(c),
    classify: () => {
      throw new Error('classifier exploded');
    },
  });
  stream.write('2 + 2 = 4. ');
  stream.end();
  await stream.settle();

  assert.equal(renderLog.join(''), '2 + 2 = 4. ');
  assert.equal(stream.interceptions.length, 0);
  assert.ok(stream.errors.some((e) => e.stage === 'classify'));
});

test('a throwing bus subscriber never reaches the stream (isolated on the bus audit)', async () => {
  const bus = new ClaimEventBus();
  const survived = [];
  bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, () => {
    throw new Error('subscriber exploded');
  });
  bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, (e) => survived.push(e));
  const stream = new StreamInterceptor({ bus });
  stream.write('2 + 2 = 4. ');
  stream.end();
  await stream.settle();

  assert.equal(survived.length, 1);
  assert.equal(bus.errors.length, 1);
  assert.equal(stream.errors.length, 0, 'the stream itself saw no error');
});

// =====================================================================================
// 5. Lifecycle + validation.
// =====================================================================================

test('write() after end() is rejected; end() is idempotent', async () => {
  const stream = new StreamInterceptor({});
  stream.write('Hello. ');
  stream.end();
  stream.end();
  assert.throws(() => stream.write('more'), /the stream has ended/);
  await stream.settle();
});

test('constructor and write() validate their inputs with clear errors', () => {
  assert.throws(() => new StreamInterceptor({ bus: {} }), /ClaimEventBus-like/);
  assert.throws(() => new StreamInterceptor({ renderSink: 'nope' }), /renderSink/);
  assert.throws(() => new StreamInterceptor({ classify: 'nope' }), /classify must be a function/);
  const stream = new StreamInterceptor({});
  assert.throws(() => stream.write(42), /chunk must be a string/);
});

test('records are frozen: renders, classifications, and interceptions are immutable audit facts', async () => {
  const stream = new StreamInterceptor({});
  const render = stream.write('2 + 2 = 4. ');
  assert.ok(Object.isFrozen(render));
  stream.end();
  await stream.settle();
  assert.ok(stream.classified.every((c) => Object.isFrozen(c)));
  assert.ok(stream.interceptions.every((c) => Object.isFrozen(c)));
  assert.ok(Object.isFrozen(STREAM_FIXTURE));
});
