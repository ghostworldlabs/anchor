// C8 (2026-07-11): the lean extraction path + the whitelist/gate behavior changes.
import test from 'node:test';
import assert from 'node:assert/strict';
import { extractLedgerLean, LEAN_LEDGER_SCHEMA } from '../src/extraction.mjs';
import { evaluateFilters, DEFAULT_VENUE_WHITELIST } from '../src/search.mjs';
import { runMixedInitiativeGate } from '../src/gate.mjs';

const PAPER = { paperId: 'abc12345', title: 'T', authors: [{ name: 'A' }], venue: 'arXiv', year: 2026, citationCount: 3 };
const TEXT = 'We measure a sustained throughput of 150 requests per second on the production replica. Latency stays under 20ms.';

test('extractLedgerLean: ONE call; grounded quotes kept as CLAIMED; fabricated quotes REJECTED deterministically', async () => {
  let calls = 0;
  const agent = async (_p, opts) => {
    calls++;
    assert.equal(opts.schema, LEAN_LEDGER_SCHEMA);
    return { assumptions: [
      { claim_id: 'c-throughput', statement: 'throughput is 150 rps', quote: 'a sustained throughput of 150 requests per second', column: 'throughput' },
      { claim_id: 'c-fake', statement: 'accuracy is 99%', quote: 'we achieve 99 percent accuracy on all benchmarks', column: 'accuracy' },
    ] };
  };
  const { ledger, rejected } = await extractLedgerLean(PAPER, TEXT, ['throughput', 'accuracy'], agent);
  assert.equal(calls, 1, 'one model call per paper — the per-chunk shark court is gone');
  assert.equal(ledger.assumptions.length, 1);
  assert.equal(ledger.assumptions[0].type, 'CLAIMED', 'one pass never self-assigns a higher rung');
  assert.equal(ledger.assumptions[0].claim_id, 'c-throughput');
  assert.equal(rejected.length, 1, 'the fabricated quote died on a string match, not an opinion');
  assert.match(rejected[0].rejection, /FABRICATED-QUOTE/);
});

test('C8: venue whitelist RANKS by default, excludes only opt-in (arXiv survives the snowball)', () => {
  const arxiv = { title: 'x', venue: '', year: 2026 };
  assert.equal(evaluateFilters(arxiv, DEFAULT_VENUE_WHITELIST, {}).excluded, false,
    'empty-venue preprints are no longer all killed as low-venue');
  assert.equal(evaluateFilters(arxiv, DEFAULT_VENUE_WHITELIST, { excludeByVenue: true }).excluded, true,
    'explicit opt-in restores exclusion');
  assert.ok(!DEFAULT_VENUE_WHITELIST.venues.some((v) => /Local Workshop/i.test(v.name)),
    'the test fixture is out of the production default');
});

test('C8: non-TTY + no mock-user auto-approves the gate with a stamp (agents no longer hang forever)', async () => {
  const logs = [];
  const r = await runMixedInitiativeGate([{ title: 'p1' }], [], { interactive: false, log: (m) => logs.push(m) });
  assert.equal(r.approved, true);
  assert.equal(r.autoApproved, true);
  assert.ok(logs.some((l) => /did NOT run/.test(l)), 'the auto-approval is stamped, never silent');
});
