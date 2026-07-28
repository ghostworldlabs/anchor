#!/usr/bin/env node
// Track B4 — sole Foreman GREEN smoke entry (Wave 4).
//
// Runs hermetically (no network, no real Lean/z3, no model calls):
//   1. knobs matrix (LITE/FULL/SPIKE + SPIKE aliases vs BAND_MAPPINGS.ramanujan)
//   2. unlock refuse (RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK; certifier never true)
//   3. sole-resolve inclusion (allowlisted certifier-arm modules)
//   4. honesty-law label invariant (LITE vs FULL; labels never thinned)
//   5. prose drift (generated/ramanujan.triage-block.md knobsByDepth ↔ live mapping;
//      regenerate-and-diff; SKILL.md embeds/links block; no mismatched hand-written knobs)
//
// Exit 0 only when every check passes; any fail → non-zero.
//
// Wire: package.json scripts.b4-ramanujan-smoke + scripts.test chain.
// Usage:
//   node test/b4-ramanujan-smoke.mjs
//   node test/b4-ramanujan-smoke.mjs --json

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import process from 'node:process';

import {
  BAND_MAPPINGS,
  resolveRamanujanDepthKnobs,
  assertRamanujanBandInvariants,
  knobsForSkill,
} from '../mapping.mjs';
import {
  buildTriageBlockPayload,
  renderGeneratedFile,
  generatedBlockFileName,
  normalizeGeneratedText,
  diffGenerated,
} from '../prose-block.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
export const TRIAGE_PKG_ROOT = join(__dirname, '..');
export const FOUNDRY_ROOT = join(TRIAGE_PKG_ROOT, '..', '..');
export const RAMANUJAN_ROOT = join(FOUNDRY_ROOT, 'skills', 'ramanujan');
export const RAMANUJAN_SRC_DIR = join(RAMANUJAN_ROOT, 'src');
export const GENERATED_RAMANUJAN_BLOCK = join(
  TRIAGE_PKG_ROOT,
  'generated',
  generatedBlockFileName('ramanujan'),
);
export const RAMANUJAN_SKILL_MD = join(RAMANUJAN_ROOT, 'SKILL.md');

/** Wave-4 surface stamp — sole Track B4 GREEN identity. */
export const B4_RAMANUJAN_SMOKE_STAMP = 'b4-ramanujan-smoke-green';

export const CANONICAL_DEPTHS = Object.freeze(['LITE', 'FULL', 'SPIKE']);
export const SPIKE_ALIASES = Object.freeze(['SPIKE-FIRST', 'SPIKE_FIRST', 'SPIKEFIRST']);

/**
 * Allowlisted production modules that may arm certifier spend (W2 sole-resolve).
 * Each must import/call resolveRamanujanDepthKnobs or resolveRamanujanBand.
 */
export const CERTIFIER_ARM_ALLOWLIST = Object.freeze([
  'triage-band.mjs',
  'proof-auto-certifier.mjs',
  'verify-router.mjs',
  'lean-certifier.mjs',
  'skill-invocation.mjs',
  'orchestrator.mjs',
]);

// ---------------------------------------------------------------------------
// Lazy production imports (ramanujan skill)
// ---------------------------------------------------------------------------

let _bandMod = null;
let _honestyMod = null;

async function loadBandMod() {
  if (_bandMod) return _bandMod;
  const url = pathToFileURL(join(RAMANUJAN_SRC_DIR, 'triage-band.mjs')).href;
  _bandMod = await import(url);
  return _bandMod;
}

async function loadHonestyMod() {
  if (_honestyMod) return _honestyMod;
  const url = pathToFileURL(join(RAMANUJAN_SRC_DIR, 'honesty-label-invariant.mjs')).href;
  _honestyMod = await import(url);
  return _honestyMod;
}

/**
 * Read production module source under skills/ramanujan/src.
 * @param {string} basename
 * @returns {string}
 */
export function readRamanujanSrc(basename) {
  return readFileSync(join(RAMANUJAN_SRC_DIR, basename), 'utf8');
}

