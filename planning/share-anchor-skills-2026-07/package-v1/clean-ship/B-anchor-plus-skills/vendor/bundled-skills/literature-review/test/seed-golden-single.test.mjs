// test/seed-golden-single.test.mjs — Wave 10: the single-seed GOLDEN fence, pinned
// BEFORE N>1 is enabled.
//
// The golden fixture (test/golden/seed-single/single-seed-snowball.golden.json) is
// the EXACT observable artifact of the committed pre-Wave-10 single-seed path — a
// direct performSnowballSearch(<resolved entity id>) run plus the Wave-9 PRISMA
// advance — over a deterministic mock catalog. This suite proves, byte-for-byte:
//
//   1. the committed legacy path still reproduces the golden bytes (search.mjs and
//      pipeline-state.mjs did not drift), and
//   2. a SINGLE-seed list driven through the ENTIRE Wave-10 machinery (seed-adapter
//      -> dedupeSeedList -> seedEntityId -> per-seed snowball -> mergeSnowballResults
//      -> PRISMA advance) reproduces the SAME golden bytes,
//
// so the multi-seed adapter provably did not regress the single-seed path.

import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { performSnowballSearch, DEFAULT_VENUE_WHITELIST } from '../src/search.mjs';
import { normalizeSeedInput } from '../src/seed-adapter.mjs';
import { dedupeSeedList, seedEntityId, mergeSnowballResults } from '../src/seed-identity.mjs';
import {
  initializePipelineState,
  markPlanApproved,
  advancePrismaWithSnowball,
} from '../src/pipeline-state.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const GOLDEN_PATH = path.join(TEST_DIR, 'golden', 'seed-single', 'single-seed-snowball.golden.json');

/** The seed's RESOLVED catalog paperId — what the pre-Wave-10 path passed to snowball. */
const LEGACY_ENTITY_ID = 'W10GOLDSEED';
/** The Wave-10 spec for the SAME paper (identifier seed; entity id 'DOI:10.5555/w10.golden'). */
const SEED_SPEC = 'doi:10.5555/w10.golden|Golden Seed Paper';

/** Deterministic mock catalog: one seed paper with two references, depth-1 exhausts it. */
function makeMockCatalogFetch() {
  const seedPaper = {
    paperId: 'W10GOLDSEED',
    title: 'Golden Seed Paper',
    venue: 'Conference on Neural Information Processing Systems',
    year: 2021,
    citationCount: 42,
    abstract: 'Golden seed abstract.',
  };
  const refAlpha = {
    paperId: 'W10REFALPHA',
    title: 'Reference Alpha',
    venue: 'International Conference on Machine Learning',
    year: 2020,
    citationCount: 10,
  };
  const refBeta = {
    paperId: 'W10REFBETA',
    title: 'Reference Beta',
    venue: 'arXiv.org',
    year: 2019,
    citationCount: 3,
  };
  // Fresh clones per call: performSnowballSearch mutates candidate objects
  // (filterResult), and a shared object would leak state between the two paths.
  const jsonRes = (obj) => ({ ok: true, status: 200, json: async () => structuredClone(obj) });
  return async (url) => {
    const u = String(url);
    if (u.includes('/paper/W10GOLDSEED/references')) {
      return jsonRes({ data: [{ citedPaper: refAlpha }, { citedPaper: refBeta }] });
    }
    if (u.includes('/paper/W10REFALPHA/references') || u.includes('/paper/W10REFBETA/references')) {
      return jsonRes({ data: [] });
    }
    if (u.includes('/paper/W10GOLDSEED?') || u.includes('/paper/DOI:10.5555/w10.golden?')) {
      return jsonRes(seedPaper);
    }
    return { ok: false, status: 404, statusText: 'Not Found', json: async () => ({}) };
  };
}

/** Recursive sorted-key clone — canonical serialization for the golden byte diff. */
function sortKeysDeep(value) {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value !== null && typeof value === 'object') {
    const out = {};
    for (const key of Object.keys(value).sort()) out[key] = sortKeysDeep(value[key]);
    return out;
  }
  return value;
}

/** The observable single-seed artifact: ranked candidates, PRISMA, exclusions, graph. */
function projectRun(searchResult, prismaState) {
  return {
    candidates: searchResult.candidates.map(({ paperId, title, venue, year, citationCount }) => ({
      paperId,
      title,
      venue,
      year,
      citationCount,
    })),
    prismaExclusions: searchResult.prismaExclusions,
    prisma: prismaState,
    mermaidLines: searchResult.mermaid.split('\n'),
  };
}

