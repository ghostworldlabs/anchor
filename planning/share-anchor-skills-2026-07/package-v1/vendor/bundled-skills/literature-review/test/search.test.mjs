import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  matchVenue,
  rankCandidates,
  evaluateFilters,
  generateMermaidGraph,
  performSnowballSearch
} from '../src/search.mjs';

const MOCK_WHITELIST = {
  venues: [
    { name: 'Conference on Neural Information Processing Systems', abbr: 'NeurIPS', tier: 'Tier-1' },
    { name: 'International Conference on Machine Learning', abbr: 'ICML', tier: 'Tier-1' },
    { name: 'ACM Conference on Computer and Communications Security', abbr: 'CCS', tier: 'Tier-2' },
    { name: 'Some Local Workshop', abbr: 'SLW', tier: 'Tier-3' }
  ]
};

describe('Wave 4: Venue Whitelist Matching', () => {
  test('matches venue exactly case-insensitively by name or abbreviation', () => {
    assert.deepEqual(matchVenue('NeurIPS', MOCK_WHITELIST), MOCK_WHITELIST.venues[0]);
    assert.deepEqual(matchVenue('icml', MOCK_WHITELIST), MOCK_WHITELIST.venues[1]);
    assert.deepEqual(matchVenue('Conference on Neural Information Processing Systems', MOCK_WHITELIST), MOCK_WHITELIST.venues[0]);
  });

  test('matches venue via substring fallback', () => {
    // Whitelist has "Conference on Neural Information Processing Systems"
    assert.deepEqual(matchVenue('Neural Information Processing Systems', MOCK_WHITELIST), MOCK_WHITELIST.venues[0]);
    // Paper venue is "NeurIPS workshop"
    assert.deepEqual(matchVenue('NeurIPS 2024', MOCK_WHITELIST), MOCK_WHITELIST.venues[0]);
  });

  test('returns null when venue is not in the whitelist', () => {
    assert.equal(matchVenue('Unknown Conference', MOCK_WHITELIST), null);
    assert.equal(matchVenue('', MOCK_WHITELIST), null);
    assert.equal(matchVenue(null, MOCK_WHITELIST), null);
  });
});

describe('Wave 4: Candidate Ranking', () => {
  test('ranks candidates by whitelist tier, then citations, then year, then ID', () => {
    const candidates = [
      { paperId: 'p-tier2-cit100', venue: 'CCS', citationCount: 100, year: 2020 },
      { paperId: 'p-tier1-cit50', venue: 'ICML', citationCount: 50, year: 2021 },
      { paperId: 'p-tier1-cit100-y2022', venue: 'NeurIPS', citationCount: 100, year: 2022 },
      { paperId: 'p-tier1-cit100-y2021', venue: 'NeurIPS', citationCount: 100, year: 2021 },
      { paperId: 'p-tier1-cit100-y2021-tiebreak', venue: 'NeurIPS', citationCount: 100, year: 2021 }
    ];

    const ranked = rankCandidates(candidates, MOCK_WHITELIST);

    // Expected order:
    // 1. Tier-1, 100 citations, year 2022 (p-tier1-cit100-y2022)
    // 2. Tier-1, 100 citations, year 2021 (p-tier1-cit100-y2021)
    // 3. Tier-1, 100 citations, year 2021 (p-tier1-cit100-y2021-tiebreak) - alphabetical check
    // 4. Tier-1, 50 citations, year 2021 (p-tier1-cit50)
    // 5. Tier-2, 100 citations, year 2020 (p-tier2-cit100)
    assert.equal(ranked[0].paperId, 'p-tier1-cit100-y2022');
    assert.equal(ranked[1].paperId, 'p-tier1-cit100-y2021');
    assert.equal(ranked[2].paperId, 'p-tier1-cit100-y2021-tiebreak');
    assert.equal(ranked[3].paperId, 'p-tier1-cit50');
    assert.equal(ranked[4].paperId, 'p-tier2-cit100');
  });
});

describe('Wave 4: Exclusion Filtering', () => {
  test('excludes papers outside the date range', () => {
    const paper = { title: 'Old paper', venue: 'NeurIPS', year: 2010 };
    const res = evaluateFilters(paper, MOCK_WHITELIST, { minYear: 2018 });
    assert.equal(res.excluded, true);
    assert.equal(res.reason, 'date-range');
  });

  test('excludes papers lacking a PDF when required', () => {
    const paper = { title: 'No PDF paper', venue: 'NeurIPS', year: 2020 };
    const res = evaluateFilters(paper, MOCK_WHITELIST, { requirePdf: true });
    assert.equal(res.excluded, true);
    assert.equal(res.reason, 'no-pdf');
  });

  test('includes papers with PDF when required', () => {
    const paper = { title: 'Has PDF paper', venue: 'NeurIPS', year: 2020, openAccessPdf: { url: 'http://example.com' } };
    const res = evaluateFilters(paper, MOCK_WHITELIST, { requirePdf: true });
    assert.equal(res.excluded, false);
  });

  test('excludes papers from non-whitelisted venues (OPT-IN since C8 2026-07-11 — default is rank-only)', () => {
    const paper = { title: 'Random paper', venue: 'ArXiv', year: 2020 };
    // C8: venue exclusion is opt-in; the bare default no longer excludes.
    assert.equal(evaluateFilters(paper, MOCK_WHITELIST).excluded, false);
    const res = evaluateFilters(paper, MOCK_WHITELIST, { excludeByVenue: true });
    assert.equal(res.excluded, true);
    assert.equal(res.reason, 'low-venue');
  });

  test('excludes papers below the minimum venue tier', () => {
    const paper = { title: 'Tier 3 paper', venue: 'SLW', year: 2020 };
    const res = evaluateFilters(paper, MOCK_WHITELIST, { excludeByVenue: true, minTier: 'Tier-2' });
    assert.equal(res.excluded, true);
    assert.equal(res.reason, 'low-tier');
  });
});

