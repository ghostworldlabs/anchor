// Wave 4 — Out-of-model adjudication-artifact substrate (A1.5) tests.
//
// Exercises the REAL Wave-4 source (src/adjudication.mjs) against the REAL inherited Phase-0
// durability substrate (resolved through inherits.manifest.json) to prove the done-when. The
// gate here is NEGATIVE-ONLY (the positive computational path — a real firewall subprocess whose
// stdout re-executes to an identical hash — is deferred to Wave 9):
//
//   - with NO minter present, promote()-to-VERIFIED hard-faults to ABSTAIN (the headline NEGATIVE);
//   - a re-presented artifact is rejected for SAME-claim, CROSS-claim, AND ACROSS-restart replay
//     (the nonce state reloads from the durability substrate — not an in-memory stub);
//   - the durable counter/spent record is ordered-BEFORE artifact validity, proven by a
//     crash-mid-mint fixture (death after mint, before flush => no usable replayable nonce).
//
// The two explicit Given/When/Then from the plan are the last two test blocks.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import {
  ARTIFACT_FIELDS,
  CANONICALIZATION_VERSION,
  VERDICT,
  runtimeFingerprint,
  canonicalize,
  canonicalStdoutHash,
  validateArtifact,
  computeNonce,
  nonceKey,
  loadDurabilitySubstrate,
  DurableNonceStore,
  AdjudicationDispatcher,
  adjudicatedPromoteToVerified,
} from '../src/adjudication.mjs';

// The REAL inherited durability substrate (foreman-lib.mjs), resolved via the pinned manifest.
const substrate = await loadDurabilitySubstrate();

// A unique, throwaway checkpoint file per call (each is its own "process's" disk).
let fileSeq = 0;
const scratchDirs = [];
function tmpFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w4-'));
  scratchDirs.push(dir);
  return path.join(dir, `nonce-store-${fileSeq++}.checkpoint.json`);
}
after(() => {
  for (const d of scratchDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best-effort cleanup */ }
  }
});

// A real 64-hex stdout hash (what a Wave-9 subprocess would emit); Wave 4 supplies it.
const STDOUT_HASH = canonicalStdoutHash({ result: '6', op: 'sum_{k=1}^{3} k' });

function freshArtifact(dispatcher, claim_id, domain = 'arithmetic', hooks = {}) {
  return dispatcher.mintArtifact(claim_id, domain, { stdout_hash: STDOUT_HASH, exit_code: 0 }, hooks);
}

// =====================================================================================
// 1. The artifact contract + re-hash primitives.
// =====================================================================================

test('runtimeFingerprint stamps { node_major, canonicalization_version }', () => {
  const rf = runtimeFingerprint();
  assert.ok(Number.isInteger(rf.node_major) && rf.node_major > 0);
  assert.equal(rf.canonicalization_version, CANONICALIZATION_VERSION);
});

test('ARTIFACT_FIELDS is the pinned P9 field set', () => {
  assert.deepEqual(ARTIFACT_FIELDS, ['claim_id', 'domain', 'nonce', 'stdout_hash', 'exit_code', 'runtime_fingerprint']);
});

test('canonicalStdoutHash is a deterministic, key-order-invariant SHA-256 (the out-of-band re-hash)', () => {
  const a = canonicalStdoutHash({ a: 1, b: 2, nested: { y: 9, x: 8 } });
  const b = canonicalStdoutHash({ b: 2, nested: { x: 8, y: 9 }, a: 1 }); // same content, different key order
  assert.equal(a, b, 'canonicalization is sorted-key, so key order does not change the hash');
  assert.match(a, /^[0-9a-f]{64}$/);
  // exact-number: a bigint renders as its decimal string (no float ever appears)
  assert.equal(canonicalize({ n: 6n }), '{"n":"6"}');
  // a string stdout passes through unchanged
  assert.equal(canonicalStdoutHash('raw'), canonicalStdoutHash('raw'));
});

test('validateArtifact accepts a well-formed artifact and itemizes every defect otherwise', () => {
  const good = {
    claim_id: 'X', domain: 'arithmetic', nonce: 'a'.repeat(64),
    stdout_hash: STDOUT_HASH, exit_code: 0, runtime_fingerprint: runtimeFingerprint(),
  };
  assert.deepEqual(validateArtifact(good), { ok: true, failures: [] });

  assert.equal(validateArtifact(null).ok, false);
  assert.equal(validateArtifact({}).failures.length >= 6, true); // every field missing
  assert.equal(validateArtifact({ ...good, nonce: 'tooshort' }).ok, false);
  assert.equal(validateArtifact({ ...good, stdout_hash: 'NOTHEX' }).ok, false);
  assert.equal(validateArtifact({ ...good, exit_code: 1.5 }).ok, false);
  assert.equal(validateArtifact({ ...good, runtime_fingerprint: {} }).ok, false);
});

