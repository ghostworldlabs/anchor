#!/usr/bin/env node
// The code-job review gate's one adapter (execution minimum item 3, 2026-10-07). THIN and FAIL-CLOSED: it asks the
// trio's existing runAgent for one review (role "review" - a verification seat, so the trio never fails it over to
// another family) of a candidate tree, and prints ONE JSON line:
//   {ok, family, model, model_attested, tree_hash, verdict: "PASS"|"FAIL", findings: [...], elegance}
// Anything else - an exception, no second family configured, the reviewer of the author's own family, an unreadable
// answer - prints {ok:false, error} and exits 2. Landing reads only this line; it never trusts prose.
//
//   node tools/steward_review.mjs --repo <worktree> --base <sha> --head <sha> --author-family <claude|chatgpt|grok|gemini>
//        [--reviewer-family <family>] [--exhausted <family,family>] [--brief-file <path>] [--delta-from <sha>]
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const MAX_DIFF = 400_000;
const FAMILIES = ['claude', 'chatgpt', 'grok', 'gemini'];

function arg(name, fallback = '') {
  const i = process.argv.indexOf('--' + name);
  return i > 0 && i + 1 < process.argv.length ? process.argv[i + 1] : fallback;
}

function out(obj, code = 0) {
  process.stdout.write(JSON.stringify(obj) + '\n');
  process.exit(code);
}

let attempted = null;     // the reviewer family asked, so a quota failure can be remembered against it
function fail(error) {
  out({ ok: false, family: attempted, error: String(error && error.message ? error.message : error).slice(0, 600) }, 2);
}

function git(repo, ...args) {
  return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }).trim();
}

const SCHEMA = {
  type: 'object',
  required: ['verdict', 'findings', 'elegance'],
  properties: {
    verdict: { type: 'string', enum: ['PASS', 'FAIL'] },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'issue'],
        properties: {
          severity: { type: 'string', enum: ['BLOCKER', 'MAJOR', 'MINOR'] },
          file: { type: 'string' }, line: { type: 'integer' }, issue: { type: 'string' }, fix: { type: 'string' },
        },
      },
    },
    elegance: { type: 'string' },
  },
};

async function main() {
  const repo = arg('repo'), base = arg('base'), head = arg('head');
  const authors = arg('author-family').toLowerCase().split(',').map(s => s.trim()).filter(Boolean);
  const exhausted = new Set(arg('exhausted').toLowerCase().split(',').map(s => s.trim()).filter(Boolean));
  if (!repo || !base || !head) throw new Error('usage: --repo --base --head --author-family are required');
  if (!authors.length || !authors.every(a => FAMILIES.includes(a))) throw new Error(`unknown author families "${authors}"`);
  const trioRoot = process.env.ANCHOR_TRIO_ROOT || 'C:/dev/trio';
  const drivers = await import(pathToFileURL(path.join(trioRoot, 'drivers', 'index.mjs')).href);

  // the reviewer: the asked family, else the dashboard's Reviewer seat, else its Coder seat - never the author's
  // family, never a family known to be exhausted. No second family: refuse (never review oneself).
  // The trio routes a review call to the dashboard's Reviewer seat whatever driver is asked for (its Anchor-prefs
  // rule), so the ONLY reviewer this adapter can honestly call is that seat. When the seat is an author's family or
  // known exhausted, refuse before launching anything - never change the seats, never call a reviewer we did not pick.
  const prefs = drivers.loadModelFamilies(process.env);
  const reviewer = String(prefs.review || '').toLowerCase();
  attempted = FAMILIES.includes(reviewer) ? reviewer : null;
  if (!FAMILIES.includes(reviewer)) throw new Error(`the Reviewer seat (${reviewer || 'unset'}) is not a known family`);
  if (authors.includes(reviewer)) throw new Error(`the Reviewer seat (${reviewer}) is an author's family (${authors}); choose another Reviewer seat on the dashboard`);
  if (exhausted.has(reviewer)) throw new Error(`the Reviewer seat (${reviewer}) hit its usage limit recently; wait or choose another Reviewer seat`);

  const treeHash = git(repo, 'rev-parse', head + '^{tree}');
  const from = arg('delta-from') || base;
  const diff = git(repo, 'diff', '--no-color', '--find-renames', from, head);
  if (!diff.trim()) throw new Error('the candidate has no change to review');
  if (diff.length > MAX_DIFF) throw new Error(`the diff is ${diff.length} characters - too large for one review; split the job`);
  // fcj review r5: the brief is read WHOLE or the review refuses - never sliced (a cut brief could drop a requirement)
  const brief = arg('brief-file') && fs.existsSync(arg('brief-file')) ? fs.readFileSync(arg('brief-file'), 'utf8') : '';
  if ([...brief].length > 16000) throw new Error(`the brief is ${[...brief].length} characters - longer than the reviewer reads whole`);

  const prompt = [
    'You are the adversarial second-family reviewer of a code change an AI coder made for John.',
    'Decide PASS only if the change is correct, does what the brief asks, and introduces no defect you can name.',
    'FAIL on any BLOCKER or MAJOR finding: a concrete wrong result, a crash, data loss, a security hole, or a',
    'missing part of the brief. MINOR findings alone do not fail it. No style preferences.',
    'Add "elegance": at most three lines on what is heavier than it needs to be.',
    from !== base ? `This is a DELTA review: only the change since an earlier reviewed candidate (${from}).` : '',
    '', 'BRIEF:', brief || '(none given)', '', `DIFF (${from}..${head}):`, diff,
  ].join('\n');

  let receipt = null;
  const result = await drivers.runAgent({
    prompt, schema: SCHEMA, role: 'review', label: 'review:code-job',
    driver: drivers.familyToDriverName(reviewer), freshContext: true,
    onReceipt: (r) => { receipt = r; },
  });
  const served = (receipt && receipt.served) || {};
  const family = String(served.family || '').toLowerCase();
  if (!family) throw new Error('the review seat did not report which family served it');
  if (authors.includes(family)) throw new Error(`the review was served by an author's own family (${family})`);
  if (!result || !['PASS', 'FAIL'].includes(result.verdict)) throw new Error('the review answer had no verdict');
  const findings = Array.isArray(result.findings) ? result.findings : [];
  if (result.verdict === 'PASS' && findings.some(f => f && ['BLOCKER', 'MAJOR'].includes(f.severity))) {
    result.verdict = 'FAIL';                 // a PASS that lists a blocking finding is not a pass
  }
  out({ ok: true, family, model: served.model || null, model_attested: !!served.model_attested, tree_hash: treeHash,
        verdict: result.verdict, findings: Array.isArray(result.findings) ? result.findings : [],
        elegance: String(result.elegance || '').slice(0, 600) });
}

main().catch(fail);
