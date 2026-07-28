// test/agent.test.mjs — Wave 1 gate for the live agent() seam. Drives the full
// schema/retry/abstain logic through an INJECTED transport (no real subprocess),
// and proves the live path is env-gated. Exercises REAL source in bin/agent.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../bin/crucible-lib.mjs';
import { makeAgentSeam, defaultRunClaude, extractJson } from '../bin/agent.mjs';

test('env-gated: the live transport refuses to spawn unless CRUCIBLE_AGENT_LIVE=1', () => {
  assert.throws(
    () => defaultRunClaude('hi', 'l', { env: {} }),
    (e) => e instanceof HaltError && /live agent seam is disabled/.test(e.reason),
  );
});

test('stubbable: plain prompt returns the transport text verbatim (no schema)', async () => {
  const { agent } = makeAgentSeam({ runClaude: async () => ({ text: 'hello world' }) });
  assert.equal(await agent('say hi'), 'hello world');
});

test('schema reply: a fenced JSON object is parsed and returned', async () => {
  const { agent } = makeAgentSeam({
    runClaude: async () => ({ text: '```json\n{"answerable":"yes","findings":[]}\n```' }),
  });
  const r = await agent('review', { schema: { type: 'object' } });
  assert.equal(r.answerable, 'yes');
  assert.deepEqual(r.findings, []);
});

test('schema reply: an unparseable first reply RETRIES once, then succeeds', async () => {
  let calls = 0;
  const { agent } = makeAgentSeam({
    runClaude: async () => {
      calls += 1;
      return { text: calls === 1 ? 'totally not json' : '{"answerable":"yes","findings":[]}' };
    },
  });
  const r = await agent('review', { schema: { type: 'object' } });
  assert.equal(calls, 2, 'one initial call + exactly one retry');
  assert.equal(r.answerable, 'yes');
});

test('schema reply: still unparseable after the retry => ABSTAIN (answerable:no, empty findings)', async () => {
  let calls = 0;
  const { agent } = makeAgentSeam({
    runClaude: async () => { calls += 1; return { text: 'no json here, ever' }; },
  });
  const r = await agent('review', { schema: { type: 'object' }, label: 'rev#1' });
  assert.equal(calls, 2, 'initial + one retry, then abstain (no infinite retry)');
  assert.equal(r.answerable, 'no');
  assert.deepEqual(r.findings, []);
  assert.match(r.note, /not parseable/i);
});

test('extractJson handles bare, fenced, and embedded JSON; rejects non-JSON', () => {
  assert.deepEqual(extractJson('{"a":1}'), { a: 1 });
  assert.deepEqual(extractJson('```json\n{"a":2}\n```'), { a: 2 });
  assert.deepEqual(extractJson('prose before {"a":3} prose after'), { a: 3 });
  // Hardened 2026-07-17 (cut transient reviewer abstains): trailing commas + arrays.
  assert.deepEqual(extractJson('{"a":4,}'), { a: 4 });
  assert.deepEqual(extractJson('{"list":[1,2,],}'), { list: [1, 2] });
  assert.deepEqual(extractJson('```json\n[{"a":5}]\n```'), [{ a: 5 }]);
  assert.deepEqual(extractJson('here you go: [1,2,3]'), [1, 2, 3]);
  assert.equal(extractJson('no object at all'), null);
  assert.equal(extractJson(null), null);
});
