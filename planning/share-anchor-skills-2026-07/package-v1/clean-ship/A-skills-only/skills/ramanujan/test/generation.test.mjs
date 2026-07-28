// Wave 15 — Generation + typed-claim decompose (C1).
//
// Exercises the REAL Wave-15 source (src/generation.mjs) against the REAL shared spine — the Wave-3 A1
// ledger and the Wave-8 grammar builders — proving the done-when:
//
//   a NEW problem yields a CANDIDATE decomposed into TYPED claims, ALL at UNVERIFIED, in the ledger.
//
// The defining honesty invariant (the Given/When/Then): every emitted claim is at UNVERIFIED until the
// ROUTER verifies it — so even a literal computation whose expression the closed firewall grammar would
// recognize is left at UNVERIFIED by C1 (generation proposes; the Wave-7 router settles). Also pins the
// Polya/Schoenfeld candidate structure, the typed-decompose, and the pass's statelessness.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  POLYA_PHASES,
  SCHOENFELD_HEURISTIC,
  GENERATION_STEPS,
  parseProblem,
  SolveGeneration,
  generate,
  FIXTURE_PROBLEM,
  runFixtureGeneration,
} from '../src/generation.mjs';

import { ClaimLedger, RUNG, BELIEF, CLAIM_TYPES } from '../src/claim-ledger.mjs';
import { recognize } from '../src/firewall-grammar.mjs';
import { int, add, variable } from '../src/firewall-grammar.mjs';

// =====================================================================================
// 0. Constants / pipeline shape.
// =====================================================================================

test('GENERATION_STEPS is the pinned 4-step pass pipeline, in order', () => {
  assert.deepEqual(GENERATION_STEPS, ['UNDERSTAND', 'GENERATE', 'DECOMPOSE', 'EMIT']);
});

test('POLYA_PHASES is Polya\'s four phases, in order', () => {
  assert.deepEqual(POLYA_PHASES, ['UNDERSTAND', 'DEVISE_PLAN', 'CARRY_OUT', 'LOOK_BACK']);
});

// =====================================================================================
// 1. Step 1 — UNDERSTAND (parseProblem).
// =====================================================================================

test('parseProblem normalizes moves and derives deterministic ids from problem id + position', () => {
  const p = parseProblem({ id: 'p1', goal: 'do X', moves: [{ statement: 'a' }, { id: 'explicit', statement: 'b' }] });
  assert.equal(p.goal, 'do X');
  assert.equal(p.moves.length, 2);
  assert.equal(p.moves[0].id, 'p1::step-0'); // derived, no wall-clock
  assert.equal(p.moves[1].id, 'explicit'); // explicit id preserved
});

test('parseProblem rejects a malformed problem', () => {
  assert.throws(() => parseProblem(null), /problem must be an object/);
  assert.throws(() => parseProblem({ moves: [{}] }), /non-empty `goal`/);
  assert.throws(() => parseProblem({ goal: 'g', moves: [] }), /no candidate `moves`/);
  assert.throws(() => parseProblem({ goal: 'g', moves: [42] }), /must be an object/);
});

// =====================================================================================
// 2. THE DONE-WHEN — a new problem yields a candidate decomposed into typed claims, ALL UNVERIFIED.
// =====================================================================================

test('done-when: the FIXTURE_PROBLEM yields a candidate decomposed into typed claims, ALL at UNVERIFIED', () => {
  const ledger = new ClaimLedger();
  const cand = runFixtureGeneration({ ledger });

  // every emitted claim is at UNVERIFIED / CONJECTURAL — both in the candidate AND in the real ledger.
  assert.equal(cand.allUnverified, true);
  assert.equal(cand.noneSettled, true);
  assert.equal(cand.typed, true);
  assert.ok(cand.claims.length >= 3, 'a candidate decomposes into multiple typed claims');
  for (const c of cand.claims) {
    assert.equal(c.rung, RUNG.UNVERIFIED, `${c.id}: rung ${c.rung} != UNVERIFIED`);
    assert.equal(c.belief, BELIEF.CONJECTURAL, `${c.id}: belief ${c.belief} != CONJECTURAL`);
    assert.ok(CLAIM_TYPES.includes(c.claim_type), `${c.id}: ${c.claim_type} is a valid claim type`);
    // the claim truly landed in the shared ledger at UNVERIFIED.
    assert.equal(ledger.rungOf(c.id), RUNG.UNVERIFIED);
    assert.equal(ledger.beliefOf(c.id), BELIEF.CONJECTURAL);
  }

  // the whole ladder is the UNVERIFIED bucket — nothing higher.
  assert.deepEqual(Object.keys(cand.ladder), [RUNG.UNVERIFIED]);
  assert.equal(cand.ladder[RUNG.UNVERIFIED].length, cand.claims.length);
});

