// test/launch-archive.test.mjs — Wave 5: nothing is ever overwritten.
//
// "Previous reports kept as browsable references, never overwritten" is a
// criterion, so it is tested as one: the same folder is archived repeatedly and
// the earlier runs are compared BYTE FOR BYTE afterwards.

import { test, describe, before, after } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs/promises';
import path from 'node:path';

import {
  archiveRun, readRunIndex, runsIndexPathFor, archiveDirFor, runDirFor,
  highestRunNumber, renderReportMarkdown, ARCHIVE_FILES,
} from '../engine/launch/archive.mjs';
import { makeRunEnvelope, makeStageResult, failedStage, STATUS } from '../engine/envelope.mjs';
import { projectIdentity } from '../engine/launch/identity.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';
import { makeTempRoot, rmTempRoot } from './helpers/git-fixture.mjs';
import { archiveLayout } from './helpers/launch-fixture.mjs';

let root;
const identityFor = (r) => projectIdentity({ rootPath: r, git: null });

function envelopeFor(rootPath, { runId = 'run-1', findings = [], stages = null } = {}) {
  return makeRunEnvelope({
    runId,
    rootPath,
    mode: 'heuristic',
    ruleset: { version: 'rs-test' },
    reportDir: reportDirFor(rootPath),
    identity: identityFor(rootPath),
    stages: stages || [makeStageResult({ stage: 'scan', status: STATUS.OK, coverage: { scanned: 1, skipped: 0, errored: 0 }, findings })],
    startedAt: '2026-07-21T00:00:00.000Z',
    endedAt: '2026-07-21T00:00:01.000Z',
  });
}

before(async () => { root = await makeTempRoot('tidy-idy-w5-archive-'); });
after(async () => { await rmTempRoot(root); });

describe('the archive', () => {
  test('run 1 lands at reports/tidy/run-001 with the full artifact set', async () => {
    const env = envelopeFor(root, { runId: 'run-a' });
    const res = await archiveRun({ rootPath: root, reportDir: reportDirFor(root), envelope: env, identity: identityFor(root) });

    assert.strictEqual(res.runNumber, 1);
    assert.strictEqual(res.dir, runDirFor(root, 1));
    const layout = await archiveLayout(res.dir);
    assert.deepStrictEqual(layout, [
      ARCHIVE_FILES.BRIEFING, ARCHIVE_FILES.COST, ARCHIVE_FILES.ENVELOPE, ARCHIVE_FILES.EXCLUDED,
      ARCHIVE_FILES.REPORT, ARCHIVE_FILES.WITHHELD,
    ].sort());

    const stored = JSON.parse(await fs.readFile(path.join(res.dir, ARCHIVE_FILES.ENVELOPE), 'utf8'));
    assert.strictEqual(stored.runId, 'run-a', 'the machine envelope is archived VERBATIM');
  });

  test('the archive self-ignores instead of editing the project .gitignore', async () => {
    const gi = await fs.readFile(path.join(archiveDirFor(root), '.gitignore'), 'utf8');
    assert.match(gi, /^\*$/m);
    await assert.rejects(fs.stat(path.join(root, '.gitignore')), /ENOENT/,
      "the tool must never write the user's own .gitignore (consent scope)");
  });

  test('a second run gets its own directory and the first is byte-identical afterwards', async () => {
    const before1 = await fs.readFile(path.join(runDirFor(root, 1), ARCHIVE_FILES.ENVELOPE));
    const res2 = await archiveRun({ rootPath: root, reportDir: reportDirFor(root), envelope: envelopeFor(root, { runId: 'run-b' }), identity: identityFor(root) });
    assert.strictEqual(res2.runNumber, 2);
    const after1 = await fs.readFile(path.join(runDirFor(root, 1), ARCHIVE_FILES.ENVELOPE));
    assert.ok(before1.equals(after1), 'archiving run 2 must not touch a single byte of run 1');
  });

  test('an existing run directory is stepped OVER, never written into', async () => {
    // Plant run-003 by hand with a marker file, as a crash or a manual copy
    // might leave one.
    await fs.mkdir(runDirFor(root, 3), { recursive: true });
    await fs.writeFile(path.join(runDirFor(root, 3), 'MARKER'), 'do not touch');
    const res = await archiveRun({ rootPath: root, reportDir: reportDirFor(root), envelope: envelopeFor(root, { runId: 'run-c' }), identity: identityFor(root) });
    assert.strictEqual(res.runNumber, 4, 'the allocator must skip an occupied number, not reuse it');
    assert.strictEqual(await fs.readFile(path.join(runDirFor(root, 3), 'MARKER'), 'utf8'), 'do not touch');
    assert.strictEqual(await highestRunNumber(root), 4);
  });
});

