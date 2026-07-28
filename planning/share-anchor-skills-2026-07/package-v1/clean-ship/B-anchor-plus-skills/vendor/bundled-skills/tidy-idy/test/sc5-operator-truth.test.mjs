// SC5 operator docs truth gate (Foreman Wave 6 / plan id W5).
// SKILL.md ↔ bin/tidy-idy.mjs USAGE/--help ↔ Anchor thin-caller dry path.
// Resolves W0 skill-mismatch-list.md M1–M8. Does not edit apply/token safety code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { USAGE, parseArgs } from '../bin/tidy-idy.mjs';
import {
  buildTidyJobSpec,
  tidyIdyEntryPoint,
  FOLDER_CLAIM_LANE,
  TIDY_JOB_TYPE,
} from '../engine/launch/anchor-caller.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const skillRoot = path.resolve(__dirname, '..');
const skillMd = path.join(skillRoot, 'SKILL.md');
const mismatchList = path.resolve(
  '<path>',
);
const operatorNote = path.join(skillRoot, 'docs', 'w5-operator-truth.md');

function read(p) {
  return fs.readFileSync(p, 'utf8');
}

/** Option flags listed in USAGE (excluding --help). */
function usageFlags(usageText) {
  const flags = [];
  for (const line of String(usageText).split(/\r?\n/)) {
    const m = /^\s+(--[a-z][a-z0-9-]*)/.exec(line);
    if (m) flags.push(m[1]);
  }
  return flags;
}

test('SC5: SKILL.md and operator pointer exist', () => {
  assert.ok(fs.existsSync(skillMd), 'SKILL.md required');
  assert.ok(fs.existsSync(operatorNote), 'docs/w5-operator-truth.md required');
  assert.ok(fs.existsSync(mismatchList), 'W0 skill-mismatch-list.md required');
});

test('SC5 M1: SKILL default entry is tidy-idy.mjs <folder>, not tidy.mjs', () => {
  const body = read(skillMd);
  assert.match(body, /bin\/tidy-idy\.mjs\s+<folder>/);
  assert.match(body, /Canonical entry point/i);
  // Legacy batch may be named, but must be demoted.
  assert.match(body, /legacy/i);
  assert.match(body, /bin\/tidy\.mjs/);
  // How-to-run primary command block must lead with tidy-idy, not tidy.mjs alone.
  const how = body.slice(body.indexOf('## How to run'));
  const firstCode = /```[\s\S]*?```/.exec(how);
  assert.ok(firstCode, 'How to run has a code fence');
  assert.match(firstCode[0], /tidy-idy\.mjs/);
  assert.doesNotMatch(firstCode[0], /^\s*node bin\/tidy\.mjs/m);
});

test('SC5 M2: SKILL documents plain-folder / no hard git-only refusal at launch', () => {
  const body = read(skillMd);
  assert.match(body, /plain (directory|folder)/i);
  assert.match(body, /Trash/i);
  // Fiction from old operator manual must not reappear as the product rule.
  assert.doesNotMatch(
    body,
    /NON-GIT directory is a HARD refusal/i,
  );
  assert.doesNotMatch(
    body,
    /Refuses to operate outside git/i,
  );
});

test('SC5 M3–M6: SKILL names panel, Trash, reorg, thin caller', () => {
  const body = read(skillMd);
  assert.match(body, /Triage Panel/i);
  assert.match(body, /Trash/i);
  assert.match(body, /reorg|reorganization/i);
  assert.match(body, /thin caller/i);
  assert.match(body, /before→after|before->after|before.?after/i);
  assert.match(body, /Apply once|one Apply per run/i);
});

