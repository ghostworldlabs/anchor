# Anchor R&D Surface v6 — "Linked Pipeline" — Execution Log

> Per-wave EXECUTE / REVIEW / FIX / GATE history for the Foreman build of v6.
> Frozen plan: `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` (this folder). Branch:
> `foreman/rnd-surface-v6` (off master `32c5a83`; base commit `a43273d` = the
> cherry-picked summarizer stream-json parse fix `1bd8b85`).

## Baseline

- **2026-06-14** — Branch `foreman/rnd-surface-v6` created off master. Cherry-picked
  `1bd8b85` (summarizer discarded all prod stream-json text → blank summaries) as the
  branch base. Full suite: **724 passed, 1 skipped** (the skip is the pre-existing
  host symlink/git skip). This is the GREEN floor; every wave must hold or grow it.

## Wave records

_(appended as each wave reaches GREEN — one record per wave: what was built, the
adversarial-review findings, fixes, the gate result/count, and the commit.)_

<!-- WAVE 1 — Summaries that actually work -->
<!-- WAVE 2 — Session linkage backbone -->
<!-- WAVE 3 — First-class session windows (maximize + free resize) -->
<!-- WAVE 4 — Tile lifecycle (new-session=new-tile + keep finished) -->
<!-- WAVE 5 — Manual advance research→planning + chain breadcrumb -->
<!-- WAVE 6 — Auto advance planning→build (gated on a real plan) -->
<!-- WAVE 7 — Main dashboard reflects project activity -->
<!-- WAVE 8 — CLI mirror + healthcheck v6 + distro + docs (PROJECT DONE) -->
