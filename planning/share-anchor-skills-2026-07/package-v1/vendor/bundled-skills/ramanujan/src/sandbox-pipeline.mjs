// Overhaul Wave 3 — Secure WASM Sandbox Runtime: the PIPELINE INTEGRATION + EVIDENCE PATH.
//
// The wave's done-when made executable: verifications execute inside the Wave-3 WASM sandbox,
// enforce its resource boundaries, and PUBLISH STRUCTURED EVIDENCE BACK TO THE EVENT BUS. This
// module plugs the sandbox engine (wasm-sandbox.mjs) and its pre-compiled payloads
// (wasm-modules.mjs) into the two Wave-2 seams that were built for it:
//
//   FAST PATH  — createLocalSandboxRuntime attaches to FastPathQueue's `runtime` seam. An
//                exact-arithmetic job runs the pre-compiled overflow-checked i64 module
//                IN-PROCESS (fuel-metered, memory-capped). The adapter NEVER throws: every job
//                settles with an evidence record — executed, trapped (the honest overflow
//                refusal), terminated (a limit fired), or an explicit ABSTENTION (no
//                machine-checkable payload / outside the i64 envelope / the empirical lane) —
//                so a fast-path job can never be lost silently OR faked as verified.
//
//   FOREMAN    — createZ3WasmCertifyStep replaces the deferred `certify` step for the background
//                agentic plan. With NO pre-compiled z3 module attached it defers honestly
//                (ABSTAIN, evidence published, job continues — exactly the Wave-2 contract).
//                With bytes attached (the capability seam: { module_b64|module_bytes,
//                source_label }) it executes them in the NATIVE child runner — the wall-clock
//                kill — and either returns the raw output (mapping to sat/unsat and any rung
//                minting stays with the adjudication layer: propose != adjudicate) or HALTS the
//                job when the sandbox terminated/refused the run. Limits enforced either way.
//
// EVERY evidence record is published on the Wave-3 bus topic `claim:evidence` (SANDBOX_TOPIC) —
// the payload the Wave-4 Honesty-Law UI listeners consume — and also rides the Wave-2 settlement
// topics as the job result. THE HONESTY LAW HOLDS THROUGHOUT: evidence states what ACTUALLY ran
// (module sha256 + caller-declared source label + enforced limits + fuel/memory accounting);
// nothing here ever mints a verification verdict from a stand-in or an abstention.
//
// Node built-ins + the project's own Wave-1/2/3 modules. Runs under `node --test test/`.

import { ClaimEventBus, CLAIM_EVENT_TOPIC } from './claim-event-bus.mjs';
import { CLAIM_KIND } from './semantic-classifier.mjs';
import { FASTPATH_LANE } from './fastpath-queue.mjs';
import { makeDeferredStep } from './foreman-worker.mjs';
import { PipelineRouter, PIPELINE, PIPELINE_TOPIC } from './pipeline-router.mjs';
import { EXACT_ARITHMETIC_WASM, EXACT_ARITHMETIC_OPS } from './wasm-modules.mjs';
import {
  executeWasm,
  runInNativeSandbox,
  EXECUTION_OUTCOME,
  I64_MIN,
  I64_MAX,
} from './wasm-sandbox.mjs';

/** The Wave-3 bus topic: one structured evidence record per sandbox verification attempt. */
export const SANDBOX_TOPIC = Object.freeze({
  EVIDENCE: 'claim:evidence',
});

/** The evidence record type stamp. */
export const EVIDENCE_TYPE = 'wasm-sandbox-execution';

/** The honest source label for the in-repo pre-compiled exact-arithmetic module. */
export const EXACT_ARITHMETIC_SOURCE_LABEL = 'exact-arithmetic-i64 (pre-compiled in-repo, overflow-checked)';

