# Provider implementation plan v2 — Refinement 2

October 7, 2026. This is a refinement of the same Setup and Mother Ship effort, carrying forward the complete functional baseline in [plan v2](IMPLEMENTATION-PLAN-v2.md), [scope v6](SCOPE-v6.md), earlier scopes and original conversation. It does not start another effort or close a slice.

## Settled answer and current evidence

John's feedback `113e63ee-c4dd-4a35-9668-7b6b027de92a` confirms that Cave's gear opens the Providers tab and accepts that placement. It requests usable subscription and optional API connections for Claude, ChatGPT, Gemini and Grok, multiple accounts, nicknames, summaries in Cave's left sidebar, and switching between accounts and model versions. This confirms the opening path, not complete provider delivery or slice acceptance.

Answer `2a3f9c71-b01b-4037-a3f0-6413483f93dc` accepts provider-owned sign-in launched from Anchor, using email/password where supported, then retaining each connection on the mother ship. This settles the sign-in design; do not ask it again. API credentials remain a separate option. Passwords are entered at the provider's sign-in page, not collected in the conversation or an Anchor password registry. Provider sessions and API secrets stay on the mother ship.

The assurance integration landed with 93 tests passing, and the shell gear repair landed with its production-shell/browser gate passing. John has now opened Cave's gear in his own client. Claude and ChatGPT verification currently reuses existing host-side Claude Code and Codex sign-ins; it does not retrieve Chrome passwords. Named connection metadata, some isolated native enrollment, API credential storage and account preferences already exist, so refinement must extend these mechanisms rather than create a second account registry.

Gemini and Grok must not be represented as complete. John clarified in turn `94ff670b-5f9d-4ac7-9426-d4e80a4a0b9e` that his Google Ultra account already authenticates the `agy` command-line interface. Retain that connection; the Antigravity IDE is not part of this workflow. Do not require a separate Gemini CLI or a duplicate Google subscription connection. Grok's supported enrollment, account isolation and account-report interfaces still need verification. Authentication, usable execution and reported allowance are separate facts.

## Refined deliverable and existing map

| Existing step | Part | Required result |
| --- | --- | --- |
| gwl-access | integrate | Add account starts the provider's supported sign-in, retains a separate connection on the mother ship and preserves existing default sign-ins. All four providers are represented. Optional API keys use separate, explicitly labeled connections and secure host storage. Each connection has its own stable identity and editable nickname. |
| gwl-provider-status | slice | Each named account shows authentication, verification result, subscription allowance/reset and API usage/cost where a supported source provides them. Show source/freshness and explicit unknown/unsupported states; never infer allowance from a login or present an unavailable account as usable. |
| gwl-cave-settings | integrate | Cave's lower-left summary shows provider, nickname, selected account and model/version, plus the agreed capacity information. Switching Claude 1 to Claude 2 selects the corresponding isolated identity for new work. Existing conversations keep their original account/session, drafts and quality settings. Setup and Cave use the same connections and preferences. |
| gwl-laptop-provider-test | rigor | Prove enrollment, two accounts of one provider, account-qualified summaries, nickname persistence and actual routing of new work, then verify the working controls in John's existing laptop client. Test each provider and subscription/API mode separately; a partial result is not four-provider completion. |
| gwl-software-review / gwl-provider-harden | rigor / harden | Carry the v2 independent review, reproducible failures, credential boundaries and re-review into the changed adapters and UI. Earlier assurance receipts remain evidence for their original revision, not proof of this unbuilt refinement. |

Keep the settled personal mother ship, warning/full-strength policy, Star Chart organization, optional calendars/email, backups and parked cross-host collaboration. No automatic billing fallback, credential replacement, provider installation, transport switch or live-session restart is authorized by opening Setup. API execution is currently restricted by the subscription-seat mechanism; storing a key alone must not be called a usable API connection. The implementation must establish a supported explicit route and prove it, or report the precise gap.

## Settled Google connection

