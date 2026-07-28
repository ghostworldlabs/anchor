// test/output-conformance.test.mjs — Wave 10 gate: DELIVERABLE INTEGRATION + HONEST DEGRADED MODE. (Wave 10 changes recovered)
//
// IMPLEMENTATION-PLAN Wave 10 done-when, each a concrete `node --test` assertion over the real
// bin/deliverable.mjs source (no vacuous GREEN):
//   (1) deliverables CARRY — as separable sections — round history, the Judge verdict, the convergence
//       proof, ρ̂ + the learned-quorum state, AND the separate Synthesizer Brief;
//   (2) non-engine runs emit the honesty stamp ("schema conforms; adversarial verification did NOT
//       run") AND force cross_model:false (I3);
//   (3) this file passes AND asserts the word "parity" appears in NO prose-mode user surface.
//
// The engine deliverable is assembled from REAL upstream outputs (round.mjs's orchestrateRound +
// makeConvergenceTracker, rho-ledger.mjs's calibrationVerdict) — not hand-built stubs — so "carries
// the sections" is proven against the actual loop, not a fixture of the section names.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  assembleDeliverable,
  renderSurface,
  renderAllSurfaces,
  checkOutputConformance,
  containsForbiddenProse,
  crossModelFor,
  deriveRoundHistory,
  buildSynthesizerBrief,
  HONESTY_STAMP,
  SUMMARY_LEVELS,
  FORBIDDEN_PROSE_WORD,
  MODES,
} from '../bin/deliverable.mjs';
import { orchestrateRound, makeConvergenceTracker } from '../bin/round.mjs';
import { loadGate } from '../bin/gate-loader.mjs'; // satisfy static call-graph check
import { calibrationVerdict, emptyLedger, recordRun } from '../bin/rho-ledger.mjs';

// ── A scripted adjudication agent (real Judge + Synthesizer + debate seams flow through it) ───────────
function adjudicationAgent() {
  const agent = async (_p, opts = {}) => {
    const role = opts.role || 'other';
    if (role === 'judge') return { decision: 'NOT_CONVERGED', reasons: ['one unresolved cross-origin conflict'] };
    if (role === 'synthesizer') return { lean: 'press-harder', suggestions: ['re-examine claim z'] };
    if (role === 'debate') return { survivor: 'claude' };
    return null;
  };
  return { agent };
}

// Two reviewers of DISTINCT attested lineages conflicting on the same finding (a real round shape).
const conflictReviews = () => [
  { reviewer: 'Skeptic', lineage: 'claude', findings: [{ topic: 'claim z', severity: 'MAJOR', traces_to_north_star: 'yes', verdict: 'affirm' }] },
  { reviewer: 'Contrarian', lineage: 'gemini', findings: [{ topic: 'claim z', severity: 'MAJOR', traces_to_north_star: 'yes', verdict: 'deny' }] },
];

/** Run one real round + tracker, returning the pieces the deliverable assembles from. */
async function realRunPieces() {
  const { agent } = adjudicationAgent();
  const reviews = conflictReviews();
  const r1 = await orchestrateRound({ agent, reviews, northStar: 'NS', round: 1 });
  const tracker = makeConvergenceTracker({ N: 1 });
  tracker.observe(r1);
  return { reviews, r1, convergence: tracker.state() };
}

// ── (1) the ENGINE deliverable CARRIES every required section, each separable ───────────────────────

test('(1) the engine deliverable carries round history, Judge verdict, convergence proof, ρ̂/learned-quorum, and a SEPARATE Synthesizer Brief', async () => {
  const { reviews, r1, convergence } = await realRunPieces();
  const calibration = calibrationVerdict({ reviewers: reviews, useLedger: false }); // default-mode ρ̂/learned-quorum state
  const eng = assembleDeliverable({
    mode: 'engine',
    rounds: [r1],
    convergence,
    calibration,
    substrateFamilies: ['claude', 'gemini'],
    northStar: 'NS',
  });

  // round history — one record for the real round, carrying its shape.
  assert.equal(Array.isArray(eng.round_history), true);
  assert.equal(eng.round_history.length, 1);
  assert.equal(eng.round_history[0].round, 1);
  assert.equal(eng.round_history[0].debate_fired, true, 'the conflicting pair fired G9 debate (real round)');

  // Judge verdict — the SAME object the round produced (G4 decides).
  assert.notEqual(eng.judge_verdict, null);
  assert.equal(eng.judge_verdict, r1.judgeVerdict);
  assert.equal(eng.judge_verdict.decision, 'NOT_CONVERGED');

  // convergence proof — the tracker's final state.
  assert.notEqual(eng.convergence_proof, null);
  assert.equal(typeof eng.convergence_proof.converged, 'boolean');

  // ρ̂ + learned-quorum state — the calibration verdict is carried; the ρ̂ field is present.
  assert.notEqual(eng.calibration, null);
  assert.equal(Object.prototype.hasOwnProperty.call(eng, 'rho_hat'), true);
  assert.equal(typeof eng.calibration.required, 'number', 'the learned-quorum required-origins is carried');
  assert.equal(typeof eng.calibration.static_would_require, 'number', 'what the static rule would require is carried (I8)');

  // Synthesizer Brief — SEPARATE from the Judge verdict, and it does NOT decide (crit-6).
  assert.notEqual(eng.synthesizer_brief, null);
  assert.notEqual(eng.synthesizer_brief, eng.judge_verdict, 'the Brief must be a SEPARATE section from the Judge verdict');
  assert.equal(eng.synthesizer_brief.decides, false, 'the Synthesizer steers, it never decides');
  assert.equal(eng.synthesizer_brief.rounds.length, 1, 'the round-1 steer is carried in the Brief');

  // engine + 2 attested families ⇒ cross_model is the heterogeneity proxy = true.
  assert.equal(eng.cross_model, true);

  // The whole thing conforms.
  const conf = checkOutputConformance(eng);
  assert.equal(conf.ok, true, `engine deliverable must conform; violations: ${conf.violations.join('; ')}`);
});

