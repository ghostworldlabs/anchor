// test/corpus.test.mjs — Wave 9: the labeled-corpus heuristic precision gate.
//
// This is the executable form of the frozen acceptance criterion:
//
//   "Given the hand-labeled corpus of 5–10 real messy folders, when heuristic
//    mode runs over the corpus in CI, then removal-verdict precision meets or
//    exceeds the agreed bar, or the heuristic-mode flag remains unshipped and
//    each miss is filed as an exclusion/tuning task."
//
// TWO things run here, and both are load-bearing:
//
//   1. CORPUS INTEGRITY. A precision bar measured against a corpus with an
//      unlabeled file, a bad truth value, or no negative control is a slogan.
//      The corpus README states the rules ("every file must carry a label",
//      "06 is the negative control, every label keep"); these tests enforce
//      them so the corpus cannot silently rot into a number that means nothing.
//
//   2. THE PRECISION GATE ITSELF. Each folder is materialised into a temp
//      directory (with its declared mtimes stamped — see the corpus README for
//      why the corpus carries ages rather than being a checked-in tree), then
//      run through heuristic mode. The set of paths heuristic mode surfaces as
//      REMOVAL candidates is the tool's removal verdict; precision is measured
//      against the hand labels.
//
// THE BAR IS 1.0 — ZERO FALSE POSITIVES. The MASTER-PLAN is explicit that v1
// gates precision on removals, "where wrong = data-loss risk", and that "missing
// some mess is acceptable, flagging good files is not." A single keep-labeled
// file offered for removal is therefore a release blocker, not a rounding error.
// Recall is measured and reported for visibility but is NOT gated (v1 gates
// precision only); a low-recall folder is a tuning task, never a build failure.
//
// WHAT "HEURISTIC MODE" MEANS HERE. The removal verdict is the heuristic stage's
// emitted candidate set, filtered through the same protection predicate the
// pipeline applies before emission — i.e. exactly the paths a human would see a
// remove control for (default-unchecked). Measuring the deterministic candidate
// set, rather than an LLM debate verdict, is what lets this gate run in CI at all:
// a bar that needed a live model could not be a build gate. The stage requires
// TWO independent heuristics before it emits anything, which is the precision
// defence this gate exists to measure.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { runPipeline } from '../engine/pipeline.mjs';
import { scanStage } from '../engine/stages/scan.stage.mjs';
import { hygieneStage } from '../engine/stages/hygiene.stage.mjs';
import { heuristicStage } from '../engine/stages/heuristic.stage.mjs';
import { makeTempRoot, rmTempRoot, materialiseCorpus } from './helpers/git-fixture.mjs';

const CORPUS_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'corpus');

/** The agreed shipping bar: removals must be RIGHT, always. Wrong = data loss. */
const PRECISION_BAR = 1.0;

/** The stages that constitute a heuristic-mode candidate run, deterministically. */
const HEURISTIC_MODE_STAGES = [scanStage, hygieneStage, heuristicStage];

async function loadIndex() {
  return JSON.parse(await fs.readFile(path.join(CORPUS_DIR, 'index.json'), 'utf8'));
}

async function loadMember(file) {
  return JSON.parse(await fs.readFile(path.join(CORPUS_DIR, file), 'utf8'));
}

/**
 * Run one corpus folder through heuristic mode and return the set of paths the
 * tool surfaced as REMOVAL candidates (post-protection, exactly as a panel would
 * receive them).
 */
async function heuristicRemovalVerdicts(spec) {
  const root = await makeTempRoot('tidy-idy-corpus-');
  try {
    await materialiseCorpus(spec, root);
    const envelope = await runPipeline({
      rootPath: root,
      mode: 'heuristic',
      // No stage below reaches a model; the empty agent guarantees no accidental
      // dependency on one and keeps the gate a pure function of the fixtures.
      agent: async () => [],
      stages: HEURISTIC_MODE_STAGES,
    });
    assert.notStrictEqual(envelope.status, 'failed',
      `heuristic run over '${spec.id}' failed: ${JSON.stringify(envelope.stages.flatMap((s) => s.errors || []), null, 2)}`);
    const heuristic = envelope.stages.find((s) => s.stage === 'heuristic');
    assert.ok(heuristic, `the heuristic stage must have run over '${spec.id}'`);
    // Every heuristic candidate is a removal verdict; the stage emits action
    // 'remove' by construction, and protection has already filtered the set.
    return (heuristic.findings || []).filter((f) => f.action === 'remove').map((f) => f.path);
  } finally {
    await rmTempRoot(root);
  }
}

// ────────────────────────────────────────────────────────────────────────────
// 1. Corpus integrity — the gate is only worth having if the labels are honest.
// ────────────────────────────────────────────────────────────────────────────

