// Wave 9 — Autonomous-VERIFIED gate, part B (A4b): firewall subprocess + artifact-mint + recall roster.
//
// Exercises the REAL Wave-9 source (src/firewall-subprocess.mjs + the spawned test/sandbox-runner.mjs
// child) against the REAL Wave-4 adjudication substrate (over the REAL inherited durability substrate)
// and the REAL Wave-7 router + Wave-8 grammar, proving the done-when:
//   - the OUT-OF-MODEL child (node, no shell, per-claim hermetic temp dir, EXACT arithmetic) settles
//     100% of the P7 positive-recall roster — INCLUDING nested-composition expressions — VERIFIED;
//   - each minted artifact RE-EXECUTES to an identical content hash (the Wave-4/Wave-6 canary warrant);
//   - the explicit GWT: minting TWICE on the same input yields an IDENTICAL canonical SHA-256 hash, and
//     the canary's re-execution reproduces it;
//   - the Wave-4 POSITIVE path (deferred from Wave 4) now passes: a real subprocess artifact promotes a
//     claim to OBSERVED and is single-use;
//   - the firewall refuses to mint / settle an out-of-grammar computation (the grammar runs first).

import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import {
  SANDBOX_RUNNER,
  FIREWALL_DOMAIN,
  FIREWALL_FAMILY,
  SUBPROCESS_DECISION,
  FirewallSubprocessError,
  serializeAst,
  parseAst,
  runSubprocess,
  parseStdout,
  resultOf,
  screenAndRun,
  mintFirewallArtifact,
  firewallReexecute,
  firewallReexecutionAgrees,
  settleComputationViaFirewall,
  POSITIVE_RECALL_ROSTER,
  runPositiveRecallRoster,
} from '../src/firewall-subprocess.mjs';

import {
  int,
  rational,
  neg,
  add,
  mul,
  div,
  pow,
  variable,
  sum,
  product,
} from '../src/firewall-grammar.mjs';

import { ClaimLedger, RUNG, BELIEF } from '../src/claim-ledger.mjs';
import {
  loadDurabilitySubstrate,
  DurableNonceStore,
  AdjudicationDispatcher,
  adjudicatedPromoteToVerified,
  validateArtifact,
  runtimeFingerprint,
  canonicalStdoutHash,
  CANONICALIZATION_VERSION,
  VERDICT,
} from '../src/adjudication.mjs';

import {
  VerifyRouter,
  ROUTE_VERDICT,
  FIREWALL_FAMILY as ROUTER_FIREWALL_FAMILY,
} from '../src/verify-router.mjs';

// The REAL inherited durability substrate, resolved via the pinned manifest (matches Wave-4/6/8 setup).
const substrate = await loadDurabilitySubstrate();

let fileSeq = 0;
const scratchDirs = [];
function tmpFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-w9-'));
  scratchDirs.push(dir);
  return path.join(dir, `nonce-store-${fileSeq++}.checkpoint.json`);
}
function freshDispatcher(family = FIREWALL_FAMILY) {
  return new AdjudicationDispatcher({ store: DurableNonceStore.load(substrate, tmpFile()), family });
}
after(() => {
  for (const d of scratchDirs) {
    try { fs.rmSync(d, { recursive: true, force: true }); } catch { /* best-effort cleanup */ }
  }
});

const NESTED = sum('k', int(1), int(3), mul(variable('k'), int(2))); // sum_{k=1}^{3} (k*2) = 12

// =====================================================================================
// 0. The pinned subprocess contract — path, no-shell, hermetic temp dir.
// =====================================================================================

test('SANDBOX_RUNNER is the pinned win32 contract path test/sandbox-runner.mjs and exists', () => {
  assert.equal(path.basename(SANDBOX_RUNNER), 'sandbox-runner.mjs');
  assert.equal(path.basename(path.dirname(SANDBOX_RUNNER)), 'test');
  assert.ok(fs.existsSync(SANDBOX_RUNNER), 'the spawned child must exist on disk');
});

test('bigint-tagged AST serialization round-trips arbitrary-magnitude integers through JSON', () => {
  const big = int(10n ** 40n);
  const round = parseAst(serializeAst(big));
  assert.equal(round.type, 'int');
  assert.equal(round.value, 10n ** 40n);
  assert.equal(typeof round.value, 'bigint');
  // a mixed tree round-trips too (numbers stay numbers, strings stay strings, bigints stay bigints).
  const tree = add(int(2), mul(int('123456789012345678901234567890'), neg(int(7n))));
  assert.deepEqual(parseAst(serializeAst(tree)), tree);
});

