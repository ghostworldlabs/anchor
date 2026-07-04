# C4 live-demo runbook — restart survival on the real service (rearch W17)

**Criterion (C4, non-negotiable half):** a spawned lane job keeps running across
`nssm restart anchor`, and the restarted dashboard reports it live with an
advancing tail. **This criterion is honestly UNMET until this runbook has run
once on the real service** — the hermetic gate proves the mechanism; only a live
run proves the cross-process survival. Run this WITH John, in one sitting.

The mechanical steps below are scripted by the harness `tools/c4_live_demo.py`
so this runbook is *executable*, not prose. The harness building blocks
(`setup_demo_project` · `launch_demo_job` · `verify_survival` · `rollback_demo`)
are production-safe and operate against the LIVE `ANCHOR_DATA_DIR`; the only
difference between the gate and this live run is that here the restart is the
REAL `nssm restart anchor`, not a simulated in-memory table teardown.

---

## Prerequisites

- The `anchor` NSSM service is running on :8777 (`Get-Service anchor`).
- The supervisor service is installed (`install_supervisor.ps1`) and the
  dashboard is in **external** mode (`ANCHOR_SUPERVISOR=external`), so job
  ownership already lives in the separate process (W16). If the supervisor is
  down the dashboard degrades to inline and the demo still proves the durable
  re-adoption, but the true cross-process survival needs external mode.
- An elevated PowerShell (nssm restart requires it).
- `ANCHOR_RUNNER_CMD` points at the deterministic `tests/fake_claude.py` mock
  for the demo job — **no real model call, no side effects**.

## Step 1 — register a dedicated THROWAWAY R&D project

A disposable project, never a real one, rooted at a scratch folder:

```powershell
# scratch folder OUTSIDE the repo (git stays clean)
$root = Join-Path $env:TEMP "c4-live-demo"
python tools\c4_live_demo.py --root $root --simulate-restart:$false
```

Or, driven from the dashboard: **New project** → name `C4 Live Demo (throwaway)`
→ point it at the scratch folder. Note its `project_id`.

## Step 2 — launch a harmless long-running job through the REAL launch path

Launch a **build** lane job (folder-locked, so the demo proves BOTH the lane
slot and the folder-build lock survive) that drips lines for ~10s then sleeps —
the same lane-guarded launch the dashboard's `/api/rnd/launch_lane` build path
uses (`supervisor.launch_guarded`). fake_claude-driven, harmless:

```
--lines 60 --line-interval 0.15 --sleep 3
```

Confirm it is live: the project window shows a running (green) tile with an
advancing tail; note its `job_id`.

## Step 3 — restart the dashboard MID-FLIGHT (the demo)

From the elevated shell, with the job still dripping lines:

```powershell
nssm restart anchor
```

## Step 4 — expected observations (the criterion, demonstrated)

After the restart, WITHOUT relaunching the job:

- The job process **never stopped** — its OS pid is still alive across the
  restart (supervisor-owned; the dashboard restart did not reap it).
- The restarted dashboard lists the **SAME `job_id`** as running (re-adopted
  from the durable records at boot — `supervisor.rebuild()`).
- Its `/api/rnd/tail` cursor **keeps advancing** (the persisted read offset
  survived and the log kept growing).
- The lane slot and the folder-build lock are **rebuilt** (a second launch in
  the same lane/folder is still serialized).
- `cancel` from the dashboard **tree-kills** the job cleanly.

Record the observed `job_id`, the pre- and post-restart tail offsets, and the
pid liveness in the execution log below.

## Step 5 — rollback (supervisor stop + lane-lock clear)

Always leave the service clean:

```powershell
# 1. cancel the demo job (reaps the process AND releases the lane lock)
#    — via the dashboard Stop button, or:
python tools\c4_live_demo.py  # run_demo always rolls back in its finally

# 2. clear any stranded lane lock defensively (idempotent)
#    rollback_demo() calls job_runner.release_slots(job_id) for this.

# 3. retire the throwaway project (kept, never hard-deleted)

# 4. if the supervisor was started only for the demo, stop it:
nssm stop anchor-supervisor
```

The harness `rollback_demo(sup, job_id, project_id)` performs steps 1–3
mechanically and never raises; step 4 (**supervisor stop**) is the ops command.

---

## Execution log

> **STATUS: NOT YET RUN.** This cell is filled in only after the runbook is
> executed live on the real service WITH John — it is never fabricated. Until
> then C4's live half is honestly unmet (the hermetic gate
> `tests/test_c4_w17.py` proves the mechanism; this cell proves the deploy).

| field | value |
|-------|-------|
| date run | _(pending)_ |
| operator | _(pending — run WITH John)_ |
| project_id | _(pending)_ |
| job_id | _(pending)_ |
| tail offset before restart | _(pending)_ |
| tail offset after restart | _(pending)_ |
| job pid alive across restart? | _(pending)_ |
| same job_id listed live after restart? | _(pending)_ |
| cancel tree-killed cleanly? | _(pending)_ |
| rollback clean (lane lock cleared, project retired)? | _(pending)_ |
| supervisor mode during demo | _(pending — external expected)_ |
| notes | _(pending)_ |
