**Ghost World Lab License v1 — textual review**

**As of 4 October 2026. Governing jurisdiction: not selected.** Drafting support only. This is not legal advice and not an opinion on enforceability, patent exposure, or any country's treatment of liability or termination. No case, statute, or regulation is cited. Every quotation below was checked against the supplied license and the supplied authority excerpts.

## Conclusion

The candidate follows the accepted policy: free personal and internal use, modification, voluntary share-back, free forks, free hosting, no sale of covered code or of a product containing it, and separate permission for paid hosting. It correctly refuses an OSI open-source label. It is fit for another drafting round and unfit to adopt or publish. As written, wages, staff confidentiality, and self-hosting on rented computers can be read as reserved commercial activity. The sales ban binds the seller more clearly than the buyer of a sold copy.

## Findings

Ranked by consequence. **Wording** aligns the text with boundaries already stated. **Decision** is a choice only John can make.

### 1. Wages can be read as a prohibited Sale

**Quote:** “Sale” means supplying a copy of Covered Software, a modification, a product containing Covered Software, or rights to use any of them in exchange for required payment, barter or other consideration. “Internal Users” means Your employees and contractors acting on Your behalf for Your own operations. “You may operate original or modified versions for Internal Users without a license fee.” Separately: “Delivering a paid custom modification is not automatically exempt as consulting: if the transaction supplies modified Covered Software for required consideration, section 3 applies.”

**Issue:** Internal Users sit inside the free permission. Sale and the consulting sentence treat a paid delivery of a modification as reserved. Payroll for a patch that stays on the employer's own systems meets both descriptions. The initial analysis quoted the consulting sentence and then discussed employing a developer. Employment on the employer's own copy is accepted internal use. Delivery of a copy for a customer's own possession is the unsettled edge.

**Consequence:** Ordinary wages or an in-house contractor invoice can be read as a Sale section 3 does not authorize.

**Suggested action:** Wording — state that pay to Internal Users, for work on a copy that remains under the engaging party's control for that party's own operations, is not a Sale or Paid Hosted Access. Decision — keep customer delivery marked as proposed. Section 4 states it as a rule, while the companion says it “needs further policy review.” Make those match. “Other consideration” is also broad enough to reach a required contact detail or similar non-monetary gate; confirm that breadth before it hardens.

### 2. “No additional restriction” can forbid keeping modifications private

**Quote:** “Do not impose a fee or additional restriction on the permissions this license grants for the Licensor's Covered Software.” Also: “You need not publish private modifications, provide their source code to the Licensor, submit a patch upstream, or participate in an exchange.”

**Issue:** The granted permissions include distribution. A staff confidentiality or security rule restricts distribution of the work copy. Section 2 expressly allows that copy to stay private.

**Consequence:** Accepted internal use can be read as a breach whenever staff are forbidden to publish an internal patch.

**Suggested action:** Wording — confine the sentence to terms added when distributing the Licensor's Covered Software, and state that a confidentiality term covering the distributor's own modifications is not itself a prohibited additional restriction. A further ban on confidentiality terms over unmodified source received from the Licensor would be a Decision; accepted policy does not require it.

### 3. The buyer of an unauthorized sale may keep a direct free license

**Quote:** “Recipients receive the permissions in this instrument directly from the relevant Licensor for that Licensor's Covered Software.” “A Sale or Paid Hosted Access outside Separate Permission is unauthorized when it occurs.” “Termination of Your permissions does not, by itself, terminate a complying recipient's direct permissions.”

**Issue:** Sale is supplying a copy for consideration. The payer receives the copy. Sections 3 and 9 do not say that a copy supplied in an unauthorized Sale carries no permission to a recipient who otherwise complies.

**Consequence:** The seller is outside the commercial permission; the sold copy can remain usable. The accepted no-sale rule then governs the seller's conduct and does not control paid circulation. That result is easier to administer, and it is a real leak.

**Suggested action:** Decision — state one reading in the instrument: either a complying recipient's direct free permissions do not depend on the distributor's compliance, or a copy supplied through an unauthorized Sale conveys no permission under this instrument.

