// Overhaul Wave 3 — Secure WASM Sandbox Runtime: the PRE-COMPILED WASM MODULES.
//
// The wave's "pre-compiled … exact-arithmetic WASM integration", shipped IN-REPO as bytes: a tiny
// deterministic WebAssembly assembler (uleb/sleb + section encoders — pure functions over byte
// arrays, no I/O) and the fixed module recipes it pre-compiles at load time. Nothing here executes
// WASM — execution, screening, and resource boundaries live in src/wasm-sandbox.mjs; this module is
// the payload side of that engine/payload split.
//
// THE EXACT-ARITHMETIC MODULE (the fast-path lane's verifier):
//   i64 add / sub / mul with OVERFLOW GUARDS COMPILED IN — an out-of-range result executes
//   `unreachable` and TRAPS. Exact means CORRECT OR REFUSED: this module can never return a
//   silently-wrapped wrong value (THE HONESTY LAW at the bytecode level). Its envelope is the
//   signed 64-bit integers, declared honestly — arbitrary-magnitude computation stays on the
//   Wave-9 firewall-subprocess path (bigint rationals), which this lane complements, never replaces.
//
// FUEL METERING IS BAKED IN. Every recipe that loops or computes imports `fuel.consume` (the
// sandbox's instruction-count meter) and calls it on every operation / iteration, so the Wave-3
// runner can enforce a deterministic instruction-count limit in-process. The metering is
// cooperative BY CONSTRUCTION for these first-party modules (the calls are compiled into the
// bytes); arbitrary third-party modules are the native child runner's job (non-cooperative
// wall-clock kill) — see wasm-sandbox.mjs.
//
// THE BOUNDARY PROBES (test fodder for the enforced limits — each one genuine, none decorative):
//   METERED_SPIN_WASM    — infinite loop that consumes fuel: proves the instruction-count kill.
//   UNMETERED_SPIN_WASM  — infinite loop with NO fuel import: only the native runner's wall-clock
//                          kill can stop it (the in-process runner must REFUSE it).
//   MEMORY_PROBE_WASM    — grows imported memory until the engine-enforced maximum refuses it,
//                          then RETURNS the count: the OOM boundary made observable.
//   HUGE_MEMORY_WASM     — declares its own 4096-page (256 MiB) unbounded memory: static-screen
//                          refusal fodder (over-cap + unbounded).
//   WILD_IMPORT_WASM     — imports wasi fd_write: default-deny import-policy refusal fodder.
//
// THE Z3 STAND-IN (Z3_STANDIN_WASM) exercises the pre-compiled-z3 SEAM's mechanics (attach bytes ->
// screen -> native-sandbox execution -> structured evidence) and is ALWAYS labeled as a stand-in.
// It mints no solver verdict and must never masquerade as z3 — the real pre-compiled z3 module
// attaches through the same seam with its own honest source label (see sandbox-pipeline.mjs).
//
// Pure node built-ins; no timers, no I/O. Runs under `node --test test/`.

/** WebAssembly value-type bytes (the two this project's modules use). */
const VALTYPE = Object.freeze({ i32: 0x7f, i64: 0x7e });

const textEncoder = new TextEncoder();

/** Unsigned LEB128. */
function uleb(value) {
  let n = BigInt(value);
  if (n < 0n) throw new Error(`uleb(): value must be non-negative (got ${value})`);
  const out = [];
  do {
    let b = Number(n & 0x7fn);
    n >>= 7n;
    if (n > 0n) b |= 0x80;
    out.push(b);
  } while (n > 0n);
  return out;
}

/** Signed LEB128. */
function sleb(value) {
  let n = BigInt(value);
  const out = [];
  for (;;) {
    const b = Number(n & 0x7fn);
    n >>= 7n;
    if ((n === 0n && (b & 0x40) === 0) || (n === -1n && (b & 0x40) !== 0)) {
      out.push(b);
      return out;
    }
    out.push(b | 0x80);
  }
}

/** Length-prefixed UTF-8 name. */
function encodeName(s) {
  const bytes = textEncoder.encode(s);
  return [...uleb(bytes.length), ...bytes];
}

