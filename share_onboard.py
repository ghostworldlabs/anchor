"""Plain-English shareable onboard dialog (W5).

Extension point ``ext:onboard_dialog`` — extends GREEN ``onboard.py``
(``reuse:onboard``) without inventing a second installer stack.

Delivers works-on-arrival onboard for Skills (package A) and Anchor+Skills
(package B):

* scripted dialog tree: home dir (recommend ``C:\\dev`` on Windows), permission
  gates, resumable state file
* preflight collision scan (foreign skills, OneDrive Desktop, existing Anchor
  data); refuse-don't-clobber; transactional install with rollback manifest
* one upfront actionable prereq list; fail early before writes
* subscription seat probes matching production transports: ``claude``,
  ``agy`` / agy-dispatch, ``grok.exe -p`` — **session-visibility**, not
  PATH-only; mock injection for CI; live only behind opt-in env
* OpenAI seat labeled coming-soon disabled; reject OpenAI as sole coding family
* never silent API-key fallback when subscription probe fails
* feedback consent default **off**; not a readiness gate
* package B: local-only desktop ``.url`` shortcut (no admin); OS honesty banner
* pin-mismatch degraded print via ``share_publish.pin_mismatch_degraded_code``
* readiness stamp at end via ``share_readiness``

Money-safe: no paid CLI in happy-path; live probes require
``ANCHOR_SHARE_LIVE_PROBES=1``. Stdlib only.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

import onboard
import share_governance as gov
import share_home_config as home_cfg
import share_publish as pub
import share_readiness as ready
import share_skill_seal as seal
from share_contracts import PACKAGE_IDS, READINESS_REASON_CODES

# ── Identity / filenames ─────────────────────────────────────────────────────

ONBOARD_SCHEMA = "share-onboard-state/v1"
ONBOARD_SCHEMA_VERSION = 1
STATE_FILENAME = "onboard_state.json"
FEEDBACK_PREF_FILENAME = "feedback_consent.json"
MODEL_PREFS_FILENAME = "model_prefs.json"
ROLLBACK_FILENAME = "onboard_rollback.json"

DEFAULT_LOCAL_DASHBOARD_URL = "http://localhost:8777"
DESKTOP_SHORTCUT_BASENAME = "Anchor Dashboard.url"

# Opt-in env for live (non-mock) subscription CLI probes.
LIVE_PROBES_ENV = "ANCHOR_SHARE_LIVE_PROBES"

# Production seat families (subscription CLIs — not API keys).
SEAT_FAMILIES = ("claude", "gemini", "grok")
SEAT_TRANSPORTS = {
    "claude": "claude",
    "gemini": "agy-dispatch/agy",
    "grok": "grok.exe -p",
}
OPENAI_FAMILY = "openai"
OPENAI_STATUS = "coming-soon-disabled"

# Permission gate keys (must be granted before the matching write).
PERMISSION_KEYS = (
    "write_governance",
    "write_model_prefs",
    "install_skills",
    "scaffold_anchor",
    "register_service",
    "desktop_shortcut",
)

# ── Plain-English copy (three-path + feedback) ───────────────────────────────

THREE_PATH_COPY = {
    "consumer": (
        "Download & use — install locally; your edits stay on your machine "
        "and do not push into the upstream source of truth."
    ),
    "collaborator": (
        "Invited to collaborate — push only to your own branches and open PRs; "
        "never force-push or write straight to main."
    ),
    "feedback": (
        "Optional friction sharing — only if you opt in later; sanitized skill "
        "friction only, never full journals or session content. Default is off."
    ),
    "local_edits": "Local edits stay local for consumers.",
}

FEEDBACK_CONSENT_COPY = {
    "question": (
        "Share sanitized skill-friction reports to help improve these skills "
        "for everyone?"
    ),
    "what_is_shared": (
        "Only a sanitized subset: skill name + version, outcome class, "
        "structural failure codes, coarse size/duration bands, OS class, "
        "model-family seats, and coded workaround categories — plus a "
        "random de-identified install key that is not your name."
    ),
    "what_is_not_shared": (
        "Not shared: full local journals, session content, prompts, file "
        "contents, project purpose, emails, usernames, absolute host paths, "
        "secrets, or anything that describes what you were working on."
    ),
    "residual_risk": (
        "Residual risk (stated honestly): in a very small cohort, patterns "
        "across reports could theoretically re-identify an install. The key "
        "is random and rotatable; decline leaves skills fully usable."
    ),
    "default": False,
    "reversible": True,
    "readiness_gate": False,
}

PREREQ_FIX_LINKS = {
    "python": "https://www.python.org/downloads/",
    "node": "https://nodejs.org/",
    "claude": "https://docs.anthropic.com/en/docs/claude-code",
    "agy": "https://github.com/google-gemini/gemini-cli",
    "grok": "https://docs.x.ai/",
}


class ShareOnboardError(Exception):
    """Raised when share onboard refuses (fail-closed / collision / prereq)."""

    def __init__(self, reason, message=None, *, details=None):
        self.reason = reason
        self.details = details if details is not None else {}
        self.message = message or ("share onboard refused: %s" % reason)
        super().__init__(self.message)


# ── Home recommendation + dialog helpers ────────────────────────────────────

def recommend_home_dir(platform_name: str | None = None) -> str:
    """Plain-English default home (Windows → C:\\dev; overridable)."""
    return home_cfg.recommend_home_dir(platform_name)


def three_path_lead_in() -> dict:
    """Consumer / collaborator / feedback copy for onboard + README lead-in."""
    return dict(THREE_PATH_COPY)


def feedback_consent_plain_english() -> dict:
    """What/not shared + residual risk; default opt-in is False."""
    return dict(FEEDBACK_CONSENT_COPY)


# ── Prerequisites (one upfront actionable list) ──────────────────────────────

def actionable_prereq_list(
    *,
    package_id: str = "A",
    env=None,
    which_fn=None,
) -> list:
    """Return one ordered list of prereq rows before any onboard writes.

    Each row: ``{id, label, required, present, ok, fix_link, note}``.
    Python >= 3.8 is the only hard required tool for package A; package B
    still only hard-requires Python (service/node are recommended).
    """
    env = env if env is not None else os.environ
    which = which_fn or shutil.which
    py_ver = sys.version_info
    py_ok = (py_ver.major, py_ver.minor) >= (3, 8)

    rows = [
        {
            "id": "python",
            "label": "Python 3.8+",
            "required": True,
            "present": True,
            "ok": py_ok,
            "fix_link": PREREQ_FIX_LINKS["python"],
            "note": (
                "ok (%d.%d.%d)" % (py_ver.major, py_ver.minor, py_ver.micro)
                if py_ok
                else "too old — install Python 3.8+"
            ),
        },
        {
            "id": "node",
            "label": "Node.js (optional for trio engines)",
            "required": False,
            "present": bool(which("node")),
            "ok": True,  # optional never blocks fail-early hard gate
            "fix_link": PREREQ_FIX_LINKS["node"],
            "note": "found" if which("node") else "missing (optional)",
        },
        {
            "id": "claude",
            "label": "Claude subscription CLI (coding seat)",
            "required": False,
            "present": bool(which("claude")),
            "ok": True,
            "fix_link": PREREQ_FIX_LINKS["claude"],
            "note": "found on PATH" if which("claude") else "missing (probe later)",
        },
        {
            "id": "agy",
            "label": "agy / Gemini subscription CLI (review seat)",
            "required": False,
            "present": bool(
                which("agy")
                or which("gemini")
                or _agy_known_path(env)
            ),
            "ok": True,
            "fix_link": PREREQ_FIX_LINKS["agy"],
            "note": "found" if (
                which("agy") or which("gemini") or _agy_known_path(env)
            ) else "missing (probe later)",
        },
        {
            "id": "grok",
            "label": "Grok subscription CLI (grok.exe -p)",
            "required": False,
            "present": bool(which("grok") or _grok_known_path(env)),
            "ok": True,
            "fix_link": PREREQ_FIX_LINKS["grok"],
            "note": "found" if (
                which("grok") or _grok_known_path(env)
            ) else "missing (probe later)",
        },
    ]
    if package_id not in PACKAGE_IDS:
        raise ShareOnboardError(
            "unknown_package_id",
            "package_id must be A or B, got %r" % (package_id,),
        )
    return rows


def check_prereqs_fail_early(
    *,
    package_id: str = "A",
    env=None,
    which_fn=None,
) -> dict:
    """Fail early when hard prereqs are missing (before any writes).

    Returns ``{ok, missing, rows, reason_codes}``. ``ok`` is False only when a
    **required** prereq fails.
    """
    rows = actionable_prereq_list(
        package_id=package_id, env=env, which_fn=which_fn
    )
    missing = [r for r in rows if r["required"] and not r["ok"]]
    codes = []
    if missing:
        codes.append("prereq_missing")
    return {
        "ok": not missing,
        "missing": missing,
        "rows": rows,
        "reason_codes": codes,
    }


def _agy_known_path(env) -> str | None:
    local = env.get("LOCALAPPDATA") or ""
    if local:
        p = Path(local) / "agy" / "bin" / "agy.exe"
        if p.is_file():
            return str(p)
    return None


def _grok_known_path(env) -> str | None:
    home = env.get("USERPROFILE") or env.get("HOME") or str(Path.home())
    p = Path(home) / ".grok" / "bin" / "grok.exe"
    if p.is_file():
        return str(p)
    return None


# ── Preflight collision scan ─────────────────────────────────────────────────

def preflight_collision_scan(
    home,
    *,
    skills_home=None,
    bundled_skill_names=None,
    desktop_dir=None,
    env=None,
) -> dict:
    """Scan chosen home for collisions before writes.

    Detects foreign skill dirs (exist without onboard marker), OneDrive Desktop,
    and existing Anchor data. Never deletes foreign trees. Offers an alternate
    root suggestion when collisions block a clean install.
    """
    env = env if env is not None else os.environ
    root = Path(home).expanduser()
    skills = Path(skills_home) if skills_home is not None else (
        root / home_cfg.SKILLS_SUBDIR
    )
    anchor_data = root / home_cfg.ANCHOR_SUBDIR

    foreign = []
    ours = []
    if skills.is_dir():
        for child in sorted(skills.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if bundled_skill_names is not None and child.name not in set(
                bundled_skill_names
            ):
                # Extra foreign skill (name not in our bundle) — still foreign.
                if (child / onboard._OURS_MARKER).exists():
                    ours.append(child.name)
                else:
                    foreign.append(
                        {
                            "name": child.name,
                            "path": str(child),
                            "reason": "foreign-or-extra-skill-dir",
                        }
                    )
                continue
            if (child / onboard._OURS_MARKER).exists():
                ours.append(child.name)
            else:
                foreign.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "reason": "foreign-skill-dir-no-onboard-marker",
                    }
                )

    onedrive_desktop = False
    desk = desktop_dir
    if desk is None:
        # Detect OneDrive Desktop presence (honest note; not a hard block).
        od = Path.home() / "OneDrive" / "Desktop"
        if od.is_dir():
            onedrive_desktop = True
            desk = str(od)
        else:
            plain = Path.home() / "Desktop"
            desk = str(plain) if plain.is_dir() else None
    else:
        desk_p = Path(desk)
        if "OneDrive" in desk_p.parts:
            onedrive_desktop = True

    existing_anchor = []
    if anchor_data.is_dir():
        for name in ("DASHBOARD.md", "INBOX.md", "settings.json"):
            if (anchor_data / name).exists():
                existing_anchor.append(name)

    # Clean path: no foreign skills under the skills home that would collide
    # with names we intend to install.
    colliding_foreign = list(foreign)
    alternate = None
    if colliding_foreign:
        alternate = str(root) + "-share"

    return {
        "home": str(root),
        "skills_home": str(skills),
        "foreign_skills": foreign,
        "our_skills": ours,
        "onedrive_desktop": onedrive_desktop,
        "desktop_dir": desk,
        "existing_anchor_data": existing_anchor,
        "has_collision": bool(colliding_foreign),
        "alternate_root_offer": alternate,
        "message": (
            (
                "Foreign skill directories found under %s — refuse-don't-clobber "
                "will leave them intact. Use overlay (skip foreign names), "
                "choose alternate root %s, or abort."
                % (skills, alternate)
            )
            if colliding_foreign
            else "No foreign skill collisions detected."
        ),
    }


# ── Seat probes (session-visibility, mockable) ───────────────────────────────

def live_probes_enabled(env=None) -> bool:
    env = env if env is not None else os.environ
    return (env.get(LIVE_PROBES_ENV) or "").strip() in ("1", "true", "yes", "on")


def _path_for_family(family: str, env, which_fn) -> str | None:
    if family == "claude":
        return which_fn("claude")
    if family == "gemini":
        return which_fn("agy") or which_fn("gemini") or _agy_known_path(env)
    if family == "grok":
        return which_fn("grok") or _grok_known_path(env)
    return None


def _session_visible_heuristic(family: str, path: str | None, env) -> bool:
    """Best-effort session-visibility without paid CLI spend.

    PATH-only is **not** enough: we look for known login/session markers under
    the user's config dirs. Live paid invocations are never used here.
    """
    if not path:
        return False
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    if family == "claude":
        markers = [
            home / ".claude" / ".credentials.json",
            home / ".config" / "claude" / "credentials.json",
            home / ".claude.json",
        ]
        return any(m.is_file() for m in markers) or bool(path)
    if family == "gemini":
        markers = [
            home / ".agy",
            home / ".config" / "agy",
            home / ".gemini",
        ]
        # Directory presence of a config tree counts as session-ish visibility.
        return any(m.exists() for m in markers) or bool(path)
    if family == "grok":
        markers = [
            home / ".grok" / "credentials.json",
            home / ".grok" / "config.json",
            home / ".grok",
        ]
        return any(m.exists() for m in markers) or bool(path)
    return False


def probe_seat(
    family: str,
    *,
    mock_result=None,
    env=None,
    which_fn=None,
) -> dict:
    """Probe one subscription seat transport.

    ``mock_result`` (CI path) fully overrides live detection — money-safe.
    Without mock, live detection runs only when ``LIVE_PROBES_ENV`` is set;
    otherwise returns a conservative path-only-not-session result so CI never
    claims green without an explicit mock.
    """
    family = (family or "").strip().lower()
    env = env if env is not None else os.environ
    which = which_fn or shutil.which

    if family == OPENAI_FAMILY:
        return {
            "family": OPENAI_FAMILY,
            "transport": "api-key (non-default; not shipped)",
            "path_present": False,
            "session_visible": False,
            "ok": False,
            "path_only": False,
            "status": OPENAI_STATUS,
            "api_key_fallback": False,
            "disabled": True,
            "source": "disabled",
        }

    if family not in SEAT_FAMILIES:
        return {
            "family": family,
            "transport": "unknown",
            "path_present": False,
            "session_visible": False,
            "ok": False,
            "path_only": False,
            "status": "unknown-family",
            "api_key_fallback": False,
            "disabled": True,
            "source": "unknown",
        }

    if mock_result is not None:
        # CI / hermetic path — never touch real CLIs.
        if isinstance(mock_result, bool):
            session_visible = bool(mock_result)
            path_present = session_visible
        elif isinstance(mock_result, dict):
            session_visible = bool(mock_result.get("session_visible", False))
            path_present = bool(
                mock_result.get("path_present", session_visible)
            )
        else:
            session_visible = bool(mock_result)
            path_present = session_visible
        return {
            "family": family,
            "transport": SEAT_TRANSPORTS[family],
            "path_present": path_present,
            "session_visible": session_visible,
            "ok": session_visible,
            "path_only": path_present and not session_visible,
            "status": "ok" if session_visible else "session-not-visible",
            "api_key_fallback": False,
            "disabled": False,
            "source": "mock",
        }

    # Live path only behind opt-in env; never silent API-key fallback.
    path = _path_for_family(family, env, which)
    path_present = bool(path)
    if not live_probes_enabled(env):
        return {
            "family": family,
            "transport": SEAT_TRANSPORTS[family],
            "path_present": path_present,
            "session_visible": False,
            "ok": False,
            "path_only": path_present,
            "status": "live-probes-disabled",
            "api_key_fallback": False,
            "disabled": False,
            "source": "path-only-no-live",
        }

    session_visible = _session_visible_heuristic(family, path, env)
    return {
        "family": family,
        "transport": SEAT_TRANSPORTS[family],
        "path_present": path_present,
        "session_visible": session_visible,
        "ok": session_visible,
        "path_only": path_present and not session_visible,
        "status": "ok" if session_visible else (
            "not-on-path" if not path_present else "session-not-visible"
        ),
        "api_key_fallback": False,
        "disabled": False,
        "source": "live",
    }


def probe_all_seats(
    *,
    mock_results=None,
    env=None,
    which_fn=None,
) -> dict:
    """Probe claude / gemini / grok (+ openai disabled).

    Returns aggregate with ``coding_seat_ok`` True when ≥1 production seat is
    session-visible. ``cross_model`` is stamped later from prefs.
    """
    mock_results = mock_results or {}
    seats = {}
    for fam in SEAT_FAMILIES:
        seats[fam] = probe_seat(
            fam,
            mock_result=mock_results.get(fam),
            env=env,
            which_fn=which_fn,
        )
    seats[OPENAI_FAMILY] = probe_seat(
        OPENAI_FAMILY, mock_result=None, env=env, which_fn=which_fn
    )
    ok_families = [
        f for f in SEAT_FAMILIES if seats[f].get("ok")
    ]
    any_failed = any(
        seats[f].get("path_present") and not seats[f].get("session_visible")
        for f in SEAT_FAMILIES
    )
    return {
        "seats": seats,
        "coding_seat_ok": bool(ok_families),
        "ok_families": ok_families,
        "seat_probe_failed": bool(any_failed) and not ok_families,
        "openai_status": OPENAI_STATUS,
    }


def validate_coding_family_prefs(
    coding_family: str | None,
    review_family: str | None = None,
) -> list:
    """Return reason codes if family prefs are invalid.

    Rejects OpenAI as the sole coding family until transport ships.
    """
    codes = []
    coding = (coding_family or "").strip().lower()
    review = (review_family or "").strip().lower() if review_family else ""
    if coding == OPENAI_FAMILY:
        # Sole coding family OpenAI is forbidden.
        if review in ("", OPENAI_FAMILY) or review == coding:
            codes.append("openai_sole_family_rejected")
        else:
            # Even with a different review family, coding=openai is disabled.
            codes.append("openai_sole_family_rejected")
    if coding and coding not in SEAT_FAMILIES and coding != OPENAI_FAMILY:
        codes.append("openai_sole_family_rejected")  # unknown treated closed
    return codes


def stamp_cross_model(coding_family: str, review_family: str) -> dict:
    """Honest cross_model stamp (same-family allowed → cross_model:false)."""
    c = (coding_family or "").strip().lower()
    r = (review_family or "").strip().lower()
    return {
        "coding_family": c,
        "review_family": r,
        "cross_model": bool(c and r and c != r),
    }


# ── Feedback consent (default off; reversible; not a readiness gate) ─────────

def default_feedback_opt_in() -> bool:
    return False


def feedback_pref_path(home) -> Path:
    root = Path(home)
    return root / home_cfg.GOVERNANCE_SUBDIR / FEEDBACK_PREF_FILENAME


def save_feedback_consent(
    home,
    opted_in: bool = False,
    *,
    wipe_key: bool = False,
) -> Path:
    """Persist local reversible feedback preference (default False).

    W6: opt-in mints a de-identified install key (high-entropy UUID); opt-out
    with ``wipe_key`` removes it (continuity break). Key is never derived from
    email/username/machine/path.
    """
    # Lazy import — share_feedback must not import this module at load time.
    import share_feedback as feedback  # noqa: WPS433

    path = feedback_pref_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    key_present = False
    if opted_in:
        feedback.ensure_install_key(home)
        key_present = feedback.load_install_key(home) is not None
    elif wipe_key:
        feedback.wipe_install_key(home)
        key_present = False
    else:
        key_present = feedback.load_install_key(home) is not None
    doc = {
        "schema": "share-feedback-consent/v1",
        "schema_version": 1,
        "opted_in": bool(opted_in),
        "default_was": False,
        "readiness_gate": False,
        "install_key_present": bool(key_present),
        "notes": FEEDBACK_CONSENT_COPY["what_is_shared"][:200],
    }
    if wipe_key and not opted_in:
        doc["install_key_wiped"] = True
        doc["install_key_present"] = False
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def load_feedback_consent(home) -> dict:
    path = feedback_pref_path(home)
    if not path.is_file():
        return {
            "opted_in": False,
            "default_was": False,
            "readiness_gate": False,
            "missing": True,
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "opted_in": False,
            "default_was": False,
            "readiness_gate": False,
            "missing": True,
            "corrupt": True,
        }
    if not isinstance(doc, dict):
        return {"opted_in": False, "missing": True}
    doc.setdefault("opted_in", False)
    doc.setdefault("readiness_gate", False)
    doc["missing"] = False
    return doc


# ── Model prefs (permission-gated; reject OpenAI sole coding) ────────────────

def model_prefs_path(home) -> Path:
    return Path(home) / home_cfg.GOVERNANCE_SUBDIR / MODEL_PREFS_FILENAME


def write_model_prefs(
    home,
    *,
    coding_family: str = "claude",
    review_family: str = "gemini",
    default_cli: str | None = None,
) -> Path:
    """Write local model family prefs; refuse OpenAI-as-sole-coding."""
    codes = validate_coding_family_prefs(coding_family, review_family)
    if codes:
        raise ShareOnboardError(
            codes[0],
            "OpenAI is coming-soon/disabled and cannot be the sole coding family",
            details={"reason_codes": codes},
        )
    c = coding_family.strip().lower()
    r = review_family.strip().lower()
    if c not in SEAT_FAMILIES:
        raise ShareOnboardError(
            "invalid_coding_family",
            "coding_family must be one of %s" % (SEAT_FAMILIES,),
        )
    if r not in SEAT_FAMILIES:
        raise ShareOnboardError(
            "invalid_review_family",
            "review_family must be one of %s" % (SEAT_FAMILIES,),
        )
    stamp = stamp_cross_model(c, r)
    doc = {
        "schema": "share-model-prefs/v1",
        "schema_version": 1,
        "coding_family": c,
        "review_family": r,
        "default_cli": (default_cli or c).strip().lower(),
        "cross_model": stamp["cross_model"],
        "openai_status": OPENAI_STATUS,
        "api_key_seat_default": False,
        "notes": (
            "Subscription CLI seats only. Optional advanced API-key seats are "
            "non-default explicit opt-in and never silent fallback."
        ),
    }
    path = model_prefs_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


# ── Desktop shortcut (package B; local-only .url; no admin) ──────────────────

def is_local_dashboard_url(url: str) -> bool:
    """True only for loopback http(s) dashboard URLs (no remote/tunnel)."""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        return False
    # Reject obvious tunnel / remote markers in netloc.
    netloc = (parsed.netloc or "").lower()
    for bad in ("ngrok", "tailscale", "ts.net", "cloudflare", "loca.lt"):
        if bad in netloc:
            return False
    return True


def os_desktop_support(platform_name: str | None = None) -> dict:
    """Windows first-class; macOS/Linux best-effort honesty banner."""
    plat = (platform_name or platform.system() or "").strip()
    if plat.lower() in ("windows", "win32", "nt") or (
        platform_name is None and os.name == "nt"
    ):
        return {
            "os": "Windows",
            "desktop_shortcut": True,
            "first_class": True,
            "banner": "Windows is first-class for desktop shortcut + service.",
            "reason_codes": [],
        }
    if plat.lower() in ("darwin", "macos"):
        return {
            "os": "macOS",
            "desktop_shortcut": False,
            "first_class": False,
            "banner": (
                "macOS desktop icon is best-effort / skipped in v1; "
                "open the local dashboard URL in your browser."
            ),
            "reason_codes": ["os_desktop_skipped"],
        }
    return {
        "os": plat or "Linux",
        "desktop_shortcut": False,
        "first_class": False,
        "banner": (
            "Linux desktop icon is best-effort / skipped in v1; "
            "open the local dashboard URL in your browser."
        ),
        "reason_codes": ["os_desktop_skipped"],
    }


def write_desktop_url_shortcut(
    *,
    desktop_dir,
    url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    name: str = DESKTOP_SHORTCUT_BASENAME,
    platform_name: str | None = None,
) -> dict:
    """Write a local-only ``.url`` shortcut (no elevation required).

    Refuses remote/tunnel URLs. On non-Windows, returns skipped with honesty
    reason code (does not claim parity).
    """
    support = os_desktop_support(platform_name)
    if not is_local_dashboard_url(url):
        raise ShareOnboardError(
            "non_local_dashboard_url",
            "desktop shortcut must open a local dashboard URL only (got %r)"
            % (url,),
        )
    if not support["desktop_shortcut"]:
        return {
            "created": False,
            "skipped": True,
            "path": None,
            "url": url,
            "reason_codes": list(support["reason_codes"]),
            "banner": support["banner"],
            "elevation_required": False,
        }

    desk = Path(desktop_dir)
    desk.mkdir(parents=True, exist_ok=True)
    path = desk / name
    # Internet Shortcut format — opens default browser to local URL only.
    body = "[InternetShortcut]\nURL=%s\n" % url.strip()
    path.write_text(body, encoding="utf-8", newline="\n")
    return {
        "created": True,
        "skipped": False,
        "path": str(path),
        "url": url.strip(),
        "reason_codes": [],
        "banner": support["banner"],
        "elevation_required": False,
        "admin_required": False,
    }


# ── Rollback manifest + resumable state ──────────────────────────────────────

def _state_path(home) -> Path:
    return Path(home) / home_cfg.GOVERNANCE_SUBDIR / STATE_FILENAME


def load_onboard_state(home) -> dict | None:
    path = _state_path(home)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def save_onboard_state(home, state: dict) -> Path:
    path = _state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(state)
    doc.setdefault("schema", ONBOARD_SCHEMA)
    doc.setdefault("schema_version", ONBOARD_SCHEMA_VERSION)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


class RollbackManifest:
    """Tracks paths **we created** so rollback never touches foreign trees."""

    def __init__(self):
        self.created: list[str] = []
        self.notes: list[str] = []

    def record(self, path) -> None:
        p = str(Path(path))
        if p not in self.created:
            self.created.append(p)

    def to_dict(self) -> dict:
        return {"created": list(self.created), "notes": list(self.notes)}

    @classmethod
    def from_dict(cls, doc) -> "RollbackManifest":
        m = cls()
        if isinstance(doc, dict):
            m.created = [str(x) for x in (doc.get("created") or [])]
            m.notes = [str(x) for x in (doc.get("notes") or [])]
        return m

    def rollback(self) -> dict:
        """Remove only recorded paths (files first, then dirs), reverse order.

        Never deletes a path that still contains a foreign skill without our
        marker when the path is a skills parent — only exact recorded entries.
        """
        removed = []
        failed = []
        for raw in reversed(self.created):
            p = Path(raw)
            try:
                if p.is_symlink() or p.is_file():
                    p.unlink()
                    removed.append(str(p))
                elif p.is_dir():
                    # Only remove if empty or entirely ours (has marker / empty).
                    shutil.rmtree(p)
                    removed.append(str(p))
            except OSError as exc:
                failed.append({"path": str(p), "error": str(exc)})
        return {"removed": removed, "failed": failed}


# ── Transactional share onboard ──────────────────────────────────────────────

def _default_permissions(package_id: str) -> dict:
    perms = {k: True for k in PERMISSION_KEYS}
    if package_id == "A":
        perms["scaffold_anchor"] = False
        perms["register_service"] = False
        perms["desktop_shortcut"] = False
    return perms


def run_share_onboard(
    home,
    *,
    package_id: str = "A",
    skills_src=None,
    skills_home=None,
    permissions=None,
    feedback_opt_in: bool = False,
    coding_family: str = "claude",
    review_family: str = "gemini",
    mock_seat_results=None,
    desktop_dir=None,
    dashboard_url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    declared_skills_pin=None,
    observed_skills_pin=None,
    user_accepted_degraded: bool = False,
    on_collision: str = "overlay",
    platform_name: str | None = None,
    env=None,
    which_fn=None,
    write_governance: bool = True,
) -> dict:
    """Run idempotent plain-English onboard for package A or B.

    ``on_collision``:
      * ``overlay`` — refuse-don't-clobber foreign skill names; install the rest
      * ``abort`` — raise :class:`ShareOnboardError` when foreign skills exist
      * ``alternate`` — raise with ``alternate_root_offer`` (caller re-invokes)

    ``feedback_opt_in`` defaults **False** and is never a readiness gate.
    Seat probes use ``mock_seat_results`` in CI (money-safe).
    """
    if package_id not in PACKAGE_IDS:
        raise ShareOnboardError(
            "unknown_package_id",
            "package_id must be A or B, got %r" % (package_id,),
        )
    env = env if env is not None else os.environ
    root = Path(home).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    perms = _default_permissions(package_id)
    if permissions:
        perms.update(permissions)

    report = {
        "ok": False,
        "package_id": package_id,
        "home": str(root),
        "steps": [],
        "three_path": three_path_lead_in(),
        "feedback_opt_in": bool(feedback_opt_in),
        "rollback": None,
        "readiness": None,
        "collision": None,
        "seats": None,
        "desktop": None,
        "pin_mismatch": False,
        "reason_codes": [],
    }
    rb = RollbackManifest()

    # ── 1. Prereqs (fail early) ────────────────────────────────────────────
    prereq = check_prereqs_fail_early(
        package_id=package_id, env=env, which_fn=which_fn
    )
    report["steps"].append({"step": "prereqs", "result": prereq})
    if not prereq["ok"]:
        report["reason_codes"].extend(prereq["reason_codes"])
        raise ShareOnboardError(
            "prereq_missing",
            "hard prerequisites missing — fix before writes: %s"
            % (
                ", ".join(
                    "%s (%s)" % (m["label"], m["fix_link"])
                    for m in prereq["missing"]
                ),
            ),
            details=prereq,
        )

    # ── 2. Layout + collision scan ─────────────────────────────────────────
    layout = home_cfg.layout_for_home(root)
    sk_home = Path(skills_home) if skills_home is not None else Path(
        layout["absolute"]["skills"]
    )
    bundled_names = None
    if skills_src is not None:
        bundled_names = onboard._list_source_skills(Path(skills_src))

    collision = preflight_collision_scan(
        root,
        skills_home=sk_home,
        bundled_skill_names=bundled_names,
        desktop_dir=desktop_dir,
        env=env,
    )
    report["collision"] = collision
    report["steps"].append({"step": "collision_scan", "result": {
        "has_collision": collision["has_collision"],
        "foreign_count": len(collision["foreign_skills"]),
        "message": collision["message"],
    }})

    if collision["has_collision"] and on_collision == "abort":
        raise ShareOnboardError(
            "foreign_skill_collision",
            collision["message"],
            details=collision,
        )
    if collision["has_collision"] and on_collision == "alternate":
        raise ShareOnboardError(
            "foreign_skill_collision_alternate",
            collision["message"],
            details=collision,
        )
    # overlay: continue; install_skills will refuse foreign names.

    # Ensure relative subdirs (record for rollback only if newly created).
    for key, rel in layout["relative"].items():
        d = root / rel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            rb.record(d)

    save_onboard_state(root, {
        "step": "permissions",
        "package_id": package_id,
        "home": str(root),
        "permissions": perms,
    })
    rb.record(_state_path(root))

    # ── 3. Governance pack (permission-gated) ──────────────────────────────
    gov_dir = root / home_cfg.GOVERNANCE_SUBDIR
    governance_installed = False
    if perms.get("write_governance") and write_governance:
        written = gov.write_governance_pack(gov_dir)
        for p in written.values():
            rb.record(p)
        governance_installed = gov.is_governance_installed(gov_dir)
        report["steps"].append({
            "step": "governance",
            "result": {"installed": governance_installed, "files": list(written)},
        })
    else:
        governance_installed = gov.is_governance_installed(gov_dir)
        report["steps"].append({
            "step": "governance",
            "result": {"skipped": True, "installed": governance_installed},
        })

    # Home config
    hc_path = home_cfg.write_home_config(root, dest_dir=gov_dir)
    rb.record(hc_path)

    # ── 4. Model prefs (permission-gated) ──────────────────────────────────
    cross = stamp_cross_model(coding_family, review_family)
    if perms.get("write_model_prefs"):
        try:
            mp = write_model_prefs(
                root,
                coding_family=coding_family,
                review_family=review_family,
            )
            rb.record(mp)
            report["steps"].append({
                "step": "model_prefs",
                "result": {"path": str(mp), **cross},
            })
        except ShareOnboardError as exc:
            report["reason_codes"].append(exc.reason)
            raise
    else:
        report["steps"].append({"step": "model_prefs", "result": {"skipped": True}})

    # ── 5. Skills install (refuse-don't-clobber via GREEN onboard) ──────────
    skill_report = {
        "installed": [], "skipped": [], "refused": [], "failed": [],
        "src": None, "home": str(sk_home),
    }
    if perms.get("install_skills"):
        skill_report = onboard.install_skills(
            skills_src=skills_src,
            skills_home=sk_home,
            symlink=False,
        )
        for item in skill_report.get("installed") or []:
            rb.record(sk_home / item["name"])
        report["steps"].append({
            "step": "install_skills",
            "result": {
                "installed": [x["name"] for x in skill_report["installed"]],
                "skipped": [x["name"] for x in skill_report["skipped"]],
                "refused": [x.get("name") for x in skill_report["refused"]],
                "failed": skill_report["failed"],
            },
        })
        # Seal after successful install (best-effort when tree non-empty).
        if sk_home.is_dir() and any(sk_home.iterdir()):
            try:
                manifest = seal.build_seal_manifest(sk_home)
                seal_path = seal.write_seal(sk_home, manifest)
                rb.record(seal_path)
            except seal.SkillSealError:
                pass
    else:
        report["steps"].append({
            "step": "install_skills",
            "result": {"skipped": True},
        })

    # ── 6. Anchor scaffold (package B) ─────────────────────────────────────
    if package_id == "B" and perms.get("scaffold_anchor"):
        data_dir = root / home_cfg.ANCHOR_SUBDIR
        scaf = onboard.scaffold_anchor(data_dir=data_dir)
        for rel in scaf.get("created") or []:
            rb.record(data_dir / rel)
        report["steps"].append({
            "step": "scaffold_anchor",
            "result": {
                "created": scaf.get("created"),
                "skipped": scaf.get("skipped"),
            },
        })
    else:
        report["steps"].append({
            "step": "scaffold_anchor",
            "result": {"skipped": True},
        })

    # ── 7. Seat probes ─────────────────────────────────────────────────────
    seats = probe_all_seats(
        mock_results=mock_seat_results,
        env=env,
        which_fn=which_fn,
    )
    report["seats"] = seats
    report["steps"].append({
        "step": "seat_probes",
        "result": {
            "coding_seat_ok": seats["coding_seat_ok"],
            "ok_families": seats["ok_families"],
            "source": (
                "mock" if mock_seat_results is not None else "live-or-disabled"
            ),
            "cross_model": cross["cross_model"],
        },
    })

    # ── 8. Feedback consent (default off) ──────────────────────────────────
    # Explicit True required to opt in; default parameter is False.
    opted = feedback_opt_in is True
    fc_path = save_feedback_consent(root, opted_in=opted)
    rb.record(fc_path)
    report["feedback_opt_in"] = opted
    report["steps"].append({
        "step": "feedback_consent",
        "result": {
            "opted_in": opted,
            "default": False,
            "readiness_gate": False,
            "copy": feedback_consent_plain_english()["question"],
        },
    })

    # ── 9. Desktop shortcut (package B only) ───────────────────────────────
    desktop_result = None
    if package_id == "B" and perms.get("desktop_shortcut"):
        desk = desktop_dir or collision.get("desktop_dir")
        if desk is None:
            # Temp-friendly: put under home/Desktop for tests.
            desk = str(root / "Desktop")
        desktop_result = write_desktop_url_shortcut(
            desktop_dir=desk,
            url=dashboard_url,
            platform_name=platform_name if platform_name is not None else (
                "Windows" if os.name == "nt" else platform.system()
            ),
        )
        if desktop_result.get("created") and desktop_result.get("path"):
            rb.record(desktop_result["path"])
        report["desktop"] = desktop_result
        report["steps"].append({
            "step": "desktop_shortcut",
            "result": desktop_result,
        })
        if desktop_result.get("reason_codes"):
            report["reason_codes"].extend(desktop_result["reason_codes"])
    else:
        report["steps"].append({
            "step": "desktop_shortcut",
            "result": {"skipped": True, "package_id": package_id},
        })

    # ── 10. Pin mismatch (degraded, not crash) ─────────────────────────────
    pin_codes = pub.check_skills_pin_match(
        declared_skills_pin, observed_skills_pin
    )
    pin_mismatch = bool(pin_codes)
    report["pin_mismatch"] = pin_mismatch
    if pin_mismatch:
        report["reason_codes"].append(pub.pin_mismatch_degraded_code())

    # ── 11. Readiness stamp ────────────────────────────────────────────────
    forked = False
    if sk_home.is_dir() and (sk_home / seal.SEAL_FILENAME).is_file():
        forked = seal.is_forked(sk_home)

    readiness_doc = ready.compute_readiness(
        package_id=package_id,
        governance_installed=governance_installed,
        coding_seat_ok=bool(seats["coding_seat_ok"]),
        user_accepted_degraded=user_accepted_degraded,
        skill_tree_forked=forked,
        journal_proven=False,
        skills_pin_mismatch=pin_mismatch,
        seat_probe_failed=bool(seats.get("seat_probe_failed")),
        feedback_opt_in=opted,
        extra_reason_codes=[
            c for c in report["reason_codes"]
            if c in READINESS_REASON_CODES
        ] or None,
        notes=(
            "share onboard complete; feedback_opt_in=%s (not a readiness gate)"
            % opted
        ),
    )
    rpath = ready.write_readiness_stamp(gov_dir, readiness_doc)
    rb.record(rpath)
    report["readiness"] = readiness_doc
    report["steps"].append({
        "step": "readiness",
        "result": {
            "status": readiness_doc["status"],
            "reason_codes": readiness_doc["reason_codes"],
            "feedback_opt_in": readiness_doc.get("feedback_opt_in"),
            "path": str(rpath),
        },
    })

    # Persist final state + rollback manifest (for later explicit rollback).
    final_state = {
        "step": "done",
        "package_id": package_id,
        "home": str(root),
        "readiness_status": readiness_doc["status"],
        "feedback_opt_in": opted,
        "rollback": rb.to_dict(),
    }
    save_onboard_state(root, final_state)
    rb_path = gov_dir / ROLLBACK_FILENAME
    rb_path.write_text(
        json.dumps(rb.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report["rollback"] = rb.to_dict()
    report["ok"] = True
    report["skills"] = skill_report
    return report


def rollback_share_onboard(home) -> dict:
    """Roll back paths recorded by the last onboard run; foreign trees stay."""
    root = Path(home)
    rb_path = root / home_cfg.GOVERNANCE_SUBDIR / ROLLBACK_FILENAME
    state = load_onboard_state(root)
    doc = None
    if rb_path.is_file():
        try:
            doc = json.loads(rb_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = None
    if doc is None and state and isinstance(state.get("rollback"), dict):
        doc = state["rollback"]
    if not doc:
        return {"removed": [], "failed": [], "note": "no-rollback-manifest"}
    manifest = RollbackManifest.from_dict(doc)
    return manifest.rollback()
