import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  getTypeWeight,
  resolveConflictsAndCorroborate,
  populateMatrix,
  formatMarkdownLedger,
  runFinalSynthesis,
  aggregateConsensus,
  getRungMultiplier,
  calculateConsensusScore
} from '../src/synthesis.mjs';

const MOCK_SOURCE_1 = {
  title: 'Attention Is All You Need',
  authors: ['Ashish Vaswani'],
  venue: 'NeurIPS',
  year: 2017,
  citationCount: 1000,
  entityId: 'ss-1'
};

const MOCK_SOURCE_2 = {
  title: 'BERT: Pre-training of Deep Bidirectional Transformers',
  authors: ['Jacob Devlin'],
  venue: 'NAACL',
  year: 2019,
  citationCount: 500,
  entityId: 'ss-2'
};

describe('Wave 6: Type Weighting', () => {
  test('returns correct weight for each Truth Ladder level', () => {
    assert.equal(getTypeWeight('OBSERVED'), 3);
    assert.equal(getTypeWeight('CORROBORATED'), 2);
    assert.equal(getTypeWeight('CLAIMED'), 1);
    assert.equal(getTypeWeight('UNKNOWN'), 0);
  });
});

describe('Wave 6: Conflict Resolution & Corroboration', () => {
  test('resolves identical topic claims by selecting the highest weight', () => {
    const assumptions = [
      {
        id: 'A1',
        statement: 'throughput is 150 rps',
        type: 'CLAIMED',
        source: MOCK_SOURCE_2
      },
      {
        id: 'A2',
        statement: 'throughput is 150 rps',
        type: 'OBSERVED',
        source: MOCK_SOURCE_1
      }
    ];

    const result = resolveConflictsAndCorroborate(assumptions);
    assert.equal(result.length, 1);
    assert.equal(result[0].type, 'OBSERVED'); // Winner should be OBSERVED
    assert.equal(result[0].source.entityId, MOCK_SOURCE_1.entityId); // Winner source should be MOCK_SOURCE_1
    assert.ok(result[0].corroborationSources.includes(MOCK_SOURCE_2.entityId));
  });

  test('upgrades CLAIMED to CORROBORATED when multiple independent sources agree', () => {
    const assumptions = [
      {
        id: 'A1',
        statement: 'latency is 12ms',
        type: 'CLAIMED',
        source: MOCK_SOURCE_1
      },
      {
        id: 'A2',
        statement: 'latency is 12ms',
        type: 'CLAIMED',
        source: MOCK_SOURCE_2
      }
    ];

    const result = resolveConflictsAndCorroborate(assumptions);
    assert.equal(result.length, 1);
    assert.equal(result[0].type, 'CORROBORATED'); // CLAIMED + CLAIMED should resolve to CORROBORATED
    assert.ok(result[0].corroborationSources.includes(MOCK_SOURCE_2.entityId));
  });

  test('records conflicting claims under conflicts property of the winner', () => {
    const assumptions = [
      {
        id: 'A1',
        statement: 'throughput is 150 rps',
        type: 'OBSERVED',
        source: MOCK_SOURCE_1
      },
      {
        id: 'A2',
        statement: 'throughput is 80 rps under heavy load',
        type: 'CLAIMED',
        source: MOCK_SOURCE_2
      }
    ];

    const result = resolveConflictsAndCorroborate(assumptions);
    assert.equal(result.length, 1); // Grouped under same normalized topic "throughput-rps"
    const resolved = result[0];
    assert.equal(resolved.type, 'OBSERVED'); // OBSERVED > CLAIMED
    assert.equal(resolved.statement, 'throughput is 150 rps');
    assert.equal(resolved.conflicts.length, 1);
    assert.equal(resolved.conflicts[0].statement, 'throughput is 80 rps under heavy load');
    assert.equal(resolved.conflicts[0].sourceId, MOCK_SOURCE_2.entityId);
  });

  test('adjusts confidence correctly based on corroboration and conflict counts', () => {
    // 1. Observed, no conflicts, no corroboration
    const assObs = [{ id: '1', statement: 'test', type: 'OBSERVED', source: MOCK_SOURCE_1 }];
    const resObs = resolveConflictsAndCorroborate(assObs);
    assert.equal(resObs[0].confidence, 0.9);

    // 2. Claimed, corroborated by 2 other papers
    const assCorrob = [
      { id: '1', statement: 'test', type: 'CLAIMED', source: MOCK_SOURCE_1 },
      { id: '2', statement: 'test', type: 'CLAIMED', source: MOCK_SOURCE_2 },
      { id: '3', statement: 'test', type: 'CLAIMED', source: { ...MOCK_SOURCE_2, entityId: 'ss-3' } }
    ];
    const resCorrob = resolveConflictsAndCorroborate(assCorrob);
    assert.equal(resCorrob[0].type, 'CORROBORATED');
    // Base for CORROBORATED is 0.7. Unique corrob sources: ss-2, ss-3 (+0.10) => 0.80
    assert.equal(resCorrob[0].confidence, 0.80);

    // 3. Observed with 1 conflict
    const assConf = [
      { id: '1', statement: 'test', type: 'OBSERVED', source: MOCK_SOURCE_1 },
      { id: '2', statement: 'test conflict', type: 'CLAIMED', source: MOCK_SOURCE_2 }
    ];
    const resConf = resolveConflictsAndCorroborate(assConf);
    // Base 0.9 - 0.15 => 0.75
    assert.equal(resConf[0].confidence, 0.75);
  });
});

