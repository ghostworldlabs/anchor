// W4 / G2 — Spend atlas fail-closed: process-owned hostname seed, not generic 443.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  providerForIp,
  activityProviderForIp,
  tierFor,
  turnUsd,
  matchSpendAtlasHost,
  evaluateSpendLeg,
  assessAtlasHealth,
  SPEND_ATLAS_VERSION,
  SPEND_ATLAS_HASH,
  SPEND_ATLAS_POSITIVE,
  SPEND_ATLAS_NEGATIVE_NEAR_MISS,
  positiveAtlasHosts,
  collectSpend,
  scoreBurnActivity,
} = require('../src/spend.js');

test('providerForIp maps observed provider prefixes (legacy telemetry only)', () => {
  assert.strictEqual(providerForIp('2607:6bc0::10'), 'anthropic');
  assert.strictEqual(providerForIp('2001:4860:4847:400::'), 'google');
  assert.strictEqual(providerForIp('34.54.84.110'), 'google');
  assert.strictEqual(providerForIp('93.184.216.34'), null);   // random host → not a provider (no false positive)
  assert.strictEqual(providerForIp(''), null);
});

test('tierFor picks the model family', () => {
  assert.strictEqual(tierFor('claude-opus-4-8'), 'opus');
  assert.strictEqual(tierFor('claude-haiku-4-5'), 'haiku');
  assert.strictEqual(tierFor('claude-sonnet-5'), 'sonnet');
  assert.strictEqual(tierFor(''), 'sonnet');   // unknown → conservative default
});

test('turnUsd is cache-aware and non-negative', () => {
  // Opus: 1M output tokens = $75; 1M cache-read = $1.50
  assert.ok(Math.abs(turnUsd('claude-opus-4-8', { output_tokens: 1e6 }) - 75) < 1e-6);
  assert.ok(Math.abs(turnUsd('claude-opus-4-8', { cache_read_input_tokens: 1e6 }) - 1.5) < 1e-6);
  // a real-ish turn is a positive small number
  const u = { input_tokens: 2, output_tokens: 8961, cache_read_input_tokens: 328419, cache_creation_input_tokens: 6250 };
  assert.ok(turnUsd('claude-opus-4-8', u) > 0);
});

test('closed positive atlas seed has ≥1 host per provider class', () => {
  assert.ok(SPEND_ATLAS_VERSION.startsWith('w4-'));
  assert.strictEqual(SPEND_ATLAS_HASH, SPEND_ATLAS_VERSION);
  const providers = new Set(SPEND_ATLAS_POSITIVE.map((r) => r.provider));
  assert.ok(providers.has('anthropic'));
  assert.ok(providers.has('google-ai'));
  assert.ok(providers.has('xai'));
  const hosts = positiveAtlasHosts();
  assert.ok(hosts.includes('api.anthropic.com'));
  assert.ok(hosts.includes('api.claude.ai'));
  assert.ok(hosts.includes('generativelanguage.googleapis.com'));
  assert.ok(hosts.includes('aiplatform.googleapis.com'));
  assert.ok(hosts.includes('api.x.ai'));
  assert.ok(hosts.length >= 5);
});

test('matchSpendAtlasHost exact positives and near-miss negatives', () => {
  assert.strictEqual(matchSpendAtlasHost('api.anthropic.com').matched, true);
  assert.strictEqual(matchSpendAtlasHost('api.anthropic.com').provider, 'anthropic');
  assert.strictEqual(matchSpendAtlasHost('API.CLAUDE.AI').matched, true);
  assert.strictEqual(matchSpendAtlasHost('generativelanguage.googleapis.com').provider, 'google-ai');
  assert.strictEqual(matchSpendAtlasHost('api.x.ai').provider, 'xai');

  for (const h of SPEND_ATLAS_NEGATIVE_NEAR_MISS) {
    const m = matchSpendAtlasHost(h);
    assert.strictEqual(m.matched, false, `near-miss must not match: ${h}`);
  }
  // Adversarial substring / suffix must not match
  assert.strictEqual(matchSpendAtlasHost('api.anthropic.com.evil.example').matched, false);
  assert.strictEqual(matchSpendAtlasHost('evil-api.anthropic.com').matched, false);
  assert.strictEqual(matchSpendAtlasHost('googleapis.com').matched, false);
  assert.strictEqual(matchSpendAtlasHost('www.google.com').matched, false);
});

