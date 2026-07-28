// test/engine-skeleton.test.mjs — Wave 5 gate: the ENGINE SKELETON (reuse, not fork).
//
// IMPLEMENTATION-PLAN Wave 5 done-when, asserted as concrete `node --test` checks:
//   - the orchestrator (real bin/ source) IMPORTS the frozen trio surface AND the shared
//     independence-accounting module (Wave 2) for GATE-1; OWNS the ledger + ladder; runs the loop via
//     the scripted driver;
//   - "the no-op loop runs ⇒ the contract test asserts it traverses every gate-slot in real call-order";
//   - "a checkpoint mid-loop ⇒ a spy counter throws if any completed step re-runs (real resume)".

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  GATE_SLOTS,
  GATE_ONE_ID,
  ENGINE_SCHEMA_VERSION,
  TRIO_SURFACE,
  makeLedger,
  makeLadder,
  makeEngineDriver,
  gateOneQuorum,
  runEngine,
} from '../bin/engine.mjs';
import { STATIC_QUORUM_FLOOR } from '../bin/trio-core/independence-accounting.mjs';

// Read the durable checkpoint through the SAME (reused, pinned) primitive the engine writes with —
// not a hardcoded `../../foreman` reach (which would ignore the RP_TRIO_ROOT pin).
const { readCheckpoint } = TRIO_SURFACE['foreman-lib'];

function tmpFile(name) {
  return path.join(os.tmpdir(), `rp-engine-${process.pid}-${name}.json`);
}

const SLOT_IDS = GATE_SLOTS.map((s) => s.id);

// ── done-when: imports the frozen trio surface + the shared module for GATE-1 ─────────────────────────

test('the engine IMPORTS the frozen trio surface (all five trio modules, foreman-lib primitives present)', () => {
  // Loading bin/engine.mjs imported the whole crossed surface — exactly the Wave-5 requirement.
  for (const key of ['shark-tank', 'synthesizer', 'judge', 'enhanced', 'foreman-lib']) {
    assert.ok(TRIO_SURFACE[key], `engine did not import trio module: ${key}`);
  }
  // Durability is REUSED from the surface, not forked.
  const fl = TRIO_SURFACE['foreman-lib'];
  for (const sym of ['newCheckpoint', 'writeCheckpointAtomic', 'readCheckpoint', 'validateCheckpoint', 'HaltError']) {
    assert.ok(fl[sym], `foreman-lib primitive missing from the imported surface: ${sym}`);
  }
});

test('GATE-1 routes through the shared independence-accounting module (the sole origin counter)', () => {
  // No reviewers ⇒ 0 origins, static ≥2 floor unmet — a real call into the Wave-2 module.
  const empty = gateOneQuorum({ reviewers: [] });
  assert.deepEqual(empty, { origins: 0, required: STATIC_QUORUM_FLOOR, met: false });
  // Two reviewers of the SAME declared lineage add only ONE origin (I3) — proves it is the shared
  // module's count, not a re-implemented one. Two distinct lineages meet the floor.
  assert.equal(gateOneQuorum({ reviewers: [{ lineage: 'A' }, { lineage: 'A' }] }).origins, 1);
  const distinct = gateOneQuorum({ reviewers: [{ lineage: 'A' }, { lineage: 'B' }] });
  assert.equal(distinct.origins, 2);
  assert.equal(distinct.met, true);
});

// ── "the no-op loop traverses every gate-slot in real call-order" ────────────────────────────────────

test('the no-op loop traverses EVERY gate-slot in real call-order (the driver call sequence == GATE_SLOTS)', async () => {
  // The scripted agent witnesses the real call-order: it records each slot id the driver invokes it for.
  const callOrder = [];
  const recordingAgent = async (_prompt, opts) => { callOrder.push(opts.slot.id); return null; };

  const res = await runEngine({ agent: recordingAgent, item: {}, maxRounds: 1 });

  // Real call-order (the agent invocation sequence) is exactly the canonical slot order — every slot, once.
  assert.deepEqual(callOrder, SLOT_IDS, 'driver did not invoke the gate-slots in canonical call-order');
  // The owned run ledger records the same traversal, round-qualified.
  assert.deepEqual(res.steps, SLOT_IDS.map((id) => `1:${id}`));
  assert.equal(res.status, 'done');
  // The GATE-1 ledger entry carries the shared module's quorum verdict (origins counted in-loop).
  const g1 = res.ledger.find((e) => e.slot === GATE_ONE_ID);
  assert.ok(g1, 'GATE-1 slot was not traversed');
  assert.deepEqual(g1.quorum, { origins: 0, required: STATIC_QUORUM_FLOOR, met: false });
});

test('the scripted driver requires an agent() seam (reuse of the trio injection contract)', () => {
  assert.throws(() => makeEngineDriver({}), /requires an agent/);
  assert.throws(() => makeEngineDriver({ agent: 'nope' }), /requires an agent/);
});

