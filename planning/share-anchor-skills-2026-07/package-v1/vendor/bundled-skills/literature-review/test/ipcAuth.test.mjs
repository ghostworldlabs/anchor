import { test, describe } from 'node:test';
import assert from 'node:assert';
import {
  createIpcSecret,
  canonicalStringify,
  signEvent,
  verifyEvent
} from '../src/ipcAuth.mjs';

describe('IPC Auth - canonical stringify', () => {
  test('produces identical output regardless of key insertion order', () => {
    const a = { b: 1, a: { z: true, y: [1, 2] } };
    const b = { a: { y: [1, 2], z: true }, b: 1 };
    assert.equal(canonicalStringify(a), canonicalStringify(b));
  });

  test('drops undefined object members and encodes JSON semantics', () => {
    assert.equal(canonicalStringify({ a: undefined, b: 2 }), '{"b":2}');
    assert.equal(canonicalStringify([1, undefined, 'x']), '[1,null,"x"]');
    assert.equal(canonicalStringify(null), 'null');
    assert.equal(canonicalStringify(NaN), 'null');
  });
});

describe('IPC Auth - sign and verify', () => {
  const secret = createIpcSecret();
  const event = {
    v: 1,
    dir: 'w2p',
    workerId: 'lrw-abc123',
    seq: 0,
    ts: 1750000000000,
    type: 'state',
    payload: { state: 'running' }
  };

  test('a signed event verifies against the same secret', () => {
    const signed = signEvent(event, secret);
    assert.equal(typeof signed.sig, 'string');
    assert.equal(verifyEvent(signed, secret), true);
  });

  test('a tampered payload fails verification', () => {
    const signed = signEvent(event, secret);
    const tampered = { ...signed, payload: { state: 'completed' } };
    assert.equal(verifyEvent(tampered, secret), false);
  });

  test('a tampered envelope field (seq, dir, workerId) fails verification', () => {
    const signed = signEvent(event, secret);
    assert.equal(verifyEvent({ ...signed, seq: 99 }, secret), false);
    assert.equal(verifyEvent({ ...signed, dir: 'p2w' }, secret), false);
    assert.equal(verifyEvent({ ...signed, workerId: 'lrw-other' }, secret), false);
  });

  test('an event signed with a different secret fails verification', () => {
    const signed = signEvent(event, createIpcSecret());
    assert.equal(verifyEvent(signed, secret), false);
  });

  test('missing, empty, or malformed signatures fail verification safely', () => {
    assert.equal(verifyEvent(event, secret), false);
    assert.equal(verifyEvent({ ...event, sig: '' }, secret), false);
    assert.equal(verifyEvent({ ...event, sig: 'not-hex!!' }, secret), false);
    assert.equal(verifyEvent(null, secret), false);
    assert.equal(verifyEvent('a string', secret), false);
  });
});
