// Wave 3 — Typed CLAIM ledger + promote() (A1) tests.
//
// Exercises the real Wave-3 source (src/claim-ledger.mjs) to prove the done-when:
//   1. the rung ladder REFUTED < UNVERIFIED < CLAIMED < PLAUSIBILITY-CORROBORATED < CORROBORATED
//      < OBSERVED is enforced and ordered (Inc-2/Wave-3 inserted PLAUSIBILITY-CORROBORATED below
//      OBSERVED, above CLAIMED — the soft cross-family check tier);
//   2. the belief tag is a DETERMINISTIC PROJECTION of the rung (pure, total);
//   3. STICKY semantics — re-assertion never flips a rung (the Given/When/Then);
//   4. promote() is the SOLE rung-RAISER (assert cannot raise; snapshots cannot be mutated to
//      raise; only promote() lifts a rung, and only strictly upward).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  RUNGS,
  RUNG,
  FLOOR_RUNG,
  isRung,
  rungRank,
  compareRungs,
  BELIEF,
  beliefForRung,
  isAssertableAsSettled,
  CLAIM_TYPES,
  ClaimLedger,
} from '../src/claim-ledger.mjs';

// =====================================================================================
// 1. The rung ladder — ordering + validation.
// =====================================================================================

test('the ladder is exactly REFUTED < UNVERIFIED < CLAIMED < PLAUSIBILITY-CORROBORATED < CORROBORATED < OBSERVED < GROUNDED, in rank order', () => {
  assert.deepEqual(RUNGS, ['REFUTED', 'UNVERIFIED', 'CLAIMED', 'PLAUSIBILITY-CORROBORATED', 'CORROBORATED', 'OBSERVED', 'GROUNDED']);
  // the soft cross-family rung is strictly below OBSERVED and strictly above CLAIMED (Inc-2 §v2.1)
  assert.ok(rungRank('PLAUSIBILITY-CORROBORATED') < rungRank(RUNG.OBSERVED));
  assert.ok(rungRank('PLAUSIBILITY-CORROBORATED') > rungRank(RUNG.CLAIMED));
  // ...and it does NOT alias or reorder the stronger CORROBORATED rung (it sits strictly below it)
  assert.ok(rungRank('PLAUSIBILITY-CORROBORATED') < rungRank(RUNG.CORROBORATED));
  // the human-attested GROUNDED apex (Inc-2/Wave-5) is the TOP rung, strictly ABOVE OBSERVED
  assert.ok(rungRank(RUNG.GROUNDED) > rungRank(RUNG.OBSERVED));
  assert.equal(rungRank(RUNG.GROUNDED), RUNGS.length - 1);
  // strictly increasing rank
  for (let i = 1; i < RUNGS.length; i++) {
    assert.ok(rungRank(RUNGS[i]) > rungRank(RUNGS[i - 1]), `${RUNGS[i]} > ${RUNGS[i - 1]}`);
    assert.ok(compareRungs(RUNGS[i], RUNGS[i - 1]) > 0);
    assert.ok(compareRungs(RUNGS[i - 1], RUNGS[i]) < 0);
  }
  assert.equal(compareRungs(RUNG.OBSERVED, RUNG.OBSERVED), 0);
  assert.equal(compareRungs(RUNG.GROUNDED, RUNG.GROUNDED), 0);
});

test('isRung / rungRank reject non-rungs', () => {
  assert.equal(isRung('OBSERVED'), true);
  assert.equal(isRung('VERIFIED'), false); // VERIFIED is a BELIEF tag, not a rung
  assert.equal(isRung('nonsense'), false);
  assert.equal(isRung(3), false);
  assert.throws(() => rungRank('VERIFIED'), /invalid rung/);
});

test('FLOOR_RUNG is UNVERIFIED', () => {
  assert.equal(FLOOR_RUNG, RUNG.UNVERIFIED);
});

