// W9 / SC7 — Clickable health + reaper-health banners → Doctor seed.
// Named gate: test_health_banner_doctor_seed (1:1 fields + async start attempted)
// + cross-surface fail-SAFE with dual-write rule.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  BANNER_SEED_FIELDS,
  BANNER_SURFACES,
  BANNER_DOCTOR_SEED_VERSION,
  normalizeBannerIssue,
  buildDashboardHealthBannerIssue,
  buildReaperHealthBannerIssue,
  extractBannerSeedFields,
  assertBannerSeedOneToOne,
  buildDoctorNavigationFromBanner,
  buildBannerDiagnosePlan,
  attemptAsyncBannerDiagnoseStart,
  assertBannerDoctorFailSafeWithDualWrite,
  buildClickableBannerContract,
} = require('../src/health-banner-doctor.js');

const {
  buildDoctorShortSeed,
  assertP5StartPlumbingGreen,
} = require('../src/session-start.js');

const {
  getDoctorIssue,
  DOCTOR_ISSUE_CATALOG_VERSION,
} = require('../src/reason-catalog.js');

const {
  evaluateDualWriteSurfaces,
  assertNoActionableRedUnderShadow,
  SURFACES,
} = require('../src/dual-write.js');

test('test_health_banner_doctor_seed', () => {
  // P5 plumbing must be green before P6 banner→Doctor ships.
  assert.strictEqual(assertP5StartPlumbingGreen().ok, true);

  // Closed catalog reused for health + reaper banner issue IDs (W9).
  assert.ok(getDoctorIssue('ZH_HEALTH_CHECK_ISSUES'));
  assert.ok(getDoctorIssue('ZH_REAPER_ABSTAIN_STREAK'));
  assert.ok(getDoctorIssue('ZH_REAPER_CHAIN_TAMPERED'));
  assert.ok(String(DOCTOR_ISSUE_CATALOG_VERSION).includes('w9')
    || DOCTOR_ISSUE_CATALOG_VERSION.length > 0);

  // ── Dashboard health banner: 1:1 fields, not a markdown path ──
  const healthIssue = buildDashboardHealthBannerIssue({
    reportDate: '2099-06-01',
    status: 'ISSUES FOUND',
    lastError: 'Status: ISSUES FOUND',
  });
  assert.strictEqual(healthIssue.issueId, 'ZH_HEALTH_CHECK_ISSUES');
  assert.ok(healthIssue.message);
  assert.strictEqual(healthIssue.message, healthIssue.exactMessage);
  assert.ok(healthIssue.component);
  assert.ok(healthIssue.lastError);
  assert.ok(Array.isArray(healthIssue.suggestedChecks));
  assert.strictEqual(healthIssue.isMarkdownPath, false);
  assert.strictEqual(healthIssue.markdownPath, null);
  assert.strictEqual(healthIssue.bannerSurface, 'dashboard_health');

  const healthSeed = buildDoctorShortSeed(healthIssue);
  const oneToOne = assertBannerSeedOneToOne(healthIssue, healthSeed);
  assert.strictEqual(oneToOne.ok, true, `1:1 mismatch: ${oneToOne.mismatches.join(',')}`);
  for (const f of BANNER_SEED_FIELDS) {
    assert.ok(Object.prototype.hasOwnProperty.call(extractBannerSeedFields(healthIssue), f), f);
  }
  assert.strictEqual(healthSeed.issueId, healthIssue.issueId);
  assert.strictEqual(healthSeed.message, healthIssue.message);
  assert.strictEqual(healthSeed.component, healthIssue.component);
  assert.strictEqual(healthSeed.lastError, healthIssue.lastError);
  assert.deepStrictEqual(healthSeed.suggestedChecks, healthIssue.suggestedChecks);
  assert.strictEqual(healthSeed.isMarkdownPath, false);

  // Navigation opens Doctor with seed query — never health_reports/*.md
  const nav = buildDoctorNavigationFromBanner(healthIssue, { autoDiagnose: true });
  assert.strictEqual(nav.ok, true);
  assert.strictEqual(nav.path, '/doctor');
  assert.ok(nav.href.startsWith('/doctor?'));
  assert.strictEqual(nav.isMarkdownPath, false);
  assert.strictEqual(nav.markdownPath, null);
  assert.ok(!/health_reports[/\\].*\.md/i.test(nav.href));
  assert.ok(nav.href.includes('issueId='));
  assert.ok(nav.href.includes('diagnose=1'));
  assert.strictEqual(nav.issue.issueId, healthIssue.issueId);
  assert.strictEqual(nav.issue.message, healthIssue.message);

  // Clickable contract for HTML banners
  const click = buildClickableBannerContract(healthIssue);
  assert.strictEqual(click.clickable, true);
  assert.strictEqual(click.opens, 'doctor');
  assert.strictEqual(click.notMarkdownPath, true);
  assert.ok(click.dataAttrs['data-issue-id']);
  assert.strictEqual(click.dataAttrs['data-diagnose'], '1');

  // ── Reaper-health banner (abstain streak + chain-tampered) ──
  const reaperIssue = buildReaperHealthBannerIssue({
    kind: 'abstain-streak',
    streak: 12,
    threshold: 5,
    message: 'Reaper has ABSTAINED for 12 consecutive sweeps (> 5) — flying blind.',
  });
  assert.strictEqual(reaperIssue.issueId, 'ZH_REAPER_ABSTAIN_STREAK');
  assert.strictEqual(reaperIssue.bannerSurface, 'reaper_health');
  const reaperSeed = buildDoctorShortSeed(reaperIssue);
  assert.strictEqual(assertBannerSeedOneToOne(reaperIssue, reaperSeed).ok, true);
  assert.strictEqual(reaperSeed.message, reaperIssue.message);

  const chainIssue = buildReaperHealthBannerIssue({ kind: 'chain-tampered' });
  assert.strictEqual(chainIssue.issueId, 'ZH_REAPER_CHAIN_TAMPERED');
  assert.ok(getDoctorIssue(chainIssue.issueId));

  // ── Async diagnose start attempted when engine enabled ──
  const profile = { claude: true, gemini: true, grok: true };
  const attempt = attemptAsyncBannerDiagnoseStart(healthIssue, {
    profile,
    engine: 'claude',
    classifierMode: 'shadow',
  });
  assert.strictEqual(attempt.attempted, true, 'async start must be attempted when engine enabled');
  assert.strictEqual(attempt.async, true);
  assert.strictEqual(attempt.ok, true);
  assert.strictEqual(attempt.failureNonBlocking, true);
  assert.strictEqual(attempt.uiUsable, true);
  assert.ok(attempt.seed);
  assert.strictEqual(attempt.seed.issueId, healthIssue.issueId);
  assert.strictEqual(attempt.seedOneToOne.ok, true);
  assert.strictEqual(attempt.session.engine, 'claude');
  assert.strictEqual(attempt.health.status, 'healthy');

  const plan = buildBannerDiagnosePlan(healthIssue, {
    profile,
    engine: 'gemini',
    classifierMode: 'shadow',
  });
  assert.strictEqual(plan.canStart, true);
  assert.strictEqual(plan.session.async, true);
  assert.strictEqual(plan.session.failureNonBlocking, true);
  assert.strictEqual(plan.session.attemptAsyncDiagnose, true);
  assert.strictEqual(plan.bannerOneToOne.ok, true);
  assert.strictEqual(plan.navigation.isMarkdownPath, false);
  assert.ok(plan.p6BannerDoctor);
  assert.strictEqual(plan.p6BannerDoctor.version, BANNER_DOCTOR_SEED_VERSION);

  // ── Start failure surfaces health and leaves UI usable ──
  const failed = attemptAsyncBannerDiagnoseStart(healthIssue, {
    profile,
    engine: 'claude',
    forceFail: true,
    failReason: 'simulated_start_timeout',
  });
  assert.strictEqual(failed.ok, false);
  assert.strictEqual(failed.attempted, true);
  assert.strictEqual(failed.uiUsable, true);
  assert.strictEqual(failed.failureNonBlocking, true);
  assert.ok(failed.health);
  assert.ok(/fail|timeout|start/i.test(failed.health.message + failed.health.status));
  assert.strictEqual(failed.session, null);

  // Disabled engine: no freeze; health surfaced; shell still usable via plan
  const denied = attemptAsyncBannerDiagnoseStart(reaperIssue, {
    profile: { claude: false, gemini: false, grok: false },
    engine: 'grok',
  });
  assert.strictEqual(denied.ok, false);
  assert.strictEqual(denied.uiUsable, true);
  assert.strictEqual(denied.failureNonBlocking, true);
  assert.ok(denied.plan.shell.paintFirst);
  assert.ok(denied.health);

  // Catalog alignment: custom message still keeps issueId + 1:1
  const custom = normalizeBannerIssue({
    issueId: 'ZH_SWEEP_ERROR',
    message: 'sweep parse failed on control char',
    lastError: 'U+0000 in process JSON',
    suggestedChecks: ['re-run sweep', 'check json-safe'],
  });
  assert.strictEqual(custom.catalogAligned, true);
  assert.strictEqual(custom.component, 'sweep'); // from catalog
  assert.strictEqual(custom.message, 'sweep parse failed on control char'); // override wins
  assert.deepStrictEqual(
    assertBannerSeedOneToOne(custom, buildDoctorShortSeed(custom)).ok,
    true,
  );

  assert.deepStrictEqual(BANNER_SURFACES.slice().sort(), ['dashboard_health', 'reaper_health'].sort());
});

