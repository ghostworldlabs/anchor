// Wave 1 (F0) — tools manifest + persistent-server infra + per-class integrity probe gate.
//
// Two tiers, per the build-gate isolation contract (DESCRIPTION-INC2 §v2.1/§v2.2):
//
//  * FAST tier (always runs; the Foreman `node --test test/` gate). Exercises the probe LOGIC against
//    STUB executables + stub generate fns spawned BY ABSOLUTE PATH (no shell), so the two load-bearing
//    negative arms are proven WITHOUT any live tool:
//      - a stub `lean` that exits 0 on the false theorem `1+1=3` is QUARANTINED (deterministic);
//      - a cross-family stub that ACCEPTS a planted plausible-but-wrong proof fails the proof-judging
//        sentinel and is QUARANTINED from the PLAUSIBILITY-CORROBORATED path.
//    Starts NO server — the fast gate cannot hang on a tool.
//
//  * TOOL lane (env-gated RAMANUJAN_TOOL_TESTS=1, serial). Starts the persistent ollama server +
//    warm-up ONCE, runs every certifier's sentinels against the REAL tools by manifest absolute path
//    within the stated wall-clock budget, then kills the server process tree on teardown.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { TOOL_LANE, toolLaneSkip, TOOL_LANE_ENV } from './tool-lane.mjs';
import {
  DEFAULT_MANIFEST_PATH,
  TOOL_LANE_ENV as PROBE_TOOL_LANE_ENV,
  TOOL_CLASS,
  PROBE_STATUS,
  CROSS_FAMILY_TRIALS,
  PLAUSIBILITY_CORROBORATED,
  PhaseFProbeError,
  loadManifest,
  validateManifest,
  runExecutable,
  smokeReachable,
  LEAN_SENTINELS,
  Z3_SENTINELS,
  probeDeterministic,
  parseVerdict,
  CROSS_FAMILY_BATTERY,
  probeCrossFamilyModel,
  runDeterministicProbe,
  // v3 cross-family substrate (Gemini-PRIMARY via agy CLI + ollama-FALLBACK):
  CORROBORATED,
  CONJECTURAL,
  CROSS_FAMILY_TIER,
  FRONTIER_FAMILY,
  KNOWN_AGY_LABELS,
  GEMINI_FAIL_CLASS,
  agyStatusToFailClass,
  buildGeminiRequest,
  parseGeminiResponse,
  createGeminiGenerate,
  frontierCanarySelfTest,
  probeCrossFamily,
  // persistent-server infra (tool lane only):
  startOllamaServer,
  stopOllamaServer,
  warmUp,
  createOllamaGenerate,
} from '../src/phasef-probe.mjs';

// ---------------------------------------------------------------------------
// Stub executables — node scripts spawned BY ABSOLUTE PATH (path=node.exe, baseArgs=[stub]).
// ---------------------------------------------------------------------------

const STUB_DIR = path.join(os.tmpdir(), `ramanujan-f0-stubs-${crypto.randomBytes(6).toString('hex')}`);
fs.mkdirSync(STUB_DIR, { recursive: true });

function writeStub(name, body) {
  const p = path.join(STUB_DIR, name);
  fs.writeFileSync(p, body, 'utf8');
  return { path: process.execPath, baseArgs: [p] }; // a real spawn by absolute path, no shell
}

// A CORRECT lean: exit 0 iff the theorem statement is true (contains `= 2`), else exit 1.
const leanCorrect = writeStub('lean-correct.mjs', `
import fs from 'node:fs';
const src = fs.readFileSync(process.argv[2], 'utf8');
process.exit(/=\\s*2\\b/.test(src) ? 0 : 1);
`);
// A WRONG lean: exits 0 on EVERYTHING (incl. the false theorem 1+1=3). MUST be quarantined.
const leanWrong = writeStub('lean-wrong.mjs', `process.exit(0);\n`);

