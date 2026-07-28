// test/dual-suite-gate.test.mjs — Wave 5: dual-suite terminal gate contract.
//
// Wave 5 makes full literature-review + researchPrime suites the terminal
// green gate (no regression to RP convergent verification / lit-review PRISMA
// honesty). Foreman's measured command remains `node --test test/` in this
// tree; this file locks the dual-suite *contract* that both skill suites:
//   • are resolvable and present;
//   • still expose the honesty surfaces Wave 5 depends on
//     (LITREVIEW_LIVE degraded posture, breadth stamps, gemini-cli labels,
//     oranges answer-branch-only, matrixScheduler v1.1 non-goal);
//   • do not re-home C3 acceptance (already in Waves 2–3).
//
// Orchestrator still owns running the RP suite as a separate gate when
// measuring dual green; this test proves the wiring + invariants without
// re-executing the entire RP suite inside every lit-review gate tick.

import { test, describe } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { resolveResearchPrimeRoot, importRp, rpFile } from './_wave1-trio-resolve.mjs';
import {
  isLiveRun,
  resolveComposedPosture,
  claim,
  POSTURE_DEGRADED,
  POSTURE_GOVERNED,
  SCOPE_PLAN_REVIEW,
  NO_LIVE_SEATS_REASON,
} from '../src/posture-resolver.mjs';
import {
  MATRIX_SCHEDULER_V1_SCOPE,
  BREADTH_TELEMETRY_VERSION,
  buildBreadthTelemetry,
} from '../src/breadthTelemetry.mjs';
import { BREADTH_STAMPS } from '../src/facetsFromPlan.mjs';
import {
  answerPlanForOranges,
  isFacetRecord,
  runOrangesOnAnswerBranches,
} from '../src/rpFacetCoverage.mjs';
import {
  assertNoApiStyleGeminiIds,
  GEMINI_CLI_DRIVER,
  findApiStyleGeminiIdsInSource,
} from '../src/reviewSeatLabels.mjs';

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR = path.resolve(TEST_DIR, '..');

