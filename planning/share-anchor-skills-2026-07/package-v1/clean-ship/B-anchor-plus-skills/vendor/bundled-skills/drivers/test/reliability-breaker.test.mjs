// drivers/test/reliability-breaker.test.mjs — Foreman Wave 2 gate (Phase A, part 2):
// the THREE hardening behaviors layered on the Wave-1 reliability wrapper. Drives the
// REAL source (drivers/reliability-breaker.mjs + its integration in drivers/reliability.mjs
// and drivers/index.mjs makeForemanDriver) with NO subprocess — injected, fault-scripted
// agents + injectable clock/timers — and proves each gated done-when as a concrete
// assertion (no vacuous GREEN):
//
//   - the per-provider BREAKER OPENS after N consecutive recoverable failures, FAILS
//     FAST (BreakerOpenError, never retried), and RECOVERS via a HALF_OPEN probe;
//   - the breaker is PER-PROVIDER (a sick provider does not degrade a healthy one);
//   - an IDLE (no-output) call is DETECTED + KILLED (its AbortSignal is raised) by the
//     idle sliver, surfaced as a recoverable fault, and a heartbeat re-arms the window;
//   - in the wrapper, an idle-killed attempt is RETRIED and recovers;
//   - ANTI-LAUNDERING: every retry is logged as its OWN schema-valid telemetry record
//     (visible to the Judge), carrying the original call's label;
//   - the breaker APPLIES on the injected-agent path through makeForemanDriver.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  makeReliableAgent,
  makePerProviderBreaker, runWithIdleWatchdog, makeIdleFault,
  BreakerOpenError, BREAKER_STATES, classifyFault,
} from '../reliability.mjs';
import { validateTelemetry, EXIT_CLASSES } from '../../foreman/bin/transport.mjs';
import { makeForemanDriver } from '../index.mjs';

// A thrown transport fault annotated with a classifyExit() INPUT, typed through the
// REAL taxonomy by the wrapper (same helper shape as the Wave-1 gate).
function transportFault(exit, message = 'induced transport fault') {
  return Object.assign(new Error(message), { exit });
}

// A controllable single-slot idle timer: captures the pending (cb, ms) and lets the
// test FIRE or inspect it deterministically (no real wall-clock).
function fakeTimers() {
  let pending = null;
  let nextId = 1;
  return {
    scheduleIdle(cb, ms) { pending = { cb, ms, id: nextId++ }; return pending.id; },
    cancelIdle(id) { if (pending && pending.id === id) pending = null; },
    fire() { const p = pending; pending = null; if (p) p.cb(); },
    peek() { return pending; },
  };
}

// Flush a few microtasks so a deferred (microtask-scheduled) call body has run.
const flush = async () => { for (let i = 0; i < 4; i++) await Promise.resolve(); };

// =====================================================================================
// (1) Per-provider circuit breaker — unit (deterministic clock).
// =====================================================================================

test('breaker OPENS after N consecutive recoverable failures, FAILS FAST, then RECOVERS', () => {
  const clock = { t: 1000 };
  const b = makePerProviderBreaker({ threshold: 3, cooldownMs: 500, now: () => clock.t });

  // Below the threshold: still CLOSED, calls are admitted.
  b.onRecoverableFailure('P');
  b.onRecoverableFailure('P');
  assert.equal(b.stateOf('P').state, BREAKER_STATES.CLOSED);
  assert.doesNotThrow(() => b.beforeCall('P'), 'two failures < threshold ⇒ still admitting');

  // The N-th consecutive recoverable failure OPENS it.
  b.onRecoverableFailure('P');
  assert.equal(b.stateOf('P').state, BREAKER_STATES.OPEN);
  assert.equal(b.stateOf('P').fails, 3);

  // OPEN + still cooling ⇒ FAIL FAST (a non-recoverable BreakerOpenError).
  assert.throws(() => b.beforeCall('P'), (e) => e instanceof BreakerOpenError && e.breakerOpen === true);
  assert.equal(classifyFault(new BreakerOpenError('P', 'x')).recoverable, false, 'a fail-fast is NEVER retried');

  // After the cooldown a HALF_OPEN probe is admitted; a clean call RECOVERS (CLOSED + streak cleared).
  clock.t += 500;
  assert.doesNotThrow(() => b.beforeCall('P'));
  assert.equal(b.stateOf('P').state, BREAKER_STATES.HALF_OPEN, 'cooled down ⇒ admits exactly one probe');
  b.onSuccess('P');
  assert.equal(b.stateOf('P').state, BREAKER_STATES.CLOSED);
  assert.equal(b.stateOf('P').fails, 0, 'recovery clears the consecutive-failure streak');
});

