// test/stage0-halt-before-snowball.test.mjs — Wave 9: the Stage-0 PLAN phase HALTs at
// the frozen one-shot gate BEFORE snowball, with a written plan artifact and fully
// serialized pipeline state.
//
// Pins the acceptance GWT: a lit-review invocation with a brownfield content path and
// no gate response yet reaches Stage-0, writes a plan artifact, HALTs with serialized
// pipeline state, never invokes src/search.mjs, and leaves PRISMA state initialized
// but NOT advanced. Also pins the structural fence: the thin Stage-0 consumer and the
// pipeline-state module never import src/search.mjs, and bin/cli.mjs unlocks
// performSnowballSearch ONLY behind the stage0AllowsExecution predicate.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import {
  runStage0Plan,
  stage0AllowsExecution,
  STAGE0_STATUSES,
  PIPELINE_STATE_FILENAME,
  PLAN_ARTIFACT_FILENAME,
} from '../src/stage0-plan.mjs';
import { initialPrismaState, readPipelineState, PIPELINE_STATUSES } from '../src/pipeline-state.mjs';
import { buildNormalizedView } from '../src/textNormalization.mjs';
import { groundQuote } from '../src/quoteExtractor.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.resolve(TEST_DIR, '..');
const LOOSE_NOTES = path.join(TEST_DIR, 'fixtures', 'adversarial-intake', 'loose-notes');
const GROUNDING = { buildNormalizedView, groundQuote };
const SEEDS = [
  { idType: 'doi', id: '10.1234/example.5678', title: 'A seed paper on deduplication' },
  { idType: 'arxiv', id: '2401.12345', title: 'Second seed on data quality' },
];

/** Deterministic Gandalf summarize spy grounded verbatim in the loose-notes fixture. */
function summarizeSpy() {
  const spy = (payload) => {
    spy.calls.push(payload);
    return {
      sentences: [
        {
          text: 'Held-out perplexity improved monotonically with data quality filtering.',
          sourceId: 'r0/scaling-notes.md',
          quote: 'the held-out perplexity improved monotonically with data quality filtering',
        },
      ],
    };
  };
  spy.calls = [];
  return spy;
}

/** Deterministic derive spy emitting a schema-valid artifact anchored to its fenced context. */
function deriveSpy(deriveMod) {
  const spy = (payload) => {
    spy.calls.push(payload);
    const sourceId =
      deriveMod.SUMMARY_SOURCE_ID in payload.groundedSources
        ? deriveMod.SUMMARY_SOURCE_ID
        : deriveMod.INTENT_SOURCE_ID;
    const anchors = [{ sourceId, quote: payload.groundedSources[sourceId] }];
    return {
      artifactVersion: 'plan-artifact/1',
      scope: { statement: 'Derived scope.', axis: 'Derived AXIS.', anchors },
      branches: [{ question: 'Derived question?', rationale: 'Derived rationale.', anchors }],
      sourcesToBeat: [],
      foresight: {
        dropped: 'nothing dropped',
        counterfactualCost: 'no cost',
        stamp: 'no foresight value added',
        anchors,
      },
      seeds: SEEDS.map(({ idType, id, title }) => ({ idType, id, title })),
    };
  };
  spy.calls = [];
  return spy;
}

/** A summarize/derive adapter that must never run (the zero-LLM-on-resume fence). */
function forbiddenAdapter(name) {
  return () => {
    throw new Error(`${name} must never be invoked on this path`);
  };
}

