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

If port 8778 is already occupied (e.g. by a stale/orphaned server the non-elevated check can't reap), the self-test automatically falls back to an OS-assigned free port and logs that under "Auto-fixes applied" — it no longer aborts the whole run over a busy test port.

- **Install / re-register scheduled task:** `powershell -ExecutionPolicy Bypass -File .\register_healthcheck.ps1` (run once; safe to re-run)
- **Run on demand:** double-click `Anchor Healthcheck.bat`, or `python anchor_healthcheck.py`
- **Disable:** `Unregister-ScheduledTask -TaskName "Anchor Health Check" -Confirm:$false`
- **Reports:** kept indefinitely in `health_reports/`. See `health_reports/README.md` for the format.

The synthetic `__healthcheck__` task is filtered out of every dashboard view by `gather_all()`, so it never shows up even if a check is mid-run when you refresh.

## File Structure
```
anchor_gui.py           ← Standalone GUI (local web server + browser dashboard)
anchor.py               ← CLI engine (reads/writes markdown, generates HTML)
anchor_healthcheck.py   ← Daily self-test (runs at 5:00 AM via Task Scheduler)
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

### anchor.py — CLI Engine
Mirror of anchor_gui.py's logic but as a command-line tool. Also generates the static `dashboard.html` file. Shares the same markdown format and file paths.

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
