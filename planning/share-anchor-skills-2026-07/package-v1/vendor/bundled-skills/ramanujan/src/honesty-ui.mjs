// Overhaul Wave 4 — Honesty Law UI & Asynchronous State Resolution: the HONESTY-LAW UI.
//
// The UI EVENT LISTENER for verification results — the layer the earlier waves left seams for
// ("Wave 4 attaches the Honesty-Law UI listeners" — claim-event-bus.mjs; "the payload the Wave-4
// Honesty-Law UI listeners consume" — sandbox-pipeline.mjs). It subscribes to the bus and keeps a
// per-claim UI record whose visual state ALWAYS reflects the strongest evidence that ACTUALLY
// arrived — never a caller assertion, never a default of trust.
//
// THE HONESTY LAW, ENFORCED IN THE STATE MACHINE (not in prose):
//   PENDING     is the ONLY entry state. A claim is registered when its interception event is
//               delivered; until a verification result arrives it is styled pending — an
//               unverified claim can never bypass the tiering by simply... being rendered.
//   VERIFIED    is EARNED, never assigned. The ONLY transition into `verified` is a structured
//               `claim:evidence` record whose sandbox execution COMPLETED and whose
//               expected-vs-observed agreement is `true`. There is NO public setter; nothing else
//               in the API can mint the verified style.
//   REFUTED     is an agreement of `false`: the sandbox actually executed and the observed value
//               CONTRADICTS the claim. A refuted claim carries INTERACTIVE CONTEXT (a tooltip +
//               an expandable inline block naming expected vs observed, the module that ran, and
//               its sha256) — the user is told not just "wrong" but wrong HOW, on WHOSE evidence.
//   UNVERIFIED  is everything else the pipeline honestly could not settle: abstentions, honest
//               overflow traps, terminated/refused runs, adapter errors, executions with nothing
//               to compare against. Unverified is a VISIBLE tier, styled as such — never blank,
//               never quietly promoted.
//
// ASYNCHRONOUS STATE RESOLUTION (the done-when's off-screen arm). Verification is asynchronous by
// construction (Waves 1-3), so a result routinely lands AFTER the claim scrolled away. The UI
// models visibility (a viewport over full-stream spans + explicit overrides); when a resolution
// arrives for an OFF-SCREEN claim, the claim's state still updates dynamically AND a margin
// indicator is appended (with a global status tray tally), so the user is alerted to the state
// change they cannot currently see. acknowledge() clears an indicator once the user has seen it.
//
// NO SILENT LOSS, both directions: evidence for a claim this UI never registered is audited on
// `orphans` (never dropped), and every state transition is an append-only `updates` entry.
//
// Pure node built-ins + the project's own Wave-1/2/3 modules. Runs under `node --test test/`.

import { ClaimEventBus, CLAIM_EVENT_TOPIC } from './claim-event-bus.mjs';
import { CLAIM_KIND } from './semantic-classifier.mjs';
import { PipelineRouter, PIPELINE_TOPIC } from './pipeline-router.mjs';
import {
  SANDBOX_TOPIC,
  EVIDENCE_TYPE,
  createLocalSandboxRuntime,
  sandboxAgenticSteps,
} from './sandbox-pipeline.mjs';
import { EXECUTION_OUTCOME } from './wasm-sandbox.mjs';

/** The four Honesty-Law UI states a claim's styling may take. */
export const CLAIM_UI_STATE = Object.freeze({
  PENDING: 'pending',
  VERIFIED: 'verified',
  UNVERIFIED: 'unverified',
  REFUTED: 'refuted',
});

/** The states, as an array (introspection + exhaustiveness checks). */
export const CLAIM_UI_STATES = Object.freeze(Object.values(CLAIM_UI_STATE));

/**
 * The dynamic claim-state styling vocabulary: one frozen descriptor per state. Styling is DERIVED
 * from the state (styleFor), never set directly — so a claim can never wear a tier it did not earn.
 */