// ---------------------------------------------------------------------------
// Check helpers — each returns { id, ok, detail, errors: string[] }
// ---------------------------------------------------------------------------

/**
 * @param {string} id
 * @param {boolean} ok
 * @param {string} detail
 * @param {string[]} [errors]
 */
function result(id, ok, detail, errors = []) {
  return Object.freeze({ id, ok, detail, errors: Object.freeze(errors.slice()) });
}

/**
 * 1. Knobs matrix — locked LITE/FULL/SPIKE (+ SPIKE aliases) deep-equal live mapping;
 *    LITE leaner; FULL/SPIKE certifier true when locked.
 */
export function checkKnobsMatrix() {
  const errors = [];
  try {
    assertRamanujanBandInvariants(BAND_MAPPINGS.ramanujan);
  } catch (err) {
    errors.push(`band invariants: ${err?.message || err}`);
  }

  for (const depth of CANONICAL_DEPTHS) {
    const row = BAND_MAPPINGS.ramanujan[depth];
    if (!row) {
      errors.push(`missing BAND_MAPPINGS.ramanujan.${depth}`);
      continue;
    }
    try {
      const resolved = resolveRamanujanDepthKnobs(depth);
      if (!Object.isFrozen(resolved)) {
        errors.push(`${depth}: resolveRamanujanDepthKnobs result not frozen`);
      }
      if (resolved.depth !== depth) {
        errors.push(`${depth}: resolved.depth=${resolved.depth}`);
      }
      if (resolved.verifyArms !== row.verifyArms) {
        errors.push(
          `${depth}: verifyArms live=${resolved.verifyArms} mapping=${row.verifyArms}`,
        );
      }
      if (resolved.certifier !== row.certifier) {
        errors.push(
          `${depth}: certifier live=${resolved.certifier} mapping=${row.certifier}`,
        );
      }
    } catch (err) {
      errors.push(`${depth}: resolve threw ${err?.message || err}`);
    }
  }

  for (const alias of SPIKE_ALIASES) {
    try {
      const resolved = resolveRamanujanDepthKnobs(alias);
      const spike = BAND_MAPPINGS.ramanujan.SPIKE;
      if (resolved.depth !== 'SPIKE') {
        errors.push(`alias ${alias}: depth=${resolved.depth} (want SPIKE)`);
      }
      if (resolved.verifyArms !== spike.verifyArms || resolved.certifier !== spike.certifier) {
        errors.push(`alias ${alias}: knobs do not match SPIKE row`);
      }
    } catch (err) {
      errors.push(`alias ${alias}: ${err?.message || err}`);
    }
  }

  try {
    const lite = resolveRamanujanDepthKnobs('LITE');
    const full = resolveRamanujanDepthKnobs('FULL');
    const spike = resolveRamanujanDepthKnobs('SPIKE');
    if (lite.certifier !== false) errors.push('LITE.certifier must be false');
    if (!(lite.verifyArms < full.verifyArms)) {
      errors.push(
        `LITE.verifyArms < FULL.verifyArms required (live ${lite.verifyArms} < ${full.verifyArms})`,
      );
    }
    if (full.certifier !== true) errors.push('FULL.certifier must be true when locked');
    if (spike.certifier !== true) errors.push('SPIKE.certifier must be true when locked');
  } catch (err) {
    errors.push(`SC2/SC3 live asserts: ${err?.message || err}`);
  }

  return result(
    'knobs-matrix',
    errors.length === 0,
    errors.length === 0
      ? 'LITE/FULL/SPIKE (+aliases) match BAND_MAPPINGS.ramanujan; LITE leaner'
      : `${errors.length} knobs-matrix error(s)`,
    errors,
  );
}

/**
 * 2. Unlock refuse — no depth lock → RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK.
 * @param {{ resolveRamanujanBand: Function, RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK: string, isCertifierArmed: Function }} band
 */
