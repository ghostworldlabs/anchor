// test/matrix-subsystem-fence.test.mjs — Wave 11: the committed parallel-matrix
// subsystem is pinned GREEN and BYTE-STABLE.
//
// The HARD BASELINE (IMPLEMENTATION-PLAN North Star) requires the committed
// parallel-matrix subsystem — the 8 execution modules (matrixScheduler /
// isolatedWorker / isolationJail / ipcAuth / workerEntry / concurrencyManager /
// terminalJoin / telemetryEmitter, whose 7 test files carry 52 tests) AND the
// evidence-lineage modules committed in the same subsystem commit bc77a3b
// (quoteExtractor / structuralSanitizer / textNormalization /
// tasks/quoteExtractionTask / schemas/evidenceLedger / schemas/telemetryEvent,
// +30 tests) — to stay green and byte-stable through the whole plan-first feature.
//
// "Green" is enforced by the suite itself (the subsystem's own test files run under
// the same `node --test` gate). "Byte-stable" is enforced HERE: the sha256 of every
// subsystem module is pinned to its committed bytes. And the fence asserts the
// MEASURED per-file test COUNTS, not merely file presence — a subsystem test file
// that is deleted, truncated, or gutted of its test declarations can never fake
// green. Any edit to the frozen modules or any drop in a pinned count fails this
// fence by design — changing the frozen subsystem requires a plan amendment and a
// deliberate re-pin, never a drive-by diff.

import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { fileSha256 } from './_wave1-trio-resolve.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.resolve(TEST_DIR, '..');

/** The committed bytes of the frozen subsystem (sha256, pinned 2026-07-21, Wave 11). */
const PINNED_MODULE_HASHES = Object.freeze({
  // The 8 execution modules.
  'src/matrixScheduler.mjs': '580def494e2cf9a8dd955af43156c789290249d92875727deafde95511e0bb09',
  'src/isolatedWorker.mjs': '399d1e7b485e7e088a925f80465f5f0c813bacdabad2972ba6da31ee435e3f27',
  'src/isolationJail.mjs': '17a43e0e1cb7dabf36440db114aa393b81e5333bb77df2a1b05ef2f7eb4b1c2e',
  'src/ipcAuth.mjs': '33717718636ba8f2a79c622ab3399fc26b59737bb59d044c7fca463fd6be90c3',
  'src/workerEntry.mjs': '4fc5dc36093c2254f5ac04cd5ac749527c16c765c03cd930a5be8a2bcd273a36',
  'src/concurrencyManager.mjs': '42bbbb934eac32a5d8bf1648d65372beefa2f4c22db51b7a914d3d289cee4a2c',
  'src/terminalJoin.mjs': 'f08c427f61c5acb0cb4afa08c4ce1a826500b7cb74bc6a1b1ab98d047bdb2a8d',
  'src/telemetryEmitter.mjs': '0920897dc42bf9f359aa77ce4f69becc539a3f6097f9fa9ba6c4bf57a69945b8',
  // The evidence-lineage modules committed in the same subsystem commit (bc77a3b).
  'src/quoteExtractor.mjs': '72bc3921ad090e41a85960b2d0b1b5bb37dae4d72ed14930e22c76cf1be5178c',
  'src/structuralSanitizer.mjs': '2dcf47b7134fa54ba1e8381c327fc83ab4c62c1ad6d208289608421937d8c9ff',
  'src/textNormalization.mjs': 'aeb0d1e2b6b4f479f0aaea5254eb835f331c5db2eb841b99165d68f8d7a1d130',
  'src/tasks/quoteExtractionTask.mjs': '32edd269cdf47c2501960a93ee735e6dfa94df211d982d6f2db0e7fc17cdf692',
  'src/schemas/evidenceLedger.mjs': 'ffa5f8c709da11cd04e39a30906931cb6a492656f7627321db23614f7574ff18',
  'src/schemas/telemetryEvent.mjs': 'bcf935774f68f08ce6fd846b150a93ad8f462374420971a37e56783ecfaf0fd0',
});

