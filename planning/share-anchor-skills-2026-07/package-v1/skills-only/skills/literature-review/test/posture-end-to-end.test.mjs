// test/posture-end-to-end.test.mjs — Wave 11: the new plan-first paths respect the
// LITREVIEW_LIVE degraded stamp end to end, and no artifact ever claims 'governed'
// and 'degraded' at the same scope.
//
// Unlike test/posture-resolver.test.mjs (Wave-5 unit coverage of the resolver), this
// suite composes posture claims from REAL Stage-0 runs: a seeds-only bootstrap run
// through the FROZEN gate to a hash-bound governance record, and a resumed run whose
// serialized pipeline state carries the intake TRUNCATED stamp. The claims those runs
// honestly support are then resolved under the exact bin/cli.mjs live convention
// (--live / LITREVIEW_LIVE === '1'), proving:
//
//   1. a governed plan-review gate does NOT make a run 'live' — without live seats
//      the whole-run stamp is 'degraded' with the named no-live-seats reason;
//   2. with live seats bound and nothing degraded, the run stamps 'live' while the
//      'governed' claim stays scoped to plan-review governance ONLY;
//   3. any degraded component (a truncated intake) downgrades the whole run even
//      when LITREVIEW_LIVE=1;
//   4. 'governed' and 'degraded' can never coexist at the same scope — composition
//      resolves one winner, and a hand-built dual claim is rejected by the invariant.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';
import { makeFullArtifact, makeGroundedSources, makeForbiddenParse } from './_wave4-rederive-fixtures.mjs';
import { runStage0Plan, STAGE0_STATUSES } from '../src/stage0-plan.mjs';
import { initializePipelineState, writePipelineState } from '../src/pipeline-state.mjs';
import {
  resolveComposedPosture,
  assertPostureInvariant,
  renderPostureStamp,
  claim,
  isLiveRun,
  PostureError,
  POSTURE_GOVERNED,
  POSTURE_DEGRADED,
  POSTURE_LIVE,
  SCOPE_RUN,
  SCOPE_PLAN_REVIEW,
  NO_LIVE_SEATS_REASON,
} from '../src/posture-resolver.mjs';

const SCOPE_INTAKE = 'brownfield-intake';