// A CORRECT z3: prints `unsat` for a (not ...) sentence, `sat` otherwise.
const z3Correct = writeStub('z3-correct.mjs', `
import fs from 'node:fs';
const src = fs.readFileSync(process.argv[2], 'utf8');
process.stdout.write(src.includes('(not') ? 'unsat\\n' : 'sat\\n');
`);
// A WRONG z3: always prints `sat` (so it says `sat` on the negation of a true sentence). MUST quarantine.
const z3Wrong = writeStub('z3-wrong.mjs', `process.stdout.write('sat\\n');\n`);

// A reachable stub "tool" that answers a version probe.
const versionStub = writeStub('version-stub.mjs', `process.stdout.write('stub-tool 9.9.9\\n');\n`);

test.after(() => { try { fs.rmSync(STUB_DIR, { recursive: true, force: true }); } catch { /* best-effort */ } });

// ---------------------------------------------------------------------------
// Stub cross-family generate fns (pure async — no network).
// ---------------------------------------------------------------------------

const isKnownTrue = (p) => p.includes('7 is a prime');
const isKnownFalse = (p) => p.includes('9 is a prime');
const isProofJudging = (p) => p.includes('VALID proof') || p.includes('VALID or INVALID');

async function genCorrect(prompt) {
  if (isKnownTrue(prompt)) return 'YES';
  if (isKnownFalse(prompt)) return 'NO';
  if (isProofJudging(prompt)) return 'INVALID';
  return 'NO';
}
async function genAlwaysAccept(prompt) {
  return 'YES'; // affirms everything => fails the known-false battery
}
async function genPassesBatteriesButAcceptsWrongProof(prompt) {
  if (isKnownTrue(prompt)) return 'YES';
  if (isKnownFalse(prompt)) return 'NO';
  if (isProofJudging(prompt)) return 'VALID'; // ACCEPTS the plausible-but-wrong proof
  return 'NO';
}
async function genUnparseable(prompt) {
  return 'I would need more context to be certain about that.';
}

// ===========================================================================
// FAST TIER — manifest schema.
// ===========================================================================

test('the shipped tools.manifest.json loads and validates', () => {
  const manifest = loadManifest();
  const v = validateManifest(manifest);
  assert.equal(v.ok, true, `manifest invalid: ${v.errors.join('; ')}`);
  // the canonical env var is pinned identically in the manifest, the probe, and the test helper
  assert.equal(manifest.tool_lane_env, TOOL_LANE_ENV);
  assert.equal(PROBE_TOOL_LANE_ENV, TOOL_LANE_ENV);
  // every tool is pinned by ABSOLUTE path
  for (const name of ['lean', 'z3', 'ollama']) {
    assert.equal(path.isAbsolute(manifest.tools[name].path), true, `${name}.path must be absolute`);
  }
  // ollama deterministic decoding is pinned (the bare `ollama run` default is NOT temp 0)
  assert.deepEqual(
    {
      t: manifest.tools.ollama.deterministic_decoding.temperature,
      k: manifest.tools.ollama.deterministic_decoding.top_k,
      p: manifest.tools.ollama.deterministic_decoding.top_p,
    },
    { t: 0, k: 1, p: 1 },
  );
  assert.equal(Number.isInteger(manifest.tools.ollama.deterministic_decoding.seed), true);
  assert.equal(manifest.tools.ollama.models.length >= 2, true);
});

test('validateManifest rejects a non-deterministic ollama decoding (temp != 0)', () => {
  const m = loadManifest();
  m.tools.ollama.deterministic_decoding.temperature = 1;
  const v = validateManifest(m);
  assert.equal(v.ok, false);
  assert.match(v.errors.join('|'), /temperature must be 0/);
});

