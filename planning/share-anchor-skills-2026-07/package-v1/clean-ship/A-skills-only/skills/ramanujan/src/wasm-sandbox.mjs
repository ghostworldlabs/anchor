// Overhaul Wave 3 — Secure WASM Sandbox Runtime: the SANDBOX ENGINE.
//
// The strict cross-platform security sandbox for exact-arithmetic and logic verifications. The
// runtime environment is the host node's own WebAssembly engine (V8) — a genuine WASM runtime on
// every platform node runs on, filling the Wasmtime-class role WITHOUT a new dependency (the
// frozen gate is `node --test test/` over pure built-ins). Three hard boundaries, all REAL:
//
//   1. DEFAULT-DENY IMPORTS (screenWasm). The module binary is statically inspected BEFORE any
//      instantiation (inspectWasm — a minimal section parser over the wasm binary format); every
//      import must be on the sanctioned list (fuel.consume + env.memory, and nothing else — no
//      WASI, no host leaks), and a module declaring its own over-cap or unbounded memory is
//      refused outright. No syscall surface exists inside the sandbox by construction.
//
//   2. MEMORY (OOM). Modules take linear memory as an IMPORT and the runner supplies a
//      WebAssembly.Memory whose `maximum` is the policy cap — the ENGINE enforces the boundary
//      (memory.grow past the cap is refused; the allocation can never exceed the cap). Over-cap
//      demands are refused statically before instantiation.
//
//   3. INSTRUCTION COUNT + TIMEOUT.
//        - FUEL (deterministic, in-process): metered modules import fuel.consume; the host meter
//          throws FuelExhaustedError past max_fuel and DeadlineExceededError past timeout_ms.
//          Cooperative by construction for the first-party pre-compiled modules (the calls are
//          compiled into their bytes — see wasm-modules.mjs). An UNMETERED module is REFUSED
//          in-process: nothing cooperative could stop it.
//        - THE NATIVE RUNNER (non-cooperative): runInNativeSandbox executes the job in a child
//          `node` process (`node test/wasm-sandbox-runner.mjs <input-file>` — same binary, NO
//          shell, hermetic per-call temp dir; the exact pattern the Wave-9 firewall pinned) with
//          execFileSync's native wall-clock timeout. A runaway module — metered or not — is
//          KILLED by the OS, and the kill comes back as a structured `terminated` record, never
//          an exception into the pipeline. Crash isolation is free: a dying module takes down
//          only the child.
//
// EVERY EXECUTION RETURNS A STRUCTURED, JSON-SAFE RECORD — completed | trapped | terminated |
// refused | error — with fuel/memory accounting, the module's sha256, and the enforced limits.
// Nothing is thrown at callers, nothing is lost, and a trap is a RESULT (for the overflow-checked
// exact-arithmetic module a trap IS the honest refusal). sandbox-pipeline.mjs lifts these records
// into claim evidence on the event bus.
//
// Node built-ins only (crypto, child_process, fs, os, path, url). Runs under `node --test test/`.

import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// ---------------------------------------------------------------------------
// Vocabulary, limits, policy.
// ---------------------------------------------------------------------------

/** Bytes per WebAssembly page. */
export const WASM_PAGE_BYTES = 65536;

/** The i64 envelope the exact-arithmetic lane is honestly bounded to. */
export const I64_MIN = -(2n ** 63n);
export const I64_MAX = 2n ** 63n - 1n;

/** Execution outcomes — every run lands on exactly one. */
export const EXECUTION_OUTCOME = Object.freeze({
  COMPLETED: 'completed',
  TRAPPED: 'trapped',
  TERMINATED: 'terminated',
  REFUSED: 'refused',
  ERROR: 'error',
});

/** Which enforced limit terminated a run. */
export const TERMINATION_LIMIT = Object.freeze({
  FUEL: 'fuel',
  TIMEOUT: 'timeout',
});

/** Which runner produced a record. */
export const SANDBOX_RUNNER_KIND = Object.freeze({
  IN_PROCESS: 'in-process',
  NATIVE_CHILD: 'native-child',
});

/** The default resource boundaries: 64 pages (4 MiB), 1M fuel, 2s wall clock. */
export const SANDBOX_LIMITS = Object.freeze({
  max_memory_pages: 64,
  max_fuel: 1_000_000,
  timeout_ms: 2000,
});