describe('Wave 11 — posture end-to-end over real Stage-0 runs', () => {
  const runDirs = [];
  let renderer;
  let governedStage0;
  let truncatedStage0;

  before(async () => {
    const indexUrl = await sharedBrownfieldUrl();
    renderer = await import(new URL('renderPlanProse.mjs', indexUrl).href);

    // A REAL seeds-only bootstrap run through the frozen gate: deterministic route,
    // APPROVE-verbatim, hash-bound governance record on disk.
    const seedsRunDir = fs.mkdtempSync(path.join(os.tmpdir(), 'litrev-w11-posture-seeds-'));
    runDirs.push(seedsRunDir);
    governedStage0 = await runStage0Plan({
      runDir: seedsRunDir,
      intake: { seeds: [{ idType: 'doi', id: '10.5555/posture.e2e', title: 'Posture E2E Seed' }] },
      gate: { decision: 'APPROVE' },
    });

    // A resumed run whose serialized pipeline state carries the intake TRUNCATED
    // stamp — the degraded-intake component of the composed posture.
    const truncRunDir = fs.mkdtempSync(path.join(os.tmpdir(), 'litrev-w11-posture-trunc-'));
    runDirs.push(truncRunDir);
    const artifact = makeFullArtifact();
    writePipelineState(
      path.join(truncRunDir, 'pipeline-state.json'),
      initializePipelineState({
        artifact,
        planBody: renderer.renderPlanProse(artifact),
        groundedSources: makeGroundedSources(),
        route: 'content',
        truncated: true,
        truncationStamp: { stamp: 'intake auto-truncated (posture e2e fixture)' },
      }),
    );
    truncatedStage0 = await runStage0Plan({
      runDir: truncRunDir,
      parse: makeForbiddenParse().parse,
      gate: { decision: 'APPROVE' },
    });
  });

  after(() => {
    for (const d of runDirs) fs.rmSync(d, { recursive: true, force: true });
  });

  /** The posture claims a resolved Stage-0 run honestly supports. */
  function claimsFor(stage0) {
    const claims = [];
    if (stage0.governanceRecord) {
      claims.push(
        claim(
          SCOPE_PLAN_REVIEW,
          POSTURE_GOVERNED,
          `hash-bound governance record for plan ${stage0.planHash}`,
        ),
      );
    }
    if (stage0.state?.truncated === true) {
      claims.push(claim(SCOPE_INTAKE, POSTURE_DEGRADED, stage0.state.truncationStamp?.stamp ?? 'intake truncated'));
    }
    return claims;
  }

  test('a governed gate without live seats stamps the WHOLE RUN degraded (LITREVIEW_LIVE unset)', () => {
    assert.equal(governedStage0.status, STAGE0_STATUSES.RUN);
    assert.ok(governedStage0.governanceRecord, 'the frozen gate resolved a hash-bound governance record');

    const artifact = resolveComposedPosture({ claims: claimsFor(governedStage0), env: {} });
    assert.equal(artifact.runStamp, POSTURE_DEGRADED);
    assert.equal(artifact.liveSeatsBound, false);
    assert.ok(
      artifact.degradedReasons.some((r) => r.includes(NO_LIVE_SEATS_REASON)),
      'the degraded stamp names the no-live-seats reason',
    );
    // The gate's honest claim survives — but only at its own scope.
    assert.equal(artifact.scopes[SCOPE_PLAN_REVIEW].posture, POSTURE_GOVERNED);
    assert.equal(artifact.scopes[SCOPE_RUN].posture, POSTURE_DEGRADED);
    assert.equal(assertPostureInvariant(artifact), true);

    const stamp = renderPostureStamp(artifact);
    assert.match(stamp, /^POSTURE: degraded \(whole-run\)/);
    assert.match(stamp, /scoped to plan-review governance only/);
  });

  test('the exact bin/cli.mjs live convention is honored: only --live or LITREVIEW_LIVE === "1" binds seats', () => {
    for (const env of [{}, { LITREVIEW_LIVE: '0' }, { LITREVIEW_LIVE: 'true' }, { LITREVIEW_LIVE: '' }]) {
      assert.equal(isLiveRun({ env }), false, `${JSON.stringify(env)} must NOT count as live`);
      const artifact = resolveComposedPosture({ claims: claimsFor(governedStage0), env });
      assert.equal(artifact.runStamp, POSTURE_DEGRADED);
    }
    assert.equal(isLiveRun({ env: { LITREVIEW_LIVE: '1' } }), true);
    assert.equal(isLiveRun({ live: true, env: {} }), true);
  });

  test('with live seats bound and no degraded component, the run stamps live and governed stays scoped', () => {
    const artifact = resolveComposedPosture({
      claims: claimsFor(governedStage0),
      env: { LITREVIEW_LIVE: '1' },
    });
    assert.equal(artifact.runStamp, POSTURE_LIVE);
    assert.equal(artifact.liveSeatsBound, true);
    assert.deepStrictEqual(artifact.degradedReasons, []);
    assert.equal(artifact.scopes[SCOPE_PLAN_REVIEW].posture, POSTURE_GOVERNED);
    assert.equal(
      artifact.scopes[SCOPE_RUN].posture,
      POSTURE_LIVE,
      "the run scope is 'live', never 'governed' — the gate's claim does not cover the run",
    );
  });

  test('a truncated intake downgrades the whole run even with LITREVIEW_LIVE=1', () => {
    assert.equal(truncatedStage0.status, STAGE0_STATUSES.RUN);
    assert.equal(truncatedStage0.state.truncated, true, 'the TRUNCATED stamp survived the HALT boundary');

    const artifact = resolveComposedPosture({
      claims: claimsFor(truncatedStage0),
      env: { LITREVIEW_LIVE: '1' },
    });
    assert.equal(artifact.runStamp, POSTURE_DEGRADED, 'any degraded component downgrades the run');
    assert.equal(artifact.scopes[SCOPE_INTAKE].posture, POSTURE_DEGRADED);
    assert.equal(artifact.scopes[SCOPE_PLAN_REVIEW].posture, POSTURE_GOVERNED, 'scoped governed claim survives');
    assert.ok(artifact.degradedReasons.some((r) => r.startsWith(`${SCOPE_INTAKE}:`)));
    assert.equal(assertPostureInvariant(artifact), true);
  });

  test("acceptance GWT: no artifact presents 'governed' and 'degraded' at the SAME scope", () => {
    // Composition: a degraded claim at the plan-review scope displaces the governed
    // claim entirely — one winner per scope, the loser's reasons dropped.
    const artifact = resolveComposedPosture({
      claims: [
        ...claimsFor(governedStage0),
        claim(SCOPE_PLAN_REVIEW, POSTURE_DEGRADED, 'governance record could not be verified'),
      ],
      env: { LITREVIEW_LIVE: '1' },
    });
    assert.equal(artifact.scopes[SCOPE_PLAN_REVIEW].posture, POSTURE_DEGRADED);
    assert.equal(
      JSON.stringify(artifact.scopes[SCOPE_PLAN_REVIEW]).includes(POSTURE_GOVERNED),
      false,
      'the displaced governed claim is dropped, never co-presented',
    );
    assert.equal(artifact.runStamp, POSTURE_DEGRADED);

    // Every scope of every composed artifact resolves to exactly ONE posture.
    for (const a of [
      artifact,
      resolveComposedPosture({ claims: claimsFor(governedStage0), env: {} }),
      resolveComposedPosture({ claims: claimsFor(truncatedStage0), env: { LITREVIEW_LIVE: '1' } }),
    ]) {
      for (const [scope, entry] of Object.entries(a.scopes)) {
        assert.deepStrictEqual(
          Object.keys(entry).sort(),
          ['posture', 'reasons'],
          `scope "${scope}" resolves to a single posture entry`,
        );
      }
      assert.equal(assertPostureInvariant(a), true);
    }

    // A hand-built dual/dishonest claim is rejected by the invariant, not tolerated.
    assert.throws(
      () => resolveComposedPosture({ claims: [claim(SCOPE_RUN, POSTURE_GOVERNED)], env: {} }),
      (err) => err instanceof PostureError && /plan-review governance ONLY/.test(err.message),
    );
    assert.throws(
      () =>
        assertPostureInvariant({
          runStamp: POSTURE_GOVERNED,
          liveSeatsBound: false,
          scopes: { [SCOPE_RUN]: { posture: POSTURE_GOVERNED, reasons: [] } },
          degradedReasons: [],
        }),
      (err) => err instanceof PostureError && /never/.test(err.message),
    );
  });
});
