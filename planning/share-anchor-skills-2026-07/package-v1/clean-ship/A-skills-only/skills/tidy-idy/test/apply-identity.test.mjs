// test/apply-identity.test.mjs — Wave 3: the finding identity contract.
//
// Frozen deliverable: "Finding identity contract: ID = hash(run_id, action,
// path, content_hash), round-tripped in full; Apply refuses unmatched IDs —
// approval by index or bare path impossible."
//
// "Impossible" is the word under test. It is not enough that the happy path
// works; each of the alternative approval forms a careless (or hostile) caller
// might reach for has to be REFUSED, by name.

import { test, describe } from 'node:test';
import assert from 'node:assert';

import {
  computeFindingId,
  stampFindingIds,
  buildFindingIndex,
  resolveApprovals,
  IDENTITY_REFUSAL,
  FINDING_ID_PREFIX,
} from '../engine/apply/identity.mjs';

const RUN = 'run-2026-07-21T00-00-00-000Z-abcd1234';

function findings() {
  return [
    { stage: 'debate', action: 'remove', path: 'scratch/a.txt', contentHash: 'sha256:aaa' },
    { stage: 'save', action: 'save', path: 'scratch/b.txt', contentHash: 'sha256:bbb' },
    { stage: 'triage', action: 'blocked', path: 'scratch/secret.env', contentHash: 'sha256:ccc', approvable: false },
  ];
}

describe('the ID is a function of exactly (run, action, path, content hash)', () => {
  test('the same four components always give the same ID', () => {
    const a = computeFindingId({ runId: RUN, action: 'remove', path: 'x/y.txt', contentHash: 'sha256:1' });
    const b = computeFindingId({ runId: RUN, action: 'remove', path: 'x/y.txt', contentHash: 'sha256:1' });
    assert.strictEqual(a, b);
    assert.ok(a.startsWith(`${FINDING_ID_PREFIX}:`), 'IDs carry a version tag so a format change is visible');
  });

  test('changing ANY component changes the ID', () => {
    const base = { runId: RUN, action: 'remove', path: 'x/y.txt', contentHash: 'sha256:1' };
    const id = computeFindingId(base);
    assert.notStrictEqual(id, computeFindingId({ ...base, runId: `${RUN}-2` }), 'a re-scan must invalidate every prior approval');
    assert.notStrictEqual(id, computeFindingId({ ...base, action: 'save' }), 'remove and save on one path are different consents');
    assert.notStrictEqual(id, computeFindingId({ ...base, path: 'x/z.txt' }));
    assert.notStrictEqual(id, computeFindingId({ ...base, contentHash: 'sha256:2' }), 'editing the file must invalidate its approval');
  });

  test('components are length-prefixed, so no two findings can share an ID by concatenation', () => {
    // Without length prefixing, ('ab','c') and ('a','bc') hash identically.
    const a = computeFindingId({ runId: RUN, action: 'remove', path: 'ab', contentHash: 'c' });
    const b = computeFindingId({ runId: RUN, action: 'remove', path: 'a', contentHash: 'bc' });
    assert.notStrictEqual(a, b);
  });

  test('a missing run id is an error, never a silently unscoped ID', () => {
    assert.throws(() => computeFindingId({ action: 'remove', path: 'a', contentHash: null }), /run id/);
  });

  test('stamping is idempotent and re-derives from the finding\'s current values', () => {
    const fs = findings();
    assert.strictEqual(stampFindingIds(fs, RUN), 3);
    const first = fs[0].id;
    stampFindingIds(fs, RUN);
    assert.strictEqual(fs[0].id, first);

    fs[0].contentHash = 'sha256:changed';
    stampFindingIds(fs, RUN);
    assert.notStrictEqual(fs[0].id, first, 'a finding whose hash changed must not keep an ID that no longer describes it');
    assert.deepStrictEqual(fs[0].identity, { runId: RUN, action: 'remove', path: 'scratch/a.txt', contentHash: 'sha256:changed' });
  });
});

