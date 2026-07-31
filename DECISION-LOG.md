# Decision Log: Scaled Gandalf Architecture

### 1. Rejection of Destructive "Ignore" Scout
- **Decision:** The Agentic Scout will output an "Include List" rather than an "Ignore List".
- **Rationale (Shark Tank Skeptic Block):** Asking a fast model what to ignore risks hallucinated destruction of critical config files. Asking it what to include is safer; if it misses something, the safe fallback is triggered.

### 2. Implementation of Concurrency Limit
- **Decision:** Map-Reduce batches in Phase 3 will use a strict concurrency semaphore of 3.
- **Rationale (Shark Tank Contrarian Block):** Unbounded asynchronous execution of large payload chunks will overwhelm the Anchor `job_runner`, hit API rate limits, and crash the local UI polling mechanism. 

### 3. Graceful Scout Fallback
- **Decision:** If the Scout pass fails to parse JSON or hits an API timeout, the engine will automatically revert to sending the unpruned payload.
- **Rationale (Shark Tank Analyst Block):** The pipeline must not fail purely because an optimization step (the Scout) encountered a transient error or malformed response. Rigor must survive optimization failures.

## 2026-07-29 — Steward personas + post-run hardening (Fable session) — COORDINATION NOTE
For any session resuming Anchor work: master now carries (1) the post-sleep-run
HARDENING (543a908 — ship-manifest closure of 17 modules, manifest !negation,
startup-gate scoping; the shippable bundle was un-startable before it) and
(2) the STEWARD PERSONA feature (4d3ed0c — anchor_settings.steward_type +
STEWARDS catalog, /api/settings, home-header selector, High Seat + Projects
tile icons follow the persona; Projects tile now carries the steward's SEAL,
not a folder glyph). Six persona icons ship from vendor/brand. Gate family:
pytest -k "steward or settings or share_ or startup or distro" → 419 passed.
STANDING: any wave touching ship-manifest-matched files must APPEND the
distro/ship gate family to its wave gate (see trio/foreman journal 0091).
Service restart (elevated) still pending for the live UI to pick this up.

## 2026-07-30 — Workbench icon LOCKED: the Watchmaker's Bench
workbench-icon.jpg = workbench-watchmakers.jpg (John's pick). The ANVIL
candidate (vendor/brand/workbench-anvil.jpg) is RESERVED as the icon for the
planned 'anvil' code-validation skill — do not reuse it elsewhere.

## 2026-07-30 — Steward reachable with auth ON; route rows are now checkable promises
Three independent faults made the steward unusable on a token-authed dashboard
(John: "it asked for a token again", then "Couldn't do that: Unknown endpoint"):
the steward POSTs sent the token as `?token=` (do_POST never reads the query);
`handle_ecgberht_stand_up` was declared `migrated=True` but never registered in
`_MIGRATED_HANDLERS`; and do_POST dispatched on the RAW request line, so any
POST with a query missed its exact route row. Full write-up:
`docs/friction/2026-07-30-steward-goal-unknown-endpoint.md`.

**DECISIONS / STANDING RULES**

1. **A POST carries its token in the `X-Anchor-Token` HEADER, never the query.**
   `?token=` is the GET transport only. New POST call sites go through
   `_postJson` (project window) or `_ecgHsHeaders()` (high seat), which also
   attach `X-Anchor-Build` so a stale tab gets the 409 'reload' instead of an
   opaque failure. POST URLs are BARE paths.

2. **A `migrated=True` route row is a PROMISE, and the promise is now gated.**
   `test_every_migrated_route_has_a_registered_handler` fails if any declared
   row has no entry in `_MIGRATED_HANDLERS`. Such a row does not 500 — it
   silently falls through to a 404 "Unknown endpoint", which is how three live
   endpoints (stand_up + both friction routes) sat dead with no startup warning.

3. **AUTH-OFF GREEN IS NOT GREEN.** With `ANCHOR_TOKEN` unset every one of the
   above faults is unreachable, and virtually the whole suite (including every
   Playwright flow) runs auth-off. Any wave touching a MUTATING endpoint must
   add at least one **auth-ON** case that asserts the OUTCOME, not the plumbing.
   Pattern to copy: `tests/test_steward_goal_authon_2026_07_30.py`.

4. **On a 401, RETRY — never `location.reload()` first.** Reload discards what
   the user typed (the chamber goal input, the saybox draft). Home adopted this
   2026-07-28; the project window carried the old reload until today. A reload
   remains only as the honest last resort (a genuinely wrong token, or a Request
   whose body is already consumed). Gated by `test_fetch_wrapper_present_*`.

5. **A repaired test must be mutation-checked.** `test_token_hygiene_lifecycle`
   had never executed a single secret-absence assertion (it died on a
   `log_change()` signature and a `journal.Journal` class that have never
   existed, and its scan was guarded by a file that is never created). Fixing a
   red test to green is not enough — plant the leak and watch it fail.

**OPEN (not done here):** the GET/POST token-transport asymmetry (a GET rejects
the header, a POST rejects the query) is pinned by test, not resolved —
widening either side is an auth-surface decision, not a drive-by fix.
