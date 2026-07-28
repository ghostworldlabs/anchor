// drivers/test/gemini-cli.test.mjs — gate for the Gemini CLI HOST backend
// (`gemini-cli`): the login-based, sub-agent-capable `agy -p` driver (contrast the
// raw-HTTP `gemini` WORKER driver gated in backends.test.mjs).
//
// W0 (2026-07-05) — rewritten for the LIVE agy contract. The old `claude`/stream-json/
// `--skip-trust` transport (and its `stats.models` attestation, `resolveGeminiEntry`
// discovery, and stdin sentinel) is DEAD; this gate now exercises the new pure/
// deterministic seams with NO subprocess:
//   * buildGeminiCliArgs — the live agy argv (`-p`, `--log-file`, `--model "<LABEL>"`,
//     `--print-timeout`, and `--sandbox --add-dir` only for edit roles).
//   * finalTextFromTranscript — the last `source==='MODEL'` line of a transcript.jsonl.
//   * servedModelFromCliLog — allowlist + substitution-detection served-model attestation
//     read from an agy cli.log window (agy logs a model line ONLY when it substitutes).
//   * parseGeminiCliFrames — the THREE honest outcomes (substituted / clean-known / unattested).
//   * model-resolution precedence, the env gate, the prompt-suffix schema/retry/ABSTAIN
//     contract (identical to Claude), registry membership, the capability-matrix row.
//
// Exercises REAL source in drivers/gemini-cli.mjs + drivers/index.mjs.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { HaltError } from '../../foreman/bin/foreman-lib.mjs';
import {
  runAgent, getDriver, listDrivers, capabilityMatrix, geminiCliDriver,
  makeForemanDriver, registerDriver,
} from '../index.mjs';
import {
  parseGeminiCliFrames, resolveGeminiModel, buildGeminiCliArgs, defaultRunGeminiCli,
  finalTextFromTranscript, servedModelFromCliLog, approvalModeFor,
  shouldStopAttestationPoll,
  KNOWN_AGY_LABELS, GEMINI_HEAVY_MODEL, GEMINI_STANDARD_MODEL,
  DEFAULT_GEMINI_CLI_MODEL, DEFAULT_GEMINI_APPROVAL_MODE,
} from '../gemini-cli.mjs';

// --- argv shaping (live agy contract) ------------------------------------------

test('buildGeminiCliArgs: edit posture emits -p prompt, --log-file, --model LABEL, --print-timeout, --sandbox --add-dir <target>', () => {
  const args = buildGeminiCliArgs({
    prompt: 'STEER…\n\nthe real prompt', logPath: '/tmp/agy.log',
    model: GEMINI_HEAVY_MODEL, target: '/proj', readonly: false,
  });
  // Prompt goes via ARGV `-p` (NOT stdin — stdin truncates ~4KB on agy).
  assert.deepEqual(args.slice(args.indexOf('-p'), args.indexOf('-p') + 2), ['-p', 'STEER…\n\nthe real prompt']);
  // The conversation-id source: agy writes "Print mode: conversation=<id>" into --log-file.
  assert.deepEqual(args.slice(args.indexOf('--log-file'), args.indexOf('--log-file') + 2), ['--log-file', '/tmp/agy.log']);
  // Model is an agy LABEL, never an API-style id.
  assert.deepEqual(args.slice(args.indexOf('--model'), args.indexOf('--model') + 2), ['--model', GEMINI_HEAVY_MODEL]);
  // agy's own print-mode wait is set (value is a `<n>s` string aligned under our kill ceiling).
  const pt = args.indexOf('--print-timeout');
  assert.ok(pt !== -1, '--print-timeout is present');
  assert.match(args[pt + 1], /^\d+s$/);
  // Edit roles get a scoped auto-approving sandbox on the target dir.
  assert.deepEqual(args.slice(args.indexOf('--sandbox'), args.indexOf('--sandbox') + 3), ['--sandbox', '--add-dir', '/proj']);
  // The dead flags are gone (they hard-error on live agy).
  assert.ok(!args.includes('--skip-trust'), '--skip-trust is dead');
  assert.ok(!args.includes('--output-format'), '--output-format stream-json is dead');
  assert.ok(!args.includes('--dangerously-skip-permissions'));
});

