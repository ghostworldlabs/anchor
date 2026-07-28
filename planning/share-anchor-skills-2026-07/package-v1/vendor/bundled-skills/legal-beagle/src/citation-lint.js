// citation-lint.js — Rule 1 as STRUCTURE, not exhortation (W3, 2026-07-11).
//
// Deterministically extracts citation-shaped strings from an output document and
// FAILS any citation that (a) appears in none of the provided source texts and
// (b) carries no [UNVERIFIED — ...] tag on its line. This is the last-line gate
// before findings are delivered: a fabricated citation has to get past a regex,
// not a promise.
//
//   node src/citation-lint.js <findings-file> <source-file...>
//   exit 0 = clean · exit 1 = ungrounded citation(s) (listed) · exit 2 = usage
//
// Citation shapes covered (deliberately broad — over-flagging is the safe error):
//   case reporters:  "597 U.S. 215", "142 S. Ct. 2111", "83 F.4th 1032"
//   case names:      "Smith v. Jones"
//   statutes/regs:   "26 U.S.C. § 2503", "Utah Code § 75B-1-101", "Treas. Reg. § 20.2031-1"
//   rulings:         "PLR 200944002", "Rev. Rul. 2023-2"

import fs from 'node:fs';

const CITATION_RES = [
  /\b\d{1,4}\s+(?:U\.?S\.?|S\.?\s?Ct\.?|F\.(?:2d|3d|4th)|F\.?\s?Supp\.?(?:\s?\d?d?)?|P\.(?:2d|3d)|A\.(?:2d|3d))\s+\d{1,5}\b/g,
  /\b[A-Z][A-Za-z'’.-]+\s+v\.?\s+[A-Z][A-Za-z'’.-]+\b/g,
  /\b\d{1,3}\s+(?:U\.?S\.?C\.?|C\.?F\.?R\.?)\s*§+\s*[\w.()-]+/g,
  /\b(?:[A-Z][a-z]+\s)?Code\s*(?:Ann\.?\s*)?§+\s*[\w.()-]+/g,
  /\bTreas\.?\s?Reg\.?\s*§+\s*[\w.()-]+/g,
  /\b(?:PLR|TAM)\s?\d{7,9}\b/g,
  /\bRev\.?\s?(?:Rul\.?|Proc\.?)\s?\d{2,4}-\d+\b/g,
];

const norm = (s) => String(s).replace(/[’]/g, "'").replace(/\s+/g, ' ').trim().toLowerCase();

/** Extract citation-shaped strings with their line numbers. */
export function extractCitations(text) {
  const out = [];
  const lines = String(text).split(/\r?\n/);
  lines.forEach((line, i) => {
    for (const re of CITATION_RES) {
      for (const m of line.matchAll(re)) {
        out.push({ citation: m[0].trim(), line: i + 1, lineText: line });
      }
    }
  });
  return out;
}

/**
 * Lint: every extracted citation must be grounded in ≥1 source text OR its line
 * must carry an [UNVERIFIED...] tag. Returns { ok, violations[] }.
 */
export function lintCitations(findingsText, sourceTexts = []) {
  const sources = sourceTexts.map(norm);
  const violations = [];
  for (const c of extractCitations(findingsText)) {
    if (/\[unverified\b/i.test(c.lineText)) continue;              // honestly tagged
    const grounded = sources.some((s) => s.includes(norm(c.citation)));
    if (!grounded) violations.push(c);
  }
  return { ok: violations.length === 0, violations };
}

// ---- CLI ----
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const invokedDirectly = (() => {
  try { return path.resolve(fileURLToPath(import.meta.url)) === path.resolve(process.argv[1] || ''); }
  catch { return false; }
})();
if (invokedDirectly) {
  const [findingsFile, ...sourceFiles] = process.argv.slice(2);
  if (!findingsFile || !sourceFiles.length) {
    console.error('usage: node src/citation-lint.js <findings-file> <source-file...>');
    process.exit(2);
  }
  const findings = fs.readFileSync(findingsFile, 'utf8');
  const sources = sourceFiles.map((f) => fs.readFileSync(f, 'utf8'));
  const { ok, violations } = lintCitations(findings, sources);
  if (ok) {
    console.log(`citation-lint: CLEAN — every citation is grounded in the provided sources or tagged [UNVERIFIED].`);
    process.exit(0);
  }
  console.error(`citation-lint: ${violations.length} UNGROUNDED citation(s) — Rule 1 violation:`);
  for (const v of violations) {
    console.error(`  line ${v.line}: "${v.citation}" — not found in any provided source and not tagged [UNVERIFIED]`);
  }
  process.exit(1);
}
