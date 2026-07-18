# Implementation Plan: Anchor Doctor UI V2

test-command: python -m pytest -v test_doctor.py

**North Star:** Transform Anchor Doctor into a production-grade diagnostic dashboard identical to Prototype 1. The UI is clean, responsive, and wired to real data. The embedded terminal functions as a context-aware Diagnostic AI Agent that can run `doctor.py`, read reports, and present human-facing summaries.

## Wave 1
**Title:** The Agentic Backend Endpoint
**Deliverables:** 
- Create `anchor_doctor_agent.py` which wraps a call to the Gemini API (using `google.generativeai` standard library).
- Create `test_doctor.py` with pytest assertions to verify the backend logic.
- Implement the core system prompt that enforces ASCII-only output.
- Modify `/api/doctor/run` in `anchor_gui.py` to route to this new agent script instead of blindly spawning `doctor.py`.
**done-when:** Submitting a text prompt to `/api/doctor/run` successfully streams or returns an AI-generated response.

## Wave 2
**Title:** Introduction & Summarization Routine
**Deliverables:** 
- Update the fetch block in the `/doctor` route's `<script>` section so it sends `init=true` on initial page load.
- Update `anchor_doctor_agent.py` to intercept `init=true`. When detected, it reads the latest `health_reports/YYYY-MM-DD.md` file, feeds it as context, and generates a short, bullet-pointed, human-facing summary of Anchor's state.
- Add the list of capabilities to the bottom of the intro summary.
- Update `test_doctor.py` to add a test explicitly asserting the `init=true` behavior, ensuring the test suite exercises these changes.
**done-when:** Reloading the `/doctor` page automatically streams a summarized, context-aware greeting.

## Wave 3
**Title:** Final GUI Polish & Error Handling
**Deliverables:** 
- Harden the regex parsing in `anchor_gui.py` (specifically `run_time` and `errors_count` extractors) so they default gracefully if a report is malformed or missing, preventing `500 Internal Server Error` crashes.
- Ensure the layout CSS uses `flex-shrink` and proper `overflow` so the terminal and cards resize cleanly on smaller screens.
**done-when:** The `/doctor` route renders perfectly with no 500 errors even if `health_reports/` is empty or corrupted.
