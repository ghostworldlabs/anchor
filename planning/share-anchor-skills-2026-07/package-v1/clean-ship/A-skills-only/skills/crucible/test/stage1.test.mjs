// test/stage1.test.mjs — Wave 7 gate for Stage 1: the Master Plan protocol.
//
// Drives bin/stage1.mjs with an INJECTED (stubbed) agent seam — no subprocess, no
// live model — and proves the done-when + G/W/T:
//   · the Oranges brainstorm runs in the MANDATORY order assumption-map → premortem
//     → ideation (and the premortem is handed the mapped assumptions);
//   · BATCH idea-triage routes integrate / Grasscatcher / drop by the inclusion test;
//   · G/W/T — an out-of-scope idea lands in the Grasscatcher and the phased plan does
//     NOT absorb it;
//   · the phased plan carries near-term specifics (and HALTs when it has none);
//   · the Shark-Tank loop drives sharkfood → fix → sharkfood → dry → Judge → gate;
//   · the user-approval HALT gate (master-plan-approval) HALTs until approved;
//   · done-when — a scripted greenfield intent runs through Stage 1 to an approved
//     phased Master Plan, exercising one full Shark-Tank loop.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  TRIAGE_DISPOSITIONS,
  ASSUMPTION_SCHEMA,
  PREMORTEM_SCHEMA,
  BRAINSTORM_IDEAS_SCHEMA,
  PHASED_PLAN_SCHEMA,
  runAssumptionMap,
  runPremortem,
  runBrainstorm,
  triageDisposition,
  triageIdeas,
  appendGrasscatcher,
  buildPhasedPlan,
  renderMasterPlanDraft,
  runMasterPlanLoop,
  approveMasterPlan,
  runStage1,
  reviseDraft,
  REVISE_MARKDOWN_BYTES,
} from '../bin/stage1.mjs';

const NORTH_STAR = 'STAGE1-NS-SENTINEL: ship a vetted, Foreman-ready plan that never drifts.';
const CRITERIA = ['emits a zero-HALT doc-trio', 'both stages converge'];

// A distinctive idea text so we can prove the plan never absorbs the out-of-scope one.
const OUT_OF_SCOPE = 'OUT-OF-SCOPE-SENTINEL: add a built-in pizza-ordering side panel';
const IN_SCOPE = 'IN-SCOPE-SENTINEL: a forge-proof well-formedness gate';

const DEFAULT_IDEAS = [
  { id: 'i1', idea: IN_SCOPE, traces_to_north_star: 'yes', criterion: 'emits a zero-HALT doc-trio', tag: 'refinement' },
  { id: 'i2', idea: OUT_OF_SCOPE, traces_to_north_star: 'no', tag: 'out-of-scope' },
  { id: 'i3', idea: 'redundant restatement', disposition: 'drop' },
];

/**
 * A label-routed stub agent covering every Stage-1 sub-step. The Shark Tank is
 * ROUND-AWARE: round 1 raises an agreed BLOCKER (Skeptic + Contrarian on the same
 * normalized topic), every later round is clean ⇒ a dry round. Records all calls.
 */