/**
 * Compose one structured, JSON-safe, frozen evidence record.
 * @param {{claim_id?:string|null, source:{pipeline:string, lane?:string|null, step?:string|null},
 *          module_source?:string|null, execution?:object|null, agreement?:boolean|null,
 *          reason?:string|null, error?:string|null}} o
 *   execution — the sandbox execution record (null on an abstention/error path).
 *   agreement — expected-vs-observed comparison (null when nothing was expected/executed).
 */
export function makeEvidenceRecord({ claim_id = null, source, module_source = null, execution = null, agreement = null, reason = null, error = null } = {}) {
  if (!source || typeof source !== 'object' || typeof source.pipeline !== 'string') {
    throw new Error('makeEvidenceRecord(): source must be an object with a pipeline string');
  }
  const abstained = execution === null && error === null;
  return Object.freeze({
    evidence_type: EVIDENCE_TYPE,
    claim_id,
    source: Object.freeze({
      pipeline: source.pipeline,
      lane: source.lane ?? null,
      step: source.step ?? null,
    }),
    module_source,
    module_sha256: execution ? execution.module_sha256 : null,
    outcome: execution ? execution.outcome : error !== null ? 'error' : 'abstained',
    abstained,
    agreement,
    reason,
    error,
    execution,
  });
}

// ---------------------------------------------------------------------------
// The fast-path arm.
// ---------------------------------------------------------------------------

const DECIMAL_INT = /^-?\d+$/;

/**
 * Validate a claim's machine-checkable computation payload:
 *   claim.computation = { op: 'add'|'sub'|'mul', args: [decimal-string, decimal-string], expected?: decimal-string }
 * Returns { ok:true, op, args, expected } or { ok:false, reason } — an honest abstention reason,
 * never an exception.
 */
export function parseComputation(claim) {
  const comp = claim && typeof claim === 'object' ? claim.computation : undefined;
  if (comp === undefined || comp === null) {
    return Object.freeze({
      ok: false,
      reason: 'no machine-checkable computation payload on the claim — nothing the sandbox may honestly execute (abstained, never faked)',
    });
  }
  if (
    typeof comp !== 'object' ||
    !EXACT_ARITHMETIC_OPS.includes(comp.op) ||
    !Array.isArray(comp.args) ||
    comp.args.length !== 2 ||
    !comp.args.every((a) => typeof a === 'string' && DECIMAL_INT.test(a))
  ) {
    return Object.freeze({
      ok: false,
      reason: `invalid computation payload — expected { op: ${EXACT_ARITHMETIC_OPS.join('|')}, args: [decimal-string, decimal-string], expected?: decimal-string }`,
    });
  }
  if (comp.args.some((a) => BigInt(a) < I64_MIN || BigInt(a) > I64_MAX)) {
    return Object.freeze({
      ok: false,
      reason: 'outside the i64 exact-arithmetic envelope — the arbitrary-magnitude path stays on the Wave-9 firewall subprocess (bigint rationals); honestly bounded, never silently wrapped',
    });
  }
  let expected = null;
  if (comp.expected !== undefined && comp.expected !== null) {
    if (typeof comp.expected !== 'string' || !DECIMAL_INT.test(comp.expected)) {
      return Object.freeze({ ok: false, reason: 'invalid computation payload — expected (when given) must be a decimal integer string' });
    }
    expected = comp.expected;
  }
  return Object.freeze({ ok: true, op: comp.op, args: Object.freeze([...comp.args]), expected });
}

/**
 * The Wave-3 fast-path runtime: attach it to FastPathQueue's `runtime` seam (or pass it as
 * PipelineRouter's `runtime` convenience arg). Executes exact-arithmetic jobs in the in-process
 * WASM sandbox and returns the evidence record as the settlement result; publishes every record
 * on `claim:evidence` when a bus is given. NEVER throws into the queue.
 * @param {{bus?: ClaimEventBus|null, limits?: object}} [o]
 * @returns {(job: {seq:number, claim_id:string|null, claim:object, lane:string}) => Promise<object>}
 */
