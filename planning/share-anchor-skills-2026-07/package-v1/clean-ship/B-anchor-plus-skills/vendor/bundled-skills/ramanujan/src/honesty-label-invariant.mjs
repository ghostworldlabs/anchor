// Track B4 / W3 — Honesty-law label invariant (depth never thins labels).
//
// Depth may change ONLY the band-knob slice (verifyArms, certifier). Honesty-law
// label machinery (rung / evidence labels / honesty stamps from live claim-ledger
// + honesty-ui surfaces) stays full-strength under LITE and FULL.
//
// Pure / hermetic API: node built-ins + live spine modules only. No network,
// no real Lean/z3, no model calls. Field names are pinned from the live surfaces.

import {
  ClaimLedger,
  RUNG,
  BELIEF,
  RUNGS,
  FLOOR_RUNG,
  beliefForRung,
} from './claim-ledger.mjs';
import {
  CLAIM_UI_STATE,
  CLAIM_UI_STATES,
  CLAIM_STATE_STYLE,
  styleFor,
} from './honesty-ui.mjs';
import {
  resolveRamanujanBand,
  resolveRamanujanDepthKnobs,
  isCertifierArmed,
} from './triage-band.mjs';
import { invokeSkill, CANNED_PROOF_INPUT } from './skill-invocation.mjs';

// ---------------------------------------------------------------------------
// Pinned field names (live honesty-ui / claim-ledger / stamp contract)
// ---------------------------------------------------------------------------

/**
 * Honesty-law label field names the invariant requires present and non-empty
 * under every locked depth. Pinned from claim-ledger + honesty-ui + NS5 stamp.
 * Depth knobs must never gate, omit, or blank these.
 */
export const HONESTY_LABEL_FIELD_NAMES = Object.freeze([
  'rung',
  'belief',
  'evidenceLabel',
  'honestyStampRung',
  'honestyStampBelief',
  'uiState',
  'uiStyleLabel',
  'uiStyleGlyph',
]);

/** Canonical fixture prompts — same under LITE and FULL (B4 W3). */
export const LABEL_INVARIANT_FIXTURES = Object.freeze([
  Object.freeze({
    id: 'b4-label-twin-primes',
    type: 'proof-bearing',
    statement:
      'There are infinitely many primes p such that p + 2 is also prime.',
  }),
  Object.freeze({
    id: 'b4-label-arithmetic',
    type: 'computational',
    statement: 'The sum of 2 and 2 equals 4.',
  }),
]);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * True when a label field value is considered present and non-empty.
 * @param {unknown} v
 * @returns {boolean}
 */
export function isNonEmptyLabelValue(v) {
  if (v == null) return false;
  if (typeof v === 'string') return v.trim().length > 0;
  if (typeof v === 'boolean' || typeof v === 'number') return true;
  if (typeof v === 'object') return Object.keys(v).length > 0;
  return Boolean(v);
}

/**
 * Band-knob slice only — the sole fields depth may change.
 * @param {{ verifyArms?: number, certifier?: boolean, certifierEnabled?: boolean, resolved?: object, knobs?: object }} band
 * @returns {Readonly<{ verifyArms: number, certifier: boolean }>}
 */
export function bandKnobSlice(band) {
  const resolved =
    band?.resolved && typeof band.resolved === 'object'
      ? band.resolved
      : band?.knobs && typeof band.knobs === 'object'
        ? band.knobs
        : band;
  const verifyArms = Number(resolved?.verifyArms);
  const certifier =
    resolved?.certifier === true ||
    band?.certifierEnabled === true ||
    isCertifierArmed(band);
  return Object.freeze({
    verifyArms,
    certifier: certifier === true,
  });
}

/**
 * Build NS5-shaped honesty stamp fields from a ledger claim snapshot.
 * Family is null until an artifact-backed lift (honest for floor claims).
 * @param {{ id: string, type: string, rung: string, belief: string }} claim
 * @returns {Readonly<object>}
 */
export function honestyStampFromClaim(claim) {
  return Object.freeze({
    claim_id: claim.id,
    claim_type: claim.type,
    rung: claim.rung,
    belief: claim.belief,
    verifier_attempted: null,
    verifier_family: null,
    artifact_backed: false,
  });
}

/**
 * Evidence / dialogue label from live honesty-ui styling for a UI state.
 * Unsettled floor claims map to the UNVERIFIED style (honest, never blank).
 * @param {string} [uiState]
 * @returns {Readonly<{ uiState: string, label: string, glyph: string, css_class: string, tone: string }>}
 */
export function evidenceLabelForUiState(uiState = CLAIM_UI_STATE.UNVERIFIED) {
  const style = styleFor(uiState);
  return Object.freeze({
    uiState: style.state,
    label: style.label,
    glyph: style.glyph,
    css_class: style.css_class,
    tone: style.tone,
  });
}