test('a HALF_OPEN probe that FAILS RE-OPENS the breaker (still sick)', () => {
  const clock = { t: 0 };
  const b = makePerProviderBreaker({ threshold: 1, cooldownMs: 100, now: () => clock.t });
  b.onRecoverableFailure('P');                       // threshold 1 ⇒ OPEN immediately
  assert.equal(b.stateOf('P').state, BREAKER_STATES.OPEN);
  clock.t += 100;
  b.beforeCall('P');                                  // cooled down ⇒ HALF_OPEN
  assert.equal(b.stateOf('P').state, BREAKER_STATES.HALF_OPEN);
  b.onRecoverableFailure('P');                        // the probe failed
  assert.equal(b.stateOf('P').state, BREAKER_STATES.OPEN, 'a failed probe re-OPENS, not closes');
  assert.equal(b.stateOf('P').openedAt, clock.t, 'the cooldown clock restarts from the re-open');
});

test('a clean call RESETS the streak (only CONSECUTIVE failures open the breaker)', () => {
  const b = makePerProviderBreaker({ threshold: 3, now: () => 0 });
  b.onRecoverableFailure('P');
  b.onRecoverableFailure('P');
  b.onSuccess('P');                                   // streak broken
  b.onRecoverableFailure('P');
  b.onRecoverableFailure('P');
  assert.equal(b.stateOf('P').state, BREAKER_STATES.CLOSED, 'two-then-two (non-consecutive) never reaches threshold');
  assert.equal(b.stateOf('P').fails, 2);
});

test('makePerProviderBreaker rejects a non-positive threshold', () => {
  assert.throws(() => makePerProviderBreaker({ threshold: 0 }), TypeError);
});

// =====================================================================================
// (1b) Breaker integration in the wrapper — fail-fast + per-provider isolation.
// =====================================================================================

test('wrapper: the breaker OPENS on the seam and FAILS FAST without calling the agent', async () => {
  const clock = { t: 0 };
  let calls = 0;
  const agent = async () => { calls += 1; throw transportFault({ timedOut: true }); }; // recoverable
  const reliable = makeReliableAgent({
    agent, maxAttempts: 1, sleep: async () => {}, provider: 'flaky',
    breaker: { threshold: 2, cooldownMs: 1000, now: () => clock.t },
  });

  await assert.rejects(() => reliable('p'), /induced transport fault/);
  await assert.rejects(() => reliable('p'), /induced transport fault/);
  assert.equal(calls, 2, 'two real attempts before the breaker opened');

  // Third call: the breaker is OPEN ⇒ fail fast, the agent is NEVER invoked.
  await assert.rejects(() => reliable('p'), (e) => e instanceof BreakerOpenError);
  assert.equal(calls, 2, 'fail-fast ⇒ the sick provider is NOT hammered');

  // After the cooldown the half-open probe is admitted and (now healthy) recovers.
  clock.t += 1000;
  let healed = 0;
  const reliable2 = makeReliableAgent({
    agent: async () => { healed += 1; return 'ok'; }, maxAttempts: 1, sleep: async () => {},
    provider: 'flaky', breaker: { threshold: 2, cooldownMs: 1000, now: () => clock.t },
  });
  assert.equal(await reliable2('p'), 'ok'); // fresh wrapper proves the recovered path resolves
  assert.equal(healed, 1);
});

