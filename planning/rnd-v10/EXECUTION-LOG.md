# Anchor R&D Surface v10 — "Live Handoff & Boneyard" — Execution Log

> Foreman appends per-wave EXECUTE / ADVERSARIAL-REVIEW / FIX / JUDGE history here.
> Frozen design: `MASTER-PLAN.md`. Build plan: `IMPLEMENTATION-PLAN.md`.
> Branch `foreman/rnd-surface-v10` off master `b33c74a` (v9 merged `9baabf0` + the
> Build→Planning tie commit). Baseline at branch cut: GREEN 1068, 1 skipped.

<!-- Foreman writes below this line. -->

## Wave 1 — Paste-NOT-submit handoff substrate (backend) — ✅ GREEN (2 iters)

- **EXECUTE.** Added `paste_prompt=` to `terminal_session.start_session` (phase-1 seed still submitted; the prompt recorded as `pending_paste`, not written); `_flush_pending_paste` writes it to the PTY unsent, once, after the greet; wired into `attach`/`read_since`. `session_registry._normalize` + `update_session` allow-list gain `pending_paste:str=""` / `paste_flushed:bool=False`. New `tests/test_pending_paste_v10.py`.
- **GATE 1.** Full suite GREEN 1080/1 — but review flagged the gate did not actually verify "after the greet".
- **REVIEW (2 independent, refute).** Both corroborated: **BLOCKER** premature flush — the greet marker is a literal substring of the echoed seed, so the paste fired before the model greeted (concrete repro, zero model greet); **MAJOR** double-paste TOCTOU under `ThreadingHTTPServer`; **MINOR** no newline strip (a `NEXT-PROMPT.md` ending in `\n` would auto-submit).
- **FIX iter 1.** Greet detection now = marker occurrences **beyond** the seed's own (`base = seed_text.count(marker)`; flush iff buffer count > base) — non-vacuous (the "no premature flush" test fails against the old logic). Double-paste closed by a compare-and-set under the reentrant `paths.WRITE_LOCK` (claim `paste_flushed=True` before the PTY write; loser no-ops). `pending.rstrip("\r\n")` before write. Tests grew 8→11 (added no-premature-flush, newline-strip, 2-thread concurrency).
- **GATE 2 (orchestrator-run, of record).** `python -m pytest -q` → **GREEN 1083 passed, 1 skipped**. Closure verified in code (`terminal_session.py:547-575`).
- **VERDICT: GO.** Commit scoped (terminal_session.py, session_registry.py, tests/test_pending_paste_v10.py).
