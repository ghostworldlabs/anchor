// test/derive-routing.test.mjs — Wave 8: the four input routes through the shared
// module's REAL end-to-end entry (brownfieldIntake).
//
// Pins the acceptance GWT: content derives from the grounded summary (ONE Gandalf
// call + ONE derive call); intent-only derives from the fenced intent with ZERO
// Gandalf calls; seeds-only bootstraps a trivial default plan deterministically with
// ZERO LLM calls of any kind and proceeds; and the zero-input run fails fast asking
// for content, intent, or seeds. A fail-fast budget decision at the intake door also
// stops everything before any call.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import { buildNormalizedView } from '../src/textNormalization.mjs';
import { groundQuote } from '../src/quoteExtractor.mjs';

const LOOSE_NOTES = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  'fixtures',
  'adversarial-intake',
  'loose-notes',
);
const GROUNDING = { buildNormalizedView, groundQuote };
const INTENT = 'compare deduplication thresholds across pretraining corpora';
const SEEDS = [
  { idType: 'doi', id: '10.1234/example.5678', title: 'A seed paper on deduplication' },
  { idType: 'arxiv', id: '2401.12345', title: 'Second seed on data quality' },
];

let entryMod;
let deriveMod;
let validateMod;

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  entryMod = await import(indexUrl.href);
  deriveMod = await import(new URL('derivePlan.mjs', indexUrl).href);
  validateMod = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
});

/** Gandalf summarize spy grounded verbatim in the loose-notes fixture. */
function summarizeSpy() {
  const spy = (payload) => {
    spy.calls.push(payload);
    return {
      sentences: [
        {
          text: 'Held-out perplexity improved monotonically with data quality filtering.',
          sourceId: 'r0/scaling-notes.md',
          quote: 'the held-out perplexity improved monotonically with data quality filtering',
        },
      ],
    };
  };
  spy.calls = [];
  return spy;
}

/** Derive spy emitting a schema-valid artifact anchored to whichever grounded text it got. */
function deriveSpy() {
  const spy = (payload) => {
    spy.calls.push(payload);
    const sourceId =
      deriveMod.SUMMARY_SOURCE_ID in payload.groundedSources
        ? deriveMod.SUMMARY_SOURCE_ID
        : deriveMod.INTENT_SOURCE_ID;
    const anchors = [{ sourceId, quote: payload.groundedSources[sourceId] }];
    return {
      artifactVersion: 'plan-artifact/1',
      scope: { statement: 'Derived scope.', axis: 'Derived AXIS.', anchors },
      branches: [{ question: 'Derived question?', rationale: 'Derived rationale.', anchors }],
      sourcesToBeat: [],
      foresight: {
        dropped: 'nothing dropped',
        counterfactualCost: 'no cost',
        stamp: 'no foresight value added',
        anchors,
      },
      seeds: SEEDS.map(({ idType, id, title }) => ({ idType, id, title })),
    };
  };
  spy.calls = [];
  return spy;
}

