// test/posture-resolver.test.mjs — Wave 5: composed posture resolution with explicit
// precedence (src/posture-resolver.mjs).
//
// Pins the Wave-5 acceptance:
//   - any 'degraded' component downgrades the WHOLE-RUN stamp (degraded-wins precedence);
//   - the gate's 'governed' claim is scoped to plan-review governance ONLY — a governed
//     claim on any other scope (including the run) throws instead of composing;
//   - NO artifact can present 'governed' and 'degraded' at the SAME scope — each scope
//     resolves to exactly one posture, enforced both by construction (resolver output) and
//     by assertPostureInvariant against hand-forged artifacts;
//   - LITREVIEW_LIVE is honored: without --live / LITREVIEW_LIVE=1 the run stamp is
//     'degraded' with the named no-live-seats reason (bin/cli.mjs parity).

import { test, describe } from 'node:test';
import assert from 'node:assert';

import {
  resolveComposedPosture,
  assertPostureInvariant,
  renderPostureStamp,
  isLiveRun,
  claim,
  PostureError,
  POSTURES,
  POSTURE_GOVERNED,
  POSTURE_LIVE,
  POSTURE_DEGRADED,
  SCOPE_RUN,
  SCOPE_PLAN_REVIEW,
  NO_LIVE_SEATS_REASON,
} from '../src/posture-resolver.mjs';

/** Every scope resolves to exactly ONE valid posture — the no-dual-claim shape check. */
function assertOnePosturePerScope(artifact) {
  for (const [scope, entry] of Object.entries(artifact.scopes)) {
    assert.equal(typeof entry.posture, 'string', `scope "${scope}" posture must be ONE string`);
    assert.ok(POSTURES.includes(entry.posture), `scope "${scope}" posture must be a known posture`);
    assert.deepStrictEqual(
      Object.keys(entry).sort(),
      ['posture', 'reasons'],
      `scope "${scope}" must carry exactly one posture field (no second claim)`,
    );
  }
}

