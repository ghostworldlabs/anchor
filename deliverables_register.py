"""The ONE registrar for the effort deliverables register (reports-links W2, 2026-09-05).

Criterion 1 ("a finished run registers itself") + premortem 1 (fan-out drift):
exactly ONE module knows how to resolve the effort dir, the active step, the
Where form, idempotency, locking and the atomic write. Each finish point
(gandalf.run_gandalf Hook A · job_runner._finalize Hook B ·
commission_session.finish_run Hook C) contributes only its (what, where, step)
facts in a one-line call.

The register file is ``<effort_dir>/DELIVERABLES.md`` with the header contract
``| What | Where | Date | Step |`` (written down once in
``steward_campaign.read_deliverables``; minted here when the file is absent).
A row's Where cell is one of the three forms :func:`where_for` emits — all of
which round-trip through ``read_deliverables`` as openable:

- an artifact INSIDE the effort dir → the plain in-effort rel path in
  backticks (openable by containment);
- an artifact outside the effort but inside the project folder →
  ``/artifact/<pid>?path=<forward-slash rel from the project folder>``;
- a lane job → ``/report/<pid>/<lane>/<job_id>``.

Durability/idempotence (property gates, journal 0080): the append happens
under :data:`paths.WRITE_LOCK` via a UNIQUE-named temp file + fsync +
``os.replace`` (the WinError-5 record-race lesson, 2026-08-07); an exact or
whitespace-variant (what, where) already present is a no-op with reason
``'dup'``. :func:`register` NEVER raises — a failure is returned as a reason
(the hooks journal it as the payload ``{register: written|dup|<reason>}`` on
the existing ``deliverable-pinned`` event, so a silent no-op is auditable).

Stdlib only.
"""
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

import paths as _paths

#: THE header contract (one source: steward_campaign.read_deliverables docstring).
HEADER = "| What | Where | Date | Step |"
HEADER_SEP = "|---|---|---|---|"
REGISTER_NAME = "DELIVERABLES.md"

#: The campaign marker file — a dir carrying it is the effort of record.
CAMPAIGN_MARKER = "ECGBERHT.md"


def _norm_cell(text) -> str:
    """Normalize a cell value: collapse whitespace; '|' would tear the pipe
    table, so it is replaced (the honest minimum, never dropped silently)."""
    return " ".join(str(text or "").replace("|", "/").split())


def effort_dir_for(run_folder, project_folder) -> str:
    """The effort of record for a run: the run's target folder when it (or a
    parent up to the project folder) carries ``ECGBERHT.md`` — i.e. the
    campaign dir — else the project root. Never walks above the project
    folder; a run folder outside it resolves to the project root."""
    proot = str(project_folder or run_folder or "")
    if not run_folder:
        return proot
    try:
        proj_real = os.path.realpath(proot)
        d = os.path.realpath(str(run_folder))
        if not (d == proj_real or d.startswith(proj_real + os.sep)):
            return proot
        while True:
            if os.path.isfile(os.path.join(d, CAMPAIGN_MARKER)):
                return d
            if d == proj_real:
                return proot
            parent = os.path.dirname(d)
            if not parent or parent == d:
                return proot
            d = parent
    except OSError:
        return proot


def where_for(effort_dir, project_folder, pid, *, abs_path=None, lane=None,
              job_id=None) -> str:
    """The Where cell for one artifact — one of the three openable forms (see
    module docstring). Returns ``""`` when nothing resolves (an artifact
    outside the project folder is honestly not linkable; the caller's
    :func:`register` then no-ops with a reason)."""
    if lane and job_id:
        return "/report/%s/%s/%s" % (quote(str(pid), safe=""),
                                     quote(str(lane), safe=""),
                                     quote(str(job_id), safe=""))
    if not abs_path:
        return ""
    try:
        real = os.path.realpath(str(abs_path))
        eff_real = os.path.realpath(str(effort_dir)) if effort_dir else ""
        # The backticked in-effort form only for a file that EXISTS — the
        # parser (read_deliverables) opens an in-effort path by containment
        # + isfile, so emitting it for a recorded-but-absent doc would mint
        # a dead Where; such a doc falls through to the /artifact route.
        if eff_real and (real == eff_real
                         or real.startswith(eff_real + os.sep)) \
                and os.path.isfile(real):
            rel = os.path.relpath(real, eff_real).replace(os.sep, "/")
            return "`%s`" % rel
        proj_real = os.path.realpath(str(project_folder)) if project_folder \
            else ""
        if proj_real and real.startswith(proj_real + os.sep):
            rel = os.path.relpath(real, proj_real).replace(os.sep, "/")
            return "/artifact/%s?path=%s" % (quote(str(pid), safe=""),
                                             quote(rel, safe="/"))
    except (OSError, ValueError):
        pass
    return ""


