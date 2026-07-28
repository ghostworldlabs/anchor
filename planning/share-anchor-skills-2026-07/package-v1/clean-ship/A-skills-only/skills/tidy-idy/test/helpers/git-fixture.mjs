// test/helpers/git-fixture.mjs — shared fixture plumbing for the Wave-2 suites.
//
// NOT a test file: it exports helpers and defines no tests. It lives under
// test/ so the suites can import it by a stable relative path.
//
// Three things the Wave-2 tests all need and must not each reinvent:
//   • a real git repository (the SAVE class is built on real porcelain, so
//     hand-written porcelain fixtures would test the parser and nothing else);
//   • the ability to stamp a file's mtime (the age heuristic is a claim about
//     timestamps, and git does not carry them);
//   • an agent double that RECORDS every prompt, which is how "no secret byte
//     entered any LLM context" becomes a checkable assertion rather than a hope.

import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFile as execFileCb } from 'node:child_process';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFileCb);

/** A fresh temp directory. Callers are responsible for removing it. */
export async function makeTempRoot(prefix = 'tidy-idy-w2-') {
  return fs.mkdtemp(path.join(os.tmpdir(), prefix));
}

export async function rmTempRoot(dir) {
  if (dir) await fs.rm(dir, { recursive: true, force: true, maxRetries: 5 });
}

/** Run git in `dir` and return stdout. */
export async function git(dir, args) {
  const { stdout } = await execFileAsync('git', ['-C', dir, ...args], { maxBuffer: 32 * 1024 * 1024 });
  return String(stdout);
}

/**
 * Initialise a repository with its identity and line-ending policy pinned in
 * the REPO's own config, so behaviour does not depend on the ambient machine's
 * global git settings (and so the engine, which shells out with ambient env,
 * still sees the pinned values).
 */
export async function initRepo(dir) {
  await execFileAsync('git', ['init', dir], {});
  await git(dir, ['config', 'user.name', 'tidy-idy-test']);
  await git(dir, ['config', 'user.email', '<email>']);
  await git(dir, ['config', 'commit.gpgsign', 'false']);
  await git(dir, ['config', 'core.autocrlf', 'false']);
  return dir;
}

/** Write a file, creating parents. */
export async function write(dir, rel, content) {
  const abs = path.join(dir, rel);
  await fs.mkdir(path.dirname(abs), { recursive: true });
  await fs.writeFile(abs, content);
  return abs;
}

/** Stage everything and commit. */
export async function commitAll(dir, message = 'fixture') {
  await git(dir, ['add', '-A']);
  await git(dir, ['commit', '-m', message]);
  return (await git(dir, ['rev-parse', 'HEAD'])).trim();
}

/** Backdate a path's mtime by `days`. */
export async function ageFile(dir, rel, days) {
  const abs = path.join(dir, rel);
  const when = new Date(Date.now() - days * 86400000);
  await fs.utimes(abs, when, when);
}

/**
 * Materialise a labeled-corpus member into `dir`, stamping each file's mtime
 * from its declared `ageDays`. See test/fixtures/corpus/README.md for why the
 * corpus carries ages rather than being a checked-in tree.
 */
export async function materialiseCorpus(spec, dir) {
  for (const f of spec.files) {
    await write(dir, f.path, f.content);
  }
  if (spec.git) {
    await initRepo(dir);
    await commitAll(dir, 'corpus baseline');
  }
  // mtimes last: `git add`/`checkout` rewrite them.
  for (const f of spec.files) {
    await ageFile(dir, f.path, f.ageDays || 0);
  }
  return dir;
}

/**
 * An agent double that RECORDS every prompt it is handed. `calls` is the
 * evidence the zero-secret-bytes assertions are made against — a gate that is
 * only inspected through its own report proves nothing.
 *
 * @param {(label: string, prompt: string) => any} respond
 */
export function recordingAgent(respond = () => []) {
  const calls = [];
  const agent = async (prompt, opts = {}) => {
    const label = String(opts.label || '');
    calls.push({ label, prompt, schema: opts.schema || null });
    return respond(label, prompt);
  };
  agent.calls = calls;
  /** Every byte this run put in front of a model, concatenated. */
  agent.allPromptText = () => calls.map((c) => c.prompt).join('\n');
  return agent;
}

/** A cooperative responder that keeps the LLM stages on their real code path. */
export function cooperativeResponder({ suspects = [], removePaths = [] } = {}) {
  return (label) => {
    if (label.startsWith('hygiene-analysis')) return suspects;
    if (label.startsWith('attacker')) return suspects.map((s) => ({ filepath: s.filepath, case_for_removal: 'no longer serves the objective', strength: 'strong' }));
    if (label.startsWith('judge')) {
      return suspects.map((s) => ({
        filepath: s.filepath,
        decision: removePaths.includes(s.filepath) ? 'REMOVE' : 'RETAIN',
        rationale: removePaths.includes(s.filepath) ? 'nothing in the project depends on it' : 'still in use',
      }));
    }
    if (label.startsWith('compress')) return { executiveSummary: '# agent\n\nActive goal: ship.\n', historyToAppend: '' };
    return [];
  };
}

/** A recognisable, obviously-fake-but-pattern-matching AWS key pair. */
export const FAKE_AWS_KEY_ID = '<secret>';
export const FAKE_AWS_SECRET = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY';
/** A private-key header — the class, not a real key. */
export const FAKE_PRIVATE_KEY = '-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAxfakefakefake\n-----END RSA PRIVATE KEY-----\n';
