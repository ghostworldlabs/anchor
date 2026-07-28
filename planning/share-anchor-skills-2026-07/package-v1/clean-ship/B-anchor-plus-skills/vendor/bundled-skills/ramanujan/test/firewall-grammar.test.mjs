// Wave 8 — Autonomous-VERIFIED gate, part A (A4a): default-deny grammar + laundering battery tests.
//
// Exercises the REAL Wave-8 source (src/firewall-grammar.mjs) and its wiring into the REAL Wave-7
// VERIFY router (src/verify-router.mjs) over the REAL A1 ledger + A1.5 adjudication gate, proving
// the done-when:
//   - the grammar REJECTS (ABSTAIN+route) 100% of the P7 laundering battery, INCLUDING a composition
//     that smuggles an out-of-grammar node ANYWHERE in an otherwise-valid tree (deep-nested smuggle);
//   - it raises NO VERIFIED rung (no minter): an in-grammar input still ABSTAINs absent a minter, and
//     an out-of-grammar input can never reach the adjudication gate even with a valid artifact present;
//   - the explicit GWT: a smuggled non-literal input ABSTAINs+routes.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  GRAMMAR_NODE,
  WHITELIST,
  SCREEN_DECISION,
  recognize,
  isInGrammar,
  screen,
  runLaunderingBattery,
  LAUNDERING_BATTERY,
  IN_GRAMMAR_EXAMPLES,
  int,
  rational,
  neg,
  add,
  mul,
  div,
  pow,
  variable,
  sum,
  product,
} from '../src/firewall-grammar.mjs';

import { VerifyRouter, ROUTE_VERDICT, FIREWALL_FAMILY } from '../src/verify-router.mjs';
import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import {
  DurableNonceStore,
  AdjudicationDispatcher,
  canonicalStdoutHash,
  loadDurabilitySubstrate,
} from '../src/adjudication.mjs';

// The REAL inherited durability substrate, resolved via the pinned manifest (matches Wave-7 setup).
const substrate = await loadDurabilitySubstrate();
const scratchDirs = [];
function scratch() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w8t-'));
  scratchDirs.push(dir);
  return dir;
}
after(() => {
  for (const d of scratchDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best-effort cleanup */ }
  }
});

let fileSeq = 0;
function freshDispatcher(family = FIREWALL_FAMILY) {
  const store = DurableNonceStore.load(substrate, path.join(scratch(), `w8-${fileSeq++}.checkpoint.json`));
  return new AdjudicationDispatcher({ store, family });
}
const STDOUT_HASH = canonicalStdoutHash({ computation: 'sum_{k=1}^{3} k', result: '6' });
function mintArtifactFor(dispatcher, claim_id, domain = 'arithmetic') {
  return dispatcher.mintArtifact(claim_id, domain, { stdout_hash: STDOUT_HASH, exit_code: 0 });
}

// =====================================================================================
// RECOGNIZE — in-grammar literal computations are ACCEPTED.
// =====================================================================================

test('the grammar ACCEPTS every in-grammar example (exact arithmetic only)', () => {
  for (const ex of IN_GRAMMAR_EXAMPLES) {
    const rec = recognize(ex.expr);
    assert.equal(rec.inGrammar, true, `${ex.name} must be in grammar (reason: ${rec.reason} @ ${rec.path})`);
    assert.equal(rec.reason, null);
    assert.equal(isInGrammar(ex.expr), true);
  }
});

test('the canonical bounded sum-of-products of literals is in grammar; the bound index is the only legal symbol', () => {
  // sum_{k=1}^{3} (k * 2)
  const e = sum('k', int(1), int(3), mul(variable('k'), int(2)));
  assert.equal(isInGrammar(e), true);
  // a bigint / big decimal-string literal is exact and in grammar.
  assert.equal(isInGrammar(int(10n ** 40n)), true);
  assert.equal(isInGrammar(int('123456789012345678901234567890')), true);
  // an exact rational is in grammar; a zero denominator is not.
  assert.equal(isInGrammar(rational(2, 7)), true);
  assert.equal(isInGrammar(rational(2, 0)), false);
});

// =====================================================================================
// THE P7 LAUNDERING BATTERY — 100% REJECTED (ABSTAIN + route).
// =====================================================================================

test('done-when: the grammar REJECTS 100% of the P7 laundering battery (no smuggle accepted)', () => {
  const report = runLaunderingBattery();
  assert.ok(report.total >= 30, `the battery must be substantial (got ${report.total})`);
  assert.equal(report.accepted, 0, `every laundering attempt must be rejected; accepted: ${report.results.filter((r) => r.inGrammar).map((r) => r.name).join(', ')}`);
  assert.equal(report.rejected, report.total);
});