export const CLAIM_STATE_STYLE = Object.freeze({
  [CLAIM_UI_STATE.PENDING]: Object.freeze({
    state: CLAIM_UI_STATE.PENDING,
    css_class: 'claim claim--pending',
    glyph: '…',
    label: 'Pending verification',
    tone: 'muted',
    aria_live: 'off',
  }),
  [CLAIM_UI_STATE.VERIFIED]: Object.freeze({
    state: CLAIM_UI_STATE.VERIFIED,
    css_class: 'claim claim--verified',
    glyph: '✓',
    label: 'Verified',
    tone: 'positive',
    aria_live: 'polite',
  }),
  [CLAIM_UI_STATE.UNVERIFIED]: Object.freeze({
    state: CLAIM_UI_STATE.UNVERIFIED,
    css_class: 'claim claim--unverified',
    glyph: '?',
    label: 'Unverified — no certification earned',
    tone: 'caution',
    aria_live: 'polite',
  }),
  [CLAIM_UI_STATE.REFUTED]: Object.freeze({
    state: CLAIM_UI_STATE.REFUTED,
    css_class: 'claim claim--refuted',
    glyph: '✗',
    label: 'Refuted',
    tone: 'negative',
    aria_live: 'assertive',
  }),
});

/** The styling for a state. Throws on an unknown state — styling never guesses. */
export function styleFor(state) {
  const style = CLAIM_STATE_STYLE[state];
  if (!style) {
    throw new Error(`styleFor(): unknown claim UI state ${JSON.stringify(state)} (expected one of ${CLAIM_UI_STATES.join(', ')})`);
  }
  return style;
}

/**
 * THE HONESTY-LAW TIERING RULE — map one structured evidence record (sandbox-pipeline.mjs) to the
 * claim's UI state. VERIFIED requires a COMPLETED execution whose agreement is true; REFUTED
 * requires an actual disagreement; EVERYTHING else — abstentions, traps, terminations, refusals,
 * errors, executions with nothing to compare against — resolves to UNVERIFIED, honestly.
 * @param {object} evidence  a `claim:evidence` payload (evidence_type 'wasm-sandbox-execution').
 * @returns {{state:string, reason:string}} frozen.
 */
export function resolveTier(evidence) {
  if (!evidence || typeof evidence !== 'object') {
    throw new Error('resolveTier(): evidence must be an object (a claim:evidence payload)');
  }
  if (evidence.evidence_type !== EVIDENCE_TYPE) {
    throw new Error(
      `resolveTier(): unrecognized evidence_type ${JSON.stringify(evidence.evidence_type)} — only ${JSON.stringify(EVIDENCE_TYPE)} records may resolve a tier (nothing else may mint a state)`,
    );
  }
  if (evidence.agreement === true && evidence.outcome === EXECUTION_OUTCOME.COMPLETED) {
    return Object.freeze({
      state: CLAIM_UI_STATE.VERIFIED,
      reason: 'the sandbox execution COMPLETED within its enforced limits and the observed value AGREES with the claim — the verified tier is earned by this evidence record',
    });
  }
  if (evidence.agreement === false) {
    return Object.freeze({
      state: CLAIM_UI_STATE.REFUTED,
      reason: 'the sandbox actually executed and the observed value CONTRADICTS the claim — refuted on machine evidence, context attached',
    });
  }
  const why =
    evidence.abstained === true
      ? `the pipeline abstained honestly (${evidence.reason ?? 'no machine-checkable path'})`
      : evidence.error !== null && evidence.error !== undefined
        ? `the runtime adapter errored (${evidence.error})`
        : evidence.outcome === EXECUTION_OUTCOME.COMPLETED
          ? 'the execution completed but the claim declared no expected value — nothing to agree with, so no tier is minted'
          : `the sandbox did not complete the run (outcome: ${evidence.outcome}) — boundaries enforced, nothing verified`;
  return Object.freeze({
    state: CLAIM_UI_STATE.UNVERIFIED,
    reason: `${why}; THE HONESTY LAW holds — an unsettled claim is styled unverified, never promoted`,
  });
}

/**
 * The interactive refuted-claim context: the tooltip (one line, for hover) and the inline block
 * (expandable, for click-through) that surface WHY the claim is refuted and on WHOSE evidence.
 * @param {{statement?:string, computation?:{expected?:string}}} claim   the registered claim payload.
 * @param {object} evidence  the refuting `claim:evidence` record (agreement === false).
 * @returns {{tooltip:string, inline_block:object}} frozen (JSON-safe).
 */
