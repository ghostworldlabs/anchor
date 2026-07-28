// drivers/test/backends.test.mjs — Wave 5 gate for the gemini/openai/grok backends.
//
// Everything here runs with MOCKED transports (an injected `fetchImpl`) — NO real
// network and NO API keys. The tests prove, for each driver:
//   * request shaping     — URL, method, auth header, model, and the native
//     structured-output knob (response_format / responseSchema) are correct;
//   * structured-output parsing — a schema reply in the backend's native envelope
//     is parsed and returned as an object; a no-schema call returns plain text;
//   * retry-then-ABSTAIN  — an unparseable reply retries exactly once, then either
//     succeeds or ABSTAINs (answerable:no) — identical to the Claude backend;
//   * key gate            — with no key and no injected transport the driver HALTs,
//     and the LIVE smoke test SKIPS (never fails) when the key is absent.
// Also: TRIO_DRIVER selects the right backend and the capability matrix is correct.
//
// Exercises REAL source in drivers/{index,gemini,openai,grok,_openai-compat,_seam}.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../../foreman/bin/foreman-lib.mjs';
import {
  runAgent, getDriver, listDrivers, capabilityMatrix,
  geminiDriver, openaiDriver, grokDriver,
} from '../index.mjs';
import { buildChatRequest, parseChatResponse } from '../_openai-compat.mjs';
import { buildGeminiRequest, parseGeminiResponse } from '../gemini.mjs';

// --- mock-transport helpers ----------------------------------------------------

/** A fetch-shaped mock. `next` returns the body object for each successive call. */
function mockFetch(next, { ok = true, status = 200, capture } = {}) {
  let n = 0;
  return async (url, init) => {
    const body = JSON.parse(init.body);
    if (capture) capture.calls.push({ url, init, body });
    const payload = typeof next === 'function' ? next(n++, body) : next;
    return {
      ok, status,
      async json() { return payload; },
      async text() { return JSON.stringify(payload); },
    };
  };
}

/** Wrap an assistant text reply in the OpenAI/Grok Chat Completions envelope. */
const chatEnvelope = (text) => ({ choices: [{ message: { content: text } }] });
/** Wrap an assistant text reply in the Gemini generateContent envelope. */
const geminiEnvelope = (text) => ({ candidates: [{ content: { parts: [{ text }] } }] });

const SCHEMA = { type: 'object', properties: { answerable: { type: 'string' } } };

// --- pure shaping functions ----------------------------------------------------

test('openai-compat: buildChatRequest shapes URL, auth, model + json_schema', () => {
  const { url, init } = buildChatRequest({
    prompt: 'hello', schema: SCHEMA, model: 'gpt-test', apiKey: 'short-key', baseUrl: 'https://api.openai.com/v1',
  });
  assert.equal(url, 'https://api.openai.com/v1/chat/completions');
  assert.equal(init.method, 'POST');
  assert.equal(init.headers.authorization, 'Bearer short-key');
  const body = JSON.parse(init.body);
  assert.equal(body.model, 'gpt-test');
  assert.deepEqual(body.messages, [{ role: 'user', content: 'hello' }]);
  assert.equal(body.response_format.type, 'json_schema');
  assert.deepEqual(body.response_format.json_schema.schema, SCHEMA);
});

test('openai-compat: no schema omits response_format; parseChatResponse extracts text', () => {
  const { init } = buildChatRequest({ prompt: 'hi', model: 'm', apiKey: 'k', baseUrl: 'https://x/v1' });
  assert.equal(JSON.parse(init.body).response_format, undefined);
  assert.equal(parseChatResponse(chatEnvelope('pong')), 'pong');
  assert.equal(parseChatResponse({}), '');
});

test('gemini: buildGeminiRequest shapes endpoint, key header + responseSchema', () => {
  const { url, init } = buildGeminiRequest({ prompt: 'hello', schema: SCHEMA, model: 'gemini-test', apiKey: 'short-key' });
  assert.equal(url, 'https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent');
  assert.equal(init.headers['x-goog-api-key'], 'short-key');
  const body = JSON.parse(init.body);
  assert.deepEqual(body.contents, [{ role: 'user', parts: [{ text: 'hello' }] }]);
  assert.equal(body.generationConfig.responseMimeType, 'application/json');
  assert.deepEqual(body.generationConfig.responseSchema, SCHEMA);
});

test('gemini: no schema omits generationConfig; parseGeminiResponse joins parts', () => {
  const { init } = buildGeminiRequest({ prompt: 'hi', model: 'm', apiKey: 'k' });
  assert.equal(JSON.parse(init.body).generationConfig, undefined);
  assert.equal(parseGeminiResponse(geminiEnvelope('pong')), 'pong');
  assert.equal(parseGeminiResponse({}), '');
});

// --- per-driver behavior through runAgent (mocked transport) -------------------

const CASES = [
  {
    name: 'openai', driver: 'openai',
    envelope: chatEnvelope,
    expectUrl: 'https://api.openai.com/v1/chat/completions',
    modelInBody: 'gpt-4o', // Chat Completions carries the model in the body
    structuredKnob: (body) => body.response_format?.type === 'json_schema',
  },
  {
    name: 'grok', driver: 'grok',
    envelope: chatEnvelope,
    expectUrl: 'https://api.x.ai/v1/chat/completions',
    modelInBody: 'grok-2-latest',
    structuredKnob: (body) => body.response_format?.type === 'json_schema',
  },
  {
    name: 'gemini', driver: 'gemini',
    envelope: geminiEnvelope,
    // Gemini encodes the model in the URL (verified by expectUrl), not the body.
    expectUrl: 'https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent',
    modelInBody: null,
    structuredKnob: (body) => body.generationConfig?.responseMimeType === 'application/json',
  },
];

