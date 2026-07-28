// Wave 5 — researchPrime intake-only + mapping tables (trio + sample).
//
// Proves:
//   · mapping tables for crucible / foreman / researchPrime / gandalf (sample)
//   · inequality of knobs across FULL | LITE | SPIKE-FIRST for each mapped skill
//   · mappings consumed at named sites (crucible-wire, foreman-wire, researchprime-wire)
//   · RP triage only via intake extension (researchprime-wire); never governance.mjs
//   · governance.mjs byte-identity vs Wave-5 baseline pin
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { DEPTH_BANDS, MODEL_TIERS, recommend } from '../core.mjs';
import { createLockRecord, getLockedBand } from '../lock.mjs';
import { assessComplexity } from '../crucible-wire.mjs';
import {
  REVIEWERS_BY_DEPTH,
  reviewersForDepth,
  inheritReviewerCount,
} from '../foreman-wire.mjs';
import {
  NS01_WAVE5_STAMP,
  MAPPED_SKILLS,
  BAND_MAPPINGS,
  knobsForSkill,
  crucibleKnobs,
  foremanKnobs,
  researchPrimeKnobs,
  gandalfKnobs,
  bandsInequal,
  knobsFingerprint,
} from '../mapping.mjs';
import {
  RESEARCHPRIME_SKILL_ID,
  recommendResearchPrimeIntake,
  resolveResearchPrimeIntakeLock,
  buildResearchPrimeIntakeExtension,
  finalizeIntakeExtensionOnGate1,
} from '../researchprime-wire.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(here, '..');
const baselinePath = join(pkgRoot, 'fixtures', 'researchprime-governance.baseline.mjs');

const DEPTHS = [DEPTH_BANDS.FULL, DEPTH_BANDS.LITE, DEPTH_BANDS.SPIKE_FIRST];