test('validateManifest rejects a relative tool path, a wrong class, and a single-family panel', () => {
  let m = loadManifest();
  m.tools.lean.path = 'relative/lean';
  assert.match(validateManifest(m).errors.join('|'), /lean\.path must be an ABSOLUTE path/);

  m = loadManifest();
  m.tools.z3.class = 'probabilistic';
  assert.match(validateManifest(m).errors.join('|'), /z3 must be class deterministic/);

  m = loadManifest();
  m.tools.ollama.models = [{ name: 'only', family: 'qwen' }];
  assert.match(validateManifest(m).errors.join('|'), />=2/);

  m = loadManifest();
  m.tool_lane_env = 'WRONG';
  assert.match(validateManifest(m).errors.join('|'), /tool_lane_env must be/);
});

// ===========================================================================
// FAST TIER — parseVerdict.
// ===========================================================================

test('parseVerdict normalizes free text to YES / NO / UNPARSEABLE (decisive token wins)', () => {
  assert.equal(parseVerdict('YES'), 'YES');
  assert.equal(parseVerdict('no'), 'NO');
  assert.equal(parseVerdict('The statement is TRUE.'), 'YES');
  assert.equal(parseVerdict('This proof is INVALID.'), 'NO');
  // reasoning then a decisive conclusion: the LAST decisive token is the verdict
  assert.equal(parseVerdict('It might look valid, but it is actually INVALID.'), 'NO');
  assert.equal(parseVerdict('hmm, not sure'), 'UNPARSEABLE');
  assert.equal(parseVerdict(null), 'UNPARSEABLE');
});

// ===========================================================================
// FAST TIER — deterministic probe against stubs.
// ===========================================================================

test('deterministic probe: a CORRECT lean stub is TRUSTED', () => {
  const r = probeDeterministic('lean', leanCorrect, LEAN_SENTINELS);
  assert.equal(r.status, PROBE_STATUS.TRUSTED, r.reason || '');
  assert.equal(r.trusted, true);
  assert.equal(r.class, TOOL_CLASS.DETERMINISTIC);
  assert.equal(r.results.length, LEAN_SENTINELS.length);
});

test('GWT: a stub `lean` that exits 0 on `1+1=3` is QUARANTINED (deterministic negative sentinel)', () => {
  const r = probeDeterministic('lean', leanWrong, LEAN_SENTINELS);
  assert.equal(r.status, PROBE_STATUS.QUARANTINED);
  assert.equal(r.trusted, false);
  assert.match(r.reason, /lean:false-theorem-must-reject/);
  // it is QUARANTINED, not merely flagged — the failing sentinel is named
  const failed = r.results.find((x) => !x.accepted);
  assert.equal(failed.label, 'lean:false-theorem-must-reject');
});

test('deterministic probe: a CORRECT z3 stub is TRUSTED; an always-`sat` z3 is QUARANTINED', () => {
  assert.equal(probeDeterministic('z3', z3Correct, Z3_SENTINELS).status, PROBE_STATUS.TRUSTED);
  const wrong = probeDeterministic('z3', z3Wrong, Z3_SENTINELS);
  assert.equal(wrong.status, PROBE_STATUS.QUARANTINED);
  assert.match(wrong.reason, /z3:negation-of-true-must-be-unsat/);
});

test('deterministic probe: an UNREACHABLE tool path is not trusted (no crash)', () => {
  const r = probeDeterministic('lean', { path: path.join(STUB_DIR, 'does-not-exist.exe'), baseArgs: [] }, LEAN_SENTINELS);
  assert.equal(r.trusted, false);
  assert.equal(r.status, PROBE_STATUS.QUARANTINED);
  assert.match(r.reason, /UNREACHABLE/);
});

// ===========================================================================
// FAST TIER — cross-family probe against stub generate fns.
// ===========================================================================

test('cross-family probe: a CORRECT panel stub is TRUSTED (5/5 + rejects the wrong proof)', async () => {
  const r = await probeCrossFamilyModel('stub-qwen', genCorrect);
  assert.equal(r.status, PROBE_STATUS.TRUSTED, r.reason || '');
  assert.equal(r.class, TOOL_CLASS.PROBABILISTIC);
  // known-true + known-false each scored 5/5
  const kt = r.results.find((x) => x.label.endsWith('known-true'));
  assert.equal(kt.observation.correct, CROSS_FAMILY_TRIALS);
});

