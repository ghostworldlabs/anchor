// SC1 mockup hygiene — single CURRENT design home (Foreman W1).
// Reads absolute plan-dir + root mockup paths so skill-root node --test fails closed
// on a second CURRENT surface, unlabelled B/C/Option2, or non-pointer root stubs.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const skillRoot = path.resolve(__dirname, '..');

const CANONICAL_DESIGN = path.resolve(
  '<path>',
);
const CURRENT_A = path.join(CANONICAL_DESIGN, 'tidy-idy-mockup-A-triage.html');
const CURRENT_A2 = path.join(CANONICAL_DESIGN, 'tidy-idy-mockup-A2-reorg.html');
const DESIGN_README = path.join(CANONICAL_DESIGN, 'README.md');
const ARCHIVE_DIR = path.join(CANONICAL_DESIGN, 'archive');
const ARCHIVE_OPT2 = path.join(ARCHIVE_DIR, 'tidy-idy-mockup-A2-option2-REJECTED.html');
const ARCHIVE_B = path.join(ARCHIVE_DIR, 'tidy-idy-mockup-B-map-REJECTED.html');
const ARCHIVE_C = path.join(ARCHIVE_DIR, 'tidy-idy-mockup-C-queue-REJECTED.html');

const ROOT_A = path.resolve('<path>');
const ROOT_A2 = path.resolve('<path>');
const ROOT_B = path.resolve('<path>');
const ROOT_C = path.resolve('<path>');

const PARENT_DESIGN = path.resolve('<path>');
const PARENT_A = path.join(PARENT_DESIGN, 'tidy-idy-mockup-A-triage.html');
const PARENT_A2 = path.join(PARENT_DESIGN, 'tidy-idy-mockup-A2-reorg.html');

const POLISH_NS = path.resolve('<path>');

function read(p) {
  return fs.readFileSync(p, 'utf8');
}

function firstScreenful(html, maxChars = 1200) {
  return html.slice(0, maxChars);
}

function isPointerOrRejectedStub(html) {
  const head = firstScreenful(html);
  const hasLabel =
    /\bPOINTER\b/i.test(head) ||
    /\bREJECTED\b/i.test(head);
  const notCurrent =
    /not current design/i.test(head) ||
    /\bPOINTER\b/i.test(head) ||
    /\bREJECTED\b/i.test(head);
  // Stubs must not carry a full mockup body (dash/verdicts/option pick language)
  const looksLikeLiveMockup =
    /class="dash"/i.test(html) ||
    /class="verdicts"/i.test(html) ||
    /Pick one \(or blend\)/i.test(html) ||
    /OPTION 2 — SORTING BUCKETS/i.test(html);
  return hasLabel && notCurrent && !looksLikeLiveMockup;
}

test('SC1: canonical CURRENT files exist under polish design/', () => {
  assert.ok(fs.existsSync(CURRENT_A), `missing CURRENT A: ${CURRENT_A}`);
  assert.ok(fs.existsSync(CURRENT_A2), `missing CURRENT A2: ${CURRENT_A2}`);
  assert.ok(fs.existsSync(DESIGN_README), 'design/README.md required');
});

