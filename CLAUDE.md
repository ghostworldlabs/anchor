# Anchor — Productivity System for J.C. Liechty

> **Single-folder layout (as of 2026-05-02):** Everything lives in `C:\dev\Anchor`. There is no Axmra sibling, no PSU sibling, no syncing — one folder, one tool.
>
> Historical note: this system used to be split across two OneDrive folders (Anchor PSU + Anchor Axmra) that synced to each other via a sibling-discovery mechanism. On 2026-05-02 the active folder moved to `C:\dev\Anchor` and the Axmra sibling was merged in and decommissioned. The frozen Axmra contents are preserved at `_archive/axmra-snapshot-2026-05-02/`. The old `Anchor PSU` OneDrive folder remains as an inert backup.

## Runtime / Host (as of 2026-05-12)
The Anchor server runs **persistently in the background** — you do not normally launch it by hand. Its lifecycle is owned by the **NSSM service `anchor`** (Windows service, `Automatic` start), which runs `python anchor_gui.py --no-browser` and binds `http://localhost:8777`.

**Host:** this is the same physical machine throughout — hostname `PUTER`, also referred to as **`gwl-server`** (its friendly / Tailscale name). Any code comment, doc, or plan that says `gwl-server` means this desktop; they are not two different boxes.

- **Restart the server:** `nssm restart anchor` (requires an elevated shell)
- **Stop / start:** `nssm stop anchor` / `nssm start anchor`
- **Status:** `Get-Service anchor`

Because the service owns the process, the dashboard no longer has a Stop button and the `/api/shutdown` endpoint has been removed — the UI cannot kill its own server.

> ✅ **Resolved (2026-06-08) — duplicate supervisor was a rogue NSSM service.** The real cause of stale-code-on-8777 was a **second NSSM service `Anchor-Server`** (WinGet nssm, created 2026-05-16, running old code) racing the legit `anchor` service for the port. Because the old code bound with `SO_REUSEADDR`, *both* servers could listen on 8777 at once and requests randomly hit old or new — and `nssm restart anchor` only restarts one supervisor. Fixes shipped: (1) a **single-instance guard** — the server now binds with `SO_EXCLUSIVEADDRUSE` (Windows) so only one Anchor process can own 8777; a duplicate exits(0) cleanly instead of squatting (see `paths.classify_bind_error`/`use_exclusive_bind`, `anchor_gui._ExclusiveThreadingHTTPServer`). (2) Every desktop launcher (`AnchorDashboard.vbs/.bat`, `launch_anchor.pyw`, `pin_anchor_to_taskbar.vbs`, `create_shortcut.py`) now **only opens the browser**, never spawns a server. (3) `fix_anchor_stale.ps1` (run elevated) removes the rogue `Anchor-Server` service, reaps 8777 by PID, restarts `anchor`, and verifies the new code is live. The Task Scheduler task **"Anchor Server"** is already Disabled and was NOT the cause. The `ledger` NSSM service (`ledger_gui.py`, port 8778) is unrelated — leave it alone.

## Quick Start
When the user says "Dashboard", "dashboard", "anchor", or "start":
1. The server is already running (NSSM service). Just open **http://localhost:8777** in the browser — no launch step needed. If it doesn't respond, run `nssm restart anchor` (elevated) or check `Get-Service anchor`.
2. Give a brief status summary (date, active tasks, upcoming deadlines, inbox count)
3. The GUI is fully interactive — user can check tasks done, add tasks, capture ideas directly in the browser. All changes save to markdown files automatically and are logged.

**IMPORTANT:** `anchor_gui.py` is the application. It runs as a persistent local web server (under the `anchor` service) and writes directly to the markdown files — no Cowork sandbox limitations. Only run `python3 anchor_gui.py` manually for local debugging when the service is stopped.

## Fallback (if GUI can't launch)
If the browser-based GUI can't be launched, fall back to:
1. Run `python3 anchor.py dashboard` to rebuild dashboard.html
2. Present `dashboard.html` using a computer:// link
3. User gives text commands: "done: [task]", "add: [task]", "capture: [idea]"

