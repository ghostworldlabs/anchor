// Wave 2 — lock record + getLockedBand (throw-on-unlocked, headless HALT,
// interactive confirm/edit, no second reader sites).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  MODEL_TIERS,
  DEPTH_BANDS,
  recommend,
} from '../core.mjs';
import {
  LOCK_SOURCES,
  LOCK_SOURCE_VALUES,
  isLockRecord,
  createLockRecord,
  getLockedBand,
  applyLock,
  lockFromInteractive,
  lockFromHeadless,
} from '../lock.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(here, '..');

test('createLockRecord validates schema and freezes both axes', () => {
  const lock = createLockRecord({
    tier: 'Heavy',
    depth: 'FULL',
    rationale: 'test lock',
    source: 'config',
  });
  assert.equal(lock.locked, true);
  assert.equal(lock.tier, MODEL_TIERS.HEAVY);
  assert.equal(lock.depth, DEPTH_BANDS.FULL);
  assert.equal(lock.source, LOCK_SOURCES.CONFIG);
  assert.ok(lock.lockedAt);
  assert.ok(Object.isFrozen(lock));
  assert.equal(isLockRecord(lock), true);
});

test('createLockRecord accepts aliases but emits pin tokens', () => {
  const lock = createLockRecord({
    tier: 'standard',
    depth: 'light',
    rationale: 'alias check',
    source: 'inherit',
  });
  assert.equal(lock.tier, MODEL_TIERS.STANDARD);
  assert.equal(lock.depth, DEPTH_BANDS.LITE);
  assert.equal(lock.source, LOCK_SOURCES.INHERIT);
});

test('createLockRecord rejects incomplete / invalid inputs', () => {
  assert.throws(
    () => createLockRecord({ tier: 'Heavy', depth: 'FULL', source: 'config' }),
    (err) => {
      assert.equal(err.code, 'TRIAGE_LOCK_SCHEMA');
      return true;
    },
  );
  assert.throws(
    () =>
      createLockRecord({
        tier: 'Heavy',
        depth: 'FULL',
        rationale: 'x',
        source: 'forged',
      }),
    /TRIAGE_LOCK_SCHEMA|invalid/,
  );
});

test('getLockedBand throws when unlocked (null / empty / recommend-only)', () => {
  assert.throws(
    () => getLockedBand(null),
    (err) => {
      assert.equal(err.name, 'TriageUnlockedError');
      assert.equal(err.code, 'TRIAGE_UNLOCKED');
      assert.match(String(err.message), /unlocked/i);
      return true;
    },
  );
  assert.throws(() => getLockedBand(undefined), /TRIAGE_UNLOCKED|unlocked/);
  assert.throws(() => getLockedBand({}), /TRIAGE_UNLOCKED|unlocked/);
  // Advisory recommend() alone is NOT a lock — no silent empty lock path.
  const rec = recommend({ scope: 'small', unknowns: 0 });
  assert.throws(() => getLockedBand(rec), /TRIAGE_UNLOCKED|unlocked/);
  assert.throws(() => getLockedBand({ lock: null }), /TRIAGE_UNLOCKED|unlocked/);
  assert.throws(
    () =>
      getLockedBand({
        tier: 'Heavy',
        depth: 'FULL',
        // missing locked/source/rationale/lockedAt
      }),
    /TRIAGE_UNLOCKED|unlocked/,
  );
});

test('getLockedBand returns validated band from record or host.lock', () => {
  const lock = createLockRecord({
    tier: MODEL_TIERS.STANDARD,
    depth: DEPTH_BANDS.LITE,
    rationale: 'host bag',
    source: LOCK_SOURCES.INTERACTIVE,
  });
  const fromRecord = getLockedBand(lock);
  assert.equal(fromRecord.tier, MODEL_TIERS.STANDARD);
  assert.equal(fromRecord.depth, DEPTH_BANDS.LITE);
  assert.equal(fromRecord.locked, true);

  const host = {};
  applyLock(host, lock);
  const fromHost = getLockedBand(host);
  assert.equal(fromHost.tier, MODEL_TIERS.STANDARD);
  assert.equal(fromHost.depth, DEPTH_BANDS.LITE);
  assert.equal(fromHost.source, LOCK_SOURCES.INTERACTIVE);
});

test('lockFromInteractive confirm locks recommendation axes', () => {
  const recommendation = recommend({
    intent: 'tweak a skill paragraph',
    scope: 'small',
    unknowns: 0,
  });
  const lock = lockFromInteractive({
    decision: 'confirm',
    recommendation,
  });
  assert.equal(lock.locked, true);
  assert.equal(lock.source, LOCK_SOURCES.INTERACTIVE);
  assert.equal(lock.tier, recommendation.tier);
  assert.equal(lock.depth, recommendation.depth);
  const band = getLockedBand(lock);
  assert.equal(band.tier, recommendation.tier);
  assert.equal(band.depth, recommendation.depth);
});

