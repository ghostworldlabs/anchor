// crucible/test/judge-rigor.test.mjs — Wave 3 (Phase C) gate: Judge rigor on the SCORING path.
//
// Proves the wave's done-when, model-free + deterministically:
//   - source/author anonymization strips identity-of-origin (author bylines, contact emails,
//     model/vendor self-mentions) from the SCORING PROMPT while KEEPING the in-text citations;
//   - length-normalization collapses cosmetic whitespace + records original vs normalized length
//     and the live prompt instructs the judge to score independent of length;
//   - the cross-family panel is the DEFAULT with an honest degrade ladder — with NO live
//     cross-family key the gate records a same-family degrade + attestation (deterministic);
//   - SR-6: the convergence Judge (judge.mjs CONVERGED/NOT_CONVERGED) path stays byte-identical
//     (judge.mjs is imported, never forked).
//
// Additive: this file only ADDS gates (SR-1 manifest superset holds) and lands at the
// glob-matched crucible/test/*.test.mjs path so it is actually in the `npm test` run set.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  scoreAgainstRubric,
  anonymizeForScoring,
  lengthNormalize,
  normalizeForScoring,
} from '../bin/packs/layer3-rubric.mjs';
import { runDefaultRubricGate, DEGRADE_LADDER } from '../bin/judge-panel.mjs';
import { makeJudge } from '../bin/judge.mjs';
import { loadPack } from '../bin/packs/registry.mjs';
import { hasAttestation } from '../../drivers/attest.mjs';
import { testDocPack } from './pack-fixtures.mjs';
import { litReviewClean, litRubricScore } from './lit-review-e2e-fixtures.mjs';

const litPack = loadPack('literature-review');

// --- pure normalization helpers ----------------------------------------------------------

test('anonymizeForScoring strips author/contact/model identity but KEEPS in-text citations', () => {
  const { text, redactions } = anonymizeForScoring(
    'By: A. Author\nGPT-4 (OpenAI) wrote this. Contact <email>. See [S1] and [S2].',
  );
  assert.ok(!/A\. Author/.test(text), 'author byline stripped');
  assert.ok(!/me@example\.io/.test(text), 'contact email stripped');
  assert.ok(!/gpt-4/i.test(text) && !/openai/i.test(text), 'model/vendor self-mentions stripped');
  assert.ok(text.includes('[S1]') && text.includes('[S2]'), 'evidence anchors (citations) preserved');
  assert.ok(redactions >= 4, `redaction count recorded (got ${redactions})`);
});

test('anonymizeForScoring is idempotent (re-running strips nothing more)', () => {
  const once = anonymizeForScoring('Author: J. Doe <<email>> used Claude.').text;
  const twice = anonymizeForScoring(once);
  assert.equal(twice.text, once);
  assert.equal(twice.redactions, 0);
});

test('lengthNormalize collapses cosmetic whitespace, records lengths, drops no content', () => {
  const raw = 'a   b\t\tc\r\n\r\n\r\n\r\nd   \ne   ';
  const { text, original_length, normalized_length } = lengthNormalize(raw);
  assert.equal(text, 'a b c\n\nd\ne');
  assert.equal(original_length, raw.length);
  assert.ok(normalized_length < original_length, 'normalized length is recorded and shorter');
});

test('normalizeForScoring applies BOTH steps by default and can disable anonymization', () => {
  const doc = 'Author: Jane Smith\nClaude scored this.  [S1]';
  const on = normalizeForScoring(doc);
  assert.equal(on.anonymized, true);
  assert.ok(on.redactions >= 2);
  assert.ok(!/Jane Smith/.test(on.doc) && !/claude/i.test(on.doc));
  assert.ok(on.doc.includes('[S1]'));

  const off = normalizeForScoring(doc, { anonymize: false });
  assert.equal(off.anonymized, false);
  assert.equal(off.redactions, 0);
  assert.ok(/Jane Smith/.test(off.doc), 'identity kept when anonymization off');
  assert.ok(off.normalized_length <= off.original_length, 'length still normalized');
});

// --- anonymization + length-norm reach the LIVE scoring prompt ----------------------------

