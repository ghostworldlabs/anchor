// test/engine-secret-triage.test.mjs — Wave 2, the UNIVERSAL pre-LLM gate.
//
// Frozen acceptance criteria covered here:
//
//   "Given a 40MB log whose AWS key sits beyond the LLM read cap, and a
//    zero-byte file named `id_rsa`, when the pre-LLM gate runs, then the
//    streaming full-content scan catches the deep key, the path/filename rule
//    catches `id_rsa`, both are flagged before any LLM stage receives any
//    excerpt, and a test asserts the assembled debate context contains no secret
//    bytes — masked or partial"
//
//   "Given a TRACKED file containing a live credential, when triage flags it,
//    then the offered remediation is an approvable `git rm --cached` untrack op
//    whose tile names the index-class change and states history rewrite is out
//    of scope, plus the .gitignore line — never a bare add-to-.gitignore"
//
// On the 40MB figure: the PROPERTY under test is "the secret sits beyond the
// LLM read cap, where the LLM stages would never have looked". The cap is
// LLM_READ_CAP_BYTES (500KB), so a 700KB file demonstrates it exactly as well
// as a 40MB one and does not make the suite take a minute. The test asserts
// against the constant, not against a hard-coded size, so raising the cap keeps
// the test honest instead of silently making it vacuous.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  triageFile, triageAll, buildRemediation, assertNoSecretBytes,
  LLM_READ_CAP_BYTES, shannonEntropy,
} from '../engine/secret-triage.mjs';
import { runPipeline } from '../engine/pipeline.mjs';
import { STAGES, LLM_STAGES, PRE_LLM_GATE_STAGE } from '../engine/stages/index.mjs';
import {
  makeTempRoot, rmTempRoot, initRepo, write, commitAll,
  recordingAgent, cooperativeResponder,
  FAKE_AWS_KEY_ID, FAKE_AWS_SECRET, FAKE_PRIVATE_KEY,
} from './helpers/git-fixture.mjs';

let root;

before(async () => { root = await makeTempRoot('tidy-idy-secret-'); });
after(async () => { await rmTempRoot(root); });

describe('the gate sits IN FRONT of every LLM stage (a structural property, not a convention)', () => {
  test('every LLM stage appears after the pre-LLM gate in the registry', () => {
    const order = STAGES.map((s) => s.name);
    const gateIndex = order.indexOf(PRE_LLM_GATE_STAGE);
    assert.ok(gateIndex >= 0, `the registry must contain the '${PRE_LLM_GATE_STAGE}' gate stage`);
    for (const llm of LLM_STAGES) {
      const i = order.indexOf(llm);
      assert.ok(i > gateIndex,
        `LLM stage '${llm}' runs at position ${i}, at or before the gate at ${gateIndex} — it would receive un-gated content`);
    }
  });
});

describe('path/filename rules fire without any content at all', () => {
  test('a ZERO-BYTE file named id_rsa is flagged on its name', async () => {
    const dir = path.join(root, 'names');
    await write(dir, 'id_rsa', '');
    const v = await triageFile({ rootPath: dir, rel: 'id_rsa' });
    assert.strictEqual(v.flagged, true, 'a zero-byte id_rsa must still be flagged — "we read nothing" is not evidence of safety');
    assert.ok(v.triggers.some((t) => t.class === 'path' && t.rule === 'ssh-private-key-name'));
    assert.strictEqual(v.size, 0);
  });

  test('an UNREADABLE secret-shaped path is still flagged, and the read failure is recorded', async () => {
    const dir = path.join(root, 'names');
    // A path that does not exist stands in for one we cannot open: the point is
    // that the path rule does not depend on the content scan succeeding.
    const v = await triageFile({ rootPath: dir, rel: 'secrets/prod.pem' });
    assert.strictEqual(v.flagged, true);
    assert.ok(v.readError, 'the failed read must be recorded as a coverage fact, not swallowed');
    assert.ok(v.triggers.some((t) => t.class === 'path'));
  });

  test('.env.example is exempt BY NAME but its CONTENT is still scanned', async () => {
    const dir = path.join(root, 'exempt');
    await write(dir, '.env.example', 'API_KEY=replace-me\n');
    const clean = await triageFile({ rootPath: dir, rel: '.env.example' });
    assert.strictEqual(clean.flagged, false, 'a documented placeholder must not be flagged on its name alone');

    await write(dir, '.env.example', `AWS_ACCESS_KEY_ID=${FAKE_AWS_KEY_ID}\n`);
    const dirty = await triageFile({ rootPath: dir, rel: '.env.example' });
    assert.strictEqual(dirty.flagged, true,
      'the name exemption must not exempt the CONTENT — a real key pasted into .env.example is still a real key');
    assert.ok(dirty.triggers.some((t) => t.rule === 'aws-access-key-id'));
  });
});

