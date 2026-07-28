// W6 / SC3 / G7 — Real Freeze + identity-safe Kill sole boundary.

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const {
  FREEZE_METHOD,
  SPEND_POSTCONDITION,
  REASON,
  SOLE_BOUNDARY_ID,
  soleFreezeKillServiceBoundary,
  identitiesMatch,
  probeFreezeCapability,
  isKillWithoutFreezeAllowed,
  reportSpendPostcondition,
  reProbeIdentity,
  freezeCandidate,
  unfreezeCandidate,
  killCandidate,
  issueKillConfirmToken,
  validateKillConfirm,
  clearKillConfirmTokens,
  assertNoThreadSuspendSoftFreeze,
  readBoundarySources,
} = require('../src/freeze.js');

const { isFreezeKillAllowed } = require('../src/mode.js');
const {
  lookupOwnership,
  OWNERSHIP_IPC_FAIL_CLOSED,
  OWNERSHIP_REGISTERED_KEEP,
} = require('../src/ownership.js');

const IDENTITY = Object.freeze({
  pid: 424242,
  createTime: 1_700_000_000_000,
  imagePath: 'C:\\lab\\claude.exe',
});

function injects(overrides = {}) {
  const live = {
    pid: IDENTITY.pid,
    createTime: IDENTITY.createTime,
    imagePath: IDENTITY.imagePath,
    alive: true,
    name: 'claude.exe',
  };
  return {
    probeIdentity: () => ({ ...live }),
    suspend: () => ({ ok: true, method: FREEZE_METHOD }),
    resume: () => ({ ok: true, method: 'NtResumeProcess' }),
    treeKill: () => ({ ok: true, killed: true, method: 'taskkill_tree' }),
    isAlive: () => false,
    lookupOwnership: (id, opts) => lookupOwnership(id, { registry: [], ...(opts || {}) }),
    mode: 'armed',
    freezeCapability: true,
    ...overrides,
  };
}

test('test_no_thread_suspend_softfreeze', () => {
  const { freezeSrc, serverSrc, softSrc, softExists } = readBoundarySources();
  const freezeCheck = assertNoThreadSuspendSoftFreeze(freezeSrc);
  assert.strictEqual(freezeCheck.ok, true, 'freeze.js must not use Thread.Suspend');
  assert.ok(freezeSrc.includes('NtSuspendProcess'), 'freeze.js uses NtSuspendProcess');
  assert.ok(!/Thread\.Suspend/i.test(serverSrc), 'server.js has no Thread.Suspend');
  assert.ok(!/new SoftFreeze\b/.test(serverSrc), 'server does not construct SoftFreeze');
  assert.ok(
    serverSrc.includes("require('./freeze.js')") || serverSrc.includes('require("./freeze.js")'),
    'server imports sole freeze boundary',
  );
  // SoftFreeze path deleted or hard-fail shim only
  if (softExists) {
    assert.ok(softSrc.includes('REMOVED') || softSrc.includes('removed'), 'soft-freeze marked removed');
    assert.ok(!/\$thread\.Suspend/i.test(softSrc), 'soft-freeze no longer suspends threads');
    assert.throws(() => {
      const { SoftFreeze } = require('../src/soft-freeze.js');
      // eslint-disable-next-line no-new
      new SoftFreeze();
    }, /SoftFreeze removed|sole/);
  }
  assert.strictEqual(FREEZE_METHOD, 'NtSuspendProcess');
});

