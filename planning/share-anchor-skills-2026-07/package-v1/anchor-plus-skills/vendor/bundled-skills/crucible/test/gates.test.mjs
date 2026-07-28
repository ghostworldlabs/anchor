// test/gates.test.mjs — Wave 4 gate for the two-gate machinery + drift detector,
// plus the FIRST end-to-end loop proof (round → tally → gate to a verdict).
//
// Proves, exercising REAL source in bin/gates.mjs:
//   - the WELL-FORMEDNESS gate SPAWNS Foreman's locate-plan.mjs and passes on a good
//     doc-trio fixture (real subprocess), FAILs on a malformed one (exit≠0 + captured
//     stderr → forge-proof artifact, no crash), and FAILs cleanly on spawn-ENOENT;
//   - the QUALITY/CONVERGENCE gate gates on dry-round + Judge + no unresolved drift +
//     fresh-eyes concur, and HALTs for user approval before locking;
//   - the DRIFT DETECTOR is post-lock only, tiered (MINOR flag vs MAJOR HALT), with
//     the two-option resolution;
//   - ONE integration test drives a real Shark-Tank round → tally → convergence gate
//     to a verdict (BLOCKED → loop, then DRY + Judge CONVERGED → AWAITING_APPROVAL →
//     approved → CONVERGED).

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  DEFAULT_LOCATE_PLAN,
  runWellFormednessGate,
  evaluateConvergenceGate,
  detectDrift,
  driftTier,
  classifyDriftOption,
  DRIFT_TIERS,
  writeGateArtifact,
} from '../bin/gates.mjs';
import { runSharkTank, tallyFindings } from '../bin/shark-tank.mjs';
import { makeJudge } from '../bin/judge.mjs';

// --- helpers ---------------------------------------------------------------

function mkTmp(prefix) { return fs.mkdtempSync(path.join(os.tmpdir(), prefix)); }
function rm(dir) { try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* best-effort */ } }

/** A stub agent() that returns a scripted reply, recording calls (mirrors the suite). */
function scriptedAgent(reply) {
  const calls = [];
  async function agent(prompt, opts = {}) {
    calls.push({ prompt, opts });
    return typeof reply === 'function' ? reply(prompt, opts) : reply;
  }
  agent.calls = calls;
  return agent;
}

/** Stub agent keyed by Shark role (mirrors shark-tank.test.mjs). */
function sharkAgent(byRole) {
  async function agent(_prompt, opts = {}) {
    const role = (opts.label || '').split(':')[1];
    return { answerable: 'yes', findings: byRole[role] || [] };
  }
  return agent;
}

const NORTH_STAR = 'NORTH-STAR-SENTINEL: ship a Foreman-ready plan that never drifts.';

/**
 * Write a minimal Foreman doc-trio into `dir`, naming all three docs in a
 * foreman.config.json (so locate-plan resolves deterministically, never via the
 * ambiguous heuristic glob). `withWaves:false` omits the `## Wave N` heading so the
 * plan is MALFORMED (parseWaves HALTs → exit 3).
 */
function writeDocTrio(dir, { withWaves = true } = {}) {
  fs.writeFileSync(path.join(dir, 'foreman.config.json'), JSON.stringify({
    docs: { description: 'DESCRIPTION.md', plan: 'PLAN.md', execution_log: 'EXECUTION-LOG.md' },
  }, null, 2));
  fs.writeFileSync(path.join(dir, 'DESCRIPTION.md'), '# Description\nA fixture project.\n');
  fs.writeFileSync(path.join(dir, 'EXECUTION-LOG.md'), '# Execution Log\n');
  // Sleep 0076 package 4: bare `node --test test/` hard-fails locate-plan preflight on Windows.
  // Well-formed fixtures must use the expanding helper or explicit test files.
  const plan = withWaves
    ? '# Plan\n\ntest-command: node scripts/run-all-tests.mjs\n\n## Wave 1 — Bootstrap\n\n**done-when:** bootstrap smoke passes\n\nStand it up.\n'
    : '# Plan\n\ntest-command: node scripts/run-all-tests.mjs\n\n(no wave headings — malformed)\n';
  fs.writeFileSync(path.join(dir, 'PLAN.md'), plan);
}

