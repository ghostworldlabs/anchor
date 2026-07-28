// drivers/test/attest.test.mjs — the shared SR-5 stamp + Claude served-model discovery.
// Covers Phase-1 done-when (d1) model-less spawn => degraded, and (d2) a known-served-
// model envelope => model_attested:true (symmetric to the gemini-cli attestation test).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { attestStamp, hasAttestation, ATTEST_FIELDS } from '../attest.mjs';
import { parseClaudeFrames } from '../claude.mjs';

test('attestStamp: a real served id positively attests', () => {
  const s = attestStamp('claude-opus-4-8');
  assert.deepEqual(s, { model_served: 'claude-opus-4-8', model_attested: true, degraded: false });
});

test('attestStamp: null / empty / non-string => DEGRADED (never fabricate)', () => {
  for (const bad of [null, undefined, '', 0, {}, []]) {
    const s = attestStamp(bad);
    assert.deepEqual(s, { model_served: null, model_attested: false, degraded: true });
  }
});

test('hasAttestation: accepts a consistent stamp, rejects a self-contradictory one', () => {
  assert.equal(hasAttestation(attestStamp('m')), true);
  assert.equal(hasAttestation(attestStamp(null)), true);
  // attested:true with a null served model is fabrication — must be rejected.
  assert.equal(hasAttestation({ model_served: null, model_attested: true, degraded: false }), false);
  // missing a field
  assert.equal(hasAttestation({ model_served: 'm', model_attested: true }), false);
  assert.equal(hasAttestation(null), false);
  assert.equal(ATTEST_FIELDS.length, 3);
});

test('parseClaudeFrames (d2): a served-model envelope stamps model_attested:true', () => {
  const stdout = [
    JSON.stringify({ type: 'system', subtype: 'init', model: 'claude-opus-4-8' }),
    JSON.stringify({ type: 'assistant', message: { model: 'claude-opus-4-8', content: [{ type: 'text', text: 'hi' }] } }),
    JSON.stringify({ type: 'result', is_error: false, result: 'hi', duration_ms: 5, usage: { output_tokens: 3 }, total_cost_usd: 0.01, model: 'claude-opus-4-8' }),
  ].join('\n');
  const { text, rec } = parseClaudeFrames(stdout, { label: 'judge', cli_status: 0 });
  assert.equal(text, 'hi');
  assert.equal(rec.model_served, 'claude-opus-4-8');
  assert.equal(rec.model_attested, true);
  assert.equal(rec.degraded, false);
  assert.equal(rec.ok, true);
  assert.equal(rec.output_tokens, 3);
  assert.equal(hasAttestation(rec), true);
});

test('parseClaudeFrames (d1): an envelope with NO served model => DEGRADED', () => {
  const stdout = [
    JSON.stringify({ type: 'assistant', message: { content: [{ type: 'text', text: 'hi' }] } }),
    JSON.stringify({ type: 'result', is_error: false, result: 'hi' }),
  ].join('\n');
  const { rec } = parseClaudeFrames(stdout, { label: 'judge' });
  assert.equal(rec.model_served, null);
  assert.equal(rec.model_attested, false, 'no model field anywhere => cannot attest');
  assert.equal(rec.degraded, true);
  assert.equal(hasAttestation(rec), true, 'a degraded stamp is still well-formed');
});

test('parseClaudeFrames: the result envelope model is authoritative over assistant frames', () => {
  const stdout = [
    JSON.stringify({ type: 'assistant', message: { model: 'claude-haiku-4-5', content: [] } }),
    JSON.stringify({ type: 'result', is_error: false, result: 'x', model: 'claude-opus-4-8' }),
  ].join('\n');
  const { rec } = parseClaudeFrames(stdout);
  assert.equal(rec.model_served, 'claude-opus-4-8');
});