function sha256(text) {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

function normalizeEol(text) {
  return String(text).replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

test('NS01_WAVE5_STAMP is exported on the mapping + RP-intake surfaces', () => {
  assert.equal(NS01_WAVE5_STAMP, 'ns01-w5-rp-intake-mapping');
});

test('mapped skills include trio + sample + Wave-6 remaining (full 11)', () => {
  // Wave 5 shipped trio + gandalf; Wave 6 completes the NS-01 set of 11.
  assert.equal(MAPPED_SKILLS.length, 11);
  for (const required of ['crucible', 'foreman', 'researchPrime', 'gandalf']) {
    assert.ok(MAPPED_SKILLS.includes(required), `missing ${required}`);
  }
  for (const skill of MAPPED_SKILLS) {
    assert.ok(BAND_MAPPINGS[skill], `BAND_MAPPINGS missing ${skill}`);
    for (const d of DEPTHS) {
      assert.ok(BAND_MAPPINGS[skill][d], `${skill} missing depth ${d}`);
      assert.ok(knobsForSkill(skill, d), `knobsForSkill(${skill},${d})`);
    }
  }
});

test('inequality across bands for every mapped skill (NS criterion 6)', () => {
  for (const skill of MAPPED_SKILLS) {
    assert.equal(
      bandsInequal(skill, DEPTH_BANDS.FULL, DEPTH_BANDS.LITE),
      true,
      `${skill}: FULL knobs must differ from LITE`,
    );
    assert.equal(
      bandsInequal(skill, DEPTH_BANDS.FULL, DEPTH_BANDS.SPIKE_FIRST),
      true,
      `${skill}: FULL knobs must differ from SPIKE-FIRST`,
    );
    assert.equal(
      bandsInequal(skill, DEPTH_BANDS.LITE, DEPTH_BANDS.SPIKE_FIRST),
      true,
      `${skill}: LITE knobs must differ from SPIKE-FIRST`,
    );

    const fingerprints = DEPTHS.map((d) => knobsFingerprint(knobsForSkill(skill, d)));
    assert.equal(new Set(fingerprints).size, 3, `${skill}: three distinct knob sets`);
  }
});

test('named site consumers return skill-tagged knobs', () => {
  const c = crucibleKnobs(DEPTH_BANDS.FULL, MODEL_TIERS.HEAVY);
  assert.equal(c.skill, 'crucible');
  assert.equal(c.sharkRounds, 3);
  assert.equal(c.seats, 'frontier');

  const f = foremanKnobs(DEPTH_BANDS.LITE, MODEL_TIERS.STANDARD);
  assert.equal(f.skill, 'foreman');
  assert.equal(f.reviewers, 1);
  assert.ok(f.reviewers >= 1);

  const r = researchPrimeKnobs(DEPTH_BANDS.SPIKE_FIRST, MODEL_TIERS.HEAVY);
  assert.equal(r.skill, 'researchPrime');
  assert.equal(r.maxRounds, 4);
  assert.equal(r.includeAdjudication, true);

  const g = gandalfKnobs(DEPTH_BANDS.LITE, MODEL_TIERS.STANDARD);
  assert.equal(g.skill, 'gandalf');
  assert.equal(g.shards, 2);
  assert.equal(g.ceremony, 'lite');
});

test('Foreman named site consumes mapping (REVIEWERS_BY_DEPTH aligned)', () => {
  for (const d of DEPTHS) {
    const fromMap = foremanKnobs(d).reviewers;
    assert.equal(REVIEWERS_BY_DEPTH[d], fromMap, `REVIEWERS_BY_DEPTH[${d}] must come from mapping`);
    assert.equal(reviewersForDepth(d), fromMap);
    assert.ok(reviewersForDepth(d) >= 1);
  }
  // LITE never zeros (Wave 4 invariant still holds via mapping).
  assert.ok(foremanKnobs(DEPTH_BANDS.LITE).reviewers >= 1);
  const inherited = inheritReviewerCount({ triage_track: 'LITE' });
  assert.equal(inherited.reviewers, foremanKnobs(DEPTH_BANDS.LITE).reviewers);
});

test('Crucible named site consumes mapping (assessComplexity.bandKnobs)', () => {
  const r = assessComplexity({
    intent: 'tweak a skill paragraph',
    scope: 'small',
    unknowns: 0,
  });
  assert.ok(r.bandKnobs, 'assessComplexity must attach bandKnobs from mapping');
  assert.equal(r.bandKnobs.skill, 'crucible');
  assert.equal(r.bandKnobs.depth, r.nsDepth);
  assert.equal(
    r.bandKnobs.sharkRounds,
    crucibleKnobs(r.nsDepth, r.nsTier).sharkRounds,
  );
});

test('researchPrime recommend + lock path; unlocked fails closed', () => {
  const rec = recommendResearchPrimeIntake({
    query: 'survey agent harnesses',
    scope: 'large',
    novel: true,
    unknowns: 4,
  });
  assert.ok(isProcessDepthish(rec.depth));
  assert.ok(rec.tier === MODEL_TIERS.HEAVY || rec.tier === MODEL_TIERS.STANDARD);
  assert.ok(rec.rationale.length > 0);

  assert.throws(
    () => resolveResearchPrimeIntakeLock({ inputs: { query: 'x' } }),
    (err) => err.code === 'TRIAGE_UNLOCKED' || err.pending_action === 'confirm-researchprime-triage',
  );

  const locked = resolveResearchPrimeIntakeLock({
    inputs: { query: 'x', scope: 'small', unknowns: 0 },
    gate1Decision: 'APPROVE',
  });
  assert.equal(locked.lock.locked, true);
  assert.ok(locked.knobs);
  assert.equal(locked.knobs.skill, RESEARCHPRIME_SKILL_ID);
  assert.equal(getLockedBand(locked.lock).depth, locked.lock.depth);
});

function isProcessDepthish(d) {
  // SPIKE is the B3 first-class pin; SPIKE-FIRST remains a legacy accepted form.
  return d === 'FULL' || d === 'LITE' || d === 'SPIKE' || d === 'SPIKE-FIRST';
}

test('intake extension payload carries both axes + knobs; APPROVE locks', () => {
  const inputs = { query: 'map the problem space', scope: 'medium', unknowns: 2 };
  const advisory = buildResearchPrimeIntakeExtension(inputs);
  assert.equal(advisory.skill, 'researchPrime');
  assert.equal(advisory.stamp, NS01_WAVE5_STAMP);
  assert.equal(advisory.locked, false);
  assert.ok(advisory.recommendation.tier);
  assert.ok(advisory.recommendation.depth);
  assert.ok(advisory.knobs.maxRounds != null);

  const finalized = finalizeIntakeExtensionOnGate1(advisory, 'APPROVE', inputs);
  assert.equal(finalized.locked, true);
  assert.ok(finalized.triage);
  assert.equal(finalized.triage.locked, true);
  assert.equal(finalized.triage.tier, finalized.recommendation.tier);
  assert.equal(finalized.triage.depth, finalized.recommendation.depth);
  assert.equal(finalized.knobs.skill, 'researchPrime');
  // Knobs match locked band from mapping.
  assert.equal(
    finalized.knobs.maxRounds,
    researchPrimeKnobs(finalized.triage.depth, finalized.triage.tier).maxRounds,
  );
});

test('headless unlocked HALTs; headless with config lock proceeds', () => {
  assert.throws(
    () =>
      buildResearchPrimeIntakeExtension(
        { query: 'x' },
        { headless: true, requireLock: true },
      ),
    (err) =>
      err.code === 'TRIAGE_HEADLESS_UNLOCKED' ||
      err.code === 'TRIAGE_UNLOCKED' ||
      err.name === 'TriageHeadlessHaltError',
  );

  const lock = createLockRecord({
    tier: 'Standard',
    depth: 'LITE',
    rationale: 'headless config lock for RP',
    source: 'config',
  });
  const ext = buildResearchPrimeIntakeExtension(
    { query: 'small fix' },
    { headless: true, triageLock: lock, requireLock: true },
  );
  assert.equal(ext.locked, true);
  assert.equal(ext.triage.depth, DEPTH_BANDS.LITE);
  assert.equal(ext.knobs.maxRounds, researchPrimeKnobs(DEPTH_BANDS.LITE).maxRounds);
});

test('governance.mjs byte-identity vs Wave-5 baseline pin (diff assert)', () => {
  assert.ok(existsSync(baselinePath), 'baseline fixture must exist');
  const baseline = normalizeEol(readFileSync(baselinePath, 'utf8'));
  const baselineHash = sha256(baseline);

  // Pin must not contain Wave-5 stamps (governance is pre-Wave-5 core).
  assert.doesNotMatch(baseline, /NS01_WAVE5|ns01-w5/);
  assert.match(baseline, /bin\/governance\.mjs/);
  assert.match(baseline, /CURRENT_SCHEMA_VERSION/);

  const livePaths = [
    '<path>',
    'C:\\Users\\john\\.claude\\skills\\researchprime\\bin\\governance.mjs',
  ];
  let checked = 0;
  for (const p of livePaths) {
    if (!existsSync(p)) continue;
    checked += 1;
    const live = normalizeEol(readFileSync(p, 'utf8'));
    assert.equal(
      sha256(live),
      baselineHash,
      `${p} must be byte-identical (LF-normalized) to Wave-5 governance baseline`,
    );
    assert.equal(live, baseline, `${p} content must match baseline pin`);
  }
  assert.ok(checked >= 1, 'expected at least one live researchPrime governance.mjs');
});

test('Wave-5 sources never import governance.mjs (intake-only contract)', () => {
  const wire = readFileSync(join(pkgRoot, 'researchprime-wire.mjs'), 'utf8');
  const mapping = readFileSync(join(pkgRoot, 'mapping.mjs'), 'utf8');
  assert.doesNotMatch(wire, /governance\.mjs/);
  assert.doesNotMatch(mapping, /governance\.mjs/);
  assert.match(wire, /intake extension|intake-only|extension payload/i);
  assert.match(wire, /NS01_WAVE5_STAMP/);

  // Live intake must import the wire and must not import governance.
  const intakeCandidates = [
    '<path>',
    'C:\\Users\\john\\.claude\\skills\\researchprime\\bin\\intake.mjs',
  ];
  let checked = 0;
  for (const p of intakeCandidates) {
    if (!existsSync(p)) continue;
    checked += 1;
    const src = readFileSync(p, 'utf8');
    assert.match(src, /researchprime-wire\.mjs/, `${p} must import researchprime-wire`);
    assert.match(src, /buildResearchPrimeIntakeExtension/, `${p} must call extension builder`);
    assert.doesNotMatch(src, /from ['"].*governance\.mjs['"]/, `${p} must not import governance`);
    assert.match(src, /extension/, `${p} must write extension payload`);
  }
  assert.ok(checked >= 1, 'expected at least one live researchPrime intake.mjs');
});

test('public surface + package gate include Wave-5 modules', () => {
  const index = readFileSync(join(pkgRoot, 'index.mjs'), 'utf8');
  assert.match(index, /mapping\.mjs/);
  assert.match(index, /researchprime-wire/);
  assert.match(index, /NS01_WAVE5_STAMP/);
  assert.match(index, /knobsForSkill|researchPrimeKnobs/);

  const pkg = JSON.parse(readFileSync(join(pkgRoot, 'package.json'), 'utf8'));
  assert.ok(
    String(pkg.scripts?.test || '').includes('rp-intake-mapping.test.mjs'),
    'package test script must include Wave-5 rp-intake-mapping tests',
  );
});

test('recommend still single source — mapping does not re-triage', () => {
  const rec = recommend({ intent: 'tiny doc tweak', scope: 'small', unknowns: 0 });
  const knobs = researchPrimeKnobs(rec.depth, rec.tier);
  assert.ok(knobs);
  // Mapping has no recommend import path that re-implements rubric.
  const mappingSrc = readFileSync(join(pkgRoot, 'mapping.mjs'), 'utf8');
  assert.doesNotMatch(mappingSrc, /export function recommend/);
  assert.match(mappingSrc, /from '\.\/core\.mjs'/);
});
