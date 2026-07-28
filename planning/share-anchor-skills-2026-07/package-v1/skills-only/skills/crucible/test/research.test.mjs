// test/research.test.mjs — Wave 5 gate for researchPrime integration.
// Drives the cost-guarded coordinator through an INJECTED (stubbed) researchPrime
// transport — no subprocess — and proves: researchPrime runs ONCE up-front
// (idempotent), per-round invocation fires ONLY on a genuinely new candidate (the
// novelty cost-guard), the Tier-3 deep-archaeology lane delegates (and is guarded),
// and findings reach BOTH consumers — the Analyst Shark (only the Analyst) and the
// Synthesizer. Exercises REAL source in bin/research.mjs (+ the Analyst wiring in
// bin/shark-tank.mjs).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  RESEARCH_SCHEMA,
  researchSpecPrompt,
  defaultRunResearch,
  summarizeFindings,
  makeResearch,
} from '../bin/research.mjs';
import { runSharkTank } from '../bin/shark-tank.mjs';
import { makeSynthesizer } from '../bin/synthesizer.mjs';

const NORTH_STAR = 'NORTH-STAR-SENTINEL: ship a Foreman-ready plan that never drifts.';

/**
 * A stub researchPrime transport: records every spec it was handed and returns a
 * scripted result keyed by the spec mode. Lets the test count actual invocations
 * (the whole point of the cost-guard) with zero subprocesses.
 */
function stubTransport(byMode = {}) {
  const specs = [];
  async function runResearch(spec) {
    specs.push(spec);
    const findings = byMode[spec.mode] ?? [
      { id: `${spec.mode}-F1`, claim: `finding for ${spec.mode}`, confidence: 'CORROBORATED', source: 'E1' },
    ];
    return { runDir: `/tmp/r1-${spec.mode}`, deliverable: null, findings };
  }
  runResearch.specs = specs;
  return runResearch;
}

// --- once up-front (idempotent) --------------------------------------------

test('researchPrime runs ONCE up-front — a second upfront() never re-invokes', async () => {
  const runResearch = stubTransport();
  const research = makeResearch({ runResearch });

  const first = await research.upfront({ northStar: NORTH_STAR, subQuestions: ['weaknesses', 'best-in-class'] });
  assert.equal(first.invoked, true);
  assert.equal(first.kind, 'upfront');
  assert.ok(first.findings.length >= 1, 'up-front findings are returned');

  const second = await research.upfront({ northStar: NORTH_STAR });
  assert.equal(second.invoked, false, 'a second up-front call is idempotent');
  assert.equal(second.reason, 'upfront-already-done');

  assert.equal(runResearch.specs.length, 1, 'researchPrime was invoked exactly once up-front');
  assert.equal(runResearch.specs[0].mode, 'upfront');
});

// --- per-round novelty cost-guard ------------------------------------------

test('per-round invokes ONLY on a genuinely new candidate (the novelty cost-guard)', async () => {
  const runResearch = stubTransport();
  const research = makeResearch({ runResearch });
  await research.upfront({ northStar: NORTH_STAR }); // 1 invocation; the up-front candidate is now "seen"

  // Same candidate as up-front (even reworded) ⇒ NOT new ⇒ SKIP, no re-invoke.
  const repeat = await research.perRound({ candidate: 'ship a Foreman-ready plan that never drifts NORTH-STAR-SENTINEL', round: 1 });
  assert.equal(repeat.invoked, false, 'an unchanged candidate is skipped');
  assert.equal(repeat.reason, 'no-new-candidate');

  // A genuinely new candidate ⇒ invoke.
  const fresh = await research.perRound({ candidate: 'pivot: add a brownfield salvage-vs-rewrite gate', round: 2 });
  assert.equal(fresh.invoked, true, 'a new candidate triggers research');
  assert.equal(fresh.kind, 'per-round');

  // That same new candidate again ⇒ now seen ⇒ SKIP.
  const again = await research.perRound({ candidate: 'pivot: add a brownfield salvage-vs-rewrite gate', round: 3 });
  assert.equal(again.invoked, false);
  assert.equal(again.reason, 'no-new-candidate');

  // An empty candidate is a no-op, not an invocation.
  const empty = await research.perRound({ candidate: '', round: 4 });
  assert.equal(empty.invoked, false);
  assert.equal(empty.reason, 'empty-candidate');

  // Net: up-front (1) + one new candidate (1) = 2 researchPrime runs across 5 calls.
  assert.equal(runResearch.specs.length, 2, 'the cost-guard prevented every redundant re-invoke');
  assert.deepEqual(research.getInvocations().map((r) => r.kind), ['upfront', 'per-round']);
});

// --- Tier-3 deep-archaeology lane (brownfield Stage 0) ----------------------

test('Tier-3 deep-archaeology delegates to researchPrime and is cost-guarded per dir', async () => {
  const runResearch = stubTransport();
  const research = makeResearch({ runResearch });

  const dig = await research.deepArchaeology({ projectDir: 'C:/dev/legacy-thing' });
  assert.equal(dig.invoked, true);
  assert.equal(dig.kind, 'tier3-archaeology');
  assert.equal(runResearch.specs[0].mode, 'tier3-archaeology');
  assert.equal(runResearch.specs[0].projectDir, 'C:/dev/legacy-thing');

  // Re-entering Stage 0 on the same tree does NOT re-excavate.
  const dig2 = await research.deepArchaeology({ projectDir: 'C:/dev/legacy-thing' });
  assert.equal(dig2.invoked, false);
  assert.equal(dig2.reason, 'archaeology-already-run');
  assert.equal(runResearch.specs.length, 1, 'the deep dive ran once for that dir');

  // No projectDir ⇒ HALT (a deep dive with nothing to excavate is a wiring bug).
  await assert.rejects(() => research.deepArchaeology({}), (e) => e instanceof HaltError);
});

