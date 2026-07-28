// Overhaul Wave 4 — Honesty Law UI & Asynchronous State Resolution: the HONESTY-LAW UI.
//
// Exercises the REAL Wave-4 source (src/honesty-ui.mjs), proving the done-when: the UI listens for
// asynchronous verification results on the event bus, resolves every claim's visual state to its
// EARNED Honesty-Law tier (pending -> verified / unverified / refuted, styling derived from state),
// surfaces interactive context on a refuted claim, and — when a resolution arrives for an
// OFF-SCREEN claim — still updates the state dynamically while raising a margin indicator and a
// global status-tray alert. VERIFIED is only ever minted from a completed, agreeing evidence
// record; there is no API that can assign it.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { ClaimEventBus, CLAIM_EVENT_TOPIC } from '../src/claim-event-bus.mjs';
import { CLAIM_KIND } from '../src/semantic-classifier.mjs';
import { SANDBOX_TOPIC, EVIDENCE_TYPE, makeEvidenceRecord } from '../src/sandbox-pipeline.mjs';
import { EXECUTION_OUTCOME } from '../src/wasm-sandbox.mjs';
import {
  CLAIM_UI_STATE,
  CLAIM_UI_STATES,
  CLAIM_STATE_STYLE,
  styleFor,
  resolveTier,
  buildRefutedContext,
  HonestyLawUI,
  HONESTY_UI_CLAIM_FIXTURE,
  HONESTY_UI_VIEWPORT,
  runHonestyUiFixture,
} from '../src/honesty-ui.mjs';

/** A registered claim payload the tests reuse. */
function makeClaim(overrides = {}) {
  return {
    id: 'ui-claim-1',
    kind: CLAIM_KIND.MATHEMATICAL,
    claim_type: 'computational',
    statement: 'The sum of 2 and 2 equals 4.',
    span: { start: 0, end: 28 },
    computation: { op: 'add', args: ['2', '2'], expected: '4' },
    ...overrides,
  };
}

/** A minimal completed-execution stub (shape-compatible with wasm-sandbox execution records). */
function execStub({ value = '4', outcome = EXECUTION_OUTCOME.COMPLETED } = {}) {
  return { outcome, value, module_sha256: 'sha-stub', metered: true };
}

/** Evidence for a claim, built through the REAL Wave-3 record composer. */
function evidenceFor(claimId, { execution = execStub(), agreement = null, reason = null, error = null } = {}) {
  return makeEvidenceRecord({
    claim_id: claimId,
    source: { pipeline: 'fast-path', lane: 'exact-arithmetic' },
    module_source: 'test-module',
    execution,
    agreement,
    reason,
    error,
  });
}

/** Register a claim and (optionally) deliver evidence for it on a fresh bus+UI pair. */
async function uiWith(claim, evidence = null) {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, claim);
  if (evidence) bus.publish(SANDBOX_TOPIC.EVIDENCE, evidence);
  await bus.settle();
  return { bus, ui };
}

// =====================================================================================
// 0. The pinned state + styling vocabulary.
// =====================================================================================

test('CLAIM_UI_STATE pins the four Honesty-Law styling states', () => {
  assert.deepEqual(CLAIM_UI_STATES, ['pending', 'verified', 'unverified', 'refuted']);
  assert.ok(Object.isFrozen(CLAIM_UI_STATE));
});

test('every state has a frozen style descriptor and styleFor derives it; unknown states throw', () => {
  for (const state of CLAIM_UI_STATES) {
    const style = styleFor(state);
    assert.equal(style, CLAIM_STATE_STYLE[state]);
    assert.ok(Object.isFrozen(style));
    assert.equal(style.state, state);
    assert.match(style.css_class, new RegExp(`claim--${state}`));
    assert.equal(typeof style.glyph, 'string');
    assert.equal(typeof style.label, 'string');
  }
  assert.throws(() => styleFor('settled'), /unknown claim UI state/);
});

// =====================================================================================
// 1. resolveTier — THE HONESTY LAW as a mapping: verified only when earned; everything
//    unsettled is UNVERIFIED, never promoted.
// =====================================================================================

