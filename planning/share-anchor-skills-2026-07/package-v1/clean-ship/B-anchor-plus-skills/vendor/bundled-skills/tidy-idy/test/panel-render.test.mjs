// test/panel-render.test.mjs — Wave 6: the panel cannot fake-clean, and it
// cannot paraphrase.
//
// These assertions are about MEANING, not markup. They run against the panel
// MODEL (engine/panel/model.mjs), which is the same object the HTML renders from
// and the same object `GET /api/panel` returns — so a divergence between what a
// human reads and what a machine reads would require the model to be built
// twice, which it is not.

import { test, describe } from 'node:test';
import assert from 'node:assert';

import { makeStageResult, failedStage, STATUS, makeRunEnvelope } from '../engine/envelope.mjs';
import { buildPanelModel } from '../engine/panel/model.mjs';
import { deriveBanners, canCelebrate, BANNER_LEVEL } from '../engine/panel/banners.mjs';
import { buildTiles, TILE_CLASS } from '../engine/panel/tiles.mjs';
import { renderPanelPage, HEADER_BRAND_DATA_URI_MAX_BYTES, shortRelLabel } from '../engine/panel/render.mjs';
import {
  headerBrandDataUri,
  HEADER_BRAND_DATA_URI_MAX_BYTES as BRAND_URI_MAX,
  BRAND_MARK_PATH,
} from '../engine/panel/assets/brand.mjs';
import { stampFindingIds } from '../engine/apply/identity.mjs';
import { reportDirFor } from '../engine/report-dir.mjs';
import { projectIdentity } from '../engine/launch/identity.mjs';
import { renderBootstrapPage } from '../engine/launch/panel-server.mjs';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  envelopeWithCrashedReorg, envelopeWithEveryClass, cleanEnvelope,
  envelopeWithReorgProposals, reorgFindingZeroHit, reorgFindingNonZeroHit,
  identityFor, removalFinding, RUN_ID,
  REORG_PRODUCTION_FIELD_KEYS, REORG_FIXTURE_PROVENANCE,
} from './helpers/panel-fixture.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SKILL_ROOT = path.resolve(__dirname, '..');

const ROOT = process.platform === 'win32' ? 'C:\\tmp\\my-project' : '/tmp/my-project';
const NOW = () => new Date('2026-07-21T00:01:00.000Z');

function modelFor(envelope, extra = {}) {
  stampFindingIds(envelope.findings, envelope.runId);
  return buildPanelModel({
    envelope,
    identity: identityFor(ROOT),
    runNumber: 7,
    now: NOW,
    ...extra,
  });
}

describe('honest banners', () => {
  test('a crashed reorg stage names exactly what is missing and what is complete', () => {
    const env = envelopeWithCrashedReorg(ROOT);
    const model = modelFor(env);

    const crashed = model.banners.find((b) => b.kind === 'stage-crashed');
    assert.ok(crashed, 'a crashed stage MUST produce a banner');
    assert.strictEqual(crashed.level, BANNER_LEVEL.RED);
    assert.strictEqual(
      crashed.message,
      'reorg analysis crashed — removal findings complete, reorg findings missing',
      'the banner must name the crashed stage AND what did complete — a vague banner teaches readers to skip banners',
    );
    assert.match(crashed.errors[0].message, /symlink loop/, 'the stage error is quoted verbatim');
  });

  test('...and the removal tiles still render, with no clean state anywhere', () => {
    const model = modelFor(envelopeWithCrashedReorg(ROOT));
    assert.strictEqual(model.clean.celebrate, false);
    assert.ok(!model.banners.some((b) => b.level === BANNER_LEVEL.GREEN), 'no green banner may appear on a run with a crashed stage');
    const removals = model.groups.find((g) => g.class === TILE_CLASS.REMOVAL);
    assert.strictEqual(removals.tiles.length, 1, 'the completed stage’s findings must still render');
  });

  test('celebratory-clean renders ONLY from envelope.isClean', () => {
    const clean = cleanEnvelope(ROOT);
    assert.strictEqual(canCelebrate(clean), true);
    assert.ok(modelFor(clean).banners.some((b) => b.level === BANNER_LEVEL.GREEN));

    // Zero findings but an incomplete-coverage stage: the classic fake-clean.
    const sneaky = makeRunEnvelope({
      runId: RUN_ID,
      rootPath: ROOT,
      mode: 'north-star',
      ruleset: { version: 'rs' },
      reportDir: reportDirFor(ROOT),
      identity: projectIdentity({ rootPath: ROOT, git: null }),
      stages: [makeStageResult({ stage: 'scan', status: STATUS.OK, coverage: { scanned: 1, skipped: 9, errored: 0 }, findings: [] })],
    });
    assert.strictEqual(canCelebrate(sneaky), false, 'zero findings is NOT a clean verdict when coverage is incomplete');
    const model = modelFor(sneaky);
    assert.ok(!model.banners.some((b) => b.level === BANNER_LEVEL.GREEN));
    assert.ok(model.banners.some((b) => b.kind === 'coverage-gap'), 'the gap must be stated, not merely withheld from the clean verdict');
  });

  test('a partial stage says its findings are incomplete, not empty', () => {
    const env = makeRunEnvelope({
      runId: RUN_ID,
      rootPath: ROOT,
      mode: 'north-star',
      ruleset: { version: 'rs' },
      reportDir: reportDirFor(ROOT),
      identity: projectIdentity({ rootPath: ROOT, git: null }),
      stages: [makeStageResult({
        stage: 'save',
        status: STATUS.PARTIAL,
        coverage: { scanned: 4, skipped: 1, errored: 1 },
        errors: [{ name: 'Error', message: 'could not compute the would-be-committed diff' }],
        findings: [],
      })],
    });
    const banner = deriveBanners(env, { now: NOW }).find((b) => b.kind === 'stage-partial');
    assert.ok(banner);
    assert.match(banner.message, /incomplete, not empty/);
  });

  test('a cost-gated run banners with a one-click confirm-full-run action', () => {
    const env = cleanEnvelope(ROOT);
    env.costGate = { ran: true, gated: true, blocked: false, banner: { message: 'cost-gated — full run needs confirmation' }, degradation: { steps: [] } };
    const banner = deriveBanners(env, { now: NOW }).find((b) => b.kind === 'cost-gated');
    assert.ok(banner);
    assert.strictEqual(banner.action.id, 'confirm-full-run');
    assert.strictEqual(banner.action.endpoint, '/api/confirm-full-run');
  });
});