test('IP burn activity never alone SPEND_POSITIVE (informational dual-signal)', () => {
  // Anthropic IPv6 on engine candidate: burnActivity yes, spendPositive no (no host/SNI)
  const r = evaluateSpendLeg({
    pid: 4242,
    connections: [
      { owningPid: 4242, remoteAddress: '2607:6bc0::10', remotePort: 443, remoteHost: '' },
    ],
    skipDnsCache: true,
  });
  assert.strictEqual(r.spendPositive, false);
  assert.strictEqual(r.status, 'SPEND_NEGATIVE');
  assert.strictEqual(r.burnActivity, true);
  assert.ok(r.activityProviders.includes('anthropic'));
  assert.ok((r.reasonCodes || []).includes('BURN_ACTIVITY_IP'));
});

test('atlas host match still SPEND_POSITIVE for RED leg', () => {
  const r = evaluateSpendLeg({
    pid: 99,
    connections: [
      {
        owningPid: 99,
        remoteAddress: '1.2.3.4',
        remotePort: 443,
        remoteHost: 'api.x.ai',
      },
    ],
    skipDnsCache: true,
  });
  assert.strictEqual(r.spendPositive, true);
  assert.strictEqual(r.status, 'SPEND_POSITIVE');
  assert.strictEqual(r.burnActivity, true);
  assert.ok(r.providers.includes('xai'));
});

test('scoreBurnActivity maps known provider IP prefixes', () => {
  const a = scoreBurnActivity([
    { remoteAddress: '2607:6bc0::1' },
    { remoteAddress: '93.184.216.34' },
  ]);
  assert.strictEqual(a.burnActivity, true);
  assert.ok(a.activityProviders.includes('anthropic'));
  assert.strictEqual(activityProviderForIp('93.184.216.34'), null);
});

test('test_spend_ownership_acquisition_fail_closed — generic 443 / empty / unknown', () => {
  // Port-443 alone (owned socket, no hostname)
  const portOnly = evaluateSpendLeg({
    pid: 100,
    connections: [
      { owningPid: 100, remotePort: 443, remoteAddress: '142.250.1.1' },
    ],
  });
  assert.strictEqual(portOnly.spendPositive, false);
  assert.ok(portOnly.status === 'SPEND_NEGATIVE' || portOnly.status === 'SPEND_UNCERTAIN');
  assert.notStrictEqual(portOnly.status, 'SPEND_POSITIVE');

  // Generic Google CDN IP with no atlas host attribution
  const googleIp = evaluateSpendLeg({
    pid: 101,
    connections: [
      {
        owningPid: 101,
        remotePort: 443,
        remoteAddress: '142.250.1.1',
        remoteHost: 'www.google.com',
      },
    ],
  });
  assert.strictEqual(googleIp.spendPositive, false);
  assert.strictEqual(googleIp.status, 'SPEND_NEGATIVE');

  // Unknown remote host
  const unknown = evaluateSpendLeg({
    pid: 102,
    connections: [
      {
        owningPid: 102,
        remotePort: 443,
        remoteHost: 'cdn.example.net',
      },
    ],
  });
  assert.strictEqual(unknown.spendPositive, false);

  // Empty PID ownership (no connections for this pid)
  const empty = evaluateSpendLeg({
    pid: 999,
    connections: [
      { owningPid: 1, remotePort: 443, remoteHost: 'api.anthropic.com' },
    ],
  });
  assert.strictEqual(empty.spendPositive, false);
  assert.strictEqual(empty.status, 'SPEND_NEGATIVE');

  // Empty connection list
  const none = evaluateSpendLeg({ pid: 1, connections: [] });
  assert.strictEqual(none.spendPositive, false);
});

test('golden spend positives on atlas-matched process-owned hosts', () => {
  for (const host of positiveAtlasHosts()) {
    const r = evaluateSpendLeg({
      pid: 50,
      connections: [
        { owningPid: 50, remotePort: 443, remoteHost: host },
      ],
    });
    assert.strictEqual(r.status, 'SPEND_POSITIVE', host);
    assert.strictEqual(r.spendPositive, true, host);
    assert.strictEqual(r.spendingNow, true, host);
    assert.ok(r.providers.length >= 1, host);
    assert.ok(r.reasonCodes.includes('SPEND_POSITIVE'), host);
  }
});

