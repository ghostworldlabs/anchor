// citation-lint.test.js — Rule 1 as structure (W3, 2026-07-11): a citation-shaped
// string in the output must be grounded in a provided source or tagged [UNVERIFIED].
import test from 'node:test';
import assert from 'node:assert';
import { extractCitations, lintCitations } from '../src/citation-lint.js';

const SOURCE = [
  'Utah Code § 75B-1-101 (recodified 2025). The trust instrument provides...',
  'Powell v. Commissioner, 148 T.C. 392; see also 26 U.S.C. § 2036(a).',
].join('\n');

test('extractCitations finds reporters, case names, statutes, and rulings', () => {
  const text = [
    'Under 26 U.S.C. § 2036(a) and Smith v. Jones, the retained-control issue...',
    'See PLR 200944002 and Rev. Rul. 2023-2; also 142 S. Ct. 2111.',
  ].join('\n');
  const found = extractCitations(text).map((c) => c.citation);
  assert.ok(found.some((c) => /2036/.test(c)), 'statute found');
  assert.ok(found.some((c) => /Smith v\.? Jones/.test(c)), 'case name found');
  assert.ok(found.some((c) => /PLR 200944002/.test(c)), 'PLR found');
  assert.ok(found.some((c) => /Rev\.? ?Rul\.? ?2023-2/.test(c)), 'Rev. Rul. found');
  assert.ok(found.some((c) => /142 S\.? ?Ct\.? 2111/.test(c)), 'reporter found');
});

test('grounded citations pass; a fabricated citation FAILS; [UNVERIFIED] tag passes honestly', () => {
  // grounded in SOURCE -> clean
  const good = 'The instrument cites Utah Code § 75B-1-101 and 26 U.S.C. § 2036(a).';
  assert.equal(lintCitations(good, [SOURCE]).ok, true);

  // fabricated (not in any source, untagged) -> violation. This is the sanctioned-
  // lawyer failure mode the rule exists for.
  const bad = 'As held in Varga v. Estate, 999 F.4th 1234, the transfer is excluded.';
  const r = lintCitations(bad, [SOURCE]);
  assert.equal(r.ok, false);
  assert.ok(r.violations.length >= 1);

  // the same fabricated cite, honestly tagged on its line -> passes the lint
  const tagged = 'As possibly held in Varga v. Estate, 999 F.4th 1234 [UNVERIFIED — do not rely on this citation].';
  assert.equal(lintCitations(tagged, [SOURCE]).ok, true, 'the honest tag is the sanctioned escape hatch');
});

test('no sources provided => every untagged citation is a violation (fail closed)', () => {
  const r = lintCitations('See Powell v. Commissioner, 148 T.C. 392.', []);
  assert.equal(r.ok, false, 'cannot ground against nothing — fail closed');
});