def active_step(effort_dir, hint=None) -> str:
    """The Step cell: the hint (a commission record's step id/name) wins; else
    the step whose ``status == 'active'`` in
    ``steward_campaign.read_map(effort_dir)['steps']``, rendered as its
    1-BASED INDEX (what the outline's stepDeliverables matches by number);
    empty when there is no map / no active step. A hint that names a map step
    by ID is likewise rendered as that step's 1-based index — the outline
    matches a Step cell by number or name fragment, never by id, so a raw id
    would land the row under no step; a hint the map doesn't know stays
    verbatim. Never raises."""
    h = _norm_cell(hint)
    try:
        from steward_cockpit import steward_campaign as _campaign
        steps = (_campaign.read_map(str(effort_dir)) or {}).get("steps") or []
        if h:
            for i, s in enumerate(steps, start=1):
                if h.lower() == str((s or {}).get("id") or "").strip().lower():
                    return str(i)
            return h
        for i, s in enumerate(steps, start=1):
            if (s or {}).get("status") == "active":
                return str(i)
    except Exception:
        pass
    return h


def _existing_rows(text):
    """(what, where) of every existing data row, whitespace-normalized."""
    rows = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-", " ", ":"} \
                or cells[0].lower() == "what":
            continue
        rows.append((_norm_cell(cells[0]), _norm_cell(cells[1])))
    return rows


def register(effort_dir, what, where, *, date=None, step=None,
             project_folder=None) -> dict:
    """Append ONE row to ``<effort_dir>/DELIVERABLES.md`` — idempotent, locked,
    atomic, never raises.

    Whitespace is normalized; an exact (what, where) already on file is a
    no-op ``{'written': False, 'reason': 'dup'}``. Otherwise the row is
    appended under :data:`paths.WRITE_LOCK` via a UNIQUE-named temp file +
    ``os.replace``, minting the header when the file is absent. ``date``
    defaults to today; ``step`` (a hint — a step id/name) wins over the map's
    active step (see :func:`active_step`). ``project_folder`` is accepted for
    call-site symmetry with :func:`where_for` (the Where is resolved by the
    caller). A failure is returned as ``{'written': False, 'reason': ...}``
    for the hook to journal — never an exception up a finishing run."""
    try:
        what_n = _norm_cell(what)
        where_n = _norm_cell(where)
        if not what_n or not where_n:
            return {"written": False, "reason": "empty-what-or-where"}
        d = Path(str(effort_dir))
        # Managed publication belongs to the roadmap spine. Legacy hooks must
        # not append a parallel row or silently announce completion.
        import json
        ledger = d / "roadmap.json"
        if ledger.is_file():
            try:
                state = json.loads(ledger.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {"written": False, "reason": "backing-store-unreadable"}
            if any(e.get("kind") == "refinement_update" for e in state.get("roadmap_events", [])):
                return {"written": False, "reason": "managed-refinement-update-required"}
        target = d / REGISTER_NAME
        with _paths.WRITE_LOCK:
            d.mkdir(parents=True, exist_ok=True)
            text = ""
            if target.is_file():
                text = target.read_text(encoding="utf-8", errors="replace")
                if (what_n, where_n) in _existing_rows(text):
                    return {"written": False, "reason": "dup"}
            else:
                text = HEADER + "\n" + HEADER_SEP + "\n"
            if text and not text.endswith("\n"):
                text += "\n"
            row = "| %s | %s | %s | %s |\n" % (
                what_n, where_n,
                _norm_cell(date) or time.strftime("%Y-%m-%d"),
                active_step(effort_dir, hint=step))
            fd, tmp = tempfile.mkstemp(prefix=".deliverables-", suffix=".tmp",
                                       dir=str(d))
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                    fh.write(text + row)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, target)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        return {"written": True, "reason": "written"}
    except Exception as exc:
        return {"written": False,
                "reason": ("%s: %s" % (type(exc).__name__, exc))[:200]}


