// Wave 26 — Journal integration (E2).
//
// Exercises the REAL Wave-26 seam (src/journal-integration.mjs) over the REAL inherited journal +
// sleep seams (resolved through inherits.manifest.json), the REAL inherited durability substrate,
// and the REAL Wave-24/25 oracle corpus + battery. It proves the done-when:
//
//   "a run appends a 7-field journal entry and the sleep-loop consumes it (tested)"
//
// and the defining Given/When/Then:
//
//   given a completed run, when journal integration executes, then a well-formed 7-field entry is
//   appended and the sleep-loop reads it.
//
// It also proves the integration is LOAD-BEARING (NS8 compose, R5 corroboration, P9 reuse-no-new-store):
//   • the schema/validator/sleep loop are the INHERITED seams, not local reimplementations;
//   • the journal is DURABLE + append-only across a simulated restart (fresh-store reload from disk);
//   • the ABLATION run's fixture-FAILURES distill into per-class lessons; a healthy BATTERY-ON run
//     produces no failures, so the sleep loop learns nothing (the oracle is sound);
//   • a malformed entry is REFUSED; only genuine-execution provenance corroborates.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  RAMANUJAN_SKILL,
  GENUINE,
  OUTCOME,
  SITUATION_PREFIX,
  resolveJournalSeam,
  resolveSleepSeam,
  resolveModuleSeam,
  fixtureRunIsCorrect,
  runToJournalEntries,
  fixtureFailureInput,
  JournalStore,
  openJournal,
  integrateRun,
} from '../src/journal-integration.mjs';

import { loadDurabilitySubstrate } from '../src/adjudication.mjs';
import { SCORER } from '../src/oracle-scorer.mjs';
import { loadCorpus, SUBSET, DEFECT_CLASSES } from '../src/oracle-corpus.mjs';

// A unique scratch journal file per test (no clock/RNG in the module; the test owns the path).
let seq = 0;
function scratchFile(tag) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-journal-'));
  return path.join(dir, `journal-${tag}-${seq++}.json`);
}

// =====================================================================================
// 0. The inherited seams resolve — Ramanujan COMPOSES them (NS8), never reimplements.
// =====================================================================================

test('E2 inheritance: the journal + sleep seams resolve through the manifest', async () => {
  const journalSeam = await resolveJournalSeam();
  const sleepSeam = await resolveSleepSeam();

  assert.ok(Array.isArray(journalSeam.JOURNAL_FIELDS) && journalSeam.JOURNAL_FIELDS.length === 7,
    'the inherited journal schema is the pinned 7 fields');
  assert.equal(typeof journalSeam.validateEntry, 'function');
  assert.ok(journalSeam.PROVENANCE_VALUES.includes(GENUINE));

  assert.equal(typeof sleepSeam.distill, 'function');
  assert.equal(typeof sleepSeam.clusterEntries, 'function');
  assert.equal(typeof sleepSeam.runSleepCycle, 'function');
});

test('E2 inheritance: resolveModuleSeam fails fast on an unknown logical_name', async () => {
  await assert.rejects(() => resolveModuleSeam('not-an-inherited-seam'), /no entry logical_name/);
});

// =====================================================================================
// 1. A completed run → well-formed 7-field entries (one per fixture).
// =====================================================================================

test('E2 run→entries: every entry is a well-formed 7-field genuine record (inherited validator)', async () => {
  const journalSeam = await resolveJournalSeam();
  const corpus = loadCorpus();
  const entries = runToJournalEntries({ scorerName: SCORER.BATTERY_ON, corpus, runId: 'run-A', journalSeam });

  assert.ok(entries.length > 0, 'a completed run yields at least one entry');
  for (const e of entries) {
    // validated by the INHERITED validator — the wave never invents its own schema check
    assert.equal(journalSeam.validateEntry(e).ok, true, `entry ${e.id} should validate: ${journalSeam.validateEntry(e).detail}`);
    assert.equal(Object.keys(e).length, 7);
    assert.equal(e.skill, RAMANUJAN_SKILL);
    assert.equal(e.provenance, GENUINE);
    assert.ok(e.situation.startsWith(`${SITUATION_PREFIX}:`));
    assert.ok([OUTCOME.PASS, OUTCOME.FAIL].includes(e.outcome));
  }
  // ids are deterministic + unique (no clock / no RNG): run-scoped, fixture-scoped.
  const ids = entries.map((e) => e.id);
  assert.equal(new Set(ids).size, ids.length, 'entry ids are unique');
  assert.ok(ids.every((id) => id.startsWith('run-A::')));
});

test('E2 run→entries: outcome grading matches Metric-G grading (catch / settle)', () => {
  // A defect is correct iff flagged (caught); a sound fixture is correct iff NOT flagged (settles).
  assert.equal(fixtureRunIsCorrect({ subset: SUBSET.SCORED }, true), true); // defect caught
  assert.equal(fixtureRunIsCorrect({ subset: SUBSET.SCORED }, false), false); // defect missed
  assert.equal(fixtureRunIsCorrect({ subset: SUBSET.SOUND }, false), true); // sound settled
  assert.equal(fixtureRunIsCorrect({ subset: SUBSET.SOUND }, true), false); // sound false-positive
});

