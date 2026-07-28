// W4 / G3 — Joint quad fail-closed gate + unsupervised spender true-positive (OL1 prep).

const { test } = require('node:test');
const assert = require('node:assert');

const {
  classifyCandidate,
  productionHostWalk,
  productionEngineLeg,
  productionSpendLeg,
  productionOwnership,
  productionQuad,
  indexProcessesByPid,
  evaluateQuad,
  VERDICT_WOULD_BE_RED,
  VERDICT_KEEP,
  VERDICT_ABSTAIN,
} = (() => {
  const c = require('../src/classify.js');
  const q = require('../src/quad.js');
  return {
    classifyCandidate: c.classifyCandidate,
    productionHostWalk: c.productionHostWalk,
    productionEngineLeg: c.productionEngineLeg,
    productionSpendLeg: c.productionSpendLeg,
    productionOwnership: c.productionOwnership,
    productionQuad: c.productionQuad,
    indexProcessesByPid: c.indexProcessesByPid,
    evaluateQuad: c.evaluateQuad,
    VERDICT_WOULD_BE_RED: q.VERDICT_WOULD_BE_RED,
    VERDICT_KEEP: q.VERDICT_KEEP,
    VERDICT_ABSTAIN: q.VERDICT_ABSTAIN,
  };
})();

const {
  resolveClassifierMode,
  isActionableRedAllowed,
  currentHashes,
  atlasBumpForcesReshadow,
  resolveModeWithAtlasReshadow,
  SPEND_ATLAS_HASH,
} = require('../src/mode.js');

const {
  evaluateDualWriteSurfaces,
  assertNoActionableRedUnderShadow,
  SURFACES,
} = require('../src/dual-write.js');

const { lookupOwnership } = require('../src/ownership.js');
const { hasEngineKeywordHint } = require('../src/engine-leg.js');
const { isKnownReasonCode } = require('../src/reason-catalog.js');
const { positiveAtlasHosts } = require('../src/spend.js');

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

function tree(nodes) {
  return nodes;
}

/** Geometry (A) reparented orphan under services.exe */
function orphanGeometryA(enginePid = 300) {
  const t0 = 3_000_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const engine = node(enginePid, 4, 'C:\\Users\\x\\claude.exe', t0 + 5000);
  return { services, engine, nodes: [services, engine], t0 };
}

/** Geometry (B) non-interactive job host not in H → R */
function orphanGeometryB(enginePid = 301) {
  const t0 = 3_000_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const task = node(60, 4, 'C:\\Windows\\System32\\taskhostw.exe', t0 + 100);
  const engine = node(enginePid, 60, 'C:\\Users\\x\\agy.exe', t0 + 200);
  return { services, task, engine, nodes: [services, task, engine], t0 };
}

function atlasSpendFor(pid, host = 'api.anthropic.com') {
  return {
    connections: [
      { owningPid: pid, remotePort: 443, remoteHost: host },
    ],
  };
}

test('test_zombie_quad_gate_fail_closed — joint positive orphan dual-run shadow', () => {
  const { engine, nodes } = orphanGeometryA(9001);
  const host = positiveAtlasHosts()[0];
  const result = classifyCandidate(engine, nodes, {
    spend: atlasSpendFor(engine.pid, host),
    ownership: { registry: [] },
    classifierMode: 'shadow',
  });

  assert.strictEqual(result.engine.isEnginePositive, true);
  assert.strictEqual(result.spend.spendPositive, true);
  assert.strictEqual(result.supervision.status, 'UNSUPERVISED');
  assert.strictEqual(result.ownership.owned, false);
  assert.strictEqual(result.quad.verdict, VERDICT_WOULD_BE_RED);
  assert.strictEqual(result.wouldBeActionableRed, true);
  assert.strictEqual(result.dualRunShadow.wouldBeActionableRed, true);
  assert.strictEqual(result.dualRunShadow.observeOnly, true);
  assert.strictEqual(result.dualRunShadow.actionableRed, false);
  assert.strictEqual(result.classifierMode, 'shadow');
  assert.strictEqual(isActionableRedAllowed(result.classifierMode), false);

  // Dual-write surfaces stay non-actionable under shadow
  assert.strictEqual(result.dualWrite.anySurfaceActionableRed, false);
  assert.ok(assertNoActionableRedUnderShadow(result.dualWrite));
  for (const s of SURFACES) {
    assert.strictEqual(result.dualWrite.surfaces[s].actionableRed, false, s);
  }

  for (const code of result.row.reasonCodes) {
    assert.ok(isKnownReasonCode(code), `closed catalog: ${code}`);
  }
});

