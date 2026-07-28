import { test, describe } from 'node:test';
import assert from 'node:assert';
import { validateSchema, ValidationError } from '../src/validateSchema.mjs';

describe('Schema Validator - Assumptions Ledger', () => {
  test('passes a valid assumptions ledger payload', () => {
    const validPayload = {
      assumptions: [
        {
          id: 'A1',
          statement: 'This is a tested observation',
          type: 'OBSERVED',
          source: {
            title: 'Foundational AI Research',
            authors: ['Author One', 'Author Two'],
            venue: 'NeurIPS',
            year: 2024,
            citationCount: 42,
            entityId: 'ss-12345'
          },
          confidence: 0.95,
          context: 'Section 3.2, page 5',
          corroborationSources: ['Title B', 'Title C'],
          conflicts: []
        },
        {
          id: 'A2',
          statement: 'Authors claim standard behavior',
          type: 'CLAIMED',
          source: {
            title: 'Some Paper Title',
            authors: ['Other Author'],
            venue: 'ArXiv',
            year: 2025
          }
        }
      ]
    };

    assert.equal(validateSchema(validPayload, 'AssumptionsLedger'), true);
    assert.equal(validateSchema(validPayload, 'assumptionsLedger'), true);
  });

  test('fails an assumptions ledger with missing required fields', () => {
    const invalidPayload = {
      assumptions: [
        {
          id: 'A1',
          statement: 'Missing source and type fields'
        }
      ]
    };

    assert.throws(() => {
      validateSchema(invalidPayload, 'AssumptionsLedger');
    }, ValidationError);
  });

  test('fails an assumptions ledger with invalid type enum value', () => {
    const invalidPayload = {
      assumptions: [
        {
          id: 'A1',
          statement: 'Invalid type enum test',
          type: 'GUESS',
          source: {
            title: 'Foundational AI Research',
            authors: ['Author One'],
            venue: 'NeurIPS',
            year: 2024
          }
        }
      ]
    };

    assert.throws(() => {
      validateSchema(invalidPayload, 'AssumptionsLedger');
    }, ValidationError);
  });
});

describe('Schema Validator - Parameterized Matrix', () => {
  test('passes a valid parameterized matrix payload', () => {
    const validPayload = {
      columns: ['throughput', 'latency', 'accuracy'],
      rows: [
        {
          paperId: 'ss-1',
          title: 'Fast Inference Paper',
          values: {
            throughput: 120.5,
            latency: '15ms',
            accuracy: true
          }
        },
        {
          paperId: 'ss-2',
          title: 'Accurate model paper',
          values: {
            throughput: null,
            latency: '200ms',
            accuracy: 0.99
          }
        }
      ]
    };

    assert.equal(validateSchema(validPayload, 'ParameterizedMatrix'), true);
  });

  test('fails a matrix with missing required elements', () => {
    const invalidPayload = {
      columns: ['throughput'],
      rows: [
        {
          paperId: 'ss-1'
        }
      ]
    };

    assert.throws(() => {
      validateSchema(invalidPayload, 'ParameterizedMatrix');
    }, ValidationError);
  });

  test('fails a matrix with disallowed additional property types inside values', () => {
    const invalidPayload = {
      columns: ['throughput'],
      rows: [
        {
          paperId: 'ss-1',
          title: 'Some Paper',
          values: {
            throughput: { min: 10, max: 20 }
          }
        }
      ]
    };

    assert.throws(() => {
      validateSchema(invalidPayload, 'ParameterizedMatrix');
    }, ValidationError);
  });
});

describe('Schema Validator - Venue Whitelist', () => {
  test('passes a valid venue whitelist payload', () => {
    const validPayload = {
      venues: [
        { name: 'NeurIPS', abbr: 'NeurIPS', tier: 'Tier-1' },
        { name: 'International Conference on Machine Learning', abbr: 'ICML', tier: 'Tier-1' },
        { name: 'Some Tier-3 Journal', abbr: 'STJ', tier: 'Tier-3' }
      ]
    };

    assert.equal(validateSchema(validPayload, 'VenueWhitelist'), true);
  });

  test('fails a venue whitelist with invalid tier', () => {
    const invalidPayload = {
      venues: [
        { name: 'Low Tier Conf', abbr: 'LTC', tier: 'Tier-4' }
      ]
    };

    assert.throws(() => {
      validateSchema(invalidPayload, 'VenueWhitelist');
    }, ValidationError);
  });
});

describe('Schema Validator - PRISMA Exclusions', () => {
  test('passes a valid prisma exclusions payload', () => {
    const validPayload = {
      exclusions: [
        {
          paperId: 'ss-99',
          title: 'Ancient AI paper',
          reason: 'date-range',
          details: 'Published in 1980, limit is >= 2018'
        },
        {
          paperId: 'ss-100',
          title: 'Not peer reviewed blog post',
          reason: 'low-venue'
        }
      ]
    };

    assert.equal(validateSchema(validPayload, 'PrismaExclusions'), true);
    assert.equal(validateSchema(validPayload, 'prismaExclusions'), true);
  });

  test('fails a prisma exclusions payload with an invalid reason enum', () => {
    const invalidPayload = {
      exclusions: [
        {
          paperId: 'ss-99',
          title: 'Ancient AI paper',
          reason: 'too-expensive'
        }
      ]
    };

    assert.throws(() => {
      validateSchema(invalidPayload, 'PrismaExclusions');
    }, ValidationError);
  });
});
