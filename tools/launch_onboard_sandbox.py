#!/usr/bin/env python3
"""Launch the Anchor Guided Onboarding & First-Run Setup Wizard in Sandbox Walkthrough Mode.

Usage:
    python tools/launch_onboard_sandbox.py [--reset] [--no-browser] [--port 8777]

In Sandbox Walkthrough Mode (?sandbox=1):
  - Existing live Anchor processes (anchor.exe) and existing Tailscale daemon state
    are ignored / treated as a clean first-run slate.
  - All wizard state, user profile, readiness receipts, and test changes write
    only to the isolated sandbox directory (<data_dir>/onboard_sandbox/) without
    modifying live production state unless the user clicks "Apply Sandbox to Live".
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import onboard_wizard


def _is_anchor_listening(port: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/onboard-wizard/state?sandbox=1")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Launch Anchor Onboarding Wizard in Sandbox Walkthrough Mode")
    parser.add_argument("--reset", action="store_true", help="Reset sandbox state before opening")
    parser.add_argument("--no-browser", action="store_true", help="Print URL and state without opening browser")
    parser.add_argument("--port", type=int, default=8777, help="Anchor HTTP port (default: 8777)")
    args = parser.parse_args(argv)

    if args.reset:
        onboard_wizard.reset_sandbox()

    state = onboard_wizard.get_wizard_full_state(sandbox=True)
    url = f"http://127.0.0.1:{args.port}/onboard-wizard?sandbox=1"

    print("=" * 72)
    print("  ANCHOR ONBOARDING WIZARD — SANDBOX WALKTHROUGH MODE")
    print("=" * 72)
    print(f"  Sandbox Data Dir : {state.get('data_dir')}")
    print(f"  Wizard URL       : {url}")
    print("  Isolation        : Ignores existing anchor.exe & Tailscale daemon;")
    print("                     writes only to onboard_sandbox/ until explicitly applied.")
    print("=" * 72)

    if args.no_browser:
        return 0

    if _is_anchor_listening(args.port):
        webbrowser.open(url)
        print(f"Opened {url} in your default browser.")
        return 0

    # If Anchor is not currently listening on args.port, start a lightweight local preview server
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse
    import json

    class _SandboxPreviewHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *a: object) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            q = parse_qs(parsed.query)
            is_sb = str((q.get("sandbox") or ["1"])[0]).strip().lower() not in ("0", "false", "no")
            if parsed.path in ("/", "/onboard-wizard", "/onboard"):
                body = onboard_wizard.render_onboard_wizard_html(sandbox=is_sb).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/onboard-wizard/state":
                payload = json.dumps(onboard_wizard.get_wizard_full_state(sandbox=is_sb)).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/onboard-wizard/action":
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                try:
                    data = json.loads(raw)
                except Exception:
                    data = {}
                is_sb = bool(data.get("sandbox", True))
                act = str(data.get("action") or "").strip()
                out = onboard_wizard.dispatch_wizard_action(act, data, sandbox=is_sb)
                payload = json.dumps(out).encode("utf-8")
                self.send_response(200 if out.get("ok") else 400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), _SandboxPreviewHandler)
    actual_port = server.server_address[1]
    preview_url = f"http://127.0.0.1:{actual_port}/onboard-wizard?sandbox=1"
    print(f"Anchor service not detected on port {args.port}; serving standalone sandbox wizard at:")
    print(f"  {preview_url}")
    webbrowser.open(preview_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped sandbox preview server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
