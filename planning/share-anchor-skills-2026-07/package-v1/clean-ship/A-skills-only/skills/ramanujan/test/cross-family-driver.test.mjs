// Wave 2 — F1a: cross-family driver (v3 substrate: GEMINI-PRIMARY + ollama-FALLBACK, verdict-level).
//
// Two tiers, per the build-gate isolation contract (DESCRIPTION-INC2 §v2.1/§v2.2 + §v3.1 fast-gate
// isolation extends to Gemini):
//
//  * FAST tier (always runs; the Foreman `node --test test/` gate). Drives the driver with an INJECTED
//    agy transport — a `geminiGenerate`/`runGemini` stub for the PRIMARY and an `ollamaGenerateFor` stub
//    for the FALLBACK — so it runs with NO live Gemini/agy and no live ollama, and cannot hang. It proves
//    the wave's contract:
//      - the driver returns a PARSED verdict stamped with the ACTUAL non-Claude backend (verifier_family
//        + tier: frontier=Gemini via agy | fallback=ollama);
//      - the v3 substrate ordering: Gemini PRIMARY (agy) first, GRACEFUL FALLBACK to ollama on every
//        fail-closed class — the agy `runGemini` returns { text, rec }; rec.ok===false (e.g.
//        status:'model_substituted' => ATTESTATION, 'timeout' => NETWORK) or a thrown transport
//        (=> NETWORK) quarantines the PRIMARY and falls back to ollama;
//      - two runs on the same prompt that wrap the SAME answer in DIFFERENT chrome are VERDICT-LEVEL
//        reproducible (same verdict + normalized_answer_hash) while transcript_hash DIFFERS — and the
//        reproducibility assertion never touches transcript_hash;
//      - the seam HARD-FAULTS on the `claude` family (cannot launder a same-family verdict).
//
//  * TOOL lane (env-gated RAMANUJAN_TOOL_TESTS=1, serial). Drives the REAL v3 substrate (Gemini PRIMARY
//    via the agy CLI — falling back to the real persistent ollama server when Gemini is unavailable)
//    TWICE on the same prompt and asserts the parsed verdict + normalized_answer_hash MATCH while
//    transcript_hash is NOT asserted equal.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';

import { toolLaneSkip } from './tool-lane.mjs';
import {
  loadManifest,
  startOllamaServer,
  stopOllamaServer,
  warmUp,
  createOllamaGenerate,
  GEMINI_FAIL_CLASS,
} from '../src/phasef-probe.mjs';
import {
  HEX64,
  ARTIFACT_FIELDS,
  REPRODUCIBILITY_KEY_FIELDS,
  TIER,
  CrossFamilyDriverError,
  promptHash,
  normalizeAnswer,
  normalizedAnswerHash,
  transcriptHash,
  makeVerdictRecord,
  validateArtifact,
  verdictReproducible,
  resolveModel,
  driveCrossFamilyVerdict,
  driveFromManifest,
  driveCrossFamily,
  buildGeminiRequest,
  GEMINI_HOST,
  GEMINI_BASE_URL,
} from '../src/cross-family-driver.mjs';

// ---------------------------------------------------------------------------
// Stub transports (pure async — no network). The chrome-varying stub returns the SAME answer wrapped in
// DIFFERENT chrome/whitespace on each call, modeling a real non-byte-reproducible model run.
// ---------------------------------------------------------------------------

function chromeVaryingGen(answerCore) {
  let n = 0;
  const chromes = [
    () => `${answerCore}`,
    () => `\x1B[32m${answerCore}\x1B[0m\n`, // ANSI green + reset + trailing newline
    () => `   ${answerCore.toUpperCase()}  \r\n`, // whitespace + CR + case
    () => `⠋⠙ ${answerCore} `, // a leading braille spinner glyph or two
  ];
  return async function generate() {
    const chrome = chromes[n % chromes.length];
    n += 1;
    return chrome();
  };
}

/** A recognizable fake key — retained for the back-compat buildGeminiRequest shaping test. */
const FAKE_KEY = 'AIzaSyTEST-DO-NOT-LOG-cross-family-0123456789';

