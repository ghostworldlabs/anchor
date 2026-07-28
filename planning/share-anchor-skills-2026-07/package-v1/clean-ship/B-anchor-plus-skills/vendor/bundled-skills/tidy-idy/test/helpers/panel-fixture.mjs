// test/helpers/panel-fixture.mjs — shared plumbing for the Wave-6 panel suites.
//
// NOT a test file: it exports helpers and defines no tests.
//
// One envelope builder used by every panel suite, so "the panel renders the
// envelope" is asserted against ONE fixture whose shape matches what the real
// stages emit — a bespoke per-test envelope would let a renderer bug hide behind
// a fixture that happened to be shaped around it.

import http from 'node:http';

import { makeRunEnvelope, makeStageResult, failedStage, STATUS } from '../../engine/envelope.mjs';
import { projectIdentity } from '../../engine/launch/identity.mjs';
import { reportDirFor } from '../../engine/report-dir.mjs';
import { TOKEN_HEADER } from '../../engine/launch/panel-server.mjs';

export const RUN_ID = 'run-2026-07-21T00:00:00.000Z-abc123';

/** A REMOVE finding carrying a verbatim attacker case and judge verdict. */
export function removalFinding(overrides = {}) {
  return {
    stage: 'debate',
    kind: 'removal-candidate',
    action: 'remove',
    removalClass: 'git',
    path: 'old/prototype.mjs',
    absolutePath: '/tmp/x/old/prototype.mjs',
    trackingClass: 'tracked-clean',
    porcelain: '1 .M N... 100644 100644 100644 aaa bbb old/prototype.mjs',
    contentHash: 'hash-removal',
    undo: 'git revert of the single tidy commit',
    debateScope: 'alignment',
    evidence: {
      decision: 'REMOVE',
      rationale: 'The North Star names a shipping CLI; this file is a superseded spike with no importers.',
      attacker: { case_for_removal: 'Superseded by src/cli.mjs six months ago; nothing imports it.', strength: 'strong' },
      eligibility: 'tracked and clean at HEAD',
    },
    ...overrides,
  };
}

export function saveFinding(overrides = {}) {
  return {
    stage: 'save',
    kind: 'save-candidate',
    action: 'save',
    path: 'notes/todo.md',
    trackingClass: 'untracked',
    porcelain: '? notes/todo.md',
    porcelainRecord: { kind: 'untracked', xy: '??', staged: false, unstaged: true },
    contentHash: 'hash-save',
    hasStagedChanges: false,
    defaultChecked: false,
    bulkApprovable: true,
    dirtyOverlap: {
      available: true,
      source: 'whole-file (untracked: every line is an addition)',
      diff: '--- /dev/null\n+++ b/notes/todo.md\n@@ -0,0 +1 @@\n+ship the thing\n',
      changedSinceScan: false,
      staged: false,
    },
    why: 'git does not hold this file at all — a SAVE commit is what makes it recoverable',
    ...overrides,
  };
}

export function secretFinding(overrides = {}) {
  return {
    stage: 'triage',
    kind: 'secret-blocked',
    action: 'blocked',
    approvable: false,
    bulkApprovable: false,
    path: '.env',
    trackingClass: 'untracked',
    blockedFrom: ['save', 'llm-context'],
    triggers: [{ rule: 'aws-access-key-id', where: 'content', line: 3 }],
    maskedTriggerText: 'AKIA****************',
    remediation: [
      { kind: 'add-to-gitignore', summary: 'add `.env` to .gitignore (untracked — nothing to untrack)' },
      { kind: 'relocate', summary: 'move the secret outside the project root' },
      { kind: 'next-run-override', summary: 'add an explicit [secrets] allow entry to .tidy-idy.toml' },
    ],
    why: 'a secret-flagged path has no approval path in this tool — the alternatives below are the only routes forward',
    ...overrides,
  };
}

export function quarantineFinding(overrides = {}) {
  return saveFinding({
    path: 'assets/build.bin',
    quarantine: 'binary',
    bulkApprovable: false,
    contentHash: 'hash-binary',
    dirtyOverlap: { available: false, reason: 'quarantined (binary) — the would-be-committed content is binary', changedSinceScan: false, staged: false },
    ...overrides,
  });
}

