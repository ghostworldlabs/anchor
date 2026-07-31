# Changelog

## 2026-07-30 — Steward usable with auth on · workbench tile collapsed

- **The steward can set a goal again.** Three independent faults made every
  steward act impossible on a token-authed dashboard: the POSTs sent the token
  as `?token=` (the POST middleware never reads the query → 401 → a re-prompt
  for a token the window already held); `handle_ecgberht_stand_up` was declared
  `migrated=True` but never registered in `_MIGRATED_HANDLERS` (→ 404 "Unknown
  endpoint"); and `do_POST` dispatched on the raw request line, so any POST
  carrying a query missed its exact route row. All three fixed and gated.
- **Two more dead endpoints found by the new route gate** — `GET
  /api/rnd/friction` and `POST /api/rnd/journal_friction` had the same missing
  registration and no legacy fallback. The friction journal's own read endpoint
  was one of them.
- **A 401 now retries instead of reloading in the project window** (home already
  did, since 2026-07-28) — a reload discarded the goal input / saybox draft on
  the first click after a token rotation.
- **Workbench tile opens COLLAPSED on project dashboards**, with a click-to-
  expand / click-to-collapse control on the tile summary.
- **Jarvis seal label is the "Server"** (was "Salver", which reads wrong at a
  glance). Image filenames unchanged.
- **Repaired two long-dead tests**: the fetch-wrapper contract tests asserted a
  `location.reload()` the product had deliberately dropped, and
  `test_token_hygiene_lifecycle` had never run a single secret-absence
  assertion. Both now assert the real contract (the hygiene scan is
  mutation-checked).
- **Standing rule added** (DECISION-LOG): auth-off green is not green — any wave
  touching a mutating endpoint must add an auth-ON case asserting the outcome.

## v1.0.0 — 2026-07-23

First shareable product release of Anchor + integrated Skill Foundry skills.

- Human skill cards (HUMAN.md) in Foundry GUI
- Zombie Hunter multi-engine burn ledger + Tailscale-safe reverse proxy
- Tidy-Idy triage panel with Grok investigator option
- Single-use bootstrap reissue: spent nonces never dump raw JSON; HTML 410 + host reissue path
- Spawn-cap census prune; default ANCHOR_SPAWN_CAP=32

## 2026-07-23 — Tidy-Idy bootstrap reissue (share-ready)

- **Spent bootstrap no longer dumps raw JSON.** Single-use SC4 nonces: Anchor re-click POSTs host-only /api/reissue-bootstrap when the panel is still live; otherwise marks status stale and starts a fresh pass.
- **Proxy:** on /bootstrap/ 410, attempt reissue + redirect, else HTML 410 page (never forward spent JSON body over Tailscale).
- **Never open panel_base alone** (that path is health JSON starting with {).

## 2026-07 — Rearchitecture

### W11 (C6) — Data-dir migration + git hygiene
- **Runtime state moves OUT of the repo as one rollback-able unit.** The scripted
  migration (`migrate_data_dir.ps1` → `tools/migrate_data_dir.py`) copies the data
  allowlist into the new `ANCHOR_DATA_DIR`, path-rewrites every repo-rooted
  absolute path to the new root, verifies zero remain, arms the reaper dry-run,
  and **rolls back** (removes the partial new root; old dir untouched) on any
  failure. The ops wrapper stops the service, points NSSM at the new dir, restarts,
  healthchecks, and preserves the old dir read-only for a week.
- **Path-audit tool** (`tools/path_audit.py`): scans every durable store
  (`rnd_registry.json` folder_path, `.anchor/sessions.json` worktree_path,
  `rnd_jobs/*.json` log_path/cwd, per-project `discovery.json` + job records) for
  repo-rooted absolute paths and emits/applies a rewrite map (atomic, idempotent).
- **`ANCHOR_REAPER_DRYRUN`** (`worktrees.py`): the first post-move boot sweeps
  worktrees report-only (env override OR the armed `.reaper_dryrun` marker) so a
  rewrite miss can never delete a legit parked/live worktree; live reaping re-arms
  only after a **clean** dry report.
- **Git hygiene** (`tools/git_hygiene.py` + `.gitignore`): un-tracks the tracked
  runtime artifacts (`git rm --cached`, content kept) so a full healthcheck cycle
  leaves `git status --porcelain` empty. Gate: `tests/test_data_dir_migration_w11.py`.

### W10 (C5) — Markdown-parser de-fork + dead-server deletion
- **Removed `anchor_server.py`** — the dead legacy Flask app (port 5000, retired
  "Anchor PSU" dual-folder layout, ignored `paths.py`, imported by nothing,
  never shipped; superseded by `anchor_gui.py`). Pre-deletion sweep results:
  `docs/anchor_server-predeletion-sweep.md`.
- Extracted the task/project/inbox/archived markdown parsers (and
  `serialize_task_line`) into the single shared module **`anchor_md.py`**,
  imported by both `anchor_gui.py` and `anchor.py`; the byte-identical twin
  parsers are de-forked to one source of truth. Golden-corpus gate:
  `tests/test_anchor_md_defork_w10.py` proves identical parses of the real
  markdown files pre/post de-fork.