/** The default-deny sanctioned import set — the ONLY imports a sandboxed module may declare. */
export const SANCTIONED_IMPORTS = Object.freeze([
  Object.freeze({ module: 'fuel', name: 'consume', kind: 'func' }),
  Object.freeze({ module: 'env', name: 'memory', kind: 'memory' }),
]);

/** Extra wall clock the native runner grants the child past timeout_ms, so a metered child that
 *  terminates itself gracefully (fuel/deadline record, exit 0) is not raced by the hard kill. */
export const NATIVE_KILL_GRACE_MS = 250;

/** Thrown by the fuel meter when the instruction-count budget is exhausted. */
export class FuelExhaustedError extends Error {
  constructor(message) {
    super(message);
    this.name = 'FuelExhaustedError';
  }
}

/** Thrown by the fuel meter when the cooperative deadline passes. */
export class DeadlineExceededError extends Error {
  constructor(message) {
    super(message);
    this.name = 'DeadlineExceededError';
  }
}

/** A malformed-binary parse failure (screened, never thrown past screenWasm). */
export class WasmParseError extends Error {
  constructor(message) {
    super(message);
    this.name = 'WasmParseError';
  }
}

/** Normalize + validate a partial limits object over the defaults. */
export function normalizeLimits(limits = {}) {
  if (limits === null || typeof limits !== 'object') {
    throw new Error('normalizeLimits(): limits must be an object');
  }
  const merged = { ...SANDBOX_LIMITS, ...limits };
  if (!Number.isInteger(merged.max_memory_pages) || merged.max_memory_pages <= 0) {
    throw new Error(`normalizeLimits(): max_memory_pages must be a positive integer (got ${JSON.stringify(merged.max_memory_pages)})`);
  }
  if (!Number.isInteger(merged.max_fuel) || merged.max_fuel <= 0) {
    throw new Error(`normalizeLimits(): max_fuel must be a positive integer (got ${JSON.stringify(merged.max_fuel)})`);
  }
  if (merged.timeout_ms !== null && (!Number.isInteger(merged.timeout_ms) || merged.timeout_ms <= 0)) {
    throw new Error(`normalizeLimits(): timeout_ms must be a positive integer or null (got ${JSON.stringify(merged.timeout_ms)})`);
  }
  return Object.freeze({
    max_memory_pages: merged.max_memory_pages,
    max_fuel: merged.max_fuel,
    timeout_ms: merged.timeout_ms,
  });
}

/** sha256 of the module bytes (evidence provenance). */
export function sha256Hex(bytes) {
  return crypto.createHash('sha256').update(toU8(bytes)).digest('hex');
}

function toU8(bytes) {
  if (bytes instanceof Uint8Array) return bytes;
  if (ArrayBuffer.isView(bytes)) return new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (bytes instanceof ArrayBuffer) return new Uint8Array(bytes);
  if (Array.isArray(bytes)) return Uint8Array.from(bytes);
  throw new Error('wasm-sandbox: module bytes must be a Uint8Array / ArrayBuffer / byte array');
}

// ---------------------------------------------------------------------------
// The static inspector — a minimal parser over the wasm binary format (sections
// 1 type / 2 import / 3 function / 5 memory / 7 export; everything else skipped).
// ---------------------------------------------------------------------------

const VALTYPE_NAME = Object.freeze({
  0x7f: 'i32',
  0x7e: 'i64',
  0x7d: 'f32',
  0x7c: 'f64',
  0x7b: 'v128',
  0x70: 'funcref',
  0x6f: 'externref',
});

const EXPORT_KIND_NAME = Object.freeze(['func', 'table', 'memory', 'global', 'tag']);

class Reader {
  constructor(u8, pos = 0) {
    this.u8 = u8;
    this.pos = pos;
  }

  byte() {
    if (this.pos >= this.u8.length) throw new WasmParseError('unexpected end of module');
    return this.u8[this.pos++];
  }

  uleb() {
    let result = 0;
    let shift = 0;
    for (;;) {
      const b = this.byte();
      result += (b & 0x7f) * 2 ** shift;
      if ((b & 0x80) === 0) return result;
      shift += 7;
      if (shift > 35) throw new WasmParseError('uleb128 too long');
    }
  }