export function buildRefutedContext(claim, evidence) {
  const expected = claim && claim.computation && typeof claim.computation.expected === 'string' ? claim.computation.expected : null;
  const observed = evidence && evidence.execution && evidence.execution.value !== undefined ? String(evidence.execution.value) : null;
  const tooltip = `REFUTED: the claim asserted ${expected ?? 'a value'}; the sandboxed execution observed ${observed ?? 'a contradicting value'}. Click for the full evidence.`;
  return Object.freeze({
    tooltip,
    inline_block: Object.freeze({
      heading: 'Why this claim is refuted',
      statement: claim && typeof claim.statement === 'string' ? claim.statement : null,
      expected,
      observed,
      module_source: evidence.module_source ?? null,
      module_sha256: evidence.module_sha256 ?? null,
      outcome: evidence.outcome ?? null,
      reason: evidence.reason ?? 'expected-vs-observed disagreement on a real sandbox execution',
    }),
  });
}

/** True when a full-stream span overlaps the viewport character range. */
function spanOnScreen(span, viewport) {
  return span.start < viewport.end && span.end > viewport.start;
}

/**
 * The Wave-4 Honesty-Law UI: bus listeners for verification results, dynamic per-claim state
 * styling, interactive refuted context, and off-screen resolution alerts (margin indicators + a
 * global status tray).
 */
export class HonestyLawUI {
  #bus;
  #detach = null;
  /** claim_id -> the mutable internal record (snapshots exposed frozen). */
  #records = new Map();
  /** claim_ids in registration order. */
  #order = [];
  /** Append-only state-transition audit: { claim_id, from, to, tick, on_screen, reason }. */
  #updates = [];
  /** Append-only: events for claims this UI never registered — audited, never dropped. */
  #orphans = [];
  /** Margin indicators for off-screen resolutions (internal mutable `seen` flag). */
  #indicators = [];
  /** The viewport over full-stream span coordinates, or null (everything visible). */
  #viewport = null;
  /** Monotonic logical clock ordering registrations and resolutions. */
  #tick = 0;

  /**
   * @param {{bus: ClaimEventBus}} o  the shared event bus interceptions, routing records, and
   *   structured evidence arrive on.
   */
  constructor({ bus } = {}) {
    if (!bus || typeof bus.subscribe !== 'function' || typeof bus.publish !== 'function') {
      throw new Error('HonestyLawUI: bus must be a ClaimEventBus-like ({subscribe, publish})');
    }
    this.#bus = bus;
  }