// =====================================================================================
// 2. The claim-bound nonce.
// =====================================================================================

test('computeNonce is deterministic, 64-hex, and binds to (claim_id, domain, counter)', () => {
  const n = computeNonce('X', 'arithmetic', 1);
  assert.match(n, /^[0-9a-f]{64}$/);
  assert.equal(n, computeNonce('X', 'arithmetic', 1));
  // a change in ANY of the three inputs changes the nonce (claim-binding)
  assert.notEqual(n, computeNonce('Y', 'arithmetic', 1)); // claim
  assert.notEqual(n, computeNonce('X', 'algebra', 1));     // domain
  assert.notEqual(n, computeNonce('X', 'arithmetic', 2));  // counter
  assert.throws(() => computeNonce('', 'd', 1), /non-empty/);
  assert.throws(() => computeNonce('X', 'd', 0), /positive integer/);
  assert.equal(nonceKey('X', 'arithmetic'), nonceKey('X', 'arithmetic'));
  assert.notEqual(nonceKey('X', 'a'), nonceKey('Xa', '')); // separator prevents aliasing
});

// =====================================================================================
// 3. DurableNonceStore — single-use + monotone + across-restart (the substrate).
// =====================================================================================

test('a freshly minted nonce is valid, consumes exactly ONCE (same-claim replay rejected)', () => {
  const file = tmpFile();
  const store = DurableNonceStore.load(substrate, file);
  const { nonce, counter } = store.mint('X', 'arithmetic');
  assert.equal(counter, 1);
  assert.equal(store.isValid(nonce, 'X', 'arithmetic'), true);
  assert.equal(store.consume(nonce, 'X', 'arithmetic'), true);   // first use: ok
  assert.equal(store.consume(nonce, 'X', 'arithmetic'), false);  // same-claim replay: rejected
  assert.equal(store.isSpent(nonce), true);
});

test('a nonce minted for claim X cannot be consumed for claim Y (cross-claim replay rejected)', () => {
  const store = DurableNonceStore.load(substrate, tmpFile());
  const { nonce } = store.mint('X', 'arithmetic');
  assert.equal(store.isValid(nonce, 'Y', 'arithmetic'), false);
  assert.equal(store.consume(nonce, 'Y', 'arithmetic'), false); // binding mismatch
  // and it is still consumable for its true owner (the failed cross-claim attempt did not spend it)
  assert.equal(store.consume(nonce, 'X', 'arithmetic'), true);
});

test('the spent set survives a restart: an already-consumed nonce stays rejected (across-restart replay)', () => {
  const file = tmpFile();
  const store = DurableNonceStore.load(substrate, file);
  const { nonce } = store.mint('X', 'arithmetic');
  assert.equal(store.consume(nonce, 'X', 'arithmetic'), true);

  // simulated restart: a brand-new store that reloads ONLY from disk
  const restarted = DurableNonceStore.load(substrate, file);
  assert.equal(restarted.isSpent(nonce), true);
  assert.equal(restarted.isValid(nonce, 'X', 'arithmetic'), false);
  assert.equal(restarted.consume(nonce, 'X', 'arithmetic'), false);
});

test('the monotone counter is durable across restarts (never resets)', () => {
  const file = tmpFile();
  const s1 = DurableNonceStore.load(substrate, file);
  assert.equal(s1.mint('X', 'arithmetic').counter, 1);
  const s2 = DurableNonceStore.load(substrate, file); // restart
  assert.equal(s2.counterFor('X', 'arithmetic'), 1);
  assert.equal(s2.mint('X', 'arithmetic').counter, 2); // continues, does not reset to 1
});

// =====================================================================================
// 4. Write-ordering — persist is ordered BEFORE validity (crash-mid-mint).
// =====================================================================================

test('crash AFTER mint but BEFORE the durable flush leaves NO usable replayable nonce on restart', () => {
  const file = tmpFile();
  const store = DurableNonceStore.load(substrate, file);

  // Death in the durability window: the nonce is computed, then the process dies before flush.
  let leaked;
  assert.throws(
    () => store.mint('X', 'arithmetic', {
      beforeFlush: ({ nonce }) => { leaked = nonce; throw new Error('process death mid-mint'); },
    }),
    /process death mid-mint/,
  );
  assert.ok(leaked, 'the in-flight nonce was computed (and leaked, as a forged replay would)');

  // restart: reload ONLY from disk. The issued-record (validity record) was never flushed.
  const restarted = DurableNonceStore.load(substrate, file);
  assert.equal(restarted.isValid(leaked, 'X', 'arithmetic'), false, 'no usable replayable nonce');
  assert.equal(restarted.consume(leaked, 'X', 'arithmetic'), false);
  assert.equal(restarted.counterFor('X', 'arithmetic'), 0, 'the durable counter never advanced');
  // and the next real mint reuses counter 1 — the crashed mint left no durable trace
  assert.equal(restarted.mint('X', 'arithmetic').counter, 1);
});

