// Recover the failed structured review through the installed driver's documented text interface.
import fs from 'node:fs';
import path from 'node:path';
import {runAgent} from 'file:///C:/dev/trio/drivers/index.mjs';
const dir='C:/dev/Anchor/Distribution and Collaboration';
const out=path.join(dir,'legal-review-v1');
const started=new Date().toISOString();
const license=fs.readFileSync(path.join(dir,'GHOST-WORLD-LAB-LICENSE-v1.md'),'utf8');
const sources=fs.readFileSync(path.join(out,'PRIMARY-SOURCES.md'),'utf8');
const initial=fs.readFileSync(path.join(out,'INITIAL-ANALYSIS.md'),'utf8');
const prompt=[
'Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans.',
'You are the independent Legal-Beagle reviewer. Textual contract/policy review of the provided Ghost World Lab License v1, as of 2026-10-04. Governing jurisdiction NOT SELECTED; do not infer jurisdiction or provide an enforceability opinion. This is drafting support, not legal advice. All necessary sources are supplied. No tools, no delegation, no edits, no messages to John. Return your complete report in ordinary Markdown, not JSON.',
'Legal-Beagle hard rules: never cite cases/statutes/regulations from memory; every authority grounded in supplied sources or explicitly unverified. Jurisdiction/date first. Quote each operative clause before analysis. Never silently rewrite operative terms as plain English; suggest precise drafting corrections separately. Flag open facts rather than guess them.',
'Accepted policy: free personal/internal business use, modification allowed, contributions/sharing back voluntary, free forks allowed, no third-party sale of Anchor or products containing its covered code, permission required for paid Anchor hosting. Custom candidate/name/draft/review authorized, but no final terms, publication, price or commercial offering approved. Owner and dependencies/contributions not cleared. Paid private development is an unresolved edge, not a settled exception.',
'Verify EVERY citation and material quotation against supplied text. Independently challenge accidental restrictions and loopholes, including wages/contractor modifications, paid bundles, hosted APIs, independent plugins, contribution rights, no patent grant and termination. Separate wording corrections from policy decisions John must make. Supply exact clause quote, issue, consequence and suggested action for every material finding, ranked by consequence. No outside cases or jurisdiction-specific assertions. Do not withhold this textual review just because adoption prerequisites remain open.',
'Begin with a short useful conclusion. Identify actual corrections that can be made without changing policy. End with open decisions and whether this candidate is suitable for continued drafting, never approval to publish. Keep report under 1400 words. No JSON or prose about creating the report: provide the report itself.',
'=== EXACT LICENSE ===\n'+license,
'=== VERIFIED PRIMARY SOURCE EXCERPTS ===\n'+sources,
'=== INITIAL ANALYSIS TO CHALLENGE ===\n'+initial
].join('\n\n');
fs.writeFileSync(path.join(out,'RECOVERY-PROMPT.txt'),prompt,'utf8');
fs.writeFileSync(path.join(out,'RECOVERY-START.json'),JSON.stringify({started,pid:process.pid,reason:'Original structured reply failed after its automatic retry; use the documented plain-text interface without changing family, quality or draft.'},null,2)+'\n');
try{
 const text=await runAgent({role:'review',label:'review:legal-beagle-license-v1-text-recovery',target:dir,prompt,freshContext:true,sandbox:'read-only',env:{...process.env,CRUCIBLE_AGENT_LIVE:'1'},onReceipt:async receipt=>fs.writeFileSync(path.join(out,'RECOVERY-SEAT-RECEIPT.json'),JSON.stringify(receipt,null,2)+'\n'),onRoutingEvent:async event=>fs.appendFileSync(path.join(out,'ROUTING.jsonl'),JSON.stringify(event)+'\n'),log:message=>console.log(message)});
 if(typeof text!=='string'||!text.trim())throw new Error('Review returned no text');
 fs.writeFileSync(path.join(out,'INDEPENDENT-REVIEW.md'),text.trim()+'\n','utf8');
 fs.writeFileSync(path.join(out,'RECOVERY-END.json'),JSON.stringify({started,ended:new Date().toISOString(),status:'completed',pid:process.pid},null,2)+'\n');
 fs.writeFileSync(path.join(dir,'.ecgberht/attention.json'),JSON.stringify({state:'quiet',reason:'Legal-Beagle’s independent written review is complete'})+'\n');
 console.log('Independent Legal-Beagle written review completed.');
}catch(error){
 if(error.receipt)fs.writeFileSync(path.join(out,'RECOVERY-SEAT-RECEIPT.json'),JSON.stringify(error.receipt,null,2)+'\n');
 fs.writeFileSync(path.join(out,'RECOVERY-END.json'),JSON.stringify({started,ended:new Date().toISOString(),status:'failed',error:{name:error.name,message:error.message,status:error.seat_status||null},pid:process.pid},null,2)+'\n');
 fs.writeFileSync(path.join(dir,'.ecgberht/attention.json'),JSON.stringify({state:'quiet',reason:'The independent written review stopped; inspect its result'})+'\n');
 console.error(error.message);process.exitCode=1;
}