export function checkUnlockRefuse(band) {
  const errors = [];
  const {
    resolveRamanujanBand,
    RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK,
    isCertifierArmed,
  } = band;

  const expectThrow = (label, fn) => {
    try {
      const out = fn();
      errors.push(
        `${label}: expected throw ${RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK}; got ${JSON.stringify(out)}`,
      );
      if (out && (out.certifier === true || out.certifierEnabled === true)) {
        errors.push(`${label}: returned certifier true without lock`);
      }
    } catch (err) {
      if (!err || err.code !== RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK) {
        errors.push(
          `${label}: wrong code ${err?.code || err?.name || err} (want ${RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK})`,
        );
      }
      if (err && (err.certifier === true || err.band?.certifier === true)) {
        errors.push(`${label}: error smuggled certifier true`);
      }
    }
  };

  expectThrow('empty env', () => resolveRamanujanBand({ env: {} }));
  expectThrow('empty opts', () => resolveRamanujanBand({}));
  expectThrow('tier env only', () =>
    resolveRamanujanBand({
      env: { RAMANUJAN_TIER: 'Heavy', FOUNDRY_TRIAGE_TIER: 'Heavy' },
    }),
  );

  if (isCertifierArmed(null) !== false) errors.push('isCertifierArmed(null) must be false');
  if (isCertifierArmed({}) !== false) errors.push('isCertifierArmed({}) must be false');
  if (isCertifierArmed({ certifier: false }) !== false) {
    errors.push('isCertifierArmed({certifier:false}) must be false');
  }

  return result(
    'unlock-refuse',
    errors.length === 0,
    errors.length === 0
      ? 'unlocked paths throw RAMANUJAN_CERTIFIER_REQUIRES_DEPTH_LOCK; certifier never true'
      : `${errors.length} unlock-refuse error(s)`,
    errors,
  );
}

/**
 * Structural sole-resolve inclusion for one allowlisted module.
 * @param {string} basename
 * @returns {{ basename: string, viaBand: boolean, viaDepthKnobs: boolean }}
 */