describe('content scanning is full-file, streaming, and exempt from the LLM read cap', () => {
  test('a key beyond the LLM read cap is caught (the LLM stages would never have looked)', async () => {
    const dir = path.join(root, 'deep');
    const padding = 'x'.repeat(LLM_READ_CAP_BYTES + 100 * 1024);
    await write(dir, 'app.log', `${padding}\nAWS_ACCESS_KEY_ID=${FAKE_AWS_KEY_ID}\ntail\n`);

    const v = await triageFile({ rootPath: dir, rel: 'app.log' });
    assert.ok(v.size > LLM_READ_CAP_BYTES, 'the fixture must actually exceed the cap or this test proves nothing');
    assert.strictEqual(v.flagged, true, 'the streaming scan must reach past the LLM read cap');
    assert.ok(v.triggers.some((t) => t.rule === 'aws-access-key-id'));
    assert.strictEqual(v.quarantine, 'size', 'oversize is quarantine, which is separate from the secret block');
    assert.strictEqual(v.scanExemptFromReadCap, true);
    assert.ok(v.scannedBytes > LLM_READ_CAP_BYTES, 'the gate must have actually read past the cap');
  });

  test('a token straddling a streaming chunk boundary is still caught', async () => {
    const dir = path.join(root, 'straddle');
    // The scanner reads in 256KB chunks with an overlap. Place the key so it
    // begins a few bytes before the first boundary and ends after it.
    const boundary = 256 * 1024;
    const prefix = 'y'.repeat(boundary - 8);
    await write(dir, 'blob.txt', `${prefix}${FAKE_AWS_KEY_ID} trailing\n`);
    const v = await triageFile({ rootPath: dir, rel: 'blob.txt' });
    assert.strictEqual(v.flagged, true,
      'a token split across the chunk boundary must be caught by the overlap window — otherwise the scan has a hole at every 256KB mark');
  });

  test('a BINARY file is scanned too (quarantined, not skipped)', async () => {
    const dir = path.join(root, 'binary');
    const abs = path.join(dir, 'dump.bin');
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(abs, Buffer.concat([
      Buffer.from([0x00, 0x01, 0x02, 0x00]),
      Buffer.from(FAKE_PRIVATE_KEY, 'utf8'),
    ]));
    const v = await triageFile({ rootPath: dir, rel: 'dump.bin' });
    assert.strictEqual(v.binary, true);
    assert.strictEqual(v.quarantine, 'binary');
    assert.strictEqual(v.flagged, true, 'binary-ness must not be a reason to stop looking for key material');
    assert.ok(v.triggers.some((t) => t.rule === 'private-key-header'));
  });

  test('entropy distinguishes a generated credential from a typed placeholder', async () => {
    const dir = path.join(root, 'entropy');
    await write(dir, 'weak.conf', 'password = changeme_changeme_changeme\n');
    await write(dir, 'strong.conf', 'api_key = "8fJ2kQ9zXv4mN7pR1sT6uW3yB5cD0eG"\n');
    assert.strictEqual((await triageFile({ rootPath: dir, rel: 'weak.conf' })).flagged, false,
      'a repetitive typed placeholder is not a credential leak');
    assert.strictEqual((await triageFile({ rootPath: dir, rel: 'strong.conf' })).flagged, true);
    assert.ok(shannonEntropy('8fJ2kQ9zXv4mN7pR1sT6uW3yB5cD0eG') > shannonEntropy('changeme_changeme_changeme'));
  });
});