test('SC5 M7–M8: description + state story match shipped surfaces', () => {
  const body = read(skillMd);
  // Frontmatter must not claim Foundry-only hard git refusal as the product.
  const fm = body.slice(0, body.indexOf('\n---', 4) + 4);
  assert.doesNotMatch(fm, /Refuses to operate outside git/i);
  assert.match(body, /\.tidy-idy\//);
  assert.match(body, /apply-state|panel-server|archive/i);
  // Briefing inline still needs the phrase used by launch-briefing tests.
  assert.match(body, /Repository hygiene/);
});

test('SC5: SKILL options align with exported USAGE / --help', () => {
  const body = read(skillMd);
  assert.match(USAGE, /tidy-idy <folder>/);
  assert.match(USAGE, /Triage Panel/);
  const flags = usageFlags(USAGE);
  assert.ok(flags.includes('--no-open'));
  assert.ok(flags.includes('--json'));
  assert.ok(flags.includes('--nonce-file'));
  assert.ok(flags.includes('--environment'));
  for (const flag of flags) {
    if (flag === '--help') continue;
    assert.ok(
      body.includes(flag),
      `SKILL.md must document USAGE flag ${flag}`,
    );
  }
  // parseArgs dry path accepts the thin-caller shape.
  const opts = parseArgs([
    'C:/some/folder',
    '--environment=anchor',
    '--json',
    '--nonce-file=C:/tmp/nonce',
  ]);
  assert.equal(opts.rootPath, 'C:/some/folder');
  assert.equal(opts.environment, 'anchor');
  assert.equal(opts.json, true);
  assert.equal(opts.nonceFile, 'C:/tmp/nonce');
});

test('SC5: thin-caller dry path dispatches same entry (no second capability channel)', () => {
  const entry = tidyIdyEntryPoint();
  assert.ok(entry.replace(/\\/g, '/').endsWith('bin/tidy-idy.mjs'));
  const spec = buildTidyJobSpec({
    rootPath: 'C:/proj',
    nonceFile: 'C:/tmp/n',
    node: 'node',
  });
  assert.equal(spec.lane, FOLDER_CLAIM_LANE);
  assert.equal(spec.job_type, TIDY_JOB_TYPE);
  assert.ok(Array.isArray(spec.command));
  assert.equal(spec.command[0], 'node');
  assert.ok(String(spec.command[1]).replace(/\\/g, '/').endsWith('bin/tidy-idy.mjs'));
  assert.ok(spec.command.includes('--environment=anchor'));
  assert.ok(spec.command.includes('--json'));
  assert.ok(spec.command.some((a) => String(a).startsWith('--nonce-file=')));
  // SKILL documents the same argv shape.
  const body = read(skillMd);
  assert.match(body, /--environment=anchor/);
  assert.match(body, /--json/);
});

test('SC5: parent NS safety story not weakened in docs', () => {
  const body = read(skillMd);
  assert.match(body, /No auto-apply|no auto-apply/i);
  assert.match(body, /one Apply per run/i);
  assert.match(body, /never/i);
  assert.match(body, /localStorage/i);
  assert.match(body, /capability token/i);
  assert.doesNotMatch(body, /auto-apply is enabled/i);
  assert.doesNotMatch(body, /token on disk/i);
  assert.doesNotMatch(body, /multiple Apply(s)? per run/i);
});

test('SC5: W0 mismatch list M1–M8 marked closed', () => {
  const list = read(mismatchList);
  for (const id of ['M1', 'M2', 'M3', 'M4', 'M5', 'M6', 'M7', 'M8']) {
    assert.match(
      list,
      new RegExp(`${id}.*\\b(CLOSED|closed|resolved)\\b`, 'i'),
      `${id} must be closed/resolved in skill-mismatch-list.md`,
    );
  }
  assert.match(list, /W5 gate checklist/i);
  // Checklist boxes checked or stamped green.
  assert.match(list, /\[x\].*tidy-idy\.mjs/i);
});

test('SC5: operator note points at truth gate and design lock', () => {
  const note = read(operatorNote);
  assert.match(note, /sc5-operator-truth\.test\.mjs/);
  assert.match(note, /Option 1/i);
  assert.match(note, /tidy-idy-mockup-A2-reorg/);
  assert.match(note, /SKILL\.md/);
});