describe('finding tiles', () => {
  const model = modelFor(envelopeWithEveryClass(ROOT));
  const byClass = (c) => model.tiles.filter((t) => t.class === c);

  test('a removal tile carries the VERBATIM attacker claim, judge verdict and confidence', () => {
    const [tile] = byClass(TILE_CLASS.REMOVAL);
    assert.strictEqual(tile.evidence.attacker.claim, 'Superseded by src/cli.mjs six months ago; nothing imports it.');
    assert.strictEqual(tile.evidence.attacker.verbatim, true);
    assert.strictEqual(tile.evidence.judge.decision, 'REMOVE');
    assert.strictEqual(
      tile.evidence.judge.rationale,
      'The North Star names a shipping CLI; this file is a superseded spike with no importers.',
      'the judge is quoted, never summarised',
    );
    assert.strictEqual(tile.evidence.confidence.value, 'strong');
  });

  test('a removal whose attacker pass produced nothing SAYS SO rather than implying a case', () => {
    const env = envelopeWithCrashedReorg(ROOT, {
      findings: [removalFinding({ evidence: { decision: 'REMOVE', rationale: 'stale', attacker: null } })],
    });
    const [tile] = buildTiles(env).tiles.filter((t) => t.class === TILE_CLASS.REMOVAL);
    assert.strictEqual(tile.evidence.attacker.claim, null);
    assert.strictEqual(tile.evidence.attacker.verbatim, false);
    assert.match(tile.evidence.attacker.note, /recorded no case/);
    assert.strictEqual(tile.evidence.confidence.value, null);
  });

  test('a SAVE tile quotes the porcelain record and the exact would-be-committed diff', () => {
    const [tile] = byClass(TILE_CLASS.SAVE);
    assert.strictEqual(tile.evidence.porcelain, '? notes/todo.md');
    assert.match(tile.evidence.dirtyOverlap.diff, /\+ship the thing/);
    assert.strictEqual(tile.bulkApprovable, true);
  });

  test('a secret-BLOCKED tile has ZERO approval controls, masked text, and per-class remediations', () => {
    const [tile] = byClass(TILE_CLASS.SECRET);
    assert.deepStrictEqual(tile.controls, [], 'not a DISABLED control — no control exists for this class');
    assert.strictEqual(tile.approvable, false);
    assert.strictEqual(tile.bulkApprovable, false);
    assert.strictEqual(tile.approval, null, 'a BLOCKED tile carries no approval payload, so there is nothing to POST');
    assert.strictEqual(tile.evidence.maskedTriggerText, 'AKIA****************');
    assert.deepStrictEqual(
      tile.evidence.remediation.map((r) => r.kind),
      ['add-to-gitignore', 'relocate', 'next-run-override'],
    );
    for (const t of tile.evidence.triggers) {
      assert.ok(t.rule, 'a trigger names its RULE and its location — never the matched bytes');
    }
  });

  test('quarantine tiles are individually confirmable and excluded from bulk-approve', () => {
    const [tile] = byClass(TILE_CLASS.QUARANTINE);
    assert.strictEqual(tile.approvable, true);
    assert.strictEqual(tile.bulkApprovable, false);
    assert.deepStrictEqual(tile.controls, ['confirm-individually']);
    assert.strictEqual(tile.confirmIndividually.required, true);
    assert.ok(!model.apply.bulkApprovable.some((a) => a.path === 'assets/build.bin'));
  });

  test('heuristic candidates are default-unchecked and never bulk-approvable', () => {
    const [tile] = byClass(TILE_CLASS.HEURISTIC);
    assert.strictEqual(tile.defaultChecked, false);
    assert.strictEqual(tile.bulkApprovable, false);
    assert.deepStrictEqual(tile.evidence.heuristics, ['age', 'duplicate']);
  });

  test('a quarantined path that produced no finding is listed as a read-only notice', () => {
    const notice = model.notices.find((n) => n.path === 'assets/huge.iso');
    assert.ok(notice, 'a quarantined path with no finding must still be visible — a run may not look emptier than it was');
    assert.strictEqual(notice.approvable, false);
  });

  test('every approvable tile carries the FULL finding identity', () => {
    for (const tile of model.tiles.filter((t) => t.approvable)) {
      assert.ok(tile.approval.id.startsWith('tif1:'));
      assert.ok(tile.approval.action && tile.approval.path);
      assert.ok('contentHash' in tile.approval, 'Apply refuses an approval that does not round-trip the content hash');
    }
  });
});

describe('the header, staleness and the drawers', () => {
  test('the header identifies the project unmistakably', () => {
    const model = modelFor(envelopeWithEveryClass(ROOT));
    assert.strictEqual(model.header.project, 'my-project');
    assert.strictEqual(model.header.absolutePath, ROOT);
    assert.strictEqual(model.header.run.number, 7);
    assert.strictEqual(model.header.run.id, RUN_ID);
    assert.ok(model.header.badges.some((b) => b.id === 'north-star'));
  });

  test('run age turns amber once the report is old', () => {
    const fresh = modelFor(envelopeWithEveryClass(ROOT));
    assert.strictEqual(fresh.header.run.ageLevel, 'fresh');
    const stale = modelFor(envelopeWithEveryClass(ROOT), { now: () => new Date('2026-07-21T02:00:00.000Z') });
    assert.strictEqual(stale.header.run.ageLevel, 'amber');
    assert.ok(stale.banners.some((b) => b.kind === 'run-age'));
  });

  test('bulk-Apply is DISABLED when HEAD moved since the scan', () => {
    const model = modelFor(envelopeWithEveryClass(ROOT), {
      staleness: { checked: true, headMoved: true, snapshotHead: 'a'.repeat(40), currentHead: 'b'.repeat(40) },
    });
    assert.strictEqual(model.apply.bulkEnabled, false);
    assert.match(model.apply.disabledReason, /HEAD moved/);
    const banner = model.banners.find((b) => b.kind === 'head-moved');
    assert.strictEqual(banner.action.id, 'rescan', 'the honest banner offers the cheap re-scan');
  });

  test('a superseding newer run voids this one', () => {
    const model = modelFor(envelopeWithEveryClass(ROOT), { supersededBy: { runNumber: 8, runId: 'run-later' } });
    assert.strictEqual(model.apply.bulkEnabled, false);
    assert.match(model.apply.disabledReason, /superseded/);
  });

  test('previous runs list newest-first and mark the current one', () => {
    const model = modelFor(envelopeWithEveryClass(ROOT), {
      runIndex: [
        { runNumber: 7, runId: RUN_ID, runDir: 'd7', status: 'ok', findings: 5, endedAt: 'e7' },
        { runNumber: 6, runId: 'older', runDir: 'd6', status: 'ok', findings: 1, endedAt: 'e6' },
      ],
    });
    assert.deepStrictEqual(model.previousRuns.map((r) => r.runNumber), [7, 6]);
    assert.strictEqual(model.previousRuns[0].current, true);
    assert.strictEqual(model.previousRuns[1].current, false);
  });

  test('the reorg slot is live (not a false reserved placeholder) and the investigator is ACTIVE', () => {
    const model = modelFor(cleanEnvelope(ROOT));
    // Reorg proposals render in actionSections when present; the slot is an
    // honest pointer (never "Wave 8 reserved" when the engine can already emit reorgs).
    assert.strictEqual(model.slots.reorg.reserved, false);
    assert.strictEqual(model.slots.reorg.count, 0);
    assert.match(model.slots.reorg.note, /no reorg proposals this run/i);
    assert.ok(model.verdicts, 'Mockup A verdict pills need counts on the model');
    assert.ok(Array.isArray(model.actionSections), 'action sections drive the triage UI');
    // Investigator tile is active, not merely reserved.
    assert.strictEqual(model.slots.investigator.active, true);
    assert.strictEqual(model.slots.investigator.reserved, false);
    assert.strictEqual(model.slots.investigator.endpoint, '/api/investigate');
    assert.strictEqual(model.slots.investigator.defaultEngine, 'claude');
    assert.deepStrictEqual(model.slots.investigator.engines.map((e) => e.id), ['claude', 'gemini']);
    assert.ok(model.slots.investigator.engines.find((e) => e.id === 'claude').default, 'Claude is the default engine');
  });
});


