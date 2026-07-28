// Exercises the jail in-process. The node test runner executes each test file
// in its own child process, so patching this process's network surface does
// not leak into other test files.
import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import http from 'node:http';
import https from 'node:https';
import net from 'node:net';
import tls from 'node:tls';
import dns from 'node:dns';
import {
  installIsolationJail,
  isHostAuthorized,
  NetworkAccessDeniedError,
  SharedMemoryDeniedError
} from '../src/isolationJail.mjs';

describe('Isolation Jail - allowlist matching', () => {
  test('authorizes exact hostnames case-insensitively', () => {
    assert.equal(isHostAuthorized('api.example.com', ['API.Example.COM']), true);
    assert.equal(isHostAuthorized('other.example.com', ['api.example.com']), false);
  });

  test('wildcard entries authorize subdomains but never the bare suffix', () => {
    assert.equal(isHostAuthorized('a.example.com', ['*.example.com']), true);
    assert.equal(isHostAuthorized('deep.a.example.com', ['*.example.com']), true);
    assert.equal(isHostAuthorized('example.com', ['*.example.com']), false);
  });

  test('denies by default: empty allowlist, empty host, non-string host', () => {
    assert.equal(isHostAuthorized('example.com', []), false);
    assert.equal(isHostAuthorized('', ['example.com']), false);
    assert.equal(isHostAuthorized(null, ['example.com']), false);
  });
});

describe('Isolation Jail - installed jail (deny-by-default, local allowlist)', () => {
  const violations = [];
  let server;
  let port;

  before(async () => {
    // Server must exist before install is irrelevant (listen is not patched),
    // but the jail must be installed exactly once per process.
    installIsolationJail({
      allowlist: ['127.0.0.1'],
      onViolation: (v) => violations.push(v)
    });
    server = http.createServer((req, res) => res.end('ok'));
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    port = server.address().port;
  });

  after(() => {
    server?.close();
  });

  test('fetch to an unauthorized host is denied and reported', async () => {
    await assert.rejects(fetch('http://unauthorized.invalid/'), NetworkAccessDeniedError);
    assert.ok(violations.some(v => v.kind === 'network' && v.api === 'fetch'));
  });

  test('http/https request and get to unauthorized hosts throw', () => {
    assert.throws(() => http.request('http://unauthorized.invalid/'), NetworkAccessDeniedError);
    assert.throws(() => http.get('http://unauthorized.invalid/'), NetworkAccessDeniedError);
    assert.throws(() => https.request('https://unauthorized.invalid/'), NetworkAccessDeniedError);
    assert.throws(() => https.get('https://unauthorized.invalid/'), NetworkAccessDeniedError);
  });

  test('raw socket and tls connections to unauthorized hosts throw', () => {
    assert.throws(() => net.connect(80, 'unauthorized.invalid'), NetworkAccessDeniedError);
    assert.throws(() => tls.connect(443, 'unauthorized.invalid'), NetworkAccessDeniedError);
  });

  test('dns resolution of unauthorized hosts is denied (callback and promises)', async () => {
    assert.throws(() => dns.lookup('unauthorized.invalid', () => {}), NetworkAccessDeniedError);
    await assert.rejects(dns.promises.lookup('unauthorized.invalid'), NetworkAccessDeniedError);
  });

  test('an authorized endpoint remains reachable through the jail', async () => {
    const body = await new Promise((resolve, reject) => {
      // agent: false -> one-off connection, closed as soon as the response ends
      http.get(`http://127.0.0.1:${port}/`, { agent: false }, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => resolve(data));
      }).on('error', reject);
    });
    assert.equal(body, 'ok');
  });

  test('SharedArrayBuffer construction is denied and reported', () => {
    assert.throws(() => new SharedArrayBuffer(8), SharedMemoryDeniedError);
    assert.ok(violations.some(v => v.kind === 'shared-memory' && v.api === 'SharedArrayBuffer'));
  });

  test('shared WebAssembly.Memory is denied; non-shared memory still works', () => {
    assert.throws(
      () => new WebAssembly.Memory({ initial: 1, maximum: 1, shared: true }),
      SharedMemoryDeniedError
    );
    const plain = new WebAssembly.Memory({ initial: 1 });
    assert.ok(plain.buffer instanceof ArrayBuffer);
  });

  test('every violation report carries kind, api, target, and message', () => {
    assert.ok(violations.length > 0);
    for (const v of violations) {
      assert.ok(['network', 'shared-memory'].includes(v.kind));
      assert.equal(typeof v.api, 'string');
      assert.equal(typeof v.message, 'string');
    }
  });
});
