// A hermetic stand-in for the trio's foreman/bin/run-live.mjs, used by tests/test_foreman_code_job_2026_10_10.py
// through code_jobs.FOREMAN_RUN_LIVE. It writes what the real run leaves behind - the project's edited file, the
// status log with its "model routing:" line, and .foreman/run-record.json - as FAKE_FOREMAN_MODE chooses:
//   done (default) | halt | no-routing | stray (also writes FAKE_FOREMAN_STRAY, outside the project) | sleep
// FAKE_FOREMAN_LOG (a file) records argv and whether foreman.config.json named Anchor's documents.
import fs from 'node:fs';
import path from 'node:path';

const project = path.resolve(process.argv[2]);
const mode = process.env.FAKE_FOREMAN_MODE || 'done';
const write = (rel, text) => {
  fs.mkdirSync(path.dirname(path.join(project, rel)), { recursive: true });
  fs.writeFileSync(path.join(project, rel), text, 'utf8');
};
if (process.env.FAKE_FOREMAN_LOG) {
  const cfg = JSON.parse(fs.readFileSync(path.join(project, 'foreman.config.json'), 'utf8'));
  const plan = fs.readFileSync(path.join(project, cfg.docs.plan), 'utf8');
  fs.appendFileSync(process.env.FAKE_FOREMAN_LOG, JSON.stringify({ argv: process.argv.slice(2), docs: cfg.docs, plan,
    profile: process.env.FOREMAN_PROFILE }) + '\n');
}
if (mode === 'sleep') {
  write('.foreman/started', String(process.pid));
  setTimeout(() => {}, 600000);
} else {
  const routing = mode === 'no-routing' ? '' : 'model routing: execute=claude:fake · review=chatgpt-cli:fake · fix=claude:fake\n';
  write('_foreman-status.log', `[00:00:00] === FOREMAN LIVE RUN ===\n[00:00:01] ${routing}`);
  write('a.txt', 'two\n');
  if (mode === 'stray') fs.writeFileSync(process.env.FAKE_FOREMAN_STRAY, 'written outside the worktree\n', 'utf8');
  const status = mode === 'halt' ? 'HALT' : 'DONE';
  write('.foreman/run-record.json', JSON.stringify({ schema: 'foreman-run-record/v1', status,
    halt_reason: status === 'HALT' ? 'the gate stayed red [taxonomy:no-progress]' : null,
    waves: [{ wave: 1, status: status === 'HALT' ? 'HALTED' : 'GREEN' }] }));
}
