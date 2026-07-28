// W8 / SC5+SC6 — Multi-engine Investigate + Doctor shared start.

const { test } = require('node:test');
const assert = require('node:assert');

const {
  ENGINE_IDS,
  ENGINE_TRANSPORT,
  SHELL_PAINT_BUDGET_MS,
  FIRST_PROMPT_BUDGET_MS,
  P5_START_PLUMBING,
  listEngineToggle,
  pickDefaultEngine,
  buildInvestigateSlimSeed,
  formatInvestigateSlimSeedText,
  buildInvestigateDeepBrief,
  buildDoctorShortSeed,
  buildSessionStartPlan,
  doctorShellBeforeSessionContract,
  assertP5StartPlumbingGreen,
  normalizeEngineId,
} = require('../src/session-start.js');

test('test_investigate_three_engines_slim_start', () => {
  // Three engines listed with subscription-CLI transports (Claude / agy / grok-cli).
  assert.deepStrictEqual(ENGINE_IDS.slice(), ['claude', 'gemini', 'grok']);
  assert.strictEqual(ENGINE_TRANSPORT.claude.transport, 'claude');
  assert.strictEqual(ENGINE_TRANSPORT.gemini.transport, 'agy');
  assert.strictEqual(ENGINE_TRANSPORT.grok.transport, 'grok-cli');
  assert.ok(ENGINE_TRANSPORT.grok.spawn.includes('grok'));
  assert.ok(ENGINE_TRANSPORT.grok.spawn.includes('-p') || ENGINE_TRANSPORT.grok.argvHint.includes('-p'));

  const profile = { claude: true, gemini: true, grok: true };
  const toggle = listEngineToggle(profile);
  assert.strictEqual(toggle.engines.length, 3);
  assert.ok(toggle.engines.every((e) => e.enabled && e.subscriptionCli));
  assert.deepStrictEqual(toggle.available, ['claude', 'gemini', 'grok']);

  // Dead / unhealthy: disabled with health, never silent.
  const partial = listEngineToggle(
    { claude: true, gemini: false, grok: true },
    { firstPromptMs: { grok: 20_000 } },
  );
  const gem = partial.engines.find((e) => e.id === 'gemini');
  const gr = partial.engines.find((e) => e.id === 'grok');
  assert.strictEqual(gem.enabled, false);
  assert.ok(/unavailable/i.test(gem.health));
  assert.strictEqual(gr.enabled, false);
  assert.ok(/budget|disabled/i.test(gr.health));

  // Slim seed: pid + class + top reason codes + freeze/kill status.
  const candidate = {
    pid: 4242,
    name: 'claude.exe',
    engineClass: 'claude',
    reasonCodes: ['SPEND_POSITIVE', 'UNSUPERVISED', 'ENGINE_POSITIVE', 'EXTRA_1', 'EXTRA_2',
      'EXTRA_3', 'EXTRA_4', 'EXTRA_5', 'EXTRA_6'],
    imagePath: 'C:\\Users\\x\\claude.exe',
    wouldBeActionableRed: true,
  };
  const slim = buildInvestigateSlimSeed(candidate, {
    classifierMode: 'shadow',
    freezeCapability: false,
    freezeKillEnabled: false,
  });
  assert.strictEqual(slim.kind, 'investigate_slim');
  assert.strictEqual(slim.pid, 4242);
  assert.strictEqual(slim.class, 'claude');
  assert.ok(Array.isArray(slim.topReasonCodes));
  assert.ok(slim.topReasonCodes.length <= 8);
  assert.ok(slim.topReasonCodes.includes('SPEND_POSITIVE'));
  assert.ok(slim.freezeStatus);
  assert.ok(slim.killStatus);
  assert.strictEqual(slim.slim, true);
  assert.strictEqual(slim.deepBrief, false);

  const text = formatInvestigateSlimSeedText(slim);
  assert.ok(text.includes('4242'));
  assert.ok(text.includes('SLIM SEED'));

  // Shell paints first; session async with slim seed for each healthy engine.
  for (const eng of ['claude', 'gemini', 'grok']) {
    const plan = buildSessionStartPlan({
      surface: 'investigate',
      engine: eng,
      candidate,
      profile,
      classifierMode: 'shadow',
      freezeCapability: false,
    });
    assert.strictEqual(plan.shell.paintFirst, true);
    assert.ok(plan.shell.paintBudgetMs <= 1000);
    assert.strictEqual(plan.shell.enginePicker, true);
    assert.strictEqual(plan.shell.engines.length, 3);
    assert.strictEqual(plan.seedBeforeSession, true);
    assert.strictEqual(plan.session.async, true);
    assert.strictEqual(plan.session.cancelable, true);
    assert.strictEqual(plan.session.failureNonBlocking, true);
    assert.strictEqual(plan.session.autoStart, false);
    assert.strictEqual(plan.session.firstPromptBudgetMs, FIRST_PROMPT_BUDGET_MS);
    assert.strictEqual(plan.engine, eng);
    assert.strictEqual(plan.canStart, true);
    assert.ok(plan.seedText.includes('SLIM SEED'));
    assert.strictEqual(plan.seed.pid, 4242);
    assert.strictEqual(plan.seed.kind, 'investigate_slim');
  }

  // Deep-brief path for selected candidate (closed recommendedNext; no second multi-minute wait).
  const deep = buildInvestigateDeepBrief(candidate, {
    classifierMode: 'shadow',
    freezeCapability: false,
  });
  assert.strictEqual(deep.kind, 'investigate_deep_brief');
  assert.ok(deep.recommendedNext);
  assert.notStrictEqual(deep.recommendedNext, 'FREEZE_THEN_KILL'); // shadow ⇒ not freeze-then-kill scare
  assert.strictEqual(deep.blocksSessionStart, false);
  assert.ok(Array.isArray(deep.treatEnum));

  // Default never picks a dead engine.
  assert.strictEqual(
    pickDefaultEngine(['claude'], { coding_family: 'grok' }, 'grok'),
    'claude',
  );
  assert.strictEqual(normalizeEngineId('agy'), 'gemini');
  assert.strictEqual(normalizeEngineId('nope'), null);
  assert.ok(SHELL_PAINT_BUDGET_MS <= 1000);
  assert.strictEqual(FIRST_PROMPT_BUDGET_MS, 15_000);
});