describe('Wave 9 — Stage-0 HALTs at the gate before snowball', () => {
  const runDirs = [];
  let deriveMod;
  let validateMod;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    deriveMod = await import(new URL('derivePlan.mjs', indexUrl).href);
    validateMod = await import(new URL('validatePlanArtifact.mjs', indexUrl).href);
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  function tmpRunDir(tag) {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), `litrev-w9-halt-${tag}-`));
    runDirs.push(d);
    return d;
  }

  test('a content-path run with no gate response writes the plan artifact and HALTs with serialized state; snowball is never unlocked', async () => {
    const runDir = tmpRunDir('content');
    const summarize = summarizeSpy();
    const derive = deriveSpy(deriveMod);

    // Wired EXACTLY as bin/cli.mjs wires it: snowball fires only behind the predicate.
    let snowballCalls = 0;
    const snowball = () => {
      snowballCalls += 1;
    };

    const stage0 = await runStage0Plan({
      runDir,
      intake: { roots: [LOOSE_NOTES], seeds: SEEDS },
      summarize,
      grounding: GROUNDING,
      derive,
      // NO gate decision channel: the run must HALT at the frozen gate.
    });
    if (stage0AllowsExecution(stage0)) snowball();

    // HALT, not RUN — and the snowball continuation never fired.
    assert.equal(stage0.status, STAGE0_STATUSES.HALTED);
    assert.equal(stage0AllowsExecution(stage0), false);
    assert.equal(snowballCalls, 0, 'snowball must never be entered before APPROVE');
    assert.equal(stage0.executionArtifact, null);
    assert.match(stage0.halt.reason, /Run halted at Gate 2/);

    // The plan artifact was WRITTEN (schema-valid, canonical) before the halt.
    const artifactPath = path.join(runDir, PLAN_ARTIFACT_FILENAME);
    assert.ok(fs.existsSync(artifactPath), 'plan artifact must be written at the HALT boundary');
    const writtenArtifact = JSON.parse(fs.readFileSync(artifactPath, 'utf8'));
    assert.equal(validateMod.validatePlanArtifact(writtenArtifact).ok, true);
    assert.equal(
      fs.readFileSync(artifactPath, 'utf8'),
      validateMod.canonicalStringifyPlanArtifact(stage0.artifact) + '\n',
      'the written plan artifact is the canonical serialization of the derived artifact',
    );

    // The ENTIRE pipeline state is serialized at the HALT boundary.
    const statePath = path.join(runDir, PIPELINE_STATE_FILENAME);
    assert.equal(stage0.statePath, statePath);
    const state = readPipelineState(statePath);
    assert.equal(state.status, PIPELINE_STATUSES.HALTED);
    assert.equal(state.stage, 'stage0-plan');
    assert.equal(state.route, 'content');
    assert.equal(state.plan.planBody, stage0.planBody);
    assert.ok(state.groundingCache.sources[deriveMod.SUMMARY_SOURCE_ID], 'grounding cache serialized');

    // PRISMA state: fully INITIALIZED by Stage-0, NOT advanced.
    assert.deepStrictEqual(state.prisma, initialPrismaState());
    assert.deepStrictEqual(state.prisma, {
      identified: 0,
      screened: 0,
      included: 0,
      excluded: 0,
      exclusions: [],
    });

    // The frozen gate left its own durable halt discipline; execution records absent.
    assert.ok(fs.existsSync(path.join(runDir, 'HALT-RECORD.json')));
    assert.equal(fs.existsSync(path.join(runDir, 'governance.json')), false);

    // Exactly ONE Gandalf call and ONE derive call were spent (the plan derivation).
    assert.equal(summarize.calls.length, 1);
    assert.equal(derive.calls.length, 1);

    // The plan was PRESENTED (one-shot) as human-readable prose before the halt.
    assert.equal(stage0.presentations.length, 1);
    assert.match(stage0.planBody, /# Research Plan/);
    assert.match(stage0.planBody, /## Candidate branches \/ questions/);
    assert.match(stage0.planBody, /## Seeds/);
  });

  test('a halted run re-entered with still no decision stays HALTED and spends ZERO further intake calls', async () => {
    const runDir = tmpRunDir('rehalt');
    const summarize = summarizeSpy();
    const derive = deriveSpy(deriveMod);
    const first = await runStage0Plan({
      runDir,
      intake: { roots: [LOOSE_NOTES], seeds: SEEDS },
      summarize,
      grounding: GROUNDING,
      derive,
    });
    assert.equal(first.status, STAGE0_STATUSES.HALTED);

    const again = await runStage0Plan({
      runDir,
      intake: { roots: [LOOSE_NOTES], seeds: SEEDS },
      summarize: forbiddenAdapter('summarize'),
      grounding: GROUNDING,
      derive: forbiddenAdapter('derive'),
    });
    assert.equal(again.resumed, true, 'the second entry resumes from the serialized state');
    assert.equal(again.status, STAGE0_STATUSES.HALTED);
    assert.equal(stage0AllowsExecution(again), false);
    assert.equal(again.planBody, first.planBody, 'the resumed plan body is the serialized one');
  });

  test('a FAILED intake (zero input) blocks execution and never presents the gate', async () => {
    const runDir = tmpRunDir('failed');
    const stage0 = await runStage0Plan({ runDir });
    assert.equal(stage0.status, STAGE0_STATUSES.FAILED);
    assert.equal(stage0AllowsExecution(stage0), false);
    assert.equal(stage0.artifact, null);
    assert.match(stage0.reason, /content/);
    assert.equal(fs.existsSync(path.join(runDir, PLAN_ARTIFACT_FILENAME)), false);
    assert.equal(fs.existsSync(path.join(runDir, 'governance.json')), false);
  });

  test('structural fence: Stage-0 and pipeline-state never import src/search.mjs; the CLI unlocks snowball only behind stage0AllowsExecution', () => {
    const stage0Src = fs.readFileSync(path.join(SKILL_DIR, 'src', 'stage0-plan.mjs'), 'utf8');
    const stateSrc = fs.readFileSync(path.join(SKILL_DIR, 'src', 'pipeline-state.mjs'), 'utf8');
    assert.doesNotMatch(stage0Src, /import[^;]*search\.mjs/s, 'stage0-plan.mjs must not import search.mjs');
    assert.doesNotMatch(stateSrc, /import[^;]*search\.mjs/s, 'pipeline-state.mjs must not import search.mjs');

    const cliSrc = fs.readFileSync(path.join(SKILL_DIR, 'bin', 'cli.mjs'), 'utf8');
    const gateIdx = cliSrc.indexOf('stage0AllowsExecution(stage0)');
    const snowballIdx = cliSrc.indexOf('performSnowballSearch(');
    assert.ok(gateIdx > -1, 'bin/cli.mjs must gate on stage0AllowsExecution');
    assert.ok(snowballIdx > -1, 'bin/cli.mjs still runs the committed snowball stage');
    assert.ok(
      gateIdx < snowballIdx,
      'the Stage-0 execution gate must sit BEFORE the snowball invocation in bin/cli.mjs',
    );
    assert.match(cliSrc, /if \(!stage0AllowsExecution\(stage0\)\)[\s\S]*?return;/, 'a non-RUN Stage-0 outcome returns before snowball');
  });
});
