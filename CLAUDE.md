# Anchor â€” Productivity System for J.C. Liechty

> **ACTIVE FOLDER NOTICE (as of 2026-05-02):** This folder (`C:\dev\Anchor`) is now the **active** Anchor working folder. All future work should be done here.
> The OneDrive folder `C:\Users\jcl12\OneDrive - The Pennsylvania State University\Anchor PSU` is now a **BACKUP ONLY** â€” do not write to it unless explicitly asked to refresh the backup.
> The Axmra sibling (`C:\Users\jcl12\OneDrive - Axmra\Anchor Axmra`) is unaffected and still pairs with this folder via the sibling discovery logic.

## Quick Start
When the user says "Dashboard", "dashboard", "anchor", or "start":
1. Launch the GUI: Run `python3 anchor_gui.py` (starts a local web server at http://localhost:8777 and opens the browser)
2. Give a brief status summary (date, active tasks, upcoming deadlines, inbox count)
3. The GUI is fully interactive â€” user can check tasks done, add tasks, capture ideas directly in the browser. All changes save to markdown files automatically and are logged.

**IMPORTANT:** `anchor_gui.py` is the preferred way to use the dashboard. It runs as a local web server and writes directly to the markdown files â€” no Cowork sandbox limitations.

## Fallback (if GUI can't launch)
If the browser-based GUI can't be launched, fall back to:
1. Run `python3 anchor.py dashboard` to rebuild dashboard.html
2. Present `dashboard.html` using a computer:// link
3. User gives text commands: "done: [task]", "add: [task]", "capture: [idea]"

## How the System Works
Both `anchor.py` and `anchor_gui.py` automatically discover and sync **both directories** (Anchor PSU and Anchor Axmra). No matter which directory you run from, all tasks, projects, and inbox items from both directories appear in the dashboard.

Changes are written to the correct markdown files in both directories, logged in both log folders, and the dashboard reflects everything.

### Sibling Directory Discovery
The scripts auto-detect whether they're running from PSU or Axmra:
- PSU is identified by having a `domains/` folder and `DASHBOARD.md`
- Axmra is identified by having a `.anchor/` subfolder
- They search for each other as sibling directories under the same parent

### Windows Paths (for reference)
- **PSU:** This folder (mounted as the Cowork workspace)
- **Axmra:** `C:\Users\jcl12\OneDrive - Axmra\Anchor Axmra` (sibling directory)
- This project is local â€” version control via local Git

## CLI Commands (anchor.py)
- **"done: David Leavitt"** â†’ Run: `python3 anchor.py done "David Leavitt"`
- **"cancel: Review paper"** â†’ Run: `python3 anchor.py cancel "Review paper"` (moves to CANCELLED.md)
- **"save: Review paper"** â†’ Run: `python3 anchor.py save "Review paper"` (moves to SAVED_FOR_LATER.md)
- **"restore: Review paper"** â†’ Run: `python3 anchor.py restore "Review paper" --from saved` (or `--from cancelled`)
- **"add task: Review paper"** â†’ Run: `python3 anchor.py add "Review paper" --domain academic --priority 2 --energy high --notes "See email from Dr. Smith"`
- **"capture: Look into MIT"** â†’ Run: `python3 anchor.py capture "Look into MIT" --domain academic`
- **"update"** or **"refresh"** â†’ Run: `python3 anchor.py dashboard` and re-present

## Task Lifecycle
Tasks can be moved through these states:
- **Active** â†’ on the dashboard (DASHBOARD.md / domain files)
- **Done** â†’ checked off in markdown (`[x]`), visible in Completed view
- **Cancelled** â†’ removed from dashboard, stored in CANCELLED.md, reviewable in Cancelled view
- **Saved for Later** â†’ removed from dashboard, stored in SAVED_FOR_LATER.md, reviewable in Saved view
- **Restored** â†’ moved back from Cancelled or Saved for Later to active dashboard

Each task can have an optional **Notes** field for storing emails, links, references, or context.

## Daily Health Check
A self-test script (`anchor_healthcheck.py`) runs every morning at 5:00 AM via Windows Task Scheduler. It verifies file integrity, parses every markdown file, boots the server on test port 8778, exercises every endpoint, walks a synthetic `__healthcheck__` task through every state, then writes `health_reports/YYYY-MM-DD.md`. If anything failed, the dashboard shows a red banner at the top until the next clean run.

- **Install scheduled task:** `powershell -ExecutionPolicy Bypass -File .\register_healthcheck.ps1` (run once)
- **Run on demand:** double-click `Anchor Healthcheck.bat`, or `python anchor_healthcheck.py`
- **Disable:** `Unregister-ScheduledTask -TaskName "Anchor Health Check" -Confirm:$false`
- **Reports:** kept indefinitely in `health_reports/`. See `health_reports/README.md` for the format.

The synthetic `__healthcheck__` task is filtered out of every dashboard view by `gather_all()`, so it never shows up even if a check is mid-run when you refresh.

## File Structure
```
anchor_gui.py           â† Standalone GUI (local web server + browser dashboard)
anchor.py               â† CLI engine (reads/writes markdown, generates HTML)
anchor_healthcheck.py   â† Daily self-test (runs at 5:00 AM via Task Scheduler)
register_healthcheck.ps1 â† One-time setup for the scheduled task
Anchor Healthcheck.bat  â† Manual trigger for the health check (with console output)
launch_anchor.pyw       â† Silent launcher (no terminal window, used by shortcuts)
Anchor Dashboard.bat    â† Double-click to launch (Windows)
pin_anchor_to_taskbar.vbs â† Run once to create a pinnable Desktop shortcut
setup_shortcut.py       â† Alternative shortcut creator (uses pywin32)
dashboard.html          â† Static HTML dashboard (auto-generated by anchor.py)
health_reports/         â† Daily health-check reports (YYYY-MM-DD.md, one per run)
CLAUDE.md               â† This file (project instructions for Cowork / Claude Code)
DASHBOARD.md            â† Daily dashboard with calendar, focus items, priorities
PROJECTS.md             â† Master project list across all domains
INBOX.md                â† Quick capture inbox
CANCELLED.md            â† Cancelled tasks (reviewable archive)
SAVED_FOR_LATER.md      â† Tasks saved for later (reviewable archive)
WEEKLY_REVIEW.md        â† Weekly retrospectives
domains/
  academic.md           â† Research projects, teaching, service
  commercial.md         â† Summary only (details in Anchor Axmra)
  family.md             â† Trusts, travel, personal finance
  writing.md            â† Chronicles of the Dragon-Kept, Artificial Magi
logs/
  YYYY-MM-DD.md         â† Daily activity logs (auto-created)
```

## Architecture (for developers / future sessions)

### anchor_gui.py â€” The Main Application (~1500 lines)
This is a self-contained Python HTTP server that generates the full dashboard HTML on every request. No external dependencies â€” just Python stdlib.

**Key sections (in order):**
1. **Paths & Discovery** (lines 1â€“70): Finds PSU and Axmra directories, sets up all file path constants
2. **Parsing** (~lines 75â€“170): `parse_tasks_from_md()`, `parse_projects_from_md()`, `parse_inbox_from_md()`, `parse_archived_tasks()` â€” read markdown into Python dicts
3. **Data Gathering** (~line 175): `gather_all()` â€” merges data from both directories, deduplicates
4. **Change Operations** (~lines 220â€“620): `log_change()`, `mark_done()`, `mark_undone()`, `add_task()`, `capture_inbox()`, `edit_task()`, `edit_project()`, `cancel_task()`, `save_for_later()`, `restore_task()`
5. **HTML Generation** (~lines 630â€“1400): `generate_html()` â€” one massive function that builds the entire dashboard as a single HTML string with embedded CSS and JS
6. **HTTP Server** (~lines 1400â€“end): `AnchorHandler` class with GET `/` and POST `/api/*` endpoints

**Task markdown format:**
```
- [ ] Task text â€” Priority: 2 â€” energy: med â€” [domain] â€” Due: 2026-04-15 â€” Notes: some reference
```

**Archived task format (CANCELLED.md / SAVED_FOR_LATER.md):**
```
- 2026-04-11: Task text â€” [domain] â€” P2 â€” Notes: some reference
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
| POST | `/api/cancel` | Cancel task â†’ CANCELLED.md |
| POST | `/api/save_for_later` | Save task â†’ SAVED_FOR_LATER.md |
| POST | `/api/restore` | Restore from archive to active |
| POST | `/api/shutdown` | Stop the server |

### anchor.py â€” CLI Engine (~630 lines)
Mirror of anchor_gui.py's logic but as a command-line tool. Also generates the static `dashboard.html` file. Shares the same markdown format and file paths.

### How to Add a New Feature
1. Add the backend function in **anchor_gui.py** (in the "Change Operations" section)
2. Add the API endpoint in `AnchorHandler.do_POST()`
3. Add UI elements in `generate_html()` â€” CSS in the `<style>` block, HTML in the view, JS in the `<script>` block
4. Mirror the backend function in **anchor.py** and add the CLI command in `main()`
5. Update this CLAUDE.md

### GUI Views
The dashboard has these views (toggled by `showView()` in JS):
- `view-dashboard` â€” main view with top tasks, projects, stats
- `view-completed` â€” completed tasks (can reopen)
- `view-cancelled` â€” cancelled tasks (can restore)
- `view-saved` â€” saved-for-later tasks (can restore)
- `view-inbox` â€” quick capture inbox
- `view-{domain}` â€” per-domain views (academic, writing, family, commercial, personal)

### Common Pitfalls
- **Browser caching:** The server sends no-cache headers, but if a user reports stale content, tell them Ctrl+Shift+R
- **Port conflict:** If port 8777 is already in use (old server still running), the new launch will fail silently. Kill old Python processes first: `taskkill /F /IM pythonw.exe`
- **Local Filesystem:** Project lives in C:\dev\Anchor.  
- **F-string escaping:** The HTML is generated inside Python f-strings, so all literal `{` and `}` in CSS/JS must be doubled: `{{` and `}}`

## Important Rules
- **anchor_gui.py is the primary interface.** It reads/writes markdown directly via a local API.
- **Both directories sync automatically.** PSU and Axmra are always kept in sync.
- **Always launch from the PSU folder.** PSU is the primary directory. Axmra is the commercial sibling.
- **commercial.md** is summary only. Proprietary details live in Anchor Axmra.
- **Markdown files are the source of truth.** No database, no lock files. Everything is plain text.
- **No external dependencies.** Python stdlib only. Must run on any machine with Python 3.8+.
- **All files must remain accessible** from Cowork, Claude Code, or any CLI tool. No binary formats, no compiled assets.