test('buildGeminiCliArgs: read-only posture OMITS --sandbox/--add-dir (reviewers/judges do not edit)', () => {
  const args = buildGeminiCliArgs({
    prompt: 'p', logPath: '/tmp/l', model: GEMINI_STANDARD_MODEL, target: '/proj', readonly: true,
  });
  assert.ok(!args.includes('--sandbox'), 'no sandbox for a read-only seat');
  assert.ok(!args.includes('--add-dir'), 'no add-dir for a read-only seat');
  // The core argv is still intact.
  assert.deepEqual(args.slice(args.indexOf('--model'), args.indexOf('--model') + 2), ['--model', GEMINI_STANDARD_MODEL]);
  assert.ok(args.includes('-p') && args.includes('--log-file') && args.includes('--print-timeout'));
});

test('buildGeminiCliArgs: model defaults to the heavy LABEL when omitted', () => {
  const args = buildGeminiCliArgs({ prompt: 'p', logPath: '/tmp/l' });
  assert.deepEqual(args.slice(args.indexOf('--model'), args.indexOf('--model') + 2), ['--model', DEFAULT_GEMINI_CLI_MODEL]);
  assert.equal(DEFAULT_GEMINI_CLI_MODEL, GEMINI_HEAVY_MODEL, 'the default is the heavy agy LABEL, not a phantom API id');
});

// --- transcript reply reader ---------------------------------------------------

test('finalTextFromTranscript: returns the LAST source===MODEL content from a JSONL transcript', () => {
  const jsonl = [
    JSON.stringify({ source: 'USER', content: 'Output exactly: PONG' }),
    JSON.stringify({ source: 'MODEL', content: 'thinking out loud, first turn' }),
    JSON.stringify({ source: 'TOOL', content: 'read_file(...)' }),
    JSON.stringify({ source: 'MODEL', content: '  FINAL answer  ' }),
  ].join('\n');
  // isText:true drives the pure string path (no file / no subprocess); content is trimmed.
  assert.equal(finalTextFromTranscript(jsonl, { isText: true }), 'FINAL answer');
});

test('finalTextFromTranscript: blank + non-JSON lines are skipped; no MODEL line -> empty string', () => {
  const jsonl = ['', 'not json at all', JSON.stringify({ source: 'USER', content: 'hi' }), '   '].join('\n');
  assert.equal(finalTextFromTranscript(jsonl, { isText: true }), '');
});

// --- served-model attestation from cli.log -------------------------------------

test('servedModelFromCliLog (a): resolve-failure + override -> substituted, served = override LABEL', () => {
  // Live agy shape for an UNRECOGNIZED id: it fails to resolve then propagates the override.
  const win = [
    'Resolving model gemini-3.1-pro',
    'Failed to resolve model flag gemini-3.1-pro: gemini-3.1-pro is not recognized as a valid model',
    'Propagating selected model override to backend: label="Gemini 3.5 Flash (Medium)"',
  ].join('\n');
  assert.deepEqual(
    servedModelFromCliLog(win, { requested: 'gemini-3.1-pro' }),
    { served: 'Gemini 3.5 Flash (Medium)', substituted: true },
  );
});

test('servedModelFromCliLog (b): empty window + a KNOWN label -> clean serve attested by ABSENCE', () => {
  // agy writes NO model line on a clean serve of a catalogued label, so absence == clean.
  assert.ok(KNOWN_AGY_LABELS.has(GEMINI_HEAVY_MODEL), 'the heavy label is catalogued');
  assert.deepEqual(
    servedModelFromCliLog('', { requested: GEMINI_HEAVY_MODEL }),
    { served: GEMINI_HEAVY_MODEL, substituted: false },
  );
});