test('runSubprocess runs a child node (no shell), hashes canonical stdout, and removes its hermetic temp dir', () => {
  const run = runSubprocess(add(int(2), int(3)));
  assert.match(run.stdout_hash, /^[0-9a-f]{64}$/);
  assert.equal(run.exit_code, 0);
  // hermetic: the per-call temp dir is under os.tmpdir() and no longer exists after the call.
  assert.ok(run.hermeticDir.startsWith(os.tmpdir()), 'temp dir is under the OS temp root');
  assert.match(path.basename(run.hermeticDir), /^ramanujan-fw-/);
  assert.equal(fs.existsSync(run.hermeticDir), false, 'the hermetic temp dir must be removed per call');
  // the stdout is canonical and exact: 2 + 3 = 5/1.
  assert.deepEqual(resultOf(run.stdout), { num: '5', den: '1' });
});

test('the child stamps a runtime fingerprint { node_major, canonicalization_version } INTO the hashed stdout', () => {
  const run = runSubprocess(int(6));
  const rf = parseStdout(run.stdout).runtime_fingerprint;
  assert.equal(rf.node_major, Number(String(process.versions.node).split('.')[0]));
  assert.equal(rf.canonicalization_version, CANONICALIZATION_VERSION);
});

// =====================================================================================
// 1. Exact arithmetic — bigint rationals, NO float.
// =====================================================================================

test('the subprocess evaluates over EXACT rational arithmetic (no float): 22/7 stays 22/7', () => {
  assert.deepEqual(resultOf(runSubprocess(div(int(22), int(7))).stdout), { num: '22', den: '7' });
  // exact rationals combine exactly: 1/2 + 1/3 = 5/6.
  assert.deepEqual(resultOf(runSubprocess(add(rational(1, 2), rational(1, 3))).stdout), { num: '5', den: '6' });
  // a big-integer literal is exact (arbitrary magnitude).
  assert.deepEqual(
    resultOf(runSubprocess(int('999999999999999999999999999999')).stdout),
    { num: '999999999999999999999999999999', den: '1' },
  );
});

// =====================================================================================
// 2. THE GWT — mint TWICE on the same input => identical hash; the canary re-executes.
// =====================================================================================

test('GWT: minting TWICE on the same in-class input (a bounded sum of products) yields an IDENTICAL canonical SHA-256 hash', () => {
  const dispatcher = freshDispatcher();
  const { artifact: a1 } = mintFirewallArtifact(dispatcher, 'gwt-1', NESTED);
  const { artifact: a2 } = mintFirewallArtifact(dispatcher, 'gwt-2', NESTED);
  // exact-arithmetic determinism: same input => same canonical stdout => same content hash.
  assert.equal(a1.stdout_hash, a2.stdout_hash, 'two mints on the same input must share one stdout_hash');
  // the nonces still differ (single-use, monotone) — only the content hash is shared.
  assert.notEqual(a1.nonce, a2.nonce);
  // and the canary RE-EXECUTION (re-run the child on the same input) reproduces the hash.
  assert.equal(firewallReexecute(NESTED).stdout_hash, a1.stdout_hash);
  assert.equal(firewallReexecutionAgrees(a1, NESTED), true);
});

test('a fabricated/forged stdout_hash does NOT re-execute (the canary catches a same-family lie)', () => {
  const dispatcher = freshDispatcher();
  const { artifact } = mintFirewallArtifact(dispatcher, 'forge', NESTED);
  const forged = { ...artifact, stdout_hash: canonicalStdoutHash('___FORGED___' + '0'.repeat(64)).replace(/.$/, '0') };
  // a forged hash (or the hash of a DIFFERENT computation) cannot reproduce by re-execution.
  assert.equal(firewallReexecutionAgrees(forged, NESTED), false);
  // re-executing a DIFFERENT in-class input against the genuine artifact also disagrees.
  assert.equal(firewallReexecutionAgrees(artifact, add(int(1), int(1))), false);
});

// =====================================================================================
// 3. THE P7 POSITIVE-RECALL ROSTER — 100% settled VERIFIED, each re-executes to its hash.
// =====================================================================================

test('the positive-recall roster is substantial and carries nested-composition cases', () => {
  assert.ok(POSITIVE_RECALL_ROSTER.length >= 8, `expected >=8 recall computations (got ${POSITIVE_RECALL_ROSTER.length})`);
  const nested = POSITIVE_RECALL_ROSTER.filter((e) => e.nested);
  assert.ok(nested.length >= 1, 'the roster must include at least one nested-composition expression');
});

