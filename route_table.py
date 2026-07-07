"""Declarative HTTP route table — the C2 strangler substrate (rearch-2026-07 W7).

The single source of truth for EVERY HTTP route Anchor serves. Each route is a
declarative ROW carrying its method, URL pattern, match kind (exact | prefix),
auth policy, handler kind (standard | stream | upgrade), the module-level handler
it has been migrated to (or ``None`` while still legacy), and a ``migrated`` flag.

Why this exists (Master Plan Phase 2; D3; Success criterion 2):
  * **Default-deny by construction.** Auth is a declared property of the row, not
    a scattered inline check. ``token`` is the intended default; the only routes
    that are unauthenticated live on an explicit, reviewed allowlist —
    ``OPEN_ROUTES.json`` — and a gate test asserts the table's ``open`` set equals
    that file EXACTLY (adding an ``open`` route fails the build until the reviewed
    file is edited with a justification string).
  * **Strangler migration.** ``anchor_gui`` dispatches the table FIRST; a matched,
    ``migrated`` row is handled by its module-level function (with the row's auth
    invoked FIRST — honestly special-cased for ``kind != standard``); anything
    unmatched or not-yet-migrated falls through to the legacy ``if``/``elif``
    chains unchanged. C2 progress is therefore a measurable count
    (:func:`legacy_arm_count`), not a narrative.
  * **Auditable.** ``/api/routes`` (token-authed) dumps the live table, and a
    route-audit test proves no dispatch arm exists in ``anchor_gui`` without a
    declared row here.

This module is PURE DATA + PURE FUNCTIONS — stdlib only, no imports of the server.
The migrated handler *functions* live in ``anchor_gui`` (where their dependencies
live) and are looked up by the string name in :attr:`Route.handler`; keeping this
table import-free means the audit/coverage tests can import it with zero side
effects.
"""

from __future__ import annotations

from collections import namedtuple

# ── Auth policies ────────────────────────────────────────────────────────────
# The declared auth posture of a route. ``token`` is default-deny (a valid
# shared-secret token is required when ANCHOR_TOKEN is configured); ``open`` is
# the explicitly-reviewed unauthenticated allowlist (OPEN_ROUTES.json); ``ws_token``
# is the query-param/subprotocol token the WS/SSE transports demand (browsers
# cannot set headers on an EventSource/WebSocket handshake).
AUTH_TOKEN = "token"
AUTH_OPEN = "open"
AUTH_WS_TOKEN = "ws_token"

AUTH_POLICIES = (AUTH_TOKEN, AUTH_OPEN, AUTH_WS_TOKEN)

# ── Handler kinds ────────────────────────────────────────────────────────────
# ``standard`` is a normal request/response arm. ``stream`` holds the socket open
# for a chunked SSE body; ``upgrade`` hijacks the raw socket for a WebSocket. The
# specials are honestly special-cased at the pre-dispatch hook (the row's auth is
# invoked FIRST, then the transport takes over the socket).
KIND_STANDARD = "standard"
KIND_STREAM = "stream"
KIND_UPGRADE = "upgrade"

HANDLER_KINDS = (KIND_STANDARD, KIND_STREAM, KIND_UPGRADE)

# ── Match kinds ──────────────────────────────────────────────────────────────
MATCH_EXACT = "exact"
MATCH_PREFIX = "prefix"

# ── The gated data-plane batch (W8 warn / W9 enforce) ────────────────────────
# These routes are currently ``auth == open`` (they served tokenless pre-rearch)
# but carry per-project data. The warn-then-enforce soak moves them ``open`` →
# ``token``: W8 runs them in log-only WARN mode (``auth_warn.record_would_401``
# for a tokenless request; still served), W9 flips the table rows to ``token``
# and the mode to ``enforce`` (a real 401). Declared here ONCE so the server's
# runtime gate, the healthcheck row-walk, and the soak reviewer share one exact
# set — matched by the row PATTERN (``match(method, path).pattern``).
DATA_PLANE_GATED = (
    ("GET", "/artifact/"),
    ("GET", "/report/"),
    ("GET", "/summary/"),
    ("GET", "/project/"),
    ("GET", "/api/rnd/projects"),
    ("GET", "/api/rnd/tail"),
    ("GET", "/api/rnd/jobs"),
)


