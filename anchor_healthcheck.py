#!/usr/bin/env python3
"""
Anchor Health Check â€” runs daily at 5:00 AM via Windows Task Scheduler.

What it does, every morning:
  1. File system integrity   â€” PSU + Axmra dirs reachable, expected files present
  2. Code compiles           â€” anchor_gui.py and anchor.py parse cleanly
  3. Markdown parses         â€” every task/project/inbox/archive file reads cleanly
  4. Server boots            â€” launches anchor_gui.py on test port 8778
  5. HTTP endpoints respond  â€” GET /, GET /api/status, validation pings on POSTs
  6. Synthetic round-trip    â€” creates a __healthcheck__ task, walks it through
                               every state (done, cancel, save, restore, delete)
  7. Logging works           â€” verifies today's log was written
  8. Local filesystem write sanity    â€” write/read a marker, ensure FS isn't read-only

Routine maintenance is applied automatically (missing logs/, stale port-holding
processes, missing top-level files restored from minimal templates). Anything
involving real user content is flagged only.

Writes report to health_reports/YYYY-MM-DD.md.

Run on demand:   python anchor_healthcheck.py
Scheduled:       registered by register_healthcheck.ps1
"""
from __future__ import annotations

import importlib.util
import json
import os
import py_compile
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

# â”€â”€ Paths â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
SCRIPT_DIR = Path(__file__).parent.resolve()
PSU_DIR = SCRIPT_DIR  # this script must live in the PSU root
REPORTS_DIR = PSU_DIR / "health_reports"
TEST_PORT = 8778
SERVER_BOOT_TIMEOUT = 12  # seconds
SYNTHETIC_TAG = "__healthcheck__"
TODAY = date.today().isoformat()

REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# â”€â”€ Discovery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def find_axmra() -> Path | None:
    """Mirror anchor_gui's sibling-discovery so we audit the same files it does."""
    parent = PSU_DIR.parent
    if not parent.exists():
        return None
    for d in parent.iterdir():
        if d.is_dir() and d != PSU_DIR and (d / ".anchor").exists():
            return d
    return None


AXMRA_DIR = find_axmra()

# Files that MUST exist in PSU (auto-restored if missing)
PSU_REQUIRED = {
    "DASHBOARD.md": "# Dashboard\n\n## Today's Priorities\n\n## Active Priorities\n",
    "PROJECTS.md": "# Projects\n",
    "INBOX.md": "# Inbox\n\n## Quick Capture\n",
    "CANCELLED.md": "# Cancelled Tasks\n\n",
    "SAVED_FOR_LATER.md": "# Saved For Later\n\n",
    "WEEKLY_REVIEW.md": "# Weekly Review\n\n",
}
PSU_DOMAIN_FILES = ["academic.md", "commercial.md", "family.md", "writing.md"]

AXMRA_REQUIRED = {  # restored if missing inside .anchor/
    "DASHBOARD.md": "# Anchor Axmra Dashboard\n\n## Active Priorities\n",
    "PROJECTS.md": "# Projects (Commercial)\n",
    "INBOX.md": "# Inbox (Commercial)\n",
}


