# Connection readiness v1

Distribution and Collaboration — 4 October 2026. This is preparation for the saved connect-first trial, not a completed cross-device trial or an approved release.

## Current position

Ghost World Lab License v1, Refinement 2 and its focused Legal-Beagle review are ready. John deferred reading them in original turn `f0c9ecc4-681b-43c2-8b6d-a0911349bcc7`, 2026-10-05T00:31:27.078595Z, and asked to carry on. They remain unaccepted; their review does not block independent connection preparation.

The first trial still connects an additional device to an existing mother ship before independent new-host installation. Setup's accepted ownership applies: each person has their own mother ship; their other computers and phones connect to it. Sharing information/projects between different people's mother ships is parked. These are recovered decisions, not new questions: Setup turns `35bc13bb-fd8a-4be5-b257-be6062683f25` and `84ec3037-96cb-4e13-87c5-f99f49888de2`. Both installation paths and Windows/Linux/macOS coverage remain in the same roadmap.

## What the existing code establishes

| Evidence | Current observation | Limit |
| --- | --- | --- |
| `shell/connect.py:17`, `setup_page` | A new client is prefilled with John's real host address and uses PUTER-specific wording | Not suitable as a generic recipient's first-run page |
| `shell/connect.py`, `normalize` and `choose` | Remote HTTPS, local loopback HTTP, explicit/local/saved address selection already exist | Preserve these behaviors and existing settings |
| `shell/connect.py`, `reachable` | Checks for an Anchor app page answering at the selected address | Does not establish owner identity, pairing or actual Tailscale authorization |
| `shell/anchor_shell.py`, `Host.connect`, retry and app opening | Existing connect/save/retry path uses that shared connection helper | Reuse it; do not introduce a second onboarding stack |
| Existing connection and shell-host tests | Focused regression coverage exists; the Windows shell is separate from the server export | No fresh tests or real-device trial have yet been claimed in this readiness audit |
| Setup scope v5 and mockup Refinement 2 | New first-launch/provider/settings layout awaits its human review | Integrating that layout remains conditional; this preparation does not bypass it |

June/July completion receipts are historical starting evidence. They do not establish acceptance or delivery of the October Setup surface. This audit was read-only and used root-read source excerpts; its bounded helper performed no test or network operation.

## Windows connection client v1 — implementation brief

Prepare the existing connection page for any recipient's own mother ship. A fresh installation must ask for that owner's address instead of populating John's real host. Show a synthetic address only as a nonactive example. Replace author-specific PUTER wording in connection, retry and recovery messages with language about the selected mother ship. Existing saved addresses, explicit overrides, local-first selection, unrelated settings and HTTPS restrictions must continue to work.

Use the existing `shell/connect.py` and `shell/anchor_shell.py` path. The scope is a reversible portability correction, independently authorized by John's continuation and the recovered personal-host requirement. Keep the separate shell/server packaging boundary. Do not implement the unreviewed Setup mockup, redesign authentication, join Tailscale, change credentials or services, move files, publish repositories/releases, apply the license, or close any slice. Linux/macOS and independent installation remain later required verification, not claims from this Windows preparation.

Add meaningful regression coverage for a blank fresh-client address, absence of the author's host/name in generated pages, safe example handling, unchanged saved/explicit/local selection and persistence, and recovery behavior. Use hermetic fixtures. The job's gate is:

```text
python -m pytest -q tests/test_app_shell_connect_2026_10_03.py tests/test_app_shell_host_2026_10_02.py
```

Check the actual generated connection/recovery pages in a controlled browser with no service/network/account changes. Capture normal and narrow viewport evidence outside the repository at `C:/Users/john/AppData/Local/anchor-distribution-preparation/20261004-connect-v1/render/`, and report observed behavior and any prerequisite failure honestly. Do not certify actual Tailscale access or another device from a localhost/render check.

The code job uses the best configured model at full effort in its own worktree. It edits code/tests only; the steward owns the roadmap, register, journal and human result. The controller commits and lands the job; the coder must not commit or alter other sessions' files. At preparation time the Cave display job owns Anchor, so this job must wait for ownership to be released before starting. No source code was changed by this document.

## Completion and next prerequisite

The portability correction is ready only when the focused gate and rendered pages pass and the controller's actual landing result is checked. That does not complete the release step. A subsequent real same-owner trial needs the actual host/client pair, authorized secure access, and any shared Setup functionality it uses. Final publication separately needs license acceptance and rights clearance. No new question is needed to perform this narrow preparation.