test('wrapper: the breaker is PER-PROVIDER — a sick provider does not degrade a healthy one', async () => {
  const breaker = makePerProviderBreaker({ threshold: 1, cooldownMs: 10_000, now: () => 0 });
  const reliable = makeReliableAgent({
    agent: async (_p, opts) => {
      if (opts.provider === 'bad') throw transportFault({ signal: 'SIGKILL' }); // recoverable
      return `ok:${opts.provider}`;
    },
    maxAttempts: 1, sleep: async () => {}, breaker,
  });

  await assert.rejects(() => reliable('p', { provider: 'bad' }));        // opens "bad"
  await assert.rejects(() => reliable('p', { provider: 'bad' }),
    (e) => e instanceof BreakerOpenError, 'the bad provider now fails fast');
  assert.equal(await reliable('p', { provider: 'good' }), 'ok:good', 'the healthy provider is unaffected');
});

// =====================================================================================
// (2) Idle-no-output sliver — unit (deterministic timer).
// =====================================================================================

test('idle sliver: a silent call is DETECTED + KILLED (its AbortSignal is raised)', async () => {
  const T = fakeTimers();
  let sawSignal = null;
  const p = runWithIdleWatchdog(
    ({ signal }) => new Promise(() => { sawSignal = signal; }), // never resolves, never heartbeats
    { idleMs: 50, scheduleIdle: T.scheduleIdle, cancelIdle: T.cancelIdle },
  );
  await flush();
  assert.ok(T.peek(), 'an idle window is armed before the call runs');
  assert.equal(sawSignal.aborted, false, 'not yet killed');

  T.fire(); // the idle window elapses with no output
  await assert.rejects(p, /idle: no output/);
  assert.equal(sawSignal.aborted, true, 'KILLED — the call’s AbortSignal is raised');
});

test('idle sliver: the idle fault is RECOVERABLE (same typed-retry path as the wall-clock kill)', () => {
  const f = makeIdleFault(50);
  assert.equal(f.idleKilled, true);
  const c = classifyFault(f);
  assert.equal(c.class, EXIT_CLASSES.TIMEOUT_KILLED);
  assert.equal(c.recoverable, true, 'an idle kill is retried, not propagated as a hard failure');
});

test('idle sliver: a heartbeat RE-ARMS the window; real output disarms it (never idle-killed)', async () => {
  const T = fakeTimers();
  let heartbeat = null, resolveCall = null;
  const p = runWithIdleWatchdog(
    ({ heartbeat: hb }) => new Promise((res) => { heartbeat = hb; resolveCall = res; }),
    { idleMs: 50, scheduleIdle: T.scheduleIdle, cancelIdle: T.cancelIdle },
  );
  await flush();
  const firstId = T.peek().id;
  heartbeat();                                        // output observed ⇒ re-arm
  assert.notEqual(T.peek().id, firstId, 'a heartbeat armed a FRESH idle window');

  resolveCall('produced');                            // the call finishes
  assert.equal(await p, 'produced');
  assert.equal(T.peek(), null, 'finishing disarms the idle timer (no spurious kill)');
});

test('idle sliver: idleMs<=0 is INERT — transparent passthrough (Wave-1 behavior preserved)', async () => {
  let seenSignal = 'unset';
  const out = await runWithIdleWatchdog(
    ({ signal }) => { seenSignal = signal; return Promise.resolve('v'); },
    { idleMs: 0 },
  );
  assert.equal(out, 'v');
  assert.equal(seenSignal, undefined, 'no signal injected when the sliver is inert');
});

// =====================================================================================
// (2b) Idle integration in the wrapper — detected, killed, then RETRIED to recovery.
// =====================================================================================

test('wrapper: an idle-killed attempt is detected, killed, and RETRIED to recovery', async () => {
  const T = fakeTimers();
  let attempts = 0;
  const agent = async (_p, opts) => {
    attempts += 1;
    if (attempts === 1) return new Promise(() => {}); // attempt 1 goes silent ⇒ idle-killed
    opts.heartbeat();                                  // attempt 2 produces output
    return 'recovered-after-idle';
  };
  const reliable = makeReliableAgent({
    agent, maxAttempts: 2, sleep: async () => {},
    idleMs: 50, scheduleIdle: T.scheduleIdle, cancelIdle: T.cancelIdle,
  });

  const pr = reliable('p', { label: 'judge' });
  await flush();          // attempt 1 started + idle window armed
  T.fire();               // detect + kill the silent attempt 1
  assert.equal(await pr, 'recovered-after-idle');
  assert.equal(attempts, 2, 'the idle-killed attempt was retried');
});