test('each laundering case is INDIVIDUALLY rejected, and the violation path points at the smuggled node', () => {
  for (const c of LAUNDERING_BATTERY) {
    const rec = recognize(c.expr);
    assert.equal(rec.inGrammar, false, `${c.name} (${c.smuggle}) must be out of grammar`);
    assert.equal(typeof rec.reason, 'string');
    assert.ok(rec.reason.length > 0, `${c.name} must carry a rejection reason`);
    if (c.at != null) {
      assert.equal(rec.path, c.at, `${c.name} must be caught at ${c.at} (got ${rec.path})`);
    }
  }
});

test('the battery includes DEEP-NESTED smuggles (an out-of-grammar node buried in a valid tree)', () => {
  const deep = LAUNDERING_BATTERY.filter((c) => (c.at ?? '').split('.').length >= 3);
  assert.ok(deep.length >= 5, `expected several deep-nested smuggle cases (got ${deep.length})`);
  for (const c of deep) {
    const rec = recognize(c.expr);
    assert.equal(rec.inGrammar, false, `${c.name} must be rejected`);
    // the smuggle is genuinely deep — the path descends into the tree, not just the root.
    assert.notEqual(rec.path, 'root', `${c.name} should be caught deep in the tree, not at the root`);
  }
});

// =====================================================================================
// DEFAULT-DENY CLOSURE — one smuggled node denies the WHOLE composition.
// =====================================================================================

test('default-deny: an unknown node type ANYWHERE in the tree denies the entire expression', () => {
  // a fully-valid skeleton...
  const valid = add(mul(int(2), int(3)), sum('k', int(1), int(4), variable('k')));
  assert.equal(isInGrammar(valid), true);
  // ...with ONE out-of-grammar node grafted at increasing depth — each denies the whole tree.
  const graft = { type: 'mystery-node', value: 1 };
  assert.equal(isInGrammar(add(valid, graft)), false);
  assert.equal(isInGrammar(add(int(1), mul(int(2), graft))), false);
  assert.equal(isInGrammar(sum('k', int(1), int(3), add(variable('k'), graft))), false);
});

test('NO float survives anywhere: as a value, in a rational, as an exponent, or buried deep', () => {
  assert.equal(isInGrammar(int(1.5)), false);
  assert.equal(isInGrammar(int(Number.NaN)), false);
  assert.equal(isInGrammar(int(Number.POSITIVE_INFINITY)), false);
  assert.equal(isInGrammar(rational(1, 1.5)), false);
  assert.equal(isInGrammar(pow(int(2), int(0.5))), false);
  assert.equal(isInGrammar(add(int(1), mul(int(2), int(3.0001)))), false);
});

test('symbols: a BOUND index is legal in its body; a FREE variable is denied; bounds must be literal', () => {
  // bound index k — legal inside the sum body.
  assert.equal(isInGrammar(sum('k', int(1), int(3), variable('k'))), true);
  // the same name OUTSIDE any binder — a free symbol — is denied.
  assert.equal(isInGrammar(variable('k')), false);
  // an index is NOT in scope of a sibling binder's body.
  assert.equal(isInGrammar(sum('i', int(1), int(2), sum('j', int(1), int(3), variable('i')))), true); // outer i IS in scope of inner body
  assert.equal(isInGrammar(sum('i', int(1), int(2), variable('j'))), false); // j was never bound
  // unbounded / symbolic / computed bounds are all denied.
  assert.equal(isInGrammar(sum('k', int(1), { type: 'infinity' }, variable('k'))), false);
  assert.equal(isInGrammar(sum('k', int(1), variable('n'), variable('k'))), false);
  assert.equal(isInGrammar(sum('k', int(1), add(int(1), int(2)), variable('k'))), false);
  // a negative LITERAL bound is still literal => in grammar.
  assert.equal(isInGrammar(sum('k', neg(int(2)), int(2), variable('k'))), true);
});

test('pow accepts only a literal non-negative integer exponent', () => {
  assert.equal(isInGrammar(pow(int(2), int(10))), true);
  assert.equal(isInGrammar(pow(int(2), int(0))), true);
  assert.equal(isInGrammar(pow(int(2), int(-1))), false); // inverse
  assert.equal(isInGrammar(pow(int(2), variable('n'))), false); // symbolic
  assert.equal(isInGrammar(pow(int(2), add(int(1), int(1)))), false); // computed (non-literal)
});

// =====================================================================================
// SCREEN — the firewall front-end decision (ABSTAIN+route vs PROCEED).
// =====================================================================================

test('screen: out-of-grammar => ABSTAIN + route out-of-model', () => {
  const d = screen(variable('x')); // a free symbol
  assert.equal(d.decision, SCREEN_DECISION.ABSTAIN);
  assert.equal(d.route, 'out-of-model');
  assert.equal(d.inGrammar, false);
  assert.match(d.reason, /default-deny/i);
});

test('screen: in-grammar but NO minter => ABSTAIN + route (recognition is necessary, not sufficient)', () => {
  const d = screen(sum('k', int(1), int(3), variable('k'))); // in grammar, no minter
  assert.equal(d.decision, SCREEN_DECISION.ABSTAIN);
  assert.equal(d.route, 'out-of-model');
  assert.equal(d.inGrammar, true);
  assert.match(d.reason, /no firewall minter|Wave 9/i);
});