// =====================================================================================
// 5. The dispatcher — sole writer of family-of-record.
// =====================================================================================

test('AdjudicationDispatcher.mintArtifact emits a valid artifact carrying its family + a real nonce', () => {
  const store = DurableNonceStore.load(substrate, tmpFile());
  const dispatcher = new AdjudicationDispatcher({ store, family: 'firewall-subprocess' });
  const art = freshArtifact(dispatcher, 'X');
  assert.deepEqual(validateArtifact(art), { ok: true, failures: [] });
  assert.equal(art.claim_id, 'X');
  assert.equal(art.stdout_hash, STDOUT_HASH);
  assert.equal(dispatcher.family, 'firewall-subprocess');
  // the artifact is frozen (provenance cannot be mutated post-mint)
  assert.ok(Object.isFrozen(art));
  // a missing/invalid stdout_hash is refused (the contract demands the subprocess re-hash)
  assert.throws(() => store && new AdjudicationDispatcher({ store, family: '' }), /family-of-record/);
  const store2 = DurableNonceStore.load(substrate, tmpFile());
  const d2 = new AdjudicationDispatcher({ store: store2, family: 'firewall-subprocess' });
  assert.throws(() => d2.mintArtifact('X', 'arithmetic', { stdout_hash: 'nothex' }), /64-hex stdout_hash/);
});

// =====================================================================================
// 6. The gate — promote()-to-VERIFIED hard-faults to ABSTAIN (NEGATIVE-only).
// =====================================================================================

test('NEGATIVE: with NO minter present, the gate hard-faults to ABSTAIN and leaves the ledger untouched', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'X', type: 'computational' });
  // no dispatcher at all
  const v1 = adjudicatedPromoteToVerified(led, 'X', { artifact: undefined, dispatcher: undefined });
  assert.equal(v1.verdict, VERDICT.ABSTAIN);
  assert.equal(v1.promoted, false);
  assert.equal(v1.belief, BELIEF.CONJECTURAL);
  // even WITH a (would-be valid) artifact but no dispatcher: still ABSTAIN — propose != adjudicate
  const store = DurableNonceStore.load(substrate, tmpFile());
  const realDispatcher = new AdjudicationDispatcher({ store, family: 'firewall-subprocess' });
  const art = freshArtifact(realDispatcher, 'X');
  const v2 = adjudicatedPromoteToVerified(led, 'X', { artifact: art, dispatcher: null });
  assert.equal(v2.verdict, VERDICT.ABSTAIN);
  // ledger never moved off the floor
  assert.equal(led.rungOf('X'), RUNG.UNVERIFIED);
  assert.equal(led.beliefOf('X'), BELIEF.CONJECTURAL);
});

test('the gate ABSTAINs on a malformed artifact and on a claim_id mismatch', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'X', type: 'computational' });
  led.assert({ id: 'Y', type: 'computational' });
  const store = DurableNonceStore.load(substrate, tmpFile());
  const dispatcher = new AdjudicationDispatcher({ store, family: 'firewall-subprocess' });

  const malformed = adjudicatedPromoteToVerified(led, 'X', { artifact: { claim_id: 'X' }, dispatcher });
  assert.equal(malformed.verdict, VERDICT.ABSTAIN);

  const artForX = freshArtifact(dispatcher, 'X');
  const mismatch = adjudicatedPromoteToVerified(led, 'Y', { artifact: artForX, dispatcher });
  assert.equal(mismatch.verdict, VERDICT.ABSTAIN, 'an artifact for X cannot promote Y');
  assert.equal(led.rungOf('X'), RUNG.UNVERIFIED);
  assert.equal(led.rungOf('Y'), RUNG.UNVERIFIED);
});