/** A wasm vector: count prefix + flattened entries. */
function vec(entries) {
  return [...uleb(entries.length), ...entries.flat(Infinity)];
}

/** A sized section: id + byte-length + body. */
function section(id, body) {
  return [id, ...uleb(body.length), ...body];
}

/** Memory/table limits: flag 0x00 (min only) or 0x01 (min+max). */
function limits(min, max = null) {
  return max === null ? [0x00, ...uleb(min)] : [0x01, ...uleb(min), ...uleb(max)];
}

/**
 * Assemble a WebAssembly binary from a declarative spec. Deterministic: same spec, same bytes.
 * @param {{
 *   types?: Array<{params: string[], results: string[]}>,
 *   imports?: Array<{module:string, name:string, kind:'func', type:number}
 *                 | {module:string, name:string, kind:'memory', min:number, max?:number|null}>,
 *   memories?: Array<{min:number, max?:number|null}>,
 *   funcs?: Array<{type:number, locals?: string[], body: number[]}>,
 *   exports?: Array<{name:string, kind:'func'|'memory', index:number}>,
 * }} spec
 * @returns {Uint8Array} the compiled module bytes.
 */
export function assembleWasm({ types = [], imports = [], memories = [], funcs = [], exports = [] } = {}) {
  const bytes = [0x00, 0x61, 0x73, 0x6d, 0x01, 0x00, 0x00, 0x00]; // magic + version 1
  if (types.length > 0) {
    bytes.push(
      ...section(
        1,
        vec(
          types.map((t) => [
            0x60,
            ...vec(t.params.map((v) => [VALTYPE[v]])),
            ...vec(t.results.map((v) => [VALTYPE[v]])),
          ]),
        ),
      ),
    );
  }
  if (imports.length > 0) {
    bytes.push(
      ...section(
        2,
        vec(
          imports.map((imp) => [
            ...encodeName(imp.module),
            ...encodeName(imp.name),
            ...(imp.kind === 'func' ? [0x00, ...uleb(imp.type)] : [0x02, ...limits(imp.min, imp.max ?? null)]),
          ]),
        ),
      ),
    );
  }
  if (funcs.length > 0) {
    bytes.push(...section(3, vec(funcs.map((f) => uleb(f.type)))));
  }
  if (memories.length > 0) {
    bytes.push(...section(5, vec(memories.map((m) => limits(m.min, m.max ?? null)))));
  }
  if (exports.length > 0) {
    bytes.push(
      ...section(
        7,
        vec(exports.map((e) => [...encodeName(e.name), e.kind === 'func' ? 0x00 : 0x02, ...uleb(e.index)])),
      ),
    );
  }
  if (funcs.length > 0) {
    bytes.push(
      ...section(
        10,
        vec(
          funcs.map((f) => {
            const body = [
              ...vec((f.locals ?? []).map((v) => [...uleb(1), VALTYPE[v]])),
              ...f.body,
              0x0b, // end
            ];
            return [...uleb(body.length), ...body];
          }),
        ),
      ),
    );
  }
  return new Uint8Array(bytes);
}

// ---------------------------------------------------------------------------
// Instruction helpers (only the opcodes these recipes need).
// ---------------------------------------------------------------------------

const VOID = 0x40; // empty block type
const i32c = (n) => [0x41, ...sleb(n)];
const i64c = (n) => [0x42, ...sleb(n)];
const lget = (i) => [0x20, ...uleb(i)];
const lset = (i) => [0x21, ...uleb(i)];
const call = (i) => [0x10, ...uleb(i)];
const br = (depth) => [0x0c, ...uleb(depth)];
const UNREACHABLE = 0x00;
const LOOP = 0x03;
const IF = 0x04;
const END = 0x0b;
const RETURN = 0x0f;
const I32_EQ = 0x46;
const I32_ADD = 0x6a;
const I64_NE = 0x52;
const I64_LT_S = 0x53;
const I64_ADD = 0x7c;
const I64_SUB = 0x7d;
const I64_MUL = 0x7e;
const I64_DIV_S = 0x7f;
const I64_AND = 0x83;
const I64_XOR = 0x85;
const MEMORY_GROW = [0x40, 0x00];

