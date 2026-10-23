# Cave health banner remains after Doctor resolves its issue

The R&D v6 correctness issue is repaired and the latest health report says
`Status: OK`, with zero issues. An open Cave can nevertheless retain its earlier
red "Health check found issues" banner. This is a separate display defect:
Anchor does not reconcile the existing banner when the report changes.

John reported the remaining warning after the repair receipt. His original
words are retained verbatim in Anchor's canonical friction intake. The display
repair remains open; this entry records analysis and proposed verification.

Canonical intake:
[Cave retains resolved Doctor health banner](../../friction/2026-10-07-01-cave-retains-resolved-doctor-health-bann.json).
Readback confirmed the original words, open status and inclusion in the
existing generated open-friction brief. Independent bounded review of the
supplied source and evidence found the conclusion and stated limits sound;
that reviewer ran no additional checks.

## Established cause

1. `anchor_gui.latest_health_report()` reads the report's `Status:` on every
   request. `_high_seat_context()` passes that status to
   `home_attention.build_attention()`. Only ISSUE, FAIL or ERROR produces a
   `health` row; `Status: OK` produces none.
2. `high_seat_page._health_banner()` renders `.healthbar` from that row during
   initial page construction. The current authenticated Cave response has no
   banner. Doctor's yellow state comes from the independent, non-blocking
   120.8-second test-server startup warning. That warning does not create the
   Cave's correctness banner.
3. `static/app.js` retains the Cave iframe for the entire app session.
   `static/high-seat-page.js::refreshFaces()` fetches current Cave HTML, then
   updates tile faces, `#nudgeSlot` and `#lane`. It neither replaces nor removes
   `.healthbar`. A health-only report change also does not move the campaign
   stamp that normally causes those refreshes. Both omissions need handling.

## Verification and limits

- A normal login cookie was used in fresh Chromium against the running app.
  Its Cave showed no health banner; the actual screenshot was inspected.
- In that separate browser, the real banner renderer supplied an earlier
  `ISSUES FOUND` banner, injected into browser memory only. An inspection hook
  exposed the existing `refreshFaces()` without changing production source.
  Its actual `/high-seat` response was HTTP 200 and contained no health banner.
  The old visible banner remained afterward. Its screenshot was inspected;
  the same composer node survived.
- Native GET event soft-wakes and browser writes other than normal login were
  guarded. The guarded event replies were immediate and produced many local
  poll requests; no paid work was started. Closing the isolated browser emitted
  a Playwright target-closed cleanup diagnostic after all assertions passed.
- A read-only interactive capture could not find a local Anchor window. The
  temporary scheduled task was removed. Its first registration used the wrong
  account separator and was corrected using the current Windows identity.
  John's specific existing client was not directly inspected. The source and
  controlled reproduction establish the defect; his original report supplies
  the observation that his own Cave still shows it.
- Evidence and repeatable inspection scripts are in
  [the evidence directory](2026-10-07-cave-health/live-evidence.json), with
  [the browser receipt](2026-10-07-cave-health/browser-receipt.json),
  [fresh app capture](2026-10-07-cave-health/fresh-app.png), and
  [stale banner after refresh](2026-10-07-cave-health/stale-after-refresh.png).

## Why the completion receipt missed it

The repair gate checked the relevant tests, fresh health report, live version
and status endpoints, and Doctor's JSON status. It did not inspect or prove
cleanup in the already-open Cave. "Zero open issues" described the corrected
report accurately, but the visible completion boundary was incomplete. A
server restart or a fresh driven browser would not by itself establish that
the persistent Cave in John's existing client had updated.

## Proposed repair and acceptance checks

Reconcile the health banner in place through a read-only health refresh that
also runs for report-only changes, on a bounded cadence and return to the Cave.
Remove the old correctness banner when the authoritative report is clean;
show current genuine failures and their exact Doctor context. Preserve the
last known indication on read failure. Keep timing warnings available in
Doctor. Preserve composer nodes, drafts, initiative frames, tile identities
and separate reaper alerts. Avoid restarting sessions or reloading the entire
Cave to clear a banner.

Acceptance must use an already-open Cave in the app: display a real synthetic
failure, update only the owned report to OK, and observe the banner disappear
without a campaign stamp change, page reload or lost draft. Repeat with a new
failure, a failed health read, warning-only report, visibility return and tile
switching; verify that Doctor and Cave share the same current report. Inspect
the actual existing client separately from fresh Chromium, and guard native
event wakes and writes in any diagnostic browser.

No banner implementation or live-session activation was performed for this
analysis and journaling request. The original worktree repair remains intact.
