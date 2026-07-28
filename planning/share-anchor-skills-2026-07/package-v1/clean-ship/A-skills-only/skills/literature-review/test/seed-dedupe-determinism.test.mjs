// test/seed-dedupe-determinism.test.mjs — Wave 10: snapshot-frozen seed identity +
// normalization at the lit-review boundary; deterministic cross-seed dedupe; NO fuzzy
// merge anywhere; id-less collisions FLAGGED for the user, never merged.
//
// Pins: the seed-adapter's spec-string classification grammar; the adapter's strict
// validation (a malformed identifier is rejected BEFORE any child-process handoff,
// with no silent precedence fallthrough); the LIST-layer dedupe (only exact
// identity-key duplicates collapse); the SNOWBALL-layer merge (exact paperId
// identity, candidate-wins, precedence attribution); and the drift fence keeping the
// lit-review-side precedence equal to the shared module's pinned SEED_ID_PRECEDENCE.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import { classifySeedSpec, normalizeSeedInput } from '../src/seed-adapter.mjs';
import {
  LITREVIEW_SEED_ID_PRECEDENCE,
  TITLE_COLLISION_MIN_JACCARD,
  seedEntityId,
  dedupeSeedList,
  mergeSnowballResults,
} from '../src/seed-identity.mjs';
import { DEFAULT_VENUE_WHITELIST } from '../src/search.mjs';

let si; // the SHARED seedIdentity module (the one identity convention)

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  si = await import(new URL('seedIdentity.mjs', indexUrl).href);
});

describe('Wave 10 — snapshot-frozen identity, precedence, and entity mapping', () => {
  test('SNAPSHOT: the lit-review precedence equals the shared pinned precedence (drift fence)', () => {
    assert.deepStrictEqual([...LITREVIEW_SEED_ID_PRECEDENCE], ['doi', 'pmid', 'arxiv', 'title-hash']);
    assert.deepStrictEqual([...LITREVIEW_SEED_ID_PRECEDENCE], [...si.SEED_ID_PRECEDENCE]);
  });

  test('SNAPSHOT: catalog entity-id mapping per idType; title-hash has NO external identity', () => {
    assert.equal(seedEntityId({ idType: 'doi', id: '10.1000/x.1' }), 'DOI:10.1000/x.1');
    assert.equal(seedEntityId({ idType: 'pmid', id: '123' }), 'PMID:123');
    assert.equal(seedEntityId({ idType: 'arxiv', id: '2203.15556' }), 'arXiv:2203.15556');
    assert.equal(seedEntityId({ idType: 'title-hash', id: 'a'.repeat(64) }), null);
    assert.equal(TITLE_COLLISION_MIN_JACCARD, 0.5, 'the advisory collision threshold is pinned');
  });

  test('SNAPSHOT: the seed-spec classification grammar', () => {
    const cases = [
      ['doi:10.1000/abc|A Title', { doi: '10.1000/abc', title: 'A Title' }],
      ['doi:10.1000/abc', { doi: '10.1000/abc', title: 'doi:10.1000/abc' }],
      ['10.1000/abc', { doi: '10.1000/abc', title: '10.1000/abc' }],
      ['https://doi.org/10.1000/abc|T', { doi: 'https://doi.org/10.1000/abc', title: 'T' }],
      ['pmid:12345|T', { pmid: '12345', title: 'T' }],
      ['12345', { pmid: '12345', title: '12345' }],
      ['arxiv:2203.15556|T', { arxiv: '2203.15556', title: 'T' }],
      ['2203.15556', { arxiv: '2203.15556', title: '2203.15556' }],
      ['hep-th/9901001', { arxiv: 'hep-th/9901001', title: 'hep-th/9901001' }],
      ['https://arxiv.org/abs/2203.15556|T', { arxiv: 'https://arxiv.org/abs/2203.15556', title: 'T' }],
      ['title:Scaling Laws for Neural LMs', { title: 'Scaling Laws for Neural LMs' }],
      ['Just Some Paper Title', { title: 'Just Some Paper Title' }],
    ];
    for (const [spec, raw] of cases) {
      const res = classifySeedSpec(spec);
      assert.equal(res.ok, true, `expected classifiable: "${spec}"`);
      assert.deepStrictEqual(res.raw, raw, `classification drifted for "${spec}"`);
    }
    // A non-identifier URL names no seed: the pdf-url path is REPLACED, by name.
    const url = classifySeedSpec('https://example.com/paper.pdf');
    assert.equal(url.ok, false);
    assert.match(url.reason, /REPLACED in Wave 10/);
  });

  test('identifier spellings normalize to ONE identity key (shared normalization, no drift)', async () => {
    const forms = ['doi:10.1000/ABC.Def|T', 'https://doi.org/10.1000/abc.def|T', '10.1000/Abc.DEF|T'];
    const { seeds } = await normalizeSeedInput({ seedSpecs: forms });
    assert.deepStrictEqual(
      seeds.map((s) => si.seedIdentityKey(s)),
      ['doi:10.1000/abc.def', 'doi:10.1000/abc.def', 'doi:10.1000/abc.def'],
    );
  });
});

