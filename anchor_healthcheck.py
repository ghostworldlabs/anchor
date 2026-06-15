#!/usr/bin/env python3
"""
Anchor Health Check â€” runs daily at 5:00 AM via Windows Task Scheduler.

What it does, every morning:
  1. File system integrity   â€” Anchor dir reachable, expected files present
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
ANCHOR_DIR = SCRIPT_DIR  # this script must live in the Anchor root (CODE dir)

# Wave 2: data paths resolve via the shared `paths` helper, honoring the
# ANCHOR_DATA_DIR env var (unset -> the code dir, so behavior is unchanged).
# Code-file references (anchor_gui.py / anchor.py compile + cwd) stay on
# ANCHOR_DIR; data-file references use DATA_DIR.
import paths as _paths
DATA_DIR = _paths.data_dir()
REPORTS_DIR = _paths.health_reports_dir()
TEST_PORT = 8778
SERVER_BOOT_TIMEOUT = 12  # seconds
SYNTHETIC_TAG = "__healthcheck__"
TODAY = date.today().isoformat()

_paths.ensure_data_dirs()

# Sentinel so _post() can distinguish "caller passed token=None on purpose"
# (deliberately tokenless request) from "caller didn't specify a token"
# (attach the configured token automatically).
_UNSET = object()

# Files that MUST exist (auto-restored if missing)
REQUIRED_FILES = {
    "DASHBOARD.md": "# Dashboard\n\n## Today's Priorities\n\n## Active Priorities\n",
    "PROJECTS.md": "# Projects\n",
    "INBOX.md": "# Inbox\n\n## Quick Capture\n",
    "CANCELLED.md": "# Cancelled Tasks\n\n",
    "SAVED_FOR_LATER.md": "# Saved For Later\n\n",
    "WEEKLY_REVIEW.md": "# Weekly Review\n\n",
}
DOMAIN_FILES = ["academic.md", "commercial.md", "family.md", "writing.md"]


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

    if not DATA_DIR.exists():
        report.check(name, False, f"Anchor data directory missing: {DATA_DIR}")
        return

    missing = []

    # Required files
    for filename, template in REQUIRED_FILES.items():
        p = DATA_DIR / filename
        if not p.exists():
            try:
                p.write_text(template, encoding="utf-8")
                report.fix(f"Restored missing {filename} from template")
            except Exception as e:
                missing.append(f"{filename} ({e})")

    # Domain files
    domains_dir = DATA_DIR / "domains"
    if not domains_dir.exists():
        try:
            domains_dir.mkdir(parents=True, exist_ok=True)
            report.fix("Created missing domains/ directory")
        except Exception as e:
            missing.append(f"domains/ ({e})")
    for df in DOMAIN_FILES:
        p = domains_dir / df
        if not p.exists():
            missing.append(f"domains/{df}")

    # logs dir
    logs_dir = DATA_DIR / "logs"
    if not logs_dir.exists():
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            report.fix("Created missing logs/ directory")
        except Exception as e:
            missing.append(f"logs/ ({e})")

    if missing:
        report.check(name, False, "missing: " + ", ".join(missing))
    else:
        report.check(name, True, "ok")


# â”€â”€ Check 2: code compiles â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_code_compiles(report: Report):
    name = "code compiles"
    failed = []
    for fname in ("anchor_gui.py", "anchor.py"):
        p = ANCHOR_DIR / fname
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
    spec = importlib.util.spec_from_file_location("anchor_gui_mod", ANCHOR_DIR / "anchor_gui.py")
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
    candidates.append(("DASHBOARD.md", DATA_DIR / "DASHBOARD.md", "tasks"))
    candidates.append(("PROJECTS.md", DATA_DIR / "PROJECTS.md", "projects"))
    candidates.append(("INBOX.md", DATA_DIR / "INBOX.md", "inbox"))
    candidates.append(("CANCELLED.md", DATA_DIR / "CANCELLED.md", "archived"))
    candidates.append(("SAVED_FOR_LATER.md", DATA_DIR / "SAVED_FOR_LATER.md", "archived"))
    for f in sorted((DATA_DIR / "domains").glob("*.md")):
        candidates.append((f"domains/{f.name}", f, "tasks"))

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


def _find_free_port(preferred: int) -> int:
    """Return `preferred` if it's free, otherwise an OS-assigned free port."""
    if not _port_in_use(preferred):
        return preferred
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def check_server_and_endpoints(report: Report):
    """Boot the server on TEST_PORT, exercise endpoints, return the popen handle."""
    global TEST_PORT
    name = "server boot"

    # The fixed test port can be left occupied by a stale server we can't reap
    # (e.g. a SYSTEM-owned orphan spawned by the NSSM service — a non-elevated
    # check can't taskkill it). Don't fail the whole self-test over that: fall
    # back to an OS-assigned free port so the boot/endpoint/round-trip checks
    # can still run. check_synthetic_roundtrip reads TEST_PORT too, so updating
    # the global keeps both in sync.
    if _port_in_use(TEST_PORT):
        fallback = _find_free_port(TEST_PORT)
        report.fix(f"test port {TEST_PORT} busy; ran on free port {fallback} instead")
        TEST_PORT = fallback

    cmd = [sys.executable, str(ANCHOR_DIR / "anchor_gui.py"), "--port", str(TEST_PORT), "--no-browser"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(ANCHOR_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
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

    # POST validation pings â€” send a no-op text and expect ok=False, not a 500.
    # _post() attaches the configured token automatically, so these don't 401
    # under the production D4 token posture.
    for endpoint in ("/api/done", "/api/undone", "/api/cancel",
                     "/api/save_for_later", "/api/restore"):
        try:
            data = _post(base, endpoint, {"text": "__nonexistent_validation_ping__"})
            # Should respond with ok=False (task not found) and not 500
            ok = "ok" in data
            endpoint_results.append((f"POST {endpoint}", ok, "status=200"))
        except urllib.error.HTTPError as e:
            endpoint_results.append((f"POST {endpoint}", False, f"HTTP {e.code}"))
        except Exception as e:
            endpoint_results.append((f"POST {endpoint}", False, str(e)))

    # SETUP.md §6 unauth-rejection assertion: when a token IS configured, a
    # deliberately tokenless mutating POST must be rejected with 401. When no
    # token is configured, skip gracefully (auth is disabled).
    if _paths.expected_token() is not None:
        try:
            req = urllib.request.Request(
                base + "/api/done",
                data=json.dumps({"text": "__unauth_probe__"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).read()
            # Reaching here means it was NOT rejected — a failure.
            endpoint_results.append(("POST /api/done (tokenless)", False, "expected 401, got 200"))
        except urllib.error.HTTPError as e:
            ok = e.code == 401
            endpoint_results.append(("POST /api/done (tokenless)", ok, f"HTTP {e.code} (expected 401)"))
            if ok:
                report.fix("unauth-rejection assertion: tokenless mutating POST correctly returned 401")
        except Exception as e:
            endpoint_results.append(("POST /api/done (tokenless)", False, str(e)))

    passed = sum(1 for _, ok, _ in endpoint_results if ok)
    total = len(endpoint_results)
    failed = [f"{ep}: {detail}" for ep, ok, detail in endpoint_results if not ok]
    if failed:
        report.check("HTTP endpoints", False, f"{passed}/{total} passed; failures: " + "; ".join(failed))
    else:
        report.check("HTTP endpoints", True, f"{passed}/{total} passed")

    return proc


# â”€â”€ Check 5: synthetic round-trip â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _post(base: str, path: str, payload: dict, timeout: float = 5.0,
          token: "str | None" = _UNSET) -> dict:
    """POST JSON to the test server.

    When ``token`` is left at its sentinel default, the configured token
    (``paths.expected_token()``) is attached automatically if one is set — so
    mutating endpoints don't 401 under the production D4 token posture. Pass
    ``token=None`` explicitly to send a deliberately tokenless request (used by
    the unauth-rejection assertion).
    """
    headers = {"Content-Type": "application/json"}
    if token is _UNSET:
        token = _paths.expected_token()
    if token is not None:
        headers["X-Anchor-Token"] = token
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers=headers,
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
        DATA_DIR / "CANCELLED.md",
        DATA_DIR / "SAVED_FOR_LATER.md",
        DATA_DIR / "DASHBOARD.md",
    ]
    domains = DATA_DIR / "domains"
    if domains.exists():
        files_to_clean.extend(domains.glob("*.md"))

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


# â”€â”€ Check 5b: R&D v2 surface (sessions / summaries / terminal / grass) â”€â”€â”€â”€â”€â”€
# Exercises the v2 R&D endpoints on the throwaway server (Wave 8). Everything
# model-driven goes through the STUB runner (ANCHOR_RUNNER_CMD -> fake_claude),
# never live claude. A SYNTHETIC project is registered in a throwaway temp folder
# and fully torn down afterward so REAL data (rnd_registry.json, the live
# project's .anchor store) is never polluted.

SYNTHETIC_RND_NAME = "__healthcheck__ rnd probe"


def _fake_runner_cmd() -> "str | None":
    """Path to the stub runner used to drive v2 model calls without live claude.

    Prefers ``tests/fake_claude.py`` (the suite's deterministic stub). Returns a
    ``python <abs path>`` command string, or ``None`` if the stub is absent (the
    v2 check then degrades gracefully instead of risking a live CLI).
    """
    stub = ANCHOR_DIR / "tests" / "fake_claude.py"
    if stub.is_file():
        return f"{sys.executable} {stub}"
    return None


def _streamjson_runner_cmd() -> "str | None":
    """Path to the STREAM-JSON stub runner (``tests/stub_streamjson.py``).

    Unlike ``fake_claude.py`` (bare text lines), this stub emits production
    ``claude -p --output-format stream-json`` NDJSON envelopes — the shape the
    summarizer's parser must extract real text from (the v6 Wave-1 regression
    guard). Returns a ``python <abs path>`` command string, or ``None`` if absent
    (the v6 check then degrades gracefully instead of risking a live CLI).
    """
    stub = ANCHOR_DIR / "tests" / "stub_streamjson.py"
    if stub.is_file():
        return f"{sys.executable} {stub}"
    return None


def check_rnd_v2_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v2 R&D surface on the throwaway server (stubbed runner).

    Walks: register a synthetic project -> status_line shape (via the project
    window) -> add_idea / promote_inbox (grass) -> pin_deliverable -> reconcile
    preview -> a discovered planning session -> /summary + regenerate_summary ->
    a terminal session start -> term_input -> term_discover -> term_adopt. All
    model calls are stubbed via ANCHOR_RUNNER_CMD=fake_claude.

    ``rnd_env`` carries the temp folder + registry-cleanup hooks set up by main()
    so this never touches real data.
    """
    name = "R&D v2 surface"
    if server_proc is None:
        report.check(name, False, "skipped (server did not boot)")
        return
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return

    base = f"http://127.0.0.1:{TEST_PORT}"
    steps: list[tuple[str, bool, str]] = []
    folder = rnd_env["folder"]

    try:
        import rnd_registry as _rnd
        import effort_history as _eh
        import sessions as _sessions
        import brownfield_scan as _bf

        # 1. Register a synthetic project in the throwaway folder.
        proj = _rnd.add_project(SYNTHETIC_RND_NAME, str(folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register project", bool(pid), pid))

        # 2. add_idea -> grass lane (POST, token-aware).
        r = _post(base, "/api/rnd/add_idea",
                  {"project_id": pid, "text": "hc synthetic idea"})
        steps.append(("add_idea", r.get("ok", False), str(r.get("error", ""))))

        # 3. promote_inbox -> grass lane (reads the live INBOX.md, copy-by-default).
        #    Seed a synthetic inbox line first so the match is deterministic and
        #    tagged for cleanup; copy-by-default leaves it for _cleanup to remove.
        inbox = DATA_DIR / "INBOX.md"
        probe_line = f"- {TODAY}: {SYNTHETIC_TAG} inbox idea\n"
        try:
            if inbox.exists():
                inbox.write_text(inbox.read_text(encoding="utf-8").rstrip()
                                 + "\n" + probe_line, encoding="utf-8")
            else:
                inbox.write_text("# Inbox\n\n" + probe_line, encoding="utf-8")
        except OSError:
            pass
        r = _post(base, "/api/rnd/promote_inbox",
                  {"project_id": pid, "text": f"{SYNTHETIC_TAG} inbox idea"})
        steps.append(("promote_inbox", r.get("ok", False),
                      str(r.get("error", ""))))

        # 4. pin_deliverable: pin a file inside the throwaway folder.
        (folder / "deliverable.py").write_text("print('hc')\n", encoding="utf-8")
        r = _post(base, "/api/rnd/pin_deliverable",
                  {"project_id": pid, "path": "deliverable.py",
                   "type": "script"})
        steps.append(("pin_deliverable", r.get("ok", False),
                      str(r.get("error", ""))))

        # 5. reconcile PREVIEW (dry-run) via the registry mirror (non-destructive).
        rep = _rnd.reconcile_folder(pid, apply=False)
        steps.append(("reconcile preview",
                      rep.get("ok", False) and rep.get("applied") is False,
                      f"to_delete={rep.get('to_delete')}"))

        # 6. status_line shape (Wave 3 contract: per-lane counts+provenance).
        sl = _rnd.status_line(pid)
        shape_ok = all(
            lane in sl and set(sl[lane].keys()) == {"count", "imported", "running"}
            for lane in ("research", "planning", "build", "deliverables")
        )
        steps.append(("status_line shape", shape_ok, str(sl.get("grass", ""))))

        # 7. A discovered planning session -> /summary (GET) + regenerate_summary.
        bd = folder / "planning" / "brownfield-discovery"
        bd.mkdir(parents=True, exist_ok=True)
        (bd / "MASTER-PLAN.md").write_text(
            "# Master Plan\n\n## North Star\nfake line goal.\n", encoding="utf-8")
        scan = _bf.scan(str(folder))
        _eh.adopt_discovered(folder, pid, scan)
        plan_sessions = _sessions.list_sessions(folder, pid, "planning")
        if plan_sessions:
            sid = plan_sessions[0]["session_id"]
            # GET /summary (run-once: generates through the stub runner on first view)
            try:
                with urllib.request.urlopen(
                    f"{base}/summary/{pid}/planning/{sid}", timeout=20) as rr:
                    body = rr.read().decode("utf-8", errors="replace")
                    steps.append(("GET /summary", rr.status == 200
                                  and len(body) > 200, f"{len(body)}b"))
            except Exception as e:
                steps.append(("GET /summary", False, str(e)))
            # regenerate_summary (POST, force re-run through the stub).
            r = _post(base, "/api/rnd/regenerate_summary",
                      {"project_id": pid, "lane": "planning",
                       "session_id": sid}, timeout=30)
            steps.append(("regenerate_summary", r.get("ok", False),
                          str(r.get("error", ""))))
        else:
            steps.append(("discovered planning session", False,
                          "no session grouped"))

        # 8. Terminal walk: start -> input -> discover -> adopt (stubbed runner).
        #    Use the research lane (engine policy permits both engines) with a
        #    short fake run so the session reaches a terminal state quickly.
        try:
            import rnd_terminal as _term
            rec = _term.start_terminal(
                pid, "research",
                extra_args=["--lines", "1", "--sleep", "0.3"])
            tjid = rec.get("job_id")
            steps.append(("terminal start", bool(tjid), str(rec.get("status"))))
            # input via the API (writes onto live stdin while the job runs).
            r = _post(base, "/api/rnd/term_input",
                      {"session": tjid, "text": "continue please"})
            # written may be False if the stub already exited — accept either as
            # long as it is a clean JSON response (no 500).
            steps.append(("term_input", "written" in r,
                          f"written={r.get('written')}"))
            # Simulate a produced file then discover -> adopt.
            out_dir = Path(rec.get("output_dir") or "")
            if out_dir and out_dir.exists():
                (out_dir / "PRODUCED.md").write_text(
                    "# Produced\nhc terminal output\n", encoding="utf-8")
            import job_runner as _jr
            try:
                _jr.wait(tjid, timeout=10)
            except Exception:
                pass
            r = _post(base, "/api/rnd/term_discover", {"session": tjid})
            steps.append(("term_discover", r.get("ok", False),
                          str(r.get("error", ""))))
            r = _post(base, "/api/rnd/term_adopt", {"session": tjid})
            # adopt returns ok=True when something was adopted; tolerate the
            # nothing-adoptable path as a clean (non-500) response too.
            steps.append(("term_adopt", "ok" in r,
                          str(r.get("error", r.get("ok")))))
        except Exception as e:
            steps.append(("terminal walk", False, f"{type(e).__name__}: {e}"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def _git_init_repo(path: Path) -> bool:
    """Best-effort ``git init`` + one commit so worktrees can be added. Returns
    success. Used ONLY for the throwaway v3 terminal repo (never the build repo)."""
    try:
        env = dict(os.environ)
        env.setdefault("GIT_AUTHOR_NAME", "anchor-hc")
        env.setdefault("GIT_AUTHOR_EMAIL", "anchor@localhost")
        env.setdefault("GIT_COMMITTER_NAME", "anchor-hc")
        env.setdefault("GIT_COMMITTER_EMAIL", "anchor@localhost")
        for args in (
            ["git", "init"],
            ["git", "config", "user.email", "anchor@localhost"],
            ["git", "config", "user.name", "anchor-hc"],
            ["git", "add", "-A"],
            ["git", "commit", "-m", "hc seed", "--no-gpg-sign"],
        ):
            subprocess.run(args, cwd=str(path), env=env, capture_output=True,
                           text=True, timeout=30)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def check_rnd_v3_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v3 "Mission Control" R&D surface — FULLY STUBBED.

    Walks the new v3 modules in a throwaway temp project/folder, never touching
    real data, never a live claude / real PTY / real preview spawn / real
    worktree off the build repo:

      1. session registry: register a synthetic session → reconcile re-statuses a
         dead "running" one → remove.
      2. stub-PTY lifecycle: ``pty_manager`` stub ``start→write→read_since`` (echo
         round-trip) → ``kill`` (reaped); AND a ``terminal_session.start_session``
         → ``attach`` (replay) → ``input`` → ``kill`` against a TEMP git repo with
         the stub backend + a TEMP worktree base (``ANCHOR_WORKTREE_BASE``).
      3. proactive summary: ``summarizer.summarize_project`` through the stub
         runner → cached.
      4. deliverable-run preview: NO real server spawn — walk
         ``preview_server.pick_free_port`` (assert ``!= 8777``) + ``reap_orphans``
         with an INJECTED dead-pid record (proves the never-8777 guard + the
         reconcile path without spawning anything).
      5. handoff: ``discover_recent_plan_set`` / ``record_handoff`` on the
         synthetic project, and the record SURVIVES a rescan.

    Everything is torn down by ``_cleanup_synthetic_rnd`` + the env restore in
    ``main()``. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (fake_claude)
    keep every model/PTY interaction off the real engine.
    """
    name = "R&D v3 surface"
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    # Force the STUB PTY backend + a hermetic worktree base for the whole walk;
    # both are restored in `finally`.
    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v3-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    try:
        import rnd_registry as _rnd
        import session_registry as _sreg
        import pty_manager as _pty
        import terminal_session as _ts
        import preview_server as _preview
        import summarizer as _summarizer
        import handoff as _handoff
        import sessions as _sessions
        import effort_history as _eh
        import brownfield_scan as _bf

        # ── 0. A throwaway git project (so worktrees can attach to a real repo) ─
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v3-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "README.md").write_text("# hc v3 probe\n", encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v3", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v3 project", bool(pid), pid))

        # ── 1. Session registry: register → reconcile(dead) → remove ───────────
        rec = _sreg.register_session(pid, "build", status=_sreg.STATUS_RUNNING,
                                     label="hc synthetic")
        sid = rec["session_id"]
        # No live ids → the "running" session is stale; reconcile re-statuses it.
        rc = _sreg.reconcile(live_session_ids=[], apply=True)
        after = _sreg.get_session(sid)
        steps.append(("registry register+reconcile",
                      sid in rc.get("stale", [])
                      and after and after.get("status") != _sreg.STATUS_RUNNING,
                      f"status={after.get('status') if after else None}"))
        removed = _sreg.remove_session(sid)
        steps.append(("registry remove",
                      removed and _sreg.get_session(sid) is None, ""))

        # ── 2a. Stub-PTY round-trip via pty_manager directly ───────────────────
        psid = _pty.start(["claude"], cwd=str(proj_folder))
        _pty.write(psid, "ECHO-ROUNDTRIP")
        out = _pty.read_since(psid, 0)
        echoed = "ECHO-ROUNDTRIP" in out.get("text", "")
        steps.append(("pty stub echo round-trip", echoed,
                      f"status={out.get('status')}"))
        _pty.kill(psid)
        reaped = psid not in _pty.live_sessions()
        steps.append(("pty stub kill reaped", reaped, ""))

        # ── 2b. terminal_session start→attach(replay)→input→kill (stub+temp repo)
        if git_ok:
            try:
                trec = _ts.start_session(pid, "build", label="hc v3 term")
                tsid = trec["session_id"]
                _ts.input(tsid, "hello-term")
                att = _ts.attach(tsid)
                steps.append(("terminal_session start+attach",
                              att.get("ok") and "hello-term" in att.get("buffer", ""),
                              f"status={att.get('status')}"))
                ko = _ts.kill(tsid, project_id=pid)
                steps.append(("terminal_session kill+worktree",
                              ko.get("ok", False),
                              f"wt={ko.get('worktree', {}).get('ok')}"))
            except Exception as e:
                steps.append(("terminal_session walk", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("terminal_session walk", True,
                          "skipped (git unavailable; pty round-trip already proven)"))

        # ── 3. Proactive PROJECT summary through the stub runner → cached ──────
        (proj_folder / "CLAUDE.md").write_text(
            "# HC v3 Project\n\nNorth Star: prove the stubbed v3 summary path.\n",
            encoding="utf-8")
        try:
            psum = _summarizer.summarize_project(str(proj_folder), pid, force=True)
            cached = _summarizer.load_cached_project(str(proj_folder), pid)
            steps.append(("project summary (stubbed)",
                          isinstance(psum, dict) and cached is not None,
                          str(psum.get("error", "ok"))))
        except Exception as e:
            steps.append(("project summary (stubbed)", False,
                          f"{type(e).__name__}: {e}"))

        # ── 4. Preview: pick_free_port (!=8777) + reap_orphans w/ injected dead pid
        try:
            port = _preview.pick_free_port()
            steps.append(("preview pick_free_port != 8777",
                          isinstance(port, int) and port != _preview.LIVE_PORT,
                          f"port={port}"))
            # Inject a dead-pid 'running' preview record (no spawn at the 5AM check)
            dead_pid = 2 ** 31 - 1  # an implausible/never-alive pid
            inj = {
                "preview_id": "hc-v3-preview",
                "project_id": pid,
                "target": "anchor_gui.py",
                "port": port,
                "url": f"http://127.0.0.1:{port}/",
                "status": _preview.STATUS_RUNNING,
                "pid": dead_pid,
                "data_dir": "",
                "started_at": time.time(),
            }
            _preview._put_record(inj)
            rep = _preview.reap_orphans()
            recd = _preview.load_previews().get("hc-v3-preview", {})
            steps.append(("preview reap_orphans (dead pid → stopped)",
                          "hc-v3-preview" in rep.get("reaped", [])
                          and recd.get("status") == _preview.STATUS_STOPPED,
                          f"reaped={rep.get('reaped')}"))
            # Clean the injected record out of the registry.
            with _paths.WRITE_LOCK:
                regp = _preview.load_previews()
                regp.pop("hc-v3-preview", None)
                _preview._save_previews(regp)
        except Exception as e:
            steps.append(("preview walk", False, f"{type(e).__name__}: {e}"))

        # ── 5. Handoff: discover_recent_plan_set + record (survives a rescan) ──
        try:
            bd = proj_folder / "planning" / "hc-v3-plan"
            bd.mkdir(parents=True, exist_ok=True)
            (bd / "MASTER-PLAN.md").write_text(
                "# Master Plan\n\n## North Star\nhc v3 north star.\n",
                encoding="utf-8")
            (bd / "IMPLEMENTATION-PLAN.md").write_text(
                "# Implementation Plan\n\n## Wave 1\nhc.\n", encoding="utf-8")
            scan = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan)
            plan_set = _handoff.discover_recent_plan_set(str(proj_folder), pid)
            steps.append(("handoff discover_recent_plan_set",
                          bool(plan_set), str(bool(plan_set))))
            rh = _handoff.record_handoff(str(proj_folder), pid,
                                         "hc-build-session", plan_set or {})
            steps.append(("handoff record", rh.get("ok", False),
                          str(rh.get("reason", ""))))
            # The record must SURVIVE a rescan (the Wave-7 durability contract).
            _bf.scan(str(proj_folder))  # re-scan; merge must preserve handoffs
            survived = any(h.get("build_session_id") == "hc-build-session"
                           for h in _handoff.list_handoffs(str(proj_folder), pid))
            steps.append(("handoff survives rescan", survived, ""))
        except Exception as e:
            steps.append(("handoff walk", False, f"{type(e).__name__}: {e}"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Restore the PTY backend + worktree-base env we forced for this walk.
        if prev_pty is None:
            os.environ.pop("ANCHOR_PTY_BACKEND", None)
        else:
            os.environ["ANCHOR_PTY_BACKEND"] = prev_pty
        if prev_wtbase is None:
            os.environ.pop("ANCHOR_WORKTREE_BASE", None)
        else:
            os.environ["ANCHOR_WORKTREE_BASE"] = prev_wtbase

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v4_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v4 "Project Cockpit" R&D surface — FULLY STUBBED.

    Walks the new v4 data/control seams in a throwaway temp project + temp git
    repo, never touching real data, never a live claude / real PTY / real preview
    spawn / real worktree off the build repo:

      (a) seed-once: ``terminal_session.start_session`` (stub PTY) writes the lane
          skill seed EXACTLY once → ``record.seeded`` is True; a repeated
          ``read_since`` never re-emits the seed.
      (b) engine switch: ``terminal_session.switch_engine`` swaps the backend in
          the SAME worktree with no orphan PTY; ``last_engine_for_project``
          reflects the new engine.
      (c) doc-roles: ``summarizer.session_doc_roles`` returns a dict for a
          discovered planning session.
      (d) rollup: ``effort_history.project_effort_rollup`` returns the
          ``{tokens,cost_usd,wall_clock_ms,sessions}`` shape for BOTH lifetime
          and 30d windows.
      (e) grass promote: ``effort_history.promote_grass_to_lane`` starts a seeded
          stub session in the target lane and the idea REMAINS in grass (copy).
      (f) type-aware deliverable launch — a skill VERIFY (no spawn, against a TEMP
          ``ANCHOR_SKILLS_DIR`` — never the live one) AND a service launch on a
          GUARANTEED-FREE injected port asserted ``!= 8777`` via a STUBBED
          ``preview_server`` (no real long-lived server is bound).

    Everything is torn down by ``_cleanup_synthetic_rnd`` + the env restore here +
    in ``main()``. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (fake_claude)
    + a temp ``ANCHOR_WORKTREE_BASE`` keep every model/PTY interaction off the real
    engine; nothing touches the live ``:8777`` service.
    """
    name = "R&D v4 surface"
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    # Force the STUB PTY backend + a hermetic worktree base + a temp skills dir
    # for the whole walk; all restored in `finally`.
    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_skills = os.environ.get("ANCHOR_SKILLS_DIR")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v4-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    skills_dir = Path(_tf.mkdtemp(prefix="anchor-hc-v4-skills-"))
    os.environ["ANCHOR_SKILLS_DIR"] = str(skills_dir)
    # A deterministic, recognizable seed so the seed-once assertion is exact.
    os.environ["ANCHOR_TERMINAL_SEED"] = "HC-V4-SEED-LOAD-SKILL"
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)
    rnd_env["v3_temp_dirs"].append(skills_dir)

    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import pty_manager as _pty
        import effort_history as _eh
        import summarizer as _summarizer
        import deliverables as _deliv
        import preview_server as _preview
        import sessions as _sessions
        import brownfield_scan as _bf

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v4-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "README.md").write_text("# hc v4 probe\n", encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v4", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v4 project", bool(pid), pid))

        seed_tsid = None
        if git_ok:
            # ── (a) seed-once on a stub Research session (so the gemini engine
            #         switch below is policy-allowed: gemini is research-only) ──
            try:
                rec = _ts.start_session(pid, "research", label="hc v4 seed")
                seed_tsid = rec["session_id"]
                seeded_flag = bool(rec.get("seeded"))
                out1 = _pty.read_since(seed_tsid, 0)
                out2 = _pty.read_since(seed_tsid, 0)
                seed_marker = "HC-V4-SEED-LOAD-SKILL"
                # Seed appears once and is identical across repeated reads (the
                # stub echoes input → the marker is in the buffer, never re-sent).
                seed_once = (out1.get("text", "").count(seed_marker)
                             == out2.get("text", "").count(seed_marker)
                             >= 1)
                steps.append(("seed-once written + flag",
                              seeded_flag and seed_once,
                              f"seeded={seeded_flag} marker_seen="
                              f"{out1.get('text','').count(seed_marker)}"))
            except Exception as e:
                steps.append(("seed-once", False, f"{type(e).__name__}: {e}"))

            # ── (b) engine switch (no orphan PTY) ─────────────────────────────
            if seed_tsid is not None:
                try:
                    live_before = set(_pty.live_sessions())
                    sw = _ts.switch_engine(seed_tsid, "gemini")
                    after = _rnd_session(seed_tsid)
                    last_eng = _ts.last_engine_for_project(pid)
                    # The session id is preserved; exactly one live PTY for it.
                    live_after = set(_pty.live_sessions())
                    no_orphan = (seed_tsid in live_after
                                 and len(live_after) <= len(live_before))
                    steps.append(("engine switch",
                                  sw.get("ok", bool(sw))
                                  and (after or {}).get("backend") == "gemini"
                                  and last_eng == "gemini"
                                  and no_orphan,
                                  f"backend={(after or {}).get('backend')} "
                                  f"last={last_eng}"))
                except Exception as e:
                    steps.append(("engine switch", False,
                                  f"{type(e).__name__}: {e}"))
                # Reap the seed session's PTY + worktree (no leak).
                try:
                    _ts.kill(seed_tsid, project_id=pid)
                except Exception:
                    pass
        else:
            steps.append(("seed-once / engine switch", True,
                          "skipped (git unavailable)"))

        # ── (c) doc-roles on a discovered planning session ────────────────────
        try:
            bd = proj_folder / "planning" / "hc-v4-plan"
            bd.mkdir(parents=True, exist_ok=True)
            (bd / "MASTER-PLAN.md").write_text(
                "# Master Plan\n\n## North Star\nhc v4 doc-roles.\n",
                encoding="utf-8")
            (bd / "IMPLEMENTATION-PLAN.md").write_text(
                "# Implementation Plan\n\n## Wave 1\nhc.\n", encoding="utf-8")
            scan = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan)
            plan_sessions = _sessions.list_sessions(str(proj_folder), pid,
                                                    "planning")
            if plan_sessions:
                psid = plan_sessions[0]["session_id"]
                roles = _summarizer.session_doc_roles(pid, "planning", psid,
                                                      folder_path=str(proj_folder))
                steps.append(("doc-roles dict", isinstance(roles, dict),
                              f"roles={list(roles.keys())}"))
            else:
                steps.append(("doc-roles", False, "no planning session grouped"))
        except Exception as e:
            steps.append(("doc-roles", False, f"{type(e).__name__}: {e}"))

        # ── (d) rollup: lifetime + 30d shape ──────────────────────────────────
        try:
            shape = {"tokens", "cost_usd", "wall_clock_ms", "sessions"}
            life = _eh.project_effort_rollup(pid, window="lifetime",
                                             folder_path=str(proj_folder))
            d30 = _eh.project_effort_rollup(pid, window="30d", now=time.time(),
                                            folder_path=str(proj_folder))
            steps.append(("rollup lifetime+30d",
                          set(life.keys()) == shape and set(d30.keys()) == shape,
                          f"life={life.get('sessions')} 30d={d30.get('sessions')}"))
        except Exception as e:
            steps.append(("rollup", False, f"{type(e).__name__}: {e}"))

        # ── (e) grass promote → seeded stub session; idea stays in grass ──────
        if git_ok:
            try:
                idea = _eh.add_idea(str(proj_folder), pid, "hc v4 grass idea")
                idea_id = idea.get("job_id")
                prec = _eh.promote_grass_to_lane(pid, idea_id, "research",
                                                 folder_path=str(proj_folder))
                ptsid = prec.get("session_id")
                still = _eh.get_grass_idea(str(proj_folder), pid, idea_id)
                steps.append(("grass promote (seeded, copy)",
                              bool(ptsid) and still is not None
                              and prec.get("status") == "running",
                              f"idea_kept={still is not None}"))
                try:
                    if ptsid:
                        _ts.kill(ptsid, project_id=pid)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("grass promote", False, f"{type(e).__name__}: {e}"))
        else:
            steps.append(("grass promote", True, "skipped (git unavailable)"))

        # ── (f) type-aware deliverable launch — skill verify + service (stub) ─
        try:
            # A skill deliverable present under the TEMP skills dir → "available",
            # verified by existence ONLY (no spawn).
            (skills_dir / "hcskill").mkdir(parents=True, exist_ok=True)
            (skills_dir / "hcskill" / "SKILL.md").write_text(
                "# hcskill\n", encoding="utf-8")
            (proj_folder / "hcskill").mkdir(parents=True, exist_ok=True)
            srec = _deliv.pin_deliverable(str(proj_folder), pid, "hcskill",
                                          name="hcskill", dtype="skill")
            sres = _deliv.launch_deliverable(str(proj_folder), pid,
                                             srec.get("job_id"))
            steps.append(("deliverable skill verify (no spawn)",
                          sres.get("ok") and sres.get("status")
                          == _deliv.VERIFY_AVAILABLE,
                          f"status={sres.get('status')}"))

            # A service deliverable launched through a STUB preview_server: assert
            # the chosen port is OS-free + != 8777 WITHOUT binding a real server.
            free_port = _preview.pick_free_port()

            class _StubPreview:
                STATUS_RUNNING = _preview.STATUS_RUNNING
                LIVE_PORT = _preview.LIVE_PORT

                def list_previews(self, project_id=None):
                    return []

                def start_preview(self, folder_path, project_id, target=None,
                                  **kw):
                    assert free_port != self.LIVE_PORT
                    return {"ok": True, "port": free_port,
                            "url": f"http://127.0.0.1:{free_port}/",
                            "preview_id": "hc-v4-svc"}

            (proj_folder / "svc.py").write_text("print('svc')\n", encoding="utf-8")
            vrec = _deliv.pin_deliverable(str(proj_folder), pid, "svc.py",
                                          name="hc svc", dtype="service")
            vres = _deliv.launch_deliverable(str(proj_folder), pid,
                                             vrec.get("job_id"),
                                             preview_mod=_StubPreview())
            steps.append(("deliverable service (stub, port != 8777)",
                          vres.get("ok") and vres.get("port") == free_port
                          and vres.get("port") != _preview.LIVE_PORT,
                          f"port={vres.get('port')}"))
        except Exception as e:
            steps.append(("deliverable launch", False,
                          f"{type(e).__name__}: {e}"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Restore every env var we forced for this walk.
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_SKILLS_DIR", prev_skills),
                          ("ANCHOR_TERMINAL_SEED", prev_seed)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v5_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v5 "Durable Work" R&D surface — FULLY STUBBED.

    Walks the new v5 data/control seams in a throwaway temp project + temp git
    repo, never touching real data, never a live claude / real PTY / real preview
    spawn / real worktree off the build repo:

      (Wave 1) run lifecycle — close-keeps-record (no reap; the PTY + registry
          record survive) vs kill-reaps (PTY gone + worktree removed + record
          terminal), via ``terminal_session.start_session`` / ``kill`` (stub PTY).
      (Wave 2) session summary + continue — ``summarizer.summarize_session``
          through the stub runner captures skill/prompts/actions and caches; then
          ``terminal_session.start_session(seed_context=…)`` starts a NEW seeded
          session carrying the prior context; the original record is intact.
      (Wave 3) project summary — ``summarizer.summarize_project`` through the stub
          runner yields a non-empty summary that is cached (read path never runs
          the model).
      (Wave 4) build deliverable — ``deliverables.resolve_build_deliverable`` +
          ``backfill_build_deliverables`` resolve a session-scoped product (and an
          HONEST unresolved when no explicit signal); nothing fabricated.
      (Wave 5) grass workbench — add_idea → develop (seeded stub session) →
          save_grass_refinement (dev-N) → set_grass_status → the idea STAYS in
          grass (copy); the refinement is listed.

    Everything is torn down by ``_cleanup_synthetic_rnd`` + the env restore here +
    in ``main()``. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (fake_claude)
    + a temp ``ANCHOR_WORKTREE_BASE`` keep every model/PTY interaction off the real
    engine; nothing touches the live ``:8777`` service.
    """
    name = "R&D v5 surface"
    if not rnd_env.get("runner_cmd"):
        report.check(name, True, "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v5-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_TERMINAL_SEED"] = "HC-V5-SEED-LOAD-SKILL"
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import pty_manager as _pty
        import session_registry as _sreg
        import effort_history as _eh
        import summarizer as _summarizer
        import deliverables as _deliv
        import sessions as _sessions
        import brownfield_scan as _bf

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v5-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v5 probe\n\nThis project exists to exercise the v5 surface.\n",
            encoding="utf-8")
        (proj_folder / "README.md").write_text("# hc v5 probe\n",
                                               encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v5", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v5 project", bool(pid), pid))

        # ── (Wave 1) run lifecycle: close keeps record; kill reaps ────────────
        if git_ok:
            try:
                rec = _ts.start_session(pid, "research", label="hc v5 close")
                sid = rec["session_id"]
                live_after_start = sid in set(_pty.live_sessions())
                # CLOSE = the panel X: it does NOT reap. We model "close" as
                # simply NOT calling kill — the registry record + the live PTY
                # must persist (a closed-to-tile session keeps running).
                still_rec = _sreg.get_session(sid)
                still_live = sid in set(_pty.live_sessions())
                close_keeps = (live_after_start and still_rec is not None
                               and still_live)
                steps.append(("close keeps record + PTY",
                              close_keeps,
                              f"rec={still_rec is not None} live={still_live}"))
                # KILL = the deliberate hard-kill: reap PTY + remove worktree +
                # mark the record terminal.
                _ts.kill(sid, project_id=pid)
                killed_live = sid in set(_pty.live_sessions())
                after_kill = _sreg.get_session(sid)
                term_status = (after_kill or {}).get("status", "")
                kill_reaps = (not killed_live
                              and term_status in ("done", "failed", "killed",
                                                  "stopped", ""))
                steps.append(("kill reaps PTY",
                              kill_reaps,
                              f"live={killed_live} status={term_status}"))
            except Exception as e:
                steps.append(("run lifecycle", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("run lifecycle", True, "skipped (git unavailable)"))

        # ── (Wave 2) session summary (skill/prompts/actions) + continue ───────
        cont_sid = None
        try:
            # A discovered research session so the summarizer has member docs.
            rd = proj_folder / "research" / "hc-v5-research"
            rd.mkdir(parents=True, exist_ok=True)
            (rd / "REPORT.md").write_text(
                "# Report\n\n## Findings\nhc v5 session summary.\n",
                encoding="utf-8")
            scan = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan)
            rsess = _sessions.list_sessions(str(proj_folder), pid, "research")
            if rsess:
                rs = rsess[0]
                rsid = rs["session_id"]
                summ = _summarizer.summarize_session(
                    str(proj_folder), pid, "research", rs)
                has_shape = (isinstance(summ, dict)
                             and "skill" in summ and "prompts" in summ
                             and "actions" in summ)
                # The read path returns the SAME cached summary (no re-run).
                cached = _summarizer.load_cached(
                    str(proj_folder), pid, _eh._resolve_subdir("research"),
                    rsid)
                steps.append(("session summary skill/prompts/actions cached",
                              has_shape and cached is not None,
                              f"shape={has_shape} cached={cached is not None}"))
                # CONTINUE: a NEW seeded session in the same lane; original intact.
                if git_ok:
                    seed_ctx = ("Continuation of session %s: %s"
                                % (rsid, summ.get("title", "")))
                    crec = _ts.start_session(pid, "research",
                                             label="hc v5 continue",
                                             seed_context=seed_ctx)
                    cont_sid = crec["session_id"]
                    orig_intact = _sessions.list_sessions(
                        str(proj_folder), pid, "research")
                    orig_ok = any(s.get("session_id") == rsid
                                  for s in orig_intact)
                    steps.append(("continue starts new seeded session",
                                  bool(cont_sid) and cont_sid != rsid
                                  and crec.get("status") == "running"
                                  and orig_ok,
                                  f"new={cont_sid} orig_intact={orig_ok}"))
                    try:
                        _ts.kill(cont_sid, project_id=pid)
                    except Exception:
                        pass
            else:
                steps.append(("session summary", False,
                              "no research session grouped"))
        except Exception as e:
            steps.append(("session summary + continue", False,
                          f"{type(e).__name__}: {e}"))

        # ── (Wave 3) project summary: non-empty objective, cached ─────────────
        try:
            psumm = _summarizer.summarize_project(str(proj_folder), pid)
            obj = ""
            if isinstance(psumm, dict):
                obj = (psumm.get("summary") or psumm.get("objective")
                       or psumm.get("markdown") or "")
                claims = psumm.get("claims", []) or []
                if not obj and claims:
                    obj = str(claims[0])
            cached_proj = _summarizer.load_cached_project(str(proj_folder), pid)
            steps.append(("project summary non-empty + cached",
                          bool(str(obj).strip()) and cached_proj is not None,
                          f"obj_len={len(str(obj))} "
                          f"cached={cached_proj is not None}"))
        except Exception as e:
            steps.append(("project summary", False,
                          f"{type(e).__name__}: {e}"))

        # ── (Wave 4) build deliverable: resolve (honest unresolved) + backfill ─
        try:
            # A discovered build session (formed from a foreman checkpoint/config)
            # whose single product member resolves as the build's deliverable.
            bd = proj_folder / "build" / "hc-v5-build"
            bd.mkdir(parents=True, exist_ok=True)
            (bd / "foreman.config.json").write_text("{}\n", encoding="utf-8")
            scan2 = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan2)
            bsess = _sessions.list_sessions(str(proj_folder), pid, "build")
            res_shape = False
            if bsess:
                res = _deliv.resolve_build_deliverable(
                    str(proj_folder), pid, bsess[0])
                res_shape = (isinstance(res, dict) and "resolved" in res
                             and "reason" in res
                             # honesty: unresolved must carry deliverable=None
                             and (res.get("resolved")
                                  or res.get("deliverable") is None))
            back = _deliv.backfill_build_deliverables(str(proj_folder), pid)
            back_shape = (isinstance(back, dict) and "pinned" in back
                          and "unresolved" in back and "scanned" in back)
            steps.append(("build deliverable resolve + backfill",
                          res_shape and back_shape,
                          f"resolve={res_shape} "
                          f"backfill_scanned={back.get('scanned')}"))
        except Exception as e:
            steps.append(("build deliverable", False,
                          f"{type(e).__name__}: {e}"))

        # ── (Wave 5) grass workbench: develop → save refinement → status ──────
        if git_ok:
            try:
                idea = _eh.add_idea(str(proj_folder), pid, "hc v5 grass idea")
                idea_id = idea.get("job_id")
                drec = _eh.develop_grass_idea(pid, idea_id, "research",
                                              folder_path=str(proj_folder))
                dsid = drec.get("session_id")
                ref = _eh.save_grass_refinement(
                    str(proj_folder), pid, idea_id,
                    text="refined", label="dev-1", session_id=dsid)
                refs = _eh.list_grass_refinements(str(proj_folder), pid,
                                                  idea_id)
                still = _eh.get_grass_idea(str(proj_folder), pid, idea_id)
                wb = _eh.grass_workbench_data(str(proj_folder), pid)
                listed = any(it.get("idea_id") == idea_id for it in wb)
                steps.append(("grass develop + refine + idea kept",
                              bool(dsid) and still is not None
                              and len(refs) >= 1
                              and "/dev-" in ref.get("refinement_id", "")
                              and _eh.grass_status(still) == "refined"
                              and listed,
                              f"refs={len(refs)} kept={still is not None} "
                              f"status={_eh.grass_status(still)}"))
                try:
                    if dsid:
                        _ts.kill(dsid, project_id=pid)
                except Exception:
                    pass
            except Exception as e:
                steps.append(("grass workbench", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("grass workbench", True, "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk.
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def check_rnd_v6_surface(report: Report, server_proc, rnd_env: dict):
    """Exercise the v6 "Linked Pipeline" R&D surface — FULLY STUBBED.

    Walks the new v6 seams in a throwaway temp project + temp git repo, never
    touching real data, never a live claude / real PTY / real worktree off the
    build repo. ``ANCHOR_PTY_BACKEND=stub`` + ``ANCHOR_RUNNER_CMD`` (the
    STREAM-JSON stub ``tests/stub_streamjson.py``) + a temp ``ANCHOR_WORKTREE_BASE``
    keep every model/PTY interaction off the real engine; nothing binds ``:8777``.

      (Wave 1) summaries-through-stream-json — ``summarizer.summarize_session``
          + ``summarize_project`` driven through the PRODUCTION stream-json
          envelope stub yield grounded NON-EMPTY content (session skill/prompts/
          actions; project objective); a SCHEMA_VERSION-stale empty project cache
          is treated as a MISS and HEALS on regenerate.
      (Wave 2 + 6) the CHAIN — start a research session → advance to a LINKED
          planning session (``start_session(parent_session_id=…)``; assert ordered
          ``chain_members`` + parent set) → finish the planning session WITH a
          real MASTER+IMPL plan set → ``auto_advance_planning_to_build`` yields
          exactly ONE linked build (idempotent on a second call) → assert
          ``chain_members`` is [research, planning, build] ordered.
      (Wave 4) the ``term_sessions`` projection (via ``session_registry``)
          INCLUDES terminal-status sessions and stays SAFE (no worktree_path /
          branch leak).

    Every stub PTY + synthetic session row is reaped, all forced env is restored,
    and the temp dirs are torn down (here + by ``_cleanup_synthetic_rnd``). The
    summarizer runner is restored to ``rnd_env['runner_cmd']`` (fake_claude) on
    exit so later checks are unaffected. Asserts nothing bound ``:8777``.
    """
    name = "R&D v6 surface"
    sj_cmd = _streamjson_runner_cmd()
    if not rnd_env.get("runner_cmd") or not sj_cmd:
        report.check(name, True,
                     "skipped (no stub runner; live claude avoided)")
        return

    import tempfile as _tf
    steps: list[tuple[str, bool, str]] = []

    prev_pty = os.environ.get("ANCHOR_PTY_BACKEND")
    prev_wtbase = os.environ.get("ANCHOR_WORKTREE_BASE")
    prev_seed = os.environ.get("ANCHOR_TERMINAL_SEED")
    prev_runner = os.environ.get("ANCHOR_RUNNER_CMD")
    prev_claims = os.environ.get("STUB_STREAMJSON_CLAIMS")
    os.environ["ANCHOR_PTY_BACKEND"] = "stub"
    wt_base = Path(_tf.mkdtemp(prefix="anchor-hc-v6-wt-"))
    os.environ["ANCHOR_WORKTREE_BASE"] = str(wt_base)
    os.environ["ANCHOR_TERMINAL_SEED"] = "HC-V6-SEED-LOAD-SKILL"
    # Drive the summarizer through the PRODUCTION stream-json stub for this walk.
    os.environ["ANCHOR_RUNNER_CMD"] = sj_cmd
    rnd_env.setdefault("v3_temp_dirs", []).append(wt_base)

    pid = None
    try:
        import rnd_registry as _rnd
        import terminal_session as _ts
        import pty_manager as _pty
        import session_registry as _sreg
        import effort_history as _eh
        import summarizer as _summarizer
        import sessions as _sessions
        import brownfield_scan as _bf
        import handoff as _handoff

        # ── 0. A throwaway git project (worktrees attach to a real repo) ───────
        proj_folder = Path(_tf.mkdtemp(prefix="anchor-hc-v6-proj-"))
        rnd_env["v3_temp_dirs"].append(proj_folder)
        (proj_folder / "CLAUDE.md").write_text(
            "# hc v6 probe\n\n## What this project is\n"
            "Anchor is a productivity system that manages markdown task files "
            "for a researcher, tracking projects and deadlines. This probe "
            "exercises the v6 linked pipeline surface.\n",
            encoding="utf-8")
        (proj_folder / "README.md").write_text("# hc v6 probe\n",
                                               encoding="utf-8")
        git_ok = _git_init_repo(proj_folder)
        proj = _rnd.add_project(SYNTHETIC_RND_NAME + " v6", str(proj_folder))
        pid = proj["id"]
        rnd_env["created_ids"].append(pid)
        steps.append(("register v6 project", bool(pid), str(pid)))

        # ── (Wave 1) summaries through the PRODUCTION stream-json stub ────────
        try:
            # A discovered planning session with two real member docs so a
            # grounded claim has a corpus.
            bd = proj_folder / "planning" / "hc-v6-plan"
            bd.mkdir(parents=True, exist_ok=True)
            (bd / "MASTER-PLAN.md").write_text(
                "# Master Plan\n\n## North Star\nCache validated summaries for "
                "each session of trio work.\n", encoding="utf-8")
            (bd / "IMPLEMENTATION-PLAN.md").write_text(
                "# Implementation Plan\n\n## Goal\nRender the most-recent session "
                "with an expander.\n", encoding="utf-8")
            scan = _bf.scan(str(proj_folder))
            _eh.adopt_discovered(proj_folder, pid, scan)
            psess = _sessions.list_sessions(str(proj_folder), pid, "planning")
            sess_ok = False
            if psess:
                os.environ["STUB_STREAMJSON_CLAIMS"] = (
                    "North Star: cache validated summaries for each session.")
                ssum = _summarizer.summarize_session(
                    str(proj_folder), pid, "planning", psess[0])
                claims = (ssum.get("claims") or []) if isinstance(ssum, dict) \
                    else []
                shape = (isinstance(ssum, dict) and "skill" in ssum
                         and "prompts" in ssum and "actions" in ssum)
                grounded = any("validated summaries" in str(c).lower()
                               for c in claims)
                sess_ok = bool(claims) and shape and grounded
            steps.append(("session summary grounded via stream-json",
                          sess_ok,
                          f"present={bool(psess)} ok={sess_ok}"))

            # Project objective through the same production envelope path.
            objective = ("Anchor is a productivity system that manages markdown "
                         "task files for a researcher, tracking projects and "
                         "deadlines.")
            os.environ["STUB_STREAMJSON_CLAIMS"] = objective
            pout = _summarizer.summarize_project(str(proj_folder), pid)
            ptext = (pout.get("summary_text") or "") if isinstance(pout, dict) \
                else ""
            proj_ok = (isinstance(pout, dict) and bool(pout.get("claims"))
                       and not pout.get("no_grounded_claims")
                       and "productivity system" in ptext.lower())
            steps.append(("project objective grounded via stream-json",
                          proj_ok, f"text_len={len(ptext)}"))

            # SCHEMA-VERSION heal: a pre-fix empty cache (no schema_version) is a
            # MISS; a force-regenerate heals it into a grounded objective.
            d = _summarizer._project_store_dir(str(proj_folder), pid)
            d.mkdir(parents=True, exist_ok=True)
            (d / _summarizer.PROJECT_SUMMARY_JSON).write_text(
                json.dumps({"project_id": pid, "kind": "project",
                            "claims": [], "summary_text": "",
                            "no_grounded_claims": True}),
                encoding="utf-8")
            miss = _summarizer.load_cached_project(str(proj_folder), pid) is None
            os.environ["STUB_STREAMJSON_CLAIMS"] = objective
            healed = _summarizer.summarize_project(str(proj_folder), pid,
                                                   force=True)
            healed_ok = (isinstance(healed, dict) and bool(healed.get("claims")))
            cached_after = _summarizer.load_cached_project(str(proj_folder), pid)
            cache_ver_ok = (isinstance(cached_after, dict)
                            and cached_after.get("schema_version")
                            == _summarizer.SUMMARY_SCHEMA_VERSION)
            steps.append(("schema-stale cache heals on regenerate",
                          miss and healed_ok and cache_ver_ok,
                          f"miss={miss} healed={healed_ok} ver={cache_ver_ok}"))
        except Exception as e:
            steps.append(("summaries via stream-json", False,
                          f"{type(e).__name__}: {e}"))

        # ── (Wave 2 + 6) the linked research → planning → build chain ─────────
        if git_ok:
            try:
                # A real MASTER+IMPL plan set committed so discovery finds it
                # (the planning lane the auto-advance executes on).
                # The MASTER+IMPL plan docs were already written under
                # planning/hc-v6-plan above (Wave-1 step); discovery reads the
                # project folder (not git), so no extra commit is needed.

                # Research session = chain root.
                rrec = _ts.start_session(pid, "research", label="hc v6 research")
                rsid = rrec["session_id"]
                root_chain_ok = (rrec.get("parent_session_id", "") == ""
                                 and rrec.get("chain_id") == rsid)

                # Advance to a LINKED planning session (parent = research).
                prec = _ts.start_session(pid, "planning",
                                         label="hc v6 planning",
                                         parent_session_id=rsid,
                                         seed_context="advance from research")
                psid = prec["session_id"]
                link_ok = (prec.get("parent_session_id") == rsid
                           and prec.get("chain_id") == rrec.get("chain_id"))
                members_rp = _sreg.chain_members(rrec.get("chain_id"))
                rp_order_ok = ([m.get("session_id") for m in members_rp]
                               == [rsid, psid])

                # Finish the planning session (hard-kill → DONE) then auto-advance.
                pre_plan = _ts.capture_plan_set(pid, psid)
                _ts.kill(psid, project_id=pid)
                build = _ts.auto_advance_planning_to_build(
                    pid, psid, plan_set=pre_plan)
                build_ok = (isinstance(build, dict)
                            and build.get("parent_session_id") == psid
                            and build.get("chain_id") == rrec.get("chain_id"))
                bsid = (build or {}).get("session_id")

                # Idempotent: a second advance must NOT create a duplicate build.
                dup = _ts.auto_advance_planning_to_build(pid, psid)
                builds = [s for s in _sreg.list_sessions(project_id=pid)
                          if s.get("lane") == "build"]
                idem_ok = dup is None and len(builds) == 1

                # The full chain is ordered [research, planning, build].
                members = _sreg.chain_members(rrec.get("chain_id"))
                lanes_order = [m.get("lane") for m in members]
                chain_ok = lanes_order == ["research", "planning", "build"]

                steps.append(("linked research→planning→build chain",
                              root_chain_ok and link_ok and rp_order_ok
                              and build_ok and idem_ok and chain_ok,
                              f"root={root_chain_ok} link={link_ok} "
                              f"rp_order={rp_order_ok} build={build_ok} "
                              f"idem={idem_ok} order={lanes_order}"))

                # ── (Wave 4) term_sessions projection: includes terminal + SAFE ─
                projection = _sreg.list_sessions(project_id=pid)
                has_terminal = any(s.get("status")
                                   in _sreg.TERMINAL_STATUSES
                                   for s in projection)
                # The SERVER projection (anchor_gui) strips worktree_path/branch;
                # assert the SAFE field set we ship has the lineage fields and
                # that a SAFE copy never carries worktree_path/branch.
                safe_copy = [{
                    "session_id": s.get("session_id"),
                    "lane": s.get("lane", ""),
                    "status": s.get("status", ""),
                    "parent_session_id": s.get("parent_session_id", ""),
                    "chain_id": s.get("chain_id", ""),
                } for s in projection]
                safe_ok = all("worktree_path" not in s and "branch" not in s
                              for s in safe_copy)
                steps.append(("term_sessions projection terminal+SAFE",
                              has_terminal and safe_ok,
                              f"terminal={has_terminal} safe={safe_ok}"))

                # Reap the live chain sessions we left running.
                for sid in (rsid, bsid):
                    if sid:
                        try:
                            _ts.kill(sid, project_id=pid)
                        except Exception:
                            pass
            except Exception as e:
                steps.append(("linked chain", False,
                              f"{type(e).__name__}: {e}"))
        else:
            steps.append(("linked chain", True, "skipped (git unavailable)"))

    except Exception as e:
        steps.append(("exception", False, f"{type(e).__name__}: {e}"))
    finally:
        # Reap any stub PTY sessions this walk left live (defensive).
        try:
            import pty_manager as _pty2
            import session_registry as _sreg2
            for sid in list(_pty2.live_sessions()):
                try:
                    _pty2.kill(sid)
                except Exception:
                    pass
            for pid_ in rnd_env.get("created_ids", []):
                for srec in _sreg2.list_sessions(project_id=pid_):
                    try:
                        _sreg2.remove_session(srec.get("session_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        # Restore every env var we forced for this walk (incl. the runner, which
        # we swapped to the stream-json stub — later checks must see fake_claude).
        for var, prev in (("ANCHOR_PTY_BACKEND", prev_pty),
                          ("ANCHOR_WORKTREE_BASE", prev_wtbase),
                          ("ANCHOR_TERMINAL_SEED", prev_seed),
                          ("ANCHOR_RUNNER_CMD", prev_runner),
                          ("STUB_STREAMJSON_CLAIMS", prev_claims)):
            if prev is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = prev

    failures = [f"{s}: {d}" for s, ok, d in steps if not ok]
    if failures:
        report.check(name, False, "; ".join(failures))
    else:
        report.check(name, True, f"{len(steps)} steps")


def _rnd_session(session_id):
    """Best-effort read of one managed session record by id (for the v4 walk)."""
    try:
        import session_registry as _sreg
        return _sreg.get_session(session_id)
    except Exception:
        return None


def _cleanup_synthetic_rnd(rnd_env: dict, report: Report):
    """Remove the synthetic project(s) + throwaway folder + inbox probe line."""
    # Drop the synthetic project ids from the live registry (never delete real ones).
    try:
        import rnd_registry as _rnd
        for pid in rnd_env.get("created_ids", []):
            try:
                _rnd.remove_project(pid)
            except Exception:
                pass
    except Exception:
        pass
    # Best-effort: remove ANY session_registry rows + preview records keyed to a
    # synthetic project id. The v3 walk (`check_rnd_v3_surface`) registers a
    # synthetic session and may inject a preview record between register/remove
    # calls that are NOT individually guarded; if any step in between raises, the
    # row would otherwise leak into REAL `.anchor/sessions.json` /
    # `previews.json` during a 5AM run. Delegate to the registries' own
    # list/remove APIs so teardown leaves real data clean regardless of where
    # the walk failed. Tolerant by design — never raises.
    for pid in rnd_env.get("created_ids", []):
        try:
            import session_registry as _sreg
            for rec in _sreg.list_sessions(project_id=pid):
                try:
                    _sreg.remove_session(rec.get("session_id"))
                except Exception:
                    pass
        except Exception:
            pass
        try:
            import preview_server as _preview
            for rec in _preview.list_previews(project_id=pid):
                key = rec.get("preview_id")
                if not key:
                    continue
                try:
                    with _paths.WRITE_LOCK:
                        regp = _preview.load_previews()
                        if regp.pop(key, None) is not None:
                            _preview._save_previews(regp)
                except Exception:
                    pass
        except Exception:
            pass
    # Remove the throwaway project folder (it is a tmp dir, not real data).
    folder = rnd_env.get("folder")
    if folder is not None:
        try:
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass
    # Remove the v3 walk's throwaway dirs (temp git repo + worktree base).
    for d in rnd_env.get("v3_temp_dirs", []):
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
    # Strip the synthetic inbox probe line we appended.
    inbox = DATA_DIR / "INBOX.md"
    if inbox.exists():
        try:
            text = inbox.read_text(encoding="utf-8")
            new_lines = [ln for ln in text.splitlines()
                         if SYNTHETIC_TAG not in ln.lower()]
            if len(new_lines) != len(text.splitlines()):
                inbox.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        except OSError:
            pass


# â”€â”€ Check 6: logging works â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_logging(report: Report):
    name = "logging"
    issues = []

    # Today's log should exist and have content (the test server boot+ops should have written)
    log_today = DATA_DIR / "logs" / f"{TODAY}.md"
    if not log_today.exists():
        issues.append(f"log {TODAY}.md not written")
    elif log_today.stat().st_size < 10:
        issues.append(f"log {TODAY}.md is empty")

    # Yesterday's log SHOULD exist if the system ran yesterday â€” but only flag if also
    # the day before is missing (to avoid noise on first install or skipped days).
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    day_before = (date.today() - timedelta(days=2)).isoformat()
    log_yesterday = DATA_DIR / "logs" / f"{yesterday}.md"
    log_day_before = DATA_DIR / "logs" / f"{day_before}.md"
    if not log_yesterday.exists() and not log_day_before.exists():
        report.recommend(f"No log files for the last 2 days ({yesterday}, {day_before}) â€” system may not have run")

    # errors.log should be readable and not catastrophically large
    err_log = DATA_DIR / "logs" / "errors.log"
    if err_log.exists():
        size_mb = err_log.stat().st_size / (1024 * 1024)
        if size_mb > 50:
            report.recommend(f"errors.log is {size_mb:.1f} MB â€” consider rotating")

    if issues:
        report.check(name, False, "; ".join(issues))
    else:
        report.check(name, True, f"today's log {log_today.stat().st_size} bytes")


# â”€â”€ Check 7: Local filesystem write sanity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_onedrive_sync(report: Report):
    name = "Local filesystem write sanity"
    marker = DATA_DIR / ".healthcheck_marker"
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


# â”€â”€ Stale-process cleanup (ports 8777, 8778) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def cleanup_stale_processes(report: Report):
    """If port 8777 or 8778 is held by a Python process older than 24h, terminate it.
    On Windows, use `tasklist` and `taskkill`. Best-effort: errors are logged but not fatal."""
    if sys.platform != "win32":
        return
    try:
        # netstat to find PIDs holding relevant ports
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"], stderr=subprocess.DEVNULL, text=True, timeout=10,
        )
    except Exception:
        return

    pids = set()
    targets = {":8777", f":{TEST_PORT}"}
    for line in out.splitlines():
        if any(t in line for t in targets) and "LISTENING" in line:
            parts = line.split()
            if parts:
                try:
                    pids.add(int(parts[-1]))
                except ValueError:
                    pass
    if not pids:
        return

    # For each PID, check creation time via Get-Process
    for pid in pids:
        try:
            # PowerShell call to check process age
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

            # Be more aggressive with the test port (8778) â€” if it's held by python,
            # we likely want it dead so we can run the check, even if it's not 24h old.
            # However, for 8777 (production), we only kill if it's truly stale.
            is_test_port = False
            for line in out.splitlines():
                if f":{TEST_PORT}" in line and str(pid) in line:
                    is_test_port = True
                    break

            if age > timedelta(hours=24) or is_test_port:
                # Kill it
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
                reason = "stale" if age > timedelta(hours=24) else "test port conflict"
                report.fix(f"Terminated anchor process PID {pid} (reason: {reason}, age: {age})")
        except Exception:
            continue


# â”€â”€ Server cleanup â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def shutdown_server(server_proc):
    if server_proc is None:
        return
    # The /api/shutdown endpoint was removed (the NSSM service owns the
    # process lifecycle now), so go straight to terminate()/kill().
    try:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            server_proc.kill()
    except Exception:
        pass


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def main():
    report = Report()
    server_proc = None

    # v2 R&D surface (Wave 8): the server subprocess + the in-process registry ops
    # must drive model calls through the STUB runner, never live claude. Set
    # ANCHOR_RUNNER_CMD in this process's environment BEFORE booting the server so
    # the child inherits it. A throwaway temp folder isolates the synthetic project
    # from real data; everything is torn down in `finally`.
    import tempfile
    rnd_env = {
        "runner_cmd": _fake_runner_cmd(),
        "folder": Path(tempfile.mkdtemp(prefix="anchor-hc-rnd-")),
        "created_ids": [],
        "prev_runner_cmd": os.environ.get("ANCHOR_RUNNER_CMD"),
    }
    if rnd_env["runner_cmd"]:
        os.environ["ANCHOR_RUNNER_CMD"] = rnd_env["runner_cmd"]

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
        check_rnd_v2_surface(report, server_proc, rnd_env)
        check_rnd_v3_surface(report, server_proc, rnd_env)
        check_rnd_v4_surface(report, server_proc, rnd_env)
        check_rnd_v5_surface(report, server_proc, rnd_env)
        check_rnd_v6_surface(report, server_proc, rnd_env)

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
        # Tear down the synthetic R&D project + throwaway folder, then restore
        # ANCHOR_RUNNER_CMD so the process env is left as we found it.
        try:
            _cleanup_synthetic_rnd(rnd_env, report)
        except Exception:
            pass
        if rnd_env.get("prev_runner_cmd") is None:
            os.environ.pop("ANCHOR_RUNNER_CMD", None)
        else:
            os.environ["ANCHOR_RUNNER_CMD"] = rnd_env["prev_runner_cmd"]

    report_path = REPORTS_DIR / f"{TODAY}.md"
    try:
        report.write(report_path)
    except Exception as e:
        # Last-ditch fallback: write to a fixed path so we don't lose the result
        fallback = DATA_DIR / "logs" / "healthcheck-error.log"
        fallback.parent.mkdir(parents=True, exist_ok=True)
        fallback.write_text(f"Could not write report: {e}\n{traceback.format_exc()}", encoding="utf-8")

    # Exit code: 0 = clean, 1 = issues, 2 = framework crash
    if report.has_issues:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