/**
 * The MEASURED per-file test counts of the frozen subsystem's own test files
 * (top-level `test(` declaration sites, measured 2026-07-21 at commit bc77a3b's
 * bytes — none of these files generates tests dynamically, so declaration sites
 * equal executed tests). The 7 execution-module test files carry 52 tests; the
 * evidence-lineage test files carry the +30.
 */
const EXECUTION_TEST_COUNTS = Object.freeze({
  'matrixScheduler.test.mjs': 10,
  'isolatedWorker.test.mjs': 6,
  'isolationJail.test.mjs': 11,
  'ipcAuth.test.mjs': 7,
  'concurrencyManager.test.mjs': 7,
  'terminalJoin.test.mjs': 7,
  'telemetryEmitter.test.mjs': 4,
});
const EXECUTION_TEST_TOTAL = 52;

const LINEAGE_TEST_COUNTS = Object.freeze({
  'quoteExtractor.test.mjs': 8,
  'structuralSanitizer.test.mjs': 9,
  'textNormalization.test.mjs': 11,
  'quoteExtractionTask.test.mjs': 2,
});
const LINEAGE_TEST_TOTAL = 30;

/**
 * Count the test-declaration sites in a test file's source: lines opening a
 * `test(` / `it(` call. The exact measurement the pinned counts were taken with;
 * comments cannot match (the `//` prefix precedes the name) and none of the pinned
 * files registers tests from loops or data tables (verified at pin time).
 */
