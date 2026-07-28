// test/_wave4-rederive-fixtures.mjs — Wave-4 shared fixtures (NOT a test file:
// test/index.mjs auto-discovers only `*.test.mjs`).
//
// One corpus shared by the three Wave-4 suites (rederive-roundtrip,
// rederive-never-represents, frozen-gate-bytes): schema-valid PlanArtifacts whose
// anchors quote the grounded sources below word-for-word, realistic human prose edits
// applied to the Wave-3 rendered plan body, and the matching fake parse emissions
// (valid and deliberately broken) that drive the bounded re-derive.

/** Grounded corpus: sourceId -> the grounded summary / seed text anchors quote from. */
export function makeGroundedSources() {
  return {
    'notes/clinical-draft.md': [
      'This draft explores retrieval-augmented generation for clinical decision support in',
      'real wards. Clinicians name dosage hallucination as the primary safety risk, and',
      'adoption is tied to verifiable citations at the point of care. Med-PaLM 2 remains',
      'the non-retrieval baseline all clinical LLM work is measured against. A multimodal',
      'imaging branch was considered and set aside for now.',
    ].join('\n'),
    'notes/corpus-notes.md': [
      'Corpus curation raises cross-site transfer questions no site has resolved. Bedside',
      'use caps acceptable latency at two seconds. Almanac is the strongest published',
      'clinical-RAG evaluation to date.',
    ].join('\n'),
    intent: 'Survey the evidence base before committing to a research direction.',
  };
}

/** Full corpus artifact (the Wave-3 golden shape): 4 branches, 2 sources, 3 seeds. */
export function makeFullArtifact() {
  return structuredClone({
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Map the evidence on retrieval-augmented generation for clinical decision support.',
      axis: 'A candidate is falsified if it lacks a prospective clinical evaluation.',
      anchors: [
        {
          sourceId: 'notes/clinical-draft.md',
          quote: 'retrieval-augmented generation for clinical decision support',
        },
      ],
    },
    branches: [
      {
        question: 'Does retrieval grounding reduce hallucinated dosages?',
        rationale: 'The draft names dosage hallucination as the primary safety risk.',
        anchors: [{ sourceId: 'notes/clinical-draft.md', quote: 'dosage hallucination' }],
      },
      {
        question: 'Which retrieval corpus curation policies transfer across hospitals?',
        rationale: 'The notes flag cross-site transfer as unresolved.',
        anchors: [{ sourceId: 'notes/corpus-notes.md', quote: 'cross-site transfer' }],
      },
      {
        question: 'How does citation grounding affect clinician trust?',
        rationale: 'The draft ties adoption to verifiable citations.',
        anchors: [{ sourceId: 'notes/clinical-draft.md', quote: 'verifiable citations' }],
      },
      {
        question: 'What latency budget keeps RAG viable at the bedside?',
        rationale: 'The methods notes cap acceptable latency at two seconds.',
        anchors: [{ sourceId: 'notes/corpus-notes.md', quote: 'acceptable latency at two seconds' }],
      },
    ],
    sourcesToBeat: [
      {
        title: 'Zakka et al. 2024 (Almanac)',
        why: 'The strongest published clinical-RAG evaluation to date.',
        anchors: [{ sourceId: 'notes/corpus-notes.md', quote: 'strongest published clinical-RAG evaluation' }],
      },
      {
        title: 'Singhal et al. 2023 (Med-PaLM 2)',
        why: 'The non-retrieval baseline all clinical LLM work is measured against.',
        anchors: [{ sourceId: 'notes/clinical-draft.md', quote: 'non-retrieval baseline' }],
      },
    ],
    foresight: {
      dropped: 'A multimodal-imaging branch was dropped.',
      counterfactualCost: 'Misses radiology-report evidence if imaging becomes central.',
      stamp: 'foresight recorded at derive time',
      anchors: [{ sourceId: 'notes/clinical-draft.md', quote: 'multimodal imaging' }],
    },
    seeds: [
      {
        idType: 'doi',
        id: '10.1056/AIoa2300068',
        title: 'Almanac: Retrieval-Augmented Language Models for Clinical Medicine',
      },
      { idType: 'pmid', id: '37460753', title: 'Large Language Models Encode Clinical Knowledge' },
      { idType: 'arxiv', id: '2305.09617', title: 'Towards Expert-Level Medical Question Answering' },
    ],
  });
}

/** Minimal corpus artifact: empty branches/sourcesToBeat/seeds, anchored to `intent`. */
export function makeMinimalArtifact() {
  return structuredClone({
    artifactVersion: 'plan-artifact/1',
    scope: {
      statement: 'Survey the evidence base before committing to a research direction.',
      axis: 'A direction is viable only if at least one replicated result supports it.',
      anchors: [{ sourceId: 'intent', quote: 'evidence base' }],
    },
    branches: [],
    sourcesToBeat: [],
    foresight: {
      dropped: 'Nothing was dropped or reordered.',
      counterfactualCost: 'None — no branch was excluded.',
      stamp: 'no foresight value added',
      anchors: [{ sourceId: 'intent', quote: 'research direction' }],
    },
    seeds: [],
  });
}

