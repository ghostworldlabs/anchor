import { test, describe } from 'node:test';
import assert from 'node:assert';
import { EventEmitter } from 'node:events';
import { TelemetryHub } from '../src/telemetryEmitter.mjs';

// A stand-in for IsolatedWorker: an EventEmitter with workerId + state.
function fakeWorker(workerId) {
  const worker = new EventEmitter();
  worker.workerId = workerId;
  worker.state = 'created';
  return worker;
}

describe('TelemetryHub - thread state and progress visibility', () => {
  test('tracks multiple threads and reflects their state transitions', () => {
    const hub = new TelemetryHub();
    const a = fakeWorker('lrw-aaa');
    const b = fakeWorker('lrw-bbb');
    hub.track(a).track(b);

    assert.equal(hub.size, 2);

    a.emit('state', 'running');
    b.emit('state', 'running');
    b.emit('state', 'completed');

    const byId = Object.fromEntries(hub.snapshot().map(t => [t.workerId, t]));
    assert.equal(byId['lrw-aaa'].state, 'running');
    assert.equal(byId['lrw-bbb'].state, 'completed');
  });

  test('records live progress and counts violations per thread', () => {
    const hub = new TelemetryHub();
    const worker = fakeWorker('lrw-ccc');
    hub.track(worker);

    worker.emit('progress', { completed: 2, total: 4, fraction: 0.5 });
    worker.emit('violation', { kind: 'network', api: 'fetch' });
    worker.emit('violation', { kind: 'shared-memory', api: 'SharedArrayBuffer' });

    const [thread] = hub.snapshot();
    assert.deepEqual(thread.progress, { completed: 2, total: 4, fraction: 0.5 });
    assert.equal(thread.violations, 2);
    assert.equal(typeof thread.updatedAt, 'number');
  });

  test('emits a thread event on every update for real-time consumers', () => {
    const hub = new TelemetryHub();
    const updates = [];
    hub.on('thread', (t) => updates.push(t));

    const worker = fakeWorker('lrw-ddd');
    hub.track(worker); // initial registration snapshot
    worker.emit('state', 'running');
    worker.emit('progress', { completed: 1, total: 2, fraction: 0.5 });

    assert.equal(updates.length, 3);
    assert.equal(updates[0].state, 'created');
    assert.equal(updates[1].state, 'running');
    assert.equal(updates[2].progress.fraction, 0.5);
    // Snapshots are copies: mutating one never touches hub state.
    updates[2].state = 'tampered';
    assert.equal(hub.snapshot()[0].state, 'running');
  });

  test('re-emits raw telemetry events from all tracked workers', () => {
    const hub = new TelemetryHub();
    const seen = [];
    hub.on('telemetry', (e) => seen.push(e));

    const a = fakeWorker('lrw-eee');
    const b = fakeWorker('lrw-fff');
    hub.track(a).track(b);

    a.emit('telemetry', { workerId: 'lrw-eee', seq: 0, type: 'state' });
    b.emit('telemetry', { workerId: 'lrw-fff', seq: 0, type: 'progress' });

    assert.equal(seen.length, 2);
    assert.deepEqual(seen.map(e => e.workerId), ['lrw-eee', 'lrw-fff']);
  });
});
