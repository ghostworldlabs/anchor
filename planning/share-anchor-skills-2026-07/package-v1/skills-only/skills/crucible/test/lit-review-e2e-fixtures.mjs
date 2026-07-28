// crucible/test/lit-review-e2e-fixtures.mjs — Wave 2 (lit-review end-to-end) fixtures.
//
// NOT a `*.test.mjs`, so the runner imports it but never executes it as a suite (same
// convention as pack-fixtures.mjs). It supplies:
//   - the REAL lit-review deliverable (clean + planted-fabrication variants, loaded from
//     the committed .md artifacts under fixtures/lit-review/),
//   - the COMMITTED labeled N+N+N evidence battery (Phase-2.3 battery manifest): N entailed
//     + N fabricated + N over-claimed, each with its source map,
//   - the deliverable's own clean + planted claim sets (for the per-deliverable Layer-2 run),
//   - a LABEL-BLIND deterministic entailment heuristic and a LABEL-BLIND deterministic
//     rubric scorer, so the whole gate runs model-free and reproducibly (the live path swaps
//     these for the SR-5-attested `agent` seam the pack names).
//
// The heuristic/scorer are label-blind ON PURPOSE: they do not read the fabricated/over-
// claimed labels — they decide from the source text / deliverable alone — so a GREEN battery
// is real signal, not a tautology over the labels.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const readFixture = (name) => fs.readFileSync(path.join(HERE, 'fixtures', 'lit-review', name), 'utf8');

/** The REAL lit-review deliverable (Wave-3 re-judges this same artifact). */
export const litReviewClean = readFixture('clean-review.md');
/** Identical EXCEPT a deliberately planted fabricated citation ([S9], no such source). */
export const litReviewPlanted = readFixture('planted-review.md');

// --- The labeled evidence sources (closed-world: entailment is judged ONLY against these) ---
export const litSources = {
  S1: { id: 'S1', text: 'In a randomized trial of 342 adults with chronic low back pain, mindfulness-based stress reduction reduced pain interference at 26 weeks compared with usual care.' },
  S2: { id: 'S2', text: 'A registered trial reported that an 8-week mindfulness program improved physical function scores relative to a waitlist control over 12 weeks.' },
  S3: { id: 'S3', text: 'Across two primary studies, mindfulness-based stress reduction lowered self-reported pain intensity on a 0 to 10 scale by about one point versus usual care.' },
  S4: { id: 'S4', text: 'A preregistered study found that mindfulness participants reported fewer days of restricted activity than the education control group at six months.' },
  S5: { id: 'S5', text: 'A primary trial observed that adherence to the mindfulness sessions was associated with greater improvement in disability scores.' },
  S6: { id: 'S6', text: 'A registered report found no significant difference in opioid use between mindfulness and usual care at 12 months.' },
};

// The deliverable's OWN claims — every one resolves to a real source and is entailed by it.
export const litCleanClaims = [
  { id: 'd1', text: 'Mindfulness-based stress reduction reduced pain interference at 26 weeks compared with usual care.', citation: 'S1' },
  { id: 'd2', text: 'An 8-week mindfulness program improved physical function scores relative to a waitlist control.', citation: 'S2' },
  { id: 'd3', text: 'Mindfulness-based stress reduction lowered self-reported pain intensity versus usual care.', citation: 'S3' },
  { id: 'd4', text: 'Mindfulness participants reported fewer days of restricted activity than the education control group at six months.', citation: 'S4' },
  { id: 'd5', text: 'No significant difference in opioid use between mindfulness and usual care was found at 12 months.', citation: 'S6' },
];

// The planted deliverable's claims = the clean set PLUS the deliberately fabricated citation
// ([S9] resolves to no source) — the one Layer 2 must flag RED.
export const litPlantedFabricatedClaim = { id: 'planted', text: 'Mindfulness-based stress reduction cured chronic low back pain in most participants.', citation: 'S9' };
export const litPlantedClaims = [...litCleanClaims, litPlantedFabricatedClaim];

