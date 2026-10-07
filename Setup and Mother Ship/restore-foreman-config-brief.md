Restore only tracked root foreman.config.json to its exact bytes at e35f598b39c50a5edfed9684360a76d29e7515a8. The live verification job 20261006-190755-18e469 landed its temporary .foreman-job paths over that file again despite its brief excluding it. This is routine recovery of an unintended side effect, not a new feature or an authorized engine rewrite. Use the original commit bytes, preserving encoding and line endings. Their SHA256 is fc14e59db8f6c50fbd6ed3dd7b0d260da7a1d90293c551f5d2e8dd157bf8ddf4. Expected source text is:
{
  "triage_track": "LITE",
  "triage": {"locked": true, "tier": "Heavy", "depth": "LITE", "rationale": "Stage-2 handoff from confirmed depth=LITE tier=Heavy; waves merged 7 -> 3 by the steward's Rabbit-Catcher read (2026-09-05)", "source": "inherit", "lockedAt": "2026-09-05T22:23:32.492Z"},
  "docs": {
    "description": "planning/reports-links-2026-09-05/handoff/DESCRIPTION.md",
    "plan": "planning/reports-links-2026-09-05/handoff/IMPLEMENTATION-PLAN.md",
    "execution_log": "planning/reports-links-2026-09-05/handoff/EXECUTION-LOG.md"
  },
  "models": {"execute": "claude:claude-fable-5", "fix": "claude:claude-fable-5"},
  "models_note": "2026-09-05: execute/fix pinned to Claude for this build (Foreman journal 0108: the codex execute seat shipped empty waves); review and the elegance adversary follow the dashboard's review family (Grok)."
}

Do not modify any other tracked path, campaign state or skill script. Do not restart Anchor, run another Foreman, or interrupt sessions. Verify the exact hash; the runner commits and safely lands this single path. Report the restoration result and any conflict. No activation or human acceptance is inferred. The repeated job-local configuration placement defect belongs to a later owning-engine repair, outside this restoration.
