#!/usr/bin/env python3
"""
Anchor GUI — Local web-based dashboard with full read/write access.

Starts a local HTTP server that serves the interactive dashboard and provides
API endpoints so that every click (done, add, capture) writes directly to
the markdown files, logs changes, and refreshes the state.

Usage:
    python3 anchor_gui.py          # Opens dashboard in your default browser
    python3 anchor_gui.py --port 8777   # Use a custom port

Launch from Cowork by typing "Dashboard" — Claude will run this for you.
"""

import json, logging, os, re, sys, threading, traceback, webbrowser
from datetime import datetime, date
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import html as html_lib

# ── Paths ──────────────────────────────────────────────────────────────
# Single-folder layout (was previously dual-folder PSU + Axmra; consolidated 2026-05-02)
ANCHOR_DIR = Path(__file__).parent

DASHBOARD_MD = ANCHOR_DIR / "DASHBOARD.md"
PROJECTS_MD = ANCHOR_DIR / "PROJECTS.md"
INBOX_MD = ANCHOR_DIR / "INBOX.md"
DOMAINS_DIR = ANCHOR_DIR / "domains"
LOGS_DIR = ANCHOR_DIR / "logs"
CANCELLED_MD = ANCHOR_DIR / "CANCELLED.md"
SAVED_FOR_LATER_MD = ANCHOR_DIR / "SAVED_FOR_LATER.md"

# Ensure log dir
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ── Error Logging ─────────────────────────────────────────────────────
ERROR_LOG = LOGS_DIR / "errors.log"
ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(ERROR_LOG),
    level=logging.ERROR,
    format="%(asctime)s — %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Also log INFO to the error log for server lifecycle events
_logger = logging.getLogger("anchor")
_logger.setLevel(logging.INFO)
_fh = logging.FileHandler(str(ERROR_LOG))
_fh.setFormatter(logging.Formatter("%(asctime)s — %(levelname)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_logger.addHandler(_fh)


# ── Parsing ────────────────────────────────────────────────────────────

def parse_tasks_from_md(filepath):
    tasks = []
    if not filepath or not filepath.exists():
        return tasks
    text = filepath.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r'\s*-\s*\[([ xX])\]\s*\*?\*?(.*?)(?:\*?\*?\s*—\s*(.*))?$', line)
        if m:
            done = m.group(1).lower() == 'x'
            raw_text = m.group(2).strip().rstrip('*')
            meta = m.group(3) or ""
            pm = re.search(r'Priority:\s*(\d)', meta) or re.search(r'Priority:\s*(\d)', raw_text)
            priority = int(pm.group(1)) if pm else 2
            em = re.search(r'energy:\s*(\w+)', meta, re.I) or re.search(r'energy:\s*(\w+)', raw_text, re.I)
            energy = em.group(1).lower() if em else "med"
            dm = re.search(r'\[(\w+)\]', meta) or re.search(r'\[(\w+)\]', raw_text)
            domain = dm.group(1).lower() if dm else "personal"
            due_m = re.search(r'Due:\s*([\d/\-\w]+)', meta, re.I)
            due = due_m.group(1) if due_m else ""
            # Extract notes
            notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|\[)|$)', meta, re.I)
            if not notes_m:
                notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
            notes = notes_m.group(1).strip().rstrip(' —') if notes_m else ""
            clean = re.sub(r'\s*—\s*Priority:.*', '', raw_text)
            clean = re.sub(r'\s*—\s*\[.*', '', clean)
            clean = re.sub(r'\s*—\s*energy:.*', '', clean, flags=re.I)
            clean = re.sub(r'\s*—\s*Notes:.*', '', clean, flags=re.I)
            clean = clean.strip(' *')
            tasks.append({"text": clean, "done": done, "priority": priority,
                          "energy": energy, "domain": domain, "due": due, "notes": notes})
    return tasks


def parse_projects_from_md(filepath):
    projects = []
    if not filepath or not filepath.exists():
        return projects
    text = filepath.read_text(encoding="utf-8")
    current = None
    for line in text.splitlines():
        h2 = re.match(r'^##\s+(.+)', line)
        if h2:
            if current:
                projects.append(current)
            current = {"name": h2.group(1).strip(), "domain": "academic", "priority": 2,
                       "status": "active", "effort": "high", "due": "", "next": "",
                       "collabs": "", "notes": ""}
            continue
        if current:
            kv = re.match(r'\s*-\s*\*\*(\w[\w\s]*?):\*\*\s*(.*)', line)
            if kv:
                key = kv.group(1).strip().lower()
                val = kv.group(2).strip()
                if key == "domain":
                    current["domain"] = val.lower().split("+")[0].strip().split("/")[0].strip()
                elif key == "priority":
                    try: current["priority"] = int(val)
                    except: pass
                elif key == "status":
                    current["status"] = val.lower().split("—")[0].strip()
                elif key.startswith("next"):
                    current["next"] = val
                elif key == "collaborators":
                    current["collabs"] = val
                elif key == "notes":
                    current["notes"] = val
                elif key in ("effort", "effort level"):
                    current["effort"] = val.lower()
                elif key in ("deadline", "due"):
                    current["due"] = val
    if current:
        projects.append(current)
    return projects


def parse_inbox_from_md(filepath):
    items = []
    if not filepath or not filepath.exists():
        return items
    text = filepath.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r'\s*-\s*(\d{4}-\d{2}-\d{2}):\s*(.*?)(?:\s*\[(\w+)\])?\s*$', line)
        if m:
            items.append({"date": m.group(1), "text": m.group(2).strip(),
                          "domain": m.group(3) or ""})
    return items


def parse_archived_tasks(filepath):
    """Parse cancelled or saved-for-later tasks from their archive file."""
    items = []
    if not filepath or not filepath.exists():
        return items
    text = filepath.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r'\s*-\s*(\d{4}-\d{2}-\d{2}):\s*(.*?)(?:\s*—\s*\[(\w+)\])?(?:\s*—\s*P(\d))?(?:\s*—\s*Notes:\s*(.*))?$', line)
        if m:
            items.append({
                "date": m.group(1),
                "text": m.group(2).strip(),
                "domain": m.group(3) or "",
                "priority": int(m.group(4)) if m.group(4) else 2,
                "notes": m.group(5).strip() if m.group(5) else "",
            })
    return items


# ── Gather all data ────────────────────────────────────────────────────

def gather_all():
    """Read everything from both directories, return (projects, tasks, inbox)."""
    all_tasks = []
    seen = set()

    def _add(task_list, default_domain=None):
        for t in task_list:
            key = t["text"].lower().strip()[:60]
            if key not in seen:
                seen.add(key)
                if default_domain and t["domain"] == "personal":
                    t["domain"] = default_domain
                all_tasks.append(t)

    if DASHBOARD_MD.exists():
        _add(parse_tasks_from_md(DASHBOARD_MD))
    if DOMAINS_DIR.exists():
        for f in sorted(DOMAINS_DIR.glob("*.md")):
            _add(parse_tasks_from_md(f), default_domain=f.stem)

    projects = []
    seen_p = set()
    if PROJECTS_MD.exists():
        for p in parse_projects_from_md(PROJECTS_MD):
            key = p["name"].lower().strip()[:60]
            if key not in seen_p:
                seen_p.add(key)
                projects.append(p)

    inbox = []
    if INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(INBOX_MD))

    # Filter out synthetic health-check probes so they never appear in any view
    all_tasks = [t for t in all_tasks if "__healthcheck__" not in t["text"].lower()]
    inbox = [i for i in inbox if "__healthcheck__" not in i["text"].lower()]

    return projects, all_tasks, inbox


# ── Health report banner ──────────────────────────────────────────────

HEALTH_REPORTS_DIR = ANCHOR_DIR / "health_reports"


def latest_health_report():
    """Return (date_str, status, path) for the most recent health report, or None.

    status is "OK" or "ISSUES FOUND" (taken from the second non-blank line of the report).
    """
    if not HEALTH_REPORTS_DIR or not HEALTH_REPORTS_DIR.exists():
        return None
    reports = sorted(HEALTH_REPORTS_DIR.glob("*.md"), reverse=True)
    for r in reports:
        if r.name.lower() == "readme.md":
            continue
        try:
            text = r.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r'^Status:\s*(.+)$', text, re.MULTILINE)
        if m:
            status = m.group(1).strip()
            return (r.stem, status, r)
    return None


def _all_md_files():
    files = []
    if DASHBOARD_MD.exists():
        files.append(DASHBOARD_MD)
    if DOMAINS_DIR.exists():
        files.extend(sorted(DOMAINS_DIR.glob("*.md")))
    return files


# ── Change operations ──────────────────────────────────────────────────

def log_change(message):
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    LOGS_DIR.mkdir(exist_ok=True)
    log_file = LOGS_DIR / f"{today}.md"
    if not log_file.exists():
        day_name = datetime.now().strftime("%A")
        log_file.write_text(f"# {today} — {day_name}\n\n## Changes\n", encoding="utf-8")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"- {now} — {message}\n")
    print(f"  Logged: {now} — {message}")


def mark_done(task_text):
    search = task_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = md_file.read_text(encoding="utf-8")
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[ \]', line) and search in line.lower():
                new_lines.append(line.replace("[ ]", "[x]", 1))
                found = True
                changed = True
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    if found:
        log_change(f"Completed: {task_text}")
    return found


def mark_undone(task_text):
    search = task_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = md_file.read_text(encoding="utf-8")
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[[xX]\]', line) and search in line.lower():
                new_lines.append(re.sub(r'\[[xX]\]', '[ ]', line, count=1))
                found = True
                changed = True
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    if found:
        log_change(f"Reopened: {task_text}")
    return found


def add_task(text, domain="academic", priority=2, energy="med", due="", notes=""):
    due_str = f" — Due: {due}" if due else ""
    notes_str = f" — Notes: {notes}" if notes else ""
    line = f"- [ ] {text} — Priority: {priority} — energy: {energy} — [{domain}]{due_str}{notes_str}"

    def _insert(filepath, section_names):
        if not filepath or not filepath.exists():
            return False
        content = filepath.read_text(encoding="utf-8")
        for section in section_names:
            idx = content.find(section)
            if idx >= 0:
                ns = content.find("\n##", idx + len(section))
                if ns < 0:
                    ns = len(content)
                content = content[:ns].rstrip() + "\n" + line + "\n\n" + content[ns:]
                filepath.write_text(content, encoding="utf-8")
                return True
        return False

    _insert(DASHBOARD_MD, ["## Today's Priorities", "## Active Priorities"])
    if DOMAINS_DIR.exists():
        _insert(DOMAINS_DIR / f"{domain}.md", ["## Active Tasks"])

    log_change(f"Added task: {text} [{domain}] P{priority}")


