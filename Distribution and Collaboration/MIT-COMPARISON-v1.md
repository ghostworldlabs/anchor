# MIT and the no-sales requirement — comparison v1

MIT does not meet the rule John described. It allows people to use and modify software, sell copies and sell products incorporating the MIT-covered code. It requires retention of the copyright and permission notices, but does not require publication of modifications. [MIT license](https://opensource.org/license/mit)

John's latest request is broad permission to use and modify Anchor, with no sale of Anchor or a product built on it. Source: local turn `9644fd33-97d1-4223-b5f9-9d080890ba70`, 2026-10-04T18:51:43Z. This explains the desired boundary; it does not select or apply a license. Earlier requirements about sharing improvements remain active.

## The example John gave

For MIT-covered code, a developer can take the source, add features, retain the required notices and sell the resulting product. The VS Code source repository uses MIT. That establishes the permission in the source license; this comparison does not determine which code Cursor actually used or the licensing of every component in its product. [VS Code source license](https://raw.githubusercontent.com/microsoft/vscode/main/LICENSE.txt)

## How the choices compare

| Choice | Use and modify | Sell a version or a product incorporating the covered code | Sharing changes |
| --- | --- | --- | --- |
| MIT | Broad permission, including business use | Permitted, with required notices | No obligation to publish or submit modifications |
| GPLv3 | Permitted, including business use | Permitted, subject to GPL obligations | Covered distributions require corresponding source and GPL rights for recipients |
| AGPLv3 | Permitted, including business use | Permitted, subject to AGPL obligations | Distributed covered work needs source; a modified network version must offer its corresponding source to remote users |
| PolyForm Shield | Permitted for purposes within its competition rules | Restricts competing products, including free competitors; does not prohibit every noncompeting commercial product | No general obligation to publish or return modifications |
| PolyForm Noncommercial | Permitted for its defined noncommercial purposes and listed organizations | Ordinary commercial use needs separate permission | No general obligation to publish or return modifications |

Sources: [GPLv3](https://spdx.org/licenses/GPL-3.0-only.html), [AGPLv3](https://spdx.org/licenses/AGPL-3.0-only.html), [Shield's full terms](https://raw.githubusercontent.com/polyformproject/polyform-licenses/1.0.0/PolyForm-Shield-1.0.0.md), [Noncommercial](https://polyformproject.org/licenses/noncommercial/1.0.0), and the MIT sources above. GPL and AGPL source-sharing obligations do not require sending every private change back to John.

## Recommendation for the same scope

Keep the requested distinction explicit: broad use and modification, with third-party sales of Anchor and products containing its covered code restricted. MIT and GPL/AGPL do not provide that sales prohibition. Standard OSI open-source licenses permit commercial redistribution; a no-sales restriction belongs to source-available terms. [Open Source Definition, sections 1 and 6](https://opensource.org/osd)

Shield is a comparison candidate, with two important mismatches: it restricts free competitors too, and can permit noncompeting commercial products. Noncommercial can restrict ordinary business use more broadly than a ban on selling the software. Neither standard option automatically supplies all of John's active requirements.

The wording still needs to distinguish incorporating Anchor's code into a sold product from merely using Anchor to do work. Paid hosting and the earlier improvement-sharing requirement also need precise treatment before selecting public terms. This comparison supplies the requested explanation; it does not draft or apply a custom license, resolve all remaining permission boundaries, accept the earlier guide or authorize a release.

This is an addendum to Licensing and IP guide v1 and Distribution scope v1, Refinement 1. Those earlier reviews stay available. The independently accepted first-trial order remains connect-first, with installation retained as a separate path.