test('a valid fresh artifact promotes to OBSERVED, stamping ONLY the dispatcher family-of-record; re-presentation ABSTAINs', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'X', type: 'computational' });
  const store = DurableNonceStore.load(substrate, tmpFile());
  const dispatcher = new AdjudicationDispatcher({ store, family: 'firewall-subprocess' });
  const art = freshArtifact(dispatcher, 'X');

  // This exercises the NONCE substrate (single-use consume) — Wave 4. The full computational
  // positive path (a real subprocess whose stdout re-executes to this hash) is Wave 9.
  const ok = adjudicatedPromoteToVerified(led, 'X', { artifact: art, dispatcher });
  assert.equal(ok.verdict, VERDICT.VERIFIED);
  assert.equal(led.rungOf('X'), RUNG.OBSERVED);
  assert.equal(led.beliefOf('X'), BELIEF.VERIFIED);
  // family-of-record was written by the dispatcher (sole writer), recorded on the promote event
  const promoteEvent = led.get('X').history.find((h) => h.event === 'promote');
  assert.equal(promoteEvent.family, 'firewall-subprocess');
  assert.equal(promoteEvent.by, 'adjudication-dispatcher');

  // same-claim, same-process re-presentation: the nonce is spent => ABSTAIN
  const replay = adjudicatedPromoteToVerified(led, 'X', { artifact: art, dispatcher });
  assert.equal(replay.verdict, VERDICT.ABSTAIN);
});

test('CROSS-claim forged replay through the gate is rejected (nonce binds to its minted claim)', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'Y', type: 'computational' });
  const store = DurableNonceStore.load(substrate, tmpFile());
  const dispatcher = new AdjudicationDispatcher({ store, family: 'firewall-subprocess' });

  // mint a nonce for X, then forge an artifact that re-labels it as claim Y
  const artForX = freshArtifact(dispatcher, 'X');
  const forged = { ...artForX, claim_id: 'Y' };
  const v = adjudicatedPromoteToVerified(led, 'Y', { artifact: forged, dispatcher });
  assert.equal(v.verdict, VERDICT.ABSTAIN, 'the X-bound nonce cannot adjudicate Y');
  assert.equal(led.rungOf('Y'), RUNG.UNVERIFIED);
});

// =====================================================================================
// 7. The two explicit Given/When/Then.
// =====================================================================================

test('GWT: a fresh artifact, persisted for X, is rejected when re-presented for a SECOND promotion after a restart', () => {
  const file = tmpFile();

  // Given: a fresh artifact minted + persisted for claim X, and a first (adjudicated) promotion.
  const store1 = DurableNonceStore.load(substrate, file);
  const dispatcher1 = new AdjudicationDispatcher({ store: store1, family: 'firewall-subprocess' });
  const art = freshArtifact(dispatcher1, 'X');
  const led1 = new ClaimLedger();
  led1.assert({ id: 'X', type: 'computational' });
  assert.equal(adjudicatedPromoteToVerified(led1, 'X', { artifact: art, dispatcher: dispatcher1 }).verdict, VERDICT.VERIFIED);

  // When: the process restarts (nonce state reloaded ONLY from disk) and the SAME artifact is
  // re-presented for a second promotion of X.
  const store2 = DurableNonceStore.load(substrate, file);
  const dispatcher2 = new AdjudicationDispatcher({ store: store2, family: 'firewall-subprocess' });
  const led2 = new ClaimLedger();
  led2.assert({ id: 'X', type: 'computational' });
  const v = adjudicatedPromoteToVerified(led2, 'X', { artifact: art, dispatcher: dispatcher2 });

  // Then: the durable single-use nonce rejects it.
  assert.equal(v.verdict, VERDICT.ABSTAIN);
  assert.equal(led2.rungOf('X'), RUNG.UNVERIFIED);
});

test('GWT: a process death AFTER mint but BEFORE the durable counter flush leaves no usable replayable nonce on restart', () => {
  const file = tmpFile();

  // Given: a process death after mint, before the durable flush.
  const store1 = DurableNonceStore.load(substrate, file);
  const dispatcher1 = new AdjudicationDispatcher({ store: store1, family: 'firewall-subprocess' });
  let leaked;
  assert.throws(
    () => dispatcher1.mintArtifact('X', 'arithmetic', { stdout_hash: STDOUT_HASH }, {
      beforeFlush: ({ nonce }) => { leaked = nonce; throw new Error('crash before flush'); },
    }),
    /crash before flush/,
  );

  // When: the process restarts and the leaked (would-be replay) nonce is presented for promotion.
  const store2 = DurableNonceStore.load(substrate, file);
  const dispatcher2 = new AdjudicationDispatcher({ store: store2, family: 'firewall-subprocess' });
  const forged = {
    claim_id: 'X', domain: 'arithmetic', nonce: leaked, stdout_hash: STDOUT_HASH,
    exit_code: 0, runtime_fingerprint: runtimeFingerprint(),
  };
  const led = new ClaimLedger();
  led.assert({ id: 'X', type: 'computational' });
  const v = adjudicatedPromoteToVerified(led, 'X', { artifact: forged, dispatcher: dispatcher2 });

  // Then: no usable replayable nonce exists — the persist is ordered-before validity.
  assert.equal(v.verdict, VERDICT.ABSTAIN);
  assert.equal(led.rungOf('X'), RUNG.UNVERIFIED);
});
