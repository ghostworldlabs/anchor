// Vocabulary pin — both NS-01 axes are frozen exact tokens.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  MODEL_TIERS,
  DEPTH_BANDS,
  MODEL_TIER_VALUES,
  DEPTH_BAND_VALUES,
  NS01_WAVE1_STAMP,
  isModelTier,
  isProcessDepth,
  normalizeDepth,
  normalizeTier,
} from '../core.mjs';

test('NS01_WAVE1_STAMP is exported (wave-1 deliverable pin)', () => {
  assert.equal(NS01_WAVE1_STAMP, 'ns01-w1');
});

test('model tier axis is exactly Heavy | Standard', () => {
  assert.deepEqual([...MODEL_TIER_VALUES].sort(), ['Heavy', 'Standard']);
  assert.equal(MODEL_TIERS.HEAVY, 'Heavy');
  assert.equal(MODEL_TIERS.STANDARD, 'Standard');
  assert.equal(isModelTier('Heavy'), true);
  assert.equal(isModelTier('Standard'), true);
  assert.equal(isModelTier('heavy'), false, 'emit tokens are Title-case only');
  assert.equal(isModelTier('LIGHT'), false);
  assert.equal(isModelTier(''), false);
  assert.equal(isModelTier(null), false);
});

test('process depth axis is exactly FULL | LITE | SPIKE (SPIKE first-class)', () => {
  assert.deepEqual([...DEPTH_BAND_VALUES].sort(), ['FULL', 'LITE', 'SPIKE']);
  assert.equal(DEPTH_BANDS.FULL, 'FULL');
  assert.equal(DEPTH_BANDS.LITE, 'LITE');
  assert.equal(DEPTH_BANDS.SPIKE, 'SPIKE');
  // Legacy property name is an alias of the SPIKE pin (B3 renorm).
  assert.equal(DEPTH_BANDS.SPIKE_FIRST, 'SPIKE');
  assert.equal(isProcessDepth('FULL'), true);
  assert.equal(isProcessDepth('LITE'), true);
  assert.equal(isProcessDepth('SPIKE'), true);
  assert.equal(isProcessDepth('SPIKE-FIRST'), true, 'legacy stored pin still accepted');
  assert.equal(isProcessDepth('full'), false, 'emit tokens are UPPERCASE only');
  assert.equal(isProcessDepth('LIGHT'), false, 'LIGHT is not a depth token (alias only on input)');
  assert.equal(isProcessDepth('lite'), false);
});

test('normalizeDepth accepts aliases but emits only pin tokens (SPIKE first-class)', () => {
  assert.equal(normalizeDepth('full'), 'FULL');
  assert.equal(normalizeDepth('LITE'), 'LITE');
  assert.equal(normalizeDepth('light'), 'LITE');
  // SPIKE-FIRST / SPIKE_FIRST / SPIKEFIRST → SPIKE (B3 operator vocabulary).
  assert.equal(normalizeDepth('spike-first'), 'SPIKE');
  assert.equal(normalizeDepth('spike_first'), 'SPIKE');
  assert.equal(normalizeDepth('SPIKEFIRST'), 'SPIKE');
  assert.equal(normalizeDepth('SPIKE'), 'SPIKE');
  assert.equal(normalizeDepth('unknown-band'), null);
  assert.equal(normalizeDepth(''), null);
  assert.equal(normalizeDepth(undefined), null);
});

test('normalizeTier accepts aliases but emits only pin tokens', () => {
  assert.equal(normalizeTier('heavy'), 'Heavy');
  assert.equal(normalizeTier('HEAVY'), 'Heavy');
  assert.equal(normalizeTier('frontier'), 'Heavy');
  assert.equal(normalizeTier('standard'), 'Standard');
  assert.equal(normalizeTier('regular'), 'Standard');
  assert.equal(normalizeTier('mid'), 'Standard');
  assert.equal(normalizeTier('opus'), null);
  assert.equal(normalizeTier(''), null);
});
