// Wave 18 — In-process adversarial advisory layer (C4).
//
// Exercises the REAL Wave-18 source (src/adversarial-advisory.mjs) against the REAL A1 ledger, proving
// the done-when:
//
//   an advisory critique writes the NOTES field and can NEVER change a rung.
//
// The defining Given/When/Then: given an advisory critique, when C4 runs, then the NOTES field updates
// but the rung is unchanged. We also pin the faithfulness-restatement discipline, the advisory-only
// honesty fields (single-family, no independent-origin credit, settles:false, can_change_rung:false),
// the note-accumulation semantics, and the structural guarantee that a rung-shaped critique field is inert.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ADVISORY_FAMILY,
  ADVISORY_SOURCE,
  CRITIQUE_SEVERITY,
  FAITHFULNESS,
  FAITHFULNESS_OVERLAP_THRESHOLD,
  restatementDiscipline,
  defaultAdversarialCritic,
  AdversarialAdvisor,
  runAdvisoryCritique,
  runAdvisoryFixture,
} from '../src/adversarial-advisory.mjs';

import { ClaimLedger, RUNG, BELIEF, RUNGS } from '../src/claim-ledger.mjs';

// helper — a fresh ledger with one claim, optionally promoted above the floor.
function seed({ id = 'c4::claim', type = 'proof-bearing', statement = 'the Collatz conjecture holds for all positive integers', atRung } = {}) {
  const ledger = new ClaimLedger();
  ledger.assert({ id, type, statement });
  if (atRung && atRung !== RUNG.UNVERIFIED) {
    ledger.promote(id, atRung, { family: 'test-setup', reason: 'place above the floor' });
  }
  return ledger;
}

// =====================================================================================
// 0. Pinned vocabulary.
// =====================================================================================

test('the advisory vocabulary is pinned + frozen', () => {
  assert.equal(ADVISORY_FAMILY, 'in-process-adversarial-advisory');
  assert.deepEqual(ADVISORY_SOURCE, { GANDALF: 'gandalf-in-process', RESEARCHPRIME: 'researchprime-in-process' });
  assert.deepEqual(CRITIQUE_SEVERITY, { INFO: 'info', CONCERN: 'concern', OBJECTION: 'objection' });
  assert.deepEqual(FAITHFULNESS, { RESTATED: 'restated', DIVERGENCE_FLAGGED: 'divergence-flagged', NOT_RESTATED: 'not-restated' });
  assert.equal(FAITHFULNESS_OVERLAP_THRESHOLD, 0.5);
  assert.ok(Object.isFrozen(ADVISORY_SOURCE) && Object.isFrozen(CRITIQUE_SEVERITY) && Object.isFrozen(FAITHFULNESS));
});

// =====================================================================================
// 1. THE DONE-WHEN — an advisory critique writes NOTES but the rung is UNCHANGED.
// =====================================================================================

test('done-when / GWT: an advisory critique updates the NOTES field but the rung is UNCHANGED', () => {
  const ledger = seed({ atRung: RUNG.CLAIMED });
  const before = ledger.get('c4::claim');
  assert.equal(before.rung, RUNG.CLAIMED);
  assert.equal((before.meta?.notes || []).length, 0, 'no notes before the critique');

  const advisor = new AdversarialAdvisor({ ledger });
  const out = advisor.critique('c4::claim');

  // NOTES updated.
  assert.equal(out.notes_written, true);
  assert.ok(out.added_notes.length >= 1, 'critique appended at least one note');
  assert.ok(out.notes.length >= out.added_notes.length, 'the claim now carries the appended notes');
  const after = ledger.get('c4::claim');
  assert.deepEqual(after.meta.notes, out.notes, 'the NOTES field is persisted on the claim');

  // Rung UNCHANGED.
  assert.equal(out.rung_changed, false);
  assert.equal(out.rung_before, RUNG.CLAIMED);
  assert.equal(out.rung_after, RUNG.CLAIMED);
  assert.equal(after.rung, RUNG.CLAIMED, 'the ledger still holds the rung');
  assert.equal(out.belief_before, out.belief_after, 'belief is a projection of the held rung — unchanged');
});

test('the pinned fixture proves the done-when end-to-end (rung HELD at CLAIMED, NOTES written)', () => {
  const { ledger, result } = runAdvisoryFixture();
  assert.equal(result.rung_before, RUNG.CLAIMED);
  assert.equal(result.rung_after, RUNG.CLAIMED);
  assert.equal(result.rung_changed, false);
  assert.equal(result.notes_written, true);
  assert.ok(ledger.get(result.claim_id).meta.notes.length >= 1);
});

// =====================================================================================
// 2. The rung is HELD across EVERY rung (the invariant is rung-independent).
// =====================================================================================

