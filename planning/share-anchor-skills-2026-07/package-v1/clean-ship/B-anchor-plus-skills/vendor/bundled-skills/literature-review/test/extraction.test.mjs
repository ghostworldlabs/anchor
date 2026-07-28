import { test, describe } from 'node:test';
import assert from 'node:assert/strict';

import {
  runExtractionLoop,
  normalizeTopic,
  normalizeFindingId,
  tallyFindings,
} from '../src/extraction.mjs';

const MOCK_SOURCE = {
  title: 'Attention Is All You Need',
  authors: ['Ashish Vaswani', 'Noam Shazeer'],
  venue: 'NeurIPS',
  year: 2017,
  citationCount: 100000,
  entityId: 'ss-12345',
};

const MOCK_COLUMNS = ['throughput', 'latency', 'accuracy'];

const MOCK_CONFLICT = {
  statement: 'Throughput is 80 rps under heavy load',
  sourceId: 'traditional-benchmarks',
};

const MOCK_CHUNK = 'We evaluated the transformer model. We observed a throughput of 150 requests per second and a latency of 12ms. We claim that this represents a 2x improvement over baseline, although some traditional benchmarks might show lower throughput (e.g. 80 rps) under heavy load.';

function makeScriptedAgent() {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    const label = opts.label || '';

    if (label === 'generator:draft:r1') {
      return {
        ledger: {
          assumptions: [
            {
              id: 'A1',
              statement: 'throughput of 150 requests per second and a latency of 12ms',
              type: 'CLAIMED',
              source: MOCK_SOURCE,
              conflicts: [],
            }
          ]
        },
        matrix: {
          columns: MOCK_COLUMNS,
          rows: [
            {
              paperId: MOCK_SOURCE.entityId,
              title: MOCK_SOURCE.title,
              values: {
                throughput: 150,
                latency: '12ms',
                accuracy: null,
              }
            }
          ]
        }
      };
    }

    if (label.startsWith('shark:')) {
      const role = label.split(':')[1];
      const round = label.split(':')[2];
      if (round === 'r1') {
        if (role === 'Skeptic' || role === 'Contrarian') {
          return {
            answerable: 'yes',
            findings: [
              {
                severity: 'MAJOR',
                topic: 'throughput is observed not claimed',
                message: 'Throughput measurement should be OBSERVED type, not CLAIMED.',
              },
              {
                severity: 'BLOCKER',
                topic: 'missing mock conflict',
                message: 'The draft misses the traditional benchmarks conflict.',
              }
            ]
          };
        }
        return { answerable: 'yes', findings: [] };
      }
      return { answerable: 'yes', findings: [] };
    }

    if (label === 'synthesizer:direct:r1') {
      return {
        status: 'needs-refinement',
        probingBrief: 'Correct throughput assumption type to OBSERVED and add traditional-benchmarks mock conflict.',
      };
    }

    if (label === 'generator:refine:r2') {
      return {
        ledger: {
          assumptions: [
            {
              id: 'A1',
              statement: 'throughput of 150 requests per second and a latency of 12ms',
              type: 'OBSERVED',
              source: MOCK_SOURCE,
              conflicts: [MOCK_CONFLICT],
            }
          ]
        },
        matrix: {
          columns: MOCK_COLUMNS,
          rows: [
            {
              paperId: MOCK_SOURCE.entityId,
              title: MOCK_SOURCE.title,
              values: {
                throughput: 150,
                latency: '12ms',
                accuracy: true,
              }
            }
          ]
        }
      };
    }

    throw new Error(`Unexpected agent call: ${label}`);
  }
  agent.calls = calls;
  return agent;
}

