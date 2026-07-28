// test/docs.test.mjs — Wave 10 gate for the docs & version-control layer.
//
// Drives bin/docs.mjs and proves the done-when: the CORE living-doc set generates
// correctly (CLAUDE.md/CLAUDE_hist split, MADR/DACI DECISION-LOG, GRASSCATCHER, the
// plans/{intake,proto,debates,research}/ tree) AND the OPTIONAL docs (RTM.md, viz/,
// SUMMARY.md) appear ONLY when the flag is set (default OFF). Plus the maintain path:
// append-only inserts into the two logs never edit an existing row.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { HaltError } from '../bin/crucible-lib.mjs';
import {
  CORE_DOC_FILENAMES,
  OPTIONAL_DOC_FILENAMES,
  PLANS_SUBDIRS,
  VIZ_DIR,
  VIZ_DEPENDENCY_FILE,
  renderClaudeMd,
  renderClaudeHist,
  renderDecisionLog,
  renderGrasscatcher,
  renderRTM,
  renderMermaidDependency,
  renderSummary,
  writeDocSet,
  appendDecision,
  appendGrasscatcherItem,
} from '../bin/docs.mjs';

const NORTH_STAR = 'DOCS-NS-SENTINEL: a planned project carries a living-doc set under git.';
const PROJECT = 'Acme Widget';

function mkdir(tag) {
  return fs.mkdtempSync(path.join(os.tmpdir(), `crucible-w10-${tag}-`));
}

// --- (1) the sharp / history split -----------------------------------------

