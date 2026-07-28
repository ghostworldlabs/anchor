// Track B7 — literature-review control plane hermetic units (B7-C1 / C2 / C3 pieces)
// + W4 fail-if-missing ship-gate registry for B7-C1..C4.
//
// Proves:
//   · literatureReviewKnobs returns knobs-only shape (omits floor keys)
//   · LIT_REVIEW_SAFETY_FLOOR frozen + identical under all bands (object identity)
//   · resolveLiteratureReviewBand deep-equals live mapping snowballDepth/adversarialRounds
//   · load-or-init leaner soft-assert GREEN on live table without remapping
//   · partial-override refuse while FOUNDRY_TRIAGE_DEPTH advertised
//   · unknown depth → LIT_REVIEW_UNKNOWN_DEPTH (refuse-closed)
//   · W4: fail-if-missing registry requires B7-C1..C4 test names in ship-gate suite

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  BAND_MAPPINGS,
  LIT_REVIEW_SAFETY_FLOOR,
  LIT_REVIEW_UNKNOWN_DEPTH,
  LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED,
  assertLiteratureReviewBandInvariants,
  literatureReviewKnobs,
  resolveLiteratureReviewBand,
} from '../mapping.mjs';
import {
  REQUIRED_B7_CELL_IDS,
  B7_SHIP_GATE_TEST_FILES,
  assertB7CellRegistryPresent,
  assertB7CellPresent,
} from './b7-ship-registry.mjs';

const FLOOR_KEYS = [
  'requireQuoteGrounding',
  'oneCallPerPaperExtraction',
  'minGroundedClaimsPerPaper',
];

const KNOBS_KEYS = new Set([
  'depth',
  'snowballDepth',
  'adversarialRounds',
  'ceremony',
  'seats',
  'skill',
]);

const BANDS = ['LITE', 'FULL', 'SPIKE'];

test('B7-C1-control-plane: literatureReviewKnobs knobs-only shape omits floor keys', () => {
  for (const band of BANDS) {
    const knobs = literatureReviewKnobs(band);
    assert.ok(knobs, `literatureReviewKnobs(${band}) must resolve`);
    assert.equal(knobs.skill, 'literature-review');
    assert.equal(knobs.depth, band === 'SPIKE' ? 'SPIKE' : band);
    for (const key of FLOOR_KEYS) {
      assert.equal(
        Object.prototype.hasOwnProperty.call(knobs, key),
        false,
        `knobs must omit floor key ${key}`,
      );
    }
    for (const key of Object.keys(knobs)) {
      assert.ok(KNOBS_KEYS.has(key), `unexpected knobs key ${key}`);
    }
    assert.ok(Object.isFrozen(knobs), 'literatureReviewKnobs return must be frozen');
  }
});

test('B7-C1-control-plane: knobs deep-equal live BAND_MAPPINGS snowballDepth/adversarialRounds', () => {
  for (const band of BANDS) {
    const knobs = literatureReviewKnobs(band);
    const row = BAND_MAPPINGS['literature-review'][band];
    assert.ok(row, `live mapping row for ${band}`);
    assert.equal(knobs.snowballDepth, row.snowballDepth);
    assert.equal(knobs.adversarialRounds, row.adversarialRounds);
    assert.equal(knobs.ceremony, row.ceremony);
    assert.equal(knobs.seats, row.seats);
  }
});

test('B7-C1-control-plane: resolve deep-equals live mapping; floor is LIT_REVIEW_SAFETY_FLOOR identity', () => {
  for (const band of BANDS) {
    const resolved = resolveLiteratureReviewBand({
      confirmedDepth: band,
      env: {},
    });
    const row = BAND_MAPPINGS['literature-review'][band];
    assert.equal(resolved.band, band === 'SPIKE' ? 'SPIKE' : band);
    assert.equal(resolved.source, 'confirmed-depth');
    assert.equal(resolved.knobs.snowballDepth, row.snowballDepth);
    assert.equal(resolved.knobs.adversarialRounds, row.adversarialRounds);
    assert.equal(resolved.floor, LIT_REVIEW_SAFETY_FLOOR);
    for (const key of FLOOR_KEYS) {
      assert.equal(
        Object.prototype.hasOwnProperty.call(resolved.knobs, key),
        false,
        'resolve knobs must omit floor keys',
      );
    }
  }
});