export function heuristicFinding(overrides = {}) {
  return {
    stage: 'heuristic',
    kind: 'heuristic-candidate',
    action: 'remove',
    label: 'heuristic candidate',
    path: 'tmp/copy of report (1).md',
    contentHash: 'hash-heur',
    defaultChecked: false,
    bulkApprovable: false,
    heuristics: ['age', 'duplicate'],
    evidence: { age: { raw: 'mtime 2024-01-02' }, duplicate: { raw: 'sha256 identical to report.md' } },
    evidenceNote: 'no North-Star document exists for this folder',
    why: 'matched 2 independent heuristics (age + duplicate) — evidence, not a verdict',
    ...overrides,
  };
}

/**
 * Keys that production reorg.stage.mjs always emits on a reorg-proposal finding.
 * W4 fixtures must carry these with non-empty projectable trees — synthetic-only
 * HTML snippets cannot be the sole SC2 proof.
 */
export const REORG_PRODUCTION_FIELD_KEYS = Object.freeze([
  'stage', 'kind', 'action', 'path', 'absolutePath', 'move', 'members', 'memberClasses',
  'before', 'after', 'referenceScan', 'eligible', 'overrideRequired', 'referenceUnsafe',
  'bulkApprovable', 'defaultChecked', 'why',
]);

/**
 * Assertable provenance stamp: fixtures mirror engine/stages/reorg.stage.mjs
 * (renderTree + referenceScan + overrideRequired / bulkApprovable differential).
 */
export const REORG_FIXTURE_PROVENANCE = Object.freeze({
  source: 'engine/stages/reorg.stage.mjs',
  shapes: 'W0/sc2-field-readiness.md production field shapes',
  hollowTreeBan: true,
});

/**
 * Production-shaped zero-hit reorg finding (matches reorg.stage.mjs field shapes).
 * Non-empty before/after trees — required by W3/W4 hollow-tree ban fixtures.
 * bulkApprovable + eligible only when hitCount === 0 (stage rule).
 */
export function reorgFindingZeroHit(overrides = {}) {
  return {
    stage: 'reorg',
    kind: 'reorg-proposal',
    action: 'reorg',
    path: 'sprites',
    absolutePath: '/tmp/x/sprites',
    move: { from: 'sprites', to: 'assets/sprites' },
    members: ['sprites/a.png', 'sprites/b.png'],
    memberClasses: [
      { path: 'sprites/a.png', contentClass: 'tracked', trackingClass: 'tracked-clean', eligible: true },
      { path: 'sprites/b.png', contentClass: 'tracked', trackingClass: 'tracked-clean', eligible: true },
    ],
    // renderTree(dir, files) shape from reorg.stage.mjs — non-empty entries required.
    before: { root: 'sprites', entries: ['sprites/a.png', 'sprites/b.png'] },
    after: { root: 'assets/sprites', entries: ['assets/sprites/a.png', 'assets/sprites/b.png'] },
    referenceScan: {
      hitCount: 0,
      hits: [],
      truncated: false,
      scannedFiles: 12,
      scope: 'whole-tree textual scan of every in-scope file including config/CI/build files',
    },
    eligible: true,
    overrideRequired: false,
    referenceUnsafe: null,
    bulkApprovable: true,
    defaultChecked: false,
    contentHash: 'hash-reorg-zero',
    why: "leaf/asset directory with ZERO references anywhere in the tree — moving it to 'assets/sprites' cannot break a reference",
    undo: 'git revert of the single tidy reorg commit',
    _fixtureProvenance: REORG_FIXTURE_PROVENANCE,
    ...overrides,
  };
}

/**
 * Production-shaped non-zero-hit reorg finding — override-only, not bulk-approvable.
 * Non-empty before/after trees + referenceUnsafe for differential chrome asserts.
 * Mirrors stage: overrideRequired + referenceUnsafe when hitCount ≠ 0.
 */