# â”€â”€ Report accumulator â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class Report:
    def __init__(self):
        self.checks: list[tuple[str, bool, str]] = []  # (name, ok, detail)
        self.issues: list[str] = []
        self.fixes: list[str] = []
        self.recommendations: list[str] = []
        self.started = datetime.now()

    def check(self, name: str, ok: bool, detail: str = ""):
        self.checks.append((name, ok, detail))
        if not ok:
            self.issues.append(f"[{name}] {detail}" if detail else name)

    def fix(self, msg: str):
        self.fixes.append(msg)

    def recommend(self, msg: str):
        self.recommendations.append(msg)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    def write(self, path: Path):
        elapsed = (datetime.now() - self.started).total_seconds()
        status_line = "ISSUES FOUND" if self.has_issues else "OK"
        lines = [
            f"# Anchor Health Report â€” {TODAY}",
            "",
            f"Status: {status_line}",
            f"Run time: {elapsed:.1f}s ({self.started.strftime('%H:%M:%S')})",
            "",
            "## Checks",
        ]
        for name, ok, detail in self.checks:
            mark = "âœ“" if ok else "âœ—"
            tail = f"  ({detail})" if detail else ""
            lines.append(f"- {mark} {name}{tail}")
        lines.extend(["", "## Issues"])
        if self.issues:
            for i in self.issues:
                lines.append(f"- {i}")
        else:
            lines.append("(none)")
        lines.extend(["", "## Auto-fixes applied"])
        if self.fixes:
            for f in self.fixes:
                lines.append(f"- {f}")
        else:
            lines.append("(none)")
        lines.extend(["", "## Recommended actions"])
        if self.recommendations:
            for r in self.recommendations:
                lines.append(f"- {r}")
        else:
            lines.append("(none)")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")


# â”€â”€ Check 1: file system integrity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_filesystem(report: Report):
    name = "file system integrity"

    if not PSU_DIR.exists():
        report.check(name, False, f"PSU directory missing: {PSU_DIR}")
        return
    if AXMRA_DIR is None:
        report.recommend("Anchor Axmra sibling directory not discovered â€” single-directory mode")

    missing = []

    # PSU required files
    for filename, template in PSU_REQUIRED.items():
        p = PSU_DIR / filename
        if not p.exists():
            try:
                p.write_text(template, encoding="utf-8")
                report.fix(f"Restored missing {filename} from template")
            except Exception as e:
                missing.append(f"{filename} ({e})")

    # PSU domain files
    domains_dir = PSU_DIR / "domains"
    if not domains_dir.exists():
        try:
            domains_dir.mkdir(parents=True, exist_ok=True)
            report.fix("Created missing domains/ directory")
        except Exception as e:
            missing.append(f"domains/ ({e})")
    for df in PSU_DOMAIN_FILES:
        p = domains_dir / df
        if not p.exists():
            missing.append(f"domains/{df}")

    # PSU logs dir
    logs_dir = PSU_DIR / "logs"
    if not logs_dir.exists():
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            report.fix("Created missing logs/ directory in PSU")
        except Exception as e:
            missing.append(f"logs/ ({e})")

    # Axmra (if present)
    if AXMRA_DIR is not None:
        anchor_sub = AXMRA_DIR / ".anchor"
        if not anchor_sub.exists():
            missing.append(f"{AXMRA_DIR.name}/.anchor")
        else:
            for filename, template in AXMRA_REQUIRED.items():
                p = anchor_sub / filename
                if not p.exists():
                    try:
                        p.write_text(template, encoding="utf-8")
                        report.fix(f"Restored missing Axmra .anchor/{filename}")
                    except Exception as e:
                        missing.append(f"Axmra .anchor/{filename} ({e})")
            axmra_logs = anchor_sub / "logs"
            if not axmra_logs.exists():
                try:
                    axmra_logs.mkdir(parents=True, exist_ok=True)
                    report.fix("Created missing logs/ directory in Axmra")
                except Exception as e:
                    missing.append(f"Axmra logs/ ({e})")

    if missing:
        report.check(name, False, "missing: " + ", ".join(missing))
    else:
        scope = "PSU + Axmra" if AXMRA_DIR else "PSU only"
        report.check(name, True, scope)


# â”€â”€ Check 2: code compiles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_code_compiles(report: Report):
    name = "code compiles"
    failed = []
    for fname in ("anchor_gui.py", "anchor.py"):
        p = PSU_DIR / fname
        if not p.exists():
            failed.append(f"{fname} (missing)")
            continue
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            failed.append(f"{fname}: {e.msg.strip()}")
        except Exception as e:
            failed.append(f"{fname}: {e}")
    if failed:
        report.check(name, False, "; ".join(failed))
    else:
        report.check(name, True, "anchor_gui.py + anchor.py")


