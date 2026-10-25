"""Ghost World Labs & Anchor Collaboration System Admin GUI + Account & 2FA Recovery Portal (stdlib only).

Provides:
1. Where the Main Anchor Server & Collaboration Hub Live (`get_gwl_admin_state()["server_locations"]`):
   - Live server on `PUTER` (`gwl-server`, NSSM service `anchor`, `http://127.0.0.1:8777` & `http://puter:8777` on Tailscale).
   - Central registrations, shared docs, ACLs, and recovery outbox in `.anchor/gwl_hub/`, automatically mirrored to
     `C:\\dev\\GhostWorldLabs-Hub` and `C:\\dev\\Anchor\\gwl_hub_repository`.
2. Standard 2FA Recovery (`STANDARD_2FA_RECOVERY_GUIDE`, `generate_2fa_backup_codes`, `verify_and_consume_2fa_backup_code`):
   - Layer 1: 10 Single-Use 2FA Recovery / Backup Codes (generated at 2FA enrollment, SHA-256 hashed at rest).
   - Layer 2: Verified Contact Email Recovery Link (`/recover-account?token=...`) + Tailscale Node / Device Attestation.
   - Layer 3: System Administrator 2FA Reset / Re-Enrollment (`/gwl-admin`) on `PUTER`.
3. Self-Service Account Recovery Portal (`GET /recover-account`, `render_account_recovery_html`):
   - Users enter their Contact Email (or Username / Pseudonym) to request a Username Reminder + Password / 2FA Recovery Link.
   - Clicking the single-use link reveals their exact Username & Collaborator Pseudonym, lets them set a new password,
     redeem a 2FA backup code, or reset/re-enroll 2FA.
4. Anchor Collaboration System Admin GUI (`GET /gwl-admin`, `GET /admin/collaboration`, `render_gwl_admin_gui_html`):
   - Review all registered accounts, make manual edits, add accounts, send recovery links, set temporary passwords,
     reset/disable 2FA, rotate `ANCHOR_TOKEN`, manage shared collaboration documents & ACL grants, and inspect the audit log.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import secrets
from typing import Any

import anchor_agent_protocol as aap
import gwl_clearinghouse as gwl
import paths


STANDARD_2FA_RECOVERY_GUIDE: dict[str, Any] = {
    "summary": (
        "Anchor implements the three industry-standard Two-Factor Authentication (2FA) recovery layers "
        "used by GitHub, Google Workspace, and 1Password so a lost phone or authenticator app never permanently locks you out."
    ),
    "layers": [
        {
            "layer": 1,
            "name": "One-Time 2FA Backup / Recovery Codes (10 Single-Use Codes)",
            "how_it_works": (
                "When you enable 2FA in Step 1 or /setup, Anchor generates 10 single-use recovery codes "
                "(e.g., GWL4-9K2M-7P3X) and stores only their SHA-256 hashes. Save or print these codes; "
                "each code can be entered once in place of a 6-digit TOTP code if you lose your phone."
            ),
        },
        {
            "layer": 2,
            "name": "Verified Contact Email Recovery Link + Tailscale Device Node Attestation",
            "how_it_works": (
                "If you forget your username/password or lose your authenticator app, enter your Contact Email "
                "on Step 1, /setup, or /recover-account to receive a time-limited (30-minute), single-use recovery link "
                "that reminds you of your Username & Pseudonym and lets you reset your password or re-enroll 2FA."
            ),
        },
        {
            "layer": 3,
            "name": "Anchor System Administrator Reset on Puter (/gwl-admin)",
            "how_it_works": (
                "If a collaborator loses both their authenticator device and backup codes, an Anchor System Admin "
                "can open the Collaboration System Admin GUI (/gwl-admin), verify the collaborator, and click "
                "'Reset 2FA & Issue 10 New Backup Codes', 'Send Recovery Link', or 'Set Temporary Password'."
            ),
        },
    ],
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_2fa_backup_codes(count: int = 10) -> dict[str, Any]:
    """Generate ``count`` human-readable single-use 2FA recovery codes and their SHA-256 hashes."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    plain_codes: list[str] = []
    hashed_codes: list[dict[str, Any]] = []
    for i in range(max(1, count)):
        part1 = "".join(secrets.choice(alphabet) for _ in range(4))
        part2 = "".join(secrets.choice(alphabet) for _ in range(4))
        part3 = "".join(secrets.choice(alphabet) for _ in range(4))
        code = f"{part1}-{part2}-{part3}"
        plain_codes.append(code)
        norm = code.replace("-", "").upper()
        hashed_codes.append({
            "index": i + 1,
            "code_hint": f"{part1}-••••-{part3[-2:]}",
            "sha256": hashlib.sha256(norm.encode("utf-8")).hexdigest(),
            "used": False,
            "used_at": "",
        })
    return {
        "codes": plain_codes,
        "hashed_records": hashed_codes,
        "remaining": len(plain_codes),
        "generated_at": _utc_now_iso(),
    }


def verify_and_consume_2fa_backup_code(
    provided_code: str,
    hashed_records: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]], int]:
    """Verify a single-use 2FA backup code against stored SHA-256 hashes and mark it used if valid."""
    norm = str(provided_code or "").strip().replace("-", "").replace(" ", "").upper()
    if not norm:
        rem = sum(1 for r in (hashed_records or []) if isinstance(r, dict) and not r.get("used"))
        return False, list(hashed_records or []), rem

    cand_hash = hashlib.sha256(norm.encode("utf-8")).hexdigest()
    updated: list[dict[str, Any]] = []
    matched = False
    for rec in (hashed_records or []):
        if not isinstance(rec, dict):
            continue
        r_copy = dict(rec)
        if not matched and not r_copy.get("used") and r_copy.get("sha256") == cand_hash:
            r_copy["used"] = True
            r_copy["used_at"] = _utc_now_iso()
            matched = True
        updated.append(r_copy)
    remaining = sum(1 for r in updated if not r.get("used"))
    return matched, updated, remaining


