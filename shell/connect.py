"""Where the Anchor program finds Anchor (PLAN v1.2 D1, Skill Foundry/planning/anchor-every-device-2026-10-03).

The program is only a window; the service lives on the owner's mother ship. On that computer it uses the local
copy (127.0.0.1); anywhere else it uses the owner's saved address, kept in %LOCALAPPDATA%/anchor-shell/settings.json.
Only https:// is accepted for another machine. When the address does not answer, the window shows a plain page
saying so, with Retry and Change address - never a browser error.
"""
import html
import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

LOCAL = "http://127.0.0.1:8777"
EXAMPLE = "https://mother-ship.example"
APP_PATH = "/static/app.html"


def settings_file(data_dir):
    return Path(data_dir) / "settings.json"


def load_address(data_dir):
    try:
        return json.loads(settings_file(data_dir).read_text(encoding="utf-8")).get("address") or ""
    except (OSError, ValueError):
        return ""


def save_address(data_dir, address):
    f = settings_file(data_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    current["address"] = address
    f.write_text(json.dumps(current, indent=2), encoding="utf-8")


def normalize(text):
    """The typed address -> 'https://host[:port]', or (None, why). Only this device may use http."""
    t = (text or "").strip()
    if not t:
        return None, "Type your mother ship's address."
    if "://" not in t:
        t = "https://" + t
    parts = urlsplit(t)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None, "That doesn't look like an address. Example only: " + EXAMPLE
    if parts.hostname.rstrip(".") == urlsplit(EXAMPLE).hostname:
        return None, "That is only an example. Type your own mother ship's address."
    local = parts.hostname in ("127.0.0.1", "localhost", "::1")
    if parts.scheme == "http" and not local:
        return None, "Anchor on another machine must be reached over https (Tailscale Serve), not http."
    return "%s://%s" % (parts.scheme, parts.netloc), None


def reachable(address, timeout=5.0):
    """True when the address answers with Anchor's app page."""
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(address + APP_PATH, timeout=timeout, context=ctx) as r:
            return r.status == 200 and b"ANCHOR" in r.read(4096).upper()
    except (urllib.error.URLError, OSError, ValueError, ssl.SSLError):
        return False


def choose(data_dir, override=""):
    """The address to open now: an explicit one, local Anchor, else the saved one ('' = ask for an address)."""
    if override:
        return override
    if reachable(LOCAL, timeout=1.5):
        return LOCAL
    return load_address(data_dir)


# ---------- the two pages the program shows itself (no service needed) ----------
_STYLE = """<style>
:root{color-scheme:dark}*{box-sizing:border-box}html,body{height:100%;margin:0}
body{background:#0f141c;color:#e6ebf2;font:15px/1.5 "Segoe UI Variable Text","Segoe UI",system-ui,sans-serif;display:grid;grid-template-rows:44px 1fr}
#bar{display:flex;align-items:center;gap:10px;padding-left:12px;background:#0b1018;border-bottom:1px solid #2b3546;-webkit-app-region:drag;app-region:drag}
#bar b{font-weight:600;font-size:13px;color:#98a4b8}#bar .sp{flex:1}
#bar button{-webkit-app-region:no-drag;app-region:no-drag;background:none;border:0;color:#98a4b8;width:46px;align-self:stretch;cursor:pointer;font-size:14px}
#bar button:hover{background:#1f2735;color:#e6ebf2}#bar button.c:hover{background:#c42b1c;color:#fff}
main{display:grid;place-items:center;padding:24px;min-width:0}.card{width:min(520px,100%);min-width:0;background:#161d29;border:1px solid #2b3546;border-radius:12px;padding:26px 28px}
h1{font-size:20px;margin:0 0 6px}p{color:#98a4b8;margin:0 0 16px}
label{display:block;margin-bottom:6px}.example{font-size:13px;margin:8px 0 0}
input{width:100%;font:15px "Segoe UI",system-ui;padding:9px 11px;border-radius:8px;border:1px solid #3a4658;background:#0f141c;color:#e6ebf2}
input:focus{outline:2px solid #e0a836;outline-offset:1px}
.row{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}
.btn{font:600 14px "Segoe UI",system-ui;padding:8px 16px;border-radius:8px;border:1px solid #3a4658;background:#1e2634;color:#e6ebf2;cursor:pointer}
.btn.go{background:#e0a836;border-color:#e0a836;color:#1a1a1a}.msg{min-height:22px;margin-top:12px;color:#e0a836;font-size:14px}
code{font:13px Consolas,monospace;color:#e9d9a8;overflow-wrap:anywhere}
.msg{overflow-wrap:anywhere}
</style>"""

_BAR = """<div id="bar"><b>Anchor</b><span class="sp"></span>
<button onclick="pywebview.api.window_control('minimize')" title="Minimize">&#8212;</button>
<button onclick="pywebview.api.window_control('maximize')" title="Maximize">&#9744;</button>
<button class="c" onclick="pywebview.api.window_control('close')" title="Close">&#10005;</button></div>"""

_SCRIPT = """<script>
function show(t){document.getElementById('msg').textContent=t||'';}
function act(name,arg){show('Connecting\\u2026');pywebview.api[name](arg).then(function(r){if(r)show(r);});}
</script>"""


def setup_page(prefill="", message=""):
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Anchor</title>%s</head><body>%s<main><div class="card">
<h1>Where is your Anchor?</h1>
<p>Enter the address of your own mother ship, the computer that runs Anchor for you. From another device, use its HTTPS address. Anchor remembers it after you connect.</p>
<label for="addr">Mother ship address</label>
<input id="addr" value="%s" aria-describedby="address-example" spellcheck="false" autofocus onkeydown="if(event.key==='Enter')act('connect',this.value)">
<p class="example" id="address-example">Example only: <code>%s</code>. Use your own address.</p>
<div class="row"><button class="btn go" onclick="act('connect',document.getElementById('addr').value)">Connect</button></div>
<div class="msg" id="msg">%s</div></div></main>%s</body></html>""" % (
        _STYLE, _BAR, html.escape(prefill or "", quote=True), html.escape(EXAMPLE), html.escape(message), _SCRIPT)


def offline_page(address):
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Anchor</title>%s</head><body>%s<main><div class="card">
<h1>Anchor isn't reachable right now</h1>
<p>This computer can't reach your selected mother ship at <code>%s</code>. Check that Tailscale is on here, and that your mother ship is awake and Anchor is running there.</p>
<div class="row"><button class="btn go" onclick="act('retry')">Retry</button>
<button class="btn" onclick="act('change_address')">Change address</button></div>
<div class="msg" id="msg"></div></div></main>%s</body></html>""" % (_STYLE, _BAR, html.escape(address), _SCRIPT)
