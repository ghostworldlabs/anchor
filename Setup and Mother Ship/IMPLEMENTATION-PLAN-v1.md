# Provider integration — implementation plan v1

John accepted Setup mockup Refinement 2 as the starting layout and explicitly authorized its build and integration in turn `d7dd98a2-97a2-42f9-9273-c71b3e49cbf9` (October 4, 2026, Mountain time). The goal remains one personal mother ship holding provider credentials and running AI work for connected devices. This plan extends the existing roadmap, rather than starting another effort.

## What this build delivers

Keep the approved Setup page, gear and Cave controls, and connect them to real host-side provider settings. Existing native sign-ins should work without keeping terminal windows open. New sign-ins use the provider's normal browser/device flow; separately named subscriptions retain separate identity and reports. Explicit API connections retain their distinct billing mode.

| Existing roadmap step | Part | Implementation and proof |
| --- | --- | --- |
| gwl-access | integrate | Read existing sign-in status safely, add native login and supported account isolation; preserve the default account and active sessions. |
| gwl-provider-status | slice | Show real account-qualified allowance/reset reports where supported, separate observed tokens and API spend, and identify unknown, unsupported or stale reports. This remains the current ongoing slice. |
| gwl-cave-settings | integrate | Connect the upper-left gear and bottom-left provider/model controls to the same Setup settings; retain the separate capacity display and Cave dialogue state. |
| gwl-laptop-provider-test | rigor | Check routes, credentials isolation and real UI in the worktree, then verify the existing running laptop client after safe activation. |
| gwl-review | rigor | Let John use and refine the integrated product; preserve the accepted layout and earlier requirements. No slice closes without his explicit instruction. |

The code job owns implementation in its own worktree, using Anchor's latest selected coding model at maximum effort. Its gate is `python -m pytest -q tests/test_provider_setup.py`, with focused affected regressions and normally authenticated browser checks. A failed gate prevents automatic landing. Do not restart active sessions to activate code; inspect the actual change and use a safe boundary.

## Capability and scope limits

Codex documents account, rate-limit and usage reads; verify the installed version before promising a working meter. Claude's existing limit events need account qualification. Grok's native usage support must be verified. Unsupported fields stay explicit, never estimated as available allowance. Account authentication and quota availability are separate facts.

Keep the settled warning policy: full strength remains until the user explicitly changes it. Preserve existing projects, conversation identities, goals and pairing. No new installations, credential replacement, file consolidation or live provider work starts merely from opening settings or refreshing status. Native browser/device login is distinct from creating an independent OAuth client.

Nothing requested was cut. Calendars/email, backups and cross-mother-ship collaboration remain in their existing later places. Needed because live activation must preserve ongoing work; dropping the activation check risks interrupting active conversations.

Sources: [Codex app-server](https://learn.chatgpt.com/docs/app-server), [Codex authentication](https://learn.chatgpt.com/docs/auth), [Claude authentication](https://code.claude.com/docs/en/authentication), and the complete original effort conversation and scope v5. Scope v6 records this turn's accepted layout and implementation authorization.
