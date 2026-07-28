// test/intake-budget-manifest.test.mjs — Wave 6: pre-flight intake budget + the
// pre-Gandalf manifest (trio-shared/brownfield-intake/intakeBudget.mjs +
// intakeManifest.mjs, resolved via the Wave-1 pinned trio home).
//
// Pins the Wave-6 acceptance: an over-budget root set FAILS FAST at the door with a
// narrow-your-roots message (never a blocking mid-run prompt, never a Gandalf call);
// with the EXPLICIT auto-truncate flag it truncates deterministically (declared roots
// first, stable path sort, head-of-file spans) and STAMPS the result truncated; the
// manifest is display + fail-fast with ZERO approval prompts and is explicitly NOT a
// second approval gate; and SUMMARY_MAX is defined by the pinned arithmetic
// DERIVE_CONTEXT - DERIVE_PROMPT_OVERHEAD - SEED_CONTEXT_CAP
// - (FENCE_FRAMING_TOKENS * MAX_FENCED_BLOCKS) — the Wave-8 revision that accounts
// for the per-source data-fencing framing, which scales with the NUMBER of sources.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';

let ib; // intakeBudget module under test
let im; // intakeManifest module under test

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  ib = await import(new URL('intakeBudget.mjs', indexUrl).href);
  im = await import(new URL('intakeManifest.mjs', indexUrl).href);
});

/** Run `fn` while spying on every stdin entry point; returns [result, promptCalls]. */
function withStdinSpy(fn) {
  const stdin = process.stdin;
  const spied = ['on', 'once', 'read', 'resume', 'addListener'];
  const originals = new Map(spied.map((k) => [k, stdin[k]]));
  let promptCalls = 0;
  for (const k of spied) {
    stdin[k] = (...args) => {
      promptCalls += 1;
      return originals.get(k).apply(stdin, args);
    };
  }
  try {
    return [fn(), promptCalls];
  } finally {
    for (const k of spied) stdin[k] = originals.get(k);
  }
}

/** The two-root over-budget fixture used by the truncation tests (fresh per call). */
function makeOverBudgetFixture() {
  const roots = ['rootB', 'rootA']; // DECLARED order: rootB first, deliberately non-alphabetical
  const files = [
    { root: 'rootA', path: 'n.md', text: 'N'.repeat(40) }, // 10 tokens
    { root: 'rootB', path: 'z.md', text: 'Z'.repeat(40) }, // 10 tokens
    { root: 'rootA', path: 'm.md', text: 'M'.repeat(40) }, // 10 tokens
    { root: 'rootB', path: 'a.md', text: 'A'.repeat(40) }, // 10 tokens
  ];
  return { roots, files }; // estimate: 40 tokens total
}

describe('Wave 6 — intake budget: pinned arithmetic + estimator', () => {
  test('SUMMARY_MAX = DERIVE_CONTEXT - DERIVE_PROMPT_OVERHEAD - INTENT_CONTEXT_CAP - SEED_CONTEXT_CAP - DERIVE_OUTPUT_RESERVE - (FENCE_FRAMING_TOKENS * MAX_FENCED_BLOCKS), all positive', () => {
    assert.equal(
      ib.SUMMARY_MAX,
      ib.DERIVE_CONTEXT -
        ib.DERIVE_PROMPT_OVERHEAD -
        ib.INTENT_CONTEXT_CAP -
        ib.SEED_CONTEXT_CAP -
        ib.DERIVE_OUTPUT_RESERVE -
        ib.FENCE_FRAMING_TOKENS * ib.MAX_FENCED_BLOCKS,
    );
    assert.ok(ib.DERIVE_CONTEXT > 0 && ib.DERIVE_PROMPT_OVERHEAD > 0 && ib.SEED_CONTEXT_CAP > 0);
    assert.ok(ib.INTENT_CONTEXT_CAP > 0);
    assert.ok(ib.FENCE_FRAMING_TOKENS > 0 && ib.MAX_FENCED_BLOCKS > 0);
    // The output reserve covers the derive call's own emission at its char cap.
    assert.ok(
      ib.DERIVE_OUTPUT_RESERVE >= Math.ceil(ib.DERIVE_MAX_OUTPUT_CHARS / ib.CHARS_PER_TOKEN),
    );
    assert.ok(ib.SUMMARY_MAX > 0);
  });

  test('the token estimate is the pinned deterministic heuristic ceil(chars / CHARS_PER_TOKEN)', () => {
    assert.equal(ib.estimateTokensForText(''), 0);
    assert.equal(ib.estimateTokensForText('x'.repeat(ib.CHARS_PER_TOKEN)), 1);
    assert.equal(ib.estimateTokensForText('x'.repeat(ib.CHARS_PER_TOKEN + 1)), 2);
  });
});

