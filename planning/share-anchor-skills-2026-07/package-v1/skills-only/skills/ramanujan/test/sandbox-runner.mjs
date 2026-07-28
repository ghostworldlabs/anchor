// Wave 9 — the OUT-OF-MODEL firewall execution SUBPROCESS (the win32 §Build-host & subprocess
// contract names this file EXACTLY: `node test/sandbox-runner.mjs`).
//
// This is the child the firewall spawns via child_process.execFileSync on the same `node` binary
// (NO shell). It receives ONE argument — the path to the hermetic input file holding the bigint-
// tagged literal-computation AST — evaluates it over EXACT arithmetic (bigint rationals, NO float)
// in a fresh process, and writes the canonical (sorted-key, exact-number) stdout the Wave-4 re-hash
// primitive digests. The single exact-arithmetic evaluator lives in src/firewall-subprocess.mjs and
// is shared (this file is a thin entry), so the mint path and the canary re-execution run identical
// code.
//
// It is NOT a test file. The frozen gate `node --test test/` loads test/index.js (which imports only
// `*.test.mjs`), so this module is never executed by the test runner — only as the spawned child.
// Invoked with no input path it is a deliberate no-op (registers nothing, exits 0).

import { runSandboxChild } from '../src/firewall-subprocess.mjs';

runSandboxChild(process.argv.slice(2));
