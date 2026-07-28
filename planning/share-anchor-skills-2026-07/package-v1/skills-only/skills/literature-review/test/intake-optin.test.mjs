// test/intake-optin.test.mjs — Wave 7: intake is STRICTLY opt-in.
//
// Brownfield CONTENT is the SOLE trigger for a Gandalf call. Pins the Wave-7
// acceptance: the Gandalf summarize adapter is called ZERO times when no content is
// provided — on the intent-only path, the seeds-only path, and the zero-input path —
// and the run proceeds with no intake cost; seeds NEVER trigger Gandalf intake (and
// never reach the summarize payload even when content IS present). A fail-fast budget
// decision at the intake door also blocks Gandalf entirely.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import { buildNormalizedView } from '../src/textNormalization.mjs';
import { groundQuote } from '../src/quoteExtractor.mjs';

const FIXTURES = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'adversarial-intake');
const GROUNDING = { buildNormalizedView, groundQuote };
const SEEDS = [
  { idType: 'doi', id: '10.1234/example.5678', title: 'A seed paper that must never be summarized' },
  { idType: 'arxiv', id: '2401.12345', title: 'Second seed, same rule' },
];
const INTENT = 'compare deduplication thresholds across pretraining corpora';

let ingestMod;
let summaryMod;

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  ingestMod = await import(new URL('ingest.mjs', indexUrl).href);
  summaryMod = await import(new URL('groundedSummary.mjs', indexUrl).href);
});

function summarizeSpy() {
  const spy = (payload) => {
    spy.calls.push(payload);
    return { sentences: [] };
  };
  spy.calls = [];
  return spy;
}

function assertNotInvoked(out, spy) {
  assert.equal(out.invoked, false);
  assert.equal(out.ok, true);
  assert.equal(out.summarizeCalls, 0);
  assert.equal(spy.calls.length, 0, 'the Gandalf summarize adapter was never called');
  // No intake cost: nothing summarized, nothing retained, nothing flagged.
  assert.equal(out.summary, '');
  assert.equal(out.summaryTokens, 0);
  assert.equal(out.sentences.length, 0);
  assert.equal(out.flagged.length, 0);
  assert.match(out.reason, /opt-in/);
  assert.match(out.reason, /SOLE trigger/);
}

describe('Wave 7 — intake opt-in: Gandalf is called zero times on every content-free path', () => {
  test('acceptance GWT: seeds + intent but NO content path -> summarize never invoked, run proceeds with no intake cost', async () => {
    // The full shared-module path: no roots declared -> ingest resolves no content…
    const ingest = ingestMod.ingestContent({ roots: [] });
    assert.equal(ingest.ok, true);
    assert.equal(ingest.decision, 'no-content');
    assert.equal(ingest.contentPresent, false);
    assert.equal(ingest.items.length, 0);
    assert.equal(ingestMod.hasBrownfieldContent(ingest), false);

    // …and the summary stage skips Gandalf even though seeds AND intent are present.
    const spy = summarizeSpy();
    const out = await summaryMod.groundedSummaryStage({
      items: ingest.items,
      seeds: SEEDS,
      intent: INTENT,
      summarize: spy,
      grounding: GROUNDING,
    });
    assertNotInvoked(out, spy);
  });

  test('intent-only: zero Gandalf calls', async () => {
    const spy = summarizeSpy();
    const out = await summaryMod.groundedSummaryStage({
      items: [],
      intent: INTENT,
      summarize: spy,
      grounding: GROUNDING,
    });
    assertNotInvoked(out, spy);
  });

  test('seeds-only: seeds NEVER trigger Gandalf intake', async () => {
    const spy = summarizeSpy();
    const out = await summaryMod.groundedSummaryStage({
      items: [],
      seeds: SEEDS,
      summarize: spy,
      grounding: GROUNDING,
    });
    assertNotInvoked(out, spy);
    assert.equal(summaryMod.shouldInvokeGandalf([]), false);
  });

  test('zero-input: no content, no seeds, no intent -> zero Gandalf calls; the skip needs no adapter at all', async () => {
    const spy = summarizeSpy();
    assertNotInvoked(await summaryMod.groundedSummaryStage({ summarize: spy, grounding: GROUNDING }), spy);
    // The content-free path does not even require summarize/grounding to be supplied —
    // the opt-in decision happens BEFORE any adapter validation, so a content-free run
    // truly costs nothing.
    const bare = await summaryMod.groundedSummaryStage({});
    assert.equal(bare.invoked, false);
    assert.equal(bare.summarizeCalls, 0);
  });

  test('a fail-fast budget decision at the intake door blocks Gandalf entirely', async () => {
    const ingest = ingestMod.ingestContent({ roots: [FIXTURES], budgetTokens: 1 });
    assert.equal(ingest.ok, false);
    assert.equal(ingest.decision, 'fail-fast');
    assert.equal(ingest.contentPresent, false);
    assert.equal(ingest.items.length, 0);
    assert.match(ingest.reason, /narrow your roots/);

    const spy = summarizeSpy();
    const out = await summaryMod.groundedSummaryStage({
      items: ingest.items,
      summarize: spy,
      grounding: GROUNDING,
    });
    assertNotInvoked(out, spy);
  });

  test('positive control: content present -> EXACTLY one Gandalf call, and seeds/intent never reach the payload', async () => {
    const ingest = ingestMod.ingestContent({ roots: [FIXTURES] });
    assert.equal(ingest.contentPresent, true);
    assert.equal(summaryMod.shouldInvokeGandalf(ingest.items), true);

    const spy = summarizeSpy();
    const out = await summaryMod.groundedSummaryStage({
      items: ingest.items,
      seeds: SEEDS,
      intent: INTENT,
      summarize: spy,
      grounding: GROUNDING,
    });
    assert.equal(out.invoked, true);
    assert.equal(out.summarizeCalls, 1);
    assert.equal(spy.calls.length, 1, 'at most one summarize call per stage');

    // Content is the sole trigger AND the sole payload: the seeds and the intent
    // string are structurally absent from what crosses the Gandalf boundary.
    const payloadText = JSON.stringify(spy.calls[0]);
    for (const seed of SEEDS) {
      assert.ok(!payloadText.includes(seed.title), 'seed titles never cross the Gandalf boundary');
      assert.ok(!payloadText.includes(seed.id), 'seed ids never cross the Gandalf boundary');
    }
    assert.ok(!payloadText.includes(INTENT), 'the intent string never crosses the Gandalf boundary');
    // What DOES cross is exactly the fenced item content.
    for (const item of ingest.items) {
      assert.ok(spy.calls[0].fencedContent.includes(`source=${item.sourceId} `));
    }
  });
});
