// test/stage0-resume-invariance.test.mjs — Wave 9: HALT/resume is invisible to the
// pipeline — PRISMA counts and the grounding cache are BYTE-identical to a no-HALT
// run of the same approved plan, and a resume spends ZERO additional intake LLM calls.
//
// Run A (no HALT): content intake -> gate APPROVEs immediately -> snowball (mocked,
// deterministic) -> PRISMA advanced -> serialized state.
// Run B (HALT + resume): the SAME intake -> no gate response -> HALT with serialized
// state -> resume with APPROVE (intake adapters replaced by throwing fences, proving
// zero Gandalf/derive calls on resume) -> the SAME snowball -> PRISMA advanced ->
// serialized state.
// The two serialized states — and specifically their PRISMA and grounding-cache
// bytes — must be identical.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import { runStage0Plan, stage0AllowsExecution, STAGE0_STATUSES } from '../src/stage0-plan.mjs';
import {
  advancePrismaWithSnowball,
  serializePipelineState,
  writePipelineState,
  PIPELINE_STATUSES,
} from '../src/pipeline-state.mjs';
import { performSnowballSearch, DEFAULT_VENUE_WHITELIST } from '../src/search.mjs';
import { buildNormalizedView } from '../src/textNormalization.mjs';
import { groundQuote } from '../src/quoteExtractor.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const LOOSE_NOTES = path.join(TEST_DIR, 'fixtures', 'adversarial-intake', 'loose-notes');
const GROUNDING = { buildNormalizedView, groundQuote };
const SEEDS = [
  { idType: 'doi', id: '10.1234/example.5678', title: 'A seed paper on deduplication' },
  { idType: 'arxiv', id: '2401.12345', title: 'Second seed on data quality' },
];

/** Deterministic Gandalf summarize spy grounded verbatim in the loose-notes fixture. */
function summarizeSpy() {
  const spy = (payload) => {
    spy.calls.push(payload);
    return {
      sentences: [
        {
          text: 'Held-out perplexity improved monotonically with data quality filtering.',
          sourceId: 'r0/scaling-notes.md',
          quote: 'the held-out perplexity improved monotonically with data quality filtering',
        },
      ],
    };
  };
  spy.calls = [];
  return spy;
}

/** Deterministic derive spy — identical output for identical grounded context. */
function deriveSpy(deriveMod) {
  const spy = (payload) => {
    spy.calls.push(payload);
    const sourceId =
      deriveMod.SUMMARY_SOURCE_ID in payload.groundedSources
        ? deriveMod.SUMMARY_SOURCE_ID
        : deriveMod.INTENT_SOURCE_ID;
    const anchors = [{ sourceId, quote: payload.groundedSources[sourceId] }];
    return {
      artifactVersion: 'plan-artifact/1',
      scope: { statement: 'Derived scope.', axis: 'Derived AXIS.', anchors },
      branches: [{ question: 'Derived question?', rationale: 'Derived rationale.', anchors }],
      sourcesToBeat: [],
      foresight: {
        dropped: 'nothing dropped',
        counterfactualCost: 'no cost',
        stamp: 'no foresight value added',
        anchors,
      },
      seeds: SEEDS.map(({ idType, id, title }) => ({ idType, id, title })),
    };
  };
  spy.calls = [];
  return spy;
}

/** An adapter that must never run — the zero-LLM-calls-on-resume fence. */
function forbiddenAdapter(name) {
  return () => {
    throw new Error(`${name} must never be invoked on the resume path`);
  };
}

// Deterministic snowball fixture: one seed, two references, one excluded by minYear.
const MOCK_DB = {
  'seed-id': {
    paperId: 'seed-id',
    title: 'Seed Paper',
    venue: 'NeurIPS',
    year: 2021,
    citationCount: 100,
    references: [
      { citedPaper: { paperId: 'ref-1', title: 'Included Ref', venue: 'ICML', year: 2020, citationCount: 50 } },
      { citedPaper: { paperId: 'ref-2', title: 'Too Old Ref', venue: 'Nowhere Workshop', year: 2018, citationCount: 5 } },
    ],
  },
};

const mockFetch = async (url) => {
  if (url.includes('/references')) {
    const id = url.split('/paper/')[1].split('/references')[0];
    return { ok: true, status: 200, json: async () => ({ data: MOCK_DB[id]?.references ?? [] }) };
  }
  const id = url.split('/paper/')[1].split('?')[0];
  const p = MOCK_DB[id];
  if (!p) return { ok: false, status: 404, statusText: 'Not Found' };
  const { references, ...paper } = p;
  return { ok: true, status: 200, json: async () => ({ ...paper }) };
};

async function runSnowballAndAdvance(stage0) {
  assert.equal(stage0AllowsExecution(stage0), true);
  const search = await performSnowballSearch('seed-id', DEFAULT_VENUE_WHITELIST, {
    depth: 1,
    fetch: mockFetch,
    minYear: 2019,
  });
  const advanced = advancePrismaWithSnowball(stage0.state, search);
  writePipelineState(stage0.statePath, advanced);
  return advanced;
}

