# Cave banner did not clear after the Doctor repair

John reported that the Cave still displayed its health warning after the R&D
v6 repair. The current report and Doctor show zero correctness issues. The
remaining test-server startup warning is independent of the Cave's red banner.

Source inspection and a guarded browser reproduction establish that the
persistent Cave frame retains its old `.healthbar`: `refreshFaces()` never
reconciles that node, and health-only changes do not trigger a campaign stamp
refresh. The earlier completion gate checked the backend but missed cleanup
in the already-open Cave. Direct capture of John's current client was not
available; controlled screenshots were inspected and qualified as such.

Recorded as an open Anchor display/verification improvement. The proposed
repair reads health independently and updates the banner in place, preserving
drafts, conversations and genuine failure visibility. Production banner code
and active sessions were not changed. The project instructions now require
this existing-client completion check.

[Diagnosis, evidence, reproduction and acceptance checks](../docs/friction/2026-10-07-cave-health-banner-cleanup.md).

[Canonical open friction intake](../friction/2026-10-07-01-cave-retains-resolved-doctor-health-bann.json)
was verified by reading it back through the existing writer and generated
brief. John's words are preserved exactly.
