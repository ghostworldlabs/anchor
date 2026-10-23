# 2026-10-22 — Release v1.4.3: 2-Role Model Policy, Deliverables & Plan Refresh UX, 7-Day Usage Fix, and Dictation

## Context & Friction
1. **Health Check / One-Click Fix & Verify (`Gemini Argon 4`):**
   - Clicking one-click `Resolve all` (`handle_doctor_resolve_all` in `anchor_gui.py`) opened an interactive Doctor terminal when `audit-hmac` or `cockpit` repair issues were present or when the 5am `check_supervisor_seam` timed out (`--sleep 6` child exiting under morning load before the parent sampled).
   - Inside that interactive Doctor terminal (`terminal_session.py`), launching `agy 1.4.5` in interactive mode (`-i`) with `--model gemini-4-argon-high` triggered an `agy` startup race condition (`model gemini-4-argon-high is not recognized as a known model or custom model in settings` / `plan model not specified`) because `agy -i` checks `--model` before loading custom settings (`~/.gemini/antigravity-cli/settings.json`).
2. **Model Role Simplification (`Orchestrator` + `Reviewer`):**
   - Having 4 separate role selectors (`Terminal`, `Coder`, `Reviewer`, `Judge`) created unnecessary complexity. John requested simplifying to 2 roles: **Orchestrator** (drives Terminal, Coder, and all skill orchestration) and **Reviewer** (drives Reviewer and Judge for cross-family adversarial validation).
3. **Deliverables Clicking Errors, `Editing` Pill, Detail Explosion, & Sort/Search:**
   - Clicking a deliverable in `For Review` added a persistent `✎ Editing` / `✎ Reviewing / Editing` badge (`review-lifecycle-pill is-editing`).
   - Clicking anywhere on a `.file-row` toggled `.expanded`, dumping a multi-paragraph wall of text.
   - Clicking `.pptx` deliverables without a registered PDF companion showed a dead "Slide preview unavailable" stub instead of rendering `office_preview.render_preview`, and clicking `.R` / `.py` script files downloaded raw bytes instead of opening rendered in the split-screen reader.
   - `Final Deliverables` (`tier-final`) lacked date-descending sort (`0047`) and search/sort controls.
4. **Cave of Wonders 7-Day Usage Stuck at ~$272 & Comma Formatting:**
   - `_compute_global_usage_summary` in `steward_routes.py` skipped `.anchor/usage_ledger/*.json` whenever `sid_map` was non-empty (`if led_dir.is_dir() and not sid_map:`), and reset `prev_u = {}` on turns with empty `usage: {}`, causing cumulative token counters to double-count or miss live cockpit turns.
5. **Plan Refresh Proposal & Review Feedback Reconciliation:**
   - Campaign plans were not surfaced with an explicit **Accept New Plan** / **Revert to Old Plan** proposal when deliverables or instructions changed the plan, and giving revision feedback in chat did not automatically clear stale `For Review` red flags.
6. **Dictation Accuracy & Latency:**
   - `dictation_engine.py` hardcoded `faster-whisper-tiny` with `beam_size=1` and no domain vocabulary prompt, and `shared.js` did not invoke `spawnBrowserRecog()` alongside microphone capture.

## Fixes Landed (v1.4.3)
- **Doctor & `agy -i`:** Increased `check_supervisor_seam` child sleep to `20s`, added `supervisor-seam-5am-load` playbook recipe, gated `fix_audit_hmac()` and `repair_cockpits()` in `handle_doctor_resolve_all`, and omitted `--model` on interactive `agy -i` TUI launches in `terminal_session.py` so `agy` reads `model` from `~/.gemini/antigravity-cli/settings.json` cleanly.
- **2-Role Model Policy (`Orchestrator` + `Reviewer`):** Simplified dashboard selectors to **Orchestrator** and **Reviewer** and mapped `orchestrator_family` / `reviewer_family` across `anchor_settings.py`, `anchor_gui.py`, `job_runner.py`, Trio (`drivers/index.mjs`, `drivers/model-policy.mjs`), and Skill Foundry (`AGENTS.md`, `skills/ramanujan/src/seat.mjs`).
- **Deliverables UX & Search/Sort:** Removed `✎ Editing` badge, wired `.expanded` toggle exclusively to `.file-exp-btn` with compact 1-line drawer summaries, enabled `office_preview.render_preview` for `.pptx?view=1`, enabled rendered split-screen reader view for `.R`/`.py` files, and added newest-first sorting + search/sort controls to `Final Deliverables` (`tier-final`) and `All Deliverables` (`tier-all`).
- **7-Day Usage & Commas:** Fixed `_compute_global_usage_summary` in `steward_routes.py` to always aggregate `.anchor/usage_ledger/*.json` (deduping by `session_id`) and preserve `prev_u` across empty usage turns; formatted all dollar, token, and count displays with commas across `shared.js`, `provider-controls.js`, and `usage_allowance_monitor.py`.
- **Plan Proposal & Review Reconciliation:** Added `read_plan_proposal`, `resolve_plan_proposal` (`/api/plan-proposal`), and `reconcile_review_on_feedback` in `steward_campaign.py` + `steward_routes.py` + `shared.js`.
- **Dictation:** Upgraded `dictation_engine.py` to prefer cached `small.en`/`base.en` models with `beam_size=2` and domain vocabulary prompt, and wired `spawnBrowserRecog()` in `shared.js`.
