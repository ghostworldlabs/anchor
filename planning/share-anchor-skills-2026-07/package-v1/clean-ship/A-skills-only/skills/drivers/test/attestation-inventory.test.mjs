// drivers/test/attestation-inventory.test.mjs — Phase 1.2 done-when (c): the spawn-site
// attestation inventory. Two guarantees:
//   1. Every model-spawning driver PARSER yields a well-formed SR-5 stamp from a known
//      envelope (claude + gemini-cli), so the stamp is real, not aspirational.
//   2. Every SOURCE FILE that spawns a model sub-agent (`spawn('claude'…)` /
//      `spawn('gemini'…)`) also produces the SR-5 stamp — so no spawn site can be added
//      that bypasses attestation. This is the "every agent() call routes through an
//      attesting wrapper" guard.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { hasAttestation } from '../attest.mjs';
import { parseClaudeFrames } from '../claude.mjs';
import { parseGeminiCliFrames } from '../gemini-cli.mjs';

const TRIO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SKIP_DIRS = new Set(['node_modules', '.git', '.foreman', 'test']);
// A model sub-agent spawn, in any of the forms the live drivers actually use — each
// launches a real backend child and so must attest:
//   (1) direct literal `spawn('claude'|'gemini'…)` transports;
//   (2) the Wave-7 guarded form `spawnGuarded({ command: <…> 'claude.exe' })` in
//       run-live.mjs (the command may be a ternary, e.g. `isWin ? 'claude.exe' : 'claude'`);
//   (3) W0/W1 (2026-07-05): the live claude.mjs + gemini-cli.mjs drivers spawn via a
//       `const cmdName = <ternary> 'agy.exe'|'claude.exe'` variable (so a raw `spawn('agy'…)`
//       literal never appears) — the scan must recognize that cmdName assignment, including
//       the agy (Antigravity CLI) backend, or those two live spawn sites slip past the guard.
// NB: `agy` is matched ONLY in the cmdName/command forms the attesting drivers use, NOT as a
// bare `spawn('agy'…)` literal — that keeps the guard focused on the real backend spawn sites
// without weakening it to always-pass.
const SPAWN_RE = new RegExp([
  /spawn\(\s*['"](?:claude|gemini)['"]/.source,
  /command:\s*[^,\n]*['"](?:claude|gemini|agy)(?:\.exe)?['"]/.source,
  /cmdName\s*=\s*[^;\n]*['"](?:claude|gemini|agy)(?:\.exe)?['"]/.source,
].join('|'));
// The file produces an SR-5 stamp — directly (attestStamp/model_attested) or via the
// Wave-7 telemetry builder (makeTelemetryRecord folds the SR-5 stamp in).
const ATTEST_MARKER = /model_attested|attestStamp|makeTelemetryRecord/;

function walk(dir, hit) {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.isDirectory()) { if (!SKIP_DIRS.has(ent.name)) walk(path.join(dir, ent.name), hit); }
    else if (ent.name.endsWith('.mjs') || ent.name.endsWith('.js')) hit(path.join(dir, ent.name));
  }
}

test('parser inventory: claude + gemini-cli parsers both emit a well-formed SR-5 stamp', () => {
  const claude = parseClaudeFrames(
    [JSON.stringify({ type: 'result', is_error: false, result: 'ok', model: 'claude-opus-4-8' })].join('\n'),
    { label: 'x' },
  ).rec;
  assert.equal(hasAttestation(claude), true);
  assert.equal(claude.model_attested, true);

  // W0 (2026-07-05): the served model is attested from agy's cli.log, not a stream-json
  // `stats.models` envelope. Feed the live signature — a clean serve of a KNOWN agy LABEL
  // (served===requested, not substituted) — and assert the well-formed attested stamp.
  const gemini = parseGeminiCliFrames('PONG', {
    label: 'x', cli_status: 0,
    requested_model: 'Gemini 3.1 Pro (High)',
    served_model: 'Gemini 3.1 Pro (High)', substituted: false,
  }).rec;
  assert.equal(hasAttestation(gemini), true);
  assert.equal(gemini.model_attested, true);
});

test('spawn-site inventory: every model-spawn source file also produces an SR-5 stamp', () => {
  const spawnSites = [];
  const uncovered = [];
  walk(TRIO_ROOT, (file) => {
    const src = fs.readFileSync(file, 'utf8');
    if (SPAWN_RE.test(src)) {
      spawnSites.push(file);
      if (!ATTEST_MARKER.test(src)) uncovered.push(file);
    }
  });
  // Sanity: the known live spawn sites are present (so the scan isn't vacuously empty).
  assert.ok(spawnSites.length >= 3, `expected >=3 model-spawn sites, found ${spawnSites.length}`);
  assert.deepEqual(uncovered, [], `spawn sites missing SR-5 attestation: ${JSON.stringify(uncovered, null, 2)}`);
});
