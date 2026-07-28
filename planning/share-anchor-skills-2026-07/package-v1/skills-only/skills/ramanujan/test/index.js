// Test-suite entry / bridge (ESM via root package.json "type":"module").
//
// The frozen project test-command is `node --test test/` (IMPLEMENTATION-PLAN.md). Under
// Node's positional resolution (Node 21+, incl. v26 on this host) a bare directory positional
// is resolved through the CJS LOAD_AS_DIRECTORY algorithm — it looks for `index.js` rather than
// triggering recursive test discovery. So `node --test test/` loads THIS module as its single
// test entry. We dynamically import every sibling `*.test.mjs` so their `test()` calls register
// and run — zero per-file maintenance as later waves add test files. (`node --test test/*.mjs`
// and a bare `node --test` work directly; this only makes the frozen `test/` form pass too.)

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const testFiles = fs
  .readdirSync(here)
  .filter((f) => f.endsWith('.test.mjs'))
  .sort();

for (const file of testFiles) {
  await import(pathToFileURL(path.join(here, file)).href);
}
