"""Auth-enumeration for the telemetry-resume plan's NEW endpoints — W3.

Cites the North Star amendment 'Endpoint auth rule' (LOCKED): every NEW endpoint
this plan introduces follows the token-auth pattern; a test enumerates the new
routes against the auth table and asserts 401-BEFORE-SUBSTANCE for each. **Adding
a new endpoint outside this enumeration without extending the test is a BLOCKER.**

W3 introduces the Layer-1 narration data GET route. Later waves APPEND their new
routes to :data:`NEW_ROUTES` (W4 ledger/capture inspection, W5 rollup, W6
orientation-job trigger) — the enumeration is the single, growing citation target.

Pure-Python + one throwaway server on an OS-assigned free port; never :8777, never
the real ~/.anchor store.
"""
import importlib
import json
import threading
import urllib.error
import urllib.request

import paths
import route_table as rt

# ── The plan's NEW endpoints (append here as later waves add routes) ─────────
# (method, path, sample query) — the sample query carries the required params so
# the authed probe reaches the handler (proving auth passed), while the tokenless
# probe must 401 BEFORE any substance is produced.
NEW_ROUTES = [
    ("GET", "/api/rnd/session_narration",
     "pid=proj-x&lane=research&session=sess-x"),
]


def _get(url, token=None):
    # A token-gated GET authenticates via the standard Authorization header
    # (the ``_term_token_ok`` header path — browsers use ``?token=`` on
    # EventSource/WS; a header works for scripted GETs).
    req = urllib.request.Request(url, method="GET")
    if token is not None:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_new_routes_declared_token_authed_in_route_table():
    """Every W3+ new route is declared in the route table as a token-authed,
    migrated GET row (default-deny by construction)."""
    declared = {(r.method, r.pattern): r for r in rt.ROUTES}
    for method, path, _q in NEW_ROUTES:
        assert (method, path) in declared, (
            f"{method} {path} must have a declared route_table row "
            "(absence for a new endpoint is a BLOCKER)")
        row = declared[(method, path)]
        assert row.auth == rt.AUTH_TOKEN, f"{path} must be token-authed"
        assert row.migrated and row.handler, f"{path} must be migrated"


def test_new_routes_401_before_substance(monkeypatch, tmp_path):
    """With a token configured, each new route rejects a tokenless GET with 401
    BEFORE producing any substance, and serves an authed GET."""
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)
    server = gui.make_server("127.0.0.1", 0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        for method, path, q in NEW_ROUTES:
            url = f"{base}{path}?{q}"
            # No token → 401 BEFORE substance (the body is the unauthorized error,
            # never a narration payload).
            code, raw = _get(url)
            assert code == 401, f"{path} must 401 a tokenless GET"
            body = json.loads(raw or b"{}")
            assert body.get("ok") is False
            assert "narration" not in body, (
                f"{path} leaked substance before auth")
            # Bad token → 401.
            code, _ = _get(url, token="nope")
            assert code == 401, f"{path} must 401 a bad token"
            # Correct token → NOT 401 (auth passed; the handler runs and returns
            # the deterministic floor even for an unknown project).
            code, raw = _get(url, token="tok-123")
            assert code != 401, f"{path} must serve an authed GET"
            body = json.loads(raw or b"{}")
            assert body.get("ok") is True
            assert "narration" in body
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
