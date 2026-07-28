// drivers/test/reliability-wrapper.test.mjs — Foreman Wave 1 gate (Phase A, part 1):
// the RELIABILITY WRAPPER at the agent-injection boundary. Drives the REAL source in
// drivers/reliability.mjs (and its application in drivers/index.mjs makeForemanDriver)
// with NO subprocess — an injected, fault-scripted agent — and proves each gated
// done-when as a concrete assertion (no vacuous GREEN):
//
//   - the wrapper is TRANSPARENT on the success path (one inner call, opts unchanged);
//   - a RECOVERABLE transport fault is retried with backoff (typed via classifyExit),
//     and the success is NOT double-executed;
//   - a NON-RECOVERABLE fault is NOT retried — it propagates on the first throw;
//   - retry typing REUSES foreman/bin/transport.mjs classifyExit (recoverable classes
//     retry; non-recoverable classes do not);
//   - round-aware idempotency yields ZERO double-execution for one logical call;
//   - two same-prompt Judge calls in DIFFERENT rounds BOTH execute (no cross-round dedup);
//   - the wrapper APPLIES on the injected-agent path through makeForemanDriver.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { makeReliableAgent, classifyFault, idempotencyKey } from '../reliability.mjs';
import { classifyExit, EXIT_CLASSES } from '../../foreman/bin/transport.mjs';
import { makeForemanDriver } from '../index.mjs';

// A no-wait sleep that records the backoff delays it was asked to honor.
function recordingSleep() {
  const delays = [];
  const sleep = async (ms) => { delays.push(ms); };
  sleep.delays = delays;
  return sleep;
}

// Build a thrown transport fault annotated with a classifyExit() INPUT, so the
// wrapper types it through the REAL taxonomy (the reuse contract).
function transportFault(exit, message = 'induced transport fault') {
  return Object.assign(new Error(message), { exit });
}

// --- guard -----------------------------------------------------------------

test('makeReliableAgent requires an agent() function and a sane maxAttempts', () => {
  assert.throws(() => makeReliableAgent({}), TypeError);
  assert.throws(() => makeReliableAgent({ agent: 'nope' }), TypeError);
  assert.throws(() => makeReliableAgent({ agent: async () => 'x', maxAttempts: 0 }), TypeError);
});

// --- transparent success path ----------------------------------------------

test('transparent on success: inner is called exactly once with the prompt + opts unchanged', async () => {
  const seen = [];
  const inner = async (prompt, opts) => { seen.push({ prompt, opts }); return `ok:${prompt}`; };
  const reliable = makeReliableAgent({ agent: inner, sleep: recordingSleep() });

  const out = await reliable('hello', { label: 'L', schema: { type: 'object' } });
  assert.equal(out, 'ok:hello');
  assert.equal(seen.length, 1, 'no fault ⇒ exactly one inner call');
  assert.equal(seen[0].prompt, 'hello');
  assert.equal(seen[0].opts.label, 'L', 'opts pass through unchanged');
  assert.deepEqual(seen[0].opts.schema, { type: 'object' });
});

// --- (Given recoverable) retry with backoff, no double-execution ------------

test('a RECOVERABLE fault retries with backoff and the success is NOT double-executed', async () => {
  let calls = 0;
  let completed = 0; // side-effect that only the SUCCESSFUL attempt reaches
  const inner = async () => {
    calls += 1;
    if (calls === 1) throw transportFault({ timedOut: true }); // -> TIMEOUT_KILLED (recoverable)
    completed += 1;
    return 'recovered';
  };
  const sleep = recordingSleep();
  const reliable = makeReliableAgent({ agent: inner, baseDelayMs: 50, sleep });

  const out = await reliable('p', { label: 'x' });
  assert.equal(out, 'recovered');
  assert.equal(calls, 2, 'one failed attempt + one successful retry');
  assert.equal(completed, 1, 'the success side-effect ran exactly once — no double execution');
  assert.deepEqual(sleep.delays, [50], 'exactly one backoff slept before the single retry');
});

