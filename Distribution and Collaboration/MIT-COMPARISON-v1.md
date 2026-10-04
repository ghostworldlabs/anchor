# MIT and the no-sales requirement — comparison v1

**Current direction, 4 October:** John accepted the custom candidate for drafting and review within Distribution scope v1, Refinement 1, then explicitly requested [Ghost World Lab License v1](GHOST-WORLD-LAB-LICENSE-v1.md) and Legal-Beagle review. That draft is now the current licensing product; this comparison remains independently reviewable. No final license is accepted, applied or published.

MIT does not meet the rule John described. It allows people to use and modify software, sell copies and sell products incorporating the MIT-covered code. It requires retention of the copyright and permission notices, but does not require publication of modifications. [MIT license](https://opensource.org/license/mit)

John's request is broad permission to use and modify Anchor, with no sale of Anchor or a product built on its covered code. Source: local turn `9644fd33-97d1-4223-b5f9-9d080890ba70`, 2026-10-04T18:51:43Z. Free internal business use is accepted. His later turn `bddb9954-a824-4209-9d17-92fc3a432a48`, 2026-10-04T19:13:54Z, expressly makes sharing modifications voluntary and asks which license best fits. That replaces the earlier mandatory share-back requirement. These answers refine the same scope; they do not select or apply a license.

## The example John gave

For MIT-covered code, a developer can take the source, add features, retain the required notices and sell the resulting product. The VS Code source repository uses MIT. That establishes the permission in the source license; this comparison does not determine which code Cursor actually used or the licensing of every component in its product. [VS Code source license](https://raw.githubusercontent.com/microsoft/vscode/main/LICENSE.txt)

## How the choices compare

| Choice | Use and modify | Sell a version or a product incorporating the covered code | Sharing changes |
| --- | --- | --- | --- |
| MIT | Broad permission, including business use | Permitted, with required notices | No obligation to publish or submit modifications |
| Apache 2.0 | Broad permission, including business use, with an express patent license | Permitted, with license/notice requirements and changed-file markings | No general obligation to disclose modifications as source |
| GPLv3 | Permitted, including business use | Permitted, subject to GPL obligations | Covered distributions require corresponding source and GPL rights for recipients |
| AGPLv3 | Permitted, including business use | Permitted, subject to AGPL obligations | Distributed covered work needs source; a modified network version must offer its corresponding source to remote users |
| PolyForm Shield | Permitted for purposes within its competition rules | Restricts competing products, including free competitors; does not prohibit every noncompeting commercial product | No general obligation to publish or return modifications |
| PolyForm Noncommercial | Permitted for its defined noncommercial purposes and listed organizations | Ordinary commercial use needs separate permission | No general obligation to publish or return modifications |
| MIT plus Commons Clause | Broad base permissions, subject to its defined selling restriction | Restricts paid products/services whose value derives entirely or substantially from the covered software; its FAQ permits selling larger value-added products containing it | No general obligation to publish or return modifications |
| Elastic 2.0 | Use, copy and modification allowed within its limitations | Restricts hosted/managed services exposing substantial functionality, rather than imposing a blanket modified-software sales ban | No general obligation to publish or return modifications |
| FSL 1.1 | Internal use and qualifying professional services expressly allowed | Restricts competing commercial products/services; each version becomes MIT or Apache licensed after two years, permitting sales | No general obligation to publish or return modifications |

Sources: [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0), [GPLv3](https://spdx.org/licenses/GPL-3.0-only.html), [AGPLv3](https://spdx.org/licenses/AGPL-3.0-only.html), [Shield's full terms](https://raw.githubusercontent.com/polyformproject/polyform-licenses/1.0.0/PolyForm-Shield-1.0.0.md), [Noncommercial](https://polyformproject.org/licenses/noncommercial/1.0.0), and the MIT sources above. GPL and AGPL source-sharing obligations do not require sending every private change back to John.

Additional primary sources: [Commons Clause terms and FAQ](https://commonsclause.com/), [Elastic 2.0 terms](https://www.elastic.co/licensing/elastic-license), [FSL 1.1 terms](https://raw.githubusercontent.com/getsentry/fsl.software/main/FSL-1.1-ALv2.template.md) and [FSL version transition explanation](https://fsl.software/).

## Recommendation for the same scope

I recommend tailored source-available terms for the exact policy: free use including internal business use, modification, optional sharing of improvements, and restricted third-party sales of Anchor and products containing its covered code. MIT and GPL/AGPL do not provide that sales prohibition. Standard OSI open-source licenses permit commercial redistribution; a no-sales restriction belongs to source-available terms. [Open Source Definition, sections 1 and 6](https://opensource.org/osd)

Shield is a comparison candidate, with two important mismatches: it restricts free competitors too, and can permit noncompeting commercial products. Noncommercial can restrict ordinary business use more broadly than a ban on selling the software. Neither standard option automatically supplies all of John's active requirements.

Commons Clause is closer to a resale restriction, but its value-based test can permit substantial value-added products that John wants covered. Its definition also reaches some paid hosting, consulting and support, so it cannot be described as a simple ban on selling software copies. Elastic focuses on hosted access; FSL's two-year transition ends its commercial restriction for each version. None of these checked licenses precisely matches the whole requested policy; this is not an exhaustive finding about every license in existence.

Tailored terms would distinguish a product containing Anchor's covered code from merely using Anchor to perform paid work. They should preserve voluntary contributions and free internal use. John has now accepted requiring permission for third-party paid hosted access, separately from the software no-sales rule. Source: local turn `54353a3f-f66f-4138-8c33-b1acdb7957d8`, `2026-10-04T19:47:51.189280+00:00`, answering saved question `bbe4240655e32bab3ec66d8821da73af2dc9a553116fa030daeef47478ea0406`. This changes the recorded policy in Distribution scope v1, Refinement 1; it does not select a custom candidate, final license, price or service offering.

The next decision is the licensing mechanism: I recommend custom source-available terms as the candidate for review, with final text and publication still subject to their own acceptance and rights/legal review. The table of accepted boundaries in the scope makes the policy concrete without drafting license text.

This comparison supplies the requested explanation. The separately authorized Ghost World Lab License v1 now supplies the custom draft; this comparison does not apply it, accept the earlier guide or authorize a release. Rights and legal review of final text remain prerequisites to publication already recorded in the scope.

This is an addendum to Licensing and IP guide v1 and Distribution scope v1, Refinement 1. Those earlier reviews stay available. The independently accepted first-trial order remains connect-first, with installation retained as a separate path.