test('SC1: CURRENT A is labelled CURRENT and has self-contained brand (no file://)', () => {
  const body = read(CURRENT_A);
  assert.match(body, /CURRENT/i);
  assert.match(body, /tidy-idy-mockup-status" content="CURRENT"/i);
  assert.doesNotMatch(body, /file:\/\/\/<path>
  assert.match(body, /data:image\/svg\+xml/i);
  assert.doesNotMatch(body, /Mockup B/i);
  assert.doesNotMatch(body, /Mockup C/i);
});

test('SC1: CURRENT A2 is Option 1 only; Option 2 not presented as live choice', () => {
  const body = read(CURRENT_A2);
  assert.match(body, /CURRENT/i);
  assert.match(body, /tidy-idy-mockup-status" content="CURRENT"/i);
  assert.match(body, /OPTION 1/i);
  assert.match(body, /before\s*→\s*after|before→after|BEFORE → AFTER/i);
  // Option 2 must be REJECTED-labelled if mentioned; never "pick one or blend"
  assert.doesNotMatch(body, /Pick one \(or blend\)/i);
  assert.doesNotMatch(body, /OPTION 2 — SORTING BUCKETS/i);
  assert.match(body, /REJECTED/i);
  assert.doesNotMatch(body, /file:\/\/\/<path>
  assert.match(body, /data:image\/svg\+xml/i);
  // primary tree chrome present
  assert.match(body, /class="ba"/i);
});

test('SC1: REJECTED archive for B, C, and A2 Option 2', () => {
  for (const p of [ARCHIVE_B, ARCHIVE_C, ARCHIVE_OPT2]) {
    assert.ok(fs.existsSync(p), `missing archive: ${p}`);
    const body = read(p);
    assert.match(firstScreenful(body), /REJECTED/i);
    assert.match(firstScreenful(body), /not current design/i);
  }
});

test('SC1: root tidy-idy-mockup stubs are POINTER or REJECTED (first screenful)', () => {
  const roots = [
    { p: ROOT_A, kind: 'POINTER' },
    { p: ROOT_A2, kind: 'POINTER' },
    { p: ROOT_B, kind: 'REJECTED' },
    { p: ROOT_C, kind: 'REJECTED' },
  ];
  for (const { p, kind } of roots) {
    assert.ok(fs.existsSync(p), `root stub missing: ${p}`);
    const body = read(p);
    assert.ok(
      isPointerOrRejectedStub(body),
      `${p} must be POINTER/REJECTED stub, not a second CURRENT mockup body`,
    );
    assert.match(firstScreenful(body), new RegExp(kind, 'i'));
    assert.match(
      body,
      /2026-07-tidy-idy-gui-polish[\\/]design/,
      `${p} must point at polish design/`,
    );
  }
});

test('SC1: parent design/ is not a second CURRENT source', () => {
  for (const p of [PARENT_A, PARENT_A2]) {
    assert.ok(fs.existsSync(p), `parent stub missing: ${p}`);
    const body = read(p);
    assert.ok(
      isPointerOrRejectedStub(body),
      `${p} must be POINTER/REJECTED, not CURRENT mockup body`,
    );
    assert.match(firstScreenful(body), /POINTER|REJECTED/i);
    assert.match(body, /2026-07-tidy-idy-gui-polish[\\/]design/);
  }
});

test('SC1: polish NORTH-STAR and design README name single CURRENT path', () => {
  assert.ok(fs.existsSync(POLISH_NS), 'polish NORTH-STAR.md');
  const ns = read(POLISH_NS);
  assert.match(ns, /2026-07-tidy-idy-gui-polish[\\/]design/);
  assert.match(ns, /CURRENT/i);
  const readme = read(DESIGN_README);
  assert.match(readme, /CURRENT/i);
  assert.match(readme, /Option 1/i);
  assert.match(readme, /REJECTED/i);
});

test('SC1: skill docs pointer and no skill-root design/ CURRENT fork', () => {
  const skillPtr = path.join(skillRoot, 'docs', 'w1-mockup-hygiene.md');
  assert.ok(fs.existsSync(skillPtr), 'docs/w1-mockup-hygiene.md');
  assert.match(read(skillPtr), /2026-07-tidy-idy-gui-polish[\\/]design/);
  const skillDesign = path.join(skillRoot, 'design');
  if (fs.existsSync(skillDesign)) {
    // If a design/ ever appears under the skill, it must not hold unlabelled CURRENT HTML
    const entries = fs.readdirSync(skillDesign).filter((f) => f.endsWith('.html'));
    for (const f of entries) {
      const body = read(path.join(skillDesign, f));
      assert.ok(
        isPointerOrRejectedStub(body) || /CURRENT/.test(body) === false,
        `skill design/${f} must not be an unlabelled second CURRENT surface`,
      );
    }
  }
});
