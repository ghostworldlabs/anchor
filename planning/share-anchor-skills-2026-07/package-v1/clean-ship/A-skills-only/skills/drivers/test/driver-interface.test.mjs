// drivers/test/driver-interface.test.mjs — Wave 4 gate for the pluggable driver
// abstraction. Proves the `runAgent` seam + registry dispatch to the Claude default
// (no subprocess: an injected `runClaude` stub drives the real seam), that the
// Claude backend's schema/retry/abstain behavior is preserved end-to-end, that
// `TRIO_DRIVER`/explicit selection + custom registration work, that an unknown
// driver HALTs, and that Foreman's `{execute,review,fix}` seam routes through the
// registry. Exercises REAL source in drivers/index.mjs + drivers/claude.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../../foreman/bin/foreman-lib.mjs';
import {
  runAgent, getDriver, listDrivers, registerDriver, makeForemanDriver, claudeDriver,
} from '../index.mjs';

test('registry: claude is registered and is the default backend', () => {
  assert.ok(listDrivers().includes('claude'), 'claude is in the registry');
  // TRIO_DRIVER unset (passed env without it) => default resolves to claude.
  assert.equal(getDriver(null, {}), claudeDriver);
  assert.equal(claudeDriver.name, 'claude');
  assert.equal(claudeDriver.subAgentCapable, true);
});

test('TRIO_DRIVER unset: runAgent dispatches to the Claude driver (plain text)', async () => {
  // Inject a stub transport so the Claude seam runs with no subprocess.
  const out = await runAgent({
    prompt: 'say hi',
    runClaude: async () => ({ text: 'hello world' }),
  });
  assert.equal(out, 'hello world');
});

test('runAgent + schema: a fenced JSON reply is parsed and returned (Claude seam)', async () => {
  const out = await runAgent({
    prompt: 'review',
    schema: { type: 'object' },
    runClaude: async () => ({ text: '```json\n{"answerable":"yes","findings":[]}\n```' }),
  });
  assert.equal(out.answerable, 'yes');
  assert.deepEqual(out.findings, []);
});

test('runAgent + schema: unparseable first reply RETRIES once then succeeds', async () => {
  let calls = 0;
  const out = await runAgent({
    prompt: 'review',
    schema: { type: 'object' },
    runClaude: async () => {
      calls += 1;
      return { text: calls === 1 ? 'not json at all' : '{"answerable":"yes","findings":[]}' };
    },
  });
  assert.equal(calls, 2, 'one initial call + exactly one retry');
  assert.equal(out.answerable, 'yes');
});

test('runAgent + schema: still unparseable after retry => ABSTAIN (answerable:no)', async () => {
  let calls = 0;
  const out = await runAgent({
    prompt: 'review',
    schema: { type: 'object' },
    label: 'rev#1',
    runClaude: async () => { calls += 1; return { text: 'never json' }; },
  });
  assert.equal(calls, 2, 'initial + one retry, then abstain (no infinite retry)');
  assert.equal(out.answerable, 'no');
  assert.deepEqual(out.findings, []);
  assert.match(out.note, /not parseable/i);
});

test('registry: a custom backend can be registered and selected explicitly', async () => {
  const seen = [];
  registerDriver({
    name: 'mock-test-backend',
    subAgentCapable: false,
    async runAgent({ prompt }) { seen.push(prompt); return `mock:${prompt}`; },
  });
  assert.ok(listDrivers().includes('mock-test-backend'));
  const out = await runAgent({ driver: 'mock-test-backend', prompt: 'ping' });
  assert.equal(out, 'mock:ping');
  assert.deepEqual(seen, ['ping']);
});