export function createLocalSandboxRuntime({ bus = null, limits = {} } = {}) {
  if (bus !== null && (typeof bus !== 'object' || typeof bus.publish !== 'function')) {
    throw new Error('createLocalSandboxRuntime(): bus (when given) must be ClaimEventBus-like ({publish})');
  }
  return async function localSandboxRuntime(job) {
    let evidence;
    try {
      evidence = await runFastPathJob(job, limits);
    } catch (error) {
      evidence = makeEvidenceRecord({
        claim_id: job && typeof job.claim_id === 'string' ? job.claim_id : null,
        source: { pipeline: PIPELINE.FAST_PATH, lane: job && typeof job.lane === 'string' ? job.lane : null },
        error: `sandbox runtime adapter error (isolated — never thrown into the queue): ${error && error.message ? error.message : String(error)}`,
      });
    }
    if (bus) bus.publish(SANDBOX_TOPIC.EVIDENCE, evidence);
    return evidence;
  };
}

/** One fast-path job -> one evidence record. */
async function runFastPathJob(job, limits) {
  const claim_id = typeof job.claim_id === 'string' ? job.claim_id : null;
  const source = { pipeline: PIPELINE.FAST_PATH, lane: job.lane };

  if (job.lane === FASTPATH_LANE.EMPIRICAL_SANDBOX) {
    return makeEvidenceRecord({
      claim_id,
      source,
      reason:
        'Claim<Empirical> re-executes on the Pillar-7 vm sandbox, not this WASM runtime — outside the exact-arithmetic/logic envelope (abstained honestly; never routed to Lean/z3)',
    });
  }

  const parsed = parseComputation(job.claim);
  if (!parsed.ok) {
    return makeEvidenceRecord({ claim_id, source, reason: parsed.reason });
  }

  const execution = await executeWasm(EXACT_ARITHMETIC_WASM, {
    entry: parsed.op,
    args: parsed.args,
    limits,
  });
  const agreement =
    execution.outcome === EXECUTION_OUTCOME.COMPLETED && parsed.expected !== null
      ? BigInt(execution.value) === BigInt(parsed.expected)
      : null;
  return makeEvidenceRecord({
    claim_id,
    source,
    module_source: EXACT_ARITHMETIC_SOURCE_LABEL,
    execution,
    agreement,
    reason:
      execution.outcome === EXECUTION_OUTCOME.TRAPPED
        ? 'the overflow-checked module trapped — an honest refusal (correct or refused, never a silently wrapped value)'
        : null,
  });
}

// ---------------------------------------------------------------------------
// The Foreman arm.
// ---------------------------------------------------------------------------

/**
 * The Wave-3 `certify` step for the Foreman background worker: pre-compiled z3 (or any solver
 * module) attaches through the capability seam and runs inside the NATIVE sandbox runner.
 *
 * @param {{bus?: ClaimEventBus|null,
 *          z3?: {module_b64?:string, module_bytes?:Uint8Array, source_label:string,
 *                entry?:string, args?:Array<string>}|null,
 *          limits?: object}} [o]
 *   z3.source_label is REQUIRED when attaching: evidence must name what ACTUALLY executed —
 *   a stand-in must never masquerade as z3 (THE HONESTY LAW).
 * @returns {{name:'certify', run:Function}} a ForemanWorker-compatible step.
 */