// === (1) WELL-FORMEDNESS GATE ==============================================

test('the default locate-plan path resolves to Foreman\'s real CLI (sibling import, not a fork)', () => {
  assert.ok(DEFAULT_LOCATE_PLAN.replace(/\\/g, '/').endsWith('foreman/bin/locate-plan.mjs'));
  assert.ok(fs.existsSync(DEFAULT_LOCATE_PLAN), 'spawned resolver exists on disk');
});

test('well-formedness gate PASSES on a good doc-trio (real spawn) and surfaces the JSON report', () => {
  const dir = mkTmp('crucible-wf-good-');
  const art = mkTmp('crucible-wf-good-art-');
  try {
    writeDocTrio(dir, { withWaves: true });
    const r = runWellFormednessGate({ projectDir: dir, artifactsDir: art });

    assert.equal(r.pass, true, 'good doc-trio ⇒ exit 0 ⇒ PASS');
    assert.equal(r.status, 0);
    assert.ok(r.report && r.report.status === 'OK', 'the resolver JSON report is parsed and surfaced');
    assert.equal(r.report.total_waves, 1);

    // Forge-proof artifact persists the REAL captured subprocess evidence.
    const saved = JSON.parse(fs.readFileSync(r.artifactPath, 'utf8'));
    assert.equal(saved.gate, 'well-formedness');
    assert.equal(saved.pass, true);
    assert.equal(saved.status, 0);
    assert.ok(saved.stdout.includes('"status": "OK"'), 'raw stdout captured verbatim');
  } finally {
    rm(dir); rm(art);
  }
});

test('well-formedness gate FAILS on a malformed doc-trio: exit≠0 + stderr captured to a forge-proof artifact, no crash', () => {
  const dir = mkTmp('crucible-wf-bad-');
  const art = mkTmp('crucible-wf-bad-art-');
  try {
    writeDocTrio(dir, { withWaves: false }); // plan has no waves ⇒ locate-plan HALTs (exit 3)
    const r = runWellFormednessGate({ projectDir: dir, artifactsDir: art });

    assert.equal(r.pass, false, 'malformed ⇒ FAIL (no throw)');
    assert.notEqual(r.status, 0, 'non-zero exit code');
    assert.equal(r.status, 3, 'locate-plan HALT exit code is 3');
    assert.match(r.stderr, /HALT/i, 'the resolver\'s HALT stderr is captured');

    const saved = JSON.parse(fs.readFileSync(r.artifactPath, 'utf8'));
    assert.equal(saved.pass, false);
    assert.equal(saved.status, 3);
    assert.match(saved.stderr, /wave/i, 'stderr names the missing wave structure');
  } finally {
    rm(dir); rm(art);
  }
});

test('well-formedness gate FAILS cleanly on spawn-ENOENT (no crash), capturing the spawn error', () => {
  const art = mkTmp('crucible-wf-enoent-art-');
  try {
    // Inject a spawn that mimics spawnSync's ENOENT shape: { error, status:null }.
    const fakeSpawn = () => ({ error: Object.assign(new Error('spawn node ENOENT'), { code: 'ENOENT' }), status: null, stdout: '', stderr: '' });
    const r = runWellFormednessGate({ projectDir: process.cwd(), artifactsDir: art, spawn: fakeSpawn });

    assert.equal(r.pass, false, 'spawn failure ⇒ FAIL');
    assert.equal(r.status, null, 'no exit code when the spawn itself failed');
    assert.ok(r.spawnError, 'the spawn error is captured');
    assert.equal(r.spawnError.code, 'ENOENT');
    assert.match(r.stderr, /ENOENT/);

    const saved = JSON.parse(fs.readFileSync(r.artifactPath, 'utf8'));
    assert.equal(saved.pass, false);
    assert.ok(saved.spawnError && saved.spawnError.code === 'ENOENT');
  } finally {
    rm(art);
  }
});

test('well-formedness gate treats exit-0-but-unparseable-stdout as FAIL (a passing gate must emit a valid report)', () => {
  const fakeSpawn = () => ({ status: 0, stdout: 'not json at all', stderr: '', error: null });
  const r = runWellFormednessGate({ projectDir: process.cwd(), spawn: fakeSpawn });
  assert.equal(r.pass, false);
  assert.equal(r.report, null);
  assert.match(r.stderr, /unparseable|JSON/i);
});