test('test_zombie_quad_gate_fail_closed — supervised interactive KEEP not RED', () => {
  const t0 = 5_000_000;
  const code = node(10, 0, 'C:\\Users\\x\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe', t0);
  const engine = node(11, 10, 'C:\\Users\\x\\claude.exe', t0 + 100);
  const nodes = [code, engine];
  const result = classifyCandidate(engine, nodes, {
    spend: atlasSpendFor(engine.pid, 'api.anthropic.com'),
    ownership: { registry: [] },
    classifierMode: 'shadow',
  });

  assert.strictEqual(result.supervision.status, 'SUPERVISED');
  assert.strictEqual(result.wouldBeActionableRed, false);
  assert.strictEqual(result.quad.verdict, VERDICT_KEEP);
  assert.strictEqual(result.dualRunShadow.wouldBeActionableRed, false);
});

test('test_zombie_quad_gate_fail_closed — uncertain spend or ownership aborts RED', () => {
  const { engine, nodes } = orphanGeometryA(9002);

  const stale = classifyCandidate(engine, nodes, {
    spend: { forceStale: true, connections: atlasSpendFor(engine.pid).connections },
    ownership: { registry: [] },
  });
  assert.strictEqual(stale.quad.verdict, VERDICT_ABSTAIN);
  assert.strictEqual(stale.wouldBeActionableRed, false);

  const owned = classifyCandidate(engine, nodes, {
    spend: atlasSpendFor(engine.pid),
    ownership: { registry: [engine.pid] },
  });
  assert.strictEqual(owned.quad.verdict, VERDICT_KEEP);
  assert.strictEqual(owned.wouldBeActionableRed, false);

  const noSpend = classifyCandidate(engine, nodes, {
    spend: {
      connections: [
        { owningPid: engine.pid, remotePort: 443, remoteHost: 'www.google.com' },
      ],
    },
    ownership: { registry: [] },
  });
  assert.strictEqual(noSpend.wouldBeActionableRed, false);
  assert.notStrictEqual(noSpend.quad.verdict, VERDICT_WOULD_BE_RED);
});

test('test_unsupervised_spender_true_positive — geometry A or B on production walk path', () => {
  // Geometry A
  {
    const { engine, nodes } = orphanGeometryA(3100);
    const walk = productionHostWalk(engine, indexProcessesByPid(nodes));
    assert.strictEqual(walk.status, 'UNSUPERVISED', 'geometry A walk');
    assert.strictEqual(walk.reason, 'WALK_COMPLETE_SYSTEM_ROOT');

    const eng = productionEngineLeg(engine, indexProcessesByPid(nodes));
    assert.strictEqual(eng.isEnginePositive, true);

    const sp = productionSpendLeg({
      pid: engine.pid,
      connections: [
        { owningPid: engine.pid, remotePort: 443, remoteHost: 'api.claude.ai' },
      ],
    });
    assert.strictEqual(sp.spendPositive, true);

    const own = productionOwnership({ pid: engine.pid }, { registry: [] });
    assert.strictEqual(own.owned, false);

    const quad = productionQuad({
      engine: eng,
      spend: sp,
      supervision: walk,
      ownership: own,
    });
    assert.strictEqual(quad.wouldBeActionableRed, true);
    assert.strictEqual(quad.jointPositive, true);

    // Same production classifyCandidate path
    const full = classifyCandidate(engine, nodes, {
      spend: {
        connections: [
          { owningPid: engine.pid, remotePort: 443, remoteHost: 'api.claude.ai' },
        ],
      },
      ownership: { registry: [] },
    });
    assert.strictEqual(full.wouldBeActionableRed, true);
    assert.strictEqual(full.observe.wouldBeActionableRed, true);
    assert.strictEqual(full.dualWrite.anySurfaceActionableRed, false);
  }

  // Geometry B
  {
    const { engine, nodes } = orphanGeometryB(3200);
    const walk = productionHostWalk(engine, indexProcessesByPid(nodes));
    assert.strictEqual(walk.status, 'UNSUPERVISED', 'geometry B walk');

    const full = classifyCandidate(engine, nodes, {
      spend: {
        connections: [
          {
            owningPid: engine.pid,
            remotePort: 443,
            remoteHost: 'generativelanguage.googleapis.com',
          },
        ],
      },
      ownership: { registry: [] },
    });
    assert.strictEqual(full.engine.isEnginePositive, true);
    assert.strictEqual(full.spend.spendPositive, true);
    assert.strictEqual(full.wouldBeActionableRed, true);
    assert.ok(full.dualRunShadow.wouldBeActionableRed);
  }
});