### 4. “Your provider” can turn self-hosting into paid hosting

**Quote:** “Hosted Access” means enabling another person to use the functionality of Covered Software running on a computer that You or Your provider operates, through an interface, API, intermediary or other service. “Paid Hosted Access” means Hosted Access for which payment, barter or other consideration is required, including access supplied as part of a paid bundle. “A voluntary donation is not a Sale when neither receipt of the software nor the permissions granted here depend on donating.”

**Issue:** Internal Users are other persons, and the computers may be a provider's. The company pays that provider. A generic computing provider is not distinguished from a service that offers Anchor's functionality. The donation sentence applies to Sale and is not repeated for hosting; “required” has to do that work alone. A paid UI, API, or intermediary is squarely reserved. A self-serve paid report API is use of the functionality through an API. The private consultant who produces an output without giving the customer that access is expressly outside Hosted Access.

**Consequence:** Rent for ordinary infrastructure, and a free community host with optional sponsorship, can be argued to need Separate Permission. The paid report API stays reserved on the current text.

**Suggested action:** Wording — exclude Internal Users' access to software the licensee operates, including on infrastructure rented for the licensee's own operations; exclude a general-purpose provider that does not offer Covered Software's functionality as the service; repeat the optional-donation rule for hosting. Decision — confirm the reserved treatment of a paid self-serve output API.

### 5. Bundles are closed; independent plugins depend on what is actually included

**Quote:** “Giving the covered component a separate price of zero does not exempt a paid bundle containing it.” “This restriction applies even when the product adds substantial independent functionality, changes its name, or charges indirectly for the covered component.” “A work is not Covered Software merely because it communicates with Anchor, implements an interface independently, or was created using Anchor without incorporating Covered Software.” Covered Software includes “portions of their copyrightable code included in another program.”

**Issue:** A paid bundle, renamed fork, or freemium installer that contains covered code is reserved even when the covered component is priced at zero. An independent implementation that only communicates with Anchor is chargeable. Any included portion is covered. Headers, generated stubs, and linking are undefined, and this review does not classify them. There is no trivial-amount exception.

**Consequence:** Plugin and bundle results wait on the empty covered-files list. The product name Anchor does not fill it. The zero-price sentence matches accepted policy.

**Suggested action:** Wording — when the file list is filled, say whether interface declarations and SDK stubs are covered. Add a trivial-amount exception only if John asks.

### 6. A submitted patch is not licensed for redistribution

**Quote:** “Submitting a contribution does not, by itself, grant the Licensor permission to sell that contributor's material under different terms.” “Modification, distribution or voluntary submission does not assign copyright to the Licensor.”

**Issue:** Those sentences block an assignment and a right to sell under other terms. They do not grant redistribution under this instrument. The bracketed licensor is still “[FULL LEGAL NAME OF AUTHORIZED COPYRIGHT HOLDER OR LICENSING ENTITY].” The supplied Copyright Office excerpt describes ownership passing through “contracts like assignments” and an exclusive right to “Prepare derivative works based upon the work.” That is U.S. explanatory guidance, not a selected governing law, and not a grant from any contributor.

**Consequence:** A merged voluntary patch may lack a stated permission even for the free edition. A paid edition has that gap plus the further absence of permission for different terms.

**Suggested action:** Wording — say submission alone grants no redistribution right, free or paid. Decision, and only if an offering is actually planned — a voluntary contribution agreement for the rights that offering needs.

### 7. A commercial breach and the 30-day cure point different ways

**Quote:** “The permissions in section 2 are conditional on compliance with this instrument. A Sale or Paid Hosted Access outside Separate Permission is unauthorized when it occurs; no notice or cure period creates a temporary commercial permission.” Then: “If You materially breach another condition of this license,” the relevant Licensor may give notice, and if “You do not cure it within 30 days after receiving that notice, the permissions granted by that Licensor under this license terminate.” Restoration requires “that Licensor's written confirmation after cure.”