// =====================================================================================
// 2. Belief-tag = deterministic projection of the rung.
// =====================================================================================

test('beliefForRung is a deterministic, total projection of the rung', () => {
  assert.equal(beliefForRung(RUNG.REFUTED), BELIEF.REFUTED);
  assert.equal(beliefForRung(RUNG.UNVERIFIED), BELIEF.CONJECTURAL);
  assert.equal(beliefForRung(RUNG.CLAIMED), BELIEF.CONJECTURAL);
  // the soft cross-family rung is grounded-but-not-settled (CORROBORATED belief), never VERIFIED
  assert.equal(beliefForRung('PLAUSIBILITY-CORROBORATED'), BELIEF.CORROBORATED);
  assert.equal(beliefForRung(RUNG.CORROBORATED), BELIEF.CORROBORATED);
  assert.equal(beliefForRung(RUNG.OBSERVED), BELIEF.VERIFIED);
  // the human-attested GROUNDED apex is settled-class — it also projects to VERIFIED (Inc-2/Wave-5)
  assert.equal(beliefForRung(RUNG.GROUNDED), BELIEF.VERIFIED);

  // total over every ladder rung, and deterministic (same input -> same output)
  for (const r of RUNGS) {
    assert.ok(beliefForRung(r), `${r} projects to a belief`);
    assert.equal(beliefForRung(r), beliefForRung(r));
  }
  assert.throws(() => beliefForRung('VERIFIED'), /invalid rung/);
});

test('only VERIFIED (the OBSERVED + GROUNDED projection) is assertable-as-settled', () => {
  assert.equal(isAssertableAsSettled(BELIEF.VERIFIED), true);
  assert.equal(isAssertableAsSettled(beliefForRung(RUNG.OBSERVED)), true);
  // the human-attested GROUNDED apex is settled-class too (it projects to VERIFIED)
  assert.equal(isAssertableAsSettled(beliefForRung(RUNG.GROUNDED)), true);
  for (const r of [RUNG.REFUTED, RUNG.UNVERIFIED, RUNG.CLAIMED, 'PLAUSIBILITY-CORROBORATED', RUNG.CORROBORATED]) {
    assert.equal(isAssertableAsSettled(beliefForRung(r)), false, `${r} is not assertable-as-settled`);
  }
});

// =====================================================================================
// 3. assert() — typed admission at/below the floor; cannot raise a rung.
// =====================================================================================

test('assert() admits a typed claim at the floor (UNVERIFIED) by default, projecting CONJECTURAL', () => {
  const led = new ClaimLedger();
  const c = led.assert({ id: 'c1', type: 'computational', statement: '2+2=4' });
  assert.equal(c.id, 'c1');
  assert.equal(c.type, 'computational');
  assert.equal(c.rung, RUNG.UNVERIFIED);
  assert.equal(c.belief, BELIEF.CONJECTURAL);
  assert.equal(led.rungOf('c1'), RUNG.UNVERIFIED);
  assert.equal(led.beliefOf('c1'), BELIEF.CONJECTURAL);
  assert.equal(led.has('c1'), true);
  assert.equal(led.size, 1);
});

test('assert() validates the claim type', () => {
  const led = new ClaimLedger();
  assert.deepEqual(CLAIM_TYPES, ['computational', 'proof-bearing', 'conceptual']);
  for (const t of CLAIM_TYPES) {
    assert.doesNotThrow(() => led.assert({ id: `id-${t}`, type: t }));
  }
  assert.throws(() => led.assert({ id: 'bad', type: 'made-up-type' }), /invalid claim type/);
  assert.throws(() => led.assert({ id: '', type: 'computational' }), /non-empty string/);
  assert.throws(() => led.assert(null), /requires a claim object/);
});

