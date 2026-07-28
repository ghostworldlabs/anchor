// Wave 14 — M1 read-only dispatch shim (B-shim) — closes Milestone M1 (comprehension-only preview).
//
// Exercises the REAL Wave-14 shim (src/dispatch-shim.mjs) against the REAL spine — the Wave-10
// comprehension protocol over the Wave-3 A1 ledger + Wave-7 router — proving the done-when:
//
//   the shim routes a user request to UNDERSTAND read-only and satisfies the EXACT predicate the
//   Wave-23 no-dispatch canary will later assert: NO commission-id emitted AND NO rung-flip on any
//   shim path.
//
//   Given any shim path, when Wave-14's check runs, then no commission-id is emitted and no rung is
//   flipped.
//
// Pins, in addition: the read-only structural guard (promote() is unreachable on a shim path), the
// single-pillar fail-safe (only UNDERSTAND), and the DISCRIMINATION that the check has teeth (a planted
// dispatched commission / flipped rung makes checkShimInvariants report held:false).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SHIM_PILLAR,
  SHIM_PILLARS,
  SHIM_MODE,
  ReadOnlyLedgerGuard,
  ReadOnlyDispatchShim,
  previewUnderstand,
  checkShimInvariants,
  dispatchedCommissionId,
} from '../src/dispatch-shim.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import { FIXTURE_METHOD } from '../src/comprehension.mjs';
import { int, rational, mul, add, variable, sum } from '../src/firewall-grammar.mjs';

// A handful of distinct SHIM PATHS — the done-when is over "any shim path", so we cover several.
const IN_CLASS = sum('k', int(1), int(3), mul(variable('k'), int(2))); // sum_{k=1}^{3}(k*2)=12
const OUT_OF_GRAMMAR = { type: 'limit', var: 'n', to: 'infinity', body: variable('n') };

const SHIM_PATHS = [
  {
    label: 'the pinned FIXTURE_METHOD (computational + proof + conceptual + smuggle)',
    method: FIXTURE_METHOD,
  },
  {
    label: 'an in-class computation only',
    method: { id: 'm-comp', subclaims: [{ id: 'm-comp::s', type: 'computational', expr: IN_CLASS }] },
  },
  {
    label: 'a proof-bearing claim only',
    method: { id: 'm-proof', subclaims: [{ id: 'm-proof::p', type: 'proof-bearing', statement: 'converges' }] },
  },
  {
    label: 'a conceptual claim only',
    method: { id: 'm-concept', subclaims: [{ id: 'm-concept::c', type: 'conceptual', statement: 'generalizes X' }] },
  },
  {
    label: 'a mixed ad-hoc method (rational arithmetic + free-symbol smuggle + a limit)',
    method: {
      id: 'm-mix',
      subclaims: [
        { id: 'm-mix::rat', type: 'computational', expr: add(rational(1, 2), rational(1, 3)) },
        { id: 'm-mix::free', type: 'computational', expr: add(variable('x'), int(1)) },
        { id: 'm-mix::lim', type: 'computational', expr: OUT_OF_GRAMMAR },
      ],
    },
  },
];

// =====================================================================================
// 0. Constants + the single-pillar surface.
// =====================================================================================

test('M1 exposes exactly ONE pillar (UNDERSTAND) in read-only mode', () => {
  assert.equal(SHIM_PILLAR.UNDERSTAND, 'understand');
  assert.deepEqual(SHIM_PILLARS, ['understand']);
  assert.equal(SHIM_PILLARS.length, 1);
  assert.equal(SHIM_MODE, 'read-only');
});

test('the shim routes a request to the UNDERSTAND pillar (read-only preview)', () => {
  const shim = new ReadOnlyDispatchShim({ ledger: new ClaimLedger() });
  assert.equal(shim.pillar, SHIM_PILLAR.UNDERSTAND);
  const preview = shim.dispatch({ method: SHIM_PATHS[1].method });
  assert.equal(preview.pillar, SHIM_PILLAR.UNDERSTAND);
  assert.equal(preview.mode, 'read-only');
  assert.equal(preview.read_only, true);
  // it really ran the UNDERSTAND spine: a laddered comprehension came back.
  assert.ok(preview.comprehension && Array.isArray(preview.comprehension.claims));
  assert.deepEqual(preview.comprehension.steps, ['PARSE', 'CLASSIFY', 'EMIT', 'ROUTE', 'LADDER']);
});

// =====================================================================================
// 1. THE DONE-WHEN — no commission-id emitted AND no rung-flip on ANY shim path.
// =====================================================================================

for (const path of SHIM_PATHS) {
  test(`done-when: no commission-id emitted AND no rung-flip — shim path: ${path.label}`, () => {
    const ledger = new ClaimLedger();
    const preview = previewUnderstand({ method: path.method }, { ledger });

    // The exact Wave-23 predicate holds on this shim path.
    assert.equal(preview.held, true, `invariants violated: ${preview.invariants.violations.join(' | ')}`);
    assert.equal(preview.noCommissionIdEmitted, true);
    assert.equal(preview.noRungFlip, true);
    assert.equal(preview.rungFlips.length, 0);
    assert.deepEqual(preview.invariants.dispatchedCommissionIds, []);

    // No rung in the ledger was raised above the floor (UNVERIFIED): the read-only preview settles nothing.
    for (const id of ledger.ids()) {
      assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED, `${id} left the floor on a read-only shim path`);
      assert.notEqual(ledger.beliefOf(id), BELIEF.VERIFIED);
    }

    // Every commission the shim produced is EMIT-not-dispatch (no live dispatch, no dispatched id).
    for (const c of preview.commissions) {
      assert.equal(c.emitted, true);
      assert.equal(c.dispatched, false);
      assert.equal(dispatchedCommissionId(c), null);
    }
  });
}