test('selection: TRIO_DRIVER env selects the backend; explicit arg overrides it', () => {
  registerDriver({ name: 'mock-env-backend', runAgent: async () => 'env' });
  // env var picks the backend...
  assert.equal(getDriver(null, { TRIO_DRIVER: 'mock-env-backend' }).name, 'mock-env-backend');
  // ...and an explicit name overrides the env var.
  assert.equal(getDriver('claude', { TRIO_DRIVER: 'mock-env-backend' }).name, 'claude');
});

test('unknown driver HALTs (no silent fallback to claude)', () => {
  assert.throws(
    () => getDriver('no-such-driver', {}),
    (e) => e instanceof HaltError && /unknown trio driver "no-such-driver"/.test(e.reason),
  );
  assert.throws(() => registerDriver({ name: 'x' }), TypeError);
});

test('foreman seam: makeForemanDriver builds {execute,review,fix} via the Claude backend', async () => {
  // No injected agent => the seam's agent is built from the registry-selected
  // backend; a stub runClaude keeps it subprocess-free.
  const drv = await makeForemanDriver({
    runClaude: async (_p, _l) => ({ text: '{"answerable":"yes","findings":[{"severity":"MAJOR","file":"a.js","line":1,"rule":"x"}]}' }),
  });
  const ctx = { wave: { n: 1, title: 't' }, reviewerIndex: 0, projectDir: '/p', iteration: 1 };
  assert.equal((await drv.execute(ctx)).note, 'agent execute complete');
  const rv = await drv.review(ctx, { artifact_path: '/p/.foreman/g.json', exit_code: 1, tap: { pass: 2, tests: 3 } });
  assert.equal(rv.answerable, 'yes');
  assert.equal(rv.findings.length, 1);
  assert.equal(rv.claim, undefined, 'production review carries no forgeable claim');
  assert.equal((await drv.fix(ctx, { artifact_path: '/p/.foreman/g.json' }, [])).note, 'agent fix complete');
});

test('foreman seam: makeForemanDriver routes an INJECTED agent through unchanged', async () => {
  const labels = [];
  const injected = async (prompt, opts) => {
    labels.push(opts?.label || 'execute');
    if (opts?.schema) return { answerable: 'yes', findings: [] };
    return 'ok';
  };
  const drv = await makeForemanDriver({ agent: injected });
  const ctx = { wave: { n: 2, title: 't' }, reviewerIndex: 0, projectDir: '/p', iteration: 1 };
  assert.equal((await drv.execute(ctx)).note, 'agent execute complete');
  const rv = await drv.review(ctx, { artifact_path: '/p/.foreman/g.json', exit_code: 0, tap: { pass: 3, tests: 3 } });
  assert.equal(rv.answerable, 'yes');
  assert.ok(labels.some((l) => l.startsWith('execute:w2')), 'injected agent received the execute label');
});

test('belowFrontierClaudeModel is the standard (one-below-frontier) tier, not hard-coded frontier (2026-07-17)', async () => {
  const { belowFrontierClaudeModel } = await import('../claude.mjs');
  assert.equal(belowFrontierClaudeModel(), 'claude-opus-4-8');
});

test('runAgent: a seat_unavailable failure fails OVER to Claude (model-integrity rule, 2026-07-17)', async () => {
  // A non-Claude backend that cannot deliver its attested model (agy silently served GPT-OSS).
  const fake = {
    name: 'fake-gemini-fo',
    runAgent: async () => {
      const e = new Error('Gemini attestation/transport failed: model_substituted');
      e.seat_unavailable = true; e.requested_model = 'Gemini 3.1 Pro (High)'; e.served_model = 'GPT-OSS 120B';
      throw e;
    },
  };
  registerDriver(fake);
  const out = await runAgent({
    driver: 'fake-gemini-fo', prompt: 'review', schema: { type: 'object' }, label: 'shark:r1',
    runClaude: async () => ({ text: '{"answerable":"yes","findings":[]}' }),
  });
  assert.equal(out.answerable, 'yes', 'the seat failed over to Claude and returned its result (no blind GPT-OSS, no throw)');
});