**Issue:** Full compliance is a condition of every section 2 permission, while cure is reserved for “another condition.” The text never says whether free permissions end at the sale or only after notice and a failed cure. “Materially” and the manner of receiving notice are undefined. No jurisdiction is applied to fill those words.

**Consequence:** A user cannot tell whether free internal use survives an unauthorized sale. Cure can be misread as blessing the past sale.

**Suggested action:** Wording, with the cure design still proposed until John accepts it — an unauthorized Sale or Paid Hosted Access is unlicensed when it occurs and is not retroactively authorized. Unrelated free permissions end only after that Licensor's notice-and-cure process. Immediate loss of all free permissions would be a stricter Decision.

### 8. No patent license, and adoption fields stay blank

**Quote:** “it does not grant a separate patent license or override any right, exception or limitation supplied by applicable law.” “No trademark license or endorsement right is granted.” The open fields are “[FULL LEGAL NAME…],” “[IDENTIFY THE ANCHOR FILES OR DIRECTORIES…],” “[JURISDICTION TO BE CHOSEN AFTER CONFIRMING THE LICENSOR],” and “[COUNSEL TO CONFIRM WHETHER A FORUM CLAUSE IS NEEDED AND, IF SO, ITS TEXT].”

**Issue:** Copyright compliance is not a patent permission, and nothing here identifies a patent holder. There is no defensive termination if a user asserts patents. Trademark text forbids presenting a fork as the official product and does not decide descriptive use of the name Anchor. “Worldwide” in section 2 is the geographic reach of the copyright permission offered; it selects no governing law. The line “The commentary below is explanatory and is not part of its operative terms” leaves the status text above section 1 unclassified. Section 8 already limits its disclaimer and liability language “to the extent permitted by applicable law.”

**Consequence:** Permitted use can still face a patent assertion this instrument does not address. There is no identified person who can give Separate Permission and no identified code for the grant to attach to.

**Suggested action:** Keep the no-patent-grant sentence until John and counsel decide otherwise. Adding a patent license or a retaliation clause is a Decision. Wording — “Only sections 1 through 10 are operative.” Leave the brackets in place.

## Corrections that do not change accepted policy

Delete “ordinary” in “ordinary internal business use.” State that only sections 1–10 are operative. Carve in-house pay, on the engaging party's own copy, out of Sale. Confine additional restrictions so private modifications may stay confidential. Exclude the licensee's rented infrastructure and generic computing providers from Paid Hosted Access, and repeat the optional-donation rule for hosting. State that submission grants no free or paid redistribution right. State that a past unauthorized sale is never cured into a permission, and that unrelated free permissions end only through notice and failure to cure.

## Source check

Checked against the supplied excerpts only.

The Open Source Definition excerpt says a qualifying license “shall not restrict any party from selling” the software in the described distribution setting, and that sections 3 and 6 concern derived works and fields including business. This candidate restricts sales. Its preamble already declines the OSI label. That is category language from the excerpt, not a statute. Source: supplied excerpt from https://opensource.org/osd.

The MIT excerpt includes “sell copies of the Software,” requires the copyright and permission notice in copies or substantial portions, and does not require publication of modifications. It does not supply John's no-sale boundary. Source: supplied excerpt from https://opensource.org/license/mit.

The Copyright Office excerpt is used only in finding 6, and only as unlabeled U.S. explanatory guidance. Source: supplied excerpt from https://www.copyright.gov/what-is-copyright/.

The initial analysis quoted those three sources accurately. It blurred wages with customer delivery and did not reach the confidentiality clash, the recipient loophole, rented infrastructure, or the missing inbound free-distribution right.

## Open decisions and fitness

Still open: paid delivery of a modification for a customer's possession; whether the recipient of an unauthorized sale keeps direct free permissions; patent terms and fork naming; how far “other consideration” reaches; and confirmation that a paid self-serve output API stays reserved. Still open with counsel: the legal owner, covered files, dependencies, contributor permissions, governing law, and any forum clause.

This candidate is suitable for continued drafting. It is not approved to publish, price, or offer commercially, and it changes no public repository license.
