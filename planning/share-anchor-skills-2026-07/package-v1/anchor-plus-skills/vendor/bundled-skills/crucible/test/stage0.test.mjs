// test/stage0.test.mjs — Wave 6 gate for Stage 0: Intake & Framing.
//
// Drives bin/stage0.mjs with an INJECTED (stubbed) agent seam + a stubbed Wave-5
// research coordinator — no subprocess, no live model — and proves the done-when:
//   · greenfield framing SHAPE (candidate North Star + criteria + Non-Goals + risk
//     taxonomy + foresight brief);
//   · correct TIER SELECTION by input (greenfield / docs-only T1 / repo T2 / large
//     or contested T3);
//   · LABEL-GATING — a Gap touching a North-Star criterion HALTs rather than locking,
//     and an irresolvable/people-only Gap HALTs (it never becomes a silent RAID assumption);
//   · the LOCK gate (HALT-until-approved; approval ⇒ locked + drift detection active).
// Plus: Tier-1 runs NO archaeology, Tier-2 downgrades Confirmed-but-untested to
// Inferred, Tier-3 delegates to researchPrime, and salvage-vs-rewrite is never scored.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  TIERS,
  INGEST_LABELS,
  FRAMING_SCHEMA,
  INGEST_SCHEMA,
  selectTier,
  runFraming,
  runIngest,
  evaluateIngestGate,
  salvageVsRewriteQuestion,
  lockNorthStar,
  runStage0,
} from '../bin/stage0.mjs';

const INTENT = 'STAGE0-INTENT-SENTINEL: turn a messy intent into a Foreman-ready plan.';
const NORTH_STAR = 'STAGE0-NS-SENTINEL: ship a vetted, Foreman-ready plan that never drifts.';

/**
 * A label-routed stub agent: returns a scripted payload keyed by the prompt's label
 * prefix (`stage0:framing`, `stage0:ingest:*:inventory`, `stage0:ingest:*:reproduce`).
 * Records every call so the test can assert what ran.
 */
function stubAgent(byLabel = {}) {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    const label = opts.label || '';
    if (label === 'stage0:framing') {
      return (
        byLabel.framing ?? {
          northStar: NORTH_STAR,
          criteria: ['emits a zero-HALT doc-trio', 'both stages converge'],
          nonGoals: ['no pedagogy'],
          riskTaxonomy: [{ risk: 'drift', mitigation: 'lock the North Star' }],
          foresightBrief: 'capture the auth wall now',
        }
      );
    }
    if (label.endsWith(':inventory')) return byLabel.inventory ?? { items: [], versions: [] };
    if (label.endsWith(':reproduce')) return byLabel.reproduce ?? { reproduces: true, note: 'builds clean' };
    return {};
  }
  agent.calls = calls;
  return agent;
}

/** A stubbed Wave-5 research coordinator that records deepArchaeology() calls. */
function stubResearch(findings = [{ id: 'ARCH-1', claim: 'legacy auth is hand-rolled', source: 'R1' }]) {
  const digs = [];
  return {
    digs,
    async deepArchaeology({ projectDir } = {}) {
      digs.push(projectDir);
      return { invoked: true, kind: 'tier3-archaeology', findings };
    },
  };
}

// --- tier selection ---------------------------------------------------------

test('correct tier selection by input (greenfield / T1 docs-only / T2 repo / T3 large|contested)', () => {
  assert.equal(selectTier({}).tier, TIERS.GREENFIELD, 'no project ⇒ greenfield');
  assert.equal(selectTier({ kind: 'greenfield' }).tier, TIERS.GREENFIELD);
  assert.equal(selectTier({ docs: ['plan-v1.md', 'plan-v2.md'] }).tier, TIERS.TIER1, 'docs-only ⇒ Tier 1');
  assert.equal(selectTier({ repoDir: 'C:/dev/legacy' }).tier, TIERS.TIER2, 'a repo ⇒ Tier 2');
  assert.equal(selectTier({ repoDir: 'C:/dev/legacy', large: true }).tier, TIERS.TIER3, 'large ⇒ Tier 3');
  assert.equal(selectTier({ docs: ['a.md'], contested: true }).tier, TIERS.TIER3, 'contested ⇒ Tier 3');
});