test('cross-surface fail-SAFE with dual-write rule (W9 banner→Doctor)', () => {
  // Health/reaper banner Doctor seed must not paint dual-write scare RED under shadow.
  const failSafe = assertBannerDoctorFailSafeWithDualWrite({
    classifierMode: 'shadow',
    legacyWouldBeZombies: [{
      id: 'x',
      name: 'claude.exe',
      path: 'C:\\x\\claude.exe',
      count: 3,
      providers: ['anthropic'],
      root: 'services.exe',
      supervised: false,
    }],
  });
  assert.strictEqual(failSafe.ok, true);
  assert.strictEqual(failSafe.anySurfaceActionableRed, false);
  assert.strictEqual(failSafe.notMarkdownPath, true);
  assert.strictEqual(failSafe.bannerOneToOne.ok, true);
  assert.ok(assertNoActionableRedUnderShadow(failSafe.dualWrite));

  for (const name of SURFACES) {
    assert.strictEqual(
      failSafe.dualWrite.surfaces[name].actionableRed,
      false,
      `${name} must stay non-actionable under shadow while banner seeds Doctor`,
    );
  }

  // Reaper-health surface specifically
  const reaperPlan = buildBannerDiagnosePlan(
    buildReaperHealthBannerIssue({ kind: 'abstain-streak', streak: 9, threshold: 3 }),
    { classifierMode: 'shadow', profile: { claude: true, gemini: true, grok: true } },
  );
  assert.strictEqual(reaperPlan.navigation.isMarkdownPath, false);
  const dual = evaluateDualWriteSurfaces({
    classifierMode: 'shadow',
    legacyWouldBeZombies: [{ id: '1', name: 'x', count: 1 }],
  });
  assert.strictEqual(dual.surfaces.reaper_health_scare.actionableRed, false);
  assert.strictEqual(dual.surfaces.dashboard_zombie_banner.actionableRed, false);
});