test('E2 run→entries: a healthy BATTERY-ON run has NO fixture-failures (oracle is sound)', async () => {
  const journalSeam = await resolveJournalSeam();
  const entries = runToJournalEntries({ scorerName: SCORER.BATTERY_ON, runId: 'run-on', journalSeam });
  const failures = fixtureFailureInput(entries);
  assert.equal(failures.length, 0, 'the real battery catches every defect and settles every sound fixture');
  assert.ok(entries.every((e) => e.outcome === OUTCOME.PASS));
});

test('E2 run→entries: the ABLATION run misses every defect (fixture-failures appear)', async () => {
  const journalSeam = await resolveJournalSeam();
  const corpus = loadCorpus();
  const entries = runToJournalEntries({ scorerName: SCORER.ABLATION, corpus, runId: 'run-abl', journalSeam });
  const failures = fixtureFailureInput(entries);

  // battery OFF ⇒ no defect is withheld ⇒ every SCORED defect is a MISS; sound fixtures still settle.
  const scoredCount = DEFECT_CLASSES.reduce((n, k) => n + corpus.defects[k].length, 0);
  assert.equal(failures.length, scoredCount, 'every scored defect is missed under ablation');
  assert.ok(failures.every((e) => e.outcome === OUTCOME.FAIL && e.subset === undefined));
  // the sound subset still settles (no false positives) under ablation
  assert.ok(entries.filter((e) => !failures.includes(e)).every((e) => e.outcome === OUTCOME.PASS));
});

test('E2 run→entries: a non-genuine runId / bad scorer is refused', async () => {
  const journalSeam = await resolveJournalSeam();
  assert.throws(() => runToJournalEntries({ runId: '', journalSeam }), /non-empty runId/);
  assert.throws(() => runToJournalEntries({ runId: 'x', scorerName: 'bogus', journalSeam }), /unknown scorer/);
  assert.throws(() => runToJournalEntries({ runId: 'x' }), /journal seam/);
});

// =====================================================================================
// 2. The durable, append-only JournalStore (inherited substrate — reuse, no new store).
// =====================================================================================

test('E2 durability: an appended entry survives a simulated restart (fresh store reload)', async () => {
  const substrate = await loadDurabilitySubstrate();
  const journalSeam = await resolveJournalSeam();
  const file = scratchFile('durable');

  const store = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry });
  const entry = {
    id: 'e1', skill: RAMANUJAN_SKILL, situation: `${SITUATION_PREFIX}:derivation-error`, context: 'ctx-1',
    observation: 'caught', outcome: OUTCOME.PASS, provenance: GENUINE,
  };
  store.append(entry);

  // Simulate a restart: a brand-new store that holds NO in-memory state reads only from disk.
  const reopened = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry });
  assert.equal(reopened.entries.length, 1);
  assert.deepEqual(reopened.entries[0], entry);
});

test('E2 durability: the store is append-only — appends accumulate, never overwrite', async () => {
  const substrate = await loadDurabilitySubstrate();
  const journalSeam = await resolveJournalSeam();
  const file = scratchFile('append-only');
  const mk = (id, ctx) => ({
    id, skill: RAMANUJAN_SKILL, situation: `${SITUATION_PREFIX}:dimensional`, context: ctx,
    observation: 'obs', outcome: OUTCOME.FAIL, provenance: GENUINE,
  });

  const s1 = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry });
  s1.append(mk('a', 'c1'));
  const s2 = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry }); // reload
  s2.append(mk('b', 'c2'));

  const s3 = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry });
  assert.deepEqual(s3.entries.map((e) => e.id), ['a', 'b'], 'both entries persist in append order');
});

test('E2 durability: a malformed entry is REFUSED by the inherited validator (never appended)', async () => {
  const substrate = await loadDurabilitySubstrate();
  const journalSeam = await resolveJournalSeam();
  const file = scratchFile('refuse');
  const store = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry });

  // missing the required `observation` field
  assert.throws(() => store.append({
    id: 'bad', skill: RAMANUJAN_SKILL, situation: 's', context: 'c', outcome: OUTCOME.PASS, provenance: GENUINE,
  }), /refused entry bad/);
  // out-of-vocabulary provenance
  assert.throws(() => store.append({
    id: 'bad2', skill: RAMANUJAN_SKILL, situation: 's', context: 'c', observation: 'o', outcome: OUTCOME.PASS,
    provenance: 'fabricated',
  }), /refused entry bad2/);

  const reopened = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry });
  assert.equal(reopened.entries.length, 0, 'nothing malformed was persisted');
});

test('E2 store: construction guards (substrate shape + file + validator required)', async () => {
  const substrate = await loadDurabilitySubstrate();
  const journalSeam = await resolveJournalSeam();
  assert.throws(() => new JournalStore({}, 'f', { validateEntry: journalSeam.validateEntry }), /durability substrate/);
  assert.throws(() => new JournalStore(substrate, '', { validateEntry: journalSeam.validateEntry }), /file path/);
  assert.throws(() => new JournalStore(substrate, 'f', {}), /validateEntry/);
});