describe('the labeled corpus is well-formed', () => {
  let index;
  let members;

  before(async () => {
    index = await loadIndex();
    members = [];
    for (const file of index.members) members.push({ file, spec: await loadMember(file) });
  });

  test('the index lists 5–10 members, as the criterion requires', () => {
    assert.ok(index.members.length >= 5 && index.members.length <= 10,
      `the corpus must have 5–10 members (the frozen criterion); has ${index.members.length}`);
  });

  test('every member declares heuristic mode and unique id', () => {
    const ids = new Set();
    for (const { file, spec } of members) {
      assert.strictEqual(spec.mode, 'heuristic', `${file} must declare heuristic mode`);
      assert.ok(spec.id, `${file} must declare an id`);
      assert.ok(!ids.has(spec.id), `duplicate corpus id '${spec.id}'`);
      ids.add(spec.id);
      assert.ok(Array.isArray(spec.files) && spec.files.length, `${file} must list files`);
      assert.ok(Array.isArray(spec.labels) && spec.labels.length, `${file} must carry labels`);
    }
  });

  test('EVERY file carries exactly one label with a valid truth value', () => {
    // The README's rule, enforced: "a partially labeled folder would let a miss
    // hide in the unlabeled remainder." No file may be unlabeled, doubly
    // labeled, or labeled with anything but remove/keep.
    for (const { file, spec } of members) {
      const filePaths = spec.files.map((f) => f.path).sort();
      const labelPaths = spec.labels.map((l) => l.path).sort();
      assert.deepStrictEqual(labelPaths, filePaths,
        `${file}: every file must have exactly one label and every label a file — unlabeled or orphan labels let misses hide`);
      for (const l of spec.labels) {
        assert.ok(l.truth === 'remove' || l.truth === 'keep',
          `${file}: label for '${l.path}' has truth '${l.truth}', expected remove|keep`);
        assert.ok(l.why && l.why.length > 0, `${file}: the label for '${l.path}' must say WHY, so a reviewer can disagree`);
      }
    }
  });

  test('a negative control exists: at least one folder whose every label is keep', () => {
    // "A corpus without one measures recall while pretending to measure precision."
    const controls = members.filter(({ spec }) => spec.labels.every((l) => l.truth === 'keep'));
    assert.ok(controls.length >= 1, 'the corpus must contain an all-keep negative control folder');
    // And it must not be trivial — a one-file all-keep folder proves little.
    assert.ok(controls.some(({ spec }) => spec.files.length >= 3),
      'the negative control must be substantial enough to be a real precision test');
  });
});

// ────────────────────────────────────────────────────────────────────────────
// 2. The precision gate — measured on the real corpus, in CI.
// ────────────────────────────────────────────────────────────────────────────

describe('heuristic-mode removal precision meets the shipping bar', () => {
  let index;
  const perFolder = [];
  const flaggedKeepers = []; // every false positive, folder + path — the blocker list

  before(async () => {
    index = await loadIndex();
    for (const file of index.members) {
      const spec = await loadMember(file);
      const truthByPath = new Map(spec.labels.map((l) => [l.path, l.truth]));
      const verdicts = await heuristicRemovalVerdicts(spec);

      let tp = 0;
      let fp = 0;
      for (const p of verdicts) {
        if (truthByPath.get(p) === 'remove') tp++;
        else { fp++; flaggedKeepers.push({ folder: spec.id, path: p, truth: truthByPath.get(p) || 'UNLABELED' }); }
      }
      const removeCount = spec.labels.filter((l) => l.truth === 'remove').length;
      perFolder.push({ id: spec.id, tp, fp, verdicts: verdicts.length, removeCount });
    }
  });

  test('NO keep-labeled file is ever offered for removal (precision = 1.0)', () => {
    // This is the release blocker. A false positive here is a good file the tool
    // proposed to delete — the one failure the whole design exists to prevent.
    assert.deepStrictEqual(flaggedKeepers, [],
      `PRECISION FAILURE — heuristic mode offered keep-labeled file(s) for removal:\n${
        flaggedKeepers.map((f) => `  • ${f.folder}: '${f.path}' (labeled ${f.truth})`).join('\n')
      }\nEach is a tuning/exclusion task; the heuristic-mode flag must not ship until the set is empty.`);
  });

  test('aggregate removal precision is at or above the agreed bar', () => {
    const tp = perFolder.reduce((n, f) => n + f.tp, 0);
    const fp = perFolder.reduce((n, f) => n + f.fp, 0);
    const precision = (tp + fp) === 0 ? 1 : tp / (tp + fp);
    assert.ok(tp + fp > 0, 'the gate must actually flag something — a run that proposes nothing measures nothing');
    assert.ok(precision >= PRECISION_BAR,
      `aggregate precision ${precision.toFixed(3)} is below the bar ${PRECISION_BAR} (tp=${tp}, fp=${fp})`);
  });

  test('the negative control folder produces ZERO removal verdicts', () => {
    // The strongest single precision assertion: an entirely-legitimate folder,
    // with files that superficially resemble junk (old vendored data, a licence,
    // a changelog), must yield nothing to remove.
    const control = perFolder.find((f) => f.id === '06-legit-small-project');
    assert.ok(control, 'the negative control folder must have been measured');
    assert.strictEqual(control.fp, 0, 'the negative control must yield no false positives');
    assert.strictEqual(control.verdicts, 0,
      'the negative control must yield no removal verdict at all — not even a "correct" one, since every label is keep');
  });

  test('recall is reported for visibility but NOT gated (v1 gates precision only)', () => {
    // Missing some mess is acceptable; flagging good files is not. This test only
    // records the number so a regression in recall is visible in the run output,
    // and asserts the weak floor that the corpus as a whole is not inert.
    const tp = perFolder.reduce((n, f) => n + f.tp, 0);
    const totalRemovals = perFolder.reduce((n, f) => n + f.removeCount, 0);
    const recall = totalRemovals === 0 ? 1 : tp / totalRemovals;
    assert.ok(recall > 0,
      `heuristic mode recalled ${tp}/${totalRemovals} true removals (recall ${recall.toFixed(2)}) — a corpus that recalls nothing is measuring nothing`);
  });
});