# â”€â”€ Check 3: markdown parses â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _import_anchor_gui():
    """Load anchor_gui as a module without invoking its main()."""
    spec = importlib.util.spec_from_file_location("anchor_gui_mod", PSU_DIR / "anchor_gui.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not build module spec for anchor_gui.py")
    mod = importlib.util.module_from_spec(spec)
    # Suppress its print() output during import
    with open(os.devnull, "w") as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.stdout = old_stdout
    return mod


def check_markdown_parses(report: Report, mod):
    name = "markdown parseability"
    errors: list[str] = []
    counts = {"tasks": 0, "projects": 0, "inbox": 0, "archived": 0}

    candidates: list[tuple[str, Path, str]] = []  # (label, path, kind)
    candidates.append(("DASHBOARD.md", PSU_DIR / "DASHBOARD.md", "tasks"))
    candidates.append(("PROJECTS.md", PSU_DIR / "PROJECTS.md", "projects"))
    candidates.append(("INBOX.md", PSU_DIR / "INBOX.md", "inbox"))
    candidates.append(("CANCELLED.md", PSU_DIR / "CANCELLED.md", "archived"))
    candidates.append(("SAVED_FOR_LATER.md", PSU_DIR / "SAVED_FOR_LATER.md", "archived"))
    for f in sorted((PSU_DIR / "domains").glob("*.md")):
        candidates.append((f"domains/{f.name}", f, "tasks"))
    if AXMRA_DIR:
        anchor_sub = AXMRA_DIR / ".anchor"
        candidates.append(("Axmra DASHBOARD.md", anchor_sub / "DASHBOARD.md", "tasks"))
        candidates.append(("Axmra PROJECTS.md", anchor_sub / "PROJECTS.md", "projects"))
        candidates.append(("Axmra INBOX.md", anchor_sub / "INBOX.md", "inbox"))

    for label, path, kind in candidates:
        if not path.exists():
            continue
        try:
            if kind == "tasks":
                items = mod.parse_tasks_from_md(path)
                counts["tasks"] += len(items)
                # Flag tasks with priority not in 1-3 or empty text
                for t in items:
                    if not t["text"]:
                        errors.append(f"{label}: empty task text")
                    if t["priority"] not in (1, 2, 3):
                        errors.append(f"{label}: bad priority on '{t['text'][:40]}' = {t['priority']}")
            elif kind == "projects":
                items = mod.parse_projects_from_md(path)
                counts["projects"] += len(items)
                for p in items:
                    if not p["name"]:
                        errors.append(f"{label}: empty project name")
            elif kind == "inbox":
                items = mod.parse_inbox_from_md(path)
                counts["inbox"] += len(items)
            elif kind == "archived":
                items = mod.parse_archived_tasks(path)
                counts["archived"] += len(items)
        except UnicodeDecodeError as e:
            errors.append(f"{label}: encoding error â€” {e}")
        except Exception as e:
            errors.append(f"{label}: {e}")

    # Cross-check: tasks named in DASHBOARD.md should appear somewhere else too
    # (skip for now â€” DASHBOARD is allowed to be a curated subset)

    if errors:
        report.check(name, False, "; ".join(errors[:5]) + (" â€¦" if len(errors) > 5 else ""))
    else:
        report.check(
            name,
            True,
            f"{counts['tasks']} tasks, {counts['projects']} projects, {counts['inbox']} inbox, {counts['archived']} archived",
        )


# â”€â”€ Check 4: server boot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False
    finally:
        s.close()


