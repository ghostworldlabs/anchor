// phase-a-efficiency.test.mjs — effort-scoped caps + human-lockable (2026-07-22)
// North-Star: user remains convergence authority; multi-Shark ≥2-agree preserved;
// never auto-locks without user approval.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  resolveLoopBounds,
  assessHumanLockable,
  runMasterPlanLoop,
  approveMasterPlan,
} from '../bin/stage1.mjs';

test('resolveLoopBounds: fresh start gets full roundCap', () => {
  const b = resolveLoopBounds({ startRound: 1, roundCap: 5 });
  assert.equal(b.remaining, 5);
  assert.equal(b.endExclusive, 6);
  assert.equal(b.mode, 'effort-scoped');
});

test('resolveLoopBounds: resume does NOT open a second full cap (journal 0011)', () => {
  // Prior invoke ran rounds 1..5; resume asked startRound=6 with roundCap=5
  const b = resolveLoopBounds({ startRound: 6, roundCap: 5 });
  assert.equal(b.already, 5);
  assert.equal(b.remaining, 0);
  assert.equal(b.endExclusive, 6);
});

test('resolveLoopBounds: additionalRounds explicitly extends', () => {
  const b = resolveLoopBounds({ startRound: 6, roundCap: 5, additionalRounds: 3 });
  assert.equal(b.mode, 'additional-rounds');
  assert.equal(b.remaining, 3);
  assert.equal(b.endExclusive, 9);
});

test('assessHumanLockable: dry + no multi-agree blockers is eligible', () => {
  const r = assessHumanLockable({
    tally: {
      dry: true,
      blockers: [],
      findings: [
        { id: 'a', severity: 'MAJOR', agreement: 1, demoted: false },
      ],
    },
  });
  assert.equal(r.eligible, true);
});

test('assessHumanLockable: multi-agree BLOCKER is NOT eligible', () => {
  const r = assessHumanLockable({
    tally: {
      dry: true,
      blockers: [{ id: 'x', agreement: 2 }],
      findings: [],
    },
  });
  assert.equal(r.eligible, false);
});

test('assessHumanLockable: non-dry is NOT eligible', () => {
  assert.equal(assessHumanLockable({ tally: { dry: false, blockers: [] } }).eligible, false);
});

test('runMasterPlanLoop: effort cap exhausted throws without model calls', async () => {
  let calls = 0;
  const agent = async () => { calls += 1; return {}; };
  await assert.rejects(
    () => runMasterPlanLoop({
      agent,
      northStar: 'NS',
      draft: '# draft',
      startRound: 6,
      roundCap: 5,
    }),
    (e) => e instanceof HaltError && /effort round budget exhausted/i.test(e.reason || e.message),
  );
  assert.equal(calls, 0, 'must not call models when budget is already spent');
});

test('approveMasterPlan: accepts humanLockable loop when user approves', () => {
  const out = approveMasterPlan({
    loop: {
      modelSideLockable: false,
      humanLockable: true,
      draft: '# Master Plan\n',
      roundsRun: 4,
    },
    approved: true,
  });
  assert.equal(out.approved, true);
  assert.equal(out.humanLockable, true);
  assert.match(out.masterPlan, /Master Plan/);
});

test('approveMasterPlan: humanLockable without approval still HALTs', () => {
  assert.throws(
    () => approveMasterPlan({
      loop: { modelSideLockable: false, humanLockable: true, draft: 'x', roundsRun: 2 },
      approved: false,
    }),
    (e) => e instanceof HaltError && /human-lockable/i.test(e.reason || e.message || e.pending_action || ''),
  );
});
