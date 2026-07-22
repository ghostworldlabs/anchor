"""Tidy-Idy thin caller for Anchor.

Dispatches the tool's own entry point (``bin/tidy-idy.mjs``) via
:func:`job_runner.launch_guarded` and returns the panel handoff URL.

No launch/archive/panel logic lives here — that is all owned by the tidy-idy
tool. This module is only a dispatcher + URL opener surface for the project
window's Tidy-Idy button.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import job_runner

#: Env override for the tidy-idy CLI entry (absolute path to tidy-idy.mjs).
ENTRY_ENV = "ANCHOR_TIDY_IDY_ENTRY"

#: Well-known locations, newest first.
_DEFAULT_CANDIDATES = (
    Path(r"C:\dev\skill-foundry-tidyidy-wt\skills\tidy-idy\bin\tidy-idy.mjs"),
    Path(r"C:\dev\Skill Foundry\skills\tidy-idy\bin\tidy-idy.mjs"),
    Path.home() / ".claude" / "skills" / "tidy-idy" / "bin" / "tidy-idy.mjs",
)

BUILD_LANE = "build"
TIDY_JOB_TYPE = "tidy"
PANEL_READY_EVENT = "panel-ready"


def resolve_entry() -> Path | None:
    """Return the path to ``tidy-idy.mjs``, or None if not installed."""
    env = (os.environ.get(ENTRY_ENV) or "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p.resolve()
    for c in _DEFAULT_CANDIDATES:
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def build_command(root_path: str | Path, *, entry: Path | None = None,
                  nonce_file: str | Path | None = None,
                  node: str | None = None) -> list[str]:
    """Argv for job_runner's ``command=`` seam (verbatim local code, no model)."""
    entry = entry or resolve_entry()
    if entry is None:
        raise FileNotFoundError(
            f"tidy-idy entry not found; set {ENTRY_ENV} to bin/tidy-idy.mjs "
            "or install the skill under Skill Foundry / the tidy-idy worktree"
        )
    root = str(Path(root_path).resolve())
    cmd = [
        node or "node",
        str(entry),
        root,
        "--environment=anchor",
        "--json",
    ]
    if nonce_file:
        cmd.append(f"--nonce-file={Path(nonce_file)}")
    return cmd


def _read_log_text(job_id: str) -> str:
    path = job_runner.log_path_for(job_id)
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def parse_panel_ready(text: str) -> dict | None:
    for line in str(text or "").splitlines():
        t = line.strip()
        if not t.startswith("{"):
            continue
        try:
            obj = json.loads(t)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("event") == PANEL_READY_EVENT:
            return obj
    return None


def read_bootstrap_file(path: str | Path) -> dict | None:
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) and obj.get("url") else None


def wait_for_panel(job_id: str, *, timeout_s: float = 120.0,
                   poll_s: float = 0.25) -> dict | None:
    """Poll the durable job log for the tool's ``panel-ready`` line."""
    deadline = time.time() + max(1.0, float(timeout_s))
    while time.time() < deadline:
        found = parse_panel_ready(_read_log_text(job_id))
        if found:
            return found
        rec = job_runner.load_record(job_id)
        if rec and rec.get("status") not in (None, "running"):
            return None
        time.sleep(poll_s)
    return None


def launch_tidy_idy(project_id: str, folder_path: str | Path, *,
                    wait_for_panel_s: float = 180.0) -> dict:
    """Thin-caller launch. Returns a JSON-serializable handoff dict."""
    root = Path(folder_path).resolve()
    if not root.is_dir():
        return {"ok": False, "error": f"folder not found: {root}", "code": "no-folder"}

    entry = resolve_entry()
    if entry is None:
        return {
            "ok": False,
            "error": (
                f"tidy-idy CLI not installed (looked for bin/tidy-idy.mjs). "
                f"Set {ENTRY_ENV} or install the skill."
            ),
            "code": "no-entry",
        }

    nonce_dir = Path(tempfile.gettempdir()) / "anchor-tidy-idy"
    nonce_dir.mkdir(parents=True, exist_ok=True)
    nonce_file = nonce_dir / f"nonce-{project_id}-{int(time.time() * 1000)}.json"

    try:
        command = build_command(root, entry=entry, nonce_file=nonce_file, node="node")
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e), "code": "no-entry"}

    try:
        rec = job_runner.launch_guarded(
            BUILD_LANE,
            project_id,
            str(root),
            cwd=str(root),
            gated=False,
            command=command,
        )
    except job_runner.LaneBusyError as e:
        return {
            "ok": False,
            "error": getattr(e, "message", None) or str(e),
            "code": getattr(e, "reason", "busy"),
            "holder": getattr(e, "holder", None),
        }
    except Exception as e:  # noqa: BLE001 — surface to UI, never crash the server
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "code": "launch-failed"}

    job_id = rec.get("job_id")
    # Stamp job_type for UI/history without changing job_runner schema.
    try:
        job_runner._update_record(job_id, job_type=TIDY_JOB_TYPE)  # noqa: SLF001
    except Exception:
        pass

    ready = wait_for_panel(job_id, timeout_s=wait_for_panel_s) if job_id else None
    bootstrap_url = None
    if ready and ready.get("bootstrapFile"):
        boot = read_bootstrap_file(ready["bootstrapFile"])
        bootstrap_url = boot.get("url") if boot else None
    if not bootstrap_url and ready and ready.get("bootstrapUrl"):
        bootstrap_url = ready.get("bootstrapUrl")

    return {
        "ok": True,
        "job_id": job_id,
        "job_type": TIDY_JOB_TYPE,
        "lane": BUILD_LANE,
        "entry": str(entry),
        "folder_path": str(root),
        "status": rec.get("status"),
        "log_path": rec.get("log_path"),
        "panel": ready,
        "open_url": bootstrap_url,
        "panel_base": (ready or {}).get("baseUrl") or (ready or {}).get("url"),
        "contributed_launch_logic": False,
        "contributed_archive_logic": False,
        "contributed_panel_logic": False,
    }
