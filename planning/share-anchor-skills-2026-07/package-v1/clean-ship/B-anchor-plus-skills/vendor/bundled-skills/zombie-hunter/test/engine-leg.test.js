// W2 / C3 — Closed engine allowlist E1 + support-ancestry E2 unit pack.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  productionEngineLeg,
  evaluateEngineLeg,
  indexProcessesByPid,
  ENGINE_ALLOWLIST_E1,
  SUPPORT_ALLOWLIST_E2,
  SUPPORT_HOP_CAP_K,
  hasEngineKeywordHint,
} = require('../src/classify.js');

const {
  matchEngineE1,
  ENGINE_NEGATIVE_BASENAMES,
} = require('../src/engine-leg.js');

function tree(nodes) {
  return indexProcessesByPid(nodes);
}

function node(pid, ppid, imagePath, createTime = 1000, commandLine = '') {
  return {
    pid,
    ppid,
    imagePath,
    name: String(imagePath).split(/[/\\]/).pop(),
    createTime,
    commandLine,
  };
}

test('test_engine_closed_allowlist', () => {
  assert.ok(SUPPORT_ALLOWLIST_E2.length <= 16, 'E2 list size ≤16');
  assert.strictEqual(SUPPORT_HOP_CAP_K, 2);

  for (const name of ENGINE_ALLOWLIST_E1) {
    const hit = matchEngineE1(`${name}.exe`);
    assert.ok(hit.matched, `E1 must match ${name}`);
  }

  // Production evaluate on image
  const byPid = tree([]);
  for (const name of ['claude', 'agy', 'gemini', 'grok']) {
    const r = productionEngineLeg(node(1, 0, `C:\\bin\\${name}.exe`), byPid);
    assert.strictEqual(r.isEnginePositive, true, name);
    assert.strictEqual(r.isE1, true, name);
    assert.strictEqual(r.reason, 'E1_CLOSED_ALLOWLIST');
  }
});

test('test_cmdline_alone_not_engine', () => {
  // Cmdline mentions claude; image is powershell → not engine-positive.
  const p = node(
    10,
    0,
    'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe',
    1000,
    'powershell.exe -Command claude -p "hi"',
  );
  const r = productionEngineLeg(p, tree([p]));
  assert.strictEqual(r.isEnginePositive, false);
  assert.ok(hasEngineKeywordHint(p.commandLine, p.name), 'keyword may still be present');
});

test('test_engine_negative_wrappers_installers_ides', () => {
  const negatives = [
    'C:\\Users\\x\\Downloads\\Claude Setup.exe',
    'C:\\Program Files\\Microsoft VS Code\\Code.exe',
    'C:\\Users\\x\\AppData\\Local\\Programs\\cursor\\Cursor.exe',
    'C:\\Windows\\System32\\msiexec.exe',
    'C:\\Program Files\\Claude\\claude-updater.exe',
  ];
  for (const image of negatives) {
    const r = productionEngineLeg(node(1, 0, image), tree([]));
    assert.strictEqual(r.isEnginePositive, false, image);
  }
  // Table includes IDE / installer basenames
  assert.ok(ENGINE_NEGATIVE_BASENAMES.includes('code'));
  assert.ok(ENGINE_NEGATIVE_BASENAMES.includes('cursor'));
});

test('test_support_ancestry_cap_and_hop_limit', () => {
  // python child of claude within K=1 → E2 support positive
  const claude = node(100, 4, 'C:\\Users\\x\\claude.exe', 1000);
  const py = node(101, 100, 'C:\\Python\\python.exe', 1100, 'python.exe worker.py');
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', 500);
  const byPid = tree([services, claude, py]);
  const ok = productionEngineLeg(py, byPid);
  assert.strictEqual(ok.isEnginePositive, true);
  assert.strictEqual(ok.isE2Support, true);
  assert.strictEqual(ok.reason, 'E2_SUPPORT_ANCESTRY');
  assert.ok(ok.supportHops <= SUPPORT_HOP_CAP_K);

  // node three hops below claude (K=2) → not support
  // chain: claude(100) → mid1(102) → mid2(103) → node(104)
  // hops from node: 103 (1), 102 (2), 100 (3) — E1 at hop 3 > K=2
  const mid1 = node(102, 100, 'C:\\app\\wrapper1.exe', 1050);
  const mid2 = node(103, 102, 'C:\\app\\wrapper2.exe', 1060);
  const deepNode = node(104, 103, 'C:\\Program Files\\nodejs\\node.exe', 1070);
  const deepTree = tree([services, claude, mid1, mid2, deepNode]);
  const no = productionEngineLeg(deepNode, deepTree);
  assert.strictEqual(no.isEnginePositive, false, 'hop > K must not be E2');
  assert.strictEqual(no.reason, 'E2_NO_E1_WITHIN_K');
});

test('test_support_ancestry_generic_node_parent_not_engine', () => {
  // Generic node with no E1 ancestor within K is not engine-positive.
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', 500);
  const nodeProc = node(50, 4, 'C:\\Program Files\\nodejs\\node.exe', 1000, 'node.exe server.js');
  const r = productionEngineLeg(nodeProc, tree([services, nodeProc]));
  assert.strictEqual(r.isEnginePositive, false);
  assert.strictEqual(r.isE1, false);
  assert.strictEqual(r.isE2Support, false);
});

test('test_idle_keyword_only_hidden', () => {
  // Keyword-only processes are not engine-positive (hidden at classify layer).
  const tail = node(
    9,
    4,
    'C:\\Windows\\System32\\cmd.exe',
    1000,
    'cmd.exe /c type C:\\logs\\claude-session.log',
  );
  const r = evaluateEngineLeg(tail, tree([tail]));
  assert.strictEqual(r.isEnginePositive, false);
  assert.ok(hasEngineKeywordHint(tail.commandLine, tail.name));
});

test('grok candidate is E1 engine; grok ancestor is host not this leg alone', () => {
  const spender = node(1, 0, 'C:\\Users\\x\\grok.exe', 1000);
  const e = productionEngineLeg(spender, tree([spender]));
  assert.strictEqual(e.isE1, true);
  assert.strictEqual(e.engineClass, 'grok');
});
