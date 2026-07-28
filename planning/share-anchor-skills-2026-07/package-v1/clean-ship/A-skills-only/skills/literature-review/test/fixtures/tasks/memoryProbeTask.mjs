// Test fixture: proves process-level memory isolation. The parent plants a
// global canary in ITS process before spawning; if memory were shared the
// worker would see it, and the worker's mutation would leak back.
export default async function run() {
  const report = {
    pid: process.pid,
    canaryBefore: globalThis.__litreviewCanary ?? null
  };

  globalThis.__litreviewCanary = 'worker-mutated';
  report.canaryAfter = globalThis.__litreviewCanary;

  try {
    new SharedArrayBuffer(8);
    report.sharedArrayBuffer = { blocked: false };
  } catch (err) {
    report.sharedArrayBuffer = { blocked: true, name: err.name };
  }

  try {
    new WebAssembly.Memory({ initial: 1, maximum: 1, shared: true });
    report.wasmSharedMemory = { blocked: false };
  } catch (err) {
    report.wasmSharedMemory = { blocked: true, name: err.name };
  }

  return report;
}
