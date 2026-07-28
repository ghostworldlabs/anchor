// Wave 11 — Firewall builder + anchors + stamps + S4 invariant (B2a).
//
// Exercises the REAL Wave-11 source (src/firewall-builder.mjs) against the REAL shared spine — the
// Wave-3 A1 ledger, the Wave-8 closed grammar, the Wave-9 out-of-model firewall subprocess, and the
// Wave-4 adjudication substrate over the REAL inherited durability substrate — proving the done-when:
//
//   a firewall builds with HONEST stamps; the planted-wrong-same-family-reference fixture caps at
//   CLAIMED. (Given a ref-fn whose AST shares symbol-provenance with the comprehension narrative,
//   when S4 runs, then the pass caps at CLAIMED — never OBSERVED/VERIFIED.)
//
// Also pins the NECESSARY-9 trust gate, the three reading-independent anchors + the
// ANCHOR-AVAILABILITY gate, and the firewall_status / anchor_coverage / warranty_excludes[] /
// reduced_warranty stamps.

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  FIREWALL_STATUS,
  ANCHOR_COVERAGE,
  ANCHOR_NAMES,
  CONDITION_STATUS,
  NECESSARY_9,
  NUMERIC_ANCHOR_REL_TOL,
  tagProvenance,
  collectProvenance,
  s4RefFnIndependence,
  buildFirewall,
  applyFirewallCap,
  buildFixtureFirewalls,
  NARRATIVE_PROVENANCE,
  REFERENCE_PROVENANCE,
  GENUINE_NARRATIVE,
  PLANTED_SAME_FAMILY_NARRATIVE,
  REDUCED_WARRANTY_NARRATIVE,
  ANCHOR_VIOLATION_NARRATIVE,
  QUOTED_MISMATCH_NARRATIVE,
  OUT_OF_GRAMMAR_REF_NARRATIVE,
  NO_ANCHORS_NARRATIVE,
} from '../src/firewall-builder.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import {
  loadDurabilitySubstrate,
  DurableNonceStore,
  AdjudicationDispatcher,
} from '../src/adjudication.mjs';
import { FIREWALL_FAMILY } from '../src/firewall-subprocess.mjs';
import { int, mul, variable, sum, add, rational } from '../src/firewall-grammar.mjs';

// The REAL inherited durability substrate (matches the Wave-4/6/9/10 setup) — needed only for the
// OBSERVED settlement path (the firewall positive path mints + adjudicates a real artifact).
const substrate = await loadDurabilitySubstrate();

let fileSeq = 0;
const scratchDirs = [];
function tmpFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w11-'));
  scratchDirs.push(dir);
  return path.join(dir, `nonce-store-${fileSeq++}.checkpoint.json`);
}
function freshDispatcher() {
  return new AdjudicationDispatcher({ store: DurableNonceStore.load(substrate, tmpFile()), family: FIREWALL_FAMILY });
}
after(() => {
  for (const d of scratchDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best-effort cleanup */ }
  }
});

const { PASS, FAIL, NA } = CONDITION_STATUS;
const condByName = (build) => Object.fromEntries(build.necessary9.map((c) => [c.name, c]));

// =====================================================================================
// 0. Shape — the NECESSARY-9, the anchors, and the provenance helpers.
// =====================================================================================

test('NECESSARY_9 has exactly 9 conditions, with ref-fn-independent (S4) as condition 5', () => {
  assert.equal(NECESSARY_9.length, 9);
  assert.equal(NECESSARY_9[4], 'ref-fn-independent');
  assert.equal(new Set(NECESSARY_9).size, 9); // no duplicates
});

test('ANCHOR_NAMES is the three reading-independent anchors', () => {
  assert.deepEqual(ANCHOR_NAMES.slice().sort(), ['closed-form', 'dimensional', 'quoted-number']);
});

test('tagProvenance stamps an inert prov tag the grammar/evaluator ignore; collectProvenance reads it back', () => {
  const tagged = tagProvenance(sum('k', int(1), int(3), mul(variable('k'), int(2))), 'fam-X');
  const provs = collectProvenance(tagged);
  assert.equal(provs.has('fam-X'), true);
  assert.equal([...provs].length, 1);
  // a tagged AST is still recognized + evaluated identically (prov is inert) — proven via the builder
  // settling the genuine (tagged) ref-fn below.
});