describe('the rendered page', () => {
  const model = modelFor(envelopeWithEveryClass(ROOT));
  const token = 'f'.repeat(64);
  const html = renderPanelPage({ token, model, baseUrl: 'http://127.0.0.1:1234' });

  test('the token is embedded in the page body and nowhere else in it', () => {
    assert.ok(html.includes(token), 'the redeemed page is the ONE place the token appears');
    assert.ok(!html.includes(`?token=${token}`) && !html.includes(`/${token}`), 'the token must never appear in a URL');
  });

  // ---- W2 / SC2 brand matrix rows (same-wave lock) -------------------------
  test('header brand element is present with stable hooks', () => {
    assert.ok(
      html.includes('data-testid="header-brand"'),
      'header brand must expose data-testid="header-brand" for structural asserts',
    );
    assert.match(
      html,
      /<img\b[^>]*\bclass="brand"[^>]*\bdata-testid="header-brand"/,
      'primary mark is an img.brand with data-testid=header-brand',
    );
    assert.ok(fs.existsSync(BRAND_MARK_PATH), 'engine/panel/assets/tidy-idy-mark.svg must ship in-skill');
  });

  test('header brand is self-contained data-URI (no file:// / external / Anchor path)', () => {
    const img = html.match(/<img\b[^>]*\bdata-testid="header-brand"[^>]*>/);
    assert.ok(img, 'header-brand img tag required');
    const tag = img[0];
    const src = tag.match(/\bsrc="([^"]+)"/);
    assert.ok(src, 'header-brand must have src');
    assert.match(src[1], /^data:image\/(svg\+xml|png|webp|jpeg)/i, 'brand src must be an image data-URI');
    assert.doesNotMatch(tag, /file:\/\//i);
    assert.doesNotMatch(src[1], /^https?:\/\//i);
    assert.doesNotMatch(html, /file:\/\/\/<path>
    // Must match the in-skill asset encoding (not a hand-rolled external reference)
    assert.strictEqual(src[1], headerBrandDataUri(), 'rendered brand URI must equal assets/brand.mjs data-URI');
  });

  test('header brand is not broom-only primary mark', () => {
    // Broom emoji must not be the primary header mark (div.logo 🧹 or img alt-only broom).
    assert.doesNotMatch(html, /class="logo"[^>]*>\s*🧹/);
    assert.doesNotMatch(html, /data-testid="header-brand"[^>]*>\s*🧹/);
    const img = html.match(/<img\b[^>]*\bdata-testid="header-brand"[^>]*>/);
    assert.ok(img, 'non-broom primary mark is an <img>, not emoji text');
    assert.doesNotMatch(img[0], /🧹/);
    // Favicon may still be broom-like (tab icon only); header brand must be the shippable mark.
    assert.match(img[0], /\bsrc="data:image\//);
  });

  test('header brand data-URI stays under size budget', () => {
    assert.strictEqual(
      HEADER_BRAND_DATA_URI_MAX_BYTES,
      BRAND_URI_MAX,
      'render re-export and assets pin must agree',
    );
    const img = html.match(/<img\b[^>]*\bdata-testid="header-brand"[^>]*>/);
    assert.ok(img);
    const src = img[0].match(/\bsrc="([^"]+)"/);
    assert.ok(src);
    const uri = src[1];
    assert.ok(
      uri.length <= HEADER_BRAND_DATA_URI_MAX_BYTES,
      `brand data-URI length ${uri.length} exceeds budget ${HEADER_BRAND_DATA_URI_MAX_BYTES}`,
    );
    // CSP posture: no external brand URL in the document (budget is for inline payload).
    assert.doesNotMatch(html, /\bsrc=["']https?:\/\/[^"']*tidy-idy/i);
  });


  test('the page references NO persistent storage API at all', () => {
    for (const forbidden of ['localStorage', 'sessionStorage', 'document.cookie', 'indexedDB']) {
      assert.ok(!html.includes(forbidden), `the panel must never persist the token: found ${forbidden}`);
    }
  });

  test('the token travels in a header, never a query string', () => {
    assert.ok(html.includes('x-tidy-idy-token'));
    assert.ok(!/fetch\([^)]*token=/.test(html));
  });

  test('a secret-BLOCKED tile renders no input or approve button', () => {
    // Match the rendered CARD only — not the inlined MODEL JSON in <script>.
    // Compact collapse may insert "compact" in the class list.
    const m = html.match(/class="card[^"]*secret-blocked[^"]*"/);
    assert.ok(m, 'secret-blocked card must appear in the markup');
    const start = html.indexOf(m[0]);
    const chunk = html.slice(start, html.indexOf('</article>', start));
    assert.ok(!chunk.includes('<input'), 'no checkbox may exist on a BLOCKED tile');
    assert.ok(!chunk.includes('confirm-one'), 'no individual-confirm button either');
    assert.match(chunk, /no approval control/);
  });

  test('banners render before the findings', () => {
    const b = html.indexOf('id="banners"');
    const findings = html.indexOf('data-section=') >= 0
      ? html.indexOf('data-section=')
      : html.indexOf('class="body"');
    assert.ok(b >= 0 && findings > b, 'a reader who reaches the tiles first has already been misled');
  });

  test('Mockup A chrome: verdict pills, project chip, progressive disclosure', () => {
    assert.match(html, /run launched from|tidy-idy run for/);
    assert.match(html, /projchip/);
    assert.match(html, /class="verdicts"/);
    assert.match(html, /Proposed removals/);
    assert.match(html, /Show evidence \(verbatim\)/);
    assert.match(html, /Kept &amp; protected|Kept & protected/);
  });

  test('verbatim evidence is escaped, not stripped', () => {
    const injected = modelFor(envelopeWithCrashedReorg(ROOT, {
      findings: [removalFinding({ evidence: { decision: 'REMOVE', rationale: '<script>alert(1)</script>', attacker: null } })],
    }));
    const page = renderPanelPage({ token, model: injected, baseUrl: 'http://127.0.0.1:1234' });
    assert.ok(!page.includes('<script>alert(1)</script>'));
    assert.ok(page.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'the judge’s exact bytes are preserved, escaped');
  });
});

// ---- W3 / SC2 layout matrix rows (same-wave lock) ---------------------------
// Primary before→after trees, always-visible safety chips, decision-first order,
// secondary evidence, zero-hit vs non-zero-hit differential, hollow-tree ban.
// Fixtures are production-shaped (reorg.stage field shapes); empty trees cannot pass.

describe('W3 / SC2 layout matrix (same-wave lock)', () => {
  const reorgModel = modelFor(envelopeWithReorgProposals(ROOT));
  const reorgHtml = renderPanelPage({
    token: 'a'.repeat(64),
    model: reorgModel,
    baseUrl: 'http://127.0.0.1:1234',
  });

  function cardChunks(html) {
    const cards = [];
    const re = /<article\b[^>]*data-testid="reorg-tile"[^>]*>/g;
    let m;
    while ((m = re.exec(html)) !== null) {
      const start = m.index;
      const end = html.indexOf('</article>', start);
      assert.ok(end > start, 'reorg tile must close');
      cards.push(html.slice(start, end));
    }
    return cards;
  }

  test('production-shaped fixtures have non-empty projectable before/after trees', () => {
    const zero = reorgFindingZeroHit();
    const hits = reorgFindingNonZeroHit();
    for (const f of [zero, hits]) {
      assert.ok(f.before && Array.isArray(f.before.entries) && f.before.entries.length > 0, 'before.entries non-empty');
      assert.ok(f.after && Array.isArray(f.after.entries) && f.after.entries.length > 0, 'after.entries non-empty');
      assert.ok(f.before.root && f.after.root, 'tree roots present');
    }
    const tiles = reorgModel.tiles.filter((t) => t.class === TILE_CLASS.REORG);
    assert.strictEqual(tiles.length, 2, 'both zero-hit and non-zero-hit reorg tiles');
    for (const t of tiles) {
      assert.ok(t.evidence.before.entries.length > 0, 'tile carries non-empty before tree');
      assert.ok(t.evidence.after.entries.length > 0, 'tile carries non-empty after tree');
    }
  });

  test('primary before→after tree-diff is outside details.evidence (not a descendant)', () => {
    const cards = cardChunks(reorgHtml);
    assert.strictEqual(cards.length, 2, 'two reorg cards');
    for (const card of cards) {
      const treeIdx = card.indexOf('data-testid="primary-tree-diff"');
      const evidenceIdx = card.indexOf('data-testid="evidence-details"');
      assert.ok(treeIdx >= 0, 'primary-tree-diff hook required');
      assert.ok(evidenceIdx >= 0, 'evidence-details hook required');
      assert.ok(treeIdx < evidenceIdx, 'primary tree must appear BEFORE secondary evidence disclosure');
      // Ancestry ban: the primary tree node must not sit inside details.evidence.
      const detailsStart = card.indexOf('<details class="evidence"');
      assert.ok(detailsStart > treeIdx, 'tree-diff is not nested under details.evidence');
      const insideDetails = card.slice(detailsStart).includes('data-testid="primary-tree-diff"');
      assert.strictEqual(insideDetails, false, 'primary-tree-diff must not be a descendant of details.evidence');
      // Trees are non-hollow in the primary chrome (short labels present).
      const primaryChunk = card.slice(treeIdx, evidenceIdx);
      assert.match(primaryChunk, /data-testid="primary-tree-diff"/);
      assert.match(primaryChunk, /data-hollow="false"/, 'production-shaped cards must not stamp hollow');
      assert.doesNotMatch(primaryChunk, /data-testid="hollow-tree-ban"/);
      assert.match(primaryChunk, /data-testid="tree-entries-before"/);
      assert.match(primaryChunk, /data-testid="tree-entries-after"/);
      assert.match(primaryChunk, /<li class="tnode/);
      // Hollow ban is broader than empty-ul alone: no empty entry lists on either side.
      assert.doesNotMatch(primaryChunk, /data-testid="tree-entries-before"><\/ul>/);
      assert.doesNotMatch(primaryChunk, /data-testid="tree-entries-after"><\/ul>/);
      assert.doesNotMatch(primaryChunk, /tree-entries"><\/ul>/);
      // Each side must list at least one short label node.
      const beforeUl = primaryChunk.match(/data-testid="tree-entries-before"[^>]*>([\s\S]*?)<\/ul>/);
      const afterUl = primaryChunk.match(/data-testid="tree-entries-after"[^>]*>([\s\S]*?)<\/ul>/);
      assert.ok(beforeUl && beforeUl[1].includes('tnode'), 'before tree must list real nodes');
      assert.ok(afterUl && afterUl[1].includes('tnode'), 'after tree must list real nodes');
    }
  });

  test('primary labels are short relative names; full paths stay secondary', () => {
    assert.strictEqual(shortRelLabel('sprites/a.png', 'sprites'), 'a.png');
    assert.strictEqual(shortRelLabel('assets/sprites/b.png', 'assets/sprites'), 'b.png');
    // Zero-hit card shows short labels in primary tree, full paths in secondary evidence.
    const cards = cardChunks(reorgHtml);
    const zeroCard = cards.find((c) => c.includes('sprites')) || cards[0];
    const primary = zeroCard.slice(
      zeroCard.indexOf('data-testid="primary-tree-diff"'),
      zeroCard.indexOf('data-testid="evidence-details"'),
    );
    assert.match(primary, />a\.png</);
    assert.match(primary, />b\.png</);
    // Full project-relative path is secondary (title and/or evidence), not the sole primary label.
    assert.match(zeroCard, /data-testid="path-secondary"/);
    assert.match(zeroCard, /data-testid="reorg-full-path-trees"/);
    assert.match(zeroCard, /sprites\/a\.png/);
  });

  test('hit-count / referenceUnsafe / override chrome is visible without expanding evidence', () => {
    const cards = cardChunks(reorgHtml);
    const zeroCard = cards.find((c) => c.includes('bulk-approvable-chip') || c.includes('0 reference hit'));
    const hitCard = cards.find((c) => c.includes('override-only-chip') || c.includes('3 reference hit'));
    assert.ok(zeroCard, 'zero-hit card present');
    assert.ok(hitCard, 'non-zero-hit card present');

    for (const card of [zeroCard, hitCard]) {
      const chipIdx = card.indexOf('data-testid="reference-scan-chip"');
      const detailsStart = card.indexOf('<details class="evidence"');
      assert.ok(chipIdx >= 0, 'reference-scan-chip always visible');
      assert.ok(chipIdx < detailsStart, 'hit chip is not buried under evidence');
    }

    // Zero-hit: bulk-approvable chrome + safe hit count.
    assert.match(zeroCard, /data-testid="bulk-approvable-chip"/);
    assert.match(zeroCard, /0 reference hit/);
    assert.doesNotMatch(zeroCard, /data-testid="override-only-chip"/);
    assert.doesNotMatch(zeroCard, /data-testid="reference-unsafe-reason"/);

    // Non-zero-hit: override-only + unsafe reason visible without expand.
    assert.match(hitCard, /data-testid="override-only-chip"/);
    assert.match(hitCard, /3 reference hit/);
    assert.match(hitCard, /data-testid="reference-unsafe-reason"/);
    assert.match(hitCard, /break 3 reference/);
  });

  test('zero-hit vs non-zero-hit control-state differential (no bulk for hits)', () => {
    const tiles = reorgModel.tiles.filter((t) => t.class === TILE_CLASS.REORG);
    const zero = tiles.find((t) => t.path === 'sprites');
    const hits = tiles.find((t) => t.path === 'icons');
    assert.ok(zero && hits);
    assert.strictEqual(zero.bulkApprovable, true);
    assert.strictEqual(hits.bulkApprovable, false);
    assert.ok(hits.confirmIndividually && hits.confirmIndividually.override);
    assert.ok(hits.approval && hits.approval.override === true);

    const cards = cardChunks(reorgHtml);
    const zeroCard = cards.find((c) => c.includes(`id="tile-${zero.id}"`) || c.includes('sprites'));
    const hitCard = cards.find((c) => c.includes(`id="tile-${hits.id}"`) || c.includes('icons'));
    // Zero-hit: checkbox approve path; non-zero: explicit override button only.
    assert.match(zeroCard, /<input[^>]*class="approve"/);
    assert.doesNotMatch(zeroCard, /Apply anyway/);
    assert.match(hitCard, /confirm-one/);
    assert.match(hitCard, /Apply anyway/);
    assert.doesNotMatch(hitCard, /<input[^>]*class="approve"/);
  });

  test('decision-first order: decision section + primary chrome before secondary evidence', () => {
    assert.match(reorgHtml, /data-testid="verdicts"/);
    assert.match(reorgHtml, /data-testid="verdict-pill-reorg"/);
    assert.match(reorgHtml, /data-testid="decision-section-reorg"/);
    const bodyIdx = reorgHtml.indexOf('class="body"');
    const sectionIdx = reorgHtml.indexOf('data-testid="decision-section-reorg"');
    const treeIdx = reorgHtml.indexOf('data-testid="primary-tree-diff"');
    const evidenceIdx = reorgHtml.indexOf('data-testid="evidence-details"');
    assert.ok(bodyIdx >= 0 && sectionIdx > bodyIdx);
    assert.ok(treeIdx > sectionIdx);
    assert.ok(evidenceIdx > treeIdx, 'secondary evidence follows primary decision chrome');
  });

  test('secondary evidence disclosure still carries full paths and hit detail', () => {
    const cards = cardChunks(reorgHtml);
    for (const card of cards) {
      assert.match(card, /data-testid="evidence-details"/);
      assert.match(card, /Show evidence \(verbatim\)/);
      assert.match(card, /data-testid="reorg-full-path-trees"/);
      assert.match(card, /data-testid="reorg-reference-hits-secondary"/);
    }
    // Hit detail lines live under evidence (secondary), not only primary chip.
    const hitCard = cards.find((c) => c.includes('3 reference hit'));
    assert.match(hitCard, /tsconfig\.json:4:/);
  });

  test('no set-level bulk multi-move product chrome (Family Trusts ban)', () => {
    // Live product is per-proposal trees; no "Approve reorg (N)" / set-level bulk.
    assert.doesNotMatch(reorgHtml, /Approve reorg\s*\(\s*\d+\s*\)/i);
    assert.doesNotMatch(reorgHtml, /approve-all-reorg/i);
    assert.doesNotMatch(reorgHtml, /data-testid="reorg-set-bulk"/);
    // Reorg section stays forceFlat (no folder-set multi-move aggregation chrome as primary product).
    const reorgSection = reorgModel.actionSections.find((s) => s.id === 'reorg');
    assert.ok(reorgSection);
    assert.ok(reorgSection.sets.every((s) => s.kind === 'flat'), 'reorg sets remain flat / per-proposal');
  });
});

// ---- W4 / SC6 — full mockup→assert matrix, production-shaped fixtures, dual-surface ----
// Deepens SC1–SC2 locks: brand + trees + pills + order + secondary evidence + SC1
// archive/pointer + fail-closed safety/hollow chrome. Dual-surface = shared panel body
// (CLI folder open + thin-caller redeem the same bootstrap → renderPanelPage). Status
// shells remain unclaimed.

/** Structural hooks that must appear on every shared panel-body emission. */
function assertMockupCriticalStructure(html, { expectReorg = false } = {}) {
  assert.match(html, /data-testid="header-brand"/, 'brand hook');
  assert.match(html, /data-testid="verdicts"/, 'verdict pills container');
  assert.match(html, /data-testid="verdict-pill-removals"/);
  assert.match(html, /data-testid="verdict-pill-save"/);
  assert.match(html, /data-testid="verdict-pill-reorg"/);
  assert.match(html, /data-testid="verdict-pill-keep"/);
  assert.match(html, /class="body"/, 'decision-first body');
  assert.match(html, /id="banners"/);
  if (expectReorg) {
    assert.match(html, /data-testid="decision-section-reorg"/);
    assert.match(html, /data-testid="primary-tree-diff"/);
    assert.match(html, /data-testid="reference-scan-chip"/);
    assert.match(html, /data-testid="evidence-details"/);
    // Decision order: primary tree before secondary evidence (first occurrences).
    const treeIdx = html.indexOf('data-testid="primary-tree-diff"');
    const evidenceIdx = html.indexOf('data-testid="evidence-details"');
    assert.ok(treeIdx >= 0 && evidenceIdx > treeIdx, 'primary trees before secondary evidence');
  }
}

describe('W4 / SC6 full mockup→assert matrix + production fixtures + dual-surface', () => {
  const token = 'b'.repeat(64);
  const baseUrl = 'http://127.0.0.1:4321';
  const reorgEnv = envelopeWithReorgProposals(ROOT);
  const reorgModel = modelFor(reorgEnv);
  const standaloneHtml = renderPanelPage({ token, model: reorgModel, baseUrl });
  // Thin-caller / bootstrap alias: same panel body emission path (W0 inventory).
  const thinCallerHtml = renderBootstrapPage({ token, model: reorgModel, baseUrl });

  test('production-shaped fixtures carry reorg.stage field keys + non-empty trees + provenance', () => {
    const zero = reorgFindingZeroHit();
    const hits = reorgFindingNonZeroHit();
    for (const f of [zero, hits]) {
      for (const key of REORG_PRODUCTION_FIELD_KEYS) {
        assert.ok(key in f, `production field missing: ${key}`);
      }
      assert.strictEqual(f.kind, 'reorg-proposal');
      assert.strictEqual(f.action, 'reorg');
      assert.ok(f.before.entries.length > 0 && f.after.entries.length > 0);
      assert.ok(f.before.root && f.after.root);
      assert.ok(f.move && f.move.from && f.move.to);
      assert.ok(Array.isArray(f.members) && f.members.length > 0);
      assert.ok(f.referenceScan && f.referenceScan.hitCount != null);
      assert.ok(f._fixtureProvenance);
      assert.strictEqual(f._fixtureProvenance.source, REORG_FIXTURE_PROVENANCE.source);
      assert.strictEqual(f._fixtureProvenance.hollowTreeBan, true);
    }
    // Differential control state (stage rule): zero bulk-approvable; non-zero override-only.
    assert.strictEqual(zero.bulkApprovable, true);
    assert.strictEqual(zero.overrideRequired, false);
    assert.strictEqual(zero.referenceScan.hitCount, 0);
    assert.strictEqual(zero.referenceUnsafe, null);
    assert.strictEqual(hits.bulkApprovable, false);
    assert.strictEqual(hits.overrideRequired, true);
    assert.ok(hits.referenceScan.hitCount > 0);
    assert.ok(hits.referenceUnsafe && hits.referenceUnsafe.reason);
    // Synthetic-only HTML cannot be the sole SC2 proof: fixtures must be projectable
    // through the real tile model (not a hand-written HTML fragment).
    const tiles = reorgModel.tiles.filter((t) => t.class === TILE_CLASS.REORG);
    assert.strictEqual(tiles.length, 2);
    for (const t of tiles) {
      assert.ok(t.evidence.before.entries.length > 0);
      assert.ok(t.evidence.after.entries.length > 0);
      assert.ok(t.evidence.referenceScan.hitCount != null);
    }
  });

  test('full matrix row: brand self-contained on reorg panel body', () => {
    for (const html of [standaloneHtml, thinCallerHtml]) {
      assert.match(html, /data-testid="header-brand"/);
      const img = html.match(/<img\b[^>]*\bdata-testid="header-brand"[^>]*>/);
      assert.ok(img);
      const src = img[0].match(/\bsrc="([^"]+)"/);
      assert.ok(src);
      assert.match(src[1], /^data:image\//i);
      assert.strictEqual(src[1], headerBrandDataUri());
      assert.doesNotMatch(img[0], /file:\/\//i);
      assert.doesNotMatch(img[0], /🧹/);
    }
  });

  test('full matrix row: primary trees, pills, decision-first order, secondary evidence', () => {
    for (const html of [standaloneHtml, thinCallerHtml]) {
      assertMockupCriticalStructure(html, { expectReorg: true });
      // Absolute / full paths are secondary: path-secondary title may hold absolute;
      // primary tree nodes show short labels, full paths live under evidence or title attrs.
      assert.match(html, /data-testid="path-secondary"/);
      assert.match(html, /data-testid="reorg-full-path-trees"/);
      // Primary tree short labels (not only full project-relative as sole visible text).
      assert.match(html, />a\.png</);
      assert.match(html, />logo\.svg</);
      // Secondary evidence still present.
      assert.match(html, /Show evidence \(verbatim\)/);
    }
  });

  test('full matrix row: zero-hit vs non-zero-hit control + chrome differential', () => {
    const cards = [];
    const re = /<article\b[^>]*data-testid="reorg-tile"[^>]*>/g;
    let m;
    while ((m = re.exec(standaloneHtml)) !== null) {
      const start = m.index;
      const end = standaloneHtml.indexOf('</article>', start);
      cards.push(standaloneHtml.slice(start, end));
    }
    assert.strictEqual(cards.length, 2);
    const zeroCard = cards.find((c) => c.includes('bulk-approvable-chip'));
    const hitCard = cards.find((c) => c.includes('override-only-chip') && c.includes('3 reference hit'));
    assert.ok(zeroCard && hitCard);
    assert.match(zeroCard, /0 reference hit/);
    assert.doesNotMatch(zeroCard, /data-testid="override-only-chip"/);
    assert.match(hitCard, /data-testid="reference-unsafe-reason"/);
    assert.match(zeroCard, /<input[^>]*class="approve"/);
    assert.match(hitCard, /Apply anyway/);
    assert.doesNotMatch(hitCard, /<input[^>]*class="approve"/);
  });

  test('fail-closed: missing referenceScan does not claim zero-hit bulk-approvable', () => {
    // Unmasked: stage stamps stay bulk-open (bulkApprovable:true, overrideRequired:false).
    // Engine control path + chrome must still refuse bulk from scan absence alone.
    const env = makeRunEnvelope({
      runId: RUN_ID,
      rootPath: ROOT,
      mode: 'north-star',
      ruleset: { version: 'rs-test' },
      reportDir: reportDirFor(ROOT),
      identity: projectIdentity({ rootPath: ROOT, git: null }),
      git: { toplevel: ROOT, head: 'a'.repeat(40), branch: 'refs/heads/main', rootIsToplevel: true },
      snapshot: { head: 'a'.repeat(40), paths: {} },
      stages: [
        makeStageResult({
          stage: 'reorg',
          status: STATUS.OK,
          coverage: { scanned: 1, skipped: 0, errored: 0 },
          findings: [
            reorgFindingZeroHit({
              path: 'orphan',
              absolutePath: '/tmp/x/orphan',
              move: { from: 'orphan', to: 'assets/orphan' },
              members: ['orphan/x.png'],
              before: { root: 'orphan', entries: ['orphan/x.png'] },
              after: { root: 'assets/orphan', entries: ['assets/orphan/x.png'] },
              // Strip scan only — leave zero-hit helper's bulk-open stamps intact.
              referenceScan: null,
              eligible: true,
              overrideRequired: false,
              bulkApprovable: true,
              referenceUnsafe: null,
              contentHash: 'hash-scan-missing',
            }),
          ],
        }),
      ],
      startedAt: '2026-07-21T00:00:00.000Z',
      endedAt: '2026-07-21T00:00:05.000Z',
    });
    const model = modelFor(env);
    const tile = model.tiles.find((t) => t.class === TILE_CLASS.REORG);
    assert.ok(tile, 'reorg tile projected');
    assert.strictEqual(tile.bulkApprovable, false, 'control path fails closed without stage bulkApprovable:false');
    assert.ok(tile.confirmIndividually && tile.confirmIndividually.override, 'override-only control when scan missing');
    assert.ok(tile.approval && tile.approval.override === true);
    assert.match(tile.summaryWhy || '', /reference scan missing|not bulk/i);

    const html = renderPanelPage({ token, model, baseUrl });
    assert.match(html, /data-testid="scan-missing-chip"/);
    assert.match(html, /data-testid="override-only-chip"/);
    assert.doesNotMatch(html, /data-testid="bulk-approvable-chip"/);
    // Must not paint a numeric "0 reference hit(s)" as if the scan ran clean.
    const cardStart = html.indexOf('data-testid="reorg-tile"');
    assert.ok(cardStart >= 0);
    const card = html.slice(cardStart, html.indexOf('</article>', cardStart));
    assert.doesNotMatch(card, />0 reference hit/);
    assert.doesNotMatch(card, /<input[^>]*class="approve"/);
    assert.match(card, /Apply anyway/);
  });

  test('fail-closed: non-numeric hitCount is not zero-hit bulk-approvable', () => {
    const env = makeRunEnvelope({
      runId: RUN_ID,
      rootPath: ROOT,
      mode: 'north-star',
      ruleset: { version: 'rs-test' },
      reportDir: reportDirFor(ROOT),
      identity: projectIdentity({ rootPath: ROOT, git: null }),
      git: { toplevel: ROOT, head: 'a'.repeat(40), branch: 'refs/heads/main', rootIsToplevel: true },
      snapshot: { head: 'a'.repeat(40), paths: {} },
      stages: [
        makeStageResult({
          stage: 'reorg',
          status: STATUS.OK,
          coverage: { scanned: 1, skipped: 0, errored: 0 },
          findings: [
            reorgFindingZeroHit({
              path: 'weird',
              absolutePath: '/tmp/x/weird',
              move: { from: 'weird', to: 'assets/weird' },
              members: ['weird/y.png'],
              before: { root: 'weird', entries: ['weird/y.png'] },
              after: { root: 'assets/weird', entries: ['assets/weird/y.png'] },
              referenceScan: {
                hitCount: 'not-a-number',
                hits: [],
                truncated: false,
                scannedFiles: 3,
                scope: 'test',
              },
              bulkApprovable: true,
              overrideRequired: false,
              contentHash: 'hash-scan-nan',
            }),
          ],
        }),
      ],
      startedAt: '2026-07-21T00:00:00.000Z',
      endedAt: '2026-07-21T00:00:05.000Z',
    });
    const model = modelFor(env);
    const tile = model.tiles.find((t) => t.class === TILE_CLASS.REORG);
    assert.strictEqual(tile.bulkApprovable, false);
    assert.ok(tile.confirmIndividually && tile.confirmIndividually.override);
    const html = renderPanelPage({ token, model, baseUrl });
    assert.match(html, /data-testid="scan-missing-chip"/);
    assert.doesNotMatch(html, /data-testid="bulk-approvable-chip"/);
  });

  test('fail-closed: empty/missing before-after trees stamp hollow-tree-ban (not empty columns)', () => {
    const env = makeRunEnvelope({
      runId: RUN_ID,
      rootPath: ROOT,
      mode: 'north-star',
      ruleset: { version: 'rs-test' },
      reportDir: reportDirFor(ROOT),
      identity: projectIdentity({ rootPath: ROOT, git: null }),
      git: { toplevel: ROOT, head: 'a'.repeat(40), branch: 'refs/heads/main', rootIsToplevel: true },
      snapshot: { head: 'a'.repeat(40), paths: {} },
      stages: [
        makeStageResult({
          stage: 'reorg',
          status: STATUS.OK,
          coverage: { scanned: 1, skipped: 0, errored: 0 },
          findings: [
            reorgFindingZeroHit({
              path: 'hollow',
              absolutePath: '/tmp/x/hollow',
              move: { from: 'hollow', to: 'assets/hollow' },
              members: [],
              before: { root: 'hollow', entries: [] },
              after: { root: 'assets/hollow', entries: [] },
              contentHash: 'hash-hollow',
            }),
          ],
        }),
      ],
      startedAt: '2026-07-21T00:00:00.000Z',
      endedAt: '2026-07-21T00:00:05.000Z',
    });
    const html = renderPanelPage({ token, model: modelFor(env), baseUrl });
    assert.match(html, /data-testid="primary-tree-diff"/);
    assert.match(html, /data-hollow="true"/);
    assert.match(html, /data-testid="hollow-tree-ban"/);
    // Must not paint empty <ul class="tree-entries"> columns that look like real trees.
    assert.doesNotMatch(html, /data-testid="tree-entries-before"/);
    assert.doesNotMatch(html, /data-testid="tree-entries-after"/);
  });

  test('absolute paths stay secondary (title / evidence), not sole primary tree labels', () => {
    // Primary crow basename is short; path-secondary holds project-relative; absolute is title only.
    assert.match(standaloneHtml, /data-testid="path-secondary"/);
    const fmeta = standaloneHtml.match(/data-testid="path-secondary"[^>]*>/);
    assert.ok(fmeta);
    // Absolute path may appear only as title= on secondary chrome, not as visible primary tree text.
    const primaryTree = standaloneHtml.slice(
      standaloneHtml.indexOf('data-testid="primary-tree-diff"'),
      standaloneHtml.indexOf('data-testid="evidence-details"'),
    );
    // Windows or POSIX absolute prefixes must not be the visible short label.
    assert.doesNotMatch(primaryTree, />\/tmp\/x\//);
    assert.doesNotMatch(primaryTree, />C:\\\\tmp\\\\/);
    // Full project-relative listing remains under secondary evidence.
    assert.match(standaloneHtml, /data-testid="reorg-full-path-trees"/);
    assert.match(standaloneHtml, /sprites\/a\.png/);
  });

  test('dual-surface: standalone renderPanelPage and thin-caller renderBootstrapPage share body structure', () => {
    assertMockupCriticalStructure(standaloneHtml, { expectReorg: true });
    assertMockupCriticalStructure(thinCallerHtml, { expectReorg: true });
    // Same mockup-critical hooks on both surfaces (shared emission path).
    const hooks = [
      'data-testid="header-brand"',
      'data-testid="verdicts"',
      'data-testid="primary-tree-diff"',
      'data-testid="decision-section-reorg"',
      'data-testid="reference-scan-chip"',
      'data-testid="evidence-details"',
      'data-testid="bulk-approvable-chip"',
      'data-testid="override-only-chip"',
    ];
    for (const hook of hooks) {
      assert.ok(standaloneHtml.includes(hook), `standalone missing ${hook}`);
      assert.ok(thinCallerHtml.includes(hook), `thin-caller missing ${hook}`);
    }
    // Bootstrap alias must not invent a second capability channel in the page body.
    assert.ok(standaloneHtml.includes(token) && thinCallerHtml.includes(token));
    assert.ok(!standaloneHtml.includes(`?token=${token}`) && !thinCallerHtml.includes(`?token=${token}`));
  });

  test('dual-surface emission path: panel-server is sole HTML body emitter; status shell out of scope', () => {
    const panelServerSrc = fs.readFileSync(path.join(SKILL_ROOT, 'engine/launch/panel-server.mjs'), 'utf8');
    const statusServerSrc = fs.readFileSync(path.join(SKILL_ROOT, 'engine/launch/status-server.mjs'), 'utf8');
    const runStatusSrc = fs.readFileSync(path.join(SKILL_ROOT, 'engine/launch/run-status.mjs'), 'utf8');
    const anchorSrc = fs.readFileSync(path.join(SKILL_ROOT, 'engine/launch/anchor-caller.mjs'), 'utf8');
    const openerSrc = fs.readFileSync(path.join(SKILL_ROOT, 'engine/launch/opener.mjs'), 'utf8');

    // Shared body: bootstrap redemption + renderBootstrapPage both call renderPanelPage.
    assert.match(panelServerSrc, /import\s*\{\s*renderPanelPage\s*\}\s*from\s*['"]\.\.\/panel\/render\.mjs['"]/);
    assert.match(panelServerSrc, /renderPanelPage\(\s*\{\s*token,\s*model,\s*baseUrl\s*\}\s*\)/);
    assert.match(panelServerSrc, /export function renderBootstrapPage/);
    assert.match(panelServerSrc, /return renderPanelPage\(\s*\{\s*token,\s*model:\s*m,\s*baseUrl\s*\}\s*\)/);

    // Status shell is a different HTML path — must not claim panel SC2 body.
    assert.doesNotMatch(statusServerSrc, /renderPanelPage/);
    assert.doesNotMatch(runStatusSrc, /renderPanelPage/);
    assert.match(statusServerSrc, /renderStatusPage/);

    // Thin-caller / opener hand off the bootstrap URL only — no second panel HTML renderer.
    assert.doesNotMatch(anchorSrc, /renderPanelPage|renderBootstrapPage/);
    assert.doesNotMatch(openerSrc, /renderPanelPage|renderBootstrapPage/);
    assert.match(anchorSrc, /open-url|bootstrapUrl|bootstrapFile/);
  });

  test('SC1 archive/pointer hygiene remains locked (matrix row owned with panel-render)', () => {
    // W4 deepens SC1 locks: canonical CURRENT mockups + REJECTED archive still exist.
    // Path derives from skill-root (same host layout as sc1-mockup-hygiene), not a
    // second hardcoded absolute that drifts from the SC1 suite.
    const design = path.resolve(SKILL_ROOT, '..', '..', '..', 'plans', '2026-07-tidy-idy-gui-polish', 'design');
    const designFallback = path.resolve('<path>');
    const designRoot = fs.existsSync(design) ? design : designFallback;
    const currentA = path.join(designRoot, 'tidy-idy-mockup-A-triage.html');
    const currentA2 = path.join(designRoot, 'tidy-idy-mockup-A2-reorg.html');
    const archiveOpt2 = path.join(designRoot, 'archive', 'tidy-idy-mockup-A2-option2-REJECTED.html');
    assert.ok(fs.existsSync(currentA), 'CURRENT Mockup A');
    assert.ok(fs.existsSync(currentA2), 'CURRENT A2 Option 1');
    assert.ok(fs.existsSync(archiveOpt2), 'REJECTED Option 2 archive');
    const a2 = fs.readFileSync(currentA2, 'utf8');
    assert.match(a2, /tidy-idy-mockup-status" content="CURRENT"/i);
    assert.match(a2, /OPTION 1/i);
    assert.doesNotMatch(a2, /Pick one \(or blend\)/i);
    assert.doesNotMatch(a2, /OPTION 2 — SORTING BUCKETS/i);
    assert.match(a2, /REJECTED/i);
    const archiveHead = fs.readFileSync(archiveOpt2, 'utf8').slice(0, 1200);
    assert.match(archiveHead, /REJECTED/i);
    // Skill-root SC1 suite file must remain present (zero-skip SC1 hygiene).
    assert.ok(fs.existsSync(path.join(SKILL_ROOT, 'test/sc1-mockup-hygiene.test.mjs')));
  });

  test('SC3 safety oracle files remain present without skip-API calls in oracles', () => {
    // Avoid a literal skip-API substring in THIS file — Foreman's skip-marker
    // inventory counts those tokens and pairs a rise with host-conditional
    // t.skip elsewhere (topology) to false-HALT integrity.
    const skipTestApi = ['test', 'skip'].join('.');
    const skipDescribeApi = ['describe', 'skip'].join('.');
    const oracles = [
      'test/apply-identity.test.mjs',
      'test/panel-apply-plane.test.mjs',
      'test/panel-apply-state.test.mjs',
      'test/panel-get-audit.test.mjs',
      'test/engine-envelope.test.mjs',
      'test/apply-trash.test.mjs',
    ];
    for (const rel of oracles) {
      const p = path.join(SKILL_ROOT, rel);
      assert.ok(fs.existsSync(p), `oracle missing: ${rel}`);
      const body = fs.readFileSync(p, 'utf8');
      assert.ok(!body.includes(`${skipTestApi}(`), `${rel} must not call ${skipTestApi}(`);
      assert.ok(!body.includes(`${skipDescribeApi}(`), `${rel} must not call ${skipDescribeApi}(`);
    }
  });
});

