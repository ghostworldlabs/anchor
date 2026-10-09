"""W3 of the night of 2026-10-10: links in a steward's reply open the right thing, or say why they cannot.

John (2026-10-08): "...giving me summaries with links that are broken ... happens pretty regularly". Nothing checked
the links a model wrote; only Anchor's own receipt line built links from the register. Now, at the end of every turn,
each link in the reply is classified by origin and route and checked against the disk:

- An EXTERNAL link (another host, mailto:) is exempt. An absolute Anchor URL (localhost / 127.0.0.1 / this host /
  the tailnet name) is an Anchor link like a relative one and is checked, then rewritten to its relative form so it
  opens through the browser's normal sign-in (the token is never written into a link).
- `/artifact/<pid>?path=<rel>`, `/artifact/<pid>/<rel>`, `/api/steward/deliverable-file?...` and `/report/...` are
  resolved against the registry and the disk: contained, not private, present, and - when the link carries a hash -
  the same bytes.
- ONE same-turn correction, by Anchor, never by guessing: a link (or a link to an HTML/Markdown copy) whose product is
  registered in this effort is rewritten to that registered item's own reading target - its registered revision,
  never another one; a registered PDF wins over the HTML beside it.
- A link that still fails is named with what failed: "not found" ONLY for a confirmed missing file; otherwise "needs
  sign-in", "changed since it was registered" or "unavailable now".

Pure apart from reading the registry and the disk; never raises (a failure leaves the reply as it was).
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

_MD_LINK = re.compile(r"(?<!!)\[([^\]\n]{1,300})\]\(([^)\s]{1,2000})\)")
_BARE = re.compile(r"(?<![(\[<`\w])(https?://[^\s<>()`\"']{3,2000})")

NOT_FOUND = "not found"
SIGN_IN = "needs sign-in"
CHANGED = "changed since it was registered"
UNAVAILABLE = "unavailable now"


def anchor_hosts():
    hosts = {"localhost", "127.0.0.1", "::1", "[::1]", "gwl-server", "puter"}
    try:
        hosts.add(socket.gethostname().lower())
    except OSError:
        pass
    extra = os.environ.get("ANCHOR_PUBLIC_HOSTS", "")
    hosts |= {h.strip().lower() for h in extra.split(",") if h.strip()}
    return hosts


def classify(url, hosts=None):
    """("external" | "anchor" | "other", the Anchor path+query or None). Relative routes are Anchor's own."""
    u = str(url or "").strip()
    if not u or u.startswith("#"):
        return "other", None
    parts = urlsplit(u)
    if parts.scheme in ("http", "https"):
        host = (parts.hostname or "").lower()
        hosts = hosts or anchor_hosts()
        if host in hosts or host.endswith(".ts.net") or host.split(".")[0] in hosts:
            if parts.port in (None, 80, 443, 8777):
                return "anchor", parts.path + (("?" + parts.query) if parts.query else "")
        return "external", None
    if parts.scheme:                      # mailto:, file:, data: ... - not an Anchor route
        return "external", None
    if u.startswith("/"):
        return "anchor", u
    return "other", None                  # a bare relative name: the receipt names files, not this checker


def _project_folder(pid):
    try:
        import rnd_registry
        rec = rnd_registry.get_project(pid)
        return (rec or {}).get("folder_path") or None
    except Exception:
        return None


def _inside(root, rel):
    """(state, Path|None): 'ok' with the file, NOT_FOUND for a contained file that is missing, UNAVAILABLE otherwise."""
    try:
        base = Path(root).resolve()
        fp = (base / unquote(rel)).resolve()
    except (OSError, ValueError):
        return UNAVAILABLE, None
    if fp != base and base not in fp.parents:
        return UNAVAILABLE, None
    if any(part in (".git", ".anchor") for part in fp.relative_to(base).parts):
        return UNAVAILABLE, None
    try:
        from provider_native import private_account_path
        if private_account_path(str(fp)):
            return UNAVAILABLE, None
    except ImportError:
        pass
    if not fp.is_file():
        return (NOT_FOUND if fp.parent.exists() or not fp.exists() else UNAVAILABLE), None
    return "ok", fp


def check_route(route):
    """The verdict for one Anchor route: "ok", or one of the four failure words. Unknown routes are "ok" (unchecked)."""
    parts = urlsplit(route)
    path, qs = parts.path, parse_qs(parts.query)
    m = re.match(r"^/artifact/([^/?#]+)(?:/(.+))?$", path)
    if m:
        pid = unquote(m.group(1))
        rel = m.group(2) or (qs.get("path") or [""])[0]
        folder = _project_folder(pid)
        if not folder or not rel:
            return UNAVAILABLE
        state, _fp = _inside(folder, rel)
        return state
    if path == "/api/steward/deliverable-file":
        pid = (qs.get("pid") or [""])[0]
        folder = _project_folder(pid)
        if not folder:
            return UNAVAILABLE
        effort = os.path.join(folder, (qs.get("dir") or [""])[0])
        state, fp = _inside(effort, (qs.get("path") or [""])[0])
        if state != "ok":
            return state
        want = (qs.get("hash") or [""])[0]
        if want:
            try:
                if hashlib.sha256(fp.read_bytes()).hexdigest() != want:
                    return CHANGED
            except OSError:
                return UNAVAILABLE
        return "ok"
    m = re.match(r"^/report/([^/]+)/([^/]+)/([^/?#]+)", path)
    if m:
        if not _project_folder(unquote(m.group(1))):
            return UNAVAILABLE
        try:
            import job_runner
            return "ok" if job_runner.load_record(unquote(m.group(3))) else NOT_FOUND
        except Exception:
            return UNAVAILABLE
    return "ok"