describe('the runs-tidy index', () => {
  test('is newest-first, append-only, and tool-owned (never a Gandalf file)', async () => {
    const index = await readRunIndex(reportDirFor(root));
    assert.deepStrictEqual(index.map((r) => r.runNumber), [4, 2, 1], 'newest first, nothing dropped');
    assert.ok(runsIndexPathFor(reportDirFor(root)).includes(path.join('.tidy-idy', 'runs-tidy')));
    // Nothing of Gandalf's exists or is touched.
    await assert.rejects(fs.stat(path.join(root, 'gandalf')), /ENOENT/);
  });

  test('each row identifies the project and the run without opening the envelope', async () => {
    const [newest] = await readRunIndex(reportDirFor(root));
    assert.strictEqual(newest.project.path, path.resolve(root));
    assert.strictEqual(newest.project.name, path.basename(root));
    assert.strictEqual(newest.status, 'ok');
    assert.ok(newest.runDir.endsWith('run-004'));
  });

  test('a corrupt index reads as empty rather than throwing — and the next append still lands', async () => {
    const other = await makeTempRoot('tidy-idy-w5-archive2-');
    try {
      const rd = reportDirFor(other);
      await fs.mkdir(path.dirname(runsIndexPathFor(rd)), { recursive: true });
      await fs.writeFile(runsIndexPathFor(rd), '{ not json');
      assert.deepStrictEqual(await readRunIndex(rd), []);
      const res = await archiveRun({ rootPath: other, reportDir: rd, envelope: envelopeFor(other), identity: identityFor(other) });
      assert.strictEqual(res.runNumber, 1);
      assert.strictEqual((await readRunIndex(rd)).length, 1);
    } finally {
      await rmTempRoot(other);
    }
  });
});

describe('the human report is envelope-driven', () => {
  test('a failed stage renders as NOT CLEAN with the blocker named', () => {
    const env = envelopeFor(root, {
      runId: 'run-x',
      stages: [failedStage('debate', new Error('the adversarial review did NOT run'))],
    });
    const md = renderReportMarkdown({ envelope: env, identity: identityFor(root), runNumber: 9 });
    assert.match(md, /## Not clean/);
    assert.match(md, /debate=failed/);
    assert.doesNotMatch(md, /## Clean/);
    assert.match(md, /the adversarial review did NOT run/);
  });

  test('a cost-gated run renders the banner and both rungs', () => {
    const md = renderReportMarkdown({
      envelope: envelopeFor(root),
      identity: identityFor(root),
      runNumber: 1,
      costGate: {
        gated: true,
        banner: { message: 'too big' },
        degradation: { steps: [{ rung: 1, step: 'generic-exclusions', why: 'w', before: { files: 10 }, after: { files: 2 } }] },
      },
    });
    assert.match(md, /Cost-gated — full run needs confirmation/);
    assert.match(md, /rung 1 — generic-exclusions/);
    assert.match(md, /never blocked awaiting input/);
  });

  test('nothing in the report claims anything was applied', () => {
    const md = renderReportMarkdown({ envelope: envelopeFor(root), identity: identityFor(root), runNumber: 1 });
    assert.match(md, /Nothing in this report has been applied/);
  });
});
