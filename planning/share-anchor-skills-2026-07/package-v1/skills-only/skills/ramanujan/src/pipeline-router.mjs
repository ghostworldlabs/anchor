// Overhaul Wave 2 — Crucible/Foreman Pipeline Integration: the PIPELINE ROUTER.
//
// The EVENT-BUS ROUTING LAYER — the wave's done-when made executable. It subscribes to the Wave-1
// bus topic `claim:intercepted` and routes EVERY intercepted claim, BY COMPLEXITY, to exactly one
// of the two Crucible/Foreman pipeline arms:
//
//   FAST PATH  (FastPathQueue)  — SINGLE-STEP LOCAL verification. An exact-arithmetic /
//              computational check rides the `exact-arithmetic` lane; a Claim<Empirical> rides the
//              `empirical-sandbox` (Pillar-7) lane — NEVER Lean/z3. The Wave-3 WASM sandbox runtime
//              plugs into the queue's runtime seam.
//   FOREMAN    (ForemanWorker)  — MULTI-STEP AGENTIC verification in the background. A
//              proof-bearing claim runs the agentic plan (formalize -> certify -> adjudicate); a
//              conceptual claim runs it toward cross-family corroboration + commission.
//
// THE LEGACY QUEUE IS BYPASSED BY CONSTRUCTION. The bespoke CertifierQueue is DISMANTLED (its
// module survives only as a hard-faulting tombstone — see certifier-queue.mjs); this router is the
// ONLY placement layer, and it stamps every routed record with the dismantling marker
// (`legacy_queue_bypassed: true` + the tombstone's provenance), so the bypass is auditable per
// claim, not asserted globally.
//
// NO SILENT LOSS. Every intercepted claim either (a) lands in exactly one pipeline and a frozen
// routed record is published on `claim:routed`, or (b) is QUARANTINED onto an explicit audit (an
// unrecognizable payload is not a certification task — but it is never dropped without a record),
// or (c) lands on the error audit (e.g. bounded-backpressure refusal). Results flowing back from
// the pipelines are re-published on the bus (`claim:fastpath-settled` / `claim:foreman-settled`)
// for the Wave-3 evidence path and the Wave-4 Honesty-Law UI listeners.
//
// Pure node built-ins + the project's own Wave-1/Wave-2 modules. Runs under `node --test test/`.

import { ClaimEventBus, CLAIM_EVENT_TOPIC } from './claim-event-bus.mjs';
import { CLAIM_KIND } from './semantic-classifier.mjs';
import { StreamInterceptor } from './stream-interceptor.mjs';
import { FastPathQueue, FASTPATH_LANE } from './fastpath-queue.mjs';
import { ForemanWorker } from './foreman-worker.mjs';
import { CERTIFIER_QUEUE_DISMANTLED } from './certifier-queue.mjs';

/** The two — and ONLY two — pipeline arms certification tasks are routed to. */
export const PIPELINE = Object.freeze({
  FAST_PATH: 'fast-path',
  FOREMAN: 'foreman',
});

/** The pipelines, as an array (introspection + exhaustiveness checks). */
export const PIPELINES = Object.freeze(Object.values(PIPELINE));

/** The Wave-2 bus topics (the Wave-1 topic vocabulary stays pinned; these are the pipeline's). */
export const PIPELINE_TOPIC = Object.freeze({
  /** A claim was placed on a pipeline: the frozen routed record (placement + legacy-bypass stamp). */
  ROUTED: 'claim:routed',
  /** A fast-path job settled locally: { job, result }. */
  FASTPATH_SETTLED: 'claim:fastpath-settled',
  /** A Foreman background job finished (DONE or honestly HALTED): the frozen job record. */
  FOREMAN_SETTLED: 'claim:foreman-settled',
});