// --- greenfield framing shape (done-when) -----------------------------------

test('greenfield framing returns the full Oranges shape (North Star + criteria + Non-Goals + risk taxonomy + foresight)', async () => {
  const agent = stubAgent();
  const framing = await runFraming({ agent, intent: INTENT });

  assert.equal(framing.northStar, NORTH_STAR);
  assert.ok(Array.isArray(framing.criteria) && framing.criteria.length >= 1, 'testable criteria');
  assert.ok(Array.isArray(framing.nonGoals), 'Non-Goals');
  assert.ok(Array.isArray(framing.riskTaxonomy) && framing.riskTaxonomy[0].risk, 'risk taxonomy {risk,mitigation}');
  assert.equal(typeof framing.foresightBrief, 'string', 'foresight brief');
  assert.equal(framing.reverseEngineered, false, 'greenfield framing is not reverse-engineered');

  // The framing pass embeds the intent and is schema-forced.
  assert.ok(agent.calls[0].prompt.includes(INTENT), 'the intent reaches the framing prompt');
  assert.equal(agent.calls[0].opts.schema, FRAMING_SCHEMA);
  assert.match(agent.calls[0].prompt, /Parable of the Oranges/);
});

test('framing HALTs when the pass yields no candidate North Star (never a silent pass)', async () => {
  const agent = stubAgent({ framing: { criteria: ['x'] } }); // no northStar
  await assert.rejects(() => runFraming({ agent, intent: INTENT }), (e) => e instanceof HaltError);
});

// --- Tier 1: docs-only runs NO archaeology (G/W/T) --------------------------

test('Given docs-only input, when the tier is chosen, then Tier 1 runs and NO archaeology is delegated', async () => {
  const agent = stubAgent({ inventory: { items: [{ id: 'i1', fact: 'plan v2 is latest', label: INGEST_LABELS.CONFIRMED }], versions: ['v1', 'v2'] } });
  const research = stubResearch();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-intake-'));

  const manifest = await runIngest({ tier: TIERS.TIER1, input: { docs: ['v1.md', 'v2.md'] }, agent, research, intakeDir: dir });

  assert.equal(manifest.tier, TIERS.TIER1);
  assert.equal(manifest.archaeologyRun, false, 'Tier 1 delegates no archaeology');
  assert.equal(research.digs.length, 0, 'researchPrime deep-archaeology was NOT called');
  assert.deepEqual(manifest.versions, ['v1', 'v2'], 'dedupe records the conflicting versions');
  // Tier 1 does only the inventory call (no reproduce probe).
  assert.equal(agent.calls.filter((c) => (c.opts.label || '').endsWith(':reproduce')).length, 0);
  // The manifest landed in plans/intake/.
  assert.ok(fs.existsSync(manifest.manifestPath), 'manifest written to the intake dir');
  assert.equal(JSON.parse(fs.readFileSync(manifest.manifestPath, 'utf8')).tier, TIERS.TIER1);
  fs.rmSync(dir, { recursive: true, force: true });
});

// --- Tier 2: no test ⇒ Inferred-untested, never Confirmed -------------------

test('Tier 2 reproduce-first downgrades a Confirmed-but-untested claim to Inferred', async () => {
  const agent = stubAgent({
    inventory: {
      items: [
        { id: 'tested', fact: 'login works', label: INGEST_LABELS.CONFIRMED, tested: true },
        { id: 'untested', fact: 'export works', label: INGEST_LABELS.CONFIRMED, tested: false },
      ],
    },
    reproduce: { reproduces: false, note: 'build fails' },
  });
  const manifest = await runIngest({ tier: TIERS.TIER2, input: { repoDir: 'C:/dev/legacy' }, agent });

  const byId = Object.fromEntries(manifest.items.map((i) => [i.id, i]));
  assert.equal(byId.tested.label, INGEST_LABELS.CONFIRMED, 'a test-backed claim stays Confirmed');
  assert.equal(byId.untested.label, INGEST_LABELS.INFERRED, 'no test ⇒ downgraded to Inferred');
  assert.match(byId.untested.note, /untested/i);
  assert.equal(manifest.reproduces, false, 'reproduce-first result is recorded');
});