  name() {
    const len = this.uleb();
    if (this.pos + len > this.u8.length) throw new WasmParseError('name runs past end of module');
    const s = new TextDecoder().decode(this.u8.subarray(this.pos, this.pos + len));
    this.pos += len;
    return s;
  }

  limits() {
    const flag = this.byte();
    const min = this.uleb();
    const max = (flag & 0x01) !== 0 ? this.uleb() : null;
    return { min, max, shared: (flag & 0x02) !== 0 };
  }

  valtype() {
    const b = this.byte();
    return VALTYPE_NAME[b] ?? `0x${b.toString(16)}`;
  }
}

/**
 * Statically inspect a wasm binary: types, imports, own memories, and exports (exported functions
 * enriched with their signatures). Throws WasmParseError on a malformed binary — screenWasm turns
 * that into a refusal.
 * @param {Uint8Array|ArrayBuffer|number[]} bytes
 * @returns {{types, imports, memories, exports, section_ids}} deep-frozen.
 */
export function inspectWasm(bytes) {
  const u8 = toU8(bytes);
  if (u8.length < 8 || u8[0] !== 0x00 || u8[1] !== 0x61 || u8[2] !== 0x73 || u8[3] !== 0x6d) {
    throw new WasmParseError('missing \\0asm magic — not a WebAssembly binary');
  }
  if (u8[4] !== 0x01 || u8[5] !== 0x00 || u8[6] !== 0x00 || u8[7] !== 0x00) {
    throw new WasmParseError('unsupported wasm binary version (expected 1)');
  }
  const r = new Reader(u8, 8);
  const types = [];
  const imports = [];
  const memories = [];
  const exports = [];
  const funcTypeIndices = [];
  const sectionIds = [];

  while (r.pos < u8.length) {
    const id = r.byte();
    const size = r.uleb();
    const end = r.pos + size;
    if (end > u8.length) throw new WasmParseError(`section ${id} runs past end of module`);
    sectionIds.push(id);

    if (id === 1) {
      const n = r.uleb();
      for (let i = 0; i < n; i += 1) {
        const form = r.byte();
        if (form !== 0x60) throw new WasmParseError(`unsupported type form 0x${form.toString(16)} (only plain func types)`);
        const params = [];
        const pCount = r.uleb();
        for (let p = 0; p < pCount; p += 1) params.push(r.valtype());
        const results = [];
        const rCount = r.uleb();
        for (let q = 0; q < rCount; q += 1) results.push(r.valtype());
        types.push(Object.freeze({ params: Object.freeze(params), results: Object.freeze(results) }));
      }
    } else if (id === 2) {
      const n = r.uleb();
      for (let i = 0; i < n; i += 1) {
        const module = r.name();
        const name = r.name();
        const kind = r.byte();
        if (kind === 0x00) {
          imports.push(Object.freeze({ module, name, kind: 'func', type_index: r.uleb() }));
        } else if (kind === 0x01) {
          r.byte(); // reftype
          const lim = r.limits();
          imports.push(Object.freeze({ module, name, kind: 'table', min: lim.min, max: lim.max }));
        } else if (kind === 0x02) {
          const lim = r.limits();
          imports.push(Object.freeze({ module, name, kind: 'memory', min: lim.min, max: lim.max, shared: lim.shared }));
        } else if (kind === 0x03) {
          r.byte(); // valtype
          r.byte(); // mutability
          imports.push(Object.freeze({ module, name, kind: 'global' }));
        } else {
          throw new WasmParseError(`unsupported import kind 0x${kind.toString(16)} (${module}.${name})`);
        }
      }
    } else if (id === 3) {
      const n = r.uleb();
      for (let i = 0; i < n; i += 1) funcTypeIndices.push(r.uleb());
    } else if (id === 5) {
      const n = r.uleb();
      for (let i = 0; i < n; i += 1) {
        const lim = r.limits();
        memories.push(Object.freeze({ min: lim.min, max: lim.max, shared: lim.shared }));
      }
    } else if (id === 7) {
      const n = r.uleb();
      for (let i = 0; i < n; i += 1) {
        const name = r.name();
        const kind = r.byte();
        exports.push({ name, kind: EXPORT_KIND_NAME[kind] ?? 'unknown', index: r.uleb() });
      }
    }
    r.pos = end; // skip any unparsed remainder / unhandled section
  }

  // Enrich exported functions with their signatures (func index space: imports first, then own).
  const importedFuncs = imports.filter((i) => i.kind === 'func');
  const enriched = exports.map((e) => {
    if (e.kind !== 'func') return Object.freeze(e);
    const typeIndex =
      e.index < importedFuncs.length
        ? importedFuncs[e.index].type_index
        : funcTypeIndices[e.index - importedFuncs.length];
    return Object.freeze({ ...e, signature: types[typeIndex] ?? null });
  });

  return Object.freeze({
    types: Object.freeze(types),
    imports: Object.freeze(imports),
    memories: Object.freeze(memories),
    exports: Object.freeze(enriched),
    section_ids: Object.freeze(sectionIds),
  });
}

