// transport.test.mjs — Wave 7 pre-registered measurements (1) exit-class taxonomy
// and (2) per-call telemetry schema. Pure + deterministic (no spawn, no model).
// Run with: node --test test/transport.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  EXIT_CLASSES, classifyExit, isExitClass,
  TELEMETRY_FIELDS, TELEMETRY_KEYS, validateTelemetry, makeTelemetryRecord,
} from '../bin/transport.mjs';

// ---------------------------------------------------------------------------
// (1) exit-class taxonomy — every outcome maps to exactly one NAMED class.
// ---------------------------------------------------------------------------

test('taxonomy: each transport outcome classifies to its specific named class', () => {
  // clean success
  assert.equal(classifyExit({ code: 0, finalEnv: { is_error: false } }).class, EXIT_CLASSES.OK);
  // CLI-reported error in the result envelope
  assert.equal(classifyExit({ code: 0, finalEnv: { is_error: true, subtype: 'error_max_turns' } }).class,
    EXIT_CLASSES.ERROR_RESULT);
  // our per-call timeout fired (SIGKILL) — even though a close-signal also arrives
  assert.equal(classifyExit({ timedOut: true, signal: 'SIGKILL', code: null }).class,
    EXIT_CLASSES.TIMEOUT_KILLED);
  // an EXTERNAL signal we did not raise
  assert.equal(classifyExit({ signal: 'SIGTERM', code: null }).class, EXIT_CLASSES.SIGNAL_KILLED);
  // exited 0 but no result envelope arrived (truncated stream)
  assert.equal(classifyExit({ code: 0, finalEnv: null }).class, EXIT_CLASSES.NO_RESULT_ENVELOPE);
  // genuine non-zero exit, no envelope
  assert.equal(classifyExit({ code: 1, finalEnv: null }).class, EXIT_CLASSES.NONZERO_EXIT);
  // spawn itself threw (binary missing)
  assert.equal(classifyExit({ spawnError: Object.assign(new Error('not found'), { code: 'ENOENT' }) }).class,
    EXIT_CLASSES.SPAWN_FAILED);
});

test('taxonomy: classifyExit is TOTAL — always a named class, never null/undefined', () => {
  const inputs = [
    {}, { code: 0 }, { code: 137 }, { code: null, signal: null },
    { timedOut: true }, { signal: 'SIGKILL' }, { finalEnv: {} },
    { code: 0, finalEnv: { is_error: false } }, { spawnError: new Error('x') },
    { code: undefined, signal: undefined }, // truly degenerate
  ];
  for (const inp of inputs) {
    const c = classifyExit(inp);
    assert.ok(c && typeof c === 'object', `classifyExit(${JSON.stringify(inp)}) returned a record`);
    assert.equal(isExitClass(c.class), true, `class "${c.class}" is a named taxonomy class (no unclassified exit)`);
    assert.equal(typeof c.recoverable, 'boolean');
    assert.equal(typeof c.detail, 'string');
  }
  // only the truly degenerate (no code, no signal, no envelope) reaches the backstop
  assert.equal(classifyExit({ code: null, signal: null }).class, EXIT_CLASSES.UNKNOWN);
});

test('taxonomy: timeout takes priority over the generic signal branch', () => {
  // our timeout SIGKILLs and the close reports SIGKILL — must read as timeout, not signal-killed
  const c = classifyExit({ timedOut: true, signal: 'SIGKILL', code: null });
  assert.equal(c.class, EXIT_CLASSES.TIMEOUT_KILLED);
  assert.equal(c.recoverable, true, 'a timeout is retryable');
});

test('taxonomy: recoverable flags — transport faults retryable, real failures not', () => {
  assert.equal(classifyExit({ timedOut: true }).recoverable, true);
  assert.equal(classifyExit({ signal: 'SIGKILL' }).recoverable, true);
  assert.equal(classifyExit({ code: 0, finalEnv: null }).recoverable, true);  // truncated stream
  assert.equal(classifyExit({ code: 0, finalEnv: { is_error: false } }).recoverable, false); // success isn't "retry"
  assert.equal(classifyExit({ code: 1, finalEnv: null }).recoverable, false); // genuine failure
  assert.equal(classifyExit({ spawnError: new Error('x') }).recoverable, false); // config fault
});