function countDeclaredTests(file) {
  const source = fs.readFileSync(file, 'utf8');
  return (source.match(/^[ \t]*(?:test|it)\s*\(/gm) ?? []).length;
}

describe('Wave 11 — parallel-matrix subsystem fence (green + byte-stable)', () => {
  test('every subsystem module byte-matches its pinned committed hash (execution + evidence lineage)', () => {
    for (const [rel, pinned] of Object.entries(PINNED_MODULE_HASHES)) {
      const file = path.join(SKILL_DIR, rel);
      assert.ok(fs.existsSync(file), `${rel} must exist (the committed subsystem may not be deleted)`);
      assert.equal(
        fileSha256(file),
        pinned,
        `${rel} drifted from its pinned committed bytes — the frozen parallel-matrix subsystem ` +
          'may only change via a plan amendment plus a deliberate fence re-pin',
      );
    }
  });

  test('the subsystem modules still import cleanly and expose their committed public surface', async () => {
    const [scheduler, worker, jail, ipc, concurrency, terminal, telemetry, workerEntry] =
      await Promise.all([
        import('../src/matrixScheduler.mjs'),
        import('../src/isolatedWorker.mjs'),
        import('../src/isolationJail.mjs'),
        import('../src/ipcAuth.mjs'),
        import('../src/concurrencyManager.mjs'),
        import('../src/terminalJoin.mjs'),
        import('../src/telemetryEmitter.mjs'),
        // Inert when imported without an IPC channel (its own documented contract) —
        // the import itself is the assertion that the entry still loads.
        import('../src/workerEntry.mjs'),
      ]);
    assert.equal(typeof scheduler.MatrixScheduler, 'function');
    assert.equal(typeof scheduler.planBroadFirstBatches, 'function');
    assert.equal(typeof worker.IsolatedWorker, 'function');
    assert.equal(typeof worker.spawnIsolatedWorker, 'function');
    assert.equal(typeof worker.WorkerFailedError, 'function');
    assert.equal(typeof jail.installIsolationJail, 'function');
    assert.equal(typeof jail.installNetworkJail, 'function');
    assert.equal(typeof jail.installSharedMemoryJail, 'function');
    assert.equal(typeof jail.isHostAuthorized, 'function');
    assert.equal(typeof ipc.createIpcSecret, 'function');
    assert.equal(typeof ipc.signEvent, 'function');
    assert.equal(typeof ipc.verifyEvent, 'function');
    assert.equal(typeof concurrency.ConcurrencyManager, 'function');
    assert.equal(typeof terminal.terminalJoin, 'function');
    assert.equal(typeof terminal.formatEvidenceLedgerMarkdown, 'function');
    assert.equal(typeof telemetry.TelemetryHub, 'function');
    assert.ok(workerEntry, 'workerEntry.mjs loads inertly outside a forked IPC context');
  });

  test('the evidence-lineage modules still import cleanly and expose their committed public surface', async () => {
    const [quoteExtractor, sanitizer, normalization, extractionTask, evidenceLedger, telemetryEvent] =
      await Promise.all([
        import('../src/quoteExtractor.mjs'),
        import('../src/structuralSanitizer.mjs'),
        import('../src/textNormalization.mjs'),
        import('../src/tasks/quoteExtractionTask.mjs'),
        import('../src/schemas/evidenceLedger.mjs'),
        import('../src/schemas/telemetryEvent.mjs'),
      ]);
    assert.equal(quoteExtractor.DEFAULT_MIN_QUOTE_LENGTH, 10);
    assert.equal(typeof quoteExtractor.groundQuote, 'function');
    assert.equal(typeof quoteExtractor.extractVerbatimQuotes, 'function');
    assert.equal(typeof sanitizer.sanitizeText, 'function');
    assert.equal(typeof sanitizer.sanitizeStructure, 'function');
    assert.equal(typeof normalization.buildNormalizedView, 'function');
    assert.equal(typeof normalization.normalizeText, 'function');
    assert.equal(typeof normalization.rawSpanForMatch, 'function');
    assert.equal(typeof extractionTask.default, 'function', 'quoteExtractionTask default run entry');
    assert.equal(typeof evidenceLedger.evidenceLedgerSchema, 'object');
    assert.equal(typeof telemetryEvent.telemetryEventSchema, 'object');
    assert.ok(Array.isArray(telemetryEvent.TELEMETRY_EVENT_TYPES));
  });

  test('measured per-file test COUNTS: the 7 execution test files carry exactly 52 tests', () => {
    let total = 0;
    for (const [name, pinned] of Object.entries(EXECUTION_TEST_COUNTS)) {
      const file = path.join(TEST_DIR, name);
      assert.ok(
        fs.existsSync(file),
        `${name} must exist — deleting a subsystem test file would fake green`,
      );
      const counted = countDeclaredTests(file);
      assert.equal(
        counted,
        pinned,
        `${name} declares ${counted} tests but the fence pins ${pinned} — gutting or growing a ` +
          'frozen subsystem test file requires a plan amendment plus a deliberate re-pin',
      );
      total += counted;
      // test/index.mjs auto-discovers every *.test.mjs sibling, so a file counted
      // here runs in this same `node --test` invocation.
    }
    assert.equal(total, EXECUTION_TEST_TOTAL, 'the execution modules\' 7 test files carry 52 tests');
  });

  test('measured per-file test COUNTS: the evidence-lineage test files carry exactly the +30 tests', () => {
    let total = 0;
    for (const [name, pinned] of Object.entries(LINEAGE_TEST_COUNTS)) {
      const file = path.join(TEST_DIR, name);
      assert.ok(
        fs.existsSync(file),
        `${name} must exist — deleting a subsystem test file would fake green`,
      );
      const counted = countDeclaredTests(file);
      assert.equal(
        counted,
        pinned,
        `${name} declares ${counted} tests but the fence pins ${pinned} — gutting or growing a ` +
          'frozen subsystem test file requires a plan amendment plus a deliberate re-pin',
      );
      total += counted;
    }
    assert.equal(total, LINEAGE_TEST_TOTAL, 'the evidence-lineage test files carry the +30 tests');
  });
});