test('test_sole_freeze_kill_service_boundary', () => {
  const b = soleFreezeKillServiceBoundary();
  assert.strictEqual(b.id, SOLE_BOUNDARY_ID);
  assert.strictEqual(b.module, 'freeze.js');
  assert.strictEqual(b.freezeMethod, FREEZE_METHOD);
  assert.ok(b.forbidden.includes('Thread.Suspend'));
  assert.ok(b.forbidden.includes('SoftFreeze'));
  assert.ok(b.entrypoints.includes('freezeCandidate'));
  assert.ok(b.entrypoints.includes('killCandidate'));

  const { serverSrc } = readBoundarySources();
  assert.ok(serverSrc.includes('freezeCandidate') || serverSrc.includes("require('./freeze.js')"));
  // No direct inline taskkill helper as the kill path
  assert.ok(
    !/function killPids\s*\(/.test(serverSrc),
    'server must not keep a side-door killPids helper',
  );
  assert.ok(serverSrc.includes('/api/kill'), 'kill still exposed via sole API');
  assert.ok(serverSrc.includes('killCandidate'), 'kill routes through killCandidate');
});

test('test_freeze_identity_reprobe_before_suspend', () => {
  const order = [];
  const deps = injects({
    probeIdentity: (pid) => {
      order.push('reprobe');
      return {
        pid: IDENTITY.pid,
        createTime: IDENTITY.createTime,
        imagePath: IDENTITY.imagePath,
        alive: true,
      };
    },
    suspend: (pid) => {
      order.push('suspend');
      assert.strictEqual(pid, IDENTITY.pid);
      return { ok: true, method: FREEZE_METHOD };
    },
  });

  const r = freezeCandidate(IDENTITY, deps);
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.frozen, true);
  assert.strictEqual(r.method, FREEZE_METHOD);
  assert.ok(order.indexOf('reprobe') < order.indexOf('suspend'), 're-probe before suspend');
  assert.ok(r.steps.some((s) => s.step === 'identity_reprobe_before_suspend'));

  // Mismatch refuses suspend
  const bad = freezeCandidate(
    { ...IDENTITY, createTime: 999 },
    injects({
      probeIdentity: () => ({
        pid: IDENTITY.pid,
        createTime: IDENTITY.createTime,
        imagePath: IDENTITY.imagePath,
        alive: true,
      }),
      suspend: () => {
        throw new Error('must not suspend on mismatch');
      },
    }),
  );
  assert.strictEqual(bad.ok, false);
  assert.strictEqual(bad.reason, REASON.FREEZE_IDENTITY_MISMATCH);

  // Missing identity fields refuse
  const missing = freezeCandidate({ pid: 1 }, injects());
  assert.strictEqual(missing.ok, false);
  assert.strictEqual(missing.reason, REASON.FREEZE_IDENTITY_REQUIRED);

  assert.strictEqual(
    identitiesMatch(IDENTITY, { ...IDENTITY, alive: true }),
    true,
  );
  assert.strictEqual(
    identitiesMatch(IDENTITY, { ...IDENTITY, createTime: 1 }),
    false,
  );
});

test('test_freeze_spend_postcondition', () => {
  const stopped = freezeCandidate(IDENTITY, injects({
    sampleSpend: () => ({ spending: false }),
  }));
  assert.strictEqual(stopped.ok, true);
  assert.strictEqual(stopped.spendPostcondition.class, SPEND_POSTCONDITION.STOPPED);
  assert.strictEqual(stopped.spendPostcondition.reported, true);
  assert.strictEqual(stopped.spendPostcondition.soleHardHalt, false);

  const continues = freezeCandidate(IDENTITY, injects({
    sampleSpend: () => ({ spending: true }),
  }));
  assert.strictEqual(continues.spendPostcondition.class, SPEND_POSTCONDITION.CONTINUES);

  const uncertain = freezeCandidate(IDENTITY, injects({}));
  assert.strictEqual(uncertain.spendPostcondition.class, SPEND_POSTCONDITION.UNCERTAIN);

  // Explicit class inject
  const forced = reportSpendPostcondition(1, { spendPostcondition: 'STOPPED' });
  assert.strictEqual(forced.class, 'STOPPED');
  assert.strictEqual(forced.soleHardHalt, false);

  // Suspend fail still reports spend postcondition honestly
  const fail = freezeCandidate(IDENTITY, injects({
    suspend: () => ({ ok: false, method: FREEZE_METHOD }),
    sampleSpend: () => ({ spending: true }),
  }));
  assert.strictEqual(fail.ok, false);
  assert.strictEqual(fail.honest, true);
  assert.strictEqual(fail.spendPostcondition.class, SPEND_POSTCONDITION.CONTINUES);
});

test('test_freeze_capability_operator_envelope', () => {
  const forcedOff = probeFreezeCapability({ forceCapability: false });
  assert.strictEqual(forcedOff.freezeCapability, false);
  assert.strictEqual(forcedOff.envelope, 'non_elevated_operator');
  assert.strictEqual(forcedOff.elevated, false);
  assert.strictEqual(forcedOff.method, FREEZE_METHOD);

  const forcedOn = probeFreezeCapability({ forceCapability: true });
  assert.strictEqual(forcedOn.freezeCapability, true);
  assert.strictEqual(forcedOn.envelope, 'non_elevated_operator');
  assert.strictEqual(forcedOn.proven, true);

  // Without capability, freeze refuses even in armed mode
  const r = freezeCandidate(IDENTITY, injects({ freezeCapability: false }));
  assert.strictEqual(r.ok, false);
  assert.ok(
    r.reason === REASON.FREEZE_CAPABILITY_FALSE || r.error === REASON.FREEZE_UNAVAILABLE,
  );
  assert.strictEqual(isFreezeKillAllowed('armed', false), false);
  assert.strictEqual(isFreezeKillAllowed('armed', true), true);
});