// === (2) QUALITY / CONVERGENCE GATE ========================================

test('convergence gate: a non-dry round ⇒ NOT_CONVERGED (loop stays open)', () => {
  const g = evaluateConvergenceGate({ tally: { dry: false, newBlockers: [{ id: 'b1' }] } });
  assert.equal(g.verdict, 'NOT_CONVERGED');
  assert.equal(g.lockable, false);
  assert.equal(g.modelSideLockable, false);
});

test('convergence gate: a non-CONVERGED Judge holds the loop even on a dry round', () => {
  const g = evaluateConvergenceGate({
    tally: { dry: true },
    judgeVerdict: { lockable: false, decision: 'CHALLENGE' },
  });
  assert.equal(g.verdict, 'NOT_CONVERGED');
  assert.match(g.reasons.join(' '), /Judge did not converge \(CHALLENGE\)/);
});

test('convergence gate: an unresolved MAJOR drift flag holds the loop; a resolved or MINOR one does not', () => {
  const blocked = evaluateConvergenceGate({
    tally: { dry: true },
    judgeVerdict: { lockable: true, decision: 'CONVERGED' },
    driftFlags: [{ tier: 'MAJOR', resolved: false }],
  });
  assert.equal(blocked.modelSideLockable, false);
  assert.match(blocked.reasons.join(' '), /unresolved MAJOR drift/);

  // A resolved MAJOR + an unresolved MINOR do NOT block ⇒ model-side lockable (HALT for approval).
  const ok = evaluateConvergenceGate({
    tally: { dry: true },
    judgeVerdict: { lockable: true, decision: 'CONVERGED' },
    driftFlags: [{ tier: 'MAJOR', resolved: true }, { tier: 'MINOR', resolved: false }],
  });
  assert.equal(ok.modelSideLockable, true);
  assert.equal(ok.verdict, 'AWAITING_APPROVAL');
});

test('convergence gate (T7): fresh-eyes is advisory-unless-BLOCKER — a named BLOCKER concern holds, a bare lean does not', () => {
  // A concrete BLOCKER-severity concern HOLDS the lock (fresh-eyes retains real teeth).
  const holds = evaluateConvergenceGate({
    tally: { dry: true },
    judgeVerdict: { lockable: true, decision: 'CONVERGED' },
    freshEyes: { lean: 'not-lockable', concerns: [{ severity: 'BLOCKER', note: 'phase 2 depends on an unbuilt API' }] },
  });
  assert.equal(holds.modelSideLockable, false);
  assert.match(holds.reasons.join(' '), /BLOCKER concern/);

  // A bare non-lockable lean with NO named BLOCKER is ADVISORY — the old 3-of-3
  // unanimity produced the observed live oscillation (22→17→20 over 4 dry rounds,
  // ~30 calls into the cap). Dry + Judge decide; the user stays the final authority.
  const advisory = evaluateConvergenceGate({
    tally: { dry: true },
    judgeVerdict: { lockable: true, decision: 'CONVERGED' },
    freshEyes: { lean: 'not-lockable', concerns: [] },
  });
  assert.equal(advisory.modelSideLockable, true, 'a vibe without a named BLOCKER cannot veto');
  assert.equal(advisory.verdict, 'AWAITING_APPROVAL', 'the user still gates the lock');
  assert.match(advisory.reasons.join(' '), /advisory: fresh-eyes/, 'the divergence is recorded, not lost');
});

test('convergence gate: model-side lockable but unapproved ⇒ HALT for the user (final authority), not a self-lock', () => {
  const g = evaluateConvergenceGate({
    tally: { dry: true },
    judgeVerdict: { lockable: true, decision: 'CONVERGED' },
    freshEyes: { lean: 'lockable' },
    approved: false,
  });
  assert.equal(g.verdict, 'AWAITING_APPROVAL');
  assert.equal(g.modelSideLockable, true);
  assert.equal(g.lockable, false, 'model-side readiness never self-locks');
  assert.equal(g.halted, true);
  assert.ok(g.halt instanceof HaltError);
  assert.equal(g.halt.halt_for_human, true);
  assert.equal(g.halt.pending_action, 'user-approval');
});