test('servedModelFromCliLog (c): empty window + an uncatalogued id -> cannot attest', () => {
  assert.deepEqual(
    servedModelFromCliLog('', { requested: 'gemini-3.1-pro' }),
    { served: null, substituted: false },
  );
});

// --- the three honest parseGeminiCliFrames outcomes ----------------------------

test('parseGeminiCliFrames (a) substituted -> ok:false, status:model_substituted, attests the override', () => {
  const { text, rec } = parseGeminiCliFrames('a reply body', {
    label: 'x', cli_status: 0,
    requested_model: 'gemini-3.1-pro',
    served_model: 'Gemini 3.5 Flash (Medium)', substituted: true,
  });
  assert.equal(text, 'a reply body');
  assert.equal(rec.ok, false, 'a silent cross-family degrade is NEVER a success');
  assert.equal(rec.status, 'model_substituted');
  // We DID attest what served — that is how we know it was substituted.
  assert.equal(rec.model_attested, true);
  assert.equal(rec.model_served, 'Gemini 3.5 Flash (Medium)');
  assert.equal(rec.model_family, 'gemini');
  assert.equal(rec.degraded, false);
  assert.equal(rec.requested_model, 'gemini-3.1-pro');
});

test('parseGeminiCliFrames (b) clean known label (served===requested) -> ok:true, status:success, attested', () => {
  const { text, rec } = parseGeminiCliFrames('PONG', {
    label: 'x', cli_status: 0,
    requested_model: GEMINI_HEAVY_MODEL,
    served_model: GEMINI_HEAVY_MODEL, substituted: false,
  });
  assert.equal(text, 'PONG');
  assert.equal(rec.ok, true);
  assert.equal(rec.status, 'success');
  assert.equal(rec.model_attested, true);
  assert.equal(rec.model_served, GEMINI_HEAVY_MODEL);
  assert.equal(rec.model_family, 'gemini');
  assert.equal(rec.degraded, false);
});

test('parseGeminiCliFrames (c) uncatalogued id, served null -> ok:false, status:unattested_model, NOT attested', () => {
  const { rec } = parseGeminiCliFrames('some reply', {
    label: 'x', cli_status: 0,
    requested_model: 'gemini-3.1-pro',
    served_model: null, substituted: false,
  });
  assert.equal(rec.ok, false, 'we refuse to assume a clean serve for an id we cannot verify');
  assert.equal(rec.status, 'unattested_model');
  assert.equal(rec.model_attested, false);
  assert.equal(rec.model_served, null);
  assert.equal(rec.degraded, true, 'honest fallback: model_attested:false ∧ degraded:true');
});

// --- model resolution ----------------------------------------------------------

test('resolveGeminiModel: precedence opts > TRIO_MODEL_<ROLE> > TRIO_MODEL > GEMINI_MODEL > default', () => {
  assert.equal(resolveGeminiModel({ model: 'm-explicit', role: 'judge', env: { TRIO_MODEL: 'x' } }), 'm-explicit');
  assert.equal(resolveGeminiModel({ role: 'judge', env: { TRIO_MODEL_JUDGE: 'm-role', TRIO_MODEL: 'x' } }), 'm-role');
  assert.equal(resolveGeminiModel({ env: { TRIO_MODEL: 'm-trio', GEMINI_MODEL: 'g' } }), 'm-trio');
  assert.equal(resolveGeminiModel({ env: { GEMINI_MODEL: 'm-gem' } }), 'm-gem');
  assert.equal(resolveGeminiModel({ env: {} }), DEFAULT_GEMINI_CLI_MODEL);
});