test('B7-C1-control-plane: floor frozen and identical under all bands (not depth-variable)', () => {
  assert.ok(Object.isFrozen(LIT_REVIEW_SAFETY_FLOOR));
  assert.equal(LIT_REVIEW_SAFETY_FLOOR.requireQuoteGrounding, true);
  assert.equal(LIT_REVIEW_SAFETY_FLOOR.oneCallPerPaperExtraction, true);
  assert.equal(LIT_REVIEW_SAFETY_FLOOR.minGroundedClaimsPerPaper, 1);

  const floors = BANDS.map(
    (band) => resolveLiteratureReviewBand({ confirmedDepth: band, env: {} }).floor,
  );
  for (const f of floors) {
    assert.equal(f, LIT_REVIEW_SAFETY_FLOOR, 'floor must be object identity for every band');
  }
});

test('B7-C1-control-plane: precedence FOUNDRY_TRIAGE_DEPTH over LITREVIEW; default-full when missing', () => {
  const fromFoundry = resolveLiteratureReviewBand({
    env: { FOUNDRY_TRIAGE_DEPTH: 'LITE', LITREVIEW_TRIAGE_DEPTH: 'FULL' },
  });
  assert.equal(fromFoundry.source, 'foundry-triage-depth');
  assert.equal(fromFoundry.band, 'LITE');
  assert.equal(
    fromFoundry.knobs.snowballDepth,
    literatureReviewKnobs('LITE').snowballDepth,
  );

  const fromSkill = resolveLiteratureReviewBand({
    env: { LITREVIEW_TRIAGE_DEPTH: 'SPIKE' },
  });
  assert.equal(fromSkill.source, 'litreview-triage-depth');
  assert.equal(fromSkill.band, 'SPIKE');

  const def = resolveLiteratureReviewBand({ env: {} });
  assert.equal(def.source, 'default-full');
  assert.equal(def.band, 'FULL');
  assert.equal(def.knobs.snowballDepth, literatureReviewKnobs('FULL').snowballDepth);
  assert.equal(def.floor, LIT_REVIEW_SAFETY_FLOOR);
});

test('B7-C1-control-plane: FOUNDRY_TRIAGE_DEPTH + desynced snowballDepth → PARTIAL_OVERRIDE_REFUSED', () => {
  const mapped = literatureReviewKnobs('LITE');
  assert.ok(mapped);
  const desynced = mapped.snowballDepth + 99;
  assert.throws(
    () =>
      resolveLiteratureReviewBand({
        env: { FOUNDRY_TRIAGE_DEPTH: 'LITE' },
        snowballDepth: desynced,
      }),
    (err) => {
      assert.equal(err && err.code, LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED);
      return true;
    },
  );
  // Clean lock with matching explicit values still succeeds.
  const clean = resolveLiteratureReviewBand({
    env: { FOUNDRY_TRIAGE_DEPTH: 'LITE' },
    snowballDepth: mapped.snowballDepth,
    adversarialRounds: mapped.adversarialRounds,
  });
  assert.equal(clean.band, 'LITE');
  assert.equal(clean.knobs.snowballDepth, mapped.snowballDepth);
});

