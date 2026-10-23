# Doctor R&D v6 branch-reference read failure - 2026-10-07

- The daily report records one correctness failure: linked-chain worktree
  creation returned `start-point-unavailable` with
  `fatal: bad object refs/heads/master`.
- The ordinary v6 linked-chain and unborn-repository checks pass (2 tests).
  A real Windows nonshared read handle on an owned temporary repository's
  branch reference reproduces the exact Git error. This establishes a possible
  failure mechanism; the overnight handle owner and cause remain unproved.
- Repair scope: retry unavailable start-point reads within a short fixed bound;
  require an actual commit when resolving references. Persistent read failures
  and missing objects must remain errors. Preserve the existing index-free
  empty seed, compare-and-swap publication, owner references and campaign data.
- Before repair, the real denied-ref recovery and missing-object regression
  failed; the permanent-denial preservation case passed (2 failed, 1 passed).
- Implemented four read attempts with one second of total backoff, only for
  `start-point-unavailable` before any seed writes. HEAD, explicit start points,
  fallback refs and the published seed now require `^{commit}` validation.
- Verification: all 53 tests passed in 53.07 seconds across worktrees, v6 and
  v10 health surfaces and terminal sessions. The transient Windows reference
  denial recovers; permanent denial and absent commit objects preserve their
  owner references and return errors. Existing staged/locked-index, concurrent
  publication and SHA-256 checks pass. Scoped diff whitespace check passed.
- Independent bounded review of supplied implementation/test details found no
  serious gap. The reviewer did not run checks or inspect the live service.
- Full healthcheck ran exactly once in 188.88 seconds, exit code 0. All 34
  correctness checks passed, including v6's six steps and fresh live
  `/api/version` and `/api/status` probes. One non-blocking warning remains:
  the owned test server needed 120.8 seconds to become ready.
- The published daily report has no issues. The live read-only Doctor status
  endpoint confirms zero issues and yellow status for that startup warning.
- The snapshot omitted historical logs and therefore produced a misleading
  recommendation about missing prior days. Both real prior-day logs exist;
  the published recommendation was corrected using that read-only evidence,
  with the unaltered staged suite report retained. The replay runner now copies
  those logs before running; the full suite was not rerun.
- No live campaign data was deleted, no skills were changed and no active
  service/session was restarted. Fresh healthcheck imports use the repair;
  the existing service loads the changed Python module at its next normal
  safe restart. This receipt does not claim a live in-process reload.