// --- The COMMITTED labeled N+N+N battery (Phase-2.3 battery manifest) ---
// 5 entailed + 3 fabricated (unresolved citation) + 3 over-claimed (resolved but unsupported).
export const litBattery = {
  sources: litSources,
  entailed: [
    { id: 'e1', text: 'Mindfulness-based stress reduction reduced pain interference at 26 weeks compared with usual care.', citation: 'S1' },
    { id: 'e2', text: 'An 8-week mindfulness program improved physical function scores relative to a waitlist control.', citation: 'S2' },
    { id: 'e3', text: 'Mindfulness-based stress reduction lowered self-reported pain intensity versus usual care.', citation: 'S3' },
    { id: 'e4', text: 'Mindfulness participants reported fewer days of restricted activity than the education control group at six months.', citation: 'S4' },
    { id: 'e5', text: 'No significant difference in opioid use between mindfulness and usual care was found at 12 months.', citation: 'S6' },
  ],
  fabricated: [
    { id: 'f1', text: 'Mindfulness-based stress reduction cured chronic low back pain in most participants.', citation: 'S9' },
    { id: 'f2', text: 'A trial showed mindfulness reduced pain more than spinal surgery.', citation: 'S12' },
    { id: 'f3', text: 'Mindfulness eliminated disability in elderly patients.', citation: 'Doe2099' },
  ],
  overclaimed: [
    { id: 'o1', text: 'Mindfulness-based stress reduction eliminated pain interference at 26 weeks compared with usual care.', citation: 'S1' },
    { id: 'o2', text: 'Mindfulness-based stress reduction lowered self-reported pain intensity in all patients versus usual care.', citation: 'S3' },
    { id: 'o3', text: 'Adherence to the mindfulness sessions guaranteed improvement in disability scores.', citation: 'S5' },
  ],
};

// --- Label-blind deterministic entailment heuristic ---
// A claim is entailed iff EVERY content (non-stopword) token of the claim appears in the
// source text. An over-claim escalates the source (e.g. "reduced" -> "eliminated", adds
// "all"/"guaranteed") with a token the source does not contain, so it is rejected — without
// the heuristic ever consulting the claim's label.
const STOP = new Set([
  'a', 'an', 'the', 'of', 'in', 'on', 'at', 'to', 'for', 'and', 'or', 'but', 'with', 'by',
  'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'that', 'this', 'these', 'those',
  'it', 'its', 'than', 'then', 'also', 'into', 'over', 'under', 'between', 'during', 'per',
  'vs', 'versus', 'there', 'no', 'not', 'we', 'our',
]);
const tokens = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(/\s+/).filter(Boolean);

export function litEntail({ claim, source }) {
  const src = new Set(tokens(source?.text ?? ''));
  const ungrounded = tokens(claim.text).filter((w) => !STOP.has(w) && !src.has(w));
  const entailed = ungrounded.length === 0;
  return {
    entailed,
    rationale: entailed ? 'all claim terms are grounded in the cited source'
      : `claim introduces ungrounded term(s): ${ungrounded.join(', ')}`,
  };
}

// --- Label-blind deterministic rubric scorer ---
// Scores each frozen criterion from the DELIVERABLE alone, by whether the criterion's
// evidence markers are present. A well-formed PRISMA review carries them all (-> 0.9); a
// deliverable missing them scores proportionally lower. Deterministic: same (doc,criterion)
// always yields the same score, so the rubric verdict is reproducible.
const RUBRIC_MARKERS = {
  c1: ['pubmed', 'embase', 'query string', '2010', '2024'],   // reproducible search strategy
  c2: ['[s1]', '## references'],                               // claims anchored to cited sources
  c3: ['identified', 'screened', 'included', 'excluded'],     // PRISMA flow accounts for records
  c4: ['risk of bias'],                                       // risk-of-bias assessed
  c5: ['limitations'],                                        // limitations stated
};

export function litRubricScore({ doc, criterion }) {
  const hay = String(doc).toLowerCase();
  const markers = RUBRIC_MARKERS[criterion.id] || [];
  const present = markers.filter((m) => hay.includes(m));
  const frac = markers.length ? present.length / markers.length : 1;
  return { score: 0.9 * frac, citations: present };
}