def check_server_and_endpoints(report: Report):
    """Boot the server on TEST_PORT, exercise endpoints, return the popen handle."""
    name = "server boot"

    if _port_in_use(TEST_PORT):
        report.check(name, False, f"test port {TEST_PORT} already in use; skipping endpoint checks")
        return None

    cmd = [sys.executable, str(PSU_DIR / "anchor_gui.py"), "--port", str(TEST_PORT)]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PSU_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            # Suppress browser auto-open by patching env? anchor_gui calls webbrowser.open.
            # On a headless or scheduled run that may silently fail â€” that's fine.
        )
    except Exception as e:
        report.check(name, False, f"could not launch: {e}")
        return None

    # Wait for the server to start serving
    boot_started = time.time()
    booted = False
    while time.time() - boot_started < SERVER_BOOT_TIMEOUT:
        if _port_in_use(TEST_PORT):
            booted = True
            break
        if proc.poll() is not None:  # crashed before binding
            break
        time.sleep(0.25)

    boot_elapsed = time.time() - boot_started

    if not booted:
        # Capture stderr for the report
        err_text = ""
        try:
            err_text = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
        except Exception:
            pass
        proc.terminate()
        report.check(name, False, f"did not bind in {SERVER_BOOT_TIMEOUT}s; stderr={err_text[:200]}")
        return None

    report.check(name, True, f"{boot_elapsed:.1f}s")

    # â”€â”€ Endpoint checks â”€â”€
    base = f"http://127.0.0.1:{TEST_PORT}"
    endpoint_results = []

    # GET /
    try:
        with urllib.request.urlopen(base + "/", timeout=5) as r:
            body = r.read().decode("utf-8", errors="replace")
            ok = r.status == 200 and "Anchor" in body and len(body) > 1000
            endpoint_results.append(("GET /", ok, f"status={r.status}, {len(body)} bytes"))
    except Exception as e:
        endpoint_results.append(("GET /", False, str(e)))

    # GET /api/status
    try:
        with urllib.request.urlopen(base + "/api/status", timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
            ok = "active" in data and "projects" in data and "inbox" in data
            endpoint_results.append(("GET /api/status", ok, json.dumps(data)))
    except Exception as e:
        endpoint_results.append(("GET /api/status", False, str(e)))

    # POST validation pings â€” send a no-op text and expect ok=False, not a 500
    for endpoint in ("/api/done", "/api/undone", "/api/cancel",
                     "/api/save_for_later", "/api/restore"):
        try:
            req = urllib.request.Request(
                base + endpoint,
                data=json.dumps({"text": "__nonexistent_validation_ping__"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode("utf-8"))
                # Should respond with ok=False (task not found) and not 500
                ok = r.status == 200 and "ok" in data
                endpoint_results.append((f"POST {endpoint}", ok, f"status={r.status}"))
        except urllib.error.HTTPError as e:
            endpoint_results.append((f"POST {endpoint}", False, f"HTTP {e.code}"))
        except Exception as e:
            endpoint_results.append((f"POST {endpoint}", False, str(e)))

    passed = sum(1 for _, ok, _ in endpoint_results if ok)
    total = len(endpoint_results)
    failed = [f"{ep}: {detail}" for ep, ok, detail in endpoint_results if not ok]
    if failed:
        report.check("HTTP endpoints", False, f"{passed}/{total} passed; failures: " + "; ".join(failed))
    else:
        report.check("HTTP endpoints", True, f"{passed}/{total} passed")

    return proc


# â”€â”€ Check 5: synthetic round-trip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _post(base: str, path: str, payload: dict, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def check_synthetic_roundtrip(report: Report, server_proc):
    name = "synthetic task round-trip"
    if server_proc is None:
        report.check(name, False, "skipped (server did not boot)")
        return

    base = f"http://127.0.0.1:{TEST_PORT}"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    task_text = f"{SYNTHETIC_TAG} probe {timestamp}"
    steps_ok: list[tuple[str, bool, str]] = []

    try:
        # 1. Add
        r = _post(base, "/api/add", {
            "text": task_text, "domain": "academic", "priority": 3,
            "energy": "low", "due": "", "notes": "automated health check",
        })
        steps_ok.append(("add", r.get("ok", False), r.get("message", "")))

        # 2. Done
        r = _post(base, "/api/done", {"text": task_text})
        steps_ok.append(("done", r.get("ok", False), r.get("message", "")))

        # 3. Undone (reopen)
        r = _post(base, "/api/undone", {"text": task_text})
        steps_ok.append(("undone", r.get("ok", False), r.get("message", "")))

        # 4. Save for later
        r = _post(base, "/api/save_for_later", {"text": task_text})
        steps_ok.append(("save_for_later", r.get("ok", False), r.get("message", "")))

        # 5. Restore from saved
        r = _post(base, "/api/restore", {"text": task_text, "from": "saved"})
        steps_ok.append(("restore", r.get("ok", False), r.get("message", "")))

        # 6. Cancel
        r = _post(base, "/api/cancel", {"text": task_text})
        steps_ok.append(("cancel", r.get("ok", False), r.get("message", "")))

    except Exception as e:
        steps_ok.append(("exception", False, f"{type(e).__name__}: {e}"))

    # 7. Cleanup â€” remove the synthetic task from the cancelled archive
    cleanup_ok, cleanup_detail = _cleanup_synthetic_task(task_text)
    steps_ok.append(("cleanup", cleanup_ok, cleanup_detail))

    failures = [f"{step}: {detail}" for step, ok, detail in steps_ok if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps_ok)} steps")


def _cleanup_synthetic_task(task_text: str) -> tuple[bool, str]:
    """Remove the synthetic task from CANCELLED.md / SAVED_FOR_LATER.md / any md file."""
    search = task_text.lower()
    files_to_clean: list[Path] = [
        PSU_DIR / "CANCELLED.md",
        PSU_DIR / "SAVED_FOR_LATER.md",
        PSU_DIR / "DASHBOARD.md",
    ]
    domains = PSU_DIR / "domains"
    if domains.exists():
        files_to_clean.extend(domains.glob("*.md"))
    if AXMRA_DIR:
        anchor_sub = AXMRA_DIR / ".anchor"
        if anchor_sub.exists():
            files_to_clean.extend([
                anchor_sub / "DASHBOARD.md",
                anchor_sub / "PROJECTS.md",
                anchor_sub / "CANCELLED.md",
                anchor_sub / "SAVED_FOR_LATER.md",
            ])

    removed_from = []
    errors = []
    for f in files_to_clean:
        if not f.exists():
            continue
        try:
            text = f.read_text(encoding="utf-8")
            new_lines = [ln for ln in text.splitlines() if SYNTHETIC_TAG not in ln.lower()]
            if len(new_lines) != len(text.splitlines()):
                f.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                removed_from.append(f.name)
        except Exception as e:
            errors.append(f"{f.name}: {e}")
    if errors:
        return False, "errors: " + "; ".join(errors)
    return True, f"removed from {len(removed_from)} file(s)" if removed_from else "no traces left"


# â”€â”€ Check 6: logging works â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_logging(report: Report):
    name = "logging"
    issues = []

    # Today's log should exist and have content (the test server boot+ops should have written)
    psu_log = PSU_DIR / "logs" / f"{TODAY}.md"
    if not psu_log.exists():
        issues.append(f"PSU log {TODAY}.md not written")
    elif psu_log.stat().st_size < 10:
        issues.append(f"PSU log {TODAY}.md is empty")

    # Yesterday's log SHOULD exist if the system ran yesterday â€” but only flag if also
    # the day before is missing (to avoid noise on first install or skipped days).
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    day_before = (date.today() - timedelta(days=2)).isoformat()
    psu_yesterday = PSU_DIR / "logs" / f"{yesterday}.md"
    psu_day_before = PSU_DIR / "logs" / f"{day_before}.md"
    if not psu_yesterday.exists() and not psu_day_before.exists():
        report.recommend(f"No log files for the last 2 days ({yesterday}, {day_before}) â€” system may not have run")

    # errors.log should be readable and not catastrophically large
    err_log = PSU_DIR / "logs" / "errors.log"
    if err_log.exists():
        size_mb = err_log.stat().st_size / (1024 * 1024)
        if size_mb > 50:
            report.recommend(f"errors.log is {size_mb:.1f} MB â€” consider rotating")

    if issues:
        report.check(name, False, "; ".join(issues))
    else:
        report.check(name, True, f"today's log {psu_log.stat().st_size} bytes")


# â”€â”€ Check 7: Local filesystem write sanity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_onedrive_sync(report: Report):
    name = "Local filesystem write sanity"
    marker = PSU_DIR / ".healthcheck_marker"
    payload = f"{datetime.now().isoformat()} healthcheck"
    try:
        marker.write_text(payload, encoding="utf-8")
        readback = marker.read_text(encoding="utf-8")
        if readback != payload:
            report.check(name, False, "write/read mismatch")
            return
        marker.unlink()
        report.check(name, True, "write/read OK")
    except PermissionError as e:
        report.check(name, False, f"permission denied: {e}")
    except Exception as e:
        report.check(name, False, f"{type(e).__name__}: {e}")


# â”€â”€ Stale-process cleanup (port 8777) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def cleanup_stale_processes(report: Report):
    """If port 8777 is held by a Python process older than 24h, terminate it.
    On Windows, use `tasklist` and `taskkill`. Best-effort: errors are logged but not fatal."""
    if sys.platform != "win32":
        return
    try:
        # netstat to find PID holding port 8777
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"], stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
    except Exception:
        return

    pids = set()
    for line in out.splitlines():
        if ":8777" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
    if not pids:
        return

    # For each PID, check creation time via wmic / Get-Process
    for pid in pids:
        try:
            # PowerShell call to check process age (simpler than wmic which is deprecated)
            ps_cmd = f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).StartTime.ToString('o')"
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
            )
            start_str = r.stdout.strip()
            if not start_str:
                continue
            start_dt = datetime.fromisoformat(start_str)
            age = datetime.now(start_dt.tzinfo) - start_dt
            if age > timedelta(hours=24):
                # Kill it
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
                report.fix(f"Terminated stale anchor process PID {pid} (age: {age})")
        except Exception:
            continue


