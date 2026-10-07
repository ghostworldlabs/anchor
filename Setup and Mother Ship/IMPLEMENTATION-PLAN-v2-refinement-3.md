# Provider implementation plan v2 - Refinement 3

October 7, 2026. Proposed resolution and testing plan; implementation is held for John's answer. This continues Refinement 2 and the same eleven-step roadmap. No slice is closed.

## What John should get

Setup manages named subscription connections for Claude, ChatGPT, Gemini and Grok, including two separate Claude subscriptions and editable nicknames. Sign-in opens the provider's own page and retains the connection on the mother ship. Optional API keys remain distinct from subscription access and billing. Cave's lower-left panel shows each account's status, reported allowance/usage and model selection for new work; account management stays in Setup. Existing conversations retain their accounts and drafts. Google Ultra uses John's existing agy CLI, without an IDE or replacement CLI.

## Where we stand

The recovery landed as 1a542fe with 176 tests passing. The final reviews retained seven major concerns; a direct check reproduced unsafe remote-address handling. Passing tests and the controller's GO did not resolve these concerns. The new changes have not been activated or proved in John's existing window. The unrelated Next steps repair was stopped at John's instruction; its branch is preserved and the overnight review owns that issue. The automatic provider repair is held.

## Proposed work, in order

1. **Resolve the seven findings in the landed code.** Validate command-line connection addresses before contacting them; correctly route provider actions containing query parameters; preserve legitimate existing Gemini/agy execution when passive status is unreported; restore verified Grok capability after a cold start; eliminate duplicate Grok discovery; read complete job/checkpoint evidence; and parse the actual native Foreman status/ETA format. Each finding needs a reproduction and a fix or an explicit, evidence-backed disposition. Serious concerns cannot disappear solely because only one reviewer reported them.

2. **Test the requested product through its real routes.** Check add/sign-in/test/save/reopen/edit flows, two isolated Claude accounts, nicknames, new-dialogue account/model routing, and unchanged running conversations. Check all four provider families independently and Cave's usage-only summaries. Exercise failures and secret boundaries. Check the exact Foreman run identity, useful provisional ETA and scoped run tag in the existing status/Next steps surface. Use existing pytest regressions plus focused tests for the seven findings; retain independent review without restarting the whole build.

3. **Show the result and remaining gaps before activation.** Report which connections actually work, which facts providers do not report, and which prerequisites remain. Gemini/Grok isolated enrollment, a usable API execution route and complete executable installation packaging remain unproved. Investigate the installed interfaces during the repair; where a missing interface requires further design or implementation, bring that specific change back to John rather than silently expanding this job. After an authorized activation, verify John's existing laptop Setup and Cave window; a worktree browser does not prove that screen. Human acceptance remains separate.

## Boundaries, timing and cuts

Use one focused Foreman code job in its own Anchor worktree after approval, with the accepted temporary ChatGPT writer/Grok review and preference restoration. The gate is the existing nine-file provider/first-launch/status pytest suite plus tests/test_provider_review_followup.py. First run the reproductions against the landed version, then run the complete gate after fixes. All tests must pass and every serious finding must have a disposition.

Provisional estimate: 60-90 minutes from launch to checked fixes and review; real provider enrollment, missing-interface work and activation are outside that estimate. Revise the run-specific estimate as evidence changes. Do not start another full build or add reports, bespoke verification scripts, installation redesign, unrelated Next steps repair, paid probes or automatic billing fallback. Preserve email/calendar and cross-host collaboration as later work. No real login, executable deployment or restart without the applicable instruction.

This plan cuts the duplicate rebuild, separate ETA repair and unrelated interface repair from this work. It preserves the requested product and necessary account/credential checks.

## Source and decision

Read the complete campaign dialogue, current Face/Strip/roadmap/register, journal 0027, Refinement 2, the landed recovery and retained reviewer findings. John's turn 163dbef5-1bd5-42ef-9a1b-c5cedcfd96ee stops the current Anchor job and requires a visible plan before further implementation. Earlier functional and model authorizations remain recorded; they do not substitute for his answer on this revised repair plan.

Recommendation: approve this bounded resolution-and-testing plan, then review the actual usable flows and remaining prerequisites before activation. Alternative: let the overnight review inspect the provider work too, delaying this focused repair. Approval starts the repair; it does not approve an unsupported connection, activate the build or close a slice.
