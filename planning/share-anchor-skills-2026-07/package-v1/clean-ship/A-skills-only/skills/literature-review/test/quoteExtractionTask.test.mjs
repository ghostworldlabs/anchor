// Wave 3 done-when: the worker extracts quotes from raw source material that
// strictly match the normalized source text and structurally sanitizes all
// outputs to prevent formatting breakage or injection.
//
// Given raw source text with erratic whitespace and unsafe markdown/HTML
// characters, when quotes are extracted by the isolated worker and sanitized,
// then each grounded quote passes strict exact-string matching against the
// normalized source, all entities are safely encoded, and ungrounded quotes
// are rejected explicitly.
import { test, describe } from 'node:test';
import assert from 'node:assert';
import { fileURLToPath } from 'node:url';
import { IsolatedWorker } from '../src/isolatedWorker.mjs';
import { normalizeText } from '../src/textNormalization.mjs';
import { sanitizeText } from '../src/structuralSanitizer.mjs';

const TASK = fileURLToPath(new URL('../src/tasks/quoteExtractionTask.mjs', import.meta.url));

// Erratic whitespace (tabs, CRLF, double spaces, an ideographic space),
// mixed case, a ligature, and unsafe HTML/Markdown characters.
const RAW_SOURCE = [
  'Verbatim  grounding:\tthe   pipeline achieves　99.9% *exact* quote grounding',
  'across <all> tested corpora, and the ﬁnal LEDGER remains fully traceable.'
].join('\r\n');

const CANDIDATES = [
  {
    claimId: 'c-ws',
    statement: 'The pipeline grounds 99.9% of quotes exactly.',
    column: 'grounding-rate',
    quote: 'The   pipeline ACHIEVES 99.9%  *exact*   quote grounding'
  },
  {
    claimId: 'c-unsafe',
    statement: 'Coverage spans <all> corpora with a traceable ledger.',
    column: 'coverage',
    quote: 'across <ALL> tested corpora, and the final ledger remains fully traceable'
  },
  {
    claimId: 'c-fake',
    statement: 'Fabricated support.',
    column: 'coverage',
    quote: 'quantum blockchain synergy delivers infinite accuracy'
  }
];

describe('quoteExtractionTask inside an IsolatedWorker (Wave 3 done-when)', () => {
  test('grounds, sanitizes, and explicitly rejects — with live progress telemetry', async () => {
    const worker = new IsolatedWorker({
      taskModule: TASK,
      input: { paperId: 'P-001', sourceText: RAW_SOURCE, candidates: CANDIDATES }
    });
    const states = [];
    const progress = [];
    worker.on('state', (s) => states.push(s));
    worker.on('progress', (p) => progress.push(p));

    const result = await worker.run();

    assert.deepEqual(states, ['spawning', 'running', 'completed']);
    assert.deepEqual(progress.map((p) => p.completed), [1, 2, 3]);
    assert.equal(progress[2].fraction, 1);

    assert.equal(result.paperId, 'P-001');
    assert.deepEqual(result.stats, {
      candidates: 3,
      grounded: 2,
      rejected: 1,
      sourceLength: RAW_SOURCE.length,
      normalizedSourceLength: normalizeText(RAW_SOURCE).length
    });
    assert.deepEqual(result.quotes.map((q) => q.claimId), ['c-ws', 'c-unsafe']);

    // Strict exact-string matching against the normalized source, verified
    // INDEPENDENTLY from the offsets the worker returned: the raw span behind
    // every grounded quote re-normalizes to a verbatim substring of the
    // normalized source, and sanitizing it reproduces the worker's output.
    const normalizedSource = normalizeText(RAW_SOURCE);
    for (const q of result.quotes) {
      const rawSpan = RAW_SOURCE.slice(q.start, q.end);
      assert.ok(normalizedSource.includes(normalizeText(rawSpan)), `${q.claimId} must match the normalized source`);
      assert.equal(q.normalizedQuote, sanitizeText(normalizeText(rawSpan)));
      assert.equal(q.verbatimQuote, sanitizeText(rawSpan));
    }

    // Erratic whitespace/case in the candidate did not break grounding, and
    // the ligature in the raw source survived into the verbatim lineage.
    assert.ok(result.quotes[0].normalizedQuote.includes('achieves 99.9%'));
    assert.ok(result.quotes[1].verbatimQuote.includes('ﬁnal'));
    assert.ok(result.quotes[1].normalizedQuote.includes('final'));

    // Structural sanitization: no string anywhere in the result contains a
    // raw HTML/Markdown-active character (entity encodings only use & # ;).
    const strings = [];
    (function collect(v) {
      if (typeof v === 'string') strings.push(v);
      else if (Array.isArray(v)) v.forEach(collect);
      else if (v && typeof v === 'object') Object.entries(v).forEach(([k, x]) => { strings.push(k); collect(x); });
    })(result);
    assert.ok(strings.length > 10);
    for (const s of strings) {
      assert.doesNotMatch(s, /[<>"'`*_[\]|~\\{}=]|!\[/, `unsafe characters must be encoded: ${s}`);
    }
    // The unsafe fragments arrived, safely encoded.
    assert.ok(result.quotes[1].normalizedQuote.includes('&lt;all&gt;'));
    assert.ok(result.quotes[0].normalizedQuote.includes('&#42;exact&#42;'));

    // The fabricated quote is rejected EXPLICITLY — surfaced with a reason,
    // not silently dropped.
    assert.equal(result.rejected.length, 1);
    assert.equal(result.rejected[0].claimId, 'c-fake');
    assert.equal(result.rejected[0].reason, 'not-in-source');
    assert.match(result.rejected[0].rejection, /UNGROUNDED-QUOTE/);
  });

  test('a source with no candidates completes cleanly with empty partitions', async () => {
    const worker = new IsolatedWorker({
      taskModule: TASK,
      input: { paperId: 'P-002', sourceText: RAW_SOURCE, candidates: [] }
    });
    const result = await worker.run();
    assert.deepEqual(result.quotes, []);
    assert.deepEqual(result.rejected, []);
    assert.equal(result.stats.candidates, 0);
  });
});