// =====================================================================================
// 1. The S4 ref-fn-independence invariant (the headline), exercised directly.
// =====================================================================================

test('S4: a reconstruction with a DISJOINT provenance is independent', () => {
  const refFn = tagProvenance(int(12), REFERENCE_PROVENANCE);
  const s4 = s4RefFnIndependence(NARRATIVE_PROVENANCE, refFn, REFERENCE_PROVENANCE);
  assert.equal(s4.independent, true);
  assert.deepEqual(s4.shared, []);
});

test('S4: a reconstruction declaring the NARRATIVE family is NOT independent (same-family reference)', () => {
  const refFn = tagProvenance(int(12), NARRATIVE_PROVENANCE);
  const s4 = s4RefFnIndependence(NARRATIVE_PROVENANCE, refFn, NARRATIVE_PROVENANCE);
  assert.equal(s4.independent, false);
  assert.deepEqual(s4.shared, [NARRATIVE_PROVENANCE]);
  assert.match(s4.reason, /same-family|shares symbol-provenance/);
});

test('S4: a narrative-tagged node SMUGGLED into an otherwise-independent ref-fn is caught', () => {
  // The reconstruction claims an independent provenance, but a sub-tree is tagged with the narrative's.
  const smuggled = add(tagProvenance(int(1), REFERENCE_PROVENANCE), tagProvenance(int(11), NARRATIVE_PROVENANCE));
  const s4 = s4RefFnIndependence(NARRATIVE_PROVENANCE, smuggled, REFERENCE_PROVENANCE);
  assert.equal(s4.independent, false);
  assert.deepEqual(s4.shared, [NARRATIVE_PROVENANCE]);
});

test('S4 is FAIL-SAFE: a missing/empty reconstruction provenance cannot prove independence', () => {
  assert.equal(s4RefFnIndependence(NARRATIVE_PROVENANCE, int(12), null).independent, false);
  assert.equal(s4RefFnIndependence(NARRATIVE_PROVENANCE, int(12), '').independent, false);
  assert.equal(s4RefFnIndependence(null, tagProvenance(int(12), REFERENCE_PROVENANCE), REFERENCE_PROVENANCE).independent, false);
});

// =====================================================================================
// 2. THE DONE-WHEN — a firewall builds with honest stamps; the planted same-family reference caps CLAIMED.
// =====================================================================================

test('done-when: a GENUINE firewall builds full-warranty with honest stamps and an OBSERVED cap', () => {
  const build = buildFirewall(GENUINE_NARRATIVE);
  // honest stamps
  assert.equal(build.firewall_status, FIREWALL_STATUS.FULL_WARRANTY);
  assert.equal(build.anchor_coverage, ANCHOR_COVERAGE.FULL);
  assert.deepEqual(build.warranty_excludes, []);
  assert.equal(build.reduced_warranty, false);
  assert.equal(build.s4.independent, true);
  assert.equal(build.rung_cap, RUNG.OBSERVED);
  // the builder produced ref-fn + spec + tests.
  assert.ok(build.ref_fn && build.spec && Array.isArray(build.tests) && build.tests.length === 3);
  assert.equal(build.spec.claim_id, 'fb::partial-sum-equals-12');
  // NECESSARY-9 all hold (no fail, no n/a — every anchor is available + holds).
  assert.equal(build.trust.trusted, true);
  for (const c of build.necessary9) assert.equal(c.status, PASS, `${c.name} expected PASS, got ${c.status}`);
});

