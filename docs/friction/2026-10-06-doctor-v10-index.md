# Doctor R&D v10 source-index failure - 2026-10-06

- The daily report has one correctness failure: boneyard worktree creation
  returned `empty-repo-seed-failed` with `.git/index: index file open failed:
  Permission denied`. The original report is preserved beside this record.
- A temporary unborn repository with a real Windows nonshared handle on its
  staged index reproduces the exact reason, return code 128 and error text.
  A second regression shows that the old `commit --allow-empty` seed changes
  the owner's index and commits staged files. Both tests failed before repair
  (2 failed, 10 deselected, 1.55 seconds).
- Repair scope: seed a truly empty commit through Git plumbing without reading
  or writing the source index; publish only into a verified unborn HEAD using
  compare-and-swap. Preserve real Git errors and concurrent commits. The
  original overnight interleaving is not established by this reproduction.
- Verification: all 45 tests passed in 47.92 seconds across worktrees, the v10
  health surface and terminal sessions. The real locked-index reproduction now
  opens its worktree, preserving the source index byte-for-byte. Concurrent
  first commits, SHA-256 repositories, failed object/ref writes and unreadable
  existing repositories are covered. Scoped diff whitespace check passed.
- Independent bounded source/diff review found no serious gap. This was an
  executed review of supplied implementation details, not a live-service check.
- Full healthcheck ran exactly once against owned snapshot data on port 61221,
  retained every correctness check, and finished with exit code 0 in 196.56
  seconds. All 34 correctness checks passed, including v10's seven steps and
  fresh live version/status probes. One non-blocking warning remains: the
  temporary server needed 128.1 seconds to become ready. The actual result was
  published to `health_reports/2026-10-06.md`, with scope stated in the report.
- An initially unauthenticated Doctor-status inspection was refused correctly;
  the same read using the configured token returned no issues and the single
  boot-speed warning. Doctor is yellow for that warning rather than red for an
  unresolved correctness issue. The active listeners remain Anchor PID 8608
  and Ledger PID 8264.
- No live campaign data was deleted, no skills were changed, and no active
  service/session was restarted. The healthcheck imports the repair in a new
  process. Existing service Python modules load it at their next normal safe
  restart; this receipt does not claim an in-process hot reload.
- Reproduction, regression tests, bounded independent review and full-run
  provenance are retained in `2026-10-06-doctor-v10-index-verification.json`
  and `doctor-v10-index-2026-10-06-run.py`. The owned snapshot was retained for
  audit; the original failed daily report remains preserved.