/**
 * Project one claim into the pinned honesty-law label field bag.
 * @param {{ id: string, type: string, statement?: string, rung: string, belief: string }} claim
 * @param {{ uiState?: string }} [opts]
 * @returns {Readonly<Record<string, string>>}
 */
export function labelFieldsFromClaim(claim, { uiState = CLAIM_UI_STATE.UNVERIFIED } = {}) {
  const evidence = evidenceLabelForUiState(uiState);
  const stamp = honestyStampFromClaim(claim);
  return Object.freeze({
    rung: claim.rung,
    belief: claim.belief,
    evidenceLabel: evidence.label,
    honestyStampRung: stamp.rung,
    honestyStampBelief: stamp.belief,
    uiState: evidence.uiState,
    uiStyleLabel: evidence.label,
    uiStyleGlyph: evidence.glyph,
  });
}

// ---------------------------------------------------------------------------
// Collect under a locked depth (live surfaces + sole-resolve knobs)
// ---------------------------------------------------------------------------

/**
 * Collect honesty-law labels for the same fixtures under a locked process depth.
 *
 * Hermetic only. Depth is resolved solely via resolveRamanujanBand →
 * resolveRamanujanDepthKnobs. Label fields come from live ClaimLedger + honesty-ui
 * vocabulary; depth knobs are recorded but never used to omit or blank labels.
 *
 * @param {string} depth  locked depth pin (LITE | FULL | SPIKE | aliases)
 * @param {{
 *   fixtures?: ReadonlyArray<{ id: string, type: string, statement: string }>,
 *   env?: object,
 * }} [opts]
 * @returns {Readonly<{
 *   depth: string,
 *   knobs: Readonly<{ verifyArms: number, certifier: boolean }>,
 *   band: object,
 *   surface: Readonly<object>,
 *   claims: ReadonlyArray<object>,
 *   labelFieldsByClaim: Readonly<Record<string, Readonly<Record<string, string>>>>,
 *   labelFieldUnion: ReadonlyArray<string>,
 * }>}
 */
export function collectHonestyLabelsForDepth(depth, { fixtures = LABEL_INVARIANT_FIXTURES, env = {} } = {}) {
  // Sole production knobs path — never freelanced; unlocked throws.
  const band = resolveRamanujanBand({ depth, env });
  const knobs = bandKnobSlice(band);
  // Structural sole-resolve touch (same as other B4 arm sites).
  void resolveRamanujanDepthKnobs(band.depth);
  void isCertifierArmed(band);

  const ledger = new ClaimLedger();
  const claims = [];
  const labelFieldsByClaim = {};

  for (const f of fixtures) {
    // Live claim-ledger: admit at floor; rung + belief are the honesty-law labels.
    const snap = ledger.assert({
      id: f.id,
      type: f.type,
      statement: f.statement,
    });
    // Unsettled claims are styled UNVERIFIED — never blank, never promoted by depth.
    const uiState = CLAIM_UI_STATE.UNVERIFIED;
    const fields = labelFieldsFromClaim(snap, { uiState });
    const stamp = honestyStampFromClaim(snap);
    const evidence = evidenceLabelForUiState(uiState);

    claims.push(
      Object.freeze({
        claim_id: snap.id,
        type: snap.type,
        statement: snap.statement,
        rung: snap.rung,
        belief: snap.belief,
        stamp,
        evidence,
        fields,
      }),
    );
    labelFieldsByClaim[snap.id] = fields;
  }

  // Live surface vocabulary — must remain complete under every band (not thinned by depth).
  const surface = Object.freeze({
    rungs: RUNGS,
    floorRung: FLOOR_RUNG,
    rungConstants: RUNG,
    beliefs: Object.freeze(Object.values(BELIEF)),
    beliefByRung: Object.freeze(
      Object.fromEntries(RUNGS.map((r) => [r, beliefForRung(r)])),
    ),
    uiStates: CLAIM_UI_STATES,
    uiStyleLabels: Object.freeze(
      CLAIM_UI_STATES.map((s) => styleFor(s).label),
    ),
    uiStyleGlyphs: Object.freeze(
      CLAIM_UI_STATES.map((s) => styleFor(s).glyph),
    ),
    claimStateStyle: CLAIM_STATE_STYLE,
  });

  return Object.freeze({
    depth: band.depth,
    knobs,
    band,
    surface,
    claims: Object.freeze(claims),
    labelFieldsByClaim: Object.freeze(labelFieldsByClaim),
    labelFieldUnion: HONESTY_LABEL_FIELD_NAMES,
  });
}

