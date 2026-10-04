// Bounded independent check of corrections made from the received Legal-Beagle findings.
import fs from 'node:fs';
import path from 'node:path';
import {runAgent} from 'file:///C:/dev/trio/drivers/index.mjs';
const dir='C:/dev/Anchor/Distribution and Collaboration';
const out=path.join(dir,'legal-review-v1');
const started=new Date().toISOString();
const license=fs.readFileSync(path.join(dir,'GHOST-WORLD-LAB-LICENSE-v1.md'),'utf8');
const prompt=[
'Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans.',
'Legal-Beagle independent CORRECTION CHECK of the exact supplied Ghost World Lab License v1, Refinement 1. As-of 2026-10-04, governing jurisdiction NOT SELECTED. Textual/policy review only, no enforceability or jurisdiction-specific opinion. No tools, no delegation, no edits. Return ordinary Markdown, not JSON, under 700 words. Provide the review itself, not a plan.',
'Hard rules: quote the operative text before any adverse finding; no cases/statutes from memory; distinguish policy choices from text errors; jurisdiction/date first. All sources needed for this check are supplied. Do not copy or change operative terms as plain-English substitutions.',
'Accepted policy: free personal/internal business use, modification, voluntary upstream sharing, free forks, no software sales of Anchor or covered-code products, permission for paid hosted access. Final text/publication/offerings not accepted. Paid delivery of a private modification OUTSIDE the Internal Users exception remains a proposed restricted interpretation for John to decide. Supporting termination/recipient/patent/notice clauses likewise remain proposed, not approved.',
'Prior independent review found: (1) wages/in-house contractor compensation could count as software sales; (2) private staff confidentiality could violate redistribution terms; (3) buyer protection after an unauthorized sale needs explicit later acceptance; (4) generic rented infrastructure/optional community donations could count as paid hosting; (5) empty coverage boundary needs a real inventory, no new trivial-amount exemption; (6) a patch submission supplies no inbound redistribution grant, free or paid; (7) compliance condition and commercial/other breach cure conflicted; (8) no patent grant/blank owner/law/status text need clear posture.',
'Root applied corrections BEFORE this check: explicit in-house compensation exception; redistribution restrictions limited outside Internal Users, privacy preserved; generic rental and optional hosting sponsorship clarified; Licensor only for material an identified holder is authorized to license; no free OR paid redistribution grant merely from submission; one consistent notice-and-cure process for free rights, never commercial permission or retroactive authorization; only sections 1-10 operative; ordinary removed from internal business use. The initial v1 input and received raw review remain preserved separately.',
'Determine whether those text corrections resolve the identified conflicts without inventing new commercial permissions, whether the companion/examples match operative clauses, and whether any NEW material contradiction remains. Flag the strongest contrary reading. If none remains beyond declared open policy/rights questions, say NO NEW MATERIAL WORDING FINDINGS; do not manufacture extra requirements or approve publication. If corrections are needed, quote and propose their exact text. End with the remaining decisions, led by paid private deliveries.',
'=== EXACT REVISED DRAFT ===\n'+license
].join('\n\n');
fs.writeFileSync(path.join(out,'CORRECTION-PROMPT.txt'),prompt,'utf8');
fs.writeFileSync(path.join(out,'CORRECTION-START.json'),JSON.stringify({started,pid:process.pid},null,2)+'\n');
try{
 const text=await runAgent({role:'review',label:'review:legal-beagle-license-v1-corrections',target:dir,prompt,freshContext:true,sandbox:'read-only',env:{...process.env,CRUCIBLE_AGENT_LIVE:'1'},onReceipt:async receipt=>fs.writeFileSync(path.join(out,'CORRECTION-SEAT-RECEIPT.json'),JSON.stringify(receipt,null,2)+'\n'),onRoutingEvent:async event=>fs.appendFileSync(path.join(out,'ROUTING.jsonl'),JSON.stringify(event)+'\n'),log:message=>console.log(message)});
 if(typeof text!=='string'||!text.trim())throw new Error('Correction check returned no text');
 fs.writeFileSync(path.join(out,'CORRECTION-CHECK.md'),text.trim()+'\n','utf8');
 fs.writeFileSync(path.join(out,'CORRECTION-END.json'),JSON.stringify({started,ended:new Date().toISOString(),status:'completed',pid:process.pid},null,2)+'\n');
 fs.writeFileSync(path.join(dir,'.ecgberht/attention.json'),JSON.stringify({state:'quiet',reason:'Legal-Beagle’s correction check is complete'})+'\n');
 console.log('Legal-Beagle correction check completed.');
}catch(error){
 if(error.receipt)fs.writeFileSync(path.join(out,'CORRECTION-SEAT-RECEIPT.json'),JSON.stringify(error.receipt,null,2)+'\n');
 fs.writeFileSync(path.join(out,'CORRECTION-END.json'),JSON.stringify({started,ended:new Date().toISOString(),status:'failed',error:{name:error.name,message:error.message},pid:process.pid},null,2)+'\n');
 fs.writeFileSync(path.join(dir,'.ecgberht/attention.json'),JSON.stringify({state:'quiet',reason:'The correction check stopped; inspect its result'})+'\n');
 console.error(error.message);process.exitCode=1;
}