test('assert() may admit at REFUTED (at/below the floor) but REFUSES to admit above the floor', () => {
  const led = new ClaimLedger();
  const r = led.assert({ id: 'refuted', type: 'proof-bearing', rung: RUNG.REFUTED });
  assert.equal(r.rung, RUNG.REFUTED);
  assert.equal(r.belief, BELIEF.REFUTED);
  // anything stronger than the floor is promote()'s job
  for (const above of [RUNG.CLAIMED, RUNG.CORROBORATED, RUNG.OBSERVED]) {
    assert.throws(
      () => led.assert({ id: `x-${above}`, type: 'computational', rung: above }),
      /Use promote\(\) to raise a rung/,
      `assert at ${above} must be refused`,
    );
  }
});

// =====================================================================================
// 4. promote() — the SOLE rung-raiser; strictly upward only.
// =====================================================================================

test('promote() is the only path that raises a rung, and only strictly upward', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'p', type: 'computational' }); // UNVERIFIED
  const promoted = led.promote('p', RUNG.OBSERVED, { family: 'firewall-subprocess', reason: 'literal computation' });
  assert.equal(promoted.rung, RUNG.OBSERVED);
  assert.equal(promoted.belief, BELIEF.VERIFIED);
  assert.equal(led.rungOf('p'), RUNG.OBSERVED);

  // the verifier-family stamp is recorded in history
  const promoteEvent = promoted.history.find((h) => h.event === 'promote');
  assert.ok(promoteEvent);
  assert.equal(promoteEvent.from, RUNG.UNVERIFIED);
  assert.equal(promoteEvent.rung, RUNG.OBSERVED);
  assert.equal(promoteEvent.family, 'firewall-subprocess');
});

test('promote() refuses a non-upward target (equal or lower) — it can never hold or demote', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'q', type: 'computational' });
  led.promote('q', RUNG.CLAIMED);
  assert.throws(() => led.promote('q', RUNG.CLAIMED), /must raise the rung/); // equal
  assert.throws(() => led.promote('q', RUNG.UNVERIFIED), /must raise the rung/); // lower
  assert.throws(() => led.promote('q', RUNG.REFUTED), /must raise the rung/); // lower
  assert.equal(led.rungOf('q'), RUNG.CLAIMED, 'rung unchanged after refused demotions');
});

test('promote() rejects an unknown claim or an invalid target rung', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'r', type: 'computational' });
  assert.throws(() => led.promote('does-not-exist', RUNG.CLAIMED), /no claim "does-not-exist"/);
  assert.throws(() => led.promote('r', 'VERIFIED'), /invalid target rung/); // VERIFIED is a belief, not a rung
});

test('promote() can climb multiple rungs at once (no forced single-step)', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'jump', type: 'computational' }); // UNVERIFIED
  const j = led.promote('jump', RUNG.OBSERVED); // straight to the top
  assert.equal(j.rung, RUNG.OBSERVED);
  assert.equal(j.belief, BELIEF.VERIFIED);
});

// =====================================================================================
// 5. STICKY semantics — the Given/When/Then.
// =====================================================================================

test('Given a VERIFIED claim, When re-asserted without re-verification, Then the sticky ledger holds the rung (no flip)', () => {
  const led = new ClaimLedger();
  // Given: a VERIFIED claim (OBSERVED rung, reached only via promote()).
  led.assert({ id: 'v', type: 'computational', statement: 'sum_{k=1}^{3} k = 6' });
  led.promote('v', RUNG.OBSERVED, { family: 'firewall-subprocess' });
  assert.equal(led.beliefOf('v'), BELIEF.VERIFIED);

  // When: re-assertion WITHOUT re-verification (a bare re-assert, and one that even tries to
  // re-state it back at UNVERIFIED).
  const reasserted = led.assert({ id: 'v', type: 'computational' });
  led.assert({ id: 'v', type: 'computational', rung: RUNG.UNVERIFIED, statement: 'restated' });

  // Then: the rung holds — no flip down, and the belief stays VERIFIED.
  assert.equal(reasserted.rung, RUNG.OBSERVED);
  assert.equal(reasserted.belief, BELIEF.VERIFIED);
  assert.equal(led.rungOf('v'), RUNG.OBSERVED);
  assert.equal(led.beliefOf('v'), BELIEF.VERIFIED);

  // the re-assert is audited as held (not a flip), and the statement refresh did take
  const v = led.get('v');
  assert.equal(v.statement, 'restated');
  const reEvents = v.history.filter((h) => h.event === 're-assert');
  assert.ok(reEvents.length >= 1 && reEvents.every((h) => h.held === true && h.rung === RUNG.OBSERVED));
});

