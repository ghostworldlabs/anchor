// test/seed-identity.test.mjs — Wave 6: strict seed-identity validation
// (trio-shared/brownfield-intake/seedIdentity.mjs, resolved via the Wave-1 pinned trio
// home — docs/DECISION-RECEIPT-shared-location.md).
//
// Pins the Wave-6 acceptance: SNAPSHOT-FROZEN precedence (DOI -> PMID -> arXiv-id ->
// normalized-title-hash) and title normalization; strict per-type formats with arXiv
// ADMITTED; malformed identifiers rejected BEFORE any child-process handoff; no silent
// precedence fallthrough for a supplied-but-malformed identifier.

import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import crypto from 'node:crypto';

import { sharedBrownfieldUrl } from './_wave1-trio-resolve.mjs';

let si; // the seedIdentity module under test

before(async () => {
  const indexUrl = await sharedBrownfieldUrl();
  si = await import(new URL('seedIdentity.mjs', indexUrl).href);
});

describe('Wave 6 — seed identity: snapshot-frozen precedence + normalization', () => {
  test('SNAPSHOT: the pinned precedence order is doi, pmid, arxiv, title-hash', () => {
    assert.deepStrictEqual([...si.SEED_ID_PRECEDENCE], ['doi', 'pmid', 'arxiv', 'title-hash']);
  });

  test('SNAPSHOT: the pinned title normalization (NFKC, lowercase, non-alnum runs -> one space, trim)', () => {
    assert.equal(
      si.normalizeTitleForHash('  The  Scaling—Laws:  of LLMs!  '),
      'the scaling laws of llms',
    );
    assert.equal(si.normalizeTitleForHash('Ｄéjà-vu   Networks'), 'déjà vu networks');
    // The title-hash is sha256 hex over EXACTLY that pinned normalized form.
    const expected = crypto
      .createHash('sha256')
      .update('the scaling laws of llms', 'utf8')
      .digest('hex');
    assert.equal(si.titleHashFor('  The  Scaling—Laws:  of LLMs!  '), expected);
  });

  test('normalization is deterministic across identifier spellings: one identity key', () => {
    const forms = ['10.1000/ABC.Def', 'doi:10.1000/abc.def', 'https://doi.org/10.1000/Abc.DEF'];
    const keys = forms.map((id) => {
      const res = si.validateSeed({ idType: 'doi', id, title: 'A Title' });
      assert.equal(res.ok, true, `expected valid doi form "${id}"`);
      return si.seedIdentityKey(res.seed);
    });
    assert.deepStrictEqual(keys, ['doi:10.1000/abc.def', 'doi:10.1000/abc.def', 'doi:10.1000/abc.def']);
  });
});

describe('Wave 6 — seed identity: strict per-type validation', () => {
  test('valid identifiers of every admitted type pass (arXiv admitted, both styles)', () => {
    const valid = [
      { idType: 'doi', id: '10.1000/example.2022.001', title: 'T' },
      { idType: 'pmid', id: '12345678', title: 'T' },
      { idType: 'pmid', id: 'PMID: 345', title: 'T' },
      { idType: 'arxiv', id: '2203.15556', title: 'T' },
      { idType: 'arxiv', id: 'arXiv:2203.15556v2', title: 'T' },
      { idType: 'arxiv', id: 'hep-th/9901001', title: 'T' },
      { idType: 'arxiv', id: 'math.GT/0309136', title: 'T' },
    ];
    for (const seed of valid) {
      const res = si.validateSeed(seed);
      assert.equal(res.ok, true, `expected valid: ${JSON.stringify(seed)} -> ${JSON.stringify(res)}`);
      assert.ok(Object.isFrozen(res.seed), 'validated seeds are frozen');
    }
  });

  test('malformed identifiers are rejected with a named reason', () => {
    const malformed = [
      { idType: 'doi', id: 'not-a-doi', title: 'T' },
      { idType: 'doi', id: '10.1/x', title: 'T' }, // registrant too short
      { idType: 'doi', id: '10.1000/', title: 'T' }, // empty suffix
      { idType: 'pmid', id: '0123', title: 'T' }, // leading zero
      { idType: 'pmid', id: '123456789', title: 'T' }, // too long
      { idType: 'pmid', id: 'abc', title: 'T' },
      { idType: 'arxiv', id: '2203.155', title: 'T' }, // bad new-style number
      { idType: 'arxiv', id: 'hep-th/99010', title: 'T' }, // bad old-style number
      { idType: 'title-hash', id: 'deadbeef', title: 'T' }, // not 64 hex chars
      { idType: 'isbn', id: '978-3-16-148410-0', title: 'T' }, // unknown type
    ];
    for (const seed of malformed) {
      const res = si.validateSeed(seed);
      assert.equal(res.ok, false, `expected rejection: ${JSON.stringify(seed)}`);
      assert.equal(typeof res.rejection.reason, 'string');
      assert.ok(res.rejection.reason.length > 0);
    }
  });

  test('a title-hash identity must equal the hash of its own title — never free-form', () => {
    const wrong = si.validateSeed({
      idType: 'title-hash',
      id: 'a'.repeat(64),
      title: 'Some Title',
    });
    assert.equal(wrong.ok, false);
    const right = si.validateSeed({
      idType: 'title-hash',
      id: si.titleHashFor('Some Title'),
      title: 'Some Title',
    });
    assert.equal(right.ok, true);
  });
});

