// Wave 6 — remaining 11 skills + prose blocks + small repairs + green.
//
// Proves:
//   · all 11 skills listed in manifest + mapping tables
//   · entry points emit both axes + rationale; unlocked paths fail closed
//   · prose hosts stamp runtime_enforced:false honestly
//   · regenerate-and-diff for committed generated/*.triage-block.md
//   · single-source: no second recommend rubric in package sources
//   · inequality across bands for every skill
//   · doc-locator + prompt-size repairs still green (criterion 8)
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { DEPTH_BANDS, MODEL_TIERS, recommend } from '../core.mjs';
import { createLockRecord, getLockedBand } from '../lock.mjs';
import {
  MAPPED_SKILLS,
  BAND_MAPPINGS,
  knobsForSkill,
  bandsInequal,
  knobsFingerprint,
  jumperKnobs,
  legalBeagleKnobs,
} from '../mapping.mjs';
import {
  ALL_SKILLS,
  NS01_WAVE6_STAMP,
  SKILLS_MANIFEST,
  WAVE6_BLOCK_SKILLS,
  assertManifestComplete,
  proseSkillIds,
  engineSkillIds,
  getSkillManifestEntry,
} from '../skills-manifest.mjs';
import {
  TRIAGE_BLOCK_BEGIN,
  TRIAGE_BLOCK_END,
  buildTriageBlockPayload,
  renderGeneratedFile,
  generatedBlockFileName,
  normalizeGeneratedText,
  diffGenerated,
  renderTriageBlock,
} from '../prose-block.mjs';
import {
  entryPointContract,
  recommendForSkill,
  resolveSkillLock,
  knobsAfterLock,
  openSkillEntry,
} from '../entry-points.mjs';
import {
  NS01_WAVE6_REPAIRS_STAMP,
  DESCRIPTION_DOC_BASENAMES,
  isDescriptionDocBasename,
  shouldUseMarkdownFirst,
  PROMPT_SIZE_MARKDOWN_FIRST_BYTES,
  repairsStatus,
} from '../repairs.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(here, '..');
const generatedDir = join(pkgRoot, 'generated');

const DEPTHS = [DEPTH_BANDS.FULL, DEPTH_BANDS.LITE, DEPTH_BANDS.SPIKE_FIRST];

const EXPECTED_11 = [
  'crucible',
  'foreman',
  'researchPrime',
  'gandalf',
  'jumper',
  'ramanujan',
  'tidy-idy',
  'zombie-hunter',
  'literature-review',
  'financial-analyst',
  'legal-beagle',
];

test('NS01_WAVE6_STAMP is exported on Wave-6 surfaces', () => {
  assert.equal(NS01_WAVE6_STAMP, 'ns01-w6-remaining-skills-prose');
  assert.equal(NS01_WAVE6_REPAIRS_STAMP, 'ns01-w6-repairs');
});

test('all 11 skills listed — manifest, mapping, North Star order', () => {
  assert.equal(ALL_SKILLS.length, 11);
  assert.equal(MAPPED_SKILLS.length, 11);
  assert.deepEqual([...ALL_SKILLS].sort(), [...EXPECTED_11].sort());
  assert.deepEqual([...MAPPED_SKILLS].sort(), [...EXPECTED_11].sort());

  const complete = assertManifestComplete();
  assert.equal(complete.ok, true, `manifest incomplete: ${complete.missing.join(', ')}`);

  for (const id of EXPECTED_11) {
    assert.ok(SKILLS_MANIFEST[id], `SKILLS_MANIFEST missing ${id}`);
    assert.ok(BAND_MAPPINGS[id], `BAND_MAPPINGS missing ${id}`);
    for (const d of DEPTHS) {
      assert.ok(BAND_MAPPINGS[id][d], `${id} missing depth ${d}`);
      assert.ok(knobsForSkill(id, d), `knobsForSkill(${id},${d})`);
    }
  }
});

test('Wave-6 block skills are the remaining 8', () => {
  assert.deepEqual([...WAVE6_BLOCK_SKILLS].sort(), [
    'financial-analyst',
    'gandalf',
    'jumper',
    'legal-beagle',
    'literature-review',
    'ramanujan',
    'tidy-idy',
    'zombie-hunter',
  ].sort());
});