test('a COMPLETED execution with agreement=true resolves VERIFIED — and nothing else does', () => {
  const verified = resolveTier(evidenceFor('c', { agreement: true }));
  assert.equal(verified.state, CLAIM_UI_STATE.VERIFIED);

  // agreement true but the run did NOT complete may never mint verified.
  const trapped = resolveTier(evidenceFor('c', { execution: execStub({ outcome: EXECUTION_OUTCOME.TRAPPED, value: null }), agreement: true }));
  assert.notEqual(trapped.state, CLAIM_UI_STATE.VERIFIED);
});

test('agreement=false resolves REFUTED', () => {
  const tier = resolveTier(evidenceFor('c', { execution: execStub({ value: '4' }), agreement: false }));
  assert.equal(tier.state, CLAIM_UI_STATE.REFUTED);
  assert.match(tier.reason, /CONTRADICTS/);
});

test('abstentions, errors, non-completed outcomes, and expectation-free completions all resolve UNVERIFIED', () => {
  const abstained = resolveTier(evidenceFor('c', { execution: null, reason: 'no machine-checkable payload' }));
  assert.equal(abstained.state, CLAIM_UI_STATE.UNVERIFIED);
  assert.match(abstained.reason, /abstained honestly/);

  const errored = resolveTier(evidenceFor('c', { execution: null, error: 'adapter blew up' }));
  assert.equal(errored.state, CLAIM_UI_STATE.UNVERIFIED);

  for (const outcome of [EXECUTION_OUTCOME.TRAPPED, EXECUTION_OUTCOME.TERMINATED, EXECUTION_OUTCOME.REFUSED, EXECUTION_OUTCOME.ERROR]) {
    const tier = resolveTier(evidenceFor('c', { execution: execStub({ outcome, value: null }) }));
    assert.equal(tier.state, CLAIM_UI_STATE.UNVERIFIED, `outcome ${outcome} must resolve unverified`);
  }

  // Completed but nothing to compare against: no tier is minted.
  const noExpectation = resolveTier(evidenceFor('c', { execution: execStub(), agreement: null }));
  assert.equal(noExpectation.state, CLAIM_UI_STATE.UNVERIFIED);
  assert.match(noExpectation.reason, /no expected value|nothing to agree with/);
});

test('resolveTier refuses non-evidence: only the typed evidence record may mint a state', () => {
  assert.throws(() => resolveTier(null), /must be an object/);
  assert.throws(() => resolveTier({ verdict: 'VERIFIED' }), /unrecognized evidence_type/);
  assert.throws(() => resolveTier({ evidence_type: 'somebody-elses-record', agreement: true }), /unrecognized evidence_type/);
});

// =====================================================================================
// 2. Registration + dynamic styling — pending is the ONLY entry state; evidence restyles.
// =====================================================================================

test('an intercepted claim registers as PENDING with the pending style', async () => {
  const { ui } = await uiWith(makeClaim());
  const record = ui.claim('ui-claim-1');
  assert.equal(record.state, CLAIM_UI_STATE.PENDING);
  assert.equal(record.style, styleFor(CLAIM_UI_STATE.PENDING));
  assert.equal(record.evidence, null);
  assert.equal(record.resolved_tick, null);
  assert.equal(record.history[0].to, CLAIM_UI_STATE.PENDING);
});

test('done-when: an asynchronous evidence result dynamically restyles the claim to its earned tier', async () => {
  const { ui } = await uiWith(makeClaim(), evidenceFor('ui-claim-1', { agreement: true }));
  const record = ui.claim('ui-claim-1');
  assert.equal(record.state, CLAIM_UI_STATE.VERIFIED);
  assert.equal(record.style, styleFor(CLAIM_UI_STATE.VERIFIED));
  // The resolution happened strictly AFTER registration — asynchronous state resolution, proven.
  assert.ok(record.resolved_tick > record.registered_tick);
  assert.deepEqual(
    record.history.map((h) => h.to),
    [CLAIM_UI_STATE.PENDING, CLAIM_UI_STATE.VERIFIED],
  );
});

