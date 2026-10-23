# Cave health refresh — October 8, 2026

John's follow-up asks when the already-open Cave banner goes down after
Doctor reports zero issues. The prior analysis established that the Cave
never reconciled its banner and only refreshed other content when the
Campaign stamp changed. This follow-up authorizes finishing that repair.

A standalone health reader now polls the existing authenticated Doctor
status endpoint every 15 seconds and on focus/visibility return. It only
updates/removes the direct health banner; it preserves the surrounding
composer, drafts and initiative frames. Failed, invalid and older responses
retain the last known banner. Warning-only reports clear the correctness
banner while keeping warnings in Doctor. No engine events or work launches.

The first targeted check invocation stopped at collection because the new
test imported the existing fixture without its `tests` package prefix.
The import was corrected; no product check ran in that invocation.

The first executed gate passed 35 checks and failed four. The new test used
the app row control ID instead of the initiative card's actual ID; this is
corrected to `card-p-one`. All eight focused browser checks now pass
(4.90 seconds): warning-only clearing, failure reappearance, retention after
malformed/failed/older responses, singleton loading, and preservation of
drafts, initiative iframe identities and composer identity. The existing
source-rendering checks also passed in the first gate.

Three existing app-header checks failed on narrow-row overflow and retained
attention; their fixture has no masthead, so the new reader does not run
there. The browser-only baseline plugin
`2026-10-08-cave-health/baseline.py` served `git HEAD:static/high-seat-page.js`
to the same fixture and reran exactly those three checks. All three failed
unchanged (13.22 seconds): `wrapped_rows[420]` and `resize_alone` have strip
overflow, and `green_attention` loses its ready state after a dropped-frame
state-read failure. These are independently reproduced pre-existing
failures outside this banner repair. No served files were reverted and the
failures remain recorded.

A same-family independent source review found no blocking defect in the
bounded health module and loader (`cross_model: false`). This review covered
banner-only DOM changes, health-state handling, singleton polling, failed
read recovery, request ordering, and existing authentication and tool links.
It did not review the actual engine or the live client.

The running service returned HTTP 200 for both changed static scripts, with
bytes matching the workspace. A normal cookie-authenticated Doctor status GET
also returned HTTP 200: `yellow`, `last_run: 2026-10-08`, no issues, and only
the 157.1-second startup timing warning. The receipt is
[live-reader-assets.json](2026-10-08-cave-health/live-reader-assets.json).
No full Doctor rerun was needed for this static repair; the preceding final
full run reported zero issues, 34 correctness checks and one timing warning.
`git diff --check -- static/high-seat-page.js` passed.

The focused Chromium fixture screenshots were visually inspected:
[health-cleared.png](2026-10-08-cave-health/health-cleared.png) shows the compact
heading after clearing, and
[health-returned.png](2026-10-08-cave-health/health-returned.png) shows the red
banner and controls restored while the expanded initiative retains its draft.
These are fixture observations, not inspection of John's existing client.

No service or session restart has been performed. Native capture found no
unambiguous Anchor/Cave window, and no browser remote-debugging listener was
available. Existing-client activation and visible banner cleanup are therefore
not claimed; the display gap remains open pending confirmation in John's
actual Cave.

One safe Cave page refresh is needed once to load the revised JavaScript.
After it loads, the correctness banner clears on the next successful Doctor
status GET showing no issues, normally within 15 seconds while the Cave is
visible. Warning-only timing information remains available in Doctor. Failed
or unknown reads continue to retain the last known banner.
