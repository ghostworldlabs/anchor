// Overhaul Wave 2 — Crucible/Foreman Pipeline Integration: the FOREMAN BACKGROUND WORKER.
//
// Exercises the REAL Wave-2 source (src/foreman-worker.mjs): synchronous non-blocking submit,
// serial FIFO background processing, multi-step orchestration with a per-step audit trail, honest
// per-job halt isolation (one bad proof never stalls the pipeline), the deferred honest-abstain
// default step plan (formalize -> certify -> adjudicate), and onResult delivery.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ForemanWorker,
  FOREMAN_JOB_STATUS,
  AGENTIC_STEP_NAMES,
  defaultAgenticSteps,
  makeDeferredStep,
} from '../src/foreman-worker.mjs';

const CLAIM = Object.freeze({ id: 'c-proof-1', kind: 'mathematical', claim_type: 'proof-bearing' });

// =====================================================================================
// 0. The default agentic step plan — deferred, honest-abstain, never a faked verdict.
// =====================================================================================

test('the default step plan is formalize -> certify -> adjudicate', () => {
  assert.deepEqual(AGENTIC_STEP_NAMES, ['formalize', 'certify', 'adjudicate']);
  const steps = defaultAgenticSteps();
  assert.deepEqual(steps.map((s) => s.name), [...AGENTIC_STEP_NAMES]);
});

test('done-when (honesty arm): every deferred default step ABSTAINs explicitly — no capability, no verdict', async () => {
  const worker = new ForemanWorker();
  worker.submit(CLAIM);
  await worker.settle();
  const [job] = worker.jobs;
  assert.equal(job.status, FOREMAN_JOB_STATUS.DONE);
  assert.equal(job.steps.length, 3);
  for (const step of job.steps) {
    assert.equal(step.ok, true);
    assert.equal(step.result.deferred, true);
    assert.equal(step.result.verdict, 'ABSTAIN');
    assert.match(step.result.reason, /not attached/);
  }
});

test('makeDeferredStep validates its name', () => {
  assert.throws(() => makeDeferredStep('', 'x'), /name must be a non-empty string/);
});

// =====================================================================================
// 1. Non-blocking submit — synchronous ticket, NO step runs inside the call.
// =====================================================================================

test('submit is synchronous and non-blocking: the ticket returns before any step has run', async () => {
  const ran = [];
  const worker = new ForemanWorker({
    steps: [{ name: 'only', run: (claim) => ran.push(claim.id) }],
  });
  const ticket = worker.submit(CLAIM);
  // The ticket came back synchronously...
  assert.ok(Object.isFrozen(ticket));
  assert.equal(ticket.claim_id, 'c-proof-1');
  assert.equal(ticket.status, FOREMAN_JOB_STATUS.QUEUED);
  assert.deepEqual([...ticket.step_plan], ['only']);
  // ...and NO step has run yet — the submitter never waited on orchestration.
  assert.equal(ran.length, 0, 'no step may run inside submit()');
  assert.equal(worker.busy, true);
  await worker.settle();
  assert.equal(ran.length, 1);
  assert.equal(worker.busy, false);
});

// =====================================================================================
// 2. Multi-step orchestration — steps run in order, each seeing the prior step results.
// =====================================================================================

test('steps run in plan order and ctx.prior carries the audited earlier results', async () => {
  const seen = [];
  const worker = new ForemanWorker({
    steps: [
      { name: 'formalize', run: () => 'formal-form' },
      {
        name: 'certify',
        run: (claim, ctx) => {
          seen.push(ctx.prior.map((p) => `${p.name}:${p.result}`));
          return 'certificate';
        },
      },
      {
        name: 'adjudicate',
        run: (claim, ctx) => {
          seen.push(ctx.prior.map((p) => `${p.name}:${p.result}`));
          return 'adjudicated';
        },
      },
    ],
  });
  worker.submit(CLAIM);
  await worker.settle();
  const [job] = worker.jobs;
  assert.equal(job.status, FOREMAN_JOB_STATUS.DONE);
  assert.deepEqual(job.steps.map((s) => s.name), ['formalize', 'certify', 'adjudicate']);
  assert.deepEqual(seen, [
    ['formalize:formal-form'],
    ['formalize:formal-form', 'certify:certificate'],
  ]);
});

test('async steps are awaited — a later step never starts before an earlier one resolves', async () => {
  const order = [];
  const worker = new ForemanWorker({
    steps: [
      {
        name: 'slow',
        run: async () => {
          await Promise.resolve();
          await Promise.resolve();
          order.push('slow-done');
          return 1;
        },
      },
      { name: 'fast', run: () => order.push('fast-done') },
    ],
  });
  worker.submit(CLAIM);
  await worker.settle();
  assert.deepEqual(order, ['slow-done', 'fast-done']);
});