// --- Tier 3: delegates deep archaeology to researchPrime ----------------------

test('Tier 3 delegates deep archaeology to the researchPrime lane and folds its findings in', async () => {
  const agent = stubAgent({ inventory: { items: [] } });
  const research = stubResearch([{ id: 'ARCH-9', claim: 'undocumented cron job', source: 'R9' }]);
  const manifest = await runIngest({ tier: TIERS.TIER3, input: { repoDir: 'C:/dev/legacy', large: true }, agent, research });

  assert.equal(manifest.archaeologyRun, true);
  assert.deepEqual(research.digs, ['C:/dev/legacy'], 'archaeology ran for the project dir');
  const arch = manifest.items.find((i) => i.from === 'tier3-archaeology');
  assert.ok(arch && arch.label === INGEST_LABELS.INFERRED, 'archaeology findings fold in as Inferred');
  assert.match(arch.fact, /cron job/);
});

test('Tier 3 without a research coordinator HALTs (Crucible never re-implements the pipeline)', async () => {
  const agent = stubAgent({ inventory: { items: [] } });
  await assert.rejects(
    () => runIngest({ tier: TIERS.TIER3, input: { repoDir: 'C:/dev/legacy', large: true }, agent, research: null }),
    (e) => e instanceof HaltError,
  );
});

// --- label gating (done-when) ----------------------------------------------

test('label gating: a clean inventory is lockable; a criterion-touching Gap blocks', () => {
  const clean = evaluateIngestGate({ items: [{ id: 'a', label: INGEST_LABELS.CONFIRMED }, { id: 'b', label: INGEST_LABELS.INFERRED }] });
  assert.equal(clean.lockable, true);
  assert.equal(clean.halt, null);

  const blocked = evaluateIngestGate({ items: [{ id: 'g', label: INGEST_LABELS.GAP, touchesCriterion: 'criterion #1' }] });
  assert.equal(blocked.lockable, false);
  assert.equal(blocked.criterionGaps.length, 1);
  assert.ok(blocked.halt instanceof HaltError);
});

test('label gating: an irresolvable / people-only Gap blocks (never a silent RAID assumption)', () => {
  const peopleOnly = evaluateIngestGate({ items: [{ id: 'g', label: INGEST_LABELS.GAP, peopleOnly: true }] });
  assert.equal(peopleOnly.lockable, false);
  assert.equal(peopleOnly.irresolvableGaps.length, 1);
  assert.equal(peopleOnly.halt.pending_action, 'surface-people-only-gap');

  const unresolvable = evaluateIngestGate({ items: [{ id: 'g', label: INGEST_LABELS.GAP, resolvable: false }] });
  assert.equal(unresolvable.lockable, false);

  // A Gap that touches no criterion AND is resolvable does not block the lock.
  const benign = evaluateIngestGate({ items: [{ id: 'g', label: INGEST_LABELS.GAP, resolvable: true }] });
  assert.equal(benign.lockable, true);
});

// --- the lock gate (done-when) ---------------------------------------------

test('the lock gate HALTs until approved, then locks and activates drift detection', () => {
  const framing = { northStar: NORTH_STAR, criteria: ['c1'] };

  // Greenfield (no ingest gate): unapproved ⇒ HALT for the user to lock.
  let halt;
  try {
    lockNorthStar({ framing, approved: false });
  } catch (e) {
    halt = e;
  }
  assert.ok(halt instanceof HaltError, 'unapproved lock HALTs');
  assert.equal(halt.pending_action, 'north-star-lock', 'names the canonical lock gate');

  // Approved ⇒ locked + drift detection now active (§9).
  const locked = lockNorthStar({ framing, approved: true });
  assert.equal(locked.locked, true);
  assert.equal(locked.gate, 'north-star-lock');
  assert.equal(locked.northStar, NORTH_STAR);
  assert.equal(locked.driftDetectionActive, true);
});