/**
 * THE COMPLEXITY RULE — which pipeline arm a claim belongs to. Deterministic over the intercepted
 * payload's (kind, claim_type):
 *   EMPIRICAL                  -> FAST_PATH / empirical-sandbox  (local Pillar-7 re-execution; never Lean/z3)
 *   MATHEMATICAL computational -> FAST_PATH / exact-arithmetic   (single-step local exact check)
 *   MATHEMATICAL proof-bearing -> FOREMAN                        (multi-step agentic proof)
 *   MATHEMATICAL conceptual    -> FOREMAN                        (multi-step agentic corroboration)
 *   MATHEMATICAL (other)       -> FOREMAN                        (fail toward the stronger multi-step arm)
 *   anything else              -> QUARANTINE                     (not a certification task; audited, never dropped)
 * @param {{kind?:string, claim_type?:string}} payload  the intercepted claim payload.
 * @returns {{pipeline:string|null, lane:string|null, quarantine:boolean, reason:string}} frozen.
 */
export function classifyComplexity(payload) {
  const kind = payload && typeof payload === 'object' ? payload.kind : undefined;
  const claimType = payload && typeof payload === 'object' ? payload.claim_type : undefined;

  if (kind === CLAIM_KIND.EMPIRICAL) {
    return Object.freeze({
      pipeline: PIPELINE.FAST_PATH,
      lane: FASTPATH_LANE.EMPIRICAL_SANDBOX,
      quarantine: false,
      reason: 'Claim<Empirical> — single-step local re-execution on the Pillar-7 sandbox lane (never Lean/z3)',
    });
  }
  if (kind === CLAIM_KIND.MATHEMATICAL) {
    if (claimType === 'computational') {
      return Object.freeze({
        pipeline: PIPELINE.FAST_PATH,
        lane: FASTPATH_LANE.EXACT_ARITHMETIC,
        quarantine: false,
        reason: 'computational claim — single-step local exact-arithmetic check on the fast path',
      });
    }
    const label =
      claimType === 'proof-bearing'
        ? 'proof-bearing claim — multi-step agentic proof (formalize -> certify -> adjudicate)'
        : claimType === 'conceptual'
          ? 'conceptual claim — multi-step agentic corroboration (cross-family + commission)'
          : `mathematical claim with unrecognized subtype ${JSON.stringify(claimType)} — failing toward the stronger multi-step arm`;
    return Object.freeze({
      pipeline: PIPELINE.FOREMAN,
      lane: null,
      quarantine: false,
      reason: `${label} — Foreman background pipeline`,
    });
  }
  return Object.freeze({
    pipeline: null,
    lane: null,
    quarantine: true,
    reason: `unrecognized claim kind ${JSON.stringify(kind)} — not a certification task this router can place; quarantined (audited, never silently dropped)`,
  });
}

/**
 * The Wave-2 routing layer: event-bus listeners that place every intercepted claim on the
 * fast-path queue or the Foreman background worker, stamping the legacy-queue bypass per claim.
 */
export class PipelineRouter {
  #bus;
  #fastPath;
  #foreman;
  /** Append-only: every routed record (also published on PIPELINE_TOPIC.ROUTED). */
  #routed = [];
  /** Append-only: quarantined payloads { payload, reason }. */
  #quarantined = [];
  /** Append-only: isolated routing failures { payload, error }. */
  #errors = [];
  #detach = null;

  /**
   * @param {{bus: ClaimEventBus, fastPath?: FastPathQueue, foreman?: ForemanWorker,
   *          runtime?: Function|null, steps?: Array|null}} o
   *   bus      — the Wave-1 event bus (required): interceptions arrive on it; routed records and
   *              pipeline results are published back onto it.
   *   fastPath — an externally-owned FastPathQueue (its owner then owns result publication).
   *              Default: a router-owned queue whose settlements are re-published on the bus.
   *   foreman  — an externally-owned ForemanWorker (ditto). Default: a router-owned worker (the
   *              deferred agentic plan) whose finished jobs are re-published on the bus.
   *   runtime  — convenience for the DEFAULT fast path: the local runtime seam (Wave 3's sandbox).
   *   steps    — convenience for the DEFAULT Foreman worker: an injected step plan.
   */
  constructor({ bus, fastPath = null, foreman = null, runtime = null, steps = null } = {}) {
    if (!bus || typeof bus.subscribe !== 'function' || typeof bus.publish !== 'function' || typeof bus.settle !== 'function') {
      throw new Error('PipelineRouter: bus must be a ClaimEventBus-like ({subscribe, publish, settle})');
    }
    this.#bus = bus;
    this.#fastPath =
      fastPath ??
      new FastPathQueue({
        runtime,
        onResult: (settlement) => this.#bus.publish(PIPELINE_TOPIC.FASTPATH_SETTLED, settlement),
      });
    this.#foreman =
      foreman ??
      new ForemanWorker({
        ...(steps ? { steps } : {}),
        onResult: (job) => this.#bus.publish(PIPELINE_TOPIC.FOREMAN_SETTLED, job),
      });
  }

