# Doctor: jobs-route timeout — October 3, 2026

Status: correction in progress; final activation and full health check pending.

The 5 AM declared-route auth walk (W8) walked 228 rows and timed out on `GET /api/rnd/jobs`. A live Doctor re-probe failed the same route. No campaign data or skills were changed to clear this issue.

## Reproduction and cause

- Live `/api/version`: HTTP 200 in 0.022 seconds.
- Original live `/api/rnd/jobs`: HTTP 200 after 4.909 seconds, returning 59,767,134 bytes.
- Exact Doctor-style status-only probe with a four-second timeout: `TimeoutError` after 4.052 seconds.
- At inspection, 19,287 historical job records occupied 68,261,124 disk bytes; normal subsequent growth produced 19,325 rows.

The route read and decoded every full historical record, then serialized large private payloads before sending response headers. Its public/auth classification was unchanged; the delay occurred while building the response.

## Correction and verification so far

The correction returns cached lifecycle/usage summaries and preserves the complete records for their existing consumers. It coalesces simultaneous refreshes so concurrent requests share one scan. A read-only benchmark against real records measured 2.435 seconds cold and 0.961 seconds warm, with a 9.18 MB response.

The final six focused regression tests passed in 0.80 seconds. A broader legacy gate returned 35 passes and 20 failures, including ambient preference/overlay expectations, older relaunch/UI assertions, and Windows temporary-directory cleanup. That gate is not claimed green.

An initial four-request concurrency check produced two HTTP 200 responses (2.517 and 3.816 seconds) and two four-second timeouts (about 4.075 seconds). After refresh coalescing, four simultaneous read-only HTTP requests against the real historical corpus all returned HTTP 200: headers arrived in 3.094–3.317 seconds and full bodies in 3.309–3.345 seconds, within Doctor's four-second limit. Review, live activation and the final full check remain pending.

## Final verification scope and activation

Final review passed. Activation was armed at 07:41:02 through the supported maintenance drain barrier (generation 1). It reported two busy Campaign turns and zero running jobs. At 07:57:46 the watcher reported one busy turn; the old build remains `591bd63+b349f64` while draining. A hidden watcher for this maintenance operation will perform a four-second live probe when the build changes. There is no forced restart or live hot reload.

The first `doctor-jobs-2026-10-03-run.py` attempt launched at 07:51 while safe activation still waited for the two active turns. Its setup was invalid: `_find_free_port(0)` returned zero unchanged, so the owned GUI bound an OS-selected port while readiness probes targeted port zero. Readiness did not complete and no valid server checks ran. The exact verified wrapper PID 115260 and child GUI PID 119492 (parent 115260, `--port 0`) were stopped; the wrapper exited 1. The live service PID 32012 was excluded and remains running. This setup failure is not a health-check pass.

The runner now obtains a concrete ephemeral port using a socket bound to `127.0.0.1:0` and rejects zero or the live-service ports 8777/8778. A corrected valid full run remains required. It uses an owned data snapshot, retaining historical payloads, marking copied terminal records metadata-only to prevent external handoff writes, and excluding live campaign/session registries. Only unsafe age/port-based termination of unrelated listeners is omitted; correctness checks remain enabled. The invalid attempt's owned log remains `logs/doctor-jobs-2026-10-03-wrapper.log`.

The valid full check will stage its report. Any immediate read-only four-second live probes that reach the old build must not count as verification of activation. After safe activation, the final active-service receipt will be recorded before publication.

The existing daily report will be preserved before a reviewed current report is published. The newest dated report determines Doctor state; no separate issue-store clearing is needed. Final results and report publication remain pending.