test('cross-family probe: an always-accept stub fails the known-false battery and is QUARANTINED', async () => {
  const r = await probeCrossFamilyModel('stub-yes', genAlwaysAccept);
  assert.equal(r.status, PROBE_STATUS.QUARANTINED);
  assert.match(r.reason, /known-false/);
  assert.deepEqual(r.disables, [PLAUSIBILITY_CORROBORATED]);
});

test('GWT: a cross-family stub that ACCEPTS a planted plausible-but-wrong proof is QUARANTINED from PLAUSIBILITY-CORROBORATED', async () => {
  const r = await probeCrossFamilyModel('stub-credulous', genPassesBatteriesButAcceptsWrongProof);
  assert.equal(r.status, PROBE_STATUS.QUARANTINED);
  assert.match(r.reason, /proof-judging|plausible-but-wrong/);
  assert.deepEqual(r.disables, [PLAUSIBILITY_CORROBORATED]);
  // the batteries passed; it is the proof-judging sentinel that quarantines it
  const pj = r.results.find((x) => x.label.endsWith('proof-judging'));
  assert.equal(pj.accepted, false);
  assert.equal(pj.observation.verdict, 'YES'); // it said the wrong proof was VALID
});

test('cross-family probe: an unparseable panel is QUARANTINED (no silent pass)', async () => {
  const r = await probeCrossFamilyModel('stub-vague', genUnparseable);
  assert.equal(r.status, PROBE_STATUS.QUARANTINED);
});

// ===========================================================================
// FAST TIER — v3 cross-family substrate (Gemini PRIMARY via agy CLI + ollama FALLBACK).
//
// No live Gemini / agy is needed here: the agy transport is INJECTED (runGemini) or the backend generate
// is stubbed, so the fast gate exercises the substrate's quarantine->fallback and HARD-FAULT logic and
// the fail-closed enumeration WITHOUT spawning agy. createGeminiGenerate takes an injected `runGemini`
// (prompt,label)=>{text,rec}; rec.ok truthy => the answer text, rec.ok===false => a typed
// PhaseFProbeError whose failClass is agyStatusToFailClass(rec.status). (§v3.1)
// ===========================================================================

const FAKE_KEY = 'AIza-FAKE-TEST-KEY-do-not-log-0000';

/** Shape a Gemini generateContent success body around an answer string (back-compat parseGeminiResponse). */
function geminiOk(text) {
  return { candidates: [{ content: { parts: [{ text }] } }] };
}
/** An injected agy transport stub: (prompt,label)=>{text,rec}. The fast tier injects this so NO agy spawns. */
const makeRunGemini = (text, rec = { ok: true, status: 'success' }) => async () => ({ text, rec });
const geminiSpec = () => loadManifest().tools.gemini;

test('the shipped manifest pins the Gemini PRIMARY + ollama FALLBACK cross-family substrate (v3)', () => {
  const m = loadManifest();
  assert.equal(m.cross_family.primary, 'gemini');
  assert.equal(m.cross_family.fallback, 'ollama');
  assert.equal(m.cross_family.frontier_rung, CORROBORATED);
  assert.equal(m.cross_family.fallback_rung, PLAUSIBILITY_CORROBORATED);
  assert.equal(m.cross_family.hard_fault_rung, CONJECTURAL);
  const g = m.tools.gemini;
  assert.equal(g.class, TOOL_CLASS.PROBABILISTIC);
  assert.equal(g.family, FRONTIER_FAMILY);
  assert.equal(g.kind, 'cli-agy');
  assert.equal(path.isAbsolute(g.driver_ref), true);
  assert.equal(g.model, 'Gemini 3.1 Pro (High)');
  assert.equal(KNOWN_AGY_LABELS.has(g.model), true);
  assert.equal(g.temperature, 0);
  assert.equal(Object.prototype.hasOwnProperty.call(g, 'path'), false, 'gemini is cli-agy: no local tool path');
});