describe('Wave 6: Matrix Population', () => {
  test('fully populates the parameterized matrix, defaulting missing values to null', () => {
    const candidates = [
      {
        paperId: 'ss-1',
        title: 'Paper One',
        matrixRow: {
          paperId: 'ss-1',
          values: { throughput: 150, latency: '12ms' }
        }
      },
      {
        paperId: 'ss-2',
        title: 'Paper Two'
      }
    ];

    const columns = ['throughput', 'latency', 'accuracy'];
    const matrix = populateMatrix(candidates, columns);

    assert.deepEqual(matrix.columns, columns);
    assert.equal(matrix.rows.length, 2);

    assert.equal(matrix.rows[0].paperId, 'ss-1');
    assert.equal(matrix.rows[0].values.throughput, 150);
    assert.equal(matrix.rows[0].values.latency, '12ms');
    assert.equal(matrix.rows[0].values.accuracy, null); // Defaulted

    assert.equal(matrix.rows[1].paperId, 'ss-2');
    assert.equal(matrix.rows[1].values.throughput, null);
    assert.equal(matrix.rows[1].values.latency, null);
    assert.equal(matrix.rows[1].values.accuracy, null);
  });
});

describe('Wave 6: Final Synthesis Integration', () => {
  test('runs final synthesis pipeline and writes output to disk', async () => {
    const candidates = [
      {
        paperId: 'ss-1',
        title: 'Attention Is All You Need',
        venue: 'NeurIPS',
        year: 2017,
        citationCount: 1000,
        ledger: {
          assumptions: [
            { id: 'A1', statement: 'throughput is 150 rps', type: 'OBSERVED' }
          ]
        },
        matrix: {
          columns: ['throughput', 'latency'],
          rows: [
            { paperId: 'ss-1', title: 'Attention Is All You Need', values: { throughput: 150, latency: '12ms' } }
          ]
        }
      },
      {
        paperId: 'ss-2',
        title: 'BERT',
        venue: 'NAACL',
        year: 2019,
        citationCount: 500,
        ledger: {
          assumptions: [
            { id: 'A2', statement: 'throughput is 150 rps', type: 'CLAIMED' },
            { id: 'A3', statement: 'accuracy is 99%', type: 'CLAIMED' }
          ]
        }
      }
    ];

    const scratchDir = path.join(process.cwd(), 'scratch');
    await fs.mkdir(scratchDir, { recursive: true });

    const ledgerJsonPath = path.join(scratchDir, 'test-synth-ledger.json');
    const ledgerMarkdownPath = path.join(scratchDir, 'test-synth-ledger.md');
    const matrixJsonPath = path.join(scratchDir, 'test-synth-matrix.json');

    const result = await runFinalSynthesis(candidates, ['throughput', 'latency', 'accuracy'], {
      ledgerJsonPath,
      ledgerMarkdownPath,
      matrixJsonPath
    });

    assert.ok(result.ledger);
    assert.ok(result.matrix);
    assert.ok(result.markdown);

    // Verify assumptions output
    assert.equal(result.ledger.assumptions.length, 2);
    assert.equal(result.ledger.assumptions[0].type, 'OBSERVED');
    assert.equal(result.ledger.assumptions[1].type, 'CLAIMED');

    // Verify matrix output
    assert.equal(result.matrix.rows.length, 2);
    assert.equal(result.matrix.rows[0].values.throughput, 150);
    assert.equal(result.matrix.rows[0].values.accuracy, null);

    // Verify files were written
    const ledgerExists = await fs.access(ledgerJsonPath).then(() => true).catch(() => false);
    const mdExists = await fs.access(ledgerMarkdownPath).then(() => true).catch(() => false);
    const matrixExists = await fs.access(matrixJsonPath).then(() => true).catch(() => false);

    assert.ok(ledgerExists);
    assert.ok(mdExists);
    assert.ok(matrixExists);

    // Cleanup
    await fs.unlink(ledgerJsonPath);
    await fs.unlink(ledgerMarkdownPath);
    await fs.unlink(matrixJsonPath);
  });
});