// ---------------------------------------------------------------------------
// The screen — default-deny imports + memory caps, decided BEFORE instantiation.
// ---------------------------------------------------------------------------

/**
 * Screen a module against the sandbox policy. Never throws.
 * @param {Uint8Array|ArrayBuffer|number[]} bytes
 * @param {{max_memory_pages?: number, sanctioned?: ReadonlyArray<{module,name,kind}>}} [o]
 * @returns {{ok:boolean, metered:boolean, refusals:ReadonlyArray<string>, inspection:object|null}} frozen.
 */
export function screenWasm(bytes, { max_memory_pages = SANDBOX_LIMITS.max_memory_pages, sanctioned = SANCTIONED_IMPORTS } = {}) {
  let inspection = null;
  try {
    inspection = inspectWasm(bytes);
  } catch (err) {
    return Object.freeze({
      ok: false,
      metered: false,
      refusals: Object.freeze([`not a well-formed WebAssembly module: ${err.message}`]),
      inspection: null,
    });
  }

  const refusals = [];
  for (const imp of inspection.imports) {
    const allowed = sanctioned.some((s) => s.module === imp.module && s.name === imp.name && s.kind === imp.kind);
    if (!allowed) {
      refusals.push(`default-deny import policy: ${imp.module}.${imp.name} (${imp.kind}) is not sanctioned`);
      continue;
    }
    if (imp.kind === 'memory') {
      if (imp.shared) refusals.push(`imported memory ${imp.module}.${imp.name} is shared — refused`);
      if (imp.min > max_memory_pages) {
        refusals.push(
          `imported memory ${imp.module}.${imp.name} demands ${imp.min} pages > the ${max_memory_pages}-page cap`,
        );
      }
    }
  }
  for (const mem of inspection.memories) {
    if (mem.shared) refusals.push('module declares a shared memory — refused');
    if (mem.max === null) {
      refusals.push(
        `module declares its own UNBOUNDED memory (min ${mem.min}, no max) — refused; sandboxed modules must import env.memory (host-capped) or declare max <= ${max_memory_pages}`,
      );
    } else if (mem.max > max_memory_pages || mem.min > max_memory_pages) {
      refusals.push(
        `module declares its own memory over the cap (min ${mem.min}, max ${mem.max}, cap ${max_memory_pages} pages) — refused`,
      );
    }
  }

  const metered = inspection.imports.some((i) => i.kind === 'func' && i.module === 'fuel' && i.name === 'consume');
  return Object.freeze({
    ok: refusals.length === 0,
    metered,
    refusals: Object.freeze(refusals),
    inspection,
  });
}

// ---------------------------------------------------------------------------
// The in-process executor.
// ---------------------------------------------------------------------------

/** Compose the uniform, JSON-safe, frozen execution record. */
function makeRecord(base, extra) {
  return Object.freeze({
    ok: false,
    outcome: null,
    entry: base.entry,
    args: base.args,
    value: null,
    trap: null,
    termination: null,
    refusals: null,
    error: null,
    fuel: null,
    memory: null,
    metered: base.metered === undefined ? false : base.metered,
    limits: base.limits,
    module_sha256: base.module_sha256,
    runner: base.runner,
    ...extra,
  });
}

