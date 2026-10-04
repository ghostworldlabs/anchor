# Legal-Beagle — Ghost World Lab License v1 review

4 October 2026. Current product: **Ghost World Lab License v1, Refinement 1 — draft for review**. Governing jurisdiction is not selected. This is textual drafting support, not legal advice or an enforceability opinion. No case, statute or regulation is cited; no public license is changed.

## What the review found

The candidate expresses John's accepted free-use and commercial-control policy. Legal-Beagle found wording that could restrict staff compensation, private workplace changes and self-hosting on generic rented computers; those conflicts have been corrected in Refinement 1. Paid delivery of a custom modification outside the internal-work exception remains a choice for John. Legal ownership, covered files, contribution/dependency rights and governing law remain prerequisites to adopting the license.

**Review status:** the independent written analysis and the fresh correction check completed. The correction check found **no new material wording findings**; the companion and examples matched the operative clauses. Open policy choices and adoption prerequisites remain, so this is a completed drafting review, not approval of final terms or publication.

[Open the current draft](/artifact/f69f6d66171f4dbd95c8c45db6846d97?path=Distribution%20and%20Collaboration%2FGHOST-WORLD-LAB-LICENSE-v1.md&render=1)

## Findings and treatment

### 1. Keep staff compensation inside free internal use

Original clause quote: “Delivering a paid custom modification is not automatically exempt as consulting: if the transaction supplies modified Covered Software for required consideration, section 3 applies.”

Issue and consequence: combined with the Sale definition, this could reach wages or contractor invoices for work performed on a business's own private copy, conflicting with free internal use. Refinement 1 now says: “Paying Internal Users for work on a copy that remains under Your control for Your own operations is not a Sale or Paid Hosted Access.” It expressly includes wages and contractor compensation. It keeps separately delivered paid modifications outside that exception, visibly marked as John's unresolved policy choice.

Suggested decision: permit paid development for a customer's own private use, while retaining the sales and paid-hosting reservations. This recommendation has not been adopted in the operative draft.

### 2. Protect private workplace changes without requiring source sharing

Original clause quote: “Do not impose a fee or additional restriction on the permissions this license grants for the Licensor's Covered Software.”

Issue and consequence: the unrestricted wording could reach staff confidentiality or security rules even though private modifications are allowed. Refinement 1 limits this condition to redistribution outside Internal Users and says: “This condition does not require You to share private copies or modifications, or prevent internal confidentiality and security rules for Your controlled copies.” Voluntary upstream sharing and the absence of a source-disclosure requirement are preserved.

### 3. Separate generic computing rental from selling Anchor access

Original clause quote: “Hosted Access” means enabling another person to use the functionality of Covered Software running on a computer that You or Your provider operates, through an interface, API, intermediary or other service.

Issue and consequence: a business paying for a generic server could be mistaken for paid Anchor hosting. Refinement 1 excludes Internal Users on rented general-purpose infrastructure and providers merely renting infrastructure on which customers install and operate their own copies. Selling Anchor's functionality itself remains reserved. Optional donations unrelated to receiving or extending access are explicitly covered for hosting as well as software copies; this donation clarification remains proposed supporting text.

A paid self-serve API exposing Anchor functionality remains reserved in the candidate; a paid report produced privately without giving access to that functionality remains allowed. These examples implement the access/output distinction rather than a blanket restriction on business use.

### 4. Obtain contribution permissions for free distribution as well as commercial editions

Original clause quote: “Submitting a contribution does not, by itself, grant the Licensor permission to sell that contributor's material under different terms.”

Issue and consequence: the original wording dealt with commercial reuse but did not establish a grant even to redistribute a submitted patch in the free edition. Refinement 1 clarifies: “Submission alone does not authorize the Licensor to redistribute a contribution, free or paid.” A contributor may provide an express accompanying license or voluntary contribution agreement. Ownership is retained, no automatic assignment is introduced, and sharing a patch is not compulsory.

The Licensor definition now identifies a rights holder only for material that holder is authorized to license. Filling the owner and file fields does not, by itself, clear third-party or contributor rights.

### 5. Make termination consistent without authorizing past sales

Original clause quote: “If You materially breach another condition of this license”.

