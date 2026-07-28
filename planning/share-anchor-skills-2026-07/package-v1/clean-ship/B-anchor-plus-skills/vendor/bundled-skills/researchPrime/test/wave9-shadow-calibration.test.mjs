import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { calibrateShadow } from '../bin/calibrate-shadow.mjs';

describe('Wave 9 — Shadow-mode calibration tooling', () => {
  let tempDir;

  before(() => {
    tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'rp-w9-'));
  });

  after(() => {
    fs.rmSync(tempDir, { recursive: true, force: true });
  });

  test('Generates a clean shadow-diff report with zero differences for mock matching baseline data', () => {
    const matchingDir = path.join(tempDir, 'matching-run');
    fs.mkdirSync(matchingDir, { recursive: true });

    // Mock a matching run
    const legacyData = {
      inputs: {
        maxRounds: 5,
        preregThresholds: { N: 1, K: 2, M: 3 }
      },
      expectedOutput: {
        roundBudget: 5,
        thresholds: { N: 1, K: 2, M: 3 }
      }
    };
    fs.writeFileSync(path.join(matchingDir, 'legacy-baseline.json'), JSON.stringify(legacyData));

    const report = calibrateShadow([matchingDir]);

    assert.equal(report.totalRuns, 1);
    assert.equal(report.matchingRuns, 1);
    assert.equal(report.differingRuns, 0);
    assert.deepEqual(report.diffs, {});
  });

  test('Correctly identifies and reports the exact differences for mock non-matching baseline data', () => {
    const differingDir = path.join(tempDir, 'differing-run');
    fs.mkdirSync(differingDir, { recursive: true });

    // Mock a differing run
    const legacyData = {
      inputs: {
        maxRounds: 5,
        preregThresholds: { N: 1, K: 2, M: 3 }
      },
      expectedOutput: {
        roundBudget: 8, // legacy expected 8, but inputs say 5
        thresholds: { N: 5, K: 2, M: 3 } // legacy expected N=5, governor will output N=1
      }
    };
    fs.writeFileSync(path.join(differingDir, 'legacy-baseline.json'), JSON.stringify(legacyData));

    const report = calibrateShadow([differingDir]);

    assert.equal(report.totalRuns, 1);
    assert.equal(report.matchingRuns, 0);
    assert.equal(report.differingRuns, 1);

    const runDiffs = report.diffs[differingDir];
    assert.ok(runDiffs);
    assert.equal(runDiffs.length, 2);

    const roundDiff = runDiffs.find(d => d.field === 'roundBudget');
    assert.equal(roundDiff.legacy, 8);
    assert.equal(roundDiff.governor, 5);

    const thresholdDiff = runDiffs.find(d => d.field === 'thresholds.N');
    assert.equal(thresholdDiff.legacy, 5);
    assert.equal(thresholdDiff.governor, 1);
  });
});