function makeStage1Agent({ ideas = DEFAULT_IDEAS, phases = null, blockedUntilRound = 2, distinctBlockerPerRound = false } = {}) {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    const label = opts.label || '';

    if (label === 'stage1:assumptions') {
      return { assumptions: [{ id: 'a1', assumption: 'the subscription seam suffices', criticality: 'high' }] };
    }
    if (label === 'stage1:premortem') {
      return { failureModes: [{ id: 'f1', mode: 'drift past the North Star', cause: 'no lock', mitigation: 'lock + tag changes' }] };
    }
    if (label === 'stage1:ideas') {
      return { ideas };
    }
    if (label === 'stage1:phased-plan') {
      return {
        summary: 'a phased plan',
        phases: phases ?? [
          { name: 'Engine skeleton', rationale: 'stand it up', nearTermSpecifics: ['import foreman-lib', IN_SCOPE], deferred: ['enhanced cross-model mode'] },
        ],
      };
    }
    if (label.startsWith('stage1:revise')) {
      const r = label.split('r').pop();
      return { draft: `# Master Plan (draft) — revised v${r}\n\n**North Star:** ${NORTH_STAR}\n`, changelog: ['addressed the blocker'] };
    }
    if (label.startsWith('shark:')) {
      const parts = label.split(':'); // shark:Role:rN
      const role = parts[1];
      const round = parseInt(String(parts[2] || 'r0').slice(1), 10) || 0;
      if (round < blockedUntilRound && (role === 'Skeptic' || role === 'Contrarian')) {
        // A distinct topic per round keeps every round a NEW blocker (defeats anti-
        // oscillation) so the cap test can never converge.
        const topic = distinctBlockerPerRound ? `lock gate underspecified r${round}` : 'lock gate underspecified';
        return {
          answerable: 'yes',
          findings: [{ severity: 'BLOCKER', topic, section: 'gates', tag: 'refinement', traces_to_north_star: 'yes', criterion: 'C2', message: 'lock criteria missing' }],
        };
      }
      return { answerable: 'yes', findings: [] };
    }
    if (label.startsWith('synthesizer:direct')) {
      return { lean: 'lockable', openDisputes: [], riskRegister: [], probingBrief: 'press the lock gate', suggestions: [] };
    }
    if (label.includes('fresh-eyes')) {
      return { lean: 'lockable', concerns: [], note: 'cold read concurs' };
    }
    if (label.startsWith('judge:')) {
      return { decision: 'CONVERGED', reasons: ['dry round, no open blocker'] };
    }
    return {};
  }
  agent.calls = calls;
  return agent;
}

// --- (1) brainstorm mandatory order -----------------------------------------

test('the brainstorm runs in the MANDATORY order: assumption-map → premortem → ideation', async () => {
  const agent = makeStage1Agent();
  const out = await runBrainstorm({ agent, northStar: NORTH_STAR, criteria: CRITERIA });

  assert.ok(out.assumptions.length >= 1, 'assumptions mapped');
  assert.ok(out.premortem.length >= 1, 'premortem produced');
  assert.equal(out.ideas.length, DEFAULT_IDEAS.length, 'ideas generated');

  const labels = agent.calls.map((c) => c.opts.label);
  const iA = labels.indexOf('stage1:assumptions');
  const iP = labels.indexOf('stage1:premortem');
  const iI = labels.indexOf('stage1:ideas');
  assert.ok(iA >= 0 && iP >= 0 && iI >= 0, 'all three steps ran');
  assert.ok(iA < iP, 'assumption-map runs BEFORE the premortem');
  assert.ok(iP < iI, 'premortem runs BEFORE ideation');

  // The premortem is handed the mapped assumptions (the order is a data dependency).
  const premortemCall = agent.calls.find((c) => c.opts.label === 'stage1:premortem');
  assert.match(premortemCall.prompt, /the subscription seam suffices/, 'premortem embeds the mapped assumptions');
  assert.equal(premortemCall.opts.schema, PREMORTEM_SCHEMA);
});

test('runAssumptionMap / runPremortem are schema-forced and North-Star-bound', async () => {
  const agent = makeStage1Agent();
  const assumptions = await runAssumptionMap({ agent, northStar: NORTH_STAR, criteria: CRITERIA });
  assert.equal(agent.calls[0].opts.schema, ASSUMPTION_SCHEMA);
  assert.match(agent.calls[0].prompt, /STAGE1-NS-SENTINEL/);

  await runPremortem({ agent, northStar: NORTH_STAR, assumptions });
  assert.equal(agent.calls[1].opts.schema, PREMORTEM_SCHEMA);
});

// --- (2) batch triage + the inclusion test ----------------------------------