test('validateManifest rejects a missing gemini, an API-style model id, and a non-pinned substrate', () => {
  let m = loadManifest(); delete m.tools.gemini;
  assert.match(validateManifest(m).errors.join('|'), /gemini is absent/);

  // an API-style id (NOT a known agy LABEL) — agy silently degrades it to Flash, so it is rejected.
  m = loadManifest(); m.tools.gemini.model = 'gemini-pro';
  assert.match(validateManifest(m).errors.join('|'), /known agy LABEL/);

  m = loadManifest(); m.tools.gemini.temperature = 1;
  assert.match(validateManifest(m).errors.join('|'), /gemini\.temperature must be 0/);

  m = loadManifest(); m.cross_family.primary = 'ollama';
  assert.match(validateManifest(m).errors.join('|'), /cross_family\.primary must be gemini/);

  m = loadManifest(); m.cross_family.frontier_rung = 'OBSERVED';
  assert.match(validateManifest(m).errors.join('|'), /frontier_rung must be CORROBORATED/);
});

test('buildGeminiRequest + parseGeminiResponse are retained as back-compat shaping helpers', () => {
  const { url, init } = buildGeminiRequest({ prompt: 'p', model: 'Gemini 3.1 Pro (High)', apiKey: FAKE_KEY });
  assert.equal(init.headers['x-goog-api-key'], FAKE_KEY);
  assert.equal(url.includes(FAKE_KEY), false, 'key must NOT appear in the URL (no query-param key)');
  assert.ok(url.includes('Gemini 3.1 Pro (High)'), 'the model label shapes the request path');
  assert.equal(parseGeminiResponse(geminiOk('hello')), 'hello');
  assert.equal(parseGeminiResponse({}), '');
});

test('createGeminiGenerate: an attested agy round-trip returns the answer text', async () => {
  const gen = createGeminiGenerate(geminiSpec(), { runGemini: makeRunGemini(' ... YES ... ', { ok: true, status: 'success', model_served: 'Gemini 3.1 Pro (High)', model_attested: true }) });
  assert.equal(await gen(CROSS_FAMILY_BATTERY.knownTrue.prompt), ' ... YES ... ');
});

test('createGeminiGenerate fail-closed enumeration maps agy statuses to fail classes', async () => {
  // agy served a DIFFERENT model than requested => ATTESTATION (the silent-Flash tripwire).
  const sub = createGeminiGenerate(geminiSpec(), { runGemini: makeRunGemini('', { ok: false, status: 'model_substituted', model_served: 'Gemini 3.5 Flash (Medium)' }) });
  await assert.rejects(sub('x'), (e) => e instanceof PhaseFProbeError && e.failClass === GEMINI_FAIL_CLASS.ATTESTATION);

  // a timeout / cli error => NETWORK.
  const to = createGeminiGenerate(geminiSpec(), { runGemini: makeRunGemini('', { ok: false, status: 'timeout' }) });
  await assert.rejects(to('x'), (e) => e.failClass === GEMINI_FAIL_CLASS.NETWORK);

  // agy returned no reply => BAD_RESPONSE.
  const noReply = createGeminiGenerate(geminiSpec(), { runGemini: makeRunGemini('', { ok: false, status: 'no_reply' }) });
  await assert.rejects(noReply('x'), (e) => e.failClass === GEMINI_FAIL_CLASS.BAD_RESPONSE);

  // the injected transport itself throwing => NETWORK (unreachable transport).
  const threw = createGeminiGenerate(geminiSpec(), { runGemini: async () => { throw new Error('agy spawn failed'); } });
  await assert.rejects(threw('x'), (e) => e.failClass === GEMINI_FAIL_CLASS.NETWORK);
});

