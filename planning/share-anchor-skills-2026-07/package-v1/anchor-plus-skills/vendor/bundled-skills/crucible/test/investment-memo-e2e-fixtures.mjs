// crucible/test/investment-memo-e2e-fixtures.mjs — Wave 4 (investment-memo end-to-end)
// fixtures. The exact mirror of lit-review-e2e-fixtures.mjs, proving the SAME kit drives a
// second domain pack with only new config + data (no engine change — the inclusion test).
//
// NOT a `*.test.mjs`, so the runner imports it but never executes it as a suite. It supplies:
//   - the REAL investment-memo deliverable (clean + planted-fabrication variants, loaded from
//     the committed .md artifacts under fixtures/investment-memo/),
//   - small inline Layer-1 fixtures (well-formed + a missing-Valuation-section memo) for the
//     model-free doc-contract def test,
//   - the COMMITTED labeled N+N+N evidence battery: N entailed + N fabricated + N over-claimed,
//     each with its audited-filing source map (every PRIMARY source carries an as-of date +
//     jurisdiction, per the pack's evidence standard),
//   - the deliverable's own clean + planted claim sets (for the per-deliverable Layer-2 run),
//   - a LABEL-BLIND deterministic entailment heuristic and a LABEL-BLIND deterministic rubric
//     scorer, so the whole gate runs model-free and reproducibly (the live path swaps these
//     for the SR-5-attested `agent` seam the pack names).
//
// The heuristic/scorer are label-blind ON PURPOSE: they do not read the fabricated/over-
// claimed labels — they decide from the source text / deliverable alone — so a GREEN battery
// is real signal, not a tautology over the labels.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const readFixture = (name) => fs.readFileSync(path.join(HERE, 'fixtures', 'investment-memo', name), 'utf8');

/** The REAL investment-memo deliverable. */
export const memoClean = readFixture('clean-memo.md');
/** Identical EXCEPT a deliberately planted fabricated citation ([F9], no such source). */
export const memoPlanted = readFixture('planted-memo.md');

// --- Small inline Layer-1 fixtures for the model-free doc-contract def test ---
// The well-formed memo carries every canonical VC section the pack requires; the malformed
// one is identical EXCEPT it drops the "Valuation" section (Layer 1 must go RED and NAME it).
export const memoWellFormed = `# Investment Thesis
What must be true for the investment to win.

# Company Overview
The company, structure, and product.

# Market
The segment and the buyer.

# Financials
Audited revenue, margin, and cash.

# Valuation
Method, assumptions, and comparables.

# Risks
Key risks and their mitigants.

# Recommendation
The decision and proposed terms.
`;

export const memoMissingValuation = `# Investment Thesis
What must be true for the investment to win.

# Company Overview
The company, structure, and product.

# Market
The segment and the buyer.

# Financials
Audited revenue, margin, and cash.

# Risks
Key risks and their mitigants.

# Recommendation
The decision and proposed terms.
`; // missing the required "Valuation" section

// --- The labeled evidence sources (closed-world: entailment is judged ONLY against these) ---
// Each PRIMARY source is an audited filing / regulated disclosure carrying an `as_of` date and
// a `jurisdiction` (the pack's `required_source_fields`) plus its `kind`.
export const memoSources = {
  F1: { id: 'F1', kind: 'audited-financial-statement', as_of: '2025-12-31', jurisdiction: 'US-Delaware', text: 'The audited income statement reported annual recurring revenue of 42 million dollars for fiscal year 2025, up from 28 million dollars in 2024.' },
  F2: { id: 'F2', kind: 'audited-financial-statement', as_of: '2025-12-31', jurisdiction: 'US-Delaware', text: 'The audited statement of cash flows reported a gross margin of 71 percent for fiscal year 2025.' },
  F3: { id: 'F3', kind: 'regulatory-filing', as_of: '2025-09-30', jurisdiction: 'US-SEC', text: 'The regulatory filing disclosed that the company held 18 million dollars in cash and had no outstanding debt as of the third quarter of 2025.' },
  F4: { id: 'F4', kind: 'audited-cap-table', as_of: '2025-12-31', jurisdiction: 'US-Delaware', text: 'The audited capitalization table showed the founders retained 55 percent ownership after the Series A financing.' },
  F5: { id: 'F5', kind: 'audited-financial-statement', as_of: '2024-12-31', jurisdiction: 'UK-England', text: 'The audited financial statement reported that net revenue retention was 118 percent for fiscal year 2024.' },
  F6: { id: 'F6', kind: 'regulatory-filing', as_of: '2025-12-31', jurisdiction: 'EU-Ireland', text: 'The regulatory filing stated that the company employed 240 full time staff at the end of fiscal year 2025.' },
};

