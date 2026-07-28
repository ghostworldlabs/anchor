// crucible/test/pack-fixtures.mjs — shared fixtures for the pack-kit tests (NOT a
// *.test.mjs, so the runner imports it but never executes it as a suite).

export const testDocPack = {
  id: 'test-doc',
  kind: 'doc',
  version: '1.0.0',
  doc_contract: {
    required_sections: [
      { id: 'methods', title: 'Methods' },
      { id: 'prisma', title: 'PRISMA Flow' },
      { id: 'results', title: 'Results' },
    ],
  },
  evidence_standard: {
    entailment_judge_model: 'claude-opus-4-8',
    minima: { catch_rate_min: 0.9, false_positive_max: 0.1 },
  },
  rubric: {
    rubric_judge_model: 'claude-opus-4-8',
    criteria: [
      { id: 'c1', statement: 'Methods are reproducible', pass_threshold: 0.6 },
      { id: 'c2', statement: 'Evidence supports the conclusions', pass_threshold: 0.6 },
      { id: 'c3', statement: 'Limitations are stated', pass_threshold: 0.6 },
    ],
    boundary: { pass_score_min: 0.7 },
  },
};

export const wellFormedDoc = `# Methods
A reproducible protocol.

# PRISMA Flow
Records identified, screened, included.

# Results
Findings with citations.
`;

export const malformedDoc = `# Methods
A protocol.

# Results
Findings.
`; // missing the required "PRISMA Flow" section

// Labeled Layer-2 battery: 2 entailed + 1 fabricated (bad citation) + 1 over-claim.
export const battery = {
  sources: {
    s1: { id: 's1', text: 'The sky appears blue due to Rayleigh scattering.' },
    s2: { id: 's2', text: 'Water boils at 100 degrees Celsius at sea level.' },
  },
  entailed: [
    { id: 'e1', text: 'The sky appears blue due to Rayleigh scattering.', citation: 's1' },
    { id: 'e2', text: 'Water boils at 100 degrees Celsius at sea level.', citation: 's2' },
  ],
  fabricated: [
    { id: 'f1', text: 'The sky is green.', citation: 's99' }, // s99 does not exist -> caught by xref
  ],
  overclaimed: [
    { id: 'o1', text: 'The sky is always blue at every hour including night.', citation: 's1' }, // source does not support
  ],
};

// --- Wave-1 literature-review fixtures (for the seeded 'literature-review' pack) ---
// A well-formed lit-review carries every PRISMA section the pack requires; the malformed
// one is identical EXCEPT it drops the "PRISMA Flow" section (the model-free Layer-1
// validator must go RED and NAME it).
export const litReviewWellFormed = `# Methods
Eligibility criteria, information sources, and the selection process are described.

# Search Strategy
PubMed and Embase were searched 2010-01-01 to 2025-12-31 with the full query string below.

# PRISMA Flow
1,204 records identified, 980 screened, 42 included; exclusions are tabulated with reasons.

# Results
Pooled findings with per-study citations and risk-of-bias ratings.

# Discussion
Interpretation, limitations, and threats to validity.
`;

export const litReviewMissingPrisma = `# Methods
Eligibility criteria, information sources, and the selection process are described.

# Search Strategy
PubMed and Embase were searched 2010-01-01 to 2025-12-31 with the full query string below.

# Results
Pooled findings with per-study citations and risk-of-bias ratings.

# Discussion
Interpretation, limitations, and threats to validity.
`; // missing the required "PRISMA Flow" section

/** Honest deterministic entailment heuristic: entailed iff the source literally states
 *  the claim. Entailed fixtures match their source exactly; over-claims do not. */
export function stubEntail({ claim, source }) {
  return { entailed: source.text.trim() === claim.text.trim(), rationale: 'exact-support heuristic' };
}

/** A broken judge that never accepts entailment (drives the minima-FAILURE path). */
export function stubEntailRejectAll() {
  return { entailed: false, rationale: 'reject-all' };
}

/** Deterministic rubric scorers. */
export function stubScorePass({ criterion }) { return { score: 0.85, citations: [`# Results (${criterion.id})`] }; }
export function stubScoreFail({ criterion }) { return { score: 0.30, citations: [`# Results (${criterion.id})`] }; }
