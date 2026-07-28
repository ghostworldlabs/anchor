// Overhaul Wave 2 — Crucible/Foreman Pipeline Integration: the FOREMAN BACKGROUND WORKER.
//
// The MULTI-STEP AGENTIC arm of the Crucible/Foreman pipeline. Claims whose verification cannot be
// a single local execution — proof-bearing claims (formalize -> certify -> adjudicate) and
// conceptual claims (cross-family corroboration + commission) — are submitted here by the Wave-2
// PipelineRouter and orchestrated Foreman-style IN THE BACKGROUND: a serial worker drives each job
// through a named STEP PLAN, wave by wave, with a per-step audit trail, halting a job honestly on
// the first failing step and moving on to the next job (one bad proof never stalls the pipeline).
//
// THE NON-BLOCKING CONTRACT (inherited from the Wave-1 spine):
//   1. `submit()` is SYNCHRONOUS and returns the frozen job ticket — NO step runs inside the
//      submit call; the worker loop is scheduled on the microtask queue.
//   2. A throwing step HALTS ITS JOB ONLY: the error is captured on that job's step record, the
//      remaining steps are skipped, and the worker continues with the next job.
//   3. Every job carries its full per-step audit ({ name, ok, halted, result | error }) — a job is
//      DONE or HALTED, never silently abandoned.
//
// THE HONEST DEFERRED ARM. The DEFAULT step plan (formalize -> certify -> adjudicate) mirrors the
// spine's deferred verifiers: absent injected capabilities each step returns an explicit ABSTAIN
// (deferred:true) — the orchestration is real and fully exercised, while the tool-backed step
// implementations arrive with the Wave-3 sandbox / the tool lane's injected certifier bundle
// (compare proof-auto-certifier: capability-gated, spawns nothing by default). No default step
// ever fakes a verification verdict — the Honesty Law holds on the background path too.
//
// Pure node built-ins; no timers, no I/O. Runs under `node --test test/`.

/** Job lifecycle states. */
export const FOREMAN_JOB_STATUS = Object.freeze({
  QUEUED: 'queued',
  RUNNING: 'running',
  DONE: 'done',
  HALTED: 'halted',
});

/** The default agentic step plan for a background proof job. */
export const AGENTIC_STEP_NAMES = Object.freeze(['formalize', 'certify', 'adjudicate']);

/**
 * A DEFERRED step: runs for real (the orchestration is exercised) but honestly ABSTAINs — the
 * named capability has not been attached yet. Mirrors the verify-router's deferred verifiers.
 */
export function makeDeferredStep(name, capability) {
  if (typeof name !== 'string' || name.length === 0) {
    throw new Error('makeDeferredStep(): name must be a non-empty string');
  }
  return Object.freeze({
    name,
    run: () =>
      Object.freeze({
        deferred: true,
        verdict: 'ABSTAIN',
        reason: `${capability} not attached — the ${name} step defers honestly (the Wave-3 sandbox runtime / an injected certifier bundle supplies it)`,
      }),
  });
}

/** The default (deferred, honest-abstain) agentic step plan: formalize -> certify -> adjudicate. */
export function defaultAgenticSteps() {
  return Object.freeze([
    makeDeferredStep('formalize', 'a formalization capability (informal statement -> Lean source + faithfulness query)'),
    makeDeferredStep('certify', 'a certifier capability (the Lean kernel + bounded z3 faithfulness bundle)'),
    makeDeferredStep('adjudicate', 'an adjudication capability (the verify-router OBSERVED seam)'),
  ]);
}

/**
 * The Wave-2 Foreman background worker: synchronous non-blocking submit, serial FIFO background
 * processing, multi-step orchestration with per-step audit, per-job halt isolation.
 */
export class ForemanWorker {
  #steps;
  #onResult;
  /** FIFO backlog of internal (mutable) jobs awaiting the worker loop. */
  #backlog = [];
  /** Append-only: every job ever submitted (internal records; exposed frozen). */
  #jobs = [];
  /** Append-only: isolated onResult failures { job, error }. */
  #errors = [];
  #running = false;
  #scheduled = 0;
  #waiters = [];
  #seq = 0;

  /**
   * @param {{steps?: ReadonlyArray<{name:string, run:Function}>, onResult?: Function|null}} [o]
   *   steps    — the ordered step plan every job runs through (default: the deferred agentic plan
   *              formalize -> certify -> adjudicate). Each step: { name, run: async (claim, ctx) }.
   *              ctx = { job_id, step_index, prior } (prior = the frozen results of earlier steps).
   *   onResult — called with each finished job's frozen record (the router publishes these back to
   *              the event bus). A throwing onResult is isolated onto the error audit.
   */
  constructor({ steps = defaultAgenticSteps(), onResult = null } = {}) {
    if (!Array.isArray(steps) || steps.length === 0) {
      throw new Error('ForemanWorker: steps must be a non-empty array of { name, run }');
    }
    for (const step of steps) {
      if (!step || typeof step.name !== 'string' || step.name.length === 0 || typeof step.run !== 'function') {
        throw new Error('ForemanWorker: every step must be { name: non-empty string, run: function }');
      }
    }
    if (onResult !== null && typeof onResult !== 'function') {
      throw new Error('ForemanWorker: onResult (when given) must be a function');
    }
    this.#steps = Object.freeze([...steps]);
    this.#onResult = onResult;
  }