test('convergence gate: all model-side conditions + user approval ⇒ CONVERGED (lock)', () => {
  const g = evaluateConvergenceGate({
    tally: { dry: true },
    judgeVerdict: { lockable: true, decision: 'CONVERGED' },
    freshEyes: { lean: 'lockable' },
    approved: true,
  });
  assert.equal(g.verdict, 'CONVERGED');
  assert.equal(g.lockable, true);
  assert.equal(g.halted, false);
});

// === (3) DRIFT DETECTOR ====================================================

test('drift detection is INACTIVE before the North-Star lock (Stage-0 gaps are exempt)', () => {
  const d = detectDrift({ severity: 'MAJOR', topic: 'a big new idea' }, { locked: false });
  assert.equal(d.drift, false);
  assert.equal(d.active, false);
  assert.match(d.reason, /only after the North-Star lock/);
});

test('driftTier: BLOCKER/MAJOR ⇒ MAJOR; MINOR/NIT ⇒ MINOR', () => {
  assert.equal(driftTier({ severity: 'BLOCKER' }), DRIFT_TIERS.MAJOR);
  assert.equal(driftTier({ severity: 'MAJOR' }), DRIFT_TIERS.MAJOR);
  assert.equal(driftTier({ severity: 'MINOR' }), DRIFT_TIERS.MINOR);
  assert.equal(driftTier({ severity: 'NIT' }), DRIFT_TIERS.MINOR);
  assert.equal(driftTier({}), DRIFT_TIERS.MINOR);
});

test('classifyDriftOption: out-of-scope ⇒ (A) Grasscatcher; refinement/tracing ⇒ (B) North-Star amendment', () => {
  const a = classifyDriftOption({ tag: 'out-of-scope', traces_to_north_star: 'no' });
  assert.equal(a.option, 'A');
  assert.equal(a.resolution, 'grasscatcher');
  assert.ok(a.suggested_home, 'option A names a suggested future home');

  const b1 = classifyDriftOption({ tag: 'refinement' });
  assert.equal(b1.option, 'B');
  assert.equal(b1.resolution, 'north-star-amendment');
  assert.equal(b1.requires_user_approval, true);

  const b2 = classifyDriftOption({ traces_to_north_star: 'yes' });
  assert.equal(b2.option, 'B', 'a tracing change is a refinement of the objective');
});

test('post-lock MINOR drift ⇒ FLAG + two options (recommend one), no HALT', () => {
  const d = detectDrift({ severity: 'MINOR', tag: 'out-of-scope', traces_to_north_star: 'no', topic: 'nice-to-have polish' }, { locked: true });
  assert.equal(d.drift, true);
  assert.equal(d.tier, DRIFT_TIERS.MINOR);
  assert.equal(d.action, 'FLAG');
  assert.equal(d.recommended, 'A');
  assert.equal(d.options.length, 2, 'always two options offered');
  assert.equal(d.options.find((o) => o.id === 'A').recommended, true);
  assert.equal(d.options.find((o) => o.id === 'B').recommended, false);
  assert.ok(!d.halt, 'minor drift does not HALT');
});

test('post-lock MAJOR drift ⇒ HALT + two options (recommend one)', () => {
  const d = detectDrift({ severity: 'MAJOR', tag: 'refinement', traces_to_north_star: 'yes', topic: 'a scope-shifting refinement' }, { locked: true });
  assert.equal(d.drift, true);
  assert.equal(d.tier, DRIFT_TIERS.MAJOR);
  assert.equal(d.action, 'HALT');
  assert.equal(d.recommended, 'B');
  assert.ok(d.halt instanceof HaltError, 'MAJOR drift HALTs for human (the §11 MAJOR-drift gate)');
  assert.equal(d.halt.pending_action, 'drift-resolution:B');
  assert.equal(d.options.find((o) => o.id === 'B').recommended, true);
});

// === Artifact writer =======================================================

test('writeGateArtifact creates the dir and writes JSON; HALTs without a dir', () => {
  const dir = mkTmp('crucible-art-');
  try {
    const p = writeGateArtifact(path.join(dir, 'nested'), 'x.json', { ok: true });
    assert.ok(fs.existsSync(p));
    assert.deepEqual(JSON.parse(fs.readFileSync(p, 'utf8')), { ok: true });
    assert.throws(() => writeGateArtifact('', 'x.json', {}), (e) => e instanceof HaltError);
  } finally {
    rm(dir);
  }
});

