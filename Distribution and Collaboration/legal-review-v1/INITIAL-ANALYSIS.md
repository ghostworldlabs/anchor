# Legal-Beagle — Ghost World Lab License v1 initial analysis

As of 4 October 2026. Governing jurisdiction: **not selected**. Review scope: the supplied license's wording, consistency with John's recorded policy, and missing facts. No opinion on enforceability, legal classification of a particular derivative work, patent exposure or local consumer-law treatment is given. No case, statute or regulation is cited. This is drafting support, not legal advice.

## Principal findings

### 1. Resolve licensor, covered scope and governing law before adoption

Clause quote: “[FULL LEGAL NAME OF AUTHORIZED COPYRIGHT HOLDER OR LICENSING ENTITY]”; “[IDENTIFY THE ANCHOR FILES OR DIRECTORIES TO WHICH THIS LICENSE APPLIES, WITH SEPARATELY LICENSED COMPONENTS EXCLUDED]”; “[JURISDICTION TO BE CHOSEN AFTER CONFIRMING THE LICENSOR]”.

Issue: the candidate deliberately leaves the owner, coverage and law unresolved. A product name cannot fill those fields. Why it matters: the contemplated grant and separate commercial permissions require an authorized rights holder and an identified code boundary. Suggested action: keep the draft unpublished; inventory ownership, dependencies and contributions, then choose governing law with counsel. This blocks adoption, not an independent review of the text.

### 2. Paid custom modifications expose an unresolved policy boundary

Clause quote: “Delivering a paid custom modification is not automatically exempt as consulting: if the transaction supplies modified Covered Software for required consideration, section 3 applies.”

Issue: this candidate treats paid delivery of even a private modification as requiring permission. John prohibited sales and allowed free internal business use; he has not distinguished paid development labour from a paid fork. Why it matters: a business employing a developer could reasonably expect private modification to be part of its free internal-use permission. Suggested action: ask whether paid development for a customer's own private use should be allowed, with public fork sales and paid hosted access still reserved. Until then, mark this edge as a proposed interpretation rather than a settled rule.

### 3. Voluntary contributions do not establish commercial reuse rights

Clause quote: “Submitting a contribution does not, by itself, grant the Licensor permission to sell that contributor's material under different terms.”

Issue: the public candidate preserves contributor ownership and supplies no commercial relicensing grant. Why it matters: John's proposed paid edition needs adequate rights to any contributed or third-party material it contains. Suggested action: keep that rights clearance separate; propose a voluntary contribution agreement only if needed for a selected offering. Do not infer an assignment from sharing a patch.

### 4. Reserved paid services need precise, usable boundaries

Clause quote: “Giving the covered component a separate price of zero does not exempt a paid bundle containing it”; “Merely using Covered Software internally to produce a report, design or other output for a customer, without giving the customer access to its functionality, is not Hosted Access.”

Issue: the first rule prevents a bundle loophole; the second protects paid work outputs. The service exception still needs testing against managed customer installations, affiliates, contractor access and fees for services that depend on Anchor. Why it matters: wording broad enough to protect paid hosting can accidentally obstruct ordinary consultants. Suggested action: test those examples and leave new service exceptions visibly proposed until John settles them.

### 5. Supporting terms need a local legal check

Clause quote: “it does not grant a separate patent license”; “To the extent permitted by applicable law”; “If You do not cure it within 30 days after receiving that notice”.

Issue: patent rights, limits on liability and termination mechanics are proposed text, not conclusions about a particular country's law. No explicit patent grant may limit the practical safety of otherwise permitted use. The draft reserves commercial activities immediately while using notice-and-cure for other breaches. Suggested action: have counsel check those clauses after owner and law are known; retain their qualification here.

## Classification and source grounding

OSI's supplied section 1 excerpt says a qualifying license “shall not restrict any party from selling”. The draft prohibits sales of covered code; call it source-available rather than OSI open source. [Open Source Definition](https://opensource.org/osd)

MIT expressly grants permission to “sell copies of the Software”. It does not express John's sales reservation. [MIT License](https://opensource.org/license/mit)

The U.S. Copyright Office's supplied guidance describes ownership through “contracts like assignments”. This supports verifying authorization rather than treating the Ghost World Lab name as ownership proof; it does not select U.S. law for the candidate. [Copyright Office guidance](https://www.copyright.gov/what-is-copyright/)

## Independent check requested

A fresh configured review-family check must verify all quotations against the supplied sources, establish the limited jurisdiction/date posture, challenge loopholes and accidental restrictions, and distinguish accepted user policy from proposed supporting clauses. This analysis is not a claim that that check has completed. Final license acceptance and publication remain with John.