describe('Wave 6 — seed identity: precedence derivation, no silent fallthrough', () => {
  test('precedence picks the highest supplied identifier: doi > pmid > arxiv > title-hash', () => {
    const all = si.deriveSeedIdentity({
      doi: '10.1000/x.y',
      pmid: '123',
      arxiv: '2203.15556',
      title: 'T',
    });
    assert.equal(all.ok, true);
    assert.equal(all.seed.idType, 'doi');

    const noDoi = si.deriveSeedIdentity({ pmid: '123', arxiv: '2203.15556', title: 'T' });
    assert.equal(noDoi.ok, true);
    assert.equal(noDoi.seed.idType, 'pmid');

    const arxivOnly = si.deriveSeedIdentity({ arxiv: '2203.15556', title: 'T' });
    assert.equal(arxivOnly.ok, true);
    assert.equal(arxivOnly.seed.idType, 'arxiv');

    const titleOnly = si.deriveSeedIdentity({ title: 'Only A Title' });
    assert.equal(titleOnly.ok, true);
    assert.equal(titleOnly.seed.idType, 'title-hash');
    assert.equal(titleOnly.seed.id, si.titleHashFor('Only A Title'));
  });

  test('a SUPPLIED-but-malformed higher-precedence identifier REJECTS the seed — no silent degrade', () => {
    const res = si.deriveSeedIdentity({ doi: 'not-a-doi', pmid: '123', title: 'T' });
    assert.equal(res.ok, false, 'malformed doi must not silently fall through to pmid');
    assert.match(res.rejection.reason, /malformed doi/i);
  });

  test('no identifier and no title fails with a named reason', () => {
    const res = si.deriveSeedIdentity({ title: '   ' });
    assert.equal(res.ok, false);
  });
});

describe('Wave 6 — seed identity: the pre-handoff checkpoint', () => {
  test('acceptance GWT: malformed identifiers are rejected BEFORE handoff; only validated seeds survive', () => {
    const result = si.validateSeedsForHandoff([
      { idType: 'doi', id: '10.1000/good.paper', title: 'Good Paper' },
      { idType: 'doi', id: 'garbage', title: 'Bad Paper' },
      { idType: 'arxiv', id: '2203.15556', title: 'Arxiv Paper' },
    ]);
    assert.equal(result.ok, false);
    assert.equal(result.seeds.length, 2);
    assert.deepStrictEqual(
      result.seeds.map((s) => si.seedIdentityKey(s)),
      ['doi:10.1000/good.paper', 'arxiv:2203.15556'],
    );
    assert.equal(result.rejected.length, 1);
    assert.match(result.rejected[0].reason, /before any child-process handoff/i);
    // The handoff list itself is frozen: nothing can be appended past validation.
    assert.ok(Object.isFrozen(result.seeds));
    for (const s of result.seeds) assert.ok(Object.isFrozen(s));
  });

  test('an all-valid set is ok with zero rejections', () => {
    const result = si.validateSeedsForHandoff([
      { idType: 'pmid', id: '99', title: 'P' },
    ]);
    assert.deepStrictEqual(result.rejected, []);
    assert.equal(result.ok, true);
  });

  test('compareSeedPrecedence orders by the pinned precedence, ties by id — deterministic, never fuzzy', () => {
    const seeds = [
      { idType: 'title-hash', id: 'f'.repeat(64) },
      { idType: 'arxiv', id: '2203.15556' },
      { idType: 'doi', id: '10.1000/b' },
      { idType: 'doi', id: '10.1000/a' },
      { idType: 'pmid', id: '123' },
    ];
    const sorted = [...seeds].sort(si.compareSeedPrecedence);
    assert.deepStrictEqual(
      sorted.map((s) => s.idType),
      ['doi', 'doi', 'pmid', 'arxiv', 'title-hash'],
    );
    assert.deepStrictEqual(sorted[0].id, '10.1000/a');
  });
});