test('an abstention restyles to UNVERIFIED — visible, never blank, never promoted', async () => {
  const { ui } = await uiWith(makeClaim(), evidenceFor('ui-claim-1', { execution: null, reason: 'deferred' }));
  const record = ui.claim('ui-claim-1');
  assert.equal(record.state, CLAIM_UI_STATE.UNVERIFIED);
  assert.equal(record.style, styleFor(CLAIM_UI_STATE.UNVERIFIED));
});

test('routing records annotate placement but NEVER change the state (routing is not evidence)', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim());
  bus.publish('claim:routed', { claim_id: 'ui-claim-1', pipeline: 'fast-path', lane: 'exact-arithmetic' });
  await bus.settle();
  const record = ui.claim('ui-claim-1');
  assert.equal(record.pipeline, 'fast-path');
  assert.equal(record.lane, 'exact-arithmetic');
  assert.equal(record.state, CLAIM_UI_STATE.PENDING);
});

// =====================================================================================
// 3. THE HONESTY LAW GATE — verified cannot be minted by anything but earned evidence.
// =====================================================================================

test('there is NO public setter for state: the UI exposes no way to assign verified', () => {
  const ui = new HonestyLawUI({ bus: new ClaimEventBus() });
  assert.equal(typeof ui.setState, 'undefined');
  assert.equal(typeof ui.verify, 'undefined');
  assert.equal(typeof ui.setClaimState, 'undefined');
});

test('a non-evidence payload published on the evidence topic mints NOTHING — audited as an orphan', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim());
  bus.publish(SANDBOX_TOPIC.EVIDENCE, { claim_id: 'ui-claim-1', verdict: 'VERIFIED', evidence_type: 'forged' });
  await bus.settle();
  assert.equal(ui.claim('ui-claim-1').state, CLAIM_UI_STATE.PENDING, 'the forged record must not restyle the claim');
  assert.equal(ui.orphans.length, 1);
  assert.match(ui.orphans[0].reason, /nothing may mint a state/);
  assert.equal(ui.honestyLawHolds, true);
});

test('honestyLawHolds measures the invariant across every record', async () => {
  const { bus, ui } = await uiWith(makeClaim(), evidenceFor('ui-claim-1', { agreement: true }));
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim({ id: 'ui-claim-2', statement: 'The sum of 3 and 3 equals 7.', computation: { op: 'add', args: ['3', '3'], expected: '7' } }));
  bus.publish(SANDBOX_TOPIC.EVIDENCE, evidenceFor('ui-claim-2', { execution: execStub({ value: '6' }), agreement: false }));
  await bus.settle();
  assert.equal(ui.honestyLawHolds, true);
});

// =====================================================================================
// 4. Refuted context — interactive tooltips / inline blocks naming the evidence.
// =====================================================================================

test('a refuted claim surfaces context: tooltip + inline block with expected vs observed and the module identity', async () => {
  const claim = makeClaim({ computation: { op: 'add', args: ['2', '2'], expected: '5' }, statement: 'The sum of 2 and 2 equals 5.' });
  const { ui } = await uiWith(claim, evidenceFor('ui-claim-1', { execution: execStub({ value: '4' }), agreement: false }));
  const record = ui.claim('ui-claim-1');
  assert.equal(record.state, CLAIM_UI_STATE.REFUTED);
  assert.ok(record.context);
  assert.match(record.context.tooltip, /REFUTED/);
  assert.match(record.context.tooltip, /asserted 5/);
  assert.match(record.context.tooltip, /observed 4/);
  assert.equal(record.context.inline_block.expected, '5');
  assert.equal(record.context.inline_block.observed, '4');
  assert.equal(record.context.inline_block.module_sha256, 'sha-stub');
  assert.ok(Object.isFrozen(record.context));
  assert.ok(Object.isFrozen(record.context.inline_block));
});

