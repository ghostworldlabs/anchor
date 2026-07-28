// wave-engine.mjs — Foreman Phase 1: the ONE-WAVE engine.
//
// Scope (Phase 1 only, per Foreman-Implementation-Plan-FINAL.md §11 line 102):
//   Take a SINGLE wave end-to-end:
//     EXECUTE -> orchestrator-run GATE -> REVIEWER_COUNT sequential reviewers ->
//     schema JUDGE -> bounded linear FIX -> re-gate/re-review until convergence.
//   On GREEN-and-converged: write the §8 checkpoint atomically and emit the §10
//   dashboard line. On any §6 halt: write the checkpoint with the exact
//   recommended next action and return a HALT result.
//
// Phase 3b ADDS (budget + intra-wave resume, no git): an optional `budget`
// enforcer (a HARD pre-flight gate — before each fix iteration it refuses to
// start work it cannot afford, writing a clean resumable budget-stop checkpoint
// instead) and an optional `resumeFrom` that re-enters a wave stopped mid-fix-loop
// by SEEDING the iteration counter. CRITICAL: resume always re-runs the GATE first
// (gate → review → judge), so a resumed wave re-proves real passing tests before
// any GO — resume is NEVER a backdoor to GREEN.
//
// Phase 3c ADDS (git hygiene, opt-in): when an optional `git` context is passed,
// finishGo COMMITS the wave on a dedicated branch AFTER a genuine GO (commit
// first, then the checkpoint records last_commit — §8 order), and a §6.3
// non-convergence HALT stashes the failed attempt and records the ref. All git
// ops live in bin/git-hygiene.mjs and are confined to the target repo. git===null
// (the default) keeps this engine git-free and every prior contract unchanged.
//
// Architecture — the driver seam:
//   The DETERMINISTIC orchestration (gate, guards, loop, judge, finding
//   identity, checkpoint, dashboard) lives here and is fully testable with a
//   single command's real output. The three MODEL-DRIVEN steps are injected as a
//   `driver` object: { execute, review, fix }. In production the driver is backed
//   by Workflow `agent()` calls (bin/wave-workflow.js). For deterministic
//   validation it is backed by a scripted driver that performs real file edits
//   (bin/drivers/scripted-driver.mjs). Either way, GROUND TRUTH is the
//   orchestrator-run gate — never a sub-agent's self-attested word (§5).

import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';

import { HaltError, newCheckpoint, writeCheckpointAtomic, renderDashboard } from './foreman-lib.mjs';

// ---------------------------------------------------------------------------
// File-set helpers (no git: C:\dev is not a repo, so we hash-diff instead of
// `git diff`). Used for "what did this wave change" + inventory snapshots.
// ---------------------------------------------------------------------------

const IGNORE_DIRS = new Set([
  'node_modules', '.git', 'docs', '.foreman', '.anchor',
  // Python build/test caches: created by the pytest gate run itself, never part
  // of the wave's deliverable, so they must not pollute the changed-file diff or
  // the test inventory (a stray `.pytest_cache/...` file would otherwise look
  // like an unreached "source" change and falsely trip the vacuous-GREEN guard).
  '__pycache__', '.pytest_cache',
  // Build output directories (e.g. from Wave 9 of Anchor shareable build)
  'bundle', 'bundle_staging',
]);

/**
 * Runtime noise that is never a wave deliverable (0078/0079 sleep).
 * Excluded from hash-diff and from proven-ledger `changed`.
 * @param {string} rel  project-relative path (posix or win)
 */
export function isRuntimeNoisePath(rel) {
  const r = String(rel || '').replace(/\\/g, '/').toLowerCase();
  if (!r || r.endsWith(' (deleted)')) {
    const base = r.replace(/\s*\(deleted\)\s*$/, '');
    return isRuntimeNoisePath(base);
  }
  const base = r.split('/').pop() || r;
  if (base === 'foreman-checkpoint.json') return true;
  if (base.startsWith('_foreman-status') || base.startsWith('_crucible-status')) return true;
  if (base === 'crucible-run.log' || base === 'heartbeat.json') return true;
  // schtask / launch logs
  if (/^_out-/.test(base) || /^_err-/.test(base) || /^_schtask-/.test(base)) return true;
  if (/^_detached-/.test(base) || /^_breakaway-/.test(base) || /^_launch-/.test(base)) return true;
  if (base.endsWith('.log') && (/^_/.test(base) || base.includes('status') || base.includes('watchdog'))) {
    return true;
  }
  // plain *.log at project root often runtime
  if (/^[^/]+\.log$/.test(r) && !r.includes('test')) return true;
  return false;
}

/**
 * Paths eligible as proven-attempt deliverables (must be code-like, not logs/docs-only).
 * @param {string} rel
 */
export function isProvenDeliverablePath(rel) {
  const r = String(rel || '').replace(/\\/g, '/');
  if (!r || r.endsWith(' (deleted)')) return false;
  if (isRuntimeNoisePath(r)) return false;
  if (isTestFile(r)) return false;
  // doc/data alone cannot prove a wave (same as vacuous DOC_DATA_RE spirit)
  if (/\.(md|txt|csv|yml|yaml|toml|ini|cfg|lock)$/i.test(r) && !/\.(mjs|js|cjs|ts|py)$/i.test(r)) {
    // allow .json only under src/ or explicit code-ish dirs — not root logs disguised
    if (/\.json$/i.test(r) && !/(^|\/)(src|lib|bin|scripts)\//i.test(r)) return false;
    if (!/\.json$/i.test(r)) return false;
  }
  return true;
}

/** Recursively list project files, skipping noise + the foreman state dir. */
function listFiles(root, foremanDir) {
  const out = [];
  const foreman = path.resolve(foremanDir);
  (function walk(dir) {
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const abs = path.join(dir, e.name);
      if (path.resolve(abs) === foreman) continue;       // never count gate artifacts/logs
      if (e.isDirectory()) {
        if (IGNORE_DIRS.has(e.name)) continue;
        walk(abs);
      } else if (e.isFile()) {
        if (e.name.endsWith('.tmp')) continue;
        if (e.name === 'foreman-checkpoint.json') continue;
        const rel = path.relative(root, abs).split(path.sep).join('/');
        if (isRuntimeNoisePath(rel)) continue;
        out.push(abs);
      }
    }
  })(path.resolve(root));
  return out;
}

function hashFile(abs) {
  return crypto.createHash('sha256').update(fs.readFileSync(abs)).digest('hex');
}

/** Map of relpath -> sha256 for every project file (the wave-start snapshot). */
function snapshotHashes(root, foremanDir) {
  const snap = {};
  for (const abs of listFiles(root, foremanDir)) {
    snap[path.relative(root, abs).split(path.sep).join('/')] = hashFile(abs);
  }
  return snap;
}

/** relpaths whose content differs from (or did not exist in) the start snapshot. */
function changedSince(root, foremanDir, startSnap) {
  const now = snapshotHashes(root, foremanDir);
  const changed = [];
  for (const rel of Object.keys(now)) {
    if (now[rel] !== startSnap[rel]) changed.push(rel);
  }
  for (const rel of Object.keys(startSnap)) {
    if (!(rel in now)) changed.push(rel + ' (deleted)');
  }
  return changed;
}

// ---------------------------------------------------------------------------
// Test-inventory snapshot (§5 anti-test-weakening). Heuristic but deterministic:
// count test declarations, assertions, and skip/xfail markers across test files.
// A wave that REDUCES tests/asserts or ADDS skips without a plan citation HALTs.
// ---------------------------------------------------------------------------

function isTestFile(rel) {
  const base = rel.toLowerCase();
  return /\.(test|spec)\.(m?js|cjs|ts)$/.test(base) ||
    /(^|\/)tests?\//.test(base) ||
    // Python (Phase 3d): pytest's default discovery treats `test_*.py` and
    // `*_test.py` (in ANY location) as test modules — recognize them so a Python
    // wave's test files are correctly excluded from the "changed source" set and
    // counted by the inventory, exactly as the JS `*.test.mjs` / `tests/` rules.
    /(^|\/)test_[^/]*\.py$/.test(base) ||
    /_test\.py$/.test(base);
}

function testFilesOf(root, foremanDir) {
  return listFiles(root, foremanDir)
    .map((abs) => path.relative(root, abs).split(path.sep).join('/'))
    .filter(isTestFile);
}

