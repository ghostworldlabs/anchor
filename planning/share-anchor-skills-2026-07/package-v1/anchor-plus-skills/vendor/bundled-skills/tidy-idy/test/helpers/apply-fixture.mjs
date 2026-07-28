// test/helpers/apply-fixture.mjs — shared plumbing for the Wave-3 Apply suites.
//
// NOT a test file: it exports helpers and defines no tests.
//
// Every Apply test needs the same four things and must not each invent them:
//   • a REAL repository (the executor is git plumbing end to end; a mocked git
//     would test the mock);
//   • a real snapshot S with real content hashes, because revalidation compares
//     against S and a hand-written hash would make the stale tests vacuous;
//   • findings shaped exactly as the stages emit them, with real IDs stamped by
//     the real identity module — an approval built any other way would not prove
//     the identity contract holds;
//   • the ability to observe the repository's exact state before and after, so
//     "bit-identical to pre-Apply" is an assertion rather than a claim.

import fs from 'node:fs/promises';
import path from 'node:path';

import { openGit } from '../../engine/git.mjs';
import { captureSnapshot, ensureHash } from '../../engine/snapshot.mjs';
import { loadPorcelain } from '../../engine/porcelain.mjs';
import { stampFindingIds } from '../../engine/apply/identity.mjs';
import { git, initRepo, write, commitAll, makeTempRoot, rmTempRoot } from './git-fixture.mjs';

export { git, initRepo, write, commitAll, makeTempRoot, rmTempRoot };

/** Every file under `root`, repo-relative, excluding .git and the report dir. */
export async function listFiles(root, rel = '') {
  const out = [];
  const entries = await fs.readdir(path.join(root, rel), { withFileTypes: true });
  for (const e of entries) {
    const child = rel ? `${rel}/${e.name}` : e.name;
    if (e.name === '.git' || e.name === '.tidy-idy') continue;
    if (e.isDirectory()) out.push(...await listFiles(root, child));
    else out.push(child);
  }
  return out.sort();
}

/**
 * The read-only half of a run: open git, capture S over the whole tree, hash
 * every in-scope path, and read porcelain — exactly what the pipeline hands the
 * executor, assembled without the LLM stages.
 */
export async function scanFixture(root, { runId = 'run-fixture-0001' } = {}) {
  const handle = await openGit(root);
  const paths = await listFiles(root);
  const snapshot = await captureSnapshot({ rootPath: root, head: handle ? handle.head : null, paths });
  for (const p of paths) await ensureHash(snapshot, p);
  const porcelain = handle ? await loadPorcelain({ git: handle, state: {} }) : null;
  return { git: handle, snapshot, porcelain, runId, paths };
}

/** A finding shaped like the stages' output, with its real hash and class. */
export function makeFinding(scan, { action, path: rel, ...extra }) {
  return {
    stage: 'fixture',
    kind: `${action}-candidate`,
    action,
    path: rel,
    contentHash: scan.snapshot.hashes[rel] ?? null,
    trackingClass: scan.porcelain ? scan.porcelain.classify(rel) : null,
    ...extra,
  };
}

/** Stamp real IDs and return the findings — the only route into Apply. */
export function stamp(findings, runId) {
  stampFindingIds(findings, runId);
  return findings;
}

/** The approval wire form: the identity, round-tripped IN FULL. */
export function approvalsFor(findings) {
  return findings.map((f) => ({ id: f.id, action: f.action, path: f.path, contentHash: f.contentHash ?? null }));
}

/** A comparable snapshot of "what the repository looks like right now". */
export async function repoState(root) {
  const files = await listFiles(root);
  const contents = {};
  for (const f of files) contents[f] = (await fs.readFile(path.join(root, f))).toString('utf8');
  return {
    files,
    contents,
    head: (await git(root, ['rev-parse', 'HEAD'])).trim(),
    // The USER's index, verbatim: the abort-all tests assert this is untouched.
    index: await git(root, ['ls-files', '-s']),
    status: await git(root, ['status', '--porcelain']),
  };
}

/** How many commits the branch has — "exactly one commit per Apply", measured. */
export async function commitCount(root) {
  return Number((await git(root, ['rev-list', '--count', 'HEAD'])).trim());
}

/**
 * An fs facade that lets a specific path vanish after N successful reads —
 * the only honest way to simulate "the user deleted this file MID-COMPILE",
 * i.e. after revalidation passed and before the compiler read the bytes.
 */
export function fsVanishingAfter(realFs, targetAbsPath, afterReads = 1) {
  let reads = 0;
  return new Proxy(realFs, {
    get(target, prop, receiver) {
      if (prop !== 'readFile') return Reflect.get(target, prop, receiver);
      return async (file, ...rest) => {
        if (path.resolve(String(file)) === path.resolve(targetAbsPath)) {
          reads++;
          if (reads > afterReads) {
            const err = new Error(`ENOENT: no such file or directory, open '${file}'`);
            err.code = 'ENOENT';
            throw err;
          }
        }
        return target.readFile(file, ...rest);
      };
    },
  });
}