test('done-when (GWT): a ref-fn whose AST shares symbol-provenance with the narrative CAPS AT CLAIMED (S4)', () => {
  const build = buildFirewall(PLANTED_SAME_FAMILY_NARRATIVE);

  // S4 is the ONLY thing that changed vs GENUINE: full coverage, all anchors hold, all structural pass.
  assert.equal(build.anchor_coverage, ANCHOR_COVERAGE.FULL);
  assert.deepEqual(build.warranty_excludes, []);
  const by = condByName(build);
  for (const n of ['spec-well-formed', 'ref-fn-present', 'ref-fn-in-grammar', 'ref-fn-executes-exactly', 'anchor-available', 'dimensional-anchor', 'quoted-number-anchor', 'closed-form-anchor']) {
    assert.equal(by[n].status, PASS, `${n} should still PASS — only S4 fails`);
  }
  // ...and S4 fails, so the firewall caps at CLAIMED.
  assert.equal(by['ref-fn-independent'].status, FAIL);
  assert.equal(build.s4.independent, false);
  assert.equal(build.firewall_status, FIREWALL_STATUS.CAPPED_SAME_FAMILY);
  assert.equal(build.rung_cap, RUNG.CLAIMED);
  assert.notEqual(build.rung_cap, RUNG.OBSERVED);

  // The cap is REALIZED on the ledger: CLAIMED / CONJECTURAL — NEVER OBSERVED / VERIFIED — even with a
  // live dispatcher present (so it is not merely the no-minter arm holding it back).
  const ledger = new ClaimLedger();
  const verdict = applyFirewallCap(build, ledger, { dispatcher: freshDispatcher() });
  assert.equal(verdict.verdict, 'CAPPED');
  assert.equal(verdict.rung, RUNG.CLAIMED);
  assert.equal(verdict.belief, BELIEF.CONJECTURAL);
  assert.notEqual(verdict.belief, BELIEF.VERIFIED);
  assert.equal(ledger.rungOf(build.claim_id), RUNG.CLAIMED);
  assert.equal(ledger.beliefOf(build.claim_id), BELIEF.CONJECTURAL);
});

test('the GENUINE firewall, applied with a dispatcher, SETTLES to OBSERVED/VERIFIED (artifact-backed)', () => {
  const build = buildFirewall(GENUINE_NARRATIVE);
  const ledger = new ClaimLedger();
  const verdict = applyFirewallCap(build, ledger, { dispatcher: freshDispatcher() });
  assert.equal(verdict.verdict, 'VERIFIED');
  assert.equal(verdict.rung, RUNG.OBSERVED);
  assert.equal(verdict.belief, BELIEF.VERIFIED);
  assert.equal(verdict.artifact_backed, true);
  assert.equal(verdict.reexecutes, true);
  assert.equal(verdict.family, FIREWALL_FAMILY);
  assert.equal(ledger.rungOf(build.claim_id), RUNG.OBSERVED);
});

test('the GENUINE firewall with NO dispatcher honestly ABSTAINs at UNVERIFIED (no-minter arm) — never silently VERIFIED', () => {
  const build = buildFirewall(GENUINE_NARRATIVE);
  const ledger = new ClaimLedger();
  const verdict = applyFirewallCap(build, ledger /* no dispatcher */);
  assert.equal(verdict.verdict, 'ABSTAIN');
  assert.equal(verdict.rung, RUNG.UNVERIFIED);
  assert.notEqual(verdict.belief, BELIEF.VERIFIED);
});

// =====================================================================================
// 3. The stamps + the ANCHOR-AVAILABILITY gate.
// =====================================================================================

test('reduced warranty: one unavailable anchor => partial coverage, warranty_excludes[] != [], cap CLAIMED', () => {
  const build = buildFirewall(REDUCED_WARRANTY_NARRATIVE);
  assert.equal(build.s4.independent, true); // independence is fine here
  assert.equal(build.anchor_coverage, ANCHOR_COVERAGE.PARTIAL);
  assert.deepEqual(build.warranty_excludes, ['closed-form']);
  assert.equal(build.reduced_warranty, true);
  assert.equal(build.firewall_status, FIREWALL_STATUS.REDUCED_WARRANTY);
  assert.equal(build.rung_cap, RUNG.CLAIMED);
  // the closed-form condition is n/a (unavailable), NOT a hard fail.
  assert.equal(condByName(build)['closed-form-anchor'].status, NA);

  const ledger = new ClaimLedger();
  const verdict = applyFirewallCap(build, ledger, { dispatcher: freshDispatcher() });
  assert.equal(verdict.rung, RUNG.CLAIMED);
  assert.notEqual(verdict.belief, BELIEF.VERIFIED);
});