test('toggleContext is the click-through: expands/collapses the inline block; non-refuted claims have none', async () => {
  const claim = makeClaim({ computation: { op: 'add', args: ['2', '2'], expected: '5' } });
  const { ui } = await uiWith(claim, evidenceFor('ui-claim-1', { execution: execStub({ value: '4' }), agreement: false }));

  assert.equal(ui.claim('ui-claim-1').context_expanded, false);
  const opened = ui.toggleContext('ui-claim-1');
  assert.equal(opened.expanded, true);
  assert.equal(ui.claim('ui-claim-1').context_expanded, true);
  const closed = ui.toggleContext('ui-claim-1');
  assert.equal(closed.expanded, false);

  const { ui: pendingUi } = await uiWith(makeClaim({ id: 'still-pending' }));
  assert.throws(() => pendingUi.toggleContext('still-pending'), /only a refuted claim carries interactive context/);
  assert.throws(() => pendingUi.toggleContext('nobody'), /unknown claim_id/);
});

test('renderClaim renders from the EARNED style, appends the tooltip, and inlines the block when expanded', async () => {
  const claim = makeClaim({ computation: { op: 'add', args: ['2', '2'], expected: '5' }, statement: 'The sum of 2 and 2 equals 5.' });
  const { ui } = await uiWith(claim, evidenceFor('ui-claim-1', { execution: execStub({ value: '4' }), agreement: false }));

  const collapsed = ui.renderClaim('ui-claim-1');
  assert.match(collapsed, /\[Refuted\] The sum of 2 and 2 equals 5\./);
  assert.match(collapsed, /REFUTED/);
  assert.doesNotMatch(collapsed, /Why this claim is refuted/);

  ui.toggleContext('ui-claim-1');
  const expanded = ui.renderClaim('ui-claim-1');
  assert.match(expanded, /Why this claim is refuted/);
  assert.match(expanded, /expected: 5\s+observed: 4/);
});

test('buildRefutedContext is total over sparse claims/evidence (nulls, not throws)', () => {
  const context = buildRefutedContext({}, { agreement: false, execution: null });
  assert.match(context.tooltip, /REFUTED/);
  assert.equal(context.inline_block.expected, null);
  assert.equal(context.inline_block.observed, null);
});

// =====================================================================================
// 5. Off-screen resolution — the viewport, margin indicators, and the global status tray.
// =====================================================================================

test('done-when: evidence for an OFF-SCREEN claim updates its state AND raises a margin indicator + tray alert', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  ui.setViewport({ start: 0, end: 100 });
  const offScreen = makeClaim({ id: 'far-away', span: { start: 400, end: 428 }, computation: { op: 'add', args: ['2', '2'], expected: '5' } });
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, offScreen);
  bus.publish(SANDBOX_TOPIC.EVIDENCE, evidenceFor('far-away', { execution: execStub({ value: '4' }), agreement: false }));
  await bus.settle();

  const record = ui.claim('far-away');
  assert.equal(record.on_screen, false);
  // The state STILL updated dynamically — resolution is never deferred just because it is unseen...
  assert.equal(record.state, CLAIM_UI_STATE.REFUTED);
  // ...and the user is alerted: a margin indicator carrying the final tier, unseen in the tray.
  const indicator = ui.marginIndicators.find((i) => i.claim_id === 'far-away');
  assert.ok(indicator);
  assert.equal(indicator.state, CLAIM_UI_STATE.REFUTED);
  assert.equal(indicator.seen, false);
  assert.equal(ui.statusTray.unseen_offscreen_updates, 1);
});

test('an ON-SCREEN resolution raises NO margin indicator', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  ui.setViewport({ start: 0, end: 100 });
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim({ span: { start: 0, end: 28 } }));
  bus.publish(SANDBOX_TOPIC.EVIDENCE, evidenceFor('ui-claim-1', { agreement: true }));
  await bus.settle();
  assert.equal(ui.claim('ui-claim-1').on_screen, true);
  assert.equal(ui.marginIndicators.length, 0);
  assert.equal(ui.statusTray.unseen_offscreen_updates, 0);
});

test('acknowledge() marks the indicator seen and drains the tray badge', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  ui.setViewport({ start: 0, end: 10 });
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim({ span: { start: 50, end: 78 } }));
  bus.publish(SANDBOX_TOPIC.EVIDENCE, evidenceFor('ui-claim-1', { agreement: true }));
  await bus.settle();
  assert.equal(ui.statusTray.unseen_offscreen_updates, 1);
  assert.equal(ui.acknowledge('ui-claim-1'), 1);
  assert.equal(ui.statusTray.unseen_offscreen_updates, 0);
  assert.equal(ui.marginIndicators[0].seen, true);
  // Idempotent: nothing left to acknowledge.
  assert.equal(ui.acknowledge('ui-claim-1'), 0);
});

