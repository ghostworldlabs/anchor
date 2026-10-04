# Setup and Mother Ship — discovery scope v2

Each person runs one mother ship on their own computer, and their other computers connect to it. John explicitly accepted that ownership choice on October 4, 2026. Collaboration between different mother ships is future work that still needs thinking; it is parked while backup policy and provider usage discovery continue.

Tailscale is the dictated connection service. June and July onboarding records report completed modules and tests; those are starting evidence, not proof that the newly requested Setup dialog is delivered.

**Placement:** Active under Ghost World Labs. **Original source:** John’s Campaign turn 3c476265-7142-441c-a934-a7a37d5a1e98, October 4, 2026. **Decision source:** John’s acceptance turn 35bc13bb-fd8a-4be5-b257-be6062683f25, 2026-10-04T18:46:28.289651Z, and clarification turn 84ec3037-96cb-4e13-87c5-f99f49888de2, 2026-10-04T18:54:12.271688Z. **Owner:** Anchor / Setup and Mother Ship. **Previous version:** [Organization scope v1](SCOPE-v1.md).

## Settled ownership

John accepted: “one mother ship per person, with their other computers connecting to it, because ownership stays clear.”

The Setup flow identifies that person’s chosen host on their own computer and connects their other computers to it. Prevent accidental duplicate hosts for the same person. A collaborator’s own host is not an accidental duplicate of another person’s host.

John clarified: “Each person has their own mother ship, that they run on their own computer. I do, in the future want to allow for different mother ships to share information/projects in order to facilitate collaboration. That still needs some thinking.”

That future collaboration is recorded in the Strip’s parked ideas, retaining this original wording and source. It concerns information and project sharing between distinct personal hosts. Its access boundaries, sharing mechanism and provider-sign-in rules are not settled. Those future choices do not block the independent personal-host Setup scope.

## John’s original words

“The service sits on one computer, and you just tail sell into the other computer”

## Requested scope

1. Add a Setup button in the upper left opening a guided dialog. The downloaded executable is the shell; the service and skills run on the chosen mother ship.

2. Detect whether this computer is that person’s host or a client. For a new host on their own computer, fetch the engine and Foundry skills, install them, create the right directories, start/register the service and confirm it runs. For a client, connect by Tailscale to that person’s established host and use its Anchor capabilities. Protect against accidental second hosts for the same person.

3. Include access-token acquisition/sharing, backups and the main directory. John prefers C:/dev. Users may nominate scattered folders; recommend project groupings, goal mappings and organization before any movement. The proposed Organizer may belong to the steward/Star Chart rather than a separate skill; that ownership remains open.

4. Connect email and calendars, including Outlook and Gmail. Provider setup covers Claude, ChatGPT, Gemini and Grok; distinguish subscription authentication from paid API credentials and save credentials locally through normal secure sign-in.

5. Show working/not-working status and honest remaining capacity in the Cave of Wonders lower-right tile: green usable, amber near limit, red exhausted. Show the actual model and reasoning level; let users choose the best available model by default or an alternate. Usage-page integration must distinguish observed values from unavailable ones.

6. Essential shared seam: Distribution launches this same Setup flow; it does not build a second installer/onboarding stack. Existing share_onboard, onboard_cli, share_skills_root and onboard modules are reuse candidates, not acceptance of this new surface.

7. Continue discovery before implementation: backup destination/restore policy and permitted provider usage discovery. Organizer ownership remains open. Multi-user collaboration between different mother ships is retained as future work for separate thinking; it is not an essential prerequisite to personal-host Setup. Existing independent organization work is not blocked by future collaboration.

## Existing work to open

- **Existing source:** [Earlier canonical skills/onboarding North Star](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FNORTH-STAR.md)
- **Existing source:** [Earlier onboarding master plan](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FMASTER-PLAN.md)
- **Existing source:** [July onboarding completion receipt — historical](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FPROJECT-DONE-RECEIPT.md)
- **Existing source:** [Earlier user onboarding guide](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FUSER-ONBOARD.md)
- **Existing source:** [June distribution/onboarding execution record — historical](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-distro-v1%2FEXECUTION-LOG.md)

## Authorization and acceptance

John authorized the organization and placement and explicitly authorized recording personal ownership in scope v2. Each product retains its own feedback, version and acceptance. This answer does not accept a completed Setup product or close a slice. Current records do not approve a new implementation plan. Publishing, domain purchases, a final license, credential changes, folder moves, token trials and deferred builds remain outside this scope revision.

## Plan boundary

This is the same scope map with one discovery answer recorded, not a build sequence. Remaining load-bearing choices precede a substantial implementation plan. Setup and Distribution share one installation/connection flow; the other products can be reviewed independently. Nothing was cut from John’s requested scope. Implementation scheduling remains excluded because unresolved product choices would make it premature.
