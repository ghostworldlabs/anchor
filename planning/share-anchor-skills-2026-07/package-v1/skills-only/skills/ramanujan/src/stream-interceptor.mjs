// Overhaul Wave 1 — Semantic Interception & Event Bus Dispatch: the STREAM INTERCEPTOR.
//
// The non-blocking text streaming pipeline that SEVERS the UI rendering path from verification.
//
// THE DEFINING INVARIANT (the done-when). "Text renders immediately without wait-states while
// claims are asynchronously intercepted and dispatched to the event bus." Concretely:
//
//   RENDER IS SYNCHRONOUS.  `write(chunk)` hands the chunk to the render sink INSIDE the call —
//                           no await, no classification, no bus work on the write path. The chunk
//                           is on screen before write() returns.
//   INTERCEPTION IS ASYNC.  Completed sentences are classified on the MICROTASK queue (after the
//                           write returns) by the Wave-1 semantic classifier; intercepted claims
//                           are published to the Wave-1 event bus, whose delivery is itself
//                           deferred. Verification (Waves 2-3) subscribes there — never here.
//   THE ORDER IS PROVEN.    A single monotonic logical clock stamps every render at write time and
//                           every classification at run time; `nonBlocking` is true iff every
//                           classification ran strictly AFTER the render of the text it classified.
//
// ERROR ISOLATION, BOTH DIRECTIONS. A throwing render sink never stops interception; a throwing
// classifier never stops rendering; a throwing bus subscriber is already isolated by the bus. Each
// failure lands on an audit log instead of severing the other path.
//
// STREAM-SAFE SEGMENTATION. A sentence is only classified once it is COMPLETE: a terminator
// followed by whitespace, or a newline. A trailing fragment (including a bare trailing '.', which
// may be a decimal point still streaming) stays buffered until the next write or `end()`, so a
// claim split across chunks is intercepted exactly once, with its span in full-stream coordinates.
//
// Pure node built-ins + the Wave-1 sibling modules. Runs under `node --test test/`.

import { ClaimEventBus, CLAIM_EVENT_TOPIC } from './claim-event-bus.mjs';
import { CLAIM_KIND, classifySentence, segmentSentences } from './semantic-classifier.mjs';

/** True when a stream-complete sentence boundary sits at index i of buffer. */
function boundaryAt(buffer, i) {
  const ch = buffer[i];
  if (ch === '\n') return true;
  if (ch !== '.' && ch !== '!' && ch !== '?') return false;
  const next = buffer[i + 1];
  return next !== undefined && /\s/.test(next);
}

/**
 * The Wave-1 non-blocking streaming pipeline: synchronous render, asynchronous semantic
 * interception, event-bus dispatch.
 */
export class StreamInterceptor {
  #bus;
  #renderSink;
  #classify;
  #buffer = '';
  /** Absolute offset of #buffer[0] in the full stream (spans are full-stream coordinates). */
  #absBase = 0;
  /** The monotonic logical clock ordering renders vs classifications. */
  #tick = 0;
  #rendered = [];
  #classified = [];
  #interceptions = [];
  #errors = [];
  #pendingTasks = 0;
  #waiters = [];
  #ended = false;

  /**
   * @param {{bus?: ClaimEventBus, renderSink?: (chunk:string)=>void, classify?: (s:string)=>object}} [o]
   *   bus        — the Wave-1 event bus intercepted claims are dispatched to (default: a fresh one).
   *   renderSink — the UI: called SYNCHRONOUSLY with each chunk inside write().
   *   classify   — the semantic classifier (default: the Wave-1 classifySentence).
   */
  constructor({ bus = new ClaimEventBus(), renderSink = null, classify = classifySentence } = {}) {
    if (!bus || typeof bus.publish !== 'function' || typeof bus.settle !== 'function') {
      throw new Error('StreamInterceptor: bus must be a ClaimEventBus-like ({publish, settle})');
    }
    if (renderSink !== null && typeof renderSink !== 'function') {
      throw new Error('StreamInterceptor: renderSink (when given) must be a function');
    }
    if (typeof classify !== 'function') {
      throw new Error('StreamInterceptor: classify must be a function');
    }
    this.#bus = bus;
    this.#renderSink = renderSink;
    this.#classify = classify;
  }

  /** The event bus intercepted claims are dispatched to. */
  get bus() {
    return this.#bus;
  }