test('GWT: a literal computation the grammar WOULD recognize is STILL emitted UNVERIFIED (C1 proposes; the router verifies)', () => {
  const ledger = new ClaimLedger();
  const cand = runFixtureGeneration({ ledger });
  const by = Object.fromEntries(cand.claims.map((c) => [c.id, c]));

  // The two computational moves carry in-grammar expressions...
  for (const id of ['fp::direct-sum', 'fp::closed-form']) {
    const c = by[id];
    assert.equal(c.claim_type, 'computational');
    assert.equal(c.has_expr, true);
    // ...the firewall grammar would recognize them as in-class literal computations...
    const expr = ledger.get(id).meta.expr;
    assert.equal(recognize(expr).inGrammar, true, `${id} should be an in-class literal computation`);
    // ...yet C1 leaves them at UNVERIFIED. The autonomous lift is the router's job, never generation's.
    assert.equal(c.rung, RUNG.UNVERIFIED);
    assert.equal(c.belief, BELIEF.CONJECTURAL);
    assert.notEqual(c.belief, BELIEF.VERIFIED);
    assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED);
  }
});

// =====================================================================================
// 3. The Polya/Schoenfeld candidate structure + typed decompose.
// =====================================================================================

test('the candidate is structured by Polya phases: a conceptual approach (DEVISE_PLAN), typed CARRY_OUT moves, a proof-bearing LOOK_BACK', () => {
  const cand = runFixtureGeneration({ ledger: new ClaimLedger() });
  const by = Object.fromEntries(cand.claims.map((c) => [c.id, c]));

  // DEVISE_PLAN — a leading CONCEPTUAL approach claim.
  const approach = by[cand.candidate.approach.claim_id];
  assert.equal(approach.phase, 'DEVISE_PLAN');
  assert.equal(approach.claim_type, 'conceptual');

  // CARRY_OUT — the candidate moves, carried at their declared types.
  assert.equal(by['fp::direct-sum'].phase, 'CARRY_OUT');
  assert.equal(by['fp::closed-form-general'].claim_type, 'proof-bearing');

  // LOOK_BACK — the honest overall solution-correctness obligation, proof-bearing (no autonomous verifier).
  const lookBack = cand.claims.find((c) => c.phase === 'LOOK_BACK');
  assert.ok(lookBack, 'a LOOK_BACK solution-correctness claim is always emitted');
  assert.equal(lookBack.claim_type, 'proof-bearing');
  assert.match(lookBack.id, /::solution-correct$/);

  // all three claim types are present (a genuinely typed decompose).
  assert.ok(cand.countsByType.computational >= 2);
  assert.ok(cand.countsByType['proof-bearing'] >= 1);
  assert.ok(cand.countsByType.conceptual >= 1);

  // the plan is ordered: approach first, look-back last.
  assert.equal(cand.candidate.plan[0].phase, 'DEVISE_PLAN');
  assert.equal(cand.candidate.plan.at(-1).phase, 'LOOK_BACK');
});

test('every generated claim is EMITTED into the shared A1 ledger as a typed claim', () => {
  const ledger = new ClaimLedger();
  const cand = runFixtureGeneration({ ledger });
  assert.equal(ledger.size, cand.claims.length);
  for (const c of cand.claims) {
    assert.equal(ledger.has(c.id), true);
    assert.equal(ledger.get(c.id).type, c.claim_type);
    assert.equal(ledger.get(c.id).meta.generated_by, 'C1-solve-generation');
  }
});

