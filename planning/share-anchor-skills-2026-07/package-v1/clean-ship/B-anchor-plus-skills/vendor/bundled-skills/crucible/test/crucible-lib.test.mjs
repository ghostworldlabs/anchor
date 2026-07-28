// test/crucible-lib.test.mjs — Wave 1 gate for the engine skeleton, contract &
// substrate seams. Exercises REAL source in bin/crucible-lib.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  HaltError,
  validateCheckpoint,
  writeCheckpointAtomic,
  readCheckpoint,
  makeGitContext,
  foremanImportSmokeTest,
  newCrucibleCheckpoint,
  CRUCIBLE_DELTA_FIELDS,
  makeStateMachine,
  haltForHuman,
  HALT_GATES,
  STAGE_SUCCESSOR,
  resolveToplevel,
  wouldTripContainment,
  resolveManagedGitContext,
  defaultIsolate,
  FOREMAN_ROOT,
} from '../bin/crucible-lib.mjs';

// --- helpers ---------------------------------------------------------------

function mkTmp(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}
function git(cwd, args) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8' });
  if (r.status !== 0) throw new Error(`git ${args.join(' ')} failed in ${cwd}: ${r.stderr}`);
  return r;
}
function initRepo(dir) {
  fs.mkdirSync(dir, { recursive: true });
  git(dir, ['init', '-q']);
  fs.writeFileSync(path.join(dir, 'README.md'), '# fixture\n');
  git(dir, ['add', '-A']);
  git(dir, ['-c', 'user.name=T', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'baseline']);
}
function rm(dir) { try { fs.rmSync(dir, { recursive: true, force: true }); } catch { /* best-effort */ } }

// --- import smoke-test -----------------------------------------------------

test('Foreman import smoke-test: all primitives import as callables', () => {
  const r = foremanImportSmokeTest();
  assert.equal(r.ok, true);
  for (const name of ['HaltError', 'newCheckpoint', 'validateCheckpoint', 'makeGitContext',
    'makeAgentDriver', 'makeBudget', 'writeCheckpointAtomic', 'readCheckpoint',
    'assertContainment', 'isGitRepo']) {
    assert.ok(r.imported.includes(name), `${name} should be a verified Foreman import`);
  }
});

// --- checkpoint superset ---------------------------------------------------

test('checkpoint superset validates and round-trips, with deltas surviving (behavioral, no field count)', () => {
  const cp = newCrucibleCheckpoint({
    plan_path: 'IMPLEMENTATION-PLAN.md',
    total_waves: 11,
    stage: 'stage1',
    phase: 'brainstorm',
    round: 2,
    drift_flags: ['scope-creep:foo'],
    synthesizer_direction_ref: 'plans/debates/round-2/direction.md',
  });

  // Passes Foreman's validator (asserted behaviorally — validateCheckpoint returns
  // the object it approved, and throws otherwise).
  assert.strictEqual(validateCheckpoint(cp), cp);

  // Crucible's deltas are present on the freshly built checkpoint.
  for (const f of CRUCIBLE_DELTA_FIELDS) {
    assert.ok(f in cp, `delta field ${f} should be present`);
  }

  const dir = mkTmp('crucible-cp-');
  try {
    const file = path.join(dir, 'foreman-checkpoint.json');
    writeCheckpointAtomic(file, cp);
    const back = readCheckpoint(file);
    // readCheckpoint returns the validated object — round-trip still valid.
    assert.strictEqual(validateCheckpoint(back), back);
    // Every Crucible delta survives the write/read round-trip intact.
    for (const f of CRUCIBLE_DELTA_FIELDS) {
      assert.deepEqual(back[f], cp[f], `delta field ${f} should survive round-trip`);
    }
    // A canonical Foreman field also survives (sanity that we wrote the superset).
    assert.equal(back.total_waves, 11);
  } finally {
    rm(dir);
  }
});

// --- state machine + halt gates -------------------------------------------

test('haltForHuman returns a HaltError carrying the pending_action', () => {
  const e = haltForHuman('Stage 0 done — lock the North Star', 'north-star-lock');
  assert.ok(e instanceof HaltError);
  assert.equal(e.reason, 'Stage 0 done — lock the North Star');
  assert.equal(e.pending_action, 'north-star-lock');
  assert.equal(e.halt_for_human, true);
});