test('B7-C1-control-plane: FOUNDRY_TRIAGE_DEPTH + desynced adversarialRounds → PARTIAL_OVERRIDE_REFUSED', () => {
  const mapped = literatureReviewKnobs('LITE');
  assert.throws(
    () =>
      resolveLiteratureReviewBand({
        env: { FOUNDRY_TRIAGE_DEPTH: 'LITE' },
        adversarialRounds: mapped.adversarialRounds + 50,
      }),
    (err) => {
      assert.equal(err && err.code, LIT_REVIEW_PARTIAL_OVERRIDE_REFUSED);
      return true;
    },
  );
});

test('B7-C1-control-plane: unknown depth token → LIT_REVIEW_UNKNOWN_DEPTH (no silent FULL lock)', () => {
  assert.throws(
    () =>
      resolveLiteratureReviewBand({
        confirmedDepth: 'NOT-A-DEPTH',
        env: {},
      }),
    (err) => {
      assert.equal(err && err.code, LIT_REVIEW_UNKNOWN_DEPTH);
      return true;
    },
  );
  assert.throws(
    () =>
      resolveLiteratureReviewBand({
        env: { FOUNDRY_TRIAGE_DEPTH: 'banana' },
      }),
    (err) => {
      assert.equal(err && err.code, LIT_REVIEW_UNKNOWN_DEPTH);
      return true;
    },
  );
});

test('B7-C3-floor pieces: load-or-init leaner soft-assert GREEN on live table without remapping', () => {
  // Live table must already satisfy leaner; assert does not rewrite cells.
  const before = JSON.stringify(BAND_MAPPINGS['literature-review']);
  assert.equal(assertLiteratureReviewBandInvariants(BAND_MAPPINGS['literature-review']), true);
  assert.equal(
    JSON.stringify(BAND_MAPPINGS['literature-review']),
    before,
    'assert must not remap/rewrite live mapping',
  );

  const lite = literatureReviewKnobs('LITE');
  const full = literatureReviewKnobs('FULL');
  const leaner =
    lite.snowballDepth < full.snowballDepth ||
    lite.adversarialRounds < full.adversarialRounds;
  assert.equal(leaner, true, 'SC2 leaner must hold on live knobs');
});

test('B7-C3-floor pieces: assert hard-fails thinned floor false/0 and broken leaner (no remap)', () => {
  assert.throws(
    () =>
      assertLiteratureReviewBandInvariants({
        FULL: { snowballDepth: 3, adversarialRounds: 2, ceremony: 'full', seats: 'frontier' },
        LITE: {
          snowballDepth: 1,
          adversarialRounds: 1,
          ceremony: 'lite',
          seats: 'standard',
          requireQuoteGrounding: false,
        },
        SPIKE: { snowballDepth: 2, adversarialRounds: 1, ceremony: 'spike-first', seats: 'frontier' },
      }),
    (err) => {
      assert.equal(err && err.code, 'LIT_REVIEW_BAND_INVARIANT');
      return true;
    },
  );

  assert.throws(
    () =>
      assertLiteratureReviewBandInvariants({
        FULL: { snowballDepth: 1, adversarialRounds: 1, ceremony: 'full', seats: 'frontier' },
        LITE: { snowballDepth: 1, adversarialRounds: 1, ceremony: 'lite', seats: 'standard' },
        SPIKE: { snowballDepth: 1, adversarialRounds: 1, ceremony: 'spike-first', seats: 'frontier' },
      }),
    (err) => {
      assert.equal(err && err.code, 'LIT_REVIEW_BAND_INVARIANT');
      return true;
    },
  );

  assert.throws(
    () =>
      assertLiteratureReviewBandInvariants({
        FULL: { snowballDepth: 3, adversarialRounds: 2, ceremony: 'full', seats: 'frontier' },
        LITE: {
          snowballDepth: 0,
          adversarialRounds: 1,
          ceremony: 'lite',
          seats: 'standard',
        },
        SPIKE: { snowballDepth: 2, adversarialRounds: 1, ceremony: 'spike-first', seats: 'frontier' },
      }),
    (err) => {
      assert.equal(err && err.code, 'LIT_REVIEW_BAND_INVARIANT');
      return true;
    },
  );
});

