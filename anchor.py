#!/usr/bin/env python3
"""
Anchor — Productivity Engine for J.C. Liechty
Reads/writes markdown files, generates dashboard.html, logs changes.

Usage:
    python3 anchor.py dashboard          # Rebuild dashboard.html from markdown files
    python3 anchor.py done "task text"   # Mark a task as done
    python3 anchor.py cancel "task text" # Cancel a task (moves to CANCELLED.md)
    python3 anchor.py save "task text"   # Save a task for later (moves to SAVED_FOR_LATER.md)
    python3 anchor.py restore "task text" --from saved|cancelled  # Restore archived task
    python3 anchor.py add "task" --domain academic --priority 1 --energy high --due 2026-04-10 --notes "some note"
    python3 anchor.py capture "idea"     # Add to inbox
    python3 anchor.py status             # Print current status summary
"""

import json, os, re, sys
from datetime import datetime, date
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
ANCHOR_DIR = Path(__file__).parent

# Detect whether we're running from PSU or Axmra
AXMRA_ANCHOR = ANCHOR_DIR / ".anchor"
IS_AXMRA = AXMRA_ANCHOR.exists()

# --- PSU paths (primary directory with domains/) ---
# --- Axmra paths (commercial directory with .anchor/) ---
# We always need BOTH directories for full sync.

def _find_sibling_dir():
    """Find the sibling Anchor directory (PSU finds Axmra, Axmra finds PSU)."""
    parent = ANCHOR_DIR.parent
    if IS_AXMRA:
        # We're in Axmra — look for PSU sibling
        for d in parent.iterdir():
            if d.is_dir() and d != ANCHOR_DIR and (d / "domains").exists() and (d / "DASHBOARD.md").exists():
                return d
    else:
        # We're in PSU — look for Axmra sibling
        for d in parent.iterdir():
            if d.is_dir() and d != ANCHOR_DIR and (d / ".anchor").exists():
                return d
    return None

SIBLING_DIR = _find_sibling_dir()

# Set up path references for BOTH directories
if IS_AXMRA:
    # Running from Axmra
    AXMRA_DIR = ANCHOR_DIR
    PSU_DIR = SIBLING_DIR  # may be None
else:
    # Running from PSU
    PSU_DIR = ANCHOR_DIR
    AXMRA_DIR = SIBLING_DIR  # may be None

# PSU file paths
PSU_DASHBOARD_MD = PSU_DIR / "DASHBOARD.md" if PSU_DIR else None
PSU_PROJECTS_MD = PSU_DIR / "PROJECTS.md" if PSU_DIR else None
PSU_INBOX_MD = PSU_DIR / "INBOX.md" if PSU_DIR else None
PSU_DOMAINS_DIR = PSU_DIR / "domains" if PSU_DIR else None
PSU_LOGS_DIR = PSU_DIR / "logs" if PSU_DIR else None
PSU_HTML_FILE = PSU_DIR / "dashboard.html" if PSU_DIR else None
PSU_CANCELLED_MD = PSU_DIR / "CANCELLED.md" if PSU_DIR else None
PSU_SAVED_FOR_LATER_MD = PSU_DIR / "SAVED_FOR_LATER.md" if PSU_DIR else None

# Axmra file paths
AXMRA_DASHBOARD_MD = AXMRA_DIR / ".anchor" / "DASHBOARD.md" if AXMRA_DIR else None
AXMRA_PROJECTS_MD = AXMRA_DIR / ".anchor" / "PROJECTS.md" if AXMRA_DIR else None
AXMRA_INBOX_MD = AXMRA_DIR / ".anchor" / "INBOX.md" if AXMRA_DIR else None
AXMRA_LOGS_DIR = AXMRA_DIR / ".anchor" / "logs" if AXMRA_DIR else None
AXMRA_HTML_FILE = AXMRA_DIR / "dashboard.html" if AXMRA_DIR else None

# The HTML file in the current directory (always exists)
HTML_FILE = ANCHOR_DIR / "dashboard.html"

# Ensure log directories exist
if PSU_LOGS_DIR:
    PSU_LOGS_DIR.mkdir(exist_ok=True)
