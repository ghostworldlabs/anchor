// W2 / C1+G1 — Host-walk geometry unit pack (forced shadow; no SC1 claim).
// Production path: classify.productionHostWalk / host-walk.js

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const {
  productionHostWalk,
  walkHostSupervision,
  matchHostAllowlist,
  normalizeImageBasename,
  indexProcessesByPid,
  HOST_WALK_MAX_DEPTH,
  HOST_ALLOWLIST_H,
  SYSTEM_ROOT_SET_R,
} = require('../src/classify.js');

const {
  HOST_NEAR_MISS_NEGATIVES,
} = require('../src/host-walk.js');

const { resolveClassifierMode, isActionableRedAllowed } = require('../src/mode.js');

/** Build a tree index from an array of walk nodes. */
function tree(nodes) {
  return indexProcessesByPid(nodes);
}

function node(pid, ppid, imagePath, createTime, commandLine = '') {
  return {
    pid,
    ppid,
    imagePath,
    name: path.basename(String(imagePath).replace(/\//g, '\\')),
    createTime,
    commandLine,
  };
}

// ── Golden supervised ancestor trees (fixture IDs) ─────────────────────────

const SUPERVISED_FIXTURES = [
  {
    fixtureId: 'F-H-CODE',
    hostImage: 'C:\\Users\\x\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe',
    hostName: 'Code.exe',
  },
  {
    fixtureId: 'F-H-CODE-INSIDERS',
    hostImage: 'C:\\Users\\x\\AppData\\Local\\Programs\\Microsoft VS Code Insiders\\Code - Insiders.exe',
    hostName: 'Code - Insiders.exe',
  },
  {
    fixtureId: 'F-H-CURSOR',
    hostImage: 'C:\\Users\\x\\AppData\\Local\\Programs\\cursor\\Cursor.exe',
    hostName: 'Cursor.exe',
  },
  {
    fixtureId: 'F-H-WT',
    hostImage: 'C:\\Windows\\System32\\WindowsTerminal.exe',
    hostName: 'WindowsTerminal.exe',
  },
  {
    fixtureId: 'F-H-OPENCONSOLE',
    hostImage: 'C:\\Windows\\System32\\OpenConsole.exe',
    hostName: 'OpenConsole.exe',
  },
  {
    fixtureId: 'F-H-GROK',
    hostImage: 'C:\\Users\\x\\AppData\\Local\\Programs\\grok\\grok.exe',
    hostName: 'grok.exe',
  },
  {
    fixtureId: 'F-H-ANCHOR',
    hostImage: 'C:\\Python\\python.exe',
    hostName: 'python.exe',
    hostCmd: 'python.exe <path>',
  },
  {
    fixtureId: 'F-H-SHELL',
    hostImage: 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
    hostName: 'powershell.exe',
  },
  {
    fixtureId: 'F-H-EXPLORER',
    hostImage: 'C:\\Windows\\explorer.exe',
    hostName: 'explorer.exe',
  },
  {
    fixtureId: 'F-H-CONHOST-ANC',
    hostImage: 'C:\\Windows\\System32\\conhost.exe',
    hostName: 'conhost.exe',
  },
];

test('test_host_walk_supervised_ide_wt_anchor_shell_explorer', () => {
  // Plan name + full NS host set (every fixture SUPERVISED on production walk).
  const mode = resolveClassifierMode({ requestedMode: 'shadow', receipt: null });
  assert.strictEqual(mode.mode, 'shadow');
  assert.strictEqual(isActionableRedAllowed(mode.mode), false);

  for (const fx of SUPERVISED_FIXTURES) {
    const t0 = 1_000_000;
    const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
    // Active interactive user session (SessionId > 0) — not services session 0.
    const host = {
      ...node(100, 4, fx.hostImage, t0 + 1000, fx.hostCmd || ''),
      sessionId: 1,
    };
    const engine = node(200, 100, 'C:\\Users\\x\\claude.exe', t0 + 2000);
    const byPid = tree([services, host, engine]);
    const r = productionHostWalk(engine, byPid);
    assert.strictEqual(r.status, 'SUPERVISED', `${fx.fixtureId} must SUPERVISE`);
    assert.strictEqual(r.supervised, true);
    assert.strictEqual(r.unsupervised, false);
    assert.strictEqual(r.fixtureId, fx.fixtureId, `${fx.fixtureId} fixture id`);
    assert.ok(r.parentAlive);
    assert.strictEqual(r.hostActive, true);
  }
});

test('test_host_walk_supervised_full_ns_host_set', () => {
  // G1 alias: every H row has a fixture id covered above.
  const ids = new Set(SUPERVISED_FIXTURES.map((f) => f.fixtureId));
  for (const row of HOST_ALLOWLIST_H) {
    assert.ok(ids.has(row.fixtureId), `H row ${row.id} needs fixture ${row.fixtureId}`);
  }
  assert.ok(SYSTEM_ROOT_SET_R.has('services'));
  assert.strictEqual(HOST_WALK_MAX_DEPTH, 32);
});

test('test_ambient_conhost_sibling_not_supervision', () => {
  // conhost as sibling of candidate (not on parent chain) must NOT supervise.
  const t0 = 2_000_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const parent = node(50, 4, 'C:\\Windows\\System32\\svchost.exe', t0 + 100); // not in H
  const engine = node(200, 50, 'C:\\Users\\x\\claude.exe', t0 + 200);
  const conhostSibling = node(201, 50, 'C:\\Windows\\System32\\conhost.exe', t0 + 200);
  const byPid = tree([services, parent, engine, conhostSibling]);
  const r = productionHostWalk(engine, byPid);
  // Walk goes engine→svchost→services (R), zero H on chain → UNSUPERVISED
  assert.strictEqual(r.status, 'UNSUPERVISED', 'sibling conhost is not ancestry supervision');
  assert.notStrictEqual(r.fixtureId, 'F-H-CONHOST-ANC');
});

test('test_orphan_detached_spender_unsupervised', () => {
  const t0 = 3_000_000;

  // Geometry (A) reparented orphan under services.exe
  {
    const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
    const engine = node(300, 4, 'C:\\Users\\x\\claude.exe', t0 + 5000);
    const r = productionHostWalk(engine, tree([services, engine]));
    assert.strictEqual(r.status, 'UNSUPERVISED', 'geometry A');
    assert.strictEqual(r.reason, 'WALK_COMPLETE_SYSTEM_ROOT');
    assert.ok(r.unsupervised);
  }

  // Geometry (B) non-interactive job host not in H → … → R
  {
    const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
    const task = node(60, 4, 'C:\\Windows\\System32\\taskhostw.exe', t0 + 100);
    const engine = node(301, 60, 'C:\\Users\\x\\agy.exe', t0 + 200);
    const r = productionHostWalk(engine, tree([services, task, engine]));
    assert.strictEqual(r.status, 'UNSUPERVISED', 'geometry B');
  }

  // Geometry (C) double-detached service helper chain → R
  {
    const smss = node(4, 0, 'C:\\Windows\\System32\\smss.exe', t0);
    const helper = node(70, 4, 'C:\\Windows\\System32\\svchost.exe', t0 + 50);
    const helper2 = node(71, 70, 'C:\\Program Files\\SomeService\\helper.exe', t0 + 100);
    const engine = node(302, 71, 'C:\\Users\\x\\grok.exe', t0 + 200);
    const r = productionHostWalk(engine, tree([smss, helper, helper2, engine]));
    assert.strictEqual(r.status, 'UNSUPERVISED', 'geometry C');
  }
});

test('test_walk_truncation_uncertain', () => {
  const t0 = 4_000_000;

  // Missing parent
  {
    const engine = node(400, 99999, 'C:\\Users\\x\\claude.exe', t0);
    const r = productionHostWalk(engine, tree([engine]));
    assert.strictEqual(r.status, 'UNCERTAIN');
    assert.strictEqual(r.reason, 'MISSING_PARENT');
    assert.strictEqual(r.unsupervised, false);
  }

  // PPID cycle
  {
    const a = node(10, 11, 'C:\\Windows\\System32\\a.exe', t0);
    const b = node(11, 10, 'C:\\Windows\\System32\\b.exe', t0 + 1);
    const engine = node(12, 10, 'C:\\Users\\x\\claude.exe', t0 + 2);
    const r = productionHostWalk(engine, tree([a, b, engine]));
    assert.strictEqual(r.status, 'UNCERTAIN');
    assert.ok(r.reason === 'PPID_CYCLE' || r.reason === 'MISSING_ANCESTOR' || r.reason === 'DEPTH_TRUNCATION'
      || r.status === 'UNCERTAIN');
    assert.strictEqual(r.unsupervised, false);
  }

  // createTime inversion (parent younger than child)
  {
    const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', 5000);
    const parent = node(20, 4, 'C:\\Windows\\System32\\svchost.exe', 9000); // after child
    const engine = node(21, 20, 'C:\\Users\\x\\claude.exe', 1000); // older createTime than parent
    const r = productionHostWalk(engine, tree([services, parent, engine]));
    assert.strictEqual(r.status, 'UNCERTAIN');
    assert.strictEqual(r.reason, 'CREATETIME_INVERSION');
    assert.strictEqual(r.unsupervised, false);
  }

  // Depth truncation past D=32
  {
    const nodes = [];
    // Long non-H, non-R chain
    nodes.push(node(1, 0, 'C:\\Windows\\System32\\mystery_root.exe', 1000));
    for (let i = 2; i <= 40; i += 1) {
      nodes.push(node(i, i - 1, `C:\\app\\layer${i}.exe`, 1000 + i));
    }
    const engine = node(41, 40, 'C:\\Users\\x\\claude.exe', 2000);
    nodes.push(engine);
    const r = productionHostWalk(engine, tree(nodes));
    assert.strictEqual(r.status, 'UNCERTAIN');
    assert.ok(
      r.reason === 'DEPTH_TRUNCATION' || r.reason === 'MISSING_ANCESTOR',
      `expected truncation-class reason, got ${r.reason}`,
    );
    assert.strictEqual(r.unsupervised, false);
  }
});

test('test_allowlist_match_normalize_near_miss', () => {
  // Positives through shared normalize path
  assert.strictEqual(matchHostAllowlist('Code.exe').matched, true);
  assert.strictEqual(matchHostAllowlist('C:\\x\\Code.exe').hostId, 'code');
  assert.strictEqual(matchHostAllowlist('Code - Insiders.exe').matched, true);
  assert.strictEqual(matchHostAllowlist('Code - Insiders.exe').hostId, 'code-insiders');
  assert.strictEqual(matchHostAllowlist('code - insiders').matched, true);
  assert.strictEqual(matchHostAllowlist('OpenConsole.exe').matched, true);
  assert.strictEqual(matchHostAllowlist('openconsole').matched, true);
  assert.strictEqual(matchHostAllowlist('WindowsTerminal.exe').matched, true);
  assert.strictEqual(matchHostAllowlist('wt.exe').matched, true);
  assert.strictEqual(matchHostAllowlist('wt.exe').hostId, 'windowsterminal');
  assert.strictEqual(matchHostAllowlist('grok.exe').matched, true);
  assert.strictEqual(matchHostAllowlist('grok.exe').hostId, 'grok');

  // Near-miss negatives
  for (const miss of HOST_NEAR_MISS_NEGATIVES) {
    if (miss === 'python' || miss === 'pythonw') {
      // bare python without cmdline gate
      assert.strictEqual(
        matchHostAllowlist(`${miss}.exe`, 'python.exe script.py').matched,
        false,
        `near-miss ${miss}`,
      );
      continue;
    }
    assert.strictEqual(
      matchHostAllowlist(miss).matched,
      false,
      `near-miss ${miss}`,
    );
  }

  // Normalize strip + case
  assert.strictEqual(normalizeImageBasename('C:\\A\\B\\Code.EXE'), 'code');
  assert.strictEqual(normalizeImageBasename('Code - Insiders.exe'), 'code - insiders');
});

test('test_allowlist_normalize_code_insiders_openconsole_grok', () => {
  // Mandatory GWTs for Insiders / OpenConsole / grok-as-host
  const insiders = matchHostAllowlist('Code - Insiders.exe');
  assert.ok(insiders.matched);
  assert.strictEqual(insiders.fixtureId, 'F-H-CODE-INSIDERS');

  const oc = matchHostAllowlist('OpenConsole.exe');
  assert.ok(oc.matched);
  assert.strictEqual(oc.fixtureId, 'F-H-OPENCONSOLE');

  // grok.exe as parent host of child spender (walk, not E1-only)
  const t0 = 5_000_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const grokHost = node(80, 4, 'C:\\Users\\x\\grok.exe', t0 + 10);
  const child = node(81, 80, 'C:\\Users\\x\\node.exe', t0 + 20);
  const r = productionHostWalk(child, tree([services, grokHost, child]));
  assert.strictEqual(r.status, 'SUPERVISED');
  assert.strictEqual(r.hostId, 'grok');
  assert.strictEqual(r.fixtureId, 'F-H-GROK');
});

test('test_no_supervision_weak_root_symbol', () => {
  // Ban SUPERVISION_WEAK_ROOT: must not appear as a live symbol in production sources.
  const srcDir = path.join(__dirname, '..', 'src');
  const files = fs.readdirSync(srcDir).filter((f) => f.endsWith('.js'));
  for (const f of files) {
    const body = fs.readFileSync(path.join(srcDir, f), 'utf8');
    assert.ok(
      !/\bSUPERVISION_WEAK_ROOT\b/.test(body),
      `${f} must not define or reference SUPERVISION_WEAK_ROOT`,
    );
  }
  // Module exports must not include it
  const hw = require('../src/host-walk.js');
  assert.strictEqual(hw.SUPERVISION_WEAK_ROOT, undefined);
  const cl = require('../src/classify.js');
  assert.strictEqual(cl.SUPERVISION_WEAK_ROOT, undefined);
});

test('uncertain never becomes unsupervised for would-be RED shape', () => {
  // Direct invariant: UNCERTAIN ⇒ unsupervised === false
  const engine = node(1, 999, 'claude.exe', 100);
  const r = walkHostSupervision(engine, tree([engine]));
  assert.strictEqual(r.status, 'UNCERTAIN');
  assert.strictEqual(r.unsupervised, false);
  assert.strictEqual(r.supervised, false);
});

// ── Active-session hardening (John 2026-07-23) ─────────────────────────────

test('test_inactive_shell_session0_does_not_supervise_spender', () => {
  // Orphaned PowerShell in session 0 under services must NOT KEEP a spender.
  const t0 = 9_000_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const shell = {
    ...node(80, 4, 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', t0 + 100),
    sessionId: 0,
  };
  const engine = node(200, 80, 'C:\\Users\\x\\claude.exe', t0 + 200);
  const r = productionHostWalk(engine, tree([services, shell, engine]));
  assert.strictEqual(r.status, 'UNSUPERVISED', 'session-0 shell is not an active terminal session');
  assert.strictEqual(r.fixtureId, null);
});

test('test_active_shell_interactive_session_supervises', () => {
  const t0 = 9_100_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const shell = {
    ...node(80, 4, 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', t0 + 100),
    sessionId: 2,
  };
  const engine = node(200, 80, 'C:\\Users\\x\\claude.exe', t0 + 200);
  const r = productionHostWalk(engine, tree([services, shell, engine]));
  assert.strictEqual(r.status, 'SUPERVISED', 'interactive shell session must SUPERVISE');
  assert.strictEqual(r.fixtureId, 'F-H-SHELL');
  assert.strictEqual(r.hostActive, true);
});

test('test_orphaned_shell_under_taskeng_does_not_supervise', () => {
  // Shell with missing sessionId but job-only parents → inactive (not a live terminal).
  const t0 = 9_200_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const task = node(50, 4, 'C:\\Windows\\System32\\svchost.exe', t0 + 50);
  const taskeng = node(60, 50, 'C:\\Windows\\System32\\taskeng.exe', t0 + 100);
  const shell = node(80, 60, 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', t0 + 150);
  const engine = node(200, 80, 'C:\\Users\\x\\node.exe', t0 + 200);
  const r = productionHostWalk(engine, tree([services, task, taskeng, shell, engine]));
  assert.strictEqual(r.status, 'UNSUPERVISED', 'job-orphaned shell must not SUPERVISE');
});

test('test_active_vscode_session_supervises', () => {
  const t0 = 9_300_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const code = {
    ...node(100, 4, 'C:\\Users\\x\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe', t0 + 100),
    sessionId: 1,
  };
  const engine = node(200, 100, 'C:\\Users\\x\\claude.exe', t0 + 200);
  const r = productionHostWalk(engine, tree([services, code, engine]));
  assert.strictEqual(r.status, 'SUPERVISED');
  assert.strictEqual(r.fixtureId, 'F-H-CODE');
});

test('test_isHostSessionActive_export', () => {
  const { isHostSessionActive } = require('../src/host-walk.js');
  const shell0 = { pid: 1, ppid: 4, imagePath: 'powershell.exe', name: 'powershell.exe', sessionId: 0, commandLine: '', createTime: 1 };
  const a = isHostSessionActive(shell0, 'shell', new Map());
  assert.strictEqual(a.active, false);
  assert.strictEqual(a.reason, 'HOST_SHELL_SESSION0');
  const shell2 = { ...shell0, sessionId: 2 };
  const b = isHostSessionActive(shell2, 'shell', new Map());
  assert.strictEqual(b.active, true);
});