describe('NO SECRET BYTES leave the gate — not the match, not a prefix, not a mask', () => {
  test('the verdict carries the rule and the location and nothing else', async () => {
    const dir = path.join(root, 'nobytes');
    await write(dir, 'creds.txt', `line one\nline two\nAWS_ACCESS_KEY_ID=${FAKE_AWS_KEY_ID}\naws_secret_access_key=${FAKE_AWS_SECRET}\n`);
    const v = await triageFile({ rootPath: dir, rel: 'creds.txt' });

    assert.strictEqual(v.flagged, true);
    const check = assertNoSecretBytes(v, [FAKE_AWS_KEY_ID, FAKE_AWS_SECRET]);
    assert.ok(check.clean, `the verdict leaked secret material: ${check.hits.join(', ')}`);

    // It must still be USEFUL: the tile has to say what fired and where.
    assert.match(v.maskedTriggerText, /AWS access key ID/);
    assert.match(v.maskedTriggerText, /line 3/);
  });
});

describe('per-class remediation — the tracked case is not the untracked case', () => {
  test('a TRACKED secret gets `git rm --cached`, and a bare .gitignore is explicitly refused', () => {
    const r = buildRemediation({ path: 'config/creds.txt', trackingClass: 'tracked-clean' });
    assert.strictEqual(r.bareGitignoreOffered, false,
      'a bare add-to-.gitignore for already-tracked content is a placebo and must never be offered');
    assert.ok(r.bareGitignoreRefusedBecause && /already-tracked/i.test(r.bareGitignoreRefusedBecause),
      'the refusal must state WHY, or the user will just do it manually');

    const op = r.ops.find((o) => o.kind === 'untrack');
    assert.ok(op, 'the tracked class must offer an untrack op');
    assert.strictEqual(op.approvable, true);
    assert.match(op.command, /^git rm --cached/);
    assert.strictEqual(op.gitignoreLine, 'config/creds.txt', 'the .gitignore line comes WITH the untrack, not instead of it');
    assert.deepStrictEqual(op.declaresClassTransition, { from: 'tracked', to: 'untracked' },
      'the consent-scope invariant requires the tile to declare the index-class change it makes');
    assert.ok(op.tileMustState.some((s) => /INDEX-CLASS/.test(s)));
    assert.ok(op.tileMustState.some((s) => /HISTORY REWRITE IS OUT OF SCOPE/.test(s)),
      'the tile must state that untracking does not remove the secret from history');
    assert.ok(r.relocation && r.configOverride, 'relocation guidance and the next-run override are offered in both classes');
    assert.match(r.configOverride.effect, /NEXT run/);
  });

  test('an UNTRACKED secret gets add-to-.gitignore, which actually works there', () => {
    const r = buildRemediation({ path: '.env', trackingClass: 'untracked' });
    assert.strictEqual(r.bareGitignoreOffered, true);
    const op = r.ops.find((o) => o.kind === 'add-to-gitignore');
    assert.ok(op && op.approvable);
    assert.strictEqual(op.gitignoreLine, '.env');
    assert.ok(!r.ops.some((o) => o.kind === 'untrack'), 'there is nothing to untrack — git has never held it');
    assert.ok(r.relocation && r.configOverride);
  });
});