const identityDoc = [
  'Author: Dr. Jane Smith — contact: <email>',
  'Reviewed by Claude (Anthropic); an earlier draft was scored by GPT-4.',
  '',
  '# Methods',
  'A   reproducible    protocol with redundant     spacing.',
  '',
  '# PRISMA Flow',
  'Records identified, screened, included [S1].',
  '',
  '# Results',
  'Findings with citations [S2].',
].join('\n');

test('GIVEN a scoring call with anonymization ON, THEN the prompt has author/source identifiers stripped', async () => {
  const seen = [];
  const agent = async (prompt) => { seen.push(prompt); return { score: 0.9, citations: [] }; };

  const r = await scoreAgainstRubric({ doc: identityDoc, pack: testDocPack, agent });

  assert.ok(seen.length === testDocPack.rubric.criteria.length, 'one prompt per criterion');
  for (const prompt of seen) {
    assert.ok(!/jane\.smith@university\.edu/.test(prompt), 'contact email stripped from prompt');
    assert.ok(!/Jane Smith/.test(prompt), 'author byline stripped from prompt');
    assert.ok(!/claude/i.test(prompt) && !/anthropic/i.test(prompt), 'model/vendor stripped');
    assert.ok(!/gpt-4/i.test(prompt), 'second model self-mention stripped');
    assert.ok(prompt.includes('[S1]') && prompt.includes('[S2]'), 'citations preserved as evidence anchors');
    assert.ok(/independent of length/i.test(prompt) || /do NOT reward LENGTH/i.test(prompt),
      'prompt carries the length-blind instruction');
  }
  // The normalization is RECORDED on the result.
  assert.equal(r.normalization.anonymized, true);
  assert.ok(r.normalization.redactions >= 4, 'redactions recorded');
  assert.ok(r.normalization.normalized_length <= r.normalization.original_length, 'lengths recorded');
});

test('anonymization can be turned OFF (identity reaches the prompt; length still normalized)', async () => {
  const seen = [];
  const agent = async (prompt) => { seen.push(prompt); return { score: 0.9, citations: [] }; };
  const r = await scoreAgainstRubric({ doc: identityDoc, pack: testDocPack, agent, anonymize: false });
  assert.ok(seen.every((p) => /Jane Smith/.test(p)), 'identity kept when anonymization off');
  assert.equal(r.normalization.anonymized, false);
  assert.equal(r.normalization.redactions, 0);
  // length-normalization still collapses the redundant spacing in the prompt.
  assert.ok(seen.every((p) => !/protocol with redundant {2,}spacing/.test(p)), 'cosmetic whitespace collapsed');
});

test('the injected deterministic score seam is bias-free and keeps the RAW doc (normalization still recorded)', async () => {
  // Existing tests inject `score`; that path must be byte-for-byte unchanged. We only ADD the
  // recorded normalization metadata — the verdict/score are untouched.
  const r = await scoreAgainstRubric({ doc: litReviewClean, pack: litPack, score: litRubricScore });
  assert.equal(r.verdict, 'PASS');
  assert.equal(r.contract, 'rubric-score');
  assert.equal(r.normalization.anonymized, true);
  assert.equal(r.normalization.redactions, 0, 'the clean lit-review carries no identity markers');
});

// --- cross-family DEFAULT + degrade ladder ------------------------------------------------

test('the degrade ladder is the fixed best-first order', () => {
  assert.deepEqual(DEGRADE_LADDER, ['cross-family', 'same-family-fresh', 'attested-degrade']);
});

