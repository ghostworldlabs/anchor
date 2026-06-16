# Anchor R&D Surface v8 — "Durable Artifacts" — Execution Log

> Per-wave EXECUTE / REVIEW / FIX / GATE history for the Foreman build of v8. Frozen
> plan: `MASTER-PLAN.md` + `IMPLEMENTATION-PLAN.md` (this folder). Branch:
> `foreman/rnd-surface-v8` (off master `80ead40`, which has v7 merged).

## Baseline

- **2026-06-16** — Branch `foreman/rnd-surface-v8` created off master (v7 merged).
  v7 baseline = **888 passed, 1 skipped**. GREEN floor; every wave holds or grows it.

## Wave records

### Wave 1 — Project bootstrap (auto git-init + starter CLAUDE.md) — GREEN (2026-06-16)

**Built (backend):** new `project_bootstrap.py` (reuses `worktrees._git`, no forked git):
`ensure_git_repo(folder)` — idempotent best-effort `git init` + initial commit honoring
`.gitignore` (no-op on an existing repo; clean `{"ok":False,"reason":"git-unavailable"}`
without raising when git absent); `ensure_claude_md(folder, name)` — writes a minimal
starter only when absent (NEVER overwrites); `bootstrap_project` (CLAUDE.md then git).
Wired (best-effort) into `select_existing_project` (was missing git init — the gap),
`create_new_folder_project`, and `discover_and_adopt` (covers both rescan + the open/
`GET /project/<id>` path). After bootstrap, `create_worktree`/research-start no longer
returns `not-a-git-repo` — the user's error is fixed.

**Orchestrator verification:** `tests/test_project_bootstrap_v8.py` (11) — init+idempotent+
honors-gitignore+git-absent-clean; CLAUDE.md created-when-absent + never-overwrites; register/
rescan paths bootstrap; **error-fixed** (pre-bootstrap create_worktree `not-a-git-repo` →
post-bootstrap ok). **Behavior change** (intended): updated `test_new_project.py` —
`test_create_new_folder_git_init_optional` → `test_create_new_folder_always_git_repo`
(every project is now a git repo + has a CLAUDE.md regardless of the legacy git_init flag).

**Gate:** **897 passed, 1 skipped** (+9). Backend-only. Commit: scoped.

<!-- WAVE 1 done -->
<!-- WAVE 2 — Trio document persistence (KEYSTONE) -->
<!-- WAVE 3 — Link GitHub + Option-A auto-push -->
<!-- WAVE 4 — Handoff that carries the documents -->
<!-- WAVE 5 — No-loss lifecycle: summary+docs on kill, promote to big tiles, detail view -->
<!-- WAVE 6 — Grass: self-contained, cumulative, exportable -->
<!-- WAVE 7 — Full chain navigation -->
<!-- WAVE 8 — CLI mirror + healthcheck v8 + distro scan + docs (PROJECT DONE) -->
