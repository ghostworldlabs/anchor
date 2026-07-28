// Track B4 / W4 — Prose drift parity for ramanujan (sibling to wave6-prose-manifest).
//
// Proves:
//   · generated/ramanujan.triage-block.md knobsByDepth matches live BAND_MAPPINGS.ramanujan
//     (verifyArms + certifier per depth)
//   · regenerate-and-diff: committed block === renderGeneratedFile('ramanujan')
//   · renderer payload + knobsForSkill + resolveRamanujanDepthKnobs stay aligned
//   · SKILL.md embeds or links the generated block; no alternate verifyArms RHS
//
// Hermetic only. Hand-edit of the generated block fails this suite (CI drift).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { BAND_MAPPINGS, knobsForSkill, resolveRamanujanDepthKnobs } from '../mapping.mjs';
import {
  buildTriageBlockPayload,
  renderGeneratedFile,
  generatedBlockFileName,
  normalizeGeneratedText,
  diffGenerated,
} from '../prose-block.mjs';
import {
  B4_RAMANUJAN_SMOKE_STAMP,
  CANONICAL_DEPTHS,
  GENERATED_RAMANUJAN_BLOCK,
  RAMANUJAN_SKILL_MD,
  extractMachinePayloadFromGenerated,
  assertKnobsByDepthMatchesMapping,
  checkProseDrift,
  runB4RamanujanSmoke,
} from './b4-ramanujan-smoke.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = join(here, '..');

test('B4 prose drift: stamp + generated block path present', () => {
  assert.equal(B4_RAMANUJAN_SMOKE_STAMP, 'b4-ramanujan-smoke-green');
  assert.equal(generatedBlockFileName('ramanujan'), 'ramanujan.triage-block.md');
  assert.ok(
    existsSync(GENERATED_RAMANUJAN_BLOCK),
    'missing generated/ramanujan.triage-block.md — run node scripts/regenerate-prose-blocks.mjs',
  );
  assert.ok(BAND_MAPPINGS?.ramanujan, 'live BAND_MAPPINGS.ramanujan required');
});

test('B4 prose drift: renderer knobsByDepth matches live BAND_MAPPINGS.ramanujan', () => {
  const payload = buildTriageBlockPayload('ramanujan');
  assert.equal(payload.skill, 'ramanujan');
  const cmp = assertKnobsByDepthMatchesMapping(payload.knobsByDepth);
  assert.equal(cmp.ok, true, cmp.errors.join('; '));

  for (const depth of CANONICAL_DEPTHS) {
    const row = BAND_MAPPINGS.ramanujan[depth];
    const viaSkill = knobsForSkill('ramanujan', depth);
    const viaSole = resolveRamanujanDepthKnobs(depth);
    assert.equal(viaSkill.verifyArms, row.verifyArms);
    assert.equal(viaSkill.certifier, row.certifier);
    assert.equal(viaSole.verifyArms, row.verifyArms);
    assert.equal(viaSole.certifier, row.certifier);
    assert.equal(payload.knobsByDepth[depth].verifyArms, row.verifyArms);
    assert.equal(payload.knobsByDepth[depth].certifier, row.certifier);
  }
});

test('B4 prose drift: regenerate-and-diff committed ramanujan.triage-block.md', () => {
  const expected = normalizeGeneratedText(renderGeneratedFile('ramanujan'));
  const actual = normalizeGeneratedText(readFileSync(GENERATED_RAMANUJAN_BLOCK, 'utf8'));
  const d = diffGenerated(expected, actual);
  assert.equal(d.match, true, `hand-edit drift: ${d.detail}`);
});