describe('Wave 6 — intake budget: fail-fast vs deterministic auto-truncate', () => {
  test('acceptance GWT: over budget WITHOUT the flag fails fast with a narrow-your-roots message', () => {
    const { roots, files } = makeOverBudgetFixture();
    const [decision, promptCalls] = withStdinSpy(() =>
      ib.preflightIntakeBudget({ roots, files, budgetTokens: 25 }),
    );
    assert.equal(decision.decision, 'fail-fast');
    assert.match(decision.reason, /narrow your roots/i);
    assert.equal(decision.estimatedTokens, 40);
    assert.equal(decision.budgetTokens, 25);
    assert.equal(decision.truncated, false);
    // Fail-fast is a DOOR decision: it carries no content for any downstream call —
    // there is nothing here a Gandalf invocation could even consume.
    assert.equal('files' in decision, false);
    // Never a blocking mid-run prompt: synchronous, zero stdin touches.
    assert.equal(promptCalls, 0);
    assert.equal(typeof decision.then, 'undefined');
  });

  test('acceptance GWT: the EXPLICIT flag truncates deterministically — declared roots first, stable path sort, head-of-file spans — and stamps truncated', () => {
    const { roots, files } = makeOverBudgetFixture();
    const run = () => ib.preflightIntakeBudget({ roots, files, budgetTokens: 25, autoTruncate: true });
    const [decision, promptCalls] = withStdinSpy(run);

    assert.equal(decision.decision, 'auto-truncate');
    assert.equal(promptCalls, 0);

    // Declared-root order FIRST (rootB before rootA despite alphabet), then stable
    // path sort within a root: a.md, z.md (rootB), then m.md (rootA head-only).
    assert.deepStrictEqual(
      decision.files.map((f) => [f.root, f.path, f.headOnly]),
      [
        ['rootB', 'a.md', false],
        ['rootB', 'z.md', false],
        ['rootA', 'm.md', true],
      ],
    );
    // The boundary file keeps exactly the head-of-file span the remaining budget covers.
    const head = decision.files[2];
    assert.deepStrictEqual(head.span, { start: 0, end: 5 * ib.CHARS_PER_TOKEN });
    assert.equal(head.text, 'M'.repeat(5 * ib.CHARS_PER_TOKEN));
    assert.equal(head.tokens, 5);
    // Past the boundary, files are dropped and named.
    assert.deepStrictEqual(decision.dropped, [{ root: 'rootA', path: 'n.md' }]);
    // The kept total honors the budget and the decision is STAMPED truncated.
    assert.equal(decision.keptTokens, 25);
    assert.ok(decision.keptTokens <= decision.budgetTokens);
    assert.equal(decision.truncated, true);
    assert.equal(decision.stamp.truncated, true);
    assert.equal(decision.stamp.stamp, ib.TRUNCATED_STAMP);

    // Deterministic: an identical second run produces byte-identical decisions.
    assert.deepStrictEqual(run(), decision);
  });

  test('within budget: everything kept whole, no truncation, no stamp', () => {
    const { roots, files } = makeOverBudgetFixture();
    const decision = ib.preflightIntakeBudget({ roots, files, budgetTokens: 40 });
    assert.equal(decision.decision, 'within-budget');
    assert.equal(decision.truncated, false);
    assert.equal(decision.files.length, 4);
    assert.ok(decision.files.every((f) => f.headOnly === false));
    assert.equal('stamp' in decision, false);
  });
});