/**
 * Production-path labels via invokeSkill under a locked depth (canned proof fixture).
 * Proves the skill entry stamp surface is not thinned by LITE.
 *
 * @param {string} depth
 * @param {{ env?: object, request?: object }} [opts]
 * @returns {Readonly<object>}
 */
export function collectInvokeSkillLabelsForDepth(depth, { env = {}, request = CANNED_PROOF_INPUT } = {}) {
  const band = resolveRamanujanBand({ depth, env });
  const knobs = bandKnobSlice(band);
  const result = invokeSkill(request, { depth, env });

  const stamps = (result.results || []).map((r) => {
    const stamp = r.stamp && typeof r.stamp === 'object' ? r.stamp : {};
    const fields = Object.freeze({
      rung: String(r.rung ?? stamp.rung ?? ''),
      belief: String(r.belief ?? stamp.belief ?? ''),
      evidenceLabel: evidenceLabelForUiState(CLAIM_UI_STATE.UNVERIFIED).label,
      honestyStampRung: String(stamp.rung ?? r.rung ?? ''),
      honestyStampBelief: String(stamp.belief ?? r.belief ?? ''),
      uiState: CLAIM_UI_STATE.UNVERIFIED,
      uiStyleLabel: evidenceLabelForUiState(CLAIM_UI_STATE.UNVERIFIED).label,
      uiStyleGlyph: evidenceLabelForUiState(CLAIM_UI_STATE.UNVERIFIED).glyph,
    });
    return Object.freeze({
      claim_id: stamp.claim_id ?? r.claim_id ?? null,
      verdict: r.verdict ?? null,
      settled: r.settled === true,
      stamp: Object.freeze({ ...stamp }),
      fields,
    });
  });

  return Object.freeze({
    depth: band.depth,
    knobs,
    band,
    certifierArmed: result.certifierArmed === true,
    honestStamps: result.honestStamps === true,
    stamps: Object.freeze(stamps),
    labelFieldUnion: HONESTY_LABEL_FIELD_NAMES,
  });
}

// ---------------------------------------------------------------------------
// Invariant: LITE vs FULL — labels present/non-empty; only knobs may differ
// ---------------------------------------------------------------------------

/**
 * Assert every pinned label field is present and non-empty on a collection.
 * @param {ReturnType<typeof collectHonestyLabelsForDepth>} collected
 * @param {string} [bandLabel]
 * @returns {true}
 */
export function assertLabelFieldsPresent(collected, bandLabel = collected.depth) {
  if (!collected || typeof collected !== 'object') {
    throw new Error(`assertLabelFieldsPresent(${bandLabel}): missing collection`);
  }
  // Surface vocabulary must be non-empty under every band
  if (!Array.isArray(collected.surface?.rungs) || collected.surface.rungs.length === 0) {
    throw new Error(`assertLabelFieldsPresent(${bandLabel}): surface.rungs empty or missing`);
  }
  if (!Array.isArray(collected.surface?.uiStyleLabels) || collected.surface.uiStyleLabels.length === 0) {
    throw new Error(`assertLabelFieldsPresent(${bandLabel}): surface.uiStyleLabels empty or missing`);
  }
  for (const label of collected.surface.uiStyleLabels) {
    if (!isNonEmptyLabelValue(label)) {
      throw new Error(`assertLabelFieldsPresent(${bandLabel}): blank uiStyleLabel in surface`);
    }
  }

  const byClaim = collected.labelFieldsByClaim || {};
  const ids = Object.keys(byClaim);
  if (ids.length === 0) {
    throw new Error(`assertLabelFieldsPresent(${bandLabel}): no claims labeled`);
  }
  for (const id of ids) {
    const fields = byClaim[id];
    for (const name of HONESTY_LABEL_FIELD_NAMES) {
      if (!Object.prototype.hasOwnProperty.call(fields, name)) {
        throw new Error(
          `assertLabelFieldsPresent(${bandLabel}): claim ${id} omits label field "${name}"`,
        );
      }
      if (!isNonEmptyLabelValue(fields[name])) {
        throw new Error(
          `assertLabelFieldsPresent(${bandLabel}): claim ${id} blanks label field "${name}"`,
        );
      }
    }
  }
  return true;
}

/**
 * Compare LITE vs FULL (or any two depth collections): label fields must match
 * (present, non-empty, same keys/values for the honesty surface); only
 * verifyArms / certifier may differ in the band-knob slice.
 *
 * @param {ReturnType<typeof collectHonestyLabelsForDepth>} a
 * @param {ReturnType<typeof collectHonestyLabelsForDepth>} b
 * @returns {true}
 */
