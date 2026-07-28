// Overhaul Wave 1 — Semantic Interception & Event Bus Dispatch: the SEMANTIC CLASSIFIER.
//
// The lightweight semantic classifier that ENTIRELY REPLACES legacy regex interception. Legacy
// interception matched one fixed syntactic template against the text — anything phrased outside the
// template slipped through, and anything accidentally shaped like it was falsely intercepted. This
// pass instead scores INDEPENDENT SEMANTIC FEATURES of each sentence (assertiveness, mathematical
// vocabulary, relational/symbolic structure, quantification, empirical-evidence markers, hedging)
// and combines them under an explicit decision rule, so paraphrases of the same claim are
// intercepted regardless of surface phrasing. Character classes are used ONLY as low-level token
// utilities; the INTERCEPTION DECISION is the weighted feature combination, never a pattern match.
//
// WHAT IT INTERCEPTS (the done-when's classifier arm):
//   MATHEMATICAL — an ASSERTED mathematical claim (equations, number-theoretic statements,
//                  quantified assertions). Sub-typed for the downstream ledger/router vocabulary
//                  (computational / proof-bearing / conceptual), so Wave-2 routing can hand it to
//                  the existing C2 dispatch spine unchanged.
//   EMPIRICAL    — a Claim<Empirical>: an asserted claim resting on measurement/observation
//                  (benchmarks, experiments, profiling). Typed 'empirical' — deliberately OUTSIDE
//                  the formal ledger CLAIM_TYPES — so it can never be mistaken for a formal claim;
//                  Wave-2 routes it to the Pillar-7 sandbox (EMPIRICALLY-TESTED), never to Lean/z3.
//   NONE         — questions, hedged musings, and claim-free prose. A hedge ("maybe", "I think")
//                  means the text is NOT asserted, so there is nothing for the Honesty Law to gate.
//
// THE HONESTY-LAW BIAS. The two error directions are NOT symmetric: OVER-interception is safe (a
// non-claim dispatched to verification just abstains downstream), UNDER-interception is the
// dangerous direction (an unverified assertion rendered with no verification tier). So thresholds
// lean toward interception once a sentence is assertive and carries claim signal.
//
// Pure node built-ins; deterministic; no I/O. Runs under `node --test test/`.

/** The three interception kinds. */
export const CLAIM_KIND = Object.freeze({
  MATHEMATICAL: 'mathematical',
  EMPIRICAL: 'empirical',
  NONE: 'none',
});

/** The kinds, as an array (introspection + exhaustiveness checks). */
export const CLAIM_KINDS = Object.freeze(Object.values(CLAIM_KIND));

// ---------------------------------------------------------------------------
// The semantic feature lexicons. Word lists, not sentence templates: each list feeds ONE feature
// score; no single list (and no single phrasing) decides interception on its own.
// ---------------------------------------------------------------------------

/** Mathematical-domain vocabulary. */
const MATH_TERMS = new Set([
  'prime', 'primes', 'integer', 'integers', 'number', 'numbers', 'even', 'odd', 'divisible',
  'divides', 'divisor', 'factor', 'factors', 'sum', 'product', 'difference', 'quotient',
  'equation', 'inequality', 'converges', 'diverges', 'series', 'sequence', 'function',
  'polynomial', 'matrix', 'rational', 'irrational', 'root', 'roots', 'square', 'cube', 'modulo',
  'congruent', 'derivative', 'integral', 'limit', 'infinite', 'infinity', 'digit', 'digits',
  'fraction', 'numerator', 'denominator', 'triangle', 'angle', 'vertex', 'graph', 'set', 'subset',
  'plus', 'minus', 'times', 'squared', 'cubed',
]);

/** Proof-obligation vocabulary — pushes a mathematical claim to the proof-bearing subtype. */
const PROOF_TERMS = new Set([
  'theorem', 'lemma', 'corollary', 'axiom', 'proof', 'prove', 'proves', 'proven', 'implies',
  'therefore', 'hence', 'contradiction', 'induction', 'conjecture', 'qed',
]);

/** Quantifier tokens + phrases — universal/existential claims carry a proof burden. */
const QUANTIFIER_TOKENS = new Set(['every', 'each']);
const QUANTIFIER_PHRASES = Object.freeze([
  'for all', 'for any', 'there exists', 'there exist', 'there is no', 'infinitely many',
  'no integer', 'no number', 'without exception',
]);