describe('Wave 5 — composed posture resolver (degraded-wins, scoped governed, LITREVIEW_LIVE)', () => {
  test('acceptance GWT: gate governed + intake degraded + LITREVIEW_LIVE degraded ⇒ whole-run degraded, governed scoped to plan-review only, no dual claim at any scope', () => {
    const artifact = resolveComposedPosture({
      claims: [
        claim(SCOPE_PLAN_REVIEW, POSTURE_GOVERNED, 'hash-bound governance record (plan-review gate)'),
        claim('intake', POSTURE_DEGRADED, 'brownfield intake ran without a grounded summary'),
      ],
      env: {}, // LITREVIEW_LIVE unset ⇒ degraded operation
    });

    // Whole-run stamp is degraded.
    assert.equal(artifact.runStamp, POSTURE_DEGRADED);
    assert.equal(artifact.scopes[SCOPE_RUN].posture, POSTURE_DEGRADED);

    // The 'governed' claim survives — but scoped to plan-review governance ONLY.
    assert.equal(artifact.scopes[SCOPE_PLAN_REVIEW].posture, POSTURE_GOVERNED);
    for (const [scope, entry] of Object.entries(artifact.scopes)) {
      if (scope !== SCOPE_PLAN_REVIEW) {
        assert.notEqual(entry.posture, POSTURE_GOVERNED, `'governed' must not appear at scope "${scope}"`);
      }
    }

    // No artifact carries both claims at the same scope.
    assertOnePosturePerScope(artifact);
    assert.equal(assertPostureInvariant(artifact), true);

    // Both degradation sources are named.
    assert.ok(artifact.degradedReasons.some((r) => r.startsWith('intake:')));
    assert.ok(artifact.degradedReasons.some((r) => r.includes(NO_LIVE_SEATS_REASON)));
  });

  test("degraded displaces governed at the SAME scope — the governed claim is dropped, never co-presented", () => {
    for (const order of [
      [
        claim(SCOPE_PLAN_REVIEW, POSTURE_GOVERNED, 'gate approved'),
        claim(SCOPE_PLAN_REVIEW, POSTURE_DEGRADED, 'governance record not hash-bound (non-Node prose stamp)'),
      ],
      [
        claim(SCOPE_PLAN_REVIEW, POSTURE_DEGRADED, 'governance record not hash-bound (non-Node prose stamp)'),
        claim(SCOPE_PLAN_REVIEW, POSTURE_GOVERNED, 'gate approved'),
      ],
    ]) {
      const artifact = resolveComposedPosture({ claims: order, env: { LITREVIEW_LIVE: '1' } });
      assert.equal(artifact.scopes[SCOPE_PLAN_REVIEW].posture, POSTURE_DEGRADED);
      assert.ok(
        !artifact.scopes[SCOPE_PLAN_REVIEW].reasons.includes('gate approved'),
        'the displaced governed claim must not ride along in the degraded scope entry',
      );
      assert.equal(artifact.runStamp, POSTURE_DEGRADED, 'degraded plan-review downgrades the run');
      assertOnePosturePerScope(artifact);
      // The rendered stamp never shows 'governed' anywhere for this artifact.
      assert.ok(!renderPostureStamp(artifact).includes(POSTURE_GOVERNED));
    }
  });

  test("a 'governed' claim outside plan-review governance is a dishonest claim and throws", () => {
    for (const scope of ['intake', 'extraction', SCOPE_RUN, 'synthesis']) {
      assert.throws(
        () =>
          resolveComposedPosture({
            claims: [claim(scope, POSTURE_GOVERNED, 'nope')],
            env: { LITREVIEW_LIVE: '1' },
          }),
        (err) =>
          err instanceof PostureError && /scoped to plan-review governance ONLY/.test(err.message),
        `governed@${scope} must throw`,
      );
    }
  });

  test('LITREVIEW_LIVE degraded-stamp propagation: unset/0 degrade the run with the named reason; =1 or --live yields a live stamp', () => {
    const claims = [claim(SCOPE_PLAN_REVIEW, POSTURE_GOVERNED, 'gate approved')];

    for (const env of [{}, { LITREVIEW_LIVE: '0' }, { LITREVIEW_LIVE: 'true' }]) {
      const artifact = resolveComposedPosture({ claims, env });
      assert.equal(artifact.runStamp, POSTURE_DEGRADED, `env ${JSON.stringify(env)} must degrade`);
      assert.equal(artifact.liveSeatsBound, false);
      assert.ok(artifact.degradedReasons.some((r) => r.includes(NO_LIVE_SEATS_REASON)));
      assert.ok(renderPostureStamp(artifact).includes(NO_LIVE_SEATS_REASON));
    }

    const liveEnv = resolveComposedPosture({ claims, env: { LITREVIEW_LIVE: '1' } });
    assert.equal(liveEnv.runStamp, POSTURE_LIVE);
    assert.equal(liveEnv.liveSeatsBound, true);
    assert.deepStrictEqual(liveEnv.degradedReasons, []);

    // CLI --live parity: the explicit flag binds even with the env unset.
    const liveFlag = resolveComposedPosture({ claims, live: true, env: {} });
    assert.equal(liveFlag.runStamp, POSTURE_LIVE);

    // And the run stamp is never 'governed', even when the only claim is governed.
    assert.notEqual(liveEnv.runStamp, POSTURE_GOVERNED);
    assert.equal(liveEnv.scopes[SCOPE_RUN].posture, POSTURE_LIVE);
  });

  test('degraded-wins precedence inside an ordinary scope, both claim orders', () => {
    for (const order of [
      [claim('extraction', POSTURE_LIVE, 'seats bound'), claim('extraction', POSTURE_DEGRADED, 'agy down')],
      [claim('extraction', POSTURE_DEGRADED, 'agy down'), claim('extraction', POSTURE_LIVE, 'seats bound')],
    ]) {
      const artifact = resolveComposedPosture({ claims: order, env: { LITREVIEW_LIVE: '1' } });
      assert.equal(artifact.scopes.extraction.posture, POSTURE_DEGRADED);
      assert.deepStrictEqual(artifact.scopes.extraction.reasons, ['agy down']);
      assert.equal(artifact.runStamp, POSTURE_DEGRADED);
    }
  });

  test('a component run-scope claim can never RAISE the run above the composed stamp', () => {
    const artifact = resolveComposedPosture({
      claims: [
        claim(SCOPE_RUN, POSTURE_LIVE, 'component believes all is well'),
        claim('extraction', POSTURE_DEGRADED, 'quote-grounding cache unavailable'),
      ],
      env: { LITREVIEW_LIVE: '1' },
    });
    assert.equal(artifact.runStamp, POSTURE_DEGRADED);
    assert.equal(artifact.scopes[SCOPE_RUN].posture, POSTURE_DEGRADED);
    assertOnePosturePerScope(artifact);
  });

  test('claim validation: malformed claims are refused with named reasons', () => {
    const live = { LITREVIEW_LIVE: '1' };
    assert.throws(
      () => resolveComposedPosture({ claims: 'not-an-array', env: live }),
      (err) => err instanceof PostureError && /must be an array/.test(err.message),
    );
    assert.throws(
      () => resolveComposedPosture({ claims: [null], env: live }),
      (err) => err instanceof PostureError && /must be an object/.test(err.message),
    );
    assert.throws(
      () => resolveComposedPosture({ claims: [claim('', POSTURE_LIVE)], env: live }),
      (err) => err instanceof PostureError && /has no scope/.test(err.message),
    );
    assert.throws(
      () => resolveComposedPosture({ claims: [claim('intake', 'nominal')], env: live }),
      (err) => err instanceof PostureError && /unknown posture "nominal"/.test(err.message),
    );
  });

  test('assertPostureInvariant rejects hand-forged dual/dishonest artifacts (the same-scope claim can never be presented)', () => {
    const good = {
      runStamp: POSTURE_LIVE,
      liveSeatsBound: true,
      scopes: { [SCOPE_RUN]: { posture: POSTURE_LIVE, reasons: [] } },
      degradedReasons: [],
    };
    assert.equal(assertPostureInvariant(good), true);

    const forge = (mutate) => {
      const forged = structuredClone(good);
      mutate(forged);
      return forged;
    };

    // The run stamp can never be 'governed'.
    assert.throws(
      () => assertPostureInvariant(forge((a) => (a.runStamp = POSTURE_GOVERNED))),
      (err) => err instanceof PostureError && /never covers the run/.test(err.message),
    );
    // 'governed' outside plan-review governance.
    assert.throws(
      () =>
        assertPostureInvariant(
          forge((a) => (a.scopes.intake = { posture: POSTURE_GOVERNED, reasons: [] })),
        ),
      (err) => err instanceof PostureError && /scoped to "plan-review-governance" only/.test(err.message),
    );
    // A degraded scope under a 'live' run stamp (degraded must downgrade the whole run).
    assert.throws(
      () =>
        assertPostureInvariant(
          forge((a) => (a.scopes.intake = { posture: POSTURE_DEGRADED, reasons: [] })),
        ),
      (err) => err instanceof PostureError && /downgrades the whole run/.test(err.message),
    );
    // A second posture-bearing field at one scope IS the dual claim — refused by shape.
    assert.throws(
      () =>
        assertPostureInvariant(
          forge(
            (a) =>
              (a.scopes[SCOPE_PLAN_REVIEW] = {
                posture: POSTURE_GOVERNED,
                reasons: [],
                shadowPosture: POSTURE_DEGRADED,
              }),
          ),
        ),
      (err) => err instanceof PostureError && /exactly ONE posture/.test(err.message),
    );
    // A multi-valued posture at one scope is refused too.
    assert.throws(
      () =>
        assertPostureInvariant(
          forge(
            (a) =>
              (a.scopes[SCOPE_PLAN_REVIEW] = {
                posture: [POSTURE_GOVERNED, POSTURE_DEGRADED],
                reasons: [],
              }),
          ),
        ),
      (err) => err instanceof PostureError && /unknown posture/.test(err.message),
    );
    // The run scope must agree with the run stamp.
    assert.throws(
      () => assertPostureInvariant(forge((a) => (a.scopes[SCOPE_RUN].posture = POSTURE_DEGRADED))),
      (err) => err instanceof PostureError && /contradicts the whole-run stamp/.test(err.message),
    );
    // 'live' run stamp without live seats bound is a dishonest stamp.
    assert.throws(
      () => assertPostureInvariant(forge((a) => (a.liveSeatsBound = false))),
      (err) => err instanceof PostureError && /requires live seats bound/.test(err.message),
    );
    // The run scope must exist at all.
    assert.throws(
      () => assertPostureInvariant(forge((a) => delete a.scopes[SCOPE_RUN])),
      (err) => err instanceof PostureError && /must resolve the "run" scope/.test(err.message),
    );
  });

  test('property sweep: every claim combination resolves to one posture per scope, correct run stamp, and a passing invariant', () => {
    const planReviewVariants = [
      [],
      [claim(SCOPE_PLAN_REVIEW, POSTURE_GOVERNED, 'gate approved')],
      [claim(SCOPE_PLAN_REVIEW, POSTURE_DEGRADED, 'prose stamp only')],
      [
        claim(SCOPE_PLAN_REVIEW, POSTURE_GOVERNED, 'gate approved'),
        claim(SCOPE_PLAN_REVIEW, POSTURE_DEGRADED, 'prose stamp only'),
      ],
    ];
    const intakeVariants = [null, POSTURE_LIVE, POSTURE_DEGRADED];

    for (const planReview of planReviewVariants) {
      for (const intakePosture of intakeVariants) {
        for (const liveEnv of [true, false]) {
          const claims = [...planReview];
          if (intakePosture) claims.push(claim('intake', intakePosture, 'intake component'));
          const artifact = resolveComposedPosture({
            claims,
            env: liveEnv ? { LITREVIEW_LIVE: '1' } : {},
          });

          const anyDegraded = claims.some((c) => c.posture === POSTURE_DEGRADED);
          const expectDegraded = anyDegraded || !liveEnv;
          const label = `planReview=${planReview.length} intake=${intakePosture} live=${liveEnv}`;

          assert.equal(
            artifact.runStamp,
            expectDegraded ? POSTURE_DEGRADED : POSTURE_LIVE,
            `run stamp wrong for ${label}`,
          );
          assertOnePosturePerScope(artifact);
          assert.equal(assertPostureInvariant(artifact), true, `invariant failed for ${label}`);
          for (const [scope, entry] of Object.entries(artifact.scopes)) {
            if (entry.posture === POSTURE_GOVERNED) {
              assert.equal(scope, SCOPE_PLAN_REVIEW, `governed leaked to "${scope}" (${label})`);
            }
          }
        }
      }
    }
  });

  test('purity and determinism: inputs unmutated, identical outputs, frozen artifact, byte-stable stamp', () => {
    const claims = [
      claim(SCOPE_PLAN_REVIEW, POSTURE_GOVERNED, 'gate approved'),
      claim('intake', POSTURE_DEGRADED, 'truncated corpus'),
    ];
    const env = { LITREVIEW_LIVE: '0' };
    const claimsSnapshot = structuredClone(claims);
    const envSnapshot = structuredClone(env);

    const a = resolveComposedPosture({ claims, env });
    const b = resolveComposedPosture({ claims, env });

    assert.deepStrictEqual(claims, claimsSnapshot, 'claims must not be mutated');
    assert.deepStrictEqual(env, envSnapshot, 'env must not be mutated');
    assert.deepStrictEqual(a, b, 'same inputs must resolve to the same artifact');
    assert.equal(renderPostureStamp(a), renderPostureStamp(b), 'stamp must be byte-stable');
    assert.ok(Object.isFrozen(a) && Object.isFrozen(a.scopes), 'artifact must be deep-frozen');
    assert.throws(() => {
      a.runStamp = POSTURE_LIVE;
    }, TypeError);

    // Stamp shape: run line leads; every other scope appears exactly once; the governed
    // line is annotated with its scope limit.
    const stamp = renderPostureStamp(a);
    const lines = stamp.split('\n');
    assert.ok(lines[0].startsWith(`POSTURE: ${POSTURE_DEGRADED} (whole-run)`));
    assert.equal(lines.filter((l) => l.startsWith(`- ${SCOPE_PLAN_REVIEW}:`)).length, 1);
    assert.ok(stamp.includes('(scoped to plan-review governance only)'));
  });

  test('isLiveRun pins the exact bin/cli.mjs convention', () => {
    assert.equal(isLiveRun({ env: {} }), false);
    assert.equal(isLiveRun({ env: { LITREVIEW_LIVE: '1' } }), true);
    assert.equal(isLiveRun({ env: { LITREVIEW_LIVE: '0' } }), false);
    assert.equal(isLiveRun({ env: { LITREVIEW_LIVE: 'true' } }), false, 'only the exact string "1" binds');
    assert.equal(isLiveRun({ live: true, env: {} }), true);
    assert.equal(isLiveRun({ live: false, env: {} }), false);
  });
});