export function reorgFindingNonZeroHit(overrides = {}) {
  return {
    stage: 'reorg',
    kind: 'reorg-proposal',
    action: 'reorg',
    path: 'icons',
    absolutePath: '/tmp/x/icons',
    move: { from: 'icons', to: 'assets/icons' },
    members: ['icons/logo.svg', 'icons/hero.png'],
    memberClasses: [
      { path: 'icons/logo.svg', contentClass: 'tracked', trackingClass: 'tracked-clean', eligible: true },
      { path: 'icons/hero.png', contentClass: 'tracked', trackingClass: 'tracked-clean', eligible: true },
    ],
    before: { root: 'icons', entries: ['icons/hero.png', 'icons/logo.svg'] },
    after: { root: 'assets/icons', entries: ['assets/icons/hero.png', 'assets/icons/logo.svg'] },
    referenceScan: {
      hitCount: 3,
      hits: [
        { path: 'tsconfig.json', line: 4, needle: 'icons', text: '"paths": { "icons/*": ["icons/*"] }' },
        { path: 'tsconfig.json', line: 5, needle: 'icons/logo', text: '"logo": "icons/logo.svg"' },
        { path: 'src/app.mjs', line: 2, needle: 'icons/', text: "import logo from '../icons/logo.svg'" },
      ],
      truncated: false,
      scannedFiles: 18,
      scope: 'whole-tree textual scan of every in-scope file including config/CI/build files',
    },
    eligible: false,
    overrideRequired: true,
    referenceUnsafe: {
      hitCount: 3,
      reason: 'the whole-tree reference scan found 3 hit(s) — moving this directory would break 3 reference(s) unless you fix them yourself',
      overrideLabel: "Apply anyway — I'll fix the references",
    },
    bulkApprovable: false,
    defaultChecked: false,
    contentHash: 'hash-reorg-hits',
    why: 'leaf/asset directory referenced 3 time(s) — advisory only; applyable via the explicit per-proposal override',
    undo: 'git revert of the single tidy reorg commit',
    _fixtureProvenance: REORG_FIXTURE_PROVENANCE,
    ...overrides,
  };
}

/** Envelope with both zero-hit and non-zero-hit reorg proposals (W3/W4 layout matrix). */
export function envelopeWithReorgProposals(rootPath, { runId = RUN_ID } = {}) {
  return makeRunEnvelope({
    runId,
    rootPath,
    mode: 'north-star',
    ruleset: { version: 'rs-test' },
    reportDir: reportDirFor(rootPath),
    identity: projectIdentity({ rootPath, git: null }),
    git: { toplevel: rootPath, head: 'a'.repeat(40), branch: 'refs/heads/main', rootIsToplevel: true },
    snapshot: { head: 'a'.repeat(40), paths: {} },
    stages: [
      makeStageResult({
        stage: 'reorg',
        status: STATUS.OK,
        coverage: { scanned: 2, skipped: 0, errored: 0 },
        findings: [reorgFindingZeroHit(), reorgFindingNonZeroHit()],
        notes: ['2 reorg proposal(s): 1 zero-hit (approvable), 1 advisory (override-only)'],
      }),
    ],
    startedAt: '2026-07-21T00:00:00.000Z',
    endedAt: '2026-07-21T00:00:05.000Z',
  });
}

/**
 * A run envelope with a CRASHED reorg stage and a COMPLETE removal stage — the
 * canonical Wave-6 honesty case.
 */
export function envelopeWithCrashedReorg(rootPath, { findings = null, extraStages = [], runId = RUN_ID } = {}) {
  const removals = findings || [removalFinding()];
  return makeRunEnvelope({
    runId,
    rootPath,
    mode: 'north-star',
    ruleset: { version: 'rs-test' },
    reportDir: reportDirFor(rootPath),
    identity: projectIdentity({ rootPath, git: null }),
    git: { toplevel: rootPath, head: 'a'.repeat(40), branch: 'refs/heads/main', rootIsToplevel: true },
    snapshot: { head: 'a'.repeat(40), paths: {} },
    stages: [
      makeStageResult({ stage: 'debate', status: STATUS.OK, coverage: { scanned: 3, skipped: 0, errored: 0 }, findings: removals }),
      failedStage('reorg', new Error('reference scan exploded on a symlink loop')),
      ...extraStages,
    ],
    startedAt: '2026-07-21T00:00:00.000Z',
    endedAt: '2026-07-21T00:00:05.000Z',
  });
}

