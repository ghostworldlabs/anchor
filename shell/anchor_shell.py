"""Anchor as a program on PUTER: one WebView2 window around static/app.html (PLAN v2.2 section 3.3,
Skill Foundry/planning/anchor-app-shell-2026-09-29).

Not product code: it runs from its own venv (%LOCALAPPDATA%/anchor-shell/.venv, pywebview + pywin32) and is
not on the ship list. The service is unchanged; this only opens a window onto it.

  - its own taskbar identity (AppUserModelID) and the new anchor as its icon, so it is not "Python";
  - a persistent WebView2 profile, so the token is pasted once and the 30-day cookie is kept;
  - downloads allowed; app links (ms-word:, mailto:) and other sites go to Windows / the default browser;
  - one instance: a second launch brings the open window forward;
  - Ctrl + / Ctrl - / Ctrl 0 (and Ctrl + wheel) zoom the whole window, remembered for the next start. pywebview
    turns WebView2's own browser keys off (F5 would reload the app and lose the open tiles), so the pages catch
    just these keys (static/app.js, app-frame.js) and call zoom() here;
  - its own title bar (his ask, 2026-10-03): the window has no Windows caption; the page draws the bar (the anchor,
    the tiles, the one/two-pane toggle, minimize/maximize/close). The bar's empty parts carry CSS app-region: drag,
    which WebView2 (non-client region support) turns into a real caption - smooth moves, snap, double-click to
    maximize. Windows 11 rounds the corners; the window's outer edges resize it.

Usage:  pythonw shell/anchor_shell.py [--url URL]
"""
import argparse
import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

APP_ID = "GhostWorldLabs.Anchor"
TITLE = "Anchor"
DEFAULT_URL = "http://127.0.0.1:8777/static/app.html"
ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "vendor" / "brand" / "anchor-icon.ico"
PROFILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "anchor-shell" / "profile"
ZOOM_FILE = PROFILE.parent / "zoom.txt"
ZOOM_STEPS = (0.5, 0.67, 0.75, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)   # Chrome's ladder

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.SendMessageW.restype = wintypes.LPARAM
user32.LoadImageW.restype = wintypes.HANDLE
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                wintypes.UINT)
comctl32 = ctypes.WinDLL("comctl32")
SUBCLASSPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
                                  ctypes.c_size_t, ctypes.c_size_t)
comctl32.SetWindowSubclass.argtypes = (wintypes.HWND, SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t)
comctl32.DefSubclassProc.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
comctl32.DefSubclassProc.restype = ctypes.c_ssize_t
ERROR_ALREADY_EXISTS = 183
EDGE = 5                                                # px of the window's edge that resize it


def bring_forward_existing():
    """A second launch: find the open Anchor window, restore it and bring it to the front."""
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        if user32.IsIconic(hwnd):                       # restore only a minimised window; a maximised one stays
            user32.ShowWindow(hwnd, 9)                  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


def set_window_icon(hwnd, path):
    """WM_SETICON with the anchor (the window frame and Alt+Tab); the taskbar uses the shortcut's icon."""
    LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x0080
    for which, size in ((1, 256), (0, 32)):             # ICON_BIG, ICON_SMALL
        h = user32.LoadImageW(None, str(path), IMAGE_ICON, size, size, LR_LOADFROMFILE)
        if h:
            user32.SendMessageW(hwnd, WM_SETICON, which, h)


def _own_title_bar(hwnd):
    """Run on the window's UI thread. A resizable window (snap, minimize animation, Windows 11 rounded corners) whose
    caption and frame nobody draws: WM_NCCALCSIZE gives the page the whole window; WM_NCHITTEST answers the outer
    edges with the resize codes; the bar's app-region is the caption."""
    GWL_STYLE, WS_THICKFRAME, WS_MAXIMIZEBOX, WS_MINIMIZEBOX, WS_SYSMENU = -16, 0x40000, 0x10000, 0x20000, 0x80000
    WM_NCCALCSIZE, WM_NCHITTEST = 0x0083, 0x0084
    style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX | WS_SYSMENU)
    codes = {(1, 0, 1, 0): 13, (0, 1, 1, 0): 14, (1, 0, 0, 1): 16, (0, 1, 0, 1): 17,
             (1, 0, 0, 0): 10, (0, 1, 0, 0): 11, (0, 0, 1, 0): 12, (0, 0, 0, 1): 15}

    def proc(h, msg, wp, lp, _id, _ref):
        if msg == WM_NCCALCSIZE and wp:
            if user32.IsZoomed(h):                      # maximised: keep the page inside the screen
                rc = ctypes.cast(lp, ctypes.POINTER(wintypes.RECT)).contents
                pad = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)   # SM_CXFRAME + SM_CXPADDEDBORDER
                rc.left += pad
                rc.top += pad
                rc.right -= pad
                rc.bottom -= pad
            return 0
        if msg == WM_NCHITTEST and not user32.IsZoomed(h):
            x, y = ctypes.c_short(lp & 0xFFFF).value, ctypes.c_short((lp >> 16) & 0xFFFF).value
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            key = (int(x < r.left + EDGE), int(x >= r.right - EDGE), int(y < r.top + EDGE), int(y >= r.bottom - EDGE))
            if key in codes:
                return codes[key]                       # HTLEFT/RIGHT/TOP/BOTTOM and the corners
        return comctl32.DefSubclassProc(h, msg, wp, lp)

    cb = SUBCLASSPROC(proc)
    _own_title_bar.keep = cb                           # the callback must outlive this call
    comctl32.SetWindowSubclass(hwnd, cb, 1, 0)
    pref = ctypes.c_int(2)                              # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), 4)
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0027)    # SWP_FRAMECHANGED | NOMOVE | NOSIZE | NOZORDER


