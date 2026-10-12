// The text a code-job reviewer is given (steward_review.mjs); its own module so it is testable without a review.
import { execFileSync } from 'node:child_process';

// The reviewer reads text only: a binary file appears in a diff as one "Binary files differ" line, so a reviewer could
// pass content it never saw. The text files go to it as their exact diff (a NUL byte or invalid UTF-8 there is refused
// rather than sent lossy - rescued from WIP 283fc40, 2026-10-11). A binary file - a PDF reading copy, an image - is
// LISTED by name, size and hash, said plainly to be unread, and kept out of the text diff: refusing it outright left
// every job with a PDF unable to land (Book 1 conflict spine v2, 2026-10-12).
export function reviewDiff(repo, from, head) {
  const bytes = (...a) => execFileSync('git', ['-C', repo, ...a], { maxBuffer: 64 * 1024 * 1024 });
  const plain = ['--no-ext-diff', '--no-textconv', '--find-renames', from, head];
  const binaries = binaryPaths(bytes('diff', '--numstat', '-z', ...plain).toString('utf8'));
  const exclude = binaries.flatMap(b => [b.from, b.to]).filter(Boolean).map(p => `:(exclude,literal)${p}`);
  const raw = bytes('diff', '--no-color', ...plain, '--', '.', ...exclude);
  if (raw.includes(0)) throw new Error('the diff holds a NUL byte - the reviewer reads text only');
  let text;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(raw).trim();
  } catch {
    throw new Error('the diff is not valid UTF-8 - the reviewer would not see its exact bytes');
  }
  if (!binaries.length) return text;
  const size = (rev, p) => { try { return Number(bytes('cat-file', '-s', `${rev}:${p}`).toString().trim()); } catch { return null; } };
  const hash = (rev, p) => { try { return bytes('rev-parse', `${rev}:${p}`).toString().trim().slice(0, 12); } catch { return null; } };
  const rows = binaries.map(b => {
    const was = b.from ? size(from, b.from) : null, now = b.to ? size(head, b.to) : null;
    const name = b.from && b.from !== b.to ? `${b.from} -> ${b.to}` : b.to || b.from;
    const what = now === null ? `deleted (was ${was} bytes)` : was === null ? `added, ${now} bytes, blob ${hash(head, b.to)}`
      : `changed, ${was} -> ${now} bytes, blob ${hash(head, b.to)}`;
    return `- ${name}: ${what}`;
  });
  return [text, '', 'BINARY FILES (not shown above, and NOT read by you - judge only whether the brief asks for each one,',
          'for example a PDF reading copy of a document in this change):', ...rows].join('\n').trim();
}

// `git diff --numstat -z`: "A\tD\tpath\0", or for a rename "A\tD\t\0from\0to\0"; a binary file counts as "-\t-".
function binaryPaths(numstat) {
  const parts = numstat.split('\0'), out = [];
  for (let i = 0; i < parts.length; i++) {
    const m = /^(-|\d+)\t(-|\d+)\t(.*)$/s.exec(parts[i]);
    if (!m) continue;
    let from = m[3], to = m[3];
    if (m[3] === '') { from = parts[++i]; to = parts[++i]; }
    if (m[1] === '-' && m[2] === '-') out.push({ from, to });
  }
  return out;
}
