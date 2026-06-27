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