const serializeProjection = (p) => JSON.stringify(sortKeysDeep(p), null, 2) + '\n';

/** The Wave-9 PRISMA advance over a (merged or legacy) snowball result. */
function advancePrisma(searchResult) {
  const state = markPlanApproved(
    initializePipelineState({ artifact: { golden: true }, planBody: '' }),
    { planHash: 'golden', approvedPath: 'approve-verbatim' },
  );
  return advancePrismaWithSnowball(state, searchResult).prisma;
}

describe('Wave 10 — single-seed golden fence (pinned before N>1)', () => {
  test('the committed pre-Wave-10 single-seed path reproduces the golden bytes exactly', async () => {
    const legacy = await performSnowballSearch(LEGACY_ENTITY_ID, DEFAULT_VENUE_WHITELIST, {
      depth: 1,
      fetch: makeMockCatalogFetch(),
    });
    const projection = projectRun(legacy, advancePrisma(legacy));
    const golden = fs.readFileSync(GOLDEN_PATH, 'utf8');
    assert.equal(
      serializeProjection(projection),
      golden,
      'the legacy single-seed artifact drifted from the pinned golden fixture',
    );
    // The golden is also structurally what it claims to be.
    assert.deepStrictEqual(sortKeysDeep(projection), JSON.parse(golden));
  });

  test('a single-seed list through the FULL Wave-10 machinery reproduces the SAME golden bytes', async () => {
    // CLI boundary: spec string -> strict validation -> canonical list -> dedupe.
    const seedInput = await normalizeSeedInput({ seedSpecs: [SEED_SPEC] });
    assert.equal(seedInput.ok, true);
    assert.equal(seedInput.seeds.length, 1);
    const { seeds } = await dedupeSeedList(seedInput.seeds);
    assert.equal(seeds.length, 1);
    assert.deepStrictEqual(
      { idType: seeds[0].idType, id: seeds[0].id, title: seeds[0].title },
      { idType: 'doi', id: '10.5555/w10.golden', title: 'Golden Seed Paper' },
    );

    // Per-seed snowball + the deterministic cross-seed merge, exactly as bin/cli.mjs
    // wires it (a single run must be the identity transform).
    const entityId = seedEntityId(seeds[0]);
    assert.equal(entityId, 'DOI:10.5555/w10.golden');
    const result = await performSnowballSearch(entityId, DEFAULT_VENUE_WHITELIST, {
      depth: 1,
      fetch: makeMockCatalogFetch(),
    });
    const merged = mergeSnowballResults([{ seed: seeds[0], entityId, result }], DEFAULT_VENUE_WHITELIST);

    const projection = projectRun(merged, advancePrisma(merged));
    const golden = fs.readFileSync(GOLDEN_PATH, 'utf8');
    assert.equal(
      serializeProjection(projection),
      golden,
      'the Wave-10 single-seed path must be byte-identical to the pinned pre-Wave-10 golden output',
    );

    // No seed merges and no attribution changes on a single-seed run.
    assert.deepStrictEqual(merged.seedMerges, []);
    assert.equal(merged.seedPapers.length, 1);
    assert.equal(merged.seedPapers[0].paperId, 'W10GOLDSEED');
  });

  test('legacy and Wave-10 single-seed PRISMA states are deep-equal (not merely projected equal)', async () => {
    const legacy = await performSnowballSearch(LEGACY_ENTITY_ID, DEFAULT_VENUE_WHITELIST, {
      depth: 1,
      fetch: makeMockCatalogFetch(),
    });
    const seedInput = await normalizeSeedInput({ seedSpecs: [SEED_SPEC] });
    const { seeds } = await dedupeSeedList(seedInput.seeds);
    const entityId = seedEntityId(seeds[0]);
    const result = await performSnowballSearch(entityId, DEFAULT_VENUE_WHITELIST, {
      depth: 1,
      fetch: makeMockCatalogFetch(),
    });
    const merged = mergeSnowballResults([{ seed: seeds[0], entityId, result }], DEFAULT_VENUE_WHITELIST);
    assert.deepStrictEqual(advancePrisma(merged), advancePrisma(legacy));
  });
});