test('done-when: the subprocess SETTLES 100% of the positive-recall roster VERIFIED, each re-executing to an identical hash', () => {
  const report = runPositiveRecallRoster({ makeDispatcher: () => freshDispatcher() });
  assert.equal(report.total, POSITIVE_RECALL_ROSTER.length);
  assert.ok(report.nestedCount >= 1, 'a nested-composition expression is part of the settled roster');
  assert.equal(report.allVerified, true, `every roster entry must settle VERIFIED: ${report.results.filter((r) => !r.settled).map((r) => r.name).join(', ')}`);
  assert.equal(report.allReexecute, true, `every minted artifact must re-execute: ${report.results.filter((r) => !r.reexecutes).map((r) => r.name).join(', ')}`);
  assert.equal(report.allResultsMatch, true, `every result must match its expected exact value: ${report.results.filter((r) => !r.resultMatches).map((r) => `${r.name}(${JSON.stringify(r.got)}!=${JSON.stringify(r.expected)})`).join(', ')}`);
  // each entry reached OBSERVED with the firewall family-of-record.
  for (const r of report.results) {
    assert.equal(r.verdict, VERDICT.VERIFIED, `${r.name} verdict`);
    assert.equal(r.rung, RUNG.OBSERVED, `${r.name} rung`);
    assert.equal(r.family, FIREWALL_FAMILY, `${r.name} family`);
  }
});

test('each roster entry, settled individually, lands OBSERVED/VERIFIED and re-executes to its artifact hash', () => {
  for (let i = 0; i < POSITIVE_RECALL_ROSTER.length; i++) {
    const entry = POSITIVE_RECALL_ROSTER[i];
    const ledger = new ClaimLedger();
    const dispatcher = freshDispatcher();
    const id = `single-${i}`;
    ledger.assert({ id, type: 'computational' });
    const settle = settleComputationViaFirewall(ledger, dispatcher, id, entry.expr);
    assert.equal(settle.settled, true, `${entry.name} must settle`);
    assert.equal(settle.verdict, VERDICT.VERIFIED);
    assert.equal(settle.reexecutes, true, `${entry.name} must re-execute to its artifact hash`);
    assert.deepEqual(settle.result, entry.expected, `${entry.name} exact result`);
    assert.equal(ledger.rungOf(id), RUNG.OBSERVED);
    assert.equal(ledger.beliefOf(id), BELIEF.VERIFIED);
    // the artifact is well-formed and carries the P9 runtime fingerprint.
    assert.deepEqual(validateArtifact(settle.artifact), { ok: true, failures: [] });
    assert.deepEqual(settle.artifact.runtime_fingerprint, runtimeFingerprint());
  }
});

// =====================================================================================
// 4. THE WAVE-4 POSITIVE PATH (deferred from Wave 4) now passes.
// =====================================================================================

test('Wave-4 positive path: a REAL subprocess artifact promotes a claim to OBSERVED through adjudicatedPromoteToVerified', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  ledger.assert({ id: 'w4pos', type: 'computational' });

  const { artifact } = mintFirewallArtifact(dispatcher, 'w4pos', NESTED);
  const gate = adjudicatedPromoteToVerified(ledger, 'w4pos', { artifact, dispatcher });
  assert.equal(gate.verdict, VERDICT.VERIFIED);
  assert.equal(gate.family, FIREWALL_FAMILY);
  assert.equal(ledger.rungOf('w4pos'), RUNG.OBSERVED);
  assert.equal(ledger.beliefOf('w4pos'), BELIEF.VERIFIED);
  // the promote stamp records the out-of-model family-of-record (sole writer = the dispatcher).
  const promoteEvent = ledger.get('w4pos').history.find((h) => h.event === 'promote');
  assert.equal(promoteEvent.family, FIREWALL_FAMILY);

  // and the artifact's stdout_hash genuinely re-executes (the canary warrant) — Wave-4's POSITIVE arm.
  assert.equal(firewallReexecutionAgrees(artifact, NESTED), true);

  // single-use: re-presenting the same (now spent) artifact ABSTAINs and does NOT re-flip.
  const replay = adjudicatedPromoteToVerified(ledger, 'w4pos', { artifact, dispatcher });
  assert.equal(replay.verdict, VERDICT.ABSTAIN);
  assert.equal(ledger.rungOf('w4pos'), RUNG.OBSERVED);
});

test('across-restart replay of a real subprocess artifact is rejected (durable single-use nonce reloads from disk)', () => {
  const file = tmpFile();
  const d1 = new AdjudicationDispatcher({ store: DurableNonceStore.load(substrate, file), family: FIREWALL_FAMILY });
  const led1 = new ClaimLedger();
  led1.assert({ id: 'X', type: 'computational' });
  const { artifact } = mintFirewallArtifact(d1, 'X', NESTED);
  assert.equal(adjudicatedPromoteToVerified(led1, 'X', { artifact, dispatcher: d1 }).verdict, VERDICT.VERIFIED);

  // simulated restart: a brand-new dispatcher/store that reloads ONLY from disk.
  const d2 = new AdjudicationDispatcher({ store: DurableNonceStore.load(substrate, file), family: FIREWALL_FAMILY });
  const led2 = new ClaimLedger();
  led2.assert({ id: 'X', type: 'computational' });
  const replay = adjudicatedPromoteToVerified(led2, 'X', { artifact, dispatcher: d2 });
  assert.equal(replay.verdict, VERDICT.ABSTAIN, 'a real artifact cannot replay across a restart');
  assert.equal(led2.rungOf('X'), RUNG.UNVERIFIED);
});