test('three-stage state machine: transition guard + you-approve HALT at every boundary', () => {
  const sm = makeStateMachine();
  assert.equal(sm.stage(), 'stage0');
  assert.equal(sm.next(), 'stage1');
  assert.equal(sm.canTransition('stage1'), true);
  assert.equal(sm.canTransition('stage2'), false, 'cannot skip a stage');

  // Advancing without approval HALTs (human is the convergence authority) and does
  // NOT change state.
  assert.throws(
    () => sm.advance(),
    (e) => e instanceof HaltError && e.pending_action === HALT_GATES['stage0->stage1'].name,
  );
  assert.equal(sm.stage(), 'stage0', 'an unapproved advance must not cross the boundary');

  // With approval it walks stage0 -> stage1 -> stage2 -> done.
  assert.equal(sm.advance({ approved: true }), 'stage1');
  assert.equal(sm.advance({ approved: true }), 'stage2');
  assert.equal(sm.advance({ approved: true }), 'done');
  assert.equal(sm.stage(), 'done');

  // No successor past done.
  assert.throws(() => sm.advance({ approved: true }), HaltError);
});

test('HALT-gate set covers every declared stage boundary', () => {
  for (const [from, to] of Object.entries(STAGE_SUCCESSOR)) {
    assert.ok(HALT_GATES[`${from}->${to}`], `a gate should guard ${from}->${to}`);
  }
});

// --- git toplevel / containment resolver -----------------------------------

test('wouldTripContainment fires in BOTH directions and clears for siblings', () => {
  const foreman = '<path>';
  assert.equal(wouldTripContainment('<path>', foreman), true, 'a repo that CONTAINS foreman trips');
  assert.equal(wouldTripContainment('<path>', foreman), true, 'a repo NESTED inside foreman trips');
  assert.equal(wouldTripContainment('<path>', foreman), true, 'the same path trips');
  assert.equal(wouldTripContainment('<path>', foreman), false, 'a SIBLING does not trip');
});

test('resolveManagedGitContext: safe project binds Foreman git context directly (no isolation)', () => {
  const repo = mkTmp('crucible-safe-');
  try {
    initRepo(repo);
    const res = resolveManagedGitContext({ repoDir: repo, log: null });
    assert.equal(res.isolated, false);
    assert.equal(res.repoTop, resolveToplevel(repo));
    assert.equal(typeof res.ctx.commitWave, 'function', 'a real Foreman git context is bound');
    // Sanity: a temp repo is never inside the real foreman tree.
    assert.equal(wouldTripContainment(res.repoTop, FOREMAN_ROOT), false);
  } finally {
    rm(repo);
  }
});

test('resolveManagedGitContext: a repo nested inside the containment root is ISOLATED, not HALTed', () => {
  const fakeForeman = mkTmp('crucible-fakeforeman-');
  const isoRoot = mkTmp('crucible-isoroot-');
  let isoTop = null;
  try {
    // A managed repo whose toplevel sits INSIDE the (injected) containment root —
    // exactly the case that would otherwise trip assertContainment.
    const nested = path.join(fakeForeman, 'managed-project');
    initRepo(nested);
    assert.equal(wouldTripContainment(resolveToplevel(nested), fakeForeman), true);

    const res = resolveManagedGitContext({
      repoDir: nested,
      foremanRoot: fakeForeman,
      isolationRoot: isoRoot,
      isolate: defaultIsolate,
      log: null,
    });
    isoTop = res.repoTop;

    assert.equal(res.isolated, true, 'it isolates instead of HALTing');
    assert.equal(res.originalTop, resolveToplevel(nested));
    // The isolated toplevel escaped the containment root (and the real foreman tree).
    assert.equal(wouldTripContainment(res.repoTop, fakeForeman), false);
    assert.equal(wouldTripContainment(res.repoTop, FOREMAN_ROOT), false);
    // A working Foreman git context is bound to the isolated copy.
    assert.equal(typeof res.ctx.commitWave, 'function');
    assert.equal(res.ctx.repoTop, res.repoTop);
  } finally {
    rm(fakeForeman);
    rm(isoRoot);
    if (isoTop) rm(isoTop);
  }
});

// Negative fixture: makeGitContext (imported, unforked) still HALTs on the real
// containment guard when handed the foreman source directly — proving Crucible did
// not weaken Foreman's safety, only routes around it via isolation.
test('imported makeGitContext still HALTs on the real Foreman source (guard intact)', () => {
  assert.throws(
    () => makeGitContext({ repoDir: FOREMAN_ROOT }),
    (e) => e instanceof HaltError,
  );
});
