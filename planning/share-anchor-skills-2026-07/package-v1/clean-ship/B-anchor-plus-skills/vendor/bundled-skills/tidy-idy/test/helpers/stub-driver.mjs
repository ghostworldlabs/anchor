// test/helpers/stub-driver.mjs — a driver module for CHILD-PROCESS launches.
//
// NOT a test file: it exports a seam and defines no tests.
//
// The Wave-5 parity test has to run the real CLI in a real child process (that
// is what Anchor's button dispatches), and a child process cannot be handed an
// injected `ctx.agent` closure. engine/agent-seam.mjs already resolves a driver
// from TIDY_IDY_DRIVER, so the child gets THIS module instead of a live model:
// deterministic, offline, and on exactly the same code path a real driver takes.
//
// It is deliberately cooperative rather than clever — the parity assertion is
// about the launch surface, and a nondeterministic judge would make two runs
// differ for reasons that have nothing to do with what is under test.

export const DEFAULT_GEMINI_CLI_MODEL = 'stub-model';

/** The paths this stub votes REMOVE on, as a comma-separated env var. */
function removeSet() {
  return new Set(String(process.env.TIDY_IDY_STUB_REMOVE || '').split(',').map((s) => s.trim()).filter(Boolean));
}

export function makeGeminiCliSeam() {
  return {
    async agent(prompt, opts = {}) {
      const label = String(opts.label || '');
      const remove = removeSet();
      // The prompts carry absolute paths; match on basename so a fixture can name
      // its expected removals without knowing the temp directory.
      const mentioned = [...String(prompt).matchAll(/([A-Za-z0-9_.-]+\.[A-Za-z0-9]+)/g)].map((m) => m[1]);
      const targets = [...new Set(mentioned)].filter((f) => remove.has(f));

      if (label.startsWith('hygiene-analysis')) {
        return targets.map((f) => ({ filepath: f, reason: 'stub driver: named in TIDY_IDY_STUB_REMOVE' }));
      }
      if (label.startsWith('attacker')) {
        return targets.map((f) => ({ filepath: f, case_for_removal: 'stub driver', strength: 'strong' }));
      }
      if (label.startsWith('judge')) {
        return targets.map((f) => ({ filepath: f, decision: 'REMOVE', rationale: 'stub driver verdict' }));
      }
      if (label.startsWith('compress')) {
        return { executiveSummary: '# agent\n\nActive goal: stub.\n', historyToAppend: '' };
      }
      return [];
    },
  };
}

export default { makeGeminiCliSeam, DEFAULT_GEMINI_CLI_MODEL };