// ── "a checkpoint mid-loop ⇒ a spy counter throws if any completed step re-runs (real resume)" ───────

test('real resume: a mid-loop checkpoint resumes WITHOUT re-running any completed step (spy throws if it does)', async () => {
  const statePath = tmpFile('resume');
  const CRASH = 4; // crash after slots 0..3 complete (mid the 10-slot loop)
  try {
    // Run 1 — crash mid-loop: the agent throws when asked for the (CRASH+1)th gate, leaving exactly
    // CRASH completed steps persisted (each checkpointed right after it completed).
    let n = 0;
    const crashingAgent = async () => {
      if (n === CRASH) throw new Error('simulated mid-loop crash');
      n += 1;
      return null;
    };
    await assert.rejects(
      () => runEngine({ agent: crashingAgent, item: {}, statePath, maxRounds: 1 }),
      /simulated mid-loop crash/,
    );

    // The durable checkpoint names exactly the CRASH steps that truly completed — and nothing past them.
    const cp = readCheckpoint(statePath);
    assert.equal(cp.rp_engine.schema_version, ENGINE_SCHEMA_VERSION);
    const persistedSteps = cp.rp_engine.ledger.map((e) => `${e.round}:${e.slot}`);
    assert.deepEqual(persistedSteps, SLOT_IDS.slice(0, CRASH).map((id) => `1:${id}`));

    // Run 2 — resume with a SPY that THROWS if asked to run any already-completed step. Real resume must
    // skip them, so the spy is never tripped and the loop finishes the remaining slots.
    const completed = new Set(persistedSteps);
    const ranOnResume = [];
    const spyAgent = async (_prompt, opts) => {
      const key = `${opts.round}:${opts.slot.id}`;
      if (completed.has(key)) throw new Error(`re-ran a completed step on resume: ${key}`);
      ranOnResume.push(opts.slot.id);
      return null;
    };

    const res = await runEngine({ agent: spyAgent, statePath, resume: true });

    // The resume ran ONLY the remaining slots, in order — no completed step re-executed.
    assert.deepEqual(ranOnResume, SLOT_IDS.slice(CRASH));
    // The full run (run 1 + resume) covered every slot exactly once, in canonical order.
    assert.deepEqual(res.steps, SLOT_IDS.map((id) => `1:${id}`));
    assert.equal(res.status, 'done');
    const finalCp = readCheckpoint(statePath);
    assert.equal(finalCp.status, 'done');
  } finally {
    fs.rmSync(statePath, { force: true });
    fs.rmSync(`${statePath}.tmp`, { force: true });
  }
});

test('resume refuses without a statePath (no silent fresh start)', async () => {
  await assert.rejects(() => runEngine({ agent: async () => null, resume: true }), /resume requires a statePath/);
});

// ── the engine OWNS a working ledger + ladder ─────────────────────────────────────────────────────────

test('the owned run LEDGER is append-only and refuses to record a completed step twice', () => {
  const ledger = makeLedger();
  ledger.append({ round: 1, slot: 'a', gate: 'A' });
  ledger.append({ round: 1, slot: 'b', gate: 'B' });
  assert.equal(ledger.hasStep(1, 'a'), true);
  assert.equal(ledger.hasStep(1, 'c'), false);
  assert.deepEqual(ledger.steps(), ['1:a', '1:b']);
  // Re-appending a completed step is a contract breach — caught at the data layer.
  assert.throws(() => ledger.append({ round: 1, slot: 'a', gate: 'A' }), /must never re-run/);
  // Restoring from a snapshot preserves the seen-set (resume fidelity).
  const restored = makeLedger(ledger.snapshot());
  assert.equal(restored.hasStep(1, 'b'), true);
  assert.throws(() => restored.append({ round: 1, slot: 'b', gate: 'B' }), /must never re-run/);
});

test('the owned evidence LADDER raises ONLY on a fresh fetched pointer (I4 G7 downgrade-only)', () => {
  const ladder = makeLadder();
  assert.equal(ladder.level(), 0);
  // No level-up without a new pointer.
  assert.throws(() => ladder.raise(''), /fresh fetched pointer/);
  assert.throws(() => ladder.raise(), /fresh fetched pointer/);
  assert.equal(ladder.level(), 0);
  // A fresh pointer raises; a re-used pointer cannot (re-used evidence is not new evidence).
  assert.equal(ladder.raise('doc#1'), 1);
  assert.throws(() => ladder.raise('doc#1'), /already used/);
  assert.equal(ladder.raise('doc#2'), 2);
  // Downgrade needs no new pointer and never goes below 0.
  assert.equal(ladder.lower(1), 1);
  assert.equal(ladder.lower(5), 0);
  // Restore round-trips level + pointers (and keeps the no-reuse guard).
  const restored = makeLadder(makeLadder({ level: 1, pointers: ['p'] }).snapshot());
  assert.equal(restored.level(), 1);
  assert.throws(() => restored.raise('p'), /already used/);
});