# ── The reading target (execution minimum item 2, 2026-10-07) ────────────────
# ONE function says how a product is read. Every surface that offers a product - the dialogue's receipt line,
# Deliverables, Next steps - takes its link from here, so the three can never disagree. A product with nothing that
# renders yet (a deck with no PDF companion) gets no Read link: "preparing a reading copy", never a dead page.

_RENDERED = {".md", ".markdown", ".txt"}
_INLINE = {".pdf", ".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
_OFFICE_VIEW = {".docx", ".xlsx"}
_DOWNLOAD = {".docx", ".pptx", ".xlsx", ".zip", ".ics", ".csv", ".json"}


def project_and_rel(folder):
    """(project id, forward-slash rel of ``folder`` inside it) for the innermost registered project holding the
    folder; (None, None) when no registered project holds it. Never raises."""
    try:
        import rnd_registry
        here = Path(folder).resolve()
        best = None
        for p in rnd_registry.list_projects(include_archived=True, include_future=True, include_retired=False):
            fp = p.get("folder_path")
            if not fp:
                continue
            root = Path(fp).resolve()
            if (here == root or root in here.parents) and (best is None or len(str(root)) > len(str(best[1]))):
                best = (p.get("id"), root)
        if best is None:
            return None, None
        return best[0], ("" if here == best[1] else here.relative_to(best[1]).as_posix())
    except Exception:
        return None, None


def _file_url(pid, effort_rel, rel_path, file_hash=None, **extra):
    q = [("pid", pid), ("dir", effort_rel), ("path", rel_path)]
    if file_hash:
        q.append(("hash", file_hash))
    q.extend((k, v) for k, v in extra.items())
    return "/api/steward/deliverable-file?" + "&".join(
        "%s=%s" % (k, quote(str(v or ""), safe="")) for k, v in q)


def reading_target(product, *, pid, effort_rel, effort_dir=None):
    """How John reads one product version: ``{"read": url|None, "download": url|None, "preparing": bool}``.

    ``product`` is a register item (``path`` relative to the effort, or a classified ``route``; managed items carry
    ``open_path`` / ``hash``). Markdown opens formatted (``render=1``); PDF/HTML/images open as they are; Word and
    Excel open in the text preview with a download; a PowerPoint deck is readable only through its PDF companion (a
    sibling PDF of the same name, or the ledger's visual companion) - without one it is ``preparing``. Every value in
    the URL is encoded, so a path with spaces or parentheses survives."""
    out = {"read": None, "download": None, "preparing": False}
    route = (product or {}).get("route")
    if route:
        out["read"] = str(route)
        return out
    rel = str((product or {}).get("open_path") or (product or {}).get("path") or "").replace(chr(92), "/").strip()
    if not rel or not pid:
        return out
    if effort_dir is not None and not (Path(effort_dir) / rel).is_file():
        return out
    file_hash = (product or {}).get("hash") if (product or {}).get("managed") else None
    ext = os.path.splitext(rel)[1].lower()
    if ext in _DOWNLOAD:
        out["download"] = _file_url(pid, effort_rel, rel, file_hash, download="1")
    if ext in _RENDERED:
        out["read"] = _file_url(pid, effort_rel, rel, file_hash, render="1")
    elif ext in _INLINE:
        out["read"] = _file_url(pid, effort_rel, rel, file_hash)
    elif ext in _OFFICE_VIEW:
        out["read"] = _file_url(pid, effort_rel, rel, file_hash, view="1")
    elif ext == ".pptx":
        sibling = rel[: -len(ext)] + ".pdf"
        if (product or {}).get("visual_companion"):
            out["read"] = _file_url(pid, effort_rel, rel, file_hash, view="1")
        elif effort_dir is not None and (Path(effort_dir) / sibling).is_file():
            out["read"] = _file_url(pid, effort_rel, sibling)
        else:
            out["preparing"] = True
    return out