if AXMRA_LOGS_DIR:
    AXMRA_LOGS_DIR.mkdir(exist_ok=True)

# Report sibling discovery
if SIBLING_DIR:
    print(f"Syncing: {ANCHOR_DIR.name} ↔ {SIBLING_DIR.name}")
else:
    print(f"Warning: Sibling directory not found. Running single-directory mode.")


# ── Parsing helpers ────────────────────────────────────────────────────

def parse_tasks_from_md(filepath):
    """Extract checkbox tasks from a markdown file."""
    tasks = []
    if not filepath.exists():
        return tasks
    text = filepath.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r'\s*-\s*\[([ xX])\]\s*\*?\*?(.*?)(?:\*?\*?\s*—\s*(.*))?$', line)
        if m:
            done = m.group(1).lower() == 'x'
            raw_text = m.group(2).strip().rstrip('*')
            meta = m.group(3) or ""
            # Extract priority
            pm = re.search(r'Priority:\s*(\d)', meta) or re.search(r'Priority:\s*(\d)', raw_text)
            priority = int(pm.group(1)) if pm else 2
            # Extract energy
            em = re.search(r'energy:\s*(\w+)', meta, re.I) or re.search(r'energy:\s*(\w+)', raw_text, re.I)
            energy = em.group(1).lower() if em else "med"
            # Extract domain
            dm = re.search(r'\[(\w+)\]', meta) or re.search(r'\[(\w+)\]', raw_text)
            domain = dm.group(1).lower() if dm else "personal"
            # Extract due date
            due_m = re.search(r'Due:\s*([\d/\-\w]+)', meta, re.I)
            due = due_m.group(1) if due_m else ""
            # Extract notes
            notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|\[)|$)', meta, re.I)
            if not notes_m:
                notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
            notes = notes_m.group(1).strip().rstrip(' —') if notes_m else ""
            # Clean text
            clean = re.sub(r'\s*—\s*Priority:.*', '', raw_text)
            clean = re.sub(r'\s*—\s*\[.*', '', clean)
            clean = re.sub(r'\s*—\s*energy:.*', '', clean, flags=re.I)
            clean = re.sub(r'\s*—\s*Notes:.*', '', clean, flags=re.I)
            clean = clean.strip(' *')
            tasks.append({
                "text": clean,
                "done": done,
                "priority": priority,
                "energy": energy,
                "domain": domain,
                "due": due,
                "notes": notes,
            })
    return tasks


def parse_projects_from_md(filepath):
    """Extract projects from PROJECTS.md."""
    projects = []
    if not filepath.exists():
        return projects
    text = filepath.read_text(encoding="utf-8")
    current = None
    for line in text.splitlines():
        h2 = re.match(r'^##\s+(.+)', line)
        if h2:
            if current:
                projects.append(current)
            current = {
                "name": h2.group(1).strip(),
                "domain": "academic",
                "priority": 2,
                "status": "active",
                "effort": "high",
                "due": "",
                "next": "",
                "collabs": "",
                "notes": "",
            }
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
    """Extract inbox items from INBOX.md."""
    items = []
    if not filepath.exists():
        return items
    text = filepath.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r'\s*-\s*(\d{4}-\d{2}-\d{2}):\s*(.*?)(?:\s*\[(\w+)\])?\s*$', line)
        if m:
            items.append({
                "date": m.group(1),
                "text": m.group(2).strip(),
                "domain": m.group(3) or "",
            })
    return items


# ── Dashboard HTML generation ──────────────────────────────────────────

def read_html_template():
    """Read the dashboard.html and return (before_state, after_state) for STATE injection."""
    if not HTML_FILE.exists():
        return None, None
    text = HTML_FILE.read_text(encoding="utf-8")
    # Find the STATE block
    state_start = text.find("const STATE = {")
    if state_start < 0:
        return None, None
    # Find the closing of STATE (nextId line + };)
    state_end = text.find("};", text.find("nextId:", state_start))
    if state_end < 0:
        return None, None
    state_end += 2  # include the };
    return text[:state_start], text[state_end:]


