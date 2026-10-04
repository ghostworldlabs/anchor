import fs from 'node:fs';
import path from 'node:path';
const root = process.cwd();
const run = path.join(root, 'legal-review-v1-refinement-2');
const end = JSON.parse(fs.readFileSync(path.join(run, 'RUN-END.json'),'utf8'));
const seat = JSON.parse(fs.readFileSync(path.join(run, 'SEAT-RECEIPT.json'),'utf8'));
const journalDir = 'C:/dev/Skill Foundry/skills/legal-beagle/journal';
const next = Math.max(...fs.readdirSync(journalDir).filter(f=>/^\d{4}-.*\.md$/.test(f)).map(f=>Number(f.slice(0,4))))+1;
const id = `${String(next).padStart(4,'0')}-ghost-world-lab-license-payment-2026-10-04`;
const journalRef = id+'.md';
const journal = [
  `id: ${id}`,
  'skill: legal-beagle@2026-10-04',
  'situation: Focused payment-policy change to an unpublished source-available software license.',
  'context: Anchor / Distribution and Collaboration; Ghost World Lab License v1, Refinement 2; John explicitly permits contractor programming time but rejects selling modified versions and recurring version-use fees.',
  'observation: The configured attested Grok review found no new material payment-wording findings. The delivery exception inside Sale and service-versus-software boundaries preserve the accepted distinction. Raw response abbreviates some quotes; four report quotations were checked verbatim against the frozen input. Engine citation gates passed with zero recognized legal-citation patterns, distinct from the actual independent check.',
  'outcome: worked — changed clauses, companion and examples independently checked; owner, governing law, rights and supporting adoption terms remain open. No license application, publication or slice close.',
  'provenance: genuine-execution',''
].join('\n');
fs.writeFileSync(path.join(journalDir,journalRef),journal);
const ended = new Date().toISOString();
const capture = {
  skill:'legal-beagle',tier:'regular',started:end.started,ended,
  input:path.join(run,'INPUT-LICENSE-v1-REFINEMENT-2.md'),
  params:{scope:'Changed contractor-payment wording and companion/examples only',
    coding_family:'chatgpt',review_family:seat.served.family,
    model_policy:'latest_supported',reasoning_effort_policy:'highest_supported',
    jurisdiction:'not selected; textual and policy check only',
    source_sha256:end.inputSha256,citation_engine:'gates-only; zero recognized legal citations',
    direct_quotation_matches:4,slice_closed:false},
  output:[path.join(root,'LEGAL-BEAGLE-REVIEW-v1-REFINEMENT-2.md'),
    path.join(run,'FOCUSED-CHECK.md'),path.join(run,'SEAT-RECEIPT.json'),
    path.join(run,'QUOTE-CHECK.json'),path.join(run,'citation-gate/LEGAL-REVIEW.json')],
  result:'Focused independent review completed: no new material payment-wording findings; draft and review remain unaccepted final terms.',
  cross_model:seat.served.family !== 'chatgpt',
  models:[{role:'drafting',family:'chatgpt',served_model:null,model_attested:false},
    {role:'focused_payment_review',...seat.served}],
  duration_s:(new Date(ended)-new Date(end.started))/1000,journal_ref:journalRef
};
const captureName='2026-10-04T22-47-14Z-ghost-world-lab-license-payment.json';
fs.writeFileSync(path.join(journalDir,'runs',captureName),JSON.stringify(capture,null,2)+'\n');
console.log(JSON.stringify({journal:journalRef,capture:captureName}));