test('B4 prose drift: committed knobsByDepth matches live mapping (hand-edit fails)', () => {
  const onDisk = readFileSync(GENERATED_RAMANUJAN_BLOCK, 'utf8');
  const payload = extractMachinePayloadFromGenerated(onDisk);
  assert.equal(payload.skill, 'ramanujan');
  assert.ok(payload.knobsByDepth && typeof payload.knobsByDepth === 'object');

  const cmp = assertKnobsByDepthMatchesMapping(payload.knobsByDepth);
  assert.equal(cmp.ok, true, cmp.errors.join('; '));

  // Negative shape: if knobsByDepth.verifyArms were hand-edited to a non-mapping
  // value, assertKnobsByDepthMatchesMapping must RED (GWT: hand-edit drift fails).
  const forged = {
    ...payload.knobsByDepth,
    LITE: {
      ...payload.knobsByDepth.LITE,
      verifyArms: 999_001,
    },
  };
  const red = assertKnobsByDepthMatchesMapping(forged);
  assert.equal(red.ok, false);
  assert.ok(red.errors.some((e) => /LITE\.verifyArms/.test(e)));
});

test('B4 prose drift: SKILL.md embeds or links generated block; no alternate verifyArms', () => {
  assert.ok(existsSync(RAMANUJAN_SKILL_MD), 'skills/ramanujan/SKILL.md required');
  const skill = readFileSync(RAMANUJAN_SKILL_MD, 'utf8');
  assert.match(
    skill,
    /ramanujan\.triage-block\.md|generated\/ramanujan\.triage-block|BEGIN NS01-TRIAGE-BLOCK/,
  );
  assert.match(skill, /Process depth|NS-01 triage|Track B4/i);

  const liveArms = new Set(
    CANONICAL_DEPTHS.map((d) => BAND_MAPPINGS.ramanujan[d].verifyArms),
  );
  for (const m of skill.matchAll(/verifyArms\s*[:=]\s*(\d+)/gi)) {
    assert.ok(
      liveArms.has(Number(m[1])),
      `hand-written verifyArms=${m[1]} not in live mapping`,
    );
  }
  for (const m of skill.matchAll(/["']verifyArms["']\s*:\s*(\d+)/gi)) {
    assert.ok(
      liveArms.has(Number(m[1])),
      `hand-written "verifyArms": ${m[1]} not in live mapping`,
    );
  }
});

test('B4 prose drift: checkProseDrift() GREEN (done-when entry)', () => {
  const r = checkProseDrift();
  assert.equal(r.id, 'prose-drift');
  assert.equal(r.ok, true, r.errors.join('; '));
});

test('B4 smoke package wiring: package.json exposes b4-ramanujan-smoke', () => {
  const pkg = JSON.parse(readFileSync(join(pkgRoot, 'package.json'), 'utf8'));
  const testScript = String(pkg.scripts?.test || '');
  const smokeScript = String(
    pkg.scripts?.['b4-ramanujan-smoke'] || pkg.scripts?.['b4-smoke'] || '',
  );
  assert.ok(
    testScript.includes('b4-ramanujan-prose-drift.test.mjs') ||
      testScript.includes('b4-ramanujan-smoke') ||
      smokeScript.includes('b4-ramanujan-smoke'),
    'package must wire prose-drift test and/or b4-ramanujan-smoke script',
  );
  assert.ok(
    smokeScript.includes('b4-ramanujan-smoke') ||
      testScript.includes('b4-ramanujan-smoke'),
    'package must expose node test/b4-ramanujan-smoke.mjs as GREEN entry',
  );
});

test('B4 smoke: runB4RamanujanSmoke exits green (sole Track B4 GREEN entry)', async () => {
  const report = await runB4RamanujanSmoke();
  assert.equal(report.stamp, B4_RAMANUJAN_SMOKE_STAMP);
  assert.equal(report.ok, true, report.errors.join('\n'));
  assert.equal(report.exitCode, 0);
  const ids = report.checks.map((c) => c.id).sort();
  assert.deepEqual(ids, [
    'honesty-label-invariant',
    'knobs-matrix',
    'prose-drift',
    'sole-resolve-inclusion',
    'unlock-refuse',
  ]);
  for (const c of report.checks) {
    assert.equal(c.ok, true, `${c.id}: ${c.errors.join('; ')}`);
  }
});