test('a VIOLATED dimensional anchor (ref-fn dimensionless != declared length) => REFUSED, cap UNVERIFIED', () => {
  const build = buildFirewall(ANCHOR_VIOLATION_NARRATIVE);
  assert.equal(build.anchors.dimensional.available, true);
  assert.equal(build.anchors.dimensional.holds, false);
  assert.equal(condByName(build)['dimensional-anchor'].status, FAIL);
  assert.equal(build.firewall_status, FIREWALL_STATUS.REFUSED);
  assert.equal(build.rung_cap, RUNG.UNVERIFIED);

  const ledger = new ClaimLedger();
  const verdict = applyFirewallCap(build, ledger, { dispatcher: freshDispatcher() });
  assert.equal(verdict.verdict, 'REFUSED');
  assert.equal(verdict.rung, RUNG.UNVERIFIED);
});

test("the paper's OWN quoted number is a real cross-check: ref-fn 12 != quoted 13 => REFUSED", () => {
  const build = buildFirewall(QUOTED_MISMATCH_NARRATIVE);
  assert.equal(build.anchors['quoted-number'].holds, false);
  assert.equal(condByName(build)['quoted-number-anchor'].status, FAIL);
  assert.equal(build.firewall_status, FIREWALL_STATUS.REFUSED);
  assert.equal(build.rung_cap, RUNG.UNVERIFIED);
});

test('an OUT-OF-GRAMMAR ref-fn fails ref-fn-in-grammar (closed default-deny) => REFUSED', () => {
  const build = buildFirewall(OUT_OF_GRAMMAR_REF_NARRATIVE);
  assert.equal(condByName(build)['ref-fn-in-grammar'].status, FAIL);
  assert.equal(build.firewall_status, FIREWALL_STATUS.REFUSED);
  assert.equal(build.rung_cap, RUNG.UNVERIFIED);
});

test('the ANCHOR-AVAILABILITY gate refuses when NO anchor is available (nothing cross-checks the ref-fn)', () => {
  const build = buildFirewall(NO_ANCHORS_NARRATIVE);
  assert.equal(build.anchor_coverage, ANCHOR_COVERAGE.NONE);
  assert.equal(condByName(build)['anchor-available'].status, FAIL);
  assert.equal(build.firewall_status, FIREWALL_STATUS.REFUSED);
  assert.equal(build.rung_cap, RUNG.UNVERIFIED);
});

test('the stamps object mirrors the top-level honest fields (no silent divergence)', () => {
  for (const f of buildFixtureFirewalls()) {
    const b = f.build;
    assert.equal(b.stamps.firewall_status, b.firewall_status);
    assert.equal(b.stamps.anchor_coverage, b.anchor_coverage);
    assert.deepEqual(b.stamps.warranty_excludes, b.warranty_excludes);
    assert.equal(b.stamps.reduced_warranty, b.reduced_warranty);
    assert.equal(b.stamps.s4_independent, b.s4.independent);
    assert.equal(b.stamps.rung_cap, b.rung_cap);
  }
});

// =====================================================================================
// 4. The full fixture sweep + the Honesty-Law floor (only an independent, fully-anchored firewall settles).
// =====================================================================================

test('every fixture lands at its expected firewall_status + rung_cap', () => {
  for (const f of buildFixtureFirewalls()) {
    assert.equal(f.build.firewall_status, f.expect_status, `${f.label}: status`);
    assert.equal(f.build.rung_cap, f.expect_cap, `${f.label}: cap`);
  }
});

test('HONESTY LAW: only the genuine (independent + full-coverage) firewall reaches OBSERVED — every other fixture caps below it', () => {
  for (const f of buildFixtureFirewalls()) {
    const ledger = new ClaimLedger();
    const verdict = applyFirewallCap(f.build, ledger, { dispatcher: freshDispatcher() });
    if (f.label === 'genuine') {
      assert.equal(verdict.belief, BELIEF.VERIFIED);
      assert.equal(ledger.rungOf(f.build.claim_id), RUNG.OBSERVED);
    } else {
      assert.notEqual(verdict.belief, BELIEF.VERIFIED, `${f.label} must NEVER reach VERIFIED`);
      assert.notEqual(ledger.rungOf(f.build.claim_id), RUNG.OBSERVED, `${f.label} must NEVER reach OBSERVED`);
    }
  }
});

