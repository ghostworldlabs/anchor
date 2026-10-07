# Driver pre-read findings — reproduced 2026-10-05 19:50-19:52 (sandbox: temp data dir + temp home, worktree code at HEAD f77710c, no files modified)

Reproduction scripts: repro_h1_h2_h3.py, repro_h4.py (this folder). Outputs: repro_h1_h2_h3.out, repro_h4.out.

## H1 — apply refuses every preference save unless the selected account has a fresh, successful native observation (provider_setup.py:205-207, :260)
Command: python repro_h1_h2_h3.py
Observed:
  H1a cold start (no native observation yet), threshold-only apply: REFUSED -> ValueError: Selected account is unready for execution; refresh its host status
  H1b fresh observation, threshold-only apply: SAVED
  H1c observation aged past TTL (301 s), threshold-only apply: REFUSED (auth=signed_in, auth_stale=True, ready=False)
  H1d after a timed-out refresh, threshold-only apply: REFUSED
Severity (driver): MAJOR — on the live service the refresh is slow and has timed out; after any service restart the observation map is empty, so no preference (threshold, warning policy) can be saved until a native refresh succeeds.

## H2 — apply re-validates an unchanged saved exact quality against a stale catalog (provider_setup.py:262-272)
Observed:
  H2a fresh catalog, save exact quality claude=balanced/high: SAVED
  catalog state after ageing past TTL: stale
  H2b catalog aged, threshold-only apply (quality unchanged): REFUSED -> ValueError: Refresh native model capabilities before choosing an exact model or effort
Severity (driver): MAJOR — same consequence as H1 for anyone who ever saved an exact model.

## H3 — a never-supported report is relabelled stale after a failed refresh (provider_setup.py:147-154, :162-164)
Observed:
  before failure: provider_usage state=unsupported tokens=None observed_at set=True
  after timeout: provider_usage state=stale tokens=None error=timeout
Severity (driver): MINOR — honesty of the label; the UI renders "Not reported · stale" for a report that never existed.

## H4 — default native credential homes are served through authenticated project/artifact routes (provider_native.py:54-59; anchor_gui.py handle_project_file_content / handle_ecgberht_artifact; report_viewer.py:395-403)
Command: python repro_h4.py (project folder = the temp home; sentinel planted in .codex/auth.json and .claude/.credentials.json)
Observed:
  /api/rnd/project_file_content?project_id=p&path=.codex/auth.json -> 200 SENTINEL LEAKED
  /artifact/p?path=.codex/auth.json -> 200 SENTINEL LEAKED
  /api/ecgberht/artifact?project_id=p&rel=.codex/auth.json -> 200 SENTINEL LEAKED
  /api/ecgberht/chamber_artifact?project_id=p&rel=.codex/auth.json -> 502 no leak
  (same for .claude/.credentials.json)
  report_viewer.resolve_project_artifact(home, '.codex/auth.json') -> returns the file bytes
  steward deliverable-file -> 200 no leak (returns a reference, not content)
Severity (driver): MAJOR with a precondition — the caller must be authenticated and a registered project folder must enclose the user's home. private_account_path's own docstring promises native credential homes are never project artifacts; the default homes hold the most valuable credentials.

## H5 — refresh route runs every native command synchronously (measure, not fix) · H6 — login success + failed status read reported as failure (MINOR)
Not reproduced by the driver (H5 requires a counting substitute for the real CLIs — assigned to the Wave-1 executor; H6 is a message-honesty observation).

## W1-G1 (found by the Wave-1 gate, 20:17) — login-status GET is misrouted when it carries a query string (provider_setup.py:542 handle_get; anchor_gui.py _strangler_dispatch "Always hand handlers the FULL request URI (query included)")
Reproduction: tests/test_provider_setup_rigor.py::test_cached_read_during_native_refresh[cached-read-during-native-refresh] — authenticated GET /api/provider-setup/login?id=<unknown 32-hex> answered 200 with the whole provider snapshot instead of 400 "Host provider status is unavailable; existing setup is retained" (gate artifact .foreman/wave-1-gate.json, iteration 0: exit 1 · 67 pass · 1 fail · 8 xfailed).
Mechanism: handle_get compares `path == "/api/provider-setup/login"` but the dispatcher passes `handler.path` including `?id=...`, so the comparison fails and the call falls to SERVICE.snapshot(). The Setup page's scheduleLogin() polls exactly this URL, so every sign-in progress poll receives a snapshot: drawLogin() ignores it (no connection_id) and polling stops (no state) — the browser never shows the device link/code updates or completion.
Severity (driver): MAJOR — the terminal-free native sign-in's progress display cannot work on the live service. Disposition: fixed in Wave 1 fix iteration (pending re-gate).