function inventory(root, foremanDir) {
  let tests = 0, asserts = 0, skips = 0, files = 0;
  for (const rel of testFilesOf(root, foremanDir)) {
    let txt;
    try { txt = fs.readFileSync(path.join(root, rel), 'utf8'); } catch { continue; }
    files++;
    // Require a test-name string right after the paren so prose like a
    // "node --test  (declared ...)" comment cannot be miscounted as a test().
    tests += (txt.match(/\b(?:test|it)\s*\(\s*['"`]/g) || []).length;
    // Python (Phase 3d): pytest test functions are `def test_<name>(...)`.
    tests += (txt.match(/\bdef\s+test_\w*\s*\(/g) || []).length;
    asserts += (txt.match(/\bassert\b/g) || []).length; // Python `assert` already matches
    // JS-style skip/xfail markers — SCOPED to a known runner prefix so they do
    // NOT also match Python's `pytest.skip(` (counted separately below). The old
    // bare `\.(skip|xfail)` matched BOTH `it.skip` AND `pytest.skip`, double-
    // counting every Python skip (the wave-5 false "2 -> 4" rise; Finding A 2026-06-04).
    skips += (txt.match(/\b(?:it|test|describe|context|suite)\.(?:skip|xfail)\b|\b(?:xit|xtest|xdescribe)\s*\(|\btodo\s*:/gi) || []).length;
    // Python (Phase 3d): pytest skip/xfail markers — decorator (`@pytest.mark.skip`
    // /`skipif`/`xfail`) and imperative (`pytest.skip(`/`xfail(`/`importorskip(`).
    skips += (txt.match(/@pytest\.mark\.(?:skip|skipif|xfail)\b|\bpytest\.(?:skip|xfail|importorskip)\s*\(/g) || []).length;
  }
  return { files, tests, asserts, skips };
}

/**
 * Compare a fresh inventory to the wave-start snapshot. Returns a HALT reason
 * string if the wave weakened the tests without a citation, else null (§5).
 */
function checkTestWeakening(before, after, citation, actuallySkipped = 0) {
  if (citation) return null; // an explicit plan citation authorizes the change
  if (after.tests < before.tests) {
    return `test count dropped ${before.tests} -> ${after.tests} with no plan citation`;
  }
  if (after.asserts < before.asserts) {
    return `assertion count dropped ${before.asserts} -> ${after.asserts} with no plan citation`;
  }
  // A static skip/xfail-marker rise only WEAKENS the suite if a test is ACTUALLY
  // being skipped now (a real test hidden from the gate). A never-firing
  // environment guard (e.g. `pytest.skip("no node")` that doesn't trigger because
  // node IS present) raises the static count but skips nothing — the gate ran
  // every test — so it is NOT weakening. Gate the HALT on the gate's own
  // actually-skipped count (Finding A 2026-06-04); a real `@pytest.mark.skip` on a
  // failing test still skips it (actuallySkipped > 0) and still HALTs.
  if (after.skips > before.skips && actuallySkipped > 0) {
    return `skip/xfail markers rose ${before.skips} -> ${after.skips} and the gate actually skipped ` +
      `${actuallySkipped} test(s) with no plan citation`;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Test-immutability guard (Wave 7 — Front 2). The anti-weakening check above
// only catches a DROP in test/assert count; it would miss a fix agent silently
// REWRITING a test (same count, changed meaning) to make a red gate go green.
//
// The invariant: a wave's tests are EXECUTE's deliverable; the FIX loop may only
// edit non-test code. So we snapshot every test file's content hash AFTER execute
// (the legitimate moment tests are authored), and on each fix iteration HALT if
// any test file was modified, added, or deleted with no plan citation. (A genuine
// plan-authorized test change is carried on `citation`, exactly like weakening.)
// ---------------------------------------------------------------------------

/** relpath -> sha256 for every test file (the post-execute immutability baseline). */
function testHashSnapshot(root, foremanDir) {
  const snap = {};
  for (const rel of testFilesOf(root, foremanDir)) {
    try { snap[rel] = hashFile(path.join(root, rel)); } catch { /* unreadable: treat as absent */ }
  }
  return snap;
}

/**
 * Compare current test-file hashes to the post-execute baseline. Returns a HALT
 * reason string if the FIX loop touched a test file (modified/added/deleted) with
 * no plan citation, else null.
 */
function checkTestImmutability(baseline, root, foremanDir, citation) {
  if (citation) return null; // an explicit plan citation authorizes the test change
  const now = testHashSnapshot(root, foremanDir);
  for (const rel of Object.keys(baseline)) {
    if (!(rel in now)) return `fix agent deleted test file ${rel}`;
    if (now[rel] !== baseline[rel]) return `fix agent modified test file ${rel}`;
  }
  for (const rel of Object.keys(now)) {
    if (!(rel in baseline)) return `fix agent added test file ${rel}`;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Vacuous-GREEN guard (§5). A GREEN gate must actually exercise something this
// wave changed. Without coverage instrumentation tied to an arbitrary discovered
// command, we use a deterministic, command-agnostic proxy: import-reachability —
// is any changed source file reachable (transitively) from a test file? Labeled
// as a proxy in the log; full coverage instrumentation is Phase 3 hardening.
// ---------------------------------------------------------------------------

function isFile(abs) {
  try { return fs.statSync(abs).isFile(); } catch { return false; }
}
function firstFile(cands) {
  for (const c of cands) if (isFile(c)) return c;
  return null;
}

/**
 * Language-aware import extraction (Phase 3d). Returns descriptor objects the
 * resolver understands, dispatched by file extension:
 *   - JS  : relative specifiers (`./x`, `../y`) from import/export-from, dynamic
 *           import(), and require() — UNCHANGED from the JS-only implementation.
 *   - Py  : absolute module paths (`import a.b.c`, `from a.b import x`) and dotted
 *           relative imports (`from . import x`, `from .mod import x`, including
 *           multiline parenthesized name lists).
 */
function extractImports(absFile) {
  let txt;
  try { txt = fs.readFileSync(absFile, 'utf8'); } catch { return []; }
  if (absFile.toLowerCase().endsWith('.py')) return extractPyImports(txt);
  return extractJsImports(txt);
}

function extractJsImports(txt) {
  const out = [];
  const re = /\b(?:import|export)\b[^'"`]*?from\s*['"]([^'"]+)['"]|\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)|\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
  let m;
  while ((m = re.exec(txt))) {
    const s = m[1] || m[2] || m[3];
    if (s && (s.startsWith('./') || s.startsWith('../'))) out.push({ kind: 'js', spec: s });
  }
  return out;
}

function extractPyImports(txt) {
  const out = [];
  // `from <dots><module> import <names>` — names may be a single line or a
  // multiline parenthesized list. `(\.*)` captures the relative-import dots,
  // `([\w.]*)` the (possibly empty) dotted module, and the trailing group the
  // imported-name clause (used to resolve `from . import submod` to a file).
  const fromRe = /^[ \t]*from[ \t]+(\.*)([\w.]*)[ \t]+import[ \t]+(\([\s\S]*?\)|[^\n]*)/gm;
  let m;
  while ((m = fromRe.exec(txt))) {
    const level = (m[1] || '').length;
    const mod = m[2] || '';
    const names = (m[3] || '').replace(/[()]/g, ' ').split(',')
      .map((s) => s.trim().split(/[ \t]+as[ \t]+/)[0].trim())
      .filter((s) => /^\w+$/.test(s));
    if (level > 0) out.push({ kind: 'py-rel', level, module: mod, names });
    else if (mod) out.push({ kind: 'py-abs', module: mod, names });
  }
  // `import a.b.c`, `import a, b.c as d` (NOT the `from ... import` form above:
  // those lines start with `from`, so this anchored `^import` never re-matches them).
  const importRe = /^[ \t]*import[ \t]+([^\n]+)/gm;
  while ((m = importRe.exec(txt))) {
    for (const part of m[1].split(',')) {
      const name = part.trim().split(/[ \t]+as[ \t]+/)[0].trim();
      if (/^[\w.]+$/.test(name)) out.push({ kind: 'py-abs', module: name, names: [] });
    }
  }
  return out;
}

function resolveJsSpec(fromAbs, spec) {
  const base = path.resolve(path.dirname(fromAbs), spec);
  return firstFile([base, base + '.js', base + '.mjs', base + '.cjs',
    path.join(base, 'index.js'), path.join(base, 'index.mjs')]);
}

/** Candidate files for a dotted module `a.b.c` under baseDir: a/b/c.py or a/b/c/__init__.py. */
function pyModuleCandidates(baseDir, parts) {
  const p = path.join(baseDir, ...parts);
  return [p + '.py', path.join(p, '__init__.py')];
}

/** Resolve a Python import descriptor to project file(s) (0+); non-project/stdlib → []. */
function resolveImportTargets(root, fromAbs, imp) {
  if (imp.kind === 'js') {
    const t = resolveJsSpec(fromAbs, imp.spec);
    return t ? [t] : [];
  }
  if (imp.kind === 'py-abs') {
    const out = [];
    if (imp.module) {
      const parts = imp.module.split('.');
      const f = firstFile(pyModuleCandidates(root, parts));
      if (f) out.push(f);
      // `from pkg import submod` — also try each imported name as a submodule file.
      for (const n of imp.names || []) {
        const sf = firstFile(pyModuleCandidates(root, [...parts, n]));
        if (sf) out.push(sf);
      }
    }
    return out;
  }
  if (imp.kind === 'py-rel') {
    // level 1 (`from .x`) = the importing file's OWN package dir; each extra dot
    // climbs one parent package.
    let dir = path.dirname(fromAbs);
    for (let i = 1; i < imp.level; i++) dir = path.dirname(dir);
    const out = [];
    if (imp.module) {
      const parts = imp.module.split('.');
      const f = firstFile(pyModuleCandidates(dir, parts));
      if (f) out.push(f);
      for (const n of imp.names || []) {
        const sf = firstFile(pyModuleCandidates(dir, [...parts, n]));
        if (sf) out.push(sf);
      }
    } else {
      // `from . import x, y` — each name is a submodule (or a name in __init__).
      for (const n of imp.names || []) {
        const f = firstFile(pyModuleCandidates(dir, [n]));
        if (f) out.push(f);
      }
      const init = path.join(dir, '__init__.py');
      if (isFile(init)) out.push(init);
    }
    return out;
  }
  return [];
}

/**
 * Set of project-relative files reachable from any test file via imports
 * (JS relative specifiers AND Python module/relative imports). Used by the
 * vacuous-GREEN coverage proxy (§5 / F2-9).
 */
function reachableFromTests(root, foremanDir) {
  const reach = new Set();
  const queue = testFilesOf(root, foremanDir).map((rel) => path.join(root, rel));
  const seen = new Set(queue.map((a) => path.resolve(a)));
  while (queue.length) {
    const cur = queue.shift();
    for (const imp of extractImports(cur)) {
      for (const tgt of resolveImportTargets(root, cur, imp)) {
        const rp = path.resolve(tgt);
        reach.add(path.relative(root, tgt).split(path.sep).join('/'));
        if (!seen.has(rp)) { seen.add(rp); queue.push(tgt); }
      }
    }
  }
  return reach;
}

/**
 * Returns a HALT reason if a GREEN gate proves nothing about THIS wave's
 * deliverable, else null (§5 vacuous-GREEN guard).
 *
 * F2-9: a wave must demonstrate its OWN deliverable was exercised. The old guard
 * returned null whenever the wave changed no source file — so a NO-OP wave on an
 * already-green suite reached GO and auto-advanced having proved nothing about
 * its deliverable, and the anti-weakening check only caught test *reductions*.
 * The plan does not specify a coverage mechanism, so per the conservative reading
 * we HALT unless a changed source file is reachable by an executed test: without
 * that, the guard cannot confirm the wave's deliverable was covered. A genuine
 * wave that changes AND covers a source file still passes (proved both ways in
 * the suite). A wave whose deliverable is purely test-only is conservatively
 * halted for human confirmation rather than auto-advanced; instrumentation that
 * could prove a specific changed *test* actually ran is Phase-3 hardening.
 */
function checkVacuousGreen(root, foremanDir, changedFiles, extra = {}) {
  const { invBefore = null, invNow = null, gateTap = null, waveTitle = '' } = extra;
  const sources = changedFiles.filter((f) => !f.endsWith(' (deleted)') && !isTestFile(f) && !f.endsWith('.log'));
  // 2026-07-04 (rearchitecture wave-6 false-GO fix): doc/data artifacts cannot
  // PROVE a wave. The gate run itself can refresh a tracked generated artifact
  // (observed live: a planning inventory .json rewritten by the test suite), and
  // such a file's NAME routinely appears in test text — so the exercisedByName
  // rescue below counted a runtime side effect as a covered deliverable and a
  // NO-OP wave converged twice. Only CODE changes can prove a wave; a wave whose
  // diff is doc/data-only conservatively HALTs for human confirmation (same
  // doctrine as the test-only case in the F2-9 note above).
  const DOC_DATA_RE = /\.(md|json|txt|ya?ml|csv|toml|ini|cfg)$/i;
  const code = sources.filter((f) => !DOC_DATA_RE.test(f));
  const reach = reachableFromTests(root, foremanDir);
  let testText = null;
  const exercisedByName = (f) => {
    if (testText === null) {
      testText = testFilesOf(root, foremanDir)
        .map((rel) => { try { return fs.readFileSync(path.join(root, rel), 'utf8'); } catch { return ''; } })
        .join('\n');
    }
    const base = path.basename(f);
    const has = base.length > 3 && testText.includes(base);
    return has;
  };
  const exercised = code.some((f) => reach.has(f) || exercisedByName(f));
  if (exercised) return null;

  // T4 (2026-07-11): HONEST TEST-ONLY PATH. A test-only / acceptance wave's
  // deliverable IS its tests — "changed no source file" is not a defect, it is
  // the plan. The engine already holds the evidence to prove such a wave
  // honestly, so use it instead of dead-stopping every terminal acceptance wave
  // (observed live: wave 10/10 HALTed after 6 GO waves — the most expensive
  // false-positive class):
  //   (a) the wave's code diff is empty but it DID deliver test files,
  //   (b) the static test inventory ROSE from the wave-start snapshot
  //       (net-new tests exist — the deliverable is real), and
  //   (c) the GREEN gate executed at least the full new inventory
  //       (the larger suite actually RAN; a partial gate stays conservative).
  // An explicit `[test-only]` tag in the wave title is the human channel for a
  // wave that only MODIFIES tests (no net rise): the tag relaxes (b) to
  // "did not shrink" — the anti-weakening guard §5 separately polices real
  // reductions, and the gate-execution bar (c) still applies.
  const changedTests = changedFiles.filter((f) => !f.endsWith(' (deleted)') && isTestFile(f));
  if (code.length === 0 && changedTests.length > 0 &&
      invBefore && invNow && gateTap && Number.isInteger(gateTap.tests)) {
    const declaredTestOnly = /\[test[-_ ]?only\]/i.test(waveTitle);
    const rose = invNow.tests > invBefore.tests;
    const heldSteady = invNow.tests >= invBefore.tests;
    const ranFullSuite = gateTap.tests >= invNow.tests;
    if (rose && ranFullSuite) return null;
    if (declaredTestOnly && heldSteady && ranFullSuite) return null;
  }

  if (sources.length === 0) {
    if (changedTests.length > 0) {
      // A test-only wave that FAILED the evidence bar: say exactly which leg failed
      // so the human clears it in one look, not a checkpoint autopsy.
      return `wave changed only test files (${changedTests.join(', ')}) but the test-only ` +
        `evidence bar did not pass: declared tests ${invBefore ? invBefore.tests : '?'} -> ` +
        `${invNow ? invNow.tests : '?'}, green gate executed ${gateTap && Number.isInteger(gateTap.tests) ? gateTap.tests : '?'} ` +
        `— a test-only wave auto-passes when the inventory ROSE and the green gate ran the ` +
        `larger suite (or tag the wave title [test-only] for a modify-only test wave)`;
    }
    // Phase A (2026-07-22): credit a PRIOR same-wave attempt that already left
    // code on disk + a proven ledger entry (resume / clear-halt / re-enter after
    // plan amendment). Journals 0010, 0015, 0043, 0045: hashStart-at-resume makes
    // a second pass look like a no-op while the deliverable is still there and
    // still exercised. NEVER credits without a ledger + live files + exercise.
    const prior = creditPriorWaveAttempt(root, foremanDir, extra.waveN, {
      reach,
      exercisedByName,
    });
    if (prior.ok) return null;

    // F2-9: the wave changed no source file at all (a no-op wave, or one that
    // touched only tests/non-source). An already-green suite proves nothing.
    return `wave reached green without proving its own deliverable was exercised ` +
      `— the wave changed no source file reachable by an executed test, so an ` +
      `already-green suite proves nothing about this wave's deliverable` +
      (prior.note ? ` (${prior.note})` : '');
  }
  if (code.length === 0) {
    return `wave changed only doc/data artifacts (${sources.join(', ')}) — such files ` +
      `can be regenerated by the gate run itself and cannot prove this wave's ` +
      `deliverable; if this wave is genuinely docs-only, a human must confirm`;
  }
  return `GREEN gate did not exercise any changed source file ` +
    `(${code.join(', ')}) — no test reaches it; gate proves nothing about this wave`;
}

// ---------------------------------------------------------------------------
// The orchestrator-run GATE (§5). Runs the DISCOVERED test command verbatim as
// the sole ground truth, captures exit code + stdout/stderr, parses the TAP/spec
// summary counts IN-PROCESS (handles Node's `# pass N` and `ℹ pass N` forms),
// and writes an artifact file the engine owns. Sub-agents never write this file.
// ---------------------------------------------------------------------------

function parseCount(text, word) {
  // Node/TAP path (UNCHANGED): TAP comments (`# pass 2`) and Node's default
  // reporter (`ℹ pass 2`) — a word FOLLOWED by its number.
  const m = text.match(new RegExp(String.raw`^\s*[#ℹ]\s+${word}\b\D*(\d+)`, 'm'));
  if (m) return Number(m[1]);
  // Python/pytest path (Phase 3d): pytest prints a `==== N passed, M failed, …
  // in T s ====` summary (a number PRECEDING its word — the opposite shape, so
  // the two never collide). Only consulted when the output actually looks like
  // pytest, so a Node run with no parseable count still returns null as before.
  if (looksLikePytest(text)) return parsePytestCount(text, word);
  return null;
}

/**
 * Output-shape detection for pytest (Phase 3d). True iff the captured output is
 * a pytest run: a per-test event line (`path::name PASSED`), a `N passed/…`
 * summary token, a `N error(s) in T s` collection-error summary, the `no tests
 * ran` banner, or the `test session starts` header. Each marker is number-then-
 * word or pytest-specific text, none of which Node's TAP/spec output ever emits,
 * so this never misclassifies a JS gate (the JS path stays byte-for-byte intact).
 */
function looksLikePytest(text) {
  return /^\s*\S+::\S+\s+(?:PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b/m.test(text) ||
    /\b\d+\s+(?:passed|failed|xfailed|xpassed|deselected)\b/.test(text) ||
    /\b\d+\s+errors?\s+in\s+[\d.]+s/.test(text) ||
    /\bno tests ran\b/.test(text) ||
    /=+\s*test session starts\s*=+/.test(text);
}

/** The authoritative pytest summary banner line (last `==== … in Ts ====`). */
function pytestSummaryLine(text) {
  const lines = text.split(/\r?\n/);
  for (let i = lines.length - 1; i >= 0; i--) {
    const l = lines[i];
    if (/^=+.*\bin\s+[\d.]+s\b.*=+$/.test(l) || /^=+.*\bno tests ran\b.*=+$/.test(l)) return l;
  }
  return text; // forged/echoed summary with no banner: scan the whole text
}

/**
 * Parse a pytest summary count for `word` (Phase 3d). pytest prints no single
 * "tests N" total, so it is DERIVED as passed+failed+errors (errors are gating
 * failures). `todo` has no pytest analogue → null. `no tests ran` ⇒ all zero.
 */
function parsePytestCount(text, word) {
  const s = pytestSummaryLine(text);
  if (/\bno tests ran\b/.test(s)) {
    return (word === 'tests' || word === 'pass' || word === 'fail') ? 0 : null;
  }
  const grab = (re) => { const mm = s.match(re); return mm ? Number(mm[1]) : 0; };
  const passed = grab(/(\d+)\s+passed/);
  const failed = grab(/(\d+)\s+failed/);
  const errors = grab(/(\d+)\s+errors?\b/);
  const skipped = grab(/(\d+)\s+skipped/);
  switch (word) {
    case 'pass':    return passed;
    case 'fail':    return failed + errors;          // errors are gating failures
    case 'skipped': return skipped;
    case 'tests':   return passed + failed + errors; // pytest emits no total line
    case 'todo':    return null;                      // no pytest analogue
    default:        return null;
  }
}

/**
 * Structural evidence that the gate actually ran tests (R2-3 vacuous-GREEN
 * defense). A real runner emits PER-TEST events: the TAP reporter prints
 * `ok N`/`not ok N` test points; Node's spec reporter prints `✔`/`✖` per-test
 * markers. A forged summary line (e.g. `echo # pass 99`) emits a count COMMENT
 * but no such event, so it fails here and cannot fabricate a GREEN from an
 * echoed line alone. (A gate command crafted to echo a FULL fake stream — counts
 * AND a `✔` — is a deliberately fraudulent gate, outside this guard's scope; §5's
 * ground-truth rule presumes the discovered command is an honest test runner.)
 */
function hasRealTestEvents(text) {
  return /^\s*(?:ok|not ok)\s+\d+\b/m.test(text) || /^\s*[✔✖✓✗]/m.test(text) ||
    // pytest -v per-test events: `path::test_name PASSED|FAILED|ERROR|SKIPPED|
    // XFAIL|XPASS [ NN%]`. The node-id (`::`) PRECEDES the status word, which is
    // what distinguishes a real event from the trailing summary-section lines
    // (`FAILED path::name - msg`) where the status comes FIRST.
    /^\s*\S+::\S+\s+(?:PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b/m.test(text);
}

/**
 * Count genuine per-test PASS / FAIL events in gate output (BRR-5 gate-integrity
 * hardening). TAP test points are `ok N` (pass) and `not ok N` (fail); a trailing
 * `# SKIP` / `# TODO` directive means the point did NOT really pass, so it is not
 * counted as a passing event. Node's spec reporter prints `✔`/`✓` (pass) and
 * `✖`/`✗` (fail) per-test markers. Returning both polarities lets the gate assert
 * that the emitted failing-event count is consistent with the summary's claimed
 * `fail` count — a stream that emits more failures than it admits is self-
 * contradicting and cannot be an honest passing run.
 */
function countTestEvents(text) {
  let pass = 0, fail = 0;
  for (const line of text.split(/\r?\n/)) {
    if (/^\s*not ok\s+\d+\b/.test(line)) { fail++; continue; }
    if (/^\s*ok\s+\d+\b/.test(line)) {
      if (/#\s*(?:skip|todo)\b/i.test(line)) continue; // directive: not a real pass
      pass++;
      continue;
    }
    // pytest -v per-test event: `path::test_name STATUS [ NN%]`. Matching the
    // node-id (`::`) BEFORE the status excludes the summary-section lines
    // (`FAILED path::name`, `ERROR path`) — counting those would double-count a
    // single failure. PASSED is the only real pass; FAILED/ERROR are failures;
    // SKIPPED/XFAIL/XPASS are neither (a skip/xfail is not a real pass, and a
    // default-mode xpass is not a failure — it does not change pytest's exit 0).
    const py = line.match(/^\s*\S+::\S+\s+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b/);
    if (py) {
      if (py[1] === 'PASSED') pass++;
      else if (py[1] === 'FAILED' || py[1] === 'ERROR') fail++;
      continue;
    }
    if (/^\s*[✔✓]/.test(line)) pass++;
    else if (/^\s*[✖✗]/.test(line)) fail++;
  }
  return { pass, fail };
}

export function runGate({ projectDir, testCommand, foremanDir, wave, iteration }) {
  // Gate-integrity hardening (Phase 1 finding M): run in a SANITIZED environment
  // so an inherited test-runner context cannot poison the ground truth. If the
  // orchestrator is itself spawned under `node --test`, the child inherits
  // `NODE_TEST_CONTEXT`, which makes a child `node --test` "skip running files"
  // and exit 0 — a FALSE GREEN. The gate must never depend on the parent's env
  // leaking a skip-tests signal, so we strip it before spawning.
  const env = { ...process.env };
  delete env.NODE_TEST_CONTEXT;
  // 2026-07: the gate timeout is CONFIGURABLE (FOREMAN_GATE_TIMEOUT_MS; default
  // increased to 20m/1200s). The old hardcoded 120s KILLED any suite that takes
  // longer, which read as a spurious RED the fix loop then chased — on a big
  // target that is pure vacuous churn. A killed gate is still RED (never GREEN).
  let gateTimeout = 1200000;
  const _t = Number(process.env.FOREMAN_GATE_TIMEOUT_MS);
  if (Number.isFinite(_t) && _t > 0) gateTimeout = _t;
  const _gateT0 = Date.now(); // SPIKE(foreman-parallel): gate wall-clock
  const res = spawnSync(testCommand, {
    cwd: projectDir,
    shell: true,
    windowsHide: true,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
    timeout: gateTimeout,
    env,
  });
  const _gateMs = Date.now() - _gateT0;
  const stdout = res.stdout || '';
  const stderr = res.stderr || '';
  const merged = stdout + '\n' + stderr;
  const exitCode = res.status; // null if killed by signal
  const tap = {
    tests: parseCount(merged, 'tests'),
    pass: parseCount(merged, 'pass'),
    fail: parseCount(merged, 'fail'),
    skipped: parseCount(merged, 'skipped'),
    todo: parseCount(merged, 'todo'),
  };
  // R2-3 (vacuous-GREEN integrity): `exit 0` ALONE is NOT proof the suite ran.
  // GREEN now requires DEMONSTRATED real passing tests — a parseable, positive
  // test+pass count with zero failures AND structural evidence that real
  // per-test events were emitted (so a forged `echo # pass 99` summary line,
  // which produces no test events, cannot manufacture a pass). Anything else
  // that still exits 0 (no parseable counts, tests===0, a `1..0` empty plan,
  // pass===0 / skip-only) is VACUOUS: it is refused as a §6 HALT (see runWave),
  // NOT silently downgraded to RED (which would bury it in the fix loop) and
  // never accepted as a false GO. A NON-zero exit keeps the existing RED /
  // fix-loop behavior unchanged.
  const countsOk =
    exitCode === 0 &&
    Number.isInteger(tap.tests) && tap.tests > 0 &&
    Number.isInteger(tap.pass) && tap.pass > 0 &&
    tap.fail === 0;
  // BRR-5: a parseable summary count is necessary but NOT sufficient. A hand-
  // forged stream can echo `# pass 1 # fail 0` (exit 0) while emitting a real
  // `not ok 1` failing test point. GREEN therefore additionally requires:
  //   (a) at least one real PASSING per-test event (an `ok N` with no SKIP/TODO
  //       directive, or a spec-reporter `✔`) — so a counts-only echo is refused;
  //   (b) internal consistency — the observed failing-event count must not exceed
  //       the summary's claimed `fail`. An honest runner that printed `not ok`
  //       reports `# fail >= 1` and exits non-zero; a stream that emits more
  //       failures than it admits is self-contradicting and is refused.
  const events = countTestEvents(merged);
  const hasPassingEvent = events.pass > 0;
  const eventsConsistent = events.fail <= (Number.isInteger(tap.fail) ? tap.fail : 0);
  const green = countsOk && hasPassingEvent && eventsConsistent;
  const fmt = (v) => (v === null ? 'none' : v);
  let vacuous_reason = null;
  if (exitCode === 0 && !green) {
    if (countsOk && !eventsConsistent) {
      // BRR-5: emitted failures exceed the claimed fail count — refuse outright.
      vacuous_reason =
        `TAP summary inconsistent with emitted test events ` +
        `(observed ${events.fail} failing test event(s) but the summary claims fail=${fmt(tap.fail)}) ` +
        `— refusing GREEN`;
    } else if (countsOk && !hasPassingEvent) {
      // Counts present but no genuine passing test point ran (echoed/forged line).
      vacuous_reason =
        `gate exited 0 with summary counts but no real per-test events ran ` +
        `(only an echoed/forged summary line) — refusing vacuous GREEN`;
    } else {
      vacuous_reason =
        `gate exited 0 but did not demonstrate real passing tests ` +
        `(tests=${fmt(tap.tests)}, pass=${fmt(tap.pass)}, fail=${fmt(tap.fail)}, ` +
        `skip=${fmt(tap.skipped)}) — refusing vacuous GREEN`;
    }
  }
  // Phase 3d — pytest "nothing ran" is vacuous EVEN on its non-zero exit. pytest
  // exits 5 when no tests are collected / all are deselected ("no tests ran"),
  // and exits 2 on a collection error ("… during collection"); in both cases the
  // gate proved nothing, so it must HALT cleanly here rather than be chased
  // through the fix loop as if it were a fixable RED. A GENUINE pytest failure
  // (real FAILED/ERROR per-test events, exit 1) is NOT vacuous — it keeps the
  // normal RED / fix-loop path so red→green can be driven. (The exit-0 forged-
  // echo and inconsistency cases are already handled above.)
  if (!green && !vacuous_reason && looksLikePytest(merged)) {
    // T3 (2026-07-11): TRUST THE PARSED SUMMARY FIRST. A real `N passed/M failed`
    // banner proves tests RAN even when no per-test EVENTS were emitted — pytest
    // without `-v` prints dots, not events — so a genuine RED must keep the
    // normal fix-loop path, never dead-stop as "nothing ran". (Live misroute:
    // gate parsed `exit 1 · 40 passed/34 failed` under `pytest -q`, yet HALTed
    // "collected/ran no real tests" with a wrong recommendation — Anchor-zombie
    // 2026-06-28. This also covers partial collection errors: `X passed, Y
    // errors` is a gating RED the fixer can drive, not a proved-nothing halt.)
    // The exit-0 GREEN bar above is UNCHANGED — passing still requires real
    // per-test events, which is why pytest gates are normalized to `-v` at
    // contract time (discoverTestCommand).
    const summaryShowsRuns =
      (Number.isInteger(tap.pass) && tap.pass > 0) ||
      (Number.isInteger(tap.fail) && tap.fail > 0);
    const noneRan = !summaryShowsRuns && (
      /\bno tests ran\b/.test(merged) ||
      /\bduring collection\b/i.test(merged) ||
      exitCode === 5 ||
      (events.pass === 0 && events.fail === 0)); // no per-test events at all
    if (noneRan) {
      vacuous_reason =
        `pytest collected/ran no real tests ` +
        `(exit ${fmt(exitCode)}; ${/\bno tests ran\b/.test(merged) ? '"no tests ran"'
          : /\bduring collection\b/i.test(merged) ? 'error during collection'
          : 'no per-test events'}) — refusing vacuous GREEN`;
    }
  }
  const artifact = {
    written_by: 'orchestrator',        // sub-agents cannot write this file (§5)
    wave: wave?.n ?? null,
    iteration,
    command: testCommand,
    cwd: projectDir,
    exit_code: exitCode,
    green,
    gate_ms: _gateMs,                  // SPIKE(foreman-parallel): gate wall-clock
    vacuous_reason,                    // R2-3: non-null ⇒ exit-0-but-not-real-GREEN
    tap,
    stdout,
    stderr,
  };
  fs.mkdirSync(foremanDir, { recursive: true });
  const file = path.join(foremanDir, `wave-${wave?.n ?? 0}-gate.json`);
  fs.writeFileSync(file, JSON.stringify(artifact, null, 2) + '\n');
  artifact.artifact_path = file;
  // SPIKE(foreman-parallel): passive phase-timing sink. The gate is NOT an agent()
  // call, so it has no per-call telemetry record; record its wall-clock here so
  // phase-report.mjs can answer "gate vs review". Append-only; never crash the gate.
  try {
    fs.appendFileSync(path.join(foremanDir, 'phase-timings.jsonl'),
      JSON.stringify({ kind: 'gate', label: `gate:w${wave?.n ?? 0}.${iteration}`,
        phase: 'gate', wave: wave?.n ?? null, iteration, duration_ms: _gateMs,
        output_tokens: 0, exit_code: exitCode, green, ts: Date.now() }) + '\n');
  } catch { /* never crash the gate on logging */ }
  return artifact;
}

// ---------------------------------------------------------------------------
// Finding identity + judge (§5). Findings carry a stable id (`file:line+rule`).
// A BLOCKER/MAJOR requires >=2 independent reviewers to agree. The judge reads
// ONLY the orchestrator gate artifact for the pass/fail of record: a forged
// "GREEN" in a sub-agent's prose can never flip a RED gate to GO.
// ---------------------------------------------------------------------------

function findingId(f) {
  return `${f.file || '?'}:${f.line ?? '?'}+${f.rule || 'unspecified'}`;
}

/** Merge per-reviewer findings into deduped findings with an agreement count. */
export function collectFindings(reviews) {
  const byId = new Map();
  reviews.forEach((rv, idx) => {
    for (const f of rv.findings || []) {
      const id = f.id || findingId(f);
      if (!byId.has(id)) {
        byId.set(id, { ...f, id, status: f.status || 'open', reviewers: new Set(), agreement: 0 });
      }
      byId.get(id).reviewers.add(rv.reviewer ?? idx);
    }
  });
  return [...byId.values()].map((f) => {
    const agreement = f.reviewers.size;
    const { reviewers, ...rest } = f;
    return { ...rest, agreement };
  });
}

/**
 * Judge: GO iff the orchestrator gate is GREEN AND no open BLOCKER/MAJOR that
 * (a) >=2 reviewers agree on and (b) carries a failing repro command+output.
 * A RED gate is never GO regardless of any sub-agent prose (anti-forgery).
 */
export function judge(gate, findings) {
  const blocking = findings.filter((f) =>
    (f.severity === 'BLOCKER' || f.severity === 'MAJOR') &&
    f.status === 'open' && f.agreement >= 2);
  if (!gate.green) {
    return { go: false, reason: `gate RED (exit ${gate.exit_code}, fail ${gate.tap.fail ?? '?'})`, blocking };
  }
  // Gate is GREEN: per §5, a reviewer may only block GREEN with a failing repro.
  const withRepro = blocking.filter((f) => f.repro && f.repro.failing);
  if (withRepro.length > 0) {
    return { go: false, reason: `GREEN gate blocked by ${withRepro.length} verified repro finding(s)`, blocking: withRepro };
  }
  return { go: true, reason: 'gate GREEN and no verified blocking finding', blocking: [] };
}

// SPIKE(foreman-parallel): A/B toggle for CONCURRENT read-only reviewers (default OFF).
// The reviewers are read-only and the finding-merge (collectFindings) keys by stable
// id, so concurrency is order-independent by construction. Flag OFF ⇒ byte-identical
// to the historical sequential path. Used only to MEASURE the latency-tail win.
function reviewConcurrencyOn() { return process.env.FOREMAN_CONCURRENT_REVIEW !== '0'; }

// ---------------------------------------------------------------------------
// The one-wave loop.
// ---------------------------------------------------------------------------

function buildCheckpoint({ planPath, totalWaves, wave, iteration, verdict, findings, status, pendingAction, reviewerCount, intraWaveStep, budgetRemaining, lastCommit, stashRef }) {
  const cp = newCheckpoint({ plan_path: planPath, total_waves: totalWaves, reviewer_count: reviewerCount });
  cp.current_wave = wave.n;
  // A halted/budget-stopped wave records WHERE to re-enter (§8 intra_wave_step).
  // 'gate' means a resume must re-run the gate first (re-prove GREEN); 'done' is a
  // terminal wave. An explicit override wins (budget stops pass 'gate').
  cp.intra_wave_step = intraWaveStep ||
    (status === 'halted' || status === 'budget_stopped' ? 'fix' : 'done');
  cp.iteration = iteration;
  cp.last_verdict = verdict;
  cp.open_findings = findings.map((f) => ({
    id: f.id, severity: f.severity, file: f.file ?? null,
    line: f.line ?? null, rule: f.rule ?? null, status: f.status || 'open',
  }));
  cp.pending_action = pendingAction;
  cp.status = status;
  if (budgetRemaining) cp.budget_remaining = budgetRemaining;
  // Phase 3c (§8): record the wave's commit (set AFTER the commit lands) and any
  // §6.3 stash ref. Left null (newCheckpoint default) when git is inactive.
  if (lastCommit !== undefined) cp.last_commit = lastCommit;
  if (stashRef !== undefined) cp.stash_ref = stashRef;
  return cp;
}

/**
 * Run ONE wave end-to-end.
 *
 * @param {object} o
 * @param {string} o.projectDir       project under build (cwd proxy)
 * @param {string} o.testCommand      the DISCOVERED gate command (ground truth)
 * @param {object} o.wave             selected wave {n, title, line}
 * @param {number} o.totalWaves
 * @param {string} o.planPath
 * @param {object} o.driver           { execute, review, fix } — model-driven seam
 * @param {number} [o.reviewerCount=2]
 * @param {number} [o.fixIterCap=4]   §6.3 MAX_ITERS
 * @param {object} [o.budget]         §4.6 budget enforcer (makeBudget); null = no budget stop
 * @param {object} [o.resumeFrom]     intra-wave resume seed { iteration } (re-enters at the gate)
 * @param {string} [o.foremanDir]     state dir (default <projectDir>/.foreman)
 * @param {string} [o.checkpointPath] default <projectDir>/foreman-checkpoint.json
 * @param {(s:string)=>void} [o.log]
 * @returns {Promise<object>} { status:'GO'|'HALT'|'BUDGET-STOP', ... }
 */
export async function runWave(o) {
  const {
    projectDir, testCommand, wave, totalWaves, planPath, driver,
    reviewerCount = 2, fixIterCap = 4, budget = null, resumeFrom = null,
    git = null, // Phase 3c: optional git-hygiene context (null = no git, unchanged)
  } = o;
  const foremanDir = o.foremanDir || path.join(projectDir, '.foreman');
  const checkpointPath = o.checkpointPath || path.join(projectDir, 'foreman-checkpoint.json');
  const log = o.log || (() => {});
  const steps = []; // dashboard step lines

  // Plan text for execute contract injection (0076 package 1). Best-effort read.
  let planText = '';
  try { planText = fs.readFileSync(planPath, 'utf8'); } catch { /* missing plan is a higher-level HALT */ }
  const ctx = { projectDir, wave, foremanDir, testCommand, log, planPath, planText };

  // §5 anti-test-weakening: snapshot inventory + file hashes BEFORE any change.
  const invBefore = inventory(projectDir, foremanDir);
  const hashStart = snapshotHashes(projectDir, foremanDir);

  // Intra-wave resume (Phase 3b): seed the fix-iteration counter from the
  // checkpoint so a wave stopped mid-fix-loop re-enters with its REMAINING fix
  // budget (it does not get a fresh MAX_ITERS) and does not re-count completed
  // iterations as new work. EXECUTE re-runs (idempotent-from-last-commit per §8 —
  // the scripted/agent execute is a no-op when its change is already on disk), and
  // the GATE below re-runs unconditionally, so resume re-establishes truth on the
  // CURRENT disk state and re-proves green; it never short-circuits to GO.
  const seededIteration =
    resumeFrom && Number.isInteger(resumeFrom.iteration) && resumeFrom.iteration > 0
      ? resumeFrom.iteration : 0;
  if (seededIteration > 0) {
    steps.push(`▸ resume… re-entering wave ${wave.n} at the gate (after ${seededIteration} prior fix iter(s)); re-proving GREEN`);
    log(`resume: re-entering wave ${wave.n} at the gate after ${seededIteration} prior fix iter(s) — must re-prove real passing tests`);
  }

  // EXECUTE (single-threaded; model-driven). May be a no-op if the wave's code
  // is already in place; it must never weaken tests.
  // F-H sleep fix (0072): skip long execute ONLY when resume stamped **review**
  // after a prior GREEN gate in the same wave. Resume at **gate** (clear-halt /
  // vacuous-GREEN fix path) must re-run execute so new deliverables + tests land
  // and the coverage graph can see this wave's sources (else already-green suite
  // vacuous-GREENs).
  const resumeStep = resumeFrom?.intraStep ? String(resumeFrom.intraStep) : '';
  const skipExecute = resumeStep === 'review';
  let exec = { note: 'done', citation: null };
  if (skipExecute) {
    steps.push(`▸ execute… skipped (resume at ${resumeStep}; re-prove GREEN at gate)`);
    log(`execute: skipped — resume at ${resumeStep} (crash-resilience; gate re-proves truth)`);
  } else {
    exec = await driver.execute(ctx);
    steps.push(`▸ execute… ${exec?.note || 'done'}`);
    log(`execute: ${exec?.note || 'done'}`);
  }

  // Wave 7 test-immutability baseline: tests are EXECUTE's deliverable, so snapshot
  // them NOW (post-execute); the fix loop below must not modify/add/delete any of
  // them (checked each iteration). A genuine plan-authorized change rides `citation`.
  // When execute was skipped, baseline still reflects current disk (idempotent).
  const testBaseline = testHashSnapshot(projectDir, foremanDir);

  let iteration = seededIteration;
  let findings = [];
  let lastGate = null;
  let lastChanged = [];   // Phase 3c: the wave's changed files (for the GO commit)
  let lastCitation = exec?.citation || null;

  // eslint-disable-next-line no-constant-condition
  while (true) {
    // ----- ORCHESTRATOR GATE (ground truth) -----
    lastGate = runGate({ projectDir, testCommand, foremanDir, wave, iteration });
    log(`gate (iter ${iteration}): exit ${lastGate.exit_code} · ` +
      `tests ${lastGate.tap.tests} pass ${lastGate.tap.pass} fail ${lastGate.tap.fail}`);

    // ----- §6 vacuous-GREEN HALT (R2-3) -----
    // A gate that exited 0 without demonstrating real passing tests proves no
    // ground truth (§4.4/§5). Refuse it outright (exit 3) — never a silent RED
    // (which the fix loop would chase) and never a false GO. Non-zero exits fall
    // through to the normal RED/fix-loop path below.
    if (lastGate.vacuous_reason) {
      const reason = `vacuous-GREEN HALT: ${lastGate.vacuous_reason}`;
      steps.push(`✗ ${reason}`);
      return finishHalt({ reason, recommend:
        `the gate command (${testCommand}) exited 0 without running real passing tests; ` +
        `make the discovered test command actually execute the wave's tests (a real failing→passing run), then re-invoke wave ${wave.n}` });
    }

    // §8 idempotent-from-last-commit: when git is active the wave's changed set is
    // measured vs git HEAD (so a crash-before-commit RESUME still sees the prior
    // run's uncommitted deliverable, which the per-invocation hash snapshot would
    // miss). Without git, fall back to the hash-diff since this invocation started.
    const changed = git ? git.changedVsHead() : changedSince(projectDir, foremanDir, hashStart);
    lastChanged = changed;

    // ----- §5 test-integrity guard (any iteration) -----
    const invNow = inventory(projectDir, foremanDir);
    const weak = checkTestWeakening(invBefore, invNow, lastCitation, (lastGate.tap && lastGate.tap.skipped) || 0);
    if (weak) {
      const reason = `test-integrity HALT: ${weak}`;
      steps.push(`✗ ${reason}`);
      return finishHalt({ reason, recommend:
        `restore the removed/weakened tests, or cite the plan line that authorizes the change, then re-invoke wave ${wave.n}` });
    }

    // ----- Wave 7 test-immutability guard: the FIX loop must not touch tests -----
    const immutable = checkTestImmutability(testBaseline, projectDir, foremanDir, lastCitation);
    if (immutable) {
      const reason = `test-immutability HALT: ${immutable}`;
      steps.push(`✗ ${reason}`);
      return finishHalt({ reason, recommend:
        `the fix loop edited a test file — FIX may only change non-test code (tests are EXECUTE's deliverable). ` +
        `Revert the test change, or cite the plan line that authorizes it, then re-invoke wave ${wave.n}` });
    }

    // F-H sleep fix (0072): after GREEN gate, stamp checkpoint at review BEFORE the
    // long review agent call(s). If the process dies mid-review (empty stderr deaths
    // observed live), --resume re-enters with intraStep=review, skips execute, re-proves
    // gate, then retries review — never re-spends a full execute agent turn.
    if (lastGate.green) {
      try {
        const midCp = buildCheckpoint({
          planPath, totalWaves, wave, iteration, verdict: null,
          findings: findings.filter((f) => f.status === 'open'),
          status: 'running',
          reviewerCount,
          intraWaveStep: 'review',
          pendingAction:
            `wave ${wave.n}/${totalWaves} gate GREEN — entering review ` +
            `(if interrupted, --resume re-proves gate then review; never auto-GO)`,
          budgetRemaining: budget ? budget.snapshotForCheckpoint() : undefined,
        });
        writeCheckpointAtomic(checkpointPath, midCp);
        log(`checkpoint: stamped intra_wave_step=review after GREEN gate (crash-resilience)`);
      } catch (e) {
        log(`!! checkpoint stamp after GREEN failed (non-fatal): ${e?.message || e}`);
      }
    }

    // ----- REVIEW: REVIEWER_COUNT independent reviewers (§3) -----
    // Default SEQUENTIAL. SPIKE(foreman-parallel) A/B: with FOREMAN_CONCURRENT_REVIEW=1
    // the read-only reviewers run CONCURRENTLY via Promise.allSettled — order-independent
    // (collectFindings keys by stable id). A reviewer whose promise REJECTS is mapped to
    // an abstain (answerable:'no') so a degraded run HALTs at the §4.7 ambiguity gate
    // rather than silently passing on one reviewer (never Promise.all, which would drop
    // a surviving reviewer's findings). Flag OFF ⇒ byte-identical to the serial path.
    // ----- red-gate review skip (2026-07 efficiency; rigor-preserving) -----
    // On a RED gate the verdict is already determined: judge() can never return
    // GO (anti-forgery, above), and reviewer blocking power exists only against
    // a GREEN gate (§5: blocking GREEN requires a failing repro). So reviewers
    // on a red intermediate iteration decide nothing — the failing tests in the
    // gate artifact ARE the fix guidance. Skip the fan-out EXCEPT on the last
    // budgeted iteration (iteration >= fixIterCap ⇒ the next stop is a
    // non-convergence HALT): that final pass keeps the §4.7 ambiguity gate and
    // the §6/F3 PLAN-AMENDMENT channel attached to the halt the human is about
    // to read. Every GO still passes gate + full ≥2-agree adversarial review +
    // all §5 guards — unchanged. FOREMAN_REVIEW_ON_RED=1 restores the old
    // review-every-iteration behavior (A/B + non-regression seam).
    // T10b (2026-07-11): the reviewer fan-out is STAKES-GATED. Exact-string ≥2-agree
    // has never fired in a sampled live log ("0 agreed" every wave), so on an
    // ordinary clean wave the second reviewer bought ~2-5 min + 1 call for near-zero
    // verdict changes. Full panel where stakes are real: the TERMINAL wave, any wave
    // that needed fix iterations, or FOREMAN_FULL_REVIEW=1 (restores always-full).
    const fullPanel = process.env.FOREMAN_FULL_REVIEW === '1' ||
      (wave?.n != null && totalWaves != null && wave.n === totalWaves) || iteration > 0;
    const effectiveReviewers = fullPanel ? reviewerCount : Math.min(reviewerCount, 1);

    let reviews;
    if (!lastGate.green && process.env.FOREMAN_REVIEW_ON_RED !== '1' && iteration < fixIterCap) {
      reviews = [];
      steps.push(`▸ review skipped (gate RED, iter ${iteration}/${fixIterCap} — verdict already determined)`);
      log(`review: skipped — gate RED (reviewers can only block GREEN, §5); fix guidance = gate artifact`);
    } else if (reviewConcurrencyOn()) {
      if (effectiveReviewers < reviewerCount) {
        steps.push(`▸ review lean (${effectiveReviewers}/${reviewerCount} — ordinary mid-run wave; full panel on terminal/fix-iter waves)`);
      }
      const settled = await Promise.allSettled(
        Array.from({ length: effectiveReviewers }, (_, r) =>
          driver.review({ ...ctx, reviewerIndex: r, changed }, lastGate)));
      // T10a: a REJECTED reviewer call is a transport failure, not a plan problem.
      reviews = settled.map((s, r) => s.status === 'fulfilled' ? s.value : {
        reviewer: `reviewer-${r}`, answerable: 'transport-failed', transport_failed: true,
        note: `reviewer ${r} call rejected (${s.reason?.message || s.reason})`,
        findings: [],
      });
    } else {
      if (effectiveReviewers < reviewerCount) {
        steps.push(`▸ review lean (${effectiveReviewers}/${reviewerCount} — ordinary mid-run wave; full panel on terminal/fix-iter waves)`);
      }
      reviews = [];
      for (let r = 0; r < effectiveReviewers; r++) {
        reviews.push(await driver.review({ ...ctx, reviewerIndex: r, changed }, lastGate));
      }
    }

    // T10a (2026-07-11): DEGRADE, don't halt, on transport-failed reviewers. A lone
    // reviewer cannot block anyway (≥2-agree), so halting the whole run because ONE
    // reply didn't parse was fail-deadly (observed live: agy exit 1 nearly killed a
    // green wave). Drop the failed seats loudly; HALT only when the ENTIRE panel
    // failed (then nothing verified the wave — that is a real stop).
    const transportFailed = reviews.filter((rv) => rv && rv.transport_failed);
    if (transportFailed.length) {
      if (transportFailed.length === reviews.length && reviews.length > 0) {
        const reason = `review transport HALT: ALL ${reviews.length} reviewer(s) unreachable/unparseable — nothing verified this wave`;
        steps.push(`✗ ${reason}`);
        return finishHalt({ reason, recommend:
          `check the reviewer backend (agy/claude transport), then re-invoke wave ${wave.n} — this is a transport problem, not a plan problem` });
      }
      steps.push(`▸ review degraded: ${transportFailed.length} reviewer(s) dropped (transport failure) — proceeding with ${reviews.length - transportFailed.length}`);
      log(`review: ${transportFailed.length} transport-failed reviewer(s) dropped — ${transportFailed.map((rv) => rv.note).join(' · ')}`);
      reviews = reviews.filter((rv) => !(rv && rv.transport_failed));
    }

    // Ambiguity gate (§4.7): any reviewer answering "no" is a HALT. UNCHANGED —
    // this remains the bare hard-halt for "the docs don't answer this" (mere
    // ambiguity), and it is checked FIRST so F3 can never weaken it.
    const ambiguous = reviews.find((rv) => rv && rv.answerable === 'no');
    if (ambiguous) {
      const reason = `ambiguity HALT: a reviewer could not answer from the frozen docs`;
      steps.push(`✗ ${reason}`);
      return finishHalt({ reason, recommend: ambiguous.note ||
        `resolve the ambiguity in the plan and re-invoke wave ${wave.n}` });
    }

    // ----- §6 PLAN-AMENDMENT-PROPOSAL HALT (F3) -----
    // A build-time discovery that the FROZEN plan is wrong/incomplete for THIS wave
    // (an assumption falsified, an API not behaving as the plan assumed) is DISTINCT
    // from mere ambiguity above: the docs WERE answerable, but reality contradicts
    // them. Today that would be a bare hard-halt. F3 lets a review/execute agent
    // ATTACH a concrete proposed resolution — a PROPOSED DIFF to the plan doc + a
    // rationale — so the human can approve a BOUNDED amendment in one click instead
    // of doing a full manual round-trip.
    //
    // ANTI-DRIFT (critical): this is STILL a HALT. There is NO silent re-planning.
    // The proposal is recorded in the checkpoint `pending_action`; the human stays
    // in the loop and must approve before any plan change takes effect. F3 only
    // attaches a resolution to a halt that would otherwise be bare — every §5 guard
    // and the ambiguity gate above are unchanged. Requiring BOTH a non-empty diff
    // and a rationale keeps a bare blocker from masquerading as a proposal.
    const amendmentReview = reviews.find((rv) => rv && rv.plan_amendment &&
      typeof rv.plan_amendment.proposed_diff === 'string' && rv.plan_amendment.proposed_diff.trim() &&
      typeof rv.plan_amendment.rationale === 'string' && rv.plan_amendment.rationale.trim());
    if (amendmentReview) {
      const pa = amendmentReview.plan_amendment;
      const reason = `PLAN-AMENDMENT-PROPOSAL HALT: the frozen plan is wrong/incomplete for wave ${wave.n}`;
      steps.push(`✗ ${reason}`);
      return finishHalt({
        subType: 'PLAN-AMENDMENT-PROPOSAL',
        amendment: { proposed_diff: pa.proposed_diff, rationale: pa.rationale, target: pa.target ?? planPath },
        reason,
        recommend:
          `PLAN-AMENDMENT-PROPOSAL for wave ${wave.n}. Rationale: ${pa.rationale.trim()} ` +
          `Proposed diff to ${pa.target ?? planPath}:\n${pa.proposed_diff.trim()}\n` +
          `This is a HALT (no silent re-planning). To approve: apply the proposed diff to the plan doc ` +
          `YOURSELF (or have your session apply it), then resume with --resume --clear-halt — the wave re-enters ` +
          `at the gate and re-proves GREEN. (T12 honesty note, 2026-07-11: there is NO automatic apply-on-approval ` +
          `mechanism; the prior text promised one that was never built.)`,
      });
    }
    findings = collectFindings(reviews);
    const openBlockers = findings.filter((f) =>
      (f.severity === 'BLOCKER' || f.severity === 'MAJOR') && f.status === 'open' && f.agreement >= 2);
    if (reviews.length) log(`review: ${reviews.length} reviewers · ${openBlockers.length} agreed BLOCKER/MAJOR`);

    // ----- JUDGE (reads only the gate artifact for pass/fail of record) -----
    const verdict = judge(lastGate, findings);

    if (verdict.go) {
      // ----- vacuous-GREEN guard before declaring convergence (§5) -----
      // T4: hand the guard the test-only evidence it needs (wave-start inventory
      // snapshot, fresh inventory, the gate's executed counts, the wave title).
      const vac = checkVacuousGreen(projectDir, foremanDir, changed, {
        invBefore,
        invNow: inventory(projectDir, foremanDir),
        gateTap: lastGate.tap,
        waveTitle: wave.title || '',
        waveN: wave.n,
      });
      if (vac) {
        const reason = `vacuous-GREEN HALT: ${vac}`;
        steps.push(`✗ ${reason}`);
        const vacuousRecommend =
          /vacuous-GREEN/i.test(reason)
            ? `vacuous-GREEN: do NOT --clear-halt alone — that re-enters the same empty execute ` +
              `(journals 0076/0078/0079). Land import-tested source for this wave (or a valid ` +
              `source-only wave-${wave.n}-proven.json), then --resume. ` +
              `add/keep a test that exercises the changed code, then re-invoke wave ${wave.n}`
            : `add/keep a test that exercises the changed code, then re-invoke wave ${wave.n}`;
        return finishHalt({ reason, recommend: vacuousRecommend });
      }
      // Record proven deliverable for resume/clear-halt credit (Phase A).
      // Filter via writeWaveProvenLedger (never logs — 0078/0079 package 6).
      try {
        writeWaveProvenLedger(foremanDir, wave.n, {
          changed: lastChanged.filter((f) => !f.endsWith(' (deleted)') && !isTestFile(f)),
          tests: lastGate.tap?.tests ?? null,
          pass: lastGate.tap?.pass ?? null,
          at: new Date().toISOString(),
        });
      } catch { /* best-effort */ }
      steps.push(`✓ wave ${wave.n} converged (${iteration} fix iter${iteration === 1 ? '' : 's'}) · ` +
        `gate ${lastGate.tap.pass}/${lastGate.tap.tests} (orchestrator-run)`);
      log(`CONVERGED: ${verdict.reason}`);
      return finishGo();
    }

    // ----- not converged: do we have fix budget? (§6.3 MAX_ITERS) -----
    if (iteration >= fixIterCap) {
      const reason = `non-convergence HALT: hit MAX_ITERS=${fixIterCap} without GO (${verdict.reason})`;
      steps.push(`✗ ${reason}`);
      // §6.3: stash the failed attempt (when git is active) so the tree is clean
      // + recoverable, and record the ref in the checkpoint.
      return finishHalt({ stash: true, reason, recommend:
        `wave ${wave.n} did not converge in ${fixIterCap} fix iterations — inspect ${path.relative(projectDir, lastGate.artifact_path)} and the plan, then re-invoke` });
    }

    // ----- §6.1 BUDGET PRE-FLIGHT (HARD GATE, not advisory) -----
    // Before STARTING the next fix iteration (an affordable unit, §4.6), check the
    // budget. If the unit cannot be afforded, do NOT start it: write a clean,
    // resumable budget-stop checkpoint and stop — the engine never overruns by
    // beginning work it cannot finish. (Telemetry may be best-effort, but an
    // unreadable clock HALTs inside the budget rather than running unbounded.)
    if (budget) {
      const pf = budget.canStartFixIter();
      if (!pf.ok) {
        const reason = `budget stop: ${pf.reason}`;
        steps.push(`⏸ ${reason}`);
        log(reason);
        return finishBudgetStop({ reason, dimension: pf.dimension });
      }
    }

    // ----- FIX (single-threaded; model-driven) -----
    iteration++;
    const fix = await driver.fix({ ...ctx, iteration }, lastGate, findings);
    lastCitation = fix?.citation || lastCitation;
    steps.push(`▸ fix iter ${iteration}… ${fix?.note || 'applied'}`);
    log(`fix iter ${iteration}: ${fix?.note || 'applied'}`);
    // loop -> re-gate -> re-review
  }

  // --- closures that finalize state (checkpoint + dashboard) ---
  function dashboard(extraFooter) {
    return renderDashboard({
      project: projectDir,
      wave: wave.n,
      totalWaves,
      waveTitle: wave.title || '(untitled)',
      lines: steps,
      contextPct: null,         // best-effort: harness exposes no live quota API (§10)
      elapsed: null,            // best-effort
      budgetWaves: `${wave.n}/${totalWaves} waves`,
      window: 'OK',
    }) + (extraFooter ? `\n${extraFooter}` : '');
  }

  function finishGo() {
    const status = wave.n === totalWaves ? 'done' : 'running';
    // ----- §9 commit-on-GO + §8 ORDER: COMMIT first, THEN checkpoint -----
    // The commit happens ONLY here, after a genuine GO through the hardened gate
    // (an unproven/vacuous/RED/HALTed wave never reaches finishGo). The checkpoint
    // below records last_commit AFTER the commit lands, so a commit-then-crash
    // leaves HEAD ahead of last_commit (reconcile adopts HEAD; commitWave is
    // idempotent so a re-run makes no duplicate). git===null => unchanged (no
    // commit, last_commit stays null).
    let lastCommit;          // undefined => leave newCheckpoint's null (no git)
    if (git) {
      // Fix B (2026-06-04): RE-MEASURE the changed set AT COMMIT TIME rather than
      // reusing the snapshot taken before the reviewers ran. A reviewer mutating
      // the tree after that snapshot (e.g. adding a map.json entry) would otherwise
      // be DROPPED from the commit — the silent gap that left map.json uncommitted
      // across 4 waves. changedVsHead is still vs HEAD, preserving §8 resume.
      const filesToCommit = git.changedVsHead();
      const res = git.commitWave({ files: filesToCommit, wave, gate: lastGate });
      lastCommit = res.sha;
      steps.push(res.committed
        ? `▸ commit ${(res.sha || '').slice(0, 7)} on ${res.branch} (${res.files.length} file(s), no push)`
        : `▸ commit: nothing new to commit (work already at ${(res.sha || '').slice(0, 7)} on ${res.branch})`);
      log(res.committed
        ? `commit: ${(res.sha || '').slice(0, 7)} on ${res.branch} — ${res.files.length} file(s) (no push, no force)`
        : `commit: nothing to commit (idempotent); HEAD ${(res.sha || '').slice(0, 7)} on ${res.branch}`);
      // Fix B completeness guard: after the commit, NO tracked deliverable may
      // remain uncommitted. A non-empty residue means the commit did not capture
      // the wave's work — convert that silent failure into a loud, debuggable HALT
      // instead of a false GO. (.foreman/ + the checkpoint are already excluded.)
      const residue = git.dirtyEntries();
      if (residue.length) {
        return finishHalt({ reason:
          `incomplete commit: ${residue.length} tracked change(s) left uncommitted after the wave commit ` +
          `(e.g. "${residue[0]}") — the commit did not capture all of the wave's deliverables`,
          recommend:
          `inspect \`git status\`, ensure every deliverable is staged, then re-invoke wave ${wave.n} ` +
          `(if a reviewer mutated the tree, run reviewers read-only).` });
      }
    }
    const cp = buildCheckpoint({
      planPath, totalWaves, wave, iteration, verdict: 'GO',
      findings: findings.filter((f) => f.status === 'open'),
      status, reviewerCount, lastCommit,
      budgetRemaining: budget ? budget.snapshotForCheckpoint() : undefined,
      pendingAction: wave.n === totalWaves
        ? `project DONE candidate: terminal wave ${wave.n} GREEN (Phase 2 evaluates plan-level acceptance)`
        : `wave ${wave.n} converged GREEN; auto-advance to wave ${wave.n + 1}`,
    });
    writeCheckpointAtomic(checkpointPath, cp);
    const dash = dashboard();
    log(dash);
    return { status: 'GO', verdict: 'GO', iterations: iteration, gate: lastGate,
      findings, checkpoint: cp, checkpointPath, dashboard: dash, lastCommit: lastCommit ?? null };
  }

  function finishHalt({ reason, recommend, stash = false, subType = null, amendment = null }) {
    // §6.3 non-convergence ONLY: stash the failed attempt so the tree is left
    // clean + recoverable, recording the ref. Other halts leave the tree as-is for
    // the human to inspect (the checkpoint is `halted` and is never auto-resumed).
    let stashRef;
    let recommend2 = recommend;
    if (stash && git) {
      const ref = git.stashFailedAttempt(`foreman: wave ${wave.n} non-convergence attempt (MAX_ITERS)`);
      if (ref) {
        stashRef = ref;
        steps.push(`▸ stashed failed attempt -> ${ref} (tree left clean, recoverable)`);
        log(`stash: failed attempt saved as ${ref}; working tree restored clean`);
        recommend2 = `${recommend} The failed attempt was stashed as ${ref} (\`git stash show -p --include-untracked ${ref}\` to inspect — the \`--include-untracked\` flag is required or new untracked files show an empty diff; \`git stash drop ${ref}\` to discard); the tree is clean.`;
      }
    }
    const cp = buildCheckpoint({
      planPath, totalWaves, wave, iteration, verdict: 'HALT',
      findings: findings.filter((f) => f.status === 'open'),
      status: 'halted', reviewerCount, pendingAction: recommend2, stashRef,
      budgetRemaining: budget ? budget.snapshotForCheckpoint() : undefined,
    });
    writeCheckpointAtomic(checkpointPath, cp);
    const dash = dashboard(`HALT: ${reason}`);
    log(dash);
    return { status: 'HALT', verdict: 'HALT', haltReason: reason, recommend: recommend2,
      haltSubType: subType, amendment,
      iterations: iteration, gate: lastGate, findings, checkpoint: cp, checkpointPath, dashboard: dash, stashRef: stashRef ?? null };
  }

  // A BUDGET stop (§6.1) is a CLEAN, resumable checkpoint — distinct in state from
  // an error HALT (status 'halted', last_verdict 'HALT', NOT auto-resumed) and from
  // project-DONE (status 'done'). It records intra_wave_step='gate' + the consumed
  // iteration count so resume re-enters this wave AT THE GATE and re-proves GREEN
  // with its remaining fix budget — never advancing or GOing without real tests.
  function finishBudgetStop({ reason, dimension }) {
    const recommend =
      `BUDGET STOP (${dimension}) at wave ${wave.n}, after ${iteration} fix iteration(s): ${reason}. ` +
      `This is a clean, resumable checkpoint — re-invoke with --resume once the budget / Pro usage window resets ` +
      `(§7), or raise the cap. Resume re-enters wave ${wave.n} at the GATE and must re-prove real passing tests ` +
      `before any GO (resume is never a backdoor to GREEN).`;
    const cp = buildCheckpoint({
      planPath, totalWaves, wave, iteration, verdict: 'BUDGET-STOP',
      findings: findings.filter((f) => f.status === 'open'),
      status: 'budget_stopped', reviewerCount, pendingAction: recommend,
      intraWaveStep: 'gate',
      budgetRemaining: budget ? budget.snapshotForCheckpoint() : undefined,
    });
    writeCheckpointAtomic(checkpointPath, cp);
    const dash = dashboard(`BUDGET-STOP: ${reason}`);
    log(dash);
    return { status: 'BUDGET-STOP', verdict: 'BUDGET-STOP', haltReason: reason, recommend,
      dimension, iterations: iteration, gate: lastGate, findings, checkpoint: cp, checkpointPath, dashboard: dash };
  }
}

/** Path of the per-wave proven-attempt ledger under .foreman/ */
export function waveProvenPath(foremanDir, waveN) {
  return path.join(foremanDir, `wave-${waveN}-proven.json`);
}

/**
 * Filter + write ledger after a real GO so a later resume with empty hash-diff
 * can credit prior same-wave code. Never stores runtime logs as deliverables
 * (0078/0079 — Track D log-poison). Skips write when no code paths remain
 * (does not overwrite a prior source-rich ledger with an empty/log-only set).
 */
export function writeWaveProvenLedger(foremanDir, waveN, payload = {}) {
  if (!foremanDir || !waveN) return null;
  fs.mkdirSync(foremanDir, { recursive: true });
  const p = waveProvenPath(foremanDir, waveN);
  const rawChanged = Array.isArray(payload.changed) ? payload.changed : [];
  const filtered = rawChanged
    .map((f) => String(f).replace(/\\/g, '/'))
    .filter((f) => isProvenDeliverablePath(f));

  if (!filtered.length) {
    // Prefer keeping an existing source-rich ledger over writing log-only poison.
    try {
      const prev = JSON.parse(fs.readFileSync(p, 'utf8'));
      if (Array.isArray(prev.changed) && prev.changed.some((f) => isProvenDeliverablePath(f))) {
        return p; // leave prior good ledger in place
      }
    } catch { /* none */ }
    // No good prior and nothing to store — do not write a log-only ledger.
    return null;
  }

  const body = {
    version: 1,
    wave: waveN,
    ...payload,
    changed: filtered,
  };
  fs.writeFileSync(p, `${JSON.stringify(body, null, 2)}\n`, 'utf8');
  return p;
}

export function readWaveProvenLedger(foremanDir, waveN) {
  try {
    return JSON.parse(fs.readFileSync(waveProvenPath(foremanDir, waveN), 'utf8'));
  } catch {
    return null;
  }
}

/**
 * Credit a prior same-wave attempt when this invocation's hash-diff is empty
 * but the ledger lists code that still exists and is still test-reachable.
 * North-Star-safe: never skips the orchestrator gate (caller already has GREEN);
 * only avoids a false "no deliverable" HALT after re-prove.
 */
export function creditPriorWaveAttempt(root, foremanDir, waveN, { reach, exercisedByName } = {}) {
  if (!waveN || !foremanDir) {
    return { ok: false, note: 'no wave ledger context' };
  }
  const led = readWaveProvenLedger(foremanDir, waveN);
  if (!led || !Array.isArray(led.changed) || !led.changed.length) {
    return { ok: false, note: 'no prior-attempt ledger for this wave' };
  }
  const live = [];
  for (const f of led.changed) {
    const rel = String(f).replace(/\\/g, '/');
    if (rel.endsWith(' (deleted)') || isTestFile(rel) || !isProvenDeliverablePath(rel)) continue;
    const abs = path.join(root, rel);
    if (!fs.existsSync(abs)) {
      return { ok: false, note: `prior deliverable missing: ${rel}` };
    }
    live.push(rel);
  }
  if (!live.length) {
    return { ok: false, note: 'prior ledger had no live code paths (logs/noise filtered)' };
  }
  const exercised = live.some((f) => (reach && reach.has(f)) || (exercisedByName && exercisedByName(f)));
  if (!exercised) {
    return { ok: false, note: `prior code still on disk but not exercised by tests: ${live.join(', ')}` };
  }
  return { ok: true, note: `credited prior wave-${waveN} attempt (${live.length} path(s))`, paths: live };
}

export const _internals = {
  inventory, checkTestWeakening, checkVacuousGreen, reachableFromTests,
  changedSince, snapshotHashes, parseCount, hasRealTestEvents, countTestEvents, findingId,
  isRuntimeNoisePath, isProvenDeliverablePath,
  // Wave 7 test-immutability guard:
  testHashSnapshot, checkTestImmutability,
  // Phase 3d (Python/pytest generalization) internals:
  isTestFile, looksLikePytest, parsePytestCount, extractImports, resolveImportTargets,
  // Phase A (2026-07-22): prior-attempt credit
  creditPriorWaveAttempt, writeWaveProvenLedger, readWaveProvenLedger, waveProvenPath,
};