test('the status tray tallies every state; visibility follows the viewport, spanless claims default visible', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  ui.setViewport({ start: 0, end: 100 });
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim({ id: 'a', span: { start: 0, end: 10 } }));
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim({ id: 'b', span: { start: 200, end: 210 } }));
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim({ id: 'c', span: undefined }));
  bus.publish(SANDBOX_TOPIC.EVIDENCE, evidenceFor('a', { agreement: true }));
  bus.publish(SANDBOX_TOPIC.EVIDENCE, evidenceFor('b', { execution: execStub({ value: '9' }), agreement: false }));
  await bus.settle();

  const tray = ui.statusTray;
  assert.equal(tray.total, 3);
  assert.deepEqual(tray.counts, { pending: 1, verified: 1, unverified: 0, refuted: 1 });
  assert.equal(ui.claim('a').on_screen, true);
  assert.equal(ui.claim('b').on_screen, false);
  assert.equal(ui.claim('c').on_screen, true, 'a spanless claim defaults visible');

  // Scrolling: the viewport moves, visibility recomputes.
  ui.setViewport({ start: 150, end: 300 });
  assert.equal(ui.claim('a').on_screen, false);
  assert.equal(ui.claim('b').on_screen, true);
});

test('markOffScreen/markOnScreen override the viewport (and survive viewport changes)', async () => {
  const { ui } = await uiWith(makeClaim());
  ui.markOffScreen('ui-claim-1');
  assert.equal(ui.claim('ui-claim-1').on_screen, false);
  ui.setViewport({ start: 0, end: 1000 });
  assert.equal(ui.claim('ui-claim-1').on_screen, false, 'the explicit override outranks the viewport');
  ui.markOnScreen('ui-claim-1');
  assert.equal(ui.claim('ui-claim-1').on_screen, true);
  assert.throws(() => ui.markOffScreen('nobody'), /unknown claim_id/);
});

test('setViewport validates its range', () => {
  const ui = new HonestyLawUI({ bus: new ClaimEventBus() });
  assert.throws(() => ui.setViewport({ start: 10, end: 0 }), /end >= start/);
  assert.throws(() => ui.setViewport('everything'), /must be null or/);
  ui.setViewport(null);
  assert.equal(ui.viewport, null);
});

// =====================================================================================
// 6. No silent loss — orphans audited; attach/detach guards.
// =====================================================================================

test('evidence for an unregistered claim is audited on orphans, never dropped, never throws', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  bus.publish(SANDBOX_TOPIC.EVIDENCE, evidenceFor('ghost', { agreement: true }));
  bus.publish('claim:routed', { claim_id: 'ghost', pipeline: 'fast-path' });
  await bus.settle();
  assert.equal(ui.orphans.length, 2);
  assert.ok(ui.orphans.every((o) => /audited/.test(o.reason)));
  assert.equal(bus.errors.length, 0, 'the UI listeners never threw into the bus');
});

test('duplicate interception keeps the first registration and audits the duplicate', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim());
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim({ statement: 'an impostor' }));
  await bus.settle();
  assert.equal(ui.claims.length, 1);
  assert.equal(ui.claim('ui-claim-1').statement, 'The sum of 2 and 2 equals 4.');
  assert.equal(ui.orphans.length, 1);
  assert.match(ui.orphans[0].reason, /duplicate/);
});

test('attach twice throws; detach stops updates and is idempotent', async () => {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  assert.throws(() => ui.attach(), /already attached/);
  ui.detach();
  ui.detach();
  assert.equal(ui.attached, false);
  bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, makeClaim());
  await bus.settle();
  assert.equal(ui.claims.length, 0, 'a detached UI receives nothing');
});

test('constructor validates the bus', () => {
  assert.throws(() => new HonestyLawUI(), /bus must be a ClaimEventBus-like/);
  assert.throws(() => new HonestyLawUI({ bus: {} }), /bus must be a ClaimEventBus-like/);
});