test('the lock gate requires an answered salvage question on brownfield (never scored)', () => {
  const framing = { northStar: NORTH_STAR, criteria: ['c1'] };
  const ingestGate = evaluateIngestGate({ items: [{ id: 'a', label: INGEST_LABELS.CONFIRMED }], brownfield: true });

  // Brownfield, approved, but no salvage answer ⇒ HALT on the salvage question.
  let halt;
  try {
    lockNorthStar({ framing, ingestGate, salvageAnswer: null, approved: true });
  } catch (e) {
    halt = e;
  }
  assert.ok(halt instanceof HaltError);
  assert.equal(halt.pending_action, 'salvage-vs-rewrite');

  // With the user's answer it locks.
  const locked = lockNorthStar({ framing, ingestGate, salvageAnswer: 'salvage', approved: true });
  assert.equal(locked.locked, true);
});

test('salvage-vs-rewrite is surfaced as a user question and is NEVER scored', () => {
  const q = salvageVsRewriteQuestion({ asIs: { items: [{ label: 'Confirmed' }, { label: 'Gap' }], reproduces: false } });
  assert.equal(q.kind, 'user-gate-question');
  assert.equal(q.scored, false, 'Crucible never scores salvage-vs-rewrite');
  assert.equal(q.facts.confirmed, 1);
  assert.equal(q.facts.gaps, 1);
  assert.equal(q.facts.reproduces, false);
  assert.match(q.note, /UNVERIFIED/);
});

// --- end-to-end: greenfield to lock + the criterion-Gap HALT (G/W/T) --------

test('runStage0 greenfield: frames then locks (with approval), no ingest', async () => {
  const agent = stubAgent();
  const research = stubResearch();
  const out = await runStage0({ intent: INTENT, input: {}, agent, research, approved: true });

  assert.equal(out.greenfield, true);
  assert.equal(out.tier, TIERS.GREENFIELD);
  assert.equal(out.ingest, null, 'greenfield runs no ingest');
  assert.equal(out.lock.locked, true);
  assert.equal(out.lock.driftDetectionActive, true);
  assert.equal(research.digs.length, 0, 'greenfield delegates no archaeology');
});

test('Given a criterion-touching Gap, then Stage 0 HALTs rather than locking', async () => {
  const agent = stubAgent({
    inventory: { items: [{ id: 'gap', fact: 'auth model unknown', label: INGEST_LABELS.GAP, touchesCriterion: 'security criterion' }] },
    reproduce: { reproduces: null },
  });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-intake-'));

  await assert.rejects(
    () => runStage0({ intent: INTENT, input: { repoDir: 'C:/dev/legacy' }, agent, intakeDir: dir, salvageAnswer: 'salvage', approved: true }),
    (e) => e instanceof HaltError && e.pending_action === 'resolve-criterion-gap',
  );
  // The ingest manifest was still persisted before the HALT (the human reviews it).
  assert.ok(fs.existsSync(path.join(dir, 'manifest.json')), 'manifest persisted before the HALT');
  fs.rmSync(dir, { recursive: true, force: true });
});

// --- wiring guards ----------------------------------------------------------

test('runFraming / runIngest HALT without an agent() seam, and INGEST_SCHEMA is exported', async () => {
  await assert.rejects(() => runFraming({ intent: INTENT }), (e) => e instanceof HaltError);
  await assert.rejects(() => runIngest({ tier: TIERS.TIER1, input: {} }), (e) => e instanceof HaltError);
  assert.equal(typeof INGEST_SCHEMA, 'object');
});