// =====================================================================================
// (3) Anti-laundering telemetry — every retry is a schema-valid, Judge-visible record.
// =====================================================================================

test('anti-laundering: every retry is logged as its OWN validated telemetry record', async () => {
  const records = [];
  let n = 0;
  const agent = async () => { n += 1; if (n < 3) throw transportFault({ timedOut: true }); return 'ok'; };
  const reliable = makeReliableAgent({
    agent, maxAttempts: 3, sleep: async () => {}, telemetry: (r) => records.push(r), servedModel: 'claude-opus-4-8',
  });

  const out = await reliable('p', { label: 'shark-hostile-output' });
  assert.equal(out, 'ok');
  assert.equal(n, 3, 'two failed attempts then success');
  assert.equal(records.length, 2, 'two retries ⇒ exactly two telemetry records (no laundering)');

  for (const r of records) {
    assert.doesNotThrow(() => validateTelemetry(r), 'each retry record is schema-valid (the Judge can read it)');
    assert.equal(r.exit_class, EXIT_CLASSES.TIMEOUT_KILLED);
    assert.equal(r.recoverable, true);
    assert.equal(r.model_served, 'claude-opus-4-8', 'SR-5 served-model attestation carried on the retry record');
    assert.match(r.label, /retry#\d/, 'the record is marked as a retry');
    assert.ok(r.label.includes('shark-hostile-output'),
      'the retry record carries the original call label — a retry never silently replaces the output');
  }
});

test('anti-laundering: no telemetry sink ⇒ no records, and a non-recoverable fault logs nothing', async () => {
  const records = [];
  const agent = async () => { throw transportFault({ code: 2 }); }; // non-recoverable ⇒ no retry
  const reliable = makeReliableAgent({ agent, maxAttempts: 3, sleep: async () => {}, telemetry: (r) => records.push(r) });
  await assert.rejects(() => reliable('p', { label: 'x' }));
  assert.equal(records.length, 0, 'a non-recoverable fault is not retried ⇒ no retry record');
});

// =====================================================================================
// (4) The breaker APPLIES on the injected-agent path through makeForemanDriver.
// =====================================================================================

test('makeForemanDriver APPLIES the per-provider breaker on the injected-agent path', async () => {
  let executeCalls = 0;
  const injected = async (prompt, opts) => {
    if ((opts?.label || '').startsWith('execute')) { executeCalls += 1; throw transportFault({ timedOut: true }); }
    return 'ok';
  };
  // maxAttempts:1 ⇒ each execute is one terminal recoverable failure; breaker opens at 2.
  const drv = await makeForemanDriver({
    agent: injected,
    reliability: { maxAttempts: 1, sleep: async () => {}, breaker: { threshold: 2 } },
  });
  const ctx = { wave: { n: 1, title: 't' }, reviewerIndex: 0, projectDir: '/p', iteration: 1 };

  await assert.rejects(() => drv.execute(ctx));
  await assert.rejects(() => drv.execute(ctx));
  assert.equal(executeCalls, 2, 'two real execute attempts before the breaker opened');

  // Third execute: the breaker is OPEN for the injected provider ⇒ fail fast.
  await assert.rejects(() => drv.execute(ctx), (e) => e instanceof BreakerOpenError);
  assert.equal(executeCalls, 2, 'the breaker degraded the build path — the agent was not invoked again');
});

test('makeForemanDriver reliability:{breaker:false} opts OUT of the breaker (no fail-fast)', async () => {
  let calls = 0;
  const injected = async (prompt, opts) => {
    if ((opts?.label || '').startsWith('execute')) { calls += 1; throw transportFault({ timedOut: true }); }
    return 'ok';
  };
  const drv = await makeForemanDriver({
    agent: injected,
    reliability: { maxAttempts: 1, sleep: async () => {}, breaker: false },
  });
  const ctx = { wave: { n: 1, title: 't' }, reviewerIndex: 0, projectDir: '/p', iteration: 1 };
  for (let i = 0; i < 4; i++) await assert.rejects(() => drv.execute(ctx));
  assert.equal(calls, 4, 'breaker:false ⇒ every attempt reaches the agent (no fail-fast)');
});
