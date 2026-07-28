// test/golden-run-fence.test.mjs — Wave 11: the full-suite golden-run fence.
//
// Criterion (5) made concrete: the ENTIRE existing lit-review pipeline — the six
// numbered stages of bin/cli.mjs (1 snowball, 2 PRISMA, 3 mixed-initiative gate,
// 4 LEAN extraction with deterministic quote-grounding, 5 weighted consensus
// synthesis, 6 the single researchPrime governed round) — is byte-stable
// BEFORE/AFTER the plan-first feature. The fence runs the six stages over ONE
// deterministic mock catalog through BOTH pipelines:
//
//   BASELINE ("before"): the committed pre-feature path — performSnowballSearch
//   driven directly, exactly as the pre-Wave-9 CLI did;
//
//   FEATURE ("after"): the full plan-first path — a REAL Stage-0 run (shared
//   seeds-only bootstrap -> the FROZEN gate -> APPROVE), seeds consumed ONLY from
//   the approved PlanArtifact, per-seed snowball + mergeSnowballResults, PRISMA
//   advanced on the Stage-0 pipeline state —
//
// and asserts the serialized projections (PRISMA counts + exclusions, candidate
// ranking, gate outcome, per-paper grounding decisions, the weighted-synthesis
// ledger/matrix/markdown BYTES, and the governed-round outcome) are BYTE-IDENTICAL
// across baseline-run-1 vs baseline-run-2 (determinism) and baseline vs feature
// (the feature changed nothing downstream). The Stage-0 grounding cache itself is
// pinned byte-stable across two independent plan-first runs via the canonical
// pipeline-state serialization.
//
// Stage 6 uses researchPrime's REAL runGovernedRound surface on its deterministic
// zero-AXIS-finding pre-flight (the tally is computed BEFORE any agent could fire),
// with a tripwire agent asserting zero LLM calls — the single-governed-round wiring
// is exercised for real without a model seat.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { importRp } from './_wave1-trio-resolve.mjs';
import { performSnowballSearch, DEFAULT_VENUE_WHITELIST } from '../src/search.mjs';
import { seedEntityId, mergeSnowballResults } from '../src/seed-identity.mjs';
import { runMixedInitiativeGate } from '../src/gate.mjs';
import { extractLedgerLean } from '../src/extraction.mjs';
import { runFinalSynthesis } from '../src/synthesis.mjs';
import {
  initializePipelineState,
  markPlanApproved,
  advancePrismaWithSnowball,
  serializePipelineState,
} from '../src/pipeline-state.mjs';
import { runStage0Plan, stage0AllowsExecution, STAGE0_STATUSES } from '../src/stage0-plan.mjs';

const COLUMNS = ['method', 'evidence', 'result'];
const MIN_YEAR = 2000;
const FENCE_SEED = { idType: 'doi', id: '10.5555/grf.seed', title: 'Golden Run Fence Seed' };
/** What the pre-feature path passed to snowball: the seed's resolved catalog paperId. */
const LEGACY_ENTITY_ID = 'GRFSEED';

// ── The deterministic mock catalog: one seed, three references, one excluded ────────
const SEED_ABSTRACT =
  'The seed system sustains ninety thousand requests per second under contention. ' +
  'It holds this rate across mixed workloads.';
const REF_A_ABSTRACT =
  'Reference alpha observes a forty one percent cache hit improvement. ' +
  'Alpha maintains the gain under skewed keys.';
const REF_B_ABSTRACT =
  'Reference beta reports twelve millisecond tail latency at the ninety ninth percentile. ' +
  'Beta replicates the measurement across three clusters.';

function makeMockCatalogFetch() {
  const seedPaper = {
    paperId: 'GRFSEED',
    title: 'Golden Run Fence Seed',
    venue: 'Conference on Neural Information Processing Systems',
    year: 2022,
    citationCount: 50,
    abstract: SEED_ABSTRACT,
  };
  const refAlpha = {
    paperId: 'GRFREFA',
    title: 'Reference Alpha',
    venue: 'International Conference on Machine Learning',
    year: 2021,
    citationCount: 30,
    abstract: REF_A_ABSTRACT,
  };
  const refBeta = {
    paperId: 'GRFREFB',
    title: 'Reference Beta',
    venue: 'arXiv.org',
    year: 2020,
    citationCount: 5,
    abstract: REF_B_ABSTRACT,
  };
  const refLegacy = {
    paperId: 'GRFREFC',
    title: 'Reference From Last Century',
    venue: 'Journal of Legacy Results',
    year: 1999,
    citationCount: 100,
    abstract: 'An old result outside the review window.',
  };
  // Fresh clones per call: performSnowballSearch mutates candidate objects.
  const jsonRes = (obj) => ({ ok: true, status: 200, json: async () => structuredClone(obj) });
  return async (url) => {
    const u = String(url);
    if (u.includes('/paper/GRFSEED/references')) {
      return jsonRes({ data: [{ citedPaper: refAlpha }, { citedPaper: refBeta }, { citedPaper: refLegacy }] });
    }
    if (u.includes('/paper/GRFSEED?') || u.includes('/paper/DOI:10.5555/grf.seed?')) {
      return jsonRes(seedPaper);
    }
    return { ok: false, status: 404, statusText: 'Not Found', json: async () => ({}) };
  };
}

