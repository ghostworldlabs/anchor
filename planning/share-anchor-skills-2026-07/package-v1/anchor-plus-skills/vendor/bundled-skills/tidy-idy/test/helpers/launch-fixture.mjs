// test/helpers/launch-fixture.mjs — shared plumbing for the Wave-5 suites.
//
// NOT a test file: it exports helpers and defines no tests.
//
// Two things every Wave-5 suite needs and must not each reinvent:
//   • a job_runner DOUBLE that behaves like the real one on the axes this wave
//     depends on (guarded launch, folder claim, durable log, terminal status) —
//     built from job_runner.py's actual semantics, so the parity test exercises
//     the button's real shape without requiring Anchor to be installed;
//   • an envelope NORMALISER, because two runs of the same folder legitimately
//     differ in run id, timestamps and absolute temp paths, and a parity
//     assertion that ignored nothing would be untestable while one that ignored
//     too much would prove nothing.

import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const SKILL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const CLI = path.join(SKILL_DIR, 'bin', 'tidy-idy.mjs');
export const STUB_DRIVER = path.join(SKILL_DIR, 'test', 'helpers', 'stub-driver.mjs');

/**
 * A job_runner double.
 *
 * Mirrors the real module where this wave depends on it (source: job_runner.py):
 *   • `launch_guarded` refuses a second same-(project, lane) job while one is
 *     live, and a second BUILD-lane job on a claimed folder — with the same
 *     machine-readable reasons;
 *   • the `command` argv is launched VERBATIM (the control-plane seam);
 *   • stdout is streamed into a durable log a caller reads back;
 *   • completion is a terminal STATUS on the record — there is no callback.
 */
export function makeJobRunnerDouble({ env = {} } = {}) {
  const records = new Map();
  const logs = new Map();
  const laneSlots = new Map();   // `${project_id}::${lane}` -> job_id
  const folderBuild = new Map(); // folder_path -> job_id
  const children = new Map();
  let seq = 0;

  const live = (jobId) => {
    const rec = records.get(jobId);
    return Boolean(rec && rec.status === 'running');
  };

  return {
    records,
    logs,
    laneSlots,
    folderBuild,

    async launchGuarded(spec) {
      const laneKey = `${spec.project_id}::${spec.lane}`;
      const laneHolder = laneSlots.get(laneKey);
      if (laneHolder && live(laneHolder)) {
        const err = new Error(`same-lane-busy (held by ${laneHolder})`);
        err.reason = 'same-lane-busy';
        err.holder = laneHolder;
        throw err;
      }
      if (spec.lane === 'build') {
        const held = folderBuild.get(spec.folder_path);
        if (held && live(held)) {
          const err = new Error(`folder-build-lock (held by ${held})`);
          err.reason = 'folder-build-lock';
          err.holder = held;
          throw err;
        }
      }

      const jobId = `job-${++seq}`;
      logs.set(jobId, '');
      const [command, ...args] = spec.command;
      const child = spawn(command, args, {
        cwd: spec.cwd,
        env: { ...process.env, TIDY_IDY_DRIVER: STUB_DRIVER, ...env },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      children.set(jobId, child);
      child.stdout.on('data', (d) => logs.set(jobId, logs.get(jobId) + String(d)));
      child.stderr.on('data', (d) => logs.set(jobId, logs.get(jobId) + String(d)));

      const rec = {
        job_id: jobId,
        lane: spec.lane,
        job_type: spec.job_type,
        pid: child.pid,
        status: 'running',
        cwd: spec.cwd,
        project_id: spec.project_id,
        folder_path: spec.folder_path,
      };
      records.set(jobId, rec);
      laneSlots.set(laneKey, jobId);
      if (spec.lane === 'build') folderBuild.set(spec.folder_path, jobId);

      child.on('exit', (code) => {
        // job_runner._finalize: done on 0, failed otherwise. No callback fires.
        rec.exit_code = code;
        rec.status = code === 0 ? 'done' : 'failed';
      });
      return rec;
    },

    async loadRecord(jobId) { return records.get(jobId) || null; },
    async readLog(jobId) { return logs.get(jobId) || ''; },
    async registerClaim(claim) { return { ...claim, registered: true }; },

    /** Terminate every child the double started. Tests call this in teardown. */
    async killAll() {
      for (const child of children.values()) {
        try { child.kill(); } catch { /* already gone */ }
      }
      // Give the exit handlers a tick so a later assertion sees terminal status.
      await new Promise((r) => setTimeout(r, 50));
    },
  };
}

/**
 * Strip everything two legitimate runs of the same folder MUST differ on, and
 * nothing else. What survives is what the parity claim is actually about.
 */
export function normaliseEnvelope(env, { rootPath }) {
  const root = path.resolve(rootPath);
  const scrub = (value) => {
    if (Array.isArray(value)) return value.map(scrub);
    if (value && typeof value === 'object') {
      const out = {};
      for (const [k, v] of Object.entries(value)) {
        if (['runId', 'startedAt', 'endedAt', 'capturedAt', 'storedAt', 'archivedAt', 'mtimeMs', 'acquiredAt'].includes(k)) continue;
        // Finding IDs hash the run id, so they differ by construction.
        if (k === 'id' || k === 'findingId') continue;
        out[k] = scrub(v);
      }
      return out;
    }
    if (typeof value === 'string') {
      return value.split(root).join('<ROOT>').replace(/run-\d{4}-[\dTZ:.-]+-[0-9a-f]+/g, '<RUNID>');
    }
    return value;
  };
  return scrub(env);
}

/** Read a run directory's file names, sorted — the "archive layout" claim. */
export async function archiveLayout(dir) {
  return (await fs.readdir(dir)).sort();
}

/** Recursively list a tree's relative file paths, sorted. */
export async function listTree(dir, base = dir, out = []) {
  let entries;
  try {
    entries = await fs.readdir(dir, { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    const abs = path.join(dir, e.name);
    if (e.isDirectory()) await listTree(abs, base, out);
    else out.push(path.relative(base, abs).split(path.sep).join('/'));
  }
  return out.sort();
}
