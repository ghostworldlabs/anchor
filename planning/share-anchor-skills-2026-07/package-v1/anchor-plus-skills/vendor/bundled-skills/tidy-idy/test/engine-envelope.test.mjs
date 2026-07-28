// test/engine-envelope.test.mjs — Wave 1: the stage/run envelope contract.
//
// The two properties the plan makes load-bearing:
//   • terminal run state = WORST stage status;
//   • celebratory-clean is STRUCTURALLY unreachable — isClean requires every
//     stage ok with complete coverage, and there is no findings-count path to it.

import { test, describe } from 'node:test';
import assert from 'node:assert';

import { STATUS, worstStatus, coverageComplete, makeStageResult, failedStage, makeRunEnvelope } from '../engine/envelope.mjs';

const okStage = (name, findings = []) => makeStageResult({
  stage: name, status: STATUS.OK, coverage: { scanned: 3, skipped: 0, errored: 0 }, findings,
});

describe('worstStatus', () => {
  test('empty list is ok', () => assert.strictEqual(worstStatus([]), STATUS.OK));
  test('ok + partial = partial', () => assert.strictEqual(worstStatus(['ok', 'partial', 'ok']), 'partial'));
  test('partial + failed = failed', () => assert.strictEqual(worstStatus(['partial', 'failed', 'ok']), 'failed'));
  test('one failed among many ok = failed (no averaging)', () => {
    assert.strictEqual(worstStatus(['ok', 'ok', 'ok', 'ok', 'failed']), 'failed');
  });
  test('an unknown status is rejected, not coerced', () => {
    assert.throws(() => worstStatus(['ok', 'mostly-fine']), /unknown stage status/);
  });
});

describe('coverage', () => {
  test('complete means nothing skipped and nothing errored', () => {
    assert.strictEqual(coverageComplete({ scanned: 10, skipped: 0, errored: 0 }), true);
    assert.strictEqual(coverageComplete({ scanned: 10, skipped: 1, errored: 0 }), false);
    assert.strictEqual(coverageComplete({ scanned: 10, skipped: 0, errored: 1 }), false);
    assert.strictEqual(coverageComplete(null), false);
  });

  test('a stage cannot report ok while carrying errors', () => {
    assert.throws(
      () => makeStageResult({ stage: 'x', status: STATUS.OK, errors: [{ message: 'boom' }] }),
      /never ok/,
      'ok-with-errors is the fake-clean failure mode in miniature and the contract must reject it');
  });
});

describe('isClean is structurally unreachable except in the genuinely clean case', () => {
  const base = {
    runId: 'r1', rootPath: '/tmp/x', mode: 'north-star', ruleset: { version: 'rs1-test' }, reportDir: '/tmp/x/.tidy-idy',
  };

  test('all stages ok, complete coverage, zero findings → clean', () => {
    const env = makeRunEnvelope({ ...base, stages: [okStage('scan'), okStage('debate')] });
    assert.strictEqual(env.isClean, true);
    assert.strictEqual(env.status, STATUS.OK);
    assert.deepStrictEqual(env.cleanBlockers, []);
  });

  test('a FAILED stage can never be clean, even with zero findings', () => {
    const env = makeRunEnvelope({ ...base, stages: [okStage('scan'), failedStage('analyze', new Error('the analysis did NOT run'))] });
    assert.strictEqual(env.isClean, false);
    assert.strictEqual(env.status, STATUS.FAILED);
    assert.ok(env.cleanBlockers.some((b) => /analyze=failed/.test(b)));
  });

  test('INCOMPLETE COVERAGE can never be clean, even with all stages ok and zero findings', () => {
    const partiallyCovered = makeStageResult({
      stage: 'scan', status: STATUS.OK, coverage: { scanned: 1, skipped: 9, errored: 0 },
    });
    const env = makeRunEnvelope({ ...base, stages: [partiallyCovered] });
    assert.strictEqual(env.isClean, false, 'a run that looked at 1 of 10 files is not a clean project');
    assert.ok(env.cleanBlockers.some((b) => /incomplete coverage/.test(b)));
  });

  test('a tripwire violation can never be clean', () => {
    const env = makeRunEnvelope({
      ...base,
      stages: [okStage('scan')],
      tripwire: { violations: [{ op: 'writeFile', target: '/tmp/x/a', stage: 'scan' }], spawns: [] },
    });
    assert.strictEqual(env.isClean, false);
    assert.ok(env.cleanBlockers.some((b) => /tripwire/.test(b)));
  });

  test('no stages at all is not clean (an empty run is not a clean run)', () => {
    const env = makeRunEnvelope({ ...base, stages: [] });
    assert.strictEqual(env.isClean, false);
    assert.ok(env.cleanBlockers.some((b) => /no stages ran/.test(b)));
  });

  test('findings block clean — and clean is never derived FROM the findings count', () => {
    const env = makeRunEnvelope({ ...base, stages: [okStage('debate', [{ action: 'remove', path: 'a.txt' }])] });
    assert.strictEqual(env.isClean, false);
    // The inverse is the important half: zero findings alone does not buy clean.
    const bad = makeRunEnvelope({ ...base, stages: [failedStage('debate', new Error('x'))] });
    assert.strictEqual(bad.findings.length, 0);
    assert.strictEqual(bad.isClean, false);
  });
});