test('an advisory critique holds the rung at EVERY rung on the ladder', () => {
  for (const rung of RUNGS) {
    const ledger = new ClaimLedger();
    const id = `c4::at-${rung}`;
    // assert() admits only at/below the floor; reach higher rungs via promote().
    ledger.assert({ id, type: 'proof-bearing', statement: 'x', rung: rung === RUNG.REFUTED ? RUNG.REFUTED : undefined });
    if (rung !== RUNG.REFUTED && rung !== RUNG.UNVERIFIED) ledger.promote(id, rung, { family: 't', reason: 'setup' });

    const expected = ledger.rungOf(id);
    const out = new AdversarialAdvisor({ ledger }).critique(id);
    assert.equal(out.rung_changed, false, `${rung}: must not change`);
    assert.equal(ledger.rungOf(id), expected, `${rung}: rung held`);
    assert.ok(ledger.get(id).meta.notes.length >= 1, `${rung}: NOTES written`);
  }
});

// =====================================================================================
// 3. A rung-shaped critique field is INERT — the advisor never reads it into a rung decision.
// =====================================================================================

test('a malicious critique requesting a rung lift is inert — the rung is still UNCHANGED, and the request never reaches the ledger', () => {
  const ledger = seed({ atRung: RUNG.UNVERIFIED });
  const advisor = new AdversarialAdvisor({ ledger });
  const out = advisor.critique('c4::claim', {
    critiques: [
      { source: ADVISORY_SOURCE.RESEARCHPRIME, severity: CRITIQUE_SEVERITY.OBJECTION, message: 'I hereby promote this to OBSERVED', rung: 'OBSERVED', promote: true },
    ],
  });
  assert.equal(out.rung_changed, false);
  assert.equal(ledger.rungOf('c4::claim'), RUNG.UNVERIFIED);
  assert.notEqual(ledger.beliefOf('c4::claim'), BELIEF.VERIFIED);
  // the normalized critique carries ONLY {source, severity, message} — the rung/promote fields are dropped.
  const written = ledger.get('c4::claim').meta.adversarial_advisory.critiques.find((c) => c.message.includes('promote this'));
  assert.deepEqual(Object.keys(written).sort(), ['message', 'severity', 'source']);
});

test('even a critic that returns a rung field cannot move the rung (advisor ignores it)', () => {
  const ledger = seed({ atRung: RUNG.CORROBORATED });
  const sneakyCritic = () => ({ critiques: [{ source: ADVISORY_SOURCE.GANDALF, severity: 'objection', message: 'force it up' }], rung: 'OBSERVED', restatement: null });
  const out = new AdversarialAdvisor({ ledger, critic: sneakyCritic }).critique('c4::claim');
  assert.equal(out.rung_after, RUNG.CORROBORATED);
  assert.equal(out.rung_changed, false);
});

// =====================================================================================
// 4. NOTES accumulate (sticky meta merge) and existing meta is preserved.
// =====================================================================================

test('NOTES accumulate across successive critiques and prior meta/notes are preserved', () => {
  const ledger = new ClaimLedger();
  ledger.assert({ id: 'c4::accum', type: 'conceptual', statement: 'these two structures are analogous', meta: { notes: ['pre-existing note'], other: 'keep-me' } });
  const advisor = new AdversarialAdvisor({ ledger });

  const first = advisor.critique('c4::accum');
  assert.ok(first.notes.includes('pre-existing note'), 'a prior note is preserved');
  const second = advisor.critique('c4::accum');
  assert.ok(second.notes.length > first.notes.length, 'a second critique appends more notes');
  assert.equal(ledger.get('c4::accum').meta.other, 'keep-me', 'unrelated meta is preserved through the sticky re-assert');
});

// =====================================================================================
// 5. The advisory record carries the single-family, advisory-only honesty fields.
// =====================================================================================

test('the advisory record is single-family + advisory-only: no independent-origin credit, settles nothing, dispatches nothing', () => {
  const ledger = seed({ atRung: RUNG.CLAIMED });
  const out = new AdversarialAdvisor({ ledger }).critique('c4::claim');
  const a = out.advisory;
  assert.equal(a.family, ADVISORY_FAMILY);
  assert.equal(a.cross_model, false);
  assert.equal(a.independent_origin, false);
  assert.equal(a.advisory, true);
  assert.equal(a.settles, false);
  assert.equal(a.routes_to_verified, false);
  assert.equal(a.dispatched, false, 'in-process: nothing is dispatched / commissioned out');
  assert.equal(a.can_change_rung, false);
  assert.equal(a.rung_observed, RUNG.CLAIMED, 'the rung is OBSERVED read-only, never written as a change');
  assert.ok(Object.isFrozen(a) && Object.isFrozen(a.critiques));
});