Issue and consequence: “another” and the general compliance condition left unclear whether an unauthorized sale immediately terminated all free permissions or only the commercial activity lacked permission. Refinement 1 consistently applies notice and failure to cure to termination of otherwise permitted activities. It also says no cure period “creates a temporary commercial permission or retroactively authorizes that activity”. The 30-day notice process remains proposed supporting text for later acceptance and legal review.

### 6. Leave stronger enforcement and additional rights visibly unapproved

Current clause quote: “Termination of Your permissions does not, by itself, terminate a complying recipient's direct permissions.”

Issue and consequence: the candidate protects complying recipients after a distributor breaches. Legal-Beagle identified an alternative that denies permission for copies obtained through unauthorized sales. That stricter alternative is not silently adopted. This candidate interpretation, any patent grant or defensive patent clause, naming boundaries and the breadth of noncash consideration remain matters for final review.

Current clause quote: “it does not grant a separate patent license”. The instrument therefore makes no claim that copyright compliance clears patent exposure. Owner, covered-file inventory, SDK/interface coverage, governing law and any forum clause remain blank or unresolved; do not publish while those adoption prerequisites remain open.

## Policy coverage

| Accepted boundary | Current candidate |
| --- | --- |
| Free personal and internal business use | Section 2; internal compensation and generic computing rental clarified in section 1 |
| Modification allowed | Section 2; private-copy confidentiality preserved in section 5 |
| Sharing changes back optional | Section 2; no mandatory upstream submission or modified-source publication |
| Free forks allowed | Sections 2 and 5, with notices; no free-competition ban |
| No covered-code sales | Sections 1 and 3 cover renamed/value-added products and paid bundles; no zero-price-component loophole |
| Paid Anchor hosting needs permission | Sections 1 and 3 cover hosted interfaces, APIs and intermediaries; generic rental distinguished |
| Commercial services merely proposed | Section 6 reserves separate licensing subject to actual rights; no offering or price approved |

## Source check and limits

The classification and MIT comparison use the supplied primary excerpts from the [Open Source Definition](https://opensource.org/osd) and [MIT License](https://opensource.org/license/mit). The [Copyright Office explanation](https://www.copyright.gov/what-is-copyright/) is identified as U.S. guidance, not governing law or a contribution grant. No case-law research or local-law certification is claimed. The original independent review abbreviates some placeholder quotations; this report uses operative quotations from the retained input or revised draft rather than treating abbreviated placeholders as exact text.

The citation engine's footer receipt distinguishes its deterministic citation checks from the actual independent textual review. A clean check with no recognized legal-citation patterns does not establish enforceability or semantic correctness. The report's operative quotations are also checked directly against the preserved input, corrected draft and source pack.

## Correction check result

The fresh check completed at 21:22 UTC on 4 October. It found no new material wording findings, confirmed the internal-use clarifications did not create a software-sale or paid-hosting permission, and confirmed the companion and examples matched the clauses. It kept the recipient-protection alternatives, paid private deliveries, patent/naming/noncash boundaries, supporting enforcement terms and blank adoption fields explicitly open. Its raw reply and attested subscription receipt are preserved at `legal-review-v1/CORRECTION-CHECK.md` and `legal-review-v1/CORRECTION-SEAT-RECEIPT.json`.

The review stops after this check; no extra review cycle or public application is authorized or needed for this drafting pass. John's next decision is whether paid development that separately delivers modifications for a customer's private use should be allowed. That would refine this draft while keeping paid products and hosted access reserved; it would not accept the other proposed terms or authorize publication.

## Independent review and preserved inputs

The original named draft is preserved at `legal-review-v1/INPUT-LICENSE-v1.md`, and the received independent report at `legal-review-v1/INDEPENDENT-REVIEW.md`. The corrected draft was written before its correction check. Changes are not represented as covered by the original snapshot's review.

The configured Grok subscription review returned an attested `grok-4.7-build` model, requested as the driver's current `grok-4.7` frontier. The original structured response failed after its one automatic retry; the same configured driver then delivered the independent written report. Aladdin's drafting used the ChatGPT-family interface; its exact served model is not attested by this interface. This is a cross-family textual check, not a licensed lawyer's sign-off, and no fallback to another review family is claimed.

The current refinement and each earlier licensing artifact retain independent acceptance. No slice is closed. Final wording and publication remain unapproved.