def get_gwl_admin_state(
    *,
    sandbox: bool = False,
    sandbox_id: str = "desktop-walkthrough",
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Return the complete state for the Anchor Collaboration System Admin GUI (`GET /api/gwl-admin/state`)."""
    import onboard_wizard as _ow

    hub_root = _ow._gwl_hub_root_for(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    hub = gwl.GWLClearinghouse(hub_root=hub_root)
    applicants = hub.list_applicant_signups()
    directory = hub.list_accounts()
    acl_grants = hub._load_acl_ledger() if hasattr(hub, "_load_acl_ledger") else []
    shared_docs = hub.list_shared_documents()
    recovery_reqs = hub.list_recovery_requests()
    audit_log = hub.list_admin_audit_log()
    model_cat = hub.get_verified_model_catalog()
    locations = hub.get_server_and_hub_locations()

    return {
        "ok": True,
        "sandbox": bool(sandbox),
        "server_locations": locations,
        "twofa_recovery_guide": STANDARD_2FA_RECOVERY_GUIDE,
        "counts": {
            "applicants": len(applicants),
            "active_accounts": sum(1 for a in applicants if a.get("account_status", "active") == "active"),
            "twofa_enabled": sum(1 for a in applicants if a.get("dual_auth_enabled")),
            "shared_documents": len(shared_docs),
            "acl_grants": len(acl_grants),
            "pending_recoveries": sum(1 for r in recovery_reqs if r.get("status") == "pending"),
            "audit_events": len(audit_log),
        },
        "applicants": applicants,
        "directory_accounts": directory,
        "acl_grants": acl_grants,
        "shared_documents": shared_docs,
        "recovery_requests": recovery_reqs,
        "audit_log": audit_log,
        "model_catalog": model_cat,
    }


def dispatch_gwl_admin_action(
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    sandbox: bool = False,
    sandbox_id: str = "desktop-walkthrough",
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Handle all admin and account-recovery actions (`POST /api/gwl-admin/action`)."""
    import onboard_wizard as _ow

    body = dict(payload or {})
    act = str(action or body.get("action") or "").strip().lower()
    use_sandbox = bool(sandbox or body.get("sandbox") in (True, 1, "1", "true"))
    sid = str(body.get("sandbox_id") or sandbox_id or "desktop-walkthrough").strip()
    hub_root = _ow._gwl_hub_root_for(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
    hub = gwl.GWLClearinghouse(hub_root=hub_root)
    actor = str(body.get("admin_actor") or "admin").strip() or "admin"

    if act == "get_admin_state":
        return get_gwl_admin_state(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)

    if act in ("request_account_recovery", "send_recovery_link"):
        ident = str(
            body.get("identifier")
            or body.get("contact_email")
            or body.get("username")
            or body.get("applicant_id")
            or ""
        ).strip()
        rec_type = str(body.get("recovery_type") or "username_and_password").strip()
        base_url = str(body.get("base_url") or "http://puter:8777").strip()
        return hub.create_account_recovery_request(
            ident,
            recovery_type=rec_type,
            base_url=base_url,
            actor=actor,
        )

    if act == "complete_account_recovery":
        tok = str(body.get("token") or body.get("recovery_token") or "").strip()
        new_pwd = str(body.get("new_password") or body.get("password") or "").strip()
        reset_2fa = bool(body.get("reset_2fa") in (True, 1, "1", "true", "yes"))
        bcode = str(body.get("backup_code") or "").strip()
        res = hub.complete_account_recovery(
            tok,
            new_password=new_pwd,
            reset_2fa=reset_2fa,
            backup_code=bcode,
        )
        if not res.get("ok"):
            return res

        # If this matches the local profile username, also update local profile credentials/2FA
        prof = _ow.get_active_user_profile(sid if use_sandbox else "", sandbox=use_sandbox, base_dir=base_dir)
        if prof.get("username") == res.get("username") or new_pwd or reset_2fa:
            pfile = _ow.user_profile_path(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
            if pfile.is_file():
                try:
                    pdoc = json.loads(pfile.read_text(encoding="utf-8"))
                except Exception:
                    pdoc = {}
            else:
                pdoc = {}
            if new_pwd:
                salt_bytes = secrets.token_bytes(16)
                pdoc["password_salt"] = salt_bytes.hex()
                pdoc["password_hash"] = hashlib.pbkdf2_hmac("sha256", new_pwd.encode("utf-8"), salt_bytes, 120_000).hex()
                pdoc["password_configured"] = True
            if reset_2fa:
                raw_b32 = base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=")
                pdoc["dual_auth_secret"] = " ".join(raw_b32[i:i + 4] for i in range(0, len(raw_b32), 4))
                bc_bundle = generate_2fa_backup_codes(10)
                pdoc["dual_auth_backup_codes"] = bc_bundle["codes"]
                pdoc["dual_auth_backup_hashes"] = bc_bundle["hashed_records"]
                res["new_dual_auth_secret"] = pdoc["dual_auth_secret"]
                res["new_backup_codes"] = bc_bundle["codes"]
            pdoc["updated_at"] = _utc_now_iso()
            pfile.parent.mkdir(parents=True, exist_ok=True)
            with paths.WRITE_LOCK:
                paths.atomic_write_text(pfile, json.dumps(pdoc, indent=2, ensure_ascii=False) + "\n")
        return res

    if act == "verify_2fa_backup_code":
        code = str(body.get("backup_code") or body.get("code") or "").strip()
        pfile = _ow.user_profile_path(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
        pdoc: dict[str, Any] = {}
        if pfile.is_file():
            try:
                pdoc = json.loads(pfile.read_text(encoding="utf-8"))
            except Exception:
                pdoc = {}
        hashes = list(pdoc.get("dual_auth_backup_hashes") or [])
        ok, updated_hashes, rem = verify_and_consume_2fa_backup_code(code, hashes)
        if ok:
            pdoc["dual_auth_backup_hashes"] = updated_hashes
            # Remove consumed code from plain display list if present
            norm_in = code.replace("-", "").replace(" ", "").upper()
            pdoc["dual_auth_backup_codes"] = [
                c for c in (pdoc.get("dual_auth_backup_codes") or [])
                if str(c).replace("-", "").upper() != norm_in
            ]
            with paths.WRITE_LOCK:
                paths.atomic_write_text(pfile, json.dumps(pdoc, indent=2, ensure_ascii=False) + "\n")
            if pdoc.get("username"):
                hub.admin_update_applicant(
                    str(pdoc["username"]),
                    {"backup_codes_remaining": rem},
                    admin_actor="2fa_backup_code",
                )
        return {
            "ok": ok,
            "verified": ok,
            "backup_codes_remaining": rem,
            "message": (
                f"2FA Backup Code verified and consumed ({rem} single-use backup codes remaining)."
                if ok
                else "Invalid or already-used 2FA Backup Code."
            ),
        }

    if act == "regenerate_2fa_backup_codes":
        pfile = _ow.user_profile_path(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
        pdoc = {}
        if pfile.is_file():
            try:
                pdoc = json.loads(pfile.read_text(encoding="utf-8"))
            except Exception:
                pdoc = {}
        bc = generate_2fa_backup_codes(10)
        pdoc["dual_auth_backup_codes"] = bc["codes"]
        pdoc["dual_auth_backup_hashes"] = bc["hashed_records"]
        pdoc["updated_at"] = _utc_now_iso()
        pfile.parent.mkdir(parents=True, exist_ok=True)
        with paths.WRITE_LOCK:
            paths.atomic_write_text(pfile, json.dumps(pdoc, indent=2, ensure_ascii=False) + "\n")
        target_user = str(body.get("username") or pdoc.get("username") or "")
        if target_user:
            hub.admin_update_applicant(target_user, {"backup_codes_remaining": 10}, admin_actor=actor)
        return {
            "ok": True,
            "backup_codes": bc["codes"],
            "backup_codes_remaining": 10,
            "profile": _ow.get_active_user_profile(sid if use_sandbox else "", sandbox=use_sandbox, base_dir=base_dir),
        }

    if act == "admin_update_account":
        target = str(body.get("applicant_id") or body.get("target_username") or body.get("username") or "").strip()
        updates = body.get("updates") if isinstance(body.get("updates"), dict) else body
        return hub.admin_update_applicant(target, updates, admin_actor=actor)

    if act == "admin_create_account":
        rec = body.get("applicant") if isinstance(body.get("applicant"), dict) else body
        res = hub.register_applicant_signup(rec)
        hub.record_admin_audit(
            "admin_create_account",
            str(res.get("applicant", {}).get("username") or ""),
            f"Admin manually registered account '{res.get('applicant', {}).get('display_name')}' ({res.get('applicant', {}).get('contact_email') or 'no email'}).",
            actor=actor,
        )
        return res

    if act == "admin_reset_account":
        target = str(body.get("applicant_id") or body.get("username") or "").strip()
        reset_kind = str(body.get("reset_kind") or "send_recovery_link").strip().lower()
        app = hub.find_applicant(target)
        if app is None:
            return {"ok": False, "error": "applicant_not_found", "message": f"Account '{target}' not found."}

        if reset_kind == "send_recovery_link":
            return hub.create_account_recovery_request(
                str(app.get("username") or app.get("applicant_id")),
                recovery_type="admin_initiated_recovery",
                actor=actor,
            )
        if reset_kind == "set_temp_password":
            temp_pwd = str(body.get("temp_password") or "").strip() or f"Anchor-{secrets.token_hex(4)}!"
            salt_bytes = secrets.token_bytes(16)
            pwd_hash = hashlib.pbkdf2_hmac("sha256", temp_pwd.encode("utf-8"), salt_bytes, 120_000).hex()
            # Update local profile if matching username
            prof = _ow.get_active_user_profile(sid if use_sandbox else "", sandbox=use_sandbox, base_dir=base_dir)
            if prof.get("username") == app.get("username"):
                _ow.save_user_identity(
                    display_name=prof.get("display_name") or app.get("display_name") or "User",
                    pseudonym=prof.get("pseudonym") or app.get("pseudonym") or aap.PSEUDONYM_DEFAULT,
                    username=str(app.get("username") or ""),
                    password=temp_pwd,
                    contact_email=str(app.get("contact_email") or prof.get("contact_email") or ""),
                    sandbox=use_sandbox,
                    sandbox_id=sid,
                    base_dir=base_dir,
                )
            hub.admin_update_applicant(
                str(app.get("applicant_id")),
                {"account_status": "active"},
                admin_actor=actor,
            )
            hub.record_admin_audit(
                "admin_set_temp_password",
                str(app.get("username")),
                f"Admin set temporary password (PBKDF2 hash {pwd_hash[:12]}…) for '{app.get('display_name')}'.",
                actor=actor,
            )
            return {
                "ok": True,
                "username": app.get("username"),
                "temp_password": temp_pwd,
                "message": f"Set temporary password for '{app.get('username')}': {temp_pwd}",
            }
        if reset_kind == "reset_2fa":
            raw_b32 = base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=")
            new_secret = " ".join(raw_b32[i:i + 4] for i in range(0, len(raw_b32), 4))
            bc = generate_2fa_backup_codes(10)
            hub.admin_update_applicant(
                str(app.get("applicant_id")),
                {"dual_auth_enabled": True, "backup_codes_remaining": 10},
                admin_actor=actor,
            )
            prof = _ow.get_active_user_profile(sid if use_sandbox else "", sandbox=use_sandbox, base_dir=base_dir)
            if prof.get("username") == app.get("username"):
                pfile = _ow.user_profile_path(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
                if pfile.is_file():
                    try:
                        pdoc = json.loads(pfile.read_text(encoding="utf-8"))
                        pdoc["dual_auth_enabled"] = True
                        pdoc["dual_auth_secret"] = new_secret
                        pdoc["dual_auth_backup_codes"] = bc["codes"]
                        pdoc["dual_auth_backup_hashes"] = bc["hashed_records"]
                        with paths.WRITE_LOCK:
                            paths.atomic_write_text(pfile, json.dumps(pdoc, indent=2, ensure_ascii=False) + "\n")
                    except Exception:
                        pass
            hub.record_admin_audit(
                "admin_reset_2fa",
                str(app.get("username")),
                f"Admin rotated 2FA secret and issued 10 fresh single-use backup codes for '{app.get('display_name')}'.",
                actor=actor,
            )
            return {
                "ok": True,
                "username": app.get("username"),
                "new_dual_auth_secret": new_secret,
                "new_backup_codes": bc["codes"],
                "backup_codes_remaining": 10,
                "message": f"Reset 2FA for '{app.get('username')}' — new TOTP secret & 10 backup codes generated.",
            }
        if reset_kind == "disable_2fa":
            hub.admin_update_applicant(
                str(app.get("applicant_id")),
                {"dual_auth_enabled": False, "backup_codes_remaining": 0},
                admin_actor=actor,
            )
            prof = _ow.get_active_user_profile(sid if use_sandbox else "", sandbox=use_sandbox, base_dir=base_dir)
            if prof.get("username") == app.get("username"):
                _ow.save_user_identity(
                    display_name=prof.get("display_name") or app.get("display_name") or "User",
                    pseudonym=prof.get("pseudonym") or app.get("pseudonym") or aap.PSEUDONYM_DEFAULT,
                    username=str(app.get("username") or ""),
                    dual_auth_enabled=False,
                    contact_email=str(app.get("contact_email") or prof.get("contact_email") or ""),
                    sandbox=use_sandbox,
                    sandbox_id=sid,
                    base_dir=base_dir,
                )
            return {
                "ok": True,
                "username": app.get("username"),
                "dual_auth_enabled": False,
                "message": f"Disabled 2FA for '{app.get('username')}' so they can sign in and re-enroll.",
            }
        if reset_kind == "rotate_token":
            tok_info = _ow._resolve_or_create_anchor_token(
                sandbox=use_sandbox,
                sandbox_id=sid,
                base_dir=base_dir,
                regenerate=True,
            )
            hub.record_admin_audit(
                "admin_rotate_anchor_token",
                str(app.get("username")),
                f"Admin rotated ANCHOR_TOKEN ({tok_info.get('anchor_token_masked')}).",
                actor=actor,
            )
            return {
                "ok": True,
                "username": app.get("username"),
                **tok_info,
                "message": f"Rotated ANCHOR_TOKEN for '{app.get('username')}' ({tok_info.get('anchor_token_masked')}).",
            }
        return {"ok": False, "error": f"Unknown reset_kind: {reset_kind}"}

    if act == "admin_delete_account":
        target = str(body.get("applicant_id") or body.get("username") or "").strip()
        return hub.admin_delete_applicant(target, admin_actor=actor)

    if act == "admin_register_shared_doc":
        return hub.register_shared_document(body, actor=actor)

    if act == "admin_revoke_shared_doc":
        return hub.revoke_shared_document(str(body.get("doc_id") or ""), actor=actor)

    if act == "admin_grant_acl":
        granter = str(body.get("granter_pseudonym") or aap.PSEUDONYM_DEFAULT).strip()
        grantee = str(body.get("grantee_pseudonym") or "").strip()
        proj_uid = str(body.get("project_uid") or "anchor-collab").strip()
        grant = aap.create_acl_grant(
            project_uid=proj_uid,
            grantee_did=aap.did_from_pseudonym(grantee),
            grantee_pseudonym=grantee,
            granter_did=aap.did_from_pseudonym(granter),
        )
        res = hub.record_acl_grant(grant)
        hub.record_admin_audit("admin_grant_acl", proj_uid, f"Granted ACL from {granter} to {grantee} on {proj_uid}", actor=actor)
        hub._sync_to_dev_backups()
        return res

    if act == "admin_sync_backups":
        cat = hub.publish_verified_model_catalog()
        synced = hub._sync_to_dev_backups()
        hub.record_admin_audit("admin_sync_backups", "gwl-hub", f"Synced hub & model catalog to {', '.join(synced)}", actor=actor)
        return {
            "ok": True,
            "backup_directories": synced,
            "published_at": cat.get("published_at"),
            "message": f"Synced all GWL Hub registries, shared docs, recovery outbox, and model catalog to {', '.join(synced)}!",
        }

    raise ValueError(f"Unknown GWL admin action: {act}")


def render_account_recovery_html(
    token: str = "",
    *,
    sandbox: bool = False,
    sandbox_id: str = "desktop-walkthrough",
    base_dir: Path | str | None = None,
) -> str:
    """Render the standalone Self-Service Account, Username, Password & 2FA Recovery Web Portal (`GET /recover-account`)."""
    esc_tok = html.escape(str(token or "").strip(), quote=True)
    guide_json = json.dumps(STANDARD_2FA_RECOVERY_GUIDE, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Anchor · Account, Username, Password &amp; 2FA Recovery</title>
  <style>
    :root {{
      --bg:#0b0f17; --panel:#131a26; --card:#182130; --border:#2a364d;
      --text:#e6edf3; --muted:#93a1b5; --gold:#eab308; --emerald:#10b981; --sky:#38bdf8;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; padding:24px; }}
    .wrap {{ max-width:880px; margin:0 auto; }}
    .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px 24px; margin-bottom:18px; }}
    h1, h2, h3 {{ margin-top:0; }}
    label {{ display:block; font-size:12px; font-weight:600; color:var(--muted); margin-bottom:6px; }}
    input[type="text"], input[type="email"], input[type="password"] {{
      width:100%; padding:10px 12px; background:#0f1622; border:1px solid var(--border); border-radius:8px; color:var(--text); font-size:14px; margin-bottom:12px;
    }}
    .btn {{ padding:9px 15px; border-radius:8px; border:1px solid var(--border); background:#243247; color:var(--text); font-weight:600; font-size:13px; cursor:pointer; text-decoration:none; display:inline-flex; align-items:center; gap:6px; }}
    .btn.primary {{ background:var(--gold); color:#0b0f17; border-color:var(--gold); }}
    .btn.emerald {{ background:var(--emerald); color:#06281e; border-color:var(--emerald); }}
    .banner {{ padding:12px 16px; border-radius:8px; background:rgba(56,189,248,0.12); border:1px solid rgba(56,189,248,0.4); color:#bae6fd; margin-bottom:16px; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    .pill {{ display:inline-block; padding:3px 9px; border-radius:999px; font-size:11px; font-weight:700; background:#243247; color:var(--sky); }}
    code {{ background:#0d131d; padding:2px 6px; border-radius:4px; color:#fde68a; font-family:Consolas,monospace; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:16px">
      <h1 style="margin:0;font-size:22px">🔑 Anchor · Account, Username, Password &amp; 2FA Recovery</h1>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <a class="btn" href="/onboard-wizard">← Onboarding Wizard</a>
        <a class="btn" href="/setup">⚙ Provider Setup</a>
        <a class="btn" href="/gwl-admin">🛡 Collaboration Admin GUI</a>
      </div>
    </div>

    <div id="recBanner" class="banner">
      Forgot your Username or Password, or lost your Two-Factor Authenticator (2FA) device? Request a recovery link using your Contact Email below, or redeem a 2FA Backup Code.
    </div>

    <!-- STEP 1: REQUEST RECOVERY LINK -->
    <div class="card">
      <h2>Step 1 · Request Username Reminder &amp; Password / 2FA Recovery Link</h2>
      <p class="muted">Enter your registered <strong>Contact Email</strong> (or your Display Name, Username, or Collaborator Pseudonym). Anchor will remind you of your Username and generate a single-use 30-minute recovery link.</p>
      <label for="inpRecIdentifier">Contact Email, Username, or Pseudonym</label>
      <input type="text" id="inpRecIdentifier" placeholder="e.g., merrill@psu.edu, john, or Samwise Gamgee">
      <button type="button" class="btn primary" id="btnSendRecoveryLink">📧 Send Username &amp; Password Recovery Link</button>
      <div id="recOutboxPreview" style="margin-top:14px" hidden></div>
    </div>

    <!-- STEP 2: COMPLETE RECOVERY WITH TOKEN OR 2FA BACKUP CODE -->
    <div class="card">
      <h2>Step 2 · Complete Account Recovery (Reset Password &amp; Optional 2FA Re-Enrollment)</h2>
      <label for="inpRecToken">Single-Use Recovery Link Token</label>
      <input type="text" id="inpRecToken" value="{esc_tok}" placeholder="rec_...">
      <label for="inpRecNewPassword">New Login Password (Stored in OS Vault + PBKDF2-SHA256)</label>
      <input type="password" id="inpRecNewPassword" placeholder="Enter your new password">
      <label for="inpRecBackupCode">Optional: 2FA Single-Use Backup Code (if recovering 2FA with one of your 10 saved codes)</label>
      <input type="text" id="inpRecBackupCode" placeholder="e.g., GWL4-9K2M-7P3X">
      <label style="display:flex;align-items:center;gap:8px;margin:8px 0 14px;cursor:pointer;color:var(--text)">
        <input type="checkbox" id="chkReset2FA">
        <span>Lost Authenticator App? Reset &amp; Re-Enroll 2FA (Issues a fresh TOTP Secret + 10 new single-use Backup Codes)</span>
      </label>
      <button type="button" class="btn emerald" id="btnCompleteRecovery">✓ Complete Account Recovery &amp; Save New Credentials</button>
      <div id="recResultBox" style="margin-top:14px" hidden></div>
    </div>

    <!-- STANDARD 2FA RECOVERY REFERENCE -->
    <div class="card" style="background:#101723">
      <h3>🛡 Standard Two-Factor Authentication (2FA) Recovery in Anchor (3 Layers)</h3>
      <div class="muted" style="line-height:1.55">
        <p><strong>Layer 1 · 10 Single-Use Backup Codes:</strong> Generated automatically when you enable 2FA. Each code (<code>XXXX-XXXX-XXXX</code>) can be used once if your phone is unavailable.</p>
        <p><strong>Layer 2 · Verified Contact Email Recovery Link:</strong> Sends a 30-minute single-use link to your Contact Email that reminds you of your Username and lets you re-enroll 2FA or reset your password.</p>
        <p><strong>Layer 3 · System Administrator Assisted Reset (<code>/gwl-admin</code>):</strong> On the Puter Mothership, an Anchor System Admin can reset 2FA, issue 10 fresh backup codes, or set a temporary password at any time.</p>
      </div>
    </div>
  </div>

  <script>
    const GUIDE = {guide_json};
    document.getElementById('btnSendRecoveryLink').addEventListener('click', async () => {{
      const ident = document.getElementById('inpRecIdentifier').value.trim();
      if (!ident) {{
        document.getElementById('recBanner').textContent = 'Please enter your Contact Email, Username, or Pseudonym.';
        return;
      }}
      const res = await fetch('/api/gwl-admin/action', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ action: 'request_account_recovery', identifier: ident, base_url: window.location.origin }})
      }});
      const out = await res.json();
      const box = document.getElementById('recOutboxPreview');
      box.hidden = false;
      if (!out.ok) {{
        box.innerHTML = `<div style="color:#fca5a5;font-weight:600">⚠ ${{out.message || out.error}}</div>`;
        return;
      }}
      document.getElementById('inpRecToken').value = out.recovery_token || '';
      document.getElementById('recBanner').textContent = out.message;
      box.innerHTML = `
        <div style="padding:12px;background:#0d131d;border:1px solid #064e3b;border-radius:8px">
          <div><span class="pill" style="background:#064e3b;color:#6ee7b7">RECOVERY LINK READY ✓</span> <strong>Username Reminder:</strong> <code>${{out.username}}</code> · <strong>Pseudonym:</strong> <code>${{out.pseudonym}}</code></div>
          <div class="muted" style="margin-top:6px">Recovery URL: <a href="${{out.recovery_url}}" style="color:#38bdf8">${{out.recovery_url}}</a> (Token auto-filled in Step 2 below!)</div>
          <pre style="margin:8px 0 0;font-size:12px;color:#cbd5e1;white-space:pre-wrap">${{out.email_preview}}</pre>
        </div>
      `;
    }});

    document.getElementById('btnCompleteRecovery').addEventListener('click', async () => {{
      const tok = document.getElementById('inpRecToken').value.trim();
      const pwd = document.getElementById('inpRecNewPassword').value;
      const bcode = document.getElementById('inpRecBackupCode').value.trim();
      const reset2fa = document.getElementById('chkReset2FA').checked;
      const res = await fetch('/api/gwl-admin/action', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          action: 'complete_account_recovery',
          token: tok,
          new_password: pwd,
          backup_code: bcode,
          reset_2fa: reset2fa
        }})
      }});
      const out = await res.json();
      const rBox = document.getElementById('recResultBox');
      rBox.hidden = false;
      if (!out.ok) {{
        rBox.innerHTML = `<div style="color:#fca5a5;font-weight:600">⚠ ${{out.message || out.error}}</div>`;
        return;
      }}
      document.getElementById('recBanner').textContent = out.message;
      const codesHtml = (out.new_backup_codes || []).map((c) => `<code>${{c}}</code>`).join(' ');
      rBox.innerHTML = `
        <div style="padding:12px;background:#0d131d;border:1px solid #10b981;border-radius:8px">
          <div><strong>✅ Account Recovered!</strong> Username: <code>${{out.username}}</code> · Pseudonym: <code>${{out.pseudonym}}</code></div>
          ${{out.new_dual_auth_secret ? `<div style="margin-top:6px"><strong>New 2FA TOTP Secret:</strong> <code>${{out.new_dual_auth_secret}}</code></div>` : ''}}
          ${{codesHtml ? `<div style="margin-top:6px"><strong>10 Fresh Single-Use 2FA Backup Codes:</strong><div style="margin-top:4px;display:flex;gap:6px;flex-wrap:wrap">${{codesHtml}}</div></div>` : ''}}
        </div>
      `;
    }});
  </script>
</body>
</html>
"""


def render_gwl_admin_gui_html(
    *,
    sandbox: bool = False,
    sandbox_id: str = "desktop-walkthrough",
    base_dir: Path | str | None = None,
) -> str:
    """Render the Anchor & Ghost World Labs Collaboration System Admin GUI (`GET /gwl-admin`)."""
    state = get_gwl_admin_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    boot_json = json.dumps(state, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Anchor · Collaboration System Admin GUI (Puter / gwl-hub)</title>
  <style>
    :root {{
      --bg:#0b0f17; --panel:#131a26; --card:#182130; --border:#2a364d;
      --text:#e6edf3; --muted:#93a1b5; --gold:#eab308; --emerald:#10b981; --sky:#38bdf8; --danger:#ef4444;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
    header.adm-top {{
      display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;
      padding:14px 24px; background:var(--panel); border-bottom:1px solid var(--border);
      cursor:move; user-select:none;
    }}
    .wrap {{ max-width:1360px; margin:0 auto; padding:22px 24px 60px; }}
    .card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:18px 20px; margin-bottom:18px; }}
    h1, h2, h3, h4 {{ margin-top:0; }}
    .stat-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(175px,1fr)); gap:12px; margin-bottom:18px; }}
    .stat-box {{ background:#101723; border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
    .stat-num {{ font-size:24px; font-weight:800; color:var(--gold); }}
    .form-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:12px; }}
    label {{ display:block; font-size:12px; font-weight:600; color:var(--muted); margin-bottom:4px; }}
    input[type="text"], input[type="email"], input[type="password"], select, textarea {{
      width:100%; padding:8px 10px; background:#0f1622; border:1px solid var(--border); border-radius:8px; color:var(--text); font-size:13px;
    }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th, td {{ text-align:left; padding:10px 8px; border-bottom:1px solid var(--border); vertical-align:top; }}
    th {{ color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:0.5px; }}
    .btn {{ padding:7px 12px; border-radius:8px; border:1px solid var(--border); background:#243247; color:var(--text); font-weight:600; font-size:12px; cursor:pointer; text-decoration:none; display:inline-flex; align-items:center; gap:5px; }}
    .btn:hover {{ border-color:var(--sky); }}
    .btn.primary {{ background:var(--gold); color:#0b0f17; border-color:var(--gold); }}
    .btn.emerald {{ background:var(--emerald); color:#06281e; border-color:var(--emerald); }}
    .btn.danger {{ background:#7f1d1d; color:#fecaca; border-color:#b91c1c; }}
    .pill {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:700; background:#243247; color:var(--sky); }}
    .banner {{ padding:12px 16px; border-radius:8px; background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.4); color:#a7f3d0; margin-bottom:16px; }}
    .muted {{ color:var(--muted); font-size:12px; }}
    code {{ background:#0d131d; padding:2px 6px; border-radius:4px; color:#fde68a; font-family:Consolas,monospace; font-size:12px; }}
  </style>
</head>
<body>
  <header class="adm-top">
    <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
      <strong style="font-size:17px">🛡 Anchor &amp; Ghost World Labs · Collaboration System Admin GUI (`puter` / `gwl-hub`)</strong>
      <span class="pill" style="background:#064e3b;color:#6ee7b7">LIVE CONTROL PLANE</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <button type="button" class="btn emerald" id="btnSyncHubBackups">🔄 Sync C:\\dev Backups &amp; Nightly Model Catalog</button>
      <a class="btn" href="/recover-account">🔑 Recovery Portal</a>
      <a class="btn" href="/onboard-wizard">🧭 Onboarding Wizard</a>
      <a class="btn" href="/setup">⚙ Provider Setup</a>
      <a class="btn primary" href="/high-seat">🏛 Cave of Wonders</a>
    </div>
  </header>

  <div class="wrap">
    <div id="admBanner" class="banner" role="status">
      System Administrator Control Center ready. Review registered collaborators, make manual account edits, issue password/username recovery links, reset 2FA, and manage shared collaboration documents.
    </div>

    <!-- STAT SUMMARY -->
    <div class="stat-grid" id="admStatsGrid"></div>

    <!-- 1. WHERE THE MAIN ANCHOR SERVER & COLLABORATION HUB LIVE -->
    <div class="card">
      <h2>🏛 1 · Where the Main Anchor Server, Registrations &amp; Shared Collaboration Docs Live</h2>
      <div id="serverLocationsBox" class="form-grid"></div>
    </div>

    <!-- 2. REGISTERED ACCOUNTS & APPLICANTS (REVIEW, MANUAL EDIT, PASSWORD / 2FA RESET) -->
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">
        <h2 style="margin:0">👥 2 · Registered Accounts &amp; Collaborators (Review, Manual Edit &amp; Account Reset)</h2>
        <button type="button" class="btn primary" id="btnOpenNewAccountEditor">➕ Add / Register Collaborator Account</button>
      </div>
      <div style="overflow-x:auto">
        <table id="applicantsTable">
          <thead>
            <tr>
              <th>Display Name &amp; Role</th>
              <th>Username &amp; Contact Email</th>
              <th>Pseudonym (`DID`)</th>
              <th>Host / Tailscale / Topology</th>
              <th>2FA &amp; Backup Codes</th>
              <th>AI Services &amp; Status</th>
              <th>Admin Actions (Edit · Reset · Recover)</th>
            </tr>
          </thead>
          <tbody id="applicantsTbody"></tbody>
        </table>
      </div>

      <!-- MANUAL ACCOUNT EDITOR / CREATOR DRAWER -->
      <div id="accountEditorBox" class="card" style="background:#101723;margin-top:16px" hidden>
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <h3 id="editorTitle" style="margin:0">✏ Manual Account Edit / Review</h3>
          <button type="button" class="btn" id="btnCloseAccountEditor">✕ Close</button>
        </div>
        <input type="hidden" id="editApplicantId">
        <div class="form-grid">
          <div>
            <label for="editDisplayName">Display Name</label>
            <input type="text" id="editDisplayName" placeholder="e.g., Merrill">
          </div>
          <div>
            <label for="editUsername">Username</label>
            <input type="text" id="editUsername" placeholder="e.g., merrill">
          </div>
          <div>
            <label for="editContactEmail">Contact / Recovery Email</label>
            <input type="email" id="editContactEmail" placeholder="e.g., merrill@psu.edu">
          </div>
          <div>
            <label for="editPseudonym">Collaborator Pseudonym</label>
            <input type="text" id="editPseudonym" placeholder="e.g., Gandalf the Grey">
          </div>
          <div>
            <label for="editAliases">Pseudonym Aliases (comma-separated)</label>
            <input type="text" id="editAliases" placeholder="e.g., Gandalf, Mithrandir">
          </div>
          <div>
            <label for="editRole">System Role</label>
            <select id="editRole">
              <option value="admin">admin (System Administrator)</option>
              <option value="member">member (Mothership Owner / Peer)</option>
              <option value="collaborator">collaborator (External Collaborator)</option>
            </select>
          </div>
          <div>
            <label for="editStatus">Account Status</label>
            <select id="editStatus">
              <option value="active">active</option>
              <option value="pending_recovery">pending_recovery</option>
              <option value="suspended">suspended</option>
            </select>
          </div>
          <div>
            <label for="editPersona">Companion Steward Persona</label>
            <select id="editPersona">
              <option value="Aladdin">Aladdin</option>
              <option value="Jarvis">Jarvis</option>
              <option value="Ecgberht">Ecgberht</option>
            </select>
          </div>
          <div>
            <label for="editTailscaleIp">Tailscale IP / Host</label>
            <input type="text" id="editTailscaleIp" placeholder="e.g., 100.64.0.2">
          </div>
          <div>
            <label for="editNotes">Admin Notes</label>
            <input type="text" id="editNotes" placeholder="Optional admin notes...">
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
          <button type="button" class="btn emerald" id="btnSaveAccountEdit">✓ Save Manual Account Changes</button>
        </div>
      </div>

      <!-- ADMIN RESET / RECOVERY ACTION OUTPUT -->
      <div id="adminResetOutputBox" class="card" style="background:#0d131d;margin-top:14px" hidden></div>
    </div>

    <!-- 3. SHARED COLLABORATION DOCUMENTS, WORKSPACES & ACL GRANTS -->
    <div class="card">
      <h2>📄 3 · Shared Collaboration Documents, Workspaces &amp; Pseudonym ACL Ledger</h2>
      <div class="form-grid" style="margin-bottom:12px;background:#101723;padding:14px;border-radius:10px">
        <div>
          <label for="inpDocTitle">Document / Brief / Workspace Title</label>
          <input type="text" id="inpDocTitle" placeholder="e.g., Collapse of Marketing · JCR Shared Brief">
        </div>
        <div>
          <label for="inpDocUrl">Path or URL on Server</label>
          <input type="text" id="inpDocUrl" placeholder="/project/collapse-of-marketing/brief">
        </div>
        <div>
          <label for="inpDocOwner">Owner Pseudonym</label>
          <input type="text" id="inpDocOwner" value="Samwise Gamgee">
        </div>
        <div>
          <label for="inpDocSharedWith">Shared With Pseudonyms (comma-separated)</label>
          <input type="text" id="inpDocSharedWith" placeholder="e.g., Gandalf the Grey, Aladdin">
        </div>
      </div>
      <button type="button" class="btn primary" id="btnAddSharedDoc">🔗 Register / Share Document with Collaborators</button>
      <div id="sharedDocsListBox" style="margin-top:14px"></div>
    </div>

    <!-- 4. RECOVERY LINK OUTBOX & ADMIN SECURITY AUDIT LOG -->
    <div class="form-grid">
      <div class="card">
        <h3>📧 4A · Account Recovery Link Outbox (`recovery_requests.json`)</h3>
        <div id="recoveryRequestsBox"></div>
      </div>
      <div class="card">
        <h3>📜 4B · Admin &amp; Security Audit Trail (`admin_audit_log.json`)</h3>
        <div id="auditLogBox"></div>
      </div>
    </div>
  </div>

  <script>
    window.GWL_ADMIN_BOOT = {boot_json};

    async function callAdminAction(action, payload = {{}}) {{
      const res = await fetch('/api/gwl-admin/action', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(Object.assign({{ action }}, payload))
      }});
      return await res.json();
    }}

    async function refreshAdminState() {{
      const res = await fetch('/api/gwl-admin/state');
      const st = await res.json();
      window.GWL_ADMIN_BOOT = st;
      renderAdminAll(st);
    }}

    function renderAdminAll(st) {{
      const c = st.counts || {{}};
      document.getElementById('admStatsGrid').innerHTML = `
        <div class="stat-box"><div class="stat-num">${{c.applicants || 0}}</div><div class="muted">Registered Individuals</div></div>
        <div class="stat-box"><div class="stat-num">${{c.active_accounts || 0}}</div><div class="muted">Active Accounts</div></div>
        <div class="stat-box"><div class="stat-num">${{c.twofa_enabled || 0}}</div><div class="muted">2FA Protected</div></div>
        <div class="stat-box"><div class="stat-num">${{c.shared_documents || 0}}</div><div class="muted">Shared Docs / Briefs</div></div>
        <div class="stat-box"><div class="stat-num">${{c.pending_recoveries || 0}}</div><div class="muted">Pending Recovery Links</div></div>
        <div class="stat-box"><div class="stat-num">${{c.audit_events || 0}}</div><div class="muted">Admin Audit Events</div></div>
      `;

      const loc = st.server_locations || {{}};
      const files = loc.files || {{}};
      document.getElementById('serverLocationsBox').innerHTML = `
        <div class="stat-box">
          <strong>🖥 Live Main Server Host</strong>
          <div class="muted" style="margin-top:4px">Host: <code>${{loc.host_machine || 'PUTER'}}</code><br>Service: <code>${{loc.windows_service || 'NSSM anchor'}}</code><br>Tailscale URL: <code>${{loc.tailscale_mothership_url || 'http://puter:8777'}}</code></div>
        </div>
        <div class="stat-box">
          <strong>📂 Active GWL Hub &amp; C:\\dev Backups</strong>
          <div class="muted" style="margin-top:4px">Live Hub: <code>${{loc.active_hub_directory || ''}}</code><br>Backed up in: <code>${{(loc.backup_repositories_in_dev || []).join('</code> &amp; <code>')}}</code></div>
        </div>
        <div class="stat-box">
          <strong>📑 Registry, Shared Docs &amp; Recovery Files</strong>
          <div class="muted" style="margin-top:4px">Applicants: <code>applicants_registry.json</code> &amp; <code>APPLICANTS.md</code><br>Shared Docs: <code>shared_documents_registry.json</code><br>Recovery Outbox: <code>recovery_requests.json</code></div>
        </div>
      `;

      const tbody = document.getElementById('applicantsTbody');
      const apps = st.applicants || [];
      if (!apps.length) {{
        tbody.innerHTML = '<tr><td colspan="7" class="muted">No registered individuals yet. Click "Add / Register Collaborator Account" above or save Step 1 in the Onboarding Wizard.</td></tr>';
      }} else {{
        tbody.innerHTML = apps.map((a) => `
          <tr>
            <td>
              <strong>${{a.display_name || ''}}</strong>
              <div><span class="pill">${{a.role || 'member'}}</span> <span class="pill" style="background:${{a.account_status === 'active' ? '#064e3b' : '#78350f'}};color:#fff">${{a.account_status || 'active'}}</span></div>
            </td>
            <td>
              <code>${{a.username || ''}}</code>
              <div class="muted">📧 ${{a.contact_email || 'No email set'}}</div>
            </td>
            <td>
              <strong>${{a.pseudonym || ''}}</strong>
              <div class="muted"><code>${{a.did || ''}}</code></div>
            </td>
            <td>
              <code>${{a.hostname || 'local'}}</code> (${{a.tailscale_ip || 'local'}})
              <div class="muted">${{a.topology_mode || 'main_mothership'}} · Steward: ${{a.steward_persona || 'Aladdin'}}</div>
            </td>
            <td>
              ${{a.dual_auth_enabled
                ? `<span class="pill" style="background:#064e3b;color:#6ee7b7">2FA ON (${{a.dual_auth_method || 'totp'}})</span><div class="muted">${{a.backup_codes_remaining ?? 10}} backup codes left</div>`
                : '<span class="pill">2FA Off</span>'}}
            </td>
            <td>
              <div class="muted">${{(a.enabled_services || []).join(', ') || 'pending'}}</div>
              ${{a.notes ? `<div class="muted" style="color:#fde68a">Note: ${{a.notes}}</div>` : ''}}
            </td>
            <td>
              <div style="display:flex;gap:5px;flex-wrap:wrap">
                <button type="button" class="btn" data-adm-edit="${{a.username}}">✏ Edit</button>
                <button type="button" class="btn primary" data-adm-reset="send_recovery_link" data-user="${{a.username}}">📧 Recovery Link</button>
                <button type="button" class="btn" data-adm-reset="set_temp_password" data-user="${{a.username}}">🔑 Temp Password</button>
                <button type="button" class="btn emerald" data-adm-reset="reset_2fa" data-user="${{a.username}}">🛡 Reset 2FA + 10 Codes</button>
                <button type="button" class="btn" data-adm-reset="disable_2fa" data-user="${{a.username}}">Disable 2FA</button>
                <button type="button" class="btn danger" data-adm-del="${{a.username}}">🗑</button>
              </div>
            </td>
          </tr>
        `).join('');
      }}

      tbody.querySelectorAll('[data-adm-edit]').forEach((btn) => {{
        btn.addEventListener('click', () => {{
          const u = btn.getAttribute('data-adm-edit');
          const app = (st.applicants || []).find((x) => x.username === u);
          if (!app) return;
          document.getElementById('accountEditorBox').hidden = false;
          document.getElementById('editorTitle').textContent = `✏ Edit Account: ${{app.display_name}} (${{app.username}})`;
          document.getElementById('editApplicantId').value = app.applicant_id || '';
          document.getElementById('editDisplayName').value = app.display_name || '';
          document.getElementById('editUsername').value = app.username || '';
          document.getElementById('editContactEmail').value = app.contact_email || '';
          document.getElementById('editPseudonym').value = app.pseudonym || '';
          document.getElementById('editAliases').value = (app.pseudonym_aliases || []).join(', ');
          document.getElementById('editRole').value = app.role || 'member';
          document.getElementById('editStatus').value = app.account_status || 'active';
          document.getElementById('editPersona').value = app.steward_persona || 'Aladdin';
          document.getElementById('editTailscaleIp').value = app.tailscale_ip || '';
          document.getElementById('editNotes').value = app.notes || '';
        }});
      }});

      tbody.querySelectorAll('[data-adm-reset]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          const u = btn.getAttribute('data-user');
          const rk = btn.getAttribute('data-adm-reset');
          const out = await callAdminAction('admin_reset_account', {{ username: u, reset_kind: rk }});
          const outBox = document.getElementById('adminResetOutputBox');
          outBox.hidden = false;
          document.getElementById('admBanner').textContent = out.message || 'Admin reset action completed.';
          outBox.innerHTML = `
            <div><strong>⚡ Admin Reset Result (${{rk}} for <code>${{u}}</code>):</strong> ${{out.message || ''}}</div>
            ${{out.recovery_url ? `<div style="margin-top:6px">Recovery Link: <a href="${{out.recovery_url}}" style="color:#38bdf8">${{out.recovery_url}}</a> (Token: <code>${{out.recovery_token}}</code>)</div>` : ''}}
            ${{out.temp_password ? `<div style="margin-top:6px">Temporary Password: <code>${{out.temp_password}}</code></div>` : ''}}
            ${{out.new_dual_auth_secret ? `<div style="margin-top:6px">New 2FA TOTP Secret: <code>${{out.new_dual_auth_secret}}</code></div>` : ''}}
            ${{(out.new_backup_codes || []).length ? `<div style="margin-top:6px">10 Fresh Backup Codes: ${{(out.new_backup_codes || []).map((c) => `<code>${{c}}</code>`).join(' ')}}</div>` : ''}}
          `;
          await refreshAdminState();
        }});
      }});

      tbody.querySelectorAll('[data-adm-del]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          const u = btn.getAttribute('data-adm-del');
          await callAdminAction('admin_delete_account', {{ username: u }});
          document.getElementById('admBanner').textContent = `Removed account '${{u}}' from active registry.`;
          await refreshAdminState();
        }});
      }});

      // Shared Documents
      const sBox = document.getElementById('sharedDocsListBox');
      const docs = st.shared_documents || [];
      sBox.innerHTML = docs.map((d) => `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#101723;border:1px solid var(--border);border-radius:8px;margin-bottom:8px;flex-wrap:wrap;gap:8px">
          <div>
            <strong>📄 ${{d.title}}</strong> <span class="pill">${{d.doc_type}}</span> <span class="pill">${{d.permissions}}</span>
            <div class="muted">Path/URL: <a href="${{d.path_or_url}}" style="color:#38bdf8">${{d.path_or_url}}</a> · Owner: <strong>${{d.owner_pseudonym}}</strong> · Shared with: <strong>${{(d.shared_with || []).join(', ')}}</strong></div>
          </div>
          <button type="button" class="btn danger" data-revoke-doc="${{d.doc_id}}">Revoke</button>
        </div>
      `).join('');
      sBox.querySelectorAll('[data-revoke-doc]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          await callAdminAction('admin_revoke_shared_doc', {{ doc_id: btn.getAttribute('data-revoke-doc') }});
          await refreshAdminState();
        }});
      }});

      // Recovery Requests
      const rBox = document.getElementById('recoveryRequestsBox');
      const reqs = st.recovery_requests || [];
      rBox.innerHTML = reqs.length
        ? reqs.slice(0, 12).map((r) => `
            <div style="padding:8px 10px;background:#101723;border-radius:6px;margin-bottom:6px;font-size:12px">
              <strong>${{r.display_name}}</strong> (<code>${{r.username}}</code> · ${{r.contact_email || 'no email'}}) — <span class="pill">${{r.status}}</span>
              <div class="muted">${{r.created_at}} · <a href="${{r.recovery_url}}" style="color:#38bdf8">Open Recovery Link</a></div>
            </div>
          `).join('')
        : '<p class="muted">No recovery links requested yet.</p>';

      // Audit Log
      const aBox = document.getElementById('auditLogBox');
      const logs = st.audit_log || [];
      aBox.innerHTML = logs.length
        ? logs.slice(0, 15).map((ev) => `
            <div style="padding:8px 10px;background:#101723;border-radius:6px;margin-bottom:6px;font-size:12px">
              <strong>${{ev.action}}</strong> → <code>${{ev.target}}</code> <span class="muted">by ${{ev.actor}} at ${{ev.at}}</span>
              <div class="muted">${{ev.detail}}</div>
            </div>
          `).join('')
        : '<p class="muted">No admin audit events recorded yet.</p>';
    }}

    document.getElementById('btnOpenNewAccountEditor').addEventListener('click', () => {{
      document.getElementById('accountEditorBox').hidden = false;
      document.getElementById('editorTitle').textContent = '➕ Register / Add New Collaborator Account';
      document.getElementById('editApplicantId').value = '';
      document.getElementById('editDisplayName').value = '';
      document.getElementById('editUsername').value = '';
      document.getElementById('editContactEmail').value = '';
      document.getElementById('editPseudonym').value = '';
      document.getElementById('editAliases').value = '';
      document.getElementById('editNotes').value = '';
    }});

    document.getElementById('btnCloseAccountEditor').addEventListener('click', () => {{
      document.getElementById('accountEditorBox').hidden = true;
    }});

    document.getElementById('btnSaveAccountEdit').addEventListener('click', async () => {{
      const appId = document.getElementById('editApplicantId').value.trim();
      const payload = {{
        applicant_id: appId || undefined,
        display_name: document.getElementById('editDisplayName').value.trim(),
        username: document.getElementById('editUsername').value.trim(),
        contact_email: document.getElementById('editContactEmail').value.trim(),
        pseudonym: document.getElementById('editPseudonym').value.trim(),
        pseudonym_aliases: document.getElementById('editAliases').value.trim(),
        role: document.getElementById('editRole').value,
        account_status: document.getElementById('editStatus').value,
        steward_persona: document.getElementById('editPersona').value,
        tailscale_ip: document.getElementById('editTailscaleIp').value.trim(),
        notes: document.getElementById('editNotes').value.trim(),
      }};
      const act = appId ? 'admin_update_account' : 'admin_create_account';
      const out = await callAdminAction(act, payload);
      document.getElementById('accountEditorBox').hidden = true;
      document.getElementById('admBanner').textContent = `Saved account '${{payload.display_name || payload.username}}' and mirrored to C:\\dev backups!`;
      await refreshAdminState();
    }});

    document.getElementById('btnAddSharedDoc').addEventListener('click', async () => {{
      const title = document.getElementById('inpDocTitle').value.trim();
      if (!title) return;
      await callAdminAction('admin_register_shared_doc', {{
        title,
        path_or_url: document.getElementById('inpDocUrl').value.trim() || `/project/${{title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}}/brief`,
        owner_pseudonym: document.getElementById('inpDocOwner').value.trim() || 'Samwise Gamgee',
        shared_with: document.getElementById('inpDocSharedWith').value.trim() || 'All Collaborators',
      }});
      document.getElementById('inpDocTitle').value = '';
      document.getElementById('admBanner').textContent = `Shared document '${{title}}' registered in gwl-hub!`;
      await refreshAdminState();
    }});

    document.getElementById('btnSyncHubBackups').addEventListener('click', async () => {{
      const out = await callAdminAction('admin_sync_backups', {{}});
      document.getElementById('admBanner').textContent = out.message || 'Synced C:\\dev backups!';
      await refreshAdminState();
    }});

    renderAdminAll(window.GWL_ADMIN_BOOT);
  </script>
</body>
</html>
"""
