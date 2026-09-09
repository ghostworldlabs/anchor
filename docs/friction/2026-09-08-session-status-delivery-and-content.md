# General session-status improvement report

Date: 2026-09-08. Reported by John during the MBA Teaching AI campaign. Scope: Anchor session status across projects and providers. **General repair remains open.** This report records an observed failure and required proof; it does not certify an engine fix.

This incident is filed in Anchor’s general friction intake and linked to the earlier open report `2026-07-26-03-a-documented-status-cadence-with-no-sche`. The canonical report is `C:/dev/Anchor/docs/friction/2026-09-08-session-status-delivery-and-content.md`; an identical campaign copy makes it openable from the cockpit register.

General intake record: `2026-09-08-01-why-are-we-not-getting-status-updates` (open).

## What John experienced

John asked, “Why are we not getting status updates?”, then directed that the forgetting and the discovered flaw be journaled for general improvement of status within sessions. Jarvis had relied on writing campaign files and the engine timer without checking that the pane showed current, useful progress. This made John chase status and restate the reporting requirement.

## What the evidence establishes

The campaign’s `.ecgberht/delivery.json` recorded actual browser render acknowledgements at **19:26 and 19:36 local time on September 8**. They establish one successful ten-minute delivery interval. A generated status at 19:34 with a last acknowledgement at 19:26 was only an eight-minute difference; it did not establish a broken timer. No new acknowledgement was fabricated during the investigation.

The status content was misleading. It selected an old homework step, showed an irrelevant elapsed estimate of roughly 32,854 minutes, omitted this session’s numerical and Chrome test results, and treated “No outstanding scope decision…” as a literal user blocker. The campaign had already completed a sample-means browser run of 1,000 means with n=500 in 153.86 seconds, but that result did not populate the pane’s Tests row.

## Flaws and code locations

| Flaw | Observed mechanism | General consequence |
|---|---|---|
| Wrong current work | `steward_campaign.py`, `slice_of` and `compose_status`, pick the first active projection row. An old homework item and a parent milestone preceded the actual lecture slice. | Multiple active rows can hide the work actually running; progress and ETA follow the wrong item. |
| Working state expires | `read_map` downgrades working attention after 120 seconds unless a recognized owner heartbeat is fresh. The interface instruction only required a stamp at launch and completion. | A launch-only stamp cannot maintain background eligibility. This can suppress background cadence when both engine busy and queue are false; that causal chain was not established for the observed delivery interval. |
| Local results omitted | `compose_status` populates Tests from a live external skill report; it does not consume this session’s numerical/Chrome receipts. `shared.js` renders `stat.journal`, which the composer does not supply for this case. | Useful local work disappears from Tests and Journal even when its receipts exist. |
| False user blocker | `_real_wait` only treats a short set of literals as empty. Explanatory “no decision” prose was nonempty. | John sees “waiting on you” despite owing no action. |
| False goal warning | `read_map` compares the latest goal-flip step to the last done step in projection order. Later demo-iteration reaffirmations referred to drafts still waiting on classroom acceptance. | A valid prior research close appears to lack its North Star reread. |
| Delivery not verified | Jarvis checked state writes without following their actual render acknowledgements. | Generated status is mistaken for delivered, useful status. |

## Corrections already made in the campaign

The homework item and Block 1 umbrella now wait on their real dependencies, leaving the lecture revision as the current active step. The no-decision field uses the supported empty meaning. The North Star was re-read and the completed research verdict reaffirmed. The actual installed composer then selected `lectures-3-4-revision`, reported the reread, emitted no false user blocker, and read quiet at completion.

These are **campaign-data corrections only**. No Anchor engine source was changed. The local test/journal ingestion gap remains. The canonical user-global rule now requires verifying real render receipts and refreshing working evidence from observed activity within the reader’s lease. It must not keep dead work alive or invent a delivery receipt.

## Proof required before the general issue can close

| Acceptance area | Required evidence inside real sessions |
|---|---|
| Timely pane delivery | Record generation and actual browser rendering separately during continuing work, over at least two configured cadence intervals. Verify the visible pane and real acknowledgements, not a hand-written status file. A missed deadline must become visible. Keep scheduled tables out of the conversation. |
| Correct current work | Exercise a parent milestone, an old active item and the actual current slice together. The pane must identify the actual work and derive progress, ETA, dependencies and North Star state from the relevant records. Preserve real acceptance gates without inventing user blockers. |
| Local tests and journal | Run a meaningful local check and record a failure or correction. The next status must expose the relevant result and journal update with source and time. Distinguish passed, failed, untested and unavailable evidence. Do not replace unknowns with invented success. |
| Background and restart | Keep real supervised work running beyond 120 seconds, let the model become idle, and exercise supported session/provider restart. Pane delivery and working state must remain accurate; completed work becomes quiet and abandoned work expires. Pending authorization must survive restart. |

Focused automated regressions should accompany the change, followed by real browser evidence for the session/provider paths the implementation claims to support. A passing composition test alone does not certify delivery, lifecycle behavior or the general fix.

## Evidence trail

Campaign: `C:/dev/MBA Teaching AI`. Incident and ownership account: `.ecgberht/session-journal.md`; raw status and delivery records: `.ecgberht/status-summary.json` and `.ecgberht/delivery.json`. Campaign corrections were committed as `a17f115`; explicit forgetting and prevention as `fba2fb2`. The browser/numerical receipts remain under `BA 815/Fall 2026/build/review-september8/` and the associated scripts.

Relevant installed source: `C:/dev/Anchor/steward_cockpit/steward_campaign.py`, `steward_engine.py`, and `static/shared.js`. The ten-minute timer is owned by the engine. Intake status stays open until a general fix is implemented and supported by the evidence above.