// The deliverable's OWN claims — every one resolves to a real source and is entailed by it.
export const memoCleanClaims = [
  { id: 'd1', text: 'Annual recurring revenue of 42 million dollars was reported for fiscal year 2025.', citation: 'F1' },
  { id: 'd2', text: 'Gross margin of 71 percent was reported for fiscal year 2025.', citation: 'F2' },
  { id: 'd3', text: 'The company held 18 million dollars in cash and had no outstanding debt.', citation: 'F3' },
  { id: 'd4', text: 'Founders retained 55 percent ownership after the Series A financing.', citation: 'F4' },
  { id: 'd5', text: 'Net revenue retention was 118 percent for fiscal year 2024.', citation: 'F5' },
];

// The planted deliverable's claims = the clean set PLUS the deliberately fabricated citation
// ([F9] resolves to no source) — the one Layer 2 must flag RED.
export const memoPlantedFabricatedClaim = { id: 'planted', text: 'The company achieved profitability and positive free cash flow in fiscal year 2025.', citation: 'F9' };
export const memoPlantedClaims = [...memoCleanClaims, memoPlantedFabricatedClaim];

// --- The COMMITTED labeled N+N+N battery ---
// 5 entailed + 3 fabricated (unresolved citation) + 3 over-claimed (resolved but unsupported).
export const memoBattery = {
  sources: memoSources,
  entailed: [
    { id: 'e1', text: 'Annual recurring revenue of 42 million dollars was reported for fiscal year 2025.', citation: 'F1' },
    { id: 'e2', text: 'Gross margin of 71 percent was reported for fiscal year 2025.', citation: 'F2' },
    { id: 'e3', text: 'The company held 18 million dollars in cash and had no outstanding debt.', citation: 'F3' },
    { id: 'e4', text: 'Founders retained 55 percent ownership after the Series A financing.', citation: 'F4' },
    { id: 'e5', text: 'Net revenue retention was 118 percent for fiscal year 2024.', citation: 'F5' },
  ],
  fabricated: [
    { id: 'f1', text: 'The company achieved profitability in fiscal year 2025.', citation: 'F9' },
    { id: 'f2', text: 'A filing showed revenue exceeded 200 million dollars.', citation: 'F12' },
    { id: 'f3', text: 'The company holds defensible patents in every major market.', citation: 'Filing2099' },
  ],
  overclaimed: [
    { id: 'o1', text: 'Annual recurring revenue of 42 million dollars doubled for fiscal year 2025.', citation: 'F1' },
    { id: 'o2', text: 'Gross margin of 71 percent was the highest in the industry for fiscal year 2025.', citation: 'F2' },
    { id: 'o3', text: 'Net revenue retention of 118 percent guaranteed future growth for fiscal year 2024.', citation: 'F5' },
  ],
};

// --- Label-blind deterministic entailment heuristic ---
// A claim is entailed iff EVERY content (non-stopword) token of the claim appears in the
// source text. An over-claim escalates the source (e.g. adds "doubled" / "highest" /
// "guaranteed") with a token the source does not contain, so it is rejected — without the
// heuristic ever consulting the claim's label.
const STOP = new Set([
  'a', 'an', 'the', 'of', 'in', 'on', 'at', 'to', 'for', 'and', 'or', 'but', 'with', 'by',
  'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'that', 'this', 'these', 'those',
  'it', 'its', 'than', 'then', 'also', 'into', 'over', 'under', 'between', 'during', 'per',
  'vs', 'versus', 'there', 'no', 'not', 'we', 'our',
]);
const tokens = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean);

export function memoEntail({ claim, source }) {
  const src = new Set(tokens(source?.text ?? ''));
  const ungrounded = tokens(claim.text).filter((w) => !STOP.has(w) && !src.has(w));
  const entailed = ungrounded.length === 0;
  return {
    entailed,
    rationale: entailed ? 'all claim terms are grounded in the cited audited source'
      : `claim introduces ungrounded term(s): ${ungrounded.join(', ')}`,
  };
}

// --- Label-blind deterministic rubric scorer ---
// Scores each frozen criterion from the DELIVERABLE alone, by whether the criterion's
// evidence markers are present. A well-formed VC memo carries them all (-> 0.9); a
// deliverable missing them scores proportionally lower. Deterministic: same (doc,criterion)
// always yields the same score, so the rubric verdict is reproducible.
const RUBRIC_MARKERS = {
  c1: ['thesis', 'we believe', 'falsifiable'],         // explicit + falsifiable thesis
  c2: ['[f1]', '## sources'],                          // claims anchored to cited audited sources
  c3: ['valuation', 'comparable', 'arr multiple'],     // valuation method + assumptions + comparables
  c4: ['risk', 'mitigant'],                            // risks identified with mitigants
  c5: ['recommend', 'terms'],                          // recommendation with proposed terms
};

export function memoRubricScore({ doc, criterion }) {
  const hay = String(doc).toLowerCase();
  const markers = RUBRIC_MARKERS[criterion.id] || [];
  const present = markers.filter((m) => hay.includes(m));
  const frac = markers.length ? present.length / markers.length : 1;
  return { score: 0.9 * frac, citations: present };
}
