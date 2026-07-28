// Test-suite entry point for the frozen gate command `node --test test/`.
// Node's test runner treats a bare directory arg as a single file path (not a
// recursive glob), so `node --test test/` resolves this directory's `main`
// (see ./package.json) and runs whatever this module loads, in one process.
// Same pattern as trio/crucible/test/index.mjs, which proved it on this gate.
//
// SELF-MAINTAINING: this auto-discovers every sibling `*.test.mjs`. A wave just
// drops its `<name>.test.mjs` in `test/` and the gate picks it up — no manual
// edit here, no test-discovery fight. An empty suite is refused so this entry
// can never produce a vacuous green.
// NOTE: import via a RELATIVE specifier (`./name`); a Windows absolute path is
// rejected by dynamic import() as an unsupported URL scheme ("c:").
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const dir = path.dirname(fileURLToPath(import.meta.url));
const testFiles = readdirSync(dir)
  .filter((f) => f.endsWith(".test.mjs"))
  .sort();
if (testFiles.length === 0) {
  throw new Error("no *.test.mjs files found in test/ — refusing to run an empty suite");
}
for (const f of testFiles) {
  await import("./" + f);
}