describe('Wave 8 — input routing through the real end-to-end entry', () => {
  test('route 1 — CONTENT: ingest -> ONE Gandalf call -> ONE derive call -> PlanArtifact', async () => {
    const summarize = summarizeSpy();
    const derive = deriveSpy();
    const res = await entryMod.brownfieldIntake({
      roots: [LOOSE_NOTES],
      seeds: SEEDS,
      summarize,
      grounding: GROUNDING,
      derive,
    });

    assert.equal(res.ok, true, res.reason);
    assert.equal(res.route, entryMod.INTAKE_ROUTES.CONTENT);
    assert.equal(res.gandalfCalls, 1);
    assert.equal(res.deriveCalls, 1);
    assert.equal(summarize.calls.length, 1);
    assert.equal(derive.calls.length, 1);

    // The derive read the GROUNDED SUMMARY (not raw files) plus the seed context.
    const payload = derive.calls[0];
    assert.equal(payload.groundedSources[deriveMod.SUMMARY_SOURCE_ID], res.summary.summary);
    for (const seed of SEEDS) {
      assert.ok(deriveMod.seedSourceId(seed) in payload.groundedSources);
    }

    // The end-to-end output is a schema-valid, anchored PlanArtifact.
    const check = validateMod.validatePlanArtifact(res.artifact);
    assert.equal(check.ok, true, JSON.stringify(check.reasons));
    assert.ok(res.groundedSources[deriveMod.SUMMARY_SOURCE_ID]);
    // Advisory readiness preview rides along, display-only.
    assert.match(res.readinessPreview, /PLAN READINESS PREVIEW/);
    assert.match(res.readinessPreview, /display only/);
  });

  test('route 2 — INTENT-ONLY: derive reads the fenced intent; Gandalf is invoked ZERO times', async () => {
    const summarize = summarizeSpy();
    const derive = deriveSpy();
    const res = await entryMod.brownfieldIntake({
      intent: INTENT,
      seeds: SEEDS,
      summarize,
      grounding: GROUNDING,
      derive,
    });

    assert.equal(res.ok, true, res.reason);
    assert.equal(res.route, entryMod.INTAKE_ROUTES.INTENT_ONLY);
    assert.equal(res.gandalfCalls, 0);
    assert.equal(summarize.calls.length, 0, 'zero Gandalf calls on the intent route');
    assert.equal(res.summary, null, 'no grounded-summary stage ran');
    assert.equal(res.deriveCalls, 1);
    assert.equal(derive.calls.length, 1);

    const payload = derive.calls[0];
    assert.equal(payload.groundedSources[deriveMod.INTENT_SOURCE_ID], INTENT);
    assert.equal(deriveMod.SUMMARY_SOURCE_ID in payload.groundedSources, false);
    assert.equal(validateMod.validatePlanArtifact(res.artifact).ok, true);
  });

  test('route 3 — SEEDS-ONLY: a trivial default plan bootstraps deterministically from seed metadata; ZERO LLM calls; the run proceeds', async () => {
    const summarize = summarizeSpy();
    const derive = deriveSpy();
    const res = await entryMod.brownfieldIntake({
      seeds: SEEDS,
      summarize,
      grounding: GROUNDING,
      derive,
    });

    assert.equal(res.ok, true, res.reason);
    assert.equal(res.route, entryMod.INTAKE_ROUTES.SEEDS_ONLY);
    assert.equal(res.gandalfCalls, 0);
    assert.equal(res.deriveCalls, 0);
    assert.equal(summarize.calls.length, 0);
    assert.equal(derive.calls.length, 0, 'the bootstrap spends no derive call');

    // The trivial default plan: schema-valid, seeded, proposing nothing beyond the seeds.
    const check = validateMod.validatePlanArtifact(res.artifact);
    assert.equal(check.ok, true, JSON.stringify(check.reasons));
    assert.deepStrictEqual(res.artifact.seeds, SEEDS.map((s) => ({ ...s })));
    assert.deepStrictEqual(res.artifact.branches, []);
    assert.deepStrictEqual(res.artifact.sourcesToBeat, []);
    assert.match(res.artifact.foresight.stamp, /seeds-only bootstrap/);
    // Bootstrap determinism: a second run yields byte-identical canonical output.
    const again = await entryMod.brownfieldIntake({ seeds: SEEDS });
    assert.equal(
      validateMod.canonicalStringifyPlanArtifact(again.artifact),
      validateMod.canonicalStringifyPlanArtifact(res.artifact),
    );
  });

  test('route 4 — ZERO-INPUT: no content, no intent, no seeds -> FAIL FAST asking for content, intent, or seeds', async () => {
    const summarize = summarizeSpy();
    const derive = deriveSpy();
    const res = await entryMod.brownfieldIntake({ summarize, grounding: GROUNDING, derive });

    assert.equal(res.ok, false);
    assert.equal(res.route, entryMod.INTAKE_ROUTES.ZERO_INPUT);
    assert.equal(res.gandalfCalls, 0);
    assert.equal(res.deriveCalls, 0);
    assert.equal(summarize.calls.length, 0);
    assert.equal(derive.calls.length, 0);
    assert.equal(res.artifact, null);
    assert.match(res.reason, /content/);
    assert.match(res.reason, /intent/);
    assert.match(res.reason, /seed/);
  });

  test('all-seeds-malformed with nothing else is still zero-input: rejected seeds never bootstrap', async () => {
    const res = await entryMod.brownfieldIntake({
      seeds: [{ idType: 'doi', id: 'not-a-doi', title: 'Malformed seed' }],
    });
    assert.equal(res.ok, false);
    assert.equal(res.route, entryMod.INTAKE_ROUTES.ZERO_INPUT);
    assert.equal(res.seeds.rejected.length, 1);
    assert.match(res.seeds.rejected[0].reason, /malformed doi/);
    assert.match(res.reason, /rejected by strict validation/);
  });

  test('a fail-fast budget decision at the intake door stops everything before any call', async () => {
    const summarize = summarizeSpy();
    const derive = deriveSpy();
    const res = await entryMod.brownfieldIntake({
      roots: [LOOSE_NOTES],
      budgetTokens: 1,
      intent: INTENT,
      seeds: SEEDS,
      summarize,
      grounding: GROUNDING,
      derive,
    });

    assert.equal(res.ok, false);
    assert.equal(res.route, entryMod.INTAKE_ROUTES.CONTENT);
    assert.equal(res.gandalfCalls, 0);
    assert.equal(res.deriveCalls, 0);
    assert.equal(summarize.calls.length, 0);
    assert.equal(derive.calls.length, 0);
    assert.equal(res.artifact, null);
    assert.match(res.reason, /narrow your roots/);
    assert.equal(res.manifest.proceed, false, 'the manifest carries the fail-fast verdict (display, not a gate)');
  });

  test('the routing decision itself is pure and pinned: content > intent > seeds > fail-fast', () => {
    const d = entryMod.decideIntakeRoute;
    assert.equal(d({ contentPresent: true, intent: INTENT, seeds: SEEDS }), 'content');
    assert.equal(d({ contentPresent: false, intent: INTENT, seeds: SEEDS }), 'intent-only');
    assert.equal(d({ contentPresent: false, intent: '   ', seeds: SEEDS }), 'seeds-only-bootstrap');
    assert.equal(d({ contentPresent: false, intent: null, seeds: [] }), 'zero-input-fail-fast');
    assert.equal(d({}), 'zero-input-fail-fast');
  });
});
