import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyAgentExit, shouldRetryTransport } from '../bin/lifecycle-launch.mjs';

test('classifyAgentExit: timeout is transport', () => {
  assert.equal(classifyAgentExit({ timedOut: true }), 'transport_timeout');
});

test('classifyAgentExit: signal is transport', () => {
  assert.equal(classifyAgentExit({ signal: 'SIGKILL', code: null }), 'transport_signal');
});

test('classifyAgentExit: nonzero code is content', () => {
  assert.equal(classifyAgentExit({ code: 1 }), 'content_nonzero');
});

test('classifyAgentExit: zero is ok', () => {
  assert.equal(classifyAgentExit({ code: 0 }), 'ok');
});

test('shouldRetryTransport only for transport classes', () => {
  assert.equal(shouldRetryTransport('transport_timeout'), true);
  assert.equal(shouldRetryTransport('content_nonzero'), false);
  assert.equal(shouldRetryTransport('ok'), false);
});