// =====================================================================================
// 4. CONSERVATIVE type resolution (the rigorous fail-safe dispatch classifier is Wave 16).
// =====================================================================================

test('conservative typing: a declared type wins; an untyped move with an expr is computational; an untyped bare move is conceptual', () => {
  const ledger = new ClaimLedger();
  const cand = generate(
    {
      id: 'typing',
      goal: 'exercise type resolution',
      moves: [
        { id: 'typing::declared-proof', type: 'proof-bearing', statement: 'declared proof obligation' },
        { id: 'typing::untyped-expr', expr: add(int(2), int(3)), statement: 'untyped but carries a literal computation' },
        { id: 'typing::untyped-bare', statement: 'an untyped, expression-less strategic move' },
      ],
    },
    { ledger },
  );
  const by = Object.fromEntries(cand.claims.map((c) => [c.id, c]));
  assert.equal(by['typing::declared-proof'].claim_type, 'proof-bearing'); // declared wins
  assert.equal(by['typing::untyped-expr'].claim_type, 'computational'); // expr => computational (still UNVERIFIED)
  assert.equal(by['typing::untyped-bare'].claim_type, 'conceptual'); // NEVER computational without an expr
  // ...and conservative typing never settles anything.
  assert.equal(cand.allUnverified, true);
});

// =====================================================================================
// 5. Statelessness + structural read-only-ness.
// =====================================================================================

test('the generation pass is STATELESS: two generations on fresh ledgers are independent + identical in shape', () => {
  const a = runFixtureGeneration({ ledger: new ClaimLedger() });
  const b = runFixtureGeneration({ ledger: new ClaimLedger() });
  const shape = (cand) => cand.claims.map((c) => [c.id, c.claim_type, c.phase, c.rung, c.belief]);
  assert.deepEqual(shape(a), shape(b));
  assert.equal(a.allUnverified, true);
  assert.equal(b.allUnverified, true);
});

test('re-generating the SAME problem on the SAME ledger is STICKY: claims are held at UNVERIFIED (no flip, no duplication)', () => {
  const ledger = new ClaimLedger();
  const first = runFixtureGeneration({ ledger });
  const sizeAfterFirst = ledger.size;
  const second = new SolveGeneration({ ledger }).generate(FIXTURE_PROBLEM);
  assert.equal(ledger.size, sizeAfterFirst); // sticky re-assert: no new claims
  assert.equal(second.allUnverified, true);
  for (const c of second.claims) assert.equal(ledger.rungOf(c.id), RUNG.UNVERIFIED);
});

test('generation NEVER raises a rung: it wires no dispatcher and never settles a computation (the router is the sole settler)', () => {
  // Even with a problem made entirely of in-grammar literal computations, C1 emits everything UNVERIFIED.
  const ledger = new ClaimLedger();
  const cand = generate(
    {
      id: 'allcomp',
      goal: 'compute things',
      moves: [
        { id: 'allcomp::a', type: 'computational', expr: add(int(1), int(2)) },
        { id: 'allcomp::b', type: 'computational', expr: add(int(40), int(2)) },
      ],
    },
    { ledger },
  );
  assert.equal(cand.allUnverified, true);
  assert.equal(cand.noneSettled, true);
  for (const id of ['allcomp::a', 'allcomp::b']) assert.equal(ledger.rungOf(id), RUNG.UNVERIFIED);
});

// =====================================================================================
// 6. Constructor contract.
// =====================================================================================

test('SolveGeneration requires an A1 ledger', () => {
  assert.throws(() => new SolveGeneration({}), /requires an A1 ClaimLedger/);
  assert.throws(() => new SolveGeneration({ ledger: {} }), /requires an A1 ClaimLedger/);
});

test('SCHOENFELD_HEURISTIC exposes a heuristic vocabulary used to tag candidate moves (advisory only)', () => {
  assert.equal(typeof SCHOENFELD_HEURISTIC.DIRECT_COMPUTE, 'string');
  const cand = runFixtureGeneration({ ledger: new ClaimLedger() });
  const direct = cand.claims.find((c) => c.id === 'fp::direct-sum');
  assert.equal(direct.heuristic, SCHOENFELD_HEURISTIC.DIRECT_COMPUTE);
});
