"""Wave 2 (D4): token-auth middleware on mutating /api/* POSTs.

- The pure predicate `paths.auth_ok` is exercised directly.
- One integration POST against a throwaway server on an OS-assigned free port
  proves: no/bad token -> 401, correct token -> 200. Read endpoints stay open.

Never touches port 8777 or the live `anchor` service.
"""
import importlib
import json
import threading
import urllib.error
import urllib.request

import paths


def test_auth_ok_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    importlib.reload(paths)
    assert paths.auth_ok(None) is True
    assert paths.auth_ok("anything") is True


def test_auth_ok_enforced_when_set(monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    importlib.reload(paths)
    assert paths.auth_ok("s3cret") is True
    assert paths.auth_ok("wrong") is False
    assert paths.auth_ok(None) is False


def test_auth_ok_ignores_blank_token(monkeypatch):
    monkeypatch.setenv("ANCHOR_TOKEN", "   ")
    importlib.reload(paths)
    # Blank == unset == disabled.
    assert paths.auth_ok(None) is True


def _post(url, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token is not None:
        req.add_header("X-Anchor-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_integration_mutating_post_requires_token(monkeypatch, tmp_path):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_TOKEN", "tok-123")
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    # Seed a task so /api/done has something real to act on.
    gui.DASHBOARD_MD.write_text(
        "# Dashboard\n- [ ] integration-task — Priority: 2 — [academic]\n",
        encoding="utf-8",
    )

    server = gui.make_server("127.0.0.1", 0)  # OS-assigned free port
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"

        # No token -> 401
        code, _ = _post(base + "/api/done", {"text": "integration-task"})
        assert code == 401

        # Bad token -> 401
        code, _ = _post(base + "/api/done", {"text": "integration-task"}, token="nope")
        assert code == 401

        # GET read endpoint is NOT gated.
        with urllib.request.urlopen(base + "/api/status", timeout=5) as r:
            assert r.status == 200

        # Correct token -> 200 + the mutation actually happened.
        code, raw = _post(base + "/api/done", {"text": "integration-task"}, token="tok-123")
        assert code == 200
        body = json.loads(raw)
        assert body.get("ok") is True
        assert "[x]" in gui.DASHBOARD_MD.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