// ===========================================================================
// FAST TIER — normalization + hashing primitives.
// ===========================================================================

test('normalizeAnswer strips ANSI chrome, the braille spinner, whitespace, and case', () => {
  assert.equal(normalizeAnswer('\x1B[32mYES\x1B[0m\n'), 'yes');
  assert.equal(normalizeAnswer('   Yes  \r\n'), 'yes');
  assert.equal(normalizeAnswer('⠋⠙⠹ NO '), 'no');
  assert.equal(normalizeAnswer('the   proof\tis\nVALID'), 'the proof is valid');
  assert.equal(normalizeAnswer(null), '');
});

test('the normalized hash is chrome-invariant; the transcript hash is chrome-sensitive', () => {
  const plain = 'YES';
  const dressed = '\x1B[32m  yes \x1B[0m\r\n';
  assert.equal(normalizedAnswerHash(plain), normalizedAnswerHash(dressed)); // chrome-invariant
  assert.notEqual(transcriptHash(plain), transcriptHash(dressed)); // provenance-sensitive
  assert.match(normalizedAnswerHash(plain), HEX64);
  assert.match(transcriptHash(plain), HEX64);
});

test('promptHash requires a non-empty prompt and is a 64-hex digest', () => {
  assert.match(promptHash('is 7 prime?'), HEX64);
  assert.throws(() => promptHash(''), CrossFamilyDriverError);
  assert.throws(() => promptHash(null), CrossFamilyDriverError);
});

// ===========================================================================
// FAST TIER — the v3 verdict record + artifact (verifier_family + tier).
// ===========================================================================

test('makeVerdictRecord mints a parsed verdict + the EXACT-field v3 artifact (verifier_family + tier)', () => {
  const rec = makeVerdictRecord({
    model: 'Gemini 3.1 Pro (High)',
    verifier_family: 'Gemini',
    tier: TIER.FRONTIER,
    prompt: 'Is 7 a prime number? Answer YES or NO.',
    rawAnswer: '\x1B[32mYES\x1B[0m\n',
  });
  assert.equal(rec.verdict, 'YES');
  assert.equal(rec.normalized_answer, 'yes');
  // the artifact is EXACTLY the frozen v3 field set — no more, no less
  assert.deepEqual(Object.keys(rec.artifact).sort(), [...ARTIFACT_FIELDS].sort());
  assert.equal(rec.artifact.verifier_family, 'gemini'); // folded, non-Claude, ACTUAL backend
  assert.equal(rec.artifact.tier, 'frontier');
  assert.equal(rec.artifact.verdict, 'YES');
  assert.match(rec.artifact.prompt_hash, HEX64);
  assert.match(rec.artifact.normalized_answer_hash, HEX64);
  assert.match(rec.artifact.transcript_hash, HEX64);
  // the artifact is frozen (Wave 3 cannot be handed a mutable object)
  assert.throws(() => { rec.artifact.verdict = 'NO'; });
});

test('makeVerdictRecord accepts `family` as a legacy alias for verifier_family (single-backend callers)', () => {
  const rec = makeVerdictRecord({ model: 'qwen2.5', family: 'qwen', tier: TIER.FALLBACK, prompt: 'p', rawAnswer: 'YES' });
  assert.equal(rec.artifact.verifier_family, 'qwen');
  assert.equal(rec.artifact.tier, 'fallback');
});

test('GWT: the seam HARD-FAULTS on the `claude` family (no same-family laundering)', () => {
  assert.throws(
    () => makeVerdictRecord({ model: 'opus', verifier_family: 'claude', tier: TIER.FRONTIER, prompt: 'p', rawAnswer: 'YES' }),
    /claude/i,
  );
  assert.throws(
    () => makeVerdictRecord({ model: 'opus', family: 'CLAUDE', tier: TIER.FALLBACK, prompt: 'p', rawAnswer: 'YES' }),
    CrossFamilyDriverError,
  );
});