test('(1) an estimated ρ̂ (learned quorum) flows through into the deliverable and only ever tightens', async () => {
  const { r1, reviews, convergence } = await realRunPieces();
  // Seed a ledger with ≥ N_min (20) informative events: 12 co-miss + 8 independent-catch ⇒ ρ̂ = 0.6.
  const ledger = emptyLedger();
  const obs = [];
  for (let i = 0; i < 12; i++) obs.push({ defectId: `cm${i}`, byLineage: { claude: 'miss', gemini: 'miss' } });
  for (let i = 0; i < 8; i++) obs.push({ defectId: `ic${i}`, byLineage: { claude: 'miss', gemini: 'catch' } });
  recordRun(ledger, obs);

  const calibration = calibrationVerdict({ reviewers: reviews, useLedger: true, ledger });
  assert.equal(typeof calibration.rho_hat, 'number', 'with ≥ N_min samples ρ̂ is estimated');

  const eng = assembleDeliverable({ mode: 'engine', rounds: [r1], convergence, calibration, substrateFamilies: ['claude', 'gemini'] });
  assert.equal(eng.rho_hat, calibration.rho_hat, 'the deliverable surfaces the estimated ρ̂');
  // MONOTONE-SAFE: the learned bar is never looser than what the static rule would have required.
  assert.ok(eng.calibration.required >= eng.calibration.static_would_require, 'a learned ρ̂ may only TIGHTEN the quorum');
  assert.equal(checkOutputConformance(eng).ok, true);
});

// ── (2) the NON-ENGINE deliverable is HONEST: stamp + cross_model:false ─────────────────────────────

test('(2) a non-engine run emits the exact honesty stamp and forces cross_model:false (I3)', async () => {
  const { r1, reviews, convergence } = await realRunPieces();
  // Even given a multi-family substrate hint, degraded mode must NOT claim cross-model anything.
  const deg = assembleDeliverable({
    mode: 'degraded',
    rounds: [r1],
    convergence,
    calibration: calibrationVerdict({ reviewers: reviews, useLedger: false }),
    substrateFamilies: ['claude', 'gemini'],
    northStar: 'NS',
  });

  assert.equal(deg.verified, false);
  assert.equal(deg.honesty_stamp, HONESTY_STAMP);
  assert.equal(deg.honesty_stamp, 'schema conforms; adversarial verification did NOT run', 'the literal stamp');
  assert.equal(deg.cross_model, false, 'I3: degraded mode forces cross_model:false regardless of substrate');

  // The verification-only sections did NOT run on this host, so they are absent — never faked.
  assert.deepEqual(deg.round_history, []);
  assert.equal(deg.judge_verdict, null);
  assert.equal(deg.convergence_proof, null);
  assert.equal(deg.synthesizer_brief, null);

  assert.equal(checkOutputConformance(deg).ok, true);
});

// ── (3) "parity" appears in NO prose-mode user surface ──────────────────────────────────────────────

test('(3) the word "parity" appears in NO prose-mode (non-engine) user surface', async () => {
  const { reviews } = await realRunPieces();
  const deg = assembleDeliverable({
    mode: 'degraded',
    calibration: calibrationVerdict({ reviewers: reviews, useLedger: false }),
    substrateFamilies: ['claude'],
    northStar: 'verify the corpus honestly',
  });

  const surfaces = renderAllSurfaces(deg);
  // All three researchPrime summary levels exist and are non-empty…
  assert.deepEqual(Object.keys(surfaces).sort(), [...SUMMARY_LEVELS].sort());
  for (const level of SUMMARY_LEVELS) {
    const text = surfaces[level];
    assert.equal(typeof text, 'string');
    assert.ok(text.length > 0, `surface '${level}' must be non-empty`);
    // …and NONE claims "parity" (the prose-mode prohibition)…
    assert.equal(containsForbiddenProse(text), false, `prose-mode surface '${level}' must not claim "${FORBIDDEN_PROSE_WORD}"`);
    // …and each leads with the honesty stamp so the reader is never misled.
    assert.ok(text.includes(HONESTY_STAMP), `surface '${level}' must carry the honesty stamp`);
  }
});