// --- findings reach the Synthesizer ----------------------------------------

test('findings reach the Synthesizer: forSynthesizer() payload is embedded in the Director prompt', async () => {
  const SENTINEL = 'RESEARCH-CLAIM-SENTINEL: running code is the most authoritative artifact';
  const runResearch = stubTransport({ upfront: [{ id: 'E2', claim: SENTINEL, confidence: 'CORROBORATED', source: 'E2' }] });
  const research = makeResearch({ runResearch });
  await research.upfront({ northStar: NORTH_STAR });

  // The Synthesizer's direct({research}) embeds the payload verbatim into its prompt.
  const calls = [];
  const agent = async (prompt, opts = {}) => { calls.push({ prompt, opts }); return { lean: 'unknown', openDisputes: [], suggestions: [] }; };
  const synth = makeSynthesizer({ agent, northStar: NORTH_STAR });
  await synth.direct({ round: 1, verdict: { verdict: 'DRY' }, research: research.forSynthesizer() });

  assert.ok(calls[0].prompt.includes(SENTINEL), 'the research claim reaches the Synthesizer prompt');
});

// --- findings reach the Analyst Shark (and ONLY the Analyst) -----------------

test('findings reach the Analyst Shark only: research is embedded in the Analyst prompt, not the others', async () => {
  const SENTINEL = 'RESEARCH-BRIEF-SENTINEL: salvage-vs-rewrite has no verified 40% threshold';
  const runResearch = stubTransport({ upfront: [{ id: 'E8', claim: SENTINEL, confidence: 'CLAIMED', source: 'E8' }] });
  const research = makeResearch({ runResearch });
  await research.upfront({ northStar: NORTH_STAR });

  const calls = [];
  const agent = async (prompt, opts = {}) => { calls.push({ prompt, opts }); return { answerable: 'yes', findings: [] }; };

  await runSharkTank({ agent, northStar: NORTH_STAR, draft: 'a draft', round: 0, research: research.forAnalyst() });

  const byRole = {};
  for (const c of calls) byRole[(c.opts.label || '').split(':')[1]] = c.prompt;
  assert.ok(byRole.Analyst.includes(SENTINEL), 'the Analyst Shark receives the research briefing');
  assert.ok(!byRole.Skeptic.includes(SENTINEL), 'the Skeptic stays research-free');
  assert.ok(!byRole.Contrarian.includes(SENTINEL), 'the Contrarian stays research-free');
});

// --- accumulation across invocations ---------------------------------------

test('getFindings accumulates across up-front + per-round, in arrival order', async () => {
  const runResearch = stubTransport({
    upfront: [{ id: 'U1', claim: 'up-front claim', confidence: 'CORROBORATED' }],
    'per-round': [{ id: 'P1', claim: 'per-round claim', confidence: 'CLAIMED' }],
  });
  const research = makeResearch({ runResearch });
  await research.upfront({ northStar: NORTH_STAR });
  await research.perRound({ candidate: 'a brand-new direction worth researching', round: 1 });

  const ids = research.getFindings().map((f) => f.id);
  assert.deepEqual(ids, ['U1', 'P1']);
  // forAnalyst rolls both into one briefing; forSynthesizer carries the same set.
  assert.match(research.forAnalyst(), /up-front claim/);
  assert.match(research.forAnalyst(), /per-round claim/);
  assert.equal(research.forSynthesizer().findings.length, 2);
});

// --- helpers + the live-seam guard -----------------------------------------

test('summarizeFindings renders confidence + source, and is empty-safe', () => {
  assert.equal(summarizeFindings([]), '(no research findings)');
  const s = summarizeFindings([{ claim: 'X', confidence: 'OBSERVED', source: 'E1' }]);
  assert.match(s, /\[OBSERVED\]/);
  assert.match(s, /src: E1/);
});

test('forAnalyst returns null when there is nothing to brief (no empty research block)', () => {
  const research = makeResearch({ runResearch: stubTransport() });
  assert.equal(research.forAnalyst(), null);
});

test('the live researchPrime seam is bound-or-HALT (never fires by accident)', async () => {
  // No transport, no agent, not enabled ⇒ invoking HALTs (mirrors the agent seam).
  const research = makeResearch({ env: {} });
  await assert.rejects(() => research.upfront({ northStar: NORTH_STAR }), (e) => e instanceof HaltError);
  // The default transport itself HALTs without the env flag + an agent carrier.
  assert.throws(() => defaultRunResearch({ mode: 'upfront' }, { env: {} }), (e) => e instanceof HaltError);
  // The spec prompt instructs the sub-agent to CALL researchPrime, schema-forced.
  assert.match(researchSpecPrompt({ mode: 'upfront' }), /researchPrime/);
  assert.equal(typeof RESEARCH_SCHEMA, 'object');
});
