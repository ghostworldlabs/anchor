// Wave 4 done-when: the system deterministically merges multiple thread
// outputs into a single inline ledger where every accepted claim is
// hyperlinked to exact quotes, and unverified/rejected claims are prominently
// documented without silent data loss.
//
// Given multiple valid quote extractions and one structurally unverified
// claim from the isolated threads, when the terminal join consolidates the
// isolated thread outputs, then valid claims are merged into the final inline
// ledger with an unbroken evidence lineage, while the unverified claim is
// prominently surfaced and documented as rejected.
import { test, describe } from 'node:test';
import assert from 'node:assert';
import { terminalJoin, formatEvidenceLedgerMarkdown } from '../src/terminalJoin.mjs';
import { validateSchema, ValidationError } from '../src/validateSchema.mjs';
import { normalizeText } from '../src/textNormalization.mjs';
import { sanitizeText } from '../src/structuralSanitizer.mjs';
import runExtraction from '../src/tasks/quoteExtractionTask.mjs';

const CTX = { log() {}, progress() {} };

// Three primary sources with erratic whitespace, so the joined evidence has to
// survive the same normalization gauntlet the Wave-3 workers apply.
const SOURCES = {
  'P-001': 'Isolated worker threads emit \t telemetry  in real   time,\r\nand the terminal join must merge them deterministically.',
  'P-002': 'Every accepted claim keeps an *unbroken* evidence lineage back to the primary source material.',
  'P-003': 'Rejected claims are surfaced prominently; unverified structure is documented, never silently lost.'
};

async function buildThreadOutputs() {
  const out1 = await runExtraction({
    paperId: 'P-001',
    sourceText: SOURCES['P-001'],
    candidates: [
      { claimId: 'c-tel', statement: 'Workers stream live telemetry.', column: 'telemetry', quote: 'isolated worker threads EMIT telemetry in real time' },
      { claimId: 'c-join', statement: 'The join is deterministic.', column: 'join', quote: 'the terminal join must merge them  deterministically' },
      { claimId: 'c-ghost', statement: 'Fabricated support.', column: 'join', quote: 'blockchain quantum synergy at the join' }
    ]
  }, CTX);
  const out2 = await runExtraction({
    paperId: 'P-002',
    sourceText: SOURCES['P-002'],
    candidates: [
      { claimId: 'c-lineage', statement: 'Lineage is unbroken.', column: 'lineage', quote: 'unbroken* evidence lineage back to the primary source' }
    ]
  }, CTX);
  const out3 = await runExtraction({
    paperId: 'P-003',
    sourceText: SOURCES['P-003'],
    candidates: [
      { claimId: 'c-surf', statement: 'Rejections are surfaced.', column: 'rejection-ux', quote: 'rejected claims are surfaced prominently' },
      { claimId: 'c-doc', statement: 'Unverified structure is documented.', column: 'rejection-ux', quote: 'unverified structure is documented' }
    ]
  }, CTX);

  // ONE structurally unverified claim: a thread record that lost its verbatim
  // span and carries an impossible occurrence count.
  const tampered = structuredClone(out3);
  const docIdx = tampered.quotes.findIndex((q) => q.claimId === 'c-doc');
  assert.notEqual(docIdx, -1);
  delete tampered.quotes[docIdx].verbatimQuote;
  tampered.quotes[docIdx].occurrences = 0;
  // Plus a well-formed record whose offsets do NOT reproduce its quotes — it
  // must fail lineage re-verification against the primary source.
  tampered.quotes.push({
    claimId: 'c-forged',
    statement: 'Forged claim with fabricated offsets.',
    column: null,
    verbatimQuote: 'totally fabricated span',
    normalizedQuote: 'totally fabricated span',
    start: 0,
    end: 23,
    occurrences: 1
  });

  return { out1, out2, tampered };
}

function settledEntries({ out1, out2, tampered }) {
  return [
    { status: 'completed', batchId: 0, workerId: 'w-0', paperId: 'P-001', depth: 0, columns: ['telemetry', 'join'], result: out1 },
    { status: 'completed', batchId: 1, workerId: 'w-1', paperId: 'P-002', depth: 0, columns: ['lineage'], result: out2 },
    { status: 'completed', batchId: 2, workerId: 'w-2', paperId: 'P-003', depth: 0, columns: ['rejection-ux'], result: tampered },
    { status: 'failed', batchId: 3, workerId: 'w-3', paperId: 'P-004', depth: 0, columns: [], error: { message: 'worker crashed before completion', name: 'Error', state: 'crashed' } }
  ];
}

