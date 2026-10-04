# Distribution and Collaboration — organization scope v1

This cockpit owns portable releases, the public distribution home and license choice. Existing distribution/onboarding work is retained. The earlier July record reserved rights; today’s open-source direction is a new proposal whose exact license remains undecided.

**Placement:** Active under Ghost World Labs. **Source:** John’s original Campaign turn 3c476265-7142-441c-a934-a7a37d5a1e98, 2026-10-04. **Owner:** Anchor / Distribution and Collaboration.

## John’s words

"make it a open source tool that many collaborators can use That can be helpful to a lot of people for improving their productivity"

## Requested scope

1. Provide Windows, Linux and macOS downloads, including Mac Mini/MacBook use. Each platform’s launcher enters the same Setup routine for a mother ship or an existing remote host; one identical binary across operating systems is not assumed.

2. Proposed identity: Ghost World Labs / ghostworldlabs on GitHub. Keep separate repositories for the Anchor engine and the current Foundry skills. Proposed website: ghostworldlabs.com or ghostworldlabs.org, with downloads and collaboration access. Identity/domain availability and ownership are unverified; this organization creates neither a public repository nor a purchase.

3. John wants use and modification, changes shared back, and is considering a ban on commercial use/embedding without written permission. These are live license preferences, not a selected license.

4. Historical initial candidate: AGPLv3 if true open source is the priority. Refinement 1 below supersedes that recommendation in light of John’s commercial-control preference. It permits commercial use, requires source when covered software is distributed and requires an offer of corresponding source to remote users of a modified network service. It does not require every private change to be sent upstream to John.

5. Alternative: noncommercial source-available terms if commercial control is the priority. PolyForm Noncommercial is a starting comparison, but it is not OSI open source and does not itself provide the desired strong share-back obligation. Custom or combined terms need a separate rights/legal review before publication.

6. The Open Source Definition does not permit excluding business use. Choosing license direction is separate from applying a license, publishing a repository, clearing dependency/contributor rights or purchasing a domain. All remain unperformed.

7. Essential shared seam: this initiative packages and distributes the Setup initiative’s one onboarding path. Foundry runtime-map enhancements and the On deck experiments are independently reviewable; they need not hold up a first tested release unless John makes them essential.

## Existing work to open

- **Existing source:** [Earlier distribution master plan](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-distro-v1%2FMASTER-PLAN.md)
- **Existing source:** [Earlier distribution implementation plan](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-distro-v1%2FIMPLEMENTATION-PLAN.md)
- **Existing source:** [June build claims and platform-test limits — historical](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-distro-v1%2FEXECUTION-LOG.md)
- **Existing source:** [July onboarding scope and rights reservation](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=planning%2Fshare-canonical-onboard-2026-07%2FNORTH-STAR.md)
- **Existing source:** [OSI: Open Source Definition, section 6](https://opensource.org/osd)
- **Existing source:** [GNU AGPLv3, including section 13](https://www.gnu.org/licenses/agpl-3.0.html)
- **Existing source:** [PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)

## Authorization and acceptance

John authorized this organization and placement. Each product keeps its own feedback, version and acceptance; no slice is closed here. Current records do not approve a new implementation plan. Publishing, domain purchases, a final license, credential changes, folder moves, token trials and deferred builds remain outside this organization.

## Plan boundary

This is a scope map, not a build sequence. Cockpit discovery must settle load-bearing choices before a substantial implementation plan. Setup and Distribution share one installation/connection flow; the other products can be reviewed independently. Nothing was cut from John’s requested scope. Implementation scheduling was excluded here because unresolved product choices would make it premature.


## Refinement 1 — John’s commercial-control preference

On 4 October, John provisionally chose restricted: others should not take Anchor and make commercial versions, while he retains a commercial edition. He requested a clearer standard-options comparison and copyright/trademark explanation before selecting terms. Source turn: `52eadd74-2b48-4381-ae92-d255c5042d21`. This answers and retires the earlier open-or-restricted question; AGPL is no longer the recommended fit for that preference.

The [Licensing and IP guide v1](/artifact/df56858063ac4025982d0c36038509d2?path=goals%2Fanchor-steward%2FLICENSING-IP-v1.html) compares PolyForm Shield, PolyForm Noncommercial, AGPL and BUSL, with Elastic as a narrower alternative. Recommendation: examine Shield with separate commercial permission if the restriction concerns competing products; Noncommercial if ordinary commercial use should also require permission. Mandatory contribution of improvements is a separate unresolved requirement, not supplied by either PolyForm candidate.

The next load-bearing distinction is free internal business use versus third-party commercialization. An answer refines this same scope; it does not apply terms or authorize a public release. Original goal words are retained until John rewrites them. Copyright ownership, third-party licenses, contributor rights and brand availability must be established before applying a final license.

## MIT comparison requested — same scope, no license selected

John's later local turn `9644fd33-97d1-4223-b5f9-9d080890ba70`, 2026-10-04T18:51:43Z, asks how the proposed choices compare with standard open-source licenses, especially MIT, and clarifies broad use and modification with no sale of Anchor or a product built on it. [MIT comparison v1](MIT-COMPARISON-v1.md) answers that question alongside the original Licensing and IP guide v1. The existing license step carries the comparison requirement; no final terms or commercial permission are inferred from this request.

MIT permits commercial derivatives and requires notices without mandatory publication of modifications. GPL/AGPL also permit sale, with applicable source-sharing requirements. The desired no-sales rule needs source-available permissions. Shield and Noncommercial retain the mismatches explained in the comparison; earlier improvement-sharing and ownership requirements remain active. The earlier internal-business-use question below is preserved as part of the pending licensing review, not re-asked as a condition for this requested explanation.

## Accepted first trial order — independent of licensing

John accepted connecting to the existing mother ship first, rather than proving a fresh independent installation first. Source: local turn `44f8b822-bfb8-413d-b5b1-f2c5cca3d98b`, 2026-10-04T18:47:01Z, scoped to the recommendation in `DISCOVERY-v1.md`. Both onboarding paths remain required; the first collaborator trial will prove connection, and independent installation follows separately. The existing release-verification step now carries that order and its answered wait is cleared.

This acceptance refines Distribution scope v1's trial order only. Independently authorized installation work can still proceed in parallel. It does not accept this refinement's licensing choices, choose the internal-business-use policy, authorize a build or close a slice. The distinct pending licensing question below retains its existing scope and version.

## Current decision — internal business use

Your restriction on commercial versions leaves one boundary open: a business using Anchor for its own staff. Shield permits that while restricting competing products; Noncommercial restricts ordinary business use too.

I recommend free internal business use because it supports adoption while reserving competing products for permission.
Broader noncommercial terms: more control, more permission requests; defer: leave this boundary undecided.
This authorizes: refine Distribution scope v1, Refinement 1 around free internal use; final licensing terms remain undecided.
Reversible: yes - undo: remove the internal-use assumption.
Should internal business use be free?