describe('Wave 4: Visual Citation Snowball Search', () => {
  test('performs depth-bounded snowball search successfully', async () => {
    const mockDb = {
      'seed-id': {
        paperId: 'seed-id',
        title: 'Seed Paper Title',
        venue: 'NeurIPS',
        year: 2020,
        citationCount: 10,
        references: [
          { citedPaper: { paperId: 'ref-1', title: 'Ref 1 Title', venue: 'ICML', year: 2019, citationCount: 5 } },
          { citedPaper: { paperId: 'ref-2', title: 'Ref 2 Title (Excluded)', venue: 'ArXiv', year: 2018, citationCount: 1 } }
        ]
      },
      'ref-1': {
        paperId: 'ref-1',
        title: 'Ref 1 Title',
        venue: 'ICML',
        year: 2019,
        citationCount: 5,
        references: [
          { citedPaper: { paperId: 'ref-1-1', title: 'Ref 1-1 Title', venue: 'CCS', year: 2018, citationCount: 10 } }
        ]
      },
      'ref-2': {
        paperId: 'ref-2',
        title: 'Ref 2 Title (Excluded)',
        venue: 'ArXiv',
        year: 2018,
        citationCount: 1,
        references: []
      },
      'ref-1-1': {
        paperId: 'ref-1-1',
        title: 'Ref 1-1 Title',
        venue: 'CCS',
        year: 2018,
        citationCount: 10,
        references: []
      }
    };

    const mockFetch = async (url) => {
      let id = null;
      if (url.includes('/references')) {
        id = url.split('/paper/')[1].split('/references')[0];
        const record = mockDb[id];
        return {
          ok: true,
          status: 200,
          json: async () => ({ data: record ? record.references : [] })
        };
      } else {
        id = url.split('/paper/')[1].split('?')[0];
        const record = mockDb[id];
        return {
          ok: true,
          status: 200,
          json: async () => record || {}
        };
      }
    };

    const exclusionsPath = path.join(process.cwd(), 'scratch', 'test-exclusions.json');
    // Ensure dir exists
    await fs.mkdir(path.dirname(exclusionsPath), { recursive: true });

    // Run depth-2 snowball search
    const result = await performSnowballSearch('seed-id', MOCK_WHITELIST, {
      depth: 2,
      fetch: mockFetch,
      exclusionsPath,
      excludeByVenue: true, // C8: exclusion is opt-in; this test exercises the opt-in path
      minTier: 'Tier-2'
    });

    // Check outputs
    assert.ok(result.graph);
    assert.ok(result.prismaExclusions);
    assert.ok(result.candidates);
    assert.ok(result.mermaid);

    // Candidates that passed filtering: seed-id (included by default), ref-1 (Tier-1), ref-1-1 (Tier-2)
    const candidateIds = result.candidates.map(c => c.paperId);
    assert.ok(candidateIds.includes('seed-id'));
    assert.ok(candidateIds.includes('ref-1'));
    assert.ok(candidateIds.includes('ref-1-1'));
    assert.ok(!candidateIds.includes('ref-2')); // Excluded because ArXiv is not in whitelist

    // Excluded papers
    const excludedIds = result.prismaExclusions.exclusions.map(e => e.paperId);
    assert.ok(excludedIds.includes('ref-2'));
    const ref2Excl = result.prismaExclusions.exclusions.find(e => e.paperId === 'ref-2');
    assert.equal(ref2Excl.reason, 'low-venue');

    // Verify written PRISMA exclusion logs
    const writtenBytes = await fs.readFile(exclusionsPath, 'utf8');
    const writtenLog = JSON.parse(writtenBytes);
    assert.equal(writtenLog.exclusions.length, 1);
    assert.equal(writtenLog.exclusions[0].paperId, 'ref-2');

    // Clean up
    await fs.unlink(exclusionsPath);

    // Verify Mermaid graph representation contains nodes and styling
    assert.ok(result.mermaid.includes('graph TD'));
    assert.ok(result.mermaid.includes('seed-id'));
    assert.ok(result.mermaid.includes('style ref-2 fill:#ffcccc'));
    assert.ok(result.mermaid.includes('style ref-1 fill:#ccffcc'));
  });

  test('exponential backoff retries on 429 and eventually succeeds', async () => {
    let callCount = 0;
    const mockFetch = async (url) => {
      callCount++;
      if (callCount < 3) {
        return { ok: false, status: 429, statusText: 'Too Many Requests' };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          paperId: 'seed-id',
          title: 'Paper',
          venue: 'NeurIPS',
          year: 2021,
          citationCount: 10
        })
      };
    };

    const result = await performSnowballSearch('seed-id', MOCK_WHITELIST, {
      depth: 0,
      fetch: mockFetch,
      backoffFactor: 5, // use tiny delay for fast testing
      maxRetries: 3
    });

    assert.equal(callCount, 3);
    assert.equal(result.candidates[0].paperId, 'seed-id');
  });
});
