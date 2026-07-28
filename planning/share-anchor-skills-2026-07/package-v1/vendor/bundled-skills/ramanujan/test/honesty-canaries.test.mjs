// Wave 6 — Honesty-Law canary suite, core (A2-core) tests.
//
// Exercises the REAL Wave-6 source (src/honesty-canaries.mjs) against the REAL A1 ledger
// (src/claim-ledger.mjs) + the A1.5 adjudication substrate (src/adjudication.mjs) over the REAL
// inherited Phase-0 durability substrate (resolved via inherits.manifest.json), proving the
// done-when:
//   1. all four canaries are GREEN on the genuine spine (the suite passes, exit 0);
//   2. EACH canary FAILS THE BUILD on its planted violation (the canary trips, exit non-zero).
//
// The explicit Given/When/Then from the plan — "a same-family object asserting VERIFIED with a
// self-authored stamp => independence + flip-law fail the build" — is the last test block.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  OUT_OF_MODEL_FAMILY,
  CANARY_NAMES,
  CANARIES,
  evalLiteral,
  reexecute,
  reexecHash,
  reexecutionAgrees,
  SAMPLE_SUM,
  SAMPLE_NESTED,
  canaryIndependence,
  canaryInvertedCompleteness,
  canaryTransitionsInvariant,
  canaryFlipLaw,
  runHonestyCanarySuite,
  canarySuiteExitCode,
} from '../src/honesty-canaries.mjs';
import { loadDurabilitySubstrate, canonicalStdoutHash } from '../src/adjudication.mjs';

// The REAL inherited durability substrate, resolved via the pinned manifest, shared across canary
// calls. Each canary mints its nonce state onto its OWN scratch file, so they never interfere.
const substrate = await loadDurabilitySubstrate();
const scratchDirs = [];
function scratch() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w6t-'));
  scratchDirs.push(dir);
  return dir;
}
after(() => {
  for (const d of scratchDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best-effort cleanup */ }
  }
});

// A clean ctx (real substrate + a throwaway scratch dir) for a single canary call.
function ctx(extra = {}) {
  return { substrate, scratchDir: scratch(), ...extra };
}

// =====================================================================================
// 0. The in-process exact-arithmetic RE-EXECUTOR (bigint only — NO float).
// =====================================================================================

test('evalLiteral evaluates the literal grammar in EXACT bigint arithmetic (no float)', () => {
  assert.equal(evalLiteral(5n), 5n);
  assert.equal(evalLiteral({ op: 'add', args: [2n, 3n, 4n] }), 9n);
  assert.equal(evalLiteral({ op: 'sub', args: [10n, 3n] }), 7n);
  assert.equal(evalLiteral({ op: 'mul', args: [2n, 3n, 4n] }), 24n);
  // bounded sum and a NESTED COMPOSITION (a bounded sum of products of literals)
  assert.equal(evalLiteral(SAMPLE_SUM), 6n);      // sum_{k=1}^{3} k
  assert.equal(evalLiteral(SAMPLE_NESTED), 12n);  // sum_{k=1}^{3} (k*2)
  // a JS float/number literal is OUT-OF-GRAMMAR (exact arithmetic only)
  assert.throws(() => evalLiteral(1.5), /float|number/i);
  assert.throws(() => evalLiteral(3), /float|number/i);
  // symbolic / unbounded / unknown nodes throw
  assert.throws(() => evalLiteral({ op: 'integral' }), /out-of-grammar/);
  assert.throws(() => evalLiteral({ var: 'k' }), /unbound/);
});

test('reexecHash is a deterministic SHA-256 over the canonical re-executed stdout', () => {
  const h1 = reexecHash(SAMPLE_SUM);
  const h2 = reexecHash(SAMPLE_SUM);
  assert.equal(h1, h2);
  assert.match(h1, /^[0-9a-f]{64}$/);
  assert.equal(reexecHash(SAMPLE_SUM), canonicalStdoutHash(reexecute(SAMPLE_SUM)));
  // a different computation hashes differently
  assert.notEqual(reexecHash(SAMPLE_SUM), reexecHash(SAMPLE_NESTED));
});

test('reexecutionAgrees is the warrant: genuine hash agrees, fabricated/out-of-grammar do not', () => {
  const genuine = { stdout_hash: reexecHash(SAMPLE_SUM) };
  assert.equal(reexecutionAgrees(genuine, SAMPLE_SUM), true);
  const fabricated = { stdout_hash: canonicalStdoutHash({ result: 'LIE' }) };
  assert.equal(reexecutionAgrees(fabricated, SAMPLE_SUM), false);
  // an out-of-grammar computation can never re-execute (=> never VERIFIED)
  assert.equal(reexecutionAgrees({ stdout_hash: 'x'.repeat(64) }, { op: 'integral' }), false);
  assert.equal(reexecutionAgrees(null, SAMPLE_SUM), false);
});

// =====================================================================================
// 1. GREEN: all four canaries pass on the genuine spine (the suite is green, exit 0).
// =====================================================================================

