"""Where the Anchor program finds Anchor (shell/connect.py, every-device PLAN v1.2 D1): https only off the device,
the saved address, PUTER's own copy first, a plain page when nothing answers."""
import http.server
import socketserver
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shell"))
import connect  # noqa: E402


@pytest.mark.parametrize("typed, want", [
    ("gwl-server.tailb49f65.ts.net", "https://gwl-server.tailb49f65.ts.net"),
    ("https://gwl-server.tailb49f65.ts.net/static/app.html", "https://gwl-server.tailb49f65.ts.net"),
    ("  https://gwl-server.tailb49f65.ts.net/  ", "https://gwl-server.tailb49f65.ts.net"),
    ("http://127.0.0.1:8777", "http://127.0.0.1:8777"),
    ("http://localhost:8777/x", "http://localhost:8777"),
])
def test_addresses_he_might_type_become_one_origin(typed, want):
    assert connect.normalize(typed) == (want, None)


@pytest.mark.parametrize("typed", ["", "http://gwl-server.tailb49f65.ts.net", "ftp://x", "https://"])
def test_bad_addresses_are_refused_with_a_reason(typed):
    address, why = connect.normalize(typed)
    assert address is None and why


def test_the_address_is_remembered(tmp_path):
    assert connect.load_address(tmp_path) == ""
    connect.save_address(tmp_path, "https://example.ts.net")
    assert connect.load_address(tmp_path) == "https://example.ts.net"


class _App(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = b"<!doctype html><title>Anchor</title>" if self.path == connect.APP_PATH else b"no"
        self.send_response(200 if self.path == connect.APP_PATH else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_reachable_means_anchors_app_page_answers():
    srv = socketserver.TCPServer(("127.0.0.1", 0), _App)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert connect.reachable("http://127.0.0.1:%d" % srv.server_address[1])
    finally:
        srv.shutdown()
        srv.server_close()
    assert not connect.reachable("http://127.0.0.1:9", timeout=1)


def test_choose_prefers_an_explicit_address_then_puters_own_then_the_saved_one(tmp_path, monkeypatch):
    connect.save_address(tmp_path, "https://saved.ts.net")
    assert connect.choose(tmp_path, "https://given.ts.net") == "https://given.ts.net"
    monkeypatch.setattr(connect, "reachable", lambda a, timeout=5.0: a == connect.LOCAL)
    assert connect.choose(tmp_path) == connect.LOCAL
    monkeypatch.setattr(connect, "reachable", lambda a, timeout=5.0: False)
    assert connect.choose(tmp_path) == "https://saved.ts.net"


def test_the_pages_carry_the_window_buttons_and_escape_what_they_show():
    page = connect.setup_page('x" onmouseover="bad')
    assert "window_control('close')" in page and 'onmouseover="bad' not in page
    assert "Retry" in connect.offline_page("https://a.ts.net") and "Change address" in connect.offline_page("https://a.ts.net")