describe('Wave 5 — dual-suite terminal gate: both skill trees present', () => {
  test('literature-review suite is the Foreman-measured tree (test/*.test.mjs)', () => {
    const testDir = path.join(SKILL_DIR, 'test');
    assert.ok(fs.existsSync(testDir));
    const suite = fs
      .readdirSync(testDir)
      .filter((f) => f.endsWith('.test.mjs'));
    assert.ok(suite.length > 20, `expected a full lit-review suite, found ${suite.length}`);
    assert.ok(suite.includes('breadth-honesty-telemetry.test.mjs'));
    assert.ok(suite.includes('review-seat-labels.test.mjs'));
    assert.ok(suite.includes('rp-facet-coverage.test.mjs'));
    assert.ok(suite.includes('posture-resolver.test.mjs'));
    // Plan test-command pin.
    const plan = fs.readFileSync(path.join(SKILL_DIR, 'IMPLEMENTATION-PLAN.md'), 'utf8');
    assert.match(plan, /test-command:\s*node --test test\//);
  });

  test('researchPrime suite is resolvable (RP_ROOT / deployed skill) with package test script', () => {
    const rpRoot = resolveResearchPrimeRoot();
    assert.ok(fs.existsSync(path.join(rpRoot, 'bin', 'oranges.mjs')));
    assert.ok(fs.existsSync(path.join(rpRoot, 'bin', 'governor.mjs')));
    assert.ok(fs.existsSync(path.join(rpRoot, 'bin', 'facet-coverage.mjs')));
    const pkg = JSON.parse(fs.readFileSync(path.join(rpRoot, 'package.json'), 'utf8'));
    assert.ok(
      typeof pkg.scripts?.test === 'string' && pkg.scripts.test.length > 0,
      'researchPrime must declare a test script for the dual-suite terminal gate',
    );
    const rpTests = fs
      .readdirSync(path.join(rpRoot, 'test'))
      .filter((f) => f.endsWith('.test.mjs'));
    assert.ok(rpTests.length > 5, `expected RP suite tests, found ${rpTests.length}`);
  });

  test('RP facet-coverage seam still resolves skill-local lit-review implementation', async () => {
    // Ensure LITREVIEW_ROOT points at this checkout for the seam.
    const prev = process.env.LITREVIEW_ROOT;
    process.env.LITREVIEW_ROOT = SKILL_DIR;
    try {
      const seam = await importRp('bin/facet-coverage.mjs');
      assert.equal(typeof seam.runPrePhase2FacetCoverage, 'function');
      assert.equal(typeof seam.answerPlanForOranges, 'function');
      assert.equal(typeof seam.attachFacetCoverageToRunRecord, 'function');
      const constants = await seam.getFacetCoverageConstants();
      assert.equal(constants.BREADTH_STAMPS.FROM_BRANCHES, BREADTH_STAMPS.FROM_BRANCHES);
      assert.equal(constants.BREADTH_STAMPS.NONE, BREADTH_STAMPS.NONE);
    } finally {
      if (prev === undefined) delete process.env.LITREVIEW_ROOT;
      else process.env.LITREVIEW_ROOT = prev;
    }
  });
});

describe('Wave 5 — no regression: LITREVIEW_LIVE degraded posture preserved', () => {
  test('without --live / LITREVIEW_LIVE=1 the run stamp is degraded (named reason)', () => {
    assert.equal(isLiveRun({ live: false, env: {} }), false);
    assert.equal(isLiveRun({ live: false, env: { LITREVIEW_LIVE: '0' } }), false);
    assert.equal(isLiveRun({ live: true, env: {} }), true);
    assert.equal(isLiveRun({ live: false, env: { LITREVIEW_LIVE: '1' } }), true);

    const artifact = resolveComposedPosture({
      claims: [claim(SCOPE_PLAN_REVIEW, POSTURE_GOVERNED, 'hash-bound plan gate')],
      live: false,
      env: {},
    });
    assert.equal(artifact.runStamp, POSTURE_DEGRADED);
    assert.ok(
      artifact.degradedReasons.some((r) => r.includes(NO_LIVE_SEATS_REASON)),
      'degraded reason must name no live seats / LITREVIEW_LIVE',
    );
    // Governed stays scoped to plan-review only — never co-presented as run stamp.
    assert.equal(artifact.scopes[SCOPE_PLAN_REVIEW].posture, POSTURE_GOVERNED);
    assert.notEqual(artifact.runStamp, POSTURE_GOVERNED);
  });
});

describe('Wave 5 — no regression: RP oranges still answer-branches only', () => {
  test('answerPlanForOranges never projects facet records; oranges receives branches only', () => {
    const plan = {
      branches: [
        { id: 'B1', question: 'Answer branch A', est_value: 10, est_cost: 1 },
        { id: 'B2', question: 'Answer branch B', est_value: 0, est_cost: 1 },
      ],
    };
    // Facet-shaped contaminants must not be treatable as answer branches here.
    const facetShaped = {
      id: 'facet:B1',
      question: 'Coverage axis, not an answer',
      sourceBranchId: 'B1',
      order: 0,
    };
    assert.equal(isFacetRecord(facetShaped), true);
    const answerPlan = answerPlanForOranges(plan);
    assert.equal(answerPlan.branches.length, 2);
    for (const b of answerPlan.branches) {
      assert.equal(isFacetRecord(b), false, 'answer plan must not contain facet records');
    }

    let received = null;
    const receipt = runOrangesOnAnswerBranches(plan, (p) => {
      received = p;
      return { dropped: [], stamp: 'test-foresight', crit3_satisfied: true };
    });
    assert.ok(received);
    assert.equal(received.branches.length, 2);
    for (const b of received.branches) {
      assert.equal(isFacetRecord(b), false);
    }
    assert.equal(receipt.stamp, 'test-foresight');
  });
});

describe('Wave 5 — matrixScheduler is v1.1 non-goal (not v1 primary)', () => {
  test('MATRIX_SCHEDULER_V1_SCOPE documents optional follow-on only', () => {
    assert.equal(MATRIX_SCHEDULER_V1_SCOPE.primaryForV1, false);
    assert.equal(MATRIX_SCHEDULER_V1_SCOPE.status, 'v1.1-non-goal-follow-on');
    assert.match(MATRIX_SCHEDULER_V1_SCOPE.note, /optional v1\.1/);
    // Hash-pinned matrixScheduler.mjs remains in-tree for the Wave-11 fence but
    // is not the v1 facet fan-out path (facetsFromPlan + breadthStage are).
    assert.ok(fs.existsSync(path.join(SKILL_DIR, 'src', 'matrixScheduler.mjs')));
    assert.ok(fs.existsSync(path.join(SKILL_DIR, 'src', 'breadthStage.mjs')));
    assert.ok(fs.existsSync(path.join(SKILL_DIR, 'src', 'facetsFromPlan.mjs')));
  });
});

describe('Wave 5 — skill-local facets (no trio-shared greenwash)', () => {
  test('facetsFromPlan + breadthTelemetry live skill-local under lit-review src/', () => {
    assert.ok(fs.existsSync(path.join(SKILL_DIR, 'src', 'facetsFromPlan.mjs')));
    assert.ok(fs.existsSync(path.join(SKILL_DIR, 'src', 'breadthTelemetry.mjs')));
    assert.ok(fs.existsSync(path.join(SKILL_DIR, 'src', 'rpFacetCoverage.mjs')));
    // Wave 6 may extract; Wave 5 keeps skill-local. No trio-shared/breadth package required.
    assert.equal(BREADTH_TELEMETRY_VERSION, 'breadth-telemetry/1');
    const empty = buildBreadthTelemetry({ skill: 'literature-review', outcome: null });
    assert.equal(empty.inventedFacets, false);
  });
});

describe('Wave 5 — review seats: gemini-cli labels; RP live routes use gemini-cli', () => {
  test('researchPrime live-round-agent DEFAULT_ROUND_ROUTES uses gemini-cli drivers only', async () => {
    const live = await importRp('bin/live-round-agent.mjs');
    const routes = live.DEFAULT_ROUND_ROUTES;
    const labels = Object.values(routes).map((r) => r.driver);
    assertNoApiStyleGeminiIds(labels);
    for (const role of live.VERIFICATION_ROLES) {
      assert.equal(
        routes[role]?.driver,
        GEMINI_CLI_DRIVER,
        `verification role ${role} must route via gemini-cli (not product model ids)`,
      );
    }
  });

  test('lit-review production paths (cli + posture + telemetry) carry no API-style Gemini product ids', () => {
    // reviewSeatLabels.mjs is the ban definition and intentionally names product
    // ids in comments/regex — it is covered by review-seat-labels.test.mjs, not here.
    for (const rel of [
      'bin/cli.mjs',
      'src/posture-resolver.mjs',
      'src/breadthTelemetry.mjs',
      'src/rpFacetCoverage.mjs',
      'src/breadthStage.mjs',
    ]) {
      const src = fs.readFileSync(path.join(SKILL_DIR, rel), 'utf8');
      const offenders = findApiStyleGeminiIdsInSource(src);
      assert.deepStrictEqual(
        offenders,
        [],
        `${rel} must not hard-code API-style Gemini product ids; found ${offenders.join(', ')}`,
      );
    }
  });
});

describe('Wave 5 — RP convergent verification gate surface unchanged', () => {
  test('oranges + governor modules still exist and export expected symbols', async () => {
    const oranges = await importRp('bin/oranges.mjs');
    assert.equal(typeof oranges.runForesight, 'function');
    const governor = await importRp('bin/governor.mjs');
    assert.equal(typeof governor.runGovernedRound, 'function');
    // Frozen gate files used by lit-review Stage-0 remain present (byte-stable
    // checks live in frozen-gate-bytes.test.mjs — this only asserts presence).
    assert.ok(fs.existsSync(rpFile('bin', 'plan-gate.mjs')));
    assert.ok(fs.existsSync(rpFile('bin', 'two-gate.mjs')));
  });
});
