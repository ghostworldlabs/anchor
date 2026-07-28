// test/synthesizer.test.mjs — Wave 3 gate for the persistent DIRECTOR.
// Drives the Synthesizer through an INJECTED (stubbed) agent — no subprocess —
// and proves: the Director STEERS but NEVER decides (no decide/lock/converge/
// reconcile; output is advisory), it carries the last round verbatim + a running
// direction log with Oranges suggesting, every prompt embeds the North Star, and
// the fresh-eyes COLD PASS is a new no-context instance whose ISOLATION ORACLE
// confirms an empty journal + no Director-context leak, with material divergence
// routed to the Judge. Exercises REAL source in bin/synthesizer.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  SYNTHESIZER_ROLE,
  DIRECTION_SCHEMA,
  FRESH_EYES_SCHEMA,
  makeSynthesizer,
  freshEyesColdPass,
  freshEyesIsolationOracle,
  reconcileFreshEyes,
} from '../bin/synthesizer.mjs';

const NORTH_STAR = 'NORTH-STAR-SENTINEL: ship a Foreman-ready plan that never drifts.';

/** A stub agent() that routes a scripted reply by the label prefix, recording calls. */
function routedAgent(byKind) {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    const label = opts.label || '';
    if (label.startsWith('synthesizer:fresh-eyes')) return byKind.freshEyes ?? { lean: 'unknown', concerns: [] };
    return byKind.direct ?? { lean: 'unknown', openDisputes: [], suggestions: [] };
  }
  agent.calls = calls;
  return agent;
}

// --- driver guard ----------------------------------------------------------

test('makeSynthesizer HALTs without an agent() function', () => {
  assert.throws(() => makeSynthesizer({}), (e) => e instanceof HaltError);
  assert.throws(() => makeSynthesizer({ agent: 'nope' }), (e) => e instanceof HaltError);
});

// --- Director ≠ decider ----------------------------------------------------

test('the Director NEVER decides: no decision authority, advisory output only', async () => {
  const agent = routedAgent({ direct: { lean: 'lockable', openDisputes: [], probingBrief: 'tighten C2', suggestions: ['add a rollback wave'] } });
  const synth = makeSynthesizer({ agent, northStar: NORTH_STAR });

  // By construction it carries no decision/reconcile method (Director ≠ decider).
  assert.equal(synth.isDecider, false);
  for (const forbidden of ['decide', 'lock', 'converge', 'reconcile', 'approve']) {
    assert.equal(typeof synth[forbidden], 'undefined', `Director must not expose ${forbidden}()`);
  }
  assert.equal(synth.role, SYNTHESIZER_ROLE);

  const dir = await synth.direct({ round: 0, verdict: { verdict: 'DRY' } });
  assert.equal(dir.advisory, true);
  assert.equal(dir.decides, false);
  assert.equal(dir.kind, 'direction');
  assert.equal(agent.calls[0].opts.schema, DIRECTION_SCHEMA);
});

// --- last round verbatim + running direction log + Oranges suggesting ------

test('the Director carries the LAST ROUND verbatim, accumulates a direction log, and surfaces Oranges suggestions', async () => {
  const agent = routedAgent({
    direct: { lean: 'not-lockable', openDisputes: ['C2 lock criteria vague'], riskRegister: ['silent default-fill'], probingBrief: 'press the lock gate', suggestions: ['define a per-wave oracle two steps ahead'] },
  });
  const synth = makeSynthesizer({ agent, northStar: NORTH_STAR });

  const verdict1 = { verdict: 'BLOCKED', blockers: [{ id: 'topic:lock-gate' }], round: 1 };
  const d1 = await synth.direct({ round: 1, verdict: verdict1 });
  assert.deepEqual(synth.snapshot().lastRound.verdict, verdict1, 'last round stored VERBATIM');
  assert.ok(d1.suggestions.length >= 1, 'Oranges suggesting is surfaced');

  await synth.direct({ round: 2, verdict: { verdict: 'DRY', round: 2 } });
  const snap = synth.snapshot();
  assert.equal(snap.journal.length, 2, 'the direction log accumulates across rounds');
  assert.deepEqual(snap.lastRound.verdict, { verdict: 'DRY', round: 2 }, 'last round advances and stays verbatim');

  // Every Director prompt embeds the North Star verbatim (§9).
  for (const c of agent.calls) assert.ok(c.prompt.includes(NORTH_STAR), 'North Star embedded in every Director prompt');
  // The position reflects the latest lean and the accumulated disputes.
  assert.equal(synth.position().lean, 'not-lockable');
  assert.ok(synth.position().openDisputes.includes('C2 lock criteria vague'));
});

// --- the fresh-eyes COLD PASS + isolation oracle ---------------------------