## CLI Commands (anchor.py)
- **"done: David Leavitt"** → Run: `python3 anchor.py done "David Leavitt"`
- **"cancel: Review paper"** → Run: `python3 anchor.py cancel "Review paper"` (moves to CANCELLED.md)
- **"save: Review paper"** → Run: `python3 anchor.py save "Review paper"` (moves to SAVED_FOR_LATER.md)
- **"restore: Review paper"** → Run: `python3 anchor.py restore "Review paper" --from saved` (or `--from cancelled`)
- **"add task: Review paper"** → Run: `python3 anchor.py add "Review paper" --domain academic --priority 2 --energy high --notes "See email from Dr. Smith"`
- **"capture: Look into MIT"** → Run: `python3 anchor.py capture "Look into MIT" --domain academic`
- **"update"** or **"refresh"** → Run: `python3 anchor.py dashboard` and re-present

## Task Lifecycle
Tasks can be moved through these states:
- **Active** → on the dashboard (DASHBOARD.md / domain files)
- **Done** → checked off in markdown (`[x]`), visible in Completed view
- **Cancelled** → removed from dashboard, stored in CANCELLED.md, reviewable in Cancelled view
- **Saved for Later** → removed from dashboard, stored in SAVED_FOR_LATER.md, reviewable in Saved view
- **Restored** → moved back from Cancelled or Saved for Later to active dashboard

Each task can have an optional **Notes** field for storing emails, links, references, or context.

## Daily Health Check
A self-test script (`anchor_healthcheck.py`) runs every morning at 5:00 AM via the Windows Task Scheduler task **"Anchor Health Check"**. It verifies file integrity, parses every markdown file, boots a throwaway server on test port 8778, exercises every endpoint, walks a synthetic `__healthcheck__` task through every state, then writes `health_reports/YYYY-MM-DD.md`. If anything failed, the dashboard shows a red banner at the top until the next clean run.

It also exercises the **v2 R&D surface** (`check_rnd_v2_surface`): it registers a synthetic project in a throwaway temp folder and walks `add_idea` / `promote_inbox` (grass) → `pin_deliverable` → reconcile preview → `status_line` shape → a discovered planning session → `GET /summary` + `regenerate_summary` → a terminal session start → `term_input` → `term_discover` → `term_adopt`. **Every model call is stubbed via `ANCHOR_RUNNER_CMD` → `tests/fake_claude.py` — never live `claude`.** The synthetic project and its temp folder are torn down afterward, the `ANCHOR_RUNNER_CMD` env is restored, and the existing `__healthcheck__` filtering is unaffected, so no real data is polluted.