  /**
   * Attach the UI listeners: `claim:intercepted` (register as PENDING), `claim:routed` (annotate
   * placement), `claim:evidence` (THE verification-result listener — resolve the tier). Returns
   * the detach function; attaching twice without detaching throws (double-counting guard).
   */
  attach() {
    if (this.#detach) {
      throw new Error('attach(): the UI is already attached — detach() it first (double-listener guard)');
    }
    const offs = [
      this.#bus.subscribe(CLAIM_EVENT_TOPIC.INTERCEPTED, (event) => this.#onIntercepted(event)),
      this.#bus.subscribe(PIPELINE_TOPIC.ROUTED, (event) => this.#onRouted(event)),
      this.#bus.subscribe(SANDBOX_TOPIC.EVIDENCE, (event) => this.#onEvidence(event)),
    ];
    this.#detach = () => {
      for (const off of offs) off();
      this.#detach = null;
    };
    return this.#detach;
  }

  /** Detach all UI listeners (idempotent). */
  detach() {
    if (this.#detach) this.#detach();
  }

  /** True while the UI listeners are subscribed. */
  get attached() {
    return this.#detach !== null;
  }

  // --- visibility -----------------------------------------------------------

  /**
   * Set (or clear, with null) the viewport as a character range over full-stream span coordinates.
   * Claims carrying a span recompute their visibility; claims without a span default to visible.
   * Explicit markOnScreen/markOffScreen overrides survive viewport changes.
   */
  setViewport(viewport) {
    if (viewport !== null) {
      if (
        !viewport ||
        typeof viewport !== 'object' ||
        !Number.isFinite(viewport.start) ||
        !Number.isFinite(viewport.end) ||
        viewport.end < viewport.start
      ) {
        throw new Error('setViewport(): viewport must be null or { start:number, end:number } with end >= start');
      }
      this.#viewport = Object.freeze({ start: viewport.start, end: viewport.end });
    } else {
      this.#viewport = null;
    }
    for (const record of this.#records.values()) {
      record.on_screen = this.#computeOnScreen(record);
    }
  }

  /** The current viewport (frozen) or null. */
  get viewport() {
    return this.#viewport;
  }

  /** Explicitly mark a claim off-screen (e.g. a collapsed section) — overrides the viewport. */
  markOffScreen(claimId) {
    const record = this.#require(claimId, 'markOffScreen()');
    record.visibility_override = false;
    record.on_screen = false;
  }

  /** Explicitly mark a claim on-screen — overrides the viewport. */
  markOnScreen(claimId) {
    const record = this.#require(claimId, 'markOnScreen()');
    record.visibility_override = true;
    record.on_screen = true;
  }

  #computeOnScreen(record) {
    if (record.visibility_override !== null) return record.visibility_override;
    if (this.#viewport && record.span) return spanOnScreen(record.span, this.#viewport);
    return true;
  }

  // --- listeners ------------------------------------------------------------

  /** Register one intercepted claim: THE ONLY ENTRY STATE IS PENDING. */
  #onIntercepted(event) {
    const payload = event && typeof event === 'object' ? event.payload : undefined;
    if (!payload || typeof payload !== 'object' || typeof payload.id !== 'string') {
      this.#orphans.push(Object.freeze({ topic: event?.topic ?? null, payload, reason: 'intercepted payload without a string id — not registrable, audited' }));
      return;
    }
    if (this.#records.has(payload.id)) {
      this.#orphans.push(Object.freeze({ topic: event.topic, payload, reason: `duplicate interception for ${payload.id} — the first registration stands, audited` }));
      return;
    }
    const record = {
      claim_id: payload.id,
      claim: payload,
      statement: typeof payload.statement === 'string' ? payload.statement : null,
      span: payload.span && Number.isFinite(payload.span.start) && Number.isFinite(payload.span.end) ? Object.freeze({ start: payload.span.start, end: payload.span.end }) : null,
      state: CLAIM_UI_STATE.PENDING,
      style: styleFor(CLAIM_UI_STATE.PENDING),
      pipeline: null,
      lane: null,
      evidence: null,
      resolution_reason: null,
      context: null,
      context_expanded: false,
      visibility_override: null,
      on_screen: true,
      registered_tick: ++this.#tick,
      resolved_tick: null,
      history: [],
    };
    record.on_screen = this.#computeOnScreen(record);
    this.#records.set(record.claim_id, record);
    this.#order.push(record.claim_id);
    this.#transition(record, CLAIM_UI_STATE.PENDING, 'intercepted — verification dispatched asynchronously; styled pending until evidence arrives');
  }

  /** Annotate the routed pipeline placement (the claim stays PENDING — routing is not evidence). */
  #onRouted(event) {
    const payload = event && typeof event === 'object' ? event.payload : undefined;
    const record = payload && typeof payload.claim_id === 'string' ? this.#records.get(payload.claim_id) : undefined;
    if (!record) {
      this.#orphans.push(Object.freeze({ topic: event?.topic ?? null, payload, reason: 'routed record for a claim this UI never registered — audited, never dropped' }));
      return;
    }
    record.pipeline = payload.pipeline ?? null;
    record.lane = payload.lane ?? null;
  }

  /** THE VERIFICATION-RESULT LISTENER: resolve one evidence record to the claim's Honesty-Law tier. */
  #onEvidence(event) {
    const evidence = event && typeof event === 'object' ? event.payload : undefined;
    if (!evidence || typeof evidence !== 'object' || evidence.evidence_type !== EVIDENCE_TYPE) {
      this.#orphans.push(Object.freeze({ topic: event?.topic ?? null, payload: evidence, reason: 'non-evidence payload on the evidence topic — nothing may mint a state from it, audited' }));
      return;
    }
    const record = typeof evidence.claim_id === 'string' ? this.#records.get(evidence.claim_id) : undefined;
    if (!record) {
      this.#orphans.push(Object.freeze({ topic: event.topic, payload: evidence, reason: `evidence for ${JSON.stringify(evidence.claim_id ?? null)} — no registered claim; audited, never dropped` }));
      return;
    }
    const { state, reason } = resolveTier(evidence);
    record.evidence = evidence;
    record.resolution_reason = reason;
    record.context = state === CLAIM_UI_STATE.REFUTED ? buildRefutedContext(record.claim, evidence) : null;
    if (state !== CLAIM_UI_STATE.REFUTED) record.context_expanded = false;
    this.#transition(record, state, reason);
    record.resolved_tick = record.history[record.history.length - 1].tick;
    if (!record.on_screen) {
      // THE OFF-SCREEN ARM OF THE DONE-WHEN: the state still updated dynamically above; now alert
      // the user that a change happened where they cannot see it.
      this.#indicators.push({
        claim_id: record.claim_id,
        state,
        statement: record.statement,
        span: record.span,
        glyph: record.style.glyph,
        label: record.style.label,
        seen: false,
        tick: record.resolved_tick,
      });
    }
  }

  /** Apply one state transition: restyle from the state (never independently) + audit the update. */
  #transition(record, to, reason) {
    const from = record.history.length === 0 ? null : record.state;
    record.state = to;
    record.style = styleFor(to);
    const entry = Object.freeze({ claim_id: record.claim_id, from, to, tick: ++this.#tick, on_screen: record.on_screen, reason });
    record.history.push(entry);
    this.#updates.push(entry);
  }

  #require(claimId, fn) {
    const record = this.#records.get(claimId);
    if (!record) throw new Error(`${fn}: unknown claim_id ${JSON.stringify(claimId)}`);
    return record;
  }

  // --- interactivity ---------------------------------------------------------

  /**
   * Toggle the refuted claim's expandable inline context block (the click-through). Returns the
   * frozen context with the new expanded flag. Only a REFUTED claim carries context — toggling
   * anything else is a UI wiring bug and throws.
   */
  toggleContext(claimId) {
    const record = this.#require(claimId, 'toggleContext()');
    if (record.state !== CLAIM_UI_STATE.REFUTED || !record.context) {
      throw new Error(`toggleContext(): claim ${claimId} is ${record.state} — only a refuted claim carries interactive context`);
    }
    record.context_expanded = !record.context_expanded;
    return Object.freeze({ expanded: record.context_expanded, ...record.context });
  }

  /**
   * Acknowledge one off-screen resolution: the user saw the margin indicator (clicked / scrolled
   * to it). Marks every indicator for the claim seen; returns how many were newly acknowledged.
   */
  acknowledge(claimId) {
    this.#require(claimId, 'acknowledge()');
    let acknowledged = 0;
    for (const indicator of this.#indicators) {
      if (indicator.claim_id === claimId && !indicator.seen) {
        indicator.seen = true;
        acknowledged += 1;
      }
    }
    return acknowledged;
  }

  // --- read model -------------------------------------------------------------

  /** One claim's frozen UI snapshot (null when unknown). */
  claim(claimId) {
    const record = this.#records.get(claimId);
    if (!record) return null;
    return Object.freeze({
      claim_id: record.claim_id,
      statement: record.statement,
      span: record.span,
      state: record.state,
      style: record.style,
      pipeline: record.pipeline,
      lane: record.lane,
      evidence: record.evidence,
      resolution_reason: record.resolution_reason,
      context: record.context,
      context_expanded: record.context_expanded,
      on_screen: record.on_screen,
      registered_tick: record.registered_tick,
      resolved_tick: record.resolved_tick,
      history: Object.freeze([...record.history]),
    });
  }

  /** Every claim's frozen snapshot, in registration order. */
  get claims() {
    return Object.freeze(this.#order.map((id) => this.claim(id)));
  }

  /** The append-only state-transition audit (frozen copy). */
  get updates() {
    return Object.freeze([...this.#updates]);
  }

  /** Events that matched no registered claim (frozen copy) — audited, never silently dropped. */
  get orphans() {
    return Object.freeze([...this.#orphans]);
  }

  /** Margin indicators for off-screen resolutions (frozen snapshots, oldest first). */
  get marginIndicators() {
    return Object.freeze(this.#indicators.map((i) => Object.freeze({ ...i })));
  }

  /**
   * THE GLOBAL STATUS TRAY: per-state claim counts + the unseen off-screen update tally the tray
   * badge shows.
   */
  get statusTray() {
    const counts = { pending: 0, verified: 0, unverified: 0, refuted: 0 };
    for (const record of this.#records.values()) counts[record.state] += 1;
    const unseen = this.#indicators.filter((i) => !i.seen);
    return Object.freeze({
      total: this.#records.size,
      counts: Object.freeze(counts),
      unseen_offscreen_updates: unseen.length,
      unseen: Object.freeze(unseen.map((i) => Object.freeze({ ...i }))),
    });
  }

  /**
   * THE HONESTY LAW, MEASURED: every VERIFIED claim earned it from a COMPLETED execution whose
   * agreement is true (never an abstention, never a caller assertion); every claim wears EXACTLY
   * the style of its earned state (styling can never drift from the tiering); every REFUTED claim
   * carries its interactive context.
   */
  get honestyLawHolds() {
    for (const record of this.#records.values()) {
      if (record.style !== styleFor(record.state)) return false;
      if (record.state === CLAIM_UI_STATE.VERIFIED) {
        const ev = record.evidence;
        if (!ev || ev.evidence_type !== EVIDENCE_TYPE || ev.agreement !== true || ev.outcome !== EXECUTION_OUTCOME.COMPLETED || ev.abstained === true) {
          return false;
        }
      }
      if (record.state === CLAIM_UI_STATE.REFUTED && (!record.context || !record.evidence || record.evidence.agreement !== false)) {
        return false;
      }
    }
    return true;
  }

  // --- rendering ---------------------------------------------------------------

  /**
   * Render one claim line from its EARNED style (glyph + label + statement); a refuted claim
   * appends its tooltip, and — when expanded — the inline context block.
   */
  renderClaim(claimId) {
    const record = this.#require(claimId, 'renderClaim()');
    const lines = [`${record.style.glyph} [${record.style.label}] ${record.statement ?? record.claim_id}`];
    if (record.context) {
      lines.push(`  ⓘ ${record.context.tooltip}`);
      if (record.context_expanded) {
        const block = record.context.inline_block;
        lines.push(`  ┌ ${block.heading}`);
        lines.push(`  │ expected: ${block.expected ?? '—'}  observed: ${block.observed ?? '—'}`);
        lines.push(`  │ executed: ${block.module_source ?? '—'} (sha256 ${block.module_sha256 ?? '—'})`);
        lines.push(`  └ ${block.reason}`);
      }
    }
    return lines.join('\n');
  }
}

// ---------------------------------------------------------------------------
// THE FIXTURE — the full Wave-1 -> Wave-4 flow: intercepted claims route by complexity, the WASM
// sandbox executes/abstains, and the Honesty-Law UI resolves every claim's visual state from the
// evidence — including a REFUTED claim that is OFF-SCREEN when its result arrives (the done-when's
// Given/When/Then, measured).
// ---------------------------------------------------------------------------

/**
 * Four span-bearing intercepted-claim payloads covering every Honesty-Law tier: a true computation
 * (-> verified), a FALSE computation placed far down-stream / off-screen (-> refuted + margin
 * indicator), a proof-bearing claim (certify defers -> unverified), and an empirical claim
 * (Pillar-7 lane abstains here -> unverified).
 */
export const HONESTY_UI_CLAIM_FIXTURE = Object.freeze([
  Object.freeze({
    id: 'wave4-verified',
    kind: CLAIM_KIND.MATHEMATICAL,
    claim_type: 'computational',
    statement: 'The sum of 2 and 2 equals 4.',
    span: Object.freeze({ start: 0, end: 28 }),
    computation: Object.freeze({ op: 'add', args: Object.freeze(['2', '2']), expected: '4' }),
  }),
  Object.freeze({
    id: 'wave4-refuted',
    kind: CLAIM_KIND.MATHEMATICAL,
    claim_type: 'computational',
    statement: 'The sum of 2 and 2 equals 5.',
    span: Object.freeze({ start: 500, end: 528 }),
    computation: Object.freeze({ op: 'add', args: Object.freeze(['2', '2']), expected: '5' }),
  }),
  Object.freeze({
    id: 'wave4-proof',
    kind: CLAIM_KIND.MATHEMATICAL,
    claim_type: 'proof-bearing',
    statement: 'Every even integer greater than 2 is the sum of two primes.',
    span: Object.freeze({ start: 529, end: 589 }),
  }),
  Object.freeze({
    id: 'wave4-empirical',
    kind: CLAIM_KIND.EMPIRICAL,
    claim_type: null,
    statement: 'We benchmarked the sieve and it averaged 40 milliseconds per run.',
    span: Object.freeze({ start: 29, end: 95 }),
  }),
]);

/** The fixture viewport: the first two spans are visible; the refuted + proof claims are off-screen. */
export const HONESTY_UI_VIEWPORT = Object.freeze({ start: 0, end: 120 });

/**
 * Drive the fixture end-to-end (bus -> router -> sandbox -> evidence -> Honesty-Law UI). Returns
 * the parts + the wave's done-when invariants, measured.
 */
export async function runHonestyUiFixture() {
  const bus = new ClaimEventBus();
  const ui = new HonestyLawUI({ bus });
  ui.attach();
  ui.setViewport(HONESTY_UI_VIEWPORT);

  const router = new PipelineRouter({
    bus,
    runtime: createLocalSandboxRuntime({ bus }),
    steps: sandboxAgenticSteps({ bus }),
  });
  router.attach();

  for (const payload of HONESTY_UI_CLAIM_FIXTURE) bus.publish(CLAIM_EVENT_TOPIC.INTERCEPTED, payload);
  await router.settle();
  await bus.settle();

  const verified = ui.claim('wave4-verified');
  const refuted = ui.claim('wave4-refuted');
  const proof = ui.claim('wave4-proof');
  const empirical = ui.claim('wave4-empirical');
  const all = [verified, refuted, proof, empirical];
  const tray = ui.statusTray;

  return Object.freeze({
    bus,
    router,
    ui,
    verified,
    refuted,
    proof,
    empirical,
    tray,
    // THE DONE-WHEN, measured:
    // ...every claim ENTERED pending and was resolved DYNAMICALLY (strictly after registration)...
    everyClaimResolvedDynamically: all.every(
      (c) => c && c.history[0].to === CLAIM_UI_STATE.PENDING && c.resolved_tick !== null && c.resolved_tick > c.registered_tick,
    ),
    // ...to its final Honesty-Law tier, reflected in the UI state AND its derived styling...
    statesReflectHonestyTiers: Boolean(
      verified &&
        verified.state === CLAIM_UI_STATE.VERIFIED &&
        refuted &&
        refuted.state === CLAIM_UI_STATE.REFUTED &&
        proof &&
        proof.state === CLAIM_UI_STATE.UNVERIFIED &&
        empirical &&
        empirical.state === CLAIM_UI_STATE.UNVERIFIED &&
        all.every((c) => c.style === styleFor(c.state)),
    ),
    // ...the refuted claim SURFACES its interactive context (tooltip + inline block)...
    refutedContextSurfaced: Boolean(
      refuted &&
        refuted.context &&
        refuted.context.tooltip.includes('REFUTED') &&
        refuted.context.inline_block.expected === '5' &&
        refuted.context.inline_block.observed === '4' &&
        refuted.context.inline_block.module_sha256,
    ),
    // ...and the OFF-SCREEN resolution raised a margin indicator + a global status-tray alert.
    offScreenAlerted: Boolean(
      refuted &&
        refuted.on_screen === false &&
        ui.marginIndicators.some((i) => i.claim_id === 'wave4-refuted' && i.state === CLAIM_UI_STATE.REFUTED && !i.seen) &&
        tray.unseen_offscreen_updates > 0,
    ),
    // THE HONESTY LAW, measured across every record: verified only when earned, styling never drifts.
    honestyLawEnforced: ui.honestyLawHolds,
  });
}
