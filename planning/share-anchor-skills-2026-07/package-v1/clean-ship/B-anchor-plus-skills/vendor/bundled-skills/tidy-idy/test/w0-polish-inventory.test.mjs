// W0 polish inventory stamps — exercises engine/panel/w0-polish-stamps.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  W0_POLISH_STAMPS,
  assertW0ProjectionOnly,
} from '../engine/panel/w0-polish-stamps.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const skillRoot = path.resolve(__dirname, '..');

test('W0 stamps: SC2 GO, SC4 Option 1, no panel edits', () => {
  assert.equal(W0_POLISH_STAMPS.sc2FieldReadiness, 'GO');
  assert.equal(W0_POLISH_STAMPS.sc4Option, 1);
  assert.equal(W0_POLISH_STAMPS.productionPanelEditsInW0, false);
  assert.equal(W0_POLISH_STAMPS.baselineStatus, 'GREEN');
  assert.ok(assertW0ProjectionOnly());
});

test('W0 pointer inventory exists under skill docs', () => {
  const p = path.join(skillRoot, 'docs', 'w0-polish-inventory.md');
  assert.ok(fs.existsSync(p), 'docs/w0-polish-inventory.md');
  const body = fs.readFileSync(p, 'utf8');
  assert.match(body, /SC2 field-readiness/i);
  assert.match(body, /\*\*GO\*\*/);
  assert.match(body, /SC4 Option/i);
  assert.match(body, /Baseline/i);
  assert.match(body, /\*\*GREEN\*\*/);
});

test('W0 deny list pins apply/** and lock-authority', () => {
  assert.ok(W0_POLISH_STAMPS.denyPaths.some((d) => d.includes('engine/apply')));
  assert.ok(W0_POLISH_STAMPS.denyPaths.some((d) => d.includes('lock-authority')));
});

test('W0 baseline note records orchestrator GREEN handoff', () => {
  const note = W0_POLISH_STAMPS.baselineNote;
  assert.ok(note && fs.existsSync(note), 'baseline note path exists');
  const body = fs.readFileSync(note, 'utf8');
  assert.match(body, /ORCHESTRATOR_BASELINE_STATUS:\s*GREEN/);
  assert.match(body, /exit:\s*0/);
  assert.match(body, /skipped_sc3_oracles:\s*0/);
  const gateRel = W0_POLISH_STAMPS.baselineGateArtifact;
  assert.ok(gateRel, 'baselineGateArtifact set');
  const gateAbs = path.join(skillRoot, gateRel);
  assert.ok(fs.existsSync(gateAbs), 'orchestrator gate artifact present');
  const gate = JSON.parse(fs.readFileSync(gateAbs, 'utf8'));
  assert.equal(gate.written_by, 'orchestrator');
  assert.equal(gate.exit_code, 0);
  assert.equal(gate.green, true);
});
