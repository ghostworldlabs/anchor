// test/derive-single-call-budget.test.mjs — Wave 8: exactly ONE bounded derive call,
// whole-context in one shot, budget-fitted by construction.
//
// Pins the Wave-8 acceptance: derivePlan makes exactly one derive LLM call (DISTINCT
// from Gandalf's summarize), the ENTIRE grounded summary plus the seed context cross
// in that single shot (no chunked/multi-pass derive), and the ACTUAL EMITTED payload
// fits by construction. The budget identity accounts for the per-source data-fencing
// framing introduced by Wave 6's trustBoundary.mjs (~FENCE_FRAMING_TOKENS per fenced
// block, scaling with the NUMBER of sources, not their size), reserves
// INTENT_CONTEXT_CAP for the fenced intent block the content route carries alongside
// the summary, and reserves DERIVE_OUTPUT_RESERVE (>= ceil(DERIVE_MAX_OUTPUT_CHARS /
// CHARS_PER_TOKEN)) for the derive call's OWN emission:
//   SUMMARY_MAX = DERIVE_CONTEXT - DERIVE_PROMPT_OVERHEAD - INTENT_CONTEXT_CAP
//                 - SEED_CONTEXT_CAP - DERIVE_OUTPUT_RESERVE
//                 - (FENCE_FRAMING_TOKENS * MAX_FENCED_BLOCKS)
// with MAX_FENCED_BLOCKS enforced as a HARD cap on source count at the budget gate
// AND on the seeds-only bootstrap route. The fit assertions here are on
// estimateTokensForText(payload.fencedContext) + DERIVE_OUTPUT_RESERVE — the bytes
// actually sent PLUS reserved output space — NOT on the bookkeeping total. An
// over-cap input FAILS at the door with ZERO derive calls (the budget gate never
// spends a call it cannot bound); a summary+intent that would overflow is caught
// BEFORE the Gandalf call, not at the derive door after it. A throwing adapter is a
// structured failure, never a retry.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';

const LOOSE_NOTES = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures',
  'adversarial-intake',
  'loose-notes',
);

let entryMod;
let deriveMod;
let budgetMod;
let validateMod;
let trustMod;

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  entryMod = await import(indexUrl.href);
  deriveMod = await import(new URL('derivePlan.mjs', indexUrl).href);
  budgetMod = await import(new URL('intakeBudget.mjs', indexUrl).href);
  validateMod = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
  trustMod = await import(new URL('trustBoundary.mjs', indexUrl).href);
});

const SEEDS = [
  { idType: 'doi', id: '10.1234/example.5678', title: 'A validated seed paper' },
  {
    idType: 'arxiv',
    id: '2401.12345',
    title: 'Second seed with an abstract',
    abstract: 'We study deduplication thresholds across pretraining corpora at scale.',
  },
];

/** A derive spy emitting a schema-valid artifact anchored to the first grounded source.
 *  The anchor quotes a BOUNDED token-aligned span (a huge grounded text quoted whole
 *  would blow the derive OUTPUT budget — the emission must stay within caps too). The
 *  emission copies the validated seed identities EXACTLY (seed-identity reconciliation
 *  is a hard gate: artifact.seeds must equal the validated set as an (idType,id)
 *  multiset). */
function deriveSpy(seeds = []) {
  const spy = (payload) => {
    spy.calls.push(payload);
    const [sourceId, text] = Object.entries(payload.groundedSources)[0];
    const quote = text.length > 200 ? text.slice(0, text.lastIndexOf(' ', 200)).trim() : text;
    const anchors = [{ sourceId, quote }];
    return {
      artifactVersion: 'plan-artifact/1',
      scope: { statement: 'Derived scope statement.', axis: 'Derived AXIS.', anchors },
      branches: [{ question: 'Derived question?', rationale: 'Derived rationale.', anchors }],
      sourcesToBeat: [{ title: 'Derived source to beat', why: 'Derived why.', anchors }],
      foresight: {
        dropped: 'nothing dropped',
        counterfactualCost: 'no cost',
        stamp: 'no foresight value added',
        anchors,
      },
      seeds: seeds.map(({ idType, id, title }) => ({ idType, id, title })),
    };
  };
  spy.calls = [];
  return spy;
}

