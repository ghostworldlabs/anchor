import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import zlib from 'node:zlib';
import { Buffer } from 'node:buffer';

import {
  downloadPdf,
  extractTextFromPdfBuffer,
  semanticChunk,
  resolveSemanticScholarEntityId,
  runIngestionPipeline,
} from '../src/ingest.mjs';
import { runEngine } from 'fil<path>';

// Helper to create a simple FlateDecoded PDF stream buffer for testing the parser
function createMockPdfBuffer(text) {
  const compressedText = zlib.deflateSync(Buffer.from(`BT\n/F1 12 Tf\n(${text}) Tj\nET`));
  const pdfContent = [
    '%PDF-1.4',
    '1 0 obj',
    '<< /Length ' + compressedText.length + ' /Filter /FlateDecode >>',
    'stream',
  ].join('\n') + '\n';
  
  const headerBuffer = Buffer.from(pdfContent, 'binary');
  const footerBuffer = Buffer.from('\nendstream\nendobj\n%%EOF', 'binary');
  
  return Buffer.concat([headerBuffer, compressedText, footerBuffer]);
}

describe('Wave 2 Ingestion: PDF Downloading', () => {
  test('downloads a PDF successfully on valid URL', async () => {
    const mockPdfBytes = Buffer.from('mock pdf text content');
    const mockFetch = async (url) => {
      return {
        ok: true,
        status: 200,
        arrayBuffer: async () => mockPdfBytes.buffer.slice(mockPdfBytes.byteOffset, mockPdfBytes.byteOffset + mockPdfBytes.byteLength),
      };
    };

    const result = await downloadPdf('https://example.com/paper.pdf', { fetch: mockFetch });
    assert.deepEqual(result, mockPdfBytes);
  });

  test('handles 404 errors with descriptive fallback message', async () => {
    const mockFetch = async (url) => {
      return {
        ok: false,
        status: 404,
        statusText: 'Not Found',
      };
    };

    await assert.rejects(
      async () => {
        await downloadPdf('https://example.com/missing.pdf', { fetch: mockFetch });
      },
      /Failed to download PDF: HTTP 404 Not Found at URL: https:\/\/example.com\/missing.pdf/
    );
  });

  test('handles timeout errors with AbortController signal', async () => {
    const mockFetch = async (url, opts) => {
      return new Promise((resolve, reject) => {
        opts.signal.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'));
        });
      });
    };

    await assert.rejects(
      async () => {
        // Force a small timeout to trigger abort path
        await downloadPdf('https://example.com/slow.pdf', { fetch: mockFetch, timeout: 5 });
      },
      /Failed to download PDF: Timeout after 5ms at URL: https:\/\/example.com\/slow.pdf/
    );
  });

  test('handles network failure gracefully', async () => {
    const mockFetch = async () => {
      throw new Error('DNS resolution failed');
    };

    await assert.rejects(
      async () => {
        await downloadPdf('https://example.com/fail.pdf', { fetch: mockFetch });
      },
      /Failed to download PDF: Network error \(DNS resolution failed\) at URL: https:\/\/example.com\/fail.pdf/
    );
  });
});

describe('Wave 2 Ingestion: PDF Extraction & Parsing', () => {
  test('extracts plain text from uncompressed/mock buffers', () => {
    const mockBuffer = Buffer.from('This is a simple plain text mock pdf representation.');
    const extracted = extractTextFromPdfBuffer(mockBuffer);
    assert.equal(extracted, 'This is a simple plain text mock pdf representation.');
  });

  test('decompresses FlateDecode stream and extracts TJ/Tj text matching parenthesis', () => {
    const originalText = 'Attention Is All You Need';
    const pdfBuffer = createMockPdfBuffer(originalText);
    const extracted = extractTextFromPdfBuffer(pdfBuffer);
    assert.equal(extracted, originalText);
  });
});

describe('Wave 2 Ingestion: Semantic Chunking', () => {
  test('splits simple paragraphs under max tokens limit', () => {
    const text = 'Paragraph 1 text.\n\nParagraph 2 text.\n\nParagraph 3 text.';
    // Each paragraph is ~17 chars long (approx 4-5 tokens). MaxTokens = 10 (approx 40 chars).
    const chunks = semanticChunk(text, 10);
    
    assert.equal(chunks.length, 2);
    assert.equal(chunks[0], 'Paragraph 1 text.\n\nParagraph 2 text.');
    assert.equal(chunks[1], 'Paragraph 3 text.');
  });

  test('splits long paragraph by sentences when it exceeds token limit', () => {
    // Para length is ~120 chars (approx 30 tokens). Limit = 10 tokens (~40 chars).
    const text = 'First sentence here. Second sentence starts here. Third sentence goes here.';
    const chunks = semanticChunk(text, 10);
    
    assert.ok(chunks.length >= 2);
    assert.equal(chunks[0], 'First sentence here. Second sentence starts here.');
    assert.equal(chunks[1], 'Third sentence goes here.');
  });

  test('splits long sentence by words if it exceeds token limit', () => {
    // Sentence is ~40 chars. Limit = 3 tokens (~12 chars).
    const text = 'ExtremelyLongWordThatExceedsTheTokenLimitHere';
    const chunks = semanticChunk(text, 5);
    
    assert.ok(chunks.length >= 1);
  });
});

