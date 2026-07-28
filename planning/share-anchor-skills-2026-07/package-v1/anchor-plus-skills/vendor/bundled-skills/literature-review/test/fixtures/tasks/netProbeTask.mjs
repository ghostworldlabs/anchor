// Test fixture: attempts every network API surface from inside the jail and
// reports whether each attempt was blocked (it must be, with an empty allowlist).
import http from 'node:http';
import net from 'node:net';
import dns from 'node:dns';

async function probe(fn) {
  try {
    await fn();
    return { blocked: false };
  } catch (err) {
    return { blocked: true, name: err.name, message: err.message };
  }
}

export default async function run() {
  return {
    fetch: await probe(() => fetch('http://unauthorized.example/')),
    http: await probe(async () => http.request('http://unauthorized.example/')),
    net: await probe(async () => net.connect(80, 'unauthorized.example')),
    dns: await probe(() => dns.promises.lookup('unauthorized.example'))
  };
}