describe('Wave 10 — strict validation at the boundary (before any child-process handoff)', () => {
  test('a malformed DOI is rejected with a named reason and contributes nothing', async () => {
    const res = await normalizeSeedInput({
      seedSpecs: ['doi:not-a-doi|Bad Seed', 'pmid:424242|Good Seed'],
    });
    assert.equal(res.ok, false);
    assert.equal(res.rejected.length, 1);
    assert.match(res.rejected[0].reason, /malformed doi identifier/);
    assert.match(res.rejected[0].reason, /before any child-process handoff/);
    // The valid seed still validated — the CLI decides what to do with a partial set.
    assert.equal(res.seeds.length, 1);
    assert.equal(res.seeds[0].idType, 'pmid');
  });

  test('no silent precedence fallthrough: a supplied-but-malformed DOI never degrades to a lower identifier', async () => {
    const listDir = fs.mkdtempSync(path.join(os.tmpdir(), 'litrev-w10-seedlist-'));
    const listPath = path.join(listDir, 'seeds.json');
    fs.writeFileSync(
      listPath,
      JSON.stringify([
        { doi: 'not-a-doi', arxiv: '2203.15556', title: 'Has A Valid ArXiv Too' },
        { arxiv: '2203.15556', title: 'ArXiv Only', abstract: 'An abstract.' },
        'title:A Listed Title Seed',
      ]),
      'utf8',
    );
    try {
      const res = await normalizeSeedInput({ seedListPath: listPath });
      assert.equal(res.ok, false);
      assert.equal(res.rejected.length, 1, 'the malformed-DOI entry must be rejected, not degraded to its arXiv id');
      assert.match(res.rejected[0].reason, /malformed doi/);
      assert.equal(res.seeds.length, 2);
      assert.equal(res.seeds[0].idType, 'arxiv');
      assert.equal(res.seeds[0].abstract, 'An abstract.', 'a caller-supplied abstract is preserved');
      assert.equal(res.seeds[1].idType, 'title-hash');
      assert.equal(res.seeds[1].id, si.titleHashFor('A Listed Title Seed'));
    } finally {
      fs.rmSync(listDir, { recursive: true, force: true });
    }
  });

  test('an unreadable or non-array --seed-list fails with a named reason', async () => {
    const missing = await normalizeSeedInput({ seedListPath: path.join(os.tmpdir(), 'litrev-w10-no-such-file.json') });
    assert.equal(missing.ok, false);
    assert.match(missing.rejected[0].reason, /not readable JSON/);

    const listDir = fs.mkdtempSync(path.join(os.tmpdir(), 'litrev-w10-badlist-'));
    const listPath = path.join(listDir, 'seeds.json');
    fs.writeFileSync(listPath, JSON.stringify({ not: 'an array' }), 'utf8');
    try {
      const notArray = await normalizeSeedInput({ seedListPath: listPath });
      assert.equal(notArray.ok, false);
      assert.match(notArray.rejected[0].reason, /JSON ARRAY/);
    } finally {
      fs.rmSync(listDir, { recursive: true, force: true });
    }
  });
});