// ── B7 W3 — B7-C2-lean (SC2 numeric-only; ceremony not required for GREEN) ──

test('B7-C2-lean: SC2 predicate on live literatureReviewKnobs integers only', () => {
  const lite = literatureReviewKnobs('LITE');
  const full = literatureReviewKnobs('FULL');
  assert.ok(lite && full);
  assert.equal(lite.snowballDepth, BAND_MAPPINGS['literature-review'].LITE.snowballDepth);
  assert.equal(full.snowballDepth, BAND_MAPPINGS['literature-review'].FULL.snowballDepth);
  assert.equal(lite.adversarialRounds, BAND_MAPPINGS['literature-review'].LITE.adversarialRounds);
  assert.equal(full.adversarialRounds, BAND_MAPPINGS['literature-review'].FULL.adversarialRounds);
  const leaner =
    lite.snowballDepth < full.snowballDepth ||
    lite.adversarialRounds < full.adversarialRounds;
  assert.equal(leaner, true, 'SC2 leaner on live numeric knobs only');
});

test('B7-C3-floor: floor fields exact-true across LITE|FULL|SPIKE(+aliases)', () => {
  for (const token of ['LITE', 'FULL', 'SPIKE', 'SPIKE-FIRST', 'SPIKE_FIRST', 'SPIKEFIRST']) {
    const resolved = resolveLiteratureReviewBand({ confirmedDepth: token, env: {} });
    assert.equal(resolved.floor, LIT_REVIEW_SAFETY_FLOOR);
    assert.equal(resolved.floor.requireQuoteGrounding, true);
    assert.equal(resolved.floor.oneCallPerPaperExtraction, true);
    assert.equal(resolved.floor.minGroundedClaimsPerPaper, 1);
  }
});

// ── B7 W4 — fail-if-missing registry (sole ship-gate C1..C4) ──

test('B7-C1-control-plane: distinct band vs snowballDepth vs adversarialRounds fields', () => {
  for (const band of BANDS) {
    const knobs = literatureReviewKnobs(band);
    const resolved = resolveLiteratureReviewBand({ confirmedDepth: band, env: {} });
    // band is a depth token string; knobs.depth is the band; snowball/rounds are integers.
    assert.equal(typeof resolved.band, 'string');
    assert.equal(typeof knobs.depth, 'string');
    assert.equal(typeof knobs.snowballDepth, 'number');
    assert.equal(typeof knobs.adversarialRounds, 'number');
    assert.notEqual(knobs.snowballDepth, knobs.depth);
    assert.notEqual(knobs.adversarialRounds, knobs.depth);
    // No collision: integer snowball is never stored as the band field.
    assert.equal(resolved.band, knobs.depth);
    assert.equal(resolved.knobs.snowballDepth, knobs.snowballDepth);
    assert.equal(resolved.knobs.adversarialRounds, knobs.adversarialRounds);
  }
});

test('B7-C-registry: fail-if-missing B7-C1..C4 all present in ship-gate suite', () => {
  const r = assertB7CellRegistryPresent();
  assert.equal(r.ok, true);
  assert.deepEqual(r.ids, [
    'B7-C1-control-plane',
    'B7-C2-lean',
    'B7-C3-floor',
    'B7-C4-compose',
  ]);
  assert.deepEqual([...REQUIRED_B7_CELL_IDS], r.ids);
  assert.equal(B7_SHIP_GATE_TEST_FILES.length, 4);
  for (const id of REQUIRED_B7_CELL_IDS) {
    assert.ok(r.coverage[id].length >= 1, `${id} must have ≥1 test name`);
  }
});

test('B7-C-registry: missing cell name fails closed (B7_CELL_MISSING)', () => {
  assert.throws(
    () => assertB7CellPresent('B7-C99-not-registered'),
    (err) => err && err.code === 'B7_CELL_MISSING',
  );
});
