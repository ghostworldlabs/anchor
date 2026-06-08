#!/usr/bin/env python3
"""Anchor shared path + write-lock helper (stdlib only).

Single source of truth for every Anchor data path, imported by the GUI server
(`anchor_gui.py`), the CLI engine (`anchor.py`), and the daily health check
(`anchor_healthcheck.py`).

Design (Wave 2, frozen plan):
- The *code* dir is always `Path(__file__).parent` (where this module lives).
- The *data* dir is controlled by the env var ``ANCHOR_DATA_DIR``. When that
  env var is **unset**, the data dir defaults to the **code dir** — so existing
  behavior and existing on-disk data are preserved with ZERO behavior change.
- Paths are resolved **lazily, per call** (the env var is read at resolution
  time), so a test can set ``ANCHOR_DATA_DIR`` to a tmp dir before calling.
- Importing this module performs **no** directory creation. Callers that need
  the data dirs to exist must call :func:`ensure_data_dirs` explicitly. (This
  is the deliberate fix for the carried minor finding that ``anchor.py`` ran
  ``LOGS_DIR.mkdir(...)`` at import time.)

It also exposes a single process-wide :data:`WRITE_LOCK` so concurrent
mutating requests (under ``ThreadingHTTPServer``) cannot lose an update.
"""

import os
import threading
from pathlib import Path

# Where the Anchor *code* lives. This never depends on the env var.
CODE_DIR = Path(__file__).resolve().parent

# Process-wide write lock. A single global lock is the simplest serialization
# that guarantees no lost update across concurrent markdown/JSON mutations.
# Acquire it around EVERY file mutation (markdown and JSON).
WRITE_LOCK = threading.RLock()

# Env var that decouples data location from code location.
DATA_DIR_ENV = "ANCHOR_DATA_DIR"

# Canonical filenames / subdir names (data layout), centralized here.
DASHBOARD_NAME = "DASHBOARD.md"
PROJECTS_NAME = "PROJECTS.md"
INBOX_NAME = "INBOX.md"
CANCELLED_NAME = "CANCELLED.md"
SAVED_FOR_LATER_NAME = "SAVED_FOR_LATER.md"
DASHBOARD_HTML_NAME = "dashboard.html"
DOMAINS_DIRNAME = "domains"
LOGS_DIRNAME = "logs"
HEALTH_REPORTS_DIRNAME = "health_reports"


def data_dir() -> Path:
    """Resolve the Anchor data root.

    Reads ``ANCHOR_DATA_DIR`` at call time. Unset/blank -> the code dir
    (backward compatible). Returns an absolute :class:`~pathlib.Path`. Does
    NOT create the directory.
    """
    raw = os.environ.get(DATA_DIR_ENV)
    if raw and raw.strip():
        return Path(raw).expanduser().resolve()
    return CODE_DIR


# ── Canonical data paths (each resolved lazily via data_dir()) ─────────────

def dashboard_md() -> Path:
    return data_dir() / DASHBOARD_NAME


def projects_md() -> Path:
    return data_dir() / PROJECTS_NAME


def inbox_md() -> Path:
    return data_dir() / INBOX_NAME


def cancelled_md() -> Path:
    return data_dir() / CANCELLED_NAME


def saved_for_later_md() -> Path:
    return data_dir() / SAVED_FOR_LATER_NAME


def dashboard_html() -> Path:
    return data_dir() / DASHBOARD_HTML_NAME


def domains_dir() -> Path:
    return data_dir() / DOMAINS_DIRNAME


def logs_dir() -> Path:
    return data_dir() / LOGS_DIRNAME


def health_reports_dir() -> Path:
    return data_dir() / HEALTH_REPORTS_DIRNAME


def ensure_data_dirs() -> None:
    """Create the data subdirectories that Anchor writes into.

    Idempotent. Callers (server startup, CLI commands that write, health
    check) invoke this explicitly — it is intentionally NOT run on import.
    """
    base = data_dir()
    base.mkdir(parents=True, exist_ok=True)
    logs_dir().mkdir(parents=True, exist_ok=True)
    domains_dir().mkdir(parents=True, exist_ok=True)
    health_reports_dir().mkdir(parents=True, exist_ok=True)