test('backoff is exponential across multiple recoverable retries up to maxAttempts', async () => {
  let calls = 0;
  const inner = async () => { calls += 1; throw transportFault({ signal: 'SIGKILL' }); }; // SIGNAL_KILLED (recoverable)
  const sleep = recordingSleep();
  const reliable = makeReliableAgent({ agent: inner, maxAttempts: 3, baseDelayMs: 10, sleep });

  await assert.rejects(() => reliable('p'), /induced transport fault/);
  assert.equal(calls, 3, 'initial + (maxAttempts-1) retries, then give up');
  assert.deepEqual(sleep.delays, [10, 20], 'exponential backoff between the two retries (no sleep after the final failure)');
});

// --- (Given non-recoverable) no retry --------------------------------------

test('a NON-RECOVERABLE fault is NOT retried — it propagates on the first throw', async () => {
  let calls = 0;
  const inner = async () => { calls += 1; throw transportFault({ code: 2 }); }; // NONZERO_EXIT (non-recoverable)
  const sleep = recordingSleep();
  const reliable = makeReliableAgent({ agent: inner, sleep });

  await assert.rejects(() => reliable('p'), /induced transport fault/);
  assert.equal(calls, 1, 'non-recoverable ⇒ exactly one attempt, no retry');
  assert.deepEqual(sleep.delays, [], 'no backoff for a non-recoverable fault');
});

test('an UNANNOTATED error is treated as non-recoverable (never blindly retried)', async () => {
  let calls = 0;
  const inner = async () => { calls += 1; throw new Error('plain logic bug'); };
  const reliable = makeReliableAgent({ agent: inner, sleep: recordingSleep() });
  await assert.rejects(() => reliable('p'), /plain logic bug/);
  assert.equal(calls, 1, 'a non-transport error is not a recoverable transport fault');
});

// --- typed retry REUSES classifyExit ---------------------------------------

test('classifyFault types faults through the REUSED transport taxonomy (recoverable vs not)', () => {
  // Recoverable classes (a retry could plausibly succeed).
  for (const exit of [{ timedOut: true }, { signal: 'SIGTERM' }, { code: 0, finalEnv: null }]) {
    const viaWrapper = classifyFault(transportFault(exit));
    const viaTaxonomy = classifyExit(exit);
    assert.equal(viaWrapper.recoverable, true);
    assert.equal(viaWrapper.recoverable, viaTaxonomy.recoverable, 'wrapper verdict == classifyExit verdict');
    assert.equal(viaWrapper.class, viaTaxonomy.class);
  }
  // Non-recoverable classes (a blind retry would just repeat the failure).
  for (const exit of [{ code: 2 }, { spawnError: new Error('ENOENT') }, { finalEnv: { is_error: true } }]) {
    const v = classifyFault(transportFault(exit));
    assert.equal(v.recoverable, false);
    assert.equal(v.class, classifyExit(exit).class);
  }
  // A precomputed classification on the error is trusted as-is.
  assert.equal(classifyFault({ classification: { class: 'custom', recoverable: true } }).recoverable, true);
  // Totality backstop: an unrecognized error routes through classifyExit({}) -> unknown.
  assert.equal(classifyFault(null).class, EXIT_CLASSES.UNKNOWN);
  assert.equal(classifyFault(null).recoverable, false);
});

// --- round-aware idempotency: ZERO double-execution ------------------------

test('idempotency: a duplicate dispatch of ONE logical call executes the inner agent ONCE', async () => {
  let calls = 0;
  const inner = async () => { calls += 1; return { n: calls }; };
  const reliable = makeReliableAgent({ agent: inner, sleep: recordingSleep() });

  const key = { round: 1, role: 'judge', seq: 7 };
  const a = await reliable('same', { ...key });
  const b = await reliable('same', { ...key }); // same logical key ⇒ memoized
  assert.equal(calls, 1, 'the underlying agent ran exactly once for one logical call');
  assert.deepEqual(a, b, 'the duplicate dispatch returned the memoized result');

  // Concurrent duplicate dispatch also collapses to one execution (same in-flight promise).
  let cCalls = 0;
  const slow = makeReliableAgent({ agent: async () => { cCalls += 1; return 'v'; }, sleep: recordingSleep() });
  const [r1, r2] = await Promise.all([
    slow('p', { round: 2, role: 'judge', seq: 1 }),
    slow('p', { round: 2, role: 'judge', seq: 1 }),
  ]);
  assert.equal(cCalls, 1);
  assert.deepEqual([r1, r2], ['v', 'v']);
});