export function assertSoleResolveInclusion(basename) {
  const src = readRamanujanSrc(basename);
  if (basename === 'triage-band.mjs') {
    const definesBand = /export\s+function\s+resolveRamanujanBand\b/.test(src);
    const callsDepthKnobs = /resolveRamanujanDepthKnobs\s*\(/.test(src);
    const noKnobsForSkillArm =
      !/knobsForSkill\s*\(\s*['"]ramanujan['"]/.test(src) &&
      !/ramanujanKnobs\s*\(/.test(src);
    if (!definesBand || !callsDepthKnobs) {
      const err = new Error(
        `triage-band.mjs must define resolveRamanujanBand and call resolveRamanujanDepthKnobs`,
      );
      err.code = 'SOLE_RESOLVE_INCLUSION';
      throw err;
    }
    if (!noKnobsForSkillArm) {
      const err = new Error(
        `triage-band.mjs must not arm via knobsForSkill/ramanujanKnobs at production resolve`,
      );
      err.code = 'SOLE_RESOLVE_INCLUSION';
      throw err;
    }
    return { basename, viaBand: true, viaDepthKnobs: true };
  }

  const importsTriageBand = /from\s+['"]\.\/triage-band\.mjs['"]/.test(src);
  const namesDepth = /resolveRamanujanDepthKnobs/.test(src) && importsTriageBand;
  const namesBand = /resolveRamanujanBand/.test(src) && importsTriageBand;
  if (!namesDepth && !namesBand) {
    const err = new Error(
      `${basename} must import resolveRamanujanDepthKnobs or resolveRamanujanBand from ./triage-band.mjs`,
    );
    err.code = 'SOLE_RESOLVE_INCLUSION';
    throw err;
  }
  if (/knobsForSkill\s*\(\s*['"]ramanujan['"]/.test(src)) {
    const err = new Error(
      `${basename} must not call knobsForSkill('ramanujan', …) — sole path is resolveRamanujanDepthKnobs`,
    );
    err.code = 'SOLE_RESOLVE_INCLUSION';
    throw err;
  }
  return { basename, viaBand: namesBand, viaDepthKnobs: namesDepth };
}

/**
 * 3. Sole-resolve inclusion on allowlisted certifier-arm modules.
 * @param {{ resolveRamanujanBand: Function, resolveRamanujanDepthKnobs: Function }} band
 */
export function checkSoleResolveInclusion(band) {
  const errors = [];
  if (!existsSync(RAMANUJAN_SRC_DIR)) {
    errors.push(`skills/ramanujan/src missing at ${RAMANUJAN_SRC_DIR}`);
    return result('sole-resolve-inclusion', false, 'ramanujan src missing', errors);
  }

  for (const basename of CERTIFIER_ARM_ALLOWLIST) {
    const path = join(RAMANUJAN_SRC_DIR, basename);
    if (!existsSync(path)) {
      errors.push(`allowlisted module missing: ${basename}`);
      continue;
    }
    try {
      const r = assertSoleResolveInclusion(basename);
      if (!r.viaBand && !r.viaDepthKnobs) {
        errors.push(`${basename}: neither viaBand nor viaDepthKnobs`);
      }
    } catch (err) {
      errors.push(`${basename}: ${err?.message || err}`);
    }
  }

  // Adapter body exclusivity
  try {
    const src = readRamanujanSrc('triage-band.mjs');
    if (!/const resolved = resolveRamanujanDepthKnobs\s*\(/.test(src)) {
      errors.push('triage-band.mjs must assign resolveRamanujanDepthKnobs result exclusively');
    }
    if (/knobsForSkill\s*\(\s*['"]ramanujan['"]/.test(src)) {
      errors.push('triage-band.mjs must not call knobsForSkill(\'ramanujan\')');
    }
  } catch (err) {
    errors.push(`triage-band body check: ${err?.message || err}`);
  }

  // Live exclusive path
  try {
    const b = band.resolveRamanujanBand({ depth: 'FULL', env: {} });
    const direct = resolveRamanujanDepthKnobs('FULL');
    if (
      b.resolved.verifyArms !== direct.verifyArms ||
      b.resolved.certifier !== direct.certifier ||
      b.resolved.depth !== direct.depth
    ) {
      errors.push('resolveRamanujanBand.resolved must equal resolveRamanujanDepthKnobs(FULL)');
    }
  } catch (err) {
    errors.push(`live exclusive path: ${err?.message || err}`);
  }

  return result(
    'sole-resolve-inclusion',
    errors.length === 0,
    errors.length === 0
      ? `allowlist (${CERTIFIER_ARM_ALLOWLIST.length}) routes via sole resolve`
      : `${errors.length} sole-resolve error(s)`,
    errors,
  );
}

/**
 * 4. Honesty-law label invariant (W3).
 * @param {{ runHonestyLabelInvariant: Function }} honesty
 */
export function checkHonestyLabelInvariant(honesty) {
  const errors = [];
  try {
    const r = honesty.runHonestyLabelInvariant();
    if (!r || r.ok !== true) {
      errors.push('runHonestyLabelInvariant did not return { ok: true }');
    }
    if (r?.lite?.knobs?.certifier !== false) {
      errors.push('LITE knobs.certifier must be false under label invariant');
    }
    if (!(r?.lite?.knobs?.verifyArms < r?.full?.knobs?.verifyArms)) {
      errors.push('label invariant: LITE.verifyArms must be < FULL.verifyArms');
    }
    if (!r?.liteInvoke?.stamps?.length || !r?.fullInvoke?.stamps?.length) {
      errors.push('label invariant: invokeSkill stamps missing under LITE or FULL');
    }
  } catch (err) {
    errors.push(`runHonestyLabelInvariant: ${err?.message || err}`);
  }
  return result(
    'honesty-label-invariant',
    errors.length === 0,
    errors.length === 0
      ? 'LITE vs FULL honesty-law labels present/non-empty; only knobs differ'
      : `${errors.length} honesty-label error(s)`,
    errors,
  );
}

/**
 * Extract machine payload JSON from a generated triage-block.md body.
 * @param {string} md
 * @returns {object}
 */
export function extractMachinePayloadFromGenerated(md) {
  const text = normalizeGeneratedText(md);
  // Prefer the Machine payload fenced block (full knobsByDepth).
  const re =
    /Machine payload \(regenerate-and-diff\)[\s\S]*?```json\n([\s\S]*?)\n```/;
  const m = text.match(re);
  if (!m) {
    const err = new Error(
      'generated ramanujan.triage-block.md missing Machine payload JSON fence',
    );
    err.code = 'PROSE_DRIFT';
    throw err;
  }
  try {
    return JSON.parse(m[1]);
  } catch (e) {
    const err = new Error(
      `generated ramanujan.triage-block.md Machine payload JSON parse failed: ${e?.message || e}`,
    );
    err.code = 'PROSE_DRIFT';
    throw err;
  }
}

/**
 * Compare knobsByDepth slice (verifyArms, certifier) to live BAND_MAPPINGS.ramanujan.
 * @param {object} knobsByDepth
 * @param {Readonly<Record<string, Readonly<object>>>} [table]
 * @returns {{ ok: boolean, errors: string[] }}
 */
export function assertKnobsByDepthMatchesMapping(
  knobsByDepth,
  table = BAND_MAPPINGS.ramanujan,
) {
  const errors = [];
  if (!knobsByDepth || typeof knobsByDepth !== 'object') {
    return { ok: false, errors: ['knobsByDepth missing or not an object'] };
  }
  for (const depth of CANONICAL_DEPTHS) {
    const live = table[depth];
    const prose = knobsByDepth[depth];
    if (!live) {
      errors.push(`BAND_MAPPINGS.ramanujan.${depth} missing`);
      continue;
    }
    if (!prose || typeof prose !== 'object') {
      errors.push(`knobsByDepth.${depth} missing`);
      continue;
    }
    if (prose.verifyArms !== live.verifyArms) {
      errors.push(
        `knobsByDepth.${depth}.verifyArms=${prose.verifyArms} ≠ mapping ${live.verifyArms}`,
      );
    }
    if (prose.certifier !== live.certifier) {
      errors.push(
        `knobsByDepth.${depth}.certifier=${prose.certifier} ≠ mapping ${live.certifier}`,
      );
    }
  }
  return { ok: errors.length === 0, errors };
}

/**
 * 5. Prose drift parity — generated block + renderer payload + SKILL.md honesty.
 */
export function checkProseDrift() {
  const errors = [];

  // Live load-or-init invariants still hold
  try {
    assertRamanujanBandInvariants(BAND_MAPPINGS.ramanujan);
  } catch (err) {
    errors.push(`mapping invariants: ${err?.message || err}`);
  }

  // Renderer payload knobsByDepth ↔ live mapping (verifyArms/certifier)
  try {
    const payload = buildTriageBlockPayload('ramanujan');
    const cmp = assertKnobsByDepthMatchesMapping(payload.knobsByDepth);
    if (!cmp.ok) errors.push(...cmp.errors.map((e) => `renderer payload: ${e}`));
    // knobsForSkill path must agree too (sole table)
    for (const depth of CANONICAL_DEPTHS) {
      const k = knobsForSkill('ramanujan', depth);
      const row = BAND_MAPPINGS.ramanujan[depth];
      if (!k || k.verifyArms !== row.verifyArms || k.certifier !== row.certifier) {
        errors.push(
          `knobsForSkill('ramanujan',${depth}) drifted from BAND_MAPPINGS.ramanujan`,
        );
      }
      const resolved = resolveRamanujanDepthKnobs(depth);
      if (
        resolved.verifyArms !== row.verifyArms ||
        resolved.certifier !== row.certifier
      ) {
        errors.push(
          `resolveRamanujanDepthKnobs(${depth}) drifted from BAND_MAPPINGS.ramanujan`,
        );
      }
    }
  } catch (err) {
    errors.push(`renderer payload: ${err?.message || err}`);
  }

  // Committed generated file present + regenerate-and-diff
  if (!existsSync(GENERATED_RAMANUJAN_BLOCK)) {
    errors.push(
      `missing ${generatedBlockFileName('ramanujan')} — run node scripts/regenerate-prose-blocks.mjs`,
    );
  } else {
    try {
      const onDisk = readFileSync(GENERATED_RAMANUJAN_BLOCK, 'utf8');
      const expected = normalizeGeneratedText(renderGeneratedFile('ramanujan'));
      const actual = normalizeGeneratedText(onDisk);
      const d = diffGenerated(expected, actual);
      if (!d.match) {
        errors.push(
          `regenerate-and-diff drift on ramanujan.triage-block.md: ${d.detail}`,
        );
      }
      // knobsByDepth inside committed file ↔ live mapping
      const payload = extractMachinePayloadFromGenerated(onDisk);
      if (payload.skill !== 'ramanujan') {
        errors.push(`generated payload.skill=${payload.skill} (want ramanujan)`);
      }
      const cmp = assertKnobsByDepthMatchesMapping(payload.knobsByDepth);
      if (!cmp.ok) {
        errors.push(...cmp.errors.map((e) => `committed knobsByDepth: ${e}`));
      }
    } catch (err) {
      errors.push(`generated file: ${err?.message || err}`);
    }
  }

  // SKILL.md embeds or links generated block; no mismatched hand-written knobs
  if (!existsSync(RAMANUJAN_SKILL_MD)) {
    errors.push(`skills/ramanujan/SKILL.md missing at ${RAMANUJAN_SKILL_MD}`);
  } else {
    try {
      const skill = readFileSync(RAMANUJAN_SKILL_MD, 'utf8');
      const linksBlock =
        /ramanujan\.triage-block\.md/.test(skill) ||
        /generated\/ramanujan\.triage-block/.test(skill) ||
        /BEGIN NS01-TRIAGE-BLOCK/.test(skill);
      if (!linksBlock) {
        errors.push(
          'SKILL.md must embed or link generated/ramanujan.triage-block.md (or NS01 triage block)',
        );
      }
      // Process depth section must exist and must not claim labels are thinned
      if (!/Process depth|NS-01 triage|Track B4/i.test(skill)) {
        errors.push('SKILL.md missing Process depth / NS-01 triage / Track B4 section');
      }
      if (/labels?\s+thinned|thin\s+honesty|omit\s+honesty/i.test(skill)) {
        // Only fail if it asserts thinning as policy (allow "never thinned")
        if (!/never\s+thinned|not\s+thinned|are\s+not\s+a\s+ceremony/i.test(skill)) {
          errors.push('SKILL.md appears to allow honesty-label thinning');
        }
      }
      // Hand-written verifyArms / certifier numeric RHS must match live mapping or be absent.
      // Accept forms: verifyArms: N, verifyArms = N, "verifyArms": N
      const verifyArmsHits = [
        ...skill.matchAll(/verifyArms\s*[:=]\s*(\d+)/gi),
        ...skill.matchAll(/["']verifyArms["']\s*:\s*(\d+)/gi),
      ];
      const certifierHits = [
        ...skill.matchAll(/certifier\s*[:=]\s*(true|false)/gi),
        ...skill.matchAll(/["']certifier["']\s*:\s*(true|false)/gi),
      ];
      // Any explicit numeric verifyArms must equal some live row (no alternate table).
      const liveArms = new Set(
        CANONICAL_DEPTHS.map((d) => BAND_MAPPINGS.ramanujan[d].verifyArms),
      );
      for (const m of verifyArmsHits) {
        const n = Number(m[1]);
        if (!liveArms.has(n)) {
          errors.push(
            `SKILL.md hand-written verifyArms=${n} is not in live BAND_MAPPINGS.ramanujan (${[...liveArms].join(',')})`,
          );
        }
      }
      // Boolean certifier literals alone are fine (true and false both appear in mapping);
      // reject only if prose invents a non-boolean.
      for (const m of certifierHits) {
        const v = String(m[1]).toLowerCase();
        if (v !== 'true' && v !== 'false') {
          errors.push(`SKILL.md hand-written certifier=${m[1]} is not boolean`);
        }
      }
    } catch (err) {
      errors.push(`SKILL.md: ${err?.message || err}`);
    }
  }

  return result(
    'prose-drift',
    errors.length === 0,
    errors.length === 0
      ? 'knobsByDepth matches live BAND_MAPPINGS.ramanujan; regenerate-and-diff clean; SKILL.md links block'
      : `${errors.length} prose-drift error(s)`,
    errors,
  );
}

// ---------------------------------------------------------------------------
// Full smoke runner
// ---------------------------------------------------------------------------

/**
 * Run every Track B4 hermetic check. Exit-code policy: 0 only when all green.
 *
 * @returns {Promise<{
 *   ok: boolean,
 *   exitCode: number,
 *   stamp: string,
 *   checks: ReadonlyArray<ReturnType<typeof result>>,
 *   errors: string[],
 * }>}
 */
export async function runB4RamanujanSmoke() {
  const checks = [];
  const errors = [];

  checks.push(checkKnobsMatrix());

  let band;
  try {
    band = await loadBandMod();
    checks.push(checkUnlockRefuse(band));
    checks.push(checkSoleResolveInclusion(band));
  } catch (err) {
    const msg = `load triage-band: ${err?.message || err}`;
    errors.push(msg);
    checks.push(result('unlock-refuse', false, msg, [msg]));
    checks.push(result('sole-resolve-inclusion', false, msg, [msg]));
  }

  try {
    const honesty = await loadHonestyMod();
    checks.push(checkHonestyLabelInvariant(honesty));
  } catch (err) {
    const msg = `load honesty-label-invariant: ${err?.message || err}`;
    errors.push(msg);
    checks.push(result('honesty-label-invariant', false, msg, [msg]));
  }

  checks.push(checkProseDrift());

  for (const c of checks) {
    if (!c.ok) errors.push(...c.errors.map((e) => `[${c.id}] ${e}`));
  }

  const ok = checks.every((c) => c.ok) && errors.length === 0;
  return Object.freeze({
    ok,
    exitCode: ok ? 0 : 1,
    stamp: B4_RAMANUJAN_SMOKE_STAMP,
    checks: Object.freeze(checks.slice()),
    errors: Object.freeze(errors.slice()),
  });
}

/**
 * Human-readable smoke report.
 * @param {Awaited<ReturnType<typeof runB4RamanujanSmoke>>} [report]
 * @returns {string}
 */
export function formatB4SmokeReport(report) {
  const lines = [
    `B4 ramanujan smoke: ${B4_RAMANUJAN_SMOKE_STAMP}`,
    `Checks (${report.checks.length}):`,
    ...report.checks.map((c) => `  [${c.ok ? 'OK' : 'FAIL'}] ${c.id} — ${c.detail}`),
    report.ok
      ? 'B4 smoke GREEN — knobs matrix · unlock refuse · sole-resolve · honesty labels · prose drift'
      : `B4 smoke RED — ${report.errors.length} error(s); fail-closed (exit≠0)`,
  ];
  if (!report.ok) {
    for (const e of report.errors) lines.push(`  ! ${e}`);
  }
  return lines.join('\n');
}

function isMain() {
  if (!process.argv[1]) return false;
  const entry = fileURLToPath(import.meta.url);
  const a = String(process.argv[1]).replace(/\\/g, '/').toLowerCase();
  const b = String(entry).replace(/\\/g, '/').toLowerCase();
  return a === b || a.endsWith('/test/b4-ramanujan-smoke.mjs');
}

if (isMain()) {
  const asJson = process.argv.includes('--json');
  const report = await runB4RamanujanSmoke();
  if (asJson) {
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } else {
    process.stdout.write(`${formatB4SmokeReport(report)}\n`);
  }
  process.exit(report.exitCode);
}
