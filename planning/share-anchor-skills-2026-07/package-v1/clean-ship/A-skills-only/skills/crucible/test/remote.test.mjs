// test/remote.test.mjs — Wave 9 gate for the hermetic push-at-gates seam.
// Drives the remote coordinator through a FAKE remote (injected runGit/runGh) — zero
// subprocesses, zero network — and proves the §11/D13 contract: push happens ONLY at
// an approval gate AND ONLY with the human's confirmation; the private remote is
// created on first push; and there is NO code path that auto-pushes. Exercises REAL
// source in bin/remote.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../bin/crucible-lib.mjs';
import { makeRemote, PUSH_GATES, defaultRunGit, defaultRunGh } from '../bin/remote.mjs';

/**
 * A fake remote: records every git/gh invocation and simulates `git remote` state so
 * "create then push" is observable WITHOUT touching the network. `hasOrigin` flips
 * once `gh repo create` runs.
 */
function fakeRemote() {
  const calls = { git: [], gh: [] };
  let hasOrigin = false;
  const runGit = (repoDir, args) => {
    calls.git.push(args);
    if (args[0] === 'remote') return { status: 0, stdout: hasOrigin ? 'origin\n' : '', stderr: '', error: null };
    if (args[0] === 'push') return { status: 0, stdout: '', stderr: '', error: null };
    return { status: 0, stdout: '', stderr: '', error: null };
  };
  const runGh = (repoDir, args) => {
    calls.gh.push(args);
    if (args[0] === 'repo' && args[1] === 'create') { hasOrigin = true; return { status: 0, stdout: '', stderr: '', error: null }; }
    return { status: 0, stdout: '', stderr: '', error: null };
  };
  return { calls, runGit, runGh, get hasOrigin() { return hasOrigin; }, preset(v) { hasOrigin = v; } };
}

const pushed = (calls) => calls.git.filter((a) => a[0] === 'push');

// --- construction guard ----------------------------------------------------

test('makeRemote requires a repoDir', () => {
  assert.throws(() => makeRemote({}), (e) => e instanceof HaltError);
});

test('PUSH_GATES is exactly the two approval gates', () => {
  assert.deepEqual([...PUSH_GATES].sort(), ['implementation-plan-approval', 'master-plan-approval']);
});

// --- never auto-push: no confirmation ⇒ no push ----------------------------

test('pushAtGate WITHOUT approval HALTs for confirmation and does NOT push', () => {
  const fr = fakeRemote();
  const remote = makeRemote({ repoDir: '/x', runGit: fr.runGit, runGh: fr.runGh });
  const r = remote.pushAtGate({ gate: 'master-plan-approval', branch: 'foreman/run', approved: false });

  assert.equal(r.pushed, false);
  assert.equal(r.halted, true);
  assert.ok(r.halt instanceof HaltError, 'returns a HALT-for-human');
  assert.equal(r.halt.pending_action, 'confirm-push:master-plan-approval');
  assert.equal(pushed(fr.calls).length, 0, 'the transport NEVER pushed without confirmation');
  assert.equal(fr.calls.gh.length, 0, 'no remote created without confirmation');
});

// --- never auto-push: wrong gate ⇒ no push ---------------------------------

test('pushAtGate at a NON-approval gate refuses (the North-Star lock is not a push gate)', () => {
  const fr = fakeRemote();
  const remote = makeRemote({ repoDir: '/x', runGit: fr.runGit, runGh: fr.runGh });
  const r = remote.pushAtGate({ gate: 'north-star-lock', branch: 'foreman/run', approved: true });

  assert.equal(r.pushed, false);
  assert.equal(r.halted, false);
  assert.match(r.reason, /not an approval push-gate/);
  assert.equal(pushed(fr.calls).length, 0, 'even WITH approval, a non-gate never pushes');
});

// --- the happy path: approved AT a gate ⇒ create private remote, then push ---

