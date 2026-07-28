#!/usr/bin/env node
// bin/intake.mjs — Wave 4 Stage-0 triage emission
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import readline from 'node:readline/promises';
import { fileURLToPath } from 'node:url';
import { HaltError } from './trio-core/contract-core.mjs';

/**
 * Perform intake, durably emit the Stage-0 triage artifact, and then prompt the human.
 * @param {object} inputs The intake data.
 * @param {object} options
 * @param {string} options.runDir Directory to write the artifact to.
 * @param {function} options.promptHuman Async function to prompt the human (returns 'APPROVE', 'EDIT', or 'ABORT').
 * @param {function} options.onBeforePrompt Optional callback before the prompt (used for testing crash-before-prompt).
 * @returns {Promise<{ artifactPath, triageHash, decision }>}
 */
export async function runIntake(inputs, { runDir, promptHuman, onBeforePrompt } = {}) {
  const triageData = {
    inputs,
    timestamp: new Date().toISOString()
  };

  const triageStr = JSON.stringify(triageData, null, 2);
  const triageHashStr = JSON.stringify({ inputs }, null, 2);
  const triageHash = crypto.createHash('sha256').update(triageHashStr).digest('hex');
  
  fs.mkdirSync(runDir, { recursive: true });
  const artifactPath = path.join(runDir, `triage-${triageHash}.json`);
  
  // Durably write the artifact BEFORE any prompt
  fs.writeFileSync(artifactPath, triageStr, 'utf8');

  if (onBeforePrompt) {
    await onBeforePrompt({ artifactPath, triageHash });
  }

  let decision = 'ABORT';
  if (promptHuman) {
    decision = await promptHuman({ artifactPath, triageHash });
  } else {
    // Default interactive prompt
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const answer = await rl.question(`Triage artifact written to ${artifactPath} (hash: ${triageHash}).\nGate 1 Decision (APPROVE, EDIT, ABORT)? `);
    rl.close();
    decision = answer.trim().toUpperCase();
    if (!['APPROVE', 'EDIT', 'ABORT'].includes(decision)) {
       decision = 'ABORT';
    }
  }

  // Triage-artifact hashing feeding the canonical governance record (partial record for Gate 1)
  const governanceRecord = {
    triageHash,
    gate1Decision: decision
  };
  fs.writeFileSync(path.join(runDir, 'gate1-record.json'), JSON.stringify(governanceRecord, null, 2), 'utf8');

  if (decision === 'ABORT') {
    throw new HaltError(`Run halted at Gate 1 with decision ABORT (Artifact: ${triageHash})`);
  }

  return { artifactPath, triageHash, decision };
}

function invokedDirectly() {
  const entry = process.argv[1];
  if (!entry) return false;
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(entry); } catch { return false; }
}

if (invokedDirectly()) {
  const runDir = process.argv[2] || process.cwd();
  // Collect stdin for inputs in a real scenario, but for now just mock it
  const inputs = { note: 'interactive intake' };
  runIntake(inputs, { runDir }).then(res => {
      console.log('Intake complete:', res);
  }).catch(err => {
      if (err instanceof HaltError) {
        console.error(err.message);
        process.exit(1);
      }
      console.error(err);
      process.exit(2);
  });
}