describe('end-to-end: no secret byte reaches ANY assembled LLM context', () => {
  let repo;
  let envelope;
  let agent;

  before(async () => {
    repo = path.join(root, 'e2e-repo');
    await initRepo(repo);
    await write(repo, 'NORTH-STAR.md', '# North Star\n\nShip the importer.\n');
    await write(repo, 'src/importer.mjs', 'export const importThings = () => 1;\n');
    await write(repo, 'notes/old-plan.md', 'an old plan nobody follows\n');
    // A TRACKED secret: it is in the baseline commit.
    await write(repo, 'config/creds.txt', `aws_secret_access_key=${FAKE_AWS_SECRET}\n`);
    await commitAll(repo, 'baseline');
    // An UNTRACKED secret, and a big log with the key past the read cap.
    await write(repo, '.env', `AWS_ACCESS_KEY_ID=${FAKE_AWS_KEY_ID}\n`);
    await write(repo, 'id_rsa', '');
    await write(repo, 'app.log', `${'z'.repeat(LLM_READ_CAP_BYTES + 50 * 1024)}\nkey=${FAKE_AWS_KEY_ID}\n`);

    agent = recordingAgent(cooperativeResponder({
      suspects: [{ filepath: 'notes/old-plan.md', reason: 'superseded' }],
      removePaths: ['notes/old-plan.md'],
    }));
    envelope = await runPipeline({ rootPath: repo, agent });
  });

  test('the run completes and the gate reports what it withheld', () => {
    assert.notStrictEqual(envelope.status, 'failed', JSON.stringify(envelope.errors, null, 2));
    assert.ok(envelope.secretGate, 'the envelope must carry a secret-gate record');
    assert.strictEqual(envelope.secretGate.ran, true);
    for (const expected of ['.env', 'id_rsa', 'config/creds.txt', 'app.log']) {
      assert.ok(envelope.secretGate.blocked.includes(expected),
        `'${expected}' should have been blocked; blocked = ${JSON.stringify(envelope.secretGate.blocked)}`);
    }
  });

  test('EVERY prompt the run assembled is free of secret bytes', () => {
    assert.ok(agent.calls.length > 0, 'the LLM stages must actually have run, or this proves nothing');
    const check = assertNoSecretBytes(agent.allPromptText(), [FAKE_AWS_KEY_ID, FAKE_AWS_SECRET]);
    assert.ok(check.clean,
      `secret material reached an LLM prompt: ${check.hits.join(', ')} — the gate is not doing its job`);
  });

  test('the archived envelope itself carries no secret bytes', () => {
    const check = assertNoSecretBytes(envelope, [FAKE_AWS_KEY_ID, FAKE_AWS_SECRET]);
    assert.ok(check.clean, `the envelope leaked: ${check.hits.join(', ')}`);
  });

  test('blocked findings have NO approval control, bulk or individual', () => {
    const blocked = envelope.findings.filter((f) => f.kind === 'secret-blocked');
    assert.ok(blocked.length >= 3, `expected the blocked tiles, got ${blocked.length}`);
    for (const f of blocked) {
      assert.strictEqual(f.approvable, false, `${f.path} must have no approval control`);
      assert.strictEqual(f.bulkApprovable, false);
      assert.ok(!['remove', 'trash', 'save', 'move', 'reorg'].includes(f.action),
        `${f.path} carries an actionable action '${f.action}' — a secret-blocked tile must not be approvable`);
      assert.ok(f.maskedTriggerText, `${f.path} must say what fired`);
      assert.ok(f.remediation && f.remediation.ops.length > 0, `${f.path} must offer alternatives`);
    }
  });

  test('the TRACKED secret is offered `git rm --cached`; the UNTRACKED one add-to-.gitignore', () => {
    const tracked = envelope.findings.find((f) => f.kind === 'secret-blocked' && f.path === 'config/creds.txt');
    const untracked = envelope.findings.find((f) => f.kind === 'secret-blocked' && f.path === '.env');
    assert.ok(tracked, 'the tracked secret must be flagged');
    assert.ok(untracked, 'the untracked secret must be flagged');
    assert.strictEqual(tracked.trackingClass, 'tracked-clean');
    assert.ok(tracked.remediation.ops.some((o) => o.kind === 'untrack'));
    assert.strictEqual(tracked.remediation.bareGitignoreOffered, false);
    assert.strictEqual(untracked.trackingClass, 'untracked');
    assert.ok(untracked.remediation.ops.some((o) => o.kind === 'add-to-gitignore'));
  });

  test('none of the blocked paths is offered as a SAVE candidate', () => {
    const saves = envelope.findings.filter((f) => f.action === 'save').map((f) => f.path);
    for (const b of envelope.secretGate.blocked) {
      assert.ok(!saves.includes(b), `'${b}' is secret-flagged and must not appear in the SAVE class`);
    }
  });
});

describe('the .tidy-idy.toml [secrets] override is deliberate and next-run only', () => {
  test('an allow-listed path is still triaged, but not blocked', async () => {
    const dir = path.join(root, 'override');
    await write(dir, 'fixtures/fake-key.txt', `AWS_ACCESS_KEY_ID=${FAKE_AWS_KEY_ID}\n`);
    const withoutOverride = await triageAll({ rootPath: dir, paths: ['fixtures/fake-key.txt'] });
    assert.strictEqual(withoutOverride.get('fixtures/fake-key.txt').blockedFromSave, true);

    const withOverride = await triageAll({ rootPath: dir, paths: ['fixtures/fake-key.txt'], allow: ['fixtures/fake-key.txt'] });
    const v = withOverride.get('fixtures/fake-key.txt');
    assert.strictEqual(v.flagged, true, 'the override does not un-flag anything — the trigger is still recorded');
    assert.strictEqual(v.overridden, true);
    assert.strictEqual(v.blockedFromSave, false);
    assert.strictEqual(v.blockedFromLlm, false);
  });
});