def generate_state_js(projects, tasks, inbox):
    """Generate the JavaScript STATE object."""
    def js_str(s):
        return s.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", " ")

    lines = ["const STATE = {"]
    lines.append("  projects: [")
    for i, p in enumerate(projects):
        lines.append("    {")
        lines.append(f'      id: {i+1}, name: "{js_str(p["name"])}", domain: "{p["domain"]}", priority: {p["priority"]},')
        lines.append(f'      status: "{p["status"]}", effort: "{p.get("effort","high")}", due: "{p.get("due","")}",')
        lines.append(f'      next: "{js_str(p.get("next",""))}", collabs: "{js_str(p.get("collabs",""))}", notes: "{js_str(p.get("notes",""))}"')
        lines.append("    },")
    lines.append("  ],")

    lines.append("  tasks: [")
    for i, t in enumerate(tasks):
        done_str = "true" if t["done"] else "false"
        lines.append(f'    {{ id: {i+1}, text: "{js_str(t["text"])}", domain: "{t["domain"]}", priority: {t["priority"]}, energy: "{t["energy"]}", due: "{t.get("due","")}", done: {done_str} }},')
    lines.append("  ],")

    lines.append("  inbox: [")
    for i, item in enumerate(inbox):
        lines.append(f'    {{ id: {i+1}, text: "{js_str(item["text"])}", date: "{item["date"]}", domain: "{item.get("domain","")}" }},')
    lines.append("  ],")

    next_proj = len(projects) + 50
    next_task = len(tasks) + 1
    next_inbox = len(inbox) + 1
    lines.append(f"  nextId: {{ projects: {next_proj}, tasks: {next_task}, inbox: {next_inbox} }}")
    lines.append("};")
    return "\n".join(lines)


def rebuild_dashboard():
    """Read all markdown files from BOTH directories, regenerate dashboard.html STATE, copy to both dirs."""
    before, after = read_html_template()
    if before is None:
        print("ERROR: dashboard.html not found or STATE block not parseable")
        return False

    # Gather all tasks from BOTH directories
    all_tasks = []
    seen_texts = set()

    def _add_tasks(task_list, default_domain=None):
        for t in task_list:
            key = t["text"].lower().strip()[:60]
            if key not in seen_texts:
                seen_texts.add(key)
                if default_domain and t["domain"] == "personal":
                    t["domain"] = default_domain
                all_tasks.append(t)

    # ── PSU tasks ──
    if PSU_DASHBOARD_MD and PSU_DASHBOARD_MD.exists():
        _add_tasks(parse_tasks_from_md(PSU_DASHBOARD_MD))

    if PSU_DOMAINS_DIR and PSU_DOMAINS_DIR.exists():
        for domain_file in sorted(PSU_DOMAINS_DIR.glob("*.md")):
            _add_tasks(parse_tasks_from_md(domain_file), default_domain=domain_file.stem)

    # ── Axmra tasks (from .anchor/ files) ──
    if AXMRA_DASHBOARD_MD and AXMRA_DASHBOARD_MD.exists():
        _add_tasks(parse_tasks_from_md(AXMRA_DASHBOARD_MD), default_domain="commercial")

    if AXMRA_PROJECTS_MD and AXMRA_PROJECTS_MD.exists():
        _add_tasks(parse_tasks_from_md(AXMRA_PROJECTS_MD), default_domain="commercial")

    # ── Projects from BOTH directories ──
    projects = []
    seen_proj = set()
    if PSU_PROJECTS_MD and PSU_PROJECTS_MD.exists():
        for p in parse_projects_from_md(PSU_PROJECTS_MD):
            key = p["name"].lower().strip()[:60]
            if key not in seen_proj:
                seen_proj.add(key)
                projects.append(p)

    if AXMRA_PROJECTS_MD and AXMRA_PROJECTS_MD.exists():
        for p in parse_projects_from_md(AXMRA_PROJECTS_MD):
            key = p["name"].lower().strip()[:60]
            if key not in seen_proj:
                seen_proj.add(key)
                if p["domain"] == "academic":
                    p["domain"] = "commercial"
                projects.append(p)

    # ── Inbox from BOTH directories ──
    inbox = []
    if PSU_INBOX_MD and PSU_INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(PSU_INBOX_MD))
    if AXMRA_INBOX_MD and AXMRA_INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(AXMRA_INBOX_MD))

    # Generate new STATE
    state_js = generate_state_js(projects, all_tasks, inbox)

    # Write updated HTML to current directory
    new_html = before + state_js + after
    HTML_FILE.write_text(new_html, encoding="utf-8")

    # Copy dashboard.html to sibling directory so both stay in sync
    if SIBLING_DIR:
        sibling_html = SIBLING_DIR / "dashboard.html"
        sibling_html.write_text(new_html, encoding="utf-8")
        print(f"Dashboard synced to {SIBLING_DIR.name}/dashboard.html")

    # Summary
    active = [t for t in all_tasks if not t["done"]]
    p1 = [t for t in active if t["priority"] == 1]
    done_count = len([t for t in all_tasks if t["done"]])

    print(f"Dashboard rebuilt: {len(projects)} projects, {len(active)} active tasks, {done_count} completed, {len(inbox)} inbox items")
    if p1:
        print(f"P1 tasks: {len(p1)}")
        for t in p1:
            due_str = f" (due {t['due']})" if t.get('due') else ""
            print(f"  - {t['text']}{due_str}")
    return True