test('approvalModeFor (back-compat posture): read-only roles -> plan, edit roles -> auto_edit, explicit wins', () => {
  for (const r of ['review', 'judge', 'shark', 'synthesizer', 'research']) {
    assert.equal(approvalModeFor({ role: r }), 'plan', `${r} must be read-only`);
  }
  for (const r of ['execute', 'fix', 'build']) {
    assert.equal(approvalModeFor({ role: r }), 'auto_edit', `${r} edits`);
  }
  // Derived from Foreman's label prefixes when no explicit role is given.
  assert.equal(approvalModeFor({ label: 'review:w1#0' }), 'plan');
  assert.equal(approvalModeFor({ label: 'execute:w1' }), 'auto_edit');
  assert.equal(approvalModeFor({ label: 'fix:w1.2' }), 'auto_edit');
  // Explicit approvalMode always wins; unknown role falls back to the default.
  assert.equal(approvalModeFor({ approvalMode: 'yolo', role: 'review' }), 'yolo');
  assert.equal(approvalModeFor({ role: 'mystery' }), DEFAULT_GEMINI_APPROVAL_MODE);
});

// --- env gate ------------------------------------------------------------------

test('env gate: live spawn HALTs unless CRUCIBLE_AGENT_LIVE=1 (no accidental billing)', () => {
  assert.throws(
    () => defaultRunGeminiCli('hi', 'l', { env: {} }),
    (e) => e instanceof HaltError && /live agent seam is disabled/.test(e.reason),
  );
});

// --- seam behavior through runAgent (injected stub, no subprocess) -------------

test('runAgent(gemini-cli, no schema): returns plain text via injected runGemini', async () => {
  const out = await runAgent({
    driver: 'gemini-cli', prompt: 'say hi',
    runGemini: async () => ({ text: 'hello from gemini', rec: { ok: true } }),
  });
  assert.equal(out, 'hello from gemini');
});

test('runAgent(gemini-cli) + schema: fenced JSON reply is parsed', async () => {
  const out = await runAgent({
    driver: 'gemini-cli', prompt: 'review', schema: { type: 'object' },
    runGemini: async () => ({ text: '```json\n{"answerable":"yes","findings":[]}\n```', rec: {} }),
  });
  assert.equal(out.answerable, 'yes');
  assert.deepEqual(out.findings, []);
});

test('runAgent(gemini-cli) + schema: unparseable first reply retries once then succeeds', async () => {
  let calls = 0;
  const out = await runAgent({
    driver: 'gemini-cli', prompt: 'review', schema: { type: 'object' },
    runGemini: async () => { calls += 1; return { text: calls === 1 ? 'not json' : '{"answerable":"yes"}', rec: {} }; },
  });
  assert.equal(calls, 2, 'one initial call + exactly one retry');
  assert.equal(out.answerable, 'yes');
});

test('runAgent(gemini-cli) + schema: unparseable twice -> ABSTAIN (answerable:no)', async () => {
  let calls = 0;
  const out = await runAgent({
    driver: 'gemini-cli', prompt: 'review', schema: { type: 'object' }, label: 'rev:gem',
    runGemini: async () => { calls += 1; return { text: 'never json', rec: {} }; },
  });
  assert.equal(calls, 2, 'initial + one retry, then abstain (no infinite retry)');
  assert.equal(out.answerable, 'no');
  assert.deepEqual(out.findings, []);
  assert.match(out.note, /not parseable/i);
});

// --- registry + capability matrix ----------------------------------------------

test('registry: gemini-cli is registered and selectable via TRIO_DRIVER', () => {
  assert.ok(listDrivers().includes('gemini-cli'));
  assert.equal(getDriver(null, { TRIO_DRIVER: 'gemini-cli' }), geminiCliDriver);
  // explicit arg still overrides; the default with no env stays claude.
  assert.equal(getDriver('claude', { TRIO_DRIVER: 'gemini-cli' }).name, 'claude');
  assert.equal(getDriver(null, {}).name, 'claude');
});

test('capability matrix: gemini-cli is sub-agent-capable (a real HOST), gemini (HTTP) is not', () => {
  const by = Object.fromEntries(capabilityMatrix().map((r) => [r.name, r]));
  assert.equal(by['gemini-cli'].subAgentCapable, true, 'the CLI host spawns real fresh sub-agents');
  assert.equal(by.gemini.subAgentCapable, false, 'the raw-HTTP worker does not');
  assert.match(by['gemini-cli'].structuredOutput, /cli-subagent/i);
});

