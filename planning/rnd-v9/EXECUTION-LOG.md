# Anchor R&D Surface v9 — "Tidy" — Execution Log

> Per-wave EXECUTE / REVIEW / FIX / GATE history for the Foreman build of v9. Frozen
> plan: `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` (this folder). Branch:
> `foreman/rnd-surface-v9` (off `foreman/rnd-surface-v8` HEAD `d09ec8d`, which has v8 +
> the dashboard perf fix).

## Baseline

- **2026-06-16** — Branch `foreman/rnd-surface-v9` created off the v8 branch (v8 deployed
  + the perf fix). Baseline = **982 passed, 1 skipped**. GREEN floor; each wave holds/grows.

## Wave records

### Wave 1 — True session delete (keep documents) — GREEN (2026-06-16)

**Built (backend + UI):** `effort_history.delete_session_efforts` (clears the session's lane
effort pointer-records + index entries via the v8 `efforts_for_session_id` join, reusing
`_delete_effort_record`, + the cached summary dir `summaries/<sid>/`; NEVER the produced
documents — Option A). `terminal_session.delete_session` (kills a live session first, then
`session_registry.remove_session` [the existing-but-unused primitive], then the effort/summary
cleanup; best-effort, idempotent, never raises) + `cleanup_ghost_sessions` (sweeps empty
terminal/idle records with no efforts; spares RUNNING + with-work). Endpoints
`POST /api/rnd/term_delete` + `cleanup_ghost_sessions` (token + explicit `confirm`). UI: a red
**✕ delete** control in the panel header top-right — distinct class/glyph/handler/endpoint/CSS
from the v8 🗑 kill (kill ends a running session; ✕ removes the record entirely), confirm-gated;
+ a `_DELETED` suppression set (belt-and-suspenders vs an in-flight repopulate). Survives
refresh because the registry record is genuinely REMOVED (term_sessions/_gather_project_sessions
read the registry) — the v6 page-load-only `_KILLED` bug is moot.

**Orchestrator verification:** `tests/test_session_delete_v9.py` (12) — clears record+efforts/
index+summary while produced docs remain; drops from list_sessions/board + survives reconcile;
idempotent; unknown-id no-raise; live-delete reaps worktree first; ghost cleanup spares
RUNNING/with-work; endpoint auth + confirm-required; DOM (red ✕ present + distinct from kill;
positive+negative); Playwright (delete → tile gone → **reload → still gone** → docs unaffected).
**Screenshot reviewed** — `_devtest/wave1_delete.png`: the solid-red ✕ delete button in the
panel header, distinct from the 🗑 kill.

**Gate:** **994 passed, 1 skipped** (+12). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 1 done -->
### Wave 2 — Grass idea delete — GREEN (2026-06-16)

**Built (backend + UI):** `effort_history.delete_grass_idea(folder, pid, idea_id)` — removes the
idea pointer-record + grass index.json entry (W1 `_delete_effort_record` pattern) + the
refinements dir (`shutil.rmtree`) + cleans the `dev_sessions` map (best-effort
`terminal_session.delete_session` per contained develop session, fallback `remove_session`);
idempotent, never raises, project-scoped. `POST /api/rnd/grass_delete` (token + explicit
`confirm`). UI: a red **✕** (`.gli-del`) on each idea row (`_render_grass_idea_li`) →
`deleteGrassIdea` (confirm-gated, `stopPropagation` so it doesn't select the row) → removes the
row + clears the workbench pane if it was selected; `grass_workbench_data` no longer lists it.

**Orchestrator verification:** `tests/test_grass_delete_v9.py` (12) — clears pointer+index+
refinements+dev_sessions; gone from `grass_workbench_data`; **siblings + other projects
untouched**; idempotent + unknown-id no-raise; endpoint auth + confirm-required; DOM (one
`.gli-del` wired to deleteGrassIdea, ✕ glyph not 🗑; positive+negative); Playwright (delete victim
→ gone, sibling stays). **Screenshot reviewed** — `_devtest/wave2_grass_delete.png`: both idea
rows show a red ✕.

**Gate:** **1004 passed, 1 skipped** (+10). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 2 done -->
<!-- WAVE 3 — Project folders: group field + collapsible UI + drag-to-group -->
<!-- WAVE 4 — Project folders: guarded on-disk move -->
<!-- WAVE 5 — CLI mirror + healthcheck v9 + distro scan + docs (PROJECT DONE) -->