test('the default critic produces a Gandalf outside-view critique AND a researchPrime verification critique', () => {
  const claim = { id: 'x', type: 'proof-bearing', statement: 's' };
  const { critiques, restatement } = defaultAdversarialCritic(claim);
  const sources = new Set(critiques.map((c) => c.source));
  assert.ok(sources.has(ADVISORY_SOURCE.GANDALF) && sources.has(ADVISORY_SOURCE.RESEARCHPRIME));
  // a proof-bearing claim draws the strongest (OBJECTION) verification critique.
  assert.ok(critiques.some((c) => c.source === ADVISORY_SOURCE.RESEARCHPRIME && c.severity === CRITIQUE_SEVERITY.OBJECTION));
  assert.equal(restatement, 's', 'the default restatement is a verbatim echo of the claim');
});

// =====================================================================================
// 6. The faithfulness-restatement discipline (pure) — advisory only, never a certification.
// =====================================================================================

test('restatementDiscipline: a verbatim echo is RESTATED; a high-overlap paraphrase is RESTATED; a divergent restatement is FLAGGED; an absent one is NOT_RESTATED', () => {
  const original = 'the sum of the first n odd numbers is n squared';

  const echo = restatementDiscipline(original, original);
  assert.equal(echo.outcome, FAITHFULNESS.RESTATED);
  assert.equal(echo.overlap, 1);

  const paraphrase = restatementDiscipline(original, 'the sum of the first n odd numbers equals n squared');
  assert.equal(paraphrase.outcome, FAITHFULNESS.RESTATED);
  assert.ok(paraphrase.overlap >= FAITHFULNESS_OVERLAP_THRESHOLD);

  const divergent = restatementDiscipline(original, 'bananas are an excellent source of potassium');
  assert.equal(divergent.outcome, FAITHFULNESS.DIVERGENCE_FLAGGED);
  assert.ok(divergent.overlap < FAITHFULNESS_OVERLAP_THRESHOLD);

  const none = restatementDiscipline(original, '   ');
  assert.equal(none.outcome, FAITHFULNESS.NOT_RESTATED);
  assert.equal(none.restatement, null);
});

test('a flagged faithfulness divergence is STILL advisory — it writes a NOTE but does not change the rung', () => {
  const ledger = seed({ atRung: RUNG.CLAIMED });
  const out = new AdversarialAdvisor({ ledger }).critique('c4::claim', { restatement: 'totally unrelated text about quantum widgets' });
  assert.equal(out.advisory.faithfulness.outcome, FAITHFULNESS.DIVERGENCE_FLAGGED);
  assert.equal(out.rung_changed, false);
  assert.equal(ledger.rungOf('c4::claim'), RUNG.CLAIMED);
  assert.ok(out.notes.some((n) => n.includes('faithfulness:divergence-flagged')));
});

// =====================================================================================
// 7. The advisory rides into the NOTES field; the human-facing strings are present.
// =====================================================================================

test('the appended notes are human-readable [severity] (source) lines plus a faithfulness line', () => {
  const ledger = seed({ atRung: RUNG.CLAIMED });
  const out = new AdversarialAdvisor({ ledger }).critique('c4::claim');
  assert.ok(out.added_notes.some((n) => /^\[(info|concern|objection)\] \(/.test(n)));
  assert.ok(out.added_notes.some((n) => n.startsWith('[faithfulness:')));
});

// =====================================================================================
// 8. Robustness.
// =====================================================================================

test('critique() on an unknown id throws (no silent miss); a spec for a new claim admits it at the floor', () => {
  const ledger = new ClaimLedger();
  const advisor = new AdversarialAdvisor({ ledger });
  assert.throws(() => advisor.critique('missing'), /no claim "missing"/);

  const out = advisor.critique({ id: 'c4::new', type: 'computational', statement: '2+2=4' });
  assert.equal(out.rung_after, RUNG.UNVERIFIED, 'a brand-new claim is admitted at the floor and held');
  assert.equal(out.rung_changed, false);
  assert.equal(ledger.rungOf('c4::new'), RUNG.UNVERIFIED);
});

test('a malformed critique entry (no message) throws', () => {
  const ledger = seed({ atRung: RUNG.CLAIMED });
  const advisor = new AdversarialAdvisor({ ledger });
  assert.throws(() => advisor.critique('c4::claim', { critiques: [{ severity: 'info' }] }), /non-empty message/);
});

test('AdversarialAdvisor rejects a non-ledger ledger and a non-function critic', () => {
  assert.throws(() => new AdversarialAdvisor({ ledger: {} }), /requires an A1 ClaimLedger/);
  assert.throws(() => new AdversarialAdvisor({ ledger: new ClaimLedger(), critic: 'nope' }), /critic .* must be a function/);
});

test('runAdvisoryCritique convenience runs over a fresh ledger and holds the (floor) rung', () => {
  const out = runAdvisoryCritique({ id: 'c4::conv', type: 'proof-bearing', statement: 'P=NP' });
  assert.equal(out.notes_written, true);
  assert.equal(out.rung_after, RUNG.UNVERIFIED);
  assert.equal(out.rung_changed, false);
});