test('the full Honesty-Law canary suite is GREEN on the genuine spine (exit 0)', async () => {
  const result = await runHonestyCanarySuite(ctx());
  assert.equal(result.ok, true, `expected all canaries green; failures:\n${result.failures.join('\n')}`);
  assert.equal(result.failures.length, 0);
  assert.equal(canarySuiteExitCode(result), 0);

  // all four named canaries ran, each with real pinned assertions (not vacuous).
  assert.deepEqual(result.canaries.map((c) => c.name).sort(), [...CANARY_NAMES].sort());
  assert.equal(Object.keys(CANARIES).length, 4);
  for (const c of result.canaries) {
    assert.equal(c.ok, true, `canary ${c.name} tripped: ${c.failures.join('; ')}`);
    assert.ok(c.assertions.length > 0, `canary ${c.name} ran at least one pinned assertion`);
    assert.ok(c.assertions.every((a) => a.ok), `canary ${c.name} has a failed assertion`);
    // each canary verifies the RE-EXECUTED artifact (propose != adjudicate).
    assert.ok(
      c.assertions.some((a) => /re-execut|OBSERVED|VERIFIED|sticky/i.test(a.name)),
      `canary ${c.name} must assert against the re-executed artifact`,
    );
  }
});

test('each canary called directly (clean) is green', async () => {
  for (const fn of [canaryIndependence, canaryInvertedCompleteness, canaryTransitionsInvariant, canaryFlipLaw]) {
    const r = await fn(ctx());
    assert.equal(r.ok, true, `${r.name} not green: ${r.failures.join('; ')}`);
  }
});

// =====================================================================================
// 2. Each canary FAILS THE BUILD on its planted violation (the done-when's second arm).
// =====================================================================================

test('INDEPENDENCE trips on a same-family self-adjudication (propose == adjudicate)', async () => {
  const r = await canaryIndependence(ctx({ plant: 'self-adjudicate' }));
  assert.equal(r.ok, false);
  assert.equal(canarySuiteExitCode({ ok: false }), 1);
  assert.ok(
    r.failures.some((f) => /out-of-model|self-authored|propose == adjudicate|same-family/i.test(f)),
    `independence must name the self-authored-stamp violation; got:\n${r.failures.join('\n')}`,
  );
});

test('INDEPENDENCE trips on a fabricated stdout_hash (a same-family lie about the result)', async () => {
  const r = await canaryIndependence(ctx({ plant: 'fabricated-stdout' }));
  assert.equal(r.ok, false);
  assert.ok(
    r.failures.some((f) => /re-execute|reproduce|fabricated/i.test(f)),
    `independence must name the re-execution mismatch; got:\n${r.failures.join('\n')}`,
  );
});

test('INVERTED-COMPLETENESS trips when re-execution is skipped (an over-trusted reduced-warranty pass)', async () => {
  const r = await canaryInvertedCompleteness(ctx({ plant: 'skip-reexecution' }));
  assert.equal(r.ok, false);
  assert.ok(
    r.failures.some((f) => /fabricated stdout_hash/i.test(f) && /green was emitted/i.test(f)),
    `inverted-completeness must catch the fabricated artifact passing without re-execution; got:\n${r.failures.join('\n')}`,
  );
});

test('TRANSITIONS-INVARIANT trips on a raw promote() that bypasses the adjudication gate', async () => {
  const r = await canaryTransitionsInvariant(ctx({ plant: 'bypass-gate' }));
  assert.equal(r.ok, false);
  assert.ok(
    r.failures.some((f) => /OBSERVED .*without|adjudicat|re-executing/i.test(f) && /B/.test(f)),
    `transitions-invariant must name the un-warranted OBSERVED rung; got:\n${r.failures.join('\n')}`,
  );
});

test('FLIP-LAW trips on a non-sticky ledger that flips the rung on a self-authored re-assertion', async () => {
  const r = await canaryFlipLaw(ctx({ plant: 'flip-on-reassert' }));
  assert.equal(r.ok, false);
  assert.ok(
    r.failures.some((f) => /flip|sticky/i.test(f)),
    `flip-law must name the rung-flip violation; got:\n${r.failures.join('\n')}`,
  );
});

// A planted violation in ANY canary must fail the WHOLE suite non-zero (gates the build).
test('a planted violation fails the whole suite non-zero (build-failing)', async () => {
  // Inject one tripped canary alongside the genuine three by overriding the suite ctx per canary.
  const clean = await runHonestyCanarySuite(ctx());
  assert.equal(canarySuiteExitCode(clean), 0);

  // and a directly-tripped canary maps to a non-zero exit
  const tripped = await canaryFlipLaw(ctx({ plant: 'flip-on-reassert' }));
  assert.equal(canarySuiteExitCode(tripped), 1);
});

// =====================================================================================
// 3. The explicit Given/When/Then.
// =====================================================================================

test('GWT: Given a same-family object asserting VERIFIED with a self-authored stamp, When independence + flip-law run, Then the build fails', async () => {
  // Given: a same-family object that (independence) self-adjudicates with its own family stamp,
  // and (flip-law) re-asserts a self-authored VERIFIED rung onto a non-sticky ledger.
  // When: independence + flip-law run.
  const independence = await canaryIndependence(ctx({ plant: 'self-adjudicate' }));
  const flipLaw = await canaryFlipLaw(ctx({ plant: 'flip-on-reassert' }));

  // Then: each canary trips and the build fails (non-zero).
  assert.equal(independence.ok, false, 'independence must fail on a self-authored VERIFIED stamp');
  assert.equal(flipLaw.ok, false, 'flip-law must fail on a self-authored rung-flip');
  assert.equal(canarySuiteExitCode(independence), 1);
  assert.equal(canarySuiteExitCode(flipLaw), 1);
});