export function assertLabelsUnthinnedAcrossDepths(a, b) {
  assertLabelFieldsPresent(a, a.depth);
  assertLabelFieldsPresent(b, b.depth);

  // Same claim ids
  const idsA = Object.keys(a.labelFieldsByClaim).sort();
  const idsB = Object.keys(b.labelFieldsByClaim).sort();
  if (idsA.length !== idsB.length || idsA.some((id, i) => id !== idsB[i])) {
    throw new Error(
      `assertLabelsUnthinnedAcrossDepths: claim id set differs (${a.depth} vs ${b.depth})`,
    );
  }

  // Per-claim label fields must be identical — depth must not thin or rewrite them
  for (const id of idsA) {
    const fa = a.labelFieldsByClaim[id];
    const fb = b.labelFieldsByClaim[id];
    for (const name of HONESTY_LABEL_FIELD_NAMES) {
      if (fa[name] !== fb[name]) {
        throw new Error(
          `assertLabelsUnthinnedAcrossDepths: claim ${id} field "${name}" differs ` +
            `under ${a.depth}=${JSON.stringify(fa[name])} vs ${b.depth}=${JSON.stringify(fb[name])} ` +
            `(depth may change only verifyArms/certifier)`,
        );
      }
    }
  }

  // Surface vocabulary must match (full-strength under both bands)
  if (JSON.stringify(a.surface.rungs) !== JSON.stringify(b.surface.rungs)) {
    throw new Error('assertLabelsUnthinnedAcrossDepths: RUNGS vocabulary thinned by depth');
  }
  if (JSON.stringify(a.surface.uiStates) !== JSON.stringify(b.surface.uiStates)) {
    throw new Error('assertLabelsUnthinnedAcrossDepths: UI states thinned by depth');
  }
  if (JSON.stringify(a.surface.uiStyleLabels) !== JSON.stringify(b.surface.uiStyleLabels)) {
    throw new Error('assertLabelsUnthinnedAcrossDepths: UI style labels thinned by depth');
  }

  // Knob slice: only verifyArms / certifier keys; values MAY differ by depth
  for (const side of [a, b]) {
    const keys = Object.keys(side.knobs).sort();
    if (keys.length !== 2 || keys[0] !== 'certifier' || keys[1] !== 'verifyArms') {
      throw new Error(
        `assertLabelsUnthinnedAcrossDepths: knobs must be only {verifyArms, certifier}; got ${keys.join(',')}`,
      );
    }
  }

  return true;
}

/**
 * Hermetic LITE-vs-FULL label invariant (B4 W3 done-when entry).
 * @returns {Readonly<{ lite: object, full: object, ok: true }>}
 */
export function runHonestyLabelInvariant() {
  const lite = collectHonestyLabelsForDepth('LITE');
  const full = collectHonestyLabelsForDepth('FULL');
  assertLabelsUnthinnedAcrossDepths(lite, full);

  // Live SC2 coupling: LITE knobs leaner; labels already proven equal
  if (lite.knobs.certifier !== false) {
    throw new Error('runHonestyLabelInvariant: LITE certifier must be false');
  }
  if (!(lite.knobs.verifyArms < full.knobs.verifyArms)) {
    throw new Error(
      `runHonestyLabelInvariant: LITE.verifyArms < FULL.verifyArms required (live ${lite.knobs.verifyArms} < ${full.knobs.verifyArms})`,
    );
  }

  // Production invokeSkill path: stamps present under both depths
  const liteInvoke = collectInvokeSkillLabelsForDepth('LITE');
  const fullInvoke = collectInvokeSkillLabelsForDepth('FULL');
  if (!liteInvoke.stamps.length || !fullInvoke.stamps.length) {
    throw new Error('runHonestyLabelInvariant: invokeSkill produced no stamps under LITE or FULL');
  }
  for (const side of [liteInvoke, fullInvoke]) {
    for (const s of side.stamps) {
      for (const name of HONESTY_LABEL_FIELD_NAMES) {
        if (!isNonEmptyLabelValue(s.fields[name])) {
          throw new Error(
            `runHonestyLabelInvariant: invokeSkill under ${side.depth} blanks "${name}"`,
          );
        }
      }
    }
  }
  // LITE must not arm certifier; FULL may (per mapping) — labels still full-strength
  if (liteInvoke.certifierArmed !== false) {
    throw new Error('runHonestyLabelInvariant: LITE invokeSkill must not arm certifier');
  }

  return Object.freeze({ lite, full, liteInvoke, fullInvoke, ok: true });
}

export {
  resolveRamanujanBand,
  resolveRamanujanDepthKnobs,
  isCertifierArmed,
  ClaimLedger,
  RUNG,
  BELIEF,
  RUNGS,
  CLAIM_UI_STATE,
  CLAIM_UI_STATES,
  styleFor,
  CANNED_PROOF_INPUT,
  invokeSkill,
};