test('GIVEN no live cross-family key, WHEN a real gate runs, THEN it records an honest same-family degrade + attestation', async () => {
  // Default probe (defaultProbeCrossModel) returns null -> no second family reachable.
  const run = () => runDefaultRubricGate({
    doc: litReviewClean, pack: litPack,
    score: litRubricScore,
    authorServedModel: 'claude-opus-4-8',
  });
  const gate = await run();

  assert.equal(gate.gate_tier, 'same-family-fresh');
  assert.equal(gate.degraded, true, 'a same-family run is an honest degrade, not cross-family');
  assert.equal(gate.cross_family, false);
  assert.deepEqual(gate.attested_families, ['claude']);
  assert.equal(gate.independent_origins, 1, 'same-family agreement is one origin');
  assert.ok(gate.attestations.length >= 2, 'each fresh-context judge recorded a stamp');
  // The degrade is HONEST: each judge still carries a well-formed, attested SR-5 stamp.
  for (const a of gate.attestations) {
    assert.equal(a.model_attested, true);
    assert.equal(a.degraded, false);
    assert.equal(hasAttestation(a), true);
  }
  assert.ok(/no cross-family model reachable/.test(gate.degrade_reason), 'the reason is recorded');
  assert.equal(gate.verdict, 'PASS', 'the clean deliverable still passes the rubric');

  // Deterministic: a second run yields the identical tier/verdict/reason.
  const again = await run();
  assert.deepEqual(
    { tier: again.gate_tier, verdict: again.verdict, reason: again.degrade_reason, origins: again.independent_origins },
    { tier: gate.gate_tier, verdict: gate.verdict, reason: gate.degrade_reason, origins: gate.independent_origins },
  );
});

test('WHEN a second family IS reachable, the DEFAULT gate runs cross-family (top of the ladder)', async () => {
  const probe = () => ({ model: 'gemini-3.1-pro-preview', family: 'gemini' });
  const gate = await runDefaultRubricGate({
    doc: litReviewClean, pack: litPack, probe,
    score: litRubricScore,
    authorServedModel: 'claude-opus-4-8',
    secondFamilyServedModel: 'gemini-3.1-pro-preview',
  });
  assert.equal(gate.gate_tier, 'cross-family');
  assert.equal(gate.degraded, false);
  assert.equal(gate.cross_family, true);
  assert.deepEqual(gate.attested_families, ['claude', 'gemini']);
  assert.equal(gate.independent_origins, 2);
  assert.equal(gate.degrade_reason, null);
});

test('a cross-family AIM that the dispatcher SERVES same-family is recorded as an honest degrade (not cross-family)', async () => {
  // Probe claims gemini is reachable, but the dispatcher SERVES claude for that member.
  const probe = () => ({ model: 'gemini-3.1-pro-preview', family: 'gemini' });
  const gate = await runDefaultRubricGate({
    doc: litReviewClean, pack: litPack, probe,
    score: litRubricScore,
    authorServedModel: 'claude-opus-4-8',
    secondFamilyServedModel: 'claude-opus-4-8', // served same family despite the gemini aim
  });
  assert.equal(gate.gate_tier, 'cross-family', 'the AIM was cross-family...');
  assert.equal(gate.cross_family, false, '...but only one attested origin was served');
  assert.equal(gate.degraded, true);
  assert.equal(gate.independent_origins, 1);
  assert.ok(/served only 1 attested origin/.test(gate.degrade_reason));
});

test('with no attestable served model at all, the gate falls to the fully-degraded rung (honestly recorded)', async () => {
  const gate = await runDefaultRubricGate({
    doc: litReviewClean, pack: litPack,
    score: litRubricScore,
    // no authorServedModel -> cannot attest even a same-family judge
  });
  assert.equal(gate.gate_tier, 'attested-degrade');
  assert.equal(gate.degraded, true);
  assert.equal(gate.cross_family, false);
  assert.equal(gate.independent_origins, 0, 'no attested origin counts');
  assert.ok(gate.attestations.every((a) => a.model_attested === false && a.degraded === true));
});

// --- SR-6: the convergence Judge path stays byte-identical (imported, never forked) -------

test('SR-6: the convergence Judge (CONVERGED/NOT_CONVERGED) path is byte-identical', async () => {
  const stubAgent = async () => ({ decision: 'CONVERGED', reasons: [], blocking: [] });
  const judge = makeJudge({ agent: stubAgent });
  const v = await judge.decide({ northStar: 'NS', findings: [], acceptanceCriteria: [] });
  assert.equal(v.decision, 'CONVERGED');
  assert.equal(v.lockable, true);
});
