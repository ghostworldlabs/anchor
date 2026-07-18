"""Anchor Doctor UI V3 — STUB GATE (planning/anchor-doctor-ui/handoff).

Wave 1 — "Rip out the API-key backend + swept-in scratch":
 - the V2 Gemini API-key agent, its tests/mocks, the standalone-product mock
   page, and the scratch files swept into master by 65e93e1 are DELETED and
   stay deleted;
 - NO module in the repo imports the third-party Gemini SDK (the repo is
   stdlib-only; distro.py's import scan is the broader enforcement, this gate
   pins the specific V2 regression);
 - POST /api/doctor/run no longer routes to a Gemini API wrapper — the V2
   handler is gone entirely (an unmatched POST falls through to the 404), and
   anchor_gui no longer references the deleted agent script or spawns anything
   synchronously for the doctor surface.

All model seams are stubbed suite-wide by tests/conftest.py
(ANCHOR_PTY_BACKEND=stub + ANCHOR_RUNNER_CMD -> tests/fake_claude.py); no test
here spawns a live model, a real ConPTY, or the :8777 service.

NOTE ON THIS FILE: it ships via the manifest glob (tests/test_*.py) and the
wave's done-when is "zero repo references" to the forbidden SDK — so, exactly
like tests/test_distro_scan.py does for the personal email, the forbidden
module name and the deleted agent-script name are ASSEMBLED AT RUNTIME, never
stored as contiguous literals in this file's source.
"""
import io
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The forbidden third-party Gemini SDK module, assembled at runtime so this
# file itself adds no repo reference to it.
_GEMINI_SDK = "google" + "." + "generat" + "iveai"

# The deleted V2 agent script's module name, likewise assembled.
_AGENT_MODULE = "anchor_" + "doctor_" + "agent"

# Everything wave 1 deletes, repo-relative (POSIX separators).
_DELETED = [
    _AGENT_MODULE + ".py",
    "test_doctor.py",
    "test/test_doctor_ui.mjs",
    "prototypes.html",
    "test.py",
    "test_quote.js",
    "test_agy_out.txt",
    "touch_loop.ps1",
]

# Directories never scanned for imports: VCS/data/caches, frozen archives, and
# vendored third-party assets (same exclusion idiom as distro.py's scan).
_SKIP_DIRS = {".git", ".anchor", "__pycache__", "_archive", "_mockups",
              "node_modules", "vendor"}

# An import statement pulling in the `google` namespace package in ANY form
# (spelled `google.<sdk>` here so this file honors its own contiguous-literal
# ban, per the NOTE in the module docstring):
#   import google.<sdk> [as x] / from google.<sdk>[.sub] import y
#   from google import <sdk> / import google
_GOOGLE_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+google(?:[.\s]|$)|from\s+google(?:[.\s]))",
    re.MULTILINE,
)


def _repo_python_files():
    """Every .py file in the repo outside the skipped dirs."""
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        yield rel.as_posix(), path


# ── Wave 1: the deleted files STAY deleted ───────────────────────────────────

@pytest.mark.parametrize("rel", _DELETED)
def test_deleted_file_stays_deleted(rel):
    assert not (REPO_ROOT / rel).exists(), (
        f"{rel} was deleted in doctor-V3 wave 1 and must stay deleted")


# ── Wave 1: no module in the repo imports the Gemini SDK ─────────────────────

def test_no_module_imports_gemini_sdk():
    offenders = []
    for rel, path in _repo_python_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _GEMINI_SDK in text or _GOOGLE_IMPORT_RE.search(text):
            offenders.append(rel)
    assert offenders == [], (
        f"module(s) reference/import the forbidden Gemini SDK: {offenders}")


def test_no_module_references_deleted_agent_script():
    """The deleted V2 agent module is referenced by NO repo .py file (this gate
    file holds only assembled fragments, so it passes its own scan)."""
    offenders = []
    for rel, path in _repo_python_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if _AGENT_MODULE in text:
            offenders.append(rel)
    assert offenders == [], (
        f"module(s) still reference the deleted V2 agent script: {offenders}")


# ── Wave 1: /api/doctor/run no longer routes to a Gemini API wrapper ─────────

def _post(gui, path, body_dict):
    """Drive anchor_gui's real do_POST without a socket (suite FakeHandler
    idiom) and return (status_code, decoded-JSON-or-None)."""

    class FakeHandler(gui.AnchorHandler):
        def __init__(self):
            self.path = path
            body_bytes = json.dumps(body_dict).encode("utf-8")
            self.headers = {"Content-Length": str(len(body_bytes))}
            self.rfile = io.BytesIO(body_bytes)
            self.wfile = io.BytesIO()
            self.response_code = None

        def send_response(self, code):
            self.response_code = code

        def send_header(self, keyword, value):
            pass

        def end_headers(self):
            pass

        def log_message(self, format, *args):
            pass

    handler = FakeHandler()
    handler.do_POST()
    raw = handler.wfile.getvalue()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        payload = None
    return handler.response_code, payload


def test_api_doctor_run_is_gone_404s_and_spawns_nothing(monkeypatch):
    """POST /api/doctor/run is an UNKNOWN endpoint now (404) — it neither
    spawns a subprocess nor blocks the request thread on a child process."""
    import subprocess

    import anchor_gui
    import paths as _paths

    spawned = []
    real_popen = subprocess.Popen

    class _TrappingPopen(real_popen):
        def __init__(self, *args, **kwargs):
            spawned.append(args[0] if args else kwargs.get("args"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", _TrappingPopen)

    # Hermetic against the ambient env: supply the configured token (None when
    # auth is disabled — then it is simply ignored).
    body = {"init": True, "token": _paths.expected_token()}
    code, payload = _post(anchor_gui, "/api/doctor/run", body)

    assert code == 404, (code, payload)
    assert payload is not None and payload.get("ok") is False
    assert "unknown" in str(payload.get("error", "")).lower()
    assert spawned == [], f"/api/doctor/run spawned a process: {spawned}"

    # The healthcheck arm of the old handler is equally gone (no synchronous
    # 75s anchor_healthcheck.py spawn in the request thread).
    code2, payload2 = _post(
        anchor_gui, "/api/doctor/run?cmd=healthcheck",
        {"token": _paths.expected_token()})
    assert code2 == 404, (code2, payload2)
    assert spawned == [], f"cmd=healthcheck spawned a process: {spawned}"


def test_anchor_gui_source_has_no_doctor_agent_spawn_path():
    """Source-level pin: anchor_gui carries no handler branch for the V2
    doctor endpoint and no reference to the deleted agent script."""
    src = (REPO_ROOT / "anchor_gui.py").read_text(encoding="utf-8")
    assert _AGENT_MODULE not in src
    assert _GEMINI_SDK not in src
    # The old POST branch compared _path_only against the endpoint literal;
    # with the handler removed, no code path matches it any more.
    assert '_path_only == "/api/doctor/run"' not in src
    # The /doctor page no longer fires client-side calls at the dead endpoint.
    assert "fetch('/api/doctor/run" not in src
