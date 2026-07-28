// W3 (Scope B) — the OPT-IN autonomous-dispatch GATE (fast tier).
//
// Ramanujan's orchestrator is READ-ONLY by default. W3 adds a GATED autonomous-dispatch surface that
// OPENS only when the caller passes a valid DispatchCapability token. These tests exercise the gate
// LOGIC end-to-end with NO real tools and NO subprocess: a FAKE AdjudicationDispatcher
// ({ consumeArtifact: () => true, family: 'firewall-subprocess' }) plus a STUB `mint` that returns a
// hand-built, structurally-valid adjudication artifact bound to the claim. Because `mint` is injected,
// the default real-firewall-subprocess mint (mintFirewallArtifact) never spawns.
//
// The five properties proven:
//   1. GATE CLOSED (default, no capability) is byte-for-byte the unchanged read-only fail-safe posture.
//   2. GATE OPEN settles an IN-GRAMMAR computation to VERIFIED (OBSERVED rung) — an honest rung-flip.
//   3. HONESTY LAW: gate open NEVER autonomously settles a proof-bearing claim (ABSTAIN, rung held).
//   4. An OUT-OF-GRAMMAR computational claim gets NO mint (recognize rejects it) => ABSTAIN, rung held.
//   5. isDispatchCapability discriminates a real token from a plain object; makeDispatchCapability
//      validates its dispatcher + mint seam.
//
// Runs under `node --test test/` with no I/O.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  orchestrate,
  AutonomousOrchestrator,
  ORCHESTRATOR_MODE,
  ORCHESTRATOR_MODE_GATED,
} from '../src/orchestrator.mjs';
import {
  makeDispatchCapability,
  isDispatchCapability,
  DispatchCapabilityError,
} from '../src/dispatch-capability.mjs';
import { ClaimLedger, RUNG } from '../src/claim-ledger.mjs';
import { ROUTE_VERDICT } from '../src/verify-router.mjs';
import { recognize, int, add, mul, variable } from '../src/firewall-grammar.mjs';
import { runtimeFingerprint } from '../src/adjudication.mjs';

// ---------------------------------------------------------------------------
// The fast-tier STUB rig — a FAKE dispatcher + a STUB mint. No subprocess ever spawns.
// ---------------------------------------------------------------------------

// A FAKE AdjudicationDispatcher: the gate consumes exactly { consumeArtifact(artifact)->bool, family }.
// consumeArtifact returns true (the single-use nonce authority the real dispatcher provides is stubbed
// out), and family is the firewall family-of-record the promote() event stamps.
const fakeDispatcher = Object.freeze({ consumeArtifact: () => true, family: 'firewall-subprocess' });

// A STUB mint: (claimId, expr) -> a hand-built, structurally-valid P9 adjudication artifact BOUND to
// claimId. Mirrors adjudication.test.mjs's valid-artifact shape (its `good` fixture + the freshArtifact
// helper): { claim_id, domain, nonce (64-hex), stdout_hash (64-hex), exit_code:int, runtime_fingerprint }.
// validateArtifact accepts it, and its claim_id matches the promotion target, so the fake dispatcher's
// consumeArtifact -> true drives adjudicatedPromoteToVerified to OBSERVED. No firewall subprocess runs.
function stubMint(claimId /*, expr */) {
  return {
    claim_id: claimId,
    domain: 'arithmetic',
    nonce: 'a'.repeat(64),
    stdout_hash: 'b'.repeat(64),
    exit_code: 0,
    runtime_fingerprint: runtimeFingerprint(),
  };
}

/** A fresh open-gate capability wired to the fake dispatcher + stub mint. */
function openCapability(mint = stubMint) {
  return makeDispatchCapability({ dispatcher: fakeDispatcher, mint });
}

// The canonical IN-GRAMMAR literal computation (exact arithmetic the closed grammar recognizes) and a
// clearly OUT-OF-GRAMMAR expr (a free/symbolic variable — rejected by the default-deny recognizer).
const inGrammarExpr = add(int(1), int(1));
const outOfGrammarExpr = variable('x');

// Sanity: the fixtures really are in / out of grammar (so the assertions below test the gate, not a typo).
assert.equal(recognize(inGrammarExpr).inGrammar, true, 'fixture: add(int(1),int(1)) must be in-grammar');
assert.equal(recognize(outOfGrammarExpr).inGrammar, false, 'fixture: variable("x") must be out-of-grammar');

// ---------------------------------------------------------------------------
// 1. GATE CLOSED (default) — unchanged read-only fail-safe posture (W3 changed nothing by default).
// ---------------------------------------------------------------------------

test('GATE CLOSED (no capability): the VERIFY dispatch stays read-only and settles nothing', () => {
  const ledger = new ClaimLedger();
  const result = orchestrate(
    { pillar: 'verify', claims: [{ id: 'c1', type: 'computational', expr: inGrammarExpr }] },
    { ledger }, // NO capability => the gate defaults to CLOSED
  );

  assert.equal(result.read_only, true);
  assert.equal(result.mode, ORCHESTRATOR_MODE); // 'read-only'
  assert.equal(result.gated, false);
  assert.equal(result.held, true); // a read-only path holds both invariants
  assert.deepEqual(result.rungFlips, []); // admission-at-floor is not a flip; nothing settled

  // The claim was EMITTED at the floor but never settled — the rung stays UNVERIFIED.
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED);
  // read-only VERIFY has no autonomous minter => the firewall verifier ABSTAINs.
  assert.equal(result.output.results[0].verdict, ROUTE_VERDICT.ABSTAIN);
});

