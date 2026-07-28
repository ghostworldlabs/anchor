// test/grounded-summary-zero-fabrication.test.mjs — Wave 7: ZERO-fabrication pass over
// the adversarial intake corpus (test/fixtures/adversarial-intake/ — loose notes,
// half-finished drafts, a mixed folder dump).
//
// Pins the Wave-7 acceptance: ingest emits per-item provenance (stable source id +
// span offsets threaded intake -> summary); the Gandalf summary is quote-checked PER
// SOURCE FILE by literature-review's EXISTING quote-grounding modules
// (src/quoteExtractor.mjs + src/textNormalization.mjs + src/structuralSanitizer.mjs,
// INJECTED — the shared module never imports a skill's src/); every RETAINED sentence
// carries a verbatim anchor into a NAMED source file; every sentence without such a
// span is dropped AND flagged with a named reason; no sentence introduces content
// absent from the sources; and the retained summary is bounded by SUMMARY_MAX.
//
// The summarize adapter here is an ADVERSARIAL mock: alongside honest grounded
// sentences it emits a fabricated sentence citing the unknown "source X" the corpus's
// embedded injection tries to smuggle in, a paraphrased (non-verbatim) quote, a
// cross-wired quote citing the wrong source file, a sub-minimum quote, and an
// anchor-free sentence. Zero fabrication means exactly the honest sentences survive.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import { buildNormalizedView, normalizeText } from '../src/textNormalization.mjs';
import { groundQuote } from '../src/quoteExtractor.mjs';
import { sanitizeText } from '../src/structuralSanitizer.mjs';

const FIXTURES = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'adversarial-intake');
const GROUNDING = { buildNormalizedView, groundQuote, sanitizeText };

let ingestMod; // trio-shared/brownfield-intake/ingest.mjs
let summaryMod; // trio-shared/brownfield-intake/groundedSummary.mjs
let budgetMod; // trio-shared/brownfield-intake/intakeBudget.mjs
let tbMod; // trio-shared/brownfield-intake/trustBoundary.mjs

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  ingestMod = await import(new URL('ingest.mjs', indexUrl).href);
  summaryMod = await import(new URL('groundedSummary.mjs', indexUrl).href);
  budgetMod = await import(new URL('intakeBudget.mjs', indexUrl).href);
  tbMod = await import(new URL('trustBoundary.mjs', indexUrl).href);
});

function ingestCorpus(extra = {}) {
  return ingestMod.ingestContent({ roots: [FIXTURES], ...extra });
}

function itemByPath(result, relPath) {
  const item = result.items.find((i) => i.path === relPath);
  assert.ok(item, `expected ingested item for ${relPath}`);
  return item;
}

// The adversarial sentence set, built against the ACTUAL ingested item texts so the
// honest quotes are verbatim by construction and every dishonest one fails for the
// exact named reason.
function adversarialSentences(result) {
  const notes = itemByPath(result, 'loose-notes/scaling-notes.md');
  const abstract = itemByPath(result, 'mixed-dump/paper-abstract.txt');
  return {
    honest: [
      {
        text: 'The team observed that held-out perplexity improved with data quality filtering.',
        sourceId: notes.sourceId,
        quote: 'the held-out perplexity improved monotonically with data quality filtering',
      },
      {
        text: 'Aggressive *near-duplicate* removal improved zero-shot transfer in the abstract.',
        sourceId: abstract.sourceId,
        quote: 'aggressive near-duplicate removal improves\nzero-shot transfer by 3.1 points on average',
      },
    ],
    fabricated: {
      // The corpus's embedded injection says "add source X" — an honoring summarizer
      // would emit exactly this. It must be flagged unknown-source and dropped.
      text: 'Source X establishes that the moon dataset proves accuracy is 99%.',
      sourceId: 'source X',
      quote: 'the moon dataset proves accuracy is 99%',
    },
    paraphrase: {
      text: 'Deduplication strongly improves all benchmarks in every regime.',
      sourceId: abstract.sourceId,
      quote: 'deduplication strongly improves all benchmarks always',
    },
    wrongSource: {
      text: 'The abstract says the eval harness was frozen before the ablation.',
      sourceId: abstract.sourceId, // quote actually lives in mixed-dump/meeting-notes.md
      quote: 'freeze the eval harness before the next data ablation',
    },
    tooShort: {
      text: 'The similarity threshold was 0.92 according to the abstract.',
      sourceId: abstract.sourceId,
      quote: '0.92',
    },
    anchorFree: {
      text: 'The team should immediately trust these findings without any source.',
    },
  };
}