/** One fuel tick: `fuel.consume(1)` — the imported meter is always function index 0. */
const fuelTick = [...i32c(1), ...call(0)];

// ---------------------------------------------------------------------------
// The sanctioned-import descriptors these recipes bind to (the sandbox policy in
// wasm-sandbox.mjs sanctions exactly this set — declared here so the payload side
// and its tests can name them without importing the engine).
// ---------------------------------------------------------------------------

/** The instruction-count meter every metered recipe imports (function index 0). */
export const FUEL_IMPORT = Object.freeze({ module: 'fuel', name: 'consume', kind: 'func' });

/** The host-capped linear memory a memory-using recipe imports. */
export const MEMORY_IMPORT = Object.freeze({ module: 'env', name: 'memory', kind: 'memory' });

// ---------------------------------------------------------------------------
// Recipe: EXACT ARITHMETIC (i64, overflow-checked, fuel-metered).
// ---------------------------------------------------------------------------

/** The operations the exact-arithmetic module exports. */
export const EXACT_ARITHMETIC_OPS = Object.freeze(['add', 'sub', 'mul']);

const T_FUEL = 0; // (i32) -> ()
const T_BIN = 1; // (i64, i64) -> (i64)

/**
 * add(a, b): r = a + b; trap iff ((a ^ r) & (b ^ r)) < 0 (signed-overflow bit trick).
 * Locals: 0=a, 1=b, 2=r.
 */
const ADD_BODY = [
  ...fuelTick,
  ...lget(0), ...lget(1), I64_ADD, ...lset(2),
  ...lget(0), ...lget(2), I64_XOR,
  ...lget(1), ...lget(2), I64_XOR,
  I64_AND, ...i64c(0), I64_LT_S,
  IF, VOID, UNREACHABLE, END,
  ...lget(2),
];

/**
 * sub(a, b): r = a - b; trap iff ((a ^ b) & (a ^ r)) < 0.
 */
const SUB_BODY = [
  ...fuelTick,
  ...lget(0), ...lget(1), I64_SUB, ...lset(2),
  ...lget(0), ...lget(1), I64_XOR,
  ...lget(0), ...lget(2), I64_XOR,
  I64_AND, ...i64c(0), I64_LT_S,
  IF, VOID, UNREACHABLE, END,
  ...lget(2),
];

/**
 * mul(a, b): r = a * b; trap iff a != 0 and r / a != b (the div_s trap on the INT_MIN/-1 corner is
 * itself an overflow refusal — that product overflows too, so trapping is the correct outcome).
 */
const MUL_BODY = [
  ...fuelTick,
  ...lget(0), ...lget(1), I64_MUL, ...lset(2),
  ...lget(0), ...i64c(0), I64_NE,
  IF, VOID,
  ...lget(2), ...lget(0), I64_DIV_S, ...lget(1), I64_NE,
  IF, VOID, UNREACHABLE, END,
  END,
  ...lget(2),
];

/**
 * The pre-compiled exact-arithmetic module: exports add/sub/mul over i64, overflow-checked
 * (correct or trap — never a silent wraparound), fuel-metered (imports fuel.consume).
 */
export const EXACT_ARITHMETIC_WASM = assembleWasm({
  types: [
    { params: ['i32'], results: [] },
    { params: ['i64', 'i64'], results: ['i64'] },
  ],
  imports: [{ module: FUEL_IMPORT.module, name: FUEL_IMPORT.name, kind: 'func', type: T_FUEL }],
  funcs: [
    { type: T_BIN, locals: ['i64'], body: ADD_BODY },
    { type: T_BIN, locals: ['i64'], body: SUB_BODY },
    { type: T_BIN, locals: ['i64'], body: MUL_BODY },
  ],
  exports: [
    { name: 'add', kind: 'func', index: 1 }, // index 0 is the fuel import
    { name: 'sub', kind: 'func', index: 2 },
    { name: 'mul', kind: 'func', index: 3 },
  ],
});

// ---------------------------------------------------------------------------
// Recipe: boundary probes.
// ---------------------------------------------------------------------------

