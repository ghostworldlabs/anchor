// Multi-engine ledger + GUI auto-refresh contract (source-level).
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const serverSrc = fs.readFileSync(path.join(__dirname, '..', 'src', 'server.js'), 'utf8');
const spendSrc = fs.readFileSync(path.join(__dirname, '..', 'src', 'spend.js'), 'utf8');

test('server defines UI_REFRESH_MS default 90s and client auto-refresh loop', () => {
  assert.ok(serverSrc.includes('UI_REFRESH_MS'), 'UI_REFRESH_MS constant');
  assert.ok(serverSrc.includes('90000') || serverSrc.includes('90_000'), 'default 90s');
  assert.ok(serverSrc.includes('document.hidden') || serverSrc.includes('visibilitychange'),
    'visibility-aware');
  assert.ok(serverSrc.includes('setInterval(tick,UI_REFRESH_MS)')
    || serverSrc.includes('setInterval(tick, UI_REFRESH_MS)'),
    'client cadence');
  assert.ok(serverSrc.includes('sweepInProgress'), 'waits on sweep');
});

test('server copy is multi-engine not Claude-only ledger', () => {
  assert.ok(serverSrc.includes('multi-engine'), 'multi-engine label');
  assert.ok(!/Burn ledger — Claude session JSONL/.test(serverSrc),
    'old Claude-only section header must be gone');
  assert.ok(!/\$ ledger = Claude JSONL only/.test(serverSrc),
    'old Claude-only footer must be gone');
  assert.ok(serverSrc.includes('Measured $/min') || serverSrc.includes('measured'),
    'measured $ label');
});

test('spend.js exports multi-engine ledger helpers', () => {
  assert.ok(spendSrc.includes('function grokLedger'));
  assert.ok(spendSrc.includes('function geminiLedger'));
  assert.ok(spendSrc.includes('function openaiLedger'));
  assert.ok(spendSrc.includes('function mergeLedgerSessions'));
  assert.ok(spendSrc.includes("engine: 'claude'"));
  assert.ok(spendSrc.includes("evidenceClass: 'measured'"));
  assert.ok(spendSrc.includes("evidenceClass: 'activity'"));
});
