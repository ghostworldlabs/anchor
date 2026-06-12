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

## Wave 2 — Durable session registry + git-worktree isolation — GO (2026-06-11)

**EXECUTE.** `session_registry.py` — durable, persisted-under-`.anchor/`
(`sessions.json`, atomic tmp+`os.replace` under `paths.WRITE_LOCK`) registry of
managed sessions `{session_id, project_id, lane, backend, worktree_path, branch,
status, created_at, label}`; best-effort load (corrupt/torn/missing → empty);
`register/get/list(filter)/update/remove`; status constants mapped to the locked
colors (running→green, needs-attention/done→amber, failed→red, idle→grey);
injectable `reconcile(live_session_ids, ...)` re-statuses dead sessions + surfaces
orphan worktrees. `worktrees.py` — `create_worktree`/`remove_worktree`/
`reap_orphans` via stdlib `subprocess`, worktrees under a git-ignored managed base
(`paths.data_dir()/.anchor/worktrees/<sid>`, overridable via
`ANCHOR_WORKTREE_BASE`), path-containment guard, never raises. Hermetic tests use
temp git repos + temp base.

**GATE (orchestrator-run).** `python -m pytest -v` → **429 passed, 1 skipped**.
Build repo verified untouched: `git worktree list` shows only the main tree;
`git branch --list 'anchor/session/*'` empty.

**REVIEW (2 independent adversarial reviewers).** Both GO-WITH-NITS. Reviewer A
verified durability/atomicity, corrupt-store survival, genuine disk restart
round-trip, reconcile correctness, isolation-test integrity (no cheats). Reviewer
B (safety focus) proved no path-traversal/absolute-id escape from the managed
base, no `shell=True`, build repo never touched, `reap_orphans(empty)` can't prune
the main tree — but found a MAJOR branch-naming bug + branch litter.

**FIX (bounded, 1 iter).** (1) MAJOR: `branch_for` no longer truncates to 12
chars (collision) — now full-id slug + 16-hex SHA-1; `create_worktree` ALWAYS
creates a fresh branch (`git worktree add -b <branch> <path> <HEAD>`) and returns
`branch-exists` rather than silently attaching to an existing branch's tip; new
shared-12-char-prefix test proves distinct branches + isolation. (2) MINOR:
`remove_worktree` now `git branch -D`s the per-session branch (tolerated) so the
real repo doesn't accumulate `anchor/session/*` litter. (3) Test-integrity: the
mislabeled `test_remove_refuses_unsafe_path` now actually drives a traversal +
absolute id and asserts `reason=='unsafe-path'` with an outside sentinel
surviving. (4) Clarified the `reconcile` `applied` docstring. Re-gate: **429
passed, 1 skipped**; zero repo leakage.

**Seam for Wave 3.** `start_session` flow: mint sid → `worktrees.create_worktree`
→ `pty_manager.start(cwd=path)` → `session_registry.register_session(...,
status=RUNNING)`. On kill: `update_session` then `remove_worktree`. On startup:
`reconcile(live=pty_manager.live_sessions())` + `reap_orphans` + `ensure_gitignored`.
Wave 3 must reconcile the pty_manager opaque id with the registry session_id
(reuse the PTY id as session_id is simplest).

**Verdict: GO.**

---