test('makeVerdictRecord rejects a missing model / verifier_family / bad tier / non-string rawAnswer', () => {
  assert.throws(() => makeVerdictRecord({ verifier_family: 'qwen', tier: TIER.FALLBACK, prompt: 'p', rawAnswer: 'YES' }), CrossFamilyDriverError);
  assert.throws(() => makeVerdictRecord({ model: 'm', tier: TIER.FALLBACK, prompt: 'p', rawAnswer: 'YES' }), CrossFamilyDriverError);
  assert.throws(() => makeVerdictRecord({ model: 'm', verifier_family: 'qwen', tier: 'bogus', prompt: 'p', rawAnswer: 'YES' }), /tier/);
  assert.throws(() => makeVerdictRecord({ model: 'm', verifier_family: 'qwen', tier: TIER.FALLBACK, prompt: 'p' }), CrossFamilyDriverError);
});

test('validateArtifact accepts the exact v3 shape and rejects extras / claude / bad tier / bad hashes / missing', () => {
  const good = makeVerdictRecord({ model: 'm', verifier_family: 'llama', tier: TIER.FALLBACK, prompt: 'p', rawAnswer: 'NO' }).artifact;
  assert.equal(validateArtifact(good).ok, true, JSON.stringify(validateArtifact(good).failures));

  const extra = { ...good, smuggled: 'x' };
  assert.match(validateArtifact(extra).failures.join('|'), /unexpected field: smuggled/);

  // 2026-07: the ban message is now GENERATOR-RELATIVE (verifier ≠ generator;
  // default generator = claude, so a claude verdict still fails by default).
  const claude = { ...good, verifier_family: 'claude' };
  assert.match(validateArtifact(claude).failures.join('|'), /must NOT equal the generator family \(claude\)/);

  const badTier = { ...good, tier: 'frontierish' };
  assert.match(validateArtifact(badTier).failures.join('|'), /tier must be one of/);

  const badHash = { ...good, normalized_answer_hash: 'not-hex' };
  assert.match(validateArtifact(badHash).failures.join('|'), /normalized_answer_hash must be a 64-hex/);

  const { transcript_hash, ...missing } = good;
  assert.match(validateArtifact(missing).failures.join('|'), /missing field: transcript_hash/);
});

// ===========================================================================
// FAST TIER — verdict-level reproducibility (the wave's headline contract).
// ===========================================================================

test('the reproducibility key is verdict + normalized_answer_hash (NEVER transcript_hash)', () => {
  assert.deepEqual([...REPRODUCIBILITY_KEY_FIELDS], ['verdict', 'normalized_answer_hash']);
  assert.equal(REPRODUCIBILITY_KEY_FIELDS.includes('transcript_hash'), false);
});

test('GWT: driving the SAME prompt twice (chrome differs) is VERDICT-LEVEL reproducible; transcript_hash differs', async () => {
  const prompt = 'A claim is sent to qwen2.5. Is "7 is prime" true? Answer YES or NO.';
  const generate = chromeVaryingGen('yes'); // same answer, different chrome each call

  const run1 = await driveCrossFamilyVerdict(null, { model: 'qwen2.5', family: 'qwen', prompt }, { generate });
  const run2 = await driveCrossFamilyVerdict(null, { model: 'qwen2.5', family: 'qwen', prompt }, { generate });

  // parsed verdict from a NON-CLAUDE family, stamped fallback tier (single ollama drive)
  assert.equal(run1.verdict, 'YES');
  assert.equal(run1.artifact.verifier_family, 'qwen');
  assert.equal(run1.artifact.tier, 'fallback');
  assert.notEqual(run1.artifact.verifier_family, 'claude');

  // verdict-level reproducible: SAME verdict + SAME normalized_answer_hash; same prompt => same prompt_hash
  assert.equal(run1.artifact.verdict, run2.artifact.verdict);
  assert.equal(run1.artifact.normalized_answer_hash, run2.artifact.normalized_answer_hash);
  assert.equal(run1.artifact.prompt_hash, run2.artifact.prompt_hash);

  // transcript_hash is PROVENANCE ONLY — here it DIFFERS (the chrome varied) and is NOT the key
  assert.notEqual(run1.artifact.transcript_hash, run2.artifact.transcript_hash);

  const rep = verdictReproducible(run1, run2);
  assert.equal(rep.reproducible, true, rep.reasons.join('; '));
});