test('renderClaudeMd is the SHARP doc (embeds the North Star, points to the history file)', () => {
  const md = renderClaudeMd({
    projectName: PROJECT,
    northStar: NORTH_STAR,
    whatItIs: 'a widget',
    keyFiles: ['bin/x.mjs — the engine'],
    standingRules: ['production-only'],
  });
  assert.match(md, /# CLAUDE\.md — Acme Widget/);
  assert.match(md, /DOCS-NS-SENTINEL/, 'the North Star is embedded');
  assert.match(md, /CLAUDE_hist\.md/, 'points at the history doc (the §12 split)');
  assert.match(md, /bin\/x\.mjs — the engine/);
  assert.match(md, /production-only/);
});

test('renderClaudeHist is newest-first dated history (empty-safe)', () => {
  const empty = renderClaudeHist({ projectName: PROJECT });
  assert.match(empty, /no history entries yet/);
  const md = renderClaudeHist({ projectName: PROJECT, entries: [{ date: '2026-06-05', note: 'locked the North Star' }] });
  assert.match(md, /## 2026-06-05/);
  assert.match(md, /locked the North Star/);
});

// --- (2) MADR/DACI decision log --------------------------------------------

test('renderDecisionLog emits an append-only MADR/DACI table with a named Approver', () => {
  const md = renderDecisionLog({
    projectName: PROJECT,
    decisions: [{ id: 'D1', date: '2026-06-05', decision: 'use a | pipe', approver: 'John', status: 'Accepted' }],
  });
  assert.match(md, /Append-only; supersede, do not edit/);
  assert.match(md, /\| # \| Date \| Decision \| Approver \| Status \|/);
  assert.match(md, /\| D1 \| 2026-06-05 \| use a \\\| pipe \| John \| Accepted \|/, 'cell pipes are escaped');
});

// --- (3) grasscatcher -------------------------------------------------------

test('renderGrasscatcher emits the backlog table and excludes refinement ideas by doc convention', () => {
  const md = renderGrasscatcher({
    projectName: PROJECT,
    items: [{ n: 1, date: '2026-06-05', idea: 'a viz suite', origin: 'round-1', why: 'altitude', home: 'v2', status: 'parked' }],
  });
  assert.match(md, /Nothing good is dropped/);
  assert.match(md, /Refinement ideas do NOT go here/);
  assert.match(md, /\| 1 \| 2026-06-05 \| a viz suite \| round-1 \| altitude \| v2 \| parked \|/);
});

// --- (4) optional renderers -------------------------------------------------

test('renderRTM maps criterion → waves → tests; renderMermaidDependency draws resolved edges only', () => {
  const rtm = renderRTM({ projectName: PROJECT, rows: [{ criterion: 'C1', waves: [1, 2], tests: ['a.test.mjs'] }] });
  assert.match(rtm, /Requirements Traceability Matrix/);
  assert.match(rtm, /\| C1 \| 1, 2 \| a\.test\.mjs \|/);

  const mmd = renderMermaidDependency({
    waves: [
      { n: 1, title: 'Engine', dependsOn: null },
      { n: 2, title: 'Docs', dependsOn: 'Engine' },
      { n: 3, title: 'Loose', dependsOn: 'Nonexistent' }, // unresolved → no edge
    ],
  });
  assert.match(mmd, /^graph TD$/m);
  assert.match(mmd, /W1\["Wave 1 — Engine"\]/);
  assert.match(mmd, /W1 --> W2/, 'a resolved dependency draws an edge');
  assert.doesNotMatch(mmd, /--> W3/, 'an unresolved dependency draws no edge');
});

test('renderSummary embeds the North Star and success criteria', () => {
  const md = renderSummary({ projectName: PROJECT, northStar: NORTH_STAR, elevatorPitch: 'widgets, faster', criteria: ['ship it'] });
  assert.match(md, /DOCS-NS-SENTINEL/);
  assert.match(md, /widgets, faster/);
  assert.match(md, /- ship it/);
});

// --- (5) THE done-when: core always; optional only on the flag --------------

test('done-when: writeDocSet generates the CORE set + plans tree and OMITS the optional docs by default', () => {
  const dir = mkdir('core');
  try {
    const out = writeDocSet({ outputDir: dir, projectName: PROJECT, northStar: NORTH_STAR });

    // Every core doc exists.
    for (const role of Object.keys(CORE_DOC_FILENAMES)) {
      assert.ok(fs.existsSync(out.core[role]), `${role} written`);
    }
    assert.ok(fs.existsSync(path.join(dir, CORE_DOC_FILENAMES.claude)));
    assert.match(fs.readFileSync(out.core.claude, 'utf8'), /DOCS-NS-SENTINEL/);

    // The plans/ working-doc tree is scaffolded.
    for (const sub of PLANS_SUBDIRS) {
      assert.ok(fs.existsSync(out.plansDirs[sub]) && fs.statSync(out.plansDirs[sub]).isDirectory(), `plans/${sub}/ created`);
    }

    // The flag is OFF by default → NO optional docs.
    assert.equal(out.optional, false, 'optional output reported as absent');
    assert.ok(!fs.existsSync(path.join(dir, OPTIONAL_DOC_FILENAMES.rtm)), 'no RTM.md by default');
    assert.ok(!fs.existsSync(path.join(dir, OPTIONAL_DOC_FILENAMES.summary)), 'no SUMMARY.md by default');
    assert.ok(!fs.existsSync(path.join(dir, VIZ_DIR)), 'no viz/ by default');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('done-when: the optional docs (RTM/viz/SUMMARY) appear ONLY when the flag is set', () => {
  const dir = mkdir('opt');
  try {
    const out = writeDocSet({
      outputDir: dir,
      projectName: PROJECT,
      northStar: NORTH_STAR,
      optional: true,
      criteria: ['ship it'],
      rtmRows: [{ criterion: 'C1', waves: [1], tests: ['a.test.mjs'] }],
      vizWaves: [{ n: 1, title: 'Engine', dependsOn: null }, { n: 2, title: 'Docs', dependsOn: 'Engine' }],
      summary: { elevatorPitch: 'widgets' },
    });

    // Core still present.
    assert.ok(fs.existsSync(out.core.decisionLog));

    // Optional now present + reported.
    assert.notEqual(out.optional, false, 'optional output reported');
    assert.ok(fs.existsSync(path.join(dir, OPTIONAL_DOC_FILENAMES.rtm)), 'RTM.md written');
    assert.ok(fs.existsSync(path.join(dir, OPTIONAL_DOC_FILENAMES.summary)), 'SUMMARY.md written');
    const vizFile = path.join(dir, VIZ_DIR, VIZ_DEPENDENCY_FILE);
    assert.ok(fs.existsSync(vizFile), 'viz/dependency.mmd written');
    assert.match(fs.readFileSync(vizFile, 'utf8'), /W1 --> W2/);
    assert.equal(out.optional.vizFiles.dependency, vizFile);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

// --- (6) the maintain path: append-only inserts -----------------------------

test('appendDecision / appendGrasscatcherItem insert a new row without editing existing rows', () => {
  const dir = mkdir('append');
  try {
    const out = writeDocSet({
      outputDir: dir,
      projectName: PROJECT,
      northStar: NORTH_STAR,
      decisions: [{ id: 'D1', date: '2026-06-05', decision: 'first', approver: 'John' }],
      grasscatcherItems: [{ n: 1, date: '2026-06-05', idea: 'parked', origin: 'r1', why: 'scope', home: 'v2' }],
    });

    const dlog = appendDecision(out.core.decisionLog, { id: 'D2', date: '2026-06-06', decision: 'second', approver: 'John', status: 'Accepted' });
    assert.match(dlog, /\| D1 \| 2026-06-05 \| first \| John \|/, 'the original row is untouched');
    assert.match(dlog, /\| D2 \| 2026-06-06 \| second \| John \| Accepted \|/, 'the new row is appended');
    assert.ok(dlog.indexOf('| D1 ') < dlog.indexOf('| D2 '), 'appended after the existing row');

    const grass = appendGrasscatcherItem(out.core.grasscatcher, { n: 2, date: '2026-06-06', idea: 'another', origin: 'r2', why: 'scope', home: 'v2' });
    assert.match(grass, /\| 1 \| 2026-06-05 \| parked \|/, 'original idea untouched');
    assert.match(grass, /\| 2 \| 2026-06-06 \| another \|/, 'new idea appended');

    // Persisted to disk, not just returned.
    assert.match(fs.readFileSync(out.core.decisionLog, 'utf8'), /\| D2 \|/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('append* HALTs when the target doc was never generated', () => {
  assert.throws(
    () => appendDecision(path.join(os.tmpdir(), 'crucible-nope-DECISION-LOG.md'), { id: 'D1', date: 'x', decision: 'y', approver: 'z' }),
    (e) => e instanceof HaltError,
  );
});

// --- (7) wiring guards ------------------------------------------------------

test('writeDocSet HALTs without an outputDir or a North Star', () => {
  assert.throws(() => writeDocSet({ northStar: NORTH_STAR }), (e) => e instanceof HaltError);
  assert.throws(() => writeDocSet({ outputDir: 'x' }), (e) => e instanceof HaltError);
});