// ── Deterministic stage-4 extraction seat: per paper, ONE grounded claim (verbatim
//    sentence from the abstract) + ONE fabricated quote the deterministic grounding
//    check must reject. Pure function of the extraction label. ────────────────────────
const EXTRACTION_FIXTURES = {
  GRFSEED: {
    claim_id: 'grfseed-throughput',
    statement: 'Seed system throughput sits at ninety thousand requests per second.',
    quote: 'The seed system sustains ninety thousand requests per second under contention.',
    column: 'result',
  },
  GRFREFA: {
    claim_id: 'grfrefa-cache',
    statement: 'Alpha caching yields a forty one percent hit gain.',
    quote: 'Reference alpha observes a forty one percent cache hit improvement.',
    column: 'evidence',
  },
  GRFREFB: {
    claim_id: 'grfrefb-latency',
    statement: 'Beta tail latency lands at twelve milliseconds.',
    quote: 'Reference beta reports twelve millisecond tail latency at the ninety ninth percentile.',
    column: 'method',
  },
};

async function extractionAgent(_prompt, opts = {}) {
  const paperId = String(opts.label || '').replace(/^extract:/, '');
  const grounded = EXTRACTION_FIXTURES[paperId];
  assert.ok(grounded, `extraction agent saw an unexpected paper: ${paperId}`);
  return {
    assumptions: [
      grounded,
      {
        claim_id: `${paperId.toLowerCase()}-fabricated`,
        statement: 'A fabricated claim with an invented supporting quote.',
        quote: 'THIS SENTENCE APPEARS IN NO PAPER TEXT ANYWHERE.',
        column: 'evidence',
      },
    ],
  };
}

/** Recursive sorted-key clone — canonical serialization for the byte diff. */
function sortKeysDeep(value) {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value !== null && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = sortKeysDeep(value[key]);
    return out;
  }
  return value;
}
const serialize = (p) => JSON.stringify(sortKeysDeep(p), null, 2) + '\n';

/**
 * Stages 2–6 over a snowball result, exactly as bin/cli.mjs wires them, projected to
 * the observable outputs the fence pins. `approvedState` is the APPROVED pipeline
 * state PRISMA advances on (the Stage-0 state on the feature path; a synthetic
 * approved state on the baseline path, which predates pipeline state entirely).
 */