// =====================================================================================
// 3. THE done-when — a completed run appends a 7-field entry AND the sleep loop consumes it.
// =====================================================================================

test('E2 done-when (GWT): a completed run appends 7-field entries and the sleep loop reads them', async () => {
  const file = scratchFile('integrate-on');
  const report = await integrateRun({ scorerName: SCORER.BATTERY_ON, runId: 'integrate-on', file });

  // a well-formed 7-field entry was appended (in fact one per fixture) ...
  assert.ok(report.appended > 0);
  assert.equal(report.journal.length, report.appended);
  const journalSeam = await resolveJournalSeam();
  for (const e of report.journal) assert.equal(journalSeam.validateEntry(e).ok, true);

  // ... and the sleep loop CONSUMED it (distill ran over the journal's fixture-failure input).
  assert.ok(report.distill && Array.isArray(report.distill.candidates) && Array.isArray(report.distill.rejected));
  // a healthy battery-on run has no failures, so there is nothing to learn (oracle is sound).
  assert.equal(report.failureInput.length, 0);
  assert.equal(report.distill.candidates.length, 0);
});

test('E2 fixture-failure learning: the ablation run distills per-class lessons via the sleep loop', async () => {
  const file = scratchFile('integrate-abl');
  const report = await integrateRun({ scorerName: SCORER.ABLATION, runId: 'integrate-abl', file });

  // the run's fixture-FAILURES (every missed defect) feed the sleep loop ...
  assert.ok(report.failureInput.length > 0, 'ablation produces fixture-failures');
  assert.ok(report.failureInput.every((e) => e.outcome === OUTCOME.FAIL));

  // ... which distills a cross-context-corroborated lesson PER defect class (≥3 instances ⇒ ≥2 contexts).
  const learnedSituations = report.distill.candidates.map((c) => c.situation).sort();
  const expected = DEFECT_CLASSES.map((k) => `${SITUATION_PREFIX}:${k}`).sort();
  assert.deepEqual(learnedSituations, expected, 'every defect class yields a distilled fixture-failure lesson');
  // each distilled candidate is corroborated across ≥2 distinct fixture instances (R5).
  for (const c of report.distill.candidates) assert.ok(c.contexts.length >= 2);
});

test('E2 fixture-failure learning: the journal is the durable audit reloaded from disk', async () => {
  const file = scratchFile('audit');
  const report = await integrateRun({ scorerName: SCORER.ABLATION, runId: 'audit', file });

  // integrateRun's `journal` is read back via a FRESH store from disk — prove it equals what's on disk.
  const substrate = await loadDurabilitySubstrate();
  const journalSeam = await resolveJournalSeam();
  const onDisk = JournalStore.load(substrate, file, { validateEntry: journalSeam.validateEntry }).entries;
  assert.deepEqual(report.journal, onDisk);
  assert.equal(report.journal.length, report.appended);
});

test('E2 provenance-distrust: seeded entries never corroborate a lesson (R5, inherited)', async () => {
  // The sleep loop is the inherited one; confirm the integration respects R5: a seeded entry that
  // duplicates a genuine failure's situation in a NEW context does NOT count toward corroboration.
  const sleepSeam = await resolveSleepSeam();
  const genuine = (id, ctx) => ({
    id, skill: RAMANUJAN_SKILL, situation: `${SITUATION_PREFIX}:off-by-one`, context: ctx,
    observation: 'missed', outcome: OUTCOME.FAIL, provenance: GENUINE,
  });
  const seeded = { ...genuine('seed', 'ctx-seed'), provenance: 'seeded' };

  // one genuine context + one seeded context ⇒ NOT cross-context-corroborated (seeded distrusted).
  const onlyOneGenuine = sleepSeam.distill([genuine('g1', 'ctx-1'), seeded]);
  assert.equal(onlyOneGenuine.candidates.length, 0, 'a seeded context does not corroborate');

  // two genuine contexts ⇒ corroborated.
  const twoGenuine = sleepSeam.distill([genuine('g1', 'ctx-1'), genuine('g2', 'ctx-2')]);
  assert.equal(twoGenuine.candidates.length, 1);
});

// =====================================================================================
// 4. openJournal wires the inherited seams + substrate together.
// =====================================================================================

test('E2 openJournal: returns a store wired to the inherited validator + seams', async () => {
  const file = scratchFile('open');
  const { store, journalSeam, sleepSeam, substrate } = await openJournal({ file });
  assert.ok(store instanceof JournalStore);
  assert.equal(typeof journalSeam.validateEntry, 'function');
  assert.equal(typeof sleepSeam.distill, 'function');
  assert.equal(typeof substrate.writeCheckpointAtomic, 'function');
  assert.equal(store.entries.length, 0, 'a fresh journal file starts empty');
  await assert.rejects(() => openJournal({}), /file path/);
});
