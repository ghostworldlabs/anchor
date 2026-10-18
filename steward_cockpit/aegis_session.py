"""aegis_session.py — Anchor AI Cockpit Integration for Aegis Defensive Security Scanner & Auto-Remediation (Wave 17).

Connects any Anchor AI Cockpit to `C:/dev/Skill Foundry/skills/aegis/scripts/aegis_engine.py`, persisting
`.aegis/session.json` and generating `AEGIS-SECURITY-REPORT.md` stamped with the verified frontier model
seating (`gemini-4-argon · high` for remediation synthesis and `claude-fable-5-1 · max` for cross-family review).
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, List

from steward_cockpit import anvil_session as _anvil_sess


AEGIS_ENGINE_PATH = Path(r"C:\dev\Skill Foundry\skills\aegis\scripts\aegis_engine.py")


def _load_aegis_engine():
    spec = importlib.util.spec_from_file_location("aegis_engine", str(AEGIS_ENGINE_PATH))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Aegis engine from {AEGIS_ENGINE_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _session_file(cockpit_dir: str | Path) -> Path:
    return Path(cockpit_dir) / ".aegis" / "session.json"


def _write_markdown_report(cdir: Path, state: Dict[str, Any]) -> Path:
    scan = state.get("scan") or {}
    seating = state.get("model_seating") or {}
    findings = scan.get("findings") or []
    sev = scan.get("severity_counts") or {}
    lines = [
        f"# Aegis Security Audit & Remediation Report — {cdir.name}",
        "",
        f"- **Updated:** `{state.get('updated_at', '')}`",
        f"- **Target Scanned:** `{scan.get('target', str(cdir))}` (`{scan.get('files_scanned', 0)}` Python files)",
        f"- **Security Verdict:** **`{scan.get('verdict', 'PASS')}`** (`{scan.get('total_findings', 0)}` open findings · `{scan.get('auto_fixable_count', 0)}` auto-fixable)",
        f"- **Severity Breakdown:** CRITICAL `{sev.get('CRITICAL', 0)}` · HIGH `{sev.get('HIGH', 0)}` · MEDIUM `{sev.get('MEDIUM', 0)}` · LOW `{sev.get('LOW', 0)}`",
        f"- **Model Seating:** `{seating.get('coding_model_id', 'gemini-4-argon')}` (`{seating.get('coding_effort', 'high')}`) + Adversarial Review: `{seating.get('review_model_id', 'claude-fable-5-1')}` (`{seating.get('review_effort', 'max')}`)",
        "",
        "## Findings & Defensive Patches",
    ]
    if not findings:
        lines.append("- **Zero open vulnerabilities detected** across all 6 OWASP/CWE families (`AEG-01` through `AEG-06`).")
    else:
        for f in findings[:50]:
            lines.append(
                f"- **`{f['rule_id']}` ({f['cwe']} · {f['severity']})** `{f['file']}:{f['line']}` — {f['message']}\n"
                f"  - Current: `{f['snippet']}`\n"
                f"  - Proposed Fix: `{f['proposed_fix']}`"
            )
    report_path = cdir / "AEGIS-SECURITY-REPORT.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def get_cockpit_aegis_state(cockpit_dir: str | Path) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    sf = _session_file(cdir)
    seating = _anvil_sess._read_model_seating_info()
    if sf.is_file():
        try:
            sess = json.loads(sf.read_text(encoding="utf-8"))
            sess["model_seating"] = seating
            return {"ok": True, "active": True, "cockpit_name": cdir.name, "session": sess}
        except Exception:
            pass
    return {"ok": True, "active": False, "cockpit_name": cdir.name, "session": None, "model_seating": seating}


def run_cockpit_aegis_scan(
    cockpit_dir: str | Path,
    target_spec: str = ".",
    signed_off_ids: List[str] | None = None,
) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    eng = _load_aegis_engine()
    target_path = (cdir / target_spec).resolve() if target_spec and target_spec != "." and not Path(target_spec).is_absolute() else (Path(target_spec).resolve() if Path(target_spec).is_absolute() else cdir)
    existing = get_cockpit_aegis_state(cdir).get("session") or {}
    signed = list(dict.fromkeys((existing.get("signed_off_ids") or []) + (signed_off_ids or [])))
    scan_res = eng.scan_target(target_path, signed_off_ids=signed)
    seating = _anvil_sess._read_model_seating_info()
    sess = {
        "schema": "anchor-aegis-session/v1",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_spec": target_spec or ".",
        "signed_off_ids": signed,
        "model_seating": seating,
        "scan": scan_res,
        "last_remediation": existing.get("last_remediation"),
    }
    sf = _session_file(cdir)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(sess, indent=2), encoding="utf-8")
    _write_markdown_report(cdir, sess)
    return {"ok": True, "active": True, "cockpit_name": cdir.name, "session": sess}


def run_cockpit_aegis_remediate(
    cockpit_dir: str | Path,
    apply: bool = False,
    rule_filter: str = "",
) -> Dict[str, Any]:
    cdir = Path(cockpit_dir).resolve()
    eng = _load_aegis_engine()
    existing = get_cockpit_aegis_state(cdir).get("session") or {}
    target_spec = existing.get("target_spec") or "."
    target_path = (cdir / target_spec).resolve() if target_spec != "." and not Path(target_spec).is_absolute() else (Path(target_spec).resolve() if Path(target_spec).is_absolute() else cdir)
    rem_res = eng.remediate_target(target_path, apply=apply, rule_filter=rule_filter)
    scan_res = eng.scan_target(target_path, signed_off_ids=existing.get("signed_off_ids") or [])
    seating = _anvil_sess._read_model_seating_info()
    sess = {
        "schema": "anchor-aegis-session/v1",
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_spec": target_spec,
        "signed_off_ids": existing.get("signed_off_ids") or [],
        "model_seating": seating,
        "scan": scan_res,
        "last_remediation": rem_res,
    }
    sf = _session_file(cdir)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(sess, indent=2), encoding="utf-8")
    _write_markdown_report(cdir, sess)
    return {"ok": True, "active": True, "cockpit_name": cdir.name, "session": sess}