test('test_spend_atlas_stale_no_invent', () => {
  const stale = evaluateSpendLeg({
    pid: 50,
    forceStale: true,
    connections: [
      { owningPid: 50, remotePort: 443, remoteHost: 'api.anthropic.com' },
    ],
  });
  assert.strictEqual(stale.spendPositive, false);
  assert.strictEqual(stale.atlasStale, true);
  assert.ok(
    stale.reasonCodes.includes('SPEND_ATLAS_STALE')
      || stale.reason === 'SPEND_ATLAS_STALE',
  );
  assert.notStrictEqual(stale.status, 'SPEND_POSITIVE');

  const emptyAtlas = evaluateSpendLeg({
    pid: 50,
    atlasEntries: [],
    connections: [
      { owningPid: 50, remotePort: 443, remoteHost: 'api.anthropic.com' },
    ],
  });
  assert.strictEqual(emptyAtlas.spendPositive, false);
  assert.strictEqual(emptyAtlas.atlasStale, true);

  const unreadable = evaluateSpendLeg({
    pid: 50,
    attributionUnreadable: true,
    connections: [
      { owningPid: 50, remotePort: 443, remoteHost: 'api.anthropic.com' },
    ],
  });
  assert.strictEqual(unreadable.spendPositive, false);
  assert.ok(unreadable.status === 'SPEND_UNCERTAIN' || unreadable.atlasStale);

  const health = assessAtlasHealth({ forceStale: true });
  assert.strictEqual(health.stale, true);
});

test('collectSpend exposes atlas health fields', () => {
  const snap = collectSpend(10, Date.now(), {
    connections: [
      { owningPid: 7, remotePort: 443, remoteHost: 'api.x.ai' },
    ],
  });
  assert.ok(snap.atlas);
  assert.strictEqual(snap.atlas.version, SPEND_ATLAS_VERSION);
  assert.strictEqual(snap.atlas.hash, SPEND_ATLAS_HASH);
  assert.strictEqual(snap.atlas.stale, false);
  assert.ok(snap.net[7]);
  assert.ok(snap.net[7].providers.includes('xai'));
});

// ── multi-engine Burn Ledger (2026-07-23) ─────────────────────────────────
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  grokLedger,
  geminiLedger,
  openaiLedger,
  mergeLedgerSessions,
  claudeLedger,
  estimateGrokSessionCost,
  grokPriceTier,
  GROK_PRICES,
} = require('../src/spend.js');

test('mergeLedgerSessions keeps measured $ separate from activity', () => {
  const { sessions, totals } = mergeLedgerSessions([
    [{
      sessionId: 'c1', engine: 'claude', evidenceClass: 'measured',
      usdPerMin: 1.5, usdRecent: 15, tokensRecent: 1000, lastActivityAgoMin: 1,
    }],
    [{
      sessionId: 'g1', engine: 'grok', evidenceClass: 'activity',
      usdPerMin: 0, usdRecent: 0, tokensRecent: 50000, lastActivityAgoMin: 0,
    }],
  ]);
  assert.strictEqual(sessions.length, 2);
  assert.strictEqual(totals.activeSessions, 2);
  assert.strictEqual(totals.measuredSessions, 1);
  assert.strictEqual(totals.activitySessions, 1);
  assert.strictEqual(totals.usdPerMin, 1.5);
  assert.strictEqual(totals.measuredUsdPerMin, 1.5);
  assert.strictEqual(totals.byEngine.claude, 1);
  assert.strictEqual(totals.byEngine.grok, 1);
  // activity-only must NOT inflate measured $
  assert.ok(totals.usdPerMin < 2);
});

test('grok-4.5 list prices match docs.x.ai flagship rates', () => {
  const p = grokPriceTier('grok-4.5');
  assert.strictEqual(p.in, 2.0);
  assert.strictEqual(p.out, 6.0);
  assert.strictEqual(p.longIn, 4.0);
  assert.strictEqual(p.longOut, 12.0);
  assert.ok(GROK_PRICES['grok-4.5']);
});

test('estimateGrokSessionCost produces estimated $/min from signals', () => {
  const est = estimateGrokSessionCost({
    contextTokensUsed: 100_000,
    turnCount: 10,
    totalChunkCount: 5000,
    sessionDurationSeconds: 600, // 10 min
    assistantMessageCount: 10,
  }, {}, 'grok-4.5', 10);
  assert.strictEqual(est.evidenceClass, 'estimated');
  assert.ok(est.usdPerMin > 0, 'expected positive est $/min');
  assert.ok(est.usdSession > 0);
  assert.ok(est.inputEst > 0);
  assert.ok(est.outputEst > 0);
  // Long-context tier when ctx ≥ 200k
  const long = estimateGrokSessionCost({
    contextTokensUsed: 250_000,
    turnCount: 4,
    totalChunkCount: 2000,
    sessionDurationSeconds: 300,
  }, {}, 'grok-4.5', 10);
  assert.ok(long.usdSession > 0);
});

test('mergeLedgerSessions exposes estimated totals without polluting measured', () => {
  const { totals } = mergeLedgerSessions([
    [{
      sessionId: 'c1', engine: 'claude', evidenceClass: 'measured',
      usdPerMin: 1.0, usdRecent: 10, tokensRecent: 100,
    }],
    [{
      sessionId: 'g1', engine: 'grok', evidenceClass: 'estimated',
      usdPerMin: 2.5, usdRecent: 25, tokensRecent: 50000,
    }],
  ]);
  assert.strictEqual(totals.usdPerMin, 1.0);
  assert.strictEqual(totals.usdPerMinEstimated, 2.5);
  assert.strictEqual(totals.usdPerMinAll, 3.5);
  assert.strictEqual(totals.estimatedSessions, 1);
});

