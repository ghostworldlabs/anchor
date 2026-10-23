# Doctor cockpit surface check — October 8, 2026

John requested repair of the single reported Doctor issue:
`[Steward cockpit surface] engine never reached 2 turn_end events
(events: ['delta', 'delta', 'delta', 'delta', 'delta', 'turn_end', 'status', 'status'])`.
Both live version and status endpoints were reported responsive.

Initial source diagnosis: the healthcheck immediately sends a human message
while the fake engine's automatic stand-up is running. The current human-first
engine deliberately interrupts that control turn and answers the queued human
message after resuming. The healthcheck still expects two completed turns from
that sequence. No live campaign data or skill changes are authorized or needed.

The first isolated run passed because an unrelated decision-shape retry
provided a second completed turn. A bounded reproduction suppresses that
unrelated correction and waits for the fake native initialization before the
human message preempts stand-up. This changes only the reproduction process,
not application source or saved settings.

The repair retains the direct first-message path and sends two distinct human
messages. Each must be acknowledged, stream its expected fake reply, complete
that reply, publish status, and settle with no queued messages or broken
engine. An automatic greeting or correction cannot substitute for either
reply. The existing 30-second deadline remains, using a monotonic clock.

The bounded reproduction failed after 30.96 seconds with the exact reported
event tail; its [receipt](2026-10-08-doctor-steward-reproduction.json) is retained.
The repair also resets streamed text at completion/interruption boundaries,
so text from one turn cannot qualify another, and rejects explicit engine
errors even if a plausible reply was streamed first.

Independent source review used the supplied engine and check excerpts and
the final bounded implementation description. Its suggested per-turn reset
and error rejection were incorporated; no remaining serious finding was
reported. That reviewer ran no checks and was not a cross-provider review.

All 10 targeted tests passed: real fake-engine exchanges with and without an
incidental decision retry, plus rejection of a greeting substituted for a
reply, missing completion, missing second reply, missing status, an error
after plausible text, text split across separate turns, ongoing work and an
undelivered queue. Fake mode intentionally omits canonical conversation
history; no claim of persisted human/steward history is made for this walk.

The complete existing Doctor suite ran once through the established
isolated snapshot runner, adapted only for this repair's evidence filenames
and source hashes. Live registries/campaigns were not copied; unrelated
listener/age cleanup is omitted, with owned-server teardown retained. The
prior daily report was preserved. No live service/session restart was needed.

The final suite completed successfully in 239.9 seconds: **34 correctness
checks passed, zero issues**, with one retained non-blocking startup warning
(the owned test server became ready after 157.1 seconds). Both live version
and status probes returned HTTP 200. The [daily report](../../health_reports/2026-10-08.md)
and [verification receipt](2026-10-08-doctor-steward-verification.json) are saved.

Existing-client inspection remains unavailable. A temporary hidden task ran
the established read-only capture in Windows interactive session 1, before
and after report publication; it found no unambiguous Anchor or Cave window.
The owned task was removed. No client was reloaded and no session was restarted.
The [capture receipt](2026-10-08-doctor-steward-client/existing-client.json)
qualifies this separately from a fresh app.

An additional authenticated read completed login and Doctor status, but the
fresh `/high-seat` response timed out after 30 seconds before its result
could be saved. This is a display-inspection limit, not evidence of banner
cleanup; no native engine event reads were made. The existing
[Cave banner display gap](2026-10-07-cave-health-banner-cleanup.md) remains
open and no claim of visible cleanup in John's persistent Cave is made.
