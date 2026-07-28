// test/rp-shared-import-parity.test.mjs — Wave 1 researchPrime-side import of the SAME shared stub.
//
// A SEPARATE test process, running from the researchPrime checkout, imports the shared
// brownfield-intake stub the way researchPrime itself resolves shared trio code — via its OWN
// TRIO_ROOT pin in bin/contract.mjs — and prints the canonical JSON serialization of the
// returned plan-artifact-shaped object. This suite (the literature-review side) imports the
// same stub through the same pin and asserts the two consumers' serializations are
// BYTE-IDENTICAL, with neither side adapting or reshaping the object. That parity is the
// Wave-1 proof that ONE shared module home serves both skills, and the proven path is what
// docs/DECISION-RECEIPT-shared-location.md pins.

import { test, describe } from 'node:test';
import assert from 'node:assert';
import { spawnSync } from 'node:child_process';

import {
  resolveResearchPrimeRoot,
  sharedBrownfieldUrl,
  SHARED_BROWNFIELD_SPEC,
} from './_wave1-trio-resolve.mjs';

describe('Wave 1 — shared-import parity (researchPrime side, separate process)', () => {
  test('researchPrime imports the SAME shared stub and serializes it byte-identically', async () => {
    // Lit-review-side serialization (this process).
    const shared = await import((await sharedBrownfieldUrl()).href);
    const litReviewBytes = JSON.stringify(shared.makePlanArtifactStub(), null, 2);

    // researchPrime-side serialization: a child Node process whose cwd is the researchPrime
    // checkout resolves the stub via researchPrime's OWN pin (bin/contract.mjs TRIO_ROOT) —
    // no lit-review code, path, or object crosses into the child.
    const rpRoot = resolveResearchPrimeRoot();
    const childScript = [
      "import path from 'node:path';",
      "import { pathToFileURL } from 'node:url';",
      "const contract = await import(pathToFileURL(path.resolve('bin/contract.mjs')).href);",
      `const shared = await import(new URL(${JSON.stringify(SHARED_BROWNFIELD_SPEC)}, contract.TRIO_ROOT).href);`,
      'process.stdout.write(JSON.stringify(shared.makePlanArtifactStub(), null, 2));',
    ].join('\n');

    const child = spawnSync(process.execPath, ['--input-type=module', '-e', childScript], {
      cwd: rpRoot,
      encoding: 'utf8',
    });

    assert.equal(
      child.status,
      0,
      `researchPrime-side import process failed (stderr):\n${child.stderr}`,
    );
    const rpBytes = child.stdout;

    // Byte-identical canonical serialization across the two consumers…
    assert.equal(rpBytes, litReviewBytes, 'both skills must observe an identical object shape');
    // …and neither consumer reshaped the object (structural equality after round-trip).
    assert.deepStrictEqual(JSON.parse(rpBytes), shared.makePlanArtifactStub());
  });
});
