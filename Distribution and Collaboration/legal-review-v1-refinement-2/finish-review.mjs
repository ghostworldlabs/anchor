import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { main } from 'file:///C:/Users/john/.agents/skills/ecgberht/engine/index.mjs';

const root = process.cwd();
const run = path.join(root, 'legal-review-v1-refinement-2');
const read = p => fs.readFileSync(p, 'utf8');
const write = (p, s) => fs.writeFileSync(p, s, 'utf8');
const sha = s => crypto.createHash('sha256').update(s, 'utf8').digest('hex');
const body = read(path.join(run, 'REVIEW-BODY.md'));
const input = read(path.join(run, 'INPUT-LICENSE-v1-REFINEMENT-2.md'));
const current = read(path.join(root, 'GHOST-WORLD-LAB-LICENSE-v1.md'));
const end = JSON.parse(read(path.join(run, 'RUN-END.json')));
const seat = JSON.parse(read(path.join(run, 'SEAT-RECEIPT.json')));
const gate = JSON.parse(read(path.join(run, 'citation-gate/LEGAL-REVIEW.json')));
if (end.status !== 'completed' || !seat.ok || !seat.served.model_attested) throw Error('Missing actual review');
if (sha(input) !== end.inputSha256 || current !== input) throw Error('Input drift');
if (sha(body) !== gate.receipt.deliverable_sha256 || !gate.citation_gate.token.ok || !gate.citation_gate.proposition.ok) throw Error('Citation gate mismatch');
const quotes = [...body.matchAll(/“([^”]+)”/g)].map(m => ({ quote: m[1], matched: input.includes(m[1]) }));
if (quotes.length !== 4 || quotes.some(q => !q.matched)) throw Error('Operative quotation mismatch');
write(path.join(run, 'QUOTE-CHECK.json'), JSON.stringify({input_sha256:sha(input), report_body_sha256:sha(body), checked:quotes.length, quotes},null,2)+'\n');
write(path.join(root, 'LEGAL-BEAGLE-REVIEW-v1-REFINEMENT-2.md'), body + '\n## Citation receipt\n\nThe receipt binds the preceding memo, preserved in `legal-review-v1-refinement-2/REVIEW-BODY.md`. Deterministic citation checks passed with zero recognized legal-citation patterns; the actual independent textual check is recorded above. This is not a legal certification.\n\n' + gate.receipt.footer_line + '\n');
const registerPath = path.join(root, 'DELIVERABLES.md');
let register = read(registerPath);
if (!register.includes('wording check pending')) throw Error('Unexpected register state');
register = register.replace('wording check pending', 'Legal-Beagle payment check completed');
const newRow = '| FOR REVIEW — Legal-Beagle Ghost World Lab License v1, Refinement 2 payment review — completed; contractor labor permitted, software/version fees reserved | `LEGAL-BEAGLE-REVIEW-v1-REFINEMENT-2.md` | 2026-10-04 | gwl-license |\n';
register = register.replace('| Earlier Legal-Beagle', newRow + '| Earlier Legal-Beagle');
write(registerPath, register);
const journalPath = path.join(root, 'journal/0009-ghost-world-lab-license-2026-10-04.md');
let journal = read(journalPath);
journal = journal.replace('a focused check of Refinement 2 is underway.', 'the [focused Refinement 2 payment review](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=Distribution%20and%20Collaboration%2FLEGAL-BEAGLE-REVIEW-v1-REFINEMENT-2.md&render=1) completed with no new material payment-wording findings.');
journal += '\nThe focused Legal-Beagle check completed at 22:50 UTC, attesting the configured Grok subscription model `grok-4.7-build`. It found no new material payment-wording findings and confirmed the operative clauses, companion and scenarios distinguish genuine programming/delivery from software sales, recurring version-use fees and paid hosting. The review loop stops here. Four verbatim quotations in the new human report match the frozen Refinement 2 input; the raw response\'s abbreviated wording is not treated as exact quotation. Citation engine gates passed with zero recognized legal-citation patterns; the engine-only receipt is distinct from the actual independent textual review. The new report is registered separately from the unchanged Refinement 1 review. Final wording and adoption prerequisites remain open; no publication, application or slice close occurs. The first path-limited commit needed explicit staging for new task files; the subsequent scoped commit succeeded, preserving unrelated staging. Cumulative overhead remains 2.\n';
write(journalPath, journal);
const facePath = path.join(root, 'ECGBERHT.md');
const oldFace = read(facePath);
const sections = [...oldFace.matchAll(/^## (Source|Existing work)\r?\n([\s\S]*?)(?=^## |$(?![\s\S]))/gm)];
const result = main(['update','--project',root,
  '--active-effort','Ghost World Lab License v1, Refinement 2 and its focused payment review are ready.',
  '--why-next','The accepted contractor policy is incorporated and independently checked; final terms remain unapproved.',
  '--human-wait','none','--wait-ref','none','--current-step','gwl-license',
  '--next-recommended','Review Ghost World Lab License v1, Refinement 2 and its payment check.',
  '--strip-why-next','Contractor labor is permitted; software sales and recurring version fees remain reserved.']);
if (!result.ok) throw Error(JSON.stringify(result));
let face = read(facePath);
face = face.replace(/^# [^\r\n]+/, oldFace.match(/^# [^\r\n]+/)[0]);
for (const section of sections) {
  let value = section[0];
  if (section[1] === 'Existing work') value = '## Existing work\n\nThis cockpit owns portable releases, the public distribution home and licensing. Contractor programming time is accepted and incorporated in Ghost World Lab License v1, Refinement 2. Its focused Legal-Beagle payment check completed with no new material findings; the unchanged earlier review covers Refinement 1. Existing distribution/onboarding work and earlier independently reviewable licensing products remain in the register. The connect-first decision accepts trial order only. No final license, public release or implementation plan is approved.\n';
  const re = new RegExp('^## '+section[1]+'\\r?\\n[\\s\\S]*?(?=^## |$(?![\\s\\S]))','m');
  if (re.test(face)) face = face.replace(re, () => value); else face += '\n'+value;
}
write(facePath, face);
console.log(JSON.stringify({report:'LEGAL-BEAGLE-REVIEW-v1-REFINEMENT-2.md', quote_matches:quotes.length, model:seat.served.model, status:'ready; not adopted; slice remains open'}));
