// Test-suite entry point for the frozen gate command `node --test test/`.
//
// Given a DIRECTORY argument, Node's test runner resolves it as a module via
// this directory's package.json `"main"` (→ index.mjs) and runs that single
// module in one process; in this mode it does NOT glob the directory for
// `*.test.mjs`. (Verified on Node 26: a sibling test file is executed only
// because THIS module imports it below — not by runner auto-discovery.) So
// index.mjs is the live entry point, not dead code.
//
// SELF-MAINTAINING: this module discovers and imports every sibling
// `*.test.mjs`, so a wave just drops its `<name>.test.mjs` in `test/` and the
// gate picks it up — no manual edit here. (Mirrors the trio convention so the
// gate is identical across repos.)
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
