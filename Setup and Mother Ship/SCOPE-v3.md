# Setup and Mother Ship — discovery scope v3

The next work is the provider mockup: subscription sign-in, optional API keys, remaining capacity/tokens, cost and model controls. John wants to explore and refine those displays inside Anchor before adding email and calendars. The roadmap carries this ordering now; the mockup’s own version is **Initial draft**, separate from this scope document’s v3.

Each person runs one mother ship on their own computer, and their other computers connect to it through Tailscale. Collaboration between different mother ships remains a parked idea that needs separate thinking. It does not block this provider mockup.

**Placement:** Active under Ghost World Labs. **Owner:** Anchor / Setup and Mother Ship. **Sources:** Campaign dictation `3c476265-7142-441c-a934-a7a37d5a1e98`; personal-host acceptance `35bc13bb-fd8a-4be5-b257-be6062683f25`; own-computer and future-collaboration clarification `84ec3037-96cb-4e13-87c5-f99f49888de2`; provider-first mockup direction `9205de17-a7fb-4aad-8d81-cb063fc494f0`, 2026-10-04T18:59:35.195923Z. Previous scope: [v2](SCOPE-v2.md); original requirements: [v1](SCOPE-v1.md).

## The provider mockup

John’s words: “I want to do the signing in to token/agentic subscriptions (plus we should allow for people to bring API keys as well) and managinig/seeing how many tokens are left and cost and such before adding in the calenders and email. I still need to have you build a mock up/refine how we will display these and interact with these elements with in Anchor.”

The initial mockup shows the same provider settings during Setup and from the Cave’s capacity tile. It demonstrates subscription authentication and optional API connections separately, remaining allowance/usage with its units and window, known versus unreported capacity and cost, model/reasoning controls, and usable/near-limit/exhausted/unknown states. Email and calendars are later setup items. Its values and account interactions are illustrative; the mockup does not acquire credentials, read accounts or install provider integration.

John reviews the actual interactive surface and gives changes before an implementation plan or production build. Producing and checking this draft does not accept it or close its step. The provider mockup, full Setup product and Distribution product retain their independent feedback and acceptance.

## Full requested scope retained

1. Add an upper-left Setup button opening a guided dialog. The downloaded executable is the shell; the service and Foundry skills run on the chosen personal mother ship.

2. Detect the host/client role. For a new host on the owner’s own computer, fetch the engine and skills, install them, create the directory structure, start/register the service and confirm it runs. Other computers connect to that owner’s established host through Tailscale. Prevent accidental second hosts for the same person, while allowing other people to own their own hosts.

3. Prioritize provider setup: normal subscription sign-in and optional API keys for Claude, ChatGPT, Gemini and Grok. Distinguish subscription allowances from paid API credentials, usage and cost; use normal secure local sign-in. Mock up the capacity tile and model/reasoning controls, including honest unavailable values, before implementing them.

4. Retain project/folder mapping, token acquisition/sharing, backups and the main directory. John prefers C:/dev. Users can nominate scattered folders; recommend projects, goals and organization before moving anything. Organizer ownership remains open between the steward/Star Chart and a separate skill. Backup destination, retention and restore policy remain discovery details; the unasked backup-location proposal is withdrawn while provider work takes priority.

5. Add Outlook/Gmail accounts and calendars after provider sign-in and usage/cost displays. This changes order, not their inclusion in Setup.

6. Distribution launches this same Setup flow; it does not build another onboarding stack. Existing share_onboard, onboard_cli, share_skills_root and onboard modules remain reuse candidates. Earlier June/July completion receipts do not establish that this new surface has been delivered.

7. Keep collaboration between different personal mother ships in the Strip’s parked ideas. Its sharing mechanism, project boundaries and provider-account rules remain future thinking. Provider usage discovery methods and source availability still need verification before production claims; they do not prevent a clearly illustrative mockup.

## Existing work to open

- **Existing source:** [Earlier canonical skills/onboarding North Star](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FNORTH-STAR.md)
- **Existing source:** [Earlier onboarding master plan](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FMASTER-PLAN.md)
- **Existing source:** [July onboarding completion receipt — historical](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FPROJECT-DONE-RECEIPT.md)
- **Existing source:** [Earlier user onboarding guide](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FUSER-ONBOARD.md)
- **Existing source:** [June distribution/onboarding execution record — historical](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-distro-v1%2FEXECUTION-LOG.md)

## Authorization and next boundary

John explicitly authorized the provider mockup and its refinement, the new order and optional API-key inclusion. Personal ownership remains settled. No account sign-in, credential change, actual usage-page inspection, backup configuration, software installation, folder move, publication, purchase or production build is authorized by this draft. The next human boundary is feedback on the initial interactive mockup, not approval of an implementation plan. No scope item was cut; email/calendars were moved later at John’s direction, and future cross-host collaboration remains caught.