async function runStagesTwoThroughSix(searchResult, approvedState) {
  // Stage 2 — PRISMA advances ONCE over the snowball result.
  const advanced = advancePrismaWithSnowball(approvedState, searchResult);

  // Stage 3 — mixed-initiative gate (deterministic mock user, copilot never needed).
  const seedChunks = [SEED_ABSTRACT];
  const gate = await runMixedInitiativeGate(searchResult.candidates, seedChunks, {
    mockUser: 'approve',
    log: () => {},
    agent: async () => {
      throw new Error('the copilot seat must not be consulted by a bare approve');
    },
  });

  // Stage 4 — LEAN extraction: one call per paper + deterministic quote grounding.
  const allAssumptions = [];
  const allRejected = [];
  for (const cand of searchResult.candidates) {
    const { ledger, rejected } = await extractLedgerLean(cand, cand.abstract, COLUMNS, extractionAgent);
    allAssumptions.push(...ledger.assumptions);
    allRejected.push(...rejected);
  }

  // Stage 5 — weighted consensus synthesis (deterministic math, in-memory).
  const withLedgers = searchResult.candidates
    .map((c) => ({ ...c, ledger: { assumptions: allAssumptions.filter((a) => a.source.entityId === c.paperId) } }))
    .filter((c) => c.ledger.assumptions.length);
  const synth = await runFinalSynthesis(withLedgers, COLUMNS, {});

  // Stage 6 — the single researchPrime governed round, REAL surface, deterministic
  // zero-AXIS pre-flight: the skip decision is provably made before any agent fires.
  const governor = await importRp('bin/governor.mjs');
  let governedAgentCalls = 0;
  const tripwireAgent = async () => {
    governedAgentCalls += 1;
    throw new Error('the governed round must not spend an agent call on the zero-AXIS path');
  };
  const round = await governor.runGovernedRound({
    agent: tripwireAgent,
    stakes: 'medium',
    reviews: [
      { reviewer: 'Skeptic', findings: [] },
      { reviewer: 'Contrarian', findings: [] },
      { reviewer: 'Analyst', findings: [] },
    ],
    round: 1,
    northStar: `An honest, source-grounded synthesis of the literature around the seed paper, compared on: ${COLUMNS.join(', ')}`,
  });

  return {
    projection: {
      prisma: advanced.prisma,
      candidates: searchResult.candidates.map(({ paperId, title, venue, year, citationCount }) => ({
        paperId,
        title,
        venue,
        year,
        citationCount,
      })),
      mermaidLines: searchResult.mermaid.split('\n'),
      gate: { approved: gate.approved, queries: gate.queries.length },
      grounding: {
        groundedByPaper: Object.fromEntries(
          searchResult.candidates.map((c) => [
            c.paperId,
            allAssumptions.filter((a) => a.source.entityId === c.paperId).map((a) => ({ id: a.id, quote: a.quote })),
          ]),
        ),
        rejected: allRejected.map((r) => ({ id: r.id, quote: r.quote, rejection: r.rejection })),
      },
      synthesis: {
        ledgerJson: JSON.stringify(synth.ledger, null, 2),
        matrixJson: JSON.stringify(synth.matrix, null, 2),
        markdown: synth.markdown,
      },
      governedRound: {
        skipped: round.skipped === true,
        demoted: round.demoted === true,
        reason: round.reason ?? null,
        counts: round.counts,
        axisFindingCount: round.axisFindingCount,
      },
    },
    governedAgentCalls,
    synth,
    rejected: allRejected,
  };
}

/** The BASELINE ("before the feature") pipeline: direct snowball, no Stage-0. */
async function runBaselinePipeline() {
  const result = await performSnowballSearch(LEGACY_ENTITY_ID, DEFAULT_VENUE_WHITELIST, {
    depth: 1,
    fetch: makeMockCatalogFetch(),
    minYear: MIN_YEAR,
  });
  // The baseline predates pipeline state; PRISMA advances on a synthetic approved
  // state exactly as test/seed-golden-single.test.mjs established.
  const approvedState = markPlanApproved(
    initializePipelineState({ artifact: { goldenRunFence: true }, planBody: '' }),
    { planHash: 'golden-run-fence', approvedPath: 'approve-verbatim' },
  );
  return runStagesTwoThroughSix(result, approvedState);
}

/** The FEATURE ("after") pipeline: real Stage-0 plan-first run, then the same stages. */
async function runFeaturePipeline(runDir) {
  const stage0 = await runStage0Plan({
    runDir,
    intake: { seeds: [{ ...FENCE_SEED }] },
    gate: { decision: 'APPROVE' },
  });
  assert.equal(stage0.status, STAGE0_STATUSES.RUN);
  assert.equal(stage0AllowsExecution(stage0), true);
  // Wave-10 discipline: seeds are consumed ONLY from the approved artifact.
  const seeds = stage0.executionArtifact.seeds;
  assert.equal(seeds.length, 1);
  const entityId = seedEntityId(seeds[0]);
  assert.equal(entityId, 'DOI:10.5555/grf.seed');
  const result = await performSnowballSearch(entityId, DEFAULT_VENUE_WHITELIST, {
    depth: 1,
    fetch: makeMockCatalogFetch(),
    minYear: MIN_YEAR,
  });
  const merged = mergeSnowballResults([{ seed: seeds[0], entityId, result }], DEFAULT_VENUE_WHITELIST);
  const stages = await runStagesTwoThroughSix(merged, stage0.state);
  return { ...stages, stage0 };
}