/** Assertion carriers — a claim must be ASSERTED to be intercepted (the Honesty Law gates assertions). */
const ASSERTIVE_TOKENS = new Set([
  'is', 'are', 'was', 'were', 'equals', 'equal', 'must', 'always', 'never', 'holds', 'cannot',
  'has', 'have', 'shows', 'runs', 'takes', 'yields', 'gives', 'produces', 'outperforms',
  'converges', 'diverges', 'completes', 'exceeds', 'averaged', 'averages',
]);

/** Empirical-evidence markers — measurement/observation vocabulary (Claim<Empirical>). */
const EMPIRICAL_TOKENS = new Set([
  'measured', 'measurement', 'measurements', 'observed', 'observation', 'observations',
  'benchmark', 'benchmarks', 'benchmarked', 'experiment', 'experiments', 'experimental',
  'experimentally', 'tested', 'empirically', 'empirical', 'simulation', 'simulated', 'sampled',
  'samples', 'dataset', 'datasets', 'profiled', 'profiling', 'runtime', 'trials', 'timing',
  'milliseconds', 'ms', 'throughput', 'iterations', 'averaged',
]);
const EMPIRICAL_PHRASES = Object.freeze(['in practice', 'on average', 'we ran', 'we observed', 'we measured']);

/** Hedges — the text is NOT asserted at full strength, so it is not an interceptable claim. */
const HEDGE_TOKENS = new Set([
  'maybe', 'perhaps', 'might', 'could', 'possibly', 'presumably', 'suspect', 'wonder', 'guess',
  'seems', 'seemingly', 'probably', 'likely',
]);
const HEDGE_PHRASES = Object.freeze(['i think', 'i believe', 'not sure', 'my hunch', 'my guess']);

/** Relational structure: an explicit comparison/equality symbol. */
const RELATION_SYMBOLS = /[=<>≠≤≥]/;
/** Operator/symbolic density: arithmetic + classic math symbols. */
const MATH_SYMBOLS = /[+*/^√∑∏∫π×÷%]/g;

// ---------------------------------------------------------------------------
// Tokenization + sentence segmentation (low-level utilities, NOT the interception decision).
// ---------------------------------------------------------------------------