test('pushAtGate APPROVED at an approval gate creates the PRIVATE remote then pushes', () => {
  const fr = fakeRemote();
  const remote = makeRemote({ repoDir: '/x', runGit: fr.runGit, runGh: fr.runGh });
  const r = remote.pushAtGate({ gate: 'implementation-plan-approval', branch: 'foreman/run', approved: true, repoName: 'crucible' });

  assert.equal(r.pushed, true);
  assert.equal(r.remoteCreated, true);
  // The private repo was created via gh (--private), then git pushed -u origin <branch>.
  assert.equal(fr.calls.gh.length, 1);
  assert.deepEqual(fr.calls.gh[0], ['repo', 'create', 'crucible', '--private', '--source', '.', '--remote', 'origin']);
  const ps = pushed(fr.calls);
  assert.equal(ps.length, 1);
  assert.deepEqual(ps[0], ['push', '-u', 'origin', 'foreman/run']);
});

test('an EXISTING remote is not recreated, but an approved push still happens', () => {
  const fr = fakeRemote();
  fr.preset(true); // origin already configured
  const remote = makeRemote({ repoDir: '/x', runGit: fr.runGit, runGh: fr.runGh });
  const r = remote.pushAtGate({ gate: 'master-plan-approval', branch: 'foreman/run', approved: true });

  assert.equal(r.pushed, true);
  assert.equal(r.remoteCreated, false);
  assert.equal(fr.calls.gh.length, 0, 'no gh repo create when a remote already exists');
  assert.equal(pushed(fr.calls).length, 1);
});

// --- ask EACH time: a second push needs its own confirmation ----------------

test('confirmation is required EACH time — a prior approved push does not carry over', () => {
  const fr = fakeRemote();
  const remote = makeRemote({ repoDir: '/x', runGit: fr.runGit, runGh: fr.runGh });

  const first = remote.pushAtGate({ gate: 'master-plan-approval', branch: 'foreman/run', approved: true, repoName: 'crucible' });
  assert.equal(first.pushed, true);

  const second = remote.pushAtGate({ gate: 'implementation-plan-approval', branch: 'foreman/run', approved: false });
  assert.equal(second.pushed, false);
  assert.equal(second.halted, true);
  assert.equal(pushed(fr.calls).length, 1, 'only the confirmed push went through');
});

// --- ensureRemote alone does not push (only pushAtGate pushes) --------------

test('ensureRemote on its own creates a remote but NEVER pushes', () => {
  const fr = fakeRemote();
  const remote = makeRemote({ repoDir: '/x', runGit: fr.runGit, runGh: fr.runGh });
  const e = remote.ensureRemote({ name: 'crucible' });
  assert.equal(e.created, true);
  assert.equal(pushed(fr.calls).length, 0, 'ensureRemote has no push path — only pushAtGate pushes');
});

// --- a push transport failure is surfaced, not crashed ----------------------

test('a failing git push is reported (pushed:false) rather than thrown', () => {
  const fr = fakeRemote();
  fr.preset(true);
  const runGit = (repoDir, args) => {
    fr.calls.git.push(args);
    if (args[0] === 'remote') return { status: 0, stdout: 'origin\n', stderr: '', error: null };
    if (args[0] === 'push') return { status: 1, stdout: '', stderr: 'rejected: non-fast-forward', error: null };
    return { status: 0, stdout: '', stderr: '', error: null };
  };
  const remote = makeRemote({ repoDir: '/x', runGit, runGh: fr.runGh });
  const r = remote.pushAtGate({ gate: 'master-plan-approval', branch: 'foreman/run', approved: true });
  assert.equal(r.pushed, false);
  assert.match(r.reason, /push failed/);
});

// --- the default transports exist (live binding present, just not exercised) --

test('default live transports are wired (not invoked here)', () => {
  assert.equal(typeof defaultRunGit, 'function');
  assert.equal(typeof defaultRunGh, 'function');
});