test('screen: in-grammar WITH a minter => PROCEED (hand to the Wave-9 subprocess)', () => {
  const minter = () => ({});
  const d = screen(add(int(2), int(3)), { minter });
  assert.equal(d.decision, SCREEN_DECISION.PROCEED);
  assert.equal(d.inGrammar, true);
  assert.equal(d.reason, null);
});

// =====================================================================================
// ROUTER INTEGRATION — A4a wired into the Wave-7 computational path.
// =====================================================================================

test('GWT: a smuggled non-literal expr ABSTAINs+routes even WITH a dispatcher present (raises no rung)', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });

  // an out-of-grammar node nested in an otherwise-valid tree, attached to a computational claim.
  const smuggled = add(mul(int(2), int(3)), add(int(4), { type: 'float', value: 0.001 }));
  const r = router.route({ id: 'c1', type: 'computational', statement: 'launder a float', expr: smuggled });

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.routed, true);
  assert.equal(r.settled, false);
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED, 'no VERIFIED rung is raised');
  assert.equal(ledger.beliefOf('c1'), BELIEF.CONJECTURAL);
  assert.ok(r.advisory && r.advisory.needs_verification === true, 'routes out-of-model with an advisory payload');
  assert.match(r.advisory.reason, /grammar rejected/i);
  assert.equal(r.stamp.verifier_family, null); // no family without an artifact
  assert.equal(r.stamp.artifact_backed, false);
});

test('anti-laundering: an out-of-grammar expr cannot reach the gate even with a VALID artifact (grammar runs first)', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });

  router.decompose({ id: 'c1', type: 'computational', expr: pow(int(2), variable('n')) }); // symbolic exponent
  const artifact = mintArtifactFor(dispatcher, 'c1'); // a structurally-valid, claim-bound artifact
  const r = router.route('c1', { artifact });

  // grammar denies BEFORE the adjudication gate — the artifact is never consumed, no VERIFIED rung.
  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED);
  assert.notEqual(ledger.beliefOf('c1'), BELIEF.VERIFIED);
});

test('an in-grammar computational claim with NO minter still ABSTAINs+routes (no VERIFIED rung in Wave 8)', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger }); // no dispatcher / minter
  const r = router.route({ id: 'c1', type: 'computational', expr: sum('k', int(1), int(3), mul(variable('k'), int(2))) });

  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(r.routed, true);
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED);
  assert.equal(ledger.beliefOf('c1'), BELIEF.CONJECTURAL);
});

test('the WHOLE battery routed through the router raises NO VERIFIED rung (no minter)', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher(); // a dispatcher is present, but the grammar denies every input
  const router = new VerifyRouter({ ledger, dispatcher });

  let i = 0;
  for (const c of LAUNDERING_BATTERY) {
    const id = `lb-${i++}`;
    const r = router.route({ id, type: 'computational', expr: c.expr });
    assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN, `${c.name} must ABSTAIN through the router`);
    assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED, `${c.name} must raise no rung`);
    assert.notEqual(ledger.beliefOf(id), BELIEF.VERIFIED);
  }
});

test('REGRESSION: a Wave-7 computational claim with NO expr is unchanged (artifact still settles to VERIFIED)', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });

  router.decompose({ id: 'c1', type: 'computational' }); // no expr attached
  const r = router.route('c1', { artifact: mintArtifactFor(dispatcher, 'c1') });
  assert.equal(r.verdict, ROUTE_VERDICT.VERIFIED);
  assert.equal(ledger.rungOf('c1'), RUNG.OBSERVED);
  assert.equal(r.stamp.verifier_family, FIREWALL_FAMILY);
});

test('the persisted expr drives the grammar on a later route() (decompose stores it in meta)', () => {
  const ledger = new ClaimLedger();
  const router = new VerifyRouter({ ledger });
  // decompose with an out-of-grammar expr; route by id later — the grammar still denies it.
  router.decompose({ id: 'c1', type: 'computational', expr: { type: 'integral', var: 'x', body: variable('x') } });
  assert.deepEqual(ledger.get('c1').meta.expr, { type: 'integral', var: 'x', body: variable('x') });
  const r = router.route('c1');
  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(ledger.rungOf('c1'), RUNG.UNVERIFIED);
});

// =====================================================================================
// Introspection guards.
// =====================================================================================

test('the whitelist is the closed set of grammar node types', () => {
  assert.deepEqual([...WHITELIST].sort(), Object.values(GRAMMAR_NODE).sort());
  assert.ok(WHITELIST.includes('int') && WHITELIST.includes('sum') && WHITELIST.includes('var'));
  // a type NOT on the whitelist is denied.
  assert.equal(isInGrammar({ type: 'float', value: 1.0 }), false);
});