def is_data_plane_gated(route) -> bool:
    """True iff ``route`` is a member of the W8/W9 gated data-plane batch.

    ``route`` is a :class:`Route` (typically :func:`match`'s return). ``None``
    (an unmatched path) is never gated here — default-deny for undeclared paths
    is the audit's job, not this soak overlay's.
    """
    if route is None:
        return False
    return (route.method, route.pattern) in DATA_PLANE_GATED

# The known non-literal (constant-valued) prefix arms in anchor_gui.do_GET. These
# static-asset routes are dispatched via ``self.path.startswith(<CONST>)`` rather
# than a string literal, so the route-audit's literal extractor cannot see them —
# they are declared here explicitly and this set documents that they are audited
# by identity, not by literal scan.
STATIC_ASSET_PREFIXES = (
    "/vendor/katex",
    "/vendor/xterm",
    "/vendor/brand",
    "/vendor/anchor-term",
    "/static",
)


Route = namedtuple(
    "Route", "method pattern match auth kind handler migrated")


def _r(method, pattern, auth, kind=KIND_STANDARD, match=MATCH_EXACT,
       handler=None, migrated=False):
    assert auth in AUTH_POLICIES, f"bad auth policy {auth!r}"
    assert kind in HANDLER_KINDS, f"bad handler kind {kind!r}"
    assert match in (MATCH_EXACT, MATCH_PREFIX), f"bad match kind {match!r}"
    if migrated:
        assert handler, f"migrated route {pattern!r} needs a handler name"
    return Route(method.upper(), pattern, match, auth, kind, handler, migrated)