// === INTEGRATION: round → tally → gate to a verdict ========================

test('END-TO-END: a real Shark-Tank round → tally → convergence gate drives a full cycle to a verdict', async () => {
  // ROUND 1 — two Sharks raise the SAME (normalized) BLOCKER ⇒ tally BLOCKED.
  const blockerAgent = sharkAgent({
    Skeptic: [{ severity: 'BLOCKER', topic: 'lock gate underspecified', traces_to_north_star: 'yes', criterion: 'C2', message: 'no lock criteria' }],
    Contrarian: [{ severity: 'BLOCKER', topic: 'underspecified lock gate', traces_to_north_star: 'yes', criterion: 'C2', message: 'lock gate vague' }],
  });
  const r1 = await runSharkTank({ agent: blockerAgent, northStar: NORTH_STAR, draft: 'draft v1', round: 1 });
  assert.equal(r1.verdict, 'BLOCKED', 'round 1 tally finds the agreed BLOCKER');
  assert.equal(r1.blockers.length, 1);

  // GATE after round 1 — not dry ⇒ NOT_CONVERGED, the loop must continue.
  const gate1 = evaluateConvergenceGate({ tally: r1 });
  assert.equal(gate1.verdict, 'NOT_CONVERGED', 'the gate keeps the loop open while a blocker stands');

  // ROUND 2 — the draft was fixed; every Shark returns clean ⇒ DRY round.
  const cleanAgent = sharkAgent({});
  const priorBlockerIds = r1.blockers.map((b) => b.id);
  const r2 = await runSharkTank({ agent: cleanAgent, northStar: NORTH_STAR, draft: 'draft v2 (fixed)', round: 2, priorBlockerIds });
  assert.equal(r2.verdict, 'DRY', 'round 2 is a dry round');
  assert.equal(r2.findings.length, 0);

  // The Judge (real bin/judge.mjs, stubbed agent) DECIDES from the dry round's evidence.
  const judge = makeJudge({ agent: scriptedAgent({ decision: 'CONVERGED', reasons: ['dry round, no open blocker'] }) });
  const judgeVerdict = await judge.decide({ northStar: NORTH_STAR, findings: r2.findings, acceptanceCriteria: ['every wave has a done-when'], round: 2 });
  assert.equal(judgeVerdict.lockable, true);

  // GATE after the dry round + Judge CONVERGED + fresh-eyes concur, but UNAPPROVED ⇒
  // AWAITING_APPROVAL (HALT for the user, the final authority).
  const gate2 = evaluateConvergenceGate({
    tally: r2,
    judgeVerdict,
    freshEyes: { lean: 'lockable' },
    approved: false,
  });
  assert.equal(gate2.verdict, 'AWAITING_APPROVAL');
  assert.equal(gate2.modelSideLockable, true);
  assert.ok(gate2.halt instanceof HaltError);

  // The user approves ⇒ the gate locks: CONVERGED. Full cycle proven end-to-end.
  const gate3 = evaluateConvergenceGate({
    tally: r2,
    judgeVerdict,
    freshEyes: { lean: 'lockable' },
    approved: true,
  });
  assert.equal(gate3.verdict, 'CONVERGED');
  assert.equal(gate3.lockable, true);
});

test('END-TO-END sanity: tallyFindings + gate agree a lone unrebutted BLOCKER is dry-and-lockable-side', () => {
  // A single-Shark BLOCKER never reaches ≥2 agreement ⇒ dry ⇒ the gate sees no blocker.
  const t = tallyFindings([
    { reviewer: 'Skeptic', findings: [{ severity: 'BLOCKER', topic: 'lone concern', traces_to_north_star: 'yes', criterion: 'C1' }] },
    { reviewer: 'Contrarian', findings: [] },
  ]);
  assert.equal(t.dry, true);
  const g = evaluateConvergenceGate({ tally: t, judgeVerdict: { lockable: true, decision: 'CONVERGED' } });
  assert.equal(g.modelSideLockable, true);
});