// ── Realistic human edits (acceptance GWT: branch reworded, source-to-beat added,
//    seed line altered) applied to the Wave-3 rendered prose body ─────────────────────

export const ORIGINAL_BRANCH_QUESTION = 'Does retrieval grounding reduce hallucinated dosages?';
export const REWORDED_BRANCH_QUESTION =
  'Does retrieval grounding reduce hallucinated drug dosages at the bedside?';

/** Edit 1: reword branch #1's question in the prose. */
export function rewordBranchEdit(prose) {
  return prose.replace(ORIGINAL_BRANCH_QUESTION, REWORDED_BRANCH_QUESTION);
}

/** The re-derive emission matching rewordBranchEdit (anchors unchanged, still verbatim). */
export function artifactWithRewordedBranch() {
  const artifact = makeFullArtifact();
  artifact.branches[0].question = REWORDED_BRANCH_QUESTION;
  return artifact;
}

export const ADDED_SOURCE_LINE = '- **Bedside latency guideline** — Bedside latency constraints shape viability.';

/** Edit 2: add a source-to-beat line under the existing list. */
export function addSourceToBeatEdit(prose) {
  const anchorLine = '- **Singhal et al. 2023 (Med-PaLM 2)** — The non-retrieval baseline all clinical LLM work is measured against.';
  return prose.replace(anchorLine, `${anchorLine}\n${ADDED_SOURCE_LINE}`);
}

/** The re-derive emission matching addSourceToBeatEdit (new element, model-authored anchor). */
export function artifactWithAddedSource() {
  const artifact = makeFullArtifact();
  artifact.sourcesToBeat.push({
    title: 'Bedside latency guideline',
    why: 'Bedside latency constraints shape viability.',
    anchors: [{ sourceId: 'notes/corpus-notes.md', quote: 'acceptable latency at two seconds' }],
  });
  return artifact;
}

export const ORIGINAL_SEED_TITLE = 'Almanac: Retrieval-Augmented Language Models for Clinical Medicine';
export const ALTERED_SEED_TITLE = 'Almanac (clinical RAG, NEJM AI 2024)';

/** Edit 3: alter seed #1's line (title changed by hand). */
export function alterSeedLineEdit(prose) {
  return prose.replace(ORIGINAL_SEED_TITLE, ALTERED_SEED_TITLE);
}

/** The re-derive emission matching alterSeedLineEdit (seeds carry no anchors by design). */
export function artifactWithAlteredSeed() {
  const artifact = makeFullArtifact();
  artifact.seeds[0].title = ALTERED_SEED_TITLE;
  return artifact;
}

/** Edit 4 (minimal artifact): the user hand-adds a branch where "None derived." stood. */
export function addBranchToMinimalEdit(prose) {
  return prose.replace(
    '## Candidate branches / questions\n\nNone derived.',
    [
      '## Candidate branches / questions',
      '',
      '1. **Question:** Which replicated results actually exist?',
      '   **Rationale:** The evidence base must be surveyed before committing.',
    ].join('\n'),
  );
}

/** The re-derive emission matching addBranchToMinimalEdit. */
export function minimalArtifactWithBranch() {
  const artifact = makeMinimalArtifact();
  artifact.branches.push({
    question: 'Which replicated results actually exist?',
    rationale: 'The evidence base must be surveyed before committing.',
    anchors: [{ sourceId: 'intent', quote: 'evidence base' }],
  });
  return artifact;
}

// ── Deliberately broken re-derive emissions (fail-to-ABORT paths) ─────────────────────

/** Schema-invalid: the foresight receipt was dropped by the parse. */
export function brokenArtifactMissingForesight() {
  const artifact = makeFullArtifact();
  delete artifact.foresight;
  return artifact;
}

/** Schema-invalid: an extra field the schema admits nowhere. */
export function brokenArtifactExtraField() {
  const artifact = makeFullArtifact();
  artifact.executionHints = { skipGate: true };
  return artifact;
}

/** Schema-invalid: a coverage table smuggled onto the artifact (advisory-only key). */
export function brokenArtifactWithCoverageTable() {
  const artifact = makeFullArtifact();
  artifact.coverage = { 'branches[0]': 'reconciled by hand', 'scope': 'reconciled by hand' };
  return artifact;
}

/** Anchor-invalid: a fabricated quote that appears in no grounded source. */
export function brokenArtifactFabricatedQuote() {
  const artifact = makeFullArtifact();
  artifact.branches[0].anchors[0].quote = 'a fabricated span that appears in no grounded source';
  return artifact;
}