describe('Wave 8 — derive: single bounded call, whole summary one shot, budget by construction', () => {
  test('the derive-context arithmetic is pinned: SUMMARY_MAX + prompt overhead + intent cap + seed cap + output reserve + fence-framing term fill DERIVE_CONTEXT exactly', () => {
    const {
      DERIVE_CONTEXT,
      DERIVE_PROMPT_OVERHEAD,
      INTENT_CONTEXT_CAP,
      SEED_CONTEXT_CAP,
      DERIVE_OUTPUT_RESERVE,
      DERIVE_MAX_OUTPUT_CHARS,
      CHARS_PER_TOKEN,
      FENCE_FRAMING_TOKENS,
      MAX_FENCED_BLOCKS,
      SUMMARY_MAX,
    } = budgetMod;
    // The identity accounts for the per-source data-fencing framing (Wave 6
    // trustBoundary.mjs), which scales with the NUMBER of sources, not their size;
    // reserves INTENT_CONTEXT_CAP for the content route's fenced intent block; and
    // reserves DERIVE_OUTPUT_RESERVE for the derive call's OWN emission.
    assert.equal(
      SUMMARY_MAX,
      DERIVE_CONTEXT -
        DERIVE_PROMPT_OVERHEAD -
        INTENT_CONTEXT_CAP -
        SEED_CONTEXT_CAP -
        DERIVE_OUTPUT_RESERVE -
        FENCE_FRAMING_TOKENS * MAX_FENCED_BLOCKS,
    );
    assert.ok(SUMMARY_MAX > 0);
    assert.ok(INTENT_CONTEXT_CAP > 0);
    assert.ok(FENCE_FRAMING_TOKENS > 0);
    assert.ok(Number.isInteger(MAX_FENCED_BLOCKS) && MAX_FENCED_BLOCKS > 0);
    // The output reserve covers an emission at the output char cap: the input never
    // consumes the whole window and the emission always has room.
    assert.ok(DERIVE_OUTPUT_RESERVE >= Math.ceil(DERIVE_MAX_OUTPUT_CHARS / CHARS_PER_TOKEN));
    assert.equal(deriveMod.DERIVE_MAX_OUTPUT_CHARS, DERIVE_MAX_OUTPUT_CHARS);
    // A context built at the caps fits the one call by construction.
    assert.equal(
      SUMMARY_MAX +
        DERIVE_PROMPT_OVERHEAD +
        INTENT_CONTEXT_CAP +
        SEED_CONTEXT_CAP +
        DERIVE_OUTPUT_RESERVE +
        FENCE_FRAMING_TOKENS * MAX_FENCED_BLOCKS,
      DERIVE_CONTEXT,
    );
    // The pinned constant is a faithful NOMINAL of the actual trust-boundary framing
    // (~168 tokens per block; the exact figure varies a few tokens with sourceId
    // length and ceil rounding). The HARD guarantee is the actual-payload gate on
    // estimateTokensForText(payload.fencedContext), tested below — never this nominal.
    const text = 'measured framing block';
    const { framed } = trustMod.fenceUntrustedData({ sourceId: 'grounded-summary', text });
    const framingTokens =
      budgetMod.estimateTokensForText(framed) - budgetMod.estimateTokensForText(text);
    assert.ok(
      Math.abs(framingTokens - FENCE_FRAMING_TOKENS) <= 8,
      `measured per-block framing (${framingTokens} tokens) is not within 8 tokens of the ` +
        `pinned FENCE_FRAMING_TOKENS nominal (${FENCE_FRAMING_TOKENS})`,
    );
  });

  test('acceptance GWT: a summary at SUMMARY_MAX plus seed context within SEED_CONTEXT_CAP -> exactly ONE call, whole summary + seed context in that one shot, schema-valid anchored artifact', async () => {
    const { SUMMARY_MAX, CHARS_PER_TOKEN, DERIVE_CONTEXT } = budgetMod;
    // Exactly SUMMARY_MAX estimated tokens of whitespace-separated text.
    const summary = 'lorem ipsum '
      .repeat(Math.ceil((SUMMARY_MAX * CHARS_PER_TOKEN) / 12))
      .slice(0, SUMMARY_MAX * CHARS_PER_TOKEN);
    assert.equal(budgetMod.estimateTokensForText(summary), SUMMARY_MAX);

    const spy = deriveSpy(SEEDS);
    const res = await deriveMod.derivePlan({ summary, seeds: SEEDS, derive: spy });

    assert.equal(res.ok, true, res.reason);
    assert.equal(res.deriveCalls, 1);
    assert.equal(spy.calls.length, 1, 'exactly one derive call — no chunked/multi-pass derive');

    // The WHOLE summary crossed in the single payload (one shot, uncut)…
    const payload = spy.calls[0];
    assert.equal(payload.groundedSources[deriveMod.SUMMARY_SOURCE_ID], summary);
    assert.ok(payload.fencedContext.includes(summary), 'the entire summary is in the one fenced payload');
    // …and so did every seed's context (metadata + abstract), each as its own fenced block.
    for (const seed of SEEDS) {
      const sid = deriveMod.seedSourceId(seed);
      assert.equal(payload.groundedSources[sid], deriveMod.seedContextText(seed));
      assert.ok(payload.fencedContext.includes(deriveMod.seedContextText(seed)));
    }

    // Fit by construction, asserted on the ACTUAL EMITTED payload — the bytes actually
    // sent (grounded text + seed text + ALL per-source fence framing) PLUS the window
    // space reserved for the derive call's OWN emission, NOT the bookkeeping total.
    const actualFencedTokens = budgetMod.estimateTokensForText(payload.fencedContext);
    assert.ok(
      actualFencedTokens + budgetMod.DERIVE_OUTPUT_RESERVE <= DERIVE_CONTEXT,
      `the ACTUAL fenced payload (${actualFencedTokens} tokens) + DERIVE_OUTPUT_RESERVE must fit DERIVE_CONTEXT`,
    );
    // …and it still fits with the prompt overhead counted too (the stronger gate the
    // implementation enforces).
    assert.ok(
      actualFencedTokens + budgetMod.DERIVE_PROMPT_OVERHEAD + budgetMod.DERIVE_OUTPUT_RESERVE <=
        DERIVE_CONTEXT,
    );
    // The bookkeeping total is consistent too — but it is not the fit assertion.
    const context = deriveMod.buildDeriveContext({ summary, seeds: SEEDS });
    assert.equal(
      context.tokens.total,
      context.tokens.grounded + context.tokens.seedContext + budgetMod.DERIVE_PROMPT_OVERHEAD,
    );
    assert.equal(context.tokens.fenced, actualFencedTokens);
    assert.equal(payload.budget.deriveContext, DERIVE_CONTEXT);
    assert.equal(payload.budget.intentContextCap, budgetMod.INTENT_CONTEXT_CAP);
    assert.equal(payload.budget.deriveOutputReserve, budgetMod.DERIVE_OUTPUT_RESERVE);
    assert.equal(payload.budget.fenceFramingTokens, budgetMod.FENCE_FRAMING_TOKENS);
    assert.equal(payload.budget.maxFencedBlocks, budgetMod.MAX_FENCED_BLOCKS);

    // The emitted artifact validates and every element carries a model-authored anchor.
    const check = validateMod.validatePlanArtifact(res.artifact);
    assert.equal(check.ok, true, JSON.stringify(check.reasons));
    assert.ok(res.artifact.scope.anchors.length >= 1);
  });

  test('an over-SUMMARY_MAX grounded context FAILS at the door: zero derive calls spent', async () => {
    const { SUMMARY_MAX, CHARS_PER_TOKEN } = budgetMod;
    const summary = 'x '.repeat(((SUMMARY_MAX + 1) * CHARS_PER_TOKEN) / 2);
    assert.ok(budgetMod.estimateTokensForText(summary) > SUMMARY_MAX);

    const spy = deriveSpy();
    const res = await deriveMod.derivePlan({ summary, seeds: SEEDS, derive: spy });
    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 0);
    assert.equal(spy.calls.length, 0, 'the bounded call was never invoked');
    assert.equal(res.artifact, null);
    assert.match(res.reason, /SUMMARY_MAX/);
    assert.equal(res.stamp, deriveMod.DERIVE_FAIL_STAMP);
  });

  test('over-cap seed context FAILS at the door: zero derive calls spent', async () => {
    const { SEED_CONTEXT_CAP, CHARS_PER_TOKEN } = budgetMod;
    const bigSeed = {
      idType: 'doi',
      id: '10.9999/huge.abstract',
      title: 'Seed with an abstract too large for the cap',
      abstract: 'w '.repeat(((SEED_CONTEXT_CAP + 1) * CHARS_PER_TOKEN) / 2),
    };
    const spy = deriveSpy();
    const res = await deriveMod.derivePlan({ summary: 'a short grounded summary.', seeds: [bigSeed], derive: spy });
    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 0);
    assert.equal(spy.calls.length, 0);
    assert.equal(res.artifact, null);
    assert.match(res.reason, /SEED_CONTEXT_CAP/);
  });

  test('acceptance GWT: within SUMMARY_MAX/SEED_CONTEXT_CAP by the OLD flat identity, but fence framing pushes the ACTUAL payload over DERIVE_CONTEXT -> rejected with ZERO calls', async () => {
    const {
      SUMMARY_MAX,
      SEED_CONTEXT_CAP,
      DERIVE_PROMPT_OVERHEAD,
      DERIVE_OUTPUT_RESERVE,
      DERIVE_CONTEXT,
      CHARS_PER_TOKEN,
      MAX_FENCED_BLOCKS,
    } = budgetMod;
    // A summary at exactly SUMMARY_MAX…
    const summary = 'lorem ipsum '
      .repeat(Math.ceil((SUMMARY_MAX * CHARS_PER_TOKEN) / 12))
      .slice(0, SUMMARY_MAX * CHARS_PER_TOKEN);
    assert.equal(budgetMod.estimateTokensForText(summary), SUMMARY_MAX);
    // …plus seeds whose LONG identifiers keep the seed-context bookkeeping under
    // SEED_CONTEXT_CAP while their per-block data-fencing framing (which the OLD flat
    // identity ignored — it scales with the NUMBER of sources, and each marker carries
    // the sourceId) pushes the ACTUAL emitted payload over DERIVE_CONTEXT once the
    // output reserve is counted.
    const seeds = Array.from({ length: MAX_FENCED_BLOCKS - 2 }, (_, i) => ({
      idType: 'doi',
      id: `10.9999/${'x'.repeat(1300)}.${i}`,
      title: `Long-identifier seed #${i}`,
    }));

    const context = deriveMod.buildDeriveContext({ summary, seeds });
    // Every nominal cap passes — the OLD flat identity would have let this through…
    assert.ok(context.tokens.summary <= SUMMARY_MAX);
    assert.ok(context.tokens.seedContext <= SEED_CONTEXT_CAP);
    assert.ok(context.tokens.fencedBlocks <= MAX_FENCED_BLOCKS);
    assert.ok(
      context.tokens.total + DERIVE_OUTPUT_RESERVE <= DERIVE_CONTEXT,
      'the flat bookkeeping total (grounded + seed + overhead + reserve) claims a fit',
    );
    // …but the bytes ACTUALLY sent (plus the reserved output space) do not fit.
    assert.ok(
      context.tokens.fenced + DERIVE_PROMPT_OVERHEAD + DERIVE_OUTPUT_RESERVE > DERIVE_CONTEXT,
      'the actual fenced payload + output reserve must exceed DERIVE_CONTEXT for this fixture',
    );

    const spy = deriveSpy(seeds);
    const res = await deriveMod.derivePlan({ summary, seeds, derive: spy });
    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 0);
    assert.equal(spy.calls.length, 0, 'the unfittable call is never spent');
    assert.equal(res.artifact, null);
    assert.match(res.reason, /DERIVE_CONTEXT/);
    assert.match(res.reason, /fenc/i);
  });

  test('MAX_FENCED_BLOCKS is a HARD cap on source count: one block too many FAILS at the door with ZERO calls', async () => {
    const { MAX_FENCED_BLOCKS } = budgetMod;
    const seeds = Array.from({ length: MAX_FENCED_BLOCKS + 1 }, (_, i) => ({
      idType: 'pmid',
      id: `${10000000 + i}`,
      title: `Tiny seed #${i}`,
    }));
    const spy = deriveSpy(seeds);
    const res = await deriveMod.derivePlan({ seeds, derive: spy });
    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 0);
    assert.equal(spy.calls.length, 0);
    assert.equal(res.artifact, null);
    assert.match(res.reason, /MAX_FENCED_BLOCKS/);
    assert.match(res.reason, /hard source-count cap/);
  });

  test('an empty context (no summary, no intent, no seeds) never spends the call', async () => {
    const spy = deriveSpy();
    const res = await deriveMod.derivePlan({ derive: spy });
    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 0);
    assert.equal(spy.calls.length, 0);
    assert.match(res.reason, /nothing to derive from/);
  });

  test('a throwing adapter is a structured failure — one call, NEVER a retry', async () => {
    const spy = (payload) => {
      spy.calls.push(payload);
      throw new Error('adapter exploded');
    };
    spy.calls = [];
    const res = await deriveMod.derivePlan({ summary: 'a short grounded summary.', derive: spy });
    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 1);
    assert.equal(spy.calls.length, 1, 'the failed call is never retried');
    assert.equal(res.artifact, null);
    assert.match(res.reason, /adapter exploded/);
  });

  test('the intent rides in its own reserved slot: an in-cap intent-only context derives normally', async () => {
    const spy = deriveSpy(SEEDS);
    const intent = 'compare deduplication thresholds across pretraining corpora';
    const res = await deriveMod.derivePlan({ intent, seeds: SEEDS, derive: spy });
    assert.equal(res.ok, true, res.reason);
    assert.equal(spy.calls.length, 1);
    assert.equal(spy.calls[0].groundedSources[deriveMod.INTENT_SOURCE_ID], intent);
    assert.equal(deriveMod.SUMMARY_SOURCE_ID in spy.calls[0].groundedSources, false);
  });

  test('an over-INTENT_CONTEXT_CAP intent FAILS at the derive door: zero derive calls spent', async () => {
    const { INTENT_CONTEXT_CAP, CHARS_PER_TOKEN } = budgetMod;
    const intent = 'x '.repeat(((INTENT_CONTEXT_CAP + 1) * CHARS_PER_TOKEN) / 2);
    assert.ok(budgetMod.estimateTokensForText(intent) > INTENT_CONTEXT_CAP);

    const spy = deriveSpy(SEEDS);
    const res = await deriveMod.derivePlan({ intent, seeds: SEEDS, derive: spy });
    assert.equal(res.ok, false);
    assert.equal(res.deriveCalls, 0);
    assert.equal(spy.calls.length, 0, 'the bounded call was never invoked');
    assert.equal(res.artifact, null);
    assert.match(res.reason, /INTENT_CONTEXT_CAP/);
  });

  test('acceptance GWT: a Wave-7-legal summary at SUMMARY_MAX WITH an intent at INTENT_CONTEXT_CAP -> one call, and the ACTUAL payload + DERIVE_OUTPUT_RESERVE fits DERIVE_CONTEXT', async () => {
    const { SUMMARY_MAX, INTENT_CONTEXT_CAP, DERIVE_OUTPUT_RESERVE, DERIVE_CONTEXT, CHARS_PER_TOKEN } =
      budgetMod;
    const summary = 'lorem ipsum '
      .repeat(Math.ceil((SUMMARY_MAX * CHARS_PER_TOKEN) / 12))
      .slice(0, SUMMARY_MAX * CHARS_PER_TOKEN);
    assert.equal(budgetMod.estimateTokensForText(summary), SUMMARY_MAX);
    const intent = 'x '.repeat((INTENT_CONTEXT_CAP * CHARS_PER_TOKEN) / 2);
    assert.equal(budgetMod.estimateTokensForText(intent), INTENT_CONTEXT_CAP);

    const spy = deriveSpy(SEEDS);
    const res = await deriveMod.derivePlan({ summary, intent, seeds: SEEDS, derive: spy });
    assert.equal(res.ok, true, res.reason);
    assert.equal(spy.calls.length, 1);

    // SUMMARY_MAX reserved INTENT_CONTEXT_CAP for the fenced intent block AND
    // DERIVE_OUTPUT_RESERVE for the emission, so the input never consumes the whole
    // window: the plan-pinned fit inequality holds on the ACTUAL emitted payload.
    const payload = spy.calls[0];
    assert.ok(payload.fencedContext.includes(summary));
    assert.ok(payload.fencedContext.includes(intent));
    const actualFencedTokens = budgetMod.estimateTokensForText(payload.fencedContext);
    assert.ok(
      actualFencedTokens + DERIVE_OUTPUT_RESERVE <= DERIVE_CONTEXT,
      `estimateTokensForText(payload.fencedContext) (${actualFencedTokens}) + ` +
        `DERIVE_OUTPUT_RESERVE (${DERIVE_OUTPUT_RESERVE}) must fit DERIVE_CONTEXT (${DERIVE_CONTEXT})`,
    );
  });

  test('acceptance GWT: a summary+intent that would overflow is caught BEFORE the Gandalf call, not at the derive door after it', async () => {
    const { INTENT_CONTEXT_CAP, CHARS_PER_TOKEN } = budgetMod;
    const intent = 'x '.repeat(((INTENT_CONTEXT_CAP + 1) * CHARS_PER_TOKEN) / 2);
    assert.ok(budgetMod.estimateTokensForText(intent) > INTENT_CONTEXT_CAP);

    const summarize = (payload) => {
      summarize.calls.push(payload);
      return { sentences: [] };
    };
    summarize.calls = [];
    const derive = deriveSpy(SEEDS);
    const res = await entryMod.brownfieldIntake({
      roots: [LOOSE_NOTES],
      intent,
      seeds: SEEDS,
      summarize,
      derive,
    });

    assert.equal(res.ok, false);
    assert.equal(res.route, entryMod.INTAKE_ROUTES.CONTENT);
    assert.equal(res.gandalfCalls, 0);
    assert.equal(summarize.calls.length, 0, 'the Gandalf summarize call was never spent');
    assert.equal(res.deriveCalls, 0);
    assert.equal(derive.calls.length, 0);
    assert.equal(res.artifact, null);
    assert.match(res.reason, /INTENT_CONTEXT_CAP/);
    assert.match(res.reason, /BEFORE the Gandalf/);
  });

  test('MAX_FENCED_BLOCKS gates the seeds-only bootstrap route too: an over-cap seed set yields NO bootstrap plan', async () => {
    const { MAX_FENCED_BLOCKS } = budgetMod;
    const seeds = Array.from({ length: MAX_FENCED_BLOCKS + 1 }, (_, i) => ({
      idType: 'pmid',
      id: `${10000000 + i}`,
      title: `Tiny seed #${i}`,
    }));

    // Directly on the deterministic bootstrap producer…
    const direct = deriveMod.bootstrapSeedPlan(seeds);
    assert.equal(direct.ok, false);
    assert.equal(direct.deriveCalls, 0);
    assert.equal(direct.artifact, null);
    assert.match(direct.reason, /MAX_FENCED_BLOCKS/);

    // …and end-to-end through the module entry's seeds-only route: zero LLM calls of
    // any kind, no artifact, the stamped reason surfaced.
    const summarize = (payload) => {
      summarize.calls.push(payload);
      return { sentences: [] };
    };
    summarize.calls = [];
    const derive = deriveSpy(seeds);
    const res = await entryMod.brownfieldIntake({ seeds, summarize, derive });
    assert.equal(res.ok, false);
    assert.equal(res.route, entryMod.INTAKE_ROUTES.SEEDS_ONLY);
    assert.equal(res.gandalfCalls, 0);
    assert.equal(res.deriveCalls, 0);
    assert.equal(summarize.calls.length, 0);
    assert.equal(derive.calls.length, 0);
    assert.equal(res.artifact, null);
    assert.match(res.reason, /MAX_FENCED_BLOCKS/);
  });
});