test('agyStatusToFailClass maps each agy status to its fail-closed class', () => {
  assert.equal(agyStatusToFailClass('model_substituted'), GEMINI_FAIL_CLASS.ATTESTATION);
  assert.equal(agyStatusToFailClass('unattested_model'), GEMINI_FAIL_CLASS.ATTESTATION);
  assert.equal(agyStatusToFailClass('timeout'), GEMINI_FAIL_CLASS.NETWORK);
  assert.equal(agyStatusToFailClass('cli_error'), GEMINI_FAIL_CLASS.NETWORK);
  assert.equal(agyStatusToFailClass('transport-error'), GEMINI_FAIL_CLASS.NETWORK);
  assert.equal(agyStatusToFailClass('no_reply'), GEMINI_FAIL_CLASS.BAD_RESPONSE);
  assert.equal(agyStatusToFailClass('unclassified-status'), GEMINI_FAIL_CLASS.HTTP_ERROR);
});

test('frontierCanarySelfTest passes ONLY when the verdict is reproduced AND correct (verdict-level, not a hash)', async () => {
  const stable = await frontierCanarySelfTest(async () => 'YES');
  assert.equal(stable.passed, true);
  assert.equal(stable.reproducible, true);
  assert.equal(stable.correct, true);

  let flip = 0;
  const flaky = await frontierCanarySelfTest(async () => (flip++ % 2 === 0 ? 'YES' : 'NO'));
  assert.equal(flaky.reproducible, false);
  assert.equal(flaky.passed, false);

  const wrong = await frontierCanarySelfTest(async () => 'NO'); // reproducible but WRONG on a known-true
  assert.equal(wrong.reproducible, true);
  assert.equal(wrong.correct, false);
  assert.equal(wrong.passed, false);
});

test('probeCrossFamily: a healthy Gemini PRIMARY => tier=frontier, rung=CORROBORATED', async () => {
  const r = await probeCrossFamily(loadManifest(), { geminiGenerate: genCorrect });
  assert.equal(r.crossFamilyTrusted, true);
  assert.equal(r.tier, CROSS_FAMILY_TIER.FRONTIER);
  assert.equal(r.activeBackend, 'gemini');
  assert.equal(r.activeFamily, FRONTIER_FAMILY);
  assert.equal(r.rung, CORROBORATED);
  assert.equal(r.gemini.trusted, true);
  assert.equal(r.gemini.selfTest.passed, true);
  assert.equal(r.fallback, null);
});

test('GWT done-when: an agy ATTESTATION failure (served != requested) => QUARANTINE -> fallback to ollama (PLAUSIBILITY-CORROBORATED)', async () => {
  const geminiAttestFail = async () => { throw new PhaseFProbeError('agy substituted Flash', { failClass: GEMINI_FAIL_CLASS.ATTESTATION }); };
  const r = await probeCrossFamily(loadManifest(), { geminiGenerate: geminiAttestFail, ollamaGenerateFor: () => genCorrect });
  assert.equal(r.crossFamilyTrusted, true);
  assert.equal(r.tier, CROSS_FAMILY_TIER.FALLBACK);
  assert.equal(r.activeBackend, 'ollama');
  assert.equal(r.rung, PLAUSIBILITY_CORROBORATED);
  assert.equal(r.gemini.trusted, false);
  assert.equal(r.gemini.failClass, GEMINI_FAIL_CLASS.ATTESTATION);
});

test('GWT: an agy transport failure (NETWORK) quarantines Gemini -> fallback (fail-closed)', async () => {
  const geminiDown = createGeminiGenerate(geminiSpec(), { runGemini: makeRunGemini('', { ok: false, status: 'timeout' }) });
  const r = await probeCrossFamily(loadManifest(), { geminiGenerate: geminiDown, ollamaGenerateFor: () => genCorrect });
  assert.equal(r.tier, CROSS_FAMILY_TIER.FALLBACK);
  assert.equal(r.gemini.failClass, GEMINI_FAIL_CLASS.NETWORK);
});