John's October 7 clarification closes the transport question: use his Google Ultra-authenticated `agy` CLI for Gemini model access. An IDE login or IDE installation is not required. Provider-owned browser sign-in, retained on the mother ship, remains the accepted enrollment policy; use only the installed adapter's verified account-isolation and authentication interfaces. Preserve its existing account and all live sessions. Do not create a second Google account, install a different CLI, or change live routing merely because the visible provider label says Gemini.

Implement the requested four-provider account refinement using the existing adapters and account registry. Where an installed provider cannot safely enroll another isolated subscription or report allowance, return its precise supported-interface prerequisite and keep that provider incomplete; do not relabel an API key as a subscription or invent an allowance. Each provider's enrollment and execution are independently tested, while the requested whole product stays open until all required connections and John's actual client experience are verified.

Sources and prior versions remain in [Refinement 1](IMPLEMENTATION-PLAN-v2-refinement-1.md) and the approved assurance baseline. The Google connection is now established by John's original account/CLI clarification, rather than an assumption about his IDE use.

## Build and acceptance boundary

Long implementation stays in an Anchor code job's own worktree under the existing functional build authorization and the now-settled sign-in/Google connection choices. Foreman executes, independently reviews, fixes and rechecks changes; no nested run or overlapping shared-tree edits. Resolve the current model policy at dispatch. Preserve the root Foreman configuration during placement; exclude the runner's temporary configuration from intended product changes.

The refinement's failing gate must exercise the new deliverable, alongside existing regressions:

`python -m pytest -v tests/test_provider_account_refinement.py tests/test_provider_setup.py tests/test_provider_setup_browser.py tests/test_provider_setup_rigor.py tests/test_provider_setup_hardening.py`

The new test file is a future implementation requirement, not an existing test or a passing receipt. It must exercise provider-owned enrollment links, isolated account attribution, nickname persistence, selected-account routing, explicit API billing, missing-provider/error states and unchanged running conversations. Browser proof must use normal authentication and guard both GET steward event soft-wakes and work-start POSTs. Do not enroll real accounts or launch paid verification turns merely to display a summary.

Return the actual supported-provider matrix, test and independent-review receipts, and the precise client activation requirement. Verify John's actual window after safe activation; a fresh browser alone is insufficient. No slice or campaign closes without John's explicit instruction.

## Latest workflow feedback - same refinement

John turn efeca945-c130-4ccf-8d23-b32b3fff3d07 reiterates the original functional build and first-launch order. The earlier waiting helper is absent and its receipt never advanced beyond queued: this refinement has not started or landed. Do not claim a termination cause. Restore the handoff after the current Anchor owner releases; preserve all prior answers.

First launch asks whether this computer hosts the personal mother ship or connects to an existing one through Tailscale. An existing-host client pairs securely and reuses its host's accounts; no provider secrets or Foundry install on the client. A new host installs the existing Anchor/Foundry package through the established installation mechanism and trusted distribution source. Use an automated installation where it is already supported; if agent help is essential, connect one subscription before that assistance, with subsequent provider editing available in Setup. Verify the actual executable bootstrap, installed prerequisites and failure/resume behavior rather than inventing an installer or pretending an HTML walkthrough installed a service. A missing installer/source/interface remains an explicit unmet prerequisite.

Setup offers all four provider families and editable named subscription/API connections: add, provider-owned sign-in, validate/test, save, reopen from the gear, rename, reconnect and remove. Two Claude subscriptions remain independently usable and visible. Google Ultra continues through agy; investigate the installed Grok and agy sign-in/status capabilities. Unconnected accounts/models are disabled for execution; provider Add account remains reachable. Display safe account identity and connection details with protected/masked secret fields, never reveal stored passwords or keys in chat or summaries.

Cave's lower-left panel contains status/usage summaries only: each saved account's nickname, provider/model, reported remaining/available allowance or usage, plus an explicit unavailable/stale state where no supported metric exists. No signup copy, credential forms, installation instructions or enrollment buttons in that summary. Account/model selection for new work stays available; management belongs in Setup. Keep separate rows for both Claude accounts, preserve current conversations, and avoid treating a missing connection as a usable model.

Nothing cut from the requested product. Deferred cross-host collaboration, email/calendar integration and automatic paid fallback remain outside this refinement. The first-host installation sequence is carried forward as part of the existing map, not a competing effort.
