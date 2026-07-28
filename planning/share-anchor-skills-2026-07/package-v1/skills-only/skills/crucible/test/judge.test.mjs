// test/judge.test.mjs — Wave 3 gate for the model-side DECIDER.
// Drives the Judge through an INJECTED (stubbed) agent — no subprocess — and
// proves: the Judge DECIDES from injected evidence (and only that evidence), it
// is context-free (its prompt says so and carries no Director journal), the
// per-role model stamp records Default vs cross-model Enhanced provenance, and an
// undecidable reply HALTs for the human rather than silently passing. Exercises
// REAL source in bin/judge.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  JUDGE_ROLE,
  JUDGE_SCHEMA,
  stampRole,
  defaultProbeCrossModel,
  selectJudgeModel,
  makeJudge,
} from '../bin/judge.mjs';

const NORTH_STAR = 'NORTH-STAR-SENTINEL: ship a Foreman-ready plan that never drifts.';

/** A stub agent() that returns a scripted reply and records every (prompt, opts). */
function scriptedAgent(reply) {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    return typeof reply === 'function' ? reply(prompt, opts) : reply;
  }
  agent.calls = calls;
  return agent;
}

// --- model stamp -----------------------------------------------------------

test('stampRole requires a role and records cross-model only for reachable Enhanced', () => {
  assert.throws(() => stampRole({}), (e) => e instanceof HaltError);
  const def = stampRole({ role: 'Judge' });
  assert.deepEqual(def, { role: 'Judge', model: 'claude', family: 'claude', mode: 'default', cross_model: false });
  // Enhanced but not reachable ⇒ still not genuine cross-model independence.
  assert.equal(stampRole({ role: 'Judge', mode: 'enhanced', reachable: false }).cross_model, false);
  // Enhanced AND a reachable different family ⇒ cross-model.
  assert.equal(stampRole({ role: 'Judge', model: 'gemini', family: 'gemini', mode: 'enhanced', reachable: true }).cross_model, true);
});

// --- judge-model selection (Default vs Enhanced) ---------------------------

test('selectJudgeModel: default probe ⇒ same-model Default persona', () => {
  assert.equal(defaultProbeCrossModel(), null);
  const sel = selectJudgeModel({ authorFamily: 'claude' });
  assert.deepEqual(sel, { model: 'claude', family: 'claude', mode: 'default', reachable: false });
});

test('selectJudgeModel: a reachable DIFFERENT family ⇒ cross-model Enhanced', () => {
  const sel = selectJudgeModel({ authorFamily: 'claude', probe: () => ({ model: 'gemini-2.5', family: 'gemini' }) });
  assert.equal(sel.mode, 'enhanced');
  assert.equal(sel.family, 'gemini');
  assert.equal(sel.reachable, true);
});

test('selectJudgeModel: a reachable SAME family is not cross-model ⇒ stays Default', () => {
  const sel = selectJudgeModel({ authorFamily: 'claude', probe: () => ({ model: 'claude-x', family: 'claude' }) });
  assert.equal(sel.mode, 'default');
  assert.equal(sel.reachable, false);
});

// --- driver guard ----------------------------------------------------------

test('makeJudge HALTs without an agent() function', () => {
  assert.throws(() => makeJudge({}), (e) => e instanceof HaltError);
  assert.throws(() => makeJudge({ agent: 'nope' }), (e) => e instanceof HaltError);
});

// --- the Judge DECIDES from injected evidence ------------------------------

test('the Judge DECIDES NOT_CONVERGED from an injected blocker, embedding all evidence in-prompt', async () => {
  const agent = scriptedAgent({ decision: 'NOT_CONVERGED', reasons: ['open blocker'], blocking: [{ id: 'b1', severity: 'BLOCKER' }] });
  const judge = makeJudge({ agent });
  const v = await judge.decide({
    northStar: NORTH_STAR,
    findings: [{ id: 'b1', severity: 'BLOCKER', message: 'FINDING-SENTINEL: lock gate underspecified' }],
    acceptanceCriteria: ['CRITERION-SENTINEL: every wave has a done-when'],
    round: 1,
  });

  assert.equal(v.decision, 'NOT_CONVERGED');
  assert.equal(v.lockable, false);
  // The decision was forced through the schema and is stamped.
  assert.equal(agent.calls.length, 1);
  assert.equal(agent.calls[0].opts.schema, JUDGE_SCHEMA);
  assert.equal(v.stamp.role, JUDGE_ROLE);
  // ALL evidence is placed in-prompt (the Judge decides only from this).
  const p = agent.calls[0].prompt;
  assert.ok(p.includes(NORTH_STAR), 'North Star embedded verbatim');
  assert.ok(p.includes('FINDING-SENTINEL'), 'the finding is in-prompt');
  assert.ok(p.includes('CRITERION-SENTINEL'), 'the acceptance criteria are in-prompt');
});

test('the Judge DECIDES CONVERGED on a clean round ⇒ lockable', async () => {
  const agent = scriptedAgent({ decision: 'CONVERGED', reasons: ['dry round, no open blocker'] });
  const judge = makeJudge({ agent });
  const v = await judge.decide({ northStar: NORTH_STAR, findings: [], acceptanceCriteria: [], round: 2 });
  assert.equal(v.decision, 'CONVERGED');
  assert.equal(v.lockable, true);
});

test('the Judge is CONTEXT-FREE: its prompt declares no prior context and carries no Director journal', async () => {
  const agent = scriptedAgent({ decision: 'CONVERGED' });
  const judge = makeJudge({ agent });
  await judge.decide({ northStar: NORTH_STAR, findings: [], acceptanceCriteria: [] });
  const p = agent.calls[0].prompt;
  assert.match(p, /NO prior context/i);
  // The Judge object exposes no way to inject a Synthesizer/Director — it can only
  // see the evidence handed to decide().
  assert.equal(typeof judge.decide, 'function');
  assert.ok(!('synthesizer' in judge) && !('director' in judge), 'Judge holds no Director reference');
  assert.ok(!p.includes('DIRECTOR-ONLY'), 'no Director-only context appears in the Judge prompt');
});

test('an undecidable (abstained) judge reply HALTs for human review — never a silent pass', async () => {
  // The Wave-1 seam returns {answerable:no, findings:[]} when unparseable after retry.
  const agent = scriptedAgent({ answerable: 'no', findings: [] });
  const judge = makeJudge({ agent });
  const v = await judge.decide({ northStar: NORTH_STAR });
  assert.equal(v.decision, 'HALT');
  assert.equal(v.lockable, false);
  assert.equal(v.halted, true);
});

// --- cross-model stamp flows through the verdict ---------------------------

test('a cross-model Enhanced Judge stamps the verdict with the different family', async () => {
  const agent = scriptedAgent({ decision: 'CONVERGED' });
  const judge = makeJudge({ agent, authorFamily: 'claude', probeCrossModel: () => ({ model: 'gpt-x', family: 'gpt' }) });
  assert.equal(judge.stamp.cross_model, true);
  assert.equal(judge.stamp.family, 'gpt');
  const v = await judge.decide({ northStar: NORTH_STAR });
  assert.equal(v.stamp.cross_model, true);
  assert.equal(v.stamp.model, 'gpt-x');
});