/** A run with every finding class, all stages ok. */
export function envelopeWithEveryClass(rootPath, { runId = RUN_ID } = {}) {
  return makeRunEnvelope({
    runId,
    rootPath,
    mode: 'north-star',
    ruleset: { version: 'rs-test' },
    reportDir: reportDirFor(rootPath),
    identity: projectIdentity({ rootPath, git: null }),
    git: { toplevel: rootPath, head: 'a'.repeat(40), branch: 'refs/heads/main', rootIsToplevel: true },
    snapshot: { head: 'a'.repeat(40), paths: {} },
    stages: [
      makeStageResult({
        stage: 'triage',
        status: STATUS.OK,
        coverage: { scanned: 5, skipped: 0, errored: 0 },
        findings: [secretFinding()],
        data: { blocked: ['.env'], quarantined: [{ path: 'assets/huge.iso', quarantine: 'size', size: 40_000_000 }] },
      }),
      makeStageResult({ stage: 'debate', status: STATUS.OK, coverage: { scanned: 3, skipped: 0, errored: 0 }, findings: [removalFinding()] }),
      makeStageResult({ stage: 'heuristic', status: STATUS.OK, coverage: { scanned: 5, skipped: 0, errored: 0 }, findings: [heuristicFinding()] }),
      makeStageResult({ stage: 'save', status: STATUS.OK, coverage: { scanned: 2, skipped: 0, errored: 0 }, findings: [saveFinding(), quarantineFinding()] }),
    ],
    startedAt: '2026-07-21T00:00:00.000Z',
    endedAt: '2026-07-21T00:00:05.000Z',
  });
}

/** A genuinely clean run — the only shape allowed to celebrate. */
export function cleanEnvelope(rootPath, { runId = RUN_ID } = {}) {
  return makeRunEnvelope({
    runId,
    rootPath,
    mode: 'north-star',
    ruleset: { version: 'rs-test' },
    reportDir: reportDirFor(rootPath),
    identity: projectIdentity({ rootPath, git: null }),
    git: { toplevel: rootPath, head: 'a'.repeat(40), branch: 'refs/heads/main', rootIsToplevel: true },
    snapshot: { head: 'a'.repeat(40), paths: {} },
    stages: [makeStageResult({ stage: 'debate', status: STATUS.OK, coverage: { scanned: 3, skipped: 0, errored: 0 }, findings: [] })],
    startedAt: '2026-07-21T00:00:00.000Z',
    endedAt: '2026-07-21T00:00:05.000Z',
  });
}

export function identityFor(rootPath) {
  return projectIdentity({ rootPath, git: null });
}

/** A tiny HTTP client that speaks this server's conventions. */
export function makeClient(baseUrl) {
  const request = (method, route, { token = null, body = null, headers = {} } = {}) =>
    new Promise((resolve, reject) => {
      const url = new URL(route, baseUrl);
      const payload = body === null ? null : JSON.stringify(body);
      const req = http.request({
        method,
        hostname: url.hostname,
        port: url.port,
        path: url.pathname + url.search,
        headers: {
          ...(token ? { [TOKEN_HEADER]: token } : {}),
          ...(payload ? { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload) } : {}),
          ...headers,
        },
      }, (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          let json = null;
          try { json = JSON.parse(text); } catch { /* html or empty */ }
          resolve({ status: res.statusCode, headers: res.headers, text, json });
        });
      });
      req.on('error', reject);
      if (payload) req.write(payload);
      req.end();
    });

  return {
    get: (route, opts) => request('GET', route, opts),
    post: (route, opts) => request('POST', route, opts),
  };
}

export { TOKEN_HEADER };