// --- no cross-round dedup: two same-prompt Judge calls in DIFFERENT rounds --

test('NO cross-round dedup: two same-prompt Judge calls in DIFFERENT rounds BOTH execute', async () => {
  const executed = [];
  // A Judge-shaped agent: same prompt + same role + same call-sequence, only the round differs.
  const judge = async (prompt, opts) => { executed.push(opts.round); return { decision: 'NOT_CONVERGED', round: opts.round }; };
  const reliable = makeReliableAgent({ agent: judge, sleep: recordingSleep() });

  const r1 = await reliable('judge the same plan', { role: 'judge', seq: 1, round: 1 });
  const r2 = await reliable('judge the same plan', { role: 'judge', seq: 1, round: 2 });

  assert.deepEqual(executed, [1, 2], 'both rounds executed — the round-1 call was NOT reused for round 2');
  assert.equal(r1.round, 1);
  assert.equal(r2.round, 2);

  // The keys differ ONLY by round — proving round is part of the idempotency key.
  assert.notEqual(idempotencyKey({ round: 1, role: 'judge', seq: 1 }), idempotencyKey({ round: 2, role: 'judge', seq: 1 }));
});

test('default (no explicit call-sequence): distinct dispatches never accidentally dedup', async () => {
  let calls = 0;
  const inner = async () => { calls += 1; return calls; };
  const reliable = makeReliableAgent({ agent: inner, sleep: recordingSleep() });
  // Same prompt/role/round, but no seq ⇒ each dispatch is a distinct logical call.
  await reliable('p', { role: 'judge', round: 1 });
  await reliable('p', { role: 'judge', round: 1 });
  assert.equal(calls, 2, 'without an explicit key the wrapper is transparent — no dedup of real calls');
});

test('a fully-failed (rejected) logical call is evicted, not cached as a poison pill', async () => {
  let calls = 0;
  const inner = async () => { calls += 1; if (calls === 1) throw transportFault({ code: 1 }); return 'later-ok'; };
  const reliable = makeReliableAgent({ agent: inner, sleep: recordingSleep() });
  const key = { round: 1, role: 'judge', seq: 9 };
  await assert.rejects(() => reliable('p', { ...key })); // non-recoverable ⇒ rejects
  const out = await reliable('p', { ...key }); // same key, fresh attempt (not poisoned)
  assert.equal(out, 'later-ok');
  assert.equal(calls, 2);
});

// --- the wrapper APPLIES on the injected-agent path (makeForemanDriver) -----

test('makeForemanDriver APPLIES the reliability wrapper on the injected-agent path', async () => {
  let executeCalls = 0;
  const injected = async (prompt, opts) => {
    if ((opts?.label || '').startsWith('execute')) {
      executeCalls += 1;
      if (executeCalls === 1) throw transportFault({ timedOut: true }); // recoverable on first try
      return 'execute-ok';
    }
    return opts?.schema ? { answerable: 'yes', findings: [] } : 'ok';
  };
  // Inject a no-wait sleep through the reliability opts so the test is instant.
  const drv = await makeForemanDriver({ agent: injected, reliability: { sleep: async () => {}, baseDelayMs: 0 } });
  const ctx = { wave: { n: 1, title: 't' }, reviewerIndex: 0, projectDir: '/p', iteration: 1 };

  const res = await drv.execute(ctx);
  assert.equal(res.note, 'agent execute complete');
  assert.equal(res.raw, 'execute-ok');
  assert.equal(executeCalls, 2, 'the injected execute call was retried once ⇒ the wrapper is applied on this path');
});

test('makeForemanDriver reliability:false opts OUT — a recoverable fault is no longer retried', async () => {
  let calls = 0;
  const injected = async (prompt, opts) => {
    if ((opts?.label || '').startsWith('execute')) { calls += 1; throw transportFault({ timedOut: true }); }
    return 'ok';
  };
  const drv = await makeForemanDriver({ agent: injected, reliability: false });
  const ctx = { wave: { n: 1, title: 't' }, reviewerIndex: 0, projectDir: '/p', iteration: 1 };
  await assert.rejects(() => drv.execute(ctx));
  assert.equal(calls, 1, 'opt-out ⇒ the raw injected agent, no retry');
});
