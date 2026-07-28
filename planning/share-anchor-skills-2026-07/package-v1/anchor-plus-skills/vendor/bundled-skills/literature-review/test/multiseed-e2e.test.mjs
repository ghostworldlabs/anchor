// test/multiseed-e2e.test.mjs — Wave 10: multi-seed injection END TO END.
//
// Pins the acceptance GWT: CLI multi-seeds (one DOI, one PMID, one arXiv — two of
// which denote the SAME paper under different identifiers) plus a content path flow
// seed-adapter -> Stage-0 -> PlanArtifact.seeds -> the presented gate prose ->
// snowball/PRISMA, where snowball reads seeds ONLY from the approved artifact's
// seeds field and never re-derives them; the duplicate pair merges deterministically
// at snowball by EXACT paperId identity, attributed by the DOI -> PMID -> arXiv-id ->
// title-hash precedence; repeated runs produce an identical dedupe result. Also pins
// the seeds-only route: a >=2-seed run with NO content and NO intent bootstraps a
// deterministic plan (zero LLM calls) and carries every seed into the gate prose.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import { performSnowballSearch, DEFAULT_VENUE_WHITELIST } from '../src/search.mjs';
import { normalizeSeedInput } from '../src/seed-adapter.mjs';
import { dedupeSeedList, seedEntityId, mergeSnowballResults } from '../src/seed-identity.mjs';
import { runStage0Plan, stage0AllowsExecution, STAGE0_STATUSES } from '../src/stage0-plan.mjs';
import {
  initializePipelineState,
  markPlanApproved,
  advancePrismaWithSnowball,
} from '../src/pipeline-state.mjs';
import { buildNormalizedView } from '../src/textNormalization.mjs';
import { groundQuote } from '../src/quoteExtractor.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.resolve(TEST_DIR, '..');
const LOOSE_NOTES = path.join(TEST_DIR, 'fixtures', 'adversarial-intake', 'loose-notes');
const GROUNDING = { buildNormalizedView, groundQuote };

// Three CLI seed specs: one DOI, one PMID, one arXiv id. The DOI and the PMID denote
// the SAME paper (the mock catalog resolves both to paperId W10DUPPAPER).
const SEED_SPECS = [
  'doi:10.5555/w10.dup|Shared Paper Under Two Identifiers',
  'pmid:424242|Shared Paper Under Two Identifiers',
  'arxiv:2401.11111|Distinct ArXiv Paper',
];
const EXPECTED_SEEDS = [
  { idType: 'doi', id: '10.5555/w10.dup', title: 'Shared Paper Under Two Identifiers' },
  { idType: 'pmid', id: '424242', title: 'Shared Paper Under Two Identifiers' },
  { idType: 'arxiv', id: '2401.11111', title: 'Distinct ArXiv Paper' },
];

/** Mock catalog: DOI and PMID resolve to ONE paper; both seed papers cite one shared ref. */
function makeMockCatalogFetch() {
  const dupPaper = {
    paperId: 'W10DUPPAPER',
    title: 'Shared Paper Under Two Identifiers',
    venue: 'Nature',
    year: 2022,
    citationCount: 7,
    abstract: 'Dup paper abstract.',
  };
  const arxPaper = {
    paperId: 'W10ARXPAPER',
    title: 'Distinct ArXiv Paper',
    venue: 'arXiv.org',
    year: 2024,
    citationCount: 1,
    abstract: 'Arx paper abstract.',
  };
  const sharedRef = {
    paperId: 'W10SHAREDREF',
    title: 'Shared Reference Paper',
    venue: 'Science',
    year: 2018,
    citationCount: 99,
  };
  const jsonRes = (obj) => ({ ok: true, status: 200, json: async () => structuredClone(obj) });
  return async (url) => {
    const u = String(url);
    if (u.includes('/paper/W10DUPPAPER/references') || u.includes('/paper/W10ARXPAPER/references')) {
      return jsonRes({ data: [{ citedPaper: sharedRef }] });
    }
    if (u.includes('/paper/W10SHAREDREF/references')) {
      return jsonRes({ data: [] });
    }
    if (u.includes('/paper/DOI:10.5555/w10.dup?') || u.includes('/paper/PMID:424242?')) {
      return jsonRes(dupPaper);
    }
    if (u.includes('/paper/arXiv:2401.11111?')) {
      return jsonRes(arxPaper);
    }
    return { ok: false, status: 404, statusText: 'Not Found', json: async () => ({}) };
  };
}

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