test('snapshots are frozen; audits are frozen copies', async () => {
  const { ui } = await uiWith(makeClaim(), evidenceFor('ui-claim-1', { agreement: true }));
  const record = ui.claim('ui-claim-1');
  assert.ok(Object.isFrozen(record));
  assert.ok(Object.isFrozen(record.history));
  assert.ok(Object.isFrozen(ui.claims));
  assert.ok(Object.isFrozen(ui.updates));
  assert.ok(Object.isFrozen(ui.statusTray));
  assert.equal(ui.claim('nobody'), null);
});

// =====================================================================================
// 7. THE DONE-WHEN, measured end-to-end — the full Wave-1 -> Wave-4 fixture.
// =====================================================================================

test('done-when (fixture): async results resolve every claim to its Honesty-Law tier; the off-screen refutation raises the margin alert', async () => {
  const run = await runHonestyUiFixture();

  // Given: an asynchronous verification result returns for a claim that is currently off-screen...
  assert.equal(run.refuted.on_screen, false, 'the refuted fixture claim sits outside the fixture viewport');
  // When: the UI receives the resolution payload... Then: the visual state updates DYNAMICALLY...
  assert.equal(run.everyClaimResolvedDynamically, true);
  // ...to its final Honesty-Law tier (refuted WITH context)...
  assert.equal(run.statesReflectHonestyTiers, true);
  assert.equal(run.refutedContextSurfaced, true);
  // ...and a margin indicator alerts the user to the off-screen state change.
  assert.equal(run.offScreenAlerted, true);
  // THE HONESTY LAW held across every record.
  assert.equal(run.honestyLawEnforced, true);

  // The tiers, spelled out.
  assert.equal(run.verified.state, CLAIM_UI_STATE.VERIFIED);
  assert.equal(run.refuted.state, CLAIM_UI_STATE.REFUTED);
  assert.equal(run.proof.state, CLAIM_UI_STATE.UNVERIFIED);
  assert.equal(run.empirical.state, CLAIM_UI_STATE.UNVERIFIED);

  // The verified tier was EARNED: real WASM executed, completed, and agreed.
  assert.equal(run.verified.evidence.evidence_type, EVIDENCE_TYPE);
  assert.equal(run.verified.evidence.agreement, true);
  assert.equal(run.verified.evidence.outcome, EXECUTION_OUTCOME.COMPLETED);
  assert.ok(run.verified.evidence.module_sha256, 'the evidence names the module that actually ran');

  // The refuted context names the disagreement the sandbox observed (2+2 = 4, not 5).
  assert.equal(run.refuted.context.inline_block.expected, '5');
  assert.equal(run.refuted.context.inline_block.observed, '4');

  // The tray reflects the final tiering globally.
  assert.deepEqual(run.tray.counts, { pending: 0, verified: 1, unverified: 2, refuted: 1 });

  // Wave-2/3 invariants still hold underneath: routed exclusively, legacy queue bypassed.
  assert.equal(run.router.quarantined.length, 0);
  assert.ok(run.router.routed.every((r) => r.legacy_queue_bypassed === true));
});

test('the fixture vocabulary is pinned and frozen', () => {
  assert.equal(HONESTY_UI_CLAIM_FIXTURE.length, 4);
  assert.ok(Object.isFrozen(HONESTY_UI_CLAIM_FIXTURE));
  assert.ok(Object.isFrozen(HONESTY_UI_VIEWPORT));
  // The refuted + proof claims sit beyond the fixture viewport; the others inside it.
  const inView = (c) => c.span.start < HONESTY_UI_VIEWPORT.end && c.span.end > HONESTY_UI_VIEWPORT.start;
  assert.equal(inView(HONESTY_UI_CLAIM_FIXTURE[0]), true);
  assert.equal(inView(HONESTY_UI_CLAIM_FIXTURE[1]), false);
  assert.equal(inView(HONESTY_UI_CLAIM_FIXTURE[2]), false);
  assert.equal(inView(HONESTY_UI_CLAIM_FIXTURE[3]), true);
});