// ---------------------------------------------------------------------------
// 2. GATE OPEN — an in-grammar computation autonomously settles to VERIFIED (OBSERVED rung).
// ---------------------------------------------------------------------------

test('GATE OPEN: an in-grammar computational claim settles to VERIFIED (rung OBSERVED) — an honest flip', () => {
  const ledger = new ClaimLedger();
  const capability = openCapability();
  const result = orchestrate(
    { pillar: 'verify', claims: [{ id: 'c2', type: 'computational', expr: inGrammarExpr }] },
    { ledger, capability },
  );

  assert.equal(result.gated, true);
  assert.equal(result.mode, ORCHESTRATOR_MODE_GATED); // 'gated-dispatch'
  assert.equal(result.read_only, false);

  const route = result.output.results[0];
  assert.equal(route.verdict, ROUTE_VERDICT.VERIFIED);

  // The ledger recorded the autonomous settlement: OBSERVED (the top autonomous rung).
  assert.equal(ledger.rungOf('c2'), RUNG.OBSERVED);

  // A settle HAPPENED, so the no-dispatch invariant is honestly false and the flip is reported.
  assert.equal(result.held, false);
  assert.ok(result.rungFlips.length > 0, 'a rung-flip (UNVERIFIED -> OBSERVED) is reported');
});

// ---------------------------------------------------------------------------
// 3. HONESTY LAW — the open gate NEVER autonomously settles a proof-bearing claim.
// ---------------------------------------------------------------------------

test('HONESTY LAW: gate open, a proof-bearing claim ABSTAINs and its rung is held at UNVERIFIED', () => {
  const ledger = new ClaimLedger();
  const capability = openCapability();
  const result = orchestrate(
    { pillar: 'verify', claims: [{ id: 'p1', type: 'proof-bearing', statement: '1+1=2' }] },
    { ledger, capability },
  );

  assert.equal(result.gated, true); // the gate is open...
  const route = result.output.results[0];
  assert.equal(route.verdict, ROUTE_VERDICT.ABSTAIN); // ...but no autonomous verifier settles a proof
  assert.equal(ledger.rungOf('p1'), RUNG.UNVERIFIED); // the rung is untouched
});

// ---------------------------------------------------------------------------
// 4. OUT-OF-GRAMMAR computational — recognize rejects it, so NO mint, so ABSTAIN (rung held).
// ---------------------------------------------------------------------------

test('OUT-OF-GRAMMAR computational: no artifact is minted => ABSTAIN, rung held (mint is never called)', () => {
  const ledger = new ClaimLedger();
  // A mint that THROWS if invoked — proving the out-of-grammar path never mints an artifact.
  const capability = openCapability(() => {
    throw new Error('stub mint must NOT be called for an out-of-grammar expr');
  });

  const result = orchestrate(
    { pillar: 'verify', claims: [{ id: 'c3', type: 'computational', expr: outOfGrammarExpr }] },
    { ledger, capability },
  );

  const route = result.output.results[0];
  assert.equal(route.verdict, ROUTE_VERDICT.ABSTAIN); // grammar rejected => firewall ABSTAINs
  assert.equal(ledger.rungOf('c3'), RUNG.UNVERIFIED); // rung unchanged
});

// A deeper out-of-grammar case (a float buried inside otherwise-valid arithmetic) — same outcome, and
// still proves the throwing mint is never reached.
test('OUT-OF-GRAMMAR (deep float smuggle): ABSTAIN, rung held, mint never called', () => {
  const ledger = new ClaimLedger();
  const capability = openCapability(() => {
    throw new Error('stub mint must NOT be called for an out-of-grammar expr');
  });
  const deepFloat = mul(int(2), add(int(1), int(2.5))); // 2.5 is a float => out of grammar

  const result = new AutonomousOrchestrator({ ledger, capability }).handle({
    pillar: 'verify',
    claims: [{ id: 'c4', type: 'computational', expr: deepFloat }],
  });

  assert.equal(result.output.results[0].verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(ledger.rungOf('c4'), RUNG.UNVERIFIED);
});

// ---------------------------------------------------------------------------
// 5. isDispatchCapability + makeDispatchCapability validation.
// ---------------------------------------------------------------------------

test('isDispatchCapability: a plain object is false; a real capability is true', () => {
  // A plain look-alike (no brand) is NOT a capability.
  assert.equal(isDispatchCapability({ dispatcher: {}, mint() {} }), false);
  assert.equal(isDispatchCapability(null), false);
  assert.equal(isDispatchCapability(undefined), false);

  // A genuine, branded capability.
  const cap = openCapability();
  assert.equal(isDispatchCapability(cap), true);
});

test('makeDispatchCapability THROWS DispatchCapabilityError on a bad dispatcher or a missing mint seam', () => {
  // Dispatcher missing consumeArtifact/family (the adjudication interface the gate consumes).
  assert.throws(
    () => makeDispatchCapability({ dispatcher: {}, mint: () => {} }),
    DispatchCapabilityError,
  );
  assert.throws(
    () => makeDispatchCapability({ dispatcher: { consumeArtifact: () => true }, mint: () => {} }),
    DispatchCapabilityError, // no `family`
  );

  // A valid dispatcher but NEITHER an injected mint NOR a dispatcher.mintArtifact.
  assert.throws(
    () => makeDispatchCapability({ dispatcher: fakeDispatcher }),
    DispatchCapabilityError,
  );

  // The happy path does not throw.
  assert.doesNotThrow(() => makeDispatchCapability({ dispatcher: fakeDispatcher, mint: stubMint }));
});