## Wave 1 independent review — two fresh Grok seats, driver-run (engine seats transport-failed twice with grok-cli protocol_error; see .foreman/wave-1-review-1.json and -2)
Method: `grok --output-format json --model grok-4.7 --reasoning-effort xhigh --permission-mode plan --max-turns 40 --prompt-file <prompt>` from the worktree; the prompt carries the plan contract, the gate artifact summary, the numbered rigor test file, the product diff vs f77710c and the numbered provider_setup.py/provider_native.py (136,852 chars), so the read-only seat needs no shell command. Both seats fresh contexts, independent processes.
- seat 0: served grok-4.7-build (modelUsage), 34 turns, 728 s, answerable=yes, 9 findings → w1-review-0.findings.json
- seat 1: served grok-4.7-build (modelUsage), 36 turns, 674 s, answerable=yes, 9 findings → w1-review-1.findings.json
Agreement (≥2 seats): H4 BLOCKER; H1 MAJOR; H2 MAJOR; W1-E1 MAJOR; H3 MINOR; H6 MINOR; rigor test browser assertion partly vacuous (MINOR, tests/test_provider_setup_rigor.py:537).
Seat-0-only: provider_setup.py:156 claude_allowance() unconditionally replaces a retained Claude window on a SUCCESSFUL refresh (MAJOR) — driver-REPRODUCED 20:58: after a refresh with a qualified rate_limit_event the window is fresh (1 window); after the signal disappears the next successful refresh reports state=unsupported, windows=0, observed_at=None instead of retaining the window as stale. provider_native.py:65 account_env never pops GROK_HOME (MINOR) — driver-REPRODUCED: GROK_HOME from the process env is present in a Claude connection's account_env.
Seat-1-only: usage_capacity.py:278 the Cave rail's Claude row still uses the unqualified latest_limit_signal (MINOR; the row's own note says two accounts cannot be told apart — honest but unqualified; pre-existing surface). provider_setup.py:93 capability(refresh=True) returns a cached `error` probe for the whole TTL, so a transient probe failure refuses `add()` for 300 s and an explicit refresh does not retry (MINOR) — confirmed by reading.
H4 escalation (seat 0's basis, driver-VERIFIED 20:58): route_table.py:164 declares GET /artifact/ AUTH_OPEN; an UNAUTHENTICATED GET /artifact/p?path=.codex/auth.json against a project folder enclosing the temp home returned 200 with the planted credential sentinel; /api/rnd/project_file_content without a cookie returned 401. The provider guard (private_account_path) is the in-scope fix; the openness of /artifact/ itself predates this work.
H5: both seats agree it is a measurement, not a defect (13 hidden native commands per cold refresh, asserted by the gate).

## Live-preferences provenance check (22:12)
<main checkout>\settings.json read coding=claude / review=chatgpt / revision 27 at 19:45 and reads coding=claude / review=grok / revision 29 at 22:12 (mtime 19:52:29; a revision-28 backup at 19:52:07). The mirror ~/.anchor/model_prefs.json carries primary_path=<main checkout>\settings.json and source=anchor at the same second: both writes came from the live Anchor service (its own dashboard save path), not from this job. Every process of this job ran with ANCHOR_DATA_DIR pointed at a temp folder (the isolated copy is untouched: mtime 19:42:54, revision 27) or with the worktree as data dir (no settings.json exists there). The live change made the dashboard's own review family equal to the seat routing used here (Grok), so the isolated preferences and the live preferences agree from 19:52 on.