test('verdictReproducible ignores transcript_hash but catches a real verdict/normalized divergence', () => {
  const a = makeVerdictRecord({ model: 'm', verifier_family: 'qwen', tier: TIER.FALLBACK, prompt: 'p', rawAnswer: 'YES' });
  const bSame = makeVerdictRecord({ model: 'm', verifier_family: 'qwen', tier: TIER.FALLBACK, prompt: 'p', rawAnswer: '  yes\n' });
  const cDiff = makeVerdictRecord({ model: 'm', verifier_family: 'qwen', tier: TIER.FALLBACK, prompt: 'p', rawAnswer: 'NO' });

  assert.notEqual(a.artifact.transcript_hash, bSame.artifact.transcript_hash);
  assert.equal(verdictReproducible(a, bSame).reproducible, true);

  const r = verdictReproducible(a, cDiff);
  assert.equal(r.reproducible, false);
  assert.match(r.reasons.join('|'), /verdict differs/);

  assert.equal(verdictReproducible(null, a).reproducible, false);
});

// ===========================================================================
// FAST TIER — manifest resolution + the single-backend driver guards.
// ===========================================================================

test('resolveModel finds a panel model by exact name AND by family', () => {
  const m = loadManifest();
  const byFamily = resolveModel(m, 'qwen');
  assert.equal(byFamily.family, 'qwen');
  assert.match(byFamily.name, /qwen/);
  const byName = resolveModel(m, byFamily.name);
  assert.deepEqual(byName, byFamily);
  assert.throws(() => resolveModel(m, 'gpt4'), CrossFamilyDriverError);
});

test('driveFromManifest resolves the model and drives a fallback-tier verdict with an injected generate', async () => {
  const m = loadManifest();
  const rec = await driveFromManifest(m, 'qwen', 'Is 7 prime? YES/NO.', { generate: async () => 'YES' });
  assert.equal(rec.verdict, 'YES');
  assert.equal(rec.artifact.verifier_family, 'qwen');
  assert.equal(rec.artifact.tier, 'fallback');
  assert.match(rec.artifact.model, /qwen/);
  assert.equal(validateArtifact(rec.artifact).ok, true);
});

test('driveCrossFamilyVerdict requires a prompt, and a network call needs ollamaSpec + baseUrl', async () => {
  await assert.rejects(
    () => driveCrossFamilyVerdict(null, { model: 'm', family: 'qwen', prompt: '' }, { generate: async () => 'YES' }),
    CrossFamilyDriverError,
  );
  await assert.rejects(
    () => driveCrossFamilyVerdict({}, { model: 'm', family: 'qwen', prompt: 'p' }, {}),
    /injected generate|baseUrl/,
  );
});

// ===========================================================================
// FAST TIER — the v3 substrate driver: GEMINI-PRIMARY, graceful ollama-FALLBACK.
// ===========================================================================

test('driveCrossFamily uses the frontier Gemini PRIMARY when it answers (tier=frontier, family=gemini)', async () => {
  const m = loadManifest();
  const rec = await driveCrossFamily(m, 'Is 7 prime? YES or NO.', {
    geminiGenerate: async () => 'YES',
    // the fallback transport is present but MUST NOT be reached
    ollamaGenerateFor: () => async () => { throw new Error('fallback must not run when Gemini answers'); },
  });
  assert.equal(rec.backend, 'gemini');
  assert.equal(rec.tier, 'frontier');
  assert.equal(rec.artifact.tier, 'frontier');
  assert.equal(rec.artifact.verifier_family, 'gemini');
  assert.equal(rec.verdict, 'YES');
  assert.equal(rec.gemini_quarantine, null);
  assert.equal(validateArtifact(rec.artifact).ok, true);
});