describe('Wave 10 — deterministic LIST-layer dedupe: exact keys collapse, nothing fuzzy', () => {
  test('exact identity-key duplicates collapse (across spellings) with a merge record', async () => {
    const { seeds } = await normalizeSeedInput({
      seedSpecs: ['doi:10.1000/ABC|First Spelling', 'https://doi.org/10.1000/abc|Second Spelling', 'pmid:7|Other'],
    });
    const dedupe = await dedupeSeedList(seeds);
    assert.equal(dedupe.seeds.length, 2);
    assert.deepStrictEqual(
      dedupe.merges.map(({ key, absorbedCount }) => ({ key, absorbedCount })),
      [{ key: 'doi:10.1000/abc', absorbedCount: 1 }],
    );
    assert.equal(dedupe.seeds[0].title, 'First Spelling', 'first occurrence wins deterministically');
  });

  test('DETERMINISM: the same input dedupes to a deep-equal result on repeated runs', async () => {
    const { seeds } = await normalizeSeedInput({
      seedSpecs: ['doi:10.1000/a|A', 'doi:10.1000/a|A again', 'pmid:9|B', 'title:Some Loose Note'],
    });
    const first = await dedupeSeedList(seeds);
    const second = await dedupeSeedList(seeds);
    assert.deepStrictEqual(second, first);
  });

  test('NO fuzzy merge: different identity keys stay distinct even with IDENTICAL titles', async () => {
    const { seeds } = await normalizeSeedInput({
      seedSpecs: ['doi:10.1000/same|The Same Paper', 'pmid:31415|The Same Paper'],
    });
    const dedupe = await dedupeSeedList(seeds);
    assert.equal(dedupe.seeds.length, 2, 'same-paper-ness across id types is proven at snowball, never by title');
    assert.deepStrictEqual(dedupe.merges, []);
    assert.deepStrictEqual(dedupe.collisions, [], 'id-carrying seeds are not collision-flagged');
  });

  test('id-less seeds: exact-equal NORMALIZED titles share a title-hash key and collapse (exact, not fuzzy)', async () => {
    const { seeds } = await normalizeSeedInput({
      seedSpecs: ['title:The  Same   Paper!', 'The Same Paper'],
    });
    assert.equal(si.normalizeTitleForHash(seeds[0].title), si.normalizeTitleForHash(seeds[1].title));
    const dedupe = await dedupeSeedList(seeds);
    assert.equal(dedupe.seeds.length, 1);
    assert.equal(dedupe.merges.length, 1);
    assert.deepStrictEqual(dedupe.collisions, []);
  });

  test('id-less seeds with SIMILAR-but-not-equal titles are kept DISTINCT and FLAGGED for the user', async () => {
    const { seeds } = await normalizeSeedInput({
      seedSpecs: [
        'title:Scaling Laws for Neural LMs',
        'title:Scaling Laws for Neural Language Models',
        'title:Quantum Error Correction Basics',
      ],
    });
    const dedupe = await dedupeSeedList(seeds);
    // ALL are kept — no merge occurred anywhere.
    assert.equal(dedupe.seeds.length, 3);
    assert.deepStrictEqual(dedupe.merges, []);
    // Exactly the similar pair is flagged; the dissimilar title flags nothing.
    assert.equal(dedupe.collisions.length, 1);
    const flag = dedupe.collisions[0];
    assert.equal(flag.leftTitle, 'Scaling Laws for Neural LMs');
    assert.equal(flag.rightTitle, 'Scaling Laws for Neural Language Models');
    assert.match(flag.reason, /kept DISTINCT/);
    assert.match(flag.reason, /refuses to fuzzy-merge/);
  });

  test('id-less containment (one normalized title inside the other) also flags, still no merge', async () => {
    const { seeds } = await normalizeSeedInput({
      seedSpecs: ['title:Scaling Laws', 'title:Scaling Laws for Neural LMs and Their Limits In Very Long Contexts'],
    });
    const dedupe = await dedupeSeedList(seeds);
    assert.equal(dedupe.seeds.length, 2);
    assert.equal(dedupe.collisions.length, 1);
  });
});