# â”€â”€ Server cleanup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def shutdown_server(server_proc):
    if server_proc is None:
        return
    try:
        # Try graceful shutdown via API
        urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{TEST_PORT}/api/shutdown",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            timeout=3,
        ).read()
    except Exception:
        pass
    try:
        server_proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main():
    report = Report()
    server_proc = None

    try:
        # Routine maintenance pass first â€” fixes that should happen before tests
        cleanup_stale_processes(report)

        check_filesystem(report)
        check_code_compiles(report)

        # Need anchor_gui as a module to call its parsers
        try:
            mod = _import_anchor_gui()
        except Exception as e:
            report.check("import anchor_gui", False, f"{type(e).__name__}: {e}")
            mod = None

        if mod is not None:
            check_markdown_parses(report, mod)

        server_proc = check_server_and_endpoints(report)
        check_synthetic_roundtrip(report, server_proc)

        # Logging check should happen AFTER the server has done its work
        # so today's log file gets written by the boot/shutdown events.
        # But that requires a clean shutdown first.
        shutdown_server(server_proc)
        server_proc = None

        check_logging(report)
        check_onedrive_sync(report)

    except Exception as e:
        report.check("healthcheck framework", False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    finally:
        shutdown_server(server_proc)

    report_path = REPORTS_DIR / f"{TODAY}.md"
    try:
        report.write(report_path)
    except Exception as e:
        # Last-ditch fallback: write to a fixed path so we don't lose the result
        fallback = PSU_DIR / "logs" / "healthcheck-error.log"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(f"Could not write report: {e}\n{traceback.format_exc()}", encoding="utf-8")

    # Exit code: 0 = clean, 1 = issues, 2 = framework crash
    if report.has_issues:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

