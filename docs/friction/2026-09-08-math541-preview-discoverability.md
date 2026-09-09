# Week 1 products present but hard to find and navigate

John reported this in the Math 541 Student Resources cockpit on 2026-09-08: promised products were not apparent under Week 1 or at the top of Deliverables. Campaign overhead increased by one.

Observed in the live service: both effort and union registers had all four files. The renderer truncates What at its first em dash, leaving the primary guide labelled only START HERE. Step matching placed the four links under distant artifact steps instead of the main Week 1 Foundations step. This was not missing output or a wrong project register.

Campaign correction: descriptive Week 1 Foundations prefixes, PDF format before the separator, first four register rows and exact main-step association. Durable rule added to campaign AGENTS.md; no duplicate register.

Opening the real served HTML also exposed broken sibling navigation. Relative paths resolve against the query endpoint; retaining the API endpoint is rejected by the opaque-origin navigation guard. Campaign HTML now uses the existing contained /artifact route for sibling navigation, preserving local relative links when downloaded. No security relaxation or Anchor code patch.

Acceptance passed on the running service: four recognisable top rows and main Week 1 links; all four documents HTTP 200; actual register click opened the example; radius/endpoint controls worked; click to cards succeeded and reveal worked. Evidence lives at C:/dev/Teaching/Math 541/Student Resources/reviews/week-01/delivery/live-delivery.json and the adjacent live screenshots. This does not claim verification on John's device.

For the Anchor owner: consider showing the first pending-review artifact without generic-prefix truncation and document a supported contained sibling-link mechanism for HTML producers. Any future change must preserve sandbox isolation and be checked through an actual cockpit click, not just API response tests. This note records the defect for the normal improvement intake; no app change is commissioned here.