describe('Wave 3 Ingestion: Topic Normalization', () => {
  test('normalizeTopic is wording- and order-insensitive', () => {
    assert.equal(
      normalizeTopic('throughput is observed not claimed'),
      normalizeTopic('observed throughput, not claimed'),
    );
    assert.equal(
      normalizeTopic('missing mock conflict'),
      normalizeTopic('the mock conflict is missing'),
    );
  });

  test('normalizeFindingId keys on normalized topic', () => {
    const f1 = { topic: 'throughput is observed not claimed', message: 'First msg' };
    const f2 = { topic: 'observed throughput, not claimed', message: 'Second msg' };
    assert.equal(normalizeFindingId(f1), normalizeFindingId(f2));
  });
});

describe('Wave 3 Ingestion: Shark Critique & Tallying', () => {
  test('counts agreement across different sharks and identifies blockers', () => {
    const reviews = [
      {
        reviewer: 'Skeptic',
        findings: [
          { severity: 'BLOCKER', topic: 'missing mock conflict', message: 'Missing conflict' }
        ]
      },
      {
        reviewer: 'Contrarian',
        findings: [
          { severity: 'BLOCKER', topic: 'the mock conflict is missing', message: 'No conflict' }
        ]
      }
    ];

    const tally = tallyFindings(reviews);
    assert.equal(tally.dry, false);
    assert.equal(tally.blockers.length, 1);
    assert.equal(tally.blockers[0].agreement, 2);
    assert.deepEqual(tally.blockers[0].raisedBy.sort(), ['Contrarian', 'Skeptic']);
  });

  test('single shark finding does not count as agreement blocker', () => {
    const reviews = [
      {
        reviewer: 'Skeptic',
        findings: [
          { severity: 'BLOCKER', topic: 'missing mock conflict', message: 'Missing conflict' }
        ]
      }
    ];

    const tally = tallyFindings(reviews);
    assert.equal(tally.blockers.length, 0);
    assert.equal(tally.dry, true);
  });
});

describe('Wave 3 Ingestion: Adversarial Extraction Loop', () => {
  test('runs full loop to convergence, resolving conflicts and extracting observed vs claimed data', async () => {
    const agent = makeScriptedAgent();
    const result = await runExtractionLoop(MOCK_CHUNK, MOCK_COLUMNS, agent, {
      knownMockConflict: MOCK_CONFLICT,
      sourceInfo: MOCK_SOURCE,
    });

    assert.equal(result.converged, true);
    assert.equal(result.rounds, 2);

    // Verify output exactly matches our deterministic hardcoded mock JSON expectation
    const assumption = result.ledger.assumptions[0];
    assert.equal(assumption.type, 'OBSERVED');
    assert.deepEqual(assumption.conflicts, [MOCK_CONFLICT]);
    assert.equal(assumption.source.entityId, MOCK_SOURCE.entityId);

    const row = result.matrix.rows[0];
    assert.equal(row.values.throughput, 150);
    assert.equal(row.values.latency, '12ms');
    assert.equal(row.values.accuracy, true);

    // Verify correct calls were made
    const labels = agent.calls.map(c => c.opts.label);
    assert.ok(labels.includes('generator:draft:r1'));
    assert.ok(labels.includes('shark:Skeptic:r1'));
    assert.ok(labels.includes('shark:Contrarian:r1'));
    assert.ok(labels.includes('shark:Analyst:r1'));
    assert.ok(labels.includes('synthesizer:direct:r1'));
    assert.ok(labels.includes('generator:refine:r2'));
    assert.ok(labels.includes('shark:Skeptic:r2'));
    assert.ok(labels.includes('shark:Contrarian:r2'));
    assert.ok(labels.includes('shark:Analyst:r2'));
  });

  test('fails if LLM output fails schema validation', async () => {
    const badAgent = async () => {
      // Return invalid assumptions ledger (missing source and type)
      return {
        ledger: {
          assumptions: [
            {
              id: 'A1',
              statement: 'bad'
            }
          ]
        },
        matrix: {
          columns: [],
          rows: []
        }
      };
    };

    await assert.rejects(
      async () => {
        await runExtractionLoop(MOCK_CHUNK, MOCK_COLUMNS, badAgent);
      },
      /Schema validation failed/
    );
  });
});