describe('Apply refuses every approval form that is not a full, matched identity', () => {
  const setup = () => {
    const list = findings();
    stampFindingIds(list, RUN);
    return list;
  };

  test('approval by INDEX is not expressible — a number is malformed', () => {
    const list = setup();
    const { approved, refusals } = resolveApprovals({ runId: RUN, findings: list, approvals: [0, 1] });
    assert.strictEqual(approved.length, 0);
    assert.deepStrictEqual(refusals.map((r) => r.code), [IDENTITY_REFUSAL.MALFORMED, IDENTITY_REFUSAL.MALFORMED]);
  });

  test('approval by BARE PATH is not expressible', () => {
    const list = setup();
    const { approved, refusals } = resolveApprovals({ runId: RUN, findings: list, approvals: [{ path: 'scratch/a.txt', action: 'remove' }] });
    assert.strictEqual(approved.length, 0);
    assert.strictEqual(refusals[0].code, IDENTITY_REFUSAL.MALFORMED);
  });

  test('a bare ID string does not round-trip the identity IN FULL and is refused', () => {
    const list = setup();
    const { approved, refusals } = resolveApprovals({ runId: RUN, findings: list, approvals: [list[0].id] });
    assert.strictEqual(approved.length, 0);
    assert.strictEqual(refusals[0].code, IDENTITY_REFUSAL.INCOMPLETE);
  });

  test('an ID from a DIFFERENT run is unknown here', () => {
    const list = setup();
    const stale = computeFindingId({ runId: 'run-yesterday', action: 'remove', path: 'scratch/a.txt', contentHash: 'sha256:aaa' });
    const { refusals } = resolveApprovals({
      runId: RUN, findings: list,
      approvals: [{ id: stale, action: 'remove', path: 'scratch/a.txt', contentHash: 'sha256:aaa' }],
    });
    assert.strictEqual(refusals[0].code, IDENTITY_REFUSAL.UNKNOWN_ID);
  });

  test('a real ID with tampered components is refused as a mismatch', () => {
    const list = setup();
    const { refusals } = resolveApprovals({
      runId: RUN, findings: list,
      approvals: [{ id: list[0].id, action: 'remove', path: 'scratch/SOMETHING-ELSE.txt', contentHash: 'sha256:aaa' }],
    });
    assert.strictEqual(refusals[0].code, IDENTITY_REFUSAL.MISMATCH);
  });

  test('a non-approvable finding (the secret-BLOCKED class) has no ID route into Apply either', () => {
    const list = setup();
    const blocked = list[2];
    const { approved, refusals } = resolveApprovals({
      runId: RUN, findings: list,
      approvals: [{ id: blocked.id, action: blocked.action, path: blocked.path, contentHash: blocked.contentHash }],
    });
    assert.strictEqual(approved.length, 0);
    assert.strictEqual(refusals[0].code, IDENTITY_REFUSAL.NOT_APPROVABLE);
  });

  test('the same finding approved twice is refused rather than applied twice', () => {
    const list = setup();
    const one = { id: list[0].id, action: 'remove', path: 'scratch/a.txt', contentHash: 'sha256:aaa' };
    const { approved, refusals } = resolveApprovals({ runId: RUN, findings: list, approvals: [one, { ...one }] });
    assert.strictEqual(approved.length, 1);
    assert.strictEqual(refusals[0].code, IDENTITY_REFUSAL.DUPLICATE);
  });

  test('a fully round-tripped identity resolves to the finding itself', () => {
    const list = setup();
    const { approved, refusals } = resolveApprovals({
      runId: RUN, findings: list,
      approvals: [{ id: list[0].id, action: 'remove', path: 'scratch/a.txt', contentHash: 'sha256:aaa' }],
    });
    assert.deepStrictEqual(refusals, []);
    assert.strictEqual(approved[0], list[0], 'the resolved object is the finding, not a copy — Apply operates on what the run emitted');
  });

  test('identical findings collapse rather than double-apply', () => {
    const list = setup();
    const twin = { ...list[0] };
    stampFindingIds([twin], RUN);
    const { byId, collisions } = buildFindingIndex([...list, twin]);
    assert.strictEqual(collisions.length, 1);
    assert.strictEqual(byId.get(twin.id), list[0]);
  });
});
