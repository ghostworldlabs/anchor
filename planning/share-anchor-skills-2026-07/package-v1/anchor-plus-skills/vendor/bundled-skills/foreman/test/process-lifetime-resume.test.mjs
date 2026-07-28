// F-H sleep fix: planResume mid-wave running checkpoint yields resumeFrom seed.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { newCheckpoint, writeCheckpointAtomic } from '../bin/foreman-lib.mjs';
import { planResume } from '../bin/project-engine.mjs';

test('planResume on status=running mid-review returns resumeFrom.intraStep=review', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fr-'));
  const cpPath = path.join(dir, 'foreman-checkpoint.json');
  const cp = newCheckpoint({ plan_path: path.join(dir, 'plan.md'), total_waves: 4, reviewer_count: 1 });
  cp.current_wave = 4;
  cp.intra_wave_step = 'review';
  cp.iteration = 0;
  cp.last_verdict = null;
  cp.status = 'running';
  cp.pending_action = 'gate GREEN — entering review';
  writeCheckpointAtomic(cpPath, cp);

  const r = planResume(cpPath, 4);
  assert.equal(r.startWave, 4);
  assert.equal(r.resumeWave, 4);
  assert.ok(r.resumeFrom);
  assert.equal(r.resumeFrom.intraStep, 'review');
  assert.equal(r.resumeFrom.iteration, 0);
});

test('planResume on status=running after GO advances to next wave without resumeFrom', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'fr-'));
  const cpPath = path.join(dir, 'foreman-checkpoint.json');
  const cp = newCheckpoint({ plan_path: path.join(dir, 'plan.md'), total_waves: 4, reviewer_count: 1 });
  cp.current_wave = 2;
  cp.intra_wave_step = 'done';
  cp.last_verdict = 'GO';
  cp.status = 'running';
  writeCheckpointAtomic(cpPath, cp);

  const r = planResume(cpPath, 4);
  assert.equal(r.startWave, 3);
  assert.equal(r.resumeFrom, undefined);
});