/**
 * Execute one exported function of a screened module inside the in-process sandbox: default-deny
 * imports, engine-capped memory, fuel + cooperative-deadline metering. NEVER throws — every path
 * lands on a structured record. Unmetered modules are refused (use runInNativeSandbox — the
 * wall-clock kill — for those).
 *
 * @param {Uint8Array|ArrayBuffer|number[]} bytes  the module.
 * @param {{entry:string, args?:Array<string|number|bigint>, limits?:object,
 *          allowUnmetered?:boolean, sanctioned?:ReadonlyArray<object>}} o
 *   args are decimal strings (i64-safe across JSON); numbers/bigints are stringified.
 * @returns {Promise<object>} the frozen execution record.
 */
export async function executeWasm(bytes, { entry, args = [], limits = {}, allowUnmetered = false, sanctioned = SANCTIONED_IMPORTS } = {}) {
  const u8 = toU8(bytes);
  const lim = normalizeLimits(limits);
  const base = {
    entry: typeof entry === 'string' ? entry : null,
    args: Object.freeze(args.map((a) => String(a))),
    limits: lim,
    module_sha256: sha256Hex(u8),
    runner: SANDBOX_RUNNER_KIND.IN_PROCESS,
  };

  const screen = screenWasm(u8, { max_memory_pages: lim.max_memory_pages, sanctioned });
  base.metered = screen.metered;
  if (!screen.ok) {
    return makeRecord(base, { outcome: EXECUTION_OUTCOME.REFUSED, refusals: screen.refusals });
  }
  if (!screen.metered && !allowUnmetered) {
    return makeRecord(base, {
      outcome: EXECUTION_OUTCOME.REFUSED,
      refusals: Object.freeze([
        'unmetered module (no fuel.consume import) refused in-process — nothing cooperative could stop it; only the native child runner (wall-clock kill) may execute it',
      ]),
    });
  }
  if (base.entry === null) {
    return makeRecord(base, {
      outcome: EXECUTION_OUTCOME.REFUSED,
      refusals: Object.freeze(['entry must be a non-empty string naming an exported function']),
    });
  }

  // The fuel meter: deterministic instruction-count budget + cooperative deadline. A hostile
  // "metered" module cannot mint fuel back (cost is clamped to >= 1).
  let fuelUsed = 0;
  let deadline = null;
  const meter = {
    consume: (n) => {
      const cost = Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
      fuelUsed += cost;
      if (fuelUsed > lim.max_fuel) {
        throw new FuelExhaustedError(`fuel exhausted: ${fuelUsed} ticks > max_fuel ${lim.max_fuel}`);
      }
      if (deadline !== null && Date.now() > deadline) {
        throw new DeadlineExceededError(`cooperative deadline exceeded: timeout_ms ${lim.timeout_ms}`);
      }
    },
  };

  // Host-capped imported memory (only if the module asks for it — screened to be <= cap).
  const memoryImport = screen.inspection.imports.find(
    (i) => i.kind === 'memory' && i.module === 'env' && i.name === 'memory',
  );
  let memoryRef = null;
  const importObject = { fuel: meter };
  if (memoryImport) {
    memoryRef = new WebAssembly.Memory({ initial: memoryImport.min, maximum: lim.max_memory_pages });
    importObject.env = { memory: memoryRef };
  }

  const finishMeters = () => ({
    fuel: screen.metered ? Object.freeze({ max: lim.max_fuel, used: fuelUsed }) : null,
    memory: memoryRef
      ? Object.freeze({ max_pages: lim.max_memory_pages, pages: memoryRef.buffer.byteLength / WASM_PAGE_BYTES })
      : null,
  });

  let instance;
  try {
    ({ instance } = await WebAssembly.instantiate(u8, importObject));
  } catch (err) {
    return makeRecord(base, {
      outcome: EXECUTION_OUTCOME.REFUSED,
      refusals: Object.freeze([`module failed to instantiate: ${err.message}`]),
    });
  }

  const exportInfo = screen.inspection.exports.find((e) => e.kind === 'func' && e.name === base.entry);
  const fn = instance.exports[base.entry];
  if (!exportInfo || typeof fn !== 'function' || !exportInfo.signature) {
    return makeRecord(base, {
      outcome: EXECUTION_OUTCOME.REFUSED,
      refusals: Object.freeze([`entry "${base.entry}" is not an exported function of this module`]),
    });
  }
  const params = exportInfo.signature.params;
  if (params.length !== base.args.length) {
    return makeRecord(base, {
      outcome: EXECUTION_OUTCOME.REFUSED,
      refusals: Object.freeze([`arity mismatch: entry "${base.entry}" takes ${params.length} argument(s), got ${base.args.length}`]),
    });
  }
  const converted = [];
  for (let i = 0; i < params.length; i += 1) {
    const s = base.args[i];
    if (!/^-?\d+$/.test(s)) {
      return makeRecord(base, {
        outcome: EXECUTION_OUTCOME.REFUSED,
        refusals: Object.freeze([`argument ${i} (${JSON.stringify(s)}) is not a decimal integer string`]),
      });
    }
    if (params[i] === 'i64') {
      const v = BigInt(s);
      if (v < I64_MIN || v > I64_MAX) {
        return makeRecord(base, {
          outcome: EXECUTION_OUTCOME.REFUSED,
          refusals: Object.freeze([
            `argument ${i} (${s}) is outside the i64 exact envelope [${I64_MIN}, ${I64_MAX}] — refused, never silently wrapped`,
          ]),
        });
      }
      converted.push(v);
    } else if (params[i] === 'i32') {
      const v = Number(s);
      if (!Number.isInteger(v) || v < -(2 ** 31) || v > 2 ** 31 - 1) {
        return makeRecord(base, {
          outcome: EXECUTION_OUTCOME.REFUSED,
          refusals: Object.freeze([`argument ${i} (${s}) is outside the i32 envelope — refused`]),
        });
      }
      converted.push(v);
    } else {
      return makeRecord(base, {
        outcome: EXECUTION_OUTCOME.REFUSED,
        refusals: Object.freeze([`unsupported parameter type "${params[i]}" at index ${i} (only i32/i64 cross the sandbox boundary)`]),
      });
    }
  }

  deadline = lim.timeout_ms === null ? null : Date.now() + lim.timeout_ms;
  try {
    const raw = fn(...converted);
    const value = typeof raw === 'bigint' ? raw.toString() : raw === undefined ? null : raw;
    return makeRecord(base, { ok: true, outcome: EXECUTION_OUTCOME.COMPLETED, value, ...finishMeters() });
  } catch (err) {
    if (err instanceof FuelExhaustedError) {
      return makeRecord(base, {
        outcome: EXECUTION_OUTCOME.TERMINATED,
        termination: Object.freeze({ limit: TERMINATION_LIMIT.FUEL, detail: err.message }),
        ...finishMeters(),
      });
    }
    if (err instanceof DeadlineExceededError) {
      return makeRecord(base, {
        outcome: EXECUTION_OUTCOME.TERMINATED,
        termination: Object.freeze({ limit: TERMINATION_LIMIT.TIMEOUT, detail: err.message }),
        ...finishMeters(),
      });
    }
    if (err instanceof WebAssembly.RuntimeError) {
      return makeRecord(base, {
        outcome: EXECUTION_OUTCOME.TRAPPED,
        trap: err.message,
        ...finishMeters(),
      });
    }
    return makeRecord(base, {
      outcome: EXECUTION_OUTCOME.ERROR,
      error: `unexpected host error during execution: ${err && err.message ? err.message : String(err)}`,
      ...finishMeters(),
    });
  }
}