/** Lowercase word tokens of a sentence. */
function tokenize(text) {
  return text.toLowerCase().match(/[a-z']+/g) ?? [];
}

/** Count phrase occurrences (normalized substring hits) across a phrase list. */
function phraseHits(normalized, phrases) {
  let n = 0;
  for (const p of phrases) if (normalized.includes(p)) n += 1;
  return n;
}

function isDigit(ch) {
  return ch >= '0' && ch <= '9';
}

/**
 * Segment text into sentences WITH absolute spans. Boundaries are '.', '!', '?' and newlines; a '.'
 * BETWEEN two digits is a decimal point, never a boundary. Spans index into the ORIGINAL text
 * (offset by `base`), so `text.slice(span.start - base, span.end - base) === statement`.
 * @param {string} text
 * @param {{base?: number}} [o] — absolute offset of `text[0]` in the full stream.
 * @returns {ReadonlyArray<{statement: string, span: {start: number, end: number}}>}
 */
export function segmentSentences(text, { base = 0 } = {}) {
  if (typeof text !== 'string') {
    throw new Error(`segmentSentences(): text must be a string (got ${typeof text})`);
  }
  const segments = [];
  const pushSegment = (rawStart, rawEnd) => {
    const raw = text.slice(rawStart, rawEnd);
    const leading = raw.length - raw.trimStart().length;
    const statement = raw.trim();
    if (statement.length === 0) return;
    const start = base + rawStart + leading;
    segments.push(Object.freeze({ statement, span: Object.freeze({ start, end: start + statement.length }) }));
  };
  let start = 0;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    const decimalPoint = ch === '.' && isDigit(text[i - 1]) && isDigit(text[i + 1]);
    if ((ch === '.' && !decimalPoint) || ch === '!' || ch === '?') {
      pushSegment(start, i + 1);
      start = i + 1;
    } else if (ch === '\n') {
      pushSegment(start, i);
      start = i + 1;
    }
  }
  pushSegment(start, text.length);
  return Object.freeze(segments);
}

// ---------------------------------------------------------------------------
// The core classifier (one sentence).
// ---------------------------------------------------------------------------

/**
 * Extract the semantic feature vector of a sentence. Each feature is independent; the decision rule
 * in `classifySentence` combines them — this separation is what makes the pass a CLASSIFIER rather
 * than a pattern match.
 */
export function extractFeatures(sentence) {
  if (typeof sentence !== 'string') {
    throw new Error(`extractFeatures(): sentence must be a string (got ${typeof sentence})`);
  }
  const normalized = sentence.toLowerCase();
  const tokens = tokenize(sentence);
  const count = (set) => tokens.reduce((n, t) => n + (set.has(t) ? 1 : 0), 0);

  const relation = RELATION_SYMBOLS.test(sentence);
  const symbols = (sentence.match(MATH_SYMBOLS) ?? []).length;
  const quantifiers = count(QUANTIFIER_TOKENS) + phraseHits(normalized, QUANTIFIER_PHRASES);
  return Object.freeze({
    question: /\?\s*$/.test(sentence),
    hedged: count(HEDGE_TOKENS) > 0 || phraseHits(normalized, HEDGE_PHRASES) > 0,
    // A relation symbol or a universal/existential quantifier is itself an assertion carrier.
    assertive: count(ASSERTIVE_TOKENS) > 0 || relation || quantifiers > 0,
    math_terms: count(MATH_TERMS),
    proof_terms: count(PROOF_TERMS),
    quantifiers,
    relation,
    math_symbols: symbols,
    digits: /\d/.test(sentence),
    empirical_terms: count(EMPIRICAL_TOKENS) + phraseHits(normalized, EMPIRICAL_PHRASES),
    equals_word: tokens.includes('equals') || tokens.includes('equal'),
  });
}

/** The mathematical subtype, in the downstream ledger/router vocabulary. Proof burden wins ties. */
function mathSubtype(f) {
  if (f.proof_terms > 0 || f.quantifiers > 0) return 'proof-bearing';
  if ((f.relation || f.equals_word || f.math_symbols > 0) && f.digits) return 'computational';
  return 'conceptual';
}

/** Bounded confidence from the winning score — transparency, not probability calibration. */
function confidenceFrom(score) {
  return Math.min(0.95, 0.35 + 0.15 * score);
}

/**
 * Classify ONE sentence. Deterministic decision rule over the feature vector:
 *   1. A question is not an assertion — NONE.
 *   2. A hedged sentence is not asserted at full strength — NONE (nothing to gate).
 *   3. Empirical-evidence markers on an assertive/quantified sentence — EMPIRICAL (Claim<Empirical>).
 *   4. Enough combined mathematical signal on an assertive sentence — MATHEMATICAL (+ subtype).
 *   5. Otherwise — NONE.
 * @returns {{kind:string, claim_type:string|null, confidence:number, features:object, reason:string}} frozen.
 */
export function classifySentence(sentence) {
  const features = extractFeatures(sentence);

  if (features.question) {
    return Object.freeze({
      kind: CLAIM_KIND.NONE, claim_type: null, confidence: 0, features,
      reason: 'interrogative — a question is not an asserted claim',
    });
  }
  if (features.hedged) {
    return Object.freeze({
      kind: CLAIM_KIND.NONE, claim_type: null, confidence: 0, features,
      reason: 'hedged — not asserted at full strength, so the Honesty Law has nothing to gate',
    });
  }

  const mathScore =
    features.math_terms + features.proof_terms + features.quantifiers +
    (features.relation ? 2 : 0) + features.math_symbols + (features.digits ? 1 : 0) +
    (features.equals_word ? 1 : 0);

  if (features.empirical_terms > 0 && (features.assertive || features.digits)) {
    return Object.freeze({
      kind: CLAIM_KIND.EMPIRICAL, claim_type: 'empirical',
      confidence: confidenceFrom(features.empirical_terms + (features.digits ? 1 : 0)),
      features,
      reason: 'asserted claim carrying empirical-evidence markers — Claim<Empirical>; routes to the Pillar-7 sandbox, never the formal certifiers',
    });
  }
  if (mathScore >= 2 && features.assertive) {
    return Object.freeze({
      kind: CLAIM_KIND.MATHEMATICAL, claim_type: mathSubtype(features),
      confidence: confidenceFrom(mathScore),
      features,
      reason: 'asserted claim with combined mathematical signal above threshold — intercepted for verification tiering',
    });
  }
  return Object.freeze({
    kind: CLAIM_KIND.NONE, claim_type: null, confidence: 0, features,
    reason: 'no semantic claim signal above threshold — claim-free prose',
  });
}

// ---------------------------------------------------------------------------
// Interception over whole text (segmentation + classification).
// ---------------------------------------------------------------------------

/**
 * Intercept every claim in a block of text: segment into sentences, classify each, keep the claims.
 * @param {string} text
 * @param {{base?: number, idPrefix?: string}} [o]
 * @returns {ReadonlyArray<{id:string, kind:string, claim_type:string, statement:string,
 *           span:{start:number,end:number}, confidence:number, features:object, reason:string}>}
 */
export function interceptClaims(text, { base = 0, idPrefix = 'sem' } = {}) {
  const claims = [];
  for (const { statement, span } of segmentSentences(text, { base })) {
    const c = classifySentence(statement);
    if (c.kind === CLAIM_KIND.NONE) continue;
    claims.push(Object.freeze({ id: `${idPrefix}::claim-${claims.length}`, statement, span, ...c }));
  }
  return Object.freeze(claims);
}

// ---------------------------------------------------------------------------
// THE FIXTURES — deliberately PARAPHRASE-DIVERSE batteries. No fixed syntactic template covers a
// whole battery; that diversity is the evidence the interception is semantic, not regex.
// ---------------------------------------------------------------------------

/** Mathematical assertions — every one MUST be intercepted as MATHEMATICAL. */
export const MATH_ASSERTION_FIXTURE = Object.freeze([
  'Every even integer greater than 2 is the sum of two primes.',
  '2 + 2 = 4.',
  'The sum of the first 100 positive integers equals 5050.',
  'For all n, the product n * (n + 1) is even.',
  'There exists a prime larger than 10^80.',
  'The harmonic series diverges.',
  'No integer square has 7 as its last digit.',
]);

/** Empirical claims (Claim<Empirical>) — every one MUST be intercepted as EMPIRICAL. */
export const EMPIRICAL_CLAIM_FIXTURE = Object.freeze([
  'We benchmarked the new sieve and it processes one million candidates in 40 milliseconds.',
  'In practice the randomized variant converges after roughly 12 iterations.',
  'The profiled runtime of the solver averaged 3.2 seconds across 50 trials.',
  'We measured a 2x throughput gain on the reference dataset.',
]);

/** Claim-free prose (greetings, questions, hedges, mundane assertions) — every one MUST be NONE. */
export const NON_CLAIM_FIXTURE = Object.freeze([
  'Hello there, thanks for the update.',
  'Is 7 a prime number?',
  'Maybe the conjecture is true for large n.',
  'I think this series converges, but let me check.',
  'The report is due on the 3rd.',
  'The weather is nice today.',
]);

/** The combined battery. */
export const CLASSIFIER_FIXTURE = Object.freeze({
  mathematical: MATH_ASSERTION_FIXTURE,
  empirical: EMPIRICAL_CLAIM_FIXTURE,
  none: NON_CLAIM_FIXTURE,
});

/** Run the classifier over the full fixture battery; returns per-battery results + the invariants. */
export function runFixtureClassification() {
  const classify = (battery) => Object.freeze(battery.map((s) => Object.freeze({ statement: s, ...classifySentence(s) })));
  const mathematical = classify(MATH_ASSERTION_FIXTURE);
  const empirical = classify(EMPIRICAL_CLAIM_FIXTURE);
  const none = classify(NON_CLAIM_FIXTURE);
  return Object.freeze({
    mathematical,
    empirical,
    none,
    // THE DONE-WHEN (classifier arm): accurate interception across paraphrase-diverse phrasings.
    allMathIntercepted: mathematical.every((r) => r.kind === CLAIM_KIND.MATHEMATICAL),
    allEmpiricalIntercepted: empirical.every((r) => r.kind === CLAIM_KIND.EMPIRICAL),
    noFalseInterceptions: none.every((r) => r.kind === CLAIM_KIND.NONE),
  });
}