  /** The ordered step plan every job runs through. */
  get steps() {
    return this.#steps;
  }

  /**
   * Submit one claim for background multi-step orchestration. SYNCHRONOUS AND NON-BLOCKING: no
   * step runs inside this call — the worker loop is scheduled on the microtask queue. Returns the
   * frozen job ticket.
   * @param {object} claim  the intercepted claim payload (needs an id).
   * @returns {{job_id:string, claim_id:string|null, status:string, step_plan:ReadonlyArray<string>}} frozen.
   */
  submit(claim) {
    if (!claim || typeof claim !== 'object') {
      throw new Error('submit(): claim must be an object (the intercepted claim payload)');
    }
    const job = {
      job_id: `foreman-job-${this.#seq++}`,
      claim_id: typeof claim.id === 'string' ? claim.id : null,
      claim,
      status: FOREMAN_JOB_STATUS.QUEUED,
      steps: [],
      halt_reason: null,
    };
    this.#backlog.push(job);
    this.#jobs.push(job);
    this.#scheduled += 1;
    queueMicrotask(() => {
      this.#scheduled -= 1;
      this.#pump().finally(() => this.#notify());
    });
    return Object.freeze({
      job_id: job.job_id,
      claim_id: job.claim_id,
      status: job.status,
      step_plan: Object.freeze(this.#steps.map((s) => s.name)),
    });
  }

  /** Resolve once every submitted job has finished (DONE or HALTED). */
  async settle() {
    while (this.busy) {
      await new Promise((resolve) => this.#waiters.push(resolve));
    }
  }

  /** True while jobs are backlogged, scheduled, or being processed. */
  get busy() {
    return this.#scheduled > 0 || this.#running || this.#backlog.length > 0;
  }

  /** Every job ever submitted, in order (frozen snapshots with full per-step audit). */
  get jobs() {
    return Object.freeze(this.#jobs.map((j) => this.#snapshot(j)));
  }

  /** Isolated onResult failures (frozen copy) — a throwing result listener never stops the worker. */
  get errors() {
    return Object.freeze([...this.#errors]);
  }

  // --- internals ----------------------------------------------------------

  /** The serial worker loop: drain the backlog FIFO, one job at a time, all steps per job. */
  async #pump() {
    if (this.#running) return;
    this.#running = true;
    try {
      while (this.#backlog.length > 0) {
        const job = this.#backlog.shift();
        job.status = FOREMAN_JOB_STATUS.RUNNING;
        for (let i = 0; i < this.#steps.length; i += 1) {
          const step = this.#steps[i];
          try {
            const result = await step.run(job.claim, {
              job_id: job.job_id,
              step_index: i,
              prior: Object.freeze([...job.steps]),
            });
            const halted = Boolean(result && typeof result === 'object' && result.halt === true);
            job.steps.push(Object.freeze({ name: step.name, ok: !halted, halted, result }));
            if (halted) {
              job.status = FOREMAN_JOB_STATUS.HALTED;
              job.halt_reason = (result && result.reason) || `step "${step.name}" requested a halt`;
              break;
            }
          } catch (error) {
            job.steps.push(Object.freeze({ name: step.name, ok: false, halted: true, error }));
            job.status = FOREMAN_JOB_STATUS.HALTED;
            job.halt_reason = `step "${step.name}" threw: ${error && error.message ? error.message : String(error)}`;
            break;
          }
        }
        if (job.status !== FOREMAN_JOB_STATUS.HALTED) {
          job.status = FOREMAN_JOB_STATUS.DONE;
        }
        if (this.#onResult) {
          try {
            this.#onResult(this.#snapshot(job));
          } catch (error) {
            this.#errors.push(Object.freeze({ job: this.#snapshot(job), stage: 'on-result', error }));
          }
        }
      }
    } finally {
      this.#running = false;
    }
  }

  #notify() {
    if (!this.busy) {
      const waiters = this.#waiters.splice(0);
      for (const resolve of waiters) resolve();
    }
  }

  #snapshot(job) {
    return Object.freeze({
      job_id: job.job_id,
      claim_id: job.claim_id,
      claim: job.claim,
      status: job.status,
      halt_reason: job.halt_reason,
      steps: Object.freeze([...job.steps]),
    });
  }
}
