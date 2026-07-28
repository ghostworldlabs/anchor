/**
 * Adversarial verification harness — sleep 0076 packages (outside Foreman loop).
 * Standalone (not via node --test) so it can cross-import Crucible Stage-2.
 *
 *   node test/adv-sleep-0076-outside-harness.mjs
 *   (cwd: <path>
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';

const FOREMAN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TRIO = path.resolve(FOREMAN, '..');
const u = (abs) => pathToFileURL(abs).href;

const { extractWaveSection, _internals: wf } = await import(u(path.join(FOREMAN, 'bin/wave-workflow.js')));
const {
  writeWaveProvenLedger,
  readWaveProvenLedger,
  creditPriorWaveAttempt,
  isRuntimeNoisePath,
  isProvenDeliverablePath,
  _internals: we,
} = await import(u(path.join(FOREMAN, 'bin/wave-engine.mjs')));
const { clearHaltedCheckpoint } = await import(u(path.join(FOREMAN, 'bin/project-engine.mjs')));
const {
  newCheckpoint,
  writeCheckpointAtomic,
  preflightTestCommand,
  HaltError,
} = await import(u(path.join(FOREMAN, 'bin/foreman-lib.mjs')));
const s2 = await import(u(path.join(TRIO, 'crucible/bin/stage2.mjs')));

const failures = [];
function check(name, fn) {
  try {
    fn();
    console.log('PASS', name);
  } catch (e) {
    failures.push(`${name}: ${e.message}`);
    console.log('FAIL', name, e.message);
  }
}

check('extract last wave', () => {
  const p = '## Wave 1 — A\nbody1\n\n## Wave 2 — B\n**done-when:** z\n';
  assert.match(extractWaveSection(p, 2), /done-when/);
  assert.equal(extractWaveSection(p, 9), '');
});

check('extract Sprint heading', () => {
  const p = '## Sprint 3 — S\n**Deliverables:** s.mjs\n';
  assert.match(extractWaveSection(p, 3), /s\.mjs/);
});

check('extract Section heading + no bleed', () => {
  const p = [
    '## Section 1 — One',
    '**Deliverables:** one.mjs',
    '',
    '## Section 2 — Two',
    '**Deliverables:** two.mjs',
    '',
  ].join('\n');
  const s1 = extractWaveSection(p, 1);
  assert.match(s1, /one\.mjs/);
  assert.ok(!s1.includes('two.mjs'));
});

check('executePrompt has contract + gate + vacuous warn', () => {
  const prompt = wf.executePrompt({
    projectDir: 'P',
    planPath: 'P/PLAN.md',
    planText: '## Wave 1 — W\n**Deliverables:** a.mjs\n**done-when:** ok\n',
    testCommand: 'node scripts/run-all-tests.mjs',
    wave: { n: 1, title: 'W' },
  });
  assert.match(prompt, /BEGIN WAVE CONTRACT/);
  assert.match(prompt, /a\.mjs/);
  assert.match(prompt, /ORCHESTRATOR GATE/);
  assert.match(prompt, /vacuous-GREEN/);
});

check('executePrompt missing wave warns', () => {
  const prompt = wf.executePrompt({
    projectDir: 'P',
    planText: '## Wave 9 — Only\nx\n',
    testCommand: 't',
    wave: { n: 1, title: 'W' },
  });
  assert.match(prompt, /WARNING: could not extract/);
  assert.ok(!prompt.includes('BEGIN WAVE CONTRACT'));
});

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'adv-clear-'));
const cpPath = path.join(dir, 'cp.json');
function halt(action) {
  const cp = newCheckpoint({ plan_path: '/p', total_waves: 2 });
  cp.status = 'halted';
  cp.current_wave = 1;
  cp.iteration = 2;
  cp.pending_action = action;
  writeCheckpointAtomic(cpPath, cp);
}

check('vacuous refuse', () => {
  halt('vacuous-GREEN HALT: empty');
  const r = clearHaltedCheckpoint(cpPath, { log: () => {} });
  assert.equal(r.cleared, false);
  assert.equal(r.refused, true);
  assert.equal(JSON.parse(fs.readFileSync(cpPath, 'utf8')).status, 'halted');
});

check('vacuous force execute', () => {
  halt('vacuous-GREEN HALT: empty');
  const r = clearHaltedCheckpoint(cpPath, { log: () => {}, force: true });
  assert.equal(r.cleared, true);
  assert.equal(r.reentry, 'execute');
  assert.equal(JSON.parse(fs.readFileSync(cpPath, 'utf8')).intra_wave_step, 'execute');
});

check('non-vacuous gate', () => {
  halt('review transport failed');
  const r = clearHaltedCheckpoint(cpPath, { log: () => {} });
  assert.equal(r.cleared, true);
  assert.equal(r.reentry, 'gate');
});

check('plan-amend execute', () => {
  halt('PLAN-AMENDMENT-PROPOSAL: expand tests');
  const r = clearHaltedCheckpoint(cpPath, { log: () => {} });
  assert.equal(r.cleared, true);
  assert.equal(r.reentry, 'execute');
});

const d2 = fs.mkdtempSync(path.join(os.tmpdir(), 'adv-led-'));
const fm = path.join(d2, '.foreman');
const proj = path.join(d2, 'proj');
fs.mkdirSync(path.join(proj, 'src'), { recursive: true });
fs.mkdirSync(path.join(proj, 'test'), { recursive: true });
fs.writeFileSync(path.join(proj, 'src', 'x.mjs'), 'export const x = 1;\n');
fs.writeFileSync(path.join(proj, 'test', 'x.test.mjs'), 'import test from "node:test";\ntest("t", () => {});\n');

check('ledger source only + no log poison', () => {
  writeWaveProvenLedger(fm, 1, { changed: ['src/x.mjs', '_foreman-status.log'] });
  assert.deepEqual(readWaveProvenLedger(fm, 1).changed, ['src/x.mjs']);
  writeWaveProvenLedger(fm, 1, { changed: ['_out-foo.log'] });
  assert.deepEqual(readWaveProvenLedger(fm, 1).changed, ['src/x.mjs']);
  assert.equal(isProvenDeliverablePath('_out-x.log'), false);
  assert.equal(isRuntimeNoisePath('_foreman-status.log'), true);
});

check('preflight bare test/', () => {
  assert.throws(
    () => preflightTestCommand({ command: 'node --test test/', source: 'plan' }),
    (e) => e instanceof HaltError,
  );
});

const d3 = fs.mkdtempSync(path.join(os.tmpdir(), 'adv-s2-'));
check('stage2 emits helper + default cmd', () => {
  assert.equal(s2.DEFAULT_TEST_COMMAND, 'node scripts/run-all-tests.mjs');
  const waves = s2.normalizeWaves([{ title: 'T', doneWhen: 'ok', deliverables: ['a.mjs'] }]);
  const trio = s2.writeDocTrio({
    outputDir: d3,
    plan: s2.renderImplementationPlan({ northStar: 'NS', waves }),
    description: s2.renderDescriptionDoc({ northStar: 'NS' }),
    executionLog: s2.renderExecutionLog({ waveCount: 1 }),
  });
  assert.ok(fs.existsSync(trio.files.run_all_tests));
  assert.match(fs.readFileSync(trio.files.plan, 'utf8'), /test-command: node scripts\/run-all-tests\.mjs/);
  assert.match(fs.readFileSync(trio.files.run_all_tests, 'utf8'), /\.test\.mjs/);
});

check('checkVacuousGreen empty still HALTs', () => {
  const reason = we.checkVacuousGreen(proj, fm, [], { waveTitle: 'Wave 1' });
  assert.ok(
    reason && /no source|no deliverable|vacuous|empty|doc\/data|not prove|no code/i.test(String(reason)),
    `expected vacuous reason, got: ${reason}`,
  );
});

check('creditPriorWaveAttempt filters log ledger', () => {
  fs.mkdirSync(fm, { recursive: true });
  fs.writeFileSync(
    path.join(fm, 'wave-9-proven.json'),
    JSON.stringify({ version: 1, wave: 9, changed: ['_foreman-status.log'] }) + '\n',
  );
  const r = creditPriorWaveAttempt(proj, fm, 9, {
    reach: new Set(),
    exercisedByName: () => true,
  });
  assert.equal(r.ok, false);
});

check('run-live always injects agent (static)', () => {
  const src = fs.readFileSync(path.join(FOREMAN, 'bin/run-live.mjs'), 'utf8');
  assert.match(src, /ALWAYS inject the instrumented `agent`/i);
  assert.match(src, /makeForemanDriver\(\{\s*agent,\s*log:/);
  assert.ok(!/TRIO_DRIVER\s*\?\s*\{\s*log/.test(src), 'old ternary branch must be gone');
});

check('changedSince ignores runtime noise', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'adv-hash-'));
  const fman = path.join(root, '.foreman');
  fs.mkdirSync(path.join(root, 'src'), { recursive: true });
  fs.mkdirSync(fman, { recursive: true });
  fs.writeFileSync(path.join(root, 'src', 'a.mjs'), 'export const a = 1;\n');
  const start = we.snapshotHashes(root, fman);
  fs.writeFileSync(path.join(root, '_foreman-status.log'), 'tick\n');
  fs.writeFileSync(path.join(root, '_out-20260723.log'), 'noise\n');
  fs.writeFileSync(path.join(root, 'src', 'a.mjs'), 'export const a = 2;\n');
  const ch = we.changedSince(root, fman, start);
  assert.ok(ch.includes('src/a.mjs'));
  assert.ok(!ch.some((f) => f.includes('_foreman') || f.includes('_out-')));
  fs.rmSync(root, { recursive: true, force: true });
});

for (const d of [dir, d2, d3]) {
  try {
    fs.rmSync(d, { recursive: true, force: true });
  } catch { /* ignore */ }
}

if (failures.length) {
  console.error(`\n${failures.length} FAILURES:\n${failures.join('\n')}`);
  process.exit(1);
}
console.log('\nALL ADVERSARIAL CHECKS PASSED');