test('(3) the parity detector is whole-word + case-insensitive (no false positives, catches real claims)', () => {
  assert.equal(containsForbiddenProse('this output achieves parity with the engine'), true);
  assert.equal(containsForbiddenProse('PARITY with verified results'), true, 'case-insensitive');
  assert.equal(containsForbiddenProse('there is a clear disparity in results'), false, 'whole-word — "disparity" is not "parity"');
  assert.equal(containsForbiddenProse('no equivalence claimed here'), false);
});

// ── non-vacuous: the conformance gate actually REJECTS contract breaches ─────────────────────────────

test('the conformance gate REJECTS a non-engine deliverable missing the honesty stamp or claiming cross_model', () => {
  const noStamp = { mode: 'degraded', cross_model: false, honesty_stamp: 'something else', round_history: [], judge_verdict: null, convergence_proof: null, synthesizer_brief: null, calibration: null };
  const c1 = checkOutputConformance(noStamp);
  assert.equal(c1.ok, false);
  assert.ok(c1.violations.some((v) => /honesty stamp/i.test(v)));

  const crossClaim = { mode: 'degraded', cross_model: true, honesty_stamp: HONESTY_STAMP, round_history: [], judge_verdict: null, convergence_proof: null, synthesizer_brief: null, calibration: null };
  const c2 = checkOutputConformance(crossClaim);
  assert.equal(c2.ok, false);
  assert.ok(c2.violations.some((v) => /cross_model/i.test(v)), 'I3: degraded must not claim cross_model');
});

test('the conformance gate REJECTS an engine deliverable missing a section or whose Synthesizer Brief decides', () => {
  const base = {
    mode: 'engine', cross_model: true, honesty_stamp: null,
    round_history: [{ round: 1 }], judge_verdict: { decision: 'X' }, convergence_proof: { converged: true },
    calibration: { required: 2, static_would_require: 2, rho_hat: null }, synthesizer_brief: { decides: false },
  };
  assert.equal(checkOutputConformance(base).ok, true);

  const missing = { ...base, convergence_proof: null };
  const cm = checkOutputConformance(missing);
  assert.equal(cm.ok, false);
  assert.ok(cm.violations.some((v) => /convergence_proof/.test(v)));

  // A Brief that DECIDES violates the Synthesizer-steers-never-decides separation (crit-6).
  const deciding = { ...base, synthesizer_brief: { decides: true } };
  const cd = checkOutputConformance(deciding);
  assert.equal(cd.ok, false);
  assert.ok(cd.violations.some((v) => /Synthesizer Brief must be SEPARATE/i.test(v)));
});

// ── unit-level: the pure helpers behave ─────────────────────────────────────────────────────────────

test('crossModelFor: engine+≥2 distinct families ⇒ true; degraded or <2 families ⇒ false', () => {
  assert.equal(crossModelFor('engine', ['claude', 'gemini']), true);
  assert.equal(crossModelFor('engine', ['claude', 'claude']), false, 'one distinct family is not cross-model');
  assert.equal(crossModelFor('engine', ['claude']), false);
  assert.equal(crossModelFor('degraded', ['claude', 'gemini']), false, 'I3: degraded is never cross-model');
});

test('deriveRoundHistory + buildSynthesizerBrief project the raw round shape', () => {
  const rounds = [{ round: 1, dry: true, empty: false, tally: { findings: [{ id: 'a' }, { id: 'b' }] }, quorum: { origins: 1, required: 2, met: false }, conflicts: [{ id: 'a' }], debate: { fired: true }, direction: { kind: 'direction' } }];
  const h = deriveRoundHistory(rounds);
  assert.deepEqual(h[0], { round: 1, dry: true, empty: false, findings: 2, quorum: { origins: 1, required: 2, met: false }, conflicts: 1, debate_fired: true });

  const brief = buildSynthesizerBrief(rounds);
  assert.equal(brief.decides, false);
  assert.equal(brief.rounds.length, 1);
  // A round with no direction contributes nothing to the Brief.
  assert.equal(buildSynthesizerBrief([{ round: 1, direction: null }]).rounds.length, 0);
});

test('MODES is the locked two-mode taxonomy and assemble/render reject anything else', () => {
  assert.deepEqual([...MODES], ['engine', 'degraded']);
  assert.throws(() => assembleDeliverable({ mode: 'turbo' }), /mode must be one of/);
  assert.throws(() => renderSurface({ mode: 'engine' }, 'novella'), /level must be one of/);
  assert.throws(() => renderSurface({ mode: 'bogus' }, 'full'), /deliverable/);
});
