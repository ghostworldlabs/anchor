// Test-suite entry point for the frozen gate command `node --test test/`.
// Node's test runner treats a bare directory arg as a single file path (not a
// recursive glob), so `node --test test/` resolves this directory's `main`
// (see ./package.json) and runs whatever this module loads, in one process.
//
// SELF-MAINTAINING: this auto-discovers every sibling `*.test.mjs`. A wave just
// drops its `<name>.test.mjs` in `test/` and the gate picks it up — no manual
// edit here, no test-discovery fight. (Replaces the hand-listed import block.)
// NOTE: import via a RELATIVE specifier (`./name`); a Windows absolute path is
// rejected by dynamic import() as an unsupported URL scheme ("c:").
import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const dir = path.dirname(fileURLToPath(import.meta.url));
const testFiles = readdirSync(dir)
  .filter((f) => f.endsWith(".test.mjs"))
  .sort();
for (const f of testFiles) {
  await import("./" + f);
}