test('makeForemanDriver forwards role + model to the backend (per-role tier reachable)', async () => {
  const captured = [];
  registerDriver({ name: 'capture-role-backend', async runAgent(opts) { captured.push(opts); return 'ok'; } });
  const drv = await makeForemanDriver({ driver: 'capture-role-backend', model: 'm-designated', role: 'judge' });
  const ctx = { wave: { n: 1, title: 't' }, reviewerIndex: 0, projectDir: '/p', iteration: 1 };
  await drv.execute(ctx);
  assert.equal(captured.length, 1);
  assert.equal(captured[0].model, 'm-designated', 'designated model reaches the backend (was dropped before)');
  assert.equal(captured[0].role, 'judge', 'role reaches the backend so TRIO_MODEL_<ROLE> is resolvable');
  assert.match(captured[0].label, /execute:w1/);
});

// --- live smoke: SKIP (never fail) unless explicitly opted in ------------------

test('gemini-cli live smoke', { skip: process.env.GEMINI_CLI_LIVE ? false : 'set GEMINI_CLI_LIVE=1 for the live smoke' }, async () => {
  const prev = process.env.CRUCIBLE_AGENT_LIVE;
  process.env.CRUCIBLE_AGENT_LIVE = '1';
  try {
    const out = await runAgent({ driver: 'gemini-cli', prompt: 'Reply with the single word: pong' });
    assert.match(String(out), /pong/i);
  } finally {
    if (prev === undefined) delete process.env.CRUCIBLE_AGENT_LIVE; else process.env.CRUCIBLE_AGENT_LIVE = prev;
  }
});

test('gemini-cli live timeout: a tiny timeoutMs kills the child -> typed status:timeout', { skip: process.env.GEMINI_CLI_LIVE ? false : 'set GEMINI_CLI_LIVE=1' }, async () => {
  const prev = process.env.CRUCIBLE_AGENT_LIVE;
  process.env.CRUCIBLE_AGENT_LIVE = '1';
  try {
    const { rec } = await defaultRunGeminiCli('Take as long as you like.', 'timeout-probe', { timeoutMs: 1 });
    assert.equal(rec.status, 'timeout');
    assert.equal(rec.ok, false);
    assert.equal(rec.model_attested, false, 'a killed run cannot attest a served model');
  } finally {
    if (prev === undefined) delete process.env.CRUCIBLE_AGENT_LIVE; else process.env.CRUCIBLE_AGENT_LIVE = prev;
  }
});

// --- B2 (2026-07-11): the attestation poll's happy-path tail ---------------------
// Pre-fix, EVERY successful Gemini call paid the full 40x250ms (~10s) poll because a
// clean serve of a known label never writes the substitution line the loop waited
// for. The poll now stops early on attest-by-absence; the tripwire is unchanged.

test('B2: known label + readable evidence-free window stops after the grace (attest-by-absence)', () => {
  const known = GEMINI_HEAVY_MODEL;
  // inside the grace: keep polling (straggler substitution lines land slightly async)
  assert.equal(shouldStopAttestationPoll({ cliWindow: '', requested: known, elapsedMs: 0 }), null);
  assert.equal(shouldStopAttestationPoll({ cliWindow: 'unrelated log noise', requested: known, elapsedMs: 1750 }), null);
  // grace elapsed, window readable, no evidence: decided — stop
  assert.equal(shouldStopAttestationPoll({ cliWindow: '', requested: known, elapsedMs: 2000 }), 'known-label-clean');
  // and servedModelFromCliLog stamps the clean serve for that same window
  const attest = servedModelFromCliLog('', { requested: known });
  assert.equal(attest.served, known);
  assert.equal(attest.substituted, false);
});

test('B2: substitution evidence stops IMMEDIATELY at any tick (tripwire intact)', () => {
  const known = GEMINI_HEAVY_MODEL;
  const win = `Failed to resolve model flag ${known}\nPropagating selected model override to backend: label="Gemini 3.5 Flash (Medium)"`;
  assert.equal(shouldStopAttestationPoll({ cliWindow: win, requested: known, elapsedMs: 0 }), 'substitution-evidence');
  const attest = servedModelFromCliLog(win, { requested: known });
  assert.equal(attest.substituted, true, 'the substitution still stamps ok:false downstream');
});