test('GWT: a Gemini that ACCEPTS a planted plausible-but-wrong proof is quarantined from the frontier rung -> fallback', async () => {
  const r = await probeCrossFamily(loadManifest(), { geminiGenerate: genPassesBatteriesButAcceptsWrongProof, ollamaGenerateFor: () => genCorrect });
  assert.equal(r.gemini.status, PROBE_STATUS.QUARANTINED);
  assert.match(r.gemini.reason, /proof-judging|plausible-but-wrong/);
  assert.equal(r.tier, CROSS_FAMILY_TIER.FALLBACK);
  assert.equal(r.rung, PLAUSIBILITY_CORROBORATED);
});

test('GWT: Gemini quarantined AND the ollama fallback ALSO fails its sentinel => HARD-FAULT to CONJECTURAL (no silent pass)', async () => {
  const geminiDown = createGeminiGenerate(geminiSpec(), { runGemini: makeRunGemini('', { ok: false, status: 'model_substituted', model_served: 'Gemini 3.5 Flash (Medium)' }) });
  const r = await probeCrossFamily(loadManifest(), { geminiGenerate: geminiDown, ollamaGenerateFor: () => genPassesBatteriesButAcceptsWrongProof });
  assert.equal(r.crossFamilyTrusted, false);
  assert.equal(r.tier, CROSS_FAMILY_TIER.NONE);
  assert.equal(r.rung, CONJECTURAL);
  assert.equal(r.hardFault, true);
});

test('GWT no-rebuild: the SAME probe stamps fallback while Gemini is quarantined and frontier once agy attests (no code change)', async () => {
  const m = loadManifest();
  const whileDown = createGeminiGenerate(geminiSpec(), { runGemini: makeRunGemini('', { ok: false, status: 'timeout' }) });
  const before = await probeCrossFamily(m, { geminiGenerate: whileDown, ollamaGenerateFor: () => genCorrect });
  assert.equal(before.tier, CROSS_FAMILY_TIER.FALLBACK);

  // agy now attests + answers: the SAME manifest + SAME probeCrossFamily, only the backend now answers.
  const afterUp = createGeminiGenerate(geminiSpec(), { runGemini: async (prompt) => ({ text: await genCorrect(prompt), rec: { ok: true, status: 'success', model_served: 'Gemini 3.1 Pro (High)', model_attested: true } }) });
  const after = await probeCrossFamily(m, { geminiGenerate: afterUp, ollamaGenerateFor: () => genCorrect });
  assert.equal(after.tier, CROSS_FAMILY_TIER.FRONTIER);
  assert.equal(after.rung, CORROBORATED);
});

// ===========================================================================
// FAST TIER — smoke reachability + build-gate isolation.
// ===========================================================================

test('smokeReachable spawns a tool by absolute path; a bogus path reports unreachable (no throw)', () => {
  const ok = smokeReachable({ path: versionStub.path, version_args: [...versionStub.baseArgs, '--version'] });
  assert.equal(ok.reachable, true);
  assert.equal(ok.exitCode, 0);
  assert.match(ok.output, /stub-tool/);

  const bad = smokeReachable({ path: path.join(STUB_DIR, 'nope.exe'), version_args: ['--version'] });
  assert.equal(bad.reachable, false);
});

test('build-gate isolation: the fast lane is the default (RAMANUJAN_TOOL_TESTS unset => TOOL_LANE off)', () => {
  // This file is GREEN with the tool lane OFF: no server is started here, so the gate cannot hang.
  if (process.env[TOOL_LANE_ENV] !== '1') {
    assert.equal(TOOL_LANE, false);
  }
  assert.equal(typeof toolLaneSkip(), TOOL_LANE ? 'boolean' : 'string');
});

// ===========================================================================
// TOOL LANE — env-gated, serial, against the REAL tools + persistent ollama server.
// ===========================================================================

