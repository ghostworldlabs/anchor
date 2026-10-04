// One bounded invocation of the installed Legal-Beagle prompt protocol.
// This is a campaign run harness, not a modification of the skill or its drivers.
import fs from 'node:fs';
import path from 'node:path';
import { runAgent } from 'file:///C:/dev/trio/drivers/index.mjs';

const dir = 'C:/dev/Anchor/Distribution and Collaboration';
const out = path.join(dir, 'legal-review-v1');
const started = new Date().toISOString();
const supplied = ['GHOST-WORLD-LAB-LICENSE-v1.md', 'SCOPE-v1-REFINEMENT-1.md', 'legal-review-v1/PRIMARY-SOURCES.md', 'legal-review-v1/INITIAL-ANALYSIS.md'];
const documents = supplied.map(name => `=== ${name} ===\n${fs.readFileSync(path.join(dir,name),'utf8')}`).join('\n\n');
const protocol = fs.readFileSync('C:/dev/Skill Foundry/skills/legal-beagle/SKILL.md','utf8');
const prompt = [
 'Read/Grep/Glob/Edit/Write ONLY — no Bash, no PowerShell, no test suites, no installs, no bulk scans.',
 'Run the Legal-Beagle CONTRACT ANALYSIS protocol below as an independent read-only reviewer. All necessary texts are supplied; do not use file tools or shells, make no edits, and do not delegate. Review these exact bytes.',
 'Regular tier, medium stakes: unpublished license candidate requested by John. Date 2026-10-04; governing jurisdiction explicitly NOT SELECTED. This is textual/policy review, NOT an enforceability opinion. Identify missing facts; do not invent owner, law, rights, authorities or a licensed lawyer.',
 'Verify EVERY citation/quote against supplied source texts, confirm jurisdiction/date limitation, and refute the strongest boundary readings. Note conflicts with free internal use, voluntary sharing, free forks, no covered-code sales, and permission for paid hosting. Find anything the initial analysis missed, especially private commissioned modifications, paid bundle loopholes, employee/contractor access, hosted APIs, independent plugins, contribution rights and termination mechanics.',
 'Return one complete JSON object with human summary inside summary, no prose preface. Give exact clause quotes, issue, consequence, suggested correction, whether John must decide or wording alone can fix it. Do not require open later inputs as a reason to withhold this requested drafting review. Use no cases/statutes from memory. Local legal applicability remains unverified. Do not copy source excerpts beyond supplied quotes.',
 'Verdicts: DRAFT_REVIEW_COMPLETE_WITH_OPEN_DECISIONS, NEEDS_TEXT_CORRECTION, or REVIEW_BLOCKED. None approves publication. Be concise but exhaustive over actual material issues.',
 '=== INSTALLED LEGAL-BEAGLE PROTOCOL ===\n'+protocol,
 documents
].join('\n\n');
fs.writeFileSync(path.join(out,'REVIEW-PROMPT.txt'),prompt,'utf8');
const schema = {
 type:'object',required:['summary','verdict','citation_check','jurisdiction_and_date','findings','policy_coverage'],additionalProperties:false,
 properties:{summary:{type:'string'},verdict:{type:'string',enum:['DRAFT_REVIEW_COMPLETE_WITH_OPEN_DECISIONS','NEEDS_TEXT_CORRECTION','REVIEW_BLOCKED']},citation_check:{type:'string'},jurisdiction_and_date:{type:'string'},findings:{type:'array',items:{type:'object',required:['id','severity','clause_quote','issue','consequence','suggested_action','john_decision_required'],additionalProperties:false,properties:{id:{type:'string'},severity:{type:'string'},clause_quote:{type:'string'},issue:{type:'string'},consequence:{type:'string'},suggested_action:{type:'string'},john_decision_required:{type:'boolean'}}}},policy_coverage:{type:'array',items:{type:'object',required:['policy','result'],additionalProperties:false,properties:{policy:{type:'string'},result:{type:'string'}}}}}
};
fs.writeFileSync(path.join(out,'RUN-START.json'),JSON.stringify({started,pid:process.pid,protocol:'Legal-Beagle regular, medium stakes',supplied},null,2)+'\n');
try {
 const review=await runAgent({role:'review',label:'review:legal-beagle-ghost-world-lab-license-v1',target:dir,prompt,schema,freshContext:true,sandbox:'read-only',env:{...process.env,CRUCIBLE_AGENT_LIVE:'1'},onReceipt:async receipt=>fs.writeFileSync(path.join(out,'SEAT-RECEIPT.json'),JSON.stringify(receipt,null,2)+'\n'),onRoutingEvent:async event=>fs.appendFileSync(path.join(out,'ROUTING.jsonl'),JSON.stringify(event)+'\n'),log:message=>console.log(message)});
 fs.writeFileSync(path.join(out,'INDEPENDENT-REVIEW.json'),JSON.stringify(review,null,2)+'\n');
 fs.writeFileSync(path.join(out,'RUN-END.json'),JSON.stringify({started,ended:new Date().toISOString(),status:'completed',verdict:review.verdict,pid:process.pid},null,2)+'\n');
 console.log('Legal-Beagle independent review complete: '+review.verdict);
} catch (error) {
 if(error.receipt) fs.writeFileSync(path.join(out,'SEAT-RECEIPT.json'),JSON.stringify(error.receipt,null,2)+'\n');
 fs.writeFileSync(path.join(out,'RUN-END.json'),JSON.stringify({started,ended:new Date().toISOString(),status:'failed',error:{name:error.name,message:error.message,status:error.seat_status||null},pid:process.pid},null,2)+'\n');
 console.error('Legal-Beagle review did not complete: '+error.message); process.exitCode=1;
}