def _target_name(route):
    parts = urlsplit(route)
    qs = parse_qs(parts.query)
    m = re.match(r"^/artifact/[^/?#]+/(.+)$", parts.path)
    rel = unquote(m.group(1)) if m else (qs.get("path") or [""])[0]
    return rel.replace("\\", "/")


def _registered_reads(cdir):
    """{lowercase basename or stem: reading URL} for the effort's registered items, the PDF of a product first."""
    try:
        from steward_cockpit import steward_campaign as campaign
        import deliverables_register as dr
        data = campaign.read_deliverables(cdir)
        items = [i for i in (data.get("items") or []) if isinstance(i, dict) and i.get("path")]
        pid, rel = dr.project_and_rel(cdir)
        if not pid:
            return {}
        registered = {str(i.get("path") or "").replace("\\", "/").lower() for i in items}
        out = {}
        for it in sorted(items, key=lambda i: 0 if str(i["path"]).lower().endswith(".pdf") else 1):
            t = dr.reading_target(it, pid=pid, effort_rel=rel, effort_dir=cdir, registered=registered)
            if not t.get("read"):
                continue
            p = str(it["path"]).replace("\\", "/")
            name, stem = p.rsplit("/", 1)[-1].lower(), os.path.splitext(p.rsplit("/", 1)[-1])[0].lower()
            out.setdefault(name, t["read"])
            out.setdefault("stem:" + stem, t["read"])
        return out
    except Exception:
        return {}


def check_reply(text, cdir, hosts=None):
    """(corrected text, report). report: [{"url", "label", "verdict", "fixed_to"}] for every Anchor link that was
    corrected or still fails; ok and external links are not reported. Never raises."""
    try:
        return _check_reply(text, cdir, hosts or anchor_hosts())
    except Exception:
        return text, []


def _check_reply(text, cdir, hosts):
    if not text or ("](" not in text and "http" not in text):
        return text, []
    reads = None
    report = []

    def fix(label, url):
        nonlocal reads
        kind, route = classify(url, hosts)
        if kind != "anchor":
            return None
        verdict = check_route(route)
        name = _target_name(route)
        if reads is None:
            reads = _registered_reads(cdir)
        base = name.rsplit("/", 1)[-1].lower()
        stem = os.path.splitext(base)[0]
        reg = reads.get(base) if base else None
        # only a REGISTERED PDF of the same product outranks a link to its HTML/Markdown copy
        pdf_beside = reads.get("stem:" + stem) if stem and base.endswith((".html", ".htm", ".md")) else None
        better = pdf_beside if pdf_beside and ".pdf" in pdf_beside.lower() and pdf_beside != route else None
        if verdict != "ok" and reg:
            report.append({"url": url, "label": label, "verdict": verdict, "fixed_to": reg})
            return reg
        if better:
            report.append({"url": url, "label": label, "verdict": "the registered PDF", "fixed_to": better})
            return better
        if verdict != "ok":
            report.append({"url": url, "label": label, "verdict": verdict, "fixed_to": None})
            return None
        if route != url:                                            # an absolute Anchor URL: open it relatively
            return route
        return None

    def md(m):
        label, url = m.group(1), m.group(2)
        new = fix(label, url)
        return "[%s](%s)" % (label, new) if new else m.group(0)

    out = _MD_LINK.sub(md, text)

    def bare(m):
        url = m.group(1).rstrip(".,;:")
        tail = m.group(1)[len(url):]
        new = fix(url, url)
        return (new + tail) if new else m.group(0)

    out = _BARE.sub(bare, out)
    return out, report


def report_line(report):
    """One Anchor line for the dialogue, or "" when there is nothing to say."""
    if not report:
        return ""
    fixed = [r for r in report if r["fixed_to"]]
    failed = [r for r in report if not r["fixed_to"]]
    bits = []
    for r in fixed:
        bits.append("[%s](%s) now opens the registered copy%s" % (
            _plain(r["label"]), r["fixed_to"], "" if r["verdict"] == "the registered PDF" else " (the link was %s)" % r["verdict"]))
    for r in failed:
        bits.append("`%s`: %s" % (_plain(r["label"])[:120], r["verdict"]))
    return "**Anchor** · links: " + " · ".join(bits)


def _plain(s):
    return str(s or "").replace("[", "(").replace("]", ")").replace("`", "'")