test('GWT: an agy ATTESTATION failure (served != requested) GRACEFULLY FALLS BACK to ollama (tier=fallback, family=qwen)', async () => {
  const m = loadManifest();
  const rec = await driveCrossFamily(m, 'Is 7 prime? YES or NO.', {
    // agy served Flash instead of the requested frontier LABEL -> ATTESTATION -> fallback.
    runGemini: async () => ({ text: '', rec: { ok: false, status: 'model_substituted', model_served: 'Gemini 3.5 Flash (Medium)' } }),
    ollamaGenerateFor: () => async () => 'YES',
    fallbackModelOrFamily: 'qwen',
  });
  assert.equal(rec.backend, 'ollama');
  assert.equal(rec.tier, 'fallback');
  assert.equal(rec.artifact.tier, 'fallback');
  assert.equal(rec.artifact.verifier_family, 'qwen');
  assert.notEqual(rec.artifact.verifier_family, 'claude');
  assert.equal(rec.verdict, 'YES');
  assert.equal(rec.gemini_quarantine.failClass, GEMINI_FAIL_CLASS.ATTESTATION);
});

test('FAST-GATE ISOLATION: an agy transport that throws (NETWORK) quarantines the PRIMARY -> fallback', async () => {
  const m = loadManifest();
  // the injected agy transport throws (unreachable) => NETWORK => the fast gate never touches the network.
  const rec = await driveCrossFamily(m, 'Is 7 prime? YES or NO.', {
    runGemini: async () => { throw new Error('agy spawn failed'); },
    ollamaGenerateFor: () => async () => 'NO',
  });
  assert.equal(rec.backend, 'ollama');
  assert.equal(rec.tier, 'fallback');
  assert.equal(rec.gemini_quarantine.failClass, GEMINI_FAIL_CLASS.NETWORK);
  assert.equal(rec.verdict, 'NO');
});

test('driveCrossFamily two runs (fallback, chrome differs) are VERDICT-LEVEL reproducible; transcript_hash differs', async () => {
  const m = loadManifest();
  const gen = chromeVaryingGen('yes');
  const opts = { env: {}, ollamaGenerateFor: () => gen, fallbackModelOrFamily: 'qwen' };
  const run1 = await driveCrossFamily(m, 'Is 7 prime? YES or NO.', opts);
  const run2 = await driveCrossFamily(m, 'Is 7 prime? YES or NO.', opts);

  assert.equal(run1.tier, 'fallback');
  assert.equal(run1.artifact.verdict, run2.artifact.verdict);
  assert.equal(run1.artifact.normalized_answer_hash, run2.artifact.normalized_answer_hash);
  assert.notEqual(run1.artifact.transcript_hash, run2.artifact.transcript_hash); // provenance only
  assert.equal(verdictReproducible(run1, run2).reproducible, true);
});

test('driveCrossFamily HARD-FAULTS when Gemini is down AND no fallback transport is available', async () => {
  const m = loadManifest();
  await assert.rejects(
    () => driveCrossFamily(m, 'p', { env: {} }), // no gemini key, no ollamaGenerateFor, no baseUrl
    /FALLBACK needs|no cross-family backend/,
  );
});

test('driveCrossFamily requires a non-empty prompt', async () => {
  await assert.rejects(() => driveCrossFamily(loadManifest(), '', { env: {} }), CrossFamilyDriverError);
});

// ===========================================================================
// FAST TIER — the retained back-compat request shaper + the agy quarantine record.
// (The live transport is the agy CLI via a login — there is no API key to leak.)
// ===========================================================================

test('buildGeminiRequest (back-compat) shapes a generateContent request with the key in the header only', () => {
  const req = buildGeminiRequest({ prompt: 'p', model: 'Gemini 3.1 Pro (High)', apiKey: FAKE_KEY, baseUrl: GEMINI_BASE_URL });
  assert.equal(req.init.headers['x-goog-api-key'], FAKE_KEY); // the key IS the transport header
  assert.ok(req.url.startsWith(`https://${GEMINI_HOST}`), 'pinned TLS host'); // TLS + pinned host
  assert.equal(req.url.includes(FAKE_KEY), false, 'the key must NOT appear in the URL');
  assert.equal(/[?&]key=/.test(req.url), false, 'the key must NOT be a URL query param');
});