test('done-when, aggregate: re-running the predicate via checkShimInvariants confirms held on every path', () => {
  for (const path of SHIM_PATHS) {
    const preview = previewUnderstand({ method: path.method }, { ledger: new ClaimLedger() });
    const v = checkShimInvariants(preview);
    assert.equal(v.held, true, `${path.label}: ${v.violations.join(' | ')}`);
  }
});

// =====================================================================================
// 2. The read-only STRUCTURAL guard — a rung-flip is UNREACHABLE on a shim path.
// =====================================================================================

test('ReadOnlyLedgerGuard delegates reads + floor-only assert but THROWS on promote() (the sole rung-raiser)', () => {
  const real = new ClaimLedger();
  real.assert({ id: 'g::x', type: 'computational', statement: 's' });
  const guard = new ReadOnlyLedgerGuard(real);

  // reads + assert delegate to the real ledger.
  assert.equal(guard.has('g::x'), true);
  assert.equal(guard.rungOf('g::x'), RUNG.UNVERIFIED);
  assert.equal(guard.size, 1);
  guard.assert({ id: 'g::y', type: 'proof-bearing', statement: 't' }); // floor admission delegates
  assert.equal(real.has('g::y'), true);

  // promote() — forbidden on the read-only shim path.
  assert.throws(() => guard.promote('g::x', RUNG.OBSERVED), /READ-ONLY|promote\(\) .* forbidden/);
  // and the real ledger was NOT touched by the blocked promote.
  assert.equal(real.rungOf('g::x'), RUNG.UNVERIFIED);
});

test('the shim emits claims into the real ledger at the floor, never raising a rung', () => {
  const ledger = new ClaimLedger();
  previewUnderstand({ method: FIXTURE_METHOD }, { ledger });
  // all four fixture sub-claims landed in the real ledger...
  assert.equal(ledger.size, 4);
  // ...every one at UNVERIFIED (read-only: even the in-class computation cannot settle without a minter).
  for (const id of ledger.ids()) assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED);
});

// =====================================================================================
// 3. The check has TEETH — a planted dispatched commission / flipped rung trips it.
// =====================================================================================

test('checkShimInvariants reports held:false on a planted DISPATCHED commission (no-commission-id arm)', () => {
  const dispatched = { emitted: true, dispatched: true, commission_id: 'rp-001', skill: 'researchPrime' };
  const v = checkShimInvariants({ commissions: [dispatched], rungFlips: [] });
  assert.equal(v.held, false);
  assert.equal(v.noCommissionIdEmitted, false);
  assert.equal(v.noRungFlip, true);
  assert.deepEqual(v.dispatchedCommissionIds, ['rp-001']);
  assert.equal(dispatchedCommissionId(dispatched), 'rp-001');
});

test('checkShimInvariants reports held:false on a planted RUNG-FLIP (no-rung-flip arm)', () => {
  const flip = { id: 'x', from: RUNG.UNVERIFIED, to: RUNG.OBSERVED };
  const v = checkShimInvariants({ commissions: [], rungFlips: [flip] });
  assert.equal(v.held, false);
  assert.equal(v.noRungFlip, false);
  assert.equal(v.noCommissionIdEmitted, true);
  assert.match(v.violations.join(' '), /rung-flip/);
});

test('a dispatched envelope with no id still surfaces a dispatched commission-id placeholder (never silently passes)', () => {
  const dispatchedNoId = { emitted: true, dispatched: true };
  assert.equal(dispatchedCommissionId(dispatchedNoId), '<dispatched-commission-without-id>');
  const v = checkShimInvariants({ commissions: [dispatchedNoId], rungFlips: [] });
  assert.equal(v.held, false);
});

// =====================================================================================
// 4. Single-pillar fail-safe + input guards.
// =====================================================================================

test('the shim is single-pillar fail-safe: any non-UNDERSTAND pillar is REFUSED (never re-routed)', () => {
  const shim = new ReadOnlyDispatchShim({ ledger: new ClaimLedger() });
  for (const bad of ['solve', 'verify', 'formalize', 'contextualize', 'dialogue']) {
    assert.throws(() => shim.dispatch({ pillar: bad, method: SHIM_PATHS[1].method }), /only the understand pillar/i);
  }
  // an explicit UNDERSTAND pillar is accepted.
  const ok = shim.dispatch({ pillar: SHIM_PILLAR.UNDERSTAND, method: SHIM_PATHS[1].method });
  assert.equal(ok.held, true);
});

test('the shim guards its inputs', () => {
  const shim = new ReadOnlyDispatchShim({ ledger: new ClaimLedger() });
  assert.throws(() => shim.dispatch(null), /requires a request/);
  assert.throws(() => shim.dispatch({}), /requires request\.method/);
  assert.throws(() => new ReadOnlyDispatchShim({ ledger: {} }), /requires an A1 ClaimLedger/);
  assert.throws(() => new ReadOnlyLedgerGuard(null), /requires an A1 ClaimLedger/);
});

// =====================================================================================
// 5. Statelessness — two shim runs on fresh ledgers are independent + identical-shaped.
// =====================================================================================

test('the shim is stateless: two previews of the same request on fresh ledgers agree', () => {
  const a = previewUnderstand({ method: FIXTURE_METHOD }, { ledger: new ClaimLedger() });
  const b = previewUnderstand({ method: FIXTURE_METHOD }, { ledger: new ClaimLedger() });
  const shape = (p) => p.comprehension.claims.map((c) => [c.id, c.rung, c.belief, c.verdict]);
  assert.deepEqual(shape(a), shape(b));
  assert.equal(a.held, true);
  assert.equal(b.held, true);
});