// =====================================================================================
// 5. Builder mechanics: pluggable reconstruction + a custom ad-hoc firewall.
// =====================================================================================

test('the reconstruction step is pluggable (prose -> ref-fn): a laundering reconstruct caps at CLAIMED', () => {
  // A reconstruct that LAUNDERS the narrative's own family into the ref-fn — even on the genuine
  // narrative, S4 catches it and caps at CLAIMED.
  const launder = (narrative) => ({
    ref_fn: tagProvenance(sum('k', int(1), int(3), mul(variable('k'), int(2))), narrative.provenance),
    provenance: narrative.provenance,
  });
  const build = buildFirewall(GENUINE_NARRATIVE, { reconstruct: launder });
  assert.equal(build.s4.independent, false);
  assert.equal(build.rung_cap, RUNG.CLAIMED);
});

test('an ad-hoc independent firewall over exact rationals builds full warranty (closed-form cross-check holds)', () => {
  // ref = 1/2 + 1/3 = 5/6 ; the paper quotes 5/6 ; the closed form is the same exact rational by a
  // different AST (6 in the denominator via 2*3) — a genuine independent cross-check.
  const narrative = {
    claim_id: 'adhoc::five-sixths',
    domain: 'arithmetic',
    provenance: 'narrative::adhoc',
    claimed: { quoted_value: { num: '5', den: '6' }, dimension: 'dimensionless' },
    anchors: {
      dimensional: { available: true, expected: 'dimensionless' },
      quoted_number: { available: true },
      closed_form: { available: true, expr: rational(5, 6) },
    },
    reconstruction: {
      ref_fn: tagProvenance(add(rational(1, 2), rational(1, 3)), 'reference::adhoc'),
      provenance: 'reference::adhoc',
    },
  };
  const build = buildFirewall(narrative);
  assert.equal(build.firewall_status, FIREWALL_STATUS.FULL_WARRANTY);
  assert.equal(build.rung_cap, RUNG.OBSERVED);
  const ledger = new ClaimLedger();
  const verdict = applyFirewallCap(build, ledger, { dispatcher: freshDispatcher() });
  assert.equal(verdict.belief, BELIEF.VERIFIED);
});

test('the numeric quoted-number anchor tolerates a DECIMAL within the pinned relative 1e-9', () => {
  // ref = 22/7 ; quoted as a decimal close to 22/7 within 1e-9 holds; a coarse decimal does not.
  const base = {
    claim_id: 'adhoc::22-7',
    domain: 'arithmetic',
    provenance: 'narrative::dec',
    claimed: { dimension: 'dimensionless' },
    anchors: {
      dimensional: { available: true, expected: 'dimensionless' },
      quoted_number: { available: true, value: 22 / 7 }, // a decimal the paper printed
      closed_form: { available: true, expr: rational(22, 7) },
    },
    reconstruction: { ref_fn: tagProvenance(rational(22, 7), 'reference::dec'), provenance: 'reference::dec' },
  };
  const ok = buildFirewall(base);
  assert.equal(ok.anchors['quoted-number'].holds, true);
  assert.equal(ok.rung_cap, RUNG.OBSERVED);
  assert.ok(NUMERIC_ANCHOR_REL_TOL > 0);

  const coarse = buildFirewall({ ...base, anchors: { ...base.anchors, quoted_number: { available: true, value: 3.14 } } });
  assert.equal(coarse.anchors['quoted-number'].holds, false); // 3.14 is outside relative 1e-9 of 22/7
  assert.equal(coarse.firewall_status, FIREWALL_STATUS.REFUSED);
});

test('buildFirewall validates its input', () => {
  assert.throws(() => buildFirewall(null), /narrative must be an object/);
  assert.throws(() => buildFirewall({ domain: 'x' }), /claim_id is required/);
  assert.throws(() => buildFirewall({ claim_id: 'c', provenance: 'p' }), /reconstruction/);
});