describe('Wave 9 — Stage-0 resume invariance (HALT+resume ≡ no-HALT, byte-for-byte)', () => {
  const runDirs = [];
  let deriveMod;
  let validateMod;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    deriveMod = await import(new URL('derivePlan.mjs', indexUrl).href);
    validateMod = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  function tmpRunDir(tag) {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), `litrev-w9-resume-${tag}-`));
    runDirs.push(d);
    return d;
  }

  test('PRISMA counts and the grounding cache are BYTE-identical between a no-HALT run and a HALT+resume run of the same approved plan', async () => {
    // ── Run A: no HALT — immediate APPROVE, then snowball. ─────────────────────────
    const dirA = tmpRunDir('nohalt');
    const summarizeA = summarizeSpy();
    const deriveA = deriveSpy(deriveMod);
    const stage0A = await runStage0Plan({
      runDir: dirA,
      intake: { roots: [LOOSE_NOTES], seeds: SEEDS },
      summarize: summarizeA,
      grounding: GROUNDING,
      derive: deriveA,
      gate: { decision: 'APPROVE' },
    });
    assert.equal(stage0A.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0A.resumed, false);
    assert.equal(stage0A.decision.path, 'approve-verbatim');
    const stateA = await runSnowballAndAdvance(stage0A);

    // ── Run B: HALT (no response) then resume with APPROVE, then the same snowball. ──
    const dirB = tmpRunDir('haltresume');
    const summarizeB = summarizeSpy();
    const deriveB = deriveSpy(deriveMod);
    const halted = await runStage0Plan({
      runDir: dirB,
      intake: { roots: [LOOSE_NOTES], seeds: SEEDS },
      summarize: summarizeB,
      grounding: GROUNDING,
      derive: deriveB,
      // no gate decision channel: HALT at the frozen gate
    });
    assert.equal(halted.status, STAGE0_STATUSES.HALTED);
    assert.equal(summarizeB.calls.length, 1);
    assert.equal(deriveB.calls.length, 1);

    const stage0B = await runStage0Plan({
      runDir: dirB,
      intake: { roots: [LOOSE_NOTES], seeds: SEEDS },
      // The resume must load the serialized state and spend ZERO further intake calls:
      summarize: forbiddenAdapter('summarize'),
      grounding: GROUNDING,
      derive: forbiddenAdapter('derive'),
      gate: { decision: 'APPROVE' },
    });
    assert.equal(stage0B.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0B.resumed, true, 'run B resumes from the serialized HALT boundary');
    assert.equal(stage0B.decision.path, 'approve-verbatim');
    assert.equal(summarizeB.calls.length, 1, 'still exactly ONE Gandalf call across HALT+resume');
    assert.equal(deriveB.calls.length, 1, 'still exactly ONE derive call across HALT+resume');
    const stateB = await runSnowballAndAdvance(stage0B);

    // ── The invariance claims. ──────────────────────────────────────────────────────
    // The SAME approved plan executed in both runs.
    assert.equal(stage0B.planHash, stage0A.planHash, 'identical plan hash across both runs');
    assert.equal(
      validateMod.canonicalStringifyPlanArtifact(stage0B.executionArtifact),
      validateMod.canonicalStringifyPlanArtifact(stage0A.executionArtifact),
      'identical execution artifact across both runs',
    );

    // PRISMA counts: byte-identical (and actually ADVANCED — non-vacuous).
    const prismaBytesA = JSON.stringify(stateA.prisma, null, 2);
    const prismaBytesB = JSON.stringify(stateB.prisma, null, 2);
    assert.equal(prismaBytesB, prismaBytesA, 'PRISMA counts must be byte-identical');
    assert.ok(stateA.prisma.included > 0, 'the snowball really included papers (non-vacuous)');
    assert.ok(stateA.prisma.excluded > 0, 'the snowball really excluded a paper (PRISMA logged, non-vacuous)');
    assert.equal(stateA.prisma.identified, stateA.prisma.included + stateA.prisma.excluded);

    // Grounding cache: byte-identical.
    const cacheBytesA = JSON.stringify(stateA.groundingCache, null, 2);
    const cacheBytesB = JSON.stringify(stateB.groundingCache, null, 2);
    assert.equal(cacheBytesB, cacheBytesA, 'the grounding cache must be byte-identical');
    assert.ok(
      stateA.groundingCache.sources[deriveMod.SUMMARY_SOURCE_ID],
      'the cache really carries the grounded summary (non-vacuous)',
    );

    // The ENTIRE serialized pipeline state is byte-identical (the strongest form).
    assert.equal(
      serializePipelineState(stateB),
      serializePipelineState(stateA),
      'the full canonical pipeline-state serialization must be byte-identical across HALT/resume',
    );
    assert.equal(stateA.status, PIPELINE_STATUSES.APPROVED);
    assert.equal(stateA.stage, 'snowball');
  });

  test('resume determinism: two resumes of the same halted state present the identical plan hash', async () => {
    const dir = tmpRunDir('rehash');
    const halted = await runStage0Plan({
      runDir: dir,
      intake: { roots: [LOOSE_NOTES], seeds: SEEDS },
      summarize: summarizeSpy(),
      grounding: GROUNDING,
      derive: deriveSpy(deriveMod),
    });
    assert.equal(halted.status, STAGE0_STATUSES.HALTED);
    const hashesSeen = [];
    for (let i = 0; i < 2; i++) {
      const again = await runStage0Plan({
        runDir: dir,
        summarize: forbiddenAdapter('summarize'),
        derive: forbiddenAdapter('derive'),
      });
      assert.equal(again.status, STAGE0_STATUSES.HALTED, 'still halted without a decision');
      assert.equal(again.resumed, true);
      hashesSeen.push(again.presentations[0].planHash);
    }
    assert.equal(hashesSeen[0], hashesSeen[1], 'the presented plan hash is stable across resumes');
  });
});