describe('Wave 10 — deterministic SNOWBALL-layer merge: exact paperId identity', () => {
  /** Hand-built per-seed results (the merge consumes performSnowballSearch's shape). */
  function syntheticRuns() {
    const runA = {
      seed: { idType: 'doi', id: '10.1000/a', title: 'Paper A' },
      entityId: 'DOI:10.1000/a',
      result: {
        graph: {
          nodes: [
            { paperId: 'PA', title: 'Paper A', venue: 'Nature', year: 2020, status: 'included', reason: null },
            { paperId: 'PX', title: 'Paper X', venue: 'Nature', year: 2001, status: 'excluded', reason: 'date-range' },
          ],
          edges: [{ source: 'PA', target: 'PX' }],
        },
        prismaExclusions: {
          exclusions: [{ paperId: 'PX', title: 'Paper X', reason: 'date-range', details: 'too old here' }],
        },
        candidates: [{ paperId: 'PA', title: 'Paper A', venue: 'Nature', year: 2020, citationCount: 5 }],
        mermaid: 'graph TD\n',
      },
    };
    const runB = {
      seed: { idType: 'pmid', id: '99', title: 'Paper B' },
      entityId: 'PMID:99',
      result: {
        graph: {
          nodes: [
            { paperId: 'PB', title: 'Paper B', venue: 'Science', year: 2021, status: 'included', reason: null },
            { paperId: 'PX', title: 'Paper X', venue: 'Nature', year: 2001, status: 'included', reason: null },
          ],
          edges: [{ source: 'PB', target: 'PX' }],
        },
        prismaExclusions: { exclusions: [] },
        candidates: [
          { paperId: 'PB', title: 'Paper B', venue: 'Science', year: 2021, citationCount: 8 },
          { paperId: 'PX', title: 'Paper X', venue: 'Nature', year: 2001, citationCount: 50 },
        ],
        mermaid: 'graph TD\n',
      },
    };
    return [runA, runB];
  }

  test('papers merge by EXACT paperId; a candidate anywhere wins over a stale per-run exclusion', () => {
    const merged = mergeSnowballResults(syntheticRuns(), DEFAULT_VENUE_WHITELIST);
    // PX appears once, as a CANDIDATE (candidate-wins), and its exclusion is dropped.
    assert.deepStrictEqual(
      merged.candidates.map((c) => c.paperId).sort(),
      ['PA', 'PB', 'PX'],
    );
    assert.deepStrictEqual(merged.prismaExclusions.exclusions, []);
    const pxNode = merged.graph.nodes.find((n) => n.paperId === 'PX');
    assert.equal(pxNode.status, 'included');
    assert.equal(pxNode.reason, null);
    assert.equal(merged.graph.nodes.length, 3);
    assert.equal(merged.graph.edges.length, 2);
    // Different seed papers: no seed merge to record.
    assert.deepStrictEqual(merged.seedMerges, []);
  });

  test('runs whose seeds resolve to the SAME paperId merge, attributed by precedence (never by input order)', () => {
    const doiRun = {
      seed: { idType: 'doi', id: '10.1000/dup', title: 'Dup' },
      entityId: 'DOI:10.1000/dup',
      result: {
        graph: { nodes: [{ paperId: 'PD', title: 'Dup', venue: 'Nature', year: 2020, status: 'included', reason: null }], edges: [] },
        prismaExclusions: { exclusions: [] },
        candidates: [{ paperId: 'PD', title: 'Dup', venue: 'Nature', year: 2020, citationCount: 1 }],
        mermaid: 'graph TD\n',
      },
    };
    const arxivRun = {
      ...doiRun,
      seed: { idType: 'arxiv', id: '2401.00001', title: 'Dup' },
      entityId: 'arXiv:2401.00001',
    };
    for (const order of [[doiRun, arxivRun], [arxivRun, doiRun]]) {
      const merged = mergeSnowballResults(order, DEFAULT_VENUE_WHITELIST);
      assert.deepStrictEqual(merged.seedMerges, [
        { paperId: 'PD', kept: 'doi:10.1000/dup', absorbed: ['arxiv:2401.00001'] },
      ]);
      assert.equal(merged.seedPapers.length, 1);
      assert.equal(merged.seedPapers[0].seed.idType, 'doi');
      assert.equal(merged.candidates.length, 1);
    }
  });

  test('DETERMINISM: the same runs merge to a deep-equal result on repeated calls', () => {
    const first = mergeSnowballResults(syntheticRuns(), DEFAULT_VENUE_WHITELIST);
    const second = mergeSnowballResults(syntheticRuns(), DEFAULT_VENUE_WHITELIST);
    assert.deepStrictEqual(second, first);
  });
});
