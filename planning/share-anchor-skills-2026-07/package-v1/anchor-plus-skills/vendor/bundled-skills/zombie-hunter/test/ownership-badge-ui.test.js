// W10 / P7 — Ownership badge UI contract on radar; Freeze/Kill hidden when owned.
// Named gate: test_ownership_badge_ui_contract

const { test } = require('node:test');
const assert = require('node:assert');

const {
  resolveOwnershipBadge,
  isOwnedKeep,
  shouldShowFreezeKill,
  ownershipBadgeUiContract,
  assertOwnershipBadgeUiContract,
  renderOwnershipBadgeChipHtml,
  renderTileActsHtml,
  attachOwnershipToGroup,
} = require('../src/ownership-ui.js');

const { buildOwnershipBadge } = require('../src/ownership.js');
const { tile } = require('../src/server.js');

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

test('test_ownership_badge_ui_contract', () => {
  const ownedBadge = buildOwnershipBadge({
    owned: true,
    keep: true,
    failClosed: false,
    reason: 'OWNERSHIP_REGISTERED_KEEP',
    reasonCodes: ['OWNERSHIP_IPC_STUB', 'OWNERSHIP_REGISTERED_KEEP'],
  });
  const ownedTile = {
    id: 'owned-claude',
    name: 'claude.exe',
    kind: 'zombie',
    pids: ['4242'],
    ownershipBadge: ownedBadge,
  };

  // Freeze/Kill hidden when owned even if freezeKillEnabled
  assert.strictEqual(
    shouldShowFreezeKill(ownedTile, { freezeKillEnabled: true, kind: 'zombie' }),
    false,
  );
  const ownedContract = ownershipBadgeUiContract(ownedTile, {
    freezeKillEnabled: true,
    kind: 'zombie',
  });
  assert.strictEqual(ownedContract.ok, true);
  assert.strictEqual(ownedContract.ownedKeep, true);
  assert.strictEqual(ownedContract.freezeKillVisible, false);
  assert.strictEqual(ownedContract.freezeKillHiddenWhenOwned, true);
  assert.strictEqual(ownedContract.ownershipBadgeVisible, true);
  assert.match(ownedContract.label, /Anchor-owned/i);

  // Unowned zombie may show Freeze/Kill when enabled
  const freeBadge = buildOwnershipBadge({
    owned: false,
    keep: false,
    failClosed: false,
    reason: 'OWNERSHIP_NOT_REGISTERED',
    reasonCodes: ['OWNERSHIP_IPC_STUB', 'OWNERSHIP_NOT_REGISTERED'],
  });
  const freeTile = {
    id: 'orphan-claude',
    name: 'claude.exe',
    kind: 'zombie',
    pids: ['7777'],
    ownershipBadge: freeBadge,
  };
  assert.strictEqual(
    shouldShowFreezeKill(freeTile, { freezeKillEnabled: true, kind: 'zombie' }),
    true,
  );
  const freeContract = ownershipBadgeUiContract(freeTile, {
    freezeKillEnabled: true,
    kind: 'zombie',
  });
  assert.strictEqual(freeContract.freezeKillVisible, true);
  assert.strictEqual(freeContract.ownedKeep, false);

  // Fail-closed ownership also hides Freeze/Kill
  const fcBadge = buildOwnershipBadge({
    owned: true,
    keep: true,
    failClosed: true,
    reason: 'OWNERSHIP_IPC_FAIL_CLOSED',
    reasonCodes: ['OWNERSHIP_IPC_STUB', 'OWNERSHIP_IPC_FAIL_CLOSED'],
  });
  assert.strictEqual(isOwnedKeep(fcBadge), true);
  assert.strictEqual(
    shouldShowFreezeKill(
      { ownershipBadge: fcBadge },
      { freezeKillEnabled: true, kind: 'zombie' },
    ),
    false,
  );

  // Batch assert
  const batch = assertOwnershipBadgeUiContract(
    [ownedTile, freeTile, { id: 'fc', ownershipBadge: fcBadge, kind: 'zombie' }],
    { freezeKillEnabled: true, kind: 'zombie' },
  );
  assert.strictEqual(batch.ok, true, batch.failures.join(','));

  // HTML acts: owned must not contain Freeze/Kill buttons
  const ownedActs = renderTileActsHtml(ownedTile, {
    freezeKillEnabled: true,
    kind: 'zombie',
  }, esc);
  assert.ok(!/doFreeze|doKill|Freeze \(reversible\)|Kill — stop/i.test(ownedActs));
  assert.ok(/ownership KEEP|Freeze\/Kill hidden/i.test(ownedActs));

  const freeActs = renderTileActsHtml(freeTile, {
    freezeKillEnabled: true,
    kind: 'zombie',
  }, esc);
  assert.ok(/doFreeze/i.test(freeActs));
  assert.ok(/doKill/i.test(freeActs));

  // Badge chip HTML
  const chip = renderOwnershipBadgeChipHtml(ownedBadge, esc);
  assert.ok(/ownership-badge/i.test(chip));
  assert.ok(/data-owned="1"/.test(chip));

  // Group attach prefers KEEP
  const group = { id: 'g1', name: 'claude.exe' };
  attachOwnershipToGroup(group, [
    { ownershipBadge: freeBadge },
    { ownershipBadge: ownedBadge },
  ]);
  assert.strictEqual(group.ownershipBadge.owned, true);
  assert.strictEqual(group.ownership.keep, true);
});

test('server tile HTML hides Freeze/Kill when owned', () => {
  const ownedBadge = buildOwnershipBadge({
    owned: true,
    keep: true,
    failClosed: false,
    reason: 'OWNERSHIP_REGISTERED_KEEP',
    reasonCodes: ['OWNERSHIP_REGISTERED_KEEP'],
  });
  const html = tile({
    id: 't-owned',
    name: 'claude.exe',
    path: 'C:\\x\\claude.exe',
    providers: ['anthropic'],
    root: 'services.exe',
    parentAlive: true,
    parentName: 'services.exe',
    supervised: false,
    sessionId: 1,
    pids: ['99'],
    count: 1,
    minAge: 1,
    maxAge: 1,
    conns: 1,
    spendAgoMin: 0,
    sample: 'claude.exe -p',
    ownershipBadge: ownedBadge,
    ownership: { owned: true, keep: true, failClosed: false, label: 'Anchor-owned' },
  }, 'zombie', { freezeKillEnabled: true });

  assert.ok(/data-owned-keep="1"/.test(html));
  assert.ok(/data-freeze-kill-visible="0"/.test(html));
  assert.ok(!/doFreeze/i.test(html));
  assert.ok(!/doKill/i.test(html));
  assert.ok(/ownership-badge|Anchor-owned/i.test(html));
});

test('resolveOwnershipBadge falls back to ownership object', () => {
  const b = resolveOwnershipBadge({
    ownership: { owned: false, keep: false, failClosed: false, label: 'not owned' },
  });
  assert.ok(b);
  assert.strictEqual(b.owned, false);
});