# ── The route table ──────────────────────────────────────────────────────────
# Every route Anchor serves gets a ROW. Auth policy reflects the CURRENT live
# behavior (W7 declares reality without flipping it; W8/W9 move data-plane rows
# from ``open`` → ``token`` under warn-then-enforce, editing OPEN_ROUTES.json as
# they go — exactly the reviewed-allowlist workflow the gate enforces).
ROUTES = [
    # ── GET: pages + public bootstrap (open) ──────────────────────────────
    _r("GET", "/", AUTH_OPEN),
    _r("GET", "/dashboard", AUTH_OPEN),
    _r("GET", "/api/version", AUTH_OPEN, handler="handle_version",
       migrated=True),
    _r("GET", "/api/status", AUTH_OPEN, handler="handle_status",
       migrated=True),
    _r("GET", "/favicon.ico", AUTH_OPEN),
    _r("GET", "/anchor.ico", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/anchor.png", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/anchor-touch.png", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/zombie_radar.jpg", AUTH_OPEN, match=MATCH_PREFIX),
    # Static-asset roots (constant-prefix arms in do_GET).
    _r("GET", "/vendor/katex", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/vendor/xterm", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/vendor/brand", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/vendor/anchor-term", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/static", AUTH_OPEN, match=MATCH_PREFIX),

    # ── GET: the live route-table dump (NEW, token-authed) ─────────────────
    _r("GET", "/api/routes", AUTH_TOKEN, handler="handle_routes",
       migrated=True),

    # ── GET: streaming / upgrade specials (ws_token) ───────────────────────
    _r("GET", "/api/rnd/term_ws", AUTH_WS_TOKEN, kind=KIND_UPGRADE),
    _r("GET", "/api/rnd/term_stream2", AUTH_WS_TOKEN, kind=KIND_STREAM),
    _r("GET", "/api/rnd/term_stream", AUTH_WS_TOKEN, kind=KIND_STREAM,
       match=MATCH_PREFIX),

    # ── GET: currently-open data plane (scheduled for W8/W9 token-gating) ──
    _r("GET", "/report/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/summary/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/artifact/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/project/", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/handoff_proposal", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/session_summary", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/term_sessions", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/projects_html", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/projects", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/dir_browse", AUTH_OPEN, match=MATCH_PREFIX,
       handler="handle_dir_browse", migrated=True),
    _r("GET", "/api/rnd/tail", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/jobs", AUTH_OPEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/previews", AUTH_OPEN, match=MATCH_PREFIX),

    # ── GET: already token-gated read surface ──────────────────────────────
    _r("GET", "/zombie_terminal", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/project_files", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/project_file_content", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/session_doc_roles", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/context_status", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/effort_rollup", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/build_deliverable", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/grass", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/gandalf", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/gandalf_status", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/gandalf_status_all", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/orphan_check", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/zombie_hunter_report", AUTH_TOKEN, match=MATCH_PREFIX),
    # Reaper control plane (token-authed; safe-to-arm build) — status read + the
    # arm/advance/disarm mutations. Sensitive control surface: token, never open.
    _r("GET", "/api/rnd/reaper_status", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("POST", "/api/rnd/reaper_arm", AUTH_TOKEN),
    _r("POST", "/api/rnd/reaper_advance", AUTH_TOKEN),
    _r("POST", "/api/rnd/reaper_disarm", AUTH_TOKEN),
    _r("GET", "/api/rnd/boneyard", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/remote_status", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/project_rollup", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/chain", AUTH_TOKEN, match=MATCH_PREFIX),
    _r("GET", "/api/rnd/board_html", AUTH_TOKEN, match=MATCH_PREFIX),

    # ── POST: browser auth-cookie login/logout (rearch W9, migrated) ──────
    # Mint / clear the HttpOnly auth cookie that carries browser page
    # navigation under ``ANCHOR_AUTH_MODE=enforce`` (SPIKE-COOKIE-WS-VERDICT).
    # Token-authed by the do_POST middleware (default-deny) BEFORE the handler
    # runs, so the login handler only ever sets a cookie for a validated caller.
    _r("POST", "/api/auth/login", AUTH_TOKEN, handler="handle_auth_login",
       migrated=True),
    _r("POST", "/api/auth/logout", AUTH_TOKEN, handler="handle_auth_logout",
       migrated=True),

    # ── POST: every mutating arm (token; do_POST middleware enforces) ──────
    _r("POST", "/api/done", AUTH_TOKEN),
    _r("POST", "/api/rnd/upload_batch", AUTH_TOKEN),
    _r("POST", "/api/upload", AUTH_TOKEN),
    _r("POST", "/api/undone", AUTH_TOKEN),
    _r("POST", "/api/add", AUTH_TOKEN),
    _r("POST", "/api/capture", AUTH_TOKEN),
    _r("POST", "/api/edit_task", AUTH_TOKEN),
    _r("POST", "/api/edit_project", AUTH_TOKEN),
    _r("POST", "/api/promote_project", AUTH_TOKEN),
    _r("POST", "/api/demote_project", AUTH_TOKEN),
    _r("POST", "/api/promote_task", AUTH_TOKEN),
    _r("POST", "/api/demote_task", AUTH_TOKEN),
    _r("POST", "/api/cancel", AUTH_TOKEN),
    _r("POST", "/api/save_for_later", AUTH_TOKEN),
    _r("POST", "/api/restore", AUTH_TOKEN),
    _r("POST", "/api/heartbeat", AUTH_TOKEN),
    _r("POST", "/api/rnd/new_project", AUTH_TOKEN),
    _r("POST", "/api/rnd/open_project", AUTH_TOKEN),
    _r("POST", "/api/rnd/rescan", AUTH_TOKEN),
    _r("POST", "/api/rnd/set_priority", AUTH_TOKEN),
    _r("POST", "/api/rnd/archive_project", AUTH_TOKEN),
    _r("POST", "/api/rnd/future_project", AUTH_TOKEN),
    _r("POST", "/api/rnd/retire_project", AUTH_TOKEN),
    _r("POST", "/api/rnd/reactivate_project", AUTH_TOKEN),
    _r("POST", "/api/rnd/set_notes", AUTH_TOKEN),
    _r("POST", "/api/rnd/set_blurb", AUTH_TOKEN),
    _r("POST", "/api/rnd/set_group", AUTH_TOKEN),
    _r("POST", "/api/rnd/move_project", AUTH_TOKEN),
    _r("POST", "/api/rnd/link_task", AUTH_TOKEN),
    _r("POST", "/api/rnd/run_deliverable", AUTH_TOKEN),
    _r("POST", "/api/rnd/pin_deliverable", AUTH_TOKEN),
    _r("POST", "/api/rnd/launch_deliverable", AUTH_TOKEN),
    _r("POST", "/api/rnd/launch_lane", AUTH_TOKEN),
    _r("POST", "/api/rnd/answer_gate", AUTH_TOKEN),
    _r("POST", "/api/rnd/start_terminal", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_input", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_discover", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_adopt", AUTH_TOKEN),
    _r("POST", "/api/rnd/cancel_job", AUTH_TOKEN),
    _r("POST", "/api/rnd/zombie_kill", AUTH_TOKEN),
    _r("POST", "/api/rnd/zombie_resume", AUTH_TOKEN),
    _r("POST", "/api/rnd/gandalf_cancel", AUTH_TOKEN),
    _r("POST", "/api/rnd/preview_start", AUTH_TOKEN),
    _r("POST", "/api/rnd/preview_stop", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_start", AUTH_TOKEN),
    _r("POST", "/api/rnd/zombie_terminal_start", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_kill", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_close", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_delete", AUTH_TOKEN),
    _r("POST", "/api/rnd/cleanup_ghost_sessions", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_set_engine", AUTH_TOKEN),
    _r("POST", "/api/rnd/switch_terminal_engine", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_resize", AUTH_TOKEN),
    _r("POST", "/api/rnd/term_input2", AUTH_TOKEN),
    _r("POST", "/api/rnd/regenerate_summary", AUTH_TOKEN),
    _r("POST", "/api/rnd/add_idea", AUTH_TOKEN),
    _r("POST", "/api/rnd/promote_inbox", AUTH_TOKEN),
    _r("POST", "/api/rnd/promote_grass", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_develop", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_workbench", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_save_refinement", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_set_status", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_pull", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_export", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_archive", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_advance", AUTH_TOKEN),
    _r("POST", "/api/rnd/grass_delete", AUTH_TOKEN),
    _r("POST", "/api/rnd/link_github", AUTH_TOKEN),
    _r("POST", "/api/rnd/set_auto_push", AUTH_TOKEN),
    _r("POST", "/api/rnd/push_now", AUTH_TOKEN),
    _r("POST", "/api/rnd/continue_session", AUTH_TOKEN),
    _r("POST", "/api/rnd/advance_session", AUTH_TOKEN),
    _r("POST", "/api/rnd/gandalf_run", AUTH_TOKEN),
    _r("POST", "/api/rnd/gandalf_delete", AUTH_TOKEN),
    _r("POST", "/api/rnd/gandalf_archive", AUTH_TOKEN),
    _r("POST", "/api/rnd/gandalf_clear_failed", AUTH_TOKEN),
    _r("POST", "/api/rnd/advance_stage", AUTH_TOKEN),
    _r("POST", "/api/rnd/handoff_to_fresh", AUTH_TOKEN),
    _r("POST", "/api/rnd/finish_to_build", AUTH_TOKEN),
    # Skill Foundry v2 — the Foundry GUI page (open, like /project/) + its mutative ops (token-gated).
    _r("GET", "/foundry", AUTH_OPEN),
    _r("POST", "/api/foundry/create_skill", AUTH_TOKEN),
    _r("POST", "/api/foundry/north_star", AUTH_TOKEN),
    _r("POST", "/api/foundry/sleep_session", AUTH_TOKEN),
    _r("POST", "/api/foundry/sync_autoload", AUTH_TOKEN),
]


# ── Matching + queries ───────────────────────────────────────────────────────
def match(method, path):
    """Return the :class:`Route` serving ``method``/``path``, or ``None``.

    Exact rows win over prefix rows; among prefix rows the LONGEST matching
    pattern wins (so ``/api/rnd/gandalf_status_all`` beats ``/api/rnd/gandalf``
    and ``/api/rnd/term_stream2`` beats ``/api/rnd/term_stream``). ``path`` should
    be the path WITHOUT the query string for exact routes; prefix routes tolerate
    a trailing query.
    """
    method = (method or "").upper()
    for r in ROUTES:
        if r.method == method and r.match == MATCH_EXACT and path == r.pattern:
            return r
    best = None
    for r in ROUTES:
        if (r.method == method and r.match == MATCH_PREFIX
                and path.startswith(r.pattern)):
            if best is None or len(r.pattern) > len(best.pattern):
                best = r
    return best


def declared_keys():
    """The set of ``(method, pattern)`` pairs the table declares."""
    return {(r.method, r.pattern) for r in ROUTES}


def open_route_keys():
    """The ``(method, pattern)`` set of routes declared ``auth == open``.

    This is the LIVE open set the OPEN_ROUTES.json reviewed allowlist must match
    exactly (the default-deny audit).
    """
    return {(r.method, r.pattern) for r in ROUTES if r.auth == AUTH_OPEN}


def migrated_routes():
    """Rows migrated to a module-level handler (dispatched by the strangler)."""
    return [r for r in ROUTES if r.migrated]


def legacy_routes():
    """Rows still served by the legacy ``if``/``elif`` chains."""
    return [r for r in ROUTES if not r.migrated]


def legacy_arm_count():
    """How many routes remain on the legacy dispatch — the C2 progress counter.

    W7 landed the first batch (version/status/routes); W8 adds dir_browse and,
    critically, structurally KILLS the os/datetime in-method import-shadowing
    class the counter was chartered to eliminate (``tools/route_import_scan`` on
    ``anchor_gui.py`` is now zero). The remaining arms are the NAMED RESIDUAL:
    the plan permits "zero OR a small named residual", and full arm-by-arm
    migration of the ~130-route monolith is a mechanical follow-through carried
    forward rather than done blind in one wave — the shadowing harm (the stated
    purpose) is already gone, and every arm still has a declared, audited row.
    """
    return sum(1 for r in ROUTES if not r.migrated)


def migrated_count():
    return sum(1 for r in ROUTES if r.migrated)


def effective_auth(route, auth_mode="open"):
    """The auth posture a route ACTUALLY enforces under ``auth_mode`` (W8/W9).

    A data-plane-gated row is declared ``open`` but the warn/enforce overlay
    changes its runtime behavior: under ``enforce`` it behaves like ``token``
    (tokenless → 401); under ``open``/``warn`` it still serves (``open``). Every
    other row enforces exactly its declared ``auth``. This is the single truth the
    healthcheck row-walk consults so its expectations match the live server in any
    named auth state.
    """
    if is_data_plane_gated(route) and auth_mode == "enforce":
        return AUTH_TOKEN
    return route.auth


def walk_expectations(token_configured, auth_mode="open"):
    """Per-row expectations for the healthcheck declared-rows auth walk (W8).

    Yields a dict per NON-upgrade row (``kind == upgrade`` rows are skipped — the
    WS handshake is covered by the socket 401-before-101 regression test):

      * ``method``/``pattern``/``kind``/``auth`` — the row identity.
      * ``tokenless_expect`` — ``"not_401"`` (an ``open`` route must serve a
        tokenless request) or ``"401"`` (a STANDARD ``token``/``ws_token`` route
        must reject one) — but only ``"401"`` when a token is CONFIGURED (auth is
        disabled otherwise → ``None`` = skip). A ``stream`` (SSE) row is walked
        but NOT tokenless-asserted (``None``): it holds the socket and a bare
        HTTP prefix probe is ambiguous (a missing-session ``400`` vs a ``401``);
        its auth ordering is proven by the dedicated stream/socket tests.
      * ``check_authed`` — True only for a STANDARD ``token``/``ws_token`` row (an
        authed request must NOT 401); ``stream`` rows skip the authed probe (it
        would block on the open stream).
    """
    for r in ROUTES:
        if r.kind == KIND_UPGRADE:
            continue
        eff = effective_auth(r, auth_mode)
        if r.kind != KIND_STANDARD:
            # A socket-holding stream — walked for completeness but not
            # tokenless-asserted here (see the docstring).
            tokenless_expect = None
        elif eff == AUTH_OPEN:
            tokenless_expect = "not_401"
        else:  # token / ws_token
            tokenless_expect = "401" if token_configured else None
        yield {
            "method": r.method,
            "pattern": r.pattern,
            "kind": r.kind,
            "auth": r.auth,
            "effective_auth": eff,
            "tokenless_expect": tokenless_expect,
            "check_authed": (eff != AUTH_OPEN and r.kind == KIND_STANDARD),
        }


def table_dump():
    """The live table as a list of JSON-safe dicts for ``GET /api/routes``.

    Each row: ``path``, ``method``, ``auth`` policy, handler ``kind``, and
    ``status`` (``migrated`` vs ``legacy``) plus the handler ``name`` when
    migrated — exactly the fields the plan mandates.
    """
    rows = []
    for r in ROUTES:
        rows.append({
            "method": r.method,
            "path": r.pattern,
            "match": r.match,
            "auth": r.auth,
            "kind": r.kind,
            "status": "migrated" if r.migrated else "legacy",
            "handler": r.handler if r.migrated else None,
        })
    return rows