# ── Change operations ──────────────────────────────────────────────────

def log_change(message):
    """Append a timestamped line to today's log file in BOTH directories."""
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")

    for logs_dir in [PSU_LOGS_DIR, AXMRA_LOGS_DIR]:
        if logs_dir is None:
            continue
        logs_dir.mkdir(exist_ok=True)
        log_file = logs_dir / f"{today}.md"
        if not log_file.exists():
            day_name = datetime.now().strftime("%A")
            log_file.write_text(f"# {today} — {day_name}\n\n## Changes\n", encoding="utf-8")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"- {now} — {message}\n")

    print(f"Logged: {now} — {message}")


def mark_done(task_text):
    """Mark a task as done across ALL markdown files in BOTH directories."""
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
        rebuild_dashboard()
        print(f"✓ Marked done: {task_text}")
    else:
        print(f"Task not found: {task_text}")
        print("Available tasks:")
        for md_file in _all_md_files():
            if md_file and md_file.exists():
                for t in parse_tasks_from_md(md_file):
                    if not t["done"]:
                        print(f"  - {t['text']} ({md_file.parent.name}/{md_file.name})")
    return found


def add_task(text, domain="academic", priority=2, energy="med", due="", notes=""):
    """Add a new task to the appropriate files in BOTH directories."""
    due_str = f" — Due: {due}" if due else ""
    notes_str = f" — Notes: {notes}" if notes else ""
    line = f"- [ ] {text} — Priority: {priority} — energy: {energy} — [{domain}]{due_str}{notes_str}"

    def _insert_in_section(filepath, section_names):
        """Insert a task line into the first matching section of a markdown file."""
        if not filepath or not filepath.exists():
            return False
        content = filepath.read_text(encoding="utf-8")
        for section in section_names:
            idx = content.find(section)
            if idx >= 0:
                next_section = content.find("\n##", idx + len(section))
                if next_section < 0:
                    next_section = len(content)
                content = content[:next_section].rstrip() + "\n" + line + "\n\n" + content[next_section:]
                filepath.write_text(content, encoding="utf-8")
                return True
        return False

    # Always add to PSU DASHBOARD.md (central hub)
    _insert_in_section(PSU_DASHBOARD_MD, ["## Today's Priorities", "## Active Priorities"])

    # Add to the right domain file or Axmra dashboard
    if domain == "commercial":
        # Commercial tasks go to Axmra .anchor/DASHBOARD.md
        _insert_in_section(AXMRA_DASHBOARD_MD, ["## Active Priorities", "## Current Focus"])
        # Also add to PSU domains/commercial.md if it has active tasks section
        if PSU_DOMAINS_DIR:
            _insert_in_section(PSU_DOMAINS_DIR / "commercial.md", ["## Active Tasks"])
    else:
        # Non-commercial tasks go to PSU domain files
        if PSU_DOMAINS_DIR:
            domain_file = PSU_DOMAINS_DIR / f"{domain}.md"
            _insert_in_section(domain_file, ["## Active Tasks"])

    log_change(f"Added task: {text} [{domain}] P{priority}")
    rebuild_dashboard()
    print(f"✓ Added: {text} [{domain}] P{priority}")