test('test_current_freeze_capability_never_blocks_paint', () => {
  // Cold path must not run PowerShell on the request thread (was ~12s vs
  // Anchor's 5s proxy → "Error connecting … timed out" after restart).
  delete process.env.ZH_FREEZE_CAPABILITY;
  // Fresh require of server helpers (library mode; does not listen).
  const serverPath = require('node:path').join(__dirname, '..', 'src', 'server.js');
  delete require.cache[require.resolve(serverPath)];
  const srv = require(serverPath);
  const t0 = Date.now();
  const cap = srv.currentFreezeCapability();
  const ms = Date.now() - t0;
  assert.ok(ms < 200, `currentFreezeCapability blocked paint for ${ms}ms`);
  assert.strictEqual(typeof cap.freezeCapability, 'boolean');
  // Pending until async probe finishes, or env/cached result — never hang.
  assert.ok(
    cap.reason === 'probe_pending'
      || cap.reason === 'probe_error'
      || cap.reason === 'env_override'
      || cap.reason === 'env_override_false'
      || cap.reason === 'nt_suspend_surface_open_ok'
      || cap.reason === 'nt_suspend_surface_unavailable'
      || cap.reason === 'non_windows_host'
      || typeof cap.reason === 'string',
  );
});

test('test_kill_without_freeze_disabled_until_capability', () => {
  clearKillConfirmTokens();
  assert.strictEqual(isKillWithoutFreezeAllowed(false), false);
  assert.strictEqual(isKillWithoutFreezeAllowed(true), true);

  const tok = issueKillConfirmToken({ pids: [IDENTITY.pid] });
  const refused = killCandidate(IDENTITY, injects({
    freezeCapability: false,
    alreadyFrozen: false,
    confirm: true,
    confirmToken: tok.confirmToken,
  }));
  assert.strictEqual(refused.ok, false);
  assert.strictEqual(refused.reason, REASON.KILL_WITHOUT_FREEZE_DISABLED);
  assert.strictEqual(refused.rowRemoved, false);

  clearKillConfirmTokens();
  const tok2 = issueKillConfirmToken({ pids: [IDENTITY.pid] });
  // With capability, kill-without-freeze path may proceed (still needs confirm + identity)
  const allowed = killCandidate(IDENTITY, injects({
    freezeCapability: true,
    alreadyFrozen: false,
    confirm: true,
    confirmToken: tok2.confirmToken,
  }));
  assert.strictEqual(allowed.ok, true);
  assert.strictEqual(allowed.killed, true);
  assert.strictEqual(allowed.deathVerified, true);
  assert.strictEqual(allowed.rowRemoved, true);
});

test('test_kill_authz_server_validated_confirm', () => {
  clearKillConfirmTokens();
  // Missing confirm
  const noConfirm = killCandidate(IDENTITY, injects({
    confirm: false,
    confirmToken: 'x'.repeat(16),
  }));
  assert.strictEqual(noConfirm.ok, false);
  assert.strictEqual(noConfirm.reason, REASON.KILL_CONFIRM_REQUIRED);

  // Invalid token
  const badTok = killCandidate(IDENTITY, injects({
    confirm: true,
    confirmToken: 'not-issued-token-xx',
  }));
  assert.strictEqual(badTok.ok, false);
  assert.strictEqual(badTok.reason, REASON.KILL_CONFIRM_INVALID);

  // Issued token validates once
  const issued = issueKillConfirmToken({ pids: [IDENTITY.pid] });
  assert.strictEqual(issued.serverValidated, true);
  const v = validateKillConfirm({
    confirm: true,
    confirmToken: issued.confirmToken,
    pids: [IDENTITY.pid],
  });
  assert.strictEqual(v.ok, true);
  // One-shot consumed
  const v2 = validateKillConfirm({
    confirm: true,
    confirmToken: issued.confirmToken,
    pids: [IDENTITY.pid],
  });
  assert.strictEqual(v2.ok, false);

  // Shadow mode authz denies
  clearKillConfirmTokens();
  const tok = issueKillConfirmToken({ pids: [IDENTITY.pid] });
  const shadow = killCandidate(IDENTITY, injects({
    mode: 'shadow',
    freezeCapability: true,
    confirm: true,
    confirmToken: tok.confirmToken,
  }));
  assert.strictEqual(shadow.ok, false);
  assert.ok(
    shadow.reason === REASON.KILL_AUTHZ_DENIED || shadow.error === REASON.KILL_DISABLED,
  );
});

