// The text a code-job reviewer is given (steward_review.mjs); its own module so it is testable without a review.
import { execFileSync } from 'node:child_process';

// The reviewer reads text only: a binary file appears in a diff as one "Binary files differ" line, so a reviewer could
// pass content it never saw. Refuse a binary row, a NUL byte or invalid UTF-8 rather than send a lossy diff
// (rescued from WIP 283fc40, 2026-10-11).
export function reviewDiff(repo, from, head) {
  const bytes = (...a) => execFileSync('git', ['-C', repo, ...a], { maxBuffer: 64 * 1024 * 1024 });
  const plain = ['--no-ext-diff', '--no-textconv', '--find-renames', from, head];
  if (/(^|\0)-\t-\t/.test(bytes('diff', '--numstat', '-z', ...plain).toString('latin1'))) {
    throw new Error('the change holds a binary file - the reviewer reads text only; take the binary file out of the job');
  }
  const raw = bytes('diff', '--no-color', ...plain);
  if (raw.includes(0)) throw new Error('the diff holds a NUL byte - the reviewer reads text only');
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(raw).trim();
  } catch {
    throw new Error('the diff is not valid UTF-8 - the reviewer would not see its exact bytes');
  }
}