describe('Wave 11 — full-suite golden-run fence (6 stages byte-stable before/after the feature)', () => {
  const runDirs = [];
  let baselineFirst;
  let baselineSecond;
  let feature;

  before(async () => {
    baselineFirst = await runBaselinePipeline();
    baselineSecond = await runBaselinePipeline();
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'litrev-w11-goldenrun-'));
    runDirs.push(runDir);
    feature = await runFeaturePipeline(runDir);
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  test('the six-stage baseline pipeline is deterministic: two runs serialize byte-identically', () => {
    assert.equal(serialize(baselineFirst.projection), serialize(baselineSecond.projection));
  });

  test('acceptance GWT: the feature-path run is BYTE-IDENTICAL to the baseline across PRISMA counts, grounding, and weighted synthesis', () => {
    assert.equal(
      serialize(feature.projection),
      serialize(baselineFirst.projection),
      'the plan-first feature must not perturb one byte of the six-stage pipeline outputs',
    );
    // The load-bearing sub-surfaces, named individually so a drift diff names its stage.
    assert.deepStrictEqual(feature.projection.prisma, baselineFirst.projection.prisma, 'PRISMA counts');
    assert.equal(
      feature.projection.synthesis.ledgerJson,
      baselineFirst.projection.synthesis.ledgerJson,
      'weighted-synthesis ledger bytes',
    );
    assert.equal(
      feature.projection.synthesis.matrixJson,
      baselineFirst.projection.synthesis.matrixJson,
      'parameterized-matrix bytes',
    );
    assert.equal(
      feature.projection.synthesis.markdown,
      baselineFirst.projection.synthesis.markdown,
      'ledger markdown bytes',
    );
    assert.deepStrictEqual(
      feature.projection.grounding,
      baselineFirst.projection.grounding,
      'deterministic quote-grounding decisions',
    );
  });

  test('the pinned PRISMA discipline: 4 identified, 4 screened, 3 included, 1 excluded with a named reason', () => {
    assert.deepStrictEqual(baselineFirst.projection.prisma, {
      identified: 4,
      screened: 4,
      included: 3,
      excluded: 1,
      exclusions: [
        {
          paperId: 'GRFREFC',
          title: 'Reference From Last Century',
          reason: 'date-range',
          details: `Published in 1999, but minYear is ${MIN_YEAR}`,
        },
      ],
    });
    assert.deepStrictEqual(
      baselineFirst.projection.candidates.map((c) => c.paperId),
      ['GRFSEED', 'GRFREFA', 'GRFREFB'],
      'deterministic ranking: tier, then citations, then year, then id',
    );
  });

  test('quote-grounding is exercised for real: one grounded claim per paper, every fabricated quote rejected', () => {
    for (const paperId of ['GRFSEED', 'GRFREFA', 'GRFREFB']) {
      assert.equal(
        baselineFirst.projection.grounding.groundedByPaper[paperId].length,
        1,
        `${paperId}: the verbatim quote grounds`,
      );
    }
    assert.equal(baselineFirst.rejected.length, 3, 'one fabricated quote per paper was rejected');
    for (const r of baselineFirst.rejected) {
      assert.match(r.rejection, /UNVERIFIED-FABRICATED-QUOTE/);
    }
  });

  test('weighted synthesis stays the committed math: three CLAIMED assumptions, matrix rows in rank order', () => {
    const ledger = JSON.parse(baselineFirst.projection.synthesis.ledgerJson);
    assert.deepStrictEqual(
      ledger.assumptions.map((a) => ({ id: a.id, type: a.type, confidence: a.confidence })),
      [
        { id: 'A1', type: 'CLAIMED', confidence: 0.5 },
        { id: 'A2', type: 'CLAIMED', confidence: 0.5 },
        { id: 'A3', type: 'CLAIMED', confidence: 0.5 },
      ],
    );
    const matrix = JSON.parse(baselineFirst.projection.synthesis.matrixJson);
    assert.deepStrictEqual(matrix.columns, COLUMNS);
    assert.deepStrictEqual(
      matrix.rows.map((r) => r.paperId),
      ['GRFSEED', 'GRFREFA', 'GRFREFB'],
    );
  });

  test('stage 6 drove researchPrime\'s REAL governed round with ZERO agent calls (deterministic pre-flight)', () => {
    for (const run of [baselineFirst, baselineSecond, feature]) {
      assert.equal(run.governedAgentCalls, 0);
      assert.equal(run.projection.governedRound.skipped, true);
      assert.equal(run.projection.governedRound.axisFindingCount, 0);
      assert.deepStrictEqual(run.projection.governedRound.counts, { synthesizer: 0, judge: 0, debate: 0 });
    }
  });

  test('the Stage-0 grounding cache is byte-stable: two independent plan-first runs serialize identical pipeline state', async () => {
    const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'litrev-w11-goldenrun2-'));
    runDirs.push(runDir);
    const second = await runFeaturePipeline(runDir);
    assert.equal(
      serializePipelineState(second.stage0.state),
      serializePipelineState(feature.stage0.state),
      'plan artifact + plan body + grounding cache + PRISMA init must serialize byte-identically',
    );
    assert.equal(serialize(second.projection), serialize(feature.projection));
  });
});
