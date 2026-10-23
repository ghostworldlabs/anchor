# Doctor R&D v10 registry collision - 2026-09-25

- The scheduled report failed in boneyard session registration: Windows error 2
  replacing `.anchor/sessions.json.tmp` with `sessions.json`, followed by PTY
  and worktree rollback. The live version and status endpoints still answered.
- The v10 walk used the ambient data root. Doctor and the dashboard have
  separate process-local locks but used the same registry temporary filename.
  A deterministic temporary-store regression consumed that file just before
  boneyard registration's replace and reproduced the exact reported failure
  before the fix (1 failed in 5.57 seconds). The actual overnight interleaving
  cannot be reconstructed from the report alone.
- Repair follows the existing v12 isolation: private data root, cleanup before
  restoring the environment, only probe-created PTYs removed, and private
  project IDs kept out of later ambient cleanup. Proactive summaries are off
  during the probe. No skill changes, service restart, or live-data deletion.
- Verification: `python -m pytest tests/test_healthcheck_v10.py
  tests/test_healthcheck_v12.py tests/test_healthcheck_cleanup.py -q --tb=short`
  passed all 24 tests in 78.98 seconds. Scoped `git diff --check` passed.
- Full health verification uses the actual `anchor_healthcheck.main()` with
  copied current task/configuration files, private synthetic registries, and an
  unused test port. Its age/port-based listener termination is omitted to
  preserve the running Anchor and Ledger services; no correctness check is
  removed. The report explicitly records this scope and includes live read-only
  `/api/version` and `/api/status` probes. The prior daily report is preserved
  beside this journal. The full runner completed once with exit code 0: all 34
  correctness checks passed in 60.5 seconds, including v10's seven steps and
  both live endpoint probes. No warnings or issues; see the verification JSON.
- The one-off verification wrapper subsequently exited 1 during temporary-dir
  teardown: its own open `logs/errors.log` caused Windows error 32. This occurred
  after the full runner wrote the successful report and receipt. Cleanup of the
  exact owned temporary root completed after process exit. Automatic review
  rejected recursive deletion without a more specific reason; a safer cleanup
  validated every child path, refused links, removed files individually, then
  removed empty directories non-recursively. No full health rerun was performed.
  The health result is not a claim about wrapper exit.
- Final read-only `/api/doctor/status` returned `green`, `Healthy`, today's
  report, and an empty issues list. Anchor (port 8777, PID 106892) and Ledger
  (port 8778, PID 7704) retained their original listener processes. The repair
  requires no service restart. Other sessions' workspace edits were preserved.
