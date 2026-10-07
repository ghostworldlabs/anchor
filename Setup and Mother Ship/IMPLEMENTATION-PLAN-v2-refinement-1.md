# Provider implementation plan v2 — Refinement 1

October 7, 2026. This is a refinement of the same Setup and Mother Ship effort, carrying forward the complete functional baseline in [plan v2](IMPLEMENTATION-PLAN-v2.md), [scope v6](SCOPE-v6.md), earlier scopes and original conversation. It does not start another effort or close a slice.

## Settled answer and current evidence

John's feedback `113e63ee-c4dd-4a35-9668-7b6b027de92a` confirms that Cave's gear opens the Providers tab and accepts that placement. It requests usable subscription and optional API connections for Claude, ChatGPT, Gemini and Grok, multiple accounts, nicknames, summaries in Cave's left sidebar, and switching between accounts and model versions. This confirms the opening path, not complete provider delivery or slice acceptance.

Answer `2a3f9c71-b01b-4037-a3f0-6413483f93dc` accepts provider-owned sign-in launched from Anchor, using email/password where supported, then retaining each connection on the mother ship. This settles the sign-in design; do not ask it again. API credentials remain a separate option. Passwords are entered at the provider's sign-in page, not collected in the conversation or an Anchor password registry. Provider sessions and API secrets stay on the mother ship.

The assurance integration landed with 93 tests passing, and the shell gear repair landed with its production-shell/browser gate passing. John has now opened Cave's gear in his own client. Claude and ChatGPT verification currently reuses existing host-side Claude Code and Codex sign-ins; it does not retrieve Chrome passwords. Named connection metadata, some isolated native enrollment, API credential storage and account preferences already exist, so refinement must extend these mechanisms rather than create a second account registry.

Gemini and Grok must not be represented as complete. The current Gemini execution transport is Antigravity (`agy`); the requested Google AI/Gemini subscription connection needs to be distinguished from that existing access. Grok's supported enrollment, account isolation and account-report interfaces still need verification. Authentication, usable execution and reported allowance are separate facts.

## Refined deliverable and existing map

| Existing step | Part | Required result |
| --- | --- | --- |
| gwl-access | integrate | Add account starts the provider's supported sign-in, retains a separate connection on the mother ship and preserves existing default sign-ins. All four providers are represented. Optional API keys use separate, explicitly labeled connections and secure host storage. Each connection has its own stable identity and editable nickname. |
| gwl-provider-status | slice | Each named account shows authentication, verification result, subscription allowance/reset and API usage/cost where a supported source provides them. Show source/freshness and explicit unknown/unsupported states; never infer allowance from a login or present an unavailable account as usable. |
| gwl-cave-settings | integrate | Cave's lower-left summary shows provider, nickname, selected account and model/version, plus the agreed capacity information. Switching Claude 1 to Claude 2 selects the corresponding isolated identity for new work. Existing conversations keep their original account/session, drafts and quality settings. Setup and Cave use the same connections and preferences. |
| gwl-laptop-provider-test | rigor | Prove enrollment, two accounts of one provider, account-qualified summaries, nickname persistence and actual routing of new work, then verify the working controls in John's existing laptop client. Test each provider and subscription/API mode separately; a partial result is not four-provider completion. |
| gwl-software-review / gwl-provider-harden | rigor / harden | Carry the v2 independent review, reproducible failures, credential boundaries and re-review into the changed adapters and UI. Earlier assurance receipts remain evidence for their original revision, not proof of this unbuilt refinement. |

Keep the settled personal mother ship, warning/full-strength policy, Star Chart organization, optional calendars/email, backups and parked cross-host collaboration. No automatic billing fallback, credential replacement, provider installation, transport switch or live-session restart is authorized by opening Setup. API execution is currently restricted by the subscription-seat mechanism; storing a key alone must not be called a usable API connection. The implementation must establish a supported explicit route and prove it, or report the precise gap.

## Remaining Google prerequisite

One materially different choice remains: does John's Gemini connection mean his Google AI/Gemini subscription, or only the existing Antigravity access? Recommend adding the Google AI/Gemini subscription as a separate connection while preserving Antigravity for existing work. This choice affects the authentication adapter and which subscription's allowance is being summarized. It does not reopen the accepted provider-owned sign-in policy. Record the answer in the next refinement of this same plan before fixing that adapter's scope.

Known sources: [Gemini CLI authentication](https://geminicli.com/docs/get-started/authentication/) documents Google-account sign-in for Google AI subscriptions and separate API keys. [Codex authentication](https://learn.chatgpt.com/docs/auth) documents persistent native sign-in. [xAI's Kilo integration](https://x.ai/news/grok-kilocode) documents a subscription OAuth integration; it is a discovery lead, not proof that Anchor's existing Grok transport supports the same account interface.

## Build and acceptance boundary

Long implementation stays in an Anchor code job's own worktree after the prerequisites affecting its scope are settled. Foreman executes, independently reviews, fixes and rechecks changes; no nested run or overlapping shared-tree edits. Resolve the current model policy at dispatch. Preserve the root Foreman configuration during placement; exclude the runner's temporary configuration from intended product changes.

The refinement's failing gate must exercise the new deliverable, alongside existing regressions:

`python -m pytest -v tests/test_provider_account_refinement.py tests/test_provider_setup.py tests/test_provider_setup_browser.py tests/test_provider_setup_rigor.py tests/test_provider_setup_hardening.py`

The new test file is a future implementation requirement, not an existing test or a passing receipt. It must exercise provider-owned enrollment links, isolated account attribution, nickname persistence, selected-account routing, explicit API billing, missing-provider/error states and unchanged running conversations. Browser proof must use normal authentication and guard both GET steward event soft-wakes and work-start POSTs. Do not enroll real accounts or launch paid verification turns merely to display a summary.

Return the actual supported-provider matrix, test and independent-review receipts, and the precise client activation requirement. Verify John's actual window after safe activation; a fresh browser alone is insufficient. No slice or campaign closes without John's explicit instruction.