/** Anchor-invalid: an anchor naming a sourceId absent from the grounded corpus. */
export function brokenArtifactUnknownSourceId() {
  const artifact = makeFullArtifact();
  artifact.scope.anchors[0].sourceId = 'notes/nonexistent-file.md';
  return artifact;
}

/**
 * Binding-invalid: schema-valid AND fully verbatim-anchored against the grounded
 * corpus, but describes a DIFFERENT plan than the approved full-artifact prose
 * (different scope, zero branches, zero seeds) — only the approved-prose binding
 * check can refuse it.
 */
export function brokenArtifactUnrelatedPlan() {
  return makeMinimalArtifact();
}

/**
 * Binding-invalid (COMPLETENESS): schema-valid, fully verbatim-anchored, and every
 * SURVIVING value appears verbatim in the approved rewordBranchEdit prose — but the
 * emission retains only 1 of the 4 approved branches and drops all 2 sources-to-beat
 * and all 3 seeds. Only the bijective binding check's dropped-slot direction can
 * refuse it.
 */
export function brokenArtifactDroppedSlots() {
  const artifact = artifactWithRewordedBranch();
  artifact.branches = [artifact.branches[0]];
  artifact.sourcesToBeat = [];
  artifact.seeds = [];
  return artifact;
}

/**
 * Binding-invalid (SLOT ALIGNMENT): schema-valid, fully verbatim-anchored, keeps
 * EVERY approved value and every approved slot count — but swaps the first two seeds'
 * titles and gives branch 0 branch 1's approved rationale. Every value still appears
 * verbatim SOMEWHERE in the approved prose; only per-slot alignment can refuse the
 * cross-wiring.
 */
export function brokenArtifactCrossWired() {
  const artifact = artifactWithRewordedBranch();
  const firstSeedTitle = artifact.seeds[0].title;
  artifact.seeds[0].title = artifact.seeds[1].title;
  artifact.seeds[1].title = firstSeedTitle;
  artifact.branches[0].rationale = artifact.branches[1].rationale;
  return artifact;
}

/**
 * Binding-invalid (SLOT ALIGNMENT, single-slot): schema-valid, fully verbatim-anchored,
 * keeps every approved value and every approved slot count — but EXCHANGES
 * scope.statement with scope.axis. Both values still appear verbatim in the approved
 * prose (each in the OTHER's labeled line); only per-labeled-line alignment can refuse
 * the exchange.
 */
export function brokenArtifactScopeExchanged() {
  const artifact = artifactWithRewordedBranch();
  const statement = artifact.scope.statement;
  artifact.scope.statement = artifact.scope.axis;
  artifact.scope.axis = statement;
  return artifact;
}

/**
 * Binding-invalid (SLOT ALIGNMENT, single-slot): exchanges foresight.dropped with
 * foresight.counterfactualCost — every value verbatim in the approved prose, but each
 * sits in the OTHER field's labeled renderer line.
 */
export function brokenArtifactForesightExchanged() {
  const artifact = artifactWithRewordedBranch();
  const dropped = artifact.foresight.dropped;
  artifact.foresight.dropped = artifact.foresight.counterfactualCost;
  artifact.foresight.counterfactualCost = dropped;
  return artifact;
}

/**
 * Binding-invalid (SLOT ALIGNMENT, single-slot): sets foresight.stamp to ANOTHER
 * slot's approved text (the approved `**Dropped/reordered:**` value) — verbatim in the
 * prose, but not in the `**Stamp:**` labeled line.
 */
export function brokenArtifactStampCrossSlot() {
  const artifact = artifactWithRewordedBranch();
  artifact.foresight.stamp = artifact.foresight.dropped;
  return artifact;
}

/**
 * A counting parse: wraps `produce` so tests can assert the bounded parse ran EXACTLY
 * the expected number of times and saw exactly the edited prose.
 */
export function makeCountingParse(produce) {
  let calls = 0;
  const seen = [];
  const parse = async (input) => {
    calls += 1;
    seen.push(input);
    return produce(input);
  };
  return { parse, calls: () => calls, seen };
}

/** A parse that must never run (the APPROVE-verbatim detector). */
export function makeForbiddenParse() {
  return makeCountingParse(() => {
    throw new Error('the bounded parse must never be invoked on this path');
  });
}

/** Instrument counters proving schema + anchor + binding validation each ran exactly once. */
export function makeValidationCounters() {
  const counts = { schema: 0, anchors: 0, binding: 0 };
  return {
    counts,
    instrument: {
      onSchemaValidated: () => {
        counts.schema += 1;
      },
      onAnchorChecked: () => {
        counts.anchors += 1;
      },
      onBindingChecked: () => {
        counts.binding += 1;
      },
    },
  };
}