  /**
   * Stream one chunk. SYNCHRONOUS AND NON-BLOCKING: the chunk is rendered inside this call; any
   * sentence the chunk completes is only SCHEDULED for classification (microtask), never classified
   * here. Returns the frozen render record.
   */
  write(chunk) {
    if (this.#ended) {
      throw new Error('write(): the stream has ended — no further chunks are accepted');
    }
    if (typeof chunk !== 'string') {
      throw new Error(`write(): chunk must be a string (got ${typeof chunk})`);
    }
    const render = Object.freeze({ index: this.#rendered.length, chunk, tick: ++this.#tick });
    this.#rendered.push(render);
    if (this.#renderSink) {
      // The UI renders NOW, inside the write — but a broken sink never severs interception.
      try {
        this.#renderSink(chunk);
      } catch (error) {
        this.#errors.push(Object.freeze({ stage: 'render', chunk, error }));
      }
    }
    this.#buffer += chunk;
    this.#drainCompleteSentences(render.tick);
    return render;
  }

  /**
   * End the stream: the trailing fragment (a sentence with no terminator yet) is flushed to
   * classification. Idempotent. Rendering already happened chunk-by-chunk; nothing renders here.
   */
  end() {
    if (this.#ended) return this;
    this.#ended = true;
    const rest = this.#buffer;
    this.#buffer = '';
    const base = this.#absBase;
    this.#absBase += rest.length;
    for (const segment of segmentSentences(rest, { base })) {
      this.#schedule(segment, this.#tick);
    }
    return this;
  }

  /** Resolve once every scheduled classification AND every bus delivery has run. */
  async settle() {
    for (;;) {
      if (this.#pendingTasks > 0) {
        await new Promise((resolve) => this.#waiters.push(resolve));
      } else if (this.#bus.pending) {
        await this.#bus.settle();
      } else {
        return;
      }
    }
  }

  /** Cut the buffer at the last stream-complete boundary and schedule the completed sentences. */
  #drainCompleteSentences(renderedTick) {
    let cut = -1;
    for (let i = 0; i < this.#buffer.length; i += 1) {
      if (boundaryAt(this.#buffer, i)) cut = i + 1;
    }
    if (cut < 0) return;
    const prefix = this.#buffer.slice(0, cut);
    this.#buffer = this.#buffer.slice(cut);
    const base = this.#absBase;
    this.#absBase += prefix.length;
    for (const segment of segmentSentences(prefix, { base })) {
      this.#schedule(segment, renderedTick);
    }
  }

  /** Defer one sentence to the microtask queue: classify there, dispatch claims to the bus there. */
  #schedule({ statement, span }, renderedTick) {
    this.#pendingTasks += 1;
    queueMicrotask(() => {
      const runTick = ++this.#tick;
      try {
        const result = this.#classify(statement);
        this.#classified.push(Object.freeze({ statement, span, rendered_tick: renderedTick, run_tick: runTick, ...result }));
        if (result.kind !== CLAIM_KIND.NONE) {
          const interception = Object.freeze({
            id: `w1::intercept-${this.#interceptions.length}`,
            source: 'stream-interceptor',
            kind: result.kind,
            claim_type: result.claim_type,
            statement,
            span,
            confidence: result.confidence,
            reason: result.reason,
          });
          this.#interceptions.push(interception);
          this.#bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, interception);
        }
      } catch (error) {
        this.#errors.push(Object.freeze({ stage: 'classify', statement, span, error }));
      } finally {
        this.#pendingTasks -= 1;
        if (this.#pendingTasks === 0) {
          const waiters = this.#waiters.splice(0);
          for (const resolve of waiters) resolve();
        }
      }
    });
  }

  /** Every chunk as rendered, in order (frozen copy): { index, chunk, tick }. */
  get rendered() {
    return Object.freeze([...this.#rendered]);
  }

  /** The full text as the UI rendered it. */
  get renderedText() {
    return this.#rendered.map((r) => r.chunk).join('');
  }

  /** Every classified sentence, claims and non-claims alike (audit; frozen copy). */
  get classified() {
    return Object.freeze([...this.#classified]);
  }

  /** Every intercepted claim, in interception order (frozen copy). */
  get interceptions() {
    return Object.freeze([...this.#interceptions]);
  }

  /** Isolated render/classify failures (frozen copy) — neither direction severs the other. */
  get errors() {
    return Object.freeze([...this.#errors]);
  }

  /**
   * THE DONE-WHEN, measured: true iff every classification ran strictly AFTER the render tick of
   * the write that completed its sentence — i.e. no render ever waited on interception.
   */
  get nonBlocking() {
    return this.#classified.every((c) => c.run_tick > c.rendered_tick);
  }
}

// ---------------------------------------------------------------------------
// THE FIXTURE — a chunked stream whose claims are SPLIT ACROSS CHUNK BOUNDARIES (each must still be
// intercepted exactly once), mixed with claim-free prose (which must render but never dispatch).
// ---------------------------------------------------------------------------

/** Chunk battery: a mathematical assertion and an empirical claim, both split mid-sentence. */
export const STREAM_FIXTURE = Object.freeze([
  'Every even integer greater than 2 is the ',
  'sum of two primes. We benchmarked the sieve and it ',
  'averaged 40 milliseconds per run. Let us grab lunch after',
  ' the meeting',
]);

/**
 * Drive the fixture through a fresh pipeline end-to-end. Returns the pipeline, the bus, the events
 * the bus delivered, and the done-when invariants.
 */
export async function runFixtureStream() {
  const bus = new ClaimEventBus();
  const delivered = [];
  bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, (event) => delivered.push(event));
  const renderLog = [];
  const stream = new StreamInterceptor({ bus, renderSink: (chunk) => renderLog.push(chunk) });
  for (const chunk of STREAM_FIXTURE) stream.write(chunk);
  stream.end();
  await stream.settle();
  return Object.freeze({
    stream,
    bus,
    delivered: Object.freeze([...delivered]),
    renderLog: Object.freeze([...renderLog]),
    // THE DONE-WHEN: every chunk rendered, in order, never waiting on classification...
    renderedEverything: renderLog.join('') === STREAM_FIXTURE.join(''),
    nonBlocking: stream.nonBlocking,
    // ...while the claims were intercepted and dispatched to the event bus.
    dispatchedToBus: delivered.length === stream.interceptions.length && delivered.length > 0,
  });
}