export function createZ3WasmCertifyStep({ bus = null, z3 = null, limits = {} } = {}) {
  if (bus !== null && (typeof bus !== 'object' || typeof bus.publish !== 'function')) {
    throw new Error('createZ3WasmCertifyStep(): bus (when given) must be ClaimEventBus-like ({publish})');
  }
  if (z3 !== null) {
    if (typeof z3 !== 'object') throw new Error('createZ3WasmCertifyStep(): z3 (when given) must be an object');
    if (typeof z3.module_b64 !== 'string' && !(z3.module_bytes instanceof Uint8Array)) {
      throw new Error('createZ3WasmCertifyStep(): z3 needs module_b64 (base64 string) or module_bytes (Uint8Array) — the pre-compiled WASM to execute');
    }
    if (typeof z3.source_label !== 'string' || z3.source_label.length === 0) {
      throw new Error('createZ3WasmCertifyStep(): z3.source_label is required — evidence must name what actually executed (a stand-in must never masquerade as z3)');
    }
  }

  return Object.freeze({
    name: 'certify',
    run: async (claim) => {
      const claim_id = claim && typeof claim.id === 'string' ? claim.id : null;
      const source = { pipeline: PIPELINE.FOREMAN, step: 'certify' };

      if (!z3) {
        const reason =
          'no pre-compiled z3 WASM module attached — the certify step defers honestly (attach { module_b64 | module_bytes, source_label } to execute the real solver inside the native sandbox)';
        const evidence = makeEvidenceRecord({ claim_id, source, reason });
        if (bus) bus.publish(SANDBOX_TOPIC.EVIDENCE, evidence);
        return Object.freeze({ deferred: true, verdict: 'ABSTAIN', reason, evidence });
      }

      const execution = runInNativeSandbox({
        module_b64: z3.module_b64 ?? null,
        module_bytes: z3.module_bytes ?? null,
        entry: z3.entry ?? 'check',
        args: z3.args ?? [],
        limits,
      });
      const evidence = makeEvidenceRecord({ claim_id, source, module_source: z3.source_label, execution });
      if (bus) bus.publish(SANDBOX_TOPIC.EVIDENCE, evidence);

      if (execution.outcome === EXECUTION_OUTCOME.COMPLETED) {
        return Object.freeze({
          executed: true,
          verdict: null,
          raw_value: execution.value,
          note: 'raw sandbox output only — mapping to sat/unsat and any rung minting stays with the adjudication layer (propose != adjudicate)',
          evidence,
        });
      }
      return Object.freeze({
        halt: true,
        reason: `z3 WASM execution did not complete: ${execution.outcome}${execution.termination ? ` (${execution.termination.limit} limit)` : ''} — the sandbox boundaries terminated/refused it safely`,
        evidence,
      });
    },
  });
}

/**
 * The Wave-3 agentic step plan: formalize (deferred) -> certify (the WASM-sandboxed z3 seam) ->
 * adjudicate (deferred). Drop-in for ForemanWorker's / PipelineRouter's `steps`.
 */
export function sandboxAgenticSteps({ bus = null, z3 = null, limits = {} } = {}) {
  return Object.freeze([
    makeDeferredStep('formalize', 'a formalization capability (informal statement -> Lean source + faithfulness query)'),
    createZ3WasmCertifyStep({ bus, z3, limits }),
    makeDeferredStep('adjudicate', 'an adjudication capability (the verify-router OBSERVED seam)'),
  ]);
}

// ---------------------------------------------------------------------------
// THE FIXTURE — the full Wave-1 -> Wave-2 -> Wave-3 flow: intercepted claims are routed by
// complexity, the fast path executes REAL WebAssembly under enforced limits, out-of-envelope /
// empirical / unattached-z3 paths abstain honestly, and every attempt publishes structured
// evidence on the bus.
// ---------------------------------------------------------------------------

/** Four intercepted-claim payloads covering both pipeline arms and the honest abstention paths. */
export const SANDBOX_CLAIM_FIXTURE = Object.freeze([
  Object.freeze({
    id: 'wave3-add',
    kind: CLAIM_KIND.MATHEMATICAL,
    claim_type: 'computational',
    statement: 'The sum of 2 and 2 equals 4.',
    computation: Object.freeze({ op: 'add', args: Object.freeze(['2', '2']), expected: '4' }),
  }),
  Object.freeze({
    id: 'wave3-huge',
    kind: CLAIM_KIND.MATHEMATICAL,
    claim_type: 'computational',
    statement: 'A product far beyond the i64 envelope.',
    computation: Object.freeze({ op: 'mul', args: Object.freeze(['123456789123456789123456789', '2']) }),
  }),
  Object.freeze({
    id: 'wave3-proof',
    kind: CLAIM_KIND.MATHEMATICAL,
    claim_type: 'proof-bearing',
    statement: 'Every even integer greater than 2 is the sum of two primes.',
  }),
  Object.freeze({
    id: 'wave3-empirical',
    kind: CLAIM_KIND.EMPIRICAL,
    claim_type: null,
    statement: 'We benchmarked the sieve and it averaged 40 milliseconds per run.',
  }),
]);