def capture_inbox(text, domain=""):
    today = date.today().isoformat()
    domain_tag = f" [{domain}]" if domain else ""
    line = f"- {today}: {text}{domain_tag}"
    if INBOX_MD.exists():
        content = INBOX_MD.read_text(encoding="utf-8")
        content = content.rstrip() + "\n" + line + "\n"
        INBOX_MD.write_text(content, encoding="utf-8")
    log_change(f"Captured: {text}")


def edit_task(old_text, new_text=None, new_priority=None, new_domain=None, new_energy=None, new_due=None, new_notes=None):
    """Edit a task's properties across all markdown files. Only changes specified fields."""
    search = old_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue

        # Infer domain from filename: domains/family.md → "family"
        file_domain = None
        if md_file.parent == DOMAINS_DIR:
            file_domain = md_file.stem  # e.g. "family", "academic", "writing", "commercial"

        text = md_file.read_text(encoding="utf-8")
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[([ xX])\]', line) and search in line.lower():
                check_m = re.match(r'(\s*-\s*\[)([ xX])(\]\s*)', line)
                if check_m:
                    prefix = check_m.group(1)
                    check_state = check_m.group(2)
                    rest = line[check_m.end():]

                    # Parse existing text (everything before the first " — ")
                    raw_rest = line[check_m.end():]
                    text_end = raw_rest.find(" — ")
                    existing_text = raw_rest[:text_end].strip(' *') if text_end >= 0 else raw_rest.strip(' *')
                    existing_priority = 2
                    existing_energy = "med"
                    existing_due = ""

                    # Domain: prefer file-inferred domain, then tag in line, then "personal"
                    existing_domain = file_domain or "personal"
                    dm = re.search(r'\[(\w+)\]', rest)
                    if dm and not file_domain:
                        existing_domain = dm.group(1).lower()

                    pm = re.search(r'Priority:\s*(\d)', rest)
                    if pm: existing_priority = int(pm.group(1))
                    em = re.search(r'energy:\s*(\w+)', rest, re.I)
                    if em: existing_energy = em.group(1).lower()
                    due_m = re.search(r'Due:\s*([\d/\-\w]+)', rest, re.I)
                    if due_m: existing_due = due_m.group(1)
                    existing_notes = ""
                    notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|\[)|$)', rest, re.I)
                    if not notes_m:
                        notes_m = re.search(r'Notes:\s*(.+?)$', rest, re.I)
                    if notes_m: existing_notes = notes_m.group(1).strip().rstrip(' —')

                    # Apply only specified changes
                    t_text = new_text if new_text is not None else existing_text
                    t_priority = new_priority if new_priority is not None else existing_priority
                    t_energy = new_energy if new_energy is not None else existing_energy
                    t_domain = new_domain if new_domain is not None else existing_domain
                    t_due = new_due if new_due is not None else existing_due
                    t_notes = new_notes if new_notes is not None else existing_notes
                    due_str = f" — Due: {t_due}" if t_due else ""
                    notes_str = f" — Notes: {t_notes}" if t_notes else ""

                    new_line = f"{prefix}{check_state}] {t_text} — Priority: {t_priority} — energy: {t_energy} — [{t_domain}]{due_str}{notes_str}"
                    new_lines.append(new_line)
                    found = True
                    changed = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    if found:
        changes = []
        if new_text and new_text != old_text:
            changes.append(f"renamed to '{new_text}'")
        if new_priority is not None:
            changes.append(f"P{new_priority}")
        if new_domain:
            changes.append(f"[{new_domain}]")
        if new_due is not None:
            changes.append(f"due {new_due}" if new_due else "due removed")
        log_change(f"Edited task '{old_text}': {', '.join(changes)}")
    return found


def edit_project(old_name, new_name=None, new_priority=None, new_domain=None,
                 new_status=None, new_effort=None, new_due=None, new_next=None):
    """Edit a project's properties in PROJECTS.md files."""
    search = old_name.lower().strip()
    found = False

    for proj_file in [PROJECTS_MD]:
        if not proj_file or not proj_file.exists():
            continue
        text = proj_file.read_text(encoding="utf-8")
        lines = text.splitlines()
        new_lines = []
        in_project = False
        i = 0
        while i < len(lines):
            line = lines[i]
            h2 = re.match(r'^##\s+(.+)', line)
            if h2 and search in h2.group(1).lower():
                in_project = True
                found = True
                # Replace name if needed
                if new_name:
                    new_lines.append(f"## {new_name}")
                else:
                    new_lines.append(line)
                i += 1
                # Process key-value lines within this project section
                while i < len(lines):
                    line = lines[i]
                    # Stop at next project heading
                    if re.match(r'^##\s+', line):
                        in_project = False
                        break
                    kv = re.match(r'(\s*-\s*\*\*)(\w[\w\s]*?)(:\*\*\s*)(.*)', line)
                    if kv:
                        key = kv.group(2).strip().lower()
                        indent = kv.group(1)
                        colon = kv.group(3)
                        if key == "priority" and new_priority is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_priority}")
                        elif key == "domain" and new_domain:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_domain}")
                        elif key == "status" and new_status:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_status}")
                        elif key in ("effort", "effort level") and new_effort:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_effort}")
                        elif key in ("deadline", "due") and new_due is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_due}")
                        elif key.startswith("next") and new_next is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_next}")
                        else:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)
                    i += 1
                continue
            else:
                if h2:
                    in_project = False
                new_lines.append(line)
            i += 1
        proj_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    if found:
        changes = []
        if new_name and new_name != old_name:
            changes.append(f"renamed to '{new_name}'")
        if new_priority is not None:
            changes.append(f"P{new_priority}")
        if new_domain:
            changes.append(f"[{new_domain}]")
        if new_status:
            changes.append(f"status: {new_status}")
        if new_next is not None:
            changes.append(f"next: {new_next}")
        log_change(f"Edited project '{old_name}': {', '.join(changes)}")
    return found


def _remove_task_from_files(task_text):
    """Remove a task line from all markdown files. Returns the task dict if found."""
    search = task_text.lower().strip()
    found_task = None
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue
        text = md_file.read_text(encoding="utf-8")
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[([ xX])\]', line) and search in line.lower():
                # Parse the task before removing
                if not found_task:
                    tm = re.match(r'\s*-\s*\[([ xX])\]\s*\*?\*?(.*?)(?:\*?\*?\s*—\s*(.*))?$', line)
                    if tm:
                        meta = tm.group(3) or ""
                        dm = re.search(r'\[(\w+)\]', meta)
                        pm = re.search(r'Priority:\s*(\d)', meta)
                        notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|\[)|$)', meta, re.I)
                        if not notes_m:
                            notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
                        found_task = {
                            "text": task_text,
                            "domain": dm.group(1).lower() if dm else "",
                            "priority": int(pm.group(1)) if pm else 2,
                            "notes": notes_m.group(1).strip().rstrip(' —') if notes_m else "",
                        }
                changed = True
                continue  # skip this line (remove it)
            new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return found_task


def _append_to_archive(filepath, task_dict):
    """Append a task entry to an archive file (CANCELLED.md or SAVED_FOR_LATER.md)."""
    if not filepath:
        return
    today = date.today().isoformat()
    domain_str = f" — [{task_dict.get('domain', '')}]" if task_dict.get('domain') else ""
    priority_str = f" — P{task_dict.get('priority', 2)}"
    notes_str = f" — Notes: {task_dict['notes']}" if task_dict.get('notes') else ""
    line = f"- {today}: {task_dict['text']}{domain_str}{priority_str}{notes_str}"

    if not filepath.exists():
        filepath.write_text(f"# {filepath.stem.replace('_', ' ').title()}\n\n", encoding="utf-8")
    content = filepath.read_text(encoding="utf-8")
    content = content.rstrip() + "\n" + line + "\n"
    filepath.write_text(content, encoding="utf-8")


def cancel_task(task_text):
    """Cancel a task: remove from active lists, add to CANCELLED.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(CANCELLED_MD, task)
        log_change(f"Cancelled: {task_text}")
        return True
    return False


def save_for_later(task_text):
    """Save a task for later: remove from active lists, add to SAVED_FOR_LATER.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(SAVED_FOR_LATER_MD, task)
        log_change(f"Saved for later: {task_text}")
        return True
    return False


def restore_task(task_text, from_archive="saved"):
    """Restore a task from an archive back to the active dashboard."""
    archive_file = SAVED_FOR_LATER_MD if from_archive == "saved" else CANCELLED_MD
    if not archive_file or not archive_file.exists():
        return False
    text = archive_file.read_text(encoding="utf-8")
    search = task_text.lower().strip()
    found = None
    new_lines = []
    for line in text.splitlines():
        if search in line.lower() and not found:
            # Parse the archived task
            m = re.match(r'\s*-\s*\d{4}-\d{2}-\d{2}:\s*(.*?)(?:\s*—\s*\[(\w+)\])?(?:\s*—\s*P(\d))?(?:\s*—\s*Notes:\s*(.*))?$', line)
            if m:
                found = {
                    "text": m.group(1).strip(),
                    "domain": m.group(2) or "personal",
                    "priority": int(m.group(3)) if m.group(3) else 2,
                    "notes": m.group(4).strip() if m.group(4) else "",
                }
            continue  # remove from archive
        new_lines.append(line)
    if found:
        archive_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        add_task(found["text"], found["domain"], found["priority"], "med", "", found["notes"])
        log_change(f"Restored from {from_archive}: {task_text}")
        return True
    return False


# ── HTML Dashboard Generation ─────────────────────────────────────────