// =====================================================================================
// 5. THE FIREWALL — out-of-grammar is refused BEFORE any child is spawned.
// =====================================================================================

test('screenAndRun ABSTAINs an out-of-grammar computation and never spawns a child', () => {
  // a float buried in an otherwise-valid tree (a Wave-8 deep-nested smuggle).
  const smuggled = add(mul(int(2), int(3)), add(int(4), { type: 'float', value: 0.001 }));
  const d = screenAndRun(smuggled);
  assert.equal(d.decision, SUBPROCESS_DECISION.ABSTAIN);
  assert.equal(d.inGrammar, false);
  assert.equal(d.route, 'out-of-model');
  assert.equal(d.stdout, undefined, 'no child ran, so there is no stdout');
});

test('mintFirewallArtifact REFUSES to mint an out-of-grammar computation (no laundering into an artifact)', () => {
  const dispatcher = freshDispatcher();
  assert.throws(
    () => mintFirewallArtifact(dispatcher, 'c', pow(int(2), variable('n'))), // symbolic exponent
    (e) => e instanceof FirewallSubprocessError && /out-of-grammar/.test(e.message),
  );
});

test('settleComputationViaFirewall ABSTAINs an out-of-grammar claim, raising NO rung', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  ledger.assert({ id: 'og', type: 'computational' });
  const settle = settleComputationViaFirewall(ledger, dispatcher, 'og', { type: 'integral', var: 'x', body: variable('x') });
  assert.equal(settle.verdict, VERDICT.ABSTAIN);
  assert.equal(settle.settled, false);
  assert.equal(settle.reexecutes, false);
  assert.equal(ledger.rungOf('og'), RUNG.UNVERIFIED);
  assert.equal(ledger.beliefOf('og'), BELIEF.CONJECTURAL);
});

// =====================================================================================
// 6. END-TO-END through the Wave-7 router — a minted artifact settles a routed claim.
// =====================================================================================

test('router integration: a subprocess-minted artifact flows through VerifyRouter.route to VERIFIED/OBSERVED', () => {
  assert.equal(FIREWALL_FAMILY, ROUTER_FIREWALL_FAMILY, 'the firewall family-of-record is shared with the router');
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });

  // decompose a computational claim carrying its in-grammar expr (the grammar front-end will accept it).
  router.decompose({ id: 'c1', type: 'computational', statement: 'bounded sum of products', expr: NESTED });
  const { artifact } = mintFirewallArtifact(dispatcher, 'c1', NESTED);
  const r = router.route('c1', { artifact });

  assert.equal(r.verdict, ROUTE_VERDICT.VERIFIED);
  assert.equal(r.settled, true);
  assert.equal(ledger.rungOf('c1'), RUNG.OBSERVED);
  assert.equal(ledger.beliefOf('c1'), BELIEF.VERIFIED);
  assert.equal(r.stamp.verifier_family, FIREWALL_FAMILY);
  assert.equal(r.stamp.artifact_backed, true);
  // and the artifact re-executes (the canary warrant behind the VERIFIED stamp).
  assert.equal(firewallReexecutionAgrees(artifact, NESTED), true);
});

test('router integration: an out-of-grammar claim with a VALID artifact still ABSTAINs (grammar runs first)', () => {
  const ledger = new ClaimLedger();
  const dispatcher = freshDispatcher();
  const router = new VerifyRouter({ ledger, dispatcher });

  // an out-of-grammar expr; mint a structurally-valid, claim-bound artifact anyway (via a raw subprocess
  // on an in-grammar surrogate) and present it — the grammar denies before the gate, so no VERIFIED rung.
  router.decompose({ id: 'c2', type: 'computational', expr: pow(int(2), variable('n')) });
  const surrogate = mintFirewallArtifact(dispatcher, 'c2', int(0)).artifact; // a real, claim-bound artifact
  const r = router.route('c2', { artifact: surrogate });
  assert.equal(r.verdict, ROUTE_VERDICT.ABSTAIN);
  assert.equal(ledger.rungOf('c2'), RUNG.UNVERIFIED);
  assert.notEqual(ledger.beliefOf('c2'), BELIEF.VERIFIED);
});