for (const c of CASES) {
  test(`${c.name}: runAgent (no schema) returns plain text + shapes the request`, async () => {
    const capture = { calls: [] };
    const out = await runAgent({
      driver: c.driver, prompt: 'say pong',
      apiKey: 'short-key', env: {}, fetchImpl: mockFetch(c.envelope('pong'), { capture }),
    });
    assert.equal(out, 'pong');
    assert.equal(capture.calls.length, 1);
    assert.equal(capture.calls[0].url, c.expectUrl);
    assert.equal(capture.calls[0].init.method, 'POST');
    if (c.modelInBody) assert.equal(capture.calls[0].body.model, c.modelInBody);
  });

  test(`${c.name}: runAgent + schema parses native JSON output (structured knob set)`, async () => {
    const capture = { calls: [] };
    const out = await runAgent({
      driver: c.driver, prompt: 'review', schema: SCHEMA,
      apiKey: 'short-key', env: {}, fetchImpl: mockFetch(c.envelope('{"answerable":"yes"}'), { capture }),
    });
    assert.equal(out.answerable, 'yes');
    assert.ok(c.structuredKnob(capture.calls[0].body), 'native structured-output knob present in request');
  });

  test(`${c.name}: schema reply unparseable -> retry once -> success`, async () => {
    const capture = { calls: [] };
    const out = await runAgent({
      driver: c.driver, prompt: 'review', schema: SCHEMA,
      apiKey: 'short-key', env: {},
      fetchImpl: mockFetch((i) => c.envelope(i === 0 ? 'not json' : '{"answerable":"yes"}'), { capture }),
    });
    assert.equal(capture.calls.length, 2, 'one initial call + exactly one retry');
    assert.equal(out.answerable, 'yes');
  });

  test(`${c.name}: schema reply unparseable twice -> ABSTAIN (answerable:no)`, async () => {
    const capture = { calls: [] };
    const out = await runAgent({
      driver: c.driver, prompt: 'review', schema: SCHEMA, label: `rev:${c.name}`,
      apiKey: 'short-key', env: {}, fetchImpl: mockFetch(c.envelope('never json'), { capture }),
    });
    assert.equal(capture.calls.length, 2, 'initial + one retry, then abstain (no infinite retry)');
    assert.equal(out.answerable, 'no');
    assert.deepEqual(out.findings, []);
    assert.match(out.note, /not parseable/i);
  });

  test(`${c.name}: a non-2xx response HALTs with the status`, async () => {
    await assert.rejects(
      runAgent({
        driver: c.driver, prompt: 'x', apiKey: 'short-key', env: {},
        fetchImpl: mockFetch({ error: 'boom' }, { ok: false, status: 500 }),
      }),
      (e) => e instanceof HaltError && /HTTP 500/.test(e.reason),
    );
  });

  test(`${c.name}: no key AND no injected transport HALTs (never a keyless request)`, async () => {
    await assert.rejects(
      runAgent({ driver: c.driver, prompt: 'x', env: {} }),
      (e) => e instanceof HaltError && /not set/i.test(e.reason),
    );
  });
}

// --- selection + capability matrix --------------------------------------------

test('selection: TRIO_DRIVER picks gemini/openai/grok; explicit driver arg overrides', () => {
  assert.equal(getDriver(null, { TRIO_DRIVER: 'gemini' }), geminiDriver);
  assert.equal(getDriver(null, { TRIO_DRIVER: 'openai' }), openaiDriver);
  assert.equal(getDriver(null, { TRIO_DRIVER: 'grok' }), grokDriver);
  // explicit overrides the env var, and the default (no env) stays claude.
  assert.equal(getDriver('grok', { TRIO_DRIVER: 'gemini' }).name, 'grok');
  assert.equal(getDriver(null, {}).name, 'claude');
});

test('capability matrix: lists all four backends with correct profiles', () => {
  for (const n of ['claude', 'gemini', 'openai', 'grok']) {
    assert.ok(listDrivers().includes(n), `${n} registered`);
  }
  const m = capabilityMatrix();
  const by = Object.fromEntries(m.map((r) => [r.name, r]));
  assert.equal(by.claude.subAgentCapable, true, 'only the CLI backend spawns real sub-agents');
  assert.equal(by.gemini.subAgentCapable, false);
  assert.equal(by.openai.subAgentCapable, false);
  assert.equal(by.grok.subAgentCapable, false);
  // every backend declares HOW it does structured output.
  for (const r of m) assert.ok(r.structuredOutput && r.structuredOutput !== 'unknown', `${r.name} declares structuredOutput`);
  assert.match(by.claude.structuredOutput, /cli-subagent/i);
  assert.match(by.openai.structuredOutput, /json/i);
});

// --- live smoke tests: SKIP (never fail) when the key is absent ----------------

test('openai live smoke', { skip: process.env.OPENAI_API_KEY ? false : 'OPENAI_API_KEY not set' }, async () => {
  const out = await runAgent({ driver: 'openai', prompt: 'Reply with the single word: pong' });
  assert.match(String(out), /pong/i);
});

test('grok live smoke', { skip: process.env.XAI_API_KEY ? false : 'XAI_API_KEY not set' }, async () => {
  const out = await runAgent({ driver: 'grok', prompt: 'Reply with the single word: pong' });
  assert.match(String(out), /pong/i);
});

test('gemini live smoke', { skip: process.env.GEMINI_API_KEY ? false : 'GEMINI_API_KEY not set' }, async () => {
  const out = await runAgent({ driver: 'gemini', prompt: 'Reply with the single word: pong' });
  assert.match(String(out), /pong/i);
});