test('lockFromInteractive edit overrides recommendation', () => {
  const recommendation = recommend({ scope: 'small', unknowns: 0 });
  const lock = lockFromInteractive({
    decision: 'edit',
    recommendation,
    tier: 'Heavy',
    depth: 'SPIKE-FIRST',
    rationale: 'operator override for novel probe',
  });
  assert.equal(lock.tier, MODEL_TIERS.HEAVY);
  assert.equal(lock.depth, DEPTH_BANDS.SPIKE_FIRST);
  assert.match(lock.rationale, /operator override/);
});

test('lockFromInteractive forbidden when headless=true', () => {
  assert.throws(
    () =>
      lockFromInteractive({
        decision: 'confirm',
        recommendation: recommend({ scope: 'small' }),
        headless: true,
      }),
    (err) => {
      assert.equal(err.name, 'TriageHeadlessHaltError');
      assert.equal(err.code, 'TRIAGE_HEADLESS_INTERACTIVE_FORBIDDEN');
      return true;
    },
  );
});

test('lockFromHeadless without config or inherit HALTs (no silent default)', () => {
  assert.throws(
    () => lockFromHeadless({}),
    (err) => {
      assert.equal(err.name, 'TriageHeadlessHaltError');
      assert.equal(err.code, 'TRIAGE_HEADLESS_UNLOCKED');
      assert.match(String(err.message), /HALT|unlocked headless/i);
      return true;
    },
  );
  assert.throws(() => lockFromHeadless(), /TRIAGE_HEADLESS_UNLOCKED|HALT/);
  assert.throws(
    () => lockFromHeadless({ config: { tier: 'nope', depth: 'FULL' } }),
    /TRIAGE_HEADLESS_UNLOCKED|HALT/,
  );
});

test('lockFromHeadless accepts config-time lock', () => {
  const lock = lockFromHeadless({
    config: { tier: 'Standard', depth: 'LITE', rationale: 'project setup lock' },
  });
  assert.equal(lock.source, LOCK_SOURCES.CONFIG);
  assert.equal(lock.tier, MODEL_TIERS.STANDARD);
  assert.equal(lock.depth, DEPTH_BANDS.LITE);
  assert.equal(getLockedBand(lock).depth, DEPTH_BANDS.LITE);
});

test('lockFromHeadless prefers inherit over config', () => {
  const lock = lockFromHeadless({
    config: { tier: 'Standard', depth: 'LITE' },
    inherit: { tier: 'Heavy', depth: 'FULL', rationale: 'Stage-0 handoff' },
  });
  assert.equal(lock.source, LOCK_SOURCES.INHERIT);
  assert.equal(lock.tier, MODEL_TIERS.HEAVY);
  assert.equal(lock.depth, DEPTH_BANDS.FULL);
});

test('no second reader sites: sole band reader is getLockedBand (package sources)', () => {
  // Wave 2 deliverable: tests for throw-on-unlocked + no second reader sites (grep).
  // Package production sources must not expose alternate unlocked readers of a
  // locked band. recommend() is advisory only (no .locked). Host field is only .lock.
  const srcFiles = readdirSync(pkgRoot).filter((f) => f.endsWith('.mjs'));
  assert.ok(srcFiles.includes('lock.mjs'));
  assert.ok(srcFiles.includes('core.mjs'));
  assert.ok(srcFiles.includes('index.mjs'));

  const lockSrc = readFileSync(join(pkgRoot, 'lock.mjs'), 'utf8');
  assert.match(lockSrc, /export function getLockedBand/);
  assert.match(lockSrc, /TRIAGE_UNLOCKED/);
  assert.match(lockSrc, /TRIAGE_HEADLESS_UNLOCKED/);

  // Recommend result must not look like a lock record.
  const rec = recommend({ scope: 'small', unknowns: 0 });
  assert.equal(isLockRecord(rec), false);
  assert.equal('locked' in rec, false);

  // Grep package .mjs for forbidden alternate band-reader exports.
  // (Prose may say "no silent defaults"; the contract is no second *reader*.)
  const forbidden = [
    /export function getBand\b/,
    /export function readBand\b/,
    /export function currentBand\b/,
    /export function getTier\b/,
    /export function getDepth\b/,
  ];
  for (const file of srcFiles) {
    const text = readFileSync(join(pkgRoot, file), 'utf8');
    for (const re of forbidden) {
      assert.equal(
        re.test(text),
        false,
        `${file} must not define second reader / silent default (${re})`,
      );
    }
  }

  // Public surface re-exports the lock API (index.mjs).
  const indexSrc = readFileSync(join(pkgRoot, 'index.mjs'), 'utf8');
  assert.match(indexSrc, /getLockedBand/);
  assert.match(indexSrc, /lockFromHeadless/);
  assert.match(indexSrc, /lockFromInteractive/);

  assert.deepEqual([...LOCK_SOURCE_VALUES].sort(), [
    'config',
    'inherit',
    'interactive',
  ]);
});
