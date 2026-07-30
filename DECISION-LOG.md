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