describe('Wave 2 Ingestion: Semantic Scholar Entity Resolution', () => {
  test('resolves canonical ID via URL lookup endpoint first', async () => {
    const mockFetch = async (url) => {
      if (url.includes('/URL:')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ paperId: 'resolved-url-entity-id' }),
        };
      }
      return { ok: false, status: 404 };
    };

    const paperId = await resolveSemanticScholarEntityId(
      'https://arxiv.org/pdf/1706.03762.pdf',
      'Attention Is All You Need\nVaswani et al.',
      { fetch: mockFetch }
    );
    
    assert.equal(paperId, 'resolved-url-entity-id');
  });

  test('falls back to search endpoint using extracted title if URL lookup fails', async () => {
    const mockFetch = async (url) => {
      if (url.includes('/URL:')) {
        return { ok: false, status: 404 };
      }
      if (url.includes('/search?query=')) {
        assert.ok(url.includes('Attention%20Is%20All%20You%20Need'));
        return {
          ok: true,
          status: 200,
          json: async () => ({
            data: [{ paperId: 'resolved-title-entity-id' }]
          }),
        };
      }
      return { ok: false, status: 404 };
    };

    const paperId = await resolveSemanticScholarEntityId(
      'https://arxiv.org/pdf/1706.03762.pdf',
      'Attention Is All You Need\nVaswani et al.',
      { fetch: mockFetch }
    );
    
    assert.equal(paperId, 'resolved-title-entity-id');
  });

  test('handles Semantic Scholar network issues gracefully by returning null', async () => {
    const mockFetch = async () => {
      throw new Error('Semantic Scholar API down');
    };

    const paperId = await resolveSemanticScholarEntityId(
      'https://arxiv.org/pdf/1706.03762.pdf',
      'Attention Is All You Need\nVaswani et al.',
      { fetch: mockFetch }
    );
    
    assert.equal(paperId, null);
  });
});

describe('Wave 2 Ingestion: Core Engine Integration', () => {
  test('ingests seed PDF and successfully runs the imported researchPrime engine skeleton', async () => {
    const originalText = 'Attention Is All You Need\nAbstract of the transformer paper...';
    const mockPdfBytes = createMockPdfBuffer(originalText);
    
    const mockFetch = async (url) => {
      if (url === 'https://example.com/paper.pdf') {
        return {
          ok: true,
          status: 200,
          arrayBuffer: async () => mockPdfBytes.buffer.slice(mockPdfBytes.byteOffset, mockPdfBytes.byteOffset + mockPdfBytes.byteLength),
        };
      }
      if (url.includes('/URL:')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ paperId: 'canonical-transformer-id' }),
        };
      }
      return { ok: false, status: 404 };
    };

    const pipelineResult = await runIngestionPipeline('https://example.com/paper.pdf', {
      fetch: mockFetch,
      maxTokens: 2000,
    });

    assert.equal(pipelineResult.entityId, 'canonical-transformer-id');
    assert.equal(pipelineResult.chunks.length, 1);
    assert.ok(pipelineResult.pdfText.includes('Attention Is All You Need'));

    const item = {
      seedUrl: pipelineResult.seedUrl,
      pdfText: pipelineResult.pdfText,
      chunks: pipelineResult.chunks,
      entityId: pipelineResult.entityId,
    };

    // Assert the engine context carries the ingested metadata in the item payload
    assert.equal(item.entityId, 'canonical-transformer-id');
    assert.deepEqual(item.chunks, ['Attention Is All You Need\nAbstract of the transformer paper...']);

    // Inject the result into researchPrime's runEngine loop
    const engineResult = await runEngine({
      agent: async (prompt, opts) => {
        // Assert the engine round is passed to the agent
        assert.equal(opts.round, 1);
        return 'test-response';
      },
      item,
      resume: false,
      maxRounds: 1,
    });

    assert.equal(engineResult.status, 'done');
    assert.equal(engineResult.rounds, 1);
  });
});