def generate_html(projects, tasks, inbox):
    """Generate a full standalone HTML dashboard matching the original Anchor style."""
    today_str = datetime.now().strftime("%A, %B %d, %Y")
    active = [t for t in tasks if not t["done"]]
    done_tasks = [t for t in tasks if t["done"]]

    # ── Health banner ──
    # If the most recent health report flagged issues, show a banner at the top.
    health_banner_html = ""
    hr = latest_health_report()
    if hr is not None:
        report_date, status, _ = hr
        if "ISSUE" in status.upper() or "FAIL" in status.upper() or "ERROR" in status.upper():
            health_banner_html = (
                f'<div style="background:#3b1f1f;border:1px solid #9b3a3a;color:#ffb3b3;'
                f'padding:10px 14px;border-radius:6px;margin:0 0 10px 0;font-size:13px;">'
                f'<strong style="color:#ff7a7a">&#9888; Health check found issues</strong>'
                f' on {html_lib.escape(report_date)}. '
                f'See <code style="background:#2a1414;padding:1px 5px;border-radius:3px">'
                f'health_reports/{html_lib.escape(report_date)}.md</code> for details.'
                f'</div>'
            )

    # Domain sort order: commercial first, then academic, family, writing, personal
    domain_sort_order = {"commercial": 0, "academic": 1, "family": 2, "writing": 3, "personal": 4}
    # Energy sort order: high-energy tasks first, then med, then low
    energy_sort_order = {"high": 0, "med": 1, "medium": 1, "low": 2}
    today_iso = date.today().isoformat()

    # Top Tasks = P1 tasks + anything due today (any priority)
    # Other Tasks = everything P2+ (that isn't due today)
    # Within Top Tasks: due today first, then by domain order (commercial → academic → family → writing → personal)
    p1 = [t for t in active if t["priority"] == 1]
    due_today_non_p1 = [t for t in active if t["priority"] != 1 and t.get("due") and t["due"] <= today_iso]
    p1_sorted = sorted(p1, key=lambda t: (
        0 if t.get("due") and t["due"] <= today_iso else 1,  # due today first
        domain_sort_order.get(t["domain"], 9),
        t["text"]
    ))

    seen_top = set()
    top_tasks = []
    for t in due_today_non_p1 + p1_sorted:
        key = t["text"].lower()[:60]
        if key not in seen_top:
            seen_top.add(key)
            top_tasks.append(t)
    top_done = len([t for t in top_tasks if t["done"]])
    top_task_texts = set(t["text"].lower()[:60] for t in top_tasks)

    # P1 and P2+ projects
    p1_projects = sorted([p for p in projects if p["priority"] == 1 and p["status"] == "active"],
                         key=lambda p: (0 if p.get("due") else 1, p.get("due", ""), p["name"]))
    p2_projects = sorted([p for p in projects if p["priority"] >= 2 and p["status"] == "active"],
                         key=lambda p: (p["priority"], p["name"]))

    # P2+ tasks not already in Top Tasks (other tasks).
    # Sort: by domain (commercial → academic → family → writing → personal),
    # then by energy (high → med → low), then by priority number, then text.
    other_tasks = sorted(
        [t for t in active if t["priority"] >= 2 and t["text"].lower()[:60] not in top_task_texts],
        key=lambda t: (
            domain_sort_order.get(t["domain"], 9),
            energy_sort_order.get(t.get("energy", "med").lower(), 1),
            t["priority"],
            t["text"],
        ),
    )

    # Group by domain for sidebar
    domain_counts = {}
    for t in active:
        domain_counts[t["domain"]] = domain_counts.get(t["domain"], 0) + 1

    def esc(s):
        return html_lib.escape(str(s)).replace("'", "&#39;").replace('"', "&quot;")

    def linkify_notes(s):
        """Escape HTML, then convert URLs into clickable <a> tags."""
        escaped = html_lib.escape(str(s))
        return re.sub(
            r'(https?://[^\s<>&\'"]+)',
            r'<a href="\1" target="_blank" rel="noopener" onclick="event.stopPropagation()">\1</a>',
            escaped
        )

    def notes_popover(notes_text):
        """Build a hoverable popover element for task notes."""
        if not notes_text:
            return ""
        linked = linkify_notes(notes_text)
        return f'''<span class="notes-wrapper">
            <span class="notes-indicator">&#128203;</span>
            <div class="notes-popover">{linked}</div>
        </span>'''

    def js_safe(s):
        """Escape a string for safe use inside JS onclick='func(\"...\")' attributes."""
        import base64
        return base64.b64encode(s.encode('utf-8')).decode('ascii')

    def task_data_b64(t):
        """Base64-encode a task's full data dict for safe embedding in HTML attributes."""
        import base64
        d = {"text": t["text"], "priority": t["priority"], "domain": t["domain"],
             "energy": t.get("energy","med"), "due": t.get("due",""), "notes": t.get("notes","")}
        return base64.b64encode(json.dumps(d).encode('utf-8')).decode('ascii')

    def project_data_b64(p):
        """Base64-encode a project's full data dict for safe embedding in HTML attributes."""
        import base64
        d = {"name": p["name"], "priority": p["priority"], "domain": p["domain"],
             "status": p.get("status","active"), "effort": p.get("effort","high"),
             "due": p.get("due",""), "next": p.get("next","")}
        return base64.b64encode(json.dumps(d).encode('utf-8')).decode('ascii')

    # Domain labels and colors
    domain_labels = {
        "academic": "Academic Research", "writing": "Writing Projects",
        "family": "Family & Personal", "commercial": "Commercial",
        "personal": "Systems & Meta"
    }
    domain_css_colors = {
        "academic": "var(--academic)", "writing": "var(--writing)",
        "family": "var(--family)", "commercial": "var(--commercial)",
        "personal": "var(--personal)"
    }

    # Build top task rows
    def top_task_row(t):
        done_class = "done" if t["done"] else ""
        btn_class = "checked" if t["done"] else ""
        action = "markUndone" if t["done"] else "markDone"
        btn_label = "&#10003; Done" if t["done"] else "Done"
        effort = t.get("energy", "med")
        b64 = js_safe(t["text"])
        tb64 = task_data_b64(t)
        if t["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteTask(\'{b64}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteTask(\'{b64}\')">&#8593; P1</button>'
        notes_html = notes_popover(t.get("notes", ""))
        return f'''<div class="top-task-row {done_class}">
            <button class="top-task-done-btn {btn_class}" onclick="{action}('{b64}')">{btn_label}</button>
            <span class="top-task-text">{esc(t["text"])}{notes_html}</span>
            {f'<span class="top-task-due">{esc(t["due"])}</span>' if t.get("due") else ""}
            <span class="top-task-effort {effort}">{effort}</span>
            <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            {tier_btn}
            <button class="edit-btn" onclick="openEditTask(decTask('{tb64}'))">&#9998;</button>
            <button class="cancel-btn" onclick="cancelTask('{b64}')" title="Cancel task">&#10007;</button>
            <button class="save-later-btn" onclick="saveForLater('{b64}')" title="Save for later">&#128337;</button>
        </div>'''

    # Build project cards
    def project_card(p):
        effort = p.get("effort", "high")
        pb64 = project_data_b64(p)
        b64p = js_safe(p["name"])
        if p["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteProject(\'{b64p}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteProject(\'{b64p}\')">&#8593; P1</button>'
        return f'''<div class="card priority-{p["priority"]}{' has-deadline' if p.get('due') else ''}">
            <div class="card-main">
                <div class="card-top">
                    <h3>{esc(p["name"])}</h3>
                    {f'<span class="due-badge">{esc(p["due"])}</span>' if p.get("due") else ""}
                    <span class="effort-badge {effort}">{effort}</span>
                    <span class="domain-tag {p["domain"]}">{esc(p["domain"])}</span>
                    {tier_btn}
                    <button class="edit-btn" onclick="openEditProject(decProj('{pb64}'))">&#9998;</button>
                </div>
                {f'<div class="next-text">Next: {esc(p["next"])}</div>' if p.get("next") else ""}
            </div>
        </div>'''

    # Build task items (for Other Tasks and domain views).
    # Presentation mirrors top_task_row() so P2 tasks look the same as P1 tasks —
    # flat row with a Done button instead of a boxy checkbox card.
    def task_item(t):
        done_class = "done" if t["done"] else ""
        btn_class = "checked" if t["done"] else ""
        action = "markUndone" if t["done"] else "markDone"
        btn_label = "&#10003; Done" if t["done"] else "Done"
        effort = t.get("energy", "med")
        b64 = js_safe(t["text"])
        tb64 = task_data_b64(t)
        if t["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteTask(\'{b64}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteTask(\'{b64}\')">&#8593; P1</button>'
        notes_html = notes_popover(t.get("notes", ""))
        return f'''<div class="top-task-row p2-task-row {done_class}">
            <button class="top-task-done-btn {btn_class}" onclick="{action}('{b64}')">{btn_label}</button>
            <span class="top-task-text">{esc(t["text"])}{notes_html}</span>
            {f'<span class="top-task-due">{esc(t["due"])}</span>' if t.get("due") else ""}
            <span class="top-task-effort {effort}">{effort}</span>
            <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            {tier_btn}
            <button class="edit-btn" onclick="openEditTask(decTask('{tb64}'))">&#9998;</button>
            <button class="cancel-btn" onclick="cancelTask('{b64}')" title="Cancel task">&#10007;</button>
            <button class="save-later-btn" onclick="saveForLater('{b64}')" title="Save for later">&#128337;</button>
        </div>'''

    # Build sidebar nav items
    domain_order = ["academic", "writing", "family", "commercial", "personal"]
    nav_items = ""
    for d in domain_order:
        if d in domain_counts or any(p["domain"] == d for p in projects):
            count = domain_counts.get(d, 0)
            nav_items += f'''<div class="nav-item" data-view="{d}" onclick="showView('{d}')">
                <span class="dot" style="background:{domain_css_colors.get(d,'var(--text-dim)')}"></span>
                {domain_labels.get(d, d.title())}
                <span class="count">{count}</span>
            </div>'''

    # Build domain views — same structure as the main dashboard
    domain_views = ""
    for d in domain_order:
        d_projects = [p for p in projects if p["domain"] == d]
        d_tasks = [t for t in tasks if t["domain"] == d]
        d_active = [t for t in d_tasks if not t["done"]]
        d_done = [t for t in d_tasks if t["done"]]
        if not d_projects and not d_tasks:
            continue

        # Same logic as main dashboard: Top Tasks = P1 + due soon
        d_p1 = [t for t in d_active if t["priority"] == 1]
        d_due_soon_non_p1 = [t for t in d_active if t["priority"] != 1 and t.get("due") and t["due"] <= today_iso]
        d_p1_sorted = sorted(d_p1, key=lambda t: (
            0 if t.get("due") and t["due"] <= today_iso else 1,
            t["text"]
        ))
        d_seen_top = set()
        d_top_tasks = []
        for t in d_due_soon_non_p1 + d_p1_sorted:
            key = t["text"].lower()[:60]
            if key not in d_seen_top:
                d_seen_top.add(key)
                d_top_tasks.append(t)
        d_top_done = len([t for t in d_top_tasks if t["done"]])
        d_top_texts = set(t["text"].lower()[:60] for t in d_top_tasks)

        # P1 and P2+ projects for this domain
        d_p1_projects = sorted([p for p in d_projects if p["priority"] == 1 and p["status"] == "active"],
                               key=lambda p: (0 if p.get("due") else 1, p.get("due", ""), p["name"]))
        d_p2_projects = sorted([p for p in d_projects if p["priority"] >= 2 and p["status"] == "active"],
                               key=lambda p: (p["priority"], p["name"]))

        # P2+ tasks not already in top tasks.
        # Sort: by energy (high → med → low), then by priority number, then text.
        # (Domain is constant here since we're inside a single-domain view.)
        d_other_tasks = sorted(
            [t for t in d_active if t["priority"] >= 2 and t["text"].lower()[:60] not in d_top_texts],
            key=lambda t: (
                energy_sort_order.get(t.get("energy", "med").lower(), 1),
                t["priority"],
                t["text"],
            ),
        )

        # Stats for this domain
        d_active_projects = len([p for p in d_projects if p.get("status") == "active"])

        # Build the top tasks rows
        d_top_rows = "".join(top_task_row(t) for t in d_top_tasks)
        if not d_top_tasks:
            d_top_rows = '<div class="empty-msg">No priority or time-sensitive tasks in this domain.</div>'

        # Build completed items for this domain
        d_completed_items = ""
        for t in reversed(d_done):
            b64c = js_safe(t["text"])
            notes_html_c = notes_popover(t.get("notes", ""))
            d_completed_items += f'''<div class="task-item completed">
                <div class="task-check checked" onclick="markUndone('{b64c}')"></div>
                <div class="task-text">{esc(t["text"])}{notes_html_c}</div>
                <div class="task-meta">
                    {f'<span class="task-energy">{t["energy"]}</span>' if t.get("energy") else ""}
                    <span class="task-priority p{t["priority"]}">P{t["priority"]}</span>
                </div>
            </div>'''

        domain_views += f'''
        <div class="view" id="view-{d}" style="display:none">
            <div class="page-header">
                <div style="display:flex;align-items:center;gap:8px">
                    <h2>{domain_labels.get(d, d.title())}</h2>
                    <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Dashboard</button>
                </div>
                <div class="date">{today_str}</div>
            </div>

            <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
                <button class="btn btn-sm" onclick="toggleAddTask_{d}()">+ Add Task</button>
            </div>
            <div class="add-task-bar" id="addTaskBar_{d}" style="display:none;flex-wrap:wrap">
                <input type="text" id="newTask_{d}" placeholder="What needs to be done?" onkeypress="if(event.key==='Enter')addTaskDomain('{d}')" style="min-width:200px" />
                <select id="newPriority_{d}">
                    <option value="1">P1</option>
                    <option value="2" selected>P2</option>
                    <option value="3">P3</option>
                </select>
                <div class="date-picker-wrap">
                  <input type="date" id="newDue_{d}" title="Due date (optional)" />
                  <button type="button" class="cal-toggle" onclick="toggleCalendar('newDue_{d}', this)" title="Open calendar">&#128197;</button>
                  <div class="cal-popup" id="cal_newDue_{d}"></div>
                </div>
                <button class="btn btn-sm" onclick="addTaskDomain('{d}')">Add</button>
                <input type="text" id="newNotes_{d}" placeholder="Notes — email, link, reference (optional)" style="min-width:200px;flex:1;margin-top:4px" />
            </div>

            <div class="top-tasks-box">
                <div class="top-header">
                    <h3>Top Tasks</h3>
                    <span class="top-progress">{d_top_done} / {len(d_top_tasks)} done</span>
                </div>
                {d_top_rows}
            </div>

            {f'<div class="section-header"><h3>Priority 1 Projects</h3></div><div class="card-grid">{"".join(project_card(p) for p in d_p1_projects)}</div>' if d_p1_projects else ""}

            <div class="stats-row">
                <div class="stat-card"><div class="num">{d_active_projects}</div><div class="label">Active Projects</div></div>
                <div class="stat-card"><div class="num">{len(d_active)}</div><div class="label">Open Tasks</div></div>
                <div class="stat-card"><div class="num">{len(d_done)}</div><div class="label">Completed</div></div>
            </div>

            {f'<div class="section-header"><h3>Other Tasks</h3></div><div class="task-list">{"".join(task_item(t) for t in d_other_tasks)}</div>' if d_other_tasks else ""}

            {f'<div class="section-header"><h3>Priority 2+ Projects</h3></div><div class="card-grid">{"".join(project_card(p) for p in d_p2_projects)}</div>' if d_p2_projects else ""}

            {f'<div class="section-header" style="margin-top:24px"><h3>Completed ({len(d_done)})</h3></div><div class="task-list">{d_completed_items}</div>' if d_done else ""}
        </div>'''

    # Build completed view
    completed_items = ""
    for t in reversed(done_tasks):  # most recent first
        b64c = js_safe(t["text"])
        notes_html = notes_popover(t.get("notes", ""))
        completed_items += f'''<div class="task-item completed">
            <div class="task-check checked" onclick="markUndone('{b64c}')"></div>
            <div class="task-text">{esc(t["text"])}{notes_html}</div>
            <div class="task-meta">
                {f'<span class="task-energy">{t["energy"]}</span>' if t.get("energy") else ""}
                <span class="task-priority p{t["priority"]}">P{t["priority"]}</span>
                <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            </div>
        </div>'''
    if not done_tasks:
        completed_items = '<div class="empty-msg">No completed tasks yet. Check off items from the dashboard to see them here.</div>'

    # Build cancelled view
    cancelled_tasks = parse_archived_tasks(CANCELLED_MD)
    cancelled_items = ""
    for ct in reversed(cancelled_tasks):
        b64r = js_safe(ct["text"])
        notes_line = f'<div class="archived-notes">Notes: {esc(ct["notes"])}</div>' if ct.get("notes") else ""
        cancelled_items += f'''<div class="task-item archived-task">
            <div style="flex:1">
                <div class="task-text">{esc(ct["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Cancelled {esc(ct["date"])}{(' &bull; ' + esc(ct["domain"])) if ct.get("domain") else ""} &bull; P{ct.get("priority",2)}</div>
                {notes_line}
            </div>
            <button class="btn btn-sm btn-outline" onclick="restoreTask('{b64r}','cancelled')" style="font-size:11px">&#8634; Restore</button>
        </div>'''
    if not cancelled_tasks:
        cancelled_items = '<div class="empty-msg">No cancelled tasks.</div>'

    # Build saved-for-later view
    saved_tasks = parse_archived_tasks(SAVED_FOR_LATER_MD)
    saved_items = ""
    for st in reversed(saved_tasks):
        b64r = js_safe(st["text"])
        notes_line = f'<div class="archived-notes">Notes: {esc(st["notes"])}</div>' if st.get("notes") else ""
        saved_items += f'''<div class="task-item archived-task">
            <div style="flex:1">
                <div class="task-text">{esc(st["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Saved {esc(st["date"])}{(' &bull; ' + esc(st["domain"])) if st.get("domain") else ""} &bull; P{st.get("priority",2)}</div>
                {notes_line}
            </div>
            <button class="btn btn-sm btn-outline" onclick="restoreTask('{b64r}','saved')" style="font-size:11px">&#8634; Restore</button>
        </div>'''
    if not saved_tasks:
        saved_items = '<div class="empty-msg">No saved-for-later tasks.</div>'

    # Inbox items
    inbox_items = ""
    for item in inbox:
        inbox_items += f'''<div class="task-item">
            <div style="flex:1">
                <div class="task-text">{esc(item["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">{esc(item["date"])}{(' &bull; ' + esc(item["domain"])) if item.get("domain") else ""}</div>
            </div>
        </div>'''
    if not inbox:
        inbox_items = '<div class="empty-msg">Inbox empty. Nice work.</div>'

    # Pre-build balance widget rows (avoid nested f-string issues)
    max_count = max(domain_counts.values()) if domain_counts else 1
    balance_rows = ""
    for d in domain_order:
        if d in domain_counts:
            pct = min(100, domain_counts[d] * 100 // max(max_count, 1))
            color = domain_css_colors.get(d, 'var(--text-dim)')
            balance_rows += f'''<div class="balance-row">
                <span class="label">{d.title()[:8]}</span>
                <div class="balance-bar"><div class="fill" style="width:{pct}%;background:{color}"></div></div>
                <span>{domain_counts[d]}</span>
            </div>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anchor Dashboard — J.C. Liechty</title>
<link rel="icon" href="/favicon.ico" type="image/x-icon">
<style>
:root {{
    --bg: #0f1117; --surface: #1a1d27; --surface2: #232733; --border: #2e3340;
    --text: #e2e4e9; --text-dim: #8b8f9a; --accent: #6c9cfc;
    --academic: #6c9cfc; --writing: #c084fc; --family: #4ade80;
    --commercial: #fb923c; --personal: #67e8f9;
    --danger: #f87171; --warning: #fbbf24; --success: #4ade80;
    color-scheme: dark;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; min-height: 100vh; }}
.app {{ display: flex; min-height: 100vh; }}

/* Sidebar */
.sidebar {{
    width: 260px; background: var(--surface); border-right: 1px solid var(--border);
    padding: 20px 0; flex-shrink: 0; display: flex; flex-direction: column;
    position: fixed; top: 0; left: 0; bottom: 0; overflow-y: auto;
}}
.sidebar h1 {{ font-size: 20px; padding: 0 20px 4px; font-weight: 700; }}
.sidebar h1 span {{ color: var(--accent); }}
.sidebar .subtitle {{ font-size: 11px; color: var(--text-dim); padding: 0 20px 20px; }}
.nav-section {{ margin-top: 16px; }}
.nav-section h3 {{ font-size: 10px; text-transform: uppercase; letter-spacing: 1.2px; color: var(--text-dim); padding: 0 20px 6px; }}
.nav-item {{
    padding: 8px 20px; cursor: pointer; font-size: 13px; display: flex; align-items: center;
    gap: 10px; transition: background 0.15s; border-left: 3px solid transparent;
}}
.nav-item:hover {{ background: var(--surface2); }}
.nav-item.active {{ background: var(--surface2); border-left-color: var(--accent); }}
.nav-item .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
.nav-item .count {{ margin-left: auto; background: var(--surface2); padding: 1px 7px; border-radius: 10px; font-size: 11px; color: var(--text-dim); }}

/* Balance widget */
.balance-widget {{
    margin: auto 16px 16px; padding: 14px; background: var(--surface2);
    border-radius: 10px; border: 1px solid var(--border);
}}
.balance-widget h4 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); margin-bottom: 10px; }}
.balance-bars {{ display: flex; flex-direction: column; gap: 6px; }}
.balance-row {{ display: flex; align-items: center; gap: 8px; font-size: 11px; }}
.balance-row .label {{ width: 60px; color: var(--text-dim); }}
.balance-bar {{ flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }}
.balance-bar .fill {{ height: 100%; border-radius: 3px; transition: width 0.5s ease; }}

/* Main content */
.main {{ margin-left: 260px; flex: 1; padding: 28px 32px; max-width: 1100px; }}
.page-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }}
.page-header h2 {{ font-size: 22px; font-weight: 600; }}
.page-header .date {{ color: var(--text-dim); font-size: 13px; }}

/* Cards */
.card-grid {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 24px; }}
.card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; transition: border-color 0.2s; display: flex; align-items: center; gap: 12px;
}}
.card:hover {{ border-color: #3e4455; }}
.card.priority-1 {{ border-left: 3px solid var(--danger); }}
.card.priority-2 {{ border-left: 3px solid var(--warning); }}
.card.priority-3 {{ border-left: 3px solid var(--accent); }}
.card.has-deadline {{ background: linear-gradient(90deg, rgba(248,113,113,0.06), transparent 40%); }}
.card-main {{ flex: 1; min-width: 0; }}
.card-top {{ display: flex; align-items: center; gap: 8px; }}
.card h3 {{ font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.due-badge {{ font-size: 10px; background: rgba(248,113,113,0.2); color: var(--danger); padding: 1px 7px; border-radius: 3px; font-weight: 600; white-space: nowrap; }}
.effort-badge {{ font-size: 9px; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }}
.effort-badge.low {{ background: rgba(74,222,128,0.15); color: var(--success); }}
.effort-badge.med {{ background: rgba(251,191,36,0.12); color: var(--warning); }}
.effort-badge.high {{ background: rgba(192,132,252,0.12); color: var(--writing); }}
.next-text {{ font-size: 11.5px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }}
.domain-tag {{ font-size: 9px; text-transform: uppercase; letter-spacing: 0.8px; padding: 2px 7px; border-radius: 4px; white-space: nowrap; }}
.domain-tag.academic {{ background: rgba(108,156,252,0.15); color: var(--academic); }}
.domain-tag.writing {{ background: rgba(192,132,252,0.15); color: var(--writing); }}
.domain-tag.family {{ background: rgba(74,222,128,0.15); color: var(--family); }}
.domain-tag.commercial {{ background: rgba(251,146,60,0.15); color: var(--commercial); }}
.domain-tag.personal {{ background: rgba(103,232,249,0.15); color: var(--personal); }}

.card-grid.expanded .card {{ flex-direction: column; align-items: stretch; padding: 14px; }}
.card-grid.expanded .card-main {{ width: 100%; }}
.card-grid.expanded .card h3 {{ white-space: normal; }}
.card-grid.expanded .next-text {{ white-space: normal; }}

/* Tasks */
.task-list {{ margin-bottom: 24px; }}
.section-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }}
.section-header h3 {{ font-size: 15px; font-weight: 600; }}
.task-item {{
    display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px; transition: all 0.15s;
}}
.task-item:hover {{ border-color: #3e4455; }}
.task-item.completed {{ opacity: 0.5; }}
.task-item.completed .task-text {{ text-decoration: line-through; }}
.task-check {{
    width: 18px; height: 18px; border: 2px solid var(--border); border-radius: 5px;
    cursor: pointer; flex-shrink: 0; margin-top: 1px; display: flex; align-items: center;
    justify-content: center; transition: all 0.15s;
}}
.task-check:hover {{ border-color: var(--accent); }}
.task-check.checked {{ background: var(--accent); border-color: var(--accent); }}
.task-check.checked::after {{ content: '\\2713'; color: white; font-size: 11px; font-weight: 700; }}
.task-text {{ font-size: 13px; flex: 1; }}
.task-meta {{ display: flex; gap: 8px; align-items: center; flex-shrink: 0; }}
.task-priority {{ font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }}
.task-priority.p1 {{ background: rgba(248,113,113,0.15); color: var(--danger); }}
.task-priority.p2 {{ background: rgba(251,191,36,0.15); color: var(--warning); }}
.task-priority.p3 {{ background: rgba(108,156,252,0.15); color: var(--accent); }}
.task-energy {{ font-size: 10px; color: var(--text-dim); }}

/* Top Tasks */
.top-tasks-box {{
    background: var(--surface); border: 1px solid rgba(108,156,252,0.3);
    border-radius: 12px; padding: 16px 18px; margin-bottom: 20px;
}}
.top-tasks-box .top-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }}
.top-tasks-box h3 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--accent); }}
.top-tasks-box .top-progress {{ font-size: 11px; color: var(--text-dim); }}
.top-task-row {{ display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border); transition: opacity 0.3s; }}
.top-task-row:last-child {{ border-bottom: none; }}
.top-task-row.done {{ opacity: 0.4; }}
.top-task-row.done .top-task-text {{ text-decoration: line-through; }}
.top-task-done-btn {{
    padding: 4px 12px; font-size: 11px; font-weight: 600; border-radius: 5px;
    cursor: pointer; flex-shrink: 0; transition: all 0.15s;
    border: 1px solid var(--border); background: var(--surface2); color: var(--text-dim);
}}
.top-task-done-btn:hover {{ background: var(--success); color: #000; border-color: var(--success); }}
.top-task-done-btn.checked {{ background: var(--success); color: #000; border-color: var(--success); }}
.top-task-text {{ font-size: 13px; flex: 1; font-weight: 500; position: relative; }}
.top-task-due {{ font-size: 10px; background: rgba(248,113,113,0.2); color: var(--danger); padding: 2px 8px; border-radius: 4px; font-weight: 600; white-space: nowrap; }}
.top-task-effort {{ font-size: 9px; padding: 2px 6px; border-radius: 3px; white-space: nowrap; }}
.top-task-effort.low {{ background: rgba(74,222,128,0.15); color: var(--success); }}
.top-task-effort.med {{ background: rgba(251,191,36,0.12); color: var(--warning); }}
.top-task-effort.high {{ background: rgba(192,132,252,0.12); color: var(--writing); }}

/* Stats row */
.stats-row {{ display: flex; gap: 10px; margin-bottom: 20px; }}
.stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; flex: 1; text-align: center; }}
.stat-card .num {{ font-size: 20px; font-weight: 700; }}
.stat-card .label {{ font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}

/* Inbox */
.inbox-input-row {{ display: flex; gap: 8px; margin-bottom: 16px; }}
.inbox-input-row input {{
    flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; color: var(--text); font-size: 13px; outline: none;
}}
.inbox-input-row input:focus {{ border-color: var(--accent); }}
.inbox-input-row input::placeholder {{ color: var(--text-dim); }}
.inbox-input-row select {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 12px; color: var(--text); font-size: 13px; cursor: pointer;
}}

/* Buttons */
.btn {{
    background: var(--accent); color: #fff; border: none; padding: 10px 18px;
    border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap;
}}
.btn:hover {{ opacity: 0.85; }}
.btn-sm {{ padding: 6px 12px; font-size: 12px; }}
.btn-outline {{ background: transparent; border: 1px solid var(--border); color: var(--text); }}
.btn-outline:hover {{ background: var(--surface2); opacity: 1; }}

/* Add task bar */
.add-task-bar {{
    display: flex; gap: 8px; margin-bottom: 12px;
}}
.add-task-bar input {{
    flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; color: var(--text); font-size: 13px; outline: none;
}}
.add-task-bar input:focus {{ border-color: var(--accent); }}
.add-task-bar input::placeholder {{ color: var(--text-dim); }}
.add-task-bar select {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; color: var(--text); font-size: 12px; cursor: pointer;
}}

.empty-msg {{ color: var(--text-dim); font-size: 13px; padding: 12px; text-align: center; }}

/* Date picker wrapper */
.date-picker-wrap {{
    position: relative; display: inline-flex; align-items: center; gap: 0;
}}
.date-picker-wrap input[type="date"] {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px 0 0 8px;
    padding: 8px 10px; color: var(--text); font-size: 12px; width: 140px; outline: none;
}}
.date-picker-wrap input[type="date"]:focus {{ border-color: var(--accent); }}
.date-picker-wrap input[type="date"]::-webkit-calendar-picker-indicator {{ filter: invert(0.7); cursor: pointer; }}
.cal-toggle {{
    background: var(--surface2); border: 1px solid var(--border); border-left: none;
    border-radius: 0 8px 8px 0; padding: 8px 10px; cursor: pointer; color: var(--text-dim);
    font-size: 14px; display: flex; align-items: center; transition: all 0.15s;
}}
.cal-toggle:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

/* Calendar popup */
.cal-popup {{
    display: none; position: absolute; top: 100%; left: 0; z-index: 1000;
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); min-width: 280px; margin-top: 4px;
}}
.cal-popup.open {{ display: block; }}
.cal-header {{
    display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;
}}
.cal-header button {{
    background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); cursor: pointer; padding: 4px 10px; font-size: 13px; transition: all 0.15s;
}}
.cal-header button:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.cal-header .cal-title {{ font-size: 13px; font-weight: 600; color: var(--text); }}
.cal-grid {{
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; text-align: center;
}}
.cal-grid .cal-dow {{
    font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px;
    padding: 4px 0; font-weight: 600;
}}
.cal-grid .cal-day {{
    font-size: 12px; padding: 6px 2px; border-radius: 6px; cursor: pointer;
    color: var(--text); transition: all 0.12s; border: 1px solid transparent;
}}
.cal-grid .cal-day:hover {{ background: var(--surface2); border-color: var(--accent); }}
.cal-grid .cal-day.today {{ border-color: var(--accent); font-weight: 700; }}
.cal-grid .cal-day.selected {{ background: var(--accent); color: #fff; font-weight: 700; }}
.cal-grid .cal-day.other-month {{ color: var(--text-dim); opacity: 0.4; }}
.cal-grid .cal-day.empty {{ cursor: default; }}
.cal-grid .cal-day.empty:hover {{ background: transparent; border-color: transparent; }}
.cal-actions {{
    display: flex; gap: 6px; margin-top: 10px; justify-content: flex-end;
}}
.cal-actions button {{
    background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text-dim); cursor: pointer; padding: 4px 12px; font-size: 11px; transition: all 0.15s;
}}
.cal-actions button:hover {{ color: var(--text); background: var(--border); }}
.cal-actions .cal-today-btn:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

/* Modal date picker adjustments */
.modal .date-picker-wrap {{ width: 100%; }}
.modal .date-picker-wrap input[type="date"] {{ width: 100%; border-radius: 8px 0 0 8px; }}

/* Edit buttons */
.edit-btn {{
    background: none; border: none; color: var(--text-dim); cursor: pointer;
    font-size: 12px; padding: 2px 6px; border-radius: 4px; opacity: 0; transition: all 0.15s;
}}
.task-item:hover .edit-btn, .top-task-row:hover .edit-btn, .card:hover .edit-btn {{ opacity: 1; }}
.edit-btn:hover {{ background: var(--surface2); color: var(--accent); }}

/* Promote/Demote buttons */
.promote-btn, .demote-btn {{
    background: none; border: 1px solid var(--border); color: var(--text-dim); cursor: pointer;
    font-size: 10px; padding: 2px 8px; border-radius: 4px; opacity: 0; transition: all 0.15s; white-space: nowrap;
}}
.card:hover .promote-btn, .card:hover .demote-btn,
.task-item:hover .promote-btn, .task-item:hover .demote-btn,
.top-task-row:hover .promote-btn, .top-task-row:hover .demote-btn {{ opacity: 1; }}
.promote-btn:hover {{ background: rgba(248,113,113,0.15); color: var(--danger); border-color: var(--danger); }}
.demote-btn:hover {{ background: rgba(251,191,36,0.15); color: var(--warning); border-color: var(--warning); }}

/* Modal */
.modal-overlay {{
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    z-index: 200; align-items: center; justify-content: center;
}}
.modal-overlay.open {{ display: flex; }}
.modal {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 24px; width: 500px; max-width: 90vw; max-height: 85vh; overflow-y: auto;
}}
.modal h3 {{ font-size: 16px; margin-bottom: 16px; }}
.modal label {{ font-size: 12px; color: var(--text-dim); display: block; margin-bottom: 4px; margin-top: 12px; }}
.modal input, .modal select, .modal textarea {{
    width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 12px; color: var(--text); font-size: 13px; outline: none; font-family: inherit;
}}
.modal textarea {{ resize: vertical; min-height: 60px; }}
.modal input:focus, .modal select:focus {{ border-color: var(--accent); }}
.modal-actions {{ display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }}

/* Toast */
.toast {{
    position: fixed; bottom: 24px; right: 24px; background: var(--success);
    color: #000; padding: 12px 20px; border-radius: 8px; font-weight: 600;
    display: none; z-index: 200; animation: fadeIn 0.2s;
}}
@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}

/* Cancel / Save for Later buttons */
.cancel-btn, .save-later-btn {{
    background: none; border: 1px solid var(--border); cursor: pointer;
    font-size: 10px; padding: 2px 8px; border-radius: 4px; opacity: 0; transition: all 0.15s; white-space: nowrap;
}}
.cancel-btn {{ color: var(--danger); }}
.save-later-btn {{ color: var(--warning); }}
.task-item:hover .cancel-btn, .task-item:hover .save-later-btn,
.top-task-row:hover .cancel-btn, .top-task-row:hover .save-later-btn {{ opacity: 1; }}
.cancel-btn:hover {{ background: rgba(248,113,113,0.15); border-color: var(--danger); }}
.save-later-btn:hover {{ background: rgba(251,191,36,0.15); border-color: var(--warning); }}

/* Notes popover */
.notes-wrapper {{
    position: relative; display: inline-block; margin-left: 6px;
}}
.notes-indicator {{
    font-size: 11px; cursor: help; opacity: 0.6;
}}
.notes-wrapper:hover .notes-indicator {{ opacity: 1; }}
.notes-popover {{
    display: none; position: absolute; bottom: calc(100% + 8px); left: 50%;
    transform: translateX(-50%); z-index: 150;
    background: var(--surface2); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; min-width: 220px; max-width: 400px;
    font-size: 12px; line-height: 1.6; color: var(--text);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    word-break: break-word; white-space: normal;
}}
.notes-popover::after {{
    content: ''; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
    border: 6px solid transparent; border-top-color: var(--border);
}}
.notes-popover a {{
    color: var(--accent); text-decoration: underline; word-break: break-all;
}}
.notes-popover a:hover {{ color: #93b8fd; }}
.notes-wrapper:hover .notes-popover {{ display: block; }}

/* Archived task notes */
.archived-notes {{
    font-size: 12px; color: var(--text-dim); margin-top: 4px;
    padding: 4px 8px; background: var(--surface2); border-radius: 4px;
    word-break: break-word;
}}
.archived-notes a {{ color: var(--accent); }}

/* Archived task items */
.archived-task {{
    align-items: center;
}}

@media (max-width: 768px) {{
    .sidebar {{ display: none; }}
    .main {{ margin-left: 0; padding: 16px; }}
    .stats-row {{ flex-wrap: wrap; }}
    .stat-card {{ min-width: calc(50% - 6px); }}
}}
</style>
</head>
<body>
<div class="app">
  <nav class="sidebar">
    <h1><span>&#9875;</span> Anchor</h1>
    <div class="subtitle">J.C. Liechty — Life Dashboard</div>
    <div class="nav-section">
      <h3>Views</h3>
      <div class="nav-item active" data-view="dashboard" onclick="showView('dashboard')">
        <span class="dot" style="background:var(--accent)"></span> Dashboard
      </div>
      <div class="nav-item" data-view="inbox" onclick="showView('inbox')">
        <span class="dot" style="background:var(--warning)"></span> Inbox <span class="count">{len(inbox)}</span>
      </div>
    </div>
    <div class="nav-section">
      <h3>Domains</h3>
      {nav_items}
    </div>
    <div class="balance-widget">
      <h4>Domain Balance</h4>
      <div class="balance-bars">
        {balance_rows}
      </div>
    </div>
  </nav>

  <div class="main">
    <!-- Dashboard view -->
    <div class="view" id="view-dashboard">
      {health_banner_html}
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Dashboard</h2>
          <button class="btn btn-sm" onclick="refresh()" style="font-size:11px;padding:4px 10px;background:var(--accent)">&#8635; Update</button>
          <button class="btn btn-sm btn-outline" id="completedBtn" onclick="showView('completed')" style="font-size:11px;padding:4px 10px">&#10003; Completed ({len(done_tasks)})</button>
          <button class="btn btn-sm btn-outline" onclick="showView('cancelled')" style="font-size:11px;padding:4px 10px;border-color:var(--danger);color:var(--danger)">&#10007; Cancelled ({len(cancelled_tasks)})</button>
          <button class="btn btn-sm btn-outline" onclick="showView('saved')" style="font-size:11px;padding:4px 10px;border-color:var(--warning);color:var(--warning)">&#128337; Saved ({len(saved_tasks)})</button>
          <button class="btn btn-sm" onclick="stopServer()" style="font-size:11px;padding:4px 10px;background:var(--danger);margin-left:auto">&#9632; Stop</button>
        </div>
        <div class="date">{today_str}</div>
      </div>

      <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
        <button class="btn btn-sm" onclick="toggleAddTask()">+ Add Task</button>
      </div>
      <div class="add-task-bar" id="addTaskBar" style="display:none;flex-wrap:wrap">
        <input type="text" id="newTask" placeholder="What needs to be done?" onkeypress="if(event.key==='Enter')addTask()" style="min-width:200px" />
        <select id="newDomain">
          <option value="academic">Academic</option>
          <option value="commercial">Commercial</option>
          <option value="writing">Writing</option>
          <option value="family">Family</option>
          <option value="personal">Personal</option>
        </select>
        <select id="newPriority">
          <option value="1">P1</option>
          <option value="2" selected>P2</option>
          <option value="3">P3</option>
        </select>
        <div class="date-picker-wrap">
          <input type="date" id="newDue" title="Due date (optional)" />
          <button type="button" class="cal-toggle" onclick="toggleCalendar('newDue', this)" title="Open calendar">&#128197;</button>
          <div class="cal-popup" id="cal_newDue"></div>
        </div>
        <button class="btn btn-sm" onclick="addTask()">Add</button>
        <input type="text" id="newNotes" placeholder="Notes — email, link, reference (optional)" style="min-width:200px;flex:1;margin-top:4px" />
      </div>

      <div class="top-tasks-box">
        <div class="top-header">
          <h3>Top Tasks</h3>
          <span class="top-progress">{top_done} / {len(top_tasks)} done</span>
        </div>
        {"".join(top_task_row(t) for t in top_tasks)}
      </div>

      <div class="section-header"><h3>Priority 1 Projects</h3></div>
      <div class="card-grid">{"".join(project_card(p) for p in p1_projects)}</div>

      <div class="stats-row">
        <div class="stat-card"><div class="num">{len([p for p in projects if p["status"]=="active"])}</div><div class="label">Active Projects</div></div>
        <div class="stat-card"><div class="num">{len(active)}</div><div class="label">Open Tasks</div></div>
        <div class="stat-card"><div class="num">{len(done_tasks)}</div><div class="label">Completed</div></div>
        <div class="stat-card"><div class="num">{len(inbox)}</div><div class="label">In Inbox</div></div>
      </div>

      <div class="section-header"><h3>Other Tasks</h3></div>
      <div class="task-list">
        {"".join(task_item(t) for t in other_tasks)}
      </div>

      <div class="section-header"><h3>Priority 2+ Projects</h3></div>
      <div class="card-grid">{"".join(project_card(p) for p in p2_projects)}</div>
    </div>

    <!-- Completed view -->
    <div class="view" id="view-completed" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Completed</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <div class="task-list">{completed_items}</div>
    </div>

    <!-- Cancelled view -->
    <div class="view" id="view-cancelled" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Cancelled Tasks</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Tasks you decided not to do. Click Restore to move one back to active.</p>
      <div class="task-list">{cancelled_items}</div>
    </div>

    <!-- Saved for Later view -->
    <div class="view" id="view-saved" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Saved for Later</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Tasks on hold. Click Restore to move one back to active.</p>
      <div class="task-list">{saved_items}</div>
    </div>

    <!-- Inbox view -->
    <div class="view" id="view-inbox" style="display:none">
      <div class="page-header"><h2>Inbox</h2></div>
      <div class="inbox-input-row">
        <input type="text" id="captureText" placeholder="Quick capture — type anything and hit Enter..." onkeydown="if(event.key==='Enter')captureItem()">
        <select id="captureDomain">
          <option value="">No tag</option>
          <option value="academic">Academic</option>
          <option value="writing">Writing</option>
          <option value="family">Family</option>
          <option value="commercial">Commercial</option>
          <option value="personal">Personal</option>
        </select>
        <button class="btn" onclick="captureItem()">Add</button>
      </div>
      <div class="task-list">{inbox_items}</div>
    </div>

    <!-- Domain views -->
    {domain_views}
  </div>
</div>

<!-- Edit Task Modal -->
<div class="modal-overlay" id="editTaskModal">
  <div class="modal">
    <h3>Edit Task</h3>
    <input type="hidden" id="editTaskOld" />
    <label>Task</label>
    <input type="text" id="editTaskText" />
    <label>Domain</label>
    <select id="editTaskDomain">
      <option value="academic">Academic</option>
      <option value="commercial">Commercial</option>
      <option value="writing">Writing</option>
      <option value="family">Family</option>
      <option value="personal">Personal</option>
    </select>
    <label>Priority</label>
    <select id="editTaskPriority">
      <option value="1">P1 — Urgent</option>
      <option value="2">P2 — Important</option>
      <option value="3">P3 — Normal</option>
    </select>
    <label>Energy</label>
    <select id="editTaskEnergy">
      <option value="low">Low</option>
      <option value="med">Med</option>
      <option value="high">High</option>
    </select>
    <label>Due Date</label>
    <div class="date-picker-wrap">
      <input type="date" id="editTaskDue" />
      <button type="button" class="cal-toggle" onclick="toggleCalendar('editTaskDue', this)" title="Open calendar">&#128197;</button>
      <div class="cal-popup" id="cal_editTaskDue"></div>
    </div>
    <label>Notes</label>
    <textarea id="editTaskNotes" placeholder="Email, link, reference, context..."></textarea>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('editTaskModal')">Cancel</button>
      <button class="btn" onclick="saveEditTask()">Save</button>
    </div>
  </div>
</div>

<!-- Edit Project Modal -->
<div class="modal-overlay" id="editProjectModal">
  <div class="modal">
    <h3>Edit Project</h3>
    <input type="hidden" id="editProjOld" />
    <label>Name</label>
    <input type="text" id="editProjName" />
    <label>Domain</label>
    <select id="editProjDomain">
      <option value="academic">Academic</option>
      <option value="commercial">Commercial</option>
      <option value="writing">Writing</option>
      <option value="family">Family</option>
      <option value="personal">Personal</option>
    </select>
    <label>Priority</label>
    <select id="editProjPriority">
      <option value="1">P1 — Top Tier</option>
      <option value="2">P2 — Important</option>
      <option value="3">P3 — Normal</option>
    </select>
    <label>Status</label>
    <select id="editProjStatus">
      <option value="active">Active</option>
      <option value="paused">Paused</option>
      <option value="completed">Completed</option>
      <option value="blocked">Blocked</option>
    </select>
    <label>Effort</label>
    <select id="editProjEffort">
      <option value="low">Low</option>
      <option value="med">Med</option>
      <option value="high">High</option>
    </select>
    <label>Due Date</label>
    <div class="date-picker-wrap">
      <input type="date" id="editProjDue" />
      <button type="button" class="cal-toggle" onclick="toggleCalendar('editProjDue', this)" title="Open calendar">&#128197;</button>
      <div class="cal-popup" id="cal_editProjDue"></div>
    </div>
    <label>Next Step</label>
    <input type="text" id="editProjNext" />
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('editProjectModal')">Cancel</button>
      <button class="btn" onclick="saveEditProject()">Save</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// Heartbeat disabled — the server runs until explicitly stopped so the
// dashboard is instantly available when you return to the tab later.

async function apiCall(endpoint, body) {{
    // Retry once on network failure — the server may have briefly paused
    // (e.g. GC, slow I/O) and the browser throttled our heartbeat.
    async function _doFetch() {{
        const r = await fetch(endpoint, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(body)
        }});
        return await r.json();
    }}
    try {{
        let data;
        try {{ data = await _doFetch(); }}
        catch(e1) {{
            await new Promise(res => setTimeout(res, 400));
            data = await _doFetch();
        }}
        if (data.ok) {{
            showToast(data.message || 'Done!');
            setTimeout(() => window.location.reload(), 600);
        }} else {{
            showToast('Error: ' + (data.error || 'unknown'));
        }}
    }} catch(e) {{
        showToast('Connection error: ' + e.message + ' — the server may have stopped. Relaunch the dashboard.');
    }}
}}

function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 2500);
}}

// ── Calendar Picker ──
let _calOpen = null;   // currently open calendar popup element
let _calInput = null;   // the date input it controls
let _calMonth = null;   // displayed month (0-11)
let _calYear = null;    // displayed year

function toggleCalendar(inputId, btn) {{
    const popup = document.getElementById('cal_' + inputId);
    const input = document.getElementById(inputId);
    if (_calOpen && _calOpen === popup) {{ closeAllCalendars(); return; }}
    closeAllCalendars();
    _calOpen = popup;
    _calInput = input;
    // Start on the input's current value or today
    const cur = input.value ? new Date(input.value + 'T00:00:00') : new Date();
    _calMonth = cur.getMonth();
    _calYear = cur.getFullYear();
    renderCalendar();
    popup.classList.add('open');
}}

function closeAllCalendars() {{
    document.querySelectorAll('.cal-popup.open').forEach(el => el.classList.remove('open'));
    _calOpen = null;
    _calInput = null;
}}

function renderCalendar() {{
    if (!_calOpen) return;
    const today = new Date();
    const todayStr = today.getFullYear() + '-' + String(today.getMonth()+1).padStart(2,'0') + '-' + String(today.getDate()).padStart(2,'0');
    const selectedStr = _calInput.value || '';
    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const dows = ['Su','Mo','Tu','We','Th','Fr','Sa'];

    const firstDay = new Date(_calYear, _calMonth, 1).getDay();
    const daysInMonth = new Date(_calYear, _calMonth + 1, 0).getDate();
    const daysInPrev = new Date(_calYear, _calMonth, 0).getDate();

    let html = `<div class="cal-header">
        <button onclick="calNav(-1)">&#9664;</button>
        <span class="cal-title">${{monthNames[_calMonth]}} ${{_calYear}}</span>
        <button onclick="calNav(1)">&#9654;</button>
    </div><div class="cal-grid">`;
    dows.forEach(d => html += `<span class="cal-dow">${{d}}</span>`);

    // Previous month trailing days
    for (let i = firstDay - 1; i >= 0; i--) {{
        const day = daysInPrev - i;
        const m = _calMonth === 0 ? 12 : _calMonth;
        const y = _calMonth === 0 ? _calYear - 1 : _calYear;
        const ds = y + '-' + String(m).padStart(2,'0') + '-' + String(day).padStart(2,'0');
        html += `<span class="cal-day other-month" onclick="calPick('${{ds}}')">${{day}}</span>`;
    }}
    // Current month days
    for (let d = 1; d <= daysInMonth; d++) {{
        const ds = _calYear + '-' + String(_calMonth+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
        let cls = 'cal-day';
        if (ds === todayStr) cls += ' today';
        if (ds === selectedStr) cls += ' selected';
        html += `<span class="${{cls}}" onclick="calPick('${{ds}}')">${{d}}</span>`;
    }}
    // Next month leading days
    const totalCells = firstDay + daysInMonth;
    const remaining = (7 - (totalCells % 7)) % 7;
    for (let d = 1; d <= remaining; d++) {{
        const m = _calMonth === 11 ? 1 : _calMonth + 2;
        const y = _calMonth === 11 ? _calYear + 1 : _calYear;
        const ds = y + '-' + String(m).padStart(2,'0') + '-' + String(d).padStart(2,'0');
        html += `<span class="cal-day other-month" onclick="calPick('${{ds}}')">${{d}}</span>`;
    }}
    html += `</div>`;
    html += `<div class="cal-actions">
        <button onclick="calClear()">Clear</button>
        <button class="cal-today-btn" onclick="calPickToday()">Today</button>
    </div>`;
    _calOpen.innerHTML = html;
}}

function calNav(delta) {{
    _calMonth += delta;
    if (_calMonth > 11) {{ _calMonth = 0; _calYear++; }}
    if (_calMonth < 0) {{ _calMonth = 11; _calYear--; }}
    renderCalendar();
}}

function calPick(dateStr) {{
    if (_calInput) {{
        _calInput.value = dateStr;
        _calInput.dispatchEvent(new Event('change'));
    }}
    closeAllCalendars();
}}

function calPickToday() {{
    const t = new Date();
    calPick(t.getFullYear() + '-' + String(t.getMonth()+1).padStart(2,'0') + '-' + String(t.getDate()).padStart(2,'0'));
}}

function calClear() {{
    if (_calInput) {{ _calInput.value = ''; _calInput.dispatchEvent(new Event('change')); }}
    closeAllCalendars();
}}

// Close calendar when clicking outside
document.addEventListener('click', function(e) {{
    if (_calOpen && !e.target.closest('.date-picker-wrap')) closeAllCalendars();
}});

function dec(b64) {{ return decodeURIComponent(Array.from(atob(b64), c => '%' + c.charCodeAt(0).toString(16).padStart(2,'0')).join('')); }}
function decTask(b64) {{ return JSON.parse(dec(b64)); }}
function decProj(b64) {{ return JSON.parse(dec(b64)); }}
function markDone(b64) {{ apiCall('/api/done', {{text: dec(b64)}}); }}
function markUndone(b64) {{ apiCall('/api/undone', {{text: dec(b64)}}); }}

function addTask() {{
    const text = document.getElementById('newTask').value.trim();
    if (!text) return;
    const domain = document.getElementById('newDomain').value;
    const priority = parseInt(document.getElementById('newPriority').value);
    const due = document.getElementById('newDue').value || '';
    const notes = document.getElementById('newNotes').value.trim();
    apiCall('/api/add', {{text, domain, priority, energy: 'med', due, notes}});
}}

function cancelTask(b64) {{
    if (confirm('Cancel this task? It will be moved to the Cancelled list.')) {{
        apiCall('/api/cancel', {{text: dec(b64)}});
    }}
}}

function saveForLater(b64) {{
    if (confirm('Save this task for later? It will be moved off the dashboard.')) {{
        apiCall('/api/save_for_later', {{text: dec(b64)}});
    }}
}}

function restoreTask(b64, from_archive) {{
    apiCall('/api/restore', {{text: dec(b64), from: from_archive}});
}}

function captureItem() {{
    const text = document.getElementById('captureText').value.trim();
    if (!text) return;
    const domain = document.getElementById('captureDomain').value;
    apiCall('/api/capture', {{text, domain}});
}}

function refresh() {{ window.location.reload(); }}

function toggleAddTask() {{
    const bar = document.getElementById('addTaskBar');
    bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
    if (bar.style.display === 'flex') document.getElementById('newTask').focus();
}}

function showView(view) {{
    document.querySelectorAll('.view').forEach(el => el.style.display = 'none');
    const el = document.getElementById('view-' + view);
    if (el) el.style.display = 'block';
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navEl = document.querySelector('.nav-item[data-view="' + view + '"]');
    if (navEl) navEl.classList.add('active');
}}

// ── Modal helpers ──
function closeModal(id) {{
    document.getElementById(id).classList.remove('open');
}}

function openEditTask(t) {{
    document.getElementById('editTaskOld').value = t.text;
    document.getElementById('editTaskText').value = t.text;
    document.getElementById('editTaskDomain').value = t.domain || 'academic';
    document.getElementById('editTaskPriority').value = t.priority || 2;
    document.getElementById('editTaskEnergy').value = t.energy || 'med';
    document.getElementById('editTaskDue').value = t.due || '';
    document.getElementById('editTaskNotes').value = t.notes || '';
    document.getElementById('editTaskModal').classList.add('open');
}}

function saveEditTask() {{
    const old_text = document.getElementById('editTaskOld').value;
    const body = {{
        old_text: old_text,
        new_text: document.getElementById('editTaskText').value.trim(),
        new_priority: parseInt(document.getElementById('editTaskPriority').value),
        new_domain: document.getElementById('editTaskDomain').value,
        new_energy: document.getElementById('editTaskEnergy').value,
        new_due: document.getElementById('editTaskDue').value || '',
        new_notes: document.getElementById('editTaskNotes').value.trim(),
    }};
    closeModal('editTaskModal');
    apiCall('/api/edit_task', body);
}}

function openEditProject(p) {{
    document.getElementById('editProjOld').value = p.name;
    document.getElementById('editProjName').value = p.name;
    document.getElementById('editProjDomain').value = p.domain || 'academic';
    document.getElementById('editProjPriority').value = p.priority || 2;
    document.getElementById('editProjStatus').value = p.status || 'active';
    document.getElementById('editProjEffort').value = p.effort || 'high';
    document.getElementById('editProjDue').value = p.due || '';
    document.getElementById('editProjNext').value = p.next || '';
    document.getElementById('editProjectModal').classList.add('open');
}}

function saveEditProject() {{
    const old_name = document.getElementById('editProjOld').value;
    const body = {{
        old_name: old_name,
        new_name: document.getElementById('editProjName').value.trim(),
        new_priority: parseInt(document.getElementById('editProjPriority').value),
        new_domain: document.getElementById('editProjDomain').value,
        new_status: document.getElementById('editProjStatus').value,
        new_effort: document.getElementById('editProjEffort').value,
        new_due: document.getElementById('editProjDue').value || '',
        new_next: document.getElementById('editProjNext').value,
    }};
    closeModal('editProjectModal');
    apiCall('/api/edit_project', body);
}}

function stopServer() {{
    if (confirm('Stop the Anchor dashboard server?')) {{
        fetch('/api/shutdown', {{method: 'POST'}}).then(() => {{
            document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;background:#0f1117;color:#e2e4e9;font-size:18px">Anchor stopped. You can close this tab.</div>';
        }}).catch(() => {{}});
    }}
}}

function promoteProject(b64) {{ apiCall('/api/promote_project', {{name: dec(b64)}}); }}
function demoteProject(b64) {{ apiCall('/api/demote_project', {{name: dec(b64)}}); }}
function promoteTask(b64) {{ apiCall('/api/promote_task', {{text: dec(b64)}}); }}
function demoteTask(b64) {{ apiCall('/api/demote_task', {{text: dec(b64)}}); }}

// Domain-specific add task
function toggleAddTask_(domain) {{
    const bar = document.getElementById('addTaskBar_' + domain);
    bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
    if (bar.style.display === 'flex') document.getElementById('newTask_' + domain).focus();
}}
// Alias so onclick="toggleAddTask_family()" works via dynamic name
{" ".join(f"function toggleAddTask_{d}() {{ toggleAddTask_('{d}'); }}" for d in domain_order)}

function addTaskDomain(domain) {{
    const text = document.getElementById('newTask_' + domain).value.trim();
    if (!text) return;
    const priority = parseInt(document.getElementById('newPriority_' + domain).value);
    const due = document.getElementById('newDue_' + domain).value || '';
    const notes = document.getElementById('newNotes_' + domain).value.trim();
    apiCall('/api/add', {{text, domain, priority, energy: 'med', due, notes}});
}}
</script>
</body>
</html>'''


# ── HTTP Server ────────────────────────────────────────────────────────

class AnchorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {args[0]}")

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_text):
        body = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/" or self.path == "/dashboard":
                projects, tasks, inbox = gather_all()
                html = generate_html(projects, tasks, inbox)
                self._send_html(html)
            elif self.path == "/favicon.ico":
                ico_path = ANCHOR_DIR / "anchor.ico"
                if ico_path.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/x-icon")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(ico_path.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path == "/api/status":
                projects, tasks, inbox = gather_all()
                active = [t for t in tasks if not t["done"]]
                self._send_json({
                    "projects": len(projects),
                    "active": len(active),
                    "done": len([t for t in tasks if t["done"]]),
                    "inbox": len(inbox),
                })
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            _logger.error(f"GET {self.path} failed: {e}\n{traceback.format_exc()}")
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_POST(self):
      try:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        if self.path == "/api/done":
            text = body.get("text", "")
            ok = mark_done(text)
            self._send_json({"ok": ok, "message": f"Marked done: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/undone":
            text = body.get("text", "")
            ok = mark_undone(text)
            self._send_json({"ok": ok, "message": f"Reopened: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/add":
            text = body.get("text", "")
            domain = body.get("domain", "academic")
            priority = body.get("priority", 2)
            energy = body.get("energy", "med")
            due = body.get("due", "")
            notes = body.get("notes", "")
            add_task(text, domain, priority, energy, due, notes)
            self._send_json({"ok": True, "message": f"Added: {text} [{domain}] P{priority}"})

        elif self.path == "/api/capture":
            text = body.get("text", "")
            domain = body.get("domain", "")
            capture_inbox(text, domain)
            self._send_json({"ok": True, "message": f"Captured: {text}"})

        elif self.path == "/api/edit_task":
            old_text = body.get("old_text", "")
            ok = edit_task(
                old_text,
                new_text=body.get("new_text"),
                new_priority=body.get("new_priority"),
                new_domain=body.get("new_domain"),
                new_energy=body.get("new_energy"),
                new_due=body.get("new_due"),
                new_notes=body.get("new_notes"),
            )
            self._send_json({"ok": ok, "message": f"Updated task" if ok else f"Task not found: {old_text}"})

        elif self.path == "/api/edit_project":
            old_name = body.get("old_name", "")
            ok = edit_project(
                old_name,
                new_name=body.get("new_name"),
                new_priority=body.get("new_priority"),
                new_domain=body.get("new_domain"),
                new_status=body.get("new_status"),
                new_effort=body.get("new_effort"),
                new_due=body.get("new_due"),
                new_next=body.get("new_next"),
            )
            self._send_json({"ok": ok, "message": f"Updated project" if ok else f"Project not found: {old_name}"})

        elif self.path == "/api/promote_project":
            name = body.get("name", "")
            ok = edit_project(name, new_priority=1)
            self._send_json({"ok": ok, "message": f"Promoted to P1: {name}" if ok else f"Not found: {name}"})

        elif self.path == "/api/demote_project":
            name = body.get("name", "")
            ok = edit_project(name, new_priority=2)
            self._send_json({"ok": ok, "message": f"Demoted to P2: {name}" if ok else f"Not found: {name}"})

        elif self.path == "/api/promote_task":
            text = body.get("text", "")
            ok = edit_task(text, new_priority=1)
            self._send_json({"ok": ok, "message": f"Promoted to P1: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/demote_task":
            text = body.get("text", "")
            ok = edit_task(text, new_priority=2)
            self._send_json({"ok": ok, "message": f"Demoted to P2: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/cancel":
            text = body.get("text", "")
            ok = cancel_task(text)
            self._send_json({"ok": ok, "message": f"Cancelled: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/save_for_later":
            text = body.get("text", "")
            ok = save_for_later(text)
            self._send_json({"ok": ok, "message": f"Saved for later: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/restore":
            text = body.get("text", "")
            from_archive = body.get("from", "saved")
            ok = restore_task(text, from_archive)
            self._send_json({"ok": ok, "message": f"Restored: {text}" if ok else f"Not found: {text}"})

        elif self.path == "/api/heartbeat":
            global _last_heartbeat
            _last_heartbeat = datetime.now()
            self._send_json({"ok": True})

        elif self.path == "/api/shutdown":
            self._send_json({"ok": True, "message": "Shutting down..."})
            log_change("Dashboard server stopped")
            threading.Timer(0.5, lambda: _server_instance.shutdown()).start()

        else:
            self._send_json({"ok": False, "error": "Unknown endpoint"}, 404)
      except Exception as e:
            _logger.error(f"POST {self.path} failed: {e}\n{traceback.format_exc()}")
            self._send_json({"ok": False, "error": str(e)}, 500)


_server_instance = None
_last_heartbeat = None
_heartbeat_active = False  # Only start monitoring after the first heartbeat arrives


def _heartbeat_watchdog():
    """Background thread: heartbeat monitoring disabled.

    The server now runs until explicitly stopped — via the Stop button in the
    dashboard, Ctrl+C in the terminal, or by killing the Python process. This
    keeps the dashboard instantly available when the user comes back to the
    tab after any amount of time.
    """
    return


def main():
    global _server_instance
    port = 8777
    no_browser = "--no-browser" in sys.argv
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    server = HTTPServer(("127.0.0.1", port), AnchorHandler)
    _server_instance = server
    url = f"http://localhost:{port}"

    # Start heartbeat watchdog thread
    watchdog = threading.Thread(target=_heartbeat_watchdog, daemon=True)
    watchdog.start()

    print(f"\n{'='*50}")
    print(f"  Anchor Dashboard running at {url}")
    print(f"  Server runs until you stop it (Stop button / Ctrl+C).")
    print(f"  Press Ctrl+C to stop manually.")
    print(f"  Error log: {ERROR_LOG}")
    print(f"{'='*50}\n")

    _logger.info(f"Server started on {url}")

    if not no_browser:
        # Open browser after a short delay
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _logger.info("Server stopped")
        print("\nAnchor stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