test('test_atlas_bump_forces_reshadow scaffolding', () => {
  const live = currentHashes();
  assert.strictEqual(live.spendAtlasHash, SPEND_ATLAS_HASH);
  assert.ok(live.spendAtlasHash.startsWith('w4-') || live.spendAtlasHash.length > 0);

  const match = atlasBumpForcesReshadow(live, live);
  assert.strictEqual(match.forceReshadow, false);

  const bumped = atlasBumpForcesReshadow(
    { ...live, spendAtlasHash: 'old-spend-atlas' },
    live,
  );
  assert.strictEqual(bumped.forceReshadow, true);
  assert.ok(bumped.bumped.includes('spendAtlasHash'));

  // Receipt with stale spend hash → resolveModeWithAtlasReshadow stays shadow
  const receipt = {
    classifierVersion: live.classifierVersion,
    hostAllowlistHash: live.hostAllowlistHash,
    engineAtlasHash: live.engineAtlasHash,
    spendAtlasHash: 'stale-or-pending-w4',
  };
  const r = resolveModeWithAtlasReshadow({
    requestedMode: 'armed',
    receipt,
  });
  assert.strictEqual(r.mode, 'shadow');
  assert.strictEqual(r.forced, true);
  assert.strictEqual(r.receiptValid, false);

  // Matching SC1 canary receipt would be eligible (no Freeze yet)
  const okReceipt = {
    ...live,
    sc1CanaryGreen: true,
    sc1Gate: { green: true },
    evidencePaths: ['fixtures/sc1/evidence/sc1-canary-gate.json'],
  };
  const armed = resolveClassifierMode({
    requestedMode: 'armed',
    receipt: okReceipt,
  });
  assert.strictEqual(armed.mode, 'armed');
  assert.strictEqual(armed.receiptValid, true);
  // But actionable scare still not production Freeze — mode alone is enough for G0 law
  assert.strictEqual(isActionableRedAllowed(armed.mode), true);
});

test('test_idle_keyword_only_hidden — no dual-write candidate chrome', () => {
  // Keyword-only node process is not engine-positive → never a would-be zombie row.
  const t0 = 6_000_000;
  const services = node(4, 0, 'C:\\Windows\\System32\\services.exe', t0);
  const idle = node(
    400,
    4,
    'C:\\Program Files\\nodejs\\node.exe',
    t0 + 100,
    'node.exe <path>',
  );
  assert.ok(hasEngineKeywordHint(idle.commandLine, idle.name));

  const eng = productionEngineLeg(idle, indexProcessesByPid([services, idle]));
  assert.strictEqual(eng.isEnginePositive, false, 'keyword-only must not be engine-positive');

  // Even with atlas-matched spend on the same PID, incomplete joint (no engine) ⇒ not RED
  const sp = productionSpendLeg({
    pid: idle.pid,
    connections: [
      { owningPid: idle.pid, remotePort: 443, remoteHost: 'api.anthropic.com' },
    ],
  });
  const walk = productionHostWalk(idle, indexProcessesByPid([services, idle]));
  const own = lookupOwnership({ pid: idle.pid }, { registry: [] });
  const quad = evaluateQuad({
    engine: eng,
    spend: sp,
    supervision: walk,
    ownership: own,
  });
  assert.strictEqual(quad.wouldBeActionableRed, false);
  assert.strictEqual(quad.jointPositive, false);

  // Dual-write with empty would-be list → no scare chrome
  const mode = resolveClassifierMode({ requestedMode: 'shadow', receipt: null });
  const dual = evaluateDualWriteSurfaces({
    classifierMode: mode.mode,
    legacyWouldBeZombies: [],
    newWouldBeZombies: [],
  });
  assert.strictEqual(dual.observe.wouldBeActionableRed, false);
  assert.strictEqual(dual.anySurfaceActionableRed, false);
  for (const s of SURFACES) {
    assert.strictEqual(dual.surfaces[s].actionableRed, false, s);
    assert.strictEqual(dual.surfaces[s].actionableCount, 0, s);
  }
});
