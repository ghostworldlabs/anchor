// test/independence-accounting.test.mjs — covers the trio-core's single origin/quorum counter
// (IMPLEMENTATION-PLAN Wave 2). The Wave-2 acceptance "Given/When/Then" is the load-bearing
// assertion: same-lineage agreement adds 0 independent origins, a distinct attested lineage
// adds +1, and the origin COUNT is invariant under any ρ̂ (ρ̂ may only change the COUNT
// REQUIRED, and only ever TIGHTEN it, never below the static ≥2 floor).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  STATIC_QUORUM_FLOOR,
  lineageOf,
  countIndependentOrigins,
  requiredQuorum,
  meetsQuorum,
} from '../bin/trio-core/independence-accounting.mjs';

// ── lineageOf: explicit lineage, stampRole `family` fallback, blank ⇒ unattested ─────────────
test('lineageOf reads `lineage`, falls back to stampRole `family`, treats blank/missing as null', () => {
  assert.equal(lineageOf({ lineage: 'claude' }), 'claude');
  assert.equal(lineageOf({ family: 'gemini' }), 'gemini'); // stampRole-shaped reviewer
  assert.equal(lineageOf({ lineage: 'openai', family: 'claude' }), 'openai'); // explicit wins
  assert.equal(lineageOf({ lineage: '   ' }), null); // blank is not a distinct lineage named " "
  assert.equal(lineageOf({}), null);
  assert.equal(lineageOf(null), null);
});

// ── The Wave-2 Given/When/Then — same lineage adds 0, distinct adds +1 ───────────────────────
test('same declared lineage adds 0 independent origins; only a distinct lineage adds +1 (I3)', () => {
  const oneClaude = [{ lineage: 'claude' }];
  const twoSameLineage = [{ lineage: 'claude' }, { lineage: 'claude' }];
  const twoDistinct = [{ lineage: 'claude' }, { lineage: 'gemini' }];

  // A second reviewer of the SAME lineage contributes nothing — the agreement is one origin.
  assert.equal(countIndependentOrigins(oneClaude), 1);
  assert.equal(countIndependentOrigins(twoSameLineage), 1, 'same-lineage agreement must add 0');

  // A reviewer of a DISTINCT attested lineage adds exactly +1.
  assert.equal(countIndependentOrigins(twoDistinct), 2);
  assert.equal(
    countIndependentOrigins(twoDistinct),
    countIndependentOrigins(oneClaude) + 1,
    'a distinct lineage adds +1',
  );

  // Piling on more same-lineage reviewers still adds 0.
  assert.equal(countIndependentOrigins([...twoDistinct, { lineage: 'claude' }, { family: 'gemini' }]), 2);
});

test('unattested reviewers (no lineage) collapse to at most one capped origin, never one-each', () => {
  assert.equal(countIndependentOrigins([]), 0);
  assert.equal(countIndependentOrigins([{}]), 1); // a single unattested origin bucket
  assert.equal(countIndependentOrigins([{}, {}, {}]), 1, 'unattested reviewers cannot each be an origin');
  assert.equal(countIndependentOrigins([{ lineage: 'claude' }, {}, {}]), 2); // claude + one capped bucket
});

// ── ρ̂ invariance of the origin COUNT (the count never reclassifies same-lineage as independent) ──
test('the origin count is INVARIANT under any ρ̂ — only the required quorum moves', () => {
  const reviewers = [{ lineage: 'claude' }, { lineage: 'gemini' }];
  const counts = [null, 0, 0.3, 0.9, 0.999, 5, NaN].map(
    (rhoHat) => meetsQuorum(reviewers, { rhoHat }).origins,
  );
  for (const c of counts) assert.equal(c, 2, 'ρ̂ must not change the independent-origin count');
});

// ── MONOTONE-SAFETY: ρ̂ may only TIGHTEN; never below the static floor (I7/I8, crit-7) ─────────
test('requiredQuorum never drops below the static ≥2 floor for ANY ρ̂ value', () => {
  const adversarial = [null, undefined, NaN, -1, -0.5, 0, 0.1, 0.5, 0.9, 0.999, 1, 2, 100, Infinity, -Infinity];
  for (const rhoHat of adversarial) {
    const q = requiredQuorum(rhoHat);
    assert.ok(
      Number.isInteger(q) && q >= STATIC_QUORUM_FLOOR,
      `requiredQuorum(${rhoHat}) = ${q} loosened below the static floor ${STATIC_QUORUM_FLOOR}`,
    );
  }
  assert.equal(STATIC_QUORUM_FLOOR, 2);
  assert.equal(requiredQuorum(null), 2, 'no correlation ⇒ static floor');
  assert.equal(requiredQuorum(0), 2);
});

test('requiredQuorum is non-decreasing in ρ̂ (higher correlation ⇒ more origins required)', () => {
  const ladder = [0, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99];
  let prev = -Infinity;
  for (const rhoHat of ladder) {
    const q = requiredQuorum(rhoHat);
    assert.ok(q >= prev, `quorum decreased at ρ̂=${rhoHat} (${q} < ${prev}) — not monotone-tighten-only`);
    prev = q;
  }
  // It must actually TIGHTEN somewhere on the way up (not a flat no-op), else it isn't a quorum.
  assert.ok(requiredQuorum(0.9) > requiredQuorum(0), 'a high ρ̂ must raise the bar');
});

// ── Attested-lineage enum (Wave-7-ready): supplying the closed enum only TIGHTENS the count ──
test('an injected attested-lineage enum collapses off-enum lineages to the cap (monotone tighten)', () => {
  const reviewers = [{ lineage: 'claude' }, { lineage: 'mystery1' }, { lineage: 'mystery2' }];
  const open = countIndependentOrigins(reviewers); // no enum: 3 self-declared distinct lineages
  const gated = countIndependentOrigins(reviewers, { attestedLineages: ['claude', 'gemini'] });
  assert.equal(open, 3);
  assert.equal(gated, 2, 'off-enum lineages share one capped bucket: claude(+1) + {mystery*}(+1)');
  assert.ok(gated <= open, 'committing the enum must never raise the count');
});

// ── meetsQuorum: the two numbers combined ────────────────────────────────────────────────────
test('meetsQuorum joins origins-present vs origins-required; ρ̂ can starve a passing set', () => {
  const distinct = [{ lineage: 'claude' }, { lineage: 'gemini' }];
  const sameLineage = [{ lineage: 'claude' }, { lineage: 'claude' }];

  // Static rule (no ρ̂): two distinct origins meet the ≥2 floor; same-lineage agreement does not.
  assert.deepEqual(meetsQuorum(distinct), { origins: 2, required: 2, met: true });
  assert.equal(meetsQuorum(sameLineage).met, false, 'same-lineage agreement never meets ≥2');

  // A high ρ̂ raises the bar above the two origins present — same count, stricter requirement.
  const tightened = meetsQuorum(distinct, { rhoHat: 0.9 });
  assert.equal(tightened.origins, 2);
  assert.ok(tightened.required > 2 && tightened.met === false, 'ρ̂ tightened the quorum past the origins present');
});

test('countIndependentOrigins rejects a non-array input loudly', () => {
  assert.throws(() => countIndependentOrigins('nope'), TypeError);
  assert.throws(() => countIndependentOrigins(null), TypeError);
});