test('the agy quarantine record carries the typed failClass and no api-key-shaped secret leaks into the result', async () => {
  const m = loadManifest();
  const rec = await driveCrossFamily(m, 'Is 7 prime? YES or NO.', {
    // agy served Flash instead of the requested frontier LABEL -> ATTESTATION -> fallback.
    runGemini: async () => ({ text: '', rec: { ok: false, status: 'model_substituted', model_served: 'Gemini 3.5 Flash (Medium)' } }),
    ollamaGenerateFor: () => async () => 'YES',
    fallbackModelOrFamily: 'qwen',
  });

  assert.equal(rec.backend, 'ollama');
  assert.equal(rec.tier, 'fallback');
  assert.notEqual(rec.artifact.verifier_family, 'claude');
  assert.equal(rec.gemini_quarantine.failClass, GEMINI_FAIL_CLASS.ATTESTATION);
  // the login-based agy transport carries no API key, so nothing key-shaped can appear in the record.
  assert.equal(JSON.stringify(rec).includes('AIza'), false, 'no api-key-shaped secret in the persisted record');
});

// ===========================================================================
// TOOL LANE — env-gated, serial, against the REAL v3 substrate (Gemini PRIMARY / ollama FALLBACK).
// ===========================================================================

describe('F1a tool lane (real v3 substrate, verdict-level reproducibility)', { skip: toolLaneSkip(), concurrency: 1 }, () => {
  const manifest = loadManifest();
  const ollamaSpec = manifest.tools.ollama;
  const qwen = ollamaSpec.models.find((m) => m.family === 'qwen');
  let server = null;

  before(async () => {
    // The ollama FALLBACK must be warm: Gemini is at $0 credits today (429), so the real driver
    // falls back to ollama. (When Gemini credits are topped up the driver simply runs frontier.)
    server = await startOllamaServer(ollamaSpec);
    await warmUp(ollamaSpec, qwen.name, server.baseUrl);
  }, { timeout: manifest.wall_clock_budget_ms.cross_family_warmup + 60000 });

  after(async () => {
    await stopOllamaServer(server); // kills the ollama process TREE
  });

  test('GWT: the same prompt driven twice over the real substrate yields the SAME normalized verdict (transcript_hash NOT asserted equal)', {
    timeout: manifest.wall_clock_budget_ms.cross_family_sentinel + 60000,
  }, async () => {
    const prompt = 'Answer with exactly one word, YES or NO. Is the following statement true? "7 is a prime number."';
    const opts = { env: process.env, baseUrl: server.baseUrl, fallbackModelOrFamily: 'qwen' };

    const run1 = await driveCrossFamily(manifest, prompt, opts);
    const run2 = await driveCrossFamily(manifest, prompt, opts);

    // a PARSED verdict from the ACTUAL non-Claude backend, with the active tier stamped (frontier|fallback)
    assert.ok(['YES', 'NO'].includes(run1.verdict), `expected a parseable verdict, got ${run1.verdict}`);
    assert.ok([TIER.FRONTIER, TIER.FALLBACK].includes(run1.tier), `unexpected tier ${run1.tier}`);
    assert.notEqual(run1.artifact.verifier_family, 'claude');
    assert.equal(validateArtifact(run1.artifact).ok, true);

    // VERDICT-LEVEL reproducible: same verdict + same normalized_answer_hash. transcript_hash is
    // PROVENANCE ONLY and is deliberately NOT asserted equal here.
    const rep = verdictReproducible(run1, run2);
    assert.equal(rep.reproducible, true, rep.reasons.join('; '));
    assert.equal(run1.artifact.verdict, run2.artifact.verdict);
    assert.equal(run1.artifact.normalized_answer_hash, run2.artifact.normalized_answer_hash);
  });
});