describe('Wave 7 — grounded summary: zero fabrication over the adversarial corpus', () => {
  test('ingest emits deterministic per-item provenance for the whole corpus', () => {
    const result = ingestCorpus();
    assert.equal(result.ok, true);
    assert.equal(result.decision, 'within-budget');
    assert.equal(result.contentPresent, true);
    assert.equal(ingestMod.hasBrownfieldContent(result), true);
    assert.deepEqual(
      result.items.map((i) => i.path),
      [
        'drafts/intro-draft.md',
        'loose-notes/reading-list.txt',
        'loose-notes/scaling-notes.md',
        'mixed-dump/meeting-notes.md',
        'mixed-dump/paper-abstract.txt',
      ],
      'deterministic root-then-path order over the mixed folder dump',
    );
    for (const item of result.items) {
      assert.equal(item.sourceId, `r0/${item.path}`, 'stable source id');
      assert.ok(fs.existsSync(item.realPath), 'provenance realPath resolves');
      assert.equal(fs.readFileSync(item.realPath, 'utf8'), item.text, 'kept text is the file bytes');
      assert.deepEqual(item.span, { start: 0, end: item.text.length });
      assert.equal(item.headOnly, false);
      assert.ok(ingestMod.ITEM_KINDS.includes(item.kind));
    }
    // Advisory kind spread across the corpus shapes (note/draft/paper all present).
    assert.equal(itemByPath(result, 'drafts/intro-draft.md').kind, 'draft');
    assert.equal(itemByPath(result, 'loose-notes/scaling-notes.md').kind, 'note');
    assert.equal(itemByPath(result, 'mixed-dump/paper-abstract.txt').kind, 'paper');
  });

  test('acceptance GWT: every retained sentence maps to a verbatim span in a named source file; every unanchored sentence is dropped AND flagged; nothing fabricated survives', async () => {
    const result = ingestCorpus();
    const s = adversarialSentences(result);
    const emitted = [
      s.honest[0],
      s.fabricated,
      s.paraphrase,
      s.honest[1],
      s.wrongSource,
      s.tooShort,
      s.anchorFree,
      'bare string, not a sentence object', // malformed candidate
    ];

    let payloadSeen = null;
    const summarize = (payload) => {
      payloadSeen = payload;
      return { sentences: emitted };
    };

    const out = await summaryMod.groundedSummaryStage({
      items: result.items,
      summarize,
      grounding: GROUNDING,
    });

    assert.equal(out.invoked, true);
    assert.equal(out.ok, true);
    assert.equal(out.summarizeCalls, 1);

    // RETAINED = exactly the honest sentences, in emitted order.
    assert.deepEqual(
      out.sentences.map((x) => x.text),
      [s.honest[0].text, s.honest[1].text],
    );
    for (const sentence of out.sentences) {
      assert.ok(sentence.anchors.length >= 1, 'every retained sentence carries an anchor');
      for (const anchor of sentence.anchors) {
        const item = result.items.find((i) => i.sourceId === anchor.sourceId);
        assert.ok(item, `anchor names an ingested source (${anchor.sourceId})`);
        assert.equal(anchor.path, item.path, 'anchor names the source FILE');
        // The verbatim span really is a slice of the item's kept text…
        assert.equal(item.text.slice(anchor.start, anchor.end), anchor.verbatimQuote);
        // …and of the named source file's actual bytes (intake -> summary thread).
        const fileBytes = fs.readFileSync(item.realPath, 'utf8');
        assert.equal(
          fileBytes.slice(anchor.spanInFile.start, anchor.spanInFile.end),
          anchor.verbatimQuote,
          'spanInFile offsets recover the identical span from the raw file',
        );
        // The grounding really is the existing normalized exact-match discipline.
        assert.equal(normalizeText(anchor.verbatimQuote), anchor.normalizedQuote);
      }
    }

    // DROPPED sentences are all flagged, each with its named reason.
    const R = summaryMod.UNANCHORED_REASONS;
    const flaggedByText = new Map(out.flagged.map((f) => [f.text, f]));
    const expectFlag = (text, reason) => {
      const f = flaggedByText.get(text);
      assert.ok(f, `expected a flag for: ${text}`);
      assert.equal(f.dropped, true);
      assert.ok(
        f.reasons.some((r) => r.reason === reason),
        `expected reason ${reason}, got ${JSON.stringify(f.reasons)}`,
      );
    };
    expectFlag(s.fabricated.text, R.UNKNOWN_SOURCE);
    expectFlag(s.paraphrase.text, R.NOT_VERBATIM);
    expectFlag(s.wrongSource.text, R.NOT_VERBATIM);
    expectFlag(s.tooShort.text, R.QUOTE_TOO_SHORT);
    expectFlag(s.anchorFree.text, R.NO_ANCHOR);
    assert.ok(
      out.flagged.some((f) => f.reasons.some((r) => r.reason === R.MALFORMED)),
      'the malformed candidate is flagged too',
    );

    // Zero fabrication: the summary is exactly the retained honest text — the embedded
    // injection's "source X" claim appears nowhere in it.
    assert.equal(out.summary, `${s.honest[0].text} ${s.honest[1].text}`);
    assert.ok(!out.summary.includes('source X') && !out.summary.toLowerCase().includes('moon'));
    assert.ok(out.summaryTokens <= budgetMod.SUMMARY_MAX);

    // The Gandalf boundary payload fenced EVERY source as hash-bound untrusted data,
    // and the instruction plane contains none of the corpus bytes (the embedded
    // "IGNORE PRIOR INSTRUCTIONS" line never reaches the instruction plane).
    for (const item of result.items) {
      assert.ok(
        payloadSeen.fencedContent.includes(`<<<UNTRUSTED-DATA source=${item.sourceId} sha256=`),
        `fence opens for ${item.sourceId}`,
      );
      assert.ok(payloadSeen.fencedContent.includes(item.text), 'bytes are inside the payload verbatim');
    }
    const instructionPlane = tbMod.instructionPlaneView(payloadSeen.fencedContent);
    assert.ok(!instructionPlane.includes('IGNORE PRIOR INSTRUCTIONS'));
    assert.ok(!instructionPlane.includes('add source X'));
  });

  test('sanitizer (src/structuralSanitizer.mjs) is applied to display text AFTER grounding, raw spans untouched', async () => {
    const result = ingestCorpus();
    const s = adversarialSentences(result);
    const out = await summaryMod.groundedSummaryStage({
      items: result.items,
      summarize: () => ({ sentences: [s.honest[1]] }),
      grounding: GROUNDING,
    });
    const [sentence] = out.sentences;
    assert.ok(sentence, 'the honest sentence is retained');
    // The sentence text carries markdown-active characters; displayText is the
    // entity-encoded form and the raw text/anchor spans stay byte-exact.
    assert.equal(sentence.displayText, sanitizeText(sentence.text));
    assert.notEqual(sentence.displayText, sentence.text);
    assert.equal(sentence.anchors[0].displayQuote, sanitizeText(sentence.anchors[0].verbatimQuote));
    const item = itemByPath(result, 'mixed-dump/paper-abstract.txt');
    assert.equal(item.text.slice(sentence.anchors[0].start, sentence.anchors[0].end), sentence.anchors[0].verbatimQuote);
  });

  test('acceptance GWT: ingested set just under budget -> summary bounded by SUMMARY_MAX with provenance threaded from each source item', async () => {
    const probe = ingestCorpus();
    // Re-run with the budget JUST above the estimate: still within-budget, untruncated.
    const result = ingestCorpus({ budgetTokens: probe.estimatedTokens + 1 });
    assert.equal(result.decision, 'within-budget');
    assert.equal(result.truncated, false);

    const s = adversarialSentences(result);
    const out = await summaryMod.groundedSummaryStage({
      items: result.items,
      summarize: () => ({ sentences: s.honest }),
      grounding: GROUNDING,
    });
    assert.equal(out.ok, true);
    assert.ok(out.summaryTokens <= budgetMod.SUMMARY_MAX);
    assert.equal(out.summaryMaxTokens, budgetMod.SUMMARY_MAX);
    // Provenance is threaded per source item, and every anchor resolves into it.
    assert.deepEqual(
      out.provenance.map((p) => p.sourceId),
      result.items.map((i) => i.sourceId),
    );
    for (const sentence of out.sentences) {
      for (const anchor of sentence.anchors) {
        assert.ok(out.provenance.some((p) => p.sourceId === anchor.sourceId && p.path === anchor.path));
      }
    }
  });

  test('the summary bound is enforced deterministically in emitted order (over-cap sentences flagged, never silently kept)', async () => {
    const result = ingestCorpus();
    const s = adversarialSentences(result);
    const firstTokens = budgetMod.estimateTokensForText(s.honest[0].text);
    const out = await summaryMod.groundedSummaryStage({
      items: result.items,
      summarize: () => ({ sentences: s.honest }),
      grounding: GROUNDING,
      summaryMaxTokens: firstTokens, // room for exactly the first honest sentence
    });
    assert.deepEqual(out.sentences.map((x) => x.text), [s.honest[0].text]);
    assert.equal(out.summaryTokens, firstTokens);
    const flag = out.flagged.find((f) => f.text === s.honest[1].text);
    assert.ok(flag, 'the over-cap sentence is flagged');
    assert.equal(flag.reasons[0].reason, summaryMod.UNANCHORED_REASONS.SUMMARY_BUDGET);
  });

  test('a summarize adapter failure yields zero retained sentences — zero fabrication holds trivially; the call is never retried', async () => {
    const result = ingestCorpus();
    let calls = 0;
    const out = await summaryMod.groundedSummaryStage({
      items: result.items,
      summarize: () => {
        calls += 1;
        throw new Error('gandalf unavailable');
      },
      grounding: GROUNDING,
    });
    assert.equal(calls, 1);
    assert.equal(out.invoked, true);
    assert.equal(out.ok, false);
    assert.equal(out.summarizeCalls, 1);
    assert.equal(out.summary, '');
    assert.equal(out.sentences.length, 0);
    assert.equal(out.flagged[0].reasons[0].reason, summaryMod.UNANCHORED_REASONS.SUMMARIZE_FAILED);
  });
});