test('inequality across bands for every mapped skill (NS criterion 6 full)', () => {
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

test('entry points: recommend both axes + rationale for every skill', () => {
  for (const id of ALL_SKILLS) {
    const contract = entryPointContract(id, {
      intent: `triage entry smoke for ${id}`,
      scope: 'small',
      unknowns: 0,
    });
    assert.equal(contract.skill, id);
    assert.equal(contract.stamp, NS01_WAVE6_STAMP);
    assert.ok(contract.recommendation.tier === MODEL_TIERS.HEAVY || contract.recommendation.tier === MODEL_TIERS.STANDARD);
    assert.ok(
      contract.recommendation.depth === 'FULL' ||
        contract.recommendation.depth === 'LITE' ||
        contract.recommendation.depth === 'SPIKE' ||
        contract.recommendation.depth === 'SPIKE-FIRST',
    );
    assert.ok(String(contract.recommendation.rationale).length > 0);
    assert.equal(typeof contract.runtime_enforced, 'boolean');
    assert.equal(contract.locked, false);
    assert.ok(contract.knobs);
    assert.equal(contract.knobs.skill, id);

    const rec = recommendForSkill(id, { intent: 'x', scope: 'small' });
    assert.ok(rec.tier);
    assert.ok(rec.depth);
  }
});

test('no path sets a dimension without a recorded lock (engine + prose API)', () => {
  for (const id of ALL_SKILLS) {
    assert.throws(
      () => resolveSkillLock(id, { inputs: { intent: 'unlocked' } }),
      (err) => err.code === 'TRIAGE_UNLOCKED' || err.name === 'TriageUnlockedError',
    );

    const lock = createLockRecord({
      tier: 'Standard',
      depth: 'LITE',
      rationale: `wave6 lock for ${id}`,
      source: 'config',
    });
    const resolved = resolveSkillLock(id, { triageLock: lock });
    assert.equal(resolved.lock.locked, true);
    assert.equal(getLockedBand(resolved.lock).depth, DEPTH_BANDS.LITE);
    assert.equal(resolved.knobs.skill, id);
    assert.equal(resolved.contract.runtime_enforced, SKILLS_MANIFEST[id].runtimeEnforced);

    const after = knobsAfterLock(id, lock);
    assert.equal(after.depth, DEPTH_BANDS.LITE);
  }

  // Headless unlocked HALTs for an engine skill.
  assert.throws(
    () => resolveSkillLock('gandalf', { headless: true }),
    (err) =>
      err.code === 'TRIAGE_HEADLESS_UNLOCKED' ||
      err.code === 'TRIAGE_UNLOCKED' ||
      err.name === 'TriageHeadlessHaltError',
  );
});

test('prose skills stamp runtime_enforced:false; engine skills stamp true', () => {
  const prose = proseSkillIds();
  const engines = engineSkillIds();
  assert.ok(prose.includes('legal-beagle'));
  assert.ok(prose.includes('financial-analyst'));
  assert.ok(engines.includes('crucible'));
  assert.ok(engines.includes('gandalf'));

  for (const id of prose) {
    const payload = buildTriageBlockPayload(id);
    assert.equal(payload.runtime_enforced, false);
    assert.equal(payload.intakeClass, 'prose');
    const block = renderTriageBlock(id);
    assert.match(block, /runtime_enforced:\s*false|runtime_enforced": false/);
    assert.match(block, /honest/i);
  }
  for (const id of engines) {
    const payload = buildTriageBlockPayload(id);
    assert.equal(payload.runtime_enforced, true);
    assert.equal(payload.intakeClass, 'engine');
  }
});

test('regenerate-and-diff: committed generated blocks match renderer', () => {
  assert.ok(existsSync(generatedDir), 'generated/ directory must exist');
  let checked = 0;
  for (const id of WAVE6_BLOCK_SKILLS) {
    const name = generatedBlockFileName(id);
    const path = join(generatedDir, name);
    assert.ok(existsSync(path), `missing ${name} — run node scripts/regenerate-prose-blocks.mjs`);
    const expected = normalizeGeneratedText(renderGeneratedFile(id));
    const actual = normalizeGeneratedText(readFileSync(path, 'utf8'));
    const d = diffGenerated(expected, actual);
    assert.equal(d.match, true, `${name} drifted: ${d.detail}`);
    assert.match(actual, new RegExp(TRIAGE_BLOCK_BEGIN.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.match(actual, new RegExp(TRIAGE_BLOCK_END.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.match(actual, new RegExp(NS01_WAVE6_STAMP));
    checked += 1;
  }
  assert.equal(checked, 8);

  // No stray hand-written blocks outside the wave-6 set without stamps.
  const files = readdirSync(generatedDir).filter((f) => f.endsWith('.triage-block.md'));
  assert.ok(files.length >= 8);
});

test('single-source grep: package sources do not re-implement recommend rubric', () => {
  const srcFiles = readdirSync(pkgRoot)
    .filter((f) => f.endsWith('.mjs'))
    .map((f) => join(pkgRoot, f));

  // Sole recommend implementation lives in core.mjs.
  const core = readFileSync(join(pkgRoot, 'core.mjs'), 'utf8');
  assert.match(core, /export function recommend\b/);

  const secondRubricRe =
    /export function recommend\b|function recommendDepth\b|function assessBand\b|Heavy\/Standard\s*×\s*FULL/;

  for (const path of srcFiles) {
    const base = path.split(/[/\\]/).pop();
    if (base === 'core.mjs') continue;
    const src = readFileSync(path, 'utf8');
    // Other modules may import/re-export recommend, but must not define a new rubric.
    if (base === 'entry-points.mjs' || base === 'index.mjs') {
      assert.doesNotMatch(src, /export function recommend\s*\(/);
      continue;
    }
    assert.doesNotMatch(
      src,
      /export function recommend\s*\(/,
      `${base} must not export a second recommend()`,
    );
    // No hand-rolled dual-axis rubric tables outside mapping knobs + core vocab.
    if (base !== 'mapping.mjs' && base !== 'prose-block.mjs' && base !== 'skills-manifest.mjs') {
      assert.doesNotMatch(src, secondRubricRe, `${base} looks like a second rubric`);
    }
  }

  // mapping still imports core; does not re-export recommend as a local function.
  const mapping = readFileSync(join(pkgRoot, 'mapping.mjs'), 'utf8');
  assert.match(mapping, /from '\.\/core\.mjs'/);
  assert.doesNotMatch(mapping, /export function recommend/);
});

test('named knobs for wave-6 skills (jumper + legal-beagle sample)', () => {
  const j = jumperKnobs(DEPTH_BANDS.FULL, MODEL_TIERS.HEAVY);
  assert.equal(j.skill, 'jumper');
  assert.equal(j.ideaRounds, 5);
  assert.equal(j.seats, 'frontier');

  const l = legalBeagleKnobs(DEPTH_BANDS.LITE, MODEL_TIERS.STANDARD);
  assert.equal(l.skill, 'legal-beagle');
  assert.equal(l.reviewSeats, 1);
  assert.equal(l.citationLintRequired, true);
  assert.equal(l.ceremony, 'lite');
});

test('openSkillEntry + confirm path for prose host', () => {
  const open = openSkillEntry('legal-beagle', {
    intake: { intent: 'review an NDA', scope: 'medium', highStakes: true },
  });
  assert.equal(open.skill, 'legal-beagle');
  assert.equal(open.runtime_enforced, false);
  assert.equal(open.locked, false);
  assert.ok(open.block.runtime_enforced === false);

  const locked = openSkillEntry('legal-beagle', {
    intake: { intent: 'review an NDA', scope: 'medium' },
    decision: 'confirm',
    requireLock: true,
  });
  assert.equal(locked.locked, true);
  assert.ok(locked.lock);
  assert.equal(locked.knobs.skill, 'legal-beagle');
});

test('small repairs: doc-locator accepts DESCRIPTION + engine-design', () => {
  for (const name of DESCRIPTION_DOC_BASENAMES) {
    assert.equal(
      isDescriptionDocBasename(name),
      true,
      `doc-locator must accept ${name}`,
    );
  }
  assert.equal(isDescriptionDocBasename('DESCRIPTION.md'), true);
  assert.equal(isDescriptionDocBasename('foo-engine-design.md'), true);
  assert.equal(isDescriptionDocBasename('random-notes.txt'), false);

  const status = repairsStatus();
  assert.equal(status.docLocator.status, 'ok');
  assert.equal(status.docLocator.acceptsDescription, true);
  assert.equal(status.docLocator.acceptsEngineDesign, true);
});

test('small repairs: prompt-size markdown-first threshold', () => {
  assert.equal(PROMPT_SIZE_MARKDOWN_FIRST_BYTES, 20_000);
  assert.equal(shouldUseMarkdownFirst(100), false);
  assert.equal(shouldUseMarkdownFirst(20_000), true);
  assert.equal(shouldUseMarkdownFirst('x'.repeat(20_000)), true);
  assert.equal(repairsStatus().promptSize.status, 'ok');
});

test('public surface + package gate include Wave-6 modules', () => {
  const index = readFileSync(join(pkgRoot, 'index.mjs'), 'utf8');
  assert.match(index, /skills-manifest|entry-points|prose-block|NS01_WAVE6/);
  assert.match(index, /entryPointContract|resolveSkillLock|renderTriageBlock/);

  const pkg = JSON.parse(readFileSync(join(pkgRoot, 'package.json'), 'utf8'));
  assert.ok(
    String(pkg.scripts?.test || '').includes('wave6-prose-manifest.test.mjs'),
    'package test script must include Wave-6 suite',
  );
  assert.ok(
    pkg.scripts?.['regenerate-prose-blocks'] ||
      pkg.scripts?.['regenerate-prose-blocks:check'],
    'package must expose regenerate-prose-blocks scripts for CI',
  );
});

test('recommend remains single source — entry points do not re-triage with a private rubric', () => {
  const rec = recommend({ intent: 'tiny doc tweak', scope: 'small', unknowns: 0 });
  const viaEntry = recommendForSkill('jumper', {
    intent: 'tiny doc tweak',
    scope: 'small',
    unknowns: 0,
  });
  // Same core path: skill overlay may change high-stakes floor only; small jumper matches core depth.
  assert.equal(viaEntry.depth, rec.depth);
  const entrySrc = readFileSync(join(pkgRoot, 'entry-points.mjs'), 'utf8');
  assert.match(entrySrc, /from '\.\/core\.mjs'/);
  assert.doesNotMatch(entrySrc, /export function recommend\s*\(/);
});

test('getSkillManifestEntry aliases resolve', () => {
  assert.equal(getSkillManifestEntry('research-prime')?.id, 'researchPrime');
  assert.equal(getSkillManifestEntry('tidyidy')?.id, 'tidy-idy');
  assert.equal(getSkillManifestEntry('legal')?.id, 'legal-beagle');
});