test('triageDisposition routes by the inclusion test (explicit disposition wins; non-tracing ⇒ Grasscatcher)', () => {
  assert.equal(triageDisposition({ disposition: 'drop' }), TRIAGE_DISPOSITIONS.DROP, 'explicit disposition wins');
  assert.equal(triageDisposition({ tag: 'out-of-scope' }), TRIAGE_DISPOSITIONS.GRASSCATCHER);
  assert.equal(triageDisposition({ traces_to_north_star: 'no' }), TRIAGE_DISPOSITIONS.GRASSCATCHER, 'a non-tracing idea is out-of-scope');
  assert.equal(triageDisposition({ traces_to_north_star: 'yes', tag: 'refinement' }), TRIAGE_DISPOSITIONS.INTEGRATE);
  assert.equal(triageDisposition({ idea: 'unlabeled' }), TRIAGE_DISPOSITIONS.INTEGRATE, 'benefit of the doubt ⇒ integrate');
});

test('triageIdeas BATCH-routes the whole brainstorm and appends parked ideas to the Grasscatcher', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-gc-'));
  const gcPath = path.join(dir, 'GRASSCATCHER.md');
  try {
    const t = triageIdeas({ ideas: DEFAULT_IDEAS, grasscatcherPath: gcPath });
    assert.equal(t.batch, true);
    assert.equal(t.integrate.length, 1);
    assert.equal(t.integrate[0].idea, IN_SCOPE);
    assert.equal(t.grasscatcher.length, 1);
    assert.equal(t.grasscatcher[0].idea, OUT_OF_SCOPE);
    assert.equal(t.dropped.length, 1);

    assert.ok(fs.existsSync(gcPath), 'parked ideas appended to the Grasscatcher');
    assert.match(fs.readFileSync(gcPath, 'utf8'), /OUT-OF-SCOPE-SENTINEL/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('appendGrasscatcher creates the file when missing and appends (never truncates)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-gc2-'));
  const gcPath = path.join(dir, 'nested', 'GRASSCATCHER.md');
  try {
    appendGrasscatcher(gcPath, [{ idea: 'first parked' }]);
    appendGrasscatcher(gcPath, [{ idea: 'second parked' }]);
    const body = fs.readFileSync(gcPath, 'utf8');
    assert.match(body, /first parked/);
    assert.match(body, /second parked/, 'second append did not truncate the first');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// --- (3) phased plan --------------------------------------------------------

test('buildPhasedPlan returns phases with near-term specifics and absorbs only the given ideas', async () => {
  const agent = makeStage1Agent();
  const plan = await buildPhasedPlan({ agent, northStar: NORTH_STAR, criteria: CRITERIA, ideas: [{ id: 'i1', idea: IN_SCOPE }] });
  assert.ok(plan.phases.length >= 1);
  assert.ok(plan.phases[0].nearTermSpecifics.length >= 1, 'near-term specifics present');
  assert.ok(plan.phases[0].deferred.length >= 1, 'the rest deferred explicitly');
  assert.equal(agent.calls[0].opts.schema, PHASED_PLAN_SCHEMA);
});

test('buildPhasedPlan HALTs when the plan has no near-term specifics (cannot seed Stage 2)', async () => {
  const agent = makeStage1Agent({ phases: [{ name: 'vague', nearTermSpecifics: [], deferred: ['everything'] }] });
  await assert.rejects(
    () => buildPhasedPlan({ agent, northStar: NORTH_STAR, ideas: [] }),
    (e) => e instanceof HaltError && e.pending_action === 'rerun-phased-plan',
  );
});

// --- (4) the Shark-Tank loop ------------------------------------------------

test('runMasterPlanLoop drives sharkfood → fix → sharkfood → dry → Judge → model-side convergence', async () => {
  const agent = makeStage1Agent({ blockedUntilRound: 2 });
  const loop = await runMasterPlanLoop({
    agent, northStar: NORTH_STAR, criteria: CRITERIA,
    draft: '# Master Plan (draft) v1', acceptanceCriteria: ['every wave has a done-when'],
  });

  assert.equal(loop.converged, true);
  assert.equal(loop.modelSideLockable, true);
  assert.equal(loop.roundsRun, 2, 'one full loop: a blocked round then a dry round');
  assert.equal(loop.rounds[0].verdict.verdict, 'BLOCKED', 'round 1 found the agreed blocker');
  assert.equal(loop.lastVerdict.dry, true, 'the final round is dry');
  assert.equal(loop.judgeVerdict.decision, 'CONVERGED');
  assert.equal(loop.gate.modelSideLockable, true);

  // The fresh-eyes cold pass was a genuine no-context isolation (Wave-3 oracle).
  assert.equal(loop.oracle.isolated, true, 'fresh-eyes cold pass received no Director context');
  assert.equal(loop.reconcile.route, 'concur');
});

test('runMasterPlanLoop HALTs when it hits the round cap (the safety ceiling)', async () => {
  // Sharks raise a NEW blocker every round ⇒ never dry ⇒ the cap HALTs.
  const agent = makeStage1Agent({ blockedUntilRound: 99, distinctBlockerPerRound: true });
  await assert.rejects(
    () => runMasterPlanLoop({ agent, northStar: NORTH_STAR, draft: 'v1', roundCap: 2 }),
    (e) => e instanceof HaltError && e.pending_action === 'stage1-round-cap',
  );
});

test('T5 REGRESSION: the round-cap HALT carries the BEST DRAFT + open findings and persists them — never discards the run', async () => {
  // The one full live run (zombie-hunter, journal 0001) burned ~30 calls into
  // this cap and emitted NOTHING; the journal proposed exactly this fix.
  const agent = makeStage1Agent({ blockedUntilRound: 99, distinctBlockerPerRound: true });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-cap-'));
  try {
    let halt = null;
    try {
      await runMasterPlanLoop({ agent, northStar: NORTH_STAR, draft: 'v1', roundCap: 2, artifactsDir: dir });
    } catch (e) { halt = e; }
    assert.ok(halt instanceof HaltError && halt.pending_action === 'stage1-round-cap', 'still a HALT — the user stays the convergence authority');
    assert.ok(halt.best_draft, 'the HALT carries the best-draft payload');
    assert.match(halt.best_draft.draft, /revised/, "the attached draft reflects the loop's refinement rounds, not the v1 input");
    assert.equal(halt.best_draft.roundsRun, 2);
    assert.ok(halt.best_draft.openFindings.length >= 1, 'the open findings ride along');
    assert.match(halt.reason, /nothing was discarded/);
    // and the artifacts are persisted for the human to review
    assert.match(fs.readFileSync(path.join(dir, 'BEST-DRAFT.md'), 'utf8'), /revised/);
    const open = JSON.parse(fs.readFileSync(path.join(dir, 'OPEN-FINDINGS.json'), 'utf8'));
    assert.ok(Array.isArray(open) && open.length >= 1);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

// --- (5) the user-approval HALT gate ----------------------------------------

test('approveMasterPlan HALTs at the canonical master-plan-approval gate until approved', () => {
  const loop = { modelSideLockable: true, draft: 'the converged plan', roundsRun: 2 };

  let halt;
  try {
    approveMasterPlan({ loop, approved: false });
  } catch (e) {
    halt = e;
  }
  assert.ok(halt instanceof HaltError, 'unapproved ⇒ HALT');
  assert.equal(halt.pending_action, 'master-plan-approval', 'names the canonical stage1->stage2 gate');

  const ok = approveMasterPlan({ loop, approved: true });
  assert.equal(ok.approved, true);
  assert.equal(ok.gate, 'master-plan-approval');
  assert.equal(ok.masterPlan, 'the converged plan');
});

test('approveMasterPlan refuses to approve a not-yet-converged loop', () => {
  assert.throws(
    () => approveMasterPlan({ loop: { modelSideLockable: false }, approved: true }),
    (e) => e instanceof HaltError && e.pending_action === 'stage1-not-converged',
  );
});

// --- done-when: end-to-end through Stage 1 ----------------------------------

test('done-when: a scripted greenfield intent runs through Stage 1 to an approved Master Plan (one full Shark-Tank loop)', async () => {
  const agent = makeStage1Agent({ blockedUntilRound: 2 });
  const out = await runStage1({
    agent, northStar: NORTH_STAR, criteria: CRITERIA,
    acceptanceCriteria: ['every wave has a done-when'], approved: true,
  });

  assert.ok(out.brainstorm.assumptions.length >= 1);
  assert.equal(out.loop.roundsRun, 2, 'one full Shark-Tank loop was exercised');
  assert.equal(out.approval.approved, true);
  assert.equal(out.approval.gate, 'master-plan-approval');
  assert.ok(out.approval.masterPlan.includes('North Star') || out.approval.masterPlan.includes(NORTH_STAR));
});

test('Stage 1 HALTs at the approval gate when unapproved (the user is the convergence authority)', async () => {
  const agent = makeStage1Agent({ blockedUntilRound: 2 });
  await assert.rejects(
    () => runStage1({ agent, northStar: NORTH_STAR, criteria: CRITERIA, approved: false }),
    (e) => e instanceof HaltError && e.pending_action === 'master-plan-approval',
  );
});

// --- G/W/T: out-of-scope idea → Grasscatcher, NOT absorbed into the plan -----

test('Given brainstorm output with an out-of-scope idea, when batch-triage runs, then it lands in the Grasscatcher and the plan does not absorb it', async () => {
  const agent = makeStage1Agent({ blockedUntilRound: 2 });
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'crucible-gwt-'));
  const gcPath = path.join(dir, 'GRASSCATCHER.md');
  try {
    const out = await runStage1({
      agent, northStar: NORTH_STAR, criteria: CRITERIA,
      grasscatcherPath: gcPath, approved: true,
    });

    // It landed in the Grasscatcher.
    assert.ok(out.triage.grasscatcher.some((i) => i.idea === OUT_OF_SCOPE), 'out-of-scope idea parked');
    assert.ok(!out.triage.integrate.some((i) => i.idea === OUT_OF_SCOPE), 'not in the integrate bucket');
    assert.match(fs.readFileSync(gcPath, 'utf8'), /OUT-OF-SCOPE-SENTINEL/);

    // The plan never absorbed it: the phased-plan prompt saw only the integrated idea.
    const planCall = agent.calls.find((c) => c.opts.label === 'stage1:phased-plan');
    assert.ok(planCall, 'the phased-plan pass ran');
    assert.ok(planCall.prompt.includes(IN_SCOPE), 'the integrated idea reached the plan');
    assert.ok(!planCall.prompt.includes(OUT_OF_SCOPE), 'the out-of-scope idea did NOT reach the plan');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// --- rendering + wiring guards ----------------------------------------------

test('renderMasterPlanDraft renders the North Star, criteria, and phases', () => {
  const draft = renderMasterPlanDraft({
    northStar: NORTH_STAR, criteria: CRITERIA,
    summary: 'sum', phases: [{ name: 'P1', rationale: 'r', nearTermSpecifics: ['s1'], deferred: ['d1'] }],
  });
  assert.match(draft, /STAGE1-NS-SENTINEL/);
  assert.match(draft, /Phase 1 — P1/);
  assert.match(draft, /Near-term specifics/);
  assert.match(draft, /Deferred/);
});

test('Stage-1 entrypoints HALT without an agent() seam or a locked North Star', async () => {
  await assert.rejects(() => runBrainstorm({ northStar: NORTH_STAR }), (e) => e instanceof HaltError);
  await assert.rejects(() => runStage1({ agent: () => {}, northStar: null }), (e) => e instanceof HaltError);
  assert.equal(typeof BRAINSTORM_IDEAS_SCHEMA, 'object');
});

// ---------------------------------------------------------------------------
// reviseDraft — the schema-FIRST / raw-text-fallback contract (journal 0002).
// The structured {draft, changelog} envelope is the primary ask (the changelog
// briefs the next round's Sharks); raw fenced markdown is the FALLBACK ONLY.
// ---------------------------------------------------------------------------

test('reviseDraft asks schema-FIRST and keeps the structured changelog when the seam honors it', async () => {
  let seenOpts = null;
  const agent = async (_prompt, opts) => {
    seenOpts = opts;
    return { draft: 'REVISED-BY-SCHEMA', changelog: ['tightened wave 2', 'dropped the dead gate'] };
  };
  const out = await reviseDraft({ agent, northStar: NORTH_STAR, draft: 'OLD-DRAFT', verdict: { blockers: [] }, direction: null, round: 1 });
  assert.ok(seenOpts && typeof seenOpts.schema === 'object', 'reviseDraft must PASS the REVISE_SCHEMA (schema-first contract)');
  assert.equal(out.draft, 'REVISED-BY-SCHEMA');
  assert.deepEqual(out.changelog, ['tightened wave 2', 'dropped the dead gate']);
});

test('reviseDraft raw-text fallback: a fenced-markdown reply recovers the draft, changelog honestly omitted', async () => {
  const agent = async () => 'Sure, here is the revision:\n```markdown\n# Revised Plan\nBetter now.\n```\nDone.';
  const out = await reviseDraft({ agent, northStar: NORTH_STAR, draft: 'OLD-DRAFT', verdict: { blockers: [] }, direction: null, round: 2 });
  assert.equal(out.draft, '# Revised Plan\nBetter now.');
  assert.equal(out.changelog.length, 1);
  assert.match(out.changelog[0], /changelog omitted/i);
});

test('reviseDraft goes MARKDOWN-FIRST for a large draft (EI1: schema-less, full-size raw markdown recovered)', async () => {
  let seenOpts = null;
  const bigDraft = '# Big Plan\n' + 'x'.repeat(REVISE_MARKDOWN_BYTES + 100);
  const revisedBody = '# Revised Big Plan\n' + 'y'.repeat(REVISE_MARKDOWN_BYTES); // full-size (passes the guard)
  const agent = async (_prompt, opts) => {
    seenOpts = opts;
    return '```markdown\n' + revisedBody + '\n```';
  };
  const out = await reviseDraft({ agent, northStar: NORTH_STAR, draft: bigDraft, verdict: { blockers: [] }, direction: null, round: 4 });
  assert.ok(seenOpts && seenOpts.schema === undefined, 'a large draft must be revised schema-LESS (markdown-first, no fragile large-JSON serialization)');
  assert.equal(out.draft, revisedBody);
  assert.equal(out.changelog.length, 1);
  assert.match(out.changelog[0], /markdown-first/i);
});

test('reviseDraft completeness guard: a markdown-first PARTIAL/delta is REJECTED and the prior draft kept (EI1 guard)', async () => {
  const bigDraft = '# Big Plan\n' + 'x'.repeat(REVISE_MARKDOWN_BYTES + 100);
  // The Stage-1e failure mode: the model returns only a tiny delta instead of the full plan.
  const agent = async () => '```markdown\n[edits ONLY Phase 9; Phases 1-8 carried forward UNCHANGED, not reproduced here]\n## Phase 9\ntweaked.\n```';
  const out = await reviseDraft({ agent, northStar: NORTH_STAR, draft: bigDraft, verdict: { blockers: [] }, direction: null, round: 5 });
  assert.equal(out.draft, bigDraft, 'a catastrophically-small markdown-first revise must be rejected — prior draft kept, plan not lost');
  assert.deepEqual(out.changelog, []);
});

test('reviseDraft raw-text fallback: unfenced non-empty text is taken trimmed', async () => {
  const agent = async () => '   # Revised Plan v2\nno fences here.  ';
  const out = await reviseDraft({ agent, northStar: NORTH_STAR, draft: 'OLD-DRAFT', verdict: { blockers: [] }, direction: null, round: 2 });
  assert.equal(out.draft, '# Revised Plan v2\nno fences here.');
});

test('reviseDraft dead-seam reply (null / empty) keeps the prior draft — a round is never lost', async () => {
  for (const reply of [null, undefined, '']) {
    const out = await reviseDraft({ agent: async () => reply, northStar: NORTH_STAR, draft: 'OLD-DRAFT', verdict: { blockers: [] }, direction: null, round: 3 });
    assert.equal(out.draft, 'OLD-DRAFT');
    assert.deepEqual(out.changelog, []);
  }
});