describe('F0 tool lane (real tools + persistent ollama)', { skip: toolLaneSkip(), concurrency: 1 }, () => {
  const manifest = loadManifest();
  let server = null;

  before(async () => {
    server = await startOllamaServer(manifest.tools.ollama);
    // pay the model cold-load ONCE per model and assert a FRESH-LOAD signal (not just a 200-OK)
    for (const m of manifest.tools.ollama.models) {
      await warmUp(manifest.tools.ollama, m.name, server.baseUrl);
    }
  }, { timeout: manifest.wall_clock_budget_ms.cross_family_warmup * manifest.tools.ollama.models.length + 60000 });

  after(async () => {
    await stopOllamaServer(server); // kills the ollama process TREE (taskkill /T on win32)
  });

  test('every tool is reachable by its manifest absolute path (clean-shell smoke)', () => {
    for (const name of ['lean', 'z3', 'ollama']) {
      const r = smokeReachable(manifest.tools[name]);
      assert.equal(r.reachable, true, `${name} unreachable at ${manifest.tools[name].path}`);
    }
  });

  test('deterministic class: real lean + z3 pass their per-class sentinels (GREEN within budget)', { timeout: manifest.wall_clock_budget_ms.deterministic_sentinel + 5000 }, () => {
    const t0 = Date.now();
    const probe = runDeterministicProbe(manifest);
    assert.equal(probe.allTrusted, true, JSON.stringify(probe.tools, null, 2));
    assert.equal(probe.tools.lean.status, PROBE_STATUS.TRUSTED);
    assert.equal(probe.tools.z3.status, PROBE_STATUS.TRUSTED);
    assert.ok(Date.now() - t0 < manifest.wall_clock_budget_ms.deterministic_sentinel, 'deterministic sentinels exceeded budget');
  });

  test('probabilistic class: each real cross-family model passes the 5/5 + proof-judging battery', { timeout: manifest.wall_clock_budget_ms.cross_family_sentinel * manifest.tools.ollama.models.length + 60000 }, async () => {
    for (const m of manifest.tools.ollama.models) {
      const generate = createOllamaGenerate(manifest.tools.ollama, m.name, server.baseUrl);
      const r = await probeCrossFamilyModel(m.name, generate);
      assert.equal(r.status, PROBE_STATUS.TRUSTED, `${m.name}: ${r.reason || ''}`);
    }
  });

  test('v3 cross-family substrate: the REAL Gemini PRIMARY is probed FIRST, then the active tier is stamped (frontier if credits, else fallback)', {
    timeout: manifest.wall_clock_budget_ms.frontier_selftest + manifest.wall_clock_budget_ms.cross_family_sentinel * manifest.tools.ollama.models.length + 60000,
  }, async () => {
    const geminiGenerate = createGeminiGenerate(manifest.tools.gemini, { env: process.env });
    const ollamaGenerateFor = (name) => createOllamaGenerate(manifest.tools.ollama, name, server.baseUrl);
    const r = await probeCrossFamily(manifest, { geminiGenerate, ollamaGenerateFor });
    // The system NEVER runs with an un-probed cross-family backend: it is TRUSTED at a STAMPED tier.
    assert.equal(r.crossFamilyTrusted, true, `cross-family HARD-FAULT: ${r.reason || ''} (gemini: ${r.gemini && r.gemini.reason})`);
    assert.ok([CROSS_FAMILY_TIER.FRONTIER, CROSS_FAMILY_TIER.FALLBACK].includes(r.tier), `tier must be stamped frontier|fallback (got ${r.tier})`);
    if (r.tier === CROSS_FAMILY_TIER.FRONTIER) {
      assert.equal(r.rung, CORROBORATED);
      assert.equal(r.gemini.selfTest.passed, true);
    } else {
      // today's expected path: Gemini at $0 credits => 429 => fallback to ollama (PLAUSIBILITY-CORROBORATED)
      assert.equal(r.rung, PLAUSIBILITY_CORROBORATED);
      assert.equal(r.gemini.trusted, false);
    }
  });
});