describe('Wave 6: Weighted Consensus Aggregator', () => {
  test('correctly computes weighted consensus stance score and verdict', async () => {
    const assumptions = [
      {
        id: 'A1',
        statement: 'Transformer has throughput of 150 rps',
        type: 'OBSERVED', // weight = 3
        source: MOCK_SOURCE_1
      },
      {
        id: 'A2',
        statement: 'Traditional models only reach 80 rps under load',
        type: 'CLAIMED', // weight = 1
        source: MOCK_SOURCE_2
      },
      {
        id: 'A3',
        statement: 'The overhead degrades latency slightly',
        type: 'CLAIMED', // weight = 1
        source: MOCK_SOURCE_2
      }
    ];

    // Mock stances:
    // A1 supports the query "Does it improve throughput?" (+1)
    // A2 contradicts the query (-1)
    // A3 is irrelevant/neutral (not included or neutral)
    const mockStances = {
      'Transformer has throughput of 150 rps': { relevant: true, stance: 'supports' },
      'Traditional models only reach 80 rps under load': { relevant: true, stance: 'contradicts' },
      'The overhead degrades latency slightly': { relevant: false, stance: 'neutral' }
    };

    const result = await aggregateConsensus(assumptions, 'Does it improve throughput?', null, {
      mockStances
    });

    // Weighted stance sum: (1 * 3) + (-1 * 1) = 2
    // Total weight: 3 + 1 = 4
    // Expected score: 2 / 4 = 0.50
    // Verdict for >= 0.5 is "Strongly Supports"
    assert.equal(result.score, 0.50);
    assert.equal(result.verdict, 'Strongly Supports');
    assert.equal(result.relevantCount, 2);
  });
});

describe('Wave 6: Consensus Score Calculations & REFUTED Type', () => {
  test('calculates correct consensus score based on rung multipliers', () => {
    const aObs = { type: 'OBSERVED', source: { citationCount: 100 } };
    const aCor = { type: 'CORROBORATED', source: { citationCount: 100 } };
    const aClm = { type: 'CLAIMED', source: { citationCount: 100 } };
    const aRef = { type: 'REFUTED', source: { citationCount: 100 } };
    const aNoCit = { type: 'OBSERVED', source: {} };

    assert.equal(calculateConsensusScore(aObs), 100.0);
    assert.equal(calculateConsensusScore(aCor), 70.0);
    assert.equal(calculateConsensusScore(aClm), 40.0);
    assert.equal(calculateConsensusScore(aRef), -100.0);
    assert.equal(calculateConsensusScore(aNoCit), 0.0);
  });

  test('resolves conflicting claims in favor of the highest consensus score', () => {
    const assumptions = [
      {
        id: 'A1',
        statement: 'throughput is high',
        type: 'CLAIMED',
        source: { ...MOCK_SOURCE_1, citationCount: 1000 } // 1000 * 0.4 = 400
      },
      {
        id: 'A2',
        statement: 'throughput is low',
        type: 'OBSERVED',
        source: { ...MOCK_SOURCE_2, citationCount: 500 } // 500 * 1.0 = 500
      }
    ];

    const result = resolveConflictsAndCorroborate(assumptions);
    assert.equal(result.length, 1);
    assert.equal(result[0].statement, 'throughput is low'); // Winner is OBSERVED with 500 score (500 > 400)
    assert.equal(result[0].conflicts.length, 1);
    assert.equal(result[0].conflicts[0].statement, 'throughput is high');
  });

  test('resolves CLAIMED claim with high citations over OBSERVED claim with very low citations', () => {
    const assumptions = [
      {
        id: 'A1',
        statement: 'throughput is high',
        type: 'CLAIMED',
        source: { ...MOCK_SOURCE_1, citationCount: 2000 } // 2000 * 0.4 = 800
      },
      {
        id: 'A2',
        statement: 'throughput is low',
        type: 'OBSERVED',
        source: { ...MOCK_SOURCE_2, citationCount: 100 } // 100 * 1.0 = 100
      }
    ];

    const result = resolveConflictsAndCorroborate(assumptions);
    assert.equal(result.length, 1);
    assert.equal(result[0].statement, 'throughput is high'); // Winner is CLAIMED because 800 > 100
    assert.equal(result[0].conflicts.length, 1);
    assert.equal(result[0].conflicts[0].statement, 'throughput is low');
  });
});