# ── Auth helper (Wave 2) ───────────────────────────────────────────────────

AUTH_TOKEN_ENV = "ANCHOR_TOKEN"


def expected_token():
    """Return the configured shared-secret token, or ``None`` if unset.

    ``None`` means auth is disabled (local-only backward compatibility).
    """
    tok = os.environ.get(AUTH_TOKEN_ENV)
    if tok and tok.strip():
        return tok
    return None


def auth_ok(provided) -> bool:
    """Token-check predicate for mutating ``/api/*`` requests.

    - If no token is configured (env unset) -> auth disabled -> always True.
    - Otherwise the provided token must match exactly.

    Kept tiny and pure so it is unit-testable on its own.
    """
    want = expected_token()
    if want is None:
        return True
    return provided == want


# ── Idempotent migration (Wave 2) ──────────────────────────────────────────

# The canonical set of top-level data files + data subdirectories that make up
# an Anchor data layout. Used by migrate_data() to copy legacy data into a
# fresh ANCHOR_DATA_DIR with zero loss.
_DATA_FILES = (
    DASHBOARD_NAME,
    PROJECTS_NAME,
    INBOX_NAME,
    CANCELLED_NAME,
    SAVED_FOR_LATER_NAME,
)
_DATA_SUBDIRS = (DOMAINS_DIRNAME, LOGS_DIRNAME, HEALTH_REPORTS_DIRNAME)


def migrate_data(source=None, dest=None):
    """Migrate the legacy Anchor markdown/data layout into the data dir.

    - ``source`` defaults to the code dir (where the legacy committed markdown
      lives); ``dest`` defaults to the resolved data dir (ANCHOR_DATA_DIR).
    - Copies the canonical data files + data subdirectories from source to
      dest. **Never deletes or overwrites** an existing destination file, so it
      is idempotent: running twice produces the same result with nothing
      duplicated or lost.
    - When ``source`` and ``dest`` resolve to the same path (the default when
      ANCHOR_DATA_DIR is unset), it is a no-op.

    Returns a dict report: ``{"copied": [...], "skipped_existing": [...],
    "noop": bool}``.
    """
    import shutil

    src = Path(source).resolve() if source is not None else CODE_DIR
    dst = Path(dest).resolve() if dest is not None else data_dir()

    report = {"copied": [], "skipped_existing": [], "noop": False}
    if src == dst:
        report["noop"] = True
        return report

    dst.mkdir(parents=True, exist_ok=True)

    # Top-level files.
    for name in _DATA_FILES:
        s = src / name
        d = dst / name
        if not s.exists():
            continue
        if d.exists():
            report["skipped_existing"].append(name)
            continue
        shutil.copy2(s, d)
        report["copied"].append(name)

    # Data subdirectories (copy file-by-file so existing files are preserved).
    for sub in _DATA_SUBDIRS:
        s_dir = src / sub
        if not s_dir.is_dir():
            continue
        d_dir = dst / sub
        d_dir.mkdir(parents=True, exist_ok=True)
        for s_file in sorted(s_dir.rglob("*")):
            if s_file.is_dir():
                continue
            rel = s_file.relative_to(s_dir)
            d_file = d_dir / rel
            key = f"{sub}/{rel.as_posix()}"
            if d_file.exists():
                report["skipped_existing"].append(key)
                continue
            d_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s_file, d_file)
            report["copied"].append(key)

    return report


# ── Bind-retry helper (Wave 2) ─────────────────────────────────────────────

def bind_with_retry(make_server, attempts: int = 5, delay: float = 0.25):
    """Construct/bind a server with a bounded retry loop.

    ``make_server`` is a zero-arg callable that constructs (and binds) the
    server, returning it. If it raises :class:`OSError` (e.g. a slow Tailscale
    interface not yet up), retry up to ``attempts`` times with ``delay``
    seconds between tries. Re-raises the last error if all attempts fail.

    Structured so a test can monkeypatch ``socket.bind`` to fail once then
    succeed and observe recovery.
    """
    import time

    last_exc = None
    for i in range(max(1, attempts)):
        try:
            return make_server()
        except OSError as exc:  # bind failures surface as OSError
            last_exc = exc
            if i < attempts - 1:
                time.sleep(delay)
    raise last_exc