def capture_inbox(text, domain=""):
    """Add an item to the inbox (PSU inbox by default, Axmra for commercial)."""
    today = date.today().isoformat()
    domain_tag = f" [{domain}]" if domain else ""
    line = f"- {today}: {text}{domain_tag}"

    # Write to PSU inbox (always — it's the central hub)
    if PSU_INBOX_MD and PSU_INBOX_MD.exists():
        content = PSU_INBOX_MD.read_text(encoding="utf-8")
        content = content.rstrip() + "\n" + line + "\n"
        PSU_INBOX_MD.write_text(content, encoding="utf-8")

    # Also write to Axmra inbox if domain is commercial
    if domain == "commercial" and AXMRA_INBOX_MD and AXMRA_INBOX_MD.exists():
        content = AXMRA_INBOX_MD.read_text(encoding="utf-8")
        content = content.rstrip() + "\n" + line + "\n"
        AXMRA_INBOX_MD.write_text(content, encoding="utf-8")

    log_change(f"Captured to inbox: {text}")
    rebuild_dashboard()
    print(f"✓ Captured: {text}")


def print_status():
    """Print a status summary from BOTH directories."""
    tasks = []
    seen = set()
    for md_file in _all_md_files():
        if md_file and md_file.exists():
            for t in parse_tasks_from_md(md_file):
                key = t["text"].lower().strip()[:60]
                if key not in seen:
                    seen.add(key)
                    tasks.append(t)

    projects = []
    if PSU_PROJECTS_MD and PSU_PROJECTS_MD.exists():
        projects.extend(parse_projects_from_md(PSU_PROJECTS_MD))
    if AXMRA_PROJECTS_MD and AXMRA_PROJECTS_MD.exists():
        projects.extend(parse_projects_from_md(AXMRA_PROJECTS_MD))

    inbox = []
    if PSU_INBOX_MD and PSU_INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(PSU_INBOX_MD))
    if AXMRA_INBOX_MD and AXMRA_INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(AXMRA_INBOX_MD))

    active = [t for t in tasks if not t["done"]]
    done = [t for t in tasks if t["done"]]
    p1 = [t for t in active if t["priority"] == 1]

    today = datetime.now().strftime("%A, %B %d, %Y")
    print(f"Anchor — {today}")
    print(f"{len(projects)} projects | {len(active)} active tasks | {len(done)} completed | {len(inbox)} inbox")
    if p1:
        print(f"\nUrgent (P1):")
        for t in p1:
            due = f" — due {t['due']}" if t.get("due") else ""
            print(f"  ⚡ {t['text']}{due}")


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
                continue
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
        _append_to_archive(PSU_CANCELLED_MD, task)
        log_change(f"Cancelled: {task_text}")
        rebuild_dashboard()
        print(f"✗ Cancelled: {task_text}")
        return True
    print(f"Task not found: {task_text}")
    return False