test('fresh-eyes cold pass is a NEW no-context instance; the isolation oracle confirms an empty journal + no leak', async () => {
  const DIRECTOR_SENTINEL = 'DIRECTOR-ONLY-SENTINEL: I already concluded this is lockable';
  const agent = routedAgent({
    direct: { lean: 'lockable', openDisputes: [], probingBrief: DIRECTOR_SENTINEL, suggestions: [] },
    freshEyes: { lean: 'lockable', concerns: [], note: 'concurs' },
  });
  const synth = makeSynthesizer({ agent, northStar: NORTH_STAR });
  await synth.direct({ round: 0, verdict: { verdict: 'DRY' } }); // Director now holds a position with a sentinel

  const cold = await freshEyesColdPass({ agent, transcripts: 'round transcript: three Sharks, no new blocker', northStar: NORTH_STAR });

  // A genuinely different instance.
  assert.notEqual(cold.instanceId, synth.instanceId);
  // The cold instance read with an EMPTY journal.
  assert.equal(cold.journalAtStart.length, 0);
  // Its prompt was schema-forced and embeds the North Star but NOT the Director's sentinel.
  const coldCall = agent.calls.find((c) => (c.opts.label || '').startsWith('synthesizer:fresh-eyes'));
  assert.equal(coldCall.opts.schema, FRESH_EYES_SCHEMA);
  assert.ok(coldCall.prompt.includes(NORTH_STAR));
  assert.ok(!coldCall.prompt.includes(DIRECTOR_SENTINEL), 'no Director context leaks into the cold prompt');

  const oracle = freshEyesIsolationOracle({ cold, directorSnapshot: synth.snapshot() });
  assert.equal(oracle.isolated, true, oracle.violations.join('; '));
  assert.equal(oracle.leaked.length, 0);
});

test('the isolation oracle FAILS on a non-empty cold journal or a leaked Director context (the oracle has teeth)', () => {
  const directorSnapshot = {
    instanceId: 'synthesizer#1',
    journal: [{ round: 0, lean: 'lockable', openDisputes: ['LEAKED-DISPUTE-XYZ'], probingBrief: '', riskRegister: [], suggestions: [] }],
  };
  // Non-empty journal at start ⇒ not isolated.
  const dirty = freshEyesIsolationOracle({ cold: { instanceId: 'synthesizer#2', journalAtStart: [{}], promptSent: 'clean' }, directorSnapshot });
  assert.equal(dirty.isolated, false);
  // Leaked Director context in the cold prompt ⇒ not isolated, and names the leak.
  const leaky = freshEyesIsolationOracle({
    cold: { instanceId: 'synthesizer#2', journalAtStart: [], promptSent: 'cold prompt mentioning LEAKED-DISPUTE-XYZ' },
    directorSnapshot,
  });
  assert.equal(leaky.isolated, false);
  assert.ok(leaky.leaked.includes('LEAKED-DISPUTE-XYZ'));
});

// --- divergence routes to the Judge (never reconciled by the Director) ------

test('Given the Director holds a prior position, when the fresh-eyes pass materially diverges, then it routes to the Judge', async () => {
  const agent = routedAgent({
    direct: { lean: 'lockable', openDisputes: [], probingBrief: 'looks done', suggestions: [] },
    freshEyes: { lean: 'not-lockable', concerns: [{ severity: 'BLOCKER', note: 'the lock gate is still ambiguous' }], note: 'I disagree' },
  });
  const synth = makeSynthesizer({ agent, northStar: NORTH_STAR });
  await synth.direct({ round: 1, verdict: { verdict: 'DRY' } });
  assert.equal(synth.position().lean, 'lockable', 'Director thinks it is lockable');

  const cold = await freshEyesColdPass({ agent, transcripts: 'the transcript', northStar: NORTH_STAR });
  const oracle = freshEyesIsolationOracle({ cold, directorSnapshot: synth.snapshot() });
  assert.equal(oracle.isolated, true);

  // Reconcile is a FREE function, not a Director method — the anchored Director
  // cannot reconcile its own anti-anchoring pass.
  assert.equal(typeof synth.reconcileFreshEyes, 'undefined');
  const r = reconcileFreshEyes({ directorPosition: synth.position(), freshEyes: cold.assessment });
  assert.equal(r.diverged, true);
  assert.equal(r.material, true);
  assert.equal(r.route, 'judge', 'material divergence is surfaced to the decider, not reconciled by the Director');
});

test('a non-material divergence recommends a challenge round; concurrence routes to concur', () => {
  const challenge = reconcileFreshEyes({ directorPosition: { lean: 'not-lockable' }, freshEyes: { lean: 'lockable', concerns: [] } });
  assert.equal(challenge.diverged, true);
  assert.equal(challenge.material, false);
  assert.equal(challenge.route, 'challenge-round');

  const concur = reconcileFreshEyes({ directorPosition: { lean: 'lockable' }, freshEyes: { lean: 'lockable', concerns: [] } });
  assert.equal(concur.diverged, false);
  assert.equal(concur.route, 'concur');
});