describe('structural deterministic terminal join (Wave 4 done-when)', () => {
  test('merges thread outputs into one hyperlinked inline ledger; rejections and failures stay prominent', async () => {
    const outputs = await buildThreadOutputs();
    const entries = settledEntries(outputs);
    const report = { batches: 4, completed: entries.slice(0, 3), failed: entries.slice(3) };
    const ledger = terminalJoin(report, { sources: SOURCES });

    // No silent data loss: every thread and every record is accounted for.
    assert.deepEqual(ledger.stats, {
      threads: 4,
      completedThreads: 3,
      failedThreads: 1,
      claims: 7,
      accepted: 4,
      rejected: 3,
      duplicatesMerged: 0
    });
    assert.equal(ledger.stats.claims, ledger.accepted.length + ledger.rejected.length);

    // Valid claims from ALL isolated threads merged, in canonical order.
    assert.deepEqual(ledger.accepted.map((a) => a.claimId), ['c-tel', 'c-join', 'c-lineage', 'c-surf']);
    assert.deepEqual(ledger.sources.map((src) => src.paperId), ['P-001', 'P-002', 'P-003', 'P-004']);

    // Unbroken evidence lineage, re-proved INDEPENDENTLY of the join: every
    // accepted claim's recorded [start, end) span of the primary source
    // reproduces its quotes exactly, and the join marked it VERIFIED.
    for (const a of ledger.accepted) {
      assert.equal(a.lineage, 'VERIFIED');
      const raw = SOURCES[a.paperId];
      const rawSpan = raw.slice(a.evidence.start, a.evidence.end);
      assert.equal(a.evidence.verbatimQuote, sanitizeText(rawSpan));
      assert.equal(a.evidence.normalizedQuote, sanitizeText(normalizeText(rawSpan)));
      assert.ok(normalizeText(raw).includes(normalizeText(rawSpan)), `${a.claimId} must match the normalized source`);
    }

    // Rigid hyperlinks: each accepted claim carries a deterministic anchor
    // that resolves to its source's index in the sources list.
    const anchors = ledger.accepted.map((a) => a.evidence.anchor);
    assert.equal(new Set(anchors).size, anchors.length);
    for (const a of ledger.accepted) {
      const m = a.evidence.anchor.match(/^evidence-s(\d+)-(\d+)-(\d+)$/);
      assert.ok(m, `rigid anchor format: ${a.evidence.anchor}`);
      assert.equal(ledger.sources[Number(m[1])].paperId, a.paperId);
      assert.equal(Number(m[2]), a.evidence.start);
      assert.equal(Number(m[3]), a.evidence.end);
    }

    // The unverified/rejected claims are documented EXPLICITLY, with reasons:
    // the worker's ungrounded rejection is carried through, the structurally
    // unverified record and the forged-offsets record are rejected at the join.
    assert.deepEqual(
      ledger.rejected.map((r) => [r.claimId, r.reason]),
      [
        ['c-ghost', 'not-in-source'],
        ['c-doc', 'structurally-unverified'],
        ['c-forged', 'lineage-mismatch']
      ]
    );
    assert.match(ledger.rejected[0].rejection, /UNGROUNDED-QUOTE/);
    assert.match(ledger.rejected[1].rejection, /STRUCTURALLY-UNVERIFIED/);
    assert.match(ledger.rejected[2].rejection, /LINEAGE-MISMATCH/);

    // The failed thread is documented too — never silently dropped.
    assert.deepEqual(ledger.failedThreads, [{
      batchId: 3,
      paperId: 'P-004',
      workerId: 'w-3',
      error: { name: 'Error', message: 'worker crashed before completion' }
    }]);

    // The joined ledger conforms to the rigid registered schema.
    assert.equal(validateSchema(ledger, 'EvidenceLedger'), true);
    assert.throws(() => validateSchema({}, 'EvidenceLedger'), ValidationError);
    assert.throws(() => validateSchema({ ...ledger, extra: true }, 'EvidenceLedger'), ValidationError);
  });

  test('the join is deterministic: any thread completion order yields identical output', async () => {
    const outputs = await buildThreadOutputs();
    const entries = settledEntries(outputs);
    const forward = terminalJoin(entries, { sources: SOURCES });
    const reversed = terminalJoin([...entries].reverse(), { sources: SOURCES });
    assert.deepEqual(reversed, forward);
    assert.equal(formatEvidenceLedgerMarkdown(reversed), formatEvidenceLedgerMarkdown(forward));
    // Report shape and flat-array shape agree too.
    const asReport = terminalJoin({ batches: 4, completed: entries.slice(0, 3), failed: entries.slice(3) }, { sources: SOURCES });
    assert.deepEqual(asReport, forward);
  });

  test('the inline Markdown ledger hyperlinks every accepted claim and surfaces every rejection prominently', async () => {
    const outputs = await buildThreadOutputs();
    const ledger = terminalJoin(settledEntries(outputs), { sources: SOURCES });
    const md = formatEvidenceLedgerMarkdown(ledger);

    // Prominent no-silent-loss banner up front.
    assert.match(md, /3 claim\(s\) were REJECTED and 1 thread\(s\) FAILED/);
    assert.match(md, /nothing was silently dropped/);

    // Every accepted claim's exact quote is an inline hyperlink into the
    // anchored evidence appendix.
    for (const a of ledger.accepted) {
      assert.ok(md.includes(`](#${a.evidence.anchor})`), `inline hyperlink for ${a.claimId}`);
      assert.ok(md.includes(`<a id="${a.evidence.anchor}"></a>`), `evidence anchor for ${a.claimId}`);
      assert.ok(md.includes(`[“${a.evidence.normalizedQuote}”](#${a.evidence.anchor})`), `exact quote inline for ${a.claimId}`);
      assert.ok(md.includes(`> ${a.evidence.verbatimQuote}`), `verbatim span in appendix for ${a.claimId}`);
    }

    // Rejected claims and failed threads get their own prominent sections.
    assert.match(md, /## ⚠ Rejected claims/);
    assert.match(md, /## ⚠ Failed threads/);
    for (const r of ledger.rejected) {
      assert.ok(md.includes(`| ${r.claimId} |`), `rejected row for ${r.claimId}`);
      assert.ok(md.includes(r.rejection), `rejection message surfaced for ${r.claimId}`);
    }
    assert.ok(md.includes('worker crashed before completion'));
  });

  test('duplicate thread records merge losslessly with combined provenance', async () => {
    const { out1 } = await buildThreadOutputs();
    const base = { status: 'completed', workerId: 'w-0', paperId: 'P-001', depth: 0, result: out1 };
    const ledger = terminalJoin([
      { ...base, batchId: 0 },
      { ...base, batchId: 7, workerId: 'w-dup' }
    ], { sources: { 'P-001': SOURCES['P-001'] } });

    // 3 records per thread (2 grounded + 1 rejected), the second thread's are
    // all merged as duplicates — counted, not silently collapsed.
    assert.equal(ledger.stats.duplicatesMerged, 3);
    assert.equal(ledger.stats.accepted, 2);
    assert.equal(ledger.stats.rejected, 1);
    assert.deepEqual(ledger.accepted[0].provenance.batchIds, [0, 7]);
    assert.deepEqual(ledger.accepted[0].provenance.workerIds, ['w-0', 'w-dup']);
  });

  test('without raw sources the join stays honest: claims carry the weaker STRUCTURAL lineage', async () => {
    const outputs = await buildThreadOutputs();
    const ledger = terminalJoin(settledEntries(outputs));
    assert.ok(ledger.accepted.length > 0);
    for (const a of ledger.accepted) assert.equal(a.lineage, 'STRUCTURAL');
    // The structurally unverified record is still rejected even with no source
    // to re-verify against — structure alone condemns it.
    assert.ok(ledger.rejected.some((r) => r.claimId === 'c-doc' && r.reason === 'structurally-unverified'));
  });

  test('a completed thread with a malformed output is surfaced as a failed thread, not consumed', async () => {
    const ledger = terminalJoin([
      { status: 'completed', batchId: 0, workerId: 'w-0', paperId: 'P-009', result: { garbage: true } }
    ]);
    assert.equal(ledger.stats.completedThreads, 0);
    assert.equal(ledger.stats.failedThreads, 1);
    assert.equal(ledger.failedThreads[0].error.name, 'MalformedThreadOutput');
    const md = formatEvidenceLedgerMarkdown(ledger);
    assert.match(md, /MalformedThreadOutput/);
  });

  test('an empty run joins to a valid, explicitly empty ledger', () => {
    const ledger = terminalJoin([]);
    assert.deepEqual(ledger.stats, {
      threads: 0, completedThreads: 0, failedThreads: 0,
      claims: 0, accepted: 0, rejected: 0, duplicatesMerged: 0
    });
    assert.equal(validateSchema(ledger, 'EvidenceLedger'), true);
    const md = formatEvidenceLedgerMarkdown(ledger);
    assert.match(md, /_None\._/);
    assert.match(md, /_No evidence — no claims were accepted\._/);
  });
});
