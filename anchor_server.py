#!/usr/bin/env python3
"""
Anchor Dashboard Server
Reads markdown files as the source of truth, serves a live dashboard,
and writes changes back to markdown when edits are made in the browser.

Usage:  python anchor_server.py
Then open http://localhost:5000 in your browser.

File layout (Anchor PSU):
  PROJECTS.md, INBOX.md, DASHBOARD.md, WEEKLY_REVIEW.md   (root)
  domains/academic.md, domains/writing.md, etc.            (subdir)
  logs/2026-04-09.md, etc.                                  (subdir)
"""

import os
import re
import json
import hashlib
import webbrowser
import threading
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, request, send_file, Response

# ── Paths ──────────────────────────────────────────────────────────────
ANCHOR_DIR = Path(__file__).parent.resolve()
PROJECTS_MD = ANCHOR_DIR / "PROJECTS.md"
INBOX_MD = ANCHOR_DIR / "INBOX.md"
DOMAINS_DIR = ANCHOR_DIR / "domains"

app = Flask(__name__)

# ── Markdown Parsers ───────────────────────────────────────────────────

def _field(lines, key):
    """Extract a **Key:** value from a list of lines."""
    for line in lines:
        m = re.match(rf"^-\s+\*\*{key}:\*\*\s*(.+)", line, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""

def parse_projects():
    """Parse PROJECTS.md into a list of project dicts."""
    if not PROJECTS_MD.exists():
        return []
    text = PROJECTS_MD.read_text(encoding="utf-8")
    blocks = re.split(r"^## ", text, flags=re.MULTILINE)[1:]  # skip header
    projects = []
    for i, block in enumerate(blocks):
        lines = block.strip().split("\n")
        name = lines[0].strip()
        rest = lines[1:]
        domain_raw = _field(rest, "Domain").lower()
        # Normalize domains like "academic + commercial crossover"
        domain = domain_raw.split("+")[0].split("&")[0].split("/")[0].strip()
        if domain not in ("academic", "writing", "family", "commercial", "personal"):
            domain = "academic"
        priority_raw = _field(rest, "Priority")
        priority = int(re.search(r"\d+", priority_raw).group()) if re.search(r"\d+", priority_raw) else 2
        status = _field(rest, "Status").split("—")[0].split("–")[0].strip().lower()
        if status not in ("active", "paused", "blocked", "winding down", "completed"):
            status = "active"
        effort_raw = _field(rest, "Effort").lower()
        effort = effort_raw if effort_raw in ("low", "med", "high") else "high"
        due = _field(rest, "Deadline")
        # Try to extract a date from due field
        due_date = ""
        if due:
            m = re.search(r"\d{4}-\d{2}-\d{2}", due)
            if m:
                due_date = m.group()
        next_step = _field(rest, "Next step")
        collabs = _field(rest, "Collaborators")
        notes = _field(rest, "Notes")

        projects.append({
            "id": i + 1,
            "name": name,
            "domain": domain if domain else "academic",
            "priority": priority,
            "status": status,
            "effort": effort,
            "due": due_date,
            "next": next_step,
            "collabs": collabs,
            "notes": notes,
        })
    return projects

def parse_domain_tasks(domain_file):
    """Parse tasks from a domain markdown file — finds ALL checkbox lines."""
    if not domain_file.exists():
        return []
    text = domain_file.read_text(encoding="utf-8")
    tasks = []
    # Find ALL checkbox lines anywhere in the file
    task_lines = re.findall(r"^- \[[ x]\].+$", text, re.MULTILINE)
    task_block = "\n".join(task_lines)
    for line in task_block.strip().split("\n"):
        line = line.strip()
        tm = re.match(r"^- \[([ x])\]\s+\*?\*?(.+?)(?:\*?\*?\s*—|$)", line)
        if not tm:
            tm = re.match(r"^- \[([ x])\]\s+(.+?)(?:\s*—|$)", line)
        if not tm:
            continue
        done = tm.group(1) == "x"
        raw_text = tm.group(2).strip().rstrip("*").strip()

        # Extract metadata from the rest of the line
        priority = 2
        energy = "med"
        due = ""
        pm = re.search(r"Priority:\s*(\d+)", line)
        if pm:
            priority = int(pm.group(1))
        em = re.search(r"Energy:\s*(\w+)", line)
        if em:
            energy = em.group(1).lower()
        dm = re.search(r"Due:\s*(\S+)", line)
        if dm:
            ddm = re.search(r"\d{4}-\d{2}-\d{2}", dm.group(1))
            if ddm:
                due = ddm.group()

        # Check for deadline keywords
        if "DEADLINE" in line.upper() or "DUE" in line.upper():
            date_match = re.search(r"\d{4}-\d{2}-\d{2}", line)
            if date_match:
                due = date_match.group()

        domain_name = domain_file.stem  # academic, writing, family, commercial
        tasks.append({
            "text": raw_text,
            "domain": domain_name,
            "priority": priority,
            "energy": energy,
            "due": due,
            "done": done,
        })
    return tasks

def parse_all_tasks():
    """Parse tasks from all domain files."""
    tasks = []
    task_id = 1
    for domain_file in sorted(DOMAINS_DIR.glob("*.md")):
        for t in parse_domain_tasks(domain_file):
            t["id"] = task_id
            task_id += 1
            tasks.append(t)
    return tasks

def parse_inbox():
    """Parse INBOX.md into list of inbox items."""
    if not INBOX_MD.exists():
        return []
    text = INBOX_MD.read_text(encoding="utf-8")
    items = []
    item_id = 1
    for line in text.split("\n"):
        m = re.match(r"^-\s+(\d{4}-\d{2}-\d{2}):\s+(.+?)(?:\s+\[(\w+)\])?\s*$", line)
        if m:
            domain = m.group(3) or ""
            items.append({
                "id": item_id,
                "text": m.group(2).strip(),
                "date": m.group(1),
                "domain": domain.lower(),
            })
            item_id += 1
    return items

def build_state():
    """Build the full STATE object from markdown files."""
    projects = parse_projects()
    tasks = parse_all_tasks()
    inbox = parse_inbox()
    return {
        "projects": projects,
        "tasks": tasks,
        "inbox": inbox,
        "nextId": {
            "projects": max((p["id"] for p in projects), default=0) + 1,
            "tasks": max((t["id"] for t in tasks), default=0) + 1,
            "inbox": max((i["id"] for i in inbox), default=0) + 1,
        },
    }

# ── File Fingerprint (for change detection) ────────────────────────────

def md_fingerprint():
    """Hash all markdown files to detect external changes."""
    h = hashlib.md5()
    for f in sorted([PROJECTS_MD, INBOX_MD] + sorted(DOMAINS_DIR.glob("*.md"))):
        if f.exists():
            h.update(f.read_bytes())
    return h.hexdigest()

_last_fingerprint = {"value": ""}

# ── Markdown Writers ───────────────────────────────────────────────────

def write_projects(projects):
    """Write projects list back to PROJECTS.md."""
    lines = ["# Active Projects\n"]
    for p in projects:
        lines.append(f"\n## {p['name']}")
        lines.append(f"- **Domain:** {p['domain']}")
        lines.append(f"- **Status:** {p['status']}")
        lines.append(f"- **Priority:** {p['priority']}")
        if p.get("next"):
            lines.append(f"- **Next step:** {p['next']}")
        if p.get("due"):
            lines.append(f"- **Deadline:** {p['due']}")
        if p.get("effort"):
            lines.append(f"- **Effort:** {p['effort']}")
        if p.get("collabs"):
            lines.append(f"- **Collaborators:** {p['collabs']}")
        if p.get("notes"):
            lines.append(f"- **Notes:** {p['notes']}")
        lines.append("")
    PROJECTS_MD.write_text("\n".join(lines), encoding="utf-8")

def write_inbox(inbox):
    """Write inbox items back to INBOX.md."""
    lines = [
        "# Inbox",
        "<!-- Drop anything here. Anchor sorts it during reviews. -->",
        "",
    ]
    for item in inbox:
        domain_tag = f" [{item['domain']}]" if item.get("domain") else ""
        lines.append(f"- {item['date']}: {item['text']}{domain_tag}")
    lines.append("")
    INBOX_MD.write_text("\n".join(lines), encoding="utf-8")

def write_domain_tasks(domain, tasks):
    """Update the Active Tasks section in a domain file."""
    domain_file = DOMAINS_DIR / f"{domain}.md"
    if not domain_file.exists():
        return

    text = domain_file.read_text(encoding="utf-8")
    domain_tasks = [t for t in tasks if t["domain"] == domain]

    # Build new task block
    task_lines = []
    for t in domain_tasks:
        check = "x" if t.get("done") else " "
        meta_parts = []
        if t.get("priority"):
            meta_parts.append(f"Priority: {t['priority']}")
        if t.get("energy"):
            meta_parts.append(f"Energy: {t['energy']}")
        if t.get("due"):
            meta_parts.append(f"Due: {t['due']}")
        if t.get("done"):
            meta_parts.append("DONE")
        meta = " — ".join(meta_parts)
        task_lines.append(f"- [{check}] **{t['text']}** — {meta}")

    new_block = "\n".join(task_lines)

    # Replace the Active Tasks section
    pattern = r"(## Active Tasks.*?\n)((?:- \[[ x]\].*\n?)+)"
    if re.search(pattern, text, re.IGNORECASE):
        text = re.sub(pattern, rf"\g<1>{new_block}\n", text, flags=re.IGNORECASE)
    else:
        # Insert after first heading
        text = re.sub(
            r"(# .+\n)",
            rf"\1\n## Active Tasks (by urgency)\n{new_block}\n",
            text,
            count=1,
        )
    domain_file.write_text(text, encoding="utf-8")

# ── State Cache (for fast reads + external change detection) ───────────

_state = {"data": None}

def get_state():
    """Return current state, re-parsing markdown if files changed."""
    fp = md_fingerprint()
    if fp != _last_fingerprint["value"] or _state["data"] is None:
        _state["data"] = build_state()
        _last_fingerprint["value"] = fp
    return _state["data"]

def save_state(state):
    """Save state back to markdown files and update cache."""
    write_projects(state["projects"])
    write_inbox(state["inbox"])
    # Write tasks per domain
    domains_seen = set()
    for t in state["tasks"]:
        domains_seen.add(t["domain"])
    for domain in domains_seen:
        write_domain_tasks(domain, state["tasks"])
    _state["data"] = state
    _last_fingerprint["value"] = md_fingerprint()

# ── Flask Routes ───────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the live dashboard HTML."""
    # Try dashboard_api.html first, fall back to dashboard_live.html
    for name in ["dashboard_api.html", "dashboard_live.html"]:
        html_path = ANCHOR_DIR / name
        if html_path.exists():
            return send_file(html_path, mimetype="text/html")
    return "No dashboard HTML found", 404

@app.route("/api/state")
def api_state():
    """Return the current state as JSON."""
    return jsonify(get_state())

@app.route("/api/fingerprint")
def api_fingerprint():
    """Return current markdown fingerprint for polling."""
    return jsonify({"fingerprint": md_fingerprint()})

@app.route("/api/task/toggle", methods=["POST"])
def api_task_toggle():
    data = request.json
    state = get_state()
    task = next((t for t in state["tasks"] if t["id"] == data["id"]), None)
    if task:
        task["done"] = not task["done"]
        save_state(state)
    return jsonify({"ok": True})

@app.route("/api/task/add", methods=["POST"])
def api_task_add():
    data = request.json
    state = get_state()
    state["tasks"].append({
        "id": state["nextId"]["tasks"],
        "text": data["text"],
        "domain": data.get("domain", "academic"),
        "priority": int(data.get("priority", 2)),
        "energy": data.get("energy", "med"),
        "due": data.get("due", ""),
        "done": False,
    })
    state["nextId"]["tasks"] += 1
    save_state(state)
    return jsonify({"ok": True})

@app.route("/api/task/delete", methods=["POST"])
def api_task_delete():
    data = request.json
    state = get_state()
    state["tasks"] = [t for t in state["tasks"] if t["id"] != data["id"]]
    save_state(state)
    return jsonify({"ok": True})

@app.route("/api/project/save", methods=["POST"])
def api_project_save():
    data = request.json
    state = get_state()
    edit_id = data.get("editId")
    proj_data = {
        "name": data["name"],
        "domain": data.get("domain", "academic"),
        "priority": int(data.get("priority", 3)),
        "status": data.get("status", "active"),
        "effort": data.get("effort", "high"),
        "due": data.get("due", ""),
        "next": data.get("next", ""),
        "collabs": data.get("collabs", ""),
        "notes": data.get("notes", ""),
    }
    if edit_id:
        proj = next((p for p in state["projects"] if p["id"] == int(edit_id)), None)
        if proj:
            proj.update(proj_data)
    else:
        proj_data["id"] = state["nextId"]["projects"]
        state["nextId"]["projects"] += 1
        state["projects"].append(proj_data)
    save_state(state)
    return jsonify({"ok": True})

@app.route("/api/project/delete", methods=["POST"])
def api_project_delete():
    data = request.json
    state = get_state()
    state["projects"] = [p for p in state["projects"] if p["id"] != data["id"]]
    save_state(state)
    return jsonify({"ok": True})

@app.route("/api/inbox/add", methods=["POST"])
def api_inbox_add():
    data = request.json
    state = get_state()
    state["inbox"].append({
        "id": state["nextId"]["inbox"],
        "text": data["text"],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "domain": data.get("domain", ""),
    })
    state["nextId"]["inbox"] += 1
    save_state(state)
    return jsonify({"ok": True})

@app.route("/api/inbox/delete", methods=["POST"])
def api_inbox_delete():
    data = request.json
    state = get_state()
    state["inbox"] = [i for i in state["inbox"] if i["id"] != data["id"]]
    save_state(state)
    return jsonify({"ok": True})

@app.route("/api/inbox/promote", methods=["POST"])
def api_inbox_promote():
    data = request.json
    state = get_state()
    item = next((i for i in state["inbox"] if i["id"] == data["id"]), None)
    if item:
        state["tasks"].append({
            "id": state["nextId"]["tasks"],
            "text": item["text"],
            "domain": item.get("domain") or "personal",
            "priority": 2,
            "energy": "med",
            "due": "",
            "done": False,
        })
        state["nextId"]["tasks"] += 1
        state["inbox"] = [i for i in state["inbox"] if i["id"] != data["id"]]
        save_state(state)
    return jsonify({"ok": True})

# ── Main ───────────────────────────────────────────────────────────────

def open_browser():
    """Open browser after a short delay to let Flask start."""
    import time
    time.sleep(1.2)
    webbrowser.open("http://localhost:5000")

if __name__ == "__main__":
    print("\n  ⚓  Anchor Dashboard Server")
    print("  ─────────────────────────────")
    print(f"  Markdown source: {ANCHOR_DIR}")
    print(f"  Dashboard:       http://localhost:5000\n")
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False)
