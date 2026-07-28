// test/stage0-complexity.test.mjs — C3 gate for the Stage-0 complexity triage.
//
// Drives bin/stage0.mjs's assessComplexity() — the FIRST step of Stage 0 — and proves
// it right-sizes the pipeline from cheap intake signals WITHOUT touching Crucible's core
// contract:
//   · LITE on a small/clear/low-stakes intake (single-pass, minimal/no Shark rounds);
//   · FULL on Complicated/novel work (the heavyweight 3-stage + Shark-Tank machinery);
//   · SPIKE-FIRST on genuinely uncertain work (probe before planning);
//   · the high-stakes / irreversible DEFAULT to FULL — rigor is NEVER silently downgraded;
//   · FULL as the safe default when the band is uncertain;
//   · every result carries a rationale + a confirm-band HALT (right-sizing is a USER call).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../bin/crucible-lib.mjs';
import { assessComplexity, COMPLEXITY_BANDS } from '../bin/stage0.mjs';

test('LITE: a small, clear, low-stakes intake recommends a single-pass plan', () => {
  const r = assessComplexity({ intent: 'tweak a skill paragraph', scope: 'small', unknowns: 0 });
  assert.equal(r.band, COMPLEXITY_BANDS.LITE);
  assert.equal(r.depth, COMPLEXITY_BANDS.LITE);
  assert.equal(typeof r.rationale, 'string');
  assert.ok(r.rationale.length > 0, 'returns a non-empty rationale');
  assert.equal(r.defaultedToFull, false);
});

test('FULL: complicated/novel work (but bounded unknowns) keeps the full pipeline', () => {
  const r = assessComplexity({ scope: 'large', novel: true, unknowns: 1 });
  assert.equal(r.band, COMPLEXITY_BANDS.FULL);
  assert.ok(r.rationale.length > 0, 'returns a rationale');
});

test('SPIKE-FIRST: genuinely uncertain work (novel + many unknowns) probes before planning', () => {
  const r = assessComplexity({ scope: 'medium', novel: true, unknowns: 4 });
  assert.equal(r.band, COMPLEXITY_BANDS.SPIKE_FIRST);
  assert.match(r.rationale, /probe|spike|before planning/i);
});

test('high stakes ⇒ FULL: rigor is NEVER silently downgraded, even on a tiny scope', () => {
  const r = assessComplexity({ scope: 'small', unknowns: 0, highStakes: true });
  assert.equal(r.band, COMPLEXITY_BANDS.FULL, 'high stakes forces FULL over the LITE signals');
  assert.match(r.rationale, /high.stakes|rigor/i);
});

test('irreversibility ⇒ FULL even when novel + many unknowns would otherwise spike', () => {
  const r = assessComplexity({ scope: 'medium', novel: true, unknowns: 5, irreversible: true });
  assert.equal(r.band, COMPLEXITY_BANDS.FULL, 'irreversible work keeps full rigor, not a spike');
});

test('FULL by default when the band is uncertain (no clear lighter case)', () => {
  const r = assessComplexity({ scope: 'medium', unknowns: 2 });
  assert.equal(r.band, COMPLEXITY_BANDS.FULL);
  assert.equal(r.defaultedToFull, true, 'flags that it defaulted to FULL when uncertain');
});

test('an empty intake is safe: defaults to FULL with a rationale', () => {
  const r = assessComplexity();
  assert.equal(r.band, COMPLEXITY_BANDS.FULL);
  assert.ok(r.rationale.length > 0);
});

test('right-sizing is a USER judgment: the result carries a confirm-band HALT', () => {
  const r = assessComplexity({ scope: 'small', unknowns: 0 });
  assert.ok(r.halt instanceof HaltError, 'carries a HALT for the user to confirm the band');
  assert.equal(r.halt.pending_action, 'confirm-complexity-band');
  assert.ok(r.halt.halt_for_human, 'it is a halt-for-human signal');
});

test('a brownfield intake never collapses to LITE on its own (raises the floor)', () => {
  const r = assessComplexity({ scope: 'small', unknowns: 0, brownfield: true });
  assert.notEqual(r.band, COMPLEXITY_BANDS.LITE, 'an existing project is not auto-LITE');
});