def _read_zoom():
    try:
        z = float(ZOOM_FILE.read_text(encoding="utf-8").strip())
        return z if ZOOM_STEPS[0] <= z <= ZOOM_STEPS[-1] else 1.0
    except (OSError, ValueError):
        return 1.0


class HostApi:
    """What the page may ask of the program: zoom(step) (+1 / -1 along the ladder, 0 = 100 %) and
    window_control(act) for the bar's own minimize / maximize-restore / close."""

    def __init__(self):
        self._window = None
        self._level = _read_zoom()

    def bind(self, window):
        self._window = window

    def zoom(self, step):
        step = int(step)
        if step == 0:
            z = 1.0
        else:
            i = min(range(len(ZOOM_STEPS)), key=lambda k: abs(ZOOM_STEPS[k] - self._level))
            z = ZOOM_STEPS[max(0, min(len(ZOOM_STEPS) - 1, i + (1 if step > 0 else -1)))]
        self.apply(z)
        try:
            ZOOM_FILE.write_text(str(z), encoding="utf-8")
        except OSError:
            pass
        return z

    def apply(self, z=None):
        self._level = self._level if z is None else z
        level = self._level
        try:
            from System import Action                   # pythonnet, pywebview's WinForms backend
            form = self._window.native
            form.Invoke(Action(lambda: setattr(form.browser.webview, "ZoomFactor", level)))
        except Exception as exc:                         # zoom is a convenience; the window works without it
            print("zoom:", exc, file=sys.stderr)

    def window_control(self, act):
        w = self._window
        if act == "minimize":
            w.minimize()
        elif act == "maximize":
            if user32.IsZoomed(int(str(w.native.Handle))):
                w.restore()
            else:
                w.maximize()
        elif act == "close":
            w.destroy()

    def _frame(self):
        """WebView2's app-region support on; True when it was off (the page then reloads once so it takes)."""
        from System import Action
        form = self._window.native
        changed = []

        def on_ui():                                    # WebView2 is touched on its own thread only
            settings = form.browser.webview.CoreWebView2.Settings
            if not settings.IsNonClientRegionSupportEnabled:
                settings.IsNonClientRegionSupportEnabled = True
                changed.append(True)

        form.Invoke(Action(on_ui))
        return bool(changed)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args(argv)

    mutex = kernel32.CreateMutexW(None, False, "Local\\" + APP_ID)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        bring_forward_existing()
        return 0

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)

    import webview                                      # the venv's; imported after the single-instance check
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True   # ms-word:, mailto:, other sites -> Windows
    PROFILE.mkdir(parents=True, exist_ok=True)

    host = HostApi()
    win = webview.create_window(TITLE, args.url, js_api=host, width=1500, height=950, min_size=(420, 500),
                                background_color="#0f141c", frameless=True, easy_drag=False)
    host.bind(win)

    def on_loaded():
        host.apply()                                    # the remembered zoom
        try:
            if host._frame():
                win.evaluate_js("location.reload()")
        except Exception as exc:                         # without it the bar does not move the window
            print("app-region:", exc, file=sys.stderr)

    win.events.loaded += on_loaded

    def on_shown():
        try:
            hwnd = int(str(win.native.Handle))
            set_window_icon(hwnd, ICON)
            from System import Action, EventHandler
            import System.Windows.Forms as WinForms
            form = win.native

            def inset(*_):                              # the page stops EDGE px short of the edges, so the edges
                pad = 0 if user32.IsZoomed(hwnd) else EDGE      # are the window's and resize it (not when maximised)
                if form.Padding.Left != pad:
                    form.Padding = WinForms.Padding(pad)

            def on_ui():
                _own_title_bar(hwnd)
                inset()
                form.Resize += EventHandler(inset)

            form.Invoke(Action(on_ui))
        except Exception as exc:                         # the window still works with the defaults
            print("frame:", exc, file=sys.stderr)

    win.events.shown += on_shown
    webview.start(private_mode=False, storage_path=str(PROFILE))
    kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    sys.exit(main())