def save_for_later(task_text):
    """Save a task for later: remove from active lists, add to SAVED_FOR_LATER.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(PSU_SAVED_FOR_LATER_MD, task)
        log_change(f"Saved for later: {task_text}")
        rebuild_dashboard()
        print(f"⏳ Saved for later: {task_text}")
        return True
    print(f"Task not found: {task_text}")
    return False


def restore_task(task_text, from_archive="saved"):
    """Restore a task from an archive back to the active dashboard."""
    archive_file = PSU_SAVED_FOR_LATER_MD if from_archive == "saved" else PSU_CANCELLED_MD
    if not archive_file or not archive_file.exists():
        print(f"Archive file not found")
        return False
    text = archive_file.read_text(encoding="utf-8")
    search = task_text.lower().strip()
    found = None
    new_lines = []
    for line in text.splitlines():
        if search in line.lower() and not found:
            m = re.match(r'\s*-\s*\d{4}-\d{2}-\d{2}:\s*(.*?)(?:\s*—\s*\[(\w+)\])?(?:\s*—\s*P(\d))?(?:\s*—\s*Notes:\s*(.*))?$', line)
            if m:
                found = {
                    "text": m.group(1).strip(),
                    "domain": m.group(2) or "personal",
                    "priority": int(m.group(3)) if m.group(3) else 2,
                    "notes": m.group(4).strip() if m.group(4) else "",
                }
            continue
        new_lines.append(line)
    if found:
        archive_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        add_task(found["text"], found["domain"], found["priority"], "med", "", found["notes"])
        log_change(f"Restored from {from_archive}: {task_text}")
        print(f"✓ Restored: {task_text}")
        return True
    print(f"Task not found in archive: {task_text}")
    return False


def _all_md_files():
    """Return all markdown files that might contain tasks from BOTH directories."""
    files = []

    # PSU files
    if PSU_DASHBOARD_MD:
        files.append(PSU_DASHBOARD_MD)
    if PSU_DOMAINS_DIR and PSU_DOMAINS_DIR.exists():
        files.extend(sorted(PSU_DOMAINS_DIR.glob("*.md")))

    # Axmra .anchor/ files
    if AXMRA_DASHBOARD_MD:
        files.append(AXMRA_DASHBOARD_MD)
    if AXMRA_PROJECTS_MD:
        files.append(AXMRA_PROJECTS_MD)

    return files


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1].lower()

    if cmd == "dashboard":
        rebuild_dashboard()

    elif cmd == "status":
        print_status()

    elif cmd == "done":
        if len(sys.argv) < 3:
            print("Usage: anchor.py done \"task text\"")
            return
        mark_done(" ".join(sys.argv[2:]))

    elif cmd == "cancel":
        if len(sys.argv) < 3:
            print("Usage: anchor.py cancel \"task text\"")
            return
        cancel_task(" ".join(sys.argv[2:]))

    elif cmd == "save":
        if len(sys.argv) < 3:
            print("Usage: anchor.py save \"task text\"")
            return
        save_for_later(" ".join(sys.argv[2:]))

    elif cmd == "restore":
        if len(sys.argv) < 3:
            print("Usage: anchor.py restore \"task text\" --from saved|cancelled")
            return
        text_parts = []
        from_archive = "saved"
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--from" and i+1 < len(sys.argv):
                from_archive = sys.argv[i+1]; i += 2
            else:
                text_parts.append(sys.argv[i]); i += 1
        restore_task(" ".join(text_parts), from_archive)

    elif cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: anchor.py add \"task\" --domain academic --priority 1 --energy high --due 2026-04-10 --notes \"some note\"")
            return
        # Parse arguments
        text_parts = []
        domain = "academic"
        priority = 2
        energy = "med"
        due = ""
        notes = ""
        i = 2
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--domain" and i+1 < len(sys.argv):
                domain = sys.argv[i+1]; i += 2
            elif arg == "--priority" and i+1 < len(sys.argv):
                priority = int(sys.argv[i+1]); i += 2
            elif arg == "--energy" and i+1 < len(sys.argv):
                energy = sys.argv[i+1]; i += 2
            elif arg == "--due" and i+1 < len(sys.argv):
                due = sys.argv[i+1]; i += 2
            elif arg == "--notes" and i+1 < len(sys.argv):
                notes = sys.argv[i+1]; i += 2
            else:
                text_parts.append(arg); i += 1
        add_task(" ".join(text_parts), domain, priority, energy, due, notes)

    elif cmd == "capture":
        if len(sys.argv) < 3:
            print("Usage: anchor.py capture \"idea\" [--domain academic]")
            return
        text_parts = []
        domain = ""
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--domain" and i+1 < len(sys.argv):
                domain = sys.argv[i+1]; i += 2
            else:
                text_parts.append(sys.argv[i]); i += 1
        capture_inbox(" ".join(text_parts), domain)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


if __name__ == "__main__":
    main()
