# Anchor R&D Surface v3 — "Mission Control" — Execution Log

> Foreman appends per-wave EXECUTE / GATE / REVIEW / FIX / JUDGE entries here.
> Seeded by the Crucible→Foreman handoff on 2026-06-11. Frozen design:
> `MASTER-PLAN.md`. Plan: `IMPLEMENTATION-PLAN.md`. Gate: `python -m pytest -v`.

## Handoff (2026-06-11)

- Crucible Stage 0 (North Star locked), Stage 1 (Master Plan approved), Stage 2
  (10-wave plan, internal Shark-Tank converged given the Wave-1 ConPTY gate)
  complete.
- User-locked decisions: real ConPTY terminals (pywinpty; stdlib-only waiver for
  the terminal subsystem only); proactive cached summaries; git-worktree
  per-session isolation; one comprehensive build; **Wave-1 ConPTY-under-service
  spike HALTS to the user if it fails (no silent downgrade)**; status colors
  green=working / amber=needs-you-or-done / red=failed / grey=idle.
- Mid-Stage-2 addition: Wave 9 — brand the home page as a Ghost World Labs tool
  powered by NextGen Nuclear, using `C:\dev\Agentic-Home\GWL-M-Icon.svg` (ghost +
  ☢, palette matches the theme).
- Awaiting Foreman Wave 1 (the ConPTY-under-service spike — a hard gate).

---

## Wave 1 — ConPTY-under-service spike (HARD GATE) — GO (2026-06-11)

**EXECUTE.** Created `pty_manager.py` (backend seam: real `pywinpty` backend +
deterministic in-memory `stub` backend, env-selected by `ANCHOR_PTY_BACKEND`;
`winpty` imported LAZILY inside the pywinpty backend's `start` — `import
pty_manager` works with the native dep absent, surfacing `PtyUnavailable`).
Manager core: `start/write/read_since/resize/kill`, cursor-stable like
`job_runner.tail`, `UnknownSession(KeyError)` on unknown ids, thread-safe live
table. Added `tests/test_pty_manager.py` (stub-only, hermetic — no real process /
no pywinpty / no live claude) and `spike_conpty_service.py` (runnable empirical
spike).

**GATE (orchestrator-run).** `python -m pytest -v` → **409 passed, 1 skipped**
(baseline 399 + 10 new pty_manager tests). `import pty_manager` / `import
anchor_gui` both OK.

**EMPIRICAL HARD-GATE PROOF (orchestrator-run, the user-gated requirement).**
1. `python spike_conpty_service.py` → **SPIKE PASS, exit 0**: a real `pywinpty`
   ConPTY `cmd` child, launched under a faithfully simulated non-interactive
   `anchor` service context (full system env with `USERPROFILE`/`HOME` pinned to
   `C:\Users\john` and `APPDATA`/`LOCALAPPDATA` stripped), executed
   `set /a R=a*b` + `echo SPIKEOUT=!R!` and the COMPUTED product (never present in
   any typed input) round-tripped — proving command execution, not just input
   echo.
2. Corroboration with the real engine: launching **`claude`** itself through the
   pywinpty backend under the same simulated service env rendered the full
   interactive TUI (`✳ Claude Code v2.1.174`, `Opus 4.8 (1M context) … Claude
   Max`, input box, auto-mode) — ~1960 bytes of healthy TUI, finding the Claude
   **Max subscription** creds with no `APPDATA`. A real ConPTY claude session runs
   under the service context. **HALT condition NOT triggered.**

**REVIEW (2 independent adversarial reviewers).** Both GO-WITH-NITS; neither could
break the lazy-import isolation, API contract, stub faithfulness, or
thread-safety. Agreed findings folded into FIX.

**FIX (bounded, 1 iter).** (1) Declared `pywinpty` as an OPTIONAL extra
(`pyproject.toml` `[project.optional-dependencies] terminal`; core stays
stdlib-only). (2) `_PywinptyChild.kill` now tree-kills (`taskkill /T /F /PID`,
Windows-only, tolerated) to reap `claude`→`node` grandchildren, mirroring
`job_runner.cancel`; reader thread signaled to stop. (3) Bounded output buffer
(`MAX_BUFFER_CHARS`) in both backends, preserving absolute-cursor semantics
(`_total`/`_dropped`) so Wave-3 reattach/replay can't grow memory unbounded; new
test added. (4) Hardened the spike's cmd proof to require command EXECUTION
(computed product distinct from input). Re-gate: **409 passed, 1 skipped**; spike
PASS exit 0.

**Known seams recorded for later waves (not Wave-1 reworks):** `read_since` uses
character offsets returning `str` (pywinpty `read()` returns decoded str) —
Wave 3/4 must handle byte-framing when wiring xterm.js; a manager-`kill`ed session
drops from the live table so its final buffer isn't drainable as `status:"dead"`
(only self-exited children report `dead`) — Wave 3/4's kill-confirm + status-color
UI may want a final-drain contract.

**Verdict: GO.** Committed on branch `foreman/rnd-surface-v3`.

---