// =====================================================================================
// 3. Halt isolation — a throwing / halting step HALTS ITS JOB ONLY; the worker continues.
// =====================================================================================

test('a throwing step HALTs the job with the error audited, skips its remaining steps, and the NEXT job still runs', async () => {
  const worker = new ForemanWorker({
    steps: [
      {
        name: 'certify',
        run: (claim) => {
          if (claim.id === 'bad') throw new Error('lean rejected the source');
          return 'ok';
        },
      },
      { name: 'adjudicate', run: () => 'adjudicated' },
    ],
  });
  worker.submit({ id: 'bad' });
  worker.submit({ id: 'good' });
  await worker.settle();
  const [bad, good] = worker.jobs;

  assert.equal(bad.status, FOREMAN_JOB_STATUS.HALTED);
  assert.match(bad.halt_reason, /certify.*lean rejected/);
  assert.equal(bad.steps.length, 1, 'the remaining steps were skipped');
  assert.equal(bad.steps[0].ok, false);
  assert.match(bad.steps[0].error.message, /lean rejected/);

  assert.equal(good.status, FOREMAN_JOB_STATUS.DONE);
  assert.equal(good.steps.length, 2);
});

test('a step returning { halt: true, reason } halts the job gracefully (an honest halt, not a crash)', async () => {
  const worker = new ForemanWorker({
    steps: [
      { name: 'formalize', run: () => ({ halt: true, reason: 'outside the ground-equation class' }) },
      { name: 'certify', run: () => assert.fail('must not run after a halt') },
    ],
  });
  worker.submit(CLAIM);
  await worker.settle();
  const [job] = worker.jobs;
  assert.equal(job.status, FOREMAN_JOB_STATUS.HALTED);
  assert.equal(job.halt_reason, 'outside the ground-equation class');
  assert.equal(job.steps.length, 1);
  assert.equal(job.steps[0].halted, true);
});

// =====================================================================================
// 4. Serial FIFO — jobs are processed one at a time, in submit order.
// =====================================================================================

test('jobs are processed serially FIFO — no interleaving between jobs', async () => {
  const trace = [];
  const worker = new ForemanWorker({
    steps: [
      {
        name: 's1',
        run: async (claim) => {
          trace.push(`${claim.id}:s1`);
          await Promise.resolve();
        },
      },
      { name: 's2', run: (claim) => trace.push(`${claim.id}:s2`) },
    ],
  });
  worker.submit({ id: 'j1' });
  worker.submit({ id: 'j2' });
  await worker.settle();
  assert.deepEqual(trace, ['j1:s1', 'j1:s2', 'j2:s1', 'j2:s2']);
});

// =====================================================================================
// 5. onResult delivery + isolation.
// =====================================================================================

test('onResult receives each finished job (DONE and HALTED alike); a throwing onResult is audited, never fatal', async () => {
  const results = [];
  const worker = new ForemanWorker({
    steps: [
      {
        name: 'only',
        run: (claim) => {
          if (claim.id === 'bad') throw new Error('nope');
          return 'ok';
        },
      },
    ],
    onResult: (job) => {
      results.push(`${job.claim_id}:${job.status}`);
      if (job.claim_id === 'bad') throw new Error('listener blew up');
    },
  });
  worker.submit({ id: 'bad' });
  worker.submit({ id: 'good' });
  await worker.settle();
  assert.deepEqual(results, ['bad:halted', 'good:done']);
  assert.equal(worker.errors.length, 1);
  assert.equal(worker.errors[0].stage, 'on-result');
  assert.match(worker.errors[0].error.message, /listener blew up/);
});

// =====================================================================================
// 6. Validation.
// =====================================================================================

test('bad step plans, listeners, and claims are rejected with clear errors', () => {
  assert.throws(() => new ForemanWorker({ steps: [] }), /steps must be a non-empty array/);
  assert.throws(() => new ForemanWorker({ steps: [{ name: 'x' }] }), /run: function/);
  assert.throws(() => new ForemanWorker({ steps: [{ name: '', run: () => {} }] }), /non-empty string/);
  assert.throws(() => new ForemanWorker({ onResult: 'nope' }), /onResult .* must be a function/);
  const worker = new ForemanWorker();
  assert.throws(() => worker.submit('not-an-object'), /claim must be an object/);
});
