# Provider integration assurance — description (Foreman input, derived from plan v2)

This document names what is under assurance and why, for Foreman's contract. The authority is John's approval of the bounded Foreman heavy contract in `Setup and Mother Ship/IMPLEMENTATION-PLAN-v2.md` (turn 087893eb, 2026-10-06T00:42Z). The functional baseline is unchanged: `Setup and Mother Ship/SCOPE-v6.md` and implementation plan v1 (appended to plan v2). Nothing here reopens the approved product design; it examines the implementation.

## The product under review

Anchor's provider integration (commit 64df9a6) and its loading repair (commit b24f922). One personal mother ship holds provider credentials and runs AI work for connected devices. The Setup page (`/setup`, Refinement 2 layout) and the Cave's upper-left gear and bottom-left provider/model controls share one host-side provider service:

- `provider_setup.py` — the service (`ProviderService`: capability probe, refresh, snapshot, add/rename/apply, login start/status/cancel), the `AccountUsageReader` ledger cache from the loading repair, `claude_allowance`, `require_capacity_choice`, `selected_for_launch`, `resolve_quality`, and the eleven normally authenticated routes (`/setup`, `/setup/install`, `/api/provider-setup`, `/api/provider-setup/login`, and the POSTs `initialize`, `accounts`, `rename`, `apply`, `login`, `cancel`, `api-key`).
- `provider_native.py` — bounded hidden native commands (`HiddenProcess` with a job object, `CodexAccount` JSON-RPC over stdio, `NativeProviders.capabilities/observe/login`), allowlisted fields, `safe_auth_url`, `account_home`/`account_env`/`private_account_path`.
- `provider_secrets.py` — optional API credentials in the Windows credential vault, never in JSON.
- `provider_settings.py` and `anchor_settings.py` — non-secret connection metadata and preferences inside the existing settings store, with revision-guarded saves.
- `static/provider-setup.html`, `static/provider-setup.js`, `static/provider-controls.js`, `static/provider-setup.css`, `high_seat_page.py` — the Setup page, the shared controls, the Cave gear, controls and capacity button.
- `route_table.py`, `anchor_gui.py`, `report_viewer.py`, `steward_cockpit/steward_routes.py` — route registration and the private-credential guard on artifact and project-file routes.
- `job_runner.py`, `steward_cockpit/steward_engine.py`, `steward_cockpit/codex_turn_bridge.py` — execution routing: new jobs and new conversations bind the selected account's native home and quality; existing conversations keep theirs.
- `usage_capacity.py`, `usage_capture.py` — account-qualified usage and rate-limit attribution.
- `tests/test_provider_setup.py`, `tests/test_provider_setup_browser.py` — the author's 60 service/route tests and 3 browser tests (63 passing at the start of this assurance).

## Why independent assurance

This software handles provider credentials and routes work between separate account identities, and a normally authenticated real-service refresh timed out before refreshing native status (17.1 s on the unchanged live service). The landed tests are evidence for the cases they exercised; they do not prove robustness of untested failure paths, working enrollment, unsupported providers or an actual existing client. Two fresh, read-only reviewers from the independent family must return substantive findings with file/line evidence; missing, same-family or failed reviewers cannot be described as cross-family assurance.

## What this assurance is not

Not acceptance. Technical readiness is bounded evidence. John's laptop verification of the existing client, his feedback and his explicit close remain his. No restart of the running service, no change to global model or provider preferences, no enrollment or replacement of real credentials, and no new product scope.
