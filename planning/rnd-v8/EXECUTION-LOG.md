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
### Wave 2 — Trio document persistence (THE KEYSTONE) — GREEN (2026-06-16)

**Built (backend):** `effort_history.persist_session_docs(folder, pid, lane, session, worktree)`
— detects produced docs via `git status --porcelain -uall` ∪ `git diff --name-only HEAD` in
the worktree, filtered to `.md`/`.pdf` under planning/research/build/deliverables + bare trio
doc names (excludes `.anchor`/`.git`/node_modules/etc.); COPIES them into the main folder
(skips byte-identical); records DISCOVERED efforts with main-folder `artifact_path`s (so
`list_efforts`/`discover_recent_plan_set` resolve them); COMMITS scoped (`git add --` only the
produced docs + pointer/index, never `-A`; refuses the Anchor repo; message `anchor: <lane>
session <id8> docs`). Idempotent (re-persist → no commit), scoped (user's unrelated files
untouched), never raises. `terminal_session.capture_session_docs` (generalizes v6
`capture_plan_set`) wired into `kill` BEFORE `remove_worktree` (reap PTY → mark DONE →
persist → remove).

**Orchestrator verification:** `tests/test_doc_persistence_v8.py` (7) — copied+scoped-commit;
user's unrelated file never staged; **survive-reap** (kill → worktree gone, docs remain);
**build-worktree-contains** the plan docs; **discover-finds** them from main; idempotent;
no-docs honest no-op. v6 auto-advance/chain stay green (stub session → no worktree docs →
`no-docs` no-op).

**Handoff note (for Wave 4):** the gui `term_kill` captures the plan_set BEFORE kill, but
persistence now runs inside kill — Wave 4 must reorder so persistence precedes the plan-set
capture (or capture after kill) for the auto-advance to see freshly-produced docs.

**Gate:** **904 passed, 1 skipped** (+7). Backend-only. Commit: scoped.

<!-- WAVE 2 done -->
### Wave 3 — Link GitHub + Option-A auto-push — GREEN (2026-06-16)

**Built (UI + backend):** new `project_remote.py` (reuses `worktrees._git`): `link_github`
(mode=create → `gh repo create --private` THROUGH the `ANCHOR_GH_CMD` seam; mode=existing →
`git remote add`; degrades to paste-URL when gh absent), `set_auto_push`/`get_auto_push`
(per-project opt-in on the rnd_registry record), `push_project`, `auto_push_if_opted`,
`remote_status`. Endpoints (token-gated): POST `link_github`/`set_auto_push`/`push_now`,
GET `remote_status`. Header UI: "Link GitHub" → inline Create-new-private / paste-existing /
not-now prompt; once linked → `owner/repo` label + auto-push opt-in checkbox + "Push now".
`_auto_push_on_finish` wired into the kill/finish path — pushes ONLY when linked + opted.

**Build note:** the first execute agent hit a transient classifier/500 mid-wave (backend
landed, UI/tests cut off). Verified the partial tree was SAFE (this repo's remote unchanged,
no stray commits, gh/push all behind the `ANCHOR_GH_CMD` seam) and a continuation agent
finished the UI + tests + screenshot. The continuation **found+fixed a real bug**: the prior
agent referenced `_auto_push_on_finish` without defining it (NameError swallowed by try/except
→ auto-push silently never fired); now defined.

**Orchestrator verification:** `tests/test_github_link_v8.py` (+ `tests/stub_gh.py`) — link
create (seam stub → private, persisted) / existing (LOCAL BARE remote, no network) / opt-in /
auto-push-on-finish ONLY when linked+opted (push lands in the local bare remote; non-opted
never pushes) / manual push / gh-absent paste-only / all endpoints token-gated. NEVER real
network/gh/github.com. **Screenshot reviewed** — `_devtest/wave3_github.png`: header shows
`🔗 johncliechty/repo · ☑ auto-push · ↑ Push now`.

**Gate:** **921 passed, 1 skipped** (+17). ⚠️ **Pending John's UI sign-off before merge.**
Commit: scoped.

<!-- WAVE 3 done -->
<!-- WAVE 4 — Handoff that carries the documents -->
<!-- WAVE 5 — No-loss lifecycle: summary+docs on kill, promote to big tiles, detail view -->
<!-- WAVE 6 — Grass: self-contained, cumulative, exportable -->
<!-- WAVE 7 — Full chain navigation -->
<!-- WAVE 8 — CLI mirror + healthcheck v8 + distro scan + docs (PROJECT DONE) -->
