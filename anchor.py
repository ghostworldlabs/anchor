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
# Single-folder layout (was previously dual-folder PSU + Axmra; consolidated 2026-05-02).
# Wave 2: all data paths resolve via the shared `paths` helper, which honors the
# ANCHOR_DATA_DIR env var (unset -> the code dir, so behavior is unchanged).
import paths as _paths

# ANCHOR_DIR is the *code* dir (kept for code-relative references / back-compat).
ANCHOR_DIR = _paths.CODE_DIR

# Data paths resolved at module load from the current ANCHOR_DATA_DIR. Resolving
# here (not at every use site) keeps the existing module-level constant API while
# still honoring the env var; tests that need a tmp data dir set the env var
# before import, or call the paths.* helpers directly.
DASHBOARD_MD = _paths.dashboard_md()
PROJECTS_MD = _paths.projects_md()
INBOX_MD = _paths.inbox_md()
DOMAINS_DIR = _paths.domains_dir()
LOGS_DIR = _paths.logs_dir()
HTML_FILE = _paths.dashboard_html()
CANCELLED_MD = _paths.cancelled_md()
SAVED_FOR_LATER_MD = _paths.saved_for_later_md()

# NOTE: directory creation is intentionally NOT done at import time (carried
# minor finding). Callers that mutate state call paths.ensure_data_dirs() /
# create the logs dir lazily inside the write helpers (see log_change()).


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
    """Read all markdown files, regenerate dashboard.html STATE."""
    before, after = read_html_template()
    if before is None:
        print("ERROR: dashboard.html not found or STATE block not parseable")
        return False

    # Gather tasks (deduplicated by first 60 chars of lowercased text)
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

    if DASHBOARD_MD.exists():
        _add_tasks(parse_tasks_from_md(DASHBOARD_MD))

    if DOMAINS_DIR.exists():
        for domain_file in sorted(DOMAINS_DIR.glob("*.md")):
            _add_tasks(parse_tasks_from_md(domain_file), default_domain=domain_file.stem)

    # Projects
    projects = []
    seen_proj = set()
    if PROJECTS_MD.exists():
        for p in parse_projects_from_md(PROJECTS_MD):
            key = p["name"].lower().strip()[:60]
            if key not in seen_proj:
                seen_proj.add(key)
                projects.append(p)

    # Inbox
    inbox = []
    if INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(INBOX_MD))

    # Generate new STATE
    state_js = generate_state_js(projects, all_tasks, inbox)

    # Write updated HTML
    new_html = before + state_js + after
    HTML_FILE.write_text(new_html, encoding="utf-8")

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
    """Append a timestamped line to today's log file."""
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")

    LOGS_DIR.mkdir(exist_ok=True)
    log_file = LOGS_DIR / f"{today}.md"
    if not log_file.exists():
        day_name = datetime.now().strftime("%A")
        log_file.write_text(f"# {today} — {day_name}\n\n## Changes\n", encoding="utf-8")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"- {now} — {message}\n")

    print(f"Logged: {now} — {message}")


def mark_done(task_text):
    """Mark a task as done across all markdown files."""
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
    """Add a new task to DASHBOARD.md and the relevant domain file."""
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

    # Always add to DASHBOARD.md (central hub)
    _insert_in_section(DASHBOARD_MD, ["## Today's Priorities", "## Active Priorities"])

    # Add to the matching domain file (commercial included — was formerly Axmra)
    if DOMAINS_DIR.exists():
        domain_file = DOMAINS_DIR / f"{domain}.md"
        _insert_in_section(domain_file, ["## Active Tasks"])

    log_change(f"Added task: {text} [{domain}] P{priority}")
    rebuild_dashboard()
    print(f"✓ Added: {text} [{domain}] P{priority}")


def capture_inbox(text, domain=""):
    """Add an item to the inbox."""
    today = date.today().isoformat()
    domain_tag = f" [{domain}]" if domain else ""
    line = f"- {today}: {text}{domain_tag}"

    if not INBOX_MD.exists():
        # Fresh/empty data dir: create a minimal inbox so the capture is never
        # silently dropped.
        INBOX_MD.write_text("# Inbox\n\n", encoding="utf-8")
    content = INBOX_MD.read_text(encoding="utf-8")
    content = content.rstrip() + "\n" + line + "\n"
    INBOX_MD.write_text(content, encoding="utf-8")

    log_change(f"Captured to inbox: {text}")
    rebuild_dashboard()
    print(f"✓ Captured: {text}")


def print_status():
    """Print a status summary."""
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
    if PROJECTS_MD.exists():
        projects.extend(parse_projects_from_md(PROJECTS_MD))

    inbox = []
    if INBOX_MD.exists():
        inbox.extend(parse_inbox_from_md(INBOX_MD))

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
        _append_to_archive(CANCELLED_MD, task)
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
        _append_to_archive(SAVED_FOR_LATER_MD, task)
        log_change(f"Saved for later: {task_text}")
        rebuild_dashboard()
        print(f"⏳ Saved for later: {task_text}")
        return True
    print(f"Task not found: {task_text}")
    return False


def restore_task(task_text, from_archive="saved"):
    """Restore a task from an archive back to the active dashboard."""
    archive_file = SAVED_FOR_LATER_MD if from_archive == "saved" else CANCELLED_MD
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
    """Return all markdown files that might contain tasks."""
    files = []
    if DASHBOARD_MD.exists():
        files.append(DASHBOARD_MD)
    if DOMAINS_DIR.exists():
        files.extend(sorted(DOMAINS_DIR.glob("*.md")))
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