test('test_kill_tree_identity', () => {
  clearKillConfirmTokens();
  const order = [];
  const tok = issueKillConfirmToken({ pids: [IDENTITY.pid] });
  const r = killCandidate(IDENTITY, injects({
    confirm: true,
    confirmToken: tok.confirmToken,
    probeIdentity: () => {
      order.push('reprobe');
      return { ...IDENTITY, alive: true };
    },
    treeKill: (pid) => {
      order.push('treekill');
      assert.strictEqual(pid, IDENTITY.pid);
      return { ok: true, method: 'taskkill_tree' };
    },
    isAlive: () => {
      order.push('death_verify');
      return false;
    },
  }));
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.killed, true);
  assert.strictEqual(r.rowRemoved, true);
  assert.strictEqual(r.deathVerified, true);
  assert.ok(order.indexOf('reprobe') < order.indexOf('treekill'));
  assert.ok(order.indexOf('treekill') < order.indexOf('death_verify'));

  // Death unverified → no row remove
  clearKillConfirmTokens();
  const tok2 = issueKillConfirmToken({ pids: [IDENTITY.pid] });
  const live = killCandidate(IDENTITY, injects({
    confirm: true,
    confirmToken: tok2.confirmToken,
    isAlive: () => true,
  }));
  assert.strictEqual(live.ok, false);
  assert.strictEqual(live.rowRemoved, false);
  assert.strictEqual(live.reason, REASON.KILL_DEATH_UNVERIFIED);
});

test('test_ownership_ipc_fail_closed', () => {
  // Destructive path fail-closes on ownership IPC failure (W6 boundary + W3 stub).
  const r = freezeCandidate(IDENTITY, injects({
    lookupOwnership: () => lookupOwnership(IDENTITY, { forceError: true }),
  }));
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.frozen, false);
  assert.ok(
    r.reason === REASON.FREEZE_OWNERSHIP_IPC_FAIL_CLOSED
    || (r.ownership && r.ownership.reason === OWNERSHIP_IPC_FAIL_CLOSED),
  );
  assert.strictEqual(r.ownership.keep, true);
  assert.strictEqual(r.ownership.failClosed, true);
});

test('test_ownership_race_abort_destructive', () => {
  // Mid-flight registration: first consult unowned, second owned → abort.
  let calls = 0;
  const r = freezeCandidate(IDENTITY, injects({
    lookupOwnership: () => {
      calls += 1;
      if (calls === 1) {
        return lookupOwnership(IDENTITY, { registry: [] });
      }
      return lookupOwnership(IDENTITY, { registry: [IDENTITY] });
    },
  }));
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.frozen, false);
  assert.strictEqual(r.reason, REASON.FREEZE_OWNERSHIP_RACE_ABORT);
  assert.ok(calls >= 2);

  clearKillConfirmTokens();
  const tok = issueKillConfirmToken({ pids: [IDENTITY.pid] });
  const k = killCandidate(IDENTITY, injects({
    confirm: true,
    confirmToken: tok.confirmToken,
    forceOwnershipRace: true,
  }));
  assert.strictEqual(k.ok, false);
  assert.strictEqual(k.killed, false);
  assert.strictEqual(k.rowRemoved, false);
  assert.strictEqual(k.reason, REASON.KILL_OWNERSHIP_RACE_ABORT);
});

test('test_anchor_owned_keep_no_node_kill', () => {
  clearKillConfirmTokens();
  const owned = freezeCandidate(IDENTITY, injects({
    lookupOwnership: () => lookupOwnership(IDENTITY, {
      registry: [{ pid: IDENTITY.pid, createTime: IDENTITY.createTime }],
    }),
  }));
  assert.strictEqual(owned.ok, false);
  assert.strictEqual(owned.frozen, false);
  assert.strictEqual(owned.reason, REASON.ANCHOR_OWNED_NO_NODE_KILL);
  assert.strictEqual(owned.ownership.owned, true);
  assert.strictEqual(owned.ownership.reason, OWNERSHIP_REGISTERED_KEEP);

  const tok = issueKillConfirmToken({ pids: [IDENTITY.pid] });
  const kill = killCandidate(IDENTITY, injects({
    confirm: true,
    confirmToken: tok.confirmToken,
    lookupOwnership: () => lookupOwnership(IDENTITY, {
      registry: [{ pid: IDENTITY.pid, createTime: IDENTITY.createTime }],
    }),
    treeKill: () => {
      throw new Error('must never tree-kill Anchor-owned');
    },
  }));
  assert.strictEqual(kill.ok, false);
  assert.strictEqual(kill.killed, false);
  assert.strictEqual(kill.rowRemoved, false);
  assert.strictEqual(kill.reason, REASON.ANCHOR_OWNED_NO_NODE_KILL);
});

test('Wave 6 SoftFreeze gone — unfreeze via sole boundary', () => {
  const r = unfreezeCandidate(IDENTITY, injects());
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.boundary, SOLE_BOUNDARY_ID);
});

test('reProbeIdentity helper matches production order', () => {
  const deps = {
    probeIdentity: () => ({ ...IDENTITY, alive: true }),
  };
  const ok = reProbeIdentity(IDENTITY, deps);
  assert.strictEqual(ok.ok, true);
  assert.strictEqual(ok.matched, true);
});