test('test_doctor_shell_before_session', () => {
  const contract = doctorShellBeforeSessionContract();
  assert.strictEqual(contract.surface, 'doctor');
  assert.strictEqual(contract.shellFirst, true);
  assert.strictEqual(contract.autoStartSession, false);
  assert.strictEqual(contract.blockingAutoSession, false);
  assert.strictEqual(contract.enginePickerRequired, true);
  assert.strictEqual(contract.oneClickDiagnose, true);
  assert.strictEqual(contract.sessionStartOnDemand, true);
  assert.ok(contract.engines.length === 3);

  // Opening Doctor without diagnose: plan paints shell, does not auto-start session.
  const plan = buildSessionStartPlan({
    surface: 'doctor',
    profile: { claude: true, gemini: true, grok: true },
    classifierMode: 'shadow',
  });
  assert.strictEqual(plan.shell.paintFirst, true);
  assert.strictEqual(plan.shell.autoStartSession, false);
  assert.strictEqual(plan.session.autoStart, false);
  assert.strictEqual(plan.session.async, true);
  assert.strictEqual(plan.session.failureNonBlocking, true);
  assert.ok(plan.shell.enginePicker);
  assert.strictEqual(plan.seed.kind, 'doctor_short');
  assert.ok(plan.seedText.includes('SHORT DIAGNOSE') || plan.seedText.includes('DOCTOR'));

  // One-click diagnose short seed may carry issue fields without blocking shell.
  const withIssue = buildDoctorShortSeed({
    issueId: 'ZH_SWEEP_ERROR',
    message: 'sweep parse failed',
    component: 'radar',
    lastError: 'control char',
    suggestedChecks: ['re-run sweep', 'check json-safe'],
  });
  assert.strictEqual(withIssue.issueId, 'ZH_SWEEP_ERROR');
  assert.ok(withIssue.short);

  // Unhealthy engine denied; failure non-blocking (plan still returns shell).
  const denied = buildSessionStartPlan({
    surface: 'doctor',
    engine: 'gemini',
    profile: { claude: true, gemini: false, grok: false },
  });
  assert.ok(denied.shell.paintFirst);
  assert.ok(denied.engineDenied || denied.engine === 'claude');
});

test('test_p6_requires_p5_start_plumbing', () => {
  // P6 (W9 banner→Doctor) must not ship without P5 shared start plumbing green.
  const gate = assertP5StartPlumbingGreen();
  assert.strictEqual(gate.ok, true, `P5 plumbing missing: ${gate.missing.join(',')}`);
  assert.deepStrictEqual(gate.plumbing.id, 'p5-shared-session-start');
  for (const req of P5_START_PLUMBING.required) {
    assert.ok(gate.checks[req], `missing check ${req}`);
  }
  assert.deepStrictEqual(P5_START_PLUMBING.engines.slice(), ['claude', 'gemini', 'grok']);
  assert.ok(P5_START_PLUMBING.surfaces.includes('investigate'));
  assert.ok(P5_START_PLUMBING.surfaces.includes('doctor'));

  // A session-start plan carries the P5 stamp for P6 consumers.
  const plan = buildSessionStartPlan({
    surface: 'investigate',
    profile: { claude: true, gemini: true, grok: true },
    candidate: { pid: 1, engineClass: 'claude', reasonCodes: ['ENGINE_POSITIVE'] },
  });
  assert.ok(plan.p5Plumbing);
  assert.strictEqual(plan.p5Plumbing.version, 'w8-p5-v1');
  assert.ok(plan.p5Plumbing.required.includes('slim_seed'));
  assert.ok(plan.p5Plumbing.required.includes('doctor_shell_first'));
});
