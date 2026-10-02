"""The Anchor program's host (shell/anchor_shell.py), PLAN v2.2 section 3.3: the identity and icon it wears,
and that it stays off the stdlib product (its third-party imports live only under shell/)."""
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the host is a Windows program")


def test_the_host_wears_his_anchor_and_its_own_taskbar_identity():
    sys.path.insert(0, str(ROOT / "shell"))
    import anchor_shell
    assert anchor_shell.ICON == ROOT / "vendor" / "brand" / "anchor-icon.ico"
    assert anchor_shell.APP_ID == "GhostWorldLabs.Anchor"
    assert anchor_shell.DEFAULT_URL.endswith("/static/app.html") and ":8777" in anchor_shell.DEFAULT_URL
    data = anchor_shell.ICON.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    sizes = {data[6 + 16 * i] or 256 for i in range(count)}
    assert (reserved, kind) == (0, 1) and {32, 256} <= sizes      # the frame's small and big icons exist


def test_the_host_is_not_product_code():
    ship = (ROOT / "dist_manifest.txt").read_text(encoding="utf-8") if (ROOT / "dist_manifest.txt").is_file() else ""
    assert "shell/" not in ship and "anchor_shell" not in ship
    for py in (ROOT / "shell").glob("*.py"):
        assert "import webview" not in py.read_text(encoding="utf-8").split("def main", 1)[0] or py.name != "anchor_shell.py"