test('grokLedger reads active_sessions + summary/signals', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'zh-grok-'));
  const sid = '019f-test-session';
  // Production layout: sessions/<encoded-cwd>/<session-id>/
  const sessDir = path.join(tmp, 'sessions', 'C%3A%5Cdev', sid);
  fs.mkdirSync(sessDir, { recursive: true });
  fs.writeFileSync(path.join(tmp, 'active_sessions.json'), JSON.stringify([
    { session_id: sid, pid: 4242, cwd: '<path>', opened_at: new Date().toISOString() },
  ]));
  fs.writeFileSync(path.join(sessDir, 'summary.json'), JSON.stringify({
    info: { id: sid, cwd: '<path>' },
    current_model_id: 'grok-4.5',
    last_active_at: new Date().toISOString(),
    num_chat_messages: 3,
  }));
  fs.writeFileSync(path.join(sessDir, 'signals.json'), JSON.stringify({
    contextTokensUsed: 120000,
    primaryModelId: 'grok-4.5',
    turnCount: 5,
    totalChunkCount: 3000,
    sessionDurationSeconds: 600,
    assistantMessageCount: 8,
  }));
  const rows = grokLedger(10, Date.now(), { grokHome: tmp });
  assert.ok(rows.length >= 1, 'expected ≥1 grok session');
  const r = rows.find((x) => x.sessionId === sid) || rows[0];
  assert.strictEqual(r.engine, 'grok');
  // With real signals (ctx + turns) we now ESTIMATE $, never leave silent $0
  assert.ok(r.evidenceClass === 'estimated' || r.evidenceClass === 'activity');
  if (r.evidenceClass === 'estimated') {
    assert.ok(r.usdPerMin > 0, 'estimated row should have positive $/min');
  }
  assert.ok(r.tokensRecent > 0 || r.contextTokens > 0);
  assert.ok(String(r.model).includes('grok'));
  // cleanup
  fs.rmSync(tmp, { recursive: true, force: true });
});

test('openaiLedger stub is empty without trail (not measured $0 theater)', () => {
  const rows = openaiLedger(10, Date.now(), {});
  assert.deepStrictEqual(rows, []);
  const injected = openaiLedger(10, Date.now(), {
    openaiSessions: [{ sessionId: 'o1', cwd: '/x', model: 'gpt-4.1', tokensRecent: 9 }],
  });
  assert.strictEqual(injected.length, 1);
  assert.strictEqual(injected[0].engine, 'openai');
});

test('collectSpend multi-engine: Grok estimate does not invent measured $', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'zh-multi-'));
  const sid = 'sess-multi';
  const sessDir = path.join(tmp, 'sessions', 'C%3A%5Cdev', sid);
  fs.mkdirSync(sessDir, { recursive: true });
  fs.writeFileSync(path.join(tmp, 'active_sessions.json'), JSON.stringify([
    { session_id: sid, pid: 1, cwd: '<path>', opened_at: new Date().toISOString() },
  ]));
  fs.writeFileSync(path.join(sessDir, 'summary.json'), JSON.stringify({
    info: { id: sid, cwd: '<path>' },
    current_model_id: 'grok-4.5',
    last_active_at: new Date().toISOString(),
  }));
  fs.writeFileSync(path.join(sessDir, 'signals.json'), JSON.stringify({
    contextTokensUsed: 80_000,
    turnCount: 6,
    totalChunkCount: 4000,
    sessionDurationSeconds: 900,
    primaryModelId: 'grok-4.5',
  }));
  // Empty claude root so no measured rows
  const claudeRoot = path.join(tmp, 'claude-projects');
  fs.mkdirSync(claudeRoot, { recursive: true });
  const snap = collectSpend(10, Date.now(), {
    grokHome: tmp,
    claudeRoot,
    geminiHome: path.join(tmp, 'no-gemini'),
    connections: [],
  });
  assert.ok(snap.totals.activeSessions >= 1);
  // Measured channel stays 0; estimated channel is positive
  assert.strictEqual(snap.totals.usdPerMin, 0);
  assert.ok(snap.totals.usdPerMinEstimated > 0, 'expected Grok estimate');
  assert.ok(snap.totals.usdPerMinAll > 0);
  assert.ok((snap.sessions || []).some((s) => s.engine === 'grok' && s.evidenceClass === 'estimated'));
  fs.rmSync(tmp, { recursive: true, force: true });
});