// ---------------------------------------------------------------------------
// (2) per-call telemetry schema.
// ---------------------------------------------------------------------------

test('telemetry schema: makeTelemetryRecord builds a schema-valid, attested record', () => {
  const rec = makeTelemetryRecord({
    label: 'execute',
    classification: classifyExit({ code: 0, finalEnv: { is_error: false } }),
    cli_status: 0, signal: null, duration_ms: 1234, tools: 5,
    output_tokens: 800, cost_usd: 0.12, permission_denials: 0,
    servedModel: 'claude-opus-4-8',
  });
  // every schema key present
  for (const k of TELEMETRY_KEYS) assert.ok(k in rec, `record carries ${k}`);
  assert.equal(rec.exit_class, EXIT_CLASSES.OK);
  assert.equal(rec.ok, true);
  assert.equal(rec.timed_out, false);
  assert.equal(rec.model_served, 'claude-opus-4-8');
  assert.equal(rec.model_attested, true);
  assert.equal(rec.degraded, false);
  assert.doesNotThrow(() => validateTelemetry(rec));
});

test('telemetry schema: a missing served model DEGRADES the SR-5 stamp but stays valid', () => {
  const rec = makeTelemetryRecord({
    label: 'review',
    classification: classifyExit({ timedOut: true, signal: 'SIGKILL' }),
    cli_status: null, signal: 'SIGKILL', servedModel: null,
  });
  assert.equal(rec.exit_class, EXIT_CLASSES.TIMEOUT_KILLED);
  assert.equal(rec.timed_out, true);
  assert.equal(rec.ok, false);
  assert.equal(rec.model_attested, false);
  assert.equal(rec.degraded, true);
  assert.equal(rec.model_served, null);
  assert.doesNotThrow(() => validateTelemetry(rec));
});

test('telemetry schema: validateTelemetry REJECTS drift (missing field, bad type, bad class, bad attest)', () => {
  const good = makeTelemetryRecord({
    label: 'fix', classification: classifyExit({ code: 0, finalEnv: { is_error: false } }),
    servedModel: 'claude-opus-4-8',
  });
  const noClass = { ...good }; delete noClass.exit_class;
  assert.throws(() => validateTelemetry(noClass), /missing required field: exit_class/);
  assert.throws(() => validateTelemetry({ ...good, exit_class: 'made-up-class' }), /not a known taxonomy class/);
  assert.throws(() => validateTelemetry({ ...good, tools: 'five' }), /tools has wrong type/);
  assert.throws(() => validateTelemetry({ ...good, label: null }), /label must not be null/);
  // half-formed attestation (attested:true but no served model) must be rejected
  assert.throws(() => validateTelemetry({ ...good, model_attested: true, model_served: null, degraded: false }),
    /no well-formed SR-5 attestation/);
  assert.throws(() => validateTelemetry(null), /not a plain object/);
});

test('telemetry schema: nullable transport fields may be null (signal-killed has no exit code)', () => {
  const rec = makeTelemetryRecord({
    label: 'execute', classification: classifyExit({ signal: 'SIGTERM' }),
    cli_status: null, signal: 'SIGTERM', duration_ms: null,
    output_tokens: null, cost_usd: null, permission_denials: null, servedModel: null,
  });
  assert.equal(rec.cli_status, null);
  assert.equal(rec.exit_class, EXIT_CLASSES.SIGNAL_KILLED);
  assert.doesNotThrow(() => validateTelemetry(rec));
  // but a non-nullable field (tools) defaults to a number, never null
  assert.equal(typeof rec.tools, 'number');
  // schema marks the right fields nullable
  assert.equal(TELEMETRY_FIELDS.cli_status.nullable, true);
  assert.equal(TELEMETRY_FIELDS.ok.nullable, false);
});