test('re-assert is sticky from an intermediate rung: it never lowers AND never raises (a named higher rung is held, not honored)', () => {
  const led = new ClaimLedger();
  led.assert({ id: 's', type: 'proof-bearing' });
  led.promote('s', RUNG.CLAIMED);
  // a re-assert that NAMES a higher rung does not raise — assert is never a raiser; the
  // existing rung is held sticky (silently), so promote() remains the sole path upward.
  const namedHigher = led.assert({ id: 's', type: 'proof-bearing', rung: RUNG.OBSERVED });
  assert.equal(namedHigher.rung, RUNG.CLAIMED, 'a higher rung named on re-assert is NOT honored');
  assert.equal(namedHigher.belief, beliefForRung(RUNG.CLAIMED));
  // a re-assert that names a LOWER rung does not lower it either
  const namedLower = led.assert({ id: 's', type: 'proof-bearing', rung: RUNG.REFUTED });
  assert.equal(namedLower.rung, RUNG.CLAIMED);
  // bare re-assert holds at CLAIMED
  const held = led.assert({ id: 's', type: 'proof-bearing' });
  assert.equal(held.rung, RUNG.CLAIMED);
  assert.equal(led.rungOf('s'), RUNG.CLAIMED);
});

test('re-assert with a conflicting TYPE throws (claim identity is fixed)', () => {
  const led = new ClaimLedger();
  led.assert({ id: 't', type: 'computational' });
  assert.throws(() => led.assert({ id: 't', type: 'proof-bearing' }), /claim identity is fixed/);
  assert.equal(led.get('t').type, 'computational');
});

// =====================================================================================
// 6. Encapsulation — a handed-out snapshot cannot mutate the ledger's rung.
// =====================================================================================

test('get()/all() snapshots are frozen clones: mutating them cannot raise/lower a rung in the ledger', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'frozen', type: 'computational' });
  const snap = led.get('frozen');
  assert.ok(Object.isFrozen(snap));
  // a frozen snapshot rejects mutation (silently in sloppy mode, throws in strict ESM)
  assert.throws(() => { snap.rung = RUNG.OBSERVED; });
  // even if a caller obtained a mutable copy elsewhere, the ledger's own rung is unchanged
  assert.equal(led.rungOf('frozen'), RUNG.UNVERIFIED);

  const [only] = led.all();
  assert.ok(Object.isFrozen(only));
  assert.throws(() => { only.belief = BELIEF.VERIFIED; });
  assert.equal(led.beliefOf('frozen'), BELIEF.CONJECTURAL);
});

test('the ledger tracks multiple claims independently; ids() and size reflect them', () => {
  const led = new ClaimLedger();
  led.assert({ id: 'a', type: 'computational' });
  led.assert({ id: 'b', type: 'proof-bearing' });
  led.assert({ id: 'c', type: 'conceptual' });
  led.promote('a', RUNG.OBSERVED);
  assert.equal(led.size, 3);
  assert.deepEqual(led.ids(), ['a', 'b', 'c']);
  assert.equal(led.beliefOf('a'), BELIEF.VERIFIED);
  assert.equal(led.beliefOf('b'), BELIEF.CONJECTURAL);
  assert.equal(led.beliefOf('c'), BELIEF.CONJECTURAL);
  assert.equal(led.get('missing'), undefined);
});