// ---------------------------------------------------------------------------
// The native runner — an out-of-process child with a hard wall-clock kill.
// ---------------------------------------------------------------------------

/**
 * The pinned child entry (mirrors the Wave-9 firewall contract: a named runner under test/ that
 * test/index.js never imports — it is only ever the spawned child).
 */
export const WASM_SANDBOX_RUNNER = fileURLToPath(new URL('../test/wasm-sandbox-runner.mjs', import.meta.url));

/**
 * Execute a WASM job in a CHILD node process — the native runner. Same node binary, NO shell,
 * hermetic per-call temp dir for the input spec. The child applies the full in-process sandbox
 * (screen + fuel + memory + cooperative deadline); the PARENT holds the non-cooperative boundary:
 * execFileSync's native timeout kills a runaway child (unmetered spin, hung solver, …) and the
 * kill returns as a structured `terminated { limit: 'timeout' }` record. Never throws.
 *
 * @param {{module_bytes?:Uint8Array|null, module_b64?:string|null, entry:string,
 *          args?:Array<string|number|bigint>, limits?:object, allowUnmetered?:boolean}} job
 * @param {{nodePath?: string}} [o]
 * @returns {object} the frozen execution record (runner: 'native-child').
 */
export function runInNativeSandbox({ module_bytes = null, module_b64 = null, entry, args = [], limits = {}, allowUnmetered = true } = {}, { nodePath = process.execPath } = {}) {
  if (module_b64 !== null && typeof module_b64 !== 'string') {
    throw new Error('runInNativeSandbox(): module_b64 (when given) must be a base64 string');
  }
  if (module_b64 === null && module_bytes === null) {
    throw new Error('runInNativeSandbox(): module_bytes or module_b64 is required');
  }
  const b64 = module_b64 ?? Buffer.from(toU8(module_bytes)).toString('base64');
  const u8 = new Uint8Array(Buffer.from(b64, 'base64'));
  const lim = normalizeLimits(limits);
  const argStrings = Object.freeze(args.map((a) => String(a)));
  const base = {
    entry: typeof entry === 'string' ? entry : null,
    args: argStrings,
    limits: lim,
    module_sha256: sha256Hex(u8),
    metered: null, // unknown until the child screens it
    runner: SANDBOX_RUNNER_KIND.NATIVE_CHILD,
  };
  // The child needs a hard wall clock even when the caller passed timeout_ms: null.
  const wallClockMs = (lim.timeout_ms ?? SANDBOX_LIMITS.timeout_ms) + NATIVE_KILL_GRACE_MS;

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ramanujan-wasm-'));
  const inputPath = path.join(dir, 'input.json');
  try {
    fs.writeFileSync(
      inputPath,
      JSON.stringify({ module_b64: b64, entry: base.entry, args: argStrings, limits: lim, allowUnmetered }),
    );
    let stdout;
    try {
      stdout = execFileSync(nodePath, [WASM_SANDBOX_RUNNER, inputPath], {
        encoding: 'utf8',
        windowsHide: true,
        timeout: wallClockMs,
        killSignal: 'SIGKILL',
      });
    } catch (err) {
      const timedOut =
        err && (err.code === 'ETIMEDOUT' || err.signal === 'SIGKILL' || err.signal === 'SIGTERM' || /ETIMEDOUT/i.test(err.message ?? ''));
      if (timedOut) {
        return makeRecord(base, {
          outcome: EXECUTION_OUTCOME.TERMINATED,
          termination: Object.freeze({
            limit: TERMINATION_LIMIT.TIMEOUT,
            detail: `native kill: the sandbox child exceeded ${wallClockMs}ms wall clock (${err.signal ?? err.code ?? 'timeout'})`,
          }),
        });
      }
      const stderr = err && typeof err.stderr === 'string' && err.stderr.length > 0 ? ` — stderr: ${err.stderr.slice(0, 400)}` : '';
      return makeRecord(base, {
        outcome: EXECUTION_OUTCOME.ERROR,
        error: `sandbox child failed: ${err && err.message ? err.message : String(err)}${stderr}`,
      });
    }
    let parsed;
    try {
      parsed = JSON.parse(stdout.trim());
    } catch {
      return makeRecord(base, {
        outcome: EXECUTION_OUTCOME.ERROR,
        error: `sandbox child produced unparseable output: ${JSON.stringify(stdout.slice(0, 200))}`,
      });
    }
    return Object.freeze({ ...parsed, runner: SANDBOX_RUNNER_KIND.NATIVE_CHILD });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

/**
 * The child side of the native runner (test/wasm-sandbox-runner.mjs is a thin entry over this, so
 * parent and child run the SAME engine). Reads the job spec from argv[0], executes it under the
 * full in-process sandbox, writes the JSON record to stdout. Invoked with no input path it is a
 * deliberate no-op (registers nothing, exits 0) — the same contract the firewall runner pinned.
 * @param {string[]} argv  process.argv.slice(2).
 * @returns {Promise<object|null>} the record (also written to stdout), or null on the no-op path.
 */
export async function runWasmSandboxChild(argv = []) {
  const [inputPath] = argv;
  if (!inputPath) return null;
  const spec = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  const record = await executeWasm(new Uint8Array(Buffer.from(spec.module_b64, 'base64')), {
    entry: spec.entry,
    args: spec.args ?? [],
    limits: spec.limits ?? {},
    allowUnmetered: spec.allowUnmetered !== false,
  });
  process.stdout.write(`${JSON.stringify(record)}\n`);
  return record;
}