If port 8778 is already occupied (e.g. by a stale/orphaned server the non-elevated check can't reap), the self-test automatically falls back to an OS-assigned free port and logs that under "Auto-fixes applied" — it no longer aborts the whole run over a busy test port.

- **Install / re-register scheduled task:** `powershell -ExecutionPolicy Bypass -File .\register_healthcheck.ps1` (run once; safe to re-run)
- **Run on demand:** double-click `Anchor Healthcheck.bat`, or `python anchor_healthcheck.py`
- **Disable:** `Unregister-ScheduledTask -TaskName "Anchor Health Check" -Confirm:$false`
- **Reports:** kept indefinitely in `health_reports/`. See `health_reports/README.md` for the format.

The synthetic `__healthcheck__` task is filtered out of every dashboard view by `gather_all()`, so it never shows up even if a check is mid-run when you refresh.

## File Structure
```
anchor_gui.py           ← Standalone GUI (local web server + browser dashboard)
anchor.py               ← CLI engine (reads/writes markdown, generates HTML; `rnd` v2 mirror)
anchor_healthcheck.py   ← Daily self-test (runs at 5:00 AM via Task Scheduler; also walks the v2 R&D surface, stubbed)
# R&D control surface v2 (design + plan frozen in planning/rnd-v2/):
rnd_registry.py         ← Id-keyed R&D project registry (status_line, blurb, reconcile_folder)
effort_history.py       ← Append-only per-lane effort pointer-records (add_idea, promote_inbox, adopt_sibling_sessions)
sessions.py             ← Session model — one trio run = one session (list_sessions, merge/split)
summarizer.py           ← Validated, cached session summaries (generate-twice + grounding filter)
rnd_terminal.py         ← Interactive terminal substrate (persistent stream-json REPL over SSE; not ConPTY)
deliverables.py         ← Deliverable declare/pin + per-type run contract
brownfield_scan.py      ← Discovery of on-disk trio artifacts + idea-docs (grass)
lanes.py / job_runner.py / gate_adapter.py ← Lane→skill mapping, durable job runner, gate stdin wiring
report_viewer.py        ← Markdown→HTML report/summary rendering (vendored KaTeX)
paths.py                ← Shared path/data-dir constants, WRITE_LOCK, auth + bind helpers (imported everywhere)
vendor/anchor-term/     ← Vendored lightweight terminal console (anchor-term.js/.css; swappable for xterm.js behind window.AnchorTerm.mount)
register_healthcheck.ps1 ← One-time setup for the scheduled task
Anchor Healthcheck.bat  ← Manual trigger for the health check (with console output)
launch_anchor.pyw       ← Silent launcher (no terminal window, used by shortcuts)
Anchor Dashboard.bat    ← Double-click to launch (Windows)
pin_anchor_to_taskbar.vbs ← Run once to create a pinnable Desktop shortcut
setup_shortcut.py       ← Alternative shortcut creator (uses pywin32)
dashboard.html          ← Static HTML dashboard (auto-generated by anchor.py)
health_reports/         ← Daily health-check reports (YYYY-MM-DD.md, one per run)
_archive/               ← Frozen historical snapshots (axmra-snapshot-2026-05-02 lives here)
CLAUDE.md               ← This file (project instructions for Cowork / Claude Code)
DASHBOARD.md            ← Daily dashboard with calendar, focus items, priorities
PROJECTS.md             ← Master project list across all domains
INBOX.md                ← Quick capture inbox
CANCELLED.md            ← Cancelled tasks (reviewable archive)
SAVED_FOR_LATER.md      ← Tasks saved for later (reviewable archive)
WEEKLY_REVIEW.md        ← Weekly retrospectives
domains/
  academic.md           ← Research projects, teaching, service
  commercial.md         ← Commercial projects (Nexia/Axmra Capital, OpX, Archty, NextGen Nuclear) — full detail, was previously summary-only
  family.md             ← Trusts, travel, personal finance
  writing.md            ← Chronicles of the Dragon-Kept, Artificial Magi
logs/
  YYYY-MM-DD.md         ← Daily activity logs (auto-created)
```

## Architecture (for developers / future sessions)

### anchor_gui.py — The Main Application
This is a self-contained Python HTTP server that generates the full dashboard HTML on every request. No external dependencies — just Python stdlib.

**Key sections (in order):**
1. **Paths** (top of file): All file path constants rooted at `ANCHOR_DIR = Path(__file__).parent`
2. **Parsing**: `parse_tasks_from_md()`, `parse_projects_from_md()`, `parse_inbox_from_md()`, `parse_archived_tasks()` — read markdown into Python dicts
3. **Data Gathering**: `gather_all()` — reads DASHBOARD.md + all `domains/*.md` files, deduplicates tasks by first 60 chars of lowercased text
4. **Change Operations**: `log_change()`, `mark_done()`, `mark_undone()`, `add_task()`, `capture_inbox()`, `edit_task()`, `edit_project()`, `cancel_task()`, `save_for_later()`, `restore_task()`
5. **HTML Generation**: `generate_html()` — one function that builds the entire dashboard as a single HTML string with embedded CSS and JS
6. **HTTP Server**: `AnchorHandler` class with GET `/` and POST `/api/*` endpoints

**Task markdown format:**
```
- [ ] Task text — Priority: 2 — energy: med — [domain] — Due: 2026-04-15 — Notes: some reference
```

**Archived task format (CANCELLED.md / SAVED_FOR_LATER.md):**
```
- 2026-04-11: Task text — [domain] — P2 — Notes: some reference
```

**API Endpoints:**
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Serve dashboard HTML |
| GET | `/api/status` | JSON status summary |
| POST | `/api/done` | Mark task done |
| POST | `/api/undone` | Reopen a completed task |
| POST | `/api/add` | Add new task (with notes) |
| POST | `/api/capture` | Add to inbox |
| POST | `/api/edit_task` | Edit task properties |
| POST | `/api/edit_project` | Edit project properties |
| POST | `/api/promote_task` | Move task to P1 |
| POST | `/api/demote_task` | Move task to P2 |
| POST | `/api/promote_project` | Move project to P1 |
| POST | `/api/demote_project` | Move project to P2 |
| POST | `/api/cancel` | Cancel task → CANCELLED.md |
| POST | `/api/save_for_later` | Save task → SAVED_FOR_LATER.md |
| POST | `/api/restore` | Restore from archive to active |
| GET | `/project/<id>` | R&D project window (rich Kanban "Dashboard A") |
| GET | `/summary/<pid>/<lane>/<session_id>` | Cached, validated session summary page (run-once on first view; rendered via `report_viewer`) |
| GET | `/report/<pid>/<lane>/<job_id>` | Read-only report viewer for one effort (PDF-by-default else Reader) |
| GET | `/artifact/<pid>?path=<rel>` | Serve a discovered (brownfield) artifact, traversal-safe |
| GET | `/api/rnd/projects` | List R&D projects (grouped by folder) |
| GET | `/api/rnd/term_stream?session=<id>` | SSE stream of a terminal session's output (bounded by `max_ticks`, heartbeated, ends on terminal status) |
| GET | `/api/rnd/tail?job_id=<id>&since=<n>` | Cursor-stable incremental job log read (long-poll-safe) |
| POST | `/api/rnd/new_project` / `open_project` / `rescan` | Register / open / re-discover a project |
| POST | `/api/rnd/set_priority` / `archive_project` / `future_project` / `retire_project` / `reactivate_project` | Project lifecycle (retained, never deleted) |
| POST | `/api/rnd/set_notes` | Set a project's free-text notes |
| POST | `/api/rnd/set_blurb` | Set the project blurb ("what this project is"); seeded once from `CLAUDE.md`/`README`/`Anchor.md` |
| POST | `/api/rnd/link_task` | Link/unlink a task to an R&D project (`Project: <id>` field) |
| POST | `/api/rnd/launch_lane` | One-shot lane job launch (research→researchPrime, plan→Crucible, build→Foreman) |
| POST | `/api/rnd/answer_gate` | Answer an in-flight AskUserQuestion gate (plan/build) |
| POST | `/api/rnd/start_terminal` | Start a PERSISTENT interactive terminal session for a lane (stream-json REPL; stdin kept open). Returns the `job_id` = session id |
| POST | `/api/rnd/term_input` | Write ONE user turn onto a live terminal session's stdin (reuses the gate-adapter stdin sink) |
| POST | `/api/rnd/term_discover` | On exit, return the adoption PROPOSAL (files this session produced) |
| POST | `/api/rnd/term_adopt` | Confirm-adopt a terminal session's produced files as ONE session in the lane |
| POST | `/api/rnd/regenerate_summary` | Force re-run + re-cache a session's validated summary (through the runner seam) |
| POST | `/api/rnd/add_idea` | Add a manual idea to a project's Grass Catchers lane |
| POST | `/api/rnd/promote_inbox` | Promote an `INBOX.md` item into a project's Grass Catchers (copy-by-default; inbox untouched) |
| POST | `/api/rnd/pin_deliverable` | Pin any path (e.g. `anchor_gui.py`) as a deliverable; `{declare:true}` instead pins everything in the folder's `Anchor.md` marker block |
| POST | `/api/rnd/run_deliverable` | Run a declared/pinned deliverable per its type contract (doc/script/skill/program) |
| POST | `/api/rnd/cancel_job` | Stop one R&D lane job (tree-kill via `job_runner.cancel`); 404 on unknown id. Used by the project-window console "Stop job" button, scoped to the ATTACHED session |

> **R&D project window (`GET /project/<id>`):** `render_project_window_html` serves the rich "Dashboard A" — a 5-column Kanban (Research|Planning|Build|Deliverables|Grass Catchers) showing the **most-recent session per lane** as the visible card with a **"previous sessions" expander** holding the rest, a multi-session console / interactive terminal drawer, a lifecycle header (priority/notes/blurb/archive/retire/reactivate, all token-aware via `_postJson`), and the linked-tasks strip. Done sessions link to the cached summary (`/summary/<pid>/<lane>/<session_id>`); individual effort docs link to the report viewer (`/report/<pid>/<lane>/<job_id>`). The window JS lives in the `_PROJECT_WINDOW_JS` RAW (single-brace) string — NOT an f-string.

### R&D Control Surface v2 (frozen design + plan in `planning/rnd-v2/`)

The v2 surface makes Anchor a **truthful, useful memory** of each project's trio work. The frozen design lives in `planning/rnd-v2/MASTER-PLAN.md`; the wave-by-wave build plan in `planning/rnd-v2/IMPLEMENTATION-PLAN.md`. Key concepts and their modules:

- **Session model (`sessions.py`).** One trio run = one **session**, not N per-file cards. `list_sessions(folder, pid, lane)` wraps `effort_history` and groups efforts into sessions newest-first: RUN efforts group by `job_id`; DISCOVERED (brownfield) efforts group by common parent directory (`planning/brownfield-discovery/` is one session, `planning/rnd-v1/` another); a `skill`+timestamp-cluster fallback handles flat folders. A `merge_sessions`/`split_session` escape hatch (persisted in a `sessions-overrides.json` sidecar) fixes mis-grouped discovered files. Each session carries `provenance` = `run` | `imported`.
- **Cached, validated summaries (`summarizer.py`).** Clicking a session opens a rendered markdown **summary** (goal · key decisions · files-with-links · findings · errors), not the raw log. Pipeline: extraction-seed from the member docs → **generate twice** through the runner → a **deterministic grounding hint-filter** drops claims whose key terms don't appear in the member docs → cache `summary.json` + `summary.md` under `<lane>/summaries/<session_id>/`. **Run-once**: a second view serves the cache; **Regenerate** (`/api/rnd/regenerate_summary`) re-runs and overwrites. All model calls go through the `ANCHOR_RUNNER_CMD` seam, so they are exercised via `tests/fake_claude.py` — **never live `claude` in any test/healthcheck path.**
- **First-class imported history (`rnd_registry.status_line`).** Returns per-lane **counts + provenance** (`{planning: {count, imported, running}}`), NOT the old `import`/`none-yet` masquerade — a lane with sessions never reads "import". "imported" is a per-card chip, not the lane's whole state. A user-editable **project blurb** (`set_blurb`, seeded once from `CLAUDE.md`/`README`/`Anchor.md` via `seed_blurb`) describes what the project is.
- **Folder reconcile (`rnd_registry.reconcile_folder` + `effort_history.adopt_sibling_sessions`).** Because one folder may have N registered ids (live + retired test ids), an **explicit, reviewable** reconcile folds same-folder siblings' real sessions into the active id, then **hard-deletes** the siblings. Two-step: `apply=False` returns a dry-run PLAN (what would fold/delete) without mutating; `apply=True` folds-then-deletes. It folds ALL content lanes (`effort_history.FOLD_LANES` = research/planning/build/deliverables/**grass**) so grass ideas are migrated, not destroyed. Ids on a DIFFERENT folder are never touched.
- **Grass Catchers lane (`grass`).** A 5th lane (`rnd_registry.LANE_DIRS`/`STATUS_LANES`-adjacent) for future ideas, fed three ways: manual add (`effort_history.add_idea`), promote-from-`INBOX.md` (`effort_history.promote_inbox`, copy-by-default — the inbox stays the untouched source of truth), and discovery classification of idea-docs in `brownfield_scan.py`.
- **Deliverable declare/pin (`deliverables.py`).** A real deliverable (e.g. the running `anchor_gui.py`, which is NOT under a `deliverables/` dir) is representable: **pin** any in-folder path as a deliverables-lane effort (`pin_deliverable`, idempotent/content-addressed, traversal-safe), or **declare** them via an `Anchor.md` `## Deliverables` marker block (`declare_deliverables_from_marker`). Running a deliverable enforces a per-type success contract (doc=exists+nonempty; script/skill=exit 0 + result-no-error; program=exit 0 within timeout) with stdin-closed + tree-kill-on-timeout discipline.
- **Interactive terminal substrate (`rnd_terminal.py`).** "New research/plan/build" opens an interactive terminal that already knows the lane's trio skill. The substrate is a **persistent `stream-json` REPL** (one long-lived `claude`/`gemini` job per session, user turns POSTed onto its stdin, assistant output streamed back over **SSE**) — deliberately **NOT a native ConPTY terminal**, which would need a compiled dependency and violate the stdlib-only / no-native-asset rule. The console is the **vendored anchor-term** static asset (xterm.js was deliberately NOT used, for the same stdlib-only/no-native-asset reason; the terminal *feel* is achieved over the REPL). It generalizes — never forks — the gate-adapter stdin mechanism. On process exit it **auto-discovers** files produced under the session output dir (`discover_produced`) and asks the user to **confirm adoption** as a session (`adopt_produced`, recorded as one RUN session keyed by the terminal job_id, reusing the Wave-1 grouping + Wave-2 adopt paths).

### anchor.py — CLI Engine
Mirror of anchor_gui.py's logic but as a command-line tool. Also generates the static `dashboard.html` file. Shares the same markdown format and file paths.

**R&D v2 CLI mirror** (`anchor.py rnd <subcommand>`) — each subcommand resolves a project by id and **delegates to the shared v2 module** (no forked logic):

- `rnd sessions <pid> --lane <lane>` — list a lane's sessions (`sessions.list_sessions`)
- `rnd status <pid>` — per-lane counts+provenance (`rnd_registry.status_line`)
- `rnd reconcile <pid> [--apply]` — folder reconcile; default is a dry-run preview (`rnd_registry.reconcile_folder`)
- `rnd add-idea <pid> "text" [--notes "..."]` — manual Grass Catchers idea (`effort_history.add_idea`)
- `rnd promote-inbox <pid> "inbox item"` — promote an INBOX item to grass (`effort_history.promote_inbox`)
- `rnd pin-deliverable <pid> <path> [--name N] [--type T] [--desc "..."]` — pin a deliverable (`deliverables.pin_deliverable`)
- `rnd set-blurb <pid> "blurb"` — set the project blurb (`rnd_registry.set_blurb`)
- `rnd regenerate-summary <pid> --lane <lane> --session <id>` — force re-cache a session summary (`summarizer.summarize_session(force=True)`, through the runner seam)

There is intentionally **no CLI form** for the live interactive terminal (start/input/SSE), the SSE stream, or the merge/split escape hatch — those are inherently interactive/UI-driven and exposing them as one-shot CLI calls would not be meaningful.

### How to Add a New Feature
1. Add the backend function in **anchor_gui.py** (in the "Change Operations" section)
2. Add the API endpoint in `AnchorHandler.do_POST()`
3. Add UI elements in `generate_html()` — CSS in the `<style>` block, HTML in the view, JS in the `<script>` block
4. Mirror the backend function in **anchor.py** and add the CLI command in `main()`
5. Update this CLAUDE.md

### GUI Views
The dashboard has these views (toggled by `showView()` in JS):
- `view-dashboard` — main view with top tasks, projects, stats
- `view-completed` — completed tasks (can reopen)
- `view-cancelled` — cancelled tasks (can restore)
- `view-saved` — saved-for-later tasks (can restore)
- `view-inbox` — quick capture inbox
- `view-{domain}` — per-domain views (academic, writing, family, commercial, personal)

### Common Pitfalls
- **Browser caching:** The server sends no-cache headers, but if a user reports stale content, tell them Ctrl+Shift+R
- **Port conflict:** If port 8777 misbehaves, restart the service: `nssm restart anchor` (elevated). Do **not** blanket-kill `taskkill /F /IM pythonw.exe` — that also kills the service's server and any unrelated `pythonw` processes on this host. To target one process, find it with `Get-NetTCPConnection -State Listen -LocalPort 8777` and kill that specific PID.
- **Local Filesystem:** Project lives in `C:\dev\Anchor`. No OneDrive, no syncing. Version control via local Git.
- **F-string escaping:** The HTML is generated inside Python f-strings, so all literal `{` and `}` in CSS/JS must be doubled: `{{` and `}}`

## Important Rules
- **anchor_gui.py is the primary interface.** It reads/writes markdown directly via a local API.
- **Single folder.** Everything lives in `C:\dev\Anchor`. No siblings, no syncing.
- **commercial.md is now full detail** — proprietary commercial info (Nexia/Axmra fundraising, drug detail, key relationships) lives directly in `domains/commercial.md`. The old "summary-only" rule no longer applies.
- **Markdown files are the source of truth.** No database, no lock files. Everything is plain text.
- **No external dependencies.** Python stdlib only. Must run on any machine with Python 3.8+.
- **All files must remain accessible** from Cowork, Claude Code, or any CLI tool. No binary formats, no compiled assets.
