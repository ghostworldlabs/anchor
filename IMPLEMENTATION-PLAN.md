# Implementation plan — Anchor durability (2026-07 review, Plan 1 Wave C)

test-command: python -m pytest tests/test_durability_2026_07.py tests/test_review_fixes_2026_07.py tests/test_gate_adapter.py tests/test_gated_stdin_wiring.py tests/test_runner.py -q

Conventions for every wave:
- Python stdlib only (the repo rule; `distro.py` enforces it).
- All new behavior lands with tests in `tests/test_durability_2026_07.py`
  (create it in Wave 1; later waves append). Tests are hermetic: temp
  `ANCHOR_DATA_DIR`, `ANCHOR_RUNNER_CMD` → `tests/fake_claude.py`, never real
  claude / node / port 8777 — copy the fixture pattern of
  `tests/test_review_fixes_2026_07.py`.
- Never spawn a visible window: every new `subprocess` call passes
  `creationflags=_paths.NO_WINDOW`.
- Do not touch `anchor_gui.py` routes except where a wave names them.
- The orchestrator owns git and the gate; do not run git or the full suite
  yourself.

## Wave 1 — Re-launchable job specs

Goal: an `interrupted` job can be re-launched in ONE call from its durable
record.

In `job_runner.py`:
1. At launch time, persist a `relaunch_spec` field on the job record:
   `{lane, cwd, prompt, output_dir, gated, permission_mode, backend, env_keys}`
   — everything `launch()` needs to start an equivalent job. Store the SEED
   env keys only for the runner-seam variables (`ANCHOR_RUNNER_CMD`, `STUB_*`,
   `FAKE_*`, `ANCHOR_GANDALF_*`) — never the full environment (no secrets in
   records).
2. Add `relaunch(job_id) -> dict`: loads the record; refuses (honest
   `{ok:False, reason}`) unless `status == interrupted`; otherwise calls
   `launch()` with the spec, links the records both ways
   (`relaunched_as` on the old record / `relaunch_of` on the new one), and
   returns the new record. Refusal reasons are strings, never exceptions.
3. `reconcile_on_startup()` return value: unchanged (list of reconciled ids) —
   callers may relaunch selectively; no auto-relaunch (a restart storm must
   not launch N stale jobs unattended).

Acceptance criteria:
- A launched job's record carries a complete `relaunch_spec` (asserted field
  by field against the launch args).
- `relaunch()` on an `interrupted` record starts a new job that runs to DONE
  under the stub runner, with `relaunch_of`/`relaunched_as` links present.
- `relaunch()` on a running/done/cancelled record refuses with an honest
  reason; unknown id refuses; a record without a spec (legacy) refuses with
  `reason == 'no-relaunch-spec'`.

## Wave 2 — Durable gate answers

Goal: answering a gate must not require the original process's live stdin
pipe. An answer written while the job is dead is delivered on relaunch.

In `gate_adapter.py` (+ the reader hook in `job_runner.py`):
1. When a gate is marked awaiting-input, ALSO write a durable
   `<jobs_dir>/<job_id>.gate.json` (atomic tmp+replace under
   `paths.WRITE_LOCK`) carrying `{job_id, prompt, asked_at, answered: false}`.
2. `answer_gate(job_id, answer)`: if the job is LIVE, keep today's stdin-pipe
   path unchanged; additionally record `{answered: true, answer, answered_at}`
   in the gate file. If the job is NOT live (interrupted/dead), record the
   answer in the gate file and return `{ok: True, deferred: True}` instead of
   failing.
3. On `relaunch()` (Wave 1), if the old job has an unanswered gate file, carry
   it to the new job id; if it has an ANSWERED-but-undelivered gate file, the
   new job's seed prompt gets the pending answer appended as context
   (delivered-once semantics: mark `delivered_at`).
4. `load_pending_prompt(job_id)` prefers the durable gate file when the
   in-memory state is gone (post-restart), so the dashboard can still render
   the pending question for an interrupted job.

Acceptance criteria:
- Marking a gate writes the durable gate file; the record survives module
  reload (fresh import reading only disk state finds the pending prompt).
- Answering a DEAD job's gate returns `{ok, deferred}` and persists the
  answer; a subsequent `relaunch()` delivers it exactly once (asserted via the
  stub runner's received prompt + `delivered_at` set).
- The live-path behavior (stdin write for a running gated job) is unchanged
  (existing `test_gate_adapter.py` / `test_gated_stdin_wiring.py` stay green).

## Wave 3 — Gandalf in-progress boot reconcile

Goal: no perpetual "running" gandalf row after a restart.

In `gandalf.py`:
1. Add `reconcile_dangling_runs(folder_path, project_id) -> int`: for every
   index row with `in_progress: true` whose `run_id` is NOT in `_ACTIVE_RUNS`
   and whose session-registry record is not RUNNING-alive, upsert the row to
   an honest terminal record (`status: 'failed'`, `reason:
   'interrupted-by-restart'`, `in_progress: false`). Returns the reconciled
   count. Never raises.
2. Wire it into the server boot path in `anchor_gui.py` right after
   `job_runner.reconcile_on_startup()` — iterate the registered projects and
   reconcile each project's gandalf index (best-effort, wrapped, logged via
   the existing boot logger).

Acceptance criteria:
- A hand-planted `in_progress` row with no live run reconciles to
  `failed/interrupted-by-restart` (and `list_runs` shows no `in_progress`).
- A row whose run IS in `_ACTIVE_RUNS` is left untouched.
- The boot wiring calls the reconcile for registered projects (asserted with a
  spy on `reconcile_dangling_runs` through the boot function, stubbed env).
