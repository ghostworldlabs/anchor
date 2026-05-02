"""
Anchor Dashboard Launcher
Double-click this file (or the taskbar shortcut) to start the Anchor dashboard.
No terminal window — runs silently and opens your browser.

Launch sequence:
  1. If an Anchor server is already on port 8777, ask it to shut down cleanly.
  2. Wait briefly; if the port is still held, force-kill whatever owns it.
  3. Start anchor_gui.py fresh so it parses the latest DASHBOARD.md.

This avoids the "zombie server" problem where Chrome was closed without
cleanly stopping the Python process, leaving a stale server holding the
port and serving pre-edit file contents.
"""

import subprocess
import sys
import os
import time
import socket
import urllib.request
import urllib.error

PORT = 8777
SHUTDOWN_URL = f"http://localhost:{PORT}/api/shutdown"
WAIT_AFTER_SHUTDOWN_S = 2.0
POLL_INTERVAL_S = 0.1


def port_in_use(port: int) -> bool:
    """Return True if something is accepting connections on this local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False


def try_clean_shutdown() -> None:
    """Send POST /api/shutdown to the running server (no-op if nothing there)."""
    if not port_in_use(PORT):
        return
    try:
        req = urllib.request.Request(SHUTDOWN_URL, data=b"", method="POST")
        urllib.request.urlopen(req, timeout=2)
    except (urllib.error.URLError, TimeoutError, OSError):
        # Server may have died mid-request or not exposed shutdown — that's fine,
        # we'll force-kill on the next step if the port is still held.
        pass


def wait_for_port_free(timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if not port_in_use(PORT):
            return True
        time.sleep(POLL_INTERVAL_S)
    return not port_in_use(PORT)


def kill_stragglers() -> None:
    """Force-kill whatever Windows process is holding port 8777."""
    if not port_in_use(PORT) or sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        pids = set()
        for line in result.stdout.splitlines():
            # Match lines like "  TCP    127.0.0.1:8777    0.0.0.0:0    LISTENING    12345"
            if f":{PORT} " in line and "LISTENING" in line:
                parts = line.split()
                if parts and parts[-1].isdigit():
                    pids.add(parts[-1])
        for pid in pids:
            subprocess.run(
                ["taskkill", "/F", "/PID", pid],
                capture_output=True, timeout=5
            )
    except Exception:
        # Last-resort fallback: kill all silent-python processes.
        # Broad, but matches the advice in CLAUDE.md.
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", "pythonw.exe"],
                capture_output=True, timeout=5
            )
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────────────────

script_dir = os.path.dirname(os.path.abspath(__file__))
gui_script = os.path.join(script_dir, "anchor_gui.py")

if not os.path.exists(gui_script):
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        0,
        f"anchor_gui.py not found in:\n{script_dir}",
        "Anchor Error",
        0x10  # MB_ICONERROR
    )
    sys.exit(1)

# 1. Graceful shutdown (if anything is listening).
try_clean_shutdown()

# 2. Wait for the port to go idle; force-kill if it won't.
if not wait_for_port_free(WAIT_AFTER_SHUTDOWN_S):
    kill_stragglers()
    # Give the OS a beat to release the port after the kill.
    wait_for_port_free(1.5)

# 3. Launch anchor_gui.py fresh. It will open the browser itself.
subprocess.Popen(
    [sys.executable, gui_script],
    cwd=script_dir,
    creationflags=0x00000008 if sys.platform == "win32" else 0,  # DETACHED_PROCESS
)