/**
 * Drive the fixture end-to-end (bus -> router -> sandbox -> evidence). Returns the parts + the
 * wave's done-when invariants, measured.
 */
export async function runSandboxPipelineFixture() {
  const bus = new ClaimEventBus();
  const evidenceEvents = [];
  const routedEvents = [];
  const settledEvents = [];
  bus.subscribe(SANDBOX_TOPIC.EVIDENCE, (e) => evidenceEvents.push(e));
  bus.subscribe(PIPELINE_TOPIC.ROUTED, (e) => routedEvents.push(e));
  bus.subscribe(PIPELINE_TOPIC.FASTPATH_SETTLED, (e) => settledEvents.push(e));
  bus.subscribe(PIPELINE_TOPIC.FOREMAN_SETTLED, (e) => settledEvents.push(e));

  const router = new PipelineRouter({
    bus,
    runtime: createLocalSandboxRuntime({ bus }),
    steps: sandboxAgenticSteps({ bus }),
  });
  router.attach();

  for (const payload of SANDBOX_CLAIM_FIXTURE) bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, payload);
  await router.settle();
  await bus.settle();

  const evidence = evidenceEvents.map((e) => e.payload);
  const byClaim = (id) => evidence.find((ev) => ev.claim_id === id) ?? null;
  const addEv = byClaim('wave3-add');
  const hugeEv = byClaim('wave3-huge');
  const proofEv = byClaim('wave3-proof');
  const empiricalEv = byClaim('wave3-empirical');

  return Object.freeze({
    bus,
    router,
    evidence: Object.freeze([...evidence]),
    routedEvents: Object.freeze([...routedEvents]),
    settledEvents: Object.freeze([...settledEvents]),
    // THE DONE-WHEN, measured:
    // ...every routed certification task produced exactly one structured evidence record...
    everyRoutedClaimProducedEvidence:
      router.routed.length === SANDBOX_CLAIM_FIXTURE.length &&
      router.quarantined.length === 0 &&
      router.errors.length === 0 &&
      SANDBOX_CLAIM_FIXTURE.every((c) => Boolean(byClaim(c.id))),
    // ...the verification executed REAL WebAssembly and completed WITHIN the enforced limits...
    verifiedWithinLimits: Boolean(
      addEv &&
        addEv.outcome === EXECUTION_OUTCOME.COMPLETED &&
        addEv.agreement === true &&
        addEv.execution.fuel.used <= addEv.execution.limits.max_fuel &&
        addEv.execution.metered === true,
    ),
    // ...the out-of-envelope / empirical / unattached-z3 paths abstained HONESTLY (nothing faked)...
    boundariesHonored: Boolean(
      hugeEv && hugeEv.abstained && empiricalEv && empiricalEv.abstained && proofEv && proofEv.abstained,
    ),
    // ...and the evidence was PUBLISHED BACK TO THE EVENT BUS, structured and typed.
    evidencePublishedOnBus:
      evidenceEvents.length === SANDBOX_CLAIM_FIXTURE.length &&
      evidenceEvents.every((e) => e.topic === SANDBOX_TOPIC.EVIDENCE && e.payload.evidence_type === EVIDENCE_TYPE),
    // The Wave-2 invariant still holds on every record: the legacy queue stayed bypassed.
    legacyBypassed: router.routed.every((r) => r.legacy_queue_bypassed === true),
  });
}