test('B2: unknown labels and unreadable windows never stop early (conservative full poll)', () => {
  // uncatalogued id: attest-by-absence is impossible — poll the full window
  assert.equal(shouldStopAttestationPoll({ cliWindow: '', requested: 'gemini-9.9-imaginary', elapsedMs: 9999 }), null);
  // unreadable cli.log (null window): we cannot attest what we could not read
  assert.equal(shouldStopAttestationPoll({ cliWindow: null, requested: GEMINI_STANDARD_MODEL, elapsedMs: 9999 }), null);
});

// ---------------------------------------------------------------------------
// Oversized-prompt file delivery (2026-07-16, journal crucible/0004): past the
// argv-safe ceiling the FULL prompt rides in promptFile and -p carries only a
// short pointer — live Item-F Sharks died silently past ~32KB argv without this.
// ---------------------------------------------------------------------------

test('buildGeminiCliArgs: promptFile swaps -p to a short pointer naming the file (readonly posture)', () => {
  const big = 'X'.repeat(50000);
  const args = buildGeminiCliArgs({
    prompt: big, promptFile: 'C:/tmp/call-1/prompt.md', logPath: 'C:/tmp/agy.log',
    model: 'M', readonly: true,
  });
  const p = args[args.indexOf('-p') + 1];
  assert.ok(p.length < 1000, 'argv prompt is the SHORT pointer, not the payload');
  assert.ok(p.includes('C:/tmp/call-1/prompt.md'), 'pointer names the prompt file');
  assert.match(p, /file-read tool/i, 'pointer instructs the in-process read');
  assert.ok(!p.includes('XXXX'), 'payload is NOT on argv');
  assert.ok(!args.includes('--sandbox'), 'readonly posture unchanged');
});

test('buildGeminiCliArgs: sandboxed posture with promptFile adds --add-dir for the prompt file dir', () => {
  const args = buildGeminiCliArgs({
    prompt: 'x', promptFile: 'C:/tmp/call-2/prompt.md', logPath: 'C:/tmp/agy.log',
    model: 'M', readonly: false, target: 'C:/proj',
  });
  const dirs = args.reduce((acc, a, i) => (a === '--add-dir' ? acc.concat(args[i + 1]) : acc), []);
  assert.ok(dirs.includes('C:/proj'), 'target still added');
  assert.ok(dirs.includes('C:/tmp/call-2'), 'prompt-file dir added so the sandbox can READ it');
});

test('buildGeminiCliArgs: no promptFile ⇒ unchanged legacy shape (-p carries the full prompt)', () => {
  const args = buildGeminiCliArgs({ prompt: 'hello world', logPath: 'L', model: 'M', readonly: true });
  assert.equal(args[args.indexOf('-p') + 1], 'hello world');
});

test('servedModelFromCliLog: the benign resolver "defaulting to CCPA" line does NOT flag a substitution (2026-07-17)', () => {
  // VERIFIED LIVE: agy serves REAL Gemini despite this line (the model self-identified as
  // "Gemini 3.1 Pro"). Treating the line as a substitution was a false positive that would fail
  // every genuine Gemini serve over to Claude. A KNOWN label + this line ⇒ clean serve.
  const win = 'I0717 resolver.go:85] Model ID Gemini 3.1 Pro (High) not in local config, defaulting to CCPA\n'
    + 'model_resolver.go:62] Resolving model Gemini 3.1 Pro (High)\n'
    + 'model_config_manager.go:213] Propagating selected model override to backend: label="Gemini 3.1 Pro (High)"';
  const out = servedModelFromCliLog(win, { requested: 'Gemini 3.1 Pro (High)' });
  assert.equal(out.substituted, false, 'the benign defaulting line must NOT be treated as a substitution');
  assert.equal(out.served, 'Gemini 3.1 Pro (High)');
});