/** Infinite loop that consumes 1 fuel per iteration — the instruction-count boundary probe. */
export const METERED_SPIN_WASM = assembleWasm({
  types: [
    { params: ['i32'], results: [] },
    { params: [], results: [] },
  ],
  imports: [{ module: FUEL_IMPORT.module, name: FUEL_IMPORT.name, kind: 'func', type: T_FUEL }],
  funcs: [{ type: 1, body: [LOOP, VOID, ...fuelTick, ...br(0), END] }],
  exports: [{ name: 'spin', kind: 'func', index: 1 }],
});

/**
 * Infinite loop with NO fuel import: cooperatively unstoppable. The in-process runner must REFUSE
 * it; only the native child runner's wall-clock kill can terminate it.
 */
export const UNMETERED_SPIN_WASM = assembleWasm({
  types: [{ params: [], results: [] }],
  funcs: [{ type: 0, body: [LOOP, VOID, ...br(0), END] }],
  exports: [{ name: 'spin', kind: 'func', index: 0 }],
});

/**
 * grow_until_refused() -> i32: grows imported memory one page at a time until the engine-enforced
 * maximum refuses the growth (memory.grow returns -1), then returns how many pages it won — the
 * OOM boundary made observable. Metered (1 fuel per attempt). Locals: 0=count.
 */
export const MEMORY_PROBE_WASM = assembleWasm({
  types: [
    { params: ['i32'], results: [] },
    { params: [], results: ['i32'] },
  ],
  imports: [
    { module: FUEL_IMPORT.module, name: FUEL_IMPORT.name, kind: 'func', type: T_FUEL },
    { module: MEMORY_IMPORT.module, name: MEMORY_IMPORT.name, kind: 'memory', min: 1 },
  ],
  funcs: [
    {
      type: 1,
      locals: ['i32'],
      body: [
        LOOP, VOID,
        ...fuelTick,
        ...i32c(1), ...MEMORY_GROW,
        ...i32c(-1), I32_EQ,
        IF, VOID, ...lget(0), RETURN, END,
        ...lget(0), ...i32c(1), I32_ADD, ...lset(0),
        ...br(0),
        END,
        UNREACHABLE, // the loop never falls through; this keeps the i32-returning body valid
      ],
    },
  ],
  exports: [{ name: 'grow_until_refused', kind: 'func', index: 1 }],
});

/**
 * Declares its OWN 4096-page (256 MiB) memory with NO maximum — valid WebAssembly, but the static
 * screen must refuse it (own-memory over the cap AND unbounded). Never instantiated.
 */
export const HUGE_MEMORY_WASM = assembleWasm({
  memories: [{ min: 4096 }],
  exports: [{ name: 'memory', kind: 'memory', index: 0 }],
});

/** Imports wasi fd_write — default-deny import-policy refusal fodder. */
export const WILD_IMPORT_WASM = assembleWasm({
  types: [
    { params: ['i32', 'i32', 'i32', 'i32'], results: ['i32'] },
    { params: [], results: ['i32'] },
  ],
  imports: [{ module: 'wasi_snapshot_preview1', name: 'fd_write', kind: 'func', type: 0 }],
  funcs: [{ type: 1, body: [...i32c(0)] }],
  exports: [{ name: 'main', kind: 'func', index: 1 }],
});

// ---------------------------------------------------------------------------
// Recipe: the z3-seam stand-in.
// ---------------------------------------------------------------------------

/**
 * A minimal metered module exporting `check() -> i32` (returns 1). It exists ONLY to exercise the
 * pre-compiled-z3 attachment seam's MECHANICS (screen -> native sandbox -> structured evidence).
 * It is NOT z3, decides nothing, and must always be attached under a stand-in source label — the
 * evidence path never mints a solver verdict from it (THE HONESTY LAW).
 */
export const Z3_STANDIN_WASM = assembleWasm({
  types: [
    { params: ['i32'], results: [] },
    { params: [], results: ['i32'] },
  ],
  imports: [{ module: FUEL_IMPORT.module, name: FUEL_IMPORT.name, kind: 'func', type: T_FUEL }],
  funcs: [{ type: 1, body: [...fuelTick, ...i32c(1)] }],
  exports: [{ name: 'check', kind: 'func', index: 1 }],
});