describe('Wave 6 — pre-Gandalf manifest: display + fail-fast, NOT a gate, zero prompts', () => {
  const fileSet = {
    files: [{ path: 'a.md' }, { path: 'notes/b.md' }],
    rejected: [
      { path: 'esc', reason: 'symlink-escape', detail: 'real path escapes the root' },
    ],
  };
  const seeds = {
    seeds: [{ idType: 'doi', id: '10.1000/x.y', title: 'Seed Paper' }],
    rejected: [{ seed: {}, reason: 'malformed pmid identifier' }],
  };

  test('acceptance GWT: manifest carries roots + files + estimate + seeds and fails fast with zero approval prompts', () => {
    const { roots, files } = makeOverBudgetFixture();
    const budget = ib.preflightIntakeBudget({ roots, files, budgetTokens: 25 });
    const [rendered, promptCalls] = withStdinSpy(() => {
      const manifest = im.buildIntakeManifest({ roots, fileSet, budget, seeds });
      return { manifest, text: im.renderIntakeManifest(manifest) };
    });
    const { manifest, text } = rendered;

    // Structure: everything the plan names is present.
    assert.equal(manifest.manifestVersion, im.INTAKE_MANIFEST_VERSION);
    assert.deepStrictEqual(manifest.roots, ['rootB', 'rootA']);
    assert.deepStrictEqual(manifest.files.map((f) => f.path), ['a.md', 'notes/b.md']);
    assert.equal(manifest.budget.estimatedTokens, 40);
    assert.equal(manifest.budget.budgetTokens, 25);
    assert.equal(manifest.budget.decision, 'fail-fast');
    assert.deepStrictEqual(manifest.seeds.accepted, [
      { idType: 'doi', id: '10.1000/x.y', title: 'Seed Paper' },
    ]);
    assert.equal(manifest.seeds.rejected.length, 1);
    assert.equal(manifest.securityRejections[0].reason, 'symlink-escape');

    // Fail-fast verdict, structurally NOT a gate, and no prompt was ever issued.
    assert.equal(manifest.notAGate, true);
    assert.equal(manifest.proceed, false);
    assert.equal(manifest.failFastReasons.length, 1);
    assert.deepStrictEqual(im.manifestFailFast(manifest), {
      proceed: false,
      reasons: manifest.failFastReasons,
    });
    assert.equal(promptCalls, 0);
    assert.ok(Object.isFrozen(manifest));

    // Display: the render names the not-a-gate stance and every section.
    assert.ok(text.includes('NOT an approval'));
    assert.ok(text.includes('rootB') && text.includes('rootA'));
    assert.ok(text.includes('a.md') && text.includes('notes/b.md'));
    assert.ok(text.includes('40') && text.includes('25'));
    assert.ok(text.includes('doi:10.1000/x.y'));
    assert.ok(text.includes('REJECTED'));
    assert.ok(text.includes('FAIL FAST'));
    assert.ok(text.includes('narrow your roots'));

    // Deterministic display.
    assert.equal(im.renderIntakeManifest(manifest), text);
  });

  test('a within-budget manifest proceeds (still without asking anyone anything)', () => {
    const { roots, files } = makeOverBudgetFixture();
    const budget = ib.preflightIntakeBudget({ roots, files, budgetTokens: 40 });
    const [manifest, promptCalls] = withStdinSpy(() =>
      im.buildIntakeManifest({ roots, fileSet: { files: [], rejected: [] }, budget, seeds }),
    );
    assert.equal(manifest.proceed, true);
    assert.deepStrictEqual(manifest.failFastReasons, []);
    assert.equal(promptCalls, 0);
    // Budget-decided file spans (with token counts) flow into the manifest display.
    assert.equal(manifest.files.length, 4);
    assert.ok(manifest.files.every((f) => Number.isInteger(f.tokens)));
    const text = im.renderIntakeManifest(manifest);
    assert.ok(text.includes('PROCEED'));
  });

  test('an auto-truncate manifest surfaces the truncated stamp in structure and display', () => {
    const { roots, files } = makeOverBudgetFixture();
    const budget = ib.preflightIntakeBudget({ roots, files, budgetTokens: 25, autoTruncate: true });
    const manifest = im.buildIntakeManifest({ roots, fileSet: { files: [], rejected: [] }, budget, seeds: {} });
    assert.equal(manifest.proceed, true, 'auto-truncate proceeds (bounded), it does not fail fast');
    assert.equal(manifest.budget.truncated, true);
    assert.equal(manifest.budget.stamp.stamp, ib.TRUNCATED_STAMP);
    const text = im.renderIntakeManifest(manifest);
    assert.ok(text.includes('TRUNCATED'));
  });
});