/** Deterministic derive spy: schema-valid artifact anchored to its fenced context,
 *  echoing EXACTLY the upstream validated seed identities (Wave-8 reconciliation). */
function deriveSpy(deriveMod, seeds) {
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
      seeds: seeds.map(({ idType, id, title }) => ({ idType, id, title })),
    };
  };
  spy.calls = [];
  return spy;
}

/** Snowball exactly as bin/cli.mjs consumes it: ONLY from the artifact's seeds field. */
async function snowballFromArtifactSeeds(artifactSeeds, mockFetch) {
  const runs = [];
  for (const seed of artifactSeeds) {
    const entityId = seedEntityId(seed);
    if (entityId === null) continue; // title-hash: no external identity, skipped honestly
    const result = await performSnowballSearch(entityId, DEFAULT_VENUE_WHITELIST, {
      depth: 1,
      fetch: mockFetch,
    });
    runs.push({ seed, entityId, result });
  }
  return mergeSnowballResults(runs, DEFAULT_VENUE_WHITELIST);
}

describe('Wave 10 — multi-seed injection end-to-end', () => {
  const runDirs = [];
  let deriveMod;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    deriveMod = await import(new URL('derivePlan.mjs', indexUrl).href);
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  function tmpRunDir(tag) {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), `litrev-w10-e2e-${tag}-`));
    runDirs.push(d);
    return d;
  }

  test('CLI seed specs -> canonical list: all three validate; none merge at the LIST layer', async () => {
    const seedInput = await normalizeSeedInput({ seedSpecs: SEED_SPECS });
    assert.equal(seedInput.ok, true);
    const dedupe = await dedupeSeedList(seedInput.seeds);
    assert.deepStrictEqual(
      dedupe.seeds.map(({ idType, id, title }) => ({ idType, id, title })),
      EXPECTED_SEEDS,
      'different identity keys never merge at the list layer — same-paper-ness is proven at snowball',
    );
    assert.deepStrictEqual(dedupe.merges, []);
    assert.deepStrictEqual(dedupe.collisions, []);
  });

  test('content route: seeds land in PlanArtifact.seeds, appear in the gate prose, and snowball consumes ONLY that field with deterministic cross-seed dedupe', async () => {
    const seedInput = await normalizeSeedInput({ seedSpecs: SEED_SPECS });
    const { seeds } = await dedupeSeedList(seedInput.seeds);

    const runDir = tmpRunDir('content');
    const summarize = summarizeSpy();
    const derive = deriveSpy(deriveMod, seeds);
    const stage0 = await runStage0Plan({
      runDir,
      intake: { roots: [LOOSE_NOTES], seeds: seeds.map((s) => ({ ...s })) },
      summarize,
      grounding: GROUNDING,
      derive,
      gate: { decision: 'APPROVE' },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0AllowsExecution(stage0), true);

    // ALL seeds appear in PlanArtifact.seeds…
    assert.deepStrictEqual(stage0.executionArtifact.seeds, EXPECTED_SEEDS);
    // …and in the presented gate prose, one line per seed (identifier + title).
    for (const s of EXPECTED_SEEDS) {
      assert.ok(
        stage0.planBody.includes(`- ${s.idType}:${s.id} — ${s.title}`),
        `gate prose must list seed ${s.idType}:${s.id}`,
      );
    }

    // Snowball reads seeds ONLY from the approved artifact's seeds field.
    const merged = await snowballFromArtifactSeeds(stage0.executionArtifact.seeds, makeMockCatalogFetch());

    // The DOI/PMID pair resolves to ONE catalog paper: merged exactly once, attributed
    // to the DOI (highest precedence), recorded deterministically.
    const ids = merged.candidates.map((c) => c.paperId);
    assert.equal(ids.filter((id) => id === 'W10DUPPAPER').length, 1, 'duplicate seed paper appears once');
    assert.deepStrictEqual(new Set(ids), new Set(['W10DUPPAPER', 'W10ARXPAPER', 'W10SHAREDREF']));
    assert.deepStrictEqual(merged.seedMerges, [
      { paperId: 'W10DUPPAPER', kept: 'doi:10.5555/w10.dup', absorbed: ['pmid:424242'] },
    ]);

    // PRISMA advances ONCE over the merged result — no double counting.
    const state = markPlanApproved(
      initializePipelineState({ artifact: stage0.executionArtifact, planBody: stage0.planBody }),
      { planHash: stage0.planHash, approvedPath: 'approve-verbatim' },
    );
    const advanced = advancePrismaWithSnowball(state, merged);
    assert.deepStrictEqual(advanced.prisma, {
      identified: 3,
      screened: 3,
      included: 3,
      excluded: 0,
      exclusions: [],
    });

    // Repeated runs produce an IDENTICAL dedupe result.
    const again = await snowballFromArtifactSeeds(stage0.executionArtifact.seeds, makeMockCatalogFetch());
    assert.deepStrictEqual(again, merged);
  });

  test('seed-order invariance: swapping the DOI/PMID run order changes nothing (precedence, not order, attributes the merge)', async () => {
    const seedInput = await normalizeSeedInput({ seedSpecs: SEED_SPECS });
    const { seeds } = await dedupeSeedList(seedInput.seeds);
    const [doiSeed, pmidSeed, arxSeed] = seeds;

    const mergedA = await snowballFromArtifactSeeds([doiSeed, pmidSeed, arxSeed], makeMockCatalogFetch());
    const mergedB = await snowballFromArtifactSeeds([pmidSeed, doiSeed, arxSeed], makeMockCatalogFetch());
    assert.deepStrictEqual(mergedB.seedMerges, mergedA.seedMerges);
    assert.deepStrictEqual(mergedB, mergedA);
    assert.equal(mergedA.seedMerges[0].kept, 'doi:10.5555/w10.dup');
  });

  test('seeds-only route: >=2 seeds with NO content and NO intent bootstrap a deterministic plan (zero LLM calls) carrying every seed', async () => {
    const seedInput = await normalizeSeedInput({ seedSpecs: SEED_SPECS });
    const { seeds } = await dedupeSeedList(seedInput.seeds);

    const runDir = tmpRunDir('seedsonly');
    // NO summarize, NO derive, NO parse adapters bound — the route must not need them.
    const stage0 = await runStage0Plan({
      runDir,
      intake: { seeds: seeds.map((s) => ({ ...s })) },
      gate: { decision: 'APPROVE' },
    });
    assert.equal(stage0.status, STAGE0_STATUSES.RUN);
    assert.equal(stage0.route, 'seeds-only-bootstrap');
    assert.equal(stage0.intake.gandalfCalls, 0);
    assert.equal(stage0.intake.deriveCalls, 0);
    assert.deepStrictEqual(stage0.executionArtifact.seeds, EXPECTED_SEEDS);
    for (const s of EXPECTED_SEEDS) {
      assert.ok(stage0.planBody.includes(`- ${s.idType}:${s.id} — ${s.title}`));
    }
  });

  test('structural fence: bin/cli.mjs accepts repeated --seed and --seed-list, validates at the boundary, and consumes ONLY executionArtifact.seeds after the Stage-0 gate', () => {
    const cliSrc = fs.readFileSync(path.join(SKILL_DIR, 'bin', 'cli.mjs'), 'utf8');

    // >=2 seeds: repeated --seed accumulates; --seed-list is accepted.
    assert.match(cliSrc, /o\.seeds\.push\(/, 'repeated --seed must accumulate into a list');
    assert.match(cliSrc, /--seed-list/, 'the CLI must accept --seed-list');
    // Strict boundary validation runs BEFORE Stage-0/any child process.
    const validateIdx = cliSrc.indexOf('normalizeSeedInput(');
    const gateIdx = cliSrc.indexOf('stage0AllowsExecution(stage0)');
    const snowballIdx = cliSrc.indexOf('performSnowballSearch(');
    assert.ok(validateIdx > -1 && gateIdx > -1 && snowballIdx > -1);
    assert.ok(validateIdx < gateIdx, 'seed validation must precede the Stage-0 gate');
    assert.ok(gateIdx < snowballIdx, 'the Stage-0 gate must precede snowball');

    // After approval, seeds come ONLY from the artifact's seeds field…
    const artifactSeedsIdx = cliSrc.indexOf('executionArtifact.seeds');
    assert.ok(artifactSeedsIdx > gateIdx, 'snowball seeds must be read from executionArtifact.seeds after the gate');
    // …and are never re-validated/re-derived: the boundary adapter runs exactly once,
    // before the gate.
    assert.equal(cliSrc.indexOf('normalizeSeedInput('), cliSrc.lastIndexOf('normalizeSeedInput('));
    assert.ok(!cliSrc.includes('runIngestionPipeline'), 'the legacy pdf-url ingest seed path is replaced');
  });
});
