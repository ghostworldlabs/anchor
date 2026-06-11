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
    python3 anchor.py link "task text" --project <id>   # Link a task to an R&D project
    python3 anchor.py status             # Print current status summary

R&D control-surface mirror (v2 — delegates to the shared modules):
    python3 anchor.py rnd sessions <project_id> --lane planning
    python3 anchor.py rnd status <project_id>
    python3 anchor.py rnd reconcile <project_id> [--apply]   # default = dry-run preview
    python3 anchor.py rnd add-idea <project_id> "idea text" [--notes "..."]
    python3 anchor.py rnd promote-inbox <project_id> "inbox item text"
    python3 anchor.py rnd pin-deliverable <project_id> <path> [--name N] [--type doc|script|skill|program] [--desc "..."]
    python3 anchor.py rnd set-blurb <project_id> "what this project is"
    python3 anchor.py rnd regenerate-summary <project_id> --lane planning --session <session_id>
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
            # Extract the optional Project: <id> link (Wave 3; no-op until Wave 9).
            proj_m = re.search(r'Project:\s*([^\s—]+)', meta, re.I)
            project = proj_m.group(1).strip() if proj_m else ""
            # Extract notes
            notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|Project|\[)|$)', meta, re.I)
            if not notes_m:
                notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
            notes = notes_m.group(1).strip().rstrip(' —') if notes_m else ""
            # Clean text
            clean = re.sub(r'\s*—\s*Priority:.*', '', raw_text)
            clean = re.sub(r'\s*—\s*\[.*', '', clean)
            clean = re.sub(r'\s*—\s*energy:.*', '', clean, flags=re.I)
            clean = re.sub(r'\s*—\s*Notes:.*', '', clean, flags=re.I)
            clean = re.sub(r'\s*—\s*Project:.*', '', clean, flags=re.I)
            clean = clean.strip(' *')
            tasks.append({
                "text": clean,
                "done": done,
                "priority": priority,
                "energy": energy,
                "domain": domain,
                "due": due,
                "notes": notes,
                "project": project,
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


def link_task(task_text, project_id):
    """Link a task to an R&D project — set/maintain its ``Project: <id>`` field.

    Wave 9 ACTIVATES the ``Project:`` field that Wave 3 parsed as a no-op. This
    edits ONLY that field, surgically, on the first matching active task line:

    - If the line has no ``Project:`` field, append ``" — Project: <id>"`` to it.
    - If it already has one, replace just the ``<id>`` in place.
    - Passing an empty ``project_id`` REMOVES the field (unlink).

    Every other character of the user's markdown line is preserved verbatim, so
    a task without the field that is not being touched stays byte-stable, and a
    task with the field round-trips cleanly through parse/serialize + the
    healthcheck parse path. Returns True if a task was updated.
    """
    search = task_text.lower().strip()
    new_id = (project_id or "").strip()
    found = False

    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = md_file.read_text(encoding="utf-8")
        new_lines = []
        changed = False
        for line in text.splitlines():
            if (not found and re.match(r'\s*-\s*\[([ xX])\]', line)
                    and search in line.lower()):
                existing = re.search(r'(\s*—\s*Project:\s*)([^\s—]+)', line, re.I)
                if existing:
                    if new_id:
                        # Replace just the id; keep surrounding text untouched.
                        new_line = (line[:existing.start(2)] + new_id
                                    + line[existing.end(2):])
                    else:
                        # Unlink: drop the whole " — Project: <id>" segment.
                        new_line = line[:existing.start(1)] + line[existing.end(2):]
                else:
                    if new_id:
                        new_line = line.rstrip() + f" — Project: {new_id}"
                    else:
                        new_line = line  # nothing to remove
                if new_line != line:
                    changed = True
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)
        if changed:
            md_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    if found:
        if new_id:
            log_change(f"Linked task '{task_text}' to project {new_id}")
            print(f"✓ Linked: {task_text} → project {new_id}")
        else:
            log_change(f"Unlinked task '{task_text}' from its project")
            print(f"✓ Unlinked: {task_text}")
        rebuild_dashboard()
    else:
        print(f"Task not found: {task_text}")
    return found


def _all_md_files():
    """Return all markdown files that might contain tasks."""
    files = []
    if DASHBOARD_MD.exists():
        files.append(DASHBOARD_MD)
    if DOMAINS_DIR.exists():
        files.extend(sorted(DOMAINS_DIR.glob("*.md")))
    return files


# ── R&D Grass Catchers content feeds (Wave 5 mirror) ───────────────────────

def add_idea(folder_path, project_id, text, notes=""):
    """CLI mirror of ``effort_history.add_idea`` — manual Grass Catchers idea.

    Records a real Anchor-created idea card on the project's grass lane.
    Delegates to the single source of truth in ``effort_history`` so the GUI and
    CLI never diverge. Returns the stored pointer-record.
    """
    import effort_history as _eh
    return _eh.add_idea(folder_path, project_id, text, notes=notes)


def promote_inbox(folder_path, project_id, inbox_item_text):
    """CLI mirror of ``effort_history.promote_inbox`` — promote an INBOX item.

    Reads the existing ``INBOX.md`` with this module's ``parse_inbox_from_md``
    (no new format) and copies the matching item into the project's Grass
    Catchers lane (copy-by-default — the inbox item is NOT removed). Returns the
    stored grass pointer-record. Raises ``ValueError`` if no item matches.
    """
    import effort_history as _eh
    inbox_items = parse_inbox_from_md(INBOX_MD)
    return _eh.promote_inbox(folder_path, project_id, inbox_item_text,
                             inbox_items=inbox_items)


# ── R&D v2 surface mirror (Wave 8) ─────────────────────────────────────────
# These delegate (never duplicate logic) to the shared v2 modules so the CLI
# and the GUI/API stay byte-for-byte consistent. Each resolves a project by id
# via ``rnd_registry`` and forwards to ``sessions`` / ``rnd_registry`` /
# ``effort_history`` / ``deliverables`` / ``summarizer``.

def _rnd_resolve(project_id):
    """Return ``(project_entry, folder_path)`` for an R&D project id.

    Raises ``KeyError`` (with a clean message) for an unknown id so callers can
    print a friendly error rather than a traceback.
    """
    import rnd_registry as _rnd
    proj = _rnd.get_project(project_id)
    if proj is None:
        raise KeyError(project_id)
    return proj, proj.get("folder_path", "")


def rnd_list_sessions(project_id, lane):
    """CLI mirror of ``sessions.list_sessions`` — one trio run = one session.

    Returns the lane's sessions newest-first (delegates to ``sessions``).
    """
    import sessions as _sessions
    _proj, folder = _rnd_resolve(project_id)
    return _sessions.list_sessions(folder, project_id, lane)


def rnd_status_line(project_id):
    """CLI mirror of ``rnd_registry.status_line`` — per-lane counts + provenance."""
    import rnd_registry as _rnd
    # Validate the id (status_line is best-effort and returns zeros for unknown).
    _rnd_resolve(project_id)
    return _rnd.status_line(project_id)


def rnd_reconcile(project_id, apply=False):
    """CLI mirror of ``rnd_registry.reconcile_folder`` — preview (dry-run) / apply.

    With ``apply=False`` (default) returns the PLAN of what folding+deleting would
    do WITHOUT mutating anything; with ``apply=True`` folds same-folder siblings'
    real sessions into the active id, then hard-deletes them.
    """
    import rnd_registry as _rnd
    return _rnd.reconcile_folder(project_id, apply=apply)


def rnd_set_blurb(project_id, blurb):
    """CLI mirror of ``rnd_registry.set_blurb`` — the project's 'what this is' line."""
    import rnd_registry as _rnd
    _rnd_resolve(project_id)
    return _rnd.set_blurb(project_id, blurb)


def rnd_pin_deliverable(project_id, path, name=None, dtype=None, description=""):
    """CLI mirror of ``deliverables.pin_deliverable`` — pin any path as a deliverable.

    Surfaces a file (e.g. ``anchor_gui.py`` at repo root) as a deliverables-lane
    effort even though it is not under a ``deliverables/`` directory.
    """
    import deliverables as _deliv
    _proj, folder = _rnd_resolve(project_id)
    return _deliv.pin_deliverable(folder, project_id, path, name=name,
                                  dtype=dtype, description=description)


def rnd_regenerate_summary(project_id, lane, session_id):
    """CLI mirror of ``summarizer.summarize_session(force=True)`` — re-cache a summary.

    Re-runs the validated summarizer (through the runner seam — ``ANCHOR_RUNNER_CMD``)
    for one session and overwrites its cached ``summary.json`` / ``summary.md``.
    Raises ``KeyError`` for an unknown project and ``ValueError`` for an unknown
    session so the CLI can report a clean error.
    """
    import sessions as _sessions
    import summarizer as _summarizer
    _proj, folder = _rnd_resolve(project_id)
    session = None
    for s in _sessions.list_sessions(folder, project_id, lane):
        if s.get("session_id") == session_id:
            session = s
            break
    if session is None:
        raise ValueError(f"unknown session: {session_id}")
    return _summarizer.summarize_session(folder, project_id, lane, session,
                                         force=True)


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

    elif cmd == "link":
        # anchor.py link "task text" --project <id>   (or --unlink to remove)
        if len(sys.argv) < 3:
            print("Usage: anchor.py link \"task text\" --project <id> | --unlink")
            return
        text_parts = []
        project_id = ""
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--project" and i + 1 < len(sys.argv):
                project_id = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--unlink":
                project_id = ""; i += 1
            else:
                text_parts.append(sys.argv[i]); i += 1
        link_task(" ".join(text_parts), project_id)

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

    elif cmd == "rnd":
        _rnd_cli(sys.argv[2:])

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)


