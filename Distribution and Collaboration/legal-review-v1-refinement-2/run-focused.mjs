import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {runAgent} from 'file:///C:/dev/trio/drivers/index.mjs';
const dir='C:/dev/Anchor/Distribution and Collaboration';
const out=path.join(dir,'legal-review-v1-refinement-2');
const started=new Date().toISOString();
const license=fs.readFileSync(path.join(dir,'GHOST-WORLD-LAB-LICENSE-v1.md'),'utf8');
const inputSha256=crypto.createHash('sha256').update(license).digest('hex');
fs.writeFileSync(path.join(out,'INPUT-LICENSE-v1-REFINEMENT-2.md'),license,'utf8');
const prompt=[
 'Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans.',
 'Legal-Beagle focused drafting check of Ghost World Lab License v1, Refinement 2. As-of 2026-10-04; governing jurisdiction NOT SELECTED. Textual/policy check only, no enforceability or jurisdiction-specific opinion. No tools, delegation or edits. Return the actual review as ordinary Markdown under 650 words, not JSON or a plan.',
 'Quote operative wording before each adverse finding. Never cite cases/statutes from memory. Distinguish accepted policy, drafting errors and unapproved supporting terms. No public application, final text approval or slice close is authorized.',
 'New explicit John answer, original turn ee1d9c6c-201e-4dc5-adfd-facb4db2d028: "Okay, paying a contractor to modify is fine; having a coder sell Anchor that they have modified is not (so they can be paid for their time to modify, but they cannot get a recuring payment for a version that they have modified)." The agreed distinction allows paid programming services for customer own use, including delivery of those changes; no one-time software sale or recurring modified-version-use fee. Earlier policy remains free personal/internal business use and modification, voluntary sharing, free forks, no covered-code product sales under the free license, and separate written permission for paid hosted access.',
 'Refinement 1 already received an independent check of internal wages, privacy, generic rental, contribution permissions and consistent cure wording. This is a fresh check of the changed payment clauses and their effects, not a repeat of the whole legal-policy discovery or a new Heavy swarm.',
 'Check sections 1, 3, 4, 5 and 9 together: does delivery for actual customer-specific programming services fit the exception without contradiction in Sale/redistribution, and does the text still forbid reselling products, one-time software-copy charges, recurring version-use fees, and disguised paid hosting? Are actual later labor services allowed without conditioning continued software use on paying? Do the companion and examples express those exact boundaries? Give the strongest contrary reading. Propose exact wording only for a NEW material textual defect, quoting the defective clause. If none, say NO NEW MATERIAL PAYMENT-WORDING FINDINGS. Keep owner, files, contributor/dependency rights, law and other supporting terms visibly unresolved; do not turn missing optional adoption inputs into a new blockage of this check.',
 '=== EXACT INPUT DRAFT ===\n'+license
].join('\n\n');
fs.writeFileSync(path.join(out,'PROMPT.txt'),prompt,'utf8');
fs.writeFileSync(path.join(out,'RUN-START.json'),JSON.stringify({started,pid:process.pid,inputSha256},null,2)+'\n');
const attention=reason=>fs.writeFileSync(path.join(dir,'.ecgberht/attention.json'),JSON.stringify({state:reason==='running'?'working':'quiet',reason:reason==='running'?'Legal-Beagle is checking the contractor-payment wording':reason})+'\n');
attention('running');
try{
 const text=await runAgent({role:'review',label:'review:legal-beagle-license-v1-refinement-2-payment',target:dir,prompt,freshContext:true,sandbox:'read-only',env:{...process.env,CRUCIBLE_AGENT_LIVE:'1'},onReceipt:async receipt=>fs.writeFileSync(path.join(out,'SEAT-RECEIPT.json'),JSON.stringify(receipt,null,2)+'\n'),onRoutingEvent:async event=>fs.appendFileSync(path.join(out,'ROUTING.jsonl'),JSON.stringify(event)+'\n'),log:message=>console.log(message)});
 if(typeof text!=='string'||!text.trim())throw new Error('Focused check returned no usable text');
 fs.writeFileSync(path.join(out,'FOCUSED-CHECK.md'),text.trim()+'\n','utf8');
 fs.writeFileSync(path.join(out,'RUN-END.json'),JSON.stringify({started,ended:new Date().toISOString(),status:'completed',pid:process.pid,inputSha256},null,2)+'\n');
 attention('Legal-Beagle has finished the contractor-payment check');
 console.log('Focused payment check completed.');
}catch(error){
 if(error.receipt)fs.writeFileSync(path.join(out,'SEAT-RECEIPT.json'),JSON.stringify(error.receipt,null,2)+'\n');
 fs.writeFileSync(path.join(out,'RUN-END.json'),JSON.stringify({started,ended:new Date().toISOString(),status:'failed',error:{name:error.name,message:error.message},pid:process.pid,inputSha256},null,2)+'\n');
 attention('The focused payment check stopped; inspect its result');
 console.error(error.message);process.exitCode=1;
}
