import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { deriveGovernorContract } from './formal-governor.mjs';

/**
 * Reads legacy run data from a path and returns the inputs for the governor 
 * along with the expected legacy output (round count, bounds, etc.)
 */
export function parseLegacyRun(runPath) {
  const legacyFile = path.join(runPath, 'legacy-baseline.json');
  if (fs.existsSync(legacyFile)) {
    const legacyData = JSON.parse(fs.readFileSync(legacyFile, 'utf8'));
    return {
      inputs: legacyData.inputs || {},
      legacyOutput: legacyData.expectedOutput || {}
    };
  }
  throw new Error(`No legacy-baseline.json found in ${runPath}`);
}

/**
 * Replays runs through the governor and compares against the legacy output.
 */
export function calibrateShadow(runPaths) {
  const report = {
    totalRuns: 0,
    matchingRuns: 0,
    differingRuns: 0,
    diffs: {}
  };

  for (const runPath of runPaths) {
    report.totalRuns++;
    let legacyRun;
    try {
      legacyRun = parseLegacyRun(runPath);
    } catch (err) {
      report.diffs[runPath] = { error: err.message };
      report.differingRuns++;
      continue;
    }

    const { inputs, legacyOutput } = legacyRun;
    const contract = deriveGovernorContract(inputs);

    const differences = [];

    if (contract.roundBudget !== legacyOutput.roundBudget) {
      differences.push({
        field: 'roundBudget',
        legacy: legacyOutput.roundBudget,
        governor: contract.roundBudget
      });
    }

    if (legacyOutput.thresholds) {
      for (const [key, value] of Object.entries(legacyOutput.thresholds)) {
        if (contract.thresholds[key] !== value) {
          differences.push({
            field: `thresholds.${key}`,
            legacy: value,
            governor: contract.thresholds[key]
          });
        }
      }
    }
    
    if (legacyOutput.bounds) {
       for (const [key, value] of Object.entries(legacyOutput.bounds)) {
        if (contract.bounds[key] !== value) {
          differences.push({
            field: `bounds.${key}`,
            legacy: value,
            governor: contract.bounds[key]
          });
        }
      }
    }

    if (differences.length === 0) {
      report.matchingRuns++;
    } else {
      report.differingRuns++;
      report.diffs[runPath] = differences;
    }
  }

  return report;
}

if (import.meta.url.startsWith('file:')) {
  const modulePath = fileURLToPath(import.meta.url);
  if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(modulePath)) {
    const runPaths = process.argv.slice(2);
    if (runPaths.length === 0) {
      console.error('Usage: node calibrate-shadow.mjs <runPath1> <runPath2> ...');
      process.exit(1);
    }
    const report = calibrateShadow(runPaths);
    console.log(JSON.stringify(report, null, 2));
  }
}