# ── R&D CLI dispatcher (Wave 8) ────────────────────────────────────────────

def _rnd_cli(args):
    """Dispatch ``anchor.py rnd <subcommand> ...`` to the v2 mirror functions.

    Follows anchor.py's existing manual-arg-parsing convention (no argparse).
    Each subcommand resolves a project by id and delegates to the shared module;
    no R&D logic is reimplemented here.
    """
    if not args:
        print("Usage: anchor.py rnd <sessions|status|reconcile|add-idea|"
              "promote-inbox|pin-deliverable|set-blurb|regenerate-summary> ...")
        return
    sub = args[0].lower()
    rest = args[1:]

    def _opt(name, default=None):
        if name in rest:
            i = rest.index(name)
            if i + 1 < len(rest):
                return rest[i + 1]
        return default

    def _flag(name):
        return name in rest

    def _positionals():
        """Positional args = everything not consumed by a --flag or its value."""
        out = []
        skip = False
        for i, a in enumerate(rest):
            if skip:
                skip = False
                continue
            if a.startswith("--"):
                # flags that take a value consume the next token
                if a in ("--lane", "--session", "--notes", "--name",
                         "--type", "--desc"):
                    skip = True
                continue
            out.append(a)
        return out

    try:
        if sub == "sessions":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd sessions <project_id> --lane <lane>")
                return
            lane = _opt("--lane", "planning")
            sessions = rnd_list_sessions(pos[0], lane)
            print(f"{len(sessions)} session(s) in lane '{lane}':")
            for s in sessions:
                prov = s.get("provenance", "")
                n = len(s.get("member_files", []))
                print(f"  - [{prov}] {s.get('title','(untitled)')} "
                      f"— {n} file(s) - id={s.get('session_id','')}")

        elif sub == "status":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd status <project_id>")
                return
            sl = rnd_status_line(pos[0])
            print(f"Status line for {pos[0]}:")
            for lane, counts in sl.items():
                print(f"  {lane:<13} count={counts.get('count',0)} "
                      f"imported={counts.get('imported',0)} "
                      f"running={counts.get('running',0)}")

        elif sub == "reconcile":
            pos = _positionals()
            if not pos:
                print("Usage: anchor.py rnd reconcile <project_id> [--apply]")
                return
            apply = _flag("--apply")
            report = rnd_reconcile(pos[0], apply=apply)
            if not report.get("ok"):
                print(f"Reconcile failed: {report.get('reason')}")
                return
            mode = "APPLIED" if report.get("applied") else "PREVIEW (dry-run)"
            print(f"Reconcile {mode} for {report.get('active_id')} "
                  f"(folder: {report.get('folder_path')})")
            for f in report.get("fold", []):
                print(f"  fold {f['id']} ({f.get('name','')}): "
                      f"{f.get('total_efforts',0)} effort(s) {f.get('efforts',{})}")
            print(f"  to_delete: {report.get('to_delete', [])}")
            if report.get("applied"):
                print(f"  imported: {report.get('imported',0)}  "
                      f"deleted: {report.get('deleted', [])}")

        elif sub == "add-idea":
            pos = _positionals()
            if len(pos) < 2:
                print('Usage: anchor.py rnd add-idea <project_id> "idea text" '
                      '[--notes "..."]')
                return
            _proj, folder = _rnd_resolve(pos[0])
            rec = add_idea(folder, pos[0], " ".join(pos[1:]),
                           notes=_opt("--notes", ""))
            print(f"OK: Idea added to grass lane: {rec.get('title','')} "
                  f"(job_id={rec.get('job_id','')})")

        elif sub == "promote-inbox":
            pos = _positionals()
            if len(pos) < 2:
                print('Usage: anchor.py rnd promote-inbox <project_id> '
                      '"inbox item text"')
                return
            _proj, folder = _rnd_resolve(pos[0])
            rec = promote_inbox(folder, pos[0], " ".join(pos[1:]))
            print(f"OK: Promoted INBOX item to grass lane: {rec.get('title','')}")

        elif sub == "pin-deliverable":
            pos = _positionals()
            if len(pos) < 2:
                print("Usage: anchor.py rnd pin-deliverable <project_id> <path> "
                      "[--name N] [--type doc|script|skill|program] [--desc ...]")
                return
            rec = rnd_pin_deliverable(pos[0], pos[1], name=_opt("--name"),
                                      dtype=_opt("--type"),
                                      description=_opt("--desc", ""))
            print(f"OK: Pinned deliverable: {rec.get('title','')} "
                  f"[{rec.get('deliverable_type','')}] -> {rec.get('artifact_path','')}")

        elif sub == "set-blurb":
            pos = _positionals()
            if len(pos) < 2:
                print('Usage: anchor.py rnd set-blurb <project_id> "blurb text"')
                return
            entry = rnd_set_blurb(pos[0], " ".join(pos[1:]))
            print(f"OK: Blurb set: {entry.get('blurb','')}")

        elif sub == "regenerate-summary":
            pos = _positionals()
            lane = _opt("--lane")
            session_id = _opt("--session")
            if not pos or not lane or not session_id:
                print("Usage: anchor.py rnd regenerate-summary <project_id> "
                      "--lane <lane> --session <session_id>")
                return
            summary = rnd_regenerate_summary(pos[0], lane, session_id)
            claims = summary.get("claims", [])
            print(f"OK: Summary regenerated for session {session_id}: "
                  f"{len(claims)} grounded claim(s)")

        else:
            print(f"Unknown rnd subcommand: {sub}")
            print(__doc__)
    except KeyError as ke:
        print(f"Unknown project: {ke.args[0] if ke.args else ke}")
    except ValueError as ve:
        print(f"Error: {ve}")


if __name__ == "__main__":
    main()