  /** The fast-path queue (local proofs). */
  get fastPath() {
    return this.#fastPath;
  }

  /** The Foreman background worker (multi-step agentic proofs). */
  get foreman() {
    return this.#foreman;
  }

  /**
   * Attach the routing listener to the bus (`claim:intercepted`). Returns the detach function.
   * Attaching twice without detaching is a wiring bug and throws (double-routing would place one
   * claim on a pipeline twice).
   */
  attach() {
    if (this.#detach) {
      throw new Error('attach(): the router is already attached — detach() it first (double-routing guard)');
    }
    const off = this.#bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, (event) => this.#route(event));
    this.#detach = () => {
      off();
      this.#detach = null;
    };
    return this.#detach;
  }

  /** Detach the routing listener (idempotent). */
  detach() {
    if (this.#detach) this.#detach();
  }

  /** True while the routing listener is subscribed. */
  get attached() {
    return this.#detach !== null;
  }

  /**
   * Resolve once the whole pipeline is quiet: bus deliveries drained, background fast-path drains
   * done, Foreman backlog processed — INCLUDING the cascades (a finished job re-publishes on the
   * bus, which is itself a new delivery).
   */
  async settle() {
    for (;;) {
      await this.#bus.settle();
      await this.#fastPath.settle();
      await this.#foreman.settle();
      if (!this.#bus.pending && !this.#fastPath.pending && !this.#foreman.busy) return;
    }
  }

  /** Every routed record, in routing order (frozen copy) — each carries the legacy-bypass stamp. */
  get routed() {
    return Object.freeze([...this.#routed]);
  }

  /** Quarantined (unrecognizable) payloads (frozen copy) — audited, never silently dropped. */
  get quarantined() {
    return Object.freeze([...this.#quarantined]);
  }

  /** Isolated routing failures (frozen copy) — e.g. a bounded-backpressure refusal. */
  get errors() {
    return Object.freeze([...this.#errors]);
  }

  // --- internals ----------------------------------------------------------

  /** Route ONE intercepted claim event: complexity -> placement -> stamped record -> publish. */
  #route(event) {
    const payload = event && typeof event === 'object' ? event.payload : undefined;
    const decision = classifyComplexity(payload);
    if (decision.quarantine) {
      this.#quarantined.push(Object.freeze({ payload, reason: decision.reason }));
      return;
    }
    try {
      let placement_ref;
      if (decision.pipeline === PIPELINE.FAST_PATH) {
        const job = this.#fastPath.enqueue(payload, { lane: decision.lane });
        placement_ref = `fastpath-seq-${job.seq}`;
      } else {
        const ticket = this.#foreman.submit(payload);
        placement_ref = ticket.job_id;
      }
      const record = Object.freeze({
        claim_id: typeof payload.id === 'string' ? payload.id : null,
        kind: payload.kind,
        claim_type: payload.claim_type ?? null,
        statement: payload.statement,
        pipeline: decision.pipeline,
        lane: decision.lane,
        placement_ref,
        reason: decision.reason,
        // THE DISMANTLING, stamped per claim: this router is the only placement layer; the legacy
        // CertifierQueue is a hard-faulting tombstone and was never touched.
        legacy_queue_bypassed: true,
        legacy_queue: CERTIFIER_QUEUE_DISMANTLED,
      });
      this.#routed.push(record);
      this.#bus.publish(PIPELINE_TOPIC.ROUTED, record);
    } catch (error) {
      // A placement failure (e.g. bounded backpressure) is captured, never propagated into the bus
      // delivery — and never silent.
      this.#errors.push(Object.freeze({ payload, error }));
    }
  }
}

// ---------------------------------------------------------------------------
// THE FIXTURE — the full Wave-1 -> Wave-2 flow: a chunked stream (claims split across chunk
// boundaries) is intercepted semantically, dispatched on the bus, and routed BY COMPLEXITY into
// both pipeline arms — proof-bearing to Foreman, computational + empirical to the fast path —
// with the legacy queue bypassed on every record.
// ---------------------------------------------------------------------------

/**
 * Chunk battery: a proof-bearing assertion (-> Foreman), a computational claim (-> fast path,
 * exact-arithmetic), an empirical claim (-> fast path, empirical-sandbox), and claim-free prose
 * (-> intercepted by nobody), all split mid-sentence across chunks.
 */
export const PIPELINE_STREAM_FIXTURE = Object.freeze([
  'Every even integer greater than 2 is the ',
  'sum of two primes. The sum of 2 and 2 equals ',
  '4. We benchmarked the sieve and it averaged 40 ',
  'milliseconds per run. Let us grab lunch after the meeting',
]);

/**
 * A deliberately-labeled STUB local runtime for the fixture — it proves the queue -> runtime seam
 * end-to-end and mints NO verification verdict (the Wave-3 WASM sandbox replaces it).
 */
function stubLocalRuntime(job) {
  return Object.freeze({
    executed_by: 'stub-local-runtime (the Wave-3 secure WASM sandbox replaces this seam)',
    lane: job.lane,
    claim_id: job.claim_id,
    verdict: 'ABSTAIN',
    reason: 'stub runtime — no real local verification ran (Wave 3 supplies the sandboxed executor)',
  });
}

/**
 * Drive the fixture stream through interception -> bus -> routing end-to-end. Returns the parts +
 * the wave's done-when invariants, measured.
 */
export async function runPipelineFixture() {
  const bus = new ClaimEventBus();
  const routedEvents = [];
  const settledEvents = [];
  bus.subscribe(PIPELINE_TOPIC.ROUTED, (e) => routedEvents.push(e));
  bus.subscribe(PIPELINE_TOPIC.FASTPATH_SETTLED, (e) => settledEvents.push(e));
  bus.subscribe(PIPELINE_TOPIC.FOREMAN_SETTLED, (e) => settledEvents.push(e));

  const router = new PipelineRouter({ bus, runtime: stubLocalRuntime });
  router.attach();

  const stream = new StreamInterceptor({ bus });
  for (const chunk of PIPELINE_STREAM_FIXTURE) stream.write(chunk);
  stream.end();
  await stream.settle();
  await router.settle();

  const routed = router.routed;
  return Object.freeze({
    bus,
    router,
    stream,
    routedEvents: Object.freeze([...routedEvents]),
    settledEvents: Object.freeze([...settledEvents]),
    // THE DONE-WHEN, measured:
    // ...every intercepted certification task was routed (none quarantined, none errored)...
    routedEverything:
      routed.length === stream.interceptions.length &&
      routed.length > 0 &&
      router.quarantined.length === 0 &&
      router.errors.length === 0,
    // ...EXCLUSIVELY to the fast-path queue or the Foreman background pipeline...
    exclusivelyPipelines: routed.every((r) => PIPELINES.includes(r.pipeline)),
    // ...with the legacy CertifierQueue completely bypassed on every record...
    legacyBypassed: routed.every((r) => r.legacy_queue_bypassed === true && r.legacy_queue.dismantled === true),
    // ...split by complexity: multi-step proof to Foreman, local checks to the fast path.
    foremanClaims: Object.freeze(routed.filter((r) => r.pipeline === PIPELINE.FOREMAN)),
    fastPathClaims: Object.freeze(routed.filter((r) => r.pipeline === PIPELINE.FAST_PATH)),
  });
}
